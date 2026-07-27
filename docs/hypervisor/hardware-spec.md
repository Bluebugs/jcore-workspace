# J-Core Hypervisor Extension Hardware Implementation Specification (Phase 3)

**Status:** Draft  
**Scope:** RTL implementation guide for J-Core hyperprivileged mode  
**Audience:** Hardware engineers implementing the hypervisor extension  
**Prerequisites:** Phase 1 hardware spec (`02-hardware-spec.md`), Phase 3 design spec (`07-hypervisor-design-spec.md`)

---

## 1. Scope

This document specifies the hardware-visible changes needed to support hyperprivileged mode and guest virtualization. The implementation closely tracks sun4v's HPSTATE-based model (UltraSPARC Architecture 2005, hyperprivileged edition).

What's specified:
- The SR.HPRIV mode bit and associated state
- New control registers (HSPC, HSSR, VBR_HYP, HEDR)
- The HCALL instruction
- LDTLB/LDTLB.RN behavior in guest mode
- Trap delivery logic with delegation
- Reset state

What's not changed from Phase 1:
- The TLB itself (no new fields, no new lookup logic)
- The TSB structure (no new fields)
- The instruction set beyond HCALL
- MMUCR, PTEH, PTEL, TSBBR, TSBCFG, TSBPTR

The IOMMU is also unchanged from Phase 2; hypervisor support is purely a software policy.

## 2. New CPU State

### 2.1 SR.HPRIV bit

Add one bit to SR at position `[14]` (a genuinely-reserved SH-4 bit; no collision with existing SH-4 SR fields). The full canonical SR layout after Phase 3, matching the SH-4 hardware manual for every bit J-Core inherits:

```
SR bit layout (J-Core, after Phase 3):
[31]     reserved (read-as-zero, write-ignored)
[30]     MD              mode (existing SH-4: 1 = supervisor, 0 = user)
[29]     RB              register bank (existing SH-4)
[28]     BL              block exceptions (existing SH-4)
[27:16]  reserved (read-as-zero, write-ignored)
[15]     FD              FPU disable (existing SH-4; Tier 1 FPU
                         and above; see ../fpu/spec.md §6.3)
[14]     HPRIV           hyperprivileged mode (NEW, J-Core hypervisor
                         extension; placed in a reserved SH-4 bit
                         to preserve binary compatibility)
[13]     VD              SIMD disable (NEW, J-Core SIMD extension;
                         placed in a reserved SH-4 bit; analogue
                         of FD for the SIMD facility; see
                         ../simd/spec.md §2.5)
[12:10]  reserved (read-as-zero, write-ignored)
[9]      M               existing SH-4 (DIV0 / DIV1 mantissa carry)
[8]      Q               existing SH-4 (DIV0 / DIV1 quotient)
[7:4]    IMASK[3:0]      interrupt mask (existing SH-4)
[3:2]    reserved (read-as-zero, write-ignored)
[1]      S               existing SH-4 (MAC saturation enable)
[0]      T               existing SH-4 (condition flag)
```

**Reconciliation note.** Earlier drafts of this spec placed MD at bit 15 (collides with SH-4 FD) and HPRIV at bit 9 (collides with SH-4 M). Both were errors. Bit positions for MD, RB, BL, FD, M, Q, IMASK, S, T match the SH-4 hardware manual verbatim; HPRIV occupies SH-4-reserved bit 14 and VD occupies SH-4-reserved bit 13. The FPU spec ([../fpu/spec.md §6.3](../fpu/spec.md)) places SR.FD at bit 15 per SH-4 and is consistent with this layout; the SIMD spec ([../simd/spec.md §2.5](../simd/spec.md)) places SR.VD at bit 13. Pre-2006 prior art for an explicit SIMD-disable SR bit: PowerPC G4 AltiVec `MSR.VEC` (1999).

**Semantics:**
- `SR.HPRIV = 1`: CPU is in hyperprivileged mode. All operations permitted including hypervisor-only control register access.
- `SR.HPRIV = 0`: CPU is in supervisor (`SR.MD=1`) or user (`SR.MD=0`) mode. Accesses to hypervisor-only registers trap.

**SR.HPRIV is privileged.** Writing to SR via `LDC Rm, SR` from a non-hyperprivileged context cannot set HPRIV; the bit is forced to its current value. Hardware ignores attempts to set HPRIV outside hyperprivileged mode.

**HPRIV is set by hardware on hyperprivileged trap entry** (see §4) and cleared by `HRTE` instruction (§3.3).

### 2.2 Hyperprivileged saved state

Three new control registers for the hyperprivileged trap path, parallel to SPC/SSR/VBR:

```
HSPC    Hyperprivileged Saved PC      word-sized
HSSR    Hyperprivileged Saved SR      word-sized
VBR_HYP Hyperprivileged Vector Base   word-sized
```

These are accessed via LDC/STC instructions. Phase 1 used the `0100 mmmm xxxx 1110` and `0000 nnnn xxxx 0010` encoding family for control register access (SR, GBR, VBR, SSR, SPC, then TSBBR/TSBCFG/TSBPTR in slots 5–7). Slots 1nnn in that family are already allocated to R0_BANK–R7_BANK.

For Phase 3 control registers we allocate a new family using the previously-unused low nibble `0xF` in the 0100 group:

```
LDC Rm, HSPC     : 0100 mmmm 0000 1111   = 0x400F | m<<8
STC HSPC, Rn     : 0000 nnnn 0000 1111   = 0x000F | n<<8
LDC Rm, HSSR     : 0100 mmmm 0001 1111   = 0x401F | m<<8
STC HSSR, Rn     : 0000 nnnn 0001 1111   = 0x001F | n<<8
LDC Rm, VBR_HYP  : 0100 mmmm 0010 1111   = 0x402F | m<<8
STC VBR_HYP, Rn  : 0000 nnnn 0010 1111   = 0x002F | n<<8
LDC Rm, HEDR     : 0100 mmmm 0011 1111   = 0x403F | m<<8
STC HEDR, Rn     : 0000 nnnn 0011 1111   = 0x003F | n<<8
LDC Rm, HEMUB    : 0100 mmmm 0100 1111   = 0x404F | m<<8
STC HEMUB, Rn    : 0000 nnnn 0100 1111   = 0x004F | n<<8
LDC Rm, HEMUM    : 0100 mmmm 0101 1111   = 0x405F | m<<8
STC HEMUM, Rn    : 0000 nnnn 0101 1111   = 0x005F | n<<8
LDC Rm, HMAR     : 0100 mmmm 0110 1111   = 0x406F | m<<8
STC HMAR, Rn     : 0000 nnnn 0110 1111   = 0x006F | n<<8
LDC Rm, HMDR     : 0100 mmmm 0111 1111   = 0x407F | m<<8
STC HMDR, Rn     : 0000 nnnn 0111 1111   = 0x007F | n<<8
LDC Rm, HMCR     : 0100 mmmm 1000 1111   = 0x408F | m<<8
STC HMCR, Rn     : 0000 nnnn 1000 1111   = 0x008F | n<<8
LDC Rm, HSQCR    : 0100 mmmm 1001 1111   = 0x409F | m<<8
STC HSQCR, Rn    : 0000 nnnn 1001 1111   = 0x009F | n<<8
```

