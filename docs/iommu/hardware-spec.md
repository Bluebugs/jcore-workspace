# J-Core IOMMU Hardware Implementation Specification (Phase 2)

**Status:** Draft  
**Scope:** RTL implementation guide for the J-Core SoC IOMMU  
**Audience:** Hardware engineers implementing the IOMMU block  
**Prerequisites:** Phase 1 hardware spec (`02-hardware-spec.md`), Phase 2 design spec (`04-iommu-design-spec.md`)

> **Reset polarity reversed and four controls re-specified — 2026-09-09, Wave-3 task C2d.**
> This document previously specified a reset state in which the IOMMU was absent:
> `IOMMU_CTRL.ENABLE` reset `0`, `BMID_BYPASS_*` reset all-ones, `SUPER_BYPASS`
> unlocked, and an IOTLB `GLOBAL` bit that matched every BMID. Those are the four
> register definitions [security/threat-model.md §7.7](../security/threat-model.md)
> read to rate bar item **L2** `NOT MET`. **§3.10 is now the normative owner** of
> the deny behaviour (`I-R1`–`I-R10`); §3.1, §3.2, §3.7, §3.9, §4.3 and §8 are
> rewritten to agree with it, and §2.2, §6 and §7 are rewritten because three
> mechanisms they relied on — a bus error response, a permission applied during
> bypass, and a snoop path from a DMA transaction to a CPU cache — **do not exist
> in any repository**. The superseded text is quoted where it is retired, per
> [decisions/0002](../decisions/0002-supersede-convention.md).
>
> **Nothing here is implemented.** There is no IOMMU, no IOTLB and no BMID in
> `jcore-cpu@origin/master` or `jcore-soc@origin/master`: a case-insensitive
> search over *all* files for `iommu|io_mmu|bmid|iotlb|io_tlb|dvma` returns zero
> matches in both repositories. Every value below is a specification value, which
> is why changing the reset polarity costs nothing today.

---

## 1. Scope

This document specifies the hardware-visible structure of the J-Core IOMMU: register interface, IOTLB organization, translation pipeline, fault model, and reset behavior.

What's specified:
- MMIO register map
- IOTLB entry format and lookup function
- BMID assignment and bypass mechanism
- Fault detection and reporting
- Interaction with the bus fabric and DRAM controller
- Reset state

What's not specified:
- Bus fabric implementation (assumes AXI or compatible; BMID-tagging at the master ports).
  **This assumption is not met by anything that exists**: there is no AXI in either
  repository and the J-Core data bus carries no transaction ID and no master ID at all
  ([security-review.md §3](security-review.md) **IH-1**). The AXI-flavoured `SIZE`,
  `LEN` and `ID` rows in §2.1 describe an intended target interface, not a present one
