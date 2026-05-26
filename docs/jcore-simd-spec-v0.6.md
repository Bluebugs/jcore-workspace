# J-Core SIMD Extension — Design Specification v0.6 (Integer SIMD Primitives)

**Status:** Draft, sixth design round (integer SIMD primitives: media, signal processing, bioinformatics, analytics, and inference)
**Target:** J32 / J4 applications-class implementations (same as v0.5)
**Prerequisite:** v0.5 conformant implementation
**Backward compatibility:** Strictly additive. All v0.5 binaries execute unchanged on v0.6 hardware. v0.6 only consumes encoding space that v0.5 §8 architecturally reserved for "saturation mode" (SIMDV `rrr` field), "VNEG / VABS" (FPU unary row slots 8..15), and "extended-precision SIMD" (`0000`/`0010` row SH-2 ops not currently governed).
**Document scope:** patch document. Reads only as a delta against v0.5. New sections renumber within this document; cross-references to v0.5 use "v0.5 §N".
**Motivation note:** The proximate motivation for v0.6 was INT8/INT4 quantized LLM inference, but every addition is a general-purpose integer SIMD primitive that has been foundational for media processing, digital signal processing, bioinformatics, database analytics, computer vision, and communications since the mid-1990s. §8 documents the application landscape that justifies the gate budget. LLM inference is one application among many — not the architectural goal in isolation.

---

## 1. Overview

v0.6 adds six classes of integer SIMD primitives to v0.5:

1. **Saturating arithmetic mode** for `SIMDV` blocks, via the `rrr` field that v0.5 §3.2 reserved for "saturation mode, signed/unsigned override".
2. **VABS, VPOPCNT** as new unary governed instructions in the FPU unary row slots that v0.5 §8 reserved for "VNEG / VABS".
3. **VUNPK4** (INT4 nibble unpack to INT8 lanes) in the same unary row.
4. **VABSDIFF** (per-lane absolute difference, the SAD primitive) via reinterpretation of SH-2 `SUBC` inside a SIMD block.
5. **VPACK** (saturating narrowing pack, int16→int8 and int32→int16) via reinterpretation of SH-2 `EXTS.B`/`EXTU.B`/`EXTS.W`/`EXTU.W` inside a SIMD block.
6. **VMULSU** (mixed-sign multiply: signed × unsigned) via reinterpretation of SH-2 `DMULS.L` inside a SIMD block.

No new prefix instructions. No new architectural state. No new register files. The v0.5 register file (V0..V15, P0, MAC pair, FPUL, DR0) is unchanged. The v0.5 prefix encoding (`SIMDV` / `SIMDH<r>`) is unchanged except that the previously-must-be-zero `rrr` field in `SIMDV` now carries the saturation modifier.

### 1.1 Motivation

These six primitives have a long and broad history. Saturating arithmetic, multiply-accumulate with widening, byte-wise absolute difference reduced across lanes, narrowing pack with clipping, mixed-sign multiply-sum, byte-wise population count, and nibble-packed integer unpack are not novel operations — every commodity SIMD ISA shipped between 1996 and 2002 (MMX, AltiVec, MIPS MDMX, SPARC VIS, ARMv6 SIMD) provided most of them, and the underlying compute patterns appear in Cray vector machines and CDC scalar machines back to the 1960s.

The proximate motivation for v0.6 was identifying which of these primitives an INT8/INT4 quantized LLM inference kernel needs and finding that v0.5 was missing a handful. But the resulting set is general-purpose:

- **Media processing** — video codecs, audio mixers, image filters, edge detectors.
- **Digital signal processing** — FIR/IIR filtering, demodulation chains, fixed-point pipelines, ADPCM codecs.
- **Bioinformatics** — short-read mapping, FM-index, BAM/CRAM parsing, bit-parallel edit distance.
- **Database analytics and search** — Roaring bitmaps, HyperLogLog, LSH/SimHash, columnar nibble-packed encodings.
- **Computer vision** — block-matching motion estimation, stereo disparity, binary feature descriptors, ORB-SLAM.
- **Communications** — Viterbi decoding, LDPC/BCH syndrome weight, SDR chains.
- **Games and simulation** — chess/Go bitboards, cellular automata, time-series similarity.
- **LLM inference** — INT8/INT4 GEMV with on-the-fly weight dequantization and saturating requantization.

Section 8 enumerates the algorithms by domain. The cumulative gate cost (≈ 4k gates, §6) is justified by the breadth of beneficiaries rather than by any single workload.

### 1.2 What this patch is *not*

v0.6 is not a matrix-engine extension. Outer-product instructions (AMX/SME class) are deferred to v0.7+. v0.6 is not a floating-point patch either — FP16 is deferred and BF16/FP8/FP4 are explicitly excluded for patent reasons (v0.5 §10 item 1). v0.6 is the integer SIMD primitives layer that those future extensions will compose against.

---

## 2. Saturating arithmetic mode (SIMDV `rrr` field)

### 2.1 Encoding

The `SIMDV` prefix gains a saturation modifier. v0.5 §3.2 required `rrr = 000` on `SIMDV` and reserved non-zero values; v0.6 defines:

| `rrr` | Mnemonic suffix | Modifier | Notes |
|---|---|---|---|
| 000 | `SIMDV` (no suffix) | wrap (v0.5 default) | Two's-complement wrap on overflow; no flag set. Identical to v0.5 behaviour. |
| 001 | `SIMDVS` | signed saturating | Result clamped to `[INT_MIN_w, INT_MAX_w]` per lane. |
| 010 | `SIMDVU` | unsigned saturating | Result clamped to `[0, UINT_MAX_w]` per lane. |
| 011 | reserved | — | Slot-illegal on v0.6; reserved for "halving" arithmetic (vhadd-class). |
| 100–111 | reserved | — | Slot-illegal on v0.6. |

`SIMDH` prefixes ignore the saturation modifier (the reduction operator already implies the destination type and width per v0.5 §2.3). Setting non-default `rrr` on a `SIMDH` prefix uses the v0.5 reduction-operator encoding and is unaffected by v0.6.

### 2.2 Affected governed instructions

The saturation modifier applies only to integer governed instructions whose result type matches the lane width and where overflow is meaningful:

| Governed instruction | Wrap (v0.5) | Signed sat (v0.6 SIMDVS) | Unsigned sat (v0.6 SIMDVU) |
|---|---|---|---|
| `ADD Vm, Vn` | wrap | clamp to `[INT_MIN_w, INT_MAX_w]` | clamp to `[0, UINT_MAX_w]` |
| `SUB Vm, Vn` | wrap | clamp to `[INT_MIN_w, INT_MAX_w]` | clamp at 0 (no negative result) |
| `NEG Vm, Vn` | wrap (so `NEG -128 = -128` at w=8) | clamp (so `NEG -128 = 127` at w=8) | slot-illegal (no negation of unsigned) |
| `SHAD Vm, Vn` | wrap on left-shift | clamp on left-shift overflow | clamp on left-shift overflow |
| `SHLD Vm, Vn` | wrap on left-shift | (logical shift; treat as unsigned) | clamp on left-shift overflow |
| `MULS Vm, Vn` (vertical) | result widens per v0.5 §2.3, no overflow | n/a (no overflow at widened type) | n/a |
| `MULU Vm, Vn` (vertical) | result widens, no overflow | n/a | n/a |
| `AND`, `OR`, `XOR`, `NOT` | unaffected | unaffected (slot-illegal: SIMDVS+logical is meaningless) | unaffected (slot-illegal: SIMDVU+logical is meaningless) |

