# J-Core IOMMU Linux Implementation Specification (Phase 2)

**Status:** Draft  
**Scope:** Linux kernel changes to support the J-Core IOMMU  
**Audience:** Kernel developer implementing the IOMMU driver  
**Prerequisites:** Phase 1 Linux spec (`03-linux-spec.md`), Phase 2 design spec, Phase 2 hardware spec

---

## 1. Scope and Strategy

This document specifies the Linux kernel additions needed to support the J-Core IOMMU. The strategy is:

- **Implement a single `iommu_ops` driver** that exposes the IOMMU via Linux's generic IOMMU framework
- **Hook the DMA-API** to route through the IOMMU automatically for devices marked in device tree
- **Require no driver changes** in existing device drivers — they continue to use `dma_map_single()`, `dma_alloc_coherent()`, etc.
- **Provide device-tree bindings** so each DMA-capable device's BMID is declared declaratively
- **Match J32 and J64 from a single source tree**, parameterized by `unsigned long` width

The work builds on Linux's mature IOMMU framework (`drivers/iommu/`). Most of the heavy lifting — IOVA allocation, generic domain management, DMA-API integration — comes from the framework. The driver implements the hardware-specific operations and the framework handles the rest.

## 2. Configuration

### 2.1 Kconfig additions

In `drivers/iommu/Kconfig`:

```kconfig
config JCORE_IOMMU
    tristate "J-Core IOMMU support"
    depends on CPU_SUBTYPE_JCORE
    select IOMMU_API
    select IOMMU_DMA
    default y
    help
      Enable support for the J-Core SoC IOMMU. The IOMMU provides
      memory isolation for DMA-capable peripherals and enables
      virtually contiguous DMA buffers. Required for any system
      with peripherals that DMA to user-space-allocated memory
      or that need scatter-gather support.
```

In `arch/sh/Kconfig`, add:

```kconfig
config ARCH_HAS_IOMMU
    def_bool y if CPU_SUBTYPE_JCORE

config IOMMU_DMA
    def_bool y if JCORE_IOMMU
```

### 2.2 Build integration

In `drivers/iommu/Makefile`:

```make
obj-$(CONFIG_JCORE_IOMMU)       += jcore-iommu.o
```

## 3. Device Tree Bindings

### 3.1 IOMMU node

```yaml
# Documentation/devicetree/bindings/iommu/jcore,iommu.yaml

properties:
  compatible:
    const: jcore,iommu-v1

  reg:
    description: MMIO region for IOMMU registers (4 KB)
    maxItems: 1

  interrupts:
    description: Fault interrupt line
    maxItems: 1

  "#iommu-cells":
    const: 1
    description: |
      Each device's iommus property carries one cell: its BMID
      (0-255).

required:
  - compatible
  - reg
  - interrupts
  - "#iommu-cells"
```

### 3.2 Example: IOMMU in SoC dts

```dts
soc {
    #address-cells = <1>;
    #size-cells = <1>;

    iommu: iommu@ff010000 {
        compatible = "jcore,iommu-v1";
        reg = <0xff010000 0x1000>;
        interrupts = <16>;
        #iommu-cells = <1>;
    };

    ethernet0: ethernet@ff200000 {
        compatible = "jcore,eth-v1";
        reg = <0xff200000 0x1000>;
        interrupts = <17>;
        iommus = <&iommu 3>;     /* BMID 3 */
    };

    display0: display@ff300000 {
        compatible = "jcore,display-v1";
        reg = <0xff300000 0x1000>;
        interrupts = <18>;
        iommus = <&iommu 4>;     /* BMID 4 */
    };

    usb0: usb@ff400000 {
        compatible = "jcore,usb-v1";
        reg = <0xff400000 0x1000>;
        interrupts = <19>;
        iommus = <&iommu 5>;     /* BMID 5 */
    };
};
```

A device without an `iommus` property is treated as bypass-only: it can DMA with physical addresses but receives no IOMMU services. This is appropriate for trusted devices and during early boot.

## 4. Driver Architecture

### 4.1 File layout

```
drivers/iommu/
    jcore-iommu.c           main driver, ~600 lines
    jcore-iommu.h           private definitions, ~100 lines
```

No other files in `drivers/iommu/` are touched. The integration with the generic framework happens entirely through the `iommu_ops` vtable.

### 4.2 Data structures

