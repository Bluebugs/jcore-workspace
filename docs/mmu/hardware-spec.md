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

Inherited from SH-4 in spirit, but **VPN-only** in this revision. Accessed via `LDC Rm, PTEH` / `STC PTEH, Rn` (existing SH-4 encodings) or as MMIO at P4 address `0xFF000000`. The 16-bit `ASID_TAG` lives in the separate **ASIDR** register (see §2.1a) — a deliberate alignment with UltraSPARC's `PRIMARY_CONTEXT` model (sun4u, 1995). This decoupling lets J-Core support the full SH-4-plus-PageMask page-size set down to **4 KB** without sacrificing ASID width.

**J32 layout (32 bits):**
```
[31:N]   VPN           Hardware-set on TLB miss, software-set for LDTLB.
                       N depends on the page size selected by PTEL.PageMask
                       at LDTLB time:
                          4 KB    →  N = 12  (VPN = bits [31:12], 20 bits)
                          16 KB   →  N = 14  (VPN = bits [31:14], 18 bits)
                          64 KB   →  N = 16  (VPN = bits [31:16], 16 bits)
                          256 KB  →  N = 18
                          1 MB    →  N = 20
                          4 MB    →  N = 22
                          16 MB   →  N = 24
                          64 MB   →  N = 26
                          256 MB  →  N = 28
                          1 GB    →  N = 30
[N-1:0]  zero          Read-as-zero, write-ignored. Hardware does not store
                       these bits; software writes are dropped.
```

The PTEH layout no longer carries ASID bits. SH-4 binary compatibility is preserved for any code that *reads* PTEH (the VPN portion is at the same position) but software that *wrote* the SH-4 ASID bits must be updated to use ASIDR instead. The standard Linux SH-4 port writes PTEH at context-switch time to set the ASID; that write becomes a write to ASIDR (one LDC, same cost).

### 2.1a ASIDR — Address Space Identifier Register

New in this revision. Holds the 16-bit `ASID_TAG` that hardware compares on every TLB lookup. Accessed via `LDC Rm, ASIDR` / `STC ASIDR, Rn` (new LDC/STC encoding — see §3) or as MMIO at P4 address `0xFF000024`.

**J32 layout (32 bits):**
```
[31:16]  reserved (read-as-zero, write-ignored)
[15:0]   ASID_TAG      The kernel-encoded 16-bit ASID_TAG. Hardware
                       compares this against the entry.ASID_TAG of every
                       TLB entry on every translation (when entry.GLOBAL=0).
```

**ASID_TAG width is 16 bits** (canonical, project-wide). The kernel packs the 12-bit ASID proper and a 4-bit generation discriminator:

```
ASID_TAG[15:0] = (ASID[11:0] | (gen_low[3:0] << 12))
```

Hardware does not interpret the split; only the kernel does. The Linux ASID allocator in [linux-spec.md §5](linux-spec.md) produces this 16-bit value directly.

**Context-switch sequence (Linux):**
```asm
        mov.l   new_asid_tag, r0    ! r0 = packed ASID_TAG (16 bits)
        ldc     r0, asidr           ! one instruction, same cost as
                                    ! SH-4's LDC Rn,PTEH for ASID update
```

**LDTLB / LDTLB.R semantics:** the installed TLB entry's tag is built as
`{ASIDR[15:0], PTEH.VPN[31:N], PTEL.PageMask[3:0]}`. LDTLB atomicity is
unchanged — both PTEH and ASIDR are read at the start of LDTLB; software
must arrange them before issuing the instruction.

**Prior art (pre-2006):**
- **UltraSPARC `PRIMARY_CONTEXT` / `SECONDARY_CONTEXT`** (sun4u ASI 0x21, 1995): a per-CPU context register independent of TLB-tag programming; hardware reads it on every translation. The model this design follows.
- **MIPS R4000 `EntryHi.ASID`** (1991): ASID is a field of EntryHi separately re-assignable from VPN-write semantics.
- **Alpha 21264 `ASN`** (1998): per-CPU address-space-number register, accessed via PALcode, independent of page-table-walk registers.
- **ARMv6 `CONTEXTIDR`** (cp15 c13, 2002): explicit separate context-ID register; the model commercial CPUs converged on.

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