`SIMDVS` and `SIMDVU` with a logical-only governed instruction raise slot-illegal at decode. This catches assembler bugs early.

### 2.3 Interaction with P0 predication

Predication (v0.5 §5) is orthogonal. A predicated saturating instruction applies saturation lane-wise to the active lanes only; inactive lanes preserve their previous Vn value as usual.

### 2.4 Examples

```asm
; Signed-saturating add of two int8 vectors (no wrap on overflow)
simdvs.b #1
add      V2, V1                  ; V1 := sat_s8(V1[i] + V2[i]) for each of 16 lanes

; Unsigned-saturating subtract for activation residual
simdvu.b #1
sub      V2, V1                  ; V1 := max(0, V1[i] - V2[i])

; Saturating accumulation pattern (post-MAC re-quantization)
simdvs.h #1
shad     V2, V1                  ; V1 := sat_s16(V1[i] << V2[i]) — saturating shift for rescaling
```

---

## 3. New unary governed instructions (FPU unary row slots 8..15)

The encoding space `1111 nnnn xxxx 1101` inside a SIMD block, slots `xxxx ∈ {1000..1111}`, was reserved by v0.5 §8 with the anticipated use "VEXTRACT/VINSERT widths (FP16, FP64); VNEG / VABS". v0.6 allocates four of those eight slots.

| `xxxx` | Mnemonic | Operation | Width-aware? |
|---|---|---|---|
| 1000 | `VABS` | per-lane signed absolute value | yes (governed by prefix `ww`) |
| 1001 | `VPOPCNT` | per-lane population count | yes |
| 1010 | `VUNPK4LU` | unpack low 64 bits as 16 unsigned nibbles → 16 int8 lanes | fixed (always 8-bit output) |
| 1011 | `VUNPK4HU` | unpack high 64 bits as 16 unsigned nibbles → 16 int8 lanes | fixed |
| 1100 | `VUNPK4LS` | unpack low 64 bits as 16 signed nibbles (sign-extended to int8) | fixed |
| 1101 | `VUNPK4HS` | unpack high 64 bits as 16 signed nibbles (sign-extended to int8) | fixed |
| 1110 | reserved | — | — |
| 1111 | reserved | — | — |

### 3.1 VABS

```
VABS  Vn          1111 nnnn 1000 1101    (inside SIMD block, SIMD_VAL=1)
```

Per-lane signed absolute value at the governed width. In `SIMDV` wrap mode (`rrr=000`), `VABS INT_MIN_w = INT_MIN_w` (i.e., abs(-128) = -128 at w=8); in `SIMDVS` mode, `VABS INT_MIN_w = INT_MAX_w` (i.e., abs(-128) = 127 at w=8). The latter matches AltiVec `vabs*` and SSSE3 `PABSB`/`PABSW`/`PABSD` semantics.

`VABS` inside a `SIMDH` block participates in horizontal reduction: 16 absolute-valued lanes are then reduced by the chosen operator (typically add, giving sum-of-absolute-values).

Pre-2006 prior art: SSSE3 `PABSB`/`PABSW`/`PABSD` (Intel, 2006 specification, predates publication cutoff); MIPS MDMX `MIN.OB R0, src` against zero plus sign-extract (1996); ARMv6 unsigned-difference SAD building block (2002).

### 3.2 VPOPCNT

```
VPOPCNT  Vn       1111 nnnn 1001 1101    (inside SIMD block, SIMD_VAL=1)
```

Per-lane population count. Result is the lane's hamming weight, stored in a same-width lane:

- w=8: result in 0..8, stored in low 4 bits of each int8 lane (high bits zero).
- w=16: result in 0..16, stored in low 5 bits of each int16 lane.
- w=32: result in 0..32, stored in low 6 bits of each int32 lane.
- w=64: result in 0..64, stored in low 7 bits of each int64 lane.

`SIMDV` modifier interacts simply: saturation is meaningless (result always in `[0, w]`), so `SIMDVS`/`SIMDVU` with VPOPCNT raise slot-illegal at decode.

`VPOPCNT` inside `SIMDH<add>` gives total hamming weight across the vector (useful for binary-net dot products via XOR-then-popcount).

Pre-2006 prior art: CDC 6600 "CXi" count instruction (Cray, 1964); STAR-100 bit-count vector instruction (CDC, 1974); Cray X-MP popcount (1982); DEC Alpha `CTPOP` (1996, scalar at 64-bit); SPARC `POPC` (UltraSPARC-T2 had it; SPARC V9 architecturally optional since 1994). For per-lane SIMD popcount specifically: AltiVec did not provide one in the original 1996/1999 spec, but the operation composes trivially from per-byte LUT via `vperm` (1996). Composition is not a patent obstacle.

### 3.3 VUNPK4 family

```
VUNPK4LU  Vn      1111 nnnn 1010 1101    ; unsigned, low 64 bits
VUNPK4HU  Vn      1111 nnnn 1011 1101    ; unsigned, high 64 bits
VUNPK4LS  Vn      1111 nnnn 1100 1101    ; signed,   low 64 bits
VUNPK4HS  Vn      1111 nnnn 1101 1101    ; signed,   high 64 bits
```

INT4-to-INT8 nibble unpack. The 64-bit half of Vn is read as 16 packed 4-bit values; each nibble is zero-extended (`U` variants) or sign-extended (`S` variants) to 8 bits, and the 16 resulting int8 values are written across the full 128 bits of Vn. The unaccessed half of input Vn is discarded.

Nibble order within each byte is **low nibble first** (lane 0 = byte0[3:0], lane 1 = byte0[7:4], lane 2 = byte1[3:0], ...). This matches the canonical little-endian INT4 packing used by GGML/llama.cpp, AWQ, and GPTQ weight formats, and matches SH's existing little-endian-within-byte convention for shift-and-mask software.

Width modifier (`ww`) from the prefix is **ignored** for VUNPK4 — the operation is fixed to produce 16 int8 lanes from 16 nibbles. The prefix must still be `SIMDV.B` (or any valid prefix; the lane width is implicit). `SIMDV.W/.L/.Q` with VUNPK4 raise slot-illegal.

Predication via P0 applies at byte granularity to the 16 output lanes.

Pre-2006 prior art: nibble-packed integer storage (BCD / packed-decimal) is foundational since 1950s mainframes. SH-2 already provides single-instruction nibble extraction via `EXTU.B` + `SHLR4`. AltiVec `vmrglb`/`vmrghb` (1996) and MMX `PUNPCKLBW` (1996) provide the analogous byte-pair unpacking pattern from which sub-byte unpacking composes. The specific INT4→INT8 fused instruction is a trivial datapath composition (two parallel AND-masks and two parallel sign- or zero-extends) that any pre-2006 SIMD ISA could have provided; absence of an exact instruction predicate predates the patent landscape and the composition is not novel.

### 3.4 Implementation cost

All four families share the FPU unary row decode and write back to V<n>. Per-lane cost:

- VABS: a per-lane two's-complement negate + select (16 × 8-bit at w=8; 8 × 16-bit at w=16; 4 × 32-bit at w=32). The saturation case adds a single comparator per lane.
- VPOPCNT: a per-lane popcount tree. At w=8 this is 7 half-adders per lane (Wallace tree ~30 gates); at w=64 it is 63 half-adders per lane (~270 gates). 16 lanes at w=8 dominate the area; w=64 has only 2 lanes so cost is dominated by per-lane tree.
- VUNPK4: a fan-out from 4 bits to 8 bits per lane (4 AND-gates with mask + 4 sign-extend muxes). 16 lanes parallel. Trivial.

