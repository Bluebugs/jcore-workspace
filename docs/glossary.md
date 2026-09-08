# J-Core Workspace Glossary

**Status:** Living document. Update before introducing a new product point, threading mode, or memory term anywhere else in the docs.

**Audience:** Anyone reading the design docs in this workspace.

> **What this document is, and what it is not — changed 2026-08-25 by
> [decisions/0001](decisions/0001-one-authority-per-fact.md).**
>
> This is a **glossary**: it defines terms and names the spec that owns each one.
> It is authoritative on **naming** — if another doc uses a different word for the
> same thing, this document wins and the other doc is wrong.
>
> It is **not** authoritative on **values**. It carries no normative number, bit
> position, address, or encoding; where a term has one, the entry links to the
> owning spec and stops. If a value appears to be stated here anyway, the owning
> spec wins.
>
> This is a demotion from an earlier claim to be "the single source of truth",
> and it was made because that claim was false. For five weeks this file
> described a live `VFPUL` register; its SIMD context entry previously read **272 bytes**
> where [simd/spec.md](simd/spec.md) had long since said otherwise; and it
> tabulated a little-endian J2 that ships big-endian.
> The argument, and the alternative that was rejected, are in
> [decisions/0001](decisions/0001-one-authority-per-fact.md).
>
> **To look up a value, start at [fact-ownership.md](fact-ownership.md)**, which
> maps each normative constant to its one owning document and section, and is
> checked by `scripts/check-doc-facts.py`.

---

## 1. Project scope ("hosted at home")

This workspace describes a **hobbyist-hosted FPGA service**: a small fleet of ULX3S boards in a home lab, running J-Core SoC bitstreams, exposed as a remote SH4 development service to GitHub-authenticated tenants. See [jcore-ulx3s-service-plan.md](jcore-ulx3s-service-plan.md).

The platform is **not self-hosting** in the toolchain sense: the J-core runs SH4 user-space and Linux, but cross-compilation, RTL synthesis, kernel builds, and bitstream generation all run on a separate x86 developer machine. "Hosted at home" refers to the FPGA service being run by the project owner on hardware they physically own, not to the J-core developing itself.

The term "self-hosted" appears in these docs only in the Tailscale/Headscale sense (self-hosting a coordination plane); it never refers to native J-core development.

---

## 2. Prior-art policy (pre-2006)

**Every technology added to this project must be backed by published prior art predating 2006.** This is a hard requirement, not a guideline.

Practical rules:
- Each design doc MUST include a **Prior art** section citing pre-2006 sources (papers, patents that have expired, ISA manuals, textbooks, open hardware projects) for every non-trivial mechanism it introduces.
- When in doubt, cite multiple independent sources to demonstrate the idea was common knowledge before 2006.
- Acceptable sources: ISCA/MICRO/HPCA/ASPLOS papers ≤2005, Hennessy & Patterson editions through 4th (2006 in print but written earlier), SH-1/2/3/4 hardware manuals, SPARC v9 manual (1994), PowerPC architecture books (≤2005), MIPS R10000/R12000 documentation, Alpha 21264 documentation, sun4v hypervisor papers/patents (filed before 2006), AltiVec/VMX documentation, expired patents with priority dates ≤2005.
- 2006 itself is the cutoff: priority date Jan 1, 2006 or later is **not** acceptable prior art.
- If a desirable mechanism has no pre-2006 prior art, either (a) find a pre-2006 equivalent and adapt it, or (b) drop the mechanism.

This policy exists because J-Core's value proposition depends on patent freedom. The SH-1/2/3/4 patents expired before this project began. Anything we add must be similarly unencumbered.

### 2.1 How prior art is matched

Two rules, learned from screening the transient-execution mitigations in [ooo/j32ooo-spec.md §20](ooo/j32ooo-spec.md) and [ooo/j32lt-spec.md §16](ooo/j32lt-spec.md). Both cut in directions the bare pre-2006 test gets wrong.

