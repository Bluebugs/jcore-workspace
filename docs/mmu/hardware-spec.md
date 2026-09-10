# J-Core MMU Hardware Implementation Specification

**Status:** Draft  
**Scope:** RTL implementation guide for J3 (and J64) MMU additions  
**Audience:** Hardware engineers implementing the J-Core MMU in VHDL

---

## 1. Scope

This document specifies the hardware-visible changes to the J-Core CPU to add an MMU compatible with SH-4 register conventions while extending page sizes, ASIDs, and adding a TSB pointer assist.

What's specified here:
- New control registers and MMIO registers
- New instruction encodings
- Bit-level layouts of all MMU-visible state
- The TLB miss exception sequence
- Per-CPU additions for SMP
- Reset state

What's not specified here:
- The TLB implementation strategy (CAM vs. set-associative SRAM) — implementer's choice
- Cache coherence between TSB stores and the MMU's reads — assumed to use the standard cache infrastructure
- Pipeline integration details — depends on the J3 pipeline structure

Conventions:
- Bit numbering: bit 0 is the LSB. Field `[H:L]` includes both endpoints.
- Word size: 32-bit on J32, 64-bit on J64. Where a register is "word-sized," it scales with the implementation.
- Address terms: VA = virtual address, PA = physical address, VPN = virtual page number (VA >> PageShift), PFN/PPN = physical (page) frame number.

## 2. Control Registers

### 2.1 PTEH — Page Table Entry High

Inherited from SH-4 in spirit, but **VPN-only** in this revision. Written via `LDC Rm, PTEH`; read via the **read-only P4 alias at `0xFF000000`** (`STC PTEH,Rn` is retired — see §3.1). The write side is `LDC`-only: there is no MMIO write path, by design (D7). The 16-bit `ASID_TAG` lives in the separate **ASIDR** register (see §2.1a) — a deliberate alignment with UltraSPARC's `PRIMARY_CONTEXT` model (sun4u, 1995). This decoupling lets J-Core support the full SH-4-plus-PageMask page-size set down to **4 KB** without sacrificing ASID width.

**J32 layout (32 bits):**
```
[31:N]   VPN           Hardware-set on TLB miss, software-set for LDTLB.
                       N depends on the page size selected by PTEL.PageMask
                       at LDTLB time:
                          4 KB    →  N = 12  (VPN = bits [31:12], 20 bits)
                          16 KB   →  N = 14  (VPN = bits [31:14], 18 bits)
                          64 KB   →  N = 16  (VPN = bits [31:16], 16 bits)
                          256 KB  →  N = 18
                          1 MB    →  N = 20
                          4 MB    →  N = 22
                          16 MB   →  N = 24
                          64 MB   →  N = 26
                          256 MB  →  N = 28
                          1 GB    →  N = 30
[N-1:0]  zero          Read-as-zero, write-ignored. Hardware does not store
                       these bits; software writes are dropped.
```

The PTEH layout no longer carries ASID bits. SH-4 binary compatibility is preserved for any code that *reads* PTEH (the VPN portion is at the same position) but software that *wrote* the SH-4 ASID bits must be updated to use ASIDR instead. The standard Linux SH-4 port writes PTEH at context-switch time to set the ASID; that write becomes a write to ASIDR (one LDC, same cost).

### 2.1a ASIDR — Address Space Identifier Register

New in this revision. Holds the 16-bit `ASID_TAG` that hardware compares on every TLB lookup. Written via `LDC Rm, ASIDR`; read via the **read-only P4 alias at `0xFF000038`** (`STC ASIDR,Rn` is retired — see §3.1). The write side is `LDC`-only: no MMIO write path (D7).

**J32 layout (32 bits):**
```
[31:16]  reserved (read-as-zero, write-ignored)
[15:0]   ASID_TAG      The kernel-encoded 16-bit ASID_TAG. Hardware
                       compares this against the entry.ASID_TAG of every
                       TLB entry on every translation (when entry.GLOBAL=0).
```

**ASID_TAG width is 16 bits** (canonical, project-wide). The kernel packs the 12-bit ASID proper and a 4-bit generation discriminator:

> **SUPERSEDED BY the merged kernel — 2026-08-25.** The generation nibble no
> longer exists.
> **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: retire the ASID generation nibble".**
> `ASID_TAG[15:12]` and `jcore_tsb_flush_on_generation()` are deleted;
> `get_asid()` returns a plain 12-bit ASID and `MMU_NO_ASID` is back to
> `MMU_CONTEXT_FIRST_VERSION`. The nibble stopped isolating anything once
> `local_flush_tlb_all()` zeroed the TSB on *every* version wrap and every CPU
> got its own TSB, and it was actively wrong for `tlbflush_32.c`'s
> save/restore.
>
> **`ASID_TAG` is still 16 bits and the comparators are unchanged** — that
> commit makes no RTL change; the top nibble is simply always zero on both
> sides. So the width above is correct and the *packing* below is not. Rewriting
> the packing formula, and §3.5 of [design-spec.md](design-spec.md)
> ("ASID-generation tagging") with it, belongs to Wave-2 **B1**.

```
ASID_TAG[15:0] = (ASID[11:0] | (gen_low[3:0] << 12))
```

Hardware does not interpret the split; only the kernel does. The Linux ASID allocator in [linux-spec.md §5](linux-spec.md) produces this 16-bit value directly.

**A per-context byte-order bit joins this register set when it is built.**
[../bi-endian-spec.md §6](../bi-endian-spec.md) (Decision BE-1) makes the byte order of the data
path **and of instruction fetch** a per-context, hypervisor-owned mode. Its `LE` bit — the byte
order the current non-hyperprivileged context runs in — is live per-context state that a context
switch must carry, exactly like `ASIDR`, and getting it wrong misattributes one context's view of
memory to another in exactly the same way. Its companion `HLE` bit describes the host rather than a
context and does **not** join this set. Neither exists in `jcore-cpu` today; this note is here so
the register set is not believed complete.

*This note previously described a per-guest **data** byte-order mode from Decision B2-1, which is
superseded. The change that matters for a per-context register list is that a wrong `LE` now also
mis-fetches, so the failure is not confined to data.*

**ASIDR is per-thread-context on FGMT implementations.** On a single-threaded core there is one ASIDR per CPU, as described above. On a core with `n_tc` hardware thread contexts ([glossary §4](../glossary.md)) each thread runs an independent address space, so the core holds **`n_tc` copies of ASIDR**:

- `LDC Rm, ASIDR` and the `0xFF000038` read alias write and read **the issuing thread's copy**. No encoding change, no new instruction, no software-visible difference from the single-threaded case — a kernel running on logical CPU *t* simply sees its own register.
- The TLB compare of §4 selects by the issuing thread's TC_ID:

  ```
  match = ... && (entry.GLOBAL || entry.ASID_TAG == ASIDR[tid])
  ```

- `LDTLB` latches `{ASIDR[tid], PTEH.VPN, PTEL}` — the fill uses the ASIDR of the thread executing the instruction.
- The **TLB itself stays shared and unpartitioned.** Entries are already `ASID_TAG`-tagged, so multiple contexts coexist correctly with no further change; a thread simply misses on another thread's entries. Partitioning the TLB per thread is explicitly rejected — it would convert a shared-capacity advantage into a fixed one, and the tag compare already provides isolation.

Cost on a 4-way implementation: 3 additional 16-bit registers and a 4:1 mux on the TLB compare input. Everything else in this specification — PTEH being VPN-only, the generation-tagged `ASID_TAG`, `STALE` enforcement, the TSB miss path, `LDTLB.RN` — is unaffected.

Consumers: [ooo/j32lt-spec.md §11](../ooo/j32lt-spec.md) (`n_tc = 4`), [ooo/j32ooo-spec.md §13.1](../ooo/j32ooo-spec.md) (`n_tc = 2`).

