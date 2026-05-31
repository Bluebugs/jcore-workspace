# J32 Code-Density ISA Extensions: `movi20`, `movmu`/`movml`, `lea`, and the delay-slot-free branches

**Status:** Draft / Proposed
**Target:** J32 (SH-2 ISA, 32-bit), both the in-order J2/J32 core and the J32-OoO core
**Audience:** CPU architects, RTL engineers, toolchain developers picking this up cold
**Companion docs:** [`hardware-impl.md`](hardware-impl.md), [`software-impl.md`](software-impl.md), [`sh2a-candidate-triage.md`](sh2a-candidate-triage.md) (the SH-2A instructions evaluated and *not* adopted, and why)
**Parent plan:** [`../ooo/j32ooo-spec.md`](../ooo/j32ooo-spec.md) §5 (Multi-Register Operations)

---

## 0. Document Map

This is the **architectural / design spec** for a set of code-density
instructions added to the J32 ISA. The first three are SH-2A-derived; `lea` is a
**new J-core encoding** placed in free SH-2A-family opcode space (it is *not* an
SH-2A instruction — see §1.4):

- `movi20` / `movi20s` — load a 20-bit immediate (32-bit instruction).
- `movmu.l` / `movml.l` — store-multiple / load-multiple of a contiguous
  register range against the stack (16-bit instructions).
- `lea` — compute a base-plus-displacement effective address into a register,
  with **no memory access** (32-bit instruction). Targets PIC/GOT code. Paired
  with *adoption* of the existing SH-2A `mov.l @(disp12,Rm),Rn` load for the
  GOT-slot-load half of the same idiom (§3.4).
- `jsr/n`, `rts/n`, `rtv/n` — **delay-slot-free** subroutine call and return
  (16-bit, SH-2A). They eliminate the `NOP` the scheduler is forced to emit when
  a `jsr`/`rts` delay slot cannot be filled (§3.5). The single SH-2A instruction
  beyond `movi20`/`lea` with a measured general-code payoff — see
  [`sh2a-candidate-triage.md`](sh2a-candidate-triage.md) for the full evaluation
  that promoted these and rejected the rest.

Microarchitecture is in [`hardware-impl.md`](hardware-impl.md); toolchain and ABI
in [`software-impl.md`](software-impl.md); the SH-2A instructions evaluated and
*not* adopted are in [`sh2a-candidate-triage.md`](sh2a-candidate-triage.md). This
file defines *what* the instructions are and *why*, and how they fit both core
variants.

---

## 1. Motivation and Goals

### 1.1 Why these instructions

SH-2/J2 is a 16-bit fixed-length ISA chosen for code density, but four common
idioms compile poorly:

1. **Constant materialization.** Any constant that does not fit the 8-bit
   `mov #imm,Rn` (sign-extended ±128) becomes a **PC-relative literal-pool
   load**: a 2-byte `mov.l @(disp,PC),Rn` plus a 4-byte literal word embedded in
   the text section. The literal pollutes the instruction stream (I-cache
   pressure) and costs 6 bytes per unique constant.

2. **Callee-saved save/restore.** Function prologues/epilogues push and pop
   `r8..r14` + `PR` one register at a time — up to 8 instructions in and 8 out
   per non-leaf function.

3. **PIC/GOT address computation.** Position-independent code uses `r12` as the
   GOT pointer (the SH GCC `PIC_OFFSET_TABLE_REGNUM`). SH has *no* instruction
   that computes a base-relative address into a register: `MOVA` is hardwired to
   `R0` and PC-relative only. So both halves of the PIC idiom are multi-step and
   clobber `R0` plus a literal-pool word:
   - **GOTOFF (local symbol address)** `&sym = r12 + gotoff`:
     `mov.l .Lgotoff,r0; add r12,r0` — a literal + an add, into `R0`.
   - **GOT slot load (external symbol address)** `&sym = *(r12 + slot)`:
     `mov.l .Lslot,r0; mov.l @(r0,r12),rN` — a literal + an indexed load, via `R0`.
   `lea` collapses the first to one instruction; adopting the SH-2A disp12
   `mov.l` collapses the second (§3.4).

4. **Unfilled branch delay slots.** SH's `jsr`/`rts` are *delayed* branches: the
   instruction after them executes before the transfer, and when the scheduler
   cannot find a useful instruction to put there it emits a 2-byte `NOP`.
   Measured on CSiBE (m2a, −O2), **3,692 of all instructions sit in a delay slot
   as a NOP — 1.69 % of the instruction stream**; `dbr_schedule` already fills
   80.6 % of slots, so the residue is unfillable by construction (see
   [`sh2a-candidate-triage.md`](sh2a-candidate-triage.md) §2 and the
   `gcc-sh-monitor` slot-fill negative result). The SH-2A delay-slot-*free*
   forms `jsr/n`/`rts/n`/`rtv/n` drop the slot entirely, recovering the `jsr`+`rts`
   share of that NOP population (§3.5).

**Measured** (differential recompile, 2026-05-29): the CSiBE benchmark (193
files that cross-compile cleanly under both) built with the *same* GCC 14.2 at
`-O2`, `-m2` (SH-2) vs `-m2a` (SH-2A), both big-endian:

| Build | size (`.text`+`.rodata`+`.data`) | vs `-m2` |
|---|---|---|
| `-m2` (SH-2) | 925,184 B | — |
| `-m2a` (SH-2A) | 911,352 B | **−1.50%** (−13,832 B) |