- **Prior art matches at the level of *mechanism*, not *motivation*.** A patent claim covers structure and steps, not purpose. A pre-2006 reference that teaches the same mechanism for an unrelated reason is still prior art and still evidence of freedom to operate. Worked example: delay-on-miss reads as a 2019 security technique, but Intel US6035393 (priority 1995, expired) claims stalling a memory access "until either the dummy instruction retires, or a misprediction of a previous branch is detected" — to avoid side effects on uncacheable MMIO. Same mechanism, different reason, and it qualifies. Do not reject a mechanism because the paper you found it in is recent; look for the mechanism.
- **A pre-2006 *structure* is necessary but not sufficient when the purpose-specific *combination* is separately claimed.** Worked example in the other direction: holding a cache fill in a side buffer and promoting it later is pre-2006 (Jouppi 1990; Cray US5761706, expired; Intel US6223258, expired) — but doing so *because the load is speculative*, promoting *when it becomes non-speculative*, and clearing *on squash and domain switch* is claimed by live patents (Microsoft US11061824, priority 2019). Citing Jouppi would have satisfied this policy as written and still walked into the claim.

Practical consequence: where a mechanism's *purpose* is post-2006 even though its structure is not — which in practice means security mechanisms — the prior-art citation is necessary but a check for live claims on the purpose-specific combination is also required. The security sections of the CPU specs are currently the only place this applies.

Neither this section nor the specs that cite it constitute legal advice or a freedom-to-operate opinion. Where a finding is load-bearing for a design decision, it warrants a professional search before RTL commits.

---

## 3. Product points (CPU/SoC variants)

Family naming uses the convention: **J<width>[-<variant>]** where width is the integer-register width.

> **The `Endianness` column is gone — 2026-09-07.** It previously read "little"
> for every row, which was never true of the shipping J2. Wave-2 **B1** decided
> the question: J-Core is big-endian at every product point, owned by
> [platform-baseline.md §2](platform-baseline.md), argued in
> [decisions/0006](decisions/0006-endianness-is-big-endian.md). One answer for
> every row is not a product-point distinction, so it is a term entry (§7) and
> not a column.
>
> **The `Addr width` column and its fence are gone — 2026-09-07.** The column
> restated what the row's own name already says: by the naming convention
> above, J*N* *is* *N*-bit, so the cell was a copy of the first column. The
> J64 row additionally carried a **VA** width, which is an MMU fact this
> document does not own and now links instead
> ([mmu/design-spec.md §3.7](mmu/design-spec.md)). With both gone the region
> needs no `value-free: off` fence, and the `glossary-fence:product-table-addr-width`
> waiver row went with it — the first waiver in
> [fact-ownership.md](fact-ownership.md) to be retired rather than carried.

| Name        | ISA baseline                              | MMU                | FPU tier              | SIMD tier      | OoO | Threading   | Status        |
|-------------|-------------------------------------------|--------------------|-----------------------|----------------|-----|-------------|---------------|
| **J2**      | SH-2 + J-core ext (CAS.L, SHAD, SHLD)     | none               | Tier 0 (J2 baseline)  | none           | no  | none        | shipping (see `jcore-cpu/`) |
| **J2-MT2x2**| J2 + dual-core + MSI L1 coherence         | none               | Tier 0                | none           | no  | FGMT 2-way  | proposal      |
| **J3**      | SH-2 + MMU                                | yes (SH-4 model)   | Tier 0                | none           | no  | none        | roadmap       |
| **J32**     | SH-2 + MMU + (optional FPU/SIMD coprocs)  | yes                | Tier 1 (SH4-complete) | Tier 0+1       | no  | none        | planned       |
| **J32-OOO** | J32 + 2-wide out-of-order                 | yes                | Tier 1                | Tier 0+1       | yes | FGMT 2-way  | spec'd        |
| **J32-LT**  | J32 + 2-wide light OoO (no rename)        | yes                | Tier 1                | Tier 0+1       | light | FGMT 4-way (barrel) | spec'd        |
| **J32-FM**  | J32-OOO + full memory subsystem (L2 v2)   | yes                | Tier 1+2 (hyp-aware)  | Tier 0+1+2     | yes | FGMT 2-way  | target        |
| **J64**     | J32-FM + wider integer regs (per §3 naming) + COMPAT | yes ([VA width](mmu/design-spec.md)) | Tier 1+2              | Tier 0+1+2+3   | yes | FGMT 2-way  | research      |


