# 0002 — Supersede, RESOLVED and PENDING-MERGE headers

**Status:** Accepted 2026-08-25. Wave-1 task B0a, from
[j4-remediation-plan.md §B0](../j4-remediation-plan.md).

---

## Context

Specs in this workspace go stale in a specific, repeatable way: reality moves
(the hardware TSB walker lands, VFPUL is retired, the TLB protection vector
splits off `+0x400`), the spec that *owns* the change is updated, and every
section elsewhere that reasoned from the old world keeps reasoning from it,
silently, with nothing to mark it. A reader has no way to tell a live section
from a fossil.

The workspace already had two halves of a solution and no rule joining them:

- A **`HISTORICAL`** blockquote, used well in
  [mmu/design-spec.md §4.2](../mmu/design-spec.md) and
  [mmu/hardware-spec.md §7.1](../mmu/hardware-spec.md).
- A **`RESOLVED`** marker, used ~15 times in
  [mmu/security-review.md](../mmu/security-review.md) and elsewhere.

Neither had a grammar, and `RESOLVED` had no merge discipline at all: several
markers claimed resolution against a *branch*, and the branch has since been
rebased and merged, so the marker now points at nothing.

**Two failure modes, both observed in the tree today, both of which this record
exists to make impossible:**

1. **Status claims that outlive their own merge.** **Eleven** sections across
   `mmu/hardware-spec.md`, `mmu/design-spec.md`, `mmu/linux-spec.md` and
   `hypervisor/design-spec.md` carried a prose claim of the shape
   "IMPLEMENTED on `mmu/tsb-hw-walker` / `mmu/tsb-phase2`, **NOT MERGED**"
   for weeks. That is honest *when written*, and it is exactly what
   `PENDING-MERGE` is for — but nothing distinguished it from `RESOLVED` except
   prose, and nothing noticed when it *did* merge. All eleven are merged;
   nothing in the repository said so until this task looked, and both branches
   are now gone from their `origin`s. Note that this is the failure the marker
   grammar alone does **not** catch — see `stale-claim` under Enforcement.

2. **Citation by SHA, which rebasing silently invalidates.**
   `mmu/linux-spec.md §4` cites `jcore-cpu` `09304a3`/`957e940`;
   `mmu/hardware-spec.md §5.0` cites `90e6cbc`. Checked today with
   `git merge-base --is-ancestor` against `jcore-cpu` `origin/master`: **none of
   the three is an ancestor.** The branches were rebased before merge. The
   commits they describe are in `master`; the identifiers are not. Citing the
   subject line would have survived.

## Decision

### 1. Marker grammar (normative)

A marker is a Markdown blockquote placed as the **first content of the section**
it applies to, before any prose. Four forms, and only these four:

```markdown
> **SUPERSEDED BY <target> — <YYYY-MM-DD>.** <one or two sentences: what changed
> and what a reader should read instead.>

> **HISTORICAL <YYYY-MM-DD>.** <what this text is the record of.>

> **RESOLVED <YYYY-MM-DD> — <repo>@<integration-branch>: "<commit subject>".**
> <what the fix was.>

> **PENDING-MERGE <YYYY-MM-DD> — <repo> branch <branch>: "<commit subject>".
> Not on <integration-branch>.** <what the fix is.>
```

`<target>` is a document and section, as a Markdown link.

`SUPERSEDED BY` and `HISTORICAL` are siblings, not synonyms. Use
**`SUPERSEDED BY`** when the text is now *wrong* and something else is now right;
the reader is being redirected. Use **`HISTORICAL`** when the text is *accurate
about a past state* and is deliberately kept as the record of what a change
replaced — a cost baseline, a retired mechanism, a rejected proposal.

**A superseded section is never silently deleted.** This continues the practice
already set by [priv-arch/design-spec.md §4.5](../priv-arch/design-spec.md)
("Superseded proposal (recorded, not silently dropped)").

### 2. RESOLVED requires merge. This is the rule that does not bend.

A section may be marked **`RESOLVED`** only when the change is an **ancestor of
its repository's integration branch**:

| Repo | Integration branch |
|---|---|
| `jcore-cpu` | `master` |
| `linux` | `jcore` |
| `jcore-soc` | `master` |
| `binutils-gdb` | `jcore` |
| `gcc` | `master` |
| `gcc-sh-monitor` | `master` |
| `llvm-project` | `main` |
| `jcore-workspace` (this repo) | `main` |

**`INTEGRATION_BRANCH` in `scripts/check-doc-facts.py` is authoritative**; this
table is the readable copy of it. A marker naming a repo absent from the dict
fails `marker-grammar` rather than being assumed, so adding a submodule means
adding a row there first. (The two copies had already drifted: this table
omitted three of the repos the checker knew about.)

