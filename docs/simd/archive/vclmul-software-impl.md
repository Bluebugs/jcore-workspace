> **Superseded.** This document was consolidated into `../spec.md` / `../hardware-impl.md` / `../software-impl.md` on 2026-05-25. Kept for historical reference.

# VCLMUL and VCRC32C: Software Implementation Guide

**Document status:** Draft v0.1
**Audience:** OS kernel developers, library maintainers, compiler toolchain engineers, application developers
**Companion to:** 01-design-spec.md (architectural specification), 02-hardware-impl.md (hardware implementation)

---

## 1. Scope

This document describes how to use VCLMUL.D and VCRC32C.B from software. It covers:

- Programmer's model and instruction semantics from a software perspective
- Assembly mnemonics and the canonical assembly idioms
- C and Rust intrinsics and their semantics
- Reference kernels for CRC-32C, AES-GCM (GHASH), RAID-6 syndrome, and HQC polynomial multiply
- Toolchain integration (binutils, GCC, LLVM)
- Linux kernel integration (crypto API, lib/crc32c, lib/raid6)
- Userspace library integration (OpenSSL, libsodium, ISA-L, zlib)
- Feature detection and fallback paths
- Performance expectations

---

## 2. Programmer's model

### 2.1 Quick reference

| Instruction | Mode | Effect |
|---|---|---|
| `vclmul.d  vd, vs` | Vertical-SIMD prefix, 64-bit lanes | `vd[63:0]` ⊗ `vs[63:0]` → `vd[127:0]` (GF(2) polynomial product) |
| `vcrc32c.b vd, vs` | Horizontal-reduce prefix, 8-bit lanes | `vd[31:0]` = CRC-32C fold of `vs` bytes with mask, into `vd[31:0]` |

### 2.2 Register model

Both instructions operate on the 128-bit SIMD register file (J32) or 128/256-bit register file (J64). They share the file with all other SIMD operations.

VCRC32C.B's accumulator lives in the **low 32 bits** of the destination SIMD register. The upper 96 bits are preserved across the instruction. This lets software park other state alongside the accumulator or use upper lanes for parallel CRC streams in future extensions.

### 2.3 Calling convention impact

No changes to the standard jcore calling convention. SIMD registers retain their existing caller/callee-save partitioning. CRC accumulators in flight across function calls follow whatever convention applies to the SIMD register holding them.

### 2.4 Mode prerequisites

Software is responsible for issuing the correct prefix before each instruction. The exception model is strict: wrong prefix mode raises illegal-instruction trap. There is no "best-effort" fallback in hardware.

---

## 3. Assembly mnemonics

### 3.1 GAS (GNU assembler) syntax

```asm
    ; VCLMUL.D under vertical prefix, single instruction
    vprefix.v.d  N=1
    vclmul.d     vr5, vr3              ; vr5 = vr5 ⊗ vr3 (low 64 bits)

    ; VCLMUL.D batch of four under vertical prefix
    vprefix.v.d  N=4
    vclmul.d     vr5, vr3
    vclmul.d     vr6, vr3
    vclmul.d     vr7, vr3
    vclmul.d     vr8, vr3

    ; VCRC32C.B under horizontal prefix with mask
    mov          #0xFFFF, r0           ; full 16-byte mask
    vprefix.h.b  N=1, mask=r0
    vcrc32c.b    vr0, vr1              ; vr0[31:0] = crc32c_fold(vr0[31:0], vr1)
```

The prefix and the SIMD operation are written as separate instructions for clarity. Some assemblers may collapse them visually; the underlying bit encoding is two 16-bit instructions in sequence regardless.

### 3.2 Mnemonic conventions

- `.d` suffix = doubleword (64-bit lane operation)
- `.b` suffix = byte (8-bit lane operation)
- `vrN` = SIMD register N (range depends on register file size, typically 0..15)
- `vprefix.v.d` = vertical prefix, 64-bit width
- `vprefix.h.b` = horizontal-reduce prefix, 8-bit width

---

## 4. C intrinsics

### 4.1 Header

```c
#include <jcore/simd.h>
```

### 4.2 Type definitions

```c
typedef union {
    uint8_t   u8 [16];
    uint16_t  u16[8];
    uint32_t  u32[4];
    uint64_t  u64[2];
    int8_t    i8 [16];
    int16_t   i16[8];
    int32_t   i32[4];
    int64_t   i64[2];
} jcore_v128_t;

typedef uint16_t jcore_mask16_t;   /* one bit per byte lane */
```

