# J-Core Hypervisor Linux Implementation Specification (Phase 3)

**Status:** Draft  
**Scope:** Linux kernel changes to support running as host and guest under the J-Core hypervisor extension  
**Audience:** KVM and Linux kernel developers  
**Prerequisites:** Phase 1 Linux spec, Phase 3 design spec, Phase 3 hardware spec

---

## 1. Scope and Strategy

This document specifies two sets of Linux changes:

1. **The hypervisor itself.** A KVM-style hypervisor implemented in the host kernel that creates and manages guests. Architecturally modeled on KVM/PowerPC's `kvm-pr` (Problem-Required) implementation, which uses shadow page tables — the closest pre-2006-style precedent in current Linux.

2. **Guest support.** Linux modifications that let a J-Core Linux kernel run efficiently as a guest. Includes paravirtualization hooks (`CONFIG_JCORE_PARAVIRT`) for the performance-critical paths, and fallback to trap-mediated operation for stock kernels.

Both build on Phase 1's `arch/sh/` infrastructure. The hypervisor lives in `arch/sh/kvm/`, parallel to `arch/sh/mm/`, `arch/sh/kernel/`. The paravirt hooks integrate into existing arch/sh code paths via the standard `paravirt_ops` mechanism (with j-core specifics).

## 2. Configuration

### 2.1 Host-side Kconfig

```kconfig
config KVM
    bool "KVM virtualization support"
    depends on CPU_SUBTYPE_JCORE
    select HAVE_KVM
    select KVM_GENERIC_HARDWARE_ENABLING
    help
      Enable KVM virtualization on J-Core. Allows running guest
      kernels in hyperprivileged-mode-protected partitions.
      Requires a J-Core CPU with Phase 3 hypervisor extensions
      (check CPUINFO[16] = HYP_SUPPORT).
```

### 2.2 Guest-side Kconfig

```kconfig
config JCORE_PARAVIRT
    bool "J-Core paravirtualization support"
    depends on CPU_SUBTYPE_JCORE
    help
      Enable paravirtualization hooks for running this kernel as
      a guest under the J-Core hypervisor. When enabled, MMU and
      certain other operations use hypercalls instead of direct
      hardware access, dramatically improving performance compared
      to trap-mediated guest execution.

      Safe to enable even when not running as a guest: the kernel
      detects at boot whether it's virtualized (via CPUINFO and a
      probe HCALL) and falls back to native operation otherwise.
```

## 3. The Hypervisor (Host Side)

### 3.1 File layout

```
arch/sh/kvm/
    Kconfig                      modified, KVM config option
    Makefile                     modified
    kvm-jcore.c                  KVM core integration, ~400 lines
    vm.c                         per-VM state, ~300 lines
    vcpu.c                       per-vCPU state and entry/exit, ~600 lines
    handle_exit.c                VM-exit dispatch, ~400 lines
    hypercall.c                  HCALL service implementations, ~500 lines
    shadow_mmu.c                 shadow page tables, ~700 lines
    tsb.c                        per-guest TSB management, ~300 lines
    interrupt.c                  virtual interrupt controller, ~400 lines
    asm/                         hyperprivileged-mode entry/exit assembly
        hyp_entry.S              ~200 lines
        hyp_exit.S               ~150 lines
        guest_switch.S           ~150 lines
arch/sh/include/asm/
    kvm_host.h                   data structures, ~250 lines
    kvm_hypercall.h              hypercall codes and ABI, ~100 lines
```

Total: ~4500 lines of new code. Comparable in size to KVM/PowerPC (kvm-pr).

### 3.2 Per-VM and per-vCPU state