Notes:
- "Tier 0/1/2/3" refer to FPU and SIMD spec tiers; see those specs for tier contents.
- J32-OOO is the spec name used in [docs/ooo/j32ooo-spec.md](ooo/j32ooo-spec.md); product-shipped variant is J32-FM once memory subsystem is reconciled.
- **J32-LT** ([docs/ooo/j32lt-spec.md](ooo/j32lt-spec.md)) is a *sibling* of J32-OOO, not a successor. "Light OoO" means in-order issue with out-of-order completion: a future-file RAT maps architectural registers to ROB slots, but there is **no register renaming**, no physical register file, and no issue queue. It targets throughput per joule via 4 thread contexts rather than single-thread latency via renaming. Neither variant supersedes the other; they are separate design points at comparable area.
- J64 OoO is out of scope for the ULX3S 85F (would consume the whole device).

---

## 4. Threading

This project uses **one and only one** threading term: **FGMT**.

- **FGMT — Fine-Grained Multi-Threading.** Each cycle the front-end selects one hardware thread context and issues instructions from it. On an *N*-wide machine the selected thread fills all *N* issue slots or leaves the surplus empty; slots are never filled from a second thread in the same cycle (that would be SMT — see below). Prior art: CDC 6600 PPU barrel processor (1964); Tera MTA (1990); SPARC T1 "Niagara" specification material pre-2006.
  - **FGMT 2-way** (J2-MT2x2, J32-OOO, J32-FM, J64): each cycle picks one of two thread contexts. Selection is a ready-thread arbiter.
  - **FGMT 4-way, barrel** (J32-LT): the thread count equals the front-end depth ahead of issue, so each front-end stage holds a different thread each cycle and thread identity is *positional* rather than tagged. Selection degenerates to a counter while all threads are ready. See [ooo/j32lt-spec.md §3.1](ooo/j32lt-spec.md). Pure barrels collapse single-thread throughput to `1/depth`, so J32-LT applies a **period floor** — a thread is granted a fetch slot no more often than once every `max(k, 2)` cycles for *k* ready threads — which costs the positional-identity property below `k = 4`. Prior art for the barrel proper: CDC 6600 peripheral processors (Thornton 1964).
- "SMT" (Simultaneous Multi-Threading, where multiple threads issue in the *same* cycle) is **not used** in this project. Earlier drafts mixed the terms; FGMT is now the only correct term. Update old text on sight.
- "MT", "barrel", "hardware threads" are colloquial; FGMT is the spec term.

**Security-domain status of co-resident contexts.** On every FGMT product point in this project, the contexts of one core **share the L1 caches, the L2, the TLB, the TSB and the branch-predictor arrays**, and are therefore **one security domain** unless a product point explicitly says otherwise. Stated as an allocation rule: **a physical core is the unit of tenant allocation at any instant** — every context of a core belongs to the same tenant (the same VM under the hypervisor extension, the same trust domain otherwise) for as long as that tenant is resident, and a tenant needing one vCPU is given a whole core. Under virtualization the hypervisor enforces this at admission time ([hypervisor/hardware-spec.md §4.7](hypervisor/hardware-spec.md)); otherwise the OS scheduler does.

