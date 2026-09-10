# 0010 — DMA coherence is software-maintained, and the IOMMU does not own it

**Status:** Accepted 2026-09-09. Wave-3 task **C2d**, from
[j4-remediation-plan.md §C2](../j4-remediation-plan.md), whose IOMMU worklist ends
*"and own coherent-DMA vs the write-back L2 (the L2 exposes no fabric snoop port
today)"*. This record is that ownership.

**Relationship to [0007](0007-l1d-write-policy-under-msi.md).** 0007 decided the
L1-D write policy per tier and stated the DMA consequence; it then named what it was
*not* doing — *"it does not specify the `arch/sh` DMA-ops implementation, and
`mmu/linux-spec.md` does not currently contain one. That is work this decision
creates and does not perform."* This record performs it, and finds the situation
worse than 0007 assumed on the software side and better on the hardware side.

---

## Context

### What the worklist said, and what is actually there

Three of the four nouns in the worklist entry do not survive a read of the tree at
`origin/master`.

**"The L2" does not exist.** There is no L2 cache RTL in `jcore-cpu` or `jcore-soc`.
No file in either repository has `l2` in its path; every `l2` token in VHDL is a
false positive — a `textio` `line` variable in three D-cache testbenches, an FPGA
ball name in three `pad_ring.vhd` files, and comments about the *TLB*'s second tier
in `sim/tlb_tb.vhd` and `synth/cpu_synth_j4_config.vhd`. The complete non-testbench
cache inventory is `dcache`, `icache` and their adapters, muxes, CCLs, MCLs and
RAMs. **L1 only.** [cache/l2-spec.md](../cache/l2-spec.md) is a specification with no
implementation, which C2b's finding shape covers: a structure the plan names that no
repository contains.

**"Write-back" is the wrong tier.** The L2 is write-back toward SDRAM in *both* the
v1 and v2 specs and nothing ever said otherwise — 0007 established that the disputed
policy was one level up, at the **L1-D**, and that it is write-through at `[T0]` and
write-back under MSI at `[T1/T2]`. The RTL agrees emphatically:
`jcore-cpu:cache/dcache_cacheable_mux.vhd:11-18` states *"there is no dirty bit or
writeback path in this cache at all"*, `core/cpu.vhd:1450-1455` repeats it, and
`cache/cache_pkg.vhd:53-59`'s command encoding has no writeback or evict command. So
the cache whose write policy creates the DMA hazard is the L1-D, at a tier nobody has
built yet, and the L2's own policy was never in dispute.

**A snoop port does exist today — on the L1-D, and it is tied off.** This is the part
the worklist's phrasing hides, and it is the useful finding. `cache_pkg.vhd:467-470`
declares

```vhdl
type dcache_snoop_io_t is record
  al : std_logic_vector(...);
  en : std_logic;
end record;
```

— an address and an enable, nothing else. It is a real external **port**, not an
internal signal: `sa`/`sy` on `cache/dcache.vhd:24-26` and `cache/dcache_ccl.vhm:21-23`,
`snpc_o`/`snpc_i` on `cache/dcache_adapter.vhd:18-19`. Reading the logic rather than
the name: an incoming `sa` drives a tag read (`dcache_ccl.vhm:104`), the comparison
forms `cachehit_snoop` (`:293-300`), and a hit **clears the valid bit** —
`nx.ffv(vtoi(this.sa_al(...))) := '0'` at `:534-536`. It is invalidate-only, with no
MSI state, no directory and no probe response, which is exactly the right primitive
for a **write-through** L1-D and exactly the wrong one for a write-back L1-D.

Where it goes: in the two-CPU configuration the two L1-Ds are cross-wired to each
other (`jcore-soc:targets/ddr_ram_mux/two_cpu_idcache.vhd:64-65, 81-82`); in the
one-CPU configuration and in the production single-cache wrapper it is tied to
nothing (`one_cpu_idcache.vhd:40-41` and `cache/dcache_cacheable_mux.vhd:78-79`, both
`snpc_i => NULL_SNOOP_IO`). **No `snpc`/`sa`/`sy` signal is exposed on
`ddr_ram_mux`'s entity or on any board's `soc` entity, and `dma_dbus_o` — the DDR
mux's DMA leg — connects to none of it.**

