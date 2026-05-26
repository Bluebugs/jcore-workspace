# Plan: J2-MT2x2 + Pipeline Deepening

**Companion document to:** `jcore-dual-smt-proposal.md`
**Status:** draft for review

This is the execution plan that turns the proposal into a sequence of decidable work items. The proposal answered *should we and why*; this document answers *how, in what order, and how do we know each step worked*.

## 1. Purpose and scope

Deliver a J2-based FPGA-targeted SoC with:

- two cores, cache-coherent, exposing four hardware threads (2 cores × 2-way fine-grained multithreading);
- a deeper pipeline than the current 5-stage where deepening pays back measured Fmax;
- a clean Linux SMP boot on the resulting hardware, with topology-aware scheduling.

Out of scope (explicit non-goals for this plan):

- The J32 MMU-enabled successor. Anything here should not block J32, but J32 work proceeds on its own track.
- Superscalar / out-of-order execution. The design stays single-issue in-order per thread.
- New ISA extensions beyond what's already in J2 (CAS.L, SHAD, SHLD).
- New cache hierarchy beyond L1; no L2, no shared TLB.
- ASIC tape-out. The target is FPGA throughout; ASIC remains a downstream decision.

## 2. Success metrics

The work is "done" when, on a single defined FPGA target (see §9):

1. The 4-thread SoC boots Linux with all four logical CPUs visible to `/proc/cpuinfo` and `cpu_sibling_mask` correctly reflecting the same-core thread pairing.
2. Aggregate CoreMark throughput across four threads is at least **2.5× single-thread CoreMark on the current J2 baseline** at the same target Fmax. (Not 4× — FGMT under contention, cache pressure, and bus contention will not give linear scaling. 2.5× is the credible "this was worth doing" threshold; 3× is the stretch.)
3. Single-thread CoreMark on one of the four threads (other three idle) is **within 5%** of the single-thread CoreMark on the same revision configured with `N_TC = 1`. (i.e., we have not made the single-thread case meaningfully worse.)
4. Fmax on the multi-stage deeper pipeline is **at least 15% above** the current 5-stage Fmax on the same target, with a 25% stretch.
5. The full regression suite (existing VHDL TBs plus new ones from this work) passes in CI on every merged commit.
6. `stress-ng --futex`, `stress-ng --cache`, and an LTP SMP subset run for 24 hours without correctness failures.

Metrics 2, 3, and 4 are go/no-go gates. Failing any of them means going back to the prior phase, not pushing on.

## 3. Decisions needed up front

These should be resolved before Phase 0 starts; each blocks something downstream.

- **D1. Target FPGA board.** Mimas v2 (Spartan-6) is the cheapest existing build target but probably too small for 2×2 plus caches plus DDR. The Turtle 1v1 board is referenced in the existing `make turtle_1v1` flow. A K7-class part is more realistic for the final 4-thread bring-up; an Artix-7 dev board (e.g. Nexys A7) is a reasonable middle ground. Decision drives synthesis flow (ISE vs Vivado) and toolchain assumptions throughout.
- **D2. Synthesis toolchain.** The existing repo assumes Xilinx ISE; that's effectively dead and bounds us to old parts. Migrating to Vivado is part of D1 — list as a separate work item if the chosen board needs it.
- **D3. Open-source vs vendor flow.** GHDL + Yosys (with the GHDL plugin) + nextpnr-xilinx is viable for Spartan-6 / Series-7 today. Vivado is faster to converge on timing. Pick one for the plan-of-record; the other can stay as a parallel CI track.
- **D4. Upstream coordination.** Reach out to Jeff Dionne / Rich Felker / Rob Landley before Phase 1 to confirm none of this collides with the J32 work or with an unreleased MMU branch. Risk of duplicate or conflicting work is high if we don't.
- **D5. Branch model.** A long-lived `mt2x2` branch on a personal fork of `jcore-cpu` and `jcore-soc`, rebased onto upstream `master` weekly. All phases land as PRs against this branch; nothing goes upstream until Phase 4 ships.
- **D6. Verification framework.** The existing repo uses hand-written VHDL test benches (`*_tap.vhd`) plus C-driven tests in `testrom/`. Adding cocotb for the new MT-specific tests is a productivity win but adds a dependency. Decide whether to introduce cocotb in Phase 0 or stick with the existing flow.

## 4. Work breakdown