A core may be shared between tenants **over time** by **gang switching** — all contexts change tenant together, with the predictor/L1/TLB invalidation sequence of [hypervisor/hardware-spec.md §4.7.1](hypervisor/hardware-spec.md) at the boundary. Prior art: Ousterhout, "Scheduling Techniques for Concurrent Systems" (ICDCS 1982).

The capacity consequence is direct and should be quoted rather than re-derived: an *N*-context core **runs** one tenant with up to *N* vCPUs, not *N* tenants. FGMT buys vCPUs per tenant; gang scheduling buys tenants per board over time; neither buys concurrently-running tenants per core.

Note that the shared L2 sits below all of this — a single set of arrays serves every core ([cache/l2-spec.md §2](cache/l2-spec.md)) — so tenants on *different* cores share it regardless of placement. That channel is closed by way-partitioning ([cache/l2-spec.md §16.1](cache/l2-spec.md)), not by any core-granular rule. This is a property of the threading model, not of any one core: see [ooo/j32ooo-spec.md §20.3](ooo/j32ooo-spec.md) and [ooo/j32lt-spec.md §16.3](ooo/j32lt-spec.md) for what the hardware does and does not provide, and Percival, *Cache Missing for Fun and Profit* (BSDCan 2005) for the pre-2006 demonstration of what shared-cache co-residency leaks.

A *thread context* is a complete architectural register set (R0–R15, SR, GBR, VBR, PC, FPU regs if present) plus an ASID. *N* FGMT contexts per core means *N* complete register sets in hardware, selected per cycle. On implementations with an MMU, the live `ASID_TAG` register (**ASIDR**, §5) is part of the context and is therefore replicated per thread, with the TLB compare selecting by thread ID — see [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md).

---

## 5. Memory and address-space terms

