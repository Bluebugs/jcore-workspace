# J-Core Hypervisor Extension Hardware Implementation Specification (Phase 3)

**Status:** Draft  
**Scope:** RTL implementation guide for J-Core hyperprivileged mode  
**Audience:** Hardware engineers implementing the hypervisor extension  
**Prerequisites:** Phase 1 hardware spec ([../mmu/hardware-spec.md](../mmu/hardware-spec.md)), Phase 3 design spec ([design-spec.md](design-spec.md)), [../sq/spec.md](../sq/spec.md)

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

Also specified (added for bare-metal / Dreamcast-class guests):
- Forced translation for a guest's P0–P3, overriding the guest's `MMUCR.AT` (§2.4, §4.4.1)
- The emulation aperture `HEMUB`/`HEMUM` and its post-translation comparator (§2.5, §4.5)
- The MMIO-trap information registers `HPAR`, `HMDR`, `HMCR`, and the store-queue status
  register `HSQCR` (§2.6, §2.7)
- Complete-on-resume: the `HRTE`-armed register writeback port (§4.5)

What's not changed from Phase 1:
- **TLB storage and the TLB lookup function** — no new tag fields, no new match term, no VMID,
  no second-stage walk. What §4.4.1 changes is the *gate* in front of the lookup (whether a guest's
  P0–P3 access enters the TLB at all), not the lookup itself; a hit computes exactly as in Phase 1.
- The TSB structure (no new fields)
- The instruction set beyond HCALL and HRTE
- The **layouts** of MMUCR, PTEH, PTEL, TSBBR, TSBCFG, TSBPTR — every field keeps its bit position
  and its meaning. `MMUCR.AT` is the one register field whose *interpretation* changes, and only
  while a guest runs: see the amendment in §2.4.

Earlier drafts of this list claimed the aperture comparator and the forced-translation gate away
by asserting Phase 3 touched no address-translation hardware at all. It does — see §10's cost
table, which itemizes both — and the list above is corrected accordingly.

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
LDC Rm, HPAR     : 0100 mmmm 0110 1111   = 0x406F | m<<8
STC HPAR, Rn     : 0000 nnnn 0110 1111   = 0x006F | n<<8
LDC Rm, HMDR     : 0100 mmmm 0111 1111   = 0x407F | m<<8
STC HMDR, Rn     : 0000 nnnn 0111 1111   = 0x007F | n<<8
LDC Rm, HMCR     : 0100 mmmm 1000 1111   = 0x408F | m<<8
STC HMCR, Rn     : 0000 nnnn 1000 1111   = 0x008F | n<<8
LDC Rm, HSQCR    : 0100 mmmm 1001 1111   = 0x409F | m<<8
STC HSQCR, Rn    : 0000 nnnn 1001 1111   = 0x009F | n<<8
LDC Rm, PDID     : 0100 mmmm 1010 1111   = 0x40AF | m<<8
STC PDID, Rn     : 0000 nnnn 1010 1111   = 0x00AF | n<<8
```

This carves a new control-register family with capacity for up to 16 hyperprivileged control registers (slots 0–15). After allocation of HEMUB, HEMUM, HPAR, HMDR, HMCR, and HSQCR in slots 4–9 and `PDID` in slot 10 (§2.8), **five free slots (11–15) remain** for future hyperprivileged register extensions. All accesses in this family, executed with `SR.HPRIV=0`, raise the **hyperprivileged-register access exception**, delivered to the hypervisor and not delegatable to a guest. Its cause code, HEDR bit and vector are specified once, in [§3.4](#34-privileged-register-access-from-supervisor-mode), and are deliberately not restated here; the HEDR bit assignment is tabulated in [§2.3.1](#231-expevt-to-hedr-bit-mapping-normative). This enforces that only hyperprivileged code can read or write these registers.

The choice of low nibble `0xF` avoids collision with SH-4's existing `0xE` (LDC/STC) and `0xB`/`0xA`/`0x7`/`0x3` (LDC.L/STC.L variants) low nibbles in the 0100 family.

### 2.3 HEDR — Hypervisor Exception Delegation Register

```
[31:0]  Bitmap: bit N = 1 -> delegate exception cause N to supervisor (guest).
                bit N = 0 -> deliver exception cause N to hyperprivileged (host).
