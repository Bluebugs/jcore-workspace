# J-Core SIMD Extension — Architectural Specification

**Status:** Consolidated draft (replaces v0.5, v0.6, and the VCLMUL design spec on 2026-05-25).
**Audience:** Architecture review, RTL implementers, toolchain and library authors.
**Companion documents:** [hardware-impl.md](hardware-impl.md), [software-impl.md](software-impl.md).
**Glossary:** see [../glossary.md](../glossary.md) for product names (J2, J32, J32-OOO, J32-FM, J64), threading terminology (FGMT), prior-art policy, and the J-Core "Tier 0/1/1.5" service-tier vocabulary (which is *not* the SIMD tier numbering below — service tiers and SIMD tiers are independent axes).

---

## 1. Overview

This document is the single source of truth for the J-Core SIMD instruction-set architecture. It supersedes the previous five SIMD documents in [archive/](archive/). All SIMD-related architectural decisions and instruction encodings reside here; hardware-implementation guidance lives in [hardware-impl.md](hardware-impl.md) and toolchain / kernel / library guidance lives in [software-impl.md](software-impl.md).

### 1.1 Tier structure

The SIMD ISA is organised in four tiers. Each tier is additive on the previous and gated by an implementation-defined feature bit (see §16). Every instruction in this specification carries a tier tag (T0, T1, T2, T3).

- **Tier 0 — Core 128-bit SIMD** (formerly spec v0.5). Dedicated V0..V15 register file, SIMDV/SIMDH prefixes, swizzle, vertical and horizontal modes, governed SH-2 integer and SH-4 FPU operations, vector load/store/gather/scatter, exception model, P0 predicate, VCSR control register. **Mandatory** baseline for any J-Core product that implements SIMD.
- **Tier 1 — Integer/saturation extensions** (formerly spec v0.6). SIMDV `rrr` saturation field (SIMDVS, SIMDVU), VABS, VPOPCNT, VUNPK4 family, VABSDIFF, VPACK family, VMULSU. Strictly additive on Tier 0. **Optional but recommended** for INT8/INT4 quantized inference, video/SAD, bioinformatics, database analytics, signal processing. Tier 0 binaries execute unchanged on a Tier 0+1 implementation.
- **Tier 2 — GF(2) crypto extensions** (formerly vclmul-design-spec). VCLMUL.D and VCRC32C.B. Strictly additive on Tier 0; **does not depend on Tier 1**. Optional; targets CRC32C, AES-GCM (GHASH), RAID-6, Reed-Solomon FEC, HQC post-quantum, gzip/zlib CRC folding. Tier 0 binaries execute unchanged on a Tier 0+2 implementation.
- **Tier 3 — Wide (256-bit) variant for J64** (architecturally reserved, not specified). Reserved for J64 implementations that want 256-bit V registers. The architectural reservation says: any future 256-bit register-width extension is **Tier 3** and is the *only* place a 256-bit SIMD facility may live. Tiers 0/1/2 are exclusively 128-bit (see §1.2). Tier 3 has no instructions defined in this revision.

J-Core product points and their tier coverage are listed in [../glossary.md §3](../glossary.md):

| Product   | SIMD tiers |
|-----------|------------|
| J2, J2-MT2x2, J3 | none |
| J32        | Tier 0+1 |
| J32-OOO    | Tier 0+1 |
| J32-FM     | Tier 0+1+2 |
| J64        | Tier 0+1+2+3 (Tier 3 yet to be specified) |

### 1.2 Register-width discipline (mandatory 128-bit)

**Tier 0/1/2 are 128-bit SIMD.** Vector width is fixed at 128 bits across the V register file, all governed instructions, all memory-access addressing, and all reduction destinations. This matches the Intel SSE / PowerPC AltiVec width established in 1996–1999.

The earlier VCLMUL design spec (now archived) mentioned "256-bit performance tier on J64". That language was inconsistent with Tier 0/1/2; this revision reconciles by stating that **any 256-bit register-width variant is Tier 3 and J64-only**, and is *not* part of Tier 0/1/2. Tier-2 (VCLMUL.D, VCRC32C.B) is specified strictly against 128-bit V registers on J32-FM and J64 alike. A future Tier 3 revision will revisit whether Tier 0/1/2 instructions promote transparently or whether Tier 3 adds new opcodes.

### 1.3 Design goals (Tier 0)

1. **Real SIMD ISA, not a DSP extension.** Tier 0 positions J-Core SIMD for applications-class workloads — autovectorisation targets, video/audio processing, light ML inference. The dedicated register file is the principal cost.
2. **Preserve SH-2 code density.** All new instructions remain 16 bits. The prefix is amortised across up to 4 governed instructions.
3. **Bounded pipeline complexity.** Single-issue in-order implementations require one new decode-stage shadow latch. SIMD prefix state is not saved on exception (atomic blocks, §6.1); the V0..V15 register file, P0, and VCSR are architectural and saved per normal context-switch rules.
4. **Reuse the existing ALU and FPU datapath** for SIMD compute. Only the register file is new.
5. **Forward compatibility.** Reserved opcode space inside SIMD blocks provides ample budget for Tier 1, Tier 2, and beyond.

### 1.4 Non-goals

- Out-of-order execution friendliness for the prefix-modal mechanism in its raw form. J32-OOO ([../ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md)) cracks the prefix and its governed group into a single internal micro-operation at decode time. The architecture is binary-compatible across in-order and OoO implementations.
- Variable-length vectors.
- Multiple predicate registers. Tier 0 specifies a single P0 register.
- Native FP8 / FP4 / bfloat16. See Appendix F.

---

## 2. Architectural Model (Tier 0)

### 2.1 SIMD register file

The SIMD register file is **dedicated**: 16 architectural registers V0..V15, each 128 bits wide, physically separate from the SH-4 scalar FPU register file (FR0..FR15 and XF0..XF15). Total new architectural state: **2048 bits**.

```
V0  (128 bits)    V1  (128 bits)    V2  (128 bits)    V3  (128 bits)
V4  (128 bits)    V5  (128 bits)    V6  (128 bits)    V7  (128 bits)
V8  (128 bits)    V9  (128 bits)    V10 (128 bits)    V11 (128 bits)
V12 (128 bits)    V13 (128 bits)    V14 (128 bits)    V15 (128 bits)
```

V0..V15 are named in SIMD context by reinterpreting the SH instruction's 4-bit register field (`nnnn` or `mmmm`) as a direct vector index 0..15. There is no multiple-of-4 constraint, and `FPSCR.FR` has no effect on SIMD register naming.

V0..V15 are saved and restored on context switch by the operating system, using the dedicated vector load/store instructions VLD.Q and VST.Q (§5.6). The OS-visible context grows by 256 bytes per thread for the V file (16 × 16 bytes), plus 4 bytes for P0, 4 bytes for VCSR, and 8 bytes for VFPUL — total **272 bytes** per task. **Save and restore are lazy when SR.VD is supported (§2.6)** — the OS sets SR.VD=1 on context-out and lets the SIMD-disabled trap drive the actual save/restore on first use, eliminating the 272-byte cost for tasks that never touch SIMD.

**VFPUL — SIMD-side scalar FP register.** A dedicated **64-bit architectural register**, **VFPUL** (Vector FP scalar register), holds the scalar FP result of any SIMD operation that produces an FP scalar. It exists so that no SIMD instruction ever writes the scalar FPU register file (FR / DR / FPUL) directly; this keeps SIMD blocks atomic with respect to SR.FD (§2.6) and avoids the silent-corruption hazard that would otherwise exist when SIMD reductions mutate FPU state owned by a different lazily-saved task. VFPUL is part of SIMD architectural state, saved and restored alongside V0..V15 / P0 / VCSR under SR.VD lazy save. The full reduction destination table is in §2.3; FP lane-bridge operations route through VFPUL per §5.7; cross-file moves between VFPUL and FR/DR happen only at the four boundary instructions specified in §5.8.

**Relationship to scalar FPU.** FR0..FR15 (front bank) and XF0..XF15 (back bank) remain scalar FPU registers, unchanged from SH-4. They are used by ordinary SH-4 FPU instructions when those instructions appear *outside* a SIMD block. SH-4 FIPR and FTRV continue to operate on quartets of FR registers as 4-element FP32 vectors — they are a separate, legacy 4-element vector facility orthogonal to the Tier 0 SIMD ISA. SIMD and the scalar FPU are otherwise **register-file-disjoint**: no SIMD instruction reads or writes FR/DR/FPUL/FPSCR. The four boundary instructions in §5.8 (`FMOV.VS`, `FMOV.VD`, both directions) are the only path between VFPUL and the scalar FPU file, and they execute outside any SIMD block. See [../fpu/spec.md](../fpu/spec.md) for the FPU's own tier structure. Implementations that omit the FPU entirely (e.g. J2) also omit Tier 0 SIMD, since the SH-4 FPU register file is the natural destination of the boundary instructions and meaningful SIMD-FP workloads need round-trippable scalar values.

**Data movement between scalar FPU and SIMD.** Two-instruction sequences `VLNS`+`VEXTF.L` / `VLNS`+`VINSF.L` and the integer variants `VEXT.B/W/L/Q` and `VINS.B/W/L/Q` (§5.7) move single lane values between a SIMD-side scalar register (`VFPUL` for FP, Rn for integer) and a specified lane of a Vn register. For cross-file moves between VFPUL and an FR/DR register, see the boundary instructions in §5.8. For wider transfers, software stages data through memory using VLD/VST and FMOV.S / MOV.L.

### 2.2 Lane organisation

Within a 128-bit vector V*n*, lanes are numbered from the low-order end:

| Lane width *w* | Lanes per vector | Lane index range |
|---|---|---|
| 8 bits  | 16 | 0..15 |
| 16 bits | 8  | 0..7  |
| 32 bits | 4  | 0..3  |
| 64 bits | 2  | 0..1  |

Lane *i* of V*n* at width *w* occupies bits `[w·i + w − 1 : w·i]` of V*n*, in little-endian lane order regardless of SH-2 endian configuration.

### 2.3 Reduction destination

Horizontal (reductive) SIMD operations write their scalar result either to the existing SH-4 integer scalar pair (MACL/MACH) for integer reductions, or to the SIMD-side scalar FP register **VFPUL** for FP reductions. **No SIMD reduction writes the scalar FPU register file** (FR / DR / FPUL) directly. This is the design choice that keeps SIMD blocks atomic with respect to SR.FD (see §2.6 rationale).

For additive reductions, the destination is **one type-class wider than the lane width** to preserve precision in long accumulation chains and prevent overflow in the common ML and DSP kernels (int8 → int32, FP16 → FP32).

| Lane width *w* | Lane type | Destination | Destination type |
|---|---|---|---|
| 8  | integer | MACL | int16 or int32 (always fits in 32 bits) |
| 16 | integer | MACL + MACH pair | int32 / int64 |
| 32 | integer | MACL + MACH pair | int64 |
| 64 | integer | MACL + MACH pair | int64 (truncates; software must guard against overflow) |
| 16 | FP (half) | **VFPUL (low 32 bits)** | FP32 |
| 32 | FP (single) | **VFPUL (low 32 bits)** | FP32 (or FP64 with widening, per operator) |
| 64 | FP (double) | **VFPUL (full 64 bits)** | FP64 |

Min/max/bitwise reductions (added in Tier 0) do not widen; the destination matches the input lane width (e.g., int16 min → MACL holds an int16). FP min/max use IEEE 754-2008 `minNum`/`maxNum` semantics. The add reduction is the canonical widening case.

**No V-register restrictions.** Any V register may be used as a source or destination in any SIMDH variant.

**Implicit clear at prefix decode.** When a SIMDH prefix is decoded, the reduction destination is implicitly cleared to zero: MACL and MACH are zeroed for integer-typed reductions; VFPUL is zeroed for FP-typed reductions. (This matches the legacy behavior, just retargeted to VFPUL.)

**Chaining cost.** A horizontal reduction's FP result is in VFPUL. To consume it in a scalar FR register, software uses one of the boundary instructions in §5.8 (`FMOV.VS VFPUL, FRn` for single-precision, `FMOV.VD VFPUL, DRn` for double-precision) — one cycle. To consume it back into another SIMD reduction, leave it in VFPUL across the next SIMDH prefix only after explicitly saving it (the prefix re-zeros VFPUL); the typical chained-reduction idiom saves VFPUL to an FR between reductions and finishes with an `FADD`. To consume the reduction back into a SIMD vector lane, use `VINSF.L` (which reads VFPUL) per §5.7. Integer reductions in MACL/MACH consume normally via `STS MACL, Rn` / `STS MACH, Rn`.

**FPU register-file independence.** Tier 0 SIMD does **not** write FR / DR / FPUL — only VFPUL and MACL/MACH. The scalar FPU register file is touched only by the boundary instructions in §5.8 and by ordinary scalar FPU code outside any SIMD block. As a corollary, SIMD lazy save (under SR.VD, §2.6) and FPU lazy save (under SR.FD, [../fpu/spec.md §6.3](../fpu/spec.md)) are **fully independent**: a task can own SIMD without owning FPU, and vice versa.

**FPU register file required nonetheless.** Although SIMD does not write FR/DR/FPUL directly, the boundary instructions in §5.8 do. Implementations targeting Tier 0 SIMD must therefore also implement the SH-4 FPU register file (FR0..FR15, FPUL, MACL, MACH) and **SR.FD** (Tier 1 FPU). This couples SIMD-enabled product points to an FPU-bearing baseline at Tier 1 minimum (J32 and up; see [../glossary.md §3](../glossary.md)). The Tier 0-SIMD-only-without-SR.FD configuration is **not architecturally allowed**.

### 2.4 Mode bits in FPSCR and VCSR

Tier 0 introduces a dedicated SIMD control register, separating SIMD mode bits from scalar FPU state:

- **VCSR** (Vector Control and Status Register, 32 bits): dedicated SIMD control register. Bit 0 = MKE (Mask Enable); bit 1 = IEE (IEEE-strict mode). Bits 2..31 reserved for future SIMD mode bits. VCSR is preserved across exception entry/RTE and saved/restored by the OS as part of per-task context — lazily, gated by SR.VD per §2.6. Software accesses VCSR via `LDS Rm, VCSR` / `STS VCSR, Rn` or via the dedicated `VMKCHG` toggle (§5.6) — both trap under SR.VD = 1.

- **VCSR.MKE** (bit 0): when set, governed SIMD operations apply P0 as a per-lane enable mask (§4.3, §4.4). When clear (default), all lanes are active. MKE has architectural effect only inside SIMD blocks — its value is read at governed-instruction decode.