- DRAM controller implementation
- IOTLB physical implementation (CAM, SRAM-and-comparator, or hybrid — implementer's choice)

Conventions match Phase 1 spec: bit 0 = LSB, bit ranges inclusive, address terms VA/PA/IOVA/PFN.

## 2. Bus Interface

### 2.1 Bus master tagging

Each transaction arriving at the IOMMU carries:

```
Signal           Width    Description
---------------  -------  --------------------------------------
BMID             8 bits   Master ID assigned by bus fabric
IOVA             36 bits  I/O virtual address (or PA in bypass)
RW               1 bit    0 = read, 1 = write
SIZE             3 bits   Standard AXI burst size encoding
LEN              8 bits   Burst length
DATA             64 bits  Data (writes)
ID               4 bits   Bus transaction ID (for response routing)
```

BMID is set by the bus fabric based on the initiator's physical position. Devices cannot spoof BMID; it's a hardwired property of the fabric layout. The canonical specification of the BMID space, master-port assignment policy, and the immutability guarantee that this IOMMU relies on lives in [bus/fabric-spec.md §4](../bus/fabric-spec.md). The transaction-ID semantics summarised in the signal table above (`ID`, 4 bits, AXI same-ID-ordered) are specified normatively in [bus/fabric-spec.md §5](../bus/fabric-spec.md).

### 2.2 Bus response

On hit, the IOMMU forwards the transaction with `IOVA` replaced by the translated PA. The bus ID and burst parameters are preserved.

On block — a miss, a permission failure, or any of the deny cases in §3.10 — the
IOMMU **completes** the transaction toward the master with read data zero and the
write data discarded. It does not withhold the acknowledge. See `I-R2`.

> **This paragraph previously read** *"the IOMMU responds to the master with a bus
> error (AXI `SLVERR` or equivalent). The data phase is suppressed for reads;
> writes are dropped."* **It was unimplementable on the bus this project has, and
> its literal reading hangs the machine.** The J-Core data bus is
> `jcore-cpu:cpu2j0_pkg.vhd`'s `cpu_data_o_t` / `cpu_data_i_t`; the response record
> is `{ d, ack }` and **carries no error field at all** — there is no `SLVERR`, no
> `RESP`, and no `AxID` (the `ID` row in §2.1's signal table is likewise aspirational).
> "Suppressing the data phase" on a bus whose only completion signal is `ack` means
> never asserting `ack`, which stalls the master forever and, behind a fixed-priority
> mux like `jcore-soc:components/misc/bus_mux_typec.vhm`, can wedge every other
> master behind it. A denial of service is not an acceptable failure mode for the
> *default* path, and under `I-R1` the deny path **is** the default path out of reset.
> An integration that later adopts a bus with an error response should carry one, in
> addition to — not instead of — the defined completion `I-R2` requires.

## 3. MMIO Register Map

All IOMMU registers live in the SoC's P4 region at base address `0xFF010000`. The block occupies 4 KB of address space.

```
Offset    Size    Name              Access  Description
--------  ------  ----------------  ------  ---------------------------
0x0000    32      IOMMU_CTRL        R/W     Global control
0x0004    32      IOMMU_STATUS      R/W1C   Global status / fault flags
0x0008    32      IOMMU_VERSION     R       Version and capability info
0x000C    32      reserved
0x0010    32      FAULT_BMID        R       Last fault BMID
0x0014    32      FAULT_IOVA_LO     R       Last fault IOVA, low 32 bits
0x0018    32      FAULT_IOVA_HI     R       Last fault IOVA, high bits (J64)
0x001C    32      FAULT_INFO        R       Last fault type, direction, count

0x0020-
0x009C            reserved

0x00A0    32      IOTLB_CMD         W       Command: write entry, invalidate, etc.
0x00A4    32      IOTLB_INDEX       R/W     Entry index for write commands
0x00A8    32      IOTLB_TAG_LO      R/W     Tag low (IOVA bits, PageMask)
0x00AC    32      IOTLB_TAG_HI      R/W     Tag high (BMID, IOVA high, valid)
0x00B0    32      IOTLB_DATA_LO     R/W     Data low (PFN bits, permissions)
0x00B4    32      IOTLB_DATA_HI     R/W     Data high (PFN high, cache attrs)

0x0100-
0x011F            BMID_BYPASS_*     R/W     Per-BMID bypass bitmap, 256 bits

0x0200-
0x0FFF            reserved (future: per-BMID statistics, debug)
```

### 3.1 IOMMU_CTRL (offset 0x0000)

```
[31:5]   reserved (0)
[4]      SB_LOCK        Write 1 to lock SUPER_BYPASS. Sticky: once 1 it
                        stays 1 until hardware reset, and writes of 0 are
                        ignored. Also set by hardware on the first accepted
                        IOTLB WRITE_ENTRY. See I-R4.
[3]      FAULT_IRQ_EN   Enable fault interrupt. Masks the IRQ line only;
                        it never affects whether a transaction is blocked
                        or whether a fault is latched.
[2]      SUPER_BYPASS   If set, all transactions bypass regardless of
                        BMID_BYPASS (debug/recovery only). Writes are
                        ignored while SB_LOCK = 1.
[1]      INVALIDATE_ALL Write 1: invalidate all IOTLB entries
                        (self-clearing). A write to this register never
                        clears ENABLE or SB_LOCK, whatever the other bits
                        of the written word hold.
[0]      ENABLE         0 = IOMMU bypassed for all masters
                        1 = IOMMU active (per BMID_BYPASS)
                        Write-once-to-1: reset sets it, a write of 0 is
                        ignored, and only hardware reset clears it. See I-R3.
```

**Reset value: `0x00000001`** — `ENABLE = 1`, `SUPER_BYPASS = 0`, `SB_LOCK = 0`,
`FAULT_IRQ_EN = 0`. Read together with §3.9's all-zeros `BMID_BYPASS_*` and §8's
all-invalid IOTLB, this is the whole of `I-R1`: **out of reset the IOMMU is
active and every BMID is denied.**

`FAULT_IRQ_EN` resets **clear** deliberately, and this is the one reset value in
§3.1 that is not simply the safe polarity. Under `I-R1` a blocked transaction at
boot is *expected* — it is what a device doing DMA before its driver has mapped
anything now produces — and a fault IRQ armed before the AIC2 and the handler
exist would be an unhandled interrupt storm at the least convenient moment. The
fault is still latched and still counted (§3.5); only the line is masked. **Nothing
about blocking depends on `FAULT_IRQ_EN`**, which is the property that makes
masking it safe and which `I-R2` states normatively.

#### 3.1a `DEFAULT_PERM` is removed

Bits `[7:4]` previously held `DEFAULT_PERM`, which this document described as the
*"permission applied when bypass active"* with a reset value of `0xC`
(read + write). **It is deleted, and the bits are reserved.** Two reasons, and the
second is the one that matters:

1. **No stage of the pipeline ever consulted it.** §4.2 of
   [design-spec.md](design-spec.md) says of the bypass path *"transaction passes
   through, `PA = IOVA`. No translation."*, and §5.1 below routes a bypassed
   transaction from the `BMID_BYPASS` lookup straight to the DRAM controller. There
   is no permission check on the bypass path to apply a default permission *to*. It
   was a control with no enforcing logic — the shape Wave-3 task C1c named, and it
   would have been read by an implementer as a licence to add one.
2. **It was half the reason the old reset value was permissive.** `0x000000C0` is
   `DEFAULT_PERM = read+write` and nothing else; the register's own reset comment
   called it *"orderly bypass"*. A field whose only effect was to make the reset
   word look deliberately open is worse than a field with no effect.

A future revision that wants a coarse per-BMID permission — a BMID that may read
but never write, without spending an IOTLB entry — should add it as a **per-BMID**
field alongside `BMID_BYPASS_*`, where it can be enforced per transaction, and not
as a single global default.

### 3.2 IOMMU_STATUS (offset 0x0004)

```
[31:8]   reserved (0)
[7]      FAULT_PENDING  At least one fault has been logged but not cleared
[6]      FAULT_OVERFLOW More than one fault occurred since last clear
                        (only first is in FAULT_* registers)
[5]      reserved
[4]      VIRGIN         Read-only. 1 = no IOTLB WRITE_ENTRY has been
                        accepted since hardware reset. Cleared by the first
                        accepted WRITE_ENTRY and never set again except by
                        reset. See I-R4.
[3]      IOTLB_WRITE_BUSY Asserted while an IOTLB write is in progress
[2]      reserved
[1]      INVALIDATE_BUSY  Asserted during INVALIDATE_ALL
[0]      ENABLED          Mirror of IOMMU_CTRL.ENABLE (read-only here)
```

Status bits are write-1-to-clear except where noted. `ENABLED` and `VIRGIN` are
read-only. **Reset value: `0x00000011`** (`VIRGIN = 1`, `ENABLED = 1`).

### 3.3 IOMMU_VERSION (offset 0x0008)

```
[31:16]  reserved (0)
[15:8]   IOTLB_ENTRIES  Number of IOTLB entries (read-only)
[7:0]    VERSION        IOMMU version. 0x01 = Phase 2 baseline.
                        (Earlier drafts allocated [15:8] to VMID_BITS;
                        VMID is removed project-wide, so the field is
                        repurposed for IOTLB_ENTRIES, freeing [23:16]
                        as reserved-for-future-use.)
```

Read at probe time by Linux to determine capabilities.

### 3.4 FAULT_BMID / FAULT_IOVA_LO / FAULT_IOVA_HI (0x0010–0x0018)

Latched on the first fault since last status clear. FAULT_BMID contains the offending master's BMID in bits 7:0; upper bits reserved. FAULT_IOVA_LO holds the lower 32 bits of the faulting IOVA; FAULT_IOVA_HI holds bits 63:32 (zero on J32 hardware).

### 3.5 FAULT_INFO (0x001C)

```
[31:16]  FAULT_COUNT    Number of faults since last clear (saturates at 0xFFFF)
[15:8]   reserved
[7:4]    FAULT_TYPE     0 = miss, 1 = permission, 2 = invalid request,
                        3-15 reserved
[3:1]    reserved
[0]      FAULT_RW       0 = read access, 1 = write access
```

### 3.6 IOTLB_CMD (offset 0x00A0)

Write-only. Encoded command:

```
[31:28]  CMD           0x1 = WRITE_ENTRY (from IOTLB_TAG/DATA registers
                              to entry at IOTLB_INDEX)
                       0x2 = READ_ENTRY  (to IOTLB_TAG/DATA registers
                              from entry at IOTLB_INDEX)
                       0x3 = INVALIDATE_ENTRY (entry at IOTLB_INDEX)
                       0x4 = INVALIDATE_BMID (all entries with BMID
                              specified in low 8 bits)
                       Others = reserved (illegal, ignored)
[27:0]   ARG           Command-specific argument:
                       For INVALIDATE_BMID: BMID in low 8 bits
                       For WRITE/READ/INVALIDATE_ENTRY: ignored
```

Hardware response to writes:
- WRITE_ENTRY: **refused** if `IOTLB_TAG_HI.GLOBAL = 1` (`I-R5`) or if
  `IOTLB_TAG_HI.BMID` is `0x00` or `0xFF` (`I-R6`) — the entry is not written, an
  invalid-request fault is raised (§6.1), and `IOMMU_STATUS.VIRGIN` is unchanged.
  Otherwise: latches `IOTLB_TAG/DATA` into entry `IOTLB_INDEX`; asserts
  `IOTLB_WRITE_BUSY` for ≤2 cycles; and, on the **first** accepted WRITE_ENTRY
  since reset, clears `IOMMU_STATUS.VIRGIN` and sets `IOMMU_CTRL.SB_LOCK` (`I-R4`)
- READ_ENTRY: copies entry into `IOTLB_TAG/DATA`; transparent to software
- INVALIDATE_ENTRY: clears VALID bit of entry; immediate
- INVALIDATE_BMID: scans all entries; clears those matching BMID; takes N cycles where N = IOTLB entry count

### 3.7 IOTLB_TAG_LO / IOTLB_TAG_HI (0x00A8 / 0x00AC)

Tag fields, format below.

**IOTLB_TAG_LO (32 bits):**
```
[31:14]  IOVA[31:14]    Low part of IOVA (for J32 fully here)
[13:10]  PAGE_MASK      log4(page_size / 4 KB), same encoding as PTEL
[9:8]    reserved
[7:4]    reserved
[3:0]    reserved
```

**IOTLB_TAG_HI (32 bits):**
```
[31:24]  reserved (0)
[23:16]  IOVA[39:32]    High IOVA bits (J64; reserved/zero on J32)
[15:8]   BMID           Bus Master ID for this entry
[7:2]    reserved (0)
[1]      GLOBAL         Must be written 0. A WRITE_ENTRY carrying 1 is
                        refused (§3.6) and an entry holding 1 never
                        matches (§4.3). See I-R5.
[0]      VALID          1 = entry valid, 0 = invalid (match always fails)
```

> **Bit `[1]` previously read** *"`GLOBAL` — If set, match any BMID."* **The grant
> is removed; only the bit position survives, and it survives as a fault term.**
> The reasoning is `I-R5`. Note also that the retired bit-list assigned `[7:0]` to
> `reserved` *and* `[1]`/`[0]` to `GLOBAL`/`VALID` — the two ranges overlapped, so
> a conformant implementation could have read `VALID` as reserved-zero and matched
> nothing, or read the reserved range as writable and matched everything. The
> ranges are disjoint now.

### 3.8 IOTLB_DATA_LO / IOTLB_DATA_HI (0x00B0 / 0x00B4)

Data fields.

**IOTLB_DATA_LO (32 bits):**
```
[31:14]  PFN[31:14]     Low part of physical frame number
[13:8]   reserved
[7]      reserved
[6]      WRITE          1 = device may write through this entry
[5]      reserved
[4]      READ           1 = device may read through this entry
[3:2]    reserved
[1]      reserved
[0]      reserved
```

**IOTLB_DATA_HI (32 bits):**
```
[31:24]  reserved (0)
[23:16]  PFN[39:32]     High PFN bits (J64)
[15:8]   reserved
[7:4]    reserved
[3]      CACHEABLE      Cacheability attribute forwarded to the fabric. NOT a
                        coherency guarantee -- the IOMMU has no path to any
                        cache. See I-R9 and §7.1.
[2]      WBA            Write-back-acknowledge attribute forwarded to the fabric.
                        Same status: an attribute, not a promise (§7.1).
[1:0]    reserved
```

*(Corrected post-F, 2026-09-09.* `CACHEABLE`'s one-line description read *"Device
transaction snoops CPU caches"* and `WBA`'s read *"Write-back acknowledge (for
posted writes)"*. §7.1 and [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md)
withdrew exactly that promise, and `I-R9` makes both bits attributes — but the
field description is what an RTL engineer implements from, and it still promised
the snoop.*)*

### 3.9 BMID_BYPASS_* (0x0100–0x011F)

256-bit bitmap spread across eight 32-bit registers. Bit *N* of register *k* controls
BMID `32k + N`:

- Bit clear (0): BMID N transactions go through IOTLB lookup — and are therefore
  **blocked** unless a valid entry matches. This is the deny state; it is not a new
  state machine, it is what a lookup miss already does (§6.1).
- Bit set (1): BMID N transactions bypass (PA = IOVA)

**Reset value: all bits clear — every BMID goes through the IOTLB, and with §8's
all-invalid IOTLB that means every BMID is blocked.** A BMID that no driver ever
claims stays blocked forever, which is the half of bar item **L2** that the
previous polarity inverted. Linux **sets** a bit only to hand a master an
explicitly-unprotected path, and [linux-spec.md §5.4](linux-spec.md) never does.

> **This paragraph previously read** *"Reset value: all bits set (all BMIDs
> bypass). Linux IOMMU driver clears bits as it claims devices."* Together with the
> old `ENABLE` reset of `0`, that is the sentence
> [security/threat-model.md §7.7](../security/threat-model.md) quotes as the boot-window
> vulnerability made permanent.

The register offset arithmetic is stated here because
[linux-spec.md §5.4](linux-spec.md) got it wrong in both directions at once: BMID
*B* lives in the register at byte offset `0x0100 + 4 * (B / 32)`, at bit `B % 32`.


### 3.10 Default-deny — normative rules `I-R1`–`I-R10`

This section owns the IOMMU's deny behaviour. It is the answer to bar item **L2**
in [security/threat-model.md §8](../security/threat-model.md), and it is written as
rules rather than as prose because §8's clauses — its original five, plus the five
[§7.7a](../security/threat-model.md) adds — each need a place an implementer can be
held to.

**The starting point, which is not a new mechanism.**
[security/threat-model.md §7.7](../security/threat-model.md) sharpened the bar in
the project's favour and the sharpening survives checking: a BMID with
`BMID_BYPASS[N] = 0` and no matching IOTLB entry **already** blocks the
transaction, latches a fault and raises an IRQ. **Deny is the existing miss
behaviour.** Nothing below adds a per-BMID state machine. What the rules change is
which way the registers point out of reset, which of them can be turned back off,
and what "blocked" does on a bus with no error response.

#### The **7** bypass paths

The productive question is not which structures leak but which reach memory with
no permission check at all. There are **7** such paths, and every rule below closes,
gates or names one:

| # | Path | Closed by |
|---|---|---|
| 1 | `IOMMU_CTRL.ENABLE = 0` — the whole block bypassed | `I-R3` (reset 1, write-once, cleared only by reset) |
| 2 | `BMID_BYPASS[BMID] = 1` | `I-R1` (reset all-zeros), `I-R7` (restored to 0 before release) |
| 3 | `IOMMU_CTRL.SUPER_BYPASS = 1` | `I-R4` (reset 0, self-arming lock) |
| 4 | BMID `0x00`, *"untagged / bypass"* ([bus/fabric-spec.md §4.3](../bus/fabric-spec.md)) | `I-R6` (blocked, never bypassed) |
| 5 | BMID `0xFF`, which that section made a **permanent** bypass until C2d reversed it | `I-R6` (blocked; and the fabric must not assign it) |
| 6 | an IOTLB entry with `GLOBAL = 1`, matching every BMID | `I-R5` (never matches; refused at install) |
| 7 | a master whose path to memory does not traverse the IOMMU at all | **Not closed — named.** `I-R1a` |

Path 7 is not hypothetical and it is the one no register can reach.
`jcore-soc:components/misc/flash_boot_reader.vhd` is a non-CPU initiator whose
ports are a **private SPRAM write port** (`sp_en`/`sp_we`/`sp_a`/`sp_dw`); it
streams flash into on-chip SRAM before boot, never touches the data bus, and is
invisible to any bus-level IOMMU by construction. Any integration adding a master
with a private path to memory must say so in its manifest, because the IOMMU's
guarantee is scoped to masters that reach memory through it and to nothing else.

#### The rules

- **`I-R1` — reset is deny.** Out of hardware reset: `IOMMU_CTRL = 0x00000001`
  (§3.1), `BMID_BYPASS_* = 0` (§3.9), every IOTLB entry `VALID = 0` (§8). A DMA
  transaction arriving before software has written anything is blocked. There is no
  window, brief or otherwise, in which the IOMMU is absent.

- **`I-R1a` — the client set is normative.** The IOMMU translates transactions from
  **non-CPU master ports only**. A CPU core's master port reaches memory without
  traversing the IOMMU — the CPU has its own MMU — so BMIDs `0x01`–`0x0F`
  ([bus/fabric-spec.md §4.4](../bus/fabric-spec.md)) never appear at the IOMMU's
  slave interface, and `I-R1` therefore cannot deny a core its own boot fetch.
  **This has to be normative rather than implied**, because
  [design-spec.md §4.1](design-spec.md)'s prose and its topology diagram disagreed
  about it, and under the old all-bypass reset the disagreement was invisible.
  Under `I-R1` it is the difference between a secure default and a part that cannot
  boot. An integration that *does* route a CPU port through the IOMMU is
  non-conformant to this revision.

- **`I-R2` — a block is a completed transaction with defined data.** A blocked
  read completes with **all-zero** data; a blocked write completes with the write
  data discarded. The acknowledge is asserted, always, and **in the same number of
  cycles as a hit** so that block and hit are not separable by timing. Blocking
  never depends on `FAULT_IRQ_EN`, on a handler being installed, or on software
  having read `IOMMU_STATUS`. See §2.2 for why the retired "return `SLVERR`, suppress
  the data phase" formulation is not available on this bus.

- **`I-R3` — `ENABLE` cannot be turned off.** It resets to 1 and a write of 0 is
  ignored; only hardware reset clears it. This is not defence against a hostile
  write — [hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md) already
  traps every guest P4 access, so the adversary of
  [security/threat-model.md §1](../security/threat-model.md) cannot reach this
  register at all. It is defence against the **host** driver's own idiom:
  [linux-spec.md §5.1](linux-spec.md) and §8.1 each write `IOMMU_CTRL` as a whole
  word containing only `INVALIDATE_ALL`, which under the old definition cleared
  `ENABLE` and put the machine in full bypass for the duration of a probe and of
  every resume. Both sites are correct code against a register that cannot be
  disabled and silent full-bypass windows against one that can.

- **`I-R4` — `SUPER_BYPASS` has a self-arming write-once lock.** `SUPER_BYPASS`
  resets to 0. `SB_LOCK` resets to 0, is write-1-to-set, and is cleared only by
  hardware reset. While `SB_LOCK = 1`, writes to `SUPER_BYPASS` are ignored — a
  read-back therefore reports the *old* value, which is how software detects that
  the lock took. **`SB_LOCK` is additionally set by hardware on the first accepted
  `WRITE_ENTRY`**, i.e. when `IOMMU_STATUS.VIRGIN` clears.

  The automatic arm is the part worth arguing for. A lock that software must
  remember to set is a rule with no detector, and the boot event that a
  "brief bypass window that locks after handoff" would have to key on **does not
  exist**: the only fabric-visible boot transition
  ([bus/fabric-spec.md §9.2](../bus/fabric-spec.md)) is the SMP release register at
  `0xFF00FF00`, which lives in a different block and is never written at all on a
  single-core part. Keying the lock on *the first IOTLB entry ever written* uses an
  event the IOMMU sees itself, that every real bring-up performs, and that
  necessarily precedes any tenant running behind a mapped device. Debug and recovery
  keep their escape: a session that programs no IOTLB entry can still set
  `SUPER_BYPASS`.

- **`I-R5` — `GLOBAL` never grants.** The match function requires
  `entry.GLOBAL = '0'` (§4.3), so an entry with the bit set matches **nothing**
  rather than everything; and `WRITE_ENTRY` refuses a tag carrying `GLOBAL = 1`
  (§3.6), so the mistake is loud at install as well as inert at lookup.

  This is [mmu/security-review.md §2](../mmu/security-review.md)'s **S-I7** applied
  one block over, and deliberately in the same shape: not a rule saying software
  must not set the bit, but a hardware term that makes the dangerous value fault, plus
  a named guard test (`I-E4`). It goes further than S-I7 because the IOMMU's case is
  not narrowable the way the MMU's was. There, the dangerous *combination* was
  `G=1 && U=1` and a global kernel page stayed legitimate. Here there is no `U` bit
  and no per-entry marker of who is untrusted, so no combination is available; and
  restricting `GLOBAL` to read-only entries would not help, because a globally
  *readable* buffer is already a cross-tenant disclosure primitive the moment two
  tenants own devices.

  **The legitimate use survives at a known price, which is why removal is available
  at all.** [design-spec.md §7](design-spec.md) justified the bit as a way to share
  "a genuinely-shared buffer". A domain that spans several BMIDs is already
  expressed exactly by installing one entry per attached BMID — which is precisely
  what [linux-spec.md §5.2](linux-spec.md)'s `.map` already does, looping
  `for_each_set_bit(bmid, domain->bmids, …)`. That form *names* its sharers where
  `GLOBAL` names none, and it costs *k* of the IOTLB's entries for a *k*-way shared
  buffer instead of one. Under §4.1's 64-entry geometry and
  [design-spec.md §5.3](design-spec.md)'s working-set estimates (~16 entries for the
  four concurrent workloads it models) that is affordable, and
  `I-R8`'s quota is what stops it being affordable *at another BMID's expense*.

