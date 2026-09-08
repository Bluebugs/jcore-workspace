# 0006 — Big-endian instruction fetch; the data path gains a per-guest little-endian mode

**Status:** Accepted 2026-09-07 (Wave-2 **B1**); **re-scoped 2026-09-08 by
Wave-2 B2 on project direction** — see *Re-scope* below. Closes the
`Endianness of the J-Core product line` row that
[fact-ownership.md](../fact-ownership.md) §Unresolved opened as the first
deliberate hole in that registry.

*The filename still reads `…-is-big-endian`. It is kept: seven documents link
it, sixteen times over, and [0002](0002-supersede-convention.md) cites records by
subject rather than by identifier — so renaming the file would break links to buy
nothing. The title above is the current one.*

---

## Re-scope, 2026-09-08

This record was **mis-scoped, not wrong.** It read a true fact — the RTL has one
byte order and no mode bit — as an architectural exclusion, when it is unbuilt
work the project intends to build. The SH architecture historically supported
both byte orders, and J-Core is to follow it on the data path.

**What survives unchanged:** the Context table; the reading of
`CONFIG_CPU_BIG_ENDIAN` in `jcore_defconfig` and the code binding built from it; the
toolchain target; the SH-2A density point; the finding that the glossary's
product table had no authority to state a byte order; and the whole *Enforcement*
section.

**What does not survive as written:** the Decision clause's "no per-product-point
byte order and **no migration**"; the sentence below concluding that making the
hardware little-endian "is not a configuration change", *read as a settled
exclusion*; the "withdrawn" verdict on [fpu/spec.md](../fpu/spec.md)'s migration
analysis; and the *What would reopen this* list, whose triggering event has now
occurred by direction rather than by evidence.

**What replaces them** is [sh4-guest-model.md §3.1](../sh4-guest-model.md),
Decision B2-1: a per-guest, hypervisor-owned **little-endian data mode**, with
instruction fetch staying big-endian. Its cost is
**unknown at this stage — needs measurement**.

---

## Context

[0001](0001-one-authority-per-fact.md) found three stale entries in the
glossary. Two were fixed on the spot. The third could not be: the glossary's
product table gave **little** for every product point J2…J64, and fixing it
required *deciding* the byte order rather than looking it up, which is B1's
job and not B0a's. 0001 §Rejected alternative says so in as many words, and the
registry has carried the row as `UNRESOLVED — Wave-2 B1` since.

The two sides, as the tree stated them before this record:

| Says little-endian | Says big-endian |
|---|---|
| [glossary.md §3](../glossary.md) product table, `Endianness` column — every row | `linux@jcore` `arch/sh/configs/jcore_defconfig`: `CONFIG_CPU_BIG_ENDIAN=y` |
| [fpu/spec.md §2.3, §6.2](../fpu/spec.md): Tier 1 onward is little-endian, with a BE→LE migration specified | the shipping toolchain target `sh2eb-linux-muslfdpic` ([fgmt/dual-fgmt-proposal.md §7](../fgmt/dual-fgmt-proposal.md)) |
| | [isa-density/software-impl.md §7](../isa-density/software-impl.md): both measurement compilers built `--with-endian=big`, "SH-2A is big-endian only, matching the J-core sh2eb target" |
| | [fgmt/mt2x2-plan.md §9 Q3](../fgmt/mt2x2-plan.md): "Big-endian is the path of least resistance; flag as a decision" |

## What the code says, which is what settled it

Three artifacts were read at `origin/<integration-branch>` for this record, not
recalled:

1. **`linux@jcore` `arch/sh/configs/jcore_defconfig`** carries
   `CONFIG_CPU_BIG_ENDIAN=y`. This is the configuration the J-Core kernel boots
   from. It is now a **code binding** (`platform.endianness` in
   [fact-ownership.md](../fact-ownership.md) §Code bindings), so the document
   and the defconfig cannot drift apart again.

2. **`jcore-soc@master` `targets/data_bus_pkg.vhd`**, procedure
   `splice_instr_data_bus`, reply path:

   ```vhdl
   if instr_o.a(1) = '0' then
     instr_i.d <= data_i.d(31 downto 16);
   else
     instr_i.d <= data_i.d(15 downto 0);
   end if;
   ```

   The even instruction halfword is taken from the **high** half of the 32-bit
   bus word. That is big-endian instruction packing, and there is **no mode
   bit** — no generic, no register, no configuration constant selects the other
   arm. `jcore-cpu@master` `cache/icache_cacheable_mux.vhd` calls this same
   procedure for the uncached-fetch bypass and its header says so: "the bypass
   reuses the canonical `splice_instr_data_bus` (correct 16-bit big-endian half
   selection)". This is the file list the ECP5 and ASIC synthesis flows
   elaborate, not a simulation helper — `jcore-cpu@master` `synth/cpu_synth.sh`
   takes `data_bus_pkg.vhd` from `jcore-soc`.

