# J-Core IOMMU Linux Implementation Specification (Phase 2)

**Status:** Draft  
**Scope:** Linux kernel changes to support the J-Core IOMMU  
**Audience:** Kernel developer implementing the IOMMU driver  
**Prerequisites:** Phase 1 Linux spec (`03-linux-spec.md`), Phase 2 design spec, Phase 2 hardware spec

> **Revised for default-deny and re-checked against the kernel — 2026-09-09, Wave-3
> task C2d.** The hardware this driver targets now denies by default
> ([iommu/hardware-spec.md §3.10](hardware-spec.md), `I-R1`–`I-R10`), which changes
> the probe path, the attach path, the teardown path that did not exist, and the boot
> sequence. §2a and §4.3a are new and are the more urgent read: **the driver sketch
> below is written against a kernel API that no longer exists**, and the framework
> has since grown the two mechanisms §5.4a needs.
>
> No `jcore` IOMMU driver exists in `linux@origin/jcore`
> (`drivers/iommu` contains no `jcore*` file and a case-insensitive grep for `jcore`
> over that directory returns nothing), and no IOMMU hardware exists to drive.

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
```

### 2a. What the kernel actually says, and why the Kconfig above cannot work as written

Checked against `linux@origin/jcore`:

- **`IOMMU_DMA` cannot be defined in `arch/sh/Kconfig`.** It already exists, at
  `drivers/iommu/Kconfig:153-154`, as `def_bool ARM64 || X86 || S390`. A second
  `config IOMMU_DMA` in `arch/sh/Kconfig` is a redefinition, and `select IOMMU_DMA`
  from `JCORE_IOMMU` selects a symbol whose value is pinned by that `def_bool` —
  **SH is not in the list**, so the `dma-iommu.c` glue this whole document assumes is
  not buildable on SH. The change belongs in `drivers/iommu/Kconfig`, adding `SUPERH`
  (or, better, converting the `def_bool` to something a driver may `select`), and it
  is a patch to a shared file that the *"No other files in `drivers/iommu/` are
  touched"* claim in §4.1 does not cover.
- **`arch/sh` selects no IOMMU symbol at all today** — a case-insensitive grep for
  `IOMMU` over `arch/sh/**Kconfig*` returns nothing.
- `IOMMU_SUPPORT` itself (`drivers/iommu/Kconfig:14-17`) is `depends on MMU`,
  `default y`, so a J4 with the MMU can enable it.
- The default-domain choice is `IOMMU_DEFAULT_DMA_STRICT` /
  `IOMMU_DEFAULT_DMA_LAZY` / `IOMMU_DEFAULT_PASSTHROUGH`
  (`drivers/iommu/Kconfig:96-146`); there is no plain `IOMMU_DEFAULT_DMA`. **J-Core
  must not ship `IOMMU_DEFAULT_PASSTHROUGH`**, and must be aware that
  `iommu.passthrough=` on the command line (`drivers/iommu/iommu.c:806`) reaches the
  same place at runtime — a boot parameter that turns every device's default domain
  into an identity domain is a software `SUPER_BYPASS`, and unlike the hardware one
  ([hardware-spec.md §3.10](hardware-spec.md) `I-R4`) it has no lock. An integration
  that cares should refuse to build with it or refuse to honour it.

### 2b. The OF path fails **open**, and hardware default-deny is what covers it

A device whose DT node has no `iommus` property gets `-ENODEV` from
`of_iommu_configure()` (`drivers/iommu/of_iommu.c:60-77`, whose loop over
`of_parse_phandle_with_args(…, "iommus", …)` never executes and returns the
`err = -ENODEV` it was initialised with). Its caller
`of_dma_configure_id()` (`drivers/of/device.c:151-167`) then **swallows the error**,
under a comment reading *"Take all other IOMMU errors to mean we'll just carry on
without it"*, sets up plain `dma-direct` ops and returns 0.

So a DMA-capable device that someone forgot to give an `iommus` property to is
silently configured for **raw physical DMA**, with no warning and no failed probe.
This is the "unclaimed devices stay unprotected" clause of bar item **L2** arriving
from the software side, and no amount of driver care fixes it — the decision is made
in the OF layer before this driver is consulted.

**It is also the third independent argument for `I-R1`**, and the strongest, because
it is the one that does not depend on anyone's diligence: under a default-deny
IOMMU the forgotten device simply does not work, loudly, on its first DMA. Under the
retired all-bypass reset it works perfectly and is unprotected for the life of the
system. §9.1's checklist step 1 is the process control for the same problem, and a
process control is not a control.

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

A device without an `iommus` property gets **no IOMMU services and no BMID**, and
under [hardware-spec.md §3.10](hardware-spec.md) `I-R1` its DMA is therefore
**blocked**, not passed through. §2b is what happens on the kernel side.

> **This paragraph previously read** *"A device without an `iommus` property is
> treated as bypass-only: it can DMA with physical addresses but receives no IOMMU
> services. This is appropriate for trusted devices and during early boot."* Both
> halves are retired. There is no "bypass-only" treatment any more, and "appropriate
> for trusted devices" is a claim about a trust decision that a *missing property*
> cannot express — an omission and a deliberate exemption look identical in DT.
> A device that genuinely must run unprotected says so positively, by having its BMID's
> `BMID_BYPASS` bit set from a board file that names it, and that act is auditable
> where an absent property is not.

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

    /* I-R8 quota. q_reserved[] sums to <= num_entries; q_used[] is per-BMID.
     * A .map for BMID B fails if q_used[B] == q_cap[B], or if granting it
     * would leave fewer free entries than the reservations not yet drawn
     * on. The second test is the one that stops starvation; a first-fit
     * walk of entry_used has neither. */
    u8                       q_reserved[JCORE_IOMMU_MAX_BMID];
    u8                       q_cap[JCORE_IOMMU_MAX_BMID];
    u8                       q_used[JCORE_IOMMU_MAX_BMID];
    unsigned int             q_undrawn;
    
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

