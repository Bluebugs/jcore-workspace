# 0003 — One encoding database: `jcore-cpu/docs/insns.json`

**Status:** Accepted 2026-08-25. Wave-1 task B0c, from
[j4-remediation-plan.md §B0](../j4-remediation-plan.md).

---

## Context

[j4-remediation-plan.md §B0](../j4-remediation-plan.md) says:

> The canonical encoding database is **`docs/insns.json`**; the specs cite it,
> they do not restate bit patterns.

There were **two** files answering to that path, in two repositories, edited
independently, and the plan does not say which one it means:

| copy | entries | schema | `insns2asm --emit check` | `cpugen insns -check` |
|---|---|---|---|---|
| this superproject, `docs/insns.json` | 460 | 37 fields | **fails** | **fails** |
| `jcore-cpu`, `docs/insns.json` (`origin/master`) | 466 | 51 fields | ok, 318 round-trip | ok |

Every figure above was produced by running the tools, not recalled. The two
`check` results are the decisive ones and they are quoted verbatim below. The
field counts are the union of per-row keys (`len(set().union(*[set(e) for e in
instructions]))`); an earlier revision of this record gave them as 46 and 60,
which were not produced by anything. The delta of 14 and the superset relation
were right, and are re-derived below; the absolutes were not, in a sentence
claiming they were measured.

### What actually differs — enumerated, because six entries is small enough to

**Six instructions exist only in the `jcore-cpu` copy**, all of them the
MMU/exception control-register moves this project added:

```
LDC Rm, ASIDR      0100mmmm01111110      STC EXPEVT, Rn     0000nnnn01010010
LDC Rm, PTEH       0100mmmm01011110      STC INTEVT, Rn     0000nnnn01100010
LDC Rm, PTEL       0100mmmm01101110      STC TRA, Rn        0000nnnn01110010
```

**One entry exists only in the superproject copy, and it is malformed.** Both
copies carry `band.b` at `0011nnnn0iii1001 0100dddddddddddd`; the superproject
spells its operand `@disp12,Rn` and `jcore-cpu` spells it `@(disp12,Rn)`, which
is the SH-2A syntax. This is not a tie. It is the single reason the superproject
copy fails the round-trip oracle:

```
$ go run ./cmd/insns2asm -in <superproject>/docs/insns.json -emit check
insns2asm: excluded 40 DSP/coproc instructions
insns2asm: "band.b     #imm3,@disp12,Rn": unmapped operand token "@disp12"
exit status 1
```

against, for the `jcore-cpu` copy:

```
$ go run ./cmd/insns2asm -in ../../docs/insns.json -emit check
insns2asm: excluded 40 DSP/coproc instructions
ok: 318 instructions round-trip
```

**The schema is a strict superset in one direction.** Every field the
superproject copy has, the `jcore-cpu` copy also has; the `jcore-cpu` copy adds
fourteen the superproject copy lacks: the `J1`, `J2A` and `J4` product columns
with their `issue`/`latency`, per-variant `exceptions` for `J1`/`J2`/`J2A`/`J4`,
and **`collides`** — the generated, variant-aware encoding-collision annotation
that Wave-2's B4 sweep is supposed to operate on. There is no field the
superproject copy could contribute back.

**Of the 459 shared entries, 42 disagree on a timing field** — `J2.latency` (34),
`J2.issue` (15), `SH4.latency` (5) — and the disagreements run one way. The
superproject copy gives `fdiv FRm,FRn` an `SH4.latency` of **1** and
`fdiv DRm,DRn` **2**; the `jcore-cpu` copy gives **12** and **24**. Single- and
double-precision divide do not retire in one and two cycles on an SH-4. The
superproject copy holds the unrefined values.

**Only one of the two is generated.** `jcore-cpu`'s copy is produced from
`decode/gen-go/spec/` — the same instruction spec that generates the RTL decoder
— and `cpugen insns -check` verifies it is current:

```
$ go run ./cmd/cpugen insns -check                    # jcore-cpu copy
$ echo $?
0
$ go run ./cmd/cpugen insns -check -json <superproject>/docs/insns.json
insns.json is out of date — run `make -C decode insns`
exit status 1
```

The superproject copy has no generator, no checker, and no consumer that is a
tool: the only things reading it are four prose citations in
`isa-density/` and two scripts that take the path as an argument.

## Decision

**`jcore-cpu/docs/insns.json` is the canonical encoding database. The
superproject's copy is deleted**, and every citation is repointed at the
submodule path `jcore-cpu/docs/insns.json`.

This is [0001](0001-one-authority-per-fact.md) applied to a data file rather
than to prose, and the empirical grounds are the same ones 0001 argued from —
with one addition that makes the case here stronger than it was there. 0001
demoted the glossary because *a fact stays correct in the document whose author
is editing it, and rots in every copy of it*. Here we can say which copy that is
without appealing to judgement, because **only one of the two is attached to the
tools that would notice**: the generator, the round-trip oracle and the
collision annotator all live in `jcore-cpu` and all read `../../docs/insns.json`
from `tools/insns2asm/`. Someone adding an instruction runs those tools, in that
repository, and the file they edit is the file that is right. The superproject
copy has drifted six instructions and 42 timing values behind precisely because
nothing there would have told anyone.

Note what 0001 itself said about this file, in the passage rejecting its
alternative (a):

> The repository has already chosen exactly that shape once, for the one class
> of fact where it pays: encodings live in `docs/insns.json`, generated into the
> toolchain tables, with `insns2asm --emit check` as the oracle.

That sentence was true of one of the two files and false of the other. This
record says which.

### The consequence for Wave-2 B4, stated because getting it wrong misdirects it

**B4's encoding sweep operates on `jcore-cpu/docs/insns.json`.** It is the copy
with the `collides` annotation, the copy `freespace` reads by default, and the
copy the toolchain emitters generate from. Run against the superproject copy,
B4 would have swept a database missing the six control-register instructions —
three of which (`LDC Rm,PTEH`, `LDC Rm,PTEL`, `LDC Rm,ASIDR`) are exactly the
entries whose `collides` annotations record the overlap with DSP's
`LDC Rm,MOD`/`RS`/`RE`.

## Enforcement

| Check | Where | What it fails on |
|---|---|---|
| `one-encoding-database` | `check-doc-facts.py` | a `docs/insns.json` reappearing in this superproject; **and** the canonical copy being absent from `jcore-cpu` `origin/master` |
| `insns2asm --emit check` | jcore-cpu CI | any encoding that does not round-trip losslessly |
| `cpugen insns -check` | jcore-cpu CI | `insns.json` no longer matching the spec it is generated from |
| `scripts/insns-collision-sweep.py` | jcore-cpu CI | a **new** same-variant identical-encoding collision (baseline may only shrink) |

`one-encoding-database` is written to fail in **both** directions, and the second
half is the one that matters. A check that only asserted "no second copy here"
would go green forever the moment the canonical file were deleted or moved —
having verified that a file which no longer exists is not duplicated. So it also
asks `jcore-cpu` `origin/master` for `docs/insns.json` and fails when the answer
is no. This is the same shape as the `registry` check in 0001: the failure mode
worth guarding is not the violation, it is the check quietly having nothing to
check.

### On the collision sweep, and why it has a baseline

The plan asks for "a `freespace`-based collision sweep". `freespace` is a
*search* tool — it finds a free form given `--avoid` — so it is the instrument
for **re-homing** a collision, not for detecting one. Detection already exists
and is better than a sweep built on `freespace` would be: `annotateCollides` in
`decode/gen-go/internal/insns/sync.go` computes the collision set with the
variant rule that matters (identical encodings link unconditionally; merely
overlapping ones link only when they share a variant, or the DSP don't-care
fields bury every real collision under thousands of spurious ones), writes it
into `insns.json` as `collides`, and `cpugen insns -check` fails if the
committed annotation is stale. Every collision is therefore already visible in
review.

