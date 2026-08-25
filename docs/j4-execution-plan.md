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
  orchestrator; `docs/insns.json` is the single writer.
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
| B0b | Platform-tag (`[FPGA]`/`[ASIC]`) sweep of existing numbers; retarget SIMD/FPU FPGA figures to ECP5. | docs | **Sonnet** | Opus design-review |
| B0c | Doc-vs-code CI checks (page size, TSB offsets, P4 offsets, context image sizes) + `insns2asm --emit check` + `freespace` collision sweep in CI. **Also inherits from B0a:** wire `scripts/check-doc-facts.py` into CI (this superproject has no workflow file yet) as **`--strict --check-waivers`, with `actions/checkout` at `submodules: recursive` and the submodule remotes fetched** — without `--strict` a submodule-less checkout skips all ~50 `RESOLVED` markers and reports success having verified nothing ([decisions/0002 §Enforcement](decisions/0002-supersede-convention.md)). Also run `scripts/test-check-doc-facts.py` (the checker's own fixture tests). Then drive the per-fact code comparison off [fact-ownership.md](fact-ownership.md), which names the one document to check per constant. | jcore-cpu + docs | **Sonnet** (scripts) / **Opus** (what to assert) | Opus code |
| C0 | Threat model rewrite: adversary = guest kernel on a shared core; supersede `mmu/security-review.md`; ratify the §E.11 minimum launch bar. | docs | **Opus** | Opus design-review |
| D0a | FPGA measurement harness: boot Linux on ULX3S, collect PMU/walk/cache counters on real workloads. | jcore-soc + linux | **Opus** (design) / **Sonnet** (glue) | Opus code |
| D0b | Extend cosim beyond VA==PA / base-first so it exercises the bug-hiding cases (feeds A1's test matrix). | jcore-cpu | **Opus** | Opus code |

### Wave 2 — Spec/doc reconciliation (needs B0 conventions in place)

| # | Task | Repo(s) | Model | Review |
|---|---|---|---|---|
| B4 | **Encoding sweep**: every documented instruction into `insns.json`, `--emit check` green, `freespace` re-homes collisions (SIMD/FMOV/FSCA/SUBC set, `movi20s` notation, `rts/n` reserve), regen toolchain. | docs + jcore-cpu + binutils-gdb | **Sonnet** (entry/regen) + **Opus** (collision adjudication) | Opus spec + code |
| B1 | Contradiction worklist — one canonical answer each + doc fixes + CI check. Split by difficulty: **Opus** for load-bearing (L2 write-through vs write-back/MSI, VIPT vs PIPT L1, TSBBR VA/PA, EXPEVT codes); **Sonnet** for mechanical (endianness, "J4" naming, CPUINFO addr, `rte` uop count). | docs | **Opus/Sonnet** per item | Opus design-review |
| B2 | SH-4-as-KVM-guest model + emulation-fidelity matrix (each review finding → emulated / native-must-decode / unsupported). | docs | **Opus** | Opus design-review |
| B3 | Roadmap reframe (FPGA vs ASIC deliverables) + the OoO-vs-FGMT model over real traces (burden-of-proof on OoO). | docs + model | **Opus** | Opus design-review |

### Wave 3 — Security remediation (each item: minimize-loss design → implement)

Each C-item is a design task (Opus, using the §E.10 low-overhead recipe + its
D.3 confirmation) followed by an implementation task (model per mechanics). Only
dispatch the implementer after the design-review is green and the perf/energy
minimize-loss step is settled.

| # | Task | Repo(s) | Design | Implement |
|---|---|---|---|---|
| C1a | SQ buffer residue scrub + defined-safe guest reads. | docs → jcore-cpu | Opus | Opus |
| C1b | Eager (across-tenant) FP/SIMD switch + register scrub; 2-bit dirty tracking; movmu-style bulk save. | docs → jcore-cpu + linux | Opus | Opus |
| C1c | Vertical-FP-SIMD FPSCR ownership fix + kernel-fpu discipline. | docs → linux | Opus | Sonnet |
| C2a | GPU memory protection (base+bounds or IOMMU/BMID) — launch blocker before user shaders. | docs → jcore-cpu | Opus | Opus |
| C2b | Speculation: delay-on-miss + frontend coverage (commit-time predictor updates, tenant-tagged BTB, degenerate-STT taint, delayed spec TLB/PTW). | docs → jcore-cpu | Opus | Opus |
| C2c | FGMT single-tenant-core + fence.t-style microreset on realloc. | docs → jcore-cpu | Opus | Opus |
| C2d | IOMMU default-deny + per-device block + no global-match IOTLB + coherent-DMA owner. | docs → jcore-cpu + jcore-soc + linux | Opus | Opus |
| C2e | Cache isolation beyond ways (DAWG-semantics metadata + MSHR reservation + bandwidth QoS + per-tenant KSM + privileged flush ops). | docs → jcore-cpu + linux | Opus | Opus |

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
