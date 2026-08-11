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
- Keeping hardware additions minimal (approximately 300 LUTs per core — see §5)
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

**Decision:** When `SR.HPRIV=0` and a guest attempts LDTLB or LDTLB.RN, the operation traps to the hyperprivileged trap vector. The hypervisor reads the guest's PTEH/PTEL, performs RA-to-HPA translation, and writes the real TLB entry.

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

### 3.7 Hypervisor-allocated ASID and BMID partitioning

**Decision:** No VMID hardware field exists. The hypervisor uses the existing 12-bit ASID space (and 8-bit BMID space for IOMMU) and allocates ranges to guests. From hardware's perspective, there is no VMID — only ASIDs and BMIDs. From software's perspective, the hypervisor partitions these spaces.

Earlier drafts of this spec, of the Phase 1 MMU spec, and of the Phase 2 IOMMU spec reserved an 8-bit VMID field in TLB and IOTLB tag layouts. **That reservation is removed**: the field never existed in shipping hardware. See [glossary §5](../glossary.md), [mmu/design-spec.md §3.6](../mmu/design-spec.md), [iommu/design-spec.md §3.7](../iommu/design-spec.md).

**Rationale:** This is sun4v's actual approach (pre-2006 SPARC v9 hypervisor ASI / context partitioning, designed 2003–2005). The hypervisor allocates "contexts" globally and gives ranges to guests, ensuring isolation by allocation policy. The advantage: zero hardware additions for guest tagging.

**Partition arithmetic.** With a 12-bit ASID space (4096 ASIDs), the hypervisor splits as follows on a SoC supporting up to 16 guests:

| Owner | ASIDs |
|-------|-------|
| Host kernel | 2048 (0–2047) |
| Guest 1..16 (128 each) | 16 × 128 = 2048 (2048–4095) |
| **Total** | **4096** |

128 ASIDs per guest is sufficient for a containerized guest workload (10–100 processes); the host's 2048 ASIDs cover the host kernel and any guest VMM-process ASIDs needed on the host side. For SoCs targeting fewer guests, the per-guest allocation grows correspondingly (e.g. 8 guests × 256 = 2048, host keeps 2048). The Linux spec ([hypervisor/linux-spec.md §3.8](linux-spec.md)) carries the canonical allocator.

### 3.8 Per-guest TSB managed by hypervisor

**Decision:** Each guest has its own TSB, allocated and managed by the hypervisor. The hypervisor populates the TSB with pre-translated entries (already containing HPAs) as part of handling guest hypercalls. The guest's TLB miss handler reads from this TSB on miss; on TSB hit, it constructs a PTEL with the HPA from the TSB entry and executes LDTLB.RN, which traps to the hypervisor. The hypervisor verifies the LDTLB matches a TSB entry it wrote, installs in TLB.

**Rationale:** Sun4v's TSB registration API (`hv_mmu_tsb_ctx0`, `hv_mmu_tsb_ctxnon0`) is the precedent. The TSB hot path remains fast (no page-table walk in the guest), and the verification step on LDTLB is a quick cryptographic-cookie or pointer-range check.

> **Amendment — hardware TSB walker ([../mmu/hardware-spec.md §5.0](../mmu/hardware-spec.md)).**
> **Status: DESIGNED, not yet implemented.** Read this before changing
> anything in this section.
>
> **The guest's TSB must be mapped read-only to the guest. This becomes a
> security requirement, not a preference.**
>
> Today a guest-writable TSB is survivable: a guest that forged an HPN into
> its own TSB would have its handler build a `PTEL`, `LDTLB.RN` would trap,
> and the verification step above would reject it. **The walker installs
> directly from the TSB with no trap and therefore no verification step.** A
> guest-writable TSB then becomes a direct guest→host escape.
>
> Read-only rather than unmapped, because the guest's software fallback still
> reaches `VBR + 0x400` on a walker miss and re-probes the slot.
>
> **What replaces the verification step** is ownership of `TSBBR`: the
> walker's only data source is the set at `TSBBR | hash`, `TSBBR` is
> hypervisor-owned and P4-trapped, and §3.8 already has the hypervisor
> pre-populating the TSB with HPAs. So the walker can only install what the
> hypervisor wrote. §5's observation that trapping `TSBBR`/`TSBCFG` is
> "load-bearing, not merely tolerable" becomes literally the isolation root —
> see §6.
>
> **This is consistent with §3.2 (no hardware nested translation)**: the TSB
> already holds HPAs, so the walker installs them verbatim with no nesting.
> The walker is only viable *because* §3.8 chose HPA-in-TSB; a design holding
> RAs there would have needed a nested walk.
>
> **Benefit:** the per-refill `LDTLB` trap disappears on the TSB-hit path —
> see the §5 cost table. §3.8's cookie/range verification becomes dead code
> for hits, retained only for the software fallback.