- **`I-R6` — the reserved BMIDs are blocked, not bypassed.** BMID `0x00` and BMID
  `0xFF` are denied like any other unmapped BMID: their `BMID_BYPASS` bits reset to
  0 like the rest, and `WRITE_ENTRY` refuses to install an entry tagged with either,
  so they cannot be mapped either. [bus/fabric-spec.md §4.3](../bus/fabric-spec.md)
  previously made `0xFF` a *permanent* bypass and stated no rule forbidding the
  fabric from assigning it to a master port — the "MUST NOT assign" it wrote for
  `0x00` had no counterpart for `0xFF`. A diagnostic path that bypasses the IOMMU is
  a DMA path that bypasses the IOMMU, and on a board with an exposed JTAG connector
  it is a physically-reachable one.

- **`I-R7` — detach re-protects before release, in that order.** When a device is
  detached, released, reset or handed to a different owner, the sequence is:
  (1) `INVALIDATE_BMID` for that BMID; (2) confirm `BMID_BYPASS[BMID] = 0`;
  (3) only then release the device or return from the teardown call. **Never the
  other order, and never "restore bypass on detach".** The channel this closes is
  the Thunderclap window reopened at the end of a device's life rather than at the
  start: between release and re-protection the device is a fully-privileged DMA
  master with a driver that has stopped watching it, and under the previous reset
  polarity "re-protection" and "return to bypass" were the *same edit*. This is the
  clause [security/threat-model.md §7.7](../security/threat-model.md) recorded as
  inherited without backing; the derivation is that the existing text specified the
  opposite — [linux-spec.md §10.1](linux-spec.md) tests that attach and detach
  *"toggle the `BMID_BYPASS` bit"*, and a toggle back to 1 is a release into bypass.

