# Fact ownership registry

**One authority per fact.** Every normative constant in this workspace has
exactly one owning document and section, listed below. This registry is the index
a reader starts from; [glossary.md](glossary.md) defines *terms* and names owners,
and carries no values of its own.

The decision and its argument: [decisions/0001](decisions/0001-one-authority-per-fact.md).
The rules a non-owning document must follow when it mentions a registered
constant, and the checks that enforce them, are in that record's *Enforcement*
section. In one line: **restating a value is allowed only with a link to the
owner on the same line; a bare copy is a defect.**

Enforced by `scripts/check-doc-facts.py`, run from the workspace root.
`scripts/check-doc-facts.py --list-checks` prints every check this file drives,
what fails it, and which record defines it.

**The five tables and what each one drives:**

| Table | Drives | Failing check |
|---|---|---|
| `## Registry` | which document owns each constant | `owner-has-fact`, `restatement-is-linked` |
| `## Code bindings` | doc value vs the same value in code | `doc-matches-code`, and `code-bindings` for a malformed or orphaned row |
| `## Value guards` | no document may state a retired value | `no-stale-value`, and `value-guards` for a malformed or orphaned row |
| `## Image layouts` | which facts must have a field table | `context-image-sums` |
| `## Enumerations` | which facts count the rows of a table | `enumeration-row-count` |
| `## Waivers` | enumerated, shrinking exemptions | `check-waivers` |

**Two cross-table dependencies, stated because they are otherwise invisible.**
An `## Image layouts` row needs a `## Value guards` row for the same fact — the
guard is where the expected total comes from, since nothing restates it. A
layout row without a guard fails rather than passing. An `## Enumerations` row
needs one for the same reason: the guard is where the expected *row count* comes
from, and a count hardcoded in the checker would drift from the fact.

> **Scope, stated so this file is not mistaken for something it is not.** This
> registry records which *document* owns a fact. It does not certify that the
> document agrees with the *code*. That is Wave-1 task **B0c** (doc-vs-code CI),
> and it consumes this table: for each row, B0c knows which single file to check
> against the RTL or the kernel.

---

## Registry

The `Pattern` column is the Python regular expression the checker uses to
recognise the constant in prose. Keep it tight enough to avoid unrelated hits and
loose enough to catch a restatement.

**The `Constant` column states a value; it does not explain a mechanism**, and is
capped at 100 characters by `registry-value-is-short`. This is not tidiness: on
this file's first commit the `mmu.asidtag.width` row described a generation
nibble that its own owner's supersede header, added in the same commit, said had
been retired. Nothing caught it, because no check reads this prose. Short cells
are the substitute for a check that cannot be written cleanly — see
[decisions/0001 §Enforcement](decisions/0001-one-authority-per-fact.md).

| ID | Constant | Owner | Pattern |
|---|---|---|---|
| `simd.vfpul` | VFPUL: **retired**, no such register | [simd/spec.md §2.3](simd/spec.md) | `\bVFPUL\b` |
| `simd.context.j32` | SIMD per-task context image, J32: **520 bytes** | [simd/spec.md §2.5](simd/spec.md) | `\b520[- ]byte` |
| `simd.context.j64` | SIMD per-task context image, J64: **1036 bytes** | [simd/spec.md §2.5](simd/spec.md) | `\b1036[- ]byte` |
| `simd.sr.vd` | `SR.VD` is **SR bit 13** | [simd/spec.md §2.6](simd/spec.md) | `SR bit 13` |
| `fpu.context.t2` | Tier-2 FPU context image: **136 bytes** | [fpu/spec.md §7.4](fpu/spec.md) | `\b136[- ]byte` |
| `fpu.sr.fd` | `SR.FD` is **SR bit 15** | [fpu/spec.md §6.3](fpu/spec.md) | `SR bit 15` |
| `mmu.asid.width` | ASID proper: **12 bits** (4096 ASIDs) | [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md) | `12-bit ASID\b` |
| `mmu.asidtag.width` | `ASID_TAG`: **16 bits** (12-bit ASID; top nibble reserved, always zero) | [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md) | `16-bit .?ASID_TAG` |
| `mmu.page.base` | Base page size: **16 KB** | [mmu/design-spec.md §3.3](mmu/design-spec.md) | `16 KB base page` |
| `mmu.tsb.entry` | TSB entry: **16 bytes** | [mmu/hardware-spec.md §2.8](mmu/hardware-spec.md) | `16-byte entr` |
| `mmu.tsb.set` | TSB set: **32 bytes, 2-way** (way 0 at `+0`, way 1 at `+16`) | [mmu/hardware-spec.md §2.8](mmu/hardware-spec.md) | `32-byte (set\b\|cache line)` |
| `mmu.tsb.tag.shift` | TSB tag granularity: **4 KB**, `JCORE_TSB_TAG_SHIFT` = 12 — never `PAGE_SHIFT` | [mmu/hardware-spec.md §7](mmu/hardware-spec.md) | `JCORE_TSB_TAG_SHIFT` |
| `mmu.vector.miss` | TLB **miss** vector: `VBR + 0x400` | [mmu/hardware-spec.md §5](mmu/hardware-spec.md) | `VBR ?\+ ?0x400` |
| `mmu.vector.prot` | TLB **protection** vector: `VBR + 0x100` — *not* `0x400` | [mmu/hardware-spec.md §5](mmu/hardware-spec.md) | `VBR ?\+ ?0x100` |
| `priv.vector.interrupt` | Interrupt vector: `VBR + 0x600`, **flat** — no per-vector stride | [priv-arch/design-spec.md §4.5](priv-arch/design-spec.md) | `VBR ?\+ ?0x600` |
| `aic2.hostowned.polarity` | Host-owned source, guest vCPU on the target TC: **not delivered** (`A2-R1`) | [aic/aic2-spec.md §5.2](aic/aic2-spec.md) | `A2-R1\. Do NOT deliver` |
| `hyp.bootstrap.polarity` | HCALL bootstrap on a tenant-facing bitstream: **MUST NOT** be built (`H-B1`) | [hypervisor/hardware-spec.md §7.2](hypervisor/hardware-spec.md) | `MUST NOT be built into a tenant-facing` |
| `mmu.mmufsr.addr` | `MMUFSR` at P4 offset `0x02C` (`0xFF00002C`) | [soc/p4-mmio-map.md §3.2](soc/p4-mmio-map.md) | `0xFF00002C\|0x0?2C.{0,12}MMUFSR\|MMUFSR.{0,12}0x0?2C` |
| `bus.bmid.width` | `BMID`: **8 bits**, `0x00`/`0xFF` reserved | [bus/fabric-spec.md §4](bus/fabric-spec.md) | `8-bit BMID` |
| `hyp.expevt.hcall` | `HCALL`: EXPEVT `0x1D0` at `VBR_HYP + 0x180` | [hypervisor/hardware-spec.md §4.2](hypervisor/hardware-spec.md) | `0x1D0` |
| `hyp.expevt.hypreg` | Hyperprivileged-register access: EXPEVT `0x1F0` at `VBR_HYP + 0x300` | [hypervisor/hardware-spec.md §4.2](hypervisor/hardware-spec.md) | `0x1F0` |
| `ooo.uops.rte` | `RTE` cracks to **3 uops** | [ooo/j32ooo-spec.md §4.1](ooo/j32ooo-spec.md) | `(?i)\brte\b.?\s*[\|→]\s*(?:\*\*)?3\b` |
| `platform.endianness` | J-Core is **big**-endian at every product point | [platform-baseline.md §2](platform-baseline.md) | `J-Core is (?:\*\*)?big(?:\*\*)?-endian` |
| `platform.fmax.floor` | J2 ECP5 `Fmax` CI floor: **40 MHz** (`ECP5_FMIN_MHZ`) | [platform-baseline.md §3](platform-baseline.md) | `ECP5_FMIN_MHZ` |
| `platform.fmax.j4.floor` | J4 (with MMU) ECP5 `Fmax` CI floor: **30 MHz** | [platform-baseline.md §3](platform-baseline.md) | `\*\*~33 MHz\*\*` |
| `platform.fmax.target` | ECP5 `Fmax` goal: **50 MHz** (`ECP5_TARGET_MHZ`) — a goal, not met | [platform-baseline.md §3](platform-baseline.md) | `ECP5_TARGET_MHZ` |
| `mmu.l1.pipt` | L1 I/D are **PIPT**; relocation covers `PA[27:12]`, so no index bit is virtual | [mmu/hardware-spec.md §4.1a](mmu/hardware-spec.md) | `PIPT` |
| `cache.l1d.write` | L1-D writes: **write-through** at T0, **write-back** under MSI at T1/T2 | [cache/l2-spec.md §17.1](cache/l2-spec.md) | `write-through at .?\[T0\]` |
| `mmu.p4.segment` | CPU P4 segment test: `VA[31:24] == 0xFF` — the whole 16 MB | [soc/p4-mmio-map.md §3.2a](soc/p4-mmio-map.md) | `va\(31 downto 24\) = x"FF"` |
| `mmu.p4.page` | CPU P4 page selector: `case ma_ad[23:12]` — 4 KB pages, PMU at `x"001"` | [soc/p4-mmio-map.md §3.2a](soc/p4-mmio-map.md) | `case ma_ad\(23 downto 12\)` |
| `mmu.p4.window` | The MMU page arm compares **8** address bits, `ma_ad[7:0]` | [soc/p4-mmio-map.md §3.2a](soc/p4-mmio-map.md) | `ma_ad\(7 downto 0\)` |
| `mmu.tsbbr.p1` | `TSBBR` holds a **P1 kernel virtual** address; the walker folds `100` → `000` | [mmu/hardware-spec.md §2.6](mmu/hardware-spec.md) | `P1 kernel virtual address` |
| `mmu.tlb.itlb` | ITLB: **8** fully-associative entries | [mmu/hardware-spec.md §4.1](mmu/hardware-spec.md) | `ITLB entries\s*[\|]\s*\*\*8\*\*` |
| `mmu.tlb.dtlb` | DTLB: **16** fully-associative entries | [mmu/hardware-spec.md §4.1](mmu/hardware-spec.md) | `DTLB entries\s*[\|]\s*\*\*16\*\*` |
| `cache.l2.ebr` | L2 EBR count, T1 baseline: **69** (60 data + 8 tag + 1 MSHR) | [cache/l2-spec.md §20.1](cache/l2-spec.md) | `L2 EBR = 69` |
| `ooo.gates.core` | OoO core + caches: **256,850** gate equivalents — an estimate, not a measurement | [ooo/j32ooo-spec.md §15](ooo/j32ooo-spec.md) | `256,850` |
| `cache.l1.index` | L1 index: **8** bits over 32-byte lines, so the top index bit is 12 | [mmu/hardware-spec.md §4.1a](mmu/hardware-spec.md) | `cache_index_bits = 8` |
| `platform.j4` | **J4** is the `jcore-cpu` build variant with `PRIV_ARCH = true`, not a product point | [glossary.md §7](glossary.md) | `PRIV_ARCH = true` |
| `sh4guest.ccr.stock` | Emulated SH-4 `CCR`: stock offset `SH_CCR` = `0xff00001c` | [sh4-guest-model.md §3.2](sh4-guest-model.md) | `\bSH_CCR\b` |
| `sh4guest.qacr0.stock` | Emulated SH-4 `QACR0`: stock offset `SQ_QACR0` = P4 `0x38` | [sh4-guest-model.md §3.2](sh4-guest-model.md) | `\bSQ_QACR0\b` |
| `sh4guest.qacr1.stock` | Emulated SH-4 `QACR1`: stock offset `SQ_QACR1` = P4 `0x3c` | [sh4-guest-model.md §3.2](sh4-guest-model.md) | `\bSQ_QACR1\b` |
| `sh4guest.fplane` | Bare-metal J4 traps the `1111` opcode plane; RTL guard word `0xF000` | [sh4-guest-model.md §2](sh4-guest-model.md) | `\b0xF000\b` |
| `sh4guest.clds` | SH-4 `flds` and J-Core `clds` are **one encoding** (canonical DB `collides`) | [sh4-guest-model.md §5.1](sh4-guest-model.md) | `flds FRm,FPUL` |
| `sh4guest.csts` | SH-4 `fsts` and J-Core `csts` are **one encoding** (canonical DB `collides`) | [sh4-guest-model.md §5.1](sh4-guest-model.md) | `fsts FPUL,FRn` |
| `sh4guest.ldsfpul` | SH-4 `lds Rm,FPUL` and J-Core `lds Rm,CPI_COM` are **one encoding** | [sh4-guest-model.md §5.1](sh4-guest-model.md) | `lds Rm,FPUL` |
| `sh4guest.stsfpul` | SH-4 `sts FPUL,Rn` and J-Core `sts CPI_COM,Rn` are **one encoding** | [sh4-guest-model.md §5.1](sh4-guest-model.md) | `sts FPUL,Rn` |
| `isa.movi20s.sext` | `movi20s`: `imm20 << 8`, then **sign-extend from bit 27** of the shifted value | [isa-density/spec.md §3.1](isa-density/spec.md) | `sign-extend(?:ed)?\s+from\s+bit\s+\*\*27\*\*\s+of\s+the\s+shifted\s+value` |
| `biendian.dside.bytelane` | Byte store to `…00` drives `we = "1000"`; the byte-order mode does not change it | [bi-endian-spec.md §4.1](bi-endian-spec.md) | `we = "1000"` |
| `biendian.ifetch.select` | Fetch halfword selection is driven by `instr_o.a(1)`, an address bit | [bi-endian-spec.md §5.1](bi-endian-spec.md) | `instr_o\.a\(1\)` |
| `sq.context.bytes` | Store-queue per-context image: **72 bytes** (2 × 32 B buffers + `QACR0`/`QACR1`, not `HSQCR`) | [sq/spec.md §7.2](sq/spec.md) | `\b72[- ](?:bytes?\b\|B\b)` |
| `hyp.gangswitch.items` | Gang-switch flush sequence: **10** numbered items; 7 SQ, 8 FP/SIMD, 9 microreset | [hypervisor/hardware-spec.md §4.7.1](hypervisor/hardware-spec.md) | `\*\*10\*\* (?:numbered )?items` |
| `fpu.fpds` | `FPDS`: 2-bit FP dirty state, per thread context, hyperprivileged-only, **not** in the FPU image | [fpu/spec.md §7.7](fpu/spec.md) | `\bFPDS\b` |
| `simd.vds` | `VDS`: 2-bit SIMD dirty state, per thread context, hyperprivileged-only, **not** `SR.VD` | [simd/spec.md §2.6.1](simd/spec.md) | `\bVDS\b` |
| `security.l6.undefined` | **0** open `undefined` sites under bar item L6; all three specified away | [security/threat-model.md §8](security/threat-model.md) | `\*\*0\*\* open .undefined. site` |
| `simd.fp.ownership` | FP SIMD requires FPU ownership (`SR.FD` = 0); rules `S-R1`–`S-R5` | [simd/spec.md §2.4.1](simd/spec.md) | `\bS-R[1-5]\b` |
| `fpu.kernelfpu` | Kernel-mode FP/SIMD rules `K-R1`–`K-R5`; the exit scrub is `K-R3` | [fpu/spec.md §6.3.1](fpu/spec.md) | `\bK-R[1-5]\b` |
| `gpu.protect.producers` | GPU address producers under the window check: **6** (`P1`–`P6`) | [simd/gpu/simd-gpu-spec.md §16.2](simd/gpu/simd-gpu-spec.md) | `\*\*6\*\* address producers` |
| `gpu.protect.rules` | GPU memory-protection rules `G-R1`–`G-R10`; the handover scrub is `G-R8` | [simd/gpu/simd-gpu-spec.md §16.3](simd/gpu/simd-gpu-spec.md) | `\bG-R(?:10\|[1-9])\b` |
| `mmu.walk.transmitters` | Transmitters a fetch squashed before dispatch reaches: **4** | [mmu/hardware-spec.md §5.0a](mmu/hardware-spec.md) | `\*\*4\*\* transmitters` |
| `mmu.walk.spec` | I-side walk speculation rules `W-R1`–`W-R5`; the arm delay is `W-R1` | [mmu/hardware-spec.md §5.0a](mmu/hardware-spec.md) | `\bW-R[1-5]\b` |
| `hyp.microreset.classes` | Structure classes the microreset clears: **4** | [hypervisor/hardware-spec.md §4.7.1a](hypervisor/hardware-spec.md) | `\*\*4\*\* structure classes` |
| `hyp.tenancy.rules` | Tenancy-check rules `T-R1`–`T-R5`; the refusal is `T-R2` | [hypervisor/hardware-spec.md §4.7.2](hypervisor/hardware-spec.md) | `\bT-R[1-5]\b` |
| `iommu.deny.rules` | IOMMU default-deny rules `I-R1`–`I-R10`; reset polarity `I-R1`, `GLOBAL` removal `I-R5` | [iommu/hardware-spec.md §3.10](iommu/hardware-spec.md) | `\bI-R(?:10\|[1-9])a?\b` |
| `iommu.bypass.paths` | Paths reaching memory with no IOTLB permission check: **7** | [iommu/hardware-spec.md §3.10](iommu/hardware-spec.md) | `\*\*7\*\* bypass paths` |
| `cache.dma.cacheops` | The J4's `cacheops-` arm compiles `cache-jcore.o` (decision 4, landed `linux`#16) | [decisions/0010](decisions/0010-dma-coherence-is-software-maintained.md) | `` `cacheops-` selector keys on `` |
| `cache.l2.isolation.rules` | Cache-isolation rules beyond ways: `P-R1`–`P-R8` | [cache/l2-spec.md §16.2](cache/l2-spec.md) | `\bP-R[1-8]\b` |
| `cache.l2.residuals` | Residual channels §16.2 leaves: **10** — 4 closed, 2 mitigated, 4 accepted | [cache/l2-spec.md §16.3](cache/l2-spec.md) | `\*\*10\*\* residual channels` |
| `soc.cachectrl.base` | Shipping cache-control MMIO block: `0xabcd00c0`, **outside P4** | [cache/l2-spec.md §16.2](cache/l2-spec.md) | `0xabcd00c0` |
| `cache.userflush.dside` | `sys_cacheflush(2)` data side on J-Core: **not performed** | [security/threat-model.md §8](security/threat-model.md) | `cacheflush_user_dside_acts` |
| `cache.userflush.iside` | `CACHEFLUSH_I` on J-Core: **accepted residual**, not closed (§10 item 19) | [security/threat-model.md §10](security/threat-model.md) | `unprivileged whole-L1-I invalidate` |
| `runbook.items` | Measurement items the programme still owes: **36** | [hardware-runbook.md §1](hardware-runbook.md) | `\*\*36\*\* measurement items` |
| `runbook.programmes` | Hardware programmes gating the blocked items: **6**, none scheduled | [hardware-runbook.md §4](hardware-runbook.md) | `\*\*6\*\* unscheduled hardware programmes` |
| `runbook.pmu.counters` | J4 PMU: **8** fixed-function free-running counters, no interrupt | [hardware-runbook.md §3](hardware-runbook.md) | `\*\*8\*\* fixed-function` |