### 3.8a Per-domain TSB partitioning composes on this machinery

> **Amendment — Phase 2 of the hardware-walker work
> ([../mmu/hardware-spec.md §2.13a](../mmu/hardware-spec.md)). Status: the
> `jcore-cpu` and `linux@jcore` side is IMPLEMENTED but NOT MERGED; the
> hypervisor itself is unimplemented (this whole document is Phase 3).**

[mmu/hardware-spec.md §2.13a](../mmu/hardware-spec.md) makes per-domain TSB
partitioning — disjoint index sets per trust domain, selected by writing
`TSBBR` — the **only** actual isolation mechanism for the TSB contention
channel. The `ASID` fold in the index and the victim LFSR are hardening; they
raise cost, they do not draw a boundary. Partitioning needs no RTL change,
because the TSB is software-managed memory and `TSBBR` is already a writable,
trapped register.

**It lands on machinery this document already specifies**, and it composes in
two levels that do not interfere:

- **Between guests** — the hypervisor allocates a per-guest TSB and owns its
  placement. This is §3.8, and it exists today; nothing new is required.
- **Within a guest** — the guest sub-divides *its own* allocation among its
  trust domains and writes `TSBBR` on domain switch. The write traps (§5); the
  hypervisor bounds-checks it against that guest's allocation and programs the
  real register.

**The hypervisor never needs to understand the guest's domain policy.** Its
entire obligation is "stay inside your allocation". The guest is free to change
how many domains it has, how it sizes them, or to abandon partitioning
entirely, with no hypervisor change and no interface to renegotiate.

**Consequence for §5's cost table: `TSBBR` is no longer a cold-path register.**
See the amendment there.

### 3.9 Untranslated guests are translated

**Decision:** When virtualization is active for a guest (`SR.HPRIV=0` in that context), all of the guest's P0-P3 accesses are translated through the TLB, regardless of what value the guest's own `MMUCR.AT` holds. A guest may believe it is running with translation off; the hardware translates it anyway. See [hardware-spec.md §4.4.1](hardware-spec.md).

**Rationale:** A bare-metal SH-4 image — a Dreamcast binary is the motivating case — runs with `MMUCR.AT=0` and lives entirely in P1/P2, which are untranslated by SH-4 architecture and bypass the TLB by design. Such a guest, taken as-is, has no translation path at all: its "physical" addresses are whatever it wrote into P1/P2 at link time, unconditionally. Load two such guests under one hypervisor and they resolve to the same host physical addresses and collide in DRAM. Forcing translation on is what turns "the address the guest wrote down" into something the hypervisor can relocate.

We reuse the existing TLB for this rather than adding a second, parallel relocation datapath, and inherit Phase 1's multi-size page support for free: a flat 16 MB guest image costs one large-page TLB entry, not per-4K-page bookkeeping. This is the same design axis §3.2 already committed to — no new translation hardware, only new uses of the old translation hardware.