### 2.10 PTEU — Page Table Entry Upper (NEW, optional — PAE only)

Present only when the core is built for **wide physical addressing** (PAE; [design-spec.md §3.8](design-spec.md)). Carries the high physical-address bits that do not fit in the 32-bit `PTEL`, so that `LDTLB` can install a > 32-bit physical frame. Omitted entirely when `ADDR_WIDTH = 32`.

**Access:** new LDC/STC encoding (see §3.3) and MMIO at `0xFF000034` (proposed; coordinate with [soc/p4-mmio-map.md](../soc/p4-mmio-map.md), as for the §4.6 cause registers).

**J32-PAE layout (32 bits):**
```
[31:8]   reserved (read-as-zero, write-ignored)
[7:0]    PPNH          Physical address bits PA[39:32]. Combined with
                       PTEL.PPN (PA[31:14]) and the page offset, forms the
                       full 40-bit physical address. Software-set; latched
                       into the TLB entry by LDTLB / LDTLB.R alongside PTEL.
```

**LDTLB semantics.** The installed entry's physical frame is `{PTEU.PPNH, PTEL.PPN}`. `PTEU` is read at the same point as `PTEL` and `PTEH` at `LDTLB` time; software must arrange all three before issuing the instruction. On a non-PAE (`ADDR_WIDTH=32`) core, the high bits are implicitly zero and `PTEU` does not exist.

**Untranslated segments are unaffected.** P1/P2 produce `PA = VA & 0x1FFFFFFF` — at most 29 bits — so the kernel direct map and the boot/XIP path always land in low physical. Wide physical (`PA[39:29] ≠ 0`) is reachable **only** through the translated P0/P3 path, i.e. only via `LDTLB`-installed entries that carry `PTEU`. This is what makes everything above 512 MB "highmem" ([design-spec.md §3.8](design-spec.md)).

**Prior art (pre-2006).** A dedicated register holding the *high* physical-address bits of a wide-physical translation is the **PowerPC Book E `MAS7`** register (Freescale e500v2, ~2004), which extends the e500's real address from 32 to 36 bits exactly as `PTEU` extends J32's from 32 to 40. The broader 64-bit-PTE wide-physical paging technique is Intel x86 **PAE** (Pentium Pro, 1995); a 32-bit-virtual → 36-bit-physical software-managed MMU is the **SPARC V8 SRMMU** (sun4m, 1992); and the narrow-virtual / wide-physical concept itself dates to the **DEC PDP-11/70** (1975). See [design-spec.md §3.8](design-spec.md) for the full lineage.

## 3. Instruction Encodings

The SH ISA reserves the LDC/STC family for control register transfers via the pattern:

```
LDC Rm, REG :  0100 mmmm xxxx 1110
STC REG, Rn :  0000 nnnn xxxx 0010
```

where `xxxx` selects the register. SH-4 uses values 0000–0100 (SR, GBR, VBR, SSR, SPC) and 1nnn (R0_BANK–R7_BANK). Values 0101, 0110, 0111 are free.

### 3.0 Baseline SH-4 instructions the MMU requires (absent from J2)

The new encodings in §3.1–§3.2 extend a family that **J2 does not currently implement**. Before any MMU register or TLB-fill instruction is meaningful, the core must first add the pre-existing SH-4 instructions on which the exception model and the miss-handler hot path are built. These are not new inventions — they are stock SH-4 (SH-4A) opcodes, catalogued with their encodings in [docs/sh4-nonfpu.json](../sh4-nonfpu.json) (Tier-1, "mmu-required"). Adding them is cheap precisely because §3.1's new registers reuse the same `0100 mmmm xxxx 1110` / `0000 nnnn xxxx 0010` decode family, so the decoder paths exist anyway.

