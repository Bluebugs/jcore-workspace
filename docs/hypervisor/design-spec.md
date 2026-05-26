# J-Core Hypervisor Extension Design Specification (Phase 3)

**Status:** Draft  
**Scope:** Hypervisor mode and guest virtualization for J-Core CPUs  
**Audience:** Hardware architects, kernel developers, hypervisor developers  
**Prerequisites:** Phase 1 MMU spec, Phase 2 IOMMU spec

---

## 1. Goals

Add hardware-assisted virtualization to the J-Core CPU family while:

- Preserving the strict pre-2006 prior-art constraint that has driven the project
- Reusing the Phase 1 MMU and Phase 2 IOMMU primitives without changes
- Supporting both unmodified and paravirtualized guests
- Keeping hardware additions minimal (under 200 LUTs per core)
- Providing a clean upgrade path: a J-Core variant without virtualization remains a strict subset

Non-goals:

- Hardware-walked nested page tables (post-2006 invention; AMD NPT 2007, Intel EPT 2008)
- VMID-tagged TLB / VPID-style identifier in hardware (post-2006: Intel VPID 2008, ARM VMID 2010)
- Two-stage automatic translation at LDTLB time (post-2006 architectural pattern)
- Live migration between physical machines (out of scope for embedded J-Core targets)

## 2. Prior Art

The design draws directly from three pre-2006 hardware-assisted virtualization architectures, listed in order of relevance:

**Sun sun4v / UltraSPARC T1 (Niagara), November 14, 2005.** The primary reference. Sun4v established the model of a software-loaded TLB combined with a hyperprivileged execution mode, with guests calling hypercalls to manage their own address space. UltraSPARC T1 was open-sourced as OpenSPARC, making the full architecture publicly auditable. The sun4v MMU API (`hv_mmu_*` hypercalls) and the hyperprivileged state (`HPSTATE`) are direct inspirations. Sun4v's choice to translate "virtual addresses" to "real addresses" (with the hypervisor managing real-to-physical) is the conceptual basis for our guest address space model.

**IBM SIE (Start Interpretive Execution), 1980 (System/370-XA on the 3081), refined through 1983 and again in ESA/390.** Established the model of "interpretive execution" — a guest runs natively but with hypervisor-mediated handling of certain operations, configured via the SIE descriptor and its interception controls. Our trap delegation register (HEDR) is the modern equivalent of the SIE interception bitmap.

**PowerPC hypervisor mode (PowerPC AS architecture, ~1997; PowerPC Book III v2.01, December 2003).** Established the `MSR[HV]` privileged bit and the `hrfid` instruction for hypervisor-to-supervisor returns. Used shadow page tables, not hardware nested paging. Our SR.HPRIV bit and HRTE instruction follow this pattern.

All three architectures pre-date the 2006 cutoff comfortably. Post-2006 innovations explicitly avoided: AMD NPT (2007), Intel EPT (2008), Intel VPID (2008), ARM VMID (2010), RISC-V H-extension (2021).

## 3. Design Choices

### 3.1 Hyperprivileged mode

**Decision:** Add a single SR bit, `SR.HPRIV`, defining a third privilege level above supervisor. When `SR.HPRIV=1`, the CPU is in hyperprivileged mode and can configure the hypervisor's view of the system. When `SR.HPRIV=0 && SR.MD=1`, the CPU is in supervisor mode (which may be a guest kernel or a non-virtualized kernel; the two are indistinguishable from the CPU's perspective). When `SR.HPRIV=0 && SR.MD=0`, the CPU is in user mode.

**Rationale:** Direct port of PowerPC `MSR[HV]` (1997, fully documented in 2003) and sun4v's `HPSTATE.HPRIV` (2005). One bit, three modes, well-understood lineage. The arrangement preserves Phase 1 binary compatibility: a kernel that doesn't set SR.HPRIV never enters hyperprivileged mode and runs exactly as Phase 1 specified.

### 3.2 No hardware nested translation

**Decision:** The TLB lookup function is unchanged from Phase 1. No second-stage cache, no VMID match, no real-to-physical hardware walker. Guest translations are pre-resolved by the hypervisor (in software) and installed in the TLB as if they were ordinary host translations.

**Rationale:** Hardware nested paging is a post-2006 invention. Pre-2006 hypervisors (sun4v, PowerPC HV, Intel VT-x v1) used shadow page tables maintained in software. The performance penalty was acceptable for the workloads of the era and is acceptable for J-Core's embedded targets today. Crucially, this means **the TLB hardware does not change between Phase 1 and Phase 3.** A J-Core implementation without hypervisor support runs Phase 3 binaries (in supervisor mode) without modification.