So the accurate statement of the gap is: *the port a DMA write would need in order to
invalidate a stale CPU line exists, is address-and-enable, is one wire away from the
DMA leg of the DDR mux, and is currently tied to a constant.*

### The specification side: a snoop bus with no seat for a device

[bus/fabric-spec.md §7.1](../bus/fabric-spec.md) is unambiguous about who is on the
snoop bus: *"Source (driver): the L2's directory / snoop driver … The L2 is the
single originator of snoop traffic; cores never originate snoops"*, destination
*"every CPU's L1-D snoop port"*. The L2 directory's `dir_vec` has one bit per **core**
([cache/l2-spec.md §7.3](../cache/l2-spec.md)), not per bus master. A DMA engine is
neither a source nor a destination and has no directory bit. The channel is `[T2]`
only; **T0 and T1 have no snoop transport at all**, and a J32 with an IOMMU and no
coherence is an explicitly valid T1 deployment
([bus/fabric-spec.md §0](../bus/fabric-spec.md)).

The L2 spec's *"acts as the directory / snoop filter for L1-D coherence"* and the
absence of a DMA-reachable port are therefore not in tension: a directory that tracks
which L1-Ds hold a line is not a port through which a fabric master can snoop or
invalidate. Confusing the two is the error this record exists to prevent, because it
is the difference between "the hardware is nearly there" and "the hardware is one
wire away, on a different block".

### The kernel side, which is worse than 0007 assumed

0007 wrote the T1/T2 software contract as *"the DMA API is non-coherent streaming:
`dma_map_*` / `dma_sync_*` do real work"*. On `linux@origin/jcore` today, for the J4,
**they do no work at all.**

- `arch/sh/mm/Makefile:8-14` selects a cache-operations file on `CPU_J2`,
  `CPU_SUBTYPE_SH7619`, `CPU_SH2A`, `CPU_SH3` or `CPU_SH4`. The first arm is the one
  that matters here, and it is the value this record is code-bound to: the
  `cacheops-` selector keys on `CPU_J2`.
- `arch/sh/configs/jcore_defconfig:1` sets `CONFIG_CPU_SUBTYPE_JCORE=y`, which selects
  `CPU_JCORE`, which selects **`CPU_SH2`** — not `CPU_J2`, and `j2_defconfig` is a
  separate file. **`cacheops-y` is empty for the J4 build.**
- `arch/sh/mm/cache.c:311-313` therefore leaves `__flush_wback_region`,
  `__flush_purge_region` and `__flush_invalidate_region` at `noop__flush_region`, and
  `:18-26` leaves every `local_flush_*` at `cache_noop`.
- `arch/sh/kernel/dma-coherent.c` is the whole of arch/sh's DMA maintenance: its
  `arch_dma_prep_coherent()` calls `__flush_purge_region` and its
  `arch_sync_dma_for_device()` calls one of the three. All three are the no-op.
- `arch/sh/Kconfig:138-142` selects `ARCH_HAS_SYNC_DMA_FOR_DEVICE` and **not**
  `ARCH_HAS_SYNC_DMA_FOR_CPU`. There is no post-transfer, CPU-side hook to implement,
  so the direction "device wrote, CPU is about to read" has no callback at all,
  independently of the no-op above.

One further hazard, recorded here **with its outcome, corrected 2026-09-09 by Wave-3
C2e**: the J4 include path adds `cpu-jcore` (which contains only `mmu_context.h`)
ahead of `cpu-sh2`, so `<cpu/cache.h>` resolves to `cpu-sh2/cpu/cache.h`.
`cpu_cache_init()` reads `SH_CCR` to decide whether to dispatch at all, and the
destination is either the `skip` label or `sh2_cache_init()`, which is declared
`__weak` in `arch/sh/include/asm/cacheflush.h:110` and defined only in
`cache-sh2.c`, which this build does not compile. Neither branch is a
cache-maintenance implementation, which is this paragraph's point and is unchanged.

