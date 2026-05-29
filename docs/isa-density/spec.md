# J32 Code-Density ISA Extensions: `movi20` and `movmu`/`movml`

**Status:** Draft / Proposed
**Target:** J32 (SH-2 ISA, 32-bit), both the in-order J2/J32 core and the J32-OoO core
**Audience:** CPU architects, RTL engineers, toolchain developers picking this up cold
**Companion docs:** [`hardware-impl.md`](hardware-impl.md), [`software-impl.md`](software-impl.md)
**Parent plan:** [`../ooo/j32ooo-spec.md`](../ooo/j32ooo-spec.md) §5 (Multi-Register Operations)

---

## 0. Document Map

This is the **architectural / design spec** for three SH-2A-derived code-density
instructions added to the J32 ISA:

- `movi20` / `movi20s` — load a 20-bit immediate (32-bit instruction).
- `movmu.l` / `movml.l` — store-multiple / load-multiple of a contiguous
  register range against the stack (16-bit instructions).

Microarchitecture is in [`hardware-impl.md`](hardware-impl.md); toolchain and ABI
in [`software-impl.md`](software-impl.md). This file defines *what* the
instructions are and *why*, and how they fit both core variants.

---

## 1. Motivation and Goals

### 1.1 Why these instructions

SH-2/J2 is a 16-bit fixed-length ISA chosen for code density, but two common
idioms compile poorly:

1. **Constant materialization.** Any constant that does not fit the 8-bit
   `mov #imm,Rn` (sign-extended ±128) becomes a **PC-relative literal-pool
   load**: a 2-byte `mov.l @(disp,PC),Rn` plus a 4-byte literal word embedded in
   the text section. The literal pollutes the instruction stream (I-cache
   pressure) and costs 6 bytes per unique constant.

2. **Callee-saved save/restore.** Function prologues/epilogues push and pop
   `r8..r14` + `PR` one register at a time — up to 8 instructions in and 8 out
   per non-leaf function.

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

### 1.2 Goals

- Add the three instructions to the J32 ISA, binary-compatible with SH-2A's
  encodings where they exist.
- Work on **both** the in-order J2/J32 core and the J32-OoO core, with a single
  architectural definition and two implementation strategies.
- Reuse existing datapath (pre-decrement store, post-increment load, the 32-bit
  immediate bus) wherever possible.
- Preserve SH-2 binary compatibility: existing programs are unaffected; the new
  encodings occupy currently-illegal opcode space.

### 1.3 Non-Goals

- Not a general ARM-style load/store-multiple with an arbitrary register
  bitmask (does not fit a 16-bit word; see §4.4).
- Not adding a hardware divider, FPU ops, or the SH-2A bit-manipulation /
  `TBR` instructions. Those are separate candidates (see the density ranking
  analysis); this spec is scoped to the two highest-value, lowest-risk wins.
- Not arbitrary base registers for the multiple-transfer forms — stack (`r15`)
  only, matching SH-2A.

### 1.4 Provenance and IP

All three encodings are SH-2A instructions (SH-2A software manual, 2004–2005).
The J-core project historically avoided SH-2A on patent-timing grounds. As of
2026 the relevant patents are expected to have expired, but **IP clearance must
be confirmed once for the whole bundle** before RTL work begins. This is a
process gate, not a technical one, and is owned outside this spec.

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
- **Interaction with single-step / debug:** non-interruptible `movmu` completes
  before a single-step trap is taken. The debugger sees the instruction as
  atomic. (OoO: retirement-based stepping is unaffected.)

These cases are enumerated as a checklist in [`hardware-impl.md`](hardware-impl.md)
§5 and exercised by the tests in [`software-impl.md`](software-impl.md) §6.

---

## 6. Compatibility

- **SH-2 binary compatibility:** the three encodings occupy opcode space that is
  currently illegal on J2/J32 (verified collision-free against the full decode
  table for both J32 and SH4). Existing binaries are unaffected.
- **SH-2A binary compatibility:** the encodings are byte-identical to SH-2A, so
  SH-2A-targeted objects using these instructions execute correctly on J32 once
  the feature is present. The reverse (J32 binaries using them on a stock SH-2)
  is not supported — they are a J32 superset.
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

## Document status

Proposed draft. RTL not started. Numbers in §1 are static-analysis upper bounds,
not measured against a recompiled corpus. Implementation gated on Open Questions
§8.1 (IP) and §8.4 (regeneration toolchain).
