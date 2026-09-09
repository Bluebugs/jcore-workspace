# 0008 — A documented-but-unimplemented instruction is a reservation row, not a decoder entry

**Status:** Accepted 2026-09-08. Wave-2 task **B4**, from
[j4-remediation-plan.md §B4](../j4-remediation-plan.md), which requires that
"every currently documented instruction gets its binary form verified and
re-homed through the tools".

---

## Context

§B4's method has four steps, and step 1 says *"enter it into `docs/insns.json`
(the canonical source) if not already present"*. Two things about that sentence
are wrong, and the second one changes what B4 can and cannot do.

**`docs/insns.json` is generated, not authored.** `cpugen insns -check`
regenerates it from `decode/gen-go/spec/*.toml` and compares byte-for-byte;
`make -C decode insns` rewrites it. The same TOML tree is `cpugen`'s input when
it emits `decode_body.vhd`, `decode_table_*.vhd` and `sh2instr.c`. So "entering
an instruction into the database" through the spec files is **not a
documentation edit — it generates decoder logic**, in a different repository,
for the illegal-instruction check as well as for the datapath. Measured this
session on `jcore-cpu@origin/master`: moving four opcodes in
`spec/system.toml` and re-emitting changed `decode_body.vhd`,
`decode_table_direct.vhd`, `decode_table_simple.vhd` and `sh2instr.c`.

That is fine for an instruction that has RTL. It is not fine for the ones B4 was
sent to sweep. The entire SIMD instruction set — 57 mnemonic rows in
[simd/spec.md](../simd/spec.md) — is documented and has no RTL anywhere, and
`isa-density`'s `lea` is in the same position. Generating a decoder for them
would be a hardware change smuggled in as a documentation task, and it would
also silently *remove* those encodings from the illegal-instruction trap.

The question this record answers: **how does a documented but unimplemented
instruction get its encoding verified and reserved, without generating decoder
logic for hardware that does not exist?**

## What the tools actually support

Read at `jcore-cpu@origin/master`, and exercised rather than assumed:

- **`freespace` records a claim from every row, whatever its variant columns.**
  `internal/freespace/claims.go` says so in as many words: "the per-claim
  variant list is what lets callers both filter against `--avoid` and detect
  encodings claimed by nothing at all."
- **A row with every variant column `false` survives regeneration.**
  `insns.Sync` clears the variant columns on existing rows and re-marks only the
  ones a spec instruction maps to; it never deletes an unmatched row. Measured:
  appending such a row and running `cpugen insns` reported *"216 matched, 0
  appended"*, kept the row, and `cpugen insns -check` then exited 0.
- **It cannot fail the collision gate spuriously.** `insns.Collisions` fails only
  on two rows with an identical encoding that **share an enabled variant**
  ([0003](0003-canonical-encoding-database.md) §Enforcement). A row enabled on
  nothing shares a variant with nothing.
- **It is self-reporting.** `annotateCollides` links identical-key rows
  unconditionally. Measured: a row carrying `1111nnnnmmmm1000` came back from
  regeneration annotated `"collides": ["fmov.s\t@Rm,FRn"]` without anyone
  asking it to.
- **`freespace` will also answer about an encoding that is in no database at
  all.** A `-form` with no `-` characters enumerates exactly one candidate and
  reports what it shadows, so a candidate can be tested before it is written
  anywhere.

## Decision

**1. A documented instruction with no RTL enters `jcore-cpu/docs/insns.json` as
a *reservation row*: every variant column `false`.** It is not entered into
`decode/gen-go/spec/`. It therefore claims the encoding against every future
`freespace` search, carries its own `collides` annotation, and generates no
decode logic and no change to the illegal-instruction trap.

**2. A reservation row is promoted to a real entry by adding the instruction to
`decode/gen-go/spec/`, at the point RTL is written, by the RTL owner.**
Regeneration then marks the variant columns and the row stops being a
reservation. The encoding does not move at that point; it was already verified.

