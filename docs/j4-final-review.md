# J4 remediation programme — whole-implementation review

**This file holds two reviews of the same programme, in one place deliberately:
a programme with two competing final reviews is the defect this whole effort has
been about.** **Part I** is **Task F2** (2026-09-10), a delta review of the 25
commits that landed after F — the post-F blocking-findings work, the first code
in the programme, two submodule repoints, and C3. **Part II** is **Task F**
(2026-09-09), the original whole-implementation review, unaltered. Read Part I
first: it says which of F's conclusions survived, and it corrects F's own record
of what it reviewed.

**Task F.** Reviewed 2026-09-09 against `main` at `eb62a37`, branch `final/f-review`.
Scope: all merged tracks — Wave 0 (hotfixes), Wave 1 (foundations), Wave 2
(reconciliation), Wave 3 (eight security designs).

**Where this document lives, and why it is not a decision record.**
[decisions/README.md](decisions/README.md) says a decision goes inline in the spec
that owns its subject, and that `decisions/` exists **only** for decisions with no
owning spec. A review is not a decision under that format at all — it has no
*Decision*, no *Enforcement* and no *Rejected alternatives* — and its subject is
the programme rather than any subsystem, so no spec owns it either. The precedent
in this tree for a programme-level report is [j4-wave0-status.md](j4-wave0-status.md),
at the root of `docs/` beside the two plan documents. This file sits there for the
same reason. Anything here that *is* a decision has been written into the owning
document instead; this file records findings and points at them.

---

## Part I — Task F2, the second review

**Task F2.** Reviewed 2026-09-10 against `final/f2-review` at `405c250`, cut from
a freshly-merged `main`. Scope: **the delta since F** — the 25 commits that
landed after F's own commit `b76c545..405c250`, and the consistency of the tree
those commits left behind. It is not a re-survey; where F and the work that acted
on F agree and I found nothing to the contrary, this part says nothing.

Code evidence is from remote refs only, per
[decisions/0002 §2](decisions/0002-supersede-convention.md):
`jcore-cpu@origin/master` `e8a5a4e1`, `jcore-soc@origin/master` `39b6abe3`,
`linux@origin/jcore` `3c1453a9`. Note that the workspace *pins* `jcore-cpu` at
`6475932e`, which lags `origin/master`; nothing below is read from a checked-out
pointer.

**Two corrections to this document's own front matter before anything else.**
F's header says it reviewed "`main` at `eb62a37`". `eb62a37` is not an ancestor
of F's commit and exists on no branch but `wave1/foundations`; F's actual base
was `b76c545`, which is on `main`. And the work since F is **25** commits, not
27: fourteen post-F blocking-findings commits, two submodule repoints, and nine
for C3.

### F2.1 The verdict

**The single most valuable thing the post-F work and C3 produced is the first
code in the programme, and it is also the thing that broke the most.** The
kernel patch is right; the six documents that describe the kernel are now wrong,
one of them is the gate's own registry, and the tripwire the threat model wrote
for exactly this event did not fire. That is not a criticism of the patch. It is
the measurement F's §2 predicted: the machinery guards attribution and
arithmetic, and the one thing it has never had to survive is a fact changing in
the code.

**F's second-most important sentence is still true after 25 commits.** 68
registered facts; 14 carry a value guard; 31 carry a code binding; 6 carry an
enumeration; **not one carries both a value guard and a code binding**, and 23
carry none of the three.

**And the inversion gap is not narrowed.** C3's per-rule polarity fact is a real
mechanism and it works on the rule it was written for. It covers 2 of the ~70
normative rule identifiers in `docs/`, none of the four F named, and I defeated
it in one edit using this tree's own house style — §F2.4.

### F2.2 What the new work closed

- **The [`P-R8`](cache/l2-spec.md) ↔ [0010](decisions/0010-dma-coherence-is-software-maintained.md)
  decision-4 collision is closed, and then *built*.** `linux@origin/jcore`
  `3c1453a9` is the squash merge of `mountain-reverie/linux`#16. Verified at the
  remote: `arch/sh/mm/Makefile` carries `cacheops-$(CONFIG_CPU_JCORE) :=
  cache-jcore.o`; `arch/sh/mm/cache-jcore.c` writes only
  `jcore_ccr_base + hard_smp_processor_id()` inside `preempt_disable()`;
  `cache-j2.c`'s `for_each_possible_cpu()` loops are gone; and
  `arch/sh/Kconfig`'s `DMA_NONCOHERENT` now selects `ARCH_HAS_SYNC_DMA_FOR_CPU`.
  The kernel half of [`P-R8`](cache/l2-spec.md) is honoured: no cross-core write
  to the block survives except `j2_send_ipi()`'s, which [`P-R8`](cache/l2-spec.md) names and accepts.
- **F's finding (b) holds.** `arch/sh/kernel/cpu/sh2/smp-j2.c`'s `j2_send_ipi()`
  writes `1U<<28` to `j2_ipi_trigger + cpu` — the **target** core's word — and
  the RTL decodes `db_i.d(28)`. It is the only `send_ipi` J-Core registers.
- **The L2 carrier fix is right.** [hypervisor/hardware-spec.md
  §2.10](hypervisor/hardware-spec.md) gained a second presence trigger — `HTCR`
  is now required on any implementation "with more than one thread context **or
  with the way-partitioned shared L2**" — which is what makes moving the L2 tag
  off the optional `PDID` an actual fix rather than a rename. `P-E6` refuses to
  elaborate a partition on a part that reports `CPUINFO[18]` clear. §F2.3 records
  the one place the old rule survived.
- **C3's §5.5 rewrite is one coherent reason and not a fourth.** The three
  incompatible justifications are gone and the replacement is a single rule with
  a number, stated at AIC2. I checked for a fourth reason and there is none.
- **C3's `msk` claim is true of shipping RTL.** `cpu2j0_pkg.vhd`'s
  `cpu_event_i_t` carries a `msk` bit, and `decode/decode_core.vhm` lines 681 and
  769 gate acceptance on `( ibit < event_i.lvl or event_i.msk = '1' )`. `IRL=15`
  really is maskable and `msk` really is the bit that is not.
- **The prior-art class is closed for C3's own text.** C3 adds four external
  citations — Arbaugh/Farber/Smith 1997, Yarrow-160, Abadi et al. CCS 2005, and
  `A2-R1` explicitly owing none beyond §5.8's pre-2006 rows. All are pre-2006,
  all correctly attributed, every quoted passage corroborated at source, and no
  new figure is attributed to an external work. The residue is the post-F sweep's,
  not C3's — §F2.3.
- **F's two ownerless obligations have owners**, and both rows are in
  [security/threat-model.md §11](security/threat-model.md)'s defect table. I
  confirmed both.

**A clean bill where I looked hard and found nothing**, stated because a delta
review that reports only breakage is not a measurement. C3 retired the
per-vector interrupt stride ([priv-arch/design-spec.md §4.5](priv-arch/design-spec.md)
owns the real value); every surviving occurrence of the strided form in the tree
is a marked-retired quotation or an absence-claim tripwire pattern, [sh4-guest-model.md §3.4](sh4-guest-model.md) does re-derive
**B2-3** on three legs that use no vector, and
[priv-arch/design-spec.md §4.5](priv-arch/design-spec.md) — named as the owner —
agrees. C3 retired the "an interior word is not a valid opcode" claim; nothing in
`isa-pcrel`, `encoding-sweep.md`, the non-FPU encoding database,
`bi-endian-spec.md` or any delay-slot or exception-restart passage reasons from
it. C3 retired the "implement both" HCALL bootstrap option; no document still
offers the two as interchangeable. And C3's two-part test on §5's
denial-of-service scope-out reconciles with §7.7a rather than adding a fifth
position — the new text quotes §7.7a's own wording, and the other three documents
that scope DoS out do it against [`I-R8`](iommu/hardware-spec.md) rather than
against §5.

### F2.3 What the new work broke

**A. The kernel merge falsified six documents and nobody swept.** All verified at
`linux@origin/jcore` `3c1453a9` this session.

1. **[fact-ownership.md](fact-ownership.md) row `cache.dma.cacheops`.** The
   `Constant` cell was updated to "The J4's `cacheops-` arm compiles
   `cache-jcore.o`". Its `owner-has-fact` **pattern was not**: it still reads
   `` `cacheops-` selector keys on `` ([0010](decisions/0010-dma-coherence-is-software-maintained.md)),
   a string whose only occurrence anywhere in `docs/` is that record's line 107, a
   present-tense bullet asserting that the selector keys on `CPU_J2` and that
   `cacheops-y` is empty for the J4. **The name guard for this fact is anchored
   to a sentence that contradicts the fact and is now false**, so correcting the
   sentence turns the row red for the wrong reason. This is the failure class the
   row's own post-mortem is about, in the row itself.
