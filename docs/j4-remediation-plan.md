# J4 / J32 remediation & direction plan

Status: **draft for review** (untracked). Prepared 2026-08-21 following the
cross-subsystem critical review. This plan sequences three tracks that run
partly in parallel:

- **Track A** — immediate hotfixes for the two *confirmed* code bugs (no spec
  dependency, start now).
- **Track B** — specification / design / documentation reconciliation (must
  precede any *new* implementation).
- **Track C** — security remediation (gated on the threat model from B).

plus two cross-cutting tracks that make the above trustworthy:

- **Track D** — measure-before-implement methodology (turn guesses into numbers
  with explicit decision gates).
- **Track E** — external evidence base (literature that backs or kills a
  direction). *Populated from the prior-art research; see §E.*

---

## Guiding principles

1. **Two platforms, stated explicitly, everywhere.** Phase-1 is the ULX3S /
   ECP5 FPGA at ~40 MHz: the goals there are **correctness, area (LUT/BRAM
   fit), and boot-to-Linux**, and **energy is explicitly out of scope**.
   *(The "~40 MHz" in this sentence is retired — it is J2's row, and J2 has no
   MMU. The measured `[FPGA]` baseline, per core variant, is owned by
   [platform-baseline.md §3](platform-baseline.md), which carries the
   retirement; the Phase-1 deliverable is restated against it by
   [decisions/0009](decisions/0009-in-order-fgmt-is-the-default-path.md) D4.
   Everything else in this principle stands, including the goals list, which is
   what the rest of the plan actually leans on.)* The
   later ASIC (a *new* design — the gf180 target is only a proof the RTL can
   reach an ASIC flow, not the product) aims at ~400 MHz+ where **frequency and
   energy efficiency** become first-class. Every quantitative claim in every
   spec must carry a `[FPGA]` or `[ASIC]` tag. A number with no platform tag is
   a defect.

2. **No claim ships unmeasured.** Most current perf/area/energy statements are
   guesses (the review found area budgets contradicting each other 4–6×). Each
   load-bearing number gets (a) a measurement method, (b) a baseline, and (c) a
   decision gate with an explicit *kill criterion*. See Track D.

3. **The docs are the contract, and the contract is tested.** The most serious
   bug found (the TLB livelock) is a documentation-vs-code mismatch. We fix the
   *process* that produced it, not just the instance: one authority per fact,
   an explicit supersede convention, and CI that fails when a normative constant
   in a doc disagrees with the code.

4. **Adapt as we measure.** This plan is a hypothesis tree, not a commitment.
   Every gate can send us back a step. Decisions and their triggers-to-revisit
   live in a decision log (Track F).

5. **Security is hardware/software codesign, and it must not default to
   slowness.** The easiest secure design is a slow one — that is not the goal.
   For every security requirement that could cost performance or energy, we run a
   *minimize-the-loss research step first* (Track D.3): find the variant that
   keeps the guarantee at the least cost, using the codesign freedom we have
   (custom instructions, hypervisor cooperation, FGMT thread overlap) before we
   implement the naive expensive version. A mitigation that throws away
   efficiency is a last resort, chosen only after the cheaper secure options are
   shown insufficient — and that finding is recorded.

6. **SH-4 / Dreamcast is a guest, not a bare-metal contract.** SH-4 support
   exists **only** on the hypervisor-bearing core (what we call **J4** — J2 plus
   everything specified here) and is delivered by **minimalistic KVM emulation**,
   not by making J4 bare-metal SH-4-compatible. Bare-metal J4 is SH-2-based
   (J2 + J-Core extensions). This reframes most "SH-4 compatibility break"
   findings as *emulation-fidelity* requirements on the hypervisor's SH-4 model
   (see §B2).

---

## Track A — Immediate hotfixes (start now, parallel, no spec dependency)

Both are confirmed against the source in the review. Each follows the same
discipline: **write the failing test first** (prove we can reproduce the bug in
CI/cosim), then fix, then keep the test as a permanent guard.

### A1. TSB walker must honor the page mask for *every* page size  *(critical — the 16 KB livelock is one symptom of a page-size-general defect)*

The manifest bug is a livelock, but the correct scope is broader, per project
direction: **the walker FSM must derive its tag compare and its installed page
size from the entry's page-mask/size field in all cases — 4 KB, 16 KB, and every
huge-page size — not from a hardwired 4 KB assumption.** A fix that only special-
cases 16 KB would re-break the moment a huge page or a 4 KB config is used.

- **Bug (the current symptom):** `jcore-cpu/core/tlb_walk.vhd:258-268` compares
  the stored tag against the full faulting VA at hardwired 4 KB granularity
  (`bus_d(31:12)=va_reg(31:12)`, low 12 bits required zero), while Linux runs
  16 KB base pages and stores a 16 KB-aligned tag (`linux/arch/sh/mm/tlb-jcore.c:200,292`)
  and also registers seven HugeTLB sizes (16 M–256 M) that stamp a page-size slot
  into the PTE (`7af599e05c`). Any access whose first touch of a page is not the
  base sub-page can never match → no retry counter → hard livelock. Huge pages
  would fail the same way for a different bit range.
- **The codesign question to resolve first (HW/SW):** the walker reads
  `tag_hi` *before* the data word that carries the PTEL/size, so it cannot mask
  the tag compare by a size it hasn't read yet. Options, to be decided jointly by
  the RTL and kernel owners: (a) carry the page-size/mask in the *tag* words so it
  is available at compare time; (b) store the tag masked to a canonical maximum
  granularity plus a size field the walker applies before install; (c) index the
  TSB by size class. Whichever is chosen must be written into
  `mmu/hardware-spec.md` and `mmu/linux-spec.md` as one contract, and the RTL
  comment that wrongly assumes `PAGE_MASK == 4 KB` removed.
- **Reproduce first — a *non-vacuous, mixed-size* test matrix (this is the
  point).** The review found the current suite hides the bug because it uses one
  size, VA==PA, base-first working sets. The new suite must, at minimum, cover:
  first-touch of a page in a *non-base* sub-page for each base size; a working
  set that *simultaneously* holds 4 KB, 16 KB, and ≥2 huge sizes with interleaved
  access (so a huge mapping and a base mapping are live in the TLB/TSB at once);
  huge/base *aliasing* of the same VA range; and eviction/replacement across
  mixed sizes. Each case must currently fail (livelock/timeout or wrong
  translation) on the unfixed RTL — a test that passes before the fix is vacuous
  and does not count.
- **Also:** rename the fossil `pteh_tag` parameter (`tlb-jcore.c:157`) and add
  the `BUILD_BUG`/`static_assert` tying the hardcoded `+0/+4/+8` TSB offsets to
  `JCORE_TSB_ENTRY_BYTES == 16` (the assert was lost with `tlbmiss.S`).

### A2. Missing P4 privilege gate  *(critical — apparent user→supervisor escape)*

- **Bug:** `jcore-cpu/core/datapath.vhm:1758` gates the MMU-register MMIO
  read/write block only on `seg_v = SEG_P4`, never on `this.sr.md`. User P4
  accesses aren't translated (`core/cpu.vhd:874-877`) and raise no address error,
  so a user `MOV.L` to `0xFF000010`/`0xFF000014` appears able to write MMUCR /
  TSBBR.
- **Reproduce first:** a user-mode (`SR.MD=0`) load *and* store to each P4 MMU
  register address, asserting an address-error/illegal exception is raised and
  the register is unchanged. The review flagged that `mmup4alias.S` only exercises
  privileged read-back and never asserts a user-mode denial — that gap is the bug
  behind the bug.
- **Fix:** require `SR.MD=1` (and the appropriate hyper-privilege where the map
  says so) for the P4 MMU-register path; deliver the SH-4 address-error/illegal
  exception on user access to a privileged segment. Cross-check against the
  priv-arch spec so the exception class/vector is the SH-4-correct one.

### A3. Warm-reset TLB flush + walker bus-takeover landmine  *(defense-in-depth)*

- `core/tlb.vhd` has no `rst` branch — stale mappings survive a warm reset (safe
  today only because MMUCR resets AT=0). Add an explicit reset-flush or a
  documented, tested invariant.
- The `core/cpu.vhd:697-711` "UNVERIFIED … not fixed here, only recorded"
  double-commit window for an in-flight D-side store during an I-side walk
  (harmful on MMIO/TAS) needs either a proof-it-can't-happen guard or a fix.
  Track as a correctness item, not left as a comment.

> A3 is lower urgency than A1/A2 but belongs on the same fast track because none
> of it needs a spec decision.

---

## Track B — Specification / design / documentation reconciliation

**Rule for this track: no new *feature* implementation starts until the spec it
depends on is internally consistent and platform-tagged.** Bug hotfixes (Track
A) and measurement work (Track D) are exempt.

### B0. Stand up the documentation system (do this first — it's the cheapest
high-leverage fix)

> **B0a — DONE (2026-08-25).** Both bullets below are decided and landed on
> `wave1/foundations`. Decision: **demote the glossary** —
> [decisions/0001](decisions/0001-one-authority-per-fact.md), registry at
> [fact-ownership.md](fact-ownership.md). Supersede convention:
> [decisions/0002](decisions/0002-supersede-convention.md). Both are enforced by
> `scripts/check-doc-facts.py`, which still needs wiring into CI by **B0c** (this
> superproject has no workflow file yet).
>
> One correction to the text below, recorded rather than silently fixed: **there
> is no "hypervisor §2.11".** No hypervisor spec has a §2.11. The single-vector
> text is in `hypervisor/hardware-spec.md` **§4.2** (and its §2.3.1 table); §2.11
> belongs to `mmu/hardware-spec.md` (MMUFSR). Headers were applied to the real
> sections.

