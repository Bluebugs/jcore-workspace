# Wave 0 execution status

Live tracker for the subagent-driven execution of Wave 0 (confirmed hotfixes).
Updated by the orchestrator as tasks progress.

## Environment findings (blocking constraint, discovered at kickoff)

- **GHDL and sh2-elf-gcc are NOT installed on this host.** Go, gcc, perl, and
  docker are. RTL guards (`sim/mmu_sim.sh`) and test-ROM builds therefore cannot
  run natively.
- The project publishes a heavy-toolchain image
  `ghcr.io/mountain-reverie/jcore-cpu-ci:latest` (used by `pr-quick.yml` /
  `full-regression.yml`). Manifest is **public and reachable**; the image is
  large and pulling in the background.
- **Consequence:** RTL tasks can be written but are only *verified* once the
  image lands. No task is marked complete on unverified claims — an implementer
  that cannot execute its guard must report DONE_WITH_CONCERNS, not DONE.
- Critical gotcha passed to every RTL subagent: the cosim MUST be built with
  `CPU_VARIANT=j4` or the MMU instructions silently vanish from the decoder and
  guards pass **vacuously** (documented in the header of `sim/mmu_sim.sh`).

## Worktrees (never main)

| Task | Worktree | Branch | Repo |
|---|---|---|---|
| A0 | `/home/cedric/work/jcore/wt-docs-a0` | `design/mmu-pagemask-contract` | superproject (docs) |
| A2 | `/home/cedric/work/jcore/wt-cpu-a2` | `fix/p4-privilege-gate` | jcore-cpu |

## Task status

| # | Task | Model | State |
|---|---|---|---|
| A0 | Page-mask codesign contract (design; gates A1) | Opus | `1063670` → **CLOSED** ✅ (6 commits, 4 review rounds) |
| A2 | P4 privilege gate + user-mode denial tests | Opus | `36d2672` → spec **PASSED** + quality **APPROVED** → **COMPLETE** ✅ |
| A2-docs | MMUFSR KIND 8/9, EXPEVT sharers, stale-claim fix | Sonnet | `f023bdd` → spot-checked ✅ |
| A1a | Canonical-4 KB TSB tag fix + Group-B guards | Opus | `09c5097`/`fd9ea76` → spec **PASSED** + quality **APPROVED** → **COMPLETE** ✅ |
| A0-amend | VA-backing rule, B4 ratification, P2 codes, Group-P | Opus | `1063670` → **APPROVED** ✅ — A1b/A1c unblocked |
| A1b | Huge-page pte-slot defect (K7 / A5) | Opus | `7531128f`/`f539647` → spec **PASSED** + quality **APPROVED** → **COMPLETE** ✅ |
| A4 | "Never identity-map the page under test" rule + suite survey | Opus | `6486fef` → **APPROVED → COMPLETE** ✅ (3 commits) |
| A1b | Huge-page pte-slot defect (A0 §1.1 / K7) | Opus | queued (split out of A1) |
| A1c | Group-C contract locks (C1–C5, C6g, C7g) | Opus | `6ec4645` → spec **PASSED** + quality **APPROVED** → **COMPLETE** ✅ |
| A3a+A3b | Warm-reset TLB flush; walker bus-takeover window | Opus | `3c39bed` → spec **PASSED** + quality **APPROVED** → **COMPLETE** ✅ |

## ✅ WAVE 0 COMPLETE — all nine tasks through two review gates each

Every task cleared spec-compliance **and** code-quality review, with reviewers
re-deriving results rather than confirming reports. Branches are ready for merge
review; two carry ordering constraints (see below).

## Merge train (updated 2026-08-25)

| PR | Repo → base | State | Blocked on |
|---|---|---|---|
| linux **#13** | linux → `jcore` | **MERGED** ✅ `3a08090` | — |
| linux **#14** | linux → `jcore` | `MERGEABLE / CLEAN` | review only |
| jcore-cpu **#179** | jcore-cpu → `master` | `MERGEABLE`, **CI red by design** | linux#14 |
| jcore-cpu **#181** | jcore-cpu → `master` | `MERGEABLE`, CI running | review only |

**The one hard ordering constraint: linux#14 merges before jcore-cpu#179.**

CI builds the Lane-2 harnesses against `mountain-reverie/linux` @ `jcore`, so
until #14 lands there, #179's guards run against a kernel without the fix they
exist to pin and correctly go red — `mmuhugefar` `Result=225` (its documented
pre-fix code) and `mmuhuge` `Result=99` (`unexpected_fault`). That red run is
the best non-vacuity evidence in the set: a real unfixed kernel, in CI, with
nothing mutated by hand to produce it.

The trap worth naming, because it is not obvious from the PR titles: **#179 also
corrects `mmuhuge`, and the corrected version now depends on the kernel fix as
well.** On `master` today `mmuhuge` passes against the unfixed `jcore`. Merging
#179 first would therefore turn the guards job red **on master**, not merely
leave it red on the PR.

### Method notes from the rebase round

- **A merge that resolves clean can still be wrong.** #14's conflict looked like
  one file but needed two resolutions, and the dangerous half was invisible to
  `git`: the old call site pre-indexed the pgd (`pgd += pgd_index(addr)`), while
  the new walker indexes internally, once per probed slot. Carrying the
  pre-increment through would have double-indexed the pgd — identical types, no
  warning, correct results for everything not crossing a directory boundary.
  Check the callee's body, not the hunk shape.
- **Registration-list conflicts are not all "keep both".** In `sim/tests/Makefile`
  the two blocks ended on a *shared* recipe line; concatenating them would have
  left `mmuhugefar.img` with no recipe. Two inventory comments had been rewritten
  on both sides, so neither was a superset.
- **A rebase can make a commit redundant rather than conflicting.** #179's
  "107/107 PASS" retraction was dropped because master had independently landed a
  stronger version of the same correction — after resolving in master's favour
  the commit was empty. The correction survives; only the commit is gone.
- **"On the current base" is a figure that rots.** `core/cpu.vhd` claimed the
  assertion moves the ASIC flop count `4483 → 4484` "on the current base"; two
  rebases had silently re-pointed what that named. Now pinned per base, with the
  +1 re-measured on `06a8148` (`4519 → 4520`) from `git archive` trees rather
  than adjusted. `core/tlb.vhd`'s table needed no such fix — it already names its
  base by SHA and scopes its ASIC numbers to itself. Worth copying that habit.

## Accepted decisions (recorded, not buried in code comments)

