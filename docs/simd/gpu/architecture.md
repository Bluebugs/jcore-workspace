# jcore SIMT GPU — Architecture (refined to the current plan)

**Status:** Design sketch, re-grounded 2026-07-17.
**Supersedes:** the earlier aspirational "Architecture GPU Hybride Évoluée" draft
(1 GHz / 2–4 cores / 256-bit SIMD / FP64 / fixed-function TPG-ISP-TMU-Tile-Resolve),
which was an ASIC-class wish list disconnected from our ISA, our FPGA target, and
our toolchain reality. This revision keeps the good bones of that draft — hybrid
programmable-core + minimal fixed-function, TBDR, software ray tracing, the
FP16 and anti-Tensor-patent rationale — and rebuilds the numbers, the memory
model, and the execution model on top of what the rest of the plan actually says.

**Reads with:**
- [../spec.md](../spec.md) — the jcore SIMD ISA (the lane ISA reused here). Vector
  width is **VLEN = 8 × XLEN** (256-bit J32 / 512-bit J64), predicate-driven — see §3.3.
- [simd-gpu-spec.md](simd-gpu-spec.md) — the SIMD-GPU extension: FIPR/FTRV promoted
  to V-file segmented reductions (vertex transform, §4.3), FP16 (§8 there), `VTEX`/
  `VTFETCH` texture-sample (§9, drives the §4.2 sampler), transcendentals
  `VFSRRA/VFSCA/VFSQRT` (§10), blend/raster-op `VBLEND/VROP` (§11), and the raster
  back-end `VZTEST/VEDGE/VINTERP` (§12) — all pre-2006-anchored.
- [simd-gpu-spec.md §16](simd-gpu-spec.md) — **memory protection and tenant
  isolation**: the per-context relocate-and-bound window, the **6** address
  producers it covers ([simd-gpu-spec.md §16.2](simd-gpu-spec.md)), and why the
  IOMMU is the outer boundary and not the inner one. That section owns the rules;
  §5.4 below states only what they mean for this document's machine.
- `../../no-gpu-decision.md` — Option B: SIMT = FGMT+SIMD+
  predication; TBDR mandatory; sort-middle binning as a compute kernel; toolchain
  is the bigger half; 85F caps at one ~8-lane SM. **This file does not exist**
  in the workspace or anywhere in its git history, and is cited eight times
  across this document and
  [../../no-gpu-dual-ecp5-asic.md](../../no-gpu-dual-ecp5-asic.md) as the record
  holding the GPU decision itself. The links below are left unlinked for the same
  reason; recovering or rewriting it is not this document's work, but a reader
  should not be sent chasing it.
- [../../no-gpu-dual-ecp5-asic.md §6](../../no-gpu-dual-ecp5-asic.md) — the target
  hardware: **single Artix-7 XC7A200T, unified DDR3 via the jcore-soc controller, accept-HLE.**

---

## 1. What this is now

A **programmable SIMT GPU built from barrel-threaded jcore cores**, with the two
fixed-function blocks you cannot skip (rasterizer setup + texture sampler),
sharing **one unified DDR3 bank** with the J4 CPU through the **existing jcore-soc
DDR controller** (multiport front-end), on a **single Artix-7 XC7A200T** with an
**open toolchain** (openXC7). Historical-game (Dreamcast) rendering runs through an **HLE
translation layer** (§7), not a bus-accurate PVR2 — we deliberately accept an
emulation layer to buy unified memory and toolchain flexibility.

The design is a **bring-up vehicle first**: one SM on the A200T proves the ISA +
toolchain + tile pipeline; the *same RTL* scales to more SMs on bigger silicon
for DC-class fill rate (§8). Nothing below assumes a clock or lane count we can't
hit on the A200T.

### 1.1 Target parameters (grounded, not aspirational)

