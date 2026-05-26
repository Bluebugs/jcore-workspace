# J-Core AIC2 Interrupt Controller — Specification

**Status:** Convention spec (v1). This is the single source of truth for the J-Core AIC2 (Advanced Interrupt Controller, version 2): the baseline that exists today in `jcore-soc/components/misc/aic2.vhm`, the FGMT extension required by [J2-MT2x2](../fgmt/dual-fgmt-proposal.md) and the OoO product points ([J32-OOO / J32-FM](../ooo/j32ooo-spec.md)), and the virtualization layer required by the [J-Core hypervisor](../hypervisor/hardware-spec.md).

**Audience:** SoC integrators wiring up interrupt sources; CPU and front-end designers consuming `cpu_event_i_t`; hypervisor authors implementing `jcore_vintc`; Linux `irq-jcore-aic` maintainers.

**Out of scope:** Concrete RTL. The shipping `aic2.vhm` already implements Tier 0; this spec describes the *contract* the file satisfies (and the Tier 1/Tier 2 additions a future revision must satisfy). The MMIO base address `0xFF020000` is allocated normatively in the canonical [P4 MMIO map](../soc/p4-mmio-map.md); register offsets within the AIC2 block are normative in this document.

---

## Changelog

- **v1** (initial): Three-tier formalisation. Tier 0 documents the existing shipping AIC2. Tier 1 specifies the FGMT extension (per-(core, thread) routing, per-TC pending bundle for the OoO ready-thread arbiter). Tier 2 specifies the hypervisor virtualization layer (per-source guest ownership, HS-mode delivery, virtual-interrupt injection MMIO, `jcore_vintc` Linux paravirt model).

---

## 0. Tier Structure

The AIC2 is specified in **three tiers**, following the project convention used in [fpu/spec.md](../fpu/spec.md), [simd/spec.md](../simd/spec.md), [cache/l2-spec.md §0](../cache/l2-spec.md), and [bus/fabric-spec.md §0](../bus/fabric-spec.md). Tier tags appear on every section heading.

| Tier | Name                              | Per-CPU instance | Per-TC delivery | Hyp virtualization | Product points          | Status        |
|------|-----------------------------------|------------------|-----------------|--------------------|-------------------------|---------------|
| T0   | Baseline AIC2                     | yes (`cpuid`)    | no (per-core)   | no                 | J2, J3, J32             | shipping (`jcore-soc/components/misc/aic2.vhm`) |
| T1   | FGMT-aware delivery               | yes (`cpuid`, `n_tc`) | yes (per `(core, thread)`) | no | J2-MT2x2, J32-OOO, J32-FM | new (this spec) |
| T2   | Hypervisor virtualization         | yes              | yes             | yes (`GUEST_OWNED`, vCPU target, injection) | J32-FM | new (this spec, normative for `jcore_vintc`) |

Per-tier rules:

- **T0** is functionally equivalent to the existing `aic2.vhm`: per-CPU instance, flat source vector, per-source enable / pending / priority / target-CPU, IRL output to the CPU's `cpu_event_i_t`, inter-AIC `aic_com` bus for IPIs. Required for any J-Core SoC with more than two interrupt sources.
- **T1** adds per-(core, thread-context) targeting. A T1 implementation with `n_tc = 1` is behaviourally identical to T0 and exposes the same MMIO ABI; with `n_tc = 2` each source's target field widens by one bit, IPIs may target a specific TC, and a new per-TC pending bundle wires to the OoO front-end's ready-thread arbiter ([../ooo/j32ooo-spec.md §13.2](../ooo/j32ooo-spec.md)).
- **T2** adds hyperprivileged-only registers — per-source `GUEST_OWNED` flag, per-source guest-vCPU target, virtual-interrupt injection MMIO, delivery-pending event to the hypervisor — and a delivery layer that routes guest-owned interrupts directly to a running guest vCPU when safe, or traps to HS-mode otherwise. Built on top of [HEDR](../hypervisor/hardware-spec.md) (`hypervisor/hardware-spec.md §2.3`) and the SR.HPRIV mode bit (§2.1).

T2 is a strict superset of T1; T1 is a strict superset of T0. A given SoC instantiation picks one tier.

---

## 1. Scope and Cross-References `[T0/T1/T2]`

### 1.1 What this spec defines

1. The **per-source register set** (enable, pending, priority, target) and its MMIO layout in P4.
2. The **delivery contract** to the CPU's `cpu_event_i_t` (IRL output, vector number, ack/clear semantics).
3. The **inter-AIC `aic_com` bus** carrying IPI messages between per-core AIC2 instances.
4. The **FGMT extension** (`n_tc` generic; per-TC target; per-TC pending bundle).
5. The **hypervisor virtualization layer** (`GUEST_OWNED`, guest-vCPU target, HS-mode delivery rules, virtual-interrupt injection MMIO, `jcore_vintc` ABI).

### 1.2 What this spec does NOT define

- The concrete number of interrupt sources (parameterized; see §10 open question).
- The RTL — the shipping `aic2.vhm` is the reference T0 implementation.
- The P4 MMIO base address — allocated normatively in the canonical [P4 MMIO map](../soc/p4-mmio-map.md). AIC2 occupies `0xFF020000`–`0xFF02FFFF` (64 KB) per that map.
- Linux driver internals beyond the ABI surface (`drivers/irqchip/irq-jcore-aic.c` is the in-tree implementation).

### 1.3 Specs that depend on this document

| Dependent spec | Section | What it assumes about AIC2 |
| -------------- | ------- | -------------------------- |
| [fgmt/dual-fgmt-proposal.md §5.3](../fgmt/dual-fgmt-proposal.md) | Per-thread interrupts | T1 — per-`(core, tc)` IPI; AIC2 carries `TC_ID` on `cpu_event_i_t`. |
| [fgmt/mt2x2-plan.md](../fgmt/mt2x2-plan.md) Phase 3 | Linux 4-CPU SMP | T1 — `aic_com` carries per-TC IPI vectors. |
| [ooo/j32ooo-spec.md §12](../ooo/j32ooo-spec.md) | PMU overflow interrupt | Per-core PMU drives a dedicated AIC2 source line. |
| [ooo/j32ooo-spec.md §13.4](../ooo/j32ooo-spec.md) | SLEEP wakeup | T1 — per-TC pending bundle unparks the SLEEPing thread. |
| [cache/l2-spec.md §13.5](../cache/l2-spec.md) | L2 PMU events | Counter overflow routed through the per-core PMU, not directly. |
| [iommu/hardware-spec.md §3.1, §3.6](../iommu/hardware-spec.md) | `FAULT_IRQ_EN` | One dedicated AIC2 source per IOMMU instance. |
| [mmu/hardware-spec.md §8.2, §8.3](../mmu/hardware-spec.md) | SMP release; wake routing | AIC2 holds IRL=0 for held-reset cores; wake interrupts default to CPU 0. |
| [bus/fabric-spec.md §3, §6.4](../bus/fabric-spec.md) | AIC2 MMIO slave | AIC2 sits at a fabric slave port; IPI writes are non-posted. |
| [hypervisor/hardware-spec.md §4](../hypervisor/hardware-spec.md) | HS-mode delivery | T2 — virtualized interrupts respect HEDR and SR.HPRIV. |
| [hypervisor/linux-spec.md §3.2](../hypervisor/linux-spec.md) | `jcore_vintc` | T2 — Linux guest sees AIC2-compatible MMIO. |
| [hypervisor/design-spec.md §3.7](../hypervisor/design-spec.md) | 4-bit guest-id | T2 — guest-vCPU target field aligns with ASID partitioning. |