```c
/* drivers/iommu/jcore-iommu.h */

#define JCORE_IOMMU_MAX_BMID    256
#define JCORE_IOMMU_MAX_ENTRIES 64

/* Per-IOMMU-instance state */
struct jcore_iommu {
    struct device           *dev;
    void __iomem            *base;
    int                      irq;
    unsigned int             num_entries;
    
    /* Track which IOTLB entries are in use. Protected by lock. */
    DECLARE_BITMAP(entry_used, JCORE_IOMMU_MAX_ENTRIES);
    
    /* Map BMID -> jcore_iommu_master (one per device using this IOMMU) */
    struct jcore_iommu_master *masters[JCORE_IOMMU_MAX_BMID];
    
    spinlock_t               lock;
    struct iommu_device      iommu;     /* generic framework handle */
};

/* Per-device state */
struct jcore_iommu_master {
    struct jcore_iommu       *iommu;
    u8                        bmid;
    struct jcore_iommu_domain *domain;  /* domain currently attached */
};

/* Per-domain state */
struct jcore_iommu_domain {
    struct iommu_domain      domain;     /* generic framework handle */
    struct jcore_iommu       *iommu;
    
    /* Per-BMID list of (iova, pfn, size) mappings owned by this domain.
     * Used to support remove/replace of mappings when domain teardown.
     * Implementation: rbtree keyed by iova. */
    struct rb_root           mappings;
    
    /* Set of BMIDs attached to this domain. */
    DECLARE_BITMAP(bmids, JCORE_IOMMU_MAX_BMID);
};
```

### 4.3 The iommu_ops vtable

```c
/* drivers/iommu/jcore-iommu.c */

static const struct iommu_ops jcore_iommu_ops = {
    .capable        = jcore_iommu_capable,
    .domain_alloc   = jcore_iommu_domain_alloc,
    .domain_free    = jcore_iommu_domain_free,
    .attach_dev     = jcore_iommu_attach_dev,
    .detach_dev     = jcore_iommu_detach_dev,
    .map            = jcore_iommu_map,
    .unmap          = jcore_iommu_unmap,
    .iova_to_phys   = jcore_iommu_iova_to_phys,
    .flush_iotlb_all = jcore_iommu_flush_iotlb_all,
    .iotlb_sync     = jcore_iommu_iotlb_sync,
    .of_xlate       = jcore_iommu_of_xlate,
    .probe_device   = jcore_iommu_probe_device,
    .release_device = jcore_iommu_release_device,
    .device_group   = jcore_iommu_device_group,
    .pgsize_bitmap  = SZ_16K | SZ_64K | SZ_256K | SZ_1M | SZ_4M |
                      SZ_16M | SZ_64M | SZ_256M | SZ_1G,
};
```

The framework calls these as devices probe, drivers attach, and `dma_map_*` calls flow through. Most callbacks are 20-50 lines; the interesting ones are `.map`, `.unmap`, and the probe path.

## 5. Key Operations in Detail

### 5.1 Driver probe

Called once at boot when the IOMMU's device-tree node matches. Allocates state, maps MMIO, requests IRQ, registers with the framework.

```c
static int jcore_iommu_probe(struct platform_device *pdev)
{
    struct jcore_iommu *iommu;
    struct resource *res;
    u32 version;
    int ret;
    
    iommu = devm_kzalloc(&pdev->dev, sizeof(*iommu), GFP_KERNEL);
    if (!iommu)
        return -ENOMEM;
    
    iommu->dev = &pdev->dev;
    spin_lock_init(&iommu->lock);
    
    res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
    iommu->base = devm_ioremap_resource(&pdev->dev, res);
    if (IS_ERR(iommu->base))
        return PTR_ERR(iommu->base);
    
    iommu->irq = platform_get_irq(pdev, 0);
    if (iommu->irq < 0)
        return iommu->irq;
    
    /* Read version register, determine IOTLB size */
    version = readl(iommu->base + IOMMU_VERSION);
    iommu->num_entries = (version >> 16) & 0xFF;
    if (iommu->num_entries == 0 || iommu->num_entries > JCORE_IOMMU_MAX_ENTRIES)
        return -EINVAL;
    
    /* Install fault interrupt handler */
    ret = devm_request_irq(&pdev->dev, iommu->irq, jcore_iommu_fault_irq,
                          IRQF_SHARED, "jcore-iommu", iommu);
    if (ret)
        return ret;
    
    /* Reset state: clear IOTLB, disable all bypasses we'll manage,
     * enable IOMMU, enable fault IRQ */
    writel(IOMMU_CTRL_INVALIDATE_ALL, iommu->base + IOMMU_CTRL);
    /* Wait for INVALIDATE_BUSY to clear */
    while (readl(iommu->base + IOMMU_STATUS) & STATUS_INVALIDATE_BUSY)
        cpu_relax();
    
    /* Enable IOMMU + fault IRQ. Bypass mask still all-set; we'll clear
     * per BMID as devices attach. */
    writel(IOMMU_CTRL_ENABLE | IOMMU_CTRL_FAULT_IRQ_EN |
           IOMMU_CTRL_DEFAULT_PERM_RW,
           iommu->base + IOMMU_CTRL);
    
    /* Register with the generic IOMMU framework */
    ret = iommu_device_sysfs_add(&iommu->iommu, &pdev->dev, NULL,
                                 "jcore-iommu");
    if (ret)
        return ret;
    
    ret = iommu_device_register(&iommu->iommu, &jcore_iommu_ops, &pdev->dev);
    if (ret) {
        iommu_device_sysfs_remove(&iommu->iommu);
        return ret;
    }
    
    /* Add to platform bus so device probing routes through us */
    bus_set_iommu(&platform_bus_type, &jcore_iommu_ops);
    
    platform_set_drvdata(pdev, iommu);
    dev_info(&pdev->dev, "J-Core IOMMU registered, %u IOTLB entries\n",
             iommu->num_entries);
    return 0;
}
```