3. **`jcore-cpu@master` `cache/dcache_check_tb.vhd`** records the same fact from
   the other side, as a known gap in a testbench: "byte-enable (sub-word) stores
   need SH big-endian byte-lane modeling in this TB (CPU we/data lane vs DDR
   lane differ by endianness)".

Making the **whole machine** little-endian is therefore not a configuration
change. It is an RTL change to the fetch path, a toolchain retarget, a kernel
reconfiguration and a rebuild of every userspace artifact — against a design
whose only shipping member is big-endian and whose density extension targets an
ISA variant that has no little-endian form at all.

**That sentence is about a wholesale switch and must not be read wider.** It is
not evidence that the *data* path cannot be made mode-dependent, and the
re-scope above says it is to be. Two functions in `jcore-cpu@master`
`core/datapath.vhm` — `to_data_o`'s byte-enable and lane mapping, and
`align_read_data`'s load lane mux — are where that lands; neither is the fetch
path, neither is a toolchain artifact, and changing them retargets nothing.

## Decision

**Instruction fetch is big-endian, and every J-Core product point ships
big-endian: J2, J2-MT2x2, J3, J32, J32-OOO, J32-LT, J32-FM and J64.** There is
no per-product-point byte order — the byte order is not a property that
distinguishes one product point from another.

**The data path is a different question and is answered elsewhere.** Per the
re-scope above it gains a little-endian mode, selected per guest by the
hypervisor and not writable by the guest, owned by
[sh4-guest-model.md §3.1](../sh4-guest-model.md). That is a *software
configuration*, which is why it does not reopen the product-point statement
above: J32 and J64 still ship big-endian.

1. The `Endianness` column is **removed** from
   [glossary.md §3](../glossary.md)'s product table. Per
   [0001](0001-one-authority-per-fact.md) the glossary carries no values; a
   column that is the same for every row carries no information about the
   product points either. The glossary's **Endianness** term entry names the
   owner and stops.

2. The owning document is a new one:
   [platform-baseline.md §2](../platform-baseline.md). It exists because this
   fact had no owner — it is a property of the platform, not of the MMU, the
   FPU or the bus, and every document that stated it was restating somebody
   else's guess.

3. [fpu/spec.md](../fpu/spec.md)'s claim that **J-Core migrates wholesale to
   little-endian from Tier 1** is withdrawn; its *analysis* of what changes is
   not. The distinction matters more after the re-scope than before it: a
   double-`FMOV`'s half-pair order is a **data**-path property, so the moment
   the little-endian data mode exists, §6.2's points 1 and 2 stop being an
   archived what-if and become a requirement on any Tier-1 FPU. They are
   re-armed rather than withdrawn, and §6.2 is marked accordingly.

## Why the FPU spec's argument does not survive

It is worth being precise about this, because the FPU spec is not sloppy: it
states its reason, and the reason is what fails.

`fpu/spec.md` §2.3: *"Per [../glossary.md §3](../glossary.md), the J-Core
product line is little-endian from J2 onward in the published product table.
… **This specification follows the glossary**"*, and §2.3 closes with *"Where
this document and the archived j2-spec.md disagree on endianness, **this
document wins** per the glossary 'single source of truth' rule."*

Both halves are now void. The glossary's product table is the artifact
[0001](0001-one-authority-per-fact.md) demoted, and its `Endianness` column is
the specific cell that record identified as never having been true. The
"single source of truth" rule it invokes was deleted by the same decision. So
the FPU spec derived a normative migration from a document that had no
authority to state it and was wrong when it did — which is the failure mode
0001 is about, observed a second time in a second file.

The *engineering* argument sometimes offered alongside it — that SH-4 and
Dreamcast binaries are little-endian, so J-Core should be too — is the one that
survives in part, and the re-scope above is what it bought. It does not reach
*this* record's conclusion, because a wholesale product-line switch is not what
little-endian guest data requires: a per-guest data mode gets the guests without
retargeting the toolchain or moving the fetch path.

**This record originally continued: "a guest's byte order is a property of the
guest's own image and of the device model that serves it, not of the host's
fetch path." That is true of a software-emulated guest and false of a KVM
guest**, which executes its own instructions on the host's path by definition.
That is exactly why Decision B2-1 puts the mode in **hardware**, per guest,
rather than leaving it to a device model: for a KVM guest there is no software
layer in the path to do the swapping.

## Rejected alternative — little-endian from J32 onward, per `fpu/spec.md` §6.2

This is the alternative the tree actually contained, so it is the one recorded.

**What it would buy.** Native SH-4 double-`FMOV` layout for guests that expect
it, without the emulation layer having to swap halves; and one fewer byte-order
boundary if J-Core ever wanted to run stock little-endian SH-4 binaries
natively.