2. **[0010](decisions/0010-dma-coherence-is-software-maintained.md) lines
   100–118** — the whole "the kernel side is worse than 0007 assumed" list — is
   written in the present tense and is false at `origin/jcore`, with **no
   supersede marker**. Decision 4 immediately below it carries one.
3. **[j4-execution-plan.md](j4-execution-plan.md) lines 495–499 and 518–523.**
   The programme's dispatch document still says the J4 build "compiles **no**
   cache-operations file at all" and that decision 4 "**is** dispatchable, in
   `linux`, today". The one buildable item in the programme is still listed as
   buildable after it was built.
4. **[security/threat-model.md §12](security/threat-model.md)'s tripwire fired
   and nothing moved.** The bullet reads "**`arch/sh` gains a `cacheops-` arm for
   `CPU_JCORE`.** Today the J4 build compiles none, so every DMA
   cache-maintenance call is a no-op." That is the trigger's own condition and it
   has happened. This is the first time in the programme a code-change tripwire
   has had the chance to fire, and it did not.
5. **[security/threat-model.md](security/threat-model.md) §11, and this one is
   security-relevant.** ***Closed 2026-09-10; the sentence below is quoted as the
   wording that was withdrawn, and the finding it names is fixed.***
   The row **used to read**, of `sys_cacheflush(2)`, that "on J4 every path
   it dispatches to is a no-op — so it is neither a flush primitive nor a channel
   there." `arch/sh/kernel/sys_sh.c` dispatches straight into
   `__flush_invalidate_region` / `__flush_purge_region` / `flush_icache_range`,
   and `cache-jcore.c`'s region helpers **ignore `start`/`size` and invalidate the
   whole L1-D**. Unprivileged userspace holding any valid VMA can now force a
   whole-L1-D invalidate. The code's reason for ignoring the region is sound — the
   L1-D is write-through with no writeback path — but the *channel* conclusion
   rested on "it is a no-op", and that premise is gone.
   **Resolution.** The data side no longer runs for userspace on J-Core, the
   instruction side is [§10 item 19](security/threat-model.md) accepted with a
   reason, and §11's clause is corrected rather than annotated. Two things this
   item got right that are worth keeping, and one it overstated: the write-through
   argument holds and is now the *justification* for the fix rather than a
   consolation; the "any valid VMA" reach is exact, and a zero-length range works
   too. Overstated: the reach is **not** cross-core on anything that ships today,
   because `CPU_SUBTYPE_JCORE` does not `select SYS_SUPPORTS_SMP` — which is item
   6's own "also under-stated" note, arriving as the mitigating half of item 5.
6. **The J4 ASIC target has no cache maintenance and no document says so.**
   `jcore-soc@origin/master:targets/asic/gf180_j4mmu/board.dts` has neither a
   `jcore,cache` node nor an IPI node, so `jcore_cache_ccr_init()` takes its warn
   path there and every J4 cache primitive stays a no-op on the ASIC vehicle.
   0010's "Done" section reads as unconditional.

   *Also under-stated rather than false:* `CPU_JCORE` selects `CPU_SH2`, `OF`,
   `OF_EARLY_FLATTREE` and `ARCH_SUPPORTS_HUGETLBFS` — **not**
   `SYS_SUPPORTS_SMP` — and `config SMP depends on SYS_SUPPORTS_SMP`. A J4 kernel
   cannot enable SMP at all today, so the "cross-core reach comes from the IPI"
   dependency the split acquires is a `CPU_J2` fact and, for the J4, prospective.

**B. The `HTCR` fix did not reach the whole of `HTCR`'s own document.**
[hypervisor/hardware-spec.md](hypervisor/hardware-spec.md) line 2045, in the cost
summary, still says `HTCR` is "required only on implementations with more than
one thread context" — the exact rule §2.10 replaced 1,500 lines above, and the
exact rule that made the `PDID` version of this defect possible. Same document,
same register, two presence rules.

**C. C3 added a fourth action to a three-write list.** Gang-switch item 6 now
reads "Switch `TSBBR`, `PDID`, `HTCR`, **and re-seed the TSB victim selector**"
and its `Cost` cell still reads "three register writes".

**D. `A2-R1` is stated at a block that cannot see its own predicate — which is
the defect C3 says it is fixing.** C3's argument is that a rule stated where it
cannot see the property it depends on is not enforceable, so it moved the rule to
AIC2. AIC2 cannot see it either. [aic2-spec.md §2.2](aic/aic2-spec.md)'s signal
list is `cpu_event_i_t` (outbound), `cpu_event_o_t`, `aic_com`, direct source
lines and an MMIO slave port; `cpu_event_o_t` at `jcore-cpu@origin/master` is
`{ack, lvl, slp, dbg}`, with no mode bit. §5.1's hyperprivileged bank holds
`GUEST_OWNED` and `GVCPU_TARGET` and no "which `(G, V)` is dispatched on TC *t*"
state, and §7.4's dispatch sequence writes only those two. So "a guest vCPU is
dispatched on `TARGET[s]` with `SR.HPRIV = 0`" has no wire and no register. C3's
note says the predicate "costs nothing new" because §5.2's fast path already
needs it — that is true, and the fast path never had it either. **§5.5 now makes
`A2-R1` "the whole of the argument" that the delegation is confined to the
guest's own sources**, so the whole of that argument rests on an input the
specification does not provide. This is a specification gap, not an RTL one: it
is fixed by naming the port or the register, in §2.2 and §5.1.

**E. `A2-R1` has no way to stop re-firing.** It leaves `PEND[s]` set and
deliberately files nothing in `HVDP` — "a host-owned source has no `(G, V)` to
file it under" — so the hypervisor's ping carries no identification (`HVDP_SUMMARY`
reads zero for it, and §5.4 says reading `HVDP_SUMMARY` is how the hypervisor
finds out what happened), and on return to the guest `ENABLE[s] & PEND[s]`
requalifies and the rule fires again. The rule's own text permits the hypervisor
to "undispatch **or defer**"; deferring livelocks. The only safe response is
undispatch, which makes "serviced one HS entry later than before" an
under-statement: the real cost is a vCPU undispatch per host-owned interrupt.
Two smaller things in the same section: §5.2's pseudocode still spells both slow
paths "at `IRL=15`" with no `msk`, and conformance item T2-9 attaches the `msk`
requirement to `A2-R1` alone rather than to the internal vector.

