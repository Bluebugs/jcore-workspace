# J-Core IOMMU Hardware Implementation Specification (Phase 2)

**Status:** Draft  
**Scope:** RTL implementation guide for the J-Core SoC IOMMU  
**Audience:** Hardware engineers implementing the IOMMU block  
**Prerequisites:** Phase 1 hardware spec (`02-hardware-spec.md`), Phase 2 design spec (`04-iommu-design-spec.md`)

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
- Bus fabric implementation (assumes AXI or compatible; BMID-tagging at the master ports)
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

BMID is set by the bus fabric based on the initiator's physical position. Devices cannot spoof BMID; it's a hardwired property of the fabric layout.

### 2.2 Bus response

On hit, the IOMMU forwards the transaction with `IOVA` replaced by the translated PA. The bus ID and burst parameters are preserved.

On miss, the IOMMU responds to the master with a bus error (AXI `SLVERR` or equivalent). The data phase is suppressed for reads; writes are dropped.

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
[31:8]   reserved (0)
[7:4]    DEFAULT_PERM   Permission applied when bypass active.
                        Bit 7 = read, bit 6 = write, others reserved.
                        Default 0xC (read+write enabled).
[3]      FAULT_IRQ_EN   Enable fault interrupt
[2]      SUPER_BYPASS   If set, all transactions bypass regardless
                        of BMID_BYPASS (debug/recovery only)
[1]      INVALIDATE_ALL Write 1: invalidate all IOTLB entries
                        (self-clearing)
[0]      ENABLE         0 = IOMMU bypassed for all masters
                        1 = IOMMU active (per BMID_BYPASS)
```

Reset value: `0x000000C0` (disabled, but default-permissions set for orderly bypass).

### 3.2 IOMMU_STATUS (offset 0x0004)

```
[31:8]   reserved (0)
[7]      FAULT_PENDING  At least one fault has been logged but not cleared
[6]      FAULT_OVERFLOW More than one fault occurred since last clear
                        (only first is in FAULT_* registers)
[5:4]    reserved
[3]      IOTLB_WRITE_BUSY Asserted while an IOTLB write is in progress
[2]      reserved
[1]      INVALIDATE_BUSY  Asserted during INVALIDATE_ALL
[0]      ENABLED          Mirror of IOMMU_CTRL.ENABLE (read-only here)
```

Status bits are write-1-to-clear except where noted. ENABLED is read-only.

### 3.3 IOMMU_VERSION (offset 0x0008)

```
[31:24]  reserved (0)
[23:16]  IOTLB_ENTRIES  Number of IOTLB entries (read-only)
[15:8]   VMID_BITS      Implemented VMID field width (0 in Phase 2)
[7:0]    VERSION        IOMMU version. 0x01 = Phase 2 baseline.
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
- WRITE_ENTRY: latches `IOTLB_TAG/DATA` into entry `IOTLB_INDEX`; asserts `IOTLB_WRITE_BUSY` for ≤2 cycles
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
[7:0]    reserved
[1]      GLOBAL         If set, match any BMID
[0]      VALID          1 = entry valid, 0 = invalid (match always fails)
```

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
[3]      CACHEABLE      Device transaction snoops CPU caches
[2]      WBA            Write-back acknowledge (for posted writes)
[1:0]    reserved
```

### 3.9 BMID_BYPASS_* (0x0100–0x011F)

256-bit bitmap spread across eight 32-bit registers. Bit N (counting from LSB of register 0) controls BMID N:

- Bit clear (0): BMID N transactions go through IOTLB lookup
- Bit set (1): BMID N transactions bypass (PA = IOVA)

Reset value: all bits set (all BMIDs bypass). Linux IOMMU driver clears bits as it claims devices.

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
VMID          8 bits      Hardwired to 0 in Phase 2 (reserved)
IOVA_TAG      26 bits     IOVA[39:14], extends to 40-bit IOVA on J64
PAGE_MASK     4 bits      Determines bit range for tag comparison
PFN           26 bits     Physical frame number
READ          1 bit
WRITE         1 bit
CACHEABLE     1 bit
WBA           1 bit
```

Total per entry: ~78 bits. For 64 entries: ~5 Kbit of storage.

For J64 implementations with wider IOVA/PFN, fields extend correspondingly (~96 bits per entry, ~6 Kbit total).

### 4.3 Match function

For each transaction `(BMID, IOVA, RW)`:

```
foreach entry in IOTLB:
    if not entry.VALID:           continue
    if not entry.GLOBAL and entry.BMID != BMID:  continue
    if entry.VMID != 0:           continue   # VMID reserved
    
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
If zero entries match: raise miss fault.  
If multiple entries match: behavior undefined (software must not program overlapping entries).

