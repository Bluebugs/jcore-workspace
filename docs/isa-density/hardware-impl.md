# Hardware Implementation: `movi20`, `movmu`/`movml`, `lea`, and the delay-slot-free branches

**Status:** Draft / Proposed
**Companion to:** [`spec.md`](spec.md) (architecture), [`software-impl.md`](software-impl.md) (toolchain)
**Scope:** RTL changes to `jcore-cpu` for both the in-order J2/J32 core and the
J32-OoO core.

---

## 1. Overview

This document specifies the microarchitecture and RTL changes for the three
density instructions. It is organized as:

- §2 — Verified facts about the current RTL (with citations) that the design
  builds on.
- §3 — Where each change lands in the file/generator structure.
- §4 — `movi20` implementation (second-word fetch + immediate path), plus §4.7
  `lea` and the SH-2A disp12 loads, which ride the same second-word fetch.
- §4A — `jsr/n`/`rts/n`/`rtv/n` (reuse the existing non-delayed-branch redirect;
  the lowest-risk item, no fetch or sequencer change).
- §5 — `movmu`/`movml` in-order implementation (shared microcode chain).
- §6 — OoO implementation (uop cracking).
- §7 — Datapath/regfile impact.
- §8 — Verification.

A recurring theme: **the decoder is generated, not hand-written.** Almost every
change below is ultimately a change to the generator input (the per-category
TOML under `decode/gen-go/spec/`) plus, where noted, a
small amount of hand-written RTL for the genuinely new datapath/fetch behavior.
See [`software-impl.md`](software-impl.md) §1 for the regenerate-first
dependency.

---

## 2. Verified baseline (RTL facts with citations)

All line numbers are as read during this analysis; treat them as anchors, not
guarantees against later drift.

**Fetch / PC path** (`jcore-cpu/core/cpu.vhd`):
- Instruction register `if_dr : std_logic_vector(15 downto 0)` (`cpu.vhd` ~L41);
  fetched via the `inst_o`/`inst_i` bus (`cpu.vhd` ~L18–19).
- Fetch issue and PC control come from decode: `if_issue` (→ `instr.issue`),
  `ifadsel` (→ `instr.addr_sel`), `incpc` (→ `pc.inc`) (`decode.vhd` L99–102).
- **No second-word fetch exists.** One 16-bit word per instruction, PC += 2.
  This is the central gap for `movi20`.

**Decode / sequencer** (`decode/decode_body.vhd`, `decode/decode_core.vhd`,
`decode/decode_pkg.vhd`):
- `predecode_rom_addr(code)` maps the 16-bit opcode → 8-bit microcode *start*
  address (`decode_body.vhd` L17–284); it is arbitrary combinational logic
  (minimized boolean per address bit). E.g. group `x"1"` → `addr := x"9e"`
  (`L60`).
- Sequencer state `decode_core_reg_t` holds `op : operation_t` (with
  `addr : std_logic_vector(7 downto 0)`) and `instr_seq_zero : std_logic`
  (`decode_pkg.vhd` L277–285, L34–39). **There is no `instr_seq` step counter**
  — an earlier analysis draft wrongly claimed a 3-bit counter; the RTL has none.
- The advance is **`op.addr := op.addr + 1`** on each non-stalled slot
  (`decode_core.vhd` ~L114), inside the `slot='1'` update process
  (`decode_core.vhd` ~L98–118). The `dispatch` output of `decode_table`
  (`decode.vhd` L114) marks the last step: when `dispatch='1'`, the next slot
  loads the next instruction's start address (`next_op`); when `dispatch='0'`,
  the chain simply continues to `addr+1`.
- `dispatch` and every control output are **combinational on `op.code`**, so a
  microcode step may assert `dispatch` (and choose its control fields) as a
  function of the opcode's operand fields. This is what makes variable-length
  `movmu`/`movml` expressible without new sequencer hardware (§5.2).
- **No operand-driven loop / decrement-branch / jump-target primitive** anywhere
  in the sequencer. `op.addr` only ever +1's or reloads at `dispatch`.

**Immediate path** (`decode_pkg.vhd`, generated decode tables):
- `immval_t` enum (`decode_pkg.vhd` L21): fixed forms up to `IMM_S_12_1`
  (12-bit signed, the current widest). No 20-bit form.
- `imm_val : std_logic_vector(31 downto 0)` already exists on both
  `buses_ctrl_t` (L57) and `pipeline_ex_t` (L138); driven out as
  `buses.imm_val` (`decode.vhd` L164). **Storage width is already sufficient
  for a 20-bit immediate.**