**F. The prior-art sweep's own residue.** The post-F commit says the retired
speculative-taint name "is retired everywhere it appeared". It is not.
[security/threat-model.md](security/threat-model.md) line 1264 — the **L4 bar
requirement itself** — still names it; line 510 states the poison-bit framing
that [ooo/j32ooo-spec.md §20.7](ooo/j32ooo-spec.md) forbids **by name** ("Do not
'simplify' §9.4 rule 3 into a poison bit, and do not reintroduce the name");
[j4-execution-plan.md](j4-execution-plan.md) line 114 carries it unannotated. And
F §7 item 3 recurs verbatim one file over:
[j4-remediation-plan.md](j4-remediation-plan.md) line 816 still gives UCP
(MICRO **2006**) and DAWG (2018) as the *adopted answer* for C2's cache
isolation, ~320 lines above the §E.10 entry that was re-grounded.

**G. A removed figure survived twice, which [0005](decisions/0005-unmeasured-figures-are-removed.md)
does not permit.** The post-F carrier fix **removed** §16.1's "~200 gates" — the
section says so in terms, "removed rather than annotated … because it was costed
against 'the domain tag is already on the fabric', which is false". The figure is
still in that document's own changelog at line 26 ("way partitioning closes it for
~200 gates"), and still in
[security/threat-model.md](security/threat-model.md)'s evidence table at line
1643, sourced to the section that no longer carries it and with `Synthesize` as
the action — commissioning synthesis of a number that has been withdrawn. The
neighbouring rows of that same table were updated on 2026-09-10.

**H. Three self-referential counts that the same commits got wrong.**
[ooo/j32ooo-spec.md](ooo/j32ooo-spec.md) line 1257 says the retired
speculative-taint name "was being carried by **five** other documents"; at
`e98119a^` it appears in **four** (`j4-execution-plan.md`,
`j4-remediation-plan.md`, `mmu/hardware-spec.md`, `security/threat-model.md`),
and the commit message says six — three numbers for one set.
[j4-execution-plan.md](j4-execution-plan.md) line 269 says "§9.4 rule 3 is
already what the plan's **fourth** name pointed at" two lines above "**Two of the
plan's three names** are retired", where the parallel passage in the threat model
says *third*. And [mmu/hardware-spec.md](mmu/hardware-spec.md) line 1367 says
"**three** documents said it was not", where its own body names two. None of
these is load-bearing; all three are the arithmetic the registry's value guards
exist for, in sentences no fact covers, written by the commits that were fixing
the previous round of the same thing.

**I. One dangling pointer.** [fgmt/dual-fgmt-proposal.md](fgmt/dual-fgmt-proposal.md)
line 89, in the new §4.1 the prior-art sweep created, grounds a bullet on
"[cache/l2-spec.md §6.1](cache/l2-spec.md)". §6.1 of that document is
*Atomicity: CAS.L via L2-Line Lock → Motivation*; the MSI prior art it means is
§3.

### F2.4 The narrow inversion answer, measured

C3 answered F's rank-3 gap per-rule: register the clause carrying a rule's
polarity as its own fact, and `owner-has-fact` then requires it to stay there.
Two rows exist, `aic2.hostowned.polarity` and `hyp.bootstrap.polarity`.

**It works on the perturbation C3 ran.** I reproduced it: changing `A2-R1. Do
NOT deliver` to `A2-R1. Deliver to the guest` fails, loudly and by name.

**It does not survive the way this tree actually reverses a rule.** Every
document here retires a claim by quoting it as history and stating the opposite
beside it — it is the house style, and C3's own commits use it on every page. So
I retired `A2-R1` in that style:

I replaced the delivery branch with two comment lines quoting the pinned clause
as something [`A2-R1`](aic/aic2-spec.md) "previously read" and calling it retired
as over-strict, followed by the live `deliver via cpu_event_i_t to the running
thread` statement the rule forbids.

The pinned literal is still in the owner, so `owner-has-fact` is satisfied.
`--strict --check-waivers` exits **0**, and the delivery rule now performs the
cross-domain delivery `A2-R1` was created to forbid. The guard is defeated by the
idiom the project uses for every retirement.

**And the line it draws is an accident of authorship.** There are ~70 normative
rule identifiers in `docs/` — the [FP](fpu/spec.md), [G](simd/gpu/simd-gpu-spec.md),
[H](hypervisor/hardware-spec.md), [I](iommu/hardware-spec.md), [K](fpu/spec.md),
[P](cache/l2-spec.md), [SQ](sq/spec.md), [S](simd/spec.md),
[T](hypervisor/hardware-spec.md), [V](simd/spec.md), [W](mmu/hardware-spec.md)
and [A2](aic/aic2-spec.md) rule families. Two have a polarity
fact, and they are the two C3 wrote. **None of the four rules F named as the
demonstrated inversion cases has one.** I inverted [`I-R5`](iommu/hardware-spec.md)
— F's worst case, the one that inverted reads as the retired specification — in
both places it is stated, the §3.10 rule text and §4.3's lookup pseudocode, and
the gate exits **0**. The registry's stated justification for stopping at two —
"two rules whose polarity is the whole of their content" — is a description of
that [very rule](iommu/hardware-spec.md).

**The honest reading.** The polarity fact is worth keeping; it is cheap and it
catches deletion. It is not an answer to inversion, and the registry should say
so in those words rather than as a limit on "rules someone remembered to
register". Either the polarity of every rule that carries one is registered — and
the pattern is anchored so that a demotion to history does not satisfy it — or
the gap is named as rank 3 still open. What is not defensible is a two-row
sample presented as a design.

### F2.5 The new checks, checked against real historical instances

The project's bar is that a check must be demonstrated against a real historical
instance, not a fixture. I re-ran two of them myself rather than trusting the
suite.

- **`enumeration-row-count` catches.** Deleting row 5 — BMID `0xFF`, the
  permanent bypass — from [iommu/hardware-spec.md §3.10](iommu/hardware-spec.md),
  which is C2d's own disclosed pass on the row C2d called the reason the
  enumeration exists:
  `FAIL [enumeration-row-count] iommu.bypass.paths: … states 7 and its `# | Path`
  table has 6 row(s).`
- **`site-absence-claim` catches.** Restoring [aic2-spec.md
  §5.5](aic/aic2-spec.md)'s retired sentence, taken verbatim from `8f1832d^`:
  `FAIL [site-absence-claim] docs/aic/aic2-spec.md:567: restates the wording
  aic2.hostowned.masked retired ('masked at the AIC2 level') …`

Neither is vacuous. Both trees were restored; the gate is green.

**A new disclosed failure, not in the register: `site-absence-claim` is
blind across documents.** The claim is anchored on a (document, wording) pair. I
reasserted `aic2.hostowned.masked`'s retired wording — the same sentence,
verbatim from `8f1832d^` — in [hypervisor/design-spec.md §4.3](hypervisor/design-spec.md)
instead of in `aic2-spec.md`, and the gate exits **0**. **F §3.2 was precisely
the cross-document class** — "stale statements one task retired and another still
asserts" — so the check written in answer to F closes the same-document half of
what F found. That belongs in `## Absence claims`'s disclosure table.

**And the registry has drifted inside itself.**
[fact-ownership.md](fact-ownership.md) line 605 says "the three rows in that
table" and line 626 says "Three sites are registered". `## Absence claims` has
**nine**; C3's `13ccc46` added six and left the prose. That is the
counted-enumeration drift `enumeration-row-count` exists for, in the document
that defines `enumeration-row-count`, uncovered because no fact registers the
absence-claim count.

### F2.6 The bar audit

**Seven items, seven `NOT MET`, and that is still correct.** I re-verified the
four categorisations put to F:

- **L4's transmitters ship today.** `core/tlb_walk.vhd` is present at
  `jcore-cpu@origin/master`, and the I→D speculative shadow fill has its own
  install path (`shadow_wr`, `shadow_vpn`, `shadow_ptel`, `shadow_asid` in
  `core/cpu.vhd`). Unchanged.
- **L2's blocker is that the bus has no BMID field.** `cpu2j0_pkg.vhd`'s
  `cpu_data_o_t` is `{en, a, rd, wr, we, d}`. Unchanged and still the largest
  prerequisite in the programme.
- **L5's second reason is fixed in the design**, and its status row says so
  without claiming the item moved. Correct.
- **L6's gap is evidential, and is now *partly* checked** rather than wholly
  unchecked: the three closed sites carry absence claims, so a reopening in the
  closing document fails. It is still unchecked against the cross-document
  reassertion of §F2.5, and the count of open sites is still maintained by hand.

**Where the audit is now wrong: L1's status row is stale.** C3 added a TSB
victim-selector re-seed to gang-switch item 6, and
[hypervisor/hardware-spec.md §4.7.1a](hypervisor/hardware-spec.md) says of it
that "the scrub for this structure is a *re-seed*, it needs entropy, and hardware
has none". L1's row still enumerates items 7, 8 and 9 as the additions and does
not carry this. **C3's report that "no bar item moved" is true of the verdicts
and its report that "none of the five was gated on one" is not**: the gang-switch
list *is* L1's requirement, and the programme's own precedent is C1a's — "adding
the scrub without adding it to *that list* would have left L1 unmet". L1 has
acquired a list item that no hardware can perform and no document sources.

### F2.7 What is buildable now

F said "one and a half"; the post-F work said 0010 became a whole one. **0010
decision 4 is now *done*, not dispatchable**, so the count is not one and a half,
or one — it is **one, and it is not the one anybody was looking at**:

1. **Part of C2b — the delayed speculative translation install.** Still the only
   design-side item with shipping hardware to build against, and it is unchanged
   by everything since F.
2. **New, created by the merge:** `targets/asic/gf180_j4mmu` has no `jcore,cache`
   node, so the J4 ASIC target — the methodology vehicle — still has no cache
   maintenance. Either the device tree gains the node, or a document says the
   ASIC target is no-DMA-coherency and 0010's "Done" is scoped to the FPGA
   boards. This is small, real, and in front of the next implementer in the same
   way the [`P-R8`](cache/l2-spec.md) collision was.
3. **Documentation and checker work**, unchanged in kind from F §6 and now with a
   specific list: §F2.3's six falsified kernel sites, §F2.3 B and C, §F2.4's
   polarity decision, §F2.5's cross-document class and the registry's own
   nine-vs-three drift, and F's rank 6.

Everything else stands exactly as F left it: **six unscheduled hardware
programmes and one unscheduled evidence infrastructure.** Nothing in 25 commits
scheduled any of them, and nothing was expected to.

### F2.8 Unowned obligations

F's two are owned and I confirmed both rows in
[security/threat-model.md §11](security/threat-model.md). C3's own filings landed
and are actionable: guest `SR.IMASK` virtualization, and the three `aic2-spec.md`
§5 descriptions C3's remit did not cover, each with a named destination. Two new
ones are not filed anywhere:

1. **Where the hypervisor's gang-switch entropy comes from.** §4.7.1 item 6
   requires a re-seed at every ownership change; §4.7.1a says hardware has none
   and makes it the hypervisor's write; no document names a source, and
   [mmu/linux-spec.md](mmu/linux-spec.md)'s answer is a `late_initcall`, which is
   boot, not a gang switch.
2. **AIC2's dispatch-state input** — §F2.3 D. `A2-R1`'s predicate needs a signal
   or a register that no section provides. §11's C3 row names three unarbitrated
   injection mechanisms but not this.

### F2.9 Gates

| Gate | After Task F | After F2's session (`405c250`) |
|---|---|---|
| `python3 scripts/check-doc-facts.py --strict --check-waivers` | exit 0 | **exit 0** |
| `python3 scripts/check-doc-facts.py --list-checks` | 22 named checks | **23** |
| `python3 scripts/test-check-doc-facts.py` | 167 passed, 0 failed | **183 passed, 0 failed** |
| `python3 scripts/test-check-doc-facts.py --mutate-sweep` | 35 killed, 0 survived | **48 killed, 0 survived, 0 with a moved target** |

Registry, measured with the checker's own parser: **68** registered facts (F: 65),
**14** with a value guard, **31** with a code binding, **6** with an enumeration,
**9** absence claims, **28** waivers, **4** unresolved. **0** facts carry both a
value guard and a code binding; **23** carry none of the three.

### F2.10 What did not survive checking

Every task in this programme has reversed at least one thing it was told. This
one reverses six, and three of them are its own brief's.

1. **"F reviewed `main` at `eb62a37`."** It did not; that SHA is on no branch but
   `wave1/foundations` and is not an ancestor of F's commit. F's base was
   `b76c545`.
2. **"27 commits have landed since F."** Twenty-five.
3. **"163 registry rows."** That is every table row in the `## Registry`
   *section*, which contains the per-wave perturbation-disclosure tables as well
   as the registry. There are **68** registered facts. F reversed the identical
   conflation in its §8 item 3 — it was "151 rows" then — and the number came
   straight back in the next brief, which is a small demonstration of the same
   thing this programme is about.
4. **"C3 answered the inversion gap narrowly."** It answered a narrower thing
   than that: not "rules someone remembered to register" but "the two rules C3
   itself wrote", and the answer does not hold against a demotion to history.
   §F2.4.
5. **"L5's is unbuilt mechanism, L2's blocker is the missing BMID field, L4's
   transmitters ship, L6's gap is purely evidential."** All four still hold. The
   framing's omission is **L1**, whose row went stale in the last nine commits.
   §F2.6.
6. **"C3's five items were not gated on a bar item."** Four of the five were not.
   The TSBVSEED re-seed is an item on bar item L1's own normative list. §F2.6.

**And the thing that is genuinely good, said plainly because a review that only
finds fault is not a measurement.** The [`P-R8`](cache/l2-spec.md) ↔ 0010 resolution was correct, was
carried into code, and the code is better than the specification asked for — the
patch's own header reasons from the RTL's decode width, names the stride hazard
in `sh2/probe.c` that it deliberately does not touch, and states the write-through
property that licenses ignoring the region argument. C3's `A2-R1` found a real
cross-domain delivery that six waves of review had read past, killed a
vector-stride claim that had propagated into a decision in another document, and
did both by reading the RTL rather than the specification. The two collisions F
found are closed and were closed by deciding, not by annotating. **The failure
mode that remains is the one F named and this review confirms from a second
angle: the tree is excellent at recording what it decides and has no mechanism
that notices when the world it described changes.** The kernel merge is the first
time the world changed, and six documents went false in one commit with the gate
green.

---

## Part II — Task F, 2026-09-09 — the original review, unaltered

*What follows is Task F's report as it was written, plus the note the post-F task
added to it. Where F2 disagrees, F2 says so above; nothing below has been edited
to match.*

> **What happened next, 2026-09-10 — read this before acting on anything below.**
> A follow-up task acted on this review's blocking findings, and several
> statements here are now descriptions of a tree that no longer exists. They are
> left standing because a review is a dated report and rewriting one destroys the
> record of what was true when it was written; this note is the supersede marker.
> What changed:
>
> - **§3.1's two collisions are resolved**, and neither by annotation.
>   [`P-R8`](cache/l2-spec.md) now *requires* the per-core split and rejects the
>   P4 move, and [0010](decisions/0010-dma-coherence-is-software-maintained.md)
>   decision 4 carries the matching kernel constraint — so §6's "must not be
>   dispatched as written" is discharged. The L2 domain tag is
>   `HTCR.TENANT`, not `PDID`, so **§4's second reason for L5 being unmet is
>   fixed in the design** and survives only as a status note.
> - **§3.2's stale statements are retired**, and **§3.3's two ownerless
>   obligations have owners** — both are now rows in
>   [security/threat-model.md §11](security/threat-model.md)'s defect table,
>   which is the structural fix §3.3 asks for.
> - **§2.2 rank 5 is implemented**, not recommended: `site-absence-claim` and
>   `fact-ownership.md`'s `## Absence claims`. **Rank 6 is not**, and the reason
>   given here still holds.
> - **§5.1's gate figures are superseded**: 23 named checks, 183 fixture cases,
>   48 mutations killed with 0 survivors.
> - **§7's five prior-art sites are grounded or dropped.** Two figures this
>   review did not question turned out not to exist in the sources they are
>   attributed to; see [security/threat-model.md §9](security/threat-model.md).
>
> **And four of this review's own claims did not survive the follow-up's
> checking**, which is the same thing this review says about every task before
> it. *(a)* §3.1 and [security/threat-model.md §11](security/threat-model.md)
> said the [`0xabcd00c0`](cache/l2-spec.md) block is placed by `turtle_1v0/design.yaml`; **two**
> boards instantiate it, `mimas_v2` as well, and `turtle_1v0/board.dts` hands
> Linux the same two words twice. *(b)* §6's suggested resolution — split the
> cross-core fields per core — is right, but it is not a relayout of one block:
> bit 28 is the IPI `arch/sh/kernel/cpu/sh2/smp-j2.c` uses for **every** J-Core
> IPI, an IPI cannot be split per core, so the fix separates two facilities and
> acquires a second kernel dependency. *(c)* §7 called the speculative-taint
> mechanism "a naming violation and not a design hole"; the naming is worse than
> stated — the structure the name points at is claimed **in force** by AMD
> US10956157B1 — and better, because the owning specs had already refused it in
> writing. *(d)* §2.2 rank 5 proposed anchoring the absence claim "on the site's
> own noun rather than on the word `undefined`"; measured against
> [sq/spec.md](sq/spec.md), noun-anchoring fires on correct prose all through a
> document that legitimately narrates its own history, so the implemented check
> anchors on the retired **wording** instead. The shape was right; the anchor was
> not.

---

## 1. The verdict, for a reader who did not follow the programme

**The specifications are sound in substance and unusually honest in form. What
they are worth is a design record, not assurance.** Nothing in the programme has
been demonstrated on hardware, because for six of the eight Wave-3 subjects the
hardware does not exist; and the CI machinery that makes the documents feel
verified checks attribution and arithmetic, not meaning.

Three things a reader should take away.

1. **All seven security-bar items are NOT MET, and the programme says so.** That
   is the correct reading and it is stated plainly in
   [security/threat-model.md §8](security/threat-model.md). The Wave-3 designs did
   not move any item; they completed the *specification half* of six of them.
   What is missing is not argument, it is silicon and evidence.

2. **The registry provides materially less assurance than the programme has been
   assuming.** This is the single most important sentence in this review. The
   `## Value guards` section of [fact-ownership.md](fact-ownership.md) claims a
   defence in depth — that a wrong value has to be written into two independently
   maintained places before anything licenses it. Task F measured that defence on
   the real tree and it **held for none of the Wave-3 security counts.** Details
   and the fix are §2.

3. **Nobody had read the disclosures together, and reading them together changed
   two of their conclusions.** Every Wave-3 task perturbed its own registry facts
   and disclosed the perturbations that passed — about forty lines of honest
   self-reporting. Five of the six recurring escapes were filed as intrinsic
   limits of what a name fact or a value fact can do. Two of them were not: they
   were properties of how the checker happened to be written, they were closable
   in a few dozen lines, and they survived six waves because each task disclosed
   its own instance faithfully and no task read the other five. **A disclosure
   register is not a defect tracker.**

**What this programme is genuinely good at, stated because a review that only
finds fault is not a measurement.** The specifications record what they do *not*
close as carefully as what they do: [cache/l2-spec.md §16.3](cache/l2-spec.md) is
an explicit list of residual channels with a status per row;
[iommu/hardware-spec.md §3.10](iommu/hardware-spec.md) enumerates the paths that
reach memory unchecked rather than only the ones it closes; every Wave-3 row of
[j4-execution-plan.md](j4-execution-plan.md) records the ways the plan's own table
was wrong. Six of the eight Wave-3 tasks reversed something they were told, in
writing. That is rare and it is the reason this review could be written at all.

---

## 2. The honesty machinery, audited as a system

### 2.1 What the checker actually guards

`scripts/check-doc-facts.py` runs 22 named checks. *(23 as of 2026-09-10 — `site-absence-claim`, rank 5 below, implemented rather than recommended. Six bear on registered facts; the table's counts of guarded facts are unchanged, because an absence claim is keyed on a document and a retired wording rather than on a fact.)* Five bear on registered facts:

| Check | What it guarantees | What it cannot see |
|---|---|---|
| `owner-has-fact` | the owning document still contains a literal the registry pins | what the document *says* about it |
| `restatement-is-linked` | a non-owner mentioning it links the owner on that line | whether the restatement is true |
| `no-stale-value` | no document states a number for the fact other than the owner's | a rule whose number is right and whose meaning is inverted |
| `doc-matches-code` | one quoted value still matches one pattern in one file of one repo | that the value is the *mechanism*, or that the mechanism is correct |
| `context-image-sums` | a byte-layout table sums to the total it declares | anything not shaped like a byte layout |

Measured on this tree: **65 registered facts. 14 have a value guard. 30 have a
code binding. Twenty-one have neither — they are name facts, guarding only that a
token appears. Not one fact has both a value guard and a code binding.**

The sharper measurement is about the security rules specifically. Wave 3 landed
three code bindings, and **not one of them binds a rule.** They bind a driver
signal in `jcore-cpu:core/cpu.vhd`, a Makefile arm in `linux:arch/sh/mm/Makefile`,
and an MMIO base in `jcore-soc:targets/boards/turtle_1v0/design.yaml` — facts
*adjacent* to the mechanisms, chosen because they were the only things in the
neighbourhood that existed. Every normative security rule in this programme is
guarded by a name fact and nothing else.

### 2.2 The gaps, ranked by whether a security claim could go false with CI green

**Rank 1 — a counted enumeration truncated under an unchanged count. FIXED.**
Four waves perturbed *"delete a row, leave the count at N"* and four waves reported
**passes**. This is rank 1 because in every instance the enumeration *is* the
security argument, not an illustration of it: §4.7.1a's scope table is what makes
"the scrub is complete" mean something, [iommu/hardware-spec.md §3.10](iommu/hardware-spec.md)'s
path list is the claim that those are *all* the paths, and
[cache/l2-spec.md §16.3](cache/l2-spec.md) *is* the honesty list, so deleting a row
is precisely how an accepted channel becomes an undocumented one. C2d's own
perturbation deleted the row for BMID `0xFF` — the permanent bypass that is the
reason the enumeration exists — and reported OK. Closed by
`enumeration-row-count`; see §2.3.

**Rank 2 — the licensing pool. FIXED, and it was mis-diagnosed for six waves.**
Six consecutive tasks recorded a registry `Constant` cell edited to contradict its
own owner, passing every time, each explaining it as *"the cell is prose no check
reads"*. The cell was read. `check_no_stale_value` scanned every `Constant` cell in
the file into **one global pool**, and Task F measured that pool on the real tree:
**48 values, including every integer from 0 to 10.** Every Wave-3 security count is
in that range — four transmitters, four microreset classes, six GPU address
producers, seven IOMMU bypass paths, ten residual channels, ten gang-switch items,
zero open `undefined` sites. So the second-opinion defence held for the
three-digit context-image sizes it was built for and for nothing else. Two
disclosed escapes follow from it directly, including the one C2e called the honest
headline of its run — *"a count stated twice inside its own owner has no guard"* —
which C2e worked around by rewording a document rather than by fixing the check.

**Rank 3 — an inverted rule reads as compliance. NOT CLOSABLE. This is now the
top residual.** Four instances are on the record:
[mmu/hardware-spec.md §5.0a](mmu/hardware-spec.md)'s `W-R1`,
[hypervisor/hardware-spec.md §4.7.2](hypervisor/hardware-spec.md)'s `T-R2`,
[iommu/hardware-spec.md §3.10](iommu/hardware-spec.md)'s `I-R5`, and
[cache/l2-spec.md §16.2](cache/l2-spec.md)'s `P-R2`.
[`I-R5`](iommu/hardware-spec.md) is the worst: inverted,
it is *verbatim the retired specification*, so it does not merely read as
compliance — it reads as the original design.
[`T-R2`](hypervisor/hardware-spec.md) inverted still sits under a
bullet titled "refusal, not a trap", so a reviewer skimming headings sees
compliance twice. **No syntactic check separates "MUST scrub" from "need not
scrub" without firing on correct prose**, and this project's own bar is that a
check which fires on correct prose is switched off within a month. Recommending
one would be worse than naming the residual.

**Rank 4 — a rule narrowed with its token and its count intact. NOT CLOSABLE.**
Same family as rank 3 and harder to see, because the narrowed text is a plausible
clause rather than a negation. The live example is C2d's: scoping the reset-deny
to the on-chip DMA range leaves BMIDs `0x80`–`0xEF`, the guest pass-through range
of [bus/fabric-spec.md §4.4](bus/fabric-spec.md), bypassing at reset — while the
prose still reads as default-deny.

**Rank 5 — two registered facts contradicting each other. CLOSABLE, RECOMMENDED,
AND CURRENTLY OWNERLESS.** [cache/l2-spec.md §16.2](cache/l2-spec.md)'s `P-R7`
inverted restores an "undefined" for a tenant-visible remainder while the bar
item's count of open sites still reads zero; nothing relates them, so both are
licensed simultaneously and the count is an assertion by whoever last edited it.
The check that would catch it is a **site-anchored absence claim** — for each
closed site, a pattern that must not reappear in the document that closed it — and
it is tight enough to meet the "does not fire on correct prose" bar because it is
anchored on the site's own noun rather than on the word `undefined`. That check is
already owed: [sq/spec.md §6.5](sq/spec.md) filed it with Wave-1 task **B0c**, and
B0c closed on 2026-08-25. **The obligation was filed against a task that had
already finished, and no open row anywhere schedules it.** C1b and C2e each
declined it in turn. I recommend rather than implement because designing the
per-site patterns requires deciding what each closed site's canonical wording is,
which is the owning specs' call and not a reviewer's.

**Rank 6 — a hex fact drifting in any non-owning document. CLOSABLE,
RECOMMENDED.** `check_no_stale_value` builds its licensing set with a
decimal-only scan, so a hex fact can never carry a value guard and is guarded by
its code binding alone — which checks the *owner* against the code and says nothing
about restatements. C2e disclosed this and named four more facts in the same
position. The fix is to extract hex literals as well as decimal ones and add the
guard rows. It is small; it is rank 6 because the consequence is a misrouted
document rather than a false security claim, and because the one hex fact with
real security weight already has a code binding.

### 2.3 What I changed, and how it was demonstrated

Both changes meet this project's bar: each was demonstrated against a *real
historical instance* from the disclosure register, each ships fixtures, and each
ships mutation entries.

**`enumeration-row-count`** (new check, new `## Enumerations` registry table).
A fact that states how many things there are must agree with the table that lists
them. Located by column header rather than section heading, for the reason
`find_tables_by_header` already gives. Requires exactly one matching table: zero
is the `simd/spec.md` failure `## Image layouts` was built for, and two or more is
worse, because the check would silently guard whichever came first.

Demonstrated by deleting one row from each of the six registered enumerations
against a committed tree, asserting a non-empty `git diff` first (C2b's rule):
**all six caught**, including C2d's BMID `0xFF` row and C2e's residual-channel row.
It also catches, without being aimed at them, C1b's two disclosed silent positions
for the gang-switch list — a row inserted before the anchor without renumbering,
and a row appended after it — which C2c confirmed were still silent.

**Per-owner, bold-scoped licensing** (rewrite inside `no-stale-value`). The
licensing set is now the bolded numbers in the `Constant` cells of facts owned by
the *same document*: 48 values down to between one and seven per fact. Bold,
because `registry-value-is-short` caps the cell at 100 characters precisely so the
tail is explanation — `cache.l2.residuals`'s cell reads a count followed by a
breakdown, and reading the tail made the breakdown's numbers statements of the
fact. Scoped by owning document rather than by fact, because a J32 and a J64 form
are legitimately two rows of one owner and per-fact scoping fails a correct tree.

This closes five of the six disclosed `Constant`-cell instances — every one whose
fact carries a value guard. C1c's is a **name** fact and is not closed and cannot
be: a name fact carries no value, so there is nothing to compare the cell against.

**A third fix, in the test harness rather than the checker.**
`scripts/test-check-doc-facts.py` attributes each failure to the assertion that
caught it, and its own comment explains that the attribution is computed rather
than eyeballed *because* a previous version credited `expect_check` with catches
that exit status had made on its own — "how a 6-of-11 figure got reported when the
honest number was 1". That guard was written for `expect_check` and the two
neighbouring assertions inherited the bug it was written about. Running the new
suite against the previous checker as a control, thirteen cases were labelled
*"exit status and check agreed"* when the control had in fact exited 0 on every
one of them, and `expect_text` was credited with eleven catches it did not make.
Fixed; the same control run now reports twelve caught by exit status and one by
`expect_text`, which is the honest split.

**Residual I am declaring rather than hiding.** Two facts owned by the same
document still license each other's values. `enumeration-row-count` counts rows
and does not read them, so a row *replaced* by a different row keeps the count and
passes. Neither is narrowed here, and both are recorded in
[fact-ownership.md](fact-ownership.md).

---

## 3. Cross-task consistency

Each task verified its own claims; nobody had checked the tasks against each
other. Two findings below would leave a security claim false after the hardware is
built, which is a different and more serious category than the rest.

### 3.1 The two that block a security claim

**C2e sites the whole L2 partition on an identifier C2c argued at length cannot
carry a security control on the default path.** [cache/l2-spec.md §16.1](cache/l2-spec.md)
and [hypervisor/design-spec.md §6.2](hypervisor/design-spec.md) both make the L2
domain tag the same `PDID` the CPU specs use for predictor tagging, and §6.2
presents the reuse as a virtue — one identifier, three consumers.
[hypervisor/hardware-spec.md §4.7.2](hypervisor/hardware-spec.md) rejects exactly
that: `PDID` is optional, required only on implementations that speculate,
explicitly *not* required on the in-order cores — so a check built on it "would be
absent on exactly the microarchitecture [decisions/0009](decisions/0009-in-order-fgmt-is-the-default-path.md)
makes the default path". C2c went so far as to allocate a new, mandatory register
rather than reuse `PDID`. C2e did not get the memo. On the default in-order part
the way-mask has no index and the L2 isolation rules are inert — while
[hypervisor/hardware-spec.md §4.7](hypervisor/hardware-spec.md) asserts that
channel is closed by way-partitioning, "required in the baseline dual-core
configuration". **C2c is correct.** Bar item L5 is unmet for a second, independent
reason that its own status line does not carry.

Three supporting defects fall out of the same sentence, all in
[cache/l2-spec.md](cache/l2-spec.md): the L1↔L2 message types carry a core and
thread identity and no domain field, and do not traverse the fabric at all, so
"carried on the fabric alongside the existing owner field" is wrong in both nouns;
the elaboration constraint in §16.2 is written over two generic names that appear
nowhere in §4's configuration-parameter table, which lists a differently-named
miss-capacity generic and no domain count at all; and the two hyperprivileged
registers the partition needs appear in no register map in the document.

**Decision [0010](decisions/0010-dma-coherence-is-software-maintained.md) tells
the kernel to build its DMA maintenance on the exact register
[cache/l2-spec.md §16.2](cache/l2-spec.md)'s `P-R8` says must become
hyperprivileged.** 0010's fourth decision asks for real cache-maintenance
primitives written against the J-Core CCR that `cache-j2.c` already reaches
through its per-core base pointer. That routine walks word offsets across cores —
which is the cross-core write [`P-R8`](cache/l2-spec.md) forbids, and the same register
[cache/l2-spec.md §16.2](cache/l2-spec.md) says the SoC ships today on the wrong
side of its own rule. Implemented as written, 0010 makes a guest kernel's routine
DMA path depend on issuing whole-cache invalidates of every other core.
[security/threat-model.md §11](security/threat-model.md) carries both rows and
neither mentions the other. **This matters more than the other doc defects because
0010's fix is one of only two dispatchable pieces of work in the programme
(§6)** — so the collision is not hypothetical, it is in front of the next
implementer.

### 3.2 Stale statements one task retired and another still asserts

- **The GPU spec asserts the pre-C2d IOMMU reset state as current fact.**
  [simd/gpu/simd-gpu-spec.md §16.3](simd/gpu/simd-gpu-spec.md) says the IOMMU
  resets with every master bypassing and the block disabled, and concludes that
  routing GPU traffic through it "buys nothing until C2d changes that". C2d did
  change it: [iommu/hardware-spec.md §8](iommu/hardware-spec.md) now says out of
  reset the IOMMU is active and every master is denied. The conclusion drawn from
  the stale premise is load-bearing for the GPU section's ordering constraint. It
  is the last live citation of the retired values in the tree.
- **[bus/fabric-spec.md §3.2](bus/fabric-spec.md) still specifies the miss
  behaviour C2d retired** — the formulation
  [iommu/security-review.md](iommu/security-review.md) rates critical-adjacent
  because, read literally, it stalls the master forever — and its own headline
  about CPU traffic contradicts its body and the IOMMU spec's conformance rule.
  This is the document an SoC integrator reads first, and the GPU spec quotes this
  very sentence as authority.
- **[bus/fabric-spec.md §4.4 and §4.5](bus/fabric-spec.md)** still describe the
  reserved untagged identifier as a boot-DMA bypass in a normative allocation
  table, immediately below the prose C2d rewrote to say no such window exists.
- **The IOTLB descriptor's cacheable bit** still promises in its one-line field
  description the snooping that the same document's §7 and 0010 both withdrew.
  That line is what an RTL engineer implements from.
- **[simd/gpu/simd-gpu-spec.md §16.3](simd/gpu/simd-gpu-spec.md) contradicts
  itself about whether a shader multiprocessor counts as a core for bar item L1.**
  The answer C2c gave is recorded at the top of the section; forty-nine lines
  below, the rule still says the question is undecided and defers it to whoever
  owns L1. The practical conclusion is the same either way, so this is a stale
  status rather than a substantive split — but it is exactly the "the reader
  arrives at the rule and not at the answer" failure the conventions exist to
  prevent.
- **The gang-switch checklist's ordering paragraph and the FPU rule disagree about
  who performs the ownership write and when** — the checklist's own note makes it
  a side effect of the restore, the FPU rule makes it release bookkeeping on the
  outgoing side. The dangerous reading is the checklist's, because "as part of the
  restore" invites an implementer to skip it for a context with nothing to
  restore, which is the no-image branch bar item L3 names as a required test case.
- **Bar item L5's requirement line still demands the mechanism C2e deliberately
  refused.** The requirement asks for isolated hits; [cache/l2-spec.md §16.1](cache/l2-spec.md)
  keeps hits unrestricted by design and §16.3 marks the resulting channel accepted,
  with the trade recorded honestly elsewhere in the same document. A reader
  checking the item against its own stated wording will score it failed for the
  wrong reason.

**A clean bill where I looked and found none.** C1b's scrub rules and C2c's
microreset scope do not overlap, do not assume each other, and fence themselves
off explicitly. C2b's delay-on-miss, C2e's L2 miss-handling reservation and C2c's
core-side scrub address three distinct structures and draw the same two-pool
distinction in the same words. C2d and 0010 tell one story about who owns
coherence. C1c and C1b compose correctly.

### 3.3 Handoffs: made, and actually received?

Four were named to me. Two are clean, one is clean in substance with a stale
sentence, and **one rests on a premise the documents refute.**

| Handoff | Verdict |
|---|---|
| C1a → C1b and C2e, two "undefined" behaviours | **Received and answered**, at the receiving rule *and* at the original site, with the source document's bookkeeping updated in both directions. The best-executed handoff in the programme. |
| C2a → C2c, is a shader multiprocessor "a core" for L1? | **Received and answered** at length, with the ratio, both costs, and the answer written back into C2a's own document and the glossary — but see §3.2: the question is still posed as open in the rule below the answer. |
| C2b → C2e, the pLRU channel | **The premise is false.** C2b did not hand it over; it explicitly refused to, and [security/threat-model.md §7.3](security/threat-model.md) says the two things sharing the word "pLRU" "share a word and not a mechanism". The L2 half was already C2e's by prior bar-item assignment and *is* answered. The speculative half was routed to [decisions/0009](decisions/0009-in-order-fgmt-is-the-default-path.md), which contains no mention of it — an unreceived pointer, mitigated by the channel having a proper home as a named accepted residual. |
| C2c → bar item L5, the L2 miss-handling pool | **Received and answered**, with the return pointer written back and a test that names the right structure. Fully closed loop. |

**Two obligations are genuinely unowned, and both were filed against destinations
that cannot act on them:**

1. **The grep-level `undefined` CI guard**, filed by [sq/spec.md §6.5](sq/spec.md)
   with Wave-1 task **B0c** — which closed on 2026-08-25, six weeks before the
   filing. Declined again by C1b and by C2e. It is absent from the checker; I
   confirmed this. This is rank 5 of §2.2.
2. **The GPU's bus master identifier allocation**, filed by
   [simd/gpu/simd-gpu-spec.md §16.3](simd/gpu/simd-gpu-spec.md) with
   [bus/fabric-spec.md](bus/fabric-spec.md), which contains no occurrence of "GPU"
   at all and whose allocation table and worked example have no GPU row. The
   filing document itself says no task schedules it, and it is a precondition of
   the clause above it.

Neither is carried in [security/threat-model.md §11](security/threat-model.md)'s
defect table, which is where an unowned obligation is supposed to live. **Both are
visible only from inside the document that filed them** — which is the same
structural failure as the disclosure register in §2: honest local reporting, no
global reader.

---

## 4. The bar-status audit

Seven items, seven **NOT MET**, and the framing that they fall into different
categories is **accurate as far as it goes**. I verified each of the four claims
put to me:

- **L4's transmitters exist today.** Verified against `jcore-cpu@origin/master`:
  `core/tlb_walk.vhd` is a real instantiated entity, and the speculative
  instruction-to-data shadow fill has its own dedicated install port with
  documented victim-selection demotion. L4 is the only item whose subject is
  shipping hardware.
- **L6's gap is purely evidential.** Correct as the table states it.
- **L5's is unbuilt mechanism.** Correct — there is no L2 in either repository.
- **L2's blocker is that the bus has no field for a master identifier.** Verified,
  and it is *stronger* than stated: the entire master-to-slave data record is six
  fields and the response two, with no master identifier, **no transaction
  identifier, and no error field**. Masters are distinguished purely by port
  position. `bus/fabric-spec.md` §4 and §5 describe an allocation table and a
  global ordering key over fields with no representation in any record in either
  repository.

**Where the categorisation is incomplete.** Three items are not covered by those
four categories, and one of the four is wrong by omission:

- **L5 has a second, independent reason to be unmet that its status line does not
  carry**: the carrier defect of §3.1. "Unbuilt mechanism" implies that building
  the L2 would move it. On the default in-order part it would not.
- **L6's "purely evidential" is true of the count and unverified for the count.**
  The number of open sites is maintained by hand, no check relates it to the specs
  it summarises, and C2e demonstrated that a spec can reassert an "undefined"
  while the count still reads zero. So L6's gap is evidential, and the claim that
  it is *only* evidential is itself unchecked.
- **L7 is a fifth category** and belongs in the list: its mechanism is already
  merged and nothing virtualizes it. That is neither "exists today, needs RTL" nor
  "specified, unbuilt".
- **L1 and L3** are the plain "specified, unbuilt" category, with L1 carrying the
  extra condition that its detector needs a second thread context to be
  meaningful — which is why its experiment's kill criterion is that a
  single-context model must report *not runnable* rather than passing vacuously.
  That is the right shape and the only place in the programme where a vacuous pass
  was designed out in advance.

**One judgement about the whole bar.** The threat model's closing line — that
seven of seven is not a crisis, because none of the speculative hardware exists,
the exposure is latent, and this is the cheapest moment to fix it — is correct and
I would not soften it. But it is only correct while the hardware does not exist,
and the programme contains no task that builds any of it (§6). The statement is a
description of the present, not a plan, and it should not be read as one.

---

## 5. Gates, and code evidence

### 5.1 The gates, run and confirmed

| Gate | Before Task F | After Task F |
|---|---|---|
| `python3 scripts/check-doc-facts.py --strict --check-waivers` | exit 0 | exit 0 |
| `python3 scripts/test-check-doc-facts.py` | 153 passed, 0 failed | 167 passed, 0 failed |
| `python3 scripts/test-check-doc-facts.py --mutate-sweep` | 27 killed, 0 survived | 35 killed, 0 survived |

The fourteen added cases were each run against the previous checker as a control:
all fourteen fail there, twelve because it exits 0 on a tree it should reject.

### 5.2 Code evidence

All code claims below are from remote refs, never a checked-out submodule pointer,
per [decisions/0002 §2](decisions/0002-supersede-convention.md):
`jcore-cpu@origin/master` `e8a5a4e1`, `jcore-soc@origin/master` `7869a729`,
`binutils-gdb@origin/master` `bda8f339`, `linux@origin/jcore` `128e8958`.

The high-consequence "the hardware does not exist" claims the Wave-3 designs rest
on all hold. No store queue, no region decode, no store-queue control registers.
No FPU, no SIMD unit, no floating-point status register in any RTL file. No
hypervisor state anywhere under `arch/sh`. No branch target buffer, no branch
predictor, no return-address stack, no replacement-metadata tree, no
miss-status-holding registers, no L2. No IOMMU, no address-translation cache, no
master identifier. No DMA master: the DMA component is a README and one type
package with no entity, and every board ties the DMA port to a constant.

Three claims are over- or under-stated and are worth correcting in place:

- **C1a's "no SH-4 `PREF`" is too strong.** A `PREF @Rn` instruction exists in the
  J2A decoder overlay at the SH-4 encoding, as an architectural no-op with nothing
  behind it. The J4 build uses a different overlay, which has none. The sentence
  should read "no `PREF`-to-store-queue semantics, and no `PREF` in the J4
  decoder"; the conclusion C1a draws is unaffected.
  > *Applied 2026-09-10 at the three sites carrying the bare form, with one
  > correction to this bullet.* `jcore-cpu@origin/master:decode/gen-go/spec/sh2a/misc.toml`
  > declares the instruction with `table_ref = "SH-2A"`, not SH-4 — the two
  > architectures share the sixteen bits `0000 nnnn 1000 0011`, so "at the SH-4
  > encoding" points at the right opcode by a description that invites the exact
  > confusion the sentence exists to prevent. [sq/spec.md §1](sq/spec.md) already
  > carried the precise form ("the only `PREF` … is the SH-2A hint form,
  > implemented as a nop") and needed no change; it was the four other sites that
  > had the bare claim.
- **C2d's "the per-device block state already existed on both sides of the
  interface" reads as hardware-and-kernel and is not.** *(Applied to the worklist
  cell 2026-09-10.)* The kernel side is real
  generic IOMMU code. The hardware side is a specification document; there is no
  IOMMU in either RTL repository. The execution plan's own prose paragraph is
  accurate; it is the worklist table cell that compresses it into a claim a reader
  will take as RTL.
- **C1c's correction to C1b is right and under-stated.** *(Both halves verified
  and applied 2026-09-10.)* Six macros collapse to
  nothing under the disabled configuration, not five; and the residual body of the
  wrappers it defends is live rather than a bare preempt pair on any kernel that
  enables FPU emulation — which is user-selectable precisely on this target,
  because it depends on the FPU being absent.

---

## 6. What is actually buildable

**Dispatchable today, in the whole programme: two things, one of which has a
blocking conflict.**

1. **Decision [0010](decisions/0010-dma-coherence-is-software-maintained.md)'s
   cache-operations fix**, in `linux`. Verified: no cache-operations file is
   compiled for a J4 kernel, and all three region-flush hooks stay at the no-op.
   This is the one live correctness bug in the programme with an existing tree to
   fix it in. **It must not be dispatched as written** — see §3.1. Resolve the
   [`P-R8`](cache/l2-spec.md) collision first; the likely resolution is its own second option,
   splitting the cross-core fields per core so a per-core control can stay
   guest-reachable, and that needs saying in one of the two documents before an
   implementer reads either alone.
2. **Part of C2b** — the delayed speculative translation install, against the
   shadow fill and dedicated speculative install port that ship today. The other
   three named mechanisms target structures no repository contains.

**Not dispatchable, and why each is a different kind of not-dispatchable:**

| Row | Blocked on | Kind |
|---|---|---|
| C1a | a store-queue task **that exists in no wave** | the artifact to modify does not exist |
| C1b (`jcore-cpu`) | an FPU existing | same |
| C1b (`linux`) | a kernel configuration symbol that cannot be selected | the code exists and is compiled out |
| C1c (`linux`) | the same, plus: the discipline the row asks for is already there and already correct | nothing to add |
| C2a | a GPU program in no wave and no phase | no programme, not just no task |
| C2c | FGMT and a hypervisor existing | same as C1a |
| C2d | the bus having no master-identifier field at all | a change to every master and slave record in two repositories |
| C2e | an L2 existing | same as C1a |

**Newly identified as dispatchable and on nobody's list.** All of the following are
pure documentation or checker work, need no hardware, and are the cheapest
remaining value in the programme:

3. Every doc defect in §3.1 and §3.2 — eight edits, two of which (the carrier and
   the [`P-R8`](cache/l2-spec.md) collision) change what an implementer would build.
4. The prior-art re-grounding sweep of §7.
5. The `undefined` absence guard of §2.2 rank 5, and the hex licensing extension of
   rank 6, both now with an owner problem to solve first.

### What the programme needs next to convert specifications into met bar items

**The plan's design-then-implement pairing is structurally wrong for Wave 3, and
the evidence is that seven of eight implement halves failed the same way.** They
are not blocked on a *scrub* task; they are blocked on a *builder* task. C1a
discovered this and recorded it precisely — its implementer "is not an implementer
for C1a, it is the store-queue task, and it does not exist in this plan" — and
C1b found the same in both its repositories. **The plan never generalised the
finding it recorded twice.** The correct shape is that each Wave-3 rule set is an
*entry condition* on whichever task first builds its structure, and the Wave-3
deliverable was never an implementation: it was a set of conditions attached to
six hardware programmes that have not been scheduled.

Those six are: a store queue; a Tier-1 FPU and SIMD unit; an L2; a master-identifier-carrying
fabric plus an IOMMU plus at least one real DMA master; FGMT plus a hypervisor;
and a GPU. **The plan schedules none of them.** Until one is scheduled, no bar item
except L4 can move, and L4 can move only as far as RTL against shipping hardware
plus the evidence to go with it.

The second thing needed is **evidence infrastructure, which is separable from the
hardware and is not scheduled either.** Every Wave-3 design ships named
experiments whose kill criteria are correctly written — a harness with no way to
exercise the scenario must report *partial* or *not runnable* rather than pass.
Not one can be run. But the *harness* for several could be built against a model
rather than silicon, and building it now is what would stop the specification-half
completions of Wave 3 from silently becoming the whole story.

---

## 7. Prior art: the pre-2006 rule is violated as a class, not twice

[glossary.md §2](glossary.md) makes pre-2006 prior art a hard requirement for
every mechanism the project adds, with 2006 itself as the cutoff. Two mechanisms
had to be re-grounded mid-programme, and both took the same shape: name the work,
date it, state that it cannot be the authority, then rename and re-ground or
re-derive. That template is good and it is applied properly in both places.

**It is a class.** Sweeping the whole of `docs/`, the specification layer is clean
— each spec carries a dated prior-art table, several with an explicit closing
guard. Around forty post-2006 names are cited purely as *threats* or *evidence*,
which the rule permits and which the project states the boundary for itself. The
violations are concentrated in the two plan documents and one unswept proposal:

1. **The speculative-taint mechanism named in C2b's four is the most load-bearing
   instance**, because it is a mechanism of a launch-bar item and it is named in
   five documents with no dating and no antecedent — the exact defect the two
   re-groundings were written to fix, applied to the neighbouring bullet and not
   to this one. Mitigating: the underlying rule *is* grounded and the owning specs
   actively disavow the named scheme's shape, so this is a naming violation and
   not a design hole. Fixing it is a paragraph.
2. **The tenant-tagged predictor shape** is attributed to a 2018 vendor feature and
   its performance figure sourced to it, marked "not verified" but never marked
   post-cutoff. The mechanism itself is grounded to 1991/1998/2005 parts.
3. **The dynamic cache-sizing scheme** recommended for adoption is MICRO **2006** —
   on the wrong side of the rule's own explicit "2006 itself is the cutoff"
   clause — and it sits two lines below the entry that was re-grounded, untouched.
4. **The bandwidth-throttling scheme** named as the adopted shape for the L5
   requirement is 2013. The rule that was actually written is grounded to a 1995
   antecedent; nothing says the name is not.
5. **[fgmt/dual-fgmt-proposal.md §4](fgmt/dual-fgmt-proposal.md) is the only
   prior-art section in the tree not qualified "(pre-2006)"**, in a document that
   states it is not superseded and is cited normatively by three others. It
   contains six ungrounded post-2006 entries, **including a patent granted in 2023
   cited as "useful prior art"** — against the rule's explicit requirement of
   expired patents with priority dates no later than 2005, and against the
   companion rule that exists precisely to catch live claims. The same document
   applies the correct treatment twice elsewhere, so the rule was understood here
   and §4 was simply never swept.

**One name that is *not* a violation, checked because it looks like the worst
one.** Per-tenant kernel same-page merging is a 2009 Linux feature and it is
handled correctly and thoroughly: the specs establish that there is nothing to
adopt, because the feature has no per-tenant axis in the kernel source at all, so
the deliverable is a policy rather than a mechanism. The rule binds technology
*added*; turning an existing feature off adds none.

**One wording defect worth fixing because a contributor will copy it.** One row of
[simd/spec.md](simd/spec.md)'s comparison table describes a March 2006 instruction
set as "within cutoff", which is the opposite of what the rule says. The row is
harmless because its second clause supplies independent 1996 and 2002 prior art,
but the parenthetical states the policy wrongly.

**Scope, which no document states.** The rule's stated rationale is patent freedom
for the CPU and SoC intellectual property. The hosting and tooling stack named in
the service plan and glossary is entirely post-2006 and entirely ungrounded, and
is presumably out of scope — but nothing says so, so every future audit will
re-raise it. One sentence in §2 would close it permanently.

---

## 8. What in the brief did not survive checking

Every task in this programme reversed at least one thing it was told. This one
reverses six.

1. **"C2b assigned the pLRU channel to C2e."** It did not. C2b explicitly refused
   to file the two together, and said so, on the grounds that filing them together
   would have handed C2e's work to C2b. §3.3.
2. **"The registry `Constant` cell has passed unread for six consecutive waves."**
   It was never unread. It was read into a global pool wide enough to license any
   single-digit number. The symptom matched "unread"; the cause did not, and the
   difference is exactly what made it a fifteen-line fix rather than a new check.
   §2.2 rank 2.
3. **"151 registry rows."** Sixty-five registered facts. One hundred and fifty
   rows across all six tables of `fact-ownership.md`, which is presumably the
   source of the number, but only 65 of them are facts and only 44 of those are
   guarded by anything beyond a token match.
4. **"42 checks."** Twenty-one named checks before this task, twenty-two after.
   Forty-two is the line count of `--list-checks`, which prints two lines per
   check.
5. **"Two things are dispatchable."** One and a half. C2b's part is dispatchable
   as stated; 0010's cacheops fix is dispatchable but collides with
   [`P-R8`](cache/l2-spec.md), and
   dispatching it as written would harden a violation of a rule the same programme
   wrote. §3.1, §6.
6. **The framing of the six disclosure gaps as a list of equally-standing
   curiosities.** Two are implementation accidents and are now closed; two are
   irreducible and always were; one is closable and ownerless; one is closable and
   minor. Treating them as one class is what let two fixable ones survive six
   waves.

**And one thing in the brief that survived exactly as stated, worth saying because
it was the most important instruction:** a rubber stamp here would have been worse
than no review. The document set is honest enough that its own disclosures
contained the evidence for the two most serious findings in this review. What it
lacked was a reader.
