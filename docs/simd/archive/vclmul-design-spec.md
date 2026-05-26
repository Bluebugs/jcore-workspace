> **Superseded.** This document was consolidated into `../spec.md` / `../hardware-impl.md` / `../software-impl.md` on 2026-05-25. Kept for historical reference.

# VCLMUL and VCRC32C: Galois Field Arithmetic Extension for jcore SIMD

**Document status:** Draft v0.1
**Audience:** Architecture review, all downstream implementers
**Depends on:** jcore SIMD specification (prefix-declared lanes, swizzle, widening multiply, predicate masks)

---

## 1. Introduction

### 1.1 Scope

This document specifies two SIMD instructions that extend the jcore SIMD framework with Galois field GF(2) arithmetic primitives:

- **VCLMUL.D** — 64×64 → 128-bit polynomial multiplication over GF(2)
- **VCRC32C.B** — CRC-32C folding step using Castagnoli polynomial

Both instructions live in the existing SIMD execution pipeline, require no new architectural state, and inherit operating mode (horizontal/vertical, lane width, predicate mask) from the surrounding SIMD prefix.

### 1.2 Motivation

GF(2) arithmetic is the underlying mathematical primitive for a wide range of workloads beyond cryptography. Adding these instructions accelerates:

| Domain | Workloads |
|---|---|
| Storage | RAID-6 P/Q syndrome (Reed-Solomon), btrfs/ext4/ZFS metadata checksums, NVMe-oF data digests |
| Networking | iSCSI digest, SCTP CRC, RoCEv2, RDMA, TCP offload |
| Cryptography | AES-GCM (GHASH), ChaCha20-Poly1305 alternative, SHA-3 absorption |
| Forward error correction | Reed-Solomon (DVB-S2, CCSDS spacecraft, QR codes, optical discs) |
| Post-quantum | HQC code-based KEM (NIST FIPS in progress) |
| Compression | gzip / zlib / xz CRC variants via CLMUL folding |
| Hashing | CLHASH and Carter-Wegman family |

The framing matters: these are arithmetic primitives, not crypto accelerators. They belong in the same chapter of the ISA reference as widening multiply, not in a siloed crypto appendix.

### 1.3 Design principles

1. **Reuse the SIMD prefix framework.** No new prefix bits, no new execution mode.
2. **Reuse the widening multiplier datapath.** The GF(2) multiplier is the existing integer widening multiplier with carry-chain gated to XOR mode.
3. **Minimal opcode commitment.** Two new opcodes in the SIMD opcode space.
4. **Width-locked decoding.** Each instruction is only legal under a specific prefix configuration; the decoder raises illegal-instruction on other modes rather than requiring redundant width bits in the instruction word.
5. **Patent-clean encoding.** Operand format, half-selection mechanism, and accumulator placement are independent of Intel PCLMULQDQ and Intel CRC32 encodings.

---

## 2. Relationship to the existing SIMD framework

These instructions assume the following capabilities already exist in the jcore SIMD specification:

- **Prefix instructions** that declare horizontal-reduce vs vertical-SIMD mode, lane width (8/16/32/64), and a count N (1..8) of following SIMD instructions.
- **128-bit SIMD register file** on J32; 128-bit baseline or 256-bit performance tier on J64. Vector-length agnostic — the same binary runs on either width with throughput proportional to width.
- **Swizzle (immediate)** covering byte-permute and rotate operations across the full register width.
- **Widening multiply** with low and high result halves accessible.
- **Predicate mask register** designated by the prefix, with per-lane mask bits routed to SIMD ALU inputs.

No changes to any of these are required. VCLMUL and VCRC32C are pure additions to the SIMD opcode space.

---

## 3. VCLMUL.D — Carryless Multiply, Doubleword

### 3.1 Mnemonic and operand form

```
vclmul.d  vd, vs
```

Two-operand form following SH-2 convention. Destination doubles as first source operand:

```
vd = vd ⊗ vs   (GF(2)[x] polynomial product, low 64 bits of each)
```

Programmers wanting non-destructive 3-operand semantics issue `mov vsrc1, vd` first; this matches all other SH-2 ALU operations.

### 3.2 Required prefix mode

