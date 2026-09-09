# J-Core SIMD-GPU Extension — Geometry / 3D Instructions

**Status:** Draft, 2026-07-17. **Follow-up to** the J-Core SIMD ISA
([../spec.md](../spec.md)); this document adds the geometry/3D facility on top of
Tier 0–2 and inherits all of that spec's model (VLEN = 8 × XLEN, V0..V15, P0,
VCSR, FP reductions writing FR0/DR0, the SIMDV/SIMDH prefix machinery, the FP exception model).
**Audience:** GPU/SM microarchitecture, RTL, toolchain.
**Companion:** [architecture.md](architecture.md) (the SIMT GPU that consumes
these instructions), [../hardware-impl.md](../hardware-impl.md),
[../software-impl.md](../software-impl.md).

**Design mandate: reuse existing hardware.** Every instruction here is built from
datapath the base SIMD unit already has — the FP multiply/FMA lanes, the
horizontal-mode reduction adder tree, the SWIZZLE crossbar, and the FPU's existing
FR/DR write ports (including the 4-wide FTRV port). The only
*new* silicon is a set of segment-boundary gates on the reduction tree, exactly
analogous to the lane-boundary carry-break gates the vertical mode already uses
([../spec.md §4.3](../spec.md)). No new register file, no matrix register, no bank
swap.

---

## 1. Motivation

The SH-4 on the Dreamcast carried the 3D-geometry FP instructions **FIPR** (4-wide
inner product) and **FTRV** (4×4 matrix × 4-vector) plus paired-single moves —
together the ~1.4 GFLOP/s geometry engine that DC games depend on. [../spec.md
§2.1](../spec.md) currently treats FIPR/FTRV as a **legacy 4-element facility
orthogonal to the SIMD ISA**, operating on FR quartets. That is the gap this
extension closes: it **promotes FIPR/FTRV into the V-file** so they run on the
SIMT/FGMT pipeline of the GPU SM ([architecture.md §3](architecture.md)), where
geometry transform is the dominant vertex-stage cost.

The other DC 3D facilities need no new instructions:

| SH-4 3D facility | Disposition in this plan |
|---|---|
| `FMAC FR0,FRm,FRn` | Already a Tier 0 governed op — per-lane FMA with V0 implicit ([../spec.md §5.2](../spec.md)). |
| `FADD/FMUL/FSUB` | Already Tier 0 governed, per-lane ([../spec.md §5.2](../spec.md)). |
| `FIPR FVm,FVn` | **Promoted here** → §4 (segmented dot, group = 4). |
| `FTRV XMTRX,FVn` | **Promoted here** → §5 (segmented matrix×vector). |
| paired-single `FMOV` / `FSCHG` (SZ) | **Subsumed** by `VLD.Q`/`VST.Q` full-vector moves ([../spec.md §5.6](../spec.md)); the 64-bit paired transfer hack is unnecessary. |
| `FRCHG` / `XMTRX` back-bank | **Obsolete** — the matrix lives in V registers; no FR↔XF bank swap, no SR.FD-bank interaction. |

---

## 2. The one new primitive: segmented horizontal reduction

Base SIMDH horizontal mode reduces the **whole** VLEN register to a single scalar
in MACL/MACH (integer) or FR0/DR0 (FP) ([../spec.md §4.4](../spec.md)). Geometry needs the reduction to stop
at **group boundaries** and pack one result per group into a destination V
register. That is the entire new idea:

> A **segmented** horizontal reduction of group size **G** partitions the active
> lanes into groups of G, reduces within each group, and writes the group results
> to consecutive lanes of the destination V register. Number of groups (and
> result lanes) = (VLEN/w)/G.

Hardware reuse: the horizontal adder tree already sums lanes; the segmented form
inserts **reduction-break gates at every G-th lane boundary**, precisely the way
vertical mode inserts carry-break gates at lane boundaries
([../spec.md §4.3](../spec.md), [../hardware-impl.md §3.1](../hardware-impl.md)).
Estimated cost: a handful of AND gates per potential group boundary — negligible.

### 2.1 Encoding — reuse the SIMDH prefix, repurpose FP-illegal `rrr`

The base prefix format ([../spec.md §3.2](../spec.md)) is
`1111 H ww rrr NN 1111`. For **horizontal FP** prefixes (H = 1, ww ∈ {10 = FP32,
11 = FP64}) the reduction-operator codes **`rrr = 110` and `rrr = 111`** are
`min-u`/`max-u` — **integer-only, slot-illegal for FP** today. This extension
claims those two FP codepoints for segmented add-reduction; no change to the
prefix word format, no new prefix bits:

| Prefix (H=1, ww=FP) | `rrr` | Meaning (this extension) | Group G |
|---|---|---|---|
| `SIMDHG4.L` / `.Q` | `110` | segmented FP add-reduction, group 4 | 4 |
| `SIMDHG2.L` / `.Q` | `111` | segmented FP add-reduction, group 2 | 2 |

`G = full` (the whole register → one scalar) remains the existing `SIMDHA`
(`rrr=000`). Only FP widths are defined (ww=10/11); integer widths keep min-u/max-u
unchanged, so nothing existing is disturbed. `N` (block length) works as in the
base spec.

### 2.2 Destination rule

- **G = full** → scalar to MACL/MACH (integer) or FR0/DR0 (FP) — unchanged base behaviour ([../spec.md §2.3](../spec.md)).
- **G < full** → two destination forms:
  - **packed V** (batched, GPU-side): the `(VLEN/w)/G` group sums are written to the
    low lanes of the governed instruction's destination register **Vn**, upper lanes
    cleared. Stays SIMD-side — no FPU ownership needed.
  - **scalar FP bank** (DC-compatible): `VFIPR`→**FR0**, `VFTRV`→**FV0 (FR0..FR3)** —
    the *G* group sums land in FR0..FR(G−1) (implied FR0 base), reproducing SH-4
    FIPR/FTRV register semantics ([../spec.md §2.3](../spec.md)). Requires FPU ownership
    (SR.FD = 0), checked at the prefix/block decode so any FPU-restore trap is at a
    clean boundary, never mid-block ([../spec.md §2.6](../spec.md)); the write reuses
    the FPU's existing FTRV/FIPR 4-wide port.

  Both forms route through the FP add tree with `FPSCR.RM` rounding and the trap-free
  SIMD FP model ([../spec.md §6.3](../spec.md)).
- **Predication** (VCSR.MKE): a masked-off lane contributes the additive identity
  (+0.0) to its group, keeping the group-tree shape mask-independent (identical to
  base horizontal masking, [../spec.md §4.4](../spec.md)).

---

## 3. VLEN mapping (why J64 is the sweet spot)

FP32 lanes per register = VLEN/32:

| Core | VLEN | FP32 lanes | Groups of 4 (= dot products / pass) |
|---|---|---|---|
| **J32** | 256 | 8  | **2** |
| **J64** | 512 | 16 | **4** |

- **J64:** the full **4×4 matrix fits in one V register** (16 FP32), and one
  segmented reduction (G=4) yields all four transform outputs — FTRV in a single
  broadcast + multiply + segmented-reduce.
- **J32:** two matrix rows per register → **two passes** (rows 0–1, then 2–3), or
  the matrix held in two registers. Still roughly half the instruction count of a
  scalar FMAC chain.

This is the same "same RTL, wider on J64" property as the rest of the ISA: J64
doubles geometry throughput per SM for free at the architectural level.

---

## 4. VFIPR — 4-wide inner product (promotes SH-4 FIPR)

`VFIPR` is the segmented dot with a single active group. DC-exact FIPR reduces one
quad to a scalar; the block idiom:

`VFIPR` is a plain dot — both operands are already vectors, so it needs **no
broadcast** (no SWIZZLE), just a one-slot reducing block:

```asm
    ; FIPR: dot(Va[0..3], Vb[0..3]) → FR0   (DC-exact, one quad; needs SR.FD=0)
    SIMDHG4.L #1                 ; horizontal FP32, segment=4, FR0 dest
    FMUL      Vb, Va             ; per-lane products, group-4 reduced → FR0
    ; result: FR0 = Va[0]*Vb[0] + ... + Va[3]*Vb[3] — already in the FP bank
```

The result lands directly in the implied FR0 (no boundary move), reproducing SH-4
FIPR semantics. When more than one quad is active (8 lanes on J32, 16 on J64), the
batched form instead produces **2 (J32) or 4 (J64) independent dot products packed
into Vn** — the natural GPU form (transform many vertices, or the four rows of a
matrix product), which stays SIMD-side and needs no FPU ownership. The FR0 (scalar)
destination is used for the single-quad DC-compatible case.

---

## 5. VFTRV — 4×4 matrix × 4-vector (promotes SH-4 FTRV)