### 5.2 Mapping a buffer (.map)

Called by the generic framework when `dma_map_single()` or similar requests an IOVA→PA mapping. The framework has already allocated an IOVA range and chosen a page size from `pgsize_bitmap`.

```c
static int jcore_iommu_map(struct iommu_domain *iommu_domain,
                           unsigned long iova, phys_addr_t paddr,
                           size_t pgsize, int prot, gfp_t gfp)
{
    struct jcore_iommu_domain *domain = to_jcore_domain(iommu_domain);
    struct jcore_iommu *iommu = domain->iommu;
    int entry_idx, bmid;
    u32 tag_lo, tag_hi, data_lo, data_hi;
    u8 page_mask;
    unsigned long flags;
    
    /* Convert page size to PageMask encoding (log4 of size/4KB) */
    page_mask = ilog2(pgsize / SZ_4K) / 2;
    
    /* Allocate an IOTLB entry */
    spin_lock_irqsave(&iommu->lock, flags);
    entry_idx = find_first_zero_bit(iommu->entry_used, iommu->num_entries);
    if (entry_idx >= iommu->num_entries) {
        spin_unlock_irqrestore(&iommu->lock, flags);
        return -ENOSPC;
    }
    set_bit(entry_idx, iommu->entry_used);
    
    /* For each BMID attached to this domain, write an IOTLB entry.
     * In the common case, only one BMID is attached. */
    for_each_set_bit(bmid, domain->bmids, JCORE_IOMMU_MAX_BMID) {
        tag_lo = (iova & GENMASK(31, 14)) | (page_mask << 10);
        tag_hi = TAG_VALID |
                 ((iova >> 32) & 0xFF) << 16 |
                 (bmid & 0xFF) << 8;
        data_lo = (paddr & GENMASK(31, 14));
        if (prot & IOMMU_READ)  data_lo |= DATA_READ;
        if (prot & IOMMU_WRITE) data_lo |= DATA_WRITE;
        data_hi = ((paddr >> 32) & 0xFF) << 16;
        if (prot & IOMMU_CACHE) data_hi |= DATA_CACHEABLE;
        
        writel(entry_idx, iommu->base + IOTLB_INDEX);
        writel(tag_lo,    iommu->base + IOTLB_TAG_LO);
        writel(tag_hi,    iommu->base + IOTLB_TAG_HI);
        writel(data_lo,   iommu->base + IOTLB_DATA_LO);
        writel(data_hi,   iommu->base + IOTLB_DATA_HI);
        writel(IOTLB_CMD_WRITE_ENTRY << 28, iommu->base + IOTLB_CMD);
        
        /* Wait for write to commit */
        while (readl(iommu->base + IOMMU_STATUS) & STATUS_IOTLB_WRITE_BUSY)
            cpu_relax();
    }
    
    /* Record the mapping in the domain's rbtree for later unmap */
    add_mapping(domain, iova, paddr, pgsize, entry_idx);
    
    spin_unlock_irqrestore(&iommu->lock, flags);
    return 0;
}
```

