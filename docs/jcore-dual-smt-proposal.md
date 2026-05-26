# Proposal: Dual-Core × 2-Way Multithreaded J-Core

**Working title:** J2-MT2x2 — two J2 cores, each with two hardware thread contexts (4 hardware threads total).

## 1. Executive summary

J-core is already a clean, BSD-licensed VHDL implementation of the SH-2 ISA with upstream Linux support (`CPU_J2`), an in-tree dual-core configuration (`cpus_two_fpga.vhd`), a CAS.L atomic added specifically for futexes and SMP, a snoop port on the data cache, and an interrupt controller (AIC2) that already takes a `cpuid` generic and exposes an inter-AIC communication bus. The pieces needed for SMP are present but only partially wired; nothing today implements per-core hardware multithreading.

This proposal extends the design along two orthogonal axes:

1. **Promote the existing dual-core configuration from a partially-wired AMP layout to a fully coherent SMP target** that Linux can boot on as two CPUs out of the box.
2. **Add 2-way fine-grained multithreading (FGMT) inside each core**, exposing four hardware threads to software while sharing nearly all combinational logic between thread contexts.

The result is a 4-thread SMP system that should fit comfortably alongside the existing J2 single-core in the same FPGA targets, with the second thread on each core acting as a cheap latency-hiding resource for load-use stalls, instruction-fetch stalls, and (eventually) cache misses, rather than as a second full pipeline.

## 2. Terminology note: SMT vs. FGMT in a single-issue pipeline

Strictly speaking, *simultaneous* multithreading (SMT) means co-issuing instructions from multiple threads in the **same** cycle, which requires a superscalar machine. J2 is a five-stage, in-order, single-issue pipeline; the natural form of hardware multithreading here is either:

- **Fine-grained multithreading (FGMT / "barrel"):** pick a different thread every cycle at the IF or ID boundary.
- **Coarse-grained / switch-on-event:** stay on one thread until a long-latency event (cache miss, MAC stall), then switch.

For consistency with the user-facing request ("dual SMT") this document uses **SMT** loosely. The concrete recommendation is **2-way FGMT with a fallback to switch-on-event when one thread is stalled** — closest in spirit to the MIPS 34K and UltraSPARC T1 cores.

## 3. What already exists in the repository

Before designing anything new, it is worth being explicit about what J-core already provides:

- `core/cpu.vhd`: a single 5-stage SH-2 pipeline composed of `decode`, `datapath`, and `mult`, with a clean per-instance interface (clk, rst, db_o/db_i, inst_o/inst_i, event_o/event_i, cop_o/cop_i, debug_o/debug_i).
- `core/register_file_two_bank.vhd`: a two-bank GPR file with 2 read ports, EX/WB write merging, and three-stage forwarding. This is the natural place to add a thread-id index.
- `cache/dcache.vhd`: a dual-clock-domain D-cache with an explicit **snoop port** (`sa`/`sy` of type `dcache_snoop_io_t`) carrying line address + enable. Invalidation snoop is therefore already a first-class concept in the design.
- `targets/cpus_two_fpga.vhd` (in `jcore-soc`): instantiates two `cpu_core` units (`cpu0`, `cpu1`), a shared 2 KB SRAM with `ram_2rw`, an arbiter (`cpumreg`) that locks RAM access per CPU, and configurations `two_cpus_decode_direct_fpga` / `two_cpus_decode_rom_fpga` / `two_cpus_decode_rodimix_fpga`.
- `components/misc/aic2.vhm`: interrupt controller with `cpuid : integer := 0` generic and an `aic_com_o/aic_com_i` inter-AIC bus (the substrate for IPIs). `cpu1eni` already exists as a software-controlled enable for CPU1.
- `components/ring_bus/`: a generic ring interconnect with example data-bus adapters — a candidate for the multi-master fabric below.
- The J2 ISA additions over SH-2 already include **CAS.L** (compare-and-swap, opcode `0010-nnnn-mmmm-0011`) and **SHAD/SHLD** (backported from SH-3). CAS.L was explicitly added "for futexes and SMP."
- Linux already supports J2 (`CPU_J2`, `arch/sh/mm/cache-j2.c`) and per-CPU cache control is keyed off `hard_smp_processor_id()`, indicating SMP boot is a known target.

