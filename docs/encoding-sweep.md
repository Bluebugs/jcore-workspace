# Encoding-verification sweep — findings, re-homings, and where it stopped

**Status:** Canonical for the *sweep results*. Wave-2 task **B4**, from
[j4-remediation-plan.md §B4](j4-remediation-plan.md).

**Scope:** every instruction encoding stated in a document under `docs/`,
checked against the canonical encoding database
([decisions/0003](decisions/0003-canonical-encoding-database.md),
`jcore-cpu/docs/insns.json`) with `cpugen freespace` and `cpugen collisions`.
This document records what the sweep found, what it proposes, and — explicitly —
what it did not cover.

**Authority:** this document owns **no encoding**. Each encoding belongs to the
spec that defines it, and the sweep's job is to say whether that spec's bits
survive the tools. Where a spec is wrong, the correction is made *in that spec*
and this document points at it.

**Method:** [decisions/0008](decisions/0008-documented-but-unimplemented-encodings.md)
decides how an instruction with no RTL is verified and reserved without
generating decode logic. Read that first; it is what makes the rest of this
sweep executable.

**Evidence discipline:** every claim below was produced this session by running
a tool against `jcore-cpu@origin/master` (`e8a5a4e`, *"fix(cpugen): walk the
encoding groups in document order"*), never against the checked-out submodule
pointer — [decisions/0002 §2](decisions/0002-supersede-convention.md).

---

## 1. Baseline

On `jcore-cpu@origin/master`, before any change:

| Gate | Result |
|---|---|
| `cpugen insns -check` | exit 0 — the database is current with the spec tree |
| `cpugen collisions` | `swept 466 instructions over 13 variants; 2 same-variant identical-encoding collision(s), 2 baselined, 0 new` |
| `insns2asm -emit check` | `excluded 40 DSP/coproc instructions` / `ok: 318 instructions round-trip` |

The 466 rows carry 13 variant columns and 94 `collides` annotations. They
account for exactly: **108** rows whose `group` starts with `DSP`, dropped by
`loader`'s group filter with no count; **40** dropped by its DSP-operand and
DSP-only filters, which *are* counted and printed; and **318** that round-trip.
There is today **no row in a group `loader.emittedGroups` does not list**, which
is why the silent-drop path has never been exercised and why a new group is
invisible to the checker rather than rejected by it — see
[decisions/0008 §Enforcement](decisions/0008-documented-but-unimplemented-encodings.md).

## 2. Live collisions in shipping RTL, with proposed re-homings

[sh4-guest-model.md §5.1](sh4-guest-model.md) found four encodings on which a
J-Core instruction and an SH-4 instruction are bit-identical, and left the
re-homing to this task. The sweep confirms all four and adds the fact that makes
the fix obvious.

**All four are the CPI coprocessor bridge, and all four of its CP0 twin's
encodings are clean.** J-Core has two coprocessor interfaces with the same four
operations each. Read from `decode/gen-go/spec/system.toml`:

| Operation | CP0 encoding | collides with | CPI encoding | collides with |
|---|---|---|---|---|
| `LDS Rm, …_COM` | `0100 mmmm 1000 1000` | — | `0100 mmmm 0101 1010` | SH-4's integer→FP bridge |
| `CLDS …_Rm, …_COM` | `0100 mmmm 1000 1001` | — | `1111 mmmm 0001 1101` | SH-4's FP register→FPUL move |
| `STS …_COM, Rn` | `0100 nnnn 1100 1000` | — | `0000 nnnn 0101 1010` | SH-4's FP→integer bridge |
| `CSTS …_COM, …_Rn` | `0100 nnnn 1100 1001` | — | `1111 nnnn 0000 1101` | SH-4's FPUL→FP register move |

The SH-4 forms are named, with their own bits, in
[sh4-guest-model.md §5.1](sh4-guest-model.md); this table does not restate them.

CP0's four encodings share one shape — `0100`, bit 7 set, bit 6 selecting
load/store, bits 5:4 = `00`, low nibble `1000` for the GPR form and `1001` for
the coprocessor-register form. **Bits 5:4 are an unused coprocessor index.**
Giving CPI index `01` re-homes all four at once and leaves two indices spare:

| Instruction | Today | **Proposed** | `freespace` verdict |
|---|---|---|---|
| `LDS Rm, CPI_COM` | `0100 mmmm 0101 1010` | `0100 mmmm 1001 1000` | virgin |
| `CLDS CPI_Rm, CPI_COM` | `1111 mmmm 0001 1101` | `0100 mmmm 1001 1001` | virgin |
| `STS CPI_COM, Rn` | `0000 nnnn 0101 1010` | `0100 nnnn 1101 1000` | virgin |
| `CSTS CPI_COM, CPI_Rn` | `1111 nnnn 0000 1101` | `0100 nnnn 1101 1001` | virgin |

Verified with, for each form,

```
cpugen freespace -avoid J1,J2,J2A,J4,SH1,SH2,SH2A,SH2E,SH3,SH3E,SH4,SH4A \
    -form '0100mmmm1001----' -family "System Control Instructions"
```

which reports `0100mmmm10011000` and `0100mmmm10011001` virgin with
`clds CP0_Rm,CP0_COM` as their nearest family member, and the `0100nnnn1101----`
run likewise for the store side. Applying the four moves to a scratch copy of
`spec/system.toml` and regenerating produced four rows with **no `collides`
annotation at all**, `cpugen collisions` still `0 new`, and `insns2asm` still
`ok: 318`. `internal/insns`, `internal/freespace` and `cmd/cpugen` pass their
own test suites with the moves applied, as they do without them.

**Three properties of this proposal, stated so a reviewer can attack them:**

1. It moves the two `1111`-plane forms *out* of the `1111` plane, which is what
   [sh4-guest-model.md §2](sh4-guest-model.md) wants: bare-metal J4 traps that
   plane, and two declared encodings in it are two holes in the trap.
2. It puts the whole coprocessor bridge in one family with one rule, so the next
   coprocessor does not need a fifth search.
3. It is an **RTL change and this task may not commit it.** Regenerating from
   the patched `spec/system.toml` changed `decode_body.vhd`,
   `decode_table_direct.vhd`, `decode_table_simple.vhd` and `sh2instr.c` —
   measured, not assumed. Owner: **B4 with an RTL / SoC co-owner**, exactly as
   [sh4-guest-model.md §8](sh4-guest-model.md) says. The four
   `sh4guest.*` code bindings in [fact-ownership.md](fact-ownership.md) go red
   on the day it lands, which that section already predicted and welcomed.

### 2.1 The two DSP pairs the collision gate carries as baseline

`cmd/cpugen/collisions.go`'s `baseline` map carries two same-variant identical
encodings and names **"Wave-2 B4 (encoding sweep)"** as their owner:

| Encoding | Pair | Reading |
|---|---|---|
| `0100 mmmm 0111 0110` | `lds Rm,A0` / `lds.l @Rm+,A0` | one of the two is a transcription error |
| `0100 nnnn 0110 0010` | `sts.l A0,@-Rn` / `sts.l DSR,@-Rn` | same shape, same reading |

**The sweep does not resolve these and says so.** Both pairs are DSP-only, both
come from the source manual transcription, and deciding which of the two rows is
wrong requires an SH-DSP manual this workspace does not hold — not a free-space
search. Nothing in J-Core implements them:
[mmu/hardware-spec.md §3.1](mmu/hardware-spec.md) records that **J4 forecloses
SH-DSP permanently**, so no J-Core part will ever face either pair. They stay
baselined; the owner line should move from B4 to whoever next has the manual.

## 3. SIMD

[simd/spec.md](simd/spec.md) states 102 encodings across 57 mnemonics and none
of them is in the canonical database. Under
[decisions/0008](decisions/0008-documented-but-unimplemented-encodings.md) they
are candidates for reservation rows — *after* the ones that do not survive the
tools are re-homed, because reserving a colliding encoding just writes the
collision down.

### 3.1 Confirmed, as the plan described

- **`VLD.Q` / `VST.Q`** claim the six SH-4 `FMOV.S` addressing-mode encodings
  and [simd/spec.md §5.6](simd/spec.md) calls them "Valid in or out of SIMD
  blocks". Confirmed mechanically: a reservation row carrying
  `1111nnnnmmmm1000` came back from regeneration annotated
  `"collides": ["fmov.s\t@Rm,FRn"]`. Six encodings, six collisions.
- **`VMKCHG`** at `1111 1100 1111 1101` is **exactly** SH-4A `fsca FPUL,DRn`
  with `n = 110`, not merely "in its row".
  `freespace -form '1111110011111101'` returns **0 candidates** once `SH4A` is
  avoided, and `shadows SH4A: fsca FPUL,DRn` when it is not.
- **Tier-0 `SUB` carries `SUBC`'s encoding.** [simd/spec.md §5.1](simd/spec.md)
  gives `SUB Rm,Rn` the bits `0011 nnnn mmmm 1010`. The database and
  `spec/arithmetic.toml` both say that is `SUBC Rm,Rn`; `SUB Rm,Rn` is
  `0011 nnnn mmmm 1000`. §5.4.3 of the same document then reuses
  `0011 nnnn mmmm 1010` for `VABSDIFF` "(was SUBC)" — so **one encoding is
  claimed twice inside one document**, once as a Tier-0 governed op and once as
  a Tier-1 reinterpretation. The other 20 rows of the Tier-0 governed tables
  were checked the same way and every one of them matches the database.
  Corrected in [simd/spec.md §5.1](simd/spec.md); the fix is one nibble and it
  dissolves the double claim.
- **The 4-bit lane and swizzle fields cannot address the lanes.** §1.2 fixes
  `VLEN = 8 × XLEN`, so there are 32 byte-lanes on J32 and 64 on J64, needing 5
  and 6 index bits. Appendix A's field list gives `llll` — the `VLNS` lane index
  — **4 bits**, and §3.3 describes the `SWIZZLE` control vector as "4 bits per
  index at w=8". Four bits reach 16 lanes: half the J32 byte-lanes and a quarter
  of J64's. This is arithmetic, not a search result, and it is recorded in
  [simd/spec.md §3.3](simd/spec.md).

### 3.2 What the plan missed, and it is larger than what it named

The plan lists `VLNS` as "overlapping `VEXT.*`". It does, and that is the
smallest part of it. `VLNS`, `VEXT.*` and `VINS.*` occupy two whole
minor-nibble families, and the sweep enumerated both against the database:

**`0100 nnnn xxxx 1011` — `VLNS` and the `VEXT` group.**

| Minor | SIMD claims | Occupied by |
|---|---|---|
| `0000`/`0001`/`0010` | (`VLNS` spans all 16) | `jsr @Rm` / `tas.b @Rn` / `jmp @Rm`, live on every variant |
| `0100` | (`VLNS`) | `jsr/n @Rm`, live on **J2A** and SH-2A — [isa-density/spec.md §3.5](isa-density/spec.md) |
| `1000` | `VEXT.B Rn` | `mov.b R0,@Rn+`, live on **J2A** and SH-2A |
| `1001` | `VEXT.W Rn` | `mov.w R0,@Rn+`, live on **J2A** and SH-2A |
| `1010` | `VEXT.L Rn` | `mov.l R0,@Rn+`, live on **J2A** and SH-2A |
| `1011` | `VEXT.Q Rn,Rn+1` | free |
| `1100` | `VEXTF.L FRn` | `mov.b @-Rm,R0`, live on **J2A** and SH-2A |

Four of the five `VEXT` slots are taken, and taken by a **J-Core** variant, not
merely by an SH one. `cpugen freespace -avoid <all 13> -form '0100nnnn----1011'`
returns 6 candidates, all virgin: minors `0011`, `0101`, `0110`, `0111`, `1011`,
`1111`.

**`0000 nnnn xxxx 1011` — the `VINS` group.** `VINS.B`/`W`/`Q`/`VINSF.L` at
minors `1000`/`1001`/`1011`/`1100` are free. **`VINS.L` at `1010` is not**: it
shadows SH-4A `synco`, and `VINS.L R0` *is* `synco`. That is a Decision B2-5
violation of the same kind as §2's four — an SH-4A guest instruction decoding as
a different J-Core instruction — and nothing in the SIMD spec mentions it.

**And `VLNS` cannot be re-homed by picking a slot, because it does not want a
slot.** `0100 mmmm llll 1011` spends *both* nibble fields — `mmmm` on the source
register and `llll` on the lane index — so it claims all 16 minors of a family
that has 6 free. There is no free family of that shape anywhere in the map. The
same 4-bit `llll` is the field §3.1 shows cannot address the lanes in the first
place, so the space defect and the width defect have one cause and need one
answer: **the lane index has to leave the instruction word** (a GPR operand, a
second word, or a width restriction). That is a design decision for
[simd/spec.md](simd/spec.md)'s owner, and B4 records the constraint rather than
inventing an encoding. The `VEXT`/`VINS` groups are re-homable the moment `VLNS`
stops claiming the family, and not before.

### 3.3 The genuine cross-spec reserve conflict

[mmu/hardware-spec.md §3.1](mmu/hardware-spec.md) retired seven encodings and
declares family `0000 nnnn xxxx 1011` **"the first reserve for J4-only
`0000 nnnn`-shaped instructions"**. Its published re-check command, run verbatim
this session, reproduces exactly: 8 candidates, 8 virgin.

**[simd/spec.md](simd/spec.md) Appendix A already spends five of them** —
`VINS.B`, `VINS.W`, `VINS.L`, `VINS.Q`, `VINSF.L` — four inside the free eight
and the fifth on the `synco` shadow. Neither document cites the other. *This* is
the cross-spec conflict B4 was sent to resolve; see §5 for the one the plan
named, which does not exist.

Resolution is not B4's to impose, because both claims are on paper and both
owners are live. What B4 records: the reserve is **contended, not free**, and
the two documents now say so — [mmu/hardware-spec.md §3.1](mmu/hardware-spec.md)
and [simd/spec.md §7](simd/spec.md).

## 4. isa-density and isa-pcrel

Every encoding in [isa-density/spec.md](isa-density/spec.md) was checked against
the database. **The adopted SH-2A set is byte-correct**: `movi20`, `movi20s`,
`movmu.l` (both directions), `movml.l` (both directions), `jsr/n`, `rts/n` and
`rtv/n` all match the canonical rows exactly, and all are already present and
live on J2A and SH-2A. The recon that opened this task recorded `movmu` as
absent from the database; it is not — it is there under `movmu.l Rm,@-R15`.

Three findings:

- **`lea`'s encoding survives, and the tool says why.** `lea` is the one genuinely
  new instruction and it is absent from the database.
  `cpugen freespace -form '0011nnnnmmmm0001' -two-word` reports its word 1 as
  `shareable?` — word 1 is fully claimed by the SH-2A disp12 family — and prints
  the extension words already taken. They are exactly minors `0000`–`1001`, so
  `lea`'s claimed `1010` is free, and [isa-pcrel/spec.md §3.2](isa-pcrel/spec.md)'s
  `1011` beside it likewise. Both specs' claims are confirmed.
- **The 16-bit `lea` alternative at `1111nnnnmmmm1111` does not survive.**
  [isa-density/spec.md §4.4](isa-density/spec.md) offers it as an open
  alternative with a note to "confirm the slot stays clear". It is not clear:
  `freespace` returns **0 candidates** with `DSP` avoided, and 83 shadowed DSP
  rows without it. It is also inside the plane bare-metal J4 traps
  ([sh4-guest-model.md §2](sh4-guest-model.md)). The alternative is closed in the
  negative, in that spec.
- **`movi20s`'s notation is inconsistent four ways, and `--emit check` cannot
  arbitrate it.** Settled in [isa-density/spec.md §3.1](isa-density/spec.md);
  see §6 below for why the plan's proposed arbiter is the wrong one.

**`movmu`'s `m = 15` anchor is not a question the tools can answer, and this is
not a gap in the tools.** `m` is an operand field; the database records that the
field exists and nothing about which of its 16 values are legal. Both
[isa-density/spec.md §5](isa-density/spec.md) and its `hardware-impl.md` §5.3
already say `m = 15` decodes as illegal-instruction, and they agree. The open
half — whether that matches SH-2A — needs the SH-2A manual, which is the same
gap as §2.1's, and it is recorded as such rather than closed by a tool that
cannot see it.

## 5. Closed as not a defect

**The plan's named cross-spec reserve conflict does not exist.** §B4 says the
MMU doc calls `0000 nnnn xxxx 1011` "8 free slots, all virgin" while
`isa-density` plans byte-identical SH-2A `rts/n`/`rtv/n` at minors `0110`/`0111`
of that family, and that `freespace --avoid` over the union would resolve who
owns which slot. Run against the tree, every step of that fails:

- `rts/n` (`0000 0000 0110 1011`) and `rtv/n Rm` (`0000 mmmm 0111 1011`) are
  **already in the canonical database**, marked live on **J2A and SH-2A**. They
  are not a plan.
- `freespace` therefore already excludes them under any `--avoid` naming either
  variant — which the MMU document's own published command does.
- Run verbatim, that command returns **8 candidates, 8 of them virgin**. The
  count is right, the word "virgin" is right, and the two documents do not
  disagree about a single bit.

Recorded as closed rather than dropped, because a plan item that quietly
disappears is indistinguishable from one that was forgotten. The reserve *is*
contended — by [simd/spec.md](simd/spec.md), per §3.3 — and that is a different
finding with different owners.

**One nuance worth keeping.** Relax the avoid set to `sh2a,j4` and a ninth
candidate appears, `0000 nnnn 1010 1011`, shadowing SH-4A `synco`. The MMU
document's count is not wrong — its own command avoids `sh4a` and so never
offers that slot. But the slot is the one [simd/spec.md](simd/spec.md) put
`VINS.L` on, which is how a family with eight free slots produced a
decode-fidelity violation on a ninth.

## 6. What did not survive checking, in the plan and in the brief

Recorded together, because Wave 2's pattern is that every task finds some:

1. **§B4 step 1 names the wrong file.** `docs/insns.json` is generated. The
   authored source is `decode/gen-go/spec/*.toml`, and it also generates the
   shipping decoder — [decisions/0008](decisions/0008-documented-but-unimplemented-encodings.md).
2. **§B4 step 2's arbiter cannot arbitrate.** `insns2asm --emit check` is offered
   as the thing that settles `movi20s`'s sign-extension notation.
   `internal/oracle` reconstructs the bit-pattern *string* and compares it to the
   original string; it models no immediate semantics whatsoever. The arbiter that
   does exist is upstream binutils, and it settled the question — see
   [isa-density/spec.md §3.1](isa-density/spec.md).
3. **§B4's cross-spec conflict does not exist**, and the real one is between two
   different documents — §5 and §3.3.
4. **The recon's "`movmu` absent from the database" is wrong.** It is present,
   correct, and live on two variants — §4.
5. **The recon's "the MMU doc's phrasing would mislead" is wrong.** The doc
   publishes the command it used; run verbatim, that command yields exactly the
   8 virgin slots it claims. The ninth candidate appears only under a weaker
   avoid set than the doc uses — §5.
6. **`insns2asm` drops unknown groups silently.** Not a plan defect but a tool
   one, and it is the reason step 2 would have reported success over a SIMD set
   it never looked at — [decisions/0008 §Enforcement](decisions/0008-documented-but-unimplemented-encodings.md).

## 7. Where the sweep stopped

Stated as a boundary, not as a summary, so nobody reads coverage into silence:

| Covered | Not covered |
|---|---|
| Every encoding stated in `docs/simd/`, `docs/isa-density/`, `docs/isa-pcrel/`, `docs/mmu/`, `docs/hypervisor/`, `docs/fpu/`, `docs/cache/`, `docs/ooo/` was extracted and compared to the canonical database | The 108 DSP rows, beyond confirming that the two baselined pairs are DSP-only and unreachable on J-Core |
| The four RTL collisions, with a verified re-homing proposal | Committing it — that is RTL, and [decisions/0008](decisions/0008-documented-but-unimplemented-encodings.md) rule 4 forbids it here |
| SIMD's named collisions, plus the `VEXT`/`VINS`/`VLNS` families the plan did not name | Writing SIMD reservation rows into the database — premature while `VLNS` has no shape and `VEXT` has no home |
| The `movi20s` notation, pinned against an executable arbiter | `movmu`'s `m = 15` against the SH-2A manual — no manual in the tree |
| The `0000 nnnn xxxx 1011` reserve, both the claimed conflict and the real one | Deciding who wins it; both claimants are live specs with owners |

**§B4 step 4 — regenerate the toolchain delta — was not reached, and it would
have been a no-op if it had been.** Nothing in this sweep changed a live
encoding: the four re-homings are proposals awaiting an RTL owner, the SIMD
corrections are to documents describing instructions no assembler emits, and
[sh4-guest-model.md §5.1](sh4-guest-model.md) already established that
`binutils-gdb@origin/master` carries no SH `clds` or `csts` at all. The
toolchain delta becomes real work on the day the §2 re-homing lands, and it
belongs in that change.

## 8. Open items, with owners

- **Commit the CPI re-homing** (§2). Owner: **B4 with an RTL / SoC co-owner**.
  Four opcodes in `decode/gen-go/spec/system.toml`, four `sh4guest.*` bindings in
  [fact-ownership.md](fact-ownership.md), and the toolchain delta, in one change.
- **Decide `VLNS`'s shape** (§3.2) — the 4-bit lane index cannot address the
  lanes and cannot fit the family. Owner: [simd/spec.md](simd/spec.md).
  `VEXT`/`VINS` re-homing is blocked behind it.
- **Re-home `VINS.L` off SH-4A `synco`** (§3.2). Owner: [simd/spec.md](simd/spec.md),
  jointly with [sh4-guest-model.md](sh4-guest-model.md) — it is a Decision B2-5
  violation, not a tidy-up.
- **Settle the `0000 nnnn xxxx 1011` reserve** (§3.3) between
  [mmu/hardware-spec.md](mmu/hardware-spec.md) and [simd/spec.md](simd/spec.md).
  Owner: whichever of the two writes an instruction there first, which is the
  wrong answer; it wants deciding before that.
- **Teach the collision sweep about guest-hosting** — carried forward unchanged
  from [sh4-guest-model.md §8](sh4-guest-model.md), and **not done here**. The
  variant rule cannot express "an SH-4 guest on a J4 host", so §2's four
  encodings and §3.2's `VINS.L` are all invisible to `cpugen collisions`. Owner:
  **B4**, in `jcore-cpu`. It is a tooling change with tests, sized like the
  collision sweep itself, and it is the single highest-value item left on this
  task: without it, the next `VINS.L` is found by a person reading tables again.
- **Teach `insns2asm` to count what it drops**, and then to know a SIMD group
  and a vector operand class (§1, [decisions/0008](decisions/0008-documented-but-unimplemented-encodings.md)).
  Owner: **B4**, in `jcore-cpu`, after the SIMD encodings settle.
- **Resolve the two DSP transcription pairs** (§2.1). Owner: whoever next holds
  an SH-DSP manual. Not B4; the `baseline` comment in
  `cmd/cpugen/collisions.go` should be updated to say so.