**Register file** (`core/register_file.vhd`, `register_file_flops.vhd`):
- **2 read ports** (`num_x`/`addr_ra`, `num_y`/`addr_rb`) plus a dedicated
  always-`R0` read (`dout_0`); **2 write ports** (`num_z`/`we_ex` EX-writeback,
  `num_w`/`we_wb` late WB-writeback) — `reg_ctrl_t` (`decode_pkg.vhd` L102–110),
  driven in `decode.vhd` L170–173, L183, L186. `NUM_REGS=21` (16 GPRs + 5
  control/shadow). One transfer/cycle is within budget.
- **CRITICAL constraint** (`register_file.vhd` header L3–6, asserted in
  `register_file_flops.vhd` ~L39 "Write clash detected"): the Z and W write
  ports **must not both fire in the same ID step** — W is a delayed EX write, so
  the file is effectively 2R1W-with-delay. This directly constrains `movmu`
  *restore* (§5.2), where each element both writes a loaded register and updates
  `r15`: those two writes must be scheduled so they do not collide in one step.

**Pre-dec / post-inc** (microcode + datapath):
- `mov.l Rm,@-Rn` / `mov.l @Rm+,Rn` already adjust the address, drive memory via
  `mem.addr_sel` (`mem_addr_sel_t`, `decode_pkg.vhd` L26), and write the updated
  pointer back through a write port. **`movmu`/`movml` reuse this per element.**

**Multi-cycle stall** (`core/mult.vhd`, decode):
- `MAC.W`/`MAC.L` hold the pipeline via `mac_busy : mac_busy_t`
  (`decode_pkg.vhd` L23) with the iteration living in the MAC hardware unit, not
  in microcode. **This is the stall template for the new multi-cycle paths.**

> **Flagged uncertainties** (carried from analysis, must be closed in RTL):
> the precise cycle handshake to fetch a second word (no reference instruction
> exists); the exact longword `-4` pre-decrement immediate selector; whether the
> generator can emit multiple-entry shared microcode chains without new fields.

---

## 3. Where changes land

| Change | File(s) | Generated? |
|---|---|---|
| New opcodes → microcode entry addresses | `decode/gen-go/spec/*.toml` → `decode_body.vhd predecode_rom_addr`, `decode_table_*.vhd` | yes (regenerate) |
| New `immval_t` form `IMM_S_20` (+ `IMM_S_20_8` for `movi20s`) | `decode_pkg.vhd` enum + generated imm builder | yes |
| `lea`/disp12 group opcodes (`0011nnnnmmmm0001` prefix) → microcode entries | `decode/gen-go/spec/*.toml` → `predecode_rom_addr` group `x"3"` | yes (regenerate) |
| New `immval_t` forms `IMM_S_12_0` (`lea`, unscaled signed) + `IMM_U_12_2` (disp12 `mov.l`, ×4) | `decode_pkg.vhd` enum + generated imm builder | yes |
| `lea` ALU add to write port (no mem); disp12 `mov.l` = add → mem read → Rn | reuse existing ALU/mem datapath; microcode rows only | yes (regenerate) |
| `jsr/n`/`rts/n`/`rtv/n` opcodes → microcode entries (reuse `bt`/`bf` non-delayed redirect + existing call/return datapath; no new fetch/field) | `decode/gen-go/spec/*.toml` rows | yes (regenerate) |
| Second-word fetch sequencing | `core/cpu.vhd` fetch FSM + new control field | **hand RTL + generator field** |
| Word1 latch + 20-bit immediate assembly | `core/datapath.vhd` (or decode EX imm path) | hand RTL |
| `movmu`/`movml` shared microcode chain | `decode/gen-go/spec/*.toml` rows | yes (regenerate) |
| Illegal-in-delay-slot + reserved-anchor decode | `decode_body.vhd` predecode functions | yes |
| OoO uop cracking | OoO decode/rename (new `gen-go` or OoO decoder) | per OoO plan |
| Sim model | `decode/sh2instr.c` | yes (regenerate) + hand for fetch |

---

## 4. `movi20` / `movi20s` — in-order implementation

### 4.1 Shape

A 2-cycle (2 micro-step) instruction:

```
step 0 (instr_seq_zero):  capture word0 fields (n, sub-op, imm[19:16]);
                          issue a second fetch (PC += 2); hold pipeline 1 cycle
step 1:                   word1 arrives in if_dr; assemble 32-bit immediate;
                          write Rn via the Z write port; PC += 2 (total +4)
```

### 4.2 Second-word fetch (the novel part)

This is the only genuinely new front-end capability. Recommended approach,
modeled on the existing multi-cycle stall:

- Add a decode control signal `if_word2` (one new microcode-word field). When a
  microcode step asserts `if_word2`, the front-end:
  1. keeps the decoder on the same instruction (suppress `dispatch`),
  2. issues a fetch (`if_issue`) and advances PC by 2 (`incpc`) so the next
     `if_dr` is word1,
  3. routes the *current* `if_dr` (word0) into a new holding register `ir0`
     before it is overwritten.
- The pipeline holds for one cycle using the existing stall path
  (`next_id_stall` / the `mac_busy`-style sense), so no new stall mechanism is
  invented — only a new *reason* to stall.

> **Prototype-first item.** Because no existing instruction exercises a
> second fetch, the exact timing of `if_issue`/`incpc`/`if_dr` capture must be
> validated in simulation before the rest of `movi20` is built. Build a minimal
> "fetch two words, write the second to Rn" instruction first and confirm PC and
> `if_dr` behave, then layer the immediate assembly on top.

**Faulting second-word fetch (mandatory on J32 + TLB).** When the word1 fetch
crosses into a different page that misses the TLB or faults, the exception must
restart the *whole* two-word instruction, which requires the
**exception/architectural PC to remain at word0** even though the fetch pointer
has advanced by 2 to grab word1. Concretely:

- Step 0 advances the *fetch* pointer (`pc_inc`) to issue the word1 fetch but
  must **not** advance the committed instruction PC (the value that becomes
  `SPC` on exception entry) — that commit happens only at step 1 completion,
  alongside the `Rn` writeback. In the J2 datapath this is the distinction
  between `this.pc` (the instruction's PC) and `this.pc_inc` (next fetch); keep
  `this.pc` at word0 across the hold cycle.
- A fault signalled while the instruction is parked at step 0/1 (`ir0` holding
  word0) therefore enters the standard fetch-fault path with `SPC = word0_PC`.
  The handler is unaware this was a two-word instruction; `RTE` returns to
  word0, the instruction re-decodes, and the second fetch is re-issued against
  the now-mapped page. No `ir0` or microcode-step state needs saving — it is all
  reconstructed by re-execution.
- This is byte-for-byte the rule SIMD blocks use ([`../simd/spec.md`](../simd/spec.md)
  §6.5) and the MMU side documents as a requirement and verification point
  ([`../mmu/hardware-spec.md`](../mmu/hardware-spec.md) §5.1). On a core without
  an MMU there is nothing to do — a physical-bus error on the word1 fetch is
  fatal (no retry). OoO gets it free via the fetch buffer (§4.6, §6.4).

### 4.3 Immediate assembly

The immediate is built today in `decode_table_simple.vhd` (the SIMPLE decoder)
as a `case imm_enum` that slices/concatenates **`op.code`** only — e.g.
`IMM_U_8_0 => x"000000" & op.code(7 downto 0)` (`decode_table_simple.vhd` ~L37),
signed forms `imms_8_1`/`imms_12_1` similar. No form reads a second word. So:

- Latch word0 in `ir0` (new 16-bit register, or reuse a delay-slot holding
  register if timing allows — to be confirmed).
- Form the 20-bit value `imm20 = ir0[11:8] & word1[15:0]`.
- `movi20`: `imm_val = sign_extend_from_bit19(imm20)`.
- `movi20s`: `imm_val = sign_extend_from_bit19(imm20) << 8` (see [`spec.md`](spec.md)
  §8.5 — confirm sign-extension order against the SH-2A manual).
- Add `IMM_S_20` (and the `movi20s` variant) to `immval_t`. The immediate mux
  gains an input that concatenates `ir0[11:8]` with `word1`. `imm_val` storage
  is already 32-bit, so only the *source mux* changes, not the bus width.

### 4.4 Writeback

- `Rn = imm_val` via the Z write port (`reg.num_z`/`reg.wr_z`), zbus = imm path.
  Identical writeback to existing immediate-producing ops; only the immediate
  *source* is new.

### 4.5 Decode-side guards

- Extend `check_illegal_delay_slot` (`decode_body.vhd`) so a `movi20`/`movi20s`
  opcode in a delay slot raises slot-illegal. A 32-bit instruction cannot
  occupy a delay slot.
- Predecode the two new opcodes (`0000 nnnn iiii 0000` / `...0001`) in the
  `x"0"` group of `predecode_rom_addr` to the `movi20` microcode entry. Note
  these patterns currently fall into illegal space in that group — confirm the
  minimized logic update does not perturb neighboring entries (covered by the
  differential decode sweep, §8).

### 4.6 `movi20` on OoO

Trivial relative to in-order: the OoO fetch unit (OoO §4.1, already gaining a
fetch buffer) delivers both words to decode in one decode action; decode emits
**one uop** carrying the assembled 32-bit immediate. No microcode chain, no
stall. The immediate assembly logic (§4.3) is shared.

### 4.7 `lea` and the SH-2A disp12 loads — in-order implementation

`lea` and the adopted disp12 `mov.l` ([`spec.md`](spec.md) §3.4) are the
**cheapest** members of this bundle: they reuse the §4.2 second-word fetch
unchanged and add **no new datapath** — only microcode rows and one new
immediate form. Both are two-word, so they share `movi20`'s shape (fetch word0,
issue word1 fetch, hold one cycle, complete on word1).

