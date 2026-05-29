# Software Implementation: `movi20` and `movmu`/`movml`

**Status:** Draft / Proposed
**Companion to:** [`spec.md`](spec.md) (architecture), [`hardware-impl.md`](hardware-impl.md) (RTL)
**Scope:** toolchain (binutils, GCC), ABI, simulator, debugger, and the
measurement plan that confirms the code-density win.

---

## 1. Prerequisite: decoder regeneration & the sim model

The CPU decoder and the C simulator model (`jcore-cpu/decode/sh2instr.c`) are
**generated** from `decode/gen` (Clojure + the `.ods` spreadsheet today; the
planned Go + TOML generator, `gen-go/`, is specified in
`jcore-cpu/jcore-decoder-migration-spec-v2.md` but not yet built). Two facts
shape all software work:

1. **The generation toolchain (lein/JVM/Clojure) is not currently installed**,
   and `gen-go/` does not exist. Before any decoder change can be built, decide:
   - restore the Clojure flow (install JDK + leiningen), or
   - land the Go migration first and add the instructions in TOML.

   The Go migration is the better foundation for *adding instructions* (the
   `.ods` is a binary blob — terrible for review/diff), and its open questions
   already flag "J32 forward-compatibility" of the field vocabulary. If multiple
   SH-2A instructions are planned (these two are the first of a longer density
   list), do the migration first.

2. **The sim model must stay in lockstep.** The generated part of `sh2instr.c`
   comes from the same spec rows; the `movi20` second-word fetch needs a hand
   addition to the sim's fetch loop (the sim, like the RTL, currently assumes
   16-bit fetch). Sim and RTL are cross-checked by the unit suite
   ([`hardware-impl.md`](hardware-impl.md) §8.5).

This dependency is why [`spec.md`](spec.md) §8.4 lists "regenerate-first" as a
gating open question.

---

## 2. Assembler (binutils `gas`)

### 2.1 Mnemonics

Add the SH-2A mnemonics (binutils already knows them for `-isa=sh2a`; the work
is enabling them under a J32 target/flag):

```
movi20   #imm20, Rn      ; 0000 nnnn iiii 0000  iiiiiiiiiiiiiiii
movi20s  #imm20, Rn      ; 0000 nnnn iiii 0001  iiiiiiiiiiiiiiii
movmu.l  Rm, @-r15       ; 0100 mmmm 1111 0000
movmu.l  @r15+, Rn       ; 0100 nnnn 1111 0100
movml.l  Rm, @-r15       ; 0100 mmmm 1111 0001
movml.l  @r15+, Rn       ; 0100 nnnn 1111 0101
```

### 2.2 Encoding/assembly rules

- `movi20`: emit two 16-bit words (big-endian to match J-core). Operand range
  check: `−524288 ≤ imm ≤ 524287`; out-of-range is an assembler error (the
  compiler/relaxation must pick a different sequence — see §3.3).
- `movi20s`: the immediate is `imm << 8`; validate that the low 8 bits are zero
  *or* document that they are dropped (match SH-2A `gas` behavior exactly).
- `movmu`/`movml`: the base must be literally `@-r15` / `@r15+`; reject other
  base registers (these forms are stack-only by definition).
- Forbid `movi20`/`movi20s` in a delay slot (assembler diagnostic), mirroring
  the hardware illegal-slot rule ([`hardware-impl.md`](hardware-impl.md) §4.5).

### 2.3 Target gating

Expose via a J-core ISA flag, e.g. `-m32-density` (or fold into an existing
`-mj32` variant). The flag must match the GCC `-m` option (§3) and the core
build config `J32_DENSITY` ([`hardware-impl.md`](hardware-impl.md) §9), so that
"assembled with density" ⇒ "runs on a density-enabled core."

### 2.4 Disassembler

`objdump` must decode the new opcodes (again, SH-2A support exists; enable for
the J32 target). Critically, the disassembler must render `movi20` as a single
4-byte instruction, not two bogus 2-byte instructions — important for the
density-measurement tooling (§7), which parses disassembly.

---

## 3. Compiler (GCC SuperH backend)

### 3.1 `movi20` for constant materialization

Today, constants that exceed the 8-bit `mov #imm,Rn` go to a PC-relative literal
pool. With `movi20`:

- Add a constant-materialization path: a 32-bit constant `c` that fits the
  20-bit signed range → `movi20 #c,Rn`; one that fits `movi20s` (low byte zero,
  value in [27:8]) → `movi20s`. Otherwise fall back to the literal pool (or
  `movi20s` + `add`/`or` for the residue — evaluate whether the 2-instruction
  sequence beats a pool entry).