- **`I-R8` — the IOTLB is quota'd per BMID.** Each BMID that has been claimed has a
  **reservation** *r* (entries no other BMID may take) and a **cap** *c* (entries it
  may not exceed), with `Σr ≤ entries`. Allocation is by software (§4.4), so this is
  a rule on the allocator, and the IOMMU exposes what the allocator needs: a per-BMID
  in-use count in the reserved `0x0200`–`0x0FFF` region. The second clause
  [security/threat-model.md §7.7](../security/threat-model.md) recorded as inherited;
  its derivation is that the shared structure is a **single 64-entry pool with a
  single free-list** ([linux-spec.md §4.2](linux-spec.md)'s `entry_used` bitmap, first-fit),
  and the channel is not the occupancy side channel §7.6 describes for the L2. It is
  worse and simpler: exhausting the pool makes a *victim's* `dma_map_*` return
  `-ENOSPC`, and the victim's next un-mapped DMA is a fault whose documented software
  response (§6.3, [design-spec.md §4.4](design-spec.md)) is *"disable the offending
  device"*. One tenant's device can therefore switch off another tenant's device, at
  will and repeatedly. That is an availability break reachable from a mapping API, not
  a timing channel, and it is why the clause survives.

- **`I-R9` — the IOMMU makes no coherence guarantee.** `CACHEABLE` and `WBA` (§3.8)
  are **attributes forwarded to the fabric**, not promises. See §7 and
  [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md).

- **`I-R10` — every IOMMU control is host-only, and the one delegated control is
  validated.** The block's MMIO is unreachable from a guest:
  [hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md) makes a guest
  access to P4 raise the emulated-MMIO trap, fail-closed and with no address in P4
  exempt. The delegated path is
  `HCALL_HV_IOMMU_MAP(iova, ra, perms, bmid)`
  ([hypervisor/design-spec.md §4.6](../hypervisor/design-spec.md)) — **`bmid` is a
  guest-supplied argument** — and the hypervisor MUST refuse the call unless `bmid`
  lies in the slice assigned to the calling guest. Without that check a guest maps
  its own real address under a *peer's* BMID and either redirects the peer's device
  into its own memory or points the peer's device at memory of its choosing; the
  same applies to `HCALL_HV_IOMMU_UNMAP`, which can silently unmap a peer's live
  ring. `I-R10` is the reason [design-spec.md §3.6](design-spec.md)'s old rationale —
  *"accidentally enabling bypass requires kernel-mode access, the same trust level as
  direct PA access"* — is retired: under the multi-tenant threat model the adversary
  **is** a kernel, and "the same trust level" stopped being an argument.

## 4. IOTLB Structure

### 4.1 Recommended organization

| Parameter | Value |
|-----------|-------|
| Number of entries | 64 |
| Associativity | Fully associative |
| Match pipeline | 1 cycle |
| Update pipeline | 2 cycles |

A fully-associative CAM is preferred over set-associative. The 64-entry size fits in modest FPGA CAM area (~1500 LUTs equivalent). For larger configurations (128 entries), a set-associative SRAM-based design with software-visible indexing may be more area-efficient.

### 4.2 Entry layout (internal, per IOTLB entry)

Each entry stores:

```
VALID         1 bit
GLOBAL        1 bit       If set, BMID match suppressed
BMID          8 bits
IOVA_TAG      26 bits     IOVA[39:14], extends to 40-bit IOVA on J64
PAGE_MASK     4 bits      Determines bit range for tag comparison
PFN           26 bits     Physical frame number
READ          1 bit
WRITE         1 bit
CACHEABLE     1 bit
WBA           1 bit
```

Total per entry: ~70 bits. For 64 entries: ~4.5 Kbit of storage. (The VMID field present in earlier drafts has been **removed** — see [glossary §5](../glossary.md) for the project-wide decision and [hypervisor/design-spec.md §3.7](../hypervisor/design-spec.md) for the ASID-partitioning approach that replaces it.)

For J64 implementations with wider IOVA/PFN, fields extend correspondingly (~96 bits per entry, ~6 Kbit total).

### 4.3 Match function

For each transaction `(BMID, IOVA, RW)`:

```
foreach entry in IOTLB:
    if not entry.VALID:           continue
    if entry.GLOBAL:              continue      # I-R5: never grants
    if entry.BMID != BMID:        continue
    if BMID == 0x00 or BMID == 0xFF: continue    # I-R6
    
    mask_bits = pagemask_to_bits(entry.PAGE_MASK)
    if (entry.IOVA_TAG >> mask_bits) != (IOVA[39:14] >> mask_bits):
        continue
    
    # Match!
    if RW == READ  and not entry.READ:   raise permission_fault
    if RW == WRITE and not entry.WRITE:  raise permission_fault
    
    pfn = entry.PFN | (IOVA[high:low] & page_offset_mask)
    return (pfn, entry.CACHEABLE)

# No match
raise miss_fault
```

The `pagemask_to_bits()` function follows the CPU TLB conventions: `PAGE_MASK=0` → 4KB → compare bits [39:12]; `PAGE_MASK=1` → 16KB → compare [39:14]; `PAGE_MASK=2` → 64KB → compare [39:16]; etc.

If exactly one entry matches: provide translation.  
If zero entries match: raise miss fault and block per `I-R2`.  
If multiple entries match: **the transaction is blocked and an invalid-request
fault is raised** (§6.1). It is not undefined.

> **The last line previously read** *"behavior undefined (software must not program
> overlapping entries)."* That is the wording
> [mmu/security-review.md §2](../mmu/security-review.md) **S-I5** was filed against on
> the CPU side, where the resolution was a multi-hit detector dispatching to a defined
> exception rather than a silent PA pick. The same reasoning applies here and the
> hardware is cheaper: the scan is already `entries`-wide and fully associative, so a
> sticky "second match seen" flag over the scan costs one bit and one OR. A duplicate
> install is a software bug, and a software bug must not be able to select which
> tenant's frame a device reaches. This closes one of the tenant-visible `undefined`
> sites the bar counts under item **L6**, in a document that had not been counted.