Phases are sequential by default; explicit parallel tracks are called out where they exist.

### Phase 0 — Baseline & instrumentation

**Goal:** know what we are starting from. No new RTL changes the CPU.

Deliverables:
- Synth & P&R reports for `cpu_decode_direct_fpga` (single-core) on the chosen target: LUT/FF/BRAM/DSP, Fmax, post-route slack on the worst 10 paths.
- Same for `two_cpus_decode_direct_fpga` (existing dual-core AMP).
- A Linux boot trace on both, with `dmesg`, `/proc/cpuinfo`, and a kernbench / CoreMark run.
- A short "where is the critical path?" memo identifying the top 3 timing-limiting paths in EX, MEM, and the decode network. This memo drives Phase 1.5.
- CI infrastructure: a job that runs `make turtle_1v1` (or chosen target), the VHDL TB regression, and an opcode-level simulator regression on every commit.

Exit criteria:
- Two Fmax numbers (single-core, dual-core) measured and reproducible.
- One critical-path memo committed to the repo.
- CI green on `master` with no functional changes.

Risks specific to Phase 0:
- Old ISE flow may not converge on a modern board → forces D1/D2 earlier than planned.
- Test infrastructure may have bit-rotted → expect to spend non-trivial time on this; it's the unglamorous part of any open-hardware project and the reason most forks die.

### Phase 1 — MSI cache coherence between cores

**Goal:** the existing `cpus_two_fpga.vhd` configuration becomes truly SMP rather than AMP-with-shared-SRAM.

Deliverables:
- Extension of `dcache_snoop_io_t` from `{address, enable}` to carry a small command field (invalidate / request-shared / request-modified / writeback-ack).
- Per-line state bits (2 bits → M/S/I, or 3 bits if we go MESI) added to the dcache tag array.
- Updates to `dcache_ccl.vhm` and `dcache_mcl.vhm` to drive the MSI state machine on local CPU accesses and on incoming snoop requests.
- A pairwise snoop interconnect between the two D-caches. For two cores, this is point-to-point and does not need the ring_bus yet.
- New testbench `cache/tests/dctest_mesi_*` covering: clean-shared read, write-invalidate, read-after-modified, false sharing, CAS contention, dirty eviction during snoop.
- Linux patch: drop the manual cache-flush dance in `arch/sh/mm/cache-j2.c` once coherence makes it unnecessary, or leave the path but verify it's never hit.

