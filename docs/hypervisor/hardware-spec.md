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
- LDTLB/LDTLB.R behavior in guest mode
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
[13:10]  reserved (read-as-zero, write-ignored)
[9]      M               existing SH-4 (DIV0 / DIV1 mantissa carry)
[8]      Q               existing SH-4 (DIV0 / DIV1 quotient)
[7:4]    IMASK[3:0]      interrupt mask (existing SH-4)
[3:2]    reserved (read-as-zero, write-ignored)
[1]      S               existing SH-4 (MAC saturation enable)
[0]      T               existing SH-4 (condition flag)
```

**Reconciliation note.** Earlier drafts of this spec placed MD at bit 15 (collides with SH-4 FD) and HPRIV at bit 9 (collides with SH-4 M). Both were errors. Bit positions for MD, RB, BL, FD, M, Q, IMASK, S, T match the SH-4 hardware manual verbatim; HPRIV occupies SH-4-reserved bit 14. The FPU spec ([../fpu/spec.md §6.3](../fpu/spec.md)) places SR.FD at bit 15 per SH-4 and is consistent with this layout.

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
```

This carves a new control-register family with capacity for up to 16 hyperprivileged control registers (slots 0–15). All accesses in this family trap with illegal-instruction exception if executed with `SR.HPRIV=0`, enforcing that only hyperprivileged code can read or write these registers.

The choice of low nibble `0xF` avoids collision with SH-4's existing `0xE` (LDC/STC) and `0xB`/`0xA`/`0x7`/`0x3` (LDC.L/STC.L variants) low nibbles in the 0100 family.

### 2.3 HEDR — Hypervisor Exception Delegation Register

```
[31:0]  Bitmap: bit N = 1 -> delegate exception cause N to supervisor (guest).
                bit N = 0 -> deliver exception cause N to hyperprivileged (host).
```

HEDR has 32 bits, each corresponding to an exception cause. The cause-to-bit mapping is fixed by hardware and given in §2.3.1; software cannot remap.

**Default after reset:** all bits 0 (all exceptions go to hyperprivileged). The hypervisor explicitly sets bits to delegate to the guest. A non-virtualized kernel never sets HPRIV, so HEDR is never consulted — backward compatibility is preserved.

**Always-to-hypervisor causes** (§4.2): bits 0 (HCALL) and 1 (guest LDTLB trap) are hard-wired to read-as-zero; software writes to these bits have no effect. These traps cannot be delegated to a guest because they exist solely to communicate with the hypervisor.

#### 2.3.1 EXPEVT-to-HEDR-bit mapping (normative)

The mapping is dense from the low bits up so a typical hypervisor configuration looks like a small bitmask. SH-4-inherited EXPEVT values are grouped by class; J-Core hyperprivileged-extension causes (`0x180`+) follow.

| HEDR bit | EXPEVT     | Cause                                                    | Delegatable? |
|---------:|------------|----------------------------------------------------------|:------------:|
|    0     | `0x180`    | HCALL instruction                                        | **no**       |
|    1     | `0x190`    | Guest LDTLB / LDTLB.R trap                               | **no**       |
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
|   24–31  | —          | reserved (future causes)                                 | yes          |

Notes:
- "Delegatable?" = whether the bit accepts software writes. Hardware ignores writes to non-delegatable bits, which always read 0.
- Two EXPEVT values appear twice in the table (`0x180` and `0x1A0`) because they overload between the hyperprivileged extension cause (HCALL / hyp-register-from-non-HS) and the pre-existing SH-4 supervisor cause (illegal-instruction). Hardware distinguishes by context: when raised by HCALL or by a hyperprivileged-register access, the cause is non-delegatable (bits 0 and 2); when raised by an ordinary illegal-instruction, the cause is delegatable (bits 12 and 13).
- The mapping is **stable**: future hardware revisions may add causes in bits 24–31 but MUST NOT reassign bits 0–23.

