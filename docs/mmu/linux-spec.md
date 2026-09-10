# J-Core MMU Linux Kernel Implementation Specification

**Status:** Draft  
**Scope:** Linux kernel changes required to support the J-Core MMU on J3, J32, and J64  
**Audience:** Kernel developer implementing the port

---

## 1. Scope and Strategy

This document specifies the Linux kernel additions and modifications needed to support the J-Core MMU. The goal is **one implementation that works on both J32 (32-bit) and J64 (64-bit)** — same source files, parameterized by `unsigned long` width and PGD depth.

The work builds on the existing `arch/sh/` infrastructure (originally for SH-3/SH-4) rather than creating a new architecture directory. Reuse:
- The exception/trap entry path (`arch/sh/kernel/entry-common.S`)
- The `pgtable.h` plumbing (PGD/PUD/PMD/PTE machinery)
- The fault handler (`arch/sh/mm/fault.c`)
- The context tracking (`mm_context_t`)

Replace or augment:
- The TLB miss handler with the TSB fast path
- The ASID allocator with the 12-bit per-CPU generation-tagged version
- The SMP bring-up with the J-Core CPUINFO-based discovery
- The page table format to support 16 KB base pages

## 2. Configuration

### 2.1 Kconfig additions

In `arch/sh/Kconfig`:

```kconfig
config CPU_SUBTYPE_JCORE
    bool "J-Core (J3/J64)"
    select HAVE_HW_BREAKPOINT
    select HAVE_PERF_EVENTS
    select GENERIC_IRQ_CHIP
    select MMU
    select JCORE_TSB

config JCORE_TSB
    bool "J-Core TSB-assisted TLB miss handler"
    depends on CPU_SUBTYPE_JCORE
    default y
    help
      Use the hardware-assisted TSB pointer to accelerate TLB miss
      handling. Disable only for debugging; the slow-path walker
      alone is much slower.

config JCORE_TSB_SIZE_LOG
    int "Log2 of TSB entry count"
    depends on JCORE_TSB
    range 6 14
    default 9
    help
      Number of TSB entries = 2^N. Each entry is 16 bytes.
      Default 9 (512 entries, 8 KB) suits embedded systems.
      Use 11–12 (32–64 KB) for systems with larger working sets.

choice
    prompt "Page size"
    depends on CPU_SUBTYPE_JCORE
    default PAGE_SIZE_16KB

config PAGE_SIZE_4KB
    bool "4 KB"
config PAGE_SIZE_16KB
    bool "16 KB"
config PAGE_SIZE_64KB
    bool "64 KB"
endchoice

config JCORE_PAE
    bool "Wide physical addressing (40-bit PA) on J32"
    depends on CPU_SUBTYPE_JCORE && !64BIT
    select PHYS_ADDR_T_64BIT
    select HIGHMEM
    help
      Enable > 4 GB physical address space on 32-bit J-Core via 64-bit
      PTEs and the PTEU register (the PAE/LPAE pattern). Per-process
      virtual stays 32-bit; RAM above the 512 MB P1 direct map is highmem.
      Requires a core built with ADDR_WIDTH=40 (see hardware-spec §2.10).
      Leave off for J32 cores with <= 4 GB physical; implied off on J64,
      which addresses wide physical natively.
```

### 2.2 PAGE_SHIFT

```c
/* arch/sh/include/asm/page.h additions */
#if defined(CONFIG_PAGE_SIZE_4KB)
#  define PAGE_SHIFT    12
#elif defined(CONFIG_PAGE_SIZE_16KB)
#  define PAGE_SHIFT    14
#elif defined(CONFIG_PAGE_SIZE_64KB)
#  define PAGE_SHIFT    16
#endif
#define PAGE_SIZE       (1UL << PAGE_SHIFT)
#define PAGE_MASK       (~(PAGE_SIZE - 1))
```

### 2.3 Cache aliasing and page colouring — none required ([PIPT L1](hardware-spec.md))

> **SUPERSEDED BY [hardware-spec.md §4.1a](hardware-spec.md) — 2026-09-07.**
> This section specified a **VIPT** L1-D contract and a strict page-colouring
> obligation on the kernel for 4 KB pages, including an `SHMLBA` of 8 KB and a
> colour-aligning `arch_get_unmapped_area`. The L1 caches are **PIPT** ([hardware-spec.md §4.1a](hardware-spec.md)): the core
> relocates the address to a physical one upstream of the cache
> (`core/cpu.vhd`), so no cache index bit is virtual and two virtual aliases of
> one physical page cannot land in different lines. **There is nothing for the
> kernel to do**, and the code this section proposed must not be written.

**The J-Core L1 instruction and data caches are physically-indexed, physically-tagged — PIPT** ([hardware-spec.md §4.1a](hardware-spec.md), which is the normative statement and carries the code binding).

**What this means for `arch/sh`, concretely:**

- **No colouring, at any page size.** The VIPT reasoning this section used to
  carry — index bits above the page offset, one colour bit at 4 KB, none at
  16 KB or 64 KB — does not apply, because there are no virtual index bits to
  reason about. `CONFIG_PAGE_SIZE_4KB` needs no special handling.
- **`SHMLBA` is left alone.** `arch/sh/include/asm/shmparam.h` on `linux@jcore`
  defines it as `0x4000` for the aliasing SH-3/SH-4 parts, and
  `arch/sh/mm/mmap.c` sets `shm_align_mask = PAGE_SIZE - 1` — the "sane caches"
  default — unless a probed cache descriptor says otherwise. J-Core is a sane
  cache. This section previously proposed writing `0x2000` into that header;
  that change is withdrawn and was never made.
- **`COLOUR_ALIGN` is not reached.** `arch_get_unmapped_area[_topdown]` applies
  it only when `do_colour_align` is set, which needs an aliasing cache. Nothing
  in the J-Core port sets it.
- **No flush-on-alias path either.** That was already this section's position
  and it survives, for a better reason: not "we chose strict colouring instead",
  but "there is no alias".

**The TLB miss handler is unaffected**, as before — and now trivially so. It
runs in P1 (`PA = VA & 0x1FFFFFFF`), and colouring is not a concept the port
has.

**Why this section existed.** VIPT was a real intermediate state of the design,
not a misreading: the cache tag RAM was widened to a physical tag and switched
on `AT` before the full VA→PA relocation landed. Written against that state,
this contract was correct. `jcore-cpu@master` has since retired the CPU-level
`mmucolor` page-colouring guard outright, replacing it with guards that assert
the relocation — see [hardware-spec.md §4.1a](hardware-spec.md) for the commits.

## 3. Page Table Format

### 3.1 J32 with 16 KB pages (two-level)

Virtual address layout:
```
[31:23]  PGD index   (9 bits, 512 entries)
[22:14]  PTE index   (9 bits, 512 entries)
[13:0]   Page offset (14 bits)
```

