# J-Core multi-tenant threat model, and the minimum security bar for launch

**Status:** Accepted 2026-08-25. Wave-1 task **C0**, from
[j4-remediation-plan.md §C0](../j4-remediation-plan.md). This document
supersedes [mmu/security-review.md §0–§1](../mmu/security-review.md) and
[mmu/design-spec.md §6.0](../mmu/design-spec.md), which are the two places the
project's threat model was previously written down.

**C0 gates all of Wave 3.** Every Track-C remediation item is argued against
this document, and §8's bar is the pass mark.

**What this document owns and does not own.** It owns the *adversary*, the
*TCB*, the *sharing model*, the *applicability verdicts*, and the *launch bar*.
It owns **no normative constant** — per
[decisions/0001](../decisions/0001-one-authority-per-fact.md) every value quoted
here links its owner on the same line, and
[fact-ownership.md](../fact-ownership.md) gains no rows from this task.

---

## 0. The three corrections this document exists to make

Stated first, because each is a case of a conclusion that outlived its
reasoning, and that is the failure mode this whole remediation wave is about.

1. **The walker is not software.** The previous review's §0 opened with the
   claim that translation is "a software handler + TLB". A TLB miss has been a
   hardware FSM stall since
   **RESOLVED 2026-08-25 — jcore-cpu@master: "rtl(mmu): the hardware walker is the sole TLB installer".**
   Software reaches the miss vector only when the hardware walk fails
   ([mmu/hardware-spec.md §5.0](../mmu/hardware-spec.md)).

2. **The adversary is not a user process.** [mmu/design-spec.md §6.0](../mmu/design-spec.md)
   names the adversary as "an unprivileged tenant (`SR.MD=0`)" and the TCB as
   "the privileged kernel". On the product that is the wrong boundary by one
   whole privilege level: the tenant *is* a kernel.

3. **"Does not apply" was inherited across cores.** The transient-execution
   family was rated `NO` "whole family" because *the J4 RTL* is in-order. The
   product is not that core. The same inheritance is still live in
   `jcore-cpu/docs/architecture/tlb.md §7` — see §11.

---

## 1. The adversary

**The adversary is a guest kernel**, running at `SR.MD = 1` / `SR.HPRIV = 0`,
on a core it shares — over time, and across its own thread contexts — with
other tenants of a public multi-tenant service
([jcore-ulx3s-service-plan.md](../jcore-ulx3s-service-plan.md): tenants are
GitHub-authenticated strangers, admitted without vetting).

This is a strictly stronger adversary than "an unprivileged tenant", and the
difference is not rhetorical. Capabilities a guest kernel has that a user
process does not:

| Capability | Where it comes from | Why it matters |
|---|---|---|
| Writes `ASIDR` natively, **untrapped** | [hypervisor/design-spec.md §5](../hypervisor/design-spec.md) — but **its justification has expired**, see below | The guest chooses the context tag every TLB compare and every TSB index-hash uses. That is fine architecturally (it only reaches its own TSB) and *not* fine microarchitecturally — it is direct control of a structure index |
| Chooses its own virtual addresses and page sizes, and can fault at will | It runs its own MMU (Configuration A, [hypervisor/hardware-spec.md §4.4.5](../hypervisor/hardware-spec.md)) | Every eviction-set construction primitive in the literature assumes far less |
| Executes privileged SH-4 instructions that reach the memory system directly | `ocbi`/`ocbp`/`ocbwb`/`pref`/`movca.l` are **user-mode** instructions on this design ([cache/l2-spec.md §17.5](../cache/l2-spec.md)) | A guest kernel needs no privilege escalation to reach them; neither does its own user-space |
| Runs continuously for a whole scheduling quantum on a core it owns | [hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md) budgets a ~10 ms quantum | Attacks that need 10⁶ noise-free samples get them |
| Uses all thread contexts of its core simultaneously | [hypervisor/hardware-spec.md §4.7](../hypervisor/hardware-spec.md): a core hosts one guest with up to *N* vCPUs | An attacker with two contexts on one core can run a *concurrent* probe against its own victim thread — and, if the tenancy rule is ever violated, against someone else's |
| Reads hardware counters | walk counters, PMU | [hypervisor/design-spec.md §6](../hypervisor/design-spec.md) already records that the walker counters "simply state the answer, at one load, with no timing apparatus and no noise" |

**One authority in that table is cited for a conclusion it no longer supports**,
and it is flagged here rather than relied on quietly — it is the same shape as
the AnC row this document exists to fix.
[hypervisor/design-spec.md §5](../hypervisor/design-spec.md) permits the guest's
untrapped `ASIDR` write on the ground that `PTEH`, `PTEL` and `ASIDR` "are
write-only staging state that hardware consults **only** at `LDTLB` time, so
letting a guest load them natively leaks nothing." **Hardware no longer consults
`ASIDR` only at `LDTLB` time.** `LDTLB` is retired from the guest refill path,
and `core/cpu.vhd` wires `dp_mmu_regs.asidr` straight into the walker, which
consumes it on **every TLB miss** — as a tag *and*, since Phase 2, as an input to
the set index ([mmu/hardware-spec.md §2.8](../mmu/hardware-spec.md)). The same §5
table still prices the guest miss path as "`LDTLB` … traps … **yes — 1**" for an
instruction that no longer decodes there.

The *conclusion* this document draws is unaffected and is if anything
strengthened: the capability is real and it is now continuous rather than
per-refill. What is void is the reason the hypervisor spec gives for tolerating
it, and a Wave-3 reviewer must not read that spec's "leaks nothing" as a
current finding. §11 carries the row.

**The adversary is assumed to know everything.** J-Core is open source: the TSB
index hash, the predictor index functions, the pLRU tree, the victim-LFSR
construction and the RTL are all public. No mechanism in this document is
credited with security it derives from obscurity —
[mmu/hardware-spec.md §2.8a](../mmu/hardware-spec.md) already states this rule
for the ASID fold and it is generalised here.

**What the adversary is not.** No physical access (no probing, glitching, power
or EM analysis, no cold boot). No control of the hypervisor, the bitstream, the
boot ROM, or the fabric. No ability to co-schedule itself against a chosen
victim beyond what the service's placement policy allows — but it *may* assume
it eventually shares a board, an L2, and a core-over-time with any other tenant.

**Second-tier adversaries, in scope but subordinate.** (a) A guest *user*
process attacking its own guest kernel — the classic AnC/ASLR setting, and the
one §7.1 turns on. (b) A tenant-controlled DMA-capable device, if the service
ever offers device passthrough (§8, item **L2**). (c) A GPU shader, once the
GPU exists — a launch blocker in its own right
([j4-remediation-plan.md §C2](../j4-remediation-plan.md)). **Specified, unbuilt
since 2026-09-09:** the isolation mechanism is now stated
Wave-3 **C2a**), covering
**6** address producers ([simd/gpu/simd-gpu-spec.md §16.2](../simd/gpu/simd-gpu-spec.md));
there is still no GPU RTL in either repo to run it on, and the outer boundary it leans on is **L2**, which is `NOT MET`.

---

## 2. The TCB

**In the TCB**, in order of how much of the system falls if it fails:

1. **The hypervisor** (hyperprivileged, `SR.HPRIV = 1`) — Phase 3,
   [hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md). It owns ASID
   range allocation, `TSBBR`, `PDID`, `L2WAYMASK`, the emulation aperture, vCPU
   placement, and the gang-switch sequence. **It does not exist yet**: the spec
   says so in as many words ("The hypervisor itself remains unimplemented — this
   whole document is Phase 3",
   [hypervisor/design-spec.md §3.8a](../hypervisor/design-spec.md)). Every
   structural isolation argument in this project currently terminates in
   software nobody has written.
2. **The CPU RTL** — the TLB compare and permission check
   ([mmu/hardware-spec.md §4.3](../mmu/hardware-spec.md); `jcore-cpu/core/tlb.vhd`
   calls itself "the multi-tenant isolation boundary"), the hardware TSB walker,
   the privilege gates, and — on a speculative part — every rule in
   [ooo/j32ooo-spec.md §9.4](../ooo/j32ooo-spec.md).
3. **The bus fabric and its BMID assignment**
   ([bus/fabric-spec.md §4](../bus/fabric-spec.md)), because the IOMMU's entire
   model rests on BMID being unforgeable by the initiator.
4. **The IOMMU** ([iommu/hardware-spec.md](../iommu/hardware-spec.md)) for any
   configuration with a DMA-capable device a tenant can influence.
5. **The boot ROM and bitstream**, trivially.
6. **The management plane** (board control, image build, tenant admission) — out
   of scope for the microarchitecture but named so nobody reads its absence as
   a claim that it is safe.

**Explicitly not in the TCB** — this list is the point of the document:

- **The guest kernel.** It is the adversary.
- **The guest's TSB.** It is memory the guest can read, and — until item **L7**
  of §8 lands — memory the guest can *write*, which is a guest→host escape under
  a hardware walker (§7.5).
- **The guest's page tables**, `PTEH`, `PTEL`, `ASIDR`, and every value it puts
  in them.
- **Any scheduler decision made by guest software.**
- **`MMUCR`, `TSBBR`, `TSBCFG` values a guest asks for.** They are trapped
  ([hypervisor/design-spec.md §5](../hypervisor/design-spec.md)); the hypervisor
  must bounds-check rather than program them.

---

## 3. The sharing model

Four levels, with a different mechanism at each. Getting these confused is how
"core = tenant" gets read as "tenant isolation is solved".

| Level | Shared by | What is shared | What separates tenants |
|---|---|---|---|
| **Thread context** (FGMT, 2-way on the product) | contexts of one core | everything not architectural state: L1-I, L1-D, TLB, TSB, predictor arrays, prefetch tables, issue bandwidth ([ooo/j32ooo-spec.md §13.3](../ooo/j32ooo-spec.md)) | **Nothing.** Contexts of a core are **one security domain** ([glossary.md §4](../glossary.md)) |
| **Core** | tenants over time | the same structures, plus their residue across a switch | The **gang switch** ([hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)) — a software sequence, with no hardware backstop |
| **Chip** | all cores | one set of L2 tag and data arrays, its pLRU, its MSHR pool, the fabric, the memory controller ([cache/l2-spec.md §2](../cache/l2-spec.md)) | **L2 way-partitioning on allocation only** ([cache/l2-spec.md §16.1](../cache/l2-spec.md)). Nothing else |
| **Board** | all tenants | DRAM device, power, thermals | Nothing in this document |

Three consequences that must be carried into every Wave-3 decision:

- **FGMT buys vCPUs per tenant, not tenants per core.** An *N*-context core runs
  one tenant with up to *N* vCPUs ([glossary.md §4](../glossary.md)). Any design
  that quietly assumes *N* tenants per core has broken the model, not optimised
  it.
- **The unit of tenancy is enforced by a scheduler, not by hardware.**
  [ooo/j32ooo-spec.md §18](../ooo/j32ooo-spec.md) calls this "the weakest link in
  the security model" in its own voice. A scheduler bug produces a perfectly
  functional machine with no isolation and no fault.
- **The chip level is *outside* the reach of the core-granular rule.** Two
  tenants on two cores share the L2 at the same instant, always. Way-partitioning
  is the only thing between them, and §7.6 scopes what it actually closes.

---

## 4. Which cores this covers, and the non-inheritance rule

**The product is J32-FM**, defined only as "J32-OOO + full memory subsystem
(L2 v2)" ([glossary.md §3](../glossary.md)). Note two things about that:

- **"FM" is "full memory subsystem", not FGMT.** The
  [j4-remediation-plan.md](../j4-remediation-plan.md) brief for this task reads
  as if it might be the latter; it is not. J32-FM is FGMT 2-way, exactly like
  J32-OOO ([glossary.md §4](../glossary.md)).
- **J32-FM has no owning specification.** Its entire definition is one glossary
  table cell, and the glossary is no longer authoritative for anything but names
  ([decisions/0001](../decisions/0001-one-authority-per-fact.md)). This threat
  model therefore treats **J32-FM's core as J32-OOO's**, and its memory system
  as [cache/l2-spec.md](../cache/l2-spec.md) T1/T2. *That substitution is an
  assumption, and it is recorded in §11 as a defect for Wave-2 **B3** to close —
  a product point with no spec cannot be security-reviewed, only guessed at.*

### 4.1 The non-inheritance rule (normative for this document and for Wave 3)

> **A verdict reached for one core is not evidence for another.** Every
> applicability judgement in §6 is stated per core class. A "does not apply"
> that rests on the absence of a microarchitectural feature is void on any part
> that has the feature, and must be re-derived rather than carried across.

This is written as a rule because the tree contains at least four live instances
of the failure, three of which this task found rather than inherited:

| Where | Claim | Why it is wrong |
|---|---|---|
| [mmu/security-review.md §1](../mmu/security-review.md) | Transient family: "**NO** (whole family)" | Superseded by this document. Rated against the in-order J4 RTL; the product speculates |
| [mmu/design-spec.md §6.0](../mmu/design-spec.md) | "The in-order, non-speculative pipeline removes the entire transient-execution attack class … by construction" | Same error, in a **live, unsuperseded** section of the MMU design spec. Superseded by this document |
| `jcore-cpu/docs/architecture/tlb.md §7` | "J4 is … strictly **non-speculative** … This neutralises the entire transient-execution attack class" and "The **software** TLB walk likewise removes the hardware-page-table-walker cache-timing class (AnC)" | Both halves are now false *for the core that document describes* — the walker is hardware, and §7.2 shows the fetch path speculates. Cross-repo; recorded in §11 |
| [ooo/j32lt-spec.md §16.1](../ooo/j32lt-spec.md) | — | The **counter-example**, cited here as the standard to copy: "In-order issue is not a defence … this core predicts branches and issues non-blocking loads past them, which is a complete Spectre-v1 gadget" |

### 4.2 Core classes