**Note on multiple BMIDs:** in practice almost all domains have exactly one attached BMID (one device per domain). Linux's generic framework groups devices into domains based on `device_group` callback; we return a unique group per device unless the device tree explicitly groups them. So the inner loop iterates once typically.

### 5.3 Unmapping (.unmap)

```c
static size_t jcore_iommu_unmap(struct iommu_domain *iommu_domain,
                                unsigned long iova, size_t size,
                                struct iommu_iotlb_gather *gather)
{
    struct jcore_iommu_domain *domain = to_jcore_domain(iommu_domain);
    struct jcore_iommu *iommu = domain->iommu;
    struct jcore_iommu_mapping *m;
    unsigned long flags;
    
    spin_lock_irqsave(&iommu->lock, flags);
    m = find_mapping(domain, iova);
    if (!m || m->size != size) {
        spin_unlock_irqrestore(&iommu->lock, flags);
        return 0;
    }
    
    /* Invalidate the IOTLB entry */
    writel(m->entry_idx, iommu->base + IOTLB_INDEX);
    writel(IOTLB_CMD_INVALIDATE_ENTRY << 28, iommu->base + IOTLB_CMD);
    
    /* Free the slot */
    clear_bit(m->entry_idx, iommu->entry_used);
    remove_mapping(domain, m);
    
    spin_unlock_irqrestore(&iommu->lock, flags);
    return size;
}
```

`iotlb_sync` is a no-op for our IOMMU because there's no buffered write queue — entries commit synchronously.

### 5.4 Device attach

```c
static int jcore_iommu_attach_dev(struct iommu_domain *iommu_domain,
                                  struct device *dev)
{
    struct jcore_iommu_domain *domain = to_jcore_domain(iommu_domain);
    struct jcore_iommu_master *master = dev_iommu_priv_get(dev);
    struct jcore_iommu *iommu = master->iommu;
    unsigned long flags;
    u32 reg, mask;
    
    spin_lock_irqsave(&iommu->lock, flags);
    
    /* Mark this BMID as part of this domain */
    set_bit(master->bmid, domain->bmids);
    master->domain = domain;
    iommu->masters[master->bmid] = master;
    
    /* Clear the bypass bit for this BMID, so it goes through IOTLB */
    reg = readl(iommu->base + BMID_BYPASS_BASE + (master->bmid / 8));
    mask = ~BIT(master->bmid % 32);
    reg &= mask;
    writel(reg, iommu->base + BMID_BYPASS_BASE + (master->bmid / 8));
    
    spin_unlock_irqrestore(&iommu->lock, flags);
    return 0;
}
```

### 5.5 Fault interrupt handler

```c
static irqreturn_t jcore_iommu_fault_irq(int irq, void *data)
{
    struct jcore_iommu *iommu = data;
    u32 status = readl(iommu->base + IOMMU_STATUS);
    u8 bmid;
    u64 iova;
    u32 info;
    
    if (!(status & STATUS_FAULT_PENDING))
        return IRQ_NONE;
    
    bmid = readl(iommu->base + FAULT_BMID) & 0xFF;
    iova = (u64)readl(iommu->base + FAULT_IOVA_LO) |
           ((u64)readl(iommu->base + FAULT_IOVA_HI) << 32);
    info = readl(iommu->base + FAULT_INFO);
    
    dev_warn(iommu->dev,
             "DMA fault from BMID %u at IOVA 0x%llx: %s %s (count %u)\n",
             bmid, iova,
             (info & FAULT_INFO_RW) ? "write" : "read",
             fault_type_str((info >> 4) & 0xF),
             info >> 16);
    
    /* If this BMID has a registered master, report via iommu framework */
    if (iommu->masters[bmid] && iommu->masters[bmid]->dev) {
        struct iommu_fault_event evt = {
            .fault.type = IOMMU_FAULT_DMA_UNRECOV,
            .fault.event.reason = IOMMU_FAULT_REASON_PASID_INVALID,
            .fault.event.addr = iova,
        };
        iommu_report_device_fault(iommu->masters[bmid]->dev, &evt);
    }
    
    /* Clear fault status */
    writel(STATUS_FAULT_PENDING | STATUS_FAULT_OVERFLOW,
           iommu->base + IOMMU_STATUS);
    
    return IRQ_HANDLED;
}
```

The framework's `iommu_report_device_fault` triggers any registered fault handlers — typically used by drivers to disable themselves cleanly on misbehavior.

## 6. Generic Framework Integration

Most of the heavy lifting comes "for free" from the generic framework once the driver is registered. Specifically:

- **IOVA allocation:** the framework maintains an IOVA bitmap per domain and finds free ranges on `dma_map_*` calls.
- **Optimal page-size selection:** the framework consults `pgsize_bitmap` and picks the largest page size that fits the buffer's size and alignment.
- **DMA-API integration:** `dma_map_single`, `dma_map_sg`, `dma_alloc_coherent` all route through the framework, which calls our `.map` and friends.
- **Domain management:** each device gets its own domain (or shares if `device_group` indicates) and IOVA space.
- **sysfs entries:** `/sys/kernel/iommu_groups/` automatically populates with diagnostic information.

The result: a driver written against the standard DMA-API works on j-core with IOMMU enabled with **no source changes**. The IOMMU is transparent to existing code.

## 7. Boot Sequence

1. IOMMU device tree node is parsed; `jcore_iommu_probe` runs.
2. IOMMU registers initialize: invalidate IOTLB, enable, enable fault IRQ. All BMID bypasses still set.
3. As DMA-capable devices probe, their device tree `iommus` property triggers `of_xlate` callback, which creates a `jcore_iommu_master` and binds it to the device.
4. The generic framework allocates a default domain for each device (or per-group).
5. On first DMA operation, the framework calls `.attach_dev` (clearing bypass for this BMID), then `.map` (installing IOTLB entries).
6. Steady-state DMA flows through the IOMMU.

Devices that need DMA *before* the IOMMU is probed (rare: maybe an early-init DMA from bootrom) work because the IOMMU starts with all bypasses enabled. Only after attach are bypasses cleared, requiring proper mapping.

## 8. PM and SMP Considerations

### 8.1 Suspend / resume

The IOMMU has soft state that doesn't survive S2RAM: IOTLB entries, BMID_BYPASS bitmap, IOMMU_CTRL. Add a `syscore_ops`:

```c
struct jcore_iommu_pm_state {
    u32 ctrl;
    u8  bypass[32];   /* 256-bit bitmap */
    /* IOTLB entries reconstructed from domain->mappings rbtree */
};
static struct jcore_iommu_pm_state pm_state;

static int jcore_iommu_pm_suspend(void)
{
    struct jcore_iommu *iommu = the_iommu;  /* singleton in practice */
    int i;
    pm_state.ctrl = readl(iommu->base + IOMMU_CTRL);
    for (i = 0; i < 8; i++)
        ((u32 *)pm_state.bypass)[i] = readl(iommu->base + BMID_BYPASS_BASE + i*4);
    return 0;
}

static void jcore_iommu_pm_resume(void)
{
    struct jcore_iommu *iommu = the_iommu;
    int i;
    
    /* IOTLB is empty after S2RAM. Restore by walking each domain's
     * mapping list and reprogramming. */
    writel(IOMMU_CTRL_INVALIDATE_ALL, iommu->base + IOMMU_CTRL);
    while (readl(iommu->base + IOMMU_STATUS) & STATUS_INVALIDATE_BUSY)
        cpu_relax();
    
    /* Restore bypass mask */
    for (i = 0; i < 8; i++)
        writel(((u32 *)pm_state.bypass)[i],
               iommu->base + BMID_BYPASS_BASE + i*4);
    
    /* Reprogram IOTLB from domain mappings */
    for_each_iommu_domain(d) {
        struct jcore_iommu_domain *jd = to_jcore_domain(d);
        struct jcore_iommu_mapping *m;
        for_each_mapping(jd, m) {
            reprogram_iotlb_entry(iommu, m);
        }
    }
    
    /* Restore control register last */
    writel(pm_state.ctrl, iommu->base + IOMMU_CTRL);
}

static struct syscore_ops jcore_iommu_syscore_ops = {
    .suspend = jcore_iommu_pm_suspend,
    .resume  = jcore_iommu_pm_resume,
};
```

The reconstruction approach (vs. saving every IOTLB entry to memory) is more code but avoids issues if the IOTLB layout changes between save and restore. In practice the IOMMU is small enough that both approaches work.

### 8.2 SMP

The IOMMU is a single SoC-level block, not per-CPU. All CPUs see the same IOMMU state. The driver uses `spin_lock_irqsave` to serialize MMIO access from different CPUs.

CPU hotplug doesn't affect the IOMMU. Onlining or offlining a CPU has no impact on IOTLB state or pending DMA mappings.

## 9. Existing Driver Migration

Drivers that already use the DMA-API need only one change: their device tree node needs an `iommus` property declaring which BMID they use. The driver source is untouched.

