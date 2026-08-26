# Fact ownership registry

**One authority per fact.** Every normative constant in this workspace has
exactly one owning document and section, listed below. This registry is the index
a reader starts from; [glossary.md](glossary.md) defines *terms* and names owners,
and carries no values of its own.

The decision and its argument: [decisions/0001](decisions/0001-one-authority-per-fact.md).
The rules a non-owning document must follow when it mentions a registered
constant, and the checks that enforce them, are in that record's *Enforcement*
section. In one line: **restating a value is allowed only with a link to the
owner on the same line; a bare copy is a defect.**

Enforced by `scripts/check-doc-facts.py`, run from the workspace root.

> **Scope, stated so this file is not mistaken for something it is not.** This
> registry records which *document* owns a fact. It does not certify that the
> document agrees with the *code*. That is Wave-1 task **B0c** (doc-vs-code CI),
> and it consumes this table: for each row, B0c knows which single file to check
> against the RTL or the kernel.

---

## Registry

The `Pattern` column is the Python regular expression the checker uses to
recognise the constant in prose. Keep it tight enough to avoid unrelated hits and
loose enough to catch a restatement.

**The `Constant` column states a value; it does not explain a mechanism**, and is
capped at 100 characters by `registry-value-is-short`. This is not tidiness: on
this file's first commit the `mmu.asidtag.width` row described a generation
nibble that its own owner's supersede header, added in the same commit, said had
been retired. Nothing caught it, because no check reads this prose. Short cells
are the substitute for a check that cannot be written cleanly — see
[decisions/0001 §Enforcement](decisions/0001-one-authority-per-fact.md).

| ID | Constant | Owner | Pattern |
|---|---|---|---|
| `simd.vfpul` | VFPUL: **retired**, no such register | [simd/spec.md §2.3](simd/spec.md) | `\bVFPUL\b` |
| `simd.context.j32` | SIMD per-task context image, J32: **520 bytes** | [simd/spec.md §2.5](simd/spec.md) | `\b520[- ]byte` |
| `simd.context.j64` | SIMD per-task context image, J64: **1036 bytes** | [simd/spec.md §2.5](simd/spec.md) | `\b1036[- ]byte` |
| `simd.sr.vd` | `SR.VD` is **SR bit 13** | [simd/spec.md §2.6](simd/spec.md) | `SR bit 13` |
| `fpu.context.t2` | Tier-2 FPU context image: **136 bytes** | [fpu/spec.md §7.4](fpu/spec.md) | `\b136[- ]byte` |
| `fpu.sr.fd` | `SR.FD` is **SR bit 15** | [fpu/spec.md §6.3](fpu/spec.md) | `SR bit 15` |
| `mmu.asid.width` | ASID proper: **12 bits** (4096 ASIDs) | [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md) | `12-bit ASID\b` |
| `mmu.asidtag.width` | `ASID_TAG`: **16 bits** (12-bit ASID; top nibble reserved, always zero) | [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md) | `16-bit .?ASID_TAG` |
| `mmu.page.base` | Base page size: **16 KB** | [mmu/design-spec.md §3.3](mmu/design-spec.md) | `16 KB base page` |
| `mmu.tsb.entry` | TSB entry: **16 bytes** | [mmu/hardware-spec.md §2.8](mmu/hardware-spec.md) | `16-byte entr` |
| `mmu.tsb.set` | TSB set: **32 bytes, 2-way** (way 0 at `+0`, way 1 at `+16`) | [mmu/hardware-spec.md §2.8](mmu/hardware-spec.md) | `32-byte (set\b\|cache line)` |
| `mmu.tsb.tag.shift` | TSB tag granularity: **4 KB**, `JCORE_TSB_TAG_SHIFT` = 12 — never `PAGE_SHIFT` | [mmu/hardware-spec.md §7](mmu/hardware-spec.md) | `JCORE_TSB_TAG_SHIFT` |
| `mmu.vector.miss` | TLB **miss** vector: `VBR + 0x400` | [mmu/hardware-spec.md §5](mmu/hardware-spec.md) | `VBR ?\+ ?0x400` |
| `mmu.vector.prot` | TLB **protection** vector: `VBR + 0x100` — *not* `0x400` | [mmu/hardware-spec.md §5](mmu/hardware-spec.md) | `VBR ?\+ ?0x100` |
| `mmu.mmufsr.addr` | `MMUFSR` at P4 offset `0x02C` (`0xFF00002C`) | [soc/p4-mmio-map.md §3.2](soc/p4-mmio-map.md) | `0xFF00002C\|0x0?2C.{0,12}MMUFSR\|MMUFSR.{0,12}0x0?2C` |
| `bus.bmid.width` | `BMID`: **8 bits**, `0x00`/`0xFF` reserved | [bus/fabric-spec.md §4](bus/fabric-spec.md) | `8-bit BMID` |
| `hyp.expevt.hcall` | `HCALL`: EXPEVT `0x1D0` at `VBR_HYP + 0x180` | [hypervisor/hardware-spec.md §4.2](hypervisor/hardware-spec.md) | `0x1D0` |
| `hyp.expevt.hypreg` | Hyperprivileged-register access: EXPEVT `0x1F0` at `VBR_HYP + 0x300` | [hypervisor/hardware-spec.md §4.2](hypervisor/hardware-spec.md) | `0x1F0` |