| Class | Parts | Speculation |
|---|---|---|
| **In-order, predictor-free** | J1, J2, the shipping J4 RTL (`PRIV_ARCH`), J32 baseline. **J1/J2 have no MMU and no walker at all** — `core/cpu.vhd` puts both behind `g_tlb_walk : if PRIV_ARCH generate`, so every MMU-derived row of §6 reads `N/A` for them, not `APPLIES` | No branch predictor, no OoO, no data speculation, no prefetcher. **But not "non-speculative"** — see §7.2, the fetch path speculates and the TSB walker is armed off it |
| **Speculative** | **J32-FM (the product)**, J32-OOO, J32-LT, J64 | Tournament or gshare predictor, BTB, RAS, stride prefetcher, speculative loads; J32-OOO adds full OoO with rename and a store-set memory-dependence predictor |

Every Spectre-class family **applies** to the speculative class. The mitigations
are specified — [ooo/j32ooo-spec.md §8.2a/§8.2b/§9.4/§20](../ooo/j32ooo-spec.md)
— and **none of them is implemented**, because neither speculative core exists.
The security posture of the product is therefore entirely a specification
posture today. That is a reason to get §8's bar right now, while it is still
free to change.

---

## 5. What we promise

Security properties, ordered so that a failure of *n* implies nothing about
*n+1*.

| # | Property | Enforced by | Status |
|---|---|---|---|
| P1 | A guest cannot name a physical address outside its own map | Hypervisor RA→HPA translation; `TSBBR` ownership | **Conditional** — depends on **L7** (§8) |
| P2 | A guest cannot install a translation the hypervisor did not author | The walker's sole data source being the hypervisor-written TSB | **Conditional** — same |
| P3 | A guest cannot read or write another guest's memory | P1 + P2 + ASID range partitioning ([hypervisor/design-spec.md §3.7](../hypervisor/design-spec.md)) | Conditional on P1/P2 |
| P4 | A guest cannot reach hypervisor memory | Hypervisor mappings absent from S/U | Architectural; loses to §7.5 and to the folded-P1 speculation escape ([hypervisor/hardware-spec.md §4.4.1a](../hypervisor/hardware-spec.md)) |
| P5 | A guest cannot execute with another guest's privileges | `SR.HPRIV` non-renamed and serializing | Specified, unimplemented |
| P6 | A guest cannot *observe* another guest's data through a microarchitectural channel | §8's bar, items **L1**, **L3**, **L4**, **L5**, **L6** | This is the property the bar exists to buy |
| P7 | A device cannot read or write memory outside its domain | IOMMU | **Currently false by default** — §7.7 |

**Non-guarantees, stated rather than discovered.** Rowhammer and DRAM-level
effects; power, EM and thermal channels; timing analysis of a victim's own
*committed* control flow (that is a constant-time-software property — the
reference is Kocher 1996, and [ooo/j32ooo-spec.md §20](../ooo/j32ooo-spec.md)
already scopes it out correctly); denial of service and fair scheduling; and
every residual channel enumerated in §10.

---

## 6. Applicability matrix, per core class

**Legend — five tokens, and the difference between two of them is the point.**

| Token | Means |
|---|---|
| `APPLIES` | The mechanism exists on that class and the design has no complete answer |
| `MITIGATED (unimpl.)` | A specified mechanism closes it — **and is not built.** *Every* `MITIGATED` in this table carries this suffix, because **nothing in §20 of either speculative spec is implemented** (§4.2). There is no bare `MITIGATED` row and there must not be one until silicon exists |
| `N/A` | The precondition is **structurally** absent on that class. **Every `N/A` names the structure whose absence it depends on**, so adding the structure invalidates the row loudly |
| `N/A (temporal)` | Absent only because a *component does not exist yet* — not a property of the design. These become live the moment the component lands |
| `out of scope` | Outside this document's boundary entirely (§5's non-guarantees) |

The distinction between `N/A` and `N/A (temporal)` is the one this table gets
read wrong: the first is a guarantee, the second is a countdown. Read alone —
which is how a matrix travels — a row must not be mistakable for "solved".

| Family | In-order class | Speculative class (**the product**) | Notes |
|---|---|---|---|
| Meltdown / L1TF (fault-suppressed illegal access) | **N/A** — no transient window past a faulting access | **MITIGATED (unimpl.)** by [ooo §9.4 rules 3, 4](../ooo/j32ooo-spec.md) (poison forwarding; no cache lookup on an unresolved PA) | Specified only; no silicon |
| Spectre v1 (bounds-check bypass) | **N/A** — no branch prediction | **APPLIES** | Delay-on-miss ([ooo §8.2a](../ooo/j32ooo-spec.md)) is the primary and is **formally incomplete** — §7.3 |
| Spectre v2 (branch-target injection), VMScape | **N/A** — no BTB | **MITIGATED (unimpl.)** by `PDID`-tagged predictors + commit-time-only updates | Tag width re-derived in §7.4. **Not built** — the bare `MITIGATED` this row used to carry read as solved when screenshotted |
| Spectre v4 (speculative store bypass) | **N/A** — no memory-dependence prediction | **APPLIES on J32-OOO** (store-set predictor, [ooo §8.4](../ooo/j32ooo-spec.md)); structurally absent on J32-LT | The product is J32-OOO-based, so it inherits the exposure, not the exemption |
| MDS / store-buffer, fill-buffer residue | **APPLIES architecturally**, not transiently — §7.8 | **APPLIES** | The SQ residue hole needs no speculation at all |
| **AnC / translation-structure cache leakage** | **APPLIES** — verdict reversed, §7.1 | **APPLIES**, and worse | The single most consequential re-derivation in this document |
| TLB side channel (TLBleed, occupancy, miss timing) | **APPLIES** | **APPLIES** | Split 8-ITLB/16-DTLB, shared across contexts, ASID-tagged but not partitioned |
| **TSB contention** (prime+probe on TSB sets) | **APPLIES** | **APPLIES** | The design already concedes this: "conflict-based prime+probe against it is real" ([mmu/design-spec.md §6.5](../mmu/design-spec.md)) |
| Cache side channel — L1 | **APPLIES**, bounded to one tenant by the tenancy rule | same | Closed *at an instant* by **L1** of §8; residue across a gang switch is **L1**'s flush obligation |
| Cache side channel — **L2** | **APPLIES** across cores | same | **Partially** mitigated — §7.6 scopes what way-partitioning closes |
| Flush+Reload | **APPLIES** — `ocbi`/`ocbp` are user-mode ([cache/l2-spec.md §17.5](../cache/l2-spec.md)) | same | Needs shared memory; therefore couples to page dedup — **L5** |
| DRAM row-buffer / bandwidth (DRAMA) | **APPLIES** | **APPLIES** | Nothing in the design addresses it |
| Port / issue-bandwidth contention (PortSmash) | **APPLIES** between contexts | **APPLIES** | Explicitly not mitigated ([ooo §20.2a](../ooo/j32ooo-spec.md)); the answer is the tenancy rule, i.e. **L1** |
| Shared MSHR occupancy | **APPLIES** | **APPLIES** | 4 MSHRs total, shared across banks *and cores* ([cache/l2-spec.md §12.3](../cache/l2-spec.md)) — a narrow, easily saturated resource |
| **Guest→host escape via a guest-writable TSB** | `N/A (temporal)` — no hypervisor exists yet, so there is no guest | **APPLIES** | Not a channel — an escape. §7.5 |
| **Guest→host escape via folded P1 under stale `SR.HPRIV`** | **N/A** — no speculation on `SR.HPRIV` | **MITIGATED (unimpl.)** by [hypervisor §4.4.1a](../hypervisor/hardware-spec.md) | Specified only; no silicon |
| DMA / IOMMU | **APPLIES** | **APPLIES** | Default-bypass at reset — §7.7 |
| Rowhammer | `out of scope` | `out of scope` | Memory part + physical allocator (§5) |

---

## 7. Re-derived verdicts

Each subsection states the old verdict, the leg it stood on, whether that leg
survives, and what the verdict is now. Per the task's standard: **a correct
conclusion resting on incorrect reasoning is a defect here.**

### 7.1 AnC / ASLR⊕Cache — verdict reversed from `NO` to `APPLIES`

**Old verdict:** `NO`. **Old leg:** *"No hardware walker, no page-table caches;
translation is a software handler + TLB."*

**Both halves of that leg are gone, and they are gone for different reasons.**

- *"No hardware walker"* is simply false now. `core/tlb_walk.vhd` is the sole
  TLB installer.
- *"No page-table caches"* is still **true** — this design has no MMU-cache
  hierarchy in Barr's sense. But it was never the load-bearing half. AnC needs
  *an attacker-observable, address-dependent memory access performed by the
  translation machinery*. Page-table caches are one way to get that. **A
  deliberately cached TSB walk is another**, and this design chose it.

**The mechanism, derived from the shipped design:**

1. On every TLB miss the walker probes the TSB set at
   `TSBPTR = (TSBBR & ~0x1F) | ((hash & mask) << 5)`
   ([mmu/hardware-spec.md §2.8](../mmu/hardware-spec.md)).
2. A set is one **32-byte cache line** ([mmu/hardware-spec.md §2.8](../mmu/hardware-spec.md)),
   and the L1 line is also 32 bytes (`jcore-cpu/cache/cache_pkg.vhd`,
   `cache_line_width_bits = 5`). **Set granularity and line granularity
   coincide**, so an observer resolves the *full* set index with no sub-line
   ambiguity — where AnC had to work through 8 PTEs per line.