```c
/* arch/sh/include/asm/kvm_host.h */

#define KVM_JCORE_MAX_VCPUS      4    /* per-VM limit; small for embedded */
#define KVM_JCORE_ASID_BASE      256  /* hypervisor uses 0-255, guests 256+ */
#define KVM_JCORE_ASID_PER_VM    256  /* each guest gets 256 ASIDs */

/* Per-VM state */
struct kvm_arch {
    struct kvm                 *kvm;     /* parent */
    
    /* RA -> HPA mapping for this guest's "real address" space */
    struct ra_map              ra_map;
    
    /* ASID partition: which range of host ASIDs are this guest's */
    u16                        asid_base;
    u16                        asid_count;
    
    /* BMID partition: which BMIDs are passed through to this guest */
    DECLARE_BITMAP(bmids, JCORE_IOMMU_MAX_BMID);
    
    /* Per-vCPU TSBs (one per vCPU) */
    struct jcore_guest_tsb     *tsbs[KVM_JCORE_MAX_VCPUS];
    
    /* Shadow page table (for non-paravirt guests) */
    struct shadow_mmu          *shadow_mmu;
    
    /* Virtual interrupt controller state */
    struct jcore_vintc         vintc;
};

/* Per-vCPU state */
struct kvm_vcpu_arch {
    /* Guest registers, saved on VM exit */
    unsigned long              gpr[16];
    unsigned long              gpr_bank1[8];
    unsigned long              pc, sr, vbr, gbr;
    unsigned long              pteh, ptel, tsbbr, tsbcfg;
    unsigned long              spc, ssr;
    unsigned long              mach, macl, pr;
    
    /* Guest's RA-space pgd (for shadow MMU mode) */
    unsigned long              guest_pgd_ra;
    
    /* TSB pointer for this vCPU */
    struct jcore_guest_tsb    *tsb;
    
    /* Pending virtual interrupts */
    unsigned long              vintr_pending;
};
```

### 3.3 The hypervisor entry/exit path

When a guest's exception or hypercall targets the hypervisor, control arrives at VBR_HYP. The assembly entry:

```asm
/* arch/sh/kvm/asm/hyp_entry.S */

        .global jcore_hyp_entry_0x100   /* HCALL handler */
jcore_hyp_entry_0x100:
        /* Save guest registers to vcpu->arch.gpr[] */
        mov.l   r0, @-r15           /* save R0 (hypercall code) */
        ; ... save R1-R15, banked regs, PR, etc.
        
        /* Compute pointer to current vcpu_arch from a per-CPU global */
        mov.l   per_cpu_vcpu, r4
        mov.l   @r4, r4             /* r4 = struct kvm_vcpu_arch * */
        
        /* Call C handler */
        mov.l   handle_hcall, r5
        jsr     @r5
         nop                        /* delay slot */
        
        /* Restore guest registers, HRTE */
        ; ... restore R0-R15, etc.
        hrte
         nop

        .global jcore_hyp_entry_0x190   /* Guest LDTLB trap */
jcore_hyp_entry_0x190:
        /* Faster path: guest tried LDTLB. Save minimal state, handle. */
        mov.l   r0, @-r15
        mov.l   r1, @-r15
        mov.l   r2, @-r15
        mov.l   r3, @-r15
        
        /* Read guest's intended PTEH/PTEL */
        stc     pteh, r0
        stc     ptel, r1
        
        /* Translate RA -> HPA, install in TLB */
        mov.l   handle_guest_ldtlb, r2
        jsr     @r2
         mov    r1, r4               /* delay slot: pass PTEL */
        
        /* Restore and return */
        mov.l   @r15+, r3
        mov.l   @r15+, r2
        mov.l   @r15+, r1
        mov.l   @r15+, r0
        hrte
         nop
```

### 3.4 Hypercall service table

