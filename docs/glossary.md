# J-Core Workspace Glossary

**Status:** Living document. Update before introducing a new product point, threading mode, or memory term anywhere else in the docs.

**Audience:** Anyone reading the design docs in this workspace. This document is the single source of truth for naming. If another doc disagrees with this one, this one wins and the other doc is wrong.

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

---

## 3. Product points (CPU/SoC variants)

Family naming uses the convention: **J<width>[-<variant>]** where width is the integer-register width.

| Name        | ISA baseline                              | MMU                | FPU tier              | SIMD tier      | OoO | Threading   | Addr width | Endianness | Status        |
|-------------|-------------------------------------------|--------------------|-----------------------|----------------|-----|-------------|------------|------------|---------------|
| **J2**      | SH-2 + J-core ext (CAS.L, SHAD, SHLD)     | none               | Tier 0 (J2 baseline)  | none           | no  | none        | 32-bit     | little     | shipping (see `jcore-cpu/`) |
| **J2-MT2x2**| J2 + dual-core + MSI L1 coherence         | none               | Tier 0                | none           | no  | FGMT 2-way  | 32-bit     | little     | proposal      |
| **J3**      | SH-2 + MMU                                | yes (SH-4 model)   | Tier 0                | none           | no  | none        | 32-bit     | little     | roadmap       |
| **J32**     | SH-2 + MMU + (optional FPU/SIMD coprocs)  | yes                | Tier 1 (SH4-complete) | Tier 0+1       | no  | none        | 32-bit     | little     | planned       |
| **J32-OOO** | J32 + 2-wide out-of-order                 | yes                | Tier 1                | Tier 0+1       | yes | FGMT 2-way  | 32-bit     | little     | spec'd        |
| **J32-FM**  | J32-OOO + full memory subsystem (L2 v2)   | yes                | Tier 1+2 (hyp-aware)  | Tier 0+1+2     | yes | FGMT 2-way  | 32-bit     | little     | target        |
| **J64**     | J32-FM + 64-bit integer regs + COMPAT     | yes (48-bit VA)    | Tier 1+2              | Tier 0+1+2+3   | yes | FGMT 2-way  | 64-bit     | little     | research      |

Notes:
- "Tier 0/1/2/3" refer to FPU and SIMD spec tiers; see those specs for tier contents.
- J32-OOO is the spec name used in [docs/ooo/j32ooo-spec.md](ooo/j32ooo-spec.md); product-shipped variant is J32-FM once memory subsystem is reconciled.
- J64 OoO is out of scope for the ULX3S 85F (would consume the whole device).

---

## 4. Threading

This project uses **one and only one** threading term: **FGMT**.

- **FGMT — Fine-Grained Multi-Threading.** Each cycle the front-end selects one hardware thread context and issues instructions from it. With FGMT 2-way on a 2-wide OoO machine, each cycle picks one of two thread contexts and fills the 2 issue slots from that thread's ready instructions. Prior art: CDC 6600 PPU barrel processor (1964); Tera MTA (1990); SPARC T1 "Niagara" specification material pre-2006.
- "SMT" (Simultaneous Multi-Threading, where multiple threads issue in the *same* cycle) is **not used** in this project. Earlier drafts mixed the terms; FGMT is now the only correct term. Update old text on sight.
- "MT", "barrel", "hardware threads" are colloquial; FGMT is the spec term.

A *thread context* is a complete architectural register set (R0–R15, SR, GBR, VBR, PC, FPU regs if present) plus an ASID. Two FGMT contexts per core means two complete register sets in hardware, selected per cycle.

---

## 5. Memory and address-space terms