Each PGD and PTE table is 512 × 4 = 2 KB. PGD entries are physical addresses of PTE tables (with low bits as flags). PTE entries match the hardware's PTEL layout (so the TLB miss handler can use them directly).

### 3.2 PTE bit layout (matches hardware PTEL)

This layout is fixed by the RTL (`tlb.vhd:190-202`): `PPN[31:10], PageMask[11:8], W7 X6 U5 D4 C3 G2 STALE1 V0`. There is no distinct Read bit — read permission is implied by `_PAGE_VALID` (a valid, non-stale entry is always readable); it is not a separate bit position.

```c
/* arch/sh/include/asm/pgtable-bits.h additions for J-Core (RTL layout) */
#define _PAGE_VALID     (1UL << 0)   /* V — inert install (see §4.2 note) */
#define _PAGE_STALE     (1UL << 1)   /* STALE — soft-invalidate, lazy shootdown */
#define _PAGE_GLOBAL    (1UL << 2)   /* G */
#define _PAGE_CACHEABLE (1UL << 3)   /* C */
#define _PAGE_DIRTY     (1UL << 4)   /* D */
#define _PAGE_USER      (1UL << 5)   /* U */
#define _PAGE_EXEC      (1UL << 6)   /* X */
#define _PAGE_WRITE     (1UL << 7)   /* W */
/* No _PAGE_READ: read is implied by _PAGE_VALID, not a distinct RTL bit. */
#define _PAGE_PAGEMASK_SHIFT  8
#define _PAGE_PAGEMASK_MASK   (0xFUL << _PAGE_PAGEMASK_SHIFT)  /* [11:8] */
#define _PAGE_PFN_SHIFT       10     /* PPN[31:10] */
#define _PAGE_PFN_MASK        (~((1UL << _PAGE_PFN_SHIFT) - 1))

/* Standard pgprot combinations (re-derived from the RTL bit positions above) */
#define PAGE_NONE       __pgprot(_PAGE_VALID | _PAGE_GLOBAL)
#define PAGE_KERNEL     __pgprot(_PAGE_VALID | _PAGE_WRITE | \
                                 _PAGE_EXEC | _PAGE_CACHEABLE | _PAGE_GLOBAL | \
                                 _PAGE_DIRTY)
#define PAGE_KERNEL_RO  __pgprot(_PAGE_VALID | _PAGE_EXEC | \
                                 _PAGE_CACHEABLE | _PAGE_GLOBAL)
#define PAGE_COPY       __pgprot(_PAGE_VALID | _PAGE_USER | \
                                 _PAGE_CACHEABLE)
#define PAGE_SHARED     __pgprot(_PAGE_VALID | _PAGE_WRITE | \
                                 _PAGE_USER | _PAGE_CACHEABLE | _PAGE_DIRTY)
#define PAGE_READONLY   __pgprot(_PAGE_VALID | _PAGE_USER | \
                                 _PAGE_CACHEABLE)
#define PAGE_EXECUTABLE __pgprot(_PAGE_VALID | _PAGE_EXEC | \
                                 _PAGE_USER | _PAGE_CACHEABLE)
```

### 3.3 J64 with 16 KB pages (four-level)

Virtual address layout (48-bit VA):
```
[47:39]  PGD  (9 bits)
[38:30]  PUD  (9 bits)
[29:21]  PMD  (9 bits)
[20:14]  PTE  (7 bits)  -- could expand to 9 with larger PMD
[13:0]   Offset
```

P4D is folded (standard Linux pattern when not using 5-level). All PTE bit definitions above are unchanged; only the walker depth differs. The `#if defined(CONFIG_64BIT)` machinery already in generic `pgtable.h` handles the level-folding.

### 3.4 J32 with wide physical addressing (PAE)

Selected by `CONFIG_JCORE_PAE` (§2.1), for J32 cores built with 40-bit physical ([design-spec.md §3.8](../mmu/design-spec.md), [hardware-spec.md §2.10](../mmu/hardware-spec.md)). The **virtual** layout is unchanged from §3.1 — still 32-bit, still **two-level** (PGD + PTE). Only the *physical*/PTE width grows, exactly as Intel x86 PAE did (Pentium Pro, 1995; see [design-spec.md §3.8](../mmu/design-spec.md) for the full pre-2006 prior art). The kernel-mm code structure follows the later ARM LPAE port (2011) as the modern reference implementation — except that, because our virtual address is unchanged, we stay **two-level** where LPAE needs a third level (LPAE adds the level only to widen the virtual address, which we do not).

```c
typedef u64 pte_t;            /* 64-bit PTE carries a 40-bit frame */
typedef u64 pmd_t;            /* (folded on 2-level)               */
#define phys_addr_t u64       /* CONFIG_PHYS_ADDR_T_64BIT          */
```

**PTE = 8 bytes.** The low 32 bits are the hardware `PTEL` image (the §3.2 bit layout, with `PPN = PA[31:14]`); the high 32 bits are the `PTEU` image — only `[7:0]` are live (`PA[39:32]`), the rest zero/software:

```
PTE[31:0]   = PTEL image  (PPN[31:14] | flags)     -> ldc r,ptel
PTE[39:32]  = PA[39:32]   (PTEU.PPNH)              -> ldc r,pteu
PTE[63:40]  = reserved / software
```