```c
/* arch/sh/kvm/hypercall.c */

#define HV_RET_OK         0
#define HV_RET_EINVAL    -1
#define HV_RET_ENOMEM    -2
#define HV_RET_EPERM     -3

typedef long (*hcall_handler_t)(struct kvm_vcpu *vcpu, unsigned long *args);

static const hcall_handler_t hcall_table[] = {
    [0x00] = hcall_hv_api_version,
    [0x10] = hcall_hv_mmu_map,
    [0x11] = hcall_hv_mmu_unmap,
    [0x12] = hcall_hv_mmu_demap_ctx,
    [0x13] = hcall_hv_mmu_tsb_register,
    [0x14] = hcall_hv_mmu_perm_map,    /* permanent mapping */
    [0x20] = hcall_hv_cpu_yield,
    [0x21] = hcall_hv_cpu_qsetup,
    [0x30] = hcall_hv_intr_eoi,
    [0x31] = hcall_hv_intr_inject,
    [0x40] = hcall_hv_iommu_map,
    [0x41] = hcall_hv_iommu_unmap,
    [0x50] = hcall_hv_cons_putchar,
    [0xFF] = hcall_hv_machine_exit,
};

long handle_hcall(struct kvm_vcpu *vcpu)
{
    unsigned long code = vcpu->arch.gpr[0];
    unsigned long args[7] = {
        vcpu->arch.gpr[1], vcpu->arch.gpr[2], vcpu->arch.gpr[3],
        vcpu->arch.gpr[4], vcpu->arch.gpr[5], vcpu->arch.gpr[6],
        vcpu->arch.gpr[7],
    };
    
    if (code >= ARRAY_SIZE(hcall_table) || !hcall_table[code])
        return HV_RET_EINVAL;
    
    return hcall_table[code](vcpu, args);
}
```

The hypercall numbering and convention mirror sun4v's HV API.

### 3.5 The hv_mmu_map handler

The most critical hot path:

```c
long hcall_hv_mmu_map(struct kvm_vcpu *vcpu, unsigned long *args)
{
    unsigned long guest_va     = args[0];
    unsigned long guest_ra     = args[1];
    unsigned long perms        = args[2];
    unsigned long asid         = args[3];
    unsigned long page_size    = args[4];
    
    struct kvm_arch *kvm = vcpu->kvm->arch;
    unsigned long hpa;
    unsigned long page_mask;
    
    /* Validate ASID is in this guest's range */
    if (asid < kvm->asid_base || asid >= kvm->asid_base + kvm->asid_count)
        return HV_RET_EPERM;
    
    /* Translate RA -> HPA */
    hpa = ra_map_lookup(&kvm->ra_map, guest_ra);
    if (!hpa)
        return HV_RET_EINVAL;
    
    /* Convert page_size to PageMask field */
    page_mask = page_size_to_mask(page_size);
    
    /* Insert into this guest's TSB so future misses are fast */
    tsb_insert(vcpu->arch.tsb, guest_va, hpa, perms, asid, page_mask);
    
    /* Optionally also install directly in TLB if this is the active vcpu */
    if (vcpu == this_cpu_current_vcpu()) {
        unsigned long pteh = (guest_va & ~PAGE_MASK) | asid;
        unsigned long ptel = (hpa & PFN_MASK) | (page_mask << 10) | perms;
        
        /* Install in real TLB; we're in hyperprivileged mode, so LDTLB
         * doesn't trap to ourselves */
        asm volatile (
            "ldc %0, pteh\n"
            "ldc %1, ptel\n"
            "ldtlb\n"
            :: "r"(pteh), "r"(ptel));
    }
    
    return HV_RET_OK;
}
```

### 3.6 Shadow MMU for non-paravirt guests

For a guest that doesn't use HCALL and instead manipulates page tables and LDTLB normally:

```c
/* arch/sh/kvm/shadow_mmu.c */

/*
 * Each guest's view: guest PTEs are in guest's pages, pointing at RFNs.
 * Our shadow PTE table: hashtable keyed by (guest_ctx, guest_va),
 * holding the final {hpa, perms} for installation in TLB.
 *
 * Whenever the guest modifies its page tables, we don't know — but the
 * next LDTLB attempt traps to us, at which point we read the guest's
 * intended PTE, validate, and install.
 */

long handle_guest_ldtlb(struct kvm_vcpu *vcpu, unsigned long pteh,
                        unsigned long ptel)
{
    struct kvm_arch *kvm = vcpu->kvm->arch;
    unsigned long guest_va = pteh & ~PAGE_MASK;
    unsigned long guest_asid = pteh & ASID_MASK;
    unsigned long guest_rfn = ptel >> PAGE_SHIFT;
    unsigned long perms = ptel & PERM_BITS;
    unsigned long hpa;
    
    /* Map guest_asid -> our partitioned asid */
    unsigned long real_asid = kvm->asid_base + (guest_asid % kvm->asid_count);
    
    /* Translate RFN -> HPN */
    hpa = ra_map_lookup(&kvm->ra_map, guest_rfn << PAGE_SHIFT);
    if (!hpa) {
        /* Inject a memory fault into the guest */
        inject_guest_fault(vcpu, guest_va);
        return -EFAULT;
    }
    
    /* Compose real PTE */
    unsigned long real_pteh = guest_va | real_asid;
    unsigned long real_ptel = hpa | (ptel & ~_PAGE_PFN_MASK);
    
    /* Install in TLB */
    asm volatile (
        "ldc %0, pteh\n"
        "ldc %1, ptel\n"
        "ldtlb\n"
        :: "r"(real_pteh), "r"(real_ptel));
    
    return 0;
}
```

For paravirt guests, this path is rarely entered — they call hv_mmu_map directly instead of attempting LDTLB.

### 3.7 RA-to-HPA map implementation

The hypervisor maintains a per-guest RA→HPA map. Implementation: a simple range list or a hash table, depending on guest size.

For embedded targets where a guest's memory is one or two contiguous physical regions, a simple base+offset works:

```c
struct ra_map_entry {
    unsigned long ra_start;
    unsigned long hpa_start;
    unsigned long size;
};

struct ra_map {
    struct ra_map_entry entries[8];   /* up to 8 regions per guest */
    int n_entries;
    rwlock_t lock;
};

unsigned long ra_map_lookup(struct ra_map *map, unsigned long ra)
{
    int i;
    read_lock(&map->lock);
    for (i = 0; i < map->n_entries; i++) {
        if (ra >= map->entries[i].ra_start &&
            ra < map->entries[i].ra_start + map->entries[i].size) {
            unsigned long offset = ra - map->entries[i].ra_start;
            read_unlock(&map->lock);
            return map->entries[i].hpa_start + offset;
        }
    }
    read_unlock(&map->lock);
    return 0;
}
```

For larger guests, replace with a radix tree.

### 3.8 ASID partitioning

```c
/* arch/sh/kvm/vm.c */

static DEFINE_MUTEX(asid_alloc_lock);
static DECLARE_BITMAP(asid_blocks, 16);   /* 16 guests, 256 ASIDs each */

int kvm_arch_init_vm(struct kvm *kvm, unsigned long type)
{
    struct kvm_arch *kvm_arch;
    int block;
    
    kvm_arch = kzalloc(sizeof(*kvm_arch), GFP_KERNEL);
    if (!kvm_arch)
        return -ENOMEM;
    
    /* Allocate an ASID block */
    mutex_lock(&asid_alloc_lock);
    block = find_first_zero_bit(asid_blocks, 16);
    if (block >= 16) {
        mutex_unlock(&asid_alloc_lock);
        kfree(kvm_arch);
        return -ENOSPC;
    }
    set_bit(block, asid_blocks);
    mutex_unlock(&asid_alloc_lock);
    
    kvm_arch->asid_base  = 256 + block * 256;   /* host uses 0-255 */
    kvm_arch->asid_count = 256;
    kvm->arch = kvm_arch;
    
    return 0;
}
```

The 12-bit ASID space (4096 total) gives the host 256 plus 15 guests × 256 = 4096. Tight but workable. For more guests, expand ASID width or reduce per-guest count.

### 3.9 VM entry / exit

