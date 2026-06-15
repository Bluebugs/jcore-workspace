# Software Implementation: `movi20`, `movmu`/`movml`, `lea`, and the delay-slot-free branches

**Status:** Draft / Proposed
**Companion to:** [`spec.md`](spec.md) (architecture), [`hardware-impl.md`](hardware-impl.md) (RTL)
**Scope:** toolchain (binutils, GCC), ABI, simulator, debugger, and the
measurement plan that confirms the code-density win.

---

## 1. Prerequisite: decoder regeneration & the sim model

The CPU decoder and the C simulator model are **generated** by the Go generator
`jcore-cpu/decode/gen-go/` (`cmd/cpugen`) from hand-editable per-category **TOML**
under `decode/gen-go/spec/*.toml`. Regenerate with `make -C decode generate`
(needs **Go 1.26+** only). The legacy Clojure tool + `SH-2 Instruction Set.ods`
are archived under `decode/gen-clj-archive/` (reference only). One fact shapes
all software work:

1. **Adding an instruction = editing TOML + regenerating** (git-diffable, no JVM).
   New SH-2A/SH-4 opcodes get a `[[instr]]` row (opcode bit-pattern + ordered
   `[[instr.slots]]` microcode steps); there is a reserved `spec/sh4/` subtree for
   SH-4/priv-arch additions. `decode/gen-go/regression.sh` runs the end-to-end
   check (generator tests + simulator + TAP).

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
lea      @(disp,Rm), Rn  ; 0011 nnnn mmmm 0001  1010 dddddddddddd   (NEW; not SH-2A)
mov.l    @(disp12,Rm),Rn ; 0011 nnnn mmmm 0001  0110 dddddddddddd   (SH-2A; GOT-slot load)
jsr/n    @Rm             ; 0100 mmmm 0100 1011                     (SH-2A; no delay slot)
rts/n                    ; 0000 0000 0110 1011                     (SH-2A; no delay slot)
rtv/n    Rm              ; 0000 mmmm 0111 1011                     (SH-2A; Rm→R0 + return)
```

`movi20`/`movi20s`/`movmu`/`movml`, the disp12 `mov.l`, and
`jsr/n`/`rts/n`/`rtv/n` are already known to `gas` under `-isa=sh2a`; the work is
enabling them on the J32 target. **`lea` is a new mnemonic** — `gas` has no SH-2A
`lea`, so it needs a fresh opcode-table entry (`0011nnnnmmmm0001`/word1-minor
`1010`, signed unscaled 12-bit `disp`, range −2048..+2047).

### 2.2 Encoding/assembly rules

- `movi20`: emit two 16-bit words (big-endian to match J-core). Operand range
  check: `−524288 ≤ imm ≤ 524287`; out-of-range is an assembler error (the
  compiler/relaxation must pick a different sequence — see §3.3).
- `movi20s`: the immediate is `imm << 8`; validate that the low 8 bits are zero
  *or* document that they are dropped (match SH-2A `gas` behavior exactly).
- `movmu`/`movml`: the base must be literally `@-r15` / `@r15+`; reject other
  base registers (these forms are stack-only by definition).
- `lea`: `disp` is a **signed, unscaled** 12-bit displacement;
  `−2048 ≤ disp ≤ 2047`, out-of-range is an assembler error (the compiler picks
  a different sequence — §3.5). `Rm` is any GPR. Accept a relocation operand
  (`R_SH_GOTOFF`/`R_SH_GOTOFF12` — see §3.5) in the `disp` position for PIC.
  The disp12 `mov.l` (GOT-slot load) takes an **unsigned ×4-scaled** 12-bit
  displacement (`0 ≤ disp ≤ 16380`, longword-aligned) — note the *different*
  displacement semantics from `lea`, matching the hardware ([`spec.md`](spec.md)
  §3.4 / §4.6); the assembler must not share one disp parser between them.
- Forbid `movi20`/`movi20s`/`lea`/disp12 forms in a delay slot (assembler
  diagnostic), mirroring the hardware illegal-slot rule
  ([`hardware-impl.md`](hardware-impl.md) §4.5) — all are 32-bit.
- `jsr/n`/`rts/n`/`rtv/n`: 16-bit, and `gas` must mark them as **non-delayed**
  (no delay slot to fill or pad) — unlike `jsr`/`rts`. The branch-in-delay-slot
  diagnostic applies to them as to any branch. `rtv/n` takes one GPR operand
  (`Rm`); `rts/n` takes none.

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

### 3.5 `lea` and disp12 `mov.l` for PIC/GOT codegen

These help **only** position-independent code (`-fPIC`/`-fpic`), where `r12` is
the GOT pointer (`PIC_OFFSET_TABLE_REGNUM`). Two distinct patterns, two distinct
instructions:

- **GOTOFF (local symbol address)** — today `mov.l .Lgotoff,r0; add r12,r0`
  (a literal + an add, clobbering `R0`). With `lea`:

  ```
  lea  @(sym@GOTOFF, r12), rN        ; rN = &sym, one instruction, no R0, no literal
  ```

  Emit a `RELOC_SH_GOTOFF12` (new) fixup in the `lea` `disp` field. Because the
  field is **signed 12-bit, byte-granular** (±2048), this fires only when the
  symbol's GOT-relative offset fits; larger offsets fall back to the existing
  `movi20`/`add`/literal path (and would overflow any 12-bit form regardless —
  [`spec.md`](spec.md) §4.6). Small-data / hot-symbol layout near the GOT base
  maximises hits.

- **GOT-slot load (external/preemptible symbol address)** — today
  `mov.l .Lslot,r0; mov.l @(r0,r12),rN` (a literal + an indexed load via `R0`).
  With the adopted disp12 `mov.l`:

  ```
  mov.l @(sym@GOT, r12), rN          ; rN = &sym, one instruction, no R0, no literal
  ```

  Emit a `RELOC_SH_GOT12` (new) fixup; the field is **unsigned ×4 (4095 slots)**,
  so it covers essentially any GOT. Beyond that, fall back to the `R0` sequence.

Both replace a 2-instruction-plus-literal idiom with one 4-byte instruction and,
critically, **free `R0`** — which on SH is the implied index/operand for many
ops, so PIC prologues and GOT-heavy code see register-pressure relief beyond the
raw byte count. The GOT pointer register stays `r12` (no ABI change — these take
an explicit base; [`spec.md`](spec.md) §1.3).

**Prior art to follow:** the GOT-base + displacement addressing model is the
classic PIC idiom — MIPS `$gp`-relative `lw` (o32, ≤1995), PowerPC `r2` TOC,
x86 `EBX`-relative `lea`/`mov`, and SH's own `@(disp,GBR)` mode — all pre-2006
([`spec.md`](spec.md) §1.4 / [../glossary.md §2](../glossary.md)). The SH novelty
is only carrying it in a 32-bit SH-2A-format instruction.

### 3.6 `jsr/n`/`rts/n`/`rtv/n` — emitting the delay-slot-free forms

Stock GCC does not emit the `/N` forms (confirmed: every `rts` it produces has a
delay slot, padded with `nop` when unfillable). The realized win
([`spec.md`](spec.md) §3.5: ~0.8 % of instructions on CSiBE) needs a small
machine-specific pass:

- **Where:** run it **after `dbr_schedule`** (the delay-slot scheduler), so it
  only ever fires on the slots `dbr_schedule` *left as `NOP`* — i.e. the
  unfillable residue. Filling is `dbr_schedule`'s job (it already wins 80.6 % of
  indirect-call slots); this pass only mops up what it could not fill, and does
  so by *removing* the slot rather than filling it. (The `gcc-sh-monitor`
  `peephole-delay-slot-jsr-fill.md` negative result is exactly why we remove
  rather than try harder to fill.)
- **Rewrite rules:**
  - `jsr @Rm` + `nop` slot → `jsr/n @Rm` (drop the `nop`).
  - `rts` + `nop` slot → `rts/n` (drop the `nop`).
  - `mov Rm,r0` ; `rts` (+ slot) → `rtv/n Rm` — fold the return-value move into
    the return when the function's result is in `Rm ≠ r0` at the epilogue. (If the
    result is already in `r0`, plain `rts/n` suffices.)
- **Do *not* touch `bra`/`braf`/`jmp`** — there is no slot-free unconditional
  branch ([`spec.md`](spec.md) §4.8), so their `NOP`s stay. The pass covers only
  `jsr`/`rts`.
- **CFI / unwind:** `jsr/n`/`rts/n` change *where* the return address points (no
  slot skipped, §5) but not the frame; epilogue CFI is unaffected. `rtv/n`'s
  `R0 ← Rm` is a normal scratch write, no CFI.
- **Gating:** behind the same `-m32-density` flag (§2.3 / §3.4).

This is the most tractable of the density compiler tasks — a local
peephole/rewrite over already-scheduled code — and unlike the others needs no new
RTL capability beyond the decode mapping ([`hardware-impl.md`](hardware-impl.md)
§4A). Prior art for the optimization itself: choosing the non-delayed branch
encoding to avoid a wasted slot is standard for ISAs offering both (e.g. MIPS
non-`/likely` vs `/likely` branch selection), all pre-2006.

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
- **`lea` / disp12 `mov.l`:** likewise 4-byte (`0011 nnnn mmmm 0001` prefix);
  the same J32 instruction-length table entry must mark the whole group as 4
  bytes. `lea` needs no CFI (it writes a scratch GPR, touches no frame state);
  the disp12 `mov.l` is an ordinary load for debug purposes.
- **`jsr/n`/`rts/n`/`rtv/n`:** 2-byte, **no delay slot** — the debugger's
  control-flow model must know these transfer *without* executing a successor
  (unlike `jsr`/`rts`). Single-stepping over `jsr/n` lands in the callee; the
  return address (`PR`) is the *next* instruction (`call+2`), not `call+4` — GDB's
  SH frame/return logic must select the right offset per form or backtraces across
  a `/N` call frame are off by one instruction. `rtv/n` additionally sets `R0`
  before returning; stepping shows the value in `r0` after the step.

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
6. **PIC tests (`-fPIC`):** small shared objects exercising (a) a local-symbol
   address — assert `lea @(sym@GOTOFF,r12),rN` emitted, no `R0` clobber, no
   literal; (b) an external-symbol address — assert disp12
   `mov.l @(sym@GOT,r12),rN`; (c) range overflow — assert clean fallback to the
   `movi20`/literal path; (d) execute the `.so`, confirm correct symbol
   resolution against a dynamic linker. Assembler round-trip the
   `R_SH_GOT12`/`R_SH_GOTOFF12` relocations.
7. **Delay-slot-free tests:** (a) functions whose `jsr`/`rts` slots GCC leaves as
   `NOP` — assert the §3.6 pass emits `jsr/n`/`rts/n` and drops the `nop`;
   (b) a function returning a value computed in `Rm ≠ r0` — assert `rtv/n Rm`;
   (c) a function whose result is already in `r0` — assert plain `rts/n` (not
   `rtv/n`); (d) `bra`/`braf` NOP cases — assert they are **left unchanged** (no
   `bra/n`); (e) execution: call/return across `/N` lands correctly and the
   successor instruction is not skipped; (f) backtrace across a `jsr/n` frame
   unwinds with the correct return offset (§5).

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
partial-link — CSiBE sidesteps this by never linking);
(d) **`lea`/disp12 PIC measurement is not yet done.** The §7 recompile is
*non-PIC*, so it says nothing about `lea`. Quantifying it needs a separate
`-O2 -fPIC` differential recompile (baseline vs. `lea`+disp12-enabled GCC),
counting GOTOFF/GOT idioms replaced and the net `.text` delta on a
shared-library-shaped corpus (the GOT-heavy parts of CSiBE, or a `.so`-built
BusyBox). Until that runs, the `lea` benefit in [`spec.md`](spec.md) is
**qualitative only** — do not quote a percentage.

---

## 8. Sequencing of software work

A pragmatic order that front-loads the cheap, decisive checks:

1. **Decoder regeneration ready** (§1) — Go 1.26+ and `make -C decode generate`;
   edit the TOML spec, never the generated VHDL. Nothing else builds without this.
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
7. **`lea` + disp12 `mov.l` for PIC** (§3.5) — independent of the above and of
   each other's payoff; gated only on the new `gas` `lea` opcode entry (§2) and
   the `RELOC_SH_GOT12`/`GOTOFF12` relocations. Land the two relocations + GCC
   PIC patterns, then run the §7(d) `-fPIC` differential to confirm the win
   before quoting any number. Lower priority than 1–6 unless PIC/shared-library
   density is a near-term target.
8. **Delay-slot-free `/N` pass** (§3.6) — the most tractable compiler task and
   fully independent of 1–7: a post-`dbr_schedule` peephole, no new immediate
   forms or relocations, RTL cost is decode-only ([`hardware-impl.md`](hardware-impl.md)
   §4A). Good early win once binutils (step 2) knows the mnemonics; re-measure
   against the 0.80 %-of-instructions opportunity.

This order means each step is independently testable and the measurement harness
(§7) exists before the subtle `movi20` heuristic is tuned.

## Document status

Proposed draft. All toolchain work gated on the decoder-regeneration decision
(§1) and the IP clearance gate ([`spec.md`](spec.md) §1.4 / §8.1). Estimates are
unconfirmed pending the §7 differential recompile.
