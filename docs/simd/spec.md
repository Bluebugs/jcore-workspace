# J-Core SIMD Extension — Architectural Specification

**Status:** Consolidated draft (replaces v0.5, v0.6, and the VCLMUL design spec on 2026-05-25). **Revised 2026-07-17:** vector width is now **VLEN = 8 × XLEN** (256-bit on J32, 512-bit on J64), predicate-driven — see §1.2. The normative sections, the §8 worked examples, and the companion [hardware-impl.md](hardware-impl.md) / [software-impl.md](software-impl.md) are all converted to VLEN-relative form. Remaining literal 128-bit/16-byte figures denote genuinely width-independent quantities (the 64×64→128-bit CLMUL, the GF(2^128) GHASH field, the 16-byte AES block) or are governed by the §1.2 legacy-figure rule.
**Audience:** Architecture review, RTL implementers, toolchain and library authors.
**Companion documents:** [hardware-impl.md](hardware-impl.md), [software-impl.md](software-impl.md).
**Glossary:** see [../glossary.md](../glossary.md) for product names (J2, J32, J32-OOO, J32-FM, J64), threading terminology (FGMT), prior-art policy, and the J-Core "Tier 0/1/1.5" service-tier vocabulary (which is *not* the SIMD tier numbering below — service tiers and SIMD tiers are independent axes).

---

## 1. Overview

This document is the single source of truth for the J-Core SIMD instruction-set architecture. It supersedes the previous five SIMD documents in [archive/](archive/). All SIMD-related architectural decisions and instruction encodings reside here; hardware-implementation guidance lives in [hardware-impl.md](hardware-impl.md) and toolchain / kernel / library guidance lives in [software-impl.md](software-impl.md).

### 1.1 Tier structure

The SIMD ISA is organised in four tiers. Each tier is additive on the previous and gated by an implementation-defined feature bit (see §16). Every instruction in this specification carries a tier tag (T0, T1, T2, T3).

- **Tier 0 — Core VLEN-wide SIMD** (256-bit on J32, 512-bit on J64; §1.2) (formerly spec v0.5). Dedicated V0..V15 register file, SIMDV/SIMDH prefixes, swizzle, vertical and horizontal modes, governed SH-2 integer and SH-4 FPU operations, vector load/store/gather/scatter, exception model, P0 predicate, VCSR control register. **Mandatory** baseline for any J-Core product that implements SIMD.
- **Tier 1 — Integer/saturation extensions** (formerly spec v0.6). SIMDV `rrr` saturation field (SIMDVS, SIMDVU), VABS, VPOPCNT, VUNPK4 family, VABSDIFF, VPACK family, VMULSU. Strictly additive on Tier 0. **Optional but recommended** for INT8/INT4 quantized inference, video/SAD, bioinformatics, database analytics, signal processing. Tier 0 binaries execute unchanged on a Tier 0+1 implementation.
- **Tier 2 — GF(2) crypto extensions** (formerly vclmul-design-spec). VCLMUL.D and VCRC32C.B. Strictly additive on Tier 0; **does not depend on Tier 1**. Optional; targets CRC32C, AES-GCM (GHASH), RAID-6, Reed-Solomon FEC, HQC post-quantum, gzip/zlib CRC folding. Tier 0 binaries execute unchanged on a Tier 0+2 implementation.
- **Tier 3 — width growth beyond 8 × XLEN** (architecturally reserved, not specified). The native vector width is now VLEN = 8 × XLEN (256-bit on J32, 512-bit on J64; §1.2), so 256-bit is the J32 *baseline*, not a Tier-3 feature. Tier 3 is redefined as the reserved space for any facility that grows the vector width **beyond** the predicate-driven VLEN — e.g. a J64 implementation electing 1024-bit registers with a widened or multi-register predicate, or AVX-style multi-VLEN opcodes. Tiers 0/1/2 are exactly VLEN-wide (see §1.2). Tier 3 has no instructions defined in this revision.

J-Core product points and their tier coverage are listed in [../glossary.md §3](../glossary.md):

| Product   | SIMD tiers |
|-----------|------------|
| J2, J2-MT2x2, J3 | none |
| J32        | Tier 0+1 (VLEN 256) |
| J32-OOO    | Tier 0+1 (VLEN 256) |
| J32-FM     | Tier 0+1+2 (VLEN 256) |
| J64        | Tier 0+1+2 (VLEN 512); Tier 3 optional, yet to be specified |

### 1.2 Register-width discipline (VLEN = 8 × XLEN)

**The SIMD vector length tracks the integer register width.** The predicate
register P0 is a jcore **integer** register holding one mask bit per byte-lane
(§2.5), so the number of byte-lanes — and therefore the vector width — is fixed by
the core's integer width XLEN:

> **VLEN = 8 × XLEN**, and **P0 width = XLEN** (one bit per byte-lane).

| Core | XLEN | P0 width | Byte-lanes | **VLEN** |
|---|---|---|---|---|
| **J32** (32-bit) | 32 | 32 bits | 32 | **256 bits** |
| **J64** (64-bit) | 64 | 64 bits | 64 | **512 bits** |

VLEN is fixed across the V register file, all governed instructions, all
memory-access addressing, and all reduction destinations *for a given core*. A
binary is therefore VLEN-specific in the same way it is XLEN-specific: J32 SIMD
binaries assume 256-bit V registers, J64 binaries assume 512-bit. Software that
must run on both discovers VLEN the same way it discovers XLEN (compile-time
target, or the feature register / HWCAP at runtime — [software-impl.md §4](software-impl.md)).

**Rationale.** Binding VLEN to the predicate-GPR width keeps the mask a single
architectural integer register (no multi-register predicate, no predicate spill),
makes lane count and byte-mask width identical by construction, and lets the same
ISA text describe both cores by parameter. Prior art for width = a multiple of the
scalar/predicate width: Cray-1 (1976, VL/VM sized to the vector registers),
Intel MMX (1996, 64-bit = the integer register width of the era on the x87 file),
AltiVec (1996, 128-bit dedicated file). The earlier "128-bit mandatory / 256-bit
= Tier 3, J64-only" framing is **withdrawn**: 256-bit is simply the J32 point of
VLEN = 8 × XLEN, and 512-bit is the J64 point. Tier 3's role is redefined in §1.1.

> **Legacy-figure rule (normative).** Passages and worked examples in this
> document that still show concrete **128-bit / 16-lane / 16-byte** figures are
> *legacy illustrations at VLEN = 128*; read every such concrete count as scaling
> by **VLEN/128** (× 2 on J32, × 4 on J64) and every "16 bytes" as **VLEN/8
> bytes**. These sites are being converted to VLEN-relative form in a follow-up
> editorial pass; the normative width is VLEN = 8 × XLEN as defined here.

### 1.3 Design goals (Tier 0)

1. **Real SIMD ISA, not a DSP extension.** Tier 0 positions J-Core SIMD for applications-class workloads — autovectorisation targets, video/audio processing, light ML inference. The dedicated register file is the principal cost.
2. **Preserve SH-2 code density.** All new instructions remain 16 bits. The prefix is amortised across up to 4 governed instructions.
3. **Bounded pipeline complexity.** Single-issue in-order implementations require one new decode-stage shadow latch. SIMD prefix state is not saved on exception (atomic blocks, §6.1); the V0..V15 register file, P0, and VCSR are architectural and saved per normal context-switch rules.
4. **Reuse the existing ALU and FPU datapath** for SIMD compute. Only the register file is new.
5. **Forward compatibility.** Reserved opcode space inside SIMD blocks provides ample budget for Tier 1, Tier 2, and beyond.

### 1.4 Non-goals

- Out-of-order execution friendliness for the prefix-modal mechanism in its raw form. J32-OOO ([../ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md)) cracks the prefix and its governed group into a single internal micro-operation at decode time. The architecture is binary-compatible across in-order and OoO implementations.
- Variable-length vectors.
- Multiple predicate registers. Tier 0 specifies a single P0 register.
- Native FP8 / FP4 / bfloat16. See Appendix F.

---

## 2. Architectural Model (Tier 0)

### 2.1 SIMD register file

The SIMD register file is **dedicated**: 16 architectural registers V0..V15, each **VLEN bits wide** (256 on J32, 512 on J64; §1.2), physically separate from the SH-4 scalar FPU register file (FR0..FR15 and XF0..XF15). Total new V-file state: **16 × VLEN = 4096 bits on J32, 8192 bits on J64**.

```
                        J32: VLEN = 256 bits        J64: VLEN = 512 bits
V0 .. V15  (16 registers, each VLEN bits wide)
   V-file total = 16 × VLEN = 4096 bits (512 B) J32 / 8192 bits (1024 B) J64
```

V0..V15 are named in SIMD context by reinterpreting the SH instruction's 4-bit register field (`nnnn` or `mmmm`) as a direct vector index 0..15. There is no multiple-of-4 constraint, and `FPSCR.FR` has no effect on SIMD register naming.

V0..V15 are saved and restored on context switch by the operating system, using the dedicated vector load/store instructions VLD.Q and VST.Q (§5.6). The OS-visible context grows by the V file (16 × VLEN/8 bytes = **512 B on J32, 1024 B on J64**), plus P0 (XLEN/8 = 4 B J32 / 8 B J64) and VCSR (4 B) — total **520 bytes per task on J32, 1036 bytes on J64**. **Save and restore are lazy when SR.VD is supported (§2.6)** — the OS sets SR.VD=1 on context-out and lets the SIMD-disabled trap drive the actual save/restore on first use, eliminating that cost for tasks that never touch SIMD.

**FP scalar results target the SH-4 FPU register file (FR / DR).** A SIMD operation that produces an FP scalar — a horizontal FP reduction (§2.3), `VFIPR`, or `VFTRV` ([gpu/simd-gpu-spec.md](gpu/simd-gpu-spec.md)) — writes its result **directly into an FR (single) or DR (double) register**, exactly as integer reductions write MACL/MACH. There is **no dedicated SIMD-side FP scalar register**; the earlier VFPUL design was retired (see the §2.6 rationale and Appendix B) once the result was written at block exit, which makes it a clean instruction-boundary event rather than a mid-block FPU write. This choice also reproduces SH-4 register semantics for the promoted geometry ops (`VFIPR`→FR0 like SH-4 FIPR, `VFTRV`→FV0 = FR0..FR3 like SH-4 FTRV) and reuses the FPU's existing FTRV/FIPR 4-wide writeback port.

**Relationship to scalar FPU.** FR0..FR15 (front bank) and XF0..XF15 (back bank) are the SH-4 scalar FPU registers, unchanged from SH-4, used by ordinary SH-4 FPU instructions. SH-4 FIPR and FTRV still exist as scalar-FPU instructions operating on FR quartets; the follow-up extension [gpu/simd-gpu-spec.md](gpu/simd-gpu-spec.md) additionally promotes their function into the V-file (segmented horizontal reductions reusing the SWIZZLE crossbar + horizontal add tree) whose **FP scalar results land in FR/DR**. **Integer** SIMD compute is register-file-disjoint from the FPU: no integer SIMD instruction reads or writes FR/DR/FPUL/`FPSCR`. **FP** SIMD is not disjoint from it, in three separate ways, and all three require FPU ownership (`SR.FD = 0`) under §2.4.1: (i) the FP-scalar writeback of a horizontal FP reduction / `VFIPR` / `VFTRV`, which commits to FR/DR at block exit; (ii) `VEXTF.L` / `VINSF.L`, which read and write `FRn` directly (§5.7); and (iii) **every** governed FP operation (§5.2), which reads `FPSCR.RM` and, under `VCSR.IEE = 1`, writes `FPSCR.FLAG` (§2.4) — including in a purely **vertical** block that writes no FR/DR at all.

> **This sentence used to claim that (i) was the only one.** It read: *"SIMD compute is otherwise register-file-disjoint from the FPU: no SIMD instruction reads or writes FR/DR/FPUL/FPSCR **except** the FP-scalar writeback of a horizontal FP reduction / VFIPR / VFTRV, which commits to FR/DR at block exit and requires FPU ownership (SR.FD = 0)…"*. That was false against §2.4 and against §5.7, both in this document, and the ownership requirement it carried reached only the writeback path. Corrected by Wave-3 task **C1c**; the rule, and what the omission cost, are §2.4.1.

Integer SIMD never touches the FPU. See [../fpu/spec.md](../fpu/spec.md) for the FPU's own tier structure. Implementations that omit the FPU entirely (e.g. J2) also omit Tier 0 SIMD, since FP scalar results have nowhere to land and meaningful SIMD-FP workloads need round-trippable scalar values.

**Data movement between scalar FPU and SIMD.** Two-instruction sequences `VLNS`+`VEXTF.L` / `VLNS`+`VINSF.L` and the integer variants `VEXT.B/W/L/Q` and `VINS.B/W/L/Q` (§5.7) move single lane values between a scalar register (`FRn` for FP, `Rn` for integer) and a specified lane of a Vn register. For wider transfers, software stages data through memory using VLD/VST and FMOV.S / MOV.L.

### 2.2 Lane organisation

Within a VLEN-bit vector V*n* (VLEN = 256 on J32, 512 on J64), lanes are numbered from the low-order end:

The number of lanes at width *w* is **VLEN/w**:

| Lane width *w* | Lanes = VLEN/w (**J32**, VLEN 256) | Lanes (**J64**, VLEN 512) |
|---|---|---|
| 8 bits  | 32 (0..31) | 64 (0..63) |
| 16 bits | 16 (0..15) | 32 (0..31) |
| 32 bits | 8  (0..7)  | 16 (0..15) |
| 64 bits | 4  (0..3)  | 8  (0..7)  |

Lane *i* of V*n* at width *w* occupies bits `[w·i + w − 1 : w·i]` of V*n*, in little-endian lane order regardless of SH-2 endian configuration. The byte-lane count (w = 8) equals P0's width XLEN by construction (§1.2).

### 2.3 Reduction destination

Horizontal (reductive) SIMD operations write their scalar result to the appropriate **scalar bank** for the lane type: the existing SH-4 integer scalar pair (MACL/MACH) for integer reductions, and the SH-4 FPU register **FR0 (single) / DR0 (double)** for FP reductions — symmetric with the integer case, and *implied* exactly as MACL/MACH is (a plain SIMDH+FMUL reduction has no free register field, since both operand fields name V sources). The geometry instructions `VFIPR`/`VFTRV` ([gpu/simd-gpu-spec.md](gpu/simd-gpu-spec.md)) likewise use an **implied FR0 base**: a segmented FP reduction with *G* groups writes FR0..FR(G−1), so `VFIPR` (1 group) → FR0 and `VFTRV` (4 groups) → FR0..FR3 = **FV0**. This keeps the destination implicit (no register field needed — both operand fields name V sources) and symmetric with MACL/MACH; software moves FV0 to another FV afterward if required. The FP-scalar write commits at **block exit** and requires FPU ownership (`SR.FD = 0`), checked at prefix decode so any FPU-restore trap fires at a clean boundary, never mid-block (§2.6). §2.4.1 rule **S-R1** generalises that requirement to **every** FP SIMD block, vertical ones included, and rule **S-R3** states what the prefix decoder has to inspect to apply it — because §3.2's prefix does not encode whether the block is FP or integer. FR0/DR0 (scalar FPU) is a distinct file from V0 (SIMD), so a reduction reading V-register sources and writing FR0 has no register conflict. There is no dedicated SIMD-side FP scalar register (VFPUL was retired; Appendix B).

For additive reductions, the destination is **one type-class wider than the lane width** to preserve precision in long accumulation chains and prevent overflow in the common ML and DSP kernels (int8 → int32, FP16 → FP32).

| Lane width *w* | Lane type | Destination | Destination type |
|---|---|---|---|
| 8  | integer | MACL | int16 or int32 (always fits in 32 bits) |
| 16 | integer | MACL + MACH pair | int32 / int64 |
| 32 | integer | MACL + MACH pair | int64 |
| 64 | integer | MACL + MACH pair | int64 (truncates; software must guard against overflow) |
| 16 | FP (half) | **FR0** | FP32 |
| 32 | FP (single) | **FR0** | FP32 (or DR0/FP64 with widening, per operator) |
| 64 | FP (double) | **DR0** | FP64 |

The FP destination is the implied **FR0/DR0** (like MACL/MACH for integer). Segmented reductions extend this: *G* groups write FR0..FR(G−1), so `VFTRV` → FV0 (FR0..FR3). FP min/max/bitwise variants target FR0 at the input width.

Min/max/bitwise reductions (added in Tier 0) do not widen; the destination matches the input lane width (e.g., int16 min → MACL holds an int16). FP min/max use IEEE 754-2008 `minNum`/`maxNum` semantics. The add reduction is the canonical widening case.

**No V-register restrictions.** Any V register may be used as a source or destination in any SIMDH variant.

**Implicit clear at prefix decode.** When a SIMDH prefix is decoded, the reduction destination is implicitly cleared to zero: MACL and MACH are zeroed for integer-typed reductions; FR0/DR0 (and, for a *G*-group segmented reduction, FR0..FR(G−1)) is zeroed for FP-typed reductions (the FPU-ownership check has already succeeded at this point, §2.4.1). **Choosing between those two destinations needs the same information the ownership check needs**, and §3.2's prefix does not carry it: whether a reduction is integer- or FP-typed is a property of the governed opcode (§5.1 versus §5.2), not of `H`, `ww`, `rrr` or `N`. §2.4.1 rule **S-R3** states the governed-opcode scan once; this clear and that check both consume it.

**Chaining cost.** A horizontal reduction's FP result is already in an FR/DR register — no boundary move. To consume it in scalar FP code, use FRn/DRn directly. To chain into another SIMD reduction, target a different FR and combine with `FADD`. To consume it back into a SIMD vector lane, use `VINSF.L` (which now reads FRn) per §5.7. Integer reductions in MACL/MACH consume normally via `STS MACL, Rn` / `STS MACH, Rn`.

**FPU coupling for FP SIMD.** A task that issues FP horizontal reductions / VFIPR / VFTRV writes FR/DR and therefore **owns the FPU** (SR.FD = 0) — so for such tasks SIMD lazy save (SR.VD, §2.6) and FPU lazy save (SR.FD, [../fpu/spec.md §6.3](../fpu/spec.md)) are coupled. This is the honest coupling: the task is doing FP math. **§2.4.1 widens it from FP *reductions* to *all* FP SIMD**, for a reason that has nothing to do with the writeback: §2.4's `FPSCR.RM` read and `FPSCR.FLAG` write are in every FP block, vertical ones included, and a task doing them under `SR.FD = 1` is using another context's register. **Integer SIMD remains fully independent** of the FPU (its reductions go to MACL/MACH), and **FPU-only tasks** never trigger a V reduction, so their independence is preserved. The pre-VFPUL-retirement design decoupled the two universally at the cost of a dedicated register and boundary moves; the trade is recorded in Appendix B.

**FPU register file required for FP SIMD.** FP SIMD reductions write FR/DR, so implementations targeting FP Tier 0 SIMD must implement the SH-4 FPU register file (FR0..FR15, DR, FPUL, MACL, MACH) and **SR.FD** (Tier 1 FPU). This couples SIMD-enabled product points to an FPU-bearing baseline at Tier 1 minimum (J32 and up; see [../glossary.md §3](../glossary.md)). Integer-only SIMD does not require the FPU.

### 2.4 Mode bits in FPSCR and VCSR

Tier 0 introduces a dedicated SIMD control register, separating SIMD mode bits from scalar FPU state:

- **VCSR** (Vector Control and Status Register, 32 bits): dedicated SIMD control register. Bit 0 = MKE (Mask Enable); bit 1 = IEE (IEEE-strict mode). Bits 2..31 reserved for future SIMD mode bits. VCSR is preserved across exception entry/RTE and saved/restored by the OS as part of per-task context — lazily, gated by SR.VD per §2.6. Software accesses VCSR via `LDS Rm, VCSR` / `STS VCSR, Rn` or via the dedicated `VMKCHG` toggle (§5.6) — both trap under SR.VD = 1.

- **VCSR.MKE** (bit 0): when set, governed SIMD operations apply P0 as a per-lane enable mask (§4.3, §4.4). When clear (default), all lanes are active. MKE has architectural effect only inside SIMD blocks — its value is read at governed-instruction decode.