Consequences for the `pgtable.h` plumbing:
- `pfn_pte()` / `pte_pfn()` operate on a 26-bit PFN (`PA[39:14]`) packed across the PTEL/PTEU split; `_PAGE_PFN_MASK` widens into the high word.
- PGD and PTE tables hold 64-bit entries, so each table is `512 × 8 = 4 KB` (was 2 KB). Both still fit well within a 16 KB page.
- The TSB-fill path ([§4.2](#42-the-c-walker)) writes the full 40-bit frame into the 64-bit TSB `Data` word; the hot-path handler stages it as two `ldc` (PTEL then PTEU) — see [hardware-spec.md §7 "PAE variant"](../mmu/hardware-spec.md) and §4.1 below.

**Highmem.** Physical RAM above the 512 MB P1 direct map (everything above 4 GB, and anything 0.5–4 GB) is `CONFIG_HIGHMEM` memory: the kernel cannot reach it through P1 and must `kmap()` it transiently into the translated **P3** (vmalloc/ioremap) window. `lowmem` = the P1-mapped low 512 MB (where page tables, the TSB, and kernel data must live — consistent with the [TSB-in-P1 rule, design-spec.md §4.3](../mmu/design-spec.md)). This is the standard arch/sh / arch/arm highmem model; the J-Core port reuses it unchanged apart from the `kmap` window living in P3.

**Storage vs. RAM — what PAE is and is not for.** Large *block* storage (SD cards, big files) needs none of this: 32-bit Linux already maps windows of multi-GB files via 64-bit `loff_t` and `mmap2`, paging in only the working set — the aggregate mapped data across processes can far exceed 4 GB with no wide-physical at all. PAE is specifically for > 4 GB of **resident physical** (RAM, or a byte-addressable memory-mapped store placed in high physical, then mapped via wide-PA PTEs / DAX).

## 4. TLB Miss Handler

> **Amendment — hardware TSB walker ([hardware-spec.md §5.0](hardware-spec.md)).**
> **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: retire inlined TLB fast path and STC ASIDR/TSBPTR reads".**
> Companion RTL:
> **RESOLVED 2026-08-25 — jcore-cpu@master: "rtl(mmu): the hardware walker is the sole TLB installer".**
> **§4.1 below is HISTORICAL** — read it for what the walker replaced, not for
> what the kernel runs.
>
> *(This block previously read "Not merged to master" and cited `jcore-cpu`
> `09304a3`/`957e940` plus a "98 PASS / 0 FAIL" tally. Checked 2026-08-25:
> **neither SHA is an ancestor of `jcore-cpu` `origin/master`** — the branch was
> rebased before merge. The tally has been dropped rather than restated, because
> it names no base and this task did not re-run the suite; see
> [../decisions/0002 §3](../decisions/0002-supersede-convention.md).)*
>
> **§4.1's assembly hot path is deleted.** The nine-instruction TSB probe is
> hardware now. `VBR + 0x400` is reached only on a walk failure, and its
> handler is save-regs / call `__jcore_tlb_walk()` / restore / `RTE`.
> Three constraints in §4.0 went with it, and are **gone, not relaxed**: the
> `bf` ±256-byte reach, the `.org jcore_vec_tlb + 0x12` exact-size assert, and
> the requirement that the slow path live in the `0x420..0x600` gap.
> **§4.2's C walker survives unchanged** and is the only software path.
>
> **The instructions the fast path used no longer exist.** `stc tsbptr,Rn`,
> `cmp/eq pteh,Rn`, `cmp/eq asidr,Rn` and `ldtlb.rn Rm` decode to General
> Illegal (hardware-spec.md §3.1). Anything in the tree that still emits them
> is a build break, not a slow path.
>
> **`get_asid()` still reads hardware — now through the P4 alias
> `0xFF000038`** (`arch/sh/include/asm/mmu_context_32.h`), because `STC ASIDR`
> is retired. It must read hardware and **not** `asid_cache(cpu)`: `set_asid()`
> composes the *passed* ASID with `asid_cache(cpu)`'s **current** `gen_low`,
> and `set_asid()`'s own comment records the `tlbflush_32.c` save/restore case
> where the saved tag came from a *different* mm — so `ASIDR` and
> `asid_cache(cpu)` provably diverge there. `set_asid()` keeps using
> `LDC Rm,ASIDR`; the write side is kept permanently (D7) and has no MMIO
> equivalent.
>
> **TSB store order must be reversed — and this is a live defect today,
> independent of the walker.** The walker compares `tag_hi` first, so
> `tag_hi` must be the **commit point**. `arch/sh/mm/tlb-jcore.c` writes it
> **first** (both in `__jcore_tlb_walk()` and in `__update_tlb()`), so a
> reader can observe a torn entry: correct VPN, stale `ASID_TAG` and `PTEL`.
> Correct order is `data`, then `tag_lo`, then `tag_hi`, with a barrier before
> the last store.
>
> **Also flagged for repair:** `__update_tlb()` executes `ldtlb.rn` in
> ordinary process context, outside any exception, where its `SR ← SSR`
> is not obviously correct. Likely should be plain `LDTLB`.
>
> **Phase 2 —
> RESOLVED 2026-08-25 — linux@jcore: "Merge pull request #10 from mountain-reverie/mmu/tsb-phase2".**
> Companion RTL:
> **RESOLVED 2026-08-25 — jcore-cpu@master: "rtl(mmu): the hardware walker is the sole TLB installer".**
> *(Promoted from "IMPLEMENTED on … NOT MERGED"; neither branch exists on
> `origin` any more.)* See §4.3 below for
> the fill contract this establishes. In one line: the TSB is 2-way with
> 32-byte sets, `TSBPTR` and the new `TSBSLOT` register both present a **set**
> address, `jcore_tsb_slot_offset()` is **deleted**, and every TSB entry write
> in the kernel goes through one helper.

### 4.0 The vector page

J4 uses SH-4-style **fixed** vectors: hardware branches to `VBR + offset` as
CODE, with the cause in `EXPEVT`/`INTEVT` and the interrupted state in
`SPC`/`SSR`. `jcore_vbr_base` (`ex.S`) is therefore a page of real code, not a
table of pointers:

| offset | contents |
|---|---|
| `+0x000` | not a J4 vector — spins, rather than running on into `+0x100` |
| `+0x100` | general exceptions → `jcore_general_entry` |
| `+0x400` | ALL TLB faults → save regs, call `__jcore_tlb_walk()`, `RTE`. *(Was: an inlined miss fast path at `+0x400` with `jcore_tlb_miss_slow` at `+0x420`; both deleted with the hardware walker.)* |
| `+0x600` | interrupts → `jcore_irq_entry` |

`jcore_general_entry` builds `pt_regs` from SPC/SSR and dispatches on `EXPEVT`:
the TLB **protection** causes (`0x0A0` IPROT, `0x0C0` DPROT_R/W) are page faults
by another name and go to `do_page_fault()` with the MMUFSR-derived
`error_code`; everything else goes to `jcore_handle_exception()`
(`exception.c`) with its raw `EXPEVT`.

> **This replaced the SH-2 arrangement the port started from.** `jcore_vbr_base`
> used to be a 256-entry *pointer table* in sh2/ex.S's layout, feeding
> sh2/entry.S's `exception_handler` — correct for SH-2, which vectors through
> the table and pushes PC/SR on the stack. J4 does neither. `VBR+0x100` landed
> *inside that table* and executed a `.long` as instructions, and `VBR+0x600` ([../priv-arch/design-spec.md §4.5](../priv-arch/design-spec.md))
> landed in whatever slow-path code followed the fast path. Only `VBR+0x400` was
> ever right, because it was the only vector CI exercised. *Guards:
> `mmulinuxexc` covers `+0x100` and `+0x600`; `mmulinux` covers `+0x400`.*

**Layout constraint, not a preference** — *and now retired; see the amendment
at the head of §4. With the fast path deleted there is no `bf` at the vector,
so `jcore_tlb_miss_slow`, the `0x420..0x600` gap rule and the `.org` assert are
all gone. Kept here because the failure mode is instructive.* `jcore_tlb_miss_slow` must stay in the
`0x420..0x600` gap. The fast path reaches it with `BF`, whose range is ±256
bytes; placed after the interrupt vector it goes out of reach and gas silently
rewrites `bf slow` as `bt .+2; bra slow; nop` — inverting the sense, so a TSB
**hit** starts taking two taken branches. `ex.S` carries an exact-size
`.org jcore_vec_tlb + 0x12` assertion that fails the build if this happens; the
older `+ 0x20` budget cannot catch it, because the relaxed macro is `0x1A`
bytes and still fits.

### 4.1 Hot path (assembly) — HISTORICAL, DELETED

> *(Implementation status: **removed**, `linux@jcore` `a9417bda9766`. The
> macro is gone from `ex.S` and three of the four instructions below no longer
> assemble.)*

Formerly `arch/sh/kernel/cpu/jcore/ex.S`, the macro `JCORE_TLB_FASTPATH`,
expanded **inline at the vector**, not jumped to.

The fast path handles the three TLB **miss** causes only. Protection faults take
`VBR + 0x100` with the other general exceptions — see §4.0 below — so this code
does not test the cause at all.

```asm
	.macro	JCORE_TLB_FASTPATH
	stc	tsbptr, r0
	mov.l	@r0+, r1		/* r1 = tag_hi (expected VPN); r0 += 4 */
	cmp/eq	pteh, r1		/* VPN match? -- fused CSR-vs-Rn compare */
	bf	jcore_tlb_miss_slow
	mov.l	@r0+, r1		/* r1 = tag_lo (expected ASID_TAG); r0 += 4 */
	mov.l	@r0, r3			/* r3 = TTE data (PTEL); load-use latency
					 * hides behind the compare + bf below */
	cmp/eq	asidr, r1		/* ASID_TAG match? -- fused compare */
	bf	jcore_tlb_miss_slow
	ldtlb.rn r3			/* PTEL<-r3 + install + return, one insn */
	.endm
```

**Nine instructions, no taken branch on a hit.** On entry SR.RB=1 (bank 1),
SR.MD=1, SR.BL=1; PTEH holds the faulting VPN, ASIDR the current ASID_TAG,
TSBPTR the precomputed slot address, and bank-1 r0-r3 are scratch. The TSB tag
is two 32-bit halves (hardware-spec.md §7): `tag_hi` = expected VPN, `tag_lo` =
expected ASID_TAG, compared separately so no small-page VPN/ASID bit overlap can
alias.

Three J4-only instructions carry the sequence, each replacing a pair:

| instruction | replaces |
|---|---|
| `cmp/eq pteh, Rn` | `stc pteh, Rt` + `cmp/eq Rt, Rn` (and the scratch register) |
| `cmp/eq asidr, Rn` | `stc asidr, Rt` + `cmp/eq Rt, Rn` |
| `ldtlb.rn Rm` | `ldc Rm, ptel` + `ldtlb.rn` |

`ldtlb.rn` has **no delay slot**. A trailing `nop` in any listing of it is
padding, not an architectural slot.

**Cost.** Measured on the cosim (`jcore-cpu/sim/bench_tlb_hotpath.sh`), fault to
back-executing the faulting instruction:

| | I-side (IMISS) | D-side (DMISS_R/W) |
|---|---|---|
| HW exception entry | 4 cyc | 5 cyc |
| handler body (9 insns) | 15 cyc | 15 cyc |
| `LDTLB.RN` install + redirect | 4 cyc | 4 cyc |
| **TSB hit, total** | **22 cyc** | **23 cyc** |
| cold (falls to the C walker) | 74 cyc | 75 cyc |

Those 22/23 cycles are the **baseline the walker is measured against**: with
the walker a TSB hit costs **8 cycles (IMISS) / 7 (DMISS)**. `mmubench` / `mmubenchi` used to carry a
byte-faithful copy of this macro, checked by
`jcore-cpu/sim/check_bench_fidelity.sh`; with the macro gone both the copy and
that script are gone, and the guards now measure the walker itself.

**PAE (`CONFIG_JCORE_PAE`).** The TTE becomes the full 64-bit TSB `Data` word:
`ldtlb.rn r3` is replaced by a two-stage load of the low word into `PTEL` and the
high word into `PTEU` before a parameterless `ldtlb.rn` (+2 instructions, no
extra TSB traffic — both halves are already in the loaded 16-byte entry). See
[hardware-spec.md §7 "PAE variant"](../mmu/hardware-spec.md).

### 4.2 The C walker

File: `arch/sh/mm/tlb-jcore.c`

```c
/*
 * Walk the OS page table to find the PTE for the faulting address.
 * On success, sets PTEL = found PTE and writes to TSB; returns 0.
 * On failure, returns nonzero (caller falls through to do_page_fault).
 */
int __jcore_tlb_walk(pgd_t *pgd, unsigned long addr, unsigned long pteh_tag)
{
    pud_t *pud;
    pmd_t *pmd;
    pte_t *pte;
    pte_t entry;
    unsigned long tsb_slot;

    pgd += pgd_index(addr);
    if (pgd_none(*pgd) || pgd_bad(*pgd))
        return -EFAULT;

    pud = pud_offset(pgd, addr);
    if (pud_none(*pud) || pud_bad(*pud))
        return -EFAULT;

    pmd = pmd_offset(pud, addr);
    if (pmd_none(*pmd) || pmd_bad(*pmd))
        return -EFAULT;

    pte = pte_offset_kernel(pmd, addr);
    entry = *pte;
    if (!(pte_val(entry) & _PAGE_VALID))
        return -EFAULT;

    if (pte_val(entry) & _PAGE_STALE)
        return -EFAULT;  /* lazy-shootdown stale; treat as fault */

    /* Update accessed/dirty bits */
    if (!(pte_val(entry) & _PAGE_ACCESSED)) {
        pte_val(entry) |= _PAGE_ACCESSED;
        *pte = entry;
    }

    /* Install into PTEL for LDTLB.RN */
    __asm__ __volatile__ ("ldc %0, ptel" :: "r"(pte_val(entry)));

    /* Write to TSB for next time */
    tsb_slot = jcore_read_tsbptr();   /* re-read; should be unchanged */
    *(unsigned long *)tsb_slot         = pteh_tag;    /* tag */
    *(unsigned long *)(tsb_slot + 8)   = pte_val(entry);  /* data */

    return 0;
}
```

For J64, the walker grows additional levels (P4D, PUD already). Compile-time level folding via the standard `pgtable.h` macros handles both widths from this one source.

**OPEN DECISION (deferred to SP1): `_PAGE_ACCESSED` bit assignment.** The walker above sets `_PAGE_ACCESSED` on the software PTE, but this document does not assign it a bit position in §3.2. On J32 the 32-bit PTE is fully consumed by the RTL-mandated layout (`flags[7:0]` + `PageMask[11:8]` + `PPN[31:10]`) — there is no spare bit for a hardware-visible Accessed flag, and the hardware TLB does not implement one (it is ignored by the walker's `ldtlb.rn`/TSB path either way). SP1 must pick one of: (a) steal/overload an existing software-only encoding (e.g. combine with `_PAGE_STALE` semantics), (b) track ACCESSED purely in a separate software structure outside the PTEL image, or (c) widen/relocate the PTE (the PAE §3.4 64-bit PTE has spare high bits available). This document does not make that call; it only records the constraint so SP1 starts from an accurate picture.

### 4.3 The TSB fill contract (Phase 2)

> **RESOLVED 2026-08-25 — linux@jcore: "Merge pull request #10 from mountain-reverie/mmu/tsb-phase2".**
> *(Promoted from "IMPLEMENTED on `mmu/tsb-phase2` / `mmu/tsb-hw-walker`, NOT MERGED"; neither branch exists on its `origin` any more.)*
> The code listings in §4.1/§4.2 above still show the pre-Phase-2 shape; this
> subsection is normative where they disagree.

The TSB is 2-way. `TSBPTR` and `TSBSLOT` both present a 32-byte-aligned **set**
address, and the set is a single cache line holding two contiguous 16-byte
entries — way 0 at `+0`, way 1 at `+16`, each laid out `tag_hi`, `tag_lo`,
`data`, reserved.

**`jcore_tsb_slot_offset()` is deleted.** It was a from-scratch C
reimplementation of the RTL's index hash that had to be kept bit-for-bit in
sync by hand — a mirror with no mechanism keeping the two copies honest.
Its replacement, `jcore_tsb_slot_addr()`, writes the VA to the `TSBSLOT` MMIO
register (`0xFF000048`, [hardware-spec.md §2.12](hardware-spec.md)) and reads
the set address back, so the index is computed by the one RTL function that
owns it. The fault path is unchanged: it uses the `TSBPTR` the fault already
latched.

**One writer.** All three words of a TSB entry are stored by
`jcore_tsb_write_entry()` in `arch/sh/mm/tlb-jcore.c`, and nothing else in the
kernel writes a TSB entry. It enforces the store order:

```
    data (PTEL)    -> slot + 8
    tag_lo (ASID)  -> slot + 4
    barrier()
    tag_hi (VPN)   -> slot + 0      <- the commit point
```

The walker compares `tag_hi` **first**, so `tag_hi` is the commit point.
Writing it earlier lets a walk that lands between the stores see `tag_hi`
already matching the new VPN while `tag_lo`/`data` still describe whatever the
slot held before — a torn read that installs a wrong translation with no
exception and no diagnostic. **Hardware cannot distinguish a torn entry from a
legitimate one**, so no bare-metal guard can catch a regression of this order.
Concentrating the stores in one function, with the reasoning attached, *is* the
enforcement: a future writer has to edit that function to get it wrong.

**Way selection, and why the rule is what it is.** `jcore_tsb_pick_way()`
applies one rule: **if either way already holds this VPN, overwrite that way.**
Only when neither matches does it take the hardware's victim nomination from
`TSBVICT` ([hardware-spec.md §2.13](hardware-spec.md)), whose LFSR the kernel
seeds through the write-only `TSBVSEED` in **two stages**: a best-effort write in
`enable_mmu()` so that no CPU is ever unseeded, and the real seed from
`jcore_reseed_tsb_vseed()`, a `late_initcall` in
`arch/sh/kernel/cpu/jcore/probe.c` that runs `on_each_cpu()` once `random_init()`
has actually run. *(This sentence previously read "seeds from boot entropy at MMU
init", which the kernel's own comment contradicts: `enable_mmu()` for CPU0 runs
from `setup_arch()`, before `random_init_early()`, so its `get_random_u32()`
draws on essentially no mixed-in entropy — and on this platform there is no
`RDSEED` and no bootloader entropy behind it. Corrected by Wave-3 **C3**,
2026-09-10; the consequences are in [hardware-spec.md §2.13](hardware-spec.md).)*
The seed is per-core, which is why this cannot be a single global initcall — it
was one once, and left every secondary CPU's selector unseeded.

This must not be "optimised" into always taking the nomination. Suppose a fresh
entry for VPN `X` went to way 1 while a stale entry for the same `X` still sat
in way 0. The next walk probes way 0 first, matches its tag, and installs the
**stale `PTEL`** — wrong permissions, no exception, no diagnostic. Hardware
cannot detect it; both tags are legitimate. Overwriting the matching way is
what makes that state **unconstructable** rather than merely unlikely, and
software can apply the rule for free because it already has both tags: one
index function plus both ways in a single 32-byte line means the tags arrive in
the one load it was going to issue anyway.

This is the reason the design has **one** index function and no skewing. Under
skewed associativity the two candidate slots for a VPN live in different sets
under different hashes, so software filling one cannot cheaply see the other,
and the stale-shadow state above becomes constructible. Skewing is a
*hardware-fill* technique — safe in a cache because the agent that fills is the
agent that just probed every way. This TSB is **software-filled**; the filler
is not the prober. That mismatch, not the hashing, is what makes skewing unsafe
here.

## 5. ASID Allocation and Context Switching

> **SUPERSEDED BY [hardware-spec.md §2.1a](hardware-spec.md) (generation nibble only) — 2026-08-25.**
> §5.1's `GEN_LOW_BITS` / `GEN_LOW_MASK` and §5.3's `encode_asid_tag()` are
> presented below as the live kernel design. **They are not in the kernel** —
> `git grep GEN_LOW_BITS origin/jcore -- arch/sh/` returns nothing.
> **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: retire the ASID generation nibble".**
> `get_asid()` returns a plain 12-bit ASID ([hardware-spec.md §2.1a](hardware-spec.md)),
> `MMU_NO_ASID` is back to `MMU_CONTEXT_FIRST_VERSION`, and `ASIDR` is written
> with that value alone.
>
> **What survives:** the per-CPU allocator, the version-wrap flush, and the
> `switch_mm` shape. **What does not:** every appearance of `gen_low`, the
> `ASIDR[15:12]` packing, and `jcore_tsb_flush_on_generation()`. Rewriting the
> listings belongs to Wave-2 **B1**.

### 5.1 Per-CPU ASID state

File: `arch/sh/mm/context-jcore.c`

```c
#define ASID_BITS        12
#define NUM_ASIDS        (1U << ASID_BITS)
#define ASID_MASK        (NUM_ASIDS - 1)
#define ASID_FIRST       1   /* 0 reserved for kernel */

#define GEN_LOW_BITS     4   /* low 4 bits packed into ASIDR[15:12] */
#define GEN_LOW_MASK     ((1U << GEN_LOW_BITS) - 1)

struct asid_state {
    u64                 generation;
    u16                 next_asid;
    DECLARE_BITMAP(used, NUM_ASIDS);
    unsigned long       last_online_jiffies;
};
static DEFINE_PER_CPU(struct asid_state, jcore_asids);

/* Per-mm context: array of (asid | gen << ASID_BITS) per CPU */
typedef struct {
    u32 asid[NR_CPUS];
    unsigned long pgd_pa;   /* physical address of pgd for slow-path walker */
} mm_context_t;
```

### 5.2 ASID allocation

```c
static u16 alloc_asid(struct mm_struct *mm, int cpu)
{
    struct asid_state *s = per_cpu_ptr(&jcore_asids, cpu);
    u16 asid;

    if (s->next_asid >= NUM_ASIDS) {
        /* Rollover: bump generation, flush local TLB */
        s->generation += NUM_ASIDS;
        bitmap_zero(s->used, NUM_ASIDS);
        local_flush_tlb_all();
        s->next_asid = ASID_FIRST;
    }
    asid = s->next_asid++;
    __set_bit(asid, s->used);
    mm->context.asid[cpu] = asid | ((s->generation & ~ASID_MASK));
    return asid;
}

static inline u32 encode_asid_tag(u16 asid, u64 generation)
{
    /* Pack ASID into low ASID_BITS and gen_low into next GEN_LOW_BITS.
     * Hardware compares the full 16-bit ASID_TAG field. */
    return asid | (((u32)(generation >> ASID_BITS) & GEN_LOW_MASK) << ASID_BITS);
}
```

### 5.3 switch_mm

```c
void switch_mm(struct mm_struct *prev, struct mm_struct *next,
               struct task_struct *tsk)
{
    int cpu = smp_processor_id();
    struct asid_state *s = this_cpu_ptr(&jcore_asids);
    u64 cur_gen = s->generation;
    u32 mm_asid = next->context.asid[cpu];
    u16 asid;

    if (likely(prev == next))
        return;

    /* Check if this mm's asid on this CPU is current */
    if ((mm_asid >> ASID_BITS) << ASID_BITS != (cur_gen & ~ASID_MASK))
        asid = alloc_asid(next, cpu);
    else
        asid = mm_asid & ASID_MASK;

    /* Publish current pgd for the slow-path walker */
    per_cpu(current_pgd, cpu) = next->pgd;

    /* Load ASIDR with the encoded 16-bit ASID_TAG.
     * (Hardware-spec.md §2.1a — ASIDR is the dedicated ASID register,
     * separate from PTEH. Replaces SH-4's "write ASID into PTEH" pattern.) */
    __asm__ __volatile__ ("ldc %0, asidr"
        :: "r"(encode_asid_tag(asid, s->generation)));
}
```

### 5.4 Kernel-space tagging

Kernel pages (P0 ASID 0 kernel mappings, P3 vmalloc) use `_PAGE_GLOBAL` so they match regardless of ASID. The TLB miss handler doesn't need to distinguish — the hardware GLOBAL bit suppresses ASID comparison.

## 6. SMP Bring-up

### 6.1 CPU discovery

File: `arch/sh/kernel/cpu/jcore/smp.c`

```c
#define JCORE_CPUINFO_MMIO   0xFF000030
#define JCORE_SMP_RELEASE    0xFF00FF00

static unsigned int read_cpuinfo(void)
{
    return *(volatile u32 *)JCORE_CPUINFO_MMIO;
}

void __init smp_init_cpus(void)
{
    unsigned int cpuinfo = read_cpuinfo();
    unsigned int hart_id = cpuinfo & 0xF;
    unsigned int core_caps = cpuinfo >> 16;

    /* Boot CPU registers itself; discover others from device tree */
    set_cpu_possible(hart_id, true);
    set_cpu_present(hart_id, true);

    /* Parse DT for additional CPUs */
    of_jcore_parse_cpus();
}
```

### 6.2 Per-CPU boot data

```c
struct jcore_per_cpu_boot {
    void           *stack;
    void           *entry;
    phys_addr_t     tsb_pa;
    u32             tsb_cfg;
    unsigned long   per_cpu_offset;
    u32             online;
    u32             padding[10];   /* pad to 64-byte cache line */
} __aligned(64);

static struct jcore_per_cpu_boot boot_data[NR_CPUS];

int jcore_cpu_up(unsigned int cpu)
{
    struct jcore_per_cpu_boot *b = &boot_data[cpu];

    if (!b->tsb_pa) {
        void *tsb = alloc_pages_exact(JCORE_TSB_BYTES,
                                      GFP_KERNEL | __GFP_ZERO);
        if (!tsb)
            return -ENOMEM;
        b->tsb_pa  = __pa(tsb);
        b->tsb_cfg = (HASH_MODE_XOR << 4) | CONFIG_JCORE_TSB_SIZE_LOG;
    }

    b->stack          = task_stack_page(idle_task(cpu)) + THREAD_SIZE;
    b->entry          = secondary_start_kernel;
    b->per_cpu_offset = __per_cpu_offset[cpu];
    b->online         = 0;
    smp_wmb();

    flush_cache_range_p1(b, b + 1);

    /* Release the CPU */
    writel(BIT(cpu), (void __iomem *)JCORE_SMP_RELEASE);

    /* Wait for it to check in */
    return wait_for_online(&b->online, msecs_to_jiffies(1000));
}
```

### 6.3 Secondary entry assembly

File: `arch/sh/kernel/cpu/jcore/head_smp.S`

```asm
        .global jcore_secondary_entry
jcore_secondary_entry:
        mov.l   sr_init, r0
        ldc     r0, sr

        mov.l   cpuinfo_p4, r0      ! 0xFF000030
        mov.l   @r0, r1
        mov     #0xF, r2
        and     r2, r1              ! r1 = hart_id

        shll2   r1
        shll2   r1
        shll2   r1                  ! × 64 (sizeof boot_data entry)
        mov.l   boot_data_p1, r0
        add     r1, r0

        mov.l   @r0, r15            ! stack
        mov.l   @(8, r0), r2        ! tsb_pa
        ldc     r2, tsbbr
        mov.l   @(12, r0), r2       ! tsb_cfg
        ldc     r2, tsbcfg

        mov     #0, r2
        ldc     r2, asidr           ! initial ASID_TAG = 0 (kernel ASID)
        ldc     r2, pteh            ! clear PTEH (no faulting VPN yet)

        mov.l   ti_at_bits, r2
        mov.l   mmucr_p4, r3
        mov.l   r2, @r3             ! TI + AT

        mov.l   @(16, r0), r2       ! per_cpu_offset
        ldc     r2, gbr

        mov     #1, r2
        mov.l   r2, @(20, r0)       ! online = 1
        synco

        mov.l   @(4, r0), r2        ! entry
        jmp     @r2
         nop

        .align 4
sr_init:      .long 0x500000F0
cpuinfo_p4:   .long 0xFF000030
boot_data_p1: .long boot_data + 0x80000000
mmucr_p4:     .long 0xFF000010
ti_at_bits:   .long 0x00000005     /* AT=1 | TI=1 */
```

### 6.4 Post-online ASID-state hygiene

```c
int jcore_secondary_post_online(unsigned int cpu)
{
    struct asid_state *s = per_cpu_ptr(&jcore_asids, cpu);
    unsigned long offline_for = jiffies - s->last_online_jiffies;

    /* If offline for long enough that process churn may have created
     * stale TSB entries, bump generation defensively */
    if (offline_for > HZ) {
        s->generation += NUM_ASIDS;
        bitmap_zero(s->used, NUM_ASIDS);
        local_flush_tlb_all();
    }
    s->last_online_jiffies = jiffies;
    return 0;
}
```

Wire via `cpuhp_setup_state(CPUHP_AP_ONLINE_DYN, "jcore/asid", jcore_secondary_post_online, NULL)`.

## 7. TLB Shootdown

### 7.1 Local invalidation

```c
static inline void local_flush_tlb_all(void)
{
    u32 mmucr;
    asm volatile (
        "mov.l   1f, r0\n"
        "mov.l   @r0, %0\n"
        "or      #1<<2, %0\n"   /* TI bit */
        "mov.l   %0, @r0\n"
        "bra     2f\n"
        "nop\n"
        ".align 4\n"
        "1: .long 0xFF000010\n"
        "2:\n"
        : "=&r"(mmucr) :: "r0", "memory");
}

static inline void local_flush_tlb_page(unsigned long addr)
{
    /* SH-4 had no per-page TLB invalidate; emulate with full flush.
     * If j-core adds a TLB-probe-and-invalidate, optimize here. */
    local_flush_tlb_all();
}
```

### 7.2 Cross-CPU invalidation

```c
void flush_tlb_mm(struct mm_struct *mm)
{
    /* Process-wide flush: increment generation on each CPU running mm.
     * No IPI needed; stale entries are rejected by the gen check. */
    int cpu;
    for_each_cpu(cpu, mm_cpumask(mm)) {
        struct asid_state *s = per_cpu_ptr(&jcore_asids, cpu);
        if (cpu == smp_processor_id()) {
            s->generation += NUM_ASIDS;
            bitmap_zero(s->used, NUM_ASIDS);
            local_flush_tlb_all();
        } else {
            /* Schedule a generation bump for next context switch on
             * that CPU. Real IPI only if synchronous semantics needed. */
            atomic_or(NUM_ASIDS, &per_cpu(pending_gen_bump, cpu));
        }
    }
}

void flush_tlb_range(struct vm_area_struct *vma,
                     unsigned long start, unsigned long end)
{
    /* For small ranges, local + IPI is fine. For larger, lazy. */
    if ((end - start) > LAZY_SHOOTDOWN_THRESHOLD) {
        flush_tlb_mm(vma->vm_mm);
        return;
    }
    /* Mark PTEs as STALE; remote CPUs will pick up on next miss */
    pte_t *pte;
    for (unsigned long addr = start; addr < end; addr += PAGE_SIZE) {
        pte = walk_pgd_lookup(vma->vm_mm, addr);
        if (pte && pte_val(*pte) & _PAGE_VALID)
            pte_val(*pte) |= _PAGE_STALE;
    }
    /* Local CPU still has live entries; flush */
    local_flush_tlb_all();
    /* Other CPUs: pages held in deferred-free until they context-switch */
    deferred_free_pages_after(vma->vm_mm, start, end);
}
```

## 8. Suspend / Resume

File: `arch/sh/kernel/cpu/jcore/pm.c`

### 8.1 State to save

```c
struct jcore_mmu_pm_state {
    u32 sr, vbr, gbr, tsbbr, tsbcfg, pteh, mmucr;
    u32 current_pgd_pa;
    u64 asid_generation;
};
static DEFINE_PER_CPU(struct jcore_mmu_pm_state, mmu_pm_save);
```

### 8.2 Save/restore hooks

Wire as `syscore_ops`:

```c
static int jcore_pm_suspend(void)
{
    struct jcore_mmu_pm_state *s = this_cpu_ptr(&mmu_pm_save);
    s->sr      = mfsr();
    s->vbr     = mfvbr();
    s->gbr     = mfgbr();
    s->tsbbr   = mftsbbr();
    s->tsbcfg  = mftsbcfg();
    s->pteh    = mfpteh();
    s->mmucr   = mfmmucr();
    s->current_pgd_pa  = __pa(per_cpu(current_pgd, smp_processor_id()));
    s->asid_generation = this_cpu_read(jcore_asids.generation);
    /* D-cache writeback handled by generic PM code */
    return 0;
}

static void jcore_pm_resume(void)
{
    struct jcore_mmu_pm_state *s = this_cpu_ptr(&mmu_pm_save);
    /* Restored to a sane SR by reset/wake controller already */
    mtvbr(s->vbr);
    mtgbr(s->gbr);
    mttsbbr(s->tsbbr);
    mttsbcfg(s->tsbcfg);
    mtpteh(s->pteh);
    /* Restore MMUCR last, OR'd with TI to flush any junk */
    mtmmucr(s->mmucr | (1u << 2));
    mtsr(s->sr);
}

static struct syscore_ops jcore_pm_ops = {
    .suspend = jcore_pm_suspend,
    .resume  = jcore_pm_resume,
};
```

Register at boot: `register_syscore_ops(&jcore_pm_ops)`.

## 9. kexec / kdump

File: `arch/sh/kernel/machine_kexec-jcore.c`

### 9.1 kexec transition

```c
void machine_kexec(struct kimage *image)
{
    /* Quiesce other CPUs */
    machine_shutdown();

    /* Disable local interrupts */
    local_irq_disable();

    /* Jump to new kernel's P1 entry. New kernel will:
     *   - Set its own TSBBR/TSBCFG
     *   - OR in MMUCR.TI to flush old TLB
     *   - Continue cold-boot path
     * No identity-mapping dance needed because we're in P1. */
    void (*new_kernel)(unsigned long, void *) =
        (void *)(image->start | P1SEG);
    new_kernel(image->arch.dtb_pa, image->arch.cmdline);
    /* Unreachable */
}
```

### 9.2 Crash kernel additional steps

```c
void machine_crash_shutdown(struct pt_regs *regs)
{
    crash_save_cpu(regs, smp_processor_id());
    /* Best-effort halt of other CPUs */
    crash_smp_send_stop();
    /* The new kernel must flush D-cache before any writes that might
     * corrupt the old kernel's image. We rely on the crash kernel's
     * early code to do OCBP across the whole D-cache. */
}

/* In the crash kernel's _start: */
crash_kernel_dcache_purge:
    mov.l   dcache_size, r1
    mov.l   p2_cache_base, r0
1:  ocbp    @r0
    add     #32, r0
    dt      r1
    bf      1b
    rts
    nop
```

## 10. File Layout Summary

Files added/modified:

```
arch/sh/Kconfig                                 (modified)
arch/sh/include/asm/page.h                      (modified)
arch/sh/include/asm/pgtable-bits.h              (modified)
arch/sh/include/asm/mmu_context.h               (modified)
arch/sh/include/asm/cpu-features.h              (new)
arch/sh/kernel/cpu/jcore/                       (new directory)
    head_smp.S                                  (new, ~80 lines asm)
    smp.c                                       (new, ~200 lines C)
    pm.c                                        (new, ~150 lines C)
    ex.S                                        (vector page + TLB fast path, asm)
    entry.S                                     (pt_regs save/restore + the three entries, asm)
    exception.c                                 (general-exception dispatch on EXPEVT)
arch/sh/kernel/machine_kexec-jcore.c            (new, ~100 lines C)
arch/sh/mm/tlb-jcore.c                          (new, ~250 lines C)
arch/sh/mm/context-jcore.c                      (new, ~200 lines C)
arch/sh/mm/fault.c                              (modified for J-Core paths)
arch/sh/kernel/entry-common.S                   (modified, vector table)
```

Total: ~1100 lines of new code (C + asm). Modifications to existing files: ~200 lines.

## 11. Boot Sequence

1. Bootrom does DRAM init, loads kernel image, jumps to P1 entry of kernel.
2. `head.S` (existing `arch/sh/kernel/head_32.S` with J-Core variant):
   - Sets SR, VBR, stack
   - Zeros BSS
   - Allocates boot TSB (in BSS, aligned)
   - Sets TSBBR, TSBCFG, ASIDR (ASID_TAG=0 = kernel ASID), PTEH (zero)
   - Builds early kernel page tables
   - Sets MMUCR.AT=1 with TI=1
   - Jumps to `start_kernel()`
3. `start_kernel()` runs standard Linux init.
4. Eventually forks `init`; the first user RTE is the first translated instruction fetch.

## 12. 32-bit vs 64-bit Differences

The same source tree compiles for both. Differences:

| Aspect | J32 | J64 |
|--------|-----|-----|
| `unsigned long` | 32 bits | 64 bits |
| Page table levels | 2 (PGD, PTE) | 4 (PGD, PUD, PMD, PTE) — P4D folded |
| VA bits | 32 | 48 (default) |
| PA bits | 32 | 40 (default, configurable) |
| TSB entry size | 16 bytes | 16 bytes (same) |
| TLB entry width | ~95 bits | ~135 bits |
| Asm `mov.l` | 32-bit loads | becomes `mov.q` for 64-bit fields |

The TLB miss assembly uses `mov.l` on J32 and `mov.q` on J64 (or just `MOVL` with macro). One `#ifdef CONFIG_64BIT` block in `ex.S` handles this.

**J32-PAE is a third column** (`CONFIG_JCORE_PAE`, §3.4): `unsigned long`/VA stay 32-bit and the page table stays 2-level, but `phys_addr_t`/`pte_t` become 64-bit, `PA bits` = 40, and `CONFIG_HIGHMEM` is forced on. It shares J32's virtual machinery and J64's 40-bit physical width — i.e. "J64 physical under a J32 virtual MMU." The `ex.S` PAE path adds the `PTEU` load under `#ifdef CONFIG_JCORE_PAE`.

## 13. Test Plan

### 13.1 Unit tests (kernel selftests)
- TLB miss → TSB hit (verify hot path runs)
- TLB miss → TSB miss → walker hit (verify slow path)
- TLB miss → walker fail (verify do_page_fault)
- ASID rollover (force 4096 context switches, verify correctness)
- `mmap` / `munmap` with various sizes and alignments
- `mprotect` permission changes take effect
- `fork()` + `exec()` (CoW correctness)
- Multi-threaded process with shared `mm`
- **Virtual aliasing (§2.3):** `shmget`/`shmat` the same segment at several
  addresses under `CONFIG_PAGE_SIZE_4KB` and assert that write-through-one /
  read-through-another observes coherent data. Note what this test is *for*
  under [PIPT](hardware-spec.md): it asserts the property holds with **no**
  alignment constraint imposed, which is the opposite of what this bullet asked
  for while §2.3 specified colouring — it used to require every attach to be
  `SHMLBA`-aligned and `arch_get_unmapped_area` to return `COLOUR_ALIGN`ed
  addresses. A colouring assertion here would now be asserting a bug.

### 13.2 Stress tests
- LTP `mm` test suite
- `stress-ng --vm --vm-bytes 4G` for sustained allocation pressure
- Multi-process memory thrashing (verify TLB and TSB efficiency)

### 13.3 SMP tests
- `cpu_up`/`cpu_down` cycles
- Process migration between CPUs
- Cross-CPU `munmap` (verify lazy shootdown correctness)
- ASID rollover on a non-boot CPU

### 13.4 PM tests
- `echo mem > /sys/power/state` cycles
- Multiple suspend/resume rounds
- `kexec` reboot
- `kdump` crash capture and `/proc/vmcore` integrity

### 13.5 Performance
- Compare TLB miss cost with and without `CONFIG_JCORE_TSB`
- Measure context-switch cost across ASID rollover
- Compare 4 KB / 16 KB / 64 KB page sizes on kernel build benchmark

## 14. Upstream Merge Plan

Suggested sequence:

1. **Phase 1: Core MMU port (no SMP, no PM).** Get a single-CPU J3 booting Linux with isolated user processes. Test with musl-libc userspace.
2. **Phase 2: SMP support.** Add `jcore_cpu_up`, secondary entry assembly, per-CPU ASID. Test with 2-4 cores.
3. **Phase 3: PM support.** Add suspend/resume. Test cycles.
4. **Phase 4: kexec / kdump.** Add for diagnostics and reboot speed.
5. **Phase 5: J64.** Once J32 is stable, extend to 64-bit. Most of the changes are `unsigned long` widening; the TLB miss path and ASID logic are unchanged.

Coordinate with the SuperH maintainer (currently John Paul Adrian Glaubitz) and the J-Core upstream (Jeff Dionne, Rich Felker).

## 15. Open Questions

- Should ASID 0 be reserved for kernel or recycled like others? Recommendation: reserve, simplifies global-bit handling.
- Should TSB sizing be per-CPU configurable at runtime or boot-only? Recommendation: boot-only initially.
- Lazy shootdown threshold: at what unmap-range size do we prefer lazy over IPI? Recommendation: start at 64 KB, tune empirically.
- Should the kernel use the contiguous-bit / mTHP convention for "free" superpages? Recommendation: yes, once base port is stable.