### 4.4 Replacement policy and per-BMID quota

Not applicable in hardware — software writes specific indices via `IOTLB_INDEX`.
There is no hardware allocation policy, and that is exactly why `I-R8`'s quota is a
rule on the **allocator** rather than a structure in the IOTLB.

**What hardware owes the allocator.** So that the quota can be enforced and audited
rather than merely asserted, the IOMMU exposes, in the reserved `0x0200`–`0x0FFF`
region, a read-only per-BMID **in-use entry count** — one byte per claimed BMID is
sufficient for the 64-, 128- and 256-entry geometries §9.3 contemplates. Without it
a quota is a number in a driver's private bitmap, and nothing outside that driver
can tell whether it was applied; with it, `I-E5`'s negative test has something to
read.

**What the allocator owes.** Each claimed BMID carries a reservation *r* and a cap
*c*. A `.map` for BMID *B* fails when *B* already holds *c* entries **or** when
granting it would leave fewer than `Σ r` entries for the BMIDs that have not yet
used their reservation — the second condition is the one that actually stops
starvation, and a first-fit allocator over a single `entry_used` bitmap
([linux-spec.md §4.2](linux-spec.md)) has neither.

For convenience, the IOMMU may provide a "find first invalid entry" mechanism via an additional MMIO command:

```
0xA = FIND_FREE   Sets IOTLB_INDEX to the lowest unused entry index,
                  or 0xFF if all entries are valid.
```

Optional but useful for Linux's allocator.

## 5. Translation Pipeline

### 5.1 Latency

| Phase | Cycles |
|-------|--------|
| BMID/IOVA arrive at IOMMU input | 0 |
| BMID_BYPASS lookup | 1 (parallel with IOTLB lookup start) |
| IOTLB tag match | 1 |
| Permission check + PA formation | 1 (overlapped with previous) |
| Forward to DRAM controller | 1 |
| **Total added latency vs. direct PA path** | **0–1 cycles** |

The 1-cycle worst case is the IOTLB tag match; if the bus fabric already requires a registered stage between master and slave, this overlaps and the IOMMU adds zero net latency.

### 5.2 Throughput

Single-lookup IOTLB serves one transaction per cycle. For a 64-bit AXI bus at 100 MHz, this is 800 MB/s of bandwidth covered by translation. If higher throughput is needed (multiple parallel DMA engines), the IOTLB can be dual-ported or replicated.

For Phase 2 j-core targets (Ethernet + Display + USB + SD), aggregate sustained DMA is well under 1 GB/s — single-port IOTLB suffices.

## 6. Fault Handling

### 6.1 Fault detection

Three fault types are detected by hardware:

1. **Miss:** No IOTLB entry matches. Generated when bypass is not active and no entry has `(BMID, IOVA)` matching.
2. **Permission:** An entry matches but the access direction (read/write) is not permitted.
3. **Invalid request:** a refused `WRITE_ENTRY` (`GLOBAL = 1` per `I-R5`, or a
   reserved BMID per `I-R6`), a transaction from a reserved BMID, a multiple-entry
   match (§4.3), or a non-canonical transaction (misaligned beyond what the bus
   allows, reserved fields nonzero).

> **The third class previously ended** *"Optional; implementer may treat as 'always
> permitted' for simplicity."* It is no longer optional and "always permitted" is no
> longer available: three of the four cases above are now the reporting half of a
> deny rule, and a deny that reports nothing is a deny nobody can test.

### 6.2 Fault sequence

On any fault:

1. Latch `BMID`, `IOVA`, `RW` into `FAULT_BMID`, `FAULT_IOVA_LO`, `FAULT_IOVA_HI`, `FAULT_INFO` — *only if `FAULT_PENDING` was clear* (first fault wins; subsequent overflow into `FAULT_COUNT`).
2. Increment `FAULT_COUNT` (saturating at 0xFFFF).
3. Set `FAULT_PENDING` in `IOMMU_STATUS`. If a previous fault was already pending, set `FAULT_OVERFLOW` too.
4. Complete the transaction toward the originating master per `I-R2` — read data
   zero, write data discarded, acknowledge asserted.
5. If `IOMMU_CTRL.FAULT_IRQ_EN` is set, raise the IOMMU interrupt line.

**Steps 1–4 do not depend on step 5, and step 4 does not depend on steps 1–3.** The
block is unconditional: it happens with the IRQ masked, with `FAULT_PENDING` already
set, with `FAULT_COUNT` saturated, and with no software having ever touched the
block. This is stated because every one of those is a state a machine reaches during
boot under `I-R1`, and a deny that stops working once the fault registers are full
would be a deny an attacker can exhaust.

### 6.3 Fault recovery

Software responsibility:

1. Read `FAULT_BMID`, `FAULT_IOVA_*`, `FAULT_INFO` to identify the offender.
2. Take corrective action: log to dmesg, disable the offending device, optionally re-establish mappings if the fault was a "race during teardown" condition.
3. Write 1 to `FAULT_PENDING` and `FAULT_OVERFLOW` bits in `IOMMU_STATUS` to clear.
4. Read `FAULT_STATUS` again to confirm clear; if `FAULT_OVERFLOW` was set, log that additional faults were lost.

The IOMMU interrupt should be a level interrupt that stays asserted while `FAULT_PENDING` is set. This avoids missed-interrupt issues with edge interrupts.

## 7. Cache Coherency — the IOMMU is not the owner

### 7.1 Per-entry attributes, not guarantees

The `CACHEABLE` and `WBA` bits in each IOTLB entry are **attributes the IOMMU
forwards to the fabric alongside the translated PA**. The IOMMU asserts nothing
about what the fabric or the caches then do with them. `I-R9`.

> **§7.1 previously read** *"`CACHEABLE = 1`: Transaction is coherent. Reads observe
> CPU writes still in cache; writes invalidate matching cache lines on CPUs"*, and
> §7.2 previously read *"The bus fabric is responsible for routing snoop traffic; the
> IOMMU just sets the coherency mode per transaction."* **Both are withdrawn: they
> promise a mechanism that exists in no specification and in no repository.**
>
> The IOMMU has no path to any cache. It sits between the fabric and the DRAM
> controller ([design-spec.md §4.1](design-spec.md)); its only outputs are a PA and
> these attribute bits. And the fabric it delegates to does not offer the service:
> [bus/fabric-spec.md §7.1](../bus/fabric-spec.md) says the snoop bus's **source** is
> *"the L2's directory / snoop driver … The L2 is the single originator of snoop
> traffic"* and its **destination** is *"every CPU's L1-D snoop port"*. A DMA master
> is neither, and the L2 directory's `dir_vec` has one bit per **core**
> ([cache/l2-spec.md §7.3](../cache/l2-spec.md)), not per bus master, so a device is
> invisible to the protocol by construction. There is no "point-to-point coherency"
> mode for `WBA` to hint at either; that sentence described an option no spec defines.
>
> A first-order reading of the plan's phrasing — *"the L2 exposes no fabric snoop
> port"* — is right about the conclusion and wrong about the structure, and the
> difference matters to whoever implements this. The L2's directory **is** a snoop
> filter; what it filters is *L1-D copies for the L2's own coherence protocol*. It
> was never a port through which a fabric master could snoop or invalidate. And the
> distinction is not academic, because a snoop port that a DMA write could drive
> **does exist today** — on the L1-D, not the L2 — and is tied off. See
> [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md).

### 7.2 What software must therefore do

