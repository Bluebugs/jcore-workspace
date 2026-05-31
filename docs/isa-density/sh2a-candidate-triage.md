# SH-2A Instruction Candidate Triage — what we evaluated, and why most of it stays out

**Status:** Design record (decisions captured 2026-05-30)
**Companion to:** [`spec.md`](spec.md) (the instructions we *are* adding — `movi20`, `movmu`/`movml`, `lea`)
**Audience:** CPU architects and toolchain devs deciding which SH-2A instructions are worth bringing into J32.

---

## 1. Purpose and method

`spec.md` adds the high-value SH-2A-derived density instructions to J32. This
document records the **rest of the evaluation**: the other SH-2A instructions we
examined for code-size or register-pressure benefit, what we measured, and why
all but one are **not** being adopted. It exists so the decision is not
re-litigated from scratch later.

**Candidate set.** The 109 instructions present in SH-2A but absent from the J32
baseline (`docs/insns.json`, filter `SH2A == true && J32 == false`), minus the
FPU group (which belongs to [`../fpu/spec.md`](../fpu/spec.md), not the density
work).

**Method — empirical, not from memory.** Every "would GCC emit this / how much
would it save" claim below was measured, not guessed, using the `gcc-sh-monitor`
sibling repo:

- **Toolchain:** GCC 14.2 built `--with-cpu=m2a --with-endian=big` (the SH-2A
  cross-compiler at `/tmp/sh2a-measure/gcc-m2a`, run inside the
  `gcc-sh-base:dev` container for glibc). m2a is the *default* cpu for that
  build, so plain `-O2` exercises SH-2A codegen.
- **Corpus:** CSiBE (`gcc-sh-monitor/csibe`, 167 of the C files compiled clean to
  assembly at `-O2`), 218,173 instruction lines — the same corpus the density
  spec uses.
- **Encoding checks:** collision-tested against `docs/insns.json` for SH-2,
  SH-2A, SH-4/4A, and the J32 decoder, the same sweep used for `lea`.

**Headline finding (decisive for everything below).** *GCC 14.2 emits **none** of
the special SH-2A instructions* — not the bit-manipulation ops, not
`clips`/`clipu`, not `mulr`, not TBR table-calls, not even the delay-slot-free
branch forms. Canonical source patterns compile to the classic SH-2 sequences
(`*REG |= 0x10` → `mov.b/or/mov.b`, a clamp → `cmp/bt/mov`, `a*b` →
`mul.l/sts macl`, an ops-struct call → `mov.l @r4,r0; jmp @r0`). This mirrors the
spec's own measurement that stock `-m2a` emits `movmu` once and `movml` never.
**Consequently every candidate's benefit is *latent*: it requires GCC backend
work to realize.** The bar for adoption is therefore "is the latent payoff large
enough to justify both the RTL *and* the compiler work?" — and for almost all of
these it is not.

---

## 2. Recommended for adoption — delay-slot-free branches

### 2.1 `jsr/n`, `rts/n`, `rtv/n`

| Mnemonic | Encoding | Operation |
|---|---|---|
| `jsr/n @Rm`  | `0100mmmm01001011` | `PR = PC+2; PC = Rm` — **no delay slot** |
| `rts/n`      | `0000000001101011` | `PC = PR` — no delay slot |
| `rtv/n Rm`   | `0000mmmm01111011` | `R0 = Rm; PC = PR` — return + value move, no delay slot |

All collision-free in J32 (byte-identical SH-2A; same IP-clearance bundle as
`movi20`, see [`spec.md`](spec.md) §1.4).

**Why this one is worth it.** SH's delayed branches force a `NOP` into the delay
slot whenever the scheduler can't fill it, costing 2 bytes. Measured on CSiBE:

| Delayed branch | total | unfilled (NOP) slot |
|---|---|---|
| `jsr` | 9,632 | **1,508** |
| `bra` | 8,421 | 1,766 |
| `rts` | 1,803 | **233** |
| `braf` | 379 | 133 |
| `jmp` | 343 | 52 |
| **all** | | **3,692 NOPs = 1.69 % of all instructions** |

`jsr/n` + `rts/n` + `rtv/n` address the `jsr` and `rts` NOPs: **1,741 slots =
0.80 % of instructions ≈ 3.5 KB ≈ ~0.4 % of `.text`** on CSiBE, more in
call-heavy code (BusyBox+musl left 6,386 unfilled *indirect-jsr* slots alone —
see `gcc-sh-monitor/docs/upstream-reports/peephole-delay-slot-jsr-fill.md`).
`rtv/n` additionally folds the common `mov Rm,r0; rts` return-value idiom.

