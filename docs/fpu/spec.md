# J-Core FPU — Specification (tiered, SH-4-complete)

**Status:** Draft, v1.0 (2026-05-25)
**Scope:** Architectural and microarchitectural specification of the
J-Core scalar floating-point unit, organised in three tiers that map
1:1 to the product points defined in [../glossary.md §3](../glossary.md).
**Audience:** RTL implementers (jcore-cpu, jcore-soc), toolchain
maintainers (gcc, llvm, qemu), kernel/hypervisor engineers, conformance
testers.
**Supersedes:** `docs/fpu/archive/j2-spec.md` (J2-only draft, v0.4,
preserved verbatim in the archive directory). All Tier 0 content in
this document is a faithful recast of the J2 baseline FPU spec; the
Tier 0 hardware decisions and protocol mechanics are unchanged. Tier 1
and Tier 2 are new in this revision.
**ISA reference:** SH-4 FPU (Renesas/Hitachi SH-4 **Programming** Manual,
Rev. 5.0, ADE-602-156D, 2001) and SH-4A FPU (REJ09B0003-0150Z, 2004).
*`ADE-602-156D` is the Programming Manual; this document previously called it
the "Software Manual", which is a different Renesas publication
(`REJ09B0318-0600`, Rev. 6.00) whose content for the sections cited here is
identical but which is dated 2006 and so cannot serve as prior art.*
**Cross-references:**
- [../glossary.md](../glossary.md) — product naming, prior-art policy.
- [../platform-baseline.md §2](../platform-baseline.md) — byte order (the
  glossary no longer carries it).
- [../jcore-ulx3s-service-plan.md §6.7](../jcore-ulx3s-service-plan.md)
  — Phase 7 deployment that requires Tier 1 (SH-4-complete) FPU.
- [../simd/spec.md](../simd/spec.md) §2.1, §2.3 — Tier 0 SIMD
  reductions write into the scalar FPU register file and therefore
  require at least the Tier 1 FPU register file on any product that
  enables SIMD.
- [../ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md) §3–§5 — the OoO core
  that hosts the Tier 1 FPU as a coprocessor.
- [../hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md)
  §2.3, §4.3 — `EXC_FPU_DISABLED` cause code and HEDR delegation
  bitmap that drives the Tier 2 lazy FPU context-switch ABI.

---

## Table of contents

1. Scope, tier model, and decision principles
2. Architectural choices common to all tiers
3. Coprocessor protocol (Tier 0, inherited by Tier 1/2)
4. Programmer's model — register file, FPUL, FPSCR
5. Tier 0 — J2 baseline FPU instruction set
6. Tier 1 — SH-4-complete FPU
   - 6.1 Overview and product applicability
   - 6.2 Endianness migration (BE → LE) — withdrawn, kept as analysis
   - 6.3 SR.FD trap semantics
   - 6.3.1 Kernel-mode use of the FPU — the `kernel_fpu` discipline
   - 6.4 Full FPSCR layout (PR / SZ / FR / DN / RM / Cause / Enable /
     Flag)
   - 6.5 FRCHG, FSCHG, FPCHG (FPSCR-toggle instructions)
   - 6.6 FIPR (4-element single-precision dot product)
   - 6.7 FTRV (4×4 matrix × 4-vector multiply)
   - 6.8 FSCA (sin/cos table approximation)
   - 6.9 FSRRA (reciprocal square root approximation)
   - 6.10 Coprocessor protocol extension for vector beats
   - 6.11 Implementer latency hints
7. Tier 2 — Hypervisor-aware FPU
   - 7.1 EXC_FPU_DISABLED cause and HEDR interaction
   - 7.2 Per-vCPU FPU-ownership flag
   - 7.3 Lazy FPU context-switch ABI
   - 7.4 Save / restore sequence (136-byte FPU image)
   - 7.5 Trap-handler register-window convention (HSPC / HSSR)
   - 7.6 Migration and live-migration corner cases
   - 7.7 Cross-tenant FP ownership: eager switch, dirty tracking, scrub
8. IEEE-754 conformance target (per tier)
9. Test plan summary
10. Open questions / TBDs
11. Revision history
12. Appendix A — Prior art per mechanism
13. Appendix B — Cross-tier instruction matrix
14. Appendix C — SH-4 reference catalogue

---

## 1. Scope, tier model, and decision principles

### 1.1 Tier model (organising principle)

This specification is organised in **three tiers**. Every instruction,
every register-bit description, every protocol section in this
document is tagged with the tier that introduces it. Lower tiers are a
strict subset of higher tiers — Tier 1 is a superset of Tier 0;
Tier 2 is a superset of Tier 1. A product point ships exactly one
tier; the tier ladder corresponds 1:1 to the product table in
[../glossary.md §3](../glossary.md).

**Tier 0 — J2 baseline FPU. [T0]**

The J2 FPU that ships today. A subset of the SH-4 scalar FPU
instruction set:

- Data movement: FMOV / FMOV.S in all addressing modes, FLDI0/FLDI1,
  FLDS/FSTS, LDS/STS for FPUL and FPSCR.
- Single-precision arithmetic: FADD, FSUB, FMUL, FDIV, FMAC, FSQRT,
  FNEG, FABS.
- Comparison: FCMP/EQ, FCMP/GT.
- Conversion: FLOAT, FTRC, FCNVSD, FCNVDS.
- Double-precision (Tier 0 supports SH-4 double, except FMAC, with
  the same set as single-precision arithmetic above).
- Bank/size toggles: FRCHG, FSCHG.

Excluded from Tier 0:

- The compound SH-4 instructions FIPR, FTRV, FSCA, FSRRA, and FPCHG.
- SR.FD (FPU-disable) trap.
- MMU interaction (J2 is no-MMU).
- Hypervisor-mediated FPU context switching.

All tiers are big-endian, per
[platform-baseline.md §2](../platform-baseline.md). This paragraph
previously said the baseline became little-endian from Tier 1 onward; see
§2.3.

**Tier 1 — SH-4-complete FPU. [T1]**

The full SH-4 scalar FPU instruction set. Adds, over Tier 0:

- **FIPR** — 4-element single-precision dot product.
- **FTRV** — 4×4 matrix × 4-vector multiply against the XMTRX
  back-bank alias (single precision only).
- **FSCA** — sin/cos table-driven approximation.
- **FSRRA** — reciprocal-square-root table-driven approximation.
- **FRCHG / FSCHG / FPCHG** — FPSCR.FR / FPSCR.SZ / FPSCR.PR toggle
  instructions. (FRCHG and FSCHG already appear in Tier 0; FPCHG is
  the SH-4A addition.)
- **SR.FD** trap semantics. Any FPU instruction (compute, transfer,
  or FPSCR control) issued with SR.FD = 1 raises an FPU-disabled
  exception.
- **Full FPSCR layout**: PR, SZ, FR, DN, RM, plus the IEEE-754
  Cause / Enable / Flag fields as defined by the SH-4 hardware
  manual.

Tier 1 is **required** for J32, J32-OOO, J32-FM, and J64 per the
glossary product table.

Tier 1 is also **required by Tier 0 SIMD horizontal reductions** per
[../simd/spec.md §2.1, §2.3](../simd/spec.md): SIMDH reductions write
their scalar result into FR0 / DR0 / FPUL, which are Tier 1 FPU
register-file resources. An implementation that wants Tier 0 SIMD
must therefore implement at least the Tier 1 FPU register file
(FR0..FR15, FPUL) and the scalar FPU instructions that consume it.

**Tier 2 — Hypervisor-aware FPU. [T2]**

A small but critical extension on top of Tier 1, required for the
hypervisor-capable product point J32-FM. Adds:

- **EXC_FPU_DISABLED** as a first-class cause code in HEDR
  ([../hypervisor/hardware-spec.md §2.3, §4.3](../hypervisor/hardware-spec.md)).
  The Tier 1 SR.FD trap, when raised on a vCPU running under a
  hypervisor, is reported via this dedicated cause so the hypervisor
  can distinguish a guest-internal FD trap from any other
  illegal-instruction class trap.
- **Per-vCPU FPU-ownership flag** maintained in the hypervisor's
  vCPU control block.
- **Lazy FPU context-switch ABI**: trap-on-first-use after vCPU
  dispatch, hypervisor saves the previous owner's FPU image and
  restores the current vCPU's FPU image using standard Tier 0 / Tier
  1 FMOV.S sequences, then resumes the guest at the trapping
  instruction.
- **136-byte FPU image** (16 × FR + 16 × XF + FPUL + FPSCR) saved /
  restored on context switch.

Tier 2 is **required** for J32-FM and J64. It is **optional** for
non-virtualised use of the same silicon; the hardware mechanism
collapses to a Tier-1 SR.FD trap when the hypervisor is absent (i.e.
SR.HPRIV is never set).

### 1.2 Tier-tagging convention

Throughout this document, every instruction box, every register-bit
description, and every section header carries an explicit tier tag in
square brackets: **[T0]**, **[T1]**, or **[T2]**. The tag indicates
the *lowest* tier that mandates the feature. Higher tiers inherit
without restatement.

When a feature changes semantics across tiers, both tier tags appear and
the migration is called out explicitly. Endianness used to be this
document's worked example of that; it is not one any more (§2.3), and no
replacement example is invented here — the rule stands without one.

### 1.3 Decision principles (inherited from j2-spec.md v0.4)

These principles are tie-breakers when multiple designs would work.
They are reproduced from the archived J2 spec because Tier 0
implementation choices made under them remain load-bearing for Tier 1
and Tier 2:

1. **Minimum diff against the existing j-core codebase.** When two
   designs are roughly equivalent on technical merits, prefer the one
   that touches the fewest existing files. Concretely: Tier 0 copies
   the `mac_busy` pattern for FPU back-pressure (§3.6) rather than
   resurrecting the dormant `cop_i.ack` path. Tier 1 extends the same
   beat-sequencing mechanism for FIPR / FTRV / FSCA / FSRRA rather
   than introducing a separate vector-coprocessor protocol.
2. **Reuse the project's idioms.** New execution units look like
   `mult`: a black-box block with its own `_pkg.vhd`, its own
   `_tap.vhd` testbench, its own busy signal feeding the decoder.
3. **Greenfield work is exempt** from the minimum-diff principle but
   inherits the reuse-idioms principle.
4. **Dormant signals stay dormant.** `cop_i.ack` and `cop_i.exc`
   remain unconsumed; FPU back-pressure and exceptions travel through
   paths we add in §3.6 and §3.8.
5. **Binary compatibility with SH-4 is the strict bar for the FPU at
   Tier 1.** Code compiled by `sh-elf-gcc -m4` or `-m4-single`
   against the SH-4 FPU model must run on a Tier 1 J-Core FPU and
   produce architecturally identical results. Where the SH-4
   Software Manual is ambiguous or implementation-defined, qemu's
   post-2017 `target/sh4` is the tiebreaker reference (Appendix C).
   **Open: the tiebreaker names no version.** An oracle that moves is
   not an oracle — two engineers consulting "post-2017 qemu" in
   different years can get different answers, which is the drift the
   fact-ownership work exists to remove. A specific qemu tag must be
   cited here. The tiebreaker's *scope* is settled and is the CPU
   surface only: [../sh4-guest-model.md §6](../sh4-guest-model.md),
   which also records that qemu is a conformance oracle rather than
   prior art, so the pre-2006 policy does not reach it.

### 1.4 In scope / out of scope

**In scope (this revision):**

- A synthesizable VHDL FPU block, parameterizable per tier, that
  hangs off the existing J2 `cop_o`/`cop_i` port pair (Tier 0) and
  the OoO core's coprocessor interface (Tier 1, Tier 2). See
  [../ooo/j32ooo-spec.md §3–§5](../ooo/j32ooo-spec.md) for the host
  pipeline.
- The full SH-4 FPU programmer-visible state (Tier 1): 32
  single-precision FRs (with bank, 16 active + 16 XF back), DR
  aliasing, FV vector aliases, XMTRX alias, FPUL, FPSCR with full
  layout.
- The full SH-4 FPU instruction set up to and including SH-4A's
  FPCHG (Tier 1).
- The Tier 2 lazy-FPU-context-switch ABI for the J-Core hypervisor.

**Out of scope (this revision):**

- Any change to the J2 base ISA, pipeline, register file, or memory
  bus beyond what Tier 0 already requires.
- IEEE 754-2008 fused multiply-add semantics for FMAC. SH-4 FMAC is
  non-fused (rounds twice). We follow SH-4 at every tier.
- Hardware multi-precision (>binary64). Software emulation only.
- Vector instruction set beyond FIPR / FTRV (these are SH-4's
  legacy 4-element vector facility, orthogonal to the SIMD
  specification in [../simd/spec.md](../simd/spec.md)).

### 1.5 Non-goals

- Bit-exact SH-4 cycle counts at any tier.
- Bit-exact match of FSCA / FSRRA accuracy across silicon vendors
  for Tier 1 (the SH-4 manual specifies bounds; we meet the bounds,
  not necessarily the same table values; see §6.8 and §6.9).
- Cross-product compatibility for FRCHG / FSCHG with FPSCR.PR=1
  ("setting prohibited" per SH-4 manual); we follow qemu (silent
  toggle).

---

## 2. Architectural choices common to all tiers

### 2.1 FPU is a coprocessor block

At every tier the FPU is a separate VHDL block instantiated alongside
`u_mult` and `u_datapath` inside the host CPU's `cpu.vhd`. The CPU has
no direct read or write port into FPU registers; every transfer
crosses the coprocessor protocol.

- **Tier 0 host:** J2 `cpu.vhd` with the existing `cop_o_t` /
  `cop_i_t` records (§3.1).
- **Tier 1 host:** J32 in-order core or J32-OOO out-of-order core.
  The OoO core treats the FPU as a one-issue-per-cycle coprocessor
  per [../ooo/j32ooo-spec.md §5](../ooo/j32ooo-spec.md). The wire
  protocol is unchanged from Tier 0; only the beat menu grows
  (§6.10).
- **Tier 2 host:** any Tier 1 host where the surrounding system also
  implements the hypervisor extension of
  [../hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md).
  No additional wires on the FPU side; the SR.FD trap path and the
  HEDR delegation logic live in the CPU.

### 2.2 Tier-parameterised RTL

The FPU's VHDL top-level takes a `TIER` generic (or three boolean
generics `FPU_T1`, `FPU_T2`). At synthesis time, Tier-1-only
arithmetic blocks (FIPR adder tree, FTRV matrix multiplier, FSCA /
FSRRA ROMs) are removed when `FPU_T1 = false`. Tier-2-only logic is a
handful of LUTs in the CPU's trap path and adds no FPU-internal
state.

### 2.3 Endianness baseline

> **SUPERSEDED BY [../platform-baseline.md §2](../platform-baseline.md) — 2026-09-07.**
> This section previously read that the product line is little-endian from
> J2 onward and that Tier 1 and Tier 2 are little-endian. J-Core is
> **big-endian at every product point**; there is no migration.
> [decisions/0006](../decisions/0006-endianness-is-big-endian.md) is the
> decision and §6.2 below is the retained record of what it withdrew.

**All tiers are big-endian**, because the platform is
([platform-baseline.md §2](../platform-baseline.md)). Nothing in this
document's tier structure varies with byte order any more: the archived
j2-spec.md §3.7 big-endian double-`FMOV` handling is the handling at
Tier 0, Tier 1 and Tier 2 alike.

