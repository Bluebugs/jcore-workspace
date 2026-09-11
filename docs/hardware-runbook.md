# Hardware runbook — the measurement work, as one list

**Who this is for.** Someone with a board on the desk, a finite evening, and no
way to tell from the specs what to run first. The J4 remediation programme is
**complete as a plan** — Waves 0–3, F, F2, C3 and the first kernel code are
merged — and what is left is almost entirely measurement and hardware. That work
exists today only as individual experiments scattered across a dozen specs, which
is why nobody has scheduled it: **the ordering constraints between the items are
invisible when each item is read alone.** This document is the list.

**What it is and is not.** It is an index and a schedule. It is **not** a
decision record ([decisions/README.md](decisions/README.md) reserves that
directory for decisions with no owning spec; this document decides nothing), and
it is **not** a spec — every experiment below is owned by the document that
specifies it, and per [decisions/0001](decisions/0001-one-authority-per-fact.md)
this file links rather than restates. It carries **two** facts of its own, both
registered in [fact-ownership.md](fact-ownership.md): the count of unscheduled
hardware programmes, and the count of items in §1's table.

**Every claim about code in this document was checked on 2026-09-10 against
`origin/master` (`origin/jcore` for `linux`), never a checked-out submodule
pointer** — [decisions/0002 §2](decisions/0002-supersede-convention.md) — and
case-insensitively, because VHDL is case-insensitive and `git grep` is not. That
last point is not a formality: a case-sensitive search of this tree has produced a
confident wrong "there is no X" finding twice in this programme.

Status: **working document**, 2026-09-10.

---

## 0. The answer, before the detail

| | Count | What it needs | What a result can move |
|---|---|---|---|
| **A — runnable today** | 4 | The ULX3S / ECP5-85F, the shipping `j4-rom` bitstream, `jcore-cpu`'s cosim | **L4** only, and only its evidence clauses (a) and (b) for one transmitter |
| **B — blocked on a builder programme** | 28 | One of **6** unscheduled hardware programmes (§4) | The *evidence* half of L1, L2, L3, L5, L6. The specification half is already done |
| **C — needs a booted Linux and a workload** | 3 | A J4 kernel on the board, a workload corpus, `perf` | Nothing on the bar. These decide **architecture and cost** |
| **D — needs the gf180 flow** | 1 | A gate-level ASIC run with switching activity | Nothing on the bar. Informs the ASIC core choice |

**Read this before you plan around it.** Nothing in category A moves a bar item
to `MET`. All seven items of
[security/threat-model.md §8](security/threat-model.md)'s launch bar are `NOT MET`
and will stay so until at least one of §4's six programmes is scheduled — the
finding [j4-final-review.md §6](j4-final-review.md) made and F2 re-confirmed over
25 further commits. What category A buys is the one thing this programme has never
had: **a measurement against hardware that exists.**

---

## 1. The list

Thirty-six items. `#` is this document's row number and nothing else — the
citable identity of an item is in the `Item` column, which names its owner.