`out[i] = Σⱼ M[i][j]·v[j]`, i,j ∈ 0..3. Built from **broadcast (SWIZZLE) → FMUL →
segmented reduce (G=4)** — all existing datapath:

The broadcast SWIZZLE is a **governed instruction inside the block** (SWIZZLE has no
standalone form and consumes a governed slot, [../spec.md §3.3/§4.5](../spec.md)), so
the block declares **two slots** (`#2`): slot 1 broadcasts, slot 2 multiplies-and-reduces.

```asm
    ; J64: full 4x4 matrix M in Vm (lanes 0..15 = rows 0..3), vector v pre-loaded in V0
    SIMDHG4.L #2                 ; horizontal FP32, segment=4 — 2 governed slots (needs SR.FD=0)
    SWIZZLE   V0, Vbcast_ctrl    ; slot 1 (in-block): (x,y,z,w) → (x,y,z,w)×4 broadcast in V0
    FMUL      V0, Vm             ; slot 2: 16 products, reduced per row-quad → FV0 (FR0..FR3)
    ; FR0..FR3 = transformed vector — directly in the FP bank, = SH-4 FTRV output
```

- **Broadcast** is a `SWIZZLE` *inside the block* driving the existing crossbar
  ([../spec.md §4.5](../spec.md)) with a fixed quad-repeat control — no new hardware,
  and no operation outside the SIMD block. It permutes only (not reduced); `v` is
  replicated to align with each of the four matrix rows.
- **Multiply** is the ordinary governed `FMUL` ([../spec.md §5.2](../spec.md)) over
  the FP32 lanes — the SM's FP FMA lanes / DSP48s.
- **Segmented reduce (G=4)** produces the four row dot-products in the implied
  **FV0 (FR0..FR3)** destination ([../spec.md §2.3](../spec.md), FR0-base) —
  reproducing SH-4 FTRV register semantics and reusing the FPU's 4-wide FTRV
  writeback port. (A packed-V destination is also available for the batched/GPU-side
  form that keeps results SIMD-side, §2.2.)

On **J32** the matrix occupies two registers (or two passes); the same three-step
idiom runs twice (rows 0–1, then 2–3) and the two 2-lane results are concatenated:

```asm
    ; J32: rows 0..1 in Vm01, rows 2..3 in Vm23; v pre-loaded in V0
    SIMDHG4.L #2                 ; pass 1: 2 slots
    SWIZZLE   V0, Vbcast_ctrl    ; slot 1 (in-block): broadcast v → V0
    FMUL      V0, Vm01           ; slot 2: rows 0,1 → packed-V result lanes 0,1
    SIMDHG4.L #2                 ; pass 2: 2 slots
    SWIZZLE   V0, Vbcast_ctrl    ; slot 1 (in-block): re-broadcast v → V0
    FMUL      V0, Vm23           ; slot 2: rows 2,3 → packed-V result lanes 0,1
    ; combine the two 2-lane results into one 4-lane vector with a following
    ; SIMDV block containing a VINS/SWIZZLE (also in-block). J32 VFTRV uses the
    ; packed-V form because two passes would both target the FR0 base.
```

---

## 6. Datapath reuse summary

| Step | Reused block (already in the base SIMD unit) | New |
|---|---|---|
| Broadcast v across rows | SWIZZLE crossbar ([../spec.md §4.5](../spec.md), [../hardware-impl.md §4](../hardware-impl.md)) | — |
| 16 (J64) / 8 (J32) FP products | governed `FMUL` FP lanes / DSP48 ([../spec.md §5.2](../spec.md)) | — |
| Per-group sum | horizontal add tree ([../spec.md §4.4](../spec.md)) | **segment-boundary gates** (few AND gates per group boundary) |
| FP-scalar result path (VFIPR→FR0, VFTRV→FV0) | the FPU's FR/DR write ports incl. the 4-wide FTRV port ([../spec.md §2.3](../spec.md)) | — |
| Packed vector result path | writeback to Vn (existing writeback muxes) | destination select (FR/FV vs packed-V) |

Total added silicon: the segment-boundary gating on the reduction tree plus a
destination-select mux — well under the swizzle crossbar's own cost. Beat count
follows the base rule (VLEN/32 beats per governed FMUL on a 32-bit ALU; FGMT hides
it — [../hardware-impl.md §3.1](../hardware-impl.md)).

---

## 7. GPU / pipeline integration

This extension is what makes the SM's **geometry (vertex-transform) stage**
([architecture.md §4.3](architecture.md)) fast:

- **One `VFTRV` idiom per vertex** replaces a 16-multiply / 12-add scalar FMAC
  chain — the dominant instruction in the geometry phase collapses to a broadcast +
  one FMUL + one segmented reduce (J64) or two (J32).
- **FGMT hides the multi-beat latency** of the segmented reduce: with ≥
  pipeline-depth warps resident, the SM issues another warp while the reduction
  drains — no stall ([architecture.md §3](architecture.md)). This is precisely the
  "in-order pipeline loves FGMT" property; geometry throughput scales with lanes,
  not with reduction latency.
- **DSP48-backed** on the Artix-7 A200T target ([../../no-gpu-dual-ecp5-asic.md §6](../../no-gpu-dual-ecp5-asic.md)):
  the FMAs land on the 740 hardware multipliers, not LUTs.
- **HLE benefit:** the Dreamcast HLE layer ([architecture.md §7](architecture.md))
  can lower a game's TA transform/lighting matrices directly onto `VFTRV`/`VFIPR`,
  reproducing DC geometry semantics on the programmable core.

---

## 8. FP16 support (half precision)

FP16 is the highest-leverage numeric addition for the GPU: it doubles lane
throughput, halves texture/geometry/BVH bandwidth, and — uniquely — lets **J32
hold a full 4×4 matrix in one register**. It is specified here because its main
consumers (shading, BVH traversal, ML) live on the GPU/SM path; the base ISA
already reserves the lane-width code for it (`ww = 01`, [../spec.md §3.2](../spec.md)).

### 8.1 Format and prior art

The format is **IEEE 754-2008 binary16 / OpenEXR `half`**: **s1e5m10** (1 sign, 5
exponent, 10 mantissa, bias 15), with denormals, ±∞, and NaN; finite range
≈ ±65 504, smallest normal ≈ 6.1×10⁻⁵. It is a mathematical standard with **deep
pre-2006 prior art**, so it is safe under the project's prior-art policy
([../spec.md Appendix E](../spec.md)):

- **SGI "bali" programmable-shading s10e5** (John Airey et al., 1997; SIGGRAPH 2000) — the exact 1-5-10 layout.
- **Thomas J. Scott, WIF** (1991) — 5-exponent/10-mantissa 16-bit float.
- **3dfx Voodoo** (1995) and **Hitachi HD61810 DSP** (1982, a 4e12m variant) — earlier 16-bit floats.
- **ILM OpenEXR `half`** (Kainz & Bogart, internal 2000, public 2002) and **NVIDIA/Microsoft Cg** (2002) — popularized s10e5; later formalized as IEEE 754-2008 binary16.

Only **binary16** is implemented natively. Per [../spec.md Appendix E](../spec.md):
**bfloat16** stays storage-only (weak pre-2006 prior art, live Intel patents);
**FP8/FP4** are not implemented (post-2022, zero pre-2006 prior art). The float↔half
conversion algorithms are trivial bit manipulation and unencumbered.

### 8.2 FP16 as a SIMD lane type

Selected by the prefix width field `ww = 01`. Lanes = VLEN/16 = **16 on J32, 32 on
J64** — double the FP32 lane count. The Tier 0 governed FP ops (`FADD`, `FSUB`,
`FMUL`, `FMAC`, `FCMP`, [../spec.md §5.2](../spec.md)) operate per-lane in FP16 when
`ww = 01`: **vertical** results are FP16 (round per `FPSCR.RM`; denormals flushed
unless `VCSR.IEE = 1`; trap-free FP model, [../spec.md §6.3](../spec.md)). An
implementation may omit FP16 entirely, in which case `ww = 01` on an FP op raises
slot-illegal.

### 8.3 Reduction semantics — FP16 multiply, **FP32 accumulate**

The one semantic that needs care. FP16's 10-bit mantissa makes long same-precision
summation lose accuracy catastrophically, so **additive FP16 reductions accumulate
in FP32**, exactly as GPUs and tensor units do (mixed precision):

- Each FP16 lane — or each FP16×FP16 product, for a dot — is **widened to FP32**,
  and the reduction tree runs in **FP32**. The result is **FP32**, written to
  **FR0** (matches the [../spec.md §2.3](../spec.md) `16 FP → FP32` widening row).
- **Non-additive** reductions (min/max/bitwise) do **not** widen — the result is
  FP16 (min/max of FP16 values is exact).