This is a seed, not a census. Rows are added as facts are reconciled; Wave-2 task
**B1** works a contradiction worklist and each item it settles becomes a row here.
Wave-3 **C1a** added `sq.context.bytes` and `hyp.gangswitch.items`, and neither
can be code-bound: there is no
store queue in `jcore-cpu` and a gang switch is hypervisor software, so both are
`## Value guards` rows instead, and `sq.context.bytes` is additionally an
`## Image layouts` row because its total is the sum of a field table that had
disagreed with its own enumeration by exactly one `HSQCR`.
Wave-3 **C1b** added `fpu.fpds`, `simd.vds` and `security.l6.undefined`, and
changed `hyp.gangswitch.items` to read the table rather than the prose (below).
The first two are name facts of the [0001](decisions/0001-one-authority-per-fact.md)
kind `simd.vfpul` already is — they carry no number, and what they buy is that a
document mentioning `FPDS` or `VDS` must link the spec that defines it, which is
the only defence against a second definition of a two-bit field appearing in the
hypervisor spec. `security.l6.undefined` is a **count that three documents
quote**: it is the number of tenant-visible "undefined"s bar item **L6** still
has open, it went from three to two to one over two Wave-3 tasks, and each of
those transitions had to be written into `security/threat-model.md`,
`sq/spec.md` and now `fpu/spec.md` at once. **It has the weakness every value
guard has and it is worth naming once here rather than per row:** the canonical
side licenses a *set*, because a fact may legitimately have a J32 and a J64 form,
so the owner stating two different values for one fact licenses both and passes.
C1b perturbed exactly that — the two statements of this count inside
`security/threat-model.md` set to disagree — and it exits 0. A wrong count in
another document is caught; a document disagreeing with itself is not. There is **no** FP or SIMD image row
in `## Image layouts` from C1b, deliberately: the design adds no bytes to either
image, and saying so is the check —
[fpu/spec.md §7.7](fpu/spec.md) argues why its two dirty bits are not context
state, and if that argument were wrong the FPU image's field table would have to
change and `context-image-sums` would see it.
Wave-3 **C1c** added `simd.fp.ownership` and `fpu.kernelfpu`, both name facts of
the `fpu.fpds` / `simd.vds` kind, and **changed no existing row** — in particular
not `hyp.gangswitch.items`, because C1c adds no gang-switch item: the defect it
fixes is intra-tenant, and the cross-tenant direction of the same registers was
closed by C1b's FP-R3. **What these two rows buy, and what they do not.** They buy
that a document mentioning `S-R1` or `K-R3` must link the spec that defines it,
which is the defence against a second rule of the same name appearing in
`hypervisor/hardware-spec.md` or in a Linux-side document. **What they do not buy
was measured, not assumed** — seven perturbations, of which three pass:

| Perturbation | Result |
|---|---|
| `S-R1` restated in `security/threat-model.md` with no link to the owner | **caught**, `restatement-is-linked` |
| `K-R3` restated in `j4-execution-plan.md` with no link to the owner | **caught**, `restatement-is-linked` |
| the owner stops stating `S-R1`–`S-R5` at all | **caught**, `owner-has-fact` |
| `simd.fp.ownership`'s `Constant` cell set to `SR.FD` = **1**, contradicting its own owner | **passes** — a name fact carries no value for `doc-matches-code` or `no-stale-value` to compare, so the cell is prose the checks never read |
| `S-R1`'s normative sentence rewritten to *"does not require FPU ownership"*, token kept | **passes** — `owner-has-fact` is satisfied by the owner mentioning the token, not by what it says about it |
| `K-R3`'s *"MUST scrub on exit"* rewritten to *"need not scrub on exit"*, token kept | **passes**, same reason |
| ownership of `simd.fp.ownership` moved to `fpu/spec.md`, which also mentions `S-R1` | **caught, but not by the check that should catch it.** `owner-has-fact` passes, because the new owner does state the token; what fails is `restatement-is-linked` over the 24 lines of `simd/spec.md` that have just become restatements. A fact whose token appears in two documents can have its ownership moved between them and be caught only by that cascade |

The three that pass are the weakness every name fact in this table has, stated
here once and not per row.

[hardware-runbook.md](hardware-runbook.md) added `runbook.items`,
`runbook.programmes` and `runbook.pmu.counters` on 2026-09-10, and the first two
are the reason that document is allowed to own anything at all. It is an index:
every experiment in it belongs to the spec that specifies it, and per
[0001](decisions/0001-one-authority-per-fact.md) it links rather than restates.
What it *does* own is the two counts nobody else has a reason to state — how many
measurement items the programme still owes, and how many hardware programmes gate
them — and both are `## Enumerations` rows rather than bare counts, because the
failure they guard is not a wrong number in another document. It is **a row
quietly leaving the table while the count stays**, which is how a scheduled
programme becomes an unscheduled one and how an experiment stops being owed.
[j4-final-review.md §6](j4-final-review.md) found the six programmes by reading
eight Wave-3 tasks against each other; nothing would have noticed a seventh going
missing.

`runbook.pmu.counters` is the third and it is an ordinary code binding, with two
rows for one fact in the `mmu.tsb.entry` pattern: the PMU counter count is stated
by the RTL that implements the counters and by the kernel header that exports
them, and the runbook's category-A and category-C instructions are written
against both. A counter added on one side and not the other is the failure, and
it is the one a runbook would otherwise discover on the board.

**Thirteen perturbations, of which three pass**, measured against a committed
tree rather than reasoned about:

| Perturbation | Result |
|---|---|
| a row deleted from §1's item table, the count left at 36 | **caught**, `enumeration-row-count` |
| a row deleted from §4's programme table, the count left at 6 | **caught**, `enumeration-row-count` |
| the item count changed to 40 without touching the table | **caught twice**, `owner-has-fact` and `no-stale-value` |
| the PMU counter count changed to 6 in the runbook | **caught twice**, `owner-has-fact` and `doc-matches-code`, the latter naming the RTL constant it disagrees with |
| the PMU binding pointed at a file that is not on `origin/master` | **caught**, `doc-matches-code` |
| a second table headed `# \| Item` added to the owner | **caught**, `enumeration-row-count` — "which list the count guards would depend on document order" |
| `j4-execution-plan.md` given a different item count | **caught**, `no-stale-value` |
| `platform-baseline.md` restating the PMU count with no link | **caught**, `restatement-is-linked` |
| the count removed from §1 **and** §4 together | **caught twice**, `owner-has-fact` and `no-stale-value` |
| the count removed from §4 alone, §0's table left stating it | **passes** — `owner-has-fact` reads the *document*, not the section the row names. A registry row can name a section that has stopped carrying the fact, as long as some other line in the same file still does |
| the count removed from §0 alone | **passes**, the same way round |
| §1's row 1 rewritten to invert what the experiment requires, count unchanged | **passes** — the standing limit of every row-counting check here: it counts rows, it does not read them, and this row is no narrower than the ones above it |
| `runbook.pmu.counters`'s relation downgraded from `eq` to `eq-text` | **passes**, and this one is new. A numeric fact bound with `eq-text` compares "8" to "8" and agrees, so the downgrade is invisible **while the two sides match** — it would surface only later, as a spurious failure on a formatting difference. The `## Code bindings` prose warns against reaching for `eq-text` on a numeric fact; nothing detects having done so |

The first two passes are one defect with two faces and the fix is not a check: it
is to state a fact **once** in its owning section, which is why §4's wording was
changed to keep the count off a line wrap when this was measured. The third is the
limit already recorded above for `enumeration-row-count`. The fourth is new and is
recorded here rather than fixed, because a `relation` whitelist that refuses
`eq-text` for a capture that parses as an integer would be a check on the registry
rather than on the documents, and this file has no such check to extend.


C1c also added no `## Code bindings` row and no `## Image layouts` row, for
C1b's reason: no FPU or SIMD unit exists in `jcore-cpu@origin/master`, no
`kernel_fpu` API exists in `linux@origin/jcore`, and neither rule set changes a
context image.

Wave-3 **C2a** added `gpu.protect.producers` and `gpu.protect.rules` — **one of
each kind**, deliberately, because the pair is the clearest side-by-side this
table has of what a value fact buys over a name fact. Ten perturbations were run,
of which four pass:

| Perturbation | Result |
|---|---|
| the owner's count changed from six to five | **caught twice**, on both mechanisms at once: `owner-has-fact` on a **pattern non-match** (the registry pattern pins the literal count), and `no-stale-value` on a **value disagreement** in `security/threat-model.md` and `simd/gpu/architecture.md` |
| the count changed to five in `security/threat-model.md` only, owner still six, link intact | **caught**, `no-stale-value`, on a **value disagreement** — the link does not license the number, which is the whole point of the guard |
| `gpu.protect.producers`'s `Constant` cell set to **5**, contradicting its own owner | **passes** — the cell is prose no check reads, exactly as C1c found for `simd.fp.ownership` |
| every `G-R`*n* token removed from the owner | **caught**, `owner-has-fact`, on a **pattern non-match** |
| `G-R8` restated in `j4-execution-plan.md` with no link to the owner | **caught**, `restatement-is-linked` |
| ownership of `gpu.protect.rules` moved to `simd/gpu/architecture.md`, which also mentions the tokens | **caught by the cascade, not by the check that should catch it** — `owner-has-fact` passes; `restatement-is-linked` fails over the 28 lines of `simd-gpu-spec.md` that have just become restatements. Same shape as C1c's last row |
| `G-R3` rewritten to *"bounding is optional and relocation is not required"*, token kept | **passes** — a name fact guards that a rule is **stated**, never what it says |
| `G-R8`'s *"is scrubbed"* rewritten to *"need not be scrubbed"*, token kept | **passes**, same reason |
| `G-R1` narrowed to *"only the texture path is checked"*, token **and** the count of six both kept | **passes**, and this is the one that matters: it is precisely the regression [simd/gpu/simd-gpu-spec.md §16.2](simd/gpu/simd-gpu-spec.md) exists to prevent, and neither fact sees it. The count guards the *number* stated in prose; nothing ties that number to what the rule ranges over |
| the `P5` row deleted from the producer table, the count left at **6** | **passes.** The value guard compares numbers between documents; it does not count rows. `context-image-sums` is the only row-counting check in this file and it applies to `Offset \| Bytes \| Content` layouts, which this is not |

One further datum, obtained by accident and worth more than a deliberate test:
the first draft of the two rows above *described* the perturbation using the
guarded wording, and `no-stale-value` failed the commit on this file. The guard
fires on the real tree, against prose written by someone who knew it was there.

An **eleventh attempt does not appear above and is recorded because it was wrong,
not because it was informative**: the first run of the "remove the tokens"
perturbation rewrote only the bolded `**G-R`*n* occurrences and the `G-R1..G-R9`
ranges, leaving roughly two dozen inline ones, and reported `OK`. That `OK` was
the perturbation failing to perturb, not the check failing to fire — the kind of
green a guard produces when its scenario was never exercised. It is listed here
because the same mistake made silently would have been reported as a checker gap.

The last two rows are what C2a's facts do **not** buy, and no checker change was
attempted for them: closing either needs a new check in
`scripts/check-doc-facts.py`, and the mutation sweep that gates that file is a
larger piece of work than this task's scope. The honest summary is that the
registry can tell you the number changed and cannot tell you the number stopped
matching the thing it counts.

