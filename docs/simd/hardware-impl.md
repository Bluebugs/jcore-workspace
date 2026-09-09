# J-Core SIMD — Hardware Implementation Guide

**Status:** Consolidated draft (replaces the Tier 0/1 pipeline-implementation guidance previously in spec-v0.5 §7 and the vclmul-hardware-impl document, on 2026-05-25).
**Audience:** J-Core HDL (VHDL/Verilog) developers, microarchitecture, FPGA bring-up.
**Companion documents:** [spec.md](spec.md) (architecture, single source of truth), [software-impl.md](software-impl.md) (toolchain, kernels).

This guide describes implementation tactics for the SIMD architecture. The architecture itself — what software sees — is specified entirely in [spec.md](spec.md); this document supplies datapath sketches, pipeline integration, area/timing estimates, verification approach, and bring-up checklists. Tier numbering matches [spec.md §1.1](spec.md).

---

## 1. Scope and organisation

- **Tier 0 / Tier 1 (§2–§5):** the VLEN-wide SIMD execution unit (256-bit on J32, 512-bit on J64; spec.md §1.2). Decode-stage shadow latch, VLEN/32-beat sequencing, coprocessor port sharing, J32-OOO dual-issue considerations, non-temporal memory handling, the additional Tier 1 datapath (saturation, VABS, VPOPCNT, VUNPK4, VABSDIFF, VPACK, VMULSU).
- **Tier 2 (§6–§12):** the GF(2) crypto unit (VCLMUL.D, VCRC32C.B). Three implementation tiers (A combinational, B Karatsuba pipelined, C iterative); reuse strategy for the existing widening multiplier; VCRC32C.B as decode-stage fusion onto VCLMUL.D; pipeline integration; verification; synthesis targets; timing; power; test/debug; bring-up.

The Tier 3 (256-bit J64) wide-vector extension has no architectural specification yet and therefore no hardware implementation guidance.

---

## 2. Tier 0/1: Decode-stage shadow latch

The SIMD prefix's effect must reach the decode of the *immediately following* instruction. On the 5-stage J32 pipeline (IF / ID / EX / MA / WB), this requires forwarding the prefix's decoded state from its own ID stage to the next instruction's ID stage in the next cycle.

```
cyc        1     2     3     4     5
prefix     IF    ID*   EX    MA    WB
gov-1            IF    ID**  EX0   ...
gov-2                  IF    ID    EX0  ...

ID*  = prefix sets shadow latches SIMD_VAL, SIMD_W, SIMD_H, SIMD_CNT,
       SIMD_RED (H=1) or SIMD_SAT (Tier 1, H=0)
ID** = gov-1 reads shadow latches, decodes via SIMD decode table
```

Shadow latch sizes:

- Tier 0 only: 6 flip-flops (SIMD_VAL, SIMD_CNT[1:0], SIMD_W[1:0], SIMD_H) + 3 flip-flops (SIMD_RED[2:0]) + 9 flip-flops (V_LANE_VALID + V_LANE_REG[3:0] + V_LANE_IDX[3:0]) = **18 bits**.
- Tier 0+1: adds 2 flip-flops (SIMD_SAT[1:0]) = **20 bits** total.

None of these are architecturally visible (see [spec.md §2.5, §6.1](spec.md)). They are cleared at all exception boundaries.

---

## 3. Tier 0/1: Beat-serial ALU sequencing and the restart-from-prefix mechanism

### 3.1 Beat schedule

For each governed instruction, the EX stage is extended into **VLEN/32 sequential beats** (spec.md §1.2: VLEN = 256 on J32 → **8 beats**, 512 on J64 → 16 beats) on a 32-bit ALU. A 32-bit ALU consumes 32 bits of lanes per beat, so the beat count is VLEN/32 independent of lane width *w*:

| Lane width | Lanes per beat (32-bit ALU) | Beats (J32, VLEN 256) | Beats (J64, VLEN 512) |
|---|---|---|---|
| 8  | 4   | 8 | 16 |
| 16 | 2   | 8 | 16 |
| 32 | 1   | 8 | 16 |
| 64 | 0.5 | 8 | 16 |

A wider ALU (e.g. a 64-bit or 128-bit SIMD datapath) reduces the beat count proportionally (VLEN/64, VLEN/128).

Carry chains are broken at lane boundaries within each beat using AND gates on the carry-out of each *w*-bit segment. The horizontal-mode reduction sums into an internal 64-bit accumulator that is written back to MACL/MACH (integer) or FR0/DR0 (FP) at WB — the FP writeback reuses the FPU's existing FR/DR write ports ([spec.md §2.3](spec.md); VFPUL retired).

Adjacent governed instructions may interleave their beats provided source/destination conflicts are honoured. On a single-ALU J32 implementation, beats are sequential. On a dual-issue J32-OOO ([../ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md)), a second ALU may consume beats in parallel for distinct lane subsets, halving the per-instruction beat count.

Prior art: Cray-1 multi-cycle vector execution on a narrow datapath (1976).

### 3.2 Restart-from-prefix microarchitecture

The architectural N=1 memory-access rule ([spec.md §5.6.1, §6.4](spec.md)) lets the implementation handle in-block memory faults via the **restart-from-prefix** mechanism:

1. The faulting governed memory access is the sole compute in the block (N=1 enforced at decode).
2. On any memory exception, the EX-stage logic raises the standard SH-4 memory exception with the saved PC pointing to **the prefix instruction**.
3. The shadow latches are unconditionally cleared by the exception entry logic (same code path as slot-illegal entry; no SIMD-aware bookkeeping required).
4. RTE returns to the prefix; the block reopens; the memory access retries.

The implementation contract: the exception entry logic must clear `SIMD_VAL`, `SIMD_CNT`, `SIMD_W`, `SIMD_H`, `SIMD_RED`, `SIMD_SAT`, `V_LANE_VALID`. Address registers used in post-increment / pre-decrement modes must commit only after the access succeeds — this is the standard SH-4 convention and applies unchanged. Gather/scatter writes commit in lane-index order so that previously-completed lanes act as idempotent no-ops on retry.

This mechanism is the architectural answer to the software-MMU problem and avoids the cost of microarchitectural write-buffering of all governed-instruction results (which would be ~N × VLEN bits per block — ~4 × 256 = 1024 b on J32, 4 × 512 = 2048 b on J64 — plus scatter-destination buffers, a significant area cost the N=1 rule sidesteps entirely).

---

## 4. Tier 0/1: Coprocessor port sharing

The j-core coprocessor port (already used by the SH-4 FPU and the MMU in J3) is the natural attachment point for the SIMD execution unit. The unit shares:

- The FPU multiplier and adder for FP governed instructions.
- The FPU register file ports for SIMD FP reduction destination writes (FR0/DR0, and the 4-wide FTRV port for VFTRV).
- The integer ALU for integer governed instructions (the SIMD unit muxes lane width into the ALU's carry-break controls).
- The integer widening multiplier for MULS.W / MULU.W governed instructions and (Tier 1) for VMULSU.

The swizzle crossbar is a new structure attached to the V register file's read ports.

Lane count is VLEN/w; the table below is the **J32 (VLEN 256)** worst case (J64 doubles each lane count and roughly quadruples the crossbar). The sizes are structural — they follow from VLEN and the lane width, not from a synthesis run:

| Lane width | Lanes = VLEN/w (J32) | Crossbar size |
|---|---|---|
| 32 | 8  | 8×8 of 32-bit buses   |
| 16 | 16 | 16×16 of 16-bit buses |
| 8  | 32 | 32×32 of 8-bit buses  |
| 64 | 4  | 4×4 of 64-bit buses   |

Crossbar area: unknown at this stage — needs measurement. It has not been synthesized for either target.

A single physical crossbar is sized for the worst case (32×32 at 8-bit width on J32; 64×64 on J64) and serves all widths.

---

## 5. Tier 0/1: Non-temporal memory access handling, dual-issue, area

### 5.1 Non-temporal hint handling

The NT bit on a SIMDV prefix ([spec.md §3.2, §5.6.2](spec.md)) is an advisory hint. Implementation options:

- **Write-combining buffer for VST.Q.NT / VSCATTER.Q.NT:** small (64–256 bytes) coalescing buffer bypassing the L1 data cache; flushes on full or on explicit fence. Pattern follows Intel SSE MOVNTPS implementation lineage (1999). Trade-off: minimal silicon, weaker ordering (software needs explicit memory fence before reading data it just wrote with NT through the cache).
- **Streaming cache way for VLD.Q.NT / VGATHER.Q.NT:** small dedicated way of L1-D reserved for non-temporal reads; FIFO replacement avoids polluting regular ways with one-shot data.
- **Cache bypass:** most aggressive option; reads directly from main memory through a streaming channel. Maximum sustained bandwidth, full memory latency per access. Practical only for predictable strided / block-streaming workloads.

**Implementation guidance:** for a typical J32 deployment (16–32 KB L1), the write-combining buffer for stores is the highest-value addition. The streaming cache way is lower priority. Cache bypass is rarely worth it for in-order embedded cores.

Implementations that do not provide a streaming-friendly cache path may treat NT-flagged operations as normal cached accesses; the architectural result is identical. Each implementation should document in its programmer's reference exactly what NT does on that part.

### 5.2 J32-OOO dual-issue considerations

On a dual-issue J32-OOO, two governed instructions may execute in parallel provided:

1. They are both governed by the same prefix block.
2. They do not share a destination vector.
3. They do not violate beat scheduling (the second ALU consumes a different lane subset per beat).

The dual-issue scheduler must respect the prefix's atomicity: an interrupt may not be taken between the two simultaneously-issued governed instructions of a block, only after the entire block retires. See [../ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md) for the OoO machine's prefix-cracking strategy.

### 5.3 Tier 1 cost summary

Cumulative Tier 1 cost atop a Tier 0 J32 implementation. **Area, per feature and in total: unknown at this stage — needs measurement** — no Tier 1 datapath has been synthesized for either target, so the ordering below (which features are cheap and which is the expensive one) is design reasoning, not a measured ranking:

| Feature | Critical path impact | Structure |
|---|---|---|
| Saturation in SIMDV (SIMDVS/SIMDVU) | none | Saturation muxes parallel to ALU; reuses existing ADD/SUB datapath |
| VABS | none | Negate + select, lane-parallel |
| VPOPCNT | adds one cycle on widest lanes if naive | Wallace-tree popcount per byte; VLEN/8 byte units (32 on J32, 64 on J64); 32/64-bit per-lane trees dominate. The one Tier 1 feature expected to dominate the group's area |
| VUNPK4 | none | AND-masks + sign-extend muxes |
| VABSDIFF | none | SUB result + per-lane two's-complement-and-select |
| VPACK family | none | Saturating clamp comparators per output lane |
| VMULSU | none | Existing MULS datapath; single sign-control mux on multiplier's second operand |

Structural, for scale: Tier 0's V register file is **16 × 256 = 4,096 flip-flops on J32** (8,192 on J64). That count follows from the register file's shape, not from synthesis.

**Partial-Tier-1 deployments.** Per [spec.md §10](spec.md), an implementation may pick any subset of Tier 1 features. Suggested subsets: bitmap analytics / search / bioinformatics (VPOPCNT + saturating modes); video / vision (VABSDIFF + VABS + sat); DSP / audio (sat + VPACK + VABS); LLM inference (VMULSU + VUNPK4 + VPACK + sat); full Tier 1. Which subset fits a given area budget is unknown at this stage — needs measurement.

### 5.4 Pipeline-stage placement summary (Tier 0/1)

```
Stage:    IF    ID       EX (beats 0..VLEN/32-1)     MA            WB
Prefix:   ──── ID*  ────── (no compute)            ──────         ──────
Gov:      ──── ID** ────── VLEN/32-beat ALU/mult ── MA(memops) ── writeback
                                                                   to V<n> /
                                                                   MACL+MACH /
                                                                   FR0 / DR0
```

ID* updates shadow latches; ID** reads them. Memops use the existing MA stage and the standard SH-4 memory-fault path with restart-from-prefix (§3.2).

---

## 6. Tier 2: VCLMUL.D datapath

### 6.1 The core operation: 64×64 → 128-bit GF(2) multiply

A 64-bit GF(2) polynomial multiply produces a 128-bit result. Logically it is a 64×64 AND array (4096 AND gates) followed by an XOR reduction tree of depth log2(64) = 6 levels (approximately 4030 two-input XOR gates).

For comparison, a 64×64 → 128 integer multiplier of equivalent throughput requires the same AND array plus a carry-save adder tree plus a final carry-propagate adder — strictly more logic, by construction. **The GF(2) multiplier is structurally a subset of the integer multiplier with the carry chain removed.** This subset relationship is the key reuse opportunity (§7).

Architectural prior art: Mastrovito (1991) bit-parallel GF(2^m) multiplier; Karatsuba & Ofman (1962) for the sub-divide-and-conquer decomposition; standard pre-2006 references in [spec.md Appendix C.3.1](spec.md).

### 6.2 Implementation Tier A — single-cycle combinational

Full 64×64 AND array + Wallace-tree XOR reduction in one cycle.

```
                                              ┌────────────┐
   Vn[63:0] ─────────┐                       │ Wallace    │
                     ▼                       │ XOR tree   │
                    ┌────┐                   │ 6 levels   │
                    │AND │ ──→ 64 partial ──→│            │── result[127:0]
                    │64×64│    products       │            │
                    └────┘                   │            │
                     ▲                       │            │
   Vm[63:0] ─────────┘                       └────────────┘
```

**Structural cost** — fixed by the algorithm, the same counts §6.1 derives, and
true of any implementation:
- AND gates: 4096 (64 × 64)
- XOR gates: ~4030, in a reduction tree of depth log2(64) = 6 levels
- Latency: 1 cycle
- Throughput: 1 CLMUL per cycle

**Area, and critical path / Fmax: unknown at this stage — needs measurement.**
See §11.1 and §11.2.

**When to use:** J64 performance tier, or an `[ASIC]` target with a generous area
budget. Whether a Phase-1 ULX3S/ECP5 build has the fabric to absorb Tier A is
unknown at this stage — needs measurement.

### 6.3 Implementation Tier B — pipelined Karatsuba (recommended baseline)

Decompose 64×64 into three 32×32 GF(2) multiplies:

```
Given: a = a_hi · x^32 + a_lo
       b = b_hi · x^32 + b_lo

Karatsuba: P0 = a_lo · b_lo                     (32×32 → 64 CLMUL)
           P1 = a_hi · b_hi                     (32×32 → 64 CLMUL)
           P2 = (a_lo ⊕ a_hi)(b_lo ⊕ b_hi)      (32×32 → 64 CLMUL)
           middle = P2 ⊕ P0 ⊕ P1
           result = P1 · x^64 ⊕ middle · x^32 ⊕ P0
```

Pipeline:

```
   ┌──────────────────────────────────────────────────────────┐
   │ Stage 1: Operand split + XOR for P2                      │
   │   a_hi, a_lo ← split(Vn);  b_hi, b_lo ← split(Vm)        │
   │   a_xor ← a_hi XOR a_lo;   b_xor ← b_hi XOR b_lo         │
   └──────────────────────────────────────────────────────────┘
                              │
                              ▼
   ┌──────────────────────────────────────────────────────────┐
   │ Stage 2: Three parallel 32×32 GF(2) multiplies           │
   │   P0 = clmul32(a_lo, b_lo)                               │
   │   P1 = clmul32(a_hi, b_hi)                               │
   │   P2 = clmul32(a_xor, b_xor)                             │
   └──────────────────────────────────────────────────────────┘
                              │
                              ▼
   ┌──────────────────────────────────────────────────────────┐
   │ Stage 3: Combine                                         │
   │   middle = P2 XOR P0 XOR P1                              │
   │   result = (P1 << 64) XOR (middle << 32) XOR P0          │
   └──────────────────────────────────────────────────────────┘
```

**Structural cost** — fixed by the Karatsuba decomposition above, not by any
target:
- 3× 32×32 GF(2) multipliers, each a 1024-entry AND array (32 × 32) plus a
  5-level XOR reduction tree
- Combining logic: two 64-bit XOR layers (`middle`) plus the shifted-XOR merge
- Latency: 3 cycles
- Throughput: 1 CLMUL per cycle (fully pipelined)

**Area, pipeline-register count, and critical path / Fmax: unknown at this stage — needs measurement.**
Tier B's design *goal* is the project's `[ASIC]` frequency target of
400–500 MHz ([j4-remediation-plan.md](../j4-remediation-plan.md) guiding
principle 1); that is a goal, not an achieved result.

**When to use:** J32-FM and J64 baseline (recommended default). Tier B is chosen
for area over Tier A at the cost of 3-cycle latency; by how much it wins is
unknown at this stage — needs measurement.

### 6.4 Implementation Tier C — iterative shift-XOR

Reuses the existing integer widening multiplier's shift register and partial-product accumulator. The integer multiplier already has a 64-bit shift-and-add loop; gating the carry chain (forcing it to XOR-only) makes the same hardware perform GF(2) multiplication.

```
   ┌─────────────────────────────────────────────────────┐
   │   Existing widening multiplier datapath             │
   │                                                     │
   │   ┌───────┐   ┌─────────┐   ┌────────────┐         │
   │   │ shift │──→│partial  │──→│accumulator │         │
   │   │ reg   │   │product  │   │128-bit     │         │
   │   └───────┘   └─────────┘   └────────────┘         │
   │       ▲           ▲                │                │
   │       │           │                ▼                │
   │   ┌───────────────────────────────────────┐         │
   │   │  gf2_mode signal: when '1', accumulator│         │
   │   │  uses XOR instead of ADD and the carry │         │
   │   │  chain is masked off                   │         │
   │   └───────────────────────────────────────┘         │
   └─────────────────────────────────────────────────────┘
```

**Structural cost** — what the mode bit adds, by construction:
- Additional logic on top of the widening multiplier: an XOR-vs-ADD mux on the
  accumulator, a carry-chain mask, and mode-bit decode
- No new flops (the existing shift register and accumulator are reused)
- Latency: 64 cycles per CLMUL (one cycle per bit of operand B)
- Throughput: 1 CLMUL per 64 cycles

**Area: unknown at this stage — needs measurement.** It is the smallest of the three tiers
by construction — it adds control, not a datapath — but no figure is claimed for it.

**When to use:** ultra-low-area J32 deployments where VCLMUL is needed for software correctness but not performance-critical, including embedded SoC variants working to a total-area budget.

### 6.5 Tier selection by target

These picks are **design intent**, not measured recommendations: no tier has
been synthesized for either of this project's targets, so the fit each row
assumes is unknown at this stage — needs measurement.

| Target | Intended Tier 2 tier | Rationale |
|---|---|---|
| J32 minimal (smallest area budget) | Tier C | Reuse existing multiplier, minimal new logic |
| J32-FM, Phase-1 ULX3S / ECP5 | Tier B | Intended area/performance balance |
| J64 baseline | Tier B | Standard target |
| J64 performance / server class | Tier A | Single-cycle for higher clock rates |
| `[ASIC]`, small node | Tier A | Area penalty expected to be negligible at small nodes; power dominates |

Settle the Phase-1 pick with a `yosys` + `nextpnr-ecp5` build targeting the
ULX3S 85F.

---

## 7. Widening multiplier reuse strategy (Tier 2)

### 7.1 The `gf2_mode` control bit

Add a single control bit to the existing widening multiplier interface. When asserted:

1. The partial-product accumulator uses XOR instead of carry-save add.
2. The carry-propagate adder at the multiplier output is bypassed (carry inputs forced to zero).
3. Sign-extension logic in the operand-prep path is disabled (GF(2) operands are unsigned polynomials).

For Tier C, this is the entire implementation. For Tier B, the three 32×32 sub-multipliers each have their own `gf2_mode` bit.

### 7.2 RTL skeleton (illustrative VHDL)

```vhdl
entity multiplier_64x64 is
    port (
        clk        : in  std_logic;
        rst_n      : in  std_logic;
        a_in       : in  std_logic_vector(63 downto 0);
        b_in       : in  std_logic_vector(63 downto 0);
        gf2_mode   : in  std_logic;                      -- new
        valid_in   : in  std_logic;
        result_out : out std_logic_vector(127 downto 0);
        valid_out  : out std_logic
    );
end entity;

architecture karatsuba_pipelined of multiplier_64x64 is
    -- Stage registers, sub-multiplier instances, combining logic.
    -- gf2_mode propagates through pipeline stages alongside operands.
begin
    -- ...
end architecture;
```

`gf2_mode` threads through the pipeline registers identically to the operand data, so back-to-back integer / GF(2) instruction mixing honours the correct mode at each pipeline stage.

### 7.3 Sub-multiplier sharing for Tier B

The three 32×32 sub-multipliers in Karatsuba can be:

- **Three physical multipliers** (full throughput, larger area).
- **One physical multiplier time-shared over three cycles** (one-third throughput, one-third area).

J32-FM should ship with one shared sub-multiplier. J64 baseline should ship with three. The decision can be revisited based on synthesis results without changing the architecture.

---

## 8. Tier 2: VCRC32C.B datapath

### 8.1 Recommended implementation — CLMUL-based fused decode

The recommended implementation **does not add new GF arithmetic silicon for VCRC32C.B**. Instead, the decoder fuses one VCRC32C.B instruction into a short sequence of CLMUL operations against precomputed Castagnoli fold constants.

```
VCRC32C.B Vm, Vn  (under SIMDHA.B, 8-bit horizontal-add prefix)
                    │
                    ▼
       Decoder expands to micro-op sequence:
                    │
                    ▼
   1. CLMUL(Vn[31:0] (zero-extended), CONST_K1)  → temp_lo
   2. CLMUL(Vn[31:0] (shifted),       CONST_K2)  → temp_hi
   3. XOR(temp_lo, temp_hi, Vm (P0-masked))      → folded
   4. Barrett reduction:
         CLMUL(folded_hi, BARRETT_U) → q
         CLMUL(q,         POLY_P)     → q_times_p
         XOR(folded, q_times_p)       → Vn[31:0]
```

Fold constants K1, K2, the Barrett constant U, and the polynomial P live in a small ROM (16 bytes per polynomial; CRC-32C is the only polynomial supported, so 16 bytes total).

Architectural prior art for the Barrett-reduction approach to CRC computation: Sarwate (1988) for the table-driven reference semantics; Mastrovito (1991) for the bit-parallel GF(2) reduction circuitry; Castagnoli-Bräuer-Herrmann (1993) for the specific polynomial 0x1EDC6F41.

### 8.2 LFSR-based alternative

For implementations that omit VCLMUL.D (unusual but permitted), VCRC32C.B can be implemented as a traditional byte-at-a-time LFSR:

```
For each byte (predicated by P0):
    index = (crc ⊕ byte) & 0xFF
    crc   = (crc >> 8) ⊕ TABLE_C[index]
```

A 256-entry × 32-bit ROM (8 kbits) provides TABLE_C lookups. With VLEN/8 bytes per instruction (32 on J32, 64 on J64), options are:
- VLEN/8 parallel ROM ports (impractical).
- VLEN/8 sequential lookups (slow, VLEN/8+ cycles per instruction).
- Multi-banked ROM with 2–4 ports (moderate area, VLEN/32–VLEN/16 cycles per instruction).

The CLMUL-fused approach is strongly preferred; the LFSR path is documented as a fallback for "VCLMUL absent" variants only.

### 8.3 Predicate routing

The P0 mask register is read concurrently with Vm. Each of the VLEN/8 byte-mask bits (32 on J32, 64 on J64) AND-gates the corresponding byte position in Vm before it enters the CLMUL fold. Masked-off bytes contribute zero to the polynomial, leaving the accumulator unchanged for those positions.

```
   Vm   ─────┐                ┌────┐
             ├─→ byte_gate ──→│CLMUL│─→ folded
   P0   ─────┘                │fold │
                              └────┘
```

Implementation: VLEN/8 × 8 = VLEN AND gates at the SIMD ALU input (256 on J32, 512 on J64). Negligible silicon.

---

## 9. Tier 2: Pipeline integration

### 9.1 Stage placement

VCLMUL.D and VCRC32C.B execute in the EX stage of the SIMD pipeline. For Tier B (3-cycle pipelined), they occupy EX1, EX2, EX3.

```
   Stage:    IF    ID    RR    EX1   EX2   EX3   WB
   VCLMUL: ───────────────[clmul────────────]─→──→
   Others:  ──────────────[other ALU]──────────→─→
```

Tier A (single-cycle) collapses EX1–EX3 into one stage for VCLMUL. The pipeline timing is set by the longest path; if Tier A CLMUL is the longest, it sets the clock period for the whole SIMD pipe.

### 9.2 Forwarding paths

- **Result forwarding from VCLMUL to subsequent SIMD ALU ops:** standard EX→ID bypass. With Tier B 3-cycle latency, the result becomes available at EX3; a subsequent instruction in ID three cycles later picks it up directly.
- **Tight CLMUL chains (AES-GCM GHASH):** the common `clmul; xor; clmul; xor` pattern reads each clmul's result 3 cycles later — naturally interleaved without stall when issued under a prefix block (N=4, four CLMULs).
- **CRC accumulator chain (VCRC32C.B loop):** each VCRC32C.B reads `Vn[31:0]` written by the previous instance. The fused micro-op sequence's final XOR result must be forwarded to the next instance's first CLMUL input — a 3-cycle dependency in Tier B. Either stall, or unroll the software loop to interleave independent CRC streams.

### 9.3 Hazard handling

| Hazard | Mitigation |
|---|---|
| Structural: two CLMULs in same cycle, one multiplier | Issue serially; second stalls one cycle |
| RAW on VCLMUL result | Forwarded at EX3→EX1 of next instruction |
| RAW on VCRC32C accumulator | Pipeline stall (3 cycles in Tier B); document this in the part-specific reference manual |
| Interrupt mid-CLMUL | Complete the instruction; standard SH-4 precise-exception model preserved |
| Interrupt mid-VCRC32C fused sequence | Complete or restart at instruction boundary (implementation choice; architecture treats VCRC32C.B as atomic — [spec.md §5.5.2](spec.md)) |

### 9.4 Multi-issue (J64 dual-issue variants)

If J64 ships dual-issue: a CLMUL can co-issue with any non-multiplier SIMD op (XOR, AND, swizzle, predicate manipulation). Two CLMULs cannot co-issue with a single physical multiplier; add a second multiplier or accept serialisation. The J32-OOO machine ([../ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md)) does not implement Tier 2; J64 dual-issue is a forward-looking case.

---

## 10. Tier 2: Verification

### 10.1 Three verification layers

1. **Unit verification of the GF(2) multiplier block** (golden-model bit-exact comparison).
2. **Instruction-level verification against [spec.md](spec.md)** (encoding, prefix-mode trap matrix, predicate semantics).
3. **Workload-level verification on real cryptographic / RAID / storage kernels** (NIST test vectors, RFC 3720 iSCSI vectors, Linux md syndrome cross-check).

### 10.2 Unit verification

Python golden model:

```python
def gf2_mul(a, b):
    """64x64 -> 128 carryless multiply."""
    result = 0
    for i in range(64):
        if (b >> i) & 1:
            result ^= a << i
    return result & ((1 << 128) - 1)
```

Test inputs:
- All-zero and all-ones operands (sanity / full coverage).
- Single-bit operands (`1 << i` for each i).
- Random with biased distributions (1%, 50%, 99% bit density).
- Known products (`0xFFFFFFFFFFFFFFFF ⊗ 0xFFFFFFFFFFFFFFFF` etc.).
- 10⁶ random pairs.

Methodology: apply via VHDL/Verilog testbench; compare with Python golden model bit-for-bit. Coverage targets: 100% AND-array activity, 100% XOR-tree internal-node toggling.

### 10.3 Instruction-level verification

Stimuli driven from a SIMD assembly test suite. Sample (using the canonical `SIMDV.w` syntax):

```asm
test_vclmul_basic:
    ; Vn=V0 ← V0 ⊗ V1, with V0[63:0]=3, V1[63:0]=5
    ; expected V0[127:0] = 0x0F  (binary 0011 ⊗ 0101 = 1111)
    VLDI.Q  #3, V0           ; broadcast 3 (low byte → all lanes; sufficient since
                             ; we then SIMDV.Q so only V0[63:0] matters for clmul)
    VLDI.Q  #5, V1
    SIMDV.Q #1
    VCLMUL.D V1, V0
    ; ... compare V0 against expected_0F via VST.Q + scalar load ...
    BF      fail
```

Verify all exception conditions ([spec.md §6.2](spec.md)):

- VCLMUL.D under horizontal prefix → slot-illegal.
- VCLMUL.D under non-64-bit width prefix → slot-illegal.
- VCLMUL.D with no prefix → slot-illegal.
- VCRC32C.B under vertical prefix → slot-illegal.
- VCRC32C.B under non-8-bit width → slot-illegal.

### 10.4 Workload verification

Three target kernels:

**Kernel 1: AES-GCM streaming (NIST test vectors).**
- Input: NIST GCM test vector (key, IV, AAD, plaintext).
- Expected: ciphertext + tag matching NIST output.
- Stress: large messages (1 MB), back-to-back GHASH operations.

**Kernel 2: CRC-32C buffer (RFC 3720 / iSCSI test vectors).**
- Input: known buffers of varying length (0, 1, 15, 16, 17, 1024, 65535 bytes).
- Expected: known CRC values.
- Stress: pathological tail lengths (15, 31, 47 bytes); fully masked instructions.

**Kernel 3: RAID-6 syndrome (mdadm test pattern).**
- Input: 4-disk RAID-6 with known data.
- Expected: P and Q syndromes matching Linux `md` driver output.
- Stress: 64 KB stripes, all-zero stripes, all-ones stripes.

### 10.5 Co-simulation strategy

1. **Verilator + golden model.** Run J-core RTL under Verilator. At every SIMD instruction retirement, compare register state against the Python golden model. Bit-exact match required.
2. **Linux on J-core (Buildroot).** Boot a minimal Linux with the kernel's crc32c-jcore path enabled and run `crypto/testmgr.c` self-tests.
3. **iperf with iSCSI / NFS-over-RDMA traffic.** Real-network workload verification, measuring CRC throughput improvement.

### 10.6 Coverage targets

- Combinational coverage: 100% of AND-array entries exercised.
- XOR-tree coverage: 100% of internal nodes toggled.
- Predicate mask coverage: all-zero, all-one, alternating, sparse, dense.
- Prefix mode coverage: all legal modes, all illegal modes (traps caught).

---

## 11. Tier 2: Synthesis, timing, power

### 11.1 Synthesis targets

No tier has been synthesized for either of this project's targets — the
Phase-1 ULX3S / Lattice ECP5 board `[FPGA]`, or gf180, the ASIC methodology
vehicle `[ASIC]`. Area and frequency are therefore stated as unknown, per
[decisions/0005](../decisions/0005-unmeasured-figures-are-removed.md):

| Tier | Gate-equivalent area `[ASIC]` | Fmax `[ASIC]` | LUT4 `[FPGA]` | FFs `[FPGA]` |
|---|---|---|---|---|
| Tier A (combinational) | unknown at this stage — needs measurement | unknown at this stage — needs measurement | unknown at this stage — needs measurement | unknown at this stage — needs measurement |
| Tier B (Karatsuba pipelined) | unknown at this stage — needs measurement | unknown at this stage — needs measurement | unknown at this stage — needs measurement | unknown at this stage — needs measurement |
| Tier C (iterative) | unknown at this stage — needs measurement | unknown at this stage — needs measurement | unknown at this stage — needs measurement | unknown at this stage — needs measurement |

**Goal, not a result:** the `[ASIC]` frequency target for this project is
~400 MHz+ ([j4-remediation-plan.md](../j4-remediation-plan.md) guiding
principle 1); the Phase-1 `[FPGA]` goal is **fit and correctness**, with area
(LUT4 / EBR) the budgeted quantity and energy out of scope. *This line
previously read "fit and correctness at ~40 MHz". That figure is retired — it
is J2's row, and the core this project builds is J4; the measured per-variant
baseline and the one real `[FPGA]` frequency goal are owned by
[platform-baseline.md §3](../platform-baseline.md), per
[decisions/0009](../decisions/0009-in-order-fgmt-is-the-default-path.md).
Nothing in this section was derived from the 40, which is why removing it
changes no number below.*

**What would produce the numbers:** `yosys` + `nextpnr-ecp5` targeting the
ULX3S 85F for the `[FPGA]` columns; a gf180 gate-level run (Track D0) for the
`[ASIC]` columns.

**Hard multiply blocks — structural, not synthesis.** GF(2) multiplication
cannot use a hard multiply block on any family: those blocks are built around
a carry chain for integer arithmetic, and this design has none. So every tier
uses **0** sysDSP slices on the ECP5 (Lattice's `MULT18X18D` and related
primitives) and would use 0 DSP48 slices on any family that has them. This
holds by construction from the algorithm and is the one resource figure in this
section that needs no measurement. Some FPGA vendors expose dedicated
carryless-multiply modes on their hard blocks; that is family-specific and
unconfirmed for the ECP5.

**Why no cross-family estimate is offered.** Two logically identical RTL trees
on this core, differing only in the operand order of one `or`, synthesized
**368 LUT4 apart** on the ECP5 — a same-family, same-node noise floor wider
than most of the deltas anyone would want to read out of an estimate. A number
carried across vendors, LUT widths or process nodes is worth less than that.

**`[ASIC]`, small nodes — qualitative only:** as the node shrinks, GF(2)
multiplier area becomes a small fraction of the SoC and power, not area,
dominates the tier choice; Tier A with operand isolation when idle is then the
expected pick. No figures are given at any node.

### 11.2 Timing analysis

Structural, and true on any target: Tier A's critical path is one AND gate
followed by a 6-level XOR tree, between operand and result registers. Tier B's
longest stage is stage 2, where each sub-multiplier is a 32-bit AND followed by
a 5-level XOR tree.

**Path delay and achievable Fmax, on both targets: unknown at this stage — needs measurement.**
Static timing analysis after a gf180 gate-level run `[ASIC]`, or after
`nextpnr-ecp5` place-and-route on the ULX3S 85F `[FPGA]`, produces them. The
400–500 MHz named for Tier B in §6.3 is the design target, not an achieved
frequency.

### 11.3 Power and operand isolation — `[ASIC]` only

Energy and power are `[ASIC]`-only for this project
([j4-remediation-plan.md](../j4-remediation-plan.md) guiding principle 1 and
Track D0): energy is not measurable on the ECP5 and is out of scope for
Phase-1.

To minimise dynamic power, AND-mask the multiplier inputs when no CLMUL is
being issued — 128 AND gates plus one OR-of-valid-signals at the operand
registers (structural: one gate per input bit). Further mitigations: clock
gating (gate the multiplier clock when no CLMUL is active in any pipeline
stage), and a power-down mode for the entire GF unit when SIMD is disabled.

GF(2) operations have high bit-toggle rates — every AND output is independent
of its neighbours — so the multiplier core is expected to be activity-dominated
rather than leakage-dominated during sustained CLMUL throughput. That is a
qualitative statement about the algorithm; the activity factor itself, the
power drawn with and without operand isolation, and the saving isolation buys
are all unknown at this stage — needs measurement.

**What would produce them:** a gf180 gate-level power run (Track D0) driven by
switching activity from a real trace, reported `[ASIC]` with the node it used.

---

## 12. Tier 2: Test, debug, bring-up

### 12.1 Scan chain coverage

Pipeline registers should be on the scan chain. The AND array and XOR tree are combinational and scan-tested by exercising the surrounding flip-flops with known patterns. Aim for >95% stuck-at fault coverage.

### 12.2 Built-in self-test (optional)

For ASIC variants in safety-critical applications, a 256-pattern BIST sequence covers all major fault classes in the multiplier. Run at boot; cost ~256 cycles of latency.

### 12.3 Performance counters

Expose at minimum:

- VCLMUL.D instruction count
- VCRC32C.B instruction count
- Pipeline stall cycles attributed to CLMUL (structural and RAW)

Enables software to validate the implementation is being used correctly. See [software-impl.md §10.2](software-impl.md) for the canonical `__jcore_read_cycles()` usage pattern.

### 12.4 Bring-up checklist

For new J-core variants adding Tier 2:

- [ ] RTL synthesis clean (no inferred latches, no synthesis warnings on the multiplier block)
- [ ] Static timing analysis passes at target clock
- [ ] Power estimation within budget
- [ ] Unit tests pass against Python golden model (10⁶ random vectors)
- [ ] AES-GCM NIST test vectors pass
- [ ] CRC-32C iSCSI test vectors pass (RFC 3720 vectors)
- [ ] RAID-6 4-disk syndrome test passes against Linux md output
- [ ] Linux boots with `crc32c-jcore` enabled (replaces `crc32c-generic` via `cra_priority`)
- [ ] `dm-crypt` AES-GCM volume mounts and benchmarks within 80% of theoretical CLMUL throughput
- [ ] `[FPGA]` bitstream meets timing on target board (ULX3S / ECP5, this project's Phase-1 target)
- [ ] Performance counters report sensible values during a kernel build
- [ ] Documentation updated: ISA reference, encoding map, programmer's guide, feature register bit

---

## 13. Open issues and future work

1. **Vertical-parallel CRC32C (multi-stream).** Specified as a Tier 2 open question ([spec.md §11](spec.md)). Spec impact small if encoding leaves room (it does: the SIMDV-prefix variant of VCRC32C.B encoding bits remain available since the architectural form is SIMDHA-only today).
2. **Vectorised Barrett-reduction primitive.** If NTT / post-quantum workloads (Kyber, Dilithium) become significant, consider a SIMD `modmul` instruction. Track adoption metrics before adding hardware.
3. **CRC-32-IEEE acceleration.** Currently software-only via CLMUL folding. If profile data shows it dominates, consider a `VCRC32.B` variant sharing the same datapath.
4. **GF(2^8) S-box / S-substitution acceleration.** Bitsliced AES suffices today; if Curve448 or similar workloads emerge, evaluate.
5. **Tier 1 partial implementations and feature-register bits.** Per [spec.md §10](spec.md), partial Tier 1 deployments are permitted but the feature-register encoding still needs to be specified (one bit per partial subset, or a single Tier 1 capability bit with an architectural manifest).
6. **Tier 3 (width beyond VLEN) hardware path.** No specification yet. Note VLEN is now 256 on J32 / 512 on J64 natively (spec.md §1.2), so Tier 3 no longer means "256-bit" — it means growth *beyond* the predicate-driven VLEN. The principal question is whether such a facility widens the existing datapath transparently (a wider ALU + register file with a widened/multi-register predicate) or introduces new AVX-style multi-VLEN opcodes.

---

## 14. References

Architectural prior art for all Tier 0/1/2 mechanisms is consolidated in [spec.md Appendix C](spec.md) (pre-2006 sources only, per the [../glossary.md §2](../glossary.md) project policy).

**Informative-only post-2006 sources** (not used as design inspiration; cited only for verification cross-checks):

- Linux kernel `lib/crc32c.c` — software fallback reference (golden model for VCRC32C.B kernel-level verification).
- Linux kernel `lib/raid6/` — multi-architecture RAID-6 driver (golden model for kernel 3 in §10.4).
- IEEE Std 802.3 — Ethernet FCS specification (CRC-32-IEEE reference behaviour).
- OpenSPARC T2 CMU (Crypto / Modular Math Unit) Verilog source (Sun/Oracle, GPL, 2007). **Post-2006; not used as design source.** Mentioned only as one of several historical examples of CRC + modular-math hardware; the Tier 2 design rests on Mastrovito (1991), Karatsuba (1962), and the carry-gated integer-multiplier reuse strategy described in §7.
- RISC-V Zkn / Zks specification — implementation patterns informative.
- Gueron (2014) Intel CLMUL white paper and Gueron-Kounavis (2009) GCM paper — *implementation references* for the well-known GHASH reduction constants only; both post-2006 and not used as architectural prior art.
