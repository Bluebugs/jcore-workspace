# J-Core bi-endian specification — byte-invariant, on both paths, per context

**Status:** Canonical for the byte-order **mechanism**. Wave-2 task
`wave2/bi-endian`, on project direction. **Supersedes** Decision B2-1 of
[sh4-guest-model.md §3.1](sh4-guest-model.md) and the instruction-fetch half of
[decisions/0006](decisions/0006-endianness-is-big-endian.md).

**What this document owns.** The byte-order *mechanism*: which scheme is used,
which accesses the mode changes, where the swap sits in the pipeline, what the
control bits mean, and — as importantly — which hardware is deliberately left
alone. It owns **no register address, no bit position, and no vector**; those
have owners in [fact-ownership.md](fact-ownership.md) and this document links
them. It does **not** own the product's byte order, which is
[platform-baseline.md §2](platform-baseline.md)'s and is unchanged by this
document.

**Audience:** RTL implementers, hypervisor and VMM authors, and anyone about to
write "J-Core is big-endian, so *X*" in a review.

**Prerequisites:** [platform-baseline.md §2](platform-baseline.md) (the
product's byte order), [sh4-guest-model.md](sh4-guest-model.md) (who the
observer is), [hypervisor/hardware-spec.md](hypervisor/hardware-spec.md) (the
trap architecture and the per-vCPU state contract).

---

## 0. Why this document exists, and what stops the axis moving again

This project's byte-order answer has now moved **three times**:

| | Answer | Left behind |
|---|---|---|
| 1 | "Big-endian, full stop" — [decisions/0006](decisions/0006-endianness-is-big-endian.md) as accepted | an exclusion read out of a true fact about the RTL |
| 2 | Little-endian **data** only; fetch hardwired big-endian — Decision B2-1 | a data-path change set that specified the wrong scheme (§4.4) |
| 3 | **Byte-invariant, both paths, per context** — this document | — |

Each move cost a review cycle, and each left prose behind that was still
reasoning from the previous answer. The common cause is visible in the table:
every previous round recorded a **verdict** ("big-endian", "data only") and
never wrote down the **mechanism**. A verdict has nothing to check it against,
so it moves whenever the motivation moves.

So this document is organised the other way round. §2 fixes the scheme, §4 and
§5 derive the change set from the bus convention rather than asserting it, and
every claim about the RTL below was read out of `origin/master` and is either
code-bound in [fact-ownership.md](fact-ownership.md) or marked as unbindable
with the reason. The verdict in §1 is a consequence of those, and a future
change of direction has to argue with them rather than with a preference.

---

## 1. Decision

> **Decision BE-1 (normative). J-Core gains byte-invariant bi-endian
> operation on *both* the data path and the instruction-fetch path, as a
> per-context mode the hypervisor owns and that no guest can write.**

Three clauses, each load-bearing and each argued separately below:

1. **Byte-invariant**, in ARM's sense of BE-8 rather than BE-32 — the byte at
   address *A* is the same memory byte in both modes, and only the assembly of
   bytes into register values changes. §2.
2. **Both paths.** A little-endian context's instructions are fetched
   little-endian and its data is accessed little-endian. §4 and §5.
3. **Per context, hypervisor-owned, two control bits** — one for the byte order
   a guest (or any non-hyperprivileged context) runs in, one for the byte order
   hyperprivileged entry runs in. §6.

**The reset state is big-endian on both paths, and
[platform-baseline.md §2](platform-baseline.md) is unchanged by this
document.** J-Core's kernel, toolchain and every shipped artifact remain
big-endian; the mode is a hypervisor-set software configuration that defaults
off.

**Cost: `unknown at this stage — needs measurement`.** No estimate is offered
here, by anyone — [decisions/0005](decisions/0005-unmeasured-figures-are-removed.md).
§9 records the one thing that *is* known about the cost, which is where in the
pipeline the swap sits, and corrects what the superseded text implied about it.

---