### 4.3a The vtable above will not compile, and the reasons are load-bearing

Checked against `include/linux/iommu.h` at `linux@origin/jcore`. Six of the names
used above have been removed or restricted, and the corrections are not cosmetic —
**two of the replacements are the mechanism this task needs**, which is why this
subsection belongs in a security-driven revision rather than in a later tidy-up.

| Named above | Reality at `origin/jcore` |
|---|---|
| `.detach_dev` | **Removed.** `struct iommu_domain_ops` (`include/linux/iommu.h:747-776`) has no such member. Detach is now expressed as *attaching a different domain* |
| `.map` / `.unmap` | **Removed.** Only `map_pages` / `unmap_pages` (`:754-760`) exist |
| `.attach_dev` | Signature changed: `int (*attach_dev)(struct iommu_domain *domain, struct device *dev, struct iommu_domain *old)` (`:748-749`) — the *previous* domain is now an argument, which is exactly what `I-R7`'s ordering needs |
| `.domain_alloc` | Restricted: it exists only under `#if IS_ENABLED(CONFIG_FSL_PAMU)` (`:701-703`) and is documented at `:640` as *"Do not use in new drivers"*. New drivers use `domain_alloc_paging()` (`:708`), `domain_alloc_paging_flags()` (`:705-707`) or `domain_alloc_identity()` (`:704`) |
| `bus_set_iommu()` (§5.1) | **Removed.** A whole-tree grep returns zero matches. Registration is `iommu_device_register()` alone |
| `struct iommu_fault_event` (§5.5) | **Removed.** `iommu_report_device_fault()` survives at `:1704` but now returns `int` and takes `struct iopf_fault *` (`:124`) |

**And the two additions the deny design needs already exist:**

```c
struct iommu_domain *identity_domain;   /* include/linux/iommu.h:740 */
struct iommu_domain *blocked_domain;    /* :741 */
struct iommu_domain *release_domain;    /* :742 */
```

with `#define IOMMU_DOMAIN_BLOCKED (0U)` at `:211`. **A blocked domain is a
first-class kernel concept**, and `release_domain` is the domain the core installs
when a device goes away. Together they are the framework half of `I-R7`, and the
driver's obligation is to publish both rather than to invent a teardown path:

```c
static const struct iommu_ops jcore_iommu_ops = {
    /* ... */
    .blocked_domain = &jcore_iommu_blocked_domain,
    .release_domain = &jcore_iommu_blocked_domain,
};
```

