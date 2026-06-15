# Software Implementation: `lea @(disp,PC),Rn`

Toolchain support for the instruction defined in [spec.md](spec.md). Written as
a delta over [`../isa-density/software-impl.md`](../isa-density/software-impl.md),
which it shares the second-word-fetch decoder regeneration, `gas` plumbing, and
GCC option machinery with.

## 1. Prerequisite

Decoder regeneration and the sim model, exactly as isa-density software-impl §1
(the generator pipeline — edit the TOML spec and regenerate via
`make -C decode generate`, Go 1.26+ only; do not hand-edit generated VHDL). The
new decode row is the spec §3.1 encoding.

## 2. Assembler (binutils `gas`)

### 2.1 Mnemonic

Overload `lea`, disambiguated by the `PC` token (spec §4.5):

```
lea  @(disp,PC),Rn      ; PC token ⇒ this 32-bit PC-relative encoding
lea  @(disp,Rm),Rn      ; GPR base ⇒ the isa-density §3.4 register-base encoding
```

`disp` is a **byte** displacement in the source (assembler/linker scale by 2);
the operand is normally a **label**, with the assembler emitting a relocation
rather than a literal `disp` (a literal is accepted for hand-written asm and
range-checked). The `PC` keyword cannot name a GPR, so there is no grammar
ambiguity with the register-base form.

### 2.2 Encoding/assembly rules

For `lea @(L,PC),Rn` at instruction address `A` (word0 at `A`):

```
field disp16 = (L - (A + 4)) / 2        ; signed, must be even before /2 (always true for code)
word0 = 0011 | Rn(4) | disp16[15:12] | 0001
word1 = 1011 | disp16[11:0]
```

- Range check: `L - (A+4) ∈ [−65536, +65534]` and even. Even-ness holds for any
  code label (2-aligned); a `.byte`-misaligned target is a user error → assembler
  diagnostic.
- The `disp16[15:12]` nibble lands in the **word0 `mmmm` field** (spec §4.3).

### 2.3 Relocation

A new PC-relative, ×2-scaled, split-field relocation — call it
`R_SH_PCREL16_CODE`:

- **Computation**: `(S + A_addend − P) / 2`, where `P` = address of word0,
  `S` = symbol, with the `−(P+4)` reference adjusted via a `−4` addend (or the
  backend's standard `pcrel` bias) so the effective reference is `P+4`
  (spec §3.2). Result is split: high nibble → word0[7:4], low 12 bits →
  word1[11:0].
- **Overflow**: out of `[−0x8000, +0x7FFF]` (post-scale) ⇒ relocation error,
  unless relaxation (§3.3) has already rewritten the site.
- **Disassembler**: print `lea @(<disp>,PC),Rn`, reconstructing
  `disp = sext16((word0[7:4]<<12)|word1[11:0]) << 1` and, where symbols are
  available, the resolved label.

### 2.4 Target gating

Enabled under the same `-m`/`.isa` gate as the rest of the J32 density bundle
(isa-density software-impl §2.3). It is a J32 extension; stock SH-2/-2A/-4
assembly never selects it.

## 3. Compiler (GCC SuperH backend)

### 3.1 When to emit it

`lea @(disp,PC),Rn` is the **position-independent materialisation of a
text-internal code address**. Under `-mfdpic` it replaces, for any **code**
symbol/label provably in the same text segment:

| Source construct | Replaced sequence | New |
|---|---|---|
| `&local_static_function` (descriptor entry word) | `mov.l .L,r0; mova .L,…` / GOT funcdesc round-trip | `lea @(func,PC),Rn` |
| `goto *&&label;` (computed goto) address-of-label | `mova .L,r0; mov r0,rN` + pool | `lea @(label,PC),Rn` |
| jump/switch table **of code addresses** | `mova table,r0` (+R0 arithmetic) | `lea @(table,PC),Rn` then indexed load/branch |
| internally-referenced code pointer (landing pad, etc.) | pool word + pc-rel load | `lea @(target,PC),Rn` |

**Hard constraint (spec §1.2):** emit **only** for targets the compiler can
prove are in the same text segment as the referencing instruction. Never for
data symbols — PC-relative *data* is invalid under FDPIC; those stay
GOT/`r12`-relative (`lea @(gotoff,r12),Rn`, isa-density §3.5). A reasonable
guard: restrict to `SYMBOL_REF`s with `SYMBOL_FLAG_FUNCTION`/local-label, in the
same comdat/section, under `-mfdpic`.

### 3.2 Relationship to `movi20` and `lea @(disp,Rm),Rn`

Three complementary materialisations; the backend picks by symbol kind:

| Want | Instruction |
|---|---|
| absolute constant / immediate | `movi20` (isa-density §3.1) |
| GOTOFF data address (`&data`, PIC) | `lea @(gotoff,r12),Rn` (isa-density §3.4) |
| GOT-slot fetch (`&extern`, PIC) | `mov.l @(slot,r12),Rn` (isa-density §3.4.1) |
| **text-internal code address (PIC)** | **`lea @(disp,PC),Rn`** (this doc) |

### 3.3 Relaxation / range handling

±64 KB covers essentially all intra-text code references (spec §4.2). For the
rare out-of-range case the backend/linker relaxes the site to a longer sequence:

1. preferred fallback: `mova`+`mov` only if the target is 4-aligned and within
   `mova`'s +1020 forward window (rare to help);
2. general fallback: `movi20`/constant-pool materialisation of the
   text-internal offset + `add pc-derived-base` — i.e. the pre-existing pattern.

The assembler must range-check at emit and either error (hand asm) or signal the
linker-relaxation path (compiler-generated, marked relaxable).

### 3.4 Option plumbing

No new user option; rides the J32 density `-m` switch (isa-density
software-impl §3.4). Costing in the backend: treat as a 2-word (4-byte),
single-cycle (in-order) / 1-uop (OoO) op — cheaper than the `mova`+`mov`+pool it
replaces (which is 4 bytes of insns **plus** a 4-byte pool word and an `R0`
clobber).

## 4. ABI considerations

- **No ABI change.** The instruction computes a value into a caller-chosen
  register; it does not alter the FDPIC calling convention, the funcdesc layout,
  or `r12` usage. It is purely a cheaper way to obtain a text-internal code
  address that the ABI already permits computing.
- **Unwinder / debugger**: a new opcode to disassemble (§2.3); it defines no CFI
  and touches no unwind state (no memory, no SP/FP). Debug info is unaffected
  beyond instruction decoding.

## 5. Test plan (software side)

- **gas**: assemble forward/backward/zero/extremes; check field split and
  relocation; assert even-ness and range diagnostics; round-trip via the
  disassembler.
- **ld**: relocation resolves to `(S − (P+4))/2`; out-of-range triggers
  relax/error.
- **gcc**: codegen tests for computed-goto, local-function address, switch
  tables under `-mfdpic`; verify **no** data symbol is ever emitted via this
  insn (negative test); verify GOTOFF data still uses `lea @(…,r12),…`.
- **Measurement** (deferred, like isa-density §7): once GCC emits it, measure
  `.text` delta on an FDPIC corpus (BusyBox-sh2eb-fdpic, CSiBE-fdpic). Expect
  the realised win to be **latent** until the backend pass exists — stock GCC
  will not emit it merely by enabling the encoding (the recurring isa-density
  lesson).

## Document status

Draft, 2026-05-31. Toolchain work specified as a delta over the isa-density
`movi20`/`lea` plumbing it shares. Density impact unmeasured pending GCC
emission; the `R_SH_PCREL16_CODE` relocation and the code-only emission guard
are the two pieces with no isa-density precedent.