- **ASID — Address Space Identifier.** Identifies which page-table tree an address belongs to. Stored (per-CPU current) in the dedicated **ASIDR** register and in each TLB entry's tag, as part of the composite `ASID_TAG` (see next entry). *Widths and the ASID space available for hypervisor partitioning: [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md).* Prior art: SH-4 hardware manual (Renesas, pre-2006); MIPS R4000 user manual (1991).
- **ASID_TAG.** The full per-TLB-entry identifier compared on every translation. The low bits are the ASID proper; the top bits **used to be** a generation discriminator and are now always zero (retired 2026-08-25 — see [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md)). Held in the dedicated **ASIDR** register, separate from PTEH — modeled on UltraSPARC `PRIMARY_CONTEXT` (sun4u, 1995). The split keeps the full SH-4-plus-PageMask page-size range available even with the wider tag; PTEH stays VPN-only. *Field widths: [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md). Whether ASIDR has a P4 MMIO alias, and at what address: [soc/p4-mmio-map.md §3.2](soc/p4-mmio-map.md).*
- **ASIDR — Address Space Identifier Register.** New dedicated control register holding the current `ASID_TAG`. Written by the kernel at context switch (`LDC Rn, ASIDR`). Hardware reads it on every TLB lookup and on LDTLB. *Width, layout, the read alias, and per-thread-context replication: [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md).*
- **VMID — Virtual Machine Identifier.** Reserved in earlier MMU/IOMMU drafts; **removed from the hardware spec** (this project achieves hypervisor isolation via ASID partitioning, see hypervisor docs). Do not introduce VMID in new specs.
- **BMID — Bus Master Identifier.** Tag attached to every bus transaction by the fabric, identifying the initiating master (CPU core, DMA engine, peripheral). Used by the IOMMU to look up the correct page table. Set by the bus fabric at the master port; not software-writable from the initiator. The authoritative definition — assignment policy, immutability guarantee, reserved values, partitioning for hypervisor guests — lives in [bus/fabric-spec.md §4](bus/fabric-spec.md). Prior art: ARM AMBA AXI `AxID` (≤2003); PCI Requester ID (PCI 2.0, 1993).
- **P4.** The SH-4 architectural privileged-MMIO region. All on-chip control registers live here. Its lowest quarter is allocated to the **Store Queue (SQ)** (see below), of which only the low part is actually SQ-decoded ([sq/spec.md §2](sq/spec.md)); the remainder of that quarter is reserved. The decoded range is *not* MMIO in the ordinary sense, and it is the exact extent of the guest-mode P4 trap carve-out ([hypervisor/hardware-spec.md §4.4.3](hypervisor/hardware-spec.md)) — everything else in P4, reserved SQ range included, traps for a guest. *Region bounds and every register offset within P4 are governed by the canonical [soc/p4-mmio-map.md](soc/p4-mmio-map.md).* Prior art: SH-4 hardware manual (Renesas, 1998).
- **SH-4 guest.** An SH-4 image running under the J-Core hypervisor rather than on bare metal. The only way SH-4/Dreamcast software runs on any J-Core core: bare-metal J4 is SH-2 plus the J-Core extensions plus the SH-4 privileged architecture, not an SH-4 at the instruction-set level. Which SH-4 surfaces are emulated by the VMM, which run natively on the hardware and must therefore decode as SH-4, and which are unsupported, are governed by [sh4-guest-model.md](sh4-guest-model.md). Prior art: IBM VM/370 (1972); Popek & Goldberg, CACM (1974).
- **Store Queue (SQ).** A pair of write-combining buffers at the base of P4, drained by `PREF` into a physical address formed from `QACR0`/`QACR1`. The primary bulk-store path on SH-4 systems. *Buffer count, buffer size and addresses: [sq/spec.md §2](sq/spec.md).* Prior art: SH-4 hardware manual (Renesas, 1998).
- **Emulation aperture.** A physical-address window (`HEMUB`/`HEMUM`) tested *after* TLB translation; a guest access resolving into it raises an emulated-MMIO trap to the hypervisor instead of reaching the bus. Replaces a per-PTE "emulated" bit, which the J-Core PTE has no room for. Prior art: IBM S/370 storage keys (1970) as the nearest pre-2006 physical-address-indexed access-control test.
- **Complete-on-resume.** The J-Core emulated-MMIO trap model: hardware latches the faulting access's address, size, direction, and destination register, and performs the register writeback when the hypervisor executes `HRTE`. The hypervisor never decodes the faulting instruction. Prior art: IBM SIE interception controls (1980/1983).
- **Generation counter.** **Retired 2026-08-25** — the kernel no longer carries a generation discriminator in `ASID_TAG`; see [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md) and [mmu/design-spec.md §3.5](mmu/design-spec.md) for the supersede note and the merged commit. The entry formerly read: *"Top 4 bits of `ASID_TAG`; incremented on full-ASID-space wraparound to logically invalidate stale TLB entries without a full flush."* Prior art, retained for the idea: MIPS R4000 ASID generation scheme (1991); Linux mm/context.c circa 2.4 (2001).
- **Lazy TLB shootdown.** Cross-CPU TLB invalidation performed via cache-coherent PTE updates rather than an IPI. Requires coherent L1-D / L2. Prior art: Sun UltraSPARC III hardware-walked TLB invalidate (2001); Linux ARM lazy TLB tracking (pre-2006).
- **SR.FD — FPU disable.** SH-4 standard. When set, any FPU instruction raises FPU-disabled exception. Enables the OS / hypervisor lazy-FPU-context-switch idiom (set on context-out, trap on first use, save/restore only the previous and incoming owners, clear). On Tier 2 (hypervisor) FPU implementations the trap is reported as `EXC_FPU_DISABLED`, delegatable via HEDR. *Bit position, EXPEVT value, HEDR bit, and the context-image size: [fpu/spec.md §6.3, §7](fpu/spec.md).* Prior art: SH-4 hardware manual (1998); Intel `CR0.TS` (i486, 1990); 4.4BSD lazy-FP (1996).
- **SR.VD — SIMD disable.** J-Core SIMD extension; SR.FD's direct analogue for the V0..V15 + P0 + VCSR state. When set, any SIMD-touching instruction or control-register access raises SIMD-disabled exception. Enables the OS lazy-SIMD-context-switch idiom and avoids the SIMD save/restore for tasks that never touch SIMD (~95% of typical Linux processes). On Tier 2 (hypervisor) implementations the trap is reported as `EXC_SIMD_DISABLED`, delegatable via HEDR. *Bit position, EXPEVT value, HEDR bit, and the context-image size: [simd/spec.md §2.5, §2.6](simd/spec.md).* Prior art: PowerPC G4 AltiVec `MSR.VEC` (1999); SH-4 `SR.FD` (1998); Apple Mac OS X lazy AltiVec save.