The reason the previous text is void rather than merely outvoted is worth
one line, because it is a citation failure and not a taste difference: it
derived a normative migration from the glossary's product table, which
[decisions/0001](../decisions/0001-one-authority-per-fact.md) found had
never been true on that column, and invoked a "single source of truth"
rule that the same record deleted. See
[decisions/0006 §Why the FPU spec's argument does not survive](../decisions/0006-endianness-is-big-endian.md).

### 2.4 Prior-art posture

Every FPU mechanism specified here has pre-2006 published prior art.
The dominant source is the SH-4 hardware manual itself (Renesas /
Hitachi, 2001), which predates 2006 and whose patents have expired.
Other sources used: IEEE-754 (1985), 4.4BSD Operating System
(McKusick et al., 1996) for the lazy-FPU ABI, MIPS R4000 user manual
(1991) for the trap-on-first-use idiom, the UltraSPARC II Programmer
Reference Manual (1997) for an alternative lazy-FPU model that we
cross-checked against. The full per-mechanism table is in
Appendix A.

---

## 3. Coprocessor protocol (Tier 0, inherited by Tier 1/2)

This section is reproduced from the archived j2-spec.md §3 with light
edits for tier tagging. The wire-level protocol does not change
between tiers; Tier 1 only enlarges the menu of `op` micro-codes and
adds longer multi-beat sequences for vector instructions (§6.10).

### 3.1 Wire-level (unchanged at every tier). [T0]

From `cpu2j0_pkg.vhd`:

```vhdl
type cop_o_t is record
  d       : std_logic_vector(31 downto 0);  -- CPU -> coproc data beat
  rna     : std_logic_vector( 3 downto 0);  -- A-side register selector
  rnb     : std_logic_vector( 3 downto 0);  -- B-side register selector
  op      : std_logic_vector( 4 downto 0);  -- micro-op
  en      : std_logic;                       -- valid pulse
  stallcp : std_logic;                       -- CPU stalls coproc next cycle
end record;

type cop_i_t is record
  d   : std_logic_vector(31 downto 0);      -- coproc -> CPU data beat
  ack : std_logic;                          -- coproc accepted / produced
  t   : std_logic;                          -- T-flag result (for fcmp)
  exc : std_logic;                          -- exception sticky
end record;
```

The same record shapes carry Tier 1 traffic. FIPR's four-operand-wide
nature is expressed as a sequence of register-addressed beats over
the existing `rna`/`rnb` 4-bit fields, not as a wider wire.

### 3.2 Beat model. [T0]

Each FPU instruction is a fixed sequence of pipeline slots, one per
beat, emitted by the decoder as a series of microcode rows. The
decoder knows the row count for each opcode; it is not negotiated on
the wire.

- **CPU-driven beat:** `cop_o.en='1'` for one cycle.
- **FPU-driven beat:** the FPU drives `cop_i.{d,t}` combinationally;
  the CPU latches the result in the same cycle.

Wait-states come from the multi-cycle-mult-style stall (§3.6). The
CPU's `cop_o.stallcp` (already `not slot_o`) continues to freeze
internal FPU state during pipeline stalls.

`cop_i.ack` is not used to delimit beats and is not driven by the
FPU at any tier (§1.3 principle 4).

### 3.3 Operand widths and beat counts. [T0/T1]

| Class                              | CPU→FPU beats | FPU→CPU beats | Examples                 | Tier |
| ---------------------------------- | ------------- | ------------- | ------------------------ | ---- |
| Single, reg-reg                    | 0             | 0             | FADD (PR=0), FNEG        | T0   |
| Single, immediate-form             | 0             | 0             | FLDI0, FLDI1             | T0   |
| Single, FPUL→FR or FR→FPUL         | 1             | 1             | FLDS, FSTS               | T0   |
| Single load from memory            | 1             | 0             | FMOV.S @Rm,FRn           | T0   |
| Single store to memory             | 0             | 1             | FMOV.S FRm,@Rn           | T0   |
| Single compare                     | 0             | 0 (T only)    | FCMP/EQ, FCMP/GT         | T0   |
| Double, reg-reg                    | 0             | 0             | FADD (PR=1)              | T0   |
| Double load from memory            | 2             | 0             | FMOV @Rm,DRn (SZ=1)      | T0   |
| Double store to memory             | 0             | 2             | FMOV DRm,@Rn (SZ=1)      | T0   |
| FPSCR read/write                   | 0/1           | 1/0           | STS FPSCR,Rn / LDS …     | T0   |
| FPUL read/write                    | 0/1           | 1/0           | STS FPUL,Rn / LDS …      | T0   |
| Vector dot-product (FIPR)          | 0             | 0             | FIPR FVm,FVn             | T1   |
| Matrix-vector multiply (FTRV)      | 0             | 0             | FTRV XMTRX,FVn           | T1   |
| Table-driven approximation (FSCA)  | 0             | 0             | FSCA FPUL,DRn            | T1   |
| Table-driven approximation (FSRRA) | 0             | 0             | FSRRA FRn                | T1   |
| FPSCR-bit toggle (FRCHG/FSCHG)     | 0             | 0             | FRCHG / FSCHG / FPCHG    | T0/T1|

Vector and matrix operands are read from the FPU's internal register
file, addressed by `rna`/`rnb` over multiple internal cycles; no
extra CPU-side beats are needed.

### 3.4 Micro-op encoding (`cop_o.op`, 5 bits). [T0/T1]

The Tier 0 allocation (from j2-spec.md §3.4) consumes encodings
0–22. Tier 1 extends into the reserved range:

| Encoding | Mnemonic     | Meaning                                                | Tier |
| -------- | ------------ | ------------------------------------------------------ | ---- |
| 0        | NOP          | no FPU action                                          | T0   |
| 1        | LDS          | load FPUL/FPSCR from CPU bus                           | T0   |
| 2        | STS          | store FPUL/FPSCR to CPU bus                            | T0   |
| 3        | CLDS         | conditional LDS                                        | T0   |
| 4        | CSTS         | conditional STS                                        | T0   |
| 5        | FOP_ADD      | floating add (PR-dependent precision)                  | T0   |
| 6        | FOP_SUB      | floating subtract                                      | T0   |
| 7        | FOP_MUL      | floating multiply                                      | T0   |
| 8        | FOP_DIV      | floating divide                                        | T0   |
| 9        | FOP_SQRT     | floating square root                                   | T0   |
| 10       | FOP_MAC      | floating multiply-accumulate (non-fused)               | T0   |
| 11       | FOP_CMP_EQ   | floating compare-equal, drives `cop_i.t`               | T0   |
| 12       | FOP_CMP_GT   | floating compare-greater, drives `cop_i.t`             | T0   |
| 13       | FOP_NEG      | floating negate                                        | T0   |
| 14       | FOP_ABS      | floating absolute value                                | T0   |
| 15       | FOP_FLOAT    | int→float, FPUL→FRn                                    | T0   |
| 16       | FOP_TRC      | float→int truncate, FRm→FPUL                           | T0   |
| 17       | FOP_CNV_SD   | single→double precision conversion                     | T0   |
| 18       | FOP_CNV_DS   | double→single precision conversion                     | T0   |
| 19       | FOP_MEM_W    | memory write beat: CPU drives `cop_o.d` into FR/DR     | T0   |
| 20       | FOP_MEM_R    | memory read beat: FPU drives `cop_i.d` from FR/DR      | T0   |
| 21       | FOP_FLDI     | load immediate (0.0 if rnb=0, 1.0 if rnb=1) into FRn   | T0   |
| 22       | FOP_CTRL     | FRCHG / FSCHG / FPCHG (encoded in rna)                 | T0/T1|
| 23       | FOP_FIPR     | 4-element single-precision dot product                 | T1   |
| 24       | FOP_FTRV     | 4×4 matrix × 4-vector multiply                         | T1   |
| 25       | FOP_FSCA     | sin/cos table approximation                            | T1   |
| 26       | FOP_FSRRA    | reciprocal-square-root table approximation             | T1   |
| 27–31    | *reserved*   | for future SH-4A compound ops and SoC-specific use     | —    |

`FOP_CTRL` is shared between Tier 0 (FRCHG, FSCHG) and Tier 1 (the
additional FPCHG); the `rna` field disambiguates:
- `rna = 0` → FRCHG (toggle FPSCR.FR), Tier 0
- `rna = 1` → FSCHG (toggle FPSCR.SZ), Tier 0
- `rna = 2` → FPCHG (toggle FPSCR.PR), Tier 1 (SH-4A addition)
- `rna = 3..15` → reserved

### 3.5 Handshake examples

Tier 0 handshake examples (FADD, FCMP/EQ, FMOV.S load, FMOV.S store,
FADD double, FMOV @Rm,DRn load) are reproduced unchanged from
j2-spec.md §3.5 and not repeated here. Tier 1 vector handshakes are
in §6.10.

### 3.6 Back-pressure (`fpu_o.busy`). [T0/T1/T2]

The mac_busy-style mechanism (j2-spec.md §3.6) carries unchanged at
every tier. The FPU exposes `fpu_o.busy : std_logic`; the decoder
stalls the pipeline while it is asserted. Tier 1 operations are
longer (FIPR / FTRV multi-cycle; FSCA / FSRRA table-lookup-pipelined
in 3–7 cycles depending on the implementation; see §6.11) so the
busy window is larger, but the wire-level mechanism is identical.

### 3.7 Endianness in the coprocessor protocol. [T0/T1]

The wire protocol is endian-neutral: `cop_o.d` and `cop_i.d` carry
32-bit words, not byte arrays. Endianness only matters where words
are stitched into 64-bit doubles for FMOV, and there it is the archived
j2-spec.md §3.7 big-endian handling at every tier
([platform-baseline.md §2](../platform-baseline.md)). §6.2 records the
little-endian treatment this document used to mandate and no longer does.

### 3.8 Exception signalling. [T0/T1/T2]

The precise-exception mechanism inherited from j2-spec.md §3.8:

1. The FPU does not commit architectural state until it is ready to
   either signal completion or raise an exception, in the same cycle.
2. `fpu_o.exc` is OR'd into the existing `illegal_instr` line at the
   decode level.
3. The CPU's existing precise illegal-instruction trap path saves
   the PC of the offending FPU instruction.

**Tier 1 additions:**

- The SR.FD trap (§6.3) is also routed through `fpu_o.exc`, with a
  dedicated cause bit so the trap handler can distinguish it from
  IEEE-754 exceptions and from the Cause.E escape. In a Tier 1
  implementation without a hypervisor, this surfaces as the regular
  SH-4 "FPU disable" exception (EXPEVT 0x800 for non-slot, 0x820 for
  slot) on architectures that expose the SH-4 vector layout, or as
  the illegal-instruction collapse path on J2-style implementations
  (the choice is the host CPU's, not the FPU's).
- FIPR / FTRV exceptions are raised at the same precise-exception
  granularity as their scalar counterparts: the offending vector
  instruction's PC is reported, and none of its component lanes
  commit results.

**Tier 2 additions:**

- The SR.FD trap, when raised on a vCPU that is running under the
  hypervisor (i.e. HEDR consultation applies), is delivered with
  cause `EXC_FPU_DISABLED` (see §7.1 and
  [../hypervisor/hardware-spec.md §2.3](../hypervisor/hardware-spec.md)).
  HEDR's bit for `EXC_FPU_DISABLED` decides whether the trap is
  delegated to the guest's supervisor handler (typical for a guest
  with its own SR.FD policy, e.g. a nested Linux) or kept in the
  hypervisor (typical for the lazy-FPU-context-switch ABI).

---

## 4. Programmer's model — register file, FPUL, FPSCR

### 4.1 Register file. [T0/T1]

**Tier 0:**

- 32 single-precision FRs, organised as two banks of 16: FR0–FR15
  (front bank) and XF0–XF15 (back bank), selected by FPSCR.FR.
- When FPSCR.PR=1, FR0/2/4/.../14 are paired into DR0/2/4/.../14.
- When FPSCR.SZ=1, FMOV transfers pairs of FRs as 64-bit operations.
- FV0/4/8/12 and XMTRX are name-only aliases over the same storage.
- Physical implementation: a 32×32 flop array with three read ports
  and two write ports; bank selection multiplexes addresses.

**Tier 1 additions:**

- FV0/4/8/12 become functionally live (FIPR, FTRV consume them).
- XMTRX (the XF back bank viewed as a 4×4 matrix) becomes
  functionally live as the input to FTRV.
- Read-port count rises to accommodate FIPR's four single-precision
  operand reads in close succession and FTRV's four-source per cycle
  matrix-vector pipeline. Implementations may either widen the
  regfile to 4 read ports or sequence FIPR / FTRV over multiple
  cycles using the existing 3 read ports plus a small staging
  buffer; this is implementer's choice with no architectural impact.

**Tier 2 additions:** none. The register file is unchanged from
Tier 1; the Tier 2 mechanism only adds save / restore-driven traffic
through the existing memory-load and memory-store beats (§7.4).

### 4.2 DR / FV / XMTRX layout. [T0/T1]

| Alias  | Backing FRs                                    | Size           | Tier |
| ------ | ---------------------------------------------- | -------------- | ---- |
| DRn    | {FRn, FR(n+1)}, n even                         | 64-bit double  | T0   |
| FVn    | {FRn, FR(n+1), FR(n+2), FR(n+3)}, n ∈ {0,4,8,12} | 4 × FP32     | T1   |
| XMTRX  | XF0..XF15 viewed as 4×4 row-major matrix       | 16 × FP32      | T1   |

**Layout of DRn** in memory (big-endian at every tier —
[platform-baseline.md §2](../platform-baseline.md)):

- FRn holds the **high** 32 bits of the IEEE-754 binary64 value (sign,
  biased exponent, mantissa high 20 bits); FR(n+1) holds the **low** 32
  bits.
- Memory layout: FRn at the lower address, FR(n+1) at the higher
  address — i.e. high word first in memory, which is what big-endian
  IEEE-754 binary64 requires.

This is the archived j2-spec.md §3.7 layout, unchanged. The paragraph
here previously said the inverse and called the change "unavoidable"; the
inversion was a consequence of the little-endian migration §6.2 records
and withdraws, not of anything about IEEE-754.

**Layout of FVn:** FVn = (FRn, FR(n+1), FR(n+2), FR(n+3)). FIPR
treats FVn as a column vector. FTRV treats the XMTRX back bank as a
4×4 matrix `M[row][col] = XF(row*4 + col)` per the SH-4 manual.

**Layout of XMTRX:** the SH-4 manual defines

```
XMTRX = | XF0  XF4  XF8   XF12 |
        | XF1  XF5  XF9   XF13 |
        | XF2  XF6  XF10  XF14 |
        | XF3  XF7  XF11  XF15 |
```

i.e. column-major. FTRV multiplies XMTRX × FVn → FVn (in place). See
§6.7 for the full semantics.

### 4.3 FPUL. [T0]

32-bit register; conduit between integer registers and the FPU.

- `LDS Rn, FPUL` — CPU writes Rn into FPUL.
- `STS FPUL, Rn` — CPU reads FPUL into Rn.
- `FLDS FRm, FPUL` — internal FPU move, FRm → FPUL.
- `FSTS FPUL, FRn` — internal FPU move, FPUL → FRn.
- `FLOAT FPUL, FRn` — int32 → single-precision (Tier 0) or →
  double-precision DRn (Tier 0, FPSCR.PR=1).
- `FTRC FRm, FPUL` — float → int32, round-toward-zero.
- `FSCA FPUL, DRn` (Tier 1, §6.8) reads FPUL as a 16.16 angle.
- `FCNVSD FPUL, DRn` / `FCNVDS DRm, FPUL` precision conversions
  (Tier 0).

### 4.4 FPSCR — Tier 0 view. [T0]

Tier 0 implementations require only the subset of FPSCR fields used
by Tier 0 instructions: PR, SZ, FR, DN, RM, plus the Cause / Enable /
Flag fields used for the IEEE-754 trap model. The j2-spec.md §4.3
layout is preserved verbatim and shown in §6.4 as the Tier 1 layout
(the layouts are identical; Tier 1 differs only in adding the SR.FD
interaction and FPCHG).

### 4.5 Reserved and implementation-defined behaviours. [T0/T1]

The j2-spec.md §4.4 decisions carry forward:

- `FRCHG` and `FSCHG` toggle their target bit regardless of PR; the
  SH-4 manual says "setting prohibited" under PR=1 but we follow
  qemu (silent toggle).
- `FPCHG` (Tier 1, SH-4A) toggles FPSCR.PR; the same "setting
  prohibited" wording applies to combinations the manual reserves,
  and the same qemu-compatible silent-toggle rule applies.
- FPSCR.SZ=1 with FPSCR.PR=1 is "reserved" per SH-4; arithmetic
  results are implementation-defined; we do not trap.

---

## 5. Tier 0 — J2 baseline FPU instruction set

This section recasts j2-spec.md Tier A + Tier B + Tier C with
explicit T0 tagging on every entry. The encoding bit patterns, beat
counts, and SH-4 binary-compat notes are unchanged.

### 5.1 Tier 0 data movement (former Tier A). [T0]

| Mnemonic            | Encoding         | Beats (in/out) |
| ------------------- | ---------------- | -------------- |
| FMOV FRm, FRn       | 1111nnnnmmmm1100 | 0/0            |
| FMOV.S @Rm, FRn     | 1111nnnnmmmm1000 | 1/0            |
| FMOV.S FRm, @Rn     | 1111nnnnmmmm1010 | 0/1            |
| FMOV.S @Rm+, FRn    | 1111nnnnmmmm1001 | 1/0            |
| FMOV.S FRm, @-Rn    | 1111nnnnmmmm1011 | 0/1            |
| FMOV.S @(R0,Rm),FRn | 1111nnnnmmmm0110 | 1/0            |
| FMOV.S FRm,@(R0,Rn) | 1111nnnnmmmm0111 | 0/1            |
| FMOV DRm, DRn       | 1111nnn0mmm01100 | 0/0            |
| FMOV @Rm, DRn       | 1111nnn0mmmm1000 | 2/0            |
| FMOV DRm, @Rn       | 1111nnnnmmm01010 | 0/2            |
| FMOV @Rm+, DRn      | 1111nnn0mmmm1001 | 2/0            |
| FMOV DRm, @-Rn      | 1111nnnnmmm01011 | 0/2            |
| FLDI0 FRn           | 1111nnnn10001101 | 0/0            |
| FLDI1 FRn           | 1111nnnn10011101 | 0/0            |
| FLDS FRm, FPUL      | 1111mmmm00011101 | 0/0            |
| FSTS FPUL, FRn      | 1111nnnn00001101 | 0/0            |
| LDS Rm, FPUL        | 0100mmmm01011010 | 1/0            |
| STS FPUL, Rn        | 0000nnnn01011010 | 0/1            |
| LDS Rm, FPSCR       | 0100mmmm01101010 | 1/0            |
| STS FPSCR, Rn       | 0000nnnn01101010 | 0/1            |
| FRCHG               | 1111101111111101 | 0/0            |
| FSCHG               | 1111001111111101 | 0/0            |

### 5.2 Tier 0 single-precision arithmetic (former Tier B). [T0]

| Mnemonic           | Encoding         | Notes                                 |
| ------------------ | ---------------- | ------------------------------------- |
| FNEG FRn           | 1111nnnn01001101 | sign-bit flip only; no FPSCR update   |
| FABS FRn           | 1111nnnn01011101 | clear sign bit; no FPSCR update       |
| FCMP/EQ FRm, FRn   | 1111nnnnmmmm0100 | unordered → T=0, V flag set on NaN    |
| FCMP/GT FRm, FRn   | 1111nnnnmmmm0101 | unordered → T=0, V flag set on NaN    |
| FADD FRm, FRn      | 1111nnnnmmmm0000 |                                       |
| FSUB FRm, FRn      | 1111nnnnmmmm0001 |                                       |
| FMUL FRm, FRn      | 1111nnnnmmmm0010 |                                       |
| FDIV FRm, FRn      | 1111nnnnmmmm0011 |                                       |
| FSQRT FRn          | 1111nnnn01101101 |                                       |
| FMAC FR0,FRm,FRn   | 1111nnnnmmmm1110 | single-precision only; non-fused      |
| FLOAT FPUL, FRn    | 1111nnnn00101101 | int32 → float, exact for ≤24-bit ints |
| FTRC FRm, FPUL     | 1111mmmm00111101 | float → int32; see §5.4               |

### 5.3 Tier 0 double-precision (former Tier C). [T0]

Same arithmetic ops with PR=1 (except FMAC, see §5.5), plus
precision conversion:

| Mnemonic            | Encoding         | Notes                          |
| ------------------- | ---------------- | ------------------------------ |
| FCNVDS DRm, FPUL    | 1111mmm010111101 | double → single, result→FPUL   |
| FCNVSD FPUL, DRn    | 1111nnn010101101 | single (from FPUL) → double    |

### 5.4 FTRC binary-compat notes. [T0]

(Identical to j2-spec.md §5.1.)

- Rounds toward zero (truncation), independent of FPSCR.RM.
- On NaN, +Inf, or value ≥ 2³¹: result = 0x7FFFFFFF, sets Cause.V
  and Flag.V (invalid operation).