This is the same shape as the hardware finding in
[security/threat-model.md §7.7](../security/threat-model.md): the "per-device deny
state" the remediation plan asked for is **not a new state** on either side of the
interface. In hardware it is the existing miss behaviour; in the kernel it is
`IOMMU_DOMAIN_BLOCKED`. What C2d supplies is the polarity and the wiring, not a
mechanism.

**Why a stale vtable is a security finding and not a chore.** A driver written to the
sketch above cannot express teardown at all — `.detach_dev` is where its author would
have put the re-protection `I-R7` requires, and that member no longer exists. The
implementer would have discovered the API drift at the first compile and *invented* a
teardown path, most plausibly by restoring the bypass bit, which is precisely the
inversion §10.1's test asks for. The API the kernel actually offers makes the correct
answer the easy one.

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
    
    /* The IOMMU is already enabled and already denying (I-R1). Nothing
     * below turns protection on; it re-establishes a known IOTLB, arms the
     * fault IRQ, and locks SUPER_BYPASS.
     *
     * Read-modify-write, never a bare word: under I-R3 a write of 0 to
     * ENABLE is ignored, but SB_LOCK and FAULT_IRQ_EN are ordinary bits
     * and a whole-word write would clear them. */
    ctrl = readl(iommu->base + IOMMU_CTRL);
    writel(ctrl | IOMMU_CTRL_INVALIDATE_ALL, iommu->base + IOMMU_CTRL);
    while (readl(iommu->base + IOMMU_STATUS) & STATUS_INVALIDATE_BUSY)
        cpu_relax();

    /* Arm the fault IRQ only now that the handler is installed -- the
     * hardware resets it masked for exactly this reason, and blocking has
     * never depended on it (I-R2). */
    ctrl = readl(iommu->base + IOMMU_CTRL);
    writel(ctrl | IOMMU_CTRL_FAULT_IRQ_EN | IOMMU_CTRL_SB_LOCK,
           iommu->base + IOMMU_CTRL);

    /* I-E2's assertion, made by the driver rather than only by a test:
     * if SUPER_BYPASS is set here, something set it before we ran and the
     * lock we just took is a lock on an open door. */
    if (readl(iommu->base + IOMMU_CTRL) & IOMMU_CTRL_SUPER_BYPASS) {
        dev_err(&pdev->dev, "SUPER_BYPASS set at probe; refusing\n");
        return -EIO;
    }

    jcore_iommu_quota_init(iommu);   /* I-R8 */
    
    /* Register with the generic IOMMU framework. bus_set_iommu() no longer
     * exists (§4.3a); iommu_device_register() is the whole of it. */
    ret = iommu_device_sysfs_add(&iommu->iommu, &pdev->dev, NULL,
                                 "jcore-iommu");
    if (ret)
        return ret;
    
    ret = iommu_device_register(&iommu->iommu, &jcore_iommu_ops, &pdev->dev);
    if (ret) {
        iommu_device_sysfs_remove(&iommu->iommu);
        return ret;
    }
    
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
    
    /* Allocate an IOTLB entry, subject to the I-R8 quota. The quota test
     * comes first and is per-BMID; find_first_zero_bit() on its own is a
     * global free-list, and a global free-list is what lets one tenant's
     * device make another tenant's dma_map fail. */
    spin_lock_irqsave(&iommu->lock, flags);
    if (!jcore_iommu_quota_take(iommu, bmid_of(domain))) {
        spin_unlock_irqrestore(&iommu->lock, flags);
        return -ENOSPC;
    }
    entry_idx = find_first_zero_bit(iommu->entry_used, iommu->num_entries);
    if (entry_idx >= iommu->num_entries) {
        jcore_iommu_quota_give_back(iommu, bmid_of(domain));
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

**This loop is also the replacement for the `GLOBAL` bit.** A buffer genuinely shared
between *k* masters is expressed by attaching their BMIDs to one domain and letting
this loop write *k* entries — which names the sharers, where `GLOBAL` named none. The
quota accounting above must charge **each** BMID it writes an entry for, or a shared
domain becomes a way to spend another BMID's reservation. See
[hardware-spec.md §3.10](hardware-spec.md) `I-R5` and `I-R8`.

**One bug in the loop above, recorded because it is invisible under either polarity:**
it allocates **one** `entry_idx` and then writes it once per BMID, so the second
iteration overwrites the first BMID's entry rather than adding a second. A multi-BMID
domain therefore ends up with exactly one working mapping — the last BMID's — and the
others fault. With `GLOBAL` available an implementer's likely fix is to set `GLOBAL`
and write one entry, which is why this and `I-R5` have to land together. The correct
fix is one `entry_idx` per BMID.

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
    
    /* Nothing to do to the bypass bitmap: under I-R1 this BMID's bit is
     * already 0 and has been since reset, so the device is already going
     * through the IOTLB and is already blocked until .map runs. Assert it
     * rather than assume it -- a set bit here means somebody handed this
     * master an unprotected path, and attaching a domain on top of that
     * would silently produce a device that looks protected and is not. */
    reg = readl(iommu->base + BMID_BYPASS_REG(master->bmid));
    if (reg & BIT(master->bmid % 32)) {
        spin_unlock_irqrestore(&iommu->lock, flags);
        dev_err(iommu->dev, "BMID %u is in bypass at attach\n", master->bmid);
        return -EIO;
    }

    spin_unlock_irqrestore(&iommu->lock, flags);
    return 0;
}
```

> **The retired body read** `reg = readl(iommu->base + BMID_BYPASS_BASE + (master->bmid / 8));`
> **and cleared** `BIT(master->bmid % 32)` **in it.** The two do not agree: the
> register index divides the BMID by 8 while the bit index takes it modulo 32, so for
> every BMID above 7 this reads the wrong register *and* clears a bit belonging to a
> different master. The correct arithmetic is one register per 32 BMIDs, four bytes
> apart —
> `#define BMID_BYPASS_REG(b) (BMID_BYPASS_BASE + 4 * ((b) / 32))`, bit `(b) % 32`,
> which [hardware-spec.md §3.9](hardware-spec.md) now states because this happened.
>
> **The bug's failure mode is the argument for `I-R1` in miniature.** Under the
> retired all-bypass reset it clears a *different* device's bypass bit and leaves the
> attaching device in bypass: the attaching device works perfectly and unprotected,
> the innocent device starts faulting, and the symptom appears somewhere other than
> the cause. Under default-deny the same bug can only set a bit nobody asked for or do
> nothing at all, and the device that fails is the one being attached. A polarity that
> converts a silent-open bug into a loud-closed one is worth more than the bug it
> would have caught.