**Rejected alternative:** a dedicated base+bound register pair (`HGBR`/`HGLR`) that would add a constant offset to every guest physical address instead of routing it through the TLB. This is cheaper in gates than reusing the TLB, but it forces each VM's guest memory to be a single physically contiguous region — no scattering a guest's frames across DRAM, no demand-paging guest memory on the host — and it adds a second, redundant address-relocation mechanism sitting alongside a TLB that already does this job. Reusing the TLB keeps address relocation as one mechanism, not two.

Prior art, pre-2006: IBM System/360 base-and-bounds relocation registers (1964) established that a program's addresses can be transparently relocated by hardware without the program's knowledge or cooperation — precisely the property an AT=0 guest needs. Sun4v's real-address offset mechanism (UltraSPARC Architecture 2005 Specification) is the direct SPARC-side precedent for treating "what the guest thinks is physical" as a software-relocatable real address rather than a literal physical one.

### 3.10 Emulated MMIO by physical aperture, not a PTE bit

**Decision:** Guest MMIO accesses to emulated devices are detected after translation, by comparing the resulting physical address against a hypervisor-configured aperture (`HEMUB`/`HEMUM`), not by a bit stored in the guest's PTE. See [hardware-spec.md §2.5](hardware-spec.md) and [hardware-spec.md §4.5](hardware-spec.md).

**Rationale:** The reason for this choice is that there is nowhere to put an MMIO bit. The jcore PTE format is already full:

```
bit: 31..............14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
     |      PFN       |SZ2|SZ1|SP|SZ0|PN|AC| W| X| U| D| C| G|ST| V|
```

Bits 0-7 are the hardware `PTEL` flags at identical bit positions, which is why `jcore_pte_to_ptel()` is a mask-and-shift operation with no bit rearrangement. Bits 8, 9, and 11 are software-only (not consulted by hardware TLB fill). Bits 10, 12, and 13 are the scattered 3-bit huge-page size slot. Bits 14-31 are the PFN. There are zero free bits in this layout. All eight size-slot code points the 3-bit field can express are already consumed (`HUGE_MAX_HSTATE 8`), so the size field cannot be narrowed to make room. Swap PTEs are equally tight: the swap-entry type field occupies bits 1-5, which is why jcore already overrides `_PAGE_SWP_EXCLUSIVE` to alias `_PAGE_EXEC` rather than allocate a fresh bit. (Source: `arch/sh/include/asm/pgtable-bits-jcore.h`.)

Against that budget, adding an "emulated device" PTE bit would cost one of: a huge-page size code point, a PFN bit (shrinking the addressable physical range), or promoting `pte_t` to 64 bits across the whole kernel. All three are bad trades for a property that is knowable a different way — from the physical address alone, at the moment of translation. The aperture derives the property instead of storing it, at the cost of one comparator (`(PA & HEMUM) == HEMUB`) rather than a PTE bit anywhere. It also gives per-VM device identity for free: because each VM's aperture slice is a distinct physical range, the comparator that detects "this is emulated MMIO" simultaneously identifies which VM's device model should handle it, with no separate tag to invent or maintain. `BMID` carries that same per-VM identity onto the bus for shared device blocks (§4.6), reusing the existing Phase 2 IOMMU partitioning scheme rather than inventing a second identity mechanism for the same purpose.

**Accepted constraint:** a guest device page and a guest RAM page can never share a real frame — device pages must be allocated from within the aperture, RAM pages from outside it. This is a real restriction on the hypervisor's physical memory allocator, accepted because the alternative (a PTE bit) is not available at any acceptable cost, per the audit above.

### 3.11 Complete-on-resume

**Decision:** When an emulated-MMIO trap fires, the faulting access is architecturally complete on every axis except the one effect the aperture intercepted (a load's register writeback, or a store's effect on the target device). The hypervisor supplies that missing half and resumes with `HRTE`; there is no guest instruction left to re-decode or re-execute. See [hardware-spec.md §4.5](hardware-spec.md).

**Rationale:** Three problems rule out the naive alternative of trapping before the access and having the hypervisor synthesize and single-step the instruction in software.

