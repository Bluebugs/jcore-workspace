# J-Core Privileged Architecture Design Specification

**Status:** Draft
**Scope:** J3 / J32 / J64 — the supervisor/user mode, register banking, and SH-4-style exception model that sit *under* the MMU
**Audience:** Hardware architects, kernel developers
**Relationship:** Prerequisite for [mmu/design-spec.md](../mmu/design-spec.md). The MMU spec already assumes everything in this document (register banking for the miss handler, `SPC`/`SSR` exception entry, `RTE`-from-`SPC`/`SSR`). This spec makes that substrate explicit and gives it its own implementation story.

---

## 1. Why this document exists (the "third bucket")

Making a J-Core that an SH-4 (`-m4-nofpu`) Linux can boot was initially scoped as two pieces of work: the **MMU/TLB** ([mmu/](../mmu/)) and the **coherent L2 + cache-maintenance ISA** ([cache/l2-spec.md](../cache/l2-spec.md)). That scoping is incomplete. There is a third, core-CPU piece that neither of those covers: **the SH-4 privileged (system) architecture**.

J2 is an **SH-2-class** core. SH-2 has no concept of user vs. supervisor mode, no register banking, and a stack-based exception model. SH-3 introduced — and SH-4 inherited — privilege levels, banked registers, and a register-based exception model (`SPC`/`SSR`/`SGR`). SH-4 Linux depends on all of it. Adding it is genuine control-path and datapath work in the core, distinct from translation and from the cache.

This is not "extra credit" relative to the MMU — it is a **hard prerequisite**. The MMU miss handler in [mmu/hardware-spec.md §7](../mmu/hardware-spec.md) opens in bank 1 (`SR.RB=1`) with the faulting PC in `SPC` and the saved status in `SSR`, and returns through `LDTLB.R` (a fused `LDTLB`+`RTE` that restores `PC←SPC, SR←SSR`). None of those mechanisms exist in J2 today.

## 2. Current J2 state (verified against the RTL)

Evidence from `jcore-soc/components/cpu` confirms J2 implements the SH-2 system architecture and nothing more:

| Feature | J2 today | Evidence |
|---|---|---|
| Status register | `sr_t = { t, s, q, m, int_mask[3:0] }` — the **SH-2 SR**. No `MD`, `RB`, `BL`, `FD`. | `core/components_pkg.vhd:24`; packed by `to_slv(sr)` at `core/datapath.vhd:74` |
| User/supervisor mode | **None.** All code runs effectively privileged; there is no `MD` bit to gate privileged instructions or P1/P2/P4 access. | absence of `MD` in `sr_t` |
| Register banking | **None.** `register_file_two_bank` writes the *same* data to both banks (`bank_a(addr) <= data; bank_b(addr) <= data;`) — it is a dual-read-port duplication trick, not SH bank0/bank1. | `core/register_file_two_bank.vhd` |
| Exception save state | **None.** No `SPC`, `SSR`, or `SGR` registers exist anywhere in the CPU. | grep of `components/cpu` |
| Exception model | **SH-2 stack-based.** `TRAPA`: `PC/SR -> Stack area, (imm×4 + VBR) -> PC`. `RTE`: `stack -> PC/SR`. | `decode/decode_table_simple.vhd:4174` (TRAPA), `:180` (RTE) |
| Cause registers | **None.** No `EXPEVT`/`INTEVT`/`TRA`. Cause is encoded in the microcode system-event path (`BREAK/ERROR/GENERAL_ILLEGAL/INTERRUPT/RESET_CPU/SLOT_ILLEGAL`). | `decode/decode_pkg.vhd:289` |
| Control registers present | `SR` (SH-2), `VBR`, `GBR`, `PR`, `MACH`, `MACL`, `PC`. These are SH-2 common and already have `LDC`/`STC` encodings. | `decode/decode_body.vhd` (VBR LDC/STC) |

**Conclusion:** the third bucket is genuinely absent. What follows specifies it.

## 3. Goals