In other words: the dual-core hardware exists today as a loosely-coupled AMP system with explicit `cpu1en_sbu` gating; the *coherent SMP* upgrade and the *per-core multithreading* work are largely additive rather than ground-up.

## 4. Prior art

The most relevant designs to study, in roughly increasing distance from J2's micro-architecture, are:

- **MIPS MT ASE (34K, 1004K, interAptiv)** — fine-grained MT on a single-issue in-order RISC almost identical in spirit to J2. Defines **VPEs** (virtual processing elements: per-thread CP0/privileged state) and **TCs** (thread contexts: per-thread GPRs + PC + minimal status). A 34K configured with 2 VPEs looks to software like two MIPS32 CPUs sharing a pipeline and caches, with cache coherence "for free" because the L1 is shared. This is the closest published architectural template for what we want on J2.
- **Sun UltraSPARC T1 ("Niagara") and T2** — multi-core (4/6/8) × 4-way FGMT, single-issue in-order per core. Each core has a per-thread register file (one window-set per thread for T1), a thread scheduler that picks among ready threads based on previous long-latency op, instruction type, and LRU. Demonstrates the throughput model at scale.
- **IBM A2 (Blue Gene/Q, PowerEN)** — in-order, 4-way SMT, with a `wrlos` ("wait, reservation lost") instruction interacting with reservation-based atomics. Useful reference for how to wake threads on synchronization events.
- **XMOS xCORE** — up to 8 hardware threads per tile, deterministic interleave, no caches. Less directly applicable (no coherence) but a good reference for very lean thread context implementation.
- **C-slow retiming** (Leiserson et al., '83; Weaver et al. on Xilinx Virtex; Strauch's SHP / RTL CSR work) — automatic transformation that "multiplies" a single-thread pipeline into N interleaved threads by adding C-1 registers in every feedback path. Worth evaluating as a tooling shortcut for early prototypes, although for an ASIC target the explicit, hand-designed approach below is preferred. The Berkeley "Simple Symmetric Multithreading in Xilinx FPGAs" project (cs252) is a directly relevant cautionary tale on the limits of pure C-slow for a real CPU.
- **FlexPRET** — a small in-order RISC-V with fine-grained MT explicitly designed for mixed-criticality real-time. Good model for *flexible* thread scheduling (hard-real-time thread + best-effort threads sharing the pipe).
- **BRISKI** — RISC-V barrel processor targeting kilo-core FPGA implementations. Good reference point for area/Fmax of a pure-barrel approach.
- **Niagara2/T2 register file techniques** and **selectable register-file blocks** (US Patent 11,726,789) — useful prior art for how to size per-thread GPRs when threads don't all need full ISA-visible state.

For coherence in a 2-core system, the smallest credible protocol is **MSI** (or MESI, if the existing snoop port can carry one additional "exclusive" hint) over the existing snoop interface, with the ring_bus or a dedicated coherence bus carrying invalidation traffic. Anything more elaborate (MOESI, directory) is unjustified at this scale.

## 5. Proposed architecture

### 5.1 Per-core thread context (TC)

Each core gains a parameter `N_TC : natural := 2`. Per thread we duplicate only the SH-2 architectural state that must persist across cycle interleaving:

- **R0–R15** general-purpose registers (16 × 32 bits)
- **PC**, **PR** (procedure register)
- **SR** (status register, including T-bit, S-bit, interrupt mask I3..I0, Q, M)
- **GBR**, **VBR**, **MACH**, **MACL**
- A new **TC_ID** field (1 bit for 2-way)
- A small **per-thread halt/run state** flag, controlled by a new memory-mapped register (analogous to the existing `cpu1en_sbu`).

The 16 GPRs are the dominant storage cost. Two options:

1. **Wider register file with thread-id as MSB of address.** `register_file_two_bank.vhd` becomes a 32-entry file (2 × 16); the decoder prepends the issuing thread's `TC_ID` to the 4-bit register index. Cleanest, but doubles RF read/write power and may require timing closure on the EX/WB forwarding network.
2. **Two parallel 16-entry banks with a thread-id select mux.** Same logical depth as today, with a 1-cycle-late mux on the read path. Lower power, slightly more area, easier timing.