3. Those reads are **cacheable, by an explicit and recently-hardened decision**:
   **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/cpu.vhd` containing `TSB COHERENCY POLICY`.**
   The policy block states it plainly — the walker drives a physical address,
   region decode on P1 returns cacheable, and "the walker reads through the very
   cache those stores go through."
4. `hash = f(VPN) ⊕ g(ASID)` is **XOR-separable and public**, and
   [mmu/hardware-spec.md §2.8a](../mmu/hardware-spec.md) says so itself, adding
   that the residual `g(ASID)` offset space is "only `2^TSB_SIZE_LOG`" and is
   brute-forceable by timing probes. *(That section previously gave the range as
   "64–1024 values", narrower than the register allows; it now reads 64–16384,
   matching [mmu/hardware-spec.md §2.6](../mmu/hardware-spec.md)'s valid range of
   6–14. Corrected by Wave-2 **B1**, so the §11 row that tracked it is retired.
   The correction does not change the conclusion — a 14-bit search is still a
   search, not an exclusion — but it was never immaterial to the attack's
   **cost**, since `TSB_SIZE_LOG` sets how many index bits exist to be learned
   and therefore how many observations the solve above needs.)

Put together: **one observation of which L1-D line the walker touched yields
`min(TSB_SIZE_LOG, log2(L1-D sets))` bits of a public, XOR-separable function of
the victim's VPN**, with a per-address-space constant that the design's own spec
calls brute-forceable.

*The bound matters and the first draft of this section omitted it.* The observer
does not read the walker's address; it resolves which **cache set** the walker
disturbed, so it can never learn more bits per observation than the cache has set
index bits, however large the TSB is. On the numbers available that is 8 —
`jcore-cpu/cache/cache_pkg.vhd` carries `cache_index_bits : natural := 8` (256
sets) — so the claim is exact for `TSB_SIZE_LOG ≤ 8` and was overstated by up to
6 bits at the top of the 6–14 range §2.6 permits.

**A caveat on that 8 is withdrawn — 2026-09-08, Wave-2 B1.** This paragraph
previously read that `cache_index_bits` is *"defined and referenced nowhere —
`git grep` finds it only at its own declaration"*, and downgraded it to "a
statement of intent, not a live parameter". That is false on
`jcore-cpu@master`: it drives `cache_tag_width`, `cache_index_msb`,
`cache_lines`, `cache_mem_words` and the address-field widths of
`dcache_ram_o_t` / `icache_ram_o_t`. **The likely cause of the original finding
is worth recording, because it will recur:** the declaration is lower-case
`cache_index_bits` and every use is upper-case `CACHE_INDEX_BITS`, and VHDL is
case-insensitive while `git grep` is not. A case-sensitive grep of a
case-insensitive language reports a live constant as dead.

So the 8 is a live parameter and the geometry *is* established: 8 index bits
over 32-byte lines put the top index bit at 12, which is
[mmu/hardware-spec.md §4.1a](../mmu/hardware-spec.md)'s subject and is now
code-bound as `cache.l1.index`. **The argument still does not need the number** —
it needs the bound to exist, which it does structurally, and enough bits per
observation to make a GF(2)-linear system at attacker-chosen VAs solvable, which
8 comfortably is. What changes is that the bound is now proven rather than
assumed, and the §11 row asking B0c to establish it is closed. `f` is linear over GF(2) in `HASH_MODE = 1`
(`VPN ⊕ (VPN >> HASH_SHIFT)`), so repeated observations at attacker-chosen VAs
give a solvable system rather than independent guesses.

**New verdict: `APPLIES`, on every J-Core part that has the walker — which is
all of them, including the in-order ones.** Three properties of this verdict
matter for Wave 3:

- **It does not require speculation.** This is the clearest demonstration that
  the old "in-order ⇒ safe" framing was answering the wrong question.
- **It is not new information to this project, only newly connected.**
  [mmu/design-spec.md §6.5](../mmu/design-spec.md) already concedes TSB
  prime+probe is real, and [mmu/hardware-spec.md §2.8a](../mmu/hardware-spec.md)
  already refuses to call the ASID fold a boundary. What was missing was the
  step from "the TSB is a contention channel" to "the *walker* makes the channel
  hardware-driven, unavoidable, and indexed by the victim's virtual address" —
  which is precisely AnC.
- **The ASLR payload is conditional; the primitive is not.** Whether a given
  guest randomises its layout is the guest's business. The hardware supplies a
  VA-recovery oracle either way, and §5's P6 is what it violates.

**What closes it, and what does not.** Cross-*tenant* exploitation at an instant
is closed by **L1** (one tenant per core, so the L1-D observer is the victim's
own tenant) — *not* by anything in the MMU. Cross-tenant exploitation through
the shared **L2** is bounded, not closed, by way-partitioning (§7.6).
**Intra-guest exploitation — a guest user process against its own guest kernel,
which is AnC's original setting — is completely open**, and no item in §8's bar
addresses it. The available mechanism is
[mmu/hardware-spec.md §2.13a](../mmu/hardware-spec.md)'s per-domain TSB
partitioning, driven by the guest itself. Deliberately left to Wave 3 (§11).

### 7.2 "The core is non-speculative" — false even for the in-order parts

Not a verdict the previous review stated as a row, but the premise under half
its rows, so it is re-derived here.

`jcore-cpu/core/cpu.vhd` arms an I-side TSB walk directly off a live fetch miss
(`walk_i_miss <= '1' when i_at_translated = '1' and sig_inst_o.en = '1' …`),
while the *fault* is deferred to dispatch (`core/components_pkg.vhd`: "A fetch
that is squashed before dispatch therefore never raises anything"). The two
together mean:

> **On the shipping in-order core, a fetch that is later squashed can still have
> caused a TSB walk — a set of cacheable reads through the L1-D — and a TLB
> install.**

That is a speculative translation-structure fill, on the part whose
documentation says it has no speculation at all. It is exactly the surface
[j4-remediation-plan.md §C2](../j4-remediation-plan.md) flags as "speculative
TLB/TSB fill", and it composes with §7.1: the *speculative* footprint is
observable by the same mechanism as the architectural one.

**Verdict: the in-order class is "predictor-free", not "non-speculative", and
the two are not the same claim.** Wave 3's C2b must cover the I-side walk arm,
not only the D-side load path.

**Widened by C2b, 2026-09-09 — it is two installs and four transmitters, not
one install.** The paragraph above says "a TLB install", singular. An I-side
install also drives a second, **speculative DTLB install** one cycle later —
`core/cpu.vhd` registers `shadow_wr <= walk_install and walk_side_i` and re-drives
the DTLB write port from it — so a squashed fetch reaches the D-side translation
array as well as the I-side one. Counting the L1-I line the fetch itself filled,
a fetch squashed before dispatch reaches **4** transmitters ([mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md)), and three
of them are conditional on the arm this section names. The enumeration, the rules
that bound them, the one that is accepted rather than closed, and the experiment
that prices the gate are [mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md).
**Nothing in this widening moves the verdict** — it makes the exposure wider than
this section stated and does not make it new.

### 7.3 Delay-on-miss is a good primary and is not a solution

**Ratified as specified, with its completeness claim removed.**
[ooo/j32ooo-spec.md §8.2a](../ooo/j32ooo-spec.md) says delay-on-miss "closes the
cache covert channel of §20.2, and it closes it for L1, L2, replacement metadata
and the coherence fabric simultaneously." Every clause of that is true *for the
D-side cache-fill channel*, and the sentence is nonetheless the kind of
completeness claim this project has to stop making: Pensieve (ISCA 2023)
model-checked delay-on-miss and found Spectre-like attacks against it, and
Speculative Interference (ASPLOS 2021) leaks through the timing of *older*
instructions with no speculative miss issued at all. **Both `LITERATURE`** (§9's
scale) — and they are load-bearing, since they are the whole reason §8.2a's
sentence is struck. If either is being read as decisive, follow it to the paper
first; C0 did not.

The design is already better than the sentence: §9.4 rule 2 gives commit-only
predictor training, rule 3 gives degenerate taint (poison may not form an
address or a branch condition), rule 5 gives mode snapshots. What is missing is
(a) the I-side walk arm of §7.2, (b) an honest statement of the residual, and
(c) the scope fix to §8.2a's sentence. **All three are Wave-3 C2b**, and item
**L4** of §8 is the pass mark.

**All three have landed as specification, 2026-09-09 — and the sentence had a
second defect that the completeness charge hid.** (a) is
[mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md); (b) is §10 items 11–13
below; (c) is [ooo/j32ooo-spec.md §8.2a](../ooo/j32ooo-spec.md), where the
sentence is now scoped to the fill/allocation half. The second defect is that
§8.2a **contradicted itself**: two bullets above the struck sentence, speculative
L1-D hits proceed at full speed, and [ooo/j32ooo-spec.md §11.1, §11.2](../ooo/j32ooo-spec.md)
make both L1s pseudo-LRU — so a hitting load that never commits does update
replacement state, in the same subsection that said no non-committing load can.
This is the *speculative-hit pLRU-update contradiction*
[j4-remediation-plan.md §C2](../j4-remediation-plan.md) asks C2b to resolve, and
it is worth noting that it sat inside a sentence already flagged for a different
reason: striking the completeness claim would have deleted the evidence of the
contradiction without ever naming it. **It is a defect of the specifications and
of nothing built** — `jcore-cpu@origin/master`'s L1s are direct-mapped and hold
no replacement state, and a case-insensitive search of that tree for `plru` or
`pseudo-lru` returns nothing. It is therefore *not* the same finding as §7.6's
hit-time pLRU update, which is about two way-partitions of a shared L2 and
belongs to **L5**/C2e; the two share a word and not a mechanism.

### 7.4 "Do not truncate `ASID_TAG` into a predictor index" — conclusion upheld, on a third leg

**Old leg:** truncation "discards the generation field", i.e. the top nibble of
the 16-bit `ASID_TAG` ([mmu/hardware-spec.md §2.1a](../mmu/hardware-spec.md)).
**Void** — the nibble is gone:
**RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: retire the ASID generation nibble".**

**B0a's replacement leg** was that truncation still discards `ASID[11:8]`, "15/16ths
of the 4096-ASID range". That is arithmetically correct and it is still the
wrong shape of argument, because it describes a *loss of entropy* when the real
problem is a *structured collision*.

**The re-derivation.** Take the design's own partition arithmetic
([hypervisor/design-spec.md §3.7](../hypervisor/design-spec.md)): host gets
ASIDs 0–2047, and sixteen guests get 128 each from 2048 upward. Truncate to
`ASID_TAG[7:0]`, the form [ooo/j32ooo-spec.md §20.10](../ooo/j32ooo-spec.md)
records as the rejected earlier revision:

| Guest | ASID range | Low 8 bits |
|---|---|---|
| Guest 1 | 2048–2175 (`0x800`–`0x87F`) | `0x00`–`0x7F` |
| Guest 2 | 2176–2303 (`0x880`–`0x8FF`) | `0x80`–`0xFF` |
| Guest 3 | 2304–2431 (`0x900`–`0x97F`) | `0x00`–`0x7F` |
| … | … | … |

**Guest 3 aliases Guest 1 exactly, one-to-one.** Sixteen guests collapse onto
**two** predictor domains, and within a colliding pair the map is a *bijection* —
guest 1's *n*-th ASID and guest 3's *n*-th ASID share a predictor index by
construction, every time, with no probability involved. The host's 2048 ASIDs
cover all 256 residues, so the host aliases every guest.

That is a strictly stronger statement than "15/16ths of the range is lost", and
it is stronger for a specific reason worth carrying forward: **range
partitioning and low-bit truncation are maximally incompatible.** Contiguous,
power-of-two-aligned ranges are precisely the allocation pattern that a modular
truncation folds onto itself perfectly. Had the hypervisor interleaved or hashed
its ASID assignment, the same truncation would have been merely lossy.

**Verdict: upheld, and now demonstrated rather than asserted.** `PDID` is
required, and it must not be derived by truncating `ASID_TAG`.
[ooo/j32ooo-spec.md §20.8](../ooo/j32ooo-spec.md)'s verification row S8 — "a
pair whose `ASID_TAG` values differ only above bit 7" — is exactly the right
test, and the table above is the concrete instance to instantiate it with:
guest 1 versus guest 3.

Two riders, both new:

- **`PDID` is 6 bits and must not be truncated either.** 64 domains against 16
  guests is comfortable, but [hypervisor/hardware-spec.md §2.8](../hypervisor/hardware-spec.md)
  already contemplates recycling. Recycling without the predictor-invalidate
  control reintroduces exactly this collision one level up.
- **The same argument applies to `L2WAYMASK`, which is keyed by `PDID`**
  ([cache/l2-spec.md §16.1](../cache/l2-spec.md)). Domain identity is now
  load-bearing in two structures, not one.

### 7.5 The guest-writable TSB — a guest→host escape, and its merge gate was inverted

**Not a re-derivation of an old verdict — a verdict the old review had no row
for, and the most severe finding in this document.**

The chain, entirely from merged code and existing specs:

1. The hardware walker installs TLB entries **with no exception and no trap**
   ([mmu/hardware-spec.md §5.0](../mmu/hardware-spec.md)).
2. The per-`LDTLB` verification step that used to catch a forged entry is
   therefore gone. [hypervisor/design-spec.md §6](../hypervisor/design-spec.md)
   states the replacement argument: "the walker's only data source is the set at
   `TSBBR | hash`; `TSBBR` is hypervisor-owned and P4-trapped; therefore the
   walker can only install entries the hypervisor wrote."
3. That argument holds **only if the guest cannot write its own TSB**. The same
   section says so: "A guest-writable TSB under a walker is a direct guest→host
   escape."
4. The read-only guest TSB mapping is **specified and not implemented**
   ([hypervisor/design-spec.md §3.8](../hypervisor/design-spec.md), "Status:
   DESIGNED, not yet implemented").
5. There is **no hardware bounds check on `TSBBR`**. The only bound is the
   walker's `timeout_cycles` liveness limit, and
   [mmu/hardware-spec.md §5.0](../mmu/hardware-spec.md) says a malformed `TSBBR`
   simply "hangs the walk". The bounds check is hypervisor software that does not
   exist.

[j4-remediation-plan.md §C2](../j4-remediation-plan.md) required exactly this
ordering: *"gate the walker's merge on the read-only-guest-TSB enforcement and
the `TSBBR` bounds check landing first … Until then the walker must keep the
per-LDTLB verification path."* **The walker merged; neither precondition did;
and the verification path was retired rather than kept.** The plan's own Track F
names walker-versus-read-only-TSB ordering as "the cautionary example" of merge
discipline, and it is the instance that was violated.

**Live exposure today is zero**, and saying so is part of being honest: there is
no hypervisor, so there is no guest, so there is nothing to escape from. **The
defect is that the structural argument for P1 and P2 is now owed entirely to
software nobody has written, with no hardware backstop and no test.** That is
why §8 gains item **L7**.

### 7.6 L2 way-partitioning — ratified as an allocation control, not as isolation

[cache/l2-spec.md §16.1](../cache/l2-spec.md) is a good mechanism and its own
text contains the scope it needs. Two clauses do the work, and they point in
opposite directions:

- *"Prime-and-probe requires the attacker to allocate lines that evict the
  victim's. Restricted to disjoint ways, it cannot."* — **true**, and this is a
  real boundary for the occupancy channel.
- *"**Hits are not restricted.** A domain may hit on a line in any way … the
  hit-time pLRU update … behave[s] as before."* — so a victim's hit **in the
  attacker's ways** updates shared replacement metadata. This is DAWG's central
  finding stated in the spec's own words, one paragraph apart from the claim it
  qualifies: in a CAT-style scheme, access patterns leak through metadata updates
  on hitting loads.

Add the two structures the section does not mention at all: the **4 shared
MSHRs** ([cache/l2-spec.md §12.3](../cache/l2-spec.md), "shared across banks"),
and DRAM bandwidth. Four MSHRs across the T1 baseline's two cores and four
contexts ([cache/l2-spec.md §12.2](../cache/l2-spec.md) sizes the `requestors`
vector as "2 cores × 2 threads × {L1-I, L1-D}") is not a
generous pool; saturating it is a low-effort, high-bandwidth channel.

**Verdict:** way-partitioning closes the **allocation/occupancy** channel by
construction and is worth building. It does not close replacement-metadata,
MSHR, bank-FIFO or bandwidth channels, and §16.1's "closes the channel" sentence
must be scoped to occupancy. Item **L5**.

### 7.7 IOMMU — the reset state is on the wrong side, and the fix is narrower than proposed

Read directly from [iommu/hardware-spec.md](../iommu/hardware-spec.md):
`IOMMU_CTRL` bit `[0] ENABLE` reset value `0` — "IOMMU bypassed for all
masters"; `BMID_BYPASS_*` resets to "All 1s (every BMID bypasses)"; and the
spec's own summary, "Until then, the IOMMU is functionally absent — all DMA
passes through with `PA = IOVA`." `SUPER_BYPASS` (bit `[2]`, "all transactions
bypass regardless of `BMID_BYPASS`") has **no lock**. IOTLB entries carry a
`GLOBAL` bit — "If set, match any BMID" — which is the Thunderclap shape:
IOMMU on, mapping too coarse.

**One sharpening of the bar, in the project's favour.** The proposed bar asks
for "per-device **deny domains**" as if a new state were needed. It is not: a
BMID with `BMID_BYPASS[N] = 0` and no matching IOTLB entry **already blocks**,
latches a fault and raises an IRQ. Deny is the *existing* miss behaviour. What
is actually wrong is three things, all cheaper than a new state machine:

1. the **reset polarity** of `ENABLE` and `BMID_BYPASS_*`;
2. `SUPER_BYPASS` having **no write-once lock**;
3. the **`GLOBAL` IOTLB bit** existing at all — it is the S-I7 lesson
   (a global bit with no guard is a cross-domain disclosure primitive) reappearing
   one block over.

**L2 requires five clauses; only these three are derived here.** The other two —
detach/teardown re-protection, and a per-BMID quota on the shared IOTLB — are
**inherited from [j4-remediation-plan.md §C2](../j4-remediation-plan.md) without
independent C0 backing.** They are plausible: a device released to a tenant
before its mappings are torn down is the Thunderclap window reopened, and an
unquota'd shared IOTLB is §7.6's MSHR channel in a different structure. But C0
did not read the IOMMU RTL, and neither the teardown path nor the IOTLB's sharing
structure was checked closely enough against
[iommu/hardware-spec.md](../iommu/hardware-spec.md) to say which channel each
closes. **C2d's design step owes that derivation**, and is entitled to argue
either clause down — which the three above are not, since they are read directly
off the register definitions.

**Verdict: bar item ratified, mechanism restated. Launch blocker for any
configuration with a tenant-influenced DMA master.** Item **L2**.

### 7.8 Lazy FP/SIMD switch — worse than LazyFP, and not because of speculation

[fpu/spec.md §7.3](../fpu/spec.md) specifies the trap-on-first-use lazy model,
and its restore path reads:

> *"Else: reset the physical FPU to post-reset defaults (`FPSCR = 0x00040001`,
> FR/XF/FPUL = **undefined** per SH-4, but the hypervisor must write at least
> FPSCR to its default to ensure determinism)."*

So a fresh vCPU with no saved image inherits **the previous owner's `FR`/`XF`/
`FPUL` contents, architecturally, with no speculation required**. LazyFP
(CVE-2018-3665) needed a transient window to read stale registers before the
`#NM` delivered; here the registers are simply there, readable by committed
instructions. The `SR.VD`/SIMD analogue is the same shape over a much larger
file.