This table resolves the open question raised in [../fpu/spec.md §10 #3](../fpu/spec.md): `EXC_FPU_DISABLED` occupies HEDR bit 3 and is delegatable.

### 2.4 No changes to existing registers

PTEH, PTEL, TSBBR, TSBCFG, TSBPTR, MMUCR, VBR, SPC, SSR, GBR, R0-R15 all behave exactly as in Phase 1. The TLB and TSB structures are unchanged.

## 3. New Instructions

### 3.1 HCALL — Hypervisor Call

Encoding: `0000 0000 0111 1000` = `0x0078`

Allocated in the `0000 0000 nnnn 1000` family alongside LDTLB (`0x38`), CLRS (`0x48`), SETS (`0x58`), LDTLB.R (`0x68`). The slot at `0x78` was previously unallocated.

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

### 3.3 LDTLB and LDTLB.R in supervisor mode

**Behavior change:** When `SR.HPRIV = 0` and `SR.MD = 1` (supervisor mode), executing LDTLB or LDTLB.R **traps to the hyperprivileged trap vector** at `VBR_HYP + 0x300`.

The trap saves:
- PC of the LDTLB/LDTLB.R → HSPC
- SR → HSSR
- EXPEVT = 0x190 (new: guest TLB write trap)

The hypervisor's handler reads PTEH (the guest's intended VPN), ASIDR (the guest's current ASID_TAG, set at guest context switch), and PTEL (the guest's intended RFN + flags), performs RA-to-HPA translation, executes its own LDTLB (which doesn't trap because HPRIV=1), and HRTE's back to the guest.

**For non-virtualized kernels:** SR.HPRIV is never set, and the trap delegation is irrelevant. LDTLB executes normally. Phase 1 binary compatibility is preserved.

### 3.4 Privileged register access from supervisor mode

When `SR.HPRIV = 0`, attempting to access hyperprivileged registers (HSPC, HSSR, VBR_HYP, HEDR) raises an illegal-instruction trap (EXPEVT = 0x180 — but routed via the HEDR rules; by default, this trap goes to the hypervisor).

This is the mechanism by which the hypervisor catches a guest that tries to manipulate its own hyperprivileged state.

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

These are the exceptions where delegation makes no sense.

### 4.2 Vector layout

Hyperprivileged vector base at VBR_HYP, with the same offset conventions as VBR but specific to hyp-mode handlers:

```
Offset    Handler
------    --------------------------------------------------------
0x100     HCALL handler (HCALL from any mode)
0x190     Guest LDTLB trap handler
0x300     Privileged-instruction trap (for sensitive instructions)
0x400     Hyperprivileged TLB miss (HS-mode address translation fault)
0x500     External interrupt (when virtualization is active)
0x600     Inter-processor interrupts targeting HS-mode
```

(Offsets are illustrative; actual values follow the SH-4 vector conventions or are chosen by the implementer.)

### 4.3 EXPEVT values

The hyperprivileged-mode extension adds four new EXPEVT codes on top of the existing SH-4 set. The full per-cause delegation routing — including which bit of HEDR controls each cause — is specified normatively in [§2.3.1](#231-expevt-to-hedr-bit-mapping-normative). Summary of the new codes:

| Code  | Cause                                                          | HEDR bit | Delegatable? |
|-------|----------------------------------------------------------------|---------:|:------------:|
| 0x180 | HCALL instruction (new)                                        | 0        | no           |
| 0x190 | Guest LDTLB/LDTLB.R trap (new)                                 | 1        | no           |
| 0x1A0 | Hyperprivileged register access from non-HS mode (new)         | 2        | no           |
| 0x1B0 | `EXC_FPU_DISABLED` — SR.FD trap (Tier 2 FPU, new)              | 3        | yes          |

Existing SH-4 EXPEVT codes (`0x040`–`0x130`, `0x500`–`0x740`) retain their meanings; their HEDR-bit assignments are in §2.3.1.

**`EXC_FPU_DISABLED` (0x1B0).** Raised when an FPU instruction is decoded with `SR.FD = 1` on a CPU that ships a Tier 2 (hypervisor-aware) FPU. The cause is subject to HEDR delegation: when `HEDR[bit-for-0x1B0] = 0` (the default) the trap is taken by the hypervisor, which uses it to implement the lazy FPU context-switch ABI (per-vCPU FPU-ownership flag, save/restore of the 132-byte FPU image, re-enable of `SR.FD = 0` in the guest's `HSSR` shadow before `HRTE`). When the bit is set, the trap is delegated to the guest's own supervisor handler (a guest OS that wants to manage its own lazy-FPU model for user threads sets the bit). The full trap-handler ABI, save/restore sequence, and migration corner cases are specified in [../fpu/spec.md §7](../fpu/spec.md).

## 5. Hyperprivileged-Only Instructions and Operations

Operations that are valid only when SR.HPRIV=1:

1. **LDC/STC to hyperprivileged control registers** (HSPC, HSSR, VBR_HYP, HEDR).
2. **HRTE** — Return from hyperprivileged exception.
3. **LDTLB / LDTLB.R** without trapping (in supervisor mode, these trap; in hyperprivileged mode, they execute).
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
| Total | **~150 LUTs, ~200 flops per core** |

For comparison, Phase 1 added ~600 LUTs to the baseline J-Core CPU. Phase 3 is a 25% addition to Phase 1's footprint. The entire CPU with MMU and hypervisor support is still well within the gate budget of mid-range FPGAs.

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