---

## 6. Coherence and atomicity

- **MESI / MSI.** Standard cache-coherence protocols. The L2 v2 spec ([cache/l2-spec.md §7](cache/l2-spec.md)) selects **MSI**, with the L2 acting as the directory / snoop filter; MESI's E state is rejected on FPGA-cost grounds. Prior art: Papamarcos & Patel ISCA 1984 (MSI/Illinois); SGI Origin 2000 (1996); Hennessy & Patterson 3rd ed. (2003).
- **CAS.L.** J-Core's compare-and-swap instruction. Semantics: atomic memory exchange conditional on equality with a register value. Implemented via **per-L2-line lock** on J32-OOO / J32-FM / J64; see [cache/l2-spec.md §6](cache/l2-spec.md). Prior art: IBM System/370 `CS` instruction (1970); SPARC v9 `CASA` over UltraSPARC II MESI (1997).
- **Bus lock.** Legacy J-core atomicity mechanism whereby a CAS holds the bus exclusive for the duration of the read-modify-write. Acceptable for single-core J2 (no L2 present); superseded by L2-line-lock in J32-OOO and J32-FM. Preserved verbatim in `cache/dcache_ccl.vhm` for the J2 path; see [cache/l2-spec.md §6.4](cache/l2-spec.md) for the compatibility statement.

---

## 7. Platform terms

- **AIC2 — Advanced Interrupt Controller, version 2.** The J-Core per-CPU interrupt controller; in-tree at `jcore-soc/components/misc/aic2.vhm`. Three-tier convention spec at [aic/aic2-spec.md](aic/aic2-spec.md): T0 = baseline (per-source enable/pending/priority/target, IRL output, `aic_com` IPI bus); T1 = FGMT-aware per-(core, thread) delivery; T2 = hypervisor virtualization (per-source `GUEST_OWNED`, vCPU targeting, `jcore_vintc` paravirt ABI). Prior art: SH-4 INTC (1998), OpenPIC (1995), Intel APIC (1993), sun4v interrupt cookies (2005).
- **ULX3S.** Open-source FPGA development board based on Lattice ECP5 LFE5U-85F-6BG381C. Project target hardware. https://radiona.org/ulx3s/
- **J4.** The `jcore-cpu` **build variant** for the in-order core with the
  privileged architecture and the MMU — `variants.toml` `[j4]`, generic
  `PRIV_ARCH = true`, config `core/cpu_config_j4.vhd`, and the `j4`/`j4c` legs
  of the `synth-cpu` matrix. It is a *bitstream configuration*, and it is what
  every MMU, priv-arch and hypervisor document in this workspace is written
  against. **J32** (§3) is a *product point*: a row in the product table with an
  FPU tier, a SIMD tier and a threading model. The two are different kinds of
  name and neither is a synonym for the other. *This entry previously read "J4 —
  earlier drafts mentioned J4 alongside J32; treated as a synonym for J32
  baseline in spec text. Prefer J32. Update on sight." That deprecation was
  never acted on and should not have been: `jcore-cpu@master` names the variant
  J4 in its authoritative variant table, this workspace's own plans are titled
  "J4", and "update on sight" would have renamed a build target after a product.*
