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
                                 (implements the jcore_vintc model defined in
                                 ../aic/aic2-spec.md §5; emulates the AIC2 MMIO
                                 ABI per-guest and routes VINJ_SEND on the
                                 physical AIC2 when delivering to a running vCPU)
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
#define KVM_JCORE_MAX_VMS       16    /* SoC-wide guest limit */
#define KVM_JCORE_ASID_BASE   2048    /* host uses 0..2047; guests 2048+ */
#define KVM_JCORE_ASID_PER_VM  128    /* each guest gets 128 ASIDs */
                                      /* 16 guests * 128 = 2048;
                                       * total 4096 = full 12-bit space */

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
    
    /* Virtual interrupt controller state.
     * The MMIO ABI exposed to the guest is the AIC2 register file specified
     * at ../aic/aic2-spec.md Tier 2 (§5.6 jcore_vintc). The hypervisor traps
     * writes to host/hyperprivileged-only AIC2 offsets and emulates the
     * guest-visible offsets out of this struct. */
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

    /* Emulated-MMIO aperture (docs/hypervisor/hardware-spec.md §2.5) */
    unsigned long              hemub;
    unsigned long              hemum;

    /* Store queue lazy state (docs/sq/spec.md §7) */
    unsigned long              qacr[2];
    unsigned long              hsqcr;
    unsigned char              sq_buf[2][32];
};
```

The aperture and store-queue fields added here bring the per-vCPU footprint to 84 bytes
(4 + 4 + 8 + 4 + 64, assuming 32-bit `unsigned long` on J32; J64 would make it 104 bytes) beyond
the base register save area, alongside the existing lazy FPU (132-byte) and SIMD (272-byte)
context images (§4.3 of [../fpu/spec.md](../fpu/spec.md), §2.6 of
[../simd/spec.md](../simd/spec.md)). `hemub`/`hemum` mirror HEMUB/HEMUM 1:1 so VM entry can load
them directly; `hsqcr` and `sq_buf[2][32]` mirror HSQCR and the two 32-byte store-queue buffers so
a vCPU's in-flight burst state survives a VM exit that lands mid-queue (§7 of
[../sq/spec.md](../sq/spec.md)).

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

        .global jcore_hyp_entry_0x200   /* Guest emulated-MMIO trap */
jcore_hyp_entry_0x200:
        /* Hardware has already latched everything the exit path needs into
         * HMAR/HMCR/HMDR (docs/hypervisor/hardware-spec.md §2.6, §4.5); this
         * entry point does no decoding of its own. Save minimal scratch,
         * copy the hardware-latched fields into vcpu->arch, and exit to the
         * common EXIT_REASON_MMIO path (§3.10). */
        mov.l   r0, @-r15
        mov.l   r1, @-r15

        stc     hmar, r0             /* faulting virtual address */
        stc     hmcr, r1             /* {SQ, DIR, SIZE, BANK, REGN} */

        mov.l   handle_guest_mmio, r2
        jsr     @r2
         nop                         /* delay slot */

        /* handle_guest_mmio() copies HMAR/HMCR/HMDR (and, for SQ=1, the
         * store-queue buffers per docs/sq/spec.md §6) into vcpu->arch and
         * returns EXIT_REASON_MMIO to the C dispatch loop in §3.9; it never
         * calls HRTE itself — the in-kernel-serviceable case (§3.10) does. */
        mov.l   @r15+, r1
        mov.l   @r15+, r0
        rts
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
static DECLARE_BITMAP(asid_blocks, KVM_JCORE_MAX_VMS);

int kvm_arch_init_vm(struct kvm *kvm, unsigned long type)
{
    struct kvm_arch *kvm_arch;
    int block;
    
    kvm_arch = kzalloc(sizeof(*kvm_arch), GFP_KERNEL);
    if (!kvm_arch)
        return -ENOMEM;
    
    /* Allocate an ASID block */
    mutex_lock(&asid_alloc_lock);
    block = find_first_zero_bit(asid_blocks, KVM_JCORE_MAX_VMS);
    if (block >= KVM_JCORE_MAX_VMS) {
        mutex_unlock(&asid_alloc_lock);
        kfree(kvm_arch);
        return -ENOSPC;
    }
    set_bit(block, asid_blocks);
    mutex_unlock(&asid_alloc_lock);
    
    kvm_arch->asid_base  = KVM_JCORE_ASID_BASE + block * KVM_JCORE_ASID_PER_VM;
    kvm_arch->asid_count = KVM_JCORE_ASID_PER_VM;
    kvm->arch = kvm_arch;
    
    return 0;
}
```

