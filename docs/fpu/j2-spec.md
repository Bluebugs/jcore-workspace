# J2 FPU Coprocessor — Specification (draft)

**Status:** working draft, v0.4
**Target:** jcore-cpu J2 core, FPU attached via the existing `cop_o`/`cop_i`
coprocessor interface, multi-beat protocol.
**ISA reference:** SH-4 FPU (Renesas SH-4 Software Manual Rev. 5.0,
ADE-602-156D). Cross-checked against qemu `target/sh4` as a working
reference implementation (§A). Where this spec narrows the SH-4 behaviour,
sections are marked **[J2 deviation]**.

---

## 1. Scope and non-goals

### 1.1 In scope
- A synthesizable VHDL FPU block that hangs off the existing J2 `cop_o`/`cop_i`
  port pair.
- SH-4 FPU programmer-visible state: 32 single-precision FRs (with bank), DR
  aliasing, FV vector aliases, XMTRX aliases, FPUL, FPSCR.
- SH-4 FPU instruction subset (see §6) sufficient to run code emitted by
  `sh-elf-gcc -m4-single` (Tier B) and `-m4` (Tier C).
- A multi-beat protocol over `cop_o_t`/`cop_i_t` carrying single, double, and
  vector operands.
- A representation in the new Go/TOML decoder generator (§7) such that FPU
  instructions are first-class entries, not a special case.

### 1.2 Out of scope (this revision)
- Any change to the J2 base ISA, pipeline, register file, or memory bus.
- Any change to the shape of `cop_o_t`/`cop_i_t` records in
  `cpu2j0_pkg.vhd`. We layer a protocol on top; we do not widen the wires.
- SR.FD-style FPU disable, FPU-related exception vectors, MMU interaction.
  J2 is no-MMU; FPU exceptions are surfaced through the existing
  illegal-instruction path (mechanism in §3.8).
- The SH-4 compound ops FIPR, FTRV, FSRRA, FSCA. Reserved for a later
  revision; encoding space is preserved.
- FMAC fused semantics. SH-4 FMAC is **not** IEEE-754 fused (it rounds
  twice). We follow SH-4.

### 1.3 Non-goals (deliberately not promising)
- Bit-exact SH-4 cycle counts.
- Bit-exact SH-4 denormal handling under all FPSCR.DN settings on the first
  pass. §8 specifies the conformance level we are targeting.

### 1.4 Decision principles

These principles are tie-breakers when multiple designs would work. They
exist because this is an open-source project where contribution-friendliness
and reviewability matter as much as elegance.

1. **Minimum diff against the existing j-core codebase.** When two designs
   are roughly equivalent on technical merits, prefer the one that touches
   the fewest existing files, leaves the fewest existing signals
   re-purposed, and adds the fewest new conventions. Concretely: we copy
   the `mac_busy` pattern for FPU back-pressure (§3.6) rather than
   resurrecting the dormant `cop_i.ack` path, because the former is a
   localized addition and the latter would rewrite the slot-generation
   logic in `datapath.vhm`.
2. **Reuse the project's idioms.** New execution units should look like
   `mult`: a black-box block with its own `_pkg.vhd`, its own `_tap.vhd`
   testbench, its own busy signal feeding the decoder. New microcode
   columns should look like existing microcode columns. We do not invent
   new patterns when an existing one fits.
3. **Greenfield work (the Go/TOML generator) is exempt** from the minimum
   diff principle, but inherits the "reuse idioms" principle: the
   generator's *output* must match the shape the rest of the codebase
   expects, and the schema should generalize patterns the existing
   generator special-cased only if the generalization comes for free.
4. **Dormant signals stay dormant.** `cop_i.ack` and `cop_i.exc` exist in
   the record but are never consumed in the current codebase. We leave
   them unconsumed in this revision and route FPU back-pressure and
   exceptions through paths we add (§3.6, §3.8). Wiring them up is a
   separate, future change with its own justification.
5. **Binary compatibility with SH-4 is the strict bar for the FPU.** Code
   compiled by `sh-elf-gcc -m4` or `-m4-single` against the SH-4 FPU
   model must run on the J2 FPU and produce architecturally identical
   results. Where the SH-4 Software Manual is ambiguous or
   implementation-defined, qemu's `target/sh4` (post-2017 Aurélien
   Jarno cleanup) is the tiebreaker reference (§A). This principle
   overrides convenience: any place where simpler-to-implement
   semantics would diverge from SH-4 observable behaviour, we
   implement SH-4 semantics.

---

## 2. Architectural choice

The FPU is a separate VHDL block, instantiated alongside `u_mult` and
`u_datapath` inside `cpu.vhd`, connected to the CPU via the existing
`cop_o_t` / `cop_i_t` interface. It owns its own register file. The CPU has
no direct read or write port into FPU registers; every transfer happens
through the coprocessor protocol.

Rationale: matches the published j-core roadmap, matches the existing
`COPRO_DECODE` generic, keeps the FPU synthesis-optional, and isolates
IEEE-754 work from the J2 pipeline.

---

## 3. The multi-beat coprocessor protocol

### 3.1 Wire-level (unchanged)
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

### 3.2 Beat model
Each FPU instruction is a fixed sequence of pipeline slots, one per beat,
emitted by the decoder as a series of microcode rows (the same mechanism
the existing multi-cycle multiplier uses for DMULSL → DMULSL1 → DMULSL2).
The decoder knows the row count for each opcode; it is not negotiated on
the wire.

In each beat:
- **CPU-driven beat:** `cop_o.en='1'` for one cycle. The FPU samples
  `cop_o.{op, rna, rnb, d}` on the rising edge.
- **FPU-driven beat:** the FPU drives `cop_i.{d, t}` combinationally
  based on `cop_o.{op, rna, rnb}` and the CPU latches the result in the
  same cycle (this matches the existing FOP_MEM_R / STS coproc-data-mux
  behaviour at `datapath.vhm:297–298`).

Wait-states between beats come from the multi-cycle-mult-style stall:
the FPU asserts `fpu_o.busy` and the decoder stalls the pipeline (see
§3.6). The CPU's `cop_o.stallcp` (already `not slot_o`) continues to
freeze internal FPU state during pipeline stalls.

`cop_i.ack` is **not** used to delimit beats and is not driven by the
FPU. It remains dormant (§1.4 principle 4).

The `op` field carries a beat-typed micro-op (§3.4), not the SH
instruction opcode. The decoder translates one SH instruction into the
correct sequence of `op` codes plus the right `rna`/`rnb` for each
beat.

### 3.3 Operand widths and beat counts

| Class                           | CPU→FPU beats | FPU→CPU beats | Examples                |
| ------------------------------- | ------------- | ------------- | ----------------------- |
| Single, reg-reg                 | 0             | 0             | FADD (PR=0), FNEG       |
| Single, immediate-form          | 0             | 0             | FLDI0, FLDI1            |
| Single, FPUL→FR or FR→FPUL      | 1             | 1             | FLDS, FSTS              |
| Single load from memory         | 1             | 0             | FMOV.S @Rm,FRn          |
| Single store to memory          | 0             | 1             | FMOV.S FRm,@Rn          |
| Single compare                  | 0             | 0 (T only)    | FCMP/EQ, FCMP/GT        |
| Double, reg-reg                 | 0             | 0             | FADD (PR=1)             |
| Double load from memory         | 2             | 0             | FMOV @Rm,DRn (SZ=1)     |
| Double store to memory          | 0             | 2             | FMOV DRm,@Rn (SZ=1)     |
| FPSCR read/write                | 0/1           | 1/0           | STS FPSCR,Rn / LDS Rn,FPSCR |
| FPUL read/write                 | 0/1           | 1/0           | STS FPUL,Rn / LDS Rn,FPUL   |