VCLMUL.D is legal only under a vertical-SIMD prefix declaring **64-bit lane width**. The decoder raises **illegal-instruction trap** under any of:

- Horizontal-reduce prefix
- Lane width ≠ 64 bits
- No active prefix (scalar mode)

This mode-locking removes the need for an explicit width bit in the instruction word and ensures programmers cannot mistakenly issue VCLMUL at the wrong lane width.

### 3.3 Semantics

For each 128-bit register slot active in the prefix N count:

```
a = vd[63:0]                      ; low 64 bits of destination as polynomial
b = vs[63:0]                      ; low 64 bits of source as polynomial
result[127:0] = a ⊗ b              ; GF(2)[x] product

if mask_bit_active for this slot:
    vd[127:0] = result[127:0]
else:
    vd unchanged
```

GF(2) multiplication is defined as:

```
(a ⊗ b)[k] = XOR over i+j=k of (a[i] AND b[j])
```

equivalently, polynomial multiplication where coefficient addition is XOR (no carries propagate).

### 3.4 Half selection

Selection of which 64-bit half of a wider register participates in the multiply is performed by **prior swizzle**, not by an immediate field in VCLMUL itself.

Rationale: PCLMULQDQ-style 2-bit immediate (selecting low/high of each operand) consumes opcode space for a function the swizzle network already performs. Cost of using swizzle: one extra instruction when non-low halves are needed. Most CLMUL chains (AES-GCM GHASH, CRC folding) reuse the same halves across many iterations, making the swizzle hoistable out of the loop.

This is the primary encoding difference between jcore VCLMUL.D and PCLMULQDQ.

### 3.5 Behavior at wider register widths

On J64 with 256-bit physical SIMD registers: the prefix's N count and the hardware width together determine how many parallel CLMULs issue. With prefix declaring N=4 and a 256-bit datapath, the instruction issues 8 CLMULs (2 per 128-bit lane × 4 instruction count). This is transparent to software written in vector-length-agnostic form.

### 3.6 Exception model

| Condition | Behavior |
|---|---|
| Wrong prefix mode (horizontal, or width ≠ 64) | Illegal-instruction trap |
| No active prefix | Illegal-instruction trap |
| Predicate mask zero for a slot | Slot result not written; no other side effect |
| Arithmetic overflow | Not possible — GF(2) multiply is a total function |
| Operand availability stall | Pipeline stall, no exception |

### 3.7 Encoding

Issued as one of the N following instructions after a vertical-SIMD prefix. Encoding is two-operand SH-2 form:

```
  15  14  13  12  11  10   9   8   7   6   5   4   3   2   1   0
+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
|   OP4    |     vd      |     vs      |        SUB-OP           |
+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
```

- `OP4` (4 bits): primary opcode group in the SIMD opcode map (TBD — depends on existing SIMD spec assignments)
- `vd` (4 bits): destination / first source SIMD register
- `vs` (4 bits): second source SIMD register
- `SUB-OP` (4 bits): identifies VCLMUL.D within the group

Exact bit assignments deferred to the consolidated SIMD opcode map.

---

## 4. VCRC32C.B — CRC-32C Folding Step, Byte Lane

### 4.1 Mnemonic and operand form

```
vcrc32c.b  vd, vs
```

Two-operand form. The CRC accumulator lives in the low 32 bits of `vd`; data bytes come from `vs`:

```
vd[31:0]  = crc32c_fold(vd[31:0], vs, mask)
vd[127:32] = unchanged
```

The upper 96 bits of `vd` are preserved so software may park unrelated state alongside the accumulator, or use the upper lanes for parallel CRC streams in future extensions.

### 4.2 Required prefix mode

VCRC32C.B is legal only under a **horizontal-reduce prefix** declaring **8-bit lane width**. Illegal-instruction trap otherwise.

### 4.3 Semantics

```
crc = vd[31:0]
for i in 0..15:
    if mask[i] == 1:
        crc = (crc >> 8) ^ TABLE_C[(crc ^ vs.byte[i]) & 0xFF]
vd[31:0] = crc
```

where `TABLE_C` is the standard 256-entry CRC-32C table for polynomial 0x1EDC6F41 (Castagnoli, reversed: 0x82F63B78).