- **Endianness.** The byte order of the core, and of the kernel and userspace built for it. One answer for the whole product line, not a per-product-point property — which is why it is a term here and not a column in §3. Owned by [platform-baseline.md §2](platform-baseline.md); the decision and the alternative it rejects are [decisions/0006](decisions/0006-endianness-is-big-endian.md). Not to be confused with SIMD **lane** order, which is a separate convention owned by [simd/spec.md §2.2](simd/spec.md), or with a **guest's data byte order**, which J-Core is to make a per-guest mode owned by the hypervisor while instruction fetch stays big-endian, per [sh4-guest-model.md §3.1](sh4-guest-model.md).
- **MCP.** Model Context Protocol server exposed by the platform's management track, allowing Claude Code to drive board control, bitstream lifecycle, and log queries programmatically. See ULX3S plan §7.
- **Tier 0 / Tier 1 / Tier 1.5.** Service tiers exposed to tenants: Tier 0 = QEMU SH4 user-mode on VPS; Tier 1 = real-hardware paravirtualized SH4 VM on J-core; Tier 1.5 = richer J-core profiles (OoO, dual-core+FGMT, FPU, SIMD). Distinct from FPU/SIMD tiers in §3 above.
- **sshpiperd.** SSH connection router on the OVH VPS. Tenants SSH to it, it routes to per-tenant board VMs over WireGuard.
- **jcore-mgmt.** REST API + database for the management plane (boards, bitstreams, reservations).

---

## 8. Sibling repositories (context)

| Repo                | Contents                                                                |
|---------------------|-------------------------------------------------------------------------|
| `jcore-cpu/`        | J2 (SH-2) CPU core VHDL, simulation, decoder generator                  |
| `jcore-soc/`        | SoC integration (memory controller, peripherals, top-level)             |
| `jcore-jx/`         | (project-specific; see repo)                                            |
| `jcore-workspace/`  | **This repo.** Design docs and roadmaps for new subsystems.             |
| `qemu/`             | QEMU fork with SH4 and J-core extensions                                |
| `gcc-sh-monitor/`   | GCC for SH targets                                                      |
| `j2-llvm/`          | LLVM with J2 backend                                                    |
| `aasm/`             | Assembler                                                               |
| `sh-insns/`         | SH instruction database                                                 |
| `arboriginal/`      | (project-specific)                                                      |

When a doc refers to "existing hardware," it almost always means the J2 implementation in `jcore-cpu/`. New blocks (MMU, IOMMU, hypervisor, L2 v2, FPU Tier 1, SIMD, OoO, FGMT) extend or replace pieces of that baseline.

---

## 9. Terms intentionally NOT used

- **SMT** — superseded by FGMT.
- **VMID** — removed from hardware (see §5).
- **VFPUL** — **retired 2026-07-17 by [simd/spec.md §2.3](simd/spec.md)**; see
  [simd/spec.md Appendix B](simd/spec.md) for why. FP scalar results now land
  directly in the SH-4 `FR`/`DR` file; there is no SIMD-side FP scalar register,
  and the four `FMOV.VS`/`FMOV.VD` boundary instructions that existed only to
  bridge it are deleted. Do not reintroduce the name.
  *This glossary carried a full entry describing the register as live for five
  weeks after it was retired — one of the three staleness findings behind
  [decisions/0001](decisions/0001-one-authority-per-fact.md).*
- **"Self-hosted" meaning native compilation** — see §1; this platform does not natively develop itself.
- **"SH-Compact"** — used once in [ooo/j32ooo-spec.md](ooo/j32ooo-spec.md) for "SH-2 + J-core extensions." Prefer "SH-2 + J-core ext" or simply "J32 ISA baseline" depending on context.