- **VCSR.IEE** (bit 1, IEEE-strict mode): when set, governed FP operations follow IEEE 754 semantics for denormals and update FPSCR.FLAG bits OR-accumulated across lanes. When clear (default), governed FP operations flush denormals to zero and do not update FPSCR.FLAG. **In neither mode do SIMD FP operations deliver traps** — see §6.3 for the full FP exception model in SIMD context.

Existing SH-4 FPSCR fields apply unchanged to scalar FPU code. For FP governed SIMD instructions, only some FPSCR fields apply:

- `FPSCR.FR` (bank) affects only scalar FPU operations, not SIMD register addressing.
- `FPSCR.PR` (precision) is overridden inside a SIMD block by the prefix's width field; the architectural FPSCR value is not modified.
- `FPSCR.SZ` (transfer size) is overridden similarly.
- `FPSCR.RM[1:0]` (rounding mode) applies normally to FP governed instructions (both modes of VCSR.IEE).
- `FPSCR.EN` (exception enable) bits are **ignored** by SIMD FP operations regardless of VCSR.IEE. SIMD never traps on FP exceptions.
- `FPSCR.CAUSE` bits are **not set** by SIMD FP operations.
- `FPSCR.FLAG` bits are updated only when VCSR.IEE = 1, OR-accumulated across lanes.

**Every field above belongs to the FPU, so a block that reads or writes one must own the FPU.**
That requirement is §2.4.1, added by Wave-3 task **C1c**. It is what makes the four bullets safe:
without it, the `FPSCR.RM` read and the `FPSCR.FLAG` write of a purely **vertical** FP block reach
the register file of whichever context currently owns the FPU, which under the lazy pattern of §2.6
and [../fpu/spec.md §7.3](../fpu/spec.md) is a different one.

**Naming rationale.** The placement of the mask-enable bit in a dedicated VCSR (rather than in FPSCR) follows the Cray-1 model (1976) of a dedicated vector-control register (VL) separate from the scalar status register. The IEE bit is directly modelled on PowerPC AltiVec's "Java mode" bit in VSCR (1996).

### 2.4.1 FPU ownership for SIMD FP operations (normative)

**Wave-3 task C1c**, from [../j4-remediation-plan.md §C1](../j4-remediation-plan.md)'s
"vertical FP SIMD ownership hole", argued against
[../security/threat-model.md §8](../security/threat-model.md)'s bar item **L3**.

*It is here and not in `../decisions/`* on [../decisions/README.md](../decisions/README.md)'s
rule that a decision goes inline when a spec owns the thing decided. What is decided here is
**which SIMD instructions require the FPU**, and that is a property of the SIMD decode rules,
which this document owns. The `FPSCR` fields themselves are
[../fpu/spec.md §6.4](../fpu/spec.md)'s and are not restated. The one consequence that lands on
`FPDS` is stated by [../fpu/spec.md §7.7](../fpu/spec.md), because it owns that bit.

#### The defect

§2.4 makes **every** governed FP operation a reader of `FPSCR.RM` — in both modes of `VCSR.IEE`,
explicitly — and, under `VCSR.IEE = 1`, a writer of `FPSCR.FLAG`, OR-accumulated across lanes.
§2.1, §2.3, §2.6 and §5.8 all attached the FPU-ownership requirement to the **FP-scalar writeback**
of a horizontal FP reduction / `VFIPR` / `VFTRV`, and to nothing else. A purely **vertical** FP
block writes no FR/DR, so it satisfied every ownership rule this document had while reading and
writing `FPSCR` with `SR.FD = 1`.

**That is an escape from a no-escape rule.** [../fpu/spec.md §6.3](../fpu/spec.md) says `SR.FD`
disables the FPU end-to-end, listing `LDS` / `STS` involving `FPUL` or `FPSCR` among the
instructions that trap and stating there is no control-only escape. A vertical FP SIMD block was
one: it read and wrote `FPSCR` under `SR.FD = 1`, which `LDS Rm,FPSCR` and `STS FPSCR,Rn` cannot.

**Three consequences, and the security one is the smallest.**

1. **The rounding mode is somebody else's.** Under `SR.FD = 1` the live `FPSCR` belongs to the
   **parked FPU owner**, which under the lazy pattern of §2.6 and
   [../fpu/spec.md §7.3](../fpu/spec.md) is a different context. §2.4 says `FPSCR.RM` "applies
   normally", so a vertical FP block's results depended on which context last owned the FPU — a
   schedule-dependent answer to a deterministic computation, and one an autovectoriser must
   not produce, since the scalar loop it replaced rounds by the mode its own task installed.
   **This is a wrong answer before it is a leak, and it would need fixing with no adversary in the
   model at all.**
2. **Sticky-flag corruption, in both directions.** `FPSCR.FLAG` is sticky and is cleared only by a
   software write ([../fpu/spec.md §6.4](../fpu/spec.md)). A vertical block OR-accumulated its lane
   exceptions into the parked owner's live `FPSCR`, from which the owner's next lazy save copies
   them into the owner's image. The running task's own flags landed in a register it cannot read —
   `STS FPSCR,Rn` traps under `SR.FD = 1` — and the parked owner read flags it never raised.
   Inside one guest that is a data-dependent channel between two tasks that share nothing else,
   and it is a correctness defect in both directions before it is a channel in one.
3. **A dirty bit that can lie in the unsafe direction.** [../fpu/spec.md §7.7](../fpu/spec.md) rule
   **FP-R4** ([../fpu/spec.md §7.7](../fpu/spec.md)) sets `FPDS` = `10` on any architectural write
   to `FPSCR` from any mode. Consequence 2
   is such a write. An implementer reading §2.1 as it stood would not have wired the SIMD FP
   datapath into that logic at all, and `FPDS` ([../fpu/spec.md §7.7](../fpu/spec.md)) would have
   read CLEAN over a file the SIMD unit had
   modified. What that loses is the tenant's *own* flags at a gang switch rather than another
   tenant's secrets — FP-R3's scrub is unconditional and is not an input to
   `FPDS` ([../fpu/spec.md §7.7](../fpu/spec.md)) — but a `FPDS`
   that can be wrong in the CLEAN direction is one bit from FP-INV, which is the direction
   [../fpu/spec.md §7.7](../fpu/spec.md) chose `11` → `10` to avoid.

#### What this is **not**: a cross-tenant channel

Stated positively because the opposite reading is the natural one and it does not survive checking.
[../fpu/spec.md §7.7](../fpu/spec.md) rule **FP-R1** names `FPSCR` in the scrub value, **FP-R3**
applies it unconditionally at every ownership installation, **FP-R5** forbids the transfer
depending on the incoming tenant executing an FP instruction, and
[../hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md) item 8 carries it on the
gang-switch list. So whatever an outgoing tenant's vertical SIMD left in `FPSCR.FLAG`, the incoming
tenant reads [../fpu/spec.md §6.4](../fpu/spec.md)'s reset value. **C1b closed the cross-tenant
direction of this site before C1c looked at it**, and nothing here adds a gang-switch item, a
scrub, or a hyperprivileged bit.

The exposure is entirely **within** a tenant, on precisely the lazy path
[../fpu/spec.md §7.7](../fpu/spec.md) deliberately left in place ("within a tenant … §7.3's lazy
ABI is unchanged"). **L3's boundary is the tenant**, so this section is not what moves L3 from
`NOT MET`; see *Bar status* below.

#### The rules (normative)

**S-R1 — A SIMD block containing any FP operation requires FPU ownership.** If a block's governed
instructions include **any** §5.2 FP form — or `VFIPR` / `VFTRV`
([gpu/simd-gpu-spec.md](gpu/simd-gpu-spec.md)) — the block requires `SR.FD = 0`. With `SR.FD = 1`
the FPU-disabled exception ([../fpu/spec.md §6.3](../fpu/spec.md)) is raised against the **prefix**,
before any governed instruction of the block has had any architectural effect. Where `SR.VD` = 1 as
well, `SR.VD` wins and the retry hits `SR.FD`, unchanged from §2.6. The horizontal FP reduction,
`VFIPR`, `VFTRV` and (§5.7) `VEXTF.L` / `VINSF.L` cases are **instances** of S-R1, not a separate
rule beside it; §2.1, §2.3, §2.6, §5.7 and §5.8 now read as consequences of this one.

**S-R2 — The requirement does not consult `VCSR.IEE`, or any other mode bit.** `VCSR` is
guest-writable (§2.4); a safety property a mode bit can switch off is not a safety property —
[../fpu/spec.md §7.7](../fpu/spec.md)'s argument about `HEDR[3]`, applied one level down. The
substantive reason is that `IEE` gates only the `FPSCR.FLAG` **write**; the `FPSCR.RM` **read** is
in both modes by §2.4, so a check conditioned on `IEE = 1` would leave consequence 1 open in the
**default** mode.

**S-R3 — The check is at the prefix, and the prefix does not carry the type, so the decoder must
look at the block.** §3.2's prefix encodes `H`, `ww`, `rrr` and `N` and nothing that separates FP
from integer: FP-ness is the *governed opcode* (§5.2 versus §5.1), so `SIMDHA.L` is an FP or an
integer reduction depending on a halfword the prefix decoder has not yet examined. The block is
`N ≤ 4` contiguous halfwords whose whole fetch extent §6.5 already requires the prefix to have
validated, so the implementation **MUST** examine the `N` governed opcodes at prefix decode and
apply S-R1 if any of them is an FP form.

Deferring the check to the FP instruction itself is **not** an alternative. For `N > 1` an FP
operation may follow integer ones that have already committed lane writes, and §4.3's lane
operation `V<Rn> ← V<Rn> op V<Rm>` is not idempotent, so the restart-from-prefix of §6.4 / §6.5
would re-apply them. §6.1's optional ROB atomic-commit group makes restart idempotent for an
arbitrary block and would permit a later check on that implementation only; S-R3 is stated as a
prefix-decode requirement so that the in-order implementation, which has no such group, is the one
the rule is written for.

*The same scan is already owed elsewhere in this document.* §2.3's "implicit clear at prefix
decode" has to know whether to zero MACL/MACH or FR0/DR0, which is the identical question, and
§6.5's prefix-time block-fetch validation already reads the block's extent at the prefix. S-R3
names the scan once rather than leaving three sections to assume it independently.

**S-R4 — `FPSCR` stays in the FPU's ownership domain and in the FPU's context image.** No copy of
`FPSCR`, and no `RM` or `FLAG` shadow, is added to `VCSR` or to §2.5's SIMD image; §2.5's
architectural-state list and the 520-byte / 1036-byte image of §2.6 are unchanged by this section.
Under S-R1 a task running FP SIMD owns the FPU, so its rounding mode and its sticky flags are its
own, `LDS Rm,FPSCR` is available to it, and both travel in the
136-byte FPU image ([../fpu/spec.md §7.4](../fpu/spec.md)) as they already did. Two owners for one register is the
[../decisions/0001](../decisions/0001-one-authority-per-fact.md) failure, and it would additionally
owe a rule for which of the two images wins on restore.

**S-R5 — Integer SIMD is untouched.** S-R1 does not fire on a block whose governed instructions are
all §5.1, §5.4, §5.5 or §5.6 forms: those read and write no FPU state, and the `SR.VD` / `SR.FD`
independence §2.6 claims for integer SIMD is exactly as it was. An `FPU`-only task is likewise
unaffected. What changes is the set of tasks that must own the FPU, from *those issuing FP
reductions* to *those issuing any FP SIMD*, which is §2.3's "honest coupling" argument applied to
the case §2.3 did not cover.

#### What it costs

One `EXC_FPU_DISABLED` trap, once, for a task doing vertical FP SIMD that would previously have
taken none, plus the 136-byte FPU image ([../fpu/spec.md §7.4](../fpu/spec.md)) it must then carry. **No new architectural state, no new
instruction, no new trap cause, no new hyperprivileged bit, no change to either context image, and
no new item on [../hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)'s
gang-switch list.** The decoder cost is S-R3's `N`-opcode scan, which §2.3 and §6.5 already require
for other reasons.

The trap is not avoidable by a cheaper rule, because it is **not** what closes the hole — owning
the register is. A task that wants a rounding mode has to install one, and `LDS Rm,FPSCR` traps
under `SR.FD = 1`; a task that does not install one and is not the owner is reading a value chosen
by whoever is.

#### What was priced and rejected

- **Give the SIMD FP path its own rounding mode and sticky flags in `VCSR`.** The obvious
  decoupling — `VCSR` has 30 reserved bits, is already in the SIMD image, and is already scrubbed
  by §2.6.1's **V-R1** — and it is wrong on three counts. It would make a horizontal FP reduction,
  `VFIPR` and `VFTRV` round by a different control from scalar `FIPR` / `FTRV` **while writing the
  same `FR0` / `FV0`**, discarding the SH-4 register-semantics compatibility §2.3 and Appendix B
  bought by retiring `VFPUL`. It would make the SIMD default rounding mode differ from the scalar
  one — `VCSR` = 0 is round-to-nearest-even, and [../fpu/spec.md §6.4](../fpu/spec.md)'s `FPSCR`
  reset value is round-to-zero — so autovectorised code would silently round differently from the
  loop it replaced, which is the single thing a vectoriser must not do. And it would cost V-R1 the
  property its own text argues for: that the scrub value and the architectural default are the same
  value, with nothing for an implementer to choose between.
- **Substitute the scrub-value `FPSCR` whenever `SR.FD = 1`.** Closes the channel with no trap and
  no ownership, and makes FP results depend on `SR.FD` — supervisor state a user task cannot read.
  A silently schedule-dependent answer with no trap to notice it by is worse than the defect.
- **Duplicate `FPSCR` into the SIMD image.** Two owners of one register;
  [0001](../decisions/0001-one-authority-per-fact.md). Rejected under S-R4.
- **Ban vertical FP SIMD.** Deletes §5.2, which is the reason FP Tier 0 SIMD exists.

#### Tests

Three, and the third is the one that gets skipped. Each is red before S-R1 and green after; none
of them is a cross-tenant residue test, because §2.4.1's exposure is not cross-tenant.

| # | Test | What it shows if the rule is absent |
|---|---|---|
| 1 | Task A owns the FPU with `FPSCR.RM` = `00` (nearest-even). Task B, not the FPU owner, runs `SIMDV.L` + `FADD` on a lane pair whose exact sum is a tie. B compares its result against the same computation with `RM` = `01`. | B rounded by A's mode. Repeat with A installing `01`: B's answer changes with no change to B. |
| 2 | A owns the FPU and clears `FPSCR.FLAG`. B, not the owner, runs a vertical FP block under `VCSR.IEE = 1` in which exactly one lane overflows. A executes `STS FPSCR,Rn`. | A reads `FLAG.O` set by B's data. |
| 3 | **The default mode.** Test 1 repeated with `VCSR.IEE = 0`. | The same wrong rounding, *with test 2 green*, on any implementation whose ownership check was conditioned on `IEE` — the natural optimisation, since `IEE = 0` performs no `FPSCR` write. This is S-R2's test and it has no analogue in test 1 or 2. |

#### Bar status

**This section does not move L3.** L3's boundary is the **tenant**
([../security/threat-model.md §8](../security/threat-model.md)), the cross-tenant direction of this
site was already closed by C1b's FP-R3, and what C1c fixes is an intra-tenant correctness defect
and an intra-guest channel. L3 remains `NOT MET` for the reason C1b left it there: the five residue
tests it does require have nothing to run on.

**Implementation status: specified, not built.** There is no FPU and no SIMD unit in
`jcore-cpu@origin/master` (`e8a5a4e1`): no file whose path contains `fpu`, `simd`, `float` or
`vector`, and no `*.vhd`/`*.vhm` matching `fpscr`, `vcsr`, `sr_fd` or `simd`, all checked
case-insensitively on 2026-09-09. The three tests above are written against hardware that does not
exist, and **nothing in this section is met because it has been written.**

### 2.5 Architectural and pipeline state

Tier 0 architectural state:

- **V0..V15** (16 × VLEN = 4096 bits on J32, 8192 bits on J64).
- **P0** (XLEN bits: 16→**32 on J32**, **64 on J64**): the SIMD predicate mask register, a jcore integer register. Each bit corresponds to one lane at the narrowest width (w = 8); there are VLEN/8 = XLEN byte-lanes, so P0 is exactly XLEN bits wide. At wider widths, lane *i* is enabled by P0[*i* · (*w*/8)] — i.e., the low bit of each *(w/8)*-bit group within P0. P0 is saved and restored via dedicated `LDS Rm, P0` and `STS P0, Rn` instructions (§5.6).
- **VCSR** (32 bits, 2 bits currently defined): mode/status as in §2.4.

There is **no VFPUL**: FP scalar results land in the SH-4 FR/DR file (§2.3), which is existing SH-4 architectural state, not new SIMD state.

Total Tier 0 architectural addition versus a baseline SH-4: **4160 new architectural bits on J32** (V 4096 + P0 32 + VCSR 32), **8288 bits on J64** (V 8192 + P0 64 + VCSR 32) — an increase of roughly 8–20% of the J32 core area depending on flip-flop vs SRAM register-file implementation. SIMD context-switch image size: **520 bytes on J32** (V0..V15 = 512 + P0 = 4 + VCSR = 4), **1036 bytes on J64** (V = 1024 + P0 = 8 + VCSR = 4). FP scalar results reuse the FR/DR file, which the OS already saves as FPU context.

Tier 1 and Tier 2 add **no new architectural state**.

The prefix-modal mechanism additionally requires the following **microarchitectural state**, none of which is architecturally visible or saved on exception:

- `SIMD_VAL` (1 bit), `SIMD_CNT[1:0]`, `SIMD_W[1:0]`, `SIMD_H` (1 bit), `SIMD_RED[2:0]` (reduction operator for horizontal blocks; ignored when SIMD_H = 0), and (Tier 1) `SIMD_SAT[1:0]` (saturation modifier for vertical blocks).
- `V_LANE_VALID` (1 bit), `V_LANE_REG[3:0]`, `V_LANE_IDX[3:0]` for the VLNS+VEXT/VINS lane-select latch.

Total decode-stage shadow state: 18 bits Tier 0 + 2 bits Tier 1 saturation modifier = 20 bits, all microarchitectural.

### 2.6 SR.VD — SIMD-disable trap (Tier 0; enables lazy context switch)

A new bit in the CPU status register, **SR.VD** at **SR bit 13**, gates access to the entire SIMD facility. It is the SIMD analogue of SR.FD ([../fpu/spec.md §6.3](../fpu/spec.md)) and exists for the same reason: to let the OS skip the 520-byte (J32; 1036-byte J64) SIMD save/restore (V0..V15 + P0 + VCSR) on context switches between tasks that do not touch SIMD.

The SR layout authoritative source is [../hypervisor/hardware-spec.md §2.1](../hypervisor/hardware-spec.md); SR.VD occupies an SH-4-reserved bit slot (no compatibility break).

**Semantics.**

- `SR.VD = 0` (reset value): SIMD is enabled. All SIMD-touching instructions execute normally.
- `SR.VD = 1`: SIMD is disabled. Any SIMD-touching instruction raises a **SIMD-disabled exception** before any architectural state changes.

**Instructions that trap under SR.VD = 1** (the full set, so the OS can rely on trap-on-first-use):

| Instruction class | Examples |
|---|---|
| Prefix instructions | `SIMDV.{B,W,L,Q}`, `SIMDH<op>.{B,W,L,Q}`, the Tier 1 `rrr` saturation variants |
| Governed instructions in a SIMD block | the ordinary SH-2 / SH-4 ops that take on SIMD meaning after a prefix (§5.1, §5.2, §5.4); also the Tier 2 reinterpreted ops VCLMUL.D / VCRC32C.B (§5.5) |
| Vector memory ops | `VLD.{B,W,L,Q}`, `VST.{B,W,L,Q}`, `VGATHER.Q`, `VSCATTER.Q`, `VLDI.Q` |
| Lane bridges | `VLNS`, `VEXT.{B,W,L,Q}`, `VINS.{B,W,L,Q}`, `VEXTF.L`, `VINSF.L` |
| Mode toggles | `VMKCHG`, `SWIZZLE.I` |
| Control-register access | `LDS Rn, P0`, `STS P0, Rn`, `LDS Rn, VCSR`, `STS VCSR, Rn` |

The rule is simple: **any decode that would access V0..V15, P0, or VCSR, or that would set SIMD_VAL in the decode shadow, traps under SR.VD = 1.** There is no SIMD-control escape; SR.VD truly disables the facility end-to-end. This mirrors the FPU's no-escape rule for SR.FD and is what makes the lazy-context-switch idiom reliable. (A block containing **any** governed FP operation additionally requires `SR.FD = 0` — §2.4.1 rule **S-R1**. That check is independent of `SR.VD` and is applied at prefix decode. It is not only the FR/DR writeback of a horizontal FP reduction / VFIPR / VFTRV that needs it: §2.4's `FPSCR.RM` read is in every FP block, including a vertical one that writes no FR/DR at all.)