| Parameter | This design (A200T bring-up) | Old draft | Why changed |
|---|---|---|---|
| Clock | **~75–100 MHz** | 1.0 GHz | ECP5/7-series soft core reality; the old 1 GHz was ASIC-only |
| Cores (SMs) | **1 SM to start, 2 SMs when it fits** | 2–4 | A200T ≈134K LUT6 / 740 DSP holds ~2 SMs + J4 + DDR ctrl + scanout |
| Lanes / SM | **8 FP32 on J32 (256-bit reg); 16 on J64 (512-bit) or two SMs** | — | warp width = register width (§3.3) |
| Warps / SM (FGMT) | **4–8 resident** | 4 threads | ≥ pipeline-depth warps hides mem/texture latency and deletes forwarding |
| Predication | per-lane mask (P0 = integer GPR) + reconvergence stack | 32-bit predicate reg | P0 / VCSR.MKE in [../spec.md](../spec.md); its GPR width sets lane count (§3.3) |
| Numeric types | **FP32 (DSP48-backed) first**; INT8/16/32; FP16 specified ([simd-gpu-spec.md §8](simd-gpu-spec.md)), enabled in phase 2 | FP16/32/64 | FP64 unneeded for graphics; FP16 = bandwidth/BVH/throughput win (FP32-accumulate) |
| Vector width | **256-bit on J32 / 512-bit on J64** (= 8 × integer-register-width, predicate-driven) | 256-bit SIMD | the old "256-bit / 8 FP32" is exactly the J32 point once aligned (§3.3) |
| Memory | **unified 256 MB DDR3 via the existing jcore-soc DDR controller** | RAM + shared L3 + SRAM (handwave) | one DDR bank shared CPU/GPU (§5) |

---

## 2. FPGA resource budget (XC7A200T)

A200T ≈ **134K LUT6, 740 DSP48, ~13 Mb BRAM** — roughly **2–3× the logic and
~4.7× the DSP** of the ECP5-85F the no-gpu-decision budget was drawn against.
That is the concrete unlock: the two-8-lane-SM configuration that *overflowed*
the 85F (~114K LUT4) now fits **alongside** the J4 SoC and the DDR controller.

An 8-lane FP32 SM on J32 is exactly **one 256-bit V-register operation per issue**
(§3.3), so the lane count and the register width coincide — no partial-register
packing. Indicative first-SM budget (one 8-lane SM + shared fixed function + scanout;
leaves ample room for the J4 SoC + DDR controller on the same die):

| Block | LUT6 (rough) | DSP48 | BRAM |
|---|---:|---:|---:|
| 8× integer ALU lanes (jcore-derived) | ~10K | – | – |
| 8× FP32 FMA lanes | ~6K | ~24 | – |
| Scalar/control + warp scheduler + scoreboard + mask/reconverge stack | ~6K | – | few |
| Per-warp vector/scalar register file (multiport, BRAM/LUTRAM) | ~4K | – | ~24 |
| Texture sampler + cache (bilinear/tri, VQ/DXT decode) | ~8K | ~12 | ~24 |
| Rasterizer: triangle setup + half-space (Pineda) + hierarchical reject | ~7K | ~8 | – |
| On-chip tile buffer (color+Z, double-buffered) | ~2K | – | ~16 |
| Command processor + DDR-controller ports + DMA | ~6K | – | few |
| Shader I-cache + vertex/attr caches + FIFOs | ~3K | – | ~24 |
| HDMI/DVI scanout | ~3K | – | few |
| **Subtotal (GPU side)** | **~55K / 134K** | **~44 / 740** | **~120 / 365 (RAMB36)** |

