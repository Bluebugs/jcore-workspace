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
argue "J-Core is big-endian, so *X*" ([platform-baseline.md §2](platform-baseline.md))
in a review. §1 is where that argument now has to stop.

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

**Attribution, because it would be easy to read this list as ARM's and it is
not.** ARM's own stated reason for introducing byte invariance is narrower than
the four bullets above: the introduction to §A2.7 of the ARM ARM (DDI 0100I,
p. A2-30) motivates it by fine-grain **big-endian and little-endian shared data
structures** and by conformance to IEEE Std 1596.5-1993. **The four bullets
above are this project's own argument**, not ARM's — the cache-line and
bus-master consequences in particular are consequences *we* draw for *this*
machine, where the other agents on the bus are not processors at all. They are
sound and they are ours; ARM is cited in §11 for the taxonomy and for the
transition, and for nothing else.

*An earlier revision of this paragraph quoted ARM as saying the difference
between the schemes "is only visible when communicating between big endian and
little endian agents using memory". **That quotation was misattributed and is
withdrawn.** It is not in DDI 0100I — the word "agents" does not occur in that
manual — and its actual source is a later ARM document, post-2006, discussing
the word-invariant BE-32 scheme: the wrong manual, the wrong side of the
prior-art cutoff, and the opposite scheme to the one specified here. It is
recorded rather than silently removed because it appeared in the one paragraph
of this document whose entire purpose is scrupulous attribution, which is the
least excusable place for it and the most instructive.*

### 2.3 The empirical argument

ARM shipped word invariance (BE-32) through ARMv4 and ARMv5, introduced byte
invariance (BE-8) at ARMv6, and retired the older scheme in two steps: at ARMv6
`BE-8` became **mandatory** and `BE-32` support became IMPLEMENTATION DEFINED,
and at ARMv7 `BE-32` was removed outright. That is a vendor with a large
installed base choosing to carry two schemes through a transition rather than
keep the one it had — which is the strongest available evidence about which of
the two is workable at scale.

*Two accuracy notes, because this argument is only worth as much as its dates.*
ARMv6's technical details were announced in **October 2001**, the first
implementation shipped in 2002, and the ARM ARM carried the architecture from
Issue F (July 2004); the edition quoted in §11 is **Issue I, July 2005**. And
the ARMv7 removal is **post-2006**, so it is evidence for *this* argument but is
**not** cited as prior art anywhere in §11 — the pre-2006 half of the story
(BE-8 defined, mandatory, and BE-32 demoted to optional) is by itself sufficient
for the policy, and mixing the two would put a post-cutoff document in a
prior-art table.

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

The **SH-4 Programming Manual** (Renesas/Hitachi, Rev. 5.0, 04/2001,
ADE-602-156D) §2.5 *Data Formats in Memory* specifies both byte orders for the
data format, and its figure 2.5 draws the same three longwords under each.

**What the figure shows, stated precisely, because the inference rests on it.**
Figure 2.5 is drawn as a *mirror*: the big-endian half runs its base addresses
`A`, `A+4`, `A+8` down the page while the little-endian half runs `A+8`, `A+4`,
`A` down the page, and the byte columns reverse with them. So **no single row
label appears identically on both halves**, and anyone checking this document
against the figure should expect not to find one. What the two halves do show is
the byte at address `A` occupying bits 31:24 on the big-endian side and bits 7:0
on the little-endian side — the same byte, the same address, a different
position within the longword. **The address does not move; the significance
does.** That is what a stock SH-4 binary's memory image depends on, and it is
the half of SH-4 that J-Core inherits: it fixes what a guest's data structures
look like in memory.

*An earlier revision of this paragraph said the figure showed "the row's address
label unchanged", which is not how it is drawn and would have sent a checker
looking for something that is not there. The conclusion is unaffected; the
evidence for it is the byte-position reversal at a fixed address, not a repeated
label.*

