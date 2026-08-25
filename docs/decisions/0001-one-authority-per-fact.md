# 0001 — One authority per fact; the glossary is an index, not an authority

**Status:** Accepted 2026-08-25. Wave-1 task B0a, from
[j4-remediation-plan.md §B0](../j4-remediation-plan.md).

---

## Context

[glossary.md](../glossary.md) opened with:

> This document is the single source of truth for naming. If another doc
> disagrees with this one, this one wins and the other doc is wrong.

That sentence was false when it was read for this task, and it had been false
for over a month. Three instances, each verified in the tree today rather than
recalled:

| Glossary said | Reality | Since |
|---|---|---|
| **VFPUL** is a SIMD-side scalar FP register, and the four `FMOV.VS`/`FMOV.VD` boundary instructions move values across it | VFPUL is **retired**; FP reductions write `FR0`/`DR0` directly and the boundary instructions are **deleted**. [simd/spec.md §2.3, §5.8, changelog](../simd/spec.md) | 2026-07-17 |
| SIMD per-task context image is **272 bytes** | **520 bytes** on J32, 1036 on J64. [simd/spec.md §2.5](../simd/spec.md) | same change |
| Every product point J2…J64 is **little**-endian | The shipping J2 target is `sh2eb-linux-muslfdpic` — **big**-endian ([fgmt/dual-fgmt-proposal.md §7](../fgmt/dual-fgmt-proposal.md), [isa-density/software-impl.md §7](../isa-density/software-impl.md)), and [fgmt/mt2x2-plan.md §9 Q3](../fgmt/mt2x2-plan.md) records the conflict as an open decision | never true for J2 |

The *authoritative* document was the stale one. The specs that actually own
those facts — `simd/spec.md`, which retired VFPUL in a dated changelog entry —
were correct and current. That is the whole finding, and it is an argument from
this repository's own history rather than from taste: **a fact stays correct in
the document whose author is editing it, and rots in every copy of it.** The
glossary held copies.

There is already one document that states the target model in so many words.
[bus/fabric-spec.md](../bus/fabric-spec.md), "Specs that depend on this
document" table, on the glossary's BMID entry: *"The glossary is the short reference; this doc is the
long one."* That is the arrangement below, and it is the one that did not fail.

## Decision

**The glossary is demoted to a glossary, and every normative constant has
exactly one owning spec.** Concretely:

1. `docs/glossary.md` defines **terms** — what a word means, what it is not to be
   confused with, and which spec owns it. It carries **no normative numeric
   value, bit position, address, or encoding.** Where a term has a value, the
   glossary names the owner and links to it, and stops.

2. Every normative constant is listed in [fact-ownership.md](../fact-ownership.md)
   with exactly one owning document and section. That registry — not the
   glossary — is the index a reader starts from.

3. A non-owning document **may** restate a constant when the prose needs it, but
   only with a link to the owner on the same line. A bare restatement is a
   defect.

4. Facts that are genuinely undecided are recorded in the registry as
   **UNRESOLVED**, naming the task that owns the decision. Endianness is the
   first such row (owner: Wave-2 task B1). A registry that hides its holes is
   the same failure in a new file.

## Enforcement

An unenforced convention is what produced the problem, so the convention lands
with its check: **`scripts/check-doc-facts.py`**, exit non-zero on failure. It
has no dependencies beyond Python 3 and `git`. Its own tests are
`scripts/test-check-doc-facts.py`, which build fixture trees via `--root` —
see "how this check is tested", below, because that part has already been got
wrong once.

| Check | What it fails on | Why this one |
|---|---|---|
| `owner-has-fact` | The owning document no longer contains its own registered constant | Catches an owner changing a value without updating the registry — the registry cannot silently outlive the fact |
| `glossary-is-value-free` | `docs/glossary.md` carrying a value-**shaped** token at all: `N bytes`, `N-bit`, `0x…`, `bit N` | The structural rule; see below for exactly how strong the claim is |
| `restatement-is-linked` | A non-owning document restates a registered constant with no link to the owner on that line | Catches new bare copies. Existing ones are enumerated in the registry's waiver list, which may only shrink |
| `registry-value-is-short` | A registry `Constant` cell longer than 100 characters | See "the gap this does not close", below |
| `registry` | The registry is missing, has no `## Registry` table, has zero rows, or has a malformed row | Fails **closed**: a registry that parses to nothing would disable every check above while still exiting 0 |