Recommendation: start with option (2) so the existing two-bank forwarding logic is untouched per thread; revisit if synthesis shows option (1) is free on the target FPGA.

The MAC/MULT block (`mult.vhm`) keeps a single MACH/MACL per thread (two 32-bit registers per TC). The multiplier itself is shared and stallable; if thread A occupies MAC for multiple cycles, thread B simply does not issue MAC-class ops during that window — the FGMT scheduler handles it as another reason not to pick A.

### 5.2 Pipeline modifications

Five-stage pipeline (IF / ID / EX / MEM / WB). Changes per stage:

- **IF:** A small **thread scheduler** at the very front of fetch picks one of the N_TC PCs each cycle. Default policy: round-robin between *ready* threads, where a thread is "not ready" if (a) it's halted, (b) the previous instruction of the same thread is still in EX and has a load-use dependency, (c) the I-cache reported a miss for that thread's PC, or (d) the MAC unit is occupied and the next op needs it. Each in-flight instruction carries TC_ID as a sideband signal.
- **ID:** Decoder is unchanged at the opcode level; control-signal records (`reg_ctrl_t`, `func_ctrl_t`, `mac_ctrl_t`, etc.) gain TC_ID. Register read addresses are concatenated with TC_ID (option 1) or used to drive a bank select (option 2). The illegal-slot / delay-slot logic stays per-thread (it only looks at the previous instruction of *the same* thread).
- **EX:** No change to the ALU or shifter — they are stateless. The forwarding network only forwards within the same TC; cross-thread forwarding is impossible by definition (different register namespaces).
- **MEM:** Shared D-cache, requests tagged with TC_ID. The cache is largely thread-agnostic since lines are addressed by physical address; tagging is only needed for routing the response back to the right TC's MEM/WB register.
- **WB:** Writeback addresses index into the per-TC banks.

The 2-cycle load-use stall that hurts single-thread J2 today disappears almost entirely under steady-state 2-thread workload: thread B's instruction naturally fills the slot behind thread A's load. This is the main first-order performance argument for FGMT on this pipeline.

### 5.3 Interrupts and per-thread events

The AIC2 already has a `cpuid` generic. The cleanest extension is to:

1. Promote `cpuid` to `(cpuid : integer; n_tc : natural := 2)` and add per-TC interrupt mask / pending / level registers, addressable by an additional MMIO offset.
2. Carry TC_ID alongside the existing `cpu_event_i_t` so the core knows which thread to interrupt; the IF-stage scheduler then biases toward the interrupted thread on the next available slot.
3. Add an IPI (inter-processor interrupt) MMIO write that targets `(cpu, tc)`; the existing `aic_com` bus is the right substrate.

For Linux, each `(core, tc)` pair maps to a logical CPU in `hard_smp_processor_id()`. With two cores and two TCs that gives logical CPUs 0..3.

### 5.4 Cache and coherence

D-cache today: per-core, with `sa`/`sy` snoop port that invalidates by line address. Proposed:

- **Per-core L1 I-cache and D-cache stay as today**, each shared by both TCs in that core. Coherence between threads on the same core is automatic.
- **Between cores: extend the snoop port from "invalidate only" toward a minimal MSI protocol.** A core that does a write to a line in Shared state issues an invalidation on its `sa` output; the peer core's `sy` input drops the line to Invalid. A core that does a read on a line another core has Modified must trigger a write-back through main memory before refilling. The state bits (2 per line) and the additional snoop traffic can be added to the existing dcache_ccl / dcache_mcl modules without redesigning the cache RAM layout.
- **Coherence interconnect:** for two cores the cheapest option is a point-to-point pair of snoop channels (already present in principle); for any later scaling, the existing `ring_bus` component is the natural fabric and was likely designed with this in mind.
- **I-cache** can remain incoherent with respect to data writes, matching SH-2 conventions (explicit cache flushes are already exposed via the J2 cache control register seen in `arch/sh/mm/cache-j2.c`). Cross-core I-cache invalidation rides on the same snoop fabric on demand.

### 5.5 Atomics and memory ordering

