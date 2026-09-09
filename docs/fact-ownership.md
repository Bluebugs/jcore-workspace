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

This is a seed, not a census. Rows are added as facts are reconciled; Wave-2 task
**B1** works a contradiction worklist and each item it settles becomes a row here.
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