Decision rule **1** — the glossary carries no values — is the load-bearing one.
Rules 3 and 4 are hygiene. Rule 1 is what makes the decision self-enforcing,
because it does not depend on anyone remembering the decision; it depends on a
file being value-free, which a machine can see.

### How strong the `glossary-is-value-free` claim is

An earlier draft of this record said the check "makes the class of failure that
produced VFPUL/272 **impossible**". That was false as implemented, and the way it
was false is instructive. The check then grepped the glossary for the registry's
**current** value patterns — so it fired on `520 bytes` (harmless, the right
answer) and was **silent** on `272 bytes` (the actual bug, because a stale value
matches no current pattern by construction). It also exempted any line linking
its owner, and by then nearly every glossary entry linked its owner. It was
`restatement-is-linked` scoped to one file, wearing another name.

The check now scans for value **shapes**, independent of the registry and
independent of links. A stale value is caught exactly as readily as a current
one, which is the property the claim needs. Measured on this glossary the scan
produced 23 hits and no false positives; years, product names (`ECP5`, `4.4BSD`,
`SPARC v9`) and section references do not match, because none of them is a number
followed by a unit.

The claim, stated at the strength it actually holds: **an unfenced value cannot
survive in `docs/glossary.md`.** Two escapes exist and both are visible:

- A line that is *retiring* the value it quotes (`retired`, `no longer`,
  `formerly read`, …). Without this the glossary could not record its own
  history, which is worse.
- A declared `<!-- value-free: off -->` fence. A fence must be closed, and must
  have a `glossary-fence` row in the registry's Waivers table or the check fails
  — so an exemption appears both where it applies and where exemptions get
  reviewed. There is exactly one today, on the product table's `Addr width`
  column, and B1 is named to remove it.

**Waivers are refused outright.** The checker fails if a waiver row targets
`docs/glossary.md`. The fence is deliberately *not* a waiver: it is narrower, it
is legible in the file it affects, and it is counted.

### The gap this does not close, stated rather than papered over

`owner-has-fact` greps the registry's **pattern** against the owning document.
It never reads the registry's own **prose**. So a `Constant` cell can describe a
mechanism that the owner has since retired, and every check still passes — which
is exactly what happened on this decision's first commit: the
`mmu.asidtag.width` row read "16 bits (12-bit ASID + 4-bit generation)" while the
owner's own supersede header, added in the same commit, said the generation
nibble no longer exists. The index that replaces the glossary reproduced the
glossary's failure on day one.

**What was decided.** Not to add prose-vs-owner checking: it needs a second
pattern per row describing what the owner must *not* say, and a negative pattern
is defeated by the owner legitimately quoting the retired text inside its own
supersede header — which every superseded section here does. The check would
have to be wrong or noisy.

Instead the room for drift is removed: **a `Constant` cell states the value, not
the mechanism**, capped at 100 characters and enforced by
`registry-value-is-short`. It is a crude bound, and it is the same move as
`glossary-is-value-free` — make the prose too short to hold an explanation, so
there is nothing to go stale, rather than trusting a rule to be remembered.
Explanation belongs in the owning spec, where `owner-has-fact` and B0c's
doc-vs-code checks both reach it.

### How this check is tested, and why it is not tested against this tree

`scripts/test-check-doc-facts.py` builds a throwaway tree per case and runs the
checker against it with `--root`. It asserts **exit status**, so a check that
does not exist fails the test rather than quietly passing.

This is a correction, not a preference. The first version of the suite mutated
the real `docs/` and asserted the checker went red. Every case therefore
exercised its check in the single configuration this tree happens to have, and
the suite reported nine-for-nine while six fail-open paths sat underneath —
among them a `glossary-is-value-free` blind to the exact bug it was named for,
and a registry parser that disabled all of 0001 if you renamed a heading. Two
further traps in that suite are worth naming because both nearly shipped: a
mutation that made the script crash was scored as a **pass** (it grepped for
`FAIL` instead of checking exit status), and a mutation applied to text the check
did not read was scored as a **gap in the check**.

Testing a guard against the tree it guards tells you the guard runs. It does not
tell you the guard would catch anything. That distinction is the same one the RTL
guards in this project keep re-learning, one level up.