Total v0.6 unary additions: ≈ 2k–4k gates at J4-class width, dominated by VPOPCNT.

---

## 4. New 2-operand governed instructions (reinterpreted SH-2 ops)

### 4.1 VABSDIFF — reinterpret `SUBC Rm, Rn`

```
SH-2 outside SIMD:  SUBC      Rm, Rn      0011 nnnn mmmm 1010
v0.6 inside SIMD:   VABSDIFF  Vm, Vn      0011 nnnn mmmm 1010
```

Per-lane absolute difference: `Vn[i] := |Vm[i] − Vn[i]|` at the governed width. Useful as the SAD primitive.

In `SIMDV.B`, computes 16 byte-wise absolute differences. In `SIMDV.W`, 8 halfword absolute differences. Saturation modifier from §2 applies (signed saturating |diff| matters only when widening, since `|INT_MIN - INT_MAX|` overflows the lane width).

In `SIMDH<add>.B`, the per-lane absolute differences are summed and widened into MACL per the v0.5 §2.3 reduction rule. This is **single-instruction 16-byte SAD** (after the two source loads):

```asm
clrmac
vld.q     @r4+, V1
vld.q     @r5+, V2
simdh.b   #1
vabsdiff  V2, V1              ; MACL := Σ |V1[i] - V2[i]| for i in 0..15
```

Pre-2006 prior art: DEC Alpha `PERR` ("Pixel Error", 1996) — sum of byte-wise absolute differences across 8 bytes, accumulator-style. MIPS MDMX `RACL.OB` / `RACM.OB` accumulator-reduction ops (1996). Intel SSE `PSADBW` (1999). ARMv6 `USAD8` / `USADA8` (2002). The fused SAD-with-reduction pattern has multiple independent 1996 sources.

### 4.2 VPACK family — reinterpret `EXTS.B` / `EXTU.B` / `EXTS.W` / `EXTU.W`

```
SH-2 outside SIMD:  EXTS.B    Rm, Rn      0110 nnnn mmmm 1110
v0.6 inside SIMD:   VPACK.SS  Vm, Vn      0110 nnnn mmmm 1110

SH-2 outside SIMD:  EXTU.B    Rm, Rn      0110 nnnn mmmm 1100
v0.6 inside SIMD:   VPACK.SU  Vm, Vn      0110 nnnn mmmm 1100

SH-2 outside SIMD:  EXTS.W    Rm, Rn      0110 nnnn mmmm 1111
v0.6 inside SIMD:   VPACKW.SS Vm, Vn      0110 nnnn mmmm 1111

SH-2 outside SIMD:  EXTU.W    Rm, Rn      0110 nnnn mmmm 1101
v0.6 inside SIMD:   VPACKW.SU Vm, Vn      0110 nnnn mmmm 1101
```

Saturating narrowing pack. Two-operand: source halves come from both Vm and Vn; destination is Vn. The mnemonic suffix carries the saturation policy:

- **VPACK.SS** — source treated as int16, narrowed signed-saturating to int8.
- **VPACK.SU** — source treated as int16, narrowed unsigned-saturating to uint8 (i.e., clamped to `[0, 255]`).
- **VPACKW.SS** — source treated as int32, narrowed signed-saturating to int16.
- **VPACKW.SU** — source treated as int32, narrowed unsigned-saturating to uint16.

Lane assignment (using VPACK.SS as the illustrative case, 8 int16 lanes per source register):

```
Vn[0..7]   := sat_s8(Vm[0..7])    ; low 8 output bytes from Vm
Vn[8..15]  := sat_s8(Vn[0..7])    ; high 8 output bytes from Vn (source overwritten in place)
```

This is the standard pack convention from MMX `PACKSSWB`. The Vn-source-Vn-dest pattern means the dest absorbs its own low half as the high output half — software places the "left" tensor in Vm and the "right" tensor in Vn before VPACK.

The width modifier in the prefix is **ignored** for VPACK (the SS/SU/W variants encode the width pair explicitly). Prefix must be `SIMDV.B` for the int16→int8 variants and `SIMDV.W` for the int32→int16 variants, otherwise slot-illegal.

P0 predication applies at output-lane granularity.

Pre-2006 prior art: MMX `PACKSSWB`, `PACKUSWB`, `PACKSSDW` (Intel, 1996). AltiVec `vpkshss`, `vpkshus`, `vpkswss`, `vpkswus` (Motorola/IBM/Apple, 1996/1999). MIPS MDMX `PACKSC` (1996). Pack-with-saturation has overlapping 1996 sources across three major ISAs — patent landscape is clear.

### 4.3 VMULSU — reinterpret `DMULS.L Rm, Rn`

```
SH-2 outside SIMD:  DMULS.L   Rm, Rn      0011 nnnn mmmm 1101
v0.6 inside SIMD:   VMULSU    Vm, Vn      0011 nnnn mmmm 1101
```

Mixed-sign multiply: lanes of Vm treated as **signed**, lanes of Vn treated as **unsigned**. Per-lane product is signed at twice the source width (e.g., int8 × uint8 → int16).

In `SIMDV.B`:
- 16 lanes: `result_lane[i] := int16(int8(Vm[i]) × uint8(Vn[i]))`
- Result widens to int16 per lane; written across two destinations or to Vn truncated — see §5 for the reduction-mode case which is the common one.

In `SIMDH<add>.B #1`:
- Per-lane products are summed and widened into MACL per the v0.5 §2.3 rule.
- **This is the VNNI/SDOT semantics**: `MACL := Σ int16(int8(Vm[i]) × uint8(Vn[i]))` over 16 lanes.

This is the canonical operation for quantized inference where weights are int8 (signed, symmetric quantization) and activations are uint8 (unsigned, asymmetric quantization with non-zero zero-point). Without VMULSU, the same operation requires either pre-subtracting the activation zero-point (extra arithmetic per inner loop) or running two MULS passes and combining.

Pre-2006 prior art: AltiVec `vmsummbm` (Multiply-Sum of Mixed Bytes), Motorola/IBM/Apple, 1996 — explicitly defined as 4 unsigned bytes × 4 signed bytes per lane, summed and added to int32 accumulator. Documented in AltiVec PEM (NXP doc ALTIVECPEM, freely distributed) section 6.95–6.96. Independently in TMS320C6x DSP "smpyhl" mixed-sign multiply (TI, 1997). The mixed-sign byte multiply-accumulate pattern is unambiguously pre-2000.

### 4.4 Vertical-mode VMULSU result placement

When `VMULSU Vm, Vn` is used in `SIMDV.B` (vertical, not reductive), the per-lane int16 products do not fit in the int8 lane of Vn. v0.6 specifies: the **low byte** of each int16 product is written to Vn (i.e., truncation per lane, identical to v0.5 `MULS Vm, Vn` in vertical mode). Software that wants the full int16 result uses `SIMDH<add>.B` instead, or computes the high-byte half via subsequent shift.

This is a minor inconsistency (vertical multiplies truncate, horizontal multiplies widen) but matches v0.5's existing behaviour for governed `MULS`/`MULU` and avoids requiring a second destination register.

---

## 5. Updated widening reduction table (extends v0.5 §2.3)

The v0.5 reduction-destination table is extended with VMULSU and VABSDIFF entries:

| Operation | Lane width *w* | Per-lane intermediate | `SIMDH<add>` destination |
|---|---|---|---|
| `MULS` (v0.5) | 8 | int16 | MACL (int16 / int32) |
| `MULS` (v0.5) | 16 | int32 | MACL+MACH pair (int32 / int64) |
| `MULU` (v0.5) | 8 | uint16 | MACL (uint32) |
| `MULU` (v0.5) | 16 | uint32 | MACL+MACH (uint64) |
| **`VMULSU` (v0.6)** | **8** | **int16** | **MACL (int32)** — VNNI-equivalent |
| **`VMULSU` (v0.6)** | **16** | **int32** | **MACL+MACH (int64)** |
| **`VABSDIFF` (v0.6)** | **8** | **uint8** (always ≥ 0) | **MACL (uint16 then widened to uint32)** |
| **`VABSDIFF` (v0.6)** | **16** | **uint16** | **MACL+MACH (uint32 → uint64)** |
| `VPOPCNT` (v0.6) | 8 | uint8 (range 0..8) | MACL (uint16) |
| `VPOPCNT` (v0.6) | 64 | uint8 (range 0..64) | MACL (uint8, low byte only) |
| `VABS` (v0.6) | 8 | uint8 (range 0..128 with sat; 0..127+1 wrap edge case) | MACL (uint16) |

`VPACK` and `VUNPK4` do not produce reducible per-lane values and are slot-illegal inside `SIMDH` blocks.

---

## 6. Implementation cost summary

Cumulative cost of v0.6 additions, atop a v0.5 J4-class implementation:

| Feature | Gates (rough) | Critical path impact | Notes |
|---|---|---|---|
| Saturation in SIMDV | ~500 | none (parallel saturation muxes after ALU) | One bit per lane width; reuses existing ADD/SUB datapath. |
| VABS | ~200 | none | Negate + select; lane-parallel. |
| VPOPCNT | ~2k–3k | adds one cycle on widest lanes if naive | A Wallace-tree popcount per byte costs ~30 gates; 16 byte units = ~500 gates. The 32-bit and 64-bit per-lane trees dominate. If single-cycle popcount blows timing at the target node, allow two-cycle issue. |
| VUNPK4 | ~300 | none | Just AND-masks + sign-extend muxes. |
| VABSDIFF | ~600 | none (parallel to existing SUB datapath) | SUB result + per-lane two's-complement-and-select. |
| VPACK family | ~400 | none | Saturating clamp comparators per output lane. |
| VMULSU | ~0 | none | The existing MULS datapath already produces int16/int32 products; the only change is a sign-control bit on the multiplier's second operand, which is a single mux per multiplier. |
| **Total** | **≈ 4k gates** | **conditional one extra cycle for VPOPCNT** | Modest compared to v0.5's V-register file. |

Estimated 2–3% area increase over v0.5 J4 SIMD block. No new register file. No new pipeline stage required (with the VPOPCNT caveat above, which is an implementation choice, not architectural).

The justification for this gate budget rests on the breadth of supported workloads (§8), not on any single application. The same ≈4k gates that enable INT8 GEMV also enable: H.264/HEVC/AV1 motion estimation, BAM/CRAM nucleotide parsing, FM-index rank operations for short-read alignment, Roaring bitmap cardinality, HyperLogLog cardinality estimation, ORB-SLAM binary descriptor matching, IMA/Microsoft ADPCM decoding, Sobel/Prewitt edge detection, Viterbi soft-decision decoding, chess and Go bitboard evaluation, audio mixing with hard limiting, and dozens of other algorithms enumerated below.

---

## 7. Pre-2006 prior art consolidated for v0.6

Every v0.6 addition cites independent prior art published or released before May 2006:

| v0.6 feature | Primary prior art | Year | Source |
|---|---|---|---|
| Saturating ADD/SUB | MMX `PADDSB`/`PADDSW`/`PSUBSB`/`PSUBSW` | 1996 | Intel IA-32 Software Developer's Manual, MMX chapter |
| Saturating ADD/SUB | AltiVec `vaddsbs`/`vaddshs`/`vsubsbs`/`vsubshs` | 1996/1999 | AltiVec PEM (NXP ALTIVECPEM) §6.13–6.18 |
| Saturating ADD/SUB | Cray-1 vector saturating mode | 1976 | Cray-1 Hardware Reference Manual (HR-0004) |
| Saturating ADD/SUB | TMS320C6000 saturating MAC | 1997 | TI SPRU189 |
| VABS | SSSE3 `PABSB`/`PABSW`/`PABSD` | 2006 (just inside cutoff) | Intel IA-32 SDM Vol 2 |
| VABS | MIPS MDMX absolute via MIN.OB + sign extract | 1996 | MIPS V instruction set |
| VABS | ARMv6 implicit ABS in USAD8 building block | 2002 | ARM ARM v6 |
| VPOPCNT (scalar) | CDC 6600 CXi count | 1964 | Thornton, "Design of a Computer: The CDC 6600" |
| VPOPCNT (vector) | CDC STAR-100 bit-count | 1974 | CDC STAR-100 Programming Reference |
| VPOPCNT | DEC Alpha `CTPOP` | 1996 | Alpha AXP Architecture Reference Manual |
| VPOPCNT | SPARC V9 `POPC` (optional) | 1994 | SPARC V9 Architecture Manual |
| VUNPK4 (composition) | BCD packed-decimal storage | 1950s | IBM 1401 Reference Manual and predecessors |
| VUNPK4 (composition) | MMX `PUNPCKLBW`, AltiVec `vmrglb` | 1996 | as above |
| VABSDIFF / SAD | DEC Alpha `PERR` | 1996 | Alpha AXP Architecture Reference Manual |
| VABSDIFF / SAD | MIPS MDMX `RACL.OB` / `RACM.OB` | 1996 | MIPS V instruction set |
| VABSDIFF / SAD | Intel SSE `PSADBW` | 1999 | Intel IA-32 SDM (Pentium III) |
| VABSDIFF / SAD | ARMv6 `USAD8` / `USADA8` | 2002 | ARM ARM v6 |
| VPACK (signed sat narrow) | MMX `PACKSSWB`/`PACKSSDW` | 1996 | Intel IA-32 SDM, MMX chapter |
| VPACK (unsigned sat narrow) | MMX `PACKUSWB` | 1996 | as above |
| VPACK | AltiVec `vpkshss`/`vpkshus`/`vpkswss`/`vpkswus` | 1996/1999 | AltiVec PEM §6.79–6.82 |
| VPACK | MIPS MDMX `PACKSC` | 1996 | MIPS V instruction set |
| VMULSU (mixed-sign byte dot) | AltiVec `vmsummbm` | 1996 | AltiVec PEM §6.95 |
| VMULSU (mixed-sign byte dot) | TMS320C6x mixed-sign MAC `smpyhl` | 1997 | TI SPRU189 |
| VMULSU (mixed-sign byte dot) | Dubey, "AltiVec Extension to PowerPC Accelerates Media Processing" | 1996 | IEEE Micro, Vol 16 No 5 |

All citations predate May 2006 by ≥ 1 year, with most predating it by 9–30 years. The patent landscape is documented in v0.5 Appendix D and is unaffected by v0.6.

---

## 8. Application domains and algorithms

The v0.6 additions are integer SIMD primitives that have been foundational across many domains since the 1990s. This section documents the application landscape that justifies the gate budget. The LLM inference case (§9.1–§9.4) is one beneficiary; the others below are independently substantial.

### 8.1 Quick reference — instruction to domain

