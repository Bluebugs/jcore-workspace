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
| C2b | Speculation: delay-on-miss + frontend coverage (commit-time predictor updates, tenant-tagged BTB, degenerate-STT taint, delayed spec TLB/PTW). **Design DONE 2026-09-09** — [mmu/hardware-spec.md §5.0a](mmu/hardware-spec.md) W-R1–W-R5, [ooo/j32ooo-spec.md §8.2a, §11.1a](ooo/j32ooo-spec.md), [ooo/j32lt-spec.md §7.4a, §7.5a](ooo/j32lt-spec.md), [security/threat-model.md §7.2, §7.3, §8 L4, §10](security/threat-model.md). **Three of the four named mechanisms target structures no repository contains and were already specified; the implementation half is dispatchable in part, and it is the first Wave-3 row of which that is true** — see below. | docs → jcore-cpu | Opus | Opus |
| C2c | FGMT single-tenant-core + microreset on realloc. **Design DONE 2026-09-09** — [hypervisor/hardware-spec.md §2.10, §2.11, §4.7.1a, §4.7.2, §4.7.3](hypervisor/hardware-spec.md), [security/threat-model.md §8 L1](security/threat-model.md). **The row's mechanism name is post-2006 and had to be replaced, its figures were nobody's, and the implementation half is not dispatchable in any repo** — see below. | docs → jcore-cpu | Opus | *blocked on FGMT and a hypervisor existing* |
| C2d | IOMMU default-deny + per-device block + no global-match IOTLB + coherent-DMA owner. **Design DONE 2026-09-09** — [iommu/hardware-spec.md §3.10](iommu/hardware-spec.md) `I-R1`–`I-R10` and §10.1 `I-E0`–`I-E6`, [iommu/security-review.md](iommu/security-review.md) (commissioned by this task; it did not exist), [decisions/0010](decisions/0010-dma-coherence-is-software-maintained.md), [security/threat-model.md §7.7a, §8 L2](security/threat-model.md). **The per-device block state already existed on both sides of the interface, the coherent-DMA entry is wrong about every noun, and the implementation half is not dispatchable in any of the three repos** — see below. | docs → jcore-cpu + jcore-soc + linux | Opus | *blocked on a BMID-carrying bus and a DMA master existing* |
| C2e | Cache isolation beyond ways (DAWG-semantics metadata + MSHR reservation + bandwidth QoS + per-tenant KSM + privileged flush ops). **Design DONE 2026-09-09** — [cache/l2-spec.md §16.2](cache/l2-spec.md) [`P-R1`–`P-R8`](cache/l2-spec.md), §16.3, §16.4 `P-E1`–`P-E5`, §22.1b, [hypervisor/design-spec.md §6.2](hypervisor/design-spec.md), [security/threat-model.md §7.6a, §8 L5, §8 L6](security/threat-model.md). **The named mechanism has no pre-2006 grounding and was re-derived rather than adopted, one of the five was asked about the wrong object, one was already discharged by a section that existed, and the implementation half is not dispatchable in either repo** — see below. | docs → jcore-cpu + linux | Opus | *blocked on an L2 existing* |

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

**C2b reverses this row too, and it reverses it in the opposite direction from C1a, C1b, C1c and
C2a.** Those four found that the hardware their fix names does not exist. C2b found that *some of
its hardware ships* — and that the row's own list of mechanisms points almost entirely at the half
that does not.

*First, the split, which is the design's spine.* **Commit-time predictor updates**,
a **tenant-tagged BTB** and **degenerate-STT taint** are three of the four named mechanisms, and
all three describe structures `jcore-cpu@origin/master` does not contain: a case-insensitive search
for `branch_pred`, `btb`, `bimodal`, `gshare`, `ras` or `predictor` returns a handful of hits and
**not one of them is a predictor or any RTL logic**: two comments calling the I→D shadow fill "a
strong predictor of an imminent D-side access", one forward-looking sentence in
`docs/pmu/perf-counters.md` about a front end that has not arrived, a `return_addr` field in two
tests' control blocks, and `RAS & CAS & WE` in `testrom/main.c` — the closest thing in the core is the decoder's
one-cycle ROM read-ahead, checked and squashed in the same cycle. All three are also **already
specified**, for the design points [decisions/0009](decisions/0009-in-order-fgmt-is-the-default-path.md)
paused: [ooo/j32ooo-spec.md §3.2](ooo/j32ooo-spec.md) already trains every predictor structure at
commit only from a domain captured at rename, already tags the BTB with the full domain field —
which is *wider* than the 2–3-bit ARM-CSV2 shape §E.10 recommends, not narrower — and §9.4 rule 3
is already the degenerate taint. C2b added no clause to any of them. The fourth mechanism,
**delayed speculative TLB/PTW fill**, is the entire live workstream, and
[mmu/hardware-spec.md §5.0a](mmu/hardware-spec.md) is where it lands. A wave that had worked the
list in order would have produced a defence for a paused path and left the shipping arm exactly
where the bar's own status line said it was.