First, the unbanked-register problem: an SH-4 load's destination can be any of R0-R15, including R8-R15, which the hypervisor's own hyperprivileged context shares with the guest and therefore cannot use as scratch space or write into without first spilling guest state to memory on every single trapped access. A hardware-armed writeback port that fires exactly once, atomically, on the mode transition back to the guest sidesteps this entirely — the hypervisor never touches R8-R15 at all.

Second, cost: a re-execute design requires the hypervisor to fetch and decode the guest's SH-4 instruction stream on every trap to recover the addressing mode, register operands, and access width — work the hardware already did once, correctly, before the trap fired. That is a 40-80 cycle software-decode tax per trapped access. For a Dreamcast workload, whose device-driver hot path is dominated by exactly this kind of access (AICA sound registers, GD-ROM control, PVR2 tile-accelerator registers), paying that tax on every access is unacceptable; complete-on-resume replaces it with a small, fixed hardware cost (§5) and no software decode at all.

Third, the delay-slot hazard: if the faulting access sits in a branch delay slot, a re-execute design would need the hypervisor to recognize the delay slot, know whether the branch was taken, and resume at the correct target — delay-slot bookkeeping the hypervisor has no architectural way to reconstruct after the fact. Complete-on-resume avoids this because `HSPC` is captured pointing past the faulting access; the branch, if any, is already resolved by the time the trap is taken, and the hypervisor only ever sees the already-decided post-branch PC.

Prior art, pre-2006: IBM System/370 SIE (Start Interpretive Execution) interception controls (1980, generally available 1983) established exactly this contract for LPAR virtualization — an intercepted instruction reports enough decoded state that the host can complete or reject the operation and resume the guest without the host ever re-fetching or re-decoding the original instruction stream. `HMCR`'s captured `REGN`/`BANK`/`SIZE`/`DIR`/`SQ` fields are the modern equivalent of SIE's interception state.

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

The mechanism underneath is a single one — hypervisor-installed TLB entries that turn a guest's notion of "physical" into a real host physical address — configured two ways depending on whether the guest walks its own page tables.

**Configuration A: MMU-using guest.** A guest that runs with `MMUCR.AT=1` and maintains its own page tables constructs its own VA-to-RA mappings in software, exactly as an unvirtualized SH-4 kernel would:

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

The hypervisor's RA-to-HPA mapping is a software data structure (radix tree, hash table, or linear range list — implementer's choice). It's consulted on every guest TLB miss (§4.5) to compose the final TLB entry, which the guest's own page-table walk supplies the RA half of.

Configuration A carries one obligation Configuration B does not. Because §3.9 forces translation on for the guest's P0-P3, the guest's P1 is no longer the untranslated direct map that [../priv-arch/design-spec.md §4.7](../priv-arch/design-spec.md)'s single-level-`SPC`/`SSR` proof depends on — so the guest's own miss handler could fault on its own TSB load. [hardware-spec.md §4.4.5](hardware-spec.md) closes this normatively: the hypervisor MUST install pinned mappings covering the guest's whole P1 before entry and MUST NOT evict them while that guest runs, which makes the guest miss handler provably non-faulting again. Configuration A remains fully supported; it is simply an admission-control requirement (§7).

**Configuration B: flat/bare-metal guest.** A guest that runs with `MMUCR.AT=0` — a bare-metal SH-4 image such as a Dreamcast binary — maintains no page tables at all. Per §3.9, its P0-P3 accesses are translated anyway, so there is no guest-side VA-to-RA step to walk:

```
   guest P0-P3 ---->  (no guest page tables)
   address                    |
                               v
                  +------------------+
                  |  hypervisor-    |  (hypervisor owns,
                  |  installed TLB  |   installed at guest
                  |  entries        |   creation / boot)
                  +------------------+
                          |
                          v
                  Host physical address (HPA)
                          |
                          v
                       DRAM
```

