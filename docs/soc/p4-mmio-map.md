# J-Core P4 MMIO Allocation Map

**Status:** Canonical allocation table. Update **before** any new spec claims a P4 address.

**Scope:** Master allocation of the SH-4 P4 segment (`0xE0000000`–`0xFFFFFFFF`, 512 MB) across all J-Core control registers, on-chip peripherals, and SoC blocks.

**Authority:** This document is the single source of truth for P4 address allocation. If another spec disagrees with this map, this map wins and the other spec is wrong. Every spec that places a control register in P4 MUST cite this document and use an address allocated here.

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
| `0xE0000000`–`0xEFFFFFFF`   | 256 MB | SH-4 legacy store-queue region (SQ)                        | reserved   |
| `0xF0000000`–`0xF7FFFFFF`   | 128 MB | Cache management — L1 array access, L2 array access        | reserved   |
| `0xF8000000`–`0xFEFFFFFF`   | 112 MB | Future expansion                                           | reserved   |
| `0xFF000000`–`0xFFFFFFFF`   | 16 MB  | **Core MMIO** — all current allocations live here          | allocated  |

**Why the 16 MB live region.** All shipping J-Core control registers fit in the top 16 MB. The other three quarters of P4 are deliberately empty — they preserve room for: (1) the SH-4 store-queue facility if J-Core ever implements it, (2) direct L1/L2 array access for debug/diagnostics, and (3) a generous reserve for blocks we haven't designed yet.

---

## 3. The `0xFF000000`–`0xFFFFFFFF` live region

The live 16 MB region is partitioned into per-block ranges. **Per-CPU blocks** appear at the same address on every core; the bus fabric routes the access to the requesting core's local instance based on the master's `BMID` (per [bus/fabric-spec.md §4](../bus/fabric-spec.md)).

| Range                       | Size   | Block                              | Per-CPU? | Spec |
|-----------------------------|-------:|------------------------------------|:--------:|------|
| `0xFF000000`–`0xFF000FFF`   |  4 KB  | MMU control + CPUINFO              | yes      | [mmu/hardware-spec.md §2](../mmu/hardware-spec.md) |
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
| `0x000`     | PTEH       | Page-table entry, high (VPN only — ASID lives in ASIDR) |
| `0x004`     | PTEL       | Page-table entry, low (with PageMask) |
| `0x008`     | TTB        | Translation table base (software)     |
| `0x00C`     | TEA        | TLB exception address                 |
| `0x010`     | MMUCR      | MMU control                           |
| `0x014`     | TSBBR      | TSB base register                     |
| `0x018`     | TSBCFG     | TSB configuration                     |
| `0x01C`     | TSBPTR     | TSB pointer (read-only)               |
| `0x020`     | CPUINFO    | Per-CPU hart ID + capability flags    |
| `0x024`     | ASIDR      | 16-bit ASID_TAG (kernel-encoded ASID + generation) |
| `0x028`–`0xFFC` | reserved | future MMU registers                 |

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
4. **No new blocks in `0xE0000000`–`0xFEFFFFFF`** without explicit project review. The reservation policy keeps those regions empty for future major subsystems.
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
4. **64-bit J64 P4 layout.** This map specifies the 32-bit J32 layout. J64 retains P4 at the same virtual addresses (high half of address space) but with wider underlying PA — see [mmu/design-spec.md §3.7](../mmu/design-spec.md). No new addresses are introduced by J64; the existing allocations remain valid.