```

HEDR has 32 bits, each corresponding to an exception cause. The cause-to-bit mapping is fixed by hardware and given in §2.3.1; software cannot remap.

**Default after reset:** all bits 0 (all exceptions go to hyperprivileged). The hypervisor explicitly sets bits to delegate to the guest. A non-virtualized kernel never sets HPRIV, so HEDR is never consulted — backward compatibility is preserved.

**Delegation is safe only for a guest that shares J-Core's cause vocabulary.** Delegating a cause
sends the guest straight to its own `VBR` carrying J-Core's `EXPEVT` value. A J-Core-aware guest
reads that correctly. A stock SH-4 guest does not, wherever the two assignments differ, and it
cannot tell — the forbidden outcome of
[../sh4-guest-model.md §1](../sh4-guest-model.md), arriving through the fast path. For a stock
SH-4 guest the hypervisor keeps the affected causes undelegated and translates them on entry:
[../sh4-guest-model.md §3.4](../sh4-guest-model.md), Decision B2-2. Which causes those are cannot
be listed here yet, because this document's §2.3.1 table and
[../mmu/hardware-spec.md §5](../mmu/hardware-spec.md) do not currently agree on J-Core's own
assignment — see the *J-Core `EXPEVT` cause table* row in
[../fact-ownership.md](../fact-ownership.md)'s `Unresolved` list.

**Always-to-hypervisor causes** (§4.2): bits 0 (HCALL), 1 (guest LDTLB trap), 2 (hyperprivileged-register access from non-HS mode), and 25 (guest emulated-MMIO access, §4.5) are hard-wired to read-as-zero; software writes to these bits have no effect. These traps cannot be delegated to a guest because they exist solely to communicate with the hypervisor — bit 25 specifically exists only to reach the hypervisor's device model, and delegating it to a guest would be meaningless: there is no guest-side handler for a physical aperture the guest does not know exists.

#### 2.3.1 EXPEVT-to-HEDR-bit mapping (normative)

> **SUPERSEDED BY [../mmu/hardware-spec.md §5](../mmu/hardware-spec.md) (Vector column only) — 2026-08-25.**
> Bits **6** (`0x0A0`) and **7** (`0x0C0`) —
> TLB protection violation — are listed below at `+0x400`. They are delivered at
> **`+0x100`**; only misses (bits 4, 5) use `+0x400`. See [§4.2](#42-vector-layout-normative)
> for the full statement and the merged commit. HEDR bit *positions*, EXPEVT
> *values* and delegatability are unaffected.

The mapping is dense from the low bits up so a typical hypervisor configuration looks like a small bitmask. SH-4-inherited EXPEVT values are grouped by class; J-Core hyperprivileged-extension causes (`0x190`, `0x1B0`–`0x1F0`) follow. The extension causes deliberately avoid every SH-4-inherited code point.

| HEDR bit | EXPEVT     | Cause                                                    | Delegatable? | Vector (from VBR / VBR_HYP) |
|---------:|------------|----------------------------------------------------------|:------------:|:---------------------------:|
|    0     | `0x1D0`    | HCALL instruction                                        | **no**       | `+0x180` |
|    1     | `0x190`    | Guest LDTLB / LDTLB.RN trap                              | **no**       | `+0x190` |
|    2     | `0x1F0`    | Hyperprivileged-register access from non-HS mode         | **no**       | `+0x300` |
|    3     | `0x1B0`    | `EXC_FPU_DISABLED` — SR.FD trap (Tier 2 FPU)             | yes          | `+0x100` |
|    4     | `0x040`    | TLB miss (read)                                          | yes          | `+0x400` |
|    5     | `0x060`    | TLB miss (write)                                         | yes          | `+0x400` |
|    6     | `0x0A0`    | TLB protection violation (read)                          | yes          | `+0x400` |
|    7     | `0x0C0`    | TLB protection violation (write)                         | yes          | `+0x400` |
|    8     | `0x0E0`    | Address error (read)                                     | yes          | `+0x100` |
|    9     | `0x100`    | Address error (write)                                    | yes          | `+0x100` |
|   10     | `0x800`    | FPU **disable**, general (SH-4-inherited) — see note      | yes          | `+0x100` |
|   11     | `0x820`    | FPU **disable**, in branch-delay slot (SH-4-inherited)    | yes          | `+0x100` |
|   12     | `0x180`    | General illegal instruction (SH-4 meaning, sole user)    | yes          | `+0x100` |
|   13     | `0x1A0`    | Slot illegal instruction (SH-4 meaning, sole user)       | yes          | `+0x100` |
|   14     | `0x160`    | Unconditional TRAPA                                      | yes          | `+0x100` |
|   15     | `0x600`    | External IRL interrupt                                   | yes          | `+0x600` |
|   16     | `0x620`    | NMI                                                      | yes          | `+0x600` |
|   17     | `0x640`    | User break                                               | yes          | `+0x600` |
|   18     | `0x500`    | Reserved-instruction (no Tier 2 FPU present)             | yes          | `+0x100` |
|   19     | `0x5C0`    | Initial-page-write (dirty trap)                          | yes          | `+0x100` |
|   20     | `0x6E0`    | Inter-processor interrupt (host-targeted)                | yes          | `+0x600` |
|   21     | `0x700`    | PMU counter-overflow interrupt                           | yes          | `+0x600` |
|   22     | `0x720`    | L2 ECC / parity error (where instrumented)               | yes          | `+0x600` |
|   23     | `0x740`    | IOMMU fault forwarded as exception                       | yes          | `+0x600` |
|   24     | `0x1C0`    | `EXC_SIMD_DISABLED` — SR.VD trap (Tier 2 SIMD, new)      | yes          | `+0x100` |
|   25     | `0x1E0`    | Guest emulated-MMIO access (aperture, P4)                | **no**       | `+0x200` |
|   26–31  | —          | reserved (future causes)                                 | yes          | per §4.2 mirror rule       |

Notes:
- "Delegatable?" = whether the bit accepts software writes. Hardware ignores writes to non-delegatable bits, which always read 0.
- **Every EXPEVT value in this table is unique to one cause.** No code point is overloaded and no cause is "distinguished by context" or by which HEDR bit is set. In particular `0x180` means SH-4 general illegal instruction and only that (bit 12), and `0x1A0` means SH-4 slot illegal instruction and only that (bit 13); the two hypervisor extension causes that formerly squatted on them now use `0x1D0` (HCALL, bit 0) and `0x1F0` (hyperprivileged-register access, bit 2). See the reconciliation note in [§4.2](#42-vector-layout-normative).
- The mapping is **stable**: future hardware revisions may add causes in bits 24–31 but MUST NOT reassign bits 0–23. **The EXPEVT reassignment described in the note above did not move any HEDR bit.** HCALL is still bit 0 and hyperprivileged-register access is still bit 2, exactly as before; only the EXPEVT *values* those two bits are associated with changed (`0x180` → `0x1D0` and `0x1A0` → `0x1F0`). Software that keys off HEDR bit positions is unaffected.
- The **Vector** column gives the offset from `VBR` (supervisor delivery) or from `VBR_HYP`
  (hyperprivileged delivery) at which the cause is delivered. They are the same number: §4.2's
  mirror rule states that HS-mode delivery reuses the supervisor offset for every inherited cause,
  and only the four Phase-3 extension causes (bits 0, 1, 2, 25) have dedicated offsets. Reading this
  table together with §4.2's offset-major table gives the cause-to-vector mapping in both
  directions, with no cause left vectorless and no offset left unbound.

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

6. **The comparator is evaluated only for a non-speculative access.** On an implementation that
   speculates, an access whose physical address lies in P4, in the aperture, or in an uncacheable
   page is not issued until it is the oldest un-retired access of its thread
   ([../ooo/j32ooo-spec.md §8.2b](../ooo/j32ooo-spec.md),
   [../ooo/j32lt-spec.md §7.4b](../ooo/j32lt-spec.md)); the aperture test, and the `HPAR`/`HMCR`/`HMDR`
   capture of §4.5, happen only at that point. Rules 1–5 above are otherwise unchanged.

   Without this, three things break, none of them visible on an in-order core: a squashed access
   that matched the aperture would write the capture registers a genuine trap is about to consume,
   handing the hypervisor's device model an address the guest never accessed; a speculative load of
   an emulated or real device register would be a real read with real side effects; and a guest
   could locate the aperture boundaries by timing squashed accesses, disclosing the device map.
   Hardware prefetchers likewise never generate an access into P4, the aperture, or an uncacheable
   page — such a prefetch is dropped silently and is never a trap source.

   Pre-2006 prior art for withholding a memory access on behalf of a speculative instruction until
   the speculation resolves, filed for exactly this hazard: Intel US6035393 (Glew & Gupta, priority
   1995, expired), whose stated purpose is preventing a speculative prefetch from reaching
   uncacheable memory-mapped I/O.

**Design rationale:** The emulation aperture traps guest accesses to reserved regions, such as Dreamcast console I/O devices (the AIC, AICA, GD-ROM, etc.), which exist at fixed physical addresses. The trap diverts these accesses to the hypervisor, which can then emulate the behavior or inject the appropriate device state into the guest. Pre-2006 prior art: IBM S/370 storage keys (1970) pioneered physical-address-indexed access tests for memory protection; the aperture applies the same model to I/O emulation on a virtualized architecture.

### 2.6 HPAR, HMDR, and HMCR — MMIO Trap Information Registers

```
HPAR    Hypervisor Physical Address Register word-sized, hardware-written
HMDR    Hypervisor MMIO Data Register        word-sized, read/write
HMCR    Hypervisor MMIO Control Register     32-bit, hardware-written
```

**HPAR — Hypervisor Physical Address Register:** On an emulation aperture trap, HPAR captures the faulting **physical** address — the post-translation PA, the very address the aperture test `(PA & HEMUM) == HEMUB` (§2.5) matched on. It is not the virtual address.

**Decision:** ship the physical address only; the virtual address is not reported.

**Rationale:** the hypervisor cannot reconstruct the PA from a VA. Its own tables are RA-to-HPA maps; the missing VA-to-RA step lives exclusively in the *guest's* page tables, which the hypervisor does not own and which the guest may mutate between the trap and the hypervisor's inspection. Reporting the VA would therefore hand the hypervisor an address it cannot resolve, while the PA is exactly what the device model needs: the aperture offset is `HPAR & ~HEMUM`, computed directly, with no table walk of any kind. Nothing in the emulated-MMIO path needs the VA — the aperture is a physical-address construct end to end (§2.5, §4.5). Reporting only the PA is also the smaller capture: one word, latched from the same comparator input that raised the trap.

**Why HPAR is a new register, not an alias of TEA:** The TLB exception address register (TEA) is written by TLB exceptions delivered to the *guest* (miss, protection violation, etc.). Overloading HPAR onto TEA would destroy the guest's TEA state whenever an emulation aperture trap occurs, even though the guest never sees that trap and cannot know its TEA was clobbered. This would break the guest's TLB miss handler invariants. HPAR as a separate register preserves guest state and closes a previously-open design question (design spec, item 3).

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

**VALID[1:0] and DIRTY[1:0]:** The SQ hardware sets VALID bits to 1 when the corresponding queue slot is written by the guest, and clears them on a burst (when the queue is flushed to memory). DIRTY bits shadow valid bits until cleared. The hypervisor uses these bits to determine which queue slots hold pending store data. Write access to HSQCR is allowed only at `SR.HPRIV = 1` for context restore (clearing bits after reading them, or setting them to match saved state). Writes at `SR.HPRIV = 0` raise the hyperprivileged-register access exception exactly as for every other register in the §2.2 family. [§3.4](#34-privileged-register-access-from-supervisor-mode) is the canonical description of that exception — its cause code, HEDR bit, delegability and vector are stated there and are deliberately **not** restated here.

**Per-vCPU context:** HSQCR is per-vCPU state, saved and restored across VM exit and entry as part of the vCPU context-save/restore sequence.

**Reset value:** 0 (both queues empty).

**Cross-reference:** The store queue architecture and the format of the queue buffers are specified in [../sq/spec.md §6](../sq/spec.md).

### 2.8 PDID — Predictor Domain ID (speculative-execution implementations only)

> **SUPERSEDED BY [../mmu/hardware-spec.md §2.1a](../mmu/hardware-spec.md) (one premise only) — 2026-08-25.**
> This section twice argues from `ASID_TAG`'s generation field, and **that field
> no longer exists**:
> **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: retire the ASID generation nibble".**
> `ASID_TAG[15:12]` is reserved and always zero.
>
> **Two consequences, and the second is the security-relevant one.**
>
> 1. Both affected sentences cite **`glossary.md §5`** as their authority for the
>    generation field. That citation is now dangling twice over: the glossary no
>    longer carries the claim, and per
>    [../decisions/0001](../decisions/0001-one-authority-per-fact.md) it is no
>    longer an authority for values at all. The owner is
>    [../mmu/hardware-spec.md §2.1a](../mmu/hardware-spec.md).
> 2. *"Any predictor index that truncates `ASID_TAG` discards the one field that
>    separation depends on"* — **the reasoning is void, the conclusion is not.**
>    Truncation no longer discards a generation field, because there is none. It
>    still discards `ASID[11:8]`, i.e. **15/16ths of the 4096-ASID range**, and
>    guest-to-guest separation still rests **entirely** on ASID range
>    partitioning because this design still has no VMID (§12). So "do not
>    truncate `ASID_TAG` into the predictor index" survives on the range
>    argument alone.
>
> **This header does not re-derive the security argument** — that is Wave-1
> **C0**, whose adversary model (guest kernel on a shared core) is the one that
> should settle it. The premise is flagged, not patched, and a reviewer must not
> read the surviving conclusion as evidence that the stated reasoning holds.

```
PDID    Predictor Domain ID     6 bits, [31:6] RAZ/WI
```

**Required on any implementation that speculates** — [../ooo/j32ooo-spec.md §20.10](../ooo/j32ooo-spec.md) and [../ooo/j32lt-spec.md §3.5](../ooo/j32lt-spec.md). Not required on the in-order J2/J32 cores, which have no predictor state to isolate; `CPUINFO` bit `[17] = PDID_SUPPORT` reports its presence.

`PDID` names the **security domain** that indexes and tags every branch-predictor structure — the direction predictors, the BTB, the return-address stack, and the prefetch tables. Hardware combines it with `SR.HPRIV`, `SR.MD` and the thread-context ID to form the predictor tag; software's only obligation is to give distinct domains distinct `PDID` values.

**Software contract:**

- The hypervisor writes `PDID` on every world switch, before `HRTE` into a guest.
- Distinct guests MUST receive distinct `PDID` values. A hypervisor that runs more than 64 concurrent guests must recycle values, and must issue the predictor-invalidate control ([../ooo/j32ooo-spec.md §20.4](../ooo/j32ooo-spec.md)) when it does — the same generation problem `ASID_TAG` solves with its generation field, in a register too small to carry one.
- An unvirtualized kernel writes `PDID` at `switch_mm`, or leaves it at 0 and relies on the invalidate control alone.

**Why this exists rather than reusing `ASIDR`.** Two reasons, both discovered only when speculation and virtualization were considered together:

1. Trap entry does not change `ASIDR`, so the hypervisor executes with whatever `ASID_TAG` the guest left. Host and guest would share a predictor domain, and a guest could train the branch targets of the HCALL dispatcher (§3.1), the guest-`LDTLB` handler (§3.3) or the emulated-MMIO device model (§4.5) — all of which run at `SR.HPRIV = 1` against addresses the guest chose. This is VMScape (CVE-2025-40300), where the same property on shipping x86 parts allowed a guest to extract host memory.
2. `ASID_TAG`'s top 4 bits are the generation discriminator ([../glossary.md §5](../glossary.md)), and guest-to-guest separation rests **entirely** on ASID range partitioning because this design has no VMID (§12). Any predictor index that truncates `ASID_TAG` discards the one field that separation depends on.

**`SR.HPRIV` is a hardware term of the predictor tag and is deliberately not folded into `PDID`.** A hypervisor that forgets to update `PDID` must still be unable to share a predictor domain with the guest it just trapped from: the guest→host path fails closed in hardware, and only the guest→guest path depends on software discipline — which it already does, through ASID allocation.

**Per-vCPU** (§2.9). **Reset value:** 0.

Prior art: sun4v's `PRIMARY_CONTEXT`/`SECONDARY_CONTEXT` with the hyperprivileged nucleus context distinct from any guest context (UltraSPARC Architecture 2005, hyperprivileged edition) — a short, software-written domain number selecting which translations and cached state apply, which is exactly this register's job; MIPS R4000 ASID (1991); SH-4 (1998).

### 2.9 Per-vCPU state on multi-threaded implementations

Every register this specification calls "per-vCPU, saved and restored across VM exit and entry" —
`SR.HPRIV`, `HSPC`, `HSSR`, `VBR_HYP`, `HEDR`, `HEMUB`, `HEMUM`, `HPAR`, `HMDR`, `HMCR`, `HSQCR`,
`PDID` — assumes a core that runs one vCPU at a time.

**On an FGMT implementation that assumption is false and the save/restore contract cannot hold.**
[../ooo/j32ooo-spec.md §13](../ooo/j32ooo-spec.md) runs two thread contexts concurrently and
[../ooo/j32lt-spec.md §9](../ooo/j32lt-spec.md) runs four. Two or four vCPUs are resident
simultaneously; there is no exit at which to run a save sequence. **On such implementations every
register in the list above is per thread context**, and so are the store-queue buffers and
`QACR0`/`QACR1` ([../sq/spec.md §7](../sq/spec.md)).

The store queue is the one that fails without any speculation involved: §4.4.3 carves the SQ region
out of the guest-mode P4 trap so a guest can use it at native speed, and two vCPUs writing the same
32-byte buffer interleave their bytes into whichever one issues the `PREF`. That is direct cross-vCPU
disclosure and corruption on the hot path the carve-out exists to accelerate. See
[../ooo/j32lt-spec.md §16.12](../ooo/j32lt-spec.md) for the cost, which at four contexts is the
largest single security line item in that design.

**This list is incomplete as of 2026-09-08, and the missing entry is known.**
[../bi-endian-spec.md §6](../bi-endian-spec.md) (Decision BE-1) adds a per-context **byte-order
mode** covering both the data path and instruction fetch, hypervisor-owned and neither
guest-writable nor guest-readable. It is carried in **two** bits, and only one of them belongs in
this list:

- **`LE`** — the byte order of the current non-hyperprivileged context. **Per-vCPU state**, by the
  same argument as everything above, and **per thread context** by the same argument again. When it
  exists it belongs in this list and in the save/restore contract. A guest resumed under the wrong
  byte order sees silently wrong data *and executes silently wrong instructions* — the outcome
  [../sh4-guest-model.md §1](../sh4-guest-model.md) outlaws, now reachable through the fetch path
  as well as the data path.
- **`HLE`** — the byte order hyperprivileged code runs in, and therefore the byte order every
  hypervisor entry starts in. It describes the **host**, of which there is one, and is written once
  at hypervisor initialisation. It is **not** per-vCPU and must not be added to this list; putting
  it here would make the byte order of the trap handler depend on which guest was interrupted,
  which is the exact property the second bit exists to remove
  ([../bi-endian-spec.md §6.2](../bi-endian-spec.md)).

Neither bit exists in `jcore-cpu` today, and neither has been allocated a register or a bit
position — [../bi-endian-spec.md §10](../bi-endian-spec.md) records that allocation as an open item
owned by **§2.2 of this document**.

*This paragraph previously named a per-guest **data** byte-order mode from Decision B2-1, as a
single unnamed bit. B2-1 is superseded; the mode covers both paths and takes two bits, of which one
is per-vCPU and one is not.*

This mirrors [../mmu/hardware-spec.md](../mmu/hardware-spec.md)'s per-context requirement for
`ASIDR`, `PTEH`, `TEA`, `MMUFSR` and `TSBPTR`, already recorded in
[../ooo/j32lt-spec.md §11](../ooo/j32lt-spec.md). The reasoning and the failure mode are identical:
silent attribution of one context's state to another.

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
4. Set EXPEVT = 0x1D0 (the HCALL trap code — unique to HCALL).
5. Jump to VBR_HYP + 0x180 (HCALL's own dedicated vector).

HCALL has both a dedicated vector (`VBR_HYP + 0x180`) and a dedicated EXPEVT (`0x1D0`). Neither is shared with any other cause, so the hypervisor's HCALL entry point never has to prove that a trap is a hypercall rather than a guest executing a bad opcode — see the reconciliation note in [§4.2](#42-vector-layout-normative).

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

When `SR.HPRIV = 0`, attempting to access any hyperprivileged register of the §2.2 family (HSPC, HSSR, VBR_HYP, HEDR, HEMUB, HEMUM, HPAR, HMDR, HMCR, HSQCR) raises the **hyperprivileged-register access exception**: `EXPEVT = 0x1F0`, HEDR bit 2, which is hard-wired non-delegatable (§2.3), so the trap always goes to the hypervisor. It is delivered at **`VBR_HYP + 0x300`** (§4.2) — the dedicated offset for the hyperprivileged-register / sensitive-instruction trap. `linux-spec.md` §3.3 names the entry point `jcore_hyp_entry_0x300`.

**This section is the canonical description of that mechanism.** It is one exception with one cause code, not a family: §2.2 (LDC/STC encodings) and §2.7 (`HSQCR` writes) both refer here rather than restating it, and §9 verification point 7 checks it by `EXPEVT` value. `0x1F0` is a code point of its own: it is **not** shared with the SH-4 slot-illegal-instruction cause, which keeps `0x1A0` and its `+0x100` vector exclusively (HEDR bit 13, delegatable). The two causes differ in both vector and EXPEVT, so no context rule or HEDR-bit inspection is needed to tell them apart.

This is the mechanism by which the hypervisor catches a guest that tries to manipulate its own hyperprivileged state.

**Reconciliation note.** Earlier drafts gave the hyp-register-access trap `EXPEVT = 0x180`, then `0x1A0`. Both squatted on SH-4-inherited code points (`0x180` general illegal instruction, `0x1A0` slot illegal instruction) and relied on a "distinguished by HEDR bit / by context" rule. That rule is withdrawn — see the reconciliation note in [§4.2](#42-vector-layout-normative). The trap now uses the unallocated code point `0x1F0`, and `0x1A0` reverts to meaning slot illegal instruction and nothing else.

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
- HCALL (EXPEVT 0x1D0)
- Guest LDTLB trap (EXPEVT 0x190)
- Hyperprivileged register access from non-HS mode (EXPEVT 0x1F0)
- Guest emulated-MMIO access (EXPEVT 0x1E0, §4.5)

These are the exceptions where delegation makes no sense.

### 4.2 Vector layout (normative)

> **SUPERSEDED BY [../mmu/hardware-spec.md §5](../mmu/hardware-spec.md), in part — 2026-08-25.**
> **The mirror rule below is correct and stands. The single TLB vector it mirrors
> does not exist any more.**
>
> This section says "**all** TLB miss/protection faults `+0x400` (a single
> vector)", and the offset table below puts the three protection causes (`0x0A0`,
> `0x0C0` ×2) at `0x400`. J-Core split them: **miss stays at `+0x400`; protection
> moved to `+0x100`**, the general-exception offset, as SH-4 itself does (SH7750
> hardware manual Rev 2.0 02/99).
>
> **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `sim/tests/mmuvecsplit.S`.**
> That guard makes each vector write a distinct marker, precisely so a silent
> regression of the split fails rather than passing quietly; it is in
> `full-regression.yml`. The commit that named the change,
> *"mmu: split TLB protection faults onto VBR+0x100, as SH-4 does"*, survives only
> on `origin/mmu/encoding-realign-sh4a` — it was rebased on the way to `master`,
> so the artifact is the citable evidence
> ([../decisions/0002 §3](../decisions/0002-supersede-convention.md)).
>
> **Consequences for this section, which a reader must apply by hand until the
> table is corrected:**
> - Rows `0x0A0` / `0x0C0` / `0x0C0` move from the `0x400` block to the `0x100`
>   block. The `0x400` block keeps only `0x040` / `0x060` / `0x080`.
> - The `§2.3.1` mapping table's `+0x400` entries for HEDR bits 6 and 7 are wrong
>   in the same way and by the same amount.
> - The paragraph beginning "The single `0x400` TLB vector …" is superseded
>   outright.
> - **A delegating hypervisor must forward *two* vectors, not one.**
>   [design-spec.md §4.5](design-spec.md) already states this correctly; this
>   section is the one that did not follow.
>
> Nothing else here is affected: the mirror rule, the four Phase-3 extension
> offsets, the `HCALL`→`0x1D0` / hyp-register→`0x1F0` decision and the normative
> closure are all independent of how many offsets the supervisor layout uses.
> Rewriting the table belongs to Wave-2 **B1** (EXPEVT/vector worklist), not to
> the header that flags it.

Hyperprivileged traps are delivered from the `VBR_HYP` base using the **same offset conventions as
`VBR`**. **These offsets are normative.** An implementation MUST place each handler at the stated
offset from `VBR_HYP`.

**Decision: HS-mode delivery mirrors supervisor-mode delivery for every inherited cause.** A cause
that is not one of the four Phase-3 extension causes below is delivered to HS mode at *exactly the
same offset from `VBR_HYP`* that it uses from `VBR` — general exception `+0x100`, **all** TLB
miss/protection faults `+0x400` (a single vector; see [../mmu/hardware-spec.md §5](../mmu/hardware-spec.md)),
interrupt `+0x600` — and the hypervisor demultiplexes by
`EXPEVT` / `INTEVT` exactly as a supervisor kernel already does. The four Phase-3 extension causes
keep dedicated offsets.

**Rationale:** the mirror rule is what makes the set of HS vectors *closed*. An earlier version of
this table listed seven offsets and ended "offsets not listed above are reserved", which left the
twenty-odd inherited SH-4 causes — every TLB fault, every address error, `TRAPA`, `EXC_FPU_DISABLED`
(`0x1B0`), `EXC_SIMD_DISABLED` (`0x1C0`) — with no legal vector at all whenever `HEDR` routed them
to the hypervisor, and listed `0x300` as a "privileged-instruction trap" that no section bound a
cause to. Mirroring costs no hardware (the offset function is already implemented for `VBR`; only
the base register changes, per §4.1) and means a hypervisor's dispatch code is structurally the same
code a kernel already has. Prior art is SH-4 itself: SH-4 delivers every exception at a fixed
`VBR + offset` and disambiguates the many causes sharing an offset by `EXPEVT`/`INTEVT` (Renesas/
Hitachi SH-4 hardware manual, 1998 — pre-2006). This rule adds nothing to that model; it reuses it
against a second base register.

Every offset below has a bound cause, and every cause of §2.3.1 has an offset:

```
Offset  Cause(s) delivered here                              EXPEVT / INTEVT
------  ---------------------------------------------------  ---------------
0x100   general illegal instruction                          0x180
        slot illegal instruction                             0x1A0
        unconditional TRAPA                                  0x160
        address error (read / write)                         0x0E0 / 0x100
        initial page write (dirty trap)                      0x5C0
        reserved instruction (no Tier 2 FPU)                 0x500
        FPU disable, general / in delay slot                 0x800 / 0x820
        EXC_FPU_DISABLED                                     0x1B0
        EXC_SIMD_DISABLED                                    0x1C0
