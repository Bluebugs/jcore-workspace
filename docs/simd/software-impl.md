# J-Core SIMD — Software Implementation Guide

**Status:** Consolidated draft (replaces the Tier 0/1 software-facing material in spec-v0.5/v0.6 and the vclmul-software-impl document on 2026-05-25).
**Audience:** OS kernel developers, library maintainers, compiler toolchain engineers, application developers.
**Companion documents:** [spec.md](spec.md) (architecture, single source of truth), [hardware-impl.md](hardware-impl.md) (datapath, pipeline, synthesis).

This guide describes how to use J-Core SIMD from software. Architectural definitions and encodings live in [spec.md](spec.md); this document covers the assembler / intrinsic / kernel / library layer. Tier numbering matches [spec.md §1.1](spec.md).

---

## 1. Scope and organisation

- **Tier 0 / Tier 1 (§2–§5):** assembler syntax, the canonical `SIMDV.w` mnemonic family, C and Rust intrinsic naming conventions, integer / saturation / FP kernels.
- **Tier 2 (§6–§13):** detailed VCLMUL.D / VCRC32C.B intrinsic bindings, reference kernels (CRC-32C, AES-GCM GHASH, RAID-6, HQC, Reed-Solomon), toolchain integration (binutils / GCC / LLVM), Linux kernel integration, userspace library integration, performance characterisation, fallback paths, end-to-end example, migration roadmap.

---

## 2. Tier 0/1: Programmer's model

### 2.1 Quick reference

| Concept | Where |
|---|---|
| V0..V15 dedicated 128-bit register file | [spec.md §2.1](spec.md) |
| P0 16-bit predicate mask | [spec.md §2.5, §5.1](spec.md) |
| VCSR.MKE (mask enable), VCSR.IEE (IEEE-strict FP) | [spec.md §2.4](spec.md) |
| SIMDV / SIMDH prefix and the four lane widths (B/W/L/Q = 8/16/32/64) | [spec.md §3.2](spec.md) |
| Eight reduction operators (add, OR, AND, XOR, min, max, min-u, max-u) | [spec.md §3.2 table](spec.md) |
| Tier 1 saturation modifiers (SIMDVS, SIMDVU) | [spec.md §3.2.1, §5.4](spec.md) |
| N=1 memory-access rule and restart-from-prefix | [spec.md §5.6.1, §6.4](spec.md) |
| VLNS+VEXT/VINS lane-bridge pair (assembler hides this as `VEXT.L Vn.lane, Rn`) | [spec.md §5.7](spec.md) |
| Trap-free SIMD FP exception model | [spec.md §6.3](spec.md) |

### 2.2 Calling convention impact

V0..V15 are caller-saved by default (matching the SH-4 FR0..FR15 convention). OS context-switch code adds 256 bytes per thread for V0..V15 plus 4 bytes for P0 and 4 bytes for VCSR. The Tier 0-aware kernel must save these immediately after FPSCR in the saved-context layout. Existing scalar SH-2 / SH-4 conventions for R0..R15 / FR0..FR15 / FPSCR are unchanged.

CRC accumulators and other long-lived SIMD state in flight across function calls follow whatever convention applies to the V register holding them.

### 2.3 Mode prerequisites

Software is responsible for issuing the correct prefix before each governed instruction. The exception model is strict: wrong prefix mode raises slot-illegal. There is no "best-effort" fallback in hardware. The detailed slot-illegal trigger matrix is in [spec.md §6.2](spec.md).

---

## 3. Assembly mnemonics and syntax normalization

### 3.1 The chosen syntax family

This project standardises on the **`SIMDV.w` / `SIMDH<op>.w` mnemonic family** for prefixes and the **`Vn`** register-name convention for the 128-bit V file. The alternative `vprefix.v.d` / `vclmul.d` skin that appeared in the original VCLMUL design draft is **not used**; all examples in this document and in [spec.md](spec.md) use the chosen family. See [spec.md §3.1](spec.md) for the decision and rationale.

Practical consequences:

- One prefix mnemonic family across Tier 0, Tier 1, and Tier 2. Tier 2's `VCLMUL.D Vm, Vn` is gated by `SIMDV.Q #N`; `VCRC32C.B Vm, Vn` is gated by `SIMDHA.B #N`. The decoder uses the same width-lock mechanism Tier 1 already uses for VPACK / VPACKW.
- Assemblers and disassemblers maintain a single parser table.
- Programmer's-reference manuals describe one set of mnemonics and one width-suffix convention.

### 3.2 GAS (GNU assembler) syntax