Wave-3 **C2b** added `mmu.walk.transmitters` and `mmu.walk.spec` — again one of
each kind, and this time **with a `## Code bindings` row**, which is what makes
the pair worth reading beside C2a's. C2b is the first Wave-3 task whose subject
is hardware on `origin/master`, so its name fact is not left to guard a token on
its own: the binding hung off `mmu.walk.spec` compares the driver the owner
quotes for `shadow_wr` against the driver `jcore-cpu:core/cpu.vhd` actually uses.
That is the difference between "the rule is written down" and "the rule is still
true of the tree". Twelve perturbations were run, of which four pass:

| Perturbation | Result |
|---|---|
| the owner's transmitter count changed from four to three | **caught twice**: `owner-has-fact` on a **pattern non-match** (the registry pattern pins the literal count), and `no-stale-value` on a **value disagreement** in `security/threat-model.md` |
| the count changed to three in `security/threat-model.md` only, owner still four, link intact | **caught**, `no-stale-value`, on a **value disagreement** — the link does not license the number |
| `mmu.walk.transmitters`'s `Constant` cell set to **3**, contradicting its own owner | **passes** — the cell is prose no check reads. Third time this table has recorded it; see C1c and C2a |
| every `W-R`*n* token removed from the owner | **caught**, `owner-has-fact`, on a **pattern non-match** |
| `W-R1` restated in `j4-execution-plan.md` with no link to the owner | **caught**, `restatement-is-linked` |
| **`W-R1` inverted** — *"the arm need not wait … may be armed by a fetch that has not dispatched"*, token kept | **passes.** A name fact guards that a rule is **stated**, never what it says, and this is the sharpest instance the table has: the perturbed text is the exact behaviour the rule exists to forbid, and it reads as compliance |
| `W-R1` narrowed to the ITLB install alone — *"the walk's TSB reads are unaffected"* — token **and** the transmitter count both kept | **passes**, and it is C2a's row repeated on a different subject. It is also the narrowing [security/threat-model.md §12](security/threat-model.md) now warns about explicitly, because W-R2 is the paragraph that exists to refuse it — a warning in prose, guarded by nothing |
| a transmitter row deleted from the owner's table, the count left at **4** | **passes.** The value guard compares numbers between documents; it does not count rows |
| the owner's quoted driver changed from `walk_install` to `dtlb_demand` | **caught**, `doc-matches-code`, on a **value disagreement** with `jcore-cpu:core/cpu.vhd@master`. This is the row C2a could not have: the guard consults the tree, not another document |
| the binding's `Code pattern` changed to one the RTL does not contain | **caught**, `doc-matches-code`, on a **pattern non-match** — a binding that stops matching is a failure, not a silent pass, which is the property the `## Code bindings` preamble claims and this confirms |
| ownership of `mmu.walk.spec` moved to `security/threat-model.md` | **caught by the cascade**: `owner-has-fact` passes (that document does state `W-R` tokens), and `restatement-is-linked` fails over the owner's own thirteen lines plus `ooo/j32ooo-spec.md` and `j4-execution-plan.md`. Same shape as C1c's and C2a's last rows |
| the owner drops the count entirely — *"reaches several structures"* | **caught twice**: `owner-has-fact` on a **pattern non-match**, and `no-stale-value` reporting that the canonical pattern matches nothing in the owner, so there is no value to compare restatements against. Worth recording separately from the four-to-three case, because *deleting* a guarded number is the edit a writer makes when they are unsure of it |

**A procedural failure is recorded here because it cost real work and will recur.**
The first perturbation run was done with the registry rows still **uncommitted**,
and the `git checkout -- docs/` that reverts each perturbation reverted the rows
along with it. Two perturbations then reported `OK` against a tree that no longer
contained the facts being tested — the same false green C2a recorded from a
different cause, reached by a different route. The rule that follows is:
**commit the facts before perturbing them**, and check `git diff` is non-empty
after applying each perturbation, which is what caught it.

The narrowing and inversion rows are what these facts do **not** buy, and no
checker change was attempted for them, for C2a's reason: the mutation sweep that
gates `scripts/check-doc-facts.py` is larger than this task. What C2b adds to
C2a's honest summary is the other half of it — a **code binding** can tell you
the document has stopped describing the tree, and still cannot tell you the
document has stopped meaning what it said.

C2b added no `## Image layouts` row: the `W-R` rules move no context state and
specify no byte layout.

Wave-3 **C2c** added `hyp.microreset.classes` and `hyp.tenancy.rules` — one of
each kind again, and **no `## Code bindings` row**, for C2a's reason rather than
C2b's: `jcore-cpu@origin/master` has neither the FGMT hardware nor the hypervisor
these facts describe. Case-insensitive searches over `*.vhd`/`*.vhm` for `fgmt`,
`thread_id` and `multithread` return nothing; `barrel` returns only
`core/shifter.vhd`, `core/shifter_seq.vhd` and `tests/shifter_seq_tap.vhd`, which
are the barrel *shifter* and not barrel threading; and `hpriv`, `hcall`, `hrte`,
`vbr_hyp`, `pdid` and `hedr` return nothing at all. **Eleven** perturbations were
run, of which **four** pass:

| Perturbation | Result |
|---|---|
| the owner's class count changed from four to three | **caught twice**: `owner-has-fact` on a **pattern non-match** (the registry pattern pins the literal count), and `no-stale-value` on a **value disagreement** in `security/threat-model.md` |
| the count changed to three in `security/threat-model.md` only, owner still four, link intact | **caught**, `no-stale-value`, on a **value disagreement** — the link does not license the number |
| `hyp.microreset.classes`'s `Constant` cell set to **3**, contradicting its own owner | **passes** — the cell is prose no check reads. **Fourth** time this table has recorded it; see C1c, C2a and C2b. Four waves is no longer a curiosity, and the fix (compare the cell against the value guard's canonical capture) is a checker change, which is still larger than any one task's scope |
| the owner drops the count entirely — *"the following structure classes"* | **caught twice**: `owner-has-fact` on a **pattern non-match**, and `no-stale-value` reporting that the canonical pattern matches nothing in the owner, so there is no value to compare restatements against |
| a class row deleted from the owner's scope table, the count left at **4** | **passes.** The value guard compares numbers between documents; it does not count rows. Same as C2b's transmitter row, and it matters more here: §4.7.1a constraint 2 says the scrub is complete *over its scope*, so deleting a row silently narrows what "complete" means |
| every `T-R`*n* token removed from the owner (all **9** occurrences rewritten to `Rule `*n*) | **caught**, `owner-has-fact`, on a **pattern non-match** |
| `T-R2` restated in `j4-execution-plan.md` with no link to the owner | **caught**, `restatement-is-linked` |
| **`T-R2` inverted** — *"the `HRTE` **completes normally**"* where the rule says **refused**, token kept | **passes.** A name fact guards that a rule is stated, never what it says. C2b recorded the same shape on `W-R1`; this instance is worse in one respect, because the inverted text still reads as a rule *about* refusal — the bullet is titled "refusal, not a trap" — so a reviewer skimming headings sees compliance twice |
| **`T-R1` narrowed** — *"and is not halted"* added to the definition of *S*, token and class count intact | **passes**, and this is the narrowing with a live consequence rather than a hypothetical one. "halted or not" is in T-R1 precisely because a context that wakes from `SLEEP` re-enters *S* without executing an `HRTE`; excluding halted siblings reopens that hole, and the closure argument in §4.7.2's prose is the only thing that would catch it. Prose, guarded by nothing — C2a's row, on a rule where the missing arm is nameable |
| ownership of `hyp.tenancy.rules` moved to `security/threat-model.md` | **caught by the cascade**: `owner-has-fact` passes (that document does state `T-R` tokens), and `restatement-is-linked` fails over the real owner's nine lines plus `j4-execution-plan.md`. Same shape as C1c's, C2a's and C2b's last rows |
| **`hyp.gangswitch.items` 10 → 9 in the owner** — not a C2c fact, run because C2c *moved* it | **caught twice**, `owner-has-fact` and `no-stale-value`. Recorded because C2c is the first task to land in the escape the C1b note below predicts. That note says the anchor is load-bearing "only while it is genuinely the last row and the author renumbers it", and names two silent passes: inserting before the anchor **without** renumbering, and appending after it. C2c's microreset could have taken either position. It was inserted **before** `Restore the incoming guest` **and the anchor renumbered to 10**, which is the one arrangement the guard can see — and the guard then fired on all three prose sites, exactly as C1b's row predicts. The two silent positions are still silent; nothing here narrows them, and the row count and contiguity check that would is still **B0c**'s |

**Procedure.** The rows were committed before being perturbed, and each
perturbation asserted a non-empty `git diff` before the checker ran — C2b's
procedural failure, applied as a rule. One perturbation (`T-R` token removal) was
**rejected by that assertion on its first attempt**: the literal string it edited
did not exist, the script reported `EDIT FAILED` rather than `OK`, and it was
re-run as a regular-expression substitution over all nine occurrences. That is
the same class of error C2a filed — an edit that missed most of its targets —
caught before it could report green.

What C2c adds to C2a's and C2b's honest summaries is a third limit. C2a's was
that a name fact cannot see a narrowing; C2b's was that a code binding sees the
tree diverge but not the meaning change. C2c's is that **the two limits compose
where there is no code**: `hyp.tenancy.rules` guards a token in a document
describing hardware that does not exist, so neither a binding nor a residue test
can contradict it, and the inverted `T-R2` above would survive until the RTL is
written. The mitigation is not a checker change; it is
[hypervisor/hardware-spec.md §4.7.3](hypervisor/hardware-spec.md)'s **T-E1**,
which must fail before the check exists and pass after — and whose kill criterion
is that a model with one thread context must report *not runnable* rather than
passing vacuously.

C2c added no `## Image layouts` row: `HTCR` and `HMRC` are per-context and
per-core control registers whose bytes are §2.9's save/restore contract, not a
context image this file owns a total for.

C2a added no `## Code bindings` row: no GPU RTL exists in
`jcore-cpu@origin/master` or `jcore-soc@origin/master` — a case-insensitive
search for `gpu|shader|opencl|simt|warp|texel|rasteriz` returns two matches, both
false positives (`vpiSimTime` in `sim/sim/vpibridge.c`, the label `_movwarpr` in
`testrom/tests/testmov.s`). It added no `## Image layouts` row either: `G-R9`
classifies GPU context state into saved and not-saved but specifies no byte
layout, and the V/P0/`VCSR` bytes it does move are `simd.context.j32`'s, already
owned.

Wave-3 **C2d** added `iommu.deny.rules`, `iommu.bypass.paths` and
`cache.dma.cacheops` — the C2a pair *plus* a code binding, which makes it the second
Wave-3 task after C2b to have one and the first whose binding points at the **kernel**
rather than at RTL. That difference is the point of the row: C2c's honest summary was
that a name fact guarding a rule about hardware that does not exist can be contradicted
by nothing at all. C2d's subject has the same problem — there is no IOMMU, no IOTLB and
no BMID in `jcore-cpu@origin/master` or `jcore-soc@origin/master`, and no bus field to
carry a BMID in — so `iommu.deny.rules` sits in exactly C2c's position. But **one C2d
finding is about code that exists and runs**: the J4 Linux build compiles no
cache-operations file, so [decisions/0010](decisions/0010-dma-coherence-is-software-maintained.md)
gets a binding, and the binding is *designed to go red* when the fix it asks for lands.
**Fourteen** perturbations were run, of which **four** pass:

| Perturbation | Result |
|---|---|
| the owner's bypass-path count changed from seven to six | **caught twice**: `owner-has-fact` on a **pattern non-match** (the registry pattern pins the literal count), and `no-stale-value` on a **value disagreement** in `j4-execution-plan.md` |
| the count changed to six in `j4-execution-plan.md` only, owner still seven, link intact | **caught**, `no-stale-value`, on a **value disagreement** — the link does not license the number |
| `iommu.bypass.paths`'s `Constant` cell set to **6**, contradicting its own owner | **passes** — the cell is prose no check reads. **Fifth** wave running; see C1c, C2a, C2b and C2c. The note there stands unchanged and so does the fix, which is a checker change |
| the owner drops the count entirely — *"there are several such paths"* | **caught twice**: `owner-has-fact` on a **pattern non-match**, and `no-stale-value` reporting that the canonical pattern matches nothing in the owner, so there is no value to compare restatements against |
| a bypass-path row deleted from the owner's table, the count left at **7** | **passes.** The value guard compares numbers between documents; it does not count rows. Third task in a row to record it, and here the deleted row was **path 5, BMID `0xFF`** — the permanent bypass that was the whole reason the enumeration exists |
| every `I-R`*n* token removed from the owner (all 60 occurrences rewritten to `Rule`) | **caught**, `owner-has-fact`, on a **pattern non-match** |
| `I-R7` restated in `j4-execution-plan.md` with no link to the owner | **caught**, `restatement-is-linked` |
| **`I-R5` inverted** — the rule rewritten to *"`GLOBAL` is retained … an entry with the bit set matches **every** BMID, which is what a genuinely-shared buffer needs"*, token kept | **passes.** A name fact guards that a rule is stated, never what it says. C2b recorded this on `W-R1` and C2c on `T-R2`; this instance is the worst of the three, because the inverted text is *the exact sentence the retired specification contained* — it does not merely read as compliance, it reads as the original design, and a reviewer who knows the IOMMU literature would have to notice that "a genuinely-shared buffer" is Thunderclap |
| **`I-R1` narrowed** — reset-deny scoped to the on-chip DMA range `0x10`–`0x1F` only, token **and** the bypass-path count both kept | **passes**, and it is the narrowing with the sharpest live consequence in this table: BMIDs `0x80`–`0xEF` are the **guest pass-through** range ([bus/fabric-spec.md §4.4](bus/fabric-spec.md)), so the narrowed rule leaves exactly the tenant-controlled devices bypassing at reset while reading as default-deny. `I-E0` and `I-E1` are what would catch it, and neither is runnable |
| ownership of `iommu.deny.rules` moved to `iommu/security-review.md`, which also states the tokens | **caught by the cascade**: `owner-has-fact` passes (that document does state `I-R` tokens), and `restatement-is-linked` fails over five files including the real owner's own 60 lines. Same shape as C1c's, C2a's, C2b's and C2c's last rows |
| the binding's **doc** side changed — 0010 says the selector keys on `CPU_JCORE` | **caught**, `doc-matches-code`, on a **value disagreement** with `linux:arch/sh/mm/Makefile@jcore`. The row C2c could not have, on the repository C2b did not use |
| the binding's **code** pattern retargeted to `CONFIG_CPU_NOPE` | **caught**, `doc-matches-code`, on a **pattern non-match**, code side |
| the binding's **doc** phrasing destroyed, value kept — *"the `cacheops-` arm is `CPU_J2`"* | **caught twice**: `owner-has-fact` and `doc-matches-code`, both on a **pattern non-match**, doc side |
| `iommu.bypass.paths` scanned against a document that states a *different* seven | not run, and recorded as **not attempted**: the scan pattern is anchored on the noun `bypass paths`, which appears nowhere else in `docs/`, so there is no site to test it at. The anchoring lesson the `## Value guards` preamble states was applied when the pattern was written rather than discovered afterwards |