DSP and BRAM are *abundant* here (the 85F's second bottleneck is gone), so the
follow-on second SM is LUT-bound, not DSP/BRAM-bound — exactly the good scaling
property the no-gpu-decision note wanted.

**What this table does not contain, said plainly because it is load-bearing
elsewhere.** There is no TLB row, no page-table-walker row and no ASID storage.
That is a deliberate consequence of §3.2's "reuse the SIMD datapath, add the SIMT
wrapper" — the SM is not a J4 core with an MMU — and it is the reason GPU
addresses are physical and need their own protection mechanism
([simd-gpu-spec.md §16.1](simd-gpu-spec.md)). The window checkers that mechanism
adds (one adder and one unsigned comparator per address-producer port, plus the
window register file) are not costed in this table either: their area and Fmax
effect is *unknown at this stage — needs measurement*, and the A/B that would
settle it is [simd-gpu-spec.md §16.5](simd-gpu-spec.md) experiment 1. That
experiment also needs something this workspace does not yet have: an `Fmax` floor
registered for the XC7A200T in [../../platform-baseline.md §3](../../platform-baseline.md),
whose floors are all ECP5 ones.

---

## 3. Execution model: SIMT = FGMT + SIMD + predication

Per `../../no-gpu-decision.md` (missing — see the reads-with note), a GPU "warp" is just:
a **shared-PC SIMD** vector issue over W lanes, **barrel-threaded (FGMT)** across
N resident warps so the scheduler issues a *ready* warp each cycle and hides
memory/texture latency, plus a **per-lane execution mask + reconvergence stack**
for divergence. This is the SPMD model the project already works in.

### 3.1 The SM pipeline

```
 warp scheduler (greedy-then-oldest, ready warps only)
        │  picks 1 ready warp / cycle
        ▼
 fetch → decode (jcore generated decoder + SIMT/vector opcodes)
        │
        ▼
 8-lane datapath: per-lane INT ALU + FP32 FMA, shared PC,
        per-warp register window, per-lane mask
        │           │
        │           └─► texture request ─► shared sampler (latency hidden:
        │                                    warp parks, scoreboard wakes it)
        ▼
 writeback → per-warp registers / tile buffer
```

FGMT **loves jcore's in-order pipeline**: with ≥ pipeline-depth warps resident,
a warp's next instruction is many cycles away, so the forwarding/interlock logic
that constrains jcore's 2-slot decode/sequencer largely disappears. This is a
structural win, not just a throughput one.

### 3.2 Reuse of the jcore SIMD ISA (spec.md) as the lane ISA

The lane compute path is **the existing SIMD datapath from [../spec.md](../spec.md)**,
not a new unit:

- Per-warp vector registers ↔ the **V0..V15** file (VLEN-wide: 256-bit J32 / 512-bit J64; §2.1 there).
- Per-lane predicate ↔ **P0 + VCSR.MKE** masked mode (§4.3/§4.4 there).
- Integer/FP governed ops ↔ the Tier 0/1 lane ops (§5.1/§5.2 there).
- Horizontal reductions ↔ SIMDH (dot products, tile reductions).

The GPU adds the *SIMT wrapper* around this datapath: warp scheduler, per-warp
PC/register-window/scoreboard, mask+reconvergence stack, and the vector
load/store/gather/scatter already specified for VLD/VST/VGATHER (§5.6 there).
The generated decoder (Go `gen-go` + TOML→VHDL) is extended with the SIMT
control opcodes — a front-end change the existing infrastructure carries.

### 3.3 SIMD register width tracks the integer register width

Predication is built on a jcore **integer register** used as the per-lane mask
(P0), one bit per byte-lane ([../spec.md §2.5](../spec.md)). That ties the natural
SIMD register width to the core's integer width — the predicate GPR must hold one
bit for every byte-lane, so the register is 8× as wide as the GPR:

- **J32 (32-bit core):** a 32-bit predicate GPR → 32 byte-lanes → **256-bit V
  registers** → **8 FP32 lanes** (16 FP16, 32 INT8) per warp.
- **J64 (64-bit core):** a 64-bit predicate GPR → 64 byte-lanes → **512-bit V
  registers** → **16 FP32 lanes** per warp.

So **warp width = register width = 8 × integer-register-width**, and the two never
disagree. The old draft's "256-bit SIMD, 8 FP32/cycle" is exactly the J32 point
once the register width is aligned this way; "16 FP32/cycle" is one **J64** SM
(512-bit) or two J32 SMs.

FP16 (the draft's headline doubling to 16/32 lanes) is **specified in
[simd-gpu-spec.md §8](simd-gpu-spec.md)** (binary16 lanes, FP32-accumulate
reductions, VCVT.HS/SH conversions). It is scheduled *after* FP32 bring-up because
it halves BVH size and texture/geometry bandwidth — landing with the shading /
ray-tracing phase (§6) — and because on **J32 a full 4×4 FP16 matrix fits in one V
register**, making it the geometry throughput lever there. Position transform stays
FP32; FP16 is for shading/BVH/ML (§8.6 there).

> **Spec note (ISA change, not yet applied).** This aligns the SIMD register width
> to the predicate GPR width and **supersedes** the "128-bit mandatory / Tier 3 =
> 256-bit reserved, J64-only" discipline in [../spec.md §1.2](../spec.md).
> Propagating 256-bit (J32) / 512-bit (J64) back into spec.md touches the V-file
> size (2048→4096 / 8192 bits), P0 width (16→32 / 64),
> the 520-byte context-switch image ([../spec.md §2.5](../spec.md); this line
> previously read 272), and the lane/reduction tables. Tracked as a separate ISA edit.

---

## 4. Fixed-function: keep it minimal

Only two blocks are non-negotiable fixed function (per no-gpu-decision); every
other stage the old draft hardwired (TPG, ISP HSR, Tile Resolve) becomes either
a **compute kernel on the SMs** or a small helper inside the tile buffer.

### 4.1 Rasterizer / triangle setup (small, regular)

Edge functions `E_i = A_i·x + B_i·y + C_i`, bounding box, `1/(2·area)` reciprocal,
per-attribute plane equations; **half-space (Pineda) rasterization** with
hierarchical trivial reject/accept at 8×8 tiles → 2×2 quads; incremental stepping
(`E(x+1,y) = E(x,y) + A` — adds only). Emits 2×2 quads with perspective-correct
interpolants to the SMs.

### 4.2 Texture sampler (or you die on bandwidth)

One sampler shared across the SM; FGMT hides its latency. Pipeline: address gen
(wrap/clamp/mirror, LOD/mip) → **2×2 texel fetch from a small BRAM cache**
(store texels so quad neighbors are local) → decompress (**VQ** — DC textures are
already VQ, a cheap 2×2 codebook lookup; DXT/ETC optional) → format unpack
(RGB565/ARGB4444/… → RGBA) → filter (bilinear = 3 lerps/channel; trilinear = ×2
mips + 1 lerp; aniso optional).

This sampler is **exposed as a first-class instruction, `VTEX`/`VTFETCH`**, in
[simd-gpu-spec.md §9](simd-gpu-spec.md) (the pre-2006 DX ps.1.4 `texld` /
`ARB_fragment_program` `TEX` model: coordinate operand + external descriptor,
long-latency, CDC-6600-scoreboard/FGMT-hidden). The instruction *drives* this
datapath; the texel fetch reuses the gather path and the filter reuses the FP FMA
lanes.

### 4.3 Everything else is programmable / compute

- **Vertex + geometry transform:** SM compute via the **`VFTRV`/`VFIPR` geometry
  extension** ([simd-gpu-spec.md](simd-gpu-spec.md)) — one broadcast+FMUL+segmented-reduce
  per vertex (matrix×vector), replacing scalar FMAC chains; FGMT hides its latency.
- **Normalize / lighting / rotation:** the **`VFSRRA`/`VFSCA`/`VFSQRT`** transcendental
  helpers ([simd-gpu-spec.md §10](simd-gpu-spec.md)) — the SH-4 3D-helper siblings of
  FTRV/FIPR, promoted to per-lane SIMD.
- **HSR / Z-cull (old "ISP"):** the **`VZTEST`** instruction ([simd-gpu-spec.md §12.1](simd-gpu-spec.md))
  — per-lane depth compare against the on-chip tile buffer → P0 kill-mask + conditional
  z-write; deferred so only visible fragments shade.
- **Binning (old "TPG"):** a **SIMT compute kernel** using **`VEDGE`** coverage
  ([simd-gpu-spec.md §12.2](simd-gpu-spec.md)) — bbox + edge-reject + prefix-sum, no
  dedicated binning hardware (§5.3). Attribute setup uses **`VINTERP`** (§12.3).
- **Blend / fog / tile write-out (old "Tile Resolve"):** the **`VBLEND`** instruction
  ([simd-gpu-spec.md §11](simd-gpu-spec.md)) — fractional-alpha ROP on packed RGBA8
  (VIS-lineage), fog as a blend mode; then a burst DMA of the finished tile to DDR.
  (Optional **`VROP`** boolean raster-op for 2D/HLE.)
- **Ray tracing:** software/SPMD, optional, post-bring-up (§6).

---

## 5. Memory: unified DDR3 + TBDR

### 5.1 One bank, many ports (jcore-soc DDR controller)

All large state lives in the **single 256 MB DDR3 bank**, shared with the J4 CPU
through the **existing jcore-soc DDR controller** fronted by a **multiport arbiter**
(the SoC bus crossbar): main RAM, textures, geometry, per-tile lists, and the
framebuffer. We reuse the controller the SoC already has rather than pull in an
external one; the only target-specific work is mapping its DDR **PHY** onto the
chosen FPGA's DDR I/O primitives (§8). On-chip BRAM holds only the
latency-critical, high-reuse structures: the **tile buffer**, the **texture
cache**, per-warp **register files**, the shader **I-cache**, and FIFOs. This is
the unified-memory model the plan committed to — flexible, and the HLE layer (§7)
feeds the GPU through the same bank.

DC's total memory footprint (26 MB: 16 main + 8 VRAM + 2 audio) fits comfortably
in one 256 MB bank, so "unified" costs us nothing in capacity and buys the
flexibility modern hardware favors.

### 5.2 TBDR is mandatory (this is what makes fill rate survive)

A programmable core's fill rate is set by *per-pixel instruction count* — the
price of programmability. **Tiling is what keeps that price in on-chip ALU
(which scales with silicon) instead of DRAM bandwidth (which doesn't):**

1. Bin geometry per screen tile (display list per tile, in DDR).
2. Shade each tile into the **on-chip color+Z tile buffer**, deferred: resolve Z
   first, run the fragment shader only on visible pixels.
3. Burst the finished tile to the DDR framebuffer once.

This eliminates overdraw cost and slashes framebuffer bandwidth — recovering most
of the ~4× fill deficit vs. the real DC, whose effective fill rate *depends* on
TBDR. With tiling, the residual limit is texture-DRAM bandwidth via cache misses
(mitigated by mip locality + VQ/DXT compression) and the per-pixel shader ALU.

### 5.3 Binning = sort-middle, done on the SMs

Screen-space, view-dependent, rebuilt every frame (not a persistent BSP tree —
that buys nothing here). Coverage filter = triangle screen-AABB → tiles, then
edge-function trivial-reject at tile corners (the rasterizer's coarse test reused
at tile granularity). Per-tile list build = **parallel prefix-sum** (Laine–Karras
"sort-middle" style). The SM lanes that shade also sort — **no dedicated binning
hardware**. Tile size trades cull efficiency against triangle replication and
tile-buffer BRAM (a sizing knob, not an architectural fork).

### 5.4 Protection: one window per context, and who checks it

Unified memory is what makes the protection question sharp: the GPU's addresses
land in the *same* DDR bank as the J4 CPU's, through the same multiport arbiter
(§5.1). Nothing in §5.1–§5.3 constrains which part of that bank a shader reaches.

The rules are owned by [simd-gpu-spec.md §16](simd-gpu-spec.md) and are not
restated here. What matters for *this* document is which of its blocks are
address producers, because §16's G-R1 requires every one of them to carry the
owning context's `GCID` and pass the window check:

| This document's block | Producer in [simd-gpu-spec.md §16.2](simd-gpu-spec.md) |
|---|---|
| SM lane load/store/gather, and the §5.3 binning kernel that runs on those lanes | P1 |
| Shader I-cache (§2) | P2 |
| Shared texture sampler (§4.2) — descriptor fetch, then texel/mip/palette/VQ fetch | P3, P4 |
| Tile write-out burst DMA (§4.3, §5.2) | P5 |
| Command processor and HDMI/DVI scanout (§2) | P6 |

Two consequences land on this document's design rather than on the ISA:

- **The sampler must carry `GCID` with each in-flight request.** It is one block
  shared across the SM (§4.2) and its latency is hidden by parking the warp and
  running others (§3.1). The requesting warp is therefore *not* the warp on the
  pipe when the texel address is generated, so the identity has to travel with
  the request rather than be read from the scheduler.
- **The tile buffer, the texture cache and the per-warp register files are
  ownership-change sites.** §16's G-R8 requires them scrubbed when their owner
  changes, not merely saved and restored — a fresh context has no image to
  restore, so a restore-based scheme leaves the predecessor's data in place.

---

## 6. Ray tracing (software / SPMD, optional)

Kept from the old draft, correctly scoped as **post-bring-up**: rays batched (16
in FP16 once FP16 lands) and traversed against a BVH by **software on the SM
lanes** — no fixed-function RTU. This buys silicon for bigger caches/more lanes
and full flexibility on the BVH format. A cache miss on the BVH read just parks
the warp; the scoreboard wakes it — the same FGMT latency-hiding as textures.
Avoid asynchronous "Tensor"-style matrix units — heavily patented; the pre-2006
prior-art policy in [../../glossary.md](../../glossary.md) applies here too.

---

## 7. HLE layer for historical games (the accepted "emulation")

We explicitly accept a translation layer instead of a bus-accurate PVR2. A
flycast-derived **HLE** runs on the J4 (or an external host during early
bring-up) and:

- **captures the Tile Accelerator command stream** a game programs, and
- **re-emits it as our GPU's command lists + shader invocations**, writing
  geometry/textures into the unified DDR bank.

Because our core is *programmable*, it can render the PVR2 semantics that a
fixed-function forward renderer (FuryGpu-class) gets wrong: **per-pixel
order-independent translucency** (the tile buffer / depth-peel handles it),
**modifier/shadow volumes**, punch-through, and DC blend/fog modes — correctly,
trading raw fill rate for that correctness. This is the "programmable route
renders PVR2 semantics correctly where fixed-function can't" resolution from the
no-gpu-decision note. (An open fixed-function alternative,
[polly2-rtl](https://github.com/skmp/polly2-rtl), exists but is Altera/hybrid and
does not fit this single-FPGA unified-memory plan — see
`../../no-gpu-decision.md` 2026-07 update (missing — see the reads-with note).)

---

## 8. Bring-up ladder and ASIC scaling

Matches the no-gpu-decision ladder, re-anchored to the A200T:

0. **Protection before step 1 runs anybody else's code.** Step 1 runs a user
   OpenCL kernel, which is the exact trigger
   [../../j4-remediation-plan.md §C2](../../j4-remediation-plan.md) names. Two
   states are supported and they differ in what has to exist first:
   **single-tenant** — one tenant owns the whole GPU at a time, with §16's G-R8
   scrub on handover — needs only the window checkers; **multi-tenant** needs
   those *and* task C2d, because the IOMMU is the outer boundary and today it
   resets to all-bypass ([simd-gpu-spec.md §16.3](simd-gpu-spec.md) G-R10).
   Bringing the GPU up before either exists is allowed only in the single-tenant
   state, and only as a decision somebody recorded.
1. **ISA + toolchain spine.** Define the SIMT/vector extension on jcore; simulate;
   run an **OpenCL kernel via PoCL** (compute only, no graphics) on one SM.
2. **First pixels.** Add the fixed-function **texture sampler + rasterizer setup**;
   software shading; render simple scenes via a **TinyGL-style GL subset** (not
   Mesa yet); TBDR tile buffer online; HDMI scanout.
3. **Real GL.** **Mesa Gallium + a NIR → SIMT-ISA backend.** Underneath all of it
   sits an **LLVM backend** for the SIMT ISA — the toolchain is the bigger half
   and the real risk, exactly as the note warns.
4. **Second SM / FP16 / software RT / HLE** as the A200T budget and the workload
   demand.
5. **Vulkan/SPIR-V** — distant north star, and only a *software API we would run*
   (implementing an API is not a hardware-design dependency), not a milestone and
   not a source for any ISA/microarchitecture decision (those are pre-2006-anchored,
   [simd-gpu-spec.md §9.9](simd-gpu-spec.md)).

**ASIC scaling.** The two fixed-function blocks and the SM are the RTL that
carries to silicon. On an ASIC the FPGA-specific pieces (the DDR PHY mapping, the
~75–100 MHz ceiling) are replaced by hard DDR and a much higher clock, and SM
count scales ~3–4×; the architecture does not change — only SM count and DRAM do.
Going J32→J64 also widens every V register 256→512-bit (§3.3), doubling FP32
lanes per SM for free at the ISA level.
"Validate the whole stack on the A200T, scale identical RTL later" is the plan.

---

## 9. Open questions

1. **Warp count vs. register-file BRAM.** 4 vs. 8 resident warps trades
   latency-hiding against per-warp register BRAM pressure — settle by simulation
   once the SM RTL exists.
2. **16 FP32/cycle: J64 SM vs. two J32 SMs?** Register width is settled (256-bit
   J32 / 512-bit J64, §3.3), so "16 FP32/cycle" is either one 512-bit J64 SM or
   two 256-bit J32 SMs. Decide on measured LUT/Fmax, not up front. (Also gates the
   spec.md width propagation noted in §3.3.)
3. **Sampler count.** One shared sampler per SM at bring-up; a second sampler is
   the first thing to add if trilinear/multitexture shaders bind (co-primary
   limiter with per-fragment ALU).
4. **HLE host during bring-up.** J4 is too slow to drive a DC HLE in real time
   early on; an external host over USB/PCIe may be needed until the on-die J4 +
   optimizations catch up (or accept sub-real-time bring-up, as polly2-rtl does).
5. **FP16 timing.** When FP16 lands, confirm the DSP48 packing (two FP16 MACs per
   DSP) actually holds Fmax; otherwise FP16 is LUT-built and the area math shifts.