```asm
    ; Tier 0 vertical FP32 FMA
    SIMDV.L  #1
    FMAC     FR1, FR2

    ; Tier 0 horizontal FP32 → FP64 reduction
    SIMDH.L  #1
    FMUL     FR4, FR0

    ; Tier 1 signed-saturating INT16 add
    SIMDVS.W #1
    ADD      V2, V1

    ; Tier 1 horizontal SAD (sum of absolute differences)
    SIMDH.B  #1
    VABSDIFF V2, V1

    ; Tier 2 carryless multiply, 64-bit lanes
    SIMDV.Q  #1
    VCLMUL.D V2, V1                ; V1[127:0] ← V1[63:0] ⊗ V2[63:0]

    ; Tier 2 CRC-32C fold, 8-bit lanes, full mask
    MOV      #0xFFFF, R0
    LDS      R0, P0
    VMKCHG                         ; VCSR.MKE ← 1
    SIMDH.B  #1
    VCRC32C.B V_data, V_crc        ; V_crc[31:0] ← fold(V_crc[31:0], V_data, P0)
    VMKCHG                         ; restore
```

### 3.3 Mnemonic conventions

- `.B` / `.W` / `.L` / `.Q` width suffixes: 8 / 16 / 32 / 64 bits.
- `Vn` for n = 0..15 names a 128-bit SIMD register.
- Governed instructions inside a SIMD block use ordinary SH-2/SH-4 mnemonics with `FRn` or `Rn` operands; the assembler reinterprets the operand field as a V-register index in SIMD context.
- `Vn.lane` in extract/insert syntax (e.g., `VEXTF.L V5.2, FR3`) is a single-mnemonic shorthand that the assembler expands to the two-instruction `VLNS + VEXT/VINS` sequence ([spec.md §5.7](spec.md)).
- Lower-case mnemonics (`simdv.b`, `vclmul.d`) are also accepted by the assembler.

### 3.4 High-level intrinsic naming (Tier 0/1)

C intrinsics follow `__jcore_<op>_<typetag>` (lane width and signedness):

```c
#include <jcore/simd.h>

/* 128-bit SIMD register, union view */
typedef union {
    uint8_t   u8 [16];  int8_t   i8 [16];
    uint16_t  u16[8];   int16_t  i16[8];
    uint32_t  u32[4];   int32_t  i32[4];
    uint64_t  u64[2];   int64_t  i64[2];
    float     f32[4];   double   f64[2];
} jcore_v128_t;

typedef uint16_t jcore_mask16_t;   /* one bit per byte lane */

/* Tier 0 — vertical compute (lane-parallel) */
jcore_v128_t __jcore_vadd_i8 (jcore_v128_t a, jcore_v128_t b);
jcore_v128_t __jcore_vadd_i16(jcore_v128_t a, jcore_v128_t b);
jcore_v128_t __jcore_vsub_i32(jcore_v128_t a, jcore_v128_t b);
jcore_v128_t __jcore_vand    (jcore_v128_t a, jcore_v128_t b);
jcore_v128_t __jcore_vxor    (jcore_v128_t a, jcore_v128_t b);
jcore_v128_t __jcore_vfmul_f32(jcore_v128_t a, jcore_v128_t b);
/* ... etc. ... */

/* Tier 0 — horizontal reduction */
int32_t      __jcore_vhadd_i16(jcore_v128_t a);                  /* SIMDHA.W + ADD/MULS */
double       __jcore_vhfmul_f32(jcore_v128_t a, jcore_v128_t b); /* dot product, → DR0 */
int32_t      __jcore_vhmin_i16(jcore_v128_t a);                  /* SIMDHMN */

/* Tier 0 — vector memory and lane bridges */
jcore_v128_t __jcore_vld_q (const void *p);                      /* VLD.Q */
void         __jcore_vst_q (void *p, jcore_v128_t v);
jcore_v128_t __jcore_vgather_q_i32(const void *base, jcore_v128_t indices);
int32_t      __jcore_vext_l(jcore_v128_t v, unsigned lane);      /* VLNS+VEXT.L */
jcore_v128_t __jcore_vins_l(jcore_v128_t v, unsigned lane, int32_t val);

/* Tier 1 — saturating arithmetic and integer SIMD primitives */
jcore_v128_t __jcore_vadd_sat_i8 (jcore_v128_t a, jcore_v128_t b); /* SIMDVS.B + ADD */
jcore_v128_t __jcore_vadd_sat_u8 (jcore_v128_t a, jcore_v128_t b); /* SIMDVU.B + ADD */
jcore_v128_t __jcore_vabs_i16    (jcore_v128_t a);                 /* VABS */
jcore_v128_t __jcore_vpopcnt_u8  (jcore_v128_t a);                 /* VPOPCNT */
jcore_v128_t __jcore_vunpk4lu    (jcore_v128_t a);                 /* VUNPK4LU */
jcore_v128_t __jcore_vunpk4hs    (jcore_v128_t a);                 /* VUNPK4HS */
jcore_v128_t __jcore_vabsdiff_u8 (jcore_v128_t a, jcore_v128_t b); /* VABSDIFF */
jcore_v128_t __jcore_vpack_ss    (jcore_v128_t hi, jcore_v128_t lo);/* VPACK.SS */
int32_t      __jcore_vdot_su_i8  (jcore_v128_t s, jcore_v128_t u); /* SIMDH.B+VMULSU */
```