- Add a two-level privilege model (supervisor / user) compatible with the SH-4 `SR.MD` semantics and the P0–P4 segment privilege rules already assumed by [mmu/design-spec.md §3.7](../mmu/design-spec.md).
- Add SH-3/SH-4 register banking (`SR.RB`, banked R0–R7) so the exception fast paths inherit scratch registers at zero save/restore cost.
- Replace the SH-2 stack-based exception model with the SH-4 register-based model (`SPC`/`SSR`, optional `SGR`, `EXPEVT`/`INTEVT`, fixed VBR-relative vectors).
- Add the privileged control-transfer instructions the model needs (`LDC`/`STC` for `SSR`/`SPC`/`R*_BANK`; `RTE` semantics change) — the **Tier-1 "mmu-required"** subset of [../sh4-nonfpu.json](../sh4-nonfpu.json).
- Stay binary-compatible with SH-4 where Linux already speaks it, and stay implementable on the existing in-order J-Core pipeline (FPGA-friendly, ASIC-portable VHDL).
- Keep the addition independently bring-up-able and testable **without** the MMU (privilege + banking + exceptions can be exercised on flat memory).

**Non-goals (this document):** the FPU and `SR.FD` (we target `-m4-nofpu`; see §9), the MMU itself (separate spec), the cache-maintenance ISA (separate spec), and SH-DSP `RC`/`MOD`/repeat state.

## 4. Design choices

### 4.1 Adopt the SH-4 SR layout

`sr_t` extends from the SH-2 set to the SH-4 set. New fields and their canonical bit positions:

```
[31]      0     reserved
[30]      MD    processor mode: 1 = privileged, 0 = user
[29]      RB    register bank select (meaningful only when MD=1)
[28]      BL    exception/interrupt block (mask all but reset)
[27:16]   0     reserved (SH-DSP RC/repeat — not implemented)
[15]      FD    FPU disable (reserved/RAZ on -nofpu cores; see §9)
[14:10]   0     reserved
[9]       M
[8]       Q
[7:4]     IMASK  interrupt mask (J2's int_mask moves here if not already)
[3:2]     0     reserved
[1]       S
[0]       T
```

`to_sr`/`to_slv` in `core/datapath.vhd` grow to carry `MD`, `RB`, `BL`. Reset state is `MD=1, RB=1, BL=1, IMASK=0xF` (privileged, bank 1, exceptions blocked) — identical to SH-4 power-on and to the exception-entry state in §4.3.

**Rationale:** binary compatibility with the SH-4 Linux `arch/sh` `SR` bit conventions; the MMU's segment privilege rules ([mmu/design-spec.md §3.7](../mmu/design-spec.md)) are defined in terms of `MD`.

### 4.2 Real register banking

Replace the `register_file_two_bank` duplication with genuine SH banking: R0–R7 have a **bank 0** and **bank 1** copy; `SR.RB` (when `MD=1`) selects which is architecturally visible as R0–R7. R8–R15 are unbanked. On exception entry hardware forces `RB=1`; `RTE`/`LDTLB.R` restores the caller's `RB` from `SSR`.

The existing dual-read-port structure does not disappear — each bank still needs its two read ports — so the change is "two *distinct* banks, each dual-ported," roughly doubling the R0–R7 storage (8 × 32 b on J32) plus `RB`-muxing on the read/write address path.

**Rationale:** this is the SH-4 mechanism Linux and the TLB-miss hot path ([mmu/hardware-spec.md §6, §7](../mmu/hardware-spec.md)) rely on for zero-cost scratch — the J-Core equivalent of UltraSPARC alternate global registers. `LDC/STC R*_BANK` give software explicit cross-bank access for context save/restore.

**Why banking, when the mainstream abandoned it.** Heavy register banking is the one SH-4 choice on the *losing* side of history: ARMv8 dropped AArch32's per-mode banking and RISC-V never had it — both converged on a single scratch CSR (`mscratch`/`sscratch`) plus an explicit save (the MIPS `k0`/`k1` lineage; see [§10](#10-design-longevity-what-survived-to-today)). That convergence happened *because* those cores went hardware-page-table-walk and therefore **never run a software refill handler** — so free scratch buys them nothing. We deliberately kept the **software-loaded TLB** ([mmu/design-spec.md §3.1](../mmu/design-spec.md)), so the refill handler is real and runs on every miss, and zero-save scratch still pays. Banking and the software TLB are a matched pair (as they were for MIPS `k0/k1`, SPARC MMU-globals, and Alpha PALshadow); keeping one justifies keeping the other. This is a deliberate design-point choice, not inertia.

**One alternate bank is sufficient — keep `BL=1` across the hot path.** SH-4 provides a single alternate bank, shared between the TLB-miss path and the interrupt path, so an interrupt taken mid-miss would clobber the handler's scratch. We close that without a second bank by keeping `SR.BL=1` for the entire ~10-instruction miss hot path ([mmu/hardware-spec.md §7](../mmu/hardware-spec.md)): `BL` masks all but reset, so no interrupt can preempt the path and no nested clobber is possible. (SPARC solved the same problem with *separate* MMU vs. interrupt global sets; the `BL`-covered single bank is the cheaper equivalent and costs no extra regfile state.) A second MMU-private bank was considered and rejected as unnecessary given the bounded, `BL`-covered path.

