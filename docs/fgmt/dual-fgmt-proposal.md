# Proposal: Dual-Core × 2-Way Multithreaded J-Core

**Working title:** J2-MT2x2 — two J2 cores, each with two hardware thread contexts (4 hardware threads total).

> **Scope note.** This document is part of the **J2 line**: `N_TC = 2` on the existing 5-stage in-order J2 pipeline, paired with dual-core MSI coherence. It is not superseded. The J32/OoO line's threading targets are specified separately — [ooo/j32ooo-spec.md §13](../ooo/j32ooo-spec.md) for 2-way FGMT on the out-of-order core, and [ooo/j32lt-spec.md](../ooo/j32lt-spec.md) for 4-way barrel FGMT on the light core. Threading vocabulary for all three is in [glossary §4](../glossary.md).


## 1. Executive summary

J-core is already a clean, BSD-licensed VHDL implementation of the SH-2 ISA with upstream Linux support (`CPU_J2`), an in-tree dual-core configuration (`cpus_two_fpga.vhd`), a CAS.L atomic added specifically for futexes and SMP, a snoop port on the data cache, and an interrupt controller (AIC2) that already takes a `cpuid` generic and exposes an inter-AIC communication bus. The pieces needed for SMP are present but only partially wired; nothing today implements per-core hardware multithreading.

This proposal extends the design along two orthogonal axes:

1. **Promote the existing dual-core configuration from a partially-wired AMP layout to a fully coherent SMP target** that Linux can boot on as two CPUs out of the box.
2. **Add 2-way fine-grained multithreading (FGMT) inside each core**, exposing four hardware threads to software while sharing nearly all combinational logic between thread contexts.

The result is a 4-thread SMP system that should fit comfortably alongside the existing J2 single-core in the same FPGA targets, with the second thread on each core acting as a cheap latency-hiding resource for load-use stalls, instruction-fetch stalls, and (eventually) cache misses, rather than as a second full pipeline.

## 2. Terminology

This document uses **FGMT** (fine-grained multi-threading) throughout: each cycle the front-end picks one of the hardware thread contexts and that thread occupies the pipeline. The project-wide threading vocabulary is defined in [glossary §4](../glossary.md); SMT is not used in this project.

The concrete recommendation for J2 is **2-way FGMT with switch-on-event when one thread is stalled** (cache miss, MAC busy, etc.) — closest in spirit to the MIPS MT ASE (MIPS Technologies, MD00378 rev 1.00, 28 Sept 2005) and Sun UltraSPARC T1 "Niagara" (Kongetira, Aingaran & Olukotun, IEEE Micro 25(2), March–April 2005, pp. 21–29) cores. *This sentence previously cited "the MIPS 34K (Kissell, MIPS Tech 2005)". Both halves were wrong for a pre-2006 citation: the 34K core was announced in February 2006, and Kissell's paper is HiPEAC 2008 — which §12 of this document already cited correctly while §2 did not. The MT ASE specification is the pre-2006 artifact; see [decisions/0009 §Citations that did not survive checking](../decisions/0009-in-order-fgmt-is-the-default-path.md).* Pre-2006 prior art for the underlying barrel-FGMT pattern goes back to the CDC 6600 PPUs (Thornton, AFIPS FJCC 1964, pt. 2 vol. 26, pp. 33–40), Denelcor HEP (Smith, ICPP 1978, pp. 6–8), and Tera MTA (Alverson et al., ICS 1990, pp. 1–6).

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

## 4. Prior art (pre-2006), and post-2006 designs cited as evidence only

**This section was swept post-F, 2026-09-10, and it was the only prior-art section
in the tree not qualified "(pre-2006)".** Task F found it carrying six ungrounded
post-2006 entries in a document that states it is not superseded and is cited
normatively by three others — and, at the end, **a patent granted in 2023 offered
as "useful prior art"**, which inverts [glossary.md §2](../glossary.md) rather than
misapplying it: the rule asks for *expired* patents with priority dates no later
than 2005, and has a companion rule (§2.1 rule 2) whose whole purpose is catching
live claims. The same document applies the correct treatment twice elsewhere — §2's
MIPS-MT correction and §4.1's IBM A2 entry below — so the rule was understood here
and this section was simply never swept. The split below is the fix: what can
ground a mechanism, and what is bibliography.