**Why slot-*free* and not slot-*fill*.** The `gcc-sh-monitor` report above
showed that trying to *fill* the residual NOP slots with a peephole pass recovers
almost nothing (101 sites / 202 bytes) — `dbr_schedule` already fills 80.6 % of
indirect-call slots, and the leftovers are unfillable by construction. Slot-free
branches sidestep filling entirely and capture the whole residual. They are the
right tool for the NOP population the fill approach could not touch.

**The ceiling (and why `bra/n` is not here).** `bra` (1,766 NOPs) + `braf` (133)
+ `jmp` (52) — 52 % of the NOP population — have **no slot-free SH-2A variant**,
so ~47 % is the realistic ceiling. The encoding reason is in §3.5.

**Adoption cost.** RTL: a no-delay-slot branch variant in both the in-order and
OoO front-ends (the front-end must not fetch/execute a successor in the slot) —
well-understood, low-moderate. **Compiler: GCC does not emit the `/N` forms
today** (every `rts` in our probe had a delay slot). The needed change is a
backend pass that rewrites an unfilled-slot `jsr`/`rts` to its `/N` form — a
local, tractable rewrite, much easier than the idiom-recognition the rejected
candidates would need.

**Status: promoted (2026-05-30).** Now a full instruction definition in
[`spec.md`](spec.md) §3.5, with microarchitecture in
[`hardware-impl.md`](hardware-impl.md) §4A and the GCC `/N`-emission pass in
[`software-impl.md`](software-impl.md) §3.6. Prior art for delayed-vs-non-delayed
branch selection is ubiquitous pre-2006 (every RISC ISA); the encodings are
SH-2A's own. This section remains as the evaluation/measurement record behind that
decision.

---

## 3. Evaluated and rejected

Each entry: what it is, whether GCC emits it, the measured opportunity, and the
reject reason. All encodings below were verified collision-free in J32 — so any
of these *could* be added later; the reason they are not is **value**, not
feasibility.

### 3.1 Bit manipulation — `bset/bclr/bst/bld #imm3,Rn` and `b{set,clr,st,and,or,xor,…}.b #imm3,@(disp12,Rn)`

Single-bit set/clear/test on a register (16-bit) or a read-modify-write on a
memory byte (32-bit), with the bit position as a 3-bit immediate and **no GPR for
the mask**.

- **GCC emits them?** **No.** `*REG |= 0x10` compiles to
  `mov.b @r1,r0; or #16,r0; mov.b r0,@r1`; `x | (1<<3)` compiles to `or #8,r0`.
  Would need new `define_insn`s plus combine/peephole patterns.
