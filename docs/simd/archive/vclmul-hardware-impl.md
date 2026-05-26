> **Superseded.** This document was consolidated into `../spec.md` / `../hardware-impl.md` / `../software-impl.md` on 2026-05-25. Kept for historical reference.

# VCLMUL and VCRC32C: Hardware Implementation Guide

**Document status:** Draft v0.1
**Audience:** jcore HDL (VHDL/Verilog) developers, microarchitecture
**Companion to:** 01-design-spec.md (architectural specification)

---

## 1. Scope

This document covers the hardware implementation of VCLMUL.D and VCRC32C.B in the jcore SIMD execution unit. It assumes familiarity with the existing jcore pipeline structure (J2 5-stage baseline, J32/J64 variants) and the SIMD prefix decoder.

Topics covered:
- GF(2) multiplier datapath (three implementation tiers)
- Reuse strategy for the existing widening integer multiplier
- Pipeline integration, forwarding, and hazard handling
- Predicate routing
- Verification approach
- Synthesis area estimates for 130nm, 40nm, and FPGA targets
- Bring-up checklist

---

## 2. Datapath design

### 2.1 The core operation: 64×64 → 128 GF(2) multiply

A 64-bit GF(2) polynomial multiply produces a 128-bit result. Logically it is a 64×64 AND array (4096 AND gates) followed by an XOR reduction tree of depth log2(64) = 6 levels (approximately 4030 two-input XOR gates).

For comparison, a 64×64 → 128 integer multiplier of equivalent throughput requires the same AND array plus a carry-save adder tree plus a final carry-propagate adder — roughly 30-40% more gates. **The GF(2) multiplier is structurally a subset of the integer multiplier with the carry chain removed.**

This subset relationship is the key reuse opportunity.

### 2.2 Implementation Tier A: Single-cycle combinational

Full 64×64 AND array + Wallace-tree XOR reduction in one cycle.

```
                                              ┌────────────┐
   vd[63:0] ─────────┐                       │ Wallace    │
                     ▼                       │ XOR tree   │
                    ┌────┐                   │ 6 levels   │
                    │AND │ ──→ 64 partial ──→│            │── result[127:0]
                    │64×64│    products       │            │
                    └────┘                   │            │
                     ▲                       │            │
   vs[63:0] ─────────┘                       └────────────┘
```

**Resource estimate:**
- AND gates: 4096
- XOR gates: ~4030
- Total: ~25k equivalent gates at 130nm
- Latency: 1 cycle
- Throughput: 1 CLMUL per cycle
- Critical path: AND + 6 XORs ≈ 0.8 ns at 130nm (1.25 GHz theoretical, ~250-400 MHz practical with margin)

**When to use:** J64 performance tier, ASIC targets with generous area budget, FPGA on Kintex/Virtex class parts.

### 2.3 Implementation Tier B: Pipelined Karatsuba (recommended baseline)

Decompose 64×64 into three 32×32 GF(2) multiplies:

```
Given: a = a_hi · x^32 + a_lo
       b = b_hi · x^32 + b_lo

       a · b = a_hi · b_hi · x^64
             + (a_hi · b_lo + a_lo · b_hi) · x^32
             + a_lo · b_lo

Karatsuba: P0 = a_lo · b_lo                     (32×32 → 64 CLMUL)
           P1 = a_hi · b_hi                     (32×32 → 64 CLMUL)
           P2 = (a_lo ⊕ a_hi)(b_lo ⊕ b_hi)      (32×32 → 64 CLMUL)
           middle = P2 ⊕ P0 ⊕ P1

           result = P1 · x^64 ⊕ middle · x^32 ⊕ P0
```

Three CLMUL32 sub-operations plus combining XORs. Each CLMUL32 is a 32-AND array + 5-level XOR tree (~1000 ANDs + ~1000 XORs).