> **SUPERSEDED BY [§2.1a](#21a-asidr--address-space-identifier-register) — 2026-08-25.** The obligation
> below is discharged by a *different* mechanism than the one it names. The
> generation nibble, `set_asid()`'s threading of it, and
> `jcore_tsb_flush_on_generation()` are all deleted —
> **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: retire the ASID generation nibble"** —
> because `local_flush_tlb_all()` already zeroes the TSB on **every** version
> wrap, which is strictly stronger than an every-16th-wrap rebuild, and per-CPU
> TSBs removed the cross-CPU sharing the nibble was protecting. There is no
> residual wrap hazard and no 16-generation window; the paragraph below describes
> a mechanism that no longer exists. Wave-2 **B1** rewrites it.
>
> **Security obligation (generation wrap) — RESOLVED:** only **4 bits** of `ASID_TAG` are the generation discriminator. The TLB is flushed at every rollover, so stale **TLB** entries are always rejected. **TSB** entries are not flushed and are rejected only by the tag compare — so after the generation field wraps (every 16 rollovers), a stale TSB slot with a matching `ASID[11:0]` and matching `gen_low[3:0]` can be a **false hit**. The Linux port (mmu/asid-generation branch) satisfies this obligation: the kernel threads generation into `ASID_TAG` at `set_asid()` and rebuilds the TSB on `gen_low` wrap via `jcore_tsb_flush_on_generation()`, ensuring stale-TSB rejection is an unconditional generation-tagged guarantee (exact for single-core; on SMP the TSB-zero-on-wrap follows `local_flush_tlb_all`'s local-only scope, revisited when jcore MMU-SMP lands). Resolved 2026-07-17 (linux@jcore mmu/asid-generation).

**Context-switch sequence (Linux):**
```asm
        mov.l   new_asid_tag, r0    ! r0 = packed ASID_TAG (16 bits)
        ldc     r0, asidr           ! one instruction, same cost as
                                    ! SH-4's LDC Rn,PTEH for ASID update
```

**LDTLB / LDTLB.RN semantics:** the installed TLB entry's tag is built as
`{ASIDR[15:0], PTEH.VPN[31:N], PTEL.PageMask[3:0]}`. LDTLB atomicity is
unchanged — both PTEH and ASIDR are read at the start of LDTLB; software
must arrange them before issuing the instruction.

**Prior art (pre-2006):**
- **UltraSPARC `PRIMARY_CONTEXT` / `SECONDARY_CONTEXT`** (sun4u ASI 0x21, 1995): a per-CPU context register independent of TLB-tag programming; hardware reads it on every translation. The model this design follows.
- **MIPS R4000 `EntryHi.ASID`** (1991): ASID is a field of EntryHi separately re-assignable from VPN-write semantics.
- **Alpha 21264 `ASN`** (1998): per-CPU address-space-number register, accessed via PALcode, independent of page-table-walk registers.
- **ARMv6 `CONTEXTIDR`** (cp15 c13, 2002): explicit separate context-ID register; the model commercial CPUs converged on.

### 2.2 PTEL — Page Table Entry Low

Inherited from SH-4, extended with PageMask. Written via `LDC Rm, PTEL`; read via the **read-only P4 alias at `0xFF000004`** (`STC PTEL,Rn` is retired — see §3.1).

**J32 layout (32 bits) — canonical, matches the J4 reference implementation (`tlb.vhd:190-202`):**
```
[31:10]  PPN           Physical page number (22-bit PFN, 4 KB granularity).
                       NOTE: PPN[31:10] overlaps PageMask[11:8] bits 10-11;
                       only PPN[27:12] drives relocation, so the overlap is
                       harmless but real. This line previously read
                       PPN[27:13]; bit 12 was added with the PIPT work and
                       it is the bit that makes the L1 caches physically
                       indexed rather than virtually (see 4.1a).
[11:8]   PageMask      log-size selector (see §2.1 PTEH VPN table).
[7]      W             Writable
[6]      X             Executable
[5]      U             User-accessible
[4]      D             Dirty
[3]      C             Cacheable
[2]      G             Global (ignore ASID_TAG on match)
[1]      STALE         Soft-invalidate marker (loaded; enforcement is an RTL
                       decision, H-I1)
[0]      V             Valid — NOTE: inert on install. LDTLB/LDTLB.RN force
                       valid=1 unconditionally (tlb.vhd:190); invalidation is
                       via STALE or MMUCR.TI, never by loading V=0.
```

### 2.3 MMUCR — MMU Control Register

Inherited from SH-4 with one change. MMIO at `0xFF000010`.

**Layout:**
```
[31:8]   reserved
[7]      reserved (was MMUCR.SV on SH-4; not used)
[6]      reserved (was MMUCR.SQMD)
[5]      reserved
[4]      reserved (was MMUCR.IX hash mode; NOT implemented on J-core)
[3]      reserved
[2]      TI            Write 1 to invalidate all TLB entries this cycle.
                       Self-clearing. Reads as 0.
[1]      reserved
[0]      AT            MMU enable. 0 = P0/P3 untranslated and faulting;
                       1 = P0/P3 translated through TLB.
                       P1, P2, P4 unaffected.
```

**TI semantics:** when software writes MMUCR with TI=1, all TLB entries (both I and D if split) on this CPU are marked invalid in one cycle. The write completes; subsequent reads of MMUCR see TI=0. TI=1 may be combined with AT=1 in a single write to atomically flush and enable.

### 2.4 TTB — Translation Table Base (reserved, deprecated)

SH-4 had TTB as a software-only "scratchpad for the TLB miss handler." Preserved as an MMIO-mapped 32-bit (J32) or 64-bit (J64) register at `0xFF000008` for SH-4 compatibility. Hardware does not interpret it. Linux uses it to store `current_pgd` on j-core if not using a dedicated per-CPU register.

### 2.5 TEA — TLB Exception Address

Inherited from SH-4. MMIO at `0xFF00000C`. On any TLB-related exception (miss, protection violation), hardware writes the full faulting effective address into TEA. Software-readable for fault diagnosis.

### 2.6 TSBBR — TSB Base Register (NEW)

Holds the base address of the per-CPU TSB and configuration bits.

> **The base is written as a P1 kernel virtual address, not a raw physical
> address.** This is a hardware/software contract with two halves, and both
> matter:
>
> - **Software** derefs the address `TSBPTR` / `TSBSLOT` hand back — those
>   registers return `TSBBR`'s own bits unconverted — so the value must be
>   directly loadable by the kernel, i.e. P1.
> - **The walker** applies the SH P1 fold itself before issuing its physical
>   reads (`core/cpu.vhd`, the `walk_own` takeover arm). P1 is untranslated by
>   architecture (`PA = VA & 0x1FFFFFFF`), so §5's "a walk cannot itself fault"
>   still holds — the fold is *how* that property is realised, not an exception
>   to it.
>
> An earlier revision of this section said "physical base address" flatly. That
> was stale, and it was not harmless: it led a reviewer to conclude the kernel
> was dereferencing a physical address as a virtual one, and it sat alongside a
> real boot-code defect that programmed `TSBBR` with
> `jcore_boot_tsb - PAGE_OFFSET + __MEMORY_START` — which both broke the P1
> contract *and* double-counted `__MEMORY_START`, since `vmlinux.lds` already
> links at `PAGE_OFFSET + __MEMORY_START`. The register pointed at neither a
> valid VA nor a valid PA. Fixed 2026-08-11; the correct value is simply
> `jcore_boot_tsb`.

**Access:** MMIO at `0xFF000014` (read/write). Cold boot-config register — MMIO only, no LDC/STC encoding (see §3.1 for the access-frequency rationale).

**J32 layout (32 bits):**
```
[31:N+5] TSB_BASE      P1 kernel VIRTUAL address of the TSB (see the note
                       above; NOT a raw physical address). Must be aligned
                       to 32 × 2^N bytes (TSB size).
[N+4:5]  reserved (0)
[4]      reserved (0)
[3:0]    TSB_SIZE_LOG  log2(number of TSB SETS). Valid: 6–14
                       (64 to 16384 sets; TSB = 2 KB to 512 KB).
                       For TSB_SIZE_LOG = N, the TSB spans 32 × 2^N
                       bytes (each set is 32 bytes = 2 ways × 16 B).
```

*(The `TSB_BASE` line previously read "Physical address of TSB", flatly
contradicting the note above it — the same wording, in the same section, that
the note says was stale and "not harmless". Correcting the prose and leaving the
layout block is how a fix half-lands.)*

**The P1 fold, normatively.** P1 is untranslated by architecture: the walker
takes the top three address bits `**100**` to `000` before issuing its physical
read, i.e. `PA = VA & 0x1FFFFFFF`. `core/cpu.vhd`'s `walk_own` takeover arm does
exactly this, and its comment names the case: *"Every TSBBR the guards and
linux@jcore program is a P1 kernel address (e.g. 0x80002C04), which the software
miss handler reads through the fold; without folding here the walker reads an
unmapped 0x8xxxxxxx and the SRAM model rejects it."* `mmu.tsbbr.p1` in
[fact-ownership.md](../fact-ownership.md) binds that bit pattern.

On J64, `TSB_BASE` widens correspondingly. It remains a P1 kernel virtual
address, not a physical one; the low 4 bits remain `TSB_SIZE_LOG`. *(This
sentence previously said "widens to a 64-bit physical address".)*

> **Amendment — Phase 2 of the hardware-walker work.**
> **RESOLVED 2026-08-25 — jcore-cpu@master: "rtl(mmu): the hardware walker is the sole TLB installer".**
> *(Promoted from a claim that `mmu/tsb-hw-walker` was implemented but unmerged;
> the branch is gone from `origin`. The block also carried "MMU suite 97 PASS /
> 0 FAIL at `a2522ed`" — `a2522ed` is **not** an ancestor of `origin/master`, so
> the tally names a base that no longer exists and has been dropped rather than
> restated. This task did not re-run the suite.)*
> Instruction retirement — the phase this note called "later" — is also done:
> **RESOLVED 2026-08-25 — jcore-cpu@master: "decode(mmu): retire LDTLB (0x0038) and LDTLB.RN (0x0078)"**,
> and the read side with it —
> **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `decode/gen-go/spec/sh4/mmu.toml` containing `All seven were retired`.**
> Kernel side:
> **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: retire inlined TLB fast path and STC ASIDR/TSBPTR reads".**
>
> `TSB_SIZE_LOG` counts **sets**, not entries. Phase 1 and everything before
> it counted 16-byte entries, and the layout above has been rewritten in
> place to the Phase-2 meaning — this register's software contract therefore
> changed, and a kernel written against the Phase-1 text will size its TSB at
> half the bytes the hardware indexes. `core/datapath_pkg.vhd`'s `tsb_ptr()`
> reads `tsbbr(3 downto 0)` as the set count and clears `tsbbr(4 downto 0)`
> before ORing the scaled index, which is where the extra reserved bit comes
> from.

### 2.7 TSBCFG — TSB Configuration (NEW)

Holds the hash configuration used by hardware when computing TSBPTR.

**Access:** MMIO at `0xFF000018` (read/write). Cold boot-config register — MMIO only, no LDC/STC encoding (see §3.1).

**J32 layout (32 bits):**
```
[31:8]   reserved (0)
[7:4]    HASH_SHIFT    Right-shift amount applied to VPN before XOR
                       folding. Typical value: ceil(log2(TSB_size))
                       to spread hot regions across TSB.
[3:0]    HASH_MODE     0 = identity (no XOR); 1 = XOR with shifted VPN
                       (recommended); 2–15 reserved.
```

For most kernels, software writes HASH_MODE=1 and HASH_SHIFT=TSB_SIZE_LOG at boot and never touches TSBCFG again.

### 2.8 TSBPTR — TSB Set Pointer (NEW, read-only)

Hardware-populated on every TLB miss. Holds the address (in physical memory) of the TSB **set** where the missing translation, if cached, would be found. A set is one 32-byte cache line holding two contiguous 16-byte entries — way 0 at `+0`, way 1 at `+16`.

**Access:** MMIO at `0xFF00001C`, read-only. (`STC TSBPTR,Rn` `0x004B` existed until Phase 3 and is retired — see §3.1; there was never an `LDC TSBPTR`.) Nothing on the miss path reads it any more: the hardware walker consumes the value internally.

**Computation (hardware, on TLB miss):**
```
vpn  = VA[31:12]
a1   = ASIDR ^ (ASIDR << 5)
amix = a1 ^ (a1 >> 9)
hash = (VPN ^ ((HASH_MODE == 1) ? (VPN >> HASH_SHIFT) : 0)) ^ amix
mask = (1 << TSBBR.TSB_SIZE_LOG) - 1
TSBPTR = (TSBBR & ~0x1F) | ((hash & mask) << 5)
```

The `<< 5` is because each **set** is 32 bytes. TSBPTR is therefore naturally aligned to a 32-byte boundary — one cache line — within the TSB.

> **Amendment — Phase 2.**
> **RESOLVED 2026-08-25 — jcore-cpu@master: "rtl(mmu): the hardware walker is the sole TLB installer".**
> *(Promoted from "IMPLEMENTED on `jcore-cpu` branch `mmu/tsb-hw-walker`, NOT
> MERGED". That branch no longer exists on `origin`; `core/tlb_walk.vhd` and
> `core/datapath_pkg.vhd`'s `tsb_ptr()` are on `master`, with
> `core/cpu.vhd` instantiating the walker at `tsb_ways => 2`. The kernel half is
> **RESOLVED 2026-08-25 — linux@jcore: "Merge pull request #10 from mountain-reverie/mmu/tsb-phase2".**)*
> The formula above **is** the RTL
> (`core/datapath_pkg.vhd`, `tsb_ptr()`); it is not a plan. Two things changed
> from Phase 1: the scale went `<< 4` → `<< 5` (2-way sets), and `ASID` is
> now folded into the **index**, not only compared as a tag.
>
> `jcore_tsb_slot_offset()` in `arch/sh/mm/tlb-jcore.c` — the from-scratch C
> reimplementation of this hash that had to be kept bit-for-bit in sync by
> hand — is **deleted**. Software that needs a set address outside a fault
> uses the `TSBSLOT` register (§2.12), which evaluates this same RTL
> function. There is now exactly one implementation of the index.

#### 2.8a The `ASID` fold is hardening, not isolation

**Do not describe this fold as a security boundary anywhere.** It is not one,
and a downstream design that treats it as one will be built on sand.

What it does: without it, the same virtual address in two address spaces always
lands in the same set. Since a TSB hit is roughly 11× cheaper than a miss, that
handed an attacker a *zero-effort*, deterministic, targeted eviction primitive —
to evict a victim's entry for VA `X`, touch VA `X`. The fold removes that
primitive and measurably improves distribution (simulated-model TSB miss rate
49.4% → 36.3% at 256 sets / 16 processes, 49.5% → 18.6% at 1024 sets / 32
processes). Both are worth having.

What it does **not** do. The fold is XOR-separable —
`hash = f(vpn) ⊕ g(asid)` — and **J-Core is open source, so `g` is public**.
The attacker recomputes it. All that is left to find is the victim's `ASID`
contribution, and the offset space is only `2^TSB_SIZE_LOG` — **64 to 16384
values**, the full range §2.6 permits — which is brute-forceable by timing
probes. *(This previously read "64–1024 values", a range narrower than the
register allows. It does not change the conclusion — a 14-bit search is still a
search — but it is what sets the attack's cost, so it is not cosmetic:
`TSB_SIZE_LOG` decides how many index bits exist to be learned. Flagged by
[security/threat-model.md §11](../security/threat-model.md).)* The attacker is delayed by a search,
not excluded. Isolation is §2.13a's per-domain partitioning, and only that.

The fold is deliberately **not** a bare `vpn ^ asid`. The `<< 5` spread with a
`>> 9` refold makes every index bit, at any TSB size, a function of three
different `ASID` bits with a different triple per bit; a bare XOR of a narrow
identifier distributes badly (see the Prior art note below). It is applied in
**both** `HASH_MODE`s — a mode that silently disabled it would be a switch for
turning the hardening off. And because it is a constant XOR for a fixed `ASID`,
it is a bijection on the set index: within one address space the conflict
distribution is bit-for-bit what it was before the fold, so it cannot introduce
thrashing in a single-`ASID` workload.

**Prior art (pre-2006).** Folding the address-space identifier into a
translation-structure *index* is **US 5,493,660**, Hewlett-Packard, filed
**1992-10-06**, granted 1996-02-20, **expired**: a *hardware TLB miss handler*
that forms its pointer by XORing high-order virtual-address bits — which are
the OS-assigned space identifier — with low-order bits, "to provide a more
uniform distribution of pointer references over periods when multiple processes
execute". Same mechanism, same motivation, same context. **US 5,899,994** (Sun
Microsystems, filed 1997-06-26, expired) is a second, independent record of TSB
index formation from PID + VA, and it carries the design warning above: XORing a
*narrow* process identifier straight into the index distributes badly and
invites thrashing — which is why the shipped fold is a mixed function rather
than a bare XOR. The *prior* J-Core design, in which context participates as a
**tag only**, is **US 7,430,643** (Sun, priority 2004-12-30).

*Publication or grant before 2006 is evidence of prior art. It is **not** a
patent-clearance opinion, which this document does not offer.*

#### 2.8b What was considered and dropped — do not re-propose

**A keyed or per-context index mapping is unavailable to this project.** Its
origin is **RPcache — Z. Wang & R. B. Lee, "New Cache Designs for Thwarting
Software Cache-Based Side Channel Attacks", ISCA 2007, pp. 494–505**, which is
past the project's 2006 prior-art cutoff (`docs/glossary.md` §2). A search for
an earlier tech report, workshop paper or filing found none. More broadly:
**there is no pre-2006 TLB index randomization at all** — the only pre-2006 TLB
security item locatable is a 1995 *observation* that the TLB is a covert
channel. Every pre-2006 randomized-index design (Seznec ISCA 1993; González,
Valero, Topham & Parcerisa ICS 1997; Topham & González, IEEE ToC 48(2), Feb
1999; Sun US 7,290,116, priority 2004-06-30, explicitly stateless) chooses its
function for *miss-ratio* reasons and **publishes it**.

**A boot-time secret constant XOR'd into the index is useless, not merely
weak.** This is the obvious idea, and it looks like it should work, so the
reason it does not is recorded here rather than left to be rediscovered. The
collision condition between two accesses is

```
(f(v₁) ⊕ g(a₁) ⊕ K) & mask  ==  (f(v₂) ⊕ g(a₂) ⊕ K) & mask
```

in which `K` **cancels**. Conflict attacks depend on *relative* placement,
never absolute placement, so a global constant — secret or not — changes
nothing an attacker can observe. It would buy zero security at the cost of a
register that looks like a secret and would be treated as one.

**The CEASER boundary.** The tempting future enhancement — "periodically re-key
the hash so an attacker who has learned the mapping loses it" — is precisely
the encumbered idea: CEASER (Qureshi, MICRO 2018), CEASER-S (ISCA 2019),
ScatterCache (USENIX Security 2019), MIRAGE (2021). All post-2006. The bright
line for J-Core is therefore: **no key, no cipher, no re-keying.** The index
function is fixed at synthesis. `TSBCFG` selects among *fixed, published*
functions and is boot configuration, never a secret. Static selection is fine;
a runtime-writable index *key* register is not.

### 2.9 CPUINFO — CPU Information (NEW, MMIO only)

Read-only MMIO register, per-CPU-distinct. Each CPU reading address `0xFF000030` sees its own hart ID and capability flags.

**Address:** `0xFF000030`. CPUINFO formerly sat at `0xFF000020`; that offset and the two following it are the stock SH-4 placement of `TRA`/`EXPEVT`/`INTEVT` (SH-4 hardware manual, Renesas/Hitachi, 1998) and have been returned to those registers; `0xFF00002C` then went to MMUFSR (§2.11), which the RTL decodes. See [soc/p4-mmio-map.md §3.2](../soc/p4-mmio-map.md) for the decision and rationale. CPUINFO is **allocated but not implemented** in current RTL, and an undecoded P4 read returns zero without faulting, so a CPU reading CPUINFO today gets `0` rather than its hart ID.

**Overlap with `jcore,cpuid-mmio` (unresolved, flagged).** The `HART_ID` field duplicates a facility jcore-soc already implements: `cpumreg` (`jcore-soc/targets/cpumreg.vhm`, decoded at `jcore-soc/targets/cpu_core_pkg.vhd:132-137`) exposes per-core identity at `0xABCD0600`, published to every board device tree as `jcore,cpuid-mmio`, and SMP boot reads it today (`jcore-soc/boot/main.c:414-432`). Whoever implements CPUINFO must pick one of the two rather than build both; this spec does not choose.

**Layout (32 bits):**
```
[31:16]  CORE_CAPS     Implementation-defined capability flags
                       (FPU present, DSP present, hypervisor mode, etc.)
[15:8]   reserved (0)
[7:4]    reserved (0)  Room to widen hart ID for >16 CPUs
[3:0]    HART_ID       This CPU's hart number (0–15)
```

No new instruction is needed; standard `MOV.L @rA, Rn` from a register holding `0xFF000030` reads it. The SoC's address decoder routes this access to a small per-core hard-wired register.

### 2.10 PTEU — Page Table Entry Upper (NEW, optional — PAE only)

Present only when the core is built for **wide physical addressing** (PAE; [design-spec.md §3.8](design-spec.md)). Carries the high physical-address bits that do not fit in the 32-bit `PTEL`, so that `LDTLB` can install a > 32-bit physical frame. Omitted entirely when `ADDR_WIDTH = 32`.

**Access:** new LDC/STC encoding (see §3.3) and MMIO at `0xFF000034` (proposed; coordinate with [soc/p4-mmio-map.md](../soc/p4-mmio-map.md), as for the §4.6 cause registers).

**J32-PAE layout (32 bits):**
```
[31:8]   reserved (read-as-zero, write-ignored)
[7:0]    PPNH          Physical address bits PA[39:32]. Combined with
                       PTEL.PPN (PA[31:14]) and the page offset, forms the
                       full 40-bit physical address. Software-set; latched
                       into the TLB entry by LDTLB / LDTLB.RN alongside PTEL.
```

**LDTLB semantics.** The installed entry's physical frame is `{PTEU.PPNH, PTEL.PPN}`. `PTEU` is read at the same point as `PTEL` and `PTEH` at `LDTLB` time; software must arrange all three before issuing the instruction. On a non-PAE (`ADDR_WIDTH=32`) core, the high bits are implicitly zero and `PTEU` does not exist.

**Untranslated segments are unaffected.** P1/P2 produce `PA = VA & 0x1FFFFFFF` — at most 29 bits — so the kernel direct map and the boot/XIP path always land in low physical. Wide physical (`PA[39:29] ≠ 0`) is reachable **only** through the translated P0/P3 path, i.e. only via `LDTLB`-installed entries that carry `PTEU`. This is what makes everything above 512 MB "highmem" ([design-spec.md §3.8](design-spec.md)).

**Prior art (pre-2006).** A dedicated register holding the *high* physical-address bits of a wide-physical translation is the **PowerPC Book E `MAS7`** register (Freescale e500v2, ~2004), which extends the e500's real address from 32 to 36 bits exactly as `PTEU` extends J32's from 32 to 40. The broader 64-bit-PTE wide-physical paging technique is Intel x86 **PAE** (Pentium Pro, 1995); a 32-bit-virtual → 36-bit-physical software-managed MMU is the **SPARC V8 SRMMU** (sun4m, 1992); and the narrow-virtual / wide-physical concept itself dates to the **DEC PDP-11/70** (1975). See [design-spec.md §3.8](design-spec.md) for the full lineage.

### 2.11 MMUFSR — MMU Fault-Status Register (NEW, read-only)

Read-only MMIO register at `0xFF00002C`, latched on every TLB exception (I-fetch or D-access, miss or protection, and multi-hit). Writes are silently ignored. Exists to resolve a real ambiguity in the `EXPEVT`-based fault model: DPROT_R (data-load protection violation) and DPROT_W (data-store protection violation) both raise `EXPEVT = 0x0C0` through the single shared vector `VBR + 0x400` (see §5), so a page-fault handler reading only `EXPEVT` cannot tell a write fault from a read fault. This matters for kernels implementing copy-on-write: misclassifying a write-protect fault as read-protect can livelock the fault handler (it never triggers the CoW break-and-retry path). MMUFSR gives software a second, independent signal to disambiguate. It is purely a software convenience register — it duplicates state the TLB already computes internally for the miss/protection decision — and does not change `EXPEVT`, the vector layout, or any decoder/opcode encoding.

**Layout (32 bits, low byte matters, upper bits read as zero except bit 12):**
```
[31:13]  reserved (0)
[12]     VALID    1 = MMUFSR holds a fault snapshot (set on every TLB exception
                  capture; there is no way to observe MMUFSR before the first
                  TLB exception other than at cold reset, where it reads 0).
[11:8]   KIND      Fault kind (see table below).
[7:5]    reserved (read-as-zero). Linux's fault handler derives an SH-style
                  error_code with a bare `extu.b` on this register, so these
                  bits MUST read zero unconditionally -- never repurpose them
                  without also updating that extraction path.
[4]      USER      1 if the faulting access was made in user mode (SR.MD=0
                  at the moment of the fault), 0 if supervisor. Sampled at
                  fault-capture time, not from SSR (which is not yet written
                  when the capture logic runs). Left 0 for MULTI_HIT (KIND=7)
                  -- see below.
[3]      PROT      1 if the fault was a protection violation (IPROT/DPROT_R/
                  DPROT_W), 0 if it was a miss (IMISS/DMISS_R/DMISS_W). Read
                  as 0 and not meaningful for MULTI_HIT.
[2]      ITLB      1 if the fault was on the instruction side (IMISS/IPROT),
                  0 if on the data side. Read as 0 and not meaningful for
                  MULTI_HIT.
[1]      INITIAL   Always 0. Reserved for a possible future distinction
                  (e.g. "first touch" vs. "re-fault"); no current hardware
                  path sets it.
[0]      WRITE     1 if the faulting access was a store (DMISS_W/DPROT_W),
                  0 for a load or instruction fetch. Read as 0 and not
                  meaningful for MULTI_HIT.
```

**KIND encoding:**

| KIND | Fault |
|------|-------|
| 0 | none (no TLB exception has been captured since reset) |
| 1 | IMISS — instruction-fetch TLB miss |
| 2 | DMISS_R — data-load TLB miss |
| 3 | DMISS_W — data-store TLB miss |
| 4 | IPROT — instruction-fetch protection violation |
| 5 | DPROT_R — data-load protection violation |
| 6 | DPROT_W — data-store protection violation |
| 7 | MULTI_HIT — multiple TLB entries matched (see §2.6/§4.5) |

**MULTI_HIT is a special case.** When KIND=7, the entire low byte (`[7:0]`, including USER at bit 4) reads 0 — only `VALID` (bit 12) and `KIND` (bits `[11:8]`) are meaningful. This mirrors the fact that a multi-hit is a configuration error detected during TLB lookup, before the normal miss/protection classification (direction, privilege) has been computed for a specific access.

**Relationship to EXPEVT (§5).** MMUFSR is latched by the same fault-capture logic that latches `TEA`/`PTEH`/`SPC`/`SSR` on a TLB exception (§5 steps 2-4), so by the time the handler is entered at `VBR + 0x400`, `STC EXPEVT, Rn` and a read of `0xFF00002C` are both immediately valid and describe the same fault. The two are read in whichever order suits the handler; neither is more expensive than the other. Linux@jcore, for instance, reads MMUFSR *unconditionally* in the fault prologue (`arch/sh/kernel/cpu/jcore/entry.S`), before it knows the fault kind, and folds its WRITE bit straight into the `error_code` argument of `do_page_fault()` — a single unpredicated MMIO load is cheaper on this pipeline than branching on `EXPEVT` to decide whether to issue it. `STC EXPEVT, Rn` is then used to separate miss from protection. Software is free to read MMUFSR lazily instead, but nothing in the hardware rewards doing so.

### 2.12 TSBSLOT — TSB set-address helper (NEW, MMIO only)

> **Amendment — Phase 2.**
> **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/datapath.vhm` containing `P4_TSBSLOT`.**
> Decoded alongside `TSBBR`/`TSBCFG`/`TSBPTR`.
> *(Promoted from a claim that `mmu/tsb-hw-walker` was implemented but unmerged;
> the branch is gone from `origin`.)*

**Access:** MMIO at `0xFF000048`, read **and** write. There is no LDC/STC form.

Write a virtual address; read the same address back to get `tsb_ptr(VA)` — the
32-byte-aligned set address for that VA under the current `TSBBR`, `TSBCFG` and
`ASIDR`. Only the VA is latched. The index function is evaluated **on the
read**, so `core/datapath_pkg.vhd`'s `tsb_ptr()` stays the single
implementation of the index anywhere in the system.

**Why it exists.** `TSBPTR` (§2.8) is latched by a fault, so it is only
available on the fault path. Linux's `__update_tlb()` fills the TSB *outside*
any fault, on permission upgrades, where no `TSBPTR` has been latched. Before
this register, that path used `jcore_tsb_slot_offset()` — a from-scratch C
reimplementation of the hash that had to be kept bit-for-bit in sync with the
RTL by hand. That mirror is the class of defect this register removes; it is
deleted.

**Its failure mode is benign, which is the point.** The register is a
write-VA-then-read-result pair, so a preemption between the two halves could
return a set address for someone else's VA. `__update_tlb()` already runs under
`local_irq_save`, and even if it did not, the consequence is that software
writes a *correct* entry into the *wrong* set: the walker then fails to find
it, misses, and takes the software path. **Slow, not wrong.** No architectural
atomicity is required of the pair, and none is provided.

### 2.13 TSBVSEED / TSBVICT — TSB victim selector (NEW, MMIO only)

> **Amendment — Phase 2.**
> **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/datapath.vhm` containing `P4_TSBVSEED`.**
> `P4_TSBVICT` is decoded alongside it, and the LFSR itself is
> **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/datapath_pkg.vhd` containing `tsb_lfsr_next`.**
> *(Promoted from a claim that `mmu/tsb-hw-walker` was implemented but unmerged;
> the branch is gone from `origin`.)*

With a 2-way set, software that finds neither tag matching must choose a way to
replace. Hardware nominates one, pseudo-randomly, so that the choice is not
something an attacker can predict or steer.

| Address | Name | Access |
|---|---|---|
| `0xFF00004C` | `TSBVSEED` | **write-only** — seeds the victim LFSR |
| `0xFF000050` | `TSBVICT`  | **read-only** — bit 0 is the way nomination; all other bits read 0 |

The selector is a 16-bit Fibonacci LFSR, taps 16/14/13/11
(`x¹⁶+x¹⁴+x¹³+x¹¹+1`, maximal length 65535). **The seed is not in the
hardware**: the OS writes it at MMU init from real boot entropy. That is not
ceremony. This is an open-source core, so the polynomial and any constant seed
compiled into the RTL are readable by anyone, and a victim sequence an attacker
can replay offline is worth no more than a fixed choice.

**Only the 1-bit nomination is exposed.** `TSBVSEED` has no read case at all
and returns a hard zero — deliberately, not by omission: if software could
recover the seed, so could an attacker. Reading `TSBVICT` **advances** the
LFSR, so each read consumes exactly one bit and no two reads observe the same
state; an attacker cannot resynchronise to the sequence even by watching
evictions.

**Zero is the LFSR's lock-up state**, and it self-heals to a fixed, non-secret
constant rather than leaving an un-seeded machine silently pinned to way 0 — a
correct-but-slow failure nobody would notice. That constant carries **no**
security claim. Security here comes from the OS seed, and only from it.

The selector sits **outside** the index function — it chooses which way to
evict, not where to look — so it is clear of the no-key boundary of §2.8b. A
key in the *index* is CEASER-shaped and post-2006; an unpredictable
*replacement victim* is not.

**Prior art (pre-2006).** Random replacement is ubiquitous well before the
cutoff — A. J. Smith, "Cache Memories", ACM Computing Surveys 14(3), 1982;
Hennessy & Patterson, any edition ≤4th; and it is the replacement policy of
essentially every ARM core of the era. *Pre-2006 publication is evidence of
prior art, not patent clearance.*

### 2.13a Isolation is partitioning, not hashing

**The `ASID` fold (§2.8a) is hardening. The victim LFSR (§2.13) is hardening.
Neither is an isolation boundary, and this specification does not claim one
from either.** The boundary, where a deployment needs one, is **per-domain TSB
partitioning**: give each trust domain its own TSB (or its own disjoint
sub-range of one allocation, by also adjusting `TSB_SIZE_LOG`) and write
`TSBBR` on domain switch. Disjoint index sets mean there are no shared sets to
contend for, so there is no cross-domain collision to measure — the channel is
closed **by construction**, not by obfuscation, and it stays closed against an
attacker who knows the whole algorithm.

**This needs no RTL change at all.** The TSB is software-managed memory and
`TSBBR` is already a writable register. The cost is one register write per
domain switch, and it moves from cycles to **memory** (k TSBs) or to
**capacity** (one allocation sub-divided). Neither is paid on the miss path.

The alternative considered and rejected as costly was **flush-on-switch**: a
full `memset` of the TSB on every cross-domain switch. It is correct and fully
covered pre-2006, and it remains the migration-safe backstop; it is simply far
more expensive per switch than reprogramming a base register.

**Prior art (pre-2006).** Partitioning a shared, index-mapped structure into
disjoint sets per activity, under OS control, precisely so one activity cannot
displace another's footprint: **J. Liedtke, H. Härtig & M. Hohmuth,
"OS-Controlled Cache Predictability for Real-Time Systems", RTAS 1997,
pp. 213–224.** Flush-on-switch / never-co-schedule-across-a-privilege-boundary:
**C. Percival, "Cache Missing for Fun and Profit", BSDCan 2005.** *Publication
before 2006 is evidence of prior art, not patent clearance.*

Under a hypervisor, this composes in two non-interfering levels — see
[../hypervisor/design-spec.md §3.8a](../hypervisor/design-spec.md).

## 3. Instruction Encodings

The SH ISA reserves the LDC/STC family for control register transfers via the pattern:

```
LDC Rm, REG :  0100 mmmm xxxx 1110
STC REG, Rn :  0000 nnnn xxxx 0010
```

where `xxxx` selects the register. SH-4 uses values 0000–0100 (SR, GBR, VBR, SSR, SPC) and 1nnn (R0_BANK–R7_BANK). Values 0101, 0110, 0111 are free.

### 3.0 Baseline SH-4 instructions the MMU requires (absent from J2)

The new encodings in §3.1–§3.2 extend a family that **J2 does not currently implement**. Before any MMU register or TLB-fill instruction is meaningful, the core must first add the pre-existing SH-4 instructions on which the exception model and the miss-handler hot path are built. These are not new inventions — they are stock SH-4 (SH-4A) opcodes, catalogued with their encodings in [docs/sh4-nonfpu.json](../sh4-nonfpu.json) (Tier-1, "mmu-required"). Adding them is cheap precisely because §3.1's new registers reuse the same `0100 mmmm xxxx 1110` / `0000 nnnn xxxx 0010` decode family, so the decoder paths exist anyway.

| Mnemonic | Encoding | Why the MMU needs it |
| -------- | -------- | -------------------- |
| `LDTLB` | `0000000000111000` (0x0038) | The TLB-fill primitive. Latches `{ASIDR, PTEH.VPN, PTEL}` into a TLB entry. §3.2's `LDTLB.RN` is the fused-with-RTE variant; both are required. |
| `LDC Rm,SSR` / `STC SSR,Rn` (+`.l`) | `0100mmmm00111110` / `0000nnnn00110010` | Saved-SR. Exception entry does `SR→SSR` (§5 step 4); the slow path and any nested fault must save/restore it. `LDTLB.RN`/`RTE` restore it on the way out. |
| `LDC Rm,SPC` / `STC SPC,Rn` (+`.l`) | `0100mmmm01001110` / `0000nnnn01000010` | Saved-PC. Exception entry does `PC→SPC`; the multi-word-fetch restart contract (§5.2) is defined in terms of what gets latched here. |
| `LDC Rm,Rn_BANK` / `STC Rm_BANK,Rn` (+`.l`) | `0100mmmm1nnn1110` / `0000nnnn1mmm0010` | Alternate-bank register access. The zero-save/restore scratch the hot path relies on (design-spec §4.4, §6 here) is the banked R0–R7; explicit `BANK` moves ferry values across banks and save both banks at `switch_mm`. |

**Privilege.** All four groups are privileged (illegal-instruction trap if `SR.MD=0`), consistent with their SH-4 definitions.

**Not required by the MMU.** Three further SH-4-only instructions surface in the same J2 gap but are *orthogonal* to translation and may be deferred or dropped: `LDC/STC DBR` (debug base register — UBC, not MMU), `STC SGR` (saved R15 — redundant here, since scratch comes from register banking, not an SGR shadow), and `CLRS`/`SETS` (the MAC saturation `S` bit). The operand-cache-maintenance instructions (`ocbi`/`ocbp`/`ocbwb`/`pref`/`movca.l`) are also in this gap but belong to the cache milestone, not the MMU core — see [cache/l2-spec.md §17.5](../cache/l2-spec.md). `pref` is additionally useful in the miss hot path (§7) to prefetch the `TSBPTR` slot.

### 3.1 Register access: in-core vs MMIO (by access frequency)

> **Retirement — IN EFFECT.** *(Implementation status: **done**, branch
> `mmu/tsb-hw-walker`, jcore-cpu `09304a3` (RTL + spec) and `957e940`;
> binutils-gdb `mmu/retire-seven`; MMU guard suite 98 PASS / 0 FAIL.)*
> The hardware TSB walker (§5.0) removed the last hot-path user of seven of
> these encodings, and they are **gone**:
>
> | Retired encoding | Was | Now |
> |---|---|---|
> | `STC TSBPTR,Rn` | `0x?4B` | General Illegal |
> | `STC PTEH,Rn` | `0x?8B` | General Illegal |
> | `STC PTEL,Rn` | `0x?9B` | General Illegal |
> | `STC ASIDR,Rn` | `0x?BB` | General Illegal |
> | `CMP/EQ PTEH,Rn` | `0x?CB` | General Illegal |
> | `CMP/EQ ASIDR,Rn` | `0x?DB` | General Illegal |
> | `LDTLB.RN Rm` | `0x?FB` | General Illegal |
>
> They are removed from `decode/gen-go/spec/sh4/mmu.toml`, from
> `jcore-cpu/docs/insns.json`, and from binutils `sh-opc.h` (with the now-unused
> `A_TSBPTR` operand type). Family `0000 nnnn xxxx 1011` is **0 used /
> 8 free** — every slot virgin, and it is the natural first reserve for
> future J4-only `0000 nnnn`-shaped instructions.
>
> **The count is confirmed and the reserve is contended — B4 encoding sweep,
> 2026-09-08** ([../encoding-sweep.md §3.3](../encoding-sweep.md)). The command
> published below was re-run verbatim and reproduces exactly: 8 candidates, 8
> virgin. What changed is the "reserve" half, not the arithmetic:
> [../simd/spec.md §5.7](../simd/spec.md) already places `VINS.B`, `VINS.W`,
> `VINS.Q` and `VINSF.L` in four of these eight slots, and `VINS.L` on the ninth
> minor this family has, `1010`, which is not free at all — it shadows SH-4A
> `synco`. Neither document cited the other. **Treat the family as spoken for
> until that is settled**, jointly with the SIMD spec; a J4-only instruction
> assigned here today would collide with a documented one.
>
> **Kept:** `LDTLB` (`0x0038`) and the parameterless `LDTLB.RN`
> (`0x0078`) — only the `Rm` form of `LDTLB.RN` went.
>
> The three `LDC` writes — `LDC Rm,{PTEH, PTEL, ASIDR}` — are **kept
> permanently** (design D7). That is deliberate: it preserves the
> hypervisor's one-trap guest-refill path
> ([../hypervisor/design-spec.md §5](../hypervisor/design-spec.md))
> and avoids having to define that `LDTLB` observes prior P4 stores. There is
> no MMIO write path to these registers, by design.
>
> The retired `STC` reads are replaced by **read-only MMIO aliases**, decoded
> in `core/datapath.vhm` (`P4_PTEH`/`P4_PTEL`/`P4_ASIDR`), at the stock SH-4
> offsets — `PTEH` `0xFF000000`, `PTEL` `0xFF000004` — plus `ASIDR` at
> `0xFF000038`, which SH-4 leaves free (`0xFF000034` stays reserved for the
> proposed `PTEU`, §2.10). See
> [../soc/p4-mmio-map.md](../soc/p4-mmio-map.md).

The choice between an in-core `LDC`/`STC` register and an uncached-MMIO register is made **by access frequency**, not by aesthetics, because the two mechanisms have opposite cost profiles:

- **Performance.** An in-core register moves in **1 pipelined cycle**. An MMIO access is an uncached P4 bus round-trip that **stalls the pipeline** for several cycles. The TLB-miss handler (software-loaded TLB, ~7-instruction hot path — §7) runs on every working-set miss; making its register accesses MMIO would turn ~7 cycles into ~40–70 (a 5–10× slowdown on the hottest OS primitive). So registers touched per-miss **must** be in-core.
- **Synthesis.** This core's Fmax bottleneck is the instruction-decoder combinational depth. Each in-core `LDC`/`STC` encoding loads that critical path and widens the `STC` read mux; an MMIO register's address comparator sits in the slack-rich memory datapath (and can live in the SoC P4 block). So for **cold/config** registers MMIO is actively *cheaper* for timing and more ASIC-portable.

**The rule:** hot-path registers → in-core `LDC`/`STC`; cold/config registers → uncached MMIO.

**Encoding-space reality.** The SH-4 control-register LDC family `0100 mmmm xxxx 1110` is *fully occupied* on J-Core: `xxxx` = `0000`–`0100` are `SR`/`GBR`/`VBR`/`SSR`/`SPC`, `0101`/`0110`/`0111` are `PTEH`/`PTEL`/`ASIDR`, and `1xxx` is `Rm_BANK`. There are **no** free control-register LDC slots, and the `0100 mmmm xxxx 1010` family is base `LDS` (MACH/MACL/PR/…) — so PTEH/PTEL/ASIDR cannot be relocated there. (Real SH-4 has *no* `LDC PTEH` either; its MMU registers are MMIO-only. The earlier draft of this section proposed an `xxxx 1010` relocation that is infeasible; it is corrected here.) This is exactly why the cold TSB-base/config registers are MMIO-only.

**In-core writes — the surviving `xxxx 1110` LDC family:**

| Mnemonic | Encoding | Hex Pattern |
|----------|----------|-------------|
| `LDC Rm, PTEH`  | `0100 mmmm 0101 1110` | `0x405E` |
| `LDC Rm, PTEL`  | `0100 mmmm 0110 1110` | `0x406E` |
| `LDC Rm, ASIDR` | `0100 mmmm 0111 1110` | `0x407E` |

The matching `STC` reads (`0x008B` / `0x009B` / `0x00BB`), `STC TSBPTR,Rn`
(`0x004B`), `CMP/EQ PTEH,Rn` (`0x00CB`), `CMP/EQ ASIDR,Rn` (`0x00DB`) and
`LDTLB.RN Rm` (`0x00FB`) are **retired** — see the notice above. Read
`PTEH`/`PTEL`/`ASIDR` through their P4 aliases and `TSBPTR` at `0xFF00001C`.

`TSBPTR` is read-only: it is hardware-computed on every TLB miss (§2.8) and has **no** `LDC` encoding (decoding one raises illegal-instruction).

**Why the read side *was* in `0000 nnnn xxxx 1011`** (history — the family is
now empty; kept because it records why the family is a safe reserve). J4 is targeted to be a superset of J2, SH-2A, SH-4 and SH-4A, so no J4-only instruction may occupy an encoding any of those four defines. The read side originally sat in `0000 nnnn xxxx 0011` (`STC PTEH` = `0x0053`, `PTEL` = `0x0063`, `ASIDR` = `0x0073`, `TSBPTR` = `0x0043`, `CMP/EQ PTEH` = `0x00D3`, `CMP/EQ ASIDR` = `0x00F3`), which fails that bar in three places:

| Old encoding | Collides with |
|---|---|
| `STC PTEL, Rn` `0x0063` | SH-4A `movli.l @Rm,R0` — the **LL** of LL/SC |
| `STC ASIDR, Rn` `0x0073` | SH-4A `movco.l R0,@Rn` — the **SC** of LL/SC |
| `CMP/EQ PTEH, Rn` `0x00D3` | SH-4/SH-4A `prefi @Rn` |

`0000 nnnn xxxx 0011` has only two slots left that are clean against the target set, so the whole read side moved to `0000 nnnn xxxx 1011`, which had seven, and it already hosted `LDTLB.RN Rm`. **All of that is now unwound: the family has 8 free slots, all virgin** — the six reads plus `LDTLB.RN Rm` were retired, and `1110` had already come free when `CMP/MISS EXPEVT` was withdrawn (§3.2a). `0000 nnnn xxxx 1011` is therefore the first reserve for J4-only `0000 nnnn`-shaped instructions, ahead of `0000 nnnn xxxx 1000`. Re-check with:

```
go run ./cmd/cpugen freespace --avoid j2,sh2a,sh4,sh4a,dsp \
    --overlay sh4 --form "----nnnn----1011" --region 0
```

**Deliberate foreclosure: SH-DSP.** The `LDC` write side (`0100 mmmm 0101/0110/0111 1110`) overlays SH-DSP's `ldc Rm,MOD/RS/RE`, and `STC EXPEVT/INTEVT/TRA` likewise overlay `stc MOD/RS/RE,Rn`. This is unavoidable, not an oversight: after excluding j2/sh2a/sh4/sh4a the `LDC` control family has exactly three surviving slots and they are precisely the DSP ones. **J4 therefore forecloses SH-DSP permanently.**

**Cold/config registers — MMIO only (no LDC/STC):**

| Register | MMIO address | Access |
|----------|--------------|--------|
| `TSBBR`  | `0xFF000014` | read/write (boot config) |
| `TSBCFG` | `0xFF000018` | read/write (boot config) |
| `TSBPTR` | `0xFF00001C` | read-only (mirror of the in-core value) |

These are written once at boot, so MMIO costs nothing at runtime and keeps three encodings off the Fmax-critical decoder.

> **Binutils status.** *(Implementation status: **done**, `mmu/retire-seven`.)*
> `sh-opc.h` now knows only the surviving set: `ldc Rm,{pteh,ptel,asidr}`,
> `ldtlb`, parameterless `ldtlb.rn`, and `stc {expevt,intevt,tra},Rn`. The
> four `STC` MMU-register forms, both `cmp/eq {pteh,asidr},Rn` and
> `ldtlb.rn Rm` were removed, along with the `A_TSBPTR` operand type. Never
> hand-edit `sh-opc.h` — it is generated from `jcore-cpu/docs/insns.json` by
> `tools/insns2asm` (`-emit gas` is the authoritative J-core-only line set).
> The CI toolchain image pins `BINUTILS_JCORE_COMMIT` in
> `jcore-cpu/.github/ci/Dockerfile`; that ARG only refreshes on a
> `build-ci-image` workflow dispatch, never on a branch push.

### 3.2 LDTLB.RN — Load TLB and Return (No delay slot)

New single-cycle instruction that fuses LDTLB and RTE. Equivalent to executing LDTLB followed immediately by RTE, but atomically (no observable state between). **Implemented and named `LDTLB.RN`** in the decoder (`decode/gen-go/spec/sh4/mmu.toml:126`) and in binutils `sh-opc.h:791`; "LDTLB.R" is the historical name used elsewhere in these docs for the same instruction.

**Encoding:** `0000 0000 0111 1000` = `0x0078`

**Semantics:**
1. Latch the current values of PTEH and PTEL into a TLB entry, chosen by the LRU/replacement policy (same as existing LDTLB).
2. Restore PC ← SPC, SR ← SSR.
3. Branch to the new PC.

**Delay slot:** **NONE.** Unlike RTE, `LDTLB.RN` has **no** delay slot — its return slots issue the fetch at the target PC directly (this is why it is named `…RN`). The miss-handler examples in §7 and [linux-spec.md §4.1](linux-spec.md) place a trailing `nop` after it; that `nop` is harmless padding, **not** an architectural delay slot, and **must not** carry a meaningful instruction (it would not execute). Handlers ported from the older "LDTLB.R has a delay slot" framing must drop any instruction placed in that slot.

**Privilege:** Privileged. Causes illegal-instruction trap if executed with SR.MD=0.

The existing LDTLB (encoding `0x0038`) is preserved for compatibility; the only difference is LDTLB.RN also returns.

### 3.2a Fault-class separation: why there is no CMP/MISS instruction

A note for anyone who finds `CMP/MISS EXPEVT` referenced in older material: it
existed, briefly, and was withdrawn. The history is worth keeping because the
tempting fix was the wrong one.

All six TLB causes originally shared the vector `VBR + 0x400`. A **protection**
fault against a VPN/ASID that still has a valid TSB entry therefore TSB-hits on
the miss fast path; reinstalling that entry and retrying livelocks, because
`do_page_fault()` is never reached to fix the pte up. The handler consequently
had to separate miss from protection on **every TSB hit** -- the hottest path in
the kernel -- first as three instructions
(`stc expevt,rN` / `add #-128,rN` / `cmp/pl rN`), then as a purpose-built fused
instruction, `CMP/MISS EXPEVT`.

Both were treating a symptom. **SH-4 does not merge these vectors** (SH7750
hardware manual Rev 2.0, 02/99, exception table):

| Exception | Vector |
|---|---|
| Instruction TLB miss | `VBR + H'400` |
| Data TLB miss (read / write) | `VBR + H'400` |
| Instruction TLB protection | `VBR + H'100` |
| Data TLB protection (read / write) | `VBR + H'100` |

J4 now matches that. Protection faults vector to `VBR + 0x100`, the general
exception vector, alongside Error / Slot Illegal / General Illegal / TRAPA.
The fast path needs no fault-class test at all, so it dropped from 11
instructions to 9, and `CMP/MISS EXPEVT` lost its only caller and was removed
rather than left as dead ISA surface -- its encoding (`0x00EB`) is back in the
free pool. Measured effect: a TSB-hit miss went from 27 to 25 cycles (D-side)
and 26 to 24 (I-side), *and* the livelock class is now excluded by
construction instead of by a software check.

**Prior art.** The miss/protection split is not an SH-4 idiosyncrasy; it is the
standard arrangement for software-managed TLBs. MIPS R2000/R3000 (1985) sends
TLB **refill** to a dedicated fast vector and TLB Invalid / Modified /
protection to the general vector, explicitly so the refill path never tests a
cause. PowerPC 603 (1993) goes further, giving instruction-miss, data-load-miss
and data-store-miss three separate vectors.

*Guard: `mmuvecsplit` -- each vector writes a distinct marker and every
sub-test asserts the one it expects, so a silent regression of the split fails
sub-test D with its own result code rather than passing quietly.*

### 3.3 PTEU encoding (PAE only)

> **Note (PAE/J64, deferred).** `PTEU` is only needed on a wide-physical J64 build and is not implemented in the J32 MMU. The encoding below is a *proposal* for that future work. It must not reuse the `0100 mmmm xxxx 1010` LDC family — that family is base `LDS` (MACH/MACL/PR/…) on J-Core (see the §3.1 encoding-space note); PTEH/PTEL/ASIDR live in the `xxxx 1110` (LDC) / `xxxx 1011` (STC) families per §3.1. A real `PTEU` encoding must be assigned from genuinely free slots when J64 is implemented.

`PTEU` would join the page-table register family alongside `PTEH`, `PTEL`, and `ASIDR` (§3.1):

| Mnemonic | Encoding | Hex Pattern |
|----------|----------|-------------|
| `LDC Rm, PTEU` | `0100 mmmm 0010 1010` | `0x402A \| m<<8` |
| `STC PTEU, Rn` | _unassigned_ (the old `0000 nnnn 0010 0011` proposal predates the §3.1 move to `xxxx 1011`) | — |

`PTEU` is privileged and exists only on PAE (`ADDR_WIDTH=40`) builds; on a non-PAE core the encoding is unallocated and decodes to illegal-instruction. The `xxxx=0010` slot is **proposed** — confirm it is free against the generated decoder and against SH-4 `PTEA` usage (J-Core does not implement SH-4 `PTEA`, so its slot is reusable, exactly as ASIDR reused the SH-DSP `MOD` slot in §3.1).

## 4. TLB Structure

### 4.1 TLB organization — shipped geometry (normative) and the recommendation it replaced

**This section is now normative for the shipped geometry.** It was titled
"Recommended TLB organization (**suggestion, not mandate**)" and gave a unified
32-entry TLB, which the RTL has never implemented; nothing else stated what the
hardware does, and [fact-ownership.md](../fact-ownership.md) had no row for it.
Flagged by [security/threat-model.md §11](../security/threat-model.md) and
closed by Wave-2 **B1**.

| Parameter | Shipped (J4) | Notes |
|-----------|--------------|-------|
| Split I/D | **Yes** — two independent instances | `core/cpu.vhd` instantiates `u_itlb` and `u_dtlb`, each `entity work.tlb` |
| ITLB entries | **8** | |
| DTLB entries | **16** | Twice the ITLB, on purpose: the D side reads every PC-relative literal pool that the I side fetches, *and* a guard (`mmudrain`) that needs more than 8 |
| Associativity | Fully associative | one combinational lookup port per instance |
| Replacement | NRU (invalid slot first) | |

`mmu.tlb.itlb` and `mmu.tlb.dtlb` in
[fact-ownership.md](../fact-ownership.md) bind both counts to the generic maps
in `core/cpu.vhd`.

**The geometry was measured, not chosen on paper** `[FPGA]`. `core/cpu.vhd`
records a 6-seed `nextpnr` sweep taken 2026-08-13, representative-harness `Fmax`
against a 32+32 control at mean 29.55 MHz: **8+16 mean 34.69** (shipped), 8+8
mean 34.31, 16+16 mean 33.01, 8+32 mean 31.36. `Fmax` scales with **total
comparator count**, and 8+16 is the point that buys the most clock without
starving the D side. The 32-entry recommendation this section used to carry
would have cost roughly 5 MHz on a core whose whole J4 budget is ~33 MHz
([platform-baseline.md §3](../platform-baseline.md)).

**Why the entry count is smaller than SH-4's 64 without being a reach
regression:** at the 16 KB base page ([design-spec.md §3.3](design-spec.md)),
8 ITLB + 16 DTLB entries cover the same address range a 32/64-entry 4 KB TLB
covers — see [j4-remediation-plan.md](../j4-remediation-plan.md)'s note on
exactly this trade.

A fully-associative TLB simplifies the indexing problem when mixing page sizes. Set-associative TLBs require either multiple lookups, VPN-partitioning by size, or skewed associativity — all of which add gates and timing pressure. At these entry counts, fully-associative CAM is comfortable in FPGA.

### 4.1a L1 cache indexing: the caches are PIPT, by upstream relocation

**The L1 instruction and data caches are physically-indexed, physically-tagged
(PIPT).** Not virtually-indexed. This is a property of *where the translation
sits*, not of the cache: on a translated access that hits the TLB, the core
replaces the frame bits of the address **before** the cache sees it, so the
cache is presented with a physical address and indexes and tags it as one.

**Normative statement of the relocation.** On a translated hit, the core drives
the external bus address as `PA[27:12]` = PPN bits where the PageMask says
"frame", and the incoming VA bits where it says "in-page offset";
`PA[11:0] = VA[11:0]` and `PA[31:28] = 0`. The lower bound of the relocated
field — **bit 12** — is what makes the caches PIPT rather than VIPT, and it is
the whole content of this section: `jcore-cpu`'s L1 index tops out at bit 12
(`cache/cache_pkg.vhd`, `cache_index_bits = 8` over 32-byte lines gives
`cache_index_msb = 12`), so relocating from bit 12 upward leaves **no** index
bit virtual. Relocating from bit 13 upward instead — which is what an earlier
revision of §2.2 still describes, see below — would leave `VA[12]` in the index
and make the cache VIPT at 4 KB pages. `mmu.l1.pipt` in
[fact-ownership.md](../fact-ownership.md) §Code bindings binds this bound to
`jcore-cpu@master` `core/cpu.vhd` so it cannot move silently.

**Consequences, both of which retire things this workspace still said:**

- **There is no virtual-synonym channel and no page-colouring obligation.** Two
  virtual aliases of one physical page resolve to the same physical address
  before indexing, so they occupy the same line by construction. There is
  nothing for software to arrange. [linux-spec.md §2.3](linux-spec.md) carried
  a VIPT contract and a colouring requirement for 4 KB pages; both are
  withdrawn there.
- **`mmucolor`, the CPU-level page-colouring guard, is retired.**
  `jcore-cpu@master` `.github` regression list, commit *"ci(mmu): retire
  mmucolor (PIPT moots page-coloring); wire reloc guards into full-regression +
  runner"* — replaced by `mmureloc` / `mmurelocif` / `mmurelocbp`, which assert
  the relocation itself.

**Status.**
> **RESOLVED 2026-09-07 — jcore-cpu@master: "feat(mmu): PIPT relocation of translated D accesses (VA->PA) + PA[12] export + mmureloc guard".**
> The I-side landed alongside it —
> **RESOLVED 2026-09-07 — jcore-cpu@master: "feat(mmu): PIPT relocation of translated I-fetches (VA->PA) + mmurelocif guard"** —
> and the last VIPT-era remnant in the cache was removed by
> **RESOLVED 2026-09-07 — jcore-cpu@master: "refactor(cache): drop the vestigial VIPT-era PA-tag path".**
> `cache/dcache_ccl.vhm` now states it in one line: *"PIPT: cpu.vhd relocates
> the address upstream of the cache, so a.a is already a PA; index and tag are
> both physical in every mode."*

**Prior state, recorded because it explains the documents that disagree.** VIPT
was a real intermediate state of this design, not a misreading: the cache tag
RAM was widened to a physical tag and switched on `AT` first, and full
relocation came later. Every VIPT statement elsewhere in this workspace dates
from that window.

### 4.2 TLB entry layout

Each TLB entry stores (one register-bit per logical field):

```
Tag fields:
  VALID         1 bit
  GLOBAL        1 bit          (Global; if set, ignore ASID_TAG match)
  VPN           up to 36 bits  (max VA bits minus min PageShift)
  ASID_TAG      16 bits        (kernel-encoded ASID[11:0] + gen_low[3:0])
  PageMask      4 bits         (encodes page size)

Data fields:
  PPN           up to 36 bits
  W, X, U, D    1 bit each
  C             1 bit
  STALE         1 bit (software-only, preserved)
```

Total ~91 bits per entry on J32, ~131 bits on J64. For the shipped 8 + 16 entries (§4.1): ~2.2 Kib of state — structural arithmetic, not a synthesis result. The VMID field present in earlier drafts has been **removed** (see project-wide decision in [glossary §5](../glossary.md)); hypervisor isolation is achieved via ASID partitioning, not VMID tagging.

**PAE reuses the J64 PPN budget.** A J32-PAE core ([design-spec.md §3.8](design-spec.md)) carries a 40-bit physical frame: `PPN = PA[39:14] = 26 bits` at the 16 KB base page. That fits inside the `up to 36 bits` already reserved here for J64, so a PAE entry costs **no extra TLB storage** over a non-PAE J32 entry beyond the high `PPN` bits the field already allows — the entry width sits between the ~91-bit J32 and ~131-bit J64 figures. The only entry-adjacent hardware cost is widening the physical-output port (and the L1 cache tags, §8) from 32 to 40 bits.

### 4.3 TLB match function

For each entry on a translation request:
```
match = entry.VALID && (entry.STALE == 0) &&
        (entry.VPN[high : pagebits_for_PageMask] == VA[high : pagebits])
match = match && (entry.GLOBAL || entry.ASID_TAG == ASIDR[tid])   ! tid = issuing thread context; constant 0 on non-FGMT cores (§2.1a)
```

The context tag is compared against **ASIDR** (the live per-context register set at context switch, §2.1a), **not** PTEH — PTEH carries the VPN only and is overwritten by hardware on every miss. `STALE` (§2.2) is enforced in the match: a software-revoked entry never hits, so the access faults into the trusted miss handler (revocation primitive — see [design-spec.md §6.3](design-spec.md)).

The bit range compared depends on the entry's PageMask: a 16 KB page compares VPN[35:14] (J64) or VPN[31:14] (J32); a 64 KB page compares VPN[35:16]; etc.

If exactly one entry matches: it provides the translation.  
If zero entries match: hardware initiates the miss sequence (see §5).  
If more than one matches: behavior undefined — software must not write duplicate entries. (Same rule as SH-4 and UltraSPARC.) The J4 reference implementation detects a multi-hit in hardware (S-I5) and takes an exception rather than translating; see the MULTI_HIT note in [§5](#5-tlb-miss-exception-sequence) for how it is delivered. Permission enforcement (IPROT/DPROT) on a hit is normatively specified in [design-spec.md §6.1](design-spec.md).

## 5. TLB Miss Exception Sequence

### 5.0 A hardware TSB walk precedes the exception

> **Implementation status — updated 2026-08-25 (was: "DESIGNED, PARTIALLY
> IMPLEMENTED", 2026-08-10).**
> **RESOLVED 2026-08-25 — jcore-cpu@master: "rtl(mmu): the hardware walker is the sole TLB installer".**
> This subsection **does** describe shipped hardware. `core/tlb_walk.vhd` is on
> `master`, instantiated at `tsb_ways => 2`; branch `mmu/tsb-hw-walker` is gone
> from `origin`. The kernel side is
> **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: stop installing TLB entries from software".**
> The per-item table at the end of this subsection is corrected in place.
> The full design is
> `docs/superpowers/specs/2026-08-09-hardware-tsb-walker-design.md`.

A TLB **miss** is no longer an exception in the first instance. It is a
**stall**, the way a cache miss is a stall. On a miss the pipeline holds and a
hardware FSM (`core/tlb_walk.vhd`) probes the TSB set addressed by `TSBPTR`.
**It probes both ways of that set**, way 0 first and then way 1, bailing out of
a way as soon as one of its two tag words mismatches:

- **On a tag match in either way** it installs the entry through the same `tlb_wr` port
  `LDTLB` uses and releases the hold. The faulting access replays and
  translates. **No exception is raised** — `SPC`, `SSR`, `EXPEVT`, `PTEH`,
  `TEA` and `MMUFSR` are *not* written, and no vector is fetched.
- **On no match in either way**, or when the matching entry has `V=0` or
  `STALE=1`, the walker stops.
  The miss condition is still true, so the sequence in §5.1 below runs
  **exactly as it did before the walker existed** — same vector, same
  `EXPEVT`, same `TEA`/`PTEH`/`TSBPTR`/`MMUFSR` capture. There is deliberately
  no separate "walk failed" signal.

The walker is **architecturally mandatory** on a J4-class MMU: there is no
`MMUCR` enable bit and no software TSB probe. `VBR + 0x400` still means "TLB
miss", but its handler is now the page-table walk, not a TSB probe.

**A walk cannot itself fault.** `TSBBR` holds a **P1 kernel virtual address**
(§2.6), and P1 is untranslated by architecture, so the walker folds it
(`PA = VA & 0x1FFFFFFF`) and its reads bypass translation entirely — no
nesting, no recursion, no new exception class. The fold is how the property is
realised, not an exception to it.

**A malformed `TSBBR` does not hang the walk — the walker fails OPEN.**
`core/tlb_walk.vhd` carries a liveness counter over *every* non-idle state
(`timeout_cycles`, 255), and expiry "takes the same exit as a tag mismatch:
`tried` set, state `st_idle`, busy low — the miss condition is still true, so
`cpu.vhd` raises the exception on the next cycle." The RTL's own comment states
the direction: it "gives up exactly as it does on a tag mismatch — it fails
**OPEN**, to the software miss path, never closed into a stall." *(This
paragraph previously ended "A malformed `TSBBR` hangs the walk, exactly as it
would hang the software handler's `mov.l`", which is the opposite of what the
hardware does and was flagged by
[security/threat-model.md §11](../security/threat-model.md) as load-bearing,
because §7.5 of that document argues from this sentence. Fail-open is the safer
of the two readings and it is the true one — but note what it does **not**
supply: there is still no `TSBBR` bounds check anywhere in `tlb_walk.vhd`, which
is why that document's **L7** exists.)*

**The walk must be self-terminating.** The miss condition is a *level* that
stays true until the miss is resolved, so a walker that re-arms on that level
never yields a cycle in which the exception can fire, and the core waits
forever for an ack. The FSM carries a one-shot for this. (Established
empirically by the Phase-1 feasibility spike, `jcore-cpu` commit `90e6cbc`.)

**Per-item implementation status:**

| item | status |
|---|---|
| Stall-and-walk mechanism (ack withheld, external `db_o` borrowed) | **merged**; `core/tlb_walk.vhd` on `jcore-cpu` `master`. *(This row read "proven on RTL by spike `90e6cbc`; walker FSM in progress". `90e6cbc` is **not** an ancestor of `origin/master` — the branch was rebased before merge, which is why [../decisions/0002](../decisions/0002-supersede-convention.md) forbids citing a SHA.)* |
| Exception path on walk failure (§5.1) | unchanged and shipped |
| TSB entry format | **Phase 2: 2-way, 32-byte set, `tsb_ptr()` scaling by `<< 5`, `ASID` folded into the index** (§2.8). **RESOLVED 2026-08-25 — jcore-cpu@master: "rtl(mmu): the hardware walker is the sole TLB installer"** *(promoted from "IMPLEMENTED on `mmu/tsb-hw-walker`, not merged")*. Phase 1's 1-way 16-byte slot is superseded. |
| Two-way probe in the walker FSM | Phase 2, IMPLEMENTED (`core/tlb_walk.vhd`, generic `tsb_ways => 2` from `core/cpu.vhd`); guard `mmuwalkway1` |
| `TSBSLOT` / `TSBVSEED` / `TSBVICT` (§2.12, §2.13) | Phase 2, IMPLEMENTED and decoded in `core/datapath.vhm` |
| Instruction retirement (§3.1) | **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `decode/gen-go/spec/sh4/mmu.toml` containing `All seven were retired`.** *(This row previously read "Phase 3, not yet started. All seven instructions still exist and still work." They do not: the whole `0000 nnnn xxxx 1011` read family is retired and the encoding space is back in the free pool. The write side — `LDC Rm,{PTEH,PTEL,ASIDR}` — is deliberately kept.)* |

### 5.0a The I-side arm is speculative — the transmitters of a squashed fetch, and the rules that bound them

**Why this subsection is here.** [security/threat-model.md §7.2](../security/threat-model.md)
retires the "the core is non-speculative" premise by showing that the I-side arm
of the walk described in §5.0 runs off a *live fetch*, while the fault it may
raise is deferred to dispatch. Its item **L4** makes covering that arm a launch
requirement, and Wave-3 task **C2b** owns it. The rules land here rather than in
a decision record because [decisions/README](../decisions/README.md)'s test is
ownership of the *subject*: §5.0 owns the walk, so the walk's speculation rules
are inline, in the section that specifies it.

**What is being bounded is shipping hardware, not a proposal.** Three of the four
mechanisms Wave 3 lists for C2b — commit-time predictor updates, a tenant-tagged
BTB, and the one the plan called "degenerate-STT taint" — describe structures
`jcore-cpu@origin/master` does not contain, and are already specified for the design points
[decisions/0009](../decisions/0009-in-order-fgmt-is-the-default-path.md) paused
([ooo/j32ooo-spec.md §3.2, §9.4](../ooo/j32ooo-spec.md)). The fourth — delayed
speculative TLB/PTW fill — is the one that lands on the core that exists, and it
is the only one this subsection is about. *(The third name is retired post-F,
2026-09-10: it is 2019 work, and the register-taint structure it names is claimed
in force by AMD US10956157B1. What §9.4 rule 3 specifies is a load-forwarding
restriction that adds no register state —
[ooo/j32ooo-spec.md §20.7](../ooo/j32ooo-spec.md) rejection 3. Nothing in W-R1–W-R5
changes.)*

#### The arm, quoted

`core/cpu.vhd` computes the I-side miss condition from the fetch request and the
ITLB lookup alone:

```vhdl
walk_i_miss <= '1' when i_at_translated = '1' and sig_inst_o.en = '1'
                        and tlb_i_multihit = '0' and tlb_i_hit = '0'
                        and sig_db_o.en = '0' and d_fault_held = '0' else
               '0';
```

Every term on that line is one of five things: the fetch request itself
(`sig_inst_o.en`), the ITLB lookup result (`tlb_i_hit`), a translation-enable
gate, a multi-hit gate, or the older-D-access ordering pair. Downstream,
`walk_req` adds one more — `dp_sr.rb = '0'`, the handler-residency gate of
§7.1 of `jcore-cpu/docs/architecture/tlb.md`. **Not one of the six is a dispatch,
squash or branch-resolution term**, and `core/tlb_walk.vhd` has no abort input —
its own arm is a per-VPN one-shot and a give-up counter, neither of which is
driven by the pipeline. The matching property is stated on the fault side in
`core/components_pkg.vhd`: *"A fetch that is squashed before dispatch therefore
never raises anything."* The fault is squashed. The walk is not.

#### The transmitters

A fetch that is squashed before dispatch reaches **4** transmitters on
`origin/master` today. They are listed in the order a single squashed fetch
reaches them, because each later one is conditional on the one before:

| # | Transmitter | Left behind by a squashed fetch because |
|---|---|---|
| 1 | **L1-I line** | `cache/icache_ccl.vhm` enters `MISS1` on a demand miss and commits the tag in that state. The fill has no speculation input at all |
| 2 | **L1-D lines touched by the walk** | the walker's TSB reads are cacheable by an explicit policy decision (`core/cpu.vhd`, the `TSB COHERENCY POLICY` block) — this is the observable [security/threat-model.md §7.1](../security/threat-model.md) builds AnC on |
| 3 | **ITLB entry** | the walk installs on a tag match through the same port `LDTLB` uses (§5.0) |
| 4 | **DTLB entry, via the I→D shadow fill** | an ITLB install registers `shadow_wr <= walk_install and walk_side_i` in `core/cpu.vhd` and re-drives the DTLB write port one cycle later |

**Transmitter 4 is the one that is easy to miss, and it is the one that crosses
structures.** The shadow fill is an address *prediction*: an ITLB install is
taken as evidence of an imminent D-side access to the same page, because SH code
pages carry PC-relative literal pools. It is bounded in the RTL — `core/tlb.vhd`
skips the install entirely when the page is already resident and usable, and
installs `used = '0'` (next NRU victim, never promoted on a hit) when it does
land — but **both bounds are about not displacing demand entries; neither is
about speculation.** The consequence is that an I-side event that never
architecturally happened becomes visible to a *D-side* observer. That is a
different exposure from transmitters 1–3, and W-R5 below is where it is
answered.

#### Rules

- **W-R1 — the arm waits.** An I-side TSB walk **must not be armed by a fetch
  that has not dispatched.** `walk_i_miss` gains a dispatch dependence, or an
  equivalent squash term that disarms it before `tlb_walk` leaves `st_idle`.
  This is [j4-remediation-plan.md §E.10](../j4-remediation-plan.md)'s *delayed
  speculative TLB/PTW fill*, applied to the only walker this project has, and it
  is the same shape as delay-on-miss: a condition on an existing arm, not a new
  structure. **It closes transmitters 2, 3 and 4 of the 4 in one term**, because
  3 requires 2 and 4 requires 3.

- **W-R2 — an abort path is not a substitute for W-R1.** Adding an abort input
  to `core/tlb_walk.vhd` closes transmitters 3 and 4 and **does not close
  transmitter 2**: by the time a squash can be signalled the walk has already
  issued its TSB reads, and those reads are the AnC observable. An abort path may
  be worth adding for other reasons — it bounds how long a doomed walk holds the
  bus — but it does not discharge W-R1, and a review that accepts it as
  equivalent has accepted a mitigation for the install while leaving the
  cacheable-read footprint intact.

- **W-R3 — the walker stays the sole installer.** W-R1 and W-R2 are conditions
  on an existing arm and an existing port. Neither may be implemented by adding
  a second install path. The shadow fill is not one: `shadow_wr` is derived from
  `walk_install`, so the walker remains what
  [security/threat-model.md §12](../security/threat-model.md) names as the
  premise of half of §7.1 — a code-level trigger that has **not** fired.

- **W-R4 — the L1-I wrong-path fill is an accepted residual, and the reason is
  on the do-not-build list.** W-R1 does not reach transmitter 1, and no rule in
  this document closes it. A fetch cannot wait for its own dispatch — it is what
  produces the instruction that dispatches — so the delay shape that works for
  the walk does not exist here. The two mechanisms that would close it are both
  refused elsewhere on grounds this task is not entitled to overturn: a
  flush-on-switch filter cache is on
  [j4-remediation-plan.md §E.10](../j4-remediation-plan.md)'s **don't build**
  list, and a speculative fill buffer promoted at non-speculative is
  [ooo/j32ooo-spec.md §20.7](../ooo/j32ooo-spec.md) rejection 1, refused there on
  live-patent grounds rather than on cost. **The residual is recorded as
  accepted, not closed**, in [security/threat-model.md §10](../security/threat-model.md).
  A third mechanism — discarding the returning line instead of committing its tag
  when the fetch that requested it was squashed — is a condition on a tag write
  rather than a buffer, so §20.7's rejection does not reach it on its face; it is
  **not adopted here** because the prior-art check §20.7 requires has not been
  done, and because nothing has yet measured how often the case arises. W-E1
  below is what would supply the second half of that.

- **W-R5 — the shadow fill's I→D disclosure is intra-tenant, and is named rather
  than closed.** Under W-R1 the shadow fill can no longer be armed by a squashed
  fetch, which is the whole of its transient-execution exposure. What remains is
  architectural: a page that was *executed* becomes DTLB-resident without ever
  being read, so D-side timing reports I-side activity. Observer and victim are
  inside one tenant — [security/threat-model.md §8](../security/threat-model.md)'s
  **L1** places both in the same tenant, exactly as it does for §7.1's AnC
  primitive — so no item of that bar requires this to be closed, and it is filed
  in §10 with the other intra-guest channel rather than fixed. **The counter is a
  separate matter and is not disposed of by privilege.** `TLBINST`
  ([soc/p4-mmio-map.md](../soc/p4-mmio-map.md)) reports DTLB slot writes and
  therefore reports shadow installs directly. It sits in P4, which a *user* process
  cannot read — but the adversary of
  [security/threat-model.md §1](../security/threat-model.md) is a **guest kernel**,
  which runs privileged inside its guest, so P4 residency is not the boundary here
  and trapping is. That is precisely the obligation of that document's **L7** part
  4, and part 4 names only `TSBCNT`; the widening is recorded there.

#### What this costs, and the experiment that prices it

W-R1 delays the start of an I-side walk by the fetch-to-dispatch distance of the
pipeline it is implemented on. That distance, and the fraction of I-side walks
that are armed off fetches which never dispatch, are
**unknown at this stage — needs measurement**.
This is the first Wave-3 item whose measurement can run on hardware that exists.

**W-E1 — how often does a squashed fetch walk?** Count I-side arms of
`walk_i_miss` whose fetch never reaches dispatch, over the `sim/tests` MMU
corpus and **two** directed tests, because the pipeline has two ways to squash a
fetch and a test that exercises only one of them would report a zero that means
nothing:

1. **Control flow.** A taken branch placed immediately before a code page that is
   mapped in the TSB but absent from the ITLB, so any fetch beyond the delay slot
   walks. `core/datapath.vhd` names this case in its own comments — "the
   speculative branch-target fetch, whose younger fault overwrites the older one".
2. **The exception squash window.** A fault taken while a later fetch is in
   flight, which is the window `core/components_pkg.vhd` describes as existing
   solely for "the precise-exception squash window … and the P4/TSB assist".

> **Kill criterion.** If the count is identically zero across the corpus **and
> both** directed tests fail to make it non-zero, then the arm is not reachable
> on a squashed fetch on this pipeline, W-R1 buys nothing here, and
> [security/threat-model.md §7.2](../security/threat-model.md) is overstated
> rather than conservative. §12 of that document already says what to do in that
> case: **re-derive it, do not delete it** — the exposure returns with any front
> end that fetches further ahead. A zero from the corpus alone does **not** meet
> this criterion; a corpus that never builds the scenario is the failure mode
> this whole item is about.

A non-zero count is also what discharges L4's *non-vacuity* clause for this
transmitter. The test is "this counter reads zero": it must **fail** on the core
as it stands and pass after W-R1, which is the demonstration that document asks
for and that is usually skipped.

**W-E2 — what does the wait cost?** A/B the gated arm over the same corpus, on
cycles. There is a measured comparator already in the tree for the structure most
affected: `jcore-cpu/docs/architecture/tlb.md` §4.1 records a whole-run A/B of
the shadow fill on `mmudrain`. Report W-E2 against that same harness so the two
numbers are commensurable, and report them **together** — W-R1 makes the shadow
fill rarer, so pricing the gate without re-pricing the fill prices half a change.

No figure from [j4-remediation-plan.md §E.10](../j4-remediation-plan.md) is
carried into this subsection as a cost for this core. Its delay-on-miss numbers
are measurements of an 8-wide out-of-order machine and of an ARM Cortex-A53, and
[decisions/0005](../decisions/0005-unmeasured-figures-are-removed.md) is the
record about what happens when a number from one machine is asked to stand in
for another's.

### 5.1 Exception sequence (when the walk does not resolve the miss)

When a memory access misses the TLB, translation is enabled (MMUCR.AT=1), and
the hardware TSB walk of §5.0 did not install a translation:

1. Compute hash and TSBPTR (see §2.8). Store result in TSBPTR register.
2. Latch the faulting effective address into TEA.
3. Latch the faulting VPN into PTEH. The page size is not yet known at miss time (it is decided by the PTE the handler eventually loads), so hardware captures the VPN at the **finest** supported granularity — 4 KB, i.e. `PTEH[31:12] = VA[31:12]`, low bits `[11:0]` zeroed — and the handler masks coarser as needed at `LDTLB` time. (Capturing only `VA[31:14]` would alias 4 KB pages that differ in `VA[13:12]`.) **ASIDR is not touched** — the kernel has set ASIDR at context switch and it remains valid for the miss handler to read.
4. Save PC → SPC and SR → SSR. The exception is a **re-execute** type: SPC must be the faulting instruction's own PC so `LDTLB.RN`/`RTE` re-runs the access (critical for stores — a faulting load's destination register is already written, but a dropped store write is lost). I-fetch faults capture the live PC (detected at the fetch pointer); **D-access faults are detected in the MA stage, where the live PC has run a variable distance ahead**, so hardware latches the faulting instruction's restart-PC and SR on the first fault cycle (alongside TEA/PTEH) and sources SPC/SSR from those latches.
5. Update SR: set MD=1, RB=1, BL=1, IMASK=0xF.
6. Jump to the vector for the fault CLASS: **`VBR + 0x400` for a miss**, **`VBR + 0x100` for a protection violation** (the general-exception vector, shared with Error / Slot Illegal / General Illegal / TRAPA). `EXPEVT` discriminates within each class, and `MMUFSR` (§2.11) additionally separates `DPROT_R` from `DPROT_W`, which share `EXPEVT = 0x0C0`.

   This is the SH-4 layout (SH7750 hardware manual Rev 2.0 02/99). Two earlier arrangements are retired: the per-access-type miss split at `+0x420`/`+0x440` (the handler was byte-identical for all three, so it only triplicated the hot path's I-cache footprint), and putting all six causes on `+0x400` (commit `a8ab8d0`), which forced the fast path to test the cause on every TSB hit — see §3.2a for why that was a livelock guard rather than a preference. *Guard: `mmuvecsplit`.*

Exception priorities and ordering relative to other interrupts follow SH-4 conventions.

**Concrete EXPEVT / vector / SPC facts (ground truth: `exceptions.toml`):**

| Fault | VBR offset | EXPEVT | SPC source | SSR source |
|-------|-----------|--------|-------------|-------------|
| TLB IMISS (instruction-fetch miss) | `+0x400` | `0x040` | `TLBPC` (delay-slot-aware I-fetch restart PC) | live `SR` |
| TLB DMISS_R (data-load miss) | `+0x400` | `0x060` | `TLBPC-4` (faulting-instruction restart PC) | latched `TLBSR` |
| TLB DMISS_W (data-store miss) | `+0x400` | `0x080` | `TLBPC-4` (faulting-instruction restart PC) | latched `TLBSR` |
| TLB IPROT (instruction protection violation) | `+0x100` | `0x0A0` | `TLBPC` (delay-slot-aware I-fetch restart PC) | live `SR` |
| TLB DPROT_R (data-load protection violation) | `+0x100` | `0x0C0` | `TLBPC-4` (faulting-instruction restart PC) | latched `TLBSR` |
| TLB DPROT_W (data-store protection violation) | `+0x100` | `0x0C0` | `TLBPC-4` (faulting-instruction restart PC) | latched `TLBSR` |

**Note:** the VBR-offset column now DOES discriminate — misses at `+0x400`, protection at `+0x100` — which is why the miss handler no longer tests the cause. `EXPEVT` separates the three causes within each class, but DPROT_R and DPROT_W both report `0x0C0`, so `EXPEVT` alone cannot recover the direction of a protection fault. **MMUFSR** (§2.11, MMIO `0xFF00002C`) exists specifically to resolve that: it is latched on every TLB exception and carries an explicit `WRITE` bit. (This note previously read "every row above shares the one vector ... it discriminates nothing", which was true of the merged-vector arrangement and is not true now.)

**MULTI_HIT is delivered out-of-band.** A multiple-TLB-match (S-I5, `tlb.vhd` `i_multihit`/`d_multihit`) does **not** use the TLB vector. It is routed to the existing General Illegal register-model exception: `PC <- VBR + 0x100`, `EXPEVT <- 0x180`. **Rationale:** the decoder's system-plane immediate-value field (ROM imm-value selector, 5 bits) is at capacity — 32 of 32 distinct constants are used — so minting a dedicated MULTI_HIT vector/EXPEVT pair would require widening the field to 6 bits and regenerating the ROM template (guarded by `romImmFieldBits` in the decoder generator). Reusing General Illegal costs zero new immediate literals and zero new opcodes. Software distinguishes a multi-hit from a real illegal instruction with the sticky multi-hit status flag, not with EXPEVT.

**Reconciliation note.** An earlier revision of this specification (and of the implementation) gave each TLB access type its own vector: I-fetch `VBR + 0x400`, data-load `VBR + 0x420`, data-store `VBR + 0x440` — the "Option-A" layout — so that the miss handler could branch on access type without reading EXPEVT. The implementation merged all six causes onto the single `VBR + 0x400` vector (commit `a8ab8d0`, "mmu: merge the three TLB-miss vectors into a single VBR+0x400"; design note at `jcore-cpu/decode/gen-go/spec/sh4/exceptions.toml:386-392`). **Rationale:** the real handler turned out to be byte-identical across all three entries — access type only matters on the slow `do_page_fault` path, which reads EXPEVT anyway — so the split merely triplicated the hot path's I-cache footprint. The merged layout also matches stock SH-4, which has always used one TLB vector (Renesas/Hitachi SH-4 hardware manual, 1998). EXPEVT codes and the SPC/SSR capture rules are unchanged by the merge. 

**Second reversal (current).** The merge above was itself partly undone: the three MISS causes keep `VBR + 0x400`, but the three PROTECTION causes moved to `VBR + 0x100`. The merge's rationale — one byte-identical handler — held only for the misses. Protection faults are not handled by the miss path at all, and routing them through it created a livelock: a protection fault against a VPN/ASID with a still-valid TSB entry TSB-hits, gets its entry reinstalled, and retries forever without ever reaching `do_page_fault()`. Avoiding that cost a cause test on every TSB hit. Splitting protection back out excludes it by construction, restores the SH-4 layout exactly (SH7750 manual Rev 2.0 02/99: misses `H'400`, protection `H'100`), and took the hot path from 11 instructions to 9. *Guard: `mmuvecsplit`.*

**SPC/SSR semantics.** I-fetch faults (IMISS/IPROT) save a delay-slot-aware restart PC (`TLBPC`) and take `SSR` from the live `SR`. D-access faults (DMISS_R/DMISS_W/DPROT_R/DPROT_W) save the faulting-instruction's own restart PC (`TLBPC-4`) so that `LDTLB.RN`/`RTE` re-executes the faulting instruction, and take `SSR` from the latched `TLBSR` (captured on the first fault cycle, alongside `TEA`/`PTEH`), because by the MA stage the live PC has already run ahead of the faulting instruction.

**Implementation note (exception re-entry gate).** Architecturally, `SR.BL=1` blocks a second exception from overwriting `SPC`/`SSR` during entry. The reference core instead gates re-entry on **`SR.RB`** (the in-handler bank-select), because the single-level save model means the bare-metal/early-boot environment can leave `BL=1` from reset, which would make `BL` useless as the in-handler discriminator. Consequence: a context **legitimately** running with `RB=1` cannot itself take a TLB fault. This is acceptable for the kernel's miss-handler model (the handler runs entirely in P1/untranslated and is provably non-faulting — see [design-spec.md §4.3](design-spec.md)), but it is a deviation from stock SH-4 `BL` semantics worth noting for anyone porting a different handler model.

### 5.2 Instruction-fetch miss inside a multi-word instruction or SIMD block

This subsection applies when the implementation pairs this MMU with an extension that introduces a **multi-word instruction unit** — i.e. an architectural instruction whose fetch spans more than one 16-bit word. Two such extensions exist in the J-Core roadmap: the two-word density instructions `movi20`/`movi20s`/`lea`/disp12-`mov.l` ([../isa-density/spec.md](../isa-density/spec.md)) and the SIMD prefix block ([../simd/spec.md](../simd/spec.md)). It imposes one additional requirement on the instruction-fetch miss path (the `VBR + 0x400` vector of §5 step 6); cores with neither extension are unaffected.

**The unifying rule.** When an instruction-fetch TLB miss (or any synchronous instruction-fetch fault) is taken while the CPU is partway through fetching a multi-word unit, the CPU **must save the PC of the unit's *first* word into SPC**, never the address of an interior word. The miss handler is then MMU-generic exactly as today; `LDTLB.RN` + `RTE` returns to the unit's start and the whole unit re-executes (re-fetching all its words) against the now-mapped page. This is correct and idempotent because a multi-word unit commits no architectural state until it retires, so re-execution from the start reproduces it exactly. Returning to an interior word would instead resume *inside* an instruction — interpreting immediate data or a governed SIMD instruction as a fresh opcode — which is silent corruption, not a fault. (Prior art: Intel 386, 1985, validating page-split instructions against the instruction's start address.)

**SIMD block.** A SIMD block is a run of consecutive halfwords — a prefix plus up to four governed instructions (≤ 10 bytes), or a `VLNS`+`VEXT`/`VINS` pair (4 bytes). The prefix establishes a *decode-stage shadow latch* (`SIMD_VAL`, lane width, block length) that is **not** architectural state and is cleared on every exception entry ([../simd/spec.md §6.5](../simd/spec.md)). The first-word PC the rule requires is the **prefix PC**; returning to a governed instruction with the shadow latch cleared would decode it as a plain scalar SH op.

**Two-word density instructions.** `movi20`/`movi20s`/`lea`/disp12-`mov.l` fetch word1 after word0. The first-word PC the rule requires is **word0's PC**; word1 is immediate / displacement data, not a valid opcode, so returning to it is garbage. The in-order requirement (keep the architectural PC at word0 while the fetch pointer advances to word1) is detailed in [../isa-density/hardware-impl.md §4.2](../isa-density/hardware-impl.md). Note `movmu`/`movml` are *single-word* instructions and so do not engage this rule, but they are multi-*data*-access and have their own restart contract ([../isa-density/spec.md §5](../isa-density/spec.md)).

**SIMD blocks (in-order J32 + TLB): prefix-time block-fetch validation.** A SIMD block's governed instructions are decoded in the cycles *after* the prefix, so by the time a governed fetch faults the prefix has retired and its decode shadow latch is gone — late detection cannot easily recover the prefix PC. The clean fix is to validate the whole block up front. The block length is known at prefix decode, so the last halfword address `end = prefix_PC + 2·N` is known immediately. If `end` falls in a different page than the prefix (a single page-number comparison; false for the overwhelming majority of blocks at a 16 KB page), the front end issues a fetch-translation probe of `end`'s page during the prefix's otherwise-idle MA slot, before any governed instruction issues. A miss on that probe enters the `VBR + 0x400` vector normally with SPC = prefix PC — the existing miss sequence of §5 needs no change, because the prefix *is* the faulting instruction at that point. After the probe resolves, all governed fetches in the block are guaranteed to translate. The `VLNS`+`VEXT`/`VINS` pair is validated by probing `prefix_PC + 2`. Out-of-order implementations (J32-OOO) get the same prefix-PC reporting for free from their ROB atomic-commit group and need no explicit probe.

**Two-word density instructions (in-order J32 + TLB): simpler still — no pre-validation.** `movi20`/`lea`/disp12 are a *single* instruction parked in decode while word1 is fetched, so the instruction is still the in-flight decode when the word1 fetch faults. No probe is needed; the implementation merely keeps the architectural/exception PC pinned at word0 (the fetch pointer advances to word1 independently) so the standard fetch-fault path captures `SPC = word0_PC`. Detail in [../isa-density/hardware-impl.md §4.2](../isa-density/hardware-impl.md).

**Cost.** For the SIMD case the probe reuses the existing instruction-fetch translation path; the only new logic is the page-number comparator on `prefix_PC` vs. `end` and the conditional one-cycle stall (which fits the existing multi-cycle decode sequencer). No new TLB port is required if the probe is allowed to share the fetch port across one extra cycle. The two-word density case adds nothing beyond not advancing the architectural PC early. Untranslated kernel code (P1/P2) and MMU-disabled operation are unaffected in both cases.

## 6. Register Banking on Exception Entry

Inherited from SH-3/SH-4 unchanged. On any exception (including TLB miss):

- If SR.MD was 0 (user mode) and SR.RB was 0, transition to MD=1, RB=1. Bank 1 R0–R7 are now visible; bank 0 R0–R7 are preserved.
- If already in MD=1 with RB=1, no bank change.
- R8–R15 are not banked; software must save/restore them if used.

The TLB-miss handler's hot path (described in §7) uses only R0–R3 of bank 1, requiring no register saves. The hot path is ~10 instructions (two CMP/EQ pairs for VPN and ASID_TAG plus the LDTLB.RN) — slightly longer than the SH-4-style single-comparison handler because of the ASID split, but still well under the ~30–50 of a pure software walker.

## 7. TLB Miss Handling

> **SUPERSEDED — 2026-08-25.** The status block below was written 2026-08-10 and
> said: *"§7.0 … is **partially implemented** (`jcore-cpu` branch
> `mmu/tsb-hw-walker`). §7.1 is what the RTL and linux@jcore run **today** …
> If you are changing code right now, §7.1 is what you will find in the tree."*
> **Both halves are now false, and it contradicted §7.1 of this same document,
> which already said "removed".**
>
> - §7.0 is merged and shipped:
>   **RESOLVED 2026-08-25 — jcore-cpu@master: "rtl(mmu): the hardware walker is the sole TLB installer".**
> - §7.1 is retired, not shipped:
>   **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: retire inlined TLB fast path and STC ASIDR/TSBPTR reads".**
>   Its sequence no longer assembles.
>
> **§7.0 is what you will find in the tree. §7.1 is `HISTORICAL` and is marked so
> at its own heading.**

### 7.0 The hardware TSB walk (design; see §5.0)

The nine-instruction sequence of §7.1 is replaced by hardware. The FSM
performs the same probe — same two tag comparisons, same `PTEL` install — with
two additional checks the software handler never made (`V=1` and `STALE=0`,
see §5.0), and without taking an exception at all on a hit.

**Phase 2: the probe covers two ways.** `TSBPTR` addresses a 32-byte **set**,
and the FSM walks way 0 (`+0`/`+4`/`+8`) and then, only if way 0 fails, way 1
(`+16`/`+20`/`+24`). Way 1's words are a D-cache hit into the line way 0
already filled, so the second way costs bus turns rather than memory latency.
Read counts: **3** for a way-0 hit, **5** for a way-1 hit, **4** for a
both-ways miss that goes on to the exception. Bailing on a `tag_hi` mismatch
before reading `tag_lo`/`data` is what keeps a way-0 miss cheap.

**Software's remaining role** is the slow path only: on a walk failure the
handler at `VBR + 0x400` walks the page tables, fills the TSB slot, and
installs via `LDC PTEH` / `LDC PTEL` / `LDTLB.RN`. That is
`__jcore_tlb_walk()` in `arch/sh/mm/tlb-jcore.c`, which already exists.

**TSB store order is now load-bearing.** The walker compares `tag_hi` first,
so `tag_hi` must be the **commit point**: software writes `data`, then
`tag_lo`, then `tag_hi` last, with a barrier before the final store.
Otherwise a walk can observe a torn entry — correct VPN, stale `ASID`/`PTEL` —
and install a wrong translation *silently*, with no exception.
`tlb-jcore.c` used to write `tag_hi` **first**; that was a defect independent
of the walker. **Fixed in Phase 2** —
**RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: commit TSB entries tag_hi-last, not tag_hi-first"**
*(promoted from "`linux@jcore` branch `mmu/tsb-phase2`, not merged")*:
all three words are now stored by a single helper,
`jcore_tsb_write_entry()`, which is the only place in the kernel that writes a
TSB entry. Hardware cannot distinguish a torn entry from a legitimate one, so
no bare-metal guard can catch a regression of this order — concentrating the
stores in one reviewed function is the enforcement.

**Expected cost:** ~5–6 cycles fault-to-resumed-execution for a warm TSB hit,
against the 22 (IMISS) / 23 (DMISS) measured for §7.1. The saving is the two
pipeline redirects (~9 cycles) and the fetch/decode of nine instructions
(~15 cycles) — **not** fewer memory accesses; the walker issues the same three
loads.

### 7.1 The software handler (HISTORICAL — retired in Phase 3)

> **HISTORICAL 2026-08-25.** The sequence below **no longer assembles** —
> `stc tsbptr`, `cmp/eq pteh`, `cmp/eq asidr` and `ldtlb.rn Rm` are all General
> Illegal now.
> **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: retire inlined TLB fast path and STC ASIDR/TSBPTR reads"**
> deleted `JCORE_TLB_FASTPATH` from `arch/sh/kernel/cpu/jcore/ex.S`;
> **RESOLVED 2026-08-25 — jcore-cpu@master: "rtl(mmu): the hardware walker is the sole TLB installer"**
> retired the four instructions it depended on. *(This block previously cited
> jcore-cpu `09304a3`, which is not an ancestor of `origin/master`.)*

Kept as the record of what the hardware walker replaced, and of the cost
baseline the walker is measured against. `VBR + 0x400` today is
save-regs / call `__jcore_tlb_walk()` / restore / `RTE`, reached only on a
walk failure.

**TSB tag format.** The 64-bit tag word is laid out as two 32-bit halves to avoid VPN/ASID-bit overlap (which would otherwise occur for small pages where VPN extends down into bit positions also covered by ASID_TAG):

```
TSB tag word (8 bytes, two 32-bit halves):
  tag_hi (offset 0, 4 bytes)  = expected VPN  (matches PTEH after miss)
  tag_lo (offset 4, 4 bytes)  = expected ASID_TAG  (matches ASIDR)
```

The kernel writes both halves at TSB-fill time. The miss handler compares both halves against PTEH (VPN) and ASIDR (ASID_TAG) — two compares, each done in ONE instruction by the fused `CMP/EQ PTEH,Rn` / `CMP/EQ ASIDR,Rn` (§3.1), which read the CSR onto ybus and set T without a `STC` or a scratch register.

**`tag_hi` is written at the architecture's finest granularity — 4 KB — for
every page size.** `JCORE_TSB_TAG_SHIFT` = **12**, and it is not `PAGE_SHIFT`.
The hardware walker compares `tag_hi` against the *raw* faulting VA with an
exact 32-bit equality and applies no page-size field to it (`PageMask` lives in
`data`, `PTEL[11:8]`, and is applied only at install), so the tag must be
canonical. The same rule already governs the PTEH capture in §5.1 — hardware
latches `PTEH[31:12] = VA[31:12]` precisely because the page size is not known
at miss time — and the TSB *index* is 4 KB-granular for the same reason
(`tsb_ptr()` hashes `VA[31:12]`, §2.8). Tag granularity, index granularity and
PTEH capture are one fact with one value.

> **Why this is stated as a constant rather than left implicit.** A tag written
> as `addr & PAGE_MASK` under `PAGE_SHIFT = 14` can never match a first touch
> outside a page's base 4 KB sub-page; the fault then repeats forever, and there
> is no retry counter. That is the 16 KB TLB-walker livelock, and its cause was
> exactly this constant being taken from `PAGE_SHIFT` instead of from the
> architecture. Nothing about **16 KB** was wrong — the page-size fact was
> correct in the docs, in Kconfig and in the RTL throughout. The registry
> therefore carries `mmu.tsb.tag.shift` as its own row, bound to the kernel's
> `JCORE_TSB_TAG_SHIFT`, so that a build in which the constant is absent or
> disagrees fails rather than livelocks.
> **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: write the canonical 4 KB TSB tag, never addr & PAGE_MASK".**

Only the three **miss** causes arrive here; protection faults take `VBR+0x100` (§5), so the handler does not test the cause.

```asm
        ! Inlined AT VBR+0x400 (not jumped to). SR.RB=1, bank 1 selected.
tlb_miss:
        stc      tsbptr, r0     ! Read pre-computed TSB slot address
        mov.l    @r0+, r1       ! Load expected VPN (tag_hi); r0 += 4
        cmp/eq   pteh, r1       ! VPN match?  (fused CSR-vs-Rn compare)
        bf       tsb_miss_slow  ! No: slow path
        mov.l    @r0+, r1       ! Load expected ASID_TAG (tag_lo); r0 += 4
        mov.l    @r0, r3        ! Load TTE data -- issued here so its load-use
                                !   latency hides behind the compare + bf below
        cmp/eq   asidr, r1      ! ASID match?  (fused compare)
        bf       tsb_miss_slow  ! No: slow path
        ldtlb.rn r3             ! PTEL <- r3, install, and return -- one insn,
                                !   no delay slot, no staging through the CSR
```

**Nine instructions, and no taken branch on a TSB hit.** Measured fault → back
executing the faulting instruction: **22 cycles** (IMISS) / **23 cycles**
(DMISS_R/W), of which ~9 is fixed hardware exception entry and `LDTLB.RN`
redirect. See `jcore-cpu/sim/bench_tlb_hotpath.sh` and
`sim/profile_tlb_hotpath.py` for the per-instruction attribution.

Three earlier shapes of this sequence are retired, and it is worth knowing why
none of them come back:

| retired | why |
|---|---|
| `stc pteh,r2` + `cmp/eq r1,r2` per compare | the fused compares removed 2 insns and freed a scratch register |
| `ldc r3,ptel` + `ldtlb.rn` | `LDTLB.RN Rm` installed straight from the GPR |
| `stc expevt` + `add #-128` + `cmp/pl` (or the short-lived `CMP/MISS EXPEVT`) | only needed while misses and protection shared a vector; §3.2a |

Hot path: ~10 instructions (VPN compare + ASID compare + LDTLB.RN). With the slow path inlined, the full handler fits in ~30 instructions.

**PAE variant.** On a wide-physical build ([design-spec.md §3.8](design-spec.md)), the TTE `Data` is the full 64-bit TSB `Data` word (the non-PAE handler above uses only its low 32 bits). The handler stages both halves before `LDTLB.RN`:

```asm
        mov.l   @r0+, r3        ! TTE data low  (PTEL image: PPN[31:14]+flags)
        ldc     r3, ptel
        mov.l   @r0, r3         ! TTE data high (PTEU image: PA[39:32] in [7:0])
        ldc     r3, pteu
        ldtlb.rn                ! {PTEU,PTEL,PTEH,ASIDR} -> TLB entry, return
         nop
```

Two extra instructions (≈ +2 on the hot path). No extra TSB traffic: the 16-byte TSB entry's `Data` field is already 64 bits ([design-spec.md §4.3](design-spec.md)), so the high word is in the same cache line that was already loaded.

## 8. SMP Considerations

### 8.1 Per-CPU state

Each CPU has its own:
- TLB (entries, lookup logic)
- PTEH, PTEL, TSBBR, TSBCFG, TSBPTR, MMUCR, TEA registers
- CPUINFO register (read-only, returns this CPU's hart ID)
- Exception state (SPC, SSR, register banks)

### 8.2 SMP release register

A platform-level (SoC) MMIO register, not part of the CPU core, allows the primary CPU to release secondaries from reset.

**Suggested address:** `0xFF00FF00` (in the SoC's MMIO range, outside the CPU MMU register block).

**Suggested layout:**
```
[31:N]   reserved
[N-1:0]  CPU_RELEASE   Write 1 to bit n to release CPU n.
                       Reads return current release-bit state.
```

This is a SoC-level addition, not a CPU-core addition. The exact mechanism depends on the platform-integration choices.

### 8.3 Wake interrupt routing

For systems that support S2RAM-style suspend, wake interrupts (RTC, external pin) should route to CPU 0 by default. CPU 0 then brings up other CPUs via the standard hotplug path. No new hardware in the CPU core is needed for this.

## 9. Reset State

On hardware reset:

| Register | Reset value |
|----------|-------------|
| MMUCR | 0 (AT=0, MMU disabled) |
| PTEH | 0 |
| PTEL | 0 |
| TSBBR | 0 |
| TSBCFG | 0 |
| TSBPTR | 0 |
| TEA | 0 |
| TTB | 0 |
| TLB | all entries VALID=0 |
| SR | implementation-defined, MD=1 |

The CPU starts executing at the reset vector (typically `0xA0000000` = P2 entry, uncached) with MMU disabled. Bootrom code initializes the system and either jumps to or loads a kernel that runs in P1.

## 10. Future-Compatibility Notes

### 10.1 Hypervisor extension

The hypervisor extension (Phase 3, see [hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md)) **does not add new MMU hardware fields**. Guest isolation is achieved via ASID partitioning in software; the hypervisor allocates ranges of the 12-bit ASID space to guests and tracks ownership outside the TLB. No VMID field, no HVMID register, no HGATP register, no second-stage hardware walker. See [glossary §5](../glossary.md) ("VMID — removed") and [hypervisor/design-spec.md §3.7](../hypervisor/design-spec.md) for the rationale.

Earlier drafts of this spec reserved an 8-bit VMID field in TLB tags. That reservation is **removed** as of this revision (see §4.2). The 8 bits are not used by anything now and are not earmarked for any future use.

### 10.2 Wider physical address

PA width is implementation-defined. J32 typically uses 32-bit PA (up to 4 GB); J64 may use 40-bit, 44-bit, or 48-bit PA. The PPN field in PTEL and TLB entries scales accordingly.

## 11. Verification Points

Critical points to verify in RTL:

1. **TLB miss → TSBPTR computation:** hash, mask, and base concatenation produce a correctly aligned 16-byte address.
2. **TLB match function:** exact-match-with-mask works for all PageMask values; ASID_TAG comparison correctly suppressed when GLOBAL=1.
3. **LDTLB.RN atomicity:** No observable interrupt window between TLB write and PC/SR restore.
4. **MMUCR.TI:** Single-cycle invalidation of all entries; self-clearing.
5. **Register banking on TLB miss:** Bank 1 R0–R7 visible to handler, bank 0 preserved.
6. **ASIDR preservation across miss:** ASIDR is not touched by miss-vector entry; hardware writes only PTEH.VPN. Handler can read ASIDR directly and trust it reflects the current context.
7. **STALE bit preservation:** LDTLB carries the STALE bit from PTEL into the TLB entry intact.
8. **Per-CPU CPUINFO routing:** Each CPU reads a distinct HART_ID at `0xFF000030`.
9. **Exception priority:** TLB miss vs. instruction-fetch fault vs. higher-priority interrupts handled correctly.
10. **Reset state:** All MMU registers cleared, TLB invalidated, MMU disabled.
11. **Multi-word-unit instruction-fetch miss (only if the SIMD or density extension is present, §5.2):** an instruction-fetch miss on the *interior* word of a multi-word unit must save the unit's **first-word PC** into SPC, and `RTE` must re-execute the whole unit. Verify both instances: (a) a SIMD block straddling a 16 KB boundary whose tail page misses → SPC = prefix PC, block re-opens with correct lane-wise semantics (test the prefix-time-validation probe path *and* a non-crossing block that takes no probe/stall); (b) a two-word `movi20`/`lea`/disp12 whose word1 lands on a missing page → SPC = word0 PC, instruction re-executes (not a resume into word1).

## 12. Estimated Hardware Cost

Beyond inheriting the SH-4 MMU structure:

| Addition | Estimated cost |
|----------|----------------|
| TSBBR, TSBCFG registers | ~96 bits flop (J32), 160 bits (J64) |
| TSBPTR register | ~32 bits (J32), 64 bits (J64) |
| TSBPTR computation (hash, XOR, mask, OR) | ~50 LUTs |
| `ASID` fold in the index (§2.8a) — two shifts and two XORs on an existing combinational path | a handful of LUTs; off the critical timing path (measured DMISS/IMISS warm cycles unchanged at 7/8) |
| TSBSLOT latch + its read-side `tsb_ptr()` evaluation (§2.12) | 32 bits flop; the index logic is shared, not duplicated |
| Victim LFSR + TSBVSEED/TSBVICT decode (§2.13) | 16 bits flop + ~10 LUTs |
| ASIDR register | 16 bits flop per CPU, ×`n_tc` on FGMT cores (§2.1a) |
| Extended ASID_TAG (8 → 16 bits) | 8 bits per TLB entry |
| PageMask (4 bits per TLB entry) | 4 bits per TLB entry |
| STALE bit per TLB entry | 1 bit per entry |
| LDTLB.RN decode | ~10 LUTs |
| ASIDR LDC/STC decode | ~5 LUTs |
| CPUINFO MMIO | ~32 bits flop per core + decoder |

For 32 TLB entries: ~600 bits of additional TLB state per CPU. Plus ~200 LUTs of new logic per CPU. Modest by FPGA standards.