## 2. Byte invariance, and why word invariance is not available

### 2.1 The two schemes

The names are ARM's, and they are the only widely-used names for the
distinction:

| | **Byte invariance** (ARM: BE-8) | **Word invariance** (ARM: BE-32) |
|---|---|---|
| What a byte address means | the same physical byte in both modes | the hardware adjusts the low address bits of byte and halfword accesses, so a byte access in one mode reaches a *different* physical byte than in the other |
| What changes with the mode | how bytes assemble into a multi-byte register value | the address, for sub-word accesses |
| Where the hardware changes | at the register boundary | in the address path |
| The memory image | one image, seen the same way by everything | two images of the same bytes |

### 2.2 The argument, which is about the caches

**Because the swap happens at the register boundary and not in memory, every
array below that boundary stores and moves raw memory bytes and is
mode-agnostic.** That single property is what makes this design tractable, and
it is why byte invariance is chosen. Concretely:

- **No endian tag bit on a cache line**, in either L1 or the L2, and no
  widening of a tag array to carry one.
- **No invalidate on guest switch**, and none on a change of mode. A line
  filled while one context ran is valid for a context running in the other byte
  order, because it holds the same bytes.
- **No answer is needed to "what if the same line is read as bytes by one
  access and as words by another"** — under byte invariance the question does
  not arise, because both see the same bytes. Under word invariance it has no
  clean answer: a region touched as both bytes and words is self-inconsistent
  by construction.
- **One image of memory for everything that is not the CPU.** DMA engines, the
  IOMMU's own page-table reads, a second core, and the boot ROM all address
  bytes; under byte invariance they address the same bytes the CPU does. Under
  word invariance they do not, and every such master needs either its own
  matching adjustment or a documented incompatibility.

The last two are the ones that would otherwise land as unbudgeted work in
[cache/l2-spec.md](cache/l2-spec.md), [bus/fabric-spec.md](bus/fabric-spec.md)
and [iommu/hardware-spec.md](iommu/hardware-spec.md) rather than here.

### 2.3 The empirical argument

ARM shipped word invariance (BE-32) in its early architecture versions,
introduced byte invariance (BE-8) at ARMv6, and deprecated the older scheme.
That is a vendor with a large installed base choosing to carry two schemes
through a transition rather than keep the one it had — which is the strongest
available evidence about which of the two is workable at scale. §11 records the
citation.

**Consequence, stated as a rule so it survives a later "optimisation":**

> **Decision BE-2 (normative). No J-Core implementation may adjust an address
> as a function of the byte-order mode.** The mode changes the assembly of
> bytes into a register value and nothing else. An implementation that flips
> the low bits of a byte or halfword address to change byte order is
> implementing word invariance, and is non-conforming — regardless of whether
> the sequences it was tested on happen to agree.

---

## 3. What SH-4 does, where it is silent, and where J-Core diverges

### 3.1 SH-4's data format is byte-invariant, and J-Core inherits that

The SH-4 Software Manual's *Data Formats in Memory* section specifies both byte
orders for the data format, and its figure places byte 0 at bits 31:24 under
big-endian and at bits 7:0 under little-endian. **The address does not move;
the significance does.** That is byte invariance, and it is what a stock SH-4
binary's memory image depends on.

This is the half of SH-4 that J-Core inherits, and it is the half that matters
for guest compatibility: it fixes what a guest's data structures look like in
memory.

### 3.2 SH-4's *control* is a reset strap, and J-Core does not inherit it

The same section specifies the control: the byte order is set by an external
pin at power-on reset and **cannot be changed dynamically**. It is one setting
for the whole system, sampled before the first instruction is fetched.

Two consequences follow, and the second is the one that matters here:

1. **SH-4's manuals say nothing about endianness in connection with instruction
   fetch.** There was nothing to say: a strap sampled before the first fetch
   makes the fetch path's byte order a property of the board, not of the
   architecture. A search of the SH-4 software manual and the SH7750 hardware
   manual for endianness in connection with instruction fetch returns nothing.
   **So SH-4 offers no guidance on mixed-endian fetch, and none should be
   inferred from its silence.**