0x180   HCALL                                        (P3)    0x1D0
0x190   guest LDTLB / LDTLB.RN trap                  (P3)    0x190
0x200   guest emulated-MMIO trap (aperture, §4.5)    (P3)    0x1E0
0x300   hyperprivileged-register access from non-HS  (P3)    0x1F0
        mode / sensitive-instruction trap (§3.4)
0x400   TLB miss, instruction fetch                          0x040
        TLB miss, data load                                  0x060
        TLB miss, data store                                 0x080
        TLB protection violation, instruction fetch          0x0A0
        TLB protection violation, data load                  0x0C0
        TLB protection violation, data store                 0x0C0
0x600   external IRL interrupt                               0x600
        NMI                                                  0x620
        user break                                           0x640
        inter-processor interrupt (IPI)                      0x6E0
        PMU counter-overflow interrupt                       0x700
        L2 ECC / parity error                                0x720
        IOMMU fault forwarded as exception                   0x740
```

**The four Phase-3 extension causes form a contiguous block: `+0x180`, `+0x190`, `+0x200`, `+0x300`.** Each has a dedicated vector *and* a dedicated EXPEVT (`0x1D0`, `0x190`, `0x1E0`, `0x1F0`), none of which collides with any SH-4-inherited code point. Every other cause reaches HS mode through the mirror rule and is demultiplexed by `EXPEVT`/`INTEVT`.

**Note on `0x800` / `0x820` — corrected 2026-09-08.** These rows previously read
"FPU exception (non-disable; arithmetic IEEE-754 trap)", contradicting
[../fpu/spec.md §6.3](../fpu/spec.md), which assigns them to the FPU-**disable**
exception. The FPU spec is right, and this is settled from the kernel rather than argued:
`linux@jcore` `arch/sh/kernel/traps_32.c` wires both codes to
`fpu_state_restore_trap_handler` under `CONFIG_SH_FPU` — the lazy-FPU *restore* path, which is
what an FPU-disable trap drives — and to `do_reserved_inst` / `do_illegal_slot_inst` on an SH-4
without an FPU. Stock SH-4's *arithmetic* FPU error is a different code entirely, `0x120`
(`arch/sh/kernel/cpu/sh3/ex.S`, `fpu_error_trap_handler`). Bit positions, EXPEVT values and
delegatability are unchanged; only the labels were wrong — **both of them**:
§2.3.1's two rows and the matching line in §4.2's vector table above, which an
earlier revision of this correction left uncorrected 25 lines above itself while
claiming the labels were the only thing wrong. Raised by Wave-2 **B2**, which needed one
answer to specify guest cause translation ([../sh4-guest-model.md §3.4](../sh4-guest-model.md)).

**`0x120` has no HEDR bit, and this note does not mint one.** J-Core has no FPU, so it raises no
arithmetic FP exception and needs no bit today; a Tier-1 FPU
([../fpu/spec.md §6](../fpu/spec.md)) would need one, and would have to take a reserved bit from
§2.3.1's `26–31` range. Flagged, not decided.

**Note on the TLB `EXPEVT` values above.** The TLB rows quote the codes of
[../mmu/hardware-spec.md §5](../mmu/hardware-spec.md), which is the authority on TLB fault delivery:
`0x040`/`0x060`/`0x080` for I-fetch/load/store miss, and `0x0A0` (I-fetch) / `0x0C0` (both data
directions) for protection violation. §2.3.1 of this document labels its HEDR bits slightly
differently (bit 4 `0x040` "read", bit 5 `0x060` "write"; bit 6 `0x0A0` "read", bit 7 `0x0C0`
"write"). That labelling disagreement predates this change and is **not** resolved here — it affects
which HEDR bit gates which fault, not which vector the fault lands on, and the mirror rule is
independent of it. It is recorded as an open item in §12.

The single `0x400` TLB vector is J-Core's supervisor TLB vector layout
([../mmu/hardware-spec.md §5](../mmu/hardware-spec.md)); the mirror rule carries it over unchanged.
A hyperprivileged TLB miss — an HS-mode access that misses — is delivered at that same offset, since
HS mode is where `SR.HPRIV = 1` and §4.1's first branch applies.

**Reconciliation note.** Earlier revisions of this specification gave `HCALL` `EXPEVT = 0x180` and
delivered it at `VBR_HYP + 0x100`, and gave the hyperprivileged-register access trap `EXPEVT = 0x1A0`
at `VBR_HYP + 0x300`. Both values squatted on SH-4-inherited code points (`0x180` general illegal
instruction, `0x1A0` slot illegal instruction), and the spec claimed hardware "distinguishes them by
context" or by which `HEDR` bit is set. **That rationale was wrong and is withdrawn.** `HEDR` is a
delegation-policy register the hypervisor writes; it is not exception status, so a handler cannot
read it to learn which cause fired. Under the mirror rule, HCALL therefore arrived at `+0x100` with
`EXPEVT = 0x180` — bit-identical to a guest executing a bad opcode arriving at `+0x100` with
`EXPEVT = 0x180`. The two need opposite handling (service the hypercall vs reflect an illegal-instruction
fault into the guest), and no architectural state distinguished them. The merge of the three TLB
vectors into one (Group D, [../mmu/hardware-spec.md §5](../mmu/hardware-spec.md)) removed the last
slack in the layout and made the collision unrecoverable rather than merely awkward.

**Decision:** HCALL moves to its own vector `VBR_HYP + 0x180` with `EXPEVT = 0x1D0`, and the
hyperprivileged-register access trap keeps `VBR_HYP + 0x300` but moves to `EXPEVT = 0x1F0`. `0x180`
and `0x1A0` revert to their stock SH-4 meanings and nothing else. **Rationale:** `0x1D0` and `0x1F0`
were the two unallocated code points in the `0x1x0` extension range (`0x1B0` is `EXC_FPU_DISABLED`,
`0x1C0` is `EXC_SIMD_DISABLED`, `0x1E0` is emulated-MMIO), so the fix costs no renumbering of anything
already assigned. Giving a distinct cause a distinct vector *and* a distinct cause code is stock SH-4
practice — SH-4 gives `TRAPA`, illegal instruction and slot illegal instruction separate `EXPEVT`
values precisely so a shared vector's handler can dispatch (Renesas/Hitachi SH-4 hardware manual,
1998). A unique vector with an ambiguous `EXPEVT` would have been a half-fix: the vector alone cannot
survive a future hypervisor that consolidates entry points. `HEDR` bit positions are unchanged
(§2.3.1). `linux-spec.md` §3.3 renames the entry symbol `jcore_hyp_entry_0x100` to
`jcore_hyp_entry_0x180` accordingly.

**The former `0x500` "external interrupt" row is withdrawn**; interrupts are delivered at `+0x600`,
per the mirror rule and SH-4's own interrupt vector. The former separate `0x600` "IPI" row folds
into the same offset: an IPI (`INTEVT = 0x6E0`) is an interrupt and is demultiplexed by `INTEVT`
alongside IRL, NMI, PMU, L2 and IOMMU sources.

These offsets are fixed by this specification and are relied on throughout: §3.3's reconciliation
note pins the guest LDTLB trap at `VBR_HYP + 0x190` (correcting an earlier draft's `0x300`), §3.4
and §5 pin the hyperprivileged-register access trap at `VBR_HYP + 0x300`, §4.5 pins the
emulated-MMIO trap at `VBR_HYP + 0x200`, [linux-spec.md §3.3](linux-spec.md) names its entry symbols
`jcore_hyp_entry_0x180` / `_0x190` / `_0x200` / `_0x300` after these numbers, and §9's verification
points 2, 4, 10, 17 and 18 check them by value. An earlier draft of this section called the offsets
"illustrative" and left them to the implementer; that disclaimer is withdrawn — it was inconsistent
with every other use of the table, and a hypervisor binary cannot be portable across implementations
that choose different ones.

**Normative closure (replaces the former "offsets not listed above are reserved").** An offset not
listed above is reserved *for new causes*, but no inherited cause is ever without a vector: for any
cause delivered to HS mode, `offset(cause)` is the same function §4.1 applies against `VBR`. If a
future revision adds a supervisor cause with a new `VBR` offset, that offset is automatically an HS
offset too, and this table is updated to name it.

### 4.3 EXPEVT values

The hyperprivileged-mode extension adds five new EXPEVT codes on top of the existing SH-4 set. The full per-cause delegation routing — including which bit of HEDR controls each cause — is specified normatively in [§2.3.1](#231-expevt-to-hedr-bit-mapping-normative). Summary of the new codes:

| Code  | Cause                                                          | HEDR bit | Delegatable? |
|-------|----------------------------------------------------------------|---------:|:------------:|
| 0x190 | Guest LDTLB/LDTLB.RN trap (new)                                | 1        | no           |
| 0x1B0 | `EXC_FPU_DISABLED` — SR.FD trap (Tier 2 FPU, new)              | 3        | yes          |
| 0x1C0 | `EXC_SIMD_DISABLED` — SR.VD trap (Tier 2 SIMD, new)            | 24       | yes          |
| 0x1D0 | HCALL instruction (new)                                        | 0        | no           |
| 0x1E0 | Guest emulated-MMIO access (aperture, new, §4.5)               | 25       | no           |
| 0x1F0 | Hyperprivileged register access from non-HS mode (new)         | 2        | no           |

None of these codes is an SH-4-inherited value; in particular `0x180` (general illegal instruction) and `0x1A0` (slot illegal instruction) are **not** in this table and retain their stock SH-4 meanings only.

Each of these is delivered at a vector given by §4.2: `0x190` at `+0x190`, `0x1B0` and `0x1C0` at `+0x100` (they are general exceptions), `0x1D0` (HCALL) at `+0x180`, `0x1E0` at `+0x200`, `0x1F0` (hyp-register access) at `+0x300`. The full cause-to-vector column for every cause, inherited ones included, is in [§2.3.1](#231-expevt-to-hedr-bit-mapping-normative).

Existing SH-4 EXPEVT codes retain their meanings. **§2.3.1's table is the only enumeration of them in this document**, and every row it does not mark "(new)" is an inherited code; consult it rather than a range. *(This sentence previously gave the inherited codes as "`0x040`–`0x130`, `0x500`–`0x740`". Both halves were wrong against §2.3.1's own table: `0x130` is not a code point at all and the low range stops short of `0x160` TRAPA, `0x180` general illegal and `0x1A0` slot illegal — the three the paragraph immediately above insists retain their stock SH-4 meanings — while the high range stops short of `0x800`/`0x820`, the FPU exceptions. Corrected by Wave-2 B1; no code point moved.)*

**`EXC_FPU_DISABLED` (0x1B0).** Raised when an FPU instruction is decoded with `SR.FD = 1` on a CPU that ships a Tier 2 (hypervisor-aware) FPU. The cause is subject to HEDR delegation: when `HEDR[bit-for-0x1B0] = 0` (the default) the trap is taken by the hypervisor, which uses it to implement the lazy FPU context-switch ABI (per-vCPU FPU-ownership flag, save/restore of the 136-byte FPU image, re-enable of `SR.FD = 0` in the guest's `HSSR` shadow before `HRTE`). When the bit is set, the trap is delegated to the guest's own supervisor handler (a guest OS that wants to manage its own lazy-FPU model for user threads sets the bit). The full trap-handler ABI, save/restore sequence, and migration corner cases are specified in [../fpu/spec.md §7](../fpu/spec.md).

**`EXC_SIMD_DISABLED` (0x1C0).** The exact analogue of `EXC_FPU_DISABLED` for the SIMD facility. Raised when any SIMD-touching instruction or register access (governed SIMD instruction, SIMDV/SIMDH prefix, VLD.Q/VST.Q, VEXT/VINS, VMKCHG, LDS/STS to P0 / VCSR / VFPUL, or the §5.8 boundary instructions FMOV.VS / FMOV.VD) is decoded with `SR.VD = 1` on a CPU that ships a Tier 2 (hypervisor-aware) SIMD implementation. HEDR-delegation rules are identical: bit 24 = 0 → trap to hypervisor (which implements lazy SIMD context-switch ABI: per-vCPU SIMD-ownership flag, save/restore of the **520-byte SIMD image** ([../simd/spec.md §2.5](../simd/spec.md)) — V0..V15 + P0 + VCSR, and deliberately **no VFPUL**, which was retired on 2026-07-17 — and re-enable of `SR.VD = 0` in `HSSR` before `HRTE`); bit 24 = 1 → trap delegated to guest's supervisor handler for guest-managed lazy SIMD across guest user threads. Full trap-handler ABI in [../simd/spec.md §2.6](../simd/spec.md). Note: the §5.8 boundary instructions also trap under SR.FD because they touch the scalar FPU register file; SR.VD wins when both are set.

**Guest emulated-MMIO access (0x1E0).** Raised when a guest (`SR.HPRIV = 0`) memory access translates to a physical address matching the emulation aperture defined by HEMUB/HEMUM (§2.5): `(PA & HEMUM) == HEMUB`. Not subject to HEDR delegation — bit 25 is hard-wired non-delegatable for the same reason as HCALL and the guest LDTLB trap (§2.3): the aperture exists to reach the hypervisor's device model, and a guest has no handler for a physical region it does not know is virtualized. Full delivery mechanics, register capture, and the complete-on-resume contract are specified in §4.5.

## 4.4 Guest-Mode Address Translation

A Dreamcast image is a bare-metal SH-4 binary: it runs with `MMUCR.AT = 0`, entirely inside
P1/P2, which are architecturally untranslated and bypass the TLB. Such a binary has no
translation path of its own. Two such guests loaded by the same hypervisor would both resolve
their P1/P2 references to the same physical addresses and collide in RAM. §4.4.1-§4.4.5 specify
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

### 4.4.1a Mode-dependent translation on a speculative implementation (normative)

§4.4.1 makes the translation regime depend on `SR.HPRIV`: a guest's P1/P2 go through the TLB, while
at `SR.HPRIV = 1` they are *folded* — `PA = VA & 0x1FFFFFFF`, no TLB lookup, **no permission check**.

On a core that executes speculatively, that is a mode-dependent address path in which one of the two
modes performs no access check at all. An access executed under a stale `SR.HPRIV` — issued before an
older `HRTE` resolved — would fold a guest virtual address directly onto host physical memory. **That
is a guest→host escape, not a side channel**, and it is the only place in this specification where a
speculation error loses the isolation boundary outright rather than leaking through a channel.

**Normative requirements on a speculative implementation:**

1. `SR.HPRIV` is not speculatively renamed; it belongs to the privileged register group whose writes
   are serializing.
2. `HCALL` and `HRTE` are serializing.
3. Every memory access carries the `SR.HPRIV`/`SR.MD` snapshot of its own instruction and selects its
   translation regime from that snapshot, never from the live register.

See [../ooo/j32ooo-spec.md §20.11](../ooo/j32ooo-spec.md). This is independent of §4.4.5's pinned
guest P1 mappings: that rule restores the non-faulting-handler proof, this one determines which
translation path an access takes. Both are required and neither implies the other.

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
**except** for accesses in the range `0xE0000000`-`0xE3FFFFFF`, which is the store-queue region
per [../sq/spec.md §2](../sq/spec.md). Those do not trap; they are handled CPU-locally as ordinary
store-queue operations.

> **The carve-out is conditional on the store queue existing, and today it does not.**
> `jcore-cpu` `origin/master` has no store queue and no decode of that range
> ([../sq/spec.md §1](../sq/spec.md)). A carve-out over hardware that does not exist is not an
> optimisation, it is a hole in a rule the rest of this section calls fail-closed: the guest's
> access neither traps nor is absorbed. **This carve-out must not be enabled on any
> implementation whose store queues are absent.** Recorded by
> [../sh4-guest-model.md §3.3](../sh4-guest-model.md).

**Trapping is what makes the host and guest P4 maps independent.** Because the guest's P4 access
never reaches the host decoder, the emulated SH-4 register map the VMM presents is free to use
stock SH-4 offsets where J-Core's own map does not — which it does for `CCR`, `QACR0` and
`QACR1`. See [../sh4-guest-model.md §3.2](../sh4-guest-model.md) and
[../soc/p4-mmio-map.md §5](../soc/p4-mmio-map.md) rule 8.

**The carve-out is exactly the SQ-decoded range, and no wider.** It stops at `0xE3FFFFFF` because
that is where [../sq/spec.md §2](../sq/spec.md)'s decode stops: `0xE4000000`-`0xEFFFFFFF` is
reserved and not SQ-decoded. An access there is neither absorbed by a queue nor handled by any
other block, so it **must** trap like the rest of P4 — the guest-mode P4 rule is fail-closed, and
there is no address in P4 that a guest can touch that neither traps nor is architecturally
defined. Earlier drafts of this section carved out the full `0xE0000000`-`0xEFFFFFFF` quarter,
which left `0xE4000000`-`0xEFFFFFFF` reaching the bus undefined; that is corrected here.

The carve-out applies to the *data* path only. A queue-data store to `0xE0000000`-`0xE3FFFFFF` is
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

### 4.4.5 Pinned guest P1 mappings (normative)

§4.4.1 forces translation on for a guest's P0–P3. For a flat, MMU-less guest (Configuration B of
[design-spec.md §4.2](design-spec.md)) that is the whole story. For a guest that runs its own MMU
and its own TLB-miss handler (Configuration A), forcing translation on removes a guarantee the
J-Core privileged architecture depends on, and this section restores it.

**The guarantee at stake.** [../priv-arch/design-spec.md §4.7](../priv-arch/design-spec.md) proves
that a single level of `SPC`/`SSR` — no hardware trap-level stack — is sufficient, and the proof
turns on one fact: **the TLB-miss handler must never itself fault**, because a nested fault
overwrites `SPC`/`SSR` and the original fault's restart state is lost. §4.7 secures that by
requiring the per-CPU TSB and the kernel page tables to live in the untranslated direct map, P1,
where `PA = VA & 0x1FFFFFFF` and the miss handler's own `TSBPTR`-relative load can never trigger a
second translation. Under §4.4.1 a guest's P1 is no longer untranslated — so a guest miss handler
could miss the TLB on its own TSB load, take a recursive fault, and lose `SPC`/`SSR`.

**Decision (normative).** When the hypervisor admits a guest that uses its own MMU — any guest for
which HEDR delegates the TLB-miss causes (bits 4–7) to the guest, i.e. any guest that runs its own
miss handler — the hypervisor **MUST**, before the first entry to that guest:

1. install TLB mappings covering the guest's **entire P1 window** (`0x80000000`–`0x9FFFFFFF`,
   `VA[31:29] = 100`), using the largest page size that covers it, per
   [../mmu/hardware-spec.md §2.2](../mmu/hardware-spec.md)'s PageMask set — a guest whose real
   memory is one contiguous 16 MB region costs a single 16 MB entry, not a per-page table;
2. mark those entries **pinned**, and **MUST NOT** evict, demap, or replace them for as long as
   that guest is runnable. They are not eligible for replacement by guest `LDTLB` traps (§4.4.4),
   by host TLB pressure, or by the hypervisor's own refill.

The hypervisor MUST refuse to admit an MMU-using guest for which it cannot satisfy both
obligations (for example, because the TLB has too few entries left to hold the pinned set).

**Invariant restored.** With the guest's whole P1 window pinned and resident, a guest miss
handler's own memory accesses — the `TSBPTR`-relative TTE load and, on TSB miss, the page-table
walk — hit a TLB entry that is guaranteed present. The guest miss handler is again **provably
non-faulting**, in exactly the sense §4.7 uses, so one level of `SPC`/`SSR` remains sufficient for
a guest just as it is for a bare-metal kernel. The guest's TSB and page tables must still live in
its P1, exactly as §4.7 requires of an unvirtualized kernel; §4.4.1 changes how P1 is reached, not
where the guest must put those structures.

**Rationale.** The obligation is placed on the hypervisor rather than on hardware because hardware
has no way to know which of a guest's mappings back its miss handler, and because the alternative —
adding a second level of `SPC`/`SSR`, or a `TL`-style trap-level stack — is precisely the
mechanism [../priv-arch/design-spec.md §4.7](../priv-arch/design-spec.md) examined and rejected on
cost grounds. Pinning is also cheap here in a way it is not in general: the guest's P1 is a single
contiguous window, so the pinned set is one large-page entry per guest, which is the same entry
§4.4.1's flat-guest case already installs. Pre-2006 prior art for permanently-resident,
never-evicted hypervisor-installed translations: sun4v's permanent mappings
(`hv_mmu_map_perm_addr`, UltraSPARC Architecture 2005 hyperprivileged edition), introduced for
exactly this reason — to keep a guest's trap-handling path from faulting; and IBM System/370
storage-key-protected, permanently-resident nucleus pages (1970).

Cost of the guest's per-miss path under this rule is accounted in
[design-spec.md §5](design-spec.md).

### 4.5 Emulated-MMIO trap delivery and complete-on-resume

**Trap entry.** When a guest (`SR.HPRIV = 0`) access's translated physical address matches the
emulation aperture (`(PA & HEMUM) == HEMUB`, §2.5), hardware delivers the trap unconditionally to
the hypervisor — this is the bit-25 always-to-hypervisor case already listed in §4.1 and §2.3. The
sequence, following the same style as §4.1's general trap entry:

```
on emulated-MMIO trap (guest access matches (PA & HEMUM) == HEMUB):
    HPAR  <- faulting physical address (the PA the aperture matched)
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