- **VCSR.IEE** (bit 1, IEEE-strict mode): when set, governed FP operations follow IEEE 754 semantics for denormals and update FPSCR.FLAG bits OR-accumulated across lanes. When clear (default), governed FP operations flush denormals to zero and do not update FPSCR.FLAG. **In neither mode do SIMD FP operations deliver traps** — see §6.3 for the full FP exception model in SIMD context.

Existing SH-4 FPSCR fields apply unchanged to scalar FPU code. For FP governed SIMD instructions, only some FPSCR fields apply:

- `FPSCR.FR` (bank) affects only scalar FPU operations, not SIMD register addressing.
- `FPSCR.PR` (precision) is overridden inside a SIMD block by the prefix's width field; the architectural FPSCR value is not modified.
- `FPSCR.SZ` (transfer size) is overridden similarly.
- `FPSCR.RM[1:0]` (rounding mode) applies normally to FP governed instructions (both modes of VCSR.IEE).
- `FPSCR.EN` (exception enable) bits are **ignored** by SIMD FP operations regardless of VCSR.IEE. SIMD never traps on FP exceptions.
- `FPSCR.CAUSE` bits are **not set** by SIMD FP operations.
- `FPSCR.FLAG` bits are updated only when VCSR.IEE = 1, OR-accumulated across lanes.

**Naming rationale.** The placement of the mask-enable bit in a dedicated VCSR (rather than in FPSCR) follows the Cray-1 model (1976) of a dedicated vector-control register (VL) separate from the scalar status register. The IEE bit is directly modelled on PowerPC AltiVec's "Java mode" bit in VSCR (1996).

### 2.5 Architectural and pipeline state

Tier 0 architectural state:

- **V0..V15** (16 × 128 = 2048 bits).
- **P0** (16 bits): the SIMD predicate mask register. Each bit corresponds to one lane at the narrowest width (w = 8). At wider widths, lane *i* is enabled by P0[*i* · (*w*/8)] — i.e., the low bit of each *(w/8)*-bit group within P0. P0 is saved and restored via dedicated `LDS Rm, P0` and `STS P0, Rn` instructions (§5.6).
- **VCSR** (32 bits, 2 bits currently defined): mode/status as in §2.4.
- **VFPUL** (64 bits): the SIMD-side scalar FP register. Holds the result of SIMD horizontal FP reductions (§2.3) and the FP lane-bridge operations (§5.7); source/destination of the boundary instructions (§5.8). Saved/restored via `STS VFPUL, Rn` / `LDS Rm, VFPUL` (§5.6).

Total Tier 0 architectural addition versus a baseline SH-4: **2160 new architectural bits** (an increase of approximately 5–15% of the J32 core area depending on flip-flop vs SRAM register-file implementation). SIMD context-switch image size: **272 bytes** (V0..V15 = 256 + P0 = 4 + VCSR = 4 + VFPUL = 8).

Tier 1 and Tier 2 add **no new architectural state**.

The prefix-modal mechanism additionally requires the following **microarchitectural state**, none of which is architecturally visible or saved on exception:

- `SIMD_VAL` (1 bit), `SIMD_CNT[1:0]`, `SIMD_W[1:0]`, `SIMD_H` (1 bit), `SIMD_RED[2:0]` (reduction operator for horizontal blocks; ignored when SIMD_H = 0), and (Tier 1) `SIMD_SAT[1:0]` (saturation modifier for vertical blocks).
- `V_LANE_VALID` (1 bit), `V_LANE_REG[3:0]`, `V_LANE_IDX[3:0]` for the VLNS+VEXT/VINS lane-select latch.

Total decode-stage shadow state: 18 bits Tier 0 + 2 bits Tier 1 saturation modifier = 20 bits, all microarchitectural.

### 2.6 SR.VD — SIMD-disable trap (Tier 0; enables lazy context switch)

A new bit in the CPU status register, **SR.VD** at **SR bit 13**, gates access to the entire SIMD facility. It is the SIMD analogue of SR.FD ([../fpu/spec.md §6.3](../fpu/spec.md)) and exists for the same reason: to let the OS skip the 272-byte SIMD save/restore (V0..V15 + P0 + VCSR + VFPUL) on context switches between tasks that do not touch SIMD.

The SR layout authoritative source is [../hypervisor/hardware-spec.md §2.1](../hypervisor/hardware-spec.md); SR.VD occupies an SH-4-reserved bit slot (no compatibility break).

**Semantics.**

- `SR.VD = 0` (reset value): SIMD is enabled. All SIMD-touching instructions execute normally.
- `SR.VD = 1`: SIMD is disabled. Any SIMD-touching instruction raises a **SIMD-disabled exception** before any architectural state changes.

**Instructions that trap under SR.VD = 1** (the full set, so the OS can rely on trap-on-first-use):

| Instruction class | Examples |
|---|---|
| Prefix instructions | `SIMDV.{B,W,L,Q}`, `SIMDH<op>.{B,W,L,Q}`, the Tier 1 `rrr` saturation variants |
| Governed instructions in a SIMD block | the ordinary SH-2 / SH-4 ops that take on SIMD meaning after a prefix (§5.1, §5.2, §5.4); also the Tier 2 reinterpreted ops VCLMUL.D / VCRC32C.B (§5.5) |
| Vector memory ops | `VLD.{B,W,L,Q}`, `VST.{B,W,L,Q}`, `VGATHER.Q`, `VSCATTER.Q`, `VLDI.Q` |
| Lane bridges | `VLNS`, `VEXT.{B,W,L,Q}`, `VINS.{B,W,L,Q}`, `VEXTF.L`, `VINSF.L` |
| Mode toggles | `VMKCHG`, `SWIZZLE.I` |
| Control-register access | `LDS Rn, P0`, `STS P0, Rn`, `LDS Rn, VCSR`, `STS VCSR, Rn`, `LDS Rn, VFPUL`, `STS VFPUL, Rn` |
| Boundary instructions (§5.8) | `FMOV.VS FRn, VFPUL`, `FMOV.VS VFPUL, FRn`, `FMOV.VD DRn, VFPUL`, `FMOV.VD VFPUL, DRn` (these also trap under SR.FD because they touch FR/DR) |

The rule is simple: **any decode that would access V0..V15, P0, VCSR, or VFPUL, or that would set SIMD_VAL in the decode shadow, traps under SR.VD = 1.** There is no SIMD-control escape; SR.VD truly disables the facility end-to-end. This mirrors the FPU's no-escape rule for SR.FD and is what makes the lazy-context-switch idiom reliable.

**Trap classification.**

- On a Tier 0 / Tier 1 / Tier 2 implementation **without** the hypervisor extension (SR.HPRIV always 0, HEDR not consulted), the trap surfaces with a new EXPEVT value. Recommended: a fresh code in the J-Core extension range. The bare-metal value is implementation-defined, with the canonical assignment `EXPEVT = 0x1C0 EXC_SIMD_DISABLED` (matches the hypervisor-aware path below so a single trap-handler entry point serves both).
- On an implementation **with** the hypervisor extension, the trap is reported with cause `EXC_SIMD_DISABLED` (EXPEVT `0x1C0`) and is subject to HEDR delegation per [../hypervisor/hardware-spec.md §2.3.1](../hypervisor/hardware-spec.md), bit 24.

**Save / restore on context switch (OS pattern).** Identical shape to the SH-4 lazy-FPU pattern, applied to SIMD state:

```
schedule_out(prev_task):
    # Do NOT save SIMD state here.
    # Just set SR.VD=1 in prev_task's saved SR; SIMD state stays
    # in the register file until someone else needs it.
    prev_task.saved_sr |= SR_VD

schedule_in(next_task):
    # next_task already has SR.VD=1 in its saved SR (either set
    # above, or set at task creation). The CPU resumes with VD=1.
    restore_SR(next_task.saved_sr)   # SR.VD=1

# Inside the SIMD-disabled trap handler:
on_simd_disabled_trap():
    if current_simd_owner == current_task:
        # Spurious — owner did not change since last touch.
        # Just clear VD and resume.
        SR.VD = 0
        return_from_exception()

    if current_simd_owner != NULL:
        save_simd_state(current_simd_owner)   # 272 bytes via VST.Q × 16 + STS P0 + STS VCSR + STS VFPUL

    if current_task.has_saved_simd_state:
        restore_simd_state(current_task)      # 272 bytes via VLD.Q × 16 + LDS P0 + LDS VCSR + LDS VFPUL

    current_simd_owner = current_task
    SR.VD = 0
    return_from_exception()
```

Cost per context switch when neither outgoing nor incoming task touches SIMD: **zero** save/restore. Cost when both touch SIMD: one trap + one 272-byte save + one 272-byte restore — same total as eager save, just shifted in time. On typical Linux workloads where <5 % of processes use SIMD, this eliminates ~95 % of the save/restore overhead.

**Interaction with FGMT.** SR is per-thread on a J32-OOO/J32-FM core under FGMT ([../ooo/j32ooo-spec.md §13.1](../ooo/j32ooo-spec.md)). SR.VD is therefore naturally per-thread; one thread using SIMD does not impose save/restore overhead on the sibling thread that does not.

**Interaction with the scalar FPU — fully independent.** SIMD instructions write only SIMD-side state (V0..V15, P0, VCSR, VFPUL, MACL/MACH). They **never** write the scalar FPU register file (FR / DR / FPUL / FPSCR). Consequently, the SR.VD lazy-save mechanism for SIMD and the SR.FD lazy-save mechanism for the scalar FPU are completely independent: a task can own SIMD without owning FPU and vice versa; no SIMD instruction can corrupt FPU state owned by a different lazily-saved task. The only place the two facilities interact is the four boundary instructions in §5.8, which **trap under both SR.VD and SR.FD** since they touch both files. When both bits are set on a boundary instruction, **SR.VD wins** (the trap is `EXC_SIMD_DISABLED`); after the SIMD handler restores VFPUL and clears SR.VD, the retry then hits SR.FD if still set. This ordering matches Linux's expectation that lazy save reports the higher-level (SIMD) extension first.

**Why no SR.FD trap inside SIMD blocks.** An earlier design considered making SIMD FP-reductions and the lane bridges VEXTF.L / VINSF.L trap under SR.FD because they would have written FR/DR. This was rejected because exceptions inside SIMD blocks force block abandon-and-restart (§4.2 atomicity), making mid-block traps operationally expensive. The §2.3 / §5.7 redesign confines all FPU register-file touching to instructions outside SIMD blocks (the §5.8 boundary instructions), eliminating the mid-block-trap case entirely.

**Hardware cost.** One SR flip-flop (the bit itself; the SR register already exists) plus the trap condition wired into SIMD decode. Across the full SIMD facility decode, the trap is a single OR of all the SIMD-touching decode signals AND'ed with `SR.VD`. Estimated 30–50 LUT4 total. Negligible.

**Hypervisor-aware lazy SIMD ABI (when the hypervisor extension is present).** Identical shape to the FPU Tier 2 lazy ABI ([../fpu/spec.md §7](../fpu/spec.md)), applied to SIMD state:

- The hypervisor maintains a per-vCPU `simd_owner` flag and a per-pCPU `current_simd_owner_vcpu` register.
- At vCPU dispatch, the hypervisor sets `SR.VD = 1` in the guest's `HSSR` shadow before `HRTE`. The guest resumes with SIMD disabled.
- First guest SIMD instruction → `EXC_SIMD_DISABLED` trap. HEDR bit 24 routing:
  - `HEDR[24] = 0` (default): trap to hypervisor. Hypervisor checks `current_simd_owner_vcpu`; if different, saves previous owner's 272-byte SIMD image, restores this vCPU's image (if any), updates `current_simd_owner_vcpu`, clears `SR.VD = 0` in `HSSR`, `HRTE` back to the guest at the trapping instruction (which re-executes successfully).
  - `HEDR[24] = 1`: trap delegated to guest's S-mode handler. Guest OS implements its own lazy-SIMD policy for its user threads (mirror of the bare-metal pattern above).
- vCPU migration to a different pCPU: hypervisor cross-calls the source pCPU to save the 272-byte SIMD image, ships it to the destination pCPU, sets `SR.VD = 1` in the destination `HSSR`; first SIMD touch on the destination re-installs the image.

The 272-byte SIMD image layout: `V0..V15` (256 bytes) + `P0` (4 bytes, low 16 bits used) + `VCSR` (4 bytes) + `VFPUL` (8 bytes). Saved via `VST.Q` × 16 + `STS P0` + `STS VCSR` + `STS VFPUL`; restored symmetrically. The 16 vector stores can be issued back-to-back (no inter-dependencies); a typical save/restore round-trip is ~45–55 cycles on a 2-wide OoO with the L1-D in M state.

**Pre-2006 prior art.**

- **PowerPC G4 AltiVec `MSR.VEC`** (1999) — the canonical reference for an explicit SIMD-disable SR bit on a 128-bit dedicated-register-file SIMD ISA layered on an SH-4-like scalar host. Apple's Mac OS X kernel relies on it for lazy AltiVec save.
- **SH-4 `SR.FD`** (1998) — the FPU mechanism this directly mirrors.
- **Intel `CR0.TS`** (i486, 1990) — generalised to FP/MMX/SSE accesses; same trap-on-first-use idiom.
- **MIPS R4000 `Status.CU1/CU3`** (1991) — coprocessor-usable bits; same pattern for optional coprocessors.
- **PA-RISC `PSW.D`** (1986) — earliest reference for an SR-bit-gated FP facility.
- **4.4BSD lazy-FP context switch** (McKusick et al., 1996) — the OS-side pattern, identical for SIMD.
- **UltraSPARC II lazy-FP via FPRS.FEF** (1997) — the hypervisor-side cross-call pattern for vCPU migration.

---

## 3. Instruction Encoding

### 3.1 Opcode space and syntax normalization

All Tier 0 SIMD prefix encodings live in the **`1111 nnnn mmmm 1111` sub-row** (256 codepoints). This is the only sub-row consistently unallocated across SH-2 base, SH-4 FPU, and SH-4A FPU extensions. The remainder of the `1111 ……` block remains available for scalar SH-4 FPU operations.

**Syntax normalization (project-wide).** Two syntactic conventions appear in earlier draft material: the v0.5/v0.6 `SIMDV.w` / `SIMDH<op>.w` family, and the original VCLMUL design spec's `vprefix.v.d` / `vclmul.d` family. **This specification picks the `SIMDV.w` family**, and rewrites all VCLMUL/VCRC32C examples accordingly. Rationale:

1. `SIMDV.w` and `SIMDH<op>.w` already cover four lane widths uniformly (`.B`/`.W`/`.L`/`.Q`), and Tier 2 instructions reuse the same width-lock mechanism — `VCLMUL.D` is governed by `SIMDV.Q` (64-bit lanes), `VCRC32C.B` by `SIMDH<add>.B`.
2. The `SIMDV/SIMDH` mnemonics match the SH lineage (`MULS.W`, `MOV.L`).
3. Toolchains already need a single prefix family; supporting two syntactic skins doubles parser/disassembler complexity for zero ISA benefit.