This carves a new control-register family with capacity for up to 16 hyperprivileged control registers (slots 0–15). After allocation of HEMUB, HEMUM, HMAR, HMDR, HMCR, and HSQCR in slots 4–9, **six free slots (10–15) remain** for future hyperprivileged register extensions. All accesses in this family trap with illegal-instruction exception if executed with `SR.HPRIV=0`, enforcing that only hyperprivileged code can read or write these registers.

The choice of low nibble `0xF` avoids collision with SH-4's existing `0xE` (LDC/STC) and `0xB`/`0xA`/`0x7`/`0x3` (LDC.L/STC.L variants) low nibbles in the 0100 family.

### 2.3 HEDR — Hypervisor Exception Delegation Register

```
[31:0]  Bitmap: bit N = 1 -> delegate exception cause N to supervisor (guest).
                bit N = 0 -> deliver exception cause N to hyperprivileged (host).
```

HEDR has 32 bits, each corresponding to an exception cause. The cause-to-bit mapping is fixed by hardware and given in §2.3.1; software cannot remap.

**Default after reset:** all bits 0 (all exceptions go to hyperprivileged). The hypervisor explicitly sets bits to delegate to the guest. A non-virtualized kernel never sets HPRIV, so HEDR is never consulted — backward compatibility is preserved.

**Always-to-hypervisor causes** (§4.2): bits 0 (HCALL), 1 (guest LDTLB trap), 2 (hyperprivileged-register access from non-HS mode), and 25 (guest emulated-MMIO access, §4.5) are hard-wired to read-as-zero; software writes to these bits have no effect. These traps cannot be delegated to a guest because they exist solely to communicate with the hypervisor — bit 25 specifically exists only to reach the hypervisor's device model, and delegating it to a guest would be meaningless: there is no guest-side handler for a physical aperture the guest does not know exists.

#### 2.3.1 EXPEVT-to-HEDR-bit mapping (normative)

The mapping is dense from the low bits up so a typical hypervisor configuration looks like a small bitmask. SH-4-inherited EXPEVT values are grouped by class; J-Core hyperprivileged-extension causes (`0x180`+) follow.

| HEDR bit | EXPEVT     | Cause                                                    | Delegatable? |
|---------:|------------|----------------------------------------------------------|:------------:|
|    0     | `0x180`    | HCALL instruction                                        | **no**       |
|    1     | `0x190`    | Guest LDTLB / LDTLB.RN trap                              | **no**       |
|    2     | `0x1A0`    | Hyperprivileged-register access from non-HS mode         | **no**       |
|    3     | `0x1B0`    | `EXC_FPU_DISABLED` — SR.FD trap (Tier 2 FPU)             | yes          |
|    4     | `0x040`    | TLB miss (read)                                          | yes          |
|    5     | `0x060`    | TLB miss (write)                                         | yes          |
|    6     | `0x0A0`    | TLB protection violation (read)                          | yes          |
|    7     | `0x0C0`    | TLB protection violation (write)                         | yes          |
|    8     | `0x0E0`    | Address error (read)                                     | yes          |
|    9     | `0x100`    | Address error (write)                                    | yes          |
|   10     | `0x800`    | FPU exception (non-disable; arithmetic IEEE-754 trap)    | yes          |
|   11     | `0x820`    | FPU slot exception (in branch-delay slot)                | yes          |
|   12     | `0x180` (Sup. case) | General illegal instruction (non-hyp cause)      | yes          |
|   13     | `0x1A0` (Sup. case) | Slot illegal instruction                         | yes          |
|   14     | `0x160`    | Unconditional TRAPA                                      | yes          |
|   15     | `0x600`    | External IRL interrupt                                   | yes          |
|   16     | `0x620`    | NMI                                                      | yes          |
|   17     | `0x640`    | User break                                               | yes          |
|   18     | `0x500`    | Reserved-instruction (no Tier 2 FPU present)             | yes          |
|   19     | `0x5C0`    | Initial-page-write (dirty trap)                          | yes          |
|   20     | `0x6E0`    | Inter-processor interrupt (host-targeted)                | yes          |
|   21     | `0x700`    | PMU counter-overflow interrupt                           | yes          |
|   22     | `0x720`    | L2 ECC / parity error (where instrumented)               | yes          |
|   23     | `0x740`    | IOMMU fault forwarded as exception                       | yes          |
|   24     | `0x1C0`    | `EXC_SIMD_DISABLED` — SR.VD trap (Tier 2 SIMD, new)      | yes          |
|   25     | `0x1E0`    | Guest emulated-MMIO access (aperture, P4)                | **no**       |
|   26–31  | —          | reserved (future causes)                                 | yes          |

Notes:
- "Delegatable?" = whether the bit accepts software writes. Hardware ignores writes to non-delegatable bits, which always read 0.
- Two EXPEVT values appear twice in the table (`0x180` and `0x1A0`) because they overload between the hyperprivileged extension cause (HCALL / hyp-register-from-non-HS) and the pre-existing SH-4 supervisor cause (illegal-instruction). Hardware distinguishes by context: when raised by HCALL or by a hyperprivileged-register access, the cause is non-delegatable (bits 0 and 2); when raised by an ordinary illegal-instruction, the cause is delegatable (bits 12 and 13).
- The mapping is **stable**: future hardware revisions may add causes in bits 24–31 but MUST NOT reassign bits 0–23.