**Attribution is decisive: the realized win is almost entirely `movi20`.**
Disassembling every object, `-m2a` emits `movi20` **11,290** times and `movi20s`
135 (both 0 under `-m2`), but `movmu` only **1** and `movml` **0**. Stock GCC's
SH-2A codegen materializes large constants with `movi20` but barely uses the
save/restore-multiple forms — so the prologue/epilogue benefit of
`movmu`/`movml` is **latent**: realizing it needs GCC backend work
([`software-impl.md`](software-impl.md) §3.2), not merely enabling `-m2a`.

> **Why 1.5%, not the ~6–8% upper bound below.** The 1.5% is what stock GCC
> *actually emits* today; the table below is a static-idiom *upper bound* (every
> idiom replaced, full regalloc cooperation). Both are correct for what they
> measure. CSiBE (compilers, codecs, parsers, `-O2`) is also less
> prologue/epilogue-heavy than BusyBox, and this metric includes `.rodata`/`.data`,
> not `.text` alone. See [`software-impl.md`](software-impl.md) §7 and
> `.density-analysis/sh2a-run/RESULTS.md` for full method and caveats.

For design rationale, the per-idiom static upper bounds (single-corpus BusyBox
`.text`, counting each idiom the instruction *could* replace) were:

| Idiom | Replacement | Static upper-bound `.text` saving |
|---|---|---|
| Literal-pool loads (singleton constants) | `movi20` | ~4.7% (singletons only; shared pools stay pooled) |
| Push/pop runs (contiguous, ending at r14+PR) | `movmu`/`movml` | ~1.8%, up to ~3.5% with regalloc help |

These bound the *opportunity*; the measured 1.5% bounds what *today's* compiler
captures. The gap — mostly the un-emitted `movmu`/`movml` share — is the
backend work this spec's [`software-impl.md`](software-impl.md) describes. Either
way the instructions serve the original SuperH density/I-cache rationale even
though main-memory cost is no longer the driver.

> **`lea` is not in the numbers above.** The CSiBE recompile was built
> *non-PIC* (`-O2`, no `-fPIC`), so it exercises neither GOTOFF nor GOT-slot
> idioms and says nothing about `lea`. The `lea` motivation is qualitative for
> now: in PIC builds each GOTOFF address and each GOT-slot load is today a
> literal-pool word plus an `R0`-clobbering instruction (idiom 3 above); `lea`
> and the adopted disp12 `mov.l` each remove the literal and the `R0` dependency.
> A `-fPIC` differential recompile to quantify it is deferred to
> [`software-impl.md`](software-impl.md) §7 — it is *not* claimed here.

### 1.2 Goals

- Add the instructions to the J32 ISA, binary-compatible with SH-2A's encodings
  where they exist (`movi20`, `movmu`/`movml`, the adopted disp12 `mov.l`, and
  `jsr/n`/`rts/n`/`rtv/n`), and with a new collision-free encoding where they do
  not (`lea`).
- Work on **both** the in-order J2/J32 core and the J32-OoO core, with a single
  architectural definition and two implementation strategies.
- Reuse existing datapath (pre-decrement store, post-increment load, the 32-bit
  immediate bus, the address adder) wherever possible. In particular `lea` and
  the disp12 loads ride the same second-word fetch path `movi20` introduces, and
  the delay-slot-free branches reuse the existing non-delayed-branch redirect
  (the machinery SH already has for `bt`/`bf`).
- Preserve SH-2 binary compatibility: existing programs are unaffected; the new
  encodings occupy currently-illegal opcode space.

### 1.3 Non-Goals

- Not a general ARM-style load/store-multiple with an arbitrary register
  bitmask (does not fit a 16-bit word; see §4.4).
- Not adding the SH-2A bit-manipulation, `clips`/`clipu`, `mulr`, TBR table-call,
  register-bank, or `divs`/`divu` instructions, and not a `bra/n`. These were
  **evaluated empirically and rejected** — measured against CSiBE with an
  `--with-cpu=m2a` GCC 14.2, GCC emits none of them and the latent payoff does not
  justify the RTL + compiler work (full rationale and numbers in
  [`sh2a-candidate-triage.md`](sh2a-candidate-triage.md)). This spec is scoped to
  the highest-value wins: `movi20`/`movmu`/`movml` for general density,
  `lea` + disp12 `mov.l` for PIC, and `jsr/n`/`rts/n`/`rtv/n` for unfilled delay
  slots (§3.5 — the one evaluated candidate that earned promotion).
- Not a delay-slot-free *unconditional* branch (`bra/n`). There is no 16-bit
  encoding for one and a 32-bit form saves nothing — so the `bra` share of the
  delay-slot NOP population is unrecoverable (triage §3.5). `jsr/n`/`rts/n` cover
  only the `jsr`+`rts` share (§3.5 / §4.8).
- Not arbitrary base registers for the multiple-transfer forms — stack (`r15`)
  only, matching SH-2A. (`lea`'s base *is* arbitrary — that is the point; only
  the `movmu`/`movml` family is `r15`-locked.)
- Not hardcoding `r12` into the `lea`/disp12 encodings. `r12` as GOT pointer is
  an ABI convention, kept in software; the instructions take an explicit base so
  they also serve GBR-relative, frame-relative, and general address arithmetic
  (§4.7 rationale; this is why a wide-displacement 16-bit form was rejected).

### 1.4 Provenance and IP

`movi20`/`movi20s`, `movmu`/`movml`, the adopted GOT-slot load
`mov.l @(disp12,Rm),Rn`, and the delay-slot-free branches `jsr/n`/`rts/n`/`rtv/n`
are SH-2A instructions (SH-2A software manual, 2004–2005). The J-core project
historically avoided SH-2A on patent-timing grounds. As of 2026 the relevant
patents are expected to have expired, but **IP clearance must be confirmed once
for the whole bundle** before RTL work begins. This is a process gate, not a
technical one, and is owned outside this spec. (The *concept* of a non-delayed
branch is ubiquitous pre-2006 prior art — SH's own `bt`/`bf`, and every RISC ISA
that chose static branch-delay policy — so only the SH-2A *encodings* are at
issue, under the same bundle clearance.)

