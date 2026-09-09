# J4 / J32 remediation — execution plan (subagent-driven)

Status: **draft for review** (untracked). Companion to `docs/j4-remediation-plan.md`
— that file says *what* to do; this file says *how to execute it* with the
superpowers subagent-driven-development workflow: a fresh subagent per task, a
two-stage review after each, and a strict model policy.

The orchestrator (this session) never inherits work into its own context: it
curates exactly the context each subagent needs, dispatches it, adjudicates the
reviews, and tracks state in TodoWrite. Subagents never read the plan files —
they get the full task text and scene-setting context in their prompt.

---

## 1. Model policy (per project direction: Opus when needed, Sonnet for mechanical)

| Model | Use for | Roles |
|---|---|---|
| **Sonnet** | Well-specified, mechanical, 1–2 files, low judgment: encoding-DB entries, supersede-header/platform-tag sweeps, CI-script wiring, toolchain regeneration, test scaffolding from a precise spec, doc edits that follow a decided canonical value. | Implementer (mechanical tasks) |
| **Opus** | Correctness-critical or design/judgment work: RTL correctness (walker, privilege gate), security design, threat model, codesign contracts, OoO-vs-FGMT modeling, encoding collision adjudication, and **all review roles** (spec-compliance, code-quality, design-review). | Implementer (hard tasks) + every Reviewer |
| **Orchestrator** (this session) | Context curation, dispatch, review adjudication, dependency tracking, escalation. Does not implement. | Controller |

Rule of thumb from the skill: use the least powerful model that can do the job.
Here that means **Sonnet is the default implementer; a task earns Opus** when it
carries correctness risk, spans repos with integration concerns, or requires
design judgment. **Reviews are always Opus** — a cheap reviewer defeats the gate.
A `BLOCKED`/`DONE_WITH_CONCERNS` from a Sonnet implementer is a signal to
re-dispatch on Opus (or split the task), never to retry unchanged.

## 2. Workspace & branch discipline (multi-repo, worktrees, never main)

This is a superproject with submodules (`jcore-cpu`, `jcore-soc`, `linux`,
`binutils-gdb`). Before any code task:

- Create an isolated **git worktree per repo per track** on a feature branch
  (`git worktree add`), never work on `main`/`master`/`jcore`. The skill requires
  this; the orchestrator sets it up before dispatching the first implementer.
- Cross-repo tasks (the encoding sweep touches `docs` + `jcore-cpu/decode` +
  `binutils-gdb`) get one coordinating branch per repo, sequenced by the
  orchestrator; `jcore-cpu/docs/insns.json` is the single writer ([decisions/0003](decisions/0003-canonical-encoding-database.md)).
- The superproject records submodule commits only after a task's reviews pass.
- Doc/spec/research tasks edit `docs/` on a feature branch in the superproject.

## 3. Per-task loop (the skill's process, adapted for code vs design tasks)

**Code tasks** (Track A, B4 mechanics, C-implementation, D-infra):
implementer (writes failing test first per TDD → implements → tests → commits →
self-reviews) → **Opus spec-compliance review** → fix loop → **Opus code-quality
review** → fix loop → mark complete. Never start the quality review before spec
compliance is green.

**Design/spec tasks** (B0 decisions, B1 canonical picks, B2, B3, C0, C-design):
design-drafter (produces the spec/decision/doc + the CI check that will enforce
it) → **Opus design-review** (is it internally consistent, does it resolve the
contradiction, does it meet the security bar / codesign contract?) → fix loop →
mark complete. The "test" for a design task is the doc-vs-code CI check it ships
with (§B0), so design and its enforcement land together.

**Research tasks** (remaining D.3 items, further prior-art): dispatch a research
subagent (Opus for synthesis, Sonnet for gather) — not the implement/review loop;
output is an evidence briefing folded into the plan. Several are already done.

**Measurement/experiment tasks** (D1 gates): a subagent builds the harness, but
running it on the ULX3S is **human-gated** (hardware in the loop). These produce a
measurement report + a decision against the gate's kill criterion.

## 4. Task decomposition, model & reviewer assignment

Grouped by wave (see §5 for sequencing). "Repo" names the primary tree.

### Wave 0 — Confirmed hotfixes (start first; correctness-critical)