- **Segmented** FP16 reductions (`SIMDHG4`/`SIMDHG2`, §2) sum each 4- or 2-lane
  group in FP32. `VFIPR`/`VFTRV` in FP16 therefore compute an **FP16-input,
  FP32-accumulate** dot/transform; the FP32 result lands in FR/FV, optionally
  narrowed to FP16 on writeback (§8.4). This is the numerically sound GPU idiom
  and keeps geometry/lighting stable despite FP16 inputs.

### 8.4 Conversion instructions (the bridge)

Packed FP16↔FP32 conversion, reusing the VPACK/VUNPK family shape
([../spec.md §5.4](../spec.md)); a small per-lane converter (exponent rebias +
mantissa shift, round `FPSCR.RM`) — combinational, ~tens of gates/lane:

| Mnemonic | Operation |
|---|---|
| `VCVT.HS Vm, Vn` | unpack: VLEN/16 FP16 lanes → VLEN/32 FP32 lanes (widen a half of Vm) |
| `VCVT.SH Vm, Vn` | pack: VLEN/32 FP32 lanes → FP16 lanes (narrow; overflow → ±∞, round `FPSCR.RM`) |

These bridge FP16 storage (memory/textures) to the FP32 accumulate path and back.

### 8.5 SH-4 FPU FP16 mode (answering the design question)

**Recommendation: do *not* add a full scalar FP16 arithmetic mode; add only scalar
conversions.** A third `FPSCR.PR` "half" arithmetic mode would be high-cost and
low-value — scalar FP16 math is rare, and the right move is always "convert to
FP32, compute, convert back." What *is* worth adding to the SH-4 FPU
([../fpu/spec.md](../../fpu/spec.md)) is a pair of scalar conversions, exactly
analogous to SH-4's existing `FCNVSD`/`FCNVDS` (single↔double):

- **`FCNVSH FRm, FRn`** — single → half (result in the low 16 bits of FRn).
- **`FCNVHS FRm, FRn`** — half (low 16 bits of FRm) → single.

Scalar FP16 *values* move as 16-bit quantities via `MOV.W` and convert with
`FCNVHS`/`FCNVSH`; all FP16 *arithmetic* stays in the SIMD lanes where it pays off.
This keeps the FPU change minimal (two conversions, no new arithmetic datapath, no
new `FPSCR.PR` state) and is a proposed addition to the FPU spec rather than this one.

### 8.6 Geometry / GPU payoff

- **Full 4×4 matrix in one register on J32.** 16 FP16 = 256 bits = one J32 V
  register, so `VFTRV` in FP16 on J32 is a single broadcast + FMUL +
  segmented-reduce — the one-register-matrix property FP32 needs J64 for (§3).
- **2× throughput** (16 FP16 ops/cycle on J32) and **halved bandwidth** for
  textures, geometry, and the BVH ([architecture.md §6](architecture.md)).
- **Precision guidance.** FP16 is excellent for lighting, colour, normals, BVH,
  and ML inference. **Vertex/position transform normally keeps FP32** — FP16's
  mantissa is too small for world-space coordinates — so FP16 geometry is a
  per-stage choice (transform in FP32, shade in FP16), not a blanket replacement.

### 8.7 Tier / feature detection

FP16 is an **optional Tier 0 lane capability**, gated by `HWCAP_JCORE_SIMD_FP16`
([../software-impl.md §8.5](../software-impl.md)) and the compile flag
`-mjcore-simd-fp16`. `VCVT.HS/SH` and FP16 governed ops are available only when the
implementation sets the bit.

---

## 9. Texture sampling (VTEX / VTFETCH)

The architecture doc ([architecture.md §4.2](architecture.md)) budgets a
fixed-function texture sampler as one of the two non-negotiable fixed blocks. This
section **exposes that sampler as a first-class SIMD-GPU instruction** — the way
pre-2006 programmable shaders did it (DirectX 8.1 ps.1.4 `texld`, 2001; OpenGL
`ARB_fragment_program`/`ATI_fragment_shader` `TEX`, 2002) — rather than invoking it
implicitly. `VTEX` *drives* the sampler datapath; the
address-gen/twiddle/VQ/palette/format-decode is the already-planned fixed block,
while the texel fetch reuses the **gather** path and the filter reuses the **FP FMA
lanes** (reuse-existing-hardware mandate).

### 9.1 Model — instruction + external descriptor (pre-2006 prior art)

**Filtering, wrap, and format state live in a descriptor, not in the instruction.**
The instruction names a coordinate operand and an **active texture descriptor**
(selected by a small index), and writes a filtered result. This is exactly the
pre-2006 shader-texturing model and is the anchor for the whole design:

- **DX 8.1 ps.1.4 `texld`** (RADEON 8500, 2001) — a `texld` samples a texture
  named by a `sampler`/stage register whose bilinear/mipmap state is bound *outside
  the instruction* via `SetSamplerState`.
- **DX9 ps.2.0** (2002) — 16 sampler stages `s0..s15`, `dcl_sampler`.
- **OpenGL `ARB_fragment_program`/`ATI_fragment_shader` `TEX`** (2002).
- **OpenGL texture objects, `glBindTexture`** (OpenGL 1.1, 1992) — selecting a
  texture by a bound id/index, with its parameters (format, filter, wrap) held in
  the texture object, is the origin of "index selects an external descriptor."

All are published pre-2006 and now long-established, so exposing texturing as an
instruction with out-of-band sampler state carries no post-2006 design dependency.

### 9.2 The two instructions

| Mnemonic | Operation |
|---|---|
| `VTEX Vu, Vv → Vd` | **Filtered** sample: per lane, sample the active texture at (u,v) with the descriptor's filter (nearest/bilinear/trilinear) and wrap modes; write decoded RGBA to Vd. (A filtered `texld`.) |
| `VTFETCH Vu, Vv → Vd` | **Unfiltered** texel read at integer coords — decode format, no filtering (equivalent to a point/nearest-sampled `texld`). For compute, palette work, or manual filtering. |

Per-lane, SIMT: each of the VLEN/32 lanes (8 on J32, 16 on J64) samples
independently. Coordinates are **SoA** — `Vu` holds u per lane, `Vv` holds v per
lane (FP32, or FP16 §8 for compact packing). `Vd` receives **packed RGBA8** per
lane by default (VLEN/32 lanes of 32-bit); a descriptor bit can request FP16×4 or
FP32×4 unpacked output for HDR/compute. The **active descriptor index** and LOD
mode live in a control register **`VTEXSEL`** (`LDS Rm, VTEXSEL`; shader-writable,
and bounded by the privileged `VTEXCNT` per §16.3 G-R5), set before the
block, so the 16-bit instruction word needs only the two V operands (exact
coordinate packing — SoA pair vs FP16 AoS — is settled in the opcode-map audit,
like other §5.x encodings). Explicit LOD/bias is taken from `VTEXSEL`; implicit LOD
from 2×2-quad derivatives is the SM-integrated mode (§9.5).

### 9.3 Texture descriptor

Descriptors live in the unified DDR bank, in a table based at the **`VTEXBASE`**
control register, indexed by `VTEXSEL`. This is just an **in-memory table of
texture-object state** selected by an id — the OpenGL texture-object model
(`glBindTexture`, 1992) with the object's parameters held in memory rather than in
a fixed number of hardware texture-unit registers, so it scales past DC's fixed
texture-unit count without a post-2006 dependency. Each descriptor carries:

- `base_addr` (texture data), `width_log2`, `height_log2`
- `format` (§9.4), `layout` (twiddled/Morton vs linear-stride)
- `filter` (nearest / bilinear / trilinear), `wrap_u`, `wrap_v` (repeat / clamp / mirror)
- `mip_base`, `mip_count`; `palette_base` (PAL4/8); `vq_codebook_base` (VQ)
- `out_format` (RGBA8 / FP16×4 / FP32×4)

**Every address in the list above is a context-relative offset, relocated and
bounded per §16.3 before it reaches memory** — a descriptor is tenant-writable
data, so nothing in it is trusted; see §16.2 producer P4.

Sampler and image state are folded into one descriptor for simplicity (as DC binds
them together); a separable texture/sampler split — sampler state bound per stage
independently of the texture, as in DX9 sampler stages and OpenGL 1.1 texture
objects (both ≤2002) — is available as an option (a second index) if multitexture
with shared samplers needs it.

### 9.4 Formats (Dreamcast-native + RGBA8888)

For DC HLE the sampler decodes the PowerVR2/PVR set natively (all pre-2006, DC 1998):