### 3.3 Guest sees Real Addresses

**Decision:** Following sun4v, a guest's view of the address space is divided into Virtual Addresses (VAs, owned by guest) and Real Addresses (RAs, what the guest believes are physical). The hypervisor maps RA to actual host Physical Addresses (HPAs). When a guest constructs a PTE for installation in the TLB, the PTE contains an RFN (Real Frame Number), not an HPN.

**Rationale:** This is the conceptual contract sun4v established. The guest builds its page tables in the same way an OS always has. The hypervisor maintains a per-guest RA-to-HPA map and uses it to fill in the actual HPN when installing a TLB entry. The guest never sees an HPN, can never construct one, and therefore cannot escape isolation.

### 3.4 All guest TLB writes mediated by hypervisor

**Decision:** When `SR.HPRIV=0` and a guest attempts LDTLB or LDTLB.R, the operation traps to the hyperprivileged trap vector. The hypervisor reads the guest's PTEH/PTEL, performs RA-to-HPA translation, and writes the real TLB entry.

**Rationale:** This is sun4v's exact model. The cost is a trap per TLB write, mitigated by:
- Per-guest TSB caching (hypervisor pre-populates entries the guest can refer to without walking page tables)
- Permanent mappings for hot pages, never demapped (hv_mmu_map_perm_addr equivalent)
- Tight trap handler implementation (target: <40 cycles per LDTLB trap)

This is slower than the G-TLB design I had originally sketched, but it's strictly pre-2006 prior art and demonstrably production-viable (Niagara servers ran Solaris this way at 1.0-1.4 GHz for years).

### 3.5 Trap delegation via HEDR

**Decision:** Add a new control register `HEDR` (Hypervisor Exception Delegation Register) as a bitmap. Each bit corresponds to an exception type; if set, the exception delivers to the supervisor (guest); if clear, it delivers to the hyperprivileged trap vector.

**Rationale:** Mirrors IBM SIE's interception controls (1980-83) and sun4v's hypervisor exception handling model. The hypervisor configures HEDR at guest-creation time to control which exceptions it wants to intercept versus delegate. Typical delegation: TLB misses and syscalls go to the guest; LDTLB writes, certain privileged instruction accesses, and external interrupts go to the hypervisor.

### 3.6 Hypercall via HCALL instruction

**Decision:** Add a new instruction `HCALL` that traps to the hyperprivileged trap vector. By convention, the hypercall code is passed in R0 and arguments in R1-R7.

**Rationale:** Sun4v used `ta` (trap-always) with a specific trap number for hypercalls. PowerPC used `sc` with LEV=1. We add a distinct mnemonic for clarity and to leave TRAPA's behavior unchanged (TRAPA continues to deliver to the guest supervisor, as it always has).

### 3.7 Reserved bits become hypervisor-allocated context

**Decision:** The 8-bit "VMID" field reserved in Phase 1 TLB tag layouts (and Phase 2 IOTLB tag layouts) is **not activated as a separate hardware field**. Instead, the hypervisor uses the existing 12-bit ASID_TAG space (and 8-bit BMID space for IOMMU) and allocates ranges to guests. From hardware's perspective, there is no VMID — only ASIDs and BMIDs. From software's perspective, the hypervisor partitions these spaces.

**Rationale:** This is sun4v's actual approach. The hardware has no VMID field; the hypervisor allocates "contexts" globally and gives ranges to guests, ensuring isolation by allocation policy. The advantage: zero hardware additions for guest tagging, and Phase 1/2 specs remain bit-compatible with Phase 3.

Concretely, if a J-Core SoC supports up to 16 guests (a reasonable target for embedded virtualization), the hypervisor reserves 4 bits of the 12-bit ASID as "guest identity" and gives each guest 256 ASIDs. The TLB just sees ASIDs; it doesn't know about the partitioning.

This means the reserved VMID bits in Phase 1/2 specs become available for future extensions (e.g., expanded ASID space, or true VMID activation in a Phase 4 variant if patent landscape changes).

### 3.8 Per-guest TSB managed by hypervisor