What was missing is a *verdict*. `collides` today has 94 entries and almost all
are legitimate — `fmov FRm,FRn` against `fmov DRm,DRn` is one encoding
discriminated by `FPSCR.SZ`, and `LDC Rm,PTEH` against DSP's `LDC Rm,MOD` is two
variants that never ship together. The defect worth failing the build on is
narrower: **two instructions with an identical encoding that share an enabled
variant.** There are exactly two today, both DSP, both real:

```
0100mmmm01110110   lds Rm,A0        vs  lds.l @Rm+,A0     (DSP)
0100nnnn01100010   sts.l DSR,@-Rn   vs  sts.l A0,@-Rn     (DSP)
```

They are recorded as a named baseline in the sweep and the list **may only
shrink**, exactly as 0001's waiver list may only shrink. A sweep that failed on
them today would have been switched off today; a sweep with no baseline at all
would have had to be written as a warning, and warnings are not checks.

## Rejected alternative — (a) make the superproject copy canonical and export to `jcore-cpu`

The superproject is where the specs live, and the plan's sentence appears in a
superproject document, so the naive reading is that the superproject's file is
the one meant. Rejected on four grounds.

1. **It is the copy that fails both oracles**, today, quoted above. Adopting it
   as canonical means either shipping a database that does not round-trip, or
   fixing it — and "fixing it" means importing the `jcore-cpu` copy, which is
   option (b) with extra steps.
2. **The tools cannot be moved to it.** `insns2asm` and `cpugen` are Go programs
   in `jcore-cpu`, `cpugen insns` *generates* `insns.json` from
   `decode/gen-go/spec/`, and that spec generates the RTL decoder from the same
   source. Making the superproject copy authoritative severs the encoding
   database from the decoder it must agree with — which is the specific
   coupling this whole task exists to enforce.
3. **It preserves duplication, which is the defect.** This is 0001's second
   objection to its own option (a), unchanged: two files, every change landing
   in both, atomically, forever. That edit was not made for six instructions and
   42 timing values, which is how the two got 6 apart.
4. **It puts the authority furthest from the work.** The person adding an
   encoding is in `jcore-cpu`, running `freespace` and `--emit check`. Under (b)
   their edit is complete when they finish it.

A narrower variant — keep both, add a CI check that they are byte-identical —
was also rejected. It is a machine-enforced version of the invariant that has
already failed, it makes every encoding change a two-repository atomic commit
across a submodule boundary, and it buys nothing that a single file does not:
the superproject can read `jcore-cpu/docs/insns.json` directly, because the
submodule is checked out for the doc checks anyway.

**The honest cost of (b).** A superproject reader who wants an encoding now
needs the submodule checked out. That is a real regression for anyone browsing
the docs repository alone, and it is not hypothetical — it is the same
dependency that makes `--strict` mandatory in CI. It is accepted because the
alternative is a file that is confidently wrong, and because the check that
enforces the doc-vs-code convention already requires the submodules.

## What would reopen this

- **The toolchain moves out of `jcore-cpu`.** If `insns2asm`/`cpugen` are
  extracted into a standalone repository, the database follows the tools, not
  this record.
- **The superproject needs the encodings without a submodule checkout** — a
  published docs site, say. The answer then is a *generated* export with a
  provenance header and a CI check that regenerates it, i.e. the file becomes a
  build artifact rather than a second authority. It is not a return to (a).
- **The collision baseline stops shrinking across two waves**, which would mean
  the two DSP collisions are being tolerated rather than fixed, and the sweep
  needs to change rather than be re-asserted. This mirrors 0001's own reopening
  condition for its waiver list.