| Instruction | Primary domains | Representative algorithms |
|---|---|---|
| `VPOPCNT` | bioinformatics, search, vision, comms, games, analytics, ML | Hamming distance, FM-index rank, Roaring bitmap cardinality, HyperLogLog, LSH/SimHash, ORB descriptor matching, LDPC syndrome weight, chess bitboards, binary neural networks |
| `VABSDIFF` + `SIMDH<add>` | video coding, vision, signal processing, comms | H.264/HEVC/AV1 motion estimation (SAD), stereo disparity, template matching, dynamic time warping, AMDF pitch detection, Viterbi soft branch metric, background subtraction |
| `SIMDVS` / `SIMDVU` (saturating) | DSP, audio, image, video, control | FIR/IIR filters with saturating accumulators, audio mixing with hard limiting, brightness/contrast clipping, alpha blending, PID with anti-windup, fixed-point Q-format arithmetic |
| `VPACK.SS` / `.SU` / `VPACKW` | media, sensor data, fixed-point chains | 16→8 bit audio with limiting, HDR-to-SDR tone mapping, 10/12-bit video to 8-bit display, ADC narrowing with saturation guard |
| `VUNPK4` family | bioinformatics, audio codecs, retro graphics, BCD, LLM weights | BAM/CRAM nucleotide parsing, IMA/Microsoft ADPCM decoding, 16-color palette graphics, packed-decimal arithmetic, GPTQ/AWQ/GGUF Q4_K weight streaming |
| `VABS` | DSP, image, statistics, optimization | Sobel/Prewitt edge magnitude, audio rectification and envelope detection, L1 norm, MAD outlier detection, LASSO/L1 regression |
| `VMULSU` | image filtering, signal correlation, LLM inference | Gaussian/sharpen/emboss kernels (signed kernel × unsigned pixel), cross-correlation, INT8 GEMV with asymmetric quantization |

### 8.2 Computer vision and video coding

**Video encoder motion estimation** is the canonical user of `VABSDIFF + SIMDH<add>`. H.264, H.265/HEVC, VP9, AV1, and VVC all rely on sum-of-absolute-differences over 4×4 through 64×64 blocks against candidate reference positions as the inner loop of inter-prediction. x264, x265, libvpx, libaom, and SVT-AV1 spend the majority of their encoding time in hand-tuned SAD kernels. The v0.6 path is `vld.q @r4+, V1 ; vld.q @r5+, V2 ; simdh.b #1 ; vabsdiff V2, V1` — four instructions per 16-byte SAD chunk, fully memory-bound at j-core silicon clocks.

**Binary feature descriptors** — BRIEF, ORB, FREAK, BRISK — encode local image regions as 128–512 bit strings compared by Hamming distance. **ORB-SLAM**, the dominant visual-SLAM stack, runs binary descriptor matching as its inner loop. The pattern is XOR (already in v0.5 governed list) + `VPOPCNT` + `SIMDH<add>`.

**Image edge detection** — Sobel, Prewitt, Scharr — computes per-pixel gradient magnitudes as `|Gx| + |Gy|`. The `VABS` lane operation feeds the magnitude approximation. With saturating arithmetic in `SIMDVU` mode, the magnitude can be safely accumulated without overflow into a uint8 output image.

**Image filtering** with signed kernels (Gaussian, sharpen, emboss, Laplacian) on unsigned pixels uses `VMULSU + SIMDH<add>` as the convolution inner loop. Without `VMULSU`, the kernel weights must be biased to unsigned or pixels biased to signed at extra arithmetic cost per output pixel.

**Other vision uses**: stereo disparity estimation via windowed SAD (`VABSDIFF`); template matching (`VABSDIFF` for `TM_SQDIFF`-style metrics); background subtraction (per-pixel `VABSDIFF` against a learned model); image registration and change detection in remote sensing.

### 8.3 Bioinformatics and genomics

**Short-read mapping.** Bowtie 2, BWA-MEM, and minimap2 use Hamming distance between k-mers as the seeding metric: encode nucleotides at 2 bits per base, pack 64 bases into a 128-bit V register, compute XOR + `VPOPCNT` + horizontal sum. v0.6 reduces this inner loop to four instructions per 64-base comparison.

**FM-index and BWT.** Backward search on the Burrows-Wheeler transform requires `rank(c, i)` — the count of character `c` in `T[0..i]` — implemented as `VPOPCNT` on a bit-vector per character. BWA, salmon, kallisto, and bowtie2's index lookups are all popcount-bound.

**Myers' bit-parallel approximate matching.** Edit-distance computation reformulated as bit operations across an alphabet bitmap; the inner loop is XOR / AND / popcount, all v0.5 + v0.6 primitives.

**BAM/CRAM nucleotide parsing.** The SAM/BAM specification stores nucleotides as 4-bit codes (A=1, C=2, G=4, T=8, N=15, plus IUPAC ambiguity codes). Every read in every BAM file is nibble-unpacked at parse time by samtools and htslib. v0.6's `VUNPK4LU` / `VUNPK4HU` makes this one instruction per 16 nucleotides.

**Variant calling and consensus.** Per-position base counting reduces to `VPOPCNT` over per-base masks; quality-score filtering uses `VABSDIFF` against thresholds.

### 8.4 Database analytics, search, and information retrieval

**Compressed bitmap indexes.** Roaring bitmaps, EWAH, and WAH compress sparse and dense bitmaps for OLAP queries. AND/OR/XOR-then-cardinality is the hot path, and the cardinality step is `VPOPCNT`. Apache Druid, Apache Pinot, ClickHouse (where bitmap encoding is used), and BlinkDB all benefit.

**HyperLogLog and cardinality sketches.** Count-distinct queries via HyperLogLog rely on leading-zero counts (a single-bit-position version of popcount) and final-register popcount. Used in every modern analytic database (Redshift, BigQuery, Snowflake, Presto).

**Locality-sensitive hashing and SimHash.** Near-duplicate detection at web scale, plagiarism detection, near-neighbor search for high-dimensional vectors compressed to binary codes. Each query is `xor + VPOPCNT + threshold compare` per candidate. The integer-side dual of cosine similarity.

**MinHash.** Set similarity via min-hash signatures; comparison uses `VPOPCNT` of XOR'd signature blocks.

**Bloom filters.** Fill-rate monitoring uses `VPOPCNT`; intersection cardinality estimation uses XOR + `VPOPCNT`.

**Columnar storage.** Bit-packed columns at 4-bit, 6-bit, or other sub-byte widths benefit from `VUNPK4` (for the 4-bit case directly) and from `VPACK` (for narrowing aggregation results back into compact storage).

### 8.5 Audio, signal processing, and DSP

**Audio mixing.** Summing N tracks of 16-bit samples into a 32-bit accumulator, then narrowing back to 16-bit with signed saturation — the classic mixer inner loop in every DAW and game audio engine. v0.6 path: `SIMDV.W` for accumulate, `VPACKW.SS` for the saturating narrow.

**Hard limiters and audio compressors.** Brick-wall limiting *is* saturating arithmetic. `SIMDVS` + `VABS` gives the magnitude side; `SIMDVU` bounds the output.

**Audio codecs — IMA ADPCM and Microsoft ADPCM.** Both store 4-bit deltas; decoder unpacks nibbles and applies a state machine. Universally present in legacy WAV/AVI files, game audio, low-bandwidth VoIP, and embedded TTS. `VUNPK4` is the decode-side bottleneck.

**Fixed-point FIR and IIR filters.** Every DSP textbook's introductory filter implementation. Audio EQ, noise cancellation, sensor smoothing, modem signal conditioning. Saturating MAC (`SIMDVS` + governed `MULS`) prevents overflow distortion at coefficient boundaries.

**Pitch detection.** AMDF (Average Magnitude Difference Function) — a cheap alternative to autocorrelation — is `VABSDIFF + SIMDH<add>` over a lag window.