### 4.3 VCLMUL intrinsic

```c
/**
 * Carryless multiply of the low 64 bits of each operand,
 * producing a 128-bit GF(2)[x] polynomial product.
 *
 * Equivalent to: result.u64[0..1] = clmul64(a.u64[0], b.u64[0]);
 *
 * Issues a vertical-SIMD prefix with 64-bit lanes followed by VCLMUL.D.
 */
jcore_v128_t __jcore_vclmul_d(jcore_v128_t a, jcore_v128_t b);
```

For non-low half selection, the programmer applies a swizzle intrinsic first:

```c
jcore_v128_t a_hi = __jcore_vswizzle_d(a, 1);  /* high 64 bits to low position */
jcore_v128_t product_hi_lo = __jcore_vclmul_d(a_hi, b);
```

### 4.4 VCRC32C intrinsic

```c
/**
 * Fold up to 16 bytes of data into a running CRC-32C accumulator.
 *
 * @param crc   The current CRC-32C accumulator (pre-XOR with 0xFFFFFFFF).
 * @param data  Up to 16 bytes of input data.
 * @param mask  Bit i selects byte i of data for inclusion. 0xFFFF = all 16.
 * @return      Updated accumulator.
 *
 * Issues a horizontal-reduce prefix with 8-bit lanes and the mask, followed
 * by VCRC32C.B. The accumulator is communicated via the low 32 bits of a
 * SIMD register; this intrinsic handles GPR<->SIMD movement transparently.
 */
uint32_t __jcore_vcrc32c_b(uint32_t crc, jcore_v128_t data, jcore_mask16_t mask);
```

### 4.5 Compiler builtins (GCC/Clang)

These intrinsics map to compiler builtins in GCC and Clang:

```c
__builtin_jcore_vclmul_d(a, b)
__builtin_jcore_vcrc32c_b(crc, data, mask)
```

The builtins are recognized only when `-mjcore-simd-gf2` (or equivalent target flag) is passed.

---

## 5. Rust bindings

### 5.1 Crate structure

```toml
# Cargo.toml
[dependencies]
jcore-simd = "0.1"
```

### 5.2 Unsafe primitive bindings

```rust
use core::simd::u8x16;

#[inline]
#[target_feature(enable = "jcore-simd-gf2")]
pub unsafe fn vclmul_d(a: u8x16, b: u8x16) -> u8x16 {
    /* compiler intrinsic call */
}

#[inline]
#[target_feature(enable = "jcore-simd-gf2")]
pub unsafe fn vcrc32c_b(crc: u32, data: u8x16, mask: u16) -> u32 {
    /* compiler intrinsic call */
}
```

### 5.3 Safe wrappers

```rust
pub struct Crc32C(u32);

impl Crc32C {
    pub fn new() -> Self { Crc32C(0xFFFFFFFF) }

    pub fn update(&mut self, data: &[u8]) {
        if !has_gf2_feature() {
            return self.update_software(data);
        }
        // Process 16-byte chunks via VCRC32C.B, tail with predicate.
        // (Full kernel in Section 7.1.)
    }

    pub fn finalize(self) -> u32 { !self.0 }
}
```

---

## 6. Common kernels

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

**Expected performance:** ~1 byte per cycle on jcore Tier B (3-cycle CLMUL pipeline). Compare to ~5-10 cycles per byte for software table-driven CRC-32C.

### 6.2 AES-GCM (GHASH)

GHASH operates in GF(2^128) modulo p(x) = x^128 + x^7 + x^2 + x + 1. Karatsuba decomposition of the 128×128 multiply:

```c
/*
 * GHASH multiplication: result = (a * b) mod p(x)
 *
 * a, b are 128-bit field elements.
 * Uses VCLMUL.D plus reduction.
 */
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

    /* Combine */
    jcore_v128_t mid = __jcore_vxor(P2, __jcore_vxor(P0, P1));
    /* result_256 = (P1 << 128) ^ (mid << 64) ^ P0 */

    /* Montgomery-style reduction modulo p(x) via two more CLMULs */
    /* Constants: K1 = p_reduction_low, K2 = p_reduction_high */
    extern const jcore_v128_t GHASH_REDUCTION_K1, GHASH_REDUCTION_K2;
    /* (full reduction sequence: see Gueron & Kounavis 2009) */

    return ghash_reduce(P0, mid, P1);
}
```