1. `HSPC` holds **the PC at which the guest resumes had the access completed normally**, never the
   PC of the faulting instruction itself. Equivalently: `HSPC` points *past* the faulting access.
   The instruction is architecturally complete in every respect except the one effect the aperture
   intercepted — a load's register writeback, or a store's effect on the target device — so there
   is no instruction left to re-decode or re-execute on resume. Rule 5 states what "the resume PC"
   means when the access sits in a branch delay slot; it is the same rule, not a second one.
2. On `HRTE`, if `HMCR.DIR = 0` (load) and `HMCR.SQ = 0`, hardware writes `HMDR` into the register
   named by `HMCR.REGN`/`HMCR.BANK`, sign- or zero-extending per `HMCR.SIZE` exactly as the original
   load would have.

   **On an implementation with register renaming or a future-file, this write is performed at
   `HRTE`'s commit**, into the architectural register file, and it resets that register's rename-map
   entry to point at the ARF. `HRTE` is serializing on such implementations. An out-of-band write to
   the ARF while the rename map still redirects readers to an in-flight ROB entry would be silently
   lost — the writeback port described here assumes a machine with one register file and no rename
   map, and this is what that assumption costs. See [../ooo/j32ooo-spec.md §4.7](../ooo/j32ooo-spec.md)
   and [../ooo/j32lt-spec.md §6.6](../ooo/j32lt-spec.md). `HCALL` and any write of `SR.HPRIV` are
   serializing for the related reason in §4.4.1a.
