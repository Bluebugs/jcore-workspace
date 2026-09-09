# J-Core IOMMU Design Specification (Phase 2)

**Status:** Draft  
**Scope:** I/O Memory Management Unit for J-Core SoCs  
**Audience:** Hardware architects, kernel developers, system integrators  
**Prerequisites:** Phase 1 MMU spec (`01-design-spec.md`)

> **§3.6, §4.1, §4.2 and §7 revised — 2026-09-09, Wave-3 task C2d.** The bypass
> design this document argued for is replaced by default-deny; the normative owner
> is [hardware-spec.md §3.10](hardware-spec.md) (`I-R1`–`I-R10`). Three claims are
> withdrawn rather than edited: that reset-to-bypass is a convenience worth its
> cost, that the `GLOBAL` bit is a legitimate sharing mechanism, and that the
> IOMMU delivers cache coherency. Each is quoted where it is retired, per
> [decisions/0002](../decisions/0002-supersede-convention.md).
>
> **Nothing in this document is implemented**: `jcore-cpu@origin/master` and
> `jcore-soc@origin/master` contain no IOMMU, no IOTLB and no BMID.

---

## 1. Goals

Add IOMMU support to the J-Core SoC family to:

- Provide memory isolation between DMA-capable devices and the CPU/OS
- Enable virtually contiguous DMA buffers without requiring physical contiguity (eliminating the need for CMA for framebuffers and large packet buffers)
- Support scatter-gather DMA natively
- Cover the primary high-bandwidth use cases (video output and Ethernet) with negligible bandwidth penalty
- Integrate cleanly with Linux's existing IOMMU framework so existing drivers work unmodified
- Reuse architectural primitives from the Phase 1 MMU design (page-size encoding, fault semantics) for engineering economy
- Reserve extensibility for future virtualization without paying for it now

Non-goals for Phase 2:

- Hardware support for PCIe or other peripheral bus standards (j-core targets are SoC-internal)
- I/O page-fault handling (we use pre-mapped buffers; no demand paging from devices)
- Two-stage IOVA translation for hypervisor guests (reserved encoding, deferred to Phase 3)

## 2. Background

Without an IOMMU, DMA-capable devices issue bus requests with physical addresses directly. This has three significant consequences:

1. **No isolation.** Any device can read or write any physical memory location, including kernel data structures. A buggy device driver or a compromised peripheral can corrupt the kernel.
2. **No virtual-to-physical scatter-gather.** Buffers must be physically contiguous or the driver must build scatter-gather descriptor lists from physical fragments. For framebuffers (multi-megabyte), the Linux Contiguous Memory Allocator (CMA) is required, and CMA fragments unfavorably over the lifetime of the system.
3. **No DMA-coherent virtual addressing.** A buffer that's virtually contiguous in user space must be either copied or scatter-gathered when given to a device, adding overhead.

An IOMMU resolves all three by interposing a translation step between devices and the memory system. Each device sees a per-device virtual I/O address space (IOVA); the IOMMU translates IOVA to physical address (PA) using software-managed mappings.

The phase-1 MMU spec established several primitives — the PageMask field for variable page sizes, the ASID/generation tagging scheme, the SH-4 register-interface conventions — which the IOMMU design reuses.

## 3. Design Choices

### 3.1 No hardware page-table walker

**Decision:** The IOMMU does not walk page tables in hardware. The IOTLB is written directly by software via MMIO; on IOTLB miss the IOMMU blocks the transaction and signals a fault.

**Rationale:** This is the most consequential design choice. A hardware walker is the largest single component of a typical IOMMU (Intel VT-d, ARM SMMU) and is needed because those IOMMUs are designed for general-purpose servers where devices issue DMA with virtual addresses chosen at runtime by guest VMs or untrusted user code.

J-Core's target workload is fundamentally different. DMA mappings for embedded and lightweight systems are **long-lived** — a framebuffer is mapped at display-init time and used continuously for hours; Ethernet rings are allocated at link-up and reused per packet; USB buffers persist for the device's lifetime. The kernel knows in advance what needs to be mapped. Pre-mapping every buffer at allocation time is not a performance constraint; it's the natural shape of the work.

If the IOTLB is large enough to hold every active mapping, **the miss rate in steady state is exactly zero**. A miss indicates a kernel bug (failed to map a buffer) or a misconfigured device (DMA from a stray address) — both are exceptional events, not hot paths.

This is the approach Sun took with UltraSPARC's DVMA controller in the early 1990s. It worked then for the same reason it works now: DMA workloads are not page-faulting workloads.