**"Byte-invariant" is this project's classification, not Renesas's word.** The
term appears nowhere in the SH-4 Programming Manual, the SH7750 hardware manual
or the SH-4A software manual; Renesas never places SH-4 in the byte-invariant /
word-invariant taxonomy at all, because that taxonomy is ARM's (§2.1) and
postdates the parts. The classification is an inference from figure 2.5 and from
the SH7750 hardware manual's 8-bit-device transfer tables, in which a longword access
issues four sequential byte transfers whose first carries register bits 31:24 in
big-endian and bits 7:0 in little-endian, with no address transformation
documented anywhere. It is a sound inference and it is ours; §11 cites the
figure, not a Renesas verdict.

**And SH-4's byte invariance has a documented exception at 64 bits, which
J-Core must not inherit by accident.** The note under figure 2.5 of that same
Programming Manual — and **only** there; the SH-4A software manual carries no
such note, so do not cite it for this — states that
SH-4 does not support endian conversion for the 64-bit data format, so a
double-precision floating-point access in little-endian mode has its upper and
lower 32 bits reversed. That is a real hole in a clean byte-invariance claim and
it is called out rather than glossed:

- **It is outside this document's change set.** J-Core's data path has no 64-bit
  access — `to_data_o`'s `mem.size` is `BYTE`, `WORD` or `LONG` and nothing
  else — so there is no 64-bit case for §4.2 to specify, and Decision BE-1 is
  unaffected.
- **It is where [fpu/spec.md §6.2.1](fpu/spec.md)'s half-pair rule comes from.**
  That section already requires a Tier-1 FPU to swap a double-`FMOV`'s half-pair
  order under the little-endian mode. Until now that requirement was derived
  from reasoning about what a guest expects; it is in fact **what the SH-4
  manual documents its own hardware doing**, which is a considerably stronger
  footing. An implementer building a Tier-1 FPU should read the rule as
  compatibility with a documented SH-4 behaviour, not as a J-Core invention.
- **It does not weaken §2.2.** The cache argument is about accesses that reach
  the cache arrays, all of which are 32 bits or narrower on this machine.
- **And it is not an SH-4 quirk.** SPARC V9 — byte-invariant on every ordinary
  access, and explicit about it (§11.1) — carves out exactly the same shape of
  exception for exactly the same width: §6.3.1.2.2 says that for the deprecated
  `LDD`/`STD` double-word instructions in little-endian mode, "the word at the
  address specified in the instruction + 4 corresponds to the even register…
  the word at the address specified in the instruction corresponds to the
  following odd-numbered register" — a word-pair order swap, which is the
  half-pair swap under another name. Two architectures that independently chose
  byte invariance both made a 64-bit exception to it. That is worth knowing
  before treating the SH-4 note as an oddity to design around: it is the
  recurring cost of composing a 64-bit datum out of two 32-bit accesses on a
  32-bit machine, and any J-Core FPU will meet it too.

### 3.2 SH-4's *control* is a reset strap, and J-Core does not inherit it

The same section specifies the control: the byte order is set by an external
pin at power-on reset and **cannot be changed dynamically**. It is one setting
for the whole system, sampled before the first instruction is fetched.

Two consequences follow, and the second is the one that matters here:

1. **SH-4's manuals say nothing about endianness in connection with instruction
   fetch.** There was nothing to say: a strap sampled before the first fetch
   makes the fetch path's byte order a property of the board, not of the
   architecture. Four manuals were searched in full — the SH-4 Programming
   Manual, two revisions of the SH7750 hardware manual, and the SH-4A software
   manual —
   and every occurrence of "endian" across them is a data-format, mode-pin,
   `BCR1.ENDIAN`, bus-alignment, `FMOV`/`FPSCR.SZ`, PCMCIA or SDRAM byte-lane
   reference. Not one is tied to instruction fetch, the instruction cache or
   opcode byte order. Checking the other direction, the software manual's
   occurrences of "instruction fetch" are all about alignment, exceptions and
   pipeline stages. **So SH-4 offers no guidance on mixed-endian fetch, and none
   should be inferred from its silence.**

   *This is a negative result and is reported as one.* It rests on full-text
   search of those four documents, not on the absence of web results; it does
   not cover figures that extract poorly to text, and it does not cover ST's
   separate SH-4 core architecture manual, which could not be retrieved. What
   makes the silence *conspicuous* rather than merely unremarkable is that the
   comparable architecture is not silent: ARM states explicitly that in its
   mixed-endian configurations "instruction fetches always assume a little
   endian byte order model" (§11). A manual that had considered the question
   would have answered it.
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