- **Critical optimization nuance (measured):** `movi20` is only a win for
  **singleton** constants. For constants that appear ≥2 times, the shared
  literal pool (one 4-byte word + N×2-byte loads) beats N×4-byte `movi20`s.
  The backend must therefore prefer `movi20` *only* when the constant is not
  pool-shared (or when pooling would cost a pool-range branch). Concretely:
  keep the constant pool machinery; route a constant to `movi20` when its
  use-count is 1 and it fits the immediate range. Getting this wrong in either
  direction loses most of the benefit — see §7.

### 3.2 `movmu`/`movml` for prologue/epilogue

This is where the regalloc interaction matters:

- Emit `movmu.l r8,@-r15` in the prologue / `movmu.l @r15+,r8` in the epilogue
  for the standard callee-saved set (`r8..r14` + `PR`), replacing the run of
  `mov.l`/`sts.l`/`lds.l`.
- The instruction transfers a *contiguous* range ending at `r14`+`PR`. To
  exploit it fully the register allocator should **prefer allocating
  callee-saved registers as a contiguous high range** (use `r14, r13, …`
  downward) so a function that saves *k* registers maps onto
  `movmu r(15-k),@-r15`. Functions that save a non-contiguous subset either use
  a slightly larger range (save a few extra registers — usually still a net win)
  or fall back to individual `mov.l`s. This is the difference between the ~1.8%
  (as-is regalloc) and ~3.5% (regalloc-assisted) estimates in [`spec.md`](spec.md)
  §1.
- **Prior art to follow:** GCC already ships register save/restore *millicode*
  for PowerPC (`_savegpr*`/`_restgpr*`) and RISC-V (`-msave-restore`). The
  existing local analysis note
  `gcc-sh-monitor/docs/upstream-reports/sh-millicode-save-restore.md` measured
  the *software-only* millicode variant (helper functions, no new instruction)
  at ~2–3% on BusyBox+musl sh4. `movmu`/`movml` are the *hardware* version of the
  same idea and should meet or beat it without the call overhead.

### 3.3 Relaxation / range handling

- `movi20` immediates are fixed 20-bit; the assembler rejects overflow, so the
  compiler must range-check before selecting `movi20`. No linker relaxation of
  the immediate itself (unlike branch relaxation).
- Interaction with the constant pool: enabling `movi20` *reduces* pool
  population, which can *shorten* the distance to remaining pool entries and ease
  the SH `mov.l @(disp,PC)` ±range pressure — a secondary benefit, but verify it
  does not perturb pool placement heuristics.

### 3.4 Option plumbing

`-m32-density` (matching the assembler flag) enables both behaviors. Default
off until the core feature ships. Document that the resulting binaries require a
density-enabled core.

---

## 4. ABI considerations

- **No ABI break.** `movmu`/`movml` change *how* callee-saved registers are
  spilled, not *which* registers are callee-saved or the stack-frame layout. The
  saved-register order on the stack must match what the unwinder expects
  (§5).
- **Stack layout:** the push order (`PR` at the highest address, `r8` at the
  lowest for the standard set) is fixed by the instruction semantics
  ([`spec.md`](spec.md) §3.2). The compiler's CFI must describe this exact
  layout so a frame saved with `movmu` is unwindable identically to one saved
  with individual pushes.
- **Mixed objects:** a `movmu`-using object and a `mov.l`-run object interoperate
  freely — same stack discipline, same `r15` semantics. Only the spill
  *instruction* differs.

---

## 5. Debugger / unwinder

- **DWARF CFI:** the prologue that uses `movmu.l r8,@-r15` must emit CFI
  describing the saved location of each of `r8..r14` and `PR` — one
  `DW_CFA_offset` per register and the `r15` adjustment — exactly as if they had
  been pushed individually. The instruction is denser but the *unwind
  description is unchanged*. This is the main toolchain correctness item:
  CFI must not be skipped just because one instruction did the work of eight.