| # | Item | Needs | Unblocked by | What a result moves |
|---|---|---|---|---|
| 1 | `W-E1` — how often does a squashed fetch arm an I-side walk? ([mmu/hardware-spec.md §5.0a](mmu/hardware-spec.md)) | Cosim or board; the `sim/tests` MMU corpus **and** two directed tests | — | **L4** clause (b) for the walk transmitter |
| 2 | `W-E2` — what does delaying the arm cost? ([mmu/hardware-spec.md §5.0a](mmu/hardware-spec.md)) | The `mmudrain` whole-run A/B harness | — | Nothing on the bar; prices the rule |
| 3 | Hardware-walker latency vs the software refill ([j4-remediation-plan.md §D1](j4-remediation-plan.md)) | `jcore-cpu`'s `sim/bench_tlb_hotpath.sh` | — | Decides burst-read, not a bar item |
| 4 | Speculation-defence cost ([j4-remediation-plan.md §D1](j4-remediation-plan.md)) | Item 2 plus a model | — | Feeds L4's cost argument |
| 5 | Store-queue synthesis A/B ([sq/spec.md §6.5](sq/spec.md), experiment 1) | ECP5 synth of a queue block | a store queue | **L6** evidence |
| 6 | Store-queue streaming throughput ([sq/spec.md §6.5](sq/spec.md), experiment 2) | A queue and a mapped ring | a store queue | Decides clear-vs-zero-mux |
| 7 | Store-queue gang-switch cost ([sq/spec.md §6.5](sq/spec.md), experiment 3) | A queue, a hypervisor, the PMU | a store queue | Confirms a predicted null |
| 8 | FP register-file synthesis A/B ([fpu/spec.md §7.7](fpu/spec.md), experiment 1) | An FPU register file | a Tier-1 FPU and SIMD unit | **L3**, **L6** evidence |
| 9 | Is the FP dirty state worth its existence? ([fpu/spec.md §7.7](fpu/spec.md), experiment 2) | An FPU, a hypervisor, two guests | a Tier-1 FPU and SIMD unit | Deletes two bits or keeps them |
| 10 | Per-instruction cost of the dirty set ([fpu/spec.md §7.7](fpu/spec.md), experiment 3) | An FPU | a Tier-1 FPU and SIMD unit | Confirms a predicted null |
| 11 | SIMD beat-serial throughput ([j4-remediation-plan.md §D1](j4-remediation-plan.md)) | A SIMD unit on the board | a Tier-1 FPU and SIMD unit | Kills neutral tiers |
| 12 | `P-E1` — pLRU metadata confinement ([cache/l2-spec.md §16.4](cache/l2-spec.md)) | An L2 with two masks | an L2 | **L5** metadata sub-clause |
| 13 | `P-E2` — L2 MSHR reservation cost ([cache/l2-spec.md §16.4](cache/l2-spec.md)) | An L2 | an L2 | **L5** MSHR sub-clause |
| 14 | `P-E3` — the interference bound, measured ([cache/l2-spec.md §16.4](cache/l2-spec.md)) | An L2 and two domains | an L2 | **L5** bandwidth sub-clause |
| 15 | `P-E4` — `movca.l` residue ([cache/l2-spec.md §16.4](cache/l2-spec.md)) | An L2 and a `movca.l` the core decodes | an L2 | **L6** site evidence |
| 16 | `P-E5` — enumerate the cross-domain flush paths ([cache/l2-spec.md §16.4](cache/l2-spec.md)) | An L2, **and a board that carries the register** (§9.4) | an L2 | **L5** flush-reach sub-clause |
| 17 | `P-E6` — refuse to elaborate a partition with no tag ([cache/l2-spec.md §16.4](cache/l2-spec.md)) | An L2 elaboration | an L2 | Nothing; a build-refusal guard |
| 18 | L2 partition performance ([j4-remediation-plan.md §D1](j4-remediation-plan.md)) | An L2, N ways, a thrash workload | an L2 | Sets min ways per tenant |
| 19 | `I-E0` — reset state, read before the first write ([iommu/hardware-spec.md §10.1](iommu/hardware-spec.md)) | An IOMMU observable pre-init | a BMID-carrying fabric, an IOMMU and a DMA master | **L2** evidence |
| 20 | `I-E1` — an unclaimed BMID is blocked ([iommu/hardware-spec.md §10.1](iommu/hardware-spec.md)) | A harness that can originate under any BMID | same | **L2** evidence, the clause satisfiable on paper |
| 21 | `I-E2` — the bypass lock holds ([iommu/hardware-spec.md §10.1](iommu/hardware-spec.md)) | An IOMMU and a transaction source | same | **L2** evidence |
| 22 | `I-E3` — detach re-protects before the call returns ([iommu/hardware-spec.md §10.1](iommu/hardware-spec.md)) | A concurrent master or mid-teardown injection | same | **L2** evidence |
| 23 | `I-E4` — a global-match entry matches nothing ([iommu/hardware-spec.md §10.1](iommu/hardware-spec.md)) | A back door into the entry array | same | **L2**, lookup half |
| 24 | `I-E5` — the per-BMID quota is real ([iommu/hardware-spec.md §10.1](iommu/hardware-spec.md)) | Two BMIDs and a genuinely oversubscribed pool | same | **L2** evidence |
| 25 | `I-E6` — device-written data is seen by the CPU ([iommu/hardware-spec.md §10.1](iommu/hardware-spec.md)) | A DMA master | same | Distinguishes a coherence contract from a claim |
| 26 | `T-E1` — a violating tenant placement is refused ([hypervisor/hardware-spec.md §4.7.3](hypervisor/hardware-spec.md)) | **Two** thread contexts with different tenancy | FGMT and a hypervisor | **L1** detector evidence |
| 27 | `T-E2` — the microreset's area, `Fmax` and duration ([hypervisor/hardware-spec.md §4.7.3](hypervisor/hardware-spec.md)) | A microreset to synthesize | FGMT and a hypervisor | **L1**; may re-shape the scrub |
| 28 | `T-E3` — residue, per structure class ([hypervisor/hardware-spec.md §4.7.3](hypervisor/hardware-spec.md)) | A gang switch and two tenants | FGMT and a hypervisor | **L1** per-structure evidence |
| 29 | Out-of-order vs in-order + FGMT ([j4-remediation-plan.md §D1](j4-remediation-plan.md)) | The in-order + FGMT point, on the FPGA | FGMT and a hypervisor | Confirms or reopens [decisions/0009](decisions/0009-in-order-fgmt-is-the-default-path.md) |
| 30 | SM synthesis A/B ([simd/gpu/simd-gpu-spec.md §16.5](simd/gpu/simd-gpu-spec.md), experiment 1) | A first SM, **and a registered `Fmax` floor for its target** (§9.5) | a GPU | Decides the window checkers |
| 31 | Texture throughput ([simd/gpu/simd-gpu-spec.md §16.5](simd/gpu/simd-gpu-spec.md), experiment 2) | An SM at 4 and 8 resident warps | a GPU | Decides the texture-path check |
| 32 | Shader memory latency ([simd/gpu/simd-gpu-spec.md §16.5](simd/gpu/simd-gpu-spec.md), experiment 3) | An SM address path | a GPU | May fall back to bounds-only |
| 33 | TLB sizing on real workloads ([j4-remediation-plan.md §D1](j4-remediation-plan.md)) | A booted J4 kernel, a workload, `perf` | — | Grows the TLB or leans on huge pages |
| 34 | Dirty-bit full-TSB-wipe fault rate ([j4-remediation-plan.md §D1](j4-remediation-plan.md)) | A booted J4 kernel and a write-heavy workload | — | Adds single-entry invalidate, or not |
| 35 | Aggregate-throughput multiplier ([j4-remediation-plan.md §D1](j4-remediation-plan.md)) | A measured single-thread baseline, then a trace-driven model | — | Re-sets the published expectation |
| 36 | Energy per op `[ASIC]` ([j4-remediation-plan.md §D1](j4-remediation-plan.md)) | A gf180 gate-level run with real switching activity | — | Informs the ASIC core choice |