**Expected performance:** ~5 VCLMUL.D + ~10 XOR per 16-byte GHASH block ≈ 25-30 cycles per block on Tier B. Comparable to AES-NI + PCLMULQDQ on x86 (which achieves ~20 cycles per block).

### 6.3 RAID-6 P and Q syndromes

```c
/*
 * Compute P and Q syndromes for RAID-6 with `nstrips` data strips,
 * each `len` bytes long.
 *
 * P[i] = XOR over all strips of strip[k][i]
 * Q[i] = XOR over all strips of g^k * strip[k][i]   (in GF(2^8))
 *
 * VCLMUL.D performs 8 parallel GF(2^8) multiplies per call when
 * operands are packed 8-bit-in-64-bit (with byte interleaving).
 */
void raid6_syndromes(const uint8_t **strips, size_t nstrips, size_t len,
                     uint8_t *P, uint8_t *Q) {
    /* Generator constants for GF(2^8): g^k for k = 0..nstrips-1 */
    extern const uint64_t RAID6_G_POWERS[];

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
            jcore_v128_t gq = gf256_mul_simd(s, g);  /* uses VCLMUL.D */
            q = __jcore_vxor(q, gq);
        }

        memcpy(P + i, &p, 16);
        memcpy(Q + i, &q, 16);
    }
}
```

The `gf256_mul_simd` helper uses VCLMUL.D for the polynomial multiply and a software reduction modulo the GF(2^8) generator (0x11D for the standard RAID-6 polynomial).

**Expected performance:** ~2-3× the per-byte syndrome throughput versus software-only RAID-6. The Linux md driver's `raid6_gen_syndrome` is a well-known benchmark target.

### 6.4 HQC post-quantum polynomial multiply

HQC's hot path is multiplication of polynomials over GF(2) with degree ~17,000+. Schoolbook with VCLMUL.D:

```c
/*
 * Multiply two GF(2) polynomials of degree n.
 * Input: a[], b[] arrays of n/64 uint64_t words.
 * Output: result[] of 2*n/64 uint64_t words.
 */
void hqc_poly_mul(const uint64_t *a, const uint64_t *b, uint64_t *result,
                  size_t n_words) {
    memset(result, 0, 2 * n_words * sizeof(uint64_t));

    for (size_t i = 0; i < n_words; i++) {
        jcore_v128_t a_i = __jcore_vload_u64_to_low(a[i]);
        for (size_t j = 0; j < n_words; j++) {
            jcore_v128_t b_j = __jcore_vload_u64_to_low(b[j]);
            jcore_v128_t prod = __jcore_vclmul_d(a_i, b_j);
            /* XOR prod into result[i+j] and result[i+j+1] */
            xor_into_result(result + i + j, prod);
        }
    }
}
```

**Expected performance:** ~O(n²/64) cycles. For HQC-128 (n ≈ 17,669 bits, ~277 64-bit words), this gives ~76,000 VCLMUL.D operations per multiply, or ~25-30 µs on a 500 MHz core. Plenty fast for the post-quantum use case.

For better performance, layer Karatsuba (or Toom-Cook) on top: O(n^log2(3) / 64) operations. Reference implementations exist in the HQC submission package.

### 6.5 Reed-Solomon FEC decoder

Reed-Solomon error correction over GF(2^8) uses the same VCLMUL.D-based GF(2^8) multiply primitive as RAID-6, with different field generators. The decoder's syndrome calculation and error locator polynomial evaluation map directly to the same patterns.

```c
/* DVB-S2 uses GF(2^8) with primitive polynomial 0x11D */
#define DVB_S2_REDUCTION_POLY  0x11D

uint8_t gf256_mul_dvb_s2(uint8_t a, uint8_t b) {
    jcore_v128_t va = __jcore_vsetlo_u64(a);
    jcore_v128_t vb = __jcore_vsetlo_u64(b);
    jcore_v128_t prod = __jcore_vclmul_d(va, vb);
    /* Reduce mod DVB_S2_REDUCTION_POLY */
    return gf256_reduce(prod, DVB_S2_REDUCTION_POLY);
}
```

---

## 7. Toolchain integration

### 7.1 Binutils (GAS, objdump)

The SH-2 assembler is extended with the new mnemonics:

```
vprefix.v.d  N=<count>
vprefix.h.b  N=<count>, mask=<reg>
vclmul.d     vd, vs
vcrc32c.b    vd, vs
```