- **A2 one-shot exception — WAIVER ACCEPTED.** `dp_p4_viol` pulses for one cycle,
  so a concurrent I-fetch fault or a held older request can swallow the address
  error. **No leak and no escape** — the refusal is unconditional and independent
  of delivery. But the code-quality review refined this claim, and the refinement
  matters: the refusal writes `TEA` **unconditionally**, so when delivery is lost
  because `texc_req` already holds an older fault, that **older fault's TEA is
  overwritten by the refused P4 VA** and its handler reads the wrong address. So
  the worst case is not merely "a swallowed signal" — it is a swallowed signal
  plus a clobbered TEA on an unrelated pending fault. **The honest ceiling on
  this waiver is "confined to diagnosis", not "harmless":** a kernel debugging a
  page fault can be misled about which address faulted. No leak, no escape, no
  privilege gain — but the follow-up should close it rather than treat it as
  free. The follow-up is also not a small change: a held request additionally
  needs a *frozen restart context*, because `tlb_exc_pc` derives from the live
  `ex_if_pc` inside the shared capture block.
  A proper hold is not the ~6-line change it appears: `tlb_exc_pc` derives from
  the *live* `ex_if_pc` inside the shared capture block, so delaying the raise
  silently produces the wrong SPC; a correct hold must modify a block that
  `mmupcprobe`, `mmudspcprobe`, `mmurestartpc`, `mmuidorder` and `mmudrain` all
  depend on — a bigger blast radius than the security fix. A cheap partial fix
  (P4 arm priority over the I-fetch arm) was costed and **deliberately not
  shipped**, because no test creates the contention. **Follow-up's first
  deliverable must be a guard that creates it** (AT on, P4 access whose
  neighbouring fetch misses), red before the fix.
- **A2 EXPEVT `0x0C0` — deferred by choice, not hardware-forced.** The
  "immediate field at capacity 32/32" justification was **false** (30 of 32;
  `11110`/`11111` free; `IMM_P256 = 0x100` already exists, so only `0x0E0` would
  be new). Kept `0x0C0` + MMUFSR KIND discrimination because it is functionally
  adequate, but the label is now honest and the cheap path is recorded.
- **A2 user-mode I-fetch from P4 — deferred.** `i_at_translated` is '0' for P4,
  so a user I-fetch is unchecked. Not an escalation path (the P4 CSR block is
  datapath-only, so a fetch cannot reach a CSR). Same-class gap, tracked.
- **4 KB pages:** a 4 KB *Linux build* is out of scope (`BUILD_BUG_ON`), but
  **pm=0 remains supported hardware** and must stay covered in the RTL matrix.

## A2 — COMPLETE (both gates cleared, `36d2672` on `fix/p4-privilege-gate`)

Final state: guard `mmup4priv` proven red-then-green by the reviewer
independently; `PASS=105` (0 FAIL/SKIP) without `-n`; `vhdl-lint` 0 violations
across 84 hand-written `.vhd`; `verify-generated` clean; worktree clean.

**Synthesis QoR measured (was the one open risk):** yosys `asic` total cells,
branch point → final — j1 19765 → 19765 (**Δ0**), j2 22203 → 22187 (**Δ−16**,
decomposing `$not` −16 / `$and` +2 / `$or` −2, i.e. boolean-optimizer wash with
no structural addition). Measured twice, before and after the predicate
factoring, identical both times.

> **Caveat to carry forward:** the ±464 LUT4 band recorded at
> `datapath.vhm:236-241` is a **`synth_ecp5`/abc9 LUT4** figure, while
> `cpu_synth.sh asic` is generic yosys — different flow, different units, so
> "inside the ±464 band" is not literally a comparison. The asic run rules out
> the bigger risk (added structure); it does **not** exercise abc9 packing,
> which is the specific mechanism that note describes. `synth-cpu.yml`'s
> `synth-ecp5` job already runs j1/j2 through abc9 + nextpnr on every push and
> prints `TRELLIS_COMB` counts and Fmax. **Glance at those when the branch
> pushes; do not run nextpnr locally** (expensive on an 85F, and disk is tight).

**A mutation that cannot produce a result code — and why that is acceptable.**
Narrowing the gate to `p4_sel_v /= P4_NONE` does not merely let a reserved-offset
access succeed; it escapes the CPU onto the external bus
(`SRAM: invalid read addr: 0xFF000034` + bus-monitor ACK timeout). The guard
structurally *cannot* return a `Result=` code there: the access leaves via
`to_data_o`, the memory model rejects it, the bus never acks, no instruction
retires, so there is no path back to `_fail`. Demanding a numeric code would mean
demanding weaker RTL. `run_guard` reports PASS only on a literal "Test Passed"
(a wedge, stop-time expiry and wall timeout are all FAIL) and its diagnostic
greps `result|fail|invalid`, so the `SRAM: invalid read addr` line surfaces
directly. This is compatible with `CLAUDE.md`'s "own result code, not a timeout"
rule because the evidence is an addressed, causally unambiguous message naming an
address that exists in the image *only* because of the new table entry — the
timeout is the downstream consequence, not the evidence. What makes it honest is
that the guard header **leads** with the failure mode rather than leaving a
reader to discover a hang.

**Follow-ups tracked out of A2:** (1) the held-request fix for the one-shot
exception, whose first deliverable must be a guard that creates the contention;
(2) user-mode instruction fetch from P4 is still unchecked (not an escalation
path — the P4 CSR block is datapath-only); (3) `scripts/vhdl-lint.sh` exits 127
in the CI image because `bc` is absent and `set -e` kills it at the summary line
*after* the real result — fix the image or the script, since anyone running it
locally sees a failure that is not one.

## A1a findings that change the plan

**Lane 2 (real kernel objects) IS executable locally — the assumed blocker was
wrong.** `jcore-cpu/CLAUDE.md` says the Linux harnesses need kbuild objects "a
normal checkout does not have", and I briefed A1a to expect it might be
CI-only. In fact the CI container's `sh2-elf-*` toolchain **is** the J4 fork, so
pointing `LINUX_SRC` at the kernel worktree and running `sim/linux_sim.sh`
drives the real TLB-miss handler locally (~13 s/iteration after the first
build). **This unblocks decisive kernel-path verification for every remaining
MMU task** — A1b and A1c should be briefed to use it rather than settling for
Lane-1 evidence. Worth folding into `CLAUDE.md`, whose current wording sends
people the wrong way.