Here the guest's untranslated address *is* what Configuration A calls the RA: the hypervisor pre-computes the RA-to-HPA map once (typically a single large-page mapping per §3.9, since a flat image is one contiguous region) and installs the resulting TLB entries directly, with no per-access guest-side walk and no TLB-miss round trip to a guest miss handler that doesn't exist. Configuration B is not a second translation mechanism — it is Configuration A with the guest-owned VA-to-RA stage collapsed to identity, because there is no guest page table to produce anything else. Both configurations terminate in the same hypervisor-owned RA-to-HPA map and the same TLB hardware; only the source of the RA differs.

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
2. Hardware traps to guest's TLB **miss** vector (`VBR + 0x400`), delegated via HEDR. (Protection violations take `VBR + 0x100` instead — see [mmu/hardware-spec.md §5](../mmu/hardware-spec.md) — so a delegating hypervisor must forward BOTH vectors, not just `0x400`.)
3. Guest's miss handler reads its TSB (registered with hypervisor at boot).
4. On TSB hit: build PTEL with HPA from TSB entry, execute LDTLB.RN.
5. LDTLB.RN traps to hyperprivileged trap vector (LDTLB always traps in S mode under virt).
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
| Guest TLB miss, TSB hit, fast LDTLB trap | ~30 cycles (**→ 0 with the hardware TSB walker**, §3.8 amendment — no trap at all on this path) |
| Guest TLB miss, TSB miss, hypercall + walk | ~150 cycles |
| Guest hypercall (HCALL_HV_*) | ~25 cycles trap + service |
| Guest context switch | ~50 cycles (hypercall to update ASID/TSB) |
| Privileged instruction trap | ~40 cycles |
| Inter-guest IPI | ~100 cycles |
| Guest MMUCR / TSBCFG access (P4 MMIO trap) | ~60 cycles, cold path |
| Guest `TSBBR` write (P4 MMIO trap) | ~60 cycles — **cold path only if the guest does not partition its TSB by trust domain; warm if it does** (§3.8a, and the amendment below) |

**What a guest TLB miss actually costs — the trap breakdown.** The forced-translation rule of
[hardware-spec.md §4.4.1](hardware-spec.md) makes all of a guest's P0-P3 accesses translated, and
[hardware-spec.md §4.4.3](hardware-spec.md) traps guest P4 wholesale. It is worth being exact
about which of the guest miss handler's instructions that actually costs, because the two rules
have very different reach:

| Guest miss-handler step | Mechanism | Traps? |
|-------------------------|-----------|:------:|
| `STC TSBPTR, Rn` — read the hardware-computed TSB slot pointer | in-core `STC` (`0x0043`), [mmu/hardware-spec.md §2.8](../mmu/hardware-spec.md), [§3.1](../mmu/hardware-spec.md) | no |
| Load the candidate TTE from the TSB | ordinary memory load, into the guest's pinned P1 window (§4.4.5) | no |
| `LDC Rm, PTEH` / `LDC Rm, PTEL` / `LDC Rm, ASIDR` | in-core `LDC` only — **these registers have no MMIO alias** ([mmu/hardware-spec.md §2.1](../mmu/hardware-spec.md), [§2.1a](../mmu/hardware-spec.md), [§3.1](../mmu/hardware-spec.md)) | no |
| `LDTLB` / `LDTLB.RN` | traps to `VBR_HYP + 0x190` by §3.4 | **yes — 1** |

So the figure is **one trap per guest TLB refill**, and the "~30 cycles, fast LDTLB trap" row above
stands. The guest's staging-register writes are not trapped and do not need to be: `PTEH`, `PTEL`
and `ASIDR` are write-only staging state that hardware consults *only* at `LDTLB` time, so letting
a guest load them natively leaks nothing — and it is exactly what makes
[hardware-spec.md §3.3](hardware-spec.md)'s handler work, since the hypervisor reads the guest's
intended VPN/RFN/ASID straight out of those registers at the trap.

