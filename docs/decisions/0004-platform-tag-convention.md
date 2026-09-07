# 0004 — Platform tags: `[FPGA]` / `[ASIC]`, and which numbers need one

**Status:** Accepted 2026-09-07. Wave-1 task B0b, from
[j4-remediation-plan.md §B0](../j4-remediation-plan.md).

---

## Context

[j4-remediation-plan.md](../j4-remediation-plan.md), guiding principle 1, states
the dual-target framing this record enforces:

> Two platforms, stated explicitly, everywhere. Phase-1 is the ULX3S / ECP5
> FPGA at ~40 MHz: the goals there are **correctness, area (LUT/BRAM fit), and
> boot-to-Linux**, and **energy is explicitly out of scope**. The later ASIC (a
> *new* design — the gf180 target is only a proof the RTL can reach an ASIC
> flow, not the product) aims at ~400 MHz+ where **frequency and energy
> efficiency** become first-class. Every quantitative claim in every spec must
> carry a `[FPGA]` or `[ASIC]` tag. A number with no platform tag is a defect.

Track D0 restates the energy half in the imperative:

> **Energy — `[ASIC]` only** — do NOT try to measure energy on the ECP5. Get
> energy numbers from gate-level activity + power analysis in the ASIC flow
> (sky130/gf180 as the *methodology* vehicle even if not the product)... Until
> an ASIC flow produces a number, energy claims are literature-calibrated
> estimates, tagged as such.

Two concrete defects, found by running this task rather than assumed:

1. **`simd/hardware-impl.md`** quotes area/timing figures for Spartan-6,
   Spartan-7, Artix-7, Kintex-7 and Virtex parts, and a **130 nm** ASIC node,
   with no platform tag anywhere in the document. None of those is the
   project's Phase-1 board (ULX3S, Lattice ECP5) or its ASIC methodology
   vehicle (gf180). A reader has no way to tell, short of recognising part
   numbers, that these figures describe hardware this project does not build.
2. **`cache/l2-spec.md` §20.3 and Appendix B** state a power figure — "Total L2
   power on ECP5-85F at 90 MHz: ~40–65 mW" — attached directly to the correct
   Phase-1 board. This is not a stale-platform problem; it is a **category**
   problem. Per principle 1 and Track D0 above, energy is not a thing this
   project measures on the FPGA at all, so a milliwatt figure attributed to the
   ECP5 is wrong regardless of which ECP5 part it names. This is the sharper
   of the two findings and is addressed in the sweep, not just tagged.

## Decision

**1. Every quantitative claim of timing (Fmax, critical path, ns/MHz), area
(gates, mm², LUT, FF, BRAM/EBR, DSP) or power/energy carries an inline
`` `[FPGA]` `` or `` `[ASIC]` `` tag at the point of use** — on the figure's own
line, or on the heading of a block where every figure under it shares one
platform (the existing convention in this tree already does this: `cache/l2-spec.md`
§20's heading carries `` `[T0/T1/T2]` `` for tier scope, and
`security/threat-model.md` §9 already tags one figure `` `[FPGA]` `` inline —
this record generalises both to every quantitative claim, not just the ones
already caught). Naming the platform in words — a heading that already reads
"130 nm" or "28/40 nm modern ASIC" — satisfies the same reader need as the
bracket and does not additionally require one; the bracket is the terse form
for a table row or bullet where prose naming would repeat itself every line.
**A number that says which machine would produce it, one way or the other, is
compliant. A number that does not is the defect this task removes.**

**2. Energy and power are `` `[ASIC]` ``, without exception.** Not "usually" —
always. This is not this task's judgement call; it is the project owner's
framing, quoted above, and it is now load-bearing: **energy is not measurable
on the ECP5 and must not be presented as if it were.** A power/energy figure
attached to an FPGA part or board is wrong regardless of which FPGA it names,
which is why the `cache/l2-spec.md` finding above is handled as a retraction,
not a re-tag — see that file's diff.

**3. `` `[FPGA]` `` names the Phase-1 target precisely: the ULX3S board, a
Lattice ECP5, ~40 MHz.** A figure measured on a different FPGA family —
Spartan, Artix, Kintex, Virtex, all Xilinx, none of them what this project
builds on — is not made `` `[FPGA]` `` by tagging it, because the tag would then
assert it describes current hardware, which it does not. Those figures are
**marked**, not retagged: state the platform actually measured, that it is not
the current target, and what would produce the real number. See §Marking
convention below.

**4. `` `[ASIC]` `` should name its process node when known.** The existing
130 nm figures in `simd/hardware-impl.md` come from "the J2 reference flow" —
an older, unrelated node, not gf180 (this project's ASIC methodology vehicle
per principle 1). They are marked for the same reason as rule 3: tagging them
bare `` `[ASIC]` `` would silently imply they describe the gf180 target.

**5. No cross-platform or cross-node arithmetic scaling.** This task does not
convert a Spartan/Artix LUT6 count into an ECP5 LUT4 estimate, and does not
scale a 130 nm figure to gf180 by a process ratio. The standing evidence in
this project is that such scaling is untrustworthy even *within* one family at
one node: two RTL trees on this same core, differing only in the operand order
of one `or` — logically identical — synthesized **368 LUT4 apart** on the
ECP5. (This figure is reported to this task by the project owner as a prior
measurement; it has not been independently reproduced here, and is cited for
its evidentiary role — cross-family, cross-node extrapolation is worth less
than a same-family, same-node noise floor of that size — not restated as a
project fact with its own owner.) A fabricated "converted" number is worse
than an honestly stale one, because it looks measured and is not.