---

## 2. Functional Model `[T0/T1/T2]`

### 2.1 Block diagram

```
                                       AIC2 (per-CPU instance, cpuid = N)
                                       +--------------------------------------------+
   peripheral IRQs[K] ----------------> |                                            |
   IOMMU fault       ----------------> |  Source state arrays:                      |
   PMU overflow      ----------------> |    PEND[S]   ENABLE[S]                     |
   Timer             ----------------> |    PRIO[S]   TARGET[S]  ETRIG[S]           |
   IPI receive (from aic_com)  ------> |    (T1) TC_TARGET[S]                       |
                                       |    (T2) GUEST_OWNED[S]  GVCPU_TARGET[S]    |
                                       |                                            |
                                       |             ↓ (priority encoder)           |
                                       |                                            |
                                       |   Highest-prio pending+enabled source --+  |
                                       |                                         |  |
                                       |   IRL_level (4 bits)  ←  PRIO[winner]   |  |
                                       |   IRL_vector (8 bits) ←  source number  |  |
                                       |   IRL_tc (T1, log2(n_tc) bits) ← TC_TGT  |  |
                                       |                                         |  |
                                       |   (T2) delivery-mode FSM:               |  |
                                       |        if !GUEST_OWNED[w]: deliver to    |  |
                                       |                            host (HEDR=0)|  |
                                       |        elif gvcpu running here & MD=1:  |  |
                                       |                            deliver to vCPU |
                                       |        else: raise HS-delivery-pending  |  |
                                       |                                         ↓  |
                                       |   ──────────────  cpu_event_i_t  ──────→ CPU
                                       |                                            |
                                       |   aic_com_o  ───→  peer AIC2[*]            |
                                       |   aic_com_i  ←───  peer AIC2[*]            |
                                       |                                            |
                                       |   MMIO slave port  ←───  SoC fabric        |
                                       +--------------------------------------------+
```

`S` is the parameterized source count (recommended 64 or 128; see §10).

### 2.2 Signal interfaces