- **Measured opportunity (CSiBE):** the memory RMW idiom (`bset.b`/`bclr.b`
  candidate: `mov.b @rX; or/and #imm; mov.b ,@rX`) appears **once** in the entire
  corpus. The register forms are worse than break-even: GCC already does
  `or #8,r0` in a single 2-byte instruction, so `bset #3,r0` saves zero bytes;
  the only theoretical win is a bit op on a *non-R0* register (SH's `and/or/xor
  #imm` are R0-only), which the allocator avoids by routing through R0 anyway.
- **Reject reason.** Near-zero benefit in general-purpose code, on top of needing
  both RTL and non-trivial compiler idiom-recognition. The genuine value —
  register pressure in **MMIO/driver bit-poking** (no GPR for value or mask) — is
  real but lives in bare-metal driver code that is not in J-core's measured
  corpus, and even there GCC would have to learn to emit it.
- **Extra hazard if ever revisited.** The `.b` memory forms are **non-atomic**
  read-modify-write. They are *not* a CAS.L substitute; on J2-MT2x2 / J32 SMP a
  `bset.b` to shared memory races. Any future adoption must scope them to
  device/single-owner memory and keep CAS.L for concurrency
  ([../glossary.md §6](../glossary.md)).
- Prior art (if revived): 8051 `SETB`/`CLR` (1980), 68000 `BSET`/`BCLR` (1979),
  x86 `BTS`/`BTR` (i386, 1985) — all pre-2006.

### 3.2 `clips.b/w`, `clipu.b/w` — saturating clip

In-place saturate of a register to signed/unsigned byte/word range, setting a new
`CS` (saturation) status bit.

- **GCC emits them?** **No.** The textbook clamp (`if (x>127) x=127; …`) compiles
  to `cmp/ge; bt; mov; cmp/gt; bf; mov`. ARM gets `SSAT`/`USAT` from such idioms
  via backend patterns; SH has none.
- **Measured opportunity:** ~0 in CSiBE. Saturation is concentrated in DSP /
  audio / video / codec code, which is not in the corpus or J-core's stated
  workload.
- **Reject reason.** Niche to media/DSP, needs compiler idiom-recognition, **and**
  introduces a new architectural `CS` status bit to save/restore. Not worth it
  absent a committed signal-processing workload.

### 3.3 `mulr R0,Rn` — in-place multiply (`R0 × Rn → Rn`)

- **GCC emits it?** **No.** `a*b` compiles to `mul.l r5,r4; sts macl,r0` (the
  result must be pulled out of MACL).
- **Value:** `mulr` writes the low 32 bits straight back to Rn, saving the
  `sts macl,Rn` (2 bytes) and avoiding MACL traffic — and MACL is shared state
  (also the SIMD integer-reduction target, [`../simd/spec.md`](../simd/spec.md)
  §2.3), so not clobbering it has marginal pressure value.
- **Reject reason — kept as a take-note, not adopted.** Implementation in J-core
  is genuinely cheap (the multiplier exists; `mulr` is just a writeback path to
  Rn). But the saving is one instruction per multiply-to-GPR and it still needs a
  GCC peephole to ever appear. **Noted as low-cost-if-ever-convenient**, not on
  the adoption path on its own.

### 3.4 TBR + `jsr/n @@(disp8,TBR)` — table-based call

`TBR` is a **dedicated control register** (accessed via `ldc Rm,TBR` /
`stc TBR,Rn`, *not* a GPR) holding the base of a function-pointer table.
`jsr/n @@(disp8,TBR)` is a **double-indirect call**: `PC = Read_32(TBR + disp*4)`
— read a pointer from table entry `disp` (0–255) and call it, in 2 bytes, using
no GPR.

- **Usable for C++ vtables?** **No.** A vtable is per-object — the vptr is loaded
  from the object, so each class's table is at a different address. TBR is a
  single global base; it cannot express per-object dispatch. Confirmed: a virtual
  call / ops-struct call compiles to `mov.l @r4,r0; jmp @r0`, never TBR.
- **Usable for C ops-structs (Linux-kernel `file_operations` style)?** **No** —
  same reason: `f->read` is a per-instance pointer, not a fixed-base table.
- **Compiler-reachable at all?** **No.** Even a literal `handlers[i](arg)` (array
  of function pointers at a fixed global address — the ideal TBR case) compiles to
  `mov.l .Lbase,r1; …@(r0,r1); jmp @r0`. GCC has no mechanism to bind a global
  table to TBR.
- **Could it free `r12` (GOT pointer) in PIC/fdPIC?** **No.** TBR's only consumer
  is the double-indirect *call*; it is **not** a data-load base (no
  `mov.l @(disp,TBR),Rn`) and not an arithmetic operand. So it cannot serve GOT
  *data* access (loading a data symbol address, or GOTOFF `r12 + gotoff`), which
  is what keeps `r12` reserved. At best it could accelerate the external-*call*
  path of a *non-fdPIC* PIC executable (`jsr/n @@(slot,TBR)` calling `GOT[slot]`),
  but you would keep the GOT base in both TBR *and* `r12` → no register saved.
  For **fdPIC** it fails outright: an fdPIC cross-module call must reload `r12`
  from the function descriptor's GOT word, and `jsr/n @@` does one load and jumps
  with no mechanism to reload `r12`.
- **Reject reason.** A control register with a real but narrow purpose — hardware
  acceleration for indexed dispatch through a *single global fixed* function
  table (heritage: Amiga library LVO jump tables and the Mac OS Toolbox A-trap
  table, both ~1984). Modern HLL dispatch is per-instance, so it is
  compiler-unreachable, and it cannot help the `r12`/GOT goal. Freeing `r12`
  would instead require GOT-base-relative *data* addressing (a new control
  register plus load/`lea` forms) — a far larger ISA commitment than the
  explicit-base `lea` already specced, and out of scope here.

### 3.5 `bra/n` — slot-free unconditional branch (does not exist; no room to add)

SH-2A added slot-free `jsr/n` and `rts/n` but **not** a slot-free `bra`. We
checked whether J32 could add one:

- **16-bit `bra/n` (full ±4 KB reach):** needs a complete free top nibble (as
  `bra`=`1010…`/`bsr`=`1011…` each consume one for their 12-bit displacement).
  **No top nibble is free** across the SH-2/2A/4 union. The only nibble free in
  the bare J32 column is `1111`, which is the **FPU block** on any FPU-bearing
  part (J32's baseline has the FPU), so it collides in practice. The free space
  in nibbles `0`/`4`/`8` is register-slot-shaped (scattered `0100nnnn…` holes),
  not a contiguous displacement field — a 11–12-bit `disp` cannot be carved from
  it.
- **32-bit `bra/n` (e.g. disp12):** 4 bytes = exactly `bra`(2 B) + `nop`(2 B), so
  **zero code-size win** on short branches, and a 12-bit displacement reaches only
  ±4 KB — the same as `bra` — so it cannot help far branches either.
- **A *wider*-reach 32-bit form (disp20)** could replace the far-branch sequence
  (`mov.l pool` + 4 B literal + `braf` + `nop` ≈ 10 B) with 4 B — but **far
  branches with NOPs are rare: 133 in all of CSiBE** (~0.1 % of `.text` even if
  perfectly captured). Too small to justify a dedicated 32-bit branch and its
  relaxation logic.
- **Reject reason.** No viable 16-bit encoding (the only form that would save
  bytes); the 32-bit forms either save nothing (disp12) or address a negligible
  population (disp20). This is *why* SH-2A itself only made the no-displacement
  branches (`jsr/n`/`rts/n`) slot-free. The `bra` half of the delay-slot NOP
  population (§2.1) is structurally unrecoverable via a slot-free branch.

### 3.6 Register banks — `ldbank @Rm,R0`, `stbank R0,@Rn`, `resbank`

Fast-interrupt register banking (save/restore a register set to/from a bank).

- **Reject reason.** Requires a banked register file — significant new
  architectural state and area, not a decode-level density add. A real feature to
  be considered on its own merits (interrupt-latency / ISR code size), out of
  scope for this density work.

### 3.7 `divs R0,Rn`, `divu R0,Rn` — single-instruction 32/32 quotient

`R[n] = R[n] / R[0]`. The biggest single code-size win available (replaces the
unrolled ~32-step `DIV1` sequence or a libgcc call).

- **GCC emits them?** **No** (and J2 currently divides via software `DIV1`
  stepping).
- **Reject reason.** Needs a divide functional unit, which the spec lists as an
  explicit non-goal ([`spec.md`](spec.md) §1.3). A middle path exists — microcode
  `DIVU/DIVS` as an internal multi-cycle loop over the *existing* `DIV1` datapath
  (held like `MAC` via `mac_busy`), capturing the code-size/register-pressure win
  without a new fast divider — but that runs into the same operand-driven
  iteration the in-order sequencer lacks ([`hardware-impl.md`](hardware-impl.md)
  §2 / §5.4), i.e. the `movmu` sequencing problem. Worth a deliberate decision
  later; not a free density add.

### 3.8 Reverse auto-update moves — `mov.{b,w,l} @-Rm,R0`, `mov.{b,w,l} R0,@Rn+`

Pre-decrement *load* and post-increment *store* (the mirror of SH's existing
post-inc load / pre-dec store), restricted to R0.

- **Reject reason.** Marginal. Enables a few descending-stack / ascending-queue
  idioms the normal `@Rm+` / `@-Rn` pair cannot, but R0-only and narrow benefit;
  GCC would rarely have cause to emit them. Low priority.

---

## 4. Summary

| Candidate | GCC emits? | Measured benefit (CSiBE) | Cost | Decision |
|---|---|---|---|---|
| `jsr/n`/`rts/n`/`rtv/n` | no | ~0.8 % insns (~0.4 % .text) | RTL + tractable GCC pass | **adopted — spec §3.5** |
| bit-manip (reg + mem) | no | 1 MMIO site; reg forms break-even | RTL + idiom patterns | reject (driver-only) |
| `clips`/`clipu` | no | ~0 | RTL + patterns + new `CS` bit | reject (DSP-only) |
| `mulr` | no | marginal | **cheap RTL** + peephole | note only |
| TBR `jsr/n @@(disp,TBR)` | no | 0 (unreachable) | control reg + state | reject (not compiler-reachable; no `r12` help) |
| `bra/n` | n/a | 0 (no encoding / no win) | — | reject (no room; 32-bit saves nothing) |
| register banks | no | — | banked regfile | reject (separate feature) |
| `divs`/`divu` | no | large *if* emitted | divider / DIV1-loop | defer (needs FU) |
| reverse auto-update mov | no | marginal | low | reject (low value) |

**One-line takeaway:** of all SH-2A instructions beyond `movi20`/`lea`, only the
delay-slot-free branches have a real, measured, general-code payoff — and even
they cap at ~47 % of the NOP population because there is no slot-free `bra`.
Everything else is either latent-and-niche (bit-manip, `clips`), unreachable by
the compiler (TBR), structurally impossible to encode for a win (`bra/n`), or a
separate functional-unit/state feature (`divs`/`divu`, register banks).

## Document status

Design record. Numbers measured 2026-05-30 against CSiBE with the
`--with-cpu=m2a` GCC 14.2 in `gcc-sh-monitor`. Encodings verified collision-free
against `docs/insns.json`. The single recommendation (delay-slot-free branches,
§2) has been **promoted** to a full instruction definition — [`spec.md`](spec.md)
§3.5, [`hardware-impl.md`](hardware-impl.md) §4A,
[`software-impl.md`](software-impl.md) §3.6 (2026-05-30). This document remains
the evaluation record for that decision and for the rejected candidates.