```
   ┌──────────────────────────────────────────────────────────┐
   │   Stage 1: Operand split + XOR for P2                    │
   │   a_hi, a_lo ← split(vd)                                 │
   │   b_hi, b_lo ← split(vs)                                 │
   │   a_xor ← a_hi XOR a_lo                                  │
   │   b_xor ← b_hi XOR b_lo                                  │
   └──────────────────────────────────────────────────────────┘
                              │
                              ▼
   ┌──────────────────────────────────────────────────────────┐
   │   Stage 2: Three parallel 32×32 GF(2) multiplies         │
   │     P0 = clmul32(a_lo, b_lo)                             │
   │     P1 = clmul32(a_hi, b_hi)                             │
   │     P2 = clmul32(a_xor, b_xor)                           │
   └──────────────────────────────────────────────────────────┘
                              │
                              ▼
   ┌──────────────────────────────────────────────────────────┐
   │   Stage 3: Combine                                       │
   │     middle = P2 XOR P0 XOR P1                            │
   │     result = (P1 << 64) XOR (middle << 32) XOR P0        │
   └──────────────────────────────────────────────────────────┘
```

**Resource estimate:**
- 3× 32×32 GF(2) multipliers: ~12k gates
- Combining logic: ~500 gates
- Pipeline registers: ~600 flops
- Total: ~16k equivalent gates at 130nm
- Latency: 3 cycles
- Throughput: 1 CLMUL per cycle (fully pipelined)
- Critical path per stage: ~0.5 ns at 130nm (target 400-500 MHz)

**When to use:** J32 and J64 baseline. This is the recommended default implementation. ~35-40% area savings versus Tier A at the cost of 3-cycle latency.

### 2.4 Implementation Tier C: Iterative shift-XOR

Reuses the existing integer widening multiplier's shift register and partial-product accumulator. The integer multiplier already has a 64-bit shift-and-add iteration loop; gating the carry chain (forcing it to XOR-only) makes the same hardware perform GF(2) multiplication.

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
   │   │  gf2_mode signal: when '1', the       │         │
   │   │  accumulator uses XOR instead of ADD  │         │
   │   │  and the carry chain is masked off    │         │
   │   └───────────────────────────────────────┘         │
   └─────────────────────────────────────────────────────┘
```

**Resource estimate:**
- Additional logic on top of widening multiplier: ~200 gates (XOR-vs-ADD mux on accumulator, carry-chain mask, mode-bit decode)
- No new flops
- Latency: 64 cycles per CLMUL (one cycle per bit of operand B)
- Throughput: 1 CLMUL per 64 cycles
- Critical path: same as existing multiplier (no impact)

**When to use:** Ultra-low-area J32 deployments where VCLMUL is needed for software correctness but not performance-critical. Embedded SoC variants targeting < 100k gates total.

### 2.5 Tier selection by target

| Target | Recommended tier | Rationale |
|---|---|---|
| J32 minimal (FPGA Spartan-6 class) | Tier C | Reuse existing multiplier, minimal new logic |
| J32 standard (J2-equivalent class) | Tier B | Best area/performance balance |
| J32 performance (Artix-7 / Kintex) | Tier B | 3-cycle latency hidden by software interleaving |
| J64 baseline | Tier B | Standard target |
| J64 performance / server class | Tier A | Single-cycle for higher clock rates |
| ASIC 28nm or smaller | Tier A | Area penalty negligible at smaller nodes |

---

## 3. Widening multiplier reuse strategy

### 3.1 The `gf2_mode` signal

Add a single control bit to the existing widening multiplier interface. When asserted:

1. The partial-product accumulator uses XOR instead of carry-save add.
2. The carry-propagate adder at the multiplier output is bypassed (its carry inputs forced to zero).
3. Sign-extension logic in the operand-prep path is disabled (GF(2) operands are unsigned polynomials).

For Tier C this is the entire implementation. For Tier B, the three 32×32 sub-multipliers each have their own gf2_mode bit.

### 3.2 RTL skeleton

```vhdl
-- VHDL fragment, illustrative
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
    -- Stage registers, sub-multiplier instances, combining logic
    -- gf2_mode propagates through pipeline stages alongside operands
begin
    -- ...