**`lea @(disp,Rm),Rn` — 2 micro-steps:**

```
step 0 (instr_seq_zero):  capture word0 (n, m, group=0011..0001);
                          issue second fetch (PC += 2); hold one cycle
step 1:                   word1 in if_dr; disp = sign_extend_12(word1[11:0]);
                          ALU: Rn = Rm + disp  (Rm via read port, disp via imm mux);
                          write Rn (Z port); PC += 2 (total +4)
```

- **No memory access.** `lea` is just an ALU add of a register and an immediate,
  writing one register — the same datapath as `add #imm,Rn` except the base is an
  arbitrary `Rm` (read port `num_x`) instead of `Rn`, and the immediate is the
  sign-extended 12-bit `disp`. The existing add path and Z write port suffice.
- **New immediate form `IMM_S_12_0`**: like the existing `imms_12_1`
  (`decode_table_simple.vhd`) but sourced from **word1** rather than `op.code`,
  and **unscaled** (no `<<` ; [`spec.md`](spec.md) §4.6). The immediate
  mux gains a word1-sourced input — the same plumbing §4.3 adds for `movi20`,
  reused.

**`mov.l @(disp12,Rm),Rn` (GOT-slot load) — 3 effective steps:** add
`Rm + (disp << 2)` (new immediate form `IMM_U_12_2`: unsigned, ×4, from word1),
drive a longword memory read at that address (existing `mem.addr_sel` load path),
write `Rn`. This is an ordinary `mov.l @(...),Rn` whose address comes from the
12-bit word1 displacement instead of a 4-bit `op.code` displacement — the memory
and writeback datapath is unchanged; only the address-immediate source is new.
Normal `mov.l` address-error/alignment behaviour applies ([`spec.md`](spec.md) §5).

**Decode-side:** predecode the `0011nnnnmmmm0001` prefix (group `x"3"` of
`predecode_rom_addr`) to the disp12 microcode entries, dispatching on word1's
high nibble (minor `1010`=`lea`, `0110`=`mov.l` load, etc.). Extend
`check_illegal_delay_slot` to flag the whole group (32-bit, illegal in a delay
slot — §4.5). As with `movi20`, confirm the predecode boolean-minimization does
not perturb neighbouring `0011` (arithmetic-group) entries — covered by the
differential decode sweep (§8.1).

> **Note — second-word fetch is the shared prerequisite.** `lea` and the disp12
> loads add essentially nothing the §4.2 fetch work does not already build. Once
> `movi20`'s second fetch is validated, these are microcode-row + immediate-form
> changes only. They are the lowest-risk way to *amortise* the §4.2 effort across
> more than one instruction.

---

## 4A. `jsr/n` / `rts/n` / `rtv/n` — delay-slot-free branches

These are the **cheapest** instructions in the bundle: 16-bit, no second-word
fetch, no new immediate form, no microcode chain, no new sequencer state. They
reuse two mechanisms the core already has — the **non-delayed-branch redirect**
(from `bt`/`bf`) and the **call/return datapath** (from `jsr`/`rts`) — and only
decouple them.

### 4A.1 The mechanism already exists

SH's `bt`/`bf` are **non-delayed**: on a taken `bt`/`bf` the front-end squashes
the sequentially-fetched successor and redirects fetch to the target, with no
delay-slot instruction issued. (`bt/s`/`bf/s` are the delayed variants.) So the
core already contains the "take a branch, do not execute a successor" path. The
`/N` branches are that path applied to call/return:

| Instruction | Reuses redirect of | Plus datapath of | Net new logic |
|---|---|---|---|
| `jsr/n @Rm` | `bt`/`bf` (taken, no slot) | `jsr @Rm` (`PR ← return; PC ← Rm`) | predecode mapping only |
| `rts/n`     | `bt`/`bf` (taken, no slot) | `rts` (`PC ← PR`) | predecode mapping only |
| `rtv/n Rm`  | `bt`/`bf` (taken, no slot) | `rts` + a GPR→R0 move | `R0 ← Rm` write before redirect |