*Second, two of the row's transmitters do not exist and two it does not name do.*
[j4-remediation-plan.md §C2](j4-remediation-plan.md) states the surface as "wrong-path fetch **+
the always-on I-prefetcher** fill **the shared L2**". Neither of the emphasised structures is in
`jcore-cpu@origin/master`: there is no L2 at all — no second-level entity, and a case-insensitive
search for `mshr` returns nothing repository-wide — and the only `prefetch` token in the L1-I RTL
is a one-bit half-word indicator inside a 32-bit RAM read, while the optional `prefetch` unit the
testbenches reference has no entity anywhere in the tree and is off by default. Both are properties
of [ooo/j32ooo-spec.md §11](ooo/j32ooo-spec.md), where the rule for them now is. What the shipping
core *does* have, and the plan does not name, is the **ITLB install** and the **speculative DTLB
install** that a squashed fetch's walk performs — two of the four transmitters §5.0a enumerates.

*Third, the pLRU contradiction is real, is in the place the plan implies it is not, and is not the
pLRU channel the plan mentions two bullets later.* There is no pLRU in RTL — a case-insensitive
search for `plru` or `pseudo-lru` over `jcore-cpu@origin/master` returns zero matches, and the
shipping L1-I and L1-D are **direct-mapped** — so it can only be a specification defect, and it is:
[ooo/j32ooo-spec.md §8.2a](ooo/j32ooo-spec.md) said in one bullet that speculative L1-D hits
proceed at full speed and in the bullet after it that no load which fails to commit updates
replacement state, over L1s the same document makes pseudo-LRU. It is **not** the pLRU channel
named under *Cache partition honesty* in the same §C2 — that one is a victim's architectural hit
crossing an L2 way partition, belongs to **L5** and **C2e**, and the two share a word rather than a
mechanism. Filing them together would have handed C2e's work to C2b and left the self-contradiction
unresolved.

*Fourth, §E's menu, and the one place it has nothing.* The defence is §E.10's **delayed speculative
TLB/PTW fill**, taken as a dispatch dependence on the walk arm. The alternative on the table —
an abort path in `core/tlb_walk.vhd` — loses for a structural reason, not a cost one: by the time a
squash can be signalled the walk has issued its TSB reads, and those reads are §7.1's whole
observable, so the abort closes the two installs and leaves the channel. Value prediction is
skipped, as §E.10 directs. **MuonTrap-style filter caches and speculative fill buffers are refused
twice over** — §E.10's *don't build* list and [ooo/j32ooo-spec.md §20.7](ooo/j32ooo-spec.md)
rejection 1 — which is why the L1-I wrong-path fill is recorded as an accepted residual rather than
closed. And §E.10 has **no line at all** for the one mechanism that would close the speculative-hit
metadata channel: its replacement-metadata entry prices DAWG, which partitions metadata between
tenants and does nothing about a squashed path inside one. Nothing was borrowed to stand in for it,
on [decisions/0005](decisions/0005-unmeasured-figures-are-removed.md)'s grounds, and the decision
was left with the design point that would build it.

**The implementation half is dispatchable in part — the first time in Wave 3 — and the row's
`docs → jcore-cpu` is right for once.** Two pieces can be dispatched now. (a) `jcore-cpu/docs/architecture/tlb.md`
§7 needs correcting; [security/threat-model.md §11](security/threat-model.md) has owned that row
since C0 and it needs no hardware, only the repository. It has also grown: the same sentence claims
"no prefetcher" and "no data/target speculation" while **§4.1 of that same file calls the I→D
shadow fill a "speculative install" in four places**, so the document contradicts itself across two
sections. (b) The [mmu/hardware-spec.md §5.0a](mmu/hardware-spec.md) **W-R1** gate itself is real RTL against hardware that exists — a dispatch term on
`walk_i_miss` in `core/cpu.vhd`, plus the counter **W-E1** describes, which is what makes the
non-vacuity clause of **L4** dischargeable for this transmitter at all. What is *not* dispatchable
is everything in [ooo/j32ooo-spec.md §11.1a](ooo/j32ooo-spec.md) and the paused specs' rules: no
predictor, no prefetcher and no L2 exist to write them against, and [decisions/0009](decisions/0009-in-order-fgmt-is-the-default-path.md)
D2 stops RTL being written against those specs regardless.