**6. What does *not* need a tag.** Cycle counts, beat counts, instruction/uop
counts, and other quantities that are fixed by the architecture rather than by
the implementation technology (VLEN, beat counts per §3.1, shadow-latch bit
widths, ROM table sizes in bits, latency-in-cycles, exception-vector offsets,
register-file bit widths) do not need a platform tag. These hold across any
implementation of the same architecture; that is what "architectural" means
here, and it is also the reason [fact-ownership.md](../fact-ownership.md)
registers most of them separately as owned facts rather than platform figures.
**Tagging these reflexively is its own defect**: an over-tagged document is as
unreadable as an untagged one. The test is "which machine would produce this
number" — if the honest answer is "any correctly-implemented one", it needs no
tag.

**7. Mixed claims are split, not tagged as one.** A derived quantity that
combines a cycle count (architectural) with an assumed clock rate
(platform-specific) — e.g. `security/threat-model.md` §9's "~15k cycles (~0.5 ms
at 30 MHz)" gang-switch figure — needs the tag on the *derived time*, not the
cycle count, and the clock rate used must match the tag's platform. That row
already exists and already says so ("platform-tagged inconsistently — 30 MHz
here against the plan's ~40 MHz `` `[FPGA]` `` target"); B0b did not re-open it,
since re-tagging it is explicitly assigned to measurement task D0a in that same
row, not to this doc sweep.

## Marking convention, for a figure that cannot be honestly retargeted

A marked figure states, in prose next to the number, all three of:

1. **What platform it actually describes** (part family, process node).
2. **That this is not the current target** (Phase-1 FPGA = ULX3S/ECP5 ~40 MHz;
   ASIC methodology vehicle = gf180).
3. **What would produce the real number** — usually "synthesize under
   `yosys`/`nextpnr-ecp5` targeting the ULX3S 85F" for `` `[FPGA]` ``, or "a
   gate-level run under the gf180 flow, per Track D0" for `` `[ASIC]` ``.

This is deliberately **not** a [decisions/0002](0002-supersede-convention.md)
`SUPERSEDED BY` / `HISTORICAL` marker. Those markers are about a *fact* that
changed and was fixed elsewhere, checked by `resolved-is-merged` against a
named commit or branch. A platform-stale figure has not been superseded by
anything — nothing has replaced it, no fix has merged, there is nothing for
`check-doc-facts.py` to verify against a branch. Borrowing 0002's marker
grammar here would either fail `marker-grammar` (no repo/branch/commit to cite)
or, worse, parse successfully against the wrong thing. A plain prose note,
per the three points above, says the true thing without pretending to be a
grammar this isn't.

## Enforcement

**Not mechanically checked**, and that is stated rather than implied.
`scripts/check-doc-facts.py` enforces [0001](0001-one-authority-per-fact.md)
and [0002](0002-supersede-convention.md); it has no rule for this record, and
this task does not add one. A regex for "quantitative claim with no adjacent
`[FPGA]`/`[ASIC]`" was considered and rejected for the same reason
`glossary-is-value-free`'s shape list is enumerated rather than claimed
complete (see [0001](0001-one-authority-per-fact.md)): distinguishing a figure
that needs a tag from one that is architectural (rule 6) requires knowing
*what kind of number it is*, not just that a number is present, and a regex
that gets that wrong in the fail-open direction is worse than the manual sweep
it would replace. This is a residual, named rather than papered over: **the
sweep in this commit is a point-in-time correction, and nothing stops the next
edit from adding an untagged number.** See "What would reopen this" below.

## What this sweep covered, and what it deliberately left

`simd/hardware-impl.md` and the two figures in `fpu/spec.md` naming Spartan-6
alongside ECP5 are the SIMD/FPU FPGA figures this task's brief names by file
and by symptom (Spartan/Artix/130 nm). `cache/l2-spec.md`'s energy-on-FPGA
figures are the sharper defect found while doing that sweep and are corrected
in the same commit, since "move all energy claims under `` `[ASIC]` ``" is not
scoped to one file. A further set of energy-percentage claims exists in
`ooo/j32ooo-spec.md` and `ooo/j32lt-spec.md` (way-prediction "5–10% energy
win", the G4/G8 validation gates, the per-cycle activity comparison table) —
these describe cores that do not exist yet, for a design point ("throughput
per joule") that is ASIC-only by definition, and are listed here as **found,
not swept**: each would need the same file-by-file judgement call this record
took for `l2-spec.md`, and doing that responsibly for two ~800-line
specifications is more than this task's named scope (SIMD/FPU FPGA figures,
plus the energy-claim sweep this record's own evidence expanded into) can
absorb without shortcuts. They are a natural next bite, tracked here rather
than silently dropped.

## What would reopen this

- **A gf180 or ECP5 synthesis run lands for the Tier A/B/C SIMD crypto unit.**
  The marked figures in `simd/hardware-impl.md` §6 and §11 get replaced with
  real numbers, tagged normally, and the marking notes are removed rather than
  kept as decoration.
- **`ooo/j32ooo-spec.md` / `ooo/j32lt-spec.md` get their own platform-tag
  pass.** Until then, treat every energy-percentage figure in those two
  documents as unswept, not as compliant-by-omission.
- **A mechanical check becomes worth writing** — e.g. if untagged numbers keep
  landing despite this record, the cost of a conservative (fail-open-tolerant)
  regex may start to beat the cost of continued manual drift, the same
  trade [0001](0001-one-authority-per-fact.md) made for `VALUE_SHAPES`.