`jsr` already computes the link value and writes `PR`; `rts` already drives
`PC ← PR`. The *only* difference for the `/N` forms is that **no delay slot is
issued** — which is exactly the `bt`/`bf` behaviour. `rtv/n` adds one register
read (`Rm`) routed to the `R0` write port before the redirect (the existing
register-move datapath).

### 4A.2 In-order (J2/J32)

- **Predecode:** map `0100mmmm01001011` (`jsr/n`), `0000000001101011` (`rts/n`),
  `0000mmmm01111011` (`rtv/n`) to microcode entries that assert the
  **non-delayed taken-branch** control (the `bt`/`bf` redirect select) together
  with the link/return datapath. No new control field — both signals already
  exist; this is a new *combination* in the decode table.
- **`PR` value:** `jsr/n` writes `PR =` address of the instruction *after* the
  `jsr/n` (no slot skipped). The link adder that `jsr` uses for `PC+4` (skip
  slot) selects `PC+2` here. This is one mux input on the existing PR-link path,
  the only genuinely new datapath detail and the item to check in sim.
- **`rtv/n`:** read `Rm` → `R0` write port, then redirect to `PR`. Schedule the
  `R0` write and the redirect so they do not collide with the W/Z write-port
  rule (§2 CRITICAL constraint) — `rtv/n` writes only `R0` (one port), so this is
  trivial, but confirm the redirect does not also need a same-cycle write.
- **No delay slot:** because the redirect is the `bt`/`bf` (non-delayed) select,
  the successor is squashed by the existing mechanism. Nothing new.

### 4A.3 Illegal-in-delay-slot

A `/N` branch in another branch's delay slot is illegal — the **branch-in-slot**
rule, already enforced by `check_illegal_delay_slot` for every branch. Add the
three encodings to that predecode check (independent of the 32-bit-in-slot rule
used for `movi20`/`lea`).

### 4A.4 OoO (J32-OoO)

Simpler than in-order: a non-delayed branch has *no* delay-slot instruction to
fetch, predict around, or track, so it is strictly easier than the delayed forms
the OoO front-end already handles. `jsr/n` is a branch-with-link uop (writes the
renamed `PR`); `rts/n`/`rtv/n` are return uops (predicted via the return-address
stack, OoO §6); `rtv/n` carries an extra `R0 ← Rm` move uop or folds the move
into the return uop's writeback. No delay-slot fixup, which removes a special
case the delayed `jsr`/`rts` need.

> **Lowest-risk, do-first candidate.** Unlike `movi20` (new fetch) or
> `movmu`/`movml` (sequencing), the `/N` branches need no new hardware capability
> — only a decode-table combination of two existing controls plus one PR-link mux
> input. They can land independently of the second-word-fetch work.

---

## 5. `movmu` / `movml` — in-order implementation

### 5.1 Per-element primitive

Each element is exactly an existing operation:
- save: `mem[r15-4] = R[k]; r15 -= 4` (the `mov.l Rk,@-r15` datapath)
- restore: `R[k] = mem[r15]; r15 += 4` (the `mov.l @r15+,Rk` datapath)
- `PR` element (upper forms): same memory step, source/destination is `PR`
  instead of a GPR (the `sts.l pr,@-r15` / `lds.l @r15+,pr` datapath already
  exists).

So **no new datapath** — only sequencing across a variable number of elements.

### 5.2 Shared straight-line chain (primary) — fitting the +1-only sequencer

The chosen approach (see [`spec.md`](spec.md) §4.3), grounded in the verified
sequencer (§2): `op.addr` only ever +1's, and both the predecode *start* address
and the per-step `dispatch` (last-step marker) are arbitrary combinational
functions of the opcode. That gives the two degrees of freedom variable-length
transfer needs — a variable **start** and a variable **stop** — one per
direction.

Save (`@-r15`, descending): one fixed start, early `dispatch`. The pushed set
always begins at the top (`PR`, then `R14, R13, ...`) and differs only in where
it ends (`Rm`), so all save opcodes share one start and one chain; the step that
pushes `R_k` asserts `dispatch` when `k == m` (a combinational compare against
the anchor field, legal because `dispatch` is combinational on `op.code`):

```
movmu.l save chain (single start E_SAVE, op.addr +1 each step):
  E_SAVE   : push PR                ; dispatch = (anchor == PR-only)
  E_SAVE+1 : push R14               ; dispatch = (m == 14)
  E_SAVE+2 : push R13               ; dispatch = (m == 13)
  ...
  E_SAVE+7 : push R8  (..R0 movml)  ; dispatch = (m == 8) [/ 0]
```

