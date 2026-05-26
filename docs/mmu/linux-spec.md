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

```c
/* arch/sh/include/asm/pgtable-bits.h additions for J-Core */
#define _PAGE_VALID     (1UL << 0)
#define _PAGE_STALE     (1UL << 2)   /* software-only, for lazy shootdown */
#define _PAGE_GLOBAL    (1UL << 3)
#define _PAGE_READ      (1UL << 4)
#define _PAGE_EXEC      (1UL << 5)
#define _PAGE_WRITE     (1UL << 6)
#define _PAGE_USER      (1UL << 7)
#define _PAGE_CACHEABLE (1UL << 8)
#define _PAGE_DIRTY     (1UL << 9)
#define _PAGE_PAGEMASK_SHIFT  10
#define _PAGE_PAGEMASK_MASK   (0xFUL << _PAGE_PAGEMASK_SHIFT)
#define _PAGE_PFN_SHIFT       PAGE_SHIFT
#define _PAGE_PFN_MASK        (~((1UL << _PAGE_PFN_SHIFT) - 1))

/* Standard pgprot combinations */
#define PAGE_NONE       __pgprot(_PAGE_VALID | _PAGE_GLOBAL)
#define PAGE_KERNEL     __pgprot(_PAGE_VALID | _PAGE_READ | _PAGE_WRITE | \
                                 _PAGE_EXEC | _PAGE_CACHEABLE | _PAGE_GLOBAL | \
                                 _PAGE_DIRTY)
#define PAGE_KERNEL_RO  __pgprot(_PAGE_VALID | _PAGE_READ | _PAGE_EXEC | \
                                 _PAGE_CACHEABLE | _PAGE_GLOBAL)
#define PAGE_COPY       __pgprot(_PAGE_VALID | _PAGE_READ | _PAGE_USER | \
                                 _PAGE_CACHEABLE)
#define PAGE_SHARED     __pgprot(_PAGE_VALID | _PAGE_READ | _PAGE_WRITE | \
                                 _PAGE_USER | _PAGE_CACHEABLE | _PAGE_DIRTY)
#define PAGE_READONLY   __pgprot(_PAGE_VALID | _PAGE_READ | _PAGE_USER | \
                                 _PAGE_CACHEABLE)
#define PAGE_EXECUTABLE __pgprot(_PAGE_VALID | _PAGE_READ | _PAGE_EXEC | \
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

## 4. TLB Miss Handler

### 4.1 Hot path (assembly)

File: `arch/sh/kernel/cpu/jcore/tlbmiss.S`

```asm
        .global jcore_tlb_miss
        .align 4
jcore_tlb_miss:
        ! Entry from VBR + 0x400 (instruction miss),
        ! VBR + 0x420 (data load miss),
        ! or VBR + 0x440 (data store miss).
        !
        ! On entry: SR.RB=1 (bank 1 selected), SR.MD=1, SR.BL=1.
        !           PTEH contains the faulting VPN (low bits zero).
        !           ASIDR contains the current ASID_TAG (unchanged from
        !             the last context switch).
        !           TSBPTR contains pre-computed slot address.
        !           Bank-1 R0-R7 are scratch.
        !
        ! The TSB tag word is split into two 32-bit halves (see
        ! hardware-spec.md §7): tag_hi = expected VPN, tag_lo = expected
        ! ASID_TAG. The handler does two CMP/EQ — VPN against PTEH,
        ! then ASID_TAG against ASIDR. This avoids any small-page VPN-
        ! vs-ASID-bit-overlap problem.

        stc     tsbptr, r0
        mov.l   @r0+, r1            ! r1 = tag_hi (expected VPN); r0 += 4
        stc     pteh, r2            ! faulting VPN
        cmp/eq  r1, r2              ! VPN match?
        bf      jcore_tlb_miss_slow
        mov.l   @r0+, r1            ! r1 = tag_lo (expected ASID_TAG); r0 += 4
        stc     asidr, r2           ! current ASID_TAG
        cmp/eq  r1, r2              ! ASID match?
        bf      jcore_tlb_miss_slow
        mov.l   @r0, r3             ! r3 = TTE data
        ldc     r3, ptel
        ldtlb.r                     ! Install + return atomically
         nop                        ! Delay slot of LDTLB.R

jcore_tlb_miss_slow:
        ! r0 points into the TSB slot; faulting VPN and ASID_TAG are
        ! re-read from PTEH and ASIDR by the slow-path code as needed.
        !
        ! Save additional registers since we may call into C.
        mov.l   r4, @-r15
        mov.l   r5, @-r15
        mov.l   r6, @-r15
        mov.l   r7, @-r15
        mov.l   pr_save, r4
        sts.l   pr, @-r15
        stc     pteh, r2            ! faulting VPN
        mov.l   r2, @-r15           ! pass faulting VPN on stack/arg

        ! Walk the page table in C
        mov.l   1f, r4              ! &current_pgd
        mov.l   @r4, r4             ! pgd_t *
        stc     tea, r5             ! faulting address
        mov.l   2f, r6              ! &__jcore_tlb_walk
        jsr     @r6
         nop

        ! r0 returns 0 on success (PTEL set, do LDTLB.R), nonzero on fault
        tst     r0, r0
        bf      jcore_tlb_real_fault
        ! restore PR and other saved registers
        lds.l   @r15+, pr
        mov.l   @r15+, r2
        mov.l   @r15+, r7
        mov.l   @r15+, r6
        mov.l   @r15+, r5
        mov.l   @r15+, r4
        ldtlb.r
         nop

jcore_tlb_real_fault:
        ! Page table walk failed; call do_page_fault
        mov.l   3f, r0
        jmp     @r0
         nop

        .align 4
1:      .long   current_pgd
2:      .long   __jcore_tlb_walk
3:      .long   do_page_fault
```

The hot path is 7 instructions. The slow path adds ~15 more plus the C walker.

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

    /* Install into PTEL for LDTLB.R */
    __asm__ __volatile__ ("ldc %0, ptel" :: "r"(pte_val(entry)));

    /* Write to TSB for next time */
    tsb_slot = jcore_read_tsbptr();   /* re-read; should be unchanged */
    *(unsigned long *)tsb_slot         = pteh_tag;    /* tag */
    *(unsigned long *)(tsb_slot + 8)   = pte_val(entry);  /* data */

    return 0;
}
```

For J64, the walker grows additional levels (P4D, PUD already). Compile-time level folding via the standard `pgtable.h` macros handles both widths from this one source.

## 5. ASID Allocation and Context Switching

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
#define JCORE_CPUINFO_MMIO   0xFF000020
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

        mov.l   cpuinfo_p4, r0      ! 0xFF000020
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
cpuinfo_p4:   .long 0xFF000020
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
    tlbmiss.S                                   (new, ~120 lines asm)
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

The TLB miss assembly uses `mov.l` on J32 and `mov.q` on J64 (or just `MOVL` with macro). One `#ifdef CONFIG_64BIT` block in `tlbmiss.S` handles this.

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