The corresponding GCC / Clang builtins follow `__builtin_jcore_<op>_<typetag>`; both names are exposed by `<jcore/simd.h>` when the compiler is invoked with `-mjcore-simd` (Tier 0), `-mjcore-simd-int` (Tier 1, implies Tier 0), or `-mjcore-simd-gf2` (Tier 2, implies Tier 0; does not imply Tier 1).

### 3.5 Predication intrinsics

```c
/* Build a predicate mask from a lane-wise comparison */
jcore_mask16_t __jcore_vcmpgt_i16(jcore_v128_t a, jcore_v128_t b);

/* Apply the mask: subsequent SIMD ops see VCSR.MKE = 1 until __jcore_vmkchg() */
void __jcore_vmkchg(void);

/* Explicit P0 access for save/restore */
jcore_mask16_t __jcore_get_p0(void);
void           __jcore_set_p0(jcore_mask16_t m);

/* Full VCSR access */
uint32_t __jcore_get_vcsr(void);
void     __jcore_set_vcsr(uint32_t v);
```

---

## 4. Compiler integration

### 4.1 GCC backend

Three integration points for the J-core SH backend:

1. **Builtin definitions** in `gcc/config/sh/sh-builtins.def` (or J-core-specific equivalent), mapping `__builtin_jcore_*` to the appropriate RTL patterns.
2. **RTL patterns** in `gcc/config/sh/sh.md` for the Tier 0 vertical/horizontal SIMD operations (parameterised over lane width), Tier 1 saturating / SAD / popcount / pack / VMULSU patterns, and Tier 2 `vclmul_d_v128` / `vcrc32c_b_v128`.
3. **Target option flags:** `-mjcore-simd` (Tier 0), `-mjcore-simd-int` (Tier 1), `-mjcore-simd-gf2` (Tier 2). `-mjcore-simd-all` is a convenience alias.

Auto-vectorisation may generate Tier 0/1 instructions from loop patterns when the data types match (FP32 lanes, INT8 / INT16 lanes for video / DSP-style loops); Tier 2 is explicitly invoked via intrinsics or inline assembly.

### 4.2 LLVM backend

Same shape: intrinsics defined in `llvm/include/llvm/IR/IntrinsicsJCore.td`, lowered via TableGen patterns in the J-core backend. Clang exposes the intrinsics via `<jcore/simd.h>`. The j2-llvm sibling repository ([../glossary.md §8](../glossary.md)) is the canonical implementation target.

### 4.3 Feature detection at compile time

```c
#if defined(__JCORE_SIMD__)
    /* Tier 0 (V0..V15, SIMDV/SIMDH, etc.) */
#endif
#if defined(__JCORE_SIMD_INT__)
    /* Tier 1 (saturation, VABS, VPOPCNT, VMULSU, ...) */
#endif
#if defined(__JCORE_SIMD_GF2__)
    /* Tier 2 (VCLMUL.D, VCRC32C.B) */
#endif
```

### 4.4 Feature detection at runtime

Linux exposes CPU features via `/proc/cpuinfo` and the auxiliary vector (`AT_HWCAP`). Allocate one HWCAP bit per SIMD tier in the J-core Linux port, plus one microarchitectural-capability bit for the relaxed-memory feature (TBD; tracked in [spec.md §11](spec.md) and §8.5 below):

```c
#include <sys/auxv.h>

bool has_jcore_simd(void) {
    return (getauxval(AT_HWCAP) & HWCAP_JCORE_SIMD) != 0;
}
bool has_jcore_simd_int(void) {       /* Tier 1 */
    return (getauxval(AT_HWCAP) & HWCAP_JCORE_SIMD_INT) != 0;
}
bool has_jcore_simd_gf2(void) {       /* Tier 2 */
    return (getauxval(AT_HWCAP) & HWCAP_JCORE_SIMD_GF2) != 0;
}
bool has_jcore_simd_relaxed_mem(void) {   /* N>1 memory blocks; orthogonal to tier */
    return (getauxval(AT_HWCAP) & HWCAP_JCORE_SIMD_RELAXED_MEM) != 0;
}
```

---

## 5. Rust bindings

```toml
# Cargo.toml
[dependencies]
jcore-simd = "0.1"
```

```rust
use core::simd::{u8x16, i8x16, i16x8, u16x8, i32x4, u32x4, f32x4};

#[target_feature(enable = "jcore-simd")]
pub unsafe fn vadd_i16(a: i16x8, b: i16x8) -> i16x8 { /* … */ }

#[target_feature(enable = "jcore-simd-int")]
pub unsafe fn vmulsu_dot(s: i8x16, u: u8x16) -> i32 {
    /* horizontal mixed-sign dot product, → MACL */
}

#[target_feature(enable = "jcore-simd-gf2")]
pub unsafe fn vclmul_d(a: u8x16, b: u8x16) -> u8x16 { /* … */ }

#[target_feature(enable = "jcore-simd-gf2")]
pub unsafe fn vcrc32c_b(crc: u32, data: u8x16, mask: u16) -> u32 { /* … */ }
```