end architecture;
```

The gf2_mode signal threads through the pipeline registers identical to the operand data, ensuring the correct mode is honored even with back-to-back integer/GF(2) instruction mixing.

### 3.3 Sub-multiplier sharing for Tier B

The three 32×32 sub-multipliers in Karatsuba can be:

- **Three physical multipliers** (full throughput, larger area)
- **One physical multiplier time-shared over three cycles** (one-third throughput, one-third area)

J32 baseline should ship with one shared sub-multiplier. J64 baseline should ship with three. This decision can be revisited based on synthesis results without changing the architecture.

---

## 4. VCRC32C.B datapath

### 4.1 Implementation choice: CLMUL-based fused decode

The recommended implementation **does not add new GF arithmetic silicon for VCRC32C.B**. Instead, it adds a decode-stage fusion that expands one VCRC32C.B instruction into a short sequence of CLMUL operations against precomputed Castagnoli fold constants.

```
VCRC32C.B vd, vs (under horizontal prefix, 8-bit width)
                    │
                    ▼
       Decoder expands to micro-op sequence:
                    │
                    ▼
   1. CLMUL(vd[31:0] (zero-extended), CONST_K1)  → temp_lo
   2. CLMUL(vd[31:0] (shifted), CONST_K2)        → temp_hi
   3. XOR(temp_lo, temp_hi, vs (masked))         → folded
   4. Barrett reduction:
         CLMUL(folded_hi, BARRETT_U) → q
         CLMUL(q, POLY_P)            → q_times_p
         XOR(folded, q_times_p)      → vd[31:0]
```

Fold constants K1, K2, the Barrett constant U, and the polynomial P live in a small ROM (16 bytes per polynomial; CRC-32C is the only polynomial supported, so 16 bytes total).

### 4.2 LFSR-based alternative

For implementations not implementing VCLMUL.D (which would be unusual but possible), VCRC32C.B can be implemented as a traditional byte-at-a-time LFSR:

```
For each byte (predicated by mask):
    index = (crc ⊕ byte) & 0xFF
    crc   = (crc >> 8) ⊕ TABLE_C[index]
```

A 256-entry × 32-bit ROM (8 kbits) provides TABLE_C lookups. Critical path is one ROM read + one XOR per byte. With 16 bytes per instruction, this requires either:
- 16 parallel ROM ports (impractical), or
- 16 sequential lookups (slow, 16+ cycles per instruction), or
- Multi-banked ROM with 2-4 ports (moderate area, 4-8 cycles per instruction)

The CLMUL-fused approach is strongly preferred because it amortizes existing silicon. The LFSR path is documented here only as a fallback for "VCLMUL absent" variants.

### 4.3 Predicate routing

The prefix-designated mask register is read concurrently with `vs`. Each of the 16 byte-mask bits AND-gates the corresponding byte position in `vs` before it enters the CLMUL fold. Masked-off bytes contribute zero to the polynomial, leaving the accumulator unchanged for those positions.

```
   vs   ─────┐                ┌────┐
             ├─→ byte_gate ──→│CLMUL│─→ folded
   mask ─────┘                │fold │
                              └────┘
```

Implementation: 16 × 8 = 128 AND gates at the SIMD ALU input. Negligible silicon.

---

## 5. Pipeline integration

### 5.1 Stage placement

VCLMUL.D and VCRC32C.B execute in the EX (execute) stage of the SIMD pipeline. For Tier B (3-cycle pipelined), they occupy EX1, EX2, EX3.

```
   Stage:    IF    ID    RR    EX1   EX2   EX3   WB
   VCLMUL: ───────────────[clmul────────────]─→──→
   Others:  ──────────────[other ALU]──────────→─→