DMA on J-Core is **non-coherent** at every tier this project has specified or built.
The contract, its two directions, the hardware that would change it and the
kernel-side state of it are owned by
[decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md), which
also records that on `linux@origin/jcore` the J4 cache-maintenance operations the DMA
API calls are currently **no-ops**. Nothing in this document may be read as relieving
a driver of that obligation.

## 8. Reset State

On hardware reset:

| Register | Reset value |
|----------|-------------|
| IOMMU_CTRL | `0x00000001` (`ENABLE`=1, `SUPER_BYPASS`=0, `SB_LOCK`=0, `FAULT_IRQ_EN`=0) |
| IOMMU_STATUS | `0x00000011` (`VIRGIN`=1, `ENABLED`=1) |
| BMID_BYPASS_* | All 0s (every BMID goes through the IOTLB) |
| IOTLB entries | All VALID=0 |
| FAULT_* registers | 0 |

**Out of reset the IOMMU is active and every BMID is denied.** No DMA succeeds
until software has claimed a BMID and installed a mapping for it. This is `I-R1`.

> **This section previously ended** *"Linux must explicitly initialize the IOMMU
> before clearing `BMID_BYPASS` bits. Until then, the IOMMU is functionally absent —
> all DMA passes through with `PA = IOVA`."*

**The cost is real and it is the requirement, not an argument against it.** A board
whose boot path uses a DMA engine must program the IOMMU before that DMA, which means
the bootrom acquires an IOMMU-init step alongside the SDRAM-controller and AIC2 init
it already performs ([bus/fabric-spec.md §9.2](../bus/fabric-spec.md)) — or uses PIO
until the kernel is up. On the boards this project actually builds the cost is
currently **zero**: the DMA leg of the DDR mux is tied to a constant zero on every
one of them (`jcore-soc:targets/boards/{ulx3s,mimas_v2,turtle_1v0,microboard}/soc.vhd`),
`jcore-soc:components/dma/` contains a `README` reading *"Stub implementation"* and no
entity, and every peripheral that exists — including the Ethernet MAC — is a bus
**slave**. There is no boot-time DMA to break.

**Reset state is asserted by reading the registers out of reset** (`I-E0`), never by
reading this table.

## 9. Future-Compatibility Notes

### 9.1 Hypervisor extension (Phase 3)

The hypervisor extension ([hypervisor/design-spec.md](../hypervisor/design-spec.md)) **does not add new IOMMU hardware fields**. Guest isolation for DMA is achieved by partitioning the 8-bit BMID space in software: the hypervisor allocates BMID ranges to guests and programs IOMMU page tables per-BMID. No VMID field, no `IOMMU_VMID_CTRL` register. See [glossary §5](../glossary.md) for the project-wide decision.

### 9.2 ATS / PRI (PCIe-like extensions)

If the J-Core SoC ever grows a PCIe root complex, the IOMMU would need ATS (Address Translation Services) and PRI (Page Request Interface) extensions. These are Phase 4+ work and would substantially change the IOMMU's role.

### 9.3 Larger IOTLB

Going from 64 to 128 or 256 entries is a parameter change. The MMIO interface scales naturally — `IOTLB_INDEX` just gets more meaningful bits.

## 10. Verification Points

Critical RTL verification:

1. **Bypass mode:** With `BMID_BYPASS[N] = 1`, transactions from BMID N produce `PA = IOVA` with zero added latency.
2. **Translation hit:** With a valid entry programmed for `(BMID, IOVA range)`, transactions hit and produce correct PA.
3. **Translation miss:** With no matching entry, transactions block, fault is latched, IRQ raised (if enabled).
4. **Permission fault:** Write transaction to RO entry blocks correctly.
5. **PageMask:** All 10 PageMask values produce correct match-mask behavior; superpage entries match all IOVAs within their range.
6. **GLOBAL bit:** a `WRITE_ENTRY` carrying `GLOBAL = 1` is refused, and an entry
   holding `GLOBAL = 1` matches no BMID. *(This point previously read "Transactions
   match a GLOBAL entry regardless of BMID" — the behaviour it asked an implementer
   to verify is the behaviour `I-R5` forbids.)*
7. **INVALIDATE_BMID:** Clears all and only entries with matching BMID.
8. **INVALIDATE_ALL:** Clears all entries.
9. **Concurrent access:** IOTLB writes don't disturb in-flight translations; if a transaction is mid-flight when its entry is invalidated, behavior is well-defined (typically: transaction completes with old translation, or transaction is aborted — implementer's choice but must be documented).
10. **FAULT_PENDING latch:** First fault wins; subsequent faults until clear bump COUNT but don't overwrite BMID/IOVA registers.
11. **Reset:** All registers and entries match §8.

### 10.1 Negative tests for the deny rules — `I-E0`–`I-E6`

Bar item **L2** requires *"a negative test per clause, because every clause here
fails silently and open"* ([security/threat-model.md §8](../security/threat-model.md)).
These are those tests. Each states the result that would **end** it, per the
remediation plan's kill-criteria rule.

| # | Test | Must fail before, pass after | Kill criterion |
|---|---|---|---|
| `I-E0` | Read `IOMMU_CTRL`, `IOMMU_STATUS` and all eight `BMID_BYPASS_*` words out of reset, before any write. Assert `0x00000001`, `0x00000011`, all zeros. | Fails on the retired reset values | If the model cannot be observed before its first MMIO write, the test reports **not runnable** rather than passing — a reset value read after initialisation is the initialisation's value, not the reset's |
| `I-E1` | An **unclaimed** BMID — one no driver has touched, with no IOTLB entry — issues a DMA read. Assert: data returned is zero, the write case leaves memory unchanged, `FAULT_PENDING` sets and `FAULT_BMID` holds that BMID. | Fails on all-bypass reset (the read succeeds and returns memory) | If the harness cannot originate a transaction under an arbitrary BMID, it reports **not runnable**. This is the clause an implementer can otherwise satisfy entirely on paper |
| `I-E2` | Set `SUPER_BYPASS`, clear it, write one IOTLB entry (so `VIRGIN` clears and `SB_LOCK` arms), then write `SUPER_BYPASS = 1` again. Assert the read-back is still 0 **and** that a transaction from an unmapped BMID is still blocked. | Fails without `I-R4` | Asserting only the read-back is insufficient: a register that reads 0 while the bypass mux is still open passes it. The transaction assertion is the test |
| `I-E3` | Attach a device, map a buffer, then detach. Assert that a DMA from that BMID is blocked **before the teardown call returns**, and that `BMID_BYPASS[BMID]` reads 0 afterwards. | Fails on any implementation that restores bypass on detach | A test that checks only the post-return state cannot see the window `I-R7` exists to close; the assertion must be made from a concurrent master or by a transaction injected mid-teardown |
| `I-E4` | Install an entry with `GLOBAL = 1` (expect refusal), then force one into the array by whatever back door the harness has, and issue a transaction from a BMID the entry does not name. Assert the transaction is blocked. | Fails on the retired match function, where it succeeds | If the harness has no way to place an entry the `WRITE_ENTRY` path refuses, only the install-refusal half is exercised and the test reports **partial** — the lookup term is the half that matters, because it is the one that holds when the install path has a bug |
| `I-E5` | BMID *A* maps buffers until it holds its cap. Assert BMID *B*, which has used none of its reservation, can still map, and that *B*'s device takes no fault. | Fails on a first-fit single free-list | A pass obtained by giving *A* a cap larger than the pool proves nothing; the test must run with `Σr` genuinely exceeding what *A* is allowed |
| `I-E6` | A device writes a buffer the CPU has previously read; the CPU reads it again. Assert the new data is returned. | **Fails today, at every tier** — see [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md) | Not runnable until a DMA master exists. It is listed here rather than deferred because it is the test that distinguishes a coherence *contract* from a coherence *claim* |