This is a seed, not a census. Rows are added as facts are reconciled; Wave-2 task
**B1** works a contradiction worklist and each item it settles becomes a row here.

## Code bindings

The Registry above says which *document* owns a constant. This table says where
the same constant lives in the **code**, and `doc-matches-code` fails when the
two disagree. Wave-1 task **B0c**; the argument is in
[decisions/0003](decisions/0003-canonical-encoding-database.md) §"Doc-vs-code".

**A binding row states no value.** It names two regular expressions — one read
against the owning document, one against a file in a submodule — each with
**exactly one capture group**, and a relation the two captures must satisfy. A
row that restated the number would be a third copy of it, and
[0001](decisions/0001-one-authority-per-fact.md) is a record about what happens
to copies. This row can go stale only by ceasing to match, which is a failure.

`Code` is `<repo>:<path>`, read from **`origin/<integration-branch>`**, never
from the checked-out submodule pointer — [0002 §2](decisions/0002-supersede-convention.md)
is explicit that the pointer is not evidence, and it currently lags by months.
Checking the docs against a stale pointer would report agreement with code
nobody runs.

Relations, enumerated (an unknown name is a failure, not a no-op): `eq` (both
decimal), `eq-hex` (both hexadecimal, compared numerically), `kb-from-shift`
(doc KB × 1024 = 2^code), `bytes-from-shift` (doc bytes = 2^code).

| Fact ID | Doc pattern | Code | Code pattern | Relation |
|---|---|---|---|---|
| `mmu.page.base` | `(\d+) KB base page` | `linux:arch/sh/configs/jcore_defconfig` | `CONFIG_PAGE_SIZE_(\d+)KB=y` | `eq` |
| `mmu.tsb.entry` | `(\d+)-byte entr` | `jcore-cpu:core/cpu.vhd` | `entry_bytes\s*=>\s*(\d+)` | `eq` |
| `mmu.tsb.entry` | `(\d+)-byte entr` | `linux:arch/sh/include/cpu-jcore/cpu/mmu_context.h` | `#define JCORE_TSB_ENTRY_BYTES\s+(\d+)` | `eq` |
| `mmu.tsb.set` | `(\d+)-byte set` | `jcore-cpu:core/datapath_pkg.vhd` | `shift_left\(v_idx, (\d+)\)` | `bytes-from-shift` |
| `mmu.tsb.tag.shift` | `` `JCORE_TSB_TAG_SHIFT` = \*\*(\d+)\*\* `` | `linux:arch/sh/include/cpu-jcore/cpu/mmu_context.h` | `#define JCORE_TSB_TAG_SHIFT\s+(\d+)` | `eq` |

Notes on what is deliberately **not** here, so the gaps are visible rather than
inferred from silence:

- **`mmu.tsb.entry` is bound twice on purpose.** The 16 is restated
  independently by the RTL generic map and by the kernel header, and either can
  move without the other. One binding would leave whichever side it did not name
  free to drift.
- **`mmu.tsb.set` binds to the shift, not to a literal 32.** The RTL has no
  `32`; it has `shift_left(v_idx, 5)`, which is the arithmetic that actually
  places a set. Binding to the real expression is why widening the TSB to 4 ways
  cannot pass with the doc still saying 32 bytes.
- **`fpu.context.t2` and `simd.context.j32`/`j64` have no code binding**, because
  there is no code: there is no FPU or SIMD RTL in `jcore-cpu`, and Linux's
  `struct sh_fpu_hard_struct` is a field list with no size constant to capture.
  They are covered instead by `context-image-sums`, which checks the owning
  spec's own field table against its own declared total — doc-internal
  arithmetic, not doc-vs-code, and labelled as such.