- On −Inf or value ≤ −(2³¹+1): result = 0x80000000, sets Cause.V and
  Flag.V.
- Normal in-range conversion may set Cause.I (inexact) if the float
  has a non-zero fractional part.

### 5.5 FMAC binary-compat notes. [T0]

(Identical to j2-spec.md §5.2.)

- **Single-precision only.** If FPSCR.PR=1 and an FMAC opcode is
  decoded, the SH-4 spec says the result is undefined; we follow
  qemu and treat it as a reserved instruction (raise via
  `fpu_o.exc`).
- Computes `FR0 × FRm + FRn → FRn`, with rounding after multiply AND
  rounding after add (non-fused). This is **not** IEEE-754-2008 FMA.

### 5.6 FCMP NaN behaviour. [T0]

Both FCMP/EQ and FCMP/GT return T=0 when either operand is a NaN
(unordered). Cause.V and Flag.V are set when either operand is a NaN.

### 5.7 Tier 0 microarchitecture sketch

(See j2-spec.md §6 for the full sketch; reproduced here only for the
top-level block layout.)

```
fpu/
  fpu_pkg.vhd              -- records, enums, constants
  fpu.vhd                  -- top: beat_seq + op_decode + regfile + ALU
  fpu_beat_seq.vhd         -- protocol state machine on cop_o/cop_i
  fpu_regfile.vhd          -- 32x32 with bank/precision addressing
  fpu_fpscr.vhd            -- FPSCR + FPUL
  fpu_addsub.vhd           -- shared add/sub datapath (PR-parametrized)
  fpu_mul.vhd              -- significand multiplier (PR-parametrized)
  fpu_div.vhd              -- iterative div + sqrt
  fpu_cmp.vhd              -- compare, NaN handling, drives cop_i.t
  fpu_cvt.vhd              -- FLOAT/FTRC/FCNVSD/FCNVDS
  fpu_round.vhd            -- shared rounding logic
  fpu_classify.vhd         -- IEEE-754 operand classification
```

Tier 1 additions to this layout are listed in §6.

---

## 6. Tier 1 — SH-4-complete FPU

### 6.1 Overview and product applicability. [T1]

Tier 1 brings the J-Core FPU to full SH-4 binary compatibility. It is
the FPU tier required by:

- **J32** — every product configuration that ships an FPU (the FPU
  is optional on J32 per [../glossary.md §3](../glossary.md), but
  when present it must be Tier 1).
- **J32-OOO** — same FPU block, hosted by the OoO core per
  [../ooo/j32ooo-spec.md §3–§5](../ooo/j32ooo-spec.md).
- **J32-FM, J64** — Tier 1 is the prerequisite for Tier 2; Tier 1 is
  always implied when Tier 2 is present.

Tier 1 instructions added on top of Tier 0:

| Mnemonic         | Encoding         | Operands                           | Cycles (typ.) |
| ---------------- | ---------------- | ---------------------------------- | ------------- |
| FIPR FVm, FVn    | 1111nnmm11101101 | 4×FP32 dot product, result→FR(n+3) | 4–6           |
| FTRV XMTRX, FVn  | 1111nn0111111101 | XMTRX × FVn → FVn                  | 4–8           |
| FSCA FPUL, DRn   | 1111nnn011111101 | sin/cos approximation              | 3–6           |
| FSRRA FRn        | 1111nnnn01111101 | 1/√FRn approximation               | 3–5           |
| FRCHG            | 1111101111111101 | toggle FPSCR.FR (already in T0)    | 1             |
| FSCHG            | 1111001111111101 | toggle FPSCR.SZ (already in T0)    | 1             |
| FPCHG            | 1111011111111101 | toggle FPSCR.PR (SH-4A addition)   | 1             |

Cycle counts are typical implementation targets, not architectural
constraints; see §6.11 for the implementer latency-hint discussion.

Beyond the new instructions, Tier 1 brings into scope:

- The SR.FD bit (SH-4 SR bit 15) and the associated FPU-disabled
  exception. §6.3.
- The full FPSCR layout (which Tier 0 already implemented in spirit
  but did not formally require the SH-4 reset value of). §6.4.
- The vector / matrix register-file readout patterns. §4.1, §4.2.

### 6.2 Endianness — the migration is withdrawn; the half-pair rule is normative. [T1]

**The wholesale BE→LE product migration this section once specified is
withdrawn** ([decisions/0006](../decisions/0006-endianness-is-big-endian.md));
§6.2.2 keeps its statement for the record. **What this section says about
double-`FMOV` half-pair order is normative**, and §6.2.1 is where it now lives,
outside any historical marker, because a reader must not have to decide which
half of a superseded section still binds them.

#### 6.2.1 Half-pair order and endian-neutrality (normative). [T1]

J-Core is to gain a **byte-invariant per-context byte-order mode**, covering the
data path **and** instruction fetch
([../bi-endian-spec.md §1](../bi-endian-spec.md), Decision BE-1;
[../decisions/0006](../decisions/0006-endianness-is-big-endian.md) §Second
re-scope). A double-`FMOV`'s half-pair order is a **data**-path property, so it
follows the **effective byte order** of the context performing the access.
*Not the `LE` bit specifically, which this paragraph previously named:
[../bi-endian-spec.md §6.1](../bi-endian-spec.md) defines the effective order as
`HLE` when `SR.HPRIV = 1` and `LE` otherwise, so naming `LE` would give the
wrong answer for a double-`FMOV` executed by hyperprivileged code.*

*This paragraph previously described the mode as little-endian **data** only,
with instruction fetch staying big-endian, citing Decision B2-1. B2-1 is
superseded. The requirement below is unaffected by the change — a paired `FMOV`
is a data access under either scoping — and it is the premise, not the rule,
that was restated.*

**Requirement.** A Tier-1 FPU on an implementation that has the byte-order mode
**must** implement the half-pair order described in points 1 and 2
below, selected by that same mode.

**This rule is SH-4's documented behaviour, not a J-Core invention**, and that
is worth knowing before implementing it. The SH-4 Programming Manual's note under
its figure 2.5 states that SH-4 does not support endian conversion for the
64-bit data format, so a double-precision access in little-endian mode has its
upper and lower 32 bits reversed — which is exactly points 1 and 2. It is the
one documented exception to SH-4's otherwise byte-invariant data format, and
[../bi-endian-spec.md §3.1](../bi-endian-spec.md) records it as such. Two
consequences: the requirement below is a **compatibility** obligation with a
citable source rather than a derived one, and it does **not** generalise — no
other access width on this machine has a half-pair rule, because no other
access width is 64 bits wide. Neither the mode nor a Tier-1 FPU exists
today, and whichever lands second inherits this requirement. Nothing observes it
in the meantime, because guest FP is trapped and emulated
([../sh4-guest-model.md §4](../sh4-guest-model.md)) — that is a reason it is not
urgent, not a reason it is optional.

Points 3–5 are statements of fact about where byte order does *not* reach, and
hold at every tier and in either mode.

1. **Double-FMOV halves swap.** For `FMOV @Rm, DRn` with FPSCR.SZ=1:
   - In **big-endian** (Tier 0 legacy): the word at `Rm` is loaded
     into FRn (= the high half of the IEEE-754 binary64); the word
     at `Rm+4` is loaded into FR(n+1) (= the low half).
   - In **little-endian** (Tier 1): the word at `Rm` is loaded into
     FRn (= the **low** half); the word at `Rm+4` is loaded into
     FR(n+1) (= the high half).

   Either way, FRn is at the lower address. The IEEE-754 bit
   significance of FRn vs FR(n+1) is what swaps, because the bytes
   on the bus are interpreted in the host's byte order.

2. **The SH-4 "LE double-FMOV swap" bug does not arise on Tier 1
   J-Core.** The SH-4 hardware manual documents a long-standing
   anomaly in SH-4 LE mode where SZ=1 FMOV swaps the two 32-bit
   halves of the double — a hardware bug grandfathered into the
   architecture. The SH-4A added a programmable fix (the FPSCR.PR=1,
   SZ=1 magic) that produces "correct" LE byte ordering on chips
   that opt in. **J-Core Tier 1 implements only the SH-4A-correct
   behaviour.** Legacy SH-4 LE binaries that depended on the swap
   will see a different byte layout; software targeting J-Core
   Tier 1 must assume the SH-4A-correct LE layout.

3. **Single-precision FMOV.S is endian-neutral** at the FPU level:
   the word loaded from memory is placed directly into FRn with no
   byte-swapping inside the FPU. Any endianness handling for the
   load itself is the CPU bus's responsibility (and is identical to
   `MOV.L`).

4. **FPSCR, FPUL, and integer transfers between the CPU and FPU are
   word-wise** and therefore endian-neutral on the wire (`cop_o.d`,
   `cop_i.d` carry 32-bit words, see §3.7).

5. **FIPR and FTRV are register-file-internal** and therefore
   endian-neutral. The FVn / XMTRX layout is defined as a sequence
   of FR/XF indices, not as a memory byte order.

**Implementation note.** An FPU may share its regfile RTL between the two byte
orders by parameterising only the `FMOV`-double half-pair ordering. All
arithmetic blocks and the FIPR / FTRV / FSCA / FSRRA datapaths are
endian-neutral, per points 3–5. *(This note previously described the parameter
as selecting between a Tier-0 big-endian and a Tier-1 little-endian **build**.
That framing went with the withdrawn migration: the selector is the per-context
byte-order mode ([../bi-endian-spec.md §6](../bi-endian-spec.md)), not
the tier, and it must therefore be switchable at run time rather than fixed at
elaboration. The selector is the **effective** byte order, not `LE` as such —
see §6.2.1.)*

#### 6.2.2 The withdrawn migration statement. [T0 → T1]

> **HISTORICAL 2026-09-07.** This subsection records the BE→LE *product*
> migration this section used to specify, and nothing in this subsection is
> normative. It is scoped deliberately: §6.2.1 above carries the part that
> still binds, so that no reader has to reconcile a normative requirement with a
> blanket "not normative any more" disclaimer in the same section. Earlier
> revisions did exactly that — first by saying "nothing below is normative",
> then by keeping that sentence while adding a normative paragraph above it.

**Statement, as it stood.** Tier 0 implementations may ship big-endian to
match existing J2 silicon; Tier 1 implementations are little-endian. The
justification given was the glossary's product table, which is exactly the
citation [decisions/0006](../decisions/0006-endianness-is-big-endian.md)
rejects. What replaced it is not the opposite claim but a narrower one: the
product ships big-endian and the *data path* gains a per-guest mode.

### 6.3 SR.FD trap semantics. [T1]

**Bit position.** SR.FD is **SR bit 15**, matching SH-4 verbatim.
The J-Core SR layout in
[../hypervisor/hardware-spec.md §2.1](../hypervisor/hardware-spec.md)
follows the SH-4 manual exactly for MD (bit 30), RB (bit 29), BL
(bit 28), FD (bit 15), M (bit 9), Q (bit 8), IMASK (bits 7:4), S
(bit 1), and T (bit 0). The only J-Core-specific addition is
**SR.HPRIV at bit 14**, which occupies an SH-4-reserved bit slot
(no collision).

Earlier drafts of the hypervisor spec mistakenly placed MD at bit
15 and HPRIV at bit 9, which collided with SH-4's FD and M
respectively. That error was corrected in the 2026-05 SR-layout
reconciliation; this FPU spec and the hypervisor spec now agree
that FD is bit 15 and HPRIV is bit 14. There is no remaining open
question on SR bit assignment.

**Semantics.**

- `SR.FD = 0` (reset value): FPU is enabled. All FPU instructions
  execute normally subject to the rest of the architectural state.
- `SR.FD = 1`: FPU is disabled. Any FPU instruction — compute,
  transfer, FPSCR control (LDS/STS to FPUL or FPSCR), or
  bit-toggle (FRCHG/FSCHG/FPCHG) — raises an FPU-disabled
  exception.

**Trap classification.**

- On a Tier 1 implementation without the hypervisor extension
  (SR.HPRIV always 0, HEDR is not consulted), the FPU-disabled
  exception surfaces via `fpu_o.exc` and is routed through the
  CPU's exception logic as a regular SH-4-compatible FPU-disable
  trap. The host CPU's preferred vector layout determines whether
  this appears as EXPEVT 0x800 (non-slot) or 0x820 (slot) per the
  SH-4 manual, or as a collapsed cause as on J2-style ports.
- On a Tier 2 implementation (next section), the trap is reported
  with cause `EXC_FPU_DISABLED` and is subject to HEDR delegation.

**Corroboration for the `0x800`/`0x820` assignment, added 2026-09-08.**
`linux@jcore` `arch/sh/kernel/traps_32.c` wires both codes to
`fpu_state_restore_trap_handler` under `CONFIG_SH_FPU` — the lazy-FPU restore
path an FPU-disable trap drives — and to the reserved/illegal-slot handlers on
an SH-4 without an FPU. SH-4's *arithmetic* FP error is `0x120`
(`arch/sh/kernel/cpu/sh3/ex.S`). This settles a disagreement with
[../hypervisor/hardware-spec.md §2.3.1](../hypervisor/hardware-spec.md), which
labelled these two codes as arithmetic exceptions; that table is corrected in
this specification's favour.

**Instructions that DO trap under SR.FD:** all FPU instructions
including FRCHG, FSCHG, FPCHG (control-bit toggles), LDS / STS
involving FPUL or FPSCR, and FLDS / FSTS. There is no "control-only"
escape; SR.FD truly disables the FPU end-to-end.

**And a SIMD block containing any FP operation, added 2026-09-09 by
Wave-3 C1c.** Governed FP instructions
([../simd/spec.md §5.2](../simd/spec.md)) read `FPSCR.RM` and, under
`VCSR.IEE = 1`, write `FPSCR.FLAG`, so a SIMD block was exactly the
control-only escape the paragraph above says does not exist: it reached
`FPSCR` under `SR.FD = 1`, which `LDS Rm,FPSCR` cannot.
[../simd/spec.md §2.4.1](../simd/spec.md) rule **S-R1** closes it — the
requirement is raised against the **prefix**, and it covers a purely
*vertical* block that writes no FR/DR at all, not only the FP-scalar
writeback of a horizontal reduction / `VFIPR` / `VFTRV`.

**Instructions that do NOT trap under SR.FD:** integer-only
instructions, branches, MMU control, hypervisor control. The SR.FD
trap is strictly scoped to FPU instructions.

**Save / restore on context switch.** On any trap that delivers to
the supervisor (SR.FD trap, syscall, asynchronous interrupt), the
hardware saves the current SR (including FD) into SSR per the
existing SH-4 trap-entry sequence. The supervisor's task-switch
sequence is responsible for arranging FD in the next task's SR
shadow per its own scheduling policy. Linux SH-4 uses the standard
lazy-FPU model: set FD=1 on context-out, clear FD=0 in the trap
handler that catches the next-task's first FPU instruction, after
saving the previous owner's FPU image. The Tier 2 hypervisor uses
the same model at vCPU granularity (§7).

**Interaction with delay slots.** An FPU instruction in the delay
slot of a branch traps with SPC pointing at the branch (not the
delay-slot instruction), per the SH-4 convention. The trap handler
must inspect SPC and read the instruction at SPC+2 to find the
offending FPU instruction. This matches SH-4 silicon exactly.

### 6.3.1 Kernel-mode use of the FPU — the `kernel_fpu` discipline (normative for the OS). [T1]

**Wave-3 task C1c**, second half. [../j4-remediation-plan.md §C1](../j4-remediation-plan.md) asks
for "a `kernel_fpu_begin`-equivalent discipline and a scrub requirement for kernel crypto that
stages key material in V registers". This section is the FP-file half — `FR`, `XF`, `FPUL`,
`FPSCR`, which this document owns; the V-file half is
[../simd/spec.md §2.6.2](../simd/spec.md).

This is a **software** rule, on the OS, not on hardware. It is written down because the hardware
rules that look like they cover it do not: §7.7's FP-R3 scrub fires on a hyperprivileged `FPDS`
write at a *cross-tenant* switch, and a kernel→user transition inside one guest is not one.

#### What the tree does today, and why that is the starting point

`linux@origin/jcore` (`128e8958`, checked 2026-09-09):

- **Kernel-mode FP is banned, and the ban has a detector.** `arch/sh/kernel/cpu/fpu.c`
  `fpu_state_restore()` opens with `if (unlikely(!user_mode(regs))) { printk(KERN_ERR "BUG: FPU is
  used in kernel mode.\n"); BUG(); }`. An `SR.FD` trap taken from kernel mode is a `BUG()`. That is
  a **stronger** rule than the generic kernel contract, which does not forbid kernel FP at all.
- **The detector is compiled out on this target.** `fpu_state_restore()` is inside
  `#ifdef CONFIG_SH_FPU`; `arch/sh/Kconfig`'s `CPU_SUBTYPE_JCORE` selects `CPU_JCORE` and `MMU` and
  reaches no `select CPU_HAS_FPU` by any path, and `arch/sh/Kconfig.cpu`'s `SH_FPU` is
  `depends on CPU_HAS_FPU`. So `CONFIG_SH_FPU` cannot be set on a J-Core build and
  `arch/sh/include/asm/fpu.h` reduces `save_fpu`, `restore_fpu`, `release_fpu`, `grab_fpu` and
  `fpu_state_restore` to `do { } while (0)`.
- **There is no `kernel_fpu_begin` under `arch/sh` at all** — no definition and no call, checked
  case-insensitively along with `kernel_neon`, `fpu_begin`, `fpu_end` and `may_use_simd` — and
  `arch/sh` is not among the architectures selecting `ARCH_HAS_KERNEL_FPU_SUPPORT` (`arch/Kconfig`
  line 1794; the five that do are arm64, loongarch, powerpc, riscv, x86).
- **There is no consumer either.** No `arch/sh/crypto`, no `lib/crypto/sh`, no
  `lib/raid/raid6/sh`, and no SH hook in generic `crypto/`, `lib/crc/` or `lib/raid/`. Nothing
  under `arch/sh` uses FP in kernel context: every FP touchpoint is user-context lazy
  save/restore, the soft-float emulator, or a mnemonic table.

So the honest answer to "what does kernel-`fpu` discipline mean on this tree" is: **the ban is the
discipline, it is already written, and it is switched off by the same Kconfig gap that switches off
the FPU.** The rules below are what must hold *if and when* the ban is lifted, and K-R1 is what must
hold until then.