That is **36** measurement items, against 7 bar items and 2 architecture
decisions. `enumeration-row-count` counts the rows of that table against the
figure stated here, because a row silently dropped under an unchanged count is
exactly how a scheduled programme becomes an unscheduled one.

---

## 2. Measurement discipline — read this before running anything

This section is in a runbook rather than a method note because **it is where the
effort in this programme actually goes wrong.** Every rule below was paid for by a
wrong result that was published first and unpicked afterwards.

**The rule under all of them:** no invented figures, and the phrase for a number
nobody has is `unknown at this stage — needs measurement`
([decisions/0005](decisions/0005-unmeasured-figures-are-removed.md)). A plausible
number in a table is worse than a blank, because a blank gets measured.

### 2.1 Area A/B on the ECP5

1. **The LUT4 noise floor is about 368.** Two RTL trees on this core differing
   only in the operand order of one `or` synthesized 368 LUT4 apart
   ([decisions/0004](decisions/0004-platform-tag-convention.md)). Any area delta
   smaller than that is not a result. This is also why a cross-vendor,
   cross-node ratio lifted from a paper is worth less than measuring badly.
2. **Never build an area table across trees that differ in assertion count.**
   `jcore-cpu`'s `cpu_synth.sh` deletes assertion cells *after* synthesis, so the
   cell disappears and its influence on how everything else mapped does not.
   Measured effect of adding one assertion: **+286 to +541 LUT4**. Wave-0's A3
   booked ~540 LUT4 of assertion against a reset flush and **inverted the sign**
   of its own result ([j4-wave0-status.md](j4-wave0-status.md)).
3. **Never synthesize a baseline by deleting a term.** A port left present and
   connected with only its term removed is a dangling input, which on this core
   produces measured ±464 LUT4 swings. **A baseline comes from a real commit**,
   built in a throwaway `git archive` copy ([j4-wave0-status.md](j4-wave0-status.md)).
4. **Do not run `jcore-cpu`'s `scripts/fmax_ab.sh` casually.** It and
   `synth/with_overlay_decoder.sh` regenerate a J4-overlay decoder into *tracked*
   `decode/*.vhd` behind a `|| true` restore, so a failed run leaves overlay
   tables in tracked source. Do synthesis in throwaway copies.

### 2.2 `Fmax` A/B on the ECP5

**A single seed decides nothing.** Seed-to-seed spread on the J4 netlist is about
±1.2–1.7 MHz, and the workflow's own sweep measured 32.51 ± 0.41 MHz over 16
seeds at the chosen placer weighting against 30.97 ± 0.61 at `nextpnr`'s default
— the same netlist, a 1.5 MHz apparent difference that a one-seed comparison
would have called a result in either direction. **Use 12–16 seeds, and report the
minimum as well as the mean.** The distribution and the floors it is measured
against are [platform-baseline.md §3](platform-baseline.md).

**And the placement gain is netlist-specific.** On an older netlist the same flag
measured a null. A floor, or a weighting, derived for one core has to be
re-derived from that core's own sweep and cannot be shifted by a constant.

### 2.3 The J4 CI `Fmax` gate is itself an open item

The gate that guards every one of these measurements reads **one** `nextpnr` seed
against the J4 floor registered in [platform-baseline.md §3](platform-baseline.md)
— the run in `jcore-cpu`'s `.github/workflows/synth-cpu.yml` passes no seed and
takes the single default run's number. That floor sits roughly two standard
deviations under the mean, and the observed 16-seed worst case clears it by about
one. **That is a real margin and a thin one, and it is the margin any
microarchitectural addition to J4 spends** — which is to say, the margin
item 27 spends, and item 8, and item 30.

A one-sample gate is a defensible engineering choice (it is cheap, and `nextpnr`
is deterministic per seed, so it does not flake). It is listed in §9 as an open
item anyway, because nothing records the choice as a choice, and the first person
whose change lands 0.8 MHz low will not be able to tell a regression from a seed.

---

## 3. Category A — what can be run today

**What exists on the board side.** The ULX3S / ECP5 LFE5U-85F target in
`jcore-soc@origin/master` builds a single-core J4 with the MMU in RTL
(`targets/boards/ulx3s/design.j4-rom.yaml`), and
`targets/boards/ulx3s/BOOT-J4-MMU.md` is a working runbook for booting the J-Core
MMU Linux port on it. There is no step in this section that needs a bitstream
that does not exist.

**What exists on the instrument side**, and it is better than the specs imply:

- **8** fixed-function 32-bit free-running performance counters in RTL
  (`jcore-cpu:core/perf.vhd`, `core/perf_pkg.vhd`) at `0xFF001000` — cycles,
  instruction dispatches, I-fetch references and waits, D-access references and
  waits, TSB walks armed, TSB walks that hit.
- **`TLBINST` at `0xFF000058`**, which reports ITLB and DTLB slot writes and
  therefore reports speculative shadow installs directly.
- **A `perf` backend for those counters in `linux@origin/jcore`**
  (`arch/sh/kernel/cpu/jcore/perf_event.c`). `arch/sh/Kconfig` selects
  `PERF_EVENTS` unconditionally for `SUPERH`, so it is in a J4 build without a
  config change. **It counts; it cannot sample** — there is no PMU interrupt, so
  `perf record` is rejected. Everything below is a counting measurement.
- **`sim/bench_tlb_hotpath.sh`**, a cosim harness that brackets TLB-miss latency
  between two fixed program addresses.
- **The `mmudrain` guard**, which already carries a whole-run A/B of the
  speculative shadow fill on I-side and D-side install counts.

