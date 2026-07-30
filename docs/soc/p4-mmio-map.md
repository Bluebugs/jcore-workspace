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
| `0x000`     | reserved   | freed — see "Registers with no P4 address" below |
| `0x004`     | reserved   | freed — see "Registers with no P4 address" below |
| `0x008`     | TTB        | Translation table base (software)     |
| `0x00C`     | TEA        | TLB exception address                 |
| `0x010`     | MMUCR      | MMU control                           |
| `0x014`     | TSBBR      | TSB base register                     |
| `0x018`     | TSBCFG     | TSB configuration                     |
| `0x01C`     | TSBPTR     | TSB pointer (read-only)               |
| `0x020`     | TRA        | TRAPA immediate — stock SH-4 placement; **decoded in RTL** (also `STC TRA,Rn`) |
| `0x024`     | EXPEVT     | Exception event code — stock SH-4 placement; **decoded in RTL**, read-only (also `STC EXPEVT,Rn`) |
| `0x028`     | INTEVT     | Interrupt event code — stock SH-4 placement; **decoded in RTL**, read-only (also `STC INTEVT,Rn`) |
| `0x02C`     | MMUFSR     | Fault-status snapshot, read-only; **decoded in RTL** (see [mmu/hardware-spec.md §2.11](../mmu/hardware-spec.md)) |
| `0x030`     | CPUINFO    | Per-CPU hart ID + capability flags — **allocated, NOT implemented in current RTL** (see note below) |
| `0x034`–`0x038` | reserved | future registers                              |
| `0x03C`     | QACR0      | Store-queue 0 area register (`0xFF00003C`), see [../sq/spec.md §3](../sq/spec.md) |
| `0x040`     | QACR1      | Store-queue 1 area register (`0xFF000040`), see [../sq/spec.md §3](../sq/spec.md) |
| `0x044`–`0xFFC` | reserved | future registers                                  |

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

**Registers with no P4 address: PTEH, PTEL, ASIDR.** Earlier revisions of this map listed
PTEH at `0x000`, PTEL at `0x004` and ASIDR at `0x024`. **Those rows were wrong and have been
removed.** PTEH, PTEL and ASIDR are **LDC/STC-only control registers with no P4 MMIO address**:
they are written with `LDC Rm, PTEH` / `LDC Rm, PTEL` / `LDC Rm, ASIDR` and read with the
matching `STC`, and they are never P4-MMIO selected. See
[../mmu/hardware-spec.md §2.1](../mmu/hardware-spec.md) (PTEH), §2.1a (ASIDR) and §2.2 (PTEL).
PTEU ([mmu/hardware-spec.md §2.10](../mmu/hardware-spec.md), PAE-only) is likewise LDC/STC-only.

The RTL is the ground truth here: `jcore-cpu/core/datapath.vhm:1136-1155` decodes exactly six P4
offsets — `0x08` TTB, `0x0C` TEA, `0x10` MMUCR, `0x14` TSBBR, `0x18` TSBCFG, `0x1C` TSBPTR
(read-only) — and the comment at `datapath.vhm:1147` states that "PTEH/PTEL/ASIDR are never P4-MMIO
selected (handled via LDC)". The LDC write path for those three is `datapath.vhm:1335-1342`.
Linux agrees independently: `arch/sh/include/cpu-jcore/cpu/mmu_context.h` defines MMIO addresses for
the six decoded registers only and documents that "PTEH/PTEL/PTEU and ASIDR are LDC/STC-only control
registers"; `arch/sh/mm/tlb-jcore.c` uses `ldc %0, pteh`.

**Undecoded P4 offsets fail SILENTLY (normative hazard).** A load or store to a P4 offset in this
block that the hardware does not decode raises **no exception and no bus error**. Writes fall into
the decoder's `when others => null` arm (`datapath.vhm:1174`) and are discarded; reads fall into
`when others => this.m_dr_next := (others => '0')` (`datapath.vhm:1184`) and return **zero**, with
`m_en` still asserted so the access completes normally from the pipeline's point of view. Software
that uses a phantom P4 address therefore observes a register that is permanently zero and never
faults — a failure mode that is easy to mistake for "the feature is disabled". Any address in this
sub-block marked *reserved*, or marked *allocated but not implemented* (CPUINFO `0x030`), behaves
this way today. TRA/EXPEVT/INTEVT and MMUFSR are no longer in that category — the RTL decodes all
four. There are zero occurrences of `cpuinfo` in
any `.vhd`/`.vhm` source; its allocation is a valid reservation, but reading it returns zero rather
than a hart ID. The same holds for the Linux `TRA`/`EXPEVT`/`INTEVT` defines: they now name the
correct architectural addresses, but until `datapath.vhm` decodes them a kernel reading them through
MMIO now reads the real register.

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