```c
/* arch/sh/kvm/vcpu.c */

int kvm_arch_vcpu_ioctl_run(struct kvm_vcpu *vcpu, struct kvm_run *run)
{
    int ret;
    
    /* Outer loop: handle exits until guest needs to be resumed by userspace */
    while (1) {
        /* Configure HEDR for this guest's exception delivery */
        load_hedr(vcpu);
        
        /* Set up HSPC and HSSR for VM entry: HRTE will use these to
         * transition to the guest's PC/SR */
        load_guest_sr_pc(vcpu);
        
        /* Restore guest registers */
        ret = enter_guest_asm(vcpu);
        /* When we return, the guest exited; ret is the exit code */
        
        if (ret == EXIT_REASON_HCALL) {
            handle_hcall(vcpu);
            continue;
        } else if (ret == EXIT_REASON_LDTLB) {
            handle_guest_ldtlb(vcpu, vcpu->arch.pteh, vcpu->arch.ptel);
            continue;
        } else if (ret == EXIT_REASON_MMIO) {
            run->exit_reason = KVM_EXIT_MMIO;
            return 0;   /* userspace handles MMIO */
        } else if (ret == EXIT_REASON_IRQ) {
            /* External IRQ; handle in host */
            handle_external_irq(vcpu);
            continue;
        }
        
        /* Unknown exit */
        break;
    }
    
    return ret;
}
```

The `enter_guest_asm` is the assembly stub that saves host state, restores guest state, executes HRTE, and on the next VM exit saves guest state and restores host state.

## 4. Guest Support (Paravirt Hooks)

For a guest kernel to perform well, it should be paravirt-aware. The hooks:

### 4.1 MMU operations

```c
/* arch/sh/include/asm/jcore_paravirt.h */

#ifdef CONFIG_JCORE_PARAVIRT
extern bool jcore_running_as_guest;

static inline void jcore_ldtlb(unsigned long pteh, unsigned long ptel)
{
    if (jcore_running_as_guest) {
        /* Use hypercall instead of trap-on-LDTLB */
        jcore_hcall_hv_mmu_map(pteh & ~PAGE_MASK, ptel & ~PAGE_MASK,
                              ptel & PERM_BITS, pteh & ASID_MASK,
                              PAGE_SIZE);
    } else {
        /* Native; use LDTLB directly */
        asm volatile (
            "ldc %0, pteh\n"
            "ldc %1, ptel\n"
            "ldtlb\n"
            :: "r"(pteh), "r"(ptel));
    }
}
#else
#define jcore_ldtlb(pteh, ptel) ({ \
    asm volatile ("ldc %0, pteh\n ldc %1, ptel\n ldtlb\n" \
                  :: "r"(pteh), "r"(ptel)); \
})
#endif
```

Every site that currently uses LDTLB directly is converted to use `jcore_ldtlb()`. The compiler inlines and optimizes; at runtime the right path is taken.

### 4.2 Boot-time detection

```c
/* arch/sh/kernel/setup.c additions */

void __init jcore_detect_virtualization(void)
{
    long ret;
    unsigned long version;
    
    /* Try HV_API_VERSION hypercall; if hypervisor exists, it answers */
    ret = jcore_hcall(HCALL_HV_API_VERSION, 0, 0, 0, 0, &version);
    if (ret == HV_RET_OK) {
        jcore_running_as_guest = true;
        pr_info("J-Core: running as guest under hypervisor v%lu\n", version);
    } else {
        jcore_running_as_guest = false;
        pr_info("J-Core: running on bare metal\n");
    }
}
```

The HCALL itself doesn't fault on bare metal — it just executes as a no-op (per Phase 3 hardware spec §3.1), returning some default value that doesn't match the expected version response.

Actually, more robust: HCALL on bare metal raises a trap if HEDR isn't configured. Detection: install a temporary trap handler that catches the HCALL exception and sets a flag. Run HCALL, check flag.

### 4.3 Hypercall stub