### 4.4 Replacement policy

Not applicable — software writes specific indices via `IOTLB_INDEX`. There is no hardware allocation policy.

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
3. **Invalid request:** A non-canonical transaction (e.g., misaligned beyond what AXI allows, or reserved fields nonzero). Optional; implementer may treat as "always permitted" for simplicity.

### 6.2 Fault sequence

On any fault:

1. Latch `BMID`, `IOVA`, `RW` into `FAULT_BMID`, `FAULT_IOVA_LO`, `FAULT_IOVA_HI`, `FAULT_INFO` — *only if `FAULT_PENDING` was clear* (first fault wins; subsequent overflow into `FAULT_COUNT`).
2. Increment `FAULT_COUNT` (saturating at 0xFFFF).
3. Set `FAULT_PENDING` in `IOMMU_STATUS`. If a previous fault was already pending, set `FAULT_OVERFLOW` too.
4. Return bus error to the originating master.
5. If `IOMMU_CTRL.FAULT_IRQ_EN` is set, raise the IOMMU interrupt line.

### 6.3 Fault recovery

Software responsibility:

1. Read `FAULT_BMID`, `FAULT_IOVA_*`, `FAULT_INFO` to identify the offender.
2. Take corrective action: log to dmesg, disable the offending device, optionally re-establish mappings if the fault was a "race during teardown" condition.
3. Write 1 to `FAULT_PENDING` and `FAULT_OVERFLOW` bits in `IOMMU_STATUS` to clear.
4. Read `FAULT_STATUS` again to confirm clear; if `FAULT_OVERFLOW` was set, log that additional faults were lost.

The IOMMU interrupt should be a level interrupt that stays asserted while `FAULT_PENDING` is set. This avoids missed-interrupt issues with edge interrupts.

## 7. Cache Coherency

### 7.1 Per-entry coherency

The `CACHEABLE` bit in each IOTLB entry indicates whether the DMA transaction should snoop CPU caches:

- `CACHEABLE = 1`: Transaction is coherent. Reads observe CPU writes still in cache; writes invalidate matching cache lines on CPUs.
- `CACHEABLE = 0`: Transaction bypasses caches. Software must flush CPU caches before reads and invalidate before writes.

The bit is per-entry, so different DMA buffers can have different coherency requirements. Framebuffers typically benefit from cacheable mappings (CPU writes are immediately visible to scanout); high-throughput Ethernet may prefer non-cacheable to avoid cache pollution.

### 7.2 SMP considerations

On SMP systems, cache-coherent DMA must snoop all CPU caches. The bus fabric is responsible for routing snoop traffic; the IOMMU just sets the coherency mode per transaction.

If the bus fabric supports only point-to-point coherency (not broadcast), the IOMMU can hint via the `WBA` bit when a write should be acknowledged before cache writeback completes — useful for posted writes where the device doesn't need ordering.

## 8. Reset State

On hardware reset:

| Register | Reset value |
|----------|-------------|
| IOMMU_CTRL | `0x000000C0` (disabled, default permissions R+W) |
| IOMMU_STATUS | `0x00000000` |
| BMID_BYPASS_* | All 1s (every BMID bypasses) |
| IOTLB entries | All VALID=0 |
| FAULT_* registers | 0 |

Linux must explicitly initialize the IOMMU before clearing `BMID_BYPASS` bits. Until then, the IOMMU is functionally absent — all DMA passes through with `PA = IOVA`.

## 9. Future-Compatibility Notes

### 9.1 VMID activation (Phase 3)

When hypervisor support is added:

- The VMID field in IOTLB entries activates (currently hardwired 0).
- A new register `IOMMU_VMID_CTRL` controls per-BMID VMID mapping.
- New IOTLB_CMD encoding for VMID-specific invalidation.

8-bit VMID is reserved now in IOTLB entries. No new MMIO offset allocation needed today.

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
6. **GLOBAL bit:** Transactions match a GLOBAL entry regardless of BMID.
7. **INVALIDATE_BMID:** Clears all and only entries with matching BMID.
8. **INVALIDATE_ALL:** Clears all entries.
9. **Concurrent access:** IOTLB writes don't disturb in-flight translations; if a transaction is mid-flight when its entry is invalidated, behavior is well-defined (typically: transaction completes with old translation, or transaction is aborted — implementer's choice but must be documented).
10. **FAULT_PENDING latch:** First fault wins; subsequent faults until clear bump COUNT but don't overwrite BMID/IOVA registers.
11. **Reset:** All registers and entries match §8.

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