This decision is also stated in [software-impl.md §3](software-impl.md). All assembly examples in this document use the `SIMDV.w` family.

### 3.2 Prefix instructions (SIMDV, SIMDH)

The prefix encodes lane width, mode, and block length.

```
SIMDV<r>.w   #N      vertical (lane-parallel) prefix, modifier r
SIMDH<op>.w  #N      horizontal (reductive) prefix with reduction operator

Bit  | 15 14 13 12 | 11 | 10 9 | 8 7 6 | 5 4 | 3 2 1 0 |
     |  1  1  1  1 |  H |  w w | r r r | N N |  1 1 1 1 |
     ─────────────────────────────────────────────────
        top nibble  H/V  width  modifier N-1  bottom nibble
                    0=V  00=8   (see)   0=1   (escape)
                    1=H  01=16          1=2
                         10=32          2=3
                         11=64          3=4
```

Field definitions:

- **H** (bit 11): 0 selects vertical mode; 1 selects horizontal mode.
- **ww** (bits 10:9): lane width — 00 = 8 bits, 01 = 16 bits, 10 = 32 bits, 11 = 64 bits.
- **rrr** (bits 8:6):
  - When H = 0 (vertical): SIMDV modifier bits.
    - bit 0 (NT, Non-Temporal): when set, governed memory access instructions in the block use non-temporal cache hints (§5.6).
    - bits 1, 2 (Tier 1): saturation modifier per §3.2.1. On Tier 0 these must be 00.
  - When H = 1 (horizontal): selects the reduction operator per the table below.
- **NN** (bits 5:4): block length, encoded as N − 1, giving N ∈ {1, 2, 3, 4} governed instructions.

**Reduction operator table (H = 1):**

| `rrr` | Mnemonic suffix | Operator | Identity element (for masked-lane substitution) | Tier |
|---|---|---|---|---|
| 000 | `SIMDHA` (default, `SIMDH` synonym) | add | integer: 0; FP: +0.0 | T0 |
| 001 | `SIMDHO` | bitwise OR | 0 | T0 |
| 010 | `SIMDHN` | bitwise AND | all-ones | T0 |
| 011 | `SIMDHX` | bitwise XOR | 0 | T0 |
| 100 | `SIMDHMN` | min (signed for int, IEEE minNum for FP) | integer: INT_MAX; FP: +∞ | T0 |
| 101 | `SIMDHMX` | max (signed for int, IEEE maxNum for FP) | integer: INT_MIN; FP: −∞ | T0 |
| 110 | `SIMDHMNU` | min unsigned (integer only; slot-illegal for FP) | UINT_MAX | T0 |
| 111 | `SIMDHMXU` | max unsigned (integer only; slot-illegal for FP) | 0 | T0 |

The block length cap of N = 4 matches the ARM Thumb-2 `IT` block precedent.

#### 3.2.1 SIMDV saturation modifier (Tier 1)

Tier 1 defines the SIMDV `rrr` field (bits 7:6, with bit 6 = NT preserved at `rrr[0]`):

| `rrr` | Mnemonic | Modifier |
|---|---|---|
| 000 | `SIMDV` (no suffix) | wrap (Tier 0 default) |
| 001 | `SIMDV.NT` (Tier 0 NT bit only) | wrap + non-temporal hint |
| 010 | `SIMDVS` | signed saturating (Tier 1) |
| 011 | `SIMDVS.NT` | signed saturating + NT (Tier 1) |
| 100 | `SIMDVU` | unsigned saturating (Tier 1) |
| 101 | `SIMDVU.NT` | unsigned saturating + NT (Tier 1) |
| 110 | reserved | slot-illegal in Tier 1; reserved for "halving" arithmetic |
| 111 | reserved | slot-illegal |

`SIMDH` prefixes ignore saturation (the reduction operator already determines the destination type). The Tier 1 saturation semantics are defined in §5.4.

### 3.3 SWIZZLE (context-sensitive)

SWIZZLE has **no standalone encoding**. Inside an open SIMD block (`SIMD_VAL = 1`), the bit pattern `1111 nnnn mmmm 1111` is decoded as SWIZZLE rather than as a prefix; the prefix's width and mode are inherited from the open block's microarchitectural state.

```
SWIZZLE Vn, Vm       1111 nnnn mmmm 1111    (inside SIMD block only; Tier 0)
```

- **nnnn**: destination/source vector Vn (V0..V15)
- **mmmm**: control vector Vm (V0..V15), interpreted as packed lane indices per §4.5

A SWIZZLE consumes one of the N governed-instruction slots declared by the prefix.

---

## 4. Execution Model (Tier 0)

### 4.1 Block lifetime

```
1. Prefix decoded:  SIMD_VAL ← 1, SIMD_CNT ← N − 1, SIMD_W ← ww, SIMD_H ← H,
                    SIMD_RED ← rrr (if H=1), SIMD_SAT ← rrr[2:1] (if H=0, Tier 1).
2. Each governed instruction decoded:
     - decode table is the SIMD decode table (see §5)
     - operand fields Rn/Rm interpreted as V0..V15 indices
     - execute lane-wise according to SIMD_W and SIMD_H (and SIMD_SAT, Tier 1)
     - on retire: if SIMD_CNT == 0, SIMD_VAL ← 0; else SIMD_CNT ← SIMD_CNT − 1
3. Block terminates when N governed instructions have retired.
```

### 4.2 Atomicity

**SIMD blocks execute atomically with respect to external interrupts.** Interrupts arriving while `SIMD_VAL = 1` are held pending and dispatched only after the block has retired its final governed instruction. No SIMD state is ever architecturally visible to an exception handler. RTE always lands at a non-SIMD instruction boundary.

The interrupt latency cost is bounded. Worst case: N = 4 governed instructions × 4 beats per instruction (narrowest lane width on a single 32-bit ALU implementation) = 16 cycles. At 50 MHz this is 320 ns. The latency is statically WCET-analysable.

**Synchronous exceptions** (slot-illegal, FPU exceptions raised by a governed FP instruction, memory faults on a governed load/store) are not deferred. See §6.

### 4.3 Vertical mode semantics

In vertical mode (`SIMD_H = 0`), a governed scalar instruction with operand pattern `op Rm, Rn` is interpreted as:

```
if VCSR.MKE == 0:                         ; unmasked
    for i in 0 .. (128/w − 1):
        V<Rn>.lane[i] ← V<Rn>.lane[i]  op  V<Rm>.lane[i]
else:                                      ; masked (VCSR.MKE == 1)
    for i in 0 .. (128/w − 1):
        if P0[i · (w/8)] == 1:
            V<Rn>.lane[i] ← V<Rn>.lane[i]  op  V<Rm>.lane[i]
        else:
            V<Rn>.lane[i] ← V<Rn>.lane[i]   (unchanged)
```

The result of every lane is independent (no cross-lane carry, no cross-lane data movement). Carry chains in the ALU are broken at lane boundaries.

**FMAC special case.** SH-4's FMAC is `FRn ← FR0 · FRm + FRn`. In SIMD context, FMAC is reinterpreted as `V<Rn>[i] ← V0[i] · V<Rm>[i] + V<Rn>[i]` — V0 plays the role of the implicit multiplier vector, matching FR0's role in scalar FMAC.

**Tier 1 saturation interaction.** When the prefix is `SIMDVS` or `SIMDVU`, the per-lane `op` result is clamped to the relevant integer range; see §5.4.

### 4.4 Horizontal mode semantics

In horizontal mode (`SIMD_H = 1`):

1. **At prefix decode**, the destination (MAC pair, FPUL, or DR0 per §2.3) is **implicitly cleared to zero**.
2. **Each governed instruction** computes its per-lane operation, reduces across lanes per the selected operator (add/OR/AND/XOR/min/max/min-u/max-u), and accumulates into the destination. Within a single block of N governed instructions, accumulation proceeds across them.
3. **When VCSR.MKE = 1**, masked lanes contribute the **identity element** for the chosen reduction operator (additive identity 0 for add, all-ones for AND, INT_MAX for min, etc., per §3.2). This keeps the reduction tree shape mask-independent.
4. **At block exit**, the destination holds the complete reduction result.

The detailed per-type reduction algorithms (integer, FP16, FP32, FP64) are unchanged from spec-v0.5 §4.4 and reproduced below for the integer case:

```
at prefix decode:        MAC ← 0
for each governed insn:
    for i in 0 .. (128/w − 1):
        if VCSR.MKE == 0 or P0[i · (w/8)] == 1:
            t[i] ← V<Rn>.lane[i]  op  V<Rm>.lane[i]
        else:
            t[i] ← identity_element(SIMD_RED)
    MAC ← reduce(SIMD_RED, MAC, t[0..(128/w − 1)])
```

For FP add-reductions the reduction respects IEEE 754 rounding using `FPSCR.RM`; the reduction order is implementation-defined.

**Cross-block accumulation.** Each SIMDH block produces a complete reduction; the destination is not preserved across block entries. Software combines partial sums with explicit scalar add operations across blocks.

### 4.5 SWIZZLE semantics

SWIZZLE permutes the lanes of Vn according to a control vector in Vm. Vm is interpreted as a packed array of lane indices (4 bits per index at w=8 down to 1 bit at w=64). Out-of-range indices force the destination lane to zero (AltiVec VPERM convention, 1996). See §5.6 for the immediate-pattern variant SWIZZLE.I.

### 4.6 Lane beat execution (implementation guidance)

Implementations time-multiplex the existing 32-bit ALU over 4 cycles ("beats") per 128-bit governed instruction. Beat schedules and implementation tactics live in [hardware-impl.md §2](hardware-impl.md).

---

## 5. Governed Instructions

When `SIMD_VAL = 1`, the decoder uses a SIMD-context decode table. The SIMD decode table differs from the standard table only in:

1. Lane-wise reinterpretation of integer arithmetic and logic operations (§5.1).
2. Lane-wise reinterpretation of SH-4 FPU compute operations (§5.2).
3. Reinterpretation of certain SH-2/SH-4 encodings as Tier 1 and Tier 2 SIMD instructions (§5.4, §5.5).
4. Reservation of all control-flow, system, and PC-relative instructions as slot-illegal (§5.3).
5. Reinterpretation of `1111 nnnn mmmm 1111` as SWIZZLE.

### 5.1 Integer SH-2 operations (Tier 0 governed)

| Encoding | Mnemonic | Lane operation | Tier |
|---|---|---|---|
| `0011 nnnn mmmm 1100` | ADD Rm,Rn | per-lane add | T0 |
| `0011 nnnn mmmm 1010` | SUB Rm,Rn | per-lane subtract | T0 |
| `0010 nnnn mmmm 1001` | AND Rm,Rn | per-lane AND | T0 |
| `0010 nnnn mmmm 1011` | OR  Rm,Rn | per-lane OR | T0 |
| `0010 nnnn mmmm 1010` | XOR Rm,Rn | per-lane XOR | T0 |
| `0110 nnnn mmmm 1011` | NEG Rm,Rn | per-lane negate | T0 |
| `0110 nnnn mmmm 0111` | NOT Rm,Rn | per-lane bitwise NOT | T0 |
| `0010 nnnn mmmm 1110` | MULU.W Rm,Rn | per-lane unsigned multiply (result width = 2w) | T0 |
| `0010 nnnn mmmm 1111` | MULS.W Rm,Rn | per-lane signed multiply | T0 |
| `0100 nnnn mmmm 1101` | SHLD Rm,Rn | per-lane dynamic logical shift | T0 |
| `0100 nnnn mmmm 1100` | SHAD Rm,Rn | per-lane dynamic arithmetic shift | T0 |
| `0011 nnnn mmmm 0000` | CMP/EQ Rm,Rn | per-lane equality test → writes P0 | T0 |
| `0011 nnnn mmmm 0011` | CMP/GE Rm,Rn | per-lane signed ≥ test → writes P0 | T0 |
| `0011 nnnn mmmm 0111` | CMP/GT Rm,Rn | per-lane signed > test → writes P0 | T0 |

Per-lane comparison results are written to **P0** (§2.5); bits not covered by the current width's active lanes are preserved across width changes.

### 5.2 SH-4 FPU operations (Tier 0 governed)

| Encoding | Mnemonic | Lane operation | Tier |
|---|---|---|---|
| `1111 nnnn mmmm 0000` | FADD FRm,FRn | per-lane FP add | T0 |
| `1111 nnnn mmmm 0001` | FSUB FRm,FRn | per-lane FP subtract | T0 |
| `1111 nnnn mmmm 0010` | FMUL FRm,FRn | per-lane FP multiply | T0 |
| `1111 nnnn mmmm 0011` | FDIV FRm,FRn | per-lane FP divide | T0 |
| `1111 nnnn mmmm 0100` | FCMP/EQ FRm,FRn | per-lane FP equality → writes P0 | T0 |
| `1111 nnnn mmmm 0101` | FCMP/GT FRm,FRn | per-lane FP > → writes P0 | T0 |
| `1111 nnnn mmmm 1110` | FMAC FR0,FRm,FRn | per-lane FMA (V0 is implicit third operand) | T0 |

`SIMD_W` selects the operand precision: w=32 → FP32 (4 lanes), w=64 → FP64 (2 lanes), w=16 → FP16 (8 lanes; requires FP16 implementation), w=8 → slot-illegal for FP.

### 5.3 Reserved inside SIMD block (Tier 0)

The following instruction classes are **reserved** as governed instructions and raise slot-illegal when encountered with `SIMD_VAL = 1`:

- Control flow (BRA, BSR, BT, BF, BT.S, BF.S, BRAF, BSRF, JMP, JSR, RTS, RTE).
- System and synchronisation (TRAPA, SLEEP, LDC, STC, LDS, STS, LDTLB).
- Cache and memory ordering (PREF, OCBI, OCBP, OCBWB, MOVCA, ICBI, MOVUA).
- PC-relative (MOVA, MOV.W @(disp,PC),Rn, MOV.L @(disp,PC),Rn).

Memory access opcodes (SH-2 `MOV.x` in rows `0001`, `0101`, `0110`, `1001`, `1101`, and SH-4 `FMOV.S` at `1111 nnnn mmmm 0110`..`1011`) are **redefined inside SIMD blocks** as vector load/store (§5.6).

A governed instruction whose encoding is not in §5.1, §5.2, §5.4, §5.5, or §5.6 is architecturally undefined and raises slot-illegal.

### 5.4 Tier 1 — integer/saturation extensions

#### 5.4.1 Saturating arithmetic mode (`SIMDVS`, `SIMDVU`)

The SIMDV `rrr` saturation modifier (§3.2.1) gates the result of integer governed instructions to clamp on overflow:

| Governed instruction | Wrap (T0) | Signed sat (SIMDVS, T1) | Unsigned sat (SIMDVU, T1) |
|---|---|---|---|
| `ADD Vm, Vn` | wrap | clamp to `[INT_MIN_w, INT_MAX_w]` | clamp to `[0, UINT_MAX_w]` |
| `SUB Vm, Vn` | wrap | clamp to `[INT_MIN_w, INT_MAX_w]` | clamp at 0 (no negative result) |
| `NEG Vm, Vn` | wrap (`NEG -128 = -128` at w=8) | clamp (`NEG -128 = 127`) | slot-illegal |
| `SHAD Vm, Vn` | wrap on left-shift | clamp on left-shift overflow | clamp on left-shift overflow |
| `SHLD Vm, Vn` | wrap | (logical shift; treated as unsigned) | clamp on left-shift overflow |
| `MULS`/`MULU` (vertical) | widens per §2.3 | n/a | n/a |
| `AND`, `OR`, `XOR`, `NOT` | unaffected | slot-illegal (SIMDVS+logical is meaningless) | slot-illegal |

Predication is orthogonal: a predicated saturating instruction applies saturation lane-wise to the active lanes; inactive lanes preserve their previous Vn value.

#### 5.4.2 New unary governed instructions

Encoded in the SH-4 FPU unary row `1111 nnnn xxxx 1101`, slots `xxxx ∈ {1000..1111}`:

| Encoding | Mnemonic | Operation | Tier |
|---|---|---|---|
| `1111 nnnn 1000 1101` | VABS Vn | per-lane signed absolute value | T1 |
| `1111 nnnn 1001 1101` | VPOPCNT Vn | per-lane population count | T1 |
| `1111 nnnn 1010 1101` | VUNPK4LU Vn | unpack low 64 bits as 16 unsigned nibbles → 16 int8 lanes | T1 |
| `1111 nnnn 1011 1101` | VUNPK4HU Vn | unpack high 64 bits as 16 unsigned nibbles → 16 int8 lanes | T1 |
| `1111 nnnn 1100 1101` | VUNPK4LS Vn | unpack low 64 bits as 16 signed nibbles | T1 |
| `1111 nnnn 1101 1101` | VUNPK4HS Vn | unpack high 64 bits as 16 signed nibbles | T1 |
| `1111 nnnn 1110 1101` | reserved | — | — |
| `1111 nnnn 1111 1101` | reserved | — | — |

- **VABS.** Per-lane signed absolute value. In wrap mode `VABS INT_MIN_w = INT_MIN_w`; in SIMDVS mode `VABS INT_MIN_w = INT_MAX_w`. Inside a SIMDH block the absolute values reduce per the chosen operator (typically add — sum of absolute values).
- **VPOPCNT.** Per-lane population count. Lane-width result stored in a same-width lane (w=8 → 0..8; w=64 → 0..64). SIMDVS/SIMDVU + VPOPCNT raises slot-illegal (no overflow possible).
- **VUNPK4 family.** INT4→INT8 nibble unpack; the 64-bit half of Vn is read as 16 packed 4-bit values, each zero- or sign-extended to 8 bits, written across the full 128 bits. Nibble order is **low nibble first** (matches GGML/llama.cpp/AWQ/GPTQ packing and SH little-endian conventions). Width modifier `ww` from the prefix is **ignored**; prefix must be `SIMDV.B` else slot-illegal.

#### 5.4.3 Tier 1 reinterpretations of SH-2 ops

| SH-2 outside SIMD | Encoding | Tier 1 inside SIMD |
|---|---|---|
| `SUBC Rm, Rn` | `0011 nnnn mmmm 1010` | `VABSDIFF Vm, Vn` — per-lane `|Vm[i] − Vn[i]|` |
| `EXTS.B Rm, Rn` | `0110 nnnn mmmm 1110` | `VPACK.SS Vm, Vn` — int16 → int8 signed sat |
| `EXTU.B Rm, Rn` | `0110 nnnn mmmm 1100` | `VPACK.SU Vm, Vn` — int16 → uint8 unsigned sat |
| `EXTS.W Rm, Rn` | `0110 nnnn mmmm 1111` | `VPACKW.SS Vm, Vn` — int32 → int16 signed sat |
| `EXTU.W Rm, Rn` | `0110 nnnn mmmm 1101` | `VPACKW.SU Vm, Vn` — int32 → uint16 unsigned sat |
| `DMULS.L Rm, Rn` | `0011 nnnn mmmm 1101` | `VMULSU Vm, Vn` — mixed-sign multiply (Vm signed × Vn unsigned) |

**VABSDIFF** in SIMDH<add> sums per-lane absolute differences into MACL (widened per §2.3) — single-instruction 16-byte SAD.