Anything else — implemented, reviewed, approved, sitting in an open PR, sitting
in a worktree — is **`PENDING-MERGE`**, and names the branch it is on.

**Submodule pointers in this superproject are not evidence of merge.** They lag
the integration branches by design and were pre-Wave-0 at the time this record
was written. Ask the submodule against `origin/<integration-branch>` after a
fetch, or ask `gh`.

### 3. Cite by subject line, not by SHA

A marker names `<repo>`, `<branch>`, and the **commit subject line, quoted
verbatim**. Not a SHA — see the three dead SHAs in §Context. A SHA is correct in
exactly one place: pinning a **measurement base**, where naming an exact tree
state is the entire point. Those are not affected by this rule.

Where several commits landed one change, cite the one whose subject names the
change (usually the `fix(...)`/`rtl(...)` commit, not the test or the docs
follow-up). Where no single commit names it, cite the merge commit's subject.

**Fallback: cite the artifact.** A rebase can leave a merged change with *no*
commit on the integration branch whose subject names it — the naming commit
survives only on a pre-rebase branch. The TLB vector split is exactly this case:
`jcore-cpu`'s *"mmu: split TLB protection faults onto VBR+0x100, as SH-4 does"*
exists only on `origin/mmu/encoding-realign-sh4a`, while the split itself is on
`master`. For these, cite the artifact instead:

```markdown
> **RESOLVED <YYYY-MM-DD> — <repo>@<branch>: artifact `<path>`.**
```

An optional ``containing `<symbol>` `` clause makes the citation say what the
artifact must actually *contain*, which is the difference between "a file with
this name exists" and "the change is in it":

```markdown
> **RESOLVED <YYYY-MM-DD> — <repo>@<branch>: artifact `<path>` containing `<symbol>`.**
```

The checker verifies the path exists on `origin/<branch>`, and that the symbol is
in it, distinguishing "grep ran and found nothing" (a failure) from "grep could
not run" (a skip). Those two used to collapse into one code path; the verdict was
right for the wrong reason, and a genuine git error would have been reported as a
missing symbol. Prefer this form over
a weak subject citation: an artifact is *stronger* evidence than a subject line,
because it is the thing itself rather than a claim about it. Prefer a naming
subject over an artifact when one exists, because it also says *why*.

### 4. Promotion is the maintenance obligation

When a `PENDING-MERGE` branch merges, the marker is **promoted** to `RESOLVED` in
the same change that would have updated it. When a `PENDING-MERGE` branch is
abandoned, the marker is **deleted** along with whatever it claimed. A
`PENDING-MERGE` marker whose branch no longer exists on `origin` is a defect in
one direction or the other.

## Enforcement

`scripts/check-doc-facts.py` (the same script that enforces
[0001](0001-one-authority-per-fact.md)) implements the four supersede checks
below. It resolves markers against the submodules'
`origin/<integration-branch>` refs.

**Every marker on a line is examined, not the first.** A line carrying a valid
marker *and* a bare legacy one used to hide the second — which is precisely the
shape §4 tells people to write when they promote something, so the blind spot sat
exactly where the convention directs traffic. It also let a marker line carry an
unchecked prose status claim.

| Check | Failure | Notes |
|---|---|---|
| `marker-grammar` | A marker keyword on a line that no `SUPERSEDED BY` / `RESOLVED` / `PENDING-MERGE` / `HISTORICAL` marker accounts for; also a `PENDING-MERGE` whose "Not on …" names the wrong integration branch, or any marker naming an unknown repo | Legacy unstructured markers are listed in the registry's waiver list under the `legacy-marker` ID and are **noted** (visible with `-v`), not warned; the list may only shrink |
| `resolved-is-merged` | A `RESOLVED` marker whose quoted subject is **not** on `<repo>`'s integration branch, or whose cited artifact (or symbol within it) is not there | This is the check the task asks for, and it is mechanical. It catches both "resolved too early" and "cited a rebased-away commit" |
| `pending-is-not-merged` | A `PENDING-MERGE` marker whose quoted subject **is** on the integration branch, **or** whose branch no longer exists on that repo's `origin` | Both fail. §4 calls a marker whose branch is gone "a defect in one direction or the other", so reporting it as an advisory warning contradicted this record |
| `stale-claim` | Any line asserting *not merged* in prose, outside the marker grammar | See below. This is the one that covers the notices that actually rotted |