*What is corrected is the premise and the hedge.* This paragraph read "the J4
inherits `SH_CCR = 0xffffffec` — an SH-2 register address" and then declined to say
which branch is taken, "because the outcome depends on hardware behaviour not
established here". **The J4 inherits no `SH_CCR` at all**: that define sits inside
`#if defined(CONFIG_CPU_SUBTYPE_SH7619)` in `arch/sh/include/cpu-sh2/cpu/cache.h`,
and `arch/sh/configs/jcore_defconfig` does not set that symbol. So there is no MMIO
read and no hardware behaviour to depend on — the `#ifdef SH_CCR` guard simply
leaves `cache_disabled` at zero, `skip` is **never** taken, and `sh2_cache_init()`
is always the destination. The hedge was hiding a `#if` behind a hardware question.

**Why none of this has bitten.** There is no DMA master. `jcore-soc:components/dma/`
holds a `README` reading *"Stub implementation of CoreSemi DMA engine"*, a
`dma_pkg.vhd` of types, and no entity; `dma_dbus_o` is tied to a constant zero on all
four boards (`targets/boards/{ulx3s,mimas_v2,turtle_1v0,microboard}/soc.vhd`); and
every peripheral that exists, the Ethernet MAC included, is a bus **slave**. The only
bus masters in any J-Core configuration today are the CPU's I- and D-cache legs.

## Decision

**1. DMA on J-Core is non-coherent, at every tier, and the obligation is software's.**
No block in this project promises that a device transaction observes a CPU cache or
that a CPU observes a device write without an explicit maintenance operation. Drivers
use the DMA API and the DMA API must do real work.