### 3.1 Item 1 — `W-E1`, and why a zero from the corpus means nothing

Count I-side walk arms whose fetch never reaches dispatch, over the `sim/tests`
MMU corpus **and two directed tests**. The two are not redundancy. The pipeline
has two ways to squash a fetch — a taken branch immediately before an
ITLB-absent code page, and the precise-exception squash window — and a test that
exercises only one of them **reports a zero that means nothing**.
[mmu/hardware-spec.md §5.0a](mmu/hardware-spec.md) states the criterion in those
terms: a zero from the corpus alone does *not* meet it, because a corpus that
never builds the scenario is the failure mode the whole item is about.

A non-zero count is what discharges the non-vacuity clause of
[security/threat-model.md §8](security/threat-model.md) **L4** for this
transmitter: the test is "this counter reads zero", it must **fail** on the core
as it stands, and pass after the rule in
[mmu/hardware-spec.md §5.0a](mmu/hardware-spec.md) lands. Run it red first or it
is not evidence.

**This is the only item in the programme that can be red-before-green today**,
because it is the only one whose transmitter is on `origin/master`:
`core/tlb_walk.vhd` is present, and the I→D speculative shadow fill has its own
install path (`shadow_wr`, `shadow_vpn`, `shadow_ptel`, `shadow_asid` in
`core/cpu.vhd`), both re-confirmed 2026-09-10.

### 3.2 Item 2 — `W-E2`, and report it with the fill

A/B the gated arm over the same corpus, on cycles, **against the `mmudrain`
harness** so the number is commensurable with the shadow-fill A/B already in
`jcore-cpu/docs/architecture/tlb.md`. Report the two **together**: the rule in
[mmu/hardware-spec.md §5.0a](mmu/hardware-spec.md) makes the shadow fill rarer,
so pricing the gate without re-pricing the fill prices half a change.

### 3.3 Item 3 — the walker gate, whose baseline has been removed

[j4-remediation-plan.md §D1](j4-remediation-plan.md) states this gate's baseline
as the software refill at 22–23 cycles and its kill criterion as "if the
serialized walk ≥ software path, add burst read or reconsider". **The software
path no longer exists**: `sim/bench_tlb_hotpath.sh`'s own header records that the
hardware walker replaced it, that with the walker on a TSB hit resolves as a
pipeline stall with no handler PC in the trace at all, and that the 22–23 figure
is kept as a historical anchor rather than as a live comparator. The measurement
is still worth making and the harness still runs; **the comparison in the gate
has to be re-stated before the result means anything**, and that is a
documentation edit, not a measurement.

The same header carries a warning worth repeating here, because it is the
category-A failure mode: the script once bracketed on a handler PC range and, with
the walker on, reported the cold path twice — once mislabelled as a TSB hit, at
3.5× the real number. **It did not fail; it lied.** A bracket defined by symbol
addresses silently measures whatever the assembler puts between them.

### 3.4 Item 4 — speculation-defence cost

[j4-remediation-plan.md §D1](j4-remediation-plan.md) asks for delay-on-miss plus
the I-side variant to be modelled. On this core the I-side variant *is* item 2,
so most of this gate is item 2's number plus a model of the D-side. Note what the
plan says about where the model must run: cost is to be measured **on the FGMT
core**, because cycles one thread loses are partly reclaimed by its sibling — and
there is no FGMT core, so the FGMT half of this gate is category B and belongs to
§4's fifth programme. What can be done today is the in-order number, and it
should be published as an in-order number.

---

## 4. Category B — blocked, and on what

**The finding this section exists to make visible.**
[j4-final-review.md §6](j4-final-review.md) found that seven of Wave 3's eight
implement halves failed the same way, and that the plan never generalised what it
had recorded twice: they are **not blocked on a scrub task, they are blocked on a
builder task.** Each Wave-3 rule set is an *entry condition* on whichever task
first builds its structure, and the Wave-3 deliverable was never an
implementation — it was a set of conditions attached to **6** unscheduled hardware
programmes. F2 re-checked this over 25 further commits and nothing scheduled any
of them.

| # | Programme | Items it unblocks | Why nothing smaller works |
|---|---|---|---|
| 1 | **A store queue** | 5, 6, 7 | [sq/spec.md](sq/spec.md) §1 says the queue does not exist; re-checked 2026-09-10, no `*.vhd`/`*.vhm` in `jcore-cpu@origin/master` matches `store_queue`, `storequeue` or `sq_`, case-insensitively |
| 2 | **A Tier-1 FPU and SIMD unit** | 8, 9, 10, 11 | No file matches `entity fpu`, `component fpu`, `entity simd`, `component simd`, `fpscr`, `fpul` or `vcsr`. On the kernel side `CPU_SUBTYPE_JCORE` does not select `CPU_HAS_FPU`, so `CONFIG_SH_FPU` cannot be set |
| 3 | **An L2** | 12–18 | No L2 in either RTL repository. Every case-insensitive `l2` match in `jcore-cpu@origin/master` is a `textio` line variable in a d-cache testbench, a config file name or a TLB comment; in `jcore-soc@origin/master` it is an FPGA ball name in three pad rings |
| 4 | **A master-identifier-carrying fabric, an IOMMU, and one real DMA master** | 19–25 | The largest prerequisite in the programme, and it is *not* the IOMMU. `cpu2j0_pkg.vhd`'s `cpu_data_o_t` is `{en, a, rd, wr, we, d}` — **the bus has no field to put a master identifier in**. `iommu`, `bmid`, `iotlb` and `dvma` match nothing in either repo, and `components/dma/` is a stub |
| 5 | **FGMT and a hypervisor** | 26, 27, 28, 29 | `fgmt`, `thread_id` and `multithread` match nothing; `barrel` matches only the barrel *shifter*. `hpriv`, `hcall`, `hrte`, `vbr_hyp`, `pdid`, `hedr` and `htcr` match nothing |
| 6 | **A GPU** | 30, 31, 32 | `gpu`, `shader` and `warp` match no `*.vhd`/`*.vhm` in either repository. This one is a programme in no wave and no phase, not merely a task in no wave |

