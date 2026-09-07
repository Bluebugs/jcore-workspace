# 0005 — An unmeasured figure is removed, not annotated

**Status:** Accepted 2026-09-07. Wave-1 task B0d, from
[j4-remediation-plan.md §B0](../j4-remediation-plan.md). **Supersedes
[0004](0004-platform-tag-convention.md) rule 3, rule 4's marking half, and
0004 §Marking convention.** The rest of 0004 — the `[FPGA]`/`[ASIC]` tag
itself, energy-is-`[ASIC]`-only, no cross-node scaling, what needs no tag —
stands unchanged.

---

## Context

[0004](0004-platform-tag-convention.md) rule 3 decided that a figure measured
on hardware this project does not build is kept and annotated rather than
retagged — its retired wording, quoted once here and nowhere else: "marked, not
retagged". The number stays, with prose beside it naming the platform it really
describes. Applying that rule produced, in `simd/hardware-impl.md` §11.1, a table whose LUT column
read `3,500 / 2,200 / 50` under a thirteen-line blockquote explaining that the
part in the column header is not this project's, and in `cache/l2-spec.md`
§20.3 a twenty-line blockquote whose subject was the history of a retracted
milliwatt figure. Both were read to write this record.

Two things are wrong with that, and the project owner named both while
reviewing the work:

1. **A number in a table cell is read as data, whatever the paragraph above it
   says.** The mark protects the reader who reads the whole section; the
   figure misleads the reader who reads the row. Tables are read the second
   way.
2. **The annotation became the content.** The prose justifying why a figure
   should not be trusted grew longer than anything the figure was ever going
   to tell anyone, and it is archaeology: where a wrong number came from is not
   useful to the next reader. What would *produce* the right number is.

The owner's instruction, verbatim:

> instead of adding a big blob justifying retractation, we should just update
> table with unknown at this stage, need measurement and remove any unmeasured <!-- quoted verbatim -->
> data. we should still keep budget and goal in mind, but not any of those that
> looks like it is already done and known.

## Decision

**1. The test.** For every quantitative figure: *would a reader take this as
having been measured for this design, on one of this project's two targets?*
The targets are the Phase-1 ULX3S / Lattice ECP5 board `` `[FPGA]` `` and
gf180, the ASIC methodology vehicle `` `[ASIC]` `` ([0004](0004-platform-tag-convention.md)
§Context). If the answer is yes and it was not, the figure goes.

**2. It is removed, and its place says what is true.** The table cell, bullet
or sentence where it stood reads, verbatim:

> unknown at this stage — needs measurement

**One wording, everywhere.** Not "TBD", not "unmeasured", not "pending
synthesis" — a cell that says the same thing five ways cannot be found with one
grep, and the burn-down in §What would reopen this is exactly a grep.

**3. One forward-looking line is allowed; the archaeology is not.** A short
statement of **what would produce the real number** may follow — "`yosys` +
`nextpnr-ecp5` targeting the ULX3S 85F", "a gf180 gate-level run per Track D0".
Where the removed number came from, which vendor's part it described, and why
the previous convention kept it: **deleted.** This is the half of
[0004](0004-platform-tag-convention.md) §Marking convention that survives —
its third point — and the two that do not are its first and second.