The reference implementation uses a table because it is canonical. Hardware implementation is free to use any equivalent computation (LFSR, CLMUL folding) provided the final accumulator value matches.

### 4.4 Polynomial

Fixed: **Castagnoli, 0x1EDC6F41** (normal form), 0x82F63B78 (reversed/reflected form).

Rationale: CRC-32C is the polynomial used by iSCSI, SCTP, btrfs, ZFS, NVMe, RoCEv2, snappy, and most modern network/storage checksums. CRC-32-IEEE (0x04C11DB7, used by Ethernet FCS / gzip / PNG / Zip) remains available via software CLMUL folding with appropriate constants — at one instruction per 16 bytes, the CLMUL-based path is competitive with a dedicated CRC32-IEEE instruction.

### 4.5 Initial value and final XOR

CRC-32C convention specifies XOR-with-0xFFFFFFFF at both input and output. This is **software's responsibility**. The full sequence:

```asm
    ; Initialize accumulator
    mov     #-1, r0                  ; 0xFFFFFFFF
    movl    r0, @-r15
    fmov.s  @r15+, vd_low            ; load into vd[31:0]
                                     ; (or whatever the GPR↔SIMD path is)

    ; Process buffer (see Software Implementation Guide)
    ; ...

    ; Finalize
    fmov.s  vd_low, @-r15
    movl    @r15+, r0
    not     r0, r0                   ; final XOR with 0xFFFFFFFF
```

Hardware init/final XOR was considered and rejected: it adds mode bits, complicates pipelining of multiple CRC streams, and saves only 2-3 instructions of negligible overhead.

### 4.6 Predicate behavior

The prefix-designated mask register selects which bytes participate in the fold. Bytes with mask=0 are skipped (no state update for that byte).

Primary use case: **end-of-buffer tail handling**. Every CRC library today has a slow scalar epilogue handling the final 0..15 bytes; predicated VCRC32C.B collapses that into one instruction with the appropriate tail mask.

### 4.7 Exception model

| Condition | Behavior |
|---|---|
| Wrong prefix mode (vertical, or width ≠ 8-bit) | Illegal-instruction trap |
| No active prefix | Illegal-instruction trap |
| All mask bits zero | No state change, no exception |
| Mid-instruction interrupt | Implementation may complete or restart; architectural state is the per-byte boundary |

### 4.8 Encoding

Same two-operand SH-2 form as VCLMUL.D, distinguished by SUB-OP field. Exact bits TBD.

---

## 5. Use case mappings

Each use case below is fully elaborated in the Software Implementation Guide.

### 5.1 AES-GCM (GHASH)

GHASH is multiplication in GF(2^128) modulo x^128 + x^7 + x^2 + x + 1. Implementation uses Karatsuba decomposition of the 128×128 multiply into three VCLMUL.D operations plus combining XORs, then Montgomery-style reduction using two more VCLMUL.D operations against the reduction polynomial. Total: ~5 VCLMUL.D per 16-byte GHASH block.

### 5.2 CRC32C tight loop

16 bytes per VCLMUL.D using polynomial folding constants, with VCRC32C.B handling tail. Expected throughput: ~1 byte per cycle on Tier B implementation.

### 5.3 RAID-6 Reed-Solomon syndrome

P syndrome is plain XOR (no GF multiply needed). Q syndrome is GF(2^8) multiplication of each data byte by a power-of-α constant, accumulated by XOR. VCLMUL.D performs 16 GF(2^8) multiplies per instruction (low byte of each operand pair) using packed 8-bit-in-64-bit layout.

### 5.4 HQC post-quantum

Hot path is multiplication of polynomials of degree ~17,000+ over GF(2). Schoolbook with VCLMUL.D gives ~O(n²/64) cycles; Karatsuba on top gives O(n^log2(3)/64). Expected speedup over pure software: 30-50×.

### 5.5 Reed-Solomon FEC

Same Q-syndrome pattern as RAID-6 with different field generators. DVB-S2 uses GF(2^8) with primitive polynomial 0x11D; CCSDS uses 0x187. Both decompose to VCLMUL.D operations.

---

## 6. Patent and IP considerations

### 6.1 Underlying mathematics