| Mnemonic | Encoding | Why the MMU needs it |
| -------- | -------- | -------------------- |
| `LDTLB` | `0000000000111000` (0x0038) | The TLB-fill primitive. Latches `{ASIDR, PTEH.VPN, PTEL}` into a TLB entry. §3.2's `LDTLB.R` is the fused-with-RTE variant; both are required. |
| `LDC Rm,SSR` / `STC SSR,Rn` (+`.l`) | `0100mmmm00111110` / `0000nnnn00110010` | Saved-SR. Exception entry does `SR→SSR` (§5 step 4); the slow path and any nested fault must save/restore it. `LDTLB.R`/`RTE` restore it on the way out. |
| `LDC Rm,SPC` / `STC SPC,Rn` (+`.l`) | `0100mmmm01001110` / `0000nnnn01000010` | Saved-PC. Exception entry does `PC→SPC`; the multi-word-fetch restart contract (§5.1) is defined in terms of what gets latched here. |
| `LDC Rm,Rn_BANK` / `STC Rm_BANK,Rn` (+`.l`) | `0100mmmm1nnn1110` / `0000nnnn1mmm0010` | Alternate-bank register access. The zero-save/restore scratch the hot path relies on (design-spec §4.4, §6 here) is the banked R0–R7; explicit `BANK` moves ferry values across banks and save both banks at `switch_mm`. |

**Privilege.** All four groups are privileged (illegal-instruction trap if `SR.MD=0`), consistent with their SH-4 definitions.

**Not required by the MMU.** Three further SH-4-only instructions surface in the same J2 gap but are *orthogonal* to translation and may be deferred or dropped: `LDC/STC DBR` (debug base register — UBC, not MMU), `STC SGR` (saved R15 — redundant here, since scratch comes from register banking, not an SGR shadow), and `CLRS`/`SETS` (the MAC saturation `S` bit). The operand-cache-maintenance instructions (`ocbi`/`ocbp`/`ocbwb`/`pref`/`movca.l`) are also in this gap but belong to the cache milestone, not the MMU core — see [cache/l2-spec.md §17.5](../cache/l2-spec.md). `pref` is additionally useful in the miss hot path (§7) to prefetch the `TSBPTR` slot.

### 3.1 New LDC/STC encodings

| Mnemonic | Encoding | Hex Pattern |
|----------|----------|-------------|
| `LDC Rm, TSBBR` | `0100 mmmm 0101 1110` | `0x405E \| m<<8` |
| `STC TSBBR, Rn` | `0000 nnnn 0101 0010` | `0x0052 \| n<<8` |
| `LDC Rm, TSBCFG` | `0100 mmmm 0110 1110` | `0x406E \| m<<8` |
| `STC TSBCFG, Rn` | `0000 nnnn 0110 0010` | `0x0062 \| n<<8` |
| `STC TSBPTR, Rn` | `0000 nnnn 0111 0010` | `0x0072 \| n<<8` |
| `LDC Rm, ASIDR` | `0100 mmmm 0101 1010` | `0x405A \| m<<8` |
| `STC ASIDR, Rn` | `0000 nnnn 0101 0011` | `0x0053 \| n<<8` |

`LDC Rm, TSBPTR` (encoding `0x407E`) is **reserved** — TSBPTR is read-only from software. Decoding this should raise illegal-instruction exception.

**ASIDR encoding rationale.** The TSB-related registers occupy free slots in the SH-4 `xxxx 1110` / `xxxx 0010` LDC/STC family. That family had only three free `xxxx` values (`0101`, `0110`, `0111`); all are now used. ASIDR is placed in the SH-4 PT-register family (`xxxx 1010` / `xxxx 0011`), reusing the slot that SH-DSP allocated to `MOD` (xxxx=`0101`). J-Core does not implement the SH-DSP extension; the encoding is unambiguously free here. This co-locates ASIDR with the other page-table-related registers (PTEH at `0100 mmmm 0000 1010`, PTEL at `0100 mmmm 0001 1010`, etc.) in the same encoding family.

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

### 3.3 PTEU encoding (PAE only)

`PTEU` joins the SH-4 **page-table register family** (`0100 mmmm xxxx 1010` for LDC, `0000 nnnn xxxx 0011` for STC) alongside `PTEH` (`xxxx=0000`), `PTEL` (`xxxx=0001`), and `ASIDR` (`xxxx=0101`, §3.1):

| Mnemonic | Encoding | Hex Pattern |
|----------|----------|-------------|
| `LDC Rm, PTEU` | `0100 mmmm 0010 1010` | `0x402A \| m<<8` |
| `STC PTEU, Rn` | `0000 nnnn 0010 0011` | `0x0023 \| n<<8` |