**Trap classification.**

- On a Tier 0 / Tier 1 / Tier 2 implementation **without** the hypervisor extension (SR.HPRIV always 0, HEDR not consulted), the trap surfaces with a new EXPEVT value. Recommended: a fresh code in the J-Core extension range. The bare-metal value is implementation-defined, with the canonical assignment `EXPEVT = 0x1C0 EXC_SIMD_DISABLED` (matches the hypervisor-aware path below so a single trap-handler entry point serves both).
- On an implementation **with** the hypervisor extension, the trap is reported with cause `EXC_SIMD_DISABLED` (EXPEVT `0x1C0`) and is subject to HEDR delegation per [../hypervisor/hardware-spec.md §2.3.1](../hypervisor/hardware-spec.md), bit 24.

**Save / restore on context switch (OS pattern).** Identical shape to the SH-4 lazy-FPU pattern, applied to SIMD state:

```
schedule_out(prev_task):
    # Do NOT save SIMD state here.
    # Just set SR.VD=1 in prev_task's saved SR; SIMD state stays
    # in the register file until someone else needs it.
    prev_task.saved_sr |= SR_VD

schedule_in(next_task):
    # next_task already has SR.VD=1 in its saved SR (either set
    # above, or set at task creation). The CPU resumes with VD=1.
    restore_SR(next_task.saved_sr)   # SR.VD=1

# Inside the SIMD-disabled trap handler:
on_simd_disabled_trap():
    if current_simd_owner == current_task:
        # Spurious — owner did not change since last touch.
        # Just clear VD and resume.
        SR.VD = 0
        return_from_exception()

    if current_simd_owner != NULL:
        save_simd_state(current_simd_owner)   # 520 bytes (J32; 1036 J64) via VST.Q × 16 + STS P0 + STS VCSR

    if current_task.has_saved_simd_state:
        restore_simd_state(current_task)      # 520 bytes (J32; 1036 J64) via VLD.Q × 16 + LDS P0 + LDS VCSR

    current_simd_owner = current_task
    SR.VD = 0
    return_from_exception()
```

Cost per context switch when neither outgoing nor incoming task touches SIMD: **zero** save/restore. Cost when both touch SIMD: one trap + one 520-byte (J32; 1036-byte J64) save + one 520-byte (J32; 1036-byte J64) restore — same total as eager save, just shifted in time. On typical Linux workloads where <5 % of processes use SIMD, this eliminates ~95 % of the save/restore overhead.

**Interaction with FGMT.** SR is per-thread on a J32-OOO/J32-FM core under FGMT ([../ooo/j32ooo-spec.md §13.1](../ooo/j32ooo-spec.md)). SR.VD is therefore naturally per-thread; one thread using SIMD does not impose save/restore overhead on the sibling thread that does not.

**Interaction with the scalar FPU.** Integer SIMD instructions write only SIMD-side state (V0..V15, P0, VCSR) and the integer MAC pair, never the FPU — so for integer SIMD the SR.VD and SR.FD lazy-save mechanisms are fully independent (own SIMD without owning FPU and vice versa). **FP** SIMD couples them for the task doing it, and §2.4.1 rule **S-R1** is where that is stated: reductions / VFIPR / VFTRV write FR/DR at block exit, *and* every governed FP operation reads `FPSCR.RM` and may write `FPSCR.FLAG` (§2.4), so a purely **vertical** FP block owns the FPU too (§2.3). Because the FP-scalar writeback happens at block exit and the FPU-ownership (SR.FD) check is applied at **prefix/block decode**, an FP-reduction instruction traps first on SR.VD if SIMD is disabled and, once SIMD is enabled, on SR.FD if the FPU is not owned — both at a clean instruction boundary. When both bits are set, **SR.VD wins** (the trap is `EXC_SIMD_DISABLED`); after the SIMD handler clears SR.VD, the retry hits SR.FD if still set, matching Linux's expectation that lazy save reports the higher-level (SIMD) extension first.