**`stale-claim` exists because the marker checks did not cover the failure that
happened, and the first version of this record said they did.** All eleven of
this tree's implemented-but-unmerged notices used a prose form —
`**Amendment — Phase 2. Status: IMPLEMENTED on <branch>, NOT MERGED.**` — which
carries no marker keyword and therefore matched nothing in the grammar above.
`pending-is-not-merged` protects *future* `PENDING-MERGE` markers and could
never have caught a single one of the eleven. `stale-claim` is what closes the
class: it flags the phrase itself, wherever it appears, and it independently
rediscovered the four notices that the first pass of this task promoted only
seven of.

Quoting a claim you have just retired is legitimate and common in a promotion
note, so `stale-claim` stands down when the line also carries `promoted from`,
`previously read`, `previously said`, `formerly read` or `used to read`. Keeping
the retired wording on the *same line* as the phrase that excuses it is
deliberate: it means the excuse cannot drift away from the thing it excuses.

**That exemption is `stale-claim`'s own, and must stay that way.** It briefly
shared a regex with the glossary's equivalent in
[0001](0001-one-authority-per-fact.md), and widening the shared regex to
`retired|no longer` — a change made for the glossary, with no thought of this
check — **exempted 119 lines across 22 files from `stale-claim` in the same
commit that introduced it**. Appending "the old walker is retired" to a line was
enough to excuse a `NOT MERGED` sitting on it. The two escapes are now two separately
written phrase lists with identical contents (`STALE_CLAIM_PHRASES` here,
`GLOSSARY_QUOTE_PHRASES` for the glossary). The duplication is deliberate and
must not be refactored away: a first attempt built both from one shared literal,
which left the coupling exactly where it was under two new names. If you are
tempted to add a phrase, add it to one list and decide about the other on
purpose. `scripts/test-check-doc-facts.py` widens one list in a patched copy of
the checker and asserts this check is unmoved.

Note the shape of that failure, because it is the one this whole task keeps
producing: a check written to close a hole, which opens a different one in the
same commit, and a suite that goes green because it tests the case the author
was thinking about.

Waiver IDs are per **check**, not per file: `legacy-marker` and `stale-claim` are
separate rows, so exempting a file from one does not exempt it from the other.
They used to share a lookup, which gave `mmu/security-review.md` a blanket
`stale-claim` exemption its waiver row never asked for.

### Skips, and why CI must pass `--strict`

Verification needs the submodule present with a fetched `origin`. When it is not,
the affected check is reported as a **SKIP** naming what could not be verified.
Without `--strict` a skip still exits 0.

**That is a trap for CI and is called out here because it will bite otherwise.**
A checkout without `submodules: recursive` skips *every* `RESOLVED` marker — 50
of them at the time of writing — and reports success having verified none. So:

> **B0c must run `scripts/check-doc-facts.py --strict --check-waivers` with the
> submodules checked out and fetched.** Under `--strict` a skip is a failure, so
> a submodule-less run fails loudly instead of passing vacuously.

`--check-waivers` additionally fails on a waiver row that never fired, so the
waiver list cannot outlive the restatements it covers.

**A shallow clone is the same trap wearing a different hat, and it was open for
longer.** `resolved-is-merged` asks `git log --format=%s origin/<branch>`. On a
shallow clone that returns a *truncated* history and **exit 0** — the answer
looks complete and is not. Both submodules in this workspace were shallow when
this was found (`jcore-cpu` showed 115 subjects against 1080; `linux` 537), so
every local run was answering from a fraction of the history: a `RESOLVED`
marker citing a real commit before the graft boundary **fails**, and a
`PENDING-MERGE` citing one **passes** — the fail-open direction — with nothing
in the output saying why the verdict might be wrong.

**But a truncated history is incomplete in only one direction, and the check
follows that exactly.** `git log` emits only commits genuinely reachable from
the branch — grafting removes commits, it never invents them — so a subject that
**is** found is a true positive at any depth. Only *absence* is ambiguous: the
commit may lie beyond the graft boundary, or may not exist. So the resolution is
three-way, not two:

| | subject found | subject absent |
|---|---|---|
| **complete history** | PASS | FAIL |
| **shallow history** | PASS | SKIP (a `--strict` failure) |

The first version skipped every marker naming a shallow repository. That was
fail-closed, but stricter than the question requires: it made `--strict`
unusable until someone unshallowed a multi-gigabyte repository, for markers
whose answer was already known. A gate that demands that gets worked around. The
table above keeps the fail-closed property exactly where the answer is genuinely
unknown and nowhere else. "Could not determine the depth" is treated as shallow,
for the same reason.