### 5.4a Detach, release and teardown — `I-R7`

There was no `.detach_dev` in this document and there is none in the kernel
(§4.3a). The teardown obligation is discharged by publishing a blocked domain and
by the ordering below, which is normative:

```c
/* The domain every detached, released or reset device lands in. */
static const struct iommu_domain_ops jcore_iommu_blocked_ops = {
    .attach_dev = jcore_iommu_attach_blocked,
};
static struct iommu_domain jcore_iommu_blocked_domain = {
    .type = IOMMU_DOMAIN_BLOCKED,
    .ops  = &jcore_iommu_blocked_ops,
};

static int jcore_iommu_attach_blocked(struct iommu_domain *d,
                                      struct device *dev,
                                      struct iommu_domain *old)
{
    struct jcore_iommu_master *master = dev_iommu_priv_get(dev);
    struct jcore_iommu *iommu = master->iommu;
    unsigned long flags;

    spin_lock_irqsave(&iommu->lock, flags);

    /* 1. Revoke first. INVALIDATE_BMID clears every entry carrying this
     *    BMID in one command and takes num_entries cycles. */
    writel((IOTLB_CMD_INVALIDATE_BMID << 28) | master->bmid,
           iommu->base + IOTLB_CMD);
    while (readl(iommu->base + IOMMU_STATUS) & STATUS_INVALIDATE_BUSY)
        cpu_relax();

    /* 2. Then confirm the bypass bit is clear. Order matters: with the
     *    bit clear and entries still live the device still reaches its
     *    old buffers; with the entries gone it reaches nothing. */
    WARN_ON(readl(iommu->base + BMID_BYPASS_REG(master->bmid)) &
            BIT(master->bmid % 32));

    /* 3. Only now give the slots and the quota back. */
    jcore_iommu_release_entries(iommu, master->bmid);

    master->domain = NULL;
    spin_unlock_irqrestore(&iommu->lock, flags);
    return 0;
}
```