Restore (`@r15+`, ascending): variable start, fixed `dispatch`. The popped set
always ends at the top (`..., R14, PR`) and differs only in where it begins
(`Rn`), so `predecode_rom_addr` maps the anchor `n` to start address `E_REST+n`,
and the chain runs to a fixed final step that asserts `dispatch`:

```
movmu.l restore chain (start E_REST+n, op.addr +1 each step):
  E_REST+n : pop R_n
  ...
  pop R14
  pop PR                            ; dispatch = 1 (fixed last step)
```

- Both map onto the existing model with **no counter, no loop-back, no new
  microcode field, no new sequencer state** — only extra microcode rows plus
  predecode/`dispatch` expressions that read the anchor nibble.
- `r15` updates once per step, reusing the existing pre-dec/post-inc pointer
  writeback (§5.1). For **non-interruptible v1** ([`spec.md`](spec.md) §4.4) the
  guarantee comes from masking interrupt acceptance for the chain duration
  (§5.5), so even if the existing pre-dec commits `r15` each cycle, no interrupt
  observes a partial `r15`/register-set state.
- **Write-port-clash watch (restore):** each restore step writes a loaded GPR
  (W port) *and* advances `r15` (Z port); per §2 the two write ports must not
  fire in the same ID step. The existing `mov.l @Rm+,Rn` already splits the
  pointer update and the loaded-data write across steps — the restore chain must
  follow the same split, or the per-element step count doubles. This is the most
  likely place a naive 1-step-per-register chain breaks in synthesis.

**Cost:** ≤ 8 steps (movmu) / ≤ 16 steps (movml) of microcode for the save
chain, plus a same-length restore chain whose per-anchor starts are entry offsets
*into* that one chain (not duplicated rows). Order-of-magnitude a few dozen
microcode entries total — confirm against the 256-entry address budget
([`spec.md`](spec.md) §8.3).

> **Open generator question** ([`spec.md`](spec.md) §8.2): the save chain needs a
> *per-step, opcode-conditional* `dispatch`; the restore chain needs a
> *per-anchor start address*. Both are framework-compatible (dispatch and
> predecode are both arbitrary combinational logic on `op.code`), but **no
> existing instruction uses either pattern**. Confirm the Go generator (`gen-go`)
> can express them without a new microcode field. If not, the
> fallback is per-anchor unrolled rows (more ROM) or the §5.4 counter approach.

### 5.3 Reserved / illegal anchors

- `movmu` with `m = 15` implies an empty range (only `PR`, or wrap) — decode as
  **illegal instruction** (route predecode to the general-illegal microcode
  address, `decode_pkg.vhd` `GENERAL_ILLEGAL => x"d1"`).
- Confirm SH-2A's exact treatment of boundary anchors and match it for binary
  compatibility ([`spec.md`](spec.md) §3.2 / §8).

### 5.4 Fallback: counter + loopback (NOT primary)

If the shared-chain approach is blocked (ROM budget, generator limitation, or
predecode fan-out timing), the alternative is:

- Add a 4-bit register-index counter to `decode_core` state.
- Add a microcode next-address mode "repeat this step, decrement counter, until
  zero" (a genuinely new microcode field + sequencer logic).
- One microcode step then handles all lengths.

This is cleaner conceptually but is **new sequencer RTL and a new microcode
field** — higher risk, more verification. Documented here only as a contingency.

### 5.5 Interrupt handling (non-interruptible v1)

- Hold off interrupt acceptance for the duration of the chain (assert the
  existing interrupt-mask / stall sense used during multi-cycle ops). Worst case
  ~8 longword memory cycles of added latency — bounded and acceptable.
- This guarantees `r15` and the register set are mutually consistent at every
  interruptible boundary, so no partial-state save/restore is needed.

**Recoverable page fault mid-chain (J32 + TLB).** Holding off *interrupts* is
not enough once the stack lives in translated memory: a synchronous page fault
on one of the chain's accesses cannot be deferred. The single-commit-point
design that makes the chain non-interruptible also makes it cleanly
**restartable** — the fault is taken with `SPC` = the `movmu`/`movml`
instruction's own PC, and because `r15` and the destination register/memory
writes are not committed until the chain completes, `RTE` re-runs the entire
transfer from the unchanged `r15`, replaying loads/stores against the same
addresses with the same data (idempotent). The only obligation on the platform
is that the instruction's whole footprint (≤ 32 bytes, ≤ 2 pages) be
simultaneously mappable, so the restart eventually makes progress. No new
hardware is needed beyond not committing `r15`/register writes early — which v1
already requires. (See [`spec.md`](spec.md) §5; OoO instead gets precise partial
completion per §6.2, and never restarts.)