**2. The IOMMU is not the coherence point and never was.** Its per-entry `CACHEABLE`
and `WBA` bits are **attributes forwarded to the fabric**, not guarantees.
[iommu/hardware-spec.md §3.10](../iommu/hardware-spec.md) `I-R9` and §7 are normative;
the retired claims are quoted there. The IOMMU sits between the fabric and the DRAM
controller and has no path to any cache, so a coherency guarantee sited in it is a
guarantee sited where the enforcing logic cannot reach the property — the shape
Wave-3 task C1c named, arriving here as a delegation to a component (*"the bus fabric
is responsible for routing snoop traffic"*) that offers no such service to a device.

**3. The hardware option is named, with its wire.** If and when a J-Core integration
wants device-write→CPU-read coherence in hardware rather than in software, the
mechanism is the **existing L1-D snoop port**, not a new L2 port and not the T2 snoop
bus: drive `dcache`'s `sa` (`{al, en}`) from the write address of every non-CPU master
transaction that targets a cacheable region, replacing the `NULL_SNOOP_IO` tie-offs at
`jcore-soc:targets/ddr_ram_mux/one_cpu_idcache.vhd:40-41` and
`jcore-cpu:cache/dcache_cacheable_mux.vhd:78-79`. This is correct for a **write-through**
L1-D and is therefore a `[T0]`/`[T1]` mechanism only: it invalidates, and a write-back
L1-D holding a dirty line needs a writeback response the port has no channel for.
**At `[T1/T2]` the answer is the L2 directory or nothing**, and that is a decision for
whoever writes the L2 RTL, not this record.

**4. The kernel work is named and is not done here.** `arch/sh` needs real
cache-maintenance primitives for `CPU_SUBTYPE_JCORE`: a `cacheops-` arm that compiles
for the J4, definitions of `__flush_wback_region` / `__flush_purge_region` /
`__flush_invalidate_region` against the J-Core CCR that `cache-j2.c` already reaches
through `j2_ccr_base`, and `ARCH_HAS_SYNC_DMA_FOR_CPU` with a matching
`arch_sync_dma_for_cpu()`. Until then the DMA API's cache maintenance on J4 is a
no-op, and this record's decision 1 is a contract the kernel does not yet keep.

**5. What is safe today, and exactly why.** At `[T0]` with a write-through L1-D, the
*device-read* direction is safe by construction: the most recent value of any line is
always at or below the L2's position, so a device read cannot observe stale data. The
*device-write* direction is **not** safe, and the no-op above is why — it is currently
unreachable only because no DMA master exists, and it becomes a silent data-corruption
bug, and under a tenant-controlled device a stale-read primitive, on the day one does.
`I-E6` in [iommu/hardware-spec.md §10.1](../iommu/hardware-spec.md) is the test.

## Enforcement

`cache.dma.coherence` in [fact-ownership.md](../fact-ownership.md) names this record
as the owner of the DMA coherence contract, so a document restating it needs a link.

**There is no code binding, and unlike [0007](0007-l1d-write-policy-under-msi.md) the
reason is not only absence.** The T1/T2 half has no code at all, as 0007 says. The
half that *does* have code — the L1-D snoop port and its tie-offs — is a fact about a
**connection**, and the binding mechanism compares two captured *values*
([fact-ownership.md](../fact-ownership.md) §Code bindings). A pattern asserting that
`snpc_i => NULL_SNOOP_IO` still appears would pass while someone added a second,
unwired instantiation, and would fail on a rename that changed nothing. The check that
would close this is the one 0007 also asked for: a doc-vs-code binding written *with*
the RTL that connects the port, not before it.

**One binding is available and is taken**, because it is a value and it is the value
that makes decision 4 true: the registry binds this record's claim that the J4 build
compiles no cache-operations file to `arch/sh/mm/Makefile`'s `cacheops-` selector for
`CPU_J2`. If someone adds a `cacheops-$(CONFIG_CPU_JCORE)` arm — which is exactly the
fix decision 4 asks for — the binding goes red and this record has to be revisited,
which is the intended behaviour, not a regression.

## Rejected alternatives

**Make the IOMMU the coherence point, as the previous text claimed it was.** Rejected
on reachability, not on cost. `iommu/hardware-spec.md` §7.1 previously promised that a
`CACHEABLE = 1` transaction *"invalidate[s] matching cache lines on CPUs"*. The IOMMU's
outputs are a physical address and attribute bits; it has no port to any cache and the
fabric it delegated to specifies the L2 as the *single* originator of snoops. This is
not a mechanism that would be expensive to add to the IOMMU — it is a mechanism that
would have to be added somewhere else and then routed, at which point the IOMMU is
forwarding an attribute, which is what decision 2 says it does.

**Route device traffic through the L2 array so the L2 becomes the coherence point.**
Rejected as out of scope rather than as wrong; it is genuinely the design most likely
to be right at `[T1/T2]`. 0007 raised the same question and left it open — *"whether
device traffic is routed through the L2 … belongs to whoever writes the L2 RTL"* — and
nothing found by this task changes that, because there is still no L2. What this record
adds is that the question is **not** answerable by pointing at the directory: the
directory tracks L1-D copies for the L2's own protocol and would need a device-side
port either way.

**Make every DMA buffer uncached and declare the problem solved.** Rejected as
incomplete rather than wrong. It is already what `dma_alloc_coherent` does on SH —
`kernel/dma/direct.c` remaps through `dma_pgprot()`, which reaches
`pgprot_dmacoherent` → `pgprot_noncached` → `arch/sh/include/asm/pgtable_32.h:397`'s
`pgprot_writecombine` — and 0007 lists it as an option (`PTEL.C = 0`). It does not
cover **streaming** mappings, which are the hot path the IOMMU design spec is written
around (Ethernet rings, `dma_map_sg`), and it does not cover the cached linear alias of
a coherent allocation, which is why `arch_dma_prep_coherent()` exists and is a no-op
here.

**Leave the contract implicit, since no DMA master exists.** Rejected for the reason
Wave-3 task C1a established on a different subject: a mitigation conditioned on state
existing misses the case where the state is fresh. Here the analogue is that a
correctness contract nobody wrote down is one the first DMA master's author will
discover by debugging silent corruption. Naming the obligation is cheap now and is not
cheap then.

## What would reopen this

- **A DMA master is instantiated** in any `jcore-soc` board — `dma_dbus_o` stops being
  tied to zero. `I-E6` becomes runnable, and decision 4's kernel work becomes blocking
  rather than latent.
- **The L2 RTL is written**, which forces the open question decision 3 defers: whether
  a device transaction traverses the L2 array, and whether the directory gains a
  device-side port. Either answer supersedes decision 3's `[T1/T2]` half.
- **`arch/sh` gains a `cacheops-` arm for `CPU_JCORE`**, which is decision 4 being done
  and which turns this record's Enforcement binding red on purpose.
- **The L1-D becomes write-back** at any tier a board actually builds
  ([0007](0007-l1d-write-policy-under-msi.md) decision 2), at which point the
  invalidate-only snoop port of decision 3 is no longer sufficient in either direction.
