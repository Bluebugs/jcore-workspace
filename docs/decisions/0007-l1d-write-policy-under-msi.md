# 0007 — The L1-D is write-through at T0 and write-back under MSI at T1/T2

**Status:** Accepted 2026-09-07. Wave-2 task B1, from
[j4-remediation-plan.md §B1](../j4-remediation-plan.md), which lists this item
as *"resolve before any L2 work"* because it changes correctness, coherence and
the DMA story.

---

## Context, and what the contradiction actually was

The worklist entry reads "L2 write-through vs write-back / MSI-M
(`l2-spec` §2 vs §6/§7/§17)". Read against the file, **the L2's own write
policy is not in dispute**: §1, §2 and §17.2 all say the L2 is write-back
toward SDRAM, and nothing says otherwise. The disagreement is one level up, in
the **L1-D → L2** direction, and it is a tier-scoping failure:

| Says the L1-D writes through | Says the L1-D holds dirty lines |
|---|---|
| [cache/l2-spec.md §2](../cache/l2-spec.md), tagged `` `[T0/T1/T2]` ``: "serves all per-core L1-I (read-only) and L1-D (**read/write-through**) clients" | §7.2: `M` = "**dirty** exclusive copy in one L1-D", 2 state bits per L1-D line |
| §10.2, tagged `` `[T0/T1/T2]` ``: "Writes from L1-D are 32-bit-word **write-throughs** (byte-enabled)" | §7.4: a `Wb` message, direction L1-D → L2, "Writeback in response to Downgrade or Recall, or voluntary" |
| §17.1's *heading*: "Write-through from L1-D" | §7.5: every `M`-state row makes the holder write back before another core may read |
| | §6.3: `GetM-Locked` "Marks the line Modified in L1-D", and the CAS compare is then performed **locally, in the L1-D, holding M** |
| | §17.1's *body*: "L1-D writes flow as a coherence message at T1 (`GetM` or `Upgrade` then implicit write into the M-line, finalized with a `Wb` on eviction). T0 uses the v1 write-through-on-each-store path." |

The right-hand column is a coherent design and the left-hand column is a
correct description of **T0**, carrying a `` `[T0/T1/T2]` `` tag it has not
earned. §17.1 has both halves in one section, with the tier scoping in the body
and a heading that contradicts it.

## What the shipped RTL does, which fixes T0

Read at `jcore-cpu@master`:

- `cache/cache_pkg.vhd`: the L1 tag is
  `cache_tag_width = CACHE_REGION_WIDTH - CACHE_LINE_WIDTH_BITS - CACHE_INDEX_BITS`
  and the per-line state is `cache_valid_bits` — a **valid** array. **There is
  no dirty bit anywhere in the L1-D**, so the L1-D cannot hold a modified line;
  the question does not arise for the hardware that exists.
- `cache/dcache_ccl.vhm`: every store emits a command to the memory-clock layer
  — `CACHE_DCMD_WRITESGL_FA`, `CACHE_DCMD_WRITESGL_SL`, `CACHE_DCMD_WRITEMISS`.
  Stores go through, always.
- `linux@jcore` `arch/sh/mm/cache-j2.c` agrees from the software side: the D-side
  maintenance operation is `DCACHE_FLUSH` through the CCR, a whole-cache
  **invalidate**. A write-back L1-D could not be maintained with an invalidate.

So T0 is write-through, and that is a lookup, not a decision.

## Decision

**1. `T0`: the L1-D is write-through, no-allocate on store.** This is the
shipped J2/J4 behaviour and this record changes nothing about it.

**2. `T1`/`T2`: the L1-D is write-back.** A line held `M` is dirty and
exclusive; stores land in it without an L2 transaction; the line reaches the L2
via a `Wb` on `Downgrade`, `Recall` or eviction. This is what §6, §7, §13.2,
§17.2 and §19 already specify and what MSI's `M` state *means*.

**3. Every unqualified statement of the T0 behaviour is re-tagged, not
deleted.** §2's client bullet, §10.2's access-width paragraph and §17.1's
heading say which tier they describe. §10.4 already had this right — it lists
"write-through merge" among the v1 port consumers and adds "inbound writeback
write" at T1, i.e. both paths coexist in one RTL, which is the T0-and-T1
parameterisation §0 asks for.

**4. The DMA story is stated rather than assumed.** See below; it is the part of
this item that a re-tag alone would have left broken.

## The DMA consequence, which is the reason this item was gated

[bus/fabric-spec.md §7](../bus/fabric-spec.md) is explicit about who is on the
snoop bus: *"Source (driver): the L2's directory / snoop driver … Destination:
every CPU's L1-D snoop port."* **Non-CPU masters are not snoop participants**,
and the L2 directory's `dir_vec` has one bit per *core*
([cache/l2-spec.md §7.3](../cache/l2-spec.md)), not per bus master. A DMA
engine, the EMAC, or anything behind the IOMMU is invisible to the protocol.

Under **T0** that is nearly harmless in one direction: with a write-through
L1-D the most recent value of any line is always at the L2 or below, so a device
*read* cannot observe stale data. Only the other direction needs software — a
device *write* must be followed by an L1-D invalidate.

Under **T1/T2 it becomes two-sided.** A dirty line can sit in an L1-D that no
device transaction will ever snoop, so a device read can observe stale memory.
**This is a real change in the software contract, and it is the correctness item
the worklist meant.** Concretely, for `arch/sh` on a T1/T2 part:

- The DMA API is **non-coherent streaming**: `dma_map_*` / `dma_sync_*` do real
  work. `dma_alloc_coherent` cannot be a no-op returning cached memory.
- Before a device reads a buffer the CPU wrote: write back — `ocbwb`/`ocbp`
  ([cache/l2-spec.md §17.5](../cache/l2-spec.md)).
- After a device writes a buffer the CPU will read: invalidate — `ocbi`, with
  that section's own warning that `ocbi` discards dirty data silently, which is
  exactly the sharp edge a write-back L1-D introduces.
- Alternatively map DMA buffers uncached (`PTEL.C = 0`), which the TLB already
  routes faithfully.

**What this record does not do**, named rather than left to be discovered: it
does not specify the `arch/sh` DMA-ops implementation, and
[mmu/linux-spec.md](../mmu/linux-spec.md) does not currently contain one. That
is work this decision creates and does not perform. It also does not settle
whether device traffic is routed *through* the L2 — [cache/l2-spec.md §1](../cache/l2-spec.md)
places the L2 between the L1s and the memory-clock layer, and
[bus/fabric-spec.md §3](../bus/fabric-spec.md)'s address map points SDRAM at the
`dcache_mcl` interface, which does not by itself say whether a fabric master's
access passes through the L2 array or around it. If it passes *around*, a device
read is stale against the **L2** as well and the software obligation is
unchanged but larger. That question is genuinely open and belongs to whoever
writes the L2 RTL.

## Rejected alternative — keep the L1-D write-through at T1/T2, with an S/I-only protocol

This is not a straw man. Write-through plus write-invalidate is a real,
pre-2006 design: it is what a shared-bus write-through cache does, and it would
let §2's and §10.2's unqualified sentences stand as written.

**What it would buy.**
1. One state bit per L1-D line instead of two. §7.2 prices two bits at 2048
   bits ≈ 0.1 EBR for a 32 KB/4-way L1-D, so the saving is ~0.05 EBR —
   structural arithmetic, and negligible.
2. The DMA problem above stays one-sided, since memory is never stale with
   respect to an L1-D.
3. No `Wb` message, no inbound-writeback port on the L2 data array (§10.4), no
   `Downgrade` handling.

**Why it is rejected.**

1. **It breaks CAS.L as specified.** [§6.3](../cache/l2-spec.md) has the L1-D
   acquire the line in `M` and then *perform the compare and the swap locally*,
   with `Unlock` carrying the new data back. A write-through L1-D has no `M` to
   hold, so the whole compare-and-swap would have to move into the L2 — a
   different atomic unit, a different message set, and a rewrite of §6 rather
   than an edit. The line-lock design is the part of this spec with the most
   prior art behind it (§3: SPARC v9 `CASA` over UltraSPARC II, MIPS R4000
   LL/SC) and the least appetite for redesign.
2. **It puts every store on the L2.** §10.4 already describes the L2 data-array
   port budget as time-multiplexed per bank, with the snoop read sharing the
   writeback-read slot because "snoop arbitration is sufficiently rare".
   Write-through at T1/T2 makes L1-D stores the *common* L2 transaction rather
   than the rare one, against an array whose ports are EBRs. §11.2's latency
   budget and §5.3's arbiter priorities are both written on the opposite
   assumption.
3. **The saving it buys is a rounding error and the cost is bandwidth.** One bit
   per line against an L2 write per store. On a board where §20.1 already books
   ~141 EBRs of 208 for the cache hierarchy, EBR *ports* are scarcer than EBR
   *bits*.
4. **It would make the T0/T1 parameterisation harder, not easier.** §0's whole
   arrangement is that one RTL targets both tiers, with T0 leaving the directory
   depopulated. §10.4's "both paths coexist" is what makes that work. An
   S/I-only T1 would need the write-through path to be the *only* path at T1
   while T0's identical path is also the only path — which sounds like
   simplification until you notice the L2 side needs a merge port at T1 that
   T0's does not exercise at anything like the same rate.

**What would reopen it.** Measured L2 write-port saturation under a write-back
L1-D that is worse than the same workload's coherence traffic under S/I — which
needs L2 RTL, since there is none in `jcore-cpu@master` today. Note that the
argument would still have to answer objection 1 separately: bandwidth does not
buy back CAS.L.

## Enforcement

`cache.l1d.write.t0` in [fact-ownership.md](../fact-ownership.md) names
[cache/l2-spec.md §17.1](../cache/l2-spec.md) as the owner of the L1-D write
policy, so a document restating it needs a link.

**There is no code binding, and the reason is not an oversight.** The T0 half is
bindable in principle — the absence of a dirty bit in `cache/cache_pkg.vhd` is
the property — but "this constant does not exist" is not a capture, and the
binding mechanism compares two captured values
([fact-ownership.md](../fact-ownership.md) §Code bindings). A pattern asserting
that `cache_tag_width` has no `+ 1` in it would pass for any of a dozen
unrelated reasons and fail on a harmless reformat. The T1/T2 half has no code at
all: there is no L2, no directory and no snoop port in `jcore-cpu@master`. This
item is therefore closed by ownership and by tier-scoping, and the check that
would close it properly is a doc-vs-code binding written *with* the L2 RTL, not
before it.