#### The rules (normative)

**K-R1 — Kernel-mode FP stays banned until every other rule here is implemented, and the ban keeps
its detector.** The `BUG()` above is not to be relaxed as a side effect of enabling
`CONFIG_SH_FPU`. When SIMD arrives, the `EXC_SIMD_DISABLED` trap
([../simd/spec.md §2.6](../simd/spec.md)) gets the same treatment: taken from kernel mode with no
critical section open, it is a bug and not a lazy-restore event.

**K-R2 — If the ban is lifted, the API is the generic one, and `arch/sh` owes three things it does
not have.** `Documentation/core-api/floating-point.rst` is the contract, and meeting it is not a
matter of writing two functions:

1. **The header name is already taken.** `include/linux/fpu.h` is `#include <asm/fpu.h>` and
   nothing else, and `arch/sh/include/asm/fpu.h` is the per-task lazy header holding `save_fpu`,
   `unlazy_fpu` and `clear_fpu`. A file doing `#include <linux/fpu.h>` on `sh` today gets that
   header and no `kernel_fpu_begin()`. Resolving the collision is a precondition, not a detail.
2. **The build-time half has no flags.** The contract's `CC_FLAGS_FPU` / `CC_FLAGS_NO_FPU` do not
   exist in `arch/sh/Makefile`; the compilation-unit isolation it requires is currently supplied by
   the *ISA* — `CONFIG_CPU_SUBTYPE_JCORE` adds only `-m2`, and SH-2 has no FP encodings for the
   compiler to emit. **That stops being true the moment the FPU lands**, and nothing in the build
   would notice.
3. **`may_use_simd()` would come from the wrong place.** There is no `arch/sh/include/asm/simd.h`,
   so `sh` inherits `include/asm-generic/simd.h`'s `return !in_interrupt();`, whose stated reason is
   that architectures do not preserve the SIMD file across an interrupt. On this design the gate is
   `SR.FD` / `SR.VD` ownership, not interrupt context, and the two are not the same question.

**K-R3 — A kernel FP critical section MUST scrub on exit. This is the rule no other architecture
has, and the reason is architectural, not a difference of taste.** On exit the physical
`FR`/`XF`/`FPUL`/`FPSCR` hold kernel data — key material, for the case
[../j4-remediation-plan.md §C1](../j4-remediation-plan.md) names. Every architecture in
`linux@origin/jcore` leaves it there: x86's `kernel_fpu_end()` (`arch/x86/kernel/fpu/core.c:499`)
writes one per-CPU boolean and unlocks, touching no FP register; arm64's `kernel_neon_end()`
(`arch/arm64/kernel/fpsimd.c:1956`) clears a thread flag and a pointer. **They are safe because the
return to user reloads unconditionally**: `kernel_fpu_begin_mask()` sets `TIF_NEED_FPU_LOAD` and
saves the user state (`core.c:483-488`), and `arch_exit_work()`
(`arch/x86/include/asm/entry-common.h:56-57`) calls `switch_fpu_return()` on that flag before the
task runs again. riscv and loongarch are safe for the blunter reason that their `end` restores
`current`'s state over the kernel's.

**§7.3's lazy model has no such unconditional reload, and that is the whole difficulty.** Its
handler has a branch that writes nothing when the incoming context is already the owner, and a
branch that writes nothing when there is no saved image — the same no-saved-image branch §7.7 exists
to close, reappearing one privilege level down and out of reach of FP-R3. Setting `SR.FD` on the way
out does not help: the trap it raises lands in that handler. So the section must write the FP-R1
scrub values over every register it may have touched, itself, before re-enabling preemption, and
must not rely on a later restore to do it.