**Procedure.** The rows were committed before being perturbed, and each perturbation
asserted a non-empty `git diff` before the checker ran — C2b's rule. **One perturbation
was rejected by that assertion and the rejection is worth recording**, because the
cause is new: the "delete a bypass-path row" edit targeted a literal containing
`` `I-R6` ``, and that literal no longer existed — the pass that added owner links to
satisfy `restatement-is-linked` had rewritten it to `` [`I-R6`](hardware-spec.md) ``
in every file *except* the owner, where the bare token survives. The harness reported
`EDIT FAILED (diff empty)` rather than `OK`, the row was re-run against the real text,
and it passes. **The general form: adding a name fact rewrites the very lines a later
perturbation wants to edit, so a perturbation script written before the linking pass
will silently miss its targets afterwards.** That is C2a's eleventh-attempt failure
reached by a third route, and the assertion caught it again.

What C2d adds to the honest summaries above is that **a code binding on a *kernel*
fact behaves exactly like C2b's binding on an RTL fact** — it catches divergence from
the tree on both sides and says nothing about meaning — and that the composition C2c
named still holds: for the nine `I-R` rules there is no code, no residue test and no
model, so the inverted `I-R5` above would survive until a T1 fabric exists. The
mitigation is not a checker change; it is
[iommu/hardware-spec.md §10.1](iommu/hardware-spec.md)'s `I-E4`, whose kill criterion
is that a harness with no way to place a `GLOBAL` entry must report **partial** rather
than pass — because the lookup term, not the install refusal, is the half that holds
when the install path has a bug.

C2d added no `## Image layouts` row: the `I-R` rules move no context state and specify
no byte layout.

### Post-F, 2026-09-10 — `cache.dma.cacheops`'s binding was blind to the fix it was designed to catch

**The tripwire did not fire, and the reason generalises.**
[decisions/0010](decisions/0010-dma-coherence-is-software-maintained.md) §Enforcement
says of this row that if someone adds a `cacheops-$(CONFIG_CPU_JCORE)` arm — "which is
exactly the fix decision 4 asks for — the binding goes red and this record has to be
revisited, which is the intended behaviour, not a regression." The task that wrote that
fix ran the gate against it and it stayed **green**.

The code pattern was `` `cacheops-\$\(CONFIG_(CPU_J2)\)` ``: it pins the literal
`CPU_J2` inside the pattern and captures it back out. The claim it was supposed to hold
up is *"the J4 build compiles no cache-operations file"*, and the fix does not touch the
J2 arm — it **adds** a second one. One arm, unchanged, still matched once, still captured
`CPU_J2`, still equalled the document. **A pattern that pins the value it captures cannot
notice anything except that value's own line disappearing.** The row read as a binding on
"which CPU the selector keys on" while the fact is "how many J-Core CPUs the selector
keys on, and which".

The repair is one character class: `` `cacheops-\$\(CONFIG_(CPU_J\w*)\)` ``. On
`origin/jcore` that still matches exactly one line and captures `CPU_J2`, so the row is
green and says the same thing it always did. With the `CPU_JCORE` arm added it matches
**two** lines with two distinct captures, and `_sole_capture` fails the row with *"captures
2 different values (CPU_J2, CPU_JCORE); there is no single value to compare"* — which is
red, on the right event, with the right message. Verified by running both patterns against
both revisions of `arch/sh/mm/Makefile` directly.

**Second finding, and it is not a defect but it needs saying once.** The binding reads
`origin/jcore` and nothing else, by the [0002 §2](decisions/0002-supersede-convention.md)
rule this table's preamble states. The fix currently lives on a topic branch, so the row
would have stayed green even with the repaired pattern. That is correct behaviour — the
registry describes the integration branch — but it means **"the record must be revisited"
fires at merge time, not at authorship time**, and a decision record that waits for the
gate to tell it the work happened will be months late. 0010 was revisited by hand instead.

