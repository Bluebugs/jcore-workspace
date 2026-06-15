# Hardware Implementation: `lea @(disp,PC),Rn`

This document specifies the RTL changes for the PC-relative address instruction
defined in [spec.md](spec.md). It is written as a **delta** over the
`isa-density` implementation ([`../isa-density/hardware-impl.md`](../isa-density/hardware-impl.md)),
because this instruction reuses three mechanisms built there and adds almost
nothing structural.

## 1. Overview

`lea @(disp,PC),Rn` = **`movi20`'s second-word fetch + displacement assembly**
(isa-density hardware-impl §4.2–§4.3) **+ `mova`'s PC+disp adder** + **`lea`'s
any-`Rn` writeback** (isa-density hardware-impl §4.7). No new sequencer, no new
architectural register, no new write port, no new exception. It is a 2-step
linear microcode run that fits the front-end's `+1`-only `op.addr` model
(isa-density §2), exactly like `movi20`.

Prerequisite: the `isa-density` second-word fetch must land first. This is a
*fourth* consumer of that one-time gate (after `movi20`, the disp12 loads, and
`lea`); it adds no further front-end change.

## 2. Verified baseline reused

All cited from the RTL facts in isa-density hardware-impl §2 (which carry
`jcore-cpu` file:line citations); not re-derived here:

- **Second-word fetch** (`movi20`): word0 is captured in a holding register, a
  second fetch is issued reusing `if_issue`/`incpc`/`ifadsel`, word1 arrives the
  next cycle. (isa-density hardware-impl §4.2 — the genuinely novel front-end
  part, shared.)
- **Displacement/immediate assembly**: `imm_val` storage is already 32-bit; the
  `movi20` path concatenates word0 operand bits with word1 into a wide value.
  (isa-density hardware-impl §4.3.)
- **`mova` PC+disp adder**: `mova @(disp,PC),R0` already feeds a PC value and a
  scaled displacement into the address adder. (Baseline SH-1 op.)
- **`lea` any-`Rn` writeback**: the disp12 group already writes an arbitrary
  `Rn` via the EX write port (`num_z`). (isa-density hardware-impl §4.7.)
- **Single write port suffices**: one register written per instruction — no
  Z/W write-clash concern (unlike `movmu`; isa-density hardware-impl §5).

## 3. In-order (J2/J32) implementation

### 3.1 Decode row

Add one row to the generator source (`decode/gen-go/spec/*.toml`, per
the decoder-architecture notes), prefix `0011nnnnmmmm0001`, word1 minor `1011`:

- **`mmmm` is NOT a base register for this minor.** The decode special-case:
  when `minor == 1011`, suppress the base-register read of `mmmm` and route
  `mmmm` (= `word0[7:4]`) to the displacement assembler as `disp[15:12]`. This
  is one mux select keyed on the already-decoded minor (spec §4.3).
- `Rn` = `word0[11:8]` → EX write port (`num_z`), as for `lea`.

### 3.2 Microcode (2 steps, linear, `dispatch` on step 1)

```
step 0 (op.addr = start):
    capture word0 into the holding reg (shared movi20 path)
    issue second-word fetch (shared movi20 path)
    latch Rn select; dispatch = 0
step 1 (op.addr = start+1):
    disp16 = (word0[7:4] << 12) | word1[11:0]        ; reclaimed-nibble assembly
    sdisp  = sign_extend_16(disp16)
    addr   = PC_word0 + 4 + (sdisp << 1)             ; mova adder; <<1, no &~3 mask
    Rn <- addr        (num_z write)
    dispatch = 1                                      ; last step
```

The only arithmetic delta versus `mova` is the operand into the adder: a
sign-extended, `<<1` displacement assembled across two words, instead of an
8-bit `<<2` field from one word — and **no `& ~3` masking of PC** (spec §4.1).
The PC fed to the adder is the address of word0 (`+4` added in the adder),
matching the relocation contract (spec §3.2).

### 3.3 Decode-side guards

- **Illegal-in-delay-slot**: reuse the `movi20` slot-illegal guard verbatim
  (isa-density hardware-impl §4.5) — a two-word instruction cannot occupy a
  delay slot.
- No other guard. No memory stage, so no address-error path; `T` not written.

### 3.4 Critical path

Same risk class as `movi20`: the second-word fetch is the timing-sensitive part
(isa-density §4.5 / hardware-impl §4.2). The add itself reuses the existing
`mova` adder and is not on a new critical path. No new hazard versus `movi20`.

## 4. OoO (J32-OoO) implementation

Cracks to **1 uop** — an ALU op `Rn = PC_word0 + 4 + (sext16(disp) << 1)` with
no memory operand and no flag write, identical in shape to how `movi20` and
`lea` crack to 1 uop (isa-density hardware-impl §4.6, §5.3, §6.5). The PC of
word0 is available at rename (it is the uop's own PC); the displacement is an
immediate carried in the uop. Precise exceptions: trivial — the only exception
is the decode-time slot-illegal, raised before issue. ROB pressure: 1 entry.

## 5. Datapath / register-file impact summary

| Resource | Change |
|---|---|
| Front-end fetch | none beyond the shared `movi20` second-word fetch |
| Microcode | +1 linear 2-step run (fits `+1` sequencer) |
| Decode tables | +1 row at `0011nnnnmmmm0001`/minor `1011`; +1 mux select (mmmm→disp when minor=1011) |
| Address adder | reused (`mova`); operand = `sext16(disp)<<1`, PC unmasked |
| Register file | +1 EX write (`num_z`); no new port; no write-clash |
| Architectural state | none added (no new register, no flag) |
| Exceptions | reuse `movi20` slot-illegal; no new path |

## 6. Verification

Per spec §7 and isa-density hardware-impl §8:

- **§8.1 decoder differential** — the *only* new decode entries must be the
  previously-reserved minor-`1011` points; any other delta = missed collision.
- **Unit tests** — `(Rn, disp16, word0_addr)` vectors: `Rn == word0_addr + 4 +
  (sext16(disp) << 1)`; cover `+0x7FFF`, `−0x8000`, `0`, sign boundary; assert
  `T`/other GPRs unchanged; assert slot-illegal in a delay slot.
- **Sim parity** — mirror the operation in the C sim model (`sim/sh2instr.c` per
  the decoder-architecture notes) and co-simulate against RTL.
- **FPGA smoke** — a handful of `lea @(L,PC),Rn` with `L` both ahead and behind,
  checked against the linker-computed addresses.

## Document status

Draft, 2026-05-31. Specified as a delta over isa-density `movi20`/`lea`; depends
on that second-word-fetch landing first. No new structural RTL beyond one decode
row, one mux select, and reuse of the `mova` adder.