```c
/* arch/sh/kernel/jcore_hcall.S */

        .global jcore_hcall
jcore_hcall:
        /* r4 = code, r5 = arg0, r6 = arg1, r7 = arg2 */
        /* Args 3-6 on stack, ret slot also on stack */
        mov     r4, r0
        /* r1-r3 already loaded from r5-r7 */
        mov     r5, r1
        mov     r6, r2
        mov     r7, r3
        /* Load r4-r6 from stack args */
        mov.l   @(0, r15), r4
        mov.l   @(4, r15), r5
        mov.l   @(8, r15), r6
        
        hcall
        /* HCALL returns to here. r0 = result, r1-r3 = additional returns */
        
        /* Store additional returns to caller's slots */
        mov.l   @(12, r15), r4    /* &ret1 */
        cmp/eq  #0, r4
        bt      1f
        mov.l   r1, @r4
1:      rts
         nop
```

### 4.4 Virtual device drivers

For paravirt I/O (much faster than emulating real devices), the guest uses virtio-style drivers. The hypervisor exposes virtio devices over a shared-memory ring protocol, with notifications via HCALL_HV_VIRTIO_NOTIFY.

This is a significant chunk of work for the guest side but it's largely a port of existing virtio code (already in `drivers/virtio/`). No j-core-specific innovation; just glue.

## 5. Boot Sequence (with Hypervisor)

### 5.1 Host boot with hypervisor

1. Bootrom hands control to kernel entry (P1, no virt mode).
2. Kernel boots normally through Phase 1 sequence.
3. After `start_kernel()`, if `CONFIG_KVM` enabled and CPUINFO[16] indicates HYP_SUPPORT:
   - Allocate hypervisor's runtime state
   - Install hyperprivileged trap handlers at VBR_HYP
   - Set up the bootstrap HCALL handler
   - Execute first HCALL with code `ACTIVATE_HYP`
   - Hypervisor takes over, sets SR.HPRIV=1, returns to kernel in S-mode
   - From this point, the kernel runs as the "host OS" with the hypervisor active

Alternative: HYP_AT_RESET fuse set, hypervisor boots first, then HRTEs to load the Linux kernel.

### 5.2 Guest boot

1. Userspace tool (e.g., qemu-kvm-jcore) creates a VM via `/dev/kvm`.
2. VM is configured: memory region (becomes the RA space), vCPUs, virtio devices.
3. Guest kernel image is loaded into the RA space.
4. First `KVM_RUN` ioctl on a vCPU: hypervisor sets up TSB, ASID range, RA map, and HRTEs into the guest at its entry point.
5. Guest kernel boots through its standard Phase 1 sequence. If `CONFIG_JCORE_PARAVIRT`, it detects virtualization early and switches to hypercall-based MMU operations.
6. Guest runs to completion (or until killed).

## 6. Performance Optimizations

### 6.1 TSB warming

After a guest has been running for a while, its TSB has built up entries. On context switches between vCPUs of the same guest, the TSB stays valid (it's keyed on guest VA + ASID, which don't change across vCPU migration within a VM).

On vCPU migration across host CPUs, the TSB is shared (per-VM, not per-vCPU-per-CPU), so warming is preserved.

### 6.2 Permanent mappings

For pages the guest accesses frequently (its kernel text, page tables, frequently-touched data), the hypervisor can pre-install permanent TLB entries via `hv_mmu_perm_map`. These never need refilling, eliminating TLB miss cost entirely.

Guest's paravirt setup code calls `hv_mmu_perm_map` for its kernel text and key data structures during early init. Result: kernel-mode TLB miss rate approaches zero for the guest after warm-up.

### 6.3 Interrupt batching

Multiple virtual interrupts can be batched into a single HCALL_HV_INTR_INJECT, reducing trap rate.

### 6.4 Tight trap handlers

The hyperprivileged trap handlers should be tuned for cycle count. The 0x190 (guest LDTLB) handler can be inline assembly without C overhead, targeting <30 cycles total round-trip.

## 7. Suspend / Resume Considerations

For host suspend/resume:
- Hypervisor saves all VM state (vCPU registers, TSBs, RA maps, IOMMU state) before host suspends.
- On resume, hypervisor restores state, then resumes guest execution.

For guest suspend/resume:
- Guest can do its own suspend/resume independent of host.
- Hypervisor cooperates via virtual power management hypercalls.