- **GDB:** must single-step over `movmu`/`movml` as atomic (in-order core is
  non-interruptible; OoO retires the uops together from the user's view).
  Stepping *into* the middle is not meaningful and need not be supported.
- **`movi20`:** appears as one 4-byte instruction; ensure the debugger's
  instruction-length logic for the J32 target knows the `0000 nnnn iiii 000x`
  forms are 4 bytes (otherwise breakpoints/stepping land mid-instruction). This
  is the software mirror of the hardware delay-slot/length concern.

---

## 6. Test plan (software side)

Complements the RTL/sim tests in [`hardware-impl.md`](hardware-impl.md) §8.

1. **Assembler round-trip:** assemble → disassemble → re-assemble each new form;
   bytes stable. Include range-error cases for `movi20`.
2. **GCC codegen tests:** small C functions exercising (a) large-constant
   materialization (singleton vs repeated — assert `movi20` only for
   singletons), (b) prologue/epilogue over 1..7 callee-saved registers (assert
   `movmu`/`movml` emitted with the right anchor), (c) leaf functions (assert
   *no* save/restore emitted).
3. **Execution tests:** run on the sim and FPGA; round-trip register save/restore
   preserves all GPRs, `PR`, and `r15`; `movi20`/`movi20s` produce the exact
   constants across the range.
4. **Unwind tests:** throw/catch or backtrace across a `movmu`-saved frame;
   assert correct unwinding and register recovery.
5. **Interop:** link a density-built object against a baseline object; run.

---

## 7. Measuring the win — RESULTS IN

The differential recompile has been **run** (2026-05-29). Method: two GCC 14.2
cross-compilers built from the same source — `--with-cpu=m2` and
`--with-cpu=m2a`, both `--with-endian=big` (SH-2A is big-endian only, matching
the J-core sh2eb target) — compiling the CSiBE corpus to objects at `-O2`
(`-c`, no link). 193 of 528 files cross-compile cleanly under both and are
compared apples-to-apples.

**Result: 925,184 → 911,352 bytes (`.text`+`.rodata`+`.data`) = −1.50%.**

**Attribution (objdump over every object):** `movi20` **11,290** uses under
`-m2a` (0 under `-m2`), `movi20s` 135, `movmu` **1**, `movml` **0**. The win is
almost entirely `movi20` (constant materialization). **Stock GCC barely emits
`movmu`/`movml`** — so the save/restore-multiple share is *latent* and requires
the backend work in §3.2 to realize; simply enabling `-m2a` does not capture it.

This is the empirical confirmation of [`spec.md`](spec.md) §1's prediction. The
1.5% is *below* the ~6–8% static upper bound, which is expected: the upper bound
assumes every idiom is replaced with full regalloc cooperation, whereas this is
what stock `-m2a` emits today, on a corpus (compilers/codecs/parsers) less
prologue-heavy than BusyBox, measured over `.text`+`.rodata`+`.data`. Full
method, per-file sizes, and caveats: `.density-analysis/sh2a-run/RESULTS.md`
(scripts `run.sh` + `csibe.sh` alongside).

Open follow-ups: (a) once §3.1's singleton-only `movi20` heuristic and §3.2's
`movmu`/`movml` prologue emission land, re-run to measure the *realized* gain
against the upper bound; (b) the gcc-sh-monitor dashboard (CSiBE -Os, CoreMark
`.text`, BusyBox badges) is the natural CI home for tracking it over time;
(c) a BusyBox `.text`-only number awaits a big-endian SH `ld` (Debian's sh4
binutils ship only little-endian SH emulations, which blocks the BusyBox
partial-link — CSiBE sidesteps this by never linking).

---

## 8. Sequencing of software work

A pragmatic order that front-loads the cheap, decisive checks:

1. **Decoder regeneration unblocked** (§1) — install Clojure flow *or* land the
   Go migration. Nothing else builds without this.
2. **binutils** mnemonics + disassembler (§2) — enables hand-written asm tests
   and the measurement tooling before any compiler work.
3. **Sim model** second-word fetch + semantics (§1) — lets software tests run
   without waiting for RTL.
4. **GCC `movmu`/`movml`** prologue/epilogue (§3.2) + CFI (§5) — the larger,
   lower-risk win; no regalloc-contiguity needed for the first ~1.8%.
5. **GCC regalloc-contiguity** pass (§3.2) — captures the remaining
   save/restore upside.
6. **GCC `movi20`** with the singleton heuristic (§3.1) — highest payoff but the
   most subtle (easy to regress); do it last, gated on the measurement harness
   (§7) so regressions are caught immediately.

This order means each step is independently testable and the measurement harness
(§7) exists before the subtle `movi20` heuristic is tuned.

## Document status

Proposed draft. All toolchain work gated on the decoder-regeneration decision
(§1) and the IP clearance gate ([`spec.md`](spec.md) §1.4 / §8.1). Estimates are
unconfirmed pending the §7 differential recompile.