Implementation: add new entries to the SH-2 opcode table in `binutils/opcodes/sh-opc.h`, with the new SIMD-prefix bit being a new instruction class. Objdump disassembly recognizes the prefix and labels the following instructions accordingly.

### 7.2 GCC backend

Two integration points:

1. **Builtin definitions** in `gcc/config/sh/sh-builtins.def` (or jcore-specific equivalent), mapping `__builtin_jcore_vclmul_d` to the appropriate RTL pattern.
2. **RTL patterns** in `gcc/config/sh/sh.md` for `vclmul_d_v128` and `vcrc32c_b_v128`.

Auto-vectorization is not expected to generate these instructions from loop patterns; they are explicitly invoked via intrinsics or inline assembly.

Target option: `-mjcore-simd-gf2` enables the builtins and emits the corresponding instructions. The default for J32/J64 with the GF2 extension present should be enabled; for other variants, software fallback paths apply.

### 7.3 LLVM backend

LLVM integration follows the same shape: intrinsics defined in `llvm/include/llvm/IR/IntrinsicsJCore.td`, lowered via TableGen patterns in the jcore backend. Clang exposes the intrinsics via `<jcore/simd.h>`.

### 7.4 Feature detection at compile time

```c
#if defined(__JCORE_SIMD_GF2__)
    /* Use VCLMUL.D / VCRC32C.B */
#else
    /* Software fallback */
#endif
```

### 7.5 Feature detection at runtime

Linux exposes CPU features via `/proc/cpuinfo` and the auxiliary vector (`AT_HWCAP`). The jcore-specific HWCAP bit for the GF2 extension should be allocated (TBD: bit number to be assigned in the jcore Linux port).

```c
#include <sys/auxv.h>

bool has_jcore_gf2(void) {
    unsigned long hwcap = getauxval(AT_HWCAP);
    return (hwcap & HWCAP_JCORE_GF2) != 0;
}
```

---

## 8. Linux kernel integration

### 8.1 Crypto API: crc32c driver

The Linux kernel has a pluggable shash provider model for CRC-32C. Add a new module `crypto/crc32c-jcore.c`:

```c
/* SPDX-License-Identifier: GPL-2.0 */
#include <crypto/internal/hash.h>
#include <linux/module.h>
#include <asm/jcore-simd.h>     /* defines __jcore_vcrc32c_b */

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
        .cra_priority       = 200,     /* higher than generic */
        .cra_blocksize      = 1,
        .cra_module         = THIS_MODULE,
    },
};
```

Module init checks the HWCAP and only registers the algorithm if the CPU supports the extension.

### 8.2 lib/crc32c

The kernel's `lib/crc32c.c` (generic CRC-32C) is the fallback path. The module above takes priority via `cra_priority` when the extension is present.

### 8.3 lib/raid6

The kernel's `lib/raid6/` directory contains per-architecture syndrome generators. Add `lib/raid6/jcore-gf2.c` implementing `raid6_gen_syndrome` and `raid6_xor_syndrome` using VCLMUL.D.

The md driver auto-selects the fastest available algorithm at boot via the `raid6_pq_init` benchmark. The jcore-gf2 implementation should win on jcore-with-extension cores.

### 8.4 dm-crypt and AES-GCM

`drivers/md/dm-crypt.c` uses the crypto API. Once `crypto/aes-gcm-jcore.c` is registered as a higher-priority AEAD provider, dm-crypt picks it up automatically. No dm-crypt code changes needed.

### 8.5 net/sctp

`net/sctp/crc32c.c` calls the lib/crc32c entry points and inherits acceleration automatically.

### 8.6 fs/btrfs

btrfs's checksum infrastructure (`fs/btrfs/checksum.c` and related) uses the crypto API. Same picture: register a higher-priority shash provider and btrfs picks it up.

### 8.7 nvme-tcp / iscsi

Both use the crypto API for data digest computation. No driver-specific work needed.

### 8.8 HWCAP bit allocation

A new HWCAP bit `HWCAP_JCORE_GF2` must be defined in `arch/sh/include/asm/hwcap.h` (or jcore-specific equivalent). Boot code probes for the extension via CPUID-equivalent mechanism and sets the bit.

---

## 9. Userspace library integration

### 9.1 OpenSSL

OpenSSL uses ENGINE (legacy) or providers (3.0+) for hardware acceleration. Add a jcore provider that registers accelerated implementations of:

- `crc32` and `crc32c` (via VCRC32C.B)
- `aes-128-gcm`, `aes-192-gcm`, `aes-256-gcm` (via VCLMUL.D for GHASH; AES itself is bitsliced or via separate path)

The provider is selected automatically based on HWCAP at library load.

### 9.2 libsodium

libsodium uses runtime CPU feature detection. Patch `src/libsodium/crypto_aead/aes256gcm/aesni/` (or add jcore-equivalent directory) to use VCLMUL.D for GHASH.

ChaCha20-Poly1305 is the preferred libsodium AEAD anyway and benefits from your broader SIMD work (not specifically from VCLMUL).

### 9.3 ISA-L (Intel Storage Acceleration Library)

ISA-L has Reed-Solomon and CRC paths. Adding a jcore backend means contributing per-architecture implementations in:

- `erasure_code/jcore/`
- `crc/jcore/`

The build system auto-detects architecture and links the appropriate backend.

### 9.4 zlib / gzip

zlib computes CRC-32-IEEE for gzip streams. Although the polynomial differs from CRC-32C, the underlying CLMUL folding technique works identically with different constants. Patch `crc32.c` to use VCLMUL.D-based folding when the extension is available.

### 9.5 libcrc

The standalone libcrc library has per-polynomial implementations. Adding a jcore backend gives transparent acceleration for any CRC variant the library supports.

---

## 10. Performance characterization

### 10.1 Expected speedups

| Workload | Software baseline | With VCLMUL/VCRC32C | Speedup |
|---|---|---|---|
| CRC-32C, 4 KB buffer | ~30,000 cycles | ~4,500 cycles | 6.7× |
| CRC-32C, 16-byte buffer | ~150 cycles | ~20 cycles | 7.5× |
| AES-GCM encrypt, 1 MB | ~30 cycles/byte | ~6 cycles/byte | 5× |
| RAID-6 syndrome, 4 disks | ~8 cycles/byte | ~3 cycles/byte | 2.7× |
| HQC multiply (HQC-128) | ~800 µs | ~25 µs | 30× |

Estimates assume Tier B (Karatsuba pipelined) at 500 MHz. Tier A is 10-15% faster; Tier C is 10-20× slower (still acceptable for correctness, not throughput).

### 10.2 Cycle counting methodology

Recommended approach:

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

The performance counter exposes total cycles, VCLMUL.D count, VCRC32C.B count, and stall cycles attributed to the GF unit.

### 10.3 Cache effects

For buffers larger than L1, performance is bounded by memory bandwidth, not CLMUL throughput. The standard prefetch-and-process pattern applies.

For small buffers (typical of network packet CRC), the entire buffer fits in registers and CLMUL throughput is the bottleneck. The 16-byte tail handler is critical here — predicated VCRC32C.B saves ~10 cycles vs scalar loop epilogue.

---

## 11. Fallback paths

### 11.1 No extension present

When HWCAP_JCORE_GF2 is not set, software falls back to:

- **CRC-32C:** Slice-by-8 table-driven implementation (Linux kernel default). ~5 cycles/byte.
- **AES-GCM:** Bitsliced AES (Käsper-Schwabe) for the cipher, scalar GHASH for the MAC. ~15 cycles/byte.
- **RAID-6:** Linux's `int.c` reference implementation. ~8 cycles/byte.
- **HQC:** Pure-software polynomial multiply. ~800 µs per HQC-128 multiply.

Fallback paths are correctness-equivalent; only performance differs.

### 11.2 Tier C present (multi-cycle iterative)

Tier C is architecturally transparent — software cannot distinguish it from Tier A or B except by cycle counting. Code written for VCLMUL.D works identically; throughput is reduced by ~64×.

Pragmatic recommendation: for variants shipping Tier C, do NOT register the higher-priority crypto API providers. The 64-cycle VCLMUL.D is slower than slice-by-8 CRC-32C, so falling back to software is the right call. Userspace libraries should still use the intrinsics directly when explicitly opted into; the kernel's automatic-best-implementation logic should not.

### 11.3 Mixed environments

In heterogeneous systems (some cores with extension, some without), pin crypto-heavy workloads to the extension-bearing cores via `sched_setaffinity` or the kernel's CPU isolation infrastructure.

---

## 12. Example: end-to-end CRC-32C

A complete, runnable example demonstrating the full software stack:

```c
/* crc32c_demo.c — compile with: cc -O2 -mjcore-simd-gf2 crc32c_demo.c */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <sys/auxv.h>
#include <jcore/simd.h>

#define HWCAP_JCORE_GF2  (1UL << 16)   /* TBD: actual bit assignment */

static uint32_t crc32c_hw(const uint8_t *buf, size_t len) {
    uint32_t crc = 0xFFFFFFFF;

    while (len >= 16) {
        jcore_v128_t chunk;
        memcpy(&chunk, buf, 16);
        crc = __jcore_vcrc32c_b(crc, chunk, 0xFFFF);
        buf += 16;
        len -= 16;
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
    while (len--) {
        crc = (crc >> 8) ^ TABLE_C[(crc ^ *buf++) & 0xFF];
    }
    return ~crc;
}

uint32_t crc32c(const uint8_t *buf, size_t len) {
    static int has_hw = -1;
    if (has_hw < 0) {
        has_hw = (getauxval(AT_HWCAP) & HWCAP_JCORE_GF2) ? 1 : 0;
    }
    return has_hw ? crc32c_hw(buf, len) : crc32c_sw(buf, len);
}

int main(int argc, char **argv) {
    const char *test = "123456789";
    uint32_t expected = 0xE3069283;  /* known CRC-32C of "123456789" */
    uint32_t got = crc32c((const uint8_t*)test, strlen(test));
    printf("CRC-32C of \"%s\" = 0x%08X (expected 0x%08X) %s\n",
           test, got, expected,
           (got == expected) ? "OK" : "FAIL");
    return (got == expected) ? 0 : 1;
}
```

This demonstrates the complete pattern: HWCAP detection, fallback path, intrinsic usage, tail handling with predicate.

---

## 13. Migration roadmap

Suggested rollout order for upstream integration:

1. **Toolchain (months 0-3):** binutils, GCC builtins, basic intrinsic header.
2. **Linux kernel CRC-32C (months 3-6):** the smallest-blast-radius win, gets the broadest coverage (storage, networking, filesystems).
3. **Linux kernel RAID-6 (months 6-9):** moderate-complexity, well-tested benchmark targets.
4. **OpenSSL provider (months 9-12):** enables web servers, VPN gateways, TLS workloads.
5. **libsodium (months 12-15):** modern application crypto.
6. **ISA-L (months 15-18):** storage-acceleration applications.
7. **HQC reference implementation port (months 18-24):** post-quantum readiness; gates on NIST FIPS finalization for HQC.

---

## 14. Open issues

1. **HWCAP bit assignment** awaits jcore Linux port coordination.
2. **Intrinsic header location** (`<jcore/simd.h>` proposed) needs alignment with broader SIMD intrinsic naming.
3. **Compiler target flag naming** (`-mjcore-simd-gf2` proposed) follows GCC convention but should be ratified before binutils patches are upstreamed.
4. **GHASH reduction constants** are well-known (Gueron-Kounavis paper provides them); package them in a header for reuse across crypto libraries.

---

## 15. References

### Specifications and standards
- 01-design-spec.md — Architectural specification for VCLMUL.D and VCRC32C.B
- 02-hardware-impl.md — Hardware implementation guide
- IETF RFC 3720 — iSCSI (CRC-32C test vectors used in Section 6.1)
- IETF RFC 4960 — SCTP (CRC-32C in network protocols)
- NIST SP 800-38D — Galois/Counter Mode (GHASH specification referenced in Section 6.2)

### Implementation references
- Linux kernel `lib/crc32c.c` — software fallback reference
- Linux kernel `lib/raid6/` — multi-architecture RAID-6 driver
- Gueron, S. "Intel Carry-Less Multiplication Instruction and its Usage for Computing the GCM Mode" — Intel white paper, 2014
- Kounavis & Berry, "A Systematic Approach to Building High Performance Software-based CRC Generators" — Intel, 2008
- Käsper & Schwabe, "Faster and Timing-Attack Resistant AES-GCM" — CHES 2009 (bitsliced AES reference for software fallback)
- HQC submission package, NIST PQC Round 4 — reference implementations of polynomial multiplication

### Existing accelerated implementations to study
- Linux kernel `arch/x86/crypto/crc32c-pcl-intel-asm_64.S` — PCLMULQDQ-based CRC-32C
- Linux kernel `arch/arm64/crypto/aes-glue.c` — ARMv8 crypto extension integration
- OpenSSL `crypto/modes/asm/ghash-x86_64.pl` — GHASH via PCLMULQDQ