```

Tier A (single-cycle) collapses EX1-EX3 into one stage for VCLMUL. The pipeline timing is set by the longest path; if Tier A clmul is the longest path, it sets the clock period for the whole SIMD pipe.

### 5.2 Forwarding paths

**Result forwarding from VCLMUL to subsequent SIMD ALU ops:** Standard EX→ID bypass. With Tier B 3-cycle latency, the result becomes available at EX3; a subsequent instruction in ID three cycles later picks it up directly.

**Tight CLMUL chains (AES-GCM GHASH):** A common pattern is `clmul; xor; clmul; xor` where each clmul reads the result of the previous. With Tier B and N=8 from the prefix, the pipeline issues a CLMUL each cycle but each CLMUL's result is needed 3 cycles later — naturally interleaved without stall.

**CRC accumulator chain (VCRC32C.B loop):** Each VCRC32C.B reads `vd[31:0]` written by the previous instance. The fused micro-op sequence's final XOR result must be forwarded to the next instance's first CLMUL input. This is a 3-cycle dependency in Tier B → either stall, or unroll the software loop to interleave independent CRC streams. Recommend documenting the stall behavior; software can choose to unroll if performance demands it.

### 5.3 Hazard handling

| Hazard | Mitigation |
|---|---|
| Structural: two CLMULs in same cycle, one multiplier | Issue serially; second stalls one cycle |
| RAW on VCLMUL result | Forwarded at EX3→EX1 of next instruction |
| RAW on VCRC32C accumulator | Pipeline stall (3 cycles in Tier B); document this |
| Interrupt mid-CLMUL | Complete the instruction; precise exception model preserved |
| Interrupt mid-VCRC32C fused sequence | Complete or restart at instruction boundary (implementation choice; architecture treats VCRC32C.B as atomic) |

### 5.4 Multi-issue (J64 dual-issue variants)

If J64 ships dual-issue: a CLMUL can co-issue with any non-multiplier SIMD op (XOR, AND, swizzle, predicate manipulation). Two CLMULs cannot co-issue with a single physical multiplier; add a second multiplier or accept serialization.

---

## 6. Verification

### 6.1 Verification levels

Three layers, in increasing scope:

1. **Unit verification of the GF(2) multiplier block.**
2. **Instruction-level verification against the architectural specification.**
3. **Workload-level verification on real cryptographic and RAID kernels.**

### 6.2 Unit verification

For the GF(2) multiplier block in isolation:

```python
# Python golden model
def gf2_mul(a, b):
    """64x64 -> 128 carryless multiply."""
    result = 0
    for i in range(64):
        if (b >> i) & 1:
            result ^= a << i
    return result & ((1 << 128) - 1)
```

Test inputs:
- All-zero operands (sanity)
- All-ones operands (full coverage of partial products)
- Single-bit operands (`1 << i` for each i)
- Random with biased distributions (1%, 50%, 99% bit density)
- Known products: e.g., `0xFFFFFFFFFFFFFFFF ⊗ 0xFFFFFFFFFFFFFFFF` is well-known
- 10^6 random pairs

Test methodology:
- Apply via VHDL/Verilog testbench
- Compare with Python golden model bit-for-bit
- Coverage: 100% AND-array activity, 100% XOR-tree paths

### 6.3 Instruction-level verification

Stimuli driven from a SIMD assembly test suite:

```asm
test_vclmul_basic:
    ; vd = 0x00000000_00000000_00000000_00000003
    ; vs = 0x00000000_00000000_00000000_00000005
    ; expected: vd = vd ⊗ vs = 0x0F (binary 0011 ⊗ 0101 = 1111)
    ldi.v   vd, =const_3
    ldi.v   vs, =const_5
    vprefix.v.d  N=1
    vclmul.d     vd, vs
    cmp.v   vd, =expected_0F
    bf      fail