### 4.3 SH-4 register-based exception model

Replace the SH-2 stack push/pop with:

**On exception/interrupt entry** (`BL=0`):
1. `SPC ← PC` (the restart PC; for multi-word/SIMD units, the first-word PC per [mmu/hardware-spec.md §5.1](../mmu/hardware-spec.md)).
2. `SSR ← SR`.
3. `SGR ← R15` (optional; see §4.4).
4. `EXPEVT` or `INTEVT ← cause code`.
5. `SR.MD ← 1, SR.RB ← 1, SR.BL ← 1`, and for interrupts `SR.IMASK ← level`.
6. `PC ← VBR + offset`, where the offset is the SH-4-style fixed vector (§4.5).

**On `RTE`:** `SR ← SSR; PC ← SPC` (one-instruction delay slot, as today). This replaces the SH-2 `stack -> PC/SR`. `LDTLB.R` ([mmu/hardware-spec.md §3.2](../mmu/hardware-spec.md)) is the MMU-fused variant.

`TRAPA #imm` changes from "push PC/SR to stack" to "`TRA ← imm<<2`; take a general exception via the register model." This is the one **behavioural break** from J2's current SH-2 semantics; no SH-2 binary that relies on stack-frame exceptions survives, but J-Core's own software stack is rebuilt for SH-4 anyway.

**Rationale:** the register model is what makes a software TLB-miss handler cheap and is required for SH-4 Linux. The stack model cannot host an MMU miss handler safely (the stack itself may be unmapped).

### 4.4 `SGR` is optional

`SGR` (saved R15) is provided for SH-4A binary compatibility but is **architecturally redundant** here: the miss/exception fast paths get their scratch from bank 1, not from an `SGR` shadow. Implementations may omit `SGR` (and `STC SGR,Rn`) to save a register and a decode slot; the Linux port must then not read it. Catalogued as **Tier-3 "orthogonal"** in [../sh4-nonfpu.json](../sh4-nonfpu.json).

**J4 omits `SGR`.** A prototype added `SGR` as a register-file slot with a read-only `STC SGR,Rn` (the read path works) and captured `SGR ← R15` during exception entry. The capture drives R15 onto the datapath bus while the entry microcode runs, and an in-flight memory cycle from the trapping context latched that value as a write address — a **spurious store to `@R15` on every exception entry**, silent only when the stack pointer is aligned (so it hid behind every aligned-SP test). The hazard reproduced with both a folded capture (sharing the cause-capture slot) and a dedicated capture slot, so it is intrinsic to reading a GPR onto the bus during entry, not an artifact of slot layout; a correct capture would need datapath work to suppress the entry-time memory cycle. Given `SGR`'s redundancy, J4 drops it: `STC SGR,Rn` remains an illegal-instruction trap and the toolchain targets SH-4 (not SH-4A), so the register is never read.

### 4.5 Exception vectors

Adopt SH-4 fixed VBR-relative offsets, aligned with the values the MMU spec already uses:

| Event | Vector | Note |
|---|---|---|
| Power-on reset | `0xA0000000` (P2, fixed) | `VBR` reset = 0 |
| General exception | `VBR + 0x100` | illegal insn, `TRAPA`, address error |
| TLB miss (I-fetch / load / store) | `VBR + 0x400 / 0x420 / 0x440` | per [mmu/hardware-spec.md §5](../mmu/hardware-spec.md) |
| Interrupt | `VBR + 0x600` | level in `INTEVT` |

A core built **without** the MMU still uses this vector layout; the `0x400` family simply never fires until translation is enabled.

### 4.6 Cause registers and the MMIO-map collision

`EXPEVT`, `INTEVT`, and `TRA` are added as P4 MMIO (and readable via the CCN path Linux expects). **Open coordination item:** SH-4 places these at `0xFF000020` (`TRA`), `0xFF000024` (`EXPEVT`), `0xFF000028` (`INTEVT`) — but j-core has already assigned `0xFF000020 = CPUINFO` and `0xFF000024 = ASIDR` ([soc/p4-mmio-map.md §3.2](../soc/p4-mmio-map.md)). Proposed resolution: place `EXPEVT/INTEVT/TRA` at the next free offsets (`0xFF000028/2C/30`) and record the divergence in the P4 map so the Linux port reads the relocated addresses. This is a map-allocation decision, not an architectural one, and is deferred to the P4-map owner.