2. **J-Core's per-context byte-order bit is therefore a deliberate divergence
   from SH-4, not inherited compatibility.** SH-4 has a strap; J-Core has a
   mode. Nothing in the SH-4 architecture licenses changing byte order at
   runtime, and this document does not claim that it does.

That divergence is compatible with [sh4-guest-model.md §1](sh4-guest-model.md)'s
one rule, and the reason is worth being precise about rather than assuming: the
observer is the guest, and a guest **cannot see the control**. §6 makes the
bit unwritable and unreadable below hyperprivileged mode, so from inside a
guest the machine looks exactly like an SH-4 strapped to that guest's byte
order — which is the machine the guest was built for. The divergence is visible
only to the hypervisor, which is not an SH-4 and knows it.

---

## 4. The data path

Everything in this section was read out of
`jcore-cpu@origin/master` `core/datapath.vhm` and
`jcore-soc@origin/master` `components/memory/bootram_infer.vhd`.

### 4.1 The bus convention, derived rather than assumed

The change set below is a consequence of one fact about the bus, so that fact
is established first, from two independent sides:

- **The CPU side.** `to_data_o` maps a `BYTE` store to an address ending `00`
  onto `we = "1000"` — bit 3 of the byte-enable vector — and replicates the
  store byte across all four lanes of `r.d`, so `we` alone selects the lane.
- **The memory side.** `bootram_infer.vhd` writes `d(8i+7 downto 8i)` when
  `we(i)` is set, positionally, with no swap.

Composing the two: **memory byte offset 0 sits on `d(31 downto 24)`**. That is
big-endian, the two sides agree, and every claim below is derived from it.

### 4.2 The change set

Store side (`to_data_o`) and load side (`align_read_data`), both in
`core/datapath.vhm`:

| Access | Lanes / `we` | Value |
|---|---|---|
| **8-bit** | **unchanged.** The `we` map (`"1000"`/`"0100"`/`"0010"`/`"0001"` for address bits `00`/`01`/`10`/`11`) and the load's lane mux both stay exactly as they are. | unchanged — a byte has no internal byte order |
| **16-bit** | **unchanged.** `we` stays `"1100"`/`"0011"` on `addr(1)`; the load still selects `d(31 downto 16)` or `d(15 downto 0)` on the same bit. | **swap the 2 bytes of the value** |
| **32-bit** | **unchanged** (`we = "1111"`; the load takes the whole word). | **reverse the 4 bytes of the value** |

Two details that fall out of the 16-bit row and are easy to lose:

- **The store's lane replication moves with the swap, not instead of it.**
  Today the store drives `data(15 downto 0) & data(15 downto 0)`; in
  little-endian it drives the *swapped* halfword replicated the same way. The
  replication is what lets `we` do the lane selection, and it is unchanged.
- **The 16-bit load's sign extension follows the swapped value.** Today the
  sign bit is `d(31)` for an even halfword; after the swap the value's bit 15
  is the byte that was at `d(23 downto 16)`, so the sign is taken from there.
  Sign extension is not a separate change — it is the same change, applied to
  a value that is now assembled differently.

**32-bit accesses are naturally aligned by the architecture**, so the 32-bit
row never has to consider a partial-word case.

### 4.3 What this means for the SH-4 lane-mapping question

The old worry — "is there a lane-remapping boundary to hang the mode on?" — is
answered by §4.2 rather than searched for. There is no lane remapping *at all*
under byte invariance: the lanes an access uses are a function of its address
and size, exactly as today. What is added is a byte permutation of the *value*
on each side of the register file, at three widths, of which one is the
identity.

### 4.4 Correction — the superseded data-path text specified the wrong scheme