**Envelope detection and rectification.** Full-wave rectifier in compressors, AM demodulation peak detection: `VABS` over the signal block.

### 8.6 Communications, channel coding, and SDR

**Viterbi decoding.** Convolutional codes used in every legacy cellular and satellite standard (GSM, IS-95, DVB-S, DAB, AMPS, Iridium). The soft-decision branch metric is `VABSDIFF` between received symbol and constellation point, accumulated via `SIMDH<add>`.

**LDPC and turbo codes.** Iterative parity-check evaluation reduces to bitmask XOR + `VPOPCNT` for syndrome weight per check node. 5G NR, DVB-S2, Wi-Fi 6, and DOCSIS 3.1 all use LDPC.

**BCH and Reed-Solomon syndrome computation.** Cyclic code syndrome evaluation uses `VPOPCNT` for hard-decision decoders. Used in storage (Blu-ray, optical discs, NAND flash ECC), DVB, deep-space telemetry.

**Software-defined radio.** Fixed-point demodulation chains with saturating MAC (`SIMDVS` + MULS), magnitude detection (`VABS`), and constellation demapping (`VABSDIFF` per constellation point).

### 8.7 Games, AI search, and simulation

**Chess and Go engines.** Bitboard representations: 64-bit per piece type or color. Mobility evaluation, attack maps, pawn structure scoring, piece counting — all `VPOPCNT` over attack and occupancy bitboards. Stockfish, Leela Chess Zero, KataGo all run `VPOPCNT`-heavy evaluation kernels.

**Conway's Game of Life and cellular automata.** Neighbor counting on bit-packed grids: `VPOPCNT` after shift-and-mask of adjacent rows. Same pattern in Ising-model simulation and other 2D statistical-mechanics kernels.

**Sudoku and constraint solvers.** Bit-twiddling on 9-bit candidate sets per cell; `VPOPCNT` for "how many candidates remain" heuristics.

**Floyd-Warshall reachability on bitmatrices.** Per-row OR + `VPOPCNT` to track connected-component sizes.

**Time-series similarity (kNN-DTW).** Speech keyword spotting, gesture recognition, ECG classification — Dynamic Time Warping cost matrix filled with `VABSDIFF`.

### 8.8 Cryptanalysis and error-correcting codes

**Linear cryptanalysis bias counting.** Sample-vs-prediction agreement counts via XOR + `VPOPCNT`.

**Boolean function analysis.** S-box nonlinearity, linearity, and correlation-immunity bounds use Walsh-Hadamard transforms whose output magnitudes are evaluated with `VABS`.

**Side-channel hamming-weight modelling.** DPA defense analysis estimates leakage via `VPOPCNT` of intermediate state values.

**Code-based post-quantum cryptography.** McEliece-class schemes evaluate codeword weights via `VPOPCNT` at every encryption/decryption.

### 8.9 LLM inference (the proximate motivation)

Documented in detail in the worked examples §9.1–§9.4: INT8 GEMV, INT4-weight GEMV with on-the-fly unpack, SAD-based attention metrics, and the saturating-pack requantization chain. Uses `VMULSU`, `VUNPK4`, `VPACK`, and `SIMDVS`/`SIMDVU`. Notably, this case re-uses primitives that the older domains established — it is not the primary driver of the gate budget so much as a recent application of a long-established primitive set.

### 8.10 Cumulative beneficiary breadth

Counting named algorithms across §8.2–§8.9: ≈ 60 distinct algorithms in production use, spanning every major application domain that runs on a J32/J4-class CPU. The ≈ 4k gate cost (§6) amortizes across this entire surface, making v0.6 one of the highest-leverage extensions per gate in the j-core roadmap.

For implementations targeting any one of these domains specifically, the relevant subset of v0.6 instructions can be implemented and the rest left as slot-illegal for forward compatibility — the additivity rule (§10) means a partial implementation is still v0.5-conformant.

---

## 9. Worked examples

### 9.1 INT8 GEMV inner loop (weights signed, activations unsigned)

Compute `acc := acc + Σ_{k=0}^{K-1} weights[k] × activations[k]` where weights are int8, activations are uint8, accumulator is int32.

```asm
        ; r4 = weight pointer (int8), r5 = activation pointer (uint8), r6 = K (bytes)
        ; result accumulates into MACL+MACH
        clrmac
        mov     r6, r0
        shlr2   r0
        shlr2   r0                  ; r0 = K / 16 (loop iterations)
.loop:
        vld.q   @r4+, V1            ; 16 int8 weights
        vld.q   @r5+, V2            ; 16 uint8 activations
        simdh.b #1
        vmulsu  V1, V2              ; MACL += Σ int16(int8(V1[i]) × uint8(V2[i]))
        dt      r0
        bf      .loop
        ; MACL+MACH now holds the int32 dot product
```

Inner loop: 5 instructions per 16-element chunk. At one issue per cycle, that's 16 MAC/cycle/5 = 3.2 MAC/cycle effective. With dual-issue on J4 and proper scheduling, approaches 8 MAC/cycle. Memory-bound at ≥200 MHz with typical embedded DRAM.

### 9.2 INT4-weight GEMV inner loop

Compute the same dot product but with int8 weights packed as 4-bit nibbles (2× weight compression):

```asm
        ; r4 = packed int4 weight pointer (8 weights per byte, 32 weights per qword)
        ; r5 = uint8 activation pointer
        ; r6 = K / 32 (number of 32-element chunks)
        clrmac
.loop:
        vld.q   @r4+, V1            ; 32 packed int4 weights (16 bytes = 32 nibbles)
        vld.q   @r5+, V2            ; first 16 activations
        vld.q   @r5+, V3            ; next 16 activations

        ; Unpack low half of V1 (16 nibbles -> 16 int8 in V4)
        simdv.b #1
        vmov    V1, V4
        simdv.b #1
        vunpk4ls V4                 ; V4 := signed-extend low 16 nibbles to 16 int8

        ; Unpack high half of V1 (16 nibbles -> 16 int8 in V1, in place)
        simdv.b #1
        vunpk4hs V1                 ; V1 := signed-extend high 16 nibbles to 16 int8

        ; Two dot products
        simdh.b #1
        vmulsu  V4, V2              ; MACL += 16 mixed-sign products
        simdh.b #1
        vmulsu  V1, V3              ; MACL += next 16 mixed-sign products

        dt      r6
        bf      .loop
```

10 instructions per 32-element chunk = ~0.31 instructions per weight. 32 MAC per loop iteration. The INT4 unpack adds ~3 instructions of overhead per 32 weights — small compared to the gain of 2× weight bandwidth.

### 9.3 SAD-based attention or distance kernel

Compute `dist := Σ |a[i] - b[i]|` over a 64-byte block:

```asm
        clrmac
        mov     #4, r0              ; 4 × 16-byte chunks = 64 bytes
.loop:
        vld.q   @r4+, V1
        vld.q   @r5+, V2
        simdh.b #1
        vabsdiff V2, V1             ; MACL += Σ |V1[i] - V2[i]| over 16 lanes
        dt      r0
        bf      .loop
```

4 instructions per 16-byte chunk, including loads. MACL holds the running SAD; widen-to-MACH guards against overflow up to 2^32 / 255 ≈ 16M-element sums.

### 9.4 Saturating requantization after MAC

After a dot product accumulates int32 in MACL, requantize to int8 with a per-tensor scale and zero-point:

```asm
        ; Assume MACL holds dot product, r0 = scale (Q16), r1 = zero_point (uint8)
        sts     macl, r2            ; r2 := dot product (int32)
        muls.w  r0, r2              ; r2 := scale × dot (Q16 × int32 → int48 in MAC)
        sts     macl, r2            ; round-to-nearest happens via the >> 16 step
        shar    #16, r2             ; arithmetic right shift by 16 = back to integer domain
        add     r1, r2              ; add zero point
        ; now use VPACK in a SIMD block, or saturate scalar via the v0.6 path
```

For the SIMD case, requantization happens after the loop on the V-register containing N accumulated int32 lanes:

```asm
        ; V1 holds 4 × int32 accumulator lanes; V0 holds 4 × int32 (scale × dot >> 16) results
        ; Pack V1 (int32) -> V2 (int16) with signed saturation
        simdv.w #1
        vpackw.ss V1, V2

        ; Now V2 holds 8 × int16 (4 from V1 source + 4 prev V2 source);
        ; pack int16 -> int8 with unsigned saturation (because output is uint8)
        simdvu.b #1
        vpack.su  V2, V3            ; V3 holds 16 × uint8 result
```

Two pack instructions chain int32 → int16 → uint8 with saturation at each step. This closes the inference loop end-to-end.

### 9.5 H.264 / HEVC / AV1 motion-estimation SAD (16×16 block)

The hottest inner loop of every software video encoder. Compute sum-of-absolute-differences between a 16×16 current block and a 16×16 reference candidate.

```asm
        ; r4 = current block pointer (256 bytes, row-major)
        ; r5 = reference block pointer (256 bytes, from motion-compensation predictor)
        ; result: MACL+MACH := Σ |cur[i] - ref[i]| over 256 bytes
        clrmac
        mov     #16, r0                 ; 16 rows of 16 bytes each
.row:
        vld.q   @r4+, V1                ; 16 current pixels
        vld.q   @r5+, V2                ; 16 reference pixels
        simdh.b #1
        vabsdiff V2, V1                 ; MACL += Σ |V1[i] - V2[i]| over 16 lanes
        dt      r0
        bf      .row
        ; MACL+MACH holds the full 16×16 SAD (max = 256 × 255 = 65,280, fits in 17 bits)
```

5 instructions per row, 16 rows = 80 instructions per 256-byte SAD. Comparable to the ARM NEON `SABD + UADDLV` path; equivalent throughput-per-cycle. The encoder typically issues this kernel ~10⁴–10⁶ times per frame during motion search; v0.6 makes it competitive on j-core silicon for low-bitrate or sub-1080p encoding workloads.

### 9.6 Bioinformatics: k-mer Hamming distance for short-read alignment

Bowtie 2, BWA-MEM, and minimap2 use Hamming distance between k-mers as the seed-comparison primitive. Encode nucleotides at 2 bits per base, pack 64 bases into a 128-bit V register, compute XOR-then-popcount across a sequence.

```asm
        ; r4 = query encoded sequence pointer (2-bit packed nucleotides)
        ; r5 = subject encoded sequence pointer
        ; r6 = number of 16-byte chunks (each chunk = 64 nucleotides)
        ; result: MACL := total bit-Hamming distance over the compared region
        clrmac
.chunk:
        vld.q   @r4+, V1                ; 64 nucleotides (2 bits each)
        vld.q   @r5+, V2                ; 64 nucleotides
        simdv.b #1
        xor     V2, V1                  ; V1 := bitmap of differing bits
        simdh.b #1
        vpopcnt V1                      ; MACL += hamming weight of V1
        dt      r6
        bf      .chunk
        ; For 2-bit encoding, a base mismatch contributes 1 or 2 bits.
        ; Bit-hamming bounds base-hamming: bit_hd/2 ≤ base_hd ≤ bit_hd.
        ; Exact base-hamming: insert "OR adjacent bit pairs" step before vpopcnt.
```

5 instructions per 64-base comparison = 0.078 instructions per base. The full BWA seed-extension pipeline composes this with a small amount of branching for the seed-extension state machine; the inner Hamming loop is no longer the bottleneck.

The same pattern accelerates **SimHash near-duplicate detection** (replace nucleotide-encoded sequences with SimHash signatures), **ORB descriptor matching** in visual SLAM (32-byte binary descriptors), and **LDPC syndrome weight** in iterative decoders (replace inputs with parity-check matrix rows).

### 9.7 BAM-format 4-bit nucleotide unpack

The SAM/BAM specification packs nucleotides at 4 bits per base. Every read in every BAM file is unpacked at parse time by samtools, htslib, and downstream variant callers.

```asm
        ; r4 = packed source (16 bytes input = 32 nucleotides as 4-bit codes)
        ; r5 = byte destination (32 bytes output, one byte per nucleotide code)
        vld.q   @r4+, V1                ; 16 packed bytes (32 nucleotides)
        simdv.b #1
        vmov    V1, V2                  ; duplicate V1 into V2

        simdv.b #1
        vunpk4lu V1                     ; V1 := 16 nucleotide codes from low nibbles
        simdv.b #1
        vunpk4hu V2                     ; V2 := 16 nucleotide codes from high nibbles

        vst.q   V1, @r5
        add     #16, r5
        vst.q   V2, @r5                 ; 32 unpacked nucleotide-code bytes total
```

5 instructions to unpack 32 nucleotides = 0.16 instructions per base. Without `VUNPK4`, the same operation requires ~3 instructions per byte processed (shift, AND-mask, OR into output) for ~10× the work. The BAM parser hot loop becomes memory-bound rather than compute-bound, freeing CPU cycles for the variant-calling work downstream.

### 9.8 Audio mixing with hard limiting

Sum N tracks of 16-bit signed samples into an output with brick-wall saturation — the classic DAW and game-audio mixer inner loop.

```asm
        ; r4 = track A pointer, r5 = track B pointer, r6 = track C pointer, r7 = track D pointer
        ; r8 = output pointer, r9 = block count (8 samples = 16 bytes per block)
.loop:
        vld.q   @r4+, V1                ; 8 int16 samples from track A
        vld.q   @r5+, V2

        simdvs.w #1
        add     V2, V1                  ; V1 := sat_s16(V1 + V2) — no overflow distortion

        vld.q   @r6+, V3
        simdvs.w #1
        add     V3, V1                  ; V1 += track C, saturating

        vld.q   @r7+, V4
        simdvs.w #1
        add     V4, V1                  ; V1 += track D, saturating

        vst.q   V1, @r8
        add     #16, r8

        dt      r9
        bf      .loop
        ; Output stream is bit-exact saturated mix; no clicks/wraparound at peak levels.
```

12 instructions per 8-sample block = 1.5 instructions per output sample. The same pattern with a different lane width handles 32-bit float audio after a pre-conversion to fixed-point, or 24-bit audio with `simdvs.l` for 32-bit-wide processing.

This kernel applies unchanged to **alpha blending in image compositors** (per-pixel saturating add of premultiplied alpha contributions), **particle additive blending in graphics**, and any other domain where bounded accumulation matters.

---

## 10. Backward compatibility

v0.5 binaries:

- Have `rrr = 000` on every `SIMDV` prefix (only legal v0.5 encoding). v0.6 treats this as the wrap mode — identical behaviour.
- Do not emit instructions in the unary row slots 8..15 (architecturally reserved in v0.5). v0.6 binaries that emit `VABS`/`VPOPCNT`/`VUNPK4` would trap on v0.5 hardware (`slot-illegal`), which is the correct behaviour for a forward-incompatible instruction set.
- Do not emit `SUBC`, `EXTS.B/W`, `EXTU.B/W`, or `DMULS.L` inside a SIMD block (v0.5 §4 enumerated the governed instruction list and those are not in it). v0.6 binaries that do so would have been slot-illegal on v0.5 — v0.6 redefines them inside a SIMD block, but outside a SIMD block they retain their SH-2 semantics, so v0.5 scalar code is unaffected.