Exit criteria:
- All MSI directed tests pass.
- Linux SMP boots and runs LTP `pthread_*` and `futex_*` overnight without failures.
- Fmax on the coherent dual-core within 5% of the baseline dual-core. (Coherence shouldn't hurt the critical path; if it does, fix before moving on.)

### Phase 1.5 — Pipeline deepening (retiming track + targeted splits)

**Goal:** raise Fmax with the minimum architectural disruption.

This phase has two sub-tracks that can be done in parallel by different people, or sequentially by one:

**1.5a. Pure retiming (no architectural change).**
- Enable synthesis retiming options on the existing 5-stage.
- Hand-place a few register-balancing flops where the tool can't see across module boundaries (notably between `decode` and `datapath`, and between `datapath` and `dcache`).
- Re-measure Fmax. Expectation: 10–20% gain.
- Exit: Fmax gain quantified; single-thread IPC unchanged (no architectural changes ⇒ this should be tautologically true, but check anyway because retiming bugs are real).

**1.5b. Split MEM stage into MEM1/MEM2.**
- Address generation moves to MEM1; D-cache RAM read + writeback alignment moves to MEM2.
- Load-use latency increases by one cycle; the decoder's hazard detection needs to know.
- New forwarding path from MEM2 → EX is needed for back-to-back load → use.
- New directed tests: every existing load/store test must still pass; new tests for the worsened load-use case.

Sequencing inside Phase 1.5: do 1.5a first (free), measure, *then* decide if 1.5b is worth the IPC cost. If 1.5a alone gets us close to the 15% Fmax target, defer 1.5b until after Phase 2 (when FGMT can hide its cost).

Exit criteria for Phase 1.5:
- Fmax target hit (≥15% above 5-stage baseline).
- Single-thread CoreMark on the deeper pipeline within 10% of single-thread CoreMark on the 5-stage baseline. (We expect some IPC loss; we want to bound it.)
- All regression tests pass.

Explicit do-not-do in this phase:
- Do not split IF or EX yet. Those interact with the thread-context work in Phase 2 and should be done after FGMT is in.
- Do not pipeline the multiplier deeper yet. Same reason.

### Phase 2 — Single-core 2-TC prototype

**Goal:** introduce hardware multithreading on one core, with the second core temporarily disabled, on a branch of the post-Phase-1.5 pipeline.

Deliverables:
- `cpu.vhd` and `datapath.vhm` parameterized by `N_TC : natural := 2`.
- `register_file_two_bank.vhd` extended with thread-id select on read/write paths. Implementation choice (wide RF vs parallel banks) per §5.1 of the proposal — bias toward parallel banks for cleaner forwarding.
- Per-TC duplication of PC, SR, GBR, VBR, PR, MACH, MACL, T-bit, S-bit, etc. — everything that must persist across cycle interleaving.
- Thread scheduler module at IF: round-robin over ready threads, with a TC marked not-ready if (a) halted, (b) prior instruction in EX has a load-use hazard, (c) I-cache miss outstanding, (d) MAC unit busy and next op is MAC.
- TC_ID sideband signal carried through all pipeline-control records (`reg_ctrl_t`, `func_ctrl_t`, `mac_ctrl_t`, etc.).
- A small MMIO halt/run register per TC, modeled on the existing `cpu1en_sbu` mechanism.
- New directed tests: two TCs running independent test programs, the same test program twice with TC_ID-keyed memory regions, a "thread starvation" test (one TC in a tight loop, ensure the other still progresses).

Exit criteria:
- With `N_TC = 1` at build time the single-thread CoreMark is bit-identical to Phase 1.5 results (proves no regression on the single-thread path).
- With `N_TC = 2`, both threads pass the full functional regression individually.
- Aggregate CoreMark on 2 threads ≥ 1.4× single-thread CoreMark on the same revision. (Lower than 2× because we're sharing one pipeline; 1.4× is the published ballpark for 2-way FGMT on a 5-stage-class pipeline with load-use stalls.)
- Fmax within 10% of the Phase 1.5 single-core number.

### Phase 3 — Dual-core × 2-TC integration

**Goal:** combine Phase 1 (coherence) and Phase 2 (FGMT) into the full 4-thread SoC.

Deliverables:
- New target `cpus_two_mt2_fpga.vhd` (or extension of the existing `cpus_two_fpga.vhd`) instantiating two MT-capable `cpu_core`s.
- `aic2` extended for per-TC interrupt routing: pending/mask/level registers per `(cpuid, tc)` pair; the existing `aic_com` bus carries per-TC IPI vectors.
- `cpumreg` extended for per-TC halt/run (4 enable bits instead of 1).
- Updated `cpu_core_pkg` and bus muxing to plumb TC_ID through to the data-bus / instr-bus interfaces where needed (mostly for the debug interface — see Phase 3 stretch).
- Linux device-tree updates: 4 CPU nodes, with `cpu-map` cluster/core/thread topology.
- Bring-up bitstream that boots U-Boot and Linux.

Exit criteria:
- All four logical CPUs come up under Linux. `/proc/cpuinfo` shows them. `cpu_sibling_mask` correctly identifies same-core thread pairs.
- LTP SMP run passes overnight.
- All Phase 1 and Phase 2 tests still pass.
- The aggregate-throughput success metric (§2.2) is met.

Stretch within Phase 3:
- Per-TC GDB debug. The existing repo notes `TODO: Add separate debug ports for cpu1` and that debt grows here. If the bring-up timeline is healthy, pay it down; if not, defer to Phase 5.

### Phase 4 — Software bring-up and characterization

**Goal:** make the hardware actually useful by ensuring the OS treats it correctly and by characterizing it on real workloads.

Deliverables:
- A small `arch/sh/kernel/topology.c`-style addition surfacing core / thread topology to the scheduler.
- `sched_smt_active()` returns true; CFS prefers different cores before same-core threads.
- `arch/sh/mm/cache-j2.c` updates to key off core-id rather than thread-id for cache flushes.
- Benchmark report: CoreMark (single-thread, all-threads, threads-per-core breakdown), kernbench, hackbench, a memory-bound workload (STREAM or a hand-rolled equivalent that fits in our cache), a MAC-heavy synthetic, and one "real" workload (suggest: the J2 USB Wireguard dongle workload mentioned in 2023 LKML if accessible, or otherwise an iperf3 + ethernet stress).
- A short paper or blog post documenting the design, results, and tradeoffs.

Exit criteria:
- All §2 success metrics confirmed on a clean build of the final SoC bitstream.
- Linux patches in a state suitable for submitting to `linux-sh@`.
- RTL changes in a state suitable for upstreaming to `j-core/jcore-cpu` and `j-core/jcore-soc`, contingent on D4.

### Phase 5 — Stretch / follow-on

Not in the main plan, but worth keeping a backlog of:

- Per-TC priorities and a FlexPRET-style soft-real-time mode.
- "Halt thread on cache miss" energy mode.
- Splitting IF or EX further now that FGMT can hide the cost.
- C-slowing the divider or the multiplier as a localized Fmax win.
- 4-way FGMT per core (would push the per-thread context cost up substantially and would want a deeper pipeline to justify).
- A 2-bit BHT branch predictor in BRAM, if the deeper IF stage makes delay-slots insufficient.

## 5. Dependencies and critical path

```
            Phase 0
               │
       ┌───────┴───────┐
       ▼               ▼
   Phase 1         Phase 1.5a (retiming)
       │               │
       │               ▼
       │           Phase 1.5b (MEM split)  ← optional, can be deferred
       │               │
       └───────┬───────┘
               ▼
            Phase 2
               │
               ▼
            Phase 3
               │
               ▼
            Phase 4
```

Phase 0 blocks everything. Phase 1 and Phase 1.5a are independent and can be done in parallel by different people. Phase 1.5b should be done after both 1 and 1.5a are clean. Phase 2 needs Phase 1.5 done (deeper pipeline is what FGMT is hiding the cost of). Phase 3 needs Phase 1 (coherence) and Phase 2 (MT) both done. Phase 4 is sequential after Phase 3.

The critical path is therefore: **0 → 1 → 1.5b → 2 → 3 → 4**. Six sequential phases. If 1.5b is deferred, it's one shorter; if 1.5a doesn't deliver 15% Fmax, 1.5b is mandatory and on the critical path.

## 6. Verification and CI plan

Three layers, each with explicit ownership of failure modes:

- **Unit testbenches (VHDL, per block).** The existing `cache/tests/`, `tests/`, `sim/tests/`, and `testrom/tests/` patterns. New tests added in each phase land here.
- **Full-system simulation.** The existing `sim/` flow runs the CPU against a memory model. Extend to multi-CPU and multi-TC. Should run as part of CI.
- **Bitstream regression on real hardware.** A nightly job that builds the bitstream, programs the FPGA, boots Linux, and runs a fixed subset of LTP plus CoreMark. Catches things sim won't (timing closure, clock-domain-crossing bugs, real DDR behavior).

CI infrastructure should be set up in Phase 0 and grow over time. Don't try to build the perfect CI pipeline before any RTL changes — get something minimal running, then expand it.

Coverage targets per phase:
- Phase 1: 100% of MSI state transitions exercised by at least one test.
- Phase 2: every entry in the thread-scheduler ready/not-ready truth table exercised; every TC_ID-tagged signal verified to be respected by every consumer.
- Phase 3: a hand-written "cross-thread, cross-core, contended CAS" stress test that runs in sim and on hardware.

## 7. Risk register

| ID | Risk | Likelihood | Impact | Mitigation / trigger |
|---|---|---|---|---|
| R1 | Phase 0 reveals the existing dual-core path is bit-rotted and doesn't boot Linux | medium | high | Budget extra time in Phase 0; reach out to upstream early (D4). Trigger: Phase 0 takes >2× expected effort → re-scope the plan around fixing the baseline first. |
| R2 | Toolchain (ISE) doesn't support the chosen target FPGA | high if D1 picks a modern part | high | Decide D1 + D2 together; pick a Vivado-supported target if there's any doubt. |
| R3 | Phase 1.5a retiming doesn't yield ≥15% Fmax | medium | medium | Means Phase 1.5b is mandatory, extending the critical path. Trigger: re-baseline Phase 2 IPC expectations accordingly. |
| R4 | Snoop-port extension breaks dcache timing closure | medium | high | Do the MSI state machine on the CPU-clock domain; keep the snoop fabric narrow. Trigger: prototype the snoop extension in isolation before integrating. |
| R5 | FGMT IPC gain too small to justify the area | low-medium | high | This is exactly what the Phase 2 exit criterion (1.4× aggregate) gates on. Trigger: if the aggregate gain is <1.2×, stop and reconsider; the design may benefit more from a wider single-thread pipeline than from FGMT. |
| R6 | Upstream J-core has incompatible plans we don't know about | medium | high | D4 — reach out before Phase 1. Trigger: if upstream has an unreleased MMU branch that conflicts, align with it before going deeper. |
| R7 | Linux arch/sh removed before we ship | low | catastrophic | Track the `linux-sh` list; engage early. The 2023 LKML thread suggests arch/sh's survival is tied to active J-core users. |
| R8 | Effort blows out beyond solo / small-team feasibility | medium | high | Phase 0 ends with a re-estimate based on measured difficulty. The whole plan is constructed so that stopping after Phase 1 (coherent SMP) is still a usable deliverable, and stopping after Phase 1.5a (retimed SMP) is too. |
| R9 | Debug interface debt makes Phase 3 bring-up impossible to diagnose | medium | medium | Do at least minimal per-TC GDB support in Phase 3 even if it's ugly. |
| R10 | DDR / memory bandwidth becomes the bottleneck before FGMT helps | medium | medium | Phase 0's critical-path memo should include a memory-bandwidth check. If we're already memory-bound on single-thread, FGMT won't help much. Trigger: re-evaluate Phase 2 if Phase 0 shows the dcache miss rate is the binding constraint. |

## 8. Tooling and infrastructure requirements

To be set up in or before Phase 0:

- A workstation or VM with enough RAM (16 GB+ realistic, 32 GB comfortable) for Vivado synthesis of the dual-core SoC.
- The chosen FPGA board (D1), plus a USB-UART cable and either an SDcard slot or QSPI-flash programming.
- A reproducible build environment, ideally a Nix flake or a Dockerfile pinning ISE/Vivado + GHDL + dtc + the SH cross-toolchain (`sh2eb-linux-muslfdpic`).
- The existing `jcore-cpu`, `jcore-soc`, `jcore-jx` repos in a working state on a personal fork.
- A musl-based SH cross-toolchain.
- A Linux kernel tree with the J2 patches applied, configured for `j2_defconfig`.
- A CI runner (a small server, a Hetzner box, or GitHub Actions if the synth flow fits in the time/memory budget) running the regression suite per commit.

Software dependencies to install: GHDL (with the `--std=08` flag for the existing VHDL), Yosys with the GHDL plugin (if going open-source), nextpnr-xilinx, Vivado (if going vendor), the SH binutils + GCC + musl, busybox for initramfs, U-Boot for the chosen board.

## 9. Open questions and decisions log

This section is to be appended-to during execution. Initial entries:

- **Q1.** D1 / D2 / D3 / D4 / D5 / D6 from §3. All open.
- **Q2.** Should the J2-MT2x2 design preserve the SH-2 architectural concept of one PC + one SR per processor, with TCs visible only via a new MMIO interface (the MIPS MT "TC" model)? Or should it expose two SH-2 processors per core with no new architectural concept (the more conservative model)? The latter is easier for Linux but loses the ability to do TC-level scheduling primitives like `FORK`/`YIELD`. Recommendation: start with the latter (each TC looks like a full SH-2), revisit in Phase 5 if there's a use case for the former.
- **Q3.** Is there an existing big-endian-only constraint we need to respect? The Jan 2023 LKML thread notes J2 SMP is big-endian; MMU chips will be little-endian. We should pick one and stick to it for this work. Big-endian is the path of least resistance; flag as a decision.
- **Q4.** Do we need to support the FDPIC ABI on every thread, or is that already a per-process concern that's invisible to the hardware? (Almost certainly the latter, but worth confirming early to avoid a surprise during Phase 4.)

## 10. Reporting cadence

Lightweight, in keeping with the scope:

- A short weekly status note in the project repo: what shipped, what's blocked, what's next.
- A phase-exit retrospective committed as `docs/phase_N_retro.md` covering: what we said we'd do, what we actually did, what the metrics say, what the next phase needs to know.
- A single living risk register (this document's §7) updated whenever a risk fires or a new one is identified.

That's the plan. The first concrete action is resolving D1–D6 in §3; everything downstream is gated on those.
