# J-Core SIMD Extension — Design Specification v0.5

**Status:** Draft, fifth design round (extended SIMD ISA: VCSR control register, multiple reduction modes, integer extract/insert, vector-indexed memory, immediate broadcast, SWIZZLE.I)
**Target:** J32 / J4 applications-class implementations
**Prerequisite ISA:** SuperH SH-2 base + SH-4 FPU (with FRn, XFn register banks and FPSCR)
**Backward compatibility:** v0.5 extends v0.4 with new instructions and renames the mask-enable bit from FPSCR.MK to VCSR.MKE (placing it in the new dedicated VCSR control register) and the toggle instruction from FMKCHG to VMKCHG. The v0.4 FMKCHG bit-pattern (`1111 1100 1111 1101`) is preserved and reassigned to VMKCHG, so v0.4 binaries continue to execute correctly on v0.5 hardware — only the assembly mnemonic changes. v0.3 and earlier are not supported in v0.5.
**Document scope:** architectural specification + implementation guidance for a 5-stage in-order pipeline

---

## Table of Contents

1. **Overview** (§1) — design goals, non-goals
2. **Architectural Model** (§2) — V0..V15 register file, lane organisation, reduction destinations, VCSR/FPSCR mode bits, architectural state
3. **Instruction Encoding** (§3) — opcode space, SIMDV/SIMDH prefixes, SWIZZLE context-sensitive encoding
4. **Execution Model** (§4) — block lifetime, atomicity, vertical/horizontal/SWIZZLE semantics, beat execution
5. **Governed Instructions** (§5) — integer ops, FP ops, reserved encodings, SIMD-control instructions (VMKCHG, LDS/STS P0/VCSR), vector memory and lane bridges (VLD.Q, VST.Q, VGATHER, VSCATTER, VMOV, VEXT/VINS, VLDI.Q, SWIZZLE.I)
6. **Exception Model** (§6) — interrupt deferral, slot-illegal, FPU exceptions
7. **Pipeline Implementation Guidance** (§7) — decode-stage shadow, four-beat sequencing, coprocessor port, dual-issue
8. **Reserved Encoding Space** (§8) — forward-compatibility budget
9. **Assembly Syntax and Examples** (§9) — six worked examples
10. **Open Questions** (§10) — v0.6+ deferrals

**Appendices:**
- A. Encoding Summary Table
- B. Decision Log (version evolution v0.1 → v0.5)
- C. References (pre-2006 design sources only)
- D. Prior Art Documentation (defensive citations for patent landscape; D.1 prefix-modal, D.2 predication, D.3 register file, D.4 patent-landscape notes, D.5 vector permutation, D.6 vector-indexed memory, D.7 non-temporal hints)
- E. Glossary
- F. Narrow-Format Strategy and Patent Avoidance (FP16 / bfloat16 / FP8 / FP4 analysis)

---

## 1. Overview

This extension defines a 128-bit SIMD facility for J-Core processors with a **dedicated SIMD register file** (V0..V15) separate from the SH-4 scalar FPU. The architecture follows pre-2006 prior art: Cray-1's V/S register separation (1976), Intel SSE's 128-bit XMM file (1999), and PowerPC AltiVec's dedicated 32-vector design (1996–1999). The v0.4 register file size (16 × 128 bits) is intermediate between SSE (8 × 128) and AltiVec (32 × 128).

The mechanism remains **prefix-modal**: a single 16-bit *prefix* instruction declares that the next *N* instructions are to be interpreted as SIMD operations, with a specified lane width and a horizontal or vertical mode. The governed instructions are ordinary SH-2 integer or SH-4 floating-point opcodes, reinterpreted in SIMD context to operate on V0..V15 instead of R0..R15 / FR0..FR15. This continues to produce SIMD-integer and SIMD-FP from a single mechanism without dedicated SIMD opcodes for each operation.

**Predication** (introduced in v0.3) is preserved unchanged: a persistent 16-bit P0 mask register, set by comparison instructions, applied to vector operations through the VCSR.MKE mode bit. The design follows the Cray-1 VL/VM separation model.

**Vector load/store** is now specified (v0.4) using the encoding space freed by removing FPU memory-access opcodes from SIMD context. VLD.Q and VST.Q with the standard SH-2 addressing modes provide direct memory access to V0..V15.

### 1.1 Design goals

1. **Real SIMD ISA, not a DSP extension.** v0.4 positions J-Core SIMD for applications-class workloads — autovectorisation targets, video/audio processing, light ML inference. The dedicated register file is the principal cost.
2. **Preserve SH-2 code density.** All new instructions remain 16 bits. The prefix is amortised across up to 4 governed instructions.
3. **Bounded pipeline complexity.** Single-issue in-order implementations require one new decode-stage shadow latch. SIMD prefix state is not saved on exception (atomic blocks, §6); the V0..V15 register file, P0, and VCSR.MKE are architectural and saved per normal context-switch rules.
4. **Reuse the existing ALU and FPU datapath** for SIMD compute. Only the register file is new.
5. **Forward compatibility.** Reserved opcode space inside SIMD blocks (now significantly expanded by the freed FPU memory opcodes) provides ample budget for future extensions.

### 1.2 Non-goals

- Out-of-order execution friendliness. The prefix-modal design is acceptable for J2/J32/J4 but is known to be hostile to OoO; a future J-core targeting OoO should consider a `vsetvl`-style architectural alternative or implement the prefix as decode-time micro-op cracking.
- Variable-length vectors. Vector width is fixed at 128 bits, matching the Intel SSE / PowerPC AltiVec width established in 1996–1999.
- Multiple predicate registers (Itanium-style). v0.4 specifies a single P0 register. Multiple predicates may be added in a future revision using reserved encoding space (§8) if real workloads require them.
- Minimal-area microcontroller deployment. Implementations needing the smallest possible silicon should target v0.3 (V0..V7 aliased to FR/XF). v0.4 trades roughly 5–15% additional area for a substantially cleaner architecture.

For a detailed comparison of v0.5 against earlier versions and the rationale for each architectural change, see Appendix B (Decision Log).

---

## 2. Architectural Model

### 2.1 SIMD register file

The SIMD register file is **dedicated**: 16 architectural registers V0..V15, each 128 bits wide, physically separate from the SH-4 scalar FPU register file (FR0..FR15 and XF0..XF15). Total new architectural state: **2048 bits**.

```
V0  (128 bits)    V1  (128 bits)    V2  (128 bits)    V3  (128 bits)
V4  (128 bits)    V5  (128 bits)    V6  (128 bits)    V7  (128 bits)
V8  (128 bits)    V9  (128 bits)    V10 (128 bits)    V11 (128 bits)
V12 (128 bits)    V13 (128 bits)    V14 (128 bits)    V15 (128 bits)
```

V0..V15 are named in SIMD context by reinterpreting the SH instruction's 4-bit register field (`nnnn` or `mmmm`) as a direct vector index 0..15. There is no multiple-of-4 constraint (the FIPR-style restriction from v0.3 is removed), and `FPSCR.FR` has no effect on SIMD register naming.

V0..V15 are saved and restored on context switch by the operating system, using the dedicated vector load/store instructions VLD.Q and VST.Q (§5.5). The OS-visible context grows by 256 bytes per thread (16 × 16 bytes). v0.4-aware kernels must include V0..V15 in their saved-context layout, immediately after FPSCR and P0.

**Relationship to scalar FPU.** FR0..FR15 (front bank) and XF0..XF15 (back bank) remain scalar FPU registers, unchanged from SH-4. They are used by ordinary SH-4 FPU instructions (FADD, FSUB, FMUL, FDIV, FMAC, FIPR, FTRV, FSTS, FLDS, FCNVSD, FCNVDS, and all FMOV variants) when these instructions appear *outside* a SIMD block. SH-4 FIPR and FTRV continue to operate on quartets of FR registers as 4-element FP32 vectors — they are a separate, legacy 4-element vector facility orthogonal to the v0.4 SIMD ISA.

**Data movement between scalar FPU and SIMD.** Two-instruction sequences VLNS+VEXTF.L / VLNS+VINSF.L and the integer variants VEXT.B/W/L/Q and VINS.B/W/L/Q (§5.6.4) move single lane values between an FRn or Rn register and a specified lane of a Vn register. For wider transfers, software stages data through memory using VLD/VST and FMOV.S / MOV.L.

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

Horizontal (reductive) SIMD operations write their scalar result to an existing architectural register **one type-class wider than the lane width**. Widening reductions preserve precision in long accumulation chains and prevent overflow in the common ML and DSP kernels (int8 → int32, FP16 → FP32). Each destination matches SH-4's existing scalar conventions for that wider type.

| Lane width *w* | Lane type | Destination | Destination type |
|---|---|---|---|
| 8  | integer | MACL | int16 or int32 (always fits in 32 bits) |
| 16 | integer | MACL + MACH pair | int32 / int64 (handles MULS.W widening: 8 × 32-bit products → ≤ 35-bit sum) |
| 32 | integer | MACL + MACH pair | int64 (non-widening MUL.L: 4 × 32-bit sum fits; widening DMULS.L: truncates at bit 64) |
| 64 | integer | MACL + MACH pair | int64 (truncates; software must guard against overflow) |
| 16 | FP (half) | FPUL | FP32 |
| 32 | FP (single) | DR0 = {FR0, FR1} | FP64 |
| 64 | FP (double) | DR0 = {FR0, FR1} | FP64 (no widening; FP128 unavailable) |

**No V-register restrictions.** Because V0..V15 are dedicated SIMD registers separate from FR0..FR15, the v0.3 V0-anchor restriction (which existed because DR0 = FR0+FR1 overlapped V0) no longer applies. Any V register may be used as a source or destination in any SIMDH variant. DR0 lives in the scalar FPU register file, V0 lives in the SIMD register file; they are physically separate.

**Chaining cost.** A horizontal reduction's result is immediately usable in same-type scalar arithmetic. To consume in a *narrower* type, software inserts a single conversion: `FCNVDS DR0, FPUL` for FP64 → FP32, or arithmetic narrowing for integer types via shifts. To consume the reduction back into a SIMD vector, use VINSF.L (for FP) or VINS.L (for integer) per §5.6.4 to place the scalar result into a specified lane of a V register.

### 2.4 Mode bits in FPSCR and VCSR

v0.5 introduces a dedicated SIMD control register, separating SIMD mode bits from scalar FPU state:

- **VCSR** (Vector Control and Status Register, 32 bits, new in v0.5): dedicated SIMD control register. Bit 0 = MKE (Mask Enable); bit 1 = IEE (IEEE-strict mode). Bits 2..31 reserved for future SIMD mode bits (saturation, rounding override, gather alignment policy, etc.). VCSR is preserved across exception entry/RTE and saved/restored by the OS as part of per-task context. Software accesses VCSR via `LDS Rm, VCSR` / `STS VCSR, Rn` (new sub-opcodes in the LDS/STS-to-system-register encoding rows) or via the dedicated `VMKCHG` toggle (§5.5).

- **VCSR.MKE** (bit 0): when set, governed SIMD operations apply P0 as a per-lane enable mask (§4.3, §4.4). When clear (default), all lanes are active. MKE has architectural effect only inside SIMD blocks — its value is read at governed-instruction decode. Software may set or clear MKE freely outside SIMD context; the value persists until next access.

- **VCSR.IEE** (bit 1, IEEE-strict mode): when set, governed FP operations follow IEEE 754 semantics for denormals and update FPSCR.FLAG bits OR-accumulated across lanes. When clear (default), governed FP operations flush denormals to zero and do not update FPSCR.FLAG. **In neither mode do SIMD FP operations deliver traps** — see §6.3 for the full FP exception model in SIMD context. IEE has architectural effect only inside SIMD blocks; outside, scalar FP follows the standard SH-4 FPU exception model unchanged.

Existing SH-4 FPSCR fields apply unchanged to scalar FPU code. For FP governed SIMD instructions, only some FPSCR fields apply:

- `FPSCR.FR` (bank) affects only scalar FPU operations, not SIMD register addressing.
- `FPSCR.PR` (precision) is overridden inside a SIMD block by the prefix's width field; the architectural FPSCR value is not modified.
- `FPSCR.SZ` (transfer size) is overridden similarly.
- `FPSCR.RM[1:0]` (rounding mode) applies normally to FP governed instructions (both modes of VCSR.IEE).
- `FPSCR.EN` (exception enable) bits are **ignored** by SIMD FP operations regardless of VCSR.IEE. SIMD never traps on FP exceptions.
- `FPSCR.CAUSE` bits are **not set** by SIMD FP operations (CAUSE supports trap-and-restart, which doesn't apply).
- `FPSCR.FLAG` bits are updated only when VCSR.IEE = 1, OR-accumulated across lanes.

**Naming rationale.** The v0.3/v0.4 placement of MK in FPSCR was a vestige of the v0.2/v0.3 alias-over-FPU register model. With dedicated V0..V15 registers in v0.4 and beyond, the SIMD mask-enable bit conceptually belongs to the SIMD ISA, not the scalar FPU. VCSR provides a natural home, following the Cray-1 model (1976) of a dedicated vector-control register (VL) separate from the scalar status register. The IEE bit is directly modelled on PowerPC AltiVec's "Java mode" bit in VSCR (1996), which selected between FTZ-default and IEEE-strict behavior with the same trap-free semantics in both modes.

### 2.5 Architectural and pipeline state

v0.4 introduces the following new architectural state, in addition to V0..V15 (§2.1):

- **P0** (16 bits, introduced v0.3): the SIMD predicate mask register. Each bit corresponds to one lane at the narrowest width (w = 8). At wider widths, lane *i* is enabled by P0[*i* · (*w*/8)] — i.e., the low bit of each *(w/8)*-bit group within P0. Bits not covered by the current width's lanes are preserved across width changes, allowing software to build composite masks under successive comparisons. P0 is saved and restored via dedicated `LDS Rm, P0` and `STS P0, Rn` instructions (§5.5).
- **VCSR.MKE** (1 bit, introduced v0.3): mode bit enabling per-lane masking.

The prefix-modal mechanism additionally requires the following **microarchitectural state**, none of which is architecturally visible or saved on exception (due to atomic block execution — see §6.1):

**SIMD block state** (set by SIMDV/SIMDH, cleared at block end):

- `SIMD_VAL` (1 bit): set when an open SIMD block is in flight.
- `SIMD_CNT[1:0]` (2 bits): remaining governed instructions in the open block, counted down from N − 1.
- `SIMD_W[1:0]` (2 bits): lane width of the current block.
- `SIMD_H` (1 bit): horizontal/vertical mode of the current block.
- `SIMD_RED[2:0]` (3 bits, v0.5): reduction operator (add/OR/AND/XOR/min/max/min-u/max-u) for horizontal blocks; ignored when SIMD_H = 0.

**Lane-select latch** (set by VLNS, cleared by VEXT/VINS, v0.5):

- `V_LANE_VALID` (1 bit): set when VLNS has armed a lane-select for the next VEXT/VINS.
- `V_LANE_REG[3:0]` (4 bits): V register index latched by VLNS.
- `V_LANE_IDX[3:0]` (4 bits): lane index latched by VLNS.

Note that v0.3's `SIMD_ANCHOR[2:0]` shadow latch is **removed in v0.4** — the prefix no longer carries an anchor field. Total decode-stage shadow state in v0.5: **18 bits** (6 bits SIMD block + 9 bits lane-select + 3 bits reduction mode), all microarchitectural.

The architectural state added by v0.5 versus a baseline SH-4: V0..V15 (16 × 128 = 2048 bits), P0 (16 bits), VCSR (32 bits, of which 2 bits — MKE and IEE — are currently defined). Total: **2096 new architectural bits**, an increase of approximately 5–15% of the J32 core area depending on implementation choices (flip-flop vs SRAM register file).

---

## 3. Instruction Encoding

### 3.1 Opcode space

All v0.2 SIMD encodings live in the **`1111 nnnn mmmm 1111` sub-row** (256 codepoints). This is the only sub-row consistently unallocated across SH-2 base, SH-4 FPU, and SH-4A FPU extensions. The remainder of the `1111 ……` block remains available for scalar SH-4 FPU operations, which v0.2 retains unchanged.

### 3.2 Prefix instructions (SIMDV, SIMDH)

The prefix encodes lane width, mode, and block length. The anchor field of v0.3 is removed in v0.4 — governed instructions name their source and destination V registers directly via their FRn/FRm fields (§4.3, §4.4). Five of the eight bits between the two fixed `1111` nibbles are used; the remaining three bits are reserved for future architectural extensions.

```
SIMDV<.NT>.w  #N      vertical (lane-parallel) prefix, optional non-temporal hint
SIMDH<op>.w   #N      horizontal (reductive) prefix with reduction operator

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
    - bit 0 (NT, Non-Temporal): when set, governed memory access instructions in the block use non-temporal cache hints (§5.6.0). Has no architectural effect on non-memory governed instructions.
    - bits 1, 2: reserved (must be 00); non-zero values raise slot-illegal. Reserved for v0.6 modifiers such as integer saturation mode.
  - When H = 1 (horizontal): selects the reduction operator per the table below.
- **NN** (bits 5:4): block length, encoded as N − 1, giving N ∈ {1, 2, 3, 4} governed instructions.

**Reduction operator table (H = 1):**

| `rrr` | Mnemonic suffix | Operator | Identity element (for masked-lane substitution) |
|---|---|---|---|
| 000 | `SIMDHA` (default, `SIMDH` synonym) | add | integer: 0; FP: +0.0 |
| 001 | `SIMDHO` | bitwise OR | 0 |
| 010 | `SIMDHN` | bitwise AND | all-ones |
| 011 | `SIMDHX` | bitwise XOR | 0 |
| 100 | `SIMDHMN` | min (signed for int, IEEE minNum for FP) | integer: INT_MAX; FP: +∞ |
| 101 | `SIMDHMX` | max (signed for int, IEEE maxNum for FP) | integer: INT_MIN; FP: −∞ |
| 110 | `SIMDHMNU` | min unsigned (integer only; slot-illegal for FP) | UINT_MAX |
| 111 | `SIMDHMXU` | max unsigned (integer only; slot-illegal for FP) | 0 |

For min/max reductions, the destination matches the input lane width without widening (e.g., int16 min → MACL holds an int16). FP min/max use IEEE 754-2008 `minNum`/`maxNum` semantics (NaN inputs return the non-NaN operand; both-NaN returns canonical NaN). The add reduction continues to widen per §2.3.

The block length cap of N = 4 matches the ARM Thumb-2 `IT` block precedent. Implementations targeting future out-of-order J-cores may choose to crack the prefix and its governed group into a single internal micro-operation at decode time.

The removal of the anchor field is the principal v0.3 → v0.4 encoding change. Each governed instruction is now self-contained — it names its operands through its own Rn and Rm fields without inheriting context from the prefix beyond the (width, mode, reduction) configuration.

### 3.3 SWIZZLE (context-sensitive)

SWIZZLE has **no standalone encoding**. Inside an open SIMD block (`SIMD_VAL = 1`), the bit pattern `1111 xxxxxxxx 1111` is decoded as SWIZZLE rather than as a prefix; the prefix's width and mode are inherited from the open block's microarchitectural state.

```
SWIZZLE Vn, Vm            permute lanes of V<Rn> using V<Rm> as control vector;
                          lane width inherited from open SIMD block

Bit  | 15 14 13 12 | 11 10 9 8 | 7 6 5 4 | 3 2 1 0 |
     |  1  1  1  1 |  n n n n  |  m m m m |  1 1 1 1 |
     ─────────────────────────────────────────────────
        escape       Vn target  Vm control   escape
                     (V0..V15)  (V0..V15)
```

- **nnnn** (bits 11:8): destination/source vector V`<Rn>` (V0..V15)
- **mmmm** (bits 7:4): control vector V`<Rm>` (V0..V15), interpreted as packed lane indices per §4.5

A SWIZZLE consumes one of the N governed-instruction slots declared by the prefix exactly like any other governed instruction.

### 3.4 No FSWCHG required

v0.4 does not introduce any new mode-toggle helper instructions for SIMD configuration. Width and mode are encoded entirely in the prefix. (VMKCHG, introduced v0.3, toggles VCSR.MKE for predication and is unchanged in v0.4.)

---

## 4. Execution Model

### 4.1 Block lifetime

```
1. Prefix decoded:  SIMD_VAL ← 1, SIMD_CNT ← N − 1, SIMD_W ← ww, SIMD_H ← H.
2. Each governed instruction decoded:
     - decode table is the SIMD decode table (see §5)
     - operand fields Rn/Rm interpreted as V0..V15 indices
     - execute lane-wise according to SIMD_W and SIMD_H
     - on retire: if SIMD_CNT == 0, SIMD_VAL ← 0; else SIMD_CNT ← SIMD_CNT − 1
3. Block terminates when N governed instructions have retired.
```

### 4.2 Atomicity

**SIMD blocks execute atomically with respect to external interrupts.** Interrupts arriving while `SIMD_VAL = 1` are held pending and dispatched only after the block has retired its final governed instruction. Consequences:

- No SIMD state (`SIMD_VAL`, `SIMD_CNT`, `SIMD_W`, `SIMD_H`) is ever architecturally visible to an exception handler.
- No additions to SR are required.
- RTE returning from any exception always lands at a non-SIMD instruction boundary.

The interrupt latency cost is bounded. Worst case: N = 4 governed instructions × 4 beats per instruction (at the narrowest lane width on a single 32-bit ALU implementation) = 16 cycles. At 50 MHz this is 320 ns. The latency is statically WCET-analysable.

**Synchronous exceptions** (slot-illegal, FPU exceptions raised by a governed FP instruction, memory faults on a governed load/store) are not deferred — they are delivered at the point of the offending governed instruction. The block is abandoned; `SIMD_VAL`, `SIMD_CNT` are cleared. Software is responsible for retrying the block from its prefix if appropriate.

### 4.3 Vertical mode semantics

In vertical mode (`SIMD_H = 0`), a governed scalar instruction with operand pattern `op Rm, Rn` is interpreted as:

```
if VCSR.MKE == 0:                         ; unmasked
    for i in 0 .. (128/w − 1):
        V<Rn>.lane[i] ← V<Rn>.lane[i]  op  V<Rm>.lane[i]

else:                                      ; masked (VCSR.MKE == 1)
    for i in 0 .. (128/w − 1):
        if P0[i · (w/8)] == 1:            ; lane is "active"
            V<Rn>.lane[i] ← V<Rn>.lane[i]  op  V<Rm>.lane[i]
        else:                              ; lane is "inactive"
            V<Rn>.lane[i] ← V<Rn>.lane[i]   (unchanged)
```

where:

- **V`<Rn>`** is the destination/accumulator vector, named directly by the governed instruction's 4-bit Rn field (values 0..15 select V0..V15). No multiple-of-4 restriction; no FPSCR.FR bank switching.
- **V`<Rm>`** is the source vector, named directly by the governed instruction's 4-bit Rm field (values 0..15 select V0..V15).

The result of every lane is independent (no cross-lane carry, no cross-lane data movement). Carry chains in the ALU are broken at lane boundaries.

**FMAC special case.** SH-4's FMAC instruction is `FRn ← FR0 · FRm + FRn`, with FR0 as an implicit operand. In SIMD context, FMAC is reinterpreted as `V<Rn>[i] ← V0[i] · V<Rm>[i] + V<Rn>[i]` — V0 plays the role of the implicit multiplier vector, matching FR0's role in scalar FMAC. Software arranges its data layout so the broadcast multiplier (e.g., a coefficient vector) lives in V0.

### 4.4 Horizontal mode semantics

In horizontal mode (`SIMD_H = 1`):

1. **At prefix decode**, the destination (MAC pair, FPUL, or DR0 per §2.3) is **implicitly cleared to zero**. Software does not need to issue `CLRMAC`, `FLDI0`, or any other zeroing sequence before entering a SIMDH block.
2. **Each governed instruction** computes its per-lane operation, reduces across lanes by addition, and *accumulates* the reduction into the (already cleared, or partially accumulated) destination. Within a single block of N governed instructions, accumulation proceeds across them.
3. **When VCSR.MKE = 1**, masked lanes contribute the **additive identity (zero)** to the reduction rather than their computed value. This preserves the reduction count (and therefore the reduction tree structure) regardless of mask, making the result independent of which lanes are masked at the IEEE-rounding level for FP. Lanes are not "skipped"; they simply contribute zero.
4. **At block exit**, the destination holds the complete reduction result.

**Integer governed instructions** (destination = MAC pair, widened per §2.3):

```
at prefix decode:        MAC ← 0
for each governed insn:
    for i in 0 .. (128/w − 1):
        if VCSR.MKE == 0 or P0[i · (w/8)] == 1:
            t[i] ← V<Rn>.lane[i]  op  V<Rm>.lane[i]    ; per-lane op may widen (e.g., MULS.W)
        else:
            t[i] ← 0
    MAC ← MAC  +  reduce_add(t[0..(128/w − 1)])
```

**FP16 governed instructions** (destination = FPUL as FP32):

```
at prefix decode:        FPUL ← 0.0 (FP32)
for each governed insn:
    for i in 0 .. 7:
        if VCSR.MKE == 0 or P0[i · 2] == 1:
            t[i] ← convert_to_FP32(V<Rn>.lane[i]  op  V<Rm>.lane[i])
        else:
            t[i] ← +0.0
    FPUL ← FPUL  +  reduce_add(t[0..7])
```

**FP32 governed instructions** (destination = DR0 as FP64; no V-register restrictions in v0.4):

```
at prefix decode:        DR0 ← 0.0 (FP64)
for each governed insn:
    for i in 0 .. 3:
        if VCSR.MKE == 0 or P0[i · 4] == 1:
            t[i] ← convert_to_FP64(V<Rn>.lane[i]  op  V<Rm>.lane[i])
        else:
            t[i] ← +0.0
    DR0 ← DR0  +  reduce_add(t[0..3])
```

**FP64 governed instructions** (destination = DR0; no widening; no V-register restrictions in v0.4):

```
at prefix decode:        DR0 ← 0.0 (FP64)
for each governed insn:
    for i in 0 .. 1:
        if VCSR.MKE == 0 or P0[i · 8] == 1:
            t[i] ← V<Rn>.lane[i]  op  V<Rm>.lane[i]
        else:
            t[i] ← +0.0
    DR0 ← DR0  +  reduce_add(t[0..1])
```

**FMAC in horizontal mode.** Per the FMAC interpretation in §4.3, V0 plays the role of the implicit multiplier. In horizontal mode, governed FMAC computes:

```
t[i] ← V<Rn>.lane[i]  +  V0.lane[i] · V<Rm>.lane[i]   ; pre-add for accumulator parity with vertical
```

then reduces. In practice, software typically sets V`<Rn>` = 0 (via VLD.Q of an all-zero memory operand) when using horizontal FMAC so it behaves as a pure dot-product reduction. (Unlike v0.3, V0 may safely be the FMAC implicit operand here because DR0 lives in the scalar FPU register file and does not overlap V0.)

The identity-element substitution rule (masked → zero) ensures that the reduction tree shape does not depend on the mask, which keeps FP rounding deterministic given a fixed reduction order and avoids IEEE 754 propagation of NaN/Inf from masked lanes.

**Cross-block accumulation.** Each SIMDH block produces a complete reduction in its destination; the destination is not preserved across block entries. To accumulate a reduction longer than fits in one block (N × lanes_per_vector elements), software extracts the per-block result and explicitly combines, e.g.:

```
SIMDH.L  #4
FMUL     FR1, FR2
FMUL     FR3, FR4
FMUL     FR5, FR6
FMUL     FR7, FR8      ; first 16 FP32 products → DR0 (4 governed × 4 lanes)
FMOV     DR0, DR2      ; save partial sum

SIMDH.L  #4
FMUL     FR9,  FR10
FMUL     FR11, FR12
FMUL     FR13, FR14
FMUL     FR15, FR0     ; next 16 FP32 products → DR0 (freshly cleared)
FADD     DR2, DR0      ; combined partial sum
; ...
```

This costs one scalar FADD per cross-block boundary, which compilers can schedule freely. The benefit is that any SIMDH block read in isolation determines its destination's final value — no hidden coupling to prior code state.

For floating-point governed instructions, the reduction respects IEEE 754 rounding using `FPSCR.RM`. The reduction order is implementation-defined (tree vs. sequential), and software must not rely on a specific order for bit-exact FP results.

### 4.5 SWIZZLE semantics

SWIZZLE permutes the lanes of V`<Rn>` according to a control vector in V`<Rm>`. v0.4 simplifies the v0.3 dual-form SWIZZLE to a single register-controlled form, gaining a full 4-bit Vn target field and a full 4-bit Vm control source. Pattern-immediate swizzles in v0.3 were limited to 128 fixed patterns; v0.4 software materialises any required pattern as a control vector via VLD.Q (loading from a precomputed memory table) or arithmetic construction, then uses SWIZZLE Vn, Vm.

Lane width is inherited from the open block's `SIMD_W`. Encoding: `1111 nnnn mmmm 1111` inside a SIMD block — the same encoding sub-row as the v0.3 SWIZZLE, but the field interpretation simplifies.

```
SWIZZLE Vn, Vm    1111 nnnn mmmm 1111    (inside SIMD block only)
```

V`<Rm>` is interpreted as a packed array of lane indices. Each lane index occupies `ceil(log2(128/w))` bits, low-order first:

| Lane width | Lane index size | Lanes encoded in Vm |
|---|---|---|
| 8 bits  | 4 bits | 16 (all 128 bits of Vm) |
| 16 bits | 3 bits | 8 |
| 32 bits | 2 bits | 4 |
| 64 bits | 1 bit  | 2 |

Operation:

```
for i in 0..(128/w - 1):
    V<Rn>.lane[i] ← V<Rn>.lane[Vm-index[i]]
```

If a control index is out of range (≥ 128/w for the current width), the corresponding destination lane is set to zero. This follows the SH-4 FIPR convention (1998) for out-of-range vector accesses and matches the natural hardware behavior of a lane-multiplexer with index-range checking: out-of-range selects produce a forced-zero output rather than reading undefined data.

**Common pattern construction**:

- Broadcast lane K to all lanes: control vector = `[K, K, K, ..., K]`
- Reverse lanes: control vector = `[N-1, N-2, ..., 1, 0]` where N = 128/w
- Interleave low half of two vectors: requires two SWIZZLEs and a merge
- Rotate-left by K: control vector = `[K, K+1, ..., N-1, 0, 1, ..., K-1] mod N`

A standard library (`libsimd`) provides these as pre-computed memory tables loaded via VLD.Q before the SWIZZLE. Cost: typically one VLD.Q + one SWIZZLE = 2 instructions for any fixed permutation. This is one instruction more than v0.3's pattern-immediate form but eliminates the architecturally-defined pattern table and gives full Vm flexibility.

A future v0.5 may add VLDI.Q-style "load lane-index constant" instructions to fold the table load into a single instruction; for v0.4 the table-from-memory approach is sufficient. **v0.5 update:** the immediate-pattern SWIZZLE form is reintroduced as SWIZZLE.I (§5.6.6), occupying SH-2 MOV-with-displacement encoding space inside SIMD context, with a 4-bit pattern selector × 4-bit parameter field giving compact access to common permutations without requiring a memory-resident control table.

### 4.6 Lane beat execution (implementation guidance)

Implementations are encouraged to time-multiplex the existing 32-bit ALU over 4 cycles ("beats") per 128-bit governed instruction:

| Lane width | Lanes per beat (32-bit ALU) | Beats per governed instruction |
|---|---|---|
| 8  | 4 | 4 |
| 16 | 2 | 4 |
| 32 | 1 | 4 |
| 64 | 0.5 (2 beats per lane) | 8 |

Adjacent governed instructions may interleave their beats provided source/destination conflicts are honoured. On a single-ALU J32 implementation, beats are sequential. On a dual-issue J4, a second ALU may consume beats in parallel for distinct lane subsets, halving the per-instruction beat count.

This **beat-multiplexed execution** approach has prior art going back to the Cray-1 (1976) — multi-cycle execution of a single vector instruction on a narrow datapath is foundational vector-processor technique. The architectural specification does not mandate any particular beat schedule; the only architectural guarantee is the final lane-wise result. Implementations may choose sequential, partially-overlapping, or fully-overlapping beat execution.

---

## 5. Governed Instructions

When `SIMD_VAL = 1`, the decoder uses a SIMD-context decode table instead of the standard SH-2/SH-4 decode table. The SIMD decode table differs from the standard table only in the following ways:

1. **Lane-wise reinterpretation** of integer arithmetic and logic operations.
2. **Lane-wise reinterpretation** of SH-4 FPU compute operations.
3. **Reservation** of all control-flow, system, and PC-relative instructions as slot-illegal.
4. **Reinterpretation** of `1111 ……… 1111` as SWIZZLE (§3.3).

### 5.1 Integer SH-2 operations (permitted as governed)

The following SH-2 instructions are valid as governed and are lane-parallelised at the prefix's width:

| Encoding | Mnemonic | Lane operation |
|---|---|---|
| `0011 nnnn mmmm 1100` | ADD Rm,Rn | per-lane add |
| `0011 nnnn mmmm 1010` | SUB Rm,Rn | per-lane subtract |
| `0010 nnnn mmmm 1001` | AND Rm,Rn | per-lane AND |
| `0010 nnnn mmmm 1011` | OR  Rm,Rn | per-lane OR |
| `0010 nnnn mmmm 1010` | XOR Rm,Rn | per-lane XOR |
| `0110 nnnn mmmm 1011` | NEG Rm,Rn | per-lane negate |
| `0110 nnnn mmmm 0111` | NOT Rm,Rn | per-lane bitwise NOT |
| `0010 nnnn mmmm 1110` | MULU.W Rm,Rn | per-lane unsigned multiply (result width = 2w) |
| `0010 nnnn mmmm 1111` | MULS.W Rm,Rn | per-lane signed multiply |
| `0100 nnnn mmmm 1101` | SHLD Rm,Rn | per-lane dynamic logical shift |
| `0100 nnnn mmmm 1100` | SHAD Rm,Rn | per-lane dynamic arithmetic shift |
| `0011 nnnn mmmm 0000` | CMP/EQ Rm,Rn | per-lane equality test → writes P0 |
| `0011 nnnn mmmm 0011` | CMP/GE Rm,Rn | per-lane signed ≥ test → writes P0 |
| `0011 nnnn mmmm 0111` | CMP/GT Rm,Rn | per-lane signed > test → writes P0 |

Per-lane comparison results are written to the **P0 mask register** (§2.5):

```
for i in 0 .. (128/w − 1):
    P0[i · (w/8)] ← 1 if (V<Rn>.lane[i] CMP V<Rm>.lane[i]) else 0
```

Bits of P0 not covered by the current width's active lanes are preserved, so successive comparisons at different widths can build composite masks. The architectural T-bit is left undefined by SIMD-context comparisons (it is reserved; v0.2 implementations that wrote the AND-reduction of the mask to T are not invalidated, but software must not depend on the T-bit value after a SIMD-context comparison).

Comparison instructions never themselves apply the mask — they only generate it. Mask application is enabled by VCSR.MKE (§2.4, §4.3, §4.4) and is fully decoupled from comparison setup. This decoupling follows the Cray-1 model (1976): comparison-writes-VM and merge-reads-VM are separate instructions.

Multiply (MULU.W, MULS.W) at width 8 produces 16-bit lane results; at width 16, 32-bit results. The 128-bit destination vector pair is `(V<Rn>, V<Rn>+1)` in this case — the only governed instruction class that writes two vectors. The pair-write requires `Rn` ≠ 15 (since V16 does not exist); `Rn` = 15 with a widening multiply raises slot-illegal.

### 5.2 SH-4 FPU operations (permitted as governed)

The following SH-4 FPU instructions are valid as governed and are lane-parallelised:

| Encoding | Mnemonic | Lane operation |
|---|---|---|
| `1111 nnnn mmmm 0000` | FADD FRm,FRn | per-lane FP add |
| `1111 nnnn mmmm 0001` | FSUB FRm,FRn | per-lane FP subtract |
| `1111 nnnn mmmm 0010` | FMUL FRm,FRn | per-lane FP multiply |
| `1111 nnnn mmmm 0011` | FDIV FRm,FRn | per-lane FP divide |
| `1111 nnnn mmmm 0100` | FCMP/EQ FRm,FRn | per-lane FP equality → writes P0 |
| `1111 nnnn mmmm 0101` | FCMP/GT FRm,FRn | per-lane FP > → writes P0 |
| `1111 nnnn mmmm 1110` | FMAC FR0,FRm,FRn | per-lane fused multiply-add (V0 is the implicit third operand) |

FMAC is the most architecturally valuable: combined with horizontal mode, it gives a fused-multiply-accumulate dot product at FP32 (4 lanes) or FP16 (8 lanes, requires implementation of FPSCR.PR = half-precision extension).

For governed FP instructions, `SIMD_W` selects the operand precision:

- `ww = 10` (w = 32): IEEE 754 single precision (FP32), 4 lanes
- `ww = 11` (w = 64): IEEE 754 double precision (FP64), 2 lanes
- `ww = 01` (w = 16): IEEE 754 half precision (FP16), 8 lanes — *requires FP16 implementation; raise slot-illegal if unsupported*
- `ww = 00` (w = 8): undefined for FP governed instructions; raises slot-illegal

The architectural FPSCR.PR is overridden for the duration of the block and is *not* modified.

When the prefix is `SIMDH` (horizontal mode), the reduction widens by one type-class (per §2.3 and §4.4):

| Lane type | Lane width *w* | Destination | Destination type | Restriction |
|---|---|---|---|---|
| FP16 | 16 | FPUL | FP32 | none |
| FP32 | 32 | DR0 | FP64 | none (V0 ≠ DR0 in v0.4) |
| FP64 | 64 | DR0 | FP64 (no widening) | none (V0 ≠ DR0 in v0.4) |

Chaining cost back into scalar FP arithmetic:

- **FP16 → FP32**: one instruction (`FSTS FPUL, FRn`); the result is immediately a usable FP32 value.
- **FP32 → FP32**: two instructions (`FCNVDS DR0, FPUL; FSTS FPUL, FRn`); the widening to FP64 is paid back if the downstream consumer accepts FP64.
- **FP32 → FP64**: zero instructions; DR0 is already a usable FP64 operand.
- **FP64 → FP64**: zero instructions.

The FP32-in / FP32-out idiom pays one extra FCNVDS compared to a hypothetical non-widening variant, in exchange for an order-of-magnitude precision improvement in long dot-product chains (the principal use of horizontal mode). A non-widening SIMDH variant is reserved in the encoding space for future revisions if real workloads demand it (see §10).

### 5.3 Reserved inside SIMD block

The following SH-2 and SH-4 instructions are **reserved** as governed instructions in v0.4. Encountering them while `SIMD_VAL = 1` raises a slot-illegal exception. They are committed architecturally as reserved encoding space for future SIMD extensions.

**Control flow** (entire opcode rows):
- BRA, BSR (`1010 ………`, `1011 ………`) — 8192 codepoints reserved
- BT, BF, BT.S, BF.S (`1000 1xxx ………`) — 1024 codepoints reserved
- BRAF, BSRF, JMP, JSR, RTS, RTE (in `0000 ……` row)

**System and synchronisation:**
- TRAPA, SLEEP, LDC, STC, LDS, STS, LDTLB

**Cache and memory ordering:**
- PREF, OCBI, OCBP, OCBWB, MOVCA, ICBI, MOVUA

**PC-relative:**
- MOVA, MOV.W @(disp,PC),Rn, MOV.L @(disp,PC),Rn

**Memory access** (now redefined in v0.4 rather than reserved):
- Scalar `MOV.x` opcodes in `0001`, `0101`, `0110`, `1001`, `1101` rows are **repurposed inside SIMD blocks as vector load/store** (VLD.Q and VST.Q variants — see §5.5). v0.4 software uses these directly within blocks to populate or store V0..V15.
- SH-4 `FMOV.S` opcodes at `1111 nnnn mmmm 0110` through `1111 nnnn mmmm 1011` are **repurposed inside SIMD blocks as vector load/store and vector register move** (see §5.5). Outside SIMD blocks they retain their scalar FPU meaning unchanged.

**Encoding-space accounting.** v0.3's "vector load/store deferred to a future extension" item is **resolved** in v0.4 by repurposing the SH-2 MOV.x and SH-4 FMOV.S rows inside SIMD context. The freed encoding space relative to v0.3 is approximately 1500 codepoints (6 sub-rows of SH-4 FMOV.S variants no longer needed in SIMD context for FRn-as-V naming) plus the MOV.x rows.

**Implementation note:** for the slot-illegal exception, the implementation should report the offending instruction's PC and the prefix's PC (saved in a debug register) to aid diagnosis.

### 5.4 Decoded but undefined

A governed instruction whose encoding is neither in §5.1, §5.2, §5.3, nor §5.6 (e.g., MAC.W, MAC.L, DIV0S, DIV0U, DIV1, CAS.L, the J2 atomic primitives) is architecturally **undefined** in v0.4 and reserved for future use. Implementations *must* raise slot-illegal; they *may not* execute the scalar semantics silently.

### 5.5 SIMD-control instructions

Three instructions support predication and SIMD mode control. All are valid only *outside* a SIMD block (raise slot-illegal if encountered as governed instructions):

| Encoding | Mnemonic | Operation |
|---|---|---|
| `1111 1100 1111 1101` | VMKCHG | toggle VCSR.MKE: `VCSR.MKE ← ¬VCSR.MKE` (renamed from VMKCHG in v0.4) |
| `0100 nnnn 1000 1010` | LDS Rn, P0 | `P0 ← Rn[15:0]` (load mask from low 16 bits of Rn) |
| `0000 nnnn 1000 1010` | STS P0, Rn | `Rn ← zero_extend_32(P0)` (store mask to Rn) |
| `0100 nnnn 1001 1010` | LDS Rn, VCSR | `VCSR ← Rn` (load full SIMD control register) |
| `0000 nnnn 1001 1010` | STS VCSR, Rn | `Rn ← VCSR` (store full SIMD control register) |

**VMKCHG** preserves the v0.4 encoding bit-pattern (`1111 1100 1111 1101`) but renames the mnemonic to reflect that the affected bit lives in VCSR rather than FPSCR. v0.4 binaries that emitted VMKCHG remain bit-compatible; only the assembly mnemonic changes.

**LDS Rn, VCSR** and **STS VCSR, Rn** provide full-register access for context-switch save/restore and explicit mode configuration. They occupy previously-unused sub-opcodes in the SH-2 LDS/STS-to-system-register encoding rows.

P0 and VCSR are saved/restored on exception entry/RTE by OS-managed context switches. v0.5-aware OSes must include both in their saved-context layout, after FPSCR and immediately preceding V0..V15.

### 5.6 Vector memory and register-move instructions

v0.5 specifies a complete set of vector memory, register-move, and lane-bridge instructions. The previous v0.4 placement of VEXT/VINS inside the SH-4 unary FPU row (which made them inside-SIMD-block-only) is corrected: these instructions now live in the SH-2 LDS/STS-style space and are valid **outside** SIMD blocks as standalone transfer operations. This matches their semantic role as register-file bridges rather than as lane-parallel SIMD ops.

#### 5.6.0 Memory access in SIMD context: the N=1 rule and the NT hint

A **memory access instruction** is one of VLD.Q, VST.Q, VGATHER.Q, or VSCATTER.Q. These are the instructions in this specification that can raise a memory exception (page fault, TLB miss on a software-MMU system, address-error misalignment, or bus error).

**Normative rule (N=1):** Within a SIMD block, a memory access instruction must be the **sole governed instruction**, with the enclosing prefix specifying `N = 1`. A SIMD block containing a memory access instruction alongside any other governed instruction (or with prefix `N > 1`) raises slot-illegal at decode (§6.2). Memory access instructions used outside any SIMD block are unrestricted; this rule applies only inside SIMD blocks.

**Normative rule (SIMDV only):** A memory access instruction governed by a SIMD block must use a **SIMDV** (vertical) prefix. A memory access instruction governed by a SIMDH (horizontal) prefix raises slot-illegal at decode. Horizontal reduction has no architectural interpretation for memory operations — load and reduce, or store and reduce, are not defined operations. SIMDH-prefixed blocks contain only arithmetic/logical governed instructions.

**Non-temporal hint (NT).** The SIMDV prefix's `rrr[0]` bit (§3.2) is the NT (Non-Temporal) flag. When set:

- **VLD.Q with NT:** the implementation may bypass cache allocation, reading the data through a streaming-friendly path. The cache state for the accessed line is unchanged. Useful for one-shot reads of large arrays that won't be reused.
- **VST.Q with NT:** the implementation may bypass cache allocation, writing the data through a write-combining buffer to memory directly. Useful for streaming writes that won't be re-read soon. Memory ordering with respect to other cores follows the standard SH-4 memory model unless the implementation provides additional synchronization (a SYNC or write-fence instruction may be needed before subsequent dependent reads).
- **VGATHER.Q with NT:** per-lane non-temporal load behavior.
- **VSCATTER.Q with NT:** per-lane non-temporal store behavior.

**The NT bit is an advisory hint, not a correctness requirement.** Implementations that do not provide a streaming-friendly cache path may treat NT-flagged operations as normal cached accesses; the architectural result is the same in either case. Implementations that *do* honor NT typically gain 1.5–2× sustained memory bandwidth on streaming workloads and avoid cache pollution that would evict data used by other concurrent workloads.

**The NT bit has no effect on non-memory governed instructions.** If a SIMDV.NT block governs (e.g.) FADD, the NT bit is architecturally a no-op. Implementations must not allow the NT bit to affect register-file state or arithmetic results in any way.

**Rationale for the N=1 rule.** The rule ensures that any memory exception raised inside a SIMD block occurs in a block containing no committed compute. This permits the **restart-from-prefix** fault-handling mechanism (§6.4): on memory exception, the saved PC points to the prefix instruction, the block state is cleared, the exception handler runs (TLB miss handler, page-fault handler, etc.), and RTE returns to the prefix, which re-executes and re-issues the memory access. The restart is correct because:

- The N=1 block contains only the memory access; no compute has committed
- The memory access itself is idempotent on retry (loads return the same data; stores write the same data from an unchanged source register; gathers and scatters with deterministic ordering re-execute their previously-completed lanes as no-ops modulo memory ordering)
- The prefix is a pure state-setting instruction with no architectural side effects beyond block-context establishment
- Post-increment / pre-decrement addressing modes (VLD.Q `@Rm+`, VST.Q `@-Rm`) follow the standard SH-4 convention of committing the register update only after the memory access succeeds, so a faulting access does not advance the address register

The N=1 rule is the architectural answer to the software-MMU problem: TLB miss handlers can be entirely scalar code that knows nothing about SIMD state, and the architecture is responsible for transparent restart. Without the rule, either microarchitectural write-buffering of all governed-instruction results would be required (expensive: roughly 4 × 128 bits per N=4 block plus scatter-destination buffers), or the architecture would have to give up support for software-managed MMUs entirely.

**Practical impact.** This rule formalizes the natural code pattern already used in §9.2, §9.3, §9.4, and §9.7: memory operations are issued either outside SIMD blocks or in dedicated N=1 blocks, and compute is grouped in separate compute-only blocks. The patterns are independent because memory access and compute have different cost profiles and natural sequencing. The architectural restriction does eliminate one theoretical optimisation — interleaving loads with compute to overlap memory latency — but in-order J-core implementations cannot exploit such overlap anyway, and the restriction does not bind out-of-order implementations because they can crack the prefix and the governed group into a single internal micro-operation as discussed in §10 item 8.

**Code density cost.** Memory-heavy SIMD code pays one extra prefix instruction per memory access compared to a hypothetical N=4 block containing 4 memory operations. For a loop performing `k` vector memory accesses and `j` compute operations, the instruction count is `k + 1 + ceil(j / 4)` prefixes plus the governed body, versus `1 + ceil((k + j) / 4)` for a hypothetical mixed-mode implementation. For balanced loops (`j ≈ k`), the overhead is approximately one extra instruction per 4 elements processed — manageable, and well-justified by the correctness benefit.

**Prior art for non-temporal hints.** The NT bit follows Intel SSE MOVNTPS / MOVNTPD (1999–2001), PowerPC AltiVec dst / dstt (1996–1999), and PowerPC dcbt / dcbtst (1993). All are pre-2006. See Appendix D.7.

#### 5.6.1 Vector load/store (basic forms)

| Encoding (inside SIMD block) | Mnemonic | Operation |
|---|---|---|
| `1111 nnnn mmmm 1000` | VLD.Q @Rm, Vn | `Vn ← memory[Rm..Rm+15]` (128-bit load) |
| `1111 nnnn mmmm 1001` | VLD.Q @Rm+, Vn | `Vn ← memory[Rm..Rm+15]; Rm ← Rm + 16` (post-increment) |
| `1111 nnnn mmmm 1010` | VST.Q Vn, @Rm | `memory[Rm..Rm+15] ← Vn` |
| `1111 nnnn mmmm 1011` | VST.Q Vn, @-Rm | `Rm ← Rm − 16; memory[Rm..Rm+15] ← Vn` (pre-decrement) |
| `1111 nnnn mmmm 0110` | VLD.Q @(R0,Rm), Vn | scalar-indexed load: address = R0 + Rm |
| `1111 nnnn mmmm 0111` | VST.Q Vn, @(R0,Rm) | scalar-indexed store |

These mirror SH-4's FMOV.S addressing modes. Address alignment: 16-byte alignment is required; misaligned addresses raise address-error exception.

VLD.Q and VST.Q **may be issued either inside or outside a SIMD block**. Outside a block, they execute as standalone vector memory operations. Inside a block, they count as one of the N governed instructions and execute with the block's beat schedule.

#### 5.6.2 Vector load/store with vector index (gather/scatter)

v0.5 adds **gather/scatter** operations, where the offset for each lane comes from a vector register rather than a scalar register. These provide the primitive for indirect indexing, hash-table walks, sparse-matrix operations, and lookup-table parallelism.

| Encoding (inside SIMD block) | Mnemonic | Operation |
|---|---|---|
| `0001 nnnn mmmm 0000` | VGATHER.Q @(R0,Vm), Vn | gather: `Vn.lane[i] ← memory[R0 + Vm.lane[i] · w/8]` |
| `0001 nnnn mmmm 0001` | VSCATTER.Q Vn, @(R0,Vm) | scatter: `memory[R0 + Vm.lane[i] · w/8] ← Vn.lane[i]` |

Where `w` is the open SIMD block's lane width. Vm is interpreted as a vector of per-lane offsets (in elements, not bytes — multiplied by `w/8` to form byte addresses). Each lane's address is `R0 + Vm.lane[i] · (w/8)`.

**Alignment requirements** for gather/scatter:
- At lane width `w`, each per-lane access must be naturally aligned to `w/8` bytes (the lane element size).
- Misaligned per-lane addresses raise address-error exception; the exception PC reports the gather/scatter instruction, and the offending lane index is implementation-defined (recommended: written to a debug register).

**Bounds and aliasing.** Gather and scatter may access memory in non-sequential order; the architecture does not guarantee any particular access ordering across lanes. Scatter is required to commit all writes (i.e., produce the architecturally-defined memory state) before retirement, but the *order* of writes is implementation-defined. Software relying on overlapping scatter destinations is undefined.

**Predication interaction.** Under VCSR.MKE = 1, masked lanes are skipped — no memory access occurs at masked lanes for gather (the destination V lane is unchanged) or scatter (no store is issued).

Gather/scatter occupy the SH-2 `0001 nnnn mmmm xxxx` row (otherwise MOV.L with displacement) inside SIMD context. Sub-opcodes `0010..1111` of this row are reserved for future gather/scatter variants (with stride, with bounds-checking, with explicit element-width override).

#### 5.6.3 Vector register move

| Encoding | Mnemonic | Operation |
|---|---|---|
| `1111 nnnn mmmm 1100` (inside SIMD) | VMOV Vm, Vn | `Vn ← Vm` (128-bit register copy) |

VMOV uses the SH-4 FMOV-register encoding inside SIMD context. Outside SIMD context the same encoding is the unchanged SH-4 `FMOV FRm, FRn` scalar instruction.

#### 5.6.4 Lane extract/insert (V ↔ scalar register bridges)

Bridging individual lanes between V registers and scalar registers (FRn or Rn) requires specifying three operands — V register, lane index, and scalar register — which cannot fit in a single 16-bit SH instruction at the narrowest lane width (w = 8 needs 4 bits of lane index alone). v0.5 resolves this with a **two-instruction sequence**:

1. **VLNS Vm, #lane** — *Vector Lane Select* prefix. Sets a microarchitectural lane-select latch (V_LANE_REG, V_LANE_IDX). 8 bits of operands fit comfortably in a 16-bit instruction.
2. **VEXT.B/W/L/Q Rn** or **VINS.B/W/L/Q Rm** (or the FP variants VEXTF.L, VINSF.L) — uses the latched (V_LANE_REG, V_LANE_IDX) as source/destination. 4 bits of operand fit comfortably.

The pair must be **adjacent and atomic**: any instruction encountered between VLNS and a following VEXT/VINS raises slot-illegal, and external interrupts are deferred between the two instructions (same atomicity rule as SIMD blocks per §6.1). This makes the lane-select latch microarchitectural — not architecturally visible, never saved on exception.

**Assembler syntax (single mnemonic):** The standard assembler accepts a single-mnemonic form and emits the VLNS prefix automatically:

```
VEXT.B  V5.7, R3       ; assembler emits:  VLNS V5, #7
                       ;                   VEXT.B R3
VINS.L  R8, V12.2      ; assembler emits:  VLNS V12, #2
                       ;                   VINS.L R8
VEXTF.L V0.3, FR9      ; assembler emits:  VLNS V0, #3
                       ;                   VEXTF.L FR9
```

**Instruction encoding:**

| Encoding | Mnemonic | Operation |
|---|---|---|
| `0100 mmmm llll 1011` | VLNS Vm, #lane | V_LANE_REG ← Vm; V_LANE_IDX ← lane; V_LANE_VALID ← 1 |
| `0100 nnnn 1000 1011` | VEXT.B Rn | `Rn ← sign_extend_32(V_LANE_REG.byte[V_LANE_IDX])` |
| `0100 nnnn 1001 1011` | VEXT.W Rn | `Rn ← sign_extend_32(V_LANE_REG.word[V_LANE_IDX])` |
| `0100 nnnn 1010 1011` | VEXT.L Rn | `Rn ← V_LANE_REG.long[V_LANE_IDX]` |
| `0100 nnnn 1011 1011` | VEXT.Q Rn, Rn+1 | `(Rn, Rn+1) ← V_LANE_REG.quad[V_LANE_IDX]` (low → Rn, high → Rn+1; `Rn` must be even) |
| `0000 nnnn 1000 1011` | VINS.B Rn | `V_LANE_REG.byte[V_LANE_IDX] ← Rn[7:0]` |
| `0000 nnnn 1001 1011` | VINS.W Rn | `V_LANE_REG.word[V_LANE_IDX] ← Rn[15:0]` |
| `0000 nnnn 1010 1011` | VINS.L Rn | `V_LANE_REG.long[V_LANE_IDX] ← Rn` |
| `0000 nnnn 1011 1011` | VINS.Q Rn, Rn+1 | `V_LANE_REG.quad[V_LANE_IDX] ← (Rn+1 :: Rn)` (high :: low; `Rn` must be even) |
| `0100 nnnn 1100 1011` | VEXTF.L FRn | `FRn ← V_LANE_REG.long[V_LANE_IDX]` (FP32 lane → scalar FRn) |
| `0000 nnnn 1100 1011` | VINSF.L FRn | `V_LANE_REG.long[V_LANE_IDX] ← FRn` |
| `0100 nnnn 1101..1111 1011` | (reserved) | reserved for VEXTU.B, VEXTU.W, VEXTF.Q (FP64 lane) in v0.6 |

After VEXT/VINS retires, V_LANE_VALID is cleared. VEXT/VINS encountered with V_LANE_VALID = 0 (no preceding VLNS) raises slot-illegal. VLNS not followed by VEXT/VINS (i.e., followed by any other instruction) also raises slot-illegal — this enforces the atomicity of the pair.

The lane-index field in VLNS is 4 bits, valid range depending on the operation width of the *following* VEXT/VINS:

- VEXT.B / VINS.B: lane ∈ 0..15 (all 4 bits used)
- VEXT.W / VINS.W: lane ∈ 0..7 (low 3 bits)
- VEXT.L / VINS.L / VEXTF.L / VINSF.L: lane ∈ 0..3 (low 2 bits)
- VEXT.Q / VINS.Q: lane ∈ 0..1 (low 1 bit)

VLNS itself does not encode the width — it's determined by the following VEXT/VINS opcode. Software is responsible for using a lane value in range; out-of-range lane indices are an architectural error (slot-illegal raised by the VEXT/VINS).

**Validity and ordering.** The VLNS+VEXT/VINS sequence is valid both inside and outside SIMD blocks. Inside a SIMD block, the pair counts as **two of the N governed instructions** (VLNS counts as one, VEXT/VINS counts as one). The pair-atomicity rule still applies, so a 1-instruction SIMD block cannot contain a VLNS+VEXT sequence — software uses N ≥ 2 for such blocks, or places the pair outside the SIMD block.

**Encoding placement rationale.** The VLNS+VEXT/VINS family lives in the SH-2 LDS/STS row family (`0x00` for STS-direction, `0x40` for LDS-direction, bottom nibble `1011` distinguishing from `1010` which holds the existing LDS/STS to system registers). The bottom nibble `1011` is otherwise sparsely populated in SH-2 (TAS.B at one slot; most slots unused), giving ample encoding room for VLNS, VEXT/VINS variants, and future VEXTU/VINSU.

#### 5.6.5 Vector immediate broadcast (VLDI.Q)

v0.5 introduces a broadcast-immediate instruction for loading constants directly into V registers without a memory access. The encoding occupies the SH-2 MOV-immediate row (`1110 nnnn iiiiiiii` = `MOV #imm, Rn`) inside SIMD context:

| Encoding (inside SIMD block) | Mnemonic | Operation |
|---|---|---|
| `1110 nnnn iiii iiii` | VLDI.Q #imm, Vn | broadcast: `Vn.lane[i] ← sign_extend_w(imm)` for all i |

The 8-bit immediate is sign-extended to the open block's lane width and broadcast to every lane. Useful for:

- All-zero / all-ones vector initialisation (`#0`, `#-1`)
- Common small constants (`#1`, `#2`, `#-1`) for arithmetic
- Broadcasting a saturation bound or threshold for compare-then-mask sequences

For 128-bit non-broadcast constants (e.g., specific permutation control vectors used by SWIZZLE), software uses a memory-resident constant table loaded via VLD.Q. The 8-bit immediate is sufficient for the broadcast-of-small-constant case but cannot express arbitrary 128-bit values.

Outside SIMD context, the `1110 nnnn iiiiiiii` row remains `MOV #imm, Rn` (scalar 8-bit immediate move).

#### 5.6.6 SWIZZLE with immediate pattern (SWIZZLE.I)

v0.5 reintroduces a pattern-immediate SWIZZLE form to avoid the v0.4 cost of memory-resident control tables for common permutations. SWIZZLE.I lives in the SH-2 MOV-with-displacement encoding (`0001 nnnn mmmm dddd` = `MOV.L Rm, @(disp,Rn)`) — but only sub-opcodes `0010..1111` of the bottom nibble are used (the `0000`/`0001` sub-opcodes are gather/scatter, §5.6.2).

| Encoding (inside SIMD block) | Mnemonic | Operation |
|---|---|---|
| `0001 nnnn pppp 0010` | SWIZZLE.I Vn, #pattern, #param=0 | apply pattern `pppp` to V`<Rn>` (parameter = 0) |
| `0001 nnnn pppp 0011..1111` | SWIZZLE.I Vn, #pattern, #param | apply pattern `pppp` with parameter from low nibble (1..15) |

**Pattern table** (`pppp` values):

| `pppp` | Pattern | Parameter meaning |
|---|---|---|
| 0000 | broadcast lane | parameter = source lane index |
| 0001 | reverse | parameter = granularity (0 = byte, 1 = word, 2 = long, 3 = quad) |
| 0010 | rotate-left by N lanes | parameter = N |
| 0011 | rotate-right by N lanes | parameter = N |
| 0100 | shift-left by N lanes (zero-fill) | parameter = N |
| 0101 | shift-right by N lanes (zero-fill, logical) | parameter = N |
| 0110 | interleave-low with self | parameter = lane-distance |
| 0111 | interleave-high with self | parameter = lane-distance |
| 1000..1111 | reserved | reserved |

The `Vn` field names the target register; the operation reads V`<Rn>`, applies the pattern, and writes back to V`<Rn>`. For patterns that need a second source (cross-vector interleave, etc.) the register-form `SWIZZLE Vn, Vm` (§4.5) remains the appropriate choice.

SWIZZLE.I is restricted to single-vector permutations of V`<Rn>` itself. For arbitrary cross-vector permutations, use the v0.4 register-controlled SWIZZLE.

---

## 6. Exception Model

### 6.1 Interrupt deferral

External interrupts arriving while `SIMD_VAL = 1` are held pending and delivered after the open block retires its final governed instruction. Similarly, interrupts arriving with `V_LANE_VALID = 1` (between VLNS and its following VEXT/VINS) are deferred until the VEXT/VINS retires. The implementation must:

1. Latch the interrupt request in the existing interrupt controller.
2. Not advance the interrupt acknowledgement protocol while `SIMD_VAL = 1` or `V_LANE_VALID = 1`.
3. Deliver the interrupt at the natural boundary — after the SIMD block, or after the VEXT/VINS that consumes the VLNS latch.

The worst-case combined interrupt latency is bounded: max SIMD block (16 cycles at 4 governed × 4 beats) + max VLNS+VEXT/VINS pair (2 cycles) = 18 cycles. At 50 MHz this is 360 ns. The latency remains statically WCET-analysable.

Implementations that wish to provide tighter interrupt latency may, as an implementation-defined extension, support **mid-block interrupt with replay**: on interrupt, the block is abandoned, the saved PC is set to the prefix's PC (not the next governed instruction), and the ISR is dispatched. Software is responsible for the block being idempotent or for explicit restart. This is permitted but not required by v0.5; software intending to rely on it must consult the implementation manual.

### 6.2 Slot-illegal exception

Slot-illegal exception is raised by:

- A reserved governed instruction (§5.3)
- A SWIZZLE with a reserved pattern selector (§4.5)
- A branch instruction outside a SIMD block whose target is determined at runtime to fall on a non-prefix instruction within the static extent of a prefix block (this can only be detected by software analysis; the architecture defines the behaviour as undefined and recommends slot-illegal on best-effort detection)
- An attempt to enter a SIMD block via any path other than fall-through from the prefix instruction
- A VEXT/VINS instruction encountered with `V_LANE_VALID = 0` (no preceding VLNS in the immediately-prior slot)
- Any instruction other than VEXT/VINS encountered with `V_LANE_VALID = 1` (a VLNS prefix not followed by its consuming instruction)
- A prefix `rrr` field non-zero for vertical mode in a position other than the NT bit (`SIMDV.w` with `rrr[1:2] ≠ 00`); the NT bit (`rrr[0]`) is permitted
- A memory access instruction (VLD.Q, VST.Q, VGATHER.Q, VSCATTER.Q) encountered as a governed instruction in a SIMD block where the prefix specifies `N > 1`, or where the memory access is not the only governed instruction (see §5.6.0, the N=1 memory access rule)
- A memory access instruction encountered as a governed instruction in a **SIMDH** (horizontal) prefixed block; memory access must use SIMDV prefix only (see §5.6.0)

The slot-illegal exception vector and stack frame format are unchanged from SH-2; the SR pushed has `SIMD_VAL = 0` and `V_LANE_VALID = 0` by definition (both microarchitectural latches are zero at all exception boundaries).

### 6.3 FP exception handling in SIMD context

SH-4 scalar FP instructions follow the standard IEEE 754 exception model with `FPSCR.EN`-controlled trapping. SIMD-context FP operations follow a different, simpler model with two architectural modes selected by VCSR.IEE. **Crucially, SIMD FP operations never deliver traps**, regardless of VCSR.IEE or FPSCR.EN settings. Software requiring IEEE-754-compliant trapping behavior must use scalar FP for the affected operations.

**Default mode (VCSR.IEE = 0):**

- All SIMD FP operations are non-trapping. No FPU exception ever delivers a signal from SIMD context.
- Denormal inputs are flushed to ±0 before computation (input FTZ).
- Denormal outputs are flushed to ±0 before writeback (output FTZ).
- NaN and Inf inputs and outputs follow IEEE 754 propagation rules. These rules are essentially free — they fall out of the bit-pattern arithmetic without requiring exception infrastructure.
- FPSCR.FLAG bits are *not* updated by SIMD operations.
- FPSCR.EN bits are *ignored* by SIMD operations.
- FPSCR.CAUSE bits are *not* set by SIMD operations.

This mode is the cheapest to implement (no denormal hardware/microcode required) and matches the expectations of virtually all autovectorised code, DSP libraries, ML inference workloads, graphics, and audio code.

**IEEE-strict mode (VCSR.IEE = 1):**

- SIMD FP operations remain non-trapping. No FPU exception ever delivers a signal from SIMD context.
- Denormal inputs and outputs are handled per IEEE 754 gradual underflow. Implementations may use hardware support or microcode fallback; the performance impact is implementation-defined and may be substantial.
- NaN and Inf inputs and outputs follow IEEE 754.
- FPSCR.FLAG bits are OR-accumulated across lanes after each SIMD FP operation. FPSCR.FLAG.X is set to 1 if any lane in the operation raised exception X (Invalid, DivByZero, Overflow, Underflow, Inexact). Bits are sticky until explicitly cleared via `LDS Rn, FPSCR`.
- FPSCR.EN bits remain *ignored* by SIMD operations even in IEEE-strict mode.
- FPSCR.CAUSE bits are *not* set by SIMD operations.

This mode is for code that needs diagnostic information (i.e., to know whether any exception occurred in a region of vectorised code) and full IEEE denormal semantics, but does not require trap-and-restart precision.

**Conformance levels:**

- **Minimal implementations** may support only VCSR.IEE = 0. In this case, VCSR.IEE is hardwired to 0; writes attempting to set it are silently ignored, and reads return 0. The architectural feature register (TBD in v0.6) should advertise that only the default mode is supported.
- **Full implementations** support both modes.

**Software interaction with IEEE traps.** Software that requires precise FP traps (e.g., on Invalid Operation for debugging, or on Overflow for safety-critical compliance) must run the critical computation in scalar FP. The transition cost is two extra instructions per trap-required scalar operation: a VEXT.L or VEXTF.L to move the lane to a scalar register, the scalar FP op (which honors FPSCR.EN bits normally and may trap), then a VINS.L or VINSF.L to return the result. For the small fraction of code that requires precise traps, this overhead is acceptable.

**Linux/POSIX implications.** Standard C library functions interact with this model as follows:

- `feenableexcept(FE_INVALID | FE_DIVBYZERO | ...)` enables traps for scalar FP only. SIMD code emitted by autovectorisation will not trap, even with `feenableexcept` enabled. This is a deliberate architectural decision; the libc implementation should document it.
- `fetestexcept()` and `feclearexcept()` operate on FPSCR.FLAG and work correctly for SIMD code only when VCSR.IEE = 1.
- `fesetround()` operates on FPSCR.RM, which does apply to SIMD operations.
- No new signal types are needed. `SIGFPE` is never delivered from SIMD context. The kernel exception-vector layout is unchanged.

**Memory faults are unaffected.** This section concerns only IEEE 754 FP exceptions. Memory access faults raised by VLD.Q, VST.Q, VGATHER.Q, VSCATTER.Q (page fault, alignment fault, bus error) are delivered normally per the SH-4 memory exception model and are not affected by VCSR.IEE. See §6.4.

**Prior art and rationale.** The two-mode design follows PowerPC AltiVec's VSCR "Java mode" bit (1996): non-Java mode (default) flushed denormals and skipped FLAG updates for performance; Java mode provided IEEE-compliant semantics. Neither AltiVec mode delivered FP traps from SIMD context. The same trap-free SIMD-FP discipline is found in Intel SSE (1999, MXCSR-controlled with trap-disabled default) and Cray-1 (1976, sticky-flag-only semantics with no FP traps at all). The design is also consistent with the broader compiler convention: GCC and LLVM both default to `-fno-trapping-math` for vector code regardless of target architecture.

### 6.4 Memory exceptions in SIMD context

Memory accesses by VLD.Q, VST.Q, VGATHER.Q, and VSCATTER.Q can raise the standard SH-4 memory exceptions:

- **Address error** (misalignment): raised when the effective address does not meet the 16-byte alignment requirement for VLD.Q/VST.Q, or the lane-width alignment requirement for VGATHER.Q/VSCATTER.Q. RTE retries the instruction (which will fault again unless software has corrected the address).
- **TLB miss / page fault**: raised when the effective address is not currently mapped. Standard SH-4 page-fault handling applies; the kernel populates the TLB and RTE retries. Both hardware-walked and software-managed MMU implementations are supported.
- **Bus error**: raised for memory-system errors (e.g., DRAM ECC failure). Standard SH-4 handling.

For VLD.Q/VST.Q the effective address is single, so handling is straightforward. For VGATHER.Q/VSCATTER.Q the effective address differs per lane:

- The implementation raises an exception on the first faulting lane (in lane-index order). For VGATHER.Q, the target V register is left architecturally unchanged. For VSCATTER.Q, implementations should commit lane writes in lane-index order so that on retry, previously-committed lanes write the same data to the same addresses (idempotent) and the previously-faulting lane proceeds with the now-valid translation. Overlapping scatter destinations remain implementation-defined per §5.6.2.
- Implementations may optionally provide a debug register reporting which lane faulted; this is not architecturally required in v0.5 but recommended.

**Memory faults inside SIMD blocks: restart-from-prefix.** When a memory access instruction raises any of the above exceptions while executing as a governed instruction inside a SIMD block, the architecture guarantees correct restart via the **restart-from-prefix** mechanism:

1. The saved PC points to **the prefix instruction**, not to the offending memory access.
2. Block microarchitectural state (SIMD_VAL, SIMD_W, SIMD_H, SIMD_CNT, SIMD_RED) is cleared at fault delivery.
3. The exception handler runs in scalar context. The handler does not need to be aware of SIMD state because the architectural visible state is that of the program point immediately before the prefix.
4. RTE returns to the prefix, which re-executes and re-opens the block with identical configuration.
5. The memory access retries with the same operand values.

This restart is correct precisely because of the N=1 memory access rule (§5.6.0): the block contains only the memory access, with no committed compute to worry about. Loads are idempotent (re-reading the same address gives the same value). Stores re-write the same data from an unchanged source register. Gathers and scatters re-execute per-lane, with previously-completed lanes acting as no-ops modulo memory ordering (which is implementation-defined per §5.6.2).

Address-register side effects from post-increment / pre-decrement modes (`@Rm+`, `@-Rm`) follow the standard SH-4 convention of committing only after the memory access succeeds. A faulting access does not advance the address register, so on retry the register holds the same value as the original attempt.

**Software-MMU support.** The restart-from-prefix mechanism makes software-managed TLB systems work transparently with SIMD code. A TLB miss handler is purely scalar code that walks page tables, refills the TLB entry, and executes RTE. The handler need not save or restore any SIMD architectural state (V0..V15, P0, VCSR) — these are preserved across the trap by standard kernel ABI discipline. After RTE returns to the prefix, the SIMD block restarts and the memory access retries with the now-valid translation. From a software-MMU perspective, a SIMD memory access fault is architecturally indistinguishable from a scalar memory access fault.

**Memory faults outside SIMD blocks.** Memory access instructions used outside any SIMD block (VLD.Q, VST.Q without a preceding prefix; VLNS+VEXT/VINS does not access memory) follow the standard SH-4 fault model: saved PC points to the faulting instruction, RTE retries it. Block-restart logic does not apply because there is no block.

**Memory faults during VLNS+VEXT/VINS pairs.** The VLNS+VEXT/VINS pair does not access memory (only register-file transfers), so cannot raise memory exceptions. If a TLB miss occurred during the next instruction fetch *after* the pair, that is a fetch fault on a subsequent instruction, not on the pair, and is handled per standard SH-4 fault rules.

**Interaction with §6.1.** Memory faults are synchronous exceptions and bypass the interrupt-deferral mechanism of §6.1. The asynchronous-interrupt latency analysis remains correct: in pure compute-only blocks, the maximum execution time is 4 governed × 4 beats = 16 cycles, plus the VLNS+VEXT/VINS pair worst case = 18 cycles total. Memory-access blocks (necessarily N=1) execute in 1 governed-instruction time plus memory latency, which is implementation-dependent but bounded by the memory subsystem's longest path.

---

## 7. Pipeline Implementation Guidance

### 7.1 Decode-stage shadow latch

The prefix's effect must reach the decode of the *immediately following* instruction. On the 5-stage J32 pipeline (IF / ID / EX / MA / WB), this requires forwarding the prefix's decoded state from its own ID stage to the next instruction's ID stage in the next cycle.

```
cyc        1     2     3     4     5
prefix     IF    ID*   EX    MA    WB
gov-1            IF    ID**  EX0   ...
gov-2                  IF    ID    EX0  ...

ID* = prefix sets shadow latches SIMD_VAL, SIMD_W, SIMD_H, SIMD_CNT
ID** = gov-1 reads shadow latches, decodes via SIMD decode table
```

The shadow latch is a single set of 6 flip-flops in the ID stage. It is *not* architecturally visible (per §6.1).

### 7.2 Four-beat ALU sequencing

For each governed instruction, the EX stage is extended into 4 (or 8, for w = 64) sequential beats:

```
beat 0: ALU consumes lanes [0..k−1]
beat 1: ALU consumes lanes [k..2k−1]
beat 2: ALU consumes lanes [2k..3k−1]
beat 3: ALU consumes lanes [3k..4k−1]
```

where `k = 4 / (32/w)` for w ≤ 32 (or `k = 0.5` for w = 64, requiring 8 beats).

Carry chains are broken at lane boundaries within each beat using AND gates on the carry-out of each *w*-bit segment. The horizontal-mode reduction sums into an internal 64-bit accumulator that is written back to MACL/MACH at WB.

### 7.3 Coprocessor port sharing

The j-core coprocessor port (already used by the SH-4 FPU and the MMU in J3) is the natural attachment point for the SIMD execution unit. The unit shares:

- The FPU multiplier and adder for FP governed instructions.
- The FPU register file ports for SIMD register access.
- The integer ALU for integer governed instructions (the SIMD unit muxes lane width into the ALU's carry-break controls).

The swizzle crossbar is a new structure attached to the FPU register file's read ports; its area cost is approximately:

| Lane width | Crossbar size | Approximate gate count |
|---|---|---|
| 32 (4 lanes) | 4×4 of 32-bit buses | ≈500 gates |
| 16 (8 lanes) | 8×8 of 16-bit buses | ≈1000 gates |
| 8 (16 lanes) | 16×16 of 8-bit buses | ≈2000 gates |
| 64 (2 lanes) | trivial swap | ≈50 gates |

A single physical crossbar is sized for the worst case (16×16 at 8-bit width) and serves all widths.

### 7.4 J4 dual-issue considerations

On a future dual-issue J4, two governed instructions may execute in parallel provided:

1. They are both governed by the same prefix block (i.e., the prefix and N − 1 governed instructions have all reached ID).
2. They do not share a destination vector.
3. They do not violate beat scheduling (the second ALU consumes a different lane subset per beat).

The dual-issue scheduler must respect the prefix's atomicity: an interrupt may not be taken between the two simultaneously-issued governed instructions of a block, only after the entire block retires.

### 7.5 Non-temporal memory access handling

The NT bit on a SIMDV prefix (§3.2, §5.6.0) is an advisory hint that the governed memory access has no temporal locality. Implementations are not required to act on the hint; treating it as a normal cached access produces architecturally correct results in all cases. Implementations that do act on the hint have several design choices:

**Write-combining buffer for VST.Q.NT / VSCATTER.Q.NT:** Stores are queued in a small write-combining buffer (typically 64–256 bytes) that coalesces adjacent writes into full-cache-line bursts to memory, bypassing the L1 data cache entirely. On buffer full or explicit memory fence, the buffer flushes to memory. This pattern follows Intel SSE's MOVNTPS implementation lineage (1999) and matches the natural hardware structure of a streaming write pipeline. Trade-off: minimal silicon cost (a buffer plus a few state bits), but stores have weaker ordering with respect to subsequent dependent reads — software must use an explicit memory fence before reading data it just wrote with NT, if the read goes through the cache.

**Streaming cache way for VLD.Q.NT / VGATHER.Q.NT:** A small dedicated way of the L1 data cache (often called a "streaming buffer" or "scratch way") is reserved for non-temporal reads. Cache lines fetched for NT loads land in this way and are subject to first-in-first-out replacement, so they don't displace data in the regular cache ways. This protects the working set of cache-resident data from streaming-read pollution.

**Cache bypass:** The most aggressive option is to bypass the cache entirely for NT memory accesses, reading directly from main memory through a streaming-DMA-like channel. This yields maximum sustained bandwidth but pays the full memory latency on every NT access (no caching of frequently-touched lanes). Practical only for predictable strided or block-streaming workloads.

**Implementation guidance:** For a typical J32 deployment with a small L1 (16-32 KB), the write-combining-buffer approach for stores is the highest-value addition (it avoids the read-for-ownership traffic that would otherwise consume bandwidth on every streaming write). The streaming cache way for reads is lower-priority but useful for video processing and large-array sweeps. Cache bypass is rarely worth the additional logic for an in-order embedded core. Implementations may choose any subset of these options or none; the NT bit's "advisory" status means software can use it without coupling to a specific implementation.

**Documenting NT behavior.** Each implementation should document in its programmer's reference exactly what the NT bit does on that part (which of the options above are implemented), so that performance-critical software can target it precisely. The architecture specifies the hint; the implementation specifies the response.

---

## 8. Reserved Encoding Space (Forward-Compatibility)

The following encoding ranges are architecturally reserved inside SIMD blocks in v0.4. Future J-core revisions may define instructions in these ranges without breaking v0.4-compliant binaries.

| Reserved range (inside SIMD block) | Approx. codepoints | Anticipated use |
|---|---|---|
| BRA, BSR top nibbles `1010`/`1011` | 8192 | Future SIMD branch / predicated-block control |
| BT/BF top nibble `1000 1xxx` | 1024 | Per-lane conditional execution variants |
| LDC/STC/LDS/STS in `0100 ……` (minus the v0.3 P0 sub-opcodes) | ~240 | Additional SIMD configuration register access |
| MOV.x loads/stores in `0001` and `0101` rows | ~8192 | Vector load/store with stride, gather/scatter, alignment hints |
| MOVA, PC-relative in `1100 0111`, `1101 ……` | ~4352 | Vector immediate broadcast (VLDI.Q), PC-relative vector load |
| SH-4 FPU unary row `1111 nnnn xxxx 1101`, slots 8..15 (inside SIMD) | 8 slots × 16 V | Additional VEXT/VINS widths (FP16, FP64); VNEG / VABS |
| `1111 ... 1111` inside SIMD (after SWIZZLE) | already allocated | SWIZZLE Vn,Vm — only encoding in this sub-row inside-block |
| Prefix `rrr` reserved bits (8 codepoints × full prefix space) | ~512 | Saturation mode, signed/unsigned override, additional H/V variants |
| TRAPA, SLEEP | 257 | Debug, vector breakpoint |
| MAC.W, MAC.L, MULL, DMULS, DMULU in `0000 ……` and `0010 ……` | ~64 | Multi-issue MAC, extended-precision SIMD |
| CAS.L, DIV0S, DIV0U, DIV1 | ~16 | SIMD atomic operations, lane-wise division |

**v0.4 allocations (no longer reserved versus v0.3):**
- Vector load/store (VLD.Q, VST.Q): six sub-opcodes in the `1111 nnnn mmmm xxxx` row at `xxxx` = 0110, 0111, 1000, 1001, 1010, 1011 (the SH-4 FMOV.S memory-access variants inside SIMD context).
- Vector register move (VMOV): `1111 nnnn mmmm 1100` (the SH-4 FMOV register-move encoding inside SIMD context).
- VEXT/VINS at FP32: `1111 nnnn 00ll 1101` / `1111 nnnn 01ll 1101` (slots 0..7 of the SH-4 unary FPU row inside SIMD context).

**Total reserved: ≈22,000 architecturally-reserved 16-bit codepoints inside SIMD blocks** (down from v0.3's ≈30,000 by the ≈8,000 codepoints now allocated to v0.4 vector memory and bridge operations). Still ample headroom for incremental architectural growth.

---

## 9. Assembly Syntax and Examples

### 9.1 Syntax

The reference assembler accepts:

```
SIMDV.B  #N           ; vertical, 8-bit lanes, N=1..4 (no anchor in v0.4)
SIMDV.W  #N           ; vertical, 16-bit lanes
SIMDV.L  #N           ; vertical, 32-bit lanes
SIMDV.Q  #N           ; vertical, 64-bit lanes
SIMDH.B  #N           ; horizontal forms, same suffixes
...
SWIZZLE  Vn, Vm       ; inside SIMD block only

VLD.Q    @Rm, Vn      ; vector load (inside or outside block)
VLD.Q    @Rm+, Vn     ; post-increment
VLD.Q    @(R0,Rm), Vn ; indexed
VST.Q    Vn, @Rm      ; vector store
VST.Q    Vn, @-Rm     ; pre-decrement
VST.Q    Vn, @(R0,Rm) ; indexed

VMOV     Vm, Vn       ; vector register copy (inside block only)
VEXTF.L  Vm.lane, FRn ; FP32 lane → FRn (assembler emits VLNS+VEXTF.L pair)
VINSF.L  FRm, Vn.lane ; FRm → FP32 lane
VEXT.L   Vm.lane, Rn  ; integer lane → Rn (assembler-paired similarly)
VINS.L   Rm, Vn.lane  ; Rn → integer lane
VLDI.Q   #imm, Vn     ; broadcast immediate (inside block only)
SWIZZLE.I Vn, #pat, #param ; pattern-immediate swizzle (inside block only)

VMKCHG                ; toggle VCSR.MKE (predication enable)
LDS      Rn, P0       ; load P0 from low 16 bits of Rn
STS      P0, Rn       ; store P0 to Rn (zero-extended)
LDS      Rn, VCSR     ; load full VCSR register
STS      VCSR, Rn     ; store full VCSR register
```

`Vn` for *n* = 0..15 names a dedicated 128-bit SIMD register. Governed instructions inside a SIMD block use ordinary SH-2/SH-4 mnemonics with FRn (or Rn for integer ops) operands; the assembler reinterprets the operand field as a V register index in SIMD context.

The notation `Vn.lane` in extract/insert syntax (e.g., `VEXTF.L V5.2, FR3`) is a single-mnemonic shorthand that the assembler expands to the two-instruction `VLNS + VEXT/VINS` sequence (§5.6.4).

### 9.2 Example: 4×4 single-precision matrix-vector multiply

Multiply a 4×4 row-major matrix held in V0..V3 by a vector in V4. Each row's dot product writes to DR0 (FP32 lanes widened to an FP64 result per §2.3). The result is then narrowed via FCNVDS and inserted into a result vector V5 lane-by-lane using VINSF.L.

```
    VLD.Q    @R_mat,    V0          ; load matrix row 0
    VLD.Q    @(R_mat+16), V1        ; row 1
    VLD.Q    @(R_mat+32), V2        ; row 2
    VLD.Q    @(R_mat+48), V3        ; row 3
    VLD.Q    @R_vec,    V4          ; load multiplier vector

    ; --- row 0 ---
    SIMDH.L  #1                     ; implicit clear of DR0
    FMUL     FR4, FR0                ; V0 · V4, widened sum → DR0
    FCNVDS   DR0, FPUL              ; narrow FP64 → FP32 in FPUL
    FSTS     FPUL, FR6              ; FPUL → FR6 (scalar FPU temp)
    VINSF.L  FR6, V5.0              ; assembler emits: VLNS V5, #0; VINSF.L FR6
                                     ;                  V5.lane[0] ← FR6

    ; --- row 1 ---
    SIMDH.L  #1
    FMUL     FR4, FR1
    FCNVDS   DR0, FPUL
    FSTS     FPUL, FR6
    VINSF.L  FR6, V5.1

    ; --- rows 2 and 3 follow the same pattern ---
    SIMDH.L  #1
    FMUL     FR4, FR2
    FCNVDS   DR0, FPUL
    FSTS     FPUL, FR6
    VINSF.L  FR6, V5.2

    SIMDH.L  #1
    FMUL     FR4, FR3
    FCNVDS   DR0, FPUL
    FSTS     FPUL, FR6
    VINSF.L  FR6, V5.3

    VST.Q    V5, @R_result          ; store the 4-element FP32 result
```

Five assembly mnemonics per row (prefix + FMUL + FCNVDS + FSTS + VINSF.L). Since `VINSF.L FR6, V5.0` expands to the two-instruction `VLNS V5, #0; VINSF.L FR6` pair, this is six machine instructions per row, or 24 total for the four rows plus the load/store envelope. The result lands in a dedicated V register via the VINSF.L bridge rather than being scattered across FRn registers, which is the principal data-layout advantage over the v0.3 approach.

### 9.3 Example: 8-lane 16-bit dot product

Compute the dot product of two 8-element 16-bit integer vectors held in V0 and V1, with the widened sum landing in the MAC pair.

```
    SIMDH.W  #1
    MULS.W   R1, R0                ; V<Rn=0> * V<Rm=1>, lane-wise (int16 → int32);
                                   ; widened sum → MAC pair (implicitly cleared at prefix)
```

A single horizontal-mode `MULS.W` governed by a 1-instruction prefix replaces what would be ≈16 scalar instructions plus loop overhead. The MAC pair's 64-bit capacity comfortably holds the worst-case 8 × 32-bit-product sum (≈35 bits used).

### 9.4 Example: vertical SIMD-FP FMA loop

Element-wise `Y[i] = A[i] · X[i] + Y[i]` over 4 single-precision lanes per iteration, with the multiplier broadcast (A) in V0 (FMAC's implicit operand vector), the data X in V1, and the accumulator Y in V2.

```
loop:
    VLD.Q    @R_y, V2               ; load Y[i..i+3]
    VLD.Q    @R_x, V1               ; load X[i..i+3]
    ; V0 (A coefficients) preloaded outside the loop

    SIMDV.L  #1
    FMAC     FR1, FR2               ; V2 ← V0 · V1 + V2, lane-wise (FMAC uses V0 implicitly)

    VST.Q    V2, @R_y               ; store Y back
    ; advance pointers, branch
```

One FMAC inside a 1-instruction vertical prefix performs 4 fused multiply-adds per dispatch. On a 4-beat single-ALU J32, this is 4 cycles for 4 lane FMAs versus ≈16 cycles for scalar — a 4× speedup before considering reduced instruction-fetch bandwidth.

### 9.5 Example: predicated FP32 update

For each FP32 lane in V1, add the corresponding lane of V2 only where `V1[i] > 0`. Uses the comparison-writes-P0 path (§5.1), the VMKCHG toggle (§5.5), and the VCSR.MKE-gated vertical mode (§4.3).

```
    ; --- step 1: build the mask in P0 ---
    ; V_zero (V3) preloaded with all zeros
    SIMDV.L  #1
    FCMP/GT  FR3, FR1               ; P0[i·4] ← (V1[i] > 0) for i = 0..3

    ; --- step 2: enable masking ---
    VMKCHG                          ; VCSR.MKE ← 1

    ; --- step 3: predicated add ---
    SIMDV.L  #1
    FADD     FR2, FR1                ; V1[i] += V2[i] only where P0[i·4] = 1

    ; --- step 4: restore unmasked state ---
    VMKCHG                          ; VCSR.MKE ← 0
```

Five instructions for a per-lane-conditional update across 4 FP32 lanes (excluding the zero-vector preload outside the loop). The mask in P0 persists past `VMKCHG`, so subsequent unrelated SIMD code is unaffected by the residual mask until the next comparison overwrites it.

### 9.6 Example: horizontal reduction with masked lanes

Sum the positive FP32 lanes of V1 into DR0 (per the widening rule of §2.3). Masked lanes contribute zero to the reduction:

```
    ; V3 = all-zeros, V_one (V4) = all-1.0  (preloaded)
    SIMDV.L  #1
    FCMP/GT  FR3, FR1               ; P0[i·4] ← (V1[i] > 0)

    VMKCHG                          ; enable mask

    SIMDH.L  #1
    FMUL     FR4, FR1                ; t[i] = V1[i] · 1.0 if P0[i·4]=1 else 0
                                     ; sum → DR0

    VMKCHG                          ; disable mask
    ; DR0 (as FP64) holds the sum of positive lanes of V1
```

The `FMUL FR4, FR1` is the standard idiom for "use V1's lanes as values multiplied by ones"; under masking, only enabled lanes contribute non-zero values to the reduction.

### 9.7 Example: sparse vector dot product with VGATHER.Q

Compute `y = Σ x[i] · v[indices[i]]` for *i* = 0..*N* − 1, where `x` is a dense FP32 vector, `indices` is an array of int32 element-indices into the larger vector `v`, and the result `y` is a scalar FP32. This is the inner loop of CSR sparse-matrix-vector multiply, ubiquitous in scientific computing, graph algorithms (PageRank, BFS frontier expansion), and machine learning (sparse attention, embedding lookup).

```
; Inputs:
; R4 = x       (dense vector pointer, FP32 elements)
; R5 = indices (int32 index array)
; R6 = v       (base address of the indexed vector)
; R7 = N       (element count, assumed > 0 and multiple of 4 for the main loop)
; Output: FR3 = scalar FP32 result

    FLDI0   FR3                    ; running accumulator = 0.0
    MOV     R6, R0                 ; R0 = v base address (gather base, set once)

loop:
    ; --- Load 4 dense values and 4 indices ---
    VLD.Q   @R4+, V0                ; V0 = x[i..i+3]      (FP32 × 4)
    VLD.Q   @R5+, V1                ; V1 = indices[i..i+3] (int32 × 4)

    ; --- Gather: V2[k] = v[V1[k]] for k = 0..3 ---
    SIMDV.L #1                      ; FP32 lane width, vertical, 1 governed
    VGATHER.Q @(R0,V1), V2          ; per-lane addr = R0 + V1.lane[k] · 4

    ; --- Multiply lane-wise and reduce to FP64 in DR0 ---
    SIMDHA.L #1                     ; horizontal add, FP32 → FP64
    FMUL    FR2, FR0                ; V0 · V2, widened sum → DR0

    ; --- Accumulate partial sum into running scalar accumulator ---
    FCNVDS  DR0, FPUL               ; narrow FP64 → FP32
    FSTS    FPUL, FR1               ; FPUL → FR1 (scalar)
    FADD    FR1, FR3                ; FR3 += partial sum

    ; --- Loop control ---
    ADD     #-4, R7
    CMP/PL  R7
    BT      loop
```

**Mechanics:**

- `VLD.Q @R4+` and `VLD.Q @R5+` load 16 bytes of dense data and 16 bytes of indices, respectively, with post-increment of the source pointer.
- The `SIMDV.L #1` prefix opens a 1-instruction SIMD block at FP32 lane width. VGATHER.Q is the single governed instruction. The gather computes 4 per-lane addresses as `R0 + V1.lane[k] · 4` (the `· 4` is `w/8 = 32/8`, the FP32 element size) and reads 4 disjoint FP32 values from memory into V2.
- The `SIMDHA.L #1` prefix opens a 1-instruction horizontal-add block. The governed FMUL multiplies V0 (dense) by V2 (gathered) lane-wise and the widened sum lands in DR0. (At FP32 input width, SIMDHA widens to FP64 per §2.3.)
- The scalar FCNVDS / FSTS / FADD sequence narrows the partial sum back to FP32 and accumulates into FR3.

**Instruction count:** 11 machine instructions per iteration of 4 elements. The scalar-equivalent inner loop (4 × FLDS-from-indexed-address + 4 × FMUL + 3 × FADD + loop control) is approximately 26 instructions, so the SIMD version is ~2.4× denser. Throughput in cycles depends heavily on memory-system gather bandwidth — the 4 gathered loads issue in parallel from the cache or memory subsystem (subject to implementation), so wall-clock speedup is typically larger than the instruction-count reduction suggests when the indexed vector is cache-resident.

**Alignment requirements.** Each gathered FP32 lane address (`R0 + V1.lane[k] · 4`) must be 4-byte aligned. Since the indices are element-indices and the base R0 is 4-byte aligned, this is automatic for any well-formed input. Misaligned per-lane addresses raise address-error exception per §6.4 (architecturally aborts the gather; target V register unchanged).

**Tail handling (N not a multiple of 4).** For the final iteration when *N* mod 4 ≠ 0, software has two options:

1. **Pre-clamp the index array.** Set the unused tail lanes of the index buffer to 0 (or any safe in-range value). The gather will read those safe addresses but the corresponding products contribute zero to the reduction *only if* the dense vector x is also zeroed in those positions. The simplest pattern is to zero-pad both `x` and `indices` to a multiple of 4 at allocation time.

2. **Use predication.** Set P0 to enable only the active tail lanes and enter VCSR.MKE = 1 mode before the tail iteration:

   ```
       MOV     #0x11, R8           ; mask = 0b00010001
                                   ; (bit 0 enables FP32 lane 0; bit 4 enables FP32 lane 1)
       LDS     R8, P0
       VMKCHG                      ; VCSR.MKE: 0 → 1

       VLD.Q   @R4+, V0
       VLD.Q   @R5+, V1

       SIMDV.L #1                  ; gather: masked lanes skip memory access entirely
       VGATHER.Q @(R0,V1), V2      ; → no read at lanes 2,3, so bogus indices there are safe

       SIMDHA.L #1                 ; reduction: masked lanes contribute identity (0)
       FMUL    FR2, FR0

       FCNVDS  DR0, FPUL
       FSTS    FPUL, FR1
       FADD    FR1, FR3

       VMKCHG                      ; restore VCSR.MKE: 1 → 0
   ```

   The masked VGATHER.Q is the key safety property: out-of-range or uninitialised index values in masked lanes do not cause memory accesses (§5.6.2), so the tail iteration cannot fault on stale index data. This makes option 2 strictly safer than option 1 when the index buffer is not under software control (e.g., it came from an external library or a memory-mapped file).

**Hash-table lookup variant.** The same primitive (VGATHER.Q with a per-lane index) handles hash-table walks: V1 holds 4 hash-bucket indices, V2 = VGATHER picks up 4 bucket-head pointers in parallel, and subsequent SIMD comparisons (FCMP/EQ writing P0) identify matching keys. This is one of the cases where the persistent P0 mask register (§2.5) and the deliberate compare-from-apply decoupling (§4.3) pay off significantly: software builds up complex per-lane match conditions across multiple compares without committing to any particular control-flow shape.

**Lookup-table parallelism (SBOX-style).** For applications with a small lookup table that fits in a few cache lines — AES SubBytes, gamma correction, finite-field arithmetic — the same VGATHER.Q pattern with a small `R0` base and 8-bit lane indices (lane width 8 via SIMDV.B) gives parallel table lookup at 16 lanes per gather. This is the canonical fast-software-crypto and image-processing idiom.

---

## 10. Open Questions

The following are deferred to a future v0.6 revision after early implementation experience:

1. **Narrow floating-point formats.** v0.5 reserves `ww = 01` (16-bit) FP semantics as slot-illegal. v0.6 specifies **IEEE 754-2008 binary16 (FP16)** as the 16-bit FP lane format, citing pre-2006 prior art (Scott 1991, Hitachi 1982, 3dfx 1995). Other 16-bit-and-smaller FP formats — bfloat16, FP8 (E4M3 / E5M2), FP4 (E2M1 with MXFP4 / NVFP4 microscaling) — are *deliberately not supported* due to insufficient pre-2006 prior art and active patent prosecution by NVIDIA, Intel, ARM, and AMD covering both the formats and the standard conversion / arithmetic operations. Software requiring these formats should use the J-Core integer SIMD path with software-managed quantization (INT8 native, INT4 via shift-and-mask), which is unencumbered. See Appendix F for the full narrow-format strategy, prior-art landscape, patent analysis, and revisit conditions.

2. **Non-widening SIMDH variant.** v0.5 always widens additive horizontal reductions by one type-class (the new min/max/bitwise reductions in v0.5 do not widen). The FP32-in / FP32-out idiom for SIMDH-add pays one FCNVDS instruction for the conversion back. If real workloads show this dominates instruction-count in practice, a non-widening SIMDH-add variant can be added.

3. **Multiple predicate registers.** v0.5 specifies a single P0. P0..P3 or P0..P7 could be added in reserved encoding space if real workloads benefit.

4. **Saturation mode.** v0.5 uses the SIMDH prefix's `rrr` field as the reduction-mode selector, but the SIMDV prefix's `rrr` field remains reserved. A v0.6 saturation mode could occupy a sub-encoding of SIMDV `rrr`, gating saturating arithmetic on integer adds and multiplies.

5. **Unsigned extract variants.** v0.5 reserves but does not specify VEXTU.B and VEXTU.W (zero-extending extracts at sub-32-bit widths). These slot naturally into the reserved space in the VEXT row.

6. **FP64 lane extract/insert.** v0.5's VEXT.Q/VINS.Q operate on integer 64-bit lanes via Rn pairs. A VEXTF.Q / VINSF.Q for FP64 lanes (between V registers and DRn pairs) would simplify FP64 SIMD code; the encoding slot is reserved in the VEXT row.

7. **Mid-block interrupt with replay.** The implementation-defined relaxation in §6.1 should be promoted to architectural with precise semantics if any J-core licensee requires it.

8. **OoO migration path.** For a future OoO J-core, decode-time cracking of the prefix and its governed group into a single internal micro-operation should be architecturally documented to ensure binary forward-compatibility. Predication interacts with this: the persistent P0 register is microarchitecturally easier to rename than count-bounded predication block schemes.

---

## Appendix A. Encoding Summary Table

```
PREFIXES (outside SIMD block)
SIMDV<.NT>.w  #N       1111 0ww<rrr> NN 1111  ; SIMDV: rrr[0]=NT, rrr[1:2] reserved
SIMDH<r>.w  #N         1111 1ww<r>  NN 1111   ; SIMDH: rrr = reduction operator

SIMDV modifier-field allocation (rrr):
  rrr[0] = NT (Non-Temporal hint for memory access; advisory)
  rrr[1] = reserved (must = 0)
  rrr[2] = reserved (must = 0)

Reduction-operator field (rrr, SIMDH only):
  000 = add (default; sum / sigma)        100 = min (signed / IEEE minNum)
  001 = OR  (bitwise)                     101 = max (signed / IEEE maxNum)
  010 = AND (bitwise)                     110 = min unsigned (integer only)
  011 = XOR (bitwise)                     111 = max unsigned (integer only)

GOVERNED INSTRUCTIONS (inside SIMD block, SIMD_VAL=1)
- Integer SH-2 ops: ADD/SUB/AND/OR/XOR/NEG/NOT/MULS/MULU/SHAD/SHLD interpret
  Rn and Rm as V<n> and V<m> indices (V0..V15, no multiple-of-4 restriction)
- FP SH-4 ops: FADD/FSUB/FMUL/FDIV/FCMP/FMAC interpret FRn/FRm as V<n>/V<m>
- Comparisons (CMP/*, FCMP/*) write per-lane results to P0

SWIZZLE (inside SIMD block only)
SWIZZLE  Vn, Vm        1111 nnnn mmmm 1111    (register-controlled)
SWIZZLE.I Vn,#pat,#par 0001 nnnn pppp dddd    (immediate; dddd ∈ 0010..1111)

VECTOR MEMORY (basic addressing, inside SIMD block;
              outside-block bit pattern is SH-4 FMOV.S)
VLD.Q    @Rm, Vn       1111 nnnn mmmm 1000
VLD.Q    @Rm+, Vn      1111 nnnn mmmm 1001
VST.Q    Vn, @Rm       1111 nnnn mmmm 1010
VST.Q    Vn, @-Rm      1111 nnnn mmmm 1011
VLD.Q    @(R0,Rm), Vn  1111 nnnn mmmm 0110
VST.Q    Vn, @(R0,Rm)  1111 nnnn mmmm 0111

VECTOR MEMORY (vector-indexed gather/scatter, inside SIMD block only)
VGATHER.Q  @(R0,Vm), Vn  0001 nnnn mmmm 0000  ; per-lane addr = R0 + Vm.lane[i]·(w/8)
VSCATTER.Q Vn, @(R0,Vm)  0001 nnnn mmmm 0001

VECTOR REGISTER MOVE (inside SIMD block only)
VMOV     Vm, Vn        1111 nnnn mmmm 1100

VECTOR IMMEDIATE BROADCAST (inside SIMD block only)
VLDI.Q   #imm, Vn      1110 nnnn iiii iiii    ; broadcast 8-bit signed to all lanes

LANE EXTRACT/INSERT (two-instruction sequence; valid in or out of SIMD blocks)
VLNS Vm, #lane         0100 mmmm llll 1011    ; Vector Lane Select prefix
VEXT.B Rn              0100 nnnn 1000 1011    ; consumes VLNS latch
VEXT.W Rn              0100 nnnn 1001 1011
VEXT.L Rn              0100 nnnn 1010 1011
VEXT.Q Rn,Rn+1         0100 nnnn 1011 1011    ; Rn must be even
VEXTF.L FRn            0100 nnnn 1100 1011    ; FP32 lane → FRn
VINS.B Rn              0000 nnnn 1000 1011
VINS.W Rn              0000 nnnn 1001 1011
VINS.L Rn              0000 nnnn 1010 1011
VINS.Q Rn,Rn+1         0000 nnnn 1011 1011
VINSF.L FRn            0000 nnnn 1100 1011

PREDICATION AND SIMD CONTROL (outside SIMD block)
VMKCHG                 1111 1100 1111 1101    ; toggle VCSR.MKE
LDS Rn, P0             0100 nnnn 1000 1010
STS P0, Rn             0000 nnnn 1000 1010
LDS Rn, VCSR           0100 nnnn 1001 1010
STS VCSR, Rn           0000 nnnn 1001 1010

KEY:
  ww:   00=byte (FP16 illegal), 01=word/FP16, 10=long/FP32, 11=quad/FP64
  NN:   N−1, so 00=1, 01=2, 10=3, 11=4 governed instructions per block
  H/V:  0=vertical (lane-parallel), 1=horizontal (reduce to MAC/FPUL/DR0)
  nnnn,mmmm: 4-bit V register index (V0..V15) or FRn (FR0..FR15) or Rn (R0..R15)
  llll: 4-bit lane index (range depends on lane width — see §5.6.4)
  pppp: 4-bit SWIZZLE pattern selector (16 patterns)
  dddd: 4-bit pattern parameter
  iiii iiii: 8-bit signed immediate (sign-extended to lane width by VLDI.Q)
  VCSR.MKE: SIMD mask-enable mode bit (1 = apply P0)
  VCSR.IEE: IEEE-strict mode bit (1 = IEEE denormals + FLAG updates; 0 = FTZ, no FLAG)
  P0:       16-bit architectural mask register
  V0..V15:  dedicated 128-bit SIMD registers (16 × 128 = 2048 bits)
```

## Appendix B. Decision Log

### v0.1 → v0.2 deltas

- **Encoding moved to `1111 nnnn mmmm 1111` sub-row** to coexist with SH-4 FPU.
- **SWIZZLE made in-block-only**, sharing the prefix encoding via `SIMD_VAL`-based context-sensitive decode. Recovers V0..V7 + N=1..4 + 8-bit swizzle parameter.
- **Atomic block execution** adopted; SR is no longer modified by SIMD. Worst-case interrupt latency added: ≈16 cycles.
- **Control-flow and system instructions reserved**, not slot-illegal-only, inside SIMD blocks. Commits ≈30,000 codepoints as forward-compatibility budget.
- **SIMD register file aliased over FR0..FR15 + XF0..XF15** instead of introducing a new register file. Zero new physical registers.
- **SIMD-FP falls out of the same mechanism** at no incremental architectural cost.
- **N capped at 4** (not the original 8) matching the Thumb-2 IT block precedent and improving the migration path to potential future OoO implementations.
- **Horizontal-mode destinations are type-specific and widening**, matching SH-4 conventions for the wider type: int8→MACL, int16/int32→MAC pair, int64→MAC pair (truncates), FP16→FPUL (FP32), FP32→DR0 (FP64), FP64→DR0. Preserves precision in long accumulation chains and matches the int8→int32 ML inference idiom natively. V0-anchor restriction (FP32 and FP64 only) is the cost. No new architectural register additions.
- **SIMDH performs implicit-clear at prefix decode**; within-block governed instructions accumulate. Eliminates the per-block clear prelude (`CLRMAC` / `FLDI0+FLDS` / `FLDI0×2`) and the state-leakage footgun. Cross-block accumulation costs one explicit FADD/etc.

### v0.2 → v0.3 deltas

- **Predication added** via persistent mask register P0 (16-bit architectural) and mode bit VCSR.MKE. Comparison instructions inside SIMD blocks (CMP/EQ/GE/GT, FCMP/EQ/GT) now write P0 architecturally — replacing v0.2's "microarchitectural register, reserved" semantics. v0.2 binaries that used these comparisons inside SIMD blocks remain valid (they now produce a defined P0 value but only affect behaviour when VCSR.MKE = 1).
- **VMKCHG toggle instruction** added at `1111 1100 1111 1101`, paralleling SH-4's FRCHG/FSCHG/FPCHG conventions. Single-instruction enable/disable of mask application.
- **LDS Rn, P0** and **STS P0, Rn** added for context-switch save/restore and explicit mask construction.
- **Masking semantics are deliberately decoupled from the prefix** — the prefix carries no predication information. Predication is a global mode (VCSR.MKE) applied to whatever SIMD operations are in flight. This decoupling follows the Cray-1 VL/VM separation (1976) and is structurally distinct from ARM Helium's count-bounded VPT mechanism (see Appendix D).
- **Horizontal-mode masking** uses identity-element substitution (masked lanes contribute 0) rather than skip semantics, keeping the reduction tree shape mask-independent and FP rounding deterministic.
- **One new architectural register** (P0) and **one new FPSCR bit** (VCSR.MKE) added. No changes to SIMDV/SIMDH/SWIZZLE encodings. v0.2 implementations remain conformant (VCSR.MKE hardwired to 0).

### v0.3 → v0.4 deltas

- **Dedicated SIMD register file V0..V15 introduced.** 16 × 128 bits = 2048 new bits of architectural state. V0..V15 are physically and architecturally separate from FR0..FR15 + XF0..XF15 — the v0.2/v0.3 alias-over-FPU approach is abandoned. This is the principal v0.4 change and the source of all downstream simplifications.
- **Anchor field removed from SIMDV/SIMDH prefix.** The 3-bit anchor (`aaa`) is replaced by 3 reserved bits (`rrr`, must = 0). Each governed instruction now names its destination and source V registers independently via its own Rn and Rm fields. The prefix carries only (H/V, width, count) — no operand naming.
- **FRn field in SIMD context names V0..V15 directly** via the full 4-bit range. v0.3's FIPR-style multiple-of-4 constraint is removed. v0.3's FPSCR.FR bank-switching role for SIMD addressing is removed (FPSCR.FR continues to apply to scalar FPU instructions only).
- **V0 anchor restriction eliminated.** DR0 = FR0+FR1 lives in the scalar FPU register file; V0 lives in the SIMD register file; they are physically separate. Any V register may be used as source or destination in any SIMDH variant without restriction. FMAC works at all SIMDH widths.
- **Vector load/store specified.** VLD.Q and VST.Q with six addressing modes (`@Rm`, `@Rm+`, `@-Rm`, `@(R0,Rm)` and base+register-indexed variants) are defined, occupying the SH-4 FMOV.S encoding space within SIMD blocks. Outside SIMD blocks, the same opcodes retain their FMOV.S meaning. This resolves the v0.3 open question on vector load/store.
- **SWIZZLE simplified to single register-controlled form.** The v0.3 pattern-immediate variant (128 patterns) is dropped in favour of `SWIZZLE Vn, Vm` where Vm contains lane indices. Software materialises fixed patterns via VLD.Q from a memory table.
- **VMOV, VEXTRACT, VINSERT instructions added in v0.4.** VMOV provided 128-bit register-to-register copies. VEXTRACT and VINSERT bridged FP32 lanes between SIMD V registers and scalar FPU FRn registers, needed for consuming horizontal-reduction results (which land in DR0/FPUL) back into V registers. *(VEXTRACT/VINSERT were subsequently renamed and restructured in v0.5; see v0.4 → v0.5 deltas below.)*
- **FPU encoding space freed inside SIMD context.** The SH-4 FMOV.S memory-access variants (six sub-rows at `1111 nnnn mmmm 0110-1011`) and the unary FPU row (`1111 nnnn xxxx 1101`) no longer have scalar meaning inside SIMD blocks. Half of this space is allocated to v0.4 vector load/store; half is reserved for future v0.5+ extensions (VLDI.Q, additional VEXT/VINS widths, etc.).
- **ABI break: kernel context-switch code must save/restore V0..V15.** 256 bytes per thread added to the saved-context layout. Old kernels on v0.4 hardware silently corrupt SIMD state across context switches; OS coordination required.
- **Microarchitectural state reduced.** SIMD_ANCHOR (3 bits) removed; decode-stage shadow latches shrink from 9 bits (v0.3) to 6 bits (v0.4).
- **3 reserved prefix bits** (`rrr`) available for future architectural use. Candidates: saturation mode, signed/unsigned override, additional H/V variants.

The v0.4 changes are **not backward-compatible** with v0.3. Implementations may choose to support v0.3 (microcontroller-class, V0..V7 aliased), v0.4 (applications-class, V0..V15 dedicated), or both with a runtime mode bit. v0.4 software does not execute correctly on v0.3 hardware (FRn field interpretation differs in SIMD context, V8..V15 are unavailable on v0.3, the prefix anchor field is missing from v0.4 binaries).

### v0.4 → v0.5 deltas

- **VCSR introduced.** Dedicated 32-bit Vector Control and Status Register replaces the v0.4 placement of MK in FPSCR. VCSR.MKE (bit 0) is the mask-enable flag; VCSR.IEE (bit 1) is the IEEE-strict mode selector for SIMD FP. Bits 2..31 reserved for future SIMD mode bits. Architectural state grows by 32 bits.
- **FP exception model rewritten for SIMD context.** v0.4's §6.3 specified that SIMD FP instructions raise FPU exceptions per the standard SH-4 model, with immediate trap delivery and SIMD_VAL clearing. v0.5 abandons this in favor of a non-trapping two-mode design controlled by VCSR.IEE: default mode (IEE = 0) flushes denormals and skips FPSCR.FLAG updates entirely; IEEE-strict mode (IEE = 1) handles denormals per IEEE 754 and OR-accumulates FPSCR.FLAG across lanes. Neither mode delivers traps — FPSCR.EN bits are always ignored by SIMD FP operations. Software requiring precise FP traps must use scalar FP for the affected operations. The design follows PowerPC AltiVec (1996), Intel SSE (1999), and Cray-1 (1976), all of which used trap-free SIMD FP. Kernel impact is minimal: no new exception vector, no new signal type, no SIGFPE from SIMD context. Memory exceptions (VLD.Q/VST.Q/VGATHER/VSCATTER faults) are unaffected and follow the standard SH-4 memory exception model (§6.4).
- **FPSCR.MK renamed to VCSR.MKE; FMKCHG renamed to VMKCHG.** Bit-pattern of the toggle instruction (`1111 1100 1111 1101`) is preserved — only the mnemonic changes. Existing v0.4 binaries continue to execute correctly with assembler retargeting only.
- **Reduction operators expanded.** SIMDH prefix's reserved `rrr` field (v0.4) is now the reduction-operator selector: add, OR, AND, XOR, min (signed/unsigned), max (signed/unsigned). Eight reductions across integer and FP (with FP-illegal for unsigned variants). Each reduction has a defined identity element for masked-lane substitution.
- **Integer lane bridges added with two-instruction sequence.** v0.4's FP-only VEXT/VINS is replaced with a `VLNS Vm, #lane` + `VEXT.B/W/L/Q Rn` (or VINS, VEXTF.L, VINSF.L) pair. The configurator instruction (VLNS) sets a microarchitectural lane-select latch; the worker instruction (VEXT/VINS) consumes it. This stylistically parallels the prefix-modal mechanism used by SIMDV/SIMDH and solves the bit-counting problem at narrow lane widths (8-bit lanes need 4 bits of lane index, leaving no room for both V and R fields in a single 16-bit instruction). The pair is atomic w.r.t. interrupts and must be adjacent; any other instruction between VLNS and VEXT/VINS raises slot-illegal. Assembler hides this with single-mnemonic syntax (`VEXT.L V5.2, R3`). Available both inside and outside SIMD blocks. This fixes the v0.4 example bug where VINSERT was called outside a SIMD block.
- **VGATHER.Q and VSCATTER.Q added.** Vector-indexed memory access. The offset for each lane comes from a vector register (Vm) rather than a scalar register. Encoding occupies the SH-2 MOV.L with-displacement row (`0001 nnnn mmmm 00xx`) inside SIMD context. Masked lanes are skipped (no memory access). Provides the primitive for sparse arrays, hash tables, and lookup-table parallelism.
- **VLDI.Q broadcast-immediate added.** Loads an 8-bit signed immediate broadcast to all lanes of a V register. Encoding occupies the SH-2 MOV-immediate row (`1110 nnnn iiiiiiii`) inside SIMD context. Eliminates the need for memory-resident constant pools for common small constants.
- **SWIZZLE.I (pattern-immediate SWIZZLE) reintroduced.** v0.4 dropped the immediate form for encoding simplicity; v0.5 restores it in the SH-2 MOV.L with-displacement row (`0001 nnnn pppp 0010-1111`), giving 14 pattern × 16 parameter combinations. Common permutations (broadcast lane K, reverse, rotate by N, shift by N) no longer require a memory-resident control table.
- **Cross-block accumulation example fixed.** The v0.4 §4.4 example still showed the v0.3-style `SIMDH.L V1, #4` anchor syntax; v0.5 rewrites it to use the v0.4 no-anchor encoding.
- **N=1 memory access rule introduced (§5.6.0).** A memory access instruction (VLD.Q, VST.Q, VGATHER.Q, VSCATTER.Q) used inside a SIMD block must be the sole governed instruction (prefix specifies N=1). Mixing memory access with compute in the same block raises slot-illegal at decode (§6.2). This formalizes the natural code pattern already used in every example in §9 and enables the **restart-from-prefix** fault-handling mechanism (§6.4), which makes the architecture transparently compatible with software-managed-MMU systems. v0.4's fault model — which abandoned the block and saved PC pointing to the offending memory access — was unsound on software-MMU systems because the post-RTE re-decode of the memory access would lose the SIMD_VAL context required to interpret it correctly. v0.5 corrects this by guaranteeing that any in-block memory fault occurs in an N=1 block, so restart from the prefix is the architecturally correct recovery and no SIMD state needs to be saved across the trap. Practical code-density impact: roughly one extra prefix instruction per 4 memory accesses in memory-heavy loops, easily absorbed by the loop structure.
- **SIMDV-only restriction for in-block memory access.** A companion rule to N=1: memory access instructions governed by SIMDH (horizontal/reductive) prefix raise slot-illegal. SIMDH has no semantic interpretation for memory operations, and the restriction frees SIMDV's `rrr` field bits for memory-related modifiers (currently the NT bit; future v0.6 modifiers).
- **NT (Non-Temporal) hint added to SIMDV prefix (§3.2, §5.6.0).** SIMDV's `rrr[0]` bit, previously reserved, now encodes a non-temporal cache hint for the governed memory access. When set, the implementation may bypass cache allocation for the access (e.g., write-combining buffer for stores, streaming cache way for loads, or full cache bypass). The hint is advisory: implementations without streaming-friendly cache pathways may ignore it. Prior art: Intel SSE MOVNTPS (1999), PowerPC AltiVec dst/dstt (1996-1999), PowerPC dcbt (1993). See Appendix D.7. Bits `rrr[1:2]` remain reserved for v0.6 modifiers (likely saturation mode or rounding-mode override).
- **Several v0.4 open-question items resolved.** Vector load/store with vector indexing (gather/scatter), VLDI.Q immediate construction, and SWIZZLE immediate forms are all specified in v0.5.

v0.4 binaries execute correctly on v0.5 hardware (with assembler mnemonic retargeting for FMKCHG → VMKCHG); v0.5 binaries that use any v0.5-new instruction (VLDI.Q, VGATHER/VSCATTER, SWIZZLE.I, integer extract/insert, non-add reductions) do not execute on v0.4 hardware.

## Appendix C. References

**Primary architectural references (pre-2006, used as design sources):**

- SuperH SH-2 Programming Manual, Hitachi, ~1992. (Defines the base 16-bit instruction encoding and the ALU operations reinterpreted lane-wise in this specification.)
- SuperH SH-4 Software Manual, Hitachi/Renesas (doc. rej09b0003), 1998. (Defines FRn, XFn register banks, FPSCR, FIPR, FTRV — the FPU register file and 4-element-vector idioms inherited by this specification's FP path.)
- SuperH SH-4A Software Manual, Renesas, ~2003. (Defines FRCHG, FSCHG, FPCHG, FSCA — the mode-toggle precedents for VMKCHG.)
- ARM Architecture Reference Manual, Thumb-2 Supplement, 2003. (Defines the IT block: a single 16-bit instruction governing the conditional execution of the next 1–4 instructions — the direct precedent for this specification's prefix-modal mechanism.)
- Cray-1 Hardware Reference Manual (HR-0004), Cray Research Inc., 1976. PDF at https://bitsavers.trailing-edge.com/pdf/cray/CRAY-1/ ; HTML transcription of relevant chapters at http://ed-thelen.org/comp-hist/CRAY-1-HardRefMan/CRAY-1-HRM.html. (Defines VL and VM registers — the predecessors of this specification's persistent mask register P0.)
- Hitachi SH-DSP Programming Manual, 1996. (Defines repeat-block state and DSP parallel-instruction conventions — the SH-family precedent for "previously-set state governs subsequent instructions.")
- Intel IA-64 Architecture Software Developer's Manual, Volumes 1–3, 1999–2000. (Defines the 64-element predicate register file and the bundle-template mechanism — predecessors for the decoupled compare-from-apply structure used in this specification's predication.)
- HP PA-RISC 1.0 Architecture and Instruction Reference Manual, Hewlett-Packard, 1986. (Defines instruction nullification — the per-instruction predication precedent.)
- TMS320C6000 CPU and Instruction Set Reference Guide (SPRU189), Texas Instruments, 1997. (Defines per-instruction VLIW predication via condition registers.)
- AltiVec Technology Programming Environments Manual, Motorola Document MPCFPE32B/AD, 1999. (Defines 32 × 128-bit dedicated SIMD registers — direct precedent for this specification's V0..V15 register file model. Chapter 6 defines vec_perm / VPERM — direct precedent for `SWIZZLE Vn, Vm`.)
- Intel Architecture Software Developer's Manual, Volume 2: Instruction Set Reference, 1999 edition (defining SSE). (Defines 8 × 128-bit dedicated XMM registers — direct precedent for the 128-bit-wide SIMD-register-separate-from-FPU model. Also defines PSHUFW, SHUFPS — immediate-controlled lane shuffle, precedent for `SWIZZLE.I`.)
- Cray X-MP Hardware Reference Manual, Cray Research Inc., 1982. (Defines arbitrary-index GATHER and SCATTER instructions — direct foundational prior art for `VGATHER.Q` / `VSCATTER.Q`. The introduction of arbitrary-index gather/scatter eliminating the Cray-1 constant-stride restriction.)
- Lee, R.B., "Subword Parallelism with MAX-2," IEEE Micro, July/August 1996. (Defines PA-RISC MAX-2 PERMH — immediate-controlled halfword permute, precedent for `SWIZZLE.I`.)
- Peleg, A., and Weiser, U., "MMX Technology Extension to the Intel Architecture," IEEE Micro, July/August 1996. (Defines MMX PSHUFW — canonical immediate-controlled word shuffle, precedent for `SWIZZLE.I`.)
- Phillip, M., et al., "AltiVec Technology: Accelerating Media Processing Across the Spectrum," Proceedings of Hot Chips 10, 1998. (Architectural overview of AltiVec including VPERM.)
- Tremblay, M., et al., "VIS Speeds New Media Processing," IEEE Micro, July/August 1996. (Defines Sun VIS BSHUFFLE/BMASK — register-controlled byte shuffle.)
- Espasa, R., and Valero, M., "Vector Architectures: Past, Present and Future," Proceedings of Supercomputing '98. (Survey of vector architecture lineage from CDC STAR-100 onward, including gather/scatter history.)
- PowerPC Architecture Book II Programming Environments Manual, IBM/Motorola, 1993. (Defines dcbt / dcbtst — the foundational cache-hint instructions; precedent for the NT bit.)
- MIPS64 Architecture for Programmers, Volume II: The MIPS64 Instruction Set, MIPS Technologies, 1996. (Defines PREF / PREFX — non-temporal prefetch with hint encoding.)
- SPARC V9 Architecture Manual, Sun Microsystems, 1994. (Defines PREFETCH variants distinguishing temporal vs non-temporal access patterns.)

**Project artifacts (not used as design inspiration):**

- j-core CPU repository, https://github.com/j-core/jcore-cpu — the implementation target.
- j-core roadmap, https://j-core.org/roadmap.html — the project's stated long-term goals, including SIMD as a planned extension.

**Note on cutoff.** All design inspirations cited in this specification predate May 2006 by at least one year, with most predating it by 20–50 years. This is deliberate: the J-Core SIMD design is built exclusively on prior art whose 20-year patent terms have expired or whose architectural concepts substantially predate any current ARM SIMD patent priority dates (2016 onward). Modern SIMD architectures (ARM Helium, ARM SVE, RISC-V V, AVX-512, etc.) are not cited as design inspiration. Where this specification references such architectures (Appendix D.4, D.5, D.6), it does so only to document the patent landscape being deliberately avoided. Appendices D.5 and D.6 specifically document the strong pre-2006 prior art for vector permutation and vector-indexed memory access primitives, both predating the relevant Intel and ARM patent priorities by 10–50 years.

## Appendix D. Prior Art Documentation

This appendix documents prior art relevant to the design choices in this specification, particularly the prefix-modal mechanism (§3.2), the predication mechanism (§2.5, §4.3, §4.4, §5.5), and the register-file aliasing (§2.1). All cited works predate the relevant ARM patent priority dates by 10–50 years and are included to (a) document the architectural provenance of the design and (b) provide defensive prior-art references for any future patent dispute.

### D.1 Prior Art for the Prefix-Modal Mechanism (§3.2)

The pattern "a single instruction declares behaviour for a fixed-length window of subsequent instructions" is well-established prior art, predating any ARM Helium / MVE patent filings (priority dates 2016 onward).

**ARM Thumb-2 IT (If-Then) block — ARMv6T2, 2003.** The IT instruction is a 16-bit Thumb-2 opcode that specifies a 4-bit condition and a 4-bit mask, governing the condition (or its inverse) for each of the next 1–4 instructions. Each governed instruction uses ordinary opcode encoding but executes conditionally based on the IT state held in the ITSTATE field of CPSR/xPSR. The ITSTATE shifts as each governed instruction retires. This is the direct architectural precedent for the prefix-modal mechanism used in §3.2, demonstrated 13 years before ARM's vector-predication patent filing. *Reference:* ARM Architecture Reference Manual, Thumb-2 Supplement, 2003–2005.

**IA-64 / Itanium template + stop bits — Intel/HP, 1998–2000.** Itanium uses 128-bit instruction bundles consisting of three 41-bit instruction slots plus a 5-bit template field. The template encodes (a) the functional-unit type (M, I, F, B) for each slot and (b) stop bits marking instruction-group boundaries. The bundle-level encoding governs the dispatch and parallelism of its three constituent instructions. While not identical to prefix-modal SIMD, the structural pattern of "bundle-level metadata controls execution of contained instructions" predates ARM VPT by ~16 years. *Reference:* Intel IA-64 Architecture Software Developer's Manual, 1999–2000.

**SH-DSP repeat block — Hitachi, 1996.** The SH-DSP extension to SH-2 introduced architecturally-visible repeat-block state: instructions LDRS, LDRE, LDRC, SETRC set up a repeat-start address, repeat-end address, and repeat counter, after which the block of instructions between those addresses is executed repeatedly under control of that state. This is "state set by previous instructions governs subsequent instructions" — the same mechanism family as prefix-modal SIMD, ~20 years before ARM VPT. *Reference:* Hitachi SH-DSP Programming Manual, 1996.

**Cray-1 vector length register VL — Cray Research, 1976.** The Cray-1's VL register, set by a separate instruction, governs the lane count of all subsequent vector operations until VL is changed. This is the canonical "configuration register controls subsequent vector instructions" precedent — predating ARM VPT by 40 years. *Reference:* Cray-1 Computer System Hardware Reference Manual, Cray Research Inc., 1976.

**Multiflow TRACE VLIW — Multiflow Computer, 1984.** Multiflow's VLIW architecture used wide instructions controlling multiple functional units in one cycle, with bundle-level structure governing intra-bundle parallelism. The "wide instruction encodes behaviour of multiple operations" pattern dates to at least this point, 32 years before ARM VPT. *Reference:* Multiflow TRACE 14/300 architecture documents, 1984; Joseph Fisher, "Trace Scheduling," IEEE TC 1981.

### D.2 Prior Art for Predication (§2.5, §4.3, §4.4, §5.5)

Predication via mask registers applied to vector or scalar operations is among the oldest mechanisms in vector and RISC processing. The v0.3 design (persistent mask P0, mode-bit VCSR.MKE enabling application, comparison instructions decoupled from mask-apply) is directly modelled on the following prior art:

**Cray-1 vector mask register VM — Cray Research, 1976.** The Cray-1 includes a 64-bit VM register. Quoting the Cray-1 Hardware Reference Manual directly: "The vector mask register may be set from an S register through the 003 instruction or may be created by testing a vector register for condition using the 175 instruction. The mask controls element selection in the vector merge instructions (146 and 147)." Three points are architecturally significant and directly precedential for v0.3:
1. VM can be set in **two independent ways**: by scalar copy (instruction 003) or by vector comparison (instruction 175). The v0.3 LDS/STS-P0 and the SIMD-context comparison writes mirror this directly.
2. VM is **consumed by separate instructions** (the merge instructions 146 and 147), entirely decoupled from how VM was set.
3. VM is **persistent architectural state** — it lives until overwritten, with no count-bounded "predication window" attached to its definition.

The §4.3 / §4.4 v0.3 design replicates this exact pattern, predating ARM VPT by **40 years**. *Reference:* Cray-1 Hardware Reference Manual (HR-0004), Cray Research Inc., 1976. PDF at https://bitsavers.trailing-edge.com/pdf/cray/CRAY-1/ ; HTML transcription of relevant chapters at http://ed-thelen.org/comp-hist/CRAY-1-HardRefMan/CRAY-1-HRM.html.

**HP PA-RISC nullification — Hewlett-Packard, 1986.** Every PA-RISC arithmetic and logical instruction can nullify the immediately following instruction based on a condition encoded in the instruction. This is per-instruction-pair predication, decoupled from comparison setup. Predates ARM VPT by 30 years. *Reference:* HP PA-RISC 1.0 Architecture Manual, 1986.

**IA-64 predicate register file — Intel/HP, 1998–2000.** Itanium has 64 architectural predicate registers (P0..P63). Every instruction includes a 6-bit predicate field naming one predicate register; the instruction's effects are nullified when the named predicate is false. Comparison instructions write to predicate-register **pairs** (e.g., `cmp.eq` writes the true-condition predicate and its complement to another). Predication and comparison are entirely decoupled: predicates can be read, written, combined, and consumed independently. The §5.1 / §5.5 v0.3 design's decoupling of comparison from VCSR.MKE directly follows this pattern, predating ARM VPT by 16 years. *Reference:* Intel IA-64 Architecture Software Developer's Manual, 2000.

**TMS320C6x VelociTI — Texas Instruments, 1997.** TI's C6x VLIW DSP supports per-instruction conditional execution from a small set of architectural condition registers (A1, A2, B0, B1, B2). Each instruction includes a 4-bit predicate field. Predicates are set by ordinary compare/move instructions, fully decoupled from their use. Predates ARM VPT by 19 years. *Reference:* TMS320C6000 CPU and Instruction Set Reference Guide, TI, 1997–2000.

**Multiflow TRACE predicated execution — 1984.** Multiflow's VLIW supported predicated/conditional execution within bundles. Predicated execution as a concept predates ARM VPT by 32 years. *Reference:* Multiflow TRACE architecture documents, 1984.

### D.3 Prior Art for Dedicated SIMD Register File (§2.1)

The architectural pattern of a dedicated wide-vector register file, physically and architecturally separate from scalar and floating-point register files, is well-established prior art predating any ARM SIMD patent by at least 25 years:

**Cray-1 V registers — Cray Research, 1976.** The Cray-1 has 8 dedicated vector registers V0..V7, each holding 64 elements of 64 bits — physically separate from the 8 scalar S registers and the 8 address A registers. Vector instructions name V registers; scalar instructions name S registers; the register files are architecturally disjoint. This is the foundational prior art for "dedicated vector register file separate from scalar files" in stored-program computing, predating any ARM SIMD patent by 50 years. *Reference:* Cray-1 Hardware Reference Manual (HR-0004), Cray Research Inc., 1976. Available at https://bitsavers.trailing-edge.com/pdf/cray/CRAY-1/.

**CDC STAR-100 vector facility — Control Data Corporation, 1974.** The STAR-100 was the first commercially-shipped vector processor with architecturally-visible vector operations. Its memory-to-memory vector instructions operated on streams of elements rather than register-resident vectors, but the principle of a vector-specific architectural facility separate from scalar arithmetic was established here. Predates ARM SIMD by 52 years. *Reference:* CDC STAR-100 Hardware Reference Manual, Control Data Corp., 1974.

**Convex C-1 vector registers — Convex Computer, 1985.** Convex's C-1 minisupercomputer had 8 dedicated vector registers, each holding 128 elements of 64 bits, separate from the integer and scalar FP register files. Predates ARM SIMD by 41 years. *Reference:* Convex C-1 Architecture Reference, 1985.

**NEC SX-2 vector registers — NEC, 1985.** The SX-2 had 40 dedicated vector data registers, each 256 elements of 64 bits, separate from scalar registers. Predates ARM SIMD by 41 years. *Reference:* NEC SX-2 System Description, 1985.

**Intel SSE XMM registers — Intel, 1999.** Intel SSE introduced 8 dedicated 128-bit registers (XMM0..XMM7), architecturally separate from x87 floating-point registers and from MMX (which aliased over x87). XMM was extended to 16 registers (XMM0..XMM15) in x86-64. The dedicated-128-bit-register design is the closest pre-2006 prior art for v0.4's V0..V15 in width and register count. Predates ARM SIMD patents by 17 years. *Reference:* Intel Pentium III Processor and Architecture Manuals, 1999; "Intel Architecture Software Developer's Manual, Volume 2: Instruction Set Reference."

**PowerPC AltiVec — Motorola/IBM/Apple consortium, 1996–1999.** AltiVec (later VMX/Velocity Engine) defined 32 × 128-bit V registers (V0..V31), entirely separate from the integer GPRs and the scalar FP register file. The PowerPC G4 (1999) was the first widely-shipped processor implementing AltiVec. The 32-vector, 128-bit-wide, separate-register-file design has been the dominant SIMD architecture for general-purpose computing since. Predates ARM SIMD by 27 years. *Reference:* AltiVec Technology Programming Environments Manual, Motorola Document MPCFPE32B/AD, 1999.

**Design provenance for v0.4/v0.5.** The dedicated V0..V15 register file in v0.4 follows the model established by Cray-1 (1976) for vector-separate-from-scalar register files and refined by Intel SSE (1999) and PowerPC AltiVec (1996–1999) for the specific case of 128-bit-wide SIMD registers. The 16-register count is intermediate between SSE's 8 (later 16) and AltiVec's 32, chosen as a balance between register pressure for autovectorising compilers and silicon area for in-order J-core implementations.

### D.4 Notes on the Patent Landscape

This documentation is intended as defensive reference, not legal advice. Two specific ARM patents bear on the design space and have been considered:

- **GB2548600A / US 10,782,972**, "Vector Predication Instruction" (ARM, priority 2016-03-23). Covers the specific mechanism of a vector predication instruction setting control information based on element comparisons that controls a predetermined number of subsequent vector instructions. The v0.4 predication design (§2.5, §4.3, §4.4, §5.5) is deliberately structured to fall outside this claim language by (a) using a persistent mask register P0 rather than a counted predication block, (b) decoupling comparison from mask-enable (comparison instructions in §5.1/§5.2 write P0 unconditionally; mask is applied only when VCSR.MKE = 1, set by the separate VMKCHG instruction in §5.5), and (c) using a mode-bit toggle rather than a "vector predication instruction." Critically, **the SIMDV/SIMDH prefix carries no predication information whatsoever** — it controls only lane width, mode, and block length (the anchor field of v0.3 is removed in v0.4; the freed encoding becomes reserved bits, also unrelated to predication). The "predetermined number of subsequent instructions" aspect of the prefix is the SIMD block length, structurally unrelated to predication. The prior art cited above demonstrates that the broader concepts (persistent mask register, decoupled compare/apply, mode-bit predication) substantially predate the patent's priority date — by 40 years in the Cray-1 case.

- **US 10,599,428**, "Relaxed execution of overlapping mixed-scalar-vector instructions" (ARM, priority 2017). Covers Helium's specific overlapped-beat execution model with relaxed (race-permitting) semantics on mixed-scalar-vector instructions. The §7.2 four-beat sequencing in this specification is **sequential, not overlapped**, and the architecture **forbids relaxed execution**. Beat-multiplexed ALU execution on a narrow datapath is established prior art going back to Cray-1 (1976) and is not covered by this patent in its general form.

**Patent-relevance note on v0.4 specifically.** The move to a dedicated V0..V15 register file in v0.4 simplifies the patent-landscape analysis: the register-file aliasing argument (SH-4 FIPR / MMX prior art, see retired D.3 commentary in v0.3) no longer applies, replaced by the much-better-established dedicated-vector-file precedent (Cray-1 1976, PowerPC AltiVec 1996, Intel SSE 1999 — see D.3). The anchor-field removal further distances the prefix from any patent claiming "instruction encoding the destination vector for a predicated block." v0.4 is structurally more defensible than v0.3 across all relevant patent claims.

Implementers planning commercial deployment should obtain a formal freedom-to-operate opinion from semiconductor IP counsel, with specific scope including the above patents and their continuations as of the FTO date.

### D.5 Prior Art for Vector Permutation (§3.3, §4.5, §5.6.6)

Vector lane permutation (also called "shuffle" or "table lookup") has continuous pre-2006 prior art spanning 30 years. The J-Core `SWIZZLE Vn, Vm` (register-controlled, §4.5) and `SWIZZLE.I Vn, #pat, #param` (immediate-controlled, §5.6.6) instructions are well-grounded in this lineage.

**Foundational prior art:**

**Cray-1 compress/expand — Cray Research, 1976.** The Cray-1 included vector compress/expand operations controlled by the VM mask register, providing lane-rearrangement at the cost of one mask bit per lane. This is the foundational prior art for "vector reorganization controlled by a per-lane control register." *Reference:* Cray-1 Hardware Reference Manual (HR-0004), 1976, Section 4.2 (Vector Compress/Expand).

**HP PA-RISC MAX-2 PERMH — Hewlett-Packard, 1995.** The MAX-2 multimedia extension introduced PERMH (Permute Halfwords), which permutes the four 16-bit halfwords of a 64-bit register using a 6-bit immediate field encoding the source position for each destination lane. This is a direct precedent for the immediate-controlled permutation pattern. *Reference:* Lee, R.B., "Subword Parallelism with MAX-2," IEEE Micro, July/August 1996.

**Sun VIS BSHUFFLE / BMASK — Sun Microsystems, 1995.** SPARC's Visual Instruction Set introduced byte-shuffle with a mask register controlling the per-byte source position. Direct precedent for register-controlled byte permutation. *Reference:* Tremblay, M., et al., "VIS Speeds New Media Processing," IEEE Micro, July/August 1996.

**Intel MMX PSHUFW — Intel, 1996.** The PSHUFW instruction (in MMX, then SSE) shuffles four 16-bit words in a 64-bit MMX register according to an 8-bit immediate, with two bits selecting the source position for each of four destination lanes. The canonical immediate-controlled shuffle. The pattern (4-bit-pair-per-destination-lane immediate selecting source lanes) is structurally similar to J-Core's `SWIZZLE.I` pattern parameter. *Reference:* Peleg, A., and Weiser, U., "MMX Technology Extension to the Intel Architecture," IEEE Micro, July/August 1996.

**MIPS MDMX pshu — MIPS Technologies, 1996.** Packed shuffle in the MIPS Digital Media Extensions. Same architectural category. *Reference:* "MIPS Digital Media Extension," 1996.

**PowerPC AltiVec VPERM (vec_perm) — Motorola/IBM/Apple consortium, 1996–1999.** **The direct precedent for J-Core's register-controlled SWIZZLE.** AltiVec's VPERM is a three-operand instruction: two 128-bit source vectors (32 bytes total) and a 128-bit control vector whose 16 bytes are interpreted as 5-bit indices selecting which source byte to place in each of the 16 destination positions. Out-of-range indices produce zero in the corresponding destination lane. This is precisely the architectural pattern J-Core's `SWIZZLE Vn, Vm` follows (single-source variant of the AltiVec two-source design) with identical out-of-range semantics. *Reference:* AltiVec Technology Programming Environments Manual, Motorola Document MPCFPE32B/AD, 1999, Chapter 6 (Permute Instructions); see also Phillip, M., et al., "AltiVec Technology: Accelerating Media Processing Across the Spectrum," Hot Chips 10, 1998.

**Intel SSE SHUFPS, PSHUFD — Intel, 1999–2001.** SHUFPS (in SSE, 1999) shuffles 4 single-precision floats in a 128-bit XMM register according to an 8-bit immediate (4 × 2-bit indices). PSHUFD (in SSE2, 2001) does the same for 4 doublewords. Both are 4-lane immediate-controlled shuffles at 32-bit granularity, similar to J-Core's `SWIZZLE.I` pattern at FP32 lane width. *Reference:* Intel Architecture Software Developer's Manual, Volume 2 (Instruction Set), 1999 / 2001 editions.

**Architectural lineage for J-Core SWIZZLE:**

- **Register-controlled form (`SWIZZLE Vn, Vm`, §4.5):** follows the AltiVec VPERM pattern (1996–1999) for vector-controlled byte/lane permutation with out-of-range-produces-zero semantics. The single-source restriction (vs AltiVec's two-source) is a J-Core simplification, not a novel mechanism.
- **Immediate-controlled form (`SWIZZLE.I Vn, #pat, #param`, §5.6.6):** follows the MMX PSHUFW (1996) and SSE SHUFPS / PSHUFD (1999–2001) pattern of immediate-encoded lane permutation. J-Core's 4-bit-pattern × 4-bit-parameter encoding is more compact than SHUFPS's 8-bit immediate but encodes equivalent operations.

**Patent landscape for SWIZZLE.** Modern patents in the area cover specific implementations (e.g., US 9,292,286 Renesas 2016 for dynamic pattern generation; US 10,592,468 for specific shuffler-circuit designs; US 9,672,034 / US 8,914,613 Intel for AVX-512's specific in-lane-shuffle structure) rather than the basic architectural operation. The early Intel patent on dual-function shuffle (US RE45,458, reissue of US 6,041,404 with priority ~1998) has expired. J-Core's SWIZZLE design avoids these specific implementations by following the simpler AltiVec VPERM pattern, which has 30 years of public prior art and no surviving patent coverage on the architectural operation itself.

**SWIZZLE and out-of-range zeroing semantics.** The J-Core specification (§4.5) states that out-of-range control indices produce zero in the destination lane. This follows AltiVec VPERM's documented behavior (out-of-range indices in the control vector produce zero) and Intel PSHUFB's documented behavior (high bit of control byte set produces zero). The semantic is established prior art across multiple vendors.

### D.6 Prior Art for Vector-Indexed Memory Access (§5.6.2)

Vector-indexed memory access — also called gather/scatter or scatter/gather — has continuous pre-2006 prior art spanning 50 years across at least eight independent vendor architectures. The J-Core `VGATHER.Q @(R0,Vm), Vn` and `VSCATTER.Q Vn, @(R0,Vm)` instructions (§5.6.2) are well-grounded in this lineage.

**Foundational prior art:**

**CDC STAR-100 — Control Data Corporation, 1974.** The STAR-100 included memory-to-memory vector operations with indirect addressing as an early form of scatter/gather. The first commercial vector processor with indirect memory access. 52 years old. *Reference:* CDC STAR-100 Hardware Reference Manual, Control Data Corp., 1974.

**Cray-1 — Cray Research, 1976.** The Cray-1 supported vector gather via an index vector held in a V register, with VM masking for per-element predication. Limited to constant-stride access in the base instructions; gather of arbitrary indices was implemented via software loop or microcoded subroutine. 50 years old. *Reference:* Cray-1 Hardware Reference Manual (HR-0004), 1976.

**Cray X-MP — Cray Research, 1982. THE canonical introduction of arbitrary-index gather/scatter.** The X-MP added explicit GATHER and SCATTER instructions taking a vector index register as the source of per-element offsets, a scalar A register as base address, and writing to / reading from a vector V register. The Cray X-MP gather/scatter design is the foundational prior art for the modern operation: 44 years old, extensively documented, widely deployed. The Wikipedia article on gather/scatter explicitly identifies the X-MP as the introduction of arbitrary-index gather/scatter, citing the elimination of Cray-1's constant-stride restriction. *Reference:* Cray X-MP Hardware Reference Manual, Cray Research Inc., 1982; see also Espasa, R., and Valero, M., "Vector Architectures: Past, Present and Future," Supercomputing '98.

The Cray X-MP gather/scatter is structurally identical to J-Core's `VGATHER.Q @(R0,Vm), Vn`:

- Base address from a scalar register (X-MP: A-register; J-Core: R0)
- Per-lane offsets from a vector register (X-MP: index V-register; J-Core: Vm)
- Destination is a vector register (X-MP: V-register; J-Core: Vn)
- Per-lane predication via mask register (X-MP: VM; J-Core: P0 with VCSR.MKE)

**NEC SX-2 — NEC Corporation, 1985.** The SX-2 included indirect-addressing gather/scatter following the X-MP model, with up to 8 simultaneous memory ports providing high gather throughput. 41 years old. *Reference:* NEC SX-2 System Description, NEC Corporation, 1985.

**Convex C-1 — Convex Computer, 1985.** The C-1 minisupercomputer included vector indirect addressing in its 128-element vector instruction set. 41 years old. *Reference:* Convex C-1 Architecture Reference, 1985.

**Fujitsu VP-200 — Fujitsu, 1982.** Vector indirect addressing in the VP-200 supercomputer. 44 years old.

**Cray Y-MP — Cray Research, 1988.** Refined gather/scatter following the X-MP model with improved memory bandwidth. 38 years old. *Reference:* Cray Y-MP Hardware Reference Manual, 1988.

**NEC SX-3 — NEC Corporation, 1989.** Continuation of the SX series gather/scatter design with higher throughput. 37 years old.

**Architectural lineage for J-Core VGATHER/VSCATTER:**

The J-Core gather/scatter design follows the Cray X-MP (1982) model directly:
- Scalar base + per-lane vector offset addressing — X-MP precedent
- Mask-controlled predication where masked lanes skip memory access — Cray-1 VM precedent (1976), refined in X-MP
- Element-index interpretation (V[i] is a count, not a byte offset, multiplied by element size internally) — standard across the Cray lineage
- Architecturally implementation-defined ordering for scatter writes — matches the actual implementation flexibility in Cray X-MP and successors

**Patent landscape for VGATHER/VSCATTER.** The basic architectural operation is 50 years old and has 44 years of continuous deployment in multiple independent vendor architectures pre-2006. No surviving patent covers the basic operation itself. Modern patents in the area cover specific microarchitectural implementations:

- **US 7,093,102** (priority ~2003): Code sequences for vector gather/scatter in a specific microarchitecture — about microcode implementation, not architectural specification.
- **US 5,430,884** (priority ~1992): Scalar/vector processor with improved gather/scatter — about specific implementation efficiency.
- **US 7,707,393, US 7,216,218:** microprocessor designs integrating high-speed memory in load/store unit — implementation patents.
- **US 8,826,252** (Intel, ~2007): Vector atomic memory operations with gather/scatter — about combining gather with atomicity.
- **US 8,688,962** (Intel): Gather cache architecture — specific cache design for accelerating gather.
- **US 20100042779** (Intel, ~2008): Alias-free gather/scatter optimization — about a specific optimization hint.
- **US 20160124749** (Intel, ~2012): Coalescing adjacent gather/scatter operations — about merging adjacent operations.
- **US 9,552,205** (Intel): Vector-indexed memory access *with combined arithmetic* — about fused operations.
- **US 9,766,887** (Intel): Multi-register gather instruction — about a specific multi-destination variant.
- **US 20220342590** (Microchip, 2022): More recent gather/scatter implementation.

None of these patents cover the basic architectural operation of "load N values into a vector register from N addresses computed as base + per-lane index." They cover specific microarchitectural optimizations (cache designs, memory-system coalescing, conflict-detection avoidance), specific variants (multi-register destination, fused arithmetic, atomic semantics), and specific encoding mechanisms (Intel's VSIB form for x86 AVX2 gather).

**Microarchitectural caveats for J-Core implementers:**

- **Memory coalescing logic** that combines adjacent per-lane addresses into single cache-line accesses — implementations should design their own coalescing scheme rather than copy specific Intel patented designs. The basic existence of coalescing is fine; specific algorithms may be patented.
- **Cache-side optimization** — Intel's "gather cache" (US 8,688,962) covers a specific cache interface design; implementations should design their own.
- **Conflict-detection logic for scatter** — Intel patents cover specific conflict-detection schemes. J-Core stays out of this territory by deliberately specifying scatter ordering as implementation-defined for overlapping destinations (§5.6.2): "the architecture does not guarantee any particular access ordering across lanes."

The J-Core spec's architectural posture — specifying the visible per-lane semantics without dictating any particular microarchitectural mechanism — keeps the spec itself clear of all modern microarch patents. Implementers building specific gather/scatter execution units should still seek FTO review for their particular implementation choices.

**Predication interaction.** J-Core's specification that masked lanes in VGATHER skip the memory access entirely (no read at masked lanes; destination V lane unchanged) follows the Cray-1 / X-MP VM precedent (1976 / 1982) of mask-controlled per-element predication on memory operations. This is the architecturally-cleanest semantic and has 40+ years of prior art.

### D.7 Prior Art for Non-Temporal Memory Access Hints (§3.2, §5.6.0)

The "non-temporal" or "streaming" memory-access hint — a per-instruction flag indicating the data has no expected reuse, allowing the cache subsystem to optimize for bandwidth rather than retention — has continuous pre-2006 prior art spanning 30+ years.

**PowerPC dcbt / dcbtst — Motorola/IBM, 1993.** The PowerPC architecture (POWER lineage) introduced *data cache block touch* (dcbt) and *data cache block touch for store* (dcbtst) instructions. These are advisory hints to the cache prefetcher to bring a line into cache (touch) or prepare a line for store (touch-for-store). Subsequent revisions added locality hints distinguishing temporal from streaming accesses. 33-year-old prior art for the basic "memory operation with cache hint" concept. *Reference:* PowerPC Architecture Book II Programming Environments Manual, IBM/Motorola, 1993.

**PowerPC AltiVec dst / dstt / dstst — Motorola/IBM/Apple, 1996–1999.** AltiVec added vector-specific streaming hints: `dst` (data stream touch), `dstt` (data stream touch transient — no temporal locality), and `dstst` (data stream touch for store). Each takes a stream ID (allowing up to 4 simultaneous prefetch streams), a base address, and a stride/block configuration. The transient variant (`dstt`) is the direct architectural precedent for J-Core's NT hint — software signals to the cache that the stream has no expected reuse. 27–30-year-old prior art. *Reference:* AltiVec Technology Programming Environments Manual, Motorola Document MPCFPE32B/AD, 1999, Chapter 6 (Data Stream Instructions).

**Intel SSE MOVNTPS / MOVNTPD / MOVNTI — Intel, 1999–2001.** SSE introduced non-temporal stores: MOVNTPS (move non-temporal packed single, 1999), MOVNTPD (packed double, 2001), MOVNTI (non-temporal integer, 2001). These instructions write data through a write-combining buffer to memory, bypassing the L1 data cache. The architectural distinction from regular stores is exactly one bit in the instruction encoding (selecting the non-temporal variant) — the same architectural design as J-Core's NT hint. 25–27-year-old prior art. *Reference:* Intel Architecture Software Developer's Manual, Volume 2: Instruction Set Reference, 1999 / 2001 editions.

**Intel SSE PREFETCHNTA — Intel, 1999.** Non-temporal aligned prefetch hint. Software hints the cache that an upcoming load has no temporal locality, allowing the cache to place it in a streaming-friendly way (or bypass it entirely). 27-year-old prior art for the architectural concept of "non-temporal load hint." *Reference:* same as above.

**MIPS PREF / PREFX — MIPS Technologies, 1996.** The MIPS PREF instruction takes an explicit hint encoding the intended use case (load, store, exclusive) and locality (temporal, non-temporal). The hint field is architecturally visible and software-controlled. 30-year-old prior art. *Reference:* MIPS64 Architecture for Programmers, Volume II: The MIPS64 Instruction Set, MIPS Technologies, 1996.

**SPARC V9 PREFETCH — Sun Microsystems, 1994.** SPARC V9 added a PREFETCH instruction with multiple variants distinguishing temporal vs non-temporal access patterns. Similar architectural posture: software-controlled hint, implementation-advisory. 32-year-old prior art. *Reference:* SPARC V9 Architecture Manual, Sun Microsystems, 1994.

**Architectural lineage for J-Core NT bit:**

The J-Core SIMDV prefix's NT bit (`rrr[0]`) follows the established architectural pattern: a single bit in the instruction encoding distinguishes "normal cached access" from "non-temporal / streaming access," with the cache implementation free to honor or ignore the hint. The specific design — placing the hint in the prefix rather than the memory-access opcode — is a J-Core-specific encoding choice motivated by the SIMDV/SIMDH prefix design, but the architectural concept is well-established across multiple pre-2006 vendor implementations.

**Patent landscape.** Modern patents in the cache-hint space cover specific implementations (particular write-combining-buffer designs, streaming cache-way replacement policies, prefetch-distance prediction algorithms). The basic architectural concept — a software hint distinguishing cacheable from streaming memory access — has 30+ years of public prior art across at least five vendor architectures (PowerPC, AltiVec, SSE, MIPS, SPARC) and is unencumbered. Implementations building specific streaming-cache hardware should seek FTO review for their particular microarchitectural choices, but the spec itself sits comfortably in well-established prior-art territory.


## Appendix E. Glossary

**Architectural registers:**

- **V0..V15** — Dedicated 128-bit SIMD register file (16 registers, 2048 bits total). Introduced v0.4 as separate architectural state from FR0..FR15 + XF0..XF15. Named via the 4-bit Rn/Rm fields of governed instructions in SIMD context.
- **FR0..FR15** — SH-4 scalar FPU register file (front bank), 16 × 32-bit. Used by scalar FPU instructions outside SIMD blocks. In v0.2/v0.3 these doubled as the storage for V0..V3 via aliasing; in v0.4/v0.5 they are dedicated to scalar FPU and never overlap V0..V15.
- **XF0..XF15** — SH-4 scalar FPU register file (back bank), accessed via FPSCR.FR = 1. Same role as FR in v0.4/v0.5: dedicated scalar storage.
- **R0..R15** — SH-2 general-purpose 32-bit integer registers. Used by integer governed instructions in SIMD context as V-register indices (via the 4-bit Rn/Rm fields) and by integer extract/insert (VEXT/VINS) as source/destination for transferred lane values.
- **MACL, MACH** — SH-2 multiply-accumulate result registers, 32 bits each. Form the 64-bit "MAC pair" that holds integer horizontal-reduction results.
- **FPUL** — SH-4 floating-point communication register (32 bits). Holds FP32 horizontal-reduction results for FP16 inputs.
- **DR0** — SH-4 double-precision register, 64 bits, occupies FR0 + FR1. Holds FP64 horizontal-reduction results for FP32 inputs.
- **FPSCR** — SH-4 Floating-Point Status and Control Register. Holds FR (bank), PR (precision), SZ (transfer size), RM (rounding mode), and exception enable/cause/flag bits. Unchanged by v0.5 SIMD instructions.
- **P0** — SIMD predicate mask register, 16 bits. Introduced v0.3. Each bit corresponds to one lane at the narrowest width (w = 8); at wider widths, lane *i* is enabled by P0[*i* · (*w*/8)]. Written by comparison instructions in SIMD context, applied when VCSR.MKE = 1.
- **VCSR** — Vector Control and Status Register, 32 bits. Introduced v0.5. Holds VCSR.MKE (bit 0, mask enable) and VCSR.IEE (bit 1, IEEE-strict FP mode), with bits 2..31 reserved for future SIMD mode bits.

- **VCSR.MKE** (Mask Enable, bit 0 of VCSR) — When set, governed SIMD operations apply P0 as a per-lane enable mask. Effective only inside SIMD blocks.

- **VCSR.IEE** (IEEE-strict mode, bit 1 of VCSR) — When set, SIMD FP operations follow IEEE 754 denormal handling and OR-update FPSCR.FLAG across lanes. When clear (default), denormals are flushed to zero and FPSCR.FLAG is not updated by SIMD operations. **In neither mode do SIMD FP operations deliver traps** — software requiring FP traps must use scalar FP. See §6.3.

**Instruction families:**

- **SIMDV.w #N** — Vertical (lane-parallel) prefix. Declares the next N (1..4) instructions are SIMD operations at lane width *w*, with no cross-lane data movement.
- **SIMDH.w #N** (or **SIMDHA, SIMDHO, SIMDHN, SIMDHX, SIMDHMN, SIMDHMX, SIMDHMNU, SIMDHMXU**) — Horizontal (reductive) prefix. Eight variants distinguished by the `rrr` field selecting the reduction operator (add, OR, AND, XOR, min, max, min-unsigned, max-unsigned).
- **SWIZZLE Vn, Vm** — Permute lanes of V`<Rn>` according to lane-index control vector V`<Rm>`. Inside SIMD blocks only.
- **SWIZZLE.I Vn, #pat, #param** — Permute lanes of V`<Rn>` using a named pattern from a 16-entry table with a 4-bit parameter. Inside SIMD blocks only.
- **VLD.Q / VST.Q** — Vector load/store, 128 bits per access, six addressing modes (`@Rm`, `@Rm+`, `@-Rm`, `@(R0,Rm)`, and the scalar-indexed forms). Valid inside and outside SIMD blocks.
- **VGATHER.Q / VSCATTER.Q** — Vector-indexed memory access (gather/scatter). The per-lane offset comes from a vector register Vm. Inside SIMD blocks only.
- **VMOV Vm, Vn** — 128-bit vector register copy. Inside SIMD blocks only.
- **VEXTF.L, VINSF.L** — FP32 lane extract/insert between Vn and FRn. Valid inside and outside SIMD blocks.
- **VEXT.B/W/L/Q, VINS.B/W/L/Q** — Integer lane extract/insert at lane widths 8/16/32/64, between Vn and Rn. Valid inside and outside SIMD blocks.
- **VLDI.Q #imm, Vn** — Broadcast 8-bit signed immediate to all lanes of Vn (sign-extended to lane width). Inside SIMD blocks only.
- **VMKCHG** — Toggle VCSR.MKE. Outside SIMD blocks only.
- **LDS Rn, P0 / STS P0, Rn** — Load/store the mask register P0. Outside SIMD blocks only.
- **LDS Rn, VCSR / STS VCSR, Rn** — Load/store the SIMD control register VCSR. Outside SIMD blocks only.

**Architectural concepts:**

- **Prefix-modal SIMD** — The mechanism where a single 16-bit prefix instruction declares that the next N (1..4) instructions are SIMD operations. Inspired by ARM Thumb-2's IT block (2003).
- **Governed instruction** — An ordinary SH-2 integer or SH-4 FP instruction that appears immediately after a SIMD prefix and is consumed as one of the N SIMD slots. Its Rn/Rm fields are reinterpreted as V-register indices.
- **Lane** — One independent element-position within a 128-bit vector. The number of lanes per vector is 128/*w* where *w* is the lane width (8, 16, 32, or 64 bits).
- **Beat** — A microarchitectural execution slot in the time-multiplexed ALU. A 4-beat schedule executes a 4-lane FP32 operation in 4 cycles on a 32-bit ALU. Prior art: Cray-1 multi-cycle vector execution (1976).
- **Atomic block** — The architectural property that SIMD blocks complete before external interrupts are delivered. No SIMD microarchitectural state is ever architecturally visible.
- **Widening reduction** — A horizontal-reduction mode where the result type is one class wider than the input lane type (int8 → int16, int16 → int32, FP16 → FP32, FP32 → FP64). Prior art: SH-4 FIPR (1998).
- **Identity-element substitution** — The masked-lane semantic for SIMDH: when VCSR.MKE = 1, masked lanes contribute the additive identity (0 for add, 1 for product, +∞ for min, etc.) rather than being skipped. Keeps the reduction tree shape mask-independent.
- **Decoupled compare-from-apply** — The predication design principle: comparison instructions write P0 unconditionally; mask application is governed by VCSR.MKE which is set/cleared by a separate instruction (VMKCHG or LDS to VCSR). Prior art: Cray-1 (1976), IA-64 (1998).

- **NT (Non-Temporal hint)** — The `rrr[0]` bit of a SIMDV prefix. When set, governs an in-block memory access (VLD.Q, VST.Q, VGATHER.Q, VSCATTER.Q) with a cache hint that the data has no expected reuse. Implementations may bypass cache allocation (e.g., via a write-combining buffer for stores, or a streaming cache way for loads) or treat the hint as a no-op. The architectural result is the same in either case. Prior art: Intel SSE MOVNTPS (1999), PowerPC AltiVec dst/dstt (1996-1999), PowerPC dcbt (1993). See §5.6.0 and Appendix D.7.

- **Streaming workload** — A memory-access pattern characterized by sequential, one-shot access to a large data set without expected reuse. Examples: memcpy, large-array sweeps, video frame processing, FIR filters streaming through long signal buffers. These workloads benefit from the NT hint to avoid cache pollution.

**Narrow floating-point formats** (see Appendix F for strategy and patent analysis):

- **FP16 / binary16** — IEEE 754-2008 16-bit floating-point: 1 sign / 5 exponent / 10 mantissa, bias 15. Pre-2006 prior art (Scott 1991, Hitachi 1982). Planned for v0.6.
- **bfloat16 / BF16** — Google-originated 16-bit FP: 1 sign / 8 exponent / 7 mantissa. Truncated IEEE FP32. Heavy Intel patent activity on operations. Not implemented in v0.6 as native arithmetic; supported as software-only storage format.
- **FP8** — Joint NVIDIA / Intel / ARM 2022 specification, OCP OFP8 (2023). Two variants: **E5M2** (1/5/2, IEEE-style) and **E4M3** (1/4/3, no Inf, restricted NaN). Active patent prosecution. Not implemented in v0.6.
- **FP4** — OCP Microscaling 2023 specification. **E2M1** (1/2/1) elements with a shared scale per block. **MXFP4** uses E8M0 scale per 32 elements; **NVFP4** uses E4M3 scale per 16 elements plus per-tensor scale. Active patent prosecution by NVIDIA/AMD. Not implemented in v0.6.
- **INT8 quantization** — Integer 8-bit values with software-managed scale factors. Standard 1990s DSP technique (TI TMS320, AT&T DSP series). Unencumbered. The recommended J-Core path for ML inference narrow-format workloads.
- **INT4 quantization** — Integer 4-bit values (two packed per int8 lane). Software-implemented via shift/mask sequences on the j-core INT8 SIMD primitives. Unencumbered.

**Encoding terms:**

- **`xxxx` row** — A 16-codepoint sub-row of the 16-bit SH instruction encoding, identified by the top nibble (e.g., the `1111` row holds all SH-4 FPU instructions and the SIMD escape encoding).
- **Slot-illegal exception** — The exception raised when a reserved or undefined encoding is decoded inside a SIMD block, or when an instruction is encoded with reserved field values (e.g., `rrr` ≠ 000 in a SIMDV prefix).
- **Reserved encoding** — A bit-pattern that is architecturally committed not to be used by current code, so that future revisions may define it. Encountering a reserved encoding in v0.5 raises slot-illegal.


## Appendix F. Narrow-Format Strategy and Patent Avoidance

### F.1 Context

By 2025–2026, the ML inference industry has rapidly adopted floating-point formats narrower than 32 bits as a primary efficiency lever. The current landscape spans:

- **16-bit:** FP16 (IEEE 754-2008 binary16), bfloat16 (BF16)
- **8-bit:** FP8 (E4M3, E5M2 variants), MXFP8
- **6-bit:** FP6 (E2M3, E3M2 variants), MXFP6
- **4-bit:** FP4 (E2M1), MXFP4, NVFP4

NVIDIA's Hopper (H100, 2022) and Blackwell (B200, 2025) GPUs implement FP8 and FP4 natively in tensor cores. AMD's MI355X implements MXFP4. ARM has announced FP8 support. The Open Compute Project published OFP8 (December 2023) and the Microscaling Formats (MX) specification (September 2023).

A J-Core SIMD competing in the ML inference market would naively want to implement all of these formats. This appendix documents why v0.5 / v0.6 deliberately does not, and what the alternative path looks like.

### F.2 The pre-2006 prior art discipline applied to narrow FP

The J-Core SIMD specification's design discipline (Appendix C, Appendix D) is to draw all architectural inspiration from pre-2006 prior art. This is not merely a stylistic choice — it provides a defensible patent-avoidance posture by ensuring that the J-Core SIMD design's structural elements (prefix-modal control, dedicated vector register file, persistent mask predication, two-mode FP exception handling) all have prior art at least 20 years old.

For narrow floating-point formats, this discipline has very different implications across format generations:

| Format | Earliest published spec | Age in 2026 | Pre-2006 prior art for the format | Patent landscape |
|---|---|---|---|---|
| FP16 (IEEE 754-2008 binary16) | 1991 (Scott WIF) | 35 years | Strong (Scott 1991, Hitachi 1982, 3dfx 1995) | Format unencumbered; specific operations may have patents but format itself is open |
| bfloat16 | 2018 (Google) | 8 years | Weak (truncated FP32 argument only) | Heavy: Intel patents on BF16 instructions; Google litigation IPR2021-00155 active |
| FP8 (E4M3, E5M2) | 2022 (NVIDIA/Intel/ARM) | 4 years | None | Active: Intel patents on conversion instructions; vendor "license-free" claim is informal |
| FP4 (MXFP4, NVFP4) | 2023 (OCP MX) | 3 years | None | Very active: NVIDIA, AMD patent prosecution underway |

Only FP16 has prior art that comfortably predates the 20-year cutoff.

### F.3 Format-by-format analysis

#### F.3.1 FP16 (IEEE 754-2008 binary16)

**Decision: implement in v0.6.**

The format itself is firmly in the public domain:

- **Hitachi HD61810 DSP (1982):** 4-bit exponent, 12-bit mantissa. 44-year-old prior art for "16-bit floating-point format." Documented in the *HD61810 Digital Signal Processor Users Manual*, archived at https://archive.org/details/bitsavers_hitachidatlSignalProcessorUsersManual_4735688. Bit allocation differs from IEEE binary16 but establishes the format category.
- **Scott's WIF (1991):** 5 exponent / 10 mantissa, *exactly matching* what became IEEE 754-2008 binary16. Published in *Proceedings of the 22nd SIGCSE Technical Symposium on Computer Science Education*, doi:10.1145/107004.107029. The strongest direct prior-art citation for the IEEE binary16 format itself.
- **3dfx Voodoo Graphics (1995):** 4 exponent / 12 mantissa for color storage. 31-year-old commercial deployment.
- **SGI s10e5 / OpenEXR "half" (1997, John Airey):** documented in SIGGRAPH 2000 paper describing the "Bali" design effort. Same bit allocation as IEEE binary16. Note that US 7,518,615 covers some SGI implementation aspects, but the format itself has older prior art (Scott 1991, Hitachi 1982 for the category).
- **NVIDIA Cg "half" type (2002), GeForce FX silicon (late 2002):** widely-deployed implementation of IEEE binary16.
- **IEEE 754-2008 binary16:** formal codification.

**Implementation plan for v0.6:**
- `ww = 01` for FP lane width selects FP16.
- 8 lanes per 128-bit V register at FP16 width.
- SIMDHA reduction widens FP16 → FP32, written to FPUL (matching the FP32 → FP64 → DR0 pattern at one type-class wider).
- Conversion instructions VCVT.FH (FP32 → FP16) and VCVT.HF (FP16 → FP32) for staging data between FP16 storage and FP32 computation.
- Follows IEEE 754-2008 semantics (the only variant; ARM's deprecated "alternative" format is not implemented).

**Patent considerations.** Specific FP16 operations (Intel F16C conversion instructions, ARM FEAT_FP16 arithmetic instructions) are patented, but the *format itself* is not. The J-Core implementation defines its own conversion instructions (VCVT.FH, VCVT.HF) using J-Core SIMD's encoding space; the format bit-layout is the unencumbered IEEE 754-2008 binary16.

#### F.3.2 bfloat16

**Decision: do not implement native arithmetic in v0.6. Software conversion only.**

bfloat16 was developed by Google Brain circa 2018 for TPU use. The format is structurally a truncated IEEE FP32 (1 sign / 8 exponent / 7 mantissa), preserving FP32's dynamic range and sacrificing precision.

**Patent situation is unfavorable:**

- **Intel US20190079767A1** ("Systems and methods for performing 16-bit floating-point vector dot product instructions") — claims the VDPBF16PS instruction explicitly.
- **Intel US20230069000A1** ("Bfloat16 arithmetic instructions") — claims general BF16 arithmetic operations.
- **Intel US12379927B2** ("BFLOAT16 scale and/or reduce instructions") — claims BF16 scale/reduce operations.
- **IPR2021-00155 (Patent No. 10,416,961)** — active patent dispute concerning Google's TPU implementation of bfloat16.

**Pre-2006 prior art is weak.** The general technique of "truncate FP32 by discarding low mantissa bits" is obvious to anyone familiar with floating-point representations and was implicit in 1990s graphics frame-buffer formats. But no formal published specification of the (1, 8, 7) bit allocation predates Google's 2018 work, leaving the prior-art argument depending on "this is so obvious it doesn't need a specification" — a weaker legal position than the multiple prior-published-spec citations supporting FP16.

**J-Core software path:** bfloat16 may be used as a storage-only format. Software emits BF16 from FP32 by truncating the low 16 bits (a single right-shift or masked store), loads from BF16 by zero-padding the low 16 bits, and performs all arithmetic in FP32. The conversion is so arithmetically trivial that no instruction-level operation is being claimed. Software-only BF16 storage:

```
; emit FP32 in FR0 to BF16 in low 16 bits of R0
FSTS    FR0, R0
SHLR16  R0           ; right-shift 16 bits (BF16 occupies low 16 bits)

; load BF16 from low 16 bits of R0 to FP32 in FR0
SHLL16  R0           ; left-shift, BF16 now in high 16 bits, low 16 = 0
FLDS    R0, FR0      ; load as FP32 (low mantissa bits = 0)
```

This idiom is patent-clear because no novel instruction is being executed; only existing shift and FLDS/FSTS instructions are used. Storage layout (which 16 bits of FP32 are dropped) is an obvious data-format choice.

#### F.3.3 FP8 (E4M3, E5M2, and variants)

**Decision: do not implement in v0.6.**

FP8 is a 2022 invention. The joint NVIDIA / Intel / ARM white paper *FP8 Formats for Deep Learning* was published September 2022; the Open Compute Project FP8 Specification (OFP8) Rev 1.0 was published December 2023.

**Two variants in the OFP8 spec:**

- **E5M2** (1 sign / 5 exponent / 2 mantissa, bias 15): truncated IEEE FP16, follows IEEE Inf / NaN conventions.
- **E4M3** (1 sign / 4 exponent / 3 mantissa, bias 7): does *not* represent Inf; uses only two bit patterns for NaN. Deliberately deviates from IEEE 754 to extend dynamic range by one binade.

**Additional vendor variants:**

- **E4M3FNUZ / E5M2FNUZ** (GraphCore): only NaN encodings, no Inf, no negative zero. "FN" = finite-only, "UZ" = unsigned-zero.

**Patent issues:**

- **EP4318224A1** (Intel) — "Instructions to convert from fp16 to fp8." Active patent prosecution covering specific conversion instruction patterns.
- The white paper authors stated FP8 was released "under open, license-free terms" but this is a public statement of intent, not a binding patent grant. No license document or covenant-not-to-sue has been published. The vendor statement may not survive corporate acquisitions or strategy changes.
- Beyond conversion: the dot-product operations on FP8 (FP8 × FP8 → FP32 accumulating) are subject to additional patent applications by NVIDIA and Intel.

**Pre-2006 prior art is essentially zero.** Some custom 8-bit FP formats existed in obscure DSPs (military and signal-processing applications used nonstandard 8-bit FP formats in the 1980s) but no widely-published 8-bit FP specification predates the 2022 work. The E4M3 deviations from IEEE (no Inf, restricted NaN encoding to extend dynamic range) are particularly novel and recent.

J-Core does not implement FP8 in v0.6. Implementations seeking to support FP8 would need explicit patent licenses from NVIDIA, Intel, and ARM, and possibly GraphCore for the FNUZ variants. This is outside the J-Core SIMD design discipline.

#### F.3.4 FP4 (MXFP4, NVFP4)

**Decision: do not implement in v0.6.**

FP4 is even more recent. The OCP Microscaling Formats (MX) Specification v1.0 was published September 2023, defining:

- **MXFP4** (OCP standard): 4-bit E2M1 elements (1 sign / 2 exponent / 1 mantissa) with a shared E8M0 (8-bit unsigned exponent) scale per 32-element block. Total: 32 × 4 + 8 = 136 bits per block.
- **NVFP4** (NVIDIA Blackwell, 2024–2025): same E2M1 element type with a shared E4M3 FP8 scale per 16-element block, plus a per-tensor scaling factor.

FP4 has only three possible significand values per sign, range −6.0 to +6.0, no Inf, no NaN.

**Hardware deployment is current:**

- NVIDIA Blackwell B200 (2025): native NVFP4 tensor cores.
- NVIDIA RTX 50-series (2025): same.
- AMD MI355X (2025–2026): MXFP4 via ROCm 7.x MFMA instructions.

**Patent issues:** NVIDIA, AMD, and Intel all have active patent prosecution covering FP4 microscaling techniques. Specific applications cover the E8M0 / E4M3 shared scale design, the per-block exponent extraction circuitry, and the dot-product operations on microscaled formats.

**Pre-2006 prior art is zero.** The concept of "block floating-point with shared exponent" exists in 1980s DSP literature (AT&T DSP32, TI TMS320 fixed-point with software-managed shared exponent), but those are *integer-mantissa* designs, not floating-point-element-with-floating-point-scale designs. MXFP4 specifically uses an FP element type combined with a shared FP-encoded scale, which is novel.

J-Core does not implement FP4 in v0.6.

### F.4 Software path: integer quantization

For ML inference workloads where narrow numeric formats are needed and FP8 / FP4 cannot be implemented, the recommended J-Core path is **integer quantization** with software-managed scaling.

**INT8 quantization** has strong pre-2006 prior art:

- TI TMS320C2x / TMS320C5x series (1985 onward) used 8-bit signed integer arithmetic with software-managed scale factors for low-power DSP applications.
- AT&T / Lucent WE-DSP series similarly.
- Standard 1990s DSP technique for low-power inference.
- v0.5's SIMDV.B + SIMDHMx variants at 8-bit lanes already cover INT8 quantization natively, with widening accumulation to MAC pair (int32 accumulator).
- For ML inference: software pre-quantises weights and activations to INT8 with per-tensor or per-channel scale factors stored separately; performs INT8 multiplications widening to INT32; rescales the INT32 accumulator at layer boundaries.

**INT4 quantization** is more recent as a published technique but the underlying mechanism (4-bit signed integer arithmetic via software shift / mask) is straightforward and unpatented:

- Software packs two INT4 values per INT8 lane.
- Multiplication uses shift-and-mask sequences plus int8 SIMD primitives.
- Accumulation widens through int16 or int32 intermediates.
- Slower than native INT4 hardware (factor of 2–4 in throughput) but legally unencumbered.

For LLM inference at INT4, this approach loses ~2x throughput versus native FP4 hardware but avoids all patent exposure. For latency-sensitive deployments this may be acceptable; for throughput-critical deployments competing with Blackwell-class hardware, the J-Core SIMD path is not competitive.

**Combining INT8 SIMD with FP32 SIMD** provides a competitive "mixed-precision" path for many ML workloads: load weights as INT8, dequantise lane-wise to FP32 via VCVT-equivalent instructions and a broadcast scale factor, accumulate in FP32. This is the standard non-tensor-core inference approach used by CPU SIMD implementations and has no FP8 / FP4 exposure.

### F.5 When to revisit

The decisions in this appendix should be revisited under the following conditions:

- **FP16:** Already approved for v0.6. No revisit needed.
- **bfloat16:** Revisit if (a) the Google IPR2021-00155 litigation resolves with format-level prior art established, (b) Intel's specific BF16 instruction patents expire (~2039+ for the earliest filings), or (c) the J-Core project obtains explicit Intel licensing for BF16 operations. Until then, software-only BF16 storage is sufficient for almost all use cases.
- **FP8:** Revisit if (a) the NVIDIA / Intel / ARM "license-free" statement is formalized into a binding patent grant or covenant-not-to-sue, or (b) ~2042+ when the 2022 patent filings approach expiration.
- **FP4:** Revisit if (a) NVIDIA / AMD provide binding patent grants for MXFP4 / NVFP4 (unlikely in the near term given active deployment), or (b) ~2043+ when the 2023 patent filings approach expiration.

Until these conditions are met, J-Core SIMD's narrow-format strategy is: implement FP16 (v0.6), recommend INT8 / INT4 quantization for ML inference, support bfloat16 as a software-managed storage format only, and document this strategic position openly so users understand the tradeoffs.

### F.6 Strategic positioning

This appendix's stance is deliberate. The J-Core project's value proposition includes architectural transparency, patent-defensive design, and accessibility to small and academic implementers. Adopting FP8 / FP4 would require either:

1. Negotiating patent licenses with NVIDIA, Intel, AMD, and ARM — which may be available to commercial implementers but is impractical for academic / hobbyist users.
2. Asserting prior art that does not exist with sufficient strength — exposing the project to potential litigation.

Neither option aligns with the project's character. By contrast, FP16 + INT8 / INT4 quantization gives J-Core SIMD a competitive position in **edge inference** and **embedded ML** workloads where peak Blackwell-class throughput is not the requirement, and where patent transparency, accessible architecture, and J-Core's open-source verification matter to the deployment.

This trade-off should be communicated openly in J-Core marketing and documentation. The product is "ML-capable SIMD with patent-clear narrow integer paths and IEEE-standard FP16," not "Blackwell competitor for hyperscale inference."

### F.7 References

- Scott, Thomas J. (March 1991). "Mathematics and computer science at odds over real numbers." *Proceedings of the 22nd SIGCSE Technical Symposium on Computer Science Education*. doi:10.1145/107004.107029.
- *HD61810 Digital Signal Processor Users Manual*, Hitachi Ltd., 1982. https://archive.org/details/bitsavers_hitachidatlSignalProcessorUsersManual_4735688
- *IEEE Standard for Floating-Point Arithmetic*, IEEE 754-2008.
- NVIDIA, Intel, ARM. "FP8 Formats for Deep Learning" white paper, September 2022. https://arxiv.org/abs/2209.05433
- *OCP 8-bit Floating Point Specification (OFP8) Revision 1.0*, Open Compute Project, December 2023.
- *OCP Microscaling Formats (MX) Specification v1.0*, Open Compute Project, September 2023.
- Intel patents relevant to BF16: US20190079767A1 (VDPBF16PS dot product), US20230069000A1 (BF16 arithmetic instructions), US12379927B2 (BF16 scale / reduce instructions).
- Intel patent relevant to FP8: EP4318224A1 (FP16 → FP8 conversion instructions).
- IPR2021-00155 (Patent No. 10,416,961): active patent proceeding concerning bfloat16 in Google TPUs.