**4. Budgets, goals and targets are kept, and must read as goals.** A target
frequency (~400 MHz+ `` `[ASIC]` ``, ~40 MHz `` `[FPGA]` ``), an area budget (the
ULX3S 85F's 208 EBRs, a LUT4 allowance), a tier-selection intent — these are
not results and were never claims about a measurement. They stay, because the
project needs something to aim at and to be judged against. Where one could be
misread as an achieved figure, the text says which it is: *goal*, *budget*,
*design intent*. Deleting the goals along with the results would be the
opposite defect and just as expensive.

**5. Structural and architectural values stay, and say so.** A value true by
construction is not an estimate and needs no measurement: the sysDSP/DSP48
column of zeros in `simd/hardware-impl.md` §11.1 (GF(2) multiply cannot use a
hard multiply block on any family — it follows from the algorithm), the
4096-entry AND array of a 64×64 carryless multiply, the 16 × 256 = 4,096
flip-flops of the J32 V register file, the EBR-capacity arithmetic in
`fpu/spec.md` §6.8/§6.9 and `cache/l2-spec.md` §20.1. Each such value states
that it is structural rather than measured, in the same breath as the value —
otherwise it is indistinguishable from the figures rule 2 removes. This
overlaps [0004](0004-platform-tag-convention.md) rule 6 (architectural
quantities need no platform tag) and does not replace it: rule 6 says such a
value needs no *tag*; this says it needs a *label*.

**6. Never a plausible substitute.** No figure is replaced by an estimate, a
scaled conversion, or a round number that looks about right.
[0004](0004-platform-tag-convention.md) rule 5 already forbids cross-family and
cross-node arithmetic and is unaffected by this record. The canonical phrase is
the answer, and it is a better one than any number nobody produced.

## Enforcement

**`unmeasured-figure-wording`** in `scripts/check-doc-facts.py` fails on:

- **either half of the canonical phrase used without the other.** This is
  rule 2's *one wording*, made mechanical: the phrase drifts the moment nothing
  holds it still, and a half-phrase is how the drift starts.
- **the retired marking convention's own signature phrase** reappearing
  anywhere in `docs/`. That is rule 3 closing behind itself: the convention
  this record supersedes cannot be reintroduced by someone who reads an older
  document and follows it.

Both literals live in the checker's source and are deliberately **not** spelled
out in this paragraph, so the text describing the rule does not trip it — the
same device [0004](0004-platform-tag-convention.md) §Enforcement uses to name
its four Xilinx family literals without failing its own check.

Like `stale-claim` in [0002](0002-supersede-convention.md), the check stands
down on a line that also carries one of a short list of quoting phrases
(`previously read`, `previously said`, `formerly read`, `used to read`,
`retired wording`, `quoted verbatim`), so a record like this one can quote what
it retired. The escape must be on the **same line** as the thing it excuses,
which 0002 argues for and which this record follows even where it costs
something: the one line here that quotes the owner's instruction word-for-word
carries its escape as a trailing HTML comment, because moving the excuse to the
lead-in line would have meant either editing a verbatim quote or letting an
escape drift away from what it excuses. The phrase list is written out
separately from `stale-claim`'s and `glossary-is-value-free`'s, not shared with
them, for the reason 0002 gives at length: the one time two of these escapes
shared a regex, a change made for one exempted 119 lines from the other in the
same commit.

**`platform-tag-foreign-part` is retained, unchanged and unweakened.** Under
this record the foreign figures it guarded are gone from the tree, so it now
has nothing to fire on — which is what a check looks like after it has done its
job, not a reason to delete it. It is the thing that notices if a Spartan/
Artix/Kintex/Virtex/Zynq figure is re-introduced *with a tag on it*, which is
the shape the next person to reach for an external datapoint will produce.

**What neither check does.** Neither can tell a measured figure from an
unmeasured one — that is a judgement about provenance, not a property of the
text, and [0004](0004-platform-tag-convention.md) §Enforcement's argument
against a general "untagged number" regex applies here word for word. A green
run means no *known-wrong* wording is present. It does not mean every figure in
the tree has been through rule 1's test; §What would reopen this lists what has
not.

## Rejected alternatives

**Keep 0004's marking convention.** Rejected on the owner's instruction and on
the evidence above: the mark does not reach the reader who reads a row, and the
prose outgrew the figure. Recorded rather than deleted, per
[0002](0002-supersede-convention.md) §1 — 0004 rule 3 was a real decision, made
for a real reason (a foreign figure was better than an invented one), and this
record agrees with that reason while rejecting the conclusion drawn from it.

**Delete the row, section or column outright.** Rejected. A missing row cannot
be told from a row nobody thought about, and a reader who needs the area of the
swizzle crossbar would find silence and conclude the question had not been
asked. The unknown cell keeps the *question* in the document while removing
the false answer, which is also what
[0002](0002-supersede-convention.md) §1 means by never silently dropping a
claim. Whole columns are the one exception: where every cell of a column would
read the same unknown, the column is dropped and the statement made once
underneath it, because five identical cells are noise, not information.

**A free-form marker — "TBD", "unmeasured", "pending synthesis".** Rejected:
see rule 2. The tree already contains all three spellings for other things, so
adopting any of them would make the burn-down grep return unrelated hits from
its first day.

**Substitute an ECP5/gf180 estimate scaled from the removed figure.** Rejected
for [0004](0004-platform-tag-convention.md) rule 5's reason, which this record
does not disturb: two logically identical RTL trees on this core, differing
only in the operand order of one `or`, synthesized 368 LUT4 apart on the ECP5
itself. A cross-vendor, cross-node ratio is worth less than that noise floor.

## What would reopen this

- **A synthesis or gate-level run lands.** `yosys`/`nextpnr-ecp5` on the ULX3S
  85F, or a gf180 run under Track D0: each unknown cell it answers is replaced
  by the measured number with its `` `[FPGA]` ``/`` `[ASIC]` `` tag, and the
  "what would produce it" line beside it is deleted rather than left as
  decoration.
- **The burn-down.** `grep -rn "unknown at this stage — needs measurement" docs/`
  is the list of what this project does not know about its own hardware. It
  should shrink.
  Today it covers `simd/hardware-impl.md` §4, §5.3, §6.2–§6.5, §11.1–§11.3 and
  `cache/l2-spec.md` §20.3 / Appendix B. It does **not** yet cover the files
  [0004](0004-platform-tag-convention.md) §"What this sweep covered" lists as
  unswept — those still hold untagged, unmeasured figures, and this record
  changes what should be done to them without having done it.
- **A figure that is neither measurement nor goal nor structure turns up.**
  Rules 2, 4 and 5 partition the cases this sweep met. A fourth kind — a
  literature value, say, carried deliberately as a design input — needs its own
  rule rather than being forced into one of these; `security/threat-model.md`
  §9's provenance scale (`SOURCED` / `LITERATURE` / `ESTIMATE` / `STRUCTURAL`)
  is where that vocabulary already exists.
