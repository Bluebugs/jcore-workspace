# J32 PC-relative address instruction: `lea @(disp,PC),Rn`

A single two-word instruction that computes the **address of a text-internal
code label into any register**, position-independently, with no GOT load and no
literal-pool word. It is the PC-relative completion of the `lea` family defined
in [`../isa-density/spec.md`](../isa-density/spec.md) §3.4: where
`lea @(disp,Rm),Rn` takes a GPR base and `mova @(disp,PC),R0` takes PC but is
hardwired to `R0`, this fills the empty cell — **PC base, any `Rn`**.

```
                 dest = R0 only            dest = any Rn
  base = PC      mova @(disp,PC),R0        lea @(disp,PC),Rn   ← THIS DOCUMENT
                 (SH-1, 1992; 16-bit)      (new; 32-bit)
  base = GPR     —                         lea @(disp,Rm),Rn   (isa-density §3.4)
```

---

> ## ⚠️ Gating: GCC co-development and a measured win precede commitment
>
> **This instruction is not committed to RTL or silicon.** Like the rest of the
> J32 density bundle ([`../isa-density/spec.md`](../isa-density/spec.md), same
> gate), it is gated on a **GCC co-development** step that makes the backend
> *actually emit* `lea @(disp,PC),Rn` (the code-only `-mfdpic` emission of
> §[software-impl.md](software-impl.md) §3), followed by a **measured `.text`
> gain** on a real FDPIC corpus, **before any hardware is built**. A
> collision-free encoding is necessary but not sufficient: stock GCC will not emit
> this form on its own (the recurring isa-density lesson — only `movi20` is
> emitted unprompted), so its win is **latent** until the backend pass exists. The
> deliverable that justifies committing it is **(1) the GCC patch + (2) a measured
> win** clearing a threshold — not this encoding analysis alone.

---

## 0. Document Map

| Document | Contents |
|---|---|
| **spec.md** (this file) | Architecture: motivation, the lea/mova matrix, encoding, operation, design decisions, the disp20-impossibility finding, compatibility proof, verification. |
| [hardware-impl.md](hardware-impl.md) | RTL: how it reuses the `movi20`/`lea` second-word fetch and the `mova` PC-adder; in-order and OoO. |
| [software-impl.md](software-impl.md) | Toolchain: assembler mnemonic, the `R_SH_PCREL16_CODE` relocation, GCC codegen under `-mfdpic`. |

Related: [`../isa-density/spec.md`](../isa-density/spec.md) (the `lea`/`movi20`
work this builds on), [`../ooo/j32ooo-spec.md`](../ooo/j32ooo-spec.md).

---

## 1. Motivation and Goals

### 1.1 The gap

SuperH has exactly one PC-relative address-compute instruction, `mova
@(disp,PC),R0` (SH-1, 1992). It is doubly constrained:

- **destination is hardwired to `R0`** — any other target costs a following
  `mov R0,Rn`, and clobbers `R0` (the ABI return / first-arg register and the
  implicit operand of many SH instructions);
- **displacement is `disp8`, ×4-scaled, `PC & ~3`-masked, unsigned** — reach is
  +1020 bytes *forward only*, and the ×4 masking means it can only name
  4-aligned addresses (fine for the 4-byte literal pools it was designed for,
  useless for arbitrary code labels — see §4.1).

The `isa-density` work adds `lea @(disp,Rm),Rn`, which generalises the
*destination* (any `Rn`) and the *base* (any GPR `Rm`) — but **PC is not a GPR**
on SuperH; no `mmmm` field can select it. So the one base that the most common
position-independent idiom needs — the program counter — is exactly the one
`lea` cannot reach. This instruction supplies it.

### 1.2 Why PC-relative, and why code-only (the FDPIC constraint)

J-core Linux uses **FDPIC**, in which the text and data segments are relocated
**independently** at load time — there is *no* fixed text↔data offset. The
consequences are sharp and they define this instruction's domain:

- **PC-relative addressing of *data* is invalid under FDPIC.** Data is reached
  GOT-relative, through `r12` — that is what `lea @(gotoff,r12),Rn`
  (isa-density §3.4) and the GOT-slot load (§3.4.1) are for. This instruction
  does **not** address data and must not be used to.
- **PC-relative addressing of *code* is valid and natural under FDPIC**, because
  the text segment is internally contiguous: the distance from an instruction to
  any label in the same text segment is a link-time constant, independent of
  where the segment is loaded. This is the one place PC-relative survives FDPIC,
  and it is precisely where a literal-pool word or a GOT round-trip is pure
  overhead today.