> ### ⚠ VACUOUS-VERIFICATION TRAP — brief every future agent on this
> The container has **no `bc` and no network**, so `apt-get install bc` fails and
> `sim/linux_sim.sh`'s kbuild dies at `include/generated/timeconst.h`. A
> subsequent `-n` run then **silently reuses whatever `.o` files are already in
> the linux worktree** — i.e. it "confirms" results without rebuilding anything.
> A1a's spec reviewer hit exactly this on its first attempt and would have
> ratified the result table against stale objects. The fix is to stage the host
> `bc` plus its loader/libs into the container and shim it onto `PATH`.
> (A1a reported "`bc` apt-installed per run", which cannot have worked as
> described; its results nevertheless stand, because the reviewer reproduced
> red-then-green with a genuine full rebuild after applying the shim.)
>
> Second setup fact: **`J4GAS`/`J4LD`/`J4OBJCOPY` must point at
> `/usr/local/bin/sh2-elf-{as,ld,objcopy}`** — the script's
> `../binutils-gdb/build-sh2/...` defaults do not exist in the image.
>
> **CORRECTION — the trap is NOT fixed, and I recorded that wrongly.** I credited
> A1a with hardening the runner; its code-quality reviewer checked directly and
> found `sim/linux_sim.sh` is **byte-identical** across A1a's commits, as are
> `sim/mmu_sim.sh`, `sim/tests/Makefile` and the CI workflow. No `bc` staging, no
> mtime printing, no new abort exists in any of the five commits. Separating what
> is actually true:
> - Abort-on-kbuild-failure **already existed** at `sim/linux_sim.sh:81`,
>   pre-dating this work — so the "kbuild dies on `bc`" half was already covered.
> - What A1a added is a **`NOTE ON -n` header block** documenting the remaining
>   hole: `-n` skips kbuild entirely and links whatever `.o` files exist, with no
>   freshness check. That is the actual trap, and a header note is the right
>   in-scope amount for a bugfix task.
> - The `bc`-staging wrapper each agent builds is **ephemeral** and helps nobody
>   downstream.
>
> **Follow-up to file:** put the container fix in the CI image or
> `.github/ci/README.md`, and if anything lands in `linux_sim.sh` make it a
> **freshness assertion on the `-n` path** (`.o` newer than `.c`), not `bc`
> plumbing. Not a condition of any current merge.

**A1a spec review — independently reproduced, not taken on trust.** The reviewer
re-ran the whole A/B itself in the container: reverted both fill sites, rebuilt
the real kernel objects, and got Results **225 / 228 / 229** at ~27/27/36 µs
(well inside the 200 µs stop-time, so genuine named failures rather than
timeouts), with `mmuhuge` and `mmulinux` staying **green on the unfixed kernel**
— direct proof the pre-existing Lane-2 coverage could never have caught this
defect. Green side rebuilt fully: all seven harnesses pass. Full Lane-1 suite:
`==> all guards PASSED`, zero FAIL lines. It also proved the RTL change is
comment-only *mechanically* (strip all comments from both revisions → identical)
rather than by reading the diff, and measured K3 both ways itself.

Non-vacuity holds on three independent axes: red-then-green with distinct codes;
a **bounded repeat-fault counter** in each guard's own `+0x400` vector shim
(FAULT_BOUND 8/8/10 against expected 3/1/4) so a livelock reports a code instead
of hanging; and an exact `TSBCNT.hits` delta with a separate `0xF0` arm for
`delta == 0` — which incidentally makes a dead `P4_TSBCNT` **fail** rather than
pass, retiring the need for a standalone counter-liveness guard.

Nice catch inside A1a's own work: `mmupmsubi.S:311-319` records that an earlier
revision used PC-relative literals inside the I-side stub — themselves D-side
accesses to the same VPN — and *measured* `cnt_hits` moving by 2. The stub now
takes everything in registers. That is precisely the vacuity class this project
warns is its default failure mode, found by measuring rather than reasoning.

