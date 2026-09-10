# J-Core L2 Unified Coherent Cache — Specification (v2)

**Status:** Draft v0.2 (coherent, multi-core, parameterized address width)
**Scope:** Unified L2 cache controller for the J32, J32-OOO, J32-FM, and J64 product points. Sits between per-core L1-I/L1-D caches and the main memory interface. Parameterized by capacity, associativity, line size, bank count, **core count**, and **physical-address width**. Acts as the directory / snoop filter for L1-D coherence and hosts per-line locks that implement CAS.L atomicity.
**Supersedes:** `archive/l2-v1-single-core-spec.md` (single-core, non-coherent, bus-lock atomicity).
**Companion docs:**
- [glossary.md](../glossary.md) — product points (§3), FGMT (§4), memory terms (§5), coherence and atomicity (§6).
- [ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md) — OoO core hosting the L1s talking to this L2; §10 (atomics), §11 (cache hierarchy), §14 (SMP), §15 (gate budget).
- [fgmt/dual-fgmt-proposal.md](../fgmt/dual-fgmt-proposal.md) — earlier MSI-on-L1 sketch; §5.4 (coherence proposal), §5.5 (per-thread atomics requirement).
- [mmu/design-spec.md](../mmu/design-spec.md) — §4.6 lazy TLB shootdown depends on L1-D coherence delivered by this spec.
- [hypervisor/linux-spec.md](../hypervisor/linux-spec.md) — §8 SMP vCPU migration assumes coherent memory.

---

## Changelog

- **v0.4** (2026-09-09, Wave-3 **C2e**): Added §16.2 (`P-R1`–`P-R8`), §16.3 (what partitioning does
  not close — each remaining channel marked closed, mitigated or accepted, two of them found by
  this task), §16.4
  (`P-E1`–`P-E5`) and §22.1b. **Narrowed §16.1's "Why this closes the channel" to the occupancy
  channel** and deleted the justification for unrestricted hits, which was wrong in two ways.
  Corrected §16.1's sizing sentence, which licensed a way split `P-R1` does not allow. `movca.l` no
  longer allocates a partly undefined line (`P-R7`). Decided that `ocbi`/`ocbp`/`ocbwb` stay
  user-mode, because per §17.5's own table none of them evicts from the L2 and the "Flush+Reload
  across the partition" premise does not hold.
- **v0.3** (2026-08): Added §16.1, way partitioning by trust domain. The L2's single shared tag and data arrays make it a cross-tenant channel that the CPU specs' core-granular tenancy rules cannot reach; way partitioning closes it for ~200 gates, and is also what makes gang scheduling ([hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)) affordable, since the alternative is a ~655 µs full-L2 flush per tenant switch.
- **v0.2** (2026-05-26): Rewrite for SMP coherence (MSI directory at L2), per-L2-line lock replacing bus-lock CAS.L, parameterized `ADDR_WIDTH ∈ {32, 40}`. Tiered presentation (T0/T1/T2). Pre-2006 prior art consolidated.
- **v0.1** (archived as `archive/l2-v1-single-core-spec.md`): Single-core, non-coherent, locked-access-bypass CAS.L. Carried forward unchanged for T0; bypass path removed at T1.

---

## 0. Tier Structure

This specification is presented in **three tiers**, each adding functionality on top of the previous one. Tier tags appear on every section heading to indicate the tier(s) where the content applies.

| Tier | Name              | Coherence | Atomicity                 | `ADDR_WIDTH` | Product points          | Status   |
|------|-------------------|-----------|---------------------------|--------------|-------------------------|----------|
| T0   | Single-core L2    | none      | locked-access bypass *or* line-lock | 32           | J32 (optional)          | Recast from v1 |
| T1   | Coherent multi-core | MSI directory at L2 | per-L2-line lock (mandatory) | 32     | J32-OOO (mandatory), J32-FM (mandatory) | New      |
| T2   | Wide-address      | T1 + 40-bit PA | T1 line-lock              | 40           | J64 (mandatory)         | New      |

Per-tier rules:

- **T0** is the v1 design with one small change: locked-access bypass is preserved as the default, but the new `LOCKED` tag-array bit is wired in unconditionally so the same RTL can target T1. T0 deployments leave the snoop fabric and directory bits depopulated.
- **T1** mandates the directory bits, the snoop fabric, per-line `LOCKED`, and the L1-D MSI state machine. CAS.L now uses `GetM-Locked` (L2-line lock) instead of bus-lock; locked-access bypass is removed for J32-OOO and J32-FM (the path is retained only for the J2 → J32 transition's compatibility shim, see §6.4).
- **T2** parameterizes the address width to 40 bits for J64 physical addresses. All tag, MSHR, eviction-buffer, and mcl-interface address fields scale with `ADDR_WIDTH`. T2 otherwise reuses T1 unchanged.

Where a section applies to all tiers it is tagged **`[T0/T1/T2]`**. Where it is tier-specific it is tagged with the introducing tier(s).

---

## 1. Scope and Relationship to the CPU Cores `[T0/T1/T2]`

The L2 sits below per-core L1 caches and above the memory-clock-layer SDRAM interface. Externally-visible properties are defined by the consuming CPU spec ([j32ooo-spec.md §11.3](../ooo/j32ooo-spec.md)): 128 KB / 8-way / 32-byte lines / write-back / pseudo-LRU / inclusive of L1 / 6–8 cycle hit latency (baseline; parameterizable). This document specifies the **implementation**: state machine, banking, tag and data arrays, miss handling, **coherence directory**, **line-lock state machine**, BRAM mapping, and VHDL entity interface.

The L2 is built on the existing J-core memory-clock-layer (`cache/dcache_mcl.vhm`) for SDRAM access. The CPU clock domain stops at the L2; the L2 synchronizes with the slower SDRAM clock through the existing CDC mechanism.

**Inclusion** of L1 contents in L2 is retained from v1, and is now **load-bearing** — the directory is exact iff inclusion holds.

The dcache lock state machine (`cache/dcache_ccl.vhm` — `RLOCK1`, `RLOCK2`, `WUNCA1`, `WUNCA2`, `NEGLCK`) was the bus-lock origin in v1. **Under T1 it is repurposed**: the same state names drive a request to L2 that acquires an L2-line lock instead of asserting `db_lock`. The J2 in-order core continues to use the bus-lock form unchanged (J2 has no L2); J32-OOO and J32-FM use the line-lock form. See §6.

---

## 2. Functional Summary `[T0/T1/T2]`

The L2 is a **unified, inclusive, write-back, banked, non-blocking, coherent** cache:

- **Unified**: serves all per-core L1-I (read-only) and L1-D clients from a single tag and data array. **The L1-D write policy is tier-dependent** and this bullet used to state only the T0 half: write-through at `[T0]`, write-back under MSI at `[T1/T2]` where a line held `M` is dirty in the L1-D and reaches the L2 on `Wb`. §17.1 owns the policy; [decisions/0007](../decisions/0007-l1d-write-policy-under-msi.md) is the decision and states the DMA consequence, which is the part that changes at T1.
- **Inclusive of L1**: every line cached in any L1-I or L1-D is also present in L2. L2 evictions force corresponding L1 invalidations. Inclusion is the directory's correctness invariant under T1/T2.
- **Write-back**: dirty lines stay in L2 until evicted; only writebacks go to SDRAM.
- **Banked**: 4 banks by address bits (configurable), parallel servicing of non-conflicting requests.
- **Non-blocking**: up to `NUM_MSHRS` outstanding misses; subsequent misses to in-flight addresses merge.
- **Pseudo-LRU replacement**: tree-LRU per set.
- **Directory / snoop filter at L2 (T1/T2)**: each L2 line carries a per-L1-D presence vector. L2 originates coherence traffic to L1-Ds on read/write misses, evictions, and downgrade requests.
- **Per-L2-line lock (T1/T2)**: each L2 line carries a `LOCKED` bit plus owner `{core_id, thread_id}`, used by CAS.L for atomicity within the coherence protocol.

The previously-listed v1 property "Locked accesses bypass" is **retained only for T0 deployments** and the J2-era compatibility path; it is removed for T1/T2.

---

## 3. Prior Art (pre-2006) `[T0/T1/T2]`

Per [glossary §2](../glossary.md), every mechanism here cites pre-2006 published prior art. New entries (T1/T2) appear at the bottom of the table.

| Mechanism                                                | Tier     | Citation                                                                                              |
| -------------------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------- |
| Non-blocking cache with MSHRs                            | T0/T1/T2 | Kroft, "Lockup-Free Instruction Fetch/Prefetch Cache Organization" (ISCA 1981)                        |
| Set-associative on-die L2                                | T0/T1/T2 | DEC Alpha 21164 (1995, 96 KB / 3-way)                                                                 |
| Backside dedicated L2                                    | T0/T1/T2 | PowerPC 750 (1997)                                                                                    |
| Banked cache for port-conflict reduction                 | T0/T1/T2 | Sohi & Franklin (ISCA 1991)                                                                           |
| Pseudo-LRU (tree-LRU)                                    | T0/T1/T2 | Intel P6 (1995); widely documented prior art                                                          |
| Inclusive multilevel cache                               | T0/T1/T2 | Baer & Wang, "On the inclusion properties for multi-level cache hierarchies" (ISCA 1988)              |
| Write-back, write-allocate L2                            | T0/T1/T2 | Hennessy & Patterson 3rd ed. (2003), Ch. 5                                                            |
| Tree-pLRU update logic                                   | T0/T1/T2 | Smith, "Cache memories" (ACM Comp. Surveys 1982)                                                      |
| Bus-lock atomicity (legacy J2 compat path only)          | T0       | IBM S/360 (1964); preserved in J2 CAS.L (`cache/dcache_ccl.vhm`)                                      |
| **MSI cache coherence protocol**                         | T1/T2    | Papamarcos & Patel, "A low-overhead coherence solution for multiprocessors with private cache memories" (ISCA 1984) |
| MSI design textbook treatment                            | T1/T2    | Hennessy & Patterson 3rd ed. (2003), Ch. 6                                                            |
| **Directory-based coherence at shared L2**               | T1/T2    | SGI Origin 2000: Laudon & Lenoski, "The SGI Origin: A ccNUMA Highly Scalable Server" (ISCA 1997)      |
| Directory-based scalable shared memory                   | T1/T2    | Stanford DASH: Lenoski et al., "The Directory-Based Cache Coherence Protocol for the DASH Multiprocessor" (ISCA 1990) |
| Snoop filter at shared cache                             | T1/T2    | Iftode et al. on snoop filtering (HPCA 1996)                                                          |
| **Per-line lock co-existing with MESI/MSI fabric**       | T1/T2    | SPARC v9 `CASA` over UltraSPARC II MESI fabric (1997); UltraSPARC III (2001); MIPS R4000 LL/SC over MESI (1991); Hennessy & Patterson 3rd ed. Ch. 5–6 |
| LL/SC primitive (line-reservation atomicity)             | T1/T2    | DEC Alpha 21064 (1992); MIPS R4000 (1991); IBM POWER `lwarx`/`stwcx` (1993)                           |
| Forward-progress timeout on lock acquisition             | T1/T2    | Alpha 21264 lock-flag clearing on exceptions (1998)                                                   |
| Per-thread atomic-group qualification under MT          | T1/T2    | UltraSPARC T1 / Niagara strand-tagged LD/STC (Kongetira et al., IEEE Micro 2005)                      |
| Broadcast snoop bus for ≤4 caches                        | T1/T2    | SGI Challenge, MIPS R4400 (1994); Sun UE-1 (1995)                                                     |
| Ring interconnect for larger coherent fabrics            | T1 ext.  | IBM POWER4 (2001) elastic interface ring; Sun Niagara crossbar/ring (2005)                            |
| Parameterized cache-line address width                   | T2       | DEC Alpha 21264 (1998, 44-bit PA); MIPS R10000 (1996, 40-bit PA); SPARC v9 (1994, 41–44-bit PA)        |

There is no post-2006 citation in this specification. Any contributor adding a mechanism must extend this table with a pre-2006 source, or the mechanism is dropped (glossary §2).

---

## 4. Configuration Parameters `[T0/T1/T2]`

The L2 controller is a parameterized VHDL entity. The baseline matches the J32-OOO spec; smaller variants are supported for staged bring-up; wider variants are supported for J64.

| Generic            | Type    | Baseline | Range                          | Tier | Notes                                  |
| ------------------ | ------- | --------:| ------------------------------ | ---- | -------------------------------------- |
| `L2_SIZE_KB`       | integer |     128  | 32, 64, 128, 256               | all  | Total L2 capacity                      |
| `L2_WAYS`          | integer |       8  | 2, 4, 8, 16                    | all  | Associativity                          |
| `L2_LINE_BYTES`    | integer |      32  | 32, 64                         | all  | Line size                              |
| `NUM_BANKS`        | integer |       4  | 1, 2, 4, 8                     | all  | Banking factor                         |
| `NUM_MSHRS`        | integer |       4  | 2, 4, 8                        | all  | Outstanding miss capacity              |
| `WAY_SELECT_PIPE`  | boolean |   false  | true (timing escape hatch)     | all  | Adds 1 cycle to L2 hit latency         |
| `ADDR_WIDTH`       | integer |      32  | **32 or 40**                   | T0/T1=32; T2=40 | Physical-address width      |
| `NUM_CORES`        | integer |       1  | 1, 2, 4                        | T0=1; T1/T2≥2 | Number of L1-D clients (cores)       |
| `NUM_THREADS_PER_CORE` | integer | 1   | 1, 2                           | all  | FGMT contexts per core; used to size lock-owner field |
| `LOCK_TIMEOUT_CYC` | integer |    256  | 64–4096                        | T1/T2 | Forward-progress backstop (cycles)    |
| `SNOOP_FABRIC`     | enum    | broadcast | broadcast, ring                | T1/T2 | `ring` reserved for future ≥6-core configs (see §5.4) |
| `NUM_DOMAINS`      | integer |       1  | 1–8                            | T1/T2 | L2 trust domains of §16.1, **including the host domain `H`**. `1` is the unpartitioned build. Sizes `L2WAYMASK`, `L2DRRQ` and the `P-R3` reservation *(added post-F, 2026-09-09: `P-R3`'s elaboration constraint was written over this name and over a miss-capacity generic spelled differently from §4's, and neither name was in this table)* |

Derived quantities for the T1 baseline (`L2_SIZE_KB=128, L2_WAYS=8, L2_LINE_BYTES=32, NUM_BANKS=4, NUM_CORES=2, NUM_THREADS_PER_CORE=2, ADDR_WIDTH=32`):

```
NUM_SETS         = L2_SIZE_KB * 1024 / (L2_WAYS * L2_LINE_BYTES) = 512
SETS_PER_BANK    = NUM_SETS / NUM_BANKS                          = 128
OFFSET_BITS      = log2(L2_LINE_BYTES)                           = 5
BANK_BITS        = log2(NUM_BANKS)                               = 2
INDEX_BITS       = log2(SETS_PER_BANK)                           = 7
TAG_BITS         = ADDR_WIDTH - INDEX_BITS - BANK_BITS - OFFSET_BITS
                 = 32 - 7 - 2 - 5 = 18   (T1)
                 = 40 - 7 - 2 - 5 = 26   (T2, J64)
LINE_WORDS       = L2_LINE_BYTES / 4                             = 8 (32-bit words)
DIR_VEC_BITS     = NUM_CORES                                      = 2 (T1 baseline)
LOCK_OWNER_BITS  = log2(NUM_CORES) + log2(NUM_THREADS_PER_CORE)   = 1 + 1 = 2 (T1 baseline)
```

**Staged bring-up recommendation**: start with `L2_SIZE_KB=64, L2_WAYS=4, NUM_BANKS=2, NUM_CORES=1` for first integration; this is effectively T0. Bring up the coherence path on `NUM_CORES=2` after T0 is stable. Bring up `ADDR_WIDTH=40` last (T2) after T1 is stable.

---

## 5. Top-Level Block Diagram `[T0/T1/T2]`

```
                  ┌──────────────────────────┐     ┌──────────────────────────┐
                  │       Core 0             │     │       Core 1   (T1/T2)   │
                  │ ┌──────┐  ┌──────┐  ┌─┐  │     │ ┌──────┐  ┌──────┐  ┌─┐  │
                  │ │ L1-I │  │ L1-D │  │S│  │     │ │ L1-I │  │ L1-D │  │S│  │
                  │ └──┬───┘  └──┬───┘  └┬┘  │     │ └──┬───┘  └──┬───┘  └┬┘  │
                  └────┼─────────┼────────┼──┘     └────┼─────────┼────────┼──┘
                       │         │        │snoop        │         │        │snoop
                       ▼         ▼        ▲             ▼         ▼        ▲
                      ┌───────────────────────────────────────────────────────┐
                      │                L2 Arbiter + Bank Steering             │
                      │     (incoming req mux; snoop fabric driver)           │
                      └───┬─────────────────┬─────────────────┬─────────────┬─┘
                          ▼                 ▼                 ▼             ▼
                     ┌─────────┐       ┌─────────┐       ┌─────────┐   ┌─────────┐
                     │ Bank 0  │       │ Bank 1  │       │ Bank 2  │   │ Bank 3  │
                     │ Tag+Dir │       │ Tag+Dir │       │ Tag+Dir │   │ Tag+Dir │
                     │ Data    │       │ Data    │       │ Data    │   │ Data    │
                     │ pLRU    │       │ pLRU    │       │ pLRU    │   │ pLRU    │
                     │ LockSM  │       │ LockSM  │       │ LockSM  │   │ LockSM  │
                     └────┬────┘       └────┬────┘       └────┬────┘   └────┬────┘
                          └───────────┬─────┴───────────┬─────┴─────────────┘
                                      ▼                 ▼
                                ┌──────────┐      ┌──────────┐
                                │ MSHR     │      │ Writeback│
                                │ Pool     │      │  Queue   │
                                └─────┬────┘      └────┬─────┘
                                      └────────┬───────┘
                                               ▼
                                     ┌────────────────────┐
                                     │  Memory-Clock      │
                                     │  Layer (mcl)       │
                                     └─────────┬──────────┘
                                               ▼
                                            SDRAM
```

The "S" box on each core is the **snoop port** on its L1-D (already a first-class concept in `cache/dcache.vhd` — `sa`/`sy` of type `dcache_snoop_io_t`, see [dual-fgmt-proposal.md §3](../fgmt/dual-fgmt-proposal.md)). The L2 drives invalidations and downgrades through these ports. The directory bits stored alongside each L2 line tell the L2 *which* cores need a snoop, eliminating bus broadcasts for the common cases.

### 5.1 Bank steering `[T0/T1/T2]`

Each incoming request carries an address. Bits `address[OFFSET_BITS + INDEX_BITS .. OFFSET_BITS + INDEX_BITS + BANK_BITS - 1]` select the bank. For baseline that's `address[11:10]`. Requests to different banks proceed in parallel.

### 5.2 Snoop fabric `[T1/T2]`

For `NUM_CORES ≤ 4`, the snoop fabric is a **broadcast bus** driven by the L2: when L2 needs to invalidate, downgrade, or recall a line, it asserts the message on the broadcast bus tagged with the target core mask (sourced from the directory bits). Each core's L1-D snoop port listens only when its mask bit is set. The bus is 1-message-per-cycle; serialization at the L2 makes it conflict-free.

For `NUM_CORES ≥ 6`, broadcast scaling becomes the bottleneck. The reserved `SNOOP_FABRIC=ring` option will repurpose the existing `jcore-soc/components/ring_bus/` component as a coherence ring (see [dual-fgmt-proposal.md §3](../fgmt/dual-fgmt-proposal.md) for the same observation). Ring fabric design is **out of scope for this revision**.

### 5.3 Arbiter priority `[T1/T2]`

The L2 arbiter prioritizes in this order. Snoops are first because in-flight snoops block forward progress on remote cores.

1. **Snoop response from a remote L1-D** (e.g. a `WbResponse` carrying a Modified line back). Highest — fills MSHRs and unblocks waiters.
2. **Coherence-driven local action** at this bank (e.g. processing an inbound `GetM-Locked` that must hold the line in Modified for the requester). High.
3. **SDRAM fill response** being installed in the data array.
4. **L1-D writeback** (a Modified-line eviction from an L1-D arriving at L2).
5. **L1-D read/write miss** (regular GetS / GetM).
6. **L1-I read miss**.
7. **Prefetch fills** (lowest, can be dropped under contention).

The reordering vs v1: snoop traffic moves to the top because it can hold up a remote core in a stalling state (waiting on its own GetS); v1 had no snoops so the SDRAM fill was top.

**This order is a *class* priority and says nothing about which domain is served inside a class.**
Two domains issuing class-5 requests at the same bank are ordered by whatever the implementation
happens to do, and that ordering is a channel. §16.2 `P-R5` adds deficit round robin over domains
*within* each class, leaving the class order above exactly as it stands. It bounds the
interference rather than removing it — §16.3 rows 5 and 6.

---

## 6. Atomicity: CAS.L via L2-Line Lock `[T1/T2]`

This section defines the **per-L2-line lock** that replaces bus-lock for J32-OOO and J32-FM CAS.L. It is the most architecturally significant change in v2.

### 6.1 Motivation

Bus-lock CAS.L (v1) holds the SDRAM bus exclusive for the duration of read-modify-write. It does not compose with a coherent fabric: a bus-lock forces the *entire* memory system to serialize on a single critical section, defeating the throughput goal of coherence. The replacement is a line-grain lock that interlocks with the MSI protocol — a CAS.L acquires exclusive ownership of one L2 line without blocking unrelated traffic.

Prior art: SPARC v9 `CASA` over MESI (UltraSPARC II 1997, UltraSPARC III 2001); MIPS LL/SC over MESI (R4000 1991); per-line lock co-existing with coherence is discussed in Hennessy & Patterson 3rd ed. (2003) Ch. 5–6.

### 6.2 Lock state in the tag array `[T1/T2]`

Each L2 line gains three fields beyond v1:

| Field          | Bits                                | Meaning                                                       |
| -------------- | ----------------------------------: | ------------------------------------------------------------- |
| `LOCKED`       | 1                                   | This line is reserved by the listed owner; no other GetM proceeds. |
| `lock_owner`   | `LOCK_OWNER_BITS` (2 for baseline)  | `{core_id, thread_id}` tuple identifying who holds the lock.  |
| `lock_age`     | `log2(LOCK_TIMEOUT_CYC)` (8 for 256) | Free-running counter since lock was acquired; triggers timeout. |

`LOCK_OWNER_BITS` is `log2(NUM_CORES) + log2(NUM_THREADS_PER_CORE)` — for the T1 baseline that's 2 bits. For the FGMT requirement of [dual-fgmt-proposal.md §5.5](../fgmt/dual-fgmt-proposal.md), encoding the thread ID in the owner field is mandatory: a context switch to a different thread on the same core must not silently steal the lock.

### 6.3 Protocol

CAS.L expands to three uops in the J32-OOO decoder ([j32ooo-spec.md §10.2](../ooo/j32ooo-spec.md)). The line-lock protocol replaces the bus-lock interactions of uops 2 and 3:

1. **uop2 (locked load).** The L1-D issues a **`GetM-Locked(addr, owner)`** to L2. L2 accepts when:
   - The L2 tag array hit returns the addressed line.
   - The line's `LOCKED == 0`.
   - All other L1-D copies of this line are invalidatable (snoop drives Modified-holder to writeback, Shared-holders to Invalid).
   On success L2:
   - Sets `LOCKED=1`, `lock_owner={core_id, thread_id}`, `lock_age=0`.
   - Marks the line Modified in L1-D #{core_id} (via the directory; presence vector becomes a one-hot of `core_id`).
   - Returns the line data to L1-D.
   If `LOCKED==1` for a different `owner`, L2 NACKs the request; the L1-D retries (the LSQ holds the uop; the OoO core does not advance the atomic group).
2. **L1-D-local compare-and-swap.** The L1-D, holding the line in M state, performs the compare against the architectural register locally. On success it has the new value to install in M; on failure (T=0 in J-core CAS.L semantics) it has nothing to install.
3. **uop3 (conditional store + unlock).** L1-D issues **`Unlock(addr, owner [, new_data])`** to L2:
   - On compare-success: include `new_data`, which L2 merges into the data array (still M, dirty). L2 then sets `LOCKED=0`, clears `lock_owner`/`lock_age`.
   - On compare-fail: send `Unlock` with no data. L2 sets `LOCKED=0` only.
   In both cases L2 ACKs to the L1-D; the uop3 retires.

The L1-D's lock state machine reuses the v1 `RLOCK1/RLOCK2/WUNCA1/WUNCA2/NEGLCK` state names. The state semantics now drive the L2 messages above instead of `db_lock`.

### 6.4 Compatibility: J2 bus-lock world `[T0]`

J2 cores have no L2; CAS.L on J2 continues to use the existing bus-lock mechanism in `cache/dcache_ccl.vhm` and is **not affected** by this spec. J2 ships and stays shipped; the bus-lock path is preserved verbatim. Only J32-OOO and J32-FM (which have an L2) use the L2-line-lock path. J32 baseline (with optional L2) may use either: if `NUM_CORES=1` and the optional L2 is omitted, bus-lock continues; if the optional L2 is present, line-lock is used.

### 6.5 Forward-progress backstop `[T1/T2]`

`LOCK_TIMEOUT_CYC` (default 256 cycles) bounds how long a single CAS.L can hold a line locked. When `lock_age == LOCK_TIMEOUT_CYC`:

- L2 force-clears `LOCKED`, `lock_owner`, `lock_age`.
- L2 increments a `lock_timeout` PMU event counter.
- The L1-D that owned the lock observes its in-flight `Unlock` either:
  - succeed (if the unlock arrives ≤ the timeout) — normal path; or
  - return as a "lock-stolen" condition. In that case the L1-D treats uop3 as compare-fail (T=0) and proceeds.

The timeout is a backstop, not a normal mechanism. A normal CAS.L completes in 8–10 cycles end-to-end (§13.3); a 256-cycle window is ~25× headroom.

Software visibility: only via the PMU. There is no architectural exception. This matches Alpha's lock-flag clearing model (1998).

### 6.6 Per-thread qualification under FGMT `[T1/T2]`

The lock is qualified with `{core_id, thread_id}`, where `thread_id` is `log2(n_tc)` bits wide — **1 bit at `n_tc = 2` (J32-OOO, J32-FM), 2 bits at `n_tc = 4` (J32-LT, [ooo/j32lt-spec.md §8](../ooo/j32lt-spec.md))**. FGMT context switches between threads on the same core (every cycle) do **not** release a lock held by a sibling thread:

- Thread A on core 0 holds the line lock. A cycle later the front end picks thread B on core 0; B issues a memory op to the same line. Since B's `{core_id=0, thread_id=1}` ≠ A's `{core_id=0, thread_id=0}`, B's GetM (or GetS) is treated like a foreign request: L2 NACKs / stalls until A's Unlock arrives.
- L1-D within a single core must track *which* thread issued the locked load so its uop3 produces an Unlock with the matching owner field. Per-thread LSQ tagging supplies this — shared-and-tagged on J32-OOO ([j32ooo-spec.md §8.3](../ooo/j32ooo-spec.md)), structurally partitioned on J32-LT ([j32lt-spec.md §7.1](../ooo/j32lt-spec.md)).

**Contention scaling.** The number of same-core threads that can contend one line rises from 2 to 4 on J32-LT, and a dual-core J32-LT puts 8 threads on one L2. Two consequences:

1. The owner field must be sized `log2(NUM_CPUS) + log2(n_tc)` — 3 bits for dual-core 2-way, **4 bits for dual-core 4-way**. Sizing it from `NUM_CPUS` alone is a latent bug at `n_tc > 2`.
2. Fairness matters more. With 8 possible contenders, a NACK-and-retry policy with no ordering guarantee makes starvation observable rather than theoretical. The per-thread auto-priority of [j32lt-spec.md §9.3](../ooo/j32lt-spec.md) mitigates it from the core side — a spinning thread yields its barrel slots to the holder — but that is a throughput optimisation, not a forward-progress guarantee. **Forward progress under ≥4-way same-line contention needs an explicit argument that this spec does not currently make**; see §6.9.

### 6.9 Forward progress under high contention `[open]`

Not resolved. The v2 line lock relies on the requester retrying after a NACK, with no queueing or ticket ordering, which was defensible at 2 contenders and is not obviously so at 8. Options, in increasing cost: bounded retry with escalation to a fair queue; a per-line FIFO of waiting `{core, thread}` owners; falling back to the v1 bus lock after N failed retries. This must be settled before a dual-core J32-LT is built, and it is testable ahead of RTL with the existing `stress-ng --futex` and CAS-bouncer workloads.

### 6.7 Cross-line atomicity (not provided)

CAS.L is a single-line atomic. Two-line atomicity (e.g., DCAS, CAS2) is not provided in this spec. Software emulation via locks remains the contract.

### 6.8 Comparison with v1 bus-lock

| Metric                         | v1 (bus-lock)               | v2 (line-lock, T1/T2)         |
| ------------------------------ | --------------------------- | ------------------------------ |
| Unrelated-traffic stalls       | yes (whole bus)             | no (only the locked line)      |
| Maximum concurrent CAS.L count | 1 system-wide               | `NUM_SETS * L2_WAYS` worst case; typically `NUM_MSHRS` |
| Latency (uncontended)          | ~8 cycles                   | 8–10 cycles                    |
| Latency (contended)            | bus arbitration time         | snoop + GetM round-trip; comparable |
| Composability with coherence   | breaks coherence            | composes                       |
| Forward-progress backstop      | implicit (bus arb fairness) | explicit timeout (§6.5)        |

---

## 7. Coherence Protocol — MSI `[T1/T2]`

The coherence messages defined here are carried by the SoC fabric's dedicated snoop bus and request/response channels. The transport-level rules (single-snoop-per-line invariant, snoop ordering, per-core ACK FIFO backpressure, snoop-bus latency) are specified normatively in [bus/fabric-spec.md §7](../bus/fabric-spec.md); this section specifies the protocol *on top of* that transport.

### 7.1 Choice of MSI (vs MESI)

The protocol is **MSI**:

- **M (Modified)** — dirty exclusive copy in one L1-D.
- **S (Shared)** — clean copy in ≥1 L1-D; readable.
- **I (Invalid)** — no valid copy in L1-D.

No E (Exclusive clean) state. The MESI E state spares a snoop on the first write to a recently-loaded line, but doubles per-line state bits in L1-D (2 → effective 2.5–3 with the extra "first-write" tracking) and the savings rarely materialize on FPGA workloads that are L2-bandwidth-bound, not snoop-bound. Keep it simple.

Prior art: Papamarcos & Patel (ISCA 1984) introduced MSI as the canonical write-invalidate protocol (originally called Illinois; the M/S/I subset is the same); Hennessy & Patterson 3rd ed. (2003) is the standard textbook treatment.

### 7.2 L1-D state encoding `[T1/T2]`

Each L1-D line tag carries 2 state bits. Encoding:

```
00 = Invalid
01 = Shared
10 = Modified
11 = (reserved; for future MESI / MOESI extension if ever needed — not used)
```

L1-D tag-array width grows by 2 bits per line. For a 32 KB / 4-way L1-D with 32-byte lines = 256 sets × 4 ways = 1024 lines, that's 2048 bits = ~0.1 EBR. Negligible.

### 7.3 L2 directory `[T1/T2]`

Each L2 line tag carries:

| Field          | Bits                              | Description                                                          |
| -------------- | --------------------------------: | -------------------------------------------------------------------- |
| `dir_vec`      | `NUM_CORES` (2 for T1 baseline)   | One bit per core: set ⇔ this core's L1-D currently holds the line.   |
| `dir_state`    | 2                                 | M / S / I as seen at L2 (Modified=`10`, Shared=`01`, Invalid=`00`).  |
| (lock fields)  | see §6.2                          |                                                                       |

When `dir_state == M`, `dir_vec` is a one-hot of the modifying core (exactly one bit set). When `dir_state == S`, `dir_vec` has ≥1 bit set. When `dir_state == I`, `dir_vec == 0`.

**Invariant** (the directory is exact, by inclusion): a line is in state X in L1-D #N iff the L2 directory says `dir_vec[N]=1 ∧ dir_state=X`.

### 7.4 Message types `[T1/T2]`

Standard MSI message set:

| Message            | Direction        | Carries                  | Purpose                                                          |
| ------------------ | ---------------- | ------------------------ | ---------------------------------------------------------------- |
| `GetS`             | L1-D → L2        | addr, owner              | Read miss, want Shared.                                          |
| `GetM`             | L1-D → L2        | addr, owner              | Write miss, want Modified.                                       |
| `GetM-Locked`      | L1-D → L2        | addr, owner              | CAS.L acquire (§6).                                              |
| `Upgrade`          | L1-D → L2        | addr, owner              | Already in Shared, want Modified (no data needed).               |
| `Inv`              | L2 → L1-D        | addr, target mask        | Invalidate; ACK required.                                        |
| `Downgrade`        | L2 → L1-D        | addr, target mask        | Demote Modified → Shared (writeback included in ACK).            |
| `Recall`           | L2 → L1-D        | addr, target mask        | Drop the line (for L2 eviction); writeback if Modified.          |
| `Wb`               | L1-D → L2        | addr, data               | Writeback in response to Downgrade or Recall, or voluntary.       |
| `Unlock`           | L1-D → L2        | addr, owner, [data]      | Release line lock (§6).                                          |
| `DataResp`         | L2 → L1-D        | addr, data, install-state | Fill response for GetS/GetM/Upgrade/GetM-Locked.                  |
| `Ack`              | L1-D → L2        | addr                     | Acknowledge Inv, Downgrade, Recall.                              |

L1-I never originates GetM/Upgrade and never participates in coherence (§7.6).

### 7.5 State transitions at L2 directory `[T1/T2]`

| From state      | Event                       | Action                                                                     | To state      |
| --------------- | --------------------------- | -------------------------------------------------------------------------- | ------------- |
| I (or not present) | GetS(N)                  | Fill from SDRAM (or use existing L2 data). DataResp(install=S). Set `dir_vec[N]=1`. | S          |
| S               | GetS(N)                     | DataResp(install=S) from L2 data. `dir_vec[N]=1`.                          | S             |
| S (`dir_vec`={K}) | GetM(N), N≠K              | Inv(K). Wait Ack. DataResp(install=M, N). `dir_vec={N}`.                   | M             |
| S               | Upgrade(N)                  | If `dir_vec` has only N: just transition. Else Inv to others first. DataResp(install=M, N). | M    |
| M (`dir_vec`={K}) | GetS(N)                   | Downgrade(K). Wait Wb. Install Wb data in L2. DataResp(install=S, N). `dir_vec={K,N}`. | S |
| M (`dir_vec`={K}) | GetM(N), N≠K              | Downgrade then Inv(K) (or just Inv(K) with writeback flag). Wait Wb+Ack. DataResp(install=M, N). | M |
| any non-locked  | GetM-Locked(N)              | Same as GetM transition; additionally set `LOCKED=1`, `lock_owner={N,thr}`. | M (locked)   |
| M (locked)      | any Get*, lock_owner ≠ requester | NACK; requester retries. (Or: ENQUEUE; see §7.8.)                     | M (locked)   |
| M (locked)      | Unlock(matching owner)      | Optional merge of new data. Clear LOCKED.                                  | M (unlocked) |
| any             | L2 eviction of this line    | Recall to all in `dir_vec`. Wait Acks/Wb. Writeback to SDRAM if dirty.     | (line gone)   |

Forbidden transitions:
- `M → M` with a different `dir_vec` bit set without an intervening Inv. (Inclusion / single-writer invariant.)
- `S → S` with `dir_vec` becoming empty. (Either go to I, or keep at least one bit.)
- Acquiring `LOCKED` while another lock with a different owner is set. (Lock exclusivity.)

### 7.6 L1-I remains incoherent `[T1/T2]`

L1-I is read-only and **not** part of the coherence domain. This matches SH-2/SH-4 convention. Self-modifying code (including JIT'd code and module loading) requires explicit cache flushes via the J2 cache-control register (`arch/sh/mm/cache-j2.c` pattern) or the v2 `L2_FLUSH_CMD` (§13.5). The L2 directory does not track L1-I presence; if a line goes through coherence transitions while a stale L1-I copy exists, the L1-I copy is stale until flushed by software. Linux already handles this on SH; no kernel change required for v2.

The v1 `in_l1i` inclusion-tracking bit is dropped (no value if L1-I is not in the coherence domain). The single `in_l1d` bit is replaced by the per-L1-D `dir_vec`.

### 7.7 Inclusion enforcement `[T1/T2]`

The directory is *exact* by inclusion. To maintain inclusion under L2 capacity pressure:

- Before allocating a new way in a set, L2 picks a pLRU victim. If the victim's `dir_vec ≠ 0`, the corresponding L1-D copies must be recalled first (§7.5 last row). This adds latency to a small fraction of misses (~1–2% on typical L2/L1 sizing because the L2 is much larger than the union of L1s).
- A line that is currently `LOCKED` cannot be evicted. If pLRU picks a locked victim, the second-LRU victim is chosen instead. If all ways are locked (pathological), the miss stalls until any lock clears or times out (§6.5).

### 7.8 Same-line contention: NACK vs queue `[T1/T2]`

When a `GetM-Locked` arrives at a line already locked by another owner, two implementation choices:

- **NACK + retry** (baseline): L2 returns NACK; the requester's L1-D treats the uop2 as a temporary failure and reissues. Simpler, but creates request-bus traffic during contention.
- **In-L2 queue** (optional): L2 enqueues up to `LOCK_QUEUE_DEPTH` pending requests per locked line; when Unlock arrives, the next request is granted. Lower bus traffic but adds queue state. Reserved for a future optimization; baseline is NACK+retry.

Either choice satisfies the FGMT auto-priority feedback ([j32ooo-spec.md §10.5](../ooo/j32ooo-spec.md)): repeated NACKs (= repeated CAS.L failures with same PC) drop the requester's priority and yield front-end bandwidth to the lock holder, accelerating release.

---

## 8. Address Layout `[T0/T1/T2]`

Physical address (`ADDR_WIDTH` bits) is split as:

```
T1 (ADDR_WIDTH=32):

  31                       14 13  12  11      5  4         0
 +---------------------------+------+----------+-----------+
 |          TAG (18)         |BANK 2| INDEX 7  | OFFSET 5  |
 +---------------------------+------+----------+-----------+

T2 (ADDR_WIDTH=40):

  39                                   14 13  12  11      5  4         0
 +--------------------------------------+------+----------+-----------+
 |              TAG (26)                |BANK 2| INDEX 7  | OFFSET 5  |
 +--------------------------------------+------+----------+-----------+
```

The bank bits sit below the index bits so consecutive cache lines spread across all banks (improving parallel-access utilization). Identical to v1 except `TAG` field width scales with `ADDR_WIDTH`.

Alternative bank-bit placement is supported by the generic but the baseline layout above gives the best parallelism for typical access patterns.

---

## 9. Tag Array `[T0/T1/T2]`

### 9.1 Per-line tag format

Each tag entry holds (T1 baseline numbers given; T2 grows `tag` to 26):

| Field          | Bits (T1) | Bits (T2) | Tier   | Description                                                          |
| -------------- | ---------:| ---------:| ------ | -------------------------------------------------------------------- |
| `tag`          |        18 |        26 | all    | Upper PA bits.                                                       |
| `valid`        |         1 |         1 | all    | Line contains valid data.                                            |
| `dirty`        |         1 |         1 | all    | Line modified since fill.                                            |
| `dir_state`    |         2 |         2 | T1/T2  | M / S / I as observed at L2 (§7.3).                                  |
| `dir_vec`      |         2 |         2 | T1/T2  | Per-L1-D presence vector (1 bit per core; 2 for baseline).            |
| `LOCKED`       |         1 |         1 | T1/T2  | CAS.L line lock (§6).                                                |
| `lock_owner`   |         2 |         2 | T1/T2  | `{core_id, thread_id}` of lock holder.                               |
| `lock_age`     |         8 |         8 | T1/T2  | Lock age in cycles (§6.5).                                           |
| **Total (T0)** |    **22** |       n/a |        | (v1: `in_l1i`, `in_l1d` instead of `dir_*`; 22 bits)                  |
| **Total (T1)** |    **35** |       n/a |        | tag(18)+valid+dirty+dir_state(2)+dir_vec(2)+LOCKED+lock_owner(2)+lock_age(8) |
| **Total (T2)** |       n/a |    **43** |        | as T1 but tag=26                                                     |

Tag growth from v1 → v2 (T1): +13 bits per line. For a 128-set × 8-way × 4-bank L2 = 4096 lines, that's 52 Kbits = ~3 EBRs of additional tag storage. Cheap.

For larger core counts the `dir_vec` widens linearly with `NUM_CORES`; a 4-core variant adds 2 bits per line = 8 Kbits per L2 → still under 1 EBR.

### 9.2 Per-set state

Unchanged from v1: 7 bits of tree-pLRU for 8-way, 3 bits for 4-way; held in distributed LUT-RAM.

### 9.3 Tag array storage estimate

Per bank (baseline 128 sets, 8 ways):

| Tier | bits per way | bits per set (8 ways) | bits per bank (128 sets) | EBRs per bank |
| ---- | -----------: | --------------------: | -----------------------: | ------------: |
| T0   |           22 |                   176 |                   22,528 |       ~1.2    |
| T1   |           35 |                   280 |                   35,840 |       ~2.0    |
| T2   |           43 |                   344 |                   44,032 |       ~2.5    |

Across 4 banks: T0 ~5 EBRs, T1 ~8 EBRs, T2 ~10 EBRs — this is the figure §20.1's allocation table books. In practice tags are split across multiple narrow EBRs read in parallel because EBR ports cap at 36 bits; the realistic *mapped* count is therefore higher than the *capacity* count, 4–6 EBRs per bank or **16–24 EBRs total** at T1. Both numbers are structural; they answer different questions (bits needed vs blocks consumed after port-width packing), and §20.1's total uses the capacity figure. Which of the two the ECP5 mapper actually produces is unknown at this stage — needs measurement.

---

## 10. Data Array `[T0/T1/T2]`

### 10.1 Organization

Unchanged from v1. Per bank (32 KB at baseline): 128 sets × 8 ways × 32-byte lines = 32 KB per bank, each line 8 × 32-bit words, each way of each set a separate addressable region. ECP5 EBR mapping: ~15 EBRs per bank for data = **60 EBRs total** for 4 banks at the 128 KB baseline.

### 10.2 Access width

L2 hit returns a full line (32 bytes). **At `[T0]`**, writes from L1-D are 32-bit-word write-throughs (byte-enabled) — unchanged from v1. **At `[T1/T2]`** a store normally lands in the L1-D's `M` line and reaches the array later as a `Wb` (§7.4), so the write-through merge is no longer the common case; both ports exist in one design, per §10.4. This paragraph previously stated the T0 form under a `[T0/T1/T2]` tag it had not earned — see §17.1 and [decisions/0007](../decisions/0007-l1d-write-policy-under-msi.md).

### 10.3 Way selection

Unchanged. Tag compare runs in parallel with data read. `WAY_SELECT_PIPE=true` adds 1 cycle of hit latency.

### 10.4 Data-array port budget under coherence `[T1/T2]`

In addition to v1's port consumers (L1-D read, L1-I read, fill write, writeback read, write-through merge), T1 adds:

- **Snoop data read**: a Recall/Downgrade may require shipping the L2's current copy back to L1-D if the M-line writeback was lost in some corner case. Treated as a low-priority data read.
- **Inbound writeback write**: a `Wb` from an L1-D writes new data into the L2 data array. Treated as a high-priority write (it precedes the originator's DataResp).

These remain feasible on the v1 time-multiplexed-per-bank port arrangement; the snoop arbitration is sufficiently rare that it can share with the writeback-read slot.

---

## 11. State Machine `[T1/T2]`

The L2 controller per bank, T1, has additional states to handle coherence and lock transitions. The v1 backbone (IDLE → TAG_READ → TAG_COMPARE → DATA_FWD / miss path) is preserved; new states stitch into the existing arrows.

```
                            ┌──────┐
                ┌──────────→│ IDLE │←──────────────────────┐
                │           └──┬───┘                       │
                │              │ request                    │
                │              ▼                           │
                │       ┌──────────┐                       │
                │       │ TAG_READ │                       │
                │       └────┬─────┘                       │
                │            ▼                             │
                │  ┌─────────────────┐                     │
                │  │ TAG_COMPARE +   │                     │
                │  │ DATA_READ + DIR │  (incl. LOCK check) │
                │  └─┬──────┬──────┬─┘                     │
                │    │ hit  │ miss │ coherence-action      │
                │    │ ok   │      │ needed                │
                │    ▼      ▼      ▼                       │
                │ ┌──────┐ ┌──────┐ ┌────────────────┐     │
                │ │FWD or│ │ALLOC │ │ ISSUE_SNOOP    │     │
                │ │ MERGE│ └──┬───┘ │ (Inv/Downgrade)│     │
                │ └──┬───┘    ▼     └──┬─────────────┘     │
                │    │   ┌────────┐    ▼                   │
                │    │   │ EVICT  │ ┌────────────────┐     │
                │    │   └───┬────┘ │ WAIT_SNOOP_ACK │     │
                │    │       ▼      └──┬─────────────┘     │
                │    │   ┌────────┐    ▼                   │
                │    │   │ MSHR_  │ ┌────────────────┐     │
                │    │   │ ALLOC  │ │ INSTALL_WB     │     │
                │    │   └───┬────┘ │ (if Wb data)   │     │
                │    │       ▼      └──┬─────────────┘     │
                │    │   ┌────────┐    ▼                   │
                │    │   │ AWAIT_ │ ┌────────────────┐     │
                │    │   │ FILL   │ │ DATA_FWD +     │     │
                │    │   └───┬────┘ │ UPDATE_DIR     │     │
                │    │       ▼      └──┬─────────────┘     │
                │    │  ┌──────────┐   │                   │
                │    │  │INSTALL + │───┘                   │
                │    │  │DATA_FWD +│                       │
                │    │  │UPDATE_DIR│                       │
                │    │  └────┬─────┘                       │
                │    └───────┴──────────────────────────────┘
                │
                │     also: LOCK_TIMEOUT_TICK every cycle in IDLE
                │           checks all lines' lock_age,
                │           force-clears on overflow.
                │
                └────────────────────────────────────────────
```

New states:

- **DIR check** (folded into TAG_COMPARE): for a GetS/GetM/GetM-Locked, examine `dir_state`/`dir_vec`/`LOCKED`. Decide: serve locally (no snoop), serve after snoop, NACK (lock conflict), or stall (line currently being snooped by another request — MSHR-style serialization on per-line basis).
- **ISSUE_SNOOP**: drive Inv/Downgrade/Recall on the broadcast bus with the target core mask from `dir_vec`. 1 cycle.
- **WAIT_SNOOP_ACK**: wait for Ack(s) (and Wb data if Downgrade/Recall hit Modified). Snoop ACK round-trip: typically 4–8 cycles depending on L1-D port availability.
- **INSTALL_WB**: if Wb data arrived, merge into L2 data array. 1 cycle.
- **UPDATE_DIR**: set new `dir_state`/`dir_vec` reflecting the post-transaction state. 1 cycle, parallel with DATA_FWD.
- **LOCK_TIMEOUT_TICK**: each L2 bank scans (in background, 1 line per cycle round-robin) for `LOCKED ∧ lock_age == LOCK_TIMEOUT_CYC`; force-clears, raises PMU pulse.

### 11.1 Per-line per-bank serialization

The L2 bank must not service two concurrent in-flight transactions on the same line (e.g. a GetS while an Inv is outstanding). A small **in-flight set** (4 entries per bank, distributed RAM) tracks which lines have outstanding snoops; incoming requests to those lines queue in the bank's input FIFO until the in-flight entry frees.

This is the standard "per-line serialization at the directory" approach (SGI Origin 2000; H&P 3rd ed. Ch. 6).

### 11.2 Latency budget

| Path                                                   | Cycles  | Tiers     |
| ------------------------------------------------------ | ------: | --------- |
| L2 hit (read, full line, no coherence work)            | 3 (4 with `WAY_SELECT_PIPE`) | all |
| L2 hit (write-through merge, no coherence work)        | 3       | all       |
| L2 hit (GetM hitting Shared in other L1 — needs Inv)   | 3 + snoop round-trip (~6) = 9 | T1/T2 |
| L2 hit (GetS hitting Modified in other L1 — Downgrade) | 3 + snoop + Wb merge (~8) = 11 | T1/T2 |
| L2 miss → SDRAM hit → fill                             | 14–24   | all       |
| L2 miss with dirty eviction                            | 16–28   | all       |
| L2 miss with eviction of a remote-Modified line        | 16–28 + Recall snoop (~6) = 22–34 | T1/T2 |
| CAS.L `GetM-Locked` (no contention, line in L2)        | 8–10    | T1/T2     |
| CAS.L `GetM-Locked` (contention, NACK + retry)         | 8–10 per attempt + back-off | T1/T2 |
| Snoop Inv latency (L2 → L1-D Ack)                      | 4–6     | T1/T2     |

---

## 12. Miss Status Holding Registers (MSHRs) `[T0/T1/T2]`

### 12.1 Purpose

Unchanged from v1: MSHRs let the L2 handle multiple outstanding misses without blocking. Per Kroft 1981.

### 12.2 MSHR fields

Each MSHR has:

| Field             | Bits (T1)               | Bits (T2)               | Description                                       |
| ----------------- | ----------------------: | ----------------------: | ------------------------------------------------- |
| `valid`           |                       1 |                       1 | This MSHR is in use                               |
| `addr`            |                      27 |                      35 | Line-aligned address (`ADDR_WIDTH - OFFSET_BITS`)  |
| `bank`            |                       2 |                       2 | Which bank initiated this miss                    |
| `way_to_install`  |                       3 |                       3 | Which way to fill on response                     |
| `dirty_to_evict`  |                       1 |                       1 | Victim was dirty                                  |
| `requestors`      |    `NUM_CORES * NUM_THR_PER_CORE * 2` (8 for T1 baseline) | (same) | Bit vector — one bit per L1 client (L1-I and L1-D per core/thread) |
| `requestor_meta`  |               several   |                various | per-requestor info: thread ID, requested coherence state, lock flag |
| `coh_install_state` |                     2 |                       2 | M/S/I to install in requester L1 on response (new in T1) |

The `requestors` width grows with NUM_CORES and threads. For T1 baseline (2 cores × 2 threads × {L1-I, L1-D}) = 8 bits.

The MSHR coalescing rules need a small update for coherence: two L1-Ds in different cores both missing on the same line **with compatible coherence requests** (both GetS) coalesce. **Incompatible** requests (one GetS, one GetM) do not coalesce — they serialize, with GetM serviced after GetS to preserve correctness.

### 12.3 MSHR pool

4 MSHRs total in T1 baseline, shared across banks. Higher counts (8) help under heavy multi-core miss contention but cost LUTs; defer the resize decision to post-bring-up measurements.

**Shared across banks *and across cores*, which is what makes this pool a cross-tenant structure.**
The `requestors` vector of §12.2 is sized as cores × threads × {L1-I, L1-D}, so an MSHR is
reachable by every core at once and **no core-granular control can reach it** — the gang switch of
[hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md) cannot flush it, and the
"MSHRs" that list names are the core-side pool of
[ooo/j32lt-spec.md §7.4](../ooo/j32lt-spec.md), not this one. Under trust-domain partitioning the
pool is statically reserved and the sizing above becomes a constraint rather than a preference:
see §16.2 `P-R3` (reservation and `NUM_MSHRS / NUM_DOMAINS >= 2`) and `P-R4` (no cross-domain
coalescing, which is a separate channel that `P-R3` does not touch).

---

## 13. Interfaces `[T0/T1/T2]`

### 13.1 L1-I read interface `[T0/T1/T2]`

```vhdl
type l2_l1i_req_t is record
    req_valid : std_logic;
    core_id   : std_logic_vector(log2(NUM_CORES)-1 downto 0);   -- T1+
    domain    : std_logic_vector(6 downto 0);                   -- T1/T2: {VALID, HTCR.TENANT} (§16.1)
    addr      : std_logic_vector(ADDR_WIDTH-1 downto 0);
end record;

type l2_l1i_resp_t is record
    resp_valid : std_logic;
    line_data  : std_logic_vector(8*L2_LINE_BYTES-1 downto 0);
    error      : std_logic;
end record;
```

L1-I issues a line read; L2 responds asynchronously. The `core_id` field is required at T1 so the L2 can route the response back to the originator on a multi-core fabric.

`domain` is the way-partition tag of [§16.1](#161-way-partitioning-by-trust-domain-t1t2) and is
present only at T1/T2. It is `{VALID, TENANT[5:0]}` read from the issuing thread context's `HTCR`
([hypervisor/hardware-spec.md §2.10](../hypervisor/hardware-spec.md)); `VALID = 0` selects the
host domain `H`. *(Added post-F, 2026-09-09. §16.1 said the tag was "carried on the fabric
alongside the existing `owner` field of §6". Neither of these records had a domain field, §6's
`owner` is a lock owner and not a domain, and none of this traffic is on the fabric — it is
core-to-L2. Without the field the partition has no index and every rule of §16.2 is inert.)*

### 13.2 L1-D coherence interface `[T1/T2]`

The v1 read/write interface is replaced by a **coherence-message interface**. The L1-D sends one of `GetS / GetM / GetM-Locked / Upgrade / Wb / Unlock / Ack`; the L2 sends `DataResp / Inv / Downgrade / Recall`.

```vhdl
type coh_msg_kind_t is (
    K_GetS, K_GetM, K_GetM_Locked, K_Upgrade,
    K_Wb,   K_Unlock, K_Ack,
    K_DataResp, K_Inv, K_Downgrade, K_Recall, K_Nack
);

type l2_l1d_msg_t is record
    valid     : std_logic;
    kind      : coh_msg_kind_t;
    addr      : std_logic_vector(ADDR_WIDTH-1 downto 0);
    core_id   : std_logic_vector(log2(NUM_CORES)-1 downto 0);
    thread_id : std_logic_vector(log2(NUM_THREADS_PER_CORE)-1 downto 0);
    domain    : std_logic_vector(6 downto 0);   -- T1/T2: {VALID, HTCR.TENANT} (§16.1, §13.1)
    install_state : std_logic_vector(1 downto 0);   -- M/S/I on DataResp
    data      : std_logic_vector(8*L2_LINE_BYTES-1 downto 0); -- on DataResp, Wb, Unlock-with-data
    byte_en   : std_logic_vector(L2_LINE_BYTES-1 downto 0);   -- on partial-write merge
    has_data  : std_logic;
end record;

-- Bi-directional: one record from L1-D to L2, one from L2 to L1-D.
type l2_l1d_port_t is record
    to_l2   : l2_l1d_msg_t;
    from_l2 : l2_l1d_msg_t;
end record;
```

For T0 (single-core, no coherence) the same record carries a degenerate message set (`K_GetS`, `K_GetM`, `K_Wb`, `K_DataResp` only; no Inv/Downgrade/Recall traffic ever generated). T0 implementations may use a simpler stripped interface; the unified record allows one RTL to compile to either tier.

### 13.3 Snoop port at L1-D `[T1/T2]`

The L1-D already has the `sa`/`sy` snoop port (`dcache_snoop_io_t` in `cache/dcache.vhd`). v2 extends it from "invalidate by line address" to carry the message kind from §7.4. Specifically:

```vhdl
type dcache_snoop_io_v2_t is record
    valid     : std_logic;
    kind      : coh_msg_kind_t;        -- Inv / Downgrade / Recall
    addr      : std_logic_vector(ADDR_WIDTH-1 downto 0);
    -- Ack / Wb data flows back on the same port in the reverse direction.
end record;
```

This is the change called out in [dual-fgmt-proposal.md §9](../fgmt/dual-fgmt-proposal.md) ("extending the abstraction... may require... reworking the dcache state machine") — done here.

### 13.4 Memory-clock-layer interface `[T0/T1/T2]`

```vhdl
type l2_mcl_req_t is record
    req_valid : std_logic;
    is_write  : std_logic;
    addr      : std_logic_vector(ADDR_WIDTH-1 downto 0);
    data      : std_logic_vector(8*L2_LINE_BYTES-1 downto 0);
end record;

type l2_mcl_resp_t is record
    resp_valid : std_logic;
    data       : std_logic_vector(8*L2_LINE_BYTES-1 downto 0);
    error      : std_logic;
end record;
```

This is the existing `dcache_mcl.vhm` interface widened to `ADDR_WIDTH` and to the L2 line size. **Hardware-impl coordination point**: `cache/dcache_mcl.vhm` record types currently fix the address width at 32 bits. T2 (J64) requires an `ADDR_WIDTH` generic at the mcl as well; the SDRAM controller below the mcl is unaffected (DDR3 still presents a 32-bit-or-less row/column address — the wider PA just selects among chip-selects / DIMM ranks).

### 13.5 Control/CSR interface `[T0/T1/T2]`

```
| Register     | Width | Tier  | Purpose                                          |
| ------------ | ----: | ----- | ------------------------------------------------ |
| `L2_CTRL`    |    32 | all   | Enable, flush-all, freeze (for debug)            |
| `L2_STATUS`  |    32 | all   | Busy, MSHR-full, writeback-pending flags, and the sticky `WAYMASK_REJECT` of §16.2 `P-R1` |
| `L2_FLUSH_ADDR` |  32 | all  | Address for targeted-line flush (low 32 bits; for T2 a second register `L2_FLUSH_ADDR_HI` holds the high 8 bits) |
| `L2_FLUSH_CMD` |   32 | all  | Flush command (clean, invalidate, clean-invalidate) |
| `L2_HIT_CNT` |    64 | all   | Counter: L2 hits                                 |
| `L2_MISS_CNT`|    64 | all   | Counter: L2 misses                               |
| `L2_WB_CNT`  |    64 | all   | Counter: writebacks to SDRAM                     |
| `L2_INVAL_CNT`|   64 | all   | Counter: L1 invalidations sent (Inv+Downgrade+Recall) |
| `L2_SNOOP_CNT`|   64 | T1/T2 | Counter: snoop messages issued (Inv+Downgrade+Recall) |
| `L2_LOCK_TO_CNT`| 64 | T1/T2 | Counter: lock timeouts (§6.5)                   |
| `L2_LOCK_NACK_CNT`| 64 | T1/T2 | Counter: GetM-Locked NACKs                     |
| `L2WAYMASK[d]` |   32 | T1/T2 | §16.1 allocation mask, low 8 bits, one per domain `d` over `NUM_DOMAINS`. Reset all-ones. An illegal value is rejected per §16.2 `P-R1` and sets `L2_STATUS.WAYMASK_REJECT` |
| `L2MSHRRSV`  |    32 | T1/T2 | Read-only: the per-domain MSHR reservation `NUM_MSHRS / NUM_DOMAINS` that §16.2 `P-R3` fixes at elaboration. Present so a hypervisor can read what it got rather than recompute it |
| `L2DRRQ[d]`  |    32 | T1/T2 | §16.2 `P-R5` deficit-round-robin quantum, one per domain `d`. Equal quanta are the reset state |
```

*The last three rows were added post-F, 2026-09-09.* §16.1 and §16.2 specify `L2WAYMASK` and
`L2DRRQ` as hyperprivileged registers and [hypervisor/design-spec.md §6.2](../hypervisor/design-spec.md)
obliges a hypervisor to write both on every tenant admission — and neither appeared in any
register map in this document, so there was nothing for that hypervisor to write to. `L2MSHRRSV`
is new rather than restored: `P-R3`'s reservation is an elaboration-time constant and §6.2 item 2
tells the hypervisor to "assign the reservation", which it cannot; it can only read it.

**Privilege.** This whole block is hyperprivileged and not guest-visible: it sits at `0xFF040000`
in P4 ([soc/p4-mmio-map.md §3](../soc/p4-mmio-map.md)), P4 is `SR.MD = 1` only, and a guest's P4
accesses trap wholesale ([hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md)).
That is the right side of §16.2 `P-R8`, and it is stated here because the cache-control register
the SoC ships **today** is on the wrong side of it — see `P-R8`.

These integrate with the J32-OOO PMU ([j32ooo-spec.md §12](../ooo/j32ooo-spec.md)). Existing event IDs 0x08 (`L2_ACCESSES`) and 0x09 (`L2_MISSES`) are preserved. New event IDs (proposed; allocate after coordination with the PMU spec):

- `L2_SNOOPS_ISSUED` — reads `L2_SNOOP_CNT`.
- `L2_LOCK_CONTENTION` — reads `L2_LOCK_NACK_CNT`.
- `L2_LOCK_TIMEOUT` — reads `L2_LOCK_TO_CNT`. Useful for diagnosing pathological CAS.L behavior.

---

## 14. Directory Bit-Vector Storage Cost (BRAM/LUT Estimate) `[T1/T2]`

Per L2 line, the v2 additions over v1 are:
- `dir_state`: 2 bits
- `dir_vec`: `NUM_CORES` bits (2 for T1 baseline)
- `LOCKED`: 1 bit
- `lock_owner`: `log2(NUM_CORES) + log2(NUM_THREADS_PER_CORE)` bits (2 for T1 baseline)
- `lock_age`: `log2(LOCK_TIMEOUT_CYC)` bits (8 for default 256)
- Subtotal: 15 bits / line (T1 baseline, 2 cores)

For the baseline 4096-line L2 = 60 Kbits ≈ **3.5 EBRs** of additional storage. Sits comfortably inside the v1 tag-array headroom because tag access already runs through several narrow EBRs in parallel; the extra bits get absorbed into existing parallel reads.

Per-line scaling with `NUM_CORES`:

| `NUM_CORES` | `dir_vec` | `lock_owner` (with FGMT=2) | v2 extra / line | EBRs (4096 lines) |
| ----------- | --------: | -------------------------: | --------------: | ----------------: |
| 1 (T0)      |     0¹    |                          1 |              12 |               2.7 |
| 2 (T1)      |         2 |                          2 |              15 |               3.5 |
| 4           |         4 |                          3 |              18 |               4.1 |
| 8 (future)  |         8 |                          4 |              23 |               5.3 |

¹ T0 omits the directory bits entirely; if compiled with `NUM_CORES=1` and coherence disabled, only the `LOCKED`+`lock_owner`+`lock_age` lock fields are kept (~12 bits/line); the lock fields are wired but inert if line-lock is also disabled.

For T2 (40-bit PA), the only additional cost is the wider tag field (+8 bits/line) — see §9.3.

LUT cost of directory state-machine: unknown at this stage — needs measurement, like everything else in §21, which says of itself that it is a budget rather than a measurement. This sentence previously estimated 1.5k LUT4 equivalents per bank and ~6k across 4 banks, which is inconsistent with §21's own table booking the directory FSM at 2,400 LUT4 for all four banks together — two different unmeasured numbers for one block, in one document.

---

## 15. Coherence-Action vs Main Pipeline Ordering `[T1/T2]`

Snoops have higher priority than incoming read/write at the per-bank arbiter (§5.3), but the **interaction with in-flight requests at the same line** requires care. The arbiter handles it as follows:

### 15.1 Snoop vs incoming request, different lines

Independent. Snoop completes on its line; incoming request proceeds on its line. The shared resource is the data-array port, time-multiplexed with snoop given priority on the conflict cycle.

### 15.2 Snoop vs incoming request, same line

The per-bank **in-flight set** (§11.1) ensures only one transaction per line proceeds at a time. If a snoop is in progress for line X, an incoming request for line X queues at the bank-input FIFO. When the snoop's `UPDATE_DIR` retires the in-flight entry, the queued request proceeds — it sees the post-snoop directory state.

This guarantees the directory state observed by request N is identical to the state left by request N-1, preserving the MSI state-machine semantics.

### 15.3 Snoop vs ongoing locked operation, same line

If line X has `LOCKED=1` and an incoming `GetS/GetM` from a non-owner arrives:
- The directory check during TAG_COMPARE notices LOCKED ∧ owner-mismatch.
- The bank issues `NACK` immediately, **without** queuing — preventing the in-flight set from filling with stalled requests for a long-locked line.
- The requester back-pressures and retries (or, with the optional in-L2 queue of §7.8, queues in a dedicated lock-wait list).

### 15.4 Snoop vs Recall (eviction) of the same line

L2 can issue at most one Recall per line. Eviction is sequenced through the same per-line in-flight slot; new requests for that line queue behind the Recall and observe the line as Invalid afterward, triggering a normal miss flow.

---

## 16. Replacement Policy `[T0/T1/T2]`

Tree pseudo-LRU, unchanged from v1 (§9 of v1 archive). One small addition under T1/T2: when the pLRU pick is a `LOCKED` line, walk to the second-LRU; if all ways are locked, the bank stalls the requester (§7.7). The pLRU update on a hit is unchanged.

### 16.1 Way partitioning by trust domain `[T1/T2]`

The L2 specified here is **one set of tag and data arrays shared by every core** (§2). That is the
right implementation choice and it has a consequence that the CPU specs' tenancy rules do not reach:
**two tenants running on two different cores share the L2**, so a prime-and-probe across its sets is
a cross-tenant channel that no placement policy on the core side can close.
[ooo/j32ooo-spec.md §20.3](../ooo/j32ooo-spec.md) and [ooo/j32lt-spec.md §16.3](../ooo/j32lt-spec.md)
make a core the unit of tenant allocation, which closes the L1, TLB and predictor channels; the
shared L2 sits below all of them and is untouched by that rule. Both of those sections named
way-partitioning as the escape hatch. This section is that escape hatch, promoted to a specified
mechanism because the channel exists in the baseline dual-core configuration and not only in some
future one.

**Mechanism.** One `L2WAYMASK` register per trust domain, consulted on **allocation only**:

```
L2WAYMASK[d]   8 bits (one per way)   -- ways into which domain d may allocate
```

- On a fill for a request tagged with domain `d`, the pLRU victim search of §16 is restricted to
  ways where `L2WAYMASK[d]` is set. This is *every* fill and not only a demand miss, so a
  software-initiated allocation — `pref`'s `GetS`, `movca.l`'s `GetM` (§17.5) — is confined by the
  same mask with no separate rule. The walk-past-`LOCKED` rule and the all-locked stall are
  unchanged. **The hit-time pLRU update is no longer unchanged**: it was, in v0.3, and that was
  the metadata channel; §16.2 `P-R2` replaces it.
- **Hits are not restricted.** A domain may hit on a line in any way. Restricting hits would break
  coherence and shared read-only mappings (the hypervisor's own text, a shared page). *The
  justification that followed was wrong and has been removed:* it read "for no security gain,
  since a hit reveals only that the line is present — which is what the partition already prevents
  an attacker from *causing*", and a hit reveals two further things the partition does not prevent
  — that it **moved replacement metadata**, closed by §16.2 `P-R2`, and that it **took a hit
  rather than a miss on a line the attacker also maps**, which is Flush+Reload's reload half and
  is **accepted** at §16.3 row 8. Unrestricted hits remain the right choice; the reason is that
  the alternative costs shared pages, not that the alternative buys nothing.
- **The domain tag travels with the request, and it is `HTCR.TENANT` — not `PDID`.** *(Decided
  post-F, 2026-09-09. This bullet read "It is the same `PDID` the CPU specs use for predictor
  tagging …, carried on the fabric alongside the existing `owner` field of §6", and all three of
  those halves were wrong: the register, the transport, and the field.)*

  `PDID` is **optional**. [hypervisor/hardware-spec.md §2.8](../hypervisor/hardware-spec.md)
  requires it only "on any implementation that speculates" and says explicitly it is "not required
  on the in-order J2/J32 cores", with `CPUINFO` bit `[17] = PDID_SUPPORT` reporting its presence —
  and [decisions/0009](../decisions/0009-in-order-fgmt-is-the-default-path.md) makes dual-issue
  **in-order** with 2-thread FGMT the default path. A partition indexed by `PDID` therefore has no
  index at all on the default part: §16.1 and every rule of §16.2 would be inert there, while
  [hypervisor/hardware-spec.md §4.7](../hypervisor/hardware-spec.md) still asserts this channel is
  closed by way-partitioning "required in the baseline dual-core configuration". Wave-3 **C2c**
  reached the same conclusion for its own check and allocated a new mandatory register rather than
  reuse `PDID`; that argument binds here for the same reason, and this section did not have it.

  The tag is `{VALID, TENANT[5:0]}` taken from the issuing thread context's **`HTCR`**
  ([hypervisor/hardware-spec.md §2.10](../hypervisor/hardware-spec.md)). A request from a context
  with `VALID = 1` carries domain `TENANT`; a request from a context with `VALID = 0` — which
  under [`T-R1`](../hypervisor/hardware-spec.md) is never a guest — carries the reserved **host
  domain** `H`. Hardware still never
  interprets the *value* of `TENANT`, which is §2.10's own rule: it uses it as an index and reads
  only `VALID`. `L2WAYMASK` is indexed over the tenants plus `H`, and `L2WAYMASK[H]` resets to
  all-ones, so an unvirtualized or T0 system is unaffected exactly as before.

  **`HTCR` has to be present wherever this partition is.** §2.10 required it only on
  implementations with more than one thread context, which would leave a single-threaded dual-core
  T1 part — the very configuration the paragraph above says the channel exists in — holding a
  partition with no tag. §2.10's presence rule now names a way-partitioned shared L2 as a second
  trigger.

  **How it travels: a new field on the L1↔L2 message, not "the fabric".** The domain reaches the
  L2 by no route today. §13.2's `l2_l1d_msg_t` carries `core_id` and `thread_id` and no domain;
  §13.1's L1-I request carries `core_id`; and §6.2's `owner` is a **lock** owner,
  `{core_id, thread_id}` written into the tag array — not a bus attribute and not a domain. None
  of those messages traverses the SoC fabric at all; they are core-to-L2. §13.1 and §13.2 gain a
  `domain` field, and that field is where the cost of this section actually sits.
- `L2WAYMASK` is hyperprivileged. A mask of all-ones is the unpartitioned behaviour, which is the
  reset state, so T0 and non-virtualized systems are unaffected.

**What this closes — the occupancy channel, and only that.** Prime-and-probe requires the
attacker to *allocate* lines that evict the victim's. Restricted to disjoint ways, it cannot: it
may observe only the occupancy of ways it owns. **This sentence previously read "Why this closes
the channel", with no article and no scope**, and [security/threat-model.md §7.6](../security/threat-model.md)
ratified §16.1 as an allocation control on exactly that ground. Replacement metadata, the L2 MSHR
pool, bank contention and memory bandwidth are all untouched by it; §16.2 addresses four of those
and §16.3 lists what remains open after §16.2 as well. Partitioning by way rather than by set is what preserves the full address range for
every domain — a set-partitioned L2 would give each domain a fraction of the physical address space,
which is useless here.

**Sizing and the residual case.** Eight ways over two-to-three concurrent tenants is workable, but
**not at any split**: §16.2 `P-R1` requires each mask to be an aligned power-of-two group of ways,
so two tenants get 4+4 and three get 4+2+2. A 3+3+2 split is not legal, and this sentence said
"2–4 ways each" before `P-R1` existed, which read as licensing one. With more tenants than ways, domains must share masks, and sharing a mask means
sharing the channel — so the hypervisor MUST either give mutually distrusting tenants disjoint
masks, or, when a tenant is descheduled and its ways reassigned, **flush that tenant's ways**. A
one-way flush is 16 KB of write-back, ~82 µs at ~200 MB/s — against a full-L2 flush at 128 KB,
~655 µs, which is the reason partitioning is specified here rather than "flush the L2 at every
tenant switch".

**Cost.** An 8-bit mask register per domain and an AND into the pLRU victim-select mask are the
cheap half; no tag-array change, no data-array change, no change to the state machine of §11 or
the coherence protocol of §7. *The "~200 gates" this paragraph carried is removed rather than
annotated ([decisions/0005](../decisions/0005-unmeasured-figures-are-removed.md)), because it was
costed against "the domain tag is already on the fabric", which is false* — the tag is not on the
fabric and is not anywhere else either. The real cost is the `domain` field added to §13.1 and
§13.2, seven bits wide on every L1↔L2 message in both directions, plus the `HTCR` read port that
sources it. No figure is offered for it and none is invented.

**Prior art (pre-2006).** MIT **column caching** — Chiou, Jain, Devadas & Rudolph, "Dynamic cache
partitioning via columnization" (DAC 2000) and Chiou, *Extending the Reach of Microprocessors:
Column and Curious Caching* (PhD thesis, MIT, 1999), which is precisely "make each way of a
set-associative cache a column and restrict allocation by software-set mask"; **US6370622**, "Method
and apparatus for curious and column caching" (MIT, filed 1998, **expired**); Suh & Devadas, dynamic
partitioning of shared cache memory (2002–2004). This is the mechanism those references describe,
used for the purpose they describe it for.

**Prior art for §16.2's additions (pre-2006), checked at source.** The rules that go beyond
allocation need their own grounding and get it, because the *purpose* — that metadata updates leak
across a partition — is younger than every structure that implements it, which is precisely the
case [glossary.md §2.1](../glossary.md) rule 2 covers.

| Rule | Pre-2006 source, and what it actually says |
|---|---|
| `P-R2`(b) — no replacement-state update on an out-of-partition hit | Chiou, Jain, Devadas & Rudolph, *Dynamic Cache Partitioning via Columnization*, **MIT CSAIL Memo 430, November 1999** (published as DAC 2000, Los Angeles, June 2000): "One way to solve this problem is to **not update the LRU state of a cache-line that is caching data not currently mapped to the column it resides in**." That is `P-R2`(b) verbatim, arrived at for a repartitioning-effectiveness reason rather than a security one — [glossary.md §2.1](../glossary.md) rule 1's case exactly. The same memo supplies §16.1's unrestricted hits: "items present in the cache will always be found whether or not they are in the correct column" |
| `P-R1`, `P-R2`(a) — per-partition replacement state | **US6370622** (Chiou & Ang, MIT, filed 1998-11-20, granted 2002-04-09, **Expired — Fee Related**), whose specification gives "a bit vector, one bit per column, which indicates the columns of the cache that are available for replacement" and provides for a replacement policy specified per region. It does **not** describe per-partition LRU *state*, so the subtree-confinement half of `P-R2`(a) is not covered by it and rests instead on composing tree-pLRU (Smith 1982, §3) with per-segment replacement (Kirk 1989, below) |
| Partitioning a cache **as a side-channel defence** | D. Page, *Partitioned Cache Architecture as a Side-Channel Defence Mechanism*, **IACR ePrint 2005/280, submitted 2005-08-25**. Pre-2006 and security-purposed, which is the combination §2.1 rule 2 asks for. It proposes `ADDPAR`/`DELPAR`/`INVPAR` and states of them that "one would expect such cache management instructions to only be available when the processor is in protected mode … this ensures user processes cannot examine or alter each others cache configuration" — the pre-2006 grounding for `P-R8`. Note where it is *stronger* than §16.1: in Page's design "access by a process to partitions of another process is invalid", so hits do not cross a partition at all. §16.3 row 8 is the price of not taking that option |
| `P-R3` — per-domain reservation to bound one client's effect on another | Kirk, *SMART (Strategic Memory Allocation for Real-Time) cache design*, IEEE RTSS 1989, pp. 229–237 (cache divided into segments allocated per task); Stone, Turek & Wolf, *Optimal partitioning of cache memory*, IEEE Trans. Computers 41(9), 1992, pp. 1054–1068. Both are already cited in this workspace at [iommu/hardware-spec.md §10.2](../iommu/hardware-spec.md) for `I-R8`, the same mechanism applied to the IOTLB |
| `P-R5` — per-domain quantum with carried-forward deficit | Shreedhar & Varghese, *Efficient Fair Queueing using Deficit Round Robin*, ACM SIGCOMM 1995 (CCR 25(4)); IEEE/ACM Trans. Networking 4(3), 1996, pp. 375–385. O(1) per request and "simple enough to implement in hardware" in the paper's own terms. Packet scheduling rather than memory scheduling — mechanism, not motivation, again |

**`DAWG` is deliberately not the name of any mechanism here, and this is the C2c treatment.**
Kiriansky, Lebedev, Amarasinghe, Devadas & Emer, MICRO 2018, is where the *finding* was published
and it is cited as evidence in [security/threat-model.md §7.6](../security/threat-model.md) and
[j4-remediation-plan.md §E.8](../j4-remediation-plan.md); it is not prior art and this
specification does not adopt its mechanism. DAWG replicates replacement metadata **per domain** and
isolates hits; §16.2 keeps one tree and confines updates within it, and keeps hits unrestricted.
Those are different structures reached for the same reason. A search for a patent filing tied to
DAWG found none — that is a search result and not a freedom-to-operate opinion, and
[glossary.md §2.1](../glossary.md)'s closing sentence still applies before RTL commits.

---

### 16.2 Cache isolation beyond ways `[T1/T2]` *(C2e, 2026-09-09)*

§16.1 closes one channel and §16.1's own body contains three sentences that reopen others: hits
are unrestricted, the hit-time pLRU update is unchanged, and the MSHR pool of §12.3 is never
mentioned. This section is the rest of the mechanism, and §16.3 is the honest list of what is
still open after it. **A reader who stops at §16.1's "Why this closes the channel" gets a wrong
answer for every channel except occupancy**, which is why that heading has been narrowed.

Eight rules, `P-R1`–`P-R8`. They are `[T1/T2]` because they presuppose the trust domains of
§16.1, which T0 does not have.

**`P-R1` — a legal `L2WAYMASK` names an aligned pLRU subtree.** The mask must be a contiguous,
power-of-two-sized, naturally aligned group of ways. With `L2_WAYS = 8` the legal partitions are
`{8}`, `{4,4}`, `{4,2,2}`, `{4,2,1,1}`, `{2,2,2,2}` and their permutations, down to single ways.
A write of any other value **leaves the previous mask in place** and sets a sticky
`WAYMASK_REJECT` bit in `L2_STATUS` (§13.5); it is not silently accepted and not silently
rounded. The rejection is the detector — a rule with no detector is not a control
(`T-R1` of [hypervisor/hardware-spec.md §4.7.2](../hypervisor/hardware-spec.md) makes the same
point).

*This costs something and the cost is not hypothetical.* §16.1's sizing sentence said "2–4 ways
each" for two to three tenants, which reads as licensing a 3+3+2 split. Under `P-R1` there is no
3-way partition: three mutually distrusting tenants get **4+2+2**, and the tenant holding two ways
has half the associativity of the one holding four. That sentence in §16.1 has been corrected
rather than left to be read the old way. The constraint buys `P-R2`, and without it `P-R2` is
unimplementable for arbitrary masks — two disjoint but interleaved masks (say `{0,4}` and `{1,5}`)
both consult and both move the root node of the tree, and no rule about *which* nodes to update
can separate them.

**`P-R2` — replacement-state updates are confined to the accessor's subtree.** Two clauses,
because the two cases have different reasons:

- **(a) In-partition access.** A hit or a fill by domain `d` on a way inside `L2WAYMASK[d]`
  updates only the pLRU nodes **strictly inside** `d`'s subtree. The nodes on the path from the
  tree root down to that subtree's root are not updated. Under `P-R1` those nodes are also never
  *consulted* by `d` — at a node with allowed ways on only one side the victim search takes that
  side regardless of the stored bit — so this removes nothing `d` uses, and two domains with
  disjoint masks then touch disjoint sets of nodes.
- **(b) Out-of-partition hit.** A hit by `d` on a way **outside** `L2WAYMASK[d]` — the case
  §16.1 deliberately permits, so that coherence and shared read-only mappings work — updates
  **no** replacement state at all.

Clause (b) is the one the channel is named for: without it, a victim's architectural hit on a line
resident in the attacker's ways moves a tree node the attacker's victim search reads, and the
attacker learns that the hit happened. That is the residual [j4-remediation-plan.md §E.8](../j4-remediation-plan.md)
quotes as "in CAT, access patterns leak through metadata updates on hitting loads", and it is
[security/threat-model.md §10](../security/threat-model.md) item 2.

**`P-R3` — L2 MSHRs are statically reserved per domain, and the pool is sized from the domain
count.** §12.3's pool is 4 entries shared across banks, and — because the `requestors` vector of
§12.2 is sized as cores × threads × {L1-I, L1-D} — across **cores** as well, so no core-granular
control reaches it (this is why the "MSHRs" named in
[hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)'s gang-switch list are the
core-side pool and not this one; see [security/threat-model.md §8](../security/threat-model.md)
**L1**). The rule:

```
NUM_MSHRS / NUM_DOMAINS >= 2         -- checked at elaboration, not at runtime
per-domain cap = reservation = NUM_MSHRS / NUM_DOMAINS
```

*The names are §4's, and until this was checked they were not.* This block was written over a
miss-capacity generic that appears in no configuration-parameter table in this document — §4
calls it **`NUM_MSHRS`** — and over `NUM_DOMAINS`, which was not a generic at all. An elaboration
constraint written over two names the entity does not declare cannot be elaborated. Both are §4
rows now *(post-F, 2026-09-09)*.

Each domain may hold at most its share and always has its whole share available. **There is no
shared remainder**, and that is the point: a remainder any domain may take is exactly the
occupancy channel this rule exists to remove, one level down from the ways.

*Cost, stated rather than estimated.* On the T1 baseline the pool is 4 and two domains get 2 each,
which halves a single domain's L2-level memory-level parallelism when it is the only domain
running. A 3- or 4-domain deployment must raise `NUM_MSHRS` to 8, which §12.3 already names as the
alternative and already says costs LUTs. Neither cost is measured here; **`P-E2`** owes the
measurement, and no number is invented for it
([decisions/0005](../decisions/0005-unmeasured-figures-are-removed.md)).

**`P-R4` — MSHR coalescing does not cross a domain boundary.** §12.2 merges two L1-D misses to the
same line when their coherence requests are compatible. Across domains that makes one domain's
miss *latency* depend on whether another domain already had a miss outstanding on that line — a
signal `P-R3` does not touch, because it is about **sharing an entry**, not about occupying one. A
request from domain `e` never merges into an MSHR owned by `d`; it takes an entry from `e`'s own
reservation or waits for one. Coalescing within a domain is unchanged, as is the GetS/GetM
serialization rule.

*Cost:* a shared read-only line missed by two domains at the same moment is fetched twice from
SDRAM. The precondition is cross-domain shared memory, which is the same precondition as `P-R6`
and is not removable — see `P-R6(c)`.

**`P-R5` — per-domain fairness at the L2 arbiter.** §5.3's class priority is unchanged and remains
the outer key; the change is *within* a class. Where two or more domains have a request pending in
the same class, selection is **deficit round robin** over domains with a per-domain quantum
`L2DRRQ[d]`: a domain that has consumed its quantum in the current round is passed over until the
round completes and the unused remainder carries forward. `L2DRRQ` is hyperprivileged like
`L2WAYMASK`; equal quanta are the reset state, and with one domain active the behaviour is §5.3
unchanged.

*This is a bound, not a closure, and §16.3 marks it so.* DRR bounds the rate at which one domain
can delay another; it does not remove the dependence, and it does nothing at all below the L2 —
the memory-clock-layer interface of §13.4 is a single request port, and in the shipping SoC the
arbitration under it is `jcore-soc/components/misc/bus_mux_typecsub.vhm`'s unweighted rotating
priority over positional masters, which carries no domain identity at all. **`P-E3`** owes the
measured bound, because [security/threat-model.md §8](../security/threat-model.md) **L5** requires
"a bandwidth-QoS bound measured, not asserted".

**`P-R6` — no cross-tenant page deduplication; and the clause that says why deciding that is not
enough.** Three parts, and the third is the one that changes another decision:

- **(a) The host must not deduplicate across tenants.** There is no "per-tenant KSM" to configure:
  on `linux@origin/jcore`, KSM's merge scope is every opted-in `mm_struct` system-wide, held on
  one `ksm_mm_head` list with one stable/unstable tree pair, and the **only** partitioning axis in
  the code is the NUMA node (`ksm_merge_across_nodes`). There is no cgroup, namespace or container
  boundary in it. The available control is therefore on or off, and in the host it is **off**:
  `CONFIG_KSM` is `depends on MMU` with no arch dependency, and neither `arch/sh/configs/j2_defconfig`
  (which has no `CONFIG_MMU`, so KSM is not even offerable) nor `arch/sh/configs/jcore_defconfig`
  (which has `CONFIG_MMU=y`, so it is) sets it.
- **(b) KSM inside one guest is permitted.** Observer and victim are then the same tenant, which is
  where [security/threat-model.md §10](../security/threat-model.md) puts intra-guest channels. The
  requirement as written in **L5** — "no cross-tenant page deduplication" — is a *scope*, and
  reading it as "no page deduplication" would cost a tenant a feature for nobody's benefit.
- **(c) Deciding (a) does not remove cross-tenant shared memory.** §16.1's own justification for
  leaving hits unrestricted names the other source in its own words: "shared read-only mappings
  (the hypervisor's own text, a shared page)". Those lines are shared across domains **by
  construction**, not by deduplication, so the Flush+Reload precondition survives the dedup
  decision intact. Any argument of the form "we disabled KSM, so there is no shared memory, so
  Flush+Reload does not apply" is false here, and §16.3 marks the resulting channel **accepted**
  rather than closed.

**`P-R7` — `movca.l` allocates a fully defined line.** §17.5's table previously read that the line is allocated in
`M` "with only the written word defined and the remainder undefined until written". It is now: the
line is allocated in `M` with `R0`'s word at its offset and **every other byte zero**. The word
"undefined" is withdrawn.

*Why zero-fill rather than a per-sub-word written mask.* A mask (8 bits per line at
`L2_LINE_BYTES = 32` and 4-byte sub-words) would add tag-array state and a read-side mux, and it
would have to be maintained through eviction and through every coherence transition of §7.5.
Zero-fill adds one data-array write and **keeps the instruction's entire reason for existing**:
`movca.l`'s saving is that it does not read the line from SDRAM, not that it skips the array
write, and §17.5's own stated use is `clear_page`, which wants zeros. The extra write is not
measured and no figure is offered for it.

**`P-R8` — cache-control facilities are hyperprivileged, and the one that ships today is not.**
The L2's own control block is already on the right side: [soc/p4-mmio-map.md §3](../soc/p4-mmio-map.md)
places the L2 CSRs of §13.5 at `0xFF040000` in P4, marked not guest-visible, and a guest's P4
accesses trap wholesale. The rule generalises that: **any facility that can invalidate, flush or
lock a cache line belonging to a domain other than the issuer's must be reachable only from
hyperprivileged state.**

It is written as a rule because the shipping SoC violates it. `jcore-cpu@origin/master`'s
`cache/icache_modereg.vhm` decodes a cache-control register whose word at offset `0x0` carries
core 0's `ic0_inv`/`dc0_inv` (bits 8 and 9) and whose word at offset `0x4` carries **core 1's**
`ic1_inv`/`dc1_inv` in the same bit positions — plus `int1`, an IPI, at bit 28 of the same word.
So one write invalidates the *other* core's L1-I and L1-D wholesale and interrupts it. On
`jcore-soc@origin/master` that block is instantiated by
`targets/boards/turtle_1v0/design.yaml` at `base-addr: 0xabcd00c0` — **not in P4**. Its protection
today is therefore a stage-2 page-mapping policy and not a privilege level, and under
[security/threat-model.md §8](../security/threat-model.md) **L1**, where a core is a tenant, a
mapping mistake hands one tenant a whole-cache flush of another's core.

**The J4 requirement is the per-core split, and the P4 move is rejected.** *(Decided post-F,
2026-09-09. This rule previously offered "move into P4 alongside the L2 CSRs, **or** split its
cross-core fields per core" as two equal options and left the choice to the integrator. It is not
open, because the two options differ in what they do to a guest kernel's DMA maintenance and
[decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md) decision 4 builds that
maintenance on this very register.)*

- **Rejected — move the block into P4.** P4 is `SR.MD = 1` and a guest's P4 accesses trap
  wholesale, so the register would become unreachable from a guest *at all*. 0010 decision 4
  requires `__flush_purge_region` / `__flush_invalidate_region` to do real work on every streaming
  `dma_map_*` / `dma_sync_*`; behind a wholesale P4 trap each of those becomes a hypercall on the
  DMA hot path. Nothing in this specification can price that, and the DMA API's callers cannot see
  it, so the P4 move turns a correctness fix into a performance cliff that appears only under
  virtualization.
- **Required — split the cross-core fields per core.** Each core's cache-control word becomes a
  separate facility at a separate address, on its own page so a stage-2 mapping can grant it per
  core. Core 0 then has no architectural means of invalidating core 1's L1s, and the control a
  guest kernel needs stays guest-reachable.

**Why the split satisfies this rule rather than merely narrowing it.** Two steps, both checkable.

1. *A core's own L1 belongs to the core's own domain.* [`T-R1`](../hypervisor/hardware-spec.md)
   ([hypervisor/hardware-spec.md §4.7.2](../hypervisor/hardware-spec.md)) refuses `HRTE` unless
   every co-resident context on the core carries the same `HTCR.TENANT`, so under the FGMT default
   path of [decisions/0009](../decisions/0009-in-order-fgmt-is-the-default-path.md) the contexts
   sharing one L1 are one tenant. A per-core facility therefore reaches lines belonging to the
   issuer's own domain and to the hypervisor, and to no other tenant.
2. *Reaching the hypervisor's own lines confers nothing new.* The shipping L1s are direct-mapped
   and 8 KB — `jcore-cpu@origin/master:cache/cache_pkg.vhd` sets `cache_line_width_bits` to 5
   ("32 byte lines") and `cache_index_bits` to 8 ("8k byte cache"), with one valid bit per line and
   no way dimension — so any code running on that core can already evict every line in it by
   touching 8 KB of its own memory. A whole-cache invalidate is a faster spelling of a capability
   the issuer has by construction. This rule is about *cross-domain* reach, not about invalidation
   as such.

**What the split costs, which the previous text did not carry: the IPI shares the word and is
load-bearing today.** Bit 28 is not a stray field. `linux@origin/jcore`'s
`arch/sh/kernel/cpu/sh2/smp-j2.c` sends **every** J-Core IPI by read-modify-writing bit 28 of the
target core's word — its own comment reads *"Generate the actual interrupt by writing to CCRn bit
28"* — and `jcore-soc@origin/master:targets/boards/turtle_1v0/board.dts` hands Linux the same two
words twice, once as `jcore,cache` (`cpu-offset = <4>`) and once as `jcore,ipi-controller` at
`0xabcd00c0`. An IPI is cross-core by definition and cannot be split per core, so this is not a
relayout of one block: it separates a per-core cache control from a cross-core interrupt facility,
and the interrupt facility needs its own privilege argument rather than inheriting the cache one.
The specified destination for it is [aic/aic2-spec.md §3.5](../aic/aic2-spec.md)'s `IPI_SEND`,
which is itself unbuilt — the shipping boards carry `jcore,aic1`. So this rule has a second SoC
dependency and a second kernel dependency, in `smp-j2.c`, beside the `cache-j2.c` one 0010 names.

Until the split happens the mapping policy is the only control and it belongs on the reviewed list.
Recorded as a defect with an owner in [security/threat-model.md §11](../security/threat-model.md);
the kernel half is [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md)
decision 4, which is written against this same register and carries the matching constraint.

### 16.3 What partitioning does not close `[T1/T2]` *(C2e, 2026-09-09)*

The point of this table is that **an accepted channel with a stated reason is a legitimate
outcome and an undocumented one is a defect**. `closed` means the mechanism removes the
dependence; `mitigated` means it bounds it; `accepted` means this design does not intend to close
it at launch and says why.

§16.2 leaves **10** residual channels, classified below: four **closed**, two **mitigated**, four
**accepted**.

| # | Channel | Status | Mechanism, or the reason for accepting it |
|---|---|---|---|
| 1 | **Allocation / occupancy** — prime-and-probe across sets | **closed** | §16.1. The attacker cannot allocate into the victim's ways, so it cannot build the eviction set |
| 2 | **Replacement metadata** — a victim's hit moving a pLRU node the attacker reads | **closed** | `P-R2`(a)+(b), bought with `P-R1`'s alignment constraint |
| 3 | **L2 MSHR occupancy** — 4 entries shared chip-wide | **closed** | `P-R3`. Static reservation with no shared remainder; the pool grows with the domain count |
| 4 | **MSHR coalescing on a shared line** | **closed** | `P-R4`. Not previously named anywhere; it survives `P-R3` because it is about sharing an entry rather than occupying one |
| 5 | **Bank contention / bank FIFO** | **mitigated** | Banks are selected by `address[11:10]` (§5.1), which is independent of the way partition, so two domains always contend for banks. `P-R5` bounds the rate. **Closing it needs bank partitioning, which is set-partitioning under another name, and §16.1 rejects that for a reason that has not changed**: it would give each domain a fraction of the physical address space |
| 6 | **Memory bandwidth at the L2 arbiter** | **mitigated** | `P-R5`, with the bound owed as `P-E3` rather than asserted |
| 7 | **DRAM row-buffer contention** | **accepted** | Below the L2 entirely; §13.4 is a single request port and nothing on the memory path carries a domain identity. Already `[accepted]` at [security/threat-model.md §10](../security/threat-model.md) item 4, and this section does not reopen it |
| 8 | **Cross-partition architectural hit on a shared line** (Flush+Reload's reload half) | **accepted** | §16.1 permits hits in any way *by design*, so that coherence and shared read-only mappings work. `P-R6`(c) is why removing KSM does not remove the precondition: the hypervisor's own shared text is shared by construction. The alternative — confining hits to the partition — is Page 2005's design and it costs shared pages outright. `P-R2`(b) removes the metadata half of the signal; the timing half remains |
| 9 | **Inclusion recall of a shared line** (§7.7) | **accepted** | A shared line lives in exactly one way, so it lives in exactly one domain's partition. When that domain's allocation pressure evicts it, §7.7 recalls the *other* domain's L1-D copy, and the other domain observes a latency event caused by the first domain's allocation rate. Way-partitioning cannot close this, because the line is deliberately not duplicated. Precondition is again cross-domain sharing, so it stands or falls with row 8. **Not previously on any list** |
| 10 | **Data-array port contention** (§10.4) | **accepted** | The port is time-multiplexed per bank across five consumer classes; §10.4 argues feasibility, not isolation. Same shape as row 5 and closed by the same thing that would close row 5, which this design does not build |

Rows 4 and 9 were found by asking Wave-3 **C2c**'s question of this cache rather than the usual
one — not *which structures leak*, but *which shared structures have no per-domain control at all*
— and both are cases where the mechanism that closes the obvious channel leaves a second one
standing beside it.

### 16.4 Experiments this section owes `[T1/T2]` *(C2e, 2026-09-09)*

Each has a kill criterion, and each is written so that it can fail. **None of them can be run
today**: there is no L2 in `jcore-cpu@origin/master` or `jcore-soc@origin/master` — every
case-insensitive `l2` match in either tree is a textio variable, an FPGA ball name, a TLB comment
or prose — so these are specified and unbuilt, exactly like §22.1a's tests.

| # | Experiment | Kill criterion |
|---|---|---|
| **`P-E1`** | Model the pLRU tree with two disjoint aligned masks and `P-R2` in force. Domain A performs a scripted hit sequence in its own ways; record every pLRU node B's victim search reads | **Killed if any node B reads was written by A.** Must be run *without* `P-R2` first and produce a non-empty set, or the experiment is vacuous — the same red-before-green discipline **L6** requires of a residue test |
| **`P-E2`** | Measure L2-level MLP and miss-service throughput for one domain, at `NUM_MSHRS=4`/2 domains and at `NUM_MSHRS=8`/4 domains, against the unpartitioned pool | **Killed if the single-domain loss from `P-R3` exceeds the cost of the alternative it replaced** — a full-L2 flush per tenant switch, which §16.1 prices at ~655 µs. If reservation is worse than flushing, reservation is the wrong mechanism |
| **`P-E3`** | Measure the interference bound `P-R5` claims: with domain A saturating its quantum, the worst-case increase in B's L2 service latency, over a fixed epoch | **Killed if the measured worst case is unbounded, or if it exceeds the bound the hypervisor's admission policy assumes.** An asserted bound does not discharge **L5**; this row exists because that is stated there in those words |
| **`P-E4`** | `movca.l` residue test, per **L6**: tenant A writes a recognisable pattern through the L2; tenant B issues `movca.l` to a line whose physical address A used, then reads the bytes it did not write | **Must be demonstrated red before `P-R7` and green after.** If it cannot be made red, the test is not testing `P-R7` |
| **`P-E5`** | Enumerate every path by which one domain can cause an invalidate, flush or lock of a line in another domain's ways, and check each against `P-R8` | **Killed if any path exists that is reachable from non-hyperprivileged state.** The known one is the `0xabcd00c0` register of `P-R8`; the experiment exists because that one was found by reading the SoC's board YAML, which is not where anyone looks for a security control |
| **`P-E6`** | Elaborate the L2 with `NUM_DOMAINS > 1` on a model whose CPU reports `CPUINFO[18] = TENANCY_CHECK` **clear** — no `HTCR`, hence no domain tag *(added post-F, 2026-09-09)* | **Killed if elaboration succeeds.** This is the failure §16.1 shipped with and nobody could see: a partition whose tag register is absent on the microarchitecture [decisions/0009](../decisions/0009-in-order-fgmt-is-the-default-path.md) makes the default, isolating nothing while [hypervisor/hardware-spec.md §4.7](../hypervisor/hardware-spec.md) asserts the channel closed. A build that cannot carry the tag must refuse to build the partition rather than build an inert one |

---

## 17. Write Policy and Dirty Bit Handling `[T0/T1/T2]`

### 17.1 L1-D write policy: write-through at `[T0]`, write-back at `[T1/T2]`

**This section owns the L1-D write policy.** The heading previously read
"Write-through from L1-D", which contradicted this section's own body and was
the visible half of a contradiction running through §2, §10.2 and §17.1 against
§6.3, §7.2, §7.4, §7.5 and §17.2. The decision, its evidence in the shipped RTL,
the S/I-only alternative it rejects and the DMA obligation it creates are
[decisions/0007](../decisions/0007-l1d-write-policy-under-msi.md).

- **`[T0]` — write-through, no-allocate on store.** Every store reaches the L2.
  This is what `jcore-cpu@master` implements: `cache/cache_pkg.vhd`'s L1 line
  state is a **valid** array with no dirty bit, so an L1-D line cannot be
  modified-and-held, and `cache/dcache_ccl.vhm` emits a
  `CACHE_DCMD_WRITESGL_*` / `CACHE_DCMD_WRITEMISS` for every write.
- **`[T1/T2]` — write-back under MSI.** L1-D writes flow as a coherence message
  (`GetM` or `Upgrade`, then the store lands in the `M` line), finalized with a
  `Wb` on `Downgrade`, `Recall` or eviction. `M` means dirty-and-exclusive, per
  §7.2; the state is unreachable under a write-through L1-D, which is why the
  two halves of the spec could not both be right.

In both tiers the L2 tag-array `dirty` bit is set whenever the L2 holds the only
up-to-date copy, and the L2 itself is **write-back toward SDRAM** at every tier
(§2, §17.2) — that half was never in dispute.

**DMA is not coherent at any tier, and gets harder at T1/T2.**
[bus/fabric-spec.md §7](../bus/fabric-spec.md) puts only the L2 and the per-core
L1-D snoop ports on the snoop bus, and the directory's `dir_vec` has one bit per
core (§7.3), not per bus master. At `[T0]` the write-through L1-D means memory
is never stale with respect to a CPU, so only device→CPU needs an invalidate. At
`[T1/T2]` a dirty line can sit in an L1-D that no device transaction snoops, so
the CPU→device direction needs an explicit write-back (`ocbwb`/`ocbp`, §17.5)
or an uncached mapping. See
[decisions/0007](../decisions/0007-l1d-write-policy-under-msi.md) §"The DMA
consequence" for what this asks of `arch/sh`, and for the routing question it
leaves open.

### 17.2 Eviction of dirty lines

Unchanged in structure from v1. T1 adds: before evicting, if `dir_vec ≠ 0` send a Recall (§7.5 last row) and merge any Wb data before performing the SDRAM write.

### 17.3 L1-I never writes

Unchanged.

### 17.4 Inclusion invariant maintenance

T0: L1-I and L1-D invalidations on eviction (via the v1 inval interface). T1/T2: Recall to all L1-Ds in `dir_vec`; L1-I incoherence stays orthogonal (§7.6).

### 17.5 Software cache-maintenance instructions `[T0/T1/T2]`

The MMU and lazy TLB-shootdown protocol ([mmu/design-spec.md §4.6](../mmu/design-spec.md)) are driven by the SH-4 operand-cache-maintenance instructions, which the current J2 does not implement. These are user-mode instructions (no `SR.MD` privilege) that issue at the L1-D and resolve through the L2 coherence path. The SH-4 operand-cache block is 32 bytes, which matches the baseline `L2_LINE_BYTES=32` (§4) one-to-one; for `L2_LINE_BYTES=64` each instruction operates on the 32-byte sub-block and the L2 action applies to the containing line. All five are absent from J2 and are catalogued in [docs/sh4-nonfpu.json](../sh4-nonfpu.json) (Tier-2, "cache").

| Instruction | Encoding | L1-D action | L2 / coherence action (T1/T2) |
| ----------- | -------- | ----------- | ----------------------------- |
| `ocbwb @Rn` | `0000nnnn10110011` | Write back if dirty; line **stays valid** (clean) | If L1 line is `M`: `Wb` to L2, downgrade local copy `M→S`, L2 `dirty` set. No directory change for other cores. |
| `ocbp @Rn`  | `0000nnnn10100011` | Write back if dirty, then **invalidate** | `M→I`: `Wb` then drop; clear this core's `dir_vec` bit at L2. Clean line: silent local invalidate. |
| `ocbi @Rn`  | `0000nnnn10010011` | **Invalidate without writeback** | Drop the L1 line and clear `dir_vec` bit *without* flushing — architecturally discards dirty data (programmer's responsibility per SH-4). The L2 copy, if any, is unaffected; no `Wb` is generated. |
| `pref @Rn`  | `0000nnnn10000011` | Non-binding fill hint into L1-D | Issues `GetS` to L2 (droppable under contention, §5.3 priority 7). Used by the TLB-miss handler to prefetch the `TSBPTR` slot ahead of the tag load ([mmu/hardware-spec.md §7](../mmu/hardware-spec.md)). |
| `movca.l R0,@Rn` | `0000nnnn11000011` | Store R0, **allocating the block without fetching** it from memory | `GetM` *without* the read-for-ownership fill: the line is allocated in `M` with `R0`'s word at its offset and **every other byte zero** (§16.2 `P-R7`). Fast `clear_page`. |

**Privilege, and the plan item that did not survive checking against this table.** The Wave-3 C2
worklist asks whether user-mode `ocbi`/`ocbp`/`pref` — "a Flush+Reload primitive across the
partition" — needs privilege gating. **The premise is false for the L2 partition, and this table is
where it fails.** Read the L2 column: `ocbwb` writes back and downgrades the *local* copy; `ocbp`
clears *this core's* `dir_vec` bit; `ocbi` drops the local line and, in this table's own words,
"the L2 copy, if any, is unaffected". **None of the three evicts anything from the L2**, so none of
them is the flush half of a Flush+Reload against an L2 way partition. What they flush is the
issuing core's own L1-D, and a core is one tenant
([security/threat-model.md §8](../security/threat-model.md) **L1**), so the observer and the victim
are the same tenant — the position [security/threat-model.md §10](../security/threat-model.md)
already takes on intra-guest channels.

**The decision, therefore: `ocbi`, `ocbp` and `ocbwb` stay user-mode, unchanged from SH-4.** The
cost of that decision is not zero and is stated rather than waved at: it leaves the *reload* half
of the primitive available (§16.3 row 8), and it means a future reviewer who reads only the
worklist will think a gate is missing. The cost of the alternative was the one that decided it —
gating them changes the ISA's user-visible surface for every SH-4 binary, and buys nothing against
the channel it was proposed for.

**Two things do need the mask, and one of them is already covered.** `pref` and `movca.l`
*allocate* — `pref` issues `GetS`, `movca.l` issues `GetM` — and allocation is already confined by
`L2WAYMASK` under §16.1, which restricts "a fill", not "a demand miss". §16.1 now says so
explicitly, because a reader of this section could not previously see it. That makes the
"privileged flush ops" item **already discharged by §16.1** for the two instructions where it
matters and **not applicable** for the three where it does not. What is genuinely open is a
*register*, not an instruction: §16.2 `P-R8`.

**These five instructions do not exist in any J-Core.** `jcore-cpu@origin/master`'s
`docs/insns.json` records `"J1": false, "J2": false, "J2A": false, "J4": false` for each, none is
decoded anywhere under `decode/`, and this section already says they are absent from J2. So the
decision above is free to make now and would not be free later, which is the reason to make it
now.

**Coherence interaction (T1/T2).** `ocbi` is the one sharp edge: in a coherent MSI cache it must clear only the issuing core's directory bit and must not emit a writeback, so a dirty line is silently lost — correct per SH-4 semantics, but the kernel must reserve `ocbi` for pages it knows are clean or being discarded. `ocbp`/`ocbwb` are the safe flush primitives the TLB-shootdown path (§7) and TSB-store→MMU-read coherence ([mmu/hardware-spec.md §1](../mmu/hardware-spec.md)) rely on to make a PTE write visible before `LDTLB`. On T0 (no L2 coherence, single L1-D) these reduce to local L1-D operations plus the existing write-through path.

---

## 18. Locked Accesses (T0 only) `[T0]`

Retained from v1 for T0 deployments and for the optional-L2 J32 variant. When `locked='1'` on an incoming L1-D request and the deployment is T0, the L2 does not look up its tag array; the request is forwarded directly to the mcl with the lock signal asserted, preserving the existing dcache state machine behavior.

**T1/T2 removes this path.** The L1-D's lock state machine instead issues `GetM-Locked` and `Unlock` to L2 per §6.3. The old `L2_FLUSH_CMD` after a locked write (v1 §14) is no longer needed because the line-lock protocol keeps L2 in sync.

---

## 19. Performance Characteristics `[T1/T2]`

### 19.1 Snoop and coherence latency

| Path                                                | Cycles   |
| --------------------------------------------------- | -------: |
| Snoop Inv (L2 → L1-D → Ack)                         |     4–6  |
| Snoop Downgrade with Wb merge                       |     6–10 |
| Snoop Recall (eviction-triggered)                   |     6–10 |
| GetS hitting Modified in another L1 (Downgrade)     |    9–13  |
| GetM hitting Shared in others (multi-Inv)           |    7–11  |

### 19.2 CAS.L cost vs bus-lock

| Metric                                          | Bus-lock (v1) | Line-lock (v2)    |
| ----------------------------------------------- | ------------: | ----------------: |
| Uncontended CAS.L (one CPU, no other lock holder) | ~8 cycles    | 8–10 cycles       |
| Contended CAS.L (two CPUs racing the same line) | bounded by bus arb | NACK+retry; ~15–25 cycles per attempt |
| Throughput impact on unrelated traffic          | severe (bus blocked) | none (only locked line) |

For the project's target workloads — short CAS.L sections in futexes and Linux kernel locking primitives — the line-lock path is comparable in single-CAS latency and dramatically better in aggregate system throughput.

### 19.3 Working-set hit-rate curve

Unchanged from v1 §16.3 (capacity-driven; coherence does not change capacity).

---

## 20. BRAM Mapping for ECP5 `[FPGA]` `[T0/T1/T2]`

### 20.1 EBR allocation summary (T1 baseline)

| Component                                          | EBRs per bank | × 4 banks | Total |
| -------------------------------------------------- | ------------: | --------: | ----: |
| Data array (32 KB / 8-way)                         |            15 |        60 |    60 |
| Tag array (T1: tag+valid+dirty+dir+lock = 35 b)    |             2 |         8 |     8 |
| pLRU state                                         | (distributed) | (distributed) | 0 |
| MSHR storage (T1: includes coh_install_state)      | (shared, distributed) |   | 1 |
| Writeback queue                                    | (shared, distributed) |   | 0 |
| Directory bits (folded into tag)                   |          (incl. above) |   | 0 |
| Lock state machine (per bank, distributed)         | (distributed) | (distributed) | 0 |
| **Subtotal**                                       |               |           | **~69** |

Approximately identical EBR count to v1 (the directory and lock bits fit inside the existing tag-array headroom). Allowance for a small snoop-port FIFO at each L1-D adds 0 EBRs (distributed RAM). These counts are **capacity arithmetic** — array size divided by the 18 Kb EBR — not a synthesis result, which is why they are stated exactly rather than as unknowns.

T2 grows tag array by +8 bits/line → +~2 EBRs total → **~71 EBRs**.

**This section owns the L2's EBR count: `L2 EBR = 69` at T1** (the Subtotal
above, 60 data + 8 tag + 1 MSHR), 71 at T2. It is registered as `cache.l2.ebr`
in [fact-ownership.md](../fact-ownership.md) with a value guard, so no other
document may state a different number for the same array.

On ULX3S 85F (208 EBRs total), the L2 uses ~33% of available BRAM. Combined with two cores' worth of L1-I and L1-D (4 × ~18 EBRs = 72 EBRs), the full **dual-core coherent** cache hierarchy uses **~68% of ULX3S BRAMs** — 72 + 69 = **141** of 208. Within budget for J32-FM on ULX3S 85F.

**Read the scope, not just the number.** This 141 counts **two** cores' L1 pairs
plus one L2. [ooo/j32ooo-spec.md §11.5](../ooo/j32ooo-spec.md)'s ~105 counts
**one** core's L1 pair plus the same L2, so the difference is exactly one L1 pair:
18 + 18 = 36, and 105 + 36 = 141. The two were tracked as a "104 vs 141"
contradiction; they are the same capacity arithmetic over different machines.

*Until 2026-09-08 the other document booked this same L2 at 68, so its one-core
total was 104 and the difference came to 37 against an L1 pair of 36. The
scope explanation above was written while that 1-EBR residual was still there and
did not account for it — a resolution that left a smaller instance of the thing it
resolved. The subtotal in this section's own table is the arithmetic that settles
it, which is why the fact is owned here.*

### 20.2 Synthesis considerations

Unchanged from v1: time-multiplex within bank with a 1-cycle pipeline stage for arbitration. Snoop traffic gets a dedicated 1-cycle slot every 4 cycles guaranteed (round-robin among the bank's port consumers) to bound snoop latency.

### 20.3 Power — `[ASIC]` only

Energy and power are `[ASIC]`-only for this project
([j4-remediation-plan.md](../j4-remediation-plan.md) guiding principle 1 and
Track D0): energy is not measurable on the ECP5, and Phase-1's goals are
correctness, area and boot-to-Linux.

**L2 power, static and dynamic: unknown at this stage — needs measurement.**
A gate-level power run under the gf180 flow (Track D0), driven by switching
activity from a real trace, produces it — tagged `[ASIC]` with the node it
used.

---

## 21. Gate-Budget Delta vs v1 `[T1/T2]`

| Component                                       | v1 LUT4 | v2 (T1) LUT4 | Delta  | Notes                                       |
| ----------------------------------------------- | ------: | -----------: | -----: | ------------------------------------------- |
| L2 banks (data/tag/pLRU control)                |   2,400 |        2,600 |   +200 | Wider tag compare for dir bits              |
| L2 arbiter + bank steering                      |     400 |          500 |   +100 | Extra priority class for snoops             |
| MSHR pool                                       |     300 |          400 |   +100 | New coh_install_state field, coalesce rule  |
| Writeback queue                                 |     200 |          200 |     0  |                                             |
| Directory FSM (per bank × 4)                    |       — |        2,400 | +2,400 | New                                         |
| Snoop fabric driver (broadcast)                 |       — |          400 |   +400 |                                             |
| Lock state machine (per bank × 4)               |       — |          800 |   +800 | LOCKED bit, owner check, age scanner        |
| In-flight per-line tracker (per bank × 4)       |       — |          400 |   +400 |                                             |
| CSR block                                       |       — |          200 |   +200 | New L2_SNOOP/_LOCK counters                 |
| **L2 subtotal (LUT4 equiv.)**                   |   3,300 |        7,900 | +4,600 |                                             |
| **L2 EBR**                                      |     ~69 |          ~69 |     0  | T2 adds +2 EBRs                             |
| **L1-D snoop-port upgrade (per core × 2)**      |       — |          600 |   +600 | Extends `dcache_snoop_io_t` v2              |
| **L1-D MSI state bits (per core × 2)**          |       — |          200 |   +200 | 2 extra tag bits and update logic           |

Total system delta v1 → v2 at T1: **+5,400 LUT4 equivalents** in the cache subsystem — a budget, like every other figure in this table.

**What the v2 L2 costs as a *fraction* of the core is unknown at this stage — needs measurement.** This sentence previously read that it "adds ~12% to the cache LUT count and ~3% to the full core-plus-cache LUT count", both derived from a citation of [j32ooo-spec.md §15](../ooo/j32ooo-spec.md) reading "248k gates ≈ 35–45k LUT4". Every part of that citation is now wrong: §15's gate total is **256,850**, not 248k, and its LUT4 conversion was **removed** under [decisions/0005](../decisions/0005-unmeasured-figures-are-removed.md) because it was arithmetic on an estimate at an unvalidated gates-per-LUT4 ratio. A percentage whose denominator has been retracted is not a smaller claim than the denominator — it is the same claim with the retraction hidden, which is why the percentages go rather than being re-based. `ooo.gates.core` in [fact-ownership.md](../fact-ownership.md) now guards the numerator so this cannot recur silently.

**The whole of this section is a budget, not a measurement.** It says what the
design is allowed to cost, and the ~50% LUT / ~70% BRAM ECP5-85F utilisation it
implies — leaving room for FPU, SIMD and SoC peripherals — is the budget's own
arithmetic. Whether the RTL meets it is unknown at this stage — needs measurement; `yosys` + `nextpnr-ecp5` on the
ULX3S 85F is what answers that.

T2 additional delta over T1: negligible LUT (~+100 for wider compares), +2 EBRs (wider tags).

---

## 22. Verification Plan `[T0/T1/T2]`

### 22.1 Unit-level (T0/T1/T2 — common)

- Tag array, data array, pLRU, MSHR, writeback queue: as v1 §19.1, with tag width extended to T1/T2 fields.

### 22.1a Way partitioning (§16.1, T1/T2)

- **Allocation confinement**: with disjoint `L2WAYMASK` values, a domain streaming through memory
  large enough to thrash the L2 evicts **no** line belonging to another domain. Check by tag-array
  inspection, not by timing — the point is a structural invariant, not a measurement.
- **Hits are unrestricted**: a domain hits a line resident in a way outside its own mask, and the
  hit does not migrate or re-allocate the line.
- **pLRU interaction**: with a mask of one way, allocation always targets that way; with a mask
  whose ways are all `LOCKED`, the bank stalls exactly as §16's all-locked case, not silently
  spilling outside the mask.
- **Reset behaviour**: an all-ones mask reproduces unpartitioned v0.2 behaviour bit-for-bit — the
  T0 and non-virtualized regression.
- **Negative control**: with masks deliberately overlapping, the confinement test above must
  **fail**. A partitioning test that passes with the partition disabled is not testing anything.

### 22.1b Isolation beyond ways (§16.2, T1/T2) *(C2e, 2026-09-09)*

[security/threat-model.md §8](../security/threat-model.md) **L5** requires **five mechanisms, five
tests**, and says in those words that "a single 'partitioning works' test discharges only the
first". §22.1a is that first test. These are the other four, plus the one **L6** requires of
`P-R7`. Each names the rule it discharges, so that a passing suite with a missing row is visible.

- **Metadata (`P-R2`)** — a *victim's hits* in the attacker's ways must not change what the
  attacker observes. Drive domain A through a scripted hit sequence in ways it does not own and in
  ways it does; snapshot every pLRU node domain B's victim search reads, before and after. The
  observable is the node set, not a timing measurement, for §22.1a's reason. **Negative control:**
  with `P-R2` disabled the same test must **fail**, and `P-E1` requires it to have been seen
  failing.
- **L2 MSHRs (`P-R3`, `P-R4`)** — at the **L2** pool, not the core-side pool of
  [ooo/j32lt-spec.md §7.4](../ooo/j32lt-spec.md), which already has evidence and is the wrong
  structure. One domain saturating its reservation must not alter another domain's observable miss
  latency beyond its own reserved share (`P-R3`); and two domains missing the same line at the same
  time must produce **two** SDRAM reads, not one coalesced entry (`P-R4`). The second is not
  implied by the first.
- **Bandwidth (`P-R5`)** — the bound is a **measurement**, not an assertion: `P-E3`. A test that
  shows DRR is wired up but never measures the residual interference does not discharge this.
- **Dedup (`P-R6`)** — prove no page is shared across tenants *by deduplication*: with the host's
  KSM off, a page identical in two guests must have two distinct host PFNs. **This test cannot
  prove there is no cross-tenant shared memory**, only that dedup did not create any — the
  hypervisor's own shared read-only mappings are shared by construction (`P-R6`(c)), and §16.3
  row 8 is where that is accepted.
- **Flush reach (`P-R8`)** — a privilege test *per facility that can reach another domain's lines*,
  which after §17.5's decision is a register and not an instruction. The `0xabcd00c0` block of
  `P-R8` must be unreachable from guest state; `P-E5` enumerates the paths.
- **`movca.l` residue (`P-R7`)** — the **L6** test, `P-E4`: tenant A writes a recognisable
  pattern, tenant B `movca.l`s the line and reads the bytes it did not write, and must see zeros.
  **Demonstrated red before the fix**, which is L6's stated bar and which nothing in this section
  can satisfy while there is no L2 to run it on.

### 22.2 Coherence-specific (T1/T2)

- **MSI state-machine coverage**: directed tests driving each transition in §7.5 from each starting state. Self-checking testbench compares post-state to expected. Coverage goal: 100% of transitions, 95% of two-step paths.
- **Inclusion enforcement**: cause L2 eviction of a line resident as M in an L1-D; verify Recall fires, Wb arrives, SDRAM is correct, L1-D drops the line. Repeat for S (Recall+Inv) and for the multi-holder case.
- **Snoop ACK timing**: vary L1-D port-availability; verify the L2 waits for Ack correctly and does not drop the in-flight slot.
- **Per-line serialization**: launch concurrent GetS and Inv to the same line; verify the bank serializes them.
- **L1-I incoherence sanity**: write through L1-D to a line that's also in an L1-I; verify the L1-I serves the *stale* data (correct per §7.6) until an explicit flush.

### 22.3 Atomicity-specific (T1/T2)

- **Locked-CAS contention**: two cores spin-CAS on the same address for 10⁹ iterations; verify no torn updates, verify NACK count is finite per successful CAS, verify forward progress (every core eventually wins).
- **Lock timeout**: artificially stall an L1-D mid-CAS so its Unlock never arrives; verify the L2 timeout fires at `LOCK_TIMEOUT_CYC`, clears LOCKED, increments `L2_LOCK_TO_CNT`, and the L1-D recovers as compare-fail.
- **FGMT thread-pair atomicity**: thread A on core 0 holds the lock; FGMT scheduler switches to thread B on core 0; B's load to the locked line stalls until A's Unlock arrives. Verify with a targeted testbench (no real workload exercises this naturally).
- **CAS.L atomicity regression**: existing `testrom/tests/testmov.s:580-635` must pass with the L2 line-lock path enabled. Run also with L2 disabled (T0 bypass path) to verify J2 compatibility.

### 22.4 Multi-core integration (T1/T2)

- **Multi-core boot**: dual-core boot via `cpus_two_fpga.vhd`; both cores reach Linux userspace through a coherent L2. Verify no kernel panics, no oopses, no random data corruption.
- **Lazy TLB shootdown sanity**: cross-core lazy TLB invalidation per [mmu/design-spec.md §4.6](../mmu/design-spec.md). Verify a PTE update on core 0 is observed by core 1 via cache coherence (not via IPI). Specifically: core 0 unmaps a page; core 1 attempts to dereference; verify the SIGSEGV occurs at the expected point.
- **vCPU migration sanity** ([hypervisor/linux-spec.md §8](../hypervisor/linux-spec.md)): migrate a vCPU's working set from core 0 to core 1; verify post-migration memory contents are coherent without an explicit flush.

### 22.5 System-level

- **Linux boot SMP**: full Linux SMP boot through to userspace. Verify SMP CAS.L stress (kernel locking primitives, libatomic, `stress-ng --futex`) under coherence.
- **PMU validation**: read counters after known workloads; verify counts match theoretical expectations.

### 22.6 Regression integration

The existing J-core verification corpus (`testrom/tests/*.s`, `cache/tests/`, `tests/*.vhd`) runs against the L2-augmented system. CAS.L atomicity tests in `testmov.s:580-635` are the canonical regression — must pass with L2 enabled (T1 line-lock), with L2 in T0 bypass mode, and with no L2 at all (J2 path).

---

## 23. VHDL Entity Skeleton `[T0/T1/T2]`

```vhdl
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.l2_pkg.all;

entity l2_cache is
    generic (
        L2_SIZE_KB           : integer := 128;
        L2_WAYS              : integer := 8;
        L2_LINE_BYTES        : integer := 32;
        NUM_BANKS            : integer := 4;
        NUM_MSHRS            : integer := 4;
        WAY_SELECT_PIPE      : boolean := false;
        ADDR_WIDTH           : integer := 32;    -- 32 (T0/T1) or 40 (T2)
        NUM_CORES            : integer := 1;     -- 1 (T0) or ≥2 (T1/T2)
        NUM_THREADS_PER_CORE : integer := 1;     -- 1 or 2 (FGMT)
        NUM_DOMAINS          : integer := 1;     -- §16.1 trust domains, incl. host domain H
        LOCK_TIMEOUT_CYC     : integer := 256;
        SNOOP_FABRIC         : string  := "broadcast"
    );
    port (
        clk         : in  std_logic;
        rst         : in  std_logic;

        -- Per-core L1-I read interfaces
        l1i_req_i   : in  l2_l1i_req_array_t(0 to NUM_CORES-1);
        l1i_resp_o  : out l2_l1i_resp_array_t(0 to NUM_CORES-1);

        -- Per-core L1-D coherence message ports
        l1d_port    : inout l2_l1d_port_array_t(0 to NUM_CORES-1);

        -- Per-core L1-D snoop ports (drives invalidations / downgrades / recalls)
        snoop_o     : out dcache_snoop_v2_array_t(0 to NUM_CORES-1);
        snoop_i     : in  dcache_snoop_ack_array_t(0 to NUM_CORES-1);

        -- Memory-clock-layer interface (to SDRAM)
        mcl_req_o   : out l2_mcl_req_t;
        mcl_resp_i  : in  l2_mcl_resp_t;

        -- Control/CSR interface
        csr_addr_i  : in  std_logic_vector(7 downto 0);
        csr_wdata_i : in  std_logic_vector(31 downto 0);
        csr_rdata_o : out std_logic_vector(31 downto 0);
        csr_wr_i    : in  std_logic;
        csr_rd_i    : in  std_logic;

        -- PMU event pulses
        pmu_hit_o          : out std_logic;
        pmu_miss_o         : out std_logic;
        pmu_wb_o           : out std_logic;
        pmu_inval_o        : out std_logic;
        pmu_snoop_o        : out std_logic;     -- T1/T2
        pmu_lock_to_o      : out std_logic;     -- T1/T2
        pmu_lock_nack_o    : out std_logic      -- T1/T2
    );
end l2_cache;
```

Architecture is structured as `l2_bank` × `NUM_BANKS`, `mshr_pool`, `writeback_queue`, `l2_arbiter`, `snoop_fabric`, `lock_scanner`, `l2_csr`, `tree_plru` (combinational helper). Where the `_v2` types are required they are defined in `l2_pkg`; T0 RTL using the legacy interfaces continues to compile against compatibility wrappers.

---

## 24. Open Issues and Future Work `[T0/T1/T2]`

1. **Ring snoop fabric (NUM_CORES ≥ 6)**: design deferred. Substrate is `jcore-soc/components/ring_bus/`.
2. **Optional in-L2 lock-wait queue (§7.8)**: NACK+retry is simpler; queue is the obvious upgrade if lock contention dominates a workload.
3. **MESI upgrade**: M/S/I → M/E/S/I doubles per-line L1-D state bits and adds a "first-write" tracker; defer pending evidence that snoop traffic is the bottleneck.
4. **L2 prefetcher** (cross-line, cross-core): deferred from v1; no change.
5. **ECC for L2 data**: relevant for ASIC; defer.
6. **NUMA-style L2 partitioning** for ≥4-core configurations: defer.
7. **The cache-control register at `0xabcd00c0` is outside P4** and can invalidate the other
   core's L1s (§16.2 `P-R8`). `P-R8` now *requires* the per-core split and rejects the P4 move,
   so what is open here is the SoC work and not the choice: splitting the block per core, moving
   the bit-28 IPI to a facility of its own, and giving each core's word its own page. This
   specification cannot make that change; owner is RTL / SoC integration, tracked at
   [security/threat-model.md §11](../security/threat-model.md), with the kernel half in
   [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md) decision 4.
8. **`NUM_MSHRS` above 4 is now load-bearing, not a preference.** §16.2 `P-R3` makes the pool size a
   function of the domain count, so the "defer the resize decision" of §12.3 is deferred only for
   the two-domain case.
9. **MMU coordination on TLB shootdown**: the [mmu/design-spec.md §4.6](../mmu/design-spec.md) lazy-shootdown path now relies on L1-D coherence; cross-check the actual shootdown bandwidth once both subsystems are stable.

---

## Appendix A: Glossary (cache-local terms only)

- **EBR** — Embedded Block RAM (Lattice ECP5 terminology).
- **MCL** — Memory-Clock Layer; existing J-core SDRAM controller interface.
- **MSHR** — Miss Status Holding Register (Kroft 1981).
- **pLRU** — Pseudo-LRU (tree-LRU) replacement.
- **MSI** — Modified / Shared / Invalid coherence states (Papamarcos & Patel 1984).
- **Directory** — Per-line tracking, at L2, of which L1-Ds hold the line and in which state.
- **Snoop** — A coherence message from L2 to an L1-D requiring invalidate, downgrade, or recall.
- **Recall** — A specific snoop sent during L2 eviction.
- **Lock owner** — `{core_id, thread_id}` tuple identifying who holds a per-L2-line lock.

Wider project terms (FGMT, ASID, BMID, …) live in [glossary.md](../glossary.md).

## Appendix B: Resource Cost Summary on ULX3S 85F `[FPGA]` `[T1 baseline]`

**These are budget figures, not synthesis results.** The EBR row is capacity
arithmetic (§20.1) and the DSP row is structural; the LUT4 and FF rows are the
§21 budget. Nothing here has been through `yosys` + `nextpnr-ecp5` on the
ULX3S 85F, so the utilisation actually achieved is unknown at this stage — needs measurement.

| Resource         | Count       | % of ULX3S 85F |
| ---------------- | ----------: | -------------: |
| EBRs (18 Kb)     |    ~69 (T1) / ~71 (T2) |  ~33–34% |
| LUT4 equivalents |       ~7,900 |           ~10% |
| DSP slices       |            0 |             0% |
| FFs (registers)  |       ~3,000 |            ~4% |
| Engineering effort | ~12 weeks (v1 base + coherence + line-lock) | — |
| Power adder | out of scope on `[FPGA]` — energy is `[ASIC]`-only (§20.3) | — |

## Appendix C: Cross-document anchors

- Atomicity (line-lock vs bus-lock): this spec §6 ↔ [glossary §6](../glossary.md) ↔ [j32ooo-spec.md §10](../ooo/j32ooo-spec.md) ↔ [j32ooo-spec.md §14](../ooo/j32ooo-spec.md).
- Coherence requirement: this spec §7 ↔ [mmu/design-spec.md §4.6](../mmu/design-spec.md) ↔ [hypervisor/linux-spec.md §8](../hypervisor/linux-spec.md) ↔ [fgmt/dual-fgmt-proposal.md §5.4](../fgmt/dual-fgmt-proposal.md).
- Software cache-maintenance instructions (`ocbi`/`ocbp`/`ocbwb`/`pref`/`movca.l`): this spec §17.5 ↔ [mmu/design-spec.md §4.6](../mmu/design-spec.md) ↔ [mmu/hardware-spec.md §1, §7](../mmu/hardware-spec.md) ↔ [docs/sh4-nonfpu.json](../sh4-nonfpu.json).
- Address-width parameterization: this spec §4, §8, §13.4 ↔ [glossary §3](../glossary.md) (J32 / J64 distinction).
- PMU event allocation: this spec §13.5 ↔ [j32ooo-spec.md §12](../ooo/j32ooo-spec.md).