**L4 does not move.** It stays `NOT MET`, and the reason it stays unmet is different in kind from
L2, L3 and L6: those three wait for hardware to be built, and L4's transmitters are on
`origin/master` today. Nothing in Wave 3 has moved a bar item to `MET`, and this row does not
either.

**C2c reverses this row four times, and the first reversal is the row's own title.**

1. **`fence.t` is 2020 work and cannot be this project's mechanism name.**
   [glossary.md §2](glossary.md) is a hard requirement: a technology with no pre-2006 prior art is
   either adapted from a pre-2006 equivalent or dropped. `fence.t` — Wistoff, Schneider, Gürkaynak,
   Benini and Heiser, *Prevention of Microarchitectural Covert Channels on an Open-Source 64-bit
   RISC-V Core* (2020), and its DATE 2021 successor — appeared **four** times across this plan and
   [j4-remediation-plan.md §E.10](j4-remediation-plan.md) with figures attached and **no prior-art
   section anywhere**. Escape (a) applies: the mechanism is pre-2006 at three levels — TCSEC object
   reuse (DoD 5200.28-STD, 1985) for the rule, Hu 1992 (*Lattice scheduling and covert channels*,
   IEEE S&P, pp. 52–61) for closing the cache channel at a switch of security class, and SH-4
   `CCR.ICI`/`CCR.OCI` (1998) for the control shape — so it is kept, renamed **microreset**, and
   grounded in [hypervisor/hardware-spec.md §4.7.1a](hypervisor/hardware-spec.md). One of the two
   candidate citations this task was handed did **not** survive checking: Hu's *Reducing timing
   channels with fuzzy time* (1991) is clock fuzzing, not state clearing.

2. **The figures attached to it are not this design's and two of them are not the cited paper's
   either.** §E.10 carried "<1% perf", "0.13% area", "~21,755 cycles" and "a ~16-cycle reset".
   Wistoff et al. 2020 report **320 cycles** on Ariane, of which **256** are the write-through
   invalidate at one set per cycle, and "the number of deployed LUTs remains within 1% of the
   original size" on **FPGA**. All four numbers are removed rather than annotated
   ([decisions/0005](decisions/0005-unmeasured-figures-are-removed.md)) and none is reproduced in
   any spec — C2a's precedent, applied to the item C2a was declining to borrow from.
   [security/threat-model.md §9](security/threat-model.md) had already listed the area figure as
   `LITERATURE`, with "ECP5 synthesis of the microreset, **under C2c**" as its discharge; C2c
   cannot discharge it, and that cell now says so.

3. **The item's flush half named a structure that means two different things.**
   [security/threat-model.md §8](security/threat-model.md) **L1** requires the gang switch to flush
   "MSHRs". The L2's pool is shared across banks *and cores*
   ([cache/l2-spec.md §12.3](cache/l2-spec.md)), so no core-granular gang switch can ever reach it
   — that word was **L5**'s all along. The core's own pool
   ([ooo/j32lt-spec.md §7.4](ooo/j32lt-spec.md)) is L1's, is partitioned per *thread* rather than
   per *tenant*, and had no item on the list. Asking *which structures had no software-visible
   control to be reached through* — rather than which structures leak — found three more in the
   same position: L1/TLB replacement state, the FGMT thread-select state, and the write buffer
   below a write-through L1-D. They are item 9 now, and
   [hypervisor/hardware-spec.md §4.7.1](hypervisor/hardware-spec.md)'s list is **10** items.