Safe wrappers (example for CRC-32C):

```rust
pub struct Crc32C(u32);

impl Crc32C {
    pub fn new() -> Self { Crc32C(0xFFFFFFFF) }
    pub fn update(&mut self, data: &[u8]) {
        if !has_gf2_feature() { return self.update_software(data); }
        /* Process 16-byte chunks via vcrc32c_b, tail with predicate. */
    }
    pub fn finalize(self) -> u32 { !self.0 }
}
```

---

## 6. Tier 2 reference kernels

The Tier 2 intrinsic surface, beyond the type definitions in §3.4, is:

```c
/**
 * Carryless multiply of the low 64 bits of each operand, producing a
 * 128-bit GF(2)[x] polynomial product.
 *
 * Equivalent to: result.u64[0..1] = clmul64(a.u64[0], b.u64[0]);
 *
 * Issues SIMDV.Q #1 followed by VCLMUL.D.
 */
jcore_v128_t __jcore_vclmul_d(jcore_v128_t a, jcore_v128_t b);

/**
 * Fold up to 16 bytes of data into a running CRC-32C accumulator.
 *
 * @param crc   Current CRC-32C accumulator (pre-XOR with 0xFFFFFFFF).
 * @param data  Up to 16 bytes of input data.
 * @param mask  Bit i selects byte i of data; 0xFFFF = all 16.
 * @return      Updated accumulator.
 *
 * Issues an LDS-to-P0, VMKCHG, SIMDH.B #1, VCRC32C.B sequence;
 * GPR<->SIMD movement is handled transparently.
 */
uint32_t __jcore_vcrc32c_b(uint32_t crc, jcore_v128_t data, jcore_mask16_t mask);
```

For non-low-half VCLMUL inputs the programmer applies a swizzle intrinsic first:

```c
jcore_v128_t a_hi = __jcore_vswizzle_d(a, 1);  /* high 64 bits to low position */
jcore_v128_t product_hi_lo = __jcore_vclmul_d(a_hi, b);
```

### 6.1 CRC-32C tight loop

```c
#include <jcore/simd.h>

uint32_t crc32c(const uint8_t *buf, size_t len) {
    uint32_t crc = 0xFFFFFFFF;

    /* 16-byte chunks */
    while (len >= 16) {
        jcore_v128_t chunk;
        memcpy(&chunk, buf, 16);
        crc = __jcore_vcrc32c_b(crc, chunk, 0xFFFF);
        buf += 16;
        len -= 16;
    }

    /* Tail: 0..15 bytes, single predicated instruction */
    if (len > 0) {
        jcore_v128_t tail;
        memset(&tail, 0, sizeof(tail));
        memcpy(&tail, buf, len);
        jcore_mask16_t mask = (uint16_t)((1u << len) - 1);
        crc = __jcore_vcrc32c_b(crc, tail, mask);
    }

    return ~crc;
}
```

**Expected performance** (Tier B 3-cycle CLMUL pipeline, see [hardware-impl.md §6.3](hardware-impl.md)): ~1 byte / cycle. Compare to ~5–10 cycles / byte for software table-driven CRC-32C.

### 6.2 AES-GCM (GHASH)

GHASH operates in GF(2^128) modulo p(x) = x^128 + x^7 + x^2 + x + 1. Karatsuba decomposition of the 128×128 multiply:

```c
jcore_v128_t ghash_mul(jcore_v128_t a, jcore_v128_t b) {
    /* Split into 64-bit halves */
    jcore_v128_t a_lo = __jcore_vswizzle_d(a, 0);  /* a[63:0]   in low */
    jcore_v128_t a_hi = __jcore_vswizzle_d(a, 1);  /* a[127:64] in low */
    jcore_v128_t b_lo = __jcore_vswizzle_d(b, 0);
    jcore_v128_t b_hi = __jcore_vswizzle_d(b, 1);

    /* Karatsuba: three CLMULs instead of four */
    jcore_v128_t P0 = __jcore_vclmul_d(a_lo, b_lo);
    jcore_v128_t P1 = __jcore_vclmul_d(a_hi, b_hi);
    jcore_v128_t a_xor = __jcore_vxor(a_lo, a_hi);
    jcore_v128_t b_xor = __jcore_vxor(b_lo, b_hi);
    jcore_v128_t P2 = __jcore_vclmul_d(a_xor, b_xor);

    /* Combine: result_256 = (P1 << 128) ^ (mid << 64) ^ P0
       where mid = P2 ^ P0 ^ P1                                 */
    jcore_v128_t mid = __jcore_vxor(P2, __jcore_vxor(P0, P1));

    /* Montgomery-style reduction modulo p(x) via two more CLMULs
       against the well-known reduction constants K1, K2.        */
    extern const jcore_v128_t GHASH_REDUCTION_K1, GHASH_REDUCTION_K2;
    return ghash_reduce(P0, mid, P1);
}
```