---

## 6. Prior art

The P4 segment itself is SH-4 architecture (Renesas/Hitachi hardware manual, 1998 — pre-2006).

Address-map partitioning conventions:
- Per-CPU MMIO base address with fabric-decoded routing — SH-4 INTC per-CPU layout (1998); UltraSPARC II per-CPU UDB registers (1997).
- Generous reservation policy with 4 KB-aligned slots — ARM AMBA "memory map by 4 KB pages" convention (AMBA AHB, 1999); PCI BAR alignment rules (PCI 2.0, 1993).
- SoC-wide control register page separate from per-CPU pages — PowerPC 7xx/74xx SoC layout (1997 onwards).
- Peripheral allocation table maintained as a single canonical document — PCI device ID registry pattern (PCI SIG, 1992).

All references pre-2006, satisfying the project-wide prior-art policy ([glossary §2](../glossary.md)).

---

## 7. Open questions

1. **Pre-this-map peripheral addresses.** Several jcore-soc peripherals currently sit at ad-hoc P4 addresses outside this map. A coordinated re-allocation across the existing RTL and the Linux DTS is required to bring them into conformance. Owner: jcore-soc maintainer + Linux DTS maintainer.
2. **Cross-CPU debug access.** Reserved range `0xFF003000`–`0xFF00EFFF` is currently empty. If a cross-CPU register-poke debug facility is desired (e.g. for halt-mode debugging), specify the protocol and consume some of this range.
3. **L1 array access for diagnostics.** SH-4 used the `0xF0000000`–`0xF7FFFFFF` region for direct cache-array access. J-Core has not yet committed to whether to implement an equivalent facility; the region is reserved either way.
4. **Three-way conflict at `0x020`/`0x024`/`0x028` — RESOLVED.** Three documents used to disagree
   about this half-dozen bytes: this map allocated `0x020` = CPUINFO and (formerly) `0x024` =
   ASIDR; Linux `arch/sh/include/cpu-jcore/cpu/mmu_context.h` assigned `0xff000020` = TRA,
   `0xff000024` = EXPEVT, `0xff000028` = INTEVT; and the RTL
   (`jcore-cpu/core/datapath.vhm:1136-1155`) decoded **none** of the three — only `0x08` TTB,
   `0x0C` TEA, `0x10` MMUCR, `0x14` TSBBR, `0x18` TSBCFG, `0x1C` TSBPTR.
   **Decision:** `0x020` = TRA, `0x024` = EXPEVT, `0x028` = INTEVT — the stock SH-4 architectural
   placement (SH-4 hardware manual, Renesas/Hitachi, 1998), which is also what Linux already
   defines. CPUINFO moves to `0x02C` and remains allocated-but-not-implemented. This supersedes
   [../priv-arch/design-spec.md §4.6](../priv-arch/design-spec.md)'s `0x028`/`0x02C`/`0x030`
   relocation proposal, whose only motivation — dodging CPUINFO and ASIDR — has dissolved now that
   ASIDR is LDC/STC-only and CPUINFO has moved. Nothing had to be displaced: CPUINFO was a paper
   allocation with zero occurrences of `cpuinfo` anywhere in `jcore-cpu` or `jcore-soc`. See
   [§3.2](#32-mmu-sub-allocation-0xff000000-0xff000fff) for the full rationale and for the
   flagged functional overlap between CPUINFO's `HART_ID` and jcore-soc's `jcore,cpuid-mmio` at
   `0xABCD0600`.
   **Residual (not part of this question):** all four offsets remain undecoded in RTL, so the
   Linux defines still read as constant zero until `datapath.vhm` implements them. That is an
   implementation task, not an allocation dispute.
5. **64-bit J64 P4 layout.** This map specifies the 32-bit J32 layout. J64 retains P4 at the same virtual addresses (high half of address space) but with wider underlying PA — see [mmu/design-spec.md §3.7](../mmu/design-spec.md). No new addresses are introduced by J64; the existing allocations remain valid.