Each of those greps was run case-insensitively on 2026-09-10 against
`origin/master`. The `barrel` and `l2` exclusions are there because both are
known false positives in this tree.

**The honest framing, which is not an apology.** Every item in this category was
**specified by a task that could not run it**. That is the correct shape for the
work — [j4-final-review.md §6](j4-final-review.md) says the rule sets are entry
conditions on the builder tasks — and it becomes dishonest only at the moment
someone reads a specified experiment as a discharged one. That is what §7 and §8
exist to prevent.

**The second thing this category needs, and nobody has scheduled it either.**
Several of these harnesses could be built against a *model* rather than silicon,
today, in parallel with the hardware. Items 12, 15, 17, 19–24 and 26 are all
harness work whose subject is a state machine, not a timing path.
[j4-final-review.md §6](j4-final-review.md) names this as the second unscheduled
programme; building it now is what would stop Wave 3's specification-half
completions from silently becoming the whole story.

---

## 5. Category C — needs a booted Linux and a workload

Three items, and what they need beyond a bitstream is a **workload corpus**, which
the programme does not have either. [jcore-ulx3s-service-plan.md](jcore-ulx3s-service-plan.md)
sketches one (cross-compiled glibc tests, kernel selftests, compiler test-suites,
generated programs) and lists "differential test corpus seeding" among its own
open items.

**What is ready:** the board, the kernel, and the counters — the `perf` backend of
§3 is in `linux@origin/jcore` and needs no config change. `PMWLK` and `PMWHT`
(walks armed, walks that hit) plus `TLBINST` give item 33 its miss rate directly.
`PMCYC` and `PMINS` give item 35 its single-thread baseline.

**What is not ready, and matters:**

- **There is no sampling.** No PMU overflow interrupt exists; `PMOVF` is a polled
  flag and the driver sets the no-interrupt capability, so `perf record` is
  rejected outright. Every measurement here is a counted total over a bracket.
  Attributing a miss rate to a *function* is not available.
- **There are no cache counters.** The eight counters cover cycles, dispatches,
  bus references, bus waits and walks. Item 34's "fault rate on write-heavy
  workloads" is reachable through the walk counters; a *cache* miss rate is not
  reachable at all, and any gate phrased in terms of one needs re-stating first.
- **Item 35's multiplier needs a model, not a second measurement.**
  [j4-remediation-plan.md §D1](j4-remediation-plan.md) asks for a trace-driven
  model at a stated memory bandwidth against a *measured* single-thread baseline.
  The baseline is a category-C evening. The multiplier is not a measurement at
  all until §4's fifth programme exists, and shipping it as one would be the
  defect [decisions/0005](decisions/0005-unmeasured-figures-are-removed.md) is
  about.

**None of these three moves a bar item.** They decide architecture and cost, and
they are the ones that would let the roadmap stop quoting J2's row for a J4
design — the error [platform-baseline.md §3](platform-baseline.md) had to retire
from five documents.

---

## 6. Category D — needs the ASIC flow

**Item 36, energy per op, `[ASIC]` only.** [j4-remediation-plan.md §D](j4-remediation-plan.md)
is explicit and it is worth restating because the temptation is real: **do not try
to measure energy on the ECP5.** The number comes from gate-level activity plus
power analysis in the ASIC flow, driven by switching activity from real traces.
Until that exists, energy claims are literature-calibrated estimates and must be
tagged as such.

The vehicle exists — `jcore-soc@origin/master:targets/asic/gf180_j4mmu` is a real
target with a librelane flow — and there is no `[ASIC]` frequency or energy
baseline yet ([platform-baseline.md §1](platform-baseline.md)). This item is
listed separately from category C rather than folded into it because its blocker
is a *flow*, not a board: a person with a ULX3S on the desk cannot start it, and a
person with the gf180 flow running does not need the board.

---

## 7. The experiments that pass for the wrong reason

**Seventeen of the thirty-six will report a green that means nothing if run by a
harness that cannot build their scenario.** Their owning specs say so, each in its
own words; this table puts them side by side, because the shape is only visible
when they are together and because a reviewer reading one spec will not recognise
it.