**Dates in §4.1 were verified at source this session except where the entry says
otherwise.** An entry that says "not dated at source" is telling the truth about
this sweep, not hedging about the design.

### 4.1 Pre-2006 prior art — what may ground a mechanism

- **MIPS MT ASE** — fine-grained MT on a single-issue in-order RISC almost identical in spirit to
  J2. Defines **VPEs** (virtual processing elements: per-thread CP0/privileged state) and **TCs**
  (thread contexts: per-thread GPRs + PC + minimal status), so a 2-VPE part looks to software like
  two MIPS32 CPUs sharing a pipeline and caches, with cache coherence "for free" because the L1 is
  shared. This is the closest published architectural template for what we want on J2, **and the
  TC/VPE split is also this document's pre-2006 antecedent for giving different thread contexts
  different amounts of architectural state** (§5.1). *The pre-2006 artifact is the ASE
  specification — MIPS Technologies **MD00378 rev 1.00, 28 September 2005**, per
  [decisions/0009](../decisions/0009-in-order-fgmt-is-the-default-path.md), which established that
  date; **this sweep could not re-verify rev 1.00, because the copy obtainable is rev 1.12 of 16
  July 2013** (MD00452 likewise, rev 1.02 of 9 September 2013). The date is carried on 0009's
  authority and not on this sweep's.* The **cores** are a different matter and are not prior art:
  the 34K was announced in February **2006**, and the 1004K and interAptiv are later still. Name
  the specification, not the parts.
- **Sun UltraSPARC T1 ("Niagara")** — 4/6/8 cores × 4-way FGMT, single-issue in-order per core,
  with a per-thread register file (one window-set per thread) and a thread scheduler picking among
  ready threads on previous long-latency op, instruction type and LRU. Demonstrates the throughput
  model at scale, and is the second pre-2006 antecedent for per-thread register state. Kongetira,
  Aingaran and Olukotun, *IEEE Micro* 25(2), March–April 2005, pp. 21–29.
- **Barrel FGMT itself** — CDC 6600 peripheral processors (Thornton, AFIPS FJCC 1964), Denelcor
  HEP (Smith, ICPP 1978) and Tera MTA (Alverson et al., ICS 1990), as §2 already cites. The
  waking-on-synchronization-event pattern has its pre-2006 antecedent in the MTA's full/empty bits.
- **C-slow retiming** — Leiserson, Rose and Saxe (1983); Weaver, Markovskiy, Patel and Wawrzynek,
  *Post-Placement C-Slow Retiming for the Xilinx Virtex FPGA*, FPGA '03. The transformation that
  "multiplies" a single-thread pipeline into N interleaved threads by adding C−1 registers in every
  feedback path. Worth evaluating as a tooling shortcut for early prototypes; for an ASIC target
  the explicit hand-designed approach of §5 is preferred.
- **MSI coherence for two cores** over the existing snoop port, with the ring_bus or a dedicated
  coherence bus carrying invalidation traffic. Anything more elaborate (MOESI, directory) is
  unjustified at this scale. Prior art is in [../cache/l2-spec.md §6.1](../cache/l2-spec.md).

### 4.2 Post-2006 designs — evidence only, and **not** usable to ground anything

[glossary.md §2](../glossary.md) permits citing post-2006 work as evidence about the option space.
It does not permit adopting a mechanism on that basis. Every entry here is in the first category.

- **Sun UltraSPARC T2** — Shah et al., IEEE **A-SSCC, November 2007** (verified). Post-cutoff.
- **IBM A2 (Blue Gene/Q, PowerEN)** — in-order, 4-way hardware multithreaded, with a `wrlos`
  ("wait, reservation lost") instruction interacting with reservation-based atomics. Post-2006
  (announced 2010); cited for completeness only. The waking-on-synchronization-event pattern itself
  has pre-2006 prior art in the Tera MTA's full/empty bits (Smith 1990). *This entry already
  carried the correct treatment before the sweep and is unchanged.*
- **XMOS xCORE / XS1** — up to 8 hardware threads per tile, deterministic interleave, no caches.
  Less directly applicable (no coherence) but a good reference for very lean thread-context
  implementation. **Not dated at source this sweep** — the fetch returned a site index rather than
  the XS1 architecture manual. Treated as post-2006, which is the safe direction: if it were
  pre-2006 nothing here would change, because nothing is grounded on it.