**K-R4 — A kernel FP critical section claims the FPU the same way a task does.** It must
`unlazy_fpu()` the current task first — save the previous owner's state, exactly as riscv's
`kernel_fpu_begin()` does `fstate_save(current, task_pt_regs(current))` — and then clear `SR.FD`
(`arch/sh/include/asm/processor_32.h`'s `enable_fpu()`). Both helpers already exist in the tree.
§2.4.1 of [../simd/spec.md](../simd/spec.md) rule **S-R1** applies to kernel code with no
exemption: a kernel routine issuing FP SIMD needs FPU ownership for the same reason a user task
does, and for a kernel routine "the current owner" is a *user task's* `FPSCR`.

**K-R5 — Process context only, non-reentrant, preemption disabled.** The three limits
`Documentation/core-api/floating-point.rst` states, adopted verbatim. **x86's wider allowance is
not adopted**: `irq_fpu_usable()` permits softirq and hardirq-with-softirqs-enabled, and it is safe
there because of `fpregs_lock()`'s `local_bh_disable()` *and* the unconditional reload K-R3
describes, neither of which exists here. Nothing in this design earns a contract wider than the
documented one.

#### What is vacuous today, said plainly

K-R2 through K-R5 have **no site** in `linux@origin/jcore`: no `CONFIG_SH_FPU` on this target, no
kernel-FP API, and no caller that would use one. K-R1 has a site and is already satisfied, by code
the build removes. **The `linux` implementation half of C1c is therefore not dispatchable**, for the
same shape of reason C1a's and C1b's were not, and the reason is recorded in
[../j4-execution-plan.md](../j4-execution-plan.md) rather than absorbed. What these rules buy now is
that the task which lands `CPU_HAS_FPU` cannot land it without meeting them.

### 6.4 Full FPSCR layout. [T1]

(Identical to j2-spec.md §4.3 in terms of bit assignment; reproduced
here for completeness and to anchor the Tier 1 normative reset value
and bit semantics.)

| Bits  | Field   | Notes                                                  |
| ----- | ------- | ------------------------------------------------------ |
| 31:22 | -       | reserved, read as 0                                    |
| 21    | FR      | register-bank select                                   |
| 20    | SZ      | FMOV transfer size: 0=32-bit, 1=64-bit                 |
| 19    | PR      | precision: 0=single, 1=double                          |
| 18    | DN      | denormal mode: 0=denormal as such, 1=flush-to-zero     |
| 17    | Cause.E | FPU Error (no Enable, no Flag); always traps when set  |
| 16:12 | Cause   | V, Z, O, U, I (in order from 16 down to 12)            |
| 11:7  | Enable  | V, Z, O, U, I (no Enable.E)                            |
| 6:2   | Flag    | V, Z, O, U, I (no Flag.E; sticky)                      |
| 1:0   | RM      | rounding mode: 00=nearest-even, 01=to-zero, 10/11=resv |

**Per-bit semantics.**

- **FR (bit 21).** Selects which physical bank is FR0..FR15 (and
  which is XF0..XF15). Toggled by FRCHG. Affects all FR-addressed
  instructions immediately on the cycle after the write.
- **SZ (bit 20).** 0: FMOV transfers 32 bits (single FR). 1: FMOV
  transfers 64 bits (pair of FRs). Affects only FMOV; arithmetic
  precision is independent (use PR). Toggled by FSCHG.
- **PR (bit 19).** 0: arithmetic instructions are
  single-precision. 1: arithmetic instructions are
  double-precision. **Combined PR=1, SZ=1 is reserved by SH-4;**
  FMAC, FIPR, FTRV, FSCA, FSRRA are all single-precision-only and
  produce implementation-defined results when PR=1. Toggled by
  FPCHG (Tier 1).
- **DN (bit 18).** 0: hardware processes denormals (or traps to
  software via Cause.E). 1: flush denormals to ±0 with sign
  preserved on input; flush tiny results to ±0 on output.
- **Cause.E (bit 17).** FPU Error. **Always traps when set; no
  Enable bit, no Flag bit.** Set when hardware refuses to complete
  an operation (denormal involved in DN=0 mode; reserved
  encoding). The Linux SH-4 FPU handler reads this bit to invoke
  software emulation (`denormal_addf`, `denormal_mulf`, etc.).
- **Cause (bits 16:12).** Per-operation Cause field for IEEE-754
  exceptions V (Invalid), Z (Divide-by-zero), O (Overflow), U
  (Underflow), I (Inexact). **Cleared to zero at the start of every
  FPU arithmetic instruction**, then set on the same cycle as the
  result becomes available. Per-operation, not cumulative.
- **Enable (bits 11:7).** Software-controlled gate for which V / Z /
  O / U / I Cause bits trigger a trap on the current operation.
  Cause.E always traps and is not gated.
- **Flag (bits 6:2).** Sticky V / Z / O / U / I bits that
  accumulate as exceptions occur. Cleared only when software writes
  a 0 via `LDS Rn, FPSCR`. There is no Flag.E.
- **RM (bits 1:0).** 00 = round-to-nearest-even; 01 = round-toward-
  zero (truncation). 10 and 11 are reserved by SH-4; the J-Core FPU
  preserves the written value but internally treats reserved modes
  as round-to-zero (qemu-compatible behaviour).

**Reset value.** `0x00040001`. This is DN=1, RM=01
(round-toward-zero). Identical to SH-4 silicon reset. Software that
wants IEEE-754 round-to-nearest-even semantics must explicitly write
FPSCR after reset.

### 6.5 FRCHG, FSCHG, FPCHG. [T0/T1]

The three FPSCR-toggle instructions are single-cycle XOR operations
on a single FPSCR bit. They are micro-encoded as `FOP_CTRL`
(§3.4) with the target bit selected via `rna`.

**FRCHG. [T0]**

```
Encoding: 1111 1011 1111 1101 = 0xFBFD
Effect:   FPSCR.FR ← !FPSCR.FR
Cycles:   1
Tier:     T0 (already in archived j2-spec.md Tier A)
```

**FSCHG. [T0]**

```
Encoding: 1111 0011 1111 1101 = 0xF3FD
Effect:   FPSCR.SZ ← !FPSCR.SZ
Cycles:   1
Tier:     T0
```

**FPCHG. [T1] (SH-4A addition)**

```
Encoding: 1111 0111 1111 1101 = 0xF7FD
Effect:   FPSCR.PR ← !FPSCR.PR
Cycles:   1
Tier:     T1
```

**Trap behaviour.** All three are FPU instructions and trap with
SR.FD=1. They do not raise IEEE-754 exceptions of their own; the
only Cause bit they can ever set is Cause.E for a reserved
encoding, which does not arise for these three by construction.

**Interaction with SR.FD.** Yes, even FPSCR control instructions are
trapped under SR.FD — this is what makes lazy FPU context switching
work (§7.3): the hypervisor's trap-on-first-use is reliably first
because *any* attempt to touch the FPU traps, not just compute.

### 6.6 FIPR — 4-element single-precision dot product. [T1]

**Mnemonic.** `FIPR FVm, FVn`

**Operand form.** FVm and FVn are 4-element single-precision vector
aliases (§4.2). FIPR is single-precision only (Cause.E if PR=1).

**Encoding.**

```
Bits:   15 14 13 12 | 11 10  9  8 |  7  6  5  4 |  3  2  1  0
        1  1  1  1  |  n  n  m  m |  1  1  1  0 |  1  1  0  1
Hex:    0xF{nm}ED, where n is FVn>>2 (00=FV0, 01=FV4, 10=FV8, 11=FV12)
        and m is FVm>>2.
Pattern: 1111 nnmm 11101101 (SH-4 manual page 264, Section 9.41)
```

**Semantics in plain English.** Compute the 4-element single-
precision dot product of FVm and FVn, write the scalar result to
**FR(n+3)** (the last element of FVn), with one rounding step at
the end.

**Pseudocode.**

```
require: FPSCR.PR == 0          // else Cause.E
require: FPSCR.SZ == 0 || ok    // SZ=1 is reserved per SH-4

m = FVm.base   // 0, 4, 8, 12
n = FVn.base
acc = FR[m+0] * FR[n+0]
    + FR[m+1] * FR[n+1]
    + FR[m+2] * FR[n+2]
    + FR[m+3] * FR[n+3]
// One rounding step over the entire 4-term sum, using FPSCR.RM.
FR[n+3] = round(acc, FPSCR.RM)
update FPSCR.Cause, FPSCR.Flag for the operation
if any enabled exception is raised: trap
```

**Precision / accuracy notes.** The SH-4 manual specifies that FIPR
"computes an approximate inner product ... and writes the result to
FR(n+3)". The maximum specified error is **2 × E** where E is the
maximum error of a single-precision multiply followed by three
single-precision adds. In practice, an FPU that computes the four
products to extended internal precision and rounds once at the end
meets this bound by a wide margin. The SH-4 manual permits
"approximate" computation; we recommend the extended-precision-then-
round-once implementation as it is both more accurate and cheaper
than four scalar FMUL + three scalar FADD.

**Exception behaviour.**

- **Cause.E** when PR=1 or any operand is denormal under DN=0.
- **Cause.V** when any operand is NaN, or when the sum involves
  +∞+(−∞).
- **Cause.O / Cause.U / Cause.I** per the final rounded result.
- Enable bits and Flag bits update per the standard rules (§6.4).

**SR.FD interaction.** FIPR is an FPU instruction; SR.FD=1 raises
the FPU-disabled trap before any operands are read.

**Latency hint for implementers.** FIPR is well-suited to a single
4-input single-rounding adder tree fed by four parallel
single-precision multipliers. A 4-multiplier + 4:1 adder-tree
implementation completes in 4–6 cycles at typical FPGA clock rates.
A serialised implementation that reuses one scalar multiplier and
one scalar adder takes 7–10 cycles and is acceptable. The arch
budget is "amortise to better than 4 × FMUL + 3 × FADD".

### 6.7 FTRV — 4×4 matrix × 4-vector multiply. [T1]

**Mnemonic.** `FTRV XMTRX, FVn`

**Operand form.** XMTRX is the fixed alias for the XF back-bank
viewed as a 4×4 column-major matrix (§4.2). FVn is one of the four
FV aliases (FV0, FV4, FV8, FV12). FTRV is single-precision only.

**Encoding.**

```
Bits:   15 14 13 12 | 11 10  9  8 |  7  6  5  4 |  3  2  1  0
        1  1  1  1  |  n  n  0  1 |  1  1  1  1 |  1  1  0  1
Hex:    0xF{n}FD, where n is FVn>>2 << 2 | 0b01 in bits [11:8]
        (the [11:8] field is `nn01`, with nn = FVn>>2 ∈ {00,01,10,11})
Pattern: 1111 nn01 11111101 (SH-4 manual page 282)
```

**Semantics in plain English.** Multiply the 4×4 matrix XMTRX
(currently in the XF back bank) by the 4-element column vector FVn,
write the resulting 4-element column vector back to FVn (in place).
Each element of the result is a 4-term dot product, computed with
the same approximation contract as FIPR.

**Pseudocode.**

```
require: FPSCR.PR == 0          // else Cause.E
n = FVn.base                    // 0, 4, 8, 12
v = (FR[n+0], FR[n+1], FR[n+2], FR[n+3])  // copy, to allow in-place write
for row in 0..3:
    acc = XF[row+0]  * v[0]
        + XF[row+4]  * v[1]
        + XF[row+8]  * v[2]
        + XF[row+12] * v[3]
    FR[n+row] = round(acc, FPSCR.RM)
update FPSCR.Cause, FPSCR.Flag (OR-accumulated across the four rows)
if any enabled exception is raised: trap
```

**Precision / accuracy notes.** The SH-4 manual specifies the same
"approximate inner product" wording per row, with the per-row error
bound matching FIPR's. Implementations that share an FIPR datapath
across the four rows meet the bound trivially.

**Exception behaviour.**

- **Cause.E** when PR=1 or any operand is denormal under DN=0.
- **Cause.V / O / U / I** OR-accumulated across the four rows.
- If any row would trap, the entire FTRV traps; no partial state is
  written to FVn. This is the SH-4 precise-exception guarantee
  applied to the compound instruction.

**SR.FD interaction.** Same as FIPR: SR.FD=1 raises the FPU-disabled
trap before any operands are read.

**Latency hint for implementers.** FTRV is four FIPRs in flight. A
shared 4-multiplier + 4-input-adder-tree datapath, sequenced over
four cycles to produce the four result elements, completes the whole
operation in 4–8 cycles. A fully parallel implementation (16
multipliers + four adder trees) is feasible on a large FPGA but
unnecessary on the ULX3S 85F target.

### 6.8 FSCA — sin/cos table approximation. [T1]

**Mnemonic.** `FSCA FPUL, DRn`

**Operand form.** FPUL holds the input angle as a 16.16 fixed-point
fraction of a full turn (so the integer part wraps mod 1.0). DRn is
a double-precision pair (DR0, DR2, DR4, ..., DR14) that receives
two single-precision results, even though the destination is named
as a double-precision register (the SH-4 manual reuses the DR
register-naming for the destination pair). The two single-precision
results are:

- **FRn = sin(2π × FPUL / 0x10000)** as a single-precision float.
- **FR(n+1) = cos(2π × FPUL / 0x10000)** as a single-precision float.

**Encoding.**

```
Bits:   15 14 13 12 | 11 10  9  8 |  7  6  5  4 |  3  2  1  0
        1  1  1  1  |  n  n  n  0 |  1  1  1  1 |  1  1  0  1
Hex:    0xF{n}FD with [11:8] = nnn0 (n is DRn>>1 ∈ 0..7)
Pattern: 1111 nnn0 11111101 (SH-4A manual)
```

**Semantics in plain English.** Read FPUL as an unsigned 16.16
fixed-point fraction of a full turn (one full revolution per
0x10000 of the integer part). Compute sin and cos via a
table-driven approximation. Write sin to FRn and cos to FR(n+1).

**Pseudocode.**

```
require: FPSCR.PR == 0          // else Cause.E
angle_units = FPUL & 0x0000FFFF   // SH-4 takes only the low 16 bits
                                  // as the angle index; the upper 16
                                  // bits are ignored. (Some SH-4
                                  // documentation discusses the full
                                  // 16.16 interpretation; the actual
                                  // silicon truncates.)
                                  // *** Verify against SH-4 manual ***
theta = 2 * pi * angle_units / 65536.0
FR[n+0] = round_single(sin(theta))
FR[n+1] = round_single(cos(theta))
update FPSCR.Cause (typically only I), FPSCR.Flag
```

**Precision / accuracy notes.** The SH-4 manual specifies a maximum
absolute error of **2⁻²¹** (approximately 4.77 × 10⁻⁷). This is well
below single-precision ULP for outputs in the [-1, 1] range. A
straightforward implementation uses a 1024-entry (or 256-entry plus
linear interpolation) table of sin values combined with a quadrant
selector. **Implementations are not required to bit-match SH-4
silicon table values**, only the accuracy bound. *Open question §10
#2: verify the 2⁻²¹ bound against the SH-4 manual; some sources
quote 2⁻²² for SH-4A.*

**Exception behaviour.**

- **Cause.E** when PR=1.
- **Cause.I** typically set (the approximation result is inexact
  except for trivial inputs like FPUL=0).
- **Cause.V / Z / O / U** generally not raised; the sin/cos outputs
  are always finite and in [-1, 1].

**SR.FD interaction.** Standard: SR.FD=1 raises the FPU-disabled
trap.

**Latency hint for implementers.** Table lookup + one multiply +
two adds per output. A pipelined implementation produces both
outputs in 3–6 cycles. The table consumes about 256 × 32 bits = 1 KB
of ROM. STRUCTURAL ([security/threat-model.md §9](../security/threat-model.md)
provenance scale), not platform-tagged: 8 Kb of table data fits in a single
18 Kb block RAM — one **EBR** on the Phase-1 ECP5, and one block on any other
family whose block is 18 Kb and whose ports reach a 256×32 aspect ratio. This
is capacity arithmetic — table size against block size — not a synthesis
result, which is why it is stated as a fact rather than as an unknown
([decisions/0005](../decisions/0005-unmeasured-figures-are-removed.md) rule 5),
and per [decisions/0004](../decisions/0004-platform-tag-convention.md) rule 6 a
fact that holds on any correctly-implemented target carries no platform tag.

### 6.9 FSRRA — reciprocal square root approximation. [T1]

**Mnemonic.** `FSRRA FRn`

**Operand form.** Single-precision FRn. Result also single-precision
FRn (in place).

**Encoding.**

```
Bits:   15 14 13 12 | 11 10  9  8 |  7  6  5  4 |  3  2  1  0
        1  1  1  1  |  n  n  n  n |  0  1  1  1 |  1  1  0  1
Hex:    0xF{n}7D
Pattern: 1111 nnnn 01111101 (SH-4A manual)
```

**Semantics in plain English.** Compute 1/√FRn as a single-precision
approximation, write to FRn (in place). Defined only for positive
operands; negative operands and zero set Cause.V and Cause.Z
respectively.

**Pseudocode.**

```
require: FPSCR.PR == 0          // else Cause.E
require: FRn > 0
if classify(FRn) == NaN:
    set Cause.V; result = qNaN
elif FRn < 0:
    set Cause.V; result = qNaN
elif FRn == 0.0 or FRn == -0.0:
    set Cause.Z; result = +Inf (or -Inf with sign-bit handling per SH-4)
elif FRn == +Inf:
    result = +0.0
else:
    result = round_single(1.0 / sqrt(FRn))
FR[n] = result
update FPSCR.Cause, FPSCR.Flag
```

**Precision / accuracy notes.** The SH-4 manual specifies a maximum
**relative** error of **2⁻²¹** (about 4.77 × 10⁻⁷). A typical
implementation uses a 128- or 256-entry table indexed by the high
bits of the mantissa, plus one Newton-Raphson refinement step. The
implementation is free to skip the Newton-Raphson step if the table
is wide enough (~512–1024 entries). **Implementations need not
bit-match SH-4 silicon table values**; only the accuracy bound is
architectural.

**Exception behaviour.** Cause.V on negative or NaN; Cause.Z on
±0; Cause.E on PR=1 or denormal under DN=0; Cause.I typically set
for general inputs.

**SR.FD interaction.** Standard.

**Latency hint for implementers.** Table lookup + optional one or
two refinement multiplies and adds. 3–5 cycles pipelined. Table
consumes one 18 Kb block RAM — one EBR on the ECP5. STRUCTURAL
([security/threat-model.md §9](../security/threat-model.md)), not
platform-tagged, same capacity arithmetic as §6.8 above.

### 6.10 Coprocessor protocol extension for vector beats. [T1]

FIPR and FTRV add no new wire-level beats. Their operand transfers
are entirely internal to the FPU regfile:

**FIPR FVm, FVn (single-precision, 4×4 dot, reg-reg):**

```
Cycle  cop_o                                          cop_i / FPU state
  N    op=FOP_FIPR, rna=FVm(0..3), rnb=FVn(0..3), en=1   FPU latches base
                                                          addresses,
                                                          asserts fpu_o.busy
  N+1..N+k    en=0                                       FPU sequences 4
                                                          regfile reads
                                                          per port, computes
                                                          via the FIPR
                                                          datapath
  N+k         en=0                                       FPU writes result
                                                          to FR(n+3),
                                                          fpu_o.busy=0
```

The `rna`/`rnb` fields carry the *base* of FVm / FVn (i.e. m and n
themselves, not individual FR indices). The FPU's beat sequencer
expands the base into four register-file reads internally.

**FTRV XMTRX, FVn:**

```
Cycle  cop_o                                          cop_i / FPU state
  N    op=FOP_FTRV, rna=FVn(0..3), rnb=ignored, en=1     FPU latches FVn
                                                          base, asserts busy
  N+1..N+k    en=0                                       FPU sequences four
                                                          row dot products,
                                                          read XMTRX from XF
                                                          back bank
  N+k         en=0                                       FPU writes four
                                                          results back to
                                                          FVn (in place),
                                                          fpu_o.busy=0
```

**FSCA and FSRRA** also fit the standard FOP_FSCA / FOP_FSRRA beat:
one CPU-driven dispatch beat, multi-cycle internal computation,
result lands in the named regfile location, no cop_i traffic.

**The wire protocol does not widen.** The 4-bit `rna`/`rnb` fields
suffice because FVm / FVn are addressed by their 2-bit FV index
(00=FV0, 01=FV4, 10=FV8, 11=FV12) zero-extended to 4 bits, and the
FPU sequencer expands internally. FTRV's source matrix is XMTRX, a
*fixed* alias of the XF back bank, requiring no operand-address
field at all.

### 6.11 Implementer latency hints. [T1]

These are recommended target latencies for a typical FPGA Tier 1
implementation on the ULX3S 85F class device. They are not
architectural requirements; the `fpu_o.busy` back-pressure mechanism
absorbs arbitrary cycle counts.

| Instruction | Typical cycles | Critical path                        |
| ----------- | -------------- | ------------------------------------ |
| FIPR        | 4–6            | 4-mul + 4-input adder tree + round   |
| FTRV        | 4–8            | sequenced 4× FIPR sharing one tree   |
| FSCA        | 3–6            | table read + small multiply + adds   |
| FSRRA       | 3–5            | table read + optional NR refinement  |
| FRCHG/FSCHG/FPCHG | 1        | XOR on a single FPSCR bit            |

Implementations that prefer a smaller area budget may serialise FIPR
to 8–12 cycles by reusing one scalar multiplier and one scalar
adder; the architecture does not penalise this choice.

---

## 7. Tier 2 — Hypervisor-aware FPU

> **SUPERSEDED BY [../simd/spec.md §2.3](../simd/spec.md) — 2026-08-25.** The
> paragraph immediately below is wrong on the one point it exists to make. It
> says the FPU and SIMD facilities are *"fully independent at the register-file
> level"* because *"SIMD never writes FR / DR / FPUL directly (it routes scalar
> FP through its own VFPUL register)"*. **VFPUL was retired on 2026-07-17 and FP
> reductions now write `FR0`/`DR0` directly** — the exact opposite of the claim.
> The four `FMOV.VS` / `FMOV.VD` boundary instructions this section points at
> ([../simd/spec.md §5.8](../simd/spec.md)) are **deleted**; that section number
> is retained only so cross-references resolve.
>
> **What is actually true**, per [../simd/spec.md §2.3](../simd/spec.md) and its
> Appendix B decision-log entry of 2026-07-17:
> - FP horizontal reductions, `VFIPR` and `VFTRV` write the SH-4 FPU file
>   directly, at an implied `FR0` base, committing at **block exit** so the
>   `SR.FD` ownership check is hoisted to prefix/block decode and never fires
>   mid-block.
> - Therefore a task doing **FP SIMD** owns the FPU: `SR.VD` and `SR.FD` lazy save
>   are **coupled** for it. **Integer** SIMD (reductions to `MACL`/`MACH`) and
>   FPU-only tasks keep full independence. The blanket independence claimed below
>   is the pre-retirement design.
>
> This is a change of record inside this repository, not of code — there is no
> merged commit to cite, and per
> [../decisions/0002](../decisions/0002-supersede-convention.md) a
> `RESOLVED` marker would be wrong here. Rewriting the paragraph, rather than
> heading it, belongs to Wave-2 **B1**.
>
> The rest of §7 — `EXC_FPU_DISABLED`, the per-vCPU ownership flag, the lazy ABI,
> the 136-byte image — is unaffected and current, with the exception noted at
> [§7.1](#71-exc_fpu_disabled-cause-and-hedr-interaction).

The Tier 2 lazy-FPU-context-switch mechanism documented in this section
has a direct **SIMD parallel**: `SR.VD` (SR bit 13) and `EXC_SIMD_DISABLED`
(EXPEVT `0x1C0`, HEDR bit 24) implement the same trap-on-first-use idiom
for SIMD state. See [../simd/spec.md §2.6](../simd/spec.md) for the SIMD
mechanism, which mirrors §7.1–§7.3 of this section structurally.
The two facilities are **fully independent at the register-file level**:
SIMD never writes FR / DR / FPUL directly (it routes scalar FP through
its own VFPUL register, see [../simd/spec.md §2.3](../simd/spec.md)), so
the lazy ownership for SIMD and for the scalar FPU are tracked
independently. The only point of interaction is the four boundary
instructions in [../simd/spec.md §5.8](../simd/spec.md) (`FMOV.VS` /
`FMOV.VD` between VFPUL and FR/DR), which trap under both SR.VD and
SR.FD; SR.VD wins when both are set.

### 7.1 EXC_FPU_DISABLED cause and HEDR interaction. [T2]

Tier 2 introduces a dedicated exception cause code, **`EXC_FPU_DISABLED`**,
delivered when the Tier 1 SR.FD trap fires on a CPU that has the
hypervisor extension enabled.

**EXPEVT value.** `0x1B0`. This is the next unused slot in the
HEDR cause table per
[../hypervisor/hardware-spec.md §4.3](../hypervisor/hardware-spec.md),
which currently allocates:

> **SUPERSEDED BY [../hypervisor/hardware-spec.md §4.2](../hypervisor/hardware-spec.md) — 2026-08-25.**
> The table below is the **pre-reconciliation** allocation. `HCALL` no longer has
> `EXPEVT 0x180` and hyperprivileged-register access no longer has `0x1A0`: both
> squatted on stock SH-4 code points (general illegal, slot illegal) that a
> handler could not distinguish them from. Per [../hypervisor/hardware-spec.md §4.2](../hypervisor/hardware-spec.md) they moved to **`0x1D0`** and **`0x1F0`** respectively,
> and `0x180`/`0x1A0` reverted to their SH-4 meanings.
> `0x190` and `0x1B0` are unchanged, so **this section's own value, `0x1B0`, is
> still correct** — only the surrounding table is stale.
>
> This is a change of record inside this repository (the hypervisor extension is
> unimplemented in RTL), so there is no merged commit to cite and no `RESOLVED`
> marker is appropriate. Correcting the table belongs to Wave-2 **B1**.

| Code  | Cause                                                  |
| ----- | ------------------------------------------------------ |
| 0x040–0x130 | Existing SH-4 EXPEVT values                      |
| 0x180 | HCALL instruction  *(stale — now `0x1D0`, [hyp §4.2](../hypervisor/hardware-spec.md))* |
| 0x190 | Guest LDTLB/LDTLB.R trap                               |
| 0x1A0 | Hyperprivileged register access from non-HS mode  *(stale — now `0x1F0`, [hyp §4.2](../hypervisor/hardware-spec.md))* |
| 0x1B0 | **FPU disabled (SR.FD trap) — Tier 2** (new)           |

**HEDR delegation semantics.** Per the trap-entry logic in
[../hypervisor/hardware-spec.md §4.1](../hypervisor/hardware-spec.md),
when SR.HPRIV=0 and the FPU-disabled exception fires:

- If `HEDR[EXC_FPU_DISABLED bit] == 1`: the trap is **delegated to
  the guest's supervisor** — the guest's SR.MD=1 handler at the
  general-exception vector, with `EXPEVT` set to the FPU-disable
  cause (`0x800` general, `0x820` in a delay slot; §6.3). The guest
  sees a normal SH-4 FPU-disable trap and handles it however it
  wants (e.g. its own lazy-FPU model for guest user-space threads).
  *(This bullet read "at VBR + 0x800 or 0x820", which treated the
  two `EXPEVT` cause codes as vector offsets. SH-4 delivers both at
  the general-exception vector and discriminates with `EXPEVT` —
  [../hypervisor/hardware-spec.md §2.3.1](../hypervisor/hardware-spec.md)
  gives the vector for both rows as `+0x100`. Pre-existing; corrected
  while §6.3 was settling what these two codes mean.)*
- If `HEDR[EXC_FPU_DISABLED bit] == 0` (default): the trap goes to
  the **hypervisor** at VBR_HYP + offset(0x1B0). This is the case
  the lazy-FPU-context-switch ABI of §7.3 relies on.

The hypervisor configures HEDR per vCPU. A vCPU running a "FPU-aware"
guest OS that wants to manage SR.FD itself sets the delegation bit;
a vCPU where the hypervisor wants to monopolise FPU ownership
clears it.

**The HEDR bit position.** `EXC_FPU_DISABLED` (EXPEVT `0x1B0`)
occupies **HEDR bit 3** per the normative mapping in
[../hypervisor/hardware-spec.md §2.3.1](../hypervisor/hardware-spec.md).
The bit is delegatable: when `HEDR[3] = 1` the trap goes to the
guest's S-mode handler; when `HEDR[3] = 0` (default) it goes to
the hypervisor.

### 7.2 Per-vCPU FPU-ownership flag. [T2]

The hypervisor maintains, per vCPU control block, a boolean field:

```
struct vcpu {
    ...
    bool fpu_owned;          // does *this* vCPU currently own the
                             // physical FPU's architectural state?
    uint8_t fpu_image[136];  // saved FPU image when !fpu_owned
                             // and FPU state was previously dirty
    bool fpu_image_valid;    // false on first dispatch ever; true
                             // once any FPU state has been observed
    ...
};
```

In addition, the hypervisor maintains one **per-physical-CPU**
pointer:

```
struct pcpu {
    ...
    struct vcpu *fpu_owner;  // the vCPU whose FPU image is
                             // currently loaded in the physical FPU
                             // registers, or NULL if FPU is in
                             // post-reset state
    ...
};
```

The invariants:

- At most one vCPU per pCPU has its FPU state loaded into the
  physical FPU. That vCPU's `fpu_owned == true` and the pCPU's
  `fpu_owner` points at it.
- Every other vCPU has `fpu_owned == false`. Its FPU image is
  saved in `fpu_image[]` if `fpu_image_valid`, otherwise the vCPU
  has not yet observed FPU state and starts with the FPU reset
  default.

### 7.3 Lazy FPU context-switch ABI. [T2]

**On vCPU dispatch (hypervisor decides to run vCPU V on pCPU P):**

1. Hypervisor writes V's general-purpose register state, SR shadow,
   etc. into the physical registers.
2. Hypervisor **forces SR.FD = 1** in V's SR shadow before
   resuming V, regardless of what V's SR.FD was.
3. Hypervisor HRTEs into V. V runs.

**On first FPU instruction executed by V:**

4. CPU raises FPU-disabled trap with cause `EXC_FPU_DISABLED`.
5. HEDR delegation (§7.1) routes this trap to the hypervisor
   (because the hypervisor cleared the delegation bit on this
   vCPU's HEDR).
6. Hypervisor's `EXC_FPU_DISABLED` handler:
   - Reads `pcpu->fpu_owner`.
   - If `fpu_owner == V`: this is a redundant trap; should not
     happen, but defensively clear V's shadow SR.FD and HRTE.
   - If `fpu_owner != V` and `fpu_owner != NULL`: save the
     previous owner's FPU state. See §7.4 for the save sequence.
     Then mark `fpu_owner->fpu_owned = false`,
     `fpu_owner->fpu_image_valid = true`.
   - If `fpu_owner == NULL`: the physical FPU is in reset state; no
     save needed.
   - Restore V's FPU state. If `V->fpu_image_valid`: load from
     `V->fpu_image[]` (§7.4). Else: apply the [§7.7](#77-cross-tenant-fp-ownership-eager-switch-dirty-tracking-scrub-normative-t2)
     scrub — every architectural bit of the file takes rule FP-R1's
     defined value, not merely `FPSCR`.
     *(This branch previously read "FR/XF/FPUL = undefined per SH-4, but the
     hypervisor must write at least FPSCR to its default to ensure
     determinism" until 2026-09-09. That was
     [../security/threat-model.md §7.8](../security/threat-model.md)'s
     finding and **L6**'s second site: on a fresh vCPU the branch left
     the previous tenant's values in place. FP-R1 withdraws the word
     "undefined"; §7.7 is where the replacement and its argument are.)*
   - Mark `pcpu->fpu_owner = V`, `V->fpu_owned = true`.
   - Clear SR.FD in V's SR shadow (so the re-executed instruction
     does not re-trap).
   - HRTE to V. V re-executes the trapping instruction successfully.

**On vCPU pre-emption / migration to another pCPU:**

7. Hypervisor does **not** eagerly save the FPU state of the
   pre-empted vCPU. **This holds for a within-tenant pre-emption only,
   and is overridden at a cross-tenant gang switch by
   [§7.7](#77-cross-tenant-fp-ownership-eager-switch-dirty-tracking-scrub-normative-t2)
   rule FP-R5.** The save is deferred until step 6 triggers it,
   on the next pCPU that the FPU is contended on. If V never resumes
   (it exits), the FPU image is simply discarded.

**On vCPU migration to a different pCPU:**

8. The migrated vCPU arrives on pCPU P' with `fpu_owned == false`.
   pCPU P', the source pCPU, may still believe `fpu_owner == V`.
   The hypervisor must, as part of cross-pCPU migration:
   - Cross-call to the source pCPU to drop its `fpu_owner` pointer
     (and save the FPU image if `fpu_image_valid` was not already
     true at the time of pre-emption).
   - This is a one-time cost per migration and is dominated by the
     IPI latency, not the FPU save itself.

**Prior art.** This is the standard 4.4BSD lazy-FPU model (McKusick
et al. 1996), extended to vCPU granularity in the manner of
UltraSPARC II's HV-FPU bookkeeping (UltraSPARC II Programmer
Reference Manual, 1997). The trap-on-first-use mechanism dates to
the VAX (1977) FPACC trap.

### 7.4 Save / restore sequence (136-byte FPU image). [T2]

> **HISTORICAL 2026-08-25.** This section read **132 bytes** from its first
> draft until Wave-1 task B0c. The number was never consistent with the table
> below it. The heading and the terminator row both read 132, while the field
> sizes summed to 136 and the terminator's own offset was `0x88` — which *is*
> 136. The table therefore contradicted its own arithmetic, which is the
> discrepancy `context-image-sums` compares. The save sequence
> underneath had already collided as a result — `FPSCR` was stored to
> `@(132-4,r0)`, i.e. offset 128, on top of `FPUL`, with an in-line
> `; offset 128, oops, recompute` left in the listing. 136 is also what Linux's
> `struct sh_fpu_hard_struct` lays out (`arch/sh/include/asm/processor_32.h`:
> `fp_regs[16]`, `xfp_regs[16]`, `fpscr`, `fpul` — the trailing `status` word is
> software-only and not part of the architectural image). The corrected value is
> **136**; see `fpu.context.t2` in [../fact-ownership.md](../fact-ownership.md).

The Tier 2 FPU image is **136 bytes**:

| Offset | Bytes | Content                |
| ------ | ----- | ---------------------- |
| 0x00   | 64    | FR0..FR15 (16 × 4 B)   |
| 0x40   | 64    | XF0..XF15 (16 × 4 B)   |
| 0x80   | 4     | FPUL                   |
| 0x84   | 4     | FPSCR                  |
| 0x88   | —     | end (136 bytes)        |

**Save sequence (hypervisor view).** With SR.HPRIV=1 and SR.FD=0,
execute:

```asm
; Save FR0..FR15 from the front bank
mov.l   r0_save_base, r0
fmov.s  fr0,  @r0
fmov.s  fr1,  @(4,r0)
...
fmov.s  fr15, @(60,r0)
; Switch bank to access XF
frchg
; Save XF0..XF15 (now appearing as the front bank)
fmov.s  fr0,  @(64,r0)
fmov.s  fr1,  @(68,r0)
...
fmov.s  fr15, @(124,r0)
; Switch bank back
frchg
; Save FPUL and FPSCR
sts     fpul,  @(128,r0)     ; 0x80
sts     fpscr, @(132,r0)     ; 0x84 -- image ends at 0x88 = 136 bytes
```

(The asm above is illustrative; an implementation will use a tight
unrolled loop. With FPSCR.SZ=1 enabled before the loop, the
sequence shortens to 8 × FMOV.D + 8 × FMOV.D + 2 × STS.)

**Restore sequence:** symmetric, FMOV.S from memory to FRn / XFn,
LDS to FPUL and FPSCR. **Order matters for FPSCR.FR:** the
hypervisor must restore FPSCR last so the FR / SZ / PR bits are not
prematurely set; the bank-switch must be done with FRCHG while
restoring XF.

**Total cycle cost.** With FPSCR.SZ=1 and a one-cycle FMOV.D, the
save + restore sequence is about 60 cycles per direction, ~120
cycles round-trip. Plus the trap-entry / trap-exit overhead (~30
cycles each on the J32-OOO core). Total: roughly 200 cycles per
context switch, dominated by trap entry/exit, which is competitive
with the lazy-FPU costs reported on UltraSPARC II and contemporary
MIPS-class CPUs.

### 7.5 Trap-handler register-window convention. [T2]

The hypervisor's `EXC_FPU_DISABLED` handler runs at
SR.HPRIV=1, SR.MD=1, SR.BL=1, SR.RB=1 per the standard
hyperprivileged trap-entry logic
([../hypervisor/hardware-spec.md §4.1](../hypervisor/hardware-spec.md)).

- **HSPC** holds the offending FPU instruction's PC.
- **HSSR** holds the guest's SR at trap time (including SR.FD=1).
- The handler:
  1. Confirms cause == EXC_FPU_DISABLED.
  2. Performs the §7.3 ownership transition.
  3. **Clears the SR.FD bit in HSSR** (this is what enables the
     guest's re-execution to succeed). HSSR is then the SR value
     restored by HRTE.
  4. Executes HRTE; the guest re-executes the trapping FPU
     instruction at HSPC.

The handler runs with SR.BL=1 (blocking nested exceptions) per
standard hypervisor convention; it must complete its FPU
save/restore work and HRTE without taking another trap. The
save/restore sequence above is straight-line and predictable, so
this is achievable.

### 7.6 Migration and live-migration corner cases. [T2]

- **Live VM migration across hosts.** The hypervisor on the source
  host invokes its own save sequence on the FPU-owning pCPU (the
  source-pCPU IPI of §7.3 step 8), then ships the 136-byte image
  across the wire. The destination hypervisor stores it in the
  destination vCPU's `fpu_image[]` with `fpu_image_valid = true`.
  On first FPU instruction in the destination vCPU, the destination
  hypervisor restores from this image as if it were a normal lazy
  restore.
- **vCPU snapshot / checkpoint.** Identical to live migration but
  to disk; the 136-byte image is part of the vCPU's checkpoint
  blob.
- **Hypervisor self-use of the FPU.** The hypervisor should not use
  the FPU. If a hypervisor handler must (e.g. for a soft-decoded
  guest FP instruction), it must save and restore the current
  owner's FPU image around its use, or arrange ownership semantics
  identically to a guest. **Recommendation:** ban hypervisor FPU
  use entirely; route any in-hypervisor FP work to soft-float
  routines.

### 7.7 Cross-tenant FP ownership: eager switch, dirty tracking, scrub (normative). [T2]

**Wave-3 task C1b**, from [../j4-remediation-plan.md §C1](../j4-remediation-plan.md), argued
against [../security/threat-model.md §8](../security/threat-model.md)'s bar items **L3**, **L6**,
and **L1**'s added clause.

*It is here and not in `../decisions/` deliberately*, on
[../decisions/README.md](../decisions/README.md)'s rule that a decision goes inline when a spec
owns the thing decided. This document owns `FR`, `XF`, `FPUL` and `FPSCR`, and what is decided
here is what those registers contain at a change of owner. The two parts that are **not** this
document's are not here: the SIMD file is [../simd/spec.md §2.6.1](../simd/spec.md), which owns
`V0..V15`, `P0` and `VCSR`, and the requirement that a gang switch perform this at all is an item
in [../hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md), the spec that owns
gang switching. Wave-3 **C1a** split [../sq/spec.md §6.5](../sq/spec.md) the same way and for the
same reason.

#### The exposure

[../security/threat-model.md §1](../security/threat-model.md)'s adversary is a guest kernel handed
a core another tenant used. §7.3's restore branch handed it the previous tenant's registers. Until
this section it previously read:

> Else: reset the physical FPU to post-reset defaults (FPSCR = …, FR/XF/FPUL = undefined per
> SH-4, but the hypervisor must write at least FPSCR to its default to ensure determinism).

No speculation is involved and no timing is measured. The incoming tenant reads `FR0..FR15`,
`XF0..XF15` and `FPUL` with committed `fmov.s` / `flds` instructions and gets whatever the
outgoing tenant computed. §6.3's no-escape rule — every FP instruction traps under `SR.FD`, with
no control-only escape — is what makes this *only* reachable through the ownership handler, and
therefore what makes it look closed when it is not.

**Two branches reach it, and only one of them is the one §7.3 describes.**

1. **The no-image branch, in the hypervisor's own handler.** §7.3 step 6's `else` arm. A vCPU on
   its first dispatch ever has `fpu_image_valid == false`, so nothing is written over the file
   except `FPSCR`. This is [../security/threat-model.md §7.8](../security/threat-model.md)'s
   finding and **L3**'s named clause.
2. **The delegated branch, where the handler is not ours.** §7.1 offers `HEDR[3] = 1` as a
   per-vCPU configuration for "a vCPU running a *FPU-aware* guest OS that wants to manage SR.FD
   itself". With that bit set the `EXC_FPU_DISABLED` trap is delivered to the **guest's**
   supervisor handler, which clears `SR.FD` and proceeds. The hypervisor's §7.3 ownership
   transition never runs, so the file is not merely unrestored — it is untouched, for a tenant
   that asked to be given it. This branch is not in §7.8's list; it was found while writing this
   section, and it is the reason the fix below is anchored at the switch and not in a trap
   handler.

Both branches run in the *corruption* direction as well as the disclosure one: an FP value the
incoming tenant did not write is a wrong answer, not only a leak.

**What the file is not.** Unlike [../sq/spec.md §6.5](../sq/spec.md)'s queue buffers there is no
"undefined read" to close here, because there is no undefined *operation*: reading `FR7` is an
ordinary architectural read at every privilege level. The hole is entirely in what the register
*contains*, which is why the whole of this section is about the transition and none of it is about
the access.

#### The invariant

> **FP-INV.** At every instant, every bit of the physical FP register file — `FR0..FR15`,
> `XF0..XF15`, `FPUL`, `FPSCR` — is either a bit the file's current owner wrote since the file's
> last scrub, or the corresponding **scrub value** of FP-R1.

Stated as an invariant rather than as a sequence, for L6's reason: the failure mode of this class
of fix is a step that silently does not run, and a step is not checkable while a state is.

#### Where eager stops, and what makes the boundary safe

**Across tenants, eager. Within a tenant, lazy. The boundary is the change of the core's tenant,
and nothing else.**

- **Within a tenant** — a guest OS switching its own tasks, and a hypervisor switching between
  vCPUs *of the same guest* on one pCPU — §7.3's lazy ABI is unchanged, `SR.FD` still traps on
  first use, and `HEDR[3] = 1` remains a legitimate per-vCPU choice. Nothing in this section makes
  a within-tenant switch more expensive, because within a tenant there is no ownership change in
  the sense FP-INV means: the *tenant* still owns every bit in the file, and a tenant reading its
  own stale FP register is a bug in that tenant and not a boundary violation.
- **Across tenants** — the gang switch of
  [../hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md) — the outgoing tenant's
  state is saved if FP-R4 says it is dirty, and the file is then **scrubbed unconditionally**
  before the incoming tenant's first instruction. The incoming tenant's image, if it has one, is
  restored over the scrub.

**What makes the boundary safe is that it is the only boundary there is.**
[../hypervisor/hardware-spec.md §4.7](../hypervisor/hardware-spec.md) makes a physical core the
unit of guest allocation at any instant, so the physical FP file can pass from one tenant to
another *only* at a gang switch. That is a load-bearing dependency and not a convenience: if
cross-tenant fine-grained MT were ever allowed, the file would change tenant between two
instructions of the barrel and this section would be unimplementable at any cost. **L1 is
therefore a precondition of L3 here, not a parallel requirement.**

**What observes it** is three things, in descending order of how much they can be forgotten:

1. FP-R3 makes the scrub a *hardware effect of a state write the switch already performs*, so it
   cannot be omitted independently of omitting the ownership change itself.
2. [../hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md) carries it as a
   numbered item, so a reader of the gang-switch list sees it.
3. The residue tests below, which are what **L3** and **L6** actually accept as evidence.

**The file is per thread context.** On an FGMT implementation every thread context has its own
`FR`/`XF`/`FPUL`/`FPSCR`, for the same reason it has its own ARF: two vCPUs of one guest running
concurrently would otherwise silently overwrite each other's FP state, which is a correctness
failure before it is a security one. This is stated here because
[../ooo/j32lt-spec.md §9.1](../ooo/j32lt-spec.md)'s per-thread-context table has no row for an FP
file — correctly, since no FPU exists — and a later reader must not read that absence as a
decision that the file is shared.

#### The rules (normative)

**FP-R1 — The scrub value is defined, and "undefined" is withdrawn.** The scrub value is **zero**
for `FR0..FR15`, `XF0..XF15` and `FPUL`, and the §6.4 reset value for `FPSCR`. §7.3's
"FR/XF/FPUL = undefined per SH-4" is **withdrawn**: those registers are zero at every point FP-INV
calls scrubbed, and a guest that reads one without writing it reads a positive zero.

Three reasons for zero rather than for a recognisable pattern or for leaving it to the
implementer:

- Zero is a valid single- and double-precision `+0.0`, so a scrubbed register cannot raise an
  invalid-operation or denormal `Cause` bit on first use and cannot make FP-R1 observable as a
  trap the guest would not otherwise take.
- Zero is what the guest kernel already writes for a task that has never used the FPU:
  `linux@origin/jcore` `arch/sh/kernel/cpu/fpu.c` `init_fpu()` does `memset(fp, 0, xstate_size)`
  over `struct sh_fpu_hard_struct` and then sets `fpscr`. A hardware scrub to zero is
  indistinguishable from the state the OS would have installed itself, so it can regress no
  conforming software.
- SH-4 calls these registers undefined at reset, which is exactly the licence
  [../security/threat-model.md §8](../security/threat-model.md)'s **L6** bans an implementer from
  taking. "Post-reset defaults" is therefore *not* an adequate answer on its own; the reset
  default has to be given a value first, and FP-R2 gives it one.

**FP-R2 — Reset.** Out of reset the file holds the FP-R1 values and `FPDS` is `00`. This is a new
requirement: §6.4 gives `FPSCR` a reset value and nothing gave the register file one.

**FP-R3 — Scrub on ownership installation.** A hyperprivileged write of `FPDS` = `00` applies
FP-R1 to the whole file — both banks, `FPUL` and `FPSCR` — in the same step as the write.
Unconditional, idempotent, no transition detection, no new instruction, no new trap. **The scrub
is never skipped**, including when `FPDS` was already `00`: FP-R4's state is what a *switch* may
use to skip the save, and it is deliberately not an input to FP-R3, because a scrub that consults
a state bit is a scrub that a wrong state bit turns off. **The scrub is not an architectural write
and does not itself set `FPDS` = `10`**; the write that performs it leaves `FPDS` = `00`.

Three consequences, and the third is the one this task exists for.

1. The gang switch writes `FPDS` = `00` for every context because that write *is* how it records
   that the physical file no longer belongs to the outgoing vCPU — the hardware form of §7.2's
   `pcpu->fpu_owner = NULL`. The bookkeeping and the scrub are one write, which is the difference
   between a control and a line on a checklist.
2. A restore, if there is one, follows and overwrites the whole file, ending with `FPDS` = `01`.
   A queue-shaped partial restore is impossible here because the image of §7.4 covers every
   architectural bit.
3. **A fresh vCPU with no saved image is covered by construction.** The `FPDS` = `00` write of
   consequence 1 has already happened on the outgoing side, so the fresh context finds a scrubbed
   file and there is simply no restore after it. *(That sentence read "Its restore is the scrub and
   nothing else", which reads as siting the write inside the restore; it is not, and
   [../hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)'s ordering paragraph had
   taken it that way and generalised it to all three writes. Corrected post-F, 2026-09-10 — the
   mechanism is unchanged, the placement is now stated once.)* The no-image branch is not a second
   code path that could be forgotten; it is the same write with no restore after it. This is the branch
   [../security/threat-model.md §7.8](../security/threat-model.md) identifies and that **L3**
   requires as its own test case, and it is why FP-R3 is not conditioned on there being an image.

**FP-R4 — `FPDS`, the two dirty bits.** `FPDS[1:0]` is a per-thread-context field, readable and
writable only at `SR.HPRIV = 1`, with no guest-visible encoding at all:

| `FPDS` | Name | Meaning | What a switch away may skip |
|---|---|---|---|
| `00` | **RESET** | the file holds the FP-R1 values | the save |
| `01` | **CLEAN** | the file holds exactly the current owner's saved image | the save |
| `10` | **DIRTY** | the current owner has written the file since it became `00` or `01` | nothing |
| `11` | reserved | treated as `10` | nothing |

- **Hardware sets `FPDS` = `10` on any architectural write to any of `FR`, `XF`, `FPUL`, `FPSCR`,
  from any mode**, including a write by hyperprivileged software. Mode-independence is deliberate:
  a rule of the form "except when the hypervisor is restoring" is transition detection wearing a
  different hat, and the restore ends with an explicit `FPDS` write anyway.
- **The SIMD FP datapath is one of those writers, and it is the one an implementer will miss.**
  A governed FP operation under `VCSR.IEE = 1` OR-accumulates into `FPSCR.FLAG`
  ([../simd/spec.md §2.4.1](../simd/spec.md)); that is an architectural write to `FPSCR` and sets
  `FPDS` = `10` exactly as `LDS Rm,FPSCR` does. Named here because `simd/spec.md` §2.1 used to
  say no SIMD instruction writes `FPSCR` at all, and an implementer who believed it would leave
  `FPDS` reading CLEAN over a file the SIMD unit had modified — wrong in the direction the `11` →
  `10` rule below exists to forbid.
- **Only a hyperprivileged write clears it.** No guest instruction reads or writes `FPDS`, so it
  adds nothing to any guest-visible ABI and nothing to the SH-4 surface a guest can probe.
- **`11` is read as `10`, and the direction is the point.** An unknown or corrupted state must
  mean *the file may hold something*, never *the file is clean*: the fail-safe reading forces a
  save and a scrub. A design in which the fail-safe direction is "clean" is one bit-flip from
  FP-INV.

**`FPDS` is not per-vCPU state and must not join
[../hypervisor/hardware-spec.md §2.9](../hypervisor/hardware-spec.md)'s save/restore list.** The
test that section already applies to `HLE` applies here and gives the same answer: ask whether a
vCPU resumed on a different pCPU would be *wrong* if the bit were lost. It would not, because the
incoming context's `FPDS` is **written** by the installation that resumes it — `00` for a scrub,
`01` after a restore — and never read from the outgoing vCPU. `FPDS` describes the **physical
file**, of which there is one per thread context, in exactly the way §7.2's per-pCPU `fpu_owner`
describes the physical FPU and the per-vCPU `fpu_owned` does not.

**This is where C1a's rejected mask and these two bits part company, and the difference is worth
stating because the surface reasoning is identical.** [../sq/spec.md §6.5](../sq/spec.md) rejected
a per-word valid mask *as the specified mechanism* because the mask recorded **which words the
owner had written** — information about the owner, which must survive the owner's absence, and
which therefore had to join the context image and reopen a register layout. `FPDS` records
**whether the file currently differs from the image** — information about the file, which is
meaningless the moment the file is handed to someone else, and which the next owner's
installation overwrites. So the two bits cost **no bytes in the §7.4 image**, no change to §7.4's
field table, and no row in
[../hypervisor/hardware-spec.md §2.9](../hypervisor/hardware-spec.md). What they do cost is two
flip-flops per thread context, and that is stated in the cost list below rather than netted out.

**FP-R5 — Eager across tenants, lazy within, and the trap is not the mechanism.** A cross-tenant
transfer of the file **MUST NOT** depend on the incoming tenant executing an FP instruction. §7.3
step 7's "the hypervisor does **not** eagerly save the FPU state of the pre-empted vCPU" stands
for a within-tenant pre-emption and is **overridden at a gang switch**, where the save (if
`FPDS` = `10`) and the scrub both happen before the incoming guest's first instruction. Two
independent reasons, either sufficient:

- The first-use trap may be **delivered to the guest**, not to the hypervisor, whenever
  `HEDR[3] = 1` (§7.1). A safety property that a per-vCPU configuration bit can switch off is not
  a safety property. With FP-R3 in place, `HEDR[3] = 1` becomes safe again, because the file the
  guest's own handler finds has already been scrubbed.
- [../security/threat-model.md §7.2](../security/threat-model.md) is explicit that this core is
  not non-speculative even in the in-order class. A mitigation that runs *at* the first FP
  instruction is racing whatever the machine did before it retired.

**FP-R6 — Guest reads of a scrubbed, unwritten register are defined.** They return the FP-R1
value. This is a consequence of FP-INV rather than an extra rule, and it is written down because
**L6**'s evidence bar is phrased as a read: a tenant must be able to read every architectural FP
register and find a defined value.

**FP-R7 — The hypervisor does not use the FPU.** §7.6 already recommends banning hypervisor FP
use; FP-INV makes it normative, for
[../sq/spec.md §6.5](../sq/spec.md) rule SQ-R6's reason in this subsystem. `FPDS` cannot
distinguish host bytes from a restored image, so a file the hypervisor filled for its own purposes
and left marked `01` would be handed to a guest as that guest's own context, and the bytes
disclosed would be the TCB's ([../security/threat-model.md §2](../security/threat-model.md)).
This is a discipline on the TCB rather than a hardware guarantee, and it is written down because
it is otherwise invisible.

**FP-R1, FP-R2 and FP-R6 are not conditional on the hypervisor extension.** Tier 1 has an FPU and
no hyperprivileged mode; there the only ownership change is reset, R2 covers it, and R1 gives the
register file the defined reset contents SH-4 never gave it. FP-R3, FP-R4, FP-R5 and FP-R7 have no
meaning without Tier 2 and are not required of a Tier 1 part.

#### What discharges the bar, and what does not

**L6** and **L3** both demand a residue test written as *tenant A stores a recognisable pattern;
tenant B reads and must not see it*, each demonstrated **red before the fix**. For this site that
is four tests, and the last three are the ones that get skipped.

| # | Test | What it recovers if the rule is absent |
|---|---|---|
| 1 | Tenant A writes a distinct pattern to `FR0..FR15`, `XF0..XF15` and `FPUL` and is gang-switched out. Tenant B reads all thirty-three. | A's values — FP-R3 absent altogether |
| 2 | **Tenant B is a fresh vCPU with no saved image**, then runs test 1's reads. | A's values, *with test 1 green*, on any implementation whose scrub is conditioned on there being an image to restore |
| 3 | **The bank that is not in front.** A writes only `XF0..XF15` (via `FRCHG`) and leaves `FPSCR.FR` as it found it; B reads `XF` via `FRCHG`. | A's back bank, *with tests 1 and 2 green*, on any implementation that scrubs "the sixteen visible registers" |
| 4 | **The tenant that never touches FP.** A uses the FPU heavily; B executes no FP instruction until after a second gang switch to tenant C, which reads the file. | A's values, on any implementation that scrubs in the first-use trap handler or under `HEDR[3] = 1` delegates that handler to the guest |

Tests 3 and 4 exist because FP-R3's trigger was chosen so that all four exercise **one** hardware
behaviour rather than four paths of which one is tested. Test 4 is the cross-tenant analogue of
**L3**'s "eager or scrubbed" and is the test that fails a design built out of §7.3's trap.

**L1's added clause is discharged in another document, deliberately.**
[../hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)'s gang-switch list now
carries the FP/SIMD scrub as a numbered item alongside C1a's store-queue one. A scrub specified
here and absent from *that list* would leave L1 unmet while looking finished — the failure
[../security/threat-model.md §8](../security/threat-model.md) predicts for this pair of tasks by
name, and the one C1a had to avoid first.

#### Minimizing the loss ([../j4-remediation-plan.md §E.10](../j4-remediation-plan.md), gated by §D3)

The guarantee to be bought is FP-INV, and this is the one Wave-3 mechanism with an obvious price:
it moves work from *when needed* to *every cross-tenant switch*. Five options were priced.

**Chosen: dirty-gated eager save, unconditional hardware scrub.** The scrub is a broadside write
of a constant into storage that must exist anyway; the *save* — the expensive half, since it is a
copy to memory — is skipped entirely when `FPDS` is `00` or `01`. Structurally the scrub covers
`(16 + 16 + 1 + 1) × 32 = 1,088` bits per thread context, a structural count and not a
measurement, and the lever is the one §E.10 names, "per-register zero bit = 1-cycle zeroing".

**Rejected: unconditional eager save and restore at every gang switch**, which is what "eager"
means read literally. It copies the §7.4 image and
[../simd/spec.md §2.5](../simd/spec.md)'s SIMD image for every context of the core on every
switch, including for a tenant that never executed an FP or SIMD instruction — and on a
four-context J32-LT that is four of each. It buys nothing FP-R3 does not: the scrub is what makes
the file safe, and the save only preserves work the outgoing tenant may want back. `FPDS` exists
to separate those two, and this option is the measurement baseline against which the two bits have
to justify themselves — see the experiment's second kill criterion.

**Rejected as the specified mechanism, and permitted as an implementation: a per-register valid
bit** — thirty-four bits per thread context for the FP file — with a read of an invalid register
returning the FP-R1 value and the scrub clearing the bits rather than the storage. It buys FP-INV
for a clear of thirty-four flip-flops instead of a clear enable across 1,088, and it is the better
answer if the file is block RAM, where a broadside clear is unavailable. It is rejected as the
*specified* mechanism because FP-INV should not name a storage technology, not because it is
unsafe.

**And here it does not carry C1a's condition, which is worth saying because the reasoning looks
identical and is not.** [../sq/spec.md §6.5](../sq/spec.md) permitted its rejected mask only on
condition that an implementation choosing it saved the mask as context, because the store queue's
`PREF` burst publishes bytes the owner never wrote — so *which* words were written was
guest-observable and had to survive the switch. Nothing in the FP file is guest-observable at word
granularity: a register the owner never wrote reads as the FP-R1 value under either mechanism, and
§7.4's save reads all thirty-four registers unconditionally, so an image taken with valid bits
clear is a correct image of zeros. **A per-register valid bit therefore needs no saving and adds
no context state.** The difference is the publish primitive, not the register count.

**Rejected: scrub in hypervisor software** — thirty-four stores per context in the switch path, no
RTL change. Rejected on L6's own argument, that a scrub which silently does not happen produces no
fault, and on a second ground: FP-R1, FP-R2 and FP-R6 bind a **Tier 1** part that has an FPU and
no hyperprivileged mode at all, where there is no hypervisor to run the loop.

**Rejected: scrub inside the `EXC_FPU_DISABLED` handler**, which is where §7.3 already does its
ownership work and so looks free. This is FP-R5's case: the handler is delivered to the *guest*
under `HEDR[3] = 1`, and it runs only if the incoming tenant executes an FP instruction, which
test 4 above is built to catch. It is the LazyFP shape, and
[../security/threat-model.md §7.8](../security/threat-model.md) already records that this design
is worse than LazyFP because it needs no transient window.

**The movmu-style bulk save is a code-density mechanism, not a throughput one, and §E.10 bundles
it as though it were both.** `movmu.l` is live on J2A and SH-2A — `jcore-cpu@origin/master`
decodes `0100mmmm11110000` and `0100nnnn11110100` in `decode/decode_core.vhm` — and
[../isa-density/hardware-impl.md §5.1](../isa-density/hardware-impl.md) is explicit that it adds
**no datapath**, only sequencing: one 32-bit memory operation per step, exactly as many bus cycles
as the unrolled equivalent. An FP analogue would therefore save instruction fetch and I-cache
footprint, and could be made non-interruptible so the sequence cannot be split — both real — but
it would **not** reduce the data movement, which is what an eager switch actually costs. The
ordering of levers here is `FPDS` first (it removes the copy), the broadside scrub second (it
removes the scrub's cycles), and bulk-move encoding third. **No encoding is allocated by this
section.** `jcore-cpu/docs/insns.json` is the single writer under
[../decisions/0003](../decisions/0003-canonical-encoding-database.md) and an FP bulk-move
instruction is an encoding change owned by that database and by Wave-2 **B4** — which additionally
left `movmu`'s `m = 15` anchor unconfirmed against SH-2A for want of a manual
([../encoding-sweep.md §4](../encoding-sweep.md)), so no anchor semantics are relied on here.

**What this costs, and what is not known.**

- **Per within-tenant switch: nothing.** No rule in this section fires.
- **Per cross-tenant switch, per thread context:** one `FPDS` write, whose scrub side effect is
  FP-R3; plus §7.4's save **only** when `FPDS` = `10`. How often a tenant leaves the file dirty at
  a quantum boundary is `unknown at this stage — needs measurement`.
- **Per FP instruction:** the `FPDS` = `10` set on any write to the file. Whether it lands on the
  critical path is `unknown at this stage — needs measurement`.
- **Area:** two flip-flops per thread context, plus a clear enable on a register file that does
  not exist yet. The gate cost is `unknown at this stage — needs measurement`.
- **§E.10's conclusion is about a class and is not a number for this mechanism.** It prices "eager
  state switch + scrub" as sub-1% on this core, which is why this design has the *shape* it has —
  cross-tenant only, dirty-gated copying, a data-path clear rather than a software loop. It is
  `LITERATURE` on [../security/threat-model.md §9](../security/threat-model.md)'s provenance
  scale, it is not evidence about the FP file, and no percentage is stated here for one.

**The experiment that would settle it.** Human-gated: this design prepares it and a person runs
the board ([../j4-execution-plan.md §5](../j4-execution-plan.md)). **None of the three can be run
today** — there is no FPU to build with or without the mechanism — so each is stated as a gate on
the task that first builds a Tier 1 FPU, in the same position C1a left the store queue.

1. **Synthesis A/B.** Build the FP register file with and without FP-R3's clear enable and FP-R4's
   two flip-flops; `yosys` + `nextpnr-ecp5` targeting the ULX3S 85F. Report ΔLUT4, ΔFF, ΔEBR and
   `Fmax` against the CI floor of [../platform-baseline.md §3](../platform-baseline.md).
   *Kill criterion:* if the broadside clear puts the build under the floor, take the per-register
   valid-bit variant, which is permitted above and costs no context state.
2. **Is `FPDS` worth its own existence.** Gang-switch cost under a two-guest schedule from the PMU
   cycle counter, with the guests chosen so one never touches FP: dirty-gated save versus the
   rejected unconditional eager save. *Kill criterion:* if the gated save is not measurably cheaper
   on the FP-free guest, **delete `FPDS`** and specify the unconditional save. The two bits exist
   only to buy that difference, and complexity that buys nothing measurable is a defect and not a
   safety margin.
3. **Per-instruction cost of the dirty set.** `Fmax` and IPC on an FP-dense loop with and without
   the FP-R4 write-enable. Expected to be unmeasurable — it is a fan-out to one flip-flop — and run
   to confirm that rather than to assume it.

#### Implementation status: specified, not built

**There is no FPU and no SIMD unit in `jcore-cpu`, so nothing in this section is met because it
has been written.** Re-checked 2026-09-09 against `jcore-cpu@origin/master` (`e8a5a4e1`),
case-insensitively throughout, because VHDL is case-insensitive and `git grep` is not:

- No `*.vhd`/`*.vhm` file matches `entity fpu`, `component fpu`, `entity simd` or
  `component simd`; none matches `fpscr`, `fpul` or `vcsr`; no path under the tree contains `fpu`,
  `simd` or `float`. The three `float` hits in `core/cpu.vhd` are comments about an *undriven*
  signal and are not floating point.
- `linux@origin/jcore` (`128e8958`) does not build the kernel's FPU support on this target at all:
  `arch/sh/Kconfig`'s `CPU_SUBTYPE_JCORE` does not `select CPU_HAS_FPU`, `CONFIG_SH_FPU` therefore
  cannot be set, and `arch/sh/include/asm/fpu.h` compiles `save_fpu`, `restore_fpu` and
  `unlazy_fpu` to `do { } while (0)`.

Three consequences, so that nothing here reads as a closure:

- **L6's FP/SIMD site moves from a specified "undefined" to a specified scrub, and no further.**
  Its evidence bar is the four residue tests above, each demonstrated red before the fix, and
  there is no hardware to run them red on.
- **FP-R1..FP-R7 must land with the Tier 1/Tier 2 FPU, not after it.** What unblocks the
  implementation half of C1b is the FPU itself. The reason is C1a's reason in another subsystem:
  [../sh4-guest-model.md §4](../sh4-guest-model.md)'s Decision B2-4 traps guest FP precisely
  because no FPU exists, and the moment an FPU is enabled on a hypervisor-bearing variant the
  exposure above becomes live — there is no intermediate state in which a guest would notice the
  scrub was missing.
- **Guest FP is trapped and emulated today**
  ([../sh4-guest-model.md §4](../sh4-guest-model.md), Decision B2-4), so the file the guest sees is
  the VMM's software state and not this one. That is why the exposure is latent rather than
  shipping, and it is not a mitigation: it is the absence of the hardware the mitigation is for.

**Prior art, pre-2006.** Two bits recording *has been referenced* and *has been changed*, read by
supervisor software to decide whether a block must be written back before it is reassigned, are
IBM System/370 (1970) storage keys — the same mechanism [../sq/spec.md §6.2](../sq/spec.md) and §7
already cite for the other half of this design, applied to a register file rather than to a page
frame. Eager state exchange at a protection-domain boundary with lazy switching inside the domain
is the Multics (1965) ring-crossing discipline. The object-reuse requirement that storage assigned
to a subject contain no information produced by a prior subject is TCSEC (DoD 5200.28-STD, 1985)
from class C2 upward. The trap-on-first-use idiom being *retained* inside the tenant is the
VAX (1977) FPACC trap and 4.4BSD (McKusick et al. 1996), which §7.3 already cites. Nothing here is
new except which structure the rules are applied to.

---

## 8. IEEE-754 conformance target (per tier)

The conformance contract is unchanged from the archived j2-spec.md
§8 (which targeted SH-4 binary compatibility under the Tier 0
subset). Tier 1 extends it to the full SH-4 surface; Tier 2 adds no
new conformance obligations beyond Tier 1.

### 8.1 Tier 0 conformance

(Reproduced from j2-spec.md §8; see the archived document for the
full discussion of Cause.E hardware/software co-design and qemu
differential testing.)

| Aspect                  | Target                                                 |
| ----------------------- | ------------------------------------------------------ |
| Formats                 | binary32, binary64                                     |
| Rounding modes          | RM=00, RM=01; RM=10/11 treated as round-to-zero        |
| Reset rounding mode     | RM=01 (round-to-zero); SH-4-compatible                 |
| Denormals               | DN=1 flush-to-zero; DN=0 trap via Cause.E              |
| Default qNaN (single)   | 0x7FBFFFFF (SH-4 default)                              |
| Default qNaN (double)   | 0x7FF7FFFFFFFFFFFF (SH-4 default)                      |
| qNaN convention         | mantissa MSB=0 → qNaN (SH-4 / MIPS style)              |
| FCMP with NaN           | T=0; set V flag                                        |
| Exception traps         | precise; SPC = offending instruction                   |
| FMAC                    | single-precision only; non-fused                       |

### 8.2 Tier 1 additions

| Aspect                  | Target                                                 |
| ----------------------- | ------------------------------------------------------ |
| FIPR accuracy           | max error ≤ 2E (E = error of FP32 mul + 3 adds);       |
|                         | SH-4 manual section 9.41                               |
| FTRV accuracy           | per-row equal to FIPR; SH-4 manual section 9.52        |
| FSCA accuracy           | max absolute error ≤ 2⁻²¹; SH-4A manual                |
|                         | (verify against manual; some sources say 2⁻²²)         |
| FSRRA accuracy          | max relative error ≤ 2⁻²¹; SH-4A manual                |
| FRCHG/FSCHG/FPCHG       | single-cycle bit toggle; no IEEE-754 effect            |
| SR.FD trap precision    | precise; SPC = offending FPU instruction PC            |
| SR.FD in delay slot     | SPC = branch PC; standard SH-4 behaviour               |

### 8.3 Tier 2 additions

No new IEEE-754 conformance requirements. The Tier 2 contract is
software-mechanical (lazy save/restore, HEDR delegation); it does
not change observable arithmetic. A Tier 2 implementation produces
bit-identical FPU outputs to a Tier 1 implementation on the same
input sequence, regardless of how often the lazy-FPU mechanism
triggered intermediate save/restores.

---

## 9. Test plan summary

### 9.1 Tier 0 tests

Inherited from j2-spec.md §9:

1. Block TAP testbenches per FPU sub-block.
2. IEEE-754 vector-driven tests using TestFloat-derived vectors.
3. ISA-level assembly tests under `testrom/tests/`.
4. Differential testing against qemu's post-2017 `target/sh4`.

### 9.2 Tier 1 tests (additions)

5. **FIPR / FTRV regression** against a reference C model that
   computes the dot product / matrix multiply in extended precision
   and rounds once. Tolerance band per the SH-4 manual's
   "approximate inner product" wording.
6. **FSCA / FSRRA accuracy sweeps**: 10⁵ inputs sampled uniformly
   over the input range, compare against host-computed double-
   precision reference, verify the 2⁻²¹ accuracy bound holds.
7. **SR.FD trap timing**: assemble an FPU instruction following an
   `LDC` that sets SR.FD=1, verify the trap fires on the FPU
   instruction (not on the LDC, not on a later instruction) and
   SPC matches the FPU instruction's PC.
8. **SR.FD in delay slot**: FPU instruction in the delay slot of a
   branch with SR.FD=1, verify SPC = branch PC per SH-4
   convention.
9. **FRCHG / FSCHG / FPCHG under SR.FD**: control instructions
   must also trap; verify no silent toggle when SR.FD=1.
10. **Double-FMOV halves**: `FMOV @Rm, DRn` with `FPSCR.SZ=1` must load
    the word at `Rm` into FRn as the **high** half of the binary64 and
    the word at `Rm+4` into FR(n+1) as the low half, at every tier
    (§4.3). A test asserting the little-endian order is asserting a
    migration this document withdrew (§6.2).

### 9.3 Tier 2 tests (additions)

11. **Lazy FPU trap-on-first-use**: dispatch vCPU A (no FPU use),
    dispatch vCPU B (uses FPU), dispatch vCPU A again (uses FPU);
    verify trap fires on A's first FPU instruction after redispatch
    and that A's saved image is restored byte-for-byte.
12. **Migration save**: pre-empt vCPU B, dispatch on a different
    pCPU; verify the source pCPU's `fpu_owner` is dropped and the
    image is saved via the cross-call mechanism.
13. **HEDR delegation**: set HEDR's `EXC_FPU_DISABLED` bit for a
    vCPU, verify the SR.FD trap is delivered to the guest's
    supervisor handler at VBR + offset, not to the hypervisor.
14. **136-byte image round-trip**: save FPU state, perturb registers,
    restore, verify all 136 bytes round-trip bit-exact.
15. **Live-migration replay**: ship a 136-byte image to a separate
    instance of the hypervisor, restore, run a known FPU sequence,
    compare with the source instance's continuation. Must be
    bit-identical.

---

## 10. Open questions / TBDs

1. **~~SR.FD bit-position collision with J-Core SR.MD~~ — RESOLVED
   (2026-05-26).** The hypervisor spec §2.1 has been corrected to
   match the SH-4 manual verbatim for all inherited bits: MD bit 30,
   RB bit 29, BL bit 28, FD bit 15, M bit 9, Q bit 8, IMASK bits 7:4,
   S bit 1, T bit 0. The J-Core-specific SR.HPRIV bit was relocated
   from bit 9 (which collided with SH-4 M) to bit 14 (an
   SH-4-reserved bit). FD remains at bit 15 as the SH-4 manual
   specifies. No further action required.
2. **FSCA accuracy bound: 2⁻²¹ or 2⁻²²?** §6.8 and §8.2 state
   2⁻²¹; some SH-4A references state 2⁻²². Verify against the
   primary SH-4 / SH-4A hardware manuals and update both sections.
   Owner: FPU spec editor.
3. **~~HEDR bit-to-EXPEVT mapping~~ — RESOLVED (2026-05-26).**
   The hypervisor spec [§2.3.1](../hypervisor/hardware-spec.md) now
   carries the normative EXPEVT-to-HEDR-bit table. `EXC_FPU_DISABLED`
   (`0x1B0`) occupies **HEDR bit 3** and is delegatable. Any
   references in this document to "HEDR slot 11" or other interim
   bit numbers are obsolete; see §2.3.1 of the hypervisor spec for
   the authoritative mapping.
4. **FSCA: angle-units bit width.** §6.8 pseudocode hedges between
   "16.16 fraction of a turn" and "low 16 bits ignored". Verify
   against the SH-4A manual which describes the FPUL interpretation
   most concretely.
5. **Hypervisor FPU use ban: enforce in RTL or in software?** §7.6
   recommends no hypervisor FPU use. Option: emit a warning when
   SR.HPRIV=1 and an FPU instruction is decoded, *without* trapping
   (so legitimate save/restore sequences in the EXC_FPU_DISABLED
   handler work). Owner: hypervisor + FPU spec.
6. **FTRV-source XF bank vs front bank.** §6.7 fixes XMTRX to the
   XF back bank. SH-4 manual confirms this. Verify that
   FPSCR.FR=0 (the J-Core reset state) puts XF in the back bank
   consistently across Tier 1 implementations (it does in the SH-4
   reference; recheck on first-silicon Tier 1.)
7. **Single-FPU-shared-across-cores vs per-core FPU on J32-OOO and
   J32-FM.** [../jcore-ulx3s-service-plan.md §6.7](../jcore-ulx3s-service-plan.md)
   says "single FPU shared across cores via coprocessor bus
   arbitration (not duplicated per core, per the OoO design
   philosophy)". This document specifies the FPU as if it were
   per-core. The shared-FPU pattern is compatible with §7's
   per-vCPU model (substitute "pCPU" with "FPU port" in §7.3) but
   the cross-pCPU IPI in §7.3 step 8 becomes a coprocessor-bus
   arbitration round-trip. Owner: J32-FM spec editor.
8. **Tier 2 + Tier 0 SIMD interaction.** SIMD horizontal reductions
   write to FR0 / DR0 / FPUL ([../simd/spec.md §2.3](../simd/spec.md)).
   A SIMD instruction is an FPU-touching instruction; should it
   raise EXC_FPU_DISABLED under SR.FD=1? Yes by analogy. Confirm
   with the SIMD spec and add the trap to the SIMD instruction's
   formal semantics. Owner: SIMD + FPU spec joint review.

---

## 11. Revision history

- **2026-09-09 — Wave-3 C1c** (no version bump; §7.7 landed the same day for
  Wave-3 **C1b** without one either, and inventing a number for someone else's
  change retroactively would be worse than the gap). §6.3's no-escape rule had
  one: a SIMD block containing any FP operation reads `FPSCR.RM` and, under `VCSR.IEE = 1`,
  writes `FPSCR.FLAG`, and `simd/spec.md` required FPU ownership only for the
  FR/DR writeback of a horizontal reduction. §6.3 now names the SIMD case and
  points at [../simd/spec.md §2.4.1](../simd/spec.md), which owns the rule;
  §7.7's FP-R4 names the SIMD FP datapath as a `FPSCR` writer, which its
  dirty-bit logic must be wired to. New §6.3.1 states the kernel-`fpu`
  discipline for the FP file: the ban that `arch/sh` already implements, the
  three things `arch/sh` owes if the ban is lifted, and the exit scrub that no
  other architecture needs because no other architecture's return-to-user path
  is a lazy branch that may write nothing.
- **v1.1 (2026-08-25).** The Tier-2 FPU image is **136 bytes**, not 132.
  Corrected in §7.4 (which carries the detail as a `HISTORICAL` note), §1.1,
  §7.2's `fpu_image[]`, §7.6, §9.3 and Appendix A, and in
  [../hypervisor/hardware-spec.md §4](../hypervisor/hardware-spec.md) and
  [../hypervisor/linux-spec.md §5](../hypervisor/linux-spec.md). What was
  self-contradictory was the §7.4 table's **arithmetic**, not one stray
  headline: the heading *and* the terminator row both read 132, while the field
  sizes summed to 136 and the terminator's own offset was `0x88` — which is 136.
  That is why the check catches it: it compares the stated total against the
  offset the fields actually reach, and those two had never agreed. The save
  sequence below had already been driven into storing `FPSCR` on top of `FPUL`
  to fit the wrong budget. §1.1 additionally said "32 × FR", which no section of
  this document supports — the front and back banks are 16 registers each.
  Found by the Wave-1 **B0c** `context-image-sums` check.
- **v1.0 (2026-05-25).** Tiered SH-4-complete consolidation.
  Supersedes the archived J2-only `docs/fpu/archive/j2-spec.md`
  (v0.4). Adds Tier 1 (FIPR, FTRV, FSCA, FSRRA, FPCHG, full SR.FD
  semantics, full FPSCR layout, and — withdrawn 2026-09-07 by
  [decisions/0006](../decisions/0006-endianness-is-big-endian.md) — an
  endianness migration to LE) and
  Tier 2 (EXC_FPU_DISABLED HEDR cause, per-vCPU FPU-ownership
  flag, lazy FPU context-switch ABI, 136-byte FPU image). Updates
  cross-references in
  [../hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md),
  [../simd/spec.md](../simd/spec.md), and
  [../ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md) to point at this
  document. Open questions §10 reflect the unresolved SR.FD
  bit-position collision with SR.MD and the FSCA accuracy bound
  ambiguity.
- **v0.4 and earlier.** See
  [archive/j2-spec.md §11](archive/j2-spec.md).

---

## 12. Appendix A — Prior art per mechanism

Per the [../glossary.md §2](../glossary.md) prior-art-pre-2006
policy, every mechanism added by this specification cites at least
one pre-2006 published source. Most of the prior art lies in the
SH-4 hardware manual (pre-2006, patents expired) and IEEE-754
(1985).

| Mechanism                          | Tier | Pre-2006 prior art                                                  |
| ---------------------------------- | ---- | ------------------------------------------------------------------- |
| Coprocessor multi-beat protocol    | T0   | SH-4 hw manual §6 (2001); MIPS R3000 FPU CP1 protocol (1988)        |
| Single/double scalar arithmetic    | T0   | IEEE-754 (1985); SH-4 hw manual §6 (2001)                           |
| FMAC non-fused                     | T0   | SH-4 hw manual §9 (2001); MIPS R10000 MADD (1996, also non-fused)   |
| FCMP/EQ, FCMP/GT (T-bit result)    | T0   | SH-4 hw manual §9 (2001)                                            |
| FRCHG, FSCHG                       | T0   | SH-4 hw manual §9 (2001)                                            |
| Cause.E hardware/software co-design| T0   | SH-4 hw manual §6.4 (2001); Linux SH-4 fpu.c (pre-2006)             |
| FPSCR Cause-per-op / Flag-sticky   | T0   | SH-4 hw manual §6.4 (2001); IEEE-754 §7 (1985)                      |
| Default qNaN bit patterns          | T0   | SH-4 hw manual §6.5 (2001); MIPS qNaN convention (R4000 manual 1991)|
| FIPR (4-element dot product)       | T1   | SH-4 hw manual §9.41 (2001)                                         |
| FTRV (4×4 matrix multiply)         | T1   | SH-4 hw manual §9.52 (2001)                                         |
| FSCA (sin/cos table)               | T1   | SH-4A hw manual (2004)                                              |
| FSRRA (rsqrt table)                | T1   | SH-4A hw manual (2004); reciprocal-sqrt table prior to NR is        |
|                                    |      | discussed in Lyon et al., "A Function Generator Based on Table      |
|                                    |      | Lookup," IEEE Trans. Computers (1985)                               |
| FPCHG                              | T1   | SH-4A hw manual (2004)                                              |
| SR.FD (FPU-disable) trap           | T1   | SH-4 hw manual §6.2 (2001)                                          |
| Full FPSCR layout                  | T1   | SH-4 hw manual §6.4 (2001); IEEE-754 §7 (1985)                      |
| Lazy FPU context switch            | T2   | 4.4BSD Operating System (McKusick et al. 1996) §3.6;                |
|                                    |      | VAX FPACC trap (DEC VAX-11 Architecture Manual, 1979);              |
|                                    |      | UltraSPARC II Programmer Reference Manual (1997) §3.10;             |
|                                    |      | Mach IPC papers, "Mach: A New Kernel Foundation for UNIX            |
|                                    |      | Development" (Accetta et al., USENIX 1986);                         |
|                                    |      | Intel i486 CR0.TS bit (i486 Programmer's Reference Manual, 1990)    |
| Trap-on-first-use                  | T2   | VAX FPACC trap (1979); Intel i486 CR0.TS (1990); MIPS R4000         |
|                                    |      | Status.CU1 bit (1991)                                               |
| Per-vCPU FPU ownership flag        | T2   | Disco "Running Commodity Operating Systems on Scalable              |
|                                    |      | Multiprocessors" (Bugnion et al., SOSP 1997);                       |
|                                    |      | Xen "Xen and the Art of Virtualization" (Barham et al., SOSP 2003); |
|                                    |      | UltraSPARC sun4v hypervisor architecture (pre-2006)                 |
| HEDR delegation bitmap             | T2   | sun4v UltraSPARC Architecture 2005 (hyperprivileged trap            |
|                                    |      | delegation); see also                                               |
|                                    |      | [../hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md)    |
| 136-byte FPU image                 | T2   | direct consequence of SH-4 FPU state size (16+16 FR/XF + FPUL +     |
|                                    |      | FPSCR); SH-4 hw manual §6.1 (2001)                                  |

**No mechanism in this specification requires post-2006 prior art.**
The SH-4 manual (2001) and SH-4A manual (2004) cover every new
instruction; lazy-FPU and trap-on-first-use predate 1990.

---

## 13. Appendix B — Cross-tier instruction matrix

| Instruction       | T0 | T1 | T2 | Notes                                              |
| ----------------- | -- | -- | -- | -------------------------------------------------- |
| FMOV variants     | ✔  | ✔  | ✔  | Big-endian double layout at every tier (§4.3)      |
| FLDI0 / FLDI1     | ✔  | ✔  | ✔  |                                                    |
| FLDS / FSTS       | ✔  | ✔  | ✔  |                                                    |
| LDS / STS FPUL    | ✔  | ✔  | ✔  |                                                    |
| LDS / STS FPSCR   | ✔  | ✔  | ✔  | T1 enforces full FPSCR layout including SZ control |
| FADD / FSUB       | ✔  | ✔  | ✔  | Single + double; double via PR=1                   |
| FMUL / FDIV       | ✔  | ✔  | ✔  | Single + double                                    |
| FSQRT             | ✔  | ✔  | ✔  | Single + double                                    |
| FMAC              | ✔  | ✔  | ✔  | Single only; non-fused                             |
| FNEG / FABS       | ✔  | ✔  | ✔  | Sign-bit ops, no FPSCR effect                      |
| FCMP/EQ, FCMP/GT  | ✔  | ✔  | ✔  | T-bit result via cop_i.t                           |
| FLOAT / FTRC      | ✔  | ✔  | ✔  | Single + double                                    |
| FCNVSD / FCNVDS   | ✔  | ✔  | ✔  |                                                    |
| FRCHG / FSCHG     | ✔  | ✔  | ✔  | T1 adds SR.FD trap interaction                     |
| FIPR              | —  | ✔  | ✔  | New at T1                                          |
| FTRV              | —  | ✔  | ✔  | New at T1                                          |
| FSCA              | —  | ✔  | ✔  | New at T1                                          |
| FSRRA             | —  | ✔  | ✔  | New at T1                                          |
| FPCHG             | —  | ✔  | ✔  | New at T1 (SH-4A addition)                         |
| (SR.FD trap)      | —  | ✔  | ✔  | New trap class at T1; renamed EXC_FPU_DISABLED at T2|
| (HEDR delegation) | —  | —  | ✔  | New at T2                                          |
| (Lazy save/restore)| — | —  | ✔  | New at T2; no new instructions, ABI only            |

---

## 14. Appendix C — SH-4 reference catalogue

The Tier 0 archived spec's Appendix A is the canonical reference
catalogue; reproduced here in summary form.

1. **Renesas/Hitachi SH-4 Programming Manual, Rev. 5.0 (ADE-602-156D)**,
   April 2001. Canonical ISA reference. Section 2.2.3, section 6,
   section 9.
2. **Renesas SH-4A Software Manual, Rev. 1.50
   (REJ09B0003-0150Z)**, October 2004. Adds FPCHG, FSCA, FSRRA;
   documents the LE double-FMOV fix.
3. **qemu `target/sh4`**, post-2017 Aurélien Jarno cleanup. The
   2017 patch series "target/sh4: fix FPSCR cause vs flag inversion"
   and "target/sh4: fix FPU unordered compare" correct several
   subtle behaviour bugs; treat post-2017 qemu as authoritative
   where the manual is silent.
4. **`sh-elf-gcc` `-m4` and `-m4-single` codegen.** What the
   compiler emits is what Tier 1 must accept.
5. **STMicroelectronics SH-4 32-bit CPU Core Architecture manual**
   (`cd00147165`, 2002). Cross-check on Renesas wording.
6. **Linux kernel `arch/sh/kernel/cpu/sh4/fpu.c`** and
   `arch/sh/math-emu/`. The de facto definition of SH-4 FPU
   exception semantics in production software. `denormal_addf`,
   `denormal_mulf`, etc. are what J-Core's Cause.E mechanism must
   trigger correctly for binary compatibility at Tier 1.
7. **NetBSD `sys/arch/sh3`**. Independent OS port; cross-check on
   software assumptions.

For the Tier 2 lazy-FPU references:

8. **4.4BSD-Lite Operating System (McKusick, Bostic, Karels,
   Quarterman, 1996)**, §3.6 "Kernel I/O Structure" — lazy device
   state save/restore pattern that the FPU model inherits.
9. **DEC VAX-11 Architecture Reference Manual (1979)** — FPACC trap
   on first use of the floating-point accelerator; the original
   trap-on-first-use mechanism.
10. **Intel i486 Programmer's Reference Manual (1990)**, CR0.TS bit
    (Task Switched) — direct ancestor of SR.FD's lazy-FPU semantics
    in x86 lineage.
11. **UltraSPARC II User's Manual (Sun, 1997)**, §3.10 floating-
    point unit context switching.
12. **Disco** (Bugnion, Devine, Govil, Rosenblum), SOSP 1997 — first
    open description of vCPU-level FPU virtualisation; underlies
    the Tier 2 per-vCPU ownership flag.
13. **Xen** (Barham et al.), SOSP 2003 — paravirtualised
    hypervisor; FPU handling pattern that Tier 2 follows closely
    (lazy save/restore with hypervisor as trap mediator).
14. **sun4v UltraSPARC Architecture 2005** (Sun, 2005) —
    hyperprivileged trap delegation, the design ancestor of HEDR.

End of specification.