"Reg-reg" beats are zero because operands are read from the FPU's internal
register file, addressed by `rna`/`rnb`. The CPU only carries traffic in
when something must cross the CPU/FPU boundary (memory data, FPUL, FPSCR,
or integer values).

### 3.4 Micro-op encoding (`cop_o.op`, 5 bits)

The existing `coproc_cmd_t` (`NOP, LDS, STS, CLDS, CSTS`) is consumed
unchanged for FPUL/FPSCR transfers. New ops:

| Encoding (decimal) | Mnemonic     | Meaning                                                |
| ------------------ | ------------ | ------------------------------------------------------ |
| 0                  | NOP          | (existing) no FPU action                               |
| 1                  | LDS          | (existing) load FPUL/FPSCR from CPU bus                |
| 2                  | STS          | (existing) store FPUL/FPSCR to CPU bus                 |
| 3                  | CLDS         | (existing) conditional LDS                             |
| 4                  | CSTS         | (existing) conditional STS                             |
| 5                  | FOP_ADD      | floating add (PR-dependent precision)                  |
| 6                  | FOP_SUB      | floating subtract                                      |
| 7                  | FOP_MUL      | floating multiply                                      |
| 8                  | FOP_DIV      | floating divide                                        |
| 9                  | FOP_SQRT     | floating square root (single-operand)                  |
| 10                 | FOP_MAC      | floating multiply-accumulate (non-fused)               |
| 11                 | FOP_CMP_EQ   | floating compare-equal, drives `cop_i.t`               |
| 12                 | FOP_CMP_GT   | floating compare-greater, drives `cop_i.t`             |
| 13                 | FOP_NEG      | floating negate                                        |
| 14                 | FOP_ABS      | floating absolute value                                |
| 15                 | FOP_FLOAT    | int→float, FPUL→FRn                                    |
| 16                 | FOP_TRC      | float→int truncate, FRm→FPUL                           |
| 17                 | FOP_CNV_SD   | single→double precision conversion                     |
| 18                 | FOP_CNV_DS   | double→single precision conversion                     |
| 19                 | FOP_MEM_W    | memory write beat: CPU drives `cop_o.d` into FR/DR     |
| 20                 | FOP_MEM_R    | memory read beat: FPU drives `cop_i.d` from FR/DR      |
| 21                 | FOP_FLDI     | load immediate (0.0 if rnb=0, 1.0 if rnb=1) into FRn   |
| 22                 | FOP_CTRL     | FRCHG/FSCHG/FPCHG (encoded in rna)                     |
| 23–31              | *reserved*   | for FIPR/FTRV/FSCA/FSRRA and future use                |

**Decision (resolved):** one `op` code per FPU operation (option (b) from
v0.1). Stealing bits from `rna`/`rnb` to extend a single `FOP_EXEC` op was
rejected as it would restrict register encoding and force special-case
microcode logic — violating §1.4 principle 2.

**Side-effect: `datapath.vhm` needs a small change.** The current
combinational block at `core/datapath.vhm:451–455` emits only 5 distinct
5-bit patterns:

```vhdl
cop_o.op <= "11101" when coproc.coproc_cmd = LDS  else
            "11111" when coproc.coproc_cmd = STS  else
            "10001" when coproc.coproc_cmd = CLDS else
            "10000" when coproc.coproc_cmd = CSTS else
            "00000";
```

We extend it to emit the additional codes when the decoder issues an FPU
op. The cleanest fit under §1.4 is to add a new decoder output (e.g.
`coproc.fpu_op : fpu_op_t`) that selects one of the new patterns when
`coproc_cmd = NOP` (no LDS/STS active). This keeps the existing
`coproc_cmd_t` enum untouched. Exact wording is implementation-detail and
will be settled in Phase 0 along with the TOML schema.

### 3.5 Handshake examples

The wire-level behaviour is consistent across all examples:

- `cop_o.en='1'` for exactly one cycle per beat that the CPU drives.
- `cop_i.ack` is **dead** in the current implementation; the FPU does not
  drive it for back-pressure. See §3.6 for how the FPU stalls the
  pipeline instead.
- `cop_o.stallcp` continues to be `not slot_o` (existing behaviour);
  during pipeline stalls it tells the FPU not to advance internal state.
- Multi-cycle FPU operations stall the CPU pipeline via `fpu_o.busy`
  ANDed with per-instruction microcode (§3.6); the wire-level trace
  below just shows the *beats*, not the stall cycles in between.

**FADD FRm, FRn (single precision, reg-reg):**

```
Cycle  cop_o                                          cop_i / FPU state
  N    op=FOP_ADD, rna=FRm, rnb=FRn, en=1             FPU latches operands,
                                                       asserts fpu_o.busy=1
  N+1  en=0                                           FPU computing,
   ..                                                  fpu_o.busy=1 (CPU
                                                       pipeline stalls via
                                                       decoder, see §3.6)
  N+k  en=0                                           FPU writes result to
                                                       its regfile,
                                                       fpu_o.busy=0
```

The CPU never sees the result on `cop_i.d`; reg-reg FPU ops keep their
result inside the FPU's regfile. The only thing crossing the wires is
the dispatch.

**FCMP/EQ FRm, FRn (single, drives T):**

```
Cycle  cop_o                                          cop_i / FPU state
  N    op=FOP_CMP_EQ, rna=FRm, rnb=FRn, en=1          FPU latches,
                                                       fpu_o.busy=1
  N+k  en=0                                           cop_i.t = result,
                                                       fpu_o.busy=0
```

`cop_i.t` is already used by the CPU pipeline (it's in the existing
record). The decoder routes it into the SR.T update path via existing
`t_sel` logic — no new wires.

**FMOV.S @Rm, FRn (single load):**

```
Cycle  cop_o                                          cop_i / FPU state
  N    op=FOP_MEM_W, rnb=FRn, d=<mem data>, en=1      FPU writes FRn,
                                                       fpu_o.busy=0 (1-cycle)
```

The CPU has already done the bus read in EX; the loaded word is on
`cop_o.d` in the same cycle as the FOP_MEM_W beat. Single-cycle
operation; no pipeline stall needed.

**FMOV.S FRm, @Rn (single store):**

```
Cycle  cop_o                                          cop_i / FPU state
  N    op=FOP_MEM_R, rna=FRm, en=1                    cop_i.d=<FRm value>,
                                                       FPU reads regfile
                                                       and drives d in
                                                       the same cycle
                                                       (latency 0)
```

The CPU latches `cop_i.d` and drives it onto the memory bus in WB. This
exactly matches the existing `coproc.cpu_data_mux /= DBUS` path in
`datapath.vhm:297`.

**FADD DRm, DRn (double precision, reg-reg):**

Identical to single-precision FADD at the wire level — same FOP_ADD op,
same beat count (zero data beats), longer `fpu_o.busy` window. The FPU
internally selects double-precision datapaths based on FPSCR.PR.

**FMOV @Rm, DRn (double load, SZ=1):**

Implemented as two decoder microcode rows, each issuing one memory read
and one FOP_MEM_W beat:

```
Slot   cop_o                                          cop_i / FPU state
  N    op=FOP_MEM_W, rnb=DRn_hi, d=<word0>, en=1      FPU writes upper FR
  N+1  op=FOP_MEM_W, rnb=DRn_lo, d=<word1>, en=1      FPU writes lower FR
```

Each slot is a complete CPU pipeline slot, identical in structure to a
single FMOV.S. There is no special "two-beat" wire protocol; the
multi-beat appearance is an emergent property of multi-row microcode.
This matches how the existing `mult` multi-cycle ops are decoded
(DMULSL → DMULSL1 → DMULSL2). Endianness is resolved in §3.7.

### 3.6 Back-pressure (resolved)

**Decision:** copy the `mac_busy` mechanism. `cop_i.ack` is not consumed
anywhere in the current codebase (verified by inspection of
`core/datapath.vhm` — single use of `cop_i` is reading `cop_i.d` at line
298, and `cop_i.ack` / `cop_i.exc` are dead wires). Resurrecting them
would require rewriting the slot-generation logic in `datapath.vhm`,
which violates §1.4 principle 1.

The existing pattern from the multiplier:

```
mult/u_mult --mac_o.busy--> cpu.vhd --mac_busy--> decoder
decode_core.vhm:128
  mac_stall <= mac_stall_sense and (p.wb1.mac_busy or p.wb2.mac_busy or
                                    p.wb3.mac_busy or p.ex1.mac_busy or
                                    mac_busy);
decode_core.vhm:132
  next_id_stall_a <= reg_conf or if_stall or mac_stall;
```

Each instruction's microcode carries a per-pipeline-stage `mac_busy` bit
plus a `mac_stall_sense` flag. The stall fires only for instructions
that have declared they care.

**Concrete changes required for the FPU:**

1. **FPU module:** the FPU exposes `fpu_o_t.busy : std_logic` (already
   in §6 record draft). High while the FPU is computing or processing
   a multi-row dispatch; low when idle and ready to accept a new op.

2. **`cpu.vhd`:** new wiring, parallel to `mac_busy => mac_o.busy`:
   ```vhdl
   u_decode: decode port map (
     ...,
     mac_busy => mac_o.busy,
     fpu_busy => fpu_o.busy,    -- NEW
     ...);
   ```

3. **`decode/decode_pkg.vhd`** (generated):
   - Add `fpu_busy_t` enum: `NOT_BUSY, EX_NOT_STALL, EX_BUSY,
     WB_NOT_STALL, WB_BUSY` (mirrors `mac_busy_t`).
   - Add `fpu_busy : std_logic` field to `pipeline_ex_t` and
     `pipeline_wb_t`.
   - Add `fpu_busy : in std_logic` port to `decode` and `decode_core`
     entities.

4. **`decode/decode_core.vhm`:**
   ```vhdl
   fpu_stall <= fpu_stall_sense and (p.wb1.fpu_busy or p.wb2.fpu_busy or
                                     p.wb3.fpu_busy or p.ex1.fpu_busy or
                                     fpu_busy);
   next_id_stall_a <= reg_conf or if_stall or mac_stall or fpu_stall;
   ```

5. **Decoder generator (Go/TOML):** each FPU instruction needs two new
   microcode columns — `fpu_busy` (per-stage tag) and `fpu_stall_sense`
   (whether this instruction stalls on FPU busy). Schema details in §7.

**Diff footprint estimate:**
- `core/cpu.vhd`: 1 line added (port map)
- `core/datapath.vhm`: 0 lines (datapath is untouched by back-pressure;
  only the §3.4 op extension touches it)
- `decode/decode.vhd` and `decode/decode_pkg.vhd`: generated, change
  comes from generator
- `decode/decode_core.vhm`: ~3 lines added
- All other code paths unchanged when `fpu_stall_sense=0` (i.e., for
  every existing SH-2 instruction)

`cop_i.ack` and `cop_i.exc` remain dormant. The spec acknowledges them
as reserved for future use (§1.4 principle 4).

### 3.7 Endianness (resolved)

**Decision: J2 FPU follows SH-4 big-endian semantics for double-precision
FMOV.** Concretely, for `FMOV @Rm, DRn` with FPSCR.SZ=1:

- The word at address `Rm` (lower address) is loaded into `FRn`
- The word at address `Rm+4` (higher address) is loaded into `FR(n+1)`

Because `DRn = {FRn, FR(n+1)}` and the IEEE-754 double-precision layout
places the sign + most-significant exponent/mantissa bits in the high
word, this means **FRn holds the high word** (sign, biased exponent,
upper 20 mantissa bits) and **FR(n+1) holds the low word** (lower 32
mantissa bits). Memory order matches: high word at lower address.

This is confirmed by qemu `target/sh4/translate.c` opcode `0xf008`
(`FMOV @Rm, DRn`) which performs sequential loads:
`cpu_fregs[fr] ← @REG(B7_4); cpu_fregs[fr+1] ← @(REG(B7_4)+4)`.

The same ordering applies to `FMOV @Rm+, DRn` (post-increment by 8),
`FMOV DRm, @Rn`, `FMOV DRm, @-Rn` (pre-decrement by 8), and the
`@(R0,Rm)` indexed forms.

**SH-4 little-endian mode**: the SH-4 has a documented "buggy" behaviour
where SZ=1 64-bit FMOV in LE mode swaps the two 32-bit halves; this was
considered a hardware bug and the SH-4 Programming Note instructs LE
software to use two SZ=0 32-bit moves instead. **J2 is big-endian only**
(verified: the existing jcore-cpu uses big-endian throughout), so this
case does not arise and we do not implement either the buggy LE
behaviour or the SH-4A fix. If LE support is ever added to J2, this
section must be revisited.

### 3.8 Exception signalling (resolved)

**SH-4 uses precise FPU exceptions.** Evidence: the Linux kernel SH-4
FPU exception handler at `arch/sh/kernel/cpu/sh4/fpu.c` (function
`ieee_fpe_handler`, called from `BUILD_TRAP_HANDLER(fpu_error)`) reads
the offending instruction directly from `*(unsigned short *)regs->pc`,
decodes it, and emulates it in software. This only works if `regs->pc`
points to the FPU instruction that caused the trap. The kernel has run
on real SH-4 silicon for two decades and this code works, so the
hardware guarantee is firm: SPC = offending FPU instruction PC, and
the offending instruction's register write-back is suppressed.

The J2 FPU must match this. The mechanism falls out of the mac_busy
pattern (§3.6):

1. FPU instruction at PC=X is dispatched via `cop_o`.
2. CPU pipeline advances; `fpu_o.busy` stalls the next instruction's
   commit (same pattern as `mac_busy` for multi-cycle multiplies).
3. FPU computes for N cycles. Result is held in an internal register,
   not yet written to the architectural FR/FPUL/FPSCR state.
4. On the FPU's completion cycle, exactly one of two things happens:
   - **No exception**: `fpu_o.busy` deasserts, result is driven on
     `cop_i.d` (or via a dedicated FPU regfile write port), CPU
     commits, next instruction proceeds.
   - **Exception**: `fpu_o.busy` deasserts AND `fpu_o.exc` asserts,
     in the same cycle. The CPU takes a trap. SPC=X automatically
     (the next instruction has been stalled the whole time and never
     committed). Result write-back to FR/FPUL is suppressed. The
     `FPSCR.Cause` field IS updated with the trap-causing bits — the
     handler reads it to identify the exception.

