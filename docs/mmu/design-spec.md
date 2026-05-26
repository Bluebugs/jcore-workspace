# J-Core MMU Design Specification

**Status:** Draft  
**Scope:** J3, J32, and J64 (32-bit and 64-bit J-Core variants with virtual memory)  
**Audience:** Hardware architects, kernel developers, system integrators

---

## 1. Goals

Add memory isolation between processes to the J-Core CPU family while:

- Keeping the hardware addition minimal and FPGA-friendly
- Supporting page sizes larger than 4 KB to reduce TLB pressure and memory bandwidth, as proven on Apple Silicon
- Producing a design that scales from 32-bit (J3, J32) to 64-bit (J64) with no ISA break
- Allowing a single Linux port — one source tree, one TLB-miss handler — to target both word widths
- Reserving extensibility for future virtualization without requiring it on day one

## 2. Background

The current J-Core (J2/J32) implements the SH-2 instruction set and has no MMU. The SH-4 MMU (1998), whose patents have all expired, provides a working reference for software-loaded translation on the SuperH family and is supported by Linux today via `arch/sh/`. However, the SH-4 design has aged in three ways: its page sizes (1 KB, 4 KB, 64 KB, 1 MB) are too restrictive, its hardware-defined register set leaks implementation choices that constrain 64-bit extension, and its 8-bit ASID field is too narrow for modern process counts.

The design proposed here keeps the SH-4 register interface where Linux already speaks it (PTEH, PTEL, MMUCR, TEA, TTB, LDTLB, the standard exception vectors), modernizes the parts that matter for performance and flexibility, and borrows the most elegant elements of the UltraSPARC, MIPS R4000, and DEC Alpha designs — all of which predate the design choices by at least 25 years and are unencumbered by patents.

## 3. Design Choices

### 3.1 Software-loaded TLB

The MMU does not walk page tables in hardware. On a TLB miss, hardware vectors to a software trap handler which is responsible for finding the translation and installing it. This is the MIPS R4000, UltraSPARC, and Alpha approach.

**Rationale:** A hardware page-table walker costs significant gates and bakes the page-table format into the ISA, which is exactly what makes 32→64-bit transitions painful on architectures like PowerPC and ARM. With a software-loaded TLB, the page-table layout is entirely an OS decision — Linux uses one format on J32 and a wider variant on J64 from the same source tree, with no hardware change.

### 3.2 Hardware TSB pointer assist

Although the hardware does not walk page tables, it computes — on every TLB miss — the address of the cache slot in a software-managed Translation Storage Buffer (TSB) where the translation, if cached, would reside. The trap handler reads this pre-computed pointer and is one load away from the candidate TTE (Translation Table Entry).

**Rationale:** This is the UltraSPARC innovation. It gives a TLB-miss hot path of ~7 instructions (versus 30–50 for a pure software walker) without committing to a hardware page-table format. The TSB itself is a flat array in memory whose layout is entirely OS-defined.

### 3.3 16 KB base page size

The default page size is 16 KB, matching Apple Silicon's choice and Linux's `CONFIG_ARM64_16K_PAGES`. Hardware supports page sizes of 4 KB, 16 KB, 64 KB, 256 KB, 1 MB, 4 MB, 16 MB, 64 MB, 256 MB, and 1 GB via a 4-bit `PageMask` field in each TLB entry.

**Rationale:** Apple's measurements and Ampere's tuning guides demonstrate that 4× larger base pages give 4× fewer TLB entries to cover the same working set and 4× less memory bandwidth wasted on page-table walks. On a software-loaded TLB this matters even more because miss handling is more expensive than on a hardware walker. As of 2026, the Linux ecosystem has converged on 16 KB working well (Asahi Linux, Raspberry Pi 5 Bookworm, Android 15+, Ampere servers). Linus Torvalds's historical objection to large pages targeted 64 KB; 16 KB is widely accepted. Smaller page sizes (4 KB) remain available via PageMask for kernel-internal mappings that need finer granularity.