### 5.6 `movmu`/`movml` on OoO — see §6.

---

## 6. OoO implementation (uop cracking)

Per OoO spec §4.3 / §5.1, the OoO decoder cracks these into uops. This is the
**preferred** implementation and the reason the instructions live in the J32OOO
plan.

### 6.1 `movmu`/`movml` → uop sequence

Decode emits, for a range of *c* registers:

```
movmu.l Rm,@-r15  (save):
  uop 0:  store PR,    @(r15 - 4)        ; addr-gen uop folds the -4
  uop 1:  store R14,   @(r15 - 8)
  ...
  uop c-1: store Rm,   @(r15 - 4c)
  uop c:  r15 <- r15 - 4c                ; single pointer-update uop
```

- Each store uop is independently renamed/issued/retired. Addresses are derived
  from the *architectural* `r15` (read once at rename) plus a decode-time
  constant offset, so the stores do not serialize on the pointer update.
- The final `r15` update is one uop; younger instructions that read `r15` get it
  via rename.
- Restore is the mirror: `c` load uops (each writes one arch register, allocated
  a fresh physical register by rename) + one `r15` update uop. `PR` is written
  via the control-register path (OoO §4.4).

### 6.2 Precise exceptions (OoO §5.2)

A faulting memory uop (e.g. misaligned `r15`, page fault under a future MMU)
signals the exception; the ROB retires all older uops and squashes the faulting
uop and everything younger. Result: a *precise* partial completion with no
special handling — the property the in-order core must engineer with the
non-interruptible rule (§5.5).

### 6.3 Uop count and ROB pressure

Worst case 9 uops (movmu, 8 regs incl. PR + pointer) or 17 (movml, 16 regs).
This consumes ROB / issue-queue entries; the decoder must throttle if the ROB
cannot accept the whole crack in one cycle (standard microcoded-uop handling —
crack across multiple decode cycles, holding fetch). Note this throttling reuses
the same "decode produces more uops than slots" mechanism any cracked
instruction needs, so it is not specific to these instructions.

### 6.4 `movi20` → 1 uop

Decode assembles the 32-bit immediate from the two fetched words and emits a
single immediate-writing uop. Requires the fetch unit to present both words;
since OoO Phase 1 adds a fetch buffer (OoO §6.1), word pairing is naturally
handled there.

### 6.5 `lea` / disp12 load → 1 uop

Both crack to a single uop, the simplest case:

- `lea` → one ALU uop `Rn = Rm + disp` (renamed source `Rm`, fresh physical
  `Rn`); no memory, no `R0`, fully pipelined alongside other ALU uops.
- disp12 `mov.l` → one load uop `Rn = mem[Rm + (disp<<2)]`, identical to any
  other load uop for scheduling, disambiguation, and fault handling (precise via
  the ROB, §6.2). Word pairing handled by the same fetch buffer as `movi20`
  (§6.4).

These add no new uop *types* — `lea` is an existing add-immediate uop with a
12-bit immediate; the disp12 load is an existing load uop with a 12-bit address
offset. The only front-end change is delivering the second word, already done
for `movi20`.

### 6.6 `jsr/n` / `rts/n` / `rtv/n` on OoO — see §4A.4

Covered with the in-order discussion in §4A.4: a non-delayed branch is *simpler*
for the OoO front-end than the delayed forms (no delay-slot instruction to fetch
or track). `jsr/n` = branch-with-link uop; `rts/n`/`rtv/n` = return uops via the
return-address stack; `rtv/n` carries an extra `R0 ← Rm` move. No new uop type.

---

## 7. Datapath / register-file impact summary

| Resource | `movi20` | `movmu`/`movml` (in-order) | `movmu`/`movml` (OoO) | `lea` | disp12 `mov.l` |
|---|---|---|---|---|---|
| Register read ports | 0 (imm only) | 1/cycle (save) | 1/uop | 1 (`Rm`) | 1 (`Rm`) |
| Register write ports | 1 (Rn) | 1/cycle (restore) | 1/uop | 1 (`Rn`) | 1 (`Rn`) |
| New datapath | imm source mux (word0[11:8]++word1) + `ir0` latch | none (reuses pre-dec/post-inc) | none | none (reuses ALU add + word1 imm mux) | none (reuses load path + word1 imm mux) |
| Fetch | **second-word fetch FSM** | none | fetch-buffer word pairing | reuses `movi20` second-word fetch | reuses `movi20` second-word fetch |
| New decode/microcode field | `if_word2`, `IMM_S_20` | entry-point predecode (no new field if shared-chain works) | uop-crack table | `IMM_S_12_0` (word1, unscaled) | `IMM_U_12_2` (word1, ×4) |
| New sequencer state | `ir0` | none (primary) / counter (fallback) | n/a (ROB handles it) | `ir0` (shared w/ `movi20`) | `ir0` (shared) |