`I-E1`, `I-E2` and `I-E3` are the three
[security/threat-model.md §8](../security/threat-model.md) names as the minimum for
**L2** to move; `I-E0` is its "reset state is asserted by reading the registers"
sentence made into a test; `I-E4`, `I-E5` and `I-E6` cover the clauses it left to
this task.

## 10.2 Prior art (pre-2006)

Per [glossary.md §2](../glossary.md), every non-trivial mechanism this revision adds
carries pre-2006 prior art matched on **mechanism, not motivation**. The IOMMU's
pre-existing mechanisms — per-device translation contexts, the software-loaded
translation cache, the page-size encoding — are cited in
[design-spec.md §9](design-spec.md) and are not repeated here.

| Mechanism added or changed here | Pre-2006 prior art |
|---|---|
| **`I-R1`** An I/O address translator that refuses a transfer whose map entry is not valid, rather than passing it through | DEC UNIBUS map (PDP-11 / VAX-11 UNIBUS adapters, 1970s): each map register carries a **map-valid bit (MRV)**; with it clear the register *"is not set up, and will not respond to the Unibus"* — the transfer takes an NXM timeout and sets an error-status bit. Deny-on-invalid is the original behaviour of I/O mapping hardware, not a modern hardening |
| **`I-R1`** (policy half) Basing access decisions on permission rather than exclusion | Saltzer & Schroeder, *The Protection of Information in Computer Systems*, Proc. IEEE 63(9), 1975 — **fail-safe defaults**. Cited as the design principle; the mechanism citation is the row above |
| **`I-R2`** A refused bus transaction that **completes** with a defined datum and discards the write, instead of erroring or hanging | PCI Local Bus Specification rev 2.1 (June 1995), **master abort**: a host bridge returns all-1s on a read terminated by master abort and discards the write data. Identical mechanism; this spec chooses **zeros** rather than all-1s because zero is already this project's defined-safe value for an unowned region (`sq/spec.md`'s guest reads, `security/threat-model.md` §8 **L6**'s `undefined`-site count) and because all-1s is a plausible datum on a bus with no separate "no device" signature |
| **`I-R4`** A configuration bit that can be set once and thereafter cleared only by hardware reset | Intel Advanced Boot Block Flash Memory (B3/C3) datasheets, 1996–1998: the **Lock-Down** state, *"set by the Lock-Down command … cannot be cleared by software—only by device reset or power-down"* |
| **`I-R4`** (the self-arming half) A hardware lock that **advances irreversibly as boot proceeds**, without the software it protects against having to ask | IBM 4758 secure coprocessor **ratchet**: a hardware lock module whose setting the boot layers *increment* — Miniboot 0 can *"request an increment of the hardware lock setting"* — and which protects storage segments from later layers. Dyer, Lindemann, Perez, Sailer, van Doorn, Smith & Weingart, *Building the IBM 4758 Secure Coprocessor*, IEEE Computer 34(10), 2001; the design is described earlier in Smith & Weingart, *Building a High-Performance, Programmable Secure Coprocessor*, 1999 |
| **`I-R8`** Partitioning a shared cache by context, with per-context reservations, to bound one client's effect on another | Kirk, *SMART (Strategic Memory Allocation for Real-Time) cache design*, IEEE RTSS 1989, pp. 229–237 (segments allocated per task); Stone, Turek & Wolf, *Optimal partitioning of cache memory*, IEEE Trans. Computers 41(9), 1992, pp. 1054–1068 |
| **`I-R5`** A translation-cache tag term that makes a dangerous entry fault at lookup rather than grant | In-tree: [mmu/security-review.md §2](../mmu/security-review.md) **S-I7**, resolved in `jcore-cpu:core/tlb.vhd`. The pre-2006 structure is the ordinary per-entry validity/permission term of any tagged translation cache (SH-4 UTLB `V`/`PR`, 1998; SPARC v9 TTE valid bit, 1994) |
| The DMA-side snoop mechanism §7 declines to promise, and [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md) sites elsewhere | Motorola M68040: `SC1`/`SC0` **snoop control** inputs sampled during an *alternate bus master* transfer, with encodings including "source dirty, invalidate line" — a DMA master driving an invalidation of the CPU's cache. *M68040 User's Manual*, Motorola, 1990 (rev. 1992/1993) |

**Rule 2 of [glossary.md §2.1](../glossary.md) applies to `I-R4` and was checked
rather than assumed.** The *structure* — a sticky lock bit — is plainly pre-2006, and
the *purpose* here (locking a DMA-bypass control before untrusted tenants run) is
younger than the structure. The purpose-specific combination this project is closest
to is "IOMMU bypass locked at handoff", which is the Apple DART / Windows Kernel DMA
Protection shape named as `LITERATURE` in
[security/threat-model.md §8](../security/threat-model.md). What is claimed here is
narrower and older: a lock on a *register*, armed by a *state transition of the block
that owns it*, which is the 4758 ratchet and the flash Lock-Down verbatim. No new
combination is introduced by `I-R1`, `I-R2`, `I-R3`, `I-R5`, `I-R6` or `I-R7`, each of
which either deletes a mechanism or changes a reset value.

*This section is not legal advice and not a freedom-to-operate opinion; per
[glossary.md §2](../glossary.md), a load-bearing finding warrants a professional
search before RTL commits.*

## 11. Cost Estimation

For the recommended 64-entry IOTLB:

| Item | Estimate |
|------|----------|
| IOTLB storage (CAM) | ~5 Kbit |
| BMID_BYPASS bitmap | 256 bits (32 bytes) |
| Status / fault registers | ~256 bits |
| Command/data interface registers | ~256 bits |
| Match logic (parallel comparators) | ~600 LUTs |
| MMIO decoder + control FSM | ~300 LUTs |
| Fault detection logic | ~100 LUTs |
| Bus interface (AXI master/slave) | ~500 LUTs (depends on fabric) |
| Total | ~1500 LUTs, ~6 Kbit storage |

Smaller variants (32-entry) save roughly 40% of LUTs and storage. Larger variants (128-entry) scale roughly linearly. Hardware cost is modest by FPGA standards — single-digit percentage of a J-Core CPU core's area.

## 12. Hardware Test Hooks

Optional but useful for bring-up:

- A debug register that reports the most recent IOTLB hit details (entry index, BMID, IOVA, PA): aids testing without runtime instrumentation
- Statistics counters (per-BMID): translations served, miss count, hit count — sampled by software for performance tuning
- A "test mode" bit that injects synthetic transactions for self-test

None of these are essential; they're conveniences for the validation team.