**Newly measured cosim constraint (constrains A1c): every VA a guard translates
must ITSELF be a backed physical address.** During a walk the core holds the
request and withholds only the ack, so the raw VA reaches the bus, and the cosim
backs only 16 MB. VA `0x01802000` bus-errors where `0x00F02000` under an
identical mapping translates. Consequence: four mappings disjoint at 16 MB
granularity cannot fit, so **1 MB is the ceiling for a four-way residency case**
(A1a's B4 uses 256 KB with four distinct PageMasks, pm=1..4). This partially
conflicts with the A0 review's guidance that B3-s use "the furthest 4 KB
sub-page still inside the backed window" — the window constrains the *raw VA*,
not just the translated PA. **Pass to A1b/A1c; the A0 contract's B3-s/B9 specs
may need amending.** Pending independent confirmation in A1a's spec review.

**The fix itself is three lines of kernel code** — which is the payoff of A0's
reversal. Had the diagnosis stayed "fix the RTL", this would have been an RTL
change to a walker FSM instead.

## A0 amendments (`a685848`) — and a cross-guard vacuity trap worth remembering

**The VA-backing rule is now normative (P5)**, stated as a *VA* constraint and
explicitly superseding the earlier PA-framed guidance. A0 independently
corroborated that it binds on the instruction bus too, since the cosim backs
`[0, 0x1000000)` via **both** `mem_bus_stack_map` and `if_bus_stack_map`.

**A0 disagreed with one of my calls, and was right.** I told it B3-s slot 5
(16 MB) was probably unconstructible because such a mapping "excludes every other
mapping". A0 kept it, correctly: B3-s is **one mapping per guard instance**, so
there is nothing to exclude; it needs only the VA == PA identity treatment
`mmuhuge.S` already uses for pm=8, and the harness's own code/stack/TSB/page
tables live in P1, which `seg_decode()` routes untranslated. Dropping it would
have lost pm=6 coverage for no reason. **B9's 16 MB variant was dropped** —
there the objection *is* fatal, since B9 needs ~17 further mappings to force an
eviction — and replaced with **4 MB (pm=5) at VA `0x0040_0000`**, preserving a
genuinely large PageMask in an eviction case while leaving 12 MB for the working
set.

### ⚠ The Group-P retirement has a carve-out — a cross-guard dependency invisible at each guard's source

I asked A0 to retire the counter-liveness guards as redundant, reasoning that the
Group-B guards assert an exact `hits` delta with a `0xF0` arm for `delta == 0`,
so a dead `P4_TSBCNT` makes them **fail** rather than pass. A0 retired them but
flagged that this argument has a real hole:

> Several **Group-C** guards assert the counter did **NOT** move — C1, C4/C7g's
> no-further-fault checks, and the pre-existing `mmupage16k.S`, whose own header
> calls that counter "THE WITNESS". **A dead counter satisfies every one of those
> vacuously.** They are non-vacuous *only* because the Group-B guards
> independently prove an increment is possible on the same RTL.

That dependency does not appear in any individual guard's source, so it is the
kind of thing that silently rots.

**Resolved better than first stated.** The reviewer confirmed the vacuity with
exact evidence (`mmupage16k.S:166-167` snapshots the counter, `:190-194` does a
bare `cmp/eq` failing on a *difference* with no nonzero check — an all-zero
counter gives `r13 == r1 == 0` and passes), then improved the remedy twice.
First, my list was wrong: forcing it into a table showed **three** distinct
exposures, not two —

| guard | exposure |
|---|---|
| `mmupage16k.S` | **fully vacuous** — passes outright on a dead counter |
| C1 | **counter clause only** — its second clause is an independent positive witness, and C1's own mutation makes the walker *hit*, raising no exception |
| C4, C7g | **not exposed** — their no-further-fault checks use the guard's *own* P2 fault counter (guard-local memory), not `P4_TSBCNT` |

Second, the general remedy is **cheaper than reinstating a dedicated guard**:
*pair any non-increment assertion with an increment assertion in the same run.*
For C1 that is one line (assert `walks` moved while `hits` did not), after which
C1 leaves the dependency list entirely; the same one-liner on `mmupage16k.S`
retires the dependency altogether. A standalone counter-liveness guard (P1g) is
now the documented **fallback** for a guard that genuinely cannot witness an
increment of its own — not the first resort. The rule is sited at **three**
places (P1, the §7.2 preamble it amends, and §7.3's detail table) rather than
only where it was originally filed, because the people who trip it never open
that section.

Also recorded: the `0xE0|phase` scheme adopted as *specified* (A0 agreed its own
P2 was self-contradicting — it cited the "distinct failure IDs" rule and then
mandated one flat code); the `__update_tlb()` coverage gap named in §7.4; and the
environment hazards placed with the lane definitions, closing with "treat *Test
Passed* as evidence only after confirming the objects under test were rebuilt
from the working tree."

**Recommended follow-up (improvement, not correction):** pm=5 at VA
`0x00C0_0000` *is* constructible alongside B4's other three at one-per-4 MB
spacing, which would restore a large PageMask to a simultaneous-residency case.
Flagged as an improvement deliberately, so nobody churns a passing guard without
re-running its mutation proof.

## A1b — the huge-page defect is REAL, confirmed by simulation (`d119090`)

The one defect in this cluster that three reviewers reasoned about and **nobody
had ever run** is now reproduced. `sim/tests/mmuhugefar.S` (706 lines, four
phases: 64 KB / 1 MB / 16 MB / 256 MB) is the case `mmuhuge.S` structurally
cannot reach: it makes the touch **past the first `PAGE_SIZE`** the *first*
touch, with `MMUCR.TI` flushing between phases so no resident entry can mask the
empty slot — which is also the state a real kernel reaches once the huge entry is
evicted from the 16-entry DTLB.

Two findings from the reproduction matter more than the fix:

1. **`mmuhuge.S` has been testing a page-table shape Linux never creates.** It
   places huge ptes at `pte_index(VA_touched)`; the kernel's `huge_pte_alloc()`
   plus generic `set_pte_at()` produce `pte_index(huge-ALIGNED VA)`. A defect in
   the pre-existing guard, independent of K7 — to be filed separately.
2. **The approved contract was wrong about case B3'-s** — now corrected in
   `4532181`. It claimed a first touch at `VA_base+0x4000` fails for *both* the
   tag defect (K1) and K7. But `0x4000` has `VA[13:12] == 00`, so it **isolates
   K7 rather than compounding it**. A0 verified the arithmetic:

   | offset | `VA[13:12]` | past first 16 KB | tags equal | tests |
   |---|---|---|---|---|
   | `+0x1000` | 01 | no | **no** | K1 only |
   | `+0x4000` | 00 | yes | **yes** | K7 only |
   | `+0x5000` | 01 | yes | **no** | both |

   **A second-order consequence I had missed:** finding **A5's resolution
   criterion rested on the same mistaken premise.** It said "if B3'-s passes with
   only the K1 fix applied, then A5 is wrong and K7 can be dropped" — but the K1
   fix changes nothing at a 16 KB-aligned address, so **that test could never have
   discriminated**. A criterion that would have "proven" something it structurally
   could not test. A5 is now marked RESOLVED by A1b's simulation, with the flawed
   criterion recorded rather than quietly deleted. A0 added **B3''-s** at
   `+0x5000` as the genuinely compounding case, ordered *after* B3'-s and B1 so a
   red result stays attributable, and noted that B3'-s's isolation is a property
   to **preserve deliberately** — "improving" it by moving the offset to a
   non-base sub-page would silently make A1b's guard un-attributable.

Note the guard was deliberately built so every VA touched is 16 KB aligned,
making the A1a tag defect invisible to it — so its red/green state is a pure
function of the K7 fix, with no confounding.

### The K7 verification boundary — state it this way, it does not shrink cheaply

A1b implemented **both** shapes the contract names, arguing they are
complementary rather than alternatives, and the argument is strong:
*replication* (`__HAVE_ARCH_HUGE_SET_HUGE_PTE_AT`, slots carrying incrementing
PFNs) is **forced** because three generic-mm walkers index the pte table with raw
`PAGE_SIZE`-granular addresses and bypass `huge_pte_offset()` entirely
(`follow_pmd_mask()`, `gup_fast_pte_range()`, `folio_walk_start()` — whose own
kerneldoc says the entry "might not correspond to the first physical entry of a
logical hugetlb entry"); arm64 `PTE_CONT` and riscv NAPOT replicate for the same
reason. *Walker alignment* is then needed because with replication alone the
walker marks the **raw** slot accessed while `huge_ptep_get()` reads the **head**,
so a huge page would never be seen young — and recovering that the arm64 way costs
an OR-reduce of **16384 reads for a 256 MB page**. So alignment is what keeps
replication's cheap variant correct.

**What a green K7 result actually means:**

- **Exercised by a running test:** the *walker-alignment half only* — resolving a
  huge mapping from a sub-page past the first `PAGE_SIZE`, at four sizes, with
  exact `TSBCNT.hits` deltas, exact PTEL images, an exact walker-invocation delta,
  and a bounded repeat-fault counter. Plus no regression in `mmuhuge`,
  `mmulinux`, `mmulinuxexc`, `mmuboot`.
- **Exercised by nothing:** the *entire replication half* — GUP (fast and slow),
  `folio_walk_start`, teardown, fork/COW, `mprotect`, migration, uffd. Compile-
  verified and read only.

The boundary is **environmental**: it does **not** shrink by adding more
bare-metal guards, only when a kernel boots. Read a green K7 as "the walker
aligns correctly", never as "huge-page replication works".

A1b's own two self-review agents ran **without shell access** — they reviewed
content, not behaviour, and executed nothing. Their clean result is **not**
verification and does not narrow the boundary above by one line. (A1b said this
itself, unprompted.)

### Object-freshness proof worth imitating

A1b's strongest evidence that its A/B really rebuilt was accidental: its first
fix used a variable shift, which compiled to an out-of-line `__ashlsi3_r0` and
**failed the link**. A stale `.o` could not have produced that undefined
reference. (It then replaced the variable shift with a rolling mask — worth
keeping regardless, since an out-of-line call in the TLB-miss path is a real
cost.) Corroborated by the object changing size across all three variants
(1908 → 2020 → 1964 bytes).

## A4 — the identity-mapping rule, and the mistake I made accepting a correction

**The rule (new bullet in `jcore-cpu/CLAUDE.md`, "Writing a guard"):** never
identity-map the page under test. With `PA == VA` the access succeeds and returns
the right bytes whether the translation resolved, the entry never installed, the
walker never ran, or `MMUCR.AT` was off for the entire run — so green means
nothing, and identity is the easiest mapping to write. Where identity is
genuinely forced, the guard must carry an **independent witness** (a `P4_TSBCNT`
delta taken *across* the access under test, an asserted fault count or
`EXPEVT`/`MMUFSR`/`TEA`, the walker's PTEL image out of the TSB row, or a
PageMask-only effect) and say in its header why identity was unavoidable and
which witness covers it.

**Survey result: 8 exposed, 1 forced-and-compliant, 71 carried by a witness**
(85 files, 80 distinct guards — 5 are `#define`+`#include` shims). The reviewer
independently re-derived six of the eight accusations and five of the
clearances; **all eleven held.**

The three `mmupage*` guards are the instructive shape: they *do* read the walk
counter — so any grep- or keyword-based audit clears them — but the check is
**negative and taken after the install** ("the counter did not move again"), so
they stay fully green with the MMU inert. The guards that look compliant to
automation are exactly the vacuous ones.

### ⚠ My error: I accepted a correction that was verified against prose, not RTL

A4 reported that a blanket `PA != VA` rule could not work under the `cpu_tb` top,
because `mmu_o.*_pa_tag` is wired only to the caches. I accepted it and told the
user my original rule had been wrong. **It was not.** The review refuted it with
live RTL:

- Relocation happens **inside the core**, not in the testbench:
  `core/cpu.vhd:761-816` (`g_dstore_squash`, D-side) and `:822-847`
  (`g_inst_p1_fold`, I-side) splice the PPN into the external bus address, both
  under `if PRIV_ARCH generate`.
- `sim/cpu_tb.vhd:212-217` passes `PRIV_ARCH => true`, and `sim/mmu_sim.sh:54`
  **hard-fails the build** unless it is set.
- The `pa_tag` port exists only to give the PIPT caches ([mmu/hardware-spec.md §4.1a](mmu/hardware-spec.md)) their tag —
  `cache/dcache_ccl.vhm:255` says so: *"cpu.vhd relocates the address upstream of
  the cache, so a.a is already a PA."*
- **An existing passing guard settles it:** `sim/tests/mmuwalkdside.S` runs in
  `mmu_sim.sh`'s default `cpu_tb` loop, maps VA `0x42000`→PA `0x44000`, and
  asserts both that the stores landed at the **PAs** and that the VA-as-physical
  words still read `0x11111111`. Under the carve-out that guard could not pass.

Had it shipped, the rule would have told the authors of ~60 of 80 guards that
non-identity mapping proves nothing under their top — **a blanket exemption from
the rule it was stating.**

**Root cause, and the transferable lesson:** A4 "checked and agreed" with a
claim — but what it checked was **another guard's header comment**
(`mmuxlate.S:9-17`). The same stale folklore appears at `mmuirun.S:194`,
`mmubenchi.S:197` and `mmuidx.S:17` ("all guards use identity" — false).
*Verifying a claim against prose that repeats it is not verification.* All four
comments are being corrected in the same change, or the next agent repeats it.

Two further review corrections: the claim that four guards were "wired into
neither lane" was wrong (`full-regression.yml` runs all four **by name**, and
`linux_sim.sh` takes a name argument), and its conclusion — *"an unrun guard's
identity exposure is moot until it is wired in"* — was dangerous and is deleted;
and §5's "every verdict is backed by a cited line" overstated provenance (~60 are
bare names from a delegated pass).

### A4 final state (COMPLETE — `docs/guard-rule-no-identity-map`, 3 commits)

Both carve-outs now **demand a witness rather than granting an exemption**, and
the weaker one has a decision procedure rather than a judgement call:

> Identity is *forced by layout* only when the page under test must sit at a
> specific **physical** address for a reason outside the mapping — a `.org`-pinned
> instruction, a vector table at a fixed `VBR` offset, the flat VA=PA image load.
> **The test: if you can move the backing frame by editing only PTE/PTEL
> constants, identity was not forced.** "It would be awkward to move" is not
> forced.

The test cuts the real cases correctly: `mmuidslot` and `mmuimiss_illegal` pass
(a branch at VA `0x0FFE` under a flat image load forces the delay-slot
instruction to be page 1's first halfword; `_zero_page` is pinned by a
hand-computed pad the VBR offsets depend on), while `mmuainc`/`mmuainc2` fail —
their frame moves with two constants. Same split §2's repair advice already made,
which is the point: the test promotes an existing distinction rather than
inventing one. Over-citing (b) costs guard strength, not soundness, since it
still mandates a witness.

Also delivered: the `m8_*` nine-guard gap named as follow-up (verified 12 files,
9 touching `PTEL`/`_tsb_tab`/`TSBBR`), honest provenance separating 17
hand-verified verdicts from ~60 bucketed by witness class, and **four guard
headers corrected at the source of the stale folklore** — proven comment-only two
ways (tight-pathspec diff, plus comment-stripped checksums identical at both
commits).

### `mmupage16k` carries TWO independent defects, not one

Confirmed by the reviewer tracing the guard end to end with the MMU inert, and
now recorded in the contract (`297ee7d`). The axes have distinct fault hypotheses
and neither is a corollary of the other:

| axis | hypothesis | why it passes anyway |
|---|---|---|
| counter liveness | walker works, instrumentation dead | `cmp/eq r13, r1` is satisfied by `0 == 0` |
| post-install snapshot | counter live, but `r13` taken *after* step 1 | no assertion in the file spans the install |
| identity mapping | translation never resolved | fails 1 & 2 are data read-backs through an identity page |

So the contract's standing condition — *"any change to `st_tag_hi` must turn
`mmupage16k` red before it is believed"* — rests on **two unverified
preconditions** (live counter **and** live MMU), neither of which the guard
establishes for itself. A0 also caught a knock-on I had not flagged: its earlier
claim that "the same one-line fix would retire the dependency altogether" is now
false — the repair needs the **stronger** counter form (delta across the step,
not merely nonzero) **and** `PA != VA`. Corrected and flagged in place as an
earlier error rather than silently rewritten.

## A1c — COMPLETE. Seven Group-C locks, and a proposed fix that was itself vacuous

Group-C guards **pass today** and must turn **red** if the contract is broken
later, so their entire value rests on demonstrated mutations. All seven built,
each mutation actually run, with a cross-table proving the locks are independent
(one RED with its own code, six green, per mutation). The spec reviewer
independently reproduced **six** of the eight rows plus the baseline, and filled
five blank cross-table cells by running combinations A1c had not.

**The headline finding: the fix the reviewer and I both proposed would have been
vacuous.** For "the guard's image must fit in one 4 KB page" we specified an
in-file `.if . > 0x1000 / .error`. A1c showed it (a) does not assemble — `.` is
not an absolute expression in a relocatable section — and (b) would have been
*wrong* even if it did: `sh32.x` merges `*(.vect)` ahead of `*(.text)` in one
output section, so `.` under-reports by exactly **0x118**. It built a deliberately
overflowing image ending at `_etext = 0x1100` where `.` reads `0xFE8` — under the
limit. **Our check would have passed exactly the overflow it existed to catch.**
The reviewer then derived the same 0x118 independently by counting the `.vect`
block (16 + 240 + 20 + 4 = 280 bytes), matching the measurement to the byte.
The check moved to `sim/tests/Makefile` against the **linked** `_etext`, matching
the existing M8 precedent, and was mutate-confirmed itself: padding produces a
hard build error **and no `.img`**, so a stale image cannot be picked up.

**Also from A1c:**
- **A contract mutation that is not constructible as a proof.** Masking at or
  finer than the entry's own mask is a provable no-op (measured: all seven stay
  green); masking coarser makes the walker re-arm without bound and wedge with
  *no result code*. No middle case exists, so that case's real proof is a
  different mutation. Third contract case to prove unbuildable as specified.