The store queue has the identical defect in write form: `PREF` bursts all 32
bytes, and [sq/spec.md §4](../sq/spec.md) said "Bytes within the queue that were
never written since the queue's last burst have **undefined** content". A tenant
that writes one word and bursts publishes the previous owner's bytes to an
address of its own choosing.

> **Specified 2026-09-09 by Wave-3 C1a, and not thereby met.**
> [sq/spec.md §6.5](../sq/spec.md) replaces that "undefined" with a defined zero,
> adds the scrub, and defines the guest read; [hypervisor/hardware-spec.md
> §4.7.1](../hypervisor/hardware-spec.md) item 7 puts the scrub on the
> gang-switch list. **There is no store-queue RTL** — `jcore-cpu@origin/master`
> has no store queue, no SQ region decode and no SH-4 `PREF` — so the site moves
> from *a specified "undefined"* to *a specified scrub*, and L6's evidence bar,
> which is a residue test demonstrated red before the fix, has nothing to run on.

> **The FP/SIMD instance: specified 2026-09-09 by Wave-3 C1b, and not thereby
> met either.** [fpu/spec.md §7.7](../fpu/spec.md) withdraws the word "undefined"
> from the branch quoted above and gives the file a scrub value; the SIMD half is
> [simd/spec.md §2.6.1](../simd/spec.md); [hypervisor/hardware-spec.md
> §4.7.1](../hypervisor/hardware-spec.md) item 8 puts both on the gang-switch
> list. **There is no FPU and no SIMD unit in `jcore-cpu@origin/master`** — no
> `entity fpu`, no `FPSCR`, no `VCSR`, checked case-insensitively — and
> `linux@origin/jcore` cannot even set `CONFIG_SH_FPU` on this target, because
> `CPU_SUBTYPE_JCORE` does not select `CPU_HAS_FPU`. Same verdict as the store
> queue: *specified "undefined"* becomes *specified scrub*, with nothing to run
> the residue tests on.
>
> **One branch this paragraph did not list**, found by C1b while writing that
> section: `HEDR[3] = 1` (and `HEDR[24] = 1` for SIMD) delegates the first-use
> trap to the **guest's** handler, so the hypervisor's ownership transition never
> runs at all. The lazy model is not merely incomplete on the no-image path; a
> per-vCPU configuration bit can remove it from the hypervisor entirely. That is
> why [fpu/spec.md §7.7](../fpu/spec.md) anchors its fix at the gang switch
> rather than in the trap handler.

And a third instance nobody had listed: `movca.l R0,@Rn` allocates an L2 line
"with only the written word defined and the remainder **undefined** until
written" ([cache/l2-spec.md §17.5](../cache/l2-spec.md)). If "undefined" is
realised as *whatever the data array way already held*, that is a cross-tenant
read primitive reachable from user mode.

**Verdict: three concrete instances of "undefined = the previous owner's data",
in three different subsystems.** Items **L3** and **L6**. Note that all three are
architectural, so all three apply to the **in-order** class as well — another
row the old review would have marked `N/A` by inheritance.

### 7.9 S-I3 (stale-TSB rejection) — closed, by a different mechanism, and the closure is stronger

[mmu/security-review.md](../mmu/security-review.md) finding S-I3 warned that a
4-bit generation discriminator wraps every 16 rollovers and lets a stale TSB
slot false-hit. Its recorded resolution — thread the generation into `ASID_TAG`
and rebuild the TSB on `gen_low` wrap — no longer exists.

**Re-derived.** The finding is closed, on two legs that are jointly stronger
than the one they replace, both merged:

- **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: give every CPU its own TSB".**
  Per-CPU TSBs remove the cross-CPU sharing that the nibble was protecting.
- `local_flush_tlb_all()` zeroes the TSB on **every** version wrap, which is
  strictly stronger than an every-16th-wrap rebuild
  ([mmu/hardware-spec.md §2.1a](../mmu/hardware-spec.md)).

**There is no residual wrap hazard and no 16-generation window.** Two riders:
this argument is about *stale-TSB* rejection within one address-space
generation, and it says nothing about tenant separation, which rests on ASID
*range partitioning* and is re-derived in §7.4.

**The second rider is a correction to this document's own first draft, and it
points the wrong way, so it is stated at length.** `ASID_TAG[15:12]` is **always
zero by kernel convention, and is not reserved in hardware.** The owning spec
says so in as many words — [mmu/hardware-spec.md §2.1a](../mmu/hardware-spec.md):
the retirement commit *"makes no RTL change; the top nibble is simply always zero
on both sides."* Checked in the merged RTL rather than inferred from that
sentence:

- `core/datapath.vhm` writes the register unmasked — `when SEL_ASIDR => this.mmu.asidr := zbus`.
- `core/tlb.vhd` compares **all sixteen bits**: `entry.asid_tag = asid`.
- `core/cpu.vhd` hands **all sixteen** to the walker — `asidr => dp_mmu_regs.asidr(15 downto 0)` —
  and `tsb_ptr()` folds all sixteen into the set index.

Zero-ness is enforced only by the kernel's own ASID mask
(`linux/arch/sh/include/asm/mmu_context.h`), and the kernel is not in the TCB.

**Why this matters here and not merely in the MMU spec.** §1 establishes that the
adversary writes `ASIDR` **untrapped**. So four *adversary-controlled* bits reach
the TLB tag compare and the TSB index fold, and describing them as
hardware-reserved would credit the design with a guard it does not have. The
**S-I3 verdict is unaffected** — neither merged leg uses the nibble — but by §7's
own standard a conclusion resting on wrong reasoning is a defect, so the reasoning
is corrected rather than the verdict.

Note also what the nibble is *not* a hole in: the extra bits widen the tag the
adversary controls, they do not narrow it. A guest that sets them still misses in
its own TSB, because the TSB entries it can reach carry the tags the hypervisor
wrote. The exposure is to §7.4's structural-index concern, not to a tag forgery.

### 7.10 The two Wave-0 fixes, confirmed merged

Recorded because the previous review predates both and a reader must not
re-derive them:

- The 16 KB TLB-walker tag-compare livelock is fixed, kernel-side, by writing a
  canonical tag rather than by changing the walker:
  **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: write the canonical 4 KB TSB tag, never addr & PAGE_MASK".**
  The hardware side of the contract is
  **RESOLVED 2026-08-25 — jcore-cpu@master: "docs(walker): the tag compare is canonical-4 KB, not `addr & PAGE_MASK`"**
  with guards at
  **RESOLVED 2026-08-25 — jcore-cpu@master: "test(mmu): Group-B guards for the TSB tag-granularity contract".**
- The missing `SR.MD` gate on the P4 MMU-register MMIO path is fixed:
  **RESOLVED 2026-08-25 — jcore-cpu@master: "fix(mmu): require SR.MD=1 for the P4 MMU-register path".**
  Note the accepted waiver recorded in
  [j4-wave0-status.md](../j4-wave0-status.md): the refusal is unconditional, but
  a one-cycle `dp_p4_viol` pulse can clobber an older pending fault's `TEA`. No
  leak and no escape; "confined to diagnosis" is the honest ceiling.

---

## 8. The minimum security bar for multi-tenant launch

**Nothing in Wave 3 ships without meeting the item it is gated on, and no
tenant-facing service opens until every item is `MET`.**

Items are renumbered **L1–L7**. They were `A1`–`A6` in
[j4-remediation-plan.md §E.11](../j4-remediation-plan.md); those IDs collided
with Track-A hotfix task numbers `A1`/`A2`, which is a real confusion hazard in
a document that gates work. The mapping is in the last column.

| ID | Requirement | Verdict | Was |
|---|---|---|---|
| **L1** | Core = single tenant at all times | Ratified, one clause added | A1 |
| **L2** | IOMMU default-deny | Ratified, mechanism narrowed | A2 |
| **L3** | Eager FP/vector switch or scrub across tenants | Ratified, strengthened | A3 |
| **L4** | Speculation covers loads **and** frontend | Ratified, scope widened | A4 |
| **L5** | Cache isolation beyond ways | Ratified, one claim added | A5 |
| **L6** | Scrub on ownership change; "undefined" banned | Ratified, two instances added | A6 |
| **L7** | The walker's data source is hypervisor-owned | **New** | — |

### L1 — Core = single tenant at all times

**Requirement.** No two tenants occupy thread contexts of one core at any
instant. A core may be reallocated between tenants over time only by a gang
switch that flushes **all** thread-shared state: L1-I, L1-D, TLB, predictors,
BTB, RAS, stride tables, MSHRs, store-queue buffers, and the FP/SIMD register
files. Cross-tenant fine-grained MT is out of bounds for launch.

