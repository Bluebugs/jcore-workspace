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

Add one bit to SR at position `[9]` (currently reserved/unused in Phase 1):

```
SR bit layout after Phase 3:
[31:30]  MQ
...
[15]     MD              mode (existing)
[14]     RB              register bank (existing)
[13]     BL              block exceptions (existing)
...
[9]      HPRIV           hyperprivileged mode (NEW)
[8]      V               reserved (was V in earlier draft; not used)
[7:4]    IMASK
[3:0]    T, S, M, Q
```

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
[31:0]  Bitmap: bit N = 1 -> delegate exception N to supervisor.
                bit N = 0 -> deliver exception N to hyperprivileged.
```

The 32 exception types correspond to the existing SH-4 EXPEVT values, with 32 the practical maximum (J-Core uses well under that today).

**Default after reset:** all bits 0 (all exceptions go to hyperprivileged). The hypervisor explicitly sets bits to delegate to the guest. A non-virtualized kernel never sets HPRIV, so HEDR is never consulted — backward compatibility is preserved.

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

The hypervisor's handler reads PTEH (the guest's intended VPN/ASID) and PTEL (the guest's intended RFN + flags), performs RA-to-HPA translation, executes its own LDTLB (which doesn't trap because HPRIV=1), and HRTE's back to the guest.

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

| Code | Cause |
|------|-------|
| 0x040 - 0x130 | Existing SH-4 EXPEVT values (TLB miss, interrupt, etc.) |
| 0x180 | HCALL instruction (new) |
| 0x190 | Guest LDTLB/LDTLB.R trap (new) |
| 0x1A0 | Hyperprivileged register access from non-HS mode (new) |

Existing exception codes retain their meanings. Bit 7+ of EXPEVT now indicates "this is a hyperprivileged-mode-specific cause."

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

- **VMID-tagged TLB:** Activate the reserved VMID field in Phase 1 spec. Hardware would need to compare VMID alongside ASID. Eliminates the need for hypervisor-allocated ASID partitioning. Patent risk: high until ~2030 (Intel VPID patents).
- **Two-stage hardware translation (G-TLB):** Add a stage-2 cache that automatically substitutes HPN for RFN at LDTLB time. Eliminates the LDTLB trap. Patent risk: high until ~2030 (Intel EPT, AMD NPT patents).
- **Nested virtualization:** Software-only; no new hardware. Just adds a layer of HEDR delegation. Implementable in Phase 3 without ISA changes if desired.

None of these are blocked by Phase 3 — the design space is left open.