**Partition arithmetic.** The 12-bit ASID space (4096 total) splits as host = 2048 (ASIDs 0..2047) + 16 guests × 128 (ASIDs 2048..4095). Exact fit; **the host retains 2048 ASIDs** (sufficient for kernel + qemu-style VMM processes) and each guest gets 128 (sufficient for a containerized workload of 10–100 processes per guest). For SoCs targeting fewer concurrent guests, raise `KVM_JCORE_ASID_PER_VM` accordingly (e.g. 8 guests × 256 = 2048, host keeps 2048). The previous design's 16 × 256 saturated the entire 4096-ASID space with zero room for the host; this revision fixes that. See [hypervisor/design-spec.md §3.7](design-spec.md) for the canonical partition-arithmetic table.

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

### 3.10 MMIO trap handling

A guest access whose translated physical address matches the emulation aperture
(`(PA & HEMUM) == HEMUB`) traps to `jcore_hyp_entry_0x200` (§3.3), per
[hardware-spec.md §4.5](hardware-spec.md). The C handler it calls:

```c
/* arch/sh/kvm/mmio.c */

int handle_guest_mmio(struct kvm_vcpu *vcpu)
{
    unsigned long hmcr = vcpu->arch.hmcr;   /* copied from HMCR by hyp_entry.S */
    unsigned long offset = vcpu->arch.hmar & ~vcpu->arch.hemum;  /* aperture offset */

    /* Fast path: does this VM's dispatch table know this offset? */
    struct jcore_mmio_dev *dev = jcore_mmio_lookup(vcpu->kvm, offset);

    if (dev && dev->in_kernel_ops) {
        /* In-kernel serviceable: compute the value, write HMDR if this was
         * a load, and return to the guest without ever reaching kvm_run.
         * Target: under 40 cycles round trip. */
        if (!(hmcr & HMCR_DIR))     /* DIR = 0: load */
            jcore_hv_write_hmdr(dev->in_kernel_ops->read(dev, offset, hmcr));
        else                        /* DIR = 1: store */
            dev->in_kernel_ops->write(dev, offset, vcpu->arch.hmdr, hmcr);

        return HANDLED_IN_KERNEL;   /* hyp_entry.S falls through to HRTE */
    }

    /* No in-kernel handler: needs the userspace device model. Populate
     * kvm_run->mmio directly from the hardware-latched fields — no guest
     * instruction is decoded here, because HMCR/HMAR/HMDR already contain
     * exactly the fields a decode would have produced (§4.5). */
    vcpu->run->exit_reason = KVM_EXIT_MMIO;
    vcpu->run->mmio.phys_addr = jcore_ra_to_hpa(vcpu, vcpu->arch.hmar);
    vcpu->run->mmio.len       = hmcr_size_bytes(hmcr);      /* from HMCR.SIZE */
    vcpu->run->mmio.is_write  = !!(hmcr & HMCR_DIR);         /* from HMCR.DIR */
    if (hmcr & HMCR_DIR)
        memcpy(vcpu->run->mmio.data, &vcpu->arch.hmdr, vcpu->run->mmio.len);

    return EXIT_REASON_MMIO;
}
```

Two outcomes, both reached without `hyp_entry.S` or `handle_guest_mmio()` decoding the trapping
instruction:

1. **In-kernel serviceable.** The handler computes the value, writes `HMDR` if `HMCR.DIR = 0`, and
   returns; `jcore_hyp_entry_0x200` executes `HRTE` directly and never enters the `kvm_run` outer
   loop of §3.9. Target: under 40 cycles round trip, since this path never leaves hyperprivileged
   mode.
2. **Needs the userspace device model.** The handler populates `kvm_run->mmio` (address, size,
   direction, data for a store) and returns `EXIT_REASON_MMIO` to the §3.9 dispatch loop, which
   sets `run->exit_reason = KVM_EXIT_MMIO` and returns to userspace exactly as it already does for
   `EXIT_REASON_MMIO` today.