### 4.7 Single-level save state constrains the VM design (TSB in P1)

SH-4 saves exactly **one** level of `SPC`/`SSR` — there is no hardware trap-level stack (SPARC's `TL`, the one era-feature that gave nested traps for free, did *not* survive to RISC-V/ARMv8 either; see [§10](#10-design-longevity-what-survived-to-today)). The consequence for the VM design is concrete: **the TLB-miss handler must never itself fault**, or it overwrites the `SPC`/`SSR` of the original fault and the restart is lost.

The miss handler's own memory accesses are: the `TSBPTR`-relative load of the candidate TTE, and (on TSB miss) the page-table walk. If any of those addresses were *translated* (P0/P3), they could themselves miss the TLB → recursive fault → corruption. Therefore:

> **The per-CPU TSB and the kernel page tables MUST live in the untranslated direct map (P1).** With `PA = VA & 0x1FFFFFFF`, a miss-handler load can never trigger a second translation, so a single level of `SPC`/`SSR` is provably sufficient and `LDTLB.R` returns cleanly to the original fault.

This refines [mmu/design-spec.md §4.3](../mmu/design-spec.md) ("TSB lives in normal cacheable memory"): it must be normal cacheable memory *in P1*. P1 is cached (so the TSB still benefits from L1/L2), just untranslated. The cost is that the TSB and page tables consume lowmem (the P1 window), which is the same constraint classic SH-4 and MIPS (`kseg0`) kernels already live with. The alternative — letting the handler save/restore `SPC`/`SSR` to tolerate one nested miss — was considered and rejected: it adds cost to every miss to buy placement flexibility we do not need.

This is the cleanest illustration of the bucket-3 ↔ MMU coupling: a privileged-architecture choice (one save level, inherited from SH-4 and vindicated by RISC-V/ARMv8) directly fixes a memory-layout rule in the VM design.

## 5. Instruction additions

The privileged-architecture subset of the J2→SH-4 gap (full list and tiers in [../sh4-nonfpu.json](../sh4-nonfpu.json), and encodings in [mmu/hardware-spec.md §3.0](../mmu/hardware-spec.md)):

**Required (Tier-1):**
- `LDC Rm,SSR` / `STC SSR,Rn` (+`.l`)
- `LDC Rm,SPC` / `STC SPC,Rn` (+`.l`)
- `LDC Rm,Rn_BANK` / `STC Rm_BANK,Rn` (+`.l`)
- `RTE` — semantics change (restore from `SPC`/`SSR`)
- `LDTLB` / `LDTLB.R` — owned by the MMU spec, listed here for completeness

**Optional / droppable (Tier-3):** `STC SGR,Rn` (+`.l`), `LDC/STC DBR` (debug base, unrelated to privilege), `CLRS`/`SETS` (MAC saturation S-bit).

All `SSR`/`SPC`/`R*_BANK` accesses are **privileged** (illegal-instruction trap when `SR.MD=0`). `VBR`/`GBR`/`SR` `LDC`/`STC` already exist in J2 and gain the privilege check. These reuse the existing `0100 mmmm xxxx 1110` / `0000 nnnn xxxx 0010` decode family, so the decode machinery is incremental (see [decoder cost note](../mmu/hardware-spec.md)).

## 6. Memory-isolation interaction

This spec provides the **privilege half** of the isolation guarantees in [mmu/design-spec.md §6](../mmu/design-spec.md): `SR.MD` gates the privileged segments (P1/P2/P3/P4) and privileged instructions; the per-page `U` bit and ASID tagging (MMU's half) gate user access to translated pages. With this spec but without the MMU, a core has supervisor/user separation and privileged-instruction protection but no per-process address-space isolation — useful for bring-up and for fixed-map RTOS configurations.

## 7. Implementation story (milestones)

Each milestone is independently testable. PM0–PM2 have **no MMU dependency** and can land first; the MMU work ([mmu/](../mmu/)) consumes PM0–PM3 as its substrate.

- **PM0 — SR + privilege mode.** Extend `sr_t` with `MD`/`RB`/`BL`; thread `MD` into instruction decode (privileged-instruction trap) and into the segment decoder (P1/P2/P4 require `MD=1`). No banking yet (`RB` inert). *Test:* user-mode program traps on `LDC Rm,VBR`; supervisor program does not.
- **PM1 — Register banking.** Real bank0/bank1 R0–R7 switched by `SR.RB`; add `LDC/STC R*_BANK`. *Test:* writes to bank-1 R0–R7 invisible from bank 0 and vice-versa; `STC Rm_BANK,Rn` reads the other bank.
- **PM2 — Exception model.** Add `SPC`/`SSR`/`EXPEVT`/`INTEVT`; convert entry to `PC→SPC, SR→SSR, set MD/RB/BL, VBR+offset`; convert `RTE` to restore-from-`SPC`/`SSR`; re-point `TRAPA` and the illegal/interrupt paths. *Test:* take an illegal-instruction exception in user mode, observe `SSR`/`SPC`/`EXPEVT`, return via `RTE` to the faulting context in the right bank/mode.
- **PM3 — Vectors + cause-register MMIO.** Wire the SH-4 fixed vector offsets and expose `EXPEVT`/`INTEVT`/`TRA` at the agreed P4 addresses (§4.6). *Test:* the SH-4 vector offsets fire the correct handlers; Linux `arch/sh` early trap setup runs.
- **PM4 — `SGR` (optional).** Add `SGR ← R15` on entry and `STC SGR,Rn` only if SH-4A binary compat is wanted.
- **PM5 — Linux bring-up gate.** With PM0–PM3 (+ the MMU milestones), boot an SH-4 `-m4-nofpu` kernel to user space. Shared gate with [mmu/](../mmu/) and the [ULX3S SoC roadmap](../ulx3s-soc-component-inventory.md).

**Dependency summary:** PM0 → PM1 → PM2 → PM3 are linear; the MMU's `LDTLB`/`LDTLB.R` and miss-handler hot path require PM1 (banking) + PM2 (SPC/SSR) before they are meaningful. The cache-maintenance ISA ([cache/l2-spec.md §17.5](../cache/l2-spec.md)) is independent of this spec.

## 8. Hardware-cost sketch

| Addition | Storage / logic |
|---|---|
| `SR` widening (`MD`/`RB`/`BL`) | 3 flops + decode of new bits |
| Banked R0–R7 | +8×32 b (J32) / +8×64 b (J64) regfile state + `RB` mux on R0–R7 port addressing |
| `SPC`/`SSR`/`SGR` | 3 × word-size registers |
| `EXPEVT`/`INTEVT`/`TRA` | 3 small MMIO registers + cause-encode mux |
| Privilege check | combinational: `MD` vs. instruction-privileged flag and vs. segment |
| Exception sequencer rework | microcode/decode-table changes (no new datapath width) |

All FPGA-friendly; the banked regfile is the only non-trivial storage bump. No change to ALU width or the multiplier.

## 9. FPU / `-m4-nofpu`

We target GCC's `-m4-nofpu`. `SR.FD` (FPU-disable) is therefore **reserved/RAZ**: a core with no FPU need not implement the FPU-disabled-exception path, and the kernel is built without FP. If the optional J-Core FPU ([fpu/spec.md](../fpu/spec.md)) is later added, `FD` and its trap activate then; nothing in PM0–PM5 forecloses it.

## 10. Design longevity (what survived to today)

The design rule for J-Core has been: *keep the SH-4 interface where Linux already speaks it, borrow better internals from the era's other architectures where SH-4's choices leak or have aged.* The MMU spec applied this to translation (software TLB from MIPS/SPARC/Alpha, TSB assist from UltraSPARC, ASID-generation from Alpha, the ASIDR split from UltraSPARC `PRIMARY_CONTEXT`). For the **privileged architecture** the same audit yields a happier result than for the MMU: most of SH-4's exception model *is* the pattern that survived, so we deviate less. Using RISC-V (`s`-mode, ~2011) and ARMv8 (2011) as the "today" yardstick:

| Era choice | Who had it | Survived to RISC-V / ARMv8? | J-Core decision |
|---|---|---|---|
| Register-save exception model (`xPC`/`xSR`/cause/fault-addr) | SH-4 `SPC`/`SSR`/`EXPEVT`/`TEA`; PPC `SRR0/1`; MIPS `EPC` | **Yes, universal** — `sepc/sstatus/scause/stval`; `ELR/SPSR/ESR/FAR` | **Keep SH-4 as-is** (§4.3) — it is the survivor |
| Separate ASID / context register | UltraSPARC `PRIMARY_CONTEXT`; Alpha `ASN`; MIPS `EntryHi.ASID` | **Yes** — `satp.ASID`; `CONTEXTIDR` | Already taken (MMU `ASIDR`); SH-4's "ASID-in-PTEH" *not* copied |
| Heavy GP register banking | SH-4 (1 bank); ARMv4–v7 (per-mode) | **No** — both moved to one scratch CSR + save | **Keep, but justified by the software TLB** (§4.2), not nostalgia |
| HW trap-level stack (nested traps free) | SPARC v9 `TL` | **No** — single-level save + software stack won | **Don't implement**; single `SPC`/`SSR` → drives TSB-in-P1 (§4.7) |
| SPARC register windows | SPARC v8/v9 | **No** — flat register files won | Never considered |
| Multiple trap-class global sets | SPARC v9 AG/MG/IG | **No** (as hardware) | Approximated cheaply by `BL`-covered fast path (§4.2) |
| Firmware privilege layer (PALcode) | Alpha | **Spirit yes** — RISC-V SBI, ARM PSCI | Out of scope here; relevant to boot/hypervisor story |
| Hardwired untranslated kernel segment | SH P1/P2; MIPS `kseg0/1` | **Spirit yes** (everyone has a kernel direct map) | **Keep P1** — hardwired map is a deliberate FPGA bring-up advantage (§4.7, [mmu §3.7](../mmu/design-spec.md)) |
| Software-loaded TLB | MIPS, SPARC, Alpha | **Minority** — mainstream went HW-walk (Sv39/48, ARMv8) | **Deliberately kept** (gate budget + ISA-stable 32→64); the reason banking still pays |
| Fixed cause register | SH-4 `EXPEVT`; MIPS `Cause` | **Yes** — `scause`/`ESR` | Keep |

**Reading of the table.** SH-4's *exception interface* (save-register model, fixed cause register, untranslated kernel segment) landed on the right side of history and needs no deviation. The two era-features that "lost" — heavy banking and the deep trap-level stack — are exactly the two we are most tempted to question. We keep banking anyway, but only because we are on the *other* minority-survivor branch (software TLB), where the two reinforce each other; and we decline the trap-level stack, accepting its single-level consequence as a VM-layout constraint (TSB in P1) rather than hardware. The net is a privileged architecture that is SH-4-compatible at the interface, internally consistent with the MMU's "1997 software-managed" design point, and free of the era's two dead-ends.

## 11. Out of scope

- The MMU/TLB itself — [mmu/design-spec.md](../mmu/design-spec.md) (this spec is its prerequisite).
- Cache-maintenance instructions and coherent L2 — [cache/l2-spec.md](../cache/l2-spec.md).
- FPU and `SR.FD` trap — [fpu/spec.md](../fpu/spec.md).
- Hypervisor / `MD`-above-supervisor — [hypervisor/design-spec.md](../hypervisor/design-spec.md); guest isolation there is via ASID partitioning, not a new privilege ring.
- SH-DSP repeat-control (`RC`/`MOD`/`RS`/`RE`) and `SETRC` — not part of the `-m4` target.
- Final P4 MMIO addresses for `EXPEVT`/`INTEVT`/`TRA` — deferred to [soc/p4-mmio-map.md](../soc/p4-mmio-map.md) (§4.6).

## 12. References

- Hitachi/Renesas SH-4 Programming Manual, 1998 (SR layout, exception model, banking).
- Hitachi SH-2 Programming Manual (the stack-based model J2 implements today).
- UltraSPARC I/II User's Manual, 1997 (alternate global registers, MMU globals, `TL` — the banking analogue).
- MIPS R4000 User's Manual, 1991 (`k0`/`k1`, `Context`, dedicated TLB-refill vector).
- DEC Alpha Architecture Reference Manual (PALcode, PALshadow, `ASN`).
- RISC-V Privileged Architecture spec and ARMv8-A ARM (the "today" yardstick: `sscratch`/`sepc`/`scause`, `ELR`/`SPSR`/`ESR`).
- Linux kernel `arch/sh/` (SR conventions, `EXPEVT`/`INTEVT` usage, trap entry).
- J-Core RTL: `jcore-soc/components/cpu/core/{components_pkg,datapath,register_file_two_bank}.vhd`, `.../decode/`.
- Companion catalog: [docs/sh4-nonfpu.json](../sh4-nonfpu.json); decoder encodings: [mmu/hardware-spec.md §3.0](../mmu/hardware-spec.md).