**Decision:** Each guest has its own TSB, allocated and managed by the hypervisor. The hypervisor populates the TSB with pre-translated entries (already containing HPAs) as part of handling guest hypercalls. The guest's TLB miss handler reads from this TSB on miss; on TSB hit, it constructs a PTEL with the HPA from the TSB entry and executes LDTLB.R, which traps to the hypervisor. The hypervisor verifies the LDTLB matches a TSB entry it wrote, installs in TLB.

**Rationale:** Sun4v's TSB registration API (`hv_mmu_tsb_ctx0`, `hv_mmu_tsb_ctxnon0`) is the precedent. The TSB hot path remains fast (no page-table walk in the guest), and the verification step on LDTLB is a quick cryptographic-cookie or pointer-range check.

## 4. Architecture Overview

### 4.1 Privilege model

```
SR.HPRIV    SR.MD    Mode                Description
--------    -----    -----------------   ---------------------------------------
   0          0      U (user)            Application code; host or guest
   0          1      S (supervisor)      Guest kernel or non-virt host kernel
   1          1      HS (hyperprivileged) Hypervisor
   1          0      undefined           Illegal; raises hyp-mode trap
```

A J-Core CPU without Phase 3 support has `SR.HPRIV` hardwired to 0. Software that tries to set HPRIV (via LDC SR) on such a CPU sees the bit ignored. This preserves binary compatibility.

### 4.2 Address space model

```
                  +------------------+
   guest VA  ---->|  guest's        |
                  |  page tables    |  (guest owns)
                  |  (VA -> RA)     |
                  +------------------+
                          |
                          v
                  Guest's "real address" (RA)
                          |
                          v
                  +------------------+
                  |  hypervisor's   |  (hypervisor owns)
                  |  RA -> HPA map  |
                  +------------------+
                          |
                          v
                  Host physical address (HPA)
                          |
                          v
                       DRAM
```

The hypervisor's RA-to-HPA mapping is a software data structure (radix tree, hash table, or linear range list — implementer's choice). It's consulted on every guest TLB miss to compose the final TLB entry.

### 4.3 Trap delivery

When an exception occurs:

```
if (cause is delegated to S via HEDR) and (current_mode is S or U):
    save guest SR/PC into SSR/SPC
    enter S mode (HPRIV stays 0)
    jump to VBR + offset
else:
    save full SR/PC into HSSR/HSPC
    enter HS mode (HPRIV=1, MD=1)
    jump to VBR_HYP + offset
```

External interrupts always go to the hypervisor when virtualization is active (they're virtualized for the guest by the hypervisor's interrupt controller emulation).

### 4.4 Hypercall mechanism

A guest executes `HCALL` with a service code in R0:

```
HCALL_HV_MMU_MAP                  install a translation
HCALL_HV_MMU_UNMAP                remove a translation
HCALL_HV_MMU_DEMAP_CTX            flush all entries for a context
HCALL_HV_MMU_TSB_REGISTER         register a TSB
HCALL_HV_CPU_YIELD                yield to other guest/host
HCALL_HV_CONS_PUTCHAR             early-boot console
HCALL_HV_INTR_EOI                 end-of-interrupt for virtual IRQ
... (full table in 09-hypervisor-linux-spec.md)
```

The hypercall numbering and parameter convention mirror the sun4v hypervisor API.

### 4.5 Guest TLB miss flow

1. Guest user code touches a VA; TLB miss.
2. Hardware traps to guest's TLB miss vector (`VBR + 0x400`), delegated via HEDR.
3. Guest's miss handler reads its TSB (registered with hypervisor at boot).
4. On TSB hit: build PTEL with HPA from TSB entry, execute LDTLB.R.
5. LDTLB.R traps to hyperprivileged trap vector (LDTLB always traps in S mode under virt).
6. Hypervisor verifies the LDTLB entry came from a TSB it manages, installs in TLB, returns.
7. Guest resumes.

On TSB miss in step 4, guest calls `HCALL_HV_MMU_MAP` after walking its own page tables. Hypervisor adds the entry to the TSB and installs in TLB. Cost: one extra hypercall per cold-cold miss.

### 4.6 Per-guest IOMMU mappings

The IOMMU's BMID space is partitioned by the hypervisor: each guest gets a slice of BMIDs corresponding to the devices passed through to it. When a guest sets up DMA, it calls `HCALL_HV_IOMMU_MAP(iova, ra, perms, bmid)`. The hypervisor translates RA→HPA and programs the IOTLB entry with the resolved HPA and the guest's BMID. The IOTLB sees no difference from a non-virtualized environment.

For DMA initiated by host devices (not passed through to any guest), the hypervisor handles them directly, no changes from Phase 2.

