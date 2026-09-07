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

## Provenance vocabulary borrowed, not reinvented

Some of the prose this sweep wrote (`fpu/spec.md` §6.8/§6.9,
`cache/l2-spec.md` §20.3) labels a claim `STRUCTURAL` or "unsourced". Those
words are not this record's own vocabulary — they belong to
[security/threat-model.md §9](../security/threat-model.md)'s evidence-status
scale (`SOURCED` / `LITERATURE` / `ESTIMATE` / `STRUCTURAL`, plus `UNSOURCED`
used informally in that section's own table body). This record does not
redefine them; it links back to §9 at each use, per this task's instruction to
reuse that vocabulary rather than invent a parallel one. Naming the debt
rather than hiding it: that scale is scoped in its own text as
*"document-wide, not table-local"* — meaning wide within `threat-model.md` —
and this sweep is the first thing to cite it from outside that file. It now
has three users (`threat-model.md` itself, and this sweep's two files) and no
single place that owns the definitions across all three; formalising that is
its own small piece of work and is not done here, since it belongs to
whoever next revisits `threat-model.md` §9, not to a platform-tag sweep.

## Marking convention, for a figure that cannot be honestly retargeted

A marked figure states, in prose next to the number, all three of:

1. **What platform it actually describes** (part family, process node).
2. **That this is not the current target** (Phase-1 FPGA = ULX3S/ECP5 ~40 MHz;
   ASIC methodology vehicle = gf180).
3. **What would produce the real number** — usually "synthesize under
   `yosys`/`nextpnr-ecp5` targeting the ULX3S 85F" for `` `[FPGA]` ``, or "a
   gate-level run under the gf180 flow, per Track D0" for `` `[ASIC]` ``.

This is deliberately **not** a [decisions/0002](0002-supersede-convention.md)
`SUPERSEDED BY` / `HISTORICAL` marker, and the first version of this record
gave the wrong reason for that: it said no marker fit because there was "no
repo/branch/commit to cite", which is true of `RESOLVED` and `PENDING-MERGE`
but **not of `HISTORICAL`** — that marker's regex is date-only, and its stated
use in 0002 ("a cost baseline, a retired mechanism") describes a retained
Spartan-7 figure about as well as it describes anything. The real reason is
narrower and is the one that survives scrutiny: `HISTORICAL` says *this text
is accurate about a past state of this project*, kept deliberately as the
record of what a change replaced. A Spartan-6/Artix-7 figure is not a past
state of this project — this project never targeted those parts at any point
in its history; it is a **different project's hardware**, cited here as a
starting estimate. `SUPERSEDED BY` fits even worse, requiring a replacement
document section that does not exist. Neither marker's *meaning* is honest
here, independent of what either regex would accept. A plain prose note, per
the three points above, says the true thing without borrowing a grammar whose
meaning doesn't match.

## Enforcement

**`scripts/check-doc-facts.py` now runs `platform-tag-foreign-part`**, added
2026-09-07 after design review found four sites in `simd/hardware-impl.md`
that broke this record's own rule 3 on first use — the sweep that introduced
the rule violated it in the same commit, and nothing caught that until a
human reviewer read the diff by hand. The check is deliberately narrow and
enumerated, not a general "does this figure need a tag" judgement: it fails
when a platform-tag bracket shares a source line with a mention of one of
five Xilinx-only FPGA families (case-insensitive, word-bounded) — the family
list, spelled out on its own so this paragraph does not itself trip the
check: Spartan, Artix, Kintex, Virtex,
Zynq. Four literals; it cannot fail open, and it cannot fire on a figure that was
correctly *marked* in prose instead of tagged, because marking prose does
not use the bracket form. This is exactly the enumeration `decisions/README.md`
asks for ("a decision with no enforcement is a preference") and exactly the
shape [0001](0001-one-authority-per-fact.md) uses for `VALUE_SHAPES` — a
reach that is stated, not claimed complete.

**What this check does not do, stated so the green run is not over-read.** It
catches a tag placed somewhere it shouldn't be. It does **not** catch a figure
that needed a tag and has none — that is still a manual-sweep problem, and a
general regex for "quantitative claim with no adjacent `[FPGA]`/`[ASIC]`" was
considered and rejected for the same reason `glossary-is-value-free`'s shape
list is enumerated rather than claimed complete: distinguishing a figure that
needs a tag from one that is architectural (rule 6) requires knowing *what
kind of number it is*, not just that a number is present, and a check that
gets that wrong in the fail-open direction is worse than the manual sweep it
would replace. That gap is real and is why "What this sweep covered, and what
it deliberately left", below, matters: the tree is not tagged-complete just
because this check is green.

## Rejected alternatives

**Reuse 0002's marker grammar (`SUPERSEDED BY` / `HISTORICAL`) for a
platform-stale figure.** Rejected — see §Marking convention above for the
full argument. In short: `HISTORICAL`'s regex would accept it, but its
*meaning* — "accurate about a past state of this project" — does not, because
a Spartan-6 figure was never a state of this project at all. Using it anyway
would make the marker grammar mean less than it says.

**A general regex for "quantitative claim with no adjacent
`[FPGA]`/`[ASIC]`".** Rejected, for the same reason
[0001](0001-one-authority-per-fact.md) enumerates `VALUE_SHAPES` instead of
claiming completeness: telling a figure that needs a tag (rule 1) apart from
one that is architectural and needs none (rule 6) requires knowing what kind
of number a line contains, not just that a number is present. A check that
gets this wrong in the fail-open direction — silently passing an untagged
figure — is worse than no check, because it would be read as proof the sweep
is complete. `platform-tag-foreign-part` (§Enforcement) takes the narrower,
enumerable half of the problem instead: not "is this tagged" but "is this
*specific, wrong* tag present", which four literals answer without
ambiguity.

**Cross-family or cross-node arithmetic scaling**, to produce an ECP5 number
from a Spartan/Artix one, or a gf180 number from the 130 nm J2 reference
figures. Rejected on the evidence in Decision rule 5: two logically-identical
RTL trees on this core, differing only in operand order, synthesized 368 LUT4
apart on the ECP5 itself — same family, same node, same design. A ratio
carried across vendors and process nodes is worth less than that noise floor,
so no such ratio is computed anywhere in this sweep.

## What this sweep covered, and what it deliberately left

`simd/hardware-impl.md` and the two figures in `fpu/spec.md` naming Spartan-6
alongside ECP5 are the SIMD/FPU FPGA figures this task's brief names by file
and by symptom (Spartan/Artix/130 nm). `cache/l2-spec.md`'s energy-on-FPGA
figures are the sharper defect found while doing that sweep and are corrected
in the same commit, since "move all energy claims under `` `[ASIC]` ``" is not
scoped to one file.

**Left inside the files this sweep touched, and not excusable by "not the
named symptom":**

- `simd/hardware-impl.md` §4 (the swizzle-crossbar area table, "Approximate
  gate count", ≈1000–8000 gates by lane width) and §5.3 ("Tier 1 area
  summary", ≈200–5000 gates per feature) — bare gate counts with **no**
  process or vendor named at all, unlike everything else in this file. This
  sweep did not resolve whether that silence means "technology-neutral gate
  equivalent" (defensible) or "unlabelled ASIC estimate" (the same defect as
  everywhere else in this file, just missing the giveaway vendor name). Listed
  as genuinely ambiguous rather than guessed at, per this task's own
  standards.

**Left everywhere else — the tree-wide surface, not just two OoO specs.** An
earlier draft of this record listed only `ooo/j32ooo-spec.md` and
`ooo/j32lt-spec.md` as found-but-unswept. A grep for LUT/EBR/MHz/mm²/gate
patterns across `docs/` (`grep -lrEi` for size, frequency and area shapes)
turns up figures with no platform tag in at least these further files, none
of which this task opened:

`hypervisor/design-spec.md`, `hypervisor/hardware-spec.md`,
`iommu/hardware-spec.md`, `iommu/linux-spec.md`, `j4-remediation-plan.md`
itself (e.g. "Baseline Fmax (42 vs 80 MHz)", already separately tracked as a
B1 contradiction, but still untagged prose), `j4-wave0-status.md`,
`jcore-ulx3s-service-plan.md`, `mmu/design-spec.md`, `mmu/hardware-spec.md`,
`no-gpu-dual-ecp5-asic.md`, `ooo/j32lt-spec.md`, `ooo/j32ooo-spec.md`,
`priv-arch/j4-implementation-design.md`, `security/threat-model.md` (which, at
§9, explicitly defers its own number audit to B0b and B0c — "It does not
audit every number in every spec; that is B0b... A figure absent from this
table has not been cleared"), `simd/gpu/architecture.md`,
`simd/software-impl.md`, `simd/spec.md`, and
`ulx3s-soc-component-inventory.md`.

That list was produced by a filename-level grep, not by reading each file —
it says these files *contain* the relevant shapes, not that every occurrence
in them is a real defect (some may already be correctly scoped by prose, the
same way several sites this sweep touched were). **The honest summary is: the
platform-tag principle is not satisfied tree-wide, only in the two files this
task's brief named plus `cache/l2-spec.md`, `fpu/spec.md`, and this record
itself.** A reader of this document alone, before this correction, would have
concluded otherwise. B0b did not have the budget to read seventeen further
specifications figure-by-figure without shortcuts that would have been worse
than leaving the list honest; see "What would reopen this".

Within that surface, `ooo/j32ooo-spec.md` and `ooo/j32lt-spec.md` remain the
most-checked-for case (way-prediction "5–10% energy win", the G4/G8
validation gates, the per-cycle activity comparison table) — they describe
cores that do not exist yet, for a design point ("throughput per joule") that
is `[ASIC]`-only by definition, and each would need the same file-by-file
judgement call this record took for `l2-spec.md` before it could be tagged
responsibly.

## What would reopen this

- **A gf180 or ECP5 synthesis run lands for the Tier A/B/C SIMD crypto unit.**
  The marked figures in `simd/hardware-impl.md` §6 and §11 get replaced with
  real numbers, tagged normally, and the marking notes are removed rather than
  kept as decoration.
- **`ooo/j32ooo-spec.md` / `ooo/j32lt-spec.md` get their own platform-tag
  pass.** Until then, treat every energy-percentage figure in those two
  documents as unswept, not as compliant-by-omission.
- **The tree-wide list in "What this sweep covered" gets worked down.** Each
  of the seventeen further files either gets tagged or gets a documented
  reason it needs none; the list here shrinks as that happens, the same
  burn-down discipline [fact-ownership.md](../fact-ownership.md)'s Waivers
  table uses. Until then, do not read a green `check-doc-facts.py` run as
  "the tree is platform-tagged" — it only means no *known-wrong* tag is
  present (`platform-tag-foreign-part`), not that every figure that needs a
  tag has one.
- **`platform-tag-foreign-part` needs a fifth (or Nth) literal.** The list is
  Spartan/Artix/Kintex/Virtex/Zynq today because those are the names found in
  the tree; a new foreign FPGA family showing up in a future edit needs its
  name added to `FOREIGN_FPGA_PARTS_RE`, the same maintenance
  [0001](0001-one-authority-per-fact.md) already asks of `VALUE_SHAPES`.
- **A mechanical check for the *absence* of a needed tag becomes worth
  writing** — e.g. if untagged numbers keep landing despite this record and
  the enumerated `platform-tag-foreign-part` check, the cost of a
  conservative (fail-open-tolerant) regex may start to beat the cost of
  continued manual drift, the same trade [0001](0001-one-authority-per-fact.md)
  made for `VALUE_SHAPES`. This is a different, harder check than the one
  added here — see §Enforcement's "what this check does not do".