- **CAS.L** is already implemented and already takes `db_lock`. Per-thread, the lock signal needs to be qualified with TC_ID so a CAS by thread A does not block thread B's unrelated access.
- A **store buffer per core** (not per thread) is acceptable; SH-2 has a relaxed-ish memory model historically, and Linux's existing `arch/sh` SMP code already uses appropriate barriers around CAS-based atomics. No new ISA additions should be needed for the dual-core × 2-TC case.

## 6. Implementation phases

Estimating absolute calendar effort would be irresponsible without knowing your collaborators and target FPGA, but the dependency ordering is clear:

**Phase 0 — Baseline (no new RTL).** Build `two_cpus_decode_direct_fpga`, boot Linux SMP on it on the existing Turtle/Mimas-class target, characterize: Fmax, LUT/FF count per core, and instructions-per-cycle on a SMP benchmark. This is essentially due diligence on the existing dual-core path and may surface issues that should be fixed before adding MT complexity.

**Phase 1 — MSI coherence between cores.** Extend `dcache_ccl` / `dcache_mcl` with per-line state bits; widen the snoop port from "invalidate" to {invalidate, request-shared, request-modified}. Add a tiny directory or pairwise snoop network for two cores. Verify with hand-written tests in `cache/tests/` and with a Linux ASMP→SMP transition (drop the explicit cache flush dance in `cache-j2.c` once coherence handles it).

**Phase 2 — Single-core 2-TC prototype.** In a branch of `core/`, parameterize `cpu.vhd` and `datapath.vhm` by `N_TC`, duplicate the architectural state in `register_file_two_bank.vhd`, and add a round-robin thread scheduler at IF. Run the existing test suite (`tests/`, `testrom/tests/`) twice: once with one TC active (must be bit-identical to current J2), once with two TCs running independent test programs. Measure: load-use stall reduction, MAC contention frequency, Fmax delta versus baseline.

**Phase 3 — Dual-core × 2-TC integration.** Combine Phases 1 and 2 in `cpus_two_fpga.vhd` (or a new `cpus_two_mt2_fpga.vhd`). Extend `aic2` and `cpumreg` for per-TC interrupts and per-TC enable/halt. Linux boots as a 4-CPU system.

**Phase 4 — Software bring-up and characterization.** A small Linux patchset to expose topology (`cpu_to_core_id`, `cpu_to_smt_id`) so the scheduler treats same-core TCs as siblings. Benchmarks: kernbench, hackbench, a memory-bound and a MAC-heavy synthetic, plus whatever real workload motivates this (e.g. the USB Wireguard VPN dongle mentioned in the LKML thread).

**Phase 5 (stretch) — Architectural extensions.** Optional and explicitly out of scope for the initial deliverable: per-thread priorities for soft-real-time use à la FlexPRET; a "thread halt on cache miss" mode for energy savings; SHP-style thread bypass/reorder if the round-robin scheduler proves limiting.

## 7. Software implications

The J2 Linux port already assumes SMP-capable hardware; the additional work for FGMT is mostly making Linux's scheduler topology-aware:

- Expose per-thread `hard_smp_processor_id()` and a flat-DT property identifying SMT siblings (similar to PowerPC's `ibm,thread-list`).
- Provide a J2-specific `cpu_topology` so `sched_smt_active()` returns true and same-core threads are picked only after both cores are busy.
- The existing J2 cache-flush path (`cache-j2.c`) keys off `hard_smp_processor_id() * j2_ccr_cpu_offset` — under the new model this should switch to a per-*core* offset, not per-thread, since both threads on a core share the cache.
- Userspace: musl already supports `sh2eb-linux-muslfdpic`; no changes expected. GCC's `-mj2` is already upstream. CAS.L lowering for futexes already exists.

If MMU work is in flight (the SH-3-flavoured J32) the proposal here is orthogonal — both can proceed in parallel, and a multi-threaded J32 is the natural next step beyond Phase 5.

## 8. Verification strategy

- **RTL regression:** every existing test in `cache/tests/`, `tests/`, `testrom/tests/`, and `sim/tests/` must pass with `N_TC = 1` (proves we haven't regressed J2). With `N_TC = 2` the same tests run twice as concurrent threads and must each individually pass.
- **New tests:** a directed test pack for the thread scheduler (fairness, starvation on stall, MAC contention), and a coherence test pack for MSI transitions (write-write race, read-modify-write, false sharing, CAS contention). Reuse the `cache/tests/dctest*_*` style.
- **Linux LTP** subset for SMP correctness, plus `stress-ng --futex` and a hand-written CAS bouncer to exercise the atomic path.
- **Formal:** the existing CAS.L lock signal interactions are the highest-risk piece; consider a small SymbiYosys property set on the lock arbitration and on the MSI state machine.
- **Continuous benchmarking:** track Fmax, LUT/FF/BRAM, and CoreMark-per-thread across phases; refuse to merge a phase that loses more than ~10% Fmax without an explicit justification, since J2's commercial value rests partly on its Fmax/area sweet spot.

## 9. Open questions and risks

- **Is 2-way FGMT really worth it on a 5-stage pipeline?** A 5-stage in-order with limited stalls might gain less from FGMT than the deeper MIPS 34K pipeline did. Phase 1 baseline IPC measurements should be a go/no-go gate for Phase 2.
- **Snoop port semantics.** The existing `dcache_snoop_io_t` only carries line address + enable. Extending it to a real coherence protocol may require dropping the abstraction and reworking the dcache state machine in `dcache_ccl.vhm`. The risk is contained but real.
- **MAC stalls dominating.** SH-2 MAC instructions can take multiple cycles; under FGMT this becomes a structural hazard between threads. Measurement-driven: if MAC contention is rare in target workloads, fine; if not, consider a second lightweight MAC for the second TC.
- **Debug interface scope.** The existing `debug_o/debug_i` ports assume one GDB connection per CPU. Per-TC debug (each TC visible as a separate target) is desirable but not strictly required for Phase 3; the `cpus_two_fpga.vhd` already notes `TODO: Add separate debug ports for cpu1`, so it's an existing debt to pay back.
- **Power.** FGMT increases register-file activity; on FPGA targets this is largely free, but on the ASIC roadmap (sky130 was mentioned in 2023 LKML threads) this matters. Phase 2 should include power estimation.
- **Coordination with upstream J-core.** The repository's most recent visible activity is from 2020. A proposal of this scope should be coordinated with Jeff Dionne / Rich Felker / Rob Landley early; otherwise the changes risk diverging from the line that drives the J32 / next-ASIC work.

## 10. Recommended next step

A short feasibility memo from Phase 0 — actual Fmax, LUT, and IPC numbers from the existing `two_cpus_decode_direct_fpga` configuration on a Mimas-class board, plus a Linux SMP boot trace — would let the rest of this plan be costed properly. Without those numbers the rest is design-on-paper.

## References

- J-core project site: `https://j-core.org/` ; repos at `https://github.com/j-core/`.
- Linux J2 patches: Rich Felker, "sh: add support for J-Core J2 processor" (2016).
- LKML "Re: remove arch/sh" thread (Jan 2023): D. Jeff Dionne confirms J2 2-core SMP in hardware and ASIC.
- Kissell, K., "MIPS MT: A Multithreaded RISC Architecture for Embedded Real-Time Processing" (Springer LNCS, 2008).
- MIPS Technologies, "MIPS® MT Principles of Operation" (MD00452).
- Kongetira, P. et al., "Niagara: A 32-Way Multithreaded Sparc Processor" (IEEE Micro, 2005).
- Shah, M. et al., "UltraSPARC T2: A Highly-Threaded, Power-Efficient, SPARC SoC" (A-SSCC, 2007).
- Leiserson, C., Rose, F., Saxe, J., "Optimizing Synchronous Circuitry by Retiming" (1983).
- Weaver, N., Markovskiy, Y., Patel, Y., Wawrzynek, J., "Post-Placement C-Slow Retiming for the Xilinx Virtex FPGA" (FPGA '03).
- Strauch, T., "Timing Driven C-Slow Retiming on RTL for MultiCores on FPGAs" (arXiv:1807.05446).
- Strauch, T., "Using System Hyper Pipelining (SHP) to Improve the Performance of a CGRA Mapped on an FPGA" (arXiv:1508.07139).
- Zimmer, M. et al., "FlexPRET: A Processor Platform for Mixed-Criticality Systems" (RTAS 2014).