- **A latent RTL gap, filed not fixed (R5):** the walker has no bound on
  *install-then-still-miss* re-arming. Unreachable today — which is *why* the
  mutation wedges — but a future install-path change of that shape would present
  as an unrecoverable hang, the failure class this contract exists to close.
- **A P5 relaxation, verified:** `core/cpu.vhd:789`/`:841` force
  `db_o.a(31 downto 28) <= "0000"` on every translated hit, so a VA outside the
  backed window can still resolve to a backed PA. Unblocks cases that had looked
  unbuildable, with the condition that the mutation must degrade to a walk rather
  than a wedge.
- **The monitor that could silently disable itself.** `p_walk_read_order` was
  gated on `entry_bytes = 16`; a future width change would have switched the check
  off rather than failed. Now an unconditional `severity failure` assertion.
  A1c's own words: *"it was the one place in my own work that reproduced the
  pattern the whole task exists to eliminate."*
- **A fix that invalidated its own evidence:** adding that assertion moved the
  code, so two verbatim transcript blocks quoted a line number that now points at
  a different `case` arm — in the only Group-C row a reader must follow into RTL
  rather than to a result code.

**Open:** `scripts/vhdl-lint.sh` cannot run here (`vsg` absent, no network, host
`pip` blocked by PEP 668). The reviewer closed the question by *inspection* —
`vsg_config.yaml` overrides nothing in the `*_400` family, the new declaration
groups are blank-line and comment separated so they form their own alignment
groups, nothing exceeds 100 chars — and rates the contagion risk low. **Lint must
still be run before push**; it is a separate gating workflow neither regression
script exercises, and the warning is capitalised in the commit message.