- **Strauch's SHP / RTL C-slow work** — arXiv:1508.07139 and arXiv:1807.05446. **Dated from the
  arXiv identifiers this document itself prints** (August 2015 and July 2018); the papers were not
  fetched. The pre-2006 half of C-slow is in §4.1; these are the modern follow-ups. The Berkeley
  "Simple Symmetric Multithreading in Xilinx FPGAs" project (cs252) remains a directly relevant
  cautionary tale on the limits of pure C-slow for a real CPU.
- **FlexPRET** — Zimmer, Broman, Shaver and Lee, **RTAS, April 2014** (verified). A small in-order
  RISC-V with fine-grained MT designed for mixed criticality; a good model for *flexible* thread
  scheduling (hard-real-time thread plus best-effort threads sharing the pipe).
- **BRISKI** — a RISC-V barrel processor targeting kilo-core FPGA overlays; a useful reference
  point for area/Fmax of a pure-barrel approach. **Not dated at source** beyond its own README,
  and it does not need to be for the policy question: it is a RISC-V design, every RISC-V artifact
  cited anywhere in this tree is 2019 or later, and nothing here is grounded on it — so if it were
  somehow pre-2006 no entry above would change.

### 4.3 Removed: a live patent that was cited as prior art

The entry **"Niagara2/T2 register file techniques and selectable register-file blocks (US Patent
11,726,789) — useful prior art for how to size per-thread GPRs when threads don't all need full
ISA-visible state"** is **removed**, and is recorded here rather than deleted silently because a
contributor who saw it once will look for it.

**Verified at source, 2026-09-10:** US11726789B1, *"Selectable Register File Blocks for Hardware
Threads of a Multithreaded Processor"*, assignee **NXP B.V.**, inventor Michael Andrew Fischer,
filed **27 January 2022**, priority **27 January 2022**, granted **15 August 2023**, **in force,
expiring 2042**. Its independent claim covers allocating a register file of B blocks of N registers
across T hardware threads such that each thread gets at least one block and not more than R/N
blocks, supporting T threads with **fewer than T×R registers**.

Three things follow, and the third is the reason this is a two-line fix and not a design problem.

1. **It is not prior art under any reading.** [glossary.md §2](../glossary.md) accepts "expired
   patents with priority dates ≤2005". This one has a 2022 priority and is in force for another
   sixteen years. Citing it as "useful prior art" states the policy backwards.
2. **It is a live claim on the mechanism the sentence recommended**, which is what §2.1 rule 2
   exists to catch: a pre-2006 *structure* (per-thread register state — Niagara, the MIPS TC/VPE
   split, both in §4.1) does not license the purpose-specific *combination* of sub-dividing one
   register file into selectable blocks so that T threads share fewer than T×R registers.
3. **This proposal does not do that, and gains nothing by dropping the citation.** §5.1 gives every
   thread context the **full** sixteen SH-2 GPRs under both of its options — a 32-entry file
   indexed by `TC_ID`, or two parallel 16-entry banks with a select mux. Neither is "fewer than
   T×R", so neither reads on the claim. The citation was decoration on a design that had already
   made the safe choice, which is the most likely way this class of mistake gets made.

If a future revision *does* want to give some thread contexts less architectural state than others,
the pre-2006 grounding is §4.1's MIPS TC/VPE split — a TC carries per-thread GPRs, PC and minimal
status while a VPE carries the full privileged state — and the freedom-to-operate question must be
re-asked at that point, because that is when the design starts approaching the claim.

Neither this section nor [glossary.md §2.1](../glossary.md) constitutes legal advice or a
freedom-to-operate opinion. The removal above is a documentation fix; a professional search is
warranted before RTL commits, as §2.1's closing sentence already says.

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

See [aic/aic2-spec.md §4](../aic/aic2-spec.md) for the formal Tier 1 specification of the FGMT extension to AIC2; this section is the design sketch that motivated it.

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

- Expose per-thread `hard_smp_processor_id()` and a flat-DT property identifying FGMT siblings (similar to PowerPC's `ibm,thread-list`).
- Provide a J2-specific `cpu_topology` so the scheduler treats same-core threads as siblings and picks them only after both cores are busy. (Linux uses `sched_smt_active()` for this regardless of whether the hardware is SMT or FGMT — the kernel API name is historical and does not constrain our hardware choice.)
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