**No mid-block FPU trap.** An FP reduction produces its scalar only at block exit (§4.4), so the FR/DR writeback — and its SR.FD-ownership requirement — is an instruction-boundary event, not a mid-block one. The SR.FD check is hoisted to prefix/block decode, so if it must trap (to restore the task's FPU context) it does so **before** the block runs; the block never abandons-and-restarts for an FPU trap (§4.2 atomicity preserved). This is what makes writing FP results straight to FR/DR safe, and is why the dedicated VFPUL register and the §5.8 boundary moves it required could be retired (Appendix B).

**Hardware cost.** One SR flip-flop (the bit itself; the SR register already exists) plus the trap condition wired into SIMD decode. Across the full SIMD facility decode, the trap is a single OR of all the SIMD-touching decode signals AND'ed with `SR.VD`. Estimated 30–50 LUT4 total. Negligible.

**Hypervisor-aware lazy SIMD ABI (when the hypervisor extension is present).** Identical shape to the FPU Tier 2 lazy ABI ([../fpu/spec.md §7](../fpu/spec.md)), applied to SIMD state:

- The hypervisor maintains a per-vCPU `simd_owner` flag and a per-pCPU `current_simd_owner_vcpu` register.
- At vCPU dispatch, the hypervisor sets `SR.VD = 1` in the guest's `HSSR` shadow before `HRTE`. The guest resumes with SIMD disabled.
- First guest SIMD instruction → `EXC_SIMD_DISABLED` trap. HEDR bit 24 routing:
  - `HEDR[24] = 0` (default): trap to hypervisor. Hypervisor checks `current_simd_owner_vcpu`; if different, saves previous owner's 520-byte (J32; 1036-byte J64) SIMD image, restores this vCPU's image (if any), updates `current_simd_owner_vcpu`, clears `SR.VD = 0` in `HSSR`, `HRTE` back to the guest at the trapping instruction (which re-executes successfully).
  - `HEDR[24] = 1`: trap delegated to guest's S-mode handler. Guest OS implements its own lazy-SIMD policy for its user threads (mirror of the bare-metal pattern above).
- vCPU migration to a different pCPU: hypervisor cross-calls the source pCPU to save the 520-byte (J32; 1036-byte J64) SIMD image, ships it to the destination pCPU, sets `SR.VD = 1` in the destination `HSSR`; first SIMD touch on the destination re-installs the image.

#### Save / restore layout (520-byte SIMD image, J32). [T0]

| Offset | Bytes | Content                  |
| ------ | ----- | ------------------------ |
| 0x000  | 512   | V0..V15 (16 × 32 B)      |
| 0x200  | 4     | P0 (all 32 bits used)    |
| 0x204  | 4     | VCSR                     |
| 0x208  | —     | end (520 bytes)          |

On J64 the V file is 1024 bytes and P0 is 8 bytes, giving a
**1036-byte SIMD image**: V0..V15 at `0x000` (1024), P0 at `0x400` (8), VCSR at `0x408` (4), end
at `0x40C`. There is deliberately **no VFPUL slot** in either image — VFPUL was
retired on 2026-07-17 (§2.3, Appendix B) and FP reductions write `FR0`/`DR0`
directly; an image carrying it is describing a register that does not exist.

The same layout in prose (J32): `V0..V15` (512 bytes) + `P0` (4 bytes, all 32 bits used) + `VCSR` (4 bytes) = 520 bytes; on J64 the V file is 1024 bytes and P0 is 8 bytes → 1036 bytes. Saved via `VST.Q` × 16 + `STS P0` + `STS VCSR`; restored symmetrically. The 16 vector stores can be issued back-to-back (no inter-dependencies); a typical save/restore round-trip is ~55–70 cycles on a 2-wide OoO with the L1-D in M state (up from the 128-bit-era estimate, since each VST.Q now moves VLEN/8 bytes).

**Pre-2006 prior art.**

- **PowerPC G4 AltiVec `MSR.VEC`** (1999) — the canonical reference for an explicit SIMD-disable SR bit on a 128-bit dedicated-register-file SIMD ISA layered on an SH-4-like scalar host. Apple's Mac OS X kernel relies on it for lazy AltiVec save.
- **SH-4 `SR.FD`** (1998) — the FPU mechanism this directly mirrors.
- **Intel `CR0.TS`** (i486, 1990) — generalised to FP/MMX/SSE accesses; same trap-on-first-use idiom.
- **MIPS R4000 `Status.CU1/CU3`** (1991) — coprocessor-usable bits; same pattern for optional coprocessors.
- **PA-RISC `PSW.D`** (1986) — earliest reference for an SR-bit-gated FP facility.
- **4.4BSD lazy-FP context switch** (McKusick et al., 1996) — the OS-side pattern, identical for SIMD.
- **UltraSPARC II lazy-FP via FPRS.FEF** (1997) — the hypervisor-side cross-call pattern for vCPU migration.

### 2.6.1 Cross-tenant SIMD ownership: eager switch, dirty tracking, scrub (normative)

**Wave-3 task C1b.** [../fpu/spec.md §7.7](../fpu/spec.md) states the invariant, the rules, the
options that were priced and the experiment that would settle them, for the scalar FP file. This
section is the SIMD half and states only what is this document's to state: the registers covered,
the scrub value for each, and the two ways the SIMD file differs from the FP one. It is here and
not in `../decisions/` for the reason [../decisions/README.md](../decisions/README.md) gives —
this document owns `V0..V15`, `P0` and `VCSR`.

**The exposure is the same shape and larger.** §2.6's hypervisor-aware lazy SIMD ABI restores a
vCPU's image "if any" in the `EXC_SIMD_DISABLED` handler. A fresh vCPU has no image, so the branch
that runs is the one that writes nothing, and the incoming tenant reads `V0..V15` — the largest
single block of architectural state in the design (§2.5) — as the outgoing tenant left it.
`HEDR[24] = 1` delegates the trap to the guest exactly as `HEDR[3]` does for the FPU
([../fpu/spec.md §7.1](../fpu/spec.md)), with the same consequence: the hypervisor's ownership
transition never runs.

**V-INV.** At every instant, every bit of `V0..V15`, `P0` and `VCSR` is either a bit the file's
current owner wrote since the file's last scrub, or the corresponding **scrub value** below.

**`FPSCR` is deliberately not on this section's list.** [../fpu/spec.md §7.7](../fpu/spec.md) owns
it and rule **FP-R1** names it in the FP scrub value, so a gang switch scrubs it whether or not the
outgoing tenant's SIMD touched it. That is why the `FPSCR` defect Wave-3 **C1c** found (§2.4.1) is
*not* a cross-tenant one, and why C1c adds nothing to this section, to
[../hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)'s list, or to `VDS`.

**V-R1 — The scrub value.** `V0..V15` = zero; `P0` = zero; `VCSR` = zero. `VCSR` = 0 is `MKE = 0`
and `IEE = 0`, which §2.4 already gives as both bits' default, so the scrub value and the
architectural default are the same value and there is nothing for an implementer to choose
between. `P0` = 0 is defined and inert: with `MKE = 0` every lane is active regardless of `P0`
(§2.4), so a scrubbed `P0` cannot silently disable a tenant's lanes.

**V-R2 — Reset.** Out of reset the SIMD file holds the V-R1 values and `VDS` is `00`.

**V-R3 — Scrub on ownership installation.** A hyperprivileged write of `VDS` = `00` applies V-R1
to `V0..V15`, `P0` and `VCSR` in the same step as the write. Unconditional, idempotent, no
transition detection. The consequences are [../fpu/spec.md §7.7](../fpu/spec.md)'s three, verbatim
in this file's terms, including that a fresh vCPU with no saved image is covered by construction.

**V-R4 — `VDS`, the two dirty bits.** `VDS[1:0]`, per thread context, hyperprivileged-only, with
[../fpu/spec.md §7.7](../fpu/spec.md)'s `FPDS` encoding and semantics: `00` RESET, `01` CLEAN, `10`
DIRTY, `11` reserved and read as `10`. Hardware sets `10` on any architectural write to
`V0..V15`, `P0` or `VCSR` from any mode. **`VDS` is not `SR.VD`** — `SR.VD` is a guest-visible
disable bit in `SR` and `VDS` is hypervisor-only state that no guest instruction can read. `VDS`
adds no bytes to §2.5's SIMD image and no row to
[../hypervisor/hardware-spec.md §2.9](../hypervisor/hardware-spec.md), for the reason
[../fpu/spec.md §7.7](../fpu/spec.md) gives at length: it describes the physical file, which the
next owner's installation overwrites, not the owner.

**V-R5 — Eager across tenants, lazy within.** §2.6's lazy pattern and its hypervisor-aware ABI are
unchanged *within* a tenant, including the delegated `HEDR[24] = 1` form. Across tenants the save
(when `VDS` = `10`) and the scrub both complete before the incoming guest's first instruction, and
neither may depend on that guest executing a SIMD instruction.

**Two things are genuinely different from the FP file, and both make the SIMD half harder.**

1. **`P0` is a jcore integer register (§2.5), not a member of `V0..V15`.** A scrub that walks the
   vector file and stops there leaves the predicate mask holding the outgoing tenant's lane
   pattern — a small leak, but one that survives every test written against the vector registers.
   V-R1 names `P0` explicitly for that reason.
2. **FP SIMD couples the two files.** Since `VFPUL`'s retirement (§2.3, Appendix B) FP horizontal
   reductions, `VFIPR` and `VFTRV` write the SH-4 FP file directly at block exit, so a task doing
   FP SIMD owns **both** facilities. An implementation that scrubs the file it believes the
   incoming tenant will use therefore has a live hole in each direction. The scrubs are specified
   as two independent rules over two independent registers precisely so that "which facility does
   this tenant use" is never asked at a switch; both are always scrubbed. Test 4 of
   [../fpu/spec.md §7.7](../fpu/spec.md), and its mirror with the roles of FP and SIMD exchanged,
   are what demonstrate it.

**Residue tests.** [../fpu/spec.md §7.7](../fpu/spec.md)'s four, with `V0..V15`, `P0` and `VCSR`
substituted for the FP registers, plus a fifth that has no FP analogue: tenant A leaves a lane
pattern in `P0` and nothing in `V0..V15`; tenant B reads `P0`. It recovers A's mask on any
implementation whose scrub covers the vector file alone, with the other four green.
**L6** requires each demonstrated red before the fix, and there is nothing to run them on: no
`*.vhd`/`*.vhm` file in `jcore-cpu@origin/master` (`e8a5a4e1`) matches `entity simd`,
`component simd` or `vcsr`, checked case-insensitively on 2026-09-09. **This section is a rule
about hardware that does not exist, and nothing in it is met because it has been written.**

**Cost.** The structural count is §2.5's Tier 0 architectural addition — every bit of it is
scrubbed — plus two flip-flops per thread context for `VDS`. Everything else, including whether
the clear enable moves `Fmax` and how often a tenant leaves the file dirty at a quantum boundary,
is `unknown at this stage — needs measurement`, and the experiment and its kill criteria are
[../fpu/spec.md §7.7](../fpu/spec.md)'s, run over both files together.

---

### 2.6.2 Kernel-mode use of the SIMD facility (normative for the OS)

**Wave-3 task C1c**, second half, SIMD side. [../fpu/spec.md §6.3.1](../fpu/spec.md) states the
`kernel_fpu` discipline for the FP file and the facts about `linux@origin/jcore` that all of it
rests on; its rules **K-R1** through **K-R5** apply here with `V0..V15`, `P0` and `VCSR`
substituted for the FP registers, and with `SR.VD` and `EXC_SIMD_DISABLED` substituted for `SR.FD`
and `EXC_FPU_DISABLED`. This section states only what is different, and both differences make the
SIMD side worse.

**1. The V file is the case [../j4-remediation-plan.md §C1](../j4-remediation-plan.md) actually
names**, in its request for "a scrub requirement for kernel crypto that stages key material in V
registers". A block cipher's round keys are the natural contents of `V0..V15` in a vectorised
kernel implementation, and §2.5 makes that file **512 bytes on J32 and 1024 on J64** — the largest
single block of architectural state in the design. Nothing else a kernel critical section touches
has that combination of size and sensitivity.

**2. §2.6's handler has *two* branches that write nothing, where the FP handler has one.** K-R3's
argument is that the lazy model provides no unconditional reload to overwrite the kernel's data
with. Here it is worse than at the FP file, and the extra branch is the one that will be missed:

- **The spurious branch.** §2.6's pseudocode opens with
  `if current_simd_owner == current_task: SR.VD = 0; return_from_exception()`. If a kernel critical
  section runs SIMD in the context of task *T* and leaves `current_simd_owner` reading *T* — which
  it does, because the kernel was not a task in that bookkeeping — then *T*'s next SIMD instruction
  takes this branch, which clears `SR.VD` and writes **nothing**. *T* reads the kernel's key
  material out of `V0..V15` with a committed `VST.Q`.
- **The no-saved-image branch.** `if current_task.has_saved_simd_state: restore_simd_state(...)` —
  a task that has never used SIMD has no image, so the restore does not run and the file is handed
  over as the kernel left it. **This is §2.6.1's exposure and
  [../fpu/spec.md §7.7](../fpu/spec.md)'s, one privilege level down and out of reach of both.**
  V-R3 fires on a hyperprivileged `VDS` write at a cross-tenant switch; a kernel→user return inside
  one guest is not one, and the guest kernel cannot write `VDS` in any case (§2.6.1: `VDS` is
  hypervisor-only state that no guest instruction can read).

**Setting `SR.VD = 1` on the way out of the section is not a fix**, and it is the fix that will be
proposed, because it is what the context-switch path does. The trap that `SR.VD` raises is
delivered to the handler above, whose first two branches are the two that write nothing. Clearing
the software `current_simd_owner` is not a fix either: it disarms the first branch and leaves the
second.

**The rule.** A kernel SIMD critical section MUST, before re-enabling preemption, write §2.6.1's
**V-R1** values — `V0..V15` = 0, `P0` = 0, `VCSR` = 0 — over the whole file, whatever subset of it
the section used, and MUST NOT rely on any later restore to do it. `P0` is named because it is a
jcore integer register and not a member of `V0..V15` (§2.5), so a scrub loop written over the
vector file misses it; that is V-R1's own reason, and it applies unchanged to a software scrub.

**What has a site today: nothing.** [../fpu/spec.md §6.3.1](../fpu/spec.md) records the checks —
there is no SIMD support of any kind in `arch/sh` at `linux@origin/jcore` (`128e8958`), no
`arch/sh/include/asm/simd.h`, no `arch/sh/crypto`, no `lib/crypto/sh` and no `lib/raid/raid6/sh`.
There is also no SIMD unit in `jcore-cpu@origin/master` (`e8a5a4e1`). This section is a rule about
software that would drive hardware, and neither exists.

---

## 3. Instruction Encoding

### 3.1 Opcode space and syntax normalization

All Tier 0 SIMD prefix encodings live in the **`1111 nnnn mmmm 1111` sub-row** (256 codepoints). This is the only sub-row consistently unallocated across SH-2 base, SH-4 FPU, and SH-4A FPU extensions. The remainder of the `1111 ……` block remains available for scalar SH-4 FPU operations.

**Syntax normalization (project-wide).** Two syntactic conventions appear in earlier draft material: the v0.5/v0.6 `SIMDV.w` / `SIMDH<op>.w` family, and the original VCLMUL design spec's `vprefix.v.d` / `vclmul.d` family. **This specification picks the `SIMDV.w` family**, and rewrites all VCLMUL/VCRC32C examples accordingly. Rationale:

1. `SIMDV.w` and `SIMDH<op>.w` already cover four lane widths uniformly (`.B`/`.W`/`.L`/`.Q`), and Tier 2 instructions reuse the same width-lock mechanism — `VCLMUL.D` is governed by `SIMDV.Q` (64-bit lanes), `VCRC32C.B` by `SIMDH<add>.B`.
2. The `SIMDV/SIMDH` mnemonics match the SH lineage (`MULS.W`, `MOV.L`).
3. Toolchains already need a single prefix family; supporting two syntactic skins doubles parser/disassembler complexity for zero ISA benefit.

This decision is also stated in [software-impl.md §3](software-impl.md). All assembly examples in this document use the `SIMDV.w` family.

### 3.2 Prefix instructions (SIMDV, SIMDH)

The prefix encodes lane width, mode, and block length.

```
SIMDV<r>.w   #N      vertical (lane-parallel) prefix, modifier r
SIMDH<op>.w  #N      horizontal (reductive) prefix with reduction operator

Bit  | 15 14 13 12 | 11 | 10 9 | 8 7 6 | 5 4 | 3 2 1 0 |
     |  1  1  1  1 |  H |  w w | r r r | N N |  1 1 1 1 |
     ─────────────────────────────────────────────────
        top nibble  H/V  width  modifier N-1  bottom nibble
                    0=V  00=8   (see)   0=1   (escape)
                    1=H  01=16          1=2
                         10=32          2=3
                         11=64          3=4
```

Field definitions:

- **H** (bit 11): 0 selects vertical mode; 1 selects horizontal mode.
- **ww** (bits 10:9): lane width — 00 = 8 bits, 01 = 16 bits, 10 = 32 bits, 11 = 64 bits.
- **rrr** (bits 8:6):
  - When H = 0 (vertical): SIMDV modifier bits.
    - bit 0 (NT, Non-Temporal): when set, governed memory access instructions in the block use non-temporal cache hints (§5.6).
    - bits 1, 2 (Tier 1): saturation modifier per §3.2.1. On Tier 0 these must be 00.
  - When H = 1 (horizontal): selects the reduction operator per the table below.
- **NN** (bits 5:4): block length, encoded as N − 1, giving N ∈ {1, 2, 3, 4} governed instructions.

**Reduction operator table (H = 1):**

| `rrr` | Mnemonic suffix | Operator | Identity element (for masked-lane substitution) | Tier |
|---|---|---|---|---|
| 000 | `SIMDHA` (default, `SIMDH` synonym) | add | integer: 0; FP: +0.0 | T0 |
| 001 | `SIMDHO` | bitwise OR | 0 | T0 |
| 010 | `SIMDHN` | bitwise AND | all-ones | T0 |
| 011 | `SIMDHX` | bitwise XOR | 0 | T0 |
| 100 | `SIMDHMN` | min (signed for int, IEEE minNum for FP) | integer: INT_MAX; FP: +∞ | T0 |
| 101 | `SIMDHMX` | max (signed for int, IEEE maxNum for FP) | integer: INT_MIN; FP: −∞ | T0 |
| 110 | `SIMDHMNU` | min unsigned (integer only; slot-illegal for FP) | UINT_MAX | T0 |
| 111 | `SIMDHMXU` | max unsigned (integer only; slot-illegal for FP) | 0 | T0 |

The block length cap of N = 4 matches the ARM Thumb-2 `IT` block precedent.

#### 3.2.1 SIMDV saturation modifier (Tier 1)

Tier 1 defines the SIMDV `rrr` field (bits 7:6, with bit 6 = NT preserved at `rrr[0]`):

| `rrr` | Mnemonic | Modifier |
|---|---|---|
| 000 | `SIMDV` (no suffix) | wrap (Tier 0 default) |
| 001 | `SIMDV.NT` (Tier 0 NT bit only) | wrap + non-temporal hint |
| 010 | `SIMDVS` | signed saturating (Tier 1) |
| 011 | `SIMDVS.NT` | signed saturating + NT (Tier 1) |
| 100 | `SIMDVU` | unsigned saturating (Tier 1) |
| 101 | `SIMDVU.NT` | unsigned saturating + NT (Tier 1) |
| 110 | reserved | slot-illegal in Tier 1; reserved for "halving" arithmetic |
| 111 | reserved | slot-illegal |

`SIMDH` prefixes ignore saturation (the reduction operator already determines the destination type). The Tier 1 saturation semantics are defined in §5.4.

### 3.3 SWIZZLE (context-sensitive)

SWIZZLE has **no standalone encoding**. Inside an open SIMD block (`SIMD_VAL = 1`), the bit pattern `1111 nnnn mmmm 1111` is decoded as SWIZZLE rather than as a prefix; the prefix's width and mode are inherited from the open block's microarchitectural state.

```
SWIZZLE Vn, Vm       1111 nnnn mmmm 1111    (inside SIMD block only; Tier 0)
```

- **nnnn**: destination/source vector Vn (V0..V15)
- **mmmm**: control vector Vm (V0..V15), interpreted as packed lane indices per §4.5

A SWIZZLE consumes one of the N governed-instruction slots declared by the prefix.

---

## 4. Execution Model (Tier 0)

### 4.1 Block lifetime

```
1. Prefix decoded:  SIMD_VAL ← 1, SIMD_CNT ← N − 1, SIMD_W ← ww, SIMD_H ← H,
                    SIMD_RED ← rrr (if H=1), SIMD_SAT ← rrr[2:1] (if H=0, Tier 1).
2. Each governed instruction decoded:
     - decode table is the SIMD decode table (see §5)
     - operand fields Rn/Rm interpreted as V0..V15 indices
     - execute lane-wise according to SIMD_W and SIMD_H (and SIMD_SAT, Tier 1)
     - on retire: if SIMD_CNT == 0, SIMD_VAL ← 0; else SIMD_CNT ← SIMD_CNT − 1
3. Block terminates when N governed instructions have retired.
```

### 4.2 Atomicity

**SIMD blocks execute atomically with respect to external interrupts.** Interrupts arriving while `SIMD_VAL = 1` are held pending and dispatched only after the block has retired its final governed instruction. No SIMD state is ever architecturally visible to an exception handler. RTE always lands at a non-SIMD instruction boundary.

The interrupt latency cost is bounded. On a single 32-bit ALU implementation each governed instruction takes VLEN/32 beats (**8 beats on J32**, 16 on J64), so the worst case is N = 4 × 8 = **32 cycles on J32** (64 on J64). At 50 MHz that is 640 ns (J32). The latency is statically WCET-analysable and scales with VLEN; wider ALUs reduce the beat count proportionally.

**Synchronous exceptions** (slot-illegal, FPU exceptions raised by a governed FP instruction, memory faults on a governed load/store) are not deferred. See §6.

### 4.3 Vertical mode semantics

In vertical mode (`SIMD_H = 0`), a governed scalar instruction with operand pattern `op Rm, Rn` is interpreted as:

```
if VCSR.MKE == 0:                         ; unmasked
    for i in 0 .. (VLEN/w − 1):
        V<Rn>.lane[i] ← V<Rn>.lane[i]  op  V<Rm>.lane[i]
else:                                      ; masked (VCSR.MKE == 1)
    for i in 0 .. (VLEN/w − 1):
        if P0[i · (w/8)] == 1:
            V<Rn>.lane[i] ← V<Rn>.lane[i]  op  V<Rm>.lane[i]
        else:
            V<Rn>.lane[i] ← V<Rn>.lane[i]   (unchanged)
```

The result of every lane is independent (no cross-lane carry, no cross-lane data movement). Carry chains in the ALU are broken at lane boundaries.

**FMAC special case.** SH-4's FMAC is `FRn ← FR0 · FRm + FRn`. In SIMD context, FMAC is reinterpreted as `V<Rn>[i] ← V0[i] · V<Rm>[i] + V<Rn>[i]` — V0 plays the role of the implicit multiplier vector, matching FR0's role in scalar FMAC.

**Tier 1 saturation interaction.** When the prefix is `SIMDVS` or `SIMDVU`, the per-lane `op` result is clamped to the relevant integer range; see §5.4.

### 4.4 Horizontal mode semantics

In horizontal mode (`SIMD_H = 1`):

1. **At prefix decode**, the destination (MAC pair for integer, or FR0/DR0 for FP, per §2.3) is **implicitly cleared to zero**.
2. **Each governed instruction** computes its per-lane operation, reduces across lanes per the selected operator (add/OR/AND/XOR/min/max/min-u/max-u), and accumulates into the destination. Within a single block of N governed instructions, accumulation proceeds across them.
3. **When VCSR.MKE = 1**, masked lanes contribute the **identity element** for the chosen reduction operator (additive identity 0 for add, all-ones for AND, INT_MAX for min, etc., per §3.2). This keeps the reduction tree shape mask-independent.
4. **At block exit**, the destination holds the complete reduction result.

The detailed per-type reduction algorithms (integer, FP16, FP32, FP64) are unchanged from spec-v0.5 §4.4 and reproduced below for the integer case:

```
at prefix decode:        MAC ← 0
for each governed insn:
    for i in 0 .. (VLEN/w − 1):
        if VCSR.MKE == 0 or P0[i · (w/8)] == 1:
            t[i] ← V<Rn>.lane[i]  op  V<Rm>.lane[i]
        else:
            t[i] ← identity_element(SIMD_RED)
    MAC ← reduce(SIMD_RED, MAC, t[0..(VLEN/w − 1)])
```

For FP add-reductions the reduction respects IEEE 754 rounding using `FPSCR.RM` — which the block owns, per §2.4.1 rule **S-R1**; the reduction order is implementation-defined.

**Cross-block accumulation.** Each SIMDH block produces a complete reduction; the destination is not preserved across block entries. Software combines partial sums with explicit scalar add operations across blocks.

### 4.5 SWIZZLE semantics

SWIZZLE permutes the lanes of Vn according to a control vector in Vm. Vm is interpreted as a packed array of lane indices (4 bits per index at w=8 down to 1 bit at w=64). Out-of-range indices force the destination lane to zero (AltiVec VPERM convention, 1996). See §5.6 for the immediate-pattern variant SWIZZLE.I.

> **The stated index width cannot address the lanes, and neither can `llll`.**
> Found by the B4 encoding sweep ([encoding-sweep.md §3.1](../encoding-sweep.md)).
> §1.2 fixes `VLEN = 8 × XLEN`, so w=8 gives **32 byte-lanes on J32 and 64 on
> J64** — 5 and 6 index bits. "4 bits per index at w=8" reaches 16 of them, and
> Appendix A's `llll` (the `VLNS` lane index) is 4 bits with the same shortfall.
> This is arithmetic against this document's own §1.2, not a search result.
>
> It is **not fixed here**, because the two candidate fixes are not equivalent
> and the choice is architectural: widen the packed index to `ceil(log2(VLEN/8))`
> and accept that the control vector's packing becomes XLEN-dependent, or keep
> 4 bits and restrict SWIZZLE/`VLNS` to lane widths where 16 indices suffice
> (w ≥ 16 on J32, w ≥ 32 on J64). `VLNS` has a second, independent reason to
> change shape — see §5.7 — and both should be settled in one revision.

SWIZZLE is a **pure lane-permute** and is **never itself reduced**: in a horizontal (or segmented, [gpu/simd-gpu-spec.md](gpu/simd-gpu-spec.md)) block it performs its permute and consumes one governed slot to **prepare operands** for a following reducing instruction; only arithmetic governed instructions contribute to the reduction. Like all SWIZZLE forms it has no standalone encoding — it is valid **only inside an open SIMD block** (§3.3), so broadcasts and half-selects that feed a reduction or a VCLMUL live in the *same* block as the operation they feed, not before the prefix.

### 4.6 Lane beat execution (implementation guidance)

Implementations time-multiplex the existing 32-bit ALU over VLEN/32 cycles ("beats") per governed instruction — **8 beats on J32** (256-bit), 16 on J64 (512-bit); a wider ALU reduces this proportionally. Beat schedules and implementation tactics live in [hardware-impl.md §2](hardware-impl.md).

---

## 5. Governed Instructions

When `SIMD_VAL = 1`, the decoder uses a SIMD-context decode table. The SIMD decode table differs from the standard table only in:

1. Lane-wise reinterpretation of integer arithmetic and logic operations (§5.1).
2. Lane-wise reinterpretation of SH-4 FPU compute operations (§5.2).
3. Reinterpretation of certain SH-2/SH-4 encodings as Tier 1 and Tier 2 SIMD instructions (§5.4, §5.5).
4. Reservation of all control-flow, system, and PC-relative instructions as slot-illegal (§5.3).
5. Reinterpretation of `1111 nnnn mmmm 1111` as SWIZZLE.

### 5.1 Integer SH-2 operations (Tier 0 governed)

| Encoding | Mnemonic | Lane operation | Tier |
|---|---|---|---|
| `0011 nnnn mmmm 1100` | ADD Rm,Rn | per-lane add | T0 |
| `0011 nnnn mmmm 1000` | SUB Rm,Rn | per-lane subtract | T0 |
| `0010 nnnn mmmm 1001` | AND Rm,Rn | per-lane AND | T0 |
| `0010 nnnn mmmm 1011` | OR  Rm,Rn | per-lane OR | T0 |
| `0010 nnnn mmmm 1010` | XOR Rm,Rn | per-lane XOR | T0 |
| `0110 nnnn mmmm 1011` | NEG Rm,Rn | per-lane negate | T0 |
| `0110 nnnn mmmm 0111` | NOT Rm,Rn | per-lane bitwise NOT | T0 |
| `0010 nnnn mmmm 1110` | MULU.W Rm,Rn | per-lane unsigned multiply (result width = 2w) | T0 |
| `0010 nnnn mmmm 1111` | MULS.W Rm,Rn | per-lane signed multiply | T0 |
| `0100 nnnn mmmm 1101` | SHLD Rm,Rn | per-lane dynamic logical shift | T0 |
| `0100 nnnn mmmm 1100` | SHAD Rm,Rn | per-lane dynamic arithmetic shift | T0 |
| `0011 nnnn mmmm 0000` | CMP/EQ Rm,Rn | per-lane equality test → writes P0 | T0 |
| `0011 nnnn mmmm 0011` | CMP/GE Rm,Rn | per-lane signed ≥ test → writes P0 | T0 |
| `0011 nnnn mmmm 0111` | CMP/GT Rm,Rn | per-lane signed > test → writes P0 | T0 |

Per-lane comparison results are written to **P0** (§2.5); bits not covered by the current width's active lanes are preserved across width changes.

> **`SUB` corrected 2026-09-08 by the B4 encoding sweep**
> ([encoding-sweep.md §3.1](../encoding-sweep.md)). This row previously read
> `0011 nnnn mmmm 1010`, which is not `SUB Rm,Rn` — it is **`SUBC Rm,Rn`**, as
> `jcore-cpu/docs/insns.json` and `decode/gen-go/spec/arithmetic.toml` both
> record. `SUB Rm,Rn` is `0011 nnnn mmmm 1000`. The error was not inert: §5.4.3
> below gives `0011 nnnn mmmm 1010` to `VABSDIFF` "(was SUBC)", so this table
> and that one claimed **one encoding twice**, both of them governed and both
> reachable in the same block. Correcting the nibble dissolves the double claim;
> `VABSDIFF` keeps `SUBC`'s slot and needs no move.
>
> The other 20 rows of §5.1 and §5.2 were checked the same way against the
> canonical database and every one of them matches.

### 5.2 SH-4 FPU operations (Tier 0 governed)

| Encoding | Mnemonic | Lane operation | Tier |
|---|---|---|---|
| `1111 nnnn mmmm 0000` | FADD FRm,FRn | per-lane FP add | T0 |
| `1111 nnnn mmmm 0001` | FSUB FRm,FRn | per-lane FP subtract | T0 |
| `1111 nnnn mmmm 0010` | FMUL FRm,FRn | per-lane FP multiply | T0 |
| `1111 nnnn mmmm 0011` | FDIV FRm,FRn | per-lane FP divide | T0 |
| `1111 nnnn mmmm 0100` | FCMP/EQ FRm,FRn | per-lane FP equality → writes P0 | T0 |
| `1111 nnnn mmmm 0101` | FCMP/GT FRm,FRn | per-lane FP > → writes P0 | T0 |
| `1111 nnnn mmmm 1110` | FMAC FR0,FRm,FRn | per-lane FMA (V0 is implicit third operand) | T0 |

`SIMD_W` selects the operand precision: w=32 → FP32, w=64 → FP64, w=16 → FP16 (optional; lanes = VLEN/w in each case), w=8 → slot-illegal for FP. **FP16 semantics — including the FP32-accumulate reduction rule, packed FP16↔FP32 conversions, and the scalar-FPU conversion recommendation — are specified in [gpu/simd-gpu-spec.md §8](gpu/simd-gpu-spec.md).** An implementation without FP16 raises slot-illegal on `ww=01` FP ops.

### 5.3 Reserved inside SIMD block (Tier 0)

The following instruction classes are **reserved** as governed instructions and raise slot-illegal when encountered with `SIMD_VAL = 1`:

- Control flow (BRA, BSR, BT, BF, BT.S, BF.S, BRAF, BSRF, JMP, JSR, RTS, RTE).
- System and synchronisation (TRAPA, SLEEP, LDC, STC, LDS, STS, LDTLB).
- Cache and memory ordering (PREF, OCBI, OCBP, OCBWB, MOVCA, ICBI, MOVUA).
- PC-relative (MOVA, MOV.W @(disp,PC),Rn, MOV.L @(disp,PC),Rn).

Memory access opcodes (SH-2 `MOV.x` in rows `0001`, `0101`, `0110`, `1001`, `1101`, and SH-4 `FMOV.S` at `1111 nnnn mmmm 0110`..`1011`) are **redefined inside SIMD blocks** as vector load/store (§5.6).

A governed instruction whose encoding is not in §5.1, §5.2, §5.4, §5.5, or §5.6 is architecturally undefined and raises slot-illegal.

### 5.4 Tier 1 — integer/saturation extensions

#### 5.4.1 Saturating arithmetic mode (`SIMDVS`, `SIMDVU`)

The SIMDV `rrr` saturation modifier (§3.2.1) gates the result of integer governed instructions to clamp on overflow:

| Governed instruction | Wrap (T0) | Signed sat (SIMDVS, T1) | Unsigned sat (SIMDVU, T1) |
|---|---|---|---|
| `ADD Vm, Vn` | wrap | clamp to `[INT_MIN_w, INT_MAX_w]` | clamp to `[0, UINT_MAX_w]` |
| `SUB Vm, Vn` | wrap | clamp to `[INT_MIN_w, INT_MAX_w]` | clamp at 0 (no negative result) |
| `NEG Vm, Vn` | wrap (`NEG -128 = -128` at w=8) | clamp (`NEG -128 = 127`) | slot-illegal |
| `SHAD Vm, Vn` | wrap on left-shift | clamp on left-shift overflow | clamp on left-shift overflow |
| `SHLD Vm, Vn` | wrap | (logical shift; treated as unsigned) | clamp on left-shift overflow |
| `MULS`/`MULU` (vertical) | widens per §2.3 | n/a | n/a |
| `AND`, `OR`, `XOR`, `NOT` | unaffected | slot-illegal (SIMDVS+logical is meaningless) | slot-illegal |

Predication is orthogonal: a predicated saturating instruction applies saturation lane-wise to the active lanes; inactive lanes preserve their previous Vn value.

#### 5.4.2 New unary governed instructions

Encoded in the SH-4 FPU unary row `1111 nnnn xxxx 1101`, slots `xxxx ∈ {1000..1111}`:

> **Those slots are not free, and this table's premise that they are is wrong.** SH-4 defines
> `FLDI0`, `FLDI1`, `FCNVSD` and `FCNVDS` in that range — see
> [../fpu/spec.md §5.2–§5.3](../fpu/spec.md) and the canonical encoding database
> ([decisions/0003](../decisions/0003-canonical-encoding-database.md)). This is **not** a
> violation of [../sh4-guest-model.md §5](../sh4-guest-model.md) Decision B2-5, because these are
> *governed* instructions: they are reachable only inside an open SIMD block, and a guest that
> never opens one never decodes them. The justification is what is false, not the placement, and
> [j4-remediation-plan.md §B4](../j4-remediation-plan.md) should not treat the range as virgin
> when it sweeps.

| Encoding | Mnemonic | Operation | Tier |
|---|---|---|---|
| `1111 nnnn 1000 1101` | VABS Vn | per-lane signed absolute value | T1 |
| `1111 nnnn 1001 1101` | VPOPCNT Vn | per-lane population count | T1 |
| `1111 nnnn 1010 1101` | VUNPK4LU Vn | unpack low VLEN/2 bits as VLEN/16 unsigned nibbles → VLEN/8 int8 lanes | T1 |
| `1111 nnnn 1011 1101` | VUNPK4HU Vn | unpack high VLEN/2 bits as VLEN/16 unsigned nibbles → VLEN/8 int8 lanes | T1 |
| `1111 nnnn 1100 1101` | VUNPK4LS Vn | unpack low VLEN/2 bits as VLEN/16 signed nibbles | T1 |
| `1111 nnnn 1101 1101` | VUNPK4HS Vn | unpack high VLEN/2 bits as VLEN/16 signed nibbles | T1 |
| `1111 nnnn 1110 1101` | reserved | — | — |
| `1111 nnnn 1111 1101` | reserved | — | — |

- **VABS.** Per-lane signed absolute value. In wrap mode `VABS INT_MIN_w = INT_MIN_w`; in SIMDVS mode `VABS INT_MIN_w = INT_MAX_w`. Inside a SIMDH block the absolute values reduce per the chosen operator (typically add — sum of absolute values).
- **VPOPCNT.** Per-lane population count. Lane-width result stored in a same-width lane (w=8 → 0..8; w=64 → 0..64). SIMDVS/SIMDVU + VPOPCNT raises slot-illegal (no overflow possible).
- **VUNPK4 family.** INT4→INT8 nibble unpack; the VLEN/2-bit half of Vn is read as VLEN/16 packed 4-bit values (16 on J32, 32 on J64), each zero- or sign-extended to 8 bits, written across the full VLEN bits (VLEN/8 int8 lanes). Nibble order is **low nibble first** (matches GGML/llama.cpp/AWQ/GPTQ packing and SH little-endian conventions). Width modifier `ww` from the prefix is **ignored**; prefix must be `SIMDV.B` else slot-illegal.

#### 5.4.3 Tier 1 reinterpretations of SH-2 ops

| SH-2 outside SIMD | Encoding | Tier 1 inside SIMD |
|---|---|---|
| `SUBC Rm, Rn` | `0011 nnnn mmmm 1010` | `VABSDIFF Vm, Vn` — per-lane `|Vm[i] − Vn[i]|` |
| `EXTS.B Rm, Rn` | `0110 nnnn mmmm 1110` | `VPACK.SS Vm, Vn` — int16 → int8 signed sat |
| `EXTU.B Rm, Rn` | `0110 nnnn mmmm 1100` | `VPACK.SU Vm, Vn` — int16 → uint8 unsigned sat |
| `EXTS.W Rm, Rn` | `0110 nnnn mmmm 1111` | `VPACKW.SS Vm, Vn` — int32 → int16 signed sat |
| `EXTU.W Rm, Rn` | `0110 nnnn mmmm 1101` | `VPACKW.SU Vm, Vn` — int32 → uint16 unsigned sat |
| `DMULS.L Rm, Rn` | `0011 nnnn mmmm 1101` | `VMULSU Vm, Vn` — mixed-sign multiply (Vm signed × Vn unsigned) |

**VABSDIFF** in SIMDH<add> sums per-lane absolute differences into MACL (widened per §2.3) — single-instruction **VLEN/8-byte SAD** (32 B on J32, 64 B on J64).

**VPACK family** uses Vn-source-Vn-dest convention: low output lanes come from Vm, high output lanes from Vn (the destination's prior value is absorbed as the high half). The prefix lane-width is ignored; `VPACK.*` must use `SIMDV.B`; `VPACKW.*` must use `SIMDV.W`; otherwise slot-illegal. Predication applies at output-lane granularity.

**VMULSU** in SIMDV.B truncates per-lane (low byte of each int16 product). In SIMDH<add>.B #1, per-lane int16 products sum and widen into MACL — this is the canonical VNNI/SDOT operation for INT8 GEMV with signed weights × unsigned activations.

#### 5.4.4 Extended widening-reduction table

Tier 1 extends the §2.3 reduction-destination table:

| Operation | *w* | Per-lane intermediate | SIMDH<add> destination |
|---|---|---|---|
| `VMULSU` | 8 | int16 | MACL (int32) — VNNI-equivalent |
| `VMULSU` | 16 | int32 | MACL+MACH (int64) |
| `VABSDIFF` | 8 | uint8 | MACL (uint16 → uint32) |
| `VABSDIFF` | 16 | uint16 | MACL+MACH (uint32 → uint64) |
| `VPOPCNT` | 8 | uint8 (0..8) | MACL (uint16) |
| `VPOPCNT` | 64 | uint8 (0..64) | MACL (uint8) |
| `VABS` | 8 | uint8 (0..128 sat) | MACL (uint16) |

`VPACK` and `VUNPK4` do not produce reducible per-lane values; they are slot-illegal inside SIMDH blocks.

### 5.5 Tier 2 — GF(2) crypto extensions

Tier 2 adds two instructions that extend the SIMD execution pipeline with Galois-field GF(2) arithmetic. Both reuse the existing widening-multiplier datapath with the carry chain gated to XOR mode (see [hardware-impl.md §6](hardware-impl.md)). No new architectural state. No new prefix bits.

#### 5.5.1 VCLMUL.D — Carryless multiply, doubleword

```
SH-2 outside SIMD:  DMULU.L   Rm, Rn   0011 nnnn mmmm 0101   (reserved by Tier 0)
Tier 2 inside SIMD: VCLMUL.D  Vm, Vn   0011 nnnn mmmm 0101
```

Two-operand form, destination doubles as first source (SH-2 convention):

```
Vn[127:0]    ← Vn[63:0] ⊗ Vm[63:0]   ; GF(2)[x] polynomial product (128-bit)
Vn[VLEN-1:128] ← unchanged            ; upper bits preserved (VLEN ≥ 256)
```

GF(2) multiplication: `(a ⊗ b)[k] = XOR over i+j=k of (a[i] AND b[j])` — polynomial multiplication where coefficient addition is XOR (no carries propagate).

**Required prefix mode:** `SIMDV.Q` (vertical, 64-bit lane width). Any other prefix (horizontal, lane width ≠ 64, no active prefix) raises slot-illegal. Width-lock removes the need for an explicit width bit in the instruction word.

**Half selection.** Selection of which 64-bit half of a wider register participates is performed by **prior swizzle**, not by an immediate field. This is the principal encoding difference from Intel PCLMULQDQ and the key patent-clearance choice (see Appendix C.3.2).

**Predication.** Under VCSR.MKE = 1, the per-lane mask is interpreted at 64-bit lane granularity (VLEN/64 lanes: 4 on J32, 8 on J64); **P0 bit 0 governs the low 64-bit lane that VCLMUL.D writes.** A masked-off lane preserves Vn unchanged.

**Behaviour at wider widths.** VCLMUL.D is defined as a **single** low-64 × low-64 → 128-bit product regardless of VLEN; the upper VLEN−128 bits are preserved (above). A form that issues VLEN/64 parallel CLMULs (one per 64-bit lane, producing more than VLEN bits of result) does not fit a VLEN-wide destination and is therefore reserved for **Tier 3** (width growth beyond VLEN, §1.1) — not delivered by the native 256/512-bit J32/J64 registers.

**Exception model.**

| Condition | Behavior |
|---|---|
| Wrong prefix mode (horizontal, width ≠ 64, no prefix) | Slot-illegal |
| Predicate mask zero for a lane | Lane result not written; no side effect |
| Arithmetic overflow | Not possible — GF(2) multiply is total |
| Operand availability stall | Pipeline stall, no exception |

#### 5.5.2 VCRC32C.B — CRC-32C folding step

```
SH-2 outside SIMD:  MAC.L @Rm+,@Rn+  0000 nnnn mmmm 1111   (reserved by Tier 0)
Tier 2 inside SIMD: VCRC32C.B Vm, Vn 0000 nnnn mmmm 1111
```

Two-operand form. The CRC accumulator lives in the **low 32 bits of Vn**; data bytes come from Vm:

```
Vn[31:0]      ← crc32c_fold(Vn[31:0], Vm, P0_mask)
Vn[VLEN-1:32] ← unchanged
```

The upper VLEN−32 bits of Vn are preserved so software may park unrelated state alongside the accumulator or use upper lanes for parallel CRC streams in future extensions.

**Required prefix mode:** `SIMDH<add>.B` (horizontal-reduce, 8-bit lanes). Any other prefix raises slot-illegal.

**Polynomial.** Fixed: **Castagnoli, 0x1EDC6F41** (normal form), 0x82F63B78 (reversed/reflected form). Used by iSCSI, SCTP, btrfs, ZFS, NVMe, RoCEv2, snappy. CRC-32-IEEE (used by Ethernet FCS / gzip / PNG / Zip) remains available via software CLMUL folding on top of VCLMUL.D.

**Semantics:**

```
crc = Vn[31:0]
for i in 0..(VLEN/8 − 1):          ; 0..31 on J32, 0..63 on J64
    if VCSR.MKE == 0 or P0[i] == 1:
        crc = (crc >> 8) ^ TABLE_C[(crc ^ Vm.byte[i]) & 0xFF]
Vn[31:0] = crc
```

where `TABLE_C` is the standard 256-entry CRC-32C table for polynomial 0x1EDC6F41. Hardware is free to use any equivalent computation (LFSR, CLMUL folding) provided the final accumulator value matches.

**Initial value and final XOR.** CRC-32C convention specifies XOR-with-0xFFFFFFFF at both input and output. This is **software's responsibility** (see [software-impl.md §7.1](software-impl.md)).

**Predicate behaviour.** P0's low VLEN/8 bits (32 on J32, 64 on J64) select which bytes of Vm participate. Bytes with P0 = 0 are skipped (no state update). Primary use: end-of-buffer tail handling — a single predicated VCRC32C.B collapses the 0..(VLEN/8−1)-byte epilogue every CRC library currently writes as a scalar loop.

**Exception model.** Wrong prefix mode → slot-illegal. All-zero mask → no state change, no exception. Mid-instruction interrupt: implementation may complete or restart at instruction boundary (architecture treats VCRC32C.B as atomic).

### 5.6 Vector memory and SIMD-control instructions

Tier 0 vector memory and SIMD-control instructions are reproduced unchanged from spec-v0.5 §5.5/§5.6. The detailed encoding table is captured in Appendix A; the highlights:

- **VLD.Q / VST.Q** at six addressing modes (`@Rm`, `@Rm+`, `@-Rm`, `@(R0,Rm)`, plus indexed forms). Each moves a full vector = VLEN/8 bytes (32 B J32, 64 B J64), **VLEN/8-byte aligned**. Valid in or out of SIMD blocks.

> **These encodings are SH-4's `FMOV.S` forms, and "out of SIMD blocks" makes that a
> violation.** [../sh4-guest-model.md §5](../sh4-guest-model.md) Decision B2-5 requires that any
> encoding SH-4 defines either behave as SH-4 defines it or raise a trap the hypervisor sees, on
> any core that can host an SH-4 guest; decoding it as a different J-Core instruction is the one
> forbidden outcome. Inside a block the reuse is fine — a guest that never opens a block cannot
> reach it, which is exactly the *contextual* reuse §5.4 relies on. Outside one it is not, and
> §5.4 of this document already says these encodings are redefined "inside SIMD blocks", which
> contradicts the sentence above. **`VMKCHG` (below) has the same problem** — it is placed outside
> SIMD blocks and its encoding is one operand form of SH-4's `FSCA`. Re-homing both is
> [j4-remediation-plan.md §B4](../j4-remediation-plan.md)'s encoding sweep, which was told to
> decide them jointly with the guest decode-fidelity policy; that policy is now written.
>
> **The sweep confirmed both, and sharpened the second**
> ([../encoding-sweep.md §3.1](../encoding-sweep.md)). A database reservation
> row carrying `1111 nnnn mmmm 1000` came back from regeneration annotated as
> colliding with `fmov.s @Rm,FRn` without being told to — six encodings, six
> collisions. `VMKCHG` is not merely "in `FSCA`'s row": `1111 1100 1111 1101`
> **is** `FSCA FPUL,DRn` at `n = 110`, and
> `cpugen freespace -form '1111110011111101'` returns zero candidates once
> `SH4A` is avoided. The one fix that costs nothing is the smaller one — both
> are declared valid *outside* SIMD blocks and nothing in this document needs
> them to be, so **the cheapest re-home is to make them in-block-only**, which
> §5.4 already says of the same bits, and only then to look for new slots for
> whatever genuinely has to work outside a block.
- **VGATHER.Q / VSCATTER.Q** with per-lane offsets from Vm (inside SIMD block only).
- **VMOV Vm, Vn** (inside SIMD block; SH-4 FMOV-register encoding reinterpreted).
- **VLDI.Q #imm, Vn** (8-bit signed immediate broadcast; inside SIMD block).
- **SWIZZLE.I Vn, #pattern, #param** (immediate-pattern variant of SWIZZLE; inside SIMD block).
- **VMKCHG** (toggle VCSR.MKE; outside SIMD block).
- **LDS Rn, P0 / STS P0, Rn / LDS Rn, VCSR / STS VCSR, Rn** (predicate and mode register access; outside SIMD block). There is no VFPUL access instruction — FP scalar results live directly in FR/DR (§2.3).

#### 5.6.1 Memory access N=1 rule

A memory access instruction (VLD.Q, VST.Q, VGATHER.Q, VSCATTER.Q) used inside a SIMD block must be the **sole governed instruction** (prefix N=1) and must use a **SIMDV** (vertical) prefix. Violations raise slot-illegal at decode. This rule enables the **restart-from-prefix** fault-handling mechanism (§6.4) and makes the architecture transparently compatible with software-managed-MMU systems.

This N=1 restriction is the **mandatory baseline** for every SIMD implementation, and is the form the in-order J32 enforces.

##### Relaxed N>1 memory blocks (optional, J32-OOO and up)

An out-of-order implementation that cracks the prefix and its governed group into a single ROB atomic-commit group (§6.1) can relax the N=1 restriction to allow a memory access to be combined with compute (and other memory ops) in an **N>1 SIMDV block**, because the same all-or-nothing group commit that handles interrupts also handles a mid-block memory fault: the fault prevents the group from committing, the group is flushed, and execution restarts from the prefix — idempotent for the whole block, exactly as for the N=1 case. An implementation may advertise this via the **`SIMD_RELAXED_MEM`** capability bit (feature register; Linux `HWCAP_JCORE_SIMD_RELAXED_MEM`, [software-impl.md §8.5](software-impl.md)).

When `SIMD_RELAXED_MEM` is supported, the implementation must guarantee:

- the cracked prefix+group commits atomically — stores in the group do **not** drain to memory / coherence, and post-increment / pre-decrement pointer updates do **not** commit, until the entire group commits;
- a synchronous fault on any group member reports the **prefix PC** and flushes the group (no member retired);
- the group's total memory footprint is bounded by N ≤ 4, so it fits the load/store queue.

`SIMDH` (horizontal) memory access remains **slot-illegal** regardless of this capability — only the N>1 part of the baseline rule is lifted, not the SIMDV-only part.

**Compatibility is one-way and fails safe.** A binary that uses N>1 memory blocks runs on any `SIMD_RELAXED_MEM` implementation, and on an implementation *without* the capability it raises slot-illegal at the first such block (§6.2) — a loud trap, never silent mis-execution. Conversely, every baseline (N=1) binary runs unchanged on a relaxed implementation. Because of this asymmetry the relaxed form is **not** emitted by default: a toolchain must gate it on the `SIMD_RELAXED_MEM` capability (a `-m`-flag / HWCAP check), so a J32+SIMD target never receives it. On J32-OOO the relaxation buys code density (fewer prefixes), not throughput — the OoO front end already issues a standalone `VLD.Q`/`VST.Q` independently of the compute block — so toolchains should weigh the density gain against the loss of in-order portability.

#### 5.6.2 Non-temporal (NT) hint

The SIMDV `rrr[0]` bit is the NT (Non-Temporal) flag. When set on a memory-access governed instruction, the implementation may bypass cache allocation (write-combining buffer for stores, streaming cache way for loads, or full cache bypass). Implementations without streaming-friendly cache pathways may treat NT as a no-op; the architectural result is identical. Prior art: Intel SSE MOVNTPS (1999), AltiVec dst/dstt (1996), PowerPC dcbt (1993).

### 5.7 Lane extract/insert (VLNS+VEXT/VINS)

Bridging individual lanes between V registers and a SIMD-side scalar register uses a **two-instruction sequence**: a VLNS prefix arms a microarchitectural lane-select latch (`V_LANE_REG`, `V_LANE_IDX`); the immediately-following VEXT/VINS consumes the latch.

The pair must be **adjacent and atomic**: any instruction between VLNS and a following VEXT/VINS raises slot-illegal, and external interrupts are deferred between the two instructions. This makes the lane-select latch microarchitectural (not architecturally visible, never saved on exception).

**Scalar-side targets.** Integer variants (`VEXT.B/W/L/Q`, `VINS.B/W/L/Q`) read/write a SH-2 integer scalar register Rn. FP variants (`VEXTF.L`, `VINSF.L`) read/write an **FR register (FRn) directly** — the same scalar FP bank the reductions target (§2.3). No intermediate register and no boundary move: `VEXTF.L` extracts a lane to FRn, `VINSF.L` inserts FRn into a lane. Because these touch FR, the FP variants require FPU ownership (trap under SR.FD as well as SR.VD; SR.VD first per §2.6) — an instance of §2.4.1 rule **S-R1**, and one of the three cases §2.1's disjointness sentence used to omit.

**Encodings** (full table in Appendix A): VLNS at `0100 mmmm llll 1011`; VEXT.B/W/L/Q at `0100 nnnn {1000..1011} 1011`; VINS.B/W/L/Q at `0000 nnnn {1000..1011} 1011`; VEXTF.L at `0100 nnnn 1100 1011` (nnnn = destination FRn); VINSF.L at `0000 nnnn 1100 1011` (nnnn = source FRn). Valid inside and outside SIMD blocks.

> **These encodings do not survive the collision sweep, and `VLNS`'s does not
> survive its own field layout.** Enumerated against the canonical database by
> the B4 sweep ([encoding-sweep.md §3.2](../encoding-sweep.md)); the encodings
> above are left as written because re-homing them is one decision, not five,
> and it is this document's to take.
>
> - **Four of the five `VEXT` slots are occupied on a J-Core variant**, not
>   merely on an SH one. `0100 nnnn 1000/1001/1010 1011` are SH-2A's
>   `mov.b/w/l R0,@Rn+` and `0100 nnnn 1100 1011` is `mov.b @-Rm,R0`, all live
>   on **J2A** and SH-2A. Only `VEXT.Q` at `1011` is free.
>   `cpugen freespace -avoid <all 13> -form '0100nnnn----1011'` leaves six free
>   minors: `0011`, `0101`, `0110`, `0111`, `1011`, `1111`.
> - **`VINS.L` at `0000 nnnn 1010 1011` is SH-4A `synco`** — `VINS.L R0` *is*
>   `synco`. That is a violation of Decision B2-5
>   ([../sh4-guest-model.md §5](../sh4-guest-model.md)), not a tidy-up, and it
>   is the one item in this block that has to move whatever else is decided.
>   The other four `VINS` slots are free.
> - **`VLNS` cannot be given a slot, because it does not want one.**
>   `0100 mmmm llll 1011` spends both nibble fields — `mmmm` on the source
>   register, `llll` on the lane index — so it claims **all 16 minors** of a
>   family with six free, and no free family of that shape exists in the map.
>   The same `llll` is the field §4.5 shows cannot address the lanes. One cause,
>   one fix: **the lane index has to leave the instruction word** — a GPR
>   operand, a second instruction word, or a width restriction — and `VEXT`/
>   `VINS` can be re-homed into their families' free minors once it has. Assembler accepts the single-mnemonic forms (`VEXT.L V5.2, R3` and `VEXTF.L V5.2, FR3`).

### 5.8 (retired) SIMD↔FPU boundary instructions

The former `FMOV.VS` / `FMOV.VD` boundary instructions existed **only** to move scalar FP between the dedicated VFPUL register and the FR/DR file. With **VFPUL retired** (Appendix B) and all FP scalar results — reductions (§2.3), `VFIPR`, `VFTRV` — written **directly to FR/DR at block exit**, there is nothing to bridge: these instructions are **removed**. FP lane↔scalar movement uses `VEXTF.L`/`VINSF.L` (§5.7), which now target FR directly. The section number is retained so cross-references resolve; the opcode space it reserved is returned to the reserved pool (Appendix A).

The four freed opcodes (formerly in the SH-4 FPU sub-family) return to the reserved pool (§7, Appendix A). The FR/DR-writeback that a reduction / `VFIPR` / `VFTRV` performs at block exit reuses the FPU's existing FR/DR write ports (including the 4-wide FTRV port) under the SR.FD-at-prefix-decode ownership rule (§2.4.1 rule **S-R1**; §2.3, §2.6) — no separate cross-file move instruction is required. Prior art for writing SIMD/vector results straight into the scalar FP file: SH-4 FTRV/FIPR themselves (1998); Intel SSE scalar-in-low-lane results (1999).

---

## 6. Exception Model

### 6.1 Interrupt deferral

External interrupts arriving while `SIMD_VAL = 1` or `V_LANE_VALID = 1` are held pending and delivered at the next architecturally-visible boundary (block exit, or VEXT/VINS retirement). Worst-case combined latency (32-bit-ALU J32): 34 cycles (32 for a 4-instruction block at 8 beats each + 2 for a VLNS+VEXT pair); it scales with VLEN and shrinks proportionally on a wider ALU.

Implementations may optionally support **mid-block interrupt with replay**: on interrupt, the block is abandoned, the saved PC is set to the prefix's PC, and the ISR is dispatched. This is permitted but not required, and is the recommended low-latency policy for out-of-order implementations.

On J32-OOO ([../ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md)) the natural realization is to crack the prefix and its governed group into a single **ROB atomic-commit group** (the same mechanism the OoO core already uses for `CAS.L`, [../ooo/j32ooo-spec.md §10](../ooo/j32ooo-spec.md)): the group commits all-or-nothing, and an interrupt arriving before commit flushes the whole group, sets the saved PC to the prefix PC (recoverable from the group's ROB entries), and dispatches the ISR. Because nothing in the group has committed, restart-from-prefix is **idempotent for an arbitrary compute block**, not only the N=1 memory case of §6.4 — the architectural V/P0/MAC state (and any FR/DR reduction target, which is written only at block commit) was never updated, so re-execution from the prefix reads the same source operands. Stores in the group must not drain to memory/coherence and post-increment / pre-decrement pointer updates must not commit until the group commits. This makes mid-block interrupt latency equal to a branch-mispredict flush rather than waiting for the block (and its slowest governed op — e.g. a per-lane `FDIV`) to retire. Implementations choosing this policy should bound consecutive flush-restarts of the same block (or fall back to deferral after a threshold) to guarantee forward progress under a high-frequency interrupt source.

### 6.2 Slot-illegal exception

Raised by:

- A reserved governed instruction (§5.3) or undefined SIMD encoding.
- SWIZZLE with a reserved pattern selector.
- A VEXT/VINS instruction with `V_LANE_VALID = 0`.
- Any instruction other than VEXT/VINS encountered with `V_LANE_VALID = 1`.
- A SIMDV prefix with `rrr` value reserved at the implementation's tier (e.g. `rrr=110/111` on a Tier 1 implementation; `rrr∈{010..111}` on a Tier 0-only implementation).
- A memory access instruction governed by a prefix with N > 1 (unless the implementation advertises `SIMD_RELAXED_MEM`, §5.6.1) or by a SIMDH prefix (always).
- A Tier 1 instruction (VABS, VPOPCNT, VUNPK4, VABSDIFF, VPACK, VMULSU, SIMDVS/SIMDVU saturation) on a Tier 0-only implementation.
- A Tier 2 instruction (VCLMUL.D, VCRC32C.B) on an implementation without Tier 2 support.
- VCLMUL.D outside `SIMDV.Q`, or VCRC32C.B outside `SIMDH<add>.B`.
- `SIMDVS`/`SIMDVU` + logical-only governed instruction (AND/OR/XOR/NOT/VPOPCNT).

The SR pushed on slot-illegal entry has `SIMD_VAL = 0` and `V_LANE_VALID = 0` (both microarchitectural latches are zero at all exception boundaries).

### 6.3 FP exception handling in SIMD context

**SIMD FP operations never deliver traps**, regardless of VCSR.IEE or FPSCR.EN. Software requiring IEEE 754 trap behaviour must use scalar FP.

- **Default mode (VCSR.IEE = 0):** denormals flushed to ±0, FPSCR.FLAG not updated, FPSCR.EN ignored, FPSCR.CAUSE not set. Cheapest to implement and matches the expectations of autovectorised code, DSP libraries, ML inference, graphics, audio.
- **IEEE-strict mode (VCSR.IEE = 1):** IEEE 754 gradual underflow; FPSCR.FLAG OR-accumulated across lanes (sticky until cleared via `LDS Rn, FPSCR`); FPSCR.EN still ignored.

Both bullets describe reads and writes of `FPSCR`, which is FPU state and not SIMD state. §2.4.1
rule **S-R1** requires the block to own the FPU (`SR.FD = 0`) before either can happen, and rule
**S-R2** makes that requirement independent of `VCSR.IEE` — the `FPSCR.RM` read is in *both* bullets
even though the `FPSCR.FLAG` write is in only one.

Minimal implementations may support only IEE = 0 (writes to IEE silently ignored, reads return 0).
This does not relax S-R1: such an implementation still reads `FPSCR.RM`.

Prior art: PowerPC AltiVec "Java mode" (1996), Intel SSE MXCSR-controlled trap-disabled default (1999), Cray-1 sticky-flag-only (1976), GCC/LLVM `-fno-trapping-math` default for vector code.

### 6.4 Memory exceptions and restart-from-prefix

VLD.Q, VST.Q, VGATHER.Q, VSCATTER.Q can raise standard SH-4 memory exceptions (address error, TLB miss / page fault, bus error).

**Memory faults inside SIMD blocks: restart-from-prefix.** Per the N=1 rule (§5.6.1), the saved PC points to **the prefix instruction**; block microarchitectural state is cleared; the exception handler runs in scalar context (need not be SIMD-aware); RTE returns to the prefix; the block re-opens and the memory access retries.

This restart is correct because the N=1 block contains only the memory access, with no committed compute. Loads are idempotent. Stores re-write the same data from an unchanged source register. Gathers and scatters re-execute per-lane (previously-completed lanes act as no-ops modulo memory ordering). Post-increment / pre-decrement modes commit only on success, so a faulting access does not advance the address register.

This makes software-managed TLB systems transparently compatible with SIMD code. See [hardware-impl.md §3](hardware-impl.md) for the restart microarchitecture.

### 6.5 Instruction-fetch faults inside a block (translated-memory implementations)

§6.4 covers *data*-side faults on governed load/store instructions. A separate hazard exists on the *instruction* side once address translation is enabled: a SIMD block is a run of consecutive halfwords (the prefix plus up to four governed instructions, ≤ 10 bytes; or a `VLNS`+`VEXT`/`VINS` pair, 4 bytes — §3.2, §5.7), and that run may straddle a page boundary. If the prefix lies on one page and a later governed instruction lies on a different page that misses the TLB / faults on fetch, a naive implementation takes the instruction-fetch exception *after* the prefix has set the decode shadow latch (`SIMD_VAL = 1`, [hardware-impl.md §2](hardware-impl.md)). Exception entry clears the shadow latch ([hardware-impl.md §3.2](hardware-impl.md)); after the handler maps the page and `RTE`s to the faulting governed instruction, that instruction would decode with `SIMD_VAL = 0` — i.e. as an ordinary scalar SH instruction operating on R-registers rather than lane-wise on V-registers. **Silent corruption.**

**Architectural rule (mandatory contract).** *Every synchronous fault taken with a SIMD block (or `VLNS` pair) open reports the prefix PC.* This generalizes the restart-from-prefix rule of §6.4 from data faults to instruction-fetch faults. The block carries no committed architectural state until it retires, so reporting the prefix PC always yields a correct, idempotent restart: the handler is SIMD-unaware, `RTE` returns to the prefix, and the block re-opens and re-executes from the beginning. The restart is correct only when the handler *fixes* the fault and retries (TLB miss / page fault); a non-recoverable instruction-fetch fault (e.g. a permission violation with no fixup) terminates the thread and never returns, so no resumption is required.

**Scope.** This hazard arises only when **both** (a) translation is enabled (MMU present, `MMUCR.AT = 1`) and the block sits in a translated segment (SH-4 P0/P3), **and** (b) the block spans a page boundary. A ≤ 10-byte block crosses at most one boundary at any supported page size (≥ 4 KB; the J-Core default is 16 KB — see [../mmu/design-spec.md §3.3](../mmu/design-spec.md)), and the prefix's own page is already known-good because the prefix was fetched from it. Implementations without an MMU (e.g. J2-class) and code running untranslated (P1/P2 kernel space) cannot raise it; a physical-bus error on an untranslated fetch is fatal (no retry) and therefore poses no resumption hazard.

**Resolution by product point.** The mandatory contract above is satisfiable three ways, matching the three implementation styles:

| Implementation | Mechanism |
|---|---|
| **J2 / J32 without MMU** | Nothing required — no translation means no recoverable instruction-fetch fault. |
| **J32 + TLB (in-order)** | **Prefix-time block-fetch validation** (below). |
| **J32-OOO** | The ROB atomic-commit group of §6.1 already reports the prefix PC on any flush, so an instruction-fetch fault on a governed uop flushes the group and restarts from the prefix with no extra mechanism. |

**Prefix-time block-fetch validation (in-order J32 + TLB).** The block length *N* is known at prefix decode (the `NN` field, §3.2), so the address of the block's last halfword, `end = prefix_PC + 2·N`, is known immediately. When `end` lies in a different page than `prefix_PC`, the implementation probes the fetch-translation of `end`'s page *before any governed instruction issues*, using the prefix's otherwise-idle memory/MA slot (the prefix performs no compute and no data access). A miss or fault on that probe is raised against the **prefix PC** (clean restart; the block never opens). Once the probe succeeds, every governed-instruction fetch in the block is guaranteed to translate, so a mid-block instruction-fetch fault becomes impossible. The same-page common case (the overwhelming majority at a 16 KB page — a ≤ 10-byte block crosses a boundary with probability ≈ 10/16384) needs only a page-number comparison and no probe. The `VLNS`+`VEXT`/`VINS` pair (§5.7) is validated identically by probing `prefix_PC + 2`. See [../mmu/hardware-spec.md §5.2](../mmu/hardware-spec.md) for the MMU-side requirement and verification point.

**Prior art.** The Intel 386 (1985) validates that an instruction whose encoding spans a page boundary is fully fetchable — faulting against the instruction's starting address — before it executes. A SIMD block is architecturally a single atomic fetch unit, so validating its entire fetch extent at the prefix is the same established technique.

---

## 7. Reserved encoding space (forward compatibility)

Inside SIMD blocks, the following encoding ranges are architecturally reserved. Future tier extensions may define instructions in these ranges without breaking existing binaries.

| Reserved range | Approx. codepoints | Anticipated use |
|---|---|---|
| BRA, BSR top nibbles `1010`/`1011` | 8192 | Future SIMD branch / predicated-block control |
| BT/BF top nibble `1000 1xxx` | 1024 | Per-lane conditional execution variants |
| LDC/STC/LDS/STS in `0100 ……` (minus the Tier 0 P0/VCSR sub-opcodes) | ~240 | Additional SIMD configuration register access |
| MOV.x loads/stores in `0001` and `0101` rows (minus gather/scatter/SWIZZLE.I sub-opcodes) | ~6000 | Stride loads, alignment hints |
| FPU unary row `1111 nnnn xxxx 1101`, slots 0..7 and 14..15 | ~144 V slots | Additional VEXT/VINS widths, future unary ops |
| Prefix `rrr` reserved bits | ~5 codepoints in SIMDV (110/111) | Halving arithmetic, future modifiers |
| TRAPA, SLEEP | 257 | Debug, vector breakpoint |
| MAC.W, MULL in `0000 ……` (MAC.L now consumed by VCRC32C.B; DMULU.L by VCLMUL.D; DMULS.L by VMULSU) | ~48 | Multi-issue MAC, extended-precision SIMD |
| CAS.L, DIV0S, DIV0U, DIV1 | ~16 | SIMD atomic operations, lane-wise division |
| Tier 3 (256-bit) | reserved entirely | J64 wide-vector extensions |

> **The `VINS` family is contended, and this table does not list it.**
> [../mmu/hardware-spec.md §3.1](../mmu/hardware-spec.md) retired seven
> encodings from `0000 nnnn xxxx 1011` and declares the resulting eight free
> slots "the first reserve for J4-only `0000 nnnn`-shaped instructions". §5.7 of
> this document already spends five of them on `VINS.B/W/L/Q` and `VINSF.L`.
> Neither document cited the other until the B4 sweep found it
> ([../encoding-sweep.md §3.3](../encoding-sweep.md)). The reserve is
> **contended, not free**; whichever way it is settled, it is settled between
> these two specs and not by whoever writes an instruction there first.

**Total Tier 0/1/2 reserved: ≈22,000 architecturally-reserved 16-bit codepoints** inside SIMD blocks. Ample headroom for incremental architectural growth.

---

## 8. Assembly syntax and worked examples

> **Note (VLEN).** These examples depict the instruction *mechanism*. Concrete
> byte offsets, lane counts, and mask constants are drawn at 128-bit granularity
> for readability; at the real width a full-vector `VLD.Q` moves **VLEN/8 bytes**
> (32 on J32, 64 on J64), a full-lane predicate is **XLEN bits** (`0xFFFFFFFF` on
> J32), and displacement constants between consecutive vectors scale to VLEN/8.
> Where an example is structurally tied to a 4-lane / 16-byte shape (the 4×4
> matrix, the 16×16 macroblock SAD), a 256-bit `VLD.Q` spans two such rows — pack
> or mask accordingly. Read every `16`/`0xFFFF`/`+16` below through this lens.

Reference assembler syntax (single-mnemonic forms):

```
SIMDV.B/.W/.L/.Q       #N
SIMDV.NT.B/.W/.L/.Q    #N            ; T0 (NT hint)
SIMDVS.B/.W/.L/.Q      #N            ; T1 (signed saturating)
SIMDVU.B/.W/.L/.Q      #N            ; T1 (unsigned saturating)
SIMDH<r>.B/.W/.L/.Q    #N            ; r ∈ {A, O, N, X, MN, MX, MNU, MXU}

VLD.Q   @Rm, Vn        / @Rm+,Vn / @(R0,Rm),Vn
VST.Q   Vn, @Rm        / @-Rm     / @(R0,Rm)
VMOV    Vm, Vn
VLDI.Q  #imm, Vn
SWIZZLE Vn, Vm
SWIZZLE.I Vn, #pat, #param
VGATHER.Q @(R0,Vm), Vn
VSCATTER.Q Vn, @(R0,Vm)

VEXT.B/W/L/Q Vm.lane, Rn             ; assembler emits VLNS+VEXT pair
VINS.B/W/L/Q Rm, Vn.lane
VEXTF.L      Vm.lane, FRn
VINSF.L      FRm, Vn.lane

VMKCHG
LDS  Rn, P0   /  STS P0, Rn
LDS  Rn, VCSR /  STS VCSR, Rn

; Tier 1
VABS Vn         /  VPOPCNT Vn
VUNPK4LU Vn / VUNPK4HU Vn / VUNPK4LS Vn / VUNPK4HS Vn
VABSDIFF  Vm, Vn
VPACK.SS  Vm, Vn / VPACK.SU Vm, Vn / VPACKW.SS Vm, Vn / VPACKW.SU Vm, Vn
VMULSU    Vm, Vn

; Tier 2
VCLMUL.D  Vm, Vn       ; legal only under SIMDV.Q
VCRC32C.B Vm, Vn       ; legal only under SIMDHA.B
```

### 8.1 Tier 0 examples

**4×4 single-precision matrix-vector multiply.** Each row's dot product writes to DR0 (FP32 lanes widened to FP64 per §2.3), then narrowed via FCNVDS and inserted into V5 lane-by-lane:

```
    VLD.Q    @R_mat,    V0
    VLD.Q    @(R_mat+16), V1
    VLD.Q    @(R_mat+32), V2
    VLD.Q    @(R_mat+48), V3
    VLD.Q    @R_vec,    V4

    SIMDH.L  #1
    FMUL     V0, V4                  ; V0 · V4 per lane, widened sum → FR0 (implied FP dest)
    ; the row's dot product is already in FR0 — no boundary move
    VINSF.L  V5.0, FR0               ; insert FR0 into V5 lane 0 (VLNS V5,#0; VINSF.L FR0)
    ; ... rows 1..3: reduce into FR0, VINSF.L into V5 lanes 1..3 ...
    VST.Q    V5, @R_result
```

(Note: the reduction result lands directly in the implied FR0 — the FP analogue of
an integer reduction landing in MACL — so there is no boundary move. The task must
own the FPU (SR.FD=0), checked at the `SIMDH.L` prefix, §2.3/§2.6. `VFTRV` does all
four rows at once with a named FV destination; see [gpu/simd-gpu-spec.md](gpu/simd-gpu-spec.md).)

**Vertical SIMD-FP FMA loop.** With multiplier broadcast (A) in V0:

```
loop:
    VLD.Q    @R_y, V2
    VLD.Q    @R_x, V1
    SIMDV.L  #1
    FMAC     FR1, FR2                ; V2 ← V0 · V1 + V2
    VST.Q    V2, @R_y
```

**Predicated FP32 update.** Add V2 to V1 only where `V1 > 0`:

```
    SIMDV.L  #1
    FCMP/GT  FR3, FR1                ; P0[i·4] ← (V1[i] > 0)
    VMKCHG                           ; VCSR.MKE ← 1
    SIMDV.L  #1
    FADD     FR2, FR1                ; predicated
    VMKCHG                           ; restore
```

**Sparse vector dot product with VGATHER.Q.** Inner loop of CSR SpMV (full version reproduced in the archived spec-v0.5 §9.7):

```
loop:
    VLD.Q   @R4+, V0                 ; dense x[i..i+VLEN/32−1] (FP32; 8 lanes on J32)
    VLD.Q   @R5+, V1                 ; matching indices (int32)

    SIMDV.L #1
    VGATHER.Q @(R0,V1), V2           ; per-lane addr = R0 + V1.lane[k] · 4

    SIMDHA.L #1
    FMUL    FR2, FR0                 ; widen-sum → DR0

    FCNVDS  DR0, FPUL
    FSTS    FPUL, FR1
    FADD    FR1, FR3
```

### 8.2 Tier 1 examples

**INT8 GEMV (signed weights × unsigned activations).**

```
        CLRMAC
.loop:
        VLD.Q    @R4+, V1            ; VLEN/8 int8 weights (32 on J32)
        VLD.Q    @R5+, V2            ; VLEN/8 uint8 activations
        SIMDH.B  #1
        VMULSU   V1, V2              ; MACL += Σ int16(int8(V1[i]) × uint8(V2[i]))
        DT       R0
        BF       .loop
```

**16×16 SAD (video motion estimation).**

```
        CLRMAC
        MOV      #16, R0
.row:
        VLD.Q    @R4+, V1
        VLD.Q    @R5+, V2
        SIMDH.B  #1
        VABSDIFF V2, V1              ; MACL += Σ |V1[i] - V2[i]|
        DT       R0
        BF       .row
```

**Audio mixing with hard limiting (saturating add).**

```
        VLD.Q    @R4+, V1
        VLD.Q    @R5+, V2
        SIMDVS.W #1
        ADD      V2, V1              ; V1 := sat_s16(V1 + V2) — no overflow distortion
        VST.Q    V1, @R8
```

**XOR-popcount Hamming distance (bioinformatics / SimHash / LDPC).**

```
        VLD.Q    @R4+, V1
        VLD.Q    @R5+, V2
        SIMDV.B  #1
        XOR      V2, V1
        SIMDH.B  #1
        VPOPCNT  V1                  ; MACL += hamming weight of V1
```

**Saturating requantization chain after MAC.** Pack int32 → int16 → uint8 with saturation at each stage:

```
        SIMDV.W  #1
        VPACKW.SS V1, V2            ; int32 → int16 signed saturating
        SIMDVU.B  #1
        VPACK.SU  V2, V3            ; int16 → uint8 unsigned saturating
```

Additional Tier 1 examples (INT4 weight unpack, BAM nucleotide unpack, 4-disk SAD video block, k-mer Hamming for short-read alignment, 8-track audio mixer, etc.) are preserved in [archive/spec-v0.6.md §9](archive/spec-v0.6.md).

### 8.3 Tier 2 examples

**CRC-32C tight loop.** VLEN/8-byte chunks (32 on J32, 64 on J64) with predicated tail handling:

```
        ; r4 = buffer, r5 = byte length
        MOV     #-1, r0              ; CRC seed = 0xFFFFFFFF
        ; ... software loads r0 into V0[31:0] using VINS.L (see software-impl.md §3) ...
.loop:
        ; While length ≥ VLEN/8: full-mask fold (VLEN/8 bytes per pass).
        VLD.Q     @R4+, V1
        MOV       #-1, R2              ; all XLEN lane bits set (0xFFFFFFFF on J32)
        LDS       R2, P0
        VMKCHG                       ; enable mask
        SIMDHA.B  #1
        VCRC32C.B V1, V0             ; V0[31:0] ← crc32c_fold(V0[31:0], V1, mask)
        VMKCHG
        ; ... loop bookkeeping ...

        ; Tail (0..VLEN/8−1 bytes): predicated, single instruction
        MOV       #tail_mask, R2     ; mask = (1u<<len)-1
        LDS       R2, P0
        VMKCHG
        SIMDHA.B  #1
        VCRC32C.B V_tail, V0         ; only `len` low bytes participate
        VMKCHG

        ; Finalize: ~V0[31:0] is the CRC-32C output
```

**AES-GCM GHASH (Karatsuba 128×128).** Five VCLMUL.D operations per 16-byte block (three for the Karatsuba product, two for Montgomery reduction); see [software-impl.md §6.2](software-impl.md) for the full kernel.

```
        ; V1 = a, V2 = b. SWIZZLE.I isolates the desired half — INSIDE the block.
        SIMDV.Q  #2                   ; vertical 64-bit lanes, 2 governed slots
        SWIZZLE.I V1, #0, #0          ; slot 1: a_lo to low 64 (in-block permute)
        VCLMUL.D V2, V1               ; slot 2: V1 ← a_lo ⊗ b_lo
        ; ... full Karatsuba sequence (3 CLMULs + reduction) in software-impl.md §6.2 ...
```

**RAID-6 Q syndrome (GF(2^8) generator multiply).** Pattern: one VCLMUL.D per data byte against the generator constant, followed by polynomial reduction modulo 0x11D (full kernel in [software-impl.md §6.3](software-impl.md)).

---

## 9. Application domain map

The cumulative beneficiary surface across the three implemented tiers:

| Domain | Tier 0 | Tier 1 | Tier 2 | Representative algorithms |
|---|---|---|---|---|
| ML inference (INT8/INT4) |   | ✔ |   | INT8 GEMV (VMULSU), INT4 weight unpack (VUNPK4), saturating requant (VPACK + SIMDVS) |
| Video coding |   | ✔ |   | H.264/HEVC/AV1 SAD (VABSDIFF + SIMDH<add>), motion estimation |
| Bioinformatics |   | ✔ |   | k-mer Hamming (XOR + VPOPCNT), BAM nucleotide unpack (VUNPK4), FM-index rank |
| Computer vision |   | ✔ |   | Sobel/Prewitt (VABS), ORB binary descriptors (XOR + VPOPCNT), stereo SAD |
| DSP / audio |   | ✔ |   | FIR/IIR with sat MAC, audio mixer (SIMDVS + ADD), pitch detection (VABSDIFF) |
| Comms / channel coding |   | ✔ | ✔ | Viterbi (VABSDIFF), LDPC syndrome (VPOPCNT), CRC32C (VCRC32C.B), Reed-Solomon (VCLMUL.D) |
| Database analytics |   | ✔ |   | Roaring bitmaps (VPOPCNT), HyperLogLog, SimHash, MinHash |
| Games / simulation |   | ✔ |   | Chess/Go bitboards (VPOPCNT), Game of Life, kNN-DTW |
| Cryptanalysis |   | ✔ |   | Linear cryptanalysis bias, S-box analysis, hamming-weight DPA models |
| Storage | ✔ | ✔ | ✔ | RAID-6 (VCLMUL.D), btrfs/ZFS checksums (VCRC32C.B), NVMe-oF digests |
| Networking |   |   | ✔ | iSCSI/SCTP digests, RoCEv2 (VCRC32C.B), AES-GCM (VCLMUL.D) |
| Cryptography |   |   | ✔ | AES-GCM (GHASH), ChaCha20-Poly1305 alt, Carter-Wegman hashing |
| FEC |   |   | ✔ | Reed-Solomon (DVB-S2, CCSDS), BCH syndrome (VPOPCNT optional) |
| Post-quantum |   |   | ✔ | HQC code-based KEM (GF(2) polynomial multiply via VCLMUL.D) |
| Compression |   |   | ✔ | gzip/zlib CRC folding (VCLMUL.D + software constants for CRC-32-IEEE) |
| Scientific / autovec | ✔ |   |   | Generic vertical/horizontal FP & integer kernels, SpMV (gather), reductions |

Combined named-algorithm count across Tiers 0+1+2: ≈ 70+ algorithms in production use. Tier 0 costs 2096 architectural bits, which is structural. The per-tier **area** cost — the number this paragraph's amortisation argument needs — is unknown at this stage — needs measurement: no tier has been synthesized for the ULX3S/ECP5 or for gf180, and [hardware-impl.md §11.1](hardware-impl.md) is the authority for it when it exists. The argument the cost amortises across a wide algorithm surface stands on the algorithm count alone.

---

## 10. Implementation tier selection

Implementations are free to pick any subset `{Tier 0} ∪ Tier_set ⊆ {Tier 1, Tier 2}` and to advertise their support via the implementation feature register (§16). Tier 3 is excluded until specified. Suggested product mappings:

- **J32:** Tier 0+1 (ML, signal processing, analytics, video).
- **J32-OOO:** Tier 0+1 (the OoO spec cracks the prefix; same SIMD coverage as J32). May additionally advertise the optional `SIMD_RELAXED_MEM` capability (§5.6.1), which lifts the N=1 memory-block restriction; this is a one-way-compatible microarchitectural feature, not a tier.
- **J32-FM:** Tier 0+1+2 (adds crypto, FEC, storage, post-quantum).
- **J64:** Tier 0+1+2+3 (Tier 3 yet to be specified).

Partial-Tier-1 implementations are allowed (per the v0.6 §10 subset menus — bitmap, vision, DSP, LLM). Tier 2 is all-or-nothing (both VCLMUL.D and VCRC32C.B, or neither, since VCRC32C.B's recommended implementation is decode-stage fusion onto VCLMUL.D — see [hardware-impl.md §6.2](hardware-impl.md) — though a stand-alone LFSR-only VCRC32C.B variant remains permitted).

---

## 11. Open questions

The following are deferred:

1. **Narrow floating-point formats.** FP16 (IEEE 754-2008 binary16) is the only narrow format pre-2006 prior art admits cleanly (Hitachi HD61810 1982, Scott WIF 1991, 3dfx Voodoo 1995, SGI/OpenEXR 1997, NVIDIA Cg 2002). **Now specified in [gpu/simd-gpu-spec.md §8](gpu/simd-gpu-spec.md)** (lane type, FP32-accumulate reductions, VCVT.HS/SH, scalar FCNVSH/FCNVHS recommendation). bfloat16, FP8 (E4M3/E5M2), FP4 (MXFP4/NVFP4) are deliberately excluded for patent reasons; see Appendix E.
2. **Non-widening SIMDH variant.** If real workloads show the FP32-in/FP32-out widening cost dominates, a non-widening SIMDH-add could be added.
3. **Multiple predicate registers.** P0..P3 or P0..P7 could be added in reserved encoding space.
4. **Mid-block interrupt with replay.** Currently implementation-defined (§6.1). Promote to architectural with precise semantics if any J-core licensee requires it.
5. **Tier 3 (256-bit).** J64 wide-vector extensions. Whether Tier 0/1/2 instructions transparently promote to 256-bit or whether Tier 3 adds distinct opcodes is the principal open question.
6. **Tier 2 multi-stream / vertical-parallel CRC.** Currently single-stream. A vertical-SIMD CRC variant under a SIMDV prefix could exploit the upper VLEN−32 bits of the accumulator register for parallel streams.
7. **GHASH reduction constants.** Well-known (Gueron-Kounavis 2009); package as a header constant table for library reuse.
8. **HWCAP bit allocation.** A new `HWCAP_JCORE_GF2` (and per-tier feature bits), plus the microarchitectural-capability bit `HWCAP_JCORE_SIMD_RELAXED_MEM` (§5.6.1), must be assigned in the jcore Linux port. See [software-impl.md §8.5](software-impl.md).

---

## Appendix A. Encoding Summary

### A.1 Prefixes (outside SIMD block)

```
SIMDV<r>.w  #N         1111 0ww<rrr> NN 1111
SIMDH<r>.w  #N         1111 1ww<r>   NN 1111

SIMDV modifier-field (rrr):
  000 = wrap (T0 default)
  001 = wrap + NT (Tier 0 non-temporal memory hint)
  010 = signed saturating (Tier 1)
  011 = signed sat + NT (Tier 1)
  100 = unsigned saturating (Tier 1)
  101 = unsigned sat + NT (Tier 1)
  110 = reserved
  111 = reserved

Reduction-operator field (rrr, SIMDH only, Tier 0):
  000 = add (default; sum)               100 = min (signed / IEEE minNum)
  001 = OR  (bitwise)                    101 = max (signed / IEEE maxNum)
  010 = AND (bitwise)                    110 = min unsigned (integer only)
  011 = XOR (bitwise)                    111 = max unsigned (integer only)
```

### A.2 Governed instructions (inside SIMD block)

```
INTEGER (Tier 0, SH-2 reinterpretation):
  ADD/SUB/AND/OR/XOR/NEG/NOT/MULS.W/MULU.W/SHAD/SHLD/CMP{EQ,GE,GT}
    interpret Rn/Rm as V<n>/V<m> indices

FP (Tier 0, SH-4 reinterpretation):
  FADD/FSUB/FMUL/FDIV/FCMP{EQ,GT}/FMAC interpret FRn/FRm as V<n>/V<m>

COMPARISONS (Tier 0):
  CMP/*, FCMP/* write per-lane results to P0

SWIZZLE (Tier 0, inside SIMD block only):
  SWIZZLE  Vn, Vm        1111 nnnn mmmm 1111   (register-controlled)
  SWIZZLE.I Vn,#pat,#par 0001 nnnn pppp dddd   (immediate; dddd ∈ 0010..1111)

VECTOR MEMORY (Tier 0):
  VLD.Q    @Rm, Vn       1111 nnnn mmmm 1000
  VLD.Q    @Rm+, Vn      1111 nnnn mmmm 1001
  VST.Q    Vn, @Rm       1111 nnnn mmmm 1010
  VST.Q    Vn, @-Rm      1111 nnnn mmmm 1011
  VLD.Q    @(R0,Rm), Vn  1111 nnnn mmmm 0110
  VST.Q    Vn, @(R0,Rm)  1111 nnnn mmmm 0111
  VGATHER.Q @(R0,Vm),Vn  0001 nnnn mmmm 0000
  VSCATTER.Q Vn,@(R0,Vm) 0001 nnnn mmmm 0001

VECTOR REGISTER MOVE (Tier 0):
  VMOV     Vm, Vn        1111 nnnn mmmm 1100

VECTOR IMMEDIATE BROADCAST (Tier 0):
  VLDI.Q   #imm, Vn      1110 nnnn iiii iiii

LANE EXTRACT/INSERT (Tier 0; valid in or out of SIMD blocks):
  VLNS Vm, #lane         0100 mmmm llll 1011
  VEXT.B Rn              0100 nnnn 1000 1011
  VEXT.W Rn              0100 nnnn 1001 1011
  VEXT.L Rn              0100 nnnn 1010 1011
  VEXT.Q Rn,Rn+1         0100 nnnn 1011 1011   ; Rn must be even
  VEXTF.L FRn            0100 nnnn 1100 1011   ; destination FRn (scalar FPU); needs SR.FD=0
  VINS.B Rn              0000 nnnn 1000 1011
  VINS.W Rn              0000 nnnn 1001 1011
  VINS.L Rn              0000 nnnn 1010 1011
  VINS.Q Rn,Rn+1         0000 nnnn 1011 1011
  VINSF.L FRn            0000 nnnn 1100 1011   ; source FRn (scalar FPU); needs SR.FD=0

SIMD↔FPU BOUNDARY (§5.8): RETIRED with VFPUL. The former FMOV.VS/FMOV.VD opcodes
  are freed to the reserved pool; FP scalars live in FR/DR directly (§2.3).

(No VFPUL control-register access — VFPUL retired.)

PREDICATION AND CONTROL (Tier 0, outside SIMD block):
  VMKCHG                 1111 1100 1111 1101
  LDS Rn, P0             0100 nnnn 1000 1010
  STS P0, Rn             0000 nnnn 1000 1010
  LDS Rn, VCSR           0100 nnnn 1001 1010
  STS VCSR, Rn           0000 nnnn 1001 1010

TIER 1 UNARY (FPU unary row slots 8..13):
  VABS      Vn           1111 nnnn 1000 1101
  VPOPCNT   Vn           1111 nnnn 1001 1101
  VUNPK4LU  Vn           1111 nnnn 1010 1101
  VUNPK4HU  Vn           1111 nnnn 1011 1101
  VUNPK4LS  Vn           1111 nnnn 1100 1101
  VUNPK4HS  Vn           1111 nnnn 1101 1101

TIER 1 REINTERPRETED 2-OPERAND (in SIMD block; SH-2 ops outside):
  VABSDIFF  Vm, Vn       0011 nnnn mmmm 1010   (was SUBC)
  VPACK.SS  Vm, Vn       0110 nnnn mmmm 1110   (was EXTS.B)
  VPACK.SU  Vm, Vn       0110 nnnn mmmm 1100   (was EXTU.B)
  VPACKW.SS Vm, Vn       0110 nnnn mmmm 1111   (was EXTS.W)
  VPACKW.SU Vm, Vn       0110 nnnn mmmm 1101   (was EXTU.W)
  VMULSU    Vm, Vn       0011 nnnn mmmm 1101   (was DMULS.L)

TIER 2 REINTERPRETED 2-OPERAND (in SIMD block):
  VCLMUL.D  Vm, Vn       0011 nnnn mmmm 0101   (was DMULU.L; required: SIMDV.Q)
  VCRC32C.B Vm, Vn       0000 nnnn mmmm 1111   (was MAC.L; required: SIMDHA.B)

KEY:
  ww:   00=byte (FP16 illegal), 01=word/FP16, 10=long/FP32, 11=quad/FP64
  NN:   N−1, so 00=1, 01=2, 10=3, 11=4 governed instructions per block
  H/V:  0=vertical, 1=horizontal
  nnnn,mmmm: 4-bit V<n>/V<m>/FRn/Rn index
  llll: 4-bit lane index
  pppp: 4-bit SWIZZLE pattern selector
  dddd: 4-bit pattern parameter (or sub-opcode discriminator)
  iiii iiii: 8-bit signed immediate (sign-extended by VLDI.Q)
```

### A.3 Tier 2 opcode-bit derivation

The Tier 2 instructions consume two of the v0.5/v0.6-reserved 2-operand slots:

- **VCLMUL.D = `0011 nnnn mmmm 0101`** reinterprets SH-2 `DMULU.L Rm, Rn`. This row is in v0.5 §8's "MAC.W, MAC.L, MULL, DMULS, DMULU in `0000`/`0010` rows" reserved space (slightly extended to include `0011 ……` row entries, which v0.5 §5.4 lists as "decoded but undefined"). v0.6 took the parallel `0011 nnnn mmmm 1101` slot (DMULS.L → VMULSU); Tier 2 takes the `0011 nnnn mmmm 0101` slot (DMULU.L) directly next to it. No collision with v0.6.
- **VCRC32C.B = `0000 nnnn mmmm 1111`** reinterprets SH-2 `MAC.L @Rm+,@Rn+`. Reserved by v0.5 §5.4 ("MAC.W, MAC.L, ... are architecturally undefined and reserved for future use") and unconsumed by v0.6 (v0.6 Appendix A still notes ~63 codepoints free in this category).

Both selections honour the layout convention of v0.5 §3 (top-op | Vn-or-Vd | Vm-or-Vs | sub-op nibbles) and follow the existing 2-operand SH-2 encoding template. The width-lock approach (legal only under `SIMDV.Q` or `SIMDHA.B`) avoids needing a width field inside the instruction word and matches v0.6's `VPACK`/`VPACKW` pattern of "lane-width comes from the prefix".

---

## Appendix B. Decision Log (consolidated)

This appendix summarises the architectural evolution that led to this consolidated specification. The full per-version delta history is preserved in [archive/spec-v0.5.md Appendix B](archive/spec-v0.5.md).

- **2026-09-09 — Wave-3 C1c: FP SIMD requires FPU ownership, not just FP-scalar writeback (§2.4.1).** §2.1's "no SIMD instruction reads or writes FR/DR/FPUL/FPSCR **except** the FP-scalar writeback" was false against this document's own §2.4 (every governed FP op reads `FPSCR.RM`; under `VCSR.IEE = 1` writes `FPSCR.FLAG`) and §5.7 (`VEXTF.L`/`VINSF.L` read and write `FRn`), and the FPU-ownership requirement it carried covered only the writeback. A **vertical** FP block therefore read and wrote `FPSCR` with `SR.FD = 1` — the control-only escape [../fpu/spec.md §6.3](../fpu/spec.md) says does not exist — taking its rounding mode from, and its sticky flags to, the parked FPU owner's register. **Fixed:** rule S-R1 requires `SR.FD = 0` for any block containing an FP operation. **Cost accepted:** the SR.VD/SR.FD coupling §2.3 accepted for FP *reductions* now covers all FP SIMD; integer SIMD keeps full independence. **Rejected alternative:** shadow `RM`/`FLAG` in `VCSR` — it would decouple the files at the price of `VFIPR`/`VFTRV` rounding differently from scalar `FIPR`/`FTRV` while writing the same `FR0`, and of a SIMD default rounding mode different from the scalar one. **Not a cross-tenant channel:** C1b's FP-R1/FP-R3 already name `FPSCR` in the scrub, so nothing was added to §2.6.1 or to the gang-switch list.
- **2026-09-09 — Wave-3 C1c: the kernel-mode discipline is a scrub, not a disable bit (§2.6.2).** Setting `SR.VD = 1` on exit from a kernel SIMD critical section does not protect the V file, because the trap it raises lands in §2.6's handler, whose first two branches — owner-unchanged, and no-saved-image — both write nothing. No architecture in `linux@origin/jcore` scrubs at `kernel_fpu_end`; they are safe because their return-to-user reloads unconditionally, which this lazy model does not.
- **v0.1–v0.3 (archived):** prefix-modal SIMD developed atop SH-4 FPU register aliasing; predicate register P0 added in v0.3.
- **v0.4 (archived):** dedicated V0..V15 register file introduced; FPU-alias model abandoned; anchor field removed; vector load/store specified.
- **v0.5 → Tier 0 in this document:** VCSR introduced as dedicated SIMD control register; trap-free SIMD FP exception model (two modes via VCSR.IEE); expanded reduction operators (add/OR/AND/XOR/min/max/min-u/max-u); VGATHER.Q/VSCATTER.Q; VLDI.Q broadcast-immediate; SWIZZLE.I pattern-immediate; VLNS+VEXT/VINS lane-bridge pair; N=1 memory-access rule with restart-from-prefix.
- **v0.6 → Tier 1 in this document:** saturating-arithmetic modifier on SIMDV (`SIMDVS`/`SIMDVU`); VABS, VPOPCNT, VUNPK4 family; VABSDIFF (SAD primitive), VPACK family (saturating narrowing pack), VMULSU (mixed-sign multiply — VNNI-equivalent for INT8 GEMV).
- **VCLMUL design spec → Tier 2 in this document:** VCLMUL.D (64×64 → 128-bit GF(2) carryless multiply) and VCRC32C.B (CRC-32C folding step). This consolidation **finalises the previously-TBD opcode bits** (Appendix A.3): VCLMUL.D at `0011 nnnn mmmm 0101`, VCRC32C.B at `0000 nnnn mmmm 1111`. The 256-bit "performance tier on J64" mention in the original VCLMUL design spec is now **superseded** by the VLEN = 8 × XLEN discipline (§1.2): 256-bit is the **J32** baseline and 512-bit the J64 baseline, so VCLMUL.D/VCRC32C.B are specified against VLEN-wide registers (256 on J32-FM, 512 on J64). Tier 3 is redefined as reserved space for width growth *beyond* VLEN (§1.1), not for 256-bit itself.
- **Syntax normalization:** all examples now use `SIMDV.w`/`SIMDH<op>.w` mnemonics. The vclmul-* `vprefix.v.d` skin is dropped (§3.1).
- **2026-07-17 — VLEN = 8 × XLEN (predicate-driven width).** Vector width was fixed to 8× the integer register width (256-bit J32 / 512-bit J64), because P0 is an integer GPR holding one bit per byte-lane (§1.2). Supersedes the earlier "128-bit mandatory / 256-bit = Tier 3" discipline; Tier 3 redefined as growth beyond VLEN.
- **2026-07-17 — geometry extension (FIPR/FTRV promoted).** SH-4 FIPR/FTRV promoted into the V-file as segmented horizontal reductions ([gpu/simd-gpu-spec.md](gpu/simd-gpu-spec.md)), reusing the SWIZZLE crossbar + horizontal add tree.
- **2026-07-17 — VFPUL retired; FP reductions write FR/DR (reverses the §2.6 v0.4-era decision).** Earlier revisions routed FP-scalar reduction results to a *dedicated* SIMD-side register **VFPUL**, explicitly to keep SIMD register-file-disjoint from the FPU and to make SR.VD/SR.FD lazy-save universally independent; consuming a result in FR required a `FMOV.VS/VD` boundary move (§5.8). **Reversed:** FP reductions / `VFIPR` / `VFTRV` now write **FR0/DR0** *directly* (implied FR0 base — a *G*-group segmented reduction writes FR0..FR(G−1), so VFTRV→FV0), symmetric with integer reductions writing MACL/MACH. **Why the original objection dissolved:** the objection was mid-block FPU traps forcing block restart (§4.2); but a reduction's result exists only at *block exit*, so the FR/DR write and its SR.FD-ownership check are hoisted to prefix/block decode — a clean instruction boundary, never mid-block. **Gains:** removes VFPUL (−8 B context → 520 B J32 / 1036 B J64; −64 arch bits), deletes the four `FMOV.VS/VD` boundary instructions (opcodes freed) and the VFPUL LDS/STS access, reuses the FPU's existing FTRV/FIPR 4-wide writeback port, and makes `VFTRV`→FV0 / `VFIPR`→FR0 bit-compatible with SH-4 register semantics (a win for the Dreamcast HLE path). **Cost accepted:** a task doing FP SIMD reductions now couples SR.VD+SR.FD (must own the FPU) — deemed the honest coupling, since such a task is doing FP math; integer SIMD and FPU-only tasks keep full lazy-save independence.

---

## Appendix C. Prior art (consolidated, pre-2006 only)

Per the project-wide prior-art-pre-2006 policy ([../glossary.md §2](../glossary.md)), every technique in this specification must be backed by published prior art predating 2006. This appendix collects the citations, organised by mechanism. Sources after 2005 are flagged.

### C.1 Tier 0 mechanisms

#### C.1.1 Prefix-modal SIMD (§3.2)

- **ARM Thumb-2 IT block** (ARMv6T2, 2003). 16-bit prefix governs 1–4 following instructions.
- **IA-64 / Itanium template + stop bits** (Intel/HP, 1998–2000). Bundle-level metadata controls contained instruction dispatch.
- **SH-DSP repeat block** (Hitachi, 1996). LDRS/LDRE/SETRC set state that governs a subsequent block.
- **Cray-1 VL register** (Cray Research, 1976). Sets lane count for subsequent vector operations.
- **Multiflow TRACE VLIW** (1984). Wide instruction encodes behaviour of multiple operations.

#### C.1.2 Predication via persistent mask (§2.5, §4.3, §4.4)

- **Cray-1 vector mask register VM** (1976). Set by scalar copy or vector compare; consumed by merge instructions; persistent architectural state.
- **HP PA-RISC nullification** (1986). Per-instruction conditional nullification.
- **IA-64 predicate register file** (Intel/HP, 1998–2000). 64 architectural predicate registers, decoupled from comparison setup.
- **TMS320C6x VelociTI** (TI, 1997). VLIW predicates set by ordinary compare/move.
- **Multiflow TRACE predicated execution** (1984).

#### C.1.3 Dedicated SIMD register file (§2.1)

- **Cray-1 V registers** (1976), 8 × 64 × 64-bit, separate from S and A files.
- **CDC STAR-100** (CDC, 1974), architecturally-visible vector facility.
- **Convex C-1** (1985), 8 vector registers separate from scalar files.
- **NEC SX-2** (1985), 40 dedicated vector data registers.
- **Intel SSE XMM registers** (1999), 8 × 128-bit, separate from x87 / MMX.
- **PowerPC AltiVec / VMX** (1996–1999), 32 × 128-bit, separate from GPR / FPR.

#### C.1.4 Vector permutation (§3.3, §4.5, §5.6)

- **Cray-1 compress/expand** (1976), VM-controlled.
- **HP PA-RISC MAX-2 PERMH** (1995–1996), immediate-controlled halfword permute (Lee, IEEE Micro Jul/Aug 1996).
- **Sun VIS BSHUFFLE/BMASK** (1995–1996, IEEE Micro 1996).
- **Intel MMX PSHUFW** (1996, Peleg & Weiser IEEE Micro 1996); **SSE SHUFPS** (1999), **SSE2 PSHUFD** (2001).
- **MIPS MDMX pshu** (1996).
- **PowerPC AltiVec VPERM / vec_perm** (1996–1999) — direct precedent for register-controlled SWIZZLE with out-of-range-produces-zero semantics.

#### C.1.5 Vector-indexed memory (§5.6)

- **CDC STAR-100** (1974), indirect-addressing vector ops.
- **Cray-1 gather** (1976), constant-stride.
- **Cray X-MP** (1982), arbitrary-index GATHER/SCATTER — *the* foundational prior art for the modern operation, with structural identity to VGATHER.Q.
- **Fujitsu VP-200** (1982), **NEC SX-2** (1985), **Convex C-1** (1985), **Cray Y-MP** (1988), **NEC SX-3** (1989) — successor architectures continuing the design.
- **Espasa & Valero**, "Vector Architectures: Past, Present and Future," Supercomputing '98 (survey).

#### C.1.6 Non-temporal memory hints (§3.2, §5.6.2)

- **PowerPC dcbt / dcbtst** (1993).
- **PowerPC AltiVec dst / dstt / dstst** (1996–1999) — direct precedent for the NT-as-transient-stream hint.
- **SPARC V9 PREFETCH** (1994).
- **MIPS PREF / PREFX** (1996).
- **Intel SSE MOVNTPS / PREFETCHNTA** (1999), **MOVNTPD / MOVNTI** (2001).

#### C.1.7 Trap-free SIMD FP (§6.3)

- **Cray-1** (1976), sticky-flag-only FP with no traps.
- **PowerPC AltiVec VSCR "Java mode"** (1996), non-Java FTZ vs Java IEEE-strict; neither trapping.
- **Intel SSE MXCSR** (1999), trap-disabled default.

### C.2 Tier 1 mechanisms

| Tier 1 feature | Prior art | Year | Source |
|---|---|---|---|
| Saturating ADD/SUB | MMX PADDSB/PADDSW/PSUBSB/PSUBSW | 1996 | Intel IA-32 SDM, MMX chapter |
| Saturating ADD/SUB | AltiVec vaddsbs/vaddshs/vsubsbs/vsubshs | 1996/1999 | AltiVec PEM §6.13–6.18 |
| Saturating ADD/SUB | Cray-1 vector saturating mode | 1976 | Cray-1 HRM (HR-0004) |
| Saturating ADD/SUB | TMS320C6000 saturating MAC | 1997 | TI SPRU189 |
| VABS | MIPS MDMX (via MIN.OB R0 + sign extract) | 1996 | MIPS V instruction set |
| VABS | ARMv6 USAD8 building block (implicit ABS) | 2002 | ARM ARM v6 |
| VABS | SSSE3 PABSB/PABSW/PABSD | 2006 | **Within cutoff (March 2006).** Independent earlier prior art (MIPS MDMX 1996, ARMv6 2002) suffices on its own. |
| VPOPCNT (scalar) | CDC 6600 CXi count | 1964 | Thornton, *Design of a Computer: The CDC 6600* |
| VPOPCNT (vector) | CDC STAR-100 bit-count vector | 1974 | CDC STAR-100 Programming Reference |
| VPOPCNT | DEC Alpha CTPOP | 1996 | Alpha AXP ARM |
| VPOPCNT | SPARC V9 POPC (optional) | 1994 | SPARC V9 Architecture Manual |
| VUNPK4 (composition) | BCD packed-decimal storage | 1959 | IBM 1401 Reference Manual |
| VUNPK4 (composition) | MMX PUNPCKLBW; AltiVec vmrglb | 1996 | as above |
| VABSDIFF / SAD | DEC Alpha PERR (sum-of-byte-differences) | 1996 | Alpha AXP ARM |
| VABSDIFF / SAD | MIPS MDMX RACL.OB / RACM.OB | 1996 | MIPS V instruction set |
| VABSDIFF / SAD | Intel SSE PSADBW | 1999 | Intel IA-32 SDM (P-III) |
| VABSDIFF / SAD | ARMv6 USAD8 / USADA8 | 2002 | ARM ARM v6 |
| VPACK (signed sat) | MMX PACKSSWB / PACKSSDW | 1996 | Intel IA-32 SDM |
| VPACK (unsigned sat) | MMX PACKUSWB | 1996 | as above |
| VPACK | AltiVec vpkshss/vpkshus/vpkswss/vpkswus | 1996/1999 | AltiVec PEM §6.79–6.82 |
| VPACK | MIPS MDMX PACKSC | 1996 | MIPS V |
| VMULSU (mixed-sign byte dot) | AltiVec vmsummbm (4 unsigned × 4 signed → int32) | 1996 | AltiVec PEM §6.95 |
| VMULSU (mixed-sign byte dot) | TMS320C6x smpyhl | 1997 | TI SPRU189 |
| VMULSU | Dubey, "AltiVec Extension Accelerates Media Processing" | 1996 | IEEE Micro 16(5) |

### C.3 Tier 2 mechanisms

#### C.3.1 GF(2) polynomial arithmetic and CRC

GF(2) polynomial arithmetic predates computing — Évariste Galois, 1830s. Carryless-multiply hardware has been continuously deployed since the 1980s in every Ethernet controller's CRC LFSR. The relevant pre-2006 design sources:

- **Karatsuba & Ofman**, "Multiplication of Multidigit Numbers on Automata," *Soviet Physics Doklady* 7:595–596, 1962. The Karatsuba decomposition used by the Tier 2 hardware (three sub-multiplies instead of four) — 60+ years of prior art.
- **Peterson, W.W. & Brown, D.T.**, "Cyclic Codes for Error Detection," *Proc. IRE* 49(1):228–235, 1961. The foundational CRC-as-error-detection paper.
- **Castagnoli, G., Bräuer, S., Herrmann, M.**, "Optimization of Cyclic Redundancy-Check Codes with 24 and 32 Parity Bits," *IEEE Trans. Communications* 41(6):883–892, 1993. The CRC-32C polynomial 0x1EDC6F41 used by VCRC32C.B — published without patent claim, 33 years of prior art.
- **Koç, Ç.K. & Acar, T.**, "Montgomery Multiplication in GF(2^k)," *Designs, Codes and Cryptography* 14(1):57–69, 1998. Montgomery-style GF(2) reduction underlying the GHASH reduction path used in [software-impl.md §6.2](software-impl.md).
- **Mastrovito, E.D.**, "VLSI Architectures for Computation in Galois Fields," PhD thesis, Linköping University, 1991. Bit-parallel GF(2^m) multiplier architecture — direct precedent for the Tier 2 datapath described in [hardware-impl.md §6](hardware-impl.md).
- **Wegman, M.N. & Carter, J.L.**, "New Hash Functions and Their Use in Authentication and Set Equality," *J. Computer and System Sciences* 22:265–279, 1981. The Carter-Wegman authentication construction that GHASH and CLHASH implement — 45 years of prior art.
- **Bernstein, D.J.**, "The Poly1305-AES Message Authentication Code," *Fast Software Encryption* 2005, LNCS 3557:32–49, 2005. Polynomial-evaluation MAC predating Gueron-Kounavis 2009 by 4 years; included for completeness of the polynomial-MAC lineage.
- **Sarwate, D.V.**, "Computation of Cyclic Redundancy Checks via Table Look-Up," *Comm. ACM* 31(8):1008–1013, 1988. The slice-by-N CRC table-driven technique that VCRC32C.B's reference semantics use as the golden model.
- **Ethernet IEEE 802.3** (1983 onward). CRC-32-IEEE / CRC-32-Ethernet LFSR hardware — every Ethernet MAC since 10Base-5 ships a hardware CRC32 implementation. Demonstrates that 32-bit CRC computation in dedicated silicon is multi-decade prior art across the entire industry.

**Note on Intel CLMUL papers.** Gueron & Kounavis "Efficient Implementation of GCM Using a Carry-Less Multiplier" (IPL, 2009) and Gueron's Intel white paper "Intel Carry-Less Multiplication Instruction and its Usage for Computing the GCM Mode" (2014) are both **post-2006** and **cannot be used as prior art** for the J-Core design. The 2009 paper is cited only in [software-impl.md §6.2](software-impl.md) as an *implementation reference* for the well-known reduction constants. The Tier 2 architectural design rests entirely on the pre-2006 sources above (Karatsuba 1962, Peterson-Brown 1961, Castagnoli-Bräuer-Herrmann 1993, Mastrovito 1991, Koç-Acar 1998, Sarwate 1988, IEEE 802.3 1983, Carter-Wegman 1981). No Intel CLMUL-era source is load-bearing for the architectural specification.

#### C.3.2 Patent landscape (Tier 2)

- **US 7,590,930** (Intel, filed 2005): "instruction to perform carry-less multiplication and an instruction to perform a bit reflection operation." 20-year term: expires 2025; **effectively expired** at time of writing (2026).
- **US 8,977,943** (AMD, filed 2012): "implementation of CRC32 using carryless multiplier." Expires ~2032.

**J-Core design choices that maintain clearance:**

- **Two-operand encoding** (Vn ← Vn ⊗ Vm) differs structurally from Intel's three-operand PCLMULQDQ with immediate.
- **Swizzle-based half-selection** is mechanically distinct from PCLMULQDQ's 2-bit immediate selector — see §5.5.1.
- **Accumulator in SIMD register file low 32 bits** (VCRC32C.B) differs from Intel CRC32 (which uses GPRs) and from the AMD patent's specific claims.
- **Width-locked decoding via prefix** is a unique J-Core mechanism not present in x86 encodings.
- **Polynomial fixed to Castagnoli**, with software handling of CRC-32-IEEE via CLMUL folding, sidesteps Intel CRC32 instruction patent claims entirely.

The design is in clean independent-development territory grounded entirely in pre-2006 prior art (the underlying mathematics is from 1830s Galois / 1962 Karatsuba / 1961 Peterson-Brown / 1993 Castagnoli, the multiplier architecture is from 1991 Mastrovito, and every commercial CLMUL/CRC32 patent of practical relevance has expired or is structurally distinct).

#### C.3.3 Patent-relevance summary across all tiers

The earlier patent-landscape discussion (archived spec-v0.5 Appendix D.4) covers two ARM patents (GB2548600A / US 10,782,972 on vector predication; US 10,599,428 on Helium's relaxed-execution model). Tier 0's design choices (persistent P0 mask register, decoupled compare-from-apply via VMKCHG, sequential beats only) sit comfortably outside both claim languages. The detailed analysis is preserved in [archive/spec-v0.5.md Appendix D.4](archive/spec-v0.5.md).

### C.4 Flagged citations (post-2006) and resolutions

- **SSSE3 PABSB/PABSW/PABSD** is dated 2006 (Intel IA-32 SDM, March 2006 edition). This is *within* the project's hard cutoff (Jan 1, 2006 priority date or later is *not* acceptable). The Tier 1 VABS instruction is **not** justified by SSSE3 alone: independent earlier prior art is MIPS MDMX (1996, via MIN.OB R0 + sign extract) and ARMv6 USAD8 (2002, implicit ABS in the building block). The SSSE3 reference is preserved for completeness but is non-load-bearing.
- **Gueron & Kounavis 2009; Gueron 2014; Kounavis & Berry 2008** (all CLMUL-era Intel sources) are explicitly listed above as post-2006 references used **only** as implementation guides (well-known reduction constants and software fold sequences) in [software-impl.md §6.2](software-impl.md). They are **not** prior art for any architectural feature; the architectural design rests on the pre-2006 Karatsuba / Mastrovito / Castagnoli / Peterson-Brown / Sarwate / IEEE 802.3 chain.
- **OpenSPARC T2 CMU** (Sun/Oracle, 2007) was referenced in the original vclmul-hardware-impl document as a Verilog source. Now flagged: any direct copy of OpenSPARC T2 silicon (2007) violates the cutoff. The Tier 2 hardware implementation must derive from the pre-2006 Mastrovito bit-parallel GF(2^m) multiplier (1991), the Karatsuba decomposition (1962), and the carry-gated integer-multiplier reuse strategy ([hardware-impl.md §6](hardware-impl.md)). The OpenSPARC T2 reference is retained as informative-only in [hardware-impl.md](hardware-impl.md) but **not as prior art**.

No mechanism has been *dropped* from the architectural specification as a result of this audit; the VABS, VCLMUL.D, and VCRC32C.B mechanisms all rest on pre-2006 sources independent of the flagged citations.

---

## Appendix D. Glossary cross-reference

For naming of products (J2, J32, J32-OOO, J32-FM, J64), threading (FGMT), service tiers (Tier 0/1/1.5 in the *service* sense, distinct from SIMD tiers here), and the prior-art-pre-2006 policy, see [../glossary.md](../glossary.md).

SIMD-specific terms (V0..V15, P0, VCSR, SIMDV/SIMDH, governed instruction, lane, beat, atomic block, widening reduction, identity-element substitution, decoupled compare-from-apply, NT hint) are defined inline in the relevant sections above. The full archival glossary lives in [archive/spec-v0.5.md Appendix E](archive/spec-v0.5.md).

---

## Appendix E. Narrow floating-point formats (FP16, bfloat16, FP8, FP4)

The full narrow-format strategy — pre-2006 prior art analysis for FP16 (admit), bfloat16 (storage-only), FP8 (do not implement), FP4 (do not implement); patent landscape; revisit conditions; strategic positioning — is preserved verbatim in [archive/spec-v0.5.md Appendix F](archive/spec-v0.5.md). Summary:

- **FP16 (IEEE 754-2008 binary16):** Strong pre-2006 prior art (Hitachi HD61810 1982, Scott WIF 1991, 3dfx Voodoo 1995, SGI "bali" s10e5 1997, ILM OpenEXR 2002, NVIDIA/MS Cg 2002). **Specified in [gpu/simd-gpu-spec.md §8](gpu/simd-gpu-spec.md)** (SIMD lane type + FP32-accumulate reductions + conversions); format itself is unencumbered.
- **bfloat16:** Weak pre-2006 prior art; heavy Intel patent activity (US 20190079767A1, US 20230069000A1, US 12379927B2); active IPR2021-00155. **Storage-only via software shift/load idioms**; no native arithmetic.
- **FP8 (E4M3 / E5M2):** Zero pre-2006 prior art; 2022 NVIDIA/Intel/ARM specification; active EP4318224A1 conversion-instruction prosecution. **Not implemented.**
- **FP4 (MXFP4 / NVFP4):** Zero pre-2006 prior art; 2023 OCP MX specification; active NVIDIA/AMD prosecution. **Not implemented.**
- **INT8 / INT4 quantization** (TI TMS320 1985+, AT&T DSP): unencumbered. The recommended J-Core narrow-format path for ML inference, fully supported by Tier 1 (VMULSU, VUNPK4, VPACK, SIMDVS/SIMDVU).
