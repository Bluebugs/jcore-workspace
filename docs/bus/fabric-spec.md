# J-Core SoC Bus Fabric — Specification

**Status:** Convention spec (v1). This document defines the interface contracts and behavioral guarantees of the J-Core SoC interconnect. It is the single source of truth for the fabric properties that other specs (IOMMU, L2 v2, hypervisor, FGMT) silently depend on.

**Audience:** Anyone writing or reviewing a J-Core hardware spec that talks to the SoC bus; SoC integrators; reviewers of the IOMMU / cache / hypervisor specs that delegate fabric-level rules here.

**Out of scope:** Concrete RTL. A future `docs/bus/hardware-impl.md` will pin a particular crossbar/ring implementation; this document specifies only the contracts that any conformant implementation must satisfy.

---

## Changelog

- **v1** (initial): Tiered convention spec. Formalises BMID assignment at the master port, AXI-style transaction-ID semantics, ordering rules, snoop-bus contract, and reset/boot conventions for the existing J-core SoC.

---

## 0. Tier Structure

The fabric is specified in **four tiers**, following the project convention used in [fpu/spec.md](../fpu/spec.md), [simd/spec.md](../simd/spec.md), and [cache/l2-spec.md §0](../cache/l2-spec.md). Tier tags appear on every section heading; where a section applies to all tiers it is tagged `[T0/T1/T2/T3]`, and where it is tier-specific it carries only the introducing tier(s).