Residual risk, named: a cell can still be wrong within 100 characters. B0c
inherits the table and is the check that compares each row's owner to the code.

**What this check does not do**, stated so nobody relies on it wrongly: it does
not compare a document against the **code**. A spec can own a fact, satisfy
every rule here, and still disagree with the RTL. That is Wave-1 task **B0c**
(doc-vs-code CI: page size, TSB entry size and offsets, P4 register offsets,
context image sizes). The two compose deliberately — B0a decides *which single
document* is checked against the code for a given constant, and B0c does the
checking. Under the rejected alternative, B0c would have had to check two.

## Rejected alternative — (a) make the glossary truly authoritative and derive

The alternative was to keep the authority claim, fix the three stale entries, and
have the specs *derive* their repeated constants from the glossary rather than
restate them. Rejected on three grounds, in increasing order of severity.

**1. There is no derivation mechanism, and the one that would work is not the
glossary.** These are Markdown files; Markdown has no include. Making derivation
real means either a generator (a machine-readable source plus a substitution
pass over every spec) or a CI check that greps the specs and compares to the
glossary. The generator route is the honest one — and it immediately stops being
option (a), because the authority becomes the *data file*, not `glossary.md`.
The repository has already chosen exactly that shape once, for the one class of
fact where it pays: encodings live in `docs/insns.json`, generated into the
toolchain tables, with `insns2asm --emit check` as the oracle. Nobody proposed
that the glossary own encodings. The remaining constants are perhaps a few dozen
scalars, which is far below the threshold where a generator earns its
maintenance.

**2. It preserves duplication, which is the actual defect.** Under (a) the value
of the SIMD context image exists in `simd/spec.md` *and* in `glossary.md`, and
every change must land in both, atomically, forever. That is precisely the edit
that was not made on 2026-07-17 and precisely why the glossary read 272 while the
spec read 520. Option (a) asks a document that has already failed to hold this
invariant to hold *more* of it. Option (b) deletes the second copy, so the
invariant has nothing to violate.

**3. It puts the authority furthest from the work.** The person who changes the
SIMD context image is editing `simd/spec.md`. Under (b) that edit is complete
when they finish it. Under (a) it is complete only when they also remember a
file they had no reason to open. The empirical record above is that they do not.

A fourth, narrower objection, recorded because it bit during this very task:
fixing the glossary's endianness row *requires deciding endianness*, which is
assigned to Wave-2 task **B1** and is not B0a's to make. Option (a) cannot be
executed without either pre-empting B1 or shipping a document that still claims
authority while carrying a known-false row — i.e. shipping the original bug.
Option (b) resolves this cleanly: the registry records endianness as UNRESOLVED
with B1 named, and the glossary's product table is marked non-normative on that
column pending B1.

**The honest cost of (b), not glossed over.** A reader who wants a value now
looks in two places instead of one: the registry, then the owning spec. That is
one extra hop, and the mitigation is that the hop is always *the same shape* —
the registry is a single table with a link per row, and the glossary continues to
name the owner for every term it defines. It is a worse experience than a correct
single document would be. It is a better experience than the incorrect single
document we actually had, which cost readers a hop *and* gave them a wrong
answer at the end of it.

## No third option was invented

The task allowed a hybrid only on a showing that both (a) and (b) are
unworkable. (b) is workable, so no hybrid was constructed. Note in particular
that "glossary keeps the pointer, spec keeps the value" is **not** a hybrid — it
is what a glossary is. The demotion is real: the glossary loses the right to
carry a value and the right to win a disagreement.

## What would reopen this

- **The scalar-constant count grows past roughly a hundred**, or constants start
  needing to be consumed by tools as well as read by humans. At that point the
  `insns.json` pattern — a machine-readable source generated into the docs —
  starts to earn its maintenance, and the answer becomes "a data file is the
  authority", which is neither (a) nor (b).
- **`check-doc-facts.py`'s waiver list stops shrinking across two waves.** That
  would mean the restatement rule is being worked around rather than complied
  with, and the rule needs to change rather than be re-asserted.
- **`registry-value-is-short` starts being fought** — rows that genuinely need
  more than 100 characters to state a value, as opposed to to explain one. That
  would mean the cap is standing in for a check that should exist, and the
  prose-vs-owner question reopens.
