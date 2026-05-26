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

- **Unified**: serves all per-core L1-I (read-only) and L1-D (read/write-through) clients. Single tag and data arrays shared.
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

The lock is qualified with `{core_id, thread_id}`. FGMT context switches between threads on the same core (every cycle, per [j32ooo-spec.md §13](../ooo/j32ooo-spec.md)) do **not** release a lock held by a sibling thread:

- Thread A on core 0 holds the line lock. Cycle later, FGMT scheduler picks thread B on core 0; B issues a memory op to the same line. Since B's `{core_id=0, thread_id=1}` ≠ A's `{core_id=0, thread_id=0}`, B's GetM (or GetS) is treated like a foreign request: L2 NACKs / stalls until A's Unlock arrives.
- L1-D within a single core must track *which* thread issued the locked load so its uop3 produces an Unlock with the matching owner field. The LSQ's existing per-thread tagging ([j32ooo-spec.md §8.3](../ooo/j32ooo-spec.md)) supplies this.

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

Across 4 banks: T0 ~5 EBRs, T1 ~8 EBRs, T2 ~10 EBRs. Within ULX3S budget. In practice tags are split across multiple narrow EBRs read in parallel because EBR ports cap at 36 bits; realistic mapping is 4–6 EBRs per bank, **16–24 EBRs total** for tag storage across 4 banks at T1 — the same envelope as v1.

---

## 10. Data Array `[T0/T1/T2]`

### 10.1 Organization

Unchanged from v1. Per bank (32 KB at baseline): 128 sets × 8 ways × 32-byte lines = 32 KB per bank, each line 8 × 32-bit words, each way of each set a separate addressable region. ECP5 EBR mapping: ~15 EBRs per bank for data = **60 EBRs total** for 4 banks at the 128 KB baseline.

### 10.2 Access width

Unchanged. L2 hit returns a full line (32 bytes). Writes from L1-D are 32-bit-word write-throughs (byte-enabled).

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

---

## 13. Interfaces `[T0/T1/T2]`

### 13.1 L1-I read interface `[T0/T1/T2]`

```vhdl
type l2_l1i_req_t is record
    req_valid : std_logic;
    core_id   : std_logic_vector(log2(NUM_CORES)-1 downto 0);   -- T1+
    addr      : std_logic_vector(ADDR_WIDTH-1 downto 0);
end record;

type l2_l1i_resp_t is record
    resp_valid : std_logic;
    line_data  : std_logic_vector(8*L2_LINE_BYTES-1 downto 0);
    error      : std_logic;
end record;
```