The fix on a developer's machine is `git -C <sub> fetch --unshallow
--filter=tree:0`; in CI it is `--filter=tree:0` at clone time, never `--depth`.

### The subject is only as strong as the namespace it is searched in

Unshallowing exposed a second, larger problem, and it is a problem this record
created: §3 chose subject-line citation, and the depth rule above then made a
found subject a PASS at any depth. Both are right in isolation. Together they
searched **1,462,492** commit subjects for a citation that names one of this
project's own changes — 1,410,912 of them distinct, **19,683** shared by more
than one commit, and **445** already beginning `sh: fix`, which is this
project's own convention. A `RESOLVED` marker citing *"sh: Fix build with
CONFIG_UBSAN=y"* — a real commit, unrelated to anything here — passed. The
mirror is the same defect the other way up: a *correct* `PENDING-MERGE` citing
that subject was forced red with "which IS on the branch. Promote it."

That is the wrong haystack, not a bad rule. A marker cites a change **this
project** made, and on a kernel fork those are a rounding error next to the
history they sit on: `linux` `origin/jcore` carries 1,462,492 commits, of which
**74** are the project's. So the search is scoped to
`origin/<base>..origin/<integration-branch>`, with the base declared per
repository in `UPSTREAM_BASE` (`linux` → `master`; `jcore-cpu` has none, because
all 1080 of its commits are the project's own and none of its subjects repeats).
Verified when this landed: all 12 distinct live markers resolve to exactly one
commit under this scoping, and none of the 7 `linux` ones exists upstream.

**And a subject that names several commits names none of them.** Resolution is
now by count: 0 → absent (the depth table above), 1 → merged, more than 1 →
**fail**, because the citation has stopped identifying a change even though all
the candidates are on the branch. The remedy in that message is to reword the
subject or use the artifact form.

**What this still does not prove, stated plainly because the check's name
overpromises.** A subject citation establishes that *a commit with this subject
is on the branch*. It does not establish that the commit is the change the
marker is about. No string-matching scheme can: scoping shrinks the haystack by
19,700× and ambiguity detection removes the coin flips, but a marker citing a
real, in-scope, unique commit that has nothing to do with its section will pass.
That is the residual, and it is why §3 already prefers the **artifact** form
where identity matters — an artifact is the thing itself rather than a claim
about it. A reviewer who wants certainty should ask for one.

One further hazard found by actually doing this, recorded because it was hidden
by the shallow clone and appeared the instant it was not: **commit subjects are
bytes, not text.** The Linux history contains subjects that are not valid UTF-8,
and reading the log with a strict decode raised `UnicodeDecodeError` *inside
`subprocess`* — neither an answer nor a skip, but a traceback, from a checker
whose entire purpose is to produce verdicts. The log is now read with
`errors="replace"`, which degrades a mangled subject into one that simply does
not match, and "does not match" is a case the table above already handles.

### What is convention here and not check

Two requirements in §1 are **not** machine-checked, and are listed so nobody
mistakes a green run for compliance with them:

- **Marker position.** "First content of the section, before any prose" is a
  convention. Determining a section's first content reliably means parsing
  Markdown structure, which is more machinery than the rule is worth; review
  catches it.
- **Choosing `SUPERSEDED BY` vs `HISTORICAL` correctly.** Both parse. Whether the
  text is *wrong* (supersede) or *accurate about a past state* (historical) is a
  judgement no regex reaches.

`Not on <branch>.` in a `PENDING-MERGE` marker **is** checked, and the named
branch must be the repo's integration branch.

One honest note on coverage: there are currently **zero** real `PENDING-MERGE`
markers in the tree, so `pending-is-not-merged` and the branch-existence lookup
have never run against live data. They are covered only by fixtures.

## Rejected alternatives

- **Marker by SHA, resolved with `git cat-file`.** Rejected: it is the failure
  already in the tree. A rebase before merge — this project's normal flow —
  destroys the citation, and the check then fails on *correct* documentation,
  which trains people to ignore it.
- **A single `RESOLVED` state with prose saying whether it merged.** Rejected:
  that is what exists today. Prose is not checkable, and the distinction is the
  one the reader most needs — "is the thing I am about to depend on in the tree
  I am about to build?"
- **Deleting superseded text instead of marking it.** Rejected: it destroys the
  record of what was tried and why it was replaced, which is the material the
  next reviewer needs most, and it contradicts the practice already established
  in `priv-arch/design-spec.md` and `simd/spec.md`'s Appendix B decision log.

## What would reopen this

- **A repo gains a second long-lived integration branch** (a release branch, say)
  so that "merged" stops being a single question. The table in §2 would then need
  a per-target answer, and `RESOLVED` would need to name its target.
- **`resolved-is-merged` starts failing on subject lines that were legitimately
  reworded on merge** (squash-and-edit). If that becomes common, the citation key
  has to become something stabler than the subject — a `Change-Id`-style trailer
  is the usual answer — and §3 changes.