- **One authority per fact.** The `glossary.md` claims to be authoritative but is
  itself stale — it previously read VFPUL, 272-byte SIMD context, and
  little-endian throughout. Either make it truly
  authoritative by fixing it and *deriving* the specs' repeated constants from
  it, or demote it to a glossary and name the owning spec per fact. Pick one.
- **Supersede convention.** Every spec section that has been overtaken (e.g.
  `mmu/security-review.md` predating the hardware walker; `hypervisor §2.11`
  single-vector text; the FPU §7 "SIMD never writes FR" text) gets a dated
  `SUPERSEDED BY …` header. A "RESOLVED" marker must link the *merged* commit;
  items whose fix is on an unmerged branch are marked `PENDING-MERGE`, not
  RESOLVED.
> **B0c — DONE (2026-08-25).** Both bullets below are landed on
> `wave1/foundations`, plus the CI that was missing entirely: this superproject
> now has `.github/workflows/docs-gate.yml`, which runs
> `check-doc-facts.py --strict --check-waivers` and its fixture suite. The
> encoding-database ambiguity below — there were **two** tracked
> `docs/insns.json`, 460 and 466 entries — is decided in
> [decisions/0003](decisions/0003-canonical-encoding-database.md):
> `jcore-cpu/docs/insns.json` is canonical and this repo's copy is deleted.
> **Wave-2 B4 sweeps the `jcore-cpu` copy.**
>
> Two corrections to the text below, recorded rather than silently applied.
> **(1) "FPU 132 vs 136" understates it**: 132 was wrong, 136 is right, and the
> §7.4 field table had always summed to 136 — the doc contradicted itself in a
> single row. It is corrected, not merely checked. **(2) A check on page size /
> `PAGE_SHIFT` would *not* have caught the livelock.** 16 KB was correct in the
> docs, in Kconfig and in the RTL throughout; the constant that disagreed was
> the TSB **tag** granularity, which had no registry row and no kernel constant
> at all. That row now exists (`mmu.tsb.tag.shift`) and is bound to
> `JCORE_TSB_TAG_SHIFT` ([mmu/hardware-spec.md §7](mmu/hardware-spec.md)).
> See B0c's report for which check catches which of the
> three named defects.

- **Doc-vs-code CI checks.** Add checks that fail when a normative constant
  disagrees with the code: page size / `PAGE_SHIFT`, TSB entry size and offsets,
  each P4 register offset (`p4-mmio-map.md` vs `datapath.vhm` decode), context
  image sizes (FPU "132" vs 136 bytes — [fpu/spec.md §7.4](fpu/spec.md) owns it;
  SIMD 520). This class of check would have
  caught the livelock, the CPUINFO address, and the FPU image size.
- **One machine-readable source of truth for instruction encodings.** Encodings
  must **not** be hand-written into prose specs (that is how the review found
  VLD.Q aliasing FMOV.S, VMKCHG on FSCA, Tier-0 SUB on SUBC, the `movi20s`
  three-notation muddle, and the `rts/n` "virgin reserve" overlap). The canonical
  encoding database is **`docs/insns.json`**; the specs cite it, they do not
  restate bit patterns. jcore-cpu now carries the Go tooling that did not exist
  when these docs were written and that makes this enforceable:
  - `tools/insns2asm --emit check` — round-trips every encoding losslessly (the
    oracle), and `--emit gas`/`gas-augment`/`llvm` **generate** the binutils/LLVM
    tables *from* `insns.json`. This is also the fix for the binutils findings:
    the toolchain instruction tables should be generated, not hand-maintained and
    left to drift (the J2 `arch_up` and `cas.l→sh-j4` bugs are hand-maintenance
    artifacts).
  - `decode/gen-go/cmd/cpugen freespace --avoid <variants> --form <pattern>
    [--region --family --two-word]` — **finds and selects a free, non-colliding
    binary form** for a new (or corrected) instruction, ranked by proximity to a
    family. This is the tool to use for *every* new encoding from now on, and to
    re-home the colliding ones.
  - CI runs `insns2asm --emit check` and a `freespace`-based collision sweep, so
    a colliding or drifted encoding fails the build.