**And the same pattern holds on the slave side of the instruction bus**, in four
`jcore-soc@origin/master` memories that answer fetches directly. Each registers
`ibus_i.a(1)` and uses it to pick the halfword; none reads instruction data:

| Site (`jcore-soc@origin/master`) | Selection |
|---|---|
| `components/memory/bootram_infer.vhd:82` | `i_word(31 downto 16)` vs `(15 downto 0)`, on `i_half` — registered from `ibus_i.a(1)` at line 68 |
| `components/memory/bootram_infer_coremark.vhd:90` | the same, on `i_half` registered at line 76 |
| `components/memory/dev_ddr_spram.vhd:64` | `sp_dr(31 downto 16)` vs `(15 downto 0)`, on `r_instr_hi` — registered from `ibus_i.a(1)` at line 54 |
| `components/memory/dev_ddr_spram_boot.vhd:93` | the same, on `r_instr_hi` registered at line 83 |

*These were absent from the first revision of this section, which presented the
five rows above as the complete set. They **strengthen** the claim rather than
qualify it — four more selections, all address-derived, all therefore
unchanged — but the section had said "every" and did not mean it. Nine sites,
and the pattern is uniform: on this machine an instruction halfword is chosen by
an address bit everywhere it is chosen at all.*

**Not one of these conditions reads instruction data.** Every one of the nine is
an address bit, or an equality between two addresses. So under byte invariance —
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

**One instruction source must *not* be swapped, and a `cpu.vhd`-sited swap
excludes it for free.** `datapath.vhm`'s debug `INSERT` command writes
`this.if_dr_next := debug_i.ir` and runs the same two illegal checks on it — a
second, independent writer of the instruction register that never passes through
`inst_i`. That is correct behaviour and not an oversight in the placement: a
debug-inserted instruction is handed to the CPU as a 16-bit opcode by the
debugger, not fetched from memory, so it has no memory byte order to convert and
applying the mode to it would corrupt it. A swap at `cpu.vhd`'s
`dp_inst_i.d <= inst_i.d` misses this path automatically; a swap placed inside
the `datapath.vhm` capture must be careful to cover the `inst_i.ack` arm only.
That asymmetry is a second reason to prefer the `cpu.vhd` site.

### 5.3 Literal pools are data, and that is correct

SH's PC-relative loads — `MOV.W @(disp,PC),Rn` and `MOV.L @(disp,PC),Rn` — are
**data** accesses and are swapped by §4, not by §5. That is checkable rather
than assumed: `jcore-cpu@origin/master` `decode/gen-go/spec/mov.toml` gives both
`ma_op = "READ"`, with `ma_size = "16"` and `"32"` respectively, so they issue
on the memory-access port and land in `align_read_data` like any other load. That is the right answer
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

**This two-bit pattern is adopted from prior art, not invented here**, and §11
gives two independent pre-2006 instances of it. PA-RISC pairs `PSW[E]` with a
software-writable (and implementation-dependent) *default endian bit* that
"controls whether the PSW E-bit is
set to 0 or 1 on interruptions"; PowerPC pairs `MSR[LE]` with `MSR[ILE]`, which
"is copied into `MSR[LE]` to select the Endian mode for the context established
by the interrupt". Both realise it by **copying** the second bit into the first
at the transition. J-Core realises it by **selecting** on `SR.HPRIV`, which
needs no copy and no restore because `SR.HPRIV` is already set by trap entry and
restored by `HRTE`. The mechanism — *the handler's byte order is a separate
architectural bit, applied by hardware at the privilege transition* — is the
same one; only the implementation of "applied" differs, and
[glossary §2.1](glossary.md)'s first rule is explicit that a match is at the
level of mechanism.