- **The P4 register offsets are not rows here.** They are a table-vs-table
  comparison (`p4-offsets-match-rtl`), which also catches a register the RTL
  decodes and the map does not list — something a per-fact binding cannot see.
- **P4 addresses restated in RTL *comments* are not checked, and that is a
  measured decision, not an oversight.** B0c built such a sweep and threw it
  away. Three attribution rules were tried against `jcore-cpu`'s `core/` and
  `docs/`, with one known real defect present (`core/components_pkg.vhd` calling
  MMUFSR `0xFF000028`, which is INTEVT's address and precisely the one MMUFSR
  was moved off): *nearest name wins* gave 4 false positives to 1 true;
  *the address's true owner must be named within ±3 lines* gave 7 to 1; *compare
  only where the window holds exactly one address and one name* gave 0 to 0 —
  it skipped the real defect, because an unrelated `EXPEVT 0x0C0` three lines
  below made the window ambiguous. Prose pairs names with addresses by
  apposition and across line wraps, and no regex reads that. A check with a 4:1
  false-positive rate fires on correct comments and gets deleted; a check with
  no true positives is worse than none. The comment defect was fixed by hand
  and the sweep was not shipped. The structured half — the map table versus the
  decode — is checked, and that is where the authority actually lives.
- **`mmu.page.base` binds to Kconfig, not to the RTL,** because the RTL has no
  page-size constant: it is page-size-general, with `PageMask` in `PTEL[11:8]`
  selecting per entry. There is nothing in the hardware for `16 KB` to disagree
  with.

## Unresolved — facts with no owner yet

A fact with no single true value has no owner, and saying so here is the point.
A registry that quietly omits its holes is the failure of the old glossary in a
new file.

| Fact | State | Owned by (task) |
|---|---|---|
| **Endianness of the J-Core product line** | Contradictory. [glossary.md §3](glossary.md) tabulates every product point as little-endian; the shipping J2 toolchain target is `sh2eb-linux-muslfdpic` (big-endian) and [fgmt/mt2x2-plan.md §9 Q3](fgmt/mt2x2-plan.md) records the conflict as an explicit open decision. [fpu/spec.md §2.3](fpu/spec.md) already hedges ("Tier 0 may ship big-endian"). | Wave-2 **B1** (listed there as a *mechanical* item; it is not — it needs a product decision before any doc edit is correct) |
| **P4 register offsets vs real SH-4** (QACR0/QACR1/CCR/CPUINFO) | Partly settled. `TRA`/`EXPEVT`/`INTEVT` and `MMUFSR` are resolved in [soc/p4-mmio-map.md §7](soc/p4-mmio-map.md); the SH-4-compat policy for the rest is not. | Wave-2 **B1**, gated on **B2** (SH-4-as-guest model) |
| **Instruction encodings** | Not a registry fact by design, and **no longer unresolved as to which file**: [decisions/0003](decisions/0003-canonical-encoding-database.md) makes `jcore-cpu/docs/insns.json` canonical and deletes this repo's copy. Checked by `insns2asm --emit check` and `cpugen insns -check`; prose specs cite it and must not restate bit patterns. | Wave-2 **B4** (the sweep itself) |

## Waivers

Pre-existing bare restatements, enumerated so the checks can land red-free and
be burned down deliberately. **This list may only shrink.** Adding a row is a
change to the decision, not a routine edit; do it in a commit that says why.

Granularity is *waiver-ID × file*. A waiver ID is either a **fact ID** (silencing
`restatement-is-linked` for that fact in that file) or a **check name** —
`legacy-marker`, `stale-claim` — silencing that check in that file. The two are
deliberately separate: a file exempted for one may not be exempted for the other,
which is why `mmu/security-review.md` appears once and not twice.

`glossary-is-value-free` accepts **no** waiver, and the checker refuses one. Its
only escape is a declared, **id-carrying** fence —
`<!-- value-free: off (some-id) -->` — which lives at the point of use *and*
must have its own `glossary-fence:some-id` row below. **The checker reads those
rows**: a fence with no matching row fails, an unnamed fence fails, a reused id
fails, and a row whose fence is gone fails under `--check-waivers`. One row
licenses one region, never the file.

`scripts/check-doc-facts.py --check-waivers` fails on a row that never fires, so
this list cannot quietly outlive the restatements it covers.