- **`cpu_event_i_t`** — the CPU's event input record (declared in `jcore-cpu/cpu2j0_pkg.vhd`). AIC2 drives `irq_level` (4 bits, 0=no irq, 15=highest), `vector_number` (8 bits, the source identifier the CPU presents to its trap handler), and on T1 an additional `tc_target` field (log2(`n_tc`) bits) selected by the front-end thread arbiter.
- **`cpu_event_o_t`** — the CPU's event output record (ack, sleep-state, etc.). AIC2 latches the CPU's interrupt-accept pulse to clear edge-triggered pending bits.
- **`aic_com_o` / `aic_com_i`** — the inter-AIC bus. Already present today. Carries IPI messages between AIC2 instances. Message format in §3.5.
- **Direct source lines** — one wire per peripheral IRQ + dedicated wires for PMU overflow (per-core, [§6](#6-integration-with-the-bus-fabric)) and IOMMU fault (one per IOMMU).
- **MMIO slave port** — connects to the SoC fabric per [bus/fabric-spec.md §3](../bus/fabric-spec.md). AIC2 registers are accessed by CPU writes (and by hyperprivileged code at T2) through this port. IPI writes are non-posted ([bus/fabric-spec.md §6.4](../bus/fabric-spec.md)).

### 2.3 Per-core instance

The shipping `aic2.vhm` is instantiated **once per CPU core** with a `cpuid : integer := 0` generic. Each instance is the interrupt controller for that core; it independently arbitrates pending+enabled sources targeting its `cpuid`. The inter-AIC `aic_com` bus is the only direct coupling between instances.

At T1 the generic widens conceptually to `(cpuid, n_tc)` (per [fgmt/dual-fgmt-proposal.md §5.3](../fgmt/dual-fgmt-proposal.md)). A T1 instance with `n_tc=1` is bit-compatible with T0.

At T2 each per-CPU instance gains the virtualization-layer state. There is no "hypervisor AIC2" as a separate block; the same per-CPU AIC2 has both host-visible and hyperprivileged-only register groups.

---

## 3. Tier 0 — Baseline AIC2 `[T0]`

### 3.1 Per-source state

For each of the `S` parameterized sources, AIC2 holds:

| Field      | Width | R/W | Description                                                                 |
| ---------- | ----- | --- | --------------------------------------------------------------------------- |
| `ENABLE`   | 1     | R/W | Source enable. When clear, the source is masked and never raises IRL.        |
| `PEND`     | 1     | R   | Source pending. Set by the source line (edge) or held by it (level). Cleared on CPU accept for edge sources; tracks the source line for level. Software clear via the `PEND_CLEAR` write-1-to-clear alias. |
| `PRIO`     | 3     | R/W | Priority level. `0` = disabled (equivalent to ENABLE=0); `1` = lowest; `7` = highest. Matches the 3 bits of SH-2/SH-4 IMASK (see [hypervisor/hardware-spec.md §2.1 SR.IMASK](../hypervisor/hardware-spec.md)). |
| `TARGET`   | log2(`N_cpus`) | R/W | Target CPU. Indexes which core's AIC2 will see the source. |
| `ETRIG`    | 1     | R/W | Edge-trigger select. `1` = edge-triggered (auto-clears on CPU accept); `0` = level-triggered (held while source asserts). |

Total per-source bookkeeping at T0: ~7+`log2(N_cpus)` bits.

### 3.2 MMIO map

AIC2 occupies the P4 range `0xFF020000` – `0xFF02FFFF` (64 KB) per the canonical [P4 MMIO map](../soc/p4-mmio-map.md) §3. The 64 KB encodes per-CPU sub-banks (see §3.5 below). The base sits immediately after the [IOMMU at `0xFF010000`](../iommu/hardware-spec.md) and before peripherals.

Per-CPU instance layout (with `cpuid`-aware decoding inside the AIC2 — each core sees only its own register file when addressing the base address):

```
AIC2_BASE = 0xFF020000

Offset    Bytes  Name              R/W  Description
------    -----  ----              ---  -----------
0x0000    4      AIC2_CAPS         R    Capability register. See §3.3.
0x0004    4      AIC2_CPUID        R    cpuid generic value (the AIC2 instance's owning core).
0x0008    4      AIC2_STATUS       R    Current IRL level (low 4 bits) + winning vector (next 8 bits).
0x000C    4      AIC2_ACK          W    Software-side accept (rarely used; the CPU auto-acks).

0x0100 + S*4   ENABLE[S]            R/W  One word per source: bit 0 is the enable.
               (recommended packed: ENABLE_BITMAP at 0x0100, 32 bits per word, S/32 words.)
0x0200 + S*4   PEND[S]              R    Pending bits, packed.
0x0204 + S*4   PEND_CLEAR[S]        W1C  Write 1 to clear (edge sources only; ignored for level).
0x0400 + S*4   PRIO[S]              R/W  One byte per source — bits[2:0] = priority, bit 7 = ETRIG (edge=1).
0x0600 + S*4   TARGET[S]            R/W  One byte per source — bits[3:0] = target CPU (≤15 cores).

0x0F00 + N*4   IPI_SEND[N]          W    Write to IPI_SEND[target_cpu] enqueues an IPI at target_cpu's AIC2.
                                          Write value layout: bits[7:0] = vector number to deliver.
                                          Non-posted: fabric withholds completion until aic_com_o delivers.

0x0FF0         AIC2_LOCK            R/W  Optional access-control register (see §6.3).
```

`S` is the source count, `N` is the CPU count. Offsets are recommended; the canonical layout is `aic2.vhm` as it ships, augmented by the new offsets at T1/T2 below.

### 3.3 `AIC2_CAPS` capability register

```
[31:24]  AIC_VERSION       2 = AIC2 (this spec). Reserved values for future revs.
[23:16]  NUM_CPUS          Cores attached to the inter-AIC bus.
[15:8]   NUM_SOURCES_LOG2  log2(S) — Linux reads this to size its bitmaps.
[7]      HAS_FGMT          1 = Tier 1 implementation; per-TC fields are honoured.
[6:4]    NUM_TC_LOG2       log2(`n_tc`). Zero on T0.
[3]      HAS_VIRT          1 = Tier 2 implementation; hyperprivileged register group present.
[2:0]    reserved          read-as-zero, write-ignored.
```

Linux's `irq-jcore-aic` driver reads `AIC2_CAPS` at probe and falls back to a hard-coded source count on Tier 0 ABI (which omits the field, returning 0 — backward compat).

### 3.4 Priority encoder and IRL output

Each cycle, AIC2 computes:

```
winner = argmax over sources s of (PRIO[s] | (ENABLE[s] & PEND[s] & target_matches_me(s)))
                                       (0 if disabled, else PRIO[s])
```

If `PRIO[winner] > SR.IMASK` on the owning CPU (and the CPU is not in a delay-slot / BL-blocked window), AIC2 asserts `cpu_event_i_t.irq_level = PRIO[winner]` and `vector_number = winner`. The CPU's exception logic accepts and jumps to `VBR + 0x600 + vector_number * 0x20` (the standard SH external-interrupt vector layout — see [mmu/hardware-spec.md §5](../mmu/hardware-spec.md) for the vector conventions AIC2 follows).

When the CPU accepts (drives `cpu_event_o_t.ack` for the AIC2-presented vector), AIC2 atomically:

- If `ETRIG[winner] = 1`: clears `PEND[winner]`.
- If `ETRIG[winner] = 0`: leaves `PEND[winner]` set; it tracks the source line and self-clears when the line de-asserts.

If no source qualifies, IRL = 0 (no interrupt).

### 3.5 IPI mechanism and `aic_com` bus

The `aic_com_o` / `aic_com_i` ports form a small inter-AIC fabric (a bus or ring; the existing implementation is a simple chained bus indexed by `cpuid`). An IPI is initiated by a CPU writing to its own AIC2's `IPI_SEND[target_cpu]` register:

```
write IPI_SEND[T] = vector V:
    aic_com_o <- { type=IPI, src=cpuid, dst=T, vector=V }
```

The target AIC2 receives the message on its `aic_com_i`, treats it as if the source line for `vector V` had just edge-triggered (`PEND[V] := 1`), and the rest of the delivery path is normal §3.4.

IPI writes are **non-posted** ([bus/fabric-spec.md §6.4](../bus/fabric-spec.md)): the fabric withholds write-completion until the target AIC2 acknowledges receipt on `aic_com_i`. This is what the fabric spec's §12 #3 open question was about; it is **resolved** here.

Message format on `aic_com` (recommended; the existing `aic_com_i/o_t` record type is the canonical):

```
struct aic_com_msg {
    type     : 2;     -- 00 = IPI; 01 = (T2) virt-injection; others reserved
    src_cpu  : 4;     -- originating cpuid
    dst_cpu  : 4;     -- target cpuid
    tc_id    : 1+;    -- (T1) target TC; 0 on T0
    guest_id : 4;     -- (T2) target guest; 0 on T0/T1
    vector   : 8;     -- vector number / source id to assert at target
}
```

### 3.6 Edge vs level sources

`ETRIG[s]` selects the semantics per source.

- **Edge sources** (e.g. UART RX, timer expiry): hardware asserts the source line for one cycle; AIC2 sets `PEND[s]` on the rising edge. Cleared automatically on CPU accept. Software MAY clear early via write-1-to-clear on `PEND_CLEAR`.
- **Level sources** (e.g. IOMMU `FAULT_IRQ` per [iommu/hardware-spec.md §3.6](../iommu/hardware-spec.md), level-sensitive peripheral controllers): hardware holds the source line asserted; `PEND[s]` tracks the line. The CPU's handler is expected to clear the source-side condition (e.g. write to `IOMMU_STATUS.FAULT_PENDING`); when the source de-asserts, AIC2's `PEND[s]` follows.

IOMMU fault, by [iommu/hardware-spec.md §3.6](../iommu/hardware-spec.md), is **level-sensitive** ("a level interrupt that stays asserted while `FAULT_PENDING` is set"). AIC2 wires that source with `ETRIG=0` at SoC integration.

PMU overflow, per [ooo/j32ooo-spec.md §12](../ooo/j32ooo-spec.md), is conventionally edge-triggered: the PMU pulses the overflow line for one cycle, AIC2 latches.

### 3.7 Reset state

| Field                | Reset value |
| -------------------- | ----------- |
| `ENABLE[*]`          | 0           |
| `PEND[*]`            | 0           |
| `PRIO[*]`            | 0 (disabled) |
| `TARGET[*]`          | 0 (boot CPU) |
| `ETRIG[*]`           | integration-defined per source (typically 1 for edge sources, 0 for IOMMU/peripheral level lines) |
| `IRL_out`            | 0           |
| `AIC2_LOCK`          | 0 (no ACL enforcement) |

After reset, no interrupts are deliverable until software explicitly enables and prioritises sources. The boot CPU's AIC2 is the only one initially serving traffic; secondary AIC2 instances are inactive (their cores are held in reset, per [bus/fabric-spec.md §9.2](../bus/fabric-spec.md) and [mmu/hardware-spec.md §8.2](../mmu/hardware-spec.md)).

### 3.8 Prior art `[T0]`

The Tier 0 mechanisms — per-source enable/pending/priority, prioritised IRL delivery, vector dispatch through a CPU-side base+offset table, inter-controller IPI fabric — are decades-old standard interrupt-controller design.

| Mechanism                                              | Citation                                                                                       |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| Per-source enable/mask + priority + vector             | Renesas SH-4 Hardware Manual (INTC chapter), 1998; SH-2 manual (1996)                          |
| 3-bit priority matching CPU IMASK                      | Renesas SH-4 INTC IMASK convention; same in SH-2 series                                        |
| Distributed per-CPU interrupt controllers with inter-CPU bus | Intel APIC (P5 Pentium, 1993); IBM/Motorola/Freescale OpenPIC (1995); ARM VIC (≤2003)    |
| Edge vs level per-source trigger select                | Intel 8259A (1976) ELCR; PowerPC OpenPIC §3.4; ARM PL192 VIC (≤2003)                           |
| IPI by MMIO write to peer controller                   | Intel APIC ICR (1993); SPARC v9 sun4u interrupt-vector cross-call (1998)                       |
| Priority-encoded vector dispatch                       | MIPS R4000 CP0 Cause register (1991); SH-4 INTC; Motorola 68000 vector table (1979)            |
| Per-source target-CPU programmability                  | Intel APIC delivery destination register (1993); OpenPIC P_FOR_CTL[N] (1995)                   |

This block does not introduce a novel mechanism. T0 is the on-disk `aic2.vhm` as it ships today.

---

## 4. Tier 1 — FGMT Extension `[T1]`

### 4.1 Generics widen to `(cpuid, n_tc)`

Per [fgmt/dual-fgmt-proposal.md §5.3](../fgmt/dual-fgmt-proposal.md), the AIC2 instance's `cpuid` generic gains a companion `n_tc : natural := 2`. With `n_tc = 1`, T1 behaves identically to T0 (the per-TC fields are present but degenerate). With `n_tc = 2`, the J2-MT2x2 / J32-OOO / J32-FM case, each per-source target widens.

### 4.2 Per-source `TC_TARGET`

Each source gains a field:

| Field        | Width      | R/W | Description                                                                 |
| ------------ | ---------- | --- | --------------------------------------------------------------------------- |
| `TC_TARGET`  | log2(`n_tc`) | R/W | Target thread context within the source's affinity core. Defaults to TC0. |

On `n_tc=2` this is a single bit, packed alongside `TARGET[s]` (e.g. into bit 7 of the per-source `TARGET` byte at offset `0x0600+s`).

### 4.3 Per-TC pending bundle `per_tc_pending[N_TC]`

A new sideband signal exposed by AIC2 to the CPU's front end (NOT through `cpu_event_i_t`, which is a single-thread signal). It is a small bitmask, one bit per local TC, asserted when **any** enabled+pending source targets that TC. The OoO front-end's ready-thread arbiter ([ooo/j32ooo-spec.md §13.2](../ooo/j32ooo-spec.md)) treats `per_tc_pending[t] = 1` as one of the unparking conditions for thread `t`.

When a parked SLEEPing thread receives an interrupt:

1. AIC2 sets `PEND[s]=1` for the targeting source and re-evaluates §3.4 with the per-TC mask.
2. `per_tc_pending[TC_TARGET[s]]` asserts.
3. The ready-thread arbiter sees `per_tc_pending[t] = 1`, unparks thread `t` (per [ooo/j32ooo-spec.md §10.6](../ooo/j32ooo-spec.md)), and restores `priority_level[t]` to its baseline (per [ooo/j32ooo-spec.md §13.4 case 2](../ooo/j32ooo-spec.md)).
4. The next available fetch slot from thread `t` arrives at IF, the CPU takes the exception (IRL > SR.IMASK), AIC2 acks/clears (per §3.4), and the thread runs the handler.

This is the contractual interface between AIC2 and the OoO front-end that §13.4 of the OoO spec relies on.

### 4.4 IPI target widens to `(core, thread)`

The IPI mechanism (§3.5) extends:

- `IPI_SEND[N]` is replaced by a 2-D MMIO offset: `IPI_SEND[cpu_id][tc_id]`, packed as one word per `(cpu, tc)`. With `N=2` cores and `n_tc=2`, that's a 4-word region replacing the T0 2-word region. The high bit of the offset distinguishes TC1 from TC0.
- The `aic_com` message gains a `tc_id` field (already shown in §3.5's recommended layout).
- The receiving AIC2 sets `PEND[V]` for the vector — but the `TC_TARGET[V]` field for that vector slot, by convention, has been pre-programmed by software to match the IPI's target TC. (Alternative: each IPI explicitly carries a TC; the AIC2 ignores the static `TC_TARGET` for IPI vectors. The shipping AIC2 takes the static approach for ordinary vectors; for IPIs the dynamic-TC approach is recommended for T1, since IPIs are typically broadcast to a specific TC at runtime.)

### 4.5 Linux topology

Each `(core, tc)` pair maps to a logical CPU in `hard_smp_processor_id()`. With 2 cores × 2 TCs that's 4 logical CPUs, indexed `0..3`. Linux's `irq_set_affinity()` programs the AIC2's `TARGET[s]` and `TC_TARGET[s]` for the source. No new userspace ABI is required — `irq_set_affinity()`'s cpumask is already per logical CPU.

### 4.6 Backward compatibility `[T1]`

A T1 implementation with `n_tc = 1`:

- Returns `HAS_FGMT = 1` and `NUM_TC_LOG2 = 0` in `AIC2_CAPS`.
- Honours `TC_TARGET[s] = 0` only; writes of non-zero `TC_TARGET` values are silently dropped (the field is degenerate).
- Exposes `per_tc_pending[0]` only (a single-bit bundle).

A T0 implementation returns `HAS_FGMT = 0` and no `TC_TARGET` fields; Linux falls back to per-core affinity.

### 4.7 Prior art `[T1]`

Per-thread interrupt targeting predates 2006 in three major architectures:

| Mechanism                                              | Citation                                                                                                |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| Per-thread interrupt mask / steering                   | MIPS MT ASE — Kissell, MIPS Tech, "MIPS MT: A Multithreaded RISC Architecture for Embedded Real-Time Processing" (LNCS draft 2005, MIPS MD00452); thread-context interrupt steer registers. |
| Strand-targeted interrupts                             | UltraSPARC T1 ("Niagara") — Kongetira, Aingaran, Olukotun, "Niagara: A 32-Way Multithreaded Sparc Processor" (IEEE Micro 25(2), Mar–Apr 2005), strand-level interrupt delivery via the per-core IRQ unit. |
| Software-controllable per-stream interrupt mask        | Tera MTA — Burton J. Smith, "Architecture and applications of the HEP multiprocessor computer system" (1981); Tera MTA system overview papers (1990s); per-stream "stream status word" includes per-stream interrupt enable. |
| Per-thread idle/wake via interrupt                     | POWER5 `HMT_*` priority changes on interrupt entry (2003–2004 product papers); J32-OOO documents this lineage at [ooo/j32ooo-spec.md §10.6](../ooo/j32ooo-spec.md). |

---

## 5. Tier 2 — Hypervisor Virtualization `[T2]`

T2 adds a virtualization layer atop T1. Every T2 implementation is also a conformant T1 implementation. The new state and registers are **hyperprivileged-only**: writes from non-HS mode raise illegal-access (per [hypervisor/hardware-spec.md §3.4](../hypervisor/hardware-spec.md)).

### 5.1 Per-source `GUEST_OWNED` and `GVCPU_TARGET`

| Field           | Width | R/W (HS only) | Description                                                                 |
| --------------- | ----- | ------------- | --------------------------------------------------------------------------- |
| `GUEST_OWNED`   | 1     | R/W           | When set, source `s` is delivered as a virtual interrupt to a guest. When clear (default), delivered to host (i.e., behaves as T0/T1 — visible to the host kernel via existing offsets). |
| `GVCPU_TARGET`  | 8     | R/W           | Only consulted when `GUEST_OWNED=1`. Layout: bits[7:4] = guest id (matches [hypervisor/design-spec.md §3.7](../hypervisor/design-spec.md) 4-bit guest-id; 16 guests max); bits[3:0] = vCPU index within that guest. |

These fields live in a hyperprivileged-only register bank at recommended offset `AIC2_BASE + 0x4000`:

```
0x4000 + s*4  GUEST_OWNED[s]    R/W (HS only)  bit 0 = GUEST_OWNED
0x4400 + s*4  GVCPU_TARGET[s]   R/W (HS only)  bits[7:0] = guest-id||vcpu
```

A write to these offsets with `SR.HPRIV = 0` raises an illegal-instruction trap to the hypervisor (per [hypervisor/hardware-spec.md §3.4](../hypervisor/hardware-spec.md)). A read returns 0 (the guest must not be able to discover the host's routing decisions).

### 5.2 Delivery rules

For each source `s` whose `ENABLE[s] & PEND[s]` qualifies:

```
if !GUEST_OWNED[s]:
    -- Host-owned interrupt: T0/T1 path
    deliver via cpu_event_i_t to the running thread on TARGET[s]/TC_TARGET[s].
    HEDR is consulted by the CPU's trap logic per hypervisor/hardware-spec.md §4.
else:
    let (G, V) = GVCPU_TARGET[s]
    if (G, V) is currently dispatched on this physical CPU's TC AND
       the dispatched vCPU is running with SR.HPRIV=0 AND SR.MD=1 (or MD=0 and
       the guest has interrupts unmasked for user-mode delivery):
        -- Direct guest delivery (fast path)
        deliver via cpu_event_i_t to the guest vCPU.
        The guest's VBR (not VBR_HYP) catches the trap.
        HEDR[external-interrupt] is set by the hypervisor at vCPU dispatch
        time so the trap goes to the guest, not to HS.
    else:
        -- Slow path: trap to HS-mode for the hypervisor to handle.
        raise the "HS delivery-pending" event:
           set the per-(guest, vcpu) bit in HVDP[G][V] (§5.4)
           raise a hyperprivileged interrupt on this physical CPU at IRL=15
           with vector = VINJ_VECTOR (see §5.4)
        HEDR is bypassed for this internal vector (always-to-HS).
        The hypervisor decides whether to immediately context-switch to (G, V)
        or buffer the interrupt for later vCPU dispatch.
```

The "fast path" exists so that, when a guest's I/O device interrupts while the guest is the dispatched vCPU on this physical CPU, the trap goes straight to the guest with no HS-mode intermediary. This matches the SPARC v9 sun4v "interrupt cookie" fast-path and the POWER5 "external interrupt delivered to G" path.

### 5.3 Virtual-interrupt injection MMIO

The hypervisor must be able to inject **emulated-device** interrupts (e.g. virtio rings, paravirt clocks) that have no physical source line. A new hyperprivileged-only MMIO write does this:

```
0x4800        VINJ_SEND          W (HS only)
    bits[31:24]  = guest-id (4 bits used; upper 4 reserved)
    bits[23:16]  = vCPU index within guest
    bits[15:8]   = source-id to inject (vector number in the guest's source space)
    bits[7:0]    = TC hint (which guest TC, if guest sees FGMT)
```

A write to `VINJ_SEND` causes the AIC2 to act as if a source line had asserted on behalf of the guest. Internally it routes through the same delivery FSM as §5.2 (with `GUEST_OWNED=1` implicit, `GVCPU_TARGET` from the write).

`VINJ_SEND` is **non-posted**: the fabric withholds completion until the AIC2 has either delivered the interrupt directly to the running vCPU or enqueued it in `HVDP` (§5.4). This guarantees the hypervisor knows whether the injection landed before it returns to the guest.

### 5.4 Hypervisor delivery-pending state `HVDP[G][V]`

When the slow path fires (target vCPU not currently running), the interrupt is buffered. AIC2 maintains:

```
HVDP[G][V]:  one bitmap per (guest, vCPU) tracking pending guest-owned source-ids
             plus injected virtual interrupts that haven't yet been delivered.
```

When the hypervisor schedules `(G, V)` onto a TC of some physical CPU, it reads `HVDP[G][V]` (via a hyperprivileged-only MMIO read), restores the bits into the guest's `PEND[*]` view through `jcore_vintc` (§5.6), and clears `HVDP[G][V]`.

The on-trap "HS delivery-pending" vector (the internal one used by §5.2's slow path) is the controller's way to ping the hypervisor that **some** guest has accumulated pending interrupts; the hypervisor reads `HVDP_SUMMARY` to find which `(G, V)` need attention.

```
0x4900        HVDP_SUMMARY       R (HS only)
    bits[31:0] = bitmap of guests with any pending HVDP entry
                 (16-guest summary fits in low 16 bits)

0x4A00 + (G*4)  HVDP_VCPU_BITMAP[G]  R (HS only)
    bitmap of vCPUs in guest G with pending HVDP entries (16 vCPUs/guest fits in low 16 bits)

0x4C00 + (G*16 + V)*4   HVDP[G][V]    R/W1C (HS only)
    Per-(G,V) pending source bitmap. Sized to match S/32 32-bit words.
```

### 5.5 Interaction with HEDR and SR.HPRIV

Per [hypervisor/hardware-spec.md §2.3](../hypervisor/hardware-spec.md), HEDR is a 32-bit bitmap selecting which exception causes delegate to the guest's VBR vs go to VBR_HYP. The external-interrupt cause (`EXPEVT` in the SH-4 INTC range) has a bit in HEDR.

The hypervisor's convention with AIC2 is:

- **At vCPU dispatch**, the hypervisor sets `HEDR[external-interrupt] = 1` for that vCPU's HEDR shadow, telling the CPU "if an interrupt arrives while this vCPU is running, deliver it to the guest's VBR." AIC2's §5.2 fast path is what makes this safe — only guest-owned interrupts can fire while the guest is running, because host-owned sources have been masked at the AIC2 level for the duration of the vCPU's quantum.
- **At vCPU undispatch**, the hypervisor clears HEDR's external-interrupt bit, ensuring the next interrupt traps to HS so the hypervisor can decide what to do.
- **Host-owned sources** never fire on a running guest vCPU because they never satisfy AIC2's `GUEST_OWNED[s]=1` predicate; they wait until the host is scheduled.

This avoids the need for any IRL-level masking at vCPU switch — the AIC2's source-side ownership is the gate.

### 5.6 `jcore_vintc` — the guest-visible model

Each guest sees its own AIC2 register file via paravirtualized MMIO. The hypervisor presents the same offsets and same field layout as the bare-metal AIC2 (§3.2), so a guest's `irq-jcore-aic` driver runs unmodified. The hypervisor traps writes to certain registers:

- `ENABLE[*]`, `PRIO[*]`, `TARGET[*]`, `TC_TARGET[*]`, `ETRIG[*]`, `PEND_CLEAR` — emulated by the hypervisor, modifying its in-memory `struct jcore_vintc` per [hypervisor/linux-spec.md §3.2](../hypervisor/linux-spec.md).
- `IPI_SEND` — handled by `HCALL_HV_IPI_SEND` in the hypervisor's `hypercall.c`; the hypervisor then arranges for the target guest vCPU to receive the virtual interrupt (typically via `VINJ_SEND` on the target physical CPU's AIC2).
- `AIC2_CAPS`, `AIC2_CPUID`, `AIC2_STATUS` — the hypervisor returns synthetic values describing the guest's view (its own vCPU count, its own source count, etc.).

The hypervisor-private offsets (`GUEST_OWNED`, `GVCPU_TARGET`, `VINJ_SEND`, `HVDP_*`) are **not visible** to the guest at all — its MMIO window is shorter, and reads/writes past the public bank return 0 / are dropped.

The "virtual interrupt controller state" stored as `struct jcore_vintc` in [hypervisor/linux-spec.md §3.2](../hypervisor/linux-spec.md) is exactly this paravirt shadow.

Concretely, the hypervisor delivers a virtual interrupt to a guest by:

1. Setting the appropriate bit in the guest's `jcore_vintc.pend[*]`.
2. If the guest is dispatched on a physical CPU: writing `VINJ_SEND` on that physical CPU's AIC2 to wake the vCPU (the AIC2 sets IRL on `cpu_event_i_t` for that vCPU's TC; the trap, via HEDR-delegated routing, lands in the guest's VBR).
3. If the guest is not dispatched: setting the bit in `HVDP[G][V]` (transparently via `VINJ_SEND`'s slow path) so that at next dispatch the hypervisor restores the pending bits into the guest's shadow.

This is the same logic the SPARC v9 sun4v hypervisor uses for cookie-based interrupt cross-calls (Sun, "UltraSPARC Architecture 2005" hyperprivileged edition).

### 5.7 Multiple guests sharing a source

For v1, **no**. Each source has a single `GUEST_OWNED` bit and a single `GVCPU_TARGET`. A source belongs to either the host or exactly one guest's vCPU. If two guests need to share a device's interrupt (e.g. a single Ethernet IRQ multiplexed across guests at the software layer), the device's interrupt is host-owned and the host kernel demuxes — this is the standard KVM model.

A future revision may add a per-source guest-shared mode (broadcast-to-bitmap), but this introduces interrupt-priority-inversion risk and is left for v2. See §10 open question.

### 5.8 Prior art `[T2]`

Hypervisor-managed virtual interrupt delivery has solid pre-2006 prior art across several architectures:

| Mechanism                                              | Citation                                                                                                            |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| Per-source guest ownership + virtual injection         | SPARC v9 sun4v "interrupt cookies" — UltraSPARC Architecture 2005 (Sun, hyperprivileged edition); designed 2003–2005; the hypervisor maintains a per-(guest, vCPU) interrupt-cookie table and delivers cookies to guests via cookie-MMIO. AIC2's `GVCPU_TARGET` and `VINJ_SEND` mirror this. |
| HV+G+U three-state interrupt routing                   | PowerPC POWER5 — IBM POWER5 Microarchitecture (J. Tendler et al., IBM Journal of R&D 49(4/5), 2005); HV-mode interrupt routing; LPAR-virtualized External Interrupts. PowerPC ISA Book III had HV state by 2003. |
| Event channels / virtual interrupt source              | Xen — P. Barham et al., "Xen and the Art of Virtualization" (SOSP 2003); event channels are the software-level abstraction AIC2's `VINJ_SEND` re-implements in hardware. |
| Hardware-assisted IRQ injection in a guest             | VMware ESX — Adams & Agesen, "A Comparison of Software and Hardware Techniques for x86 Virtualization" (ASPLOS 2006, design and impl. work pre-2006); virtual-APIC for emulated devices. |
| Per-LPAR / per-guest interrupt steering                | IBM POWER4/5 ("LPAR" model, 2001+); each LPAR sees a virtualized External Interrupt that the firmware steers.       |
| Hyperprivileged mode separate from supervisor          | sun4v HPSTATE (UltraSPARC Architecture 2005); the SR.HPRIV bit and trap delegation in [hypervisor/hardware-spec.md §2](../hypervisor/hardware-spec.md) lift this directly. |

No mechanism in §5 is novel; all are direct translations of sun4v / POWER5 / Xen design patterns into the SH-4 INTC vocabulary.

---

## 6. Integration with the Bus Fabric `[T0/T1/T2]`

### 6.1 AIC2 MMIO is a slave port

AIC2's register file is a slave port on the SoC fabric per [bus/fabric-spec.md §3.1](../bus/fabric-spec.md). Reads and writes follow the same conventions as any other P4 MMIO slave: BMID-tagged, transaction-ID-ordered, MMIO-write-posting except where explicitly non-posted.

### 6.2 IPI writes are non-posted

`IPI_SEND` (and at T2 `VINJ_SEND`) write-completion is withheld by the fabric until AIC2 has acknowledged delivery on `aic_com_o`. This is the canonical example called out in [bus/fabric-spec.md §6.4](../bus/fabric-spec.md) and the resolution of [bus/fabric-spec.md §12 #3](../bus/fabric-spec.md). The reason: cross-CPU TLB shootdown and IPI-based synchronization need ack-on-delivery semantics; otherwise the sender could proceed before the target observes the IPI.

### 6.3 Access control (`AIC2_LOCK`)

An optional hyperprivileged-managed register at `AIC2_BASE + 0x0FF0`:

```
[31:0]   BMID_ALLOW_BITMAP    256-bit bitmap (8 words, 0x0FF0–0x100C) of BMIDs
                              allowed to write AIC2 host registers.
                              When all zero: no enforcement (T0 default).
                              When non-zero: writes from BMIDs with their bit
                              clear are dropped, with SLVERR returned.
```

Setting `AIC2_LOCK` itself requires hyperprivileged mode (`SR.HPRIV = 1`); attempts to write it from non-HS code raise an illegal-access fault.

This is the AIC2-internal piece of the hypervisor's defence-in-depth: the BMID space (per [bus/fabric-spec.md §4.4](../bus/fabric-spec.md)) is partitioned by integration role, and the hypervisor can restrict which masters get to program AIC2's source enables. Non-HS guest writes that bypass `jcore_vintc` and target the physical AIC2 directly (which should not happen if the MMU is configured correctly, but is defence-in-depth) are dropped here.

### 6.4 Direct-wire sources (bypass the fabric)

The following interrupt sources are wired **directly** to AIC2, not through the fabric:

- **PMU overflow**: per-core wire from each CPU's PMU to its own AIC2 instance ([ooo/j32ooo-spec.md §12](../ooo/j32ooo-spec.md)). One dedicated source line per PMU counter (recommended; alternative is an aggregate "any-PMU-overflow" line — see §10 open question). The L2 PMU's counter overflows ([cache/l2-spec.md §13.5](../cache/l2-spec.md)) route through the per-core PMU first, not directly into AIC2.
- **IOMMU fault**: one wire per IOMMU instance, level-sensitive, per [iommu/hardware-spec.md §3.6](../iommu/hardware-spec.md). The IOMMU asserts this line while `FAULT_PENDING` is set in `IOMMU_STATUS`. Wired with `ETRIG=0` at integration.
- **Timer**: per-core wire from the SoC timer block (or per-core local timer if present). Edge-triggered.

These bypasses exist because (a) source latency matters for PMU sampling fidelity and (b) routing them through the fabric would mean an extra hop for every interrupt, which is the dominant interrupt-latency contributor in many SoCs.

### 6.5 Peripheral source lines

Peripheral IRQs (UART, SD, Ethernet, USB, GPIO, …) wire from the peripheral block to a per-peripheral entry in the source vector. Integration is per-SoC; the [P4 MMIO map](../soc/p4-mmio-map.md) is the canonical allocator of source numbers (it owns both register-bank addresses and source-line assignments).

---

## 7. Reset and Boot `[T0/T1/T2]`

### 7.1 Reset state

All per-source state is cleared per §3.7. Specifically:

- `ENABLE[*] = 0`, `PEND[*] = 0`, `PRIO[*] = 0`, `TARGET[*] = 0`, `TC_TARGET[*] = 0`.
- T2 only: `GUEST_OWNED[*] = 0`, `GVCPU_TARGET[*] = 0`, `HVDP[*][*] = 0`, `AIC2_LOCK = 0`.
- IRL output = 0 on all per-CPU instances.
- `aic_com` bus is quiesced (no in-flight messages).

After reset, the boot CPU (CPU 0) is the only active CPU, per [bus/fabric-spec.md §9.2](../bus/fabric-spec.md) and [mmu/hardware-spec.md §8.2](../mmu/hardware-spec.md). Its AIC2 instance is ready to accept register writes; secondary AIC2 instances are valid but their CPUs are held in reset.

### 7.2 Secondary CPU release

Per [mmu/hardware-spec.md §8.2](../mmu/hardware-spec.md), CPU 0 writes to the SMP-release register at `0xFF00FF00` to release secondary cores. Until released:

- The fabric does not deliver MMIO traffic to a held core ([bus/fabric-spec.md §9.2](../bus/fabric-spec.md)).
- That core's AIC2 instance holds `IRL = 0` (no interrupt delivery).
- The `aic_com` bus's input from a held core's AIC2 is gated off (the held AIC2 cannot originate IPIs).

When CPU `n` is released, its AIC2 begins delivering pending interrupts; software is expected to first program enables/priorities/targets *before* any source can legitimately fire at the new core.

### 7.3 Wake-from-suspend routing

Per [mmu/hardware-spec.md §8.3](../mmu/hardware-spec.md), wake interrupts (RTC, external pin) default to CPU 0 by `TARGET[s] = 0` at reset. CPU 0 wakes first and brings up secondary cores via the standard hotplug path.

### 7.4 Hypervisor bootstrap `[T2]`

After the hypervisor takes control (either via `HYP_AT_RESET` fuse or HCALL bootstrap, per [hypervisor/hardware-spec.md §7](../hypervisor/hardware-spec.md)):

- It programs `AIC2_LOCK` to restrict register writes to its own BMID.
- It clears all `GUEST_OWNED[*]` (default at reset, but reasserted as policy).
- It initialises `HVDP[*][*] = 0`.
- It installs its per-guest virtual AIC2 ("jcore_vintc") state in software.
- When a guest is dispatched on a TC, the hypervisor sets `GUEST_OWNED[s] = 1` for each source the guest currently owns and updates `GVCPU_TARGET[s]` to the dispatched `(G, V)`.

---

## 8. Linux Driver Model `[T0/T1/T2]`

### 8.1 Existing in-tree driver `[T0]`

`drivers/irqchip/irq-jcore-aic.c` already handles AIC2 in mainline Linux. It probes the AIC2 via device-tree (`compatible = "jcore,aic2"`), reads `AIC2_CAPS` (or assumes a default source count if absent on T0), and provides the standard `irq_chip` ops:

- `irq_mask`, `irq_unmask` — write to `ENABLE[s]`.
- `irq_ack`, `irq_eoi` — write to `PEND_CLEAR[s]` (edge sources).
- `irq_set_type` — write to `ETRIG[s]`.
- `irq_set_affinity` — write to `TARGET[s]`.

This document does not replicate the driver's content. The driver's ABI to the hardware is the §3 register set.

### 8.2 FGMT extension `[T1]`

The Linux driver gains:

- **`AIC2_CAPS` probe** for `HAS_FGMT` / `NUM_TC_LOG2`. On hardware where the bit is set, the driver knows logical CPUs map to `(core, tc)` pairs.
- **`irq_set_affinity` extension**: the cpumask received names logical CPUs; the driver decomposes each into `(core, tc)` and writes `TARGET[s]` + `TC_TARGET[s]`. Linux's existing FGMT topology (per [fgmt/dual-fgmt-proposal.md §7](../fgmt/dual-fgmt-proposal.md)) already represents siblings; the IRQ affinity API doesn't change.

This is largely free in the driver — the existing `irq_set_affinity_cpumask()` path already takes a per-logical-CPU mask. The only new code is the bit packing for `TARGET || TC_TARGET`.

### 8.3 `jcore_vintc` paravirt driver `[T2]`

Inside a guest, the driver is the same `irq-jcore-aic.c` — the MMIO ABI is compatible. The hypervisor presents a per-vCPU view (each guest CPU sees its own AIC2 at the same canonical offset, in the guest's RA space). The hypervisor's `arch/sh/kvm/interrupt.c` (per [hypervisor/linux-spec.md §3.2](../hypervisor/linux-spec.md)) traps writes to the hyperprivileged-only AIC2 offsets — but those offsets are simply not mapped into the guest, so a well-behaved guest driver never touches them.

A guest may probe `AIC2_CAPS` and see:

- `HAS_VIRT = 0` (the guest does not know it is virtualized — `jcore_vintc` lies here; matches how Linux handles paravirt PICs on Xen/KVM).
- `HAS_FGMT = 1` if the hypervisor exposes virtual FGMT siblings (typical for multi-vCPU guests).
- `NUM_CPUS` = the guest's vCPU count.
- `NUM_SOURCES_LOG2` = the guest's source-space size (typically smaller than the physical AIC2's).

The hypervisor's `jcore_vintc` structure and its hypercall surface are specified in [hypervisor/linux-spec.md §3.2](../hypervisor/linux-spec.md); this spec defines only the MMIO ABI the guest driver sees.

---

## 9. Prior Art (pre-2006, consolidated)

Per [glossary §2](../glossary.md), every mechanism in this spec has pre-2006 published prior art. The consolidated table:

| Mechanism                                                  | Tier | Citation                                                                                                       |
| ---------------------------------------------------------- | ---- | -------------------------------------------------------------------------------------------------------------- |
| Per-source enable/mask + priority + vector                 | T0   | Renesas SH-4 Hardware Manual INTC chapter (1998); SH-2 manual (1996)                                            |
| 3-bit priority matching CPU IMASK                          | T0   | SH-4 INTC; SH-2 INTC                                                                                            |
| Distributed per-CPU interrupt controllers with inter-CPU bus | T0 | Intel APIC (P5 Pentium, 1993); IBM/Motorola OpenPIC spec (1995); ARM PL192 VIC (≤2003)                          |
| Edge vs level per-source trigger select                    | T0   | Intel 8259A ELCR (1976); OpenPIC §3.4 (1995); ARM PL192 VIC                                                     |
| IPI by MMIO write                                          | T0   | Intel APIC ICR (1993); SPARC v9 sun4u cross-call (1998)                                                         |
| Priority-encoded vector dispatch                           | T0   | MIPS R4000 CP0 Cause (1991); SH-4 INTC; Motorola 68000 vector table (1979)                                       |
| Per-source target-CPU programmability                      | T0   | Intel APIC delivery destination (1993); OpenPIC P_FOR_CTL                                                       |
| Capability register for software discovery                 | T0   | PCI Capability Pointer (PCI 2.2, 1998); ARM CP15 ID registers (≤2003)                                            |
| Non-posted MMIO write for IPI                              | T0   | AMBA AXI write-response semantics (ARM IHI 0022A, 2003); PCI ordering rules (1993)                              |
| Per-thread interrupt mask / steering                       | T1   | MIPS MT ASE — Kissell, "MIPS MT" (MIPS Tech 2005, MD00452)                                                       |
| Strand-targeted interrupts                                 | T1   | Kongetira, Aingaran, Olukotun, "Niagara: A 32-Way Multithreaded Sparc Processor" (IEEE Micro 25(2), 2005)         |
| Software-controllable per-stream interrupt mask            | T1   | Burton J. Smith, Tera MTA architecture (1990); Smith, "Architecture and applications of the HEP" (1981)         |
| Per-thread idle/wake on interrupt                          | T1   | POWER5 `HMT_*` (2003–2005); referenced from [ooo/j32ooo-spec.md §10.6](../ooo/j32ooo-spec.md)                    |
| Per-source guest ownership / virtual injection             | T2   | sun4v interrupt cookies — UltraSPARC Architecture 2005, hyperprivileged edition (designed 2003–2005)             |
| HV+G+U three-state interrupt routing                       | T2   | J. Tendler et al., "POWER5 system microarchitecture" (IBM J. R&D 49(4/5), 2005); PowerPC ISA Book III HV (2003)  |
| Event channels / virtual interrupt source                  | T2   | P. Barham et al., "Xen and the Art of Virtualization" (SOSP 2003)                                                |
| Hardware-assisted IRQ injection in a guest                 | T2   | Adams & Agesen, "A Comparison of Software and Hardware Techniques for x86 Virtualization" (ASPLOS 2006, design pre-2006); VMware ESX virtual-APIC patterns |
| Per-LPAR interrupt steering                                | T2   | IBM POWER4/5 LPAR firmware steering (2001+); IBM eServer iSeries Hypervisor                                      |
| Hyperprivileged mode separate from supervisor              | T2   | sun4v HPSTATE (UltraSPARC Architecture 2005); reused by [hypervisor/hardware-spec.md §2](../hypervisor/hardware-spec.md) |

No mechanism in this spec relies on a post-2006-only citation. Contributors extending the spec MUST cite pre-2006 sources for any new mechanism per [glossary §2](../glossary.md).

---

## 10. Open Questions

Items deferred to a future revision of this spec.

1. **Source-count parameter.** The shipping `aic2.vhm` has a parameterizable source count; current J-Core integrations use somewhere around 32–64. For J32-FM with PMU + IOMMU + per-peripheral lines, 64 is likely tight and 128 may be required. Recommendation pending P4 MMIO map review: **default `S = 64` for J2/J3/J32, `S = 128` for J32-OOO/FM/J64**. The on-die cost difference is ~`(S * 16)` flops per per-CPU AIC2 — modest.

2. **PMU integration granularity.** Does each PMU counter get a distinct AIC2 source, or one aggregate "any-PMU-overflow" source per core that software demuxes via PMU status registers? PowerPC 750 used per-counter; SH-4A UBC uses aggregate. Per-counter is cleaner for Linux `perf` but uses more AIC2 sources. Recommendation pending: **per-counter on J32-OOO/FM (typically 4 counters = 4 sources/core); aggregate on cheaper variants.**

3. **IPI broadcast (one-to-all).** Cross-core TLB shootdown's fallback path (when the lazy shootdown of [glossary §5](../glossary.md) cannot be used) needs one-to-all IPI semantics. Currently `IPI_SEND[target]` is unicast; a `IPI_BROADCAST` MMIO write would set `PEND` at every peer AIC2's matching vector. Should the `aic_com` message gain a "broadcast" type? Recommendation pending: **yes for T1+, on a separate `IPI_BROADCAST_SEND` MMIO offset; defer the wire format.**

4. **Guest-shared sources at T2.** §5.7 says "no" for v1. A future revision may add a per-source bitmap of receiving guests for shared interrupts (multicast). This would let multiple guests share a physical device that doesn't passthrough cleanly. Out of scope for v1.

5. **L2 PMU events as a separate AIC2 source line.** [cache/l2-spec.md §13.5](../cache/l2-spec.md) routes L2 counter overflows through the per-core PMU. An alternative is a dedicated AIC2 source per L2 instance. Recommendation pending: **stay with per-core-PMU routing for v1**, since the L2 PMU events are sampled in the OS by the same code path as core PMU events.

6. **Discovery-of-source-purpose register.** Linux's `irq-jcore-aic.c` currently relies on device-tree to map source numbers to peripheral names. A small ROM-like MMIO region naming sources (e.g. one 32-bit cookie per source) would let Linux probe without DT. Probably not worth doing; defer.

7. **Per-source latency budget.** With 128 sources and a single-cycle priority encoder, timing closure on a low-Fmax FPGA target (ULX3S) may be tight. The encoder may need a 2-cycle pipeline. Out of scope for this convention spec; tracked in the integration / synthesis report.

8. **Affinity-set partitioning across guests at boot.** When `HYP_AT_RESET=1` (per [hypervisor/hardware-spec.md §7.1](../hypervisor/hardware-spec.md)) the hypervisor controls AIC2 from cycle one. The host-vs-guest partition of the source space at first dispatch is policy, not architecture. Document the policy in a hypervisor-cookbook chapter once the first concrete platform is integrated.

None of these block T0/T1/T2 specification or integration.

---

## 11. Conformance Summary

A SoC integration claiming conformance to a tier MUST satisfy all of the following:

**T0:**

- (T0-1) Per-source `ENABLE`, `PEND`, `PRIO`, `TARGET`, `ETRIG` per §3.1.
- (T0-2) MMIO layout compatible with §3.2 (the shipping `aic2.vhm` register file is the reference).
- (T0-3) Priority-encoded delivery via `cpu_event_i_t.irq_level` per §3.4.
- (T0-4) IPI via `IPI_SEND` MMIO and `aic_com` bus per §3.5.
- (T0-5) Non-posted MMIO write semantics for `IPI_SEND` per [bus/fabric-spec.md §6.4](../bus/fabric-spec.md).
- (T0-6) Reset state per §3.7 / §7.

**T1** = T0 +:

- (T1-1) Per-source `TC_TARGET` field per §4.2.
- (T1-2) `per_tc_pending[N_TC]` sideband bundle to the front-end ready-thread arbiter per §4.3.
- (T1-3) IPI MMIO layout extended to `(cpu, tc)` per §4.4.
- (T1-4) `AIC2_CAPS.HAS_FGMT = 1` and `NUM_TC_LOG2` set per §3.3.
- (T1-5) `n_tc = 1` configuration is bit-compatible with T0 per §4.6.

**T2** = T1 +:

- (T2-1) Per-source `GUEST_OWNED`, `GVCPU_TARGET` (hyperprivileged-only) per §5.1.
- (T2-2) Delivery FSM per §5.2 (fast path direct, slow path to HS).
- (T2-3) `VINJ_SEND` non-posted MMIO per §5.3.
- (T2-4) `HVDP[*][*]` per-(guest, vCPU) pending bitmap per §5.4.
- (T2-5) `AIC2_LOCK` access-control register per §6.3.
- (T2-6) Hyperprivileged-only register protection per [hypervisor/hardware-spec.md §3.4](../hypervisor/hardware-spec.md).
- (T2-7) `jcore_vintc` ABI parity with the bare-metal AIC2 host register file per §5.6.
- (T2-8) `AIC2_CAPS.HAS_VIRT = 1` on the bare-metal view; `HAS_VIRT = 0` on the `jcore_vintc` view per §8.3.

---

## 12. Index of Cross-Doc Updates Driven by This Spec

When this spec lands, the following sister-doc edits are required for consistency:

| Doc | Section | Change |
| --- | ------- | ------ |
| [bus/fabric-spec.md §12 #3](../bus/fabric-spec.md) | AIC2 IPI delivery path | Mark resolved; point at this spec §3.5. |
| [glossary.md §7](../glossary.md) | Platform terms | Add AIC2 entry pointing at this spec. |
| [hypervisor/linux-spec.md §3.2](../hypervisor/linux-spec.md) | `jcore_vintc` | Cross-link to this spec §5.6 as the canonical model. |
| [fgmt/dual-fgmt-proposal.md §5.3](../fgmt/dual-fgmt-proposal.md) | Interrupts and per-thread events | Cross-link to this spec §4 (Tier 1). |
| [ooo/j32ooo-spec.md §12](../ooo/j32ooo-spec.md) | PMU overflow interrupt | Cross-link to this spec §6.4 (direct-wire source). |
| [ooo/j32ooo-spec.md §13.4](../ooo/j32ooo-spec.md) | SLEEP wakeup via interrupt | Cross-link to this spec §4.3 (`per_tc_pending` bundle). |

These edits are landed in the same change as this spec.