Details are largely orthogonal to the MMU/hypervisor design; standard KVM PM patterns apply.

## 8. SMP Considerations

Each host CPU can be running either bare-metal code (HPRIV=0, MD=1) or be hosting a vCPU (HPRIV=1 during exits, HPRIV=0 during guest execution).

Each host CPU has its own per-CPU state:
- HEDR (configured per guest at vCPU-switch time)
- VBR_HYP (pointing at this CPU's hyp trap entry)
- Per-CPU current vCPU pointer
- Per-CPU ASID/generation state (Phase 1) — used by host kernel mappings; isolated from guest ASIDs by the partitioning

Migration of vCPUs across host CPUs requires:
- Save vCPU state on the old host CPU
- Send the vCPU descriptor to the new host CPU
- Restore vCPU state on the new host CPU
- Possibly flush stale TLB entries on the old CPU (or use the lazy mechanism from Phase 1)

This is standard KVM SMP work, not j-core specific.

## 9. Test Plan

### 9.1 Hypervisor correctness

- Boot a simple guest, verify it reaches its `init`.
- Memory isolation: guest cannot access host memory via any constructed RA.
- ASID isolation: two guests running concurrently cannot see each other's TLB entries.
- Privileged instruction trapping: guest's LDC SR (attempting to set HPRIV) is rejected.
- HCALL dispatch: each hypercall produces correct results and updates state correctly.

### 9.2 Performance

- Compare guest performance (paravirt vs shadow-MMU) on:
  - Kernel build benchmark
  - Network throughput (paravirt virtio-net)
  - File I/O (paravirt virtio-blk)
- Target: paravirt within 10% of bare-metal; shadow-MMU within 30%.

### 9.3 Robustness

- Stress with concurrent guests issuing TLB-intensive workloads.
- Verify hypervisor doesn't leak ASID slots, RA-map entries, or TSB pages.
- Long-running soak tests (24+ hours) to catch memory leaks.

### 9.4 Compatibility

- Verify Phase 1 binary kernels run as guests (via shadow MMU; slower but correct).
- Verify paravirt-aware kernels detect virtualization correctly.
- Verify both run unchanged on bare metal when no hypervisor is active.

## 10. Upstream Merge Plan

Significant work; suggest staged approach:

1. **Phase 3a — bare hypervisor mode in arch/sh/.** Get the host kernel able to enter and exit hyperprivileged mode. Test with assembly-only guest stubs.

2. **Phase 3b — minimal KVM with one guest.** Single-vCPU, no SMP guests, no device passthrough. Boot a stripped guest kernel under the hypervisor.

3. **Phase 3c — paravirt hooks in guest kernel.** Add CONFIG_JCORE_PARAVIRT; same kernel runs efficient as guest or natively.

4. **Phase 3d — full KVM.** Multi-vCPU guests, IOMMU passthrough via Phase 2, virtio devices, live migration if needed.

Coordinate with KVM maintainers and the SuperH maintainer. The work is sizable (~4500 lines new) but architecturally clean — it slots into the existing KVM framework without unusual demands.

## 11. Estimated Effort

- Hypervisor core (host side): 3-4 months one developer
- Guest paravirt: 1-2 months
- IOMMU integration: 1 month (mostly tying Phase 2 to per-VM contexts)
- Virtio devices: 2-3 months
- Testing, debugging, hardening: 3-4 months
- Upstream review: 6-12 months

**Total: ~12-18 months from start of Phase 3 software work to upstream merge.** Faster if developed in parallel with Phase 1 stabilization.

## 12. References

- *KVM/PowerPC documentation* in `Documentation/virt/kvm/ppc-pv.txt` — closest architectural analog (shadow MMU + paravirt)
- *Sun4v Hypervisor API specification* — concrete hypercall reference
- *KVM development documentation* in `Documentation/virt/kvm/`
- *Linux paravirt_ops infrastructure* — patterns for paravirt detection and dispatch