`PTEU` is privileged and exists only on PAE (`ADDR_WIDTH=40`) builds; on a non-PAE core the encoding is unallocated and decodes to illegal-instruction. The `xxxx=0010` slot is **proposed** — confirm it is free against the generated decoder and against SH-4 `PTEA` usage (J-Core does not implement SH-4 `PTEA`, so its slot is reusable, exactly as ASIDR reused the SH-DSP `MOD` slot in §3.1).

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

**PAE reuses the J64 PPN budget.** A J32-PAE core ([design-spec.md §3.8](design-spec.md)) carries a 40-bit physical frame: `PPN = PA[39:14] = 26 bits` at the 16 KB base page. That fits inside the `up to 36 bits` already reserved here for J64, so a PAE entry costs **no extra TLB storage** over a non-PAE J32 entry beyond the high `PPN` bits the field already allows — the entry width sits between the ~91-bit J32 and ~131-bit J64 figures. The only entry-adjacent hardware cost is widening the physical-output port (and the L1 cache tags, §8) from 32 to 40 bits.

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
3. Latch the faulting VPN (extracted from VA based on the default page size, 16 KB) into PTEH[31:N] where N is determined by the default-page PageMask. The low bits `[N-1:0]` of PTEH are zeroed. **ASIDR is not touched** — the kernel has set ASIDR at context switch and it remains valid for the miss handler to read.
4. Save PC → SPC and SR → SSR. Save register-bank state if applicable.
5. Update SR: set MD=1, RB=1, BL=1, IMASK=0xF.
6. Jump to `VBR + 0x400` (instruction-fetch miss) or `VBR + 0x420` (data-load miss) or `VBR + 0x440` (data-store miss) — same vector layout as SH-4.

Exception priorities and ordering relative to other interrupts follow SH-4 conventions.

### 5.1 Instruction-fetch miss inside a multi-word instruction or SIMD block

This subsection applies when the implementation pairs this MMU with an extension that introduces a **multi-word instruction unit** — i.e. an architectural instruction whose fetch spans more than one 16-bit word. Two such extensions exist in the J-Core roadmap: the two-word density instructions `movi20`/`movi20s`/`lea`/disp12-`mov.l` ([../isa-density/spec.md](../isa-density/spec.md)) and the SIMD prefix block ([../simd/spec.md](../simd/spec.md)). It imposes one additional requirement on the instruction-fetch miss path (the `VBR + 0x400` vector of §5 step 6); cores with neither extension are unaffected.

