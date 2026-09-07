# 0006 — J-Core is big-endian, at every product point

**Status:** Accepted 2026-09-07. Wave-2 task B1, from
[j4-remediation-plan.md §B1](../j4-remediation-plan.md). Closes the
`Endianness of the J-Core product line` row that
[fact-ownership.md](../fact-ownership.md) §Unresolved opened as the first
deliberate hole in that registry.

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

Making the hardware little-endian is therefore not a configuration change. It is
an RTL change to the fetch path, a toolchain retarget, a kernel reconfiguration
and a rebuild of every userspace artifact — against a design whose only shipping
member is big-endian and whose density extension targets an ISA variant that has
no little-endian form at all.

## Decision

**J-Core is big-endian at every product point: J2, J2-MT2x2, J3, J32, J32-OOO,
J32-LT, J32-FM and J64.** There is no per-product-point byte order and no
migration.

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

3. [fpu/spec.md](../fpu/spec.md)'s BE→LE migration (§2.3, §6.2, and the tier
   bullets that quote them) is **withdrawn**. The sections are kept and marked
   per [0002](0002-supersede-convention.md), because the *content* — what
   changes about double-`FMOV` register pairing between the two byte orders —
   is correct and is exactly what a reader needs if this is ever reopened. What
   is withdrawn is the claim that J-Core will make that change.

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
Dreamcast binaries are little-endian, so J-Core should be too — does not reach
the conclusion either, and B2's framing is why. Per
[j4-remediation-plan.md §B2](../j4-remediation-plan.md), SH-4/Dreamcast is
**not a bare-metal target on any J-Core core**; it runs as a KVM guest under
the hypervisor extension. A guest's byte order is a property of the guest's
own image and of the device model that serves it, not of the host's fetch
path. Host byte order would matter if Dreamcast images ran bare metal. They do
not, by decision.

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

3. **The benefit accrues to a target that is not bare metal.** See above: the
   SH-4 surface is emulated, and a device model that already translates
   addresses can translate byte order.

4. **The cost is a flag day across four repositories** with no measurement
   saying what is bought. The project's standing rule for that shape of claim
   is [0005](0005-unmeasured-figures-are-removed.md): do not act on a number
   nobody produced.

**What would reopen it.** A decision that SH-4/Dreamcast guests run *natively*
rather than trapped-and-emulated for the FP paths — B2 explicitly leaves that
open ("Decide explicitly whether guest SH-4 FP runs natively on J4's FPU or is
trapped-and-emulated") — **and** a measurement showing the emulation cost of
byte-swapping is material. Both, not either.

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
- **B2 decides guest SH-4 FP runs natively**, per the rejected alternative
  above.
- **A little-endian J-Core target appears in a toolchain or kernel tree** — an
  `sh2el`/`sh4le` defconfig on an integration branch would make the binding red,
  which is the point of having it.
