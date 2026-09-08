# J-Core P4 MMIO Allocation Map

**Status:** Canonical allocation table. Update **before** any new spec claims a P4 address.

**Scope:** Master allocation of the SH-4 P4 segment (`0xE0000000`–`0xFFFFFFFF`, 512 MB) across all J-Core control registers, on-chip peripherals, and SoC blocks.

**Authority:** This document is the single source of truth for P4 address allocation. If another spec disagrees with this map, this map wins and the other spec is wrong. Every spec that places a control register in P4 MUST cite this document and use an address allocated here.

That authority covers **allocation** — who owns an address — not **implementation**: it does not
make an address decoded merely because this map lists it. Where the RTL is the question ("does this
register answer at this address today?"), `jcore-cpu` is the ground truth and this map records what
it found; see §3.2's notes on undecoded offsets and on CPUINFO.

**Audience:** Anyone authoring a J-Core hardware spec, RTL implementer, kernel-driver author, IOMMU/hypervisor reviewer.

---

## 1. Background

The SH-4 architecture defines P4 (`0xE0000000`–`0xFFFFFFFF`) as the privileged-only MMIO segment. Accesses are untranslated (no MMU lookup), uncached, and accessible only with `SR.MD = 1`. The convention is well-known pre-2006 — see the SH-4 hardware manual (Renesas/Hitachi, 1998).

Earlier J-Core specs allocated P4 addresses ad-hoc; this document consolidates them and reserves space for future blocks. The reservation policy is conservative: blocks get larger ranges than they currently need so they can grow without re-allocation.

**Cross-links to this map:**
- [glossary §5 — P4](../glossary.md)
- [mmu/hardware-spec.md §2](../mmu/hardware-spec.md) — MMU control registers
- [iommu/hardware-spec.md §3](../iommu/hardware-spec.md) — IOMMU register map
- [aic/aic2-spec.md §3.5](../aic/aic2-spec.md) — AIC2 base address
- [cache/l2-spec.md §13.5](../cache/l2-spec.md) — L2 CSR base address
- [bus/fabric-spec.md §3](../bus/fabric-spec.md) — slave-port allocation table

---

## 2. Top-level P4 partition

The 512 MB P4 segment is partitioned into four quarter-gigabyte regions. Sub-allocation within each is shown in §3 onward.

| Range                       | Size   | Purpose                                                    | Status     |
|-----------------------------|--------|------------------------------------------------------------|------------|
| `0xE0000000`–`0xEFFFFFFF`   | 256 MB | SH-4 store-queue (SQ) region, see [../sq/spec.md](../sq/spec.md); only `0xE0000000`–`0xE3FFFFFF` is SQ-decoded, the remainder is reserved | allocated  |
| `0xF0000000`–`0xF7FFFFFF`   | 128 MB | Cache management — L1 array access, L2 array access        | reserved   |
| `0xF8000000`–`0xFEFFFFFF`   | 112 MB | Future expansion                                           | reserved   |
| `0xFF000000`–`0xFFFFFFFF`   | 16 MB  | **Core MMIO** — all current allocations live here          | allocated  |

**Why the 16 MB live region.** All shipping J-Core control registers fit in the top 16 MB. The other three quarters of P4 are deliberately empty — they preserve room for: (1) the SH-4 store-queue (SQ) facility, see [../sq/spec.md](../sq/spec.md); (2) direct L1/L2 array access for debug/diagnostics, and (3) a generous reserve for blocks we haven't designed yet.

---

## 3. The `0xFF000000`–`0xFFFFFFFF` live region

The live 16 MB region is partitioned into per-block ranges. **Per-CPU blocks** appear at the same address on every core; the bus fabric routes the access to the requesting core's local instance based on the master's `BMID` (per [bus/fabric-spec.md §4](../bus/fabric-spec.md)).

| Range                       | Size   | Block                              | Per-CPU? | Spec |
|-----------------------------|-------:|------------------------------------|:--------:|------|
| `0xFF000000`–`0xFF000FFF`   |  4 KB  | MMU control + event regs + CPUINFO | yes      | [mmu/hardware-spec.md §2](../mmu/hardware-spec.md) |
| `0xFF001000`–`0xFF001FFF`   |  4 KB  | PMU (Performance Monitoring Unit)  | yes      | [ooo/j32ooo-spec.md §12](../ooo/j32ooo-spec.md) |
| `0xFF002000`–`0xFF002FFF`   |  4 KB  | Hypervisor control registers       | yes      | [hypervisor/hardware-spec.md §2.2](../hypervisor/hardware-spec.md) |
| `0xFF003000`–`0xFF00EFFF`   | 48 KB  | reserved (future per-CPU blocks)   | —        | —    |
| `0xFF00F000`–`0xFF00FFFF`   |  4 KB  | SoC-wide control (SMP release)     | no       | [mmu/hardware-spec.md §8.2](../mmu/hardware-spec.md) |
| `0xFF010000`–`0xFF010FFF`   |  4 KB  | IOMMU                              | no       | [iommu/hardware-spec.md §3](../iommu/hardware-spec.md) |
| `0xFF011000`–`0xFF01FFFF`   | 60 KB  | reserved (IOMMU expansion)         | —        | —    |
| `0xFF020000`–`0xFF02FFFF`   | 64 KB  | AIC2 interrupt controller          | yes¹     | [aic/aic2-spec.md §3.5](../aic/aic2-spec.md) |
| `0xFF030000`–`0xFF03FFFF`   | 64 KB  | reserved (AIC2 expansion / IPI)    | —        | —    |
| `0xFF040000`–`0xFF04FFFF`   | 64 KB  | L2 cache CSRs                      | no       | [cache/l2-spec.md §13.5](../cache/l2-spec.md) |
| `0xFF050000`–`0xFF0FFFFF`   | 768 KB | reserved (future cache/coherence)  | —        | —    |
| `0xFF100000`–`0xFF7FFFFF`   |  7 MB  | Peripheral register banks          | no       | [§4 below](#4-peripheral-allocation) |
| `0xFF800000`–`0xFFFEFFFF`   | ~8 MB  | reserved (future peripherals)      | —        | —    |
| `0xFFFF0000`–`0xFFFFFFFF`   | 64 KB  | reserved (top of P4)               | —        | —    |

¹ AIC2 is logically per-CPU; the 64 KB range encodes per-CPU sub-banks (see [aic/aic2-spec.md §3.5](../aic/aic2-spec.md)).

### 3.1 Per-CPU block routing

Per-CPU ranges (MMU, PMU, Hypervisor, AIC2) are decoded by the bus fabric as follows: the requesting CPU's BMID (see [bus/fabric-spec.md §4](../bus/fabric-spec.md)) selects which physical instance of the block receives the access. From software's perspective every core reads/writes the same P4 address; from hardware's perspective each core has its own instance behind the decoder.

The cross-CPU access pattern (CPU 0 reading CPU 1's PMU) is **not supported** through these per-CPU addresses; it requires either:
- IPI to the target CPU which then reads its own register and replies via shared memory, or
- a future cross-CPU debug-access path (not specified in this revision; reserved in `0xFF003000`–`0xFF00EFFF`).

### 3.2 MMU sub-allocation (`0xFF000000`–`0xFF000FFF`)

The MMU block at `0xFF000000` carries the registers specified in [mmu/hardware-spec.md §2](../mmu/hardware-spec.md). Current allocations (4-byte aligned):

| Offset      | Register   | Description                          |
|-------------|------------|--------------------------------------|
| `0x000`     | PTEH       | Page-table-entry high, **read-only alias, decoded in RTL** (`core/datapath.vhm`, `P4_PTEH`). Stock SH-4 offset. This is now the *only* way to read `PTEH`: `STC PTEH,Rn` was retired in Phase 3 ([mmu/hardware-spec.md §3.1](../mmu/hardware-spec.md)). Writes are **not** decoded — `LDC Rm,PTEH` remains the sole write path (design D7). |
| `0x004`     | PTEL       | Page-table-entry low, **read-only alias, decoded in RTL** (`P4_PTEL`). Stock SH-4 offset. Replaces the retired `STC PTEL,Rn`; write path stays `LDC Rm,PTEL` (D7). |
| `0x008`     | TTB        | Translation table base (software)     |
| `0x00C`     | TEA        | TLB exception address                 |
| `0x010`     | MMUCR      | MMU control                           |
| `0x014`     | TSBBR      | TSB base register                     |
| `0x018`     | TSBCFG     | TSB configuration                     |
| `0x01C`     | TSBPTR     | TSB pointer, read-only; **decoded in RTL** (`P4_TSBPTR`). **Squat** per §5 rule 8: stock SH-4 puts `CCR` here (`0xFF00001C`, Linux `arch/sh/include/cpu-sh4/cpu/cache.h`). No guest consequence — [sh4-guest-model.md §3.2](../sh4-guest-model.md) |
| `0x020`     | TRA        | TRAPA immediate — stock SH-4 placement; **decoded in RTL** (also `STC TRA,Rn`) |
| `0x024`     | EXPEVT     | Exception event code — stock SH-4 placement; **decoded in RTL**, read-only (also `STC EXPEVT,Rn`) |
| `0x028`     | INTEVT     | Interrupt event code — stock SH-4 placement; **decoded in RTL**, read-only (also `STC INTEVT,Rn`) |
| `0x02C`     | MMUFSR     | Fault-status snapshot, read-only; **decoded in RTL** (see [mmu/hardware-spec.md §2.11](../mmu/hardware-spec.md)) |
| `0x030`     | CPUINFO    | Per-CPU hart ID + capability flags — **allocated, NOT implemented in current RTL** (see note below) |
| `0x034`     | reserved   | proposed `PTEU` (PAE only, [mmu/hardware-spec.md §2.10](../mmu/hardware-spec.md)) |
| `0x038`     | ASIDR      | Address-space identifier, **read-only alias, decoded in RTL** (`P4_ASIDR`). **Squat** per §5 rule 8: stock SH-4 puts `QACR0` here. This row previously said `0x038` was chosen because *no stock SH-4 offset exists* — true of ASIDR, false of the offset, which SH-4 uses. (`0x034` stays reserved for the proposed `PTEU`; SH-4 uses that one too, for `PTEA`.) Replaces the retired `STC ASIDR,Rn`; write path stays `LDC Rm,ASIDR` (D7). Linux's `get_asid()` reads this. |
| `0x03C`     | QACR0      | Store-queue 0 area register (`0xFF00003C`) — **allocated, NOT implemented in current RTL** (see the silent-failure note below), see [../sq/spec.md §3](../sq/spec.md). **Squat** per §5 rule 8: this offset is stock SH-4's `QACR1`, so J-Core's `QACR0` and SH-4's `QACR0` are *different addresses with the same name* — the most confusable arrangement in this table. The emulated surface a guest sees uses the stock pair: [sh4-guest-model.md §3.2](../sh4-guest-model.md) |
| `0x040`     | QACR1      | Store-queue 1 area register (`0xFF000040`) — **allocated, NOT implemented in current RTL**, see [../sq/spec.md §3](../sq/spec.md). Stock SH-4 leaves `0x040` free, so this one is a J-Core addition rather than a squat — but it is the *pair* of a squat and moves with it if `0x03C` is ever restored to the stock layout |
| `0x044`     | reserved   | no allocation; falls in the silent-zero class below. Previously absent from this table altogether — neither allocated nor reserved, in a table headed "current allocations" |
| `0x048`     | TSBSLOT    | TSB slot-address helper — **decoded in RTL** (`core/datapath.vhm`, `P4_TSBSLOT`, read/write alongside TSBBR/TSBCFG/TSBPTR). Write a VA, read the same address back to get `tsb_ptr(VA)` — the exact slot address the hardware TSB walker (`core/tlb_walk.vhd`) and TSBPTR-on-fault use. Only the VA is latched; the index function is evaluated on the read, so `core/datapath_pkg.vhd`'s `tsb_ptr()` remains the single implementation. Added in Phase-2 Task 2 so Linux's `jcore_tsb_slot_offset()` bit-for-bit C mirror could be deleted; kernel side is `JCORE_TSB_SLOT` (`0xFF000048`) in `arch/sh/include/cpu-jcore/cpu/mmu_context.h`. |
| `0x04C`     | TSBVSEED   | TSB victim-selector seed — **decoded in RTL** (`core/datapath.vhm`, `P4_TSBVSEED`). **WRITE-ONLY**: there is no read case, so a read returns the decoder's hard zero *deliberately*, not by omission. Seeds the LFSR that nominates which way of a 2-way TSB set to replace when neither tag matches. The seed comes from the OS at MMU init precisely because it must not be public — this is an open-source core, so the polynomial and any constant seed compiled into the RTL are readable by anyone. If software could read the seed back, so could an attacker. Kernel side is `JCORE_TSB_VSEED`. See [mmu/hardware-spec.md §2.13](../mmu/hardware-spec.md). |
| `0x050`     | TSBVICT    | TSB victim nomination — **decoded in RTL** (`core/datapath.vhm`, `P4_TSBVICT`). **READ-ONLY**, and only bit 0 is meaningful: the way to replace. **The read advances the LFSR**, so each read consumes one bit and no two reads observe the same state; neither the seed nor the LFSR state is ever readable. Kernel side is `JCORE_TSB_VICTIM`. |
| `0x054`     | TSBCNT     | Walker counters, **read-only, decoded in RTL** (`core/datapath.vhm`, `P4_TSBCNT`): `[31:16]` = `cnt_walks`, `[15:0]` = `cnt_hits`, exported by `core/tlb_walk.vhd`. **Not scaffolding** — the pair is the TSB hit-rate signal used for TSB sizing and hash tuning, and nine anti-vacuity guards assert on it. They were moved here from the P2 debug window `0xABCD0F00` (**retired**) precisely because guest P4 is trapped wholesale, so a hypervisor can virtualize or deny them; a guest reading `cnt_hits` otherwise observes TSB behaviour caused by *other* guests. See [../hypervisor/design-spec.md](../hypervisor/design-spec.md) and [mmu/hardware-spec.md §5.0](../mmu/hardware-spec.md). |
| `0x058`     | TLBINST    | TLB slot-write counters, **read-only, decoded in RTL** (`core/datapath.vhm`, `P4_TLBINST`): `[31:16]` = ITLB slot writes, `[15:0]` = DTLB slot writes. Anti-vacuity instrumentation for the I→D shadow fill; **not architectural**, and a hypervisor may virtualize or deny it for the same guest-observability reason as `TSBCNT` above. This row was added by the B0c doc-vs-code check, which found the register decoded in RTL while this table still called `0x058` reserved. |
| `0x05C`–`0xFFC` | reserved | future registers                                  |

**`CCR` is deliberately absent from this table, and that is now a decision.** Stock SH-4's cache control register is at `0xFF00001C`, which J-Core decodes as `TSBPTR`. J-Core allocates no `CCR` anywhere and `jcore-cpu` implements none. It does not need one: a guest's `CCR` is emulated by the VMM with no host register behind it ([sh4-guest-model.md §3.2](../sh4-guest-model.md)), and the J-Core kernel configures its caches through the cache subsystem's own interface, not through an SH-4-shaped register. Adding a `CCR` here would require an offset, and every offset that could plausibly carry it is taken.

**Decision: `0x020`/`0x024`/`0x028` are TRA / EXPEVT / INTEVT.** This closes the three-way
conflict formerly recorded as §7 open question 4. CPUINFO moves from `0x020` to `0x030`, and
MMUFSR takes `0x02C` — it had been specified at `0x028`, i.e. on top of INTEVT.

**Rationale:** these three offsets are the stock SH-4 architectural placement of TRA, EXPEVT and
INTEVT (SH-4 hardware manual, Renesas/Hitachi, 1998 — pre-2006). Matching the architecture *is* the
rationale: it is what an SH-4-aware kernel, debugger and simulator already assume, and it is what
Linux `arch/sh/include/cpu-jcore/cpu/mmu_context.h` already defines (`TRA 0xff000020`,
`EXPEVT 0xff000024`, `INTEVT 0xff000028`). Nothing is displaced by adopting it: the RTL
(`jcore-cpu/core/datapath.vhm`) decoded none of `0x020`/`0x024`/`0x028` when this was decided, so
there was no implemented register to move — and it decodes all three at those addresses now; `0x024` was freed when ASIDR was removed from MMIO (below); and
CPUINFO at `0x020` was a paper allocation only — there are zero occurrences of `cpuinfo` in any
`jcore-cpu` or `jcore-soc` source. Moving a never-implemented allocation costs nothing, while
diverging from SH-4 would cost every future port.

**This supersedes [../priv-arch/design-spec.md §4.6](../priv-arch/design-spec.md)'s proposal** to
relocate EXPEVT/INTEVT/TRA to `0x028`/`0x02C`/`0x030`. That proposal existed solely to dodge
CPUINFO at `0x020` and ASIDR at `0x024`. ASIDR has since been removed from MMIO entirely (it is
LDC/STC-only), and CPUINFO has moved here, so the reason for the relocation has dissolved. The
relocated addresses are **not** allocated to those registers; `0x02C` is MMUFSR and `0x030` is
CPUINFO. Do not use them for the cause registers.

**CPUINFO overlaps `jcore,cpuid-mmio` — a future implementer must pick one.** CPUINFO's `HART_ID`
field ([mmu/hardware-spec.md §2.9](../mmu/hardware-spec.md)) duplicates a facility jcore-soc already
implements: the `cpumreg` block (`jcore-soc/targets/cpumreg.vhm`, decoded at
`jcore-soc/targets/cpu_core_pkg.vhd:132-137`) exposes per-core identity at `0xABCD0600`, emitted
into every board device tree as `jcore,cpuid-mmio` by
`jcore-soc/tools/socgen/devicetree/tree.go:409-411` and reserved in
`jcore-soc/tools/socgen/elaborate/addr_validate.go:66`. SMP boot depends on it today:
`jcore-soc/boot/main.c:414-432` reads bit 0 of `0xABCD0600` to learn which core it is. Whoever
implements CPUINFO should decide whether to fold `cpuid-mmio` into it or drop CPUINFO's HART_ID
field and keep `cpuid-mmio`; building both would give a core two disagreeing answers to "who am I?".
This map does not make that choice — it flags it.

**PTEH, PTEL and ASIDR are read-only at P4, write-only via `LDC`.** *(Implementation status:
aliases decoded, Phase 3.)* Earlier revisions of this map listed PTEH at `0x000`, PTEL at `0x004`
and ASIDR at `0x024`, as full registers; that was wrong, and the correction over-swung into
"no P4 address at all", which is now also wrong. The settled shape: **read** through the P4
aliases `0x000` / `0x004` / `0x038` (the matching `STC` forms are retired), **write** only with
`LDC Rm, PTEH` / `LDC Rm, PTEL` / `LDC Rm, ASIDR` — the decoder has no write case for these
offsets. See
[../mmu/hardware-spec.md §2.1](../mmu/hardware-spec.md) (PTEH), §2.1a (ASIDR) and §2.2 (PTEL).
PTEU ([mmu/hardware-spec.md §2.10](../mmu/hardware-spec.md), PAE-only) is likewise LDC/STC-only.

The RTL is the ground truth here: `jcore-cpu/core/datapath.vhm` (the `p4_sel_v` decode, inside the
`if PRIV_ARCH then` block) decodes `0x08` TTB, `0x0C` TEA, `0x10` MMUCR, `0x14` TSBBR, `0x18` TSBCFG,
`0x1C` TSBPTR (read-only), `0x20` TRA, `0x24` EXPEVT, `0x28` INTEVT, `0x2C` MMUFSR, `0x048`
TSBSLOT, `0x04C` TSBVSEED (write-only), `0x050` TSBVICT (read-only), `0x054` TSBCNT (read-only)
and the read-only `0x00` PTEH / `0x04` PTEL / `0x38` ASIDR aliases. Those three have **read**
cases only; their write path is `LDC`, elsewhere in the same file. Read that list as "what the RTL decoded when this line was written" —
it grows; grep `p4_sel_v` rather than trusting it.

> **Do not read this paragraph as a count.** It said "exactly six offsets" with pinned line numbers
> long after the RTL had grown past six, and that staleness directly caused a defect: an
> implementer concluded from it that P4 could not carry a new register, put a production helper at a
> P2 debug address, and Linux shipped a `#define` pointing there (fixed 2026-08-11). **P4 works for
> reads and writes; new MMU registers are decoded here, in `datapath.vhm`, alongside `TSBPTR`.** The
> only true limitation is that P4 accesses never reach `cpu.vhd`'s *return path*, because
> `datapath.vhm` consumes them first — which is why genuinely debug-only windows once sat at P2
> `0xABCD0F00` instead — though the walker counters, the last such window, moved *into* P4 at
> `0x054` because their guest-observability makes hypervisor trapping the point. Line numbers here are indicative; grep for `p4_sel_v`.
Linux agrees independently: `arch/sh/include/cpu-jcore/cpu/mmu_context.h` defines MMIO addresses for
the decoded registers only (not a fixed number of them) and documents the register set (`PTEU` is still LDC-only; `PTEH`/`PTEL`/`ASIDR` now have read-only
aliases); `arch/sh/mm/tlb-jcore.c` uses `ldc %0, pteh`.

**Undecoded P4 offsets fail SILENTLY (normative hazard).** A load or store to a P4 offset in this
block that the hardware does not decode raises **no exception and no bus error**. Writes fall into
the decoder's `when others => null` arm and are discarded; reads fall into
`when others => this.m_dr_next := (others => '0')` and return **zero**, with
`m_en` still asserted so the access completes normally from the pipeline's point of view.
*(Line numbers were pinned here and had drifted; grep the arms instead.)* Software
that uses a phantom P4 address therefore observes a register that is permanently zero and never
faults — a failure mode that is easy to mistake for "the feature is disabled". Any address in this
sub-block marked *reserved*, or marked *allocated but not implemented*, behaves this way today —
`0x030` CPUINFO, `0x034`, `0x03C` QACR0, `0x040` QACR1, `0x044`, and `0x05C`–`0xFFC`.
TRA/EXPEVT/INTEVT and MMUFSR are **not** in that category: the RTL decodes all four
(`datapath.vhm`, `P4_TRA`/`P4_EXPEVT`/`P4_INTEVT`/`P4_MMUFSR`), so a kernel reading them through
MMIO reads the real register. There are zero occurrences of `cpuinfo` in any `.vhd`/`.vhm` source;
its allocation is a valid reservation, but reading it returns zero rather than a hart ID.

*(This paragraph previously ended with a sentence that contradicted itself mid-way — "until
`datapath.vhm` decodes them a kernel reading them through MMIO now reads the real register" — a
leftover from before the decode landed, sitting two sentences after the line that says it did. It
also listed only CPUINFO as marked not-implemented while QACR0 and QACR1 carried no such marker,
which `scripts/check-doc-facts.py`'s own `check_p4_offsets` docstring asserted they did.)*

### 3.2a How wide the CPU's P4 decode actually is — a normative hazard, and a live defect

**This map allocates P4 by 4 KB / 64 KB block. `datapath.vhm` does not decode
it that way, and on a `PRIV_ARCH` build it does not leave any of P4 to the
fabric at all.** Found while reconciling this map against the RTL for Wave-2
**B1**; recorded here because it is the map's problem to state and somebody
else's to fix.

Three facts, all read at `jcore-cpu@master`:

1. **The segment test is one byte wide.** `core/datapath_pkg.vhd`'s
   `seg_decode` returns `SEG_P4` for `va(31 downto 24) = x"FF"` — the whole
   16 MB from `0xFF000000` to `0xFFFFFFFF`, not the 4 KB this map's §3.2
   sub-allocates.
2. **Inside that, there is a 4 KB page selector**: `case ma_ad(23 downto 12)`.
   It has two arms today — `when x"001"` for the PMU page at `0xFF001xxx`, and
   `when others` for the MMU page.
3. **The MMU arm's register test is one byte wide.** Its `p4_sel_v` chain
   compares only `ma_ad(7 downto 0)`. The PMU arm, by contrast, compares all
   twelve bits, `ma_ad(11 downto 0)`.

**Aliasing — real, and known to the RTL.** Because the MMU arm is the `others`
arm and matches on the low byte alone, each of the **18** offsets it decodes
answers at *every* 256-byte stride across the P4 window, excepting the PMU's own
page. *(18 is the count of `ma_ad(7 downto 0) = x"NN" then p4_sel_v := P4_…`
arms, which is also what `p4-offsets-match-rtl` parses and what §3.2's table
lists. Do not derive it from `p4_sel_t` in `core/datapath_pkg.vhd`: that type has
**23** enumerators — these 18, plus four for the PMU page, plus the `p4_none`
sentinel — so counting the enum gives a different and wrong answer for this
sentence.)* `0xFF000010`, `0xFF000110`, `0xFF104010` and `0xFFFFFF10` all select
`P4_MMUCR`. The RTL says this is deliberate preservation, not oversight: the MMU
page is `others` rather than `when x"000"` *"ON PURPOSE… it keeps the
pre-existing behaviour that the MMU registers answer across the rest of the P4
window byte-for-byte. That aliasing is old, undocumented and out of scope to
change here."* It is documented here now, which is the half of this that was
missing.

**A block outside the MMU page needs its own page arm, and gets one.** In
`datapath.vhm` the external bus assignment `this.data_o := to_data_o(...)` sits
in the `else` arm of the privilege/serve gate, so on a `PRIV_ARCH` build every
supervisor access to `0xFF......` is consumed inside the datapath and **none of
it reaches the fabric**. A P4 block therefore cannot be implemented as a fabric
slave on such a build; it is implemented as a page arm in this `case`. The PMU is
exactly that, and the RTL states the rule for the next one: *"ADDING A THIRD
BLOCK: add a `when x"00N" =>` arm here. Do NOT append to the MMU chain in the
`others` arm."*

**What this means for §3's table.** Of the seven blocks §3 allocates in the
`0xFF` segment, one — the PMU at `0xFF001000` — has its page arm and works. The
others do not exist in `datapath.vhm`, so today they read as zero and discard
writes: the SoC-wide **SMP release** register at `0xFF00FF00`, the **hypervisor**
block at `0xFF002000`, the **IOMMU** at `0xFF010000`, **AIC2** at `0xFF020000`,
the **L2 CSRs** at `0xFF040000`, and every peripheral bank at `0xFF100000+`.
That is an unimplemented-block problem with a known implementation route, not the
architectural dead end it looks like from the segment test alone. On a
non-`PRIV_ARCH` (J2) build the gate does not exist and P4 reaches the bus
normally.

**Correcting this section's own first revision, since it is the kind of error it
exists to catch.** It was written on facts 1 and 3 without fact 2, and concluded
that "no P4 address outside `datapath.vhm`'s 18 is reachable at all", listing the
PMU among the casualties. The PMU is decoded, with a full 12-bit compare chosen
precisely so it does not alias. The remedy it proposed — an RTL "window check" —
is also wrong: the structure already exists and the correct move is a page arm.
What survives is the aliasing (fact 3, confirmed by the RTL's own comment) and
the observation that a `PRIV_ARCH` build routes no P4 to the fabric.

**What is still open.** Whether the six unimplemented blocks get page arms here
or move out of the `0xFF` segment, and whether the MMU page's byte-wide compare
should be narrowed at all — narrowing it touches the gate that stops a user-mode
store to `0xFF000014` repointing the TSB walker (`mmup4priv`), so it needs care
rather than a smaller mask. **Not B1's to decide**, and B1 does not decide it.

**What is enforced now.** `mmu.p4.segment`, `mmu.p4.page` and `mmu.p4.window`
in [fact-ownership.md](../fact-ownership.md) §Code bindings pin all three widths
— the `0xFF` segment test, the `ma_ad(23 downto 12)` page selector and the MMU
arm's 8-bit offset compare — against `datapath_pkg.vhd` and `datapath.vhm`. None
can move without this section going red. The page-selector binding is the one
this section's first revision most needed and did not have.

### 3.3 SoC-wide control (`0xFF00F000`–`0xFF00FFFF`)

Currently allocated:

| Address     | Register            | Notes                                                         |
|-------------|---------------------|---------------------------------------------------------------|
| `0xFF00FF00` | SMP release         | Write bit *n* to release CPU *n*. See [mmu/hardware-spec.md §8.2](../mmu/hardware-spec.md). |

The remainder of the 4 KB SoC-wide page is available for future system-level registers (clock control, reset cause, SoC capability registers, etc.).

---

## 4. Peripheral allocation

The 7 MB peripheral region (`0xFF100000`–`0xFF7FFFFF`) accommodates board-level peripherals. Each peripheral gets a 4 KB slot. The first 32 slots are reserved for the standard J-Core SoC peripheral set:

| Slot | Range                       | Peripheral                          | Status     |
|-----:|-----------------------------|-------------------------------------|------------|
|   0  | `0xFF100000`–`0xFF100FFF`   | SDRAM controller config             | existing   |
|   1  | `0xFF101000`–`0xFF101FFF`   | Ethernet MAC (LiteEth on ULX3S)     | existing   |
|   2  | `0xFF102000`–`0xFF102FFF`   | SD / eMMC                           | existing   |
|   3  | `0xFF103000`–`0xFF103FFF`   | USB                                 | future     |
|   4  | `0xFF104000`–`0xFF104FFF`   | UART 0 (primary console)            | existing   |
|   5  | `0xFF105000`–`0xFF105FFF`   | UART 1                              | reserved   |
|   6  | `0xFF106000`–`0xFF106FFF`   | GPIO                                | existing   |
|   7  | `0xFF107000`–`0xFF107FFF`   | SPI / QSPI flash controller         | existing   |
|   8  | `0xFF108000`–`0xFF108FFF`   | I²C                                 | reserved   |
|   9  | `0xFF109000`–`0xFF109FFF`   | Timer / counter block               | existing   |
|  10  | `0xFF10A000`–`0xFF10AFFF`   | Watchdog                            | reserved   |
|  11  | `0xFF10B000`–`0xFF10BFFF`   | RTC                                 | reserved   |
|  12–31 | `0xFF10C000`–`0xFF11FFFF` | reserved (future standard peripherals) | —     |

Slots 32 and above (`0xFF120000`–`0xFF7FFFFF`) are available for board-specific peripherals. The bus fabric's slave-port allocator (see [bus/fabric-spec.md §3](../bus/fabric-spec.md)) governs which peripherals are wired on each SoC variant.

**Exact addresses for existing peripherals.** The pre-existing J-Core SoC uses ad-hoc P4 addresses for SDRAM/UART/etc. that predate this map. **As of this map's introduction, those peripherals MUST be relocated to the slots above on any new RTL release.** The Linux device-tree binding handles the indirection; no code changes outside the DTS are required. Existing pre-this-map bitstreams continue to work with their original DTS until they are rebuilt.

---

## 5. Allocation policy

Rules for adding new P4 allocations:

1. **Update this document first.** No spec may claim a P4 address that does not appear here.
2. **Choose the right region.** Per-CPU blocks go in `0xFF000000`–`0xFF00EFFF`; SoC-wide control blocks go after `0xFF00F000`; peripherals go in `0xFF100000+`.
3. **Reserve generously.** Allocate at least 4 KB even if you only need 256 bytes; allocate 64 KB for blocks expected to grow (cache subsystems, multi-instance controllers).
4. **`0xE0000000`–`0xEFFFFFFF` (SQ region)** is allocated to the Store Queue and owned by [../sq/spec.md](../sq/spec.md). The subdivision of this range is determined by the SQ spec: `0xE0000000`–`0xE3FFFFFF` is SQ-decoded, `0xE4000000`–`0xEFFFFFFF` is reserved and decoded by nothing. Only the SQ-decoded sub-range is exempt from the guest-mode P4 trap ([../hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md)); a spec that wants to place anything in the reserved remainder must amend both documents. **`0xF0000000`–`0xFEFFFFFF`** remains reserved without explicit project review. The reservation policy keeps those regions empty for future major subsystems.
5. **Document the per-CPU vs SoC-wide property** explicitly in the table above.
6. **Cite the canonical spec** for the block in the table's "Spec" column.
7. **Update both this map and the [bus/fabric-spec.md §3](../bus/fabric-spec.md) slave-port table** in the same change; they must agree.
8. **State the SH-4 relationship in the row, in one of three words.** Every
   allocation in `0xFF000000`–`0xFF000FFF` is one of:
   - **alias** — the register exists on SH-4 and J-Core places it at the *stock
     SH-4 offset*, so SH-4-aware kernels, debuggers and simulators keep working.
     `PTEH 0x000`, `PTEL 0x004`, `TTB 0x008`, `TEA 0x00C`, `MMUCR 0x010`,
     `TRA 0x020`, `EXPEVT 0x024`, `INTEVT 0x028`. The RTL says why in as many
     words: *"the MMIO aliases exist so generic (non-J-core) SH-4 kernel code
     that pokes 0xFF0000{20,24,28} keeps working"* (`datapath.vhm`).
   - **J-Core addition** — SH-4 has no such register, and the offset J-Core
     picked is one SH-4 leaves free. `TSBBR`/`TSBCFG` `0x014`–`0x018`,
     `TSBSLOT`/`TSBVSEED`/`TSBVICT`/`TSBCNT`/`TLBINST` `0x048`–`0x058`,
     `CPUINFO 0x030`.
   - **deliberate divergence** — the register is J-Core-only *and* the obvious
     offset is occupied by an SH-4 register, so the row names the collision it
     dodged. Exactly one today: `MMUFSR` at `0x02C`, moved off `0x028` because
     that is SH-4's `INTEVT`, onto an offset *"which SH-4 and SH-4A both leave
     free"* (`datapath.vhm`).
   - **squat** — a J-Core register at an offset stock SH-4 uses for something
     else. This is the case an SH-4-aware kernel cannot detect, and it is
     licensed only by the guest model (below). Three today, each named with the
     SH-4 register it sits on:
     `TSBPTR 0x01C` on SH-4's `CCR` and `ASIDR 0x038` on SH-4's `QACR0`, both
     **decoded in RTL**; and J-Core's own `QACR0 0x03C` on SH-4's `QACR1`,
     which is an **allocation only — the RTL decodes nothing at `0x3C`**.
     Case-insensitively, `qacr` occurs in `jcore-cpu` `origin/master` outside
     documentation as **one source comment in two committed files** —
     `core/datapath.vhm` and the `core/datapath.vhd` generated from it and
     committed alongside (`CLAUDE.md`, *Tracked generated files*). The decode
     arms carry `x"38"` and `x"1C"` and no `x"3C"`. *(The count in this sentence
     has now been wrong twice: first "all decoded", then "exactly once". It is
     stated as source-comment-and-generated-copy rather than as a number so
     there is nothing left to miscount.)*

     *(This bullet said "Three today, **all decoded in RTL**" when it was first
     written on 2026-09-07. That was false, and falsifiable from two rows of
     §3.2 in this same file — `0x03C` is marked "allocated, NOT implemented" —
     which is what makes it worth recording rather than quietly fixing: the
     sentence that replaced a false rule-8 claim was itself false, in the same
     way, one paragraph later. A squat is a **map-level** property; whether the
     RTL decodes it is a second question and the two were run together.)*

   **The `squat` case was previously written as "a fourth case is deliberately
   absent … no allocation here does that", and that was false when written.**
   The three squats above were all in `datapath.vhm` at the time. The stock
   SH-4 offsets that contradict it are not a matter of recollection: Linux
   defines `CCR` at `0xFF00001C`
   (`arch/sh/include/cpu-sh4/cpu/cache.h`) and `QACR0`/`QACR1` at
   `P4SEG_REG_BASE + 0x38` / `+ 0x3c`
   (`arch/sh/include/cpu-sh4/cpu/sq.h`), against a `P4SEG_REG_BASE` of
   `0xff000000`. Two rows in §3.2 asserted the opposite of this in their own
   text — `ASIDR`'s said it was placed at `0x038` because no stock SH-4 offset
   exists, and the RTL's own comment describing `0x3C`/`0x40` as
   "`QACR0`/`QACR1`" says nothing about the stock pair being elsewhere. Both are
   corrected in §3.2.

   `0x014` and `0x018` are **not** classified above by evidence: SH-4 places its
   UBC break-ASID registers in that area and this workspace has no in-tree
   artifact stating their offsets, so `TSBBR`/`TSBCFG` are listed as J-Core
   additions on the strength of the SH-4 hardware manual alone. Confirming or
   reclassifying them belongs with whoever next revises this rule; it changes
   nothing operationally, because the guest reasoning below holds for a squat
   and a J-Core addition alike.

   **This rule covers placement, not behaviour, and the behaviour is now
   settled.** Whether an SH-4 *guest* sees the SH-4 semantics of a register it
   pokes is decided by
   [sh4-guest-model.md](../sh4-guest-model.md) (Wave-2 **B2**):

   - **A squat costs a guest nothing.** Guest P4 traps wholesale
     ([../hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md)),
     so a guest's P4 access never reaches this decoder. The VMM presents the
     stock SH-4 map — `CCR` at `0xFF00001C`, `QACR0` at `0xFF000038`, `QACR1`
     at `0xFF00003C` — while the hardware keeps the offsets in §3.2. See
     [sh4-guest-model.md §3.2](../sh4-guest-model.md).
   - **A squat costs a bare-metal stock SH-4 kernel everything**, silently,
     because undecoded P4 reads return zero and writes are discarded (§3.2).
     That cost is accepted: a stock SH-4 kernel on bare-metal J-Core is not a
     target — [sh4-guest-model.md §2](../sh4-guest-model.md) — and the J-Core
     kernel uses `arch/sh/include/cpu-jcore/`, which carries these offsets.
   - **`QACR0`/`QACR1` behaviour** is therefore: emulated at the stock offsets
     for a guest; on the host, allocated here and unimplemented, and they stay
     unimplemented until the store queue exists at all
     ([../sq/spec.md](../sq/spec.md) is a paper spec — `jcore-cpu` has no store
     queue, no SQ region decode and no SH-4 `PREF`).
   - **`CCR` behaviour** is: emulated by the VMM with **no host register
     behind it**. This map is right not to allocate one, and this is now a
     decision rather than an omission. §7 item 3's `0xF0000000`–`0xF7FFFFFF`
     cache-array region is settled the same way: the guest P4 trap covers it,
     so no allocation is needed for the guest, and none is proposed for the
     host.

---

## 6. Prior art

The P4 segment itself is SH-4 architecture (Renesas/Hitachi hardware manual, 1998 — pre-2006).

Address-map partitioning conventions:
- Per-CPU MMIO base address with fabric-decoded routing — SH-4 INTC per-CPU layout (1998); UltraSPARC II per-CPU UDB registers (1997).
- Generous reservation policy with 4 KB-aligned slots — ARM AMBA "memory map by 4 KB pages" convention (AMBA AHB, 1999); PCI BAR alignment rules (PCI 2.0, 1993).
- SoC-wide control register page separate from per-CPU pages — PowerPC 7xx/74xx SoC layout (1997 onwards).
- Peripheral allocation table maintained as a single canonical document — PCI device ID registry pattern (PCI SIG, 1992).
- A **write-only** control register whose value cannot be read back, so that privileged software can install a value software must not be able to recover (`0x04C` TSBVSEED) — write-only control registers are standard pre-2006 practice; SH-4's own write-only cache/MMU control paths and the PCI 2.0 write-only configuration semantics are both examples.
- A **read-destructive** status register whose read advances internal state (`0x050` TSBVICT) — read-to-clear / read-to-advance registers are pervasive pre-2006, e.g. SH-4 interrupt-controller and UART status registers (1998) and the 16550 UART's read-clearing IIR/LSR (1987).

All references pre-2006, satisfying the project-wide prior-art policy ([glossary §2](../glossary.md)).

---

## 7. Open questions

1. **Pre-this-map peripheral addresses.** Several jcore-soc peripherals currently sit at ad-hoc P4 addresses outside this map. A coordinated re-allocation across the existing RTL and the Linux DTS is required to bring them into conformance. Owner: jcore-soc maintainer + Linux DTS maintainer.
2. **Cross-CPU debug access.** Reserved range `0xFF003000`–`0xFF00EFFF` is currently empty. If a cross-CPU register-poke debug facility is desired (e.g. for halt-mode debugging), specify the protocol and consume some of this range.
3. **L1 array access for diagnostics — the guest half is closed.** SH-4 used the `0xF0000000`–`0xF7FFFFFF` region for direct cache-array access. A *guest* never reaches it: guest P4 traps wholesale ([../hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md)) and the region is `not supported` on the guest surface ([sh4-guest-model.md §3.5](../sh4-guest-model.md)), so no allocation is owed to SH-4 compatibility. What remains open is only whether J-Core wants such a facility *for itself*; the region is reserved either way. Owner: RTL / SoC integration.
4. **Three-way conflict at `0x020`/`0x024`/`0x028` — RESOLVED.** *(This item said
   "CPUINFO moves to `0x02C`" until 2026-08-25. It was wrong and had been since
   §3.2 was written: `0x02C` is MMUFSR, as §3.2 states twice, and CPUINFO is at
   `0x030`. The error had already propagated to
   [../priv-arch/j4-implementation-design.md](../priv-arch/j4-implementation-design.md),
   which still carries `0xFF00002C` for CPUINFO — left for B1, which owns that
   file's P4 reconciliation. Note that this is a doc-vs-**doc** contradiction and
   B0c's `p4-offsets-match-rtl` did not find it; review did, while building the
   check. What the check does catch is the shape the CPUINFO defect originally
   had — a name in the map sitting on an offset the RTL decodes as something
   else.)* Three documents used to disagree
   about this half-dozen bytes: this map allocated `0x020` = CPUINFO and (formerly) `0x024` =
   ASIDR; Linux `arch/sh/include/cpu-jcore/cpu/mmu_context.h` assigned `0xff000020` = TRA,
   `0xff000024` = EXPEVT, `0xff000028` = INTEVT; and the RTL
   (`jcore-cpu/core/datapath.vhm:1136-1155`) decoded **none** of the three — only `0x08` TTB,
   `0x0C` TEA, `0x10` MMUCR, `0x14` TSBBR, `0x18` TSBCFG, `0x1C` TSBPTR.
   **Decision:** `0x020` = TRA, `0x024` = EXPEVT, `0x028` = INTEVT — the stock SH-4 architectural
   placement (SH-4 hardware manual, Renesas/Hitachi, 1998), which is also what Linux already
   defines. CPUINFO moves to `0x030` and remains allocated-but-not-implemented. This supersedes
   [../priv-arch/design-spec.md §4.6](../priv-arch/design-spec.md)'s `0x028`/`0x02C`/`0x030`
   relocation proposal, whose only motivation — dodging CPUINFO and ASIDR — has dissolved now that
   ASIDR is LDC/STC-only and CPUINFO has moved. Nothing had to be displaced: CPUINFO was a paper
   allocation with zero occurrences of `cpuinfo` anywhere in `jcore-cpu` or `jcore-soc`. See
   [§3.2](#32-mmu-sub-allocation-0xff000000-0xff000fff) for the full rationale and for the
   flagged functional overlap between CPUINFO's `HART_ID` and jcore-soc's `jcore,cpuid-mmio` at
   `0xABCD0600`.
   **Residual — CLOSED 2026-09-07.** This paragraph previously read that "all four offsets remain
   undecoded in RTL, so the Linux defines still read as constant zero". They are decoded:
   `datapath.vhm` selects `P4_TRA` at `x"20"`, `P4_EXPEVT` at `x"24"`, `P4_INTEVT` at `x"28"` and
   `P4_MMUFSR` at `x"2C"`, with `TRA` read/write and `EXPEVT`/`INTEVT` read-only. §3.2 said so
   already; this residual note outlived it.
5. **64-bit J64 P4 layout.** This map specifies the 32-bit J32 layout. J64 retains P4 at the same virtual addresses (high half of address space) but with wider underlying PA — see [mmu/design-spec.md §3.7](../mmu/design-spec.md). No new addresses are introduced by J64; the existing allocations remain valid.