`lea` is **not** an SH-2A instruction — it is a new J-core encoding occupying a
reserved slot of the SH-2A disp12 instruction group (§3.4). Its IP story is
therefore cleaner: the *operation* (compute an effective address into a register
without dereferencing) is decades-old prior art under the project's pre-2006
policy ([../glossary.md §2](../glossary.md)) — Intel x86 `LEA` (8086, 1978);
Motorola 68000 `LEA <ea>,An` (1979); DEC VAX `MOVA`/`PUSHA` (1977). The only
SH-2A-derived part of `lea` is the *32-bit instruction format* it reuses (the
`0011nnnnmmmm0001` two-word prefix), which falls under the same bundle clearance
as the disp12 loads. No SH-2A patent reads on the new `1010` minor itself.

---

## 2. Background: the J2/J32 front-end today

This section states only facts verified from the RTL
(`jcore-cpu/core/cpu.vhd`, `decode/decode*.vhd`, `core/datapath.vhd`,
`core/register_file*.vhd`). Citations are in [`hardware-impl.md`](hardware-impl.md) §2.

- **Strictly 16-bit fetch.** One 16-bit word is fetched per instruction into the
  instruction register `if_dr`. PC advances by 2. **No instruction in the ISA
  fetches a second word** — there is no 32-bit-instruction support anywhere in
  the front-end today. This is the single most important fact for `movi20`.
- **Microcoded decode.** `decode_body.vhd:predecode_rom_addr()` maps the 16-bit
  opcode to an **8-bit microcode *start* address** (`op.addr`). The sequencer
  (`decode_core.vhd`) then **advances `op.addr` by +1 each non-stalled cycle**;
  each microcode step emits a `dispatch` bit, and the step that asserts
  `dispatch` is the last (the next cycle loads the next instruction's start
  address from predecode). Multi-cycle instructions are therefore linear runs of
  consecutive microcode addresses. Crucially, the per-step `dispatch` bit and all
  control outputs are **combinational functions of the 16-bit opcode**
  (`decode_table`), so a step *can* make its decision — including whether it is
  the last step — depend on operand fields of the opcode.
- **No operand-driven loop counter.** `op.addr` only ever increments by +1 —
  there is no microcode branch/jump target, no decrement-and-branch primitive,
  and no iteration counter. Variable-length behaviour must be expressed either by
  selecting a different *start* address per opcode (predecode is arbitrary
  combinational logic) or by a step asserting `dispatch` early as a function of
  the opcode — **not** by looping. This is the pivotal fact for `movmu`/`movml`
  (see [`hardware-impl.md`](hardware-impl.md) §5). (Consistent with `DIV1` being a
  single-cycle step that software repeats.)
- **Register file: 2 read ports, 2 write ports** (`num_x`/`num_y` read;
  `num_z` EX-writeback and `num_w` late-writeback). One register per cycle in or
  out is comfortably within budget.
- **Pre-dec / post-inc already exist.** `mov.l Rm,@-Rn` and `mov.l @Rm+,Rn`
  already compute the adjusted address, drive the memory access, and write the
  updated pointer back. `movmu`/`movml` are, per element, exactly these.
- **Multi-cycle stall model exists.** `MAC.W`/`MAC.L` hold the pipeline via
  `mac_busy` while a functional unit works. This is the template for any
  multi-cycle hold the new instructions need.

The OoO core (`../ooo/j32ooo-spec.md`) replaces this front-end with
fetch→decode→**rename**→dispatch→issue→RS→EX→ROB, and §4.3/§5.1 of that spec
already commit to **cracking complex instructions into uops**.

---

## 3. Instruction Definitions (architectural)

Notation: bit 15 is MSB. `nnnn`/`mmmm` = 4-bit register field. `iiii…` =
immediate bits. `dddd…` = displacement bits.

### 3.1 `movi20` / `movi20s` — 20-bit immediate load (32-bit)

| Mnemonic | Encoding (word0 word1) | Operation |
|---|---|---|
| `movi20  #imm20,Rn`  | `0000 nnnn iiii 0000` `iiiiiiiiiiiiiiii` | sign_extend₂₀(imm) → Rn |
| `movi20s #imm20,Rn`  | `0000 nnnn iiii 0001` `iiiiiiiiiiiiiiii` | sign_extend₂₈(imm) << 8 → Rn |

- The 20-bit immediate is `word0[11:8]` (high nibble) concatenated with
  `word1[15:0]`.
- `movi20`: sign-extend the 20-bit value to 32 bits. Range −524288..+524287.
- `movi20s`: the 20-bit value is shifted left by 8 (so it lands in bits
  [27:8]) and sign-extended from bit 27. Reaches large/upper-bit constants and
  addresses that `movi20` cannot.
- PC advances by **4**. These are the only J32 instructions that consume two
  instruction words.
- No flags affected. No memory access.

These encodings are byte-identical to SH-2A `MOVI20`/`MOVI20S`.

### 3.2 `movmu.l` / `movml.l` — load/store-multiple (16-bit)

| Mnemonic | Encoding | Set transferred |
|---|---|---|
| `movmu.l Rm,@-r15`  | `0100 mmmm 1111 0000` | push `Rm … R14`, then `PR` |
| `movmu.l @r15+,Rn`  | `0100 nnnn 1111 0100` | pop `PR`, then `R14 … Rn` |
| `movml.l Rm,@-r15`  | `0100 mmmm 1111 0001` | push `Rm … R0` |
| `movml.l @r15+,Rn`  | `0100 nnnn 1111 0101` | pop `R0 … Rn` |