4. **The detector exists and the obvious design for it was wrong twice.** It sits on a **new**
   register rather than on `PDID`, because `PDID` is optional
   ([hypervisor/hardware-spec.md §2.8](hypervisor/hardware-spec.md): not required on in-order
   cores) and would therefore be absent on exactly the path
   [decisions/0009](decisions/0009-in-order-fgmt-is-the-default-path.md) made the default — and
   because `PDID`'s privilege was stated three incompatible ways, one of which let a **guest**
   write it. And it **refuses** the `HRTE` rather than trapping it, because
   [hypervisor/hardware-spec.md §4.1](hypervisor/hardware-spec.md)'s trap path at `SR.HPRIV = 1`
   overwrites `HSPC`/`HSSR` — the guest resume state the refused entry needs in order to retry.
   That also saves an `EXPEVT` code point and an `HEDR` bit.

**The implementation half is not dispatchable in any repo, and this row's `Implement Opus` is
wrong as written.** `jcore-cpu@origin/master` has **no FGMT** — case-insensitive searches for
`fgmt`, `thread_id` and `multithread` over `*.vhd`/`*.vhm` return nothing, and `barrel` returns
only `core/shifter.vhd`, `core/shifter_seq.vhd` and `tests/shifter_seq_tap.vhd`, which are the
barrel *shifter* — and **no hypervisor**: `hpriv`, `hcall`, `hrte`, `vbr_hyp`, `pdid` and `hedr`
all return nothing over the same files. Without a second thread context there is no violating
placement to refuse, and without `HRTE` there is nothing to refuse it at; without either there is
nothing to microreset. Unlike C2a's GPU, though, the missing hardware is **not** a parked program:
[decisions/0009](decisions/0009-in-order-fgmt-is-the-default-path.md) makes 2-thread switch-on-miss
FGMT the project's default microarchitecture, so C2c's rules land inside whatever task first builds
it, exactly as C1a's do inside the store-queue task. Naming that dependency is the deliverable.

**L1 does not move.** It stays `NOT MET`. Both of its open halves are now *specified and unbuilt*:
the detector ([hypervisor/hardware-spec.md §4.7.2](hypervisor/hardware-spec.md) T-R1–T-R5) and the
per-structure residue tests (§4.7.3 T-E3). C2c did settle the scoping question C2a filed against
L1 — an SM **is** a core for L1, so a two-tenant SM is out of bounds at launch independently of
C2a's windows, and the SM's own L1-equivalent detector becomes an entry condition on un-parking the
GPU program rather than a launch blocker. Nothing in Wave 3 has moved a bar item to `MET`, and this
row does not either.

**C2d reverses this row five times, and the eight-item worklist splits three ways.**

| # | Worklist item | Outcome |
|---|---|---|
| 1 | per-BMID deny/block state | **Already present, on both sides.** [security/threat-model.md §7.7](security/threat-model.md)'s sharpening survives checking — a BMID with its bypass bit clear and no matching entry already blocks, latches a fault and raises an IRQ. And the *kernel* half was already there too, which nobody had said: `IOMMU_DOMAIN_BLOCKED`, `blocked_domain` and `release_domain` all exist in `include/linux/iommu.h` at `linux@origin/jcore`. **No new state machine on either side** |
| 2 | reset = deny, or a locked bypass window | **Specified: hard deny.** The window alternative is *rejected with a derived reason*, below |
| 3 | write-once lock on `SUPER_BYPASS` | **Specified, and widened.** `ENABLE` needed the same treatment and nobody had asked |
| 4 | guard the `GLOBAL` IOTLB bit | **Reversed to removal.** The grant is deleted; the bit becomes a fault term |
| 5 | detach/teardown re-protection | **Specified — and the existing text specified the opposite direction** |
| 6 | quota the shared IOTLB | **Specified**, with a channel sharper than the one it was assumed to close |
| 7 | commission the IOMMU security review | **Delivered**: [iommu/security-review.md](iommu/security-review.md), 5 critical / 8 important / 7 minor spec findings and 5 implementation-prerequisite findings |
| 8 | own coherent-DMA vs the write-back L2 | **Reversed.** Every noun in the entry is wrong, and the useful fact is one nobody had recorded |