**Expected performance:** ~5 VCLMUL.D + ~10 XOR per 16-byte block ≈ 25–30 cycles per block on Tier B. Comparable to AES-NI + PCLMULQDQ on x86 (~20 cycles per block).

The reduction-constant values K1, K2 are the well-known Gueron–Kounavis constants (their 2009 paper is a *post-2006 implementation reference* only; the underlying Montgomery-GF(2) reduction technique is the pre-2006 Koç-Acar 1998 work cited in [spec.md Appendix C.3.1](spec.md)).

### 6.3 RAID-6 P and Q syndromes

```c
void raid6_syndromes(const uint8_t **strips, size_t nstrips, size_t len,
                     uint8_t *P, uint8_t *Q) {
    extern const uint64_t RAID6_G_POWERS[];   /* GF(2^8) generator powers */

    for (size_t i = 0; i < len; i += 16) {
        jcore_v128_t p = __jcore_vzero();
        jcore_v128_t q = __jcore_vzero();

        for (size_t k = 0; k < nstrips; k++) {
            jcore_v128_t s;
            memcpy(&s, strips[k] + i, 16);

            /* P syndrome: simple XOR */
            p = __jcore_vxor(p, s);

            /* Q syndrome: GF(2^8) multiply by g^k, accumulate */
            jcore_v128_t g = __jcore_vbroadcast_b(RAID6_G_POWERS[k]);
            jcore_v128_t gq = gf256_mul_simd(s, g);    /* uses VCLMUL.D */
            q = __jcore_vxor(q, gq);
        }
        memcpy(P + i, &p, 16);
        memcpy(Q + i, &q, 16);
    }
}
```

The `gf256_mul_simd` helper uses VCLMUL.D for the polynomial multiply and a software reduction modulo the GF(2^8) generator (0x11D for the standard RAID-6 polynomial).

**Expected performance:** ~2–3× the per-byte syndrome throughput versus software-only RAID-6. The Linux `md` driver's `raid6_gen_syndrome` is the canonical benchmark target.

### 6.4 HQC post-quantum polynomial multiply

```c
void hqc_poly_mul(const uint64_t *a, const uint64_t *b, uint64_t *result,
                  size_t n_words) {
    memset(result, 0, 2 * n_words * sizeof(uint64_t));
    for (size_t i = 0; i < n_words; i++) {
        jcore_v128_t a_i = __jcore_vload_u64_to_low(a[i]);
        for (size_t j = 0; j < n_words; j++) {
            jcore_v128_t b_j = __jcore_vload_u64_to_low(b[j]);
            jcore_v128_t prod = __jcore_vclmul_d(a_i, b_j);
            xor_into_result(result + i + j, prod);
        }
    }
}
```

**Expected performance:** O(n²/64) cycles for the schoolbook variant. For HQC-128 (n ≈ 17,669 bits, ~277 64-bit words): ~76,000 VCLMUL.D operations per multiply, or ~25–30 µs on a 500 MHz core. Layer Karatsuba (or Toom-Cook) on top for O(n^log₂3 / 64); reference implementations exist in the HQC NIST submission package.

### 6.5 Reed-Solomon FEC decoder

Same VCLMUL.D-based GF(2^8) primitive as RAID-6 with different field generators:

```c
#define DVB_S2_REDUCTION_POLY  0x11D

uint8_t gf256_mul_dvb_s2(uint8_t a, uint8_t b) {
    jcore_v128_t va = __jcore_vsetlo_u64(a);
    jcore_v128_t vb = __jcore_vsetlo_u64(b);
    jcore_v128_t prod = __jcore_vclmul_d(va, vb);
    return gf256_reduce(prod, DVB_S2_REDUCTION_POLY);
}
```

CCSDS uses 0x187; same shape.

---

## 7. Toolchain integration (Tier 2 specifics)

### 7.1 Binutils (GAS, objdump)

The SH-2 assembler is extended with the Tier 0/1/2 mnemonics. The bottom-line additions for Tier 2:

```
SIMDV.Q  #N                  ; required prefix for VCLMUL.D
SIMDH.B  #N (alias SIMDHA.B) ; required prefix for VCRC32C.B
VCLMUL.D Vm, Vn
VCRC32C.B Vm, Vn
```

Implementation: add new entries to the SH-2 opcode table in `binutils/opcodes/sh-opc.h`, with the SIMD-prefix bit a new instruction class. Objdump disassembly recognises the prefix and labels the following instructions with their SIMD context.

A working binutils-style description of the canonical CRC-32C initialisation idiom:

```asm
    ; Initialise CRC accumulator in V0[31:0] = 0xFFFFFFFF
    MOV     #-1, R0
    VINS.L  R0, V0.0         ; assembler emits VLNS V0, #0 ; VINS.L R0

    ; Process buffer (see kernel in §6.1) ...

    ; Finalise: extract V0[31:0] into R0 and complement
    VEXT.L  V0.0, R0
    NOT     R0, R0
```

This replaces the GPR-stack-shuffling sequence shown in the archived VCLMUL software spec; with VLNS+VEXT/VINS as documented in [spec.md §5.7](spec.md), no scratch-stack round-trip is needed.

### 7.2 GCC and LLVM backends

See §4.1 / §4.2. Tier 2 adds the builtins `__builtin_jcore_vclmul_d` and `__builtin_jcore_vcrc32c_b`, available under `-mjcore-simd-gf2`. RTL pattern names: `vclmul_d_v128`, `vcrc32c_b_v128`.

---

## 8. Linux kernel integration

### 8.1 Crypto API: crc32c driver

Add a new module `crypto/crc32c-jcore.c`:

```c
/* SPDX-License-Identifier: GPL-2.0 */
#include <crypto/internal/hash.h>
#include <linux/module.h>
#include <asm/jcore-simd.h>          /* defines __jcore_vcrc32c_b */

static int crc32c_jcore_update(struct shash_desc *desc, const u8 *data,
                                unsigned int len) {
    u32 *crc = shash_desc_ctx(desc);
    *crc = crc32c_jcore(*crc, data, len);
    return 0;
}

static struct shash_alg crc32c_alg = {
    .digestsize = 4,
    .init       = crc32c_jcore_init,
    .update     = crc32c_jcore_update,
    .final      = crc32c_jcore_final,
    .descsize   = sizeof(u32),
    .base       = {
        .cra_name           = "crc32c",
        .cra_driver_name    = "crc32c-jcore",
        .cra_priority       = 200,   /* higher than generic */
        .cra_blocksize      = 1,
        .cra_module         = THIS_MODULE,
    },
};
```

Module init checks `HWCAP_JCORE_SIMD_GF2` and registers the algorithm only if the CPU supports the extension.

### 8.2 lib/crc32c, lib/raid6

- `lib/crc32c.c` (generic) remains the fallback path; the jcore module takes priority via `cra_priority` when present.
- Add `lib/raid6/jcore-gf2.c` implementing `raid6_gen_syndrome` and `raid6_xor_syndrome` using VCLMUL.D. The `md` driver's `raid6_pq_init` boot-time benchmark auto-selects the fastest available algorithm.

### 8.3 Higher-level consumers

- **dm-crypt and AES-GCM**: register `crypto/aes-gcm-jcore.c` as a higher-priority AEAD provider; `drivers/md/dm-crypt.c` picks it up automatically via the crypto API. No dm-crypt code changes.
- **net/sctp** (`net/sctp/crc32c.c`): calls lib/crc32c entry points; inherits acceleration automatically.
- **fs/btrfs** (`fs/btrfs/checksum.c`): uses crypto API; same picture.
- **nvme-tcp / iSCSI**: both use crypto API for data digest. No driver-specific work needed.

### 8.4 Conformance for partial Tier-2 implementations

For variants shipping Tier 2 in the iterative (Tier C) hardware mode (see [hardware-impl.md §6.4](hardware-impl.md), 64 cycles per CLMUL), the recommended kernel posture is: **do not** register the higher-priority crypto API providers. At 64-cycle VCLMUL.D, the software slice-by-8 CRC-32C is faster. Boot-time benchmarking (`raid6_pq_init`-style) for the crc32c module should be added so the kernel automatically picks the right path. Userspace libraries may still use the intrinsics directly when explicitly opted in.

### 8.5 HWCAP bit allocation

New HWCAP bits must be defined in `arch/sh/include/uapi/asm/hwcap.h` (or J-core-specific equivalent):

```c
#define HWCAP_JCORE_SIMD             (1UL << X)   /* Tier 0; bit TBD */
#define HWCAP_JCORE_SIMD_INT         (1UL << Y)   /* Tier 1; bit TBD */
#define HWCAP_JCORE_SIMD_GF2         (1UL << Z)   /* Tier 2; bit TBD */
#define HWCAP_JCORE_SIMD_RELAXED_MEM (1UL << W)   /* N>1 memory blocks; bit TBD */
```

The first three bits are **tier** bits (additive feature levels). `HWCAP_JCORE_SIMD_RELAXED_MEM` is a **microarchitectural-capability** bit, orthogonal to tier: it signals that the core lifts the N=1 memory-block restriction ([spec.md §5.6.1](spec.md)), as J32-OOO may. It is *not* implied by any tier and must be tested independently.

A binary or library may only emit N>1 SIMDV memory blocks when this bit is set; otherwise such a block raises slot-illegal on the running core (the feature is one-way compatible — see [spec.md §5.6.1](spec.md)). Toolchains gate the relaxed form behind a `-m` flag plus this runtime check:

```c
static inline int jcore_simd_relaxed_mem(void) {
    return (getauxval(AT_HWCAP) & HWCAP_JCORE_SIMD_RELAXED_MEM) != 0;
}
```

Bit numbers must be coordinated with the J-core Linux port; tracked as an open question in [spec.md §11](spec.md).

---

## 9. Userspace library integration

| Library | Touchpoint | Acceleration source |
|---|---|---|
| OpenSSL (3.0+ provider, or ENGINE for legacy) | `crc32`, `crc32c`, `aes-{128,192,256}-gcm` | VCRC32C.B for CRC; VCLMUL.D for GHASH |
| libsodium | `crypto_aead/aes256gcm/*` | VCLMUL.D for GHASH (ChaCha20-Poly1305 is the preferred AEAD anyway and benefits from broader SIMD) |
| ISA-L (Intel Storage Acceleration Library) | `erasure_code/jcore/`, `crc/jcore/` | VCLMUL.D for Reed-Solomon and CRC paths |
| zlib / gzip | `crc32.c` | VCLMUL.D-based CLMUL folding (CRC-32-IEEE constants differ from CRC-32C; same primitive) |
| libcrc | per-polynomial backends | VCLMUL.D for any CRC variant |

All of these auto-select based on HWCAP at library load.

---

## 10. Performance characterisation

### 10.1 Expected speedups (Tier B Tier 2 hardware, 500 MHz)

| Workload | Software baseline | With Tier 2 | Speedup |
|---|---|---|---|
| CRC-32C, 4 KB buffer | ~30,000 cycles | ~4,500 cycles | 6.7× |
| CRC-32C, 16-byte buffer | ~150 cycles | ~20 cycles | 7.5× |
| AES-GCM encrypt, 1 MB | ~30 cycles/byte | ~6 cycles/byte | 5× |
| RAID-6 syndrome, 4 disks | ~8 cycles/byte | ~3 cycles/byte | 2.7× |
| HQC multiply (HQC-128) | ~800 µs | ~25 µs | 30× |

Tier A is 10–15% faster; Tier C is 10–20× slower (still correctness-equivalent, not throughput-equivalent).

### 10.2 Cycle counting methodology

```c
#include <jcore/perfcounter.h>

void measure_crc32c(const uint8_t *buf, size_t len) {
    uint64_t cycles_start = __jcore_read_cycles();
    uint32_t crc = crc32c(buf, len);
    uint64_t cycles_end = __jcore_read_cycles();
    printf("%lu cycles for %zu bytes (%.2f bytes/cycle)\n",
           cycles_end - cycles_start, len,
           (double)len / (cycles_end - cycles_start));
}
```

The performance counter exposes total cycles, VCLMUL.D count, VCRC32C.B count, and stall cycles attributed to the GF unit. See [hardware-impl.md §12.3](hardware-impl.md).

### 10.3 Cache effects

For buffers larger than L1, performance is bounded by memory bandwidth, not CLMUL throughput. The standard prefetch-and-process pattern applies — and the Tier 0 NT hint ([spec.md §5.6.2](spec.md)) is the architectural lever for streaming workloads that should not pollute the cache.

For small buffers (typical of network-packet CRC), the entire buffer fits in registers and CLMUL throughput is the bottleneck. The 16-byte tail handler is critical here — predicated VCRC32C.B saves ~10 cycles vs scalar loop epilogue.

---

## 11. Fallback paths

### 11.1 No extension present

When `HWCAP_JCORE_SIMD_GF2` is not set, software falls back to:

- **CRC-32C:** slice-by-8 table-driven (Linux kernel default). ~5 cycles/byte.
- **AES-GCM:** bitsliced AES (Käsper-Schwabe) for the cipher, scalar GHASH for the MAC. ~15 cycles/byte.
- **RAID-6:** Linux's `int.c` reference. ~8 cycles/byte.
- **HQC:** pure-software polynomial multiply. ~800 µs / HQC-128 multiply.

Fallback paths are correctness-equivalent; only performance differs.

### 11.2 Tier C present

Tier C is architecturally transparent — software cannot distinguish it from Tier A or B except by cycle counting. Code written for VCLMUL.D works identically; throughput is reduced ~64×. See §8.4 for the recommended kernel posture.

### 11.3 Mixed environments

In heterogeneous systems (some cores with extension, some without), pin crypto-heavy workloads to the extension-bearing cores via `sched_setaffinity` or kernel CPU-isolation infrastructure.

---

## 12. End-to-end CRC-32C example