Target idioms (all text-internal, all FDPIC-safe):

| Idiom | Today | With `lea @(disp,PC),Rn` |
|---|---|---|
| `&local_function` (entry half of a function descriptor) | `mova .L,r0` + `mov.l .L,rN` + pool word, or GOT round-trip | one instruction, any `Rn`, no `R0` clobber, no pool word |
| switch / jump-table base of code targets | `mova` (R0) + arithmetic | `lea @(table,PC),Rn` directly into the index register |
| computed-`goto` label address (`&&label`) | `mova`+`mov`+pool | one instruction |
| exception landing-pad / `__builtin_return_address`-style code pointers | pool word | one instruction |

### 1.3 Goals

- **G1** — Materialise a text-internal code address into **any** `Rn` in one
  instruction, position-independently, with no `R0` clobber and no literal-pool
  word (removes both the 2-byte pc-rel load *and* its 4-byte pool entry from the
  I-cache stream).
- **G2** — **Signed**, useful reach in both directions (backward refs: loop
  tops, earlier functions). Target **±64 KB**, which covers essentially all
  text-internal code-label distances (§4.2).
- **G3** — **ABI-neutral and globally collision-free**: one encoding that is
  illegal/reserved on SH-2, SH-2A, SH-4/SH-4A, the DSP encodings, and the
  current J32 decoder — verified, not assumed (§6).
- **G4** — **Near-zero marginal hardware**: reuse the `movi20`/`lea` second-word
  fetch and the existing `mova` PC+disp adder; add no new sequencer, no new
  architectural register, no new exception (§ [hardware-impl.md](hardware-impl.md)).

### 1.4 Non-Goals

- **Not** a data-addressing instruction. PC-relative data is invalid under
  FDPIC (§1.2); use `lea @(disp,r12),Rn` / the GOT-slot load.
- **Not** a wide-immediate loader. Absolute constants are `movi20`'s job
  (isa-density §3.1); this produces a *relocated address*, not an immediate.
- **Not** a branch. Control transfer to a PC-relative target is `bra`/`bsr`
  (±4 KB) or `braf`/`bsrf` (register). This computes an address into a register;
  the call/jump is a separate instruction (or feeds a function descriptor).

### 1.5 Provenance and IP

The PC-relative address-compute *concept* has unimpeachable, pre-everything
prior art: SuperH's own `MOVA @(disp,PC),R0` shipped in **SH-1 (1992)**. This
instruction is that operation with a wider signed displacement and a free
destination register — no new *idea*, only a new encoding. The encoding itself
is **new to J-core** (it occupies an unallocated minor in the SH-2A disp12
group, §3.2), so it carries no SH-2A-era encoding question; the second-word
fetch it relies on is the same one `movi20`/`lea` already introduce
(isa-density §1.4 provenance applies unchanged). PC-relative-to-`R0` (`MOVA`)
and the sign-extended byte-granular address arithmetic (`LEA`, isa-density §4.6)
are both decades old; their combination here adds no fresh claim.

---

## 2. Background: what this reuses

This instruction is deliberately **almost entirely reuse**. The two mechanisms
it needs already exist or are already being built:

1. **The 32-bit (two-word) front-end** — the second-word fetch that `movi20`
   and `lea` require. J-core's front-end is strictly 16-bit today
   (isa-density §2: "No instruction in the ISA fetches a second word"); the
   `movi20` work adds the second-word fetch path, paid once. This instruction
   adds no further front-end change — it is a fourth consumer of the same gate.
2. **The `mova` PC+displacement adder** — `mova @(disp,PC),R0` already routes a
   PC value and a scaled displacement into the address adder. This instruction
   uses that adder with (a) a wider displacement assembled across two words
   (exactly as `movi20` assembles its immediate) and (b) an arbitrary `Rn`
   write port (exactly as `lea`).

So architecturally this is **`movi20`'s displacement assembly + `mova`'s PC-add
+ `lea`'s any-`Rn` writeback**, with no new structural element. The microcode
fits the front-end's `+1`-only sequencer in two linear steps (no loop, no
counter), like `movi20` (isa-density §2; [hardware-impl.md](hardware-impl.md) §3).

---

## 3. Instruction Definition (architectural)

### 3.1 Encoding

| Mnemonic | Encoding (word0 word1) | Operation |
|---|---|---|
| `lea @(disp,PC),Rn` | `0011 nnnn DDDD 0001`  `1011 dddddddddddd` | `(PC_word0 + 4) + sign_extend₁₆(DDDD:dddddddddddd) × 2 → Rn` |