1. **The reset decision is hard deny, and the argument for it is not the bar's.**
   [security/threat-model.md §8](security/threat-model.md) had already ratified
   block-all-at-reset; what C2d owes is why the *alternative* the plan offered — "a
   documented brief bypass window that locks after handoff" — is not available.
   **It is not available because the handoff event does not exist.** A window that
   locks needs hardware to observe handoff, and the only fabric-visible boot
   transition ([bus/fabric-spec.md §9.2](bus/fabric-spec.md)) is the SMP release
   register at `0xFF00FF00` — a different block, and never written at all on a
   single-core part. A window that locks on a *software* command is a rule with no
   detector, which is the failure C1c and C2c both filed. Hard deny needs no event.
   Two further arguments are derived rather than inherited: the kernel's OF path
   **fails open** by design (`of_dma_configure_id()` swallows `of_iommu_configure()`'s
   `-ENODEV` under a comment reading *"we'll just carry on without it"* and configures
   raw `dma-direct`), so an un-annotated device is unprotected no matter how careful
   the driver is; and default-deny converts this document's own bugs from silent-open
   to loud-closed — `iommu/linux-spec.md` §5.4's bypass-bitmap arithmetic indexed the
   register by `bmid / 8` and the bit by `bmid % 32`, which under all-bypass reset
   unprotects the attaching device *and* faults an innocent one.

2. **`GLOBAL` is removed rather than guarded, and S-I7's shape is why the narrower
   answer is not available.** [mmu/security-review.md §2](mmu/security-review.md)
   **S-I7** resolved by making a *combination* fault — `G=1 && U=1` — which left the
   legitimate global kernel page alone. The IOMMU has no `U` bit and no per-entry
   marker of who is untrusted, so there is no combination to make fault; and
   restricting `GLOBAL` to read-only would not help, because a globally *readable*
   buffer is already cross-tenant disclosure once two tenants own devices. What made
   removal free is a fact in `iommu/linux-spec.md` §5.2 that nobody had connected to
   it: `.map` already loops `for_each_set_bit(bmid, domain->bmids, …)`, so a *k*-way
   shared buffer is already expressed as *k* entries that **name their sharers**.
   S-I7's shape is kept where it counts — a hardware term at lookup plus a named guard
   ([iommu/hardware-spec.md §3.10](iommu/hardware-spec.md) `I-R5`, `I-E4`), not a rule
   telling software not to set the bit.

3. **Three mechanisms the specs relied on exist in no repository, and the first of
   them hangs the machine.** `iommu/hardware-spec.md` §2.2 told an implementer to
   return `SLVERR` and *"suppress the data phase"*; `jcore-cpu:cpu2j0_pkg.vhd`'s
   response record is `{ d, ack }` and carries **no error field**, so suppressing the
   data phase means never asserting `ack` — a permanent stall of the master and, behind
   `bus_mux_typec.vhm`'s fixed-priority arbiter, of everything queued behind it. Under
   default-deny that is the *default* path. `IOMMU_CTRL.DEFAULT_PERM` applied a
   permission on the bypass path, which has no permission check (C1c's shape, in a
   register field). And §7's coherency guarantee delegated to a fabric whose snoop bus
   has one originator, the L2, and one class of destination, CPU L1-D ports.

4. **Two defects nobody had listed, found by asking who can write each control.**
   [bus/fabric-spec.md §4.3](bus/fabric-spec.md) made BMID `0xFF` a **permanent**
   bypass and — unlike `0x00` — stated **no rule** forbidding the fabric from assigning
   it to a master port: one integration decision from a master with unconditional
   physical DMA, on a path a board's JTAG connector makes physically reachable. And
   `HCALL_HV_IOMMU_MAP(iova, ra, perms, bmid)`
   ([hypervisor/design-spec.md §4.6](hypervisor/design-spec.md)) takes **`bmid` from
   the guest**, with no stated validation — the one IOMMU control delegated to the
   adversary, and C1b's lesson arriving at a hypercall argument. Every other control is
   MMIO the guest cannot reach, because
   [hypervisor/hardware-spec.md §4.4.3](hypervisor/hardware-spec.md) traps P4
   fail-closed; that check is a strength, and it is in a different document from the one
   that needed it. Counting the ways to memory rather than the ways to leak gives
   **7** bypass paths ([iommu/hardware-spec.md §3.10](iommu/hardware-spec.md)), of which
   six are closed and the seventh — a master with a private path, `flash_boot_reader`'s
   SPRAM port — is named because no register can reach it.