| Item | Shape | What a naive harness reports | What it must report |
|---|---|---|---|
| 26 `T-E1` | Compared set empty | **Pass.** On a single-context model the set the rule quantifies over is empty, so the assertion holds | **Not runnable.** A harness that cannot build a second context with a different tenancy has not tested the check |
| 19 `I-E0` | Observed after initialisation | Pass | **Not runnable** — a reset value read after initialisation is the initialisation's value |
| 20 `I-E1` | Cannot originate the transaction | Pass | **Not runnable.** This is the clause an implementer can otherwise satisfy entirely on paper |
| 25 `I-E6` | No device to originate from | Pass | **Not runnable** until a DMA master exists |
| 1 `W-E1` | Corpus zero | **Pass**, reading "the case never happens" | **Zero from the corpus alone does not meet the criterion.** Two directed tests, one per squash mechanism, must also fail to make it non-zero |
| 27 `T-E2` | Zero-cycle busy count | Pass — "the scrub is free" | **Fail.** A zero busy count means the scrub is not reaching a multi-entry array, which is the exact failure the duration constraint exists to prevent |
| 12 `P-E1` | Never run red | Pass | **Vacuous** unless first run without the confinement rule and shown to produce a non-empty set |
| 15 `P-E4` | Never run red | Pass | **Not a test of the rule** if it cannot be made red first |
| 28 `T-E3` | A class with no surviving pattern | "Class clean" | **Remove the row, with the reason.** A class that is not a channel on this implementation must not be left as scope nothing tests |
| 21 `I-E2` | Asserting the read-back only | Pass — the register reads 0 | **Insufficient.** A register reading 0 with the bypass mux still open passes it; the transaction assertion is the test |
| 22 `I-E3` | Asserting post-return state only | Pass | **Cannot see the window.** The assertion must come from a concurrent master or a transaction injected mid-teardown |
| 24 `I-E5` | Cap larger than the pool | Pass | **Proves nothing.** The test must run with the sum of reservations genuinely exceeding what the first BMID is allowed |
| 23 `I-E4` | Install-refusal half only | Pass | **Partial.** The lookup term is the half that matters, because it is the one that holds when the install path has a bug |
| 17 `P-E6` | A harness that never elaborates | "Did not succeed" — which is the pass condition | The pass must come from a *refusal to elaborate*, distinguished from a harness that was never asked |
| 16 `P-E5` | An incomplete enumeration | "No path found" | An enumeration is not a measurement: "no path found" and "did not look" are the same output. §9.4 adds a second trap on top of this one |
| 7 store-queue exp. 3 | A predicted null | "No difference" | The prediction is that there is none; a null therefore confirms nothing unless the harness is separately shown able to resolve one |
| 10 FP exp. 3 | A predicted null | "No difference" | Same. [fpu/spec.md §7.7](fpu/spec.md) says the experiment exists to confirm the null rather than assume it, which requires a demonstrated resolution |

**One criterion in the set is written the way all of them should be**, and it is
worth copying: [simd/gpu/simd-gpu-spec.md §16.5](simd/gpu/simd-gpu-spec.md)'s
texture-throughput experiment is killed only if sustained throughput falls at
*both* warp counts — a construction that separates a real throughput loss from
latency the warp scheduler absorbs, and that cannot be satisfied by a harness
which simply failed to load the machine.

**And the same discipline binds the residue tests that are not in §1's list.**
[fpu/spec.md §7.7](fpu/spec.md)'s four residue tests, plus the fifth with no FP
analogue in [simd/spec.md §2.6.1](simd/spec.md), and the five tests of
[cache/l2-spec.md §22.1b](cache/l2-spec.md), are evidence obligations rather than
measurements, which is why they are not numbered above. Every one of them carries
the same red-before-green bar, and there is nothing to run any of them on.

---

## 8. What a result would actually move — checked, not assumed

The rule for this section is
[j4-final-review.md §8](j4-final-review.md)'s: do not claim an experiment moves a
bar item without reading that bar item's own text. The programme has already been
caught twice by the opposite habit.

| Bar item | Status | What would move it | What would **not** |
|---|---|---|---|
| **L1** — core = single tenant | `NOT MET` | Items 26–28, after §4 programme 5. `T-E3` is what discharges the per-structure evidence requirement | Nothing in category A or C. The rule, the gang-switch list and the detector are all *specified* and none is demonstrated |
| **L2** — IOMMU default-deny | `NOT MET` | Items 19–25, after §4 programme 4 — and the prerequisite is the **bus**, not the IOMMU | Item 30–32. The GPU's windows sit inside the GPU, one master port below where this item acts. What the GPU *does* do is flip this item from `N/A`-as-blocker to blocking, by being the first tenant-influenced DMA master |
| **L3** — eager FP/vector switch | `NOT MET` | Items 8–10 plus the five residue tests, after §4 programme 2 | The vertical-FP ownership fix. Its defect is between two tasks inside one guest, and this item's boundary is the tenant |
| **L4** — speculation covers loads and the frontend | `NOT MET` | **Items 1 and 2 — the only bar movement available today.** Item 1 discharges clause (b) for the walk transmitter; item 2 prices the rule | Reaching `MET`. That needs a test per transmitter, a non-vacuity demonstration for each, **and** the residual list re-published with the implementation. A green corpus with a stale residual list does not discharge the last clause |
| **L5** — cache isolation beyond ways | `NOT MET` | Items 12–18, after §4 programme 3 — and even then only per sub-clause: five mechanisms, five tests, and a single "partitioning works" result discharges the first only | **The user-flush finding does not move it, and this is the worked example.** F2 found that the merged kernel cache-maintenance change turned `sys_cacheflush(2)` into a real flush primitive. Both reasons this item is unmet concern an L2 that does not exist, so a finding about an L1 that does neither opens nor closes a sub-clause |
| **L6** — scrub on ownership change | `NOT MET` | Items 5, 12–15 and 30–32, each red first, after programmes 1, 2, 3 and 6 | **Closing the last open `undefined` site moved nothing**, and this is the trap most likely to be re-fallen into. That count reaching zero completes the *specification* half; the bar is a residue test per site demonstrated red before the fix, and there is no store queue, no FPU, no SIMD unit, no GPU and no L2 to run one red on |
| **L7** — the walker's data source is hypervisor-owned | `NOT MET` | Hypervisor Phase 3. No item in §1's list is against this | Item 1. It widened part 4 of this item to a second counter without moving it: both addresses are decoded in RTL and nothing virtualizes either |