This table resolves the open question raised in [../fpu/spec.md §10 #3](../fpu/spec.md): `EXC_FPU_DISABLED` occupies HEDR bit 3 and is delegatable. The parallel SIMD trap `EXC_SIMD_DISABLED` ([../simd/spec.md §2.5](../simd/spec.md)) occupies HEDR bit 24 — placed in the formerly-reserved range so that the dense low-numbered bits remain stable as J-Core's exception model evolves.

### 2.4 No changes to existing register layouts

PTEH, PTEL, TSBBR, TSBCFG, TSBPTR, MMUCR, VBR, SPC, SSR, GBR, R0-R15 all keep exactly the same bit layout as in Phase 1. The TLB and TSB structures are unchanged.

**Amendment:** layout is unchanged, but `MMUCR.AT` acquires new *meaning* under `SR.HPRIV = 0`. On bare metal (no hypervisor present, or `SR.HPRIV = 1`), `MMUCR.AT` still gates P0/P3 translation exactly as specified in [../mmu/hardware-spec.md §2.3](../mmu/hardware-spec.md). For a guest (`SR.HPRIV = 0` with virtualization active), hardware forces translation on for P0-P3 regardless of the `MMUCR.AT` bit value; guest writes to `MMUCR` are trapped and shadowed rather than applied directly. See §4.4.1 for the full rule.

### 2.5 HEMUB and HEMUM — Emulation Aperture

```
HEMUB   Hypervisor Emulation Aperture Base   word-sized
HEMUM   Hypervisor Emulation Aperture Mask   word-sized

Trap condition (guest only, SR.HPRIV = 0):
    (PA & HEMUM) == HEMUB
```

**Normative rules:**

1. **Physical-address matching:** The aperture test is applied to the **physical** address produced by the TLB, not the virtual address. This allows the hypervisor to trap accesses to any physical region, even if mapped by the guest at different virtual addresses.

2. **Guest-mode only:** The aperture test applies only when `SR.HPRIV = 0`. Accesses by the hypervisor to the same physical addresses do not trigger the aperture trap and do not recurse; the hypervisor is exempt from emulation.

3. **Aperture disabled by HEMUM=0:** When `HEMUM = 0`, the aperture is disabled. No address matches the test (since any value AND'ed with 0 equals 0, which cannot equal `HEMUB` unless both are 0; define `HEMUM = 0` explicitly as "aperture disabled" rather than relying on bit arithmetic to fall out correctly).

4. **Per-vCPU context:** HEMUB and HEMUM are per-vCPU state, saved and restored across VM exit and entry by the hypervisor's vCPU context-save/restore sequence.

5. **Reset value:** Both HEMUB and HEMUM read as 0 at reset (aperture disabled).

**Design rationale:** The emulation aperture traps guest accesses to reserved regions, such as Dreamcast console I/O devices (the AIC, AICA, GD-ROM, etc.), which exist at fixed physical addresses. The trap diverts these accesses to the hypervisor, which can then emulate the behavior or inject the appropriate device state into the guest. Pre-2006 prior art: IBM S/370 storage keys (1970) pioneered physical-address-indexed access tests for memory protection; the aperture applies the same model to I/O emulation on a virtualized architecture.

### 2.6 HMAR, HMDR, and HMCR — MMIO Trap Information Registers

```
HMAR    Hypervisor MMIO Address Register     word-sized, hardware-written
HMDR    Hypervisor MMIO Data Register        word-sized, read/write
HMCR    Hypervisor MMIO Control Register     32-bit, hardware-written
```

**HMAR — Hypervisor MMIO Address Register:** On an emulation aperture trap, the faulting **virtual** address is captured in HMAR. The hypervisor recovers the physical address from its own guest-to-host PA translation tables (as in sun4v), and keeping the virtual address lets it identify which guest mapping was used for the access. This is essential for correct trap context when the guest page tables or TLB state change between the trap and the hypervisor's inspection.

**Why HMAR is a new register, not an alias of TEA:** The TLB exception address register (TEA) is written by TLB exceptions delivered to the *guest* (miss, protection violation, etc.). Overloading HMAR onto TEA would destroy the guest's TEA state whenever an emulation aperture trap occurs, even though the guest never sees the trap. This would break the guest's TLB miss handler invariants. HMAR as a separate register preserves guest state and closes a previously-open design question (design spec, item 3).

**HMDR — Hypervisor MMIO Data Register:** Holds the data payload associated with an emulation aperture trap. For a load (`HMCR.DIR = 0`), the hypervisor writes the guest's expected result into HMDR before `HRTE`. For a store (`HMCR.DIR = 1`), HMDR holds the guest's store value on entry. For a burst store (`HMCR.SQ = 1`), the data is **not** in HMDR — it resides in the store queue buffers and is readable per [../sq/spec.md §6](../sq/spec.md), which gives the buffer layout and access protocol.

**HMCR — Hypervisor MMIO Control Register (32-bit, read-only to software except as noted):**

```
[31:9]  reserved, RAZ
[8]     SQ      1 = 32-byte store-queue burst; SIZE and REGN are ignored
[7]     DIR     0 = load (hypervisor supplies HMDR), 1 = store (HMDR holds guest data)
[6:5]   SIZE    0 = byte, 1 = word (16-bit), 2 = longword (32-bit), 3 = reserved
[4]     BANK    destination register bank for a load (0 = bank 0, 1 = bank 1)
[3:0]   REGN    destination register number for a load (R0-R15)
```

BANK is meaningful only for REGN 0–7; R8–R15 are unbanked and BANK reads 0 for them. Hardware sets all fields on trap; software cannot write HMCR. The hypervisor uses HMCR fields to determine where to inject the emulated result (REGN, BANK for registers; SIZE for the number of bytes to write), and whether HMDR holds the value or the data is in the store queue (SQ flag).

### 2.7 HSQCR — Hypervisor Store-Queue Status Register

```
HSQCR   Hypervisor Store-Queue Status Register    32-bit
```

**Layout (32-bit):**

```
[31:4]  reserved, RAZ/WI
[3]     DIRTY1  queue 1 holds data not yet burst
[2]     DIRTY0  queue 0 holds data not yet burst
[1]     VALID1  queue 1 has been written since last burst or clear
[0]     VALID0  queue 0 has been written since last burst or clear
```

**VALID[1:0] and DIRTY[1:0]:** The SQ hardware sets VALID bits to 1 when the corresponding queue slot is written by the guest, and clears them on a burst (when the queue is flushed to memory). DIRTY bits shadow valid bits until cleared. The hypervisor uses these bits to determine which queue slots hold pending store data. Write access to HSQCR is allowed only at `SR.HPRIV = 1` for context restore (clearing bits after reading them, or setting them to match saved state). Writes at `SR.HPRIV = 0` trap with an illegal-instruction exception.

**Per-vCPU context:** HSQCR is per-vCPU state, saved and restored across VM exit and entry as part of the vCPU context-save/restore sequence.

**Reset value:** 0 (both queues empty).

**Cross-reference:** The store queue architecture and the format of the queue buffers are specified in [../sq/spec.md §6](../sq/spec.md).

## 3. New Instructions

### 3.1 HCALL — Hypervisor Call

Encoding: `0000 0000 1001 1000` = `0x0098`

Allocated in the `0000 0000 nnnn 1000` family alongside LDTLB (`0x38`), CLRS (`0x48`), SETS (`0x58`), LDTLB.RN (`0x78`). The slot at `0x98` is now allocated to HCALL.

| Offset | Mnemonic | Encoding |
|--------|----------|----------|
| `0x0008` | CLRT | `0000 0000 0000 1000` |
| `0x0018` | SETT | `0000 0000 0001 1000` |
| `0x0028` | CLRMAC | `0000 0000 0010 1000` |
| `0x0038` | LDTLB | `0000 0000 0011 1000` |
| `0x0048` | CLRS | `0000 0000 0100 1000` |
| `0x0058` | SETS | `0000 0000 0101 1000` |
| `0x0068` | SH-2A `nott` | `0000 0000 0110 1000` |
| `0x0078` | LDTLB.RN | `0000 0000 0111 1000` |
| `0x0088` | HRTE | `0000 0000 1000 1000` |
| `0x0098` | HCALL | `0000 0000 1001 1000` |
| `0x00A8`–`0x00F8` | (free) | — |

**Reconciliation note.** An earlier draft assigned `HCALL` encoding `0x0078` and described that slot as unallocated, attributing `LDTLB.R` to `0x0068`. Both statements were incorrect. The ground truth from RTL is: `LDTLB.RN` occupies `0x0078` (the J-Core fused TLB-fill-and-return instruction implemented in `decode/gen-go/spec/sh4/mmu.toml:165` and used on the host TLB-miss hot path), while SH-2A `nott` occupies `0x0068` per `decode/gen-go/spec/sh2a/misc.toml:24`. The `0x0098` slot is the next free slot in the family, adjacent to `HRTE` at `0x0088`, and is the appropriate place for `HCALL`.

**Semantics:**

1. Save PC + 2 → HSPC (instruction after HCALL).
2. Save SR → HSSR.
3. Set SR.HPRIV = 1, SR.MD = 1, SR.BL = 1, SR.RB = 1.
4. Set EXPEVT = 0x180 (new value for HCALL trap).
5. Jump to VBR_HYP + 0x100.

**Privilege:** HCALL is not privileged — user mode can execute it. The hypervisor decides what to do with hypercalls from user mode (typically: reject, since hypercalls should come from the guest kernel).

**Hyperprivileged usage:** When executed with SR.HPRIV=1 already, HCALL behaves as a no-op (or, optionally, raises illegal-instruction trap — implementer's choice; document the choice).

**Convention:**
- R0 holds the hypercall code.
- R1-R7 hold arguments (extras pushed on stack).
- R0 on return holds the result/error code.
- R1-R3 may hold additional return values.

### 3.2 HRTE — Hyperprivileged Return from Exception

Encoding: `0000 0000 1000 1000` = `0x0088`

**Semantics:**
1. Restore SR ← HSSR.
2. Restore PC ← HSPC.
3. Branch to new PC.
4. **One-instruction delay slot** (like RTE).

Used by the hypervisor to return to supervisor or user mode. The HSSR's HPRIV bit is restored — typically 0, returning to a guest.

If HSSR has HPRIV=1, HRTE returns to nested hyperprivileged execution; useful for hypervisor internal trap chains.

### 3.3 LDTLB and LDTLB.RN in supervisor mode

**Behavior change:** When `SR.HPRIV = 0` and `SR.MD = 1` (supervisor mode), executing LDTLB or LDTLB.RN (formerly LDTLB.R) **traps to the hyperprivileged trap vector** at `VBR_HYP + 0x190`.

The trap saves:
- PC of the LDTLB/LDTLB.RN → HSPC
- SR → HSSR
- EXPEVT = 0x190 (new: guest TLB write trap)

**Reconciliation note.** Earlier drafts of this spec gave the guest LDTLB trap as `VBR_HYP + 0x300`, inconsistent with §4.2 (vector table), §4.3 (EXPEVT 0x190), and §9 (verification point 2). The correct vector is `VBR_HYP + 0x190`. Corroborating evidence: [linux-spec.md §3.3](linux-spec.md) already names the hypervisor entry symbol `jcore_hyp_entry_0x190`. The instruction name was also standardized: `LDTLB.R` was a working name; the implemented name is `LDTLB.RN`.

The hypervisor's handler reads PTEH (the guest's intended VPN), ASIDR (the guest's current ASID_TAG, set at guest context switch), and PTEL (the guest's intended RFN + flags), performs RA-to-HPA translation, executes its own LDTLB (which doesn't trap because HPRIV=1), and HRTE's back to the guest.

**For non-virtualized kernels:** SR.HPRIV is never set, and the trap delegation is irrelevant. LDTLB executes normally. Phase 1 binary compatibility is preserved.

### 3.4 Privileged register access from supervisor mode

When `SR.HPRIV = 0`, attempting to access hyperprivileged registers (HSPC, HSSR, VBR_HYP, HEDR) raises an illegal-instruction trap (EXPEVT = 0x1A0 — but routed via the HEDR rules; by default, this trap goes to the hypervisor).

This is the mechanism by which the hypervisor catches a guest that tries to manipulate its own hyperprivileged state.

**Reconciliation note.** An earlier draft gave the hyp-register-access trap as `EXPEVT = 0x180`, conflicting with §2.3.1 (bit 2: 0x1A0) and §4.3. The correct code is `0x1A0`. Note that `0x180` legitimately appears elsewhere: as the HCALL trap code (§2.3.1 bit 0, §4.3) and as the SH-4 supervisor general-illegal-instruction code (§2.3.1 bit 12). Hardware distinguishes these by context, as explained in §2.3.1.

## 4. Trap Delivery

### 4.1 Trap entry logic

```
on exception(cause):
    if SR.HPRIV == 1:
        # We're already in hyperprivileged mode; deliver locally
        HSPC <- PC
        HSSR <- SR
        SR.HPRIV <- 1   # no change
        SR.BL <- 1
        EXPEVT <- cause
        PC <- VBR_HYP + offset(cause)
    elif (HEDR[cause] == 1) and (some other conditions):
        # Delegated to supervisor (guest kernel)
        SPC <- PC
        SSR <- SR
        SR.MD <- 1
        SR.BL <- 1
        SR.RB <- 1
        EXPEVT <- cause
        PC <- VBR + offset(cause)
    else:
        # Take to hyperprivileged
        HSPC <- PC
        HSSR <- SR
        SR.HPRIV <- 1
        SR.MD <- 1
        SR.BL <- 1
        SR.RB <- 1
        EXPEVT <- cause
        PC <- VBR_HYP + offset(cause)
```

**Always-to-hypervisor exceptions:** Regardless of HEDR, certain causes always go to the hypervisor:
- HCALL (EXPEVT 0x180)
- Guest LDTLB trap (EXPEVT 0x190)
- Hyperprivileged register access from non-HS mode
- Guest emulated-MMIO access (EXPEVT 0x1E0, §4.5)

These are the exceptions where delegation makes no sense.

### 4.2 Vector layout

Hyperprivileged vector base at VBR_HYP, with the same offset conventions as VBR but specific to hyp-mode handlers:

```
Offset    Handler
------    --------------------------------------------------------
0x100     HCALL handler (HCALL from any mode)
0x190     Guest LDTLB trap handler
0x200     Guest emulated-MMIO trap (aperture access, §4.5)
0x300     Privileged-instruction trap (for sensitive instructions)
0x400     Hyperprivileged TLB miss (HS-mode address translation fault)
0x500     External interrupt (when virtualization is active)
0x600     Inter-processor interrupts targeting HS-mode
```

(Offsets are illustrative; actual values follow the SH-4 vector conventions or are chosen by the implementer.)

### 4.3 EXPEVT values

The hyperprivileged-mode extension adds five new EXPEVT codes on top of the existing SH-4 set. The full per-cause delegation routing — including which bit of HEDR controls each cause — is specified normatively in [§2.3.1](#231-expevt-to-hedr-bit-mapping-normative). Summary of the new codes:

| Code  | Cause                                                          | HEDR bit | Delegatable? |
|-------|----------------------------------------------------------------|---------:|:------------:|
| 0x180 | HCALL instruction (new)                                        | 0        | no           |
| 0x190 | Guest LDTLB/LDTLB.RN trap (new)                                | 1        | no           |
| 0x1A0 | Hyperprivileged register access from non-HS mode (new)         | 2        | no           |
| 0x1B0 | `EXC_FPU_DISABLED` — SR.FD trap (Tier 2 FPU, new)              | 3        | yes          |
| 0x1C0 | `EXC_SIMD_DISABLED` — SR.VD trap (Tier 2 SIMD, new)            | 24       | yes          |
| 0x1E0 | Guest emulated-MMIO access (aperture, new, §4.5)               | 25       | no           |

Existing SH-4 EXPEVT codes (`0x040`–`0x130`, `0x500`–`0x740`) retain their meanings; their HEDR-bit assignments are in §2.3.1.

**`EXC_FPU_DISABLED` (0x1B0).** Raised when an FPU instruction is decoded with `SR.FD = 1` on a CPU that ships a Tier 2 (hypervisor-aware) FPU. The cause is subject to HEDR delegation: when `HEDR[bit-for-0x1B0] = 0` (the default) the trap is taken by the hypervisor, which uses it to implement the lazy FPU context-switch ABI (per-vCPU FPU-ownership flag, save/restore of the 132-byte FPU image, re-enable of `SR.FD = 0` in the guest's `HSSR` shadow before `HRTE`). When the bit is set, the trap is delegated to the guest's own supervisor handler (a guest OS that wants to manage its own lazy-FPU model for user threads sets the bit). The full trap-handler ABI, save/restore sequence, and migration corner cases are specified in [../fpu/spec.md §7](../fpu/spec.md).

**`EXC_SIMD_DISABLED` (0x1C0).** The exact analogue of `EXC_FPU_DISABLED` for the SIMD facility. Raised when any SIMD-touching instruction or register access (governed SIMD instruction, SIMDV/SIMDH prefix, VLD.Q/VST.Q, VEXT/VINS, VMKCHG, LDS/STS to P0 / VCSR / VFPUL, or the §5.8 boundary instructions FMOV.VS / FMOV.VD) is decoded with `SR.VD = 1` on a CPU that ships a Tier 2 (hypervisor-aware) SIMD implementation. HEDR-delegation rules are identical: bit 24 = 0 → trap to hypervisor (which implements lazy SIMD context-switch ABI: per-vCPU SIMD-ownership flag, save/restore of the **272-byte SIMD image** — V0..V15 + P0 + VCSR + VFPUL — and re-enable of `SR.VD = 0` in `HSSR` before `HRTE`); bit 24 = 1 → trap delegated to guest's supervisor handler for guest-managed lazy SIMD across guest user threads. Full trap-handler ABI in [../simd/spec.md §2.6](../simd/spec.md). Note: the §5.8 boundary instructions also trap under SR.FD because they touch the scalar FPU register file; SR.VD wins when both are set.

**Guest emulated-MMIO access (0x1E0).** Raised when a guest (`SR.HPRIV = 0`) memory access translates to a physical address matching the emulation aperture defined by HEMUB/HEMUM (§2.5): `(PA & HEMUM) == HEMUB`. Not subject to HEDR delegation — bit 25 is hard-wired non-delegatable for the same reason as HCALL and the guest LDTLB trap (§2.3): the aperture exists to reach the hypervisor's device model, and a guest has no handler for a physical region it does not know is virtualized. Full delivery mechanics, register capture, and the complete-on-resume contract are specified in §4.5.

## 4.4 Guest-Mode Address Translation

A Dreamcast image is a bare-metal SH-4 binary: it runs with `MMUCR.AT = 0`, entirely inside
P1/P2, which are architecturally untranslated and bypass the TLB. Such a binary has no
translation path of its own. Two such guests loaded by the same hypervisor would both resolve
their P1/P2 references to the same physical addresses and collide in RAM. §4.4.1-§4.4.4 specify
the rule that fixes this: translation is forced on for guests, independent of the value the guest
believes `MMUCR.AT` holds, so that a flat MMU-off binary becomes relocatable.

### 4.4.1 Translation forced on

**Decision:** Whenever a guest is active (`SR.HPRIV = 0`, virtualization active for the running
context), all P0, P1, P2, and P3 accesses are translated through the TLB, regardless of the
guest's `MMUCR.AT` value. The guest may read and write what it believes is `MMUCR.AT` — the
hypervisor shadows this bit per-vCPU (guest writes to `MMUCR` trap to the hypervisor as an
ordinary P4 MMIO access, per §4.4.3, since `MMUCR` lives at `0xFF000010`) — but the shadow value
never reaches the hardware `AT` gate while a guest is running. Hardware translation remains
enabled unconditionally for the guest's P0-P3 accesses.

This does not contradict [../mmu/hardware-spec.md §2.3](../mmu/hardware-spec.md), which states
that `MMUCR.AT` gates P0/P3 only and that P1, P2, P4 are unaffected by it. That statement
describes the bare-metal (non-virtualized, or `SR.HPRIV = 1`) behavior of the `AT` bit itself, and
remains true unchanged: on bare metal, `AT` still gates only P0/P3, and P1/P2 are still
architecturally untranslated when `AT = 0`. The rule here is a guest-mode override sitting above
that bit, forcing translation on for P0-P3 for the guest — it does not change what `AT` gates, it
changes whether `AT`'s bare-metal meaning is consulted at all while a guest runs.

**Rationale:** Bare-metal SH-4 runs with `AT = 0` entirely in P1/P2, an untranslated-by-architecture
region that bypasses the TLB. Without this rule, a guest has no translation path at all, and two
VMs sharing one physical machine would both land on the same physical memory. Forcing translation
on reuses the existing TLB rather than adding a parallel relocation datapath, and inherits Phase 1's
multi-size page support: a flat 16 MB guest image costs a single large-page TLB entry, not per-page
bookkeeping. Prior art for guest-address relocation, both pre-dating hardware-assisted virtualization
patents: IBM System/360 base-and-bounds relocation registers (1964), and sun4v's real-address offset
mechanism (UltraSPARC Architecture 2005).

**Rejected alternative:** a dedicated base+bound register pair (`HGBR`/`HGLR`) that would add a
constant offset to every guest physical address instead of going through the TLB. This is cheaper
in gates than reusing the TLB, but it was rejected because it forces each VM's guest memory to be
physically contiguous (no ability to scatter a guest's frames, no demand-paging of guest memory
from the host), and it adds a second, redundant address-relocation mechanism alongside the TLB that
already does this job. Reusing the TLB is one relocation mechanism, not two.

### 4.4.2 Cacheability and the C-bit alias

**Decision:** A guest's P1/P2 accesses, now translated per §4.4.1, are mapped by hypervisor-installed
PTEs. Because P1 (`VA[31:29] = 100`, i.e. `KSEG0`) and P2 (`VA[31:29] = 101`, i.e. `KSEG1`) differ
only in `VA[29]` and otherwise alias the same low address range, the hypervisor can map the *same*
guest physical frame twice — once through a P1-range VPN with `PTEL.C = 1` (cached) and once through
a P2-range VPN with `PTEL.C = 0` (uncached) — reproducing the P1/P2 cached/uncached alias that
bare-metal SH-4 software already relies on.

**Consequence, stated explicitly:** this creates a cached/uncached alias of one physical frame
through two distinct TLB entries. The hardware does **not** maintain coherence between the two
views — a write through the cached (P1) mapping is not automatically visible through the uncached
(P2) mapping until the cache line is flushed, exactly as on real, non-virtualized SH-4 hardware.
Guest software is responsible for using the correct alias and flushing when it switches between
them, precisely as it already had to do running bare-metal on real Dreamcast hardware. This design
does not soften or paper over that requirement; it reproduces it faithfully so unmodified Dreamcast
binaries continue to work.

### 4.4.3 P4 in guest mode

**Decision:** A guest access to P4 (`0xE0000000`-`0xFFFFFFFF`) raises the emulated-MMIO trap (§4.5),
**except** for accesses in the range `0xE0000000`-`0xEFFFFFFF`, which is the store-queue region
per [../sq/spec.md §2](../sq/spec.md). Those do not trap; they are handled CPU-locally as ordinary
store-queue operations.

The carve-out applies to the *data* path only. A queue-data store to `0xE0000000`-`0xEFFFFFFF` is
absorbed into the store queue without a trap, exactly as on bare metal. But the burst that a
subsequent `PREF` triggers is still address-translated (per [../sq/spec.md §3](../sq/spec.md), the
burst target is formed from `QACRn.AREA` and `VA[25:5]`) and the resulting physical burst address
is still subject to the emulation-aperture test of §2.5. The carve-out means the store-queue *data
writes* skip the P4 trap; it does not mean the store-queue *burst target* skips translation or the
aperture test.

**Rationale:** P4 is an untranslated-by-architecture region holding core control and MMIO registers;
a guest has no legitimate direct access to host control state, so trapping the whole segment is
correct and needs no per-register range comparators — one range check (`VA[31:29] == 111`, minus
the SQ carve-out) covers all of P4. The store-queue carve-out exists because the SQ region is
architecturally inside P4 but is exercised on a hot path: eight sequential word stores followed by
one `PREF` per 32-byte burst. Trapping each of the eight stores would cost eight traps per burst —
exactly the cost this design exists to avoid. Leaving the burst's translated target subject to the
aperture test preserves the hypervisor's ability to emulate or intercept any physical destination
the guest's store-queue burst resolves to, including a device the hypervisor wants to virtualize.

### 4.4.4 Guest TLB refill

**Decision:** A guest's TLB refill uses plain `LDTLB` (`0x0038`), which — per §3.3 — traps to
`VBR_HYP + 0x190` whenever `SR.HPRIV = 0` and `SR.MD = 1`. The hypervisor's own refill of its
shadow/host TLB entries uses the fused `LDTLB.RN` (`0x0078`) at full speed, untouched by this rule.

**Rationale:** This is free for the host. The host's own TLB-miss hot path, specified in
[../mmu/linux-spec.md §4.1](../mmu/linux-spec.md), uses `LDTLB.RN` exclusively (`ldtlb.rn` at the
end of the fast-path compare-and-install sequence in `jcore_tlb_miss`) and never emits plain
`LDTLB`. Plain `LDTLB` is consequently dead code in a non-virtualized J-Core kernel today. Routing
the guest-refill trap through the encoding the host never uses costs the host's own hot path
nothing — no fast-path instruction changes meaning, no extra branch is added to
`jcore_tlb_miss`, and the trap-on-`LDTLB` behavior for supervisor mode was already specified in
§3.3 for exactly this purpose.

### 4.5 Emulated-MMIO trap delivery and complete-on-resume

**Trap entry.** When a guest (`SR.HPRIV = 0`) access's translated physical address matches the
emulation aperture (`(PA & HEMUM) == HEMUB`, §2.5), hardware delivers the trap unconditionally to
the hypervisor — this is the bit-25 always-to-hypervisor case already listed in §4.1 and §2.3. The
sequence, following the same style as §4.1's general trap entry:

```
on emulated-MMIO trap (guest access matches (PA & HEMUM) == HEMUB):
    HMAR  <- faulting virtual address
    HMCR  <- {SQ, DIR, SIZE, BANK, REGN}   # captured from the faulting access
    HMDR  <- store data                     # only if DIR = 1 and SQ = 0
    HSPC  <- PC of instruction AFTER the faulting access
    HSSR  <- SR
    SR.HPRIV <- 1 ; SR.MD <- 1 ; SR.BL <- 1 ; SR.RB <- 1
    EXPEVT   <- 0x1E0
    PC       <- VBR_HYP + 0x200
```

**Complete-on-resume contract.** The trapped access is architecturally complete except for its
register writeback (loads) or its bus effect (stores); the hypervisor supplies the missing half and
resumes with `HRTE`. Normative rules:

1. `HSPC` points **past** the faulting access, not at it. The instruction is architecturally
   complete in every respect except the one effect the aperture intercepted: a load's register
   writeback, or a store's effect on the target device. There is no instruction left to re-decode
   or re-execute on resume.
2. On `HRTE`, if `HMCR.DIR = 0` (load) and `HMCR.SQ = 0`, hardware writes `HMDR` into the register
   named by `HMCR.REGN`/`HMCR.BANK`, sign- or zero-extending per `HMCR.SIZE` exactly as the original
   load would have.
3. For `HMCR.DIR = 1` (store) and `HMCR.SQ = 0`, hardware performs no writeback on resume — the
   store's architectural effect on the emulated device is entirely the hypervisor's to produce (by
   updating its device model); there is no guest-visible register state to restore.
4. For `HMCR.SQ = 1` (a 32-byte store-queue burst targeting the aperture), hardware performs no
   writeback and does **not** clear the queue's `HSQCR.VALID`/`DIRTY` bits for the affected queue on
   trap entry. The data remains in the SQ buffers ([../sq/spec.md §6](../sq/spec.md)), not in
   `HMDR`. The hypervisor alone decides, after inspecting the buffer, whether the burst is
   considered consumed and clears `HSQCR` accordingly on resume.
5. If the faulting access was in a branch delay slot, `HSPC` points past the delay slot, and the
   branch has already been resolved before the trap was taken. The hypervisor needs no delay-slot
   handling: it never sees the branch instruction, only the already-decided post-branch PC.

**Rationale:** Complete-on-resume means the hypervisor never decodes an SH-4 instruction to
determine which register to fill or how many bytes a store touched — HMCR already carries REGN,
BANK, SIZE, DIR, and SQ, decoded once by hardware at trap time. It also means the hypervisor never
writes a guest GPR directly through an ad hoc register-file backdoor, because a trapped load's
destination may be `R8`–`R15`, which are **unbanked** and shared with the hypervisor's own register
file ([../priv-arch/design-spec.md §4.2](../priv-arch/design-spec.md)'s banking model covers only R0–R7). If the hypervisor wrote R8–R15 itself to deliver an
emulated load's result, it would have no scratch registers of its own left across the trap boundary
without spilling to memory on every single MMIO access. The `HRTE`-armed writeback port sidesteps
this: hardware performs the write, once, atomically with the mode transition back to guest context.

An alternative re-execute design — trap before the access, let the hypervisor synthesize the
correct instruction semantics in software, and single-step or emulate the access itself — would
solve the same two problems (no register corruption, no decode-once guarantee) but would cost
40–80 cycles of software instruction decode on every trapped MMIO access, since the hypervisor
would need to fetch and decode the guest instruction from scratch on each entry. Given a Dreamcast
workload dominated by device access (AICA sound registers, GD-ROM control, PVR2 tile-accelerator
registers), that per-access cost is unacceptable; complete-on-resume trades a fixed hardware cost
(§10) for a constant, small per-trap software path instead.

Prior art, pre-2006: IBM System/370 SIE (Start Interpretive Execution) interception controls
(1980, generally available 1983) delivered essentially this same contract for LPAR virtualization —
an intercepted instruction reports enough decoded state (opcode class, operand registers, access
type) for the host to complete or reject the operation and resume the guest without the host
re-fetching and re-decoding the original instruction stream.

## 5. Hyperprivileged-Only Instructions and Operations

Operations that are valid only when SR.HPRIV=1:

1. **LDC/STC to hyperprivileged control registers** (HSPC, HSSR, VBR_HYP, HEDR).
2. **HRTE** — Return from hyperprivileged exception.
3. **LDTLB / LDTLB.RN** without trapping (in supervisor mode, these trap; in hyperprivileged mode, they execute).
4. **Setting SR.HPRIV via LDC** — only possible to clear it (transitioning down via HRTE), never to set it directly; setting requires hyperprivileged-mode trap entry.

Attempts to execute hyperprivileged-only operations outside SR.HPRIV=1 raise illegal-instruction trap, which delivers to the hypervisor (always; not delegate-able).

## 6. Reset State

| Register | Reset value |
|----------|-------------|
| SR.HPRIV | 0 |
| HSPC | undefined |
| HSSR | undefined |
| VBR_HYP | 0 |
| HEDR | 0 (all exceptions go to hyp; irrelevant since HPRIV=0 at boot) |

A J-Core CPU comes out of reset in non-virtualized mode (HPRIV=0). The boot ROM and kernel proceed exactly as in Phase 1. The hypervisor, if present, is loaded later and explicitly transitions into HS-mode via an initial HCALL.

## 7. Bootstrap of Hyperprivileged Mode

Since SR.HPRIV cannot be set directly via LDC, how does the system first enter HS-mode? Two options:

### 7.1 Reset-time HS-mode

Add a small ROM stub or fuse-controlled bit: if set at reset, the CPU enters HPRIV=1 immediately. The hypervisor is the first thing to run, then it sets up guests and HRTE's into them.

Implementation: one fuse bit `HYP_AT_RESET`. If set: SR.HPRIV=1, PC=reset_vector_hyp. If clear: SR.HPRIV=0, PC=reset_vector (Phase 1 behavior).

### 7.2 HCALL bootstrap from supervisor

The kernel boots normally (HPRIV=0). The hypervisor is loaded as a kernel module or built-in component. To activate it, the kernel executes HCALL #ACTIVATE_HYP with a pointer to the hypervisor's setup descriptor. The HCALL handler is at a fixed location (initially, the kernel installs the hypervisor's code at this location). On first HCALL, the CPU enters HS-mode and the hypervisor takes over.

This is the cleaner model — it lets the kernel be the "bootloader" for the hypervisor. The downside is that the kernel briefly has more privilege than the hypervisor (until the first HCALL); a Trusted Computing Base argument could prefer the reset-time option.

**Recommendation:** Implement both. The fuse bit (option 1) for production systems where the hypervisor is fully trusted; the HCALL bootstrap (option 2) for development.

## 8. Per-CPU Considerations (SMP)

Each CPU has its own:
- SR (including HPRIV bit)
- HSPC, HSSR, VBR_HYP, HEDR
- All Phase 1 MMU registers

The hypervisor runs on each CPU independently. Inter-CPU coordination (IPIs, shared data structures) is handled in software, using existing SMP primitives plus a few additional ones for virtual IRQ delivery.

The CPUINFO register (Phase 1 §2.9) gains one capability bit: `[16] = HYP_SUPPORT`. Hypervisor probe reads this bit to determine whether this CPU supports Phase 3.

## 9. Verification Points

Critical RTL verification:

1. **SR.HPRIV behavior:** Bit can be set only by hyp-trap entry; cannot be set by LDC from S or U mode.
2. **LDTLB trap from S mode:** When HPRIV=0 and MD=1, LDTLB traps to VBR_HYP+0x190 with correct HSPC/HSSR/EXPEVT.
3. **LDTLB direct from HS mode:** When HPRIV=1, LDTLB executes normally (no trap).
4. **HCALL from any mode:** Traps to VBR_HYP+0x100 regardless of HPRIV (but no-op if already in HPRIV=1 by default).
5. **HRTE:** Correctly restores SR (including HPRIV bit) and PC.
6. **HEDR delegation:** Exceptions with HEDR[cause]=1 deliver to VBR (S-mode); with HEDR[cause]=0 deliver to VBR_HYP (HS-mode). Always-to-hyp exceptions ignore HEDR.
7. **Hyperprivileged register protection:** Access to HSPC/HSSR/VBR_HYP/HEDR from S or U mode raises illegal-instruction trap.
8. **Backward compatibility:** With HPRIV never set (Phase 1 binary), all behavior matches Phase 1 exactly.
9. **Vector dispatch:** Correct offset selected based on EXPEVT and delivery destination.
10. **Emulated-MMIO trap on aperture match:** A guest access (`MMUCR.AT = 0` bare-metal or `MMUCR.AT = 1`) whose translated PA satisfies `(PA & HEMUM) == HEMUB` traps to `VBR_HYP + 0x200` with `EXPEVT = 0x1E0`, `HMAR` holding the faulting virtual address, and `HMCR` correctly capturing `{SQ, DIR, SIZE, BANK, REGN}` for every addressing mode and access width. A translated PA one byte outside the aperture on either boundary does not trap and reaches the bus normally.
11. **HSPC past-the-access invariant:** For both loads and stores, `HSPC` on trap entry equals the address of the instruction *after* the faulting access, never the faulting instruction itself, including when the faulting access is the last instruction before a taken branch.
12. **Complete-on-resume register writeback:** A trapped **load** targeting each of `R8`–`R15` resumes with the correct value delivered into the correct register and no corruption of any hypervisor register, tested **per-register, not once** — R8–R15 are the **unbanked** case ([../priv-arch/design-spec.md §4.2](../priv-arch/design-spec.md)), shared directly between guest and hypervisor context, and this is precisely the case complete-on-resume exists to handle without the hypervisor ever writing a guest GPR itself.
13. **Store and burst-store no-writeback:** A trapped store (`HMCR.DIR = 1`, `HMCR.SQ = 0`) performs no register writeback on `HRTE`. A trapped store-queue burst (`HMCR.SQ = 1`) additionally leaves `HSQCR.VALID`/`DIRTY` for the affected queue unchanged across the trap — hardware neither sets nor clears them — until the hypervisor's own `HRTE`-path write to `HSQCR`.
14. **SQ burst aperture routing:** An SQ burst whose translated target lies outside the aperture reaches memory with no trap; one whose translated target lies inside the aperture raises exactly one trap with `HMCR.SQ = 1`, regardless of how many of the eight word-stores preceding the `PREF` fell inside or outside the aperture.
15. **SQ context save/restore across VM exit:** A VM exit taken with `HSQCR.VALID` set for a partially-filled queue, followed by another vCPU running and bursting its own store queues, followed by re-entry to the first vCPU, leaves the first vCPU's queue's 32 bytes byte-identical to their state at exit.

## 10. Cost Estimation

Phase 3 hardware additions beyond Phase 1 baseline:

| Item | Cost |
|------|------|
| SR.HPRIV bit | 1 flop |
| HSPC, HSSR registers | 2 × word_size flops |
| VBR_HYP register | 1 × word_size flops |
| HEDR register | 32 flops |
| HCALL instruction decode | ~5 LUTs |
| HRTE instruction decode | ~5 LUTs |
| LDTLB-traps-from-S logic | ~30 LUTs |
| Hyperprivileged register access check | ~20 LUTs |
| Vector dispatch (VBR vs VBR_HYP selection) | ~30 LUTs |
| HEDR consultation logic | ~50 LUTs |
| HYP_AT_RESET fuse / mode | ~5 LUTs |
| Subtotal (Phase 3 pre-MMIO-trap) | ~150 LUTs, ~200 flops |
| Aperture comparator (`(PA & HEMUM) == HEMUB`, per access) | ~15 LUTs |
| `HEMUB`, `HEMUM` storage | 2 × word_size flops |
| `HMAR`, `HMDR` storage | 2 × word_size flops |
| `HMCR` storage (9 bits captured: SQ, DIR, SIZE, BANK, REGN) | 9 flops |
| `HSQCR` storage | 4 flops |
| Destination-register latch (REGN/BANK decode feeding writeback mux) | ~20 LUTs |
| `HRTE`-armed writeback port (complete-on-resume register write, §4.5) | ~60 LUTs |
| Two 32-byte SQ buffers with valid/dirty tracking | attributed to [../sq/spec.md](../sq/spec.md), not counted here (§10 note below) |
| `QACR` address-formation path reuse for aperture routing | ~15 LUTs |
| MMIO-trap control/sequencing (entry mux, EXPEVT/vector selection) | ~25 LUTs |
| **Emulated-MMIO trap subtotal** | **~120–180 LUTs, ~15 flops** |
| **Total (per core)** | **approximately 300 LUTs, ~215 flops** |

Arithmetic: 150 LUTs (existing Phase 3 baseline, row above) + 120–180 LUTs (emulated-MMIO trap,
this task) = 270–330 LUTs, stated conservatively as **approximately 300 LUTs** per core. This is a
doubling of the pre-existing Phase 3 hypervisor footprint, and it is not hidden: the single largest
contributor is the `HRTE`-armed complete-on-resume writeback path (§4.5), because it must decode
`HMCR.REGN`/`BANK`/`SIZE` into a register-file write port that can target any of R0–R15 including
the unbanked R8–R15, sign/zero-extend per size, and gate on `HMCR.DIR`/`SQ` — logic an ordinary
exception path does not need, since ordinary exceptions do not resume mid-instruction. The
alternative — a re-execute design that traps before the access and lets the hypervisor synthesize
the semantics in software — would remove this writeback port and most of the destination-register
latch, but was explicitly rejected (§4.5) because it would trade this fixed hardware cost for
40–80 cycles of software instruction decode on every trapped MMIO access, unacceptable for a
workload dominated by device access.

**Store-queue buffer attribution.** The two 32-byte SQ buffers and their valid/dirty tracking
listed above are **not** part of the hypervisor's gate cost: the store queue exists independently
of virtualization and is specified in [../sq/spec.md](../sq/spec.md) (§1–§5), whose own cost
accounting covers that storage. The hypervisor extension's only SQ-related cost is `HSQCR` itself
(4 flops, listed above) and the save/restore control path that persists `HSQCR` across VM exit/entry
(folded into the MMIO-trap control/sequencing row above) — it adds no additional queue storage.

For comparison, Phase 1 added ~600 LUTs to the baseline J-Core CPU. Phase 3, including the
emulated-MMIO trap specified in this section, is now roughly a 50% addition to Phase 1's footprint.
The entire CPU with MMU and hypervisor support is still well within the gate budget of mid-range
FPGAs.

## 11. What Phase 3 Does NOT Add

To be explicit: Phase 3 adds nothing to the TLB hardware, nothing to the TSB structure, nothing to the IOMMU. All virtualization happens through:

- A privilege-mode bit (one flop)
- A trap-delegation register (32 flops)
- A separate vector for hyperprivileged traps
- Two new instructions (HCALL, HRTE)
- One change to LDTLB behavior in supervisor mode

The rest is software. This is the central virtue of the design: it sits atop Phase 1 with minimal additions and uses Phase 1's primitives (TLB, TSB, ASID, PageMask) without modification.

## 12. Future Extensions

If patent landscape changes and post-2006 primitives become viable, the design can grow:

- **VMID-tagged TLB:** No longer on the roadmap. The 8-bit field that earlier drafts reserved in Phase 1/2 tag layouts is **removed** project-wide ([glossary §5](../glossary.md)). Hardware-VMID would have eliminated software ASID partitioning, but its patent risk is high until ~2030 (Intel VPID patents post-2008), and the ASID-partitioning approach (pre-2006 sun4v prior art) is sufficient at the guest counts this platform targets.
- **Two-stage hardware translation (G-TLB):** Add a stage-2 cache that automatically substitutes HPN for RFN at LDTLB time. Eliminates the LDTLB trap. Patent risk: high until ~2030 (Intel EPT, AMD NPT patents).
- **Nested virtualization:** Software-only; no new hardware. Just adds a layer of HEDR delegation. Implementable in Phase 3 without ISA changes if desired.

None of these are blocked by Phase 3 — the design space is left open.