L1-I issues a line read; L2 responds asynchronously. The `core_id` field is required at T1 so the L2 can route the response back to the originator on a multi-core fabric.

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
| `L2_STATUS`  |    32 | all   | Busy, MSHR-full, writeback-pending flags         |
| `L2_FLUSH_ADDR` |  32 | all  | Address for targeted-line flush (low 32 bits; for T2 a second register `L2_FLUSH_ADDR_HI` holds the high 8 bits) |
| `L2_FLUSH_CMD` |   32 | all  | Flush command (clean, invalidate, clean-invalidate) |
| `L2_HIT_CNT` |    64 | all   | Counter: L2 hits                                 |
| `L2_MISS_CNT`|    64 | all   | Counter: L2 misses                               |
| `L2_WB_CNT`  |    64 | all   | Counter: writebacks to SDRAM                     |
| `L2_INVAL_CNT`|   64 | all   | Counter: L1 invalidations sent (Inv+Downgrade+Recall) |
| `L2_SNOOP_CNT`|   64 | T1/T2 | Counter: snoop messages issued (Inv+Downgrade+Recall) |
| `L2_LOCK_TO_CNT`| 64 | T1/T2 | Counter: lock timeouts (§6.5)                   |
| `L2_LOCK_NACK_CNT`| 64 | T1/T2 | Counter: GetM-Locked NACKs                     |
```

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

LUT cost of directory state-machine: estimated 1.5k LUT4 equivalents for the bank-local directory FSM, snoop-issue logic, in-flight-set tracking, and lock-age scanner. Across 4 banks: ~6k LUT4. Comparable to the MSHR pool.

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

---

## 17. Write Policy and Dirty Bit Handling `[T0/T1/T2]`

### 17.1 Write-through from L1-D

L1-D writes flow as a coherence message at T1 (`GetM` or `Upgrade` then implicit write into the M-line, finalized with a `Wb` on eviction). T0 uses the v1 write-through-on-each-store path. The L2 tag-array `dirty` bit is set whenever the L2 holds the only up-to-date copy.

### 17.2 Eviction of dirty lines

Unchanged in structure from v1. T1 adds: before evicting, if `dir_vec ≠ 0` send a Recall (§7.5 last row) and merge any Wb data before performing the SDRAM write.

### 17.3 L1-I never writes

Unchanged.

### 17.4 Inclusion invariant maintenance

T0: L1-I and L1-D invalidations on eviction (via the v1 inval interface). T1/T2: Recall to all L1-Ds in `dir_vec`; L1-I incoherence stays orthogonal (§7.6).

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

## 20. BRAM Mapping for ECP5 `[T0/T1/T2]`

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

Approximately identical EBR count to v1 (the directory and lock bits fit inside the existing tag-array headroom). Allowance for a small snoop-port FIFO at each L1-D adds 0 EBRs (distributed RAM).

T2 grows tag array by +8 bits/line → +~2 EBRs total → **~71 EBRs**.

On ULX3S 85F (208 EBRs total), the L2 uses ~33–34% of available BRAM. Combined with two cores' worth of L1-I and L1-D (4 × ~18 EBRs = 72 EBRs), the full **dual-core coherent** cache hierarchy uses **~70% of ULX3S BRAMs** (141 of 208). Within budget for J32-FM on ULX3S 85F.

### 20.2 Synthesis considerations

Unchanged from v1: time-multiplex within bank with a 1-cycle pipeline stage for arbitration. Snoop traffic gets a dedicated 1-cycle slot every 4 cycles guaranteed (round-robin among the bank's port consumers) to bound snoop latency.

### 20.3 Power estimate

T1 adds ~10–15 mW dynamic across the coherence FSM and snoop driver. Total L2 power on ECP5-85F at 90 MHz: ~40–65 mW. Still negligible at FPGA scale.

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

Total system delta v1 → v2 at T1: **+5,400 LUT4 equivalents** in cache subsystem. Combined with the existing OoO budget ([j32ooo-spec.md §15](../ooo/j32ooo-spec.md): 248k gates ≈ 35–45k LUT4), the v2 coherent L2 adds ~12% to the cache LUT count and ~3% to the full core-plus-cache LUT count. **Fits on ECP5-85F alongside dual-core OoO** with ~50% LUT and ~70% BRAM utilization, leaving room for FPU, SIMD, and SoC peripherals.

T2 additional delta over T1: negligible LUT (~+100 for wider compares), +2 EBRs (wider tags).

---

## 22. Verification Plan `[T0/T1/T2]`

### 22.1 Unit-level (T0/T1/T2 — common)

- Tag array, data array, pLRU, MSHR, writeback queue: as v1 §19.1, with tag width extended to T1/T2 fields.

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
7. **MMU coordination on TLB shootdown**: the [mmu/design-spec.md §4.6](../mmu/design-spec.md) lazy-shootdown path now relies on L1-D coherence; cross-check the actual shootdown bandwidth once both subsystems are stable.

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

## Appendix B: Resource Cost Summary on ULX3S 85F `[T1 baseline]`

| Resource         | Count       | % of ULX3S 85F |
| ---------------- | ----------: | -------------: |
| EBRs (18 Kb)     |    ~69 (T1) / ~71 (T2) |  ~33–34% |
| LUT4 equivalents |       ~7,900 |           ~10% |
| DSP slices       |            0 |             0% |
| FFs (registers)  |       ~3,000 |            ~4% |
| Engineering effort | ~12 weeks (v1 base + coherence + line-lock) | — |
| Static power adder | ~40–65 mW   |              — |

## Appendix C: Cross-document anchors

- Atomicity (line-lock vs bus-lock): this spec §6 ↔ [glossary §6](../glossary.md) ↔ [j32ooo-spec.md §10](../ooo/j32ooo-spec.md) ↔ [j32ooo-spec.md §14](../ooo/j32ooo-spec.md).
- Coherence requirement: this spec §7 ↔ [mmu/design-spec.md §4.6](../mmu/design-spec.md) ↔ [hypervisor/linux-spec.md §8](../hypervisor/linux-spec.md) ↔ [fgmt/dual-fgmt-proposal.md §5.4](../fgmt/dual-fgmt-proposal.md).
- Address-width parameterization: this spec §4, §8, §13.4 ↔ [glossary §3](../glossary.md) (J32 / J64 distinction).
- PMU event allocation: this spec §13.5 ↔ [j32ooo-spec.md §12](../ooo/j32ooo-spec.md).