**Critical timing invariant.** `fpu_o.exc` MUST be raised on the same
cycle that the FPU instruction would have committed, not earlier. If
the FPU detects an exception condition mid-computation (e.g. denormal
input on cycle 1 of a 5-cycle FADD), it must hold that knowledge and
only assert `fpu_o.exc` on the completion cycle. Raising `exc` earlier
risks SPC pointing at a later instruction that's already started
flowing through the pipeline.

**Trap routing.** `fpu_o.exc` is OR'd into the existing `illegal_instr`
line at the `decode` level. The existing illegal-instruction trap path
in J2 is precise (verified: the j-core pipeline saves the PC of the
instruction whose `illegal_instr` is asserted at commit time, not a
later PC). Routing `fpu_o.exc` through it gives us precise FPU
exceptions for free, with one VHDL line of diff in `decode.vhd` and
zero change to the trap-taking machinery.

**[J2 deviation from SH-4 vector layout].** SH-4 has separate vectors:
- General FPU disable exception (FD bit set, non-delay-slot)
- Slot FPU disable exception (FD bit set, in delay slot)
- FPU exception (IEEE-754 exception with corresponding Enable set)
- FPU Error (Cause.E set; always traps)

J2 collapses all of these into the existing illegal-instruction vector,
which is the same vector SH-4 uses for "general illegal instruction"
(EXPEVT 0x180). Software distinguishes by reading FPSCR.Cause after
the trap. Linux's `fpu_error` handler does exactly this — it reads
FPSCR.Cause to decide what emulation to perform — so collapsing the
vectors is binary-compatible with Linux as long as the cause bits
match SH-4. We do not implement SR.FD, so the disable-exception cases
do not arise.

**The Cause.E mechanism — hardware/software co-design.** SH-4 has a
sixth Cause bit, "FPU Error" (Cause.E, bit 17 of FPSCR), with NO
corresponding Enable bit and NO corresponding Flag bit. **Cause.E
always traps when raised.** It is the architecture's escape hatch for
operations the hardware cannot or will not handle:

- Denormal operand when FPSCR.DN=0 (hardware refuses to multiply with
  a denormal input)
- Result would be denormal when FPSCR.DN=0 (hardware refuses to
  produce a denormal output)
- Other implementation-defined "I give up, software handle this" cases

The Linux SH-4 FPU handler has dedicated routines (`denormal_addf`,
`denormal_mulf`, etc.) that the kernel invokes when Cause.E is set,
to complete the operation in software.

**J2 deliberately exploits this.** Our FPU implements IEEE-754
arithmetic only for normalized inputs. When a denormal input is
encountered (any DN value), or when DN=0 and a denormal output would
be produced, we set Cause.E and trap. The Linux kernel handles the
rest. This is **a major hardware simplification** for the J2 FPU and
is fully binary-compatible because it is exactly what SH-4 silicon
does. See §6.3 for the FPU microarchitecture impact and §8 for the
conformance implications.

For DN=1 (the J2 default after reset, matching SH-4 default), denormal
handling collapses to: flush denormal inputs to ±0 with sign preserved,
flush tiny results to ±0, set Cause.U (underflow) on flush. No trap
needed in this path — this is straightforward hardware. Most software
runs with DN=1 because the SH-4 hardware reset value sets it.

---

## 4. Programmer's model

### 4.1 Register file
- 32 single-precision FRs, organized as two banks of 16:
  FR0–FR15 (front bank) and XF0–XF15 (back bank), selected by FPSCR.FR.
- When FPSCR.PR=1, FR0/2/4/...14 are paired into DR0/2/4/...14, each
  holding one IEEE-754 double. `DRn = {FRn, FR(n+1)}` per SH-4 spec.
  **FRn holds the high word** (sign + biased exponent + upper 20
  mantissa bits); **FR(n+1) holds the low word** (lower 32 mantissa
  bits). This matches the IEEE-754 binary64 layout when stored to
  memory in big-endian byte order with FRn at the lower address (§3.7).
  Odd-numbered FR access while PR=1 is reserved by SH-4; we do not trap
  but the result is implementation-defined.
- When FPSCR.SZ=1, FMOV transfers pairs of FRs as 64-bit operations.
- FV0/4/8/12 and XMTRX are name-only aliases over the same storage.
- Physical implementation: a 32×32 flop array (`fpu_regfile.vhd`) with
  three read ports (A, B, and a memory-load write port) and two write
  ports (result, memory-load). Bank selection multiplexes addresses; it
  does not duplicate storage.

### 4.2 FPUL
- 32-bit register. Conduit between integer registers and the FPU.
- Accessed by:
  - `LDS Rn, FPUL` — CPU writes Rn into FPUL (cop_o.op=LDS, target=FPUL).
  - `STS FPUL, Rn` — CPU reads FPUL into Rn (cop_o.op=STS).
  - `FLDS FRm, FPUL` — internal FPU move, FRm → FPUL.
  - `FSTS FPUL, FRn` — internal FPU move, FPUL → FRn.
- FLOAT reads FPUL as a signed 32-bit integer and writes a float to FRn.
  FTRC reads a float from FRm and writes a signed 32-bit integer to FPUL.

### 4.3 FPSCR (32 bits, layout matches SH-4)

| Bits  | Field   | Notes                                                  |
| ----- | ------- | ------------------------------------------------------ |
| 31:22 | -       | reserved, read as 0                                    |
| 21    | FR      | register-bank select                                   |
| 20    | SZ      | FMOV size: 0=32-bit, 1=64-bit                          |
| 19    | PR      | precision: 0=single, 1=double                          |
| 18    | DN      | denormal mode: 0=denormal as such, 1=flush-to-zero     |
| 17:12 | Cause   | E, V, Z, O, U, I (six bits, in SH-4 order)             |
| 11:7  | Enable  | V, Z, O, U, I (five bits — **no Enable.E**)            |
| 6:2   | Flag    | V, Z, O, U, I (five bits — **no Flag.E**)              |
| 1:0   | RM      | rounding mode: 00=nearest-even, 01=to-zero, 10/11=resv |

**Cause.E (FPU Error) — special, always traps.** Bit 17 has no Enable
bit and no Flag bit. When the FPU sets Cause.E it always raises an
FPU exception, regardless of any Enable setting. This is the SH-4
architectural escape hatch for "the hardware cannot or will not
complete this operation"; Linux's SH-4 FPU handler emulates the
operation in software when it sees Cause.E set. See §3.8 for full
discussion. J2 sets Cause.E for:
- Denormal operand encountered (any DN value, since our hardware does
  not handle denormal arithmetic at all)
- Denormal result would be produced when DN=0
- Reserved-encoding FPU operations (e.g. PR=1 + FMAC)

**Reset value: 0x00040001** (DN=1, RM=01). Note: RM=01 is **Round to
Zero** (truncation toward zero), not Round to Nearest. Software that
wants IEEE-754 round-to-nearest-even semantics must explicitly write
FPSCR after reset. This matches SH-4 exactly.

**Cause vs Flag field semantics (SH-4 binary-compat):**

- The **Cause field** is **cleared to zero at the start of every FPU
  operation instruction**, then the bits corresponding to exceptions
  raised by *that* instruction are set. It is per-instruction state,
  not cumulative. This includes Cause.E.