Semantics (verified against the SH-2A manual; matches the `insns.json` operation
pseudocode in the repo):

```
# movmu.l Rm,@-r15   (save upper: callee-saved set when m == 8)
mem[r15-4] = PR;  r15 -= 4
for i in 14 downto m:        # descending
    mem[r15-4] = R[i];  r15 -= 4

# movmu.l @r15+,Rn   (restore upper: exact mirror)
for i in n to 14:            # ascending
    R[i] = mem[r15];  r15 += 4
PR = mem[r15];  r15 += 4

# movml.l Rm,@-r15   (save lower: R0..Rm)
for i in m downto 0:
    mem[r15-4] = R[i];  r15 -= 4

# movml.l @r15+,Rn   (restore lower: R0..Rn)
for i in 0 to n:
    R[i] = mem[r15];  r15 += 4
```

- Base register is implicitly `r15`. Pre-decrement on store, post-increment on
  load — built from the existing `@-Rn` / `@Rm+` primitives.
- **`R15`→`PR` aliasing** (SH-2A quirk, preserved): in the *upper* forms the
  `PR` slot is bundled at the top of the range; the field never names `r15`
  itself as a transferred GPR.
- Longword transfers only; `r15` must be 4-byte aligned (normal address-error
  behavior otherwise — see §5).
- The transferred count is `15 - m` (+PR) for `movmu`, `m + 1` for `movml` —
  i.e. **1 to 8 (movmu) / 1 to 16 (movml) registers**, variable, encoded by the
  single anchor field.

### 3.3 Why a contiguous range, not a bitmask

A 16-bit word cannot hold both a 16-bit register mask and an opcode. The
SH-2A contiguous-range-from-anchor design encodes "1 to N registers" in a single
4-bit field by fixing one endpoint (R14+PR or R0) and naming the other. This is
the only "limited form" that fits 16 bits, and it exactly matches the ABI
callee-saved set at `m = 8`. The cost is that the compiler must allocate
callee-saved registers as a contiguous high range to fully exploit it
(see [`software-impl.md`](software-impl.md) §4).

### 3.4 `lea` — load effective address (32-bit)

| Mnemonic | Encoding (word0 word1) | Operation |
|---|---|---|
| `lea @(disp,Rm),Rn` | `0011 nnnn mmmm 0001` `1010 dddddddddddd` | Rm + sign_extend₁₂(disp) → Rn |

```
void LEA (int d, int m, int n)   # disp = sign_extend_12(d), unscaled (bytes)
{
  long disp = (d & 0x800) ? (long)(d | 0xFFFFF000) : (long)d;
  R[n] = R[m] + disp;            # no memory access
  PC += 4;
}
```

- Computes a base-plus-displacement effective address and writes it to `Rn`.
  **No memory access, no flags affected.** This is the SuperH analogue of x86
  `LEA` / 68k `LEA` — the address-arithmetic operation the SH ISA otherwise
  lacks. The only existing address-compute instruction, `MOVA @(disp,PC),R0`, is
  hardwired to `R0` and PC-relative; `lea` generalises it to an arbitrary base
  `Rm` and an arbitrary destination `Rn`.
- `disp` is the 12-bit field `word1[11:0]`, **sign-extended** (range
  −2048..+2047) and **unscaled** (byte granularity) — decided over the scaled,
  unsigned form of the disp12 *loads* that share this encoding group; rationale
  and the rejected alternative are in §4.6 / §8.6.
- Base `Rm` is **any** GPR. In PIC code `Rm = r12` (the SH GCC GOT pointer), so
  `lea @(gotoff,r12),Rn` materialises a GOTOFF address in one instruction with
  no `R0` clobber and no literal-pool word. With `Rm = r15` it computes
  frame-relative addresses (`&local`); it is a general pointer-arithmetic op.
- PC advances by **4** (a two-word instruction, like `movi20`).
- **New encoding** (not SH-2A): it occupies word1-minor `1010` of the SH-2A
  disp12 group whose 16-bit prefix is `0011nnnnmmmm0001`. SH-2A defines minors
  `0000`–`1001` (the disp12 loads/stores, §3.4.1); `1010`–`1111` are unallocated.
  Verified collision-free against SH-2, SH-2A, SH-4/SH-4A, and the J32 decoder
  (`docs/insns.json` sweep; see §6).

#### 3.4.1 Companion: GOT-slot load via existing SH-2A `mov.l @(disp12,Rm),Rn`

The *other* half of the PIC idiom — loading a GOT slot (`Rn = *(r12 + slot)`,
the address of an external symbol) — needs **no new instruction**. SH-2A already
defines, in the same encoding group as `lea`:

| Mnemonic | Encoding (word0 word1) | Operation |
|---|---|---|
| `mov.l @(disp12,Rm),Rn` | `0011 nnnn mmmm 0001` `0110 dddddddddddd` | Read_32(Rm + (disp << 2)) → Rn |

This carries an **explicit base register** and a **12-bit ×4-scaled** (longword)
displacement — reach `Rm + 16380`, i.e. **4095 GOT slots** with `Rm = r12`. It
is byte-identical SH-2A but **`J32: False`** (not implemented in J-core today).
*Adopting* it — it shares `lea`'s decode prefix and the `movi20` second-word
fetch — replaces today's `mov.l .Lslot,r0; mov.l @(r0,r12),rN` pair with one
instruction, no `R0` clobber, no literal. `lea` (address compute) and this load
(slot fetch) are the matched pair, exactly as x86/68k pair `LEA` with their
displacement loads. The matching `mov.b/w`, `movu.b/w`, and stores come with the
same prefix for free if wanted, but only `mov.l` is required for PIC.