- It lives in the **SH-2A disp12 group** whose 16-bit prefix is
  `0011nnnnmmmm0001` — the same group as `lea @(disp,Rm),Rn` and the disp12
  load/store family (isa-density §3.4). Instructions in this group are
  distinguished by the **word1 minor** (bits [15:12]). SH-2A allocates minors
  `0000`–`1001` (the disp12 integer loads/stores plus the `fmov.s`/`fmov.d` FP
  loads/stores at minors `0011`/`0111`); `lea` (isa-density) takes `1010`;
  **this instruction takes `1011`** (verified unallocated everywhere, §6).
- Because the base is **PC (implicit)**, the word0 base field `mmmm` is dead —
  it is **reclaimed as the high nibble `DDDD` of a 16-bit displacement**. The
  full displacement is `disp16 = (DDDD << 12) | word1[11:0]`, sign-extended.
- **`Rn`** = word0 bits [11:8], any GPR.

### 3.2 Operation (pseudocode)

```c
void LEA_PCREL(int n, int D /* word0[7:4] */, int d /* word1[11:0] */)
{
    /* PC here == address of word0, per SH convention (+4 below). */
    int disp16 = (D << 12) | (d & 0xFFF);                 /* 16-bit field   */
    long sdisp = (disp16 & 0x8000) ? (disp16 | ~0xFFFF)   /* sign-extend    */
                                   :  disp16;
    R[n] = (PC + 4) + (sdisp << 1);                       /* ×2, code-aligned */
    /* no memory access; T and all flags unchanged */
    PC += 4;                                               /* two-word insn  */
}
```

- **Reference point.** `PC + 4`. The instruction occupies `[word0 .. word0+3]`,
  so `PC + 4` is the address of the *following* instruction. The linker computes
  the field as `disp16 = (target − (word0 + 4)) / 2`; both operands are even, so
  the division is exact and the low bit is never lost.
- **No memory access, no flags.** It is pure address arithmetic into a register
  — the same exception/flag profile as `lea`/`mova`.
- **Reach.** `sdisp ∈ [−32768, +32767]`, ×2 ⇒ `Rn − (PC+4) ∈ [−65536, +65534]`
  bytes = **±64 KB**.

### 3.3 The 2×2 it completes

`mova` (PC/R0), `lea @(disp,Rm),Rn` (GPR/anyRn), and this (PC/anyRn) span three
of the four base×destination cells; the fourth (GPR base, R0 dest) is a
degenerate special case of `lea` and needs nothing. A reader who knows `lea`
needs no new mental model: it is `lea` with `PC` written where a base register
would go, and the assembler selects this encoding precisely because the `PC`
token cannot denote a GPR.

---

## 4. Design Decisions

### 4.1 `×2` scaled, `PC`-unmasked — because the target is *code* (decided 2026-05-31)

SH's existing PC-relative ops scale by the **target's** size: `mov.w @(disp,PC)`
is ×2, `mov.l @(disp,PC)` and `mova` are ×4 **and** mask `PC & ~3`. The ×4/mask
pair is correct for those because they target **longword literal data**
(4-aligned pool entries). This instruction targets a **code label**, and on
SuperH **all instructions are 16-bit, hence only 2-byte aligned** — a code
target may sit at any address ≡ 0 *or* 2 (mod 4).

Therefore:

- **×4 is wrong here.** A ×4 scale (or a `PC & ~3` mask) can only name 4-aligned
  addresses and would make **half of all instruction addresses unreachable** —
  any switch case, computed-goto label, or function entry at a 2-mod-4 offset.
- **×2 is exact and free.** Code targets are always even, so the displacement is
  always even; scaling by 2 wastes no bit and doubles reach versus unscaled.
  **No `PC & ~3` masking** — the result is naturally 2-aligned, which is correct
  for a code address.

This is the code-specific counterpart to `lea`'s "unscaled, because no operand
size to scale by" decision (isa-density §4.6). *Considered and rejected:* a
×4-scaled form constraining targets to 4-aligned (reach ±128 KB). It would
require `-falign-functions=4`-style alignment on *every* referenced label
including interior switch/goto labels — not guaranteed by the ABI, and a
correctness hazard if violated. ×2 is the safe default; the ×4 variant is noted
only as a future option for corpora that can guarantee 4-aligned targets (§8).

### 4.2 `disp16` / ±64 KB is the chosen reach — and why not `disp20`

The goal was originally to mirror `movi20`'s 20-bit field (±1 MB). **A disp20
PC-relative form has no globally collision-free encoding — proven, not
assumed.** A 20-bit displacement needs four free immediate bits in word0, i.e. a
fully-free 16-value "nibble-plane" `hhhh nnnn iiii ssss`. A sweep of
`docs/insns.json` over **every** SuperH variant shows:

- The **only two** fully-free nibble-planes in the entire 16-bit map are
  `0000nnnniiii0000` and `…0001` — **already occupied by SH-2A's own
  `movi20`/`movi20s`.**
- The only other disp20-shaped holes alias **`cas.l`** (SH-4A compare-and-swap,
  at `0010nnnnmmmm0011` — **which J-core implements for SMP**) or the **DSP**
  `p*`/`movx`/`movy` encodings (`1111…`). Both are unacceptable.

So disp20 cannot be both wide *and* a good ISA citizen. **disp16** sidesteps the
entire problem: with the displacement carried in word1 (plus the reclaimed
`DDDD` nibble) and a **fixed** word1 minor, no free nibble-plane is needed — only
one unallocated minor in the disp12 group, which exists (`1011`, §6). ±64 KB
(×2) comfortably covers text-internal code-label distances: a single
PC-relative reference spans at most the distance to a label in the same function
or a nearby one, far under 64 KB even in large binaries (BusyBox's ~268 KB
`.text` has essentially no intra-reference exceeding it). For the rare overflow
the assembler relaxes to `mova`+pool or a `movi20`+`add` sequence
([software-impl.md](software-impl.md) §3.3).

### 4.3 Reclaiming the base field as displacement (decided 2026-05-31)

In the disp12 group, word0 `mmmm` is the base register. With base = PC it is
dead; rather than leave it zero (which would yield only `disp12`, ±4 KB after
×2), it becomes `disp[15:12]`. This is a clean, local decode special-case: when
the word1 minor is `1011`, the decoder does **not** read `mmmm` as a base — it
takes PC as base and `mmmm` as displacement high bits. The cost is one extra
mux select keyed on the (already-decoded) minor; the gain is +4 displacement
bits = ×16 reach (±4 KB → ±64 KB).

### 4.4 Signed displacement