- The **Flag field** is **sticky**: bits accumulate as exceptions
  occur (only V/Z/O/U/I; no Flag.E), and are only cleared when
  software writes a 0 to them via LDS Rn, FPSCR.
- The **Enable field** is software-controlled; it gates which V/Z/O/U/I
  Cause bits trigger a trap. Cause.E always traps. Flag updates happen
  regardless of Enable.

This is the SH-4 model and is non-negotiable for binary compatibility.
It also matters for the differential test setup — the C model must
mirror this clear-then-set behaviour per instruction.

- **[J2 deviation]:** SH-4 defines RM=10 and RM=11 as reserved; we
  honour that. We do not implement round-to-plus-infinity or
  round-to-minus-infinity. Software writing RM=10 or RM=11 gets
  implementation-defined behaviour; we follow qemu by preserving the
  written value but treating the rounding mode as Round-to-Zero
  internally.

### 4.4 Banks and reserved encodings
- `FRCHG` toggles FR. SH-4 spec says "setting prohibited" when PR=1;
  behaviour is implementation-defined. **We follow qemu**: toggle FR
  regardless of PR (single-cycle XOR). Software that does this gets
  the toggle but should not rely on the FPU state afterward.
- `FSCHG` toggles SZ. SH-4 same wording, same J2 behaviour: toggle
  regardless of PR.
- FPSCR.SZ=1 with FPSCR.PR=1 is "reserved" per SH-4. We do not trap;
  arithmetic instructions with both bits set produce implementation-
  defined results. Real code does not enter this state.

---

## 5. Instruction subset, by tier

Tier listing only; full encoding tables live in the TOML (§7). Each row is
"included in this revision: yes/no", "phase: which TDD phase implements it".

### Tier A — data movement (Phase 1)

| Mnemonic            | Encoding (hex pattern) | Beats (in/out) | Phase |
| ------------------- | ---------------------- | -------------- | ----- |
| FMOV FRm, FRn       | 1111nnnnmmmm1100       | 0/0            | 1     |
| FMOV.S @Rm, FRn     | 1111nnnnmmmm1000       | 1/0            | 1     |
| FMOV.S FRm, @Rn     | 1111nnnnmmmm1010       | 0/1            | 1     |
| FMOV.S @Rm+, FRn    | 1111nnnnmmmm1001       | 1/0            | 1     |
| FMOV.S FRm, @-Rn    | 1111nnnnmmmm1011       | 0/1            | 1     |
| FMOV.S @(R0,Rm),FRn | 1111nnnnmmmm0110       | 1/0            | 1     |
| FMOV.S FRm,@(R0,Rn) | 1111nnnnmmmm0111       | 0/1            | 1     |
| FMOV DRm, DRn       | 1111nnn0mmm01100       | 0/0            | 1     |
| FMOV @Rm, DRn       | 1111nnn0mmmm1000       | 2/0            | 1     |
| FMOV DRm, @Rn       | 1111nnnnmmm01010       | 0/2            | 1     |
| FMOV @Rm+, DRn      | 1111nnn0mmmm1001       | 2/0            | 1     |
| FMOV DRm, @-Rn      | 1111nnnnmmm01011       | 0/2            | 1     |
| FLDI0 FRn           | 1111nnnn10001101       | 0/0            | 1     |
| FLDI1 FRn           | 1111nnnn10011101       | 0/0            | 1     |
| FLDS FRm, FPUL      | 1111mmmm00011101       | 0/0            | 1     |
| FSTS FPUL, FRn      | 1111nnnn00001101       | 0/0            | 1     |
| LDS Rm, FPUL        | 0100mmmm01011010       | 1/0            | 1     |
| STS FPUL, Rn        | 0000nnnn01011010       | 0/1            | 1     |
| LDS Rm, FPSCR       | 0100mmmm01101010       | 1/0            | 1     |
| STS FPSCR, Rn       | 0000nnnn01101010       | 0/1            | 1     |
| FRCHG               | 1111101111111101       | 0/0            | 1     |
| FSCHG               | 1111001111111101       | 0/0            | 1     |

### Tier B — single precision arithmetic (Phase 2)

| Mnemonic           | Encoding         | SH-4 notes                            |
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
| FMAC FR0,FRm,FRn   | 1111nnnnmmmm1110 | **single precision only**; non-fused  |
| FLOAT FPUL, FRn    | 1111nnnn00101101 | int32 → float, exact for ≤24-bit ints |
| FTRC FRm, FPUL     | 1111mmmm00111101 | float → int32; see §5.1               |

**§5.1 FTRC binary-compat notes (SH-4):**
- Rounds toward zero (truncation), independent of FPSCR.RM.
- On NaN, +Inf, or value ≥ 2³¹: result = 0x7FFFFFFF, sets Cause.V and
  Flag.V (invalid operation).
- On −Inf or value ≤ −(2³¹+1): result = 0x80000000, sets Cause.V and
  Flag.V.
- Normal in-range conversion may set Cause.I (inexact) if the float
  has a non-zero fractional part.

**§5.2 FMAC binary-compat notes (SH-4):**
- **Single-precision only**, full stop. There is no double-precision
  FMAC; if FPSCR.PR=1 and an FMAC opcode is decoded, the SH-4 spec
  says the result is undefined. We follow qemu and treat it as a
  reserved/illegal instruction (raise via `fpu_o.exc`).
- Computes `FR0 × FRm + FRn → FRn`, with rounding after multiply AND
  rounding after add (non-fused). This is **not** IEEE-754-2008 fused
  multiply-add. Test vectors that assume fused FMA will diverge; this
  is correct SH-4 behaviour.

**§5.3 FCMP NaN behaviour (SH-4):**
- Both FCMP/EQ and FCMP/GT return T=0 when either operand is a NaN
  (unordered). FCMP/EQ does NOT consider unordered as "equal".
- Cause.V and Flag.V are set when either operand is a NaN (qemu's
  current behaviour matches SH-4 spec section 6 after the 2017 Jarno
  patches).

### Tier C — double precision (Phase 3)
Same set of arithmetic ops with PR=1, **except FMAC** which has no
double-precision form (see §5.2). Plus precision-conversion:

| Mnemonic            | Encoding         | Notes                          |
| ------------------- | ---------------- | ------------------------------ |
| FCNVDS DRm, FPUL    | 1111mmm010111101 | double → single, result→FPUL   |
| FCNVSD FPUL, DRn    | 1111nnn010101101 | single (from FPUL) → double    |

### Tier D — compound ops (deferred)
FIPR, FTRV, FSRRA, FSCA. Encoding-reserved, not implemented this
revision. Code that uses these will trap via `fpu_o.exc`; software
needing them must avoid `-m4` codegen of the relevant intrinsics or
upgrade to a future J-core revision that supports Tier D.

---

## 6. Microarchitecture sketch

```
                +-------------------- FPU --------------------+
   cop_o   --+->| beat_seq  ->  op_decode  ->  exec dispatch  |
   cop_i   <--  |                  |              |  |  |  |  |
                |              regfile_a       add sub mul ... |
                |              regfile_b          \  |  /      |
                |                                  result      |
                |                                    |         |
                |              regfile_wb  <---------+         |
                |                                              |
                |    FPUL    FPSCR                             |
                +----------------------------------------------+
```

Modules (target file layout):

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
  fpu_round.vhd            -- shared rounding logic (single/double)
  fpu_classify.vhd         -- IEEE-754 operand classification