## Method note worth reusing: two ways to confound a synthesis A/B

A3's area table attributed a cost to the wrong change, and unpicking it exposed
**two** independent traps. Both are easy to fall into and neither is obvious.

1. **Never build an area table across trees that differ in assertion count.**
   `cpu_synth.sh` runs `chformal -remove; delete t:$check t:$print` **after**
   `synth_ecp5`/`synth`, so the assertion *cell* disappears but its influence on
   how everything else mapped does not — its operands stay live through
   optimisation and abc9 sees a different cone. Measured effect of adding one
   assertion: **+286 to +541 LUT4** and +1 generic `reg`. The comment claiming
   "simulation-only; assertions have no synthesis effect" was therefore false,
   in **two** places (the second pre-existing, 250 lines away). A3's original
   baseline lacked the assertion while its other rows carried it, so the
   assertion's ~540 LUT4 was booked against the reset flush — **inverting the
   sign** of the reported result.
2. **Never synthesise a baseline by deleting a term.** A3's second confound,
   which it found itself: its "baseline" had the `rst` port **present and
   connected** with only the flush term removed — a dangling input, precisely the
   "signals merely tied off" condition `core/datapath.vhm:236-241` records as
   producing measured ±464 LUT4 swings on J1. That row measured neither the flush
   nor its absence, but a third thing. **A baseline must come from a real
   commit**, built in a throwaway copy.

Corrected method: four trees from real commits (base; base + A3a; assertion only;
HEAD), each synthesised in a `git archive` copy. First two reproduce the
reviewer's independently-derived figures to the digit — and with the assertion
held out, the reset flush is **−81 LUT4 / −120 cells / +26 generic assigns**,
flop count untouched. The decision A3 actually made was never at risk: the
ship-vs-fold pair *was* properly controlled (two trees byte-identical but for the
flush form) and reproduced exactly at **−464 LUT4** in favour of the shipped form.

> **The recurring shape:** a correct conclusion resting on incorrect reasoning.
> Third occurrence this wave, after the stale capacity claim that justified an
> EXPEVT deviation and the A5 resolution criterion that could never have
> discriminated. It is why reviewers were asked to **re-derive** rather than
> confirm.

**Also do not run `scripts/fmax_ab.sh` casually.** Both A3 and its reviewer
independently confirmed it (and `synth/with_overlay_decoder.sh`) regenerate a
J4-overlay decoder into **tracked** `decode/*.vhd` behind a `|| true` restore, so
a failed run can leave overlay tables in tracked source. A3 killed its own 6-seed
run for this reason and recorded Fmax as **explicitly unmeasured** rather than
assumed benign; the reviewer did all its synthesis in throwaway copies.

## Method note worth reusing: choosing the right oracle