3. For `HMCR.DIR = 1` (store) and `HMCR.SQ = 0`, hardware performs no writeback on resume — the
   store's architectural effect on the emulated device is entirely the hypervisor's to produce (by
   updating its device model); there is no guest-visible register state to restore.
4. For `HMCR.SQ = 1` (a 32-byte store-queue burst targeting the aperture), hardware performs no
   writeback and does **not** clear the queue's `HSQCR.VALID`/`DIRTY` bits for the affected queue on
   trap entry. The data remains in the SQ buffers ([../sq/spec.md §6](../sq/spec.md)), not in
   `HMDR`. The hypervisor alone decides, after inspecting the buffer, whether the burst is
   considered consumed and clears `HSQCR` accordingly on resume.
5. Rule 1 applied to a delay slot: if the faulting access is in a branch delay slot, the resume PC
   is the **branch target** (or the fall-through, for an untaken conditional branch), because that
   is where a normally-completing guest would go next. The branch is already resolved when the trap
   is taken, so `HSPC` holds that already-decided post-branch PC — which is what "past the access"
   means here, the delay slot being the last instruction executed before the transfer. The
   hypervisor needs no delay-slot handling and never sees the branch instruction.

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

### 4.6 Which accesses may target the aperture (normative)

`HMCR` can describe a bounded set of accesses and no more. `REGN`/`BANK` name one of R0–R15 in one
bank, and `DIR` is a single bit — so an access with two register results, no general-register
result at all, or a result outside the general-register file has no representation in `HMCR`, and
the complete-on-resume writeback port of §4.5 rule 2 would have nothing well-defined to do.