**The unifying rule.** When an instruction-fetch TLB miss (or any synchronous instruction-fetch fault) is taken while the CPU is partway through fetching a multi-word unit, the CPU **must save the PC of the unit's *first* word into SPC**, never the address of an interior word. The miss handler is then MMU-generic exactly as today; `LDTLB.R` + `RTE` returns to the unit's start and the whole unit re-executes (re-fetching all its words) against the now-mapped page. This is correct and idempotent because a multi-word unit commits no architectural state until it retires, so re-execution from the start reproduces it exactly. Returning to an interior word would instead resume *inside* an instruction — interpreting immediate data or a governed SIMD instruction as a fresh opcode — which is silent corruption, not a fault. (Prior art: Intel 386, 1985, validating page-split instructions against the instruction's start address.)

**SIMD block.** A SIMD block is a run of consecutive halfwords — a prefix plus up to four governed instructions (≤ 10 bytes), or a `VLNS`+`VEXT`/`VINS` pair (4 bytes). The prefix establishes a *decode-stage shadow latch* (`SIMD_VAL`, lane width, block length) that is **not** architectural state and is cleared on every exception entry ([../simd/spec.md §6.5](../simd/spec.md)). The first-word PC the rule requires is the **prefix PC**; returning to a governed instruction with the shadow latch cleared would decode it as a plain scalar SH op.

**Two-word density instructions.** `movi20`/`movi20s`/`lea`/disp12-`mov.l` fetch word1 after word0. The first-word PC the rule requires is **word0's PC**; word1 is immediate / displacement data, not a valid opcode, so returning to it is garbage. The in-order requirement (keep the architectural PC at word0 while the fetch pointer advances to word1) is detailed in [../isa-density/hardware-impl.md §4.2](../isa-density/hardware-impl.md). Note `movmu`/`movml` are *single-word* instructions and so do not engage this rule, but they are multi-*data*-access and have their own restart contract ([../isa-density/spec.md §5](../isa-density/spec.md)).

**SIMD blocks (in-order J32 + TLB): prefix-time block-fetch validation.** A SIMD block's governed instructions are decoded in the cycles *after* the prefix, so by the time a governed fetch faults the prefix has retired and its decode shadow latch is gone — late detection cannot easily recover the prefix PC. The clean fix is to validate the whole block up front. The block length is known at prefix decode, so the last halfword address `end = prefix_PC + 2·N` is known immediately. If `end` falls in a different page than the prefix (a single page-number comparison; false for the overwhelming majority of blocks at a 16 KB page), the front end issues a fetch-translation probe of `end`'s page during the prefix's otherwise-idle MA slot, before any governed instruction issues. A miss on that probe enters the `VBR + 0x400` vector normally with SPC = prefix PC — the existing miss sequence of §5 needs no change, because the prefix *is* the faulting instruction at that point. After the probe resolves, all governed fetches in the block are guaranteed to translate. The `VLNS`+`VEXT`/`VINS` pair is validated by probing `prefix_PC + 2`. Out-of-order implementations (J32-OOO) get the same prefix-PC reporting for free from their ROB atomic-commit group and need no explicit probe.

**Two-word density instructions (in-order J32 + TLB): simpler still — no pre-validation.** `movi20`/`lea`/disp12 are a *single* instruction parked in decode while word1 is fetched, so the instruction is still the in-flight decode when the word1 fetch faults. No probe is needed; the implementation merely keeps the architectural/exception PC pinned at word0 (the fetch pointer advances to word1 independently) so the standard fetch-fault path captures `SPC = word0_PC`. Detail in [../isa-density/hardware-impl.md §4.2](../isa-density/hardware-impl.md).

**Cost.** For the SIMD case the probe reuses the existing instruction-fetch translation path; the only new logic is the page-number comparator on `prefix_PC` vs. `end` and the conditional one-cycle stall (which fits the existing multi-cycle decode sequencer). No new TLB port is required if the probe is allowed to share the fetch port across one extra cycle. The two-word density case adds nothing beyond not advancing the architectural PC early. Untranslated kernel code (P1/P2) and MMU-disabled operation are unaffected in both cases.

## 6. Register Banking on Exception Entry

Inherited from SH-3/SH-4 unchanged. On any exception (including TLB miss):

- If SR.MD was 0 (user mode) and SR.RB was 0, transition to MD=1, RB=1. Bank 1 R0–R7 are now visible; bank 0 R0–R7 are preserved.
- If already in MD=1 with RB=1, no bank change.
- R8–R15 are not banked; software must save/restore them if used.

The TLB-miss handler's hot path (described in §7) uses only R0–R3 of bank 1, requiring no register saves. The hot path is ~10 instructions (two CMP/EQ pairs for VPN and ASID_TAG plus the LDTLB.R) — slightly longer than the SH-4-style single-comparison handler because of the ASID split, but still well under the ~30–50 of a pure software walker.

## 7. Recommended TLB Miss Handler

For reference. Implementation in software, but documenting the expected sequence:

**TSB tag format.** The 64-bit tag word is laid out as two 32-bit halves to avoid VPN/ASID-bit overlap (which would otherwise occur for small pages where VPN extends down into bit positions also covered by ASID_TAG):

```
TSB tag word (8 bytes, two 32-bit halves):
  tag_hi (offset 0, 4 bytes)  = expected VPN  (matches PTEH after miss)
  tag_lo (offset 4, 4 bytes)  = expected ASID_TAG  (matches ASIDR)
```

The kernel writes both halves at TSB-fill time. The miss handler compares both halves against PTEH (VPN) and ASIDR (ASID_TAG) — two `CMP/EQ` operations.

```asm
        ! At VBR+0x400, SR.RB=1, bank 1 selected.
tlb_miss:
        stc     tsbptr, r0      ! Read pre-computed TSB slot address
        mov.l   @r0+, r1        ! Load expected VPN (tag_hi); r0 += 4
        stc     pteh, r2        ! Load faulting VPN
        cmp/eq  r1, r2          ! VPN match?
        bf      tsb_miss_slow   ! No: slow path
        mov.l   @r0+, r1        ! Load expected ASID_TAG (tag_lo); r0 += 4
        stc     asidr, r2       ! Load current ASID_TAG
        cmp/eq  r1, r2          ! ASID match?
        bf      tsb_miss_slow   ! No: slow path
        mov.l   @r0, r3         ! Load TTE data
        ldc     r3, ptel        ! Stage data into PTEL
        ldtlb.r                 ! Install entry, return from exception
         nop                    ! Delay slot of LDTLB.R
```

Hot path: ~10 instructions (VPN compare + ASID compare + LDTLB.R). With the slow path inlined, the full handler fits in ~30 instructions.

**PAE variant.** On a wide-physical build ([design-spec.md §3.8](design-spec.md)), the TTE `Data` is the full 64-bit TSB `Data` word (the non-PAE handler above uses only its low 32 bits). The handler stages both halves before `LDTLB.R`:

```asm
        mov.l   @r0+, r3        ! TTE data low  (PTEL image: PPN[31:14]+flags)
        ldc     r3, ptel
        mov.l   @r0, r3         ! TTE data high (PTEU image: PA[39:32] in [7:0])
        ldc     r3, pteu
        ldtlb.r                 ! {PTEU,PTEL,PTEH,ASIDR} -> TLB entry, return
         nop
```

Two extra instructions (≈ +2 on the hot path). No extra TSB traffic: the 16-byte TSB entry's `Data` field is already 64 bits ([design-spec.md §4.3](design-spec.md)), so the high word is in the same cache line that was already loaded.

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
6. **ASIDR preservation across miss:** ASIDR is not touched by miss-vector entry; hardware writes only PTEH.VPN. Handler can read ASIDR directly and trust it reflects the current context.
7. **STALE bit preservation:** LDTLB carries the STALE bit from PTEL into the TLB entry intact.
8. **Per-CPU CPUINFO routing:** Each CPU reads a distinct HART_ID at `0xFF000020`.
9. **Exception priority:** TLB miss vs. instruction-fetch fault vs. higher-priority interrupts handled correctly.
10. **Reset state:** All MMU registers cleared, TLB invalidated, MMU disabled.
11. **Multi-word-unit instruction-fetch miss (only if the SIMD or density extension is present, §5.1):** an instruction-fetch miss on the *interior* word of a multi-word unit must save the unit's **first-word PC** into SPC, and `RTE` must re-execute the whole unit. Verify both instances: (a) a SIMD block straddling a 16 KB boundary whose tail page misses → SPC = prefix PC, block re-opens with correct lane-wise semantics (test the prefix-time-validation probe path *and* a non-crossing block that takes no probe/stall); (b) a two-word `movi20`/`lea`/disp12 whose word1 lands on a missing page → SPC = word0 PC, instruction re-executes (not a resume into word1).

## 12. Estimated Hardware Cost

Beyond inheriting the SH-4 MMU structure:

| Addition | Estimated cost |
|----------|----------------|
| TSBBR, TSBCFG registers | ~96 bits flop (J32), 160 bits (J64) |
| TSBPTR register | ~32 bits (J32), 64 bits (J64) |
| TSBPTR computation (hash, XOR, mask, OR) | ~50 LUTs |
| ASIDR register | 16 bits flop per CPU |
| Extended ASID_TAG (8 → 16 bits) | 8 bits per TLB entry |
| PageMask (4 bits per TLB entry) | 4 bits per TLB entry |
| STALE bit per TLB entry | 1 bit per entry |
| LDTLB.R decode | ~10 LUTs |
| ASIDR LDC/STC decode | ~5 LUTs |
| CPUINFO MMIO | ~32 bits flop per core + decoder |

For 32 TLB entries: ~600 bits of additional TLB state per CPU. Plus ~200 LUTs of new logic per CPU. Modest by FPGA standards.
