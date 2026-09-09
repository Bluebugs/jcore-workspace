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
| `## Waivers` | enumerated, shrinking exemptions | `check-waivers` |

**One cross-table dependency, stated because it is otherwise invisible:** an
`## Image layouts` row needs a `## Value guards` row for the same fact — the
guard is where the expected total comes from, since nothing restates it. A
layout row without a guard fails rather than passing.

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
| `security.l6.undefined` | **1** open `undefined` site under bar item L6: `movca.l`'s L2 line (C2e) | [security/threat-model.md §8](security/threat-model.md) | `\*\*1\*\* open .undefined. site` |
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
| `cache.dma.cacheops` | J4 Linux build compiles **no** cache-operations file; `cacheops-` keys on `CPU_J2` | [decisions/0010](decisions/0010-dma-coherence-is-software-maintained.md) | `` `cacheops-` selector keys on `` |

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
| `sh4guest.csts` | `annotation on fsts FPUL,FRn names ([a-z]+)` | `jcore-cpu:docs/insns.json` | `"collides": \["(csts)\\tCPI_COM,CPI_Rn"\]` | `eq-text` |
| `sh4guest.ldsfpul` | `annotation on lds Rm,FPUL names ([a-z]+)` | `jcore-cpu:docs/insns.json` | `"collides": \["(lds)\\tRm,FPUL"\]` | `eq-text` |
| `sh4guest.stsfpul` | `annotation on sts FPUL,Rn names ([a-z]+)` | `jcore-cpu:docs/insns.json` | `"collides": \["(sts)\\tFPUL,Rn"\]` | `eq-text` |
| `biendian.dside.bytelane` | `` onto `we = "([01]+)"` — bit 3 `` | `jcore-cpu:core/datapath.vhm` | `when "00" =>\s+r\.we := "([01]+)"` | `eq-text` |
| `biendian.ifetch.select` | `` `instr_o\.a\((\d+)\)` — an address bit `` | `jcore-soc:targets/data_bus_pkg.vhd` | `if instr_o\.a\((\d+)\) = '0' then` | `eq` |
| `mmu.walk.spec` | `` `shadow_wr <= (\w+) and walk_side_i` `` | `jcore-cpu:core/cpu.vhd` | `shadow_wr\s*<=\s*(\w+) and walk_side_i;` | `eq-text` |
| `cache.dma.cacheops` | `` `cacheops-` selector keys on `(CPU_\w+)` `` | `linux:arch/sh/mm/Makefile` | `cacheops-\$\(CONFIG_(CPU_J2)\)` | `eq-text` |

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