Every row below was produced by running the checker against the tree on
2026-08-25 — none is speculative. `owner-has-fact` and `glossary-is-value-free`
have **no waivers and are live**; those are the two rules
[0001](decisions/0001-one-authority-per-fact.md) calls load-bearing.
`restatement-is-linked` is the burn-down rule, and this is its worklist.

Clearing a row means one of two edits at the cited site: add a link to the owner,
or delete the duplicated value. Both are one-line changes.

| Fact ID | File | Why waived / who clears it |
|---|---|---|
| `bus.bmid.width` | [hypervisor/design-spec.md](hypervisor/design-spec.md) | pre-existing bare restatement — B1 |
| `bus.bmid.width` | [iommu/design-spec.md](iommu/design-spec.md) | pre-existing bare restatement — B1 |
| `bus.bmid.width` | [iommu/hardware-spec.md](iommu/hardware-spec.md) | pre-existing bare restatement — B1 |
| `hyp.expevt.hcall` | [hypervisor/linux-spec.md](hypervisor/linux-spec.md) | pre-existing bare restatement — B1 |
| `hyp.expevt.hypreg` | [hypervisor/linux-spec.md](hypervisor/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.asid.width` | [hypervisor/design-spec.md](hypervisor/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.asid.width` | [hypervisor/linux-spec.md](hypervisor/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.asid.width` | [iommu/design-spec.md](iommu/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.asid.width` | [mmu/design-spec.md](mmu/design-spec.md) | §3.4's heading *is* the value; B1 decides whether design-spec §3.4 or hardware-spec §2.1a owns ASID width |
| `mmu.asidtag.width` | [bus/fabric-spec.md](bus/fabric-spec.md) | pre-existing bare restatement — B1 |
| `mmu.asidtag.width` | [mmu/linux-spec.md](mmu/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.asidtag.width` | [ooo/j32ooo-spec.md](ooo/j32ooo-spec.md) | pre-existing bare restatement — B1 |
| `mmu.mmufsr.addr` | [mmu/hardware-spec.md](mmu/hardware-spec.md) | §2.11 defines the register and quotes its address; correct content, missing link — B1 |
| `mmu.mmufsr.addr` | [priv-arch/design-spec.md](priv-arch/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.mmufsr.addr` | [priv-arch/j4-implementation-design.md](priv-arch/j4-implementation-design.md) | pre-existing bare restatement — B1 |
| `mmu.page.base` | [j4-remediation-plan.md](j4-remediation-plan.md) | the plan quotes the review finding verbatim; clears when the plan is retired |
| `mmu.page.base` | [mmu/linux-spec.md](mmu/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.tsb.entry` | [mmu/linux-spec.md](mmu/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.miss` | [hypervisor/design-spec.md](hypervisor/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.miss` | [mmu/design-spec.md](mmu/design-spec.md) | §4.1a argues the split and must name both vectors — B1 adds the link |
| `mmu.vector.miss` | [mmu/linux-spec.md](mmu/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.miss` | [priv-arch/design-spec.md](priv-arch/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.prot` | [hypervisor/hardware-spec.md](hypervisor/hardware-spec.md) | §9 verification points quote both vectors — B1 adds the link |
| `mmu.vector.prot` | [mmu/design-spec.md](mmu/design-spec.md) | §4.1a, as above — B1 |
| `mmu.vector.prot` | [mmu/linux-spec.md](mmu/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.prot` | [priv-arch/design-spec.md](priv-arch/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.prot` | [priv-arch/j4-implementation-design.md](priv-arch/j4-implementation-design.md) | pre-existing bare restatement — B1 |
| `simd.sr.vd` | [fpu/spec.md](fpu/spec.md) | §7 preamble; **superseded** by B0a, text rewritten by Wave 2 |
| `simd.vfpul` | [fpu/spec.md](fpu/spec.md) | §7 preamble still describes VFPUL as live; **superseded** by B0a, text deleted by Wave 2 |
| `simd.vfpul` | [j4-remediation-plan.md](j4-remediation-plan.md) | the plan quotes the review finding verbatim; clears when the plan is retired |
| `glossary-fence:product-table-addr-width` | [glossary.md](glossary.md) §3 | Authorises exactly one fenced region — the product table's `Addr width` column, which mixes self-referential naming (J*N* is *N*-bit) with a borrowed MMU fact (the J64 VA width). **The checker reads this row**: delete it and the fence fails; add a fence with any other id and it fails until that id has its own row. Wave-2 **B1** splits the column, then this row and the fence go together. |