### 3.2 16K base page with variable superpages

**Decision:** Same page-size encoding as the Phase 1 CPU MMU. PageMask field selects from {4 KB, 16 KB, 64 KB, 256 KB, 1 MB, 4 MB, 16 MB, 64 MB, 256 MB, 1 GB}.

**Rationale:** Sharing the page-size encoding lets the kernel use the same allocation primitives for CPU and IOMMU mappings. More importantly, large pages are exactly what makes a small IOTLB cover a real DMA workload: a 1080p framebuffer (8 MB) fits in one 16 MB superpage entry; a 4K framebuffer (32 MB) fits in one 64 MB entry.

The IOTLB hit rate of 100% in steady state is achieved by choosing the right page size for each buffer at map time — Linux's generic IOMMU layer does this automatically based on the `pgsize_bitmap` advertised by the driver.

### 3.3 Per-device contexts via Bus Master ID (BMID)

**Decision:** Each bus initiator carries a unique 8-bit BMID (256 distinct devices). IOTLB entries are tagged with BMID. Two devices using the same IOVA refer to different physical mappings.

**Rationale:** BMID is analogous to ASID for the CPU MMU. It provides device-level isolation: a buggy Ethernet driver can't accidentally clobber the framebuffer's mappings because they live under different BMIDs. The BMID is assigned by the SoC bus fabric based on the device's physical position, not by software — devices can't spoof each other.

8 bits gives 256 BMIDs, which is more than any realistic J-Core SoC will have. Each major peripheral consumes one BMID; if a peripheral has multiple DMA engines (e.g., separate RX and TX MAC channels), they may share a BMID or use distinct ones depending on isolation needs.

The BMID assignment policy (which ranges go to CPU cores vs DMA engines vs guest pass-through), the unforgability guarantee (master cannot influence its own BMID), and the reserved values (`0x00` and `0xFF`) are specified normatively in [bus/fabric-spec.md §4](../bus/fabric-spec.md). This IOMMU design assumes those properties.

### 3.4 Software-managed IOTLB, no software-visible page tables

**Decision:** There is no IOMMU-visible page table format. The kernel maintains its own data structures tracking what's mapped where, but the IOMMU only sees IOTLB entries.

**Rationale:** This is a direct consequence of having no hardware walker. The kernel can use whatever internal representation suits Linux's IOMMU subsystem (a generic IOVA allocator plus per-domain bitmaps is typical). The IOMMU is "just" a fast translation cache — semantically it's a memory protection unit with caching, not a full virtual memory subsystem.

This also means the IOMMU has no concept of a "page-table base register" or domain pointer per device. Switching between IOMMU domains (e.g., for VFIO passthrough) is implemented by invalidating and reloading IOTLB entries, not by switching a domain root pointer.

### 3.5 Block-and-report on miss

**Decision:** When the IOTLB misses, the IOMMU blocks the transaction, latches fault information in a status register, and raises an interrupt. *(This previously read "returns bus error to the master"; the J-Core bus has no error response, so the block **completes** the transaction with read data zero and the write discarded — [hardware-spec.md §2.2](hardware-spec.md) and [`I-R2`](hardware-spec.md).)*

**Rationale:** The miss case is a kernel bug or misbehaving device, not a routine event. Blocking is the secure default: any other behavior either leaks data (passthrough on miss) or silently corrupts memory (default-write-to-scratchpad). The interrupt lets Linux log the fault and take action — typically logging to dmesg and disabling the offending device.

This matches Linux's `iommu_report_device_fault()` framework conventions and produces good diagnostics out of the box.

### 3.6 Per-BMID deny at reset; bypass is opt-in

**Decision:** A per-BMID bitmap controls which BMIDs skip translation. **It resets
to all zeros**, so every BMID goes through the IOTLB, and with the IOTLB reset
empty every BMID is blocked. Setting a bit is an explicit act that hands one master
an unprotected path. Normative: [hardware-spec.md §3.10](hardware-spec.md) `I-R1`.

**Rationale:** an unclaimed device is exactly the device nobody has reasoned about,
and it is the one that must not be able to reach memory. Deny costs no new state —
a BMID with its bypass bit clear and no matching entry already blocks, latches a
fault and raises an IRQ, so "deny" and "miss" are the same hardware
([security/threat-model.md §7.7](../security/threat-model.md)). What the reset
polarity buys is that the protection is present *before* the software that would
configure it, rather than after.