**Steps 1 and 2 must both complete before the call returns**, because the call
returning is what the core treats as the device being detached. `release_domain` is
set to the same object so that a device that disappears — hot-unplug, driver unbind,
a `VFIO` handover — takes the identical path; the framework installs
`release_domain` on release precisely so that a driver does not have to remember to.

**What this closes.** Between "the device is released" and "the device is
re-protected" the device is a fully-privileged DMA master whose driver has stopped
watching it. That is the Thunderclap window, opened at the *end* of a device's life
rather than at the start, and it is the more dangerous end because handing a device
to a different tenant is exactly when it happens.

**What it does not close, named rather than implied.** A transaction already in
flight when step 1 runs is governed by [hardware-spec.md §10](hardware-spec.md)
verification point 9, which leaves the mid-flight case to the implementer *provided
it is documented*. For a teardown that is not good enough, and the implementation
choice is therefore constrained here: the mid-flight transaction must **not** complete
with the old translation. Draining the master's port first
([bus/fabric-spec.md §9.3](../bus/fabric-spec.md) already requires the fabric to
quiesce a master's port before resetting it) is the clean way, and an integration that
cannot drain must abort in-flight transactions instead.

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

0. **Power-on: every BMID is already blocked.** No software has run and no DMA
   succeeds. [hardware-spec.md §3.10](hardware-spec.md) `I-R1`.
1. IOMMU device tree node is parsed; `jcore_iommu_probe` runs.
2. The driver invalidates the IOTLB, arms the fault IRQ now that its handler exists,
   locks `SUPER_BYPASS`, and initialises the quota. **It does not enable anything** —
   protection was already on.
3. As DMA-capable devices probe, their device tree `iommus` property triggers `of_xlate` callback, which creates a `jcore_iommu_master` and binds it to the device.
4. The generic framework allocates a default domain for each device (or per-group).
5. On first DMA operation, the framework calls `.attach_dev` — which now *checks* the
   bypass bit rather than clearing it — then `.map` (installing IOTLB entries).
6. Steady-state DMA flows through the IOMMU.

> **Step 2 previously read** *"invalidate IOTLB, enable, enable fault IRQ. All BMID
> bypasses still set"*, and the section previously ended *"Devices that need DMA
> before the IOMMU is probed … work because the IOMMU starts with all bypasses
> enabled. Only after attach are bypasses cleared, requiring proper mapping."*
> Both are retired. There is no window in which a device works unprotected, and a
> device that needs DMA before its driver has mapped anything now fails.

**A device that genuinely must DMA before the kernel is up** — a boot-time DMA engine
loading a kernel image, which no board this project builds currently has — is served
by the bootrom programming the IOMMU before that DMA, alongside the SDRAM controller
and AIC2 initialisation it already performs
([bus/fabric-spec.md §9.2](../bus/fabric-spec.md)), or by that engine using PIO. The
cost is real; [hardware-spec.md §8](hardware-spec.md) prices it and it is the
requirement, not an argument against it.

**kexec is the case default-deny makes *harder*, and it is worth being explicit.**
Reset polarity does not apply across a kexec: the new kernel inherits a **running**
IOMMU with the old kernel's IOTLB entries live and its `SB_LOCK` still set. The
inherited entries are the hazard — a device still DMAing into memory the new kernel
has repurposed — so `jcore_iommu_probe`'s `INVALIDATE_ALL` (step 2) is not a
formality on that path, it is the re-protection. It runs before any device attaches,
which is the ordering that makes it sufficient. The inherited `SB_LOCK` is benign: it
is locked *off*, and the new kernel would set it anyway.

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
    
    /* IOTLB is empty after S2RAM and the block is back in its reset
     * state, i.e. denying (I-R1). Restore by walking each domain's
     * mapping list and reprogramming.
     *
     * Read-modify-write, as in probe: a bare word here would clear
     * FAULT_IRQ_EN and SB_LOCK. */
    writel(readl(iommu->base + IOMMU_CTRL) | IOMMU_CTRL_INVALIDATE_ALL,
           iommu->base + IOMMU_CTRL);
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
    
    /* Re-arm the fault IRQ and re-lock SUPER_BYPASS last. pm_state.ctrl is
     * deliberately not written back wholesale -- see below. */
    writel(readl(iommu->base + IOMMU_CTRL) |
           (pm_state.ctrl & IOMMU_CTRL_FAULT_IRQ_EN) |
           IOMMU_CTRL_SB_LOCK,
           iommu->base + IOMMU_CTRL);
}