Of the three, **PA-RISC is the closest match and is the one to read first**: its
`E` bit is byte-invariant *and* covers instruction fetch, which is exactly this
document's combination. SPARC V9 is byte-invariant but keeps fetch big-endian,
and PowerPC's `LE` is an address-munging scheme (§11.3, §11.3a).

**One instructive divergence in SPARC V9, since it is the nearest thing to a
counter-example.** Its RED_state reset trap does *not* copy: it forces
`PSTATE.TLE ← 0` and `PSTATE.CLE ← 0`, "big-endian mode for traps" and
"big-endian mode for non-traps". So even the architecture that copies on every
ordinary trap makes reset an exception and drives both bits to the machine's
native order. §6.1 does the same thing for the same reason, and it is worth
knowing that this is a convergent choice rather than an arbitrary one.

**The third trap destination needs no rule, and checking that is what makes the
scheme complete.** [hypervisor/hardware-spec.md §4.1](hypervisor/hardware-spec.md)'s
trap-entry logic has three arms, and only two of them enter hyperprivileged
mode. The middle arm — an exception delegated to the guest kernel via `HEDR` —
sets `SR.MD`, `SR.BL` and `SR.RB` and vectors to the guest's own `VBR`, leaving
`SR.HPRIV` at 0. So a delegated exception runs its handler at `LE`, which is
correct: that handler is the guest's own code, built in the guest's byte order.
The two bits cover all three arms with no third case, and a guest's internal
exception handling needs no byte-order rule of its own.

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
the canonical `SR` layout in
[hypervisor/hardware-spec.md §2.1](hypervisor/hardware-spec.md) — which states
that it matches the SH-4 hardware manual for every bit J-Core inherits — marks
every unallocated bit *reserved, read-as-zero, write-ignored*. A guest would
therefore read a set bit where its architecture promises a clear one: a
divergence the observer can see, which is what
[sh4-guest-model.md §1](sh4-guest-model.md) is about. `SR.HPRIV` sits in that
same register and raises no such problem, because a guest only ever reads it as
0; `LE` is different precisely because it reads as 1 for exactly the guests that
can look. A hyperprivileged register
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
  load-bearing findings; the same engagement should cover both. **Point it at
  §11.3 first:** the fetch clause rests on a single pre-2006 source, and a
  single-source clause inside a purpose-specific combination is where the two
  §2.1 rules compound rather than cancel.
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
  [mmu/hardware-spec.md §2.1a](mmu/hardware-spec.md)).
  Cost: `unknown at this stage — needs measurement`.
  **Owner: RTL / SoC integration**, jointly with
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

**Every citation below was read in the primary source before being written
down**, and where a source could not be obtained that is said rather than
papered over. This is stated because the first draft of this section was
assembled from a list of *expected* citations, and checking them changed three
of the four load-bearing ones (§11.3), added a fifth architecture that reframed
the weakest clause (§11.3a), and — in §2.2, outside this section — produced one
quotation that turned out to belong to a different ARM manual on the wrong side
of the cutoff. That last one is withdrawn in place. **A citation nobody opened is
a guess with a document number attached**, and this document has now generated
one of those for every three it got right.

### 11.1 The mechanisms, and what each is matched to