5. **The coherent-DMA entry is wrong about every noun, and the useful fact is the
   opposite of the one it states.** *"The L2 exposes no fabric snoop port today"*:
   there is **no L2** in either repository — every `l2` token in VHDL is a `textio`
   variable, an FPGA ball name, or a comment about the *TLB*'s second tier. The
   write-back cache that creates the hazard is the **L1-D** at `[T1/T2]`
   ([decisions/0007](decisions/0007-l1d-write-policy-under-msi.md)), not the L2, whose
   own policy was never in dispute. And **a snoop port does exist today** — on the
   L1-D: `cache_pkg.vhd:467-470`'s `dcache_snoop_io_t` is `{ al, en }`, it is a real
   external port, an incoming address clears the matching line's valid bit, it is
   cross-wired CPU↔CPU in the two-CPU build, and it is tied to `NULL_SNOOP_IO`
   everywhere else with `dma_dbus_o` connected to none of it. So the accurate statement
   is that the hardware a DMA write needs in order to invalidate a stale CPU line is
   present, invalidate-only, and one wire from the DMA leg of the DDR mux.
   [decisions/0010](decisions/0010-dma-coherence-is-software-maintained.md) names the
   wire, and finds the software half worse than
   [0007](decisions/0007-l1d-write-policy-under-msi.md) assumed: the J4 Linux build
   compiles **no** cache-operations file at all — `cacheops-` keys on `CPU_J2` and
   `jcore_defconfig` sets `CPU_SUBTYPE_JCORE`, which selects `CPU_JCORE` → `CPU_SH2` —
   so `__flush_wback_region`, `__flush_purge_region` and `__flush_invalidate_region`
   all stay at `noop__flush_region` and every DMA cache-maintenance call on J4 is a
   no-op. That is the one C2d finding reachable on hardware that exists today.

**The implementation half is not dispatchable in any of the three repos, and this
row's `Implement Opus` is wrong as written — but the reason is a step larger than the
IOMMU.** `jcore-cpu@origin/master` and `jcore-soc@origin/master` contain no IOMMU, no
IOTLB and no BMID (case-insensitive over *all* files: zero matches in both), and
`linux@origin/jcore` has no `jcore` file in `drivers/iommu`. That is C2a's and C2c's
position. What is new is the **prerequisite**: the J-Core bus carries no master
identifier of any kind. `cpu2j0_pkg.vhd`'s `cpu_data_o_t` is `{ en, a, rd, wr, we, d }`
and the DDR mux tells its five masters apart by *port position*, recorded in a comment.
There is no field to put a BMID in, and widening the bus record touches every master
and slave in both repositories. There is also nothing to protect yet:
`components/dma/` is a stub with a `README` and no entity, `dma_dbus_o` is tied to a
constant zero on all four boards, and every peripheral including the Ethernet MAC is a
bus **slave**. Unlike C2a's GPU this is not a parked program —
[bus/fabric-spec.md §0](bus/fabric-spec.md) already calls BMID tagging the T0→T1 step —
so C2d's rules land inside whatever task first builds a T1 fabric. Naming that
dependency, and its size, is the deliverable.

**One thing *is* dispatchable, in `linux`, today**, and it is the exception to the
paragraph above: [decisions/0010](decisions/0010-dma-coherence-is-software-maintained.md)
decision 4 — a `cacheops-` arm for `CPU_JCORE`, real `__flush_*_region` implementations
against the J-Core CCR that `cache-j2.c` already reaches through `j2_ccr_base`, and
`ARCH_HAS_SYNC_DMA_FOR_CPU`. It needs no IOMMU and no DMA master; it is a correctness
bug waiting for one.

**L2 does not move.** It stays `NOT MET`, with every clause now *specified and
unbuilt*, and with a second status that must be recorded rather than skipped:
[security/threat-model.md §8](security/threat-model.md) makes L2 a launch blocker only
for a configuration with a tenant-influenced DMA master, and there is no DMA master at
all, so the item's **blocker** condition is `N/A` today. `N/A`-as-blocker is not `MET`.
Nothing in Wave 3 has moved a bar item to `MET`, and this row does not either.

**C2e reverses this row twice, and closes the last of L6's three `undefined` sites without
moving L6.** Wave 3's last item, and the pattern of the wave holds to the end.

