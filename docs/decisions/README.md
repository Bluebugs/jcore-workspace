# Decision records

**This directory is new (created 2026-08-25 by Wave-1 task B0a).** Before it, the
workspace had no decision-record convention. It had a *practice*, which is
different and which stays: a decision about a subsystem is written **inline, in
the spec that owns the subsystem**, together with the alternative it rejected.
Two worked examples of that practice, both good, both retained:

- [priv-arch/design-spec.md §4.5](../priv-arch/design-spec.md) — "**Decision
  (RESOLVED — collision closed)**" followed by "**Superseded proposal (recorded,
  not silently dropped)**".
- [soc/p4-mmio-map.md §7](../soc/p4-mmio-map.md) — "**Three-way conflict at
  `0x020`/`0x024`/`0x028` — RESOLVED**".

**The rule: a decision goes inline in its owning spec whenever there is one.**
This directory exists only for decisions that have *no* owning spec — decisions
about the documentation system itself, about cross-cutting process, or about
which document owns what. Putting those inline would require choosing a host
spec arbitrarily, and an arbitrarily-hosted rule is a rule nobody knows to read.

**A worked application of that rule, 2026-09-08.** The bi-endian decisions BE-1
to BE-3 are **not** in this directory, and deliberately so: they are decisions
about the machine, and
[bi-endian-spec.md](../bi-endian-spec.md) is the spec that owns the mechanism,
so they go inline there. [0006](0006-endianness-is-big-endian.md) stays here
because what *it* decides is a product-line property with no owning subsystem —
which is why it needed a new owning document ([platform-baseline.md](../platform-baseline.md))
to be created for the value in the first place.

## Format

One file per decision, `NNNN-kebab-case-title.md`, numbered in landing order.
Each record carries, in this order:

1. **Status** — `Accepted` / `Superseded by NNNN` / `Withdrawn`, and a date.
2. **Context** — what forced the decision, with evidence. Claims about the tree
   are verified against the tree, not remembered.
3. **Decision** — the thing decided, stated so it can be complied with.
4. **Enforcement** — the mechanical check that makes it true. A decision with no
   enforcement is a preference, and this project has already paid for the
   difference; see [0001](0001-one-authority-per-fact.md) §Context.
5. **Rejected alternatives** — recorded, not silently dropped, with the argument
   that killed each.
6. **What would reopen this** — the trigger to revisit, per the remediation
   plan's guiding principle 4 ("this plan is a hypothesis tree").

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-one-authority-per-fact.md) | One authority per fact; the glossary is an index, not an authority | Accepted 2026-08-25 |
| [0002](0002-supersede-convention.md) | Supersede, RESOLVED and PENDING-MERGE headers | Accepted 2026-08-25 |
| [0003](0003-canonical-encoding-database.md) | One encoding database: `jcore-cpu/docs/insns.json` | Accepted 2026-08-25 |
| [0004](0004-platform-tag-convention.md) | Platform tags: `[FPGA]` / `[ASIC]`, and which numbers need one | Accepted 2026-09-07; rules 3–4 and §Marking convention superseded by [0005](0005-unmeasured-figures-are-removed.md) |
| [0005](0005-unmeasured-figures-are-removed.md) | An unmeasured figure is removed, not annotated | Accepted 2026-09-07 |
| [0006](0006-endianness-is-big-endian.md) | J-Core ships big-endian; byte order is a per-context mode, not a product-point property | Accepted 2026-09-07, re-scoped twice 2026-09-08; fetch half superseded by [bi-endian-spec.md](../bi-endian-spec.md) |
| [0007](0007-l1d-write-policy-under-msi.md) | The L1-D is write-through at T0 and write-back under MSI at T1/T2 | Accepted 2026-09-07 |
| [0008](0008-documented-but-unimplemented-encodings.md) | A documented-but-unimplemented instruction is a reservation row, not a decoder entry | Accepted 2026-09-08 |