> **B0b — DONE (2026-09-07), partially.** The rule is
> [decisions/0004](decisions/0004-platform-tag-convention.md), enforced by
> `check-doc-facts.py`'s `platform-tag-foreign-part` check (fail-closed,
> narrow: catches a platform-tag bracket sharing a line with a
> Spartan/Artix/Kintex/Virtex/Zynq mention, not a missing tag). Swept and
> landed on `wave1/foundations`:
> `simd/hardware-impl.md` (the SIMD/FPU FPGA figures named below), the two
> `fpu/spec.md` BRAM figures, and `cache/l2-spec.md` (an L2 power estimate
> attributed to the ECP5 — retracted outright, not merely tagged; it disagreed
> with itself between "total" and "static" in the same document, which is
> stronger evidence than the platform question alone).
>
> **Not done — recorded rather than implied.** Seventeen further specs contain
> untagged LUT/gate/MHz/mm²/EBR figures (`ooo/j32ooo-spec.md` and
> `ooo/j32lt-spec.md`'s energy-percentage claims, `mmu/hardware-spec.md`,
> `jcore-ulx3s-service-plan.md`, `no-gpu-dual-ecp5-asic.md`,
> `ulx3s-soc-component-inventory.md`, and others — the full list is in
> [decisions/0004](decisions/0004-platform-tag-convention.md)'s "What this
> sweep covered, and what it deliberately left"). `security/threat-model.md`
> §9 explicitly defers its own number audit to B0b/B0c and remains
> unaudited. **Do not read this line, or a green `check-doc-facts.py`, as
> "the tree is platform-tagged."**

> **B0d — change of approach (2026-09-07), on the project owner's
> instruction.** B0b kept each figure it could not honestly retarget and put
> prose beside it. That is reversed: a figure nobody measured for the ULX3S/
> ECP5 or for gf180 is **removed**, and the cell where it stood reads that the
> value is not known and has to be measured, in one canonical wording, with at
> most one line saying what would produce it. Budgets, goals and targets stay
> and are labelled as such; so do values that are structural rather than
> measured. The rule is
> [decisions/0005](decisions/0005-unmeasured-figures-are-removed.md), which
> supersedes 0004's rule 3, rule 4's marking half and its Marking convention,
> and is enforced by `check-doc-facts.py`'s `unmeasured-figure-wording` check.
> Applied to `simd/hardware-impl.md`, `cache/l2-spec.md` and `fpu/spec.md`.
> The bullet below still reads "retarget ... onto ECP5 LUT4/BRAM": that is
> what the plan said, and it is left as written rather than quietly edited —
> but retargeting a figure across vendors is arithmetic on a number nobody
> measured, so what B0d did instead is remove it. The seventeen further specs
> B0b listed as unswept are still unswept, and 0005 changes what should be
> done to them without having done it.

- **Platform tags.** Introduce the `[FPGA]`/`[ASIC]` tag rule and sweep existing
  numbers. Retarget the SIMD/FPU FPGA figures (currently Spartan/Artix/130 nm)
  onto ECP5 LUT4/BRAM for Phase-1, and move all energy claims under `[ASIC]`.

### B1. Reconcile the concrete contradictions (assign a canonical answer to each)

A worklist, each item = pick the true value, fix every other doc, add a CI check:

> **B1 status — 2026-09-07.** Worked. Every item below is annotated in place
> with what it resolved to and where the answer now lives. Three things this
> worklist got wrong about itself, recorded because they are the reusable part:
>
> - **Two of the three "area/BRAM" contradictions were not contradictions** — a
>   unit mismatch (gates vs LUT4) and a scope mismatch (one core vs two). Only
>   the OoO LUT4 spread was real, and neither of its sides is measured, so
>   [decisions/0005](decisions/0005-unmeasured-figures-are-removed.md) applies
>   rather than adjudication.
> - **Three items were already closed** before this task and are verified, not
>   re-done: CPUINFO `0x030`/`0x02C`, `TSB_SIZE_LOG` counting sets, and the
>   EXPEVT *assignments*.
> - **The "J4" naming item resolves against the glossary**, not for it. See the
>   long-tail bullet.
>
> Sixteen registry rows and fifteen code bindings were added (18 → 34 and
> 5 → 20 rows), three of them value guards rather than bindings. Two waiver rows
> went — one ordinary `restatement-is-linked` row, and the registry's only
> `value-free` fence together with the row licensing it. Six rows of
> [security/threat-model.md §11](security/threat-model.md) that named B1 as
> owner are closed too — that table is part of this worklist and the bullets
> below are not the whole of it.

- **P4 register map vs real SH-4** — **PARTLY CLOSED.** The map and
  `datapath.vhm` now agree on every offset the RTL decodes; the three stale
  "undecoded in RTL" claims about TRA/EXPEVT/INTEVT/MMUFSR are gone; QACR0 and
  QACR1 carry the allocated-but-unimplemented marker the checker's own docstring
  claimed they had; `0x044` exists as a row. The alias-vs-divergence decision is
  **encoded as an allocation rule**, [soc/p4-mmio-map.md §5](soc/p4-mmio-map.md)
  rule 8: every MMU-block row is *alias* (stock SH-4 offset), *J-Core addition*
  (no SH-4 offset exists) or *deliberate divergence* (names the SH-4 register it
  dodged — `MMUFSR` off `INTEVT`'s `0x028`, the only one). **Still gated on B2:**
  QACR0/QACR1 behaviour and `CCR`, which is allocated nowhere and decoded
  nowhere. **Found while doing this, and larger than the item:**
  [§3.2a](soc/p4-mmio-map.md) — the CPU's P4 decode is byte-wide in both
  dimensions, so on a `PRIV_ARCH` build the datapath consumes *all* of
  `0xFF......` and no P4 block outside it is reachable. That is an RTL question,
  not a doc one; both widths are now code-bound so they cannot move quietly.
- ~~**Endianness**~~ — **CLOSED: big-endian at every product point**
  ([platform-baseline.md §2](platform-baseline.md),
  [decisions/0006](decisions/0006-endianness-is-big-endian.md)). Decided against
  the kernel defconfig and the toolchain target, both of which are big-endian.
  Bound to `linux@jcore`'s `jcore_defconfig`. The glossary's
  `Endianness` column is deleted rather than corrected.
  *This bullet also cited "the RTL's instruction-halfword selection … none of
  which has a little-endian arm" as a third leg. That leg is withdrawn: the
  selection is address-derived and was never the thing that fixed the byte
  order, and the machine now gains a mode
  ([bi-endian-spec.md §5.1](bi-endian-spec.md)). The closure stands on the two
  remaining legs, which are the two that were ever about the product.*
- ~~**Baseline Fmax**~~ — **CLOSED, and it is not one number**
  ([platform-baseline.md §3](platform-baseline.md)). 42 is measured and gated in
  `jcore-cpu` CI; 80 was never measured and is removed with everything derived
  from it. The figure that matters here is neither: **J4-with-MMU measures ~33
  MHz**. All four CI floors in that table are code-bound to the workflow.
- ~~**Area/BRAM budgets**~~ — **CLOSED, and two of the three were not
  contradictions.** FGMT was a unit mismatch (gates vs LUT4); BRAM was a scope
  mismatch (one core vs two) *plus* a genuine 1-EBR disagreement about the same
  L2, now owned by [cache/l2-spec.md §20.1](cache/l2-spec.md) at 69, which makes
  the arithmetic close exactly (105 + 36 = 141). Only the OoO LUT4 spread was
  real, and **neither side of it is measured** — there is no OoO, FGMT or L2 RTL
  to synthesize — so
  [decisions/0005](decisions/0005-unmeasured-figures-are-removed.md) applies and
  the budget is kept, labelled as a budget. *This bullet's original instruction
  — "supersede with one measured/estimated number" — is the convention 0005
  retired: an estimate offered in place of a measurement is exactly what it
  forbids.*
- ~~**L2 write-through vs write-back / MSI-M**~~ — **CLOSED**
  ([cache/l2-spec.md §17.1](cache/l2-spec.md),
  [decisions/0007](decisions/0007-l1d-write-policy-under-msi.md)). The **L2's**
  policy was never in dispute (write-back to SDRAM at every tier); the
  disagreement was the **L1-D**'s, and it was a tier-scoping failure: §2 and
  §10.2 stated the T0 write-through form under a `[T0/T1/T2]` tag. T0 is
  write-through — the shipped L1-D has no dirty bit — and T1/T2 are write-back,
  which is what MSI's `M` state means and what §6.3's local CAS.L requires. The
  DMA obligation this creates is stated in both places rather than left implied;
  it is not yet implemented in `arch/sh`.
- ~~**VIPT vs PIPT L1**~~ — **CLOSED: the answer is PIPT** ([mmu/hardware-spec.md §4.1a](mmu/hardware-spec.md)), established against
  `core/cpu.vhd` rather than adjudicated between documents, with a code binding
  on the relocation bound. `mmu/linux-spec.md` §2.3's VIPT contract and its 4 KB
  page-colouring requirement are withdrawn; the synonym-channel claim in
  `security-review` and `design-spec` holds.
- **The long tail from the review — worked, item by item:**
  - **TSBBR = P1 VA vs PA** — **CLOSED**
    ([mmu/hardware-spec.md §2.6](mmu/hardware-spec.md)): it is a P1 kernel
    virtual address. §2.6's note said so already; its own layout block still read "Physical address of TSB",
    and the J64 sentence said "64-bit physical address". Both corrected, and the
    walker's P1 fold is now code-bound to `core/cpu.vhd`
    ([mmu/hardware-spec.md §2.6](mmu/hardware-spec.md)).
  - **TSB_SIZE_LOG = entries vs sets** — **was already closed** by the Phase-2
    walker work; §2.6 and [mmu/design-spec.md](mmu/design-spec.md) both say
    *sets*. What was still live is its **range**: §2.8a's brute-force argument
    said "64–1024" against §2.6's 6–14 (64–16384). Corrected in three files;
    this retires a `security/threat-model.md` §11 row.
  - **CPUINFO `0x030` vs `0x02C`** — **was already closed** in Wave 1.
    `0x02C` is MMUFSR ([soc/p4-mmio-map.md §3.2](soc/p4-mmio-map.md), decoded), `0x030` is CPUINFO (allocated, not decoded);
    [priv-arch/design-spec.md §4.6](priv-arch/design-spec.md) records the
    superseded relocation proposal. Verified, not re-done.
  - **`rte` uop count** — **CLOSED: 3.** §4.1's table wins over Appendix A's
    grouping; [ooo/j32ooo-spec.md §4.1](ooo/j32ooo-spec.md) owns it, with a
    value guard.
  - **EXPEVT code assignments** — the *assignments* were already reconciled by
    [hypervisor/hardware-spec.md §4.2](hypervisor/hardware-spec.md)'s own
    reconciliation notes ([hypervisor/hardware-spec.md §4.2](hypervisor/hardware-spec.md): `0x180`→`0x1D0`, `0x1A0`→`0x1F0`), and §2.3.1's table
    is internally consistent. What was live: §4.3 gave the inherited SH-4 range
    as "`0x040`–`0x130`, `0x500`–`0x740`", which excludes `0x160`/`0x180`/`0x1A0`
    — the three the paragraph above it insists are inherited — and `0x800`/`0x820`.
    Corrected to point at the table instead of restating a range.
  - **The MMU-doc "J4" naming** — **CLOSED the other way.** The glossary
    deprecated "J4" as a synonym for J32, and nothing complied, including this
    plan's own filename. It should not have: `jcore-cpu@master`'s
    `variants.toml` names `[j4]` as the authoritative build variant
    (`PRIV_ARCH = true`, [glossary §7](glossary.md)). J4 is a bitstream configuration and J32 is a product
    point; [glossary §7](glossary.md) now says that, and the deprecation is
    withdrawn rather than enforced.

### B2. Write down the SH-4 / Dreamcast compatibility model — as a *guest*, not bare metal

> **Delivered: [sh4-guest-model.md](sh4-guest-model.md).** Five numbered
> decisions, a three-way classification of every surface, and a findings map.
> What changed relative to the framing below, since a plan item reversing under
> evidence is a legitimate outcome:
>
> - **Byte order becomes a per-context mode on both paths** — Decision **BE-1**,
>   [bi-endian-spec.md](bi-endian-spec.md), 2026-09-08 on project direction,
>   **superseding Decision B2-1**. The scheme is **byte invariance** (ARM's
>   BE-8): byte accesses are unchanged, 16- and 32-bit values are byte-permuted
>   at the register boundary, and one 16-bit swap is added on the fetched
>   instruction word. The icache, dcache, line-fill packing and bus glue are
>   untouched, because every halfword selection on those paths is
>   address-derived. Nothing of this exists today. **A stock little-endian SH-4
>   binary — Dreamcast images included — becomes executable on the KVM path**,
>   so Dreamcast is gated on the missing FPU and the absent device model rather
>   than on byte order. This re-scopes
>   [decisions/0006](decisions/0006-endianness-is-big-endian.md) a second time
>   and re-arms `fpu/spec.md` §6.2's double-`FMOV` half-pair analysis as a live
>   requirement on any Tier-1 FPU.
>
>   *B2-1, recorded here on 2026-09-08 as "little-endian data becomes a
>   per-guest mode; the fetch path does not", was wrong twice over: it specified
>   a word-invariant change set (an address adjustment, which byte invariance
>   forbids), and it excluded the fetch path on the strength of a halfword
>   selection that is address-derived and therefore mode-independent. Both are
>   corrected in [bi-endian-spec.md §4.4 and §5.1](bi-endian-spec.md). A plan
>   item reversing twice under evidence is still a legitimate outcome, but twice
>   is the point at which the mechanism gets written down rather than the
>   verdict.*
> - **Guest FP is trapped, not native** (Decision B2-4). There is no FPU in
>   `jcore-cpu` at all, and J4 already traps the whole `1111` plane as illegal.
>   This closes one of the two conditions
>   [decisions/0006](decisions/0006-endianness-is-big-endian.md) named for
>   reopening little-endian, in the negative.
> - **The decode-fidelity violations that matter are not the ones this section
>   names, and there are four of them.** The SIMD collisions are on paper. In
>   shipping RTL: `CLDS`/`CSTS` on SH-4's `FLDS`/`FSTS`, **and `LDS Rm,CPI_COM`
>   / `STS CPI_COM,Rn` on SH-4's `LDS Rm,FPUL` / `STS FPUL,Rn`** — the ordinary
>   integer↔FP bridge, outside the `1111` plane and so with no plane-wide
>   illegal-instruction backstop at all. All four are already recorded in the
>   canonical database's `collides` annotations and all four are invisible to
>   the collision sweep, whose variant rule cannot express "an SH-4 guest on a
>   J4 host" (Decision B2-5). **B4 cannot deliver the re-home alone**: these are
>   defined in `decode/gen-go/spec/system.toml`, which generates both the
>   database and the shipping decoder, so it is an RTL change in another
>   repository. **B4 plus an RTL / SoC co-owner.**
> - **`soc/p4-mmio-map.md` rule 8 was factually wrong.** Its "a fourth case is
>   deliberately absent" claim was false when written: three J-Core registers
>   sit on stock SH-4 offsets. The rule now names them and says why the guest
>   model licenses them.


Per project direction, SH-4/Dreamcast is **not** a bare-metal target on any
J-Core core. It runs as a **KVM guest under the J4 hypervisor via minimalistic
emulation**. J4 = J2 + everything specified in this project (MMU, hypervisor,
priv-arch, the extensions); bare-metal J4 is SH-2-based. This changes what the
compatibility policy has to say:

- **The compatibility surface is the *emulated* SH-4 the hypervisor presents to
  the guest, plus whatever guest instructions the hardware runs natively.** So
  most of the review's "silent SH-4 breakage" findings are re-scoped:
  - QACR/QACR0/QACR1, CCR, store-queue behavior, LDTLB, the SH-4 MMU register
    interface, EXPEVT code semantics, AIC2 vectoring → these become
    **hypervisor emulation-fidelity requirements**. The SH-4 device/register
    model the VMM presents must be correct; the P4 map and SQ spec must be
    consistent with *what the emulation exposes to the guest*, not with a
    bare-metal SH-4 that never runs. The A2 privilege gate and trap-and-emulate
    do the containment.
  - The items that still bite *natively* are where guest instructions execute on
    the hardware without a trap: e.g. if the guest uses the SH-4 FPU and the SIMD
    extension reuses FMOV.S/FSCA encodings, the hardware must decode those as the
    guest expects (or the VMM must trap them). **This is now a live path, not a
    hypothetical one:** under Decision BE-1 stock little-endian SH-4 code
    executes natively, so the four shipping-RTL collisions of
    [sh4-guest-model.md §5.1](sh4-guest-model.md) — in particular
    `LDS`/`STS` against SH-4's `FPUL` bridge, which sits outside the `1111`
    plane with no illegal-instruction backstop — are reachable by ordinary guest
    code rather than waiting for a guest that could run.
    The **little-endian paired-FMOV**
    divergence and the **SIMD-vs-scalar encoding collisions** are therefore
    emulation/decode-fidelity questions to pin down, not bare-metal breaks.
    Decide explicitly whether guest SH-4 FP runs natively on J4's FPU or is
    trapped-and-emulated (the OoO/LT cores have no SH-4 FPU until Phase 7).
- **Deliverable:** a one-page model doc stating (a) bare-metal J4 = SH-2 + J-Core
  extensions (what assembles/runs directly); (b) SH-4/Dreamcast = KVM guest, with
  the emulated register/device/FPU surface enumerated and each review finding
  mapped to "emulated here" / "native here (must decode as SH-4)" / "not
  supported"; (c) the fidelity bar (bit-exact where guests observe it — the
  qemu-as-tiebreaker policy needs the same scrutiny). "Silently different from
  what the guest expects" remains the one outlawed outcome — but the *observer*
  is the guest, not bare-metal SH-4 hardware.

### B3. Re-frame the microarchitecture roadmap around the two platforms

> **B3 — decided 2026-09-08. The decision is [decisions/0009](decisions/0009-in-order-fgmt-is-the-default-path.md) and the question below is answered there: dual-issue in-order + 2-thread switch-on-miss FGMT is the default path, new OoO RTL effort pauses, and the reopening trigger is recorded.** The record went to `decisions/` rather than inline because the path it makes the default has no spec to be inline *in*, and because the two specs it most affects are the two it pauses.
>
> **Four corrections to the text below, recorded rather than silently applied**, since three of them are to *this* section's own premises and the fourth is to the evidence §E.1 supplies it.
>
> **(1) "which core actually fits and boots at ~40 MHz" has no answer, because ~40 MHz is not a J4 number.** Against [platform-baseline.md §3](platform-baseline.md) — measured, and code-bound to `jcore-cpu@master`'s `synth-cpu` workflow — ~40 MHz is the **J2** row, and J2 has no MMU, so it cannot host a hypervisor, a guest or a tenant. The core this project builds is **J4**, and it measures materially lower. There is no J4 measurement, floor or goal equal to 40 MHz anywhere in that workflow; the only 40 in it is J2's `ECP5_FMIN_MHZ`. The figure entered this plan at guiding principle 1 and propagated to [decisions/0004](decisions/0004-platform-tag-convention.md) rule 3, [decisions/0005](decisions/0005-unmeasured-figures-are-removed.md) rule 4 and two SIMD implementation guides. It is retired; platform-baseline.md §3 owns the replacement.
>
> **(2) "adding dual-issue or FGMT" is not free, and the margin it spends is now measured.** The J4 CI gate reads **one** `nextpnr` seed against its floor, on a distribution whose seed-to-seed `sd` the workflow puts at ~1.2 MHz. Under the placement weighting CI runs, the 16-seed minimum clears the floor by about one `sd`; under `nextpnr`'s default weighting the 16-seed minimum fell *below* it. So the Phase-1 deliverable is a core with roughly one standard deviation of timing headroom, and every structure the default path adds comes out of that. Recorded here because §B3 asked for the Phase-1 deliverable to be stated and this is the part of the answer that is easy to omit.
>
> **(3) The "~10× the LUTs on the ECP5" in the paragraph below does not survive checking, and §E.1 is where it comes from.** See the correction note at §E.1. In one line: the survey §E.1 names measured a different device family, and the sentence's "on an 84K-LUT ECP5-85F" is not that survey's platform. The area leg of this section's argument is therefore weaker than it reads. **The decision still went the way §B3 expected**, because it never rested on that leg alone and because what it does is shift a burden of proof rather than close a question — 0009 §Context says so explicitly, including what the honest outcome would have been if the area leg had been load-bearing.
>
> **(4) "The OoO fails at hiding SDRAM latency (its stated purpose) regardless of platform" is the strongest claim here and it checked out.** Mutlu, Stark, Wilkerson & Patt, HPCA 2003, pp. 129–140: a machine with a 128-entry window "spends 71% of its cycles in full instruction window stalls", and removing the main-memory latency rather than the scheduler is what fixes it. One precision point that makes the claim *stronger* than §E.1 states it: the 128 entries are micro-operations, not instructions.
>
> **What did not change.** The direction, the burden-of-proof flip and the pause are all as this section directs. The reversal is in one of the three supporting arguments, not in the conclusion.

Fold the dual-target principle into the service plan and the OoO/FGMT specs.
Concretely: state the Phase-1 FPGA deliverable (which core actually fits and
boots at ~40 MHz), and separate it from the ASIC ambitions (frequency/energy).
The OoO-vs-FGMT question is decided *here*. **The evidence base (§E.1) already
points strongly at dual-issue in-order + 2-thread switch-on-miss FGMT** for both
targets — the OoO fails at hiding SDRAM latency (its stated purpose) regardless
of platform, costs ~10× the LUTs on the ECP5, and concentrates ASIC power in the
exact structures (issue-queue CAM, rename) it adds. This flips the burden of
proof: **OoO must now demonstrate, on a model over real memory-bound traces, that
it beats in-order+FGMT at equal area/effort — not the reverse.** Until it does,
new OoO RTL effort pauses and the FGMT path is the default. Keep this reversible:
the decision log records the trigger that would reopen it.

### B4. Encoding-verification sweep of *every* documented instruction

> **B4 — swept 2026-09-08; four items handed on with owners.** The results are
> [encoding-sweep.md](encoding-sweep.md) and the method is
> [decisions/0008](decisions/0008-documented-but-unimplemented-encodings.md).
> **Four corrections to the text below, recorded rather than silently applied.**
>
> **(1) Step 1 names the wrong file.** `docs/insns.json` is *generated* from
> `decode/gen-go/spec/*.toml`, and that same tree generates the shipping
> decoder — measured, by diffing the emitted VHDL. So "enter it into the
> database" is an RTL change, which the whole of SIMD cannot be.
> [decisions/0008](decisions/0008-documented-but-unimplemented-encodings.md)
> settles what a documented-but-unimplemented instruction does instead.
>
> **(2) Step 2's arbiter cannot arbitrate.** `insns2asm --emit check` is
> nominated to settle `movi20s`'s sign-extension notation; its oracle
> reconstructs the bit-pattern *string* and models no immediate semantics at
> all. Upstream binutils settled it instead
> ([isa-density/spec.md §3.1](isa-density/spec.md)) — and the two readings the
> spec called different are the same function on all 2²⁰ immediates.
>
> **(3) The cross-spec reserve conflict named below does not exist.** `rts/n`
> and `rtv/n` are already in the canonical database and live on J2A and SH-2A,
> so `freespace --avoid` excludes them; the MMU document's own published command
> reproduces its "8 free, all virgin" exactly. Closed as not-a-defect. **The
> real conflict is [simd/spec.md](simd/spec.md) against
> [mmu/hardware-spec.md](mmu/hardware-spec.md)** over the same family — SIMD's
> `VINS` group already spends five of those eight slots — and both documents now
> say so.
>
> **(4) The named SIMD list is incomplete in the direction that matters.**
> Beyond `VLD.Q`/`VST.Q`, `VMKCHG`, `VLNS` and the `SUBC` reuse — all confirmed
> — four of five `VEXT` slots are live SH-2A `mov` encodings **on J2A**, and
> `VINS.L` is SH-4A `synco`, a Decision B2-5 violation nothing had noticed.
> `VLNS` cannot be re-homed at all: it spends both nibble fields, so it claims
> 16 minors of a family with six free, and its 4-bit lane index cannot address
> 32 byte-lanes anyway. One cause, one fix, and it is the SIMD spec's to take.
>
> **What is handed on, with owners**, in
> [encoding-sweep.md §8](encoding-sweep.md): committing the CPI re-homing
> (**B4 + RTL/SoC**, as §B2 already required); deciding `VLNS`'s shape and
> re-homing `VINS.L` (**SIMD spec**); settling the contended reserve (**MMU +
> SIMD specs**); and, still **B4**'s and still open, teaching the collision
> sweep about guest-hosting — without it the next `VINS.L` is found by a person
> reading tables again. **Step 4 (toolchain delta) was not reached and would
> have been a no-op**: nothing in this sweep changed a live encoding.

Per project direction: now that the encoding tooling exists, **every currently
documented instruction gets its binary form verified and re-homed through the
tools** — not just the ones the review caught. The docs were written before
`freespace`/`insns2asm` existed, so their bit patterns were hand-chosen and never
machine-checked. This sweep is a prerequisite for any spec work that adds or
touches instructions (SIMD, isa-density, isa-pcrel, FPU, the hypervisor LDC/STC
encodings).

Method, per instruction:
1. Enter it into `docs/insns.json` (the canonical source) if not already present.
2. Run `insns2asm --emit check` — it must round-trip losslessly. A failure means
   the documented encoding is inconsistent with its operand/field layout.
3. Run the `cpugen freespace` collision check against the full variant set. Any
   instruction whose encoding collides with a live SH/J-Core encoding (outside a
   context that disambiguates it) is **re-homed**: pick a new free form with
   `freespace --avoid <all colliding variants> --form <its field layout>
   [--region] [--family <its group>]`, update `insns.json`, re-run check, and
   update the spec to cite the new encoding.
4. Regenerate the toolchain delta (`insns2asm --emit gas`/`llvm`) so binutils/LLVM
   track `insns.json` rather than carrying hand-written entries.

Known encodings the review flagged as needing this treatment (non-exhaustive —
the sweep must cover all, but these are the confirmed collisions/ambiguities):
- **SIMD:** `VLD.Q`/`VST.Q` reuse the SH-4 **FMOV.S** encodings while claimed
  valid outside a SIMD block; `VMKCHG` collides with **FSCA**; `VLNS` overlaps
  `VEXT.*`; Tier-0 governed `SUB` is given **SUBC**'s encoding and then reused for
  `VABSDIFF`; the 4-bit lane/swizzle fields can't address 32 byte-lanes at
  VLEN=256. Each must be re-homed or its in-block-only constraint enforced in the
  encoding, decided jointly with the SH-4-guest decode-fidelity policy (§B2).
- **isa-density:** the `movi20s` sign-extend/shift notation appears three
  inconsistent ways across spec/impl — pin one and let `insns2asm --emit check`
  be the arbiter; confirm `movmu`'s `m=15` anchor against SH-2A via the tool.
- **Cross-spec reserve conflict:** the MMU doc calls `0000 nnnn xxxx 1011` "8 free
  slots, all virgin," but isa-density plans byte-identical SH-2A `rts/n`/`rtv/n`
  at minors `0110`/`0111` of that family. `freespace --avoid` over the *union* of
  both docs' claims resolves who owns which slot — exactly the check that was
  missing.

Deliverable: `docs/insns.json` covers every documented J-Core instruction, the
`check` gate is green in CI, no encoding collides, and the specs cite `insns.json`
instead of restating bits.

---

## Track C — Security remediation (threat-model-gated)

### C0. Write a current threat model and supersede the stale review *(do first)*

> **C0 — DONE (2026-08-25).** The threat model is
> [security/threat-model.md](security/threat-model.md). It supersedes
> `mmu/security-review.md` §0–§1 and `mmu/design-spec.md` §6.0, re-derives the
> verdicts B0a flagged (AnC reverses to *applies*; the `ASID_TAG`-truncation
> conclusion survives on a collision demonstration; S-I3 closes on two merged
> legs), and ratifies §E.11's bar as **L1–L7** — renumbered off `A1`–`A6` because
> those IDs collided with the Track-A hotfix numbers, and with **L7** added for
> the walker's data source, which §C2 identified but E.11 never lifted into the
> bar. §E.10's overhead figures are ratified as a *position* and classified
> individually as sourced / literature / estimate in
> [§9 of the threat model](security/threat-model.md).

`mmu/security-review.md` reasons from "the walker is software" — false since the
hardware walker landed. Replace it with a threat model that states, up front:
the actual adversary (a **guest kernel** on a shared core in a public
multi-tenant service, not merely user-vs-kernel), the TCB, the sharing model
(FGMT + gang-scheduling), and which cores it covers (the product is the
*speculative* J32-FM, so Spectre-class attacks apply — the "does not apply"
verdict must not be inherited from the in-order core). This document defines the
**minimum security bar for multi-tenant launch** (see §E for the evidence-based
proposal) and every item below is gated on meeting it.

### C1. Confirmed-mechanism fixes (specify the normative behavior, then implement)

- **SQ buffer residue** → mandate a scrub (or unconditional full-64B restore) on
  any SQ ownership change; define guest reads of the SQ region as defined-safe
  (trap or zero), not "undefined".
- **FPU/SIMD register residue on first touch** → mandate scrubbing the FR/XF/
  FPUL and V-file/P0/VCSR to defaults for a fresh context with no saved image;
  extend gang-switch invalidation to the FP/SIMD register files.
- **Lazy FD/VD on speculative cores** → require non-forwarding of stale FP/V
  state under a pending FD/VD trap, or adopt **eager** FP/SIMD switch (the
  post-LazyFP industry norm — §E). Cross-reference the OoO transient-exec spec.
- **Vertical FP SIMD ownership hole** → close the case where SIMD reads/writes
  FPSCR while SR.FD=1 and FPSCR belongs to the parked owner (wrong rounding-mode
  + sticky-flag corruption). Add a `kernel_fpu_begin`-equivalent discipline and a
  scrub requirement for kernel crypto that stages key material in V registers.

### C2. Structural gaps (need a design decision, informed by §E)

- **GPU memory protection** — currently none; user shaders get raw physical
  base addresses. Decide the isolation mechanism (per-context base+bounds, or
  route GPU masters through the IOMMU with BMIDs) *before* the GPU bring-up runs
  user OpenCL. This is a launch blocker for any GPU-in-multi-tenant scenario.
- **FGMT cross-thread isolation backstop** — "core = tenant unit, enforced by
  the scheduler" needs either a hardware backstop or an explicit, evidence-based
  acceptance that mirrors how clouds disable SMT (§E). Decide and document; do
  not leave it implied-safe.
- **Speculation coverage is D-side only** — extend the delay-on-miss / no-
  speculative-fill rules to the **instruction side** (wrong-path fetch + the
  always-on I-prefetcher fill the shared L2) and resolve the speculative-hit
  pLRU-update contradiction and speculative TLB/TSB fill. Pick a defense from the
  measured menu in §E rather than inventing one.
- **Hardware TSB-walker merge ordering** — gate the walker's merge on the
  read-only-guest-TSB enforcement and the `TSBBR` bounds check landing first;
  add the mandatory negative test. Until then the walker must keep the per-LDTLB
  verification path.
- **IOMMU** — add a per-BMID **deny/block** state; make **reset = deny** (not
  bypass) or a documented brief bypass window that locks after handoff; a
  **write-once lock** on `SUPER_BYPASS`; guard the GLOBAL IOTLB bit (the S-I7
  lesson); define detach/teardown re-protection; quota the shared IOTLB. Commission
  the IOMMU security review that currently doesn't exist, and own coherent-DMA
  vs the write-back L2 (the L2 exposes no fabric snoop port today).
- **Cache partition honesty** — scope the L2 "closes the channel by
  construction" claim to the *occupancy* channel; document the residual shared-
  MSHR / bank-FIFO / bandwidth / pLRU channels; decide whether user-mode
  `ocbi/ocbp/pref` (a Flush+Reload primitive across the partition) needs
  privilege gating or is accepted.

### C3. Lower-severity tracked items

Interrupt-delegation description unified across the hypervisor/AIC2 docs; HCALL
rate-limiting/DoS; HCALL-bootstrap TCB inversion; LFSR reseeding + boot-time
entropy; embedded-immediate gadget acknowledgement. Each gets a decision, not
necessarily a fix.

---

## Track D — Measure before we implement

The engine of the whole plan. For every "guess" we attach a measurement and a
gate. General method, then the per-decision table.

### D0. Measurement infrastructure (build once, reuse)

- **FPGA hardware counters** — the cores already expose PMU/walk counters
  (`walk_cnt_walks/hits`, PMCYC/PMINS). Boot Linux on ULX3S and collect real
  TLB-miss rates, walk latency, cache miss rates, IPC on real workloads
  (CoreMark, a kernel build, lmbench, the actual tenant mix). This is the
  highest-fidelity, lowest-cost data source we have and it is under-used.
- **Cycle cosim** — extend the existing cosim beyond VA==PA small working sets
  so it exercises the cases that hide bugs (non-base-first page touches, TLB
  pressure > entry count, mixed I/D walks). The mmudrain-style capacity canaries
  become a real suite.
- **Architectural modeling for what we can't yet build** — for OoO/FGMT/L2/SIMD
  tradeoffs, use a parameterized model (gem5 has an SH/SuperH-ish path, or a
  small trace-driven model) calibrated against the FPGA counters. Model first,
  RTL second.
- **Energy — `[ASIC]` only** — do NOT try to measure energy on the ECP5. Get
  energy numbers from gate-level activity + power analysis in the ASIC flow
  (sky130/gf180 as the *methodology* vehicle even if not the product), driven by
  switching activity from real traces. Until an ASIC flow produces a number,
  energy claims are literature-calibrated estimates, tagged as such.

### D1. Per-decision measurement gates (each has a kill criterion)

| Decision (current guess) | Measure how | Baseline | Gate / kill criterion |
|---|---|---|---|
| OoO worth it vs in-order FGMT *(prior: drop it — §E.1)* | Model both on real traces; FPGA-measure the in-order+FGMT point | measured in-order wall-clock at the J4 `Fmax` of [platform-baseline.md §3](platform-baseline.md) — this cell previously read "80 MHz in-order J32", a figure nothing produced | Burden is on OoO: keep it **only if** it beats in-order+FGMT at equal area/effort AND holds `Fmax` ≥ 50 MHz. Else **drop OoO** (default). Note that 50 MHz is above every measured variant today, J2 included |
| "2–3× aggregate throughput" | Trace-driven model at ~200 MB/s memory | measured single-thread | Ship the *measured* multiplier; if < 1.5×, re-set expectations |
| TLB size 8I/16D | FPGA miss-rate on real workloads at 16 KB pages | SH-4 64-entry | If miss-cost > a set % of runtime, grow TLB or lean on huge pages before shrinking further |
| Hardware walker (serialized 3-6 reads) | Cosim/FPGA walk-latency; compare burst | software refill (22–23 cyc) | If serialized walk ≥ software path, add burst read or reconsider |
| Dirty-bit = full TSB wipe | FPGA fault-rate on write-heavy workloads | — | If first-write flush dominates, add single-entry invalidate |
| SIMD beat-serial throughput | Micro-benchmark governed vs scalar on FPGA | scalar SH loop | Publish per-tier real speedup; kill tiers that are ~neutral |
| L2 partition perf | FPGA per-tenant thrash with N ways | unpartitioned | Set min ways/tenant from data; verify inclusion self-thrash |
| Speculation defense cost | Model delay-on-miss + I-side variant | unmitigated | Adopt the cheapest defense meeting the bar (§E) |
| Energy per op `[ASIC]` | Gate-level power on traces | — | Compare OoO vs FGMT energy; inform the ASIC core choice |

### D2. Calibrate against prior art (Track E) before spending RTL effort

Where we can't measure yet, the literature gives us priors and sanity bounds.
The research in §E is the first pass; we keep a living bibliography and cite it in
each spec's rationale so future readers see *why* a number was chosen.

### D3. The security-vs-efficiency research gate (per principle 5)

Any Track-C security fix that could cost performance or energy passes through a
**minimize-the-loss research step before implementation**. The deliverable of
that step is: the security guarantee stated precisely, the cheapest known
variant(s) that still meet it (with literature numbers), the codesign levers
available (custom instruction, hypervisor cooperation, FGMT thread overlap,
dirty/partial tracking, background work), and the experiment that will measure
the residual cost. Only if the cheap options are shown insufficient do we accept
a slow mitigation — and we record *why*. The recurring low-overhead levers this
project has that generic designs don't:

- **FGMT thread overlap** — cycles one thread loses to a security delay
  (e.g. delay-on-miss) are partly reclaimed by the sibling thread. Speculation-
  mitigation cost should be measured *on the FGMT core*, not taken from single-
  thread papers.
- **Short speculation window** — a dual-issue in-order pipeline has a far smaller
  mis-speculation shadow than an OoO core, shrinking both the attack surface and
  the mitigation cost.
- **Codesign instructions** — J-Core already has multi-register moves
  (`movmu`/`movml`); the same idea applies to bulk/partial state save-restore and
  scrub, so eager FP/SIMD switching need not be naive.

**First-pass answers are in (§E.10); each still needs FPGA confirmation via §D:**

| Security item (Track C) | Efficiency risk | Minimize-loss answer (first pass — measure to confirm) |
|---|---|---|
| Speculation: delay-on-miss + frontend coverage (C2) | lost MLP / stalls | Bare DoM (no filter cache, **no value prediction**); FGMT overlap + ~2–6-cycle in-order shadow → target ~1%, likely net-positive energy. Frontend: predictor-updates-at-commit + 2–3-bit tenant-tagged BTB + degenerate-STT taint. Gang-scheduling removes the cross-tenant FGMT channel. |
| Eager FP/SIMD switch + scrub (C1) | ~520 B V-file + FPU per switch | Eager+scrub **only at cross-tenant boundary**, dirty-bit lazy within tenant; 2-bit init/clean/dirty per block skips untouched state; movmu-style bulk save + per-register zero bit + background scrub → <0.9% @40 MHz. |
| Cache isolation beyond ways (C2) | partition perf loss | DAWG-semantics ways (hit+fill masks + partitioned replacement metadata) ≤2%; hypervisor UCP epochs *beat* free sharing; per-thread MSHR reservation ≈0 on in-order. |
| Core=single-tenant + flush on realloc (C2) | gang-switch flush (~15k cyc cold) | Tenant-tagged predictors (nothing to flush) + fence.t-style multi-cycle microreset of untagged transient state; **write-through L1 collapses the flush** to ~10² cyc; <1% at ms timeslices. |
| Scrub SQ / registers on ownership change (C1) | zeroing cost on switch | Per-register/valid zero bit (1-cycle); background overlapped scrub under the hypervisor switch code; cross-tenant only; constant-time padded. |

---

## Track E — External evidence base

*Populated from the prior-art research (in progress). This section will hold, per
decision: the claim, the source (title/URL/venue/year), the number, and the
J-Core implication — plus a synthesis of "what the evidence says we should do"
and the proposed minimum multi-tenant security bar.*

Two prior-art briefings were commissioned to back or kill the load-bearing
directions. The findings are distilled below with primary sources; the full
briefings are archived in the review scratchpad. **Confidence:** the
microarchitecture evidence is strong enough to act on now; the security evidence
sets a hard minimum bar.

### E.1 — Out-of-order vs in-order dual-issue + FGMT  *(evidence points strongly one way)*

The core finding: **a small OoO core cannot do the one job used to justify it**
(hiding 30–50-cycle SDRAM latency), while 2-thread FGMT does it by construction
and dual-issue in-order captures most of the width benefit at a fraction of the
cost.

- **Small windows can't hide memory latency.** Mutlu et al., *Runahead
  Execution*, HPCA 2003 — even a 128-entry window is insufficient for main-memory
  latency. Hiding a 40-cycle miss at 2 IPC needs ~80 instructions in flight, i.e.
  an 80+-entry ROB + proportional LSQ/rename — far beyond any "small 2-wide OoO"
  J-Core could afford. A small OoO buys ILP-on-hits, **not** SDRAM tolerance.
  https://people.inf.ethz.ch/omutlu/pub/mutlu_hpca03.pdf
- **FGMT is the FPGA-friendly, throughput-per-area winner.** BOOM (OoO) ≈ 49,865
  LUTs vs Rocket (in-order) ≈ 5,073 — ~10× — on an 84K-LUT ECP5-85F (RISC-V
  soft-core survey, TU-Braunschweig). FGMT with threads = pipeline stages
  *removes* hazard/forwarding logic and can raise Fmax (Fort, FCCM 2006;
  Labrecque, FPL 2007). MIPS 34K measured **~60% throughput for ~14% area** from
  FGMT on an in-order Linux core (EE Journal, 2006).

  > **Two of the three citations in this bullet were checked at source on
  > 2026-09-08 by Wave-2 **B3** and do not hold. The bullet is left as written,
  > per this plan's practice of correcting rather than rewriting the review text
  > it quotes; the corrections are load-bearing and are in
  > [decisions/0009 §Context](decisions/0009-in-order-fgmt-is-the-default-path.md)
  > and §Citations that did not survive checking.**
  >
  > **The device is wrong.** The survey is Dörflinger et al., *A Comparative
  > Survey of Open-Source Application-Class RISC-V Processor Implementations*,
  > ACM Computing Frontiers (CF '21) — and its abstract states its results are
  > for "the Xilinx Virtex UltraScale+ family and GlobalFoundries 22FDX ASIC
  > technology". There is no ECP5 in it, and UltraScale+ LUTs are 6-input where
  > the ECP5's are 4-input, so "84K-LUT ECP5-85F" is not a restatement of that
  > survey. [decisions/0004](decisions/0004-platform-tag-convention.md) rule 3
  > names this exact defect by part family. What survives is that a third-party,
  > peer-reviewed comparison under forced-common parameters puts an
  > out-of-order RISC-V core at a *multiple* of an in-order one on both FPGA and
  > ASIC — evidence about the shape of the cost, not a magnitude for this board.
  >
  > **The MIPS 34K attribution is wrong and the result is narrower than stated.**
  > It is Kissell, *Demystifying multithreading and multi-core*, **EDN, 26
  > September 2007** — not EE Journal 2006 — and it reads: "an increase in area
  > of 14% can buy an increase of throughput of 60% relative to a comparable
  > single-threaded core (as measured using the EEMBC PKFLOW and OSPF
  > benchmarks, run sequentially on a MIPS32 24KE core versus concurrently on a
  > **dual-threaded** MIPS32 34K core)". A vendor-authored trade-press claim on
  > two networking kernels, not a general result. Note what it *is*, though:
  > two threads on an in-order embedded core is precisely the configuration
  > §B3's decision adopts, so this is the piece of §E.1 that transfers most
  > directly to J-Core and it was the piece cited least precisely.
- **The Niagara precedent.** Kongetira et al., *Niagara*, IEEE Micro 2005 —
  8 single-issue in-order cores × 4 threads, zero-cycle switch, no per-core branch
  predictor, chosen *specifically* because memory stalls dominate and OoO gives
  poor return per watt/mm². Tera MTA (Emer, MIT 6.823) hid ~70 cycles with barrel
  threading and no cache — but needed 128 threads, so **2 threads hide a fraction
  of a 30–50-cycle stall, not all of it.**
- **Dual-issue in-order captures most of the width win.** ARM A53 (2-wide
  in-order) ≈ A9 (OoO) performance at ~40% less area (Chips and Cheese, 2023).
  Lean dual-issue in-order RISC-V: 1.47× speedup, 1.37× better energy efficiency,
  no ROB/rename/CAM (DAC 2025, arXiv:2503.20590). SonicBOOM CoreMark/MHz 2.3→6.2
  is ~2.7× but for a wide/deep OoO at ~10× area; a realistic small 2-wide OoO
  lands ~1.4× over in-order (CARRV 2020).
- **OoO energy is concentrated in exactly the proposed structures.** Alpha 21264
  (Gowan et al., DAC 1998): issue queue + rename ≈ 13% of *total chip* power; the
  issue queue alone is 50% of the fetch/issue box. The wakeup-CAM is the
  structure a whole 2000–2005 subfield existed to de-power (Folegnani, ISCA 2001).
- **Honest counter-evidence.** Hölzle, *Brawny cores beat wimpy cores*, IEEE
  Micro 2010 — many slow threads cost single-thread latency and Amdahl serial
  sections. Reading for J-Core: don't let per-thread IPC collapse (favors 2-thread
  switch-on-miss FGMT over a 4–8-way barrel), but this argues against barrel, not
  against FGMT-over-OoO.

**Implication:** for both the FPGA and the ASIC, the evidence favors **dual-issue
in-order + 2-thread (switch-on-miss) FGMT** over the ROB/rename/CAM OoO. This
turns the §B3 "decision" into "confirm our own model reproduces a well-supported
prior," and it materially de-risks the ECP5 fit and the ASIC energy story.

### E.2 — TLB sizing + 16 KB pages + hardware walker  *(evidence supports current direction, with conditions)*

- **8 ITLB / 16 DTLB at 16 KB = the reach of a 32/64-entry 4 KB TLB** (128 KB I,
  256 KB D). Apple Silicon runs 16 KB pages kernel-wide; the decisions are
  defensible *jointly* (either alone is weaker). Condition: **keep the TLBs fully
  associative** — a 64-entry TLB loses ~9 points of hit rate going
  fully-assoc→direct-mapped.
- **Ordinary-workload ceilings are modest:** dTLB hit 90–95%, iTLB >99%, and a
  perfect 1-cycle MMU is worth only 4–12% IPC on the worst SPEC/PARSEC cases
  (Patil, arXiv:2002.01073). The 10–51% TLB-cost horror numbers (Basu, ISCA 2013)
  are multi-GB working sets — far from J-Core's regime. So the shrink is tolerable
  **if walks stay cheap** (the small TLB shifts cost onto the walker).
- **Hardware TSB walker is the right call.** Software refill is 20–>400 cycles,
  high variance (Nagle, ISCA 1993). A single-level hashed TSB walk is structurally
  better than a radix walk that needs MMU caches to become tolerable (Barr, ISCA
  2010; ~135-cycle avg radix walks, Patil). **Two refinements the evidence
  demands:** (a) fetch the TSB bucket as one SDRAM **burst** — the current
  serialized 3-per-way word reads leave locality on the table; (b) keep walker
  fills **out of L1-D** (AMD walks in L2 specifically for pollution — Patil ref).

### E.3 — Performance-claim realism  *(evidence kills the "2–3×" figure)*

- 200 MB/s at 400 MHz is **0.5 bytes/cycle** — one line fill per ~64 cycles.
  Memory-bound throughput is bounded by bandwidth × MLP, not issue width. The two
  "2×"s (dual-issue and 2-thread) **do not multiply** — they compete for the same
  stall cycles and the same pipe. Plausible composite: ~1.5× (dual-issue) × ~1.3–
  1.6× (2nd thread on miss-heavy code) ≈ **2× best case, converging to 1.0× as
  miss traffic saturates SDRAM**. "2–3×" holds only for cache-resident loads.
- **Do not validate on CoreMark/Dhrystone** — they fit in cache by design (EEMBC
  says so and built CoreMark-PRO to fix it). Use CoreMark-PRO, kernel builds,
  netperf. Re-baseline the advertised number to the measured composite.

### E.4 — Speculation defenses  *(delay-on-miss is a good primary, proven incomplete)*

- **Delay-on-miss is cheap and validated as a *primary* mitigation:** ~11% perf /
  7% energy *with value prediction* (Sakalis et al., ISCA 2019; TC 2020) — and an
  in-order-ish core with little MLP loses less than a big OoO. Good choice.
- **But D-side-only is formally bypassable.** Pensieve (ISCA 2023) model-checked
  delay-on-miss/InvisiSpec/GhostMinion and *found* Spectre-like attacks.
  Speculative Interference (ASPLOS 2021) leaks via timing of older instructions
  even when no speculative miss issues. The frontend is a transmitter: STT/NDA/
  DOLMA and the SoK (arXiv:2301.03724) classify D-cache-only as partial coverage;
  the branch predictor itself leaks (arXiv:2107.09833).
- **So:** keep delay-on-miss, **stop claiming completeness**, and add frontend
  coverage (no secret-dependent speculative I-fetch/BTB/ITLB updates past
  unresolved branches). Cheapest comprehensive options for a small core: MuonTrap
  (flush-on-switch filter cache, ~4%) or STT (8.5–14.5%, the cheapest scheme with
  a *formal* non-interference proof).

### E.5 — Multi-tenant thread sharing  *(the scheduler-only model is accepted only as a coarse rule)*

- "Core = tenant unit, enforced by scheduler" **is** industry practice — but as a
  *coarse allocation rule* where a core is never shared between tenants. AWS Nitro
  never co-schedules two customers on sibling threads; Azure ships SMT-off SKUs
  for isolation.
- Software scheduling has a **documented track record of leaking** when it *does*
  share threads: MDS (line-fill/store buffers — not cache-partitionable),
  PortSmash (execution-port contention, zero shared memory, CVE-2018-5407),
  TLBleed. The Linux core-scheduling docs state it themselves: "the only full
  mitigation of cross-HT attacks is to disable Hyper-Threading," and enumerate an
  IPI-race window. OpenBSD disabled SMT outright.
- **So:** J-Core's gang-scheduling is defensible **only if** (a) all threads of a
  core always belong to one tenant, and (b) core reallocation flushes *all*
  thread-shared state (pipeline buffers, predictors, MSHRs). **Cross-tenant
  fine-grained MT is out of bounds for launch.**

### E.6 — IOMMU  *(current direction is on the wrong side of every norm)*

- Thunderclap (NDSS 2019): IOMMU-*on* but permissive/coarse mappings → arbitrary
  kernel R/W in seconds. J-Core's **global-match IOTLB entry** is exactly this
  failure mode.
- Boot/reset bypass windows are an actively-closed threat (Garrett; Linux
  deferred-attach; IOMMU deferred-invalidation, DATE 2024). J-Core **resets to
  all-bypass and leaves unclaimed devices in bypass forever** — the boot-window
  vuln made permanent.
- Secure designs are **default-deny from power-on**: Apple DART ("default-deny …
  the instant the system is powered on"), Windows Kernel DMA Protection (block
  until authorized). **So:** flip to default-deny reset, per-device block state,
  block-until-mapped for unknown devices, drop the global IOTLB match. Largest
  single gap vs norms; a launch blocker for tenant-controlled devices.

### E.7 — Lazy FPU/vector switch  *(the spec reproduces a known CVE)*

- Leaving the previous owner's FR/XF/V contents until first-touch **is** LazyFP
  (CVE-2018-3665): the #NM window lets the new context speculatively read stale
  registers and exfiltrate via cache. Linux made eager FPU the default in 2016 and
  **removed lazy mode entirely**. **So:** eager FP/SIMD save-restore (or scrub) on
  every cross-tenant/context switch. Well-understood, low-cost fix.

### E.8 — Cache partitioning limits  *(way-partitioning ≠ isolation)*

- Way-partitioning (Intel CAT-equivalent) closes only the crudest eviction-set
  channel. DAWG (MICRO 2018) had to add isolation of **hits, misses, and
  replacement metadata** — "in CAT, access patterns leak through metadata updates
  on hitting loads." Residual channels that survive way-partitioning: replacement/
  LRU metadata (DAWG), shared **MSHRs** (Speculative Interference; MSHR-contention
  papers), **DRAM row-buffer / bandwidth** contention (DRAMA, USENIX 2016, ~2 Mbps
  cross-CPU with no shared memory/cache), and **user-mode flush** enabling
  Flush+Reload (Yarom & Falkner, USENIX 2014 — 96.7% of a GnuPG key from one op).
- **So:** if way-partitioning is the story, also partition replacement metadata +
  MSHRs per tenant, add memory-bandwidth QoS, disable cross-tenant page dedup, and
  gate user-mode `ocbi`/`ocbp`/`pref` at the tenant boundary.

### E.9 — What the evidence says, in one paragraph

Drop the ROB/rename/CAM OoO in favor of **dual-issue in-order + 2-thread
switch-on-miss FGMT** (nearly dispositive on FPGA, strong on ASIC energy, and the
OoO fails at hiding SDRAM latency regardless). Keep the 8/16 TLB + 16 KB pages
(fully associative) and the hardware TSB walker, but **burst-fetch the bucket and
keep walker fills out of L1-D**. Re-baseline the throughput claim to ~2× best-case
/ ~1× at the bandwidth ceiling, measured on CoreMark-PRO-class loads. On security,
keep delay-on-miss but add frontend coverage; make the FPU switch eager; flip the
IOMMU to default-deny; treat way-partitioning as one control among several.

### E.10 — Minimizing the security-performance loss  *(the D.3 research, first pass — it confirms the thesis)*

A dedicated research pass priced every perf-sensitive security fix for **this**
core (small, dual-issue in-order, 2-way FGMT, write-through L1, gang-scheduled).
**Result: the mitigations that look expensive in the OoO literature are all
sub-1% here** — the OoO tax is mostly the price of protecting deep speculation and
dirty write-back state this core doesn't have. The only genuinely costly option is
static partitioning of dynamically-shared pipeline/bandwidth, which adaptive or
software regulation recovers.

**Speculation — target ~1%, likely net-positive energy:**
- **FGMT recovers the delay-on-miss cost.** DoM is −18% on an 8-wide OoO
  (Sakalis, IEEE TC 2020) and that loss is memory-overlap an in-order core barely
  has; switch-on-miss FGMT hands the stall cycles to the sibling thread. Measuring
  DoM-under-FGMT is an open experiment and the novel number to publish. **Skip
  value prediction** (adds ILP not MLP; +1pp even on OoO).
- In-order is not automatically safe — the A53 fills a line ~2 instructions into
  the shadow (SiSCloak) — but the shadow is ~2–6 cycles, so gating fills costs
  almost nothing. **Cheap frontend coverage:** predictor/BTB/RAS update **only at
  commit** (wrong-path trains nothing); **2–3-bit tenant-tagged BTB/PHT** (ARM
  CSV2 partial-context — zero flush, zero warm-up, beats full-flush 26–37%);
  **degenerate-STT taint** (1 bit/register — a shadow-load result can't feed a
  missing address, redirect fetch, resolve a branch, or train a predictor);
  delayed speculative TLB/PTW fills. ProSpeCT shows the taint unit fits a small
  FPGA core (+17% LUT, +2% critical path).
- **Tenant switch:** fence.t-style microreset, <1% at ms timeslices; tagged
  predictors survive. **Gang-scheduling by tenant** makes the cross-tenant FGMT
  contention channel structurally absent *and* legitimizes the sibling-thread
  recovery. **Don't build:** value prediction, MuonTrap filter caches (fallback),
  full STT, SafeBet.

**Eager state switch + scrub — sub-1%, and write-through is the enabler:**
- Eager FP/SIMD switch of the ~520 B V-file is ~150–350 cycles via movmu/movml
  bulk moves → <0.9% at 40 MHz/1 kHz, <0.09% at 400 MHz. The trap-based lazy
  scheme is the thing to avoid (it *is* the LazyFP channel). **Dirty/init tracking**
  (2-bit per block, like RISC-V FS/VS) makes the save ~0 when the unit was
  untouched; **eager across tenant boundary, dirty-bit lazy within a tenant**
  (Linux/KVM already do this).
- **Scrub:** fence.t full on-core scrub is <1% perf / 0.13% area. **The
  write-through L1 collapses the flush** from ~21,755 cycles (dirty-writeback
  dominated) to a ~16-cycle reset — a structural advantage, keep it. Measured
  gotchas to honor: a **single-cycle flush pulse leaks** (assert reset several
  cycles); you must also reset the **replacement LFSR, arbiters, and miss
  handler**. Per-register zero bit = 1-cycle zeroing; background scrub overlaps the
  hypervisor's switch code; scrub **only on cross-tenant**; pad the switch to
  constant latency so it leaks nothing.

**Cache isolation beyond ways — metadata bits, not cycles:**
- **DAWG** (isolate hits + misses + replacement metadata) is ≤2% at half-cache,
  ~0 elsewhere — the marginal cost over the CAT-style ways you'd build anyway is
  metadata bits. **Dynamic sizing (UCP)** *beats* free sharing (+11% weighted
  speedup, <2 kB monitor); hypervisor-driven at quantized epochs so the adaptation
  channel is negligible. **MSHRs:** per-thread static reservation ≈ 0 on an
  in-order core (SecSMT). **Bandwidth:** MemGuard-style software miss-budget
  throttling eliminated >50% interference; a 2-tenant TDM arbiter closes it in
  hardware. **Randomized caches** only degrade conflict (not occupancy) channels
  and cost ASIC energy — partitioning is the right tool for an isolation
  *guarantee*. **Software levers (pay in memory, not cycles):** per-tenant-only
  KSM; privileged/audited `ocbi`/`ocbp` (removes the cheapest Flush+Reload
  primitive at ~0 perf).

Full briefing: `evidence-security-minoverhead.md` in the review scratchpad.
**Takeaway: "slowness is not the price of security" holds numerically for this
core — proven cheap by construction (small window, write-through, rare switches,
gang-scheduling), pending the FPGA measurements in §D.**

### E.11 — Proposed minimum security bar for a multi-tenant launch

Anything less leaves a *documented, demonstrated* cross-tenant channel open:

- **A1 — Core = single tenant at all times.** No two tenants share a core's
  threads; core reallocation flushes all thread-shared microarch state. *(E.5)*
- **A2 — IOMMU default-deny.** Block-all at reset; unclaimed devices stay blocked;
  per-device domains; no global-match IOTLB. *(E.6)*
- **A3 — Eager FP/vector switch (or scrub) on every cross-tenant switch.** *(E.7)*
- **A4 — Speculation covers loads AND frontend**, with a tested threat model that
  names residual channels rather than claiming Spectre is closed. *(E.4)*
- **A5 — Cache isolation beyond ways:** per-tenant replacement metadata + MSHRs,
  bandwidth QoS, no cross-tenant page sharing, no unprivileged cross-tenant flush.
  *(E.8)*
- **A6 — Scrub on ownership change** for SQ buffers and FP/SIMD register files;
  no "undefined = previous tenant's data" anywhere. *(review §2)*

---

## Track F — Ways of working (keep us honest and adaptive)

- **Decision log.** One append-only file: each architectural decision, the
  evidence/measurement behind it, the date, and the **trigger that would make us
  revisit** (e.g. "revisit OoO if FGMT Fmax lands < 45 MHz"). The review found
  the same fact re-decided differently across docs; a log stops that.
- **Kill criteria up front.** Every experiment states, before it runs, what
  result would end it. The service plan already gestures at this ("if
  delay-on-miss > 20%, reconsider OoO") — make it universal.
- **Merge discipline.** No spec marked RESOLVED without a merged commit link; no
  RTL feature merged ahead of its stated security precondition (the walker/
  read-only-TSB ordering is the cautionary example).
- **Stay flexible.** This plan is versioned; when measurement contradicts a
  direction, we update the plan and the decision log, not just the code.

---

## Suggested sequencing (first 4 moves)

1. **Track A hotfixes** (livelock, P4 gate) with their missing tests — this week,
   parallel to everything else.
2. **B0 doc system + B4 encoding sweep** (single source of truth, supersede
   headers, platform tags, doc-vs-code CI; `docs/insns.json` as the one encoding
   source with `insns2asm --emit check` + `freespace` collision sweep in CI) —
   cheap now that the tooling exists, stops new drift immediately and fixes the
   hand-chosen colliding encodings.
3. **C0 threat model + D0 FPGA measurement harness** — the two foundations the
   rest of Track C and D depend on.
4. **The OoO-vs-FGMT decision (B3/D1/E)** — the biggest fork in the roadmap;
   settle it with the model + evidence before more OoO RTL effort.