**Decision:** exactly the following access classes may target the emulation aperture. This is the
**representable set**:

```
Loads and stores of the plain MOV family:
  MOV.B / MOV.W / MOV.L, in either direction, with any of the addressing modes
  @Rn, @Rn+, @-Rn, @(disp,Rn), @(R0,Rn), @(disp,GBR), @(disp,PC)   (load side)
  -> HMCR.DIR, SIZE, REGN, BANK describe the access completely; HMCR.SQ = 0.

The 32-byte store-queue burst triggered by PREF (§4.4.3, ../sq/spec.md §4):
  -> HMCR.SQ = 1; SIZE, REGN and BANK are ignored, data lives in the SQ buffers.
```

**Decision:** any *other* access that resolves to a physical address inside the aperture is an
**unrepresentable aperture access**. Hardware does **not** raise the emulated-MMIO trap for it.
It raises the general illegal-instruction / reserved-instruction path instead (EXPEVT `0x180`,
HEDR bit 12), which is delegatable and therefore lands wherever the guest's own
illegal-instruction handling is configured to land. Concretely, the unrepresentable classes are:

- read-modify-write accesses: `TAS.B @Rn` (reads, sets bit 7, writes back, and also writes `T`);
- FPU and SIMD memory accesses: `FMOV.S`/`FMOV.D`/`FMOV.VS`/`FMOV.VD`, `VLD.Q`/`VST.Q`
  ([../fpu/spec.md §6](../fpu/spec.md), [../simd/spec.md §5.8](../simd/spec.md)) — the
  destination is an FPU/SIMD register, which `HMCR.REGN`/`BANK` cannot name;
- `MAC.W` / `MAC.L`, whose two operand fetches and `MACH`/`MACL` accumulate are not one
  register writeback;
- instruction fetch from inside the aperture (executing out of an emulated device).

**Consequent obligation on the VMM (normative):** the VMM MUST NOT place inside the aperture any
physical page that the guest reaches by an unrepresentable access. For a bare-metal guest this is
checkable ahead of time — the device register windows a Dreamcast image touches
([linux-spec.md §4.5](linux-spec.md)) are byte/word/longword `MOV` accesses and store-queue
bursts, exactly the representable set. A guest that issues an unrepresentable access into the
aperture is a guest whose device model the VMM got wrong.

**Where that exception is delivered depends on HEDR, and the VMM must choose.** The exception is
raised through the general illegal-instruction path, and HEDR bit 12 is delegatable — so it is
delivered to whichever handler HEDR selects: to the hypervisor if bit 12 is *not* delegated, or to
the guest's own illegal-instruction handler if it is. In the delegated case the guest absorbs the
violation and **the VMM never learns its device model is wrong**. Failure is closed either way —
no bus access, no partial emulation, no state the guest can exploit — but visibility is not
automatic. A VMM that wants to observe guest device-model violations MUST NOT delegate HEDR
bit 12 for that guest. This specification does not add a separate non-delegatable code point for
the case; the routing is deliberately the ordinary illegal-instruction routing, and the
consequence is stated here so a VMM author can configure HEDR accordingly.

**Rationale:** the alternative is widening `HMCR` to encode a register file selector, a
second destination, and read-modify-write sequencing — a materially larger capture path and a
larger writeback mux, for access classes no known guest performs against MMIO. Failing closed (a
delivered exception, with no bus access and no partial emulation) is strictly better than failing
open (an aperture access that silently reaches the bus) or than a partially-decoded trap the
hypervisor cannot complete — and whether that failure is also *loud* to the VMM is an HEDR bit 12
configuration choice, per the paragraph above. Pre-2006 prior art for restricting which instruction classes may
target an intercepted region: IBM System/370-XA SIE (1980, generally available 1983) likewise
intercepts a defined set of instruction classes and presents an operation exception for
instructions outside it, rather than attempting to describe every possible operand form.

## 4.7 vCPU placement on multi-threaded implementations (normative)

On an FGMT implementation, the thread contexts of one core share the L1 caches, the L2, the TLB, the
TSB, the branch-predictor arrays and the prefetch tables
([../ooo/j32ooo-spec.md §13.3](../ooo/j32ooo-spec.md),
[../ooo/j32lt-spec.md §9.2](../ooo/j32lt-spec.md)). Those structures are not partitioned, and
partitioning them would consume most of what the extra contexts earn.

**Decision (normative):** a **physical core is the unit of guest allocation *at any instant***. Every
thread context of a core belongs to the same guest for as long as that guest is resident. The
hypervisor **MUST NOT** place vCPUs of different guests on contexts of one core **concurrently**.

The word "concurrently" is load-bearing and was absent from an earlier revision of this section. A
core may be shared between guests **over time**, provided the transition is a gang switch per §4.7.1.
Without that relaxation the rule caps the machine at one guest per core for its lifetime, which is a
much stronger constraint than the channels require.

Two placement modes therefore satisfy this section:

| Mode | Guests per core | When to use |
|---|---|---|
| **Dedicated** | one, for its lifetime | Simplest. No gang-switch cost, no residual-state flushing. The right default for a single-purpose appliance or a guest that must not see scheduling jitter |
| **Gang-scheduled** (§4.7.1) | many, one at a time | Recovers guest density on a small machine. Costs a flush sequence and a cold cache per quantum |

Consequences, stated plainly because they are a capacity statement as much as a security one:

- In **dedicated** mode a dual-core J32-OOO part hosts **two guests of up to two vCPUs each** and a
  dual-core J32-LT part **two guests of up to four vCPUs each**. Not four and eight.
- Under J32-LT the rule converts four contexts per core from four sellable guest slots into one
  guest's four vCPUs. That core's throughput advantage shows up as vCPUs-per-guest, not
  guests-per-board, in **both** modes — gang scheduling raises the number of guests a board can
  host, never the number that can run at one instant.
  [../jcore-ulx3s-service-plan.md §3](../jcore-ulx3s-service-plan.md) carries the counts.
- Nothing else in this specification changes. The isolation arguments of
  [design-spec.md §6](design-spec.md) — ASID partitioning, `TSBBR` ownership, hypervisor memory
  unmapped from S and U — are all *architectural* and hold regardless of placement. This rule
  addresses the *microarchitectural* contention channels those arguments do not reach.
- **The shared L2 is outside the reach of either mode.** A single set of L2 arrays serves every
  core ([../cache/l2-spec.md §2](../cache/l2-spec.md)), so two guests on two different cores share
  it no matter how vCPUs are placed. That channel is closed by way-partitioning
  ([../cache/l2-spec.md §16.1](../cache/l2-spec.md)), which is required in the baseline dual-core
  configuration and is not a gang-scheduling-specific measure.

### 4.7.1 Gang switching (normative, when the gang-scheduled mode is used)

All contexts of a core switch guests together, at a quantum boundary, never individually. The
hypervisor **MUST** perform the following before the first entry to the incoming guest. Each item is
a channel that would otherwise carry the outgoing guest's state across the boundary:

| # | Action | Mechanism | Cost |
|---|---|---|---|
| 1 | Quiesce every context of the core | ordinary trap into HS mode on each | — |
| 2 | Save each vCPU's context | §2.9's per-context state, ~318 B per vCPU | see below |
| 3 | Invalidate predictors, BTB, RAS and stride tables, **per context** | [../ooo/j32ooo-spec.md §20.4](../ooo/j32ooo-spec.md) | one register write each |
| 4 | Invalidate L1-I and L1-D | SH-4 `CCR.ICI` / `CCR.OCI`. **L1-D is write-through** ([../ooo/j32ooo-spec.md §11.2](../ooo/j32ooo-spec.md)), so there is no dirty data to write back and this is an invalidate, not a flush | one register write each |
| 5 | Flush the TLB | tens of entries; `ASID_TAG` tagging makes this unnecessary for *correctness*, and it is done for the channel | negligible |
| 6 | Switch `TSBBR`, `PDID`, `L2WAYMASK` | already per-guest (§2.8, design-spec §3.8, [../cache/l2-spec.md §16.1](../cache/l2-spec.md)) | three register writes |
| 7 | Restore the incoming guest's vCPU contexts, enter | §2.9 | — |

**The L2 is deliberately not flushed.** Way-partitioning ([../cache/l2-spec.md §16.1](../cache/l2-spec.md))
is what isolates it; a full L2 flush would cost ~655 µs of write-back at ~200 MB/s and dominate every
other item on this list by an order of magnitude. Ways are flushed only when a descheduled guest's
mask is reassigned to a different guest — 16 KB per way, ~82 µs.

**Quantum.** The dominant cost is not the flush sequence, which is a handful of register writes plus
~1.3 KB of context per four-vCPU gang; it is the **cold cache** the incoming guest starts with —
roughly 10k cycles to refill a modest working set from SDRAM. Budget **~15k cycles (~0.5 ms at
30 MHz) per gang switch**, giving ≤5% overhead at a **~10 ms quantum**. Three guests at that quantum
see ~20 ms worst-case scheduling latency. Both figures are ordinary for a time-sharing system and
neither requires the guest kernel to change.

**Guest-visible time.** The guest kernel is unaware of gang scheduling and needs no modification,
but it will observe multi-millisecond gaps in real time. The hypervisor MUST virtualize the guest's
timer and provide steal-time accounting, or the guest's own scheduler will mis-attribute the gap.
This is the one place where gang scheduling reaches into guest-visible behaviour.

**Prior art (pre-2006):** gang scheduling / coscheduling is Ousterhout, "Scheduling Techniques for
Concurrent Systems" (ICDCS 1982), which also documents the fragmentation cost below. Denelcor HEP
and Tera MTA scheduled thread groups on barrel front ends. Nothing here is post-2005, and it is in
any case hypervisor software policy rather than hardware.

**Fragmentation — the honest cost.** If the resident guest has fewer runnable vCPUs than the core
has contexts, the surplus contexts idle for the whole quantum. On J32-LT a guest with one runnable
vCPU runs at the single-thread floor of ~0.94 IPC
([../ooo/j32lt-spec.md §2.5](../ooo/j32lt-spec.md)) while three contexts sit empty. Idle *guests*
cost nothing, since they are not scheduled at all; the loss is confined to a scheduled guest that
lacks parallelism. This makes the mode's value workload-dependent in a way worth measuring rather
than assuming: a guest serving concurrent requests keeps the barrel full, while a guest running one
interactive shell does not.

**Why the hypervisor rather than hardware.** The same reason §4.4.5 puts pinned-mapping duty on the
hypervisor: hardware cannot know which vCPU belongs to which guest. And the same reason the rule
must be written down — it is invisible in the ISA, so a scheduler that violates it produces a
perfectly functional machine with no isolation between its co-resident tenants.

The exposure being bounded is pre-2006 documented, not speculative: Percival, *Cache Missing for Fun
and Profit* (BSDCan 2005), recovered an RSA key across a shared L1 between two hardware contexts of
one core, and observed that it applies to any system where caches are shared between mutually
untrusted execution threads.

## 5. Hyperprivileged-Only Instructions and Operations

Operations that are valid only when SR.HPRIV=1:

1. **LDC/STC to hyperprivileged control registers** (HSPC, HSSR, VBR_HYP, HEDR).
2. **HRTE** — Return from hyperprivileged exception.
3. **LDTLB / LDTLB.RN** without trapping (in supervisor mode, these trap; in hyperprivileged mode, they execute).
4. **Setting SR.HPRIV via LDC** — only possible to clear it (transitioning down via HRTE), never to set it directly; setting requires hyperprivileged-mode trap entry.

Attempts to execute hyperprivileged-only operations outside SR.HPRIV=1 raise the hyperprivileged-register access exception of §3.4 (`EXPEVT = 0x1F0`, HEDR bit 2), delivered at `VBR_HYP + 0x300` (§4.2), which always delivers to the hypervisor and is not delegatable.

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
4. **HCALL from any mode:** Traps to VBR_HYP+0x180 with `EXPEVT = 0x1D0`, regardless of HPRIV. Behaviour of `HCALL` executed at HPRIV=1 is implementer-defined per §3.1 (no-op or illegal-instruction trap); verify whichever the implementation documents.
5. **HRTE:** Correctly restores SR (including HPRIV bit) and PC.
6. **HEDR delegation:** Exceptions with HEDR[cause]=1 deliver to VBR (S-mode); with HEDR[cause]=0 deliver to VBR_HYP (HS-mode). Always-to-hyp exceptions ignore HEDR.
7. **Hyperprivileged register protection:** Access to any §2.2 hyperprivileged register (HSPC, HSSR, VBR_HYP, HEDR, HEMUB, HEMUM, HPAR, HMDR, HMCR, HSQCR) from S or U mode raises the hyperprivileged-register access exception with `EXPEVT = 0x1F0`, delivered to the hypervisor regardless of HEDR (bit 2 is non-delegatable).
8. **Backward compatibility:** With HPRIV never set (Phase 1 binary), all behavior matches Phase 1 exactly.
9. **Vector dispatch:** Correct offset selected based on EXPEVT and delivery destination.
10. **Emulated-MMIO trap on aperture match:** A guest access (`MMUCR.AT = 0` bare-metal or `MMUCR.AT = 1`) whose translated PA satisfies `(PA & HEMUM) == HEMUB` traps to `VBR_HYP + 0x200` with `EXPEVT = 0x1E0`, `HPAR` holding the faulting **physical** address (bit-identical to the PA presented to the aperture comparator), and `HMCR` correctly capturing `{SQ, DIR, SIZE, BANK, REGN}` for every access in the **representable set of §4.6** — that is, for each addressing mode (`@Rn`, `@Rn+`/`@-Rn`, `@(disp,Rn)`, `@(R0,Rn)`, `@(disp,GBR)`) and each access width (byte, word, longword) of the plain `MOV.{B,W,L}` load and store family, and for the 32-byte store-queue burst. Accesses outside that set are covered by verification point 16 instead. A translated PA one byte outside the aperture on either boundary does not trap and reaches the bus normally.
11. **HSPC resume-PC invariant (§4.5 rules 1 and 5):** For both loads and stores, `HSPC` on trap entry equals the PC at which the guest would have resumed had the access completed — never the faulting instruction itself. Two cases must both be checked: the faulting access in ordinary straight-line code (`HSPC` = address of the next instruction), and the faulting access in a branch delay slot (`HSPC` = the resolved branch target, or the fall-through for an untaken conditional branch).
12. **Complete-on-resume register writeback:** A trapped **load** targeting each of `R8`–`R15` resumes with the correct value delivered into the correct register and no corruption of any hypervisor register, tested **per-register, not once** — R8–R15 are the **unbanked** case ([../priv-arch/design-spec.md §4.2](../priv-arch/design-spec.md)), shared directly between guest and hypervisor context, and this is precisely the case complete-on-resume exists to handle without the hypervisor ever writing a guest GPR itself.
13. **Store and burst-store no-writeback:** A trapped store (`HMCR.DIR = 1`, `HMCR.SQ = 0`) performs no register writeback on `HRTE`. A trapped store-queue burst (`HMCR.SQ = 1`) additionally leaves `HSQCR.VALID`/`DIRTY` for the affected queue unchanged across the trap — hardware neither sets nor clears them — until the hypervisor's own `HRTE`-path write to `HSQCR`.
14. **SQ burst aperture routing:** An SQ burst whose translated target lies outside the aperture reaches memory with no trap; one whose translated target lies inside the aperture raises exactly one trap with `HMCR.SQ = 1`, regardless of how many of the eight word-stores preceding the `PREF` fell inside or outside the aperture.
15. **SQ context save/restore across VM exit:** A VM exit taken with `HSQCR.VALID` set for a partially-filled queue, followed by another vCPU running and bursting its own store queues, followed by re-entry to the first vCPU, leaves the first vCPU's queue's 32 bytes byte-identical to their state at exit.
16. **Unrepresentable aperture accesses fail closed (§4.6):** a guest `TAS.B @Rn`, `FMOV.S @Rm,FRn`,
    `MAC.L @Rm+,@Rn+`, or instruction fetch whose physical address falls inside the aperture raises
    the general illegal-instruction path, does **not** raise `EXPEVT = 0x1E0`, does **not** write
    `HPAR`/`HMDR`/`HMCR`, and does **not** reach the bus. Test both HEDR configurations: with
    bit 12 clear the exception is delivered at `VBR_HYP`; with bit 12 set it is delivered to the
    guest at `VBR` and the hypervisor is not entered. Fail-closed behaviour (no bus access, no
    aperture register capture) must hold identically in both.

19. **HCALL and general illegal instruction are distinguishable on both axes (§3.1, §4.2):** a guest
    `HCALL` and a guest general-illegal-instruction, taken under otherwise identical conditions,
    must differ in **both** the delivered vector and `EXPEVT`. The `HCALL` lands at
    `VBR_HYP + 0x180` with `EXPEVT = 0x1D0`; the illegal instruction lands at `+0x100` (or at
    `VBR + 0x100` if `HEDR` bit 12 is set) with `EXPEVT = 0x180`. Neither value nor offset may be
    shared. Check the same pairing for a hyperprivileged-register access (`+0x300` / `0x1F0`)
    against a slot illegal instruction (`+0x100` / `0x1A0`). This is a regression guard against the
    collision described in §4.2's reconciliation note.

17. **Hyp-register-access trap vector (§3.4, §4.2):** an access to any §2.2 hyperprivileged register
    executed in supervisor mode (`SR.MD = 1`, `SR.HPRIV = 0`) lands at `VBR_HYP + 0x300` with
    `EXPEVT = 0x1F0`, `HSPC`/`HSSR` correctly captured, and does so regardless of `HEDR` bit 2 or
    bit 13. Check the same from user mode. This offset previously had no bound cause; verifying it
    by value is what keeps `0x300` from drifting back into being a placeholder.