- **ASID — Address Space Identifier.** Identifies which page-table tree an address belongs to. **Width: 12 bits** (4096 ASIDs). Stored (per-CPU current) in the dedicated **ASIDR** register and in each TLB entry's tag, combined with a 4-bit generation counter into a single 16-bit `ASID_TAG` (see next entry). Prior art: SH-4 hardware manual (Renesas, pre-2006); MIPS R4000 user manual (1991).
- **ASID_TAG.** The full per-TLB-entry identifier compared on every translation: low 12 bits are the ASID proper, top 4 bits are the generation discriminator (lets recycled ASIDs be distinguished in the TLB after rollover without a full flush — Linux mm/context.c pattern, pre-2006). Total field width: **16 bits**. Held in the dedicated **ASIDR** register (P4 `0xFF000024`), separate from PTEH — modeled on UltraSPARC `PRIMARY_CONTEXT` (sun4u, 1995). The split keeps the full SH-4-plus-PageMask page-size range (4 KB through 1 GB) available even with the wider 16-bit ASID_TAG; PTEH stays VPN-only. The total ASID space available for hypervisor partitioning is **4096** (12-bit ASID); the generation discriminator does not enlarge the ASID space, only the TLB-distinguishability of recycled values.
- **ASIDR — Address Space Identifier Register.** New dedicated control register holding the current 16-bit `ASID_TAG`. Written by the kernel at context switch (`LDC Rn, ASIDR`). Hardware reads it on every TLB lookup and on LDTLB. See [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md).
- **VMID — Virtual Machine Identifier.** Reserved in earlier MMU/IOMMU drafts; **removed from the hardware spec** (this project achieves hypervisor isolation via ASID partitioning, see hypervisor docs). Do not introduce VMID in new specs.
- **BMID — Bus Master Identifier.** Tag attached to every bus transaction by the fabric, identifying the initiating master (CPU core, DMA engine, peripheral). Used by the IOMMU to look up the correct page table. Set by the bus fabric at the master port; not software-writable from the initiator. **Width: 8 bits**, with `0x00` and `0xFF` reserved. The authoritative definition — assignment policy, immutability guarantee, reserved values, partitioning for hypervisor guests — lives in [bus/fabric-spec.md §4](bus/fabric-spec.md). Prior art: ARM AMBA AXI `AxID` (≤2003); PCI Requester ID (PCI 2.0, 1993).
- **P4.** The SH-4 architectural privileged-MMIO region (`0xE0000000`–`0xFFFFFFFF`). All on-chip control registers live here. Allocation is governed by the canonical [soc/p4-mmio-map.md](soc/p4-mmio-map.md). Prior art: SH-4 hardware manual (Renesas, 1998).
- **Generation counter.** Top 4 bits of `ASID_TAG`; incremented on full-ASID-space wraparound to logically invalidate stale TLB entries without a full flush. Prior art: MIPS R4000 ASID generation scheme (1991); Linux mm/context.c circa 2.4 (2001).
- **Lazy TLB shootdown.** Cross-CPU TLB invalidation performed via cache-coherent PTE updates rather than an IPI. Requires coherent L1-D / L2. Prior art: Sun UltraSPARC III hardware-walked TLB invalidate (2001); Linux ARM lazy TLB tracking (pre-2006).

---

## 6. Coherence and atomicity

- **MESI / MSI.** Standard cache-coherence protocols. The L2 v2 spec ([cache/l2-spec.md §7](cache/l2-spec.md)) selects **MSI**, with the L2 acting as the directory / snoop filter; MESI's E state is rejected on FPGA-cost grounds. Prior art: Papamarcos & Patel ISCA 1984 (MSI/Illinois); SGI Origin 2000 (1996); Hennessy & Patterson 3rd ed. (2003).
- **CAS.L.** J-Core's compare-and-swap instruction. Semantics: atomic memory exchange conditional on equality with a register value. Implemented via **per-L2-line lock** on J32-OOO / J32-FM / J64; see [cache/l2-spec.md §6](cache/l2-spec.md). Prior art: IBM System/370 `CS` instruction (1970); SPARC v9 `CASA` over UltraSPARC II MESI (1997).
- **Bus lock.** Legacy J-core atomicity mechanism whereby a CAS holds the bus exclusive for the duration of the read-modify-write. Acceptable for single-core J2 (no L2 present); superseded by L2-line-lock in J32-OOO and J32-FM. Preserved verbatim in `cache/dcache_ccl.vhm` for the J2 path; see [cache/l2-spec.md §6.4](cache/l2-spec.md) for the compatibility statement.

---

## 7. Platform terms

- **AIC2 — Advanced Interrupt Controller, version 2.** The J-Core per-CPU interrupt controller; in-tree at `jcore-soc/components/misc/aic2.vhm`. Three-tier convention spec at [aic/aic2-spec.md](aic/aic2-spec.md): T0 = baseline (per-source enable/pending/priority/target, IRL output, `aic_com` IPI bus); T1 = FGMT-aware per-(core, thread) delivery; T2 = hypervisor virtualization (per-source `GUEST_OWNED`, vCPU targeting, `jcore_vintc` paravirt ABI). Prior art: SH-4 INTC (1998), OpenPIC (1995), Intel APIC (1993), sun4v interrupt cookies (2005).
- **ULX3S.** Open-source FPGA development board based on Lattice ECP5 LFE5U-85F-6BG381C. Project target hardware. https://radiona.org/ulx3s/
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
- **"Self-hosted" meaning native compilation** — see §1; this platform does not natively develop itself.
- **J4** — earlier drafts mentioned J4 alongside J32; treated as a synonym for J32 baseline in spec text. Prefer J32. Update on sight.
- **"SH-Compact"** — used once in [ooo/j32ooo-spec.md](ooo/j32ooo-spec.md) for "SH-2 + J-core extensions." Prefer "SH-2 + J-core ext" or simply "J32 ISA baseline" depending on context.