> **SUPERSEDED BY [§4.2](#42-the-change-set) — 2026-09-08.** The change set
> Decision B2-1 recorded in [sh4-guest-model.md §3.1](sh4-guest-model.md) is
> **word-invariant**, and this section records the correction visibly rather
> than reword it away.

The superseded text read, in full:

> - `to_data_o` — the store path's `we` byte-enable and data-lane mapping. Today
>   a `BYTE` store to address `…00` drives `we = "1000"`; little-endian drives
>   `"0001"`.
> - `align_read_data` — the load path's lane mux. Today a `BYTE` load from `…00`
>   takes `d(31 downto 24)`; little-endian takes `d(7 downto 0)`.

Both bullets change the `we` index (and the load lane) from `3 − addr` to
`addr`. That is **address adjustment**: it sends a byte access to address 0 to
physical byte 3. It is word invariance — the BE-32 scheme of §2.1 — and it
changes byte-access behaviour, which byte invariance must not. Under Decision
BE-1 the 8-bit row of §4.2 is **unchanged**, on both sides.

Recording it rather than quietly rewording it is the point: the text was
specific, plausible, and merged, and the next person to specify a byte-order
mode from first principles will reach for exactly the same construction,
because address adjustment is the obvious way to do it if you have not met the
distinction in §2. The reason it is wrong is §2.2, not taste.

---

## 5. The instruction-fetch path

The claim to establish is narrow and is the crux of Decision BE-1's second
clause:

> **Every halfword *selection* on the fetch path is derived from an address.
> Byte invariance changes no address. Therefore no selection changes, and the
> whole of the I-side change is one 16-bit byte swap.**

That is verified below rather than asserted, because it is what makes fetch-side
bi-endianness cheap enough to be worth having.

### 5.1 Every fetch-path selection, and what drives it

| Site (`origin/master`) | Selection | Driven by |
|---|---|---|
| `jcore-soc` `targets/data_bus_pkg.vhd`, `splice_instr_data_bus` reply path | `data_i.d(31 downto 16)` vs `d(15 downto 0)` | `instr_o.a(1)` — an address bit |
| `jcore-cpu` `cache/cache_pkg.vhd`, `to_cache_idata` | high vs low half of the cache word | `a(CACHE_I_WIDTH_BITS)` — an address bit |
| `jcore-cpu` `cache/icache_ccl.vhm`, critical-word path in `MISS2`/`MISS3` | `this.cd1(31 downto 16)` vs `cd1(15 downto 0)` | `a.a(4 downto 1) = this.ma0(4 downto 1)` — a comparison of two addresses |
| `jcore-cpu` `cache/icache_ccl.vhm`, cache-off path | `mtoc.rfilld(15 downto 0)` | not a selection here at all: `rfilld` is `ic_onm & this.d`, and the 16-bit `d` was selected in the `mcl` by `to_cache_idata(ma0_1in & '0', ma.d)` — an address bit |
| `jcore-cpu` `cache/icache_mcl.vhm`, line-fill packing | rotates the fill word by a halfword so the *requested* halfword lands in `cd(31 downto 16)` | `this.ma0_1in` (captured from `ctom.filla(1)`) and `this.ma0(4 downto 2) = this.reqw` — address bits |

`jcore-cpu` `cache/icache_cacheable_mux.vhd` is the uncached-fetch bypass; it
calls the same `splice_instr_data_bus` procedure and adds no selection of its
own.

**Not one of these conditions reads instruction data.** Every one is an address
bit, or an equality between two addresses. So under byte invariance —
which by Decision BE-2 changes no address — **the icache, the line-fill packing,
the bus glue and the uncached bypass are all untouched**, and so are the dcache
and the L2, which never see the fetch path at all.

### 5.2 Where the swap goes

One 16-bit byte swap on the fetched instruction word, at the register boundary,
exactly as on the data side.

`jcore-cpu@origin/master` `core/cpu.vhd` carries the whole of the instruction
reply on a single line — `dp_inst_i.d <= inst_i.d;` — which is the one point
that covers every downstream consumer.

The alternative site is `core/datapath.vhm`'s capture,
`this.if_dr_next := inst_i.d;`. **A swap placed there must cover three uses,
not one:** the same enable also evaluates `check_illegal_delay_slot(inst_i.d)`
and `check_illegal_instruction(inst_i.d)`, and an illegal-instruction check run
on an unswapped opcode is a decode-fidelity break of exactly the shape
[sh4-guest-model.md §5](sh4-guest-model.md), Decision B2-5, outlaws — the
little-endian guest's legal instruction would be tested as some other opcode.
The `cpu.vhd` site avoids that hazard by construction, which is the reason to
prefer it; this document does not otherwise mandate a site.

### 5.3 Literal pools are data, and that is correct

SH's PC-relative loads — `MOV.W @(disp,PC),Rn` and `MOV.L @(disp,PC),Rn` — are
**data** accesses and are swapped by §4, not by §5. That is the right answer
and not an accident of where the swap sits: a little-endian image's literal
pool is little-endian *data*, laid down by a little-endian assembler, and it
must be read as such. An implementation that routed literal loads through the
instruction-fetch swap would swap 16 bits of a 32-bit literal and be silently
wrong on every `MOV.L`.

---

## 6. The control — two bits, and why two

### 6.1 The bits

> **Decision BE-3 (normative). Byte order is selected by two hypervisor-owned
> bits.**
>
> - **`LE`** — the byte order of the current **non-hyperprivileged** context:
>   a guest, or the host's supervisor and user code. Written only from
>   hyperprivileged mode. Per-vCPU and per-thread-context state (§6.4).
> - **`HLE`** — the byte order **hyperprivileged code runs in**, and therefore
>   the byte order every hypervisor entry starts in, whatever the interrupted
>   context was running.
>
> The effective byte order of every access — instruction fetch, load and store
> alike — is `HLE` when `SR.HPRIV = 1` and `LE` otherwise. **Both bits reset to
> big-endian**, and on an implementation without the hypervisor extension
> neither exists and the machine is big-endian
> ([platform-baseline.md §2](platform-baseline.md)).

This document does **not** assign either bit a register or a position. That is
[hypervisor/hardware-spec.md §2.2](hypervisor/hardware-spec.md)'s to allocate
out of the hyperprivileged control-register family, and
[soc/p4-mmio-map.md](soc/p4-mmio-map.md)'s if either gains an MMIO alias; §10
records it as an open item with that owner.

### 6.2 Why the second bit exists: the transition is where this gets hard

The hard part of a per-context byte-order mode is not the swap, it is the
**transition**. A trap taken while a little-endian guest is running transfers
control to a handler that is not part of that guest, and the first instruction
of that handler must be fetched in *some* byte order. If that byte order is
"whatever the trapped context was using", the hypervisor's entry point has to
exist in both byte orders, or the machine has to be told which one out of band —
and either way there is a window in which the answer is a convention rather than
a fact.

`HLE` removes the window. Hyperprivileged mode selects `HLE`; `SR.HPRIV` is set
by hardware as part of trap entry
([hypervisor/hardware-spec.md §4.1](hypervisor/hardware-spec.md)); so the
handler's byte order changes in the same indivisible step as the privilege
level, and there is no ordering to specify between them. Symmetrically, `HRTE`
clears `SR.HPRIV` and the byte order reverts to `LE` in that same step.

This is [PowerPC `MSR[ILE]`](#11-prior-art-pre-2006)'s pattern, adopted
deliberately: a second privileged bit that fixes the byte order the handler
runs in, independently of the interrupted context, applied by hardware at the
transition. PowerPC realises it by copying `ILE` into `LE` on interrupt; J-Core
realises it by selecting on `SR.HPRIV`, which needs no copy and no restore
because `SR.HPRIV` is already restored by `HRTE`. The mechanism — *the handler's
byte order is a separate architectural bit, applied by hardware at the privilege
transition* — is the same one.

**A hypervisor entry sequence must not straddle the change.** This is a
requirement on the RTL, not on software: the byte order applies to the
instruction *fetched at* `VBR_HYP + offset`, not to the one after it. Stated as
a rule because it is the only place where a plausible implementation could get
the timing wrong and still pass a big-endian-only test suite — with `HLE` and
`LE` both big-endian, which is the shipping configuration, no test can see the
difference.

### 6.3 What a guest can see, and what it cannot

**`LE` is not guest-writable and not guest-readable.** A guest that could flip
its own byte order mid-execution could desynchronise the hypervisor's view of
its memory; no SH-4 guest expects to be able to, because on SH-4 the control is
a strap (§3.2). Making the bit unreadable as well as unwritable is what keeps
§3.2's compatibility argument true: the guest sees a machine strapped to its own
byte order, with no bit anywhere in its architectural state that says so.

**Consequence for placement, and it rules one option out.** The obvious home for
`LE` is a reserved bit of `SR`, beside `SR.HPRIV`, because `SR` is already saved
to `HSSR` and restored by `HRTE` atomically with the privilege transition. That
is *almost* right and is rejected: `SR` is guest-readable via `STC SR,Rn`, and
SH-4 defines the bits in question as reserved and read-as-zero, so a guest would
read a set bit where its architecture promises a clear one — a divergence the
observer can see, which is what
[sh4-guest-model.md §1](sh4-guest-model.md) is about. A hyperprivileged register
has no such problem, because the guest cannot read it at all
([hypervisor/hardware-spec.md §3.4](hypervisor/hardware-spec.md) traps the whole
family). An implementation that wants the `SR` placement anyway must mask the bit
out of every guest-visible read of `SR` **and** of `SSR`, and must say so.

### 6.4 `LE` is per-vCPU and per-thread-context state

`LE` is live architectural state that a context switch must carry, by exactly
the argument [hypervisor/hardware-spec.md §2.9](hypervisor/hardware-spec.md)
makes for every other per-vCPU register and
[mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md) makes for `ASIDR`: a vCPU
resumed under the wrong byte order sees silently wrong data and executes
silently wrong instructions. On an FGMT implementation
([glossary §4](glossary.md)) it is per thread context by the same argument
again, because there is no exit at which to run a save sequence.

`HLE` is **not** per-vCPU: it describes the host, and there is one host. It is
written once at hypervisor initialisation.

---

## 7. What the mode does not reach

Stated so the boundary is enumerable rather than inferred, and because three of
these are places a reader would reasonably expect a byte-order requirement to
land.

- **The hardware TSB walker.** `core/tlb_walk.vhd` takes `bus_d => db_i.d`
  directly in `core/cpu.vhd` — it reads full 32-bit words off the bus and never
  passes through `align_read_data`. So the walker's PTE reads are structurally
  outside the mode, which is the correct behaviour: page tables belong to the
  host, not to the guest whose translations they hold. This costs nothing and
  needs no rule; it is recorded because it would otherwise be re-derived.
- **The caches, the fill path, the bus fabric and every non-CPU bus master.**
  §2.2. They move bytes.
- **The store-queue burst.** Queue-data stores are ordinary data accesses and
  follow §4. The 32-byte burst itself is a byte copy from the buffer to memory
  and has **no byte order** under byte invariance — see
  [sq/spec.md §6.4](sq/spec.md), which this document corrects on that point.
- **The SIMD lane order** of [simd/spec.md §2.2](simd/spec.md), which is a
  separate convention and is not affected by this mode. The glossary already
  keeps the two apart ([glossary §7](glossary.md)).
- **Hyperprivileged readback of a guest's store-queue buffers**
  ([sq/spec.md §6.2](sq/spec.md)). The hypervisor runs at `HLE`, so it reads
  those buffers in the host's byte order — which is what saving and restoring
  raw bytes requires.

**One thing it *does* reach and that is not yet specified: the emulated-MMIO
register writeback.** [hypervisor/hardware-spec.md §4.5](hypervisor/hardware-spec.md)
rule 2 has hardware write `HMDR` into a guest register on `HRTE`, "sign- or
zero-extending per `HMCR.SIZE` exactly as the original load would have" — and
once a byte-order mode exists, "exactly as the original load would have"
silently includes a byte swap. Whether `HMDR` holds the guest-register value
(no swap) or the bus-lane bytes (swap) is a real choice, it is currently
unstated, and both a load's writeback and a store's capture depend on it. §10
records it with an owner.

---

## 8. Consequences for other documents

| Document | What changes |
|---|---|
| [sh4-guest-model.md §3.1](sh4-guest-model.md) | Decision B2-1 is superseded by BE-1. Its data-path change set is corrected (§4.4); its exclusion of the fetch path is reversed. |
| [sh4-guest-model.md §3.5, §4](sh4-guest-model.md) | Stock little-endian SH-4 binaries can execute natively once the mode exists, so Dreamcast is gated on the *other* gaps — no FPU, no device model — and not on byte order. |
| [sh4-guest-model.md §5](sh4-guest-model.md) | The four encoding collisions become **live and urgent**: a stock little-endian SH-4 guest can now reach them. |
| [decisions/0006](decisions/0006-endianness-is-big-endian.md) | The instruction-fetch half is superseded. Rejected-alternative objections 2 and 4 stand and are untouched — they are about a *wholesale* switch, which this is not. |
| [platform-baseline.md §2](platform-baseline.md) | Verdict unchanged; one supporting argument is withdrawn, because the fetch path now has a mode bit. |
| [hypervisor/hardware-spec.md §2.9](hypervisor/hardware-spec.md), [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md) | Both already record the gap. Updated for the two-bit scheme: `LE` is in those lists, `HLE` is not. |
| [sq/spec.md §6.4](sq/spec.md) | Still correct that queue-data stores follow the guest's mode. Corrected on the burst, which under byte invariance has no byte order. |
| [fpu/spec.md §6.2.1](fpu/spec.md) | The double-`FMOV` half-pair requirement stands; its premise that fetch stays big-endian does not. |
| [glossary.md §7](glossary.md) | The **Endianness** entry's cross-reference to a data-only guest mode is replaced. |

---

## 9. Cost

**`unknown at this stage — needs measurement`**, per
[decisions/0005](decisions/0005-unmeasured-figures-are-removed.md). No estimate
appears in this document.

One thing about the cost *is* known and is worth recording, because the
superseded text implied otherwise. Decision B2-1 described the change as making
`to_data_o`'s lane map and `align_read_data`'s lane mux "mode-dependent", which
places the mode in a **mux select** — in the load path's address-to-lane
decode. Under byte invariance the selects are untouched (§4.2) and the swap is a
**byte permutation of the value at the register boundary**, after the lane mux on
loads and before the lane replication on stores. That is a different position in
the pipeline with a different timing character, and a measurement taken against
the earlier description would be measuring something this document does not
specify.

What to measure, so the item is actionable rather than a placeholder: `Fmax` on
the `j4` and `j4c` legs of `jcore-cpu`'s `synth-cpu` matrix, with and without
the mode, against the CI floors [platform-baseline.md §3](platform-baseline.md)
owns.

---

## 10. Open items, with owners

- **The prior-art screen this document cannot perform.** §11 establishes that
  every *structure* here is thoroughly pre-2006. It does **not** establish
  freedom to operate on the purpose-specific *combination* — **per-guest
  endianness switched on VM entry and exit under a hypervisor** — which is
  precisely the shape [glossary §2.1](glossary.md)'s second rule warns about:
  a pre-2006 structure is necessary but not sufficient when the
  purpose-specific combination is separately claimed, and the worked example
  there is a citation that satisfied the policy as written and still walked
  into a live claim. Per-*context* endianness control is 1990s prior art and is
  cited as such; per-*guest* endianness under a hypervisor is a different
  combination and **no web search — mine, or anyone's — closes it**. This needs
  a professional search before RTL commits, on the combination and not on the
  structures. **Owner: project owner**, jointly with whoever commissions the
  screen already owed on [ooo/j32ooo-spec.md §20.7](ooo/j32ooo-spec.md)'s two
  load-bearing findings; the same engagement should cover both.
- **Allocate `LE` and `HLE`.** Which hyperprivileged control register, which
  bit positions, whether either gains a P4 MMIO alias, and the `LDC`/`STC`
  encodings if a new register is needed. §6.1 deliberately assigns none of
  these. **Owner: [hypervisor/hardware-spec.md §2.2](hypervisor/hardware-spec.md)**,
  jointly with [soc/p4-mmio-map.md](soc/p4-mmio-map.md) for any alias.
- **Decide what `HMDR` holds under a byte-order mode** (§7). The
  complete-on-resume writeback is a register write, and the mode is a
  register-boundary property, so the emulated-MMIO path cannot stay silent about
  it. Both directions are defensible; neither is stated today, and a VMM author
  and an RTL author reading
  [hypervisor/hardware-spec.md §4.5](hypervisor/hardware-spec.md) rule 2 today
  would reasonably choose differently. **Owner:
  [hypervisor/hardware-spec.md §4.5](hypervisor/hardware-spec.md)**, jointly
  with the VMM work.
- **Build the mode.** §4.2's value permutations, §5.2's single instruction-word
  swap, and §6's two bits, with `LE` added to the per-vCPU and per-context state
  lists ([hypervisor/hardware-spec.md §2.9](hypervisor/hardware-spec.md),
  [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md)). Cost is `unknown at this
  stage — needs measurement`. **Owner: RTL / SoC integration**, jointly with
  [hypervisor/hardware-spec.md](hypervisor/hardware-spec.md).
- **A test that can see §6.2's transition rule.** With `HLE` and `LE` both
  big-endian — the shipping configuration — no existing test distinguishes a
  correct implementation from one that applies the byte order one instruction
  late at a hypervisor entry. The verification plan needs a case that runs a
  little-endian guest and traps out of it. **Owner: RTL / SoC integration**,
  with the hypervisor verification work.
- **The four encoding collisions are now reachable by stock guest code**
  ([sh4-guest-model.md §5.1](sh4-guest-model.md)). That is a change in urgency,
  not in ownership. **Owner: B4 *and* an RTL / SoC co-owner**, unchanged.

---

## 11. Prior art (pre-2006)

Per [glossary §2](glossary.md). Every mechanism this document introduces is
matched below to a pre-2006 source, and §2.1's two matching rules are applied
rather than merely cited: the match is on **mechanism, not motivation**, and
§10's first open item records where a pre-2006 structure is **not sufficient**.

---

## 12. What would reopen this

- **A measurement showing the fetch-path swap does not fit the timing budget.**
  §9 says the cost is unknown; if measurement says it is unaffordable, the
  fallback is not "revert to data-only" — that configuration buys
  little-endian data for big-endian-compiled software, which is a workload
  nobody has asked for. The fallback is software emulation for little-endian
  guests, which is where they were before this document.
- **The prior-art screen of §10 returns a live claim on the combination.** That
  is the one finding that changes the design rather than the schedule, and
  [glossary §2](glossary.md) rule (b) — drop the mechanism — applies.
- **A second bus master gains a byte-order mode of its own.** §2.2's "one image
  of memory" argument assumes the CPU is the only thing with a mode. A
  byte-swapping DMA descriptor field, say, would make that assumption false and
  the argument would need re-making rather than restating.
- **`SR` acquires the `LE` bit after all** (§6.3), in which case the masking
  requirement in that section becomes normative text somewhere rather than a
  condition attached to a rejected option.