**3. `freespace -form` is the query; the reservation row is the record.** Use the
tool to find a slot. Do not stop there: a slot verified and not recorded is a
slot the next `freespace` run will hand to somebody else.

**4. B4 may propose a re-home for an implemented encoding, and may not commit
one.** Committing it edits `decode/gen-go/spec/`, which is RTL. Every such
proposal in [encoding-sweep.md](../encoding-sweep.md) is marked as needing the
RTL / SoC co-owner, as [sh4-guest-model.md §8](../sh4-guest-model.md) already
required.

## Enforcement

The three gates that already exist do the work, and rule 1 was chosen because it
keeps all three meaningful rather than needing a fourth:

| Gate | What a reservation row does to it |
|---|---|
| `cpugen insns -check` | must stay green; the row is byte-stable across regeneration |
| `cpugen collisions` | unchanged; a variant-less row can never make it fail |
| `freespace --avoid …` | the row appears as a `shadows` line, never as `virgin` |

**One limitation, stated because it is otherwise invisible.** §B4 step 2 says to
round-trip each instruction through `insns2asm --emit check`. **That step does
not run on a reservation row in a new group.** `tools/insns2asm/internal/loader`
keeps only the groups in its `emittedGroups` map and drops the rest with **no
count and no message** — unlike the DSP path beside it, which counts what it
drops and prints the total. Measured: adding a `"group": "SIMD Instructions"`
row left the checker's output at exactly `ok: 318 instructions round-trip`,
unchanged. So the checker's silence about a new group is not a pass; it is an
absence. Teaching `loader` and `internal/operand` about a vector register class
is the work that makes step 2 real, and it belongs with the RTL, not before it.

**And `--emit check` is not the arbiter §B4 says it is for immediate
semantics.** `internal/oracle` reconstructs the *bit-pattern string* from the
parsed words and compares it to the original string. It models no
sign-extension, no shift and no field width. A question like "does `movi20s`
sign-extend before or after the shift" is invisible to it; see
[isa-density/spec.md §3.1](../isa-density/spec.md) for what settled that one
instead.

## Rejected alternatives

**Enter unimplemented instructions into `decode/gen-go/spec/*.toml`.** This is
what §B4 step 1 reads as if it means. Rejected: it generates a decoder — proven
above by diffing the emitted VHDL — for hardware that does not exist, and it
removes those encodings from the illegal-instruction trap, which is the opposite
of what an unimplemented encoding should do. It is also an RTL-repository change
with no RTL in it.

**Use `freespace -form` as the whole method and record nothing.** The check
works; the reservation does not exist. `freespace` classifies a candidate
against the claims it can see, so an encoding "verified free" in a review
comment is free again tomorrow. This is precisely how the tree acquired the
collisions B4 was sent to find: the bit patterns were chosen correctly at the
time and never written anywhere a tool would read.

**Put reservation rows in an existing emitted group so `--emit check` sees
them.** Rejected twice over. It mislabels the instruction, and it does not work:
`ir.Build` fails on any operand token `operand.Classify` does not know, so a
vector-register operand stops the whole run rather than being checked. The
honest sequence is to extend the tool when the instruction is real.

**Add a `reserved: true` field to the row.** Rejected as redundant. "Enabled on
no variant" already means exactly this, is already what every consumer reads,
and needs no new field, no new parser branch and no new way for the two to
disagree.

## What would reopen this

- **`decode/gen-go/spec/` gains a way to declare an encoding without generating
  decode logic** — a `reserved`/`unimplemented` instruction kind that the
  illegal-instruction check still traps. That would be strictly better than a
  reservation row, because one file would own both halves; rule 1 would move
  there and rule 2 would disappear.
- **`insns2asm` learns the SIMD group and a vector operand class.** Step 2 then
  applies to reservation rows and the limitation above is retired.
- **A reservation row is found to have influenced generated output.** That would
  falsify the measurement this record rests on and the rule would have to change
  the same day.