A1a proved its symbolic-constant refactor **value-inert** (not merely "still
green") two ways, and the reviewer — which re-derived the result independently
rather than trusting it — judged one method clearly better:

- **Weaker:** check the regenerated tables against an *independently written
  model*. A model written by the same author from the same source can encode the
  same misunderstanding, so agreement proves less than it appears to.
- **Stronger and cheaper:** evaluate the *preprocessed output* of the new
  revision against the **previously committed values**. That uses the old
  artifact as the oracle instead of a fresh derivation, so it cannot inherit the
  author's misreading.

The reviewer's own run: `mmupmsub4k` all 49 words identical, `mmupmsubi` all 16,
`mmupmmix` all 82, with every newly-introduced derived expression hand-checked
against the constant it replaced. Only intended delta: `K_SCRATCH_WORDS` 8→12.

**Rule for future refactors of guards:** a guard refactor is exactly where a
silent value change hides, so prove inertness against the previous artifact, not
against a re-derivation.

## Doc-drift finding for the B-track (a worked example of the problem)

A stale sentence in `docs/mmu/hardware-spec.md:899` ("imm field at capacity,
32/32") propagated into **five** RTL/spec comment sites and was then used to
justify an architectural deviation. The origin was traced to
`decode/gen-go/spec/sh4/exceptions.toml:390`. All six sites are now corrected.
This is precisely the failure mode Track B0's doc-vs-code CI checks exist to
prevent, and it is worth citing when that work is specified.

Side-finding: `scripts/vhdl-lint.sh` exits **127** inside the CI image because
`bc` is absent and `set -e` kills it at the summary line — the lint itself was
already clean. Anyone running it locally needs a `bc` shim to get a genuine
exit code.

## Merge notes — read before landing anything

| branch | repo | notes |
|---|---|---|
| `design/mmu-pagemask-contract` | docs | 8 commits; the contract everything else implements |
| `fix/p4-privilege-gate` | jcore-cpu | privilege-escalation fix; independent |
| `docs/p4-privilege-mmufsr` | docs | MMUFSR KIND 8/9 + stale-claim fix; pairs with the above |
| `fix/tsb-tag-mask` | linux | **kernel-first**: the 3-line livelock fix |
| `fix/tsb-tag-comment` | jcore-cpu | Group-B guards; pairs with the above |
| `fix/hugetlb-pte-slot` | linux | **kernel-first** — `test/hugetlb-pte-slot`'s corrected `mmuhuge.S` requires it |
| `test/hugetlb-pte-slot` | jcore-cpu | huge-page guards + `mmuhuge.S` correction |
| `docs/guard-rule-no-identity-map` | jcore-cpu | standing guard rule + 80-guard survey |
| `test/contract-group-c` | jcore-cpu | 7 contract locks; passes on pristine base, no dependency |
| `fix/tlb-reset-and-walk-takeover` | jcore-cpu | reset flush + walker proof/lock |

**⚠ `fix/p4-privilege-gate` carries 6 untracked generated files.** `cache/{d,i}cache_{ccl,mcl}.vhd`, `cache/icache_modereg{,_wsbu}.vhd` — v2p output from their `.vhm` sources, left by `sim/mmu_sim.sh`'s preprocess step. They are **not** in that branch's `.gitignore` (the ignore entries were added later, on `fix/tsb-tag-comment`), so a **`git add -A` before merging this branch would commit generated files** the project explicitly says must never be hand-maintained. Delete them, or land the `.gitignore` addition first. Verified: all ten Wave-0 branches are otherwise committed with clean trees.

**Before push, on every branch touching a lint-scope `.vhd`:** run
`vsg -c vsg_config.yaml -f <file>`. `vhdl-lint` is a **separate gating CI
workflow** that neither `regression.sh` nor `sim/mmu_sim.sh` exercises, and `vsg`
could not be installed in this environment (absent from the image, no network,
host `pip` blocked by PEP 668). Two reviewers assessed the alignment-contagion
risk as low-to-zero by inspection, but that is not the gate.

## Open items carried out of Wave 0 (recorded, not failures)

1. **D-side double-issue** — real, reachable, **documented and unfixed by
   design**, at three sites in `core/cpu.vhd`. On a D-side walk the faulting
   access is driven and acked externally, then replayed, so it issues twice.
   Benign only because (a) faulting stores are demoted to reads by
   `d_store_faulting`, and (b) `d_at_translated` is `mmucr(0)` only for
   `SEG_P0`/`SEG_P3`, so MMIO in P1/P2/P4 can never be a walk's faulting access.
   **A device mapped into P0/P3 under `AT=1` will see the read twice, and no
   guard would notice.**
2. **Post-P&R Fmax unmeasured** for the reset flush — recorded as unknown rather
   than assumed benign. Less pressing now the change is LUT4-negative, but a
   −336 LUT4 mapping change is still a mapping change. Do **not** use
   `scripts/fmax_ab.sh` casually: it regenerates a J4-overlay decoder into
   **tracked** `decode/*.vhd` behind a `|| true` restore.
3. **The one-shot P4 exception waiver** (from A2) — safety unaffected, but a
   swallowed violation clobbers an older pending fault's TEA, so the ceiling is
   "confined to diagnosis", not "harmless". Its follow-up's **first** deliverable
   must be a guard that creates the contention, since none does today.
4. **`__update_tlb()` fill site uncovered** — decision recorded, with the
   reachable substitute specified (`__update_tlb(NULL, addr, pte)` touches no mm
   state; its only `vma` dereference short-circuits). Belongs on the A1a merge
   branch, where it is red before and green after.
5. **8 identity-mapped guards named as vacuous** in
   `sim/tests/README-identity-mapping.md`, plus a 9-guard `m8_*` gap unsurveyed.
   Each repair's first step is to delete the guard's `MMUCR.AT` enable and
   confirm it stays green.
6. **Two standing contract amendments** in `docs/mmu/group-c-locks.md`: C5's
   mutation dichotomy, and **R5** — the walker has no bound on
   *install-then-still-miss* re-arming (unreachable today, which is *why* the
   mutation wedges; a future install-path change of that shape would hang
   unrecoverably).
7. **`huge_ptep_clear_flush` and the whole replication half are compile-verified
   only** — nothing here boots a kernel. GUP, teardown, fork/COW, `mprotect`,
   migration and uffd over a huge mapping are exercised by no executed test.

## Environment resolved

`/` was 100% full, which failed the first image pull. The A2 agent ran
`docker image prune -f` (dangling/untagged only — the option authorized by the
user; no `-a`), reclaiming 4.6 GB. Disk now 78% used, 15 G free, and
`ghcr.io/mountain-reverie/jcore-cpu-ci:latest` is **present and working** — RTL
guards are now genuinely runnable locally, so verification is no longer deferred.

Side-finding worth fixing later: `sim/mmu_sim.sh`'s `TOOLS_DIR` wildcard
(`../../mcu_lib/tools`, `../../../tools`) resolves to nothing in this workspace
layout; A2 worked around it by mounting `jcore-soc/tools` at `/tools`. This will
bite anyone running the script locally.

## A0 outcome — a reversal of the original diagnosis (under review)

A0 concluded the **RTL compare is already correct and the KERNEL is wrong**:
`tag_hi` should be `VA & 0xFFFF_F000` (finest granularity, 4 KB) for *every* page
size, because the TSB **index** is already 4 KB-granular (`tsb_ptr` hashes
`VA[31:12]`). The "walker doesn't know the size at compare time" difficulty then
*dissolves* — the compared quantity is size-independent; PageMask lives once in
`data` (`PTEL[11:8]`) and is applied only at install, after `data` is read. So the
fix is kernel-side (`PAGE_MASK` → `JCORE_TSB_TAG_MASK`) plus an RTL comment fix.

Accepted tradeoff: a page larger than 4 KB owns one TSB row per *touched* 4 KB
sub-page. Its load-bearing argument against a size-masked tag: that would make the
anti-duplicate invariant **constructible** — on a huge→base split, the walker
would match a stale huge row that `jcore_tsb_pick_way()` cannot see, installing
stale PTEL silently.

**Design review UPHELD the reversal** (APPROVED-WITH-CHANGES), verifying each link
independently: the index really is 4 KB-granular (`datapath_pkg.vhd:251`, fixed
shift, no PageMask input); the walker really compares the raw latched VA
(`tlb_walk.vhd:263-264`); install really applies PageMask correctly for all nine
sizes (`tlb.vhd:394-406`, `:121` masks both operands); the kernel really is the
deviant (`tlb-jcore.c:200,292`). **So A1's scope moves from RTL-side to
kernel-side.**

The review also found the reversal is *established doctrine*, not a new position:
`hardware-spec.md:894` (pre-existing) already states the canonical-4 KB rule for
PTEH with the identical rationale, and `sim/tests/mmupage16k.S:8-11` already
guards it. The bug's origin is on record too — `tlb-jcore.c:217-222` correctly
observes the fixed 12-bit hardware shift and then draws the wrong conclusion
("only ever costs a fast-path miss ... never a wrong translation"). It costs an
unbreakable loop, because software rewrites the same unmatched tag.

### NEW defect found by the review (neither the original review nor A0 caught it)

`data[11:8]` (PageMask) is installed **verbatim with no validation**
(`tlb.vhd:398`), and the two mask functions **disagree above pm=8**:
`vpn_compare_mask` continues to n=18 (pm=9) and n=20 (pm≥10) while
`page_offset_mask` saturates at n=16 (`components_pkg.vhd:628-730`). A TSB row
with pm≥10 therefore installs a TLB entry whose VPN compare mask is **all
zeros** — a **wildcard entry matching every VA in the ASID**, relocating as if
256 MB. Since the TSB lives in kernel memory the walker trusts, this is a
containment concern, not merely a correctness one. pm 9..15 must be declared
reserved with defined hardware behaviour and a guard pinning it.

### Required fixes sent back to A0 (6)

1. **B5' is unachievable and would fail after the fix** — the walker matches the
   stale row's tag exactly and installs stale PTEL before software is ever
   invoked. Invert it into a lock proving the TSB memset in
   `local_flush_tlb_all()` is what makes remap safe, or delete it. Correspondingly
   **scope C6**: it makes an intra-set *duplicate of a VPN* unconstructable; it
   does **not** make remapping safe without a TSB flush.
2. **K3 understated** — a 4 KB build is broken by the pte layout itself (SZ bits
   {10,12,13} collide with PFN bits under `PFN_PTE_SHIFT = PAGE_SHIFT`), and the
   config **is selectable** (`arch/sh/mm/Kconfig:7`). Needs a
   `BUILD_BUG_ON(PAGE_SHIFT != 14)` declaring 4 KB out of scope, or the full
   layout rework. B7 as written is vacuous.
3. **B3-s unrunnable** for sizes ≥ 16 MB (cosim backing window is 16 MB).
4. **Add the `data[11:8] > 8` clause** (the new defect above).
5. **§3(e)'s rejection rationale self-refutes** — it rejects a global TAGSHIFT for
   being global, but 4 KB is also global. Restate on cost grounds.
6. **Two numbers wrong** — K8 is 65536 rows not 16384 (contradicts C7); K3 "two"
   → "four".

Also flagged: the *decisive* argument against a masked tag is not C6 but that
sub-pages of a large page land in **different sets**, so a masked tag serves only
sub-pages colliding into its own set — masking the tag without masking the index
is provably useless, and masking the index needs the size before choosing the
set. And C7's "self-limiting" replication claim is optimistic: worst case
`size/4KB` rows against a **512-row** TSB, and after a TLB eviction huge pages
get little TSB benefit. Recorded as an accepted, unmeasured cost.

A0 also raised two further defects for A1: (1) a huge PTE occupies one pte slot
covering only `PAGE_SIZE` of VA while `__jcore_tlb_walk()` indexes by the raw
faulting address, so a huge page may be unusable past its first 16 KB even after
the tag fix; (2) `jcore_pm_for_slot[]` hardwires base == 16 KB, so a 4 KB build
would install 16 KB TLB entries. It also corrected the brief: the seven HugeTLB
sizes are **64 KB–256 MB**, not 16 M–256 M.

## A2 outcome (under review)

Gate implemented in `core/datapath.vhm` with delivery via the existing D-side
TLB-fault machinery; new guard `sim/tests/mmup4priv.S` (451 lines) sweeps user
read *and* write of all 17 decoded P4 offsets. Reported before-fix
`FAIL ... Result=1` ("user READ raised no exception" — the escape itself) and
after-fix `PASS`, with 105/105 guards, base J2 20/20, TAP 726/726. **The reviewer
is re-running these independently rather than trusting the report.**

Self-declared concerns to adjudicate: EXPEVT is `0x0C0` (shared with DPROT_R/W,
discriminated by new MMUFSR KIND 8/9) rather than SH-4's real address-error codes
`0x0E0`/`0x100`, because `tlb_exc_expevt` is claimed to be **dead silicon** (no
reader) and the decoder's system-plane immediate field is claimed to be at
capacity (32/32); a one-shot exception request that could be dropped (safety
unaffected — refusal is unconditional, worst case a swallowed signal); and a
residual gap: user-mode *instruction fetch* from P4 is still unchecked.

## Orchestrator pre-verification (done before dispatch, to curate context)

**A2 vulnerability confirmed real, not "apparent":**
- `core/datapath.vhm:1758` gates the P4 MMU-register read/write block on
  `PRIV_ARCH and seg_v = SEG_P4` only — no `sr.md` term.
- `sr.md` *is* available and used in that same file for privileged-instruction
  gating (`:1646`), register banking, and the fault-status USER bit (`:1283`,
  `:1437`) — so the omission is an oversight, not a structural limitation.
- A grep across `core/*.vhd` + `core/*.vhm` for address-error / privileged-segment
  checks returns **only** those two `SEG_P4` lines: there is no address-error
  exception for user access to a privileged segment.
- `core/cpu.vhd:874-877` asserts translation only for SEG_P0/SEG_P3, so no TLB
  permission fault intervenes on a P4 access.
- Source of truth is `core/datapath.vhm`; `core/datapath.vhd` is a generated
  artifact (listed in `.gitignore` despite a stale tracked copy).

**A1 livelock confirmed at RTL level (from the review pass):**
- `core/tlb_walk.vhd` `st_tag_hi` compares `bus_d(31 downto 12) = va_reg(31
  downto 12)` with low 12 bits required zero — hardwired 4 KB granularity — and
  its comment states the (false) assumption that "Linux writes `address &
  PAGE_MASK`" at 4 KB.
- `va_reg` latches `req_va` = the raw unmasked faulting VA (`core/cpu.vhd:598`,
  `:868-869`).
- Linux uses 16 KB pages (`CONFIG_PAGE_SIZE_16KB=y`) and writes a 16 KB-aligned
  tag (`arch/sh/mm/tlb-jcore.c:200,292`), and registers seven HugeTLB sizes.
- No retry counter (`arch/sh/kernel/cpu/jcore/ex.S:148`) ⇒ hard livelock, not a
  slow path.
