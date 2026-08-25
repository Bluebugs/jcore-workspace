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

1. **`RESOLVED` against unmerged work.**
   [mmu/hardware-spec.md §5.0](../mmu/hardware-spec.md) and
   [mmu/linux-spec.md §4, §4.3](../mmu/linux-spec.md) carried
   "IMPLEMENTED on `mmu/tsb-hw-walker` / `mmu/tsb-phase2`, **NOT MERGED**"
   for weeks. That is honest, and it is exactly what `PENDING-MERGE` is for —
   but nothing distinguished it from `RESOLVED` except prose, and nothing
   noticed when it *did* merge. Both are merged now; nothing in the repository
   said so until this task looked.

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
| `jcore-workspace` (this repo) | `main` |

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

The checker verifies the path exists on `origin/<branch>`. Prefer this form over
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
[0001](0001-one-authority-per-fact.md)) implements three supersede checks. It
resolves markers against the submodules' `origin/<integration-branch>` refs.

| Check | Failure | Notes |
|---|---|---|
| `marker-grammar` | A `SUPERSEDED BY` / `RESOLVED` / `PENDING-MERGE` marker that does not parse | Legacy unstructured markers are listed in the registry's waiver list and warn rather than fail; the list may only shrink |
| `resolved-is-merged` | A `RESOLVED` marker whose quoted subject is **not** on `<repo>`'s integration branch | This is the check the task asks for, and it is mechanical. It catches both "resolved too early" and "cited a rebased-away commit" |
| `pending-is-not-merged` | A `PENDING-MERGE` marker whose quoted subject **is** on the integration branch | Fails with "promote to RESOLVED". This is the check nothing in the repository had, and it is why five stale `NOT MERGED` notices survived their own merges |

Verification needs the submodule present with an `origin` remote fetched. When a
submodule is absent the script **warns and skips**, and says which checks it
could not run — it never reports a pass it did not perform.

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