**Why this reuses `EXIT_REASON_MMIO` rather than adding a new exit reason.** The aperture trap and
the pre-existing MMIO exit path in §3.9 both resolve to the same userspace contract — an address,
a size, a direction, and a data payload for stores. Carrying the store-queue-burst distinction
(`HMCR.SQ = 1`) as a flag inside the `kvm_run->mmio` payload, rather than inventing
`EXIT_REASON_MMIO_SQ` or similar, means the existing userspace MMIO handling in the VMM applies
unchanged: a device model that already implements `KVM_EXIT_MMIO` handling needs no new exit-reason
case to also handle store-queue bursts, only to notice the burst flag and read 32 bytes instead of
up to 4.

**Why the exit path performs no decoding.** `HMCR`, `HMAR`, and `HMDR` are populated entirely by
hardware at trap time (§2.6, §4.5 of [hardware-spec.md](hardware-spec.md)): `HMCR.DIR`,
`HMCR.SIZE`, `HMCR.REGN`, `HMCR.BANK`, and `HMCR.SQ` are exactly the fields a software instruction
decode would have produced from the faulting load or store, and `HMAR`/`HMDR` are exactly the
address and data fields. `handle_guest_mmio()` above does nothing but copy these hardware-latched
fields into `kvm_run->mmio` (or into the in-kernel device's read/write call) — there is no guest
instruction bytes to fetch or decode anywhere in this path, in either outcome.

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

    /* CPUINFO[16] (HYP_SUPPORT) is set only when this core was built with
     * the hyperprivileged extension at all; a plain bare-metal SH-4 core
     * reads 0 here and HCALL is not even a valid encoding to probe. */
    if (!(read_cpuinfo() & CPUINFO_HYP_SUPPORT)) {
        jcore_running_as_guest = false;
        pr_info("J-Core: no hypervisor extension, running on bare metal\n");
        return;
    }

    /* The extension is present, but this could still be an unhosted core
     * (hypervisor never installed) rather than a guest. Wrap the probe in
     * a temporary trap handler so an HCALL taken to the ordinary
     * supervisor vector (no hyperprivileged mode configured to receive
     * it) is caught instead of crashing the boot. */
    if (jcore_install_temp_hcall_trap_handler()) {
        jcore_running_as_guest = false;
        pr_info("J-Core: hypervisor extension present but unhosted\n");
        jcore_remove_temp_hcall_trap_handler();
        return;
    }

    ret = jcore_hcall(HCALL_HV_API_VERSION, 0, 0, 0, 0, &version);
    jcore_remove_temp_hcall_trap_handler();

    if (ret == HV_RET_OK) {
        jcore_running_as_guest = true;
        pr_info("J-Core: running as guest under hypervisor v%lu\n", version);
    } else {
        jcore_running_as_guest = false;
        pr_info("J-Core: running on bare metal\n");
    }
}
```

Per [hardware-spec.md §3.1](hardware-spec.md), what `HCALL` does when executed with
`SR.HPRIV = 1` already set is **implementer-defined**: it "behaves as a no-op (or, optionally,
raises illegal-instruction trap — implementer's choice; document the choice)." Either way, that
rule describes hypercalls issued from *already-hyperprivileged* code (e.g. the hypervisor calling
its own service routines) — it says nothing about bare-metal execution. On a machine with no
hypervisor installed, `SR.HPRIV` is hardwired to 0, so `HCALL` always traps normally, exactly as it
does under a real hypervisor's guest. Detection above therefore cannot rely on `HCALL`'s
HPRIV=1 behavior at all, since that behavior is not architecturally fixed — it uses `CPUINFO[16]`
(`HYP_SUPPORT`) together with a temporary trap handler installed around the probe instead, so that
a bare-metal `HCALL` trap (taken to the ordinary supervisor vector, since there is no
hyperprivileged mode to receive it) is caught and reported as "no hypervisor" rather than crashing.
This is precisely why the detection method is robust: it never depends on which of the two
implementer-defined choices a given core made.

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

### 4.5 Bare-metal guest support

§4.1–§4.4 assume a cooperating Linux guest that detects the hypervisor and switches to
paravirt-aware MMU and I/O paths. A Dreamcast image is the opposite case: a bare-metal SH-4 binary
with `MMUCR.AT = 0` (per [hardware-spec.md §4.4](hardware-spec.md)) and no knowledge that a
hypervisor exists at all. For this guest, the VMM — not the guest — does the work §4.1–§4.4 leave
to a cooperating kernel:

- **Build the guest's TLB mappings directly.** There is no guest page table to shadow (§3.6 does
  not apply); the VMM installs the guest's fixed memory map into the shadow/guest TLB itself, ahead
  of guest execution, driven by the worked example below rather than by guest-issued `LDTLB` traps.
- **Install both cached and uncached views of guest RAM** (`PTEL.C = 1` and `PTEL.C = 0`) at the
  guest's expected addresses, since the guest's own code assumes both P1/P2-style aliases exist and
  never sets them up itself.
- **Allocate device pages into the emulation aperture and ordinary pages elsewhere.** Only the
  physical range the VMM wants trapped needs to fall inside `HEMUB`/`HEMUM`; guest RAM and VRAM are
  mapped straight to host RAM and never trap.
- **Set `HEMUB`/`HEMUM` on VM entry** from the per-vCPU `hemub`/`hemum` fields added to
  `kvm_vcpu_arch` in §3.2.
- **Never expect the guest to execute `HCALL`.** A bare-metal image was compiled with no knowledge
  of hypercalls; the entire paravirt surface of §4.1–§4.3 is unused for this guest class, and the
  MMU and I/O paths above are the VMM's sole levers.

**Dreamcast guest memory map (worked example):**

| Region | Guest address | Size | Mapping |
|---|---|---|---|
| Main RAM, cached | `0x8C000000` | 16 MB | host RAM, `PTEL.C = 1` |
| Main RAM, uncached | `0xAC000000` | 16 MB | same frames, `PTEL.C = 0` |
| VRAM | `0xA5000000` | 8 MB | host RAM |
| Sound RAM | `0xA0800000` | 2 MB | host RAM |
| TA submission window | per `QACR` | — | host ring buffer, [../sq/spec.md §6](../sq/spec.md) |

The Dreamcast register file at `0xA05F6800`–`0xA05F8000` (holobox/AICA/GD-ROM control and status
registers) does not map uniformly into one bucket. It is split into the emulation aperture **per
page**, not per register:

- Pages holding only pure-storage registers (status bits the guest merely reads back, counters,
  configuration fields with no external effect) map to host RAM and never trap.
- Pages holding **any** side-effecting register (TA kickoff, DMA start, GD-ROM command issue,
  interrupt acknowledge) map into the aperture in their entirety, so that register traps into the
  hypervisor.

**Consequence, stated honestly:** because the split is per page rather than per register, a
pure-storage register that happens to share a page with a side-effecting register still traps on
every access, even though its own value never needs hypervisor involvement. This is pure overhead
with no correctness benefit, and it argues for choosing the smallest page size the MMU supports for
this register block specifically, to minimize how many pure-storage registers get dragged into the
aperture by a page-mate. Producing the actual side-effect classification for each register in
`0xA05F6800`–`0xA05F8000` — which ones are pure-storage and which are side-effecting — is VMM work
outside the scope of this spec; it depends on the target console's device model, not on the
hypervisor architecture.

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

### 9.5 Dreamcast validation stages

Four ordered stages, each with its own pass criterion. Later stages assume earlier ones pass.

1. **Synthetic guest, cosim.** A guest built to deliberately exercise each trap class the
   emulated-MMIO path can take — byte/word/longword loads and stores, both register banks, an SQ
   burst that lands inside the aperture, and an SQ burst that lands outside it. Pass criterion:
   every verification point listed in [hardware-spec.md §9](hardware-spec.md) (items 10–15) is
   observed at least once in the cosim trace, with the expected `HMAR`/`HMCR`/`HMDR` values at each
   trap.
2. **Homebrew, RAM-resident.** A small homebrew Dreamcast ELF that touches only main RAM (cached
   and uncached aliases) and does no TA/AICA/GD-ROM access. Pass criterion: the binary runs
   unmodified to completion with zero emulated-MMIO traps, confirming the §4.5 memory map by
   itself introduces no spurious aperture hits.
3. **Homebrew, TA-submitting.** A homebrew demo that submits polygon data to the tile accelerator
   via the store-queue burst path (§4.5 worked example, TA submission window). Pass criterion: the
   SQ path takes **zero traps**, verified by the hypervisor's exit counter — the entire TA
   submission burst goes straight to the host ring buffer with no aperture hit, which is the
   headline performance claim of the store-queue design (§6, [../sq/spec.md](../sq/spec.md)) and
   must hold even though the TA kickoff register itself, on the same or an adjacent register page,
   does trap.
4. **Commercial title.** A full commercial Dreamcast title runs at playable speed under the
   hypervisor. Pass criterion: subjectively playable frame rate, with the emulated-MMIO exit rate
   per frame recorded so later hardware or software optimization work has a baseline to improve
   against.

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