| # | Task | Repo(s) | Model | Review |
|---|---|---|---|---|
| A0 | **Design** the page-mask codesign contract: how the walker obtains page size at tag-compare time (size-in-tag vs canonical-granularity+size-field vs size-class index). Output: one contract written into `mmu/hardware-spec.md` + `mmu/linux-spec.md`. | docs | **Opus** | Opus design-review |
| A1 | Implement A0: walker honors page mask for 4K/16K/huge; kernel tag write matches; **non-vacuous mixed-size test matrix** (4K+16K+huge live simultaneously, non-base-first, aliasing, eviction) that fails on current RTL first. | jcore-cpu + linux | **Opus** | Opus spec + code |
| A2 | P4 MMU-register MMIO privilege gate (`SR.MD`, SH-4-correct exception) + user-mode denial tests (read & write, each register). | jcore-cpu | **Opus** | Opus spec + code |
| A3a | Warm-reset TLB flush (add `rst` branch / documented invariant + test). | jcore-cpu | **Sonnet** | Opus spec + code |
| A3b | Walker bus-takeover double-commit window: prove-unreachable guard or fix (MMIO/TAS correctness). | jcore-cpu | **Opus** | Opus spec + code |

### Wave 1 — Foundations (parallel with Wave 0)

| # | Task | Repo(s) | Model | Review |
|---|---|---|---|---|
| B0a | "One authority per fact" decision + supersede-header convention; apply supersede headers to known-stale sections. **DONE 2026-08-25** — [decisions/0001](decisions/0001-one-authority-per-fact.md), [decisions/0002](decisions/0002-supersede-convention.md), [fact-ownership.md](fact-ownership.md), `scripts/check-doc-facts.py` + `scripts/test-check-doc-facts.py`. | docs | **Opus** (decision) → **Sonnet** (apply) | Opus design-review |
| B0b | Platform-tag (`[FPGA]`/`[ASIC]`) sweep of existing numbers; retarget SIMD/FPU FPGA figures to ECP5. **DONE 2026-09-07, partially** — [decisions/0004](decisions/0004-platform-tag-convention.md), `platform-tag-foreign-part` check. Swept: `simd/hardware-impl.md`, `fpu/spec.md`, `cache/l2-spec.md` (one figure retracted, not tagged). **Not swept, tracked in 0004:** `ooo/j32{ooo,lt}-spec.md` and sixteen further specs, including `security/threat-model.md` §9's own deferred audit. | docs | **Sonnet** | Opus design-review |
| B0c | Doc-vs-code CI checks (page size, TSB offsets, P4 offsets, context image sizes) + `insns2asm --emit check` + `freespace` collision sweep in CI. **Also inherits from B0a:** wire `scripts/check-doc-facts.py` into CI (this superproject has no workflow file yet) as **`--strict --check-waivers`, with `actions/checkout` at `submodules: recursive` and the submodule remotes fetched** — without `--strict` a submodule-less checkout skips all ~50 `RESOLVED` markers and reports success having verified nothing ([decisions/0002 §Enforcement](decisions/0002-supersede-convention.md)). Also run `scripts/test-check-doc-facts.py` (the checker's own fixture tests). Then drive the per-fact code comparison off [fact-ownership.md](fact-ownership.md), which names the one document to check per constant. | jcore-cpu + docs | **Sonnet** (scripts) / **Opus** (what to assert) | Opus code |
| C0 | Threat model rewrite: adversary = guest kernel on a shared core; supersede `mmu/security-review.md`; ratify the §E.11 minimum launch bar. **DONE 2026-08-25** — [security/threat-model.md](security/threat-model.md); bar ratified as L1–L7. | docs | **Opus** | Opus design-review |
| D0a | FPGA measurement harness: boot Linux on ULX3S, collect PMU/walk/cache counters on real workloads. | jcore-soc + linux | **Opus** (design) / **Sonnet** (glue) | Opus code |
| D0b | Extend cosim beyond VA==PA / base-first so it exercises the bug-hiding cases (feeds A1's test matrix). | jcore-cpu | **Opus** | Opus code |

### Wave 2 — Spec/doc reconciliation (needs B0 conventions in place)

| # | Task | Repo(s) | Model | Review |
|---|---|---|---|---|
| B4 | **Encoding sweep**: every documented instruction into `jcore-cpu/docs/insns.json` ([0003](decisions/0003-canonical-encoding-database.md)), `--emit check` green, `freespace` re-homes collisions (SIMD/FMOV/FSCA/SUBC set, `movi20s` notation, `rts/n` reserve), regen toolchain. | docs + jcore-cpu + binutils-gdb | **Sonnet** (entry/regen) + **Opus** (collision adjudication) | Opus spec + code |
| B1 | Contradiction worklist — one canonical answer each + doc fixes + CI check. Split by difficulty: **Opus** for load-bearing (L2 write-through vs write-back/MSI, VIPT vs PIPT L1 — closed as PIPT, [mmu/hardware-spec.md §4.1a](mmu/hardware-spec.md) — TSBBR VA/PA, EXPEVT codes); **Sonnet** for mechanical (endianness, "J4" naming, CPUINFO addr, `rte` uop count). | docs | **Opus/Sonnet** per item | Opus design-review |
| B2 | SH-4-as-KVM-guest model + emulation-fidelity matrix (each review finding → emulated / native-must-decode / unsupported). | docs | **Opus** | Opus design-review |
| B3 | Roadmap reframe (FPGA vs ASIC deliverables) + the OoO-vs-FGMT model over real traces (burden-of-proof on OoO). | docs + model | **Opus** | Opus design-review |

### Wave 3 — Security remediation (each item: minimize-loss design → implement)

Each C-item is a design task (Opus, using the §E.10 low-overhead recipe + its
D.3 confirmation) followed by an implementation task (model per mechanics). Only
dispatch the implementer after the design-review is green and the perf/energy
minimize-loss step is settled.

| # | Task | Repo(s) | Design | Implement |
|---|---|---|---|---|
| C1a | SQ buffer residue scrub + defined-safe guest reads. **Design DONE 2026-09-09** — [sq/spec.md §6.5](sq/spec.md), [hypervisor/hardware-spec.md §4.7.1](hypervisor/hardware-spec.md) item 7. **The implementation half is not dispatchable and this row's `docs → jcore-cpu` is wrong as written** — see below. | docs → jcore-cpu | Opus | *blocked on the queues existing* |
| C1b | Eager (across-tenant) FP/SIMD switch + register scrub; 2-bit dirty tracking; movmu-style bulk save. **Design DONE 2026-09-09** — [fpu/spec.md §7.7](fpu/spec.md), [simd/spec.md §2.6.1](simd/spec.md), [hypervisor/hardware-spec.md §4.7.1](hypervisor/hardware-spec.md) item 8. **The implementation half is not dispatchable in either repo** — see below. | docs → jcore-cpu + linux | Opus | *blocked on an FPU existing* |
| C1c | Vertical-FP-SIMD FPSCR ownership fix + kernel-fpu discipline. **Design DONE 2026-09-09** — [simd/spec.md §2.4.1](simd/spec.md), [fpu/spec.md §6.3.1](fpu/spec.md), [simd/spec.md §2.6.2](simd/spec.md). **The defect is real and is *not* the bar item this row is filed under; the implementation half is not dispatchable in `linux`** — see below. | docs → linux | Opus | *blocked on an FPU existing* |
| C2a | GPU memory protection (base+bounds or IOMMU/BMID) — launch blocker before user shaders. **Design DONE 2026-09-09** — [simd/gpu/simd-gpu-spec.md §16](simd/gpu/simd-gpu-spec.md), [simd/gpu/architecture.md §5.4](simd/gpu/architecture.md). **The `or` is a false alternative, the "launch blocker" is not blocking any scheduled launch, and the implementation half is not dispatchable in any repo** — see below. | docs → jcore-cpu | Opus | *blocked on a GPU program existing* |
| C2b | Speculation: delay-on-miss + frontend coverage (commit-time predictor updates, tenant-tagged BTB, degenerate-STT taint, delayed spec TLB/PTW). | docs → jcore-cpu | Opus | Opus |
| C2c | FGMT single-tenant-core + fence.t-style microreset on realloc. | docs → jcore-cpu | Opus | Opus |
| C2d | IOMMU default-deny + per-device block + no global-match IOTLB + coherent-DMA owner. | docs → jcore-cpu + jcore-soc + linux | Opus | Opus |
| C2e | Cache isolation beyond ways (DAWG-semantics metadata + MSHR reservation + bandwidth QoS + per-tenant KSM + privileged flush ops). | docs → jcore-cpu + linux | Opus | Opus |

**C1a's implementation step reverses this table, and the reversal is recorded rather than
absorbed.** This plan schedules every C-item as design-then-implement in the same wave. C1a cannot
be: there is **no store queue in `jcore-cpu` or `jcore-soc` at all** — no region decode, no
buffers, no `QACR0`/`QACR1`, no SH-4 `PREF` — so there is no artifact for an implementer to add a
scrub to. The rules in [sq/spec.md §6.5](sq/spec.md) are not a follow-on to the baseline queues of
that document's §1–§5; they must land **inside** whatever task builds them, for the reason
[sq/spec.md §6.4](sq/spec.md) gives about the byte-order mode: the
[hypervisor/hardware-spec.md §4.4.3](hypervisor/hardware-spec.md) carve-out is enabled with the
queues, and after that there is no point at which a guest would notice a missing scrub. So the
Wave-3 implementer for C1a is not "an implementer for C1a" — it is the store-queue task, and it
does not exist in this plan. Until it does, **L6**'s store-queue site is specified and unbuilt, and
no residue test can be run red, which is the precondition for running one green.

**C1b reverses the same table in both of its repos, and one of the two is a new
kind of reversal.** The `jcore-cpu` half fails exactly as C1a's did: there is **no FPU and no SIMD
unit** in `jcore-cpu@origin/master` — no `entity fpu`, no `FPSCR`, no `VCSR`, no file whose path
contains `fpu`, `simd` or `float`, all checked case-insensitively — so there is no artifact for an
implementer to add a scrub to, and [fpu/spec.md §7.7](fpu/spec.md)'s rules must land inside
whatever task first builds a Tier-1 FPU. Wave-2 **B2**'s Decision B2-4 already traps and emulates
guest FP for that reason, and C1b adds a fourth reopening condition to it
([sh4-guest-model.md §4](sh4-guest-model.md)) so that turning native guest FP on cannot happen
without the scrub.

The `linux` half fails differently and more quietly: **the kernel's FPU support is compiled out on
this target.** `linux@origin/jcore`'s `arch/sh/Kconfig` gives `CPU_SUBTYPE_JCORE` no
`select CPU_HAS_FPU`, so `CONFIG_SH_FPU` cannot be set and `arch/sh/include/asm/fpu.h` reduces
`save_fpu`, `restore_fpu`, `release_fpu`, `grab_fpu` and `fpu_state_restore` to `do { } while (0)`.
*(C1c correction, 2026-09-09: this sentence named `unlazy_fpu` as one of the three. It is not —
`unlazy_fpu` and `clear_fpu` are `static inline`s defined **outside** the `#ifdef CONFIG_SH_FPU`
block, so they are still compiled, still call `preempt_disable()` and still clear `TS_USEDFPU`;
what they call is what vanishes. The conclusion is unchanged and the mechanism is not.)* There is also no hypervisor code
in that tree at all — nothing under `arch/sh` matches `SR_HPRIV`, `VBR_HYP`, `HEDR` or `HSQCR` —
and C1b's design is entirely hypervisor-side and guest-invisible by construction, so even a kernel
with `CONFIG_SH_FPU` on would have nothing to change. `docs → jcore-cpu + linux` is therefore wrong
in both directions for this row, and the `Implement Opus` cell describes work that cannot be
started.

**C1c reverses this table too, and it also reverses the reason it was scheduled.**
Three findings, in the order they matter.

1. **The defect is real, and [j4-remediation-plan.md §C1](j4-remediation-plan.md) already stated it
   precisely** — "close the case where SIMD reads/writes FPSCR while SR.FD=1 and FPSCR belongs to
   the parked owner (wrong rounding-mode + sticky-flag corruption)". [simd/spec.md §2.4](simd/spec.md)
   makes every governed FP operation read `FPSCR.RM` and, under `VCSR.IEE = 1`, write
   `FPSCR.FLAG`; the ownership requirement was attached to the FP-scalar writeback path alone, so a
   **vertical** FP block never took it. §2.1 of that document said in so many words that no SIMD
   instruction reads or writes `FPSCR`, which was false against its own §2.4 *and* its own §5.7.
   The fix is [simd/spec.md §2.4.1](simd/spec.md).
2. **It is not a cross-tenant channel, so it does not bear on L3**, the bar item the
   [security/threat-model.md](security/threat-model.md) reverse index files it under. C1b's FP-R1
   and FP-R3 already name `FPSCR` in the scrub value and apply it unconditionally at every
   ownership installation, so the tenant boundary was closed before C1c looked at it. What C1c
   fixes is a wrong-rounding-mode correctness defect and a channel between two tasks **inside one
   guest**, which no item of that bar requires. **C1c makes a fix the security bar does not ask
   for, and L3 is exactly where it was.**
3. **The `linux` half is not dispatchable, and "kernel-`fpu` discipline" does not mean what the row
   implies.** There is no `kernel_fpu_begin` under `arch/sh` in `linux@origin/jcore` (`128e8958`),
   `arch/sh` does not select `ARCH_HAS_KERNEL_FPU_SUPPORT`, and there is no consumer that would
   call one — no `arch/sh/crypto`, no `lib/crypto/sh`, no `lib/raid/raid6/sh`, and no SH hook in
   generic `crypto/`, `lib/crc/` or `lib/raid/`. What `arch/sh` *does* have is a rule stronger than
   the generic kernel contract: `arch/sh/kernel/cpu/fpu.c` `BUG()`s on an `SR.FD` trap taken from
   kernel mode — and it is inside `#ifdef CONFIG_SH_FPU`, which C1b established cannot be set on
   this target. So the discipline exists, is correct, and is compiled out, and there is nothing for
   Sonnet to add. The rules are [fpu/spec.md §6.3.1](fpu/spec.md) and
   [simd/spec.md §2.6.2](simd/spec.md), and they bind the task that lands `CPU_HAS_FPU`, which this
   plan does not contain.

**C2a reverses this row three ways, and the third one is about this plan rather than about the
GPU.** *First, the mechanism.* The row offers "base+bounds **or** IOMMU/BMID". Those are not
alternatives. [bus/fabric-spec.md §4.1–§4.2](bus/fabric-spec.md) makes BMID a constant held in the
*fabric*, not in the master, which the fabric stamps onto every transaction "overwriting any
BMID-like field the master itself might assert" — that unforgeability is the whole security value
of BMID, and it means a GPU holding 4–8 warps resident
([simd/gpu/architecture.md §1.1](simd/gpu/architecture.md)) cannot present a different BMID per
tenant without one physical master port per tenant. An IOMMU keyed on BMID can stop the GPU
reaching outside the GPU; it cannot stop warp A reading warp B's texture, because both requests
carry the same BMID. So the design picks base+bounds for the inner boundary and keeps the IOMMU as
the outer one, and the two rejected alternatives are recorded in
[simd/gpu/simd-gpu-spec.md §16.4](simd/gpu/simd-gpu-spec.md).

*Second, the C2d dependency, which turns out not to bind the chosen mechanism.* The IOMMU option
would have depended on C2d, since the IOMMU resets with every master bypassing
([iommu/hardware-spec.md §8](iommu/hardware-spec.md)) — and it is weaker than "unconfigured": no
IOMMU RTL exists in `jcore-cpu@origin/master` or `jcore-soc@origin/master` either. Per-context
base+bounds is self-contained and does not duplicate C2d, because C2d's granularity is the master
port and the GPU is one master port hosting many tenants. The ordering constraint that survives is
therefore not "C2d before C2a" but **"C2d before any GPU bring-up that runs more than one
tenant"**, with a recorded single-tenant mode for the case where the GPU arrives first
([simd/gpu/simd-gpu-spec.md §16.3](simd/gpu/simd-gpu-spec.md) G-R10). A precondition nobody has
scheduled sits in front of even that: [bus/fabric-spec.md §4.4](bus/fabric-spec.md)'s normative
allocation policy **has no GPU row**, so the GPU has no BMID to route.

*Third, "launch blocker" is true as a gate and false as urgency.* This row's phrasing implies work
in front of it. There is none. `jcore-ulx3s-service-plan.md` — the roadmap [decisions/0009](decisions/0009-in-order-fgmt-is-the-default-path.md)
re-staged — contains no occurrence of *GPU*, *OpenCL*, *shader*, *SIMT*, *Mesa* or *graphics* in its
entire length; it lists "framebuffer / desktop / video" under **non-goals** and the board's video
connector as "unused in this plan". 0009 itself never mentions the GPU, and its numbered sequence
runs 0 → 8.5 with no GPU phase before or after. The GPU's own documents agree: `no-gpu-dual-ecp5-asic.md`
is "Status: Research note / parked analysis" and says the rig is worth doing "*if* the
programmable-GPU program is ever un-parked; not a reason on its own to un-park it", and
[simd/gpu/architecture.md §1](simd/gpu/architecture.md) targets a **single Artix-7 XC7A200T** —
a different FPGA from the ECP5-85F the whole service plan is built on. So C2a is not a blocker on
the critical path; it is an **entry condition on un-parking**, and the design is worth having now
for the reason the rest of Wave 3 is: this is the cheapest moment, because nothing has been built
wrong yet. Stating it as urgency would be the error, and stating it as unimportant would be the
opposite error.

**The implementation half is not dispatchable in any repo, and this row's `docs → jcore-cpu` is
wrong twice.** There is no GPU in `jcore-cpu` or `jcore-soc` at `origin/master` — a
case-insensitive search for `gpu|shader|opencl|simt|warp|texel|rasteriz` returns two matches, both
false positives (`vpiSimTime` in `sim/sim/vpibridge.c`, the label `_movwarpr` in
`testrom/tests/testmov.s`). That is the same shape as C1a, C1b and C1c, but with a harder edge:
those three block on hardware some later task is expected to build, while C2a blocks on a program
that appears in no wave and no phase. And when it is built, `jcore-cpu` is the wrong single repo:
[simd/gpu/architecture.md §2, §5.1](simd/gpu/architecture.md) puts the command processor, the
DDR-controller ports, the tile write-out DMA and the scanout on the SoC side, and the missing BMID
row is `bus/fabric-spec.md`'s. The rules land **inside** whatever task builds the SM, for
[sq/spec.md §6.4](sq/spec.md)'s reason: after the GPU runs its first user kernel there is no point
at which a tenant would notice a missing check.

One further plan item did not survive checking. §E.10 prices C1's fix as
"movmu-style bulk save + per-register zero bit + background scrub", which reads as three cost
levers of a kind. `movmu` is not one of them in the way that implies:
[isa-density/hardware-impl.md §5.1](isa-density/hardware-impl.md) and the merged
`decode/decode_core.vhm` both make it a **decode-driven sequencing** construct with no new
datapath — one 32-bit memory operation per step, the same number of bus cycles as the unrolled
sequence. It buys instruction fetch and atomicity, not data movement, and data movement is what an
eager switch costs. The lever that removes the copy is the 2-bit dirty state, and
[fpu/spec.md §7.7](fpu/spec.md) orders them accordingly and allocates no encoding.

### Final

| # | Task | Model |
|---|---|---|
| F | Whole-implementation review across all merged tracks (security bar met, no regressions, docs↔code consistent). Then `superpowers:finishing-a-development-branch` per repo. | **Opus** |

## 5. Sequencing (dependency waves)

```
Wave 0  A0→A1, A2, A3a, A3b            (hotfixes — start now, parallel except A0→A1)
Wave 1  B0a/b/c, C0, D0a, D0b          (foundations — parallel with Wave 0)
Wave 2  B4, B1, B2, B3                 (needs B0 conventions; B4 needs B0c CI)
Wave 3  C1a..C2e                       (each needs C0 threat model + its D.3 confirm; several need D0 measurements)
Final   F                             (needs all)
```

- **Within a wave**, dispatch independent tasks one at a time (the skill forbids
  parallel *implementer* subagents on the same tree — conflicts). Independent
  tasks on *different repos/worktrees* may overlap, but keep reviews serialized
  per tree.
- **A0 gates A1** (design before implement). **B0c gates B4** (the check gate
  must exist before the sweep is meaningful). **C0 gates all of Wave 3.**
  **D0 gates the D1 experiments** and informs B3 and the Wave-3 minimize-loss
  confirmations.
- Measurement/experiment steps (D1, and each Wave-3 perf confirmation on FPGA)
  are **human-gated**: the subagent prepares and reports; a human runs the board
  and records the decision against the kill criterion.

## 6. Status handling & escalation (from the skill)

- **DONE** → spec review. **DONE_WITH_CONCERNS** → read concerns; correctness/
  scope concerns fixed before review, observations noted. **NEEDS_CONTEXT** →
  orchestrator supplies it, re-dispatch. **BLOCKED** → diagnose: context problem
  (add context, same model), needs more reasoning (**re-dispatch Sonnet→Opus**),
  too large (split), or the plan is wrong (**escalate to the human**). Never
  retry unchanged; never ignore an escalation.

## 7. First move (go/no-go)

Recommended kickoff, pending your consent (the skill forbids starting on `main`
without it):
1. Orchestrator creates worktrees: a `docs` feature branch, and `jcore-cpu` +
   `linux` feature branches for the walker fix.
2. Dispatch **A0** (Opus) — the page-mask codesign contract — because A1's
   implementation and its test matrix both depend on the contract A0 chooses.
3. In parallel, dispatch **B0a** (Opus decision) and **A2** (Opus) — independent
   trees, no A0 dependency.

On your go-ahead I set up the worktrees and dispatch A0, B0a, and A2. Everything
else follows the waves above, one task at a time per tree, two-stage review each.
