# J-core J4 MMU — Multi-Tenant Security Review

> **SUPERSEDED BY [security/threat-model.md](../security/threat-model.md) — 2026-08-25.**
> C0 is done, and the threat model is that document, not this one. **§0's verdict
> and §1's applicability matrix are void**: they reason from *"the walker is
> software"* and from an adversary who is an unprivileged user process. The walker
> is hardware, and the adversary is a **guest kernel on a shared core**.
> §2–§5 remain as the finding-by-finding record — read them for *that*, with the
> three re-derivations in the next paragraph applied.
>
> **What C0 re-derived here, so no reader inherits an answer from this file:**
> [threat-model.md §7.1](../security/threat-model.md) reverses the **AnC** row
> from `NO` to *applies*;
> [§7.4](../security/threat-model.md) rebuilds the `ASID_TAG`-truncation argument
> on a collision demonstration rather than an entropy count;
> [§7.9](../security/threat-model.md) re-derives **S-I3** on the two merged legs
> that replaced the generation nibble; and
> [§7.2](../security/threat-model.md) retires the "non-speculative core"
> premise that half of §1's `NO` verdicts rested on.
>
> **The eight unstructured `RESOLVED` markers in §2 and §3 were reformatted by C0**
> into [decisions/0002](../decisions/0002-supersede-convention.md) grammar and are
> now verified mechanically by `scripts/check-doc-facts.py` on every run. Each
> previously cited a *branch* (`mmu/hardening-si457`, `mmu/asid-generation`) that
> no longer exists on `origin`; each now cites an artifact on the integration
> branch. This file's `legacy-marker` waiver row in
> [fact-ownership.md](../fact-ownership.md) is retired with them.
>
> **What changed, and where it is merged.**
> **RESOLVED 2026-08-25 — jcore-cpu@master: "rtl(mmu): the hardware walker is the sole TLB installer".**
> The companion kernel change is
> **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: stop installing TLB entries from software".**
> A TLB miss is now serviced by an RTL FSM (`core/tlb_walk.vhd`, `tsb_ways => 2`)
> that probes the TSB over the memory system and installs the entry with no
> exception at all. Software reaches `VBR + 0x400` ([hardware-spec.md §5.0, §7.0](hardware-spec.md))
> only when that walk fails, and then walks the page tables to fill the TSB.
>
> **Why this is a security change and not a wording change.** Three of §1's
> verdicts rested on the absent walker. B0a flagged them; C0 has now settled all
> three, and the answers are in the threat model, not here:
>
> - **AnC / ASLR⊕Cache, rated "NO — no hardware walker, no page-table caches".**
>   **Answered: the verdict is reversed.** There is now a hardware walker, and its
>   TSB reads go through the cache hierarchy deliberately — the RTL states the
>   policy in its own words:
>   **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/cpu.vhd` containing `TSB COHERENCY POLICY`.**
>   A *TSB* walk does meet AnC's requirement, and on one axis exceeds it: a TSB set
>   is exactly one cache line, so an observer resolves the whole set index with no
>   sub-line ambiguity. See
>   [threat-model.md §7.1](../security/threat-model.md) for the derivation.
> - **"Software miss-handler timing is a J4-specific surface"** (TLB row) now
>   describes only the slow path. The fast path's timing is hardware and
>   data-dependent on TSB way hit/miss (3 reads for way 0, 5 for way 1, 4 for a
>   both-ways miss — [hardware-spec.md §7.0](hardware-spec.md)). Carried into
>   [threat-model.md §10](../security/threat-model.md) as residual channel 6.
> - **The "Software-TLB-specific" family** (LDTLB non-atomicity, PTE-read→install
>   TOCTOU) is re-scoped: the hardware install is atomic, but the TSB *fill* is
>   still software, and its store order is now load-bearing
>   ([hardware-spec.md §7.0](hardware-spec.md), "TSB store order").
>
> B0a also noted that §2's threat model assumes a single tenant and a trusted
> kernel. It does, and that is why C0 wrote a separate document rather than
> editing this one.

**Date:** 2026-06-27 · **Scope:** the SH-4-class J4 MMU (software-loaded TLB, ASID isolation, SH-4 privileged architecture, VIPT→PIPT L1 caches — the transition is complete and PIPT is the shipped organisation, [hardware-spec.md §4.1a](hardware-spec.md)) as a multi-tenant isolation boundary. Covers (1) the modern MMU/TLB/cache attack landscape and its applicability to this design, (2) a security review of the specification, (3) a security review of the RTL implementation, and (4) verification that design, implementation, and **tests** line up — with the concrete test/hardening gaps.

---

## 0. Executive summary

**The single most important property of this design is that the core is in-order, single-issue, strictly non-speculative, with no out-of-order execution, no data/target speculation, and no prefetcher.** This neutralizes — *by construction, not by mitigation* — the entire transient-execution attack family and the hardware-page-table-walker cache attack:

> Meltdown, Spectre v1/v2/v4, L1TF/Foreshadow, MDS (RIDL/ZombieLoad/Fallout/TAA), Retbleed, Downfall/GDS, Inception/SRSO, **and AnC ("ASLR⊕Cache")** all DO-NOT-APPLY. There is no transient window in which an architecturally-forbidden access executes, and there is no hardware walker whose page-table-cache footprint can be timed.

The residual attack surface is therefore almost entirely:
1. **Software correctness in the TLB/ASID/permission/exception path** (the walker is software, so these are *your* code), and
2. **Conventional time-sliced timing/covert channels** on the shared L1 caches and TLB (bounded by single-hart time-slicing — no SMT concurrency — and a low clock), and
3. **Rowhammer** — the one physical threat the good CPU properties do nothing for; gated by the SDRAM part and the physical allocator, not the core.

**Verdict on the current state:** the implementation enforces the core isolation primitives correctly and is, in several places, *more* correct than the written spec. The gaps are: (a) the **specification under-specifies** permission semantics and states no threat model; (b) a few **implementation hardening** opportunities (faulting-load defense-in-depth); and (c) the **test suite has a real hole around ASID/global/revocation isolation** — every existing guard uses ASID 0 and never proves a revoked or cross-tenant mapping is unusable. None of (a)/(b)/(c) is a confirmed live exploit today, but each is exactly where a future regression would silently become a cross-tenant break.

---

## 1. Attack landscape → applicability matrix

Rated against *this* design (not generic x86). Full catalog in the appendix; this is the decision-grade summary.

| Family | Representative attacks | Applies to J4? | Why |
|---|---|---|---|
| Transient / speculative | Meltdown, Spectre v1/2/4, L1TF, MDS, Retbleed, Downfall, Inception | **NO** (whole family) | In-order, non-speculative: the forbidden access is never performed; no transient window. |
| HW page-table-walker cache | AnC / ASLR⊕Cache | **NO** | No hardware walker, no page-table caches; translation is a software handler + TLB. |
| TLB side/covert channel | TLBleed, TLB occupancy, miss-timing | **PARTIAL** | No SMT → no concurrent observation; only time-sliced cross-context, closed by flush-on-switch. Software miss-handler timing is a J4-specific surface. |
| Cache side-channel | Prime+Probe, Flush+Reload, Evict+Time | **PARTIAL** | Shared L1 contention survives even under PIPT; bounded by time-slicing. PIPT *removes* VIPT synonym leakage (security-positive) — and PIPT is now established against the RTL rather than assumed, [hardware-spec.md §4.1a](hardware-spec.md). No user `clflush`. |
| Page-table / translation | TLB-desync (stale entry), permission-bit confusion, controlled-channel | **APPLIES** | Software-TLB: invalidation correctness and U/W/X decode are entirely yours. **Top correctness risk.** |
| ASID / context tag | missing flush on recycle, global-bit misuse, ASID confusion | **APPLIES** | Cross-tenant read/write if ASID recycle/global hygiene is wrong. **#1 risk.** |
| Rowhammer / physical | Rowhammer, RAMBleed, Half-Double | **PARTIAL** | DRAM-dependent; non-ECC SDR on ULX3S is comparatively favorable; MMU's role is physical placement. Core properties don't help here. |
| Fault / exception channel | EXPEVT/TEA leak, fault-timing, double-fault | **APPLIES (low/correctness)** | High-fidelity fault oracle by design; fine in trusted-kernel model. Nested-fault hygiene is a real correctness area. |
| Software-TLB-specific | LDTLB non-atomicity, PTE-read→install TOCTOU, NRU covert channel | **APPLIES** | Distinctive to a software walker. Continue the M4 atomic-install direction. |

> **The matrix above is void — 2026-08-25.** It is left in place as the record of
> what was believed, per
> [decisions/0002](../decisions/0002-supersede-convention.md)'s rule that a
> superseded section is never silently deleted. **Do not read a row out of it.**
> The live matrix is
> [security/threat-model.md §6](../security/threat-model.md), which rates every
> family *per core class* — because two of this table's four `NO` verdicts are
> inherited from the in-order J4 RTL onto a product that speculates, and the
> third (AnC) is reversed outright.

**Top risks for THIS design, ranked:** (1) ASID/flush/global correctness, (2) permission enforcement + stale-entry/TLB-desync invalidation, (3) nested-fault/exception hygiene, (4) software-handler atomicity & TOCTOU, (5) time-sliced timing channels (document + optional hardening), (6) Rowhammer (memory-controller/allocator scope), (7) EXPEVT/TEA hygiene.

---

## 2. Specification review (findings)

The spec gets the *plumbing* right (all MMU registers/instructions privileged; ASID-generation tagging; single-save/P1 handler discipline; store re-execution; safe reset state). Gaps:

| # | Sev | Finding | Security consequence | Fix |
|---|---|---|---|---|
| S-C1 | Critical | `hardware-spec §4.3` defines the TLB **match** as tag-only (`VALID && VPN && (G||ASID)`). The **permission check** (U/W/X vs access type vs MD) that raises IPROT/DPROT is **never normatively specified**. | A conformant impl could hit-on-tag and return PA with *no* permission enforcement. (Our RTL does enforce — so this is a spec hole, not an impl hole, but it leaves the core isolation rule unwritten.) | Add a normative "Permission check" section enumerating the predicate per access type and the MD interaction. – Resolved by SP0 (2026-07-10) |
| S-C2 | Critical | Privileged (MD=1) bypass rules over translated pages are unspecified — can the kernel execute a user (U=1) page (SMEP), write a W=0 page, etc.? | Undefined kernel-mode permission semantics in the TCB; divergent/insecure impls. (Current RTL lacks SMEP; kernel still honors X and W. **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/tlb.vhd` containing `SMEP: kernel fetch of user page`.** SMEP is enforced in RTL and is the decided target ([design-spec.md §6.2](design-spec.md)) — kernel fetch of a U=1 page raises IPROT; RTL enforcement + `mmusmep.S` land in the jcore-cpu stream, see Task 6. SMAP-equivalent remains a documented future item via an `ASI_AIUP`-style uaccess mechanism; kernel may still read/write U=1 pages today.) | State the MD=1 rules explicitly; decide SMEP/SMAP-equivalent policy for the multi-tenant goal. **DONE** — see design-spec.md §6.2. – Resolved by SP0 (2026-07-10) |
| S-C3 | Critical | No threat model / isolation-guarantee section anywhere. | No yardstick to tell a bug from intended behavior; side-channel posture undefined. | Add threat model: TCB = kernel; adversary = unprivileged tenant; guaranteed properties + explicit non-guarantees (timing channels, DMA/IOMMU, Rowhammer). – Resolved by SP0 (2026-07-10) |
| S-I1 | Important | `LDTLB.R` (spec, "has a delay slot") vs `LDTLB.RN` (decode TOML, opcode 0x0078, "NO delay slot"). | A handler written to the spec's delay-slot framing silently mis-executes on the no-delay-slot impl. | Reconcile to one name/semantics across all docs + TOML (impl is authoritative: no delay slot). – Resolved by SP0 (2026-07-10) |
| S-I2 | Important | `design-spec §4.1/§4.3` says the ASID is compared against **PTEH**; architecture/RTL compare **ASIDR**. | If implemented per design-spec, the context tag would change every miss → ASID isolation broken. (Our RTL correctly uses ASIDR.) | Correct design-spec to `ASIDR`. – Resolved by SP0 (2026-07-10) |
| S-I3 | Important | Stale-TSB rejection relies on a **4-bit** generation discriminator; spec claims entries are "naturally rejected." | After 16 ASID-generation wraps, a stale TSB slot can false-hit and be installed → cross-tenant translation. | **HISTORICAL 2026-07-17.** Generation was threaded into `ASID_TAG` by `set_asid()`; kernel rebuilds TSB on `gen_low` wrap via `jcore_tsb_flush_on_generation()`, ensuring stale-TSB rejection is a real generation-tagged guarantee (exact for single-core; on SMP the TSB-zero-on-wrap follows `local_flush_tlb_all`'s local-only scope, revisited when jcore MMU-SMP lands). **The resolution above has itself been superseded — 2026-08-25.** The generation nibble no longer exists: **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: retire the ASID generation nibble"** deleted `ASID_TAG[15:12]`, `jcore_tsb_flush_on_generation()` and its stub, on the grounds that `local_flush_tlb_all()` already zeroes the TSB on *every* version wrap and per-CPU TSBs removed the cross-CPU sharing the nibble protected. `ASID_TAG` stays 16 bits in RTL with the top nibble always zero. The **finding** S-I3 is therefore closed by a different mechanism than the one recorded here; C0 must re-derive it rather than inherit this row. |
| S-I4 | Important | No hardware double-fault protection; re-entry gated on `SR.RB`, fault-while-RB=1 silently overwrites SPC/SSR. | No hardware backstop; a handler-path fault corrupts saved context rather than trapping. | **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/cpu.vhd` containing `event_i_gated.cmd <= RESET_CPU`.** Any exception taken while RB=1 (exception context live) is redirected to the defined register-model-free Reset-CPU entry instead of clobbering SPC/SSR. Design note: jcore has SR.BL and sets it on entry, but the SW-TLB handlers are non-reentrant by design (they run untranslated in P1 and TLB faults are suppressed at RB=1 — proven by `mmunest.S`), so RB=1 is the "in a handler / blocked" indicator and "any exception while RB=1 → reset" is the correct policy; adopting full SH-4 `SR.BL` reentrancy is a documented, deferred future option. **Part 1** (2026-07-17): async Interrupt/Error + nested General-Illegal, via a synthesized RESET_CPU on cpu.vhd's `g_dblflt` at the illegal_instr/event *dispatch* point (guard `mmudblflt.S`); RB=1⇒MD=1 assertion added. **Part 2 / S-I4b** (2026-07-18): the two residuals — a nested **TRAPA** and a **Slot-Illegal in a delay slot** — extend the *same dispatch point* (key insight: the double-fault must be injected at the exception-dispatch decision, not at the downstream SSR-save where the harm lands — by then `next_op` has already committed to the handler vector). Fix: `g_dblflt` adds a TRAPA-opcode term (`if_dr(15:8)=0xC3`, since TRAPA is a normal_op invisible to `illegal_instr`); `decode_core.vhm` adds a highest-priority `next_op` arm that accepts an injected RESET_CPU even in a delay slot (MMU_ARCH-gated → j1/j2 byte-identical). Guards `mmunest_trapa.S` + `mmunest_slotill.S` (both RED on base, GREEN after). |
| S-I5 | Important | Multiple-TLB-match -> "behavior undefined," no hardware guard. | A duplicate-entry kernel bug yields undefined PA selection (possibly another tenant's frame). | **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/tlb.vhd` containing `multihit`.** LDTLB **dedups** on install (reuses the matching VPN+ASID slot in place, SH-4 replace semantics), so a benign re-install of a resident page -- e.g. a Linux permission/dirty-bit upgrade on a write fault -- can never manufacture a duplicate; any residual multiple-match (reachable only via page-size aliasing) is detected (sticky flag over the 32-entry scan) and dispatched to the defined non-recoverable General-Illegal exception (EXPEVT=0x180), never a silent PA pick. Guard mmumultihit.S (dedup + aliasing multi-hit). |
| S-I6 | Important | Accessed/Referenced bit used by the C-walker and NRU is **undefined** in the PTEL layout. | Undefined bit could collide with a permission bit; NRU keyed on an unspecified bit is divergent. | Allocate/document the Accessed bit; reconcile the flag lists. – Resolved by SP0 (2026-07-10) |
| S-I7 | Important | No stated invariant that the **global bit must never be set on tenant pages**. | One mis-set G on a tenant mapping = global cross-tenant disclosure, no hardware guard. | **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/tlb.vhd` containing `entry.global = '1' and entry.u = '1'`.** A global user page (G=1 && U=1) faults at lookup on both I- and D-side (folded into the protection check), so it can never grant an access. Guard mmuglobal.S. |
| S-M1..6 | Minor | DPROT_R/W share EXPEVT 0x0C0 (vector distinguishes); IMASK-on-entry doc mismatch; side-channel surface unaddressed (tie to C3); ASID-0 reserve-vs-recycle open; PTEU/PAE wide-frame note; safe reset state (positive). | — | Documentation/clarity. |

---

## 3. Implementation review (findings)

**Confirmed correct (defenses present):** all MMU instructions privileged (user access traps); valid-gated match (reset/flushed entries never hit); atomic single-cycle LDTLB install; full 16-bit ASID compare with global-OR; G sourced only from privileged `ptel(2)`; protection raises an exception **and** faulting **stores are demoted to reads at the external bus** so memory is never mutated; PIPT relocation ([hardware-spec.md §4.1a](hardware-spec.md)) strictly gated on `tlb_*_hit='1'` and downstream of the lookup; C-bit faithfully routes cacheability (a tenant cannot force-cache an uncacheable page); bit-11 opcode pinning prevents TLB-nibble aliasing. Permission enforcement is complete across I-fetch/load/store and the user (MD=0) cases — and is **well tested** by `mmufault` (W=0→DPROT_W, X=0→IPROT in user mode, U=0→DPROT_R in user mode, plus the three miss classes, each asserting exception + EXPEVT + TEA).

| # | Sev | Finding (file:line) | Consequence | Fix |
|---|---|---|---|---|
| H-I1 | Important | **STALE bit (`PTEL[1]`) is loaded but never enforced.** `tlb.vhd:142` writes `ram(idx).stale`; the I/D lookup match+prot logic (`tlb.vhd:46-58, 77-89`) never reads `entry.stale`. | If software uses STALE as a soft-invalidate marker, the hardware still matches and grants the old translation — a revoked mapping stays live. | **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/tlb.vhd` containing `entry.stale = '0'`.** Enforce was chosen: both I- and D-side lookup match conditions in `core/tlb.vhd` now require `entry.stale='0'`, so a STALE entry stops matching (a soft-invalidate revocation primitive). Guards `mmustale.S` + `mmuremap.S`. |
| H-I2 | Important | **Faulting loads are not bus-suppressed** (only stores are demoted). `d_store_faulting` asserts only for `wr=1` (`cpu.vhd:157-160`). A protection-violating load (`hit=1, prot=1`) is issued to the relocated PA; isolation then rests **entirely** on the downstream precise-exception writeback squash (M8 `we_wb`). | Single point of failure: a regression in the writeback squash turns into a cross-tenant read with no defense-in-depth. (Not a confirmed leak today — squash is in place and guards are green.) | Mirror the store treatment: suppress `rd`/`en` for any `d_at_translated and (hit=0 or prot=1)` read. (Decision needed.) |
| H-M1 | Minor | **No multiple-hit detection.** Both lookups iterate all 32 entries and let the **last** match win (`tlb.vhd:46-59, 77-90`); no multi-hit exception (real SH-4 raises one). | A duplicate VPN+ASID install yields highest-index (possibly more-permissive) PA. Software-discipline issue today. | **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/tlb.vhd` containing `multihit`.** Closed by S-I5: multi-hit detector implemented, sticky flag over 32-entry scan, dispatches to General-Illegal (EXPEVT=0x180). Guard mmumultihit.S. |
| H-M2 | Minor | **Dirty bit (`PTEL[4]`) not enforced** — store to a writable-but-clean (D=0) page succeeds with no initial-write exception. | Removes a CoW/dirty-tracking primitive an OS may expect. Not an isolation break. | Enforce D for first-write fault if CoW is desired. |
| H-M3 | Minor | **TLB faults globally suppressed while `SR.RB=1`** (`cpu.vhd:298,309`). Safe only because user code can't set RB and the handler is trusted; fragile under any future RB-reaches-untrusted-code path. | Defense-in-depth gap. | **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `core/cpu.vhd` containing `event_i_gated.cmd <= RESET_CPU`.** Closed by S-I4: RB=1⇒MD=1 invariant assertion added; non-TLB exceptions while RB=1 redirect to Reset-CPU instead of overwriting SPC/SSR. Guard mmudblflt.S. |

---

## 4. Design ↔ implementation ↔ test alignment

**Design ↔ implementation:** they substantially agree, and where they diverge **the implementation is the more-correct side** (it uses ASIDR not PTEH for the ASID tag; it has no delay slot for LDTLB.RN; it enforces U/W/X). The spec contradictions S-I1/S-I2 are *documentation* defects to fix against the impl, not impl bugs.

**Test coverage vs the applicable threats** — this is the actionable hole:

| Applicable threat | Enforced in RTL? | Covered by a test? | Gap |
|---|---|---|---|
| Permission U/W/X (incl. user MD=0) | ✅ | ✅ `mmufault` (6 classes) | none — strength |
| Privileged-instruction / MMU-reg trap | ✅ | ✅ `privmode`, `mmuguard`, `mmureg` | none |
| Store-miss doesn't bypass protection | ✅ | ✅ `mmustore` | none |
| Fault model EXPEVT/TEA/vectors | ✅ | ✅ `mmufault` | none |
| SR/bank state on exception entry | ✅ | ✅ `mmusr` | none |
| Address relocation (VA→PA) | ✅ | ✅ `mmureloc`/`if`/`bp` | none |
| **ASID isolation** (entry under ASID A not usable under ASID B) | ✅ (RTL match) | ✅ `mmuasid.S` (cross-ASID fault + global-hit + generation tagging) | RESOLVED |
| **Global-bit** semantics (G hits across ASIDs; G must not be on user pages) | ✅ match / ✅ LDTLB guard S-I7 | ✅ `mmuglobal.S` | RESOLVED |
| **Revocation / TLB-desync** (remap or invalidate VA → old PA must fault) | ✅ via TI flush / STALE soft-invalidate | ✅ `mmuremap.S` (STALE-revoke then remap VA→PA2; proves PA1 no longer served) | RESOLVED |
| **STALE-bit invalidation** | ✅ enforced (H-I1: `entry.stale='0'` in both match conditions) | ✅ `mmustale.S`, `mmuremap.S` | RESOLVED |
| **Multiple-hit** behavior | ✅ detector (H-M1 resolved) | ✅ `mmumultihit.S` | RESOLVED |
| **Nested fault** (fault inside the miss handler) | ✅ any exception while RB=1 → Reset-CPU (S-I4/S-I4b) | ✅ `mmudblflt.S` (general-illegal), `mmunest_trapa.S` (TRAPA), `mmunest_slotill.S` (slot-illegal), `mmunest.S` (TLB-fault suppression) | RESOLVED |
| Timing/covert channels (Prime+Probe, NRU, miss-timing) | n/a (accept/ document) | ❌ | out of unit-test scope; document residual |
| Rowhammer | n/a (memory controller) | ❌ | out of scope; SDRAM-controller/allocator |

---

## 5. Recommendations

### 5a. New security guard tests (highest value — closes the isolation test hole)
1. **`mmuasid.S`** — install VPN→PPN under ASIDR=A; set ASIDR=B; prove the same VA **faults** (DMISS, no cross-ASID hit). Then prove a **global** (G=1) entry installed under A **still hits** under B. Non-vacuous by construction (flip to G=0 → must fault).
2. **`mmuglobal.S`** (or folded into `mmuasid`) — G-bit cross-ASID visibility + (if S-I7 HW guard is added) that `G=1 && U=1` is rejected at LDTLB.
3. **`mmuremap.S`** (TLB-desync / revocation) — map VA→PA1, read it; TI-flush (or remap VA→PA2); prove the old PA1 content is no longer returned for VA (entry re-walked / faults). Proves revocation actually revokes.
4. **`mmustale.S`** — install an entry with STALE=1; prove the access **faults**. *This test FAILS on current RTL* — it is the RED guard for hardening H-I1 (enforce STALE) or the documentation that STALE is a no-op (then delete the field).
5. **`mmumultihit.S`** — install two entries with the same VPN+ASID but different permissions; document/assert the resolution (RED guard for H-M1 if we add a detector).
6. **`mmunest.S`** — take a TLB fault whose handler itself touches an unmapped page (nested fault); assert SPC/SSR/bank integrity and clean resumption (exercises S-I4 / Family 7).

### 5b. RTL hardening (each needs a yes/no decision — changes behavior)
- **H-I1 STALE:** enforce `entry.stale='0'` in match, **or** remove the field. (Recommend: enforce — it's a cheap, real revocation primitive and the field already exists.)
- **H-I2 faulting-load demote:** add bus-level suppression of faulting/protection-violating reads for defense-in-depth. (Recommend: yes — symmetry with the store path, low cost.)
- **S-I7 / H-M1:** reject `G=1 && U=1` at LDTLB and/or add a multi-hit detector. (Optional; defense-in-depth.)

### 5c. Specification fixes (documentation)
- Add the threat model (S-C3), the normative permission-check rule (S-C1) and MD-bypass policy (S-C2).
- Reconcile LDTLB.R/RN delay-slot (S-I1), PTEH→ASIDR (S-I2), the Accessed bit (S-I6), and the global-bit invariant (S-I7).

### 5d. Document residuals (non-guarantees)
- Time-sliced Prime+Probe / TLB-occupancy / deterministic-NRU / data-dependent miss-handler timing: bounded by single-hart, no SMT; mitigations = flush L1+TLB on context switch (perf cost), constant-time miss handler, C=0 pages for secrets.
- Rowhammer: SDRAM-controller + physical-allocator scope; non-ECC SDR is comparatively favorable.

---

## Appendix — full attack catalog
(See the attack-research section;每 family rated APPLIES / PARTIAL / DOES-NOT-APPLY with mechanism + reference. Key references: TLBleed USENIX'18; AnC NDSS'17; Controlled-channel S&P'15; Flush+Reload USENIX'14; Prime+Scope CCS'21; RAMBleed S&P'20; Rowhammer ISCA'14 + ZenHammer/RISC-H 2024.)