**The debugging convenience survives** — a developer bringing up a driver can still
set that BMID's bypass bit — but it is now a positive act on a running system rather
than the state a board powers up in.

> **The retired rationale read:** *"At reset, all bypasses are set — the IOMMU is
> effectively absent. This lets the bootrom and early kernel use DMA without first
> initializing the IOMMU. Once the IOMMU driver is up, it clears bypass bits for
> devices it manages while leaving them set for any device that hasn't yet been
> claimed."* The second sentence is a real cost and
> [hardware-spec.md §8](hardware-spec.md) prices it. The third is the defect: leaving
> unclaimed devices in bypass is not a transitional state, it is the permanent one
> for every device no driver ever binds.
>
> **And the security argument under it is retired outright:** *"The bypass bitmap is
> itself an MMIO register, so accidentally enabling bypass requires kernel-mode
> access, the same trust level as direct PA access."* That is sound under a threat
> model whose adversary is an unprivileged process. Under
> [security/threat-model.md §1](../security/threat-model.md)'s, **the adversary is a
> guest kernel**, and "the same trust level as direct PA access" stops being a
> reassurance and becomes the thing being defended. What actually keeps the register
> out of a guest's reach is
> [hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md)'s fail-closed
> P4 trap — a different mechanism, in a different document, that this paragraph was
> not relying on.

### 3.7 No VMID field