static struct syscore_ops jcore_iommu_syscore_ops = {
    .suspend = jcore_iommu_pm_suspend,
    .resume  = jcore_iommu_pm_resume,
};
```

The reconstruction approach (vs. saving every IOTLB entry to memory) is more code but avoids issues if the IOTLB layout changes between save and restore. In practice the IOMMU is small enough that both approaches work.

**The resume ordering is safe and it is worth saying why, because it looks wrong.**
The bypass mask is restored before the IOTLB is reprogrammed, so there is a window in
which devices are non-bypassed with an empty IOTLB. Under `I-R1` that window is
**fail-closed**: every device in it is blocked, and the worst outcome is a fault
latched against a device that resumed early. Restoring the IOTLB first and the bypass
mask second would be the fail-open ordering, and it is the one an implementer
optimising for "no faults in the resume log" would reach for.

**What must not be restored: `SUPER_BYPASS` and `SB_LOCK`.** Saving `IOMMU_CTRL` and
writing it back wholesale — which the retired code above did — treats a lock as
saveable state, and restores a bypass that may have been set for debugging before the
suspend. A lock cleared by reset is *re-taken*, never restored.

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
- Attach **asserts** `BMID_BYPASS[BMID] == 0` and fails if it is set; detach installs
  the blocked domain. *(This line previously read "Attach and detach toggle the
  BMID_BYPASS bit correctly." A toggle back to 1 on detach releases the device into
  unrestricted DMA — it is the inversion `I-R7` exists to forbid, written down as the
  thing to verify.)*
- Quota: BMID *A* at its cap does not prevent BMID *B* from mapping (`I-E5`).

### 10.2 Functional tests

- Allocate a 16 KB DMA buffer; verify device can read what CPU wrote and vice versa.
- Allocate a 16 MB DMA buffer (forcing superpage mapping); verify same.
- Run `dma_map_sg` on a scatter list spanning 32 fragments; verify all visible to device.
- Repeatedly `dma_alloc_coherent` / `dma_free_coherent` over 100k cycles; verify no IOTLB leaks.

### 10.3 Fault and deny tests

- Manually corrupt a device's DMA descriptor to point at unmapped IOVA; verify fault is logged with correct BMID and IOVA.
- Stress with high IOTLB pressure (allocate many small buffers to exhaust IOTLB); verify graceful `-ENOSPC` rather than silent corruption.
- **A device with no `iommus` property in DT does not DMA.** This is §2b's fail-open
  OF path meeting `I-R1`; the test asserts that the hardware catches what the kernel
  does not.
- **The negative tests `I-E0`–`I-E6`** in
  [hardware-spec.md §10.1](hardware-spec.md) are the ones bar item **L2** requires,
  and three of them (`I-E1`, `I-E3`, `I-E5`) are driven from this driver.

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
- What's the right behavior when IOTLB fills? Currently we return `-ENOSPC` to the
  framework. **This is no longer an open question in the direction it was asked.** An
  LRU eviction policy over a *shared* pool would make one BMID's pressure evict
  another BMID's live mapping, turning a starvation problem into a fault-and-disable
  problem — the shared pool has to be quota'd (`I-R8`) before any eviction policy over
  it is safe. Eviction *within* a BMID's own quota is a legitimate future option and
  needs profiling; eviction across BMIDs is now excluded.
- **Where do the quota numbers come from?** `q_reserved` and `q_cap` per BMID are a
  policy this document does not set, because the right values depend on the board's
  device mix and §5.3 of [design-spec.md](design-spec.md) gives per-workload entry
  counts, not a partition. The defensible default is an equal reservation across
  claimed BMIDs with a cap of the whole pool, which prevents starvation without
  capping a single-device board; a board with a known mix should override it in DT.
  **unknown at this stage — needs measurement**: the entry counts a real J-Core
  workload mix holds concurrently. What would produce them is an instrumented run on
  the ULX3S once a DMA master exists.
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