Only `MMUCR` (`0xFF000010`), `TSBBR` (`0xFF000014`) and `TSBCFG` (`0xFF000018`) are genuinely MMIO
in the P4 core block, and only they take the emulated-MMIO trap. They are boot/config registers
([mmu/hardware-spec.md §3.1](../mmu/hardware-spec.md) puts them on the cold path deliberately), so
a guest touches them at boot and at whole-TLB-flush time (`MMUCR.TI`), not per miss — hence the
cold-path row added to the table above. A guest that flushes its whole TLB on every context switch
pays one extra ~60-cycle trap there, not one per mapping.

Note also that `TSBBR`/`TSBCFG` being trapped is load-bearing, not merely tolerable: it is how the
hypervisor keeps ownership of the guest's TSB placement (§3.8) while the guest's own
`STC TSBPTR` still returns a pointer into that TSB, computed by hardware from the base the
hypervisor programmed.

> **Amendment — the "cold path only" characterisation of `TSBBR` is wrong once a
> guest partitions its TSB by trust domain (§3.8a).** The reasoning above — a
> guest touches these at boot and at whole-TLB-flush time, not per miss — holds
> for `MMUCR` and `TSBCFG`. It does **not** hold for `TSBBR`: per-domain
> partitioning switches `TSBBR` on **domain switch**, potentially on every
> crossing of a trust boundary inside the guest. That is a warm path, not a
> cold one.
>
> **The ~60-cycle figure itself stands** — it is the cost of one emulated-MMIO
> P4 trap and nothing about the trap changed. What changes is how often it is
> paid, and therefore what a hypervisor implementer should optimise. A
> `TSBBR`-write trap handler that is merely *correct* is adequate for a boot
> register; one on a domain-switch path wants to be short, and its bounds check
> wants to be branch-free rather than merely present.
>
> A guest that does not partition its TSB pays exactly what the row above says.
> The hypervisor cannot tell which kind of guest it has in advance, so it must
> be built for the warm case.

**Pinned P1 mappings ([hardware-spec.md §4.4.5](hardware-spec.md)) cost TLB capacity, not cycles.**
An MMU-using guest requires its P1 window resident and never evicted. Because P1 is one contiguous
region, that is typically a single large-page entry per admitted guest — the same entry a flat
guest already needs — so the steady-state cost is one TLB way's worth of capacity per MMU-using
guest, and zero added cycles on any hot path.

For typical workloads (high TLB hit rate, occasional TSB warming), the **average virtualization overhead is 1-3%**. This is competitive with sun4v's measured overhead on Solaris workloads.