**The four categories of `NOT MET` are not the same category, and scheduling
should respect the difference.** L2, L3 and L6 are unmet because the hardware to
test does not exist. **L4's transmitters ship today** — what is missing is RTL
nobody has written against hardware that does. L5 is unmet for two independent
reasons, one of which was a design defect and is now fixed without the status
moving. L1 and L7 wait on a hypervisor. Reading all seven as one backlog is how a
category-A evening gets spent on a category-B item.

---

## 9. The non-experiment work that is also waiting

Not everything left in the programme is an experiment. These five are each
small, each blocking something, and each currently on nobody's list.

### 9.1 The coprocessor-bridge re-home needs an RTL co-owner

[encoding-sweep.md §2](encoding-sweep.md) found four J-Core encodings colliding
with SH-4 forms — the CPI coprocessor bridge's four operations, two of them in
the `1111` plane that a bare-metal J4 traps — and produced a **validated** fix:
give CPI the unused coprocessor index its CP0 twin leaves free, which re-homes
all four at once into slots the tooling reports virgin, leaves two indices spare,
and puts the whole bridge in one family with one rule.

It is not committed, and the reason is structural rather than doubt about the
fix. Regenerating from the patched encoding source changes four generated files
including the **shipping decoder**, so it is an RTL change;
[decisions/0008](decisions/0008-documented-but-unimplemented-encodings.md)
rule 4 forbids the sweep task from committing it. **Owner: B4 with an RTL/SoC
co-owner**, in one change together with the four `sh4guest.*` bindings in
[fact-ownership.md](fact-ownership.md) that go red on the day it lands — which
that registry already predicts and welcomes. This is the item most likely to be
lost, because it is finished work waiting on a second signature.

### 9.2 The J4 CI `Fmax` gate reads one seed

§2.3. Not a defect; an undocumented choice with about one standard deviation of
headroom, guarding every synthesis A/B in categories A, B and D.

### 9.3 Two obligations with no owner

Both from [j4-final-review.md §F2.8](j4-final-review.md), and neither is filed
anywhere:

1. **Where the hypervisor's gang-switch entropy comes from.** The gang-switch
   list requires a re-seed of the TSB victim selector at every ownership change;
   [hypervisor/hardware-spec.md §4.7.1a](hypervisor/hardware-spec.md) says
   hardware has no entropy source and makes the re-seed the hypervisor's write;
   no document names a source. [mmu/linux-spec.md](mmu/linux-spec.md)'s answer is
   a `late_initcall`, which is boot, not a gang switch. **This is an item on bar
   item L1's own normative list that no hardware can perform.**
2. **The dispatch-state input AIC2 needs.** The interrupt-delivery rule's
   predicate needs a signal or a register that no section provides.

Neither is a measurement, and both must be resolved before items 26–28 mean
anything, because both are inputs to the gang switch those items test.

### 9.4 No target that can run a J4 carries the cache-control register

*New, checked 2026-09-10; this is a finding of this document.*

[cache/l2-spec.md §16.2](cache/l2-spec.md) records that the shipping SoC puts a
cache-control block at `0xabcd00c0` ([cache/l2-spec.md §16.2](cache/l2-spec.md)),
outside P4, whose per-core words let one core invalidate another's whole L1-I and
L1-D, and it names the two boards that instantiate it: `targets/boards/turtle_1v0` and `targets/boards/mimas_v2`. That
is correct. What no document says is what it means for this programme:

- **Neither of those boards builds a J4.** A case-insensitive search for `j4`
  over `jcore-soc@origin/master:targets/boards/` returns hits under `ulx3s/`
  only. The two boards that carry the register are J2 boards.
- **The ULX3S does not carry it.** `targets/boards/ulx3s/base.yaml` declares four
  devices — GPIO, AIC, UART, SPI — and no cache-control device; its dual variants
  put the *same entity* at that address under the generic `ipi` class instead,
  for the IPI alone. `targets/boards/ulx3s/soc.vhd` ties `icache0_ctrl`,
  `icache1_ctrl`, `dcache0_ctrl` and `dcache1_ctrl` to the constant
  `CACHE_CTRL_ON`, so nothing reads the entity's invalidate outputs.
- **The gf180 target does not carry it either** — its own comment says "no
  cache-control device on this ASIC target" and hardwires the same four ports on.
  F2 found this half and did not carry it to the board.
- **No ULX3S or gf180 device tree has a `jcore,cache` node.** Only
  `mimas_v2/board.dts` and `turtle_1v0/board.dts` do.

Three consequences, each of which changes what someone would do:

1. **[decisions/0010](decisions/0010-dma-coherence-is-software-maintained.md)
   decision 4 does no work on any J4 target today.** The merged kernel change is
   real and correct; `arch/sh/mm/cache-jcore.c` finds its register by device-tree
   compatible string, and on a build with no such node it warns once and leaves
   every helper a no-op. The fix is sound and currently inert where it matters,
   and the inertness is visible only as one `pr_warn` line in a boot log.
2. **The user-mode flush channel is latent rather than live on a J4 board.**
   An `unprivileged whole-L1-I invalidate` — [security/threat-model.md §10](security/threat-model.md)
   accepts it as a residual — rests on the merged kernel change having given
   `sys_cacheflush(2)` a real mechanism. On a J4 target there
   is no mechanism to reach, so the residual is currently unreachable. **The
   acceptance stays as written** — it is right about what happens when the
   register is present, and adding it to a J4 board is a device-tree line — but
   a reader who tries to *demonstrate* the channel on a ULX3S will not be able
   to, and will draw the wrong conclusion from that.