### 3.5 `jsr/n`, `rts/n`, `rtv/n` — delay-slot-free call and return (16-bit)

| Mnemonic | Encoding | Operation |
|---|---|---|
| `jsr/n @Rm`  | `0100 mmmm 0100 1011` | `PR ← (addr of next instruction); PC ← Rm` |
| `rts/n`      | `0000 0000 0110 1011` | `PC ← PR` |
| `rtv/n Rm`   | `0000 mmmm 0111 1011` | `R0 ← Rm; PC ← PR` |

```
void JSRN (int m)  { PR = PC + 2; PC = R[m]; }      /* PC = address of jsr/n */
void RTSN (void)   { PC = PR; }
void RTVN (int m)  { R[0] = R[m]; PC = PR; }
```

- **No delay slot.** Unlike `jsr`/`rts` (and `bsr`, `jmp`, `bra`, `braf`, the
  `…/s` conditionals), these do **not** execute the textually-following
  instruction before transferring. They are the call/return analogues of SH's
  already-non-delayed `bt`/`bf`. The instruction after a `jsr/n` is ordinary
  straight-line code; nothing is reserved or skipped.
- **`jsr/n @Rm`** — indirect subroutine call. `PR` receives the address of the
  instruction sequentially following the `jsr/n` (no slot is skipped), so the
  callee returns *right after* the call. This is the slot-free counterpart of
  `jsr @Rm`, which is the form GCC emits for almost all SH calls (target loaded
  into a register, then `jsr @reg`).
- **`rts/n`** — subroutine return; `PC ← PR`, no slot. Slot-free counterpart of
  `rts`.
- **`rtv/n Rm`** — "return with value": `R0 ← Rm` then `PC ← PR`, no slot. Folds
  the common `mov Rm,r0; rts` epilogue (move the result into the ABI return
  register `r0`, then return) into one 2-byte instruction when the result is not
  already in `r0`.
- 16-bit instructions; PC advances per the transfer (no `+2` straight-line step).
  No flags affected. `T` unchanged.
- These are **byte-identical SH-2A** encodings, verified collision-free against
  SH-2, SH-2A, SH-4/SH-4A, and the J32 decoder (`docs/insns.json` sweep; see §6).

**What they recover (and the ceiling).** The SH scheduler must emit a 2-byte
`NOP` whenever it cannot fill a delayed branch's slot. Measured on CSiBE (m2a,
−O2): **3,692 delay-slot NOPs (1.69 % of instructions)**, distributed as

| delayed branch | unfilled (NOP) slots | coverable by a `/N` form? |
|---|---|---|
| `jsr` | 1,508 | ✅ `jsr/n` |
| `rts` | 233 | ✅ `rts/n` (or `rtv/n`) |
| `bra` | 1,766 | ❌ no slot-free `bra` (§4.8 / triage §3.5) |
| `braf` | 133 | ❌ |
| `jmp` | 52 | ❌ |

`jsr/n`+`rts/n`+`rtv/n` therefore address **1,741 slots = ~47 % of the NOP
population = 0.80 % of instructions (~3.5 KB, ~0.4 % of `.text`)** on CSiBE, and
more in call-heavy code (BusyBox+musl left 6,386 unfilled *indirect-jsr* slots
alone). The `bra`/`braf`/`jmp` half is structurally unrecoverable — see §4.8.

> **Latent until GCC emits the `/N` forms.** Like every other SH-2A instruction
> here except `movi20`, stock GCC does not emit `jsr/n`/`rts/n` today (it
> schedules a delay slot and pads with `NOP`). The benefit above requires the
> backend pass in [`software-impl.md`](software-impl.md) §3.6 — a local rewrite of
> an unfilled-slot `jsr`/`rts` into its `/N` form — not merely enabling the
> encodings.

---

## 4. Design Decisions

### 4.1 Two cores, one architecture, two implementations

The instructions are defined once (§3) and implemented twice:

| | In-order J2/J32 | J32-OoO |
|---|---|---|
| `movi20` | 2-cycle microcode chain: fetch word1, then write Rn | decode emits 1 uop carrying the assembled 32-bit imm; fetch widened to deliver both words |
| `movmu`/`movml` | shared straight-line microcode chain, multiple entry points (§4.3) | decode **cracks** into N memory uops + pointer-update uop(s) (§4.2) |

The architectural result (registers, memory, `r15`, `PR`) is identical on both.
This is the "handle all cases" requirement: a program built with these
instructions runs unmodified on either core.

### 4.2 OoO strategy: crack into uops (aligns with OoO §5.1)

The OoO spec already mandates cracking multi-register ops into uops. This spec
specializes that:

- `movmu`/`movml` decode into a sequence of **single-register memory uops**
  (each a `store Rk,@-r15` / `load @r15+,Rk` equivalent) plus the `r15` update.
  Each uop is renamed, issued, and retired independently.
- `PR` is treated as a renameable/serialized control register (OoO §4.4) and is
  one more uop in the sequence.
- **Precise exceptions fall out for free** (OoO §5.2): a fault on uop *k* leaves
  uops `0..k-1` retired and `k..end` squashed — which is exactly the
  restartable behavior the in-order core must engineer explicitly (§5).
- `movi20` is a single uop carrying the pre-assembled 32-bit immediate; the only
  OoO front-end change is delivering two instruction words to decode (the fetch
  unit is already being redesigned with a fetch buffer in OoO Phase 1).

This is the **preferred long-term implementation** and the reason these
instructions belong in the J32OOO plan: the OoO microarchitecture makes
multi-register ops *natural*, whereas the in-order core makes them *awkward*.

### 4.3 In-order strategy: shared chain with multiple entry points

For the in-order core, the chosen primary approach (see §1 decision record)
avoids any new sequencer hardware:

- Build **one** straight-line microcode chain of up to 8 (movmu) / 16 (movml)
  steps, each step transferring exactly one register and falling through to the
  next via the existing next-address field.
- Because the chain for `Rm..R14` is a *tail* of the chain for `R(m-1)..R14`,
  the `predecode_rom_addr` logic selects the **entry point** into the shared
  chain from the anchor field. No loop counter, no decrement-branch — just
  arbitrary combinational predecode (which already exists) choosing one of N
  start addresses.
- The pipeline holds across the chain using the existing `mac_busy`-style stall
  mechanism.

The alternative — a register-index counter plus a decrement-branch-nonzero
microcode primitive — is **not** chosen as primary (it is genuine new sequencer
RTL and a new microcode field) but is documented as a fallback in
[`hardware-impl.md`](hardware-impl.md) §5.4 in case ROM-space or fan-out makes
the shared-chain approach unattractive.

### 4.4 Interrupt / restart model (in-order)

`movmu`/`movml` are **non-interruptible in v1** on the in-order core: the chain
runs to completion atomically, with `r15` committed only at the end. Worst-case
added interrupt latency is bounded (~8 longword memory cycles) and acceptable
for J-core interrupt budgets. This removes all partial-architectural-state
hazards. (The OoO core does not need this rule — uop-level retirement already
gives precise, restartable behavior.)

### 4.5 `movi20` second-word fetch is the critical-path risk

The one capability the in-order front-end lacks entirely is fetching a second
instruction word. This is isolated, well-understood, and a prerequisite for any
future 32-bit SH-2A instruction (disp12 moves, bit-ops, etc.). It is specified
in detail in [`hardware-impl.md`](hardware-impl.md) §4 and flagged there as the
item to prototype first.

### 4.6 `lea` displacement: sign-extended and unscaled (decided 2026-05-30)

`lea`'s 12-bit displacement is **sign-extended and unscaled** (−2048..+2047,
byte granularity), *unlike* the SH-2A disp12 *loads* that share its encoding
group (which scale by operand size — `disp << 2` for `mov.l`). Rationale:

- **Generality.** x86, 68k, and VAX `LEA` all do raw, byte-granular address
  arithmetic; `lea` has no operand size to scale by. Byte granularity is required
  for GOTOFF addresses of sub-longword data (chars, packed struct fields) and for
  general `&expr` pointer arithmetic.
- **Signed displacement** lets GOTOFF data sit on *either* side of the GOT base,
  which the linker's data layout may require. The GOT-slot *load* (§3.4.1), which
  only indexes upward into the GOT, keeps its unsigned ×4 form.
- **Prior art — both forms clear the pre-2006 bar; this one is broader.** A
  scaled, zero-extended address computation is *not* prior-art-less: SH's own
  `MOVA @(disp,PC),R0` (SH-1, 1992) is exactly `disp`-zero-extended-×4, as are
  the `@(disp,Rn)` / `@(disp,GBR)` scaled load modes. But the sign-extended,
  byte-granular form carries the *canonical, multi-source* `LEA` prior art —
  Intel 8086 (1978), Motorola 68000 (1979), DEC VAX (1977) — i.e. the semantics
  a reader expects of an instruction named `lea`. Choosing it loses no prior-art
  coverage and gains the more general operation.

The only thing given up is reach: ±2048 bytes vs. the load's +16380. For larger
GOTOFF the compiler falls back to `movi20`+`add` or the constant pool
([`software-impl.md`](software-impl.md) §3) — and large GOTOFF needs that
regardless, since whole-section offsets exceed any 12-bit field. The
scaled-×4/unsigned variant was **considered and rejected** (§8.6 decision record).

### 4.7 Why a 32-bit form, and the 16-bit alternative

A 16-bit `lea` cannot carry a useful displacement: `opcode + Rn(4) + Rm(4)`
already consumes 8–12 bits, leaving no room for a meaningful `disp` *and* a free
base register — the only way to widen the displacement in 16 bits is to hardcode
the base (e.g. always `r12`), baking an ABI convention into the ISA (§1.3,
rejected). SH-2A's 32-bit format already carries a full base register *and* a
12-bit displacement, and the second-word fetch it needs is being built for
`movi20` anyway — so the 32-bit `lea` is nearly free to add and stays
ABI-neutral.

A **16-bit indexed** form, `lea @(R0,Rm),Rn` → `R[n] = R[m] + R[0]`, remains a
viable *lighter-weight companion*: it fits the unallocated `1111nnnnmmmm1111`
slot (free in SH-2, SH-2A, SH-4, and J32), is 2 bytes, executes in one cycle
reusing the address adder, but offers **no displacement** and reintroduces an
`R0` dependency (the very thing the 32-bit form removes). It is documented as an
alternative, not the primary encoding — Open Question §8.7.

### 4.8 Delay-slot-free branches: reuse the `bt`/`bf` redirect; no `bra/n`

**Implementation is not novel.** SH already has *non-delayed* branches: `bt` and
`bf` take their branch without executing a delay-slot instruction (only `bt/s`,
`bf/s` are delayed). The front-end therefore already squashes the
sequentially-fetched successor and redirects fetch on a taken non-delayed branch.
`jsr/n`/`rts/n`/`rtv/n` reuse that exact path, adding only the datapath each
already needs in its delayed form: `jsr/n` writes `PR` (as `jsr` does) and
redirects to `Rm`; `rts/n` redirects to `PR`; `rtv/n` writes `R0 ← Rm` then
redirects to `PR`. No new fetch capability, no second-word fetch (these are
16-bit), no new sequencer state. This is the **lowest-RTL-risk** item in the
bundle. Per-core detail is in [`hardware-impl.md`](hardware-impl.md) §4A.