The overhead is higher than hardware-walked nested-paging designs (EPT/NPT achieve sub-1% for most workloads) but the gap closes for I/O-heavy workloads where the IOMMU does the heavy lifting (Phase 2 already paid that performance bill, and it's the same cost under virtualization).

**Hardware budget: ~300 LUTs/core, not ~200.** Earlier drafts of this spec set a goal of under 200 LUTs per core. That goal is superseded: the actual budget, itemized in [hardware-spec.md §10](hardware-spec.md), is approximately 300 LUTs per core. The increase over the original goal is entirely attributable to two additions made to support bare-metal (Dreamcast-class) guests, neither of which existed when the 200-LUT goal was set: the complete-on-resume writeback path (§3.11) — the destination-register latch and the `HRTE`-armed writeback port that let the hypervisor complete a trapped load without touching guest R8-R15 — and the emulated-MMIO aperture comparator and its trap-entry sequencing (§3.10). What that ~100-LUT increase buys is real: native-speed store-queue bursts to emulated devices with no software involvement on the hot path (the SQ carve-out of [hardware-spec.md §4.4.3](hardware-spec.md)), and zero software instruction decode on every trapped MMIO access — the 40-80 cycle per-access alternative that §3.11 rejects. Both are prerequisites for running an unmodified Dreamcast image at acceptable speed; the budget grew because the goalposts (bare-metal guest support) moved, not because the original design was under-costed.

## 6. Memory Isolation Guarantees

With the hypervisor active and all guests confined to their assigned ASID ranges and RA maps:

- **Guest-to-host isolation:** Guest can never construct an HPA. All addresses the guest manipulates are RAs; only the hypervisor's RA-to-HPA map can produce HPAs. **Enforcement differs before and after the hardware TSB walker, and the guarantee is only as good as its enforcement:**
  - *Today (procedural):* every `LDTLB`/`LDTLB.RN` traps, and the hypervisor verifies the entry against one it wrote (§3.8). A guest-writable TSB is therefore survivable.
  - *With the walker (structural, DESIGNED not implemented):* the walker installs without a trap, so verification is gone. The argument becomes: **the walker's only data source is the set at `TSBBR | hash`; `TSBBR` is hypervisor-owned and P4-trapped; therefore the walker can only install entries the hypervisor wrote.** This holds **only if the guest cannot write its own TSB** — hence the read-only mapping mandated in §3.8. A guest-writable TSB under a walker is a direct guest→host escape.
- **The `TSBBR` write-trap handler carries BOTH of the above, and that is a
  single point requiring its own test.** This is stated here explicitly rather
  than left implied across §3.8a and the guest-to-host bullet above, because
  the two properties are separately documented and a reader can easily meet
  only one of them.
  - *Guest→host:* after the walker, `TSBBR` ownership **is** the isolation
    argument. If a guest can point `TSBBR` outside its own allocation, it
    chooses what the walker installs into the TLB, with no trap and no
    verification. That is a **guest→host escape**.
  - *Intra-guest:* per-domain partitioning (§3.8a) makes the *same* register
    write the boundary between a guest's own trust domains. A bounds check
    that permits an out-of-partition base lets one domain prime and probe
    another's TSB sets. That is a **cross-domain leak**.
  - Therefore a missing, off-by-one, or non-total bounds check in that one
    handler is **simultaneously** a cross-domain leak and a guest→host escape.
    It must have a dedicated negative test — a guest writing a `TSBBR` outside
    its allocation, and a guest writing one inside its allocation but outside
    its current domain's sub-range — not merely be covered incidentally by
    tests that exercise the happy path. Both properties fail together and
    silently; neither produces a fault of its own.
- **Guest-to-guest isolation:** Different guests get different ASID ranges. A TLB lookup with the wrong ASID misses, falls into the trap handler. Hypervisor's TSB management ensures no cross-guest TSB entries exist.
- **Hypervisor protection:** Hypervisor's own memory is mapped only in HS-mode mappings, with no TLB entries accessible from S or U. Even a malicious guest kernel cannot reach hypervisor memory.
- **Device-to-guest isolation:** Phase 2 IOMMU's per-BMID enforcement, with BMID ranges assigned per guest.

## 7. Limitations and Trade-offs

Honest accounting of what we give up by staying pre-2006:

- **TLB miss cost under virt is higher than EPT/NPT designs.** For TLB-miss-bound workloads (databases, large working sets), expect 5-10% slowdown vs. hardware nested paging. For typical workloads, the gap is in the noise.
- **Shadow page tables (for non-paravirt guests) consume hypervisor memory** proportional to active guest mappings. A guest with a large address space and many mappings has a sizable shadow PT footprint. Manageable but real.
- **Migration between physical machines requires significant hypervisor work** (gathering all RA-to-HPA mappings, transferring, reconstructing). Not impossible, but more work than EPT-based designs where the page tables are themselves the state.
- **Para-virtualization of the guest is highly recommended for performance.** Stock kernels work via shadow PTs but at a measurable cost.
- **Device pages must come from the aperture.** Because §3.10 detects emulated MMIO by physical address rather than by a PTE bit, a guest device page and a guest RAM page can never share a real frame; the hypervisor's physical allocator must carve device pages exclusively from the `HEMUB`/`HEMUM` aperture. This is a real constraint on how flexibly the hypervisor can pack guest physical memory, accepted because a PTE bit was not available at any acceptable cost (§3.10).
- **Cached/uncached guest aliases are not hardware-coherent.** The P1/P2 alias described in [hardware-spec.md §4.4.2](hardware-spec.md) gives a guest two TLB entries mapping one physical frame, one cached and one uncached, exactly as bare-metal SH-4 software expects — but the hardware does not keep the two views coherent. A guest (or a buggy device model) that writes through the cached alias and reads through the uncached one without an explicit flush sees stale data, same as on real bare-metal hardware.
- **A Dreamcast guest's TLB footprint competes with the host's.** Guest translations, including the large-page mapping installed under §3.9's flat-guest configuration, occupy real TLB entries alongside host and other-guest entries. A guest with a large or fragmented footprint can evict host-hot entries, adding TLB-miss cost to the host's own steady-state workload.
- **An MMU-using guest obliges the hypervisor to pin its whole P1 window.** Because §3.9 forces
  translation on for a guest's P0-P3, a guest that runs its own TLB-miss handler no longer has the
  untranslated P1 that [../priv-arch/design-spec.md §4.7](../priv-arch/design-spec.md)'s
  single-level-`SPC`/`SSR` proof relies on. [hardware-spec.md §4.4.5](hardware-spec.md) restores
  the proof by *requiring* the hypervisor to install pinned TLB mappings covering the guest's
  entire P1 before entry and to hold them for the guest's lifetime. That is a real cost: TLB
  entries are permanently consumed per admitted MMU-using guest, and a hypervisor that cannot
  spare them must refuse to admit the guest. It is cheap in practice — P1 is contiguous, so it is
  normally one large-page entry — but it is a hard admission-control constraint, not a hint.
- **Only a restricted set of access classes may target the emulation aperture.** Per
  [hardware-spec.md §4.6](hardware-spec.md), `HMCR` can describe `MOV.{B,W,L}` loads and stores and
  the store-queue burst, and nothing else; `TAS.B`, FPU/SIMD loads and stores, `MAC`, and
  instruction fetch into the aperture are unrepresentable and fail closed to the illegal-instruction
  path. The VMM must therefore not map into the aperture anything a guest reaches by such an
  access. For the Dreamcast case this is checkable ahead of time, but it constrains what an
  arbitrary guest's device model may look like. Note also that the resulting exception routes
  through HEDR bit 12, which is delegatable: a VMM that delegates bit 12 lets the guest absorb the
  violation and never learns its device model is wrong. Failure is closed either way, but a VMM
  that wants visibility must not delegate bit 12.
- **Page-granular aperture mapping over-traps some device accesses.** The emulation aperture test (§3.10, §4.5) operates at physical-page granularity. A non-side-effecting register that happens to share a page with a side-effecting one traps on every access, even though the access itself has no emulation-relevant effect, because the hardware comparator cannot distinguish offsets within a page.

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
- *IBM System/360 Principles of Operation*, IBM, 1964 (base-and-bounds relocation registers).
- *IBM System/370 Principles of Operation*, IBM, 1970 (storage keys — physical-address-indexed access checking, the precedent cited by §3.10's emulation aperture and by [hardware-spec.md §2.5](hardware-spec.md); also the `ISK`/`SSK` privileged-only exposure of otherwise-invisible machine state cited by [../sq/spec.md §6.2](../sq/spec.md) and [§7](../sq/spec.md)).
- *IBM System/370 Extended Architecture Interpretive Execution* (SA22-7095-0), IBM, January 1984 (SIE, 1980, refined through 1983).
- *UltraSPARC Architecture 2005 Specification* (Hyperprivileged Edition), Sun Microsystems, 2005 (`PRIMARY_CONTEXT`, real-address offset mechanism).
- Renesas SH-4 CPU Core Architecture manual, 1998 (store queues).
- `arch/sh/include/asm/pgtable-bits-jcore.h` (jcore Linux PTE bit layout, §3.10).
- [hardware-spec.md §4.4](hardware-spec.md), [hardware-spec.md §4.5](hardware-spec.md), [hardware-spec.md §10](hardware-spec.md)
- [../sq/spec.md](../sq/spec.md) (store-queue architecture)