GF(2) polynomial arithmetic predates computing (Galois, 1830s). CRC as an error-detection technique was published by Peterson and Brown in 1961. LFSR hardware CRC implementations have been in every Ethernet controller since the original 10Base-5 chips (1980s). The Castagnoli polynomial was published in 1993 without any patent claim. None of these primitives carry patent risk.

### 6.2 Relevant active patents

- **US7590930** (Intel, filed 2005): covers "an instruction to perform carry-less multiplication and an instruction to perform a bit reflection operation." 20-year term expires 2025; effectively expired at time of writing.
- **US8977943** (AMD, filed 2012): covers "implementation of CRC32 using carryless multiplier." Expires ~2032.

### 6.3 Design choices that maintain clearance

- **Two-operand encoding** (vd ← vd ⊗ vs) differs structurally from Intel's three-operand PCLMULQDQ with immediate.
- **Swizzle-based half-selection** is mechanically distinct from PCLMULQDQ's 2-bit immediate selector.
- **Accumulator in SIMD register file low 32 bits** differs from Intel CRC32 (which uses GPRs) and from AMD's specific patent claims.
- **Width-locked decoding via prefix** is a unique jcore mechanism not present in x86 encodings.
- **Polynomial fixed to Castagnoli** with software handling of CRC32-IEEE via CLMUL folding sidesteps Intel CRC32 instruction patent claims entirely.

The design is in clean independent-development territory.

---

## 7. Compatibility and migration

### 7.1 Forward compatibility

- Future width extension (e.g., VCLMUL.W for 32×32 → 64 packed) can reuse the prefix's 32-bit width binding without breaking VCLMUL.D.
- Future vertical-parallel CRC (multi-stream) can reuse VCRC32C.B's encoding under a vertical-SIMD prefix variant.

### 7.2 Backward compatibility

- No existing scalar SH-2 or J-extension instruction is modified.
- No existing SIMD instruction is modified.
- Two new opcode points consumed in the SIMD opcode space.

### 7.3 Implementation tier compatibility

The architectural specification is independent of implementation tier (combinational, Karatsuba-pipelined, or iterative). Software written against this specification runs unchanged on all three tiers; only throughput varies.

---

## 8. Open questions

1. **Exact opcode bit assignments** depend on the consolidated jcore SIMD opcode map. Resolve in coordination with existing SIMD spec maintainer.
2. **Multi-cycle CLMUL stalls under prefix N=8**: should the architecture document an effective latency, or hide it behind pipeline stalls? Implementation Guide recommends "hide via stalls" for software simplicity.
3. **GPR↔SIMD register move for CRC initial value**: depends on existing SIMD framework's scalar-to-SIMD path. Document the canonical sequence once the underlying mechanism is fixed.

---

## 9. References

### Standards
- ISO/IEC 9899 (C) and ISO/IEC 14882 (C++) — for intrinsic naming conventions
- IETF RFC 3720 — iSCSI (CRC-32C test vectors)
- IETF RFC 4960 — SCTP (CRC-32C)
- NIST FIPS 197 — AES (used by AES-GCM, the largest VCLMUL.D consumer)
- NIST FIPS 800-38D — Galois/Counter Mode (GHASH specification)

### Academic
- Peterson, W.W. and Brown, D.T., "Cyclic Codes for Error Detection," Proc. IRE, 1961.
- Castagnoli, G., Brauer, S., Herrmann, M., "Optimization of Cyclic Redundancy-Check Codes with 24 and 32 Parity Bits," IEEE Trans. Communications, 1993.
- Gueron, S. and Kounavis, M., "Efficient Implementation of the Galois Counter Mode Using a Carry-Less Multiplier and a Fast Reduction Algorithm," IPL, 2009.
- Plank, J.S., "A Tutorial on Reed-Solomon Coding for Fault-Tolerance in RAID-like Systems," Software Practice and Experience, 1997.

### Related ISA documentation
- jcore SIMD specification v[TBD] — prefix encoding, swizzle, widening multiply, predicate masks
- RISC-V Cryptography Extensions Vol I (informative — used as design reference for instruction shape, not for direct encoding)
- ARM Architecture Reference Manual, NEON crypto extensions chapter (informative)