Earlier drafts reserved an 8-bit VMID in IOTLB entries (mirroring the CPU MMU's earlier VMID reservation). **Both reservations are removed.** The hypervisor extension achieves guest isolation for DMA by partitioning the 8-bit BMID space in software — each guest gets a range of BMIDs, and the IOMMU's per-BMID page-table programming naturally enforces isolation. No VMID field exists in IOTLB entries.

See [glossary §5](../glossary.md), [mmu/design-spec.md §3.6](../mmu/design-spec.md), and [hypervisor/design-spec.md §3.7](../hypervisor/design-spec.md).

## 4. Architecture Overview

### 4.1 Topology

The IOMMU is a single SoC-level block sitting between the bus fabric and the DRAM controller (plus any shared on-chip SRAM that's DMA-accessible):

```
   CPU cores         GPU             Ethernet      USB         Display
     |                |                 |           |            |
     +-----+----------+--------+--------+--------+--+----+-------+
           |                   |                 |       |
           +-- coherent cache --+                |       |
                |                                |       |
                v                                v       v
           +----------------------------------------------------+
           |               SoC Bus Fabric (AXI)                 |
           |  Each initiator's transactions tagged with BMID    |
           +-----------------------+----------------------------+
                                   |
                                   v
                          +----------------+
                          |     IOMMU      |
                          | +------------+ |
                          | |   IOTLB    | |
                          | |  64 entry  | |
                          | +------------+ |
                          | + MMIO ctrl    |
                          +-------+--------+
                                  |
                                  v
                          +---------------+
                          |  DRAM ctrl    |
                          +---------------+
```

**The CPU's accesses do not pass through the IOMMU** — the CPU has its own MMU. The
IOMMU only translates transactions originating from non-CPU masters. This is
normative as [hardware-spec.md §3.10](hardware-spec.md) `I-R1a`, and it is normative
rather than descriptive because **the diagram above contradicts it**: the diagram
routes the CPU cores into the SoC bus fabric and the fabric into the IOMMU, which
would put a core's every DRAM access behind the IOTLB.

Under the retired all-bypass reset the contradiction was harmless — a core's
transactions bypassed like everything else, so the diagram and the sentence produced
the same machine. Under [`I-R1`](hardware-spec.md) they do not: reading the diagram, a core would be
denied its own boot fetch. The sentence is the correct half, and
[bus/fabric-spec.md §3.2](../bus/fabric-spec.md) agrees with it — *"DMA masters
bypass the CPU MMU but go through the IOMMU"*, said of DMA masters and of nobody
else. The diagram is retained, unfixed, as the record of what it said; read the
`coherent cache → fabric → IOMMU` chain as applying to the non-CPU initiators only.

### 4.2 Translation pipeline

A DMA transaction proceeds:

1. Bus master issues transaction; bus fabric tags it with the master's BMID.
2. Transaction reaches the IOMMU. IOMMU checks `BMID_BYPASS[BMID]`.
3. If the BMID is reserved (`0x00`, `0xFF`): block. [`I-R6`](hardware-spec.md).
4. If bypass: transaction passes through, `PA = IOVA`. No translation, and **no
   permission check** — there is no per-transaction permission on this path, which
   is why [hardware-spec.md §3.1a](hardware-spec.md) deletes the `DEFAULT_PERM`
   field that claimed to supply one.
5. If not bypass: IOMMU looks up `(BMID, IOVA)` in IOTLB, skipping entries with
   `GLOBAL = 1`. [`I-R5`](hardware-spec.md).
6. On IOTLB hit: form PA from `entry.PFN | (IOVA & page_offset_mask)`, check
   permissions, forward to DRAM controller.
7. On IOTLB miss, permission failure, or multiple match: block the transaction,
   **complete it with read data zero and the write discarded** ([`I-R2`](hardware-spec.md) — the bus has
   no error response), latch fault info, raise IRQ if enabled.

Step 4 is reachable only for a BMID whose bypass bit software has deliberately set.
Out of reset no BMID reaches it.

### 4.3 IOTLB structure

Recommended:

- 64 entries, fully associative
- Per-entry width ~100 bits (BMID, IOVA, PageMask, PFN, perms, flags)
- One-cycle lookup pipelined with bus arbitration (no added transaction latency on hit)

Smaller variants (32 entries) are reasonable for systems with few devices; larger (128 entries) for systems with many DMA buffers active simultaneously.

### 4.4 Fault model

Three classes of IOMMU fault:

| Fault | Cause | Hardware response | Software response |
|-------|-------|-------------------|-------------------|
| Translation miss | Unmapped IOVA | Block, log, IRQ | Log to dmesg, disable device |
| Permission | Write to RO mapping | Block, log, IRQ | Log to dmesg, disable device |
| Invalid request | Reserved BMID, refused entry install, multiple match, malformed transaction | Block, log, IRQ | Log to dmesg |

All faults block the originating transaction, which **completes** with read data
zero and the write discarded ([hardware-spec.md §2.2](hardware-spec.md) — the master
receives no error indication, because the bus carries none). A device whose DMA
engine relies on a bus error to halt will not halt; it will read zeros. That is a
correctness consequence for device drivers and it is stated here rather than left to
be discovered.

**The "disable device" column is load-bearing in a direction it does not look.**
It is the reason the shared IOTLB needs a quota: a tenant who can make *another*
tenant's `dma_map` fail can make that tenant's device fault, and this table is where
the fault becomes a shutdown. See [hardware-spec.md §3.10](hardware-spec.md) `I-R8`.

## 5. Performance Model

### 5.1 Steady-state performance

In steady state with all required mappings resident in the IOTLB:

- **Latency overhead per transaction:** 0 cycles (IOTLB lookup pipelined with bus arbitration)
- **Throughput overhead:** 0%
- **Power overhead:** small (one CAM lookup per transaction; negligible compared to DRAM access power)

### 5.2 Mapping setup overhead

- **`dma_map_single()` for a small buffer (fits one entry):** ~50 cycles for the MMIO writes that program the IOTLB entry, plus Linux DMA-API overhead.
- **`dma_map_sg()` for a large scatter list (10 fragments):** ~500 cycles for the MMIO writes.
- **First-time `dma_alloc_coherent()` for a framebuffer:** dominated by the kernel page allocator, not the IOMMU. IOTLB programming is one entry (one superpage) so ~50 cycles.

Mapping setup is amortized over many DMA transactions — typically 10⁴ to 10⁹ — making per-transaction setup cost invisible.

### 5.3 Workload-specific projections

For workloads we care about:

**1080p60 framebuffer scanout:**
- Display engine reads ~498 MB/s continuously
- One IOTLB entry maps the entire 8 MB framebuffer (16 MB superpage)
- Hit rate: 100%
- Penalty: <0.1%

**1 Gbps Ethernet TX/RX:**
- Sustained ~120 MB/s in each direction
- Working set: ring buffers (~256 KB) + active packet buffers (~1 MB)
- ~8 IOTLB entries needed
- Hit rate: 100%
- Penalty: <0.1%

**USB 2.0 high-speed transfers:**
- Up to 60 MB/s
- Working set: control buffers + active transfer buffers (~512 KB)
- ~4 IOTLB entries
- Hit rate: 100%
- Penalty: <0.1%

**SD card / eMMC DMA:**
- Variable rate, ~50-300 MB/s
- One DMA buffer per active transfer
- ~2 IOTLB entries
- Hit rate: 100%
- Penalty: <0.1%

**All four simultaneously active:** ~16 IOTLB entries, fits in a 32-entry IOTLB with headroom. No misses in steady state.

## 6. Relationship to Phase 1 MMU

The IOMMU and CPU MMU are independent but architecturally related:

| Aspect | CPU MMU (Phase 1) | IOMMU (Phase 2) |
|--------|-------------------|-----------------|
| Page sizes | 4 KB – 1 GB via PageMask | Same encoding |
| Translation cache | 32-entry TLB per CPU | 64-entry IOTLB shared |
| Context tagging | 12-bit ASID per process | 8-bit BMID per device |
| Miss handling | Trap to software TSB walker | Block + fault IRQ |
| Page table walker | None (software-loaded) | None (software-loaded) |
| Future virt support | ASID partitioning (12-bit space) | BMID partitioning (8-bit space) |
| Register interface | SH-4 style P4 MMIO | Independent P4 MMIO block |

Sharing the page-size encoding means the kernel's superpage logic is reused between CPU and IOMMU. Sharing the philosophical "no hardware walker, software writes the translation cache" approach means both translation units have similar fault-handling code paths and similar performance characteristics.

The two units do **not** share physical hardware — the CPU TLB and the IOTLB are separate physical structures. There is no cross-pollination of entries.

## 7. Memory Isolation Guarantees

With the IOMMU enabled and all DMA-capable devices not in bypass:

- **Device-to-kernel isolation:** A device can only access memory the kernel has explicitly mapped to its BMID. Kernel data structures are unreachable from devices.
- **Device-to-device isolation:** Two devices cannot access each other's mappings
  unless the kernel deliberately shares an IOVA range **by installing one entry per
  sharing BMID**, which names the sharers and costs one entry each.
- **Permission enforcement:** Per-entry R/W bits prevent write-only buffers from being read or read-only buffers from being written.
- **Cache coherency:** **not a guarantee of this block.** See §7.1 below.

> **The device-to-device bullet previously ended** *"(or uses the `GLOBAL` bit for a
> genuinely-shared buffer)"*, and the cache-coherency bullet previously read
> *"Per-entry CACHEABLE bit controls whether the transaction snoops CPU caches.
> Configurable per-buffer."* The first is withdrawn by
> [hardware-spec.md §3.10](hardware-spec.md) `I-R5` — a bit that matches *every*
> BMID cannot express "a genuinely-shared buffer", it expresses "shared with
> everything, including whatever device is attached next" — and the second by [`I-R9`](hardware-spec.md),
> because the IOMMU has no path to any cache.

These guarantees are equivalent to user-process isolation in the CPU MMU **and are
scoped to masters that reach memory through the IOMMU.** A master with a private path
— [hardware-spec.md §3.10](hardware-spec.md)'s bypass path 7 — is outside them, and
an integration that adds one must say so.

### 7.1 What this block does not guarantee

- **Coherence with CPU caches**, in either direction. [`I-R9`](hardware-spec.md);
  [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md).
- **A bus error on a blocked transaction.** The master is told nothing; it reads
  zeros. [`I-R2`](hardware-spec.md).
- **Anything about a master it does not see.** Bypass path 7.
- **Freedom from cross-BMID denial of service** unless the IOTLB quota [`I-R8`](hardware-spec.md) is
  implemented — the isolation is of *access*, not of *capacity*.

## 8. Out of Scope

Not addressed in this phase:

- **Two-stage I/O translation (guest IOVA → host IOVA → PA):** Phase 3 achieves equivalent isolation via per-BMID single-stage translation, where the hypervisor owns the IOMMU page tables and pre-resolves guest IOVA → host PA. No hardware second stage.
- **I/O page faults / demand paging from devices:** Linux drivers pre-map; no support for devices that page-fault.
- **PCIe ATS / PRI:** No PCIe in current j-core SoC targets.
- **Hardware-walked page tables:** Explicitly rejected (see §3.1).
- **DMA window / "translation domains" beyond per-BMID grouping:** A single device gets its own BMID and its own slice of IOVA space; not a generalized domain abstraction.

If any of these become required, they'd be additive — they don't conflict with the Phase 2 design.

## 9. References

- UltraSPARC I/II User's Manual, Sun Microsystems, 1997 (DVMA controller chapters)
- "The Sun4M System Architecture", Sun Microsystems, 1991 (original IOMMU design)
- Linux IOMMU subsystem documentation (`Documentation/iommu/`)
- Linux DMA-API documentation (`Documentation/core-api/dma-api.rst`)
- Phase 1 MMU design spec (`01-design-spec.md`)