**VPACK family** uses Vn-source-Vn-dest convention: low output lanes come from Vm, high output lanes from Vn (the destination's prior value is absorbed as the high half). The prefix lane-width is ignored; `VPACK.*` must use `SIMDV.B`; `VPACKW.*` must use `SIMDV.W`; otherwise slot-illegal. Predication applies at output-lane granularity.

**VMULSU** in SIMDV.B truncates per-lane (low byte of each int16 product). In SIMDH<add>.B #1, per-lane int16 products sum and widen into MACL — this is the canonical VNNI/SDOT operation for INT8 GEMV with signed weights × unsigned activations.

#### 5.4.4 Extended widening-reduction table

Tier 1 extends the §2.3 reduction-destination table:

| Operation | *w* | Per-lane intermediate | SIMDH<add> destination |
|---|---|---|---|
| `VMULSU` | 8 | int16 | MACL (int32) — VNNI-equivalent |
| `VMULSU` | 16 | int32 | MACL+MACH (int64) |
| `VABSDIFF` | 8 | uint8 | MACL (uint16 → uint32) |
| `VABSDIFF` | 16 | uint16 | MACL+MACH (uint32 → uint64) |
| `VPOPCNT` | 8 | uint8 (0..8) | MACL (uint16) |
| `VPOPCNT` | 64 | uint8 (0..64) | MACL (uint8) |
| `VABS` | 8 | uint8 (0..128 sat) | MACL (uint16) |

`VPACK` and `VUNPK4` do not produce reducible per-lane values; they are slot-illegal inside SIMDH blocks.

### 5.5 Tier 2 — GF(2) crypto extensions

Tier 2 adds two instructions that extend the SIMD execution pipeline with Galois-field GF(2) arithmetic. Both reuse the existing widening-multiplier datapath with the carry chain gated to XOR mode (see [hardware-impl.md §6](hardware-impl.md)). No new architectural state. No new prefix bits.

#### 5.5.1 VCLMUL.D — Carryless multiply, doubleword

```
SH-2 outside SIMD:  DMULU.L   Rm, Rn   0011 nnnn mmmm 0101   (reserved by Tier 0)
Tier 2 inside SIMD: VCLMUL.D  Vm, Vn   0011 nnnn mmmm 0101
```

Two-operand form, destination doubles as first source (SH-2 convention):

```
Vn[127:0] ← Vn[63:0] ⊗ Vm[63:0]    ; GF(2)[x] polynomial product
```

GF(2) multiplication: `(a ⊗ b)[k] = XOR over i+j=k of (a[i] AND b[j])` — polynomial multiplication where coefficient addition is XOR (no carries propagate).

**Required prefix mode:** `SIMDV.Q` (vertical, 64-bit lane width). Any other prefix (horizontal, lane width ≠ 64, no active prefix) raises slot-illegal. Width-lock removes the need for an explicit width bit in the instruction word.

**Half selection.** Selection of which 64-bit half of a wider register participates is performed by **prior swizzle**, not by an immediate field. This is the principal encoding difference from Intel PCLMULQDQ and the key patent-clearance choice (see Appendix C.3.2).

**Predication.** Under VCSR.MKE = 1, the per-lane mask (interpreted at 64-bit lane granularity, so two relevant P0 bits per V register) selects whether the lane's result is written. Masked lanes preserve Vn unchanged.

**Behaviour at Tier 3 (future).** Reserved: any Tier 3 256-bit V register issuing VCLMUL.D under a 64-bit-lane prefix would compute 4 parallel CLMULs (low 64 bits of each 64-bit half). The architectural promise is delivered only when Tier 3 is specified.

**Exception model.**

| Condition | Behavior |
|---|---|
| Wrong prefix mode (horizontal, width ≠ 64, no prefix) | Slot-illegal |
| Predicate mask zero for a lane | Lane result not written; no side effect |
| Arithmetic overflow | Not possible — GF(2) multiply is total |
| Operand availability stall | Pipeline stall, no exception |

#### 5.5.2 VCRC32C.B — CRC-32C folding step

```
SH-2 outside SIMD:  MAC.L @Rm+,@Rn+  0000 nnnn mmmm 1111   (reserved by Tier 0)
Tier 2 inside SIMD: VCRC32C.B Vm, Vn 0000 nnnn mmmm 1111
```

Two-operand form. The CRC accumulator lives in the **low 32 bits of Vn**; data bytes come from Vm:

```
Vn[31:0]   ← crc32c_fold(Vn[31:0], Vm, P0_mask)
Vn[127:32] ← unchanged
```

The upper 96 bits of Vn are preserved so software may park unrelated state alongside the accumulator or use upper lanes for parallel CRC streams in future extensions.

**Required prefix mode:** `SIMDH<add>.B` (horizontal-reduce, 8-bit lanes). Any other prefix raises slot-illegal.

**Polynomial.** Fixed: **Castagnoli, 0x1EDC6F41** (normal form), 0x82F63B78 (reversed/reflected form). Used by iSCSI, SCTP, btrfs, ZFS, NVMe, RoCEv2, snappy. CRC-32-IEEE (used by Ethernet FCS / gzip / PNG / Zip) remains available via software CLMUL folding on top of VCLMUL.D.

**Semantics:**

```
crc = Vn[31:0]
for i in 0..15:
    if VCSR.MKE == 0 or P0[i] == 1:
        crc = (crc >> 8) ^ TABLE_C[(crc ^ Vm.byte[i]) & 0xFF]
Vn[31:0] = crc
```

where `TABLE_C` is the standard 256-entry CRC-32C table for polynomial 0x1EDC6F41. Hardware is free to use any equivalent computation (LFSR, CLMUL folding) provided the final accumulator value matches.

**Initial value and final XOR.** CRC-32C convention specifies XOR-with-0xFFFFFFFF at both input and output. This is **software's responsibility** (see [software-impl.md §7.1](software-impl.md)).

**Predicate behaviour.** P0's low 16 bits select which bytes of Vm participate. Bytes with P0 = 0 are skipped (no state update). Primary use: end-of-buffer tail handling — a single predicated VCRC32C.B collapses the 0..15-byte epilogue every CRC library currently writes as a scalar loop.

**Exception model.** Wrong prefix mode → slot-illegal. All-zero mask → no state change, no exception. Mid-instruction interrupt: implementation may complete or restart at instruction boundary (architecture treats VCRC32C.B as atomic).

### 5.6 Vector memory and SIMD-control instructions

Tier 0 vector memory and SIMD-control instructions are reproduced unchanged from spec-v0.5 §5.5/§5.6. The detailed encoding table is captured in Appendix A; the highlights:

- **VLD.Q / VST.Q** at six addressing modes (`@Rm`, `@Rm+`, `@-Rm`, `@(R0,Rm)`, plus indexed forms). 16-byte alignment required. Valid in or out of SIMD blocks.
- **VGATHER.Q / VSCATTER.Q** with per-lane offsets from Vm (inside SIMD block only).
- **VMOV Vm, Vn** (inside SIMD block; SH-4 FMOV-register encoding reinterpreted).
- **VLDI.Q #imm, Vn** (8-bit signed immediate broadcast; inside SIMD block).
- **SWIZZLE.I Vn, #pattern, #param** (immediate-pattern variant of SWIZZLE; inside SIMD block).
- **VMKCHG** (toggle VCSR.MKE; outside SIMD block).
- **LDS Rn, P0 / STS P0, Rn / LDS Rn, VCSR / STS VCSR, Rn / LDS Rn, VFPUL / STS VFPUL, Rn** (predicate, mode, and SIMD-scalar-FP register access; outside SIMD block). VFPUL transfers via these mnemonics move the low 32 bits to/from an integer scalar register Rn; for cross-file moves to/from the SH-4 FPU file (FRn / DRn) use the boundary instructions in §5.8.

#### 5.6.1 Memory access N=1 rule

A memory access instruction (VLD.Q, VST.Q, VGATHER.Q, VSCATTER.Q) used inside a SIMD block must be the **sole governed instruction** (prefix N=1) and must use a **SIMDV** (vertical) prefix. Violations raise slot-illegal at decode. This rule enables the **restart-from-prefix** fault-handling mechanism (§6.4) and makes the architecture transparently compatible with software-managed-MMU systems.

This N=1 restriction is the **mandatory baseline** for every SIMD implementation, and is the form the in-order J32 enforces.

##### Relaxed N>1 memory blocks (optional, J32-OOO and up)

An out-of-order implementation that cracks the prefix and its governed group into a single ROB atomic-commit group (§6.1) can relax the N=1 restriction to allow a memory access to be combined with compute (and other memory ops) in an **N>1 SIMDV block**, because the same all-or-nothing group commit that handles interrupts also handles a mid-block memory fault: the fault prevents the group from committing, the group is flushed, and execution restarts from the prefix — idempotent for the whole block, exactly as for the N=1 case. An implementation may advertise this via the **`SIMD_RELAXED_MEM`** capability bit (feature register; Linux `HWCAP_JCORE_SIMD_RELAXED_MEM`, [software-impl.md §8.5](software-impl.md)).

When `SIMD_RELAXED_MEM` is supported, the implementation must guarantee:

- the cracked prefix+group commits atomically — stores in the group do **not** drain to memory / coherence, and post-increment / pre-decrement pointer updates do **not** commit, until the entire group commits;
- a synchronous fault on any group member reports the **prefix PC** and flushes the group (no member retired);
- the group's total memory footprint is bounded by N ≤ 4, so it fits the load/store queue.

`SIMDH` (horizontal) memory access remains **slot-illegal** regardless of this capability — only the N>1 part of the baseline rule is lifted, not the SIMDV-only part.

**Compatibility is one-way and fails safe.** A binary that uses N>1 memory blocks runs on any `SIMD_RELAXED_MEM` implementation, and on an implementation *without* the capability it raises slot-illegal at the first such block (§6.2) — a loud trap, never silent mis-execution. Conversely, every baseline (N=1) binary runs unchanged on a relaxed implementation. Because of this asymmetry the relaxed form is **not** emitted by default: a toolchain must gate it on the `SIMD_RELAXED_MEM` capability (a `-m`-flag / HWCAP check), so a J32+SIMD target never receives it. On J32-OOO the relaxation buys code density (fewer prefixes), not throughput — the OoO front end already issues a standalone `VLD.Q`/`VST.Q` independently of the compute block — so toolchains should weigh the density gain against the loss of in-order portability.

#### 5.6.2 Non-temporal (NT) hint

The SIMDV `rrr[0]` bit is the NT (Non-Temporal) flag. When set on a memory-access governed instruction, the implementation may bypass cache allocation (write-combining buffer for stores, streaming cache way for loads, or full cache bypass). Implementations without streaming-friendly cache pathways may treat NT as a no-op; the architectural result is identical. Prior art: Intel SSE MOVNTPS (1999), AltiVec dst/dstt (1996), PowerPC dcbt (1993).

### 5.7 Lane extract/insert (VLNS+VEXT/VINS)

Bridging individual lanes between V registers and a SIMD-side scalar register uses a **two-instruction sequence**: a VLNS prefix arms a microarchitectural lane-select latch (`V_LANE_REG`, `V_LANE_IDX`); the immediately-following VEXT/VINS consumes the latch.

The pair must be **adjacent and atomic**: any instruction between VLNS and a following VEXT/VINS raises slot-illegal, and external interrupts are deferred between the two instructions. This makes the lane-select latch microarchitectural (not architecturally visible, never saved on exception).

**Scalar-side targets.** Integer variants (`VEXT.B/W/L/Q`, `VINS.B/W/L/Q`) read/write a SH-2 integer scalar register Rn. FP variants (`VEXTF.L`, `VINSF.L`) read/write **VFPUL**, the SIMD-side scalar FP register (§2.1, §2.3) — **not** an FR/DR register. To move the lane's value to or from the scalar FPU register file, follow / precede the VLNS+VEXTF.L (or VLNS+VINSF.L) pair with one of the boundary instructions in §5.8 (`FMOV.VS` for single-precision, `FMOV.VD` for double-precision). The two-step pattern keeps all FPU register-file touching outside SIMD blocks.

**Encodings** (full table in Appendix A): VLNS at `0100 mmmm llll 1011`; VEXT.B/W/L/Q at `0100 nnnn {1000..1011} 1011`; VINS.B/W/L/Q at `0000 nnnn {1000..1011} 1011`; VEXTF.L at `0100 0000 1100 1011` (destination is implicit VFPUL — no register field); VINSF.L at `0000 0000 1100 1011` (source is implicit VFPUL — no register field). Valid inside and outside SIMD blocks. Assembler accepts the single-mnemonic forms (`VEXT.L V5.2, R3` and `VEXTF.L V5.2` → result in VFPUL).

### 5.8 SIMD↔FPU boundary instructions (FMOV.VS / FMOV.VD)

Four instructions move scalar FP between **VFPUL** and the SH-4 FPU register file (FR / DR). They are the **only** path between the two register files and are executable only outside a SIMD block (raise slot-illegal inside one). They trap under **both SR.VD and SR.FD** because they touch both files; trap ordering is SR.VD first per §2.6.

| Mnemonic | Direction | Semantics |
|---|---|---|
| `FMOV.VS FRn, VFPUL` | scalar FPU → SIMD | move single-precision FP from FRn into VFPUL (low 32 bits; high 32 bits of VFPUL are zeroed) |
| `FMOV.VS VFPUL, FRn` | SIMD → scalar FPU | move single-precision FP from VFPUL (low 32 bits) into FRn |
| `FMOV.VD DRn, VFPUL` | scalar FPU → SIMD | move double-precision FP from DRn = {FR2n, FR2n+1} into VFPUL (full 64 bits) |
| `FMOV.VD VFPUL, DRn` | SIMD → scalar FPU | move double-precision FP from VFPUL (full 64 bits) into DRn |

**Encoding allocation** (preliminary; final bit assignments in Appendix A):
- Live in the SH-4 FPU sub-family (`xxxx 1010` / `xxxx 0011` LDC/STC pattern) using slots not consumed by PTEH/PTEL/TTB/TEA/MMUCR/ASIDR or by SH-DSP. Two unused slot pairs cover the four mnemonics. The encoding-space audit is deferred to the consolidated opcode-map pass.

**Privilege and traps:**
- User-mode access permitted (these are not privileged).
- SR.VD=1: trap with `EXC_SIMD_DISABLED` (cause 0x1C0 under hypervisor; bare-metal cause per §2.6).
- SR.VD=0, SR.FD=1: trap with FPU-disabled (cause 0x1B0 under hypervisor with Tier 2 FPU; bare-metal per [../fpu/spec.md §6.3](../fpu/spec.md)).
- Both bits set: SR.VD wins (handler restores SIMD; retry then hits SR.FD if still set).

**Latency:** one cycle in a typical Tier 1 FPGA implementation; pipelined as a register-file-to-register-file move with no FP-unit involvement. The double-precision variants share the existing FR-pair access pattern from FMOV.D (Tier 1 FPU spec §5).

**No FPSCR effect.** These instructions do not modify FPSCR (no rounding, no conversion, no flag update). They are pure bit-pattern moves.

**Pre-2006 prior art:** Intel SSE MOVD / MOVQ between XMM and x87/general registers (1999); MIPS-3D paired-single moves between FP scalar and FP pair (1999); Cray-1 VL→S register copy through a dedicated path (1976). All establish the precedent of explicit cross-file moves between a SIMD-side scalar register and the host scalar file.

---

## 6. Exception Model

### 6.1 Interrupt deferral

External interrupts arriving while `SIMD_VAL = 1` or `V_LANE_VALID = 1` are held pending and delivered at the next architecturally-visible boundary (block exit, or VEXT/VINS retirement). Worst-case combined latency: 18 cycles (16 for a 4-instruction block + 2 for a VLNS+VEXT pair).

Implementations may optionally support **mid-block interrupt with replay**: on interrupt, the block is abandoned, the saved PC is set to the prefix's PC, and the ISR is dispatched. This is permitted but not required, and is the recommended low-latency policy for out-of-order implementations.

On J32-OOO ([../ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md)) the natural realization is to crack the prefix and its governed group into a single **ROB atomic-commit group** (the same mechanism the OoO core already uses for `CAS.L`, [../ooo/j32ooo-spec.md §10](../ooo/j32ooo-spec.md)): the group commits all-or-nothing, and an interrupt arriving before commit flushes the whole group, sets the saved PC to the prefix PC (recoverable from the group's ROB entries), and dispatches the ISR. Because nothing in the group has committed, restart-from-prefix is **idempotent for an arbitrary compute block**, not only the N=1 memory case of §6.4 — the architectural V/P0/MAC/VFPUL state was never updated, so re-execution from the prefix reads the same source operands. Stores in the group must not drain to memory/coherence and post-increment / pre-decrement pointer updates must not commit until the group commits. This makes mid-block interrupt latency equal to a branch-mispredict flush rather than waiting for the block (and its slowest governed op — e.g. a per-lane `FDIV`) to retire. Implementations choosing this policy should bound consecutive flush-restarts of the same block (or fall back to deferral after a threshold) to guarantee forward progress under a high-frequency interrupt source.

### 6.2 Slot-illegal exception

Raised by:

- A reserved governed instruction (§5.3) or undefined SIMD encoding.
- SWIZZLE with a reserved pattern selector.
- A VEXT/VINS instruction with `V_LANE_VALID = 0`.
- Any instruction other than VEXT/VINS encountered with `V_LANE_VALID = 1`.
- A SIMDV prefix with `rrr` value reserved at the implementation's tier (e.g. `rrr=110/111` on a Tier 1 implementation; `rrr∈{010..111}` on a Tier 0-only implementation).
- A memory access instruction governed by a prefix with N > 1 (unless the implementation advertises `SIMD_RELAXED_MEM`, §5.6.1) or by a SIMDH prefix (always).
- A Tier 1 instruction (VABS, VPOPCNT, VUNPK4, VABSDIFF, VPACK, VMULSU, SIMDVS/SIMDVU saturation) on a Tier 0-only implementation.
- A Tier 2 instruction (VCLMUL.D, VCRC32C.B) on an implementation without Tier 2 support.
- VCLMUL.D outside `SIMDV.Q`, or VCRC32C.B outside `SIMDH<add>.B`.
- `SIMDVS`/`SIMDVU` + logical-only governed instruction (AND/OR/XOR/NOT/VPOPCNT).

The SR pushed on slot-illegal entry has `SIMD_VAL = 0` and `V_LANE_VALID = 0` (both microarchitectural latches are zero at all exception boundaries).

### 6.3 FP exception handling in SIMD context

**SIMD FP operations never deliver traps**, regardless of VCSR.IEE or FPSCR.EN. Software requiring IEEE 754 trap behaviour must use scalar FP.

- **Default mode (VCSR.IEE = 0):** denormals flushed to ±0, FPSCR.FLAG not updated, FPSCR.EN ignored, FPSCR.CAUSE not set. Cheapest to implement and matches the expectations of autovectorised code, DSP libraries, ML inference, graphics, audio.
- **IEEE-strict mode (VCSR.IEE = 1):** IEEE 754 gradual underflow; FPSCR.FLAG OR-accumulated across lanes (sticky until cleared via `LDS Rn, FPSCR`); FPSCR.EN still ignored.

Minimal implementations may support only IEE = 0 (writes to IEE silently ignored, reads return 0).

Prior art: PowerPC AltiVec "Java mode" (1996), Intel SSE MXCSR-controlled trap-disabled default (1999), Cray-1 sticky-flag-only (1976), GCC/LLVM `-fno-trapping-math` default for vector code.

### 6.4 Memory exceptions and restart-from-prefix

VLD.Q, VST.Q, VGATHER.Q, VSCATTER.Q can raise standard SH-4 memory exceptions (address error, TLB miss / page fault, bus error).

**Memory faults inside SIMD blocks: restart-from-prefix.** Per the N=1 rule (§5.6.1), the saved PC points to **the prefix instruction**; block microarchitectural state is cleared; the exception handler runs in scalar context (need not be SIMD-aware); RTE returns to the prefix; the block re-opens and the memory access retries.

This restart is correct because the N=1 block contains only the memory access, with no committed compute. Loads are idempotent. Stores re-write the same data from an unchanged source register. Gathers and scatters re-execute per-lane (previously-completed lanes act as no-ops modulo memory ordering). Post-increment / pre-decrement modes commit only on success, so a faulting access does not advance the address register.

This makes software-managed TLB systems transparently compatible with SIMD code. See [hardware-impl.md §3](hardware-impl.md) for the restart microarchitecture.

### 6.5 Instruction-fetch faults inside a block (translated-memory implementations)

§6.4 covers *data*-side faults on governed load/store instructions. A separate hazard exists on the *instruction* side once address translation is enabled: a SIMD block is a run of consecutive halfwords (the prefix plus up to four governed instructions, ≤ 10 bytes; or a `VLNS`+`VEXT`/`VINS` pair, 4 bytes — §3.2, §5.7), and that run may straddle a page boundary. If the prefix lies on one page and a later governed instruction lies on a different page that misses the TLB / faults on fetch, a naive implementation takes the instruction-fetch exception *after* the prefix has set the decode shadow latch (`SIMD_VAL = 1`, [hardware-impl.md §2](hardware-impl.md)). Exception entry clears the shadow latch ([hardware-impl.md §3.2](hardware-impl.md)); after the handler maps the page and `RTE`s to the faulting governed instruction, that instruction would decode with `SIMD_VAL = 0` — i.e. as an ordinary scalar SH instruction operating on R-registers rather than lane-wise on V-registers. **Silent corruption.**

**Architectural rule (mandatory contract).** *Every synchronous fault taken with a SIMD block (or `VLNS` pair) open reports the prefix PC.* This generalizes the restart-from-prefix rule of §6.4 from data faults to instruction-fetch faults. The block carries no committed architectural state until it retires, so reporting the prefix PC always yields a correct, idempotent restart: the handler is SIMD-unaware, `RTE` returns to the prefix, and the block re-opens and re-executes from the beginning. The restart is correct only when the handler *fixes* the fault and retries (TLB miss / page fault); a non-recoverable instruction-fetch fault (e.g. a permission violation with no fixup) terminates the thread and never returns, so no resumption is required.

**Scope.** This hazard arises only when **both** (a) translation is enabled (MMU present, `MMUCR.AT = 1`) and the block sits in a translated segment (SH-4 P0/P3), **and** (b) the block spans a page boundary. A ≤ 10-byte block crosses at most one boundary at any supported page size (≥ 4 KB; the J-Core default is 16 KB — see [../mmu/design-spec.md §3.3](../mmu/design-spec.md)), and the prefix's own page is already known-good because the prefix was fetched from it. Implementations without an MMU (e.g. J2-class) and code running untranslated (P1/P2 kernel space) cannot raise it; a physical-bus error on an untranslated fetch is fatal (no retry) and therefore poses no resumption hazard.

**Resolution by product point.** The mandatory contract above is satisfiable three ways, matching the three implementation styles:

| Implementation | Mechanism |
|---|---|
| **J2 / J32 without MMU** | Nothing required — no translation means no recoverable instruction-fetch fault. |
| **J32 + TLB (in-order)** | **Prefix-time block-fetch validation** (below). |
| **J32-OOO** | The ROB atomic-commit group of §6.1 already reports the prefix PC on any flush, so an instruction-fetch fault on a governed uop flushes the group and restarts from the prefix with no extra mechanism. |

**Prefix-time block-fetch validation (in-order J32 + TLB).** The block length *N* is known at prefix decode (the `NN` field, §3.2), so the address of the block's last halfword, `end = prefix_PC + 2·N`, is known immediately. When `end` lies in a different page than `prefix_PC`, the implementation probes the fetch-translation of `end`'s page *before any governed instruction issues*, using the prefix's otherwise-idle memory/MA slot (the prefix performs no compute and no data access). A miss or fault on that probe is raised against the **prefix PC** (clean restart; the block never opens). Once the probe succeeds, every governed-instruction fetch in the block is guaranteed to translate, so a mid-block instruction-fetch fault becomes impossible. The same-page common case (the overwhelming majority at a 16 KB page — a ≤ 10-byte block crosses a boundary with probability ≈ 10/16384) needs only a page-number comparison and no probe. The `VLNS`+`VEXT`/`VINS` pair (§5.7) is validated identically by probing `prefix_PC + 2`. See [../mmu/hardware-spec.md §5.1](../mmu/hardware-spec.md) for the MMU-side requirement and verification point.

**Prior art.** The Intel 386 (1985) validates that an instruction whose encoding spans a page boundary is fully fetchable — faulting against the instruction's starting address — before it executes. A SIMD block is architecturally a single atomic fetch unit, so validating its entire fetch extent at the prefix is the same established technique.

---

## 7. Reserved encoding space (forward compatibility)

Inside SIMD blocks, the following encoding ranges are architecturally reserved. Future tier extensions may define instructions in these ranges without breaking existing binaries.

| Reserved range | Approx. codepoints | Anticipated use |
|---|---|---|
| BRA, BSR top nibbles `1010`/`1011` | 8192 | Future SIMD branch / predicated-block control |
| BT/BF top nibble `1000 1xxx` | 1024 | Per-lane conditional execution variants |
| LDC/STC/LDS/STS in `0100 ……` (minus the Tier 0 P0/VCSR sub-opcodes) | ~240 | Additional SIMD configuration register access |
| MOV.x loads/stores in `0001` and `0101` rows (minus gather/scatter/SWIZZLE.I sub-opcodes) | ~6000 | Stride loads, alignment hints |
| FPU unary row `1111 nnnn xxxx 1101`, slots 0..7 and 14..15 | ~144 V slots | Additional VEXT/VINS widths, future unary ops |
| Prefix `rrr` reserved bits | ~5 codepoints in SIMDV (110/111) | Halving arithmetic, future modifiers |
| TRAPA, SLEEP | 257 | Debug, vector breakpoint |
| MAC.W, MULL in `0000 ……` (MAC.L now consumed by VCRC32C.B; DMULU.L by VCLMUL.D; DMULS.L by VMULSU) | ~48 | Multi-issue MAC, extended-precision SIMD |
| CAS.L, DIV0S, DIV0U, DIV1 | ~16 | SIMD atomic operations, lane-wise division |
| Tier 3 (256-bit) | reserved entirely | J64 wide-vector extensions |

**Total Tier 0/1/2 reserved: ≈22,000 architecturally-reserved 16-bit codepoints** inside SIMD blocks. Ample headroom for incremental architectural growth.

---

## 8. Assembly syntax and worked examples

Reference assembler syntax (single-mnemonic forms):

```
SIMDV.B/.W/.L/.Q       #N
SIMDV.NT.B/.W/.L/.Q    #N            ; T0 (NT hint)
SIMDVS.B/.W/.L/.Q      #N            ; T1 (signed saturating)
SIMDVU.B/.W/.L/.Q      #N            ; T1 (unsigned saturating)
SIMDH<r>.B/.W/.L/.Q    #N            ; r ∈ {A, O, N, X, MN, MX, MNU, MXU}

VLD.Q   @Rm, Vn        / @Rm+,Vn / @(R0,Rm),Vn
VST.Q   Vn, @Rm        / @-Rm     / @(R0,Rm)
VMOV    Vm, Vn
VLDI.Q  #imm, Vn
SWIZZLE Vn, Vm
SWIZZLE.I Vn, #pat, #param
VGATHER.Q @(R0,Vm), Vn
VSCATTER.Q Vn, @(R0,Vm)

VEXT.B/W/L/Q Vm.lane, Rn             ; assembler emits VLNS+VEXT pair
VINS.B/W/L/Q Rm, Vn.lane
VEXTF.L      Vm.lane, FRn
VINSF.L      FRm, Vn.lane

VMKCHG
LDS  Rn, P0   /  STS P0, Rn
LDS  Rn, VCSR /  STS VCSR, Rn

; Tier 1
VABS Vn         /  VPOPCNT Vn
VUNPK4LU Vn / VUNPK4HU Vn / VUNPK4LS Vn / VUNPK4HS Vn
VABSDIFF  Vm, Vn
VPACK.SS  Vm, Vn / VPACK.SU Vm, Vn / VPACKW.SS Vm, Vn / VPACKW.SU Vm, Vn
VMULSU    Vm, Vn

; Tier 2
VCLMUL.D  Vm, Vn       ; legal only under SIMDV.Q
VCRC32C.B Vm, Vn       ; legal only under SIMDHA.B
```

### 8.1 Tier 0 examples

**4×4 single-precision matrix-vector multiply.** Each row's dot product writes to DR0 (FP32 lanes widened to FP64 per §2.3), then narrowed via FCNVDS and inserted into V5 lane-by-lane:

```
    VLD.Q    @R_mat,    V0
    VLD.Q    @(R_mat+16), V1
    VLD.Q    @(R_mat+32), V2
    VLD.Q    @(R_mat+48), V3
    VLD.Q    @R_vec,    V4

    SIMDH.L  #1
    FMUL     FR4, FR0                ; V0 · V4, widened sum → VFPUL
    ; VFPUL holds the FP32 sum; move it across the SIMD/FPU boundary
    FMOV.VS  VFPUL, FR6              ; §5.8 boundary move
    VINSF.L  V5.0                    ; reads VFPUL (assembler emits VLNS V5, #0; VINSF.L)
    ; ... rows 1..3 identical pattern ...
    VST.Q    V5, @R_result
```

(Note: earlier drafts of this example used `FCNVDS DR0, FPUL ; FSTS FPUL, FR6`
to drain the reduction. With VFPUL as the reduction destination at the
prefix-declared width, those two instructions collapse into a single
`FMOV.VS VFPUL, FR6`.)

**Vertical SIMD-FP FMA loop.** With multiplier broadcast (A) in V0:

```
loop:
    VLD.Q    @R_y, V2
    VLD.Q    @R_x, V1
    SIMDV.L  #1
    FMAC     FR1, FR2                ; V2 ← V0 · V1 + V2
    VST.Q    V2, @R_y
```

**Predicated FP32 update.** Add V2 to V1 only where `V1 > 0`:

```
    SIMDV.L  #1
    FCMP/GT  FR3, FR1                ; P0[i·4] ← (V1[i] > 0)
    VMKCHG                           ; VCSR.MKE ← 1
    SIMDV.L  #1
    FADD     FR2, FR1                ; predicated
    VMKCHG                           ; restore
```

**Sparse vector dot product with VGATHER.Q.** Inner loop of CSR SpMV (full version reproduced in the archived spec-v0.5 §9.7):

```
loop:
    VLD.Q   @R4+, V0                 ; dense x[i..i+3] (FP32)
    VLD.Q   @R5+, V1                 ; indices[i..i+3] (int32)

    SIMDV.L #1
    VGATHER.Q @(R0,V1), V2           ; per-lane addr = R0 + V1.lane[k] · 4

    SIMDHA.L #1
    FMUL    FR2, FR0                 ; widen-sum → DR0

    FCNVDS  DR0, FPUL
    FSTS    FPUL, FR1
    FADD    FR1, FR3
```

### 8.2 Tier 1 examples

**INT8 GEMV (signed weights × unsigned activations).**

```
        CLRMAC
.loop:
        VLD.Q    @R4+, V1            ; 16 int8 weights
        VLD.Q    @R5+, V2            ; 16 uint8 activations
        SIMDH.B  #1
        VMULSU   V1, V2              ; MACL += Σ int16(int8(V1[i]) × uint8(V2[i]))
        DT       R0
        BF       .loop
```

**16×16 SAD (video motion estimation).**

```
        CLRMAC
        MOV      #16, R0
.row:
        VLD.Q    @R4+, V1
        VLD.Q    @R5+, V2
        SIMDH.B  #1
        VABSDIFF V2, V1              ; MACL += Σ |V1[i] - V2[i]|
        DT       R0
        BF       .row
```

**Audio mixing with hard limiting (saturating add).**

```
        VLD.Q    @R4+, V1
        VLD.Q    @R5+, V2
        SIMDVS.W #1
        ADD      V2, V1              ; V1 := sat_s16(V1 + V2) — no overflow distortion
        VST.Q    V1, @R8
```

**XOR-popcount Hamming distance (bioinformatics / SimHash / LDPC).**

```
        VLD.Q    @R4+, V1
        VLD.Q    @R5+, V2
        SIMDV.B  #1
        XOR      V2, V1
        SIMDH.B  #1
        VPOPCNT  V1                  ; MACL += hamming weight of V1
```

**Saturating requantization chain after MAC.** Pack int32 → int16 → uint8 with saturation at each stage:

```
        SIMDV.W  #1
        VPACKW.SS V1, V2            ; int32 → int16 signed saturating
        SIMDVU.B  #1
        VPACK.SU  V2, V3            ; int16 → uint8 unsigned saturating
```

Additional Tier 1 examples (INT4 weight unpack, BAM nucleotide unpack, 4-disk SAD video block, k-mer Hamming for short-read alignment, 8-track audio mixer, etc.) are preserved in [archive/spec-v0.6.md §9](archive/spec-v0.6.md).

### 8.3 Tier 2 examples

**CRC-32C tight loop.** 16-byte chunks with predicated tail handling:

```
        ; r4 = buffer, r5 = byte length
        MOV     #-1, r0              ; CRC seed = 0xFFFFFFFF
        ; ... software loads r0 into V0[31:0] using VINS.L (see software-impl.md §3) ...
.loop:
        ; While length ≥ 16: full-mask 16-byte fold.
        VLD.Q     @R4+, V1
        MOV       #0xFFFF, R2
        LDS       R2, P0
        VMKCHG                       ; enable mask
        SIMDHA.B  #1
        VCRC32C.B V1, V0             ; V0[31:0] ← crc32c_fold(V0[31:0], V1, mask)
        VMKCHG
        ; ... loop bookkeeping ...

        ; Tail (0..15 bytes): predicated, single instruction
        MOV       #tail_mask, R2     ; mask = (1u<<len)-1
        LDS       R2, P0
        VMKCHG
        SIMDHA.B  #1
        VCRC32C.B V_tail, V0         ; only `len` low bytes participate
        VMKCHG

        ; Finalize: ~V0[31:0] is the CRC-32C output
```

**AES-GCM GHASH (Karatsuba 128×128).** Five VCLMUL.D operations per 16-byte block (three for the Karatsuba product, two for Montgomery reduction); see [software-impl.md §6.2](software-impl.md) for the full kernel.

```
        ; V1 = a (128-bit), V2 = b (128-bit). Swizzle isolates the desired halves.
        SWIZZLE.I V1, #0, #0          ; a_lo to low 64 (broadcast-lane param=0 example)
        ; ... full Karatsuba sequence in software-impl.md §6.2 ...
        SIMDV.Q  #1
        VCLMUL.D V2, V1               ; V1 ← a_lo ⊗ b_lo
        ; ... three CLMULs total + reduction CLMULs ...
```

**RAID-6 Q syndrome (GF(2^8) generator multiply).** Pattern: one VCLMUL.D per data byte against the generator constant, followed by polynomial reduction modulo 0x11D (full kernel in [software-impl.md §6.3](software-impl.md)).

---

## 9. Application domain map

The cumulative beneficiary surface across the three implemented tiers:

| Domain | Tier 0 | Tier 1 | Tier 2 | Representative algorithms |
|---|---|---|---|---|
| ML inference (INT8/INT4) |   | ✔ |   | INT8 GEMV (VMULSU), INT4 weight unpack (VUNPK4), saturating requant (VPACK + SIMDVS) |
| Video coding |   | ✔ |   | H.264/HEVC/AV1 SAD (VABSDIFF + SIMDH<add>), motion estimation |
| Bioinformatics |   | ✔ |   | k-mer Hamming (XOR + VPOPCNT), BAM nucleotide unpack (VUNPK4), FM-index rank |
| Computer vision |   | ✔ |   | Sobel/Prewitt (VABS), ORB binary descriptors (XOR + VPOPCNT), stereo SAD |
| DSP / audio |   | ✔ |   | FIR/IIR with sat MAC, audio mixer (SIMDVS + ADD), pitch detection (VABSDIFF) |
| Comms / channel coding |   | ✔ | ✔ | Viterbi (VABSDIFF), LDPC syndrome (VPOPCNT), CRC32C (VCRC32C.B), Reed-Solomon (VCLMUL.D) |
| Database analytics |   | ✔ |   | Roaring bitmaps (VPOPCNT), HyperLogLog, SimHash, MinHash |
| Games / simulation |   | ✔ |   | Chess/Go bitboards (VPOPCNT), Game of Life, kNN-DTW |
| Cryptanalysis |   | ✔ |   | Linear cryptanalysis bias, S-box analysis, hamming-weight DPA models |
| Storage | ✔ | ✔ | ✔ | RAID-6 (VCLMUL.D), btrfs/ZFS checksums (VCRC32C.B), NVMe-oF digests |
| Networking |   |   | ✔ | iSCSI/SCTP digests, RoCEv2 (VCRC32C.B), AES-GCM (VCLMUL.D) |
| Cryptography |   |   | ✔ | AES-GCM (GHASH), ChaCha20-Poly1305 alt, Carter-Wegman hashing |
| FEC |   |   | ✔ | Reed-Solomon (DVB-S2, CCSDS), BCH syndrome (VPOPCNT optional) |
| Post-quantum |   |   | ✔ | HQC code-based KEM (GF(2) polynomial multiply via VCLMUL.D) |
| Compression |   |   | ✔ | gzip/zlib CRC folding (VCLMUL.D + software constants for CRC-32-IEEE) |
| Scientific / autovec | ✔ |   |   | Generic vertical/horizontal FP & integer kernels, SpMV (gather), reductions |

Combined named-algorithm count across Tiers 0+1+2: ≈ 70+ algorithms in production use. The per-tier cost (Tier 0: 2096 architectural bits + ~5–15% area; Tier 1: ≈4k gates; Tier 2: ≈16k gates Karatsuba pipelined) amortises across this surface.

---

## 10. Implementation tier selection

Implementations are free to pick any subset `{Tier 0} ∪ Tier_set ⊆ {Tier 1, Tier 2}` and to advertise their support via the implementation feature register (§16). Tier 3 is excluded until specified. Suggested product mappings:

- **J32:** Tier 0+1 (ML, signal processing, analytics, video).
- **J32-OOO:** Tier 0+1 (the OoO spec cracks the prefix; same SIMD coverage as J32). May additionally advertise the optional `SIMD_RELAXED_MEM` capability (§5.6.1), which lifts the N=1 memory-block restriction; this is a one-way-compatible microarchitectural feature, not a tier.
- **J32-FM:** Tier 0+1+2 (adds crypto, FEC, storage, post-quantum).
- **J64:** Tier 0+1+2+3 (Tier 3 yet to be specified).

Partial-Tier-1 implementations are allowed (per the v0.6 §10 subset menus — bitmap, vision, DSP, LLM). Tier 2 is all-or-nothing (both VCLMUL.D and VCRC32C.B, or neither, since VCRC32C.B's recommended implementation is decode-stage fusion onto VCLMUL.D — see [hardware-impl.md §6.2](hardware-impl.md) — though a stand-alone LFSR-only VCRC32C.B variant remains permitted).

---

## 11. Open questions

The following are deferred:

1. **Narrow floating-point formats.** FP16 (IEEE 754-2008 binary16) is the only narrow format pre-2006 prior art admits cleanly (Hitachi HD61810 1982, Scott WIF 1991, 3dfx Voodoo 1995, SGI/OpenEXR 1997, NVIDIA Cg 2002). Planned for the next Tier 0 revision. bfloat16, FP8 (E4M3/E5M2), FP4 (MXFP4/NVFP4) are deliberately excluded for patent reasons; see Appendix F.
2. **Non-widening SIMDH variant.** If real workloads show the FP32-in/FP32-out widening cost dominates, a non-widening SIMDH-add could be added.
3. **Multiple predicate registers.** P0..P3 or P0..P7 could be added in reserved encoding space.
4. **Mid-block interrupt with replay.** Currently implementation-defined (§6.1). Promote to architectural with precise semantics if any J-core licensee requires it.
5. **Tier 3 (256-bit).** J64 wide-vector extensions. Whether Tier 0/1/2 instructions transparently promote to 256-bit or whether Tier 3 adds distinct opcodes is the principal open question.
6. **Tier 2 multi-stream / vertical-parallel CRC.** Currently single-stream. A vertical-SIMD CRC variant under a SIMDV prefix could exploit the upper 96 bits of the accumulator register for parallel streams.
7. **GHASH reduction constants.** Well-known (Gueron-Kounavis 2009); package as a header constant table for library reuse.
8. **HWCAP bit allocation.** A new `HWCAP_JCORE_GF2` (and per-tier feature bits), plus the microarchitectural-capability bit `HWCAP_JCORE_SIMD_RELAXED_MEM` (§5.6.1), must be assigned in the jcore Linux port. See [software-impl.md §8.5](software-impl.md).

---

## Appendix A. Encoding Summary

### A.1 Prefixes (outside SIMD block)

```
SIMDV<r>.w  #N         1111 0ww<rrr> NN 1111
SIMDH<r>.w  #N         1111 1ww<r>   NN 1111

SIMDV modifier-field (rrr):
  000 = wrap (T0 default)
  001 = wrap + NT (Tier 0 non-temporal memory hint)
  010 = signed saturating (Tier 1)
  011 = signed sat + NT (Tier 1)
  100 = unsigned saturating (Tier 1)
  101 = unsigned sat + NT (Tier 1)
  110 = reserved
  111 = reserved

Reduction-operator field (rrr, SIMDH only, Tier 0):
  000 = add (default; sum)               100 = min (signed / IEEE minNum)
  001 = OR  (bitwise)                    101 = max (signed / IEEE maxNum)
  010 = AND (bitwise)                    110 = min unsigned (integer only)
  011 = XOR (bitwise)                    111 = max unsigned (integer only)
```

### A.2 Governed instructions (inside SIMD block)

```
INTEGER (Tier 0, SH-2 reinterpretation):
  ADD/SUB/AND/OR/XOR/NEG/NOT/MULS.W/MULU.W/SHAD/SHLD/CMP{EQ,GE,GT}
    interpret Rn/Rm as V<n>/V<m> indices

FP (Tier 0, SH-4 reinterpretation):
  FADD/FSUB/FMUL/FDIV/FCMP{EQ,GT}/FMAC interpret FRn/FRm as V<n>/V<m>

COMPARISONS (Tier 0):
  CMP/*, FCMP/* write per-lane results to P0

SWIZZLE (Tier 0, inside SIMD block only):
  SWIZZLE  Vn, Vm        1111 nnnn mmmm 1111   (register-controlled)
  SWIZZLE.I Vn,#pat,#par 0001 nnnn pppp dddd   (immediate; dddd ∈ 0010..1111)

VECTOR MEMORY (Tier 0):
  VLD.Q    @Rm, Vn       1111 nnnn mmmm 1000
  VLD.Q    @Rm+, Vn      1111 nnnn mmmm 1001
  VST.Q    Vn, @Rm       1111 nnnn mmmm 1010
  VST.Q    Vn, @-Rm      1111 nnnn mmmm 1011
  VLD.Q    @(R0,Rm), Vn  1111 nnnn mmmm 0110
  VST.Q    Vn, @(R0,Rm)  1111 nnnn mmmm 0111
  VGATHER.Q @(R0,Vm),Vn  0001 nnnn mmmm 0000
  VSCATTER.Q Vn,@(R0,Vm) 0001 nnnn mmmm 0001

VECTOR REGISTER MOVE (Tier 0):
  VMOV     Vm, Vn        1111 nnnn mmmm 1100

VECTOR IMMEDIATE BROADCAST (Tier 0):
  VLDI.Q   #imm, Vn      1110 nnnn iiii iiii

LANE EXTRACT/INSERT (Tier 0; valid in or out of SIMD blocks):
  VLNS Vm, #lane         0100 mmmm llll 1011
  VEXT.B Rn              0100 nnnn 1000 1011
  VEXT.W Rn              0100 nnnn 1001 1011
  VEXT.L Rn              0100 nnnn 1010 1011
  VEXT.Q Rn,Rn+1         0100 nnnn 1011 1011   ; Rn must be even
  VEXTF.L                0100 0000 1100 1011   ; destination implicit: VFPUL
  VINS.B Rn              0000 nnnn 1000 1011
  VINS.W Rn              0000 nnnn 1001 1011
  VINS.L Rn              0000 nnnn 1010 1011
  VINS.Q Rn,Rn+1         0000 nnnn 1011 1011
  VINSF.L                0000 0000 1100 1011   ; source implicit: VFPUL

SIMD↔FPU BOUNDARY (Tier 0, §5.8; outside SIMD block; trap under SR.VD and SR.FD):
  FMOV.VS FRn, VFPUL     (encoding pending opcode-map audit, §5.8)
  FMOV.VS VFPUL, FRn     (encoding pending opcode-map audit, §5.8)
  FMOV.VD DRn, VFPUL     (encoding pending opcode-map audit, §5.8)
  FMOV.VD VFPUL, DRn     (encoding pending opcode-map audit, §5.8)

SIMD CONTROL-REGISTER ACCESS — VFPUL (Tier 0; outside SIMD block):
  LDS Rn, VFPUL          (encoding pending opcode-map audit; in the SIMD-control LDS/STS family)
  STS VFPUL, Rn          (encoding pending opcode-map audit; in the SIMD-control LDS/STS family)

PREDICATION AND CONTROL (Tier 0, outside SIMD block):
  VMKCHG                 1111 1100 1111 1101
  LDS Rn, P0             0100 nnnn 1000 1010
  STS P0, Rn             0000 nnnn 1000 1010
  LDS Rn, VCSR           0100 nnnn 1001 1010
  STS VCSR, Rn           0000 nnnn 1001 1010

TIER 1 UNARY (FPU unary row slots 8..13):
  VABS      Vn           1111 nnnn 1000 1101
  VPOPCNT   Vn           1111 nnnn 1001 1101
  VUNPK4LU  Vn           1111 nnnn 1010 1101
  VUNPK4HU  Vn           1111 nnnn 1011 1101
  VUNPK4LS  Vn           1111 nnnn 1100 1101
  VUNPK4HS  Vn           1111 nnnn 1101 1101

TIER 1 REINTERPRETED 2-OPERAND (in SIMD block; SH-2 ops outside):
  VABSDIFF  Vm, Vn       0011 nnnn mmmm 1010   (was SUBC)
  VPACK.SS  Vm, Vn       0110 nnnn mmmm 1110   (was EXTS.B)
  VPACK.SU  Vm, Vn       0110 nnnn mmmm 1100   (was EXTU.B)
  VPACKW.SS Vm, Vn       0110 nnnn mmmm 1111   (was EXTS.W)
  VPACKW.SU Vm, Vn       0110 nnnn mmmm 1101   (was EXTU.W)
  VMULSU    Vm, Vn       0011 nnnn mmmm 1101   (was DMULS.L)

TIER 2 REINTERPRETED 2-OPERAND (in SIMD block):
  VCLMUL.D  Vm, Vn       0011 nnnn mmmm 0101   (was DMULU.L; required: SIMDV.Q)
  VCRC32C.B Vm, Vn       0000 nnnn mmmm 1111   (was MAC.L; required: SIMDHA.B)

KEY:
  ww:   00=byte (FP16 illegal), 01=word/FP16, 10=long/FP32, 11=quad/FP64
  NN:   N−1, so 00=1, 01=2, 10=3, 11=4 governed instructions per block
  H/V:  0=vertical, 1=horizontal
  nnnn,mmmm: 4-bit V<n>/V<m>/FRn/Rn index
  llll: 4-bit lane index
  pppp: 4-bit SWIZZLE pattern selector
  dddd: 4-bit pattern parameter (or sub-opcode discriminator)
  iiii iiii: 8-bit signed immediate (sign-extended by VLDI.Q)
```

### A.3 Tier 2 opcode-bit derivation

The Tier 2 instructions consume two of the v0.5/v0.6-reserved 2-operand slots:

- **VCLMUL.D = `0011 nnnn mmmm 0101`** reinterprets SH-2 `DMULU.L Rm, Rn`. This row is in v0.5 §8's "MAC.W, MAC.L, MULL, DMULS, DMULU in `0000`/`0010` rows" reserved space (slightly extended to include `0011 ……` row entries, which v0.5 §5.4 lists as "decoded but undefined"). v0.6 took the parallel `0011 nnnn mmmm 1101` slot (DMULS.L → VMULSU); Tier 2 takes the `0011 nnnn mmmm 0101` slot (DMULU.L) directly next to it. No collision with v0.6.
- **VCRC32C.B = `0000 nnnn mmmm 1111`** reinterprets SH-2 `MAC.L @Rm+,@Rn+`. Reserved by v0.5 §5.4 ("MAC.W, MAC.L, ... are architecturally undefined and reserved for future use") and unconsumed by v0.6 (v0.6 Appendix A still notes ~63 codepoints free in this category).

Both selections honour the layout convention of v0.5 §3 (top-op | Vn-or-Vd | Vm-or-Vs | sub-op nibbles) and follow the existing 2-operand SH-2 encoding template. The width-lock approach (legal only under `SIMDV.Q` or `SIMDHA.B`) avoids needing a width field inside the instruction word and matches v0.6's `VPACK`/`VPACKW` pattern of "lane-width comes from the prefix".

---

## Appendix B. Decision Log (consolidated)

This appendix summarises the architectural evolution that led to this consolidated specification. The full per-version delta history is preserved in [archive/spec-v0.5.md Appendix B](archive/spec-v0.5.md).

- **v0.1–v0.3 (archived):** prefix-modal SIMD developed atop SH-4 FPU register aliasing; predicate register P0 added in v0.3.
- **v0.4 (archived):** dedicated V0..V15 register file introduced; FPU-alias model abandoned; anchor field removed; vector load/store specified.
- **v0.5 → Tier 0 in this document:** VCSR introduced as dedicated SIMD control register; trap-free SIMD FP exception model (two modes via VCSR.IEE); expanded reduction operators (add/OR/AND/XOR/min/max/min-u/max-u); VGATHER.Q/VSCATTER.Q; VLDI.Q broadcast-immediate; SWIZZLE.I pattern-immediate; VLNS+VEXT/VINS lane-bridge pair; N=1 memory-access rule with restart-from-prefix.
- **v0.6 → Tier 1 in this document:** saturating-arithmetic modifier on SIMDV (`SIMDVS`/`SIMDVU`); VABS, VPOPCNT, VUNPK4 family; VABSDIFF (SAD primitive), VPACK family (saturating narrowing pack), VMULSU (mixed-sign multiply — VNNI-equivalent for INT8 GEMV).
- **VCLMUL design spec → Tier 2 in this document:** VCLMUL.D (64×64 → 128-bit GF(2) carryless multiply) and VCRC32C.B (CRC-32C folding step). This consolidation **finalises the previously-TBD opcode bits** (Appendix A.3): VCLMUL.D at `0011 nnnn mmmm 0101`, VCRC32C.B at `0000 nnnn mmmm 1111`. The 256-bit "performance tier on J64" mention in the original VCLMUL design spec is reconciled here as Tier 3 (architecturally reserved, J64-only; not part of Tier 2).
- **Syntax normalization:** all examples now use `SIMDV.w`/`SIMDH<op>.w` mnemonics. The vclmul-* `vprefix.v.d` skin is dropped (§3.1).

---

## Appendix C. Prior art (consolidated, pre-2006 only)

Per the project-wide prior-art-pre-2006 policy ([../glossary.md §2](../glossary.md)), every technique in this specification must be backed by published prior art predating 2006. This appendix collects the citations, organised by mechanism. Sources after 2005 are flagged.

### C.1 Tier 0 mechanisms

#### C.1.1 Prefix-modal SIMD (§3.2)

- **ARM Thumb-2 IT block** (ARMv6T2, 2003). 16-bit prefix governs 1–4 following instructions.
- **IA-64 / Itanium template + stop bits** (Intel/HP, 1998–2000). Bundle-level metadata controls contained instruction dispatch.
- **SH-DSP repeat block** (Hitachi, 1996). LDRS/LDRE/SETRC set state that governs a subsequent block.
- **Cray-1 VL register** (Cray Research, 1976). Sets lane count for subsequent vector operations.
- **Multiflow TRACE VLIW** (1984). Wide instruction encodes behaviour of multiple operations.

#### C.1.2 Predication via persistent mask (§2.5, §4.3, §4.4)

- **Cray-1 vector mask register VM** (1976). Set by scalar copy or vector compare; consumed by merge instructions; persistent architectural state.
- **HP PA-RISC nullification** (1986). Per-instruction conditional nullification.
- **IA-64 predicate register file** (Intel/HP, 1998–2000). 64 architectural predicate registers, decoupled from comparison setup.
- **TMS320C6x VelociTI** (TI, 1997). VLIW predicates set by ordinary compare/move.
- **Multiflow TRACE predicated execution** (1984).

#### C.1.3 Dedicated SIMD register file (§2.1)

- **Cray-1 V registers** (1976), 8 × 64 × 64-bit, separate from S and A files.
- **CDC STAR-100** (CDC, 1974), architecturally-visible vector facility.
- **Convex C-1** (1985), 8 vector registers separate from scalar files.
- **NEC SX-2** (1985), 40 dedicated vector data registers.
- **Intel SSE XMM registers** (1999), 8 × 128-bit, separate from x87 / MMX.
- **PowerPC AltiVec / VMX** (1996–1999), 32 × 128-bit, separate from GPR / FPR.

#### C.1.4 Vector permutation (§3.3, §4.5, §5.6)

- **Cray-1 compress/expand** (1976), VM-controlled.
- **HP PA-RISC MAX-2 PERMH** (1995–1996), immediate-controlled halfword permute (Lee, IEEE Micro Jul/Aug 1996).
- **Sun VIS BSHUFFLE/BMASK** (1995–1996, IEEE Micro 1996).
- **Intel MMX PSHUFW** (1996, Peleg & Weiser IEEE Micro 1996); **SSE SHUFPS** (1999), **SSE2 PSHUFD** (2001).
- **MIPS MDMX pshu** (1996).
- **PowerPC AltiVec VPERM / vec_perm** (1996–1999) — direct precedent for register-controlled SWIZZLE with out-of-range-produces-zero semantics.

#### C.1.5 Vector-indexed memory (§5.6)

- **CDC STAR-100** (1974), indirect-addressing vector ops.
- **Cray-1 gather** (1976), constant-stride.
- **Cray X-MP** (1982), arbitrary-index GATHER/SCATTER — *the* foundational prior art for the modern operation, with structural identity to VGATHER.Q.
- **Fujitsu VP-200** (1982), **NEC SX-2** (1985), **Convex C-1** (1985), **Cray Y-MP** (1988), **NEC SX-3** (1989) — successor architectures continuing the design.
- **Espasa & Valero**, "Vector Architectures: Past, Present and Future," Supercomputing '98 (survey).

#### C.1.6 Non-temporal memory hints (§3.2, §5.6.2)

- **PowerPC dcbt / dcbtst** (1993).
- **PowerPC AltiVec dst / dstt / dstst** (1996–1999) — direct precedent for the NT-as-transient-stream hint.
- **SPARC V9 PREFETCH** (1994).
- **MIPS PREF / PREFX** (1996).
- **Intel SSE MOVNTPS / PREFETCHNTA** (1999), **MOVNTPD / MOVNTI** (2001).

#### C.1.7 Trap-free SIMD FP (§6.3)

- **Cray-1** (1976), sticky-flag-only FP with no traps.
- **PowerPC AltiVec VSCR "Java mode"** (1996), non-Java FTZ vs Java IEEE-strict; neither trapping.
- **Intel SSE MXCSR** (1999), trap-disabled default.

### C.2 Tier 1 mechanisms

| Tier 1 feature | Prior art | Year | Source |
|---|---|---|---|
| Saturating ADD/SUB | MMX PADDSB/PADDSW/PSUBSB/PSUBSW | 1996 | Intel IA-32 SDM, MMX chapter |
| Saturating ADD/SUB | AltiVec vaddsbs/vaddshs/vsubsbs/vsubshs | 1996/1999 | AltiVec PEM §6.13–6.18 |
| Saturating ADD/SUB | Cray-1 vector saturating mode | 1976 | Cray-1 HRM (HR-0004) |
| Saturating ADD/SUB | TMS320C6000 saturating MAC | 1997 | TI SPRU189 |
| VABS | MIPS MDMX (via MIN.OB R0 + sign extract) | 1996 | MIPS V instruction set |
| VABS | ARMv6 USAD8 building block (implicit ABS) | 2002 | ARM ARM v6 |
| VABS | SSSE3 PABSB/PABSW/PABSD | 2006 | **Within cutoff (March 2006).** Independent earlier prior art (MIPS MDMX 1996, ARMv6 2002) suffices on its own. |
| VPOPCNT (scalar) | CDC 6600 CXi count | 1964 | Thornton, *Design of a Computer: The CDC 6600* |
| VPOPCNT (vector) | CDC STAR-100 bit-count vector | 1974 | CDC STAR-100 Programming Reference |
| VPOPCNT | DEC Alpha CTPOP | 1996 | Alpha AXP ARM |
| VPOPCNT | SPARC V9 POPC (optional) | 1994 | SPARC V9 Architecture Manual |
| VUNPK4 (composition) | BCD packed-decimal storage | 1959 | IBM 1401 Reference Manual |
| VUNPK4 (composition) | MMX PUNPCKLBW; AltiVec vmrglb | 1996 | as above |
| VABSDIFF / SAD | DEC Alpha PERR (sum-of-byte-differences) | 1996 | Alpha AXP ARM |
| VABSDIFF / SAD | MIPS MDMX RACL.OB / RACM.OB | 1996 | MIPS V instruction set |
| VABSDIFF / SAD | Intel SSE PSADBW | 1999 | Intel IA-32 SDM (P-III) |
| VABSDIFF / SAD | ARMv6 USAD8 / USADA8 | 2002 | ARM ARM v6 |
| VPACK (signed sat) | MMX PACKSSWB / PACKSSDW | 1996 | Intel IA-32 SDM |
| VPACK (unsigned sat) | MMX PACKUSWB | 1996 | as above |
| VPACK | AltiVec vpkshss/vpkshus/vpkswss/vpkswus | 1996/1999 | AltiVec PEM §6.79–6.82 |
| VPACK | MIPS MDMX PACKSC | 1996 | MIPS V |
| VMULSU (mixed-sign byte dot) | AltiVec vmsummbm (4 unsigned × 4 signed → int32) | 1996 | AltiVec PEM §6.95 |
| VMULSU (mixed-sign byte dot) | TMS320C6x smpyhl | 1997 | TI SPRU189 |
| VMULSU | Dubey, "AltiVec Extension Accelerates Media Processing" | 1996 | IEEE Micro 16(5) |

### C.3 Tier 2 mechanisms

#### C.3.1 GF(2) polynomial arithmetic and CRC

GF(2) polynomial arithmetic predates computing — Évariste Galois, 1830s. Carryless-multiply hardware has been continuously deployed since the 1980s in every Ethernet controller's CRC LFSR. The relevant pre-2006 design sources:

- **Karatsuba & Ofman**, "Multiplication of Multidigit Numbers on Automata," *Soviet Physics Doklady* 7:595–596, 1962. The Karatsuba decomposition used by the Tier 2 hardware (three sub-multiplies instead of four) — 60+ years of prior art.
- **Peterson, W.W. & Brown, D.T.**, "Cyclic Codes for Error Detection," *Proc. IRE* 49(1):228–235, 1961. The foundational CRC-as-error-detection paper.
- **Castagnoli, G., Bräuer, S., Herrmann, M.**, "Optimization of Cyclic Redundancy-Check Codes with 24 and 32 Parity Bits," *IEEE Trans. Communications* 41(6):883–892, 1993. The CRC-32C polynomial 0x1EDC6F41 used by VCRC32C.B — published without patent claim, 33 years of prior art.
- **Koç, Ç.K. & Acar, T.**, "Montgomery Multiplication in GF(2^k)," *Designs, Codes and Cryptography* 14(1):57–69, 1998. Montgomery-style GF(2) reduction underlying the GHASH reduction path used in [software-impl.md §6.2](software-impl.md).
- **Mastrovito, E.D.**, "VLSI Architectures for Computation in Galois Fields," PhD thesis, Linköping University, 1991. Bit-parallel GF(2^m) multiplier architecture — direct precedent for the Tier 2 datapath described in [hardware-impl.md §6](hardware-impl.md).
- **Wegman, M.N. & Carter, J.L.**, "New Hash Functions and Their Use in Authentication and Set Equality," *J. Computer and System Sciences* 22:265–279, 1981. The Carter-Wegman authentication construction that GHASH and CLHASH implement — 45 years of prior art.
- **Bernstein, D.J.**, "The Poly1305-AES Message Authentication Code," *Fast Software Encryption* 2005, LNCS 3557:32–49, 2005. Polynomial-evaluation MAC predating Gueron-Kounavis 2009 by 4 years; included for completeness of the polynomial-MAC lineage.
- **Sarwate, D.V.**, "Computation of Cyclic Redundancy Checks via Table Look-Up," *Comm. ACM* 31(8):1008–1013, 1988. The slice-by-N CRC table-driven technique that VCRC32C.B's reference semantics use as the golden model.
- **Ethernet IEEE 802.3** (1983 onward). CRC-32-IEEE / CRC-32-Ethernet LFSR hardware — every Ethernet MAC since 10Base-5 ships a hardware CRC32 implementation. Demonstrates that 32-bit CRC computation in dedicated silicon is multi-decade prior art across the entire industry.

**Note on Intel CLMUL papers.** Gueron & Kounavis "Efficient Implementation of GCM Using a Carry-Less Multiplier" (IPL, 2009) and Gueron's Intel white paper "Intel Carry-Less Multiplication Instruction and its Usage for Computing the GCM Mode" (2014) are both **post-2006** and **cannot be used as prior art** for the J-Core design. The 2009 paper is cited only in [software-impl.md §6.2](software-impl.md) as an *implementation reference* for the well-known reduction constants. The Tier 2 architectural design rests entirely on the pre-2006 sources above (Karatsuba 1962, Peterson-Brown 1961, Castagnoli-Bräuer-Herrmann 1993, Mastrovito 1991, Koç-Acar 1998, Sarwate 1988, IEEE 802.3 1983, Carter-Wegman 1981). No Intel CLMUL-era source is load-bearing for the architectural specification.

#### C.3.2 Patent landscape (Tier 2)

- **US 7,590,930** (Intel, filed 2005): "instruction to perform carry-less multiplication and an instruction to perform a bit reflection operation." 20-year term: expires 2025; **effectively expired** at time of writing (2026).
- **US 8,977,943** (AMD, filed 2012): "implementation of CRC32 using carryless multiplier." Expires ~2032.

**J-Core design choices that maintain clearance:**

- **Two-operand encoding** (Vn ← Vn ⊗ Vm) differs structurally from Intel's three-operand PCLMULQDQ with immediate.
- **Swizzle-based half-selection** is mechanically distinct from PCLMULQDQ's 2-bit immediate selector — see §5.5.1.
- **Accumulator in SIMD register file low 32 bits** (VCRC32C.B) differs from Intel CRC32 (which uses GPRs) and from the AMD patent's specific claims.
- **Width-locked decoding via prefix** is a unique J-Core mechanism not present in x86 encodings.
- **Polynomial fixed to Castagnoli**, with software handling of CRC-32-IEEE via CLMUL folding, sidesteps Intel CRC32 instruction patent claims entirely.

The design is in clean independent-development territory grounded entirely in pre-2006 prior art (the underlying mathematics is from 1830s Galois / 1962 Karatsuba / 1961 Peterson-Brown / 1993 Castagnoli, the multiplier architecture is from 1991 Mastrovito, and every commercial CLMUL/CRC32 patent of practical relevance has expired or is structurally distinct).

#### C.3.3 Patent-relevance summary across all tiers

The earlier patent-landscape discussion (archived spec-v0.5 Appendix D.4) covers two ARM patents (GB2548600A / US 10,782,972 on vector predication; US 10,599,428 on Helium's relaxed-execution model). Tier 0's design choices (persistent P0 mask register, decoupled compare-from-apply via VMKCHG, sequential beats only) sit comfortably outside both claim languages. The detailed analysis is preserved in [archive/spec-v0.5.md Appendix D.4](archive/spec-v0.5.md).

### C.4 Flagged citations (post-2006) and resolutions

- **SSSE3 PABSB/PABSW/PABSD** is dated 2006 (Intel IA-32 SDM, March 2006 edition). This is *within* the project's hard cutoff (Jan 1, 2006 priority date or later is *not* acceptable). The Tier 1 VABS instruction is **not** justified by SSSE3 alone: independent earlier prior art is MIPS MDMX (1996, via MIN.OB R0 + sign extract) and ARMv6 USAD8 (2002, implicit ABS in the building block). The SSSE3 reference is preserved for completeness but is non-load-bearing.
- **Gueron & Kounavis 2009; Gueron 2014; Kounavis & Berry 2008** (all CLMUL-era Intel sources) are explicitly listed above as post-2006 references used **only** as implementation guides (well-known reduction constants and software fold sequences) in [software-impl.md §6.2](software-impl.md). They are **not** prior art for any architectural feature; the architectural design rests on the pre-2006 Karatsuba / Mastrovito / Castagnoli / Peterson-Brown / Sarwate / IEEE 802.3 chain.
- **OpenSPARC T2 CMU** (Sun/Oracle, 2007) was referenced in the original vclmul-hardware-impl document as a Verilog source. Now flagged: any direct copy of OpenSPARC T2 silicon (2007) violates the cutoff. The Tier 2 hardware implementation must derive from the pre-2006 Mastrovito bit-parallel GF(2^m) multiplier (1991), the Karatsuba decomposition (1962), and the carry-gated integer-multiplier reuse strategy ([hardware-impl.md §6](hardware-impl.md)). The OpenSPARC T2 reference is retained as informative-only in [hardware-impl.md](hardware-impl.md) but **not as prior art**.

No mechanism has been *dropped* from the architectural specification as a result of this audit; the VABS, VCLMUL.D, and VCRC32C.B mechanisms all rest on pre-2006 sources independent of the flagged citations.

---

## Appendix D. Glossary cross-reference

For naming of products (J2, J32, J32-OOO, J32-FM, J64), threading (FGMT), service tiers (Tier 0/1/1.5 in the *service* sense, distinct from SIMD tiers here), and the prior-art-pre-2006 policy, see [../glossary.md](../glossary.md).

SIMD-specific terms (V0..V15, P0, VCSR, SIMDV/SIMDH, governed instruction, lane, beat, atomic block, widening reduction, identity-element substitution, decoupled compare-from-apply, NT hint) are defined inline in the relevant sections above. The full archival glossary lives in [archive/spec-v0.5.md Appendix E](archive/spec-v0.5.md).

---

## Appendix E. Narrow floating-point formats (FP16, bfloat16, FP8, FP4)

The full narrow-format strategy — pre-2006 prior art analysis for FP16 (admit), bfloat16 (storage-only), FP8 (do not implement), FP4 (do not implement); patent landscape; revisit conditions; strategic positioning — is preserved verbatim in [archive/spec-v0.5.md Appendix F](archive/spec-v0.5.md). Summary:

- **FP16 (IEEE 754-2008 binary16):** Strong pre-2006 prior art (Hitachi HD61810 1982, Scott WIF 1991, 3dfx Voodoo 1995, SGI/OpenEXR 1997, NVIDIA Cg 2002). **Planned** for the next Tier 0 revision; format itself is unencumbered.
- **bfloat16:** Weak pre-2006 prior art; heavy Intel patent activity (US 20190079767A1, US 20230069000A1, US 12379927B2); active IPR2021-00155. **Storage-only via software shift/load idioms**; no native arithmetic.
- **FP8 (E4M3 / E5M2):** Zero pre-2006 prior art; 2022 NVIDIA/Intel/ARM specification; active EP4318224A1 conversion-instruction prosecution. **Not implemented.**
- **FP4 (MXFP4 / NVFP4):** Zero pre-2006 prior art; 2023 OCP MX specification; active NVIDIA/AMD prosecution. **Not implemented.**
- **INT8 / INT4 quantization** (TI TMS320 1985+, AT&T DSP): unencumbered. The recommended J-Core narrow-format path for ML inference, fully supported by Tier 1 (VMULSU, VUNPK4, VPACK, SIMDVS/SIMDVU).