```

Verify all four exception conditions:
- VCLMUL.D under horizontal prefix → trap
- VCLMUL.D under 32-bit width prefix → trap
- VCLMUL.D with no prefix → trap
- VCRC32C.B under vertical prefix → trap

### 6.4 Workload verification

Three target kernels, each exercising different access patterns:

**Kernel 1: AES-GCM streaming (NIST test vectors)**
```
Input: NIST GCM test vector (key, IV, AAD, plaintext)
Expected: ciphertext + tag matching NIST output
Stress: large messages (1 MB), back-to-back GHASH operations
```

**Kernel 2: CRC-32C buffer (RFC 3720 / iSCSI test vectors)**
```
Input: known buffers of varying length (0, 1, 15, 16, 17, 1024, 65535 bytes)
Expected: known CRC values
Stress: pathological tail lengths (15, 31, 47 bytes); fully masked instructions
```

**Kernel 3: RAID-6 syndrome (mdadm test pattern)**
```
Input: 4-disk RAID-6 with known data
Expected: P and Q syndromes matching Linux md driver output
Stress: 64KB stripes, all-zero stripes, all-ones stripes
```

### 6.5 Co-simulation strategy

Recommended flow:

1. **Verilator + golden model.** Run jcore RTL under Verilator. At every SIMD instruction retirement, compare register state against the Python golden model. Bit-exact match required.

2. **Linux on jcore (Buildroot).** Boot a minimal Linux with the kernel's crc32c-pclmul-equivalent path enabled and run `crypto/testmgr.c` self-tests. Pass = architectural correctness.

3. **iperf with iSCSI / NFS-over-RDMA traffic.** Real-network workload verification, measuring CRC throughput improvement.

### 6.6 Coverage targets

- Combinational coverage: 100% of AND-array entries exercised
- XOR-tree coverage: 100% of internal nodes toggled
- Predicate mask coverage: all-zero, all-one, alternating, sparse, dense
- Prefix mode coverage: all legal modes, all illegal modes (traps caught)

---

## 7. Synthesis targets

### 7.1 130nm (J2 reference flow)

| Tier | Estimated gates | Estimated area | Estimated max freq |
|---|---|---|---|
| Tier A (combinational) | 25,000 | 0.20 mm² | 300 MHz |
| Tier B (Karatsuba pipelined) | 16,000 | 0.13 mm² | 500 MHz |
| Tier C (iterative) | 200 (additional) | 0.002 mm² (additional) | No impact on freq |

Reference J2 core size: ~30,000 gates / 0.25 mm² at 130nm. Tier B roughly doubles the SIMD execution unit area; the total core grows by perhaps 40-50%.

### 7.2 28nm/40nm modern ASIC

At smaller nodes, GF(2) multiplier area becomes a small fraction of the SoC and Tier A is usually justified for performance reasons. Power, not area, dominates the design choice — Tier A with operand isolation when idle is typically the right call.

### 7.3 FPGA targets

**Spartan-7 / Artix-7 (low-cost FPGA):**

| Tier | LUTs | FFs | DSP48 slices |
|---|---|---|---|
| Tier A | 3,500 | 100 | 0 (LUT-only) |
| Tier B | 2,200 | 600 | 0 |
| Tier C | 50 (additional) | 10 (additional) | 0 |

DSP48 blocks are not directly usable for GF(2) multiplication (they have carry chains designed for integer arithmetic). Some FPGA vendors expose carryless-multiply modes; this is family-specific.

**Kintex-7 / Virtex Ultrascale:**

Tier A becomes the obvious choice; LUT cost is negligible relative to total fabric.

### 7.4 Operand isolation

To minimize dynamic power, AND-mask the multiplier inputs when no CLMUL is being issued. This adds 128 AND gates and one OR-of-valid-signals — negligible silicon, 30-50% dynamic power savings on cores where CLMUL is not in the critical path.

---

## 8. Timing analysis

### 8.1 Critical paths

**Tier A critical path:**
```
operand register → AND gate → XOR tree (6 levels) → result register
≈ 0.05 ns + 0.10 ns + 6 × 0.10 ns + 0.05 ns = 0.80 ns @ 130nm
```

This sets a theoretical maximum of 1.25 GHz; with margin, target 250-400 MHz at 130nm.

**Tier B critical path (per stage):**
```
Stage 2 (the three sub-multipliers): each is 32-bit AND + 5-level XOR tree
≈ 0.05 + 0.10 + 5 × 0.10 + 0.05 = 0.70 ns @ 130nm
```

Limits stage frequency similarly; choose 400-500 MHz target.

### 8.2 Setup/hold

Standard SIMD pipeline conventions apply. No special considerations beyond those required by the existing widening multiplier.

### 8.3 Clock gating

Gate the multiplier clock when no CLMUL is active in any pipeline stage. Three-cycle pipeline means the gate signal must look ahead three cycles in the issue queue — straightforward for a small jcore with deterministic issue.

---

## 9. Power

### 9.1 Activity factor

GF(2) operations tend to have high bit-toggle rates (every AND output is independent of its neighbors). Expect 30-40% activity in the multiplier core during sustained CLMUL throughput.

### 9.2 Mitigations

- Operand isolation (Section 7.4)
- Clock gating (Section 8.3)
- Wide AND-tree at the multiplier input gated by valid signal
- Power-down mode for the entire GF unit when the SIMD subsystem is disabled

### 9.3 Expected power impact

Tier B multiplier under sustained 100% CLMUL throughput at 500 MHz, 130nm: estimated 15-25 mW. With operand isolation and clock gating during typical mixed workloads (10-20% CLMUL): 3-5 mW average. Negligible relative to the core's total power budget.

---

## 10. Test and debug

### 10.1 Scan chain coverage

Pipeline registers should be on the scan chain. The AND array and XOR tree are combinational and scan-tested by exercising the surrounding flip-flops with known patterns. Aim for >95% stuck-at fault coverage.

### 10.2 Built-in self-test (optional)

For ASIC variants in safety-critical applications, a 256-pattern BIST sequence covers all major fault classes in the multiplier. Run at boot; cost is ~256 cycles of latency.

### 10.3 Performance counters

Expose at minimum:
- VCLMUL.D instruction count
- VCRC32C.B instruction count
- Pipeline stall cycles due to CLMUL (structural and RAW)

These enable software to validate the implementation is being used correctly.

---

## 11. Bring-up checklist

For new jcore variants adding this extension:

- [ ] RTL synthesis clean (no inferred latches, no synthesis warnings on the multiplier block)
- [ ] Static timing analysis passes at target clock
- [ ] Power estimation within budget
- [ ] Unit tests pass against Python golden model (10^6 random vectors)
- [ ] AES-GCM NIST test vectors pass
- [ ] CRC-32C iSCSI test vectors pass (RFC 3720 vectors)
- [ ] RAID-6 4-disk syndrome test passes against Linux md output
- [ ] Linux boots with `crypto/crc32c_pclmul` equivalent enabled
- [ ] `dm-crypt` AES-GCM volume mounts and benchmarks within 80% of theoretical CLMUL throughput
- [ ] FPGA bitstream meets timing on target board (Artix-7 or chosen reference)
- [ ] Performance counters report sensible values during a kernel build
- [ ] Documentation updated: ISA reference, instruction encoding map, programmer's guide

---

## 12. Open issues and future work

1. **Vertical-parallel CRC32C** (multi-stream): defer to future extension. Spec impact small if encoding leaves room.
2. **Vectorized Barrett reduction primitive**: if NTT/PQ workloads become significant, consider a SIMD modmul instruction. Track Kyber/Dilithium adoption metrics.
3. **CRC32-IEEE acceleration**: currently software-only via CLMUL folding. If profile data shows it dominates, consider a CRC32-IEEE.B variant sharing the same datapath.
4. **GF(2^8) S-box S-substitution acceleration**: bitsliced AES suffices today, but if Curve448 or other workloads emerge, evaluate.

---

## 13. References

- jcore project documentation (j-core.org, github.com/j-core)
- OpenSPARC T2 CMU (Crypto / Modular Math Unit) Verilog source — Sun/Oracle, GPL, 2007
- RISC-V Zkn / Zks specification — implementation patterns informative
- Gueron, S. "Intel Carry-Less Multiplication Instruction and its Usage for Computing the GCM Mode" — Intel white paper, 2014
- Kounavis, M.E. and Berry, F.L. "A Systematic Approach to Building High Performance Software-based CRC Generators" — Intel, 2008
- IEEE Std 802.3 (Ethernet FCS specification, for reference CRC-32-IEEE behavior)