- **Uncompressed 16-bit:** RGB565, ARGB1555, ARGB4444, YUV422 (→ RGB) — `VUNPK`-class unpack.
- **Paletted:** PAL4 (16-colour) / PAL8 (256-colour) via a palette in memory/BRAM (DC's on-chip 1024-entry palette modelled as `palette_base`); 4bpp nibble index reuses the `VUNPK4` path (§5.4.2).
- **VQ (vector quantization):** 2×2-texel blocks from a codebook (`vq_codebook_base`) — a codebook lookup then the 2×2 block; DC's native compression (PowerVR, 1998; the VQ technique is Linde–Buzo–Gray 1980).
- **Twiddled (Morton/Z-order) addressing** for all of the above (DC requires it for paletted/VQ) — a bit-interleave in address-gen (Z-order curve, G. M. Morton, IBM, **1966**).
- Plus linear **RGBA8888** for the programmable/compute path.

Optional DXT/ETC decode is a later add; DC does not use them.

### 9.5 Filtering and LOD

- **Nearest:** one texel, no fetch fan-out.
- **Bilinear:** 2×2 texel gather + **3 lerps** (per channel) on the FMA lanes.
- **Trilinear:** bilinear on two mip levels + 1 lerp; LOD picks the mip pair.
- **LOD:** explicit (from `VTEXSEL`/a coordinate lane) at bring-up; **implicit** from
  2×2-quad screen-space derivatives once the SM organizes lanes into 2×2 quads
  ([architecture.md §4.1](architecture.md)) — the `ImplicitLod` model, which needs
  the descriptor/coords uniform across the quad.

### 9.6 Datapath reuse

| Step | Reused / new |
|---|---|
| Address-gen (u·w, v·h, mip, **twiddle** bit-interleave) | small new datapath (integer mul + interleave); the fixed block budgeted in [architecture.md §2](architecture.md) |
| 2×2 (or codebook / palette) texel fetch | **reuses the gather path** (`VGATHER.Q`, [../spec.md §5.6](../spec.md)) into the texel BRAM cache |
| VQ codebook / palette lookup, format unpack | fixed decode block; 4bpp index reuses `VUNPK4` (§5.4.2) |
| Bilinear/trilinear lerp | **reuses the FP FMA lanes** (§8 FP16 or FP32) |

So `VTEX` adds only the address-gen + format-decode fixed block (already planned);
fetch and filter fall onto existing datapath.

### 9.7 Latency and FGMT (GPU profile)

`VTEX`/`VTFETCH` are **long-latency, asynchronous** memory-class instructions (a
cache miss reaches DDR). The issuing warp **parks** and a completion **scoreboard**
wakes it when RGBA is ready, while the scheduler runs other warps
([architecture.md §3](architecture.md)). Both mechanisms are deeply pre-2006: the
register scoreboard is the **CDC 6600** (Thornton, 1964), and hiding memory latency
by switching to another ready thread is **fine-grained multithreading** (Tera MTA,
1990; Sun MAJC, 1999) — the same latency-hiding this whole design rests on, and why
a multi-hundred-cycle sample costs no throughput. Consequently
these are **GPU-profile** instructions: they are not intended for the interrupt-
latency-atomic CPU SIMD context (§4.2 of the base spec bounds block latency for the
CPU), and a core issuing them must implement the SM scoreboard. They follow the
base memory-fault model (N=1 memory rule + restart-from-prefix, [../spec.md §5.6](../spec.md)).

### 9.8 Toolchain / feature bit

Intrinsics (VLEN-neutral): `jcore_vec_t __jcore_vtex(jcore_vec_t u, jcore_vec_t v)`
and `__jcore_vtfetch(...)`, with the active texture bound by
`__jcore_vtex_bind(unsigned index)` (→ `LDS VTEXSEL`). Gated by
`HWCAP_JCORE_SIMD_TEX` and the compile flag `-mjcore-simd-tex`; an implementation
without the sampler raises slot-illegal on `VTEX`/`VTFETCH`. Maps cleanly from
GLSL 1.10 `texture2D()` (2004) / `ARB_fragment_program` `TEX` in the Mesa backend
([architecture.md §8](architecture.md)); newer GLSL/Vulkan `texture()` calls lower
to the same instruction but are only *targets we run*, not design sources.

### 9.9 Prior art (pre-2006 only — no post-2006 GPU-vendor ISA is used as a design source)

Every decision in §9 is anchored below; **AMD GCN/RDNA, SPIR-V, Vulkan and other
post-2006 ISAs are deliberately *not* design sources** (they appear elsewhere only
as software targets we run, not as microarchitecture we copy):

- **Texturing as a shader instruction, filter/wrap state bound *outside* it:** DX 8.1 ps.1.4 `texld` + `SetSamplerState` (RADEON 8500, 2001); DX9 ps.2.0 sampler stages `s0..s15` (2002); OpenGL `ARB_fragment_program`/`ATI_fragment_shader` `TEX` (2002).
- **Select a texture by a bound id whose parameters live in an external object/table:** OpenGL texture objects, `glBindTexture` (OpenGL 1.1, 1992).
- **Filtering / mipmapping:** bilinear texture filtering (Catmull 1974; Blinn–Newell 1976); trilinear mipmapping (Williams, "Pyramidal Parametrics", SIGGRAPH 1983).
- **Formats:** PowerVR2/Dreamcast twiddled/VQ/paletted formats (1998); Z-order/Morton addressing (Morton, IBM, 1966); vector quantization (Linde–Buzo–Gray, 1980).
- **Async long-latency fetch, completion tracked and hidden by thread switching:** register scoreboard (CDC 6600, Thornton, 1964); fine-grained multithreading (Tera MTA, 1990; Sun MAJC, 1999).

---

## 10. Transcendental FP helpers (VFSRRA / VFSCA / VFSQRT)

We promoted SH-4 FTRV/FIPR (§4–5); their **transcendental siblings** in the same
1998 SH-4 3D-helper family are equally worth promoting to per-lane SIMD, since they
are the hot per-vertex/per-pixel math the SM's shading and geometry stages run:

| Mnemonic | Per-lane operation | Main use |
|---|---|---|
| `VFSRRA Vn` | reciprocal square root approx, 1/√x | **normalize** (1/√(x²+y²+z²)), lighting falloff, `VINTERP` 1/w |
| `VFSQRT Vn` | square root | distances, magnitudes |
| `VFSCA Vn → (sin,cos)` | sine and cosine of an angle | rotations, UV animation, procedural |

These are **vertical governed ops** (inside a `SIMDV` block, like `FMUL`), writing
V-register lanes — not reductions, so no FR0/DR0 involvement. `VFSCA` produces a
pair per lane (sin, cos) — packed into adjacent lanes or a second register (exact
packing pending opcode-map audit, like SH-4 `FSCA`'s FRn/FRn+1 pair).

- **Reuse:** the FPU already contains the **FSRRA/FSCA approximation unit** (seed
  table + Newton/polynomial step); a SIMD helper drives it across the lanes,
  exactly as the FMUL lanes reuse the multiplier. No new algorithm.
- **Accuracy:** approximations (as on SH-4 — `FSRRA` ~single-precision seed refined;
  `FSCA` fixed accuracy), matching every GPU's `rsq`/`sincos`; not IEEE-exact.
- **Prior art (pre-2006):** SH-4 `FSRRA`/`FSCA`/`FSQRT` (Hitachi, 1998); CORDIC for
  sin/cos (Volder, 1959); Newton–Raphson reciprocal/rsqrt seed refinement (classical).

## 11. Per-pixel raster ops: blend and logic (VBLEND / VROP)

`architecture.md §4.3` left blend/fog as "SM code." Blending is a fixed per-pixel
equation on packed RGBA8; making it an instruction collapses ~6 ops to one and has
deep pre-2006 pedigree (see the blend-instruction lineage below).

### 11.1 VBLEND — fractional alpha blend

Per lane, on packed RGBA8: `out = sat( src·Fs + dst·Fd )`, where `(Fs, Fd)` are the
blend factors selected by a **mode field** (the DC/PVR set: `ZERO`, `ONE`,
`SRC_ALPHA`, `INV_SRC_ALPHA`, `DST_ALPHA`, `INV_DST_ALPHA`, …). Operands `Vsrc`,
`Vdst` → `Vout`; mode in a small immediate or a `VBLENDCFG` control register. **Fog**
is the same op toward a fog colour by a fog factor (a mode / `VLERP`).

- **Reuse:** the **Tier-1 partitioned multiply** (`VMULSU`, 8-bit × 16-bit scale) +
  **saturating add** (`SIMDVS`) — almost no new silicon. This *is* the SPARC-VIS
  datapath.
- **Prior art (pre-2006):** compositing algebra — **Porter–Duff, "Compositing
  Digital Images," SIGGRAPH 1984**; the pixel-scale primitive — **SPARC VIS
  `FMUL8x16` + `FEXPAND`/`FPACK16`** (UltraSPARC-I, **1995**), built by reusing the
  FPU datapath; packed-byte blend/average — **Intel MMX `PADDUSB`** (1996) and
  **SSE `PAVGB`** (1999).

### 11.2 VROP — boolean raster op (Amiga-minterm)

Optional companion for 2D / HLE / windowing: per bit, `d = f(a,b,c)` where the
**8-bit `LF` immediate** selects one of **256 boolean functions** of three sources
— the Amiga Blitter's function generator, verbatim. Operands `Va`,`Vb`,`Vc` + `#LF`
→ `Vd`. Classic cookie-cut (masked composite) is `LF=$CA`: `d = a·b + ¬a·c`.

- **Reuse:** an **8:1 mux per bit** driven by `LF` (the three source bits index the
  LF byte) — trivial, ~nothing.
- **Prior art (pre-2006):** **Xerox Alto `BitBlt`** (Ingalls, ~1975); **Amiga
  Blitter 256-minterm `LF` control byte** (Commodore-Amiga Hardware Reference
  Manual, **1985**); Windows GDI ternary raster ops (ROP3).
- **Scope:** DC 3D uses only fractional alpha (`VBLEND`); `VROP` is for 2D/desktop
  and is an open-question inclusion (§17).

## 12. Raster back-end: depth/stencil and coverage/interpolation

The remaining `architecture.md §4.3` "SM compute" hand-waves become concrete
instructions; the coverage *walker* stays fixed-function, but its math kernels are
pure SIMD.

### 12.1 VZTEST — depth (and stencil) test → kill mask

Per lane, compare the incoming z against the **on-chip tile-buffer z** (or a z
operand) under a compare mode (`LESS`/`LEQUAL`/…); write pass/fail into **P0** (the
kill mask that predicates the rest of the fragment), and conditionally update z if
z-write is enabled. Optional stencil op (`KEEP`/`REPLACE`/`INCR`) as a mode.

- **Reuse:** the existing **per-lane compare → P0** path (`FCMP`, [../spec.md §5.2](../spec.md))
  + the **tile-buffer BRAM** ([architecture.md §5.2](architecture.md)).
- **Prior art (pre-2006):** z-buffer (Catmull, PhD thesis, **1974**); stencil buffer
  (IRIS GL, 1980s).

### 12.2 VEDGE — edge-function coverage

Per lane (pixel), evaluate the three edge functions `E_i = A_i·x + B_i·y + C_i` and
produce an inside/outside coverage mask in **P0** (all `E_i ≥ 0`). This is exactly
an FMA/dot, so it **reuses the VFIPR datapath** (§4).

- **Prior art (pre-2006):** Pineda, "A Parallel Algorithm for Polygon Rasterization,"
  **SIGGRAPH 1988**.

### 12.3 VINTERP — perspective-correct attribute interpolation

Per lane: numerator = barycentric·attribute (a dot → **reuses VFIPR**), then multiply
by `1/w` (**reuses `VFSRRA`**/reciprocal, §10) — perspective-correct interpolation of
colour/UV/normal across the triangle.

- **Prior art (pre-2006):** perspective-correct (hyperbolic) interpolation — Heckbert,
  "Fundamentals of Texture Mapping and Image Warping," **1989**; Blinn, "W Pleasure,
  W Fun," 1998.

---

## 13. Semantics (reference)

```
segmented_freduce(width w, group G, src lanes t[0 .. VLEN/w − 1]) -> dst:
    ngroups = (VLEN/w) / G
    for g in 0 .. ngroups − 1:
        acc = +0.0
        for k in 0 .. G − 1:
            i = g*G + k
            lane = (VCSR.MKE==0 or P0[i*(w/8)]==1) ? t[i] : +0.0
            acc = fadd(acc, lane)            ; FPSCR.RM rounding; order impl-defined
        dst.lane[g] = acc
    dst.lane[ngroups .. ] = +0.0             ; upper lanes cleared

; A G-group segmented FP reduction writes the implied FR0 base: FR0..FR(G-1).
; The broadcast for VFTRV is a SWIZZLE that is the FIRST governed slot of the
; SAME block (SWIZZLE is in-block only, spec.md §3.3/§4.5) — not a pre-prefix op.

VFIPR (one quad active): segmented_freduce(w=32, G=4) then either
    FR0   = dst.lane[0]                      ; scalar → FP bank (DC-exact FIPR; needs SR.FD=0), or
    Vn    = dst                              ; packed (batched, SIMD-side)

VFTRV: FV0 = {FR0..FR3} = segmented_freduce(w=32, G=4, t = FMUL(V0_broadcast, M))
       ; V0_broadcast produced by the in-block SWIZZLE slot; = SH-4 FTRV semantics;
       ; needs SR.FD=0 (checked at prefix decode)

VTEX Vu,Vv → Vd (per lane i, active descriptor D = VTEXBASE[VTEXSEL]):
    (s,t)     = wrap_D(Vu[i], Vv[i])
    lod       = explicit(VTEXSEL) or quad_derivatives(Vu,Vv)      ; §9.5
    addr[0..3]= twiddle_D(texel_addrs(s,t,lod))                    ; 2x2 for bilinear
    texels    = decode_D(gather(addr[0..3]))                       ; VQ/palette/format
    Vd[i]     = filter_D(texels)                                   ; FMA-lane lerps
    ; long-latency: warp parks, SM scoreboard writes Vd[i] when ready (§9.7)
VTFETCH: as VTEX but integer coords, no wrap/lod/filter (single decoded texel).

; --- §10 transcendentals (vertical, per-lane, write V lanes) ---
VFSRRA Vn: for each lane i: Vn[i] = 1/sqrt(Vn[i])        ; approx (SH-4 FSRRA)
VFSQRT Vn: for each lane i: Vn[i] = sqrt(Vn[i])
VFSCA  Vn: for each lane i: (sin[i], cos[i]) = sincos(Vn[i])   ; pair per lane

; --- §11 blend / raster-op (vertical, packed RGBA8) ---
VBLEND Vsrc,Vdst → Vout (mode m):
    for each lane i (per RGBA channel c):
        Vout[i].c = sat8( Vsrc[i].c * Fs(m) + Vdst[i].c * Fd(m) )   ; VMULSU + SIMDVS
VROP Va,Vb,Vc,#LF → Vd:
    for each bit b: Vd.b = LF[ (Va.b<<2)|(Vb.b<<1)|Vc.b ]          ; 256-fn minterm mux

; --- §12 raster back-end ---
VZTEST Vz (mode cmp, zwrite):
    for each lane i: pass = cmp(Vz[i], tilebuf.z[i]);  P0[i] = pass
        if pass and zwrite: tilebuf.z[i] = Vz[i]                   ; FCMP→P0 + tile BRAM
VEDGE Vx,Vy (edges E0..2): for each lane i: P0[i] = (E0[i]>=0 and E1[i]>=0 and E2[i]>=0)
VINTERP Vbary, attr, Vinvw:                                        ; reuses VFIPR + VFSRRA
    for each lane i: Vd[i] = dot(Vbary[i], attr) * Vinvw[i]
```

FP exception behaviour, denormal handling, and IEEE-strict mode follow
[../spec.md §6.3](../spec.md) unchanged (SIMD FP never traps; VCSR.IEE governs
flag accumulation). Reduction order within a group is implementation-defined
(same latitude as base horizontal add).

---

## 14. Toolchain / intrinsics

VLEN-neutral C intrinsics (types from [../software-impl.md §3.4](../software-impl.md),
`jcore_vec_t` / `jcore_mask_t`), under a new option `-mjcore-simd-geom`
(implies Tier 0):

```c
/* 4-wide inner product → scalar in the FP bank (DC-exact FIPR; result in FRn) */
float        __jcore_fipr(jcore_vec_t a, jcore_vec_t b);      /* SIMDHG4.L #1 + FMUL, quad 0 → FR0 */

/* batched 4-wide dot: 2 (J32) or 4 (J64) dots packed into result lanes */
jcore_vec_t  __jcore_fipr_batch(jcore_vec_t a, jcore_vec_t b);

/* 4x4 matrix (m, row-major in lanes) × 4-vector v → transformed 4-vector */
jcore_vec_t  __jcore_ftrv(jcore_vec_t m /*J64: full matrix*/, jcore_vec_t v);
jcore_vec_t  __jcore_ftrv_j32(jcore_vec_t m01, jcore_vec_t m23, jcore_vec_t v);
```

GCC/LLVM RTL pattern names: `simd_freduce_seg_f32`, `vftrv_f32`, `vfipr_f32`.
GAS adds the `SIMDHG4.w` / `SIMDHG2.w` prefixes to the SH-2 opcode table; objdump
disassembles them as horizontal FP prefixes with segment size.

---

## 15. Prior art (pre-2006, per project policy)

- **SH-4 `FIPR` and `FTRV`** (Hitachi/Renesas, 1998) — the exact 4-wide inner
  product and 4×4 matrix transform this extension promotes; the Dreamcast geometry
  engine. This is the project's own target ISA, comfortably pre-2006.
- **Segmented / grouped reductions:** Cray-1 vector reductions on a narrow datapath
  (1976); PowerPC AltiVec `vmsum*` grouped multiply-sum (1996–1999) — precedent for
  reducing within lane groups and packing results.
- **Broadcast/permute for matrix ops:** AltiVec `vperm` (1996) — the SWIZZLE-based
  operand broadcast reused in §5.
- **Transcendental FP helpers (§10):** SH-4 `FSRRA`/`FSCA`/`FSQRT` (1998); CORDIC (Volder, 1959); Newton–Raphson reciprocal/rsqrt (classical).
- **Blend / raster-op (§11):** compositing algebra — Porter–Duff (SIGGRAPH 1984); pixel-scale primitive — SPARC VIS `FMUL8x16`/`FEXPAND`/`FPACK16` (UltraSPARC-I, 1995); packed-byte blend/average — Intel MMX `PADDUSB` (1996), SSE `PAVGB` (1999); boolean raster-op — Xerox Alto `BitBlt` (Ingalls, ~1975), Amiga Blitter 256-minterm `LF` byte (1985), Windows GDI ROP3.
- **Raster back-end (§12):** z-buffer (Catmull, 1974); edge functions (Pineda, SIGGRAPH 1988); perspective-correct interpolation (Heckbert, 1989).

**Texture-sampling and all §10–12 instructions use only pre-2006 / patent-free prior
art; no post-2006 GPU-vendor ISA (AMD, NVIDIA, SPIR-V, Vulkan) is a design source.**

---

## 16. Memory protection and tenant isolation

**What this section changes, stated first.** Before it, this specification carried
no protection story at all. Searched case-insensitively, *physical*, *base
address*, *protection*, *isolation*, *MMU* and *IOMMU* did not occur anywhere in
it, and none of §17's eleven open questions raised one. Protection was
therefore not *deferred* here — it was **absent**, which is the harder failure,
because a deferred item is visible to a reader and an absent one is not.

Adding this section makes the site **specified**. It does not make it **met**. No
GPU RTL exists in `jcore-cpu` or `jcore-soc` at `origin/master`: a
case-insensitive search for `gpu|shader|opencl|simt|warp|texel|rasteriz` returns
two matches in `jcore-cpu` and none in `jcore-soc`, and both are false positives
(`vpiSimTime` in `sim/sim/vpibridge.c`, the label `_movwarpr` in
`testrom/tests/testmov.s`). Nothing below can be made to fail on hardware, which
is the precondition for ever seeing it pass.

### 16.1 Why the CPU's mechanisms do not reach a shader

The base SIMD memory instructions are already translated. `VLD.Q`, `VST.Q`,
`VGATHER.Q` and `VSCATTER.Q` take standard SH-4 memory exceptions — address
error, TLB miss, page fault, bus error ([../spec.md §6.4](../spec.md)) — and
§6.5 there specifies the instruction-side hazard once `MMUCR.AT = 1`. That covers
a shader **only where the shader runs on something with an MMU.** The SM is not
such a thing. [architecture.md §2](architecture.md)'s indicative budget lists ten
blocks and contains no TLB, no page-table walker and no ASID storage; the SM
reaches memory through the "Command processor + DDR-controller ports + DMA" line
into the shared DDR bank ([architecture.md §5.1](architecture.md)).
[../../bus/fabric-spec.md §3.2](../../bus/fabric-spec.md) recognises exactly two
kinds of initiator, and the SM is the second of them: "DMA masters bypass the CPU
MMU but go through the IOMMU… CPU cores never bypass the IOMMU."

So a GPU address is a physical address **by omission**: no document in this tree
states that GPU addresses are physical, and none states that they are translated.
[../../j4-remediation-plan.md §C2](../../j4-remediation-plan.md) reads "user
shaders get raw physical base addresses" — the right conclusion, reached from
silence rather than from text. This section is what replaces the silence.

### 16.2 The six address producers

Isolation has to be stated over the set of things that emit an address, not over
the instruction that is easiest to think about. Reading this document and
[architecture.md](architecture.md) together, a GPU-originated address comes from
exactly **6** address producers:

| # | Producer | Address comes from | Controlled by |
|---|---|---|---|
| P1 | Shader load / store / gather | `VLD.Q`, `VST.Q`, `VGATHER.Q`, `VSCATTER.Q` operands ([../spec.md §5.6](../spec.md)) | the shader |
| P2 | Shader instruction fetch | the warp PC, via the shader I-cache ([architecture.md §2](architecture.md)) | the shader |
| P3 | Texture-descriptor fetch | `VTEXBASE` + `VTEXSEL` × descriptor stride (§9.3) | `VTEXSEL` is the shader's |
| P4 | Texel / mip / palette / VQ-codebook fetch | the sampler's address generation from the descriptor's `base_addr`, `mip_base`, `palette_base`, `vq_codebook_base` (§9.3, §9.6) | the descriptor's contents |
| P5 | Tile write-out burst | the raster back-end bursting the finished colour+Z tile to the DDR framebuffer ([architecture.md §4.3, §5.2](architecture.md)) | the tile's owner |
| P6 | Command processor and scanout | command-buffer fetch and the HDMI/DVI scanout read of the framebuffer ([architecture.md §2](architecture.md)) | privileged host code |

Two entries are not on that list because they collapse into P1: **binning and
per-tile display-list traffic** is a compute kernel running on the SM lanes and
not dedicated hardware ([architecture.md §5.3](architecture.md)), and the
**gather path** P4 borrows is P1's datapath reached from a different address
source (§9.6).

> **G-R1 — every producer is checked.** All six of P1–P6 are subject to §16.3's
> window check. This is stated as a rule rather than left implicit because the
> obvious mitigation — bounding the texture path, which is where the
> attacker-supplied `base_addr` visibly is — leaves five producers open, and P5
> is the one that *writes*.

### 16.3 The mechanism: per-context relocate-and-bound

The unit of isolation is the **GPU context**: the owner of a warp slot, of the
tile-buffer region its fragments resolve into, and of the texture-cache lines its
fetches fill. Each resident context has a numeric **`GCID`** and a window:

| Register | Meaning |
|---|---|
| `GBASE` | physical base of the context's private window |
| `GLIMIT` | length of that window in bytes |
| `GBASE_RO`, `GLIMIT_RO` | *optional* second window, read-only (shared immutable data: an HLE texture atlas, a shared shader image) |

> **G-R2 — identity travels with the request.** Every request from any of P1–P6
> carries its `GCID` from the producer to the memory port. The `GCID` is **not**
> recovered by asking "which warp is running now" at completion time.
>
> This is a correctness requirement, not an implementation convenience. The
> sampler is one shared block per SM ([architecture.md §4.2](architecture.md))
> and `VTEX` is explicitly long-latency and asynchronous: the issuing warp parks
> and a scoreboard wakes it (§9.7), while the scheduler runs other warps. By the
> time P4's texel fetch presents an address, the warp that asked for it is not
> the warp on the pipe. A check that reads the current warp's window would check
> the wrong tenant's window, and would do so *more* often the better the
> latency-hiding works.

> **G-R3 — relocate and bound, do not merely bound.** For a request with offset
> `a` and identity `GCID`, the emitted physical address is `GBASE[GCID] + a`, and
> the access faults per G-R7 unless `a < GLIMIT[GCID]` compared as unsigned (or
> `a < GLIMIT_RO[GCID]` with `GBASE_RO`, for a read matched to the read-only
> window). A context therefore cannot *name* an address outside its window: no
> shader-computed address, no descriptor field, no interpolated coordinate and no
> wrapped texture coordinate can express one, whatever value it holds.
>
> Bounding without relocating was considered and rejected in §16.4. Prior art is
> pre-2006 and predates the ISA this project descends from: CDC 6600 `RA`/`FL`
> relocation-address plus field-length (Thornton, 1964), GE-645 descriptor
> base-and-bound (1965), Cray-1 `BA`/`LA` base and limit (1976).

> **G-R4 — the window registers are unreachable from the GPU, and
> non-delegatable.** `GBASE`, `GLIMIT`, `GBASE_RO`, `GLIMIT_RO` and the
> slot→`GCID` binding are written only by privileged host code. There is no
> `LDS`/`STS` form, no MMIO alias and no command-buffer opcode that reaches them
> from a shader, a command buffer, or any GPU-resident agent. They occupy pages
> of the GPU's control window **distinct from** any page a guest may be given
> under GPU pass-through, and no delegation control may hand a guest authority
> over them or over the fault of G-R7.
>
> This clause exists because the analogous escape is already in the tree twice.
> `HEDR[3]` / `HEDR[24]` delegation hands the FP/SIMD first-use trap to the
> guest, so a scrub written into that handler is switched off by configuration
> ([../../security/threat-model.md §8](../../security/threat-model.md)); and
> `HEDR[23]` — IOMMU fault forwarded as exception — is likewise delegatable
> ([../../hypervisor/hardware-spec.md §2.3.1](../../hypervisor/hardware-spec.md)).
> Delegating `HEDR[23]` does **not** unblock the transaction, and the distinction
> matters: what it removes is the hypervisor's *visibility* of the violation, on
> a bar item whose own text requires that an unclaimed master's DMA "must latch a
> fault". A GPU protection scheme that leaned on that report for detection would
> inherit a control that configuration can switch off.

> **G-R5 — the descriptor index is bounded, and the bound is not load-bearing.**
> `VTEXBASE` and a new descriptor-count register `VTEXCNT` are privileged
> per-context state (G-R4). `VTEXSEL` remains shader-writable (`LDS Rm, VTEXSEL`,
> §9.2). A `VTEX`/`VTFETCH` whose `VTEXSEL` selects an index ≥ `VTEXCNT` faults
> per G-R7. That check is a diagnostic, not the containment: the descriptor fetch
> P3 generates is *also* put through G-R3, so a `VTEXCNT` programmed too large
> cannot reach outside the window — it can only read the context's own memory as
> if it were a descriptor.

> **G-R6 — the texture check is sited at the sampler's address-generation output,
> not at prefix decode.** For P4, the address to be checked does not exist at
> decode. It is produced many cycles later, inside a shared fixed-function block,
> after wrap/clamp/mirror, after LOD selection, after the Morton twiddle, and
> after a memory round-trip that fetched the descriptor whose fields it is
> computed from (§9.3, §9.5, §9.6). The prefix encodes `H`/`ww`/`rrr`/`N` (§3.2
> of [../spec.md](../spec.md)) and nothing about any of that. An implementation
> that asserts this check "at prefix decode" has asserted something it cannot
> perform. P1 and P2 are checked in the SM's own address and fetch paths, P3 at
> the descriptor-fetch address, P5 at the write-out DMA's address generator, P6
> at the command processor's and scanout's address generators — in every case at
> the point that first holds the final address together with the `GCID` G-R2
> carried there.

> **G-R7 — a violation is a fault; never a wrap, a clamp, a truncation or a
> zero.** For the synchronous producers P1–P4 the fault is delivered to the
> issuing (parked) warp and reports the **prefix PC**, per the restart-from-prefix
> contract of [../spec.md §6.4 and §6.5](../spec.md); the block carries no
> committed state, so the report is well-defined even though the warp parked. For
> the asynchronous producers P5 and P6 the transaction is suppressed — the data
> phase for a read, the write dropped — and the GPU latches `{GCID, offending
> offset, producer, R/W}` in a fault register and raises a protection interrupt
> to privileged host code, and the offending context is halted rather than
> allowed to continue. No path may define the result of a blocked access as
> "undefined": that word is banned at an ownership boundary by bar item **L6**
> ([../../security/threat-model.md §8](../../security/threat-model.md)).

> **G-R8 — handover scrubs; saving is not scrubbing.** On any change of owner of
> a warp slot, an SM, a tile-buffer region or a texture-cache line, the state
> tagged to the outgoing `GCID` — the per-warp V/P0/`VCSR` window, the tile
> buffer's colour and Z lines, the texture-cache lines, and any in-flight
> sampler request queue entries — is scrubbed to a defined value before the
> resource is offered to the next context. A save-and-restore discipline is not a
> substitute: a **fresh** context has no saved image, so restoring "its" state
> restores nothing and leaves the predecessor's, which is exactly the branch a
> save/restore test between two established owners passes without touching.

> **G-R9 — what joins the context image, and what does not.** State *about the
> owner* must survive the owner's absence and is saved with the context. State
> *about the structure* is overwritten by the next owner's installation and is
> not.
>
> | State | Class | In the tenant-visible context image? |
> |---|---|---|
> | `VTEXSEL` | about the owner — shader-written, shader-observable | **yes** |
> | `GBASE`, `GLIMIT`, `GBASE_RO`, `GLIMIT_RO` | about the structure — installed by the binder for whoever occupies the slot | **no** |
> | slot → `GCID` binding | about the structure | **no** |
> | `VTEXBASE`, `VTEXCNT` | about the structure — privileged per-context state, reinstalled on every bind | **no** |
>
> The window registers being *per-context* does not make them the context's:
> nothing in them survives to be restored, because the binder writes them from the
> host's record before the context runs a single instruction.

> **G-R10 — this is the inner boundary only, and the outer one is not built.**
> G-R1..G-R9 separate tenants *inside* the GPU. They do not contain a GPU that is
> itself faulty or misprogrammed, because they are enforced by the GPU. The outer
> boundary is the IOMMU on the GPU's fabric master ports, and it is task **C2d**.
> Consequently:
>
> 1. **Multi-tenant GPU operation requires both halves**, and the ordering is
>    hard: C2d before any GPU bring-up that runs more than one tenant. Today the
>    IOMMU resets with `BMID_BYPASS_*` all-ones — every master bypasses — and
>    `ENABLE = 0` ([../../iommu/hardware-spec.md §8](../../iommu/hardware-spec.md)),
>    so routing GPU traffic through it buys nothing until C2d changes that. It is
>    weaker still than "unconfigured": no IOMMU RTL exists in `jcore-soc` or
>    `jcore-cpu` at `origin/master` either (case-insensitive `iommu`, `bmid`:
>    zero files).
> 2. **The GPU has no BMID.** [../../bus/fabric-spec.md §4.4](../../bus/fabric-spec.md)'s
>    normative allocation policy has no GPU row and its §4.5 worked example has
>    none, although [../../iommu/design-spec.md §4.1](../../iommu/design-spec.md)'s
>    topology diagram draws a GPU as an initiator. Assigning one is fabric-spec
>    work that no task currently schedules, and it is a precondition of clause 1.
> 3. **If the GPU arrives before either half, it runs single-tenant.** Exactly one
>    tenant owns the whole GPU at a time — the shape bar item **L1** already
>    imposes on a core — and G-R8's scrub still applies on handover, because
>    handover between single tenants is precisely an ownership change. This is
>    recorded as a supported degraded mode rather than left as an implication, so
>    that shipping it is a decision somebody made.
> 4. **The multi-tenant mode needs one more thing that is not C2d.** **L1** reads
>    "no two tenants occupy thread contexts of one core at any instant" and
>    "cross-tenant fine-grained MT is out of bounds for launch", and an SM is a
>    barrel-threaded core holding 4–8 warps resident
>    ([architecture.md §1.1, §3.1](architecture.md)). Whether an SM is "a core"
>    for L1 is undecided in the text, and the two readings differ on whether the
>    multi-tenant mode is legal at launch at all
>    ([../../security/threat-model.md §8, item L1](../../security/threat-model.md)).
>    Until that is resolved by whoever owns L1, clause 3's single-tenant mode is
>    the only mode this section claims is launch-legal. G-R1..G-R9 remain
>    required in it: they are what separates *processes* inside the one tenant,
>    and what keeps a shader bug inside the tenant that wrote it.

### 16.4 Rejected alternatives

[../../j4-execution-plan.md](../../j4-execution-plan.md) offers this task a
choice — "base+bounds **or** IOMMU/BMID". **That disjunction does not survive
contact with the fabric spec: the two act at different granularities, and only
one of them acts at tenant granularity.** They are not alternatives; §16.3 is the
inner mechanism and G-R10 keeps the IOMMU as the outer one.

**Rejected: the IOMMU with per-tenant BMIDs as the tenant-separation mechanism.**
Three independent reasons, any one sufficient.

1. **The fabric forbids it.** BMID is "an 8-bit identifier held in a register
   inside the fabric (**not inside the master**)" which the fabric "drives onto
   every transaction the port emits, overwriting any BMID-like field the master
   itself might assert"; a conformant master port "MUST NOT expose its BMID
   register to software running on the master"
   ([../../bus/fabric-spec.md §4.1, §4.2](../../bus/fabric-spec.md)). That
   unforgeability is the whole security value of BMID — and it means the GPU
   *cannot* present a different BMID for each of the 4–8 warps per SM it holds
   resident ([architecture.md §1.1](architecture.md)) without one physical
   fabric master port per resident tenant. Per-tenant BMID is not expensive here;
   it is structurally unavailable.
2. **The granularity is wrong even where it is available.** A BMID identifies a
   master. The GPU is one master hosting many tenants at once, by construction:
   FGMT with several resident warps is the mechanism the whole design rests on
   (§9.7, [architecture.md §3](architecture.md)). An IOMMU keyed on BMID can stop
   the GPU reaching outside the GPU's aperture. It cannot stop warp A reading
   warp B's texture, because both requests carry the same BMID.
3. **The performance class is wrong.** The IOMMU has no hardware page-table
   walker; the IOTLB is 64 entries, fully associative, and **written directly by
   software**, and a miss blocks the transaction and raises a fault
   ([../../iommu/design-spec.md §3.1, §3.4](../../iommu/design-spec.md),
   [../../iommu/hardware-spec.md §4.1](../../iommu/hardware-spec.md)). Putting a
   GPU's texture and framebuffer working set behind that turns every capacity
   miss into a blocked transaction plus a host-software refill, on a path whose
   entire premise is that a multi-hundred-cycle sample costs no throughput
   because FGMT hides it (§9.7). A host round-trip is not a latency FGMT hides.

**Rejected: an MMU and TLB per SM.** This is the mechanism that would generalise
best, and it is the right answer at ASIC scale. It is rejected for the first cut
on three grounds: [architecture.md §2](architecture.md) budgets no TLB, walker or
ASID storage, and the LUT budget is the binding constraint the whole document is
written against; demand paging is the feature it buys and a GPU working set is
pinned; and it does not remove any of §16.3's work, because the shared sampler
would still have to carry the requesting context's identity with each in-flight
request (G-R2) for a per-context translation to be applied to it. Recorded as the
successor, not as a discarded idea — see §16.6.

**Rejected: bounds-checking without relocation.** Checking `GBASE ≤ addr <
GBASE + GLIMIT` on an address the shader computes in full is one comparator
cheaper and strictly weaker: it leaves the tenant able to *name* every address in
the machine, so the mechanism's correctness rests on the comparator being present
on all six producers with no gap, rather than on the tenant's address space not
containing the words in the first place. Under G-R1 the two would be equivalent;
relocation is what makes a gap in G-R1 a bug rather than a breach.

### 16.5 Minimize-loss — what this costs, and the experiments that would say

**No figure is given here, because none has been measured.** Per
[../../decisions/0005](../../decisions/0005-unmeasured-figures-are-removed.md) an
unmeasured figure is removed rather than annotated, and the honest value for the
area, frequency and throughput cost of G-R1..G-R8 is
*unknown at this stage — needs measurement*. [../../j4-remediation-plan.md §E.10](../../j4-remediation-plan.md)
prices three classes — speculation defences, eager state switch and scrub, cache
isolation — and **has no line for an address-path check at all**; the nearest
thing it prices is the *scrub* half ("fence.t full on-core scrub is <1% perf /
0.13% area"), which speaks to G-R8 by analogy and says nothing about G-R1..G-R7.
Its sub-1% conclusion must not be borrowed for this item.

Three experiments, each with the result that ends it. A human runs them; none is
runnable before the first SM RTL exists.

1. **Synthesis A/B on the first SM.** Build the SM with and without the window
   checkers — one adder and one unsigned comparator per producer port, the
   `GCID` field widened onto each request, and the window register file — and
   record ΔLUT4, ΔFF and ΔFmax. **Kill criterion:** ΔFmax takes the SM below the
   `Fmax` floor registered for its target in
   [../../platform-baseline.md §3](../../platform-baseline.md). *No such floor
   exists for the Artix-7 XC7A200T the GPU targets* ([architecture.md §1.1](architecture.md));
   the floors registered there are ECP5 ones. **Registering a floor for the GPU's
   target is a precondition of running this experiment**, and inventing one to
   have a criterion would be the failure 0005 exists to prevent.
2. **Texture throughput.** Sustained texels/cycle through P4 with and without the
   G-R6 check, at the 4 and 8 resident-warp points
   ([architecture.md §1.1](architecture.md)). This is the only producer on a
   bandwidth-critical inner loop. **Kill criterion:** the check adds a pipeline
   stage the warp scheduler cannot fill — i.e. sustained texels/cycle falls at
   *both* warp counts, which distinguishes a real throughput loss from latency
   FGMT absorbs.
3. **Shader memory latency.** Added cycles on P1's address path. **Kill
   criterion:** the relocation add cannot be folded into the SM's existing
   address adder and costs a whole cycle in the memory stage — in which case the
   fallback is the rejected bounds-only form of §16.4 for P1 alone, with the
   consequence recorded there accepted explicitly.

### 16.6 What would reopen this

- **An SM that gains an MMU.** If §16.4's per-SM MMU becomes affordable — the
  ASIC scaling of [architecture.md §8](architecture.md) is the obvious trigger —
  the window becomes a redundant second check and should be retired, not kept
  "for safety", because two mechanisms of different granularities that both claim
  to be the isolation boundary is how a gap hides.
- **A GPU working set that stops being one contiguous region.** The single window
  per context is what makes base-and-bound sufficient. Virtual texturing, tenant
  memory that must grow without relocation, or sharing that needs more than the
  one read-only window all break that premise and argue for the MMU.
- **A fabric that can vary BMID per request.** §16.4's first reason is a property
  of [../../bus/fabric-spec.md §4.1](../../bus/fabric-spec.md), not a law. If a
  future fabric admits a fabric-checked sub-master identity, the IOMMU option
  returns to the table for the inner boundary too.
- **C2d landing with a different shape than default-deny.** G-R10's ordering
  constraint is written against the IOMMU that C2d is specified to build. If C2d
  argues its clauses down (§7.7 of the threat model notes two of five are
  inherited without backing), the outer boundary this section assumes changes
  with it.

---

## 17. Open questions

1. **G = 3 / non-power-of-two groups.** Homogeneous 3-vectors (xyz) are common;
   G=4 with a zeroed w-lane covers them, but a native G=3 could save a lane. Decide
   on measured geometry-kernel profiles; likely not worth the gating complexity.
2. **Fused broadcast.** §5 uses an explicit `SWIZZLE` as the first **in-block**
   governed slot for the operand broadcast (reuse-hardware mandate; SWIZZLE is
   in-block-only per [../spec.md §3.3](../spec.md)). This costs one slot, so a
   VFTRV block is `#2`. If profiling shows the broadcast dominates, a quad-broadcast
   operand mode folded into `FMUL` (making VFTRV a `#1` block) could reclaim it —
   deferred, as it adds datapath the mandate currently forbids.
3. **FP16 geometry — specified (§8).** Half-precision transforms (`SIMDHG4` with
   `ww=01`, FP32 accumulate) double geometry throughput and put a full 4×4 matrix in
   one J32 register (§8.6). Remaining sub-question: whether to add a native FP16
   result-narrowing writeback mode to VFTRV or leave it to a following `VCVT.SH`.
4. **Scalar FP16 conversions in the FPU.** §8.5 proposes `FCNVSH`/`FCNVHS` for
   [../fpu/spec.md](../../fpu/spec.md); the encoding and whether to also add `FMOV.H`
   (16-bit FP load/store) are open, tracked against the FPU spec.
5. **Texture coordinate encoding (§9.2).** SoA (`Vu`,`Vv`) vs FP16 AoS `(u,v)` per
   lane — settle in the opcode-map audit against how the shader backend emits coords.
6. **Separable texture+sampler (§9.3).** Bring-up folds sampler state into the texture
   descriptor; whether to expose a separate sampler index (per-stage sampler state,
   as in DX9/OpenGL ≤2002) for shared samplers is deferred until multitexture shaders
   need it.
7. **VQ/DXT decode scope (§9.4).** VQ is required for DC HLE; DXT/ETC are optional
   later adds — confirm no post-2006 compression-format patent applies before adding
   non-DC codecs (VQ itself is 1980/1998, clear).
8. **VFSCA result packing (§10).** sin/cos pair to adjacent lanes vs a second
   destination register (SH-4 `FSCA` uses FRn/FRn+1) — settle in the opcode-map audit.
9. **VROP inclusion (§11.2).** DC 3D needs only fractional `VBLEND`; the Amiga-minterm
   `VROP` is pure upside for 2D/HLE/windowing and near-free — include in the first cut
   or defer? (Leaning include: it is tiny and has 1975/1985 prior art.)
10. **VZTEST tile-buffer coupling (§12.1).** `VZTEST` reads/writes the on-chip tile
    buffer, so it is an SM-profile op like `VTEX`; confirm the tile-buffer port model
    (single-cycle BRAM) before committing the conditional-z-write encoding.
11. **Feature bits.** Allocate `HWCAP_JCORE_SIMD_GEOM`, `HWCAP_JCORE_SIMD_FP16`,
    `HWCAP_JCORE_SIMD_TEX`, and `HWCAP_JCORE_SIMD_RASTER` (transcendentals + blend +
    depth/coverage) alongside the other SIMD tier bits ([../software-impl.md §8.5](../software-impl.md)).