18. **Inherited cause delegated to HS mode arrives at its mirrored offset (§4.2):** for a
    representative inherited cause of each vector class — a `TRAPA` (`EXPEVT 0x160`, `+0x100`), a
    data-load TLB miss (`EXPEVT 0x060`, `+0x400` — the single TLB vector), and an external IRL interrupt (`INTEVT 0x600`, `+0x600`) — taken
    while a guest is running with the corresponding `HEDR` bit **clear**, the trap is delivered at
    `VBR_HYP` **plus the same offset the supervisor path uses from `VBR`**, not at any dedicated
    hypervisor offset. Then set the `HEDR` bit and confirm the identical cause arrives at
    `VBR + <same offset>` in the guest. The offset must be bit-identical between the two runs; only
    the base register changes.

### 9.1 Additional verification points on a speculative implementation

These apply only to cores that speculate ([../ooo/j32ooo-spec.md §20.8](../ooo/j32ooo-spec.md) gates
S7–S12, [../ooo/j32lt-spec.md §12.2](../ooo/j32lt-spec.md) gates S5–S8, where they are stated as
CPU-side gates; repeated here so a hypervisor-side reviewer sees them):

20. **Predictor domain separation (§2.8).** A guest that trains an indirect branch at the virtual
    address of a hypervisor dispatch site produces no measurable change in that site's misprediction
    rate. Repeat across two guests with distinct `PDID`s, including a pair whose `ASID_TAG` values
    differ only above bit 7 — that pair is the specific regression against a truncated predictor tag.
21. **No speculative aperture access (§2.5 rule 6).** A mispredicted branch over a load from the
    aperture produces no bus request, no `EXPEVT = 0x1E0`, and leaves `HPAR`/`HMCR`/`HMDR` unchanged.
    Assert this in RTL, not only by directed test.
22. **Mode snapshot (§4.4.1a).** A guest memory access issued in the shadow of an unresolved `HRTE`
    resolves through the guest's TLB path, never through P1 folding.
23. **Per-context state (§2.9).** Two guests on two thread contexts of one core — a configuration
    §4.7 forbids in production but which must be *tested*, since the whole point is that hardware
    does not prevent it: each context's `HSPC`/`HSSR`/`HPAR`/`HMCR`/`HMDR`/`HEMUB`/`HEMUM`/`HEDR`
    and each context's store-queue buffers are unaffected by the other's traps and bursts.
24. **`HRTE` writeback under rename (§4.5 rule 2).** A trapped load to each of `R8`–`R15` resumes
    with the correct value when the destination register is also the target of an in-flight producer
    at the time of the trap. Verification point 12 covers the unbanked case; this covers the rename
    interaction, which is a different failure.

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
| `HPAR`, `HMDR` storage | 2 × word_size flops |
| `HMCR` storage (9 bits captured: SQ, DIR, SIZE, BANK, REGN) | 9 flops |
| `HSQCR` storage | 4 flops |
| Destination-register latch (REGN/BANK decode feeding writeback mux) | ~20 LUTs |
| `HRTE`-armed writeback port (complete-on-resume register write, §4.5) | ~60 LUTs |
| Two 32-byte SQ buffers with valid/dirty tracking | attributed to [../sq/spec.md](../sq/spec.md), not counted here (§10 note below) |
| `QACR` address-formation path reuse for aperture routing | ~15 LUTs |
| MMIO-trap control/sequencing (entry mux, EXPEVT/vector selection) | ~25 LUTs |
| Unrepresentable-access detection + fail-closed gating (§4.6) | ~10–15 LUTs |
| **Emulated-MMIO trap subtotal** | **~130–195 LUTs, ~15 flops** |
| **Total (per core), single-threaded implementation** | **approximately 300 LUTs, ~215 flops** |
| `PDID` register + predictor-tag width (§2.8) | ~6 flops, ~40 LUTs |
| Non-speculative region gating for P4 / aperture / uncacheable (§2.5 rule 6) | ~40 LUTs |
| Serialization and mode-snapshot logic (§4.4.1a) | ~50 LUTs |
| **Per additional thread context** (§2.9: the 12 per-vCPU registers + two 32 B SQ buffers + `QACR0/1`) | **~910 flops each** |
| **Total, 2-way FGMT (J32-OOO)** | **~430 LUTs, ~1,130 flops** |
| **Total, 4-way FGMT (J32-LT)** | **~430 LUTs, ~2,950 flops** |

The per-context rows are the honest cost of virtualizing a multi-threaded core and they dominate
everything else in this table. They are flops, not LUTs, so they land on FPGA registers rather than
logic; on the ECP5 that is the cheaper of the two resources, but at four contexts it is no longer a
rounding error. §2.9 explains why none of it is optional.

Arithmetic: 150 LUTs (existing Phase 3 baseline, row above) + 130–195 LUTs (emulated-MMIO trap,
this task) = 280–345 LUTs, stated conservatively as **approximately 300 LUTs** per core. The
~300 LUT headline is unchanged by §4.6's addition and remains the conservative statement: the new
row moves the midpoint from 300 to ~312, still inside the rounding the figure already carried. This is a
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

**§4.6 unrepresentable-access detection (~10–15 LUTs).** §4.6 makes the aperture trap fire only for
the representable set and fail closed for everything else. The representability predicate is a
plain OR over opcode-class signals the decoder **already produces** — it must already distinguish
the plain `MOV.{B,W,L}` load/store family in order to drive `HMCR.DIR`/`SIZE`/`REGN`/`BANK` at all,
and it already identifies `TAS.B`, the FPU/SIMD memory ops and `MAC.W`/`MAC.L` as distinct classes.
So the new logic is not a decoder; it is (a) the exception-source mux that steers an
aperture-matching access to the general illegal-instruction path instead of `EXPEVT = 0x1E0`, and
(b) the gating that holds off the bus request and the `HPAR`/`HMDR`/`HMCR` write enables on that
path. Both are a handful of gates on signals already in flight, hence the small figure.

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

To be explicit: Phase 3 adds nothing to the **TLB array or its lookup function**, nothing to the TSB structure, nothing to the IOMMU. It does add a translation-path *gate* in front of the lookup and a comparator behind it, both itemized in §10. Virtualization happens through:

- A privilege-mode bit (one flop)
- A trap-delegation register (32 flops)
- A separate vector base for hyperprivileged traps
- Two new instructions (HCALL, HRTE), plus eleven new hyperprivileged LDC/STC control-register encodings (§2.2), of which `PDID` (§2.8) is required only on implementations that speculate
- One change to LDTLB behavior in supervisor mode
- A guest-mode override on the `MMUCR.AT` translation gate (§4.4.1) — one extra term in front of the existing lookup, not a change to the lookup, and no change to the TLB entry format
- One aperture comparator on the post-translation physical address (§2.5, §4.5), plus the trap-entry capture registers and the `HRTE`-armed writeback port that go with it (§10: ~130–195 LUTs, ~15 flops, including §4.6 fail-closed gating)

What Phase 3 still explicitly does **not** add, and what distinguishes it from post-2006 designs: no VMID or hardware guest tag, no second-stage translation, no hardware page-table walker, no TLB entry-format change, no change to how a TLB hit resolves. Every guest translation is an ordinary Phase 1 TLB entry, installed by hypervisor software.

Earlier drafts of this section claimed Phase 3 added "nothing to the TLB hardware" full stop, and listed only the first five bullets. That was written before §4.4's forced-translation rule and §4.5's aperture existed; it is corrected here. §10 is the authority on what was added.

The rest is software. That remains the central virtue of the design: it sits atop Phase 1 and uses Phase 1's primitives (TLB, TSB, ASID, PageMask) **without modifying any of them** — which is a different and weaker claim than "without adding anything", and the correct one.

## 12. Future Extensions

If patent landscape changes and post-2006 primitives become viable, the design can grow:

- **VMID-tagged TLB:** No longer on the roadmap. The 8-bit field that earlier drafts reserved in Phase 1/2 tag layouts is **removed** project-wide ([glossary §5](../glossary.md)). Hardware-VMID would have eliminated software ASID partitioning, but its patent risk is high until ~2030 (Intel VPID patents post-2008), and the ASID-partitioning approach (pre-2006 sun4v prior art) is sufficient at the guest counts this platform targets.
- **Two-stage hardware translation (G-TLB):** Add a stage-2 cache that automatically substitutes HPN for RFN at LDTLB time. Eliminates the LDTLB trap. Patent risk: high until ~2030 (Intel EPT, AMD NPT patents).
- **Nested virtualization:** Software-only; no new hardware. Just adds a layer of HEDR delegation. Implementable in Phase 3 without ISA changes if desired.

None of these are blocked by Phase 3 — the design space is left open.

**Open item — does the instruction-fetch path need its own aperture comparator?** §10's aperture
comparator row (`(PA & HEMUM) == HEMUB`, ~15 LUTs) is described as "per access", which is ambiguous
about whether the **instruction-fetch** address is one of those accesses. §4.6 requires it to be:
"instruction fetch from inside the aperture" is listed as an unrepresentable access that must fail
closed, and §9 verification point 16 tests exactly that — which is only implementable if the
I-fetch physical address is compared against the aperture at all. If the implementation's single
comparator sits on the data-side post-translation address only, a second instance on the
instruction-fetch address is required, at roughly **another 15 LUTs** — a duplicate of the existing
comparator row, plus the small amount of gating to turn its match into the fetch-side illegal
path. Whether one comparator can be shared (the two paths may present their physical addresses in
different pipeline cycles, in which case sharing is possible; if they can be simultaneous it is
not) is a microarchitecture question this specification does not decide. **Flagged for the
implementer:** budget the second comparator until the pipeline analysis shows it can be shared, and
update §10 with the answer.

**Open item — TLB fault `EXPEVT` labelling.** §2.3.1's HEDR rows label bits 4–7 as
`0x040`/`0x060` "TLB miss read/write" and `0x0A0`/`0x0C0` "protection violation read/write", while
[../mmu/hardware-spec.md §5](../mmu/hardware-spec.md) — the authority on TLB fault delivery —
assigns `0x040`/`0x060`/`0x080` to I-fetch/load/store miss and `0x0A0` (I-fetch) / `0x0C0` (both
data directions) to protection violation, with the vector offset carrying the access-type
distinction. The two are reconcilable (an instruction-fetch miss is neither a "read" nor a "write"
in the data sense) but the wording is not aligned, and there is no HEDR bit named for `0x080`. This
predates §4.2's mirror rule and is unaffected by it — the mirror rule fixes vectors, not HEDR bit
assignment. Owner needed: reconcile §2.3.1's bit labels with mmu §5's cause codes, or state
explicitly that one HEDR bit gates both data directions.