| Tier | Name                              | Masters | BMID enforced | Snoop bus | `ADDR_WIDTH` | Product points          | Status        |
|------|-----------------------------------|---------|---------------|-----------|--------------|-------------------------|---------------|
| T0   | Baseline AXI-lite crossbar        | 1–2     | implicit per port | no    | 32           | J2, J3, J32 (no hypervisor) | shipping-equivalent (matches today's `cpumreg`) |
| T1   | BMID-enforced + IOMMU-aware       | ≥2      | yes, tagged at master port | no | 32         | J32 with IOMMU and/or hypervisor | new (this spec) |
| T2   | Coherent + snoop                  | ≥2      | yes           | yes (broadcast, ≤4 cores) | 32 or 40 | J32-OOO, J32-FM, J64 | new (this spec, normative for L2 v2) |
| T3   | Ring fabric (≥6 masters)          | ≥6      | yes           | ring-carried | 32 or 40 | future SMP product       | stub (§13)    |

Per-tier rules:

- **T0** is functionally equivalent to today's `jcore-soc/components/cpumreg`: a simple arbiter between one or two CPU cores and SDRAM/SRAM/peripherals. BMID is not transported on the bus; the IOMMU is absent or in `BMID_BYPASS` mode (see [iommu/hardware-spec.md §3.9](../iommu/hardware-spec.md)).
- **T1** adds a fabric-tagged BMID on every transaction. Tagging is performed by the **fabric, at the master port**, not by the master. This is the property the IOMMU and the hypervisor rely on for isolation. T1 does not require coherence: a single-core J32 with an IOMMU is a valid T1 deployment.
- **T2** adds a dedicated snoop-bus channel between the L2 (acting as directory) and every L1-D snoop port. T2 is required for J32-OOO and J32-FM. The snoop-ordering rules in §7 are normative for [cache/l2-spec.md §7](../cache/l2-spec.md).
- **T3** replaces the broadcast snoop bus and the request crossbar with a ring fabric built on the existing `jcore-soc/components/ring_bus/` component. **T3 is not specified in detail in this revision** — see §13.

A given SoC instantiation picks one tier. T1 is a strict superset of T0; T2 is a strict superset of T1. T3 is a re-topology of T2.

---

## 1. Scope and Cross-References `[T0/T1/T2/T3]`

This spec defines:

1. The **master-port and slave-port contract**: what signals each port presents, what fields it must drive, what ordering it must observe.
2. The **BMID assignment rule**: how the fabric tags transactions and why software cannot influence its own BMID.
3. **Transaction-ID semantics** (AXI `AxID` convention): same-ID-ordered, different-ID-may-reorder.
4. **Snoop-bus transport** for L2-driven coherence traffic in T2.
5. **Reset and boot conventions** at the fabric level, including the SMP-release register.

It does **not** define:

- The RTL of any particular crossbar, arbiter, or ring node (a future hardware-impl doc).
- The P4 MMIO address map — see [soc/p4-mmio-map.md](../soc/p4-mmio-map.md).
- The AIC2 interrupt-controller register set — see [aic/aic2-spec.md](../aic/aic2-spec.md).
- The internal microarchitecture of any IP block hanging off the fabric.

### Specs that depend on this document

| Dependent spec | Section | What it assumes about the fabric |
| -------------- | ------- | -------------------------------- |
| [iommu/hardware-spec.md §2.1](../iommu/hardware-spec.md) | Bus master tagging | The fabric attaches an 8-bit BMID to every transaction; devices cannot spoof. |
| [iommu/hardware-spec.md §4](../iommu/hardware-spec.md) | IOTLB match | BMID is delivered on the IOMMU's master interface in time for IOTLB lookup. |
| [iommu/hardware-spec.md §9](../iommu/hardware-spec.md) | Future-compat | Hypervisor extension partitions the same BMID space. |
| [iommu/design-spec.md §3.3, §3.7](../iommu/design-spec.md) | Per-device contexts; no VMID | 8-bit BMID space, fabric-assigned, partitionable in software. |
| [cache/l2-spec.md §5.2, §7](../cache/l2-spec.md) | Snoop fabric; MSI message types | A broadcast snoop bus with ordered drain; per-line in-flight ≤ 1. |
| [ooo/j32ooo-spec.md §14](../ooo/j32ooo-spec.md) | SMP | The L1-D snoop port is reachable from the L2 over the fabric's snoop channel. |
| [mmu/hardware-spec.md §8.2](../mmu/hardware-spec.md) | SMP release register | `0xFF00FF00` is a fabric-visible MMIO; held-reset cores receive no traffic. |
| [hypervisor/](../hypervisor/) | Guest isolation | Master-port BMID is hardwired; guests cannot reprogram their own ID. |
| [fgmt/dual-fgmt-proposal.md §3](../fgmt/dual-fgmt-proposal.md) | Dual-core fabric | The ring bus is the future ≥6-core option; existing `cpumreg` is T0. |
| [glossary.md §5](../glossary.md) | BMID short definition | The glossary is the short reference; this doc is the long one. |

---

## 2. Prior Art (pre-2006) `[T0/T1/T2/T3]`

Per [glossary §2](../glossary.md), every mechanism here cites pre-2006 published prior art. Nothing in this spec is novel: it is the canonical AMBA AXI contract with the well-known "per-port hardwired identifier" addition.

| Mechanism                                                | Tier        | Citation                                                                                              |
| -------------------------------------------------------- | ----------- | ----------------------------------------------------------------------------------------------------- |
| Master/slave port model, request/response separation     | T0/T1/T2/T3 | ARM AMBA AHB Specification (Rev 2.0, 1999); AMBA AXI Specification (ARM IHI 0022A, 2003)              |
| Transaction-ID (`AxID`), same-ID order / different-ID reorder | T0/T1/T2/T3 | AMBA AXI Specification (ARM IHI 0022A, 2003), §A5 (Transaction Identifiers)                           |
| Write-posting (no response required for write)           | T0/T1/T2/T3 | AMBA AXI Specification (2003), §A3.4; PCI 2.0 (1993) posted writes                                    |
| Per-port hardwired requester identifier                  | T1/T2/T3    | PCI Requester ID (PCI Local Bus Specification 2.0, 1993, §3.2.2.3.3); HyperTransport UnitID (HT 1.0, 2001) |
| Per-master isolation by hardwired source identifier      | T1/T2/T3    | SPARC v9 hypervisor ASI / sun4v context partitioning (1994 SPARC v9 manual; sun4v design 2003–2005)   |
| Broadcast snoop bus for ≤4 caches                        | T2          | SGI Challenge / MIPS R4400 (1994); Sun UE-1 (1995); Hennessy & Patterson 3rd ed. (2003) Ch. 6        |
| Directory-driven snoop fabric (L2 originated)            | T2          | SGI Origin 2000: Laudon & Lenoski, "The SGI Origin: A ccNUMA Highly Scalable Server" (ISCA 1997)      |
| Snoop ordering at a shared directory                     | T2          | Stanford DASH: Lenoski et al., "The Directory-Based Cache Coherence Protocol for the DASH Multiprocessor" (ISCA 1990) |
| Snoop ordering in a 60x-style bus protocol               | T2          | IBM PowerPC 601 bus / 60x bus protocol (MPC601 User's Manual, 1993)                                   |
| Ring interconnect for coherent fabrics                   | T3          | IBM POWER4 elastic interface ring (2001); Sun Niagara ring/crossbar (Kongetira et al., IEEE Micro 2005) |
| Parameterized physical-address width                     | T2/T3       | DEC Alpha 21264 (1998, 44-bit PA); MIPS R10000 (1996, 40-bit PA); SPARC v9 (1994, 41–44-bit PA)        |
| Reset-held secondary cores released by a primary CPU write | T0/T1/T2/T3 | SPARC v9 sun4v `cpu_start` hypercall (pre-2006); PowerPC "spin-table" boot protocol (Open Firmware, ≤2005) |
| 8-bit identifier sized to "more than any realistic SoC will have" | T1/T2/T3 | PCI Requester ID 8-bit Bus Number subfield (PCI 2.0, 1993)                                            |

No mechanism in this spec is supported by a post-2006-only citation. Contributors extending the spec MUST add a pre-2006 source for any new mechanism, or the mechanism is dropped.

---

## 3. Address Map and Routing `[T0/T1/T2/T3]`

The fabric routes by physical address. Each master port may originate transactions to any slave port; restrictions are enumerated explicitly.

### 3.1 Slave-port allocation

The baseline J-Core SoC exposes the following slave ports. Addresses are the P1/P2/P4 ranges defined by the SH-4 memory model; the per-region MMIO assignments live in the canonical [soc/p4-mmio-map.md](../soc/p4-mmio-map.md).

| Slave port                | PA range                       | Notes                                                              |
| ------------------------- | ------------------------------ | ------------------------------------------------------------------ |
| SDRAM controller          | `0x00000000` – `0x0FFFFFFF` (P0/P1/P2 alias) | Backed by `cache/dcache_mcl.vhm` interface; bulk memory.        |
| On-chip SRAM              | implementation-defined         | Per-CPU SRAM today via `cpumreg`; remains in T1 with BMID tagging. |
| AIC2 MMIO                 | `0xFF020000` – `0xFF02FFFF`    | See [aic/aic2-spec.md](../aic/aic2-spec.md).                       |
| IOMMU MMIO                | `0xFF010000` – `0xFF010FFF`    | See [iommu/hardware-spec.md §3](../iommu/hardware-spec.md).        |
| MMU per-CPU MMIO          | inside P4                      | See [mmu/hardware-spec.md](../mmu/hardware-spec.md).               |
| SMP release register      | `0xFF00FF00` (single word)     | See [mmu/hardware-spec.md §8.2](../mmu/hardware-spec.md).          |
| Peripheral register banks | inside P4 (Ethernet, SD, USB, UART, GPIO, …) | Per-peripheral; allocation in the P4 map.                |

### 3.2 Routing rules `[T0/T1/T2/T3]`

- **All-to-all baseline.** Every master can address every slave by default. The fabric MUST NOT silently drop transactions whose target is reachable.
- **DMA masters bypass the CPU MMU but go through the IOMMU.** A DMA master's request reaches the IOMMU's slave-side IOTLB-front interface; the IOMMU's master-side interface continues into the fabric with `PA` substituted for `IOVA` (or with `SLVERR` on miss, per [iommu/hardware-spec.md §2.2](../iommu/hardware-spec.md)).
- **CPU cores never bypass the IOMMU.** CPU transactions carry already-translated PA (the CPU MMU runs first); they take a direct path to slaves and skip the IOMMU. The IOMMU does not see CPU traffic.
- **Held-reset cores (§9).** The fabric MUST NOT deliver any transaction (data, snoop, interrupt vector fetch) to a CPU master port that is currently held in reset by the SMP-release register.
- **Per-region restrictions** beyond the above are out of scope here. If a future SoC integration restricts e.g. DMA access to a sub-range of SDRAM, that restriction is captured in the P4 MMIO map and enforced by the IOMMU's per-BMID tables, not by fabric routing.

### 3.3 P4 MMIO map cross-reference

The P4 region (`0xE0000000`–`0xFFFFFFFF`, per [glossary §5](../glossary.md)) is partitioned by the canonical [soc/p4-mmio-map.md](../soc/p4-mmio-map.md). This fabric spec cites specific addresses (e.g. `0xFF010000` for the IOMMU, `0xFF00FF00` for the SMP release register) without redefining them; the P4 map is the authoritative source.

---

## 4. Master-Port BMID Assignment `[T1/T2/T3]`

This is the spec's critical security primitive. The hypervisor and IOMMU both depend on the property that **a master cannot forge its own BMID**.

### 4.1 BMID is a per-port constant `[T1/T2/T3]`

The BMID is an **8-bit identifier** held in a register inside the fabric (not inside the master) at each master port. The fabric drives this register's value onto every transaction the port emits, overwriting any BMID-like field the master itself might assert. The register's value is established at SoC integration time and is one of:

- **Hardwired** (constant per port, set in the VHDL generic / netlist).
- **Fuse-controlled** (programmed once during chip personalisation).
- **Boot-time locked** (writable by trusted ROM during early reset, then locked until the next hardware reset; this option is for SoC integrators who want field-configurable port mapping).

Implementations choose one of these mechanisms per port. The choice is invisible to software running on any master; from any master's point of view, its BMID is read-only and immutable.

> Rationale: this matches PCI Requester IDs (per-port, fabric-assigned) and HyperTransport UnitIDs. It is the same property the IOMMU's design spec assumes when it says ([iommu/design-spec.md §3.3](../iommu/design-spec.md)) "the BMID is assigned by the SoC bus fabric based on the device's physical position, not by software — devices can't spoof each other."

### 4.2 Masters cannot influence their BMID `[T1/T2/T3]`

A conformant T1+ master port:

1. MUST NOT expose its BMID register to software running on the master.
2. MUST overwrite any BMID-like bits in an outgoing transaction with the port-constant value before the transaction leaves the master port toward the rest of the fabric.
3. MUST NOT accept fabric-side traffic that tries to change the port-constant BMID register (apart from the optional one-shot boot-time lock mechanism above, which is reset-domain only).

This is the property [hypervisor/](../hypervisor/) and [iommu/hardware-spec.md §2.1](../iommu/hardware-spec.md) require.

### 4.3 Reserved values `[T1/T2/T3]`

- **BMID `0x00` is reserved.** It means "untagged / bypass." The fabric MUST NOT assign BMID `0x00` to any normal master port. The only legitimate use of BMID `0x00` on the wire is by a transaction that the IOMMU sees with `BMID_BYPASS` set for source `0x00` ([iommu/hardware-spec.md §3.9](../iommu/hardware-spec.md)) — and even then only for boot-time DMA prior to IOMMU initialisation.
- **BMID `0xFF` is reserved** for diagnostic / scan-chain traffic that must never trigger an IOMMU translation. Fabric-injected debug transactions (if any) use this ID; software cannot. The IOMMU treats BMID `0xFF` as a permanent bypass.

### 4.4 BMID allocation policy `[T1/T2/T3]`

The 256-entry BMID space is partitioned by integration role. The policy is normative: tools that scan an SoC manifest for BMID conflicts assume this layout.

| BMID range        | Class                          | Notes                                                                     |
| ----------------- | ------------------------------ | ------------------------------------------------------------------------- |
| `0x00`            | Reserved (untagged / bypass)   | Boot DMA only; see §4.3.                                                  |
| `0x01` – `0x0F`   | CPU cores                      | Core *N* → BMID `0x01 + N`. Up to 15 cores.                               |
| `0x10` – `0x1F`   | On-chip DMA engines            | Ethernet MAC, SD/eMMC, USB, audio DMA, etc.                               |
| `0x20` – `0x7F`   | On-board peripherals (originating masters) | Reserved for board-integrated devices that originate bus traffic.   |
| `0x80` – `0xEF`   | Guest-owned device pass-through | Hypervisor-assigned. See [iommu/design-spec.md §3.7](../iommu/design-spec.md). |
| `0xF0` – `0xFE`   | Reserved for future expansion  | Do not allocate without updating this spec.                               |
| `0xFF`            | Reserved (diagnostic / bypass) | See §4.3.                                                                 |

### 4.5 Worked example: dual-core J32-FM with 16 guests `[T1/T2]`

```
BMID  Owner                              Class
----  ---------------------------------- ----------
0x00  (untagged, IOMMU boot bypass)      reserved
0x01  Core 0 (master port)               CPU
0x02  Core 1 (master port)               CPU
0x10  Ethernet MAC (TX+RX DMA)           on-chip DMA
0x11  SD / eMMC controller DMA           on-chip DMA
0x12  USB controller DMA                 on-chip DMA
0x80  Guest 0  pass-through device       guest
0x81  Guest 1  pass-through device       guest
0x82  Guest 2  pass-through device       guest
...
0x8F  Guest 15 pass-through device       guest
0xFF  Diagnostic / scan-chain            reserved
```

The hypervisor allocates `0x80`–`0x8F` to the 16 guests. The IOMMU's per-BMID page-table programming enforces isolation: guest *G*'s pass-through device can only DMA to memory the hypervisor has mapped for BMID `0x80 + G`. Cross-link: [iommu/design-spec.md §3.7 "No VMID field"](../iommu/design-spec.md) — guest isolation is via BMID partitioning, not via a separate VMID.

### 4.6 BMID and ASID are orthogonal `[T1/T2/T3]`

BMID identifies the **bus master**; ASID identifies the **address space within a CPU MMU** (see [glossary §5](../glossary.md)). They live in different fields, are sized differently (BMID = 8 bits, ASID = 12 bits + 4-bit generation = 16-bit `ASID_TAG`), and are consumed by different blocks (IOMMU vs CPU MMU). A CPU core has one BMID (its master port) and many ASIDs (one per current process / guest). A DMA engine has one BMID and no ASID.

---

## 5. Transaction-ID Semantics `[T0/T1/T2/T3]`

The fabric uses the AXI `AxID` convention. This is pre-2006 prior art (AMBA AXI specification, ARM IHI 0022A, 2003, §A5).

### 5.1 ID width `[T0/T1/T2/T3]`

Each master port carries a **4-bit transaction ID** (`AxID`). This gives 16 outstanding-transactions-per-master, which is sufficient for J-Core targets (J32-OOO's LSU has at most ~12 in-flight loads + ~8 stores; DMA engines never go above 8 outstanding bursts on the existing peripherals).

Implementations MAY widen this to 5 or 6 bits for a particular master port if that master genuinely needs more outstanding transactions (e.g. a future scatter-gather DMA). Widening is per-port and does not require changing the fabric — slaves see the widest ID they receive.

### 5.2 Same-ID ordering `[T0/T1/T2/T3]`

Per AMBA AXI: **transactions with the same `{BMID, AxID}` MUST complete in issue order.** Transactions with different `AxID` (even from the same master) MAY complete out of order.

The fabric uses **`{BMID, AxID}` as the global ordering key**, not `AxID` alone, because `AxID` is per-master-port-scoped. Two different masters that both choose to use `AxID = 0x3` for their critical path do not interfere — the BMID tag distinguishes them.

### 5.3 ID scoping `[T0/T1/T2/T3]`

`AxID` is **per-master-port-scoped**. A master assigns IDs from its own 4-bit space without coordinating with any other master. The fabric is responsible for routing the response back to the correct master, which it does using the full `{BMID, AxID}` tuple (the BMID is fabric-stamped per §4, so this is always available without trusting the master).

A slave does not see the BMID's role in routing — it just echoes back the `{BMID, AxID}` it received. The fabric strips the BMID at the response-arrival side and presents the master with its own `AxID` only.

### 5.4 Same-master multi-ID example `[T0/T1/T2/T3]`

A J32-OOO core may issue:

```
T1: BMID=0x01, AxID=0x0, ld r0,@(...)   ; load A
T2: BMID=0x01, AxID=0x0, ld r1,@(...)   ; load B  -- same ID as T1
T3: BMID=0x01, AxID=0x1, ld r2,@(...)   ; load C  -- different ID
```

The fabric guarantees: T1 completes before T2 (same `AxID = 0x0`). T3 may complete before, between, or after T1/T2.

This is the standard AXI rule; the core's LSU is responsible for assigning IDs such that load–load and store–store ordering required by SH semantics is preserved (typically one ID per outstanding cache line, or one ID per dependency chain).

---

## 6. Ordering Rules `[T0/T1/T2/T3]`

### 6.1 Within a master `[T0/T1/T2/T3]`

By transaction ID, per AXI (§5.2). No cross-ID ordering is guaranteed by the fabric. The master's own logic (or the CPU's LSU memory-ordering model) is responsible for choosing IDs that preserve required ordering.

### 6.2 Across masters `[T0/T1/T2/T3]`

**No ordering** by default. Two masters that issue concurrently see no inter-master ordering from the fabric. Where cross-master ordering is required (e.g. CPU producer / DMA consumer), the producer issues a fence or polls a software-visible flag in coherent memory; the fabric does not synthesize ordering.

### 6.3 Coherence-protocol messages `[T2]`

Cache-line-granularity ordering is enforced by the L2 directory (see [cache/l2-spec.md §7](../cache/l2-spec.md) message types and §7.5 transitions). The fabric merely **transports** coherence messages; it does not interpret them. The L2's per-line in-flight tracking (one snoop in flight per line, see §7) is what enforces single-writer / atomic-snoop semantics.

### 6.4 MMIO writes `[T0/T1/T2/T3]`

- **MMIO writes are posted** by default: the fabric returns write-completion to the master as soon as the write enters the fabric, not when it reaches the slave. This matches AXI's write-posting rule (AMBA AXI 2003, §A3.4) and PCI 2.0 posted writes (1993).
- **Slaves that require non-posted writes** (e.g. AIC2 IPI write where the master needs an ack-when-delivered to avoid races) declare themselves non-posted at integration time, and the fabric withholds write-completion until the slave responds. The AIC2 spec (forthcoming) is the canonical example.
- **Read-after-write to the same MMIO address from the same master IS ordered.** That is, a read by master *M* to address *A* issued after a write by *M* to *A* MUST observe the write (or a value at least as new). This is the standard AXI guarantee for the same `{BMID, AxID}` pair, and slaves that present non-posted writes naturally inherit it.

### 6.5 Cache-line accesses `[T2]`

Governed by the L2 v2 MSI protocol ([cache/l2-spec.md §7](../cache/l2-spec.md)). The fabric carries the request/response messages; the L2 enforces the ordering and state-machine transitions. Same-line atomicity is via the per-L2-line lock ([cache/l2-spec.md §6](../cache/l2-spec.md)), which is invisible to the fabric.

### 6.6 Summary table `[T0/T1/T2]`

| Scenario                                            | Ordering source                                  |
| --------------------------------------------------- | ------------------------------------------------ |
| Same-master, same-AxID                              | Fabric (AXI rule)                                |
| Same-master, different-AxID                         | None — master responsible                        |
| Different-master, same-slave                        | None — software / IPI / shared-memory flag       |
| Cache-line miss/fill                                | L2 directory (T2 only)                           |
| Same-line CAS.L                                     | L2 line-lock (T2 only)                           |
| MMIO read-after-write, same master, same address    | Fabric (per-AxID rule)                           |
| MMIO read-after-write, same master, different address | None — software fence required (rare in J-Core) |

---

## 7. Snoop Bus `[T2]`

The snoop bus is a **separate set of wires** from the regular data/address bus. It carries L2-originated coherence messages to per-core L1-D snoop ports and per-core ACK/Wb responses back to the L2.

### 7.1 Source and destination `[T2]`

- **Source (driver):** the L2's directory / snoop driver, as specified in [cache/l2-spec.md §5.2](../cache/l2-spec.md). The L2 is the single originator of snoop traffic; cores never originate snoops.
- **Destination:** every CPU's L1-D snoop port. The L1-D snoop-port signal type is `dcache_snoop_io_t` from `jcore-cpu/cache/dcache.vhd` (the `sa`/`sy` ports — already a first-class concept in the J2 design).

### 7.2 Per-cycle contract `[T2]`

- One snoop message is broadcast to all L1-Ds per cycle. The L2's target mask (from the directory's `dir_vec`) selects which L1-Ds respond; non-targeted L1-Ds drop the message.
- Affected L1-Ds respond with a state transition (M → S, M → I, S → I) and, if the previous state was Modified, a writeback (`Wb` message) carrying the line data.
- The set of L2 → L1-D message types is normative in [cache/l2-spec.md §7.4](../cache/l2-spec.md) (`Inv`, `Downgrade`, `Recall`, `DataResp`); the snoop bus is the transport for those types whose direction is `L2 → L1-D`.

### 7.3 Latency `[T2]`

Baseline for `NUM_CORES ≤ 4`:

- **1 cycle drive** — L2 places the snoop on the broadcast bus.
- **1 cycle response** — targeted L1-Ds present their ACK (and Wb data if applicable) on the response bus.

Total snoop-round-trip is 2 cycles when no contention. The L2's arbiter prioritises snoop traffic (see [cache/l2-spec.md §5.3](../cache/l2-spec.md)).

### 7.4 Snoop ordering `[T2]`

The fabric's snoop bus is a **single-driver, ordered** channel: snoops drain from the L2 in the order the L2 emits them. Concretely:

- The L2 maintains a per-line **in-flight snoop count** and MUST hold this count at most **1** per line: only one outstanding snoop targeting a given physical line address may be in flight on the snoop bus at any time. The next snoop to that line is held in the L2 arbiter until the previous one's ACK/Wb returns.
- Across different lines, snoops drain in the order the L2 emits them. L1-Ds MUST process snoops in arrival order.
- An L1-D that issued a `GetS`/`GetM`/`Upgrade`/`GetM-Locked` to the L2 MUST be prepared to receive a snoop targeting the same line while its request is still pending. The L1-D resolves this per the L2 spec's state-transition table ([cache/l2-spec.md §7.5](../cache/l2-spec.md)).

> Rationale: the single-snoop-per-line invariant is the property that lets the L2 directory be **exact**. Two concurrent snoops to the same line could let an L1-D miss one of them, breaking the directory's invariant that `dir_vec` reflects all L1-D copies.

### 7.5 Backpressure and overflow `[T2]`

L1-D snoop ports have a small ACK FIFO (depth ≥ 2; sized in the L1-D RTL). The L2 arbiter MUST NOT issue a new snoop to a core whose ACK FIFO is full. If the ACK FIFO fills (e.g. because the L1-D's snoop processing pipeline is briefly stalled), the L2 stalls the snoop bus and prioritises drain.

### 7.6 Reference `[T2]`

Full coherence protocol on top of this transport: [cache/l2-spec.md §7](../cache/l2-spec.md). The fabric specifies the *transport*; the L2 spec specifies the *protocol*.

---

## 8. SoC-Level Integration with Existing J-Core Blocks `[T0/T1/T2]`

The fabric must compose cleanly with the existing J-core implementation. This section maps the spec onto concrete files in `jcore-cpu/` and `jcore-soc/` so an integrator can read the spec and the code together.

### 8.1 CPU bus types `[T0/T1/T2]`

The CPU's bus interface is defined by `jcore-cpu/cpu2j0_pkg.vhd`, which declares:

- `cpu_data_o_t` / `cpu_data_i_t` — the data-side request/response signal record carrying `a` (address), `d` (write data), `wr` (write enable), `rd` (read enable), plus byte-strobe and acknowledge fields.
- `cpu_instruction_*_t` — the instruction-side equivalents.

A **T0** fabric is a thin wrapper around these record types: the fabric is essentially the same arbiter as today's `cpumreg`, demultiplexing CPU requests to SDRAM / SRAM / peripheral slaves. No new CPU-side signals are required at T0.

A **T1** fabric adds an 8-bit BMID field at each master port. The BMID is **not added to the CPU-side `cpu_data_o_t` record** — the CPU still drives only address/data/strobes. The BMID is asserted by the fabric's master-port-adapter logic, between the CPU's bus output and the fabric's internal channel. This is what guarantees the CPU cannot influence its own BMID (§4.2).

A **T2** fabric additionally exposes the L1-D's snoop port to the L2's snoop bus. The L1-D snoop-port signal type already exists as `dcache_snoop_io_t` (see [cache/l2-spec.md §5](../cache/l2-spec.md)); the T2 fabric wires it to the L2's `snoop_bus_*` channels.

### 8.2 The existing `cpumreg` arbiter `[T0]`

`jcore-soc/components/cpumreg.vhm` is the existing per-CPU-master register / arbiter. It implements a T0-equivalent fabric for one or two cores: round-robin arbitration between the two CPU master ports for SDRAM access, plus per-CPU SRAM windows.

The T1 generalisation **wraps `cpumreg`** rather than replacing it: a thin BMID-tagging layer sits between each CPU's `cpu_data_o_t` output and `cpumreg`'s input; the IOMMU (when present) sits between `cpumreg`'s SDRAM-side output and the SDRAM controller. The T1 fabric remains arbiter-based for ≤4 masters.

### 8.3 The existing dual-CPU target `[T0]`

`jcore-soc/targets/cpus_two_fpga.vhd` is the existing dual-core target, instantiating two CPUs through `cpumreg`. The same target file is the starting point for a **T1 dual-core J32**: re-target it to instantiate the T1 master-port wrappers (assigning BMIDs `0x01` and `0x02` per §4.4) and the IOMMU between `cpumreg` and SDRAM. See [fgmt/dual-fgmt-proposal.md §3](../fgmt/dual-fgmt-proposal.md) for the parallel discussion in the FGMT context.

### 8.4 The memory-clock-layer interface `[T0/T1/T2]`

`jcore-cpu/cache/dcache_mcl.vhm` is the cache's memory-clock-layer interface to SDRAM. The fabric's **slave-side SDRAM port** speaks this protocol on T0 and T1 unchanged. On T2 the L2 sits between the per-core L1-Ds and the mcl interface (per the L2 spec); the fabric's slave-side SDRAM port becomes the L2's downstream port, still speaking mcl.

### 8.5 The ring-bus component `[T3]`

`jcore-soc/components/ring_bus/` (with `node.vhm`, `ring_bus_pkg.vhd`, etc.) is the existing ring-bus IP. It is the candidate T3 fabric — see §13. It is **not used at T0/T1/T2**.

---

## 9. Reset and Boot `[T0/T1/T2/T3]`

### 9.1 Reset `[T0/T1/T2/T3]`

On hardware reset:

- All master ports quiesce: no in-flight transactions on any master-side or slave-side channel.
- All slaves return to their architectural reset state (defined per-slave; e.g. IOMMU reset state per [iommu/hardware-spec.md §8](../iommu/hardware-spec.md), MMU reset state per [mmu/hardware-spec.md §9](../mmu/hardware-spec.md)).
- The fabric's BMID-tag registers (per §4.1) reload their hardwired/fused values.
- Snoop-bus FIFOs (T2) drain to empty.

### 9.2 Boot `[T0/T1/T2/T3]`

- **CPU 0 wakes** at the reset vector (typically `0xA0000000` = P2 entry, uncached; per [mmu/hardware-spec.md §9](../mmu/hardware-spec.md)).
- **CPU 1..N-1 are held in reset.** The fabric MUST NOT deliver any bus traffic — neither data nor snoops nor interrupts — to a held-reset core. Specifically, the master port for a held core is gated off (no requests accepted from it; no snoops driven to its L1-D; no interrupt vector fetches routed back to it).
- CPU 0 initialises the SoC (SDRAM controller, IOMMU bypass map, AIC2) and then writes the **SMP release register** at `0xFF00FF00` (per [mmu/hardware-spec.md §8.2](../mmu/hardware-spec.md)) to release secondary cores. Writing bit *n* releases core *n*.
- The release is a **fabric-visible event**: when bit *n* transitions from 0 to 1, the fabric un-gates master port *n* and the snoop bus begins delivering messages to core *n*'s L1-D. The fabric MUST NOT release a core that the SMP release register has not yet released.

> Cross-reference: [mmu/hardware-spec.md §8.2](../mmu/hardware-spec.md) defines the register layout (`[N-1:0] CPU_RELEASE`, write-1-to-release). This fabric spec defines the fabric-side semantics that the register triggers.

### 9.3 Reset of a single master `[T1/T2/T3]`

Some integrations support resetting an individual DMA master (e.g. a misbehaving Ethernet controller). The fabric MUST quiesce that master's port before reset is applied (drop new requests, wait for in-flight responses to drain or time out) and MUST drop any responses arriving for the master during the reset window. This avoids dangling transactions corrupting state at the master's L1 / fabric adapter.

---

## 10. Address Width `[T0/T1/T2/T3]`

Per the project-wide rule (same pattern as [cache/l2-spec.md §0](../cache/l2-spec.md) and the OoO / MMU specs), the fabric's address width is parameterized:

```
ADDR_WIDTH ∈ {32, 40}
```

- **T0 and T1 may instantiate either width.** Today's shipping J2/J3 are 32-bit; a J32 with an IOMMU may want 40-bit if the SoC integrates >4 GB of DRAM (rare today, plausible in 5 years).
- **T2 may instantiate either width.** J32-OOO and J32-FM are 32-bit (matching their L2 spec baseline); J64 mandates 40-bit.
- **T3 (future) likewise scales.**

Address-bearing fields in the fabric — request address (`AxADDR`), response error address, snoop address — all carry `ADDR_WIDTH` bits. Where the IOMMU translates from a 36-bit IOVA to a 32/40-bit PA, the IOMMU's master interface produces the fabric's `ADDR_WIDTH`-bit value, with high-bit zero-extension when `ADDR_WIDTH = 40` and the PA is in the 32-bit-mapped range.

Master ports that emit narrower addresses than `ADDR_WIDTH` (e.g. a 32-bit CPU core in an `ADDR_WIDTH = 40` fabric) zero-extend before the BMID-tag layer.

---

## 11. Conformance Summary `[T0/T1/T2/T3]`

A SoC integration claiming conformance to a tier MUST satisfy all of the following:

**T0:**

- (T0-1) Every master port presents a request/response interface compatible with `cpu_data_o_t`/`cpu_data_i_t` semantics or AXI(-lite).
- (T0-2) Same-`AxID` ordering preserved (§5.2).
- (T0-3) MMIO write-posting per §6.4.
- (T0-4) Reset and boot per §9.

**T1** = T0 +:

- (T1-1) 8-bit BMID per master port, fabric-assigned per §4.1, immutable from the master per §4.2.
- (T1-2) BMID allocation policy per §4.4 (or a documented per-SoC exception, captured in the SoC's integration manifest).
- (T1-3) IOMMU slave-side interface receives BMID in time for IOTLB lookup ([iommu/hardware-spec.md §2.1, §4](../iommu/hardware-spec.md)).
- (T1-4) Held-reset cores receive no fabric traffic (§9.2).

**T2** = T1 +:

- (T2-1) Snoop bus per §7, with single-snoop-per-line invariant (§7.4).
- (T2-2) L2 directory is the single snoop driver (§7.1).
- (T2-3) Snoop ACK / Wb response channel with backpressure (§7.5).
- (T2-4) Coherence message types as enumerated in [cache/l2-spec.md §7.4](../cache/l2-spec.md) carried by the snoop and request/response channels.

**T3** — out of scope for this revision; see §13.

---

## 12. Open Questions

Items deferred to a future revision of this spec or to a hardware-impl doc:

1. **Concrete crossbar vs ring decision for T2 with 4 cores.** A 4-core J32-FM might still use a broadcast snoop bus (the T2 baseline) or might benefit from a small ring. The L2 spec leaves the choice to the fabric ([cache/l2-spec.md §5.2](../cache/l2-spec.md)); this spec inherits the deferral.
2. **Non-posted-write declaration mechanism.** §6.4 says slaves that need non-posted writes "declare themselves at integration time"; the mechanism is per-integration today. A future revision may standardise a per-slave-port flag.
3. ~~**AIC2 IPI delivery path.**~~ **Resolved** in [aic/aic2-spec.md §3.5](../aic/aic2-spec.md) (and §4.4 for the FGMT extension): `IPI_SEND[target]` is the canonical non-posted MMIO write; the `aic_com` bus carries the inter-AIC message; the fabric withholds write-completion until the target AIC2 acks. The hyperprivileged virtual-interrupt-injection equivalent (`VINJ_SEND`) is at [aic/aic2-spec.md §5.3](../aic/aic2-spec.md).
4. **Per-master quiescence interface.** §9.3 calls for individual master reset; the specific control register and wait-for-drain timeout are integration-defined.
5. **BMID-to-physical-port discovery from software.** Currently the only way for software (e.g. the hypervisor or Linux IOMMU driver) to learn the BMID of a given device is through a board-specific table (device tree, SoC manifest). A future revision may add a fabric-discoverable BMID-map MMIO region.

None of these block T0/T1/T2 specification or integration.

---

## 13. T3 — Ring Fabric (stub) `[T3]`

For SoCs with ≥6 master ports (≥6 CPU cores, or a 4-core SMP plus a heavy DMA mix), the broadcast snoop bus and the central arbiter become the bottleneck. The intended replacement is a ring fabric built on the existing `jcore-soc/components/ring_bus/` component (`node.vhm`, `ring_bus_pkg.vhd`, the per-node insertion logic in `node8b.vhmh` / `node9b.vhmh`).

T3 is **not specified in detail in this revision.** A future spec will define:

- Ring node-port BMID tagging (same property as §4, but at ring-node ingress rather than at a crossbar master port).
- Ring-carried snoop ordering (ring is naturally ordered around the loop, but cache-line ordering across nodes requires explicit coherence-fence messages — see IBM POWER4 / Sun Niagara prior art in §2).
- Reset/boot in the ring topology.

Until that spec lands, ≥6-core J-Core integrations should be treated as research.

Prior art for T3 mechanisms is already in the §2 table (POWER4 elastic ring, Niagara). The same pre-2006 rule applies to anything added in the future T3 spec.

---

## 14. Index of Cross-Doc Updates Driven by This Spec

When this spec lands, the following sister-doc edits are required for consistency:

| Doc | Section | Change |
| --- | ------- | ------ |
| [iommu/hardware-spec.md §2.1](../iommu/hardware-spec.md) | Bus master tagging | Add a cross-link to `docs/bus/fabric-spec.md §4` as the canonical BMID source. |
| [iommu/design-spec.md §3.3](../iommu/design-spec.md) | Per-device contexts via BMID | Add a cross-link to `docs/bus/fabric-spec.md §4` for the BMID space and assignment policy. |
| [cache/l2-spec.md §7](../cache/l2-spec.md) | Coherence Protocol — MSI | Add a sentence pointing at `docs/bus/fabric-spec.md §7` for the snoop-bus transport rules. |
| [glossary.md §5](../glossary.md) | BMID entry | Add "see [bus/fabric-spec.md §4](bus/fabric-spec.md) for the authoritative definition." |

These edits are landed in the same change as this spec.