**Ratified.** The rule already exists as normative text —
[hypervisor/hardware-spec.md §4.7](../hypervisor/hardware-spec.md) and
[glossary.md §4](../glossary.md) — and the evidence base (MDS, PortSmash, the
Linux core-scheduling documentation's own "the only full mitigation of cross-HT
attacks is to disable Hyper-Threading", OpenBSD's SMT removal, AWS Nitro and
Azure's SMT-off SKUs) supports it as *industry practice at exactly this
granularity*. **`LITERATURE`** (§9's scale), not verified by C0 — every item in
that list reaches this
document through [j4-remediation-plan.md §E.5](../j4-remediation-plan.md), and
none was checked against a primary source by this task. The same label §9 applies
to the performance literature applies here, and for the same reason: the
strongest argument on this page should not be the least-audited one.

**One clause added, and it is the one that will actually be got wrong.**
[hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)'s gang-switch
list did not include the store-queue buffers or the FP/SIMD register files, and
§7.8 shows both carry the previous owner's data by specification. **The
gang-switch sequence must be extended, and L1 is not `MET` until it is** —
otherwise **L1** and **L6** each assume the other covers this, which is how a gap
survives two reviews.

**Discharged as a specification, 2026-09-09.** The list now has **10** items ([hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)),
of which item 7 is the store-queue scrub (Wave-3 **C1a**), item 8 the FP/SIMD
register-file scrub (Wave-3 **C1b**) and item 9 the microreset (Wave-3 **C2c**).
Both structures this clause names are on
the list, so **the clause itself is discharged**. L1 is still `NOT MET`, on the
two things the clause was never about: the **detector**, which is C2c's, and the
per-structure residue tests below, none of which can be run because none of the
items has hardware to run them on. Recording the two halves here rather than
in C1a's and C1b's own documents is deliberate — a task that reads only its own
spec is exactly how the other half gets forgotten.

**A third structure this requirement names was on no list at all, and it is the
one nobody noticed because the word is ambiguous.** The requirement above says
the gang switch must flush "MSHRs". Until 2026-09-09 no item on
[hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)'s list
reached one, and the reason it went unremarked is that the docs contain two
different MSHR pools:

- The **L2's**, four of them, shared across banks *and cores*
  ([cache/l2-spec.md §12.3](../cache/l2-spec.md)) — already an `APPLIES` row in
  §5. No core-granular gang switch can reach it, so this word never belonged to
  **L1**; it is **L5**'s, and §10 item 4 and the C2e row below already say so.
- The **core's own**, which [ooo/j32lt-spec.md §7.4](../ooo/j32lt-spec.md)
  partitions two demand plus one prefetch per thread. Per-*thread* partitioning
  says nothing about a realloc of the same thread context to a **new tenant**, so
  it is squarely L1's — and it has no software-visible clear, because a fill in
  flight is not a tag and `CCR.ICI`/`CCR.OCI` clear tags.

C2c's item 9 covers the second and explicitly not the first
([hypervisor/hardware-spec.md §4.7.1a](../hypervisor/hardware-spec.md)), together
with three further classes that had the same problem — L1/TLB **replacement-policy
state**, the **FGMT thread-select state**, and any **write buffer** below a
write-through L1-D — for
**4** structure classes ([hypervisor/hardware-spec.md §4.7.1a](../hypervisor/hardware-spec.md)) in all. Item 9 exists because *"there is a control for it"* was doing
the work of *"it is on the list"*, and every structure the list reached had a
control for a different reason.

**Second clause, weaker but recorded:** the rule has no hardware backstop, and
[ooo/j32ooo-spec.md §18](../ooo/j32ooo-spec.md) calls it the model's weakest
link. Launch accepts scheduler enforcement — with the industry precedent as the
justification, not as an excuse — **provided** there is a test that a violating
placement is detectable. An unenforceable rule with no detector is not a
control.

**The detector is specified, 2026-09-09, Wave-3 C2c** —
[hypervisor/hardware-spec.md §4.7.2](../hypervisor/hardware-spec.md), rules
rules **T-R1**–**T-R5** of [hypervisor/hardware-spec.md §4.7.2](../hypervisor/hardware-spec.md),
on a new per-thread-context hyperprivileged register `HTCR` (§2.10 there). It turns on a distinction §4.7 did not draw: hardware cannot know
*which* tenant a context belongs to — §4.7 says so and is right — but it can be
told that two contexts belong to *different* ones, and disagreement is the whole
of the property. The check is evaluated at `HRTE`, which is the only transition
that can falsify the property, and a failing `HRTE` is **refused** rather than
trapped, because [hypervisor/hardware-spec.md §4.1](../hypervisor/hardware-spec.md)'s
trap-entry path would overwrite `HSPC`/`HSSR` — the guest resume state the
refused entry needs to retry.

**This fires §12's second trigger.** *"A hardware backstop for tenancy is
proposed"* is listed there as a condition that reopens this document, and it has
now happened. What it changes is narrower than the trigger's wording suggests and
the narrowing is the point: L1's *placement* half becomes a control, so §10 item 8
and the C2e row's reliance on "the scheduler is right" are backed by hardware for
the virtualized case. L1's *flush* half does not change:
**T-R3** of [hypervisor/hardware-spec.md §4.7.2](../hypervisor/hardware-spec.md) clears nothing,
deliberately, and the reason is
[ooo/j32ooo-spec.md §20.7](../ooo/j32ooo-spec.md) rejection 2. And three cases
stay pure policy: an unvirtualized multi-tenant system has no `HRTE` to check, a
hypervisor may still hand two tenants the same number, and the GPU's SM is not
reached at all (below). **Nothing here moves L1 to `MET`:** the detector is
*specified and unbuilt*, like every other clause on this item.

**Evidence required for MET.** A test that a *violating placement is detected* — not
merely that a conforming one works. Concretely: a two-tenant placement on one
core's contexts must be refused at admission, or flagged by a counter the
operator reads. Plus, for the flush half, a residue test per structure on the
§4.7.1 list **and** per structure this item adds: write a recognisable pattern
from tenant A, gang-switch, and prove tenant B cannot recover it. A list with no
per-structure test is a list, not a control — which is this item's own argument
turned on itself.

**Those tests now exist as specifications and none of them can be run**
([hypervisor/hardware-spec.md §4.7.1b](../hypervisor/hardware-spec.md)): **T-E1**
is the violating-placement refusal, **T-E2** the microreset's cost and duration,
**T-E3** the per-structure residue test. C2c verified at
`jcore-cpu@origin/master` that there is neither FGMT RTL (`fgmt`, `thread_id`,
`multithread` return nothing over `*.vhd`/`*.vhm`; `barrel` returns only the
barrel *shifter*, `core/shifter.vhd` and `core/shifter_seq.vhd`) nor hypervisor
RTL (`hpriv`, `hcall`, `hrte`, `vbr_hyp`, `pdid`, `hedr` return nothing), so
there is no second thread context to place a second tenant on and no `HRTE` to
refuse. T-E1 carries the instruction that matters most for this item's history:
on a single-context model it passes **vacuously**, and it must report *not
runnable* instead — a detector that reports success against a machine which
cannot express the violation is worse than no detector.

**The scoping question C2a raised on 2026-09-09 is decided here, 2026-09-09, by
C2c, which owns this item.** The requirement says "one core" and "Cross-
tenant fine-grained MT is out of bounds for launch". The GPU's SM is described by
its own architecture as a **barrel-threaded jcore core** running the existing
SIMD datapath as its lane ISA, holding **4–8 warps resident** so the scheduler
can issue a ready one each cycle
([simd/gpu/architecture.md §1.1, §3.1, §3.2](../simd/gpu/architecture.md)). That
is fine-grained MT by this document's own definition. So:

- **If an SM is "a core" for L1**, then a GPU with warps from two tenants
  resident is out of bounds at launch *independently of C2a* — and C2a's windows
  are then intra-tenant separation plus defence in depth, not the cross-tenant
  mechanism [j4-remediation-plan.md §C2](../j4-remediation-plan.md) asks them to
  be. The only launch-legal GPU is the single-tenant one
  ([simd/gpu/simd-gpu-spec.md §16.3](../simd/gpu/simd-gpu-spec.md) G-R10.3).
- **If it is not**, the GPU needs an L1-equivalent that nobody has written, and
  its absence is invisible because L1 looks satisfied.

**Decision: an SM is "a core" for L1.** The first reading is correct, and what
settles it is that "core" is not L1's operative term. [glossary.md §4](../glossary.md)
defines the security-domain status of co-resident contexts by a *property* —
"the contexts of one core **share** the L1 caches, the L2, the TLB, the TSB and
the branch-predictor arrays, and are therefore **one security domain** unless a
product point explicitly says otherwise" — and states the allocation rule as a
consequence of it. An SM has that property by its own architecture: 4–8 warps
resident, selected per cycle, over a shared tile buffer, texture cache and
per-warp register files that
**G-R8** ([simd/gpu/simd-gpu-spec.md §16.3](../simd/gpu/simd-gpu-spec.md)) makes
ownership-change sites precisely because they are shared. Reading
"core" as a word about CPU pipelines would make the rule depend on which
document names a block, and the glossary's "unless a product point explicitly
says otherwise" is the only exemption clause on offer — the GPU specs claim no
such exemption.

**What the decision costs, and it is not nothing.** Two consequences follow, and
the second is why this could not be decided by asserting the reading alone.

1. **At launch, warps of two tenants must not be concurrently resident on one
   SM**, independently of C2a. C2a's windows are therefore intra-tenant
   separation plus defence in depth, and the only launch-legal GPU is the
   single-tenant one —
   G-R10.3 of [simd/gpu/simd-gpu-spec.md §16.3](../simd/gpu/simd-gpu-spec.md) — which is what
   C2a's row in the reverse index anticipated.
2. **The detector does not transfer, and this is Wave-3 C1c's lesson applied to
   L1's own rule.** [hypervisor/hardware-spec.md §4.7.2](../hypervisor/hardware-spec.md)
   is evaluated at `HRTE`, because on a CPU that is the only transition that
   makes a context start running a tenant. Warp residency on an SM is decided by
   the SM's own hardware warp scheduler from a work queue; no `HRTE` is executed
   and the hypervisor is not in the loop per warp. So the rule now reaches the
   SM and the enforcing logic cannot see the property — which is exactly the
   shape C1c named as unimplementable, arrived at by extending a rule rather
   than by writing one.

**Therefore: an L1-equivalent detector for the SM is an entry condition on
un-parking the GPU program, not a launch blocker.** C2a established that no GPU
exists in either repository and that the program is parked; a rule that bars a
machine nobody is building blocks no scheduled launch. What it does do is make
the obligation visible at the moment the program restarts, which is the failure
mode the two-way scoping note above was written to prevent: the second reading's
danger was that L1 *looks* satisfied while the GPU has no equivalent, and naming
the entry condition is what stops that.

**Gated Wave-3 items:** C2c (the microreset **and** the detector, both landed as
specifications 2026-09-09), C2b (predictor invalidate), C1a/C1b
(the added clause). C2a's scoping question was gated here and is answered above.

### L2 — IOMMU default-deny

**Requirement.** Block-all at reset (`ENABLE = 1`, `BMID_BYPASS_* = 0`);
unclaimed and unknown BMIDs stay blocked; `SUPER_BYPASS` gains a **write-once
lock** cleared only by reset; the IOTLB **`GLOBAL` match bit is removed** or
made hyperprivileged-write-once; detach and teardown re-protect before the
device is released; the shared IOTLB is quota'd per BMID.

**Provenance of the five clauses is not uniform, and an implementer needs to know
which is which.** The first three are derived in §7.7 from register definitions
this task read. The last two — **detach/teardown re-protection and the per-BMID
IOTLB quota** — are inherited from
[j4-remediation-plan.md §C2](../j4-remediation-plan.md) with **no independent C0
backing**. C2d's design step owes that derivation and may argue either down.

**Ratified; mechanism narrowed** per §7.7 — "deny" is the existing miss
behaviour, so this is a reset-polarity change plus two guards, not a new state
machine. Evidence, all **`LITERATURE`** (§9's scale — named, not followed):
Thunderclap (NDSS 2019) for the coarse-mapping failure; Apple DART and Windows
Kernel DMA Protection for default-deny-from-power-on as the norm; the Linux
deferred-attach work for the boot-window class. The *in-tree* half of this item —
the reset values, `SUPER_BYPASS`, the `GLOBAL` bit — was read directly from
[iommu/hardware-spec.md](../iommu/hardware-spec.md) and is not literature.

**Launch blocker only for configurations with a tenant-influenced DMA master** —
which today means *any* pass-through device and, later, the GPU. Where no such
master exists, L2 is `N/A` and must be *recorded* as `N/A` rather than silently
skipped, because adding one device changes the answer.

**Honest cost note:** a default-deny reset means the boot path must program the
IOMMU before any DMA, which is a real bring-up cost on a board with a boot-time
DMA engine. That cost is the requirement, not an argument against it.

**Evidence required for MET.** A **negative** test per clause, because every clause
here fails silently and open. At minimum: an *unclaimed* BMID issuing a DMA read
must be blocked and must latch a fault (this is the one an implementer can
otherwise satisfy on paper — flip the polarity, add the lock, delete the global
bit, and never demonstrate that an unenumerated device actually stops); a second
write to `SUPER_BYPASS` after the lock must not take; and a detached device must
be blocked *before* the driver returns. Reset state is asserted by reading the
registers out of reset, not by reading the spec.

**Gated Wave-3 items:** C2d, C2a (GPU).

### L3 — Eager FP/vector switch or scrub on every cross-tenant switch

**Requirement.** On a cross-tenant boundary, FP and SIMD architectural state is
saved and restored **eagerly**, or scrubbed to defined values. The lazy
trap-on-first-use path may be used **within** a tenant only. A fresh context
with no saved image gets **defined** register contents, never "undefined".

**Ratified and strengthened.** §7.8 shows the current spec is not merely
LazyFP-shaped but **architecturally worse**: no speculation is needed. The
strengthening is the last sentence — the plan's bar said "eager switch or
scrub", and the concrete defect in [fpu/spec.md §7.3](../fpu/spec.md) is
specifically the *no-saved-image* branch, which an eager-save discipline alone
does not fix.

**Evidence required for MET.** A cross-tenant residue test on the FP, and separately
the SIMD, register file: tenant A writes a recognisable pattern to every
architectural FP/SIMD register, is switched out, and tenant B reads all of them
and finds defined values. **The no-saved-image branch must be its own case** —
that is the specific defect §7.8 identifies, and a test that only exercises
save/restore between two *established* owners passes without touching it.

**Specified 2026-09-09 by C1b, and still `NOT MET`.**
[fpu/spec.md §7.7](../fpu/spec.md) and [simd/spec.md §2.6.1](../simd/spec.md)
put the boundary where this item asks for it — eager across tenants, lazy within
one — and make the no-saved-image branch the *same* write as the ordinary one
rather than a second path, which is what stops a save/restore test between two
established owners from passing over it. Five residue tests are specified and
none has been run: there is no FPU and no SIMD unit in `jcore-cpu@origin/master`.

**C1c's half landed 2026-09-09, and it does not move this item either — for a
different reason from C1b's, and the difference is worth stating.** C1c found
what [j4-remediation-plan.md §C1](../j4-remediation-plan.md) called the "vertical
FP SIMD ownership hole" and it is real: [simd/spec.md §2.4](../simd/spec.md) makes
every governed FP operation a reader of `FPSCR.RM` and, under `VCSR.IEE = 1`, a
writer of `FPSCR.FLAG`, while the FPU-ownership requirement was attached to the
FP-scalar writeback of a horizontal reduction alone — so a **vertical** FP block
read and wrote `FPSCR` with `SR.FD = 1`, taking its rounding mode from and
returning its sticky flags to whichever context was parked as the FPU's owner.
[simd/spec.md §2.4.1](../simd/spec.md) closes it.

**But it is not a cross-tenant channel, and this item's boundary is the tenant.**
C1b's FP-R1 and FP-R3 already name `FPSCR` in the scrub value and apply it
unconditionally at every ownership installation, so the incoming tenant reads
`FPSCR`'s reset value whatever the outgoing tenant's SIMD did. What C1c fixes is a
wrong-rounding-mode correctness defect and a channel **between two tasks inside one
guest** — which no item of this bar requires, exactly as §10 item 7 says of the
intra-guest AnC primitive. **L3 is unchanged by it**, and stays `NOT MET` for
C1b's reason: five residue tests, nothing to run them on.

**Gated Wave-3 items:** C1b. C1c's design is done and adds no clause to this item.

### L4 — Speculation covers loads **and** the frontend

**Requirement.** Delay-on-miss remains the primary D-side mitigation. Added:
no secret-dependent speculative I-fetch, BTB, ITLB or **TSB/TLB** fill past an
unresolved branch; predictor updates at commit only, with the domain captured at
rename; degenerate-STT taint. Ship a threat model that **names residual channels
rather than claiming Spectre is closed.**

**Ratified, scope widened twice.**

- **Widening 1 — the walker.** The frontend clause must cover the **TSB walk
  armed off a speculative fetch** (§7.2). The plan's bar said "speculative
  I-fetch/BTB/ITLB"; on this design the walker is a *fourth* frontend
  transmitter and the only one that issues cacheable bus reads.
- **Widening 2 — the in-order parts.** §7.2 shows the I-side walk arm is on the
  **shipping in-order core**, so this item is not exclusively a J32-FM
  obligation.

The "name the residuals" clause is discharged by §10 of this document, and
[ooo/j32ooo-spec.md §8.2a](../ooo/j32ooo-spec.md)'s completeness sentence must
be scoped as part of C2b.

**Evidence required for MET.** Three things, and the third is the one that is
usually skipped. (a) For each transmitter — D-side fill, I-fetch, BTB/RAS, ITLB,
**and the TSB walk** — a test that a squashed path leaves no trace the same
core can measure. (b) A demonstration that each test is *non-vacuous*: red on
the unmitigated core, green after. (c) The residual list of §10 reviewed and
re-published with the implementation, since a mitigation that closes one
transmitter changes which residuals remain. A green corpus with no updated
residual list does not discharge this item's last clause.

**Widening 3 — the mechanism list splits in two, and the split is the point.**
*(C2b, 2026-09-09.)* The four mechanisms Wave 3 lists against this item are not
one workstream. **Commit-time predictor updates, a tenant-tagged BTB and
degenerate-STT taint** describe structures that exist in no repository — a
case-insensitive search of `jcore-cpu@origin/master` for `branch_pred`, `btb`,
`bimodal`, `gshare`, `ras` or `predictor` returns **no predictor and no RTL
logic** — only comments, a forward-looking PMU sentence, a test's `return_addr`
field and DRAM strobe names — and all three are **already specified**, for the design
points [decisions/0009](../decisions/0009-in-order-fgmt-is-the-default-path.md)
paused: [ooo/j32ooo-spec.md §3.2](../ooo/j32ooo-spec.md) trains every predictor
structure at commit only from a `DOM` captured at rename, tags the BTB with the
full `DOM`, and §9.4 rule 3 is the degenerate taint. C2b added no clause to any
of them. **Delayed speculative TLB/PTW fill** is the fourth, and it is the only
one that lands on hardware that exists. A wave that had spent its effort on the
first three would have produced a defence for a paused path and left the live arm
where it was — which is the shape of the status line this item carried.

**What C2b changed, and what it did not.** The I-side arm now has a rule
([mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md) **W-R1**), the frontend
prefetch gap in the paused specs has one
([ooo/j32ooo-spec.md §11.1a](../ooo/j32ooo-spec.md)), the completeness sentence
is scoped (§7.3), and the residuals are named (§10 items 11–13). No test in
clause (a) exists, no non-vacuity demonstration in clause (b) has been run, and
no RTL has changed. This item stays `NOT MET`.

**The category is different from L2, L3 and L6, and reading it as the same would
be the mistake.** Those three are unmet because the hardware to test is not
built — no IOMMU, no FPU, no store queues. **L4's transmitters are on
`origin/master` today.** The gate here is RTL nobody has written against
hardware that ships, not a specification waiting for a unit to exist. It is the
one bar item on this list whose evidence clauses (a) and (b) could begin being
discharged now, for the walk arm, with the counter **W-E1** describes.

**Gated Wave-3 items:** C2b.

### L5 — Cache isolation beyond ways

**Requirement.** Way-partitioning plus: per-tenant **replacement metadata**
(DAWG semantics — isolate hits, misses and metadata updates), per-tenant
**MSHR** reservation at the L2, memory-**bandwidth** QoS, **no cross-tenant page
deduplication**, and **privilege-gated** `ocbi`/`ocbp`/`pref` at the tenant
boundary.

**Ratified, with one claim added and one scoped.**

- **Added: the L2 MSHR pool is 4 entries, shared across banks and cores**
  ([cache/l2-spec.md §12.3](../cache/l2-spec.md)). J32-LT already partitions its
  *core-side* MSHRs (2 demand + 1 prefetch per thread,
  [ooo/j32lt-spec.md §7.4](../ooo/j32lt-spec.md)), so the "≈0 cost" evidence
  covers the core side and **not** the L2 side. The L2 pool is the one that
  spans tenants, and it is the one nobody has costed.
- **Scoped:** [cache/l2-spec.md §16.1](../cache/l2-spec.md)'s "closes the
  channel" must be narrowed to the occupancy channel (§7.6).
- The `ocbi`/`ocbp` gating matters *because* of the page-dedup clause, not
  independently: Flush+Reload needs shared memory. Deciding "no cross-tenant KSM"
  and "gate the flush ops" together is one decision, not two.

**Evidence required for MET.** Per sub-clause, since they are independent
mechanisms: a metadata test (a victim's *hits* in the attacker's ways must not
change what the attacker observes); an MSHR test at the **L2** pool, not the
core-side one (§7.6 — one tenant saturating 4 entries must not alter another's
observable miss latency beyond the reserved share); a bandwidth-QoS bound
measured, not asserted; a dedup test proving no page is shared across tenants;
and a privilege test per gated instruction. **Five mechanisms, five tests** — a
single "partitioning works" test discharges only the first.

**Gated Wave-3 items:** C2e.

### L6 — Scrub on ownership change; "undefined = previous tenant's data" is banned

**Requirement.** Store-queue buffers and the FP/SIMD register files are scrubbed
or fully restored on any ownership change. **No architectural definition
anywhere may resolve "undefined" to residual state from a previous owner.**

**Ratified; two instances added** beyond the SQ and the register files:
`movca.l`'s partially-defined L2 line, and the no-saved-image branch of the
lazy-FPU restore (§7.8). Both are user-mode-reachable.

**Two of the three are now specified away, 2026-09-09**, which leaves
**1** open `undefined` site. The store-queue instance is C1a's, and
[sq/spec.md §6.5](../sq/spec.md) replaces it: the buffer is zeroed at reset, on
burst completion and on the hyperprivileged `HSQCR` write that ends a restore,
and a guest load of the region returns zero rather than "undefined". The FP/SIMD
instance is C1b's, and [fpu/spec.md §7.7](../fpu/spec.md) with
[simd/spec.md §2.6.1](../simd/spec.md) replaces it: every architectural bit of
both files takes a defined scrub value at a change of tenant, and the word
"undefined" is withdrawn from [fpu/spec.md §7.3](../fpu/spec.md)'s restore
branch. The one that remains is
[cache/l2-spec.md §17.5](../cache/l2-spec.md)'s `movca.l` line (**C2e**).
**Specified is not met**: there is no store queue, no FPU and no SIMD unit in
`jcore-cpu@origin/master`, so the residue tests below cannot be run red, let
alone green.

The ban is a *specification* rule, not only an implementation one: a spec that
says "undefined" where the hardware will supply the previous owner's bytes has
already lost, because the implementer is entitled to do the cheap thing.
Reviewers should treat "undefined" in any tenant-visible context as a defect
until it is qualified.

**Evidence required for MET.** **This item currently has the weakest check of the
seven and the failure mode of the strongest**, which is why it gets the most
specific requirement. A scrub that silently does not happen produces no fault —
exactly what L7 says of a missing bounds check. So: a residue test per site
(store-queue buffers, FP file, SIMD file, `movca.l`'s unwritten bytes), each
written as *tenant A stores a recognisable pattern; tenant B reads and must not
see it*, and each demonstrated **red before the fix**. Guidance to reviewers —
"treat `undefined` as a defect" — is not a gate and does not discharge this.

Additionally, a grep-level check that no tenant-visible "undefined" is
reintroduced belongs in B0c's CI, because the ban is a specification rule and
specifications are where it will come back. **It is still not there**: as of
2026-09-09 `scripts/check-doc-facts.py --list-checks` names no such check, and
C1a — which had the strongest motive to write one — deliberately did not, because
the check is B0c's and a check owned by whoever happened to need it is a check
nobody maintains.

**Gated Wave-3 items:** C1a, C1b, C2e.

### L7 — The walker's data source must be hypervisor-owned (NEW)

**Requirement**, all four parts:

1. A guest's TSB is mapped **read-only** to that guest
   ([hypervisor/design-spec.md §3.8](../hypervisor/design-spec.md)).
2. Every guest `TSBBR` write is **bounds-checked, totally and without an
   off-by-one**, against that guest's allocation.
3. A **dedicated negative test** exists for each (this is L7's *evidence
   required for MET*, and the shape the six items above were retrofitted to): a
   guest writing a `TSBBR` outside its allocation, and a guest attempting to
   write its own TSB.
   [hypervisor/design-spec.md §6](../hypervisor/design-spec.md) already demands
   this and explains why — "Both properties fail together and silently; neither
   produces a fault of its own."
4. The walker's guest-observable counters at `0xFF000054` are **virtualized or
   denied**, never forwarded raw — **and `0xFF000058` with them.** *(Widened by
   C2b, 2026-09-09.)* `TLBINST` at `0xFF000058` is a second read-only counter of
   exactly this kind ([soc/p4-mmio-map.md](../soc/p4-mmio-map.md)), reporting ITLB
   and DTLB slot writes, and it is the *sharpest* of the two for this bar: it counts
   the speculative DTLB installs of §7.2 directly, and it counts slots **actually
   written**, so a skipped speculative install is absent from it and "nothing
   happened on the D side" is readable from software. That map already says a
   hypervisor may deny it "for the same guest-observability reason as `TSBCNT`" —
   **may** is the gap this part closes, since a permission is not a requirement.
   Privilege is not the boundary: P4 is unreadable to a *user* process, and the
   adversary of §1 is a guest kernel. The clause's own wording is what generalises —
   *the walker's guest-observable counters*, plural and by role — so an
   implementation that virtualizes the one address the clause used to name has met
   the letter of an older draft and not this item.

**Why this is a new bar item rather than a Wave-3 detail.** Every other item on
this list buys resistance to a *side channel*. This one is the difference
between a guest reading host physical memory and not. It dominates the list, it
was identified in [j4-remediation-plan.md §C2](../j4-remediation-plan.md) but
never lifted into the launch bar, and its merge gate has already been inverted
once (§7.5). An item whose ordering constraint has been violated in practice is
exactly the item that needs a gate rather than a note.

**Gated Wave-3 items:** the hypervisor implementation itself; C2b for part 4.

### Reverse index — arrive holding a C-number

A Wave-3 implementer is dispatched with a task ID, not a bar item. This is the
lookup in that direction, so nobody has to grep eight scattered mentions to find
which bar they must clear.

| Wave-3 task | Bar items it must satisfy | The clause most likely to be missed |
|---|---|---|
| **C1a** SQ residue *(design landed 2026-09-09; no RTL possible — see §7.8)* | **L6**, and **L1**'s added clause | The gang-switch list of [hypervisor §4.7.1](../hypervisor/hardware-spec.md) did not mention the store queue; adding the scrub without adding it to *that list* would have left L1 unmet. It is item 7 there now. The clause most likely to be missed **next** is that neither bar item moved to `MET`: there is no store-queue RTL to test |
| **C1b** eager FP/SIMD switch *(design landed 2026-09-09; no RTL possible — see §7.8)* | **L3**, **L6**, **L1**'s added clause | L3's *no-saved-image* branch — an eager save/restore between two established owners passes without touching it (§7.8). The clause most likely to be missed **next** is that the branch is not the only one: `HEDR[3]`/`HEDR[24]` delegation hands the first-use trap to the guest, so a scrub written into that handler is switched off by configuration |
| **C1c** FPSCR ownership *(design landed 2026-09-09; **the fix is above this bar, not on it** — see §8 L3)* | **L3**, and it turns out **none of L3** | That the defect is **not** cross-tenant. C1b's FP-R3 already scrubs `FPSCR`, so the exposure is between two tasks inside one guest: wrong rounding mode from the parked FPU owner's `FPSCR.RM`, sticky flags accumulated into it. The clause most likely to be missed **next** is [simd/spec.md §2.4.1](../simd/spec.md) **S-R2** — the natural optimisation is to require ownership only when `VCSR.IEE = 1`, since that is when `FPSCR` is *written*, and it leaves the `FPSCR.RM` read open in the **default** mode. The second is **S-R3**: §3.2's prefix encodes `H`/`ww`/`rrr`/`N` and nothing that says FP, so "checked at prefix decode" is unimplementable without scanning the block's governed opcodes |
| **C2a** GPU protection *(design landed 2026-09-09; no RTL possible — no GPU exists in either repo)* | **L2**, **L6**, and a scoping question against **L1** | L2 is `N/A` only while no tenant-influenced DMA master exists. The GPU *is* one, so C2a flips L2 to blocking — and C2a does **not** move L2, because L2 is about the IOMMU and the GPU's windows are inside the GPU. The clause most likely to be missed **next** is that the row's single bar item was wrong in two directions. **L6:** [simd/gpu/simd-gpu-spec.md §16.3](../simd/gpu/simd-gpu-spec.md) **G-R8** makes the tile buffer, texture cache and per-warp register files ownership-change sites, so L6 gains three *specified, unbuilt* structures; G-R7 adds no `undefined` site because it defines the blocked-access result. **L1:** **decided against C2a's mechanism on 2026-09-09 by C2c**, which owns L1 — an SM *is* a core for L1, so a two-tenant SM is out of bounds at launch independently of the windows, and C2a's windows are intra-tenant separation plus defence in depth. See §8 L1 |
| **C2b** speculation coverage *(design landed 2026-09-09; **the implementation half is dispatchable in part, which no earlier Wave-3 item was** — see §8 L4)* | **L4**, **L7** part 4 | The **TSB walk** is a frontend transmitter (§7.2), and the I-side arm is on the *in-order* core too. Also: §12's code-level trigger — making the walk uncacheable flips §7.1. The clause most likely to be missed **next** is that three of this row's four named mechanisms target structures no repository contains *and are already specified* for the paused design points, so an implementer who works the list in order builds nothing that runs; the fourth, delayed speculative TLB/PTW fill, is the whole of the live work. The second is that an abort path in `core/tlb_walk.vhd` looks like the same mitigation and is not — [mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md) **W-R2**: it closes the two installs and leaves the cacheable TSB reads, which are §7.1's observable. On **L7 part 4**, the clause named one counter address and there are two: `TLBINST` at `0xFF000058` counts the speculative DTLB installs this task is about, and it is the register a reader arriving from C2b will meet first |
| **C2c** FGMT single-tenant core + microreset *(design landed 2026-09-09; no RTL possible — there is no FGMT and no hypervisor in `jcore-cpu@origin/master`)* | **L1**, both halves | The detector — "an unenforceable rule with no detector is not a control" — and it is now [hypervisor/hardware-spec.md §4.7.2](../hypervisor/hardware-spec.md) **T-R1**–**T-R5**. The clause most likely to be missed **next** is that the item's flush half named a structure — "MSHRs" — that means two different pools, one of which (**the L2's**, shared across cores) no gang switch can ever reach and which belongs to **L5**; see §8 L1. The second is that this row's mechanism is **not** the one the plan named: `fence.t` is 2020s work with no pre-2006 prior art of its own, and what survives the [glossary.md §2](../glossary.md) test is the pre-2006 *object-reuse* shape, not the instruction. The third is that C2c's own detector is a **refusal**, not a trap, for a reason §4.1 makes concrete — a trap would clobber the `HSPC`/`HSSR` the refused entry needs |
| **C2d** IOMMU | **L2** | Two of the five clauses are inherited without C0 backing and owe a derivation (§7.7) |
| **C2e** cache isolation | **L5**, **L6** | Five mechanisms, five tests. The MSHR one must target the **L2** pool, not the core-side pool that already has evidence |
| Hypervisor (Phase 3) | **L7**, and it carries **L1**'s enforcement | L7's four parts are a single bounds-check handler's correctness; §7.5 explains why it fails silently in two directions at once |

### Bar status at the time of writing

| Item | Status | Blocking |
|---|---|---|
| L1 | **NOT MET** — rule specified; gang-switch list complete as a specification (item 7 C1a, item 8 C1b, item 9 C2c's microreset); the **detector is now specified too** ([hypervisor/hardware-spec.md §4.7.2](../hypervisor/hardware-spec.md) T-R1–T-R5) and is *specified, unbuilt* — no FGMT and no hypervisor RTL exists at `jcore-cpu@origin/master`, so T-E1 has no second thread context to place a second tenant on. **No item on the list is demonstrated.** The SM scoping question is decided (an SM *is* a core for L1) and adds an entry condition on un-parking the GPU, not a launch blocker | C2c's design is done; the RTL that builds FGMT and the hypervisor |
| L2 | **NOT MET** — reset is all-bypass, and that reset is a *specification* value: no IOMMU RTL exists in `jcore-cpu` or `jcore-soc` at `origin/master` (case-insensitive `iommu`, `bmid`: zero files). C2a's design landed and does **not** move this item — its windows sit inside the GPU, one master port down from where L2 acts | C2d |
| L3 | **NOT MET** — eager-across-tenants specified by C1b; *specified, unbuilt* — no FPU and no SIMD unit exists to run the five residue tests on. C1c's design landed and does **not** bear on this item: its defect is intra-tenant (§8 L3) | the RTL that builds an FPU |
| L4 | **NOT MET** — the I-side walk arm is now *specified* ([mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md) W-R1–W-R5, C2b) and unimplemented; the frontend rules of the paused specs are tightened but remain specified for cores that do not exist. **Not the same category as L2/L3/L6:** the transmitters are on `origin/master` today, so what is missing is RTL against shipping hardware, not hardware to test | C2b |
| L5 | **NOT MET** — way-partitioning specified; metadata, L2 MSHRs, bandwidth, KSM, flush-op gating all open | C2e |
| L6 | **NOT MET** — **1** open `undefined` site, was three; the store-queue and FP/SIMD sites are *specified, unbuilt* — the scrubs are stated and `jcore-cpu` has neither queues nor an FPU to run the residue tests on. C2a adds three more *specified, unbuilt* sites and no new `undefined` one: the GPU tile buffer, texture cache and per-warp register files ([simd/gpu/simd-gpu-spec.md §16.3](../simd/gpu/simd-gpu-spec.md) G-R8) | C2e, and the RTL that builds the queues, the FPU and the GPU |
| L7 | **NOT MET** — both preconditions absent; walker already merged. C2b widened **part 4** to a second counter (`0xFF000058`, `TLBINST`) without moving the item: the register is decoded in RTL and nothing virtualizes either address | hypervisor Phase 3 |

Seven of seven. That is the correct reading of the current state and it is not a
crisis: none of the speculative hardware exists yet, the exposure is latent, and
this is the cheapest moment in the programme to fix all of it.

---

## 9. The efficiency position, and the evidence status of every number in it

**The position is a project principle** ([j4-remediation-plan.md](../j4-remediation-plan.md),
guiding principle 5): security must not default to slowness, and for every
perf-sensitive control we find the cheapest variant that still meets the
guarantee before accepting an expensive one. This document endorses the position
and **does not endorse the numbers**, which are the load-bearing part.

The rule this project keeps having to relearn: *a number with no source is an
estimate wearing a fact's clothes.*

**Scope, stated so the table is not read as broader than it is.** What follows
classifies every quantitative claim in
[j4-remediation-plan.md §E.10 and §D.3](../j4-remediation-plan.md) — the
minimize-the-loss research pass — plus the in-tree cost figures those claims lean
on. It does **not** audit every number in every spec; that is B0b (platform tags)
and B0c (doc-vs-code). A figure absent from this table has not been cleared by
C0, it has merely not been looked at.

**The labels are document-wide, not table-local.** They apply wherever this
document leans on an outside claim — §7.3's Pensieve and Speculative Interference
citations, L1's industry-practice list, L2's Thunderclap/DART list, §10's
bandwidth figure — and not only in the table below.

| Label | Means |
|---|---|
| **SOURCED** | A citation this task followed to the primary source |
| **LITERATURE** | A citation this task did **not** follow. The source is named and plausible; that is all that is being claimed |
| **ESTIMATE** | Arithmetic or judgement, with no source |
| **STRUCTURAL** | True by construction, so no measurement can confirm or refute it — only its *residual* needs measuring |

**No row below is `SOURCED`, and that is a finding rather than an omission.**
C0 followed **zero** external citations to a primary source: every piece of
outside evidence in this document reaches it through
[j4-remediation-plan.md §E](../j4-remediation-plan.md), which is itself a
distillation of two briefings archived outside the tree. The in-tree numbers were
checked against the specs that own them, and the RTL claims against merged code —
that is what this task did verify. The literature was not. A Wave-3 reviewer
should read `LITERATURE` as "this project believes this and has not checked it",
because on this page that is exactly what it means.

| Claim | Figure | Status | What would settle it |
|---|---|---|---|
| Each mitigation costs sub-1% on this core | "~sub-1% each" | **UNSOURCED aggregate.** No in-tree measurement; it is a summary of the per-item estimates below, several of which are themselves estimates | The composite is the thing to measure, on the FPGA, on one workload — D0a |
| Delay-on-miss cost on a big OoO | −18% (Sakalis, IEEE TC 2020) | **LITERATURE, cited in-tree, not verified by C0.** The plan cites it; this task did not read the paper | Read the paper, or treat as a bound rather than a value |
| FGMT recovers the DoM cost | — | **UNMEASURED, and the specs agree.** [ooo/j32ooo-spec.md §20.5](../ooo/j32ooo-spec.md) says of delay-on-miss: "**This is a measurement, not a projection**" | D1's speculation-defense gate |
| In-order speculation shadow | "~2–6 cycles" | **CONTRADICTED IN-TREE.** Both speculative specs state a **7-cycle raw** misprediction penalty ([ooo/j32ooo-spec.md §3.2](../ooo/j32ooo-spec.md), [ooo/j32lt-spec.md §3.5](../ooo/j32lt-spec.md)); J32-OOO reaches 4 only with checkpoint recovery. The 2–6 figure has no in-tree owner | Pick one definition of "shadow" — fetch-to-resolve or resolve-to-redirect — and cite the spec that owns it |
| Eager FP/SIMD switch of the V-file | "~150–350 cycles" for the [520-byte J32 SIMD context image](../simd/spec.md) | **ESTIMATE, unsourced.** Derived from an assumed bulk-move rate with a dirty-skip; no `movmu`/`movml` throughput measurement exists in-tree | Microbenchmark on the FPGA once `movmu` exists; until then quote a range and say it is arithmetic |
| Tenant-switch scrub, write-through L1 | "~21k → ~10² cycles" | **MIXES TWO QUANTITIES, and the smaller one invites a wrong reading.** ~10² cycles is plausibly the *microreset*; but [hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md) budgets **~15k cycles per gang switch**, dominated by the incoming tenant's **cold cache**, not by the flush. Both can be true; quoting only the ~10² understates the switch by two orders of magnitude | State scrub cost and switch cost separately, always |
| A single-cycle flush pulse leaks | — | **ADOPTED AS A REQUIREMENT, 2026-09-09.** [hypervisor/hardware-spec.md §4.7.1a](../hypervisor/hardware-spec.md) constraint 4 (multi-cycle assert with observable completion) and scope classes 1–3 (miss handler, replacement state, arbiter). The claim was sourced to the post-2006 work named in the plan; what was adopted is the *design consequence*, which is cheap and whose failure mode is silent, and not the paper's numbers — see the row below | Done as a specification. T-E2 (§4.7.1b) is the measurement, and a busy count of **zero cycles** fails it rather than passing it |
| DAWG-semantics ways | "≤2%" | **LITERATURE (MICRO 2018), not verified by C0** | — |
| Per-thread MSHR reservation | "≈0" | **PARTIALLY APPLICABLE.** Established for core-side MSHRs on an in-order core; **says nothing about the 4-entry shared L2 pool**, which is the cross-tenant one (§7.6) | Model the L2 pool under a 2-tenant miss-heavy mix — D1's L2 gate |
| Tenant-tagged BTB beats full flush | "26–37%" | **LITERATURE (ARM CSV2), not verified by C0** | — |
| Taint unit fits a small FPGA core | "+17% LUT, +2% critical path" (ProSpeCT) | **LITERATURE, not verified by C0.** Note +17% LUT is *not* a small number on an 85F | ECP5 synthesis of the degenerate-taint variant only |
| L2 way-partitioning cost | "~200 gates" | **IN-TREE ESTIMATE** ([cache/l2-spec.md §16.1](../cache/l2-spec.md)), not a synthesis result | Synthesize |
| Security-mechanism area, J32-OOO / J32-LT | ~8,400 gates (3.7%) / ~15,200 (6.5%) | **IN-TREE ESTIMATES** ([ooo/j32ooo-spec.md §20.5](../ooo/j32ooo-spec.md), [ooo/j32lt-spec.md §16.5](../ooo/j32lt-spec.md)) for cores that do not exist | Synthesis, after B3 |
| Full-L2 flush / per-way flush | ~655 µs / ~82 µs | **DERIVED IN-TREE** from an assumed ~200 MB/s. Correct arithmetic on an unmeasured bandwidth | Measure SDRAM bandwidth on the ULX3S — D0a |
| Gang switch | "~15k cycles (~0.5 ms at 30 MHz)", ≤5% at a ~10 ms quantum | **IN-TREE ESTIMATE, and the tagging complaint has been withdrawn** — this cell read "platform-tagged inconsistently — 30 MHz here against the plan's ~40 MHz `[FPGA]` target". [decisions/0009](../decisions/0009-in-order-fgmt-is-the-default-path.md) retired that ~40 MHz: it is J2's measured row, and J2 has no MMU. Against [platform-baseline.md §3](../platform-baseline.md) the 30 used here is J4's CI floor, i.e. the *closer* of the two to the machine this row is about. The estimate is still an estimate | Measure under D0a; no re-tag needed |
| Full on-core scrub | "<1% perf / 0.13% area" | **LITERATURE, not verified by C0**, and **not carried into any spec**. The area figure is the one that matters for the ECP5 fit and it is quoted at two significant figures from a paper about a different core. C2c removed both figures from [j4-remediation-plan.md §E.10](../j4-remediation-plan.md) rather than annotating them ([decisions/0005](../decisions/0005-unmeasured-figures-are-removed.md)) and reproduced neither in [hypervisor/hardware-spec.md §4.7.1a](../hypervisor/hardware-spec.md) | ECP5 synthesis of the microreset — **not C2c**, which found no FGMT and no hypervisor RTL to synthesize. It is T-E2 (§4.7.1b), and it is blocked on the RTL that builds them |
| Dirty/init tracking makes an untouched save free | "~0" | **STRUCTURAL, and true by construction** — a 2-bit clean/dirty state skips a save that has nothing to save. The *residual* is what fraction of switches actually find the unit clean, which is a workload property and is unmeasured | Instrument FP/SIMD touch rate under D0a |
| Privileged `ocbi`/`ocbp` | "at ~0 perf" | **UNSOURCED, and the weakest "~0" on this list.** These are the SH-4 cache-maintenance ops the TLB-shootdown path uses ([cache/l2-spec.md §17.5](../cache/l2-spec.md)); privileging them turns each into a trap on whatever path uses them, which is not obviously free. It is free only if user-space genuinely never issues them | Count user-mode `ocbi`/`ocbp`/`pref` in a real workload before assuming zero |
| MemGuard-style bandwidth throttling | ">50% interference eliminated" | **LITERATURE, not verified by C0.** Note it is a *reduction* figure, not a bound — it does not close the channel | — |
| Hypervisor UCP epoch sizing | "+11% weighted speedup, <2 kB monitor" | **LITERATURE, not verified by C0.** A *performance* result being used to argue a security control is affordable; the security-relevant number (how much the adaptation itself leaks) is not in it | — |
| Value prediction adds ~1pp even on OoO | "+1pp" | **LITERATURE, not verified by C0** — and it is cited to justify *not* building something, which is the direction where a weak number is cheapest to accept | — |
| Gang-scheduling removes cross-tenant FGMT contention | — | **STRUCTURAL — and the strongest item on this list.** It is a placement property, not a performance estimate. It is also the one that fails silently if the scheduler is wrong — hence L1's detector clause | A test that a violating placement is detected |

**What survives, stated plainly.** The *structural* efficiency arguments —
write-through L1 means no dirty write-back to flush; gang scheduling makes
cross-tenant FGMT contention absent rather than mitigated; tagged predictors need
no flush; a short pipeline has a small shadow — are sound and do not depend on
any number. The *quantities* are estimates, and Wave 3 must not treat any of
them as a measured result. Where a Wave-3 design says "this costs under 1%", the
reviewer's question is "which row of this table, and has D0a run yet?"

---

## 10. Residual channels this design does not close

Named because L4 requires it, and because a threat model that lists only what it
defeats is marketing.

**Two kinds of entry, and conflating them would be a way of quietly lowering the
bar.** Items marked **[gated]** are *not* accepted residuals — they are verbatim
requirements of §8 and are listed here only because they are open **today**. They
leave this list when their bar item is met. Items marked **[accepted]** are
channels this design does not intend to close at launch, and a Wave-3 proposal to
close one is scope expansion, not compliance.

1. **[accepted] Issue-bandwidth / thread-selection timing.** One context's stalls appear as
   another's speed-up; the ready-thread arbiter is the mechanism, and removing it
   removes FGMT. Not mitigated; the answer is L1 (observer and victim are the
   same tenant).
2. **[gated — L5]** **L2 replacement metadata**, updated on hits across way partitions (§7.6).
3. **[gated — L5]** **L2 MSHR occupancy**, 4 entries shared chip-wide.
4. **[gated — L5]**, for the bandwidth half only; the row-buffer half is **[accepted]**. **DRAM row-buffer and bandwidth contention.** Nothing in the design addresses
   it; DRAMA is cited for ~Mbps across CPUs with no shared memory or cache
   (**`LITERATURE`**, §9's scale — the figure is quoted from
   [j4-remediation-plan.md §E.8](../j4-remediation-plan.md), not from the paper).
5. **[accepted]** **TSB set contention within a guest**, unless the guest partitions its own TSB
   ([mmu/hardware-spec.md §2.13a](../mmu/hardware-spec.md)).
6. **[accepted]** **Walker timing** — 3 reads for a way-0 hit, 5 for way 1, 4 for a both-ways
   miss ([mmu/hardware-spec.md §7.0](../mmu/hardware-spec.md)) — is a
   data-dependent hardware signal on the fast path, where the old review assumed
   a software slow path.
7. **[accepted, by omission — the uncomfortable one]** **The AnC primitive of §7.1, intra-guest.** No bar item covers it, so launch would ship it open. That is a decision this document is making by not making it, and §11 gives it an owner. **A second instance turned up on 2026-09-09 and this time it was closed anyway:** Wave-3 C1c found that a vertical FP SIMD block read and wrote another *task's* `FPSCR` inside one guest ([simd/spec.md §2.4.1](../simd/spec.md)). No bar item required the fix — L3's boundary is the tenant — and it was made because the same defect gives wrong FP results. **Two intra-guest channels found, one closed for a reason unrelated to this bar, is not a policy**, and it is the evidence that the omission above is a real gap rather than a theoretical one.
8. **[gated — L1]** **Gang-switch residue in any structure the §4.7.1 list omits.** The list is
   the control; anything absent from it is a channel. Both structures this document named left the
   omitted set on 2026-09-09 — the store-queue buffers as
   [hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md) item 7 and the FP/SIMD
   register files as item 8. The item stays gated all the same, and the reason has changed:
   **the list is a control only where its items have been demonstrated**, and none of them has
   hardware to demonstrate on. It is also still open in the direction it was written for — a
   structure nobody has thought of is absent from the list and from this sentence alike, and
   Wave-3 **C2c** found four more of them on 2026-09-09 by asking a different question: not
   *which structures leak*, which is how the list was built, but *which structures had no
   software-visible control to be reached through*, since every item on the list reached its
   structure through a control that existed for some other reason. That found core-side MSHRs,
   L1/TLB replacement-policy state, the FGMT thread-select state and the write buffer below a
   write-through L1-D, now item 9
   ([hypervisor/hardware-spec.md §4.7.1a](../hypervisor/hardware-spec.md)). The question is worth
   re-asking of any structure added later; it is not worth believing it has been asked for the
   last time.
9. **[accepted]** **Fault and exception oracles** — `EXPEVT`/`TEA`/`MMUFSR` are high-fidelity by
   design and fine within a tenant.
10. **[accepted]** **Rowhammer**, and everything physical.
11. **[accepted]** **The L1-I line filled by a wrong-path fetch**, on every core in this
    document. *(Added by C2b, 2026-09-09.)* A fetch squashed before dispatch has already
    entered `MISS1` and committed its tag — `cache/icache_ccl.vhm` has no speculation input
    at all — and the shipping L1-I is **direct-mapped**, so one line is the whole eviction set
    for its index and an observer resolves that index with no ambiguity. Unlike the walk arm
    it cannot be closed by delay, because a fetch cannot wait for the dispatch of the
    instruction it is fetching. Both mechanisms that would close it are refused elsewhere and
    C2b did not overturn either: a flush-on-switch filter cache is on
    [j4-remediation-plan.md §E.10](../j4-remediation-plan.md)'s **don't build** list, and a
    speculative fill buffer is [ooo/j32ooo-spec.md §20.7](../ooo/j32ooo-spec.md) rejection 1,
    refused on live-patent grounds. [mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md) **W-R4** names a third —
    discarding the returning line instead of committing its tag —
    and declines to adopt it until the prior-art check §20.7 requires has been done and
    **W-E1** has measured how often the case arises.
12. **[accepted]** **The I→D shadow fill's cross-structure disclosure, intra-tenant.**
    *(Added by C2b, 2026-09-09.)* An ITLB install drives a speculative DTLB install of the
    same page (§7.2), so a page that was only ever *executed* becomes D-side resident and
    D-side timing reports I-side activity. [mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md) **W-R1** removes its
    transient-execution half by removing the arm; what is left is architectural and inside one
    tenant, which is where
    **L1** puts observer and victim — the same position item 7 above takes on the AnC
    primitive, and it is listed beside it deliberately, because that is now three intra-guest
    channels rather than two.
13. **[accepted, speculative class only]** **Replacement-metadata update by a squashed
    *hitting* load.** *(Added by C2b, 2026-09-09.)* Delay-on-miss lets L1-D hits proceed
    speculatively, and a hit moves a pLRU tree
    ([ooo/j32ooo-spec.md §8.2a](../ooo/j32ooo-spec.md)). **This channel does not exist on any
    core that has been built** — the shipping L1s are direct-mapped and hold no replacement
    state — and it is distinct from item 2, which is the *same word* about a different
    mechanism: item 2 is a victim's architectural hit crossing an L2 way partition and is
    **L5**'s, this is a squashed path inside one domain and is **L4**'s. The one mechanism
    that would close it has no price in §E.10 and the decision belongs to whoever resumes the
    design point.

---

## 11. Defects found while writing this, deliberately left for later

Recorded rather than fixed, with an owner, because fixing them here would exceed
C0's remit and hide them in a large commit.

**Six rows were closed by Wave-2 B1** (2026-09-07/08) and deleted from this table
rather than struck through, since the burn-down is the point: the `ASID_TAG`
generation-nibble restatement in `bus/fabric-spec.md` and the matching one in
`ooo/j32lt-spec.md`; `TSB_SIZE_LOG`'s two ranges (see §7.1, corrected in place);
the walker's failure direction, where **fail-open is the true reading** and
[mmu/hardware-spec.md §5.0](../mmu/hardware-spec.md) now says so — §7.5's
argument was quoting the wrong half; and TLB geometry, which now has an owner
([mmu/hardware-spec.md §4.1](../mmu/hardware-spec.md), 8 ITLB / 16 DTLB) and a
code binding to the generic maps in `core/cpu.vhd`; and **L1 cache geometry**,
whose row rested on a premise that turns out to be false — `cache_index_bits` is
referenced throughout `cache_pkg.vhd`, and the row's "referenced nowhere" came
from case-sensitively grepping a case-insensitive language (see §7.1). It is now
bound as `cache.l1.index`. **The `TSBBR` bounds check is still absent** from `tlb_walk.vhd` — fail-open does not supply one — so
**L7** stands unchanged.

**One further row was closed by Wave-3 C2b** (2026-09-09) and deleted on the same
principle: [ooo/j32ooo-spec.md §8.2a](../ooo/j32ooo-spec.md)'s completeness
sentence is scoped, and the scoping turned up a second defect inside the same
sentence that the row did not know about — see §7.3. The row for
`jcore-cpu/docs/architecture/tlb.md` below is **not** closed and has grown; it is
now the implementation half of C2b.

| Defect | Owner |
|---|---|
| `jcore-cpu/docs/architecture/tlb.md §7` still claims the core is "strictly non-speculative" and that "the **software** TLB walk … removes … AnC". Both false; cross-repo. **C2b's design half read the file and the count is now four, not two** *(2026-09-09)*: the same sentence also says "no prefetcher" and "no data/target speculation", and **§4.1 of that same file calls the I→D shadow fill a "speculative install" in four places** — so the document contradicts itself across two sections, which is why the row cannot be closed by deleting a clause; the residual paragraph under it also carries the `TSB_SIZE_LOG` offset range that Wave-2 **B1** corrected in [mmu/hardware-spec.md §2.8a](../mmu/hardware-spec.md), and §1's banner still describes the walker as arriving on a branch. **This is C2b's implementation half and it is dispatchable now** — it needs no hardware, only the repository | Wave-3 **C2b**, implementation half |
| **J32-FM — the product — has no owning specification.** One glossary table cell is its entire definition, and the glossary is not authoritative | Wave-2 **B3** |
| **The guest-`ASIDR` justification has expired** — *the contradiction is corrected, the security question is not.* [hypervisor/design-spec.md §5](../hypervisor/design-spec.md) now records that `ASIDR` is the TLB **match** input on every translation (`core/cpu.vhd`, `asid => dp_mmu_regs.asidr(...)` into both TLB instances) and a TSB index input on every miss, so the "write-only staging state consulted only at `LDTLB` time" argument for leaving a guest write untrapped is void; the stale one-`LDTLB`-trap costing beside it is likewise marked. **Whether the write must now be trapped is a hypervisor-design decision B1 did not make.** | Wave-2 **B1** (doc) → **Wave-3** (decide) |
| [cache/l2-spec.md §16.1](../cache/l2-spec.md)'s "closes the channel" needs scoping to occupancy (§7.6) | Wave-3 **C2e** |
| Intra-guest AnC (§7.1) has no bar item and no owner | Wave-3, after C2b |
| The one-cycle `dp_p4_viol` window clobbers an older fault's `TEA` ([j4-wave0-status.md](../j4-wave0-status.md)) | Wave-3 follow-up, red guard first |

---

## 12. What would reopen this document

- **A second tenant is placed on a core concurrently with another**, for any
  reason — L1 is the load-bearing assumption of six other verdicts, and its
  failure re-opens all of them at once.
- **A hardware backstop for tenancy is proposed.** That would convert L1 from a
  policy to a control and change what the residuals in §10 cost.
  **This trigger fired on 2026-09-09** — Wave-3 **C2c**,
  [hypervisor/hardware-spec.md §4.7.2](../hypervisor/hardware-spec.md). It converts
  the **placement** half for the virtualized case only and leaves the **flush** half
  untouched by design:
  **T-R3** of [hypervisor/hardware-spec.md §4.7.2](../hypervisor/hardware-spec.md) scrubs nothing.
  Three cases stay policy:
  an unvirtualized multi-tenant system, which executes no `HRTE`; a hypervisor that
  issues two tenants the same `HTCR.TENANT`, which hardware cannot see; and the GPU's
  SM, which §8 L1 now rules *is* a core for this item and for which no equivalent
  exists. Re-read as: the trigger's wording asked whether hardware backs the rule, and
  the answer is now "for one of its two halves, on the deployment that ships". The
  residual costs in §10 change accordingly and item 8 there says how.
- **The OoO-vs-FGMT decision (Wave-2 B3) lands on in-order + FGMT.** §4 and §6
  are written against a speculative product; if the product stops speculating,
  the speculative column is re-derived — **not deleted**, because §7.2 shows the
  in-order class is not speculation-free either.
- **Software *or hardware* gives `ASID_TAG[15:12]` a meaning.** §7.9's verdict
  depends on the nibble being unused, not on its being reserved — **the RTL
  already carries it** through the tag compare and the index fold. So the trigger
  is a *kernel* that stops masking it just as much as an RTL change that assigns
  it, and the kernel half needs no hardware change to happen.
- **D0a produces real numbers.** §9 is a table of estimates; it should shrink
  every time the board runs.

**Code-level triggers.** The programme-level bullets above are the ones a planner
will notice. These are the ones an *implementer* will trip without noticing, and
they are listed by artifact for that reason. §7.1 is called the most consequential
re-derivation in this document, and it rests on four tree facts, **any one of
which flips it**:

| If this changes | Then | Most likely to change it |
|---|---|---|
| **The walker's TSB reads stop being cacheable** — `jcore-cpu/core/cpu.vhd`, the `TSB COHERENCY POLICY` block, currently "the walker reads through the very cache those stores go through" | §7.1's observable disappears and the AnC verdict flips **back to `N/A`**. §6's AnC row, §10 items 5 and 7, and §11's intra-guest row all move with it | **C2b — this is the most obvious AnC mitigation available**, and it would be done for that reason. It is also not free: the RTL block records that the uncached path "is not coherent with dirty dcache lines holding TSB writes" |
| **The TSB set stops being exactly one cache line** — either `mmu/hardware-spec.md §2.8`'s set size or `jcore-cpu/cache/cache_pkg.vhd`'s `cache_line_width_bits` moves | The observer gains or loses sub-line ambiguity. A *larger* line weakens the attack; a set spanning two lines strengthens it | A cache resize for area or for the L2's `L2_LINE_BYTES=64` option |
| **`tsb_ptr()` stops being XOR-separable, or its VPN half stops being GF(2)-linear** — `jcore-cpu/core/datapath_pkg.vhd` | The "recompute `g`, solve for VPN" step fails and the attack becomes a search rather than a solve. This is the *other* real mitigation, and `mmu/hardware-spec.md §2.8b` explains why it is closed to this project on prior-art grounds — **re-read that before proposing it** | Anyone re-reading §2.8a and concluding the fold should be secret |
| **The hardware walker stops being the sole TLB installer** — `jcore-cpu/core/tlb_walk.vhd` | The whole of §7.1 and half of §0 revert to the superseded review's world | A revert, or a second install path added for the hypervisor. **Checked by C2b, 2026-09-09: this trigger has not fired, and it comes closer to firing than the row suggests.** `core/cpu.vhd`'s I→D shadow fill *is* a second write of the DTLB port, described in the RTL and in `jcore-cpu/docs/architecture/tlb.md` §4.1 as a "speculative install" — but it is derived from `walk_install`, so the walker is still the only thing that decides an entry exists. A reviewer reading "a second, speculative DTLB install" without following `shadow_wr` back to its driver would report this trigger as fired. [mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md) **W-R3** makes keeping that true a rule rather than a coincidence |

And for §7.2, which is what retires the "non-speculative core" premise:

- **The I-side walk arm gains a dependence on dispatch or a squash path.**
  Today `jcore-cpu/core/cpu.vhd` arms `walk_i_miss` off a live fetch with no such
  dependence, and `core/tlb_walk.vhd` has no abort path at all. Add either and
  the in-order class stops being able to walk on a squashed fetch — which would
  be a genuine improvement, and would make §7.2, §6's in-order column and part of
  **L4** overstated rather than merely conservative. **Do not delete them; re-derive
  them**, because the *speculative* class keeps the exposure regardless.
  **This bullet says "either" and the two are not equivalent** *(C2b, 2026-09-09)*:
  [mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md) **W-R2** shows that an
  abort path closes the two TLB installs and leaves the walk's cacheable TSB
  reads — §7.1's whole observable — already issued. Only the dispatch dependence
  ([mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md) **W-R1**) is the trigger this bullet describes. An implementation that lands
  the abort path alone does **not** fire this trigger and must not be read as
  having done so.
- **`walk_i_miss` gains a dispatch term — the same event, seen from the other
  side.** When [mmu/hardware-spec.md §5.0a](../mmu/hardware-spec.md) **W-R1** lands, §10 items 12 and 13 shrink and item 11 does not, and
  **W-E1**'s counter is the evidence for clause (b) of §8 **L4**. Re-publishing
  §10 at that moment is not optional tidying; it is the third clause of that
  item.
- **A tenant-influenced DMA master is added**, which flips L2 from `N/A` to
  blocking for that configuration.
