# ULX3S J-Core SoC — Component Inventory & Build Order

**Status:** High-level decomposition (brainstorm output)
**Date:** 2026-06-01
**Context:** The J2 CPU now synthesizes for ECP5 (yosys+ghdl, abc9). The
measured clock, and the per-variant figures that matter more than the J2 one,
are [platform-baseline.md §3](platform-baseline.md) — this line previously
carried a bare `~42 MHz` of its own.
This doc inventories everything needed to build a full SoC on the ULX3S
(LFE5U-85F) and proposes an incremental build order. Companion to
[`jcore-ulx3s-service-plan.md`](jcore-ulx3s-service-plan.md).

> **Scope note — no-MMU core.** This J2 core is SH-2 / no-MMU. The realistic SoC
> endpoint is **bare-metal / nommu uClinux** (the canonical J2 OS), *not* the
> MMU-based Debian in the service plan (which assumes a J32+MMU core — a separate
> core effort). The service plan's networking/observability still apply later.

## Target SoC block view

```
   25 MHz osc ─► [clkgen EHXPLLL] ─► clk_cpu / clk_mem        [reset gen]
                                         │
   ┌─────────────────────────────────────────────────────────────────┐
   │  J2 CPU (ECP5-synthesizable)                                      │
   │     │ instr_bus / data_bus (J-core internal bus)                  │
   │  [bootmem BRAM] ─ [I/D cache + RAM/mem mux] ─► [SDRAM ctrl] ─► 32MB SDR SDRAM
   │     │                                                             │
   │  [peripheral bus mux]                                             │
   │     ├─ UART (uartlite) ──► FTDI / ESP32 console                   │
   │     ├─ AIC (interrupt controller)                                 │
   │     ├─ timer                                                      │
   │     ├─ GPIO (LEDs / buttons)                                      │
   │     ├─ SPI (spi2/3) ──► microSD                                   │
   │     └─ EMAC ──► RMII glue ──► LAN8720 (Ethernet)                  │
   └─────────────────────────────────────────────────────────────────┘
   board glue: pad_ring + .lpf pin constraints + device tree (board.dts) + bootrom
```

## Component inventory

Status legend: ✅ ready/portable · ⚠️ port-and-verify (generic VHDL, Xilinx tail only) · ❌ net-new for ECP5/ULX3S · ⛔ not needed.

| Component | Role | Status |
|---|---|---|
| J2 CPU | core | ✅ done (ECP5 synth + timing gate) |
| Internal bus + `bus_mux_*` | interconnect | ✅ generic VHDL |
| `memory_tech_lib` (inferred) | BRAM/ROM | ✅ infers to ECP5 EBR |
| `cpu/cache`, `ddr_ram_mux` | I/D cache + mem arbitration | ⚠️ logic portable; only DDR-PHY tail is Xilinx |
| `memory_fpga` / bootmem | BRAM boot memory | ✅ portable |
| `uartlite` | UART console | ✅ portable |
| `misc/aic`, `aic2` | interrupt controller | ⚠️ verify |
| `misc/gpio`, `pio` | GPIO | ⚠️ verify |
| `misc/spi2`, `spi3` | SD over SPI | ⚠️ verify |
| `emac` | Ethernet MAC | ⚠️ MAC portable; RMII glue net-new |
| `dma` | DMA engine | ⚠️ portable; optional early |
| `clk` (`clkin25_*`) | PLL | ❌ net-new ECP5 `EHXPLLL` clkgen |
| `lib/hwutils/*_fpga` | BUFG / IDDR / ODDR | ❌ ECP5 prims or inference |
| `ddr` / `ddr2` | memory controller | ❌ net-new SDR-SDRAM controller (ULX3S is SDR) |
| `fpga_reboot` (ICAP) | bitstream reboot | ❌ ECP5 equiv or drop |
| board `soc.vhd`/`devices.vhd`/`pad_ring.vhd` | top + peripheral block | ❌ new ULX3S target (soc_gen design.edn, or hand-written top) |
| constraints | pinout | ❌ `.ucf` → ULX3S `.lpf` |
| `boot/` bootrom | first-stage boot | ⚠️ exists (sh2-elf); needs ULX3S `board.h`/`dts` + SDRAM init |
| `ring_bus`, `gps_if2` | ring interconnect / GNSS | ⛔ not needed |

**Three real net-new pieces:** ECP5 **clkgen** (small) · **SDR-SDRAM controller**
(big — write one or port an open core, e.g. LiteDRAM or a known ULX3S SDR
controller) · **ULX3S board target** (top + `.lpf` + device tree). Everything
else is mostly port-and-verify of existing VHDL.

## Build order (each milestone independently demonstrable)

| Milestone | Adds | Deliverable |
|---|---|---|
| **M0 — BRAM + UART** | clkgen + reset + CPU + bootmem(BRAM) + uartlite + minimal bus + `.lpf` | SoC boots on ULX3S to a serial banner; no SDRAM/cache/peripherals |
| **M1 — SDRAM** | SDR-SDRAM controller + cache/`ddr_ram_mux` wiring | runs real code from 32 MB main RAM |
| **M2 — Core peripherals** | AIC + timer + GPIO | interrupt-driven bare-metal |
| **M3 — Storage/boot** | SD-over-SPI and/or QSPI-flash boot + device tree | load a payload from storage |
| **M4 — Ethernet** | EMAC + RMII glue (LAN8720) | networking |
| **M5 — uClinux (no-MMU)** | full bring-up | nommu uClinux shell on J2 |

## Decisions

- **ASIC portability is a goal** (open-source fab, e.g. SkyWater 130 via
  OpenLane/OpenROAD — consistent with J-core being silicon-proven). Consequences:
  - **LiteX is excluded for core SoC components.** Its high-value cores
    (litedram DRAM PHY, PLLs, SerDes, FPGA I/O primitives) are FPGA-specific and
    don't map to an open PDK. The SoC stays **portable VHDL** with jcore's
    tech-abstraction (`memory_tech_lib` inferred/tech/sim, ASIC vs FPGA build
    split). LiteX may still be used as throwaway FPGA-only bring-up scaffolding
    if it never locks us in — but not on the silicon path.
  - **M0 board top = hand-written VHDL** (toolchain-free; ASIC-neutral).
  - **M1 SDRAM = ASIC-portable SDR controller** written/ported as VHDL, not litedram.
  - **SoC generator = Go `soc_gen`** (`jcore-soc/tools/socgen`, emitting VHDL) —
    now canonical, consistent with the completed `cpugen` Clojure→Go migration;
    not LiteX. Adopted for the ULX3S SoC at ~M2 when peripherals justify it.
- **OS trajectory:** bare-metal → nommu uClinux on J2 (MMU Debian needs a J32 core).

## Open decisions

- **SDRAM controller (M1):** write a minimal ASIC-portable SDR controller vs
  port an existing open VHDL/Verilog SDR core that can go through OpenLane.
- **ECP5 vs ASIC clocking:** EHXPLLL for FPGA; the clkgen needs a tech-abstracted
  interface so an ASIC PLL/clock tree can swap in.