Two perturbations, run against a committed tree with a non-empty `git diff` asserted first
(C2b's rule):

| Perturbation | Result |
|---|---|
| the repaired code pattern reverted to the old `` `(CPU_J2)` `` form, with the `CPU_JCORE` arm present in the code | **passes** — the original defect, reproduced deliberately. This is the row's own disclosure and the reason the pattern changed |
| the repaired pattern run against the same tree — the `CPU_JCORE` arm present | **caught**, `doc-matches-code`, on a **multi-capture** on the code side: *"captures 2 different values (CPU_J2, CPU_JCORE); there is no single value to compare"*. The positive control for the row above, and the event 0010 §Enforcement always meant to name |
| the doc side of 0010 changed to say the selector keys on `CPU_JCORE`, code unchanged | **caught**, `doc-matches-code`, on a **value disagreement** with `linux:arch/sh/mm/Makefile@jcore` |

The first two rows need the fix on the branch the registry reads, so they were run with
`refs/remotes/origin/jcore` in the `linux` submodule temporarily retargeted at the fix
commit and restored afterwards. That is the second finding above, made operational: a
binding on the integration branch **cannot** be perturbed from a topic branch without
saying so, and a perturbation table that quietly did it would be describing a tree nobody
has.

Wave-3 **C2e** added `cache.l2.isolation.rules`, `cache.l2.residuals` and
`soc.cachectrl.base` — the C2d shape again, a name fact plus a value fact plus a code
binding, and the binding is the first row in this file pointing at a **board file**
rather than at RTL or at kernel source. It exists because C2e is otherwise in C2a's and
C2c's position: there is no L2 in `jcore-cpu@origin/master` or `jcore-soc@origin/master`
— every case-insensitive `l2` match is a textio variable in a `dcache_tb`, an FPGA ball
name `"L2"` in a `pad_ring.vhd`, a TLB comment or prose — so `cache.l2.isolation.rules`
guards rules about hardware nobody has built.

`soc.cachectrl.base` is registered under protest and the protest is the row. `0xabcd00c0`
appeared in **no** document in this workspace before C2e, and no document owns non-P4 SoC
addresses at all — [soc/p4-mmio-map.md](soc/p4-mmio-map.md) owns P4 and this block is
outside it. Owning it from [cache/l2-spec.md §16.2](cache/l2-spec.md) is a compromise:
that is where the normative rule about it lives (`P-R8`), and the alternative was a
security-relevant address stated in three documents with no owner, which is the exact
failure [decisions/0001](decisions/0001-one-authority-per-fact.md) exists to prevent. If
the SoC ever gets its own address map, the row moves. It carries **no value guard**, and
the reason is a checker limit rather than a choice: `check_no_stale_value` builds its
licensing set with `re.findall(r"\d[\d,]*")` over the `Constant` cells, so a hex address
can never be in it and any guard row would fail as `stray` however correct. Every other
hex fact in this file is guarded the same way — by a code binding only — so this is a
standing gap and not a new one.

**Fourteen** perturbations were run, of which **seven** pass:

| Perturbation | Result |
|---|---|
| the owner's residual count changed from 10 to 8 | **caught**, `owner-has-fact`, on a **pattern non-match** — *on the second attempt.* On the first it **passed**, and the reason was in the owner: the changelog entry restated the count, the registry pattern still matched there, and `no-stale-value` then licensed both 10 and 8 because both digits appear somewhere in some `Constant` cell. **A count stated twice inside its own owner has no guard.** The changelog was reworded to state it once and the perturbation re-run |
| a second document states a *different* residual-channel count, link to the owner intact | **caught**, `no-stale-value`, on a **value disagreement**. The link does not license the number — the same result C2c recorded, on a different fact |
| `cache.l2.residuals`'s `Constant` cell set to **8**, contradicting its own owner | **passes** — the cell is prose no check reads. **Sixth** wave running; see C1c, C2a, C2b, C2c and C2d. Nothing has changed and neither has the fix, which is a checker change: compare the cell against the value guard's canonical capture |
| the owner drops the count entirely — *"the residual channels classified below"* | **caught twice**: `owner-has-fact` on a **pattern non-match**, and `no-stale-value` reporting that the canonical pattern matches nothing in the owner |
| a row deleted from §16.3's table, the count left at **10** | **passes.** The guard compares numbers between documents; it does not count rows. Third instance — C2b's transmitter row and C2c's class row are the others — and it matters here for the same reason it mattered there: §16.3 *is* the honesty list, so deleting a row is exactly how an accepted channel becomes an undocumented one, which is the defect the section defines itself against |
| every `P-R`*n* token rewritten in the owner (all 20+ occurrences) | **caught**, `owner-has-fact`, on a **pattern non-match** |
| `P-R3` restated in `j4-execution-plan.md` with no link | **caught**, `restatement-is-linked` |
| **`P-R2`(b) inverted** — *"updates replacement state exactly as an in-partition hit does"*, token kept | **passes.** A name fact guards that a rule is *stated*, never what it says. Fourth instance after C2b's `W-R1`, C2c's `T-R2` and C2d's `I-R5`, and this one is the plainest: the inverted text is a verbatim restatement of the channel [security/threat-model.md §10](security/threat-model.md) item 2 exists to describe, sitting under a bullet headed "Out-of-partition hit" |
| **`P-R3` narrowed** — *"except that a domain may exceed its share while no other domain has a request outstanding"*, token and constraint intact | **passes**, and it is the narrowing with the sharpest consequence in this set. That sentence reads like a harmless efficiency clause and is precisely the shared remainder `P-R3`'s own next sentence says must not exist: a domain that can expand into idle entries reveals, by the latency of its own expansion, that the other domain went idle. C2c recorded the same shape on `T-R1`; the lesson repeats because prose is what states the closure argument and prose is guarded by nothing |
| the owner's cache-control base changed to `0xabcd00c4` | **caught**, `doc-matches-code`, against `jcore-soc:targets/boards/turtle_1v0/design.yaml`. The one C2e fact with real code behind it, and the binding does its job |
| a second document restates the base as `0xabcd00c4`, link intact | **passes**, and this is a limit no previous wave has recorded. A code binding checks the **owner** against the code; it says nothing about restatements, and the value guard that would is impossible for a hex fact (above). So every hex address in this workspace can drift in any non-owning document without a single check firing. `sh4guest.ccr.stock`, `sh4guest.qacr0.stock`, `mmu.mmufsr.addr` and `mmu.vector.miss` are in the same position; only the last is digits-only enough to be guarded, and it is |
| ownership of `cache.l2.isolation.rules` moved to `security/threat-model.md` | **caught by the cascade**: `owner-has-fact` passes, and `restatement-is-linked` fails over 60 lines of the real owner plus `hypervisor/design-spec.md` and `sq/spec.md`. Same shape as C1c's, C2a's, C2b's, C2c's and C2d's last rows |
| **`P-R7` inverted** — `movca.l`'s remainder *"undefined until written, as before"*, token kept, and `security.l6.undefined` left at **0** | **passes**, and this is the one worth reading twice. Two registered facts now disagree — the spec says a tenant-visible value is undefined, the bar item's count says no such site exists — and **no check relates them**, because one is a name fact over `P-R` tokens and the other is a value fact counting sites in a different document. The count is maintained by hand. `security.l6.undefined` reaching 0 is therefore an assertion by whoever last edited it, not a property of the tree |
| §17.5's `movca.l` table row reverted to the "undefined until written" wording, `P-R7` left intact | **passes**, for the same reason and one step worse: this is the sentence a reader of the instruction table actually reads, and it can be reverted while the rule that replaced it still stands three sections earlier. Both halves of the same fix must be edited to change the behaviour, and neither half is guarded |

That second row is written without the number it used, deliberately: the guard's scan
pattern is anchored on the noun phrase, so spelling the perturbation out here would fire
the check against this file — which is the same trap C2a's note records hitting, and it
was avoided this time by reading that note first.

**Procedure.** The rows were committed before being perturbed; each perturbation asserted
a non-empty `git diff` over `docs/` before the checker ran and reverted afterwards, and
the tree was confirmed clean and green at the end. The `P-R` token removal was written as
a regular-expression substitution with a minimum match count from the start, which is
C2c's lesson applied rather than rediscovered. **One perturbation reported a false green
and was caught by re-reading the output rather than by the harness** — the residual-count
row above — and that is the honest headline of this run: the assertion that a perturbation
*perturbed* does not assert that it perturbed the *only* copy.

What C2e adds to the previous waves' honest summaries is a fourth limit, and it composes
with C2c's rather than replacing it. C2c's was that a name fact and a code binding both
fail where there is no code. C2e's is that **two registered facts can be made to
contradict each other with every check green**, because nothing in this file relates one
fact to another. The `P-R7` rows are the demonstration: `security.l6.undefined = 0` and a
specification that says "undefined" are simultaneously licensed. The mitigation is not a
checker change either — it is [cache/l2-spec.md §16.4](cache/l2-spec.md)'s **`P-E4`**, the
`movca.l` residue test, which must fail before `P-R7` and pass after, and which cannot be
run because there is no L2.

C2e added no `## Image layouts` row: `P-R1`–`P-R8` move no context state and specify no
byte layout. The one byte-level fact it does state — `movca.l`'s line is `R0`'s word plus
zeros — is a line's contents and not a saved context image.

B1 added `ooo.uops.rte`, `platform.endianness`, `platform.fmax.floor`,
`platform.fmax.j4.floor`, `platform.j4`, `mmu.l1.pipt`, `cache.l1d.write`,
`cache.l1.index`, `cache.l2.ebr`, `ooo.gates.core`, `mmu.p4.segment`,
`mmu.p4.page`, `mmu.p4.window`, `mmu.tsbbr.p1`, `mmu.tlb.itlb` and
`mmu.tlb.dtlb`. All but three carry a code binding. `ooo.uops.rte`,
`cache.l2.ebr` and `ooo.gates.core` have **value guards** instead — each is a
figure that exists only in documents, so the thing to police is that no second
document states a different one. `cache.l1d.write` has neither; see
[decisions/0007 §Enforcement](decisions/0007-l1d-write-policy-under-msi.md) for
why, which is that the T0 property is the *absence* of a dirty bit and T1/T2 has
no RTL at all.

**Task F — the whole-implementation review — audited the six waves of
disclosures above as a set, and closed two of the gaps they record.** The other
task in this programme perturbed its own facts; this one perturbed the
*machinery*, and its finding is that two of the escapes disclosed above were not
the intrinsic limits they were each recorded as being.

**1. The `Constant` cell was never unread; it was read into a pool wide enough to
license anything.** Six consecutive waves — C1c, C2a, C2b, C2c, C2d, C2e —
recorded a `Constant` cell edited to contradict its own owner and passing, each
time explaining it as "the cell is prose no check reads" and deferring the fix to
a checker change nobody had scope for. The cell **was** read: `check_no_stale_value`
built its second-opinion licensing set by scanning every `Constant` cell in this
file into one global pool. Task F measured that pool on the real tree: **48
values, including every integer from 0 to 10.** Every Wave-3 security count is in
that range — 4 transmitters, 4 microreset classes, 6 GPU producers, 7 IOMMU
bypass paths, 10 residual channels, 10 gang-switch items, 0 open `undefined`
sites — so the guarantee the `## Value guards` preamble claims, that "a stale
value now has to be written into both before it licenses anything", **held for no
Wave-3 security fact at all.** It held for `272` and `132`, the three-digit sizes
it was built for, and the disclosure generalised from those.

The set is now scoped to the **bolded** values in the `Constant` cells of facts
owned by **the same document**, which takes it from 48 values to between one and
seven per fact. Bold, because `registry-value-is-short` caps the cell at 100
characters precisely so the tail is explanation — `cache.l2.residuals` reads
"**10** — 4 closed, 2 mitigated, 4 accepted", and reading the tail made 4 and 2
statements of that fact. By owning document rather than by fact, because
`simd.context.j32` and `simd.context.j64` are two rows of one owner and the
canonical pattern licenses both from either; per-fact scoping fails a correct
tree. **The residual is stated rather than implied: two facts owned by the same
document still license each other's values.**

This closes five of the six disclosed `Constant`-cell instances — every one whose
fact carries a value guard. C1c's `simd.fp.ownership` is a **name** fact and is
not closed, and cannot be: a name fact carries no value, so there is nothing to
compare the cell against. It also closes the escape C2e called the honest
headline of its run — *"a count stated twice inside its own owner has no
guard"* — which was the same pooling seen from the other side, and which C2e
worked around by rewording the owner rather than by fixing the check.

**2. Four waves recorded "delete a row, leave the count" as passing. It now
fails.** `## Enumerations` above is that check. It is `context-image-sums`'s shape
applied to counted lists instead of byte layouts, and it was demonstrated against
every historical instance rather than argued for: each of the six registered
enumerations had one row deleted against a committed tree, with a non-empty
`git diff` asserted first (C2b's rule), and all six failed.

| Perturbation | Result |
|---|---|
| transmitter 3 (**ITLB entry**) deleted from `mmu/hardware-spec.md` §5.0a, count left at 4 | **caught**, `enumeration-row-count`. Disclosed as passing by C2b |
| microreset class 2 (**replacement-policy state**) deleted, count left at 4 | **caught**. Disclosed as passing by C2c, where §4.7.1a constraint 2 says the scrub is complete *over its scope* |
| bypass path 5 (**BMID `0xFF`**, the permanent bypass) deleted from `iommu/hardware-spec.md` §3.10, count left at 7 | **caught**. Disclosed as passing by C2d, on the row it called "the whole reason the enumeration exists" |
| residual channel 9 (**inclusion recall**) deleted from `cache/l2-spec.md` §16.3, count left at 10 | **caught**. Disclosed as passing by C2e, on the section that *is* the honesty list |
| GPU producer **P5** (tile write-out burst) deleted, count left at 6 | **caught**. Disclosed as passing by C2a, which called it the row "that matters" |
| a gang-switch item deleted, count left at 10 | **caught** |
| a row **inserted before** the `hyp.gangswitch.items` anchor **without renumbering** | **caught.** C1b disclosed this as one of two positions its re-anchoring could not see; C2c confirmed both were still silent |
| a row **appended after** the anchor | **caught.** The second of C1b's two |
| the count, the table and the `Constant` cell all moved together to a new value | **passes**, as it must — a fixture asserts this, because a check comparing against a number hardcoded in the checker would pass every perturbation above and drift from the fact |
| only the table's column **header** renamed, rows and count intact | **caught**, as *no table headed that*. This is the `## Image layouts` failure — a registered fact asserted to be covered by a list that is not there — on the other table |
| a **second** table with the same header added, with the right row count | **caught as ambiguous.** A check taking the first match would have reported OK while guarding the wrong list, so which list the count protects would depend on document order |

**What Task F did not close, and did not attempt.** The inversion rows
(`W-R1`, `T-R2`, `I-R5`, `P-R2`(b)) and the narrowing rows (`G-R1`, `W-R1`,
`T-R1`, `I-R1`, `P-R3`) are unchanged and are a genuine residual, not a deferral:
no syntactic check distinguishes *"MUST scrub"* from *"need not scrub"* without
firing on correct prose, and a check that fires on correct prose is switched off
within a month. The two contradiction rows (`P-R7` against `security.l6.undefined`)
are also unchanged; the check that would relate them is the grep-level `undefined`
guard `sq/spec.md` §6.5 filed with **B0c**, and B0c closed on 2026-08-25, so that
obligation currently has no owner. ***That last clause is superseded: the
obligation has an owner and the two contradiction rows now fail — see the post-F
section below.*** **`enumeration-row-count` counts rows; it does
not read them.** A row *replaced* by a different row keeps the count and passes.

**The honest summary, and it is a correction rather than an addition.** Five of
the six escapes recorded above were filed as properties of what a name fact or a
value fact can do. Two of them were not: they were properties of how this
checker happened to be written, they were closable in a few dozen lines, and they
survived six waves because each task disclosed its own instance faithfully and no
task read the other five. **A disclosure register is not a defect tracker.** The
lesson worth carrying is not about the checker: it is that per-task honesty
produced a set of forty accurate observations from which nobody had drawn the
conclusion, and drawing it took reading them together and measuring the code they
described rather than trusting the description.

### Post-F, 2026-09-10 — `site-absence-claim`, and what it caught

**Task F's rank 5 is closed, and the two contradiction rows above now fail.** The
`## Absence claims` table and `site-absence-claim` are the answer to *"two
registered facts contradicting each other, with nothing relating them"*. F
recommended rather than implemented because the per-site wording is the owning
specs' call; the three rows in that table are those specs making it.

Every row was perturbed against a **committed** tree with a non-empty `git diff`
asserted first, per C2b's rule, and each perturbation is a *historical* instance
rather than an invented one. All five were caught by the same check — none by
exit status alone and none by a neighbouring check — and that is stated because
the previous version of the test harness credited catches to the wrong assertion
and Task F had to correct it.

| Perturbation | Result |
|---|---|
| **C2e's second disclosure**: §17.5's `movca.l` table row reverted to *"the remainder undefined until written"*, `P-R7` left standing | **caught**, `site-absence-claim`, at the reverted line. This is the sentence a reader of the instruction table actually reads, and C2e recorded it as passing |
| **C2e's first disclosure, from the other side**: the retired wording deleted from the document altogether, so nothing is left to match | **caught**, by the second arm — *"the retired wording is not there even as history, so this row cannot notice it coming back"*. Without that arm, inverting the rule **and** deleting its history would pass, and deleting its history is what whoever reverts a rule actually does |
| **C1a's site**: `sq/spec.md` §4 reverted to *"buffer bytes have undefined content"* as current text, `SQ-R5` left standing | **caught** |
| **C1b's site**: `fpu/spec.md` §7.3's restore branch reinstated as *"FR/XF/FPUL = undefined per SH-4"*, `FP-R1` left standing | **caught** |
| the registry row repointed at a document that does not contain the wording | **caught**, same second arm. An orphaned claim is how a rename would quietly switch this off |
| a retraction marker two lines above the match | **passes**, as it must — the tree's own idiom puts the marker on the line introducing a block quotation. A fixture asserts this, and a second fixture asserts that a marker *three* lines above **fails**, because a window with no asserted edge is a window that widens silently |

**What this does not close, and it is the same residual as before.** The check
catches the retired *wording* coming back. It does not catch the retired *rule*
coming back in different words — Task F's rank-3 inversion — and nothing here
narrows that. Three sites are registered; a fourth closed site adds its own row,
and the table's prose says so, because a sweep that guessed at wordings would be
the "check that fires on correct prose" this project switches off within a month.

### 2026-09-10 — `cache.userflush.*`, and a blind spot `site-absence-claim` has only in tables

Two Registry rows and two `## Absence claims` rows were added by the task that
closed the `sys_cacheflush(2)` data-side channel
([security/threat-model.md §8](security/threat-model.md) **L5**, §10 item 19).
Every row was perturbed against a **committed** tree with a non-empty `git diff`
asserted first, per C2b's rule.

| Perturbation | Result |
|---|---|
| `cacheflush_user_dside_acts` removed from the owner's §8 text, Registry row kept | **caught**, `owner-has-fact`, on a **pattern non-match** |
| the same token restated in `j4-execution-plan.md` with no link to the owner | **caught**, `restatement-is-linked` |
| `unprivileged whole-L1-I invalidate` reworded in §10 item 19, Registry row kept | **caught**, `owner-has-fact`, on a **pattern non-match** |
| the same phrase restated in `j4-execution-plan.md` with no link | **caught**, `restatement-is-linked` |
| ownership of `cache.userflush.dside` moved to [decisions/0010](decisions/0010-dma-coherence-is-software-maintained.md), which also states the token | **caught by the cascade**: `owner-has-fact` passes, `restatement-is-linked` fails against the real owner. Same shape as C1c's, C2a's, C2b's, C2c's, C2d's and C2e's last rows |
| the retired no-op sentence reasserted as current prose in §7.6a, far from any marker | **caught**, `site-absence-claim` |
| the retired sentence deleted from `threat-model.md` outright, leaving nothing to match | **caught**, by the second arm |
| the retired sentence reasserted as a new numbered item in `j4-final-review.md` | **caught**, `site-absence-claim`, on the second row — which is why there are two rows and not one |
| the same sentence reasserted in a **third** document (`j4-execution-plan.md`, which has no row) | **passes.** Known and stated in the preamble: the claim is anchored per (document, wording). Recorded again because this task is the first to have the sentence live in two documents at once, which is when the limit stops being theoretical |
| **§8 L5's decision inverted in place** — "the **data side is closed**" rewritten to "the data side is **left open, deliberately**", every registered token and every retraction intact | **passes.** C3's finding, reproduced on a new pair of rows. A name fact guards that a rule is stated, never what it says |
| §10 item 19 relabelled `[closed]` instead of `[accepted]`, wording otherwise intact | **passes.** §10's two-kinds-of-entry distinction is prose no check reads; the label that decides whether a channel is a residual or a closure is unguarded |

**And one result that is new, was found by mis-siting a perturbation, and is a
defect rather than a limit.** The first attempt reasserted the retired sentence in
the §11 table row *immediately after* the row carrying the retraction marker, and
the gate returned **exit 0**. That is not the per-document limit above; the same
sentence one row further down is caught. `ABSENCE_LOOKBACK = 2` is calibrated for
**prose** — the comment beside it says so, citing `fpu/spec.md` §7.7's marker-line
and block-quotation-below idiom — and in a Markdown table **one line is one row**.
So a wording retired inside a table row silently exempts the **next two rows** from
its own absence claim, and those rows can be arbitrarily long and about entirely
different subjects. Demonstrated at `security/threat-model.md`: the marker sits in
the `decisions/0010` row, and reasserting the sentence in either of the two rows
below it passes while the third fails.

**Not fixed here, and the reason is a rule and not an omission.** The narrowing
that closes it — when the matched line is a table row, accept a marker only on that
same row — is a change to a check with 183 fixtures behind it, and a checker change
with no fixture asserting the new edge is the exact failure the existing
"marker three lines above **fails**" fixture exists to prevent. Adding that fixture
moves the required count, which is the gate this task was given. So it is recorded
with its demonstration, at the row it was found on, for whoever owns
`check-doc-facts.py` next. **The mitigation available today is placement**: do not
retire a wording inside a table row that has neighbours you would mind losing.

**Rank 6, hex drift, is still open and still recommended rather than
implemented.** `check_no_stale_value` builds its licensing set with a
decimal-only scan, so a hex fact can carry no value guard. Task F ranked it 6
because the consequence is a misrouted document rather than a false security
claim, and because the one hex fact with real security weight
(`soc.cachectrl.base`) has a code binding. That judgement is unchanged and this
task did not attempt it.


## Code bindings

The Registry above says which *document* owns a constant. This table says where
the same constant lives in the **code**, and `doc-matches-code` fails when the
two disagree. Wave-1 task **B0c**; the argument is in
[decisions/0001 §Enforcement](decisions/0001-one-authority-per-fact.md), which
says B0a decides *which single document* is checked against the code and B0c
does the checking. (This previously cited a §"Doc-vs-code" of
[decisions/0003](decisions/0003-canonical-encoding-database.md); 0003 has no
such section — it decides the encoding database, not this table.)

**A binding row states no value.** It names two regular expressions — one read
against the owning document, one against a file in a submodule — each with
**exactly one capture group**, and a relation the two captures must satisfy. A
row that restated the number would be a third copy of it, and
[0001](decisions/0001-one-authority-per-fact.md) is a record about what happens
to copies. This row can go stale only by ceasing to match, which is a failure.

`Code` is `<repo>:<path>`, read from **`origin/<integration-branch>`**, never
from the checked-out submodule pointer — [0002 §2](decisions/0002-supersede-convention.md)
is explicit that the pointer is not evidence, and it currently lags by months.
Checking the docs against a stale pointer would report agreement with code
nobody runs.

**A row may only name a submodule CI actually provisions**, which
`ci-provisions-submodules` is what enforces. The `Code` cell is a promise that
the comparison can be *made*, and that promise is kept in a second file —
[`.github/workflows/docs-gate.yml`](../.github/workflows/docs-gate.yml), which
clones the submodules the gate reads. Nothing made the two agree, and the gap is
silent in the expensive direction: a developer has every submodule checked out,
so a row naming an unprovisioned one passes locally and surfaces in CI as
`(skipped, --strict)` — after review, after a push, on someone else's time. Not
hypothetical: `biendian.ifetch.select` is the row it happened to and `jcore-soc`
is the submodule.

The check requires **all three** provisioning sites in that workflow — the
`git submodule update --init` argument list, the per-submodule
`git … fetch … origin <integration-branch>` line, and the shallow-clone guard
loop — because each one missing leaves the same binding unverifiable, only with
a different message and at a different step. A submodule cloned without its
integration branch fetched fails immediately after the checkout succeeds;
[0002 §2](decisions/0002-supersede-convention.md) is why the branch and not the
pointer is what has to arrive. It also covers the two submodule reads that are
*not* rows in this table — `p4-offsets-match-rtl` and `one-encoding-database` —
so deleting the last row naming a submodule cannot quietly drop a requirement
those two still have. A workflow the check can no longer parse is a failure
naming the site that moved, not a pass: an unparseable workflow would otherwise
report every submodule as missing, which is a pile of confident wrong findings
in place of one true one.

Relations, enumerated (an unknown name is a failure, not a no-op): `eq` (both
decimal), `eq-hex` (both hexadecimal, compared numerically),
`bytes-from-shift` (doc bytes = 2^code) and `eq-text` (neither side is a
number; the two captures are compared as text, case- and
surrounding-whitespace-insensitively). A `kb-from-shift` relation was
defined here and used by no row; it was deleted rather than left as untested
surface that no fixture could reach.

`eq-text` is the one relation that does not parse its captures as integers, and
it is here because a byte order has no honest integer
([decisions/0006](decisions/0006-endianness-is-big-endian.md) §Enforcement).
Reach for it only when that is true of the fact: a relation that compares
strings will happily compare two numbers written differently and call them
different, so a numeric fact bound with `eq-text` is a check that fires on
formatting.

| Fact ID | Doc pattern | Code | Code pattern | Relation |
|---|---|---|---|---|
| `mmu.page.base` | `(\d+) KB base page` | `linux:arch/sh/configs/jcore_defconfig` | `CONFIG_PAGE_SIZE_(\d+)KB=y` | `eq` |
| `mmu.tsb.entry` | `(\d+)-byte entr` | `jcore-cpu:core/cpu.vhd` | `entry_bytes\s*=>\s*(\d+)` | `eq` |
| `priv.vector.interrupt` | `[\|] Interrupt [\|] .VBR \+ 0x([0-9A-Fa-f]+)` | `jcore-cpu:decode/gen-go/spec/sh4/exceptions.toml` | `INTEVT<-vec; PC<-VBR\+0x([0-9A-Fa-f]+)` | `eq-hex` |
| `mmu.tsb.entry` | `(\d+)-byte entr` | `linux:arch/sh/include/cpu-jcore/cpu/mmu_context.h` | `#define JCORE_TSB_ENTRY_BYTES\s+(\d+)` | `eq` |
| `mmu.tsb.set` | `(\d+)-byte set` | `jcore-cpu:core/datapath_pkg.vhd` | `shift_left\(v_idx, (\d+)\)` | `bytes-from-shift` |
| `mmu.tsb.tag.shift` | `` `JCORE_TSB_TAG_SHIFT` = \*\*(\d+)\*\* `` | `linux:arch/sh/include/cpu-jcore/cpu/mmu_context.h` | `#define JCORE_TSB_TAG_SHIFT\s+(\d+)` | `eq` |
| `platform.endianness` | `J-Core is (?:\*\*)?(big\|little)(?:\*\*)?-endian` | `linux:arch/sh/configs/jcore_defconfig` | `CONFIG_CPU_(\w+)_ENDIAN=y` | `eq-text` |
| `platform.fmax.floor` | `\*\*(\d+) MHz\*\* \(`ECP5_FMIN_MHZ`\)` | `jcore-cpu:.github/workflows/synth-cpu.yml` | `ECP5_FMIN_MHZ: "(\d+)"` | `eq` |
| `platform.fmax.j4.floor` | `\*\*~33 MHz\*\*\s*[\|]\s*(\d+) MHz` | `jcore-cpu:.github/workflows/synth-cpu.yml` | `j4\)\s+floor=(\d+)` | `eq` |
| `platform.fmax.target` | `` `ECP5_TARGET_MHZ` is \*\*(\d+) MHz\*\* `` | `jcore-cpu:.github/workflows/synth-cpu.yml` | `ECP5_TARGET_MHZ: "(\d+)"` | `eq` |
| `mmu.l1.pipt` | `bound of the relocated\s+field — \*\*bit (\d+)\*\*` | `jcore-cpu:core/cpu.vhd` | `db_o\.a\(27 downto (\d+)\) <= \(ppn_lo` | `eq` |
| `mmu.l1.pipt` | `bound of the relocated\s+field — \*\*bit (\d+)\*\*` | `jcore-cpu:core/cpu.vhd` | `inst_o\.a\(27 downto (\d+)\) <= \(ppn_lo` | `eq` |
| `mmu.p4.segment` | `` `va\(31 downto 24\) = x"([0-9A-F]+)"` `` | `jcore-cpu:core/datapath_pkg.vhd` | `va\(31 downto 24\) = x"([0-9A-F]+)"` | `eq-hex` |
| `mmu.p4.page` | `case ma_ad\(23 downto (\d+)\)` | `jcore-cpu:core/datapath.vhm` | `case ma_ad\(23 downto (\d+)\) is` | `eq` |
| `mmu.p4.window` | `compares only `ma_ad\((\d+) downto 0\)`` | `jcore-cpu:core/datapath.vhm` | `ma_ad\((\d+) downto 0\) = x"00"` | `eq` |
| `mmu.tsbbr.p1` | `top three address bits `\*\*([01]+)\*\*` to` | `jcore-cpu:core/cpu.vhd` | `walk_bus_a\(31 downto 29\) = "([01]+)"` | `eq-text` |
| `mmu.tlb.itlb` | `ITLB entries\s*[\|]\s*\*\*(\d+)\*\*` | `jcore-cpu:core/cpu.vhd` | `entries   => (\d+),\n        side_is_i => true` | `eq` |
| `mmu.tlb.dtlb` | `DTLB entries\s*[\|]\s*\*\*(\d+)\*\*` | `jcore-cpu:core/cpu.vhd` | `entries   => (\d+),\n        side_is_i => false` | `eq` |
| `cache.l1.index` | `` `cache_index_bits = (\d+)` `` | `jcore-cpu:cache/cache_pkg.vhd` | `cache_index_bits : natural := (\d+);` | `eq` |
| `platform.j4` | `` `(PRIV_ARCH) = true` `` | `jcore-cpu:variants.toml` | `\[j4\]\ngenerics    = \{ (PRIV_ARCH) = "true" \}` | `eq-text` |
| `platform.fmax.floor` | `[\|] J1 [\|] ~38–40 MHz [\|] (\d+) MHz [\|]` | `jcore-cpu:.github/workflows/synth-cpu.yml` | `j1\)  floor=(\d+)` | `eq` |
| `platform.fmax.floor` | `CDC-limited [\|] (\d+) MHz [\|]` | `jcore-cpu:.github/workflows/synth-cpu.yml` | `j2c\) floor=(\d+)` | `eq` |
| `sh4guest.ccr.stock` | `SH_CCR at 0x([0-9a-f]+)` | `linux:arch/sh/include/cpu-sh4/cpu/cache.h` | `#define SH_CCR\s+0x([0-9a-f]+)` | `eq-hex` |
| `sh4guest.qacr0.stock` | `SQ_QACR0 at offset 0x([0-9a-f]+)` | `linux:arch/sh/include/cpu-sh4/cpu/sq.h` | `#define SQ_QACR0\s+\(P4SEG_REG_BASE\s+\+ 0x([0-9a-f]+)\)` | `eq-hex` |
| `sh4guest.qacr1.stock` | `SQ_QACR1 at offset 0x([0-9a-f]+)` | `linux:arch/sh/include/cpu-sh4/cpu/sq.h` | `#define SQ_QACR1\s+\(P4SEG_REG_BASE\s+\+ 0x([0-9a-f]+)\)` | `eq-hex` |
| `sh4guest.fplane` | `the guard word is 0x([0-9A-F]+)` | `jcore-cpu:sim/tests/j4_illegal_trap.S` | `\.word\s+0x(F000)` | `eq-hex` |
| `sh4guest.clds` | `annotation on flds FRm,FPUL names ([a-z]+)` | `jcore-cpu:docs/insns.json` | `"collides": \["(clds)\\tCPI_Rm,CPI_COM"\]` | `eq-text` |
| `runbook.pmu.counters` | `\*\*(\d+)\*\* fixed-function` | `jcore-cpu:core/perf_pkg.vhd` | `constant pmu_num_cnt : pmu_cnt_count_t := (\d+);` | `eq` |
| `runbook.pmu.counters` | `\*\*(\d+)\*\* fixed-function` | `linux:arch/sh/include/cpu-jcore/cpu/perf_event.h` | `#define JCORE_PMU_NR_COUNTERS\s+(\d+)` | `eq` |
| `sh4guest.csts` | `annotation on fsts FPUL,FRn names ([a-z]+)` | `jcore-cpu:docs/insns.json` | `"collides": \["(csts)\\tCPI_COM,CPI_Rn"\]` | `eq-text` |
| `sh4guest.ldsfpul` | `annotation on lds Rm,FPUL names ([a-z]+)` | `jcore-cpu:docs/insns.json` | `"collides": \["(lds)\\tRm,FPUL"\]` | `eq-text` |
| `sh4guest.stsfpul` | `annotation on sts FPUL,Rn names ([a-z]+)` | `jcore-cpu:docs/insns.json` | `"collides": \["(sts)\\tFPUL,Rn"\]` | `eq-text` |
| `biendian.dside.bytelane` | `` onto `we = "([01]+)"` — bit 3 `` | `jcore-cpu:core/datapath.vhm` | `when "00" =>\s+r\.we := "([01]+)"` | `eq-text` |
| `biendian.ifetch.select` | `` `instr_o\.a\((\d+)\)` — an address bit `` | `jcore-soc:targets/data_bus_pkg.vhd` | `if instr_o\.a\((\d+)\) = '0' then` | `eq` |
| `mmu.walk.spec` | `` `shadow_wr <= (\w+) and walk_side_i` `` | `jcore-cpu:core/cpu.vhd` | `shadow_wr\s*<=\s*(\w+) and walk_side_i;` | `eq-text` |
| `cache.dma.cacheops` | `` the J4's arm compiles `(cache-\w+)\.o` `` | `linux:arch/sh/mm/Makefile` | `cacheops-\$\(CONFIG_CPU_JCORE\)\s*:=\s*(cache-\w+)\.o` | `eq-text` |
| `soc.cachectrl.base` | `` `base-addr: 0x([0-9a-f]+)` `` | `jcore-soc:targets/boards/turtle_1v0/design.yaml` | `- class: cache_ctrl\n    base-addr: 0x([0-9a-f]+)` | `eq-hex` |

Notes on what is deliberately **not** here, so the gaps are visible rather than
inferred from silence:

- **`mmu.l1.pipt` is bound twice on purpose**, and to the *relocation bound*
  rather than to the letters `PIPT`. The I-side and the D-side relocate
  independently in `core/cpu.vhd`, so one binding would leave the other free to
  drift, and a VIPT I-cache beside a PIPT D-cache is a real configuration
  somebody could produce. Binding to bit 12 is what makes the check mean
  something: `PIPT` in a comment is a claim, whereas "the relocated field starts
  at the bit the L1 index tops out at" is the property, and moving the bound to
  13 — which is where this design was before the PIPT work — turns the check red
  rather than leaving a stale word in a comment.
- **`mmu.tsb.entry` is bound twice on purpose.** The 16 is restated
  independently by the RTL generic map and by the kernel header, and either can
  move without the other. One binding would leave whichever side it did not name
  free to drift.
- **`mmu.tsb.set` binds to the shift, not to a literal 32.** The RTL has no
  `32`; it has `shift_left(v_idx, 5)`, which is the arithmetic that actually
  places a set. Binding to the real expression is why widening the TSB to 4 ways
  cannot pass with the doc still saying 32 bytes.
- **`fpu.context.t2` and `simd.context.j32`/`j64` have no code binding**, because
  there is no code: there is no FPU or SIMD RTL in `jcore-cpu`, and Linux's
  `struct sh_fpu_hard_struct` is a field list with no size constant to capture.
  They are covered instead by `context-image-sums` — doc-internal arithmetic,
  not doc-vs-code, and labelled as such. *(This bullet previously said the same
  thing while `simd/spec.md` had no field table at all, so the SIMD half of the
  claim was false and the check could not have noticed: it failed only when
  **no** table existed anywhere in `docs/`, and the FPU table alone kept it
  green. An uncovered fact asserted to be covered, under a heading promising the
  gaps were visible. `## Image layouts` below now names the facts that must have
  a table, and a registered fact whose owner has none is a failure.)*
- **`cache.userflush.dside` has no binding row yet, and the two that belong here
  are written out below so they can be pasted in rather than reinvented.** The
  fact — that `sys_cacheflush(2)`'s data side does not run on J-Core — is carried
  in code by two lines that do not exist on `linux@origin/jcore`; they are on the
  branch that fixed it. Adding the rows now would fail `doc-matches-code` on a
  **code-side pattern non-match**, which is the mechanism working correctly and is
  still a red gate, so the rows wait for the merge. This is the **second** time
  [0002 §2](decisions/0002-supersede-convention.md)'s pointer rule has made a
  fix's own guard unlandable at authorship time; `cache.dma.cacheops` was the
  first, and 0010 §Enforcement's "the binding's red is a merge-time signal"
  generalises past that one row.

  | Fact ID | Doc pattern | Code | Code pattern | Relation |
  |---|---|---|---|---|
  | `cache.userflush.dside` | `` performs it only where\s+`(cacheflush_user_dside_acts)\(\)` `` | `linux:arch/sh/kernel/sys_sh.c` | `if \((cacheflush_user_dside_acts)\(\)\) \{` | `eq-text` |
  | `cache.userflush.dside` | `` on a `CONFIG_(CPU_JCORE)` build it is\s+not `` | `linux:arch/sh/include/asm/cacheflush.h` | `return !IS_ENABLED\(CONFIG_(CPU_JCORE)\);` | `eq-text` |

  **The second row catches an inversion, and that is worth stating because this
  file says elsewhere that name facts cannot.** The `!` sits *inside* the code
  pattern and *outside* its capture group, so dropping it — the one-character edit
  that turns the gate into its opposite while leaving every guarded wording intact
  — makes the pattern match nothing and fails the row. Verified by running both
  patterns against `origin/jcore` (0 matches, both), against the fix branch (1
  match each, capturing `cacheflush_user_dside_acts` and `CPU_JCORE`), against the
  branch with the `!` removed (0 matches), and against the branch with the `if`
  replaced by `if (1)` (0 matches). **Read the limit honestly**: this works because
  this rule's polarity is a single token that a tight pattern can be anchored
  around. It is not a general answer to C3's inverted-`A2-R1` finding, and nothing
  here claims one.

- **The P4 register offsets are not rows here.** They are a table-vs-table
  comparison (`p4-offsets-match-rtl`), which also catches a register the RTL
  decodes and the map does not list — something a per-fact binding cannot see.
- **P4 addresses restated in RTL *comments* are not checked, and that is a
  measured decision, not an oversight.** B0c built such a sweep and threw it
  away. Three attribution rules were tried against `jcore-cpu`'s `core/` and
  `docs/`, with one known real defect present (`core/components_pkg.vhd` calling
  MMUFSR `0xFF000028`, which is INTEVT's address and precisely the one MMUFSR
  was moved off): *nearest name wins* gave 4 false positives to 1 true;
  *the address's true owner must be named within ±3 lines* gave 7 to 1; *compare
  only where the window holds exactly one address and one name* gave 0 to 0 —
  it skipped the real defect, because an unrelated `EXPEVT 0x0C0` three lines
  below made the window ambiguous. Prose pairs names with addresses by
  apposition and across line wraps, and no regex reads that. A check with a 4:1
  false-positive rate fires on correct comments and gets deleted; a check with
  no true positives is worse than none. The comment defect was fixed by hand
  and the sweep was not shipped. The structured half — the map table versus the
  decode — is checked, and that is where the authority actually lives.
- **The `sh4guest.*` bindings are asymmetric, and the weak side is the code
  side.** All eight were perturbed on the **document** side and every one failed
  with a value disagreement (`says X, but … says Y`), not with a pattern that
  stopped matching — the doc captures are character classes, not literals. The
  **code** captures are a different story and three shapes of them are literals
  by necessity:
  - `sh4guest.fplane`'s code pattern is `\.word\s+0x(F000)`. Widening it to
    `0x([0-9A-F]+)` was tried and is not available: `j4_illegal_trap.S` contains
    nine distinct `.word 0x…` values, so a widened capture trips
    `_sole_capture`'s "captures N different values" arm and fails for the wrong
    reason. The literal is the only workable form, and the cost is that a *code*
    change fails as "pattern matches nothing" rather than as a disagreement.
  - The four `collides` bindings assert only that a given mnemonic appears
    inside a given annotation. The database has no field asserting that two
    encodings coincide, so no single capture can check the thing the fact is
    actually about. **They will go red when B4 re-homes those encodings** — as a
    code-side pattern non-match — which is the intended reminder, not a
    regression. [sh4-guest-model.md §5.1](sh4-guest-model.md) says so where a
    reader hits it.

  Stated because a green run should not be read as more than it is. A previous
  version of this work claimed all these bindings fail on value disagreement
  without distinguishing the two sides; the doc side does, the code side often
  cannot.

- **The two `biendian.*` bindings fail on *both* arms from *both* sides**, which
  the `sh4guest.*` bullet above says is unusual, so the evidence is recorded
  rather than claimed. Each was perturbed four ways against a committed tree and
  the checker's own message was read back:

  | Row | Doc side, value changed | Doc side, phrasing destroyed | Code side, retargeted to a different real value | Code side, retargeted to an absent shape |
  |---|---|---|---|---|
  | `biendian.dside.bytelane` | value disagreement (`says 0001, but … says 1000`) | pattern non-match, doc side | value disagreement (`says 1000, but … says 0100`) | pattern non-match, code side |
  | `biendian.ifetch.select` | value disagreement (`says 2, but … says 1`), **plus** `owner-has-fact` | pattern non-match, doc side, **plus** `owner-has-fact` | value disagreement (`says 1, but … says 31`) | pattern non-match, code side |

  The code side can disagree on *value* here — where the `sh4guest.*` rows can
  only fail on a pattern non-match — because both captures are character classes
  and both files contain sibling constructs holding different values. The
  `datapath.vhm` `case` has four arms with four different `we` masks, so a byte
  map that was remapped rather than deleted still matches and still disagrees;
  that is exactly the mutation Decision B2-1 specified, and it is the reason
  this row exists. `owner-has-fact` additionally fires on
  `biendian.ifetch.select`'s **value** perturbation, because its registry
  `Pattern` spells the literal `instr_o.a(1)` rather than a class, so changing
  the bit trips the registry check and the binding independently.

  **That second failure is a property of the perturbation, not of the binding**,
  and this table claimed otherwise in its phrasing column until the claim was
  checked: the perturbation run there rewrote the surrounding sentence *and*
  removed the `instr_o.a(1)` token, so both checks fired and both were recorded.
  A perturbation that changes only the phrasing around an intact token fires the
  doc-side pattern non-match alone. Reporting the stronger result for a
  perturbation that did not isolate it is precisely the over-reading the next
  paragraph warns about, committed one paragraph above it.

  **What this does not prove**, stated in the same spirit as the bullet above:
  the code-side perturbations move the *pattern*, not the submodule, because the
  code is read from `origin/master` and this repository cannot rewrite it. They
  establish that the comparison and both failure arms work on the real files;
  they do not establish what a real RTL edit would look like. The two are close
  here — retargeting the capture to the `"01"` arm produces the same captured
  string a remapped `"00"` arm would — but they are not the same act.

- **The `sh4guest.*` registry patterns are deliberately tight**, keying on the
  Linux symbol name (`SH_CCR`, `SQ_QACR0`, `SQ_QACR1`) rather than on the hex
  value. The values themselves are not usable as patterns here: `0xFF000038` is
  stock SH-4's `QACR0` **and** J-Core's `ASIDR` alias, and `0xFF00001C` is stock
  SH-4's `CCR` **and** J-Core's `TSBPTR` — the same number naming different
  registers in the same tree. A bare-hex pattern would fire on five correct
  lines in `mmu/`, and the only way to keep it green would be five waiver rows
  for a check that was wrong. The cost is real and is stated rather than hidden:
  `restatement-is-linked` will not catch a bare `0xFF000038` written elsewhere
  as if it were the stock `QACR0`. What is caught is the direction that rots —
  the owning document drifting from the header it claims to follow — because
  each of these facts is code-bound.

- **`hyp.gangswitch.items` now guards the §4.7.1 table against the prose that
  counts it, and that changed on 2026-09-09.** It was added by Wave-3 **C1a**
  because [security/threat-model.md §8](security/threat-model.md) quotes the
  length of
  [hypervisor/hardware-spec.md §4.7.1](hypervisor/hardware-spec.md)'s gang-switch
  list as evidence, and that quotation had to survive an item being added to the
  list. As C1a left it, the row had a hole it recorded rather than closed:
  canonical and scan were the *same* prose pattern, so adding a row to the table
  while leaving the prose one short of the table's length passed with exit 0 —
  nothing read the table. Wave-3 **C1b**, which had to add the ninth row, closed
  it without touching the checker: the **canonical** pattern is now anchored on
  the table's own last row (`| 9 | Restore the incoming guest…`), so the value the
  owner licenses is read out of the table and the owner's own sentence is scanned
  against it like every other document's. Grow the table and renumber, and the
  prose in **both** documents fails until it is updated.

  **What it still does not catch**, stated because a green run should not be read
  as more than it is. C1b ran five perturbations of this row and three failed:
  renumbering the anchor row while leaving the prose behind fails in all three
  documents that state the count, and each prose site failing on its own fails
  too. **Two passed with exit 0.** Inserting a row *before* the anchor without
  renumbering leaves the anchor's number unchanged, and appending a row *after*
  the anchor leaves it unchanged as well — in both cases the licensed value is
  still the old one and nothing notices that the table grew. The anchor is
  load-bearing only while it is genuinely the last row and the author renumbers
  it. Catching the rest needs a row count and a contiguity check over the table's
  index column, which is the shape `p4-offsets-match-rtl` already has and is
  **B0c**'s to write, not a row's to imply. What is now caught is the failure
  that actually occurred — a document quoting a count the list has outgrown, in
  two consecutive waves — and what is not caught has not occurred.

- **`sq.context.bytes` is doc-internal arithmetic, like the two image facts above
  it.** There is no store queue in `jcore-cpu` at all — no SQ region decode, no
  buffers, no SH-4 `PREF` — so there is nothing to bind to, and the row is
  covered by `context-image-sums` over [sq/spec.md §7.2](sq/spec.md)'s field
  table plus a value guard. The table is what caught the defect the row was
  written for: §7.1 enumerated the replicated state as two buffers plus both
  `QACR`s plus `HSQCR` and then costed it at 72 bytes, which is that list minus
  `HSQCR`. The image is 72 and `HSQCR` is counted with the hypervisor register
  block; before the table, nothing could see the difference.

- **`mmu.page.base` binds to Kconfig, not to the RTL,** because the RTL has no
  page-size constant: it is page-size-general, with `PageMask` in `PTEL[11:8]`
  selecting per entry. There is nothing in the hardware for `16 KB` to disagree
  with.

## Value guards

**The hole this closes.** `restatement-is-linked` matches the `Pattern` column,
which spells the *current* value. A **stale** value therefore matches nothing
and is invisible — the escape [0001](decisions/0001-one-authority-per-fact.md)
identified and built `VALUE_SHAPES` for. But that shape scan runs on
`glossary.md` alone, because its rule is "carry no value at all", which no other
document can be held to. So the blindness 0001 closed for one file stayed open
for every other file. Three lines got through the whole of B0a and B0c's first
commit because of it: `hypervisor/hardware-spec.md` §4 previously read
**272 bytes** for the SIMD image *and* listed `VFPUL` among its fields — two
stale facts on one line, which *did* link the owner, so `restatement-is-linked`
was satisfied; `simd/gpu/architecture.md` previously read the same 272 for the
context-switch image; and `jcore-ulx3s-service-plan.md` previously read
**132 bytes** for the FPU image. All three are corrected.

Each row carries two regexes, **one capture group each, and no value**:

- **Canonical** runs against the owner and *licenses* the values it finds there.
  Normally one; two where a fact has a J32 and a J64 form. More than four is a
  failure — a pattern that loose has stopped being a guard. **Every licensed
  value must also appear in some Registry `Constant` cell.** The retraction rule
  below narrows the self-licensing hole but does not close it: a *bare* stale
  value in the owner — a sentence that previously read "the 272-byte SIMD image
  is what Tier 1 shipped", with no retraction phrase to exempt it — licensed 272
  for the whole tree again. The
  Constant cells are a second statement of the same values, maintained by a
  different edit, so a stale value now has to be written into both before it
  licenses anything. This is weaker than a per-fact comparison (any row's number
  counts, not just this fact's) and is stated that way rather than implied; it is
  strong enough for the case it exists to catch, because a retired value appears
  in no cell at all — the row was corrected when the fact was.
- **Scan** runs against every document under `docs/` except `decisions/` (whose
  records quote retired values deliberately). A capture the owner does not
  license is a failure **whether or not the line links the owner** — a linked
  wrong number is still a wrong number.

**The scan pattern must be anchored on the subject noun.** `(\d+)[-\s]byte\s+FPU`
looks right and is not: it fires on "a 4-byte FPU register transfer" and "a
64-byte FPU scratch region", reporting that they "state 4 for `fpu.context.t2`",
which is not what they say. A check that fires on correct prose is switched off
within a month, so the patterns require the word **`image`** — the thing the
fact is actually about. Both patterns match across a line wrap (`\s+`, and the
scan runs over the whole file rather than line by line), because
`272-byte context-switch\nimage` is the same defect reflowed.

Two escapes, and they are different things:

- **A retraction line** — `previously read`, `formerly read`, `used to read`,
  `previously said`, `promoted from` — for text whose subject *is* the
  retirement. This is a third phrase list, written separately from the
  glossary's and `stale-claim`'s, for the reason 0001 and 0002 both give at
  length. **A retraction line in the owner licenses nothing**: the first version
  applied this exemption only when scanning, so writing a sanctioned retraction
  into `simd/spec.md` — one that previously read "272-byte SIMD image" — made
  272 a licensed value for the whole tree, and the restatement this check exists
  to catch then passed with exit 0. The convention for recording history opened
  the hole instead of confining it, which is why the licensing side now applies
  the same exemption.
- **A `no-stale-value` waiver row** below, keyed check × file exactly as
  `stale-claim` is, for a site where the number is a *different quantity* and
  no retraction has occurred. Claiming a retirement that did not happen, purely
  to silence a check, is the failure mode 0002 was written about; there has to
  be a way to say "different quantity" without lying. `--check-waivers` fails on
  a row that stops firing, so the list cannot outlive its sites.

| Fact ID | Canonical (in owner) | Scan (everywhere) |
|---|---|---|
| `fpu.context.t2` | `(\d+)[-\s]byte\s+FPU\s+(?:[\w/-]+\s+)*image` | `(\d+)[-\s]byte\s+FPU\s+(?:[\w/-]+\s+)*image` |
| `simd.context.j32` | `(\d+)[-\s]byte\s+SIMD\s+(?:[\w/-]+\s+)*image` | `(\d+)[-\s]byte\s+(?:SIMD\|context-switch)\s+(?:[\w/-]+\s+)*image` |
| `ooo.uops.rte` | `(?i)\brte\b.?\s*[\|→]\s*(?:\*\*)?(\d+)\b` | `(?i)\brte\b.?\s*[\|→]\s*(?:\*\*)?(\d+)\b` |
| `cache.l2.ebr` | `L2 EBR = (\d+)` | `(?:the )?(?:128 KB )?L2 (?:unified [^\n]{0,20})?at\s*~?(\d+) EBRs` |
| `ooo.gates.core` | `core \+ caches\*\*\s*[\|]\s*\*\*([\d,]+)\*\*` | `(?:OoO budget\|core \+ caches)[^\n]{0,60}?([\d,]+)k? gates` |
| `isa.movi20s.sext` | `sign-extend(?:ed)?\s+from\s+bit\s+\*\*(\d+)\*\*\s+of\s+the\s+shifted\s+value` | `sign-extend(?:ed)?\s+from\s+bit\s+\*\*(\d+)\*\*\s+of\s+the\s+shifted\s+value` |
| `sq.context.bytes` | `(\d+)[-\s]byte store-queue image` | `(\d+)[-\s]byte store-queue image` |
| `hyp.gangswitch.items` | `[\|]\s*(\d+)\s*[\|] Restore the incoming guest` | `\*\*(\d+)\*\* (?:numbered )?items` |
| `security.l6.undefined` | `\*\*(\d+)\*\* open .undefined. sites?` | `\*\*(\d+)\*\* open .undefined. sites?` |
| `gpu.protect.producers` | `\*\*(\d+)\*\* address producers` | `\*\*(\d+)\*\* address producers` |
| `mmu.walk.transmitters` | `\*\*(\d+)\*\* transmitters` | `\*\*(\d+)\*\* transmitters` |
| `hyp.microreset.classes` | `\*\*(\d+)\*\* structure classes` | `\*\*(\d+)\*\* structure classes` |
| `iommu.bypass.paths` | `\*\*(\d+)\*\* bypass paths` | `\*\*(\d+)\*\* bypass paths` |
| `cache.l2.residuals` | `\*\*(\d+)\*\* residual channels` | `\*\*(\d+)\*\* residual channels` |
| `runbook.items` | `\*\*(\d+)\*\* measurement items` | `\*\*(\d+)\*\* measurement items` |
| `runbook.programmes` | `\*\*(\d+)\*\* unscheduled hardware programmes` | `\*\*(\d+)\*\* unscheduled hardware programmes` |

## Enumerations

Facts that state **how many things there are** above a table that lists them.
`enumeration-row-count` requires the owner to carry exactly one table with the
named first two column headers, and that table to have exactly as many rows as
the fact's `## Value guards` canonical pattern finds in the owner.

**Why this table exists.** Four waves perturbed *"delete a row from the owner's
table, leave the count at N"* and four waves recorded **passes** — C2b on a
transmitter row, C2c on a structure-class row, C2d on **bypass path 5, BMID
`0xFF`**, C2e on a residual-channel row. Each disclosure gave the same reason and
the same fix: the value guard compares numbers *between documents* and does not
count rows, and `context-image-sums` — the only row-counting check here — applies
to `Offset | Bytes | Content` layouts, which none of these are. Every one of
those enumerations is load-bearing for a security claim in the way a byte layout
is not: §4.7.1a says its scrub is complete *over its scope*, §16.3 *is* the
honesty list, and §3.10's enumeration is the argument that the bypass paths are
all of them. A shortened list under an unchanged count is exactly how a closed
enumeration becomes an open one.

Located by **column header**, not by section heading, for
`find_tables_by_header`'s reason: renumbering or rewording a heading is an
ordinary edit and must not move a check, while changing what the columns mean is
the event a check should notice. Exactly one matching table is required — zero is
the `simd/spec.md` failure `## Image layouts` was built for, and two or more is
worse, because the check would silently guard whichever came first in the file.

**What it does not buy.** It counts rows; it does not read them. A row *replaced*
by a different row keeps the count and passes, and so does a row whose content is
inverted. That is the standing limit of every check in this file (see the
`W-R1`/`T-R2`/`I-R5`/`P-R2` inversion rows below) and this check does not narrow
it.

| Fact ID | Column 1 | Column 2 |
|---|---|---|
| `hyp.gangswitch.items` | `#` | `Action` |
| `gpu.protect.producers` | `#` | `Producer` |
| `mmu.walk.transmitters` | `#` | `Transmitter` |
| `hyp.microreset.classes` | `#` | `Class` |
| `iommu.bypass.paths` | `#` | `Path` |
| `cache.l2.residuals` | `#` | `Channel` |
| `runbook.items` | `#` | `Item` |
| `runbook.programmes` | `#` | `Programme` |

## Absence claims

Wordings a document **retired**, which must appear in it only as history.
`site-absence-claim` reads this table.

**Why this table exists, and why it took four waves to get one.**
[security/threat-model.md §8](security/threat-model.md) **L6** states a *count*
of open "undefined" sites and the specs state the *closures*, and nothing
related the two. Wave-3 **C2e** demonstrated the consequence and disclosed it
below: invert [cache/l2-spec.md](cache/l2-spec.md) `P-R7` — restore the
"undefined" remainder for a tenant-visible `movca.l` line — and
`security.l6.undefined` still reads **0**, so a specification saying "undefined"
and a count saying no such site exists are licensed simultaneously. C2e's second
row is the same fix's other half: revert §17.5's instruction-table row and leave
`P-R7` standing. Both passed. [sq/spec.md §6.5](sq/spec.md) filed the guard with
Wave-1 task **B0c**, which had closed on 2026-08-25 — six weeks before the
filing — so the obligation was filed against a destination that could not act;
C1b and C2e each declined it in turn, and Task F ranked it 5, recommended it and
did not implement it, because choosing each site's canonical wording is the
owning specs' call and not a reviewer's. **This table is those specs making that
call.** The owner of a row is the document named in it.

**Why the pattern is the retired wording and not the word "undefined".** A scan
for "undefined" fires on correct prose — undefined *encodings*, undefined
*operations*, and the SH-4 manual's own "undefined" that
[sq/spec.md §7](sq/spec.md) narrows rather than contradicts — and this project's
bar is that a check which fires on correct prose is switched off within a month.
The retired *sentence* coming back is syntactic, and the exemption is the tree's
existing convention for recording history: a retraction marker on the matching
line or within two lines above it.

**A row that matches nothing FAILS.** If the retired wording is deleted from the
document altogether, the pattern can no longer notice its return and the row
would pass forever while guarding nothing. `no-stale-value` fails the same way
when its canonical pattern matches nothing in the owner, for the same reason.

**What this does not close.** The retired *rule* reintroduced in different
words. That is Task F's rank-3 inversion; no syntactic check separates it from
correct prose, F declined to recommend one, and nothing here narrows it.

**And the sharper half of the same gap, demonstrated rather than asserted, with
the narrow answer C3 added.** *(2026-09-10.)* An absence claim guards a wording a
document **retired**. It says nothing about a rule the document currently
**states**, so a rule can be **inverted in place** with every guarded wording
intact. C3 perturbed [`A2-R1`](aic/aic2-spec.md) exactly that way — the
delivery-rule pseudocode's `Do NOT deliver` changed to `Deliver to the guest`,
every retraction and every absence claim untouched — and the gate returned
**exit 0**.

There is no general syntactic fix and this table does not claim one. There is a
**per-rule** one, and it is a Registry row rather than an absence claim: register
the single clause carrying the rule's *polarity*, and `owner-has-fact` then
requires it to still be there. `aic2.hostowned.polarity` pins `A2-R1. Do NOT
deliver`; `hyp.bootstrap.polarity` pins `H-B1`'s `MUST NOT be built into a
tenant-facing`. **Read the limit honestly.** This catches the polarity clause
being edited away or deleted. It does not catch the rule being stated correctly
in one place and contradicted in another — which is what
[aic/aic2-spec.md](aic/aic2-spec.md) §5.5 contained for as long as it existed, and
which no check in this file would have found. Two rows are not a policy; they are
two rules whose polarity is the whole of their content, which is what makes the
row worth its cost.

| Site | Document | Retired wording |
|---|---|---|
| `l6.sq.readback` | [sq/spec.md §4](sq/spec.md) | `(?:\*\*)?undefined(?:\*\*)? content` |
| `l6.fpu.restore` | [fpu/spec.md §7.3](fpu/spec.md) | `FR/XF/FPUL = undefined` |
| `l6.l2.movca` | [cache/l2-spec.md §17.5](cache/l2-spec.md) | `remainder undefined until written` |
| `aic2.vector.stride` | [aic/aic2-spec.md §3.4](aic/aic2-spec.md) | `VBR \+ 0x600 \+ vector` |
| `guest.vector.stride` | [sh4-guest-model.md §3.4](sh4-guest-model.md) | `VBR \+ 0x600 \+ vector` |
| `aic2.hostowned.masked` | [aic/aic2-spec.md §5.5](aic/aic2-spec.md) | `masked at the AIC2 level` |
| `hyp.bootstrap.both` | [hypervisor/hardware-spec.md §7.2](hypervisor/hardware-spec.md) | `Implement both` |
| `density.word1.opcode` | [isa-density/spec.md §4.5](isa-density/spec.md) | `not a valid\s+opcode` |
| `mmu.word1.opcode` | [mmu/hardware-spec.md §5.2](mmu/hardware-spec.md) | `not a valid\s+opcode` |
| `cacheflush.noop.threatmodel` | [security/threat-model.md §11](security/threat-model.md) | `every path it dispatches to is a no-op` |
| `cacheflush.noop.review` | [j4-final-review.md](j4-final-review.md) | `every path\s+it dispatches to is a no-op` |

## Image layouts

Facts whose owning spec must carry a `Offset | Bytes | Content` field table.
`context-image-sums` checks each table's running offsets, its terminator total
and its heading, and that the total is a value the owner states.

**Why this table exists rather than a global scan.** The check used to fail only
when *no* layout table existed anywhere in `docs/`, which the one table in
`fpu/spec.md` satisfied forever. `simd/spec.md` had none, and the registry said
otherwise. A per-fact requirement cannot be satisfied by somebody else's table.

| Fact ID |
|---|
| `fpu.context.t2` |
| `simd.context.j32` |
| `sq.context.bytes` |

## Unresolved — facts with no owner yet

A fact with no single true value has no owner, and saying so here is the point.
A registry that quietly omits its holes is the failure of the old glossary in a
new file.

| Fact | State | Owned by (task) |
|---|---|---|
| **TLB fault `EXPEVT` labelling** | **Not a new hole — this row exists to make an old one visible from the registry.** [hypervisor/hardware-spec.md §12](hypervisor/hardware-spec.md) has recorded it since before Wave 2, and §4.2's closing note repeats it: §2.3.1's HEDR rows label bits 4–7 as read/write miss and read/write protection, while [mmu/hardware-spec.md §5](mmu/hardware-spec.md) — which matches `jcore-cpu`'s `decode/gen-go/spec/sh4/exceptions.toml` and is the authority — assigns `0x040`/`0x060`/`0x080` to I-fetch/load/store miss and `0x0A0`/`0x0C0` to protection, with no HEDR bit named for `0x080` at all. Wave-2 **B2** needs one answer to specify guest cause translation ([sh4-guest-model.md §3.4](sh4-guest-model.md), Decision B2-2) and cannot supply it: picking a winner moves which HEDR bit gates which fault. *(A second half of this — `0x800`/`0x820` labelled as FPU arithmetic rather than FPU disable — **was** decidable and B2 decided it from `linux@jcore`; see the correction note in [hypervisor/hardware-spec.md §4.2](hypervisor/hardware-spec.md).)* | **hypervisor / priv-arch spec reconciliation**, per §12's own "owner needed" |
| **Interrupt `INTEVT` value** | **Contradictory, and this one is shipping RTL.** [hypervisor/hardware-spec.md §2.3.1 and §4.2](hypervisor/hardware-spec.md) assign `INTEVT` values `0x600` (external IRL), `0x620` (NMI), `0x640` (user break), `0x6E0` (IPI), `0x700` (PMU), `0x720` (L2 ECC), `0x740` (IOMMU fault) and build the whole single-vector demultiplexing story on them. The core cannot produce any of them. `jcore-cpu@origin/master`'s `decode/gen-go/spec/sh4/exceptions.toml` declares the `Interrupt` entry with `opcode = "---- 0000 dddd dddd"` and `INTEVT<-vec`, and `core/datapath.vhm` loads it as `this.priv.intevt := buses.imm_val(11 downto 0)` from that synthesized code, whose low 8 bits are `cpu_event_i_t.vec` (`cpu2j0_pkg.vhd`: `vec : std_logic_vector(7 downto 0)`) and whose bits [11:8] are the event *command* nibble, `c_event_irq = "000"` for an interrupt (`jcore-soc@origin/master:components/misc/aic2_pkg.vhd`). So a J4 interrupt's `INTEVT` is the **AIC source number in `0x000`–`0x0FF`**, and `0x600` is unreachable. [aic/aic2-spec.md §3.4](aic/aic2-spec.md) matches the RTL; the hypervisor spec does not. Deciding this moves which values `hyp.expevt.*` neighbours state and how a stock SH-4 guest's `INTEVT` is synthesized ([sh4-guest-model.md §3.4](sh4-guest-model.md), Decision B2-2), which is why C3 recorded it rather than picking a winner: C3's remit was to unify the *delegation* description, and one of the two candidates here is a value table this task does not own. *(Found by Wave-3 **C3**, 2026-09-10, while unifying the interrupt-delegation description.)* | **hypervisor / priv-arch spec reconciliation**, the same owner as the row above |
| **CPU P4 decode width vs the P4 block allocation** | Contradictory, and this one is hardware. [soc/p4-mmio-map.md §3.2a](soc/p4-mmio-map.md): `datapath.vhm` gates on `VA[31:24] == 0xFF` and compares only `ma_ad[7:0]`, so on a `PRIV_ARCH` build no P4 access reaches the fabric: a block is implemented as an arm of the `ma_ad[23:12]` page selector or not at all. One of §3's seven blocks (the PMU) has such an arm; six do not and read as zero. The MMU page's byte-wide compare additionally aliases every 256 bytes, which the RTL preserves deliberately. All three widths are code-bound so none can move quietly. | **RTL / SoC integration**, not a doc task; found by Wave-2 **B1** |
| **Instruction encodings** | Not a registry fact by design, and **no longer unresolved as to which file**: [decisions/0003](decisions/0003-canonical-encoding-database.md) makes `jcore-cpu/docs/insns.json` canonical and deletes this repo's copy. Checked by `insns2asm --emit check` and `cpugen insns -check`; prose specs cite it and must not restate bit patterns. | Wave-2 **B4** (the sweep itself) |

## Waivers

Pre-existing bare restatements, enumerated so the checks can land red-free and
be burned down deliberately. **This list may only shrink.** Adding a row is a
change to the decision, not a routine edit; do it in a commit that says why.

Granularity is *waiver-ID × file*. A waiver ID is either a **fact ID** (silencing
`restatement-is-linked` for that fact in that file) or a **check name** —
`legacy-marker`, `stale-claim` — silencing that check in that file. The two are
deliberately separate: a file exempted for one may not be exempted for the other,
which is why `mmu/security-review.md` appears once and not twice.

`glossary-is-value-free` accepts **no** waiver, and the checker refuses one. Its
only escape is a declared, **id-carrying** fence —
`<!-- value-free: off (some-id) -->` — which lives at the point of use *and*
must have its own `glossary-fence:some-id` row below. **The checker reads those
rows**: a fence with no matching row fails, an unnamed fence fails, a reused id
fails, and a row whose fence is gone fails under `--check-waivers`. One row
licenses one region, never the file.

**There are no fences today.** The one that existed —
`glossary-fence:product-table-addr-width`, over the product table's `Addr width`
column — was retired by Wave-2 **B1**, which deleted the column rather than
keeping it fenced: the cell restated what the row's own name says by the §3
naming convention, and the one borrowed value in the region (the J64 VA width)
now links its owner. That is the shape a fence is supposed to have: a named
region, a row that expires with it, and a task that removes both. The mechanism
stays; the fixtures in `scripts/test-check-doc-facts.py` are what exercise it
now.

`scripts/check-doc-facts.py --check-waivers` fails on a row that never fires, so
this list cannot quietly outlive the restatements it covers.

Every row below was produced by running the checker against the tree on
2026-08-25 — none is speculative. `owner-has-fact` and `glossary-is-value-free`
have **no waivers and are live**; those are the two rules
[0001](decisions/0001-one-authority-per-fact.md) calls load-bearing.
`restatement-is-linked` is the burn-down rule, and this is its worklist.

Clearing a row means one of two edits at the cited site: add a link to the owner,
or delete the duplicated value. Both are one-line changes.

| Fact ID | File | Why waived / who clears it |
|---|---|---|
| `bus.bmid.width` | [hypervisor/design-spec.md](hypervisor/design-spec.md) | pre-existing bare restatement — B1 |
| `bus.bmid.width` | [iommu/design-spec.md](iommu/design-spec.md) | pre-existing bare restatement — B1 |
| `bus.bmid.width` | [iommu/hardware-spec.md](iommu/hardware-spec.md) | pre-existing bare restatement — B1 |
| `hyp.expevt.hcall` | [hypervisor/linux-spec.md](hypervisor/linux-spec.md) | pre-existing bare restatement — B1 |
| `hyp.expevt.hypreg` | [hypervisor/linux-spec.md](hypervisor/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.asid.width` | [hypervisor/design-spec.md](hypervisor/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.asid.width` | [hypervisor/linux-spec.md](hypervisor/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.asid.width` | [iommu/design-spec.md](iommu/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.asid.width` | [mmu/design-spec.md](mmu/design-spec.md) | §3.4's heading *is* the value; B1 decides whether design-spec §3.4 or hardware-spec §2.1a owns ASID width |
| `mmu.asidtag.width` | [mmu/linux-spec.md](mmu/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.asidtag.width` | [ooo/j32ooo-spec.md](ooo/j32ooo-spec.md) | pre-existing bare restatement — B1 |
| `mmu.mmufsr.addr` | [mmu/hardware-spec.md](mmu/hardware-spec.md) | §2.11 defines the register and quotes its address; correct content, missing link — B1 |
| `mmu.mmufsr.addr` | [priv-arch/design-spec.md](priv-arch/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.page.base` | [j4-remediation-plan.md](j4-remediation-plan.md) | the plan quotes the review finding verbatim; clears when the plan is retired |
| `mmu.page.base` | [mmu/linux-spec.md](mmu/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.tsb.entry` | [mmu/linux-spec.md](mmu/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.miss` | [hypervisor/design-spec.md](hypervisor/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.miss` | [mmu/design-spec.md](mmu/design-spec.md) | §4.1a argues the split and must name both vectors — B1 adds the link |
| `mmu.vector.miss` | [mmu/linux-spec.md](mmu/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.miss` | [priv-arch/design-spec.md](priv-arch/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.prot` | [hypervisor/hardware-spec.md](hypervisor/hardware-spec.md) | §9 verification points quote both vectors — B1 adds the link |
| `mmu.vector.prot` | [mmu/design-spec.md](mmu/design-spec.md) | §4.1a, as above — B1 |
| `mmu.vector.prot` | [mmu/linux-spec.md](mmu/linux-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.prot` | [priv-arch/design-spec.md](priv-arch/design-spec.md) | pre-existing bare restatement — B1 |
| `mmu.vector.prot` | [priv-arch/j4-implementation-design.md](priv-arch/j4-implementation-design.md) | pre-existing bare restatement — B1 |
| `simd.sr.vd` | [fpu/spec.md](fpu/spec.md) | §7 preamble; **superseded** by B0a, text rewritten by Wave 2 |
| `simd.vfpul` | [fpu/spec.md](fpu/spec.md) | §7 preamble still describes VFPUL as live; **superseded** by B0a, text deleted by Wave 2 |
| `simd.vfpul` | [j4-remediation-plan.md](j4-remediation-plan.md) | the plan quotes the review finding verbatim; clears when the plan is retired |