*First, `DAWG` is post-2006 and there is no pre-2006 grounding for it anywhere in the tree.* That
is C2c's `fence.t` problem, and it took C2c's treatment: the name is not used for any mechanism in
[cache/l2-spec.md](cache/l2-spec.md), the rules were re-derived, and each was grounded at source.
The grounding turned out to be better than expected. **MIT CSAIL Memo 430** (Chiou, Jain, Devadas
& Rudolph, November 1999; published as DAC 2000) contains the metadata rule verbatim — *"not
update the LRU state of a cache-line that is caching data not currently mapped to the column it
resides in"* — reached for a repartitioning reason rather than a security one, which is
[glossary.md §2.1](glossary.md) rule 1's case exactly. **US6370622** (Chiou & Ang, MIT, filed
1998-11-20, *Expired — Fee Related*) supplies the per-column allocation mask and per-region
replacement policy but **not** per-partition replacement *state*, which is stated as the boundary
rather than glossed. **IACR ePrint 2005/280** (D. Page, submitted 2005-08-25) supplies partitioning
for a *security* purpose pre-2006, and supplies the privilege argument for cache-management
instructions in its own words. What J-Core specifies is not DAWG's mechanism either: DAWG
replicates metadata per domain and isolates hits; [`P-R2`](cache/l2-spec.md) keeps one tree,
confines updates within it, and keeps hits unrestricted. A search for a patent tied to DAWG found none — a search result,
not an opinion.

*Second, the row's fifth mechanism is asked about the wrong object, and the object that is wrong
is one the row does not mention.* "Privileged flush ops" reads on
[j4-remediation-plan.md §C2](j4-remediation-plan.md)'s "user-mode `ocbi`/`ocbp`/`pref` — a
Flush+Reload primitive across the partition". [cache/l2-spec.md §17.5](cache/l2-spec.md)'s own
table says of `ocbi` that "the L2 copy, if any, is unaffected", and `ocbp` and `ocbwb` touch only
the issuing core's copy and its directory bit: **none of the three evicts from the L2**, so none
is a flush primitive against an L2 way partition. `pref` and `movca.l` do reach the L2, by
*allocating*, and allocation was already confined by §16.1 — so that half was **already
discharged** by a section written a month earlier, which is C2d's lesson repeating. The decision
is that the three stay user-mode. What *is* ungated is a register: `cache/icache_modereg.vhm`
decodes core 1's whole-cache invalidate bits and an IPI to core 1 in one word, and
`jcore-soc@origin/master` places it at `0xabcd00c0` ([cache/l2-spec.md §16.2](cache/l2-spec.md)), **outside P4**, so its protection is a
stage-2 mapping policy rather than a privilege level. That is shipping RTL, not a paused spec.

*Third, four of the ten residual channels are `accepted`, and two of the four were on no list.*
The row asks for mechanisms; the [j4-remediation-plan.md §C2](j4-remediation-plan.md) worklist
asks, correctly, for the opposite — that a claim be **narrowed**. [cache/l2-spec.md §16.3](cache/l2-spec.md)
does both, and the two new entries are cross-domain **MSHR coalescing** on a shared line (it
survives per-domain reservation, because it is about sharing an entry rather than occupying one)
and the **inclusion recall** of a shared line (a shared line lives in one way, so one domain's
allocation pressure evicts it and the *other* domain's L1-D copy is recalled). Both were found by
asking C2c's question — which shared structures have no per-domain control at all — of a
different structure.

**The implementation half is not dispatchable in either repo, and this is the fourth Wave-3 row of
which that is true.** There is no L2: every case-insensitive `l2` match in
`jcore-cpu@origin/master` or `jcore-soc@origin/master` is a textio variable in a `dcache_tb`, an
FPGA ball name `"L2"` in a `pad_ring.vhd`, a TLB comment, or prose — and
`jcore-cpu/docs/architecture/cpu-variants.md` says so itself, "Future — not yet implemented". The
`linux` half is thinner than the row implies: "per-tenant KSM" is not a thing to build, because
KSM merges across every opted-in `mm` system-wide with the NUMA node as its only partitioning
axis, so the deliverable is a **policy** — KSM off in the host — plus the clause that says turning
it off does not remove cross-tenant shared memory.

**Neither L5 nor L6 moves.** L5 is `NOT MET` with all five mechanisms specified and none built;
two of the five are narrower than the row's wording, and [`P-R5`](cache/l2-spec.md) is a measured *bound* rather than
a closure. L6 goes from one open `undefined` site to **zero** and stays `NOT MET`, because its
evidence bar is a residue test per site demonstrated **red before the fix** and there is no store
queue, no FPU, no SIMD unit, no GPU and no L2 to run one on. Zero open sites completes the
*specification* half of L6 and nothing else. **Nothing in Wave 3 has moved a bar item to `MET`,
and this row, which is Wave 3's last, does not either.**

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