```

`fpu_pkg.vhd` mirrors `mult_pkg.vhd` style:

```vhdl
type fpu_op_t is (FOP_NOP, FOP_ADD, FOP_SUB, FOP_MUL, FOP_DIV,
                  FOP_SQRT, FOP_MAC, FOP_CMP_EQ, FOP_CMP_GT,
                  FOP_NEG, FOP_ABS, FOP_FLOAT, FOP_TRC,
                  FOP_CNV_SD, FOP_CNV_DS,
                  FOP_MEM_W, FOP_MEM_R, FOP_FLDI, FOP_CTRL);

type fpu_i_t is record
  op       : fpu_op_t;
  rna, rnb : std_logic_vector(3 downto 0);
  d        : std_logic_vector(31 downto 0);
  en       : std_logic;
end record;

type fpu_o_t is record
  d    : std_logic_vector(31 downto 0);  -- to cop_i.d (for FOP_MEM_R/STS)
  t    : std_logic;                       -- to cop_i.t (for FCMP)
  busy : std_logic;                       -- to decoder, back-pressure
  exc  : std_logic;                       -- to decoder, illegal_instr path
end record;
```

Notes on the output record:

- `d` and `t` drive `cop_i.d` and `cop_i.t` directly at the `cpu.vhd`
  level. They do not bypass the existing coprocessor wiring.
- `busy` and `exc` are **separate** signals from the FPU to the
  decoder, parallel to `mac_o.busy`. They do NOT travel through
  `cop_i.ack` / `cop_i.exc`, which remain dormant per §1.4. This is a
  deliberate choice — using the existing `_busy` idiom is a smaller
  diff than wiring up `cop_i` ack/exc semantics.
- No `ack` field on `fpu_o_t`: there is nothing in the current
  pipeline that would consume it. Adding it would be a forward-looking
  field with no current reader, which contradicts §1.4 principle 4.

---

## 7. TOML schema implications

The Go generator replacing `decode/gen/` reads a TOML representation of
the instruction set. FPU instructions must round-trip through it without
special-casing.

### 7.1 Generalize the busy-tracking column

Under §1.4 principle 3 (greenfield generator may generalize patterns
the old one special-cased, *if it comes for free*), the generator's
internal model should treat busy-tracking as a named list of execution
units rather than as two hardcoded paths.

Schema sketch:

```toml
# Top-level: declare the execution units the CPU has. The generator
# uses this list to size pipeline records and emit per-unit stall logic.
[[exec_unit]]
name        = "mac"
busy_signal = "mac_busy"
states      = ["NOT_BUSY", "EX_NOT_STALL", "EX_BUSY",
               "WB_NOT_STALL", "WB_BUSY"]

[[exec_unit]]
name        = "fpu"
busy_signal = "fpu_busy"
states      = ["NOT_BUSY", "EX_NOT_STALL", "EX_BUSY",
               "WB_NOT_STALL", "WB_BUSY"]
```

For each `exec_unit`, the generator emits the corresponding enum
(`{name}_busy_t`), the pipeline record fields, the decoder port, and
the stall-combinator line. Adding a third unit later (e.g. a crypto
coprocessor) is a TOML change, not a generator change.

This is a one-time generalization at generator-design time; the cost is
a single iteration over the `exec_unit` list in the code that emits
`decode_pkg.vhd` and `decode_core.vhm`. Cheap and clean.

### 7.2 Per-instruction shape

```toml
[[instruction]]
mnemonic    = "FADD"
pattern     = "1111nnnnmmmm0000"
plane       = "normal"
unit        = "fpu"                  # routes to coproc dispatch path
fpu_busy    = "EX_BUSY"              # this instruction stalls if FPU busy
fpu_stall_sense = true
coproc      = { op = "FOP_ADD",
                uses_rna = "frm",
                uses_rnb = "frn",
                precision = "PR_dep"  # follows FPSCR.PR
              }

[[instruction]]
mnemonic    = "FMOV.S"
variant     = "loadidx"
pattern     = "1111nnnnmmmm0110"
plane       = "normal"
unit        = "fpu"
# CPU side does the memory read; FPU side is single-cycle
mem         = { issue = true, wr = false, size = "long",
                addr_sel = "ZBUS" }
coproc      = { op = "FOP_MEM_W", uses_rnb = "frn" }
# No fpu_busy / fpu_stall_sense: single-cycle, no stall needed.