### 3.4 12-bit ASID

Each TLB entry is tagged with a 12-bit Address Space Identifier (ASID), giving 4096 simultaneous process contexts before rollover.

**Rationale:** MIPS used 8 bits (256 contexts); SH-4 used 8 bits. Modern process and container counts make 4096 a more comfortable working size. The cost is 4 extra bits of state per TLB entry — negligible.

### 3.5 ASID-generation tagging

The TSB tag includes both the ASID and a 4-bit generation discriminator drawn from a per-CPU 64-bit generation counter. The kernel encodes the 16-bit `ASID_TAG = (asid | gen_low << 12)` and writes it on every context switch — into the dedicated **ASIDR** register (not PTEH; see [hardware-spec.md §2.1a](hardware-spec.md)). Hardware compares this composite tag against the TSB entry's tag word on every TLB lookup. The PTEH/ASIDR split (modeled on UltraSPARC `PRIMARY_CONTEXT`) keeps the full 4 KB–1 GB page-size range available even with the wider 16-bit ASID_TAG.

**Rationale:** This single design choice resolves several otherwise-difficult problems: ASID rollover invalidation becomes a counter bump (no TLB flush needed), stale TSB entries after suspend/resume are naturally rejected, IPI-free TLB shootdown via lazy invalidation becomes possible, and the per-CPU ASID scheme (each CPU has its own allocator) becomes safe even when an `mm` migrates between CPUs.

### 3.6 No VMID field

Earlier drafts reserved an 8-bit VMID (Virtual Machine ID) in the TLB tag layout. **That reservation is removed.** The hypervisor extension ([hypervisor/design-spec.md §3.7](../hypervisor/design-spec.md)) implements guest isolation by partitioning the 12-bit ASID space in software (each guest gets a sub-range of ASIDs), not by tagging TLB entries with a separate guest identifier. This follows sun4v's actual approach (pre-2006 SPARC v9 hypervisor architecture). The eight saved bits per TLB entry are gone, not earmarked for future use.

See [glossary §5](../glossary.md) for the project-wide decision.

### 3.7 Inherited SH-4 segment layout

The SuperH fixed segment layout is preserved unchanged:

| Segment | Range | Translation | Caching | Privilege |
|---------|-------|-------------|---------|-----------|
| P0 | `0x00000000`–`0x7FFFFFFF` | Translated | Cached | User + Kernel |
| P1 | `0x80000000`–`0x9FFFFFFF` | **Untranslated** (PA = VA & `0x1FFFFFFF`) | Cached | Kernel |
| P2 | `0xA0000000`–`0xBFFFFFFF` | **Untranslated** | Uncached | Kernel |
| P3 | `0xC0000000`–`0xDFFFFFFF` | Translated | Cached | Kernel |
| P4 | `0xE0000000`–`0xFFFFFFFF` | MMIO, no caching | — | Kernel |

**Rationale:** P1's untranslated direct map eliminates the "MMU bring-up chicken-and-egg" problem that plagues x86 and ARM kernels. The kernel runs in P1 at all times; the MMU only translates user-space (P0) and vmalloc/ioremap (P3). MMU enable is a single bit flip with no PC-moves-under-you risk.

For J64, the layout extends naturally: P1 becomes the high half of the address space with `PA = VA & ((1 << PA_BITS) - 1)`.

## 4. Architecture Overview

### 4.1 Translation pipeline

A user-mode (or P0/P3 kernel) memory access proceeds:

1. Virtual address presented to MMU.
2. MMU consults TLB. Match on `{ASID_TAG, VPN}` returns the PFN, page size, and permissions. (`ASID_TAG` is 16 bits = 12-bit ASID + 4-bit gen_low, per the kernel's encoding.)
3. On hit: physical address forms, access proceeds.
4. On miss: hardware computes `TSBPTR = TSBBR | (hash(VPN) & mask) << 4`, stores it in the TSBPTR register, latches the faulting VPN into PTEH, stores the faulting effective address in TEA, and traps to the TLB-miss vector at `VBR + 0x400`.

### 4.2 TLB-miss software flow

The handler runs in supervisor mode with `SR.RB=1` (bank 1 selected, providing 8 scratch registers without save/restore):

1. Read TSBPTR. Load the TTE tag and data from that address.
2. Compare tag against PTEH. If match: load the data into PTEL, execute LDTLB.R to install in the TLB and return atomically.
3. If mismatch: fall through to the slow-path page-table walker. Find the translation by walking the OS page table from `current_pgd`. Install in both the TSB (for next time) and the TLB.
4. If the walker also fails: vector to the page-fault handler, which signals SIGSEGV or grows the stack or pages in the file, per standard Linux semantics.

### 4.3 TSB structure

Each TSB entry is 16 bytes:

```
Offset  Field        Width   Description
------  -----------  ------  -----------------------------------------
+0      tag_hi       32b     Expected VPN  (matches PTEH after miss)
+4      tag_lo       32b     Expected ASID_TAG  (matches ASIDR), low 16 bits
+8      Data         64b     PPN | PageMask | Flags (R/W/X/D/C/U/G)
```

The same layout works for J32 (with upper VPN/PPN bits unused) and J64 (with all bits populated). Hash function for indexing: XOR-fold the VPN with itself shifted right by `log2(TSB_entries)`, masked to entry count.

The TSB lives in normal cacheable memory, allocated by the kernel at boot (one per CPU). Its size is a kernel policy decision; typical sizes are 8 KB (512 entries) for embedded, 64 KB (4096 entries) for systems with significant working sets.

### 4.4 Register banking

SH-3 and SH-4 already provide R0–R7 register banking controlled by `SR.RB`. On exception entry, hardware sets `SR.RB=1, SR.MD=1, SR.BL=1` and saves `PC→SPC`, `SR→SSR`. The TLB-miss handler thus inherits 8 scratch registers with zero save/restore cost — equivalent to UltraSPARC's alternate global registers, achieved by inheriting the existing SH banking mechanism unchanged.

### 4.5 SMP topology

Each CPU in an SMP J-core configuration has:

- Its own TLB and TSB
- Its own ASID allocator state (generation counter, used bitmap, current next-asid pointer)
- Its own per-CPU page directory pointer (`current_pgd`)
- A unique hart ID readable from the `CPUINFO` MMIO register

The kernel page tables are global; user page tables are per-process and accessed via per-CPU `current_pgd`. ASIDs are per-CPU (an ASID number on CPU 0 is unrelated to the same number on CPU 1), eliminating the need for cross-CPU ASID coordination.

### 4.6 TLB shootdown protocol

Lazy TLB shootdown requires L1-D coherence; depends on L2 v2 (see [cache/l2-spec.md](../cache/l2-spec.md), specifically §7 for the MSI directory protocol and §22.4 for the cross-CPU lazy-shootdown sanity test). On single-core J32 (no coherence required), only the local-flush paths below apply.

Standard Linux IPI-based shootdown is supported but minimized:

- **Process exit / exec:** ASID is freed in the per-CPU allocator; no IPI needed. Recycled ASID will get a new generation number, naturally rejecting stale TSB entries.
- **Full TLB flush:** Local-only via `MMUCR.TI` bit. Other CPUs are not affected.
- **Per-VA unmap (e.g., `munmap` of a small region):** Lazy invalidation. PTE is cleared in memory, the physical page is marked deferred-free, and remote CPUs invalidate their TLB entries opportunistically at the next context switch, syscall, or scheduler tick. The `mm_cpumask` tracks which CPUs need to drain.
- **Hard cases requiring synchronous invalidation:** Standard cross-CPU IPI to the affected CPUs only (not broadcast).

## 5. Address-Space Layout (Detail)

### 5.1 User space (P0)

J32: 2 GB user virtual address space (`0x00000000` to `0x7FFFFFFF`).  
J64: configurable, default 256 GB (38-bit VA), expandable to 48-bit or beyond.

### 5.2 Kernel space (P1, P2, P3)

P1 is the direct-mapped kernel image and "lowmem" data. P3 is reserved for vmalloc, ioremap, and module loading. P4 is MMIO and not subject to translation.

### 5.3 J64 extension

J64 uses 48-bit virtual addresses by default with the segment layout repositioned to the high end:

| Segment | J64 Range | Notes |
|---------|-----------|-------|
| User | `0x0000_0000_0000_0000` – `0x0000_7FFF_FFFF_FFFF` | Translated |
| Direct map (P1 equivalent) | `0xFFFF_8000_0000_0000` – `0xFFFF_BFFF_FFFF_FFFF` | Untranslated, cached |
| Uncached direct (P2 equiv) | `0xFFFF_C000_0000_0000` – `0xFFFF_CFFF_FFFF_FFFF` | Untranslated, uncached |
| Vmalloc (P3 equiv) | `0xFFFF_D000_0000_0000` – `0xFFFF_EFFF_FFFF_FFFF` | Translated |
| MMIO (P4 equiv) | `0xFFFF_F000_0000_0000` – `0xFFFF_FFFF_FFFF_FFFF` | MMIO |

Linux's standard 4-level or 5-level page table walking handles this naturally.

## 6. Memory Isolation Guarantees

- **Process isolation:** Each process has a unique ASID per CPU. TLB entries are tagged with ASID; access from the wrong context misses the TLB and falls into the trap handler, which consults the right page table.
- **User/kernel isolation:** User-mode access to P1, P2, P3, or P4 raises a privilege fault unconditionally. The User bit in each PTE further restricts user access to kernel-owned P0 mappings.
- **W^X (write-xor-execute):** Per-page Write and Execute permissions are independent in the PTE; the kernel can enforce non-writable code and non-executable data.
- **Inter-process page sharing:** Pages may be mapped into multiple ASIDs with potentially different permissions; the TLB tracks the `(ASID, VPN)` pair, so shared-memory regions work transparently.

## 7. Performance Characteristics

Target performance metrics (100 MHz J-Core, 16 KB pages, 32-entry fully-associative TLB, 512-entry TSB):

| Operation | Cycles |
|-----------|--------|
| TLB hit | 0 (in pipeline) |
| TLB miss, TSB hit | ~12 (7 instructions + entry/exit overhead) |
| TLB miss, TSB miss, walker hit | ~30 |
| Context switch (`switch_mm`) | ~20 |
| ASID rollover (every ~4096 context switches) | ~200 |
| Page fault (genuine) | depends on Linux mm path |

For typical workloads with 16 KB pages, TLB hit rates >99% are realistic, making the average memory access cost essentially the TLB hit cost.

## 8. Out of Scope

The following are noted but not specified in detail in this document:

- **Hypervisor extension:** specified in [hypervisor/design-spec.md](../hypervisor/design-spec.md). No new MMU hardware fields; guest isolation is via ASID partitioning in software (see §3.6 and [glossary §5](../glossary.md)).
- **I/O MMU:** Not addressed. If needed for DMA isolation, a separate IOMMU design is required.
- **Cache coherency:** Inherited from existing J-Core SMP design. Multi-CPU cache coherence is orthogonal to MMU design.
- **Fast parallel SMP resume:** The serial primary-then-secondary resume model is specified. A future fast-parallel variant requiring always-on persistent registers is deferred.

## 9. References

- Hitachi SH-4 Hardware Manual, 1998
- UltraSPARC I/II User's Manual, Sun Microsystems, 1997
- MIPS R4000 User's Manual, 1991
- ARM Architecture Reference Manual (ARMv8-A), 16K granule chapter
- Linux kernel `arch/sh/`, `arch/sparc/`, `arch/mips/` MMU implementations
- J-core mailing list, [J-core] MMU-Design thread, December 2017