**Delay-slot-free branches** (`jsr/n`/`rts/n`/`rtv/n`) sit outside this table
because they add essentially nothing: 0–1 register read (`Rm` for `jsr/n`/`rtv/n`),
0–1 write (`PR` for `jsr/n`, `R0` for `rtv/n`), **no** fetch change, **no** new
immediate form, **no** new sequencer state. The only new datapath is one mux
input on the existing `PR`-link adder (`PC+2` instead of `jsr`'s `PC+4`); the
redirect itself is the existing `bt`/`bf` non-delayed path (§4A).

The register file needs **no new ports** for any variant. `lea`, the disp12
load, and the `/N` branches are the cheapest entries: zero new datapath beyond
the word1 immediate mux that `movi20` already introduces (and, for the branches,
the one PR-link mux input).

---

## 8. Verification

### 8.1 Decoder differential (mandatory, cheapest)

Regenerate the decoder with the new instructions and run the exhaustive
(opcode × slot) differential sweep from the decoder-migration spec
(`jcore-cpu/jcore-decoder-migration-spec-v2.md` §6 Layer 3) against the
pre-change decoder. Required result: the three new opcodes decode to the new
microcode; **every other opcode is bit-identical**. This catches predecode
boolean-minimization regressions (§4.5, §5.3).

### 8.2 Unit tests (per instruction, per count)

- `movi20`/`movi20s`: positive, negative, zero, max-range, and (for `movi20s`)
  the shifted/upper-bit cases. Confirm PC += 4 and delay-slot-illegal.
- `movmu`/`movml`: every register count (1..8 / 1..16), both directions,
  round-trip (save then restore restores identical state and `r15`), and the
  reserved-anchor illegal cases.
- `lea`: positive/negative/zero `disp` across ±2048; `Rm = Rn` (in-place add)
  and `Rm ≠ Rn`; `Rm = r0`/`r12`/`r15`; assert **no memory access** and no flag
  change; PC += 4; delay-slot-illegal. disp12 `mov.l`: aligned/misaligned `Rm`,
  full 12-bit displacement range, `Rm = r12` GOT pattern.
- `jsr/n`/`rts/n`/`rtv/n`: assert **the successor is not executed** (place a
  poison instruction after the branch; it must not retire) — the core
  differentiator vs `jsr`/`rts`. For `jsr/n`: `PR` = address of that successor
  (return lands there). `rts/n`: returns to `PR`. `rtv/n Rm`: `R0 = Rm` *and*
  returns; check `Rm = r0` (identity) and `Rm ≠ r0`. All three: `T` and other
  flags unchanged; branch-in-delay-slot raises illegal. Round-trip
  `jsr/n`→callee→`rts/n` lands on the instruction after the call.

### 8.3 Exception precision

Force a misaligned `r15` at element *k* and assert: in-order leaves the
architecturally-correct atomic state (nothing committed, exception taken); OoO
leaves elements `0..k-1` retired, `k..end` squashed.

### 8.4 In-order ↔ OoO co-simulation

Same program through both cores; compare architectural state (GPRs, `r15`, `PR`,
memory) at every retirement boundary. Reuses the OoO co-sim harness (OoO §7).

### 8.5 Sim model parity

The C sim model (`decode/sh2instr.c`) must implement the same semantics; the
generated portion comes from the spreadsheet/TOML, the second-word fetch needs a
hand addition. Cross-check sim vs RTL on the unit suite.

### 8.6 FPGA smoke (pre-merge)

Build a prologue/epilogue-heavy program (e.g. recompiled BusyBox subset, see
[`software-impl.md`](software-impl.md) §7) and run on the iCE40/ULX3S target to
catch PnR-specific issues the simulators miss.

---

## 9. Build / configuration

- The feature is a core configuration generic (mirroring the existing
  decoder-style VHDL config). `J32_DENSITY = false` builds a strict SH-2 core
  where the encodings are illegal; `true` enables them.
- Regeneration of the decoder is a prerequisite (see [`software-impl.md`](software-impl.md)
  §1) — these changes are *generator-input* changes plus the hand-written fetch
  and immediate-assembly RTL listed in §3.