[[instruction]]
mnemonic    = "FMOV"
variant     = "double_load"
pattern     = "1111nnn0mmmm1000"     # nnn0: even FR only (DR pair)
plane       = "normal"
unit        = "fpu"
# Multi-row: two memory reads, two FPU write beats
rows = [
  { mem = { issue = true, wr = false, size = "long",
            addr_sel = "XBUS" },             # @Rm
    coproc = { op = "FOP_MEM_W", uses_rnb = "drn_hi" } },
  { mem = { issue = true, wr = false, size = "long",
            addr_sel = "XBUS_PLUS_4" },      # @(Rm+4)
    coproc = { op = "FOP_MEM_W", uses_rnb = "drn_lo" } },
]
```

### 7.3 What the generator must learn

1. **A `unit` field** that routes instructions to ALU / shifter /
   multiplier / FPU / etc. microcode columns. Existing j-core
   instructions get `unit = "alu"` or similar; FPU instructions get
   `unit = "fpu"`.

2. **Multi-row instructions** as a first-class concept (`rows = [...]`
   array). Existing multi-cycle multiplies were expressed in the ODS by
   having multiple rows with the same mnemonic and incrementing cycle
   numbers — the new TOML makes this explicit and reviewable.

3. **Pattern wildcards beyond `n` and `m`.** FPU encodings need
   `nnn0` / `mmm0` ("even register only" for DR/FV/XMTRX) and possibly
   `nn00` ("FV0/4/8/12 only"). Settled in Phase 0.

4. **Precision-dependent expansion.** For arithmetic ops, the same
   16-bit encoding executes as single or double depending on FPSCR.PR.
   The generator emits ONE microcode row whose op is precision-tagged;
   the FPU itself reads FPSCR.PR to dispatch internally. Open question
   recorded as §10 #4 — settle before Phase 2 begins.

### 7.4 Phase 0 exit criterion (updated)

"TOML can express:
- the existing SH-2 instruction set with byte-identical decoder output
  to the Clojure generator's output, AND
- all 23 Tier A FPU instructions including the multi-row double FMOV
  forms, AND
- the new `exec_unit` declaration with both `mac` and `fpu` units
  producing correct pipeline stall logic.

The FPU module itself does not need to exist yet — a stub with
`fpu_o.busy = '0'` is sufficient to validate the generator and the
decoder/CPU wiring."

---

## 8. IEEE-754 conformance target

We target SH-4-compatible behaviour, which is itself a constrained subset
of IEEE-754. Per §1.4 principle 5, when in doubt, qemu's `target/sh4` is
the reference. **J2 implements the SH-4 hardware/software co-design model
for denormals via Cause.E (§3.8, §4.3): the hardware handles normalized
inputs only and traps to software for denormal cases.**

| Aspect                  | Target                                                 |
| ----------------------- | ------------------------------------------------------ |
| Formats                 | binary32, binary64                                     |
| Rounding modes          | RM=00 round-nearest-even, RM=01 round-toward-zero;     |
|                         | RM=10/11 treated as round-to-zero (qemu behaviour)     |
| Reset rounding mode     | **RM=01 (round-to-zero)**; software must reprogram     |
|                         | FPSCR for round-to-nearest-even                        |
| Denormal inputs (DN=1)  | flush to ±0 with sign preserved in hardware, no trap   |
| Denormal inputs (DN=0)  | **trap via Cause.E**, software emulates (SH-4 model)   |
| Denormal results (DN=1) | flush to ±0 in hardware, set Cause.U/Flag.U on flush   |
| Denormal results (DN=0) | **trap via Cause.E**, software emulates (SH-4 model)   |
| FPU exception precision | **precise**; SPC = offending FPU instruction PC;       |
|                         | offending instruction's result write-back suppressed   |
| Default NaN (single)    | 0x7FBFFFFF (sign=0, exp=all-1, mantissa MSB=0,         |
|                         | next bits set) — SH-4 default qNaN                     |
| Default NaN (double)    | 0x7FF7FFFFFFFFFFFF — SH-4 default qNaN                 |
| qNaN convention         | mantissa MSB=0 → qNaN, MSB=1 → sNaN (SH-4 / MIPS-style |
|                         | convention, **opposite** of IEEE-754-2008 default)     |
| NaN propagation         | for binary ops, propagate input NaN if any (favouring  |
|                         | the first NaN operand); for invalid operations on      |
|                         | non-NaN inputs, produce default qNaN; sNaN inputs      |
|                         | quieted on first use and set V flag                    |
| FCMP with NaN           | both FCMP/EQ and FCMP/GT return T=0; set V flag        |
| Exception flags         | V, Z, O, U, I; Cause cleared per-op, Flag sticky (§4.3)|
| Cause.E (FPU Error)     | always traps when set; no Enable.E (§3.8, §4.3)        |
| Exception traps         | via `fpu_o.exc` → illegal_instr (§3.8); precise         |
| FMAC                    | single-precision only; non-fused (round-after-mul,     |
|                         | round-after-add); SH-4 conformant, NOT IEEE-2008 FMA   |
| FTRC overflow / NaN     | +overflow / NaN / +Inf → 0x7FFFFFFF, set V;            |
|                         | -overflow / -Inf → 0x80000000, set V (§5.1)            |

**Implication of the Cause.E model.** With DN=0 and any denormal
involved, the FPU traps and Linux emulates the operation. This means
DN=0 performance is dominated by trap latency, not FPU throughput.
Code that runs in DN=1 mode (the post-reset default) never trips
Cause.E for denormals and runs at full FPU speed. This matches
real-world SH-4 behaviour and is what software actually expects.

**[Implementation freedom].** For Tier C double-precision, J2 may
optionally trap *any* double-precision arithmetic via Cause.E and
emulate it in software (similar to how the SH-2A's hardware emulates
double-precision in some configurations). This would be a much
smaller hardware footprint than implementing IEEE-754 binary64
arithmetic. **Decision deferred to Phase 3 architectural review** —
likely we implement at least basic double-precision arithmetic in
hardware (FADD/FSUB/FMUL) and trap the rest, but specifics need
benchmarking against typical SH-4 software workloads.

Test strategy is **vector-driven**: hand-curated unit cases plus
Berkeley TestFloat vectors filtered to the supported rounding modes,
plus **differential testing against qemu** (boot qemu in single-step
mode, run identical instruction streams, diff FPSCR + FR + FPUL state
after each FPU op). The qemu comparison is the highest-confidence
check for SH-4 binary compatibility.

Additionally, **Cause.E precision testing**: assemble a sequence of
FPU instructions with a denormal injected at a known instruction,
run it through the FPU, verify SPC at the trap matches the injected
instruction PC and the register state matches "instruction did not
execute". This is a small but important set of tests since the SH-4
binary-compat story rests on this guarantee.

Each arithmetic block testbench reads its vector file, applies inputs,
checks results and flag updates. Vectors live under `tests/vectors/`.

---

## 9. Test plan summary

Test layers (specified in detail in the implementation plan; here for
reference only):

1. **Block TAP testbenches** — one per FPU sub-block under `tests/`:
   `fpu_regfile_tap.vhd`, `fpu_fpscr_tap.vhd`, `fpu_addsub_tap.vhd`,
   `fpu_mul_tap.vhd`, `fpu_div_tap.vhd`, `fpu_cmp_tap.vhd`,
   `fpu_cvt_tap.vhd`, `fpu_beat_seq_tap.vhd`.
2. **IEEE-754 vector-driven testbenches** — TestFloat-derived files
   consumed by the same TAP testbenches above. Vectors live under
   `tests/vectors/`.
3. **ISA-level assembly tests** under `testrom/tests/`: `testfmov.s`,
   `testfldi.s`, `testfadd.s`, `testfmul.s`, `testfdiv.s`, ...
4. **Differential testing** against a C model (`sim/fpu_model.c`) that
   implements SH-4 FPU semantics in software; the simulator compares
   FR/FPUL/FPSCR state after every retired FPU instruction.

---

## 10. Open questions / TBDs (consolidated)

Resolved since v0.2:
- ~~Endianness for double FMOV~~ — resolved (§3.7): big-endian, FRn at
  low address, FR(n+1) at high address. Confirmed against SH-4 spec
  and qemu.
- ~~TOML row shape for PR-dependent ops~~ — resolved: one row per SH
  encoding with FPU-internal PR dispatch. Multi-row TOML reserved for
  multi-cycle memory ops (double FMOV) and multi-microcode arithmetic.
- ~~FPSCR.DN=0 support~~ — resolved (§8): **required** for SH-4 binary
  compatibility. Both DN=0 (gradual underflow) and DN=1 (FTZ) paths
  must be implemented.
- ~~Address-source for double FMOV second row~~ — answered by qemu
  reference: simply `Rm + 4`. The TOML `addr_sel = "XBUS_PLUS_4"`
  (or equivalent name) is the cleanest representation; verify the
  existing j-core decoder supports a base+4 addressing form or extend
  it minimally. The post-increment FMOV variants already advance Rm by
  8 (qemu confirms), so for `FMOV @Rm+, DRn` the second row uses the
  unchanged base address and the increment happens at the end.

Resolved since v0.1 (carried forward):
- ~~§3.4 op encoding allocation~~ — resolved (option (b), 19 codes
  defined, 9 reserved).
- ~~§3.6 back-pressure mechanism~~ — resolved (mac_busy-style path).

Resolved since v0.3:
- ~~Precise vs imprecise FPU exceptions~~ — resolved (§3.8): SH-4 uses
  precise FPU exceptions, confirmed by Linux kernel `fpu_error` handler
  which reads the offending instruction at `regs->pc`. J2 inherits
  this via the existing precise illegal-instruction trap path, with
  `fpu_o.exc` OR'd into `illegal_instr` at the decode level.
- ~~`fpu_o.exc` injection point~~ — resolved (§3.8): at the `decode`
  level, OR'd into `illegal_instr`. The illegal-instruction path in
  j-core is already precise so no additional plumbing is needed.
- ~~DN=0 implementation cost~~ — resolved (§8): J2 follows the SH-4
  hardware/software co-design model. Hardware handles normalized
  inputs only; denormals (input or output, when DN=0) trap via
  Cause.E to software. The Linux kernel SH-4 FPU handler already
  contains the emulation routines (`denormal_addf`, `denormal_mulf`,
  etc.) and works as-is on this model.

Still open:

1. **Initial state of `fpu_o.busy`** when no FPU is synthesized
   (compile-time disable, parallel to `COPRO_DECODE`): tie to '0' at
   `cpu.vhd` level when an `FPU_SYNTH` generic is false; arrange for
   FPU opcodes to trap as illegal instructions in that build.
2. **FRCHG/FSCHG with PR=1 actual SH-4 silicon behaviour**: the spec
   says "setting prohibited" and there are anecdotal reports of some
   chips trapping while others toggle silently (qemu bug 1796520).
   We follow qemu (toggle silently). If a real-silicon corner case
   surfaces, revisit.
3. **Two-bank physical implementation**: the SH-4 FR/XF bank switch
   is conceptually a register rename. Cheapest J2 implementation is
   one 32×32 flop array with bank-bit XORed into the address. Verify
   this matches FRCHG cycle count expectations (single-cycle).
4. **Double-precision arithmetic scope** (§8 implementation freedom):
   how much of Tier C is hardware vs trap-and-emulate. Deferred to
   Phase 3 architectural review.
5. **Linux SH-4 FPU handler binary compat verification**: once Phase 1
   is up, boot a Linux kernel with `CONFIG_SH_FPU=y` (not `_EMU=y`)
   and confirm the `fpu_error` handler successfully services Cause.E
   traps on J2. This is the gold-standard binary compat test.

---

## 11. Revision history
- v0.4 (current): resolved §3.8 precise vs imprecise FPU exception
  question. SH-4 uses precise FPU exceptions; confirmed by the Linux
  kernel `arch/sh/kernel/cpu/sh4/fpu.c` handler which reads the
  offending instruction at `regs->pc`. Rewrote §3.8 with the J2
  implementation mechanism (fpu_o.exc OR'd into illegal_instr at
  decode level; precise by virtue of the mac_busy-style stall keeping
  the FPU instruction's PC as the current architectural PC).
  Discovered and documented the SH-4 Cause.E hardware/software
  co-design model: Cause.E has no Enable bit, always traps, and is
  how SH-4 silicon offloads denormal arithmetic to software. J2
  adopts this model — major hardware simplification (§4.3, §8). Added
  qNaN convention clarification (mantissa MSB=0 → qNaN, SH-4/MIPS
  style, opposite of IEEE-754-2008). Closed §10 #1, #2, #3; added
  new TBDs for synth-disable, double-precision scope, and Linux
  binary-compat test.
- v0.3: added §1.4 principle 5 (SH-4 binary compatibility).
  Resolved §3.7 endianness (big-endian, FRn at low address, confirmed
  against SH-4 spec and qemu). Fixed FPSCR reset note (§4.3): RM=01 =
  round-to-zero (not round-to-nearest). Documented Cause-cleared-per-op
  vs Flag-sticky semantics (§4.3). Added explicit SH-4 binary-compat
  notes for FTRC, FMAC, FCMP (§5.1–§5.3). Tightened §8 conformance
  table with default qNaN bit patterns, both DN paths required, and
  FCMP NaN behaviour. Added differential testing against qemu to §8
  test strategy. Updated §10 TBDs: closed endianness, DN=0,
  address-source, and TOML-row-shape; left precise-exception
  attribution and synth-disable behaviour open. Added Appendix §A
  enumerating SH-4 reference sources.
- v0.2: added §1.4 decision principles (minimum diff,
  reuse idioms, dormant signals stay dormant). Resolved §3.4 op
  encoding allocation and §3.6 back-pressure (mac_busy-style path
  with `fpu_o.busy` and per-instruction stall_sense). Rewrote §3.5
  handshake examples to reflect the actual mechanism (not `cop_i.ack`,
  which is dormant). Updated §3.8 to route FPU exceptions through
  `fpu_o.exc` and the existing `illegal_instr` path. Generalized §7
  TOML schema with named `exec_unit` declarations. Updated §10 with
  new open questions surfacing from `datapath.vhm` inspection.
- v0.1 (initial draft): scope, multi-beat protocol skeleton, Tier-A
  encodings, TOML schema sketch, IEEE-754 target, TBDs enumerated.

---

## Appendix A: SH-4 binary compatibility references

Primary, in order of authority:

1. **Renesas SH-4 Software Manual, Rev. 5.0 (ADE-602-156D)**, April 2001.
   The canonical ISA reference. Section 2.2.3 (floating-point registers),
   section 6 (Floating-Point Unit), section 9 (instruction descriptions
   FABS through FTRV, pages 232–282). When silicon and manual disagree,
   the manual loses — but historically the SH-4 silicon has matched the
   manual closely on FPU behaviour.

2. **Renesas SH-4A Software Manual, Rev. 1.50 (REJ09B0003-0150Z)**,
   October 2004. Useful for clarifications that the older SH-4 manual
   left ambiguous. Adds FPCHG, FSCA, FSRRA, FSRRA (out of scope for J2
   FPU revision 1). The SH-4A also documents the "SZ=1, PR=1" fix mode
   for little-endian double FMOV.

3. **qemu `target/sh4`**, post-2017 Aurélien Jarno cleanup
   (`qemu/qemu` repo, `target/sh4/translate.c` and `op_helper.c`). The
   2017 patches "target/sh4: fix FPSCR cause vs flag inversion",
   "target/sh4: fix FPU unordered compare", and the patch series at
   `https://lists.gnu.org/archive/html/qemu-devel/2017-07/msg00424.html`
   together correct several subtle bugs in earlier qemu versions.
   Treat any qemu commit after these patches as authoritative for
   behaviour the manual underspecifies.