**Why no `bra/n`.** The biggest delay-slot-NOP category is `bra` (1,766 of 3,692
on CSiBE, §3.5), but a slot-free *unconditional* branch cannot be added profitably:

- A **16-bit** `bra/n` with `bra`'s ±4 KB reach needs a whole free top nibble
  (as `bra`=`1010…`/`bsr`=`1011…` each consume one). **No top nibble is free**
  across SH-2/2A/4; the only one free in the bare J32 column is `1111`, which is
  the FPU block on any FPU-bearing part. No room.
- A **32-bit** `bra/n` is 4 bytes = exactly `bra`(2) + `nop`(2): **zero size
  win**, and a 12-bit displacement reaches no farther than `bra` so it cannot help
  far branches either. A wider (disp20) form *could* replace the far-branch
  sequence, but far branches with NOPs are rare (133 on CSiBE) — too small to
  justify a dedicated instruction.

This is exactly why SH-2A made only the *no-displacement* branches (`jsr/n`,
`rts/n`, `rtv/n`) slot-free. The full reasoning is in
[`sh2a-candidate-triage.md`](sh2a-candidate-triage.md) §3.5.

---

## 5. Exceptions and Corner Cases

- **Address error:** `movmu`/`movml` raise the normal address-error exception if
  `r15` is not longword-aligned, identical to `mov.l`. In-order: the exception
  is taken before `r15` is committed (non-interruptible chain, single commit
  point). OoO: the faulting memory uop signals the exception; the ROB squashes
  it and all younger uops, leaving older transfers retired — a *precise* partial
  completion.
- **`movmu`/`movml` with an out-of-range anchor:** behavior for anchors that
  imply an empty or wrapping range (e.g. `movmu` with `m = 15`) is **reserved /
  illegal-instruction**. The exact decode is defined in
  [`hardware-impl.md`](hardware-impl.md) §5.3.
- **`movi20` in a branch delay slot:** a 32-bit instruction in a delay slot is
  **illegal** (the delay-slot fetch machinery assumes a 16-bit successor). The
  existing `check_illegal_delay_slot` predecode is extended to flag it. See
  [`hardware-impl.md`](hardware-impl.md) §4.5.
- **`lea` / disp12 `mov.l` in a branch delay slot:** also **illegal** for the
  same reason (32-bit, two-word). The same `check_illegal_delay_slot` extension
  covers all members of the `0011nnnnmmmm0001` group.
- **`lea` raises no memory exception:** it performs address arithmetic only, with
  no access — it cannot fault on alignment or translation, and computing an
  out-of-range/garbage address is not an error (the address is not used until a
  later load/store, which faults normally). The disp12 `mov.l` (§3.4.1) *does*
  take the usual `mov.l` address-error/translation behaviour on `Rm + (disp<<2)`.
- **Interaction with single-step / debug:** non-interruptible `movmu` completes
  before a single-step trap is taken. The debugger sees the instruction as
  atomic. (OoO: retirement-based stepping is unaffected.)
- **`jsr/n`/`rts/n`/`rtv/n` in a branch delay slot:** **illegal**, like any
  branch in a delay slot — flagged by the existing `check_illegal_delay_slot`
  predecode (this is the *branch-in-slot* rule, independent of the 32-bit rule for
  `movi20`/`lea`). They are 16-bit, so they are otherwise legal anywhere.
- **`jsr/n`/`rts/n`/`rtv/n` carry no delay slot:** the instruction textually
  following is *not* executed before the transfer. `PR` from `jsr/n` is the
  address of that following instruction (no slot is skipped), so a callee returns
  to it directly. This differs from `jsr`/`rts`, where `PR`/return skips the slot
  — the debugger and unwinder must use the right return-offset per form
  ([`software-impl.md`](software-impl.md) §5).
- **`rtv/n` writeback then transfer:** `R0 ← Rm` commits before `PC ← PR`; an
  interrupt taken at the boundary sees the completed `R0` write (the instruction
  is atomic, like any single branch).

These cases are enumerated as a checklist in [`hardware-impl.md`](hardware-impl.md)
§5 and exercised by the tests in [`software-impl.md`](software-impl.md) §6.

---

## 6. Compatibility

- **SH-2 binary compatibility:** the encodings occupy opcode space that is
  currently illegal on J2/J32 (verified collision-free against the full decode
  table for both J32 and SH4). Existing binaries are unaffected.
- **SH-2A binary compatibility:** `movi20`/`movmu`/`movml`, the adopted disp12
  `mov.l`, and `jsr/n`/`rts/n`/`rtv/n` are byte-identical to SH-2A, so
  SH-2A-targeted objects using them execute correctly on J32 once the feature is
  present. `lea` is a J-core addition with no SH-2A counterpart, so a `lea`-using
  object is J32-only. The reverse (J32 binaries using any of these on a stock
  SH-2) is not supported — they are a J32 superset.
- **`jsr/n`/`rts/n`/`rtv/n` collision check (`docs/insns.json`):** the encodings
  `0100mmmm01001011`, `0000000001101011`, `0000mmmm01111011` are illegal in SH-2
  and unclaimed by the J32 decoder (verified). A `/N`-using object on a stock
  SH-2 faults illegal-instruction — fail-stop, not silent.
- **`lea` collision check (`docs/insns.json`):** the 16-bit prefix
  `0011nnnnmmmm0001` is used *only* by the SH-2A 32-bit disp12 family and is
  illegal in SH-2, SH-2A's 16-bit space, SH-4/SH-4A, and J32. Within that prefix,
  word1-minors `1010`–`1111` are unallocated; `lea` takes `1010`. A `lea`-using
  object run on a stock SH-2A (which lacks the `1010` minor) faults
  illegal-instruction rather than mis-executing — fail-stop, not silent.