```c
/* crc32c_demo.c — compile with: cc -O2 -mjcore-simd-gf2 crc32c_demo.c */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <sys/auxv.h>
#include <jcore/simd.h>

#define HWCAP_JCORE_SIMD_GF2  (1UL << 16)   /* TBD */

static uint32_t crc32c_hw(const uint8_t *buf, size_t len) {
    uint32_t crc = 0xFFFFFFFF;
    while (len >= 16) {
        jcore_v128_t chunk;
        memcpy(&chunk, buf, 16);
        crc = __jcore_vcrc32c_b(crc, chunk, 0xFFFF);
        buf += 16; len -= 16;
    }
    if (len > 0) {
        jcore_v128_t tail;
        memset(&tail, 0, sizeof(tail));
        memcpy(&tail, buf, len);
        crc = __jcore_vcrc32c_b(crc, tail, (1u << len) - 1);
    }
    return ~crc;
}

static uint32_t crc32c_sw(const uint8_t *buf, size_t len) {
    static const uint32_t TABLE_C[256] = { /* slice-by-1 table */ };
    uint32_t crc = 0xFFFFFFFF;
    while (len--) crc = (crc >> 8) ^ TABLE_C[(crc ^ *buf++) & 0xFF];
    return ~crc;
}

uint32_t crc32c(const uint8_t *buf, size_t len) {
    static int has_hw = -1;
    if (has_hw < 0)
        has_hw = (getauxval(AT_HWCAP) & HWCAP_JCORE_SIMD_GF2) ? 1 : 0;
    return has_hw ? crc32c_hw(buf, len) : crc32c_sw(buf, len);
}

int main(void) {
    const char *test = "123456789";
    uint32_t expected = 0xE3069283;  /* known CRC-32C of "123456789" */
    uint32_t got = crc32c((const uint8_t*)test, strlen(test));
    printf("CRC-32C of \"%s\" = 0x%08X (expected 0x%08X) %s\n",
           test, got, expected, (got == expected) ? "OK" : "FAIL");
    return (got == expected) ? 0 : 1;
}
```

This pattern (HWCAP detection, fallback path, intrinsic use, predicated tail) is the canonical template for any Tier 2-aware C application.

---

## 13. Migration roadmap (Tier 2 upstream rollout)

Suggested rollout order for upstream integration:

1. **Toolchain** (months 0–3): binutils, GCC builtins, basic intrinsic header.
2. **Linux kernel CRC-32C** (months 3–6): smallest blast radius, broadest coverage (storage, networking, filesystems).
3. **Linux kernel RAID-6** (months 6–9): moderate complexity, well-tested benchmark targets.
4. **OpenSSL provider** (months 9–12): enables web servers, VPN gateways, TLS workloads.
5. **libsodium** (months 12–15): modern application crypto.
6. **ISA-L** (months 15–18): storage-acceleration applications.
7. **HQC reference implementation port** (months 18–24): post-quantum readiness; gates on NIST FIPS finalisation for HQC.

---

## 14. Open issues

1. **HWCAP bit assignment** for all three SIMD tiers awaits J-core Linux port coordination.
2. **Intrinsic header location** (`<jcore/simd.h>` proposed) needs alignment with broader SIMD intrinsic naming across the project.
3. **Compiler target-flag naming** (`-mjcore-simd`, `-mjcore-simd-int`, `-mjcore-simd-gf2` proposed) follows GCC convention but should be ratified before binutils patches are upstreamed.
4. **GHASH reduction constants** are well-known; package them in a single header for reuse across crypto libraries.
5. **Tier 0/1 autovectorisation patterns** in GCC and LLVM need a dedicated lowering pass; the current state is intrinsics-driven only.

---

## 15. References

Architectural prior art and the project-wide pre-2006 prior-art policy are in [spec.md Appendix C](spec.md) and [../glossary.md §2](../glossary.md). Implementation-level (post-2006) reference material — not used as architectural prior art — includes:

- Linux kernel `lib/crc32c.c` (software fallback reference).
- Linux kernel `lib/raid6/` (multi-architecture RAID-6 driver).
- Linux kernel `arch/x86/crypto/crc32c-pcl-intel-asm_64.S` (PCLMULQDQ-based CRC-32C — informative pattern).
- Linux kernel `arch/arm64/crypto/aes-glue.c` (ARMv8 crypto extension integration pattern).
- OpenSSL `crypto/modes/asm/ghash-x86_64.pl` (GHASH via PCLMULQDQ — informative pattern).
- HQC submission package, NIST PQC Round 4 — reference implementations of polynomial multiplication.
- IETF RFC 3720 (iSCSI, CRC-32C test vectors).
- IETF RFC 4960 (SCTP, CRC-32C in network protocols).
- NIST SP 800-38D (Galois/Counter Mode, GHASH specification).
- Käsper & Schwabe, "Faster and Timing-Attack Resistant AES-GCM," CHES 2009 (bitsliced AES reference for the software fallback path).

The Gueron-Kounavis 2009 paper and Gueron's 2014 Intel white paper are referenced *only* as implementation guides for the well-known reduction constants used by §6.2; they are not architectural prior art. See [spec.md Appendix C.4](spec.md).