**Why it is rejected.**

1. **The evidence is one-sided and the sides are not comparable.** Big-endian
   is what the kernel is configured for, what the compilers were built for,
   what the measurements in `isa-density/software-impl.md` §7 were taken on,
   and what the RTL does with no alternative arm. Little-endian is asserted by
   a product table that decision 0001 has already found false on this exact
   column, and by a spec that cites that table as its authority.

2. **SH-2A has no little-endian form.** `isa-density/software-impl.md` §7 says
   so plainly, and the density extension (`movi20`, `movmu.l`, `movml.l`)
   targets SH-2A encodings. Choosing little-endian would put the density work
   and the byte order in direct conflict.

3. **~~The benefit accrues to a target that cannot use it.~~ Withdrawn by the
   re-scope.** The benefit is real and the project now intends to have it — but
   a per-guest data mode delivers it, so it is not an argument for flipping the
   product line. This objection is struck rather than restated, because
   objections 2 and 4 are the ones that actually carry this rejection and it is
   better to have two live reasons than four of mixed standing.

4. **The cost is a flag day across four repositories** with no measurement
   saying what is bought. The project's standing rule for that shape of claim
   is [0005](0005-unmeasured-figures-are-removed.md): do not act on a number
   nobody produced.

**What would reopen it.** Objections **2** and **4** are what stand: SH-2A has
no little-endian encoding form, and a wholesale switch is a flag day across four
repositories with no measurement saying what it buys. Both are *cost*, not
exclusion, and reopening this alternative means answering them — a little-endian
form for the density extension's target encodings, and a measurement. The
per-guest data mode of Decision B2-1 deliberately avoids both by not being a
wholesale switch: it changes no encoding and retargets nothing.

The old triggers are gone rather than pending. This record previously said the
alternative would reopen if B2 decided guest SH-4 FP runs natively *and* a
measurement showed byte-swap cost material. B2 decided FP is trapped
([sh4-guest-model.md §4](../sh4-guest-model.md), Decision B2-4) — but the
byte-order question was reopened anyway, by direction, and answered in a way
neither trigger anticipated. Two-condition triggers written against a guess
about *how* a question will come back are worth less than they look.

## Enforcement

`platform.endianness` is a row in [fact-ownership.md](../fact-ownership.md)'s
`## Registry` (so a restatement without a link to the owner fails
`restatement-is-linked`) and in `## Code bindings`, comparing
[platform-baseline.md §2](../platform-baseline.md) against
`linux@jcore` `arch/sh/configs/jcore_defconfig` under a new relation,
**`eq-text`**.

`eq-text` is the first non-numeric relation the binding mechanism has. It exists
because this fact has no number: `eq`, `eq-hex` and `bytes-from-shift` all parse
their two captures as integers, and there is no honest integer for a byte order.
Both captures are compared case-insensitively after stripping surrounding
whitespace, so the document may write `big` where the Kconfig symbol writes
`BIG`. It is enumerated in `RELATIONS` exactly as the other three are — an
unknown relation name is a failure, not a no-op — and it is covered by fixtures
in `scripts/test-check-doc-facts.py` in both directions (agreeing captures pass;
disagreeing captures fail `doc-matches-code`).

**What this does not catch**, stated so a green run is not over-read: the
binding compares the owning document with the *kernel configuration*. If the
RTL fetch path were made little-endian while the defconfig stayed `=y`, the
check would still pass. The RTL side has no constant to bind to — the byte
order there is the *shape* of an `if`, not a value — and
[fact-ownership.md](../fact-ownership.md) §Code bindings already records that
a fact with no code constant gets no binding rather than a fake one. The
defconfig is the strongest single artifact available, and it is the one that
would have to change first in any real migration.

## What would reopen this

- **The `eq-text` relation acquires a second, differently-shaped user.** One
  user is a relation; three would be a pattern, and the pattern to look at then
  is whether the binding table wants a general "these two strings must agree"
  rule rather than a per-fact relation name.
- **The little-endian *data* mode's scope grows to the fetch path.** Decision
  B2-1 deliberately stops at the data path, which is what keeps this record's
  product-point statement true. Extending it to instruction fetch would make a
  guest's *code* byte order configurable, and at that point "J-Core ships
  big-endian" is a default rather than a fact about the machine. That is the
  event that reopens this record, and the last time this question moved it moved
  by direction rather than by any trigger written here — so read this list as
  the events worth watching, not as the only ones that can occur.
- **Objection 2 or 4 of the rejected alternative is answered** (above): a
  little-endian encoding form for the SH-2A-targeted density instructions, or a
  measurement of what a wholesale switch buys.
- **A little-endian J-Core target appears in a toolchain or kernel tree** — an
  `sh2el`/`sh4le` defconfig on an integration branch would make the binding red,
  which is the point of having it.