- **Feature gating:** the instructions are a build-time core configuration
  (a generic / VHDL config, like the existing decoder-style selection). A core
  built without them treats the encodings as illegal instructions, preserving
  strict SH-2 behavior. The toolchain gates emission behind a `-m` flag
  (see [`software-impl.md`](software-impl.md) §2).

---

## 7. Verification Strategy (architectural)

Full detail in the companion specs; the architectural requirements are:

1. **Equivalence to semantics in §3** for every register count (1..8 / 1..16)
   and both directions, on both cores.
2. **In-order ↔ OoO co-simulation**: same program, identical architectural
   state at every retirement boundary (OoO spec §7 co-sim harness).
3. **Exhaustive decode check**: the new opcodes decode correctly and *every
   other* opcode is unchanged (differential against the pre-change decoder,
   per the decoder-migration spec's Layer 3 sweep).
4. **Exception precision**: forced misalignment mid-transfer leaves exactly the
   architecturally-correct partial state on each core.
5. **Delay-slot-free branch semantics**: `jsr/n`/`rts/n`/`rtv/n` execute **no**
   delay slot (the successor is squashed/not-issued, exactly as for a taken
   `bt`/`bf`); `PR` from `jsr/n` is the next-instruction address; `rtv/n` commits
   `R0 ← Rm` before transfer; branch-in-delay-slot is illegal. Verified by
   directed tests on both cores ([`hardware-impl.md`](hardware-impl.md) §8.2) and
   against the C sim model.

---

## 8. Open Questions

1. **IP clearance** for the SH-2A encodings (process gate, §1.4).
2. **Generator support** for multiple-entry shared microcode chains: the
   mechanism is framework-compatible but not used by any existing instruction;
   confirm the Clojure (or future Go) generator can express shared-tail chains
   with multiple predecode entry points without new microcode fields. See
   [`hardware-impl.md`](hardware-impl.md) §5.2.
3. **Microcode ROM budget**: the shared chain adds ≤ ~16 microcode steps; the
   8-bit (256-entry) address space utilization was not measured. Confirm
   headroom.
4. **Regenerate-first dependency**: the decoder is generated and the toolchain
   (lein/JVM) is not currently installed; the Go migration (`gen-go/`) is not
   started. Decide whether to restore the Clojure flow or land the Go migration
   before this work (see [`software-impl.md`](software-impl.md) §1).
5. **`movi20s` exact sign-extension width**: confirm against the SH-2A manual
   whether the pre-shift value is sign-extended from bit 19 then shifted, or the
   post-shift value from bit 27 (this spec assumes the latter); the two differ
   for negative immediates.
6. **`lea` displacement form — RESOLVED (2026-05-30):** sign-extended, unscaled
   (±2048, byte-granular). The scaled-×4/unsigned alternative (+16380,
   longword-granular, uniform with the disp12 loads) was rejected: it is less
   general (no signed GOTOFF, no sub-longword targets), and although it *does*
   have pre-2006 prior art (SH `MOVA`'s zero-extended ×4 — so the choice was
   *not* forced by prior-art absence), it carries narrower prior art than the
   canonical x86/68k/VAX `LEA` semantics. The reach loss is recoverable via the
   `movi20`/pool fallback. See §4.6. *(Follow-up: the `-fPIC` GOTOFF
   offset-distribution measurement in [`software-impl.md`](software-impl.md) §7(d)
   is now a confirm-the-fallback-rate check, not a decision input.)*
7. **`lea` 16-bit indexed companion** (§4.7): is the lighter
   `lea @(R0,Rm),Rn` (`1111nnnnmmmm1111`) worth adding alongside the 32-bit form
   for the no-displacement case, or does it just re-introduce the `R0` pressure
   the 32-bit form exists to remove? Note `1111…` is the FPU/SIMD nibble — confirm
   the slot stays clear on FPU-bearing J32 parts before committing.
8. **Adopt the SH-2A disp12 load family wholesale?** §3.4.1 needs only `mov.l`
   for PIC, but the same prefix carries `mov.b/w`, `movu.b/w`, and the disp12
   stores (and `fmov.s`). Decide whether to implement just `mov.l` (minimal PIC
   support) or the whole group (full SH-2A disp12 compatibility) — a scope, not a
   feasibility, question, since they share decode and fetch.
9. **GCC `/N`-emission pass**: stock GCC does not emit `jsr/n`/`rts/n`/`rtv/n`
   (§3.5). The realized saving depends on a backend pass that rewrites an
   unfilled-slot `jsr`/`rts` to its `/N` form and folds `mov Rm,r0; rts` →
   `rtv/n Rm` ([`software-impl.md`](software-impl.md) §3.6). Confirm it runs after
   `dbr_schedule` (so it only fires on slots `dbr_schedule` left as `NOP`) and
   re-measure the realized vs. the 0.80 %-of-instructions opportunity (§3.5).

## Document status

Proposed draft. RTL not started. The `movi20`/`movmu`/`movml` numbers in §1 mix
a measured `-m2`→`-m2a` recompile (1.5%) with static upper bounds; the `lea`
PIC/GOT benefit is **qualitative only** — no `-fPIC` corpus has been recompiled
(§1.1 note, [`software-impl.md`](software-impl.md) §7). The
`jsr/n`/`rts/n`/`rtv/n` opportunity is **measured** (0.80% of instructions,
~0.4% of `.text` on CSiBE, §3.5) but **latent** until the GCC `/N` pass lands
(§8.9). Implementation gated on Open Questions §8.1 (IP) and §8.4 (regeneration
toolchain). `lea`'s displacement form is **decided**
(sign-extended/unscaled, §4.6 / §8.6).
