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

Inherited from SH-4, extended. Accessed via `LDC Rm, PTEH` / `STC PTEH, Rn` (existing SH-4 encodings) or as MMIO at P4 address `0xFF000000` (for compatibility).

**J32 layout (32 bits) — provisional, see open question below:**
```
[31:14]  VPN[31:14]    Hardware-set on TLB miss, software-set for LDTLB
                       (for the default 16 KB page size; smaller pages
                       extend VPN downward into [13:0])
[13:0]   ASID_TAG[13:0]  Low 14 bits of the 16-bit ASID_TAG.
                       (Upper 2 bits live elsewhere — see open question.)
```

**ASID_TAG width is 16 bits** (canonical, project-wide). The kernel packs the 12-bit ASID proper and a 4-bit generation discriminator into a single 16-bit opaque tag that hardware uses for TLB and TSB comparison:

```
ASID_TAG[15:0] = (ASID[11:0] | (gen_low[3:0] << 12))
```

The TLB-entry tag carries the full 16 bits (see §2.6). The Linux ASID allocator in `docs/mmu/linux-spec.md` §5 produces this 16-bit value directly; hardware does not interpret the split, only the kernel does.

**Open question (PTEH layout): the full 16-bit ASID_TAG does not cleanly fit in PTEH alongside the VPN for sub-64-KB page sizes.** With a 16 KB minimum page, VPN occupies PTEH `[31:14]` (18 bits) leaving 14 bits for ASID_TAG — 2 bits short. Three resolutions are on the table; pick one before RTL:

1. **Min page size becomes 64 KB on the J32 MMU.** VPN occupies `[31:16]` (16 bits); ASID_TAG occupies `[15:0]` (16 bits). Clean. Cost: loses the 16 KB page size as a finest grain on J32; J64 can restore it with a wider PTEH. Aligns with SH-3 conventions (4 KB / 64 KB / 1 MB).
2. **Add a separate ASIDR register holding ASID_TAG[15:14].** PTEH keeps the original layout (ASID_TAG[13:0] at PTEH[13:0]). Adds one new control register and one MMIO offset; LDTLB latches both. Cost: extra register-file plumbing, slightly more complex context-switch sequence.
3. **PTEH widens to 40 or 64 bits, accessed as a register pair on J32.** Cleanest semantically, biggest software impact (PTEH no longer fits in a J32 register; LDC/STC require two operations or a new instruction). Most invasive.

This document currently shows resolution 1 (16 KB page dropped) tentatively in the bit layout above. The Linux spec, hypervisor spec, and IOMMU spec are all consistent with whichever resolution is picked, since they only see the 16-bit `ASID_TAG` value, not the PTEH storage location.

### 2.2 PTEL — Page Table Entry Low

Inherited from SH-4, extended with PageMask. Accessed via `LDC` / `STC` or MMIO at `0xFF000004`.

**J32 layout (32 bits):**
```
[31:14]  PPN[31:14]    Physical page number, software-set
[13:10]  PageMask      log4(page_size / 4 KB), 4 bits:
                       0 = 4 KB,  1 = 16 KB,  2 = 64 KB,
                       3 = 256 KB, 4 = 1 MB,   5 = 4 MB,
                       6 = 16 MB,  7 = 64 MB,  8 = 256 MB,
                       9 = 1 GB,  10–15 reserved
[9]      D (Dirty)
[8]      C (Cacheable)
[7]      U (User accessible)
[6]      W (Writable)
[5]      X (Executable)
[4]      R (Readable; usually implied by Valid)
[3]      G (Global; ignore ASID_TAG in TLB match)
[2]      STALE         Software-only bit, used by lazy TLB shootdown.
                       Hardware ignores. Must be preserved by LDTLB.
[1]      reserved
[0]      V (Valid)
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

Holds the physical base address of the per-CPU TSB and configuration bits.

**Access:** New LDC/STC encoding (see §3) and MMIO at `0xFF000014`.

**J32 layout (32 bits):**
```
[31:N+4] TSB_BASE      Physical address of TSB. Must be aligned to 
                       16 × 2^N bytes (TSB size).
[N+3:4]  reserved (0)
[3:0]    TSB_SIZE_LOG  log2(number of TSB entries). Valid: 6–14
                       (64 to 16384 entries; TSB = 1 KB to 256 KB).
                       For TSB_SIZE_LOG = N, the TSB spans 16 × 2^N
                       bytes (each entry is 16 bytes).