| Mechanism | Prior art |
|---|---|
| **Byte-invariant** bi-endian data format — the same byte address in both modes, only the assembly into register values changing | **SPARC V9** (1994), §6.3.1.2.1 and §6.3.1.2.2, which state identically under *both* addressing conventions: "A load/store byte instruction accesses the addressed byte in both big- and little-endian modes." Its figures 35 and 36 label both halves with the **same** `Address<1:0> = 00 01 10 11`, differing only in which register field maps to each. §H.1.6 makes the mechanism explicit from the other side — a little-endian store's "data will be reordered before the bytes are written to memory", never the address. **PA-RISC 1.1**, `PSW[E]`, Third Edition, February 1994 (HP 09740-90039), §2 *Byte Ordering*: byte loads and stores are **unaffected** by `E`, while halfword and word operands reverse within their own addresses. **SH-4 Programming Manual** §2.5 / figure 2.5 (Renesas/Hitachi Rev. 5.0, 04/2001, ADE-602-156D) — the classification is ours, see §3.1. *The 2001 Programming Manual is cited and not the later Renesas SH-4 **Software** Manual (Rev. 6.00, REJ09B0318-0600), whose §2.5, figure 2.5 and 64-bit note are byte-identical: that edition is dated September **2006** and would breach [glossary §2](glossary.md)'s cutoff. Same words, wrong side of the line.* **ARM BE-8**, ARM ARM DDI 0100I, July 2005, §A2.7.2 |
| The taxonomy itself, and the demonstration that the alternative was abandoned | **ARM DDI 0100I §A2.7.2** names `BE-8`, `BE-32` and `LE`, defines byte invariance as "the address of a byte in memory is the same irrespective of whether that byte is being accessed in a big endian or little endian manner", and §A2.7.3 makes `BE-8` mandatory at ARMv6 with `BE-32` IMPLEMENTATION DEFINED |
| **Per-context, privileged** byte-order control | **SPARC V9** `PSTATE.CLE`, bit 9 (*The SPARC Architecture Manual, Version 9*, Weaver & Germond eds., SPARC International / PTR Prentice Hall, © **1994**, ISBN 0-13-825001-4), §5.2.1.2: with `CLE = 1` "all data accesses using an implicit ASI are performed in little-endian byte order". **PA-RISC** `PSW[E]` (1994) — in the PSW, saved to `IPSW` on interruption, restorable only by privileged `RFI`. **PowerPC** `MSR[LE]` (*PowerPC Architecture*, First Edition, May 1993, IBM SR28-5124-00, §10.2.3), privileged via `mtmsr`. **MIPS** `Status[RE]` bit 25 (R4000 User's Manual, 1992/1994), which reverses **user** mode's endianness relative to the kernel's |
| Byte order applying to **instruction fetch** as well as data, under that same per-context bit | **PA-RISC 1.1** (1994), §2 *Byte Ordering*: "**The E-bit also affects instruction fetch.**" This is the only pre-2006 source found that does so — see §11.3 |
| A **second** privileged bit fixing the byte order the trap handler runs in, applied by hardware at the transition | **SPARC V9** `PSTATE.TLE`, bit 8 (1994). §5.2.1.3: "When a trap is taken, the current PSTATE register is pushed onto the trap stack and the PSTATE.TLE bit is copied into PSTATE.CLE in the new PSTATE register. **This allows system software to have a different implicit byte ordering than the current process.**" The trap-entry pseudocode in §7.6.1 *Normal Trap Processing* (printed p. 107) carries the step verbatim as `PSTATE.CLE ← PSTATE.TLE (set endian mode for traps)`, and it recurs in five further trap variants in §7.6.2. **PA-RISC 1.1** (1994) *default endian bit*: "controls whether the PSW E-bit is set to 0 or 1 on interruptions" — described as **implementation-dependent** and software-writable, with no architected register named, so this document names none either. **PowerPC** `MSR[ILE]` (1993, §10.2.3): "When an interrupt is taken, this bit is copied into MSR_LE to select the Endian mode for the context established by the interrupt", tabulated for every interrupt type in Figure 68 |
| The hypervisor owning a guest-visible mode the guest cannot write | IBM VM/370 (1972); Popek & Goldberg, CACM 17(7), 1974 — already cited by [sh4-guest-model.md §9](sh4-guest-model.md) |

### 11.2 Applying §2.1's first rule — mechanism, not motivation

PA-RISC's `E` bit and its default endian bit exist to let one HP-UX system run
big-endian and little-endian binaries side by side. PowerPC's `MSR[LE]`/`ILE`
pair exists to ease porting little-endian operating systems. Neither was built
for virtualization, and neither had a hypervisor in mind. Under
[glossary §2.1](glossary.md)'s first rule that is irrelevant: what is claimed is
structure and steps, and the structure here — *a privileged per-context bit
selecting byte order for fetch and data, plus a second privileged bit that fixes
the byte order of the trap handler, applied by hardware at the transition* — is
what those documents teach. §10's first open item is where the *motivation*
becomes relevant again, and it is recorded as unresolved rather than argued
away.

### 11.3 What checking changed

Three of the expected citations did not survive contact with the sources, and
the corrections matter to which reference supports which clause. A fourth
architecture was missing entirely and is dealt with in §11.3a, which is also
where the weakest clause is assessed:

1. **PowerPC `MSR[LE]` is address munging, not byte invariance**, so it must
   **not** be cited for the byte-invariance clause. *PowerPC Architecture*
   (First Edition, 1993) Appendix D.3.2 is explicit: "PowerPC systems do not do
   such swapping, but instead achieve the effect of Little-Endian byte ordering
   by modifying the low-order three bits of the effective address… Individual
   scalars actually appear in storage in Big-Endian byte order." Because it XORs
   the low **three** bits, it is *doubleword*-invariant rather than
   word-invariant — a third point on the axis of §2.1, not one of the two — and
   the equivalence holds **for aligned scalars** (App. D.4.2.1); misaligned
   little-endian accesses are a separate case the architecture handles by trap.
   *Cite Appendix D to the 1993 First Edition specifically: by Book I 2.01/2.02
   this material had moved into the main chapters, so "Appendix D" resolves only
   against the edition named here.* It is a correct citation
   for **per-context privileged control** and for **`ILE`**, and it is cited for
   exactly those and nothing else. (Byte-invariant PowerPC exists — the MPC8xx
   "true little-endian" mode, 1998, and Book E's per-page `E` attribute, 2002 —
   but neither is `MSR[LE]`, and the architecture mainline did not adopt byte
   invariance until Power ISA 2.03 in September 2006, which is **past the
   cutoff** and is therefore not cited.)
2. **MIPS `Status[RE]` is address munging too** — the R4000 pseudocode XORs the
   physical address, so with `RE = 1` a byte load from address 0 returns the
   byte at physical address 7. Same correction, same consequence: cited for
   per-context privileged control only.
3. **PA-RISC's `PSW[E]` is February 1994, not "early 1990s".** It was introduced
   in the **Third Edition** of the PA-RISC 1.1 manual and is absent from the
   First (November 1990) and Second (September 1992) editions, whose own preface
   says so. Still comfortably pre-2006, but a citation to a 1990 edition would
   have pointed at a document that does not contain the feature.

### 11.3a The fetch clause: where the art actually stands

This is the weakest citation in the document, and the first draft of this
section described the weakness wrongly — as "one source against silence". The
truth is more interesting and is set out as a split, because a reader deciding
how much weight the clause carries needs the shape of the evidence, not a
verdict about it.

| Architecture | Does the per-context byte-order bit reach **instruction fetch**? |
|---|---|
| **PA-RISC 1.1** (1994) | **Yes**, verbatim: "The E-bit also affects instruction fetch." |
| **PowerPC** (1993) | **Yes** — the instruction effective address is munged like any other (App. D.5, XOR of `0b100`) — but by address transformation, a different mechanism |
| **SPARC V9** (1994) | **No**, and emphatically: "Instruction accesses are always big-endian" (§5.2.1.2), restated in §3.2, §3.2.1.2, §6.3.1.2, §H.1.6 and §K.6 |
| **ARM BE-8** (2005) | **No**: DDI 0100I §A2.7.2 — "instruction fetches always assume a little endian byte order model" |
| **SH-4** (2001) | Silent (§3.2) |

So on *whether a per-context endian bit reaches fetch at all* the pre-2006 art
is **2–2**, not one-against-silence. Two architectures did it and two
deliberately did not, which is a live design question with precedent on both
sides rather than an unexplored one.

**For the clause this document actually needs — byte-invariant *and* covering
fetch — PA-RISC remains the sole source.** PowerPC reaches fetch by munging;
SPARC V9 and ARM are byte-invariant but stop at data. PA-RISC is the only one of
the five that is both. §12 keeps a trigger for that, and §10's screen should be
pointed here first.

**And the search that produced this was not exhausted, which is worth admitting
rather than burying.** SPARC V9 is named on [glossary §2](glossary.md)'s
acceptable-source list, is already cited in five places in this workspace, and
is the primary reference for `hypervisor/design-spec.md`'s own privilege model —
and the first draft of this section did not consult it. It turned out to
strengthen two rows and to settle the fetch question in a way that made the
original framing wrong. [glossary §2](glossary.md)'s instruction to "cite
multiple independent sources to demonstrate the idea was common knowledge" is
not a formality about volume; it is what stops a single source's idiosyncrasies
being mistaken for the state of the art.

**What that leaves as the honest position**, since a flagged weakness is only
useful if someone says whether it is acceptable: one solid pre-2006 source plus
a documented split, with the gap named and a reopening trigger attached,
satisfies [glossary §2](glossary.md) and §2.1's second rule. It does not
substitute for the screen in §10, and this section does not claim it does.

### 11.4 Considered and not cited

- **US 2005/0251650 A1, "Dynamic endian switching"** (Microsoft; filed
  **29 April 2004**, published 10 November 2005, granted as US 7,139,905 B2 on
  21 November 2006). Its priority date is **2004**, not 2005 — the 2005 is the
  publication year — so it clears the cutoff by more than the publication number
  suggests, and the 2004 filing puts its expiry in 2024. It is **not cited as
  prior art for this design**, because it does not teach it: what it discloses
  is an external endian-select circuit plus an instruction sequence that decodes
  meaningfully in both byte orders, used to change endianness **across a
  processor reset** — "When the processor comes out of reset, the processor
  re-samples its Endian Select input to determine the current endian mode."
  That is closer to SH-4's strap than to a per-context mode. It is listed here
  so that a later reader who finds it does not assume it was missed.
- **The SPARC V9 edition caveat.** The rows above cite `© 1994 SPARC
  International, ISBN 0-13-825001-4`, which is the copyright and ISBN carried by
  the manual. The two freely available full-text PDFs consulted are **later
  corrected reissues of that 1994 text** — revision `SAV09R1459912` (Rev. 1.45,
  1999) and `SA-V09-R147-Jul2003` (Rev. 1.47, July 2003) — not scans of the 1994
  printing, and their §5.2.1.2 wording differs slightly between revisions (the
  1.47 text is the one quoted). Every passage cited here is present and
  materially identical in both. The 1994 date is the copyright date of the work,
  which is what [glossary §2](glossary.md)'s acceptable-source list names, and
  the reissues are noted so that a reader comparing page numbers is not
  surprised.
- **Power ISA 2.03** (September 2006) and **ARMv7's removal of BE-32** (2007
  onward) are both **post-cutoff** and are cited nowhere in §11.1. They appear
  in §2.3 as evidence for an engineering argument, which is a different use and
  is labelled as such.

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
- **PA-RISC 1.1 turns out not to say what §11.3a reports.** For the combination
  this document needs — byte-invariant *and* reaching instruction fetch — that
  one document is the sole pre-2006 source; the other four architectures
  surveyed each supply one half and not the other. If a screen finds the 1994
  Third Edition's `E`-bit text does not reach instruction fetch, or that the
  edition history is other than reported, the fetch half loses its only support
  for that combination and [glossary §2](glossary.md)'s rule (a) — find a
  pre-2006 equivalent — has to be satisfied before RTL commits. Note what would
  *not* be lost: per-context privileged control and the two-bit trap pattern are
  three-sourced each and are unaffected.
- **A second bus master gains a byte-order mode of its own.** §2.2's "one image
  of memory" argument assumes the CPU is the only thing with a mode. A
  byte-swapping DMA descriptor field, say, would make that assumption false and
  the argument would need re-making rather than restating.
- **`SR` acquires the `LE` bit after all** (§6.3), in which case the masking
  requirement in that section becomes normative text somewhere rather than a
  condition attached to a rejected option.