Strict additivity is preserved.

**Partial implementations.** An implementation targeting a specific application domain may implement only the relevant subset of v0.6 instructions and leave the rest as slot-illegal. The partial implementation remains v0.5-conformant; programs that try to use unimplemented v0.6 features will trap rather than mis-execute. Suggested subsets:

- **Bitmap analytics / search / bioinformatics focus**: `VPOPCNT` + saturating modes. ~3k gates.
- **Video / vision focus**: `VABSDIFF` + `VABS` + saturating modes. ~1.5k gates.
- **DSP / audio focus**: saturating modes + `VPACK` family + `VABS`. ~1.5k gates.
- **LLM inference focus**: `VMULSU` + `VUNPK4` + `VPACK` + saturating modes. ~1.5k gates.
- **Full v0.6**: all of the above. ~4k gates.

---

## 11. Open questions deferred to v0.7

1. **Fused load-MAC for the tightest inference inner loop.** A `VLDMACSU @Rm+, @Rn+, V<acc>` instruction would do two post-increment loads and one VMULSU horizontal step in a single 16-bit encoding, halving the inner-loop instruction count. Cost: requires a new opcode and a load-multiply-accumulate composite functional unit. Defer pending workload measurement on v0.6 baseline.

2. **VDOT4** as a single-instruction form of `simdh.b #1 ; vmulsu`. Same semantics, half the instruction count, no functional difference. Defer pending opcode space audit.

3. **Block-floating-point requantization mode** (per-block exponent, like MX formats but patent-clean — Cray-1 had per-vector exponent in 1976). Could compose entirely from v0.6 + v0.5 primitives in software; hardware support would need its own architectural design round.

4. **Wider VPOPCNT pre-aggregation.** A `VPOPCNT.SUM` that combines per-lane popcount and horizontal-add in one micro-op (saving the second instruction) would make XOR-popcount binary nets very tight. Pre-2006 prior art: Cray X-MP whole-register popcount with implicit reduction (1982). Defer.

5. **INT2 / ternary unpack.** Same shape as VUNPK4 with 2 bits per lane instead of 4. Prior art: BCD-style 2-bit packing is older than computing. Defer pending workload demand.

---

## Appendix A. v0.6 encoding summary delta

**Prefix (outside SIMD block):**

```
SIMDVS.w #N         1111 0ww0 01NN 1111   ; rrr=001, signed saturating
SIMDVU.w #N         1111 0ww0 10NN 1111   ; rrr=010, unsigned saturating
                    (rrr=011..111 slot-illegal)
```

**Governed integer instructions (inside SIMD block, additions to v0.5 §4):**

```
VABS      Vn       1111 nnnn 1000 1101   ; unary, in FPU unary row slot 8
VPOPCNT   Vn       1111 nnnn 1001 1101   ; unary, slot 9
VUNPK4LU  Vn       1111 nnnn 1010 1101   ; unary, slot 10
VUNPK4HU  Vn       1111 nnnn 1011 1101   ; unary, slot 11
VUNPK4LS  Vn       1111 nnnn 1100 1101   ; unary, slot 12
VUNPK4HS  Vn       1111 nnnn 1101 1101   ; unary, slot 13
                   1111 nnnn 1110 1101   ; reserved (was VNEG candidate; NEG already governed)
                   1111 nnnn 1111 1101   ; reserved

VABSDIFF  Vm, Vn   0011 nnnn mmmm 1010   ; reinterpret SUBC
VPACK.SS  Vm, Vn   0110 nnnn mmmm 1110   ; reinterpret EXTS.B
VPACK.SU  Vm, Vn   0110 nnnn mmmm 1100   ; reinterpret EXTU.B
VPACKW.SS Vm, Vn   0110 nnnn mmmm 1111   ; reinterpret EXTS.W
VPACKW.SU Vm, Vn   0110 nnnn mmmm 1101   ; reinterpret EXTU.W
VMULSU    Vm, Vn   0011 nnnn mmmm 1101   ; reinterpret DMULS.L
```

**Updated reserved encoding space (v0.5 §8 → v0.6 §A):**

- FPU unary row slots `1110 1101` and `1111 1101` remain reserved (down from 8 to 2 free unary slots).
- Prefix `rrr` reserved bits down from 8 codepoints to 5 (now 011..111 reserved in SIMDV).
- v0.5 reserved range "MAC.W, MAC.L, MULL, DMULS, DMULU in `0000`/`0010` rows" is reduced by 1 (DMULS.L consumed by VMULSU); remaining ~63 codepoints still available.

Total v0.6 encoding consumption: ≈ 9 new instruction families, ~80 codepoints out of v0.5's ≈ 22,000 reserved.

---

## Appendix B. References for v0.6 additions (additive to v0.5 Appendix C)

- AltiVec Technology Programming Environments Manual, Motorola/Freescale/NXP doc ALTIVECPEM, Rev. 3, 2006. §§ 6.13–6.18 (saturating add/sub), §§ 6.79–6.82 (saturating pack), § 6.95 (vmsummbm mixed-byte multiply-sum).
- Dubey, P. K. "AltiVec Extension to PowerPC Accelerates Media Processing." *IEEE Micro*, Vol 16, No 5, Sept/Oct 1996, pp. 49–55.
- DEC Alpha AXP Architecture Reference Manual, 2nd ed., Digital Press / Butterworth-Heinemann, 1995/1996. Sections on PERR (sum of byte differences) and CTPOP (population count).
- MIPS V Instruction Set (MDMX), Silicon Graphics, 1996.
- Intel IA-32 Software Developer's Manual, Volume 2, 1997 edition for MMX and 1999 edition for SSE — definitions of PADDSB, PADDSW, PSUBSB, PSUBSW, PACKSSWB, PACKUSWB, PACKSSDW, PSADBW.
- Intel IA-32 SDM Volume 2, 2006 edition (March 2006), defining SSSE3 PABSB/PABSW/PABSD. Published within the design cutoff window.
- TMS320C6000 CPU and Instruction Set Reference Guide (SPRU189), Texas Instruments, 1997. Mixed-sign MAC `smpyhl` and saturating arithmetic family.
- ARM Architecture Reference Manual, ARMv6 edition, 2002. USAD8/USADA8 (sum of absolute differences).
- Cray-1 Hardware Reference Manual (HR-0004), Cray Research Inc., 1976. Vector saturating mode and per-vector exponent block-FP precedent.
- Thornton, J. E. *Design of a Computer: The Control Data 6600*. Scott, Foresman, 1970. Count instruction CXi as scalar popcount precedent.
- IBM 1401 Reference Manual, 1959. BCD packed-decimal storage as nibble-packing precedent.

**Note on cutoff.** All v0.6 design inspirations predate May 2006 by ≥ 1 year, with most predating it by 9–30 years. The single 2006 reference (SSSE3 PABS family) is included for completeness; the underlying operation has independent earlier prior art (MIPS MDMX 1996, ARMv6 2002) on which the v0.6 design can rest without depending on the 2006 source.

---

## End of v0.6 patch

Net document size: ~9 new instruction families, ~80 consumed codepoints, ~4k additional gates, zero new architectural state, full v0.5 binary compatibility. Beneficiary surface: ≈ 60 named algorithms across video coding, bioinformatics, database analytics, computer vision, communications, signal processing, audio, games, cryptanalysis, and quantized inference (§8). Partial implementations supported (§10).