Drivers that *don't* use the DMA-API — e.g., legacy framebuffer drivers that map physical memory directly via `ioremap` and let the device read raw PA — need to be converted to use `dma_alloc_coherent` or `dma_map_resource` to work behind the IOMMU. For j-core's existing driver set (post-MMU port), all expected drivers will be DMA-API users.

### 9.1 Recommended driver checklist

For each device that should be IOMMU-protected:

1. Add `iommus = <&iommu N>` to its device tree node with appropriate BMID.
2. Verify driver uses `dma_map_single`, `dma_map_sg`, or `dma_alloc_coherent` for all DMA buffers.
3. Confirm driver does not bypass the DMA-API (no direct `virt_to_phys`-then-DMA patterns).
4. Test under stress (high allocation pressure, scatter-gather edge cases).
5. Verify fault diagnostics work: deliberately trigger a missing-mapping and confirm dmesg log appears.

## 10. Test Plan

### 10.1 Unit tests

- IOMMU probe completes successfully on boot.
- Domain allocation and free; no leaks under repeated cycles.
- `.map` and `.unmap` install and remove IOTLB entries correctly.
- `.iova_to_phys` returns the right PA.
- Attach and detach toggle the BMID_BYPASS bit correctly.

### 10.2 Functional tests

- Allocate a 16 KB DMA buffer; verify device can read what CPU wrote and vice versa.
- Allocate a 16 MB DMA buffer (forcing superpage mapping); verify same.
- Run `dma_map_sg` on a scatter list spanning 32 fragments; verify all visible to device.
- Repeatedly `dma_alloc_coherent` / `dma_free_coherent` over 100k cycles; verify no IOTLB leaks.

### 10.3 Fault tests

- Manually corrupt a device's DMA descriptor to point at unmapped IOVA; verify fault is logged with correct BMID and IOVA.
- Stress with high IOTLB pressure (allocate many small buffers to exhaust IOTLB); verify graceful `-ENOSPC` rather than silent corruption.

### 10.4 Performance tests

- Saturate Ethernet at 1 Gbps; measure CPU utilization with and without IOMMU. Difference should be <1%.
- Stream 1080p60 video to framebuffer; verify zero dropped frames over 1 hour.
- Microbenchmark `dma_map_single` / `dma_unmap_single` cost. Target: <500 ns each on a 100 MHz J-Core.

### 10.5 PM and lifecycle tests

- Suspend / resume 100 cycles; verify IOMMU state is restored, devices continue working.
- kexec from one kernel to another; verify new kernel initializes IOMMU correctly even if old kernel had mappings.
- `cpu_up` / `cpu_down` cycles; verify no effect on IOMMU.

## 11. Open Questions

- Should we expose IOTLB statistics (hit/miss counters) via debugfs? Helpful for tuning but adds RTL complexity. **Recommendation:** add in Phase 2b after Phase 2a stabilizes.
- Should each device get its own domain by default, or should related devices (e.g., Ethernet RX and TX channels of the same MAC) share? **Recommendation:** unique per-device by default; let device tree group via `iommu-map` if needed.
- What's the right behavior when IOTLB fills? Currently we return `-ENOSPC` to the framework. **Recommendation:** could implement an "evict LRU" policy in software if this becomes common; profile first.
- Should we attempt zero-copy from user-space allocated memory (i.e., let userspace allocations be directly DMA-able via IOMMU)? **Recommendation:** defer to Phase 3; requires more thought about lifetime and security.

## 12. Upstream Merge Plan

The IOMMU driver is largely self-contained and doesn't modify the rest of the kernel. Suggested merge approach:

1. Submit the device tree binding (`Documentation/devicetree/bindings/iommu/jcore,iommu.yaml`) to devicetree-spec maintainers.
2. Submit the driver to the IOMMU subsystem maintainer (Joerg Roedel).
3. Submit the `arch/sh/` Kconfig hooks to the SuperH maintainer.

The work parallels the Phase 1 merges and can proceed independently once Phase 1 is upstream.

## 13. Estimated Effort

- Driver development: ~2-3 weeks for a developer familiar with Linux IOMMU framework
- Device tree updates for existing devices: ~1 week
- Testing: ~2 weeks including stress and PM scenarios
- Upstream review iteration: ~2-3 months calendar time
- **Total: ~4-6 months from start to upstream merge**

Faster if developed in parallel with Phase 1 hardware bring-up — most of the Linux work can be tested against an emulator or FPGA before silicon is final.