4. **`sh-elf-gcc` `-m4` and `-m4-single` codegen.** Whatever the
   compiler actually emits is what J2 must accept; reading the output
   of representative C programs compiled with these flags is the
   ground truth for "what software expects".

Secondary / cross-reference:

5. **STMicroelectronics SH-4 32-bit CPU Core Architecture manual**
   (`cd00147165`, 2002). STMicro licensed the SH-4 from Hitachi and
   published their own reference; useful as a cross-check on the
   Renesas wording.

6. **Linux kernel `arch/sh/kernel/cpu/sh4/fpu.c`** (and the analogous
   `arch/sh/kernel/cpu/sh2a/fpu.c`). The `fpu_error` trap handler and
   its `ieee_fpe_handler` worker function are the de-facto definition
   of what SH-4 FPU exception semantics actually are in production
   software. The handler reads the offending FPU instruction directly
   from `*(unsigned short *)regs->pc`, decodes it, and emulates the
   operation in software — proving that SH-4 raises **precise** FPU
   exceptions (SPC = offending instruction PC) and that the Cause.E
   mechanism is the architectural contract by which hardware punts
   denormal arithmetic to software. Specifically of interest:
   `denormal_addf`, `denormal_mulf`, and similar functions in
   `arch/sh/math-emu/sfp-util_32.h` — these are the routines J2's
   FPU implementation must trigger correctly via Cause.E for
   binary compatibility.

7. **NetBSD `sys/arch/sh3`**. Independent OS port to the SH family;
   similar value as the Linux source above for cross-checking
   software assumptions.

When this spec says "binary compatibility with SH-4", it means: code
compiled by a stock SH-4 toolchain (sources 4) and run on a stock
SH-4 OS (sources 6, 7) must produce architecturally identical results
on J2 FPU. Behaviour not exercised by stock toolchains and OSes is
permitted to differ within the bounds set by source 1 (and broken
ties by source 3).