```

On J64, TSB_BASE widens to a 64-bit physical address. The low 4 bits remain `TSB_SIZE_LOG`.

### 2.7 TSBCFG — TSB Configuration (NEW)

Holds the hash configuration used by hardware when computing TSBPTR.

**Access:** New LDC/STC encoding and MMIO at `0xFF000018`.

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

### 2.8 TSBPTR — TSB Slot Pointer (NEW, read-only)

Hardware-populated on every TLB miss. Holds the address (in physical memory) of the TSB slot where the missing translation, if cached, would be found.

**Access:** STC only (read-only from software). MMIO at `0xFF00001C` (also read-only).

**Computation (hardware, on TLB miss):**
```
hash = VPN ^ ((HASH_MODE == 1) ? (VPN >> HASH_SHIFT) : 0)
mask = (1 << TSBBR.TSB_SIZE_LOG) - 1
TSBPTR = (TSBBR.TSB_BASE) | ((hash & mask) << 4)
```

The `<< 4` is because each TSB entry is 16 bytes. TSBPTR is therefore naturally aligned to a 16-byte boundary within the TSB.

### 2.9 CPUINFO — CPU Information (NEW, MMIO only)

Read-only MMIO register, per-CPU-distinct. Each CPU reading address `0xFF000020` sees its own hart ID and capability flags.

**Layout (32 bits):**
```
[31:16]  CORE_CAPS     Implementation-defined capability flags
                       (FPU present, DSP present, hypervisor mode, etc.)
[15:8]   reserved (0)
[7:4]    reserved (0)  Room to widen hart ID for >16 CPUs
[3:0]    HART_ID       This CPU's hart number (0–15)
```

No new instruction is needed; standard `MOV.L @rA, Rn` from a register holding `0xFF000020` reads it. The SoC's address decoder routes this access to a small per-core hard-wired register.

## 3. Instruction Encodings

The SH ISA reserves the LDC/STC family for control register transfers via the pattern:

```
LDC Rm, REG :  0100 mmmm xxxx 1110
STC REG, Rn :  0000 nnnn xxxx 0010
```

where `xxxx` selects the register. SH-4 uses values 0000–0100 (SR, GBR, VBR, SSR, SPC) and 1nnn (R0_BANK–R7_BANK). Values 0101, 0110, 0111 are free.

### 3.1 New LDC/STC encodings

| Mnemonic | Encoding | Hex Pattern |
|----------|----------|-------------|
| `LDC Rm, TSBBR` | `0100 mmmm 0101 1110` | `0x405E \| m<<8` |
| `STC TSBBR, Rn` | `0000 nnnn 0101 0010` | `0x0052 \| n<<8` |
| `LDC Rm, TSBCFG` | `0100 mmmm 0110 1110` | `0x406E \| m<<8` |
| `STC TSBCFG, Rn` | `0000 nnnn 0110 0010` | `0x0062 \| n<<8` |
| `STC TSBPTR, Rn` | `0000 nnnn 0111 0010` | `0x0072 \| n<<8` |

`LDC Rm, TSBPTR` (encoding `0x407E`) is **reserved** — TSBPTR is read-only from software. Decoding this should raise illegal-instruction exception.

### 3.2 LDTLB.R — Load TLB and Return

New single-cycle instruction that fuses LDTLB and RTE. Equivalent to executing LDTLB followed immediately by RTE, but atomically (no observable state between).

**Encoding:** `0000 0000 0110 1000` = `0x0068`

**Semantics:**
1. Latch the current values of PTEH and PTEL into a TLB entry, chosen by the LRU/replacement policy (same as existing LDTLB).
2. Restore PC ← SPC, SR ← SSR.
3. Branch to the new PC.

**Delay slot:** like RTE, LDTLB.R has a one-instruction delay slot. The instruction in the delay slot executes before the branch takes effect.

**Privilege:** Privileged. Causes illegal-instruction trap if executed with SR.MD=0.

The existing LDTLB (encoding `0x0038`) is preserved for compatibility; the only difference is LDTLB.R also returns.

## 4. TLB Structure

### 4.1 Recommended TLB organization (suggestion, not mandate)

| Parameter | Value |
|-----------|-------|
| Number of entries | 32 (J3), 64 (J64) |
| Associativity | Fully associative |
| Split I/D | No (unified) on J3; implementer's choice on J64 |
| Replacement | NRU or random |

A unified, fully-associative TLB simplifies the indexing problem when mixing page sizes. Set-associative TLBs require either multiple lookups, VPN-partitioning by size, or skewed associativity — all of which add gates and timing pressure. For 32-entry sizes, fully-associative CAM is reasonable in FPGA.

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

Total ~91 bits per entry on J32, ~131 bits on J64. For 32 entries: ~3 Kib of state. The VMID field present in earlier drafts has been **removed** (see project-wide decision in [glossary §5](../glossary.md)); hypervisor isolation is achieved via ASID partitioning, not VMID tagging.

### 4.3 TLB match function

For each entry on a translation request:
```
match = entry.VALID &&
        (entry.VPN[high : pagebits_for_PageMask] == VA[high : pagebits])