3. **Item 16 cannot be run on the board this programme has.** `P-E5`'s one known
   cross-domain flush path is that register. Running it needs the register on a
   J4 target, or a J2 board, and the experiment's own note — that the path was
   found by reading a board YAML, which is not where anyone looks for a security
   control — applies twice over now that the board list is the deciding fact.

### 9.5 The GPU has no registered `Fmax` floor to be killed against

Item 30's kill criterion is that the window checkers take the SM below the floor
registered for its target, and
[simd/gpu/simd-gpu-spec.md §16.5](simd/gpu/simd-gpu-spec.md) says in its own text
that **no such floor exists** — the floors in
[platform-baseline.md §3](platform-baseline.md) are ECP5 ones and the GPU targets
a different part. Registering a floor for that target is a precondition of running
the experiment, and inventing one to have a criterion is exactly the failure
[decisions/0005](decisions/0005-unmeasured-figures-are-removed.md) exists to
prevent. This is a measurement plus a registry row, and it is the only entry
condition on §4's sixth programme that does not need the GPU to exist first.

### 9.6 Should the nine un-numbered experiments get IDs?

Nine of §1's items have no identifier of their own: the three in
[sq/spec.md §6.5](sq/spec.md), the three in [fpu/spec.md §7.7](fpu/spec.md) and
the three in [simd/gpu/simd-gpu-spec.md §16.5](simd/gpu/simd-gpu-spec.md). The
eighteen that do — `W-E`, `T-E`, `P-E`, `I-E` — are citable from other documents
and from bar items; the nine are not, which is precisely why they were the hard
ones to find.

**The case for minting them here:** this document has to refer to them, a
positional reference is fragile under editing, and the four existing families
show the convention is established and cheap.

**The case against, which wins:** an identifier in someone else's spec is a
normative addition to that spec. It becomes citable, and once
[security/threat-model.md §8](security/threat-model.md) or a future wave cites
`SQ-E2`, the owning spec can no longer renumber, reorder or merge its own
experiments without breaking a reference it did not make. Under
[decisions/0001](decisions/0001-one-authority-per-fact.md) the owning spec is the
one authority for its own content, and a runbook that mints identifiers into
three specs it does not own has made three specs' editorial decisions from
outside. The programme has a name for the failure where a document asserts
something about a subject it does not own, and it has paid for it more than once.

**What this document does instead:** refer to them by the numbering each spec
*already uses* — all three sections number their own experiments 1, 2, 3 — so the
reference is the spec's own and introduces nothing. And file the recommendation
as an open item with an owner: **the three owning specs should mint `SQ-E1..3`,
`FP-E1..3` and `G-E1..3` themselves**, in the shape the other four families use.
That is one edit each, it is theirs to make, and until they make it this
document's `#` column is the only stable handle the nine have — which is a defect
of the situation, stated rather than papered over.

---

## 10. What this document found while being written

Recorded separately from the inventory, because a runbook that quietly changes a
fact is worse than one that does not notice it.

1. **§9.4** — no target that can run a J4 carries the cache-control register, so
   the merged DMA-maintenance change does no work on any J4 target, the accepted
   user-flush residual is currently unreachable there, and item 16 cannot be run
   on the ULX3S. Four independent checks, listed in §9.4.
2. **The measurement instrument is in better shape than the specs say.**
   `jcore-cpu:docs/pmu/perf-counters.md` §10 lists a `perf` backend as "left to
   the Linux half" of the measurement-harness task. **It has landed**:
   `linux@origin/jcore:arch/sh/kernel/cpu/jcore/perf_event.c`, with
   `arch/sh/include/cpu-jcore/cpu/perf_event.h`, built for every `SUPERH` config.
   That moves item 33's and item 35's instrument from "to be written" to "boot it
   and read it", and the RTL-side document should say so.
3. **Item 3's baseline no longer exists.** Its kill criterion compares the
   hardware walk against a software refill path that the walker replaced; the
   figure survives in `sim/bench_tlb_hotpath.sh`'s header as a historical anchor
   and is marked there as one. The gate needs re-stating before the measurement
   means anything (§3.3).
4. **Exactly nine experiments are recorded as prose without identifiers**, and
   they are the three sets in [sq/spec.md §6.5](sq/spec.md),
   [fpu/spec.md §7.7](fpu/spec.md) and
   [simd/gpu/simd-gpu-spec.md §16.5](simd/gpu/simd-gpu-spec.md).
   [simd/spec.md §2.6.1](simd/spec.md) has none of its own and defers to the FPU
   spec's, run over both register files together — which is the right shape and is
   why it adds no item to §1.

---

## 11. What this document is not

It is not a status page: the bar's status is
[security/threat-model.md §8](security/threat-model.md)'s and is restated here
only with links. It is not a plan: sequencing lives in
[jcore-ulx3s-service-plan.md](jcore-ulx3s-service-plan.md) and the worklist in
[j4-remediation-plan.md](j4-remediation-plan.md). It is not a review:
[j4-final-review.md](j4-final-review.md) is, and most of §4 and §8 is its work
re-indexed by what a person can do with it.

**What would make it stale.** Any of §4's six programmes being scheduled; a
seventh appearing; an owning spec adding an experiment; a bar item moving; or the
counters in §3 changing. The first, third and fifth of those are guarded — the
programme count and the item count by `enumeration-row-count` against §4's and
§1's tables, and the counter count by a code binding against both the RTL that
implements it and the kernel header that exports it
([fact-ownership.md](fact-ownership.md)). The other two are not, and no check in
this workspace can catch them.