Like `lea`, the field is **signed** (two's complement). Backward references are
common for code labels — loop tops, earlier-defined functions, switch tables
emitted before their use. An unsigned-forward-only field (as `mova` has) would
halve the useful population for no benefit.

### 4.5 Mnemonic: overload `lea`, disambiguated by the `PC` token

The assembler mnemonic is `lea @(disp,PC),Rn` — the same `lea` as the
register-base form, because `PC` is a reserved token that **cannot** denote a
GPR, so the two forms never collide syntactically. This makes the family
self-documenting: `lea @(disp,r12),Rn` (GOTOFF data) and `lea @(disp,PC),Rn`
(text-internal code) read as the two halves of one address-arithmetic
instruction, base = data-pointer vs base = program-counter. (An internal opcode
name `LEA_PCREL` distinguishes them in the decoder/sim.)

---

## 5. Exceptions and Corner Cases

- **Illegal in a delay slot.** Like every two-word instruction (`movi20`,
  `lea`), it must raise an illegal-instruction (slot-illegal) exception if it
  appears in the delay slot of a delayed branch — the second-word fetch cannot
  be sequenced there. Decode-side guard, identical to `movi20`'s
  ([hardware-impl.md](hardware-impl.md) §3; isa-density hardware-impl §4.5).
- **No address-error / data-access exception.** It performs no memory access;
  the computed value is written to `Rn` regardless of whether it points at
  mapped memory. (Dereferencing it later is the consumer's concern.)
- **`T` and flags unchanged.** Pure register write.
- **`Rn = R0` is legal** and is the common `mova`-superset case (one
  instruction instead of `mova`+nothing) — but with ×2/signed/wider reach.
- **FDPIC validity is a software contract, not a hardware check.** The hardware
  computes `PC+4+disp×2` unconditionally; it is the compiler/assembler's
  responsibility to emit it only for text-internal targets (§1.2). Using it for
  a data address would compute a wrong (load-time-variant) pointer — a codegen
  bug, not a trap. [software-impl.md](software-impl.md) §3 constrains emission to
  code labels.
- **Interaction with `mova`.** Both remain legal; `mova` stays the 2-byte choice
  when the target is a 4-aligned literal within +1020 forward and `R0` is free.
  The compiler picks the smaller encoding that reaches ([software-impl.md](software-impl.md) §3.3).

---

## 6. Compatibility — collision-free proof

Methodology: parse every instruction's `code` in `docs/insns.json` into a
`(mask, value)` over the first word (and, for two-word ops in this group, the
word1 minor), treat operand letters as don't-care, and test the candidate for
*any* common bit pattern against **every** variant present
(`SH1, SH2, SH2E, SH3, SH3E, SH4, SH4A, SH2A, DSP, J32`) — not merely SH-2/-2A/-4.

Result for `0011 nnnn DDDD 0001` + word1 minor `1011`:

- **Word0 prefix `0011nnnnmmmm0001`** is the SH-2A disp12 escape; on SH-2 and
  SH-4 it is a **reserved** slot (group 3 defines `…0000` `cmp/eq`, `…0010`
  `cmp/hs`, … — `…0001` is unallocated). It carries no instruction on any
  non-2A variant.
- **Word1 minor `1011`** is **unallocated in the disp12 group on every variant**:
  SH-2A uses `0000`–`1001` (integer + `fmov.s`/`fmov.d` disp12 loads/stores);
  `lea` (isa-density) claims `1010`; `1011`–`1111` are free. (Sweep output: group
  minors used = `0000…1001`; free = `1010,1011,1100,1101,1110,1111`.)
- Therefore the full two-word encoding collides with **nothing** on SH-2,
  SH-2A, SH-4/SH-4A, the DSP set, or the current J32 decoder.

Contrast — what was **rejected** for collision reasons (the disp20 search,
§4.2): the group-2 gap `0010nnnniiii0011` aliases **`cas.l`** (J32-present); the
FPU group `1111nnnniiii1111` is buried under the **DSP** `p*`/`movx`/`movy`
encodings. The disp16 choice is what makes a clean slot possible.

This instruction is `J32`-only: it does not change the behaviour of any existing
SH binary, and SH-2/-2A/-4 code never emits it.

---

## 7. Verification Strategy (architectural)

1. **Decoder differential (cheapest, mandatory).** Regenerate the decoder with
   the new row and diff the decode tables against baseline: the *only* changed
   entries must be the previously-reserved `0011nnnnmmmm0001`/minor-`1011`
   points. Any other delta means a collision was missed (isa-density
   hardware-impl §8.1).
2. **Encoding-sweep regression.** Add `0011nnnnDDDD0001 1011…` to the
   `docs/insns.json` collision sweep as a committed test, so future additions
   can't silently re-use the minor.
3. **Operation unit tests.** For representative `(Rn, disp16, word0_addr)`:
   assert `Rn == (word0_addr + 4) + sign_ext16(disp)×2`; cover max forward
   (`+0x7FFF`), max backward (`−0x8000`), zero, and the sign boundary; assert
   `T` and other GPRs unchanged.
4. **Linker/relocation round-trip.** Assemble `lea @(L,PC),Rn`; check the
   relocation resolves to `(L − (insn+4))/2` and that an out-of-range `L`
   triggers the assembler's relax/fallback ([software-impl.md](software-impl.md) §3.3).
5. **Delay-slot guard.** Assert slot-illegal when placed in a delay slot.
6. **Sim ↔ RTL parity** and **FPGA smoke**, per isa-density hardware-impl §8.4–§8.6.

---

## 8. Open Questions

- **Q1 — ×4-scaled 4-aligned variant?** A ×4 form (±128 KB) is sound *iff* every
  referenced code label is 4-aligned. Worth it only with a codegen pass that
  forces such alignment and a corpus showing >64 KB intra-text references exist.
  Default stays ×2 (§4.1).
- **Q2 — Should the disp12 *loads/stores* of this group also be adopted for the
  GOT path?** Orthogonal; tracked in isa-density §3.4.1. This instruction only
  claims minor `1011`.
- **Q3 — GCC emission heuristics.** When does the backend prefer
  `lea @(disp,PC),Rn` over `mova`+`mov` over a GOT round-trip? Sketched in
  [software-impl.md](software-impl.md) §3; needs a measured pass like the
  isa-density CSiBE run.
- **Q4 — A 16-bit short form?** Analogous to ARM `ADR` vs `ADRP`. The 16-bit
  space has no free `nnnn`-bearing slot with useful PC-relative reach (the same
  wall `lea` hit, isa-density §4.7); deferred unless a measured near-reference
  population justifies hunting one.

---

## Document status

Draft, 2026-05-31. Architecture defined; encoding (`0011nnnnDDDD0001` / minor
`1011`) verified collision-free against all SuperH variants in
`docs/insns.json`. Hardware and software implementations sketched in the
companion documents as deltas over the `isa-density` `movi20`/`lea` work, which
must land first (shared second-word fetch). Density impact is **not** yet
measured — it depends on GCC actually emitting the form (latent, like every
non-`movi20` instruction in isa-density); a CSiBE/BusyBox-FDPIC measurement is
the natural follow-up.