match = match && (entry.GLOBAL || entry.ASID_TAG == PTEH.ASID_TAG)
```

The bit range compared depends on the entry's PageMask: a 16 KB page compares VPN[35:14] (J64) or VPN[31:14] (J32); a 64 KB page compares VPN[35:16]; etc.

If exactly one entry matches: it provides the translation.  
If zero entries match: hardware initiates the miss sequence (see §5).  
If more than one matches: behavior undefined — software must not write duplicate entries. (Same rule as SH-4 and UltraSPARC.)

## 5. TLB Miss Exception Sequence

When a memory access misses the TLB and translation is enabled (MMUCR.AT=1):

1. Compute hash and TSBPTR (see §2.8). Store result in TSBPTR register.
2. Latch the faulting effective address into TEA.
3. Latch the faulting VPN (extracted from VA based on the default page size, 16 KB) into PTEH[31:14] (J32) or PTEH[high:14] (J64). **The ASID_TAG bits of PTEH are preserved** — the kernel has set them at context switch.
4. Save PC → SPC and SR → SSR. Save register-bank state if applicable.
5. Update SR: set MD=1, RB=1, BL=1, IMASK=0xF.
6. Jump to `VBR + 0x400` (instruction-fetch miss) or `VBR + 0x420` (data-load miss) or `VBR + 0x440` (data-store miss) — same vector layout as SH-4.

Exception priorities and ordering relative to other interrupts follow SH-4 conventions.

## 6. Register Banking on Exception Entry

Inherited from SH-3/SH-4 unchanged. On any exception (including TLB miss):

- If SR.MD was 0 (user mode) and SR.RB was 0, transition to MD=1, RB=1. Bank 1 R0–R7 are now visible; bank 0 R0–R7 are preserved.
- If already in MD=1 with RB=1, no bank change.
- R8–R15 are not banked; software must save/restore them if used.

The TLB-miss handler's hot path (described in §7) uses only R0–R3 of bank 1, requiring no register saves.

## 7. Recommended TLB Miss Handler

For reference. Implementation in software, but documenting the expected sequence:

```asm
        ! At VBR+0x400, SR.RB=1, bank 1 selected.
tlb_miss:
        stc     tsbptr, r0      ! Read pre-computed TSB slot address
        mov.l   @r0+, r1        ! Load TTE tag (and advance r0 to data)
        stc     pteh, r2        ! Load current faulting tag
        cmp/eq  r1, r2          ! Match?
        bf/s    tsb_miss_slow   ! Mismatch -> slow path
         mov.l  @(4, r0), r3    ! delay slot: load TTE data
        ldc     r3, ptel        ! Stage data into PTEL
        ldtlb.r                 ! Install entry, return from exception
         nop                    ! Delay slot of LDTLB.R
```

Hot path: 7 instructions. With the slow path inlined, the full handler fits in ~30 instructions.

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
3. **LDTLB.R atomicity:** No observable interrupt window between TLB write and PC/SR restore.
4. **MMUCR.TI:** Single-cycle invalidation of all entries; self-clearing.
5. **Register banking on TLB miss:** Bank 1 R0–R7 visible to handler, bank 0 preserved.
6. **PTEH preservation across miss:** ASID_TAG bits preserved when hardware writes VPN.
7. **STALE bit preservation:** LDTLB carries the STALE bit from PTEL into the TLB entry intact.
8. **Per-CPU CPUINFO routing:** Each CPU reads a distinct HART_ID at `0xFF000020`.
9. **Exception priority:** TLB miss vs. instruction-fetch fault vs. higher-priority interrupts handled correctly.
10. **Reset state:** All MMU registers cleared, TLB invalidated, MMU disabled.

## 12. Estimated Hardware Cost

Beyond inheriting the SH-4 MMU structure:

| Addition | Estimated cost |
|----------|----------------|
| TSBBR, TSBCFG registers | ~96 bits flop (J32), 160 bits (J64) |
| TSBPTR register | ~32 bits (J32), 64 bits (J64) |
| TSBPTR computation (hash, XOR, mask, OR) | ~50 LUTs |
| Extended ASID_TAG (8 → 16 bits) | 8 bits per TLB entry |
| PageMask (4 bits per TLB entry) | 4 bits per TLB entry |
| STALE bit per TLB entry | 1 bit per entry |
| LDTLB.R decode | ~10 LUTs |
| CPUINFO MMIO | ~32 bits flop per core + decoder |

For 32 TLB entries: ~600 bits of additional TLB state per CPU. Plus ~200 LUTs of new logic per CPU. Modest by FPGA standards.
