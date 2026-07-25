# Dual ECP5-85F (CPU + GPU, shared memory) toward ASIC DC hardware

**Status:** Research note / parked analysis
**Date:** 2026-07-17
**Context:** Follow-up to [no-gpu-decision.md](no-gpu-decision.md) and
[polly2-rtl](https://github.com/skmp/polly2-rtl). Question asked: *could we wire
two ECP5-85F together — one dedicated to the GPU — sharing the same memory, as a
step toward designing ASIC Dreamcast hardware?*

---

## TL;DR

- **As a partitioning idea it is sound and actually matches the real Dreamcast**,
  which is *not* a shared-memory machine: SH4 has 16 MB main RAM, PVR2 has its
  own 8 MB VRAM on a separate bus, AICA has 2 MB. A "CPU chip + GPU chip, each
  with private DRAM, connected by a bus" two-board rig mirrors the SH4↔Holly
  split cleanly. **Two ULX3S boards is a legitimate prototyping topology.**
- **"Sharing the same memory" is the wrong goal** and the hard part. True shared
  external DRAM between two FPGAs needs an arbiter, halves bandwidth, and isn't
  how DC works. The right model is **private memories + DMA/message-passing over
  the inter-chip link** — which is the DC model anyway.
- **The inter-chip link is the binding constraint on standard ULX3S:** the board
  populates **LFE5U-85F, which has NO SERDES** (SERDES exists only on the UM/UM5G
  variants). So no 3.2/5 Gbps hardened lanes — you get **source-synchronous LVDS
  over GPDI + GPIO diff pairs**, realistically a few hundred MB/s to maybe ~1–2
  GB/s aggregate under yosys/nextpnr. Fine for the SH4→TA command/texture DMA
  path; **far too little to let two chips share a GPU's VRAM/tile traffic**
  (that wants tens of GB/s).
- **What the split buys you:** it relieves the "one 85F = one ~8-lane SM /
  ~½ DC fill" LUT wall from [no-gpu-decision.md](no-gpu-decision.md) by giving
  the GPU a *whole* 84K-LUT chip and the CPU another. It does **not** remove the
  toolchain (Mesa/NIR/LLVM) half, the missing SH4 fast vector FPU, or (for
  polly2-rtl specifically) the Altera→ECP5 port and the software-emulator-host
  dependency.
- **For the ASIC end-goal the two-chip FPGA partition is only a validation
  vehicle.** On silicon you have one die, real DDR at tens of GB/s, and 3–4× the
  logic — the FPGA chip-count and its slow LVDS bus disappear from the final
  design. "Validate the stack on 85F, scale identical RTL later" already covers
  this.

---

## 1. Map to the real Dreamcast memory architecture

DC is a **partitioned (non-unified) memory** design:

| Block | Memory | Bus |
|---|---|---|
| SH4 CPU | 16 MB SDRAM (main) | SH4 external bus, 64-bit @ 100 MHz |
| PVR2 "Holly" GPU | 8 MB VRAM | dedicated PVR bus (~800 MB/s class) |
| AICA audio (ARM7) | 2 MB | AICA local bus |

The SH4 does **not** read/write VRAM as shared memory in the fast path; it
**DMAs display lists + textures** into VRAM through the Tile Accelerator, and
programs PVR registers. That is a **producer→consumer command stream**, not
shared memory. So the natural two-FPGA partition is:

```
   ULX3S #A  (CPU)                         ULX3S #B  (GPU)
 ┌────────────────────┐   LVDS bus     ┌────────────────────┐
 │ J4/SH4-class core   │  (GPDI+GPIO)   │ PVR2-style or       │
 │ + MMU + FPU         │◄──────────────►│ programmable SM GPU │
 │ + AICA (ARM7+DSP)   │  TA cmd / DMA  │ + rasterizer/TSP    │
 │ 32 MB SDRAM (main)  │  reg / IRQ     │ 32 MB SDRAM (VRAM)  │
 └────────────────────┘                 └────────┬───────────┘
                                                  │ GPDI → monitor
```

Each board uses **its own on-board SDRAM** as private memory. The link carries
exactly what the SH4↔Holly interface carries: TA vertex/parameter DMA, texture
uploads, register writes, vsync/IRQ. This is bandwidth-modest (per-frame lists +
texture deltas at 30 fps) and fits the LVDS budget below.

**Conclusion:** don't share memory — replicate the DC's private-memory + bus
topology. It's easier *and* more faithful.

---

## 2. The inter-chip link (the real constraint)

Standard ULX3S FPGA = **LFE5U-85F-6BG381C**. Key fact from the ECP5 datasheet /
SERDES usage guide (FPGA-TN-02206): **SERDES Duals (DCU, 3.2 Gb/s; 5 Gb/s on
-5G) exist only on LFE5UM / LFE5UM5G parts.** The plain "U…F" part on ULX3S has
**none**. Boards that do expose SERDES are e.g. **ECPIX-5 (LFE5UM5G-85F)**.

So on two stock ULX3S boards the link options are:

| Link | Physical | Realistic throughput (yosys/nextpnr) | Notes |
|---|---|---|---|
| **GPDI** | 4 TMDS/LVDS diff pairs (AC-coupled, HEC-capable) | ~0.2–1 Gbps/pair source-synchronous → **~0.5–2 GB/s aggregate** at the optimistic end | designed for TMDS video rates + Ethernet-over-HDMI board-to-board |
| **GPIO** | 12 true diff pairs (PMOD, 2.5 V) | +several hundred Mbps/pair | adds width for a parallel bus |
| **US2/US3** | USB (FTDI) | ~MB/s | control/debug only, not a data path |

No hardened 8b/10b/PCS, so you hand-build source-synchronous LVDS with a clock
lane + DDR capture, or a slow parallel handshake. **Good enough for a
command/DMA channel; not good enough to unify GPU-internal memory across chips.**

**Corollary for GPU scaling:** you cannot use the second chip to make *one*
bigger GPU (two SMs sharing a tile buffer / VRAM want tens of GB/s of coherent
traffic). The clean split is **CPU-chip + GPU-chip**, one SM on the GPU chip.
A second SM would need to live on the *same* die/chip as the first to share VRAM
at BRAM/DRAM bandwidth — which is exactly what the ASIC (not the FPGA rig) gives
you.

---

## 3. What the split does and does not fix

**Fixes / helps:**
- **LUT wall.** [no-gpu-decision.md](no-gpu-decision.md) put two 8-lane SMs at
  ~114K LUT (>84K ceiling). Dedicating a whole 85F to the GPU gives it the full
  ~84K; the CPU/MMU/FPU/AICA get the other 84K. Each half now fits with headroom.
- **Faithful topology.** Mirrors SH4↔Holly, private VRAM, DMA command stream.
- **Independent Fmax.** CPU and GPU clock domains fully separated; the LVDS bus
  is the only CDC, and it's a narrow, well-defined interface.

**Does not fix:**
- **polly2-rtl portability.** It's SystemVerilog + Quartus + Altera primitives,
  "takes over most of" a *bigger* DE10-Nano, and is a **hybrid** that needs a
  flycast-class **software emulator host** feeding the TA stream. On this rig the
  host would have to be the CPU-chip J4 (~50–100 MHz — nowhere near enough) or an
  external PC over USB (too slow). Porting SV→ECP5 (sv2v/Synlig) is its own
  project. So "GPU chip runs polly2-rtl" is not near-term realistic.
- **Programmable-GPU toolchain.** The Mesa/NIR/LLVM-backend half — the part
  every CPU-derived-GPU project dies on — is unchanged.
- **SH4 fast vector FPU** (paired-single, FTRV, FIPR) still unbuilt; DC *games*
  need it even if the GPU is solved.
- **ASIC relevance.** The two-chip FPGA partition and its LVDS bus are a
  prototyping artifact. The ASIC is one die with real DDR; the interesting RTL
  (SM, rasterizer, TSP, TA) is what carries over, not the board topology.

---

## 4. If ever pursued: realistic ladder for the two-chip rig

1. **Define the inter-chip bus first.** A source-synchronous LVDS link over GPDI
   (clock + N data lanes, DDR) with a simple credit/DMA protocol. Prove it
   board-to-board with a loopback throughput/BER test *before* any GPU work.
   This de-risks the one genuinely novel piece.
2. **CPU chip = existing jcore SoC** (SH4-class J4 + MMU + SDRAM + AICA stub) with
   the link as a DMA master — reuses the whole ULX3S SoC roadmap.
3. **GPU chip = Option-B step 1–2** from [no-gpu-decision.md](no-gpu-decision.md):
   one 8-lane SIMT SM (jcore SIMD-derived) + rasterizer setup + texture sampler +
   on-chip tile buffer (TBDR) + GPDI scanout, fed by the link. Run an OpenCL
   kernel via PoCL first (compute), then a TinyGL-style subset (graphics).
4. **Only then** consider polly2-rtl as an *alternative* GPU-chip payload, on a
   SERDES-bearing board (ECPIX-5 / CertusPro-NX) with a real host — a different
   track, not this rig.
5. **ASIC:** collapse both chips onto one die, swap LVDS for on-die fabric + real
   DDR, scale the SM count 3–4×. Same RTL.

---

## 5. Bottom line

- **Two ULX3S as CPU-chip + GPU-chip with private SDRAMs and an LVDS command
  bus is a good, DC-faithful prototyping topology** — and the cleanest way to
  dodge the single-85F LUT wall.
- **Do not try to literally share one memory between the two FPGAs** — no SERDES,
  no shared DRAM, and DC doesn't work that way. Use private memories + DMA.
- **It buys logic headroom, not a shortcut past the real blockers** (toolchain,
  SH4 vector FPU, polly2's Altera/host dependency).
- **For the ASIC goal the rig is a validation vehicle only.** Worth doing *if*
  the programmable-GPU program is ever un-parked; not a reason on its own to
  un-park it.

---

## 6. Reframe: unified memory on a *single* bigger FPGA (2026-07)

If we accept an **HLE / "emulation" layer** (translate the TA command stream to a
programmable jcore-SM GPU, rather than bus-accurate PVR2), then unified memory —
which modern hardware favors for flexibility — becomes the better target, and the
whole two-chip split above collapses into a simpler question: **one FPGA big
enough for J4 + GPU + an open DDR controller, sharing one DDR bank.**

This removes the section-2 inter-chip-link problem entirely (no LVDS bus, no
SERDES gap) and replaces the shared-DRAM arbiter with an on-die multiport
controller. The binding constraint becomes "biggest part with a *usable open
toolchain* and a *real open DDR path*."

### 6.1 The pieces that make it real in 2026

- **Open place-and-route for big Xilinx 7-series: [openXC7](https://github.com/openXC7/nextpnr-xilinx)**
  (yosys + nextpnr-xilinx + prjxray). Supports **XC7A200T** and Kintex-7
  (325/420/480T). At **FOSDEM 2025** they demoed a full A200T SoC on openXC7 with
  **HDMI, MMCM, IOSERDES, SD, and an open DDR3 controller**.
- **DDR3 controller: reuse the existing jcore-soc controller.** We already have a
  DDR controller in jcore-soc, fronted by the SoC bus crossbar as a **multiport
  arbiter** so J4 and the GPU share one DDR3 bank. **This is the unified-memory
  model**, and the emulation layer feeds the GPU instead of a bus-accurate PVR2.
  The only target-specific work is mapping the controller's **DDR PHY** onto the
  FPGA's DDR I/O primitives (DQS/IDELAY/ISERDES). openXC7's FOSDEM 2025 demo
  shipped an open DDR3 controller on A200T, so prjxray/nextpnr-xilinx **model the
  DDR primitives** — evidence the jcore PHY can be brought up under the open flow
  without Xilinx MIG.

### 6.2 Why XC7A200T is the right size (the concrete unlock)

XC7A200T ≈ **134K LUT6, 740 DSP48, ~13 Mb BRAM**, vs ECP5-85F's **84K LUT4 /
156 DSP / ~5.4 Mb**: roughly **2–3× the usable logic and ~4.7× the DSP**. LUT6
pack more per cell, so this clears the wall that killed the two-SM plan in
[no-gpu-decision.md](no-gpu-decision.md) (§"Two cores … does NOT fit one 85F":
~114K LUT for two 8-lane SMs > the 84K ceiling). On a 200T that **fits alongside
the J4 SoC and the DDR controller**, with headroom. The **740 DSP48s** are the
bigger deal for the GPU — that's the FP32-FMA lane budget and the SH4 vector-FPU
path, where the 85F was DSP-tight.

### 6.3 FPGA candidate ranking (open toolchain + DDR + capacity)

| Option | Logic / DDR | Open-flow verdict |
|---|---|---|
| **Artix-7 XC7A200T** ⭐ | 134K LUT6 / 740 DSP / DDR3 | **Recommended.** openXC7 proven on A200T incl. open DDR3; reuse the jcore-soc DDR controller (multiport arbiter = unified mem), port its PHY to the 7-series DDR primitives |
| Kintex-7 XC7K325T | ~203K LUT6 / 840 DSP / DDR3 | Scale-up for true multi-SM DC-class; openXC7 lists Kintex, less-trodden than Artix; pricier |
| CertusPro-NX LFCPNX-100 | 100K LC / LPDDR4/DDR3 HW | Stays in the **prjoxide/nextpnr-nexus** lineage already used for ECP5 (continuity), but **open DDR/DQS support is the weak spot** — likely forces Lattice Radiant IP for the memory controller, breaking "fully open." Watch. |
| Sipeed Tang Mega 138K (GW5AST-138) | 138K LUT / DDR3 / hard PCIe / 12.5G SERDES | Huge hardware-per-dollar, **but** apicula/himbaechel open support is production-ready only for GW1N/GW2A; **GW5A + DDR3 not there yet**. Wildcard to revisit. |

### 6.4 Accessible boards (AliExpress-tier pricing)

| Board | ~Price | Notes |
|---|---|---|
| **QMTECH XC7A200T core board** ⭐ | **~$180** | Bare core + **256 MB DDR3** + 8 MB QSPI, 50 MHz osc, two 2×32 headers. **Open schematics** ([ChinaQMTECH GitHub](https://github.com/ChinaQMTECH/QMTECH_XC7A75T-100T-200T_Core_Board)). No on-board HDMI/SD — add via headers (PMOD/HDMI breakout or QMTECH XME baseboard). Best price/capability for openXC7 + the jcore-soc DDR controller |
| QMTECH XC7A**100**T core board | ~$110–130 | Cheaper fallback: **~63K LUT6** (still ~1.5× an 85F); holds J4 + one modest SM + DDR3. Same toolchain flow — prove the stack here, drop identical RTL onto the 200T for the 2nd SM |
| ALINX AX7A200B | ~$300+ | Full board: **1 GB DDR3**, HDMI, PCIe, SFP+, SD — less DIY, pricier |
| Digilent Nexys Video (A200T) | ~$500+ | Not AliExpress; HDMI **in**+out + SD out of the box — nicest bring-up (HDMI-in can prototype TA capture), worst price |

**256 MB DDR3** (QMTECH) is ample for a unified J4-main + GPU-VRAM map — real DC
total was 26 MB — and the jcore-soc controller's multiport arbiter shares the one
bank between CPU and GPU.

**Buy-time check:** open the QMTECH schematic and note the **exact DDR3 chip**
(Micron MT41J… part) so you can confirm the jcore-soc DDR controller's PHY/timing
maps to it on 7-series — the one detail that turns "board arrived" into "unified
memory working."

### 6.5 Recommendation

For a single-FPGA, unified-DDR **J4 + programmable-SM GPU** with an accept-HLE
layer: target **Artix-7 XC7A200T on openXC7**, reusing the **jcore-soc DDR
controller** (multiport arbiter for the shared bank; port its PHY to the 7-series
DDR primitives), on a **~$180 QMTECH A200T core board** + a cheap HDMI-PMOD
breakout. De-risk cost/flow first on the
**~$120 XC7A100T** variant (identical toolchain), then move the same RTL to the
200T for the second SM. **Kintex-325T** is the same flow if more SMs are needed
later; **CertusPro-NX** and **Tang Mega 138K** are worth tracking but each has an
unresolved open-DDR / open-toolchain gap today. This is the concrete realization
of [no-gpu-decision.md](no-gpu-decision.md)'s "validate on 85F, scale identical
RTL onto bigger silicon" — the bigger silicon is now open-toolchain-reachable.

Sources: [openXC7/nextpnr-xilinx](https://github.com/openXC7/nextpnr-xilinx),
[openXC7 toolchain-installer](https://github.com/openXC7/toolchain-installer),
[QMTECH core-board GitHub](https://github.com/ChinaQMTECH/QMTECH_XC7A75T-100T-200T_Core_Board),
[QMTECH A200T (AliExpress)](https://de.aliexpress.com/item/1005002960622091.html),
[ALINX AX7A200B](https://www.aliexpress.com/item/1005008637225473.html),
[CertusPro-NX datasheet](https://www.farnell.com/datasheets/3983850.pdf),
[prjoxide](https://github.com/gatecat/prjoxide),
[apicula](https://github.com/YosysHQ/apicula),
[Tang Mega 138K Pro](https://wiki.sipeed.com/hardware/en/tang/tang-mega-138k/mega-138k-pro.html).