## 5. Performance Characteristics

Realistic estimates for a Linux guest under a paravirtualized hypervisor on 100 MHz J-Core:

| Scenario | Cost |
|----------|------|
| Guest user-space steady-state (TLB hit) | 0 added overhead |
| Guest TLB miss, TSB hit, fast LDTLB trap | ~30 cycles |
| Guest TLB miss, TSB miss, hypercall + walk | ~150 cycles |
| Guest hypercall (HCALL_HV_*) | ~25 cycles trap + service |
| Guest context switch | ~50 cycles (hypercall to update ASID/TSB) |
| Privileged instruction trap | ~40 cycles |
| Inter-guest IPI | ~100 cycles |

For typical workloads (high TLB hit rate, occasional TSB warming), the **average virtualization overhead is 1-3%**. This is competitive with sun4v's measured overhead on Solaris workloads.

The overhead is higher than hardware-walked nested-paging designs (EPT/NPT achieve sub-1% for most workloads) but the gap closes for I/O-heavy workloads where the IOMMU does the heavy lifting (Phase 2 already paid that performance bill, and it's the same cost under virtualization).

## 6. Memory Isolation Guarantees

With the hypervisor active and all guests confined to their assigned ASID ranges and RA maps:

- **Guest-to-host isolation:** Guest can never construct an HPA. All addresses the guest manipulates are RAs; only the hypervisor's RA-to-HPA map can produce HPAs.
- **Guest-to-guest isolation:** Different guests get different ASID ranges. A TLB lookup with the wrong ASID misses, falls into the trap handler. Hypervisor's TSB management ensures no cross-guest TSB entries exist.
- **Hypervisor protection:** Hypervisor's own memory is mapped only in HS-mode mappings, with no TLB entries accessible from S or U. Even a malicious guest kernel cannot reach hypervisor memory.
- **Device-to-guest isolation:** Phase 2 IOMMU's per-BMID enforcement, with BMID ranges assigned per guest.

## 7. Limitations and Trade-offs

Honest accounting of what we give up by staying pre-2006:

- **TLB miss cost under virt is higher than EPT/NPT designs.** For TLB-miss-bound workloads (databases, large working sets), expect 5-10% slowdown vs. hardware nested paging. For typical workloads, the gap is in the noise.
- **Shadow page tables (for non-paravirt guests) consume hypervisor memory** proportional to active guest mappings. A guest with a large address space and many mappings has a sizable shadow PT footprint. Manageable but real.
- **Migration between physical machines requires significant hypervisor work** (gathering all RA-to-HPA mappings, transferring, reconstructing). Not impossible, but more work than EPT-based designs where the page tables are themselves the state.
- **Para-virtualization of the guest is highly recommended for performance.** Stock kernels work via shadow PTs but at a measurable cost.

For J-Core's target market — embedded systems, FPGA-based dev boards, single-purpose appliances with isolation requirements — these trade-offs are acceptable. We're not building a cloud server.

## 8. Out of Scope

- **Nested virtualization** (guest running its own guest). Theoretically possible but adds significant complexity. Defer.
- **Live migration.** Not implemented in Phase 3; future work if needed.
- **Hardware support for nested paging.** Explicitly rejected as post-2006.
- **Hardware VMID/VPID.** Explicitly rejected as post-2006. ASID partitioning serves the same role.
- **Trusted Execution Environment (TEE).** Could be added later as a Phase 4 (PowerPC's later "ultravisor" model exists but is post-2006).

## 9. References

- *UltraSPARC Architecture 2005 Specification* (Hyperprivileged Edition), Sun Microsystems, 2005. Available via OpenSPARC at oracle.com.
- *UltraSPARC Virtual Machine Specification* (sun4v hypervisor API), 2006 onwards. Available via sun4v.github.io.
- *OpenSPARC T1 Microarchitecture Specification*, 2006.
- *ESA/390 Interpretive-Execution Architecture, Foundation for VM/ESA*, IBM Journal of Research and Development, 1991.
- *IBM System/370 Extended Architecture Interpretive Execution* (SA22-7095-0), IBM, January 1984.
- *PowerPC Operating Environment Architecture Book III* (v2.01), IBM, December 2003.
- *Intel Virtualization Technology Specification for the IA-32 Architecture* (initial VT-x), Intel, 2005.
- Phase 1 MMU design spec (`01-design-spec.md`)
- Phase 2 IOMMU design spec (`04-iommu-design-spec.md`)
