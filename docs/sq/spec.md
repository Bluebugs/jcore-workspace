# J-Core Store Queue Specification

**Status:** Draft
**Scope:** SH-4-compatible store queue: region layout, address formation, burst semantics, privilege, memory ordering. Hypervisor interaction §6–7.
**Audience:** RTL implementers, kernel developers, hypervisor authors
**Prerequisites:** [../mmu/hardware-spec.md](../mmu/hardware-spec.md), [../soc/p4-mmio-map.md](../soc/p4-mmio-map.md)

---

## 1. Scope

This document specifies the J-Core store queue (SQ): a write-combining bulk-store path that
turns eight sequential 32-bit stores plus a `PREF` instruction into a single 32-byte bus burst.
This is the SH-4 store-queue facility (Renesas hardware manual, 1998); J-Core did not previously
implement it, and [../soc/p4-mmio-map.md](../soc/p4-mmio-map.md) held the region reserved for it
pending this specification. §1–§5 define the baseline hardware feature, which stands on its own
and is what a non-virtualized J-Core implements; §6–§7 then specify what changes when the store
queue is used by a hypervisor guest.

**Implementation status: none of this exists.** `jcore-cpu` `origin/master` has no store queue, no
decode of the SQ region, and no SH-4 `PREF` — the only `PREF` in the instruction set is the SH-2A
hint form, implemented as a nop. Read every "is" below as "shall be". This matters beyond
book-keeping in one place: [../hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md)
carves `0xE0000000`–`0xE3FFFFFF` out of the guest P4 trap so that guest queue stores run
untrapped, and a carve-out over hardware that does not exist is a hole, not an optimisation. **The
carve-out must not be enabled before the queues are.** See
[../sh4-guest-model.md §3.3](../sh4-guest-model.md).

## 2. Region Layout

```
0xE0000000 - 0xE000001F   SQ0 data (32 bytes)
0xE0000020 - 0xE000003F   SQ1 data (32 bytes)
0xE0000000 - 0xE3FFFFFF   SQ aliasing window: VA[25:5] selects the target
                           32-byte burst address (see §3); VA[4:2] selects
                           the word within the queue; VA[5] selects SQ0/SQ1
0xE4000000 - 0xEFFFFFFF   reserved (not SQ-decoded)
```

The two 8-word queues, SQ0 and SQ1, are addressed at their base offsets
(`0xE0000000`, `0xE0000020`) for ordinary word stores. The full `0xE0000000`–`0xE3FFFFFF`
range is also an aliasing window: `VA[5]` selects SQ0 vs. SQ1, `VA[4:2]` selects the word
within the 8-word queue, and `VA[25:6]` participates in forming the eventual burst target
address (§3). All SQ accesses require `SR.MD = 1` (§5).

`0xE4000000`–`0xEFFFFFFF` is allocated to the SQ in [../soc/p4-mmio-map.md §2](../soc/p4-mmio-map.md)
but is decoded by nothing: no queue absorbs it and no slave claims it. For a hypervisor guest it
therefore traps like the rest of P4 — the guest-mode P4 carve-out of
[../hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md) is exactly
`0xE0000000`–`0xE3FFFFFF`, the SQ-decoded range and no more.

Reading the queue buffers back (via ordinary load) **returns zero** at `SR.MD = 1` with
`SR.HPRIV = 0`, and on any implementation without the hypervisor extension. It does not trap and
it changes nothing. The single, narrow exception is hyperprivileged software: §6.2 defines
queue-buffer readback at `SR.HPRIV = 1`. No other software may rely on reading queue contents —
it may only rely on **not** being shown someone else's.

> **SUPERSEDED BY §6.5 — 2026-09-09.** This paragraph previously read that the readback is
> "architecturally undefined" below `SR.HPRIV = 1`. That is one of the three
> "undefined = the previous owner's data" instances
> [../security/threat-model.md §7.8](../security/threat-model.md) enumerates, and it is the one
> this document owns. §6.5 rule **SQ-R4** replaces it with a defined zero and argues the choice.

## 3. QACR Layout and Address Formation

**Register layout** (MMIO, privileged). Both registers live in the MMU per-CPU block at
`0xFF000000`, at the offsets allocated in
[../soc/p4-mmio-map.md §3.2](../soc/p4-mmio-map.md): `QACR0` at offset `0x03C`, `QACR1` at offset
`0x040`.

```
QACR0 (base + 0x03C = 0xFF00003C)   QACR1 (base + 0x040 = 0xFF000040)
[31:5]  reserved, RAZ/WI
[4:2]   AREA         PA[28:26] contributed to the SQ0 (QACR0) / SQ1 (QACR1) burst target
[1:0]   reserved, RAZ/WI
```

The burst target address is formed as:

```
PA[28:26] = QACRn.AREA          (n = 0 for SQ0, 1 for SQ1)
PA[25:5]  = VA[25:5]            (VA is the address used in the triggering PREF operand)
PA[4:0]   = 0
```

This matches the SH-4 address-formation algorithm exactly. It does **not** follow that existing
SH-4 software runs unchanged, and an earlier revision of this paragraph said it did. The
*algorithm* is stock; the *register addresses* are not. Stock SH-4 places `QACR0` at
`0xFF000038` and `QACR1` at `0xFF00003C` — J-Core decodes `0xFF000038` as `ASIDR`, and its own
`QACR0` sits where SH-4 puts `QACR1`. A bare-metal stock SH-4 kernel that pokes the stock
addresses therefore programs the wrong register or none at all, silently, because undecoded P4
writes are discarded ([../soc/p4-mmio-map.md §3.2](../soc/p4-mmio-map.md)).

That costs nothing, because bare-metal stock SH-4 is not a target
([../sh4-guest-model.md §2](../sh4-guest-model.md)) and a *guest* never sees these offsets: its P4
access traps and the VMM presents the stock pair
([../sh4-guest-model.md §3.2](../sh4-guest-model.md)). What survives is a rule for whoever ports
software: SH-4 store-queue code needs its two register addresses changed and nothing else.

Note that PA here is a guest physical address when a guest is running — §6 covers what happens
next, including §6.4's normative rule that the burst's byte order follows the guest's byte-order
mode rather than the host's.

## 4. Burst Semantics

`PREF @Rn`, where `Rn` holds an address in `0xE0000000`–`0xE3FFFFFF`, drains the selected queue
(SQ0 or SQ1, chosen by `Rn[5]`) as a single 32-byte burst to the address formed per §3. The burst
is all-or-nothing: all 32 bytes of the queue are written to the bus in one transaction. Bytes
within the queue that were never written since that queue's last clear are **zero** — hardware
does not track per-byte validity within a queue, so a burst of a partly-filled queue publishes
zeros where software wrote nothing, and software filling a queue for a burst must still write all
8 words. After the burst completes, the queue's internal valid/dirty state clears **and its 32
buffer bytes are zeroed** (§6.3, and §6.5 rule **SQ-R2** for why the zeroing is here rather than
left to software).

> **SUPERSEDED BY §6.5 — 2026-09-09.** The sentence above previously read that such bytes "have
> **undefined** content". A guest that writes one word and bursts would then publish 28 bytes of
> whoever owned the queue before it, to an address of its own choosing
> ([../security/threat-model.md §7.8](../security/threat-model.md)).

`PREF` issued with an address outside the SQ aliasing window retains its ordinary
cache-prefetch meaning and has no interaction with the store queues.

## 5. Privilege and Ordering

SQ access — both queue-data stores and `PREF`-triggered bursts — requires `SR.MD = 1`. J-Core
keeps `MMUCR[6]` (SH-4's `SQMD`, which on SH-4 selected whether user-mode software could access
the store queues) **reserved and unimplemented** — see
[../mmu/hardware-spec.md §2.3](../mmu/hardware-spec.md). There is consequently no user-mode SQ
access path on J-Core, consistent with the rest of P4 being privileged-only.

**Ordering.** Stores into a queue are not ordered with respect to ordinary (non-SQ) stores until
the burst is issued. The burst itself is a single, atomically-ordered bus transaction relative to
other bus traffic. Software that needs a queue burst ordered relative to other memory operations
must issue the burst (via `PREF`) and rely on the resulting single transaction; there is no
partial-drain or fencing primitive within a queue.

## 6. Hypervisor Interaction

This section specifies what changes when a guest (`SR.HPRIV = 0`) uses the store queues under
the J-Core hypervisor extension ([../hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md)).
Nothing in §1–§5 changes for bare-metal (non-virtualized, or `SR.HPRIV = 1`) operation.

### 6.1 The burst is translated

**Decision:** when a guest is running, the `QACR`-formed address of §3 is a *guest* physical
address. It is translated through the TLB like any other guest access and then aperture-tested
per [../hypervisor/hardware-spec.md §4.5](../hypervisor/hardware-spec.md).

Consequences, stated as rules:

1. A burst whose target translates outside the aperture goes to memory as a single 32-byte
   transaction with **no hypervisor involvement**.
2. A burst whose target lands in the aperture raises exactly one trap, with `HMCR.SQ = 1`.
3. Because the target is translated, the guest's `QACR` values are loaded into hardware verbatim
   — the hypervisor performs no address arithmetic on them.

**Rationale:** the alternative — trapping every burst — costs roughly 30 cycles per 32 bytes.
For the motivating workload (a title streaming vertex data to a tile accelerator, megabytes per
frame) that would be the single dominant cost in the system. *(This workload was originally written as a Dreamcast
title running as a guest, and that is again what it is. An intervening revision of this note read
that "a stock Dreamcast image's instruction stream is little-endian and the fetch path stays
big-endian, so such an image is a software-emulation workload rather than a KVM guest" — true under
Decision B2-1, and false under Decision BE-1
([../bi-endian-spec.md §1](../bi-endian-spec.md)), which makes the fetch path bi-endian. The
rationale never depended on it either way: what it rests on is the **shape** of the workload, bulk
streaming to a device from a guest, and that was unchanged by the exclusion and is unchanged by its
removal. Recorded because this is the second time this parenthetical has been rewritten for a reason
that does not touch its conclusion, which is a sign the conclusion was never resting on it.)* Making the common
case a plain memory write lets a hypervisor map the guest's submission window to an ordinary
ring buffer in host memory and drain it asynchronously.

### 6.2 Hypervisor access to the queue buffers

**Decision:** at `SR.HPRIV = 1`, reads of `0xE0000000`–`0xE000003F` return the queue buffer
contents. This is a **J-Core extension**: §2 leaves such reads undefined at `HPRIV = 0`, and
real SH-4 left these reads undefined entirely, at any privilege level.

**Rationale:** this is the cheapest possible state exposure — it needs no indexed register
window and no new encodings, because the hypervisor is already exempt from the guest trap rules
of [../hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md).

Hypervisor **writes** to the same range also address the buffers directly and do **not** update
`HSQCR`. Restoring valid/dirty state is a separate, explicit `LDC` to `HSQCR`, and that `LDC` is
why §7's restore writes `HSQCR` last: it is the single point at which restored state becomes
architecturally live.

**One state is deliberately no longer reproducible, and it is worth saying which.** This paragraph
previously offered, as evidence of the two paths' independence, that a restore could reproduce "a
queue whose bytes are fully written but whose `VALID`/`DIRTY` bits are clear". Under §6.5 rule
**SQ-R3** it cannot: the `HSQCR` write that leaves `VALIDn` clear also zeroes queue *n*'s bytes.
That state — bytes present, with nothing marking them live — **is** the residue state, and it was
being described as a capability. The independence of the two paths survives unchanged; what is
withdrawn is one example of it that [../security/threat-model.md §8](../security/threat-model.md)'s
**L6** bans outright.

**Prior art, pre-2006.** The store queue itself, including the architectural decision to leave
buffer readback undefined, is SH-4 (Renesas SH-4 CPU Core Architecture manual, 1998); this section
narrows that "undefined" to "defined at the highest privilege level only", which is the
System/370 pattern: IBM System/370 (1970) exposed otherwise-inaccessible machine state — storage
keys — to privileged software through `ISK`/`SSK` precisely so that a supervisor could read and
write state the problem program could neither see nor rely on. Extending readback to the
hyperprivileged level and no further is the same move at one privilege level higher: the state is
opaque to every level that could depend on it, and legible to the one level that must checkpoint
it.

### 6.3 HSQCR semantics

`HSQCR`'s bit layout is defined in
[../hypervisor/hardware-spec.md §2.7](../hypervisor/hardware-spec.md): `[3] DIRTY1`,
`[2] DIRTY0`, `[1] VALID1`, `[0] VALID0`. The transitions are SQ behaviour and are specified
here:

```
guest store into queue n   : VALIDn <- 1, DIRTYn <- 1
successful burst of queue n: VALIDn <- 0, DIRTYn <- 0, buffer n <- 0   (SQ-R2)
trapped burst (HMCR.SQ=1)  : unchanged - the hypervisor decides; the buffer
                             is NOT cleared, because it is the evidence
LDC to HSQCR at HPRIV=1    : set directly; buffer n <- 0 for every n whose
                             written VALIDn is 0                        (SQ-R3)
reset                      : all zero, buffers included                 (SQ-R1)
```

The three annotated rows are §6.5's residue rules seen from this register; §6.5 is where they are
stated normatively and argued.

The "trapped burst" row agrees with
[../hypervisor/hardware-spec.md §4.5](../hypervisor/hardware-spec.md) rule 4: for `HMCR.SQ = 1`,
hardware performs no writeback and does not clear `HSQCR.VALID`/`DIRTY` for the affected queue on
trap entry. The hypervisor alone decides, after inspecting the buffer via §6.2, whether the burst
is considered consumed and clears `HSQCR` accordingly before resuming the guest.

### 6.4 Queue-data stores follow the guest's byte order; the burst has none (normative)

> **SUPERSEDED BY this section's own text — 2026-09-08.** It previously read
> "**Decision:** queue-data stores and the `QACRn`-formed burst are **data**
> accesses, so they follow the guest's byte-order mode — the byte lanes a guest
> store lands in, and the byte order of the 32-byte burst, follow the guest's
> setting and not the host's." The half about the burst is **withdrawn**: it was
> written against Decision B2-1, whose scheme was word-invariant, and it does not
> survive the move to byte invariance. The half about the stores stands and is
> restated below.

**Decision:** queue-data stores are **data** accesses, so they follow the
guest's byte-order mode: the **byte order in which a guest's stored value is
laid down** in the queue buffer follows the guest's setting and not the host's.
**The 32-byte burst has no byte order of its own** and needs no rule.

*Stated that way deliberately: it is **not** about lanes.* Under byte invariance
the lanes a store occupies are a function of its address and size and do not
move with the mode at all — [../bi-endian-spec.md §4.3](../bi-endian-spec.md)
says there is no lane remapping in the design. The retained half of this
requirement previously read "the byte lanes a guest store lands in", which is
the superseded word-invariant vocabulary describing the right conclusion; the
thing that actually varies is the order of the bytes within the value, permuted
at the register boundary before it reaches any lane.

Per [../bi-endian-spec.md §1](../bi-endian-spec.md), Decision BE-1, J-Core is to
gain a byte-invariant per-context byte-order mode covering the data path and
instruction fetch, owned by the hypervisor and neither guest-writable nor
guest-readable. This section is in §6 and not in §3 deliberately: §1 declares
§1–§5 to be the non-virtualized baseline, and this requirement is per-guest and
hypervisor-owned, so it belongs with the rest of the hypervisor interaction.

**Why the burst drops out, since this is a requirement being removed and a
removed requirement deserves more argument than an added one.** Under byte
invariance the swap sits at the register boundary
([../bi-endian-spec.md §2.2](../bi-endian-spec.md)), so what a guest's stores
leave in the queue buffer is *raw bytes* — already in the order they will occupy
in memory. §4's burst writes all 32 of those bytes to the bus in one
transaction. A byte copy of bytes that are already correct has nothing to
reorder, in either mode. The buffer is not a register file and the burst is not
a load or a store; it is the one part of this path with no byte-order property
at all.

Had the scheme been word-invariant, the withdrawn half would have been
necessary — under address adjustment the buffer's byte at offset 0 is not
necessarily the memory byte at offset 0, and the burst would have had to know
which mode laid the bytes down. That is one concrete instance of the cost §2.2
of the bi-endian spec is about, and it is recorded here because it is the only
place in this workspace where the two schemes produce a visibly different
requirement.

**Rationale, and why it is not optional politeness.** §4.4.3 of
[../hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md) carves the SQ
region out of the guest P4 trap precisely so these stores run **untrapped**. A
little-endian guest whose stores were laid down in the host's byte order would
therefore be silently wrong on the one guest path nothing inspects — exactly the outcome
[../sh4-guest-model.md §5](../sh4-guest-model.md), Decision B2-5, outlaws.
Neither the mode nor the queues exist yet; both must arrive with this property
already in them, because there is no later point at which a guest would notice
it was missing.

**Interaction with §7.** The mode's `LE` bit — the one that applies to a guest,
since a guest runs at `SR.HPRIV = 0` and the effective order is `LE` there
([../bi-endian-spec.md §6.1](../bi-endian-spec.md)) — is per-vCPU context like
everything else in §7, and like `HSQCR` it must be restored before the guest resumes. *This
paragraph previously gave the failure as "a vCPU resumed under the wrong byte
order bursts a buffer whose bytes were laid down under the other one", which is
the withdrawn burst claim in another form and is false under byte invariance:
the burst is unaffected.* The real failure is one step earlier and no less
serious — a vCPU resumed under the wrong `LE` lays down **subsequent** stores
into that buffer in the wrong byte order, mixing them with the bytes it wrote
before the exit, and then bursts the mixture. Nothing traps, because the
carve-out exists to keep this path untrapped. See
[../hypervisor/hardware-spec.md §2.9](../hypervisor/hardware-spec.md), whose
per-vCPU register list records the same gap and distinguishes `LE` from `HLE`.

**Hyperprivileged buffer readback (§6.2) needs no byte-order rule.** The
hypervisor runs at `HLE`, so its loads from a guest's queue buffer assemble in
the host's byte order — which is what saving and restoring raw bytes requires,
and what §7's save sequence already assumes.

### 6.5 Buffer residue: a queue holds only its current owner's bytes (normative)

**Wave-3 task C1a**, from [../j4-remediation-plan.md §C1](../j4-remediation-plan.md), argued against
[../security/threat-model.md §8](../security/threat-model.md)'s bar items **L6** and **L1**.

*It is here and not in `../decisions/` deliberately.*
[../decisions/README.md](../decisions/README.md)'s rule turns on whether a spec owns the thing
decided, and one does: this document owns the store queue, and what is decided here is store-queue
behaviour. The one part that is **not** store-queue behaviour — that a gang switch must scrub — is
correspondingly not here either; it is an item in
[../hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md), the spec that owns gang
switching.

#### The exposure

The adversary of [../security/threat-model.md §1](../security/threat-model.md) is a *guest kernel*
that owns a core for a whole quantum and is handed a core another tenant used. Against that
adversary the queues, as §1–§5 and §6.1–§6.4 previously left them, are three primitives, and not
one of them needs speculation, timing, or noise:

1. **Publish.** §4's burst is all-or-nothing: `PREF` writes all 32 bytes of the queue to the bus.
   A guest that writes one word and bursts therefore publishes 28 bytes it did not write, to a
   physical address it chose through `QACRn.AREA` and `VA[25:5]` (§3), and then reads them back
   out of its own memory. Committed instructions throughout.
2. **Read.** §2 previously left a load of the queue region "architecturally undefined" below
   `SR.HPRIV = 1`. An implementer may satisfy "undefined" with the buffer contents, at which point
   the exposure is a plain load.
3. **Read the host.** §6.2 lets hyperprivileged software *write* the buffers. The bytes a queue
   holds at an ownership change are therefore not necessarily another guest's — they can be the
   hypervisor's, which is the TCB ([../security/threat-model.md §2](../security/threat-model.md)).

All three run in the corruption direction as well as the disclosure one: a burst carrying stale
bytes writes them into the *incoming* guest's own memory, silently, on a path nothing inspects.

**This section is about the *temporal* case only** — one thread context, two owners over time. The
concurrent case, two vCPUs of one core writing one buffer at the same instant, is closed by §7.1's
per-context replication and is not restated here.

#### The invariant

> **SQ-INV.** At every instant, every byte of a queue buffer is either a byte the queue's current
> owner stored since that queue's last clear, or **zero**.

Everything below exists to make SQ-INV true and testable. It is stated as an invariant rather than
as a sequence of steps because L6's failure mode is precisely a step that silently does not run.

#### The rules (normative)

**SQ-R1 — Reset.** Out of reset both queue buffers are zero, and so are `QACR0`, `QACR1` and
`HSQCR`. [../hypervisor/hardware-spec.md §2.7](../hypervisor/hardware-spec.md) already gives
`HSQCR`'s reset value; this extends the requirement to the buffers and the area registers, which
had none.

**SQ-R2 — Clear on burst completion.** When a burst is issued to the bus and completes, the source
queue's 32 buffer bytes become zero, in the same step as §6.3's `VALIDn`/`DIRTYn` clear.
**A trapped burst clears nothing.** Under `HMCR.SQ = 1` the buffer is the evidence the hypervisor
is required to inspect (§6.2, §6.3, and
[../hypervisor/hardware-spec.md §4.5](../hypervisor/hardware-spec.md) rule 4), so R2 is conditioned
on the burst reaching the bus and not on `PREF` executing. Getting that condition backwards would
break complete-on-resume while looking like a stronger scrub.

R2 and R3 compose correctly across that trap, which is worth stating because the composition is
what a reviewer will check. The hypervisor resolving a trapped burst either decides it was
consumed, and clears `VALIDn` — at which point R3 zeroes the buffer, correctly, because the data
is gone — or decides it was not, and leaves `VALIDn` set, at which point R3 does nothing and the
bytes survive for the guest to burst again.

**SQ-R3 — Scrub on ownership change.** A hyperprivileged write to `HSQCR` clears queue *n*'s 32
buffer bytes to zero, for every *n* whose **written** `VALIDn` bit is 0. Unconditional, idempotent,
no transition detection, no new register, no new encoding.

Three consequences, and the third is the one this task exists for.

1. §7's restore writes `HSQCR` **last** and unconditionally, so every queue it does not restore is
   scrubbed at that write. **§7's sequence needs no change**: a queue whose saved `VALIDn` was 1
   had its bytes written by step 2 and is not scrubbed; a queue whose saved `VALIDn` was 0 had
   nothing saved and is scrubbed.
2. The scrub is a hardware effect of a register write the switch already performs. It cannot be
   omitted independently of omitting the restore, which is the difference between a control and an
   item on a checklist.
3. **A fresh vCPU with no saved image is covered by construction.** Its `HSQCR` is the reset value
   0 ([../hypervisor/hardware-spec.md §2.7](../hypervisor/hardware-spec.md)), so its restore
   scrubs both queues. This is the branch
   [../security/threat-model.md §7.8](../security/threat-model.md) identifies in the lazy-FPU
   restore and that **L3** requires as its own test case — a save/restore between two *established*
   owners passes without ever reaching it. Here it is not a second code path that could be
   forgotten; it is the same write with a different operand.

**R3 is per thread context, and on an FGMT core that is the whole of its meaning.** `HSQCR` is
per-context ([../hypervisor/hardware-spec.md §2.9](../hypervisor/hardware-spec.md)) and so are the
buffers (§7.1), so a write executed *in* context *c* scrubs *c*'s queues and no others.
[../hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md) item 1 quiesces every
context of the core with its own trap into HS mode, which is what makes "every context gets the
write" achievable at all; a scrub that ran once per core would leave three of four queues loaded on
a J32-LT.

**R1–R2 alone are sufficient on a machine with no hypervisor**, which is worth saying because
§1–§5 are the non-virtualized baseline and R3's trigger does not exist there. On such a machine
`SR.MD = 1` is the only privilege that can reach a queue (§5), so the queues have exactly one
owner for the machine's lifetime and the only ownership change is reset. R1 covers reset, R2 keeps
the steady state clean, and R4 answers the readback that §2 previously left undefined at every
privilege level. Nothing in R3 or R6 is required of an implementation without the hypervisor
extension, and nothing in R1, R2 or R4 is optional for one.

**SQ-R4 — Guest reads are defined.** At `SR.MD = 1`, `SR.HPRIV = 0`, a load from
`0xE0000000`–`0xE3FFFFFF` returns **zero**. It does not trap, does not read the buffer, and has no
effect on `HSQCR`. At `SR.MD = 0` an SQ-region access is a privilege violation and not a zero:
§5 enumerates queue-data stores and `PREF`-triggered bursts, and **loads are added to that
enumeration here**, because R4 makes a load a defined operation and a defined operation needs its
privilege stated. At `SR.HPRIV = 1`, §6.2's readback applies and returns the buffer word selected by
the same `VA[5]` / `VA[4:2]` decode a queue-data store uses — so §2's aliasing window aliases
identically for reads and for stores, and §6.2's base addresses are the canonical spelling of that
decode rather than a second comparator. This closes the last hole in
[../hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md), whose carve-out is for
"the *data* path" and which specifies what an untrapped guest **store** into the region does
without ever saying what an untrapped guest **load** returns.

**SQ-R5 — Nothing here is "undefined".** §4's "bytes … have undefined content" is withdrawn: bytes
not written since the queue's last clear (R1, R2 or R3) **are zero**, and burst as zero. Software
filling a queue should still write all eight words, because zeros are not its payload — but that
is now a correctness obligation about its own data, and no longer a security one.

**SQ-R6 — The hypervisor does not stage its own data in a queue.** Hyperprivileged writes to
`0xE0000000`–`0xE000003F` are permitted only as §7's restore of the incoming context's saved image.
R3 keys the scrub on the *incoming* context's `HSQCR`, and no mechanism can distinguish host bytes
from a restored image, so a queue the hypervisor filled for its own purposes and left marked
`VALID` would be burst by the guest. This is a discipline on the TCB rather than a hardware
guarantee, and it is written down because it is otherwise invisible.

#### What discharges the bar, and what does not

**L6** demands "a residue test per site … written as *tenant A stores a recognisable pattern;
tenant B reads and must not see it*, and each demonstrated **red before the fix**". For this site
that is three tests, and the third is the one that gets skipped.

| # | Test | What it recovers if the rule is absent |
|---|---|---|
| 1 | Tenant A fills SQ0 with a recognisable pattern and is gang-switched out **without** bursting. Tenant B stores one word at the queue base, issues `PREF`, and reads the burst target. | A's remaining 28 bytes — R2 and R3 both absent |
| 2 | Tenant B loads the SQ region directly at `SR.MD = 1`, `SR.HPRIV = 0`. | A's bytes — R4 absent, "undefined" realised as the buffer |
| 3 | **Tenant B is a fresh vCPU with no saved image**, so its restore writes no buffer bytes at all; B then runs test 1. | A's bytes, *with tests 1 and 2 green*, on any implementation whose scrub is conditioned on there being an image to restore |

Test 3 is the store-queue form of the no-saved-image branch, and R3 has the shape it has so that
tests 1 and 3 exercise the same hardware rather than two paths of which one is exercised.

**L1**'s added clause is discharged in another document, deliberately.
[../hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)'s gang-switch list now
carries the scrub as a numbered item. A scrub specified here and absent from *that list* would
leave L1 unmet while looking finished — which is the failure
[../security/threat-model.md §8](../security/threat-model.md) predicts for this task by name.

#### Minimizing the loss ([../j4-remediation-plan.md §E.10](../j4-remediation-plan.md), gated by §D3)

The guarantee to be bought is SQ-INV. Four options were priced: two for how the buffer is kept clean, one for how a guest read is answered, and one for where the scrub runs.

**Chosen: clear the storage.** R1–R3 are a broadside zeroing of storage §7.1 already requires to
exist per thread context. It adds **no architectural state**: §7.2's image stays as it is,
`HSQCR`'s layout is untouched, and §7's sequence is unchanged. Structurally the clear covers
64 bytes × 8 = **512 bits per thread context** — a structural count, not a measurement — and the
lever is the one §E.10 names, "per-register zero bit = 1-cycle zeroing".

**Rejected as the specified mechanism, and recorded: an 8-bit word-valid mask per queue**, with the
burst sourcing zero for any word whose bit is clear. It buys the same invariant with 16 bits per
context instead of a clear enable across 512, and it is the better answer if the buffers are block
RAM, where a broadside clear is unavailable and a word-serial clear could not overlap a burst
reading the same single-ported array. It is rejected because the mask bits are **per-vCPU
architectural state**: they would have to join
[../hypervisor/hardware-spec.md §2.9](../hypervisor/hardware-spec.md)'s list, §7's save and
restore, and §7.2's image, and `HSQCR`'s layout would have to be reopened to carry them. Sixteen
bits is cheap in gates and expensive in specification surface, and specification surface is where
L6 says this class of defect comes back. **It remains a permitted implementation of SQ-INV** — the
invariant does not care which — on the explicit condition that an implementation choosing it
carries the mask as saved context. An implementation that masks without saving the mask
reintroduces the residue across exactly the switch the mask was added to survive.

**Rejected: trap the guest read, instead of R4's zero.** A trap needs an `EXPEVT` value, an `HEDR`
bit, a vector and a hypervisor handler, all to deliver an exception on the one guest path
[../hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md) carves out of the P4 trap
in order to keep it untrapped. It also makes the defined behaviour depend on that handler being
correct, and this item exists because a mitigation that depends on software running is the one that
silently does not. SH-4 left the read undefined, so no conforming software reads the queues and a
defined zero can regress nothing.

**Rejected: scrub in hypervisor software** — sixteen word stores per context in the switch path, no
RTL change at all. Rejected on L6's own argument, that a scrub which silently does not happen
produces no fault, and on a second ground the bar does not state: §1–§5 are the **non-virtualized**
baseline, where there is no hyperprivileged mode and no hypervisor to run the loop, and §2's
readback was undefined there too. A software-only scrub leaves the bare-metal machine exactly as it
was.

**What this costs, and what is not known.**

- **Per gang switch: no added instruction.** R3 is a side effect of the `HSQCR` write §7's restore
  already performs.
- **Per burst:** R2's clear. Whether it adds a cycle to the burst, and whether the clear enable
  moves the core's `Fmax`, is `unknown at this stage — needs measurement`.
- **Area:** no added architectural state; a clear enable on storage §7.1 already requires. The gate
  cost is `unknown at this stage — needs measurement`.
- **§E.10's conclusion is about a class and is not a number for this mechanism.** It prices "eager
  state switch + scrub" as sub-1% on this core, and that is why this design has the *shape* it has
  — cross-tenant only, no per-switch copying, a data-path clear rather than a software loop. It is
  `LITERATURE` on [../security/threat-model.md §9](../security/threat-model.md)'s provenance scale,
  it is not evidence about the store queue, and no percentage is stated here for one.

**The experiment that would settle it.** Human-gated: this design prepares it and a person runs the
board ([../j4-execution-plan.md §5](../j4-execution-plan.md)).

1. **Synthesis A/B.** Build the store-queue block with and without R2/R3's clear; `yosys` +
   `nextpnr-ecp5` targeting the ULX3S 85F. Report ΔLUT4, ΔFF, ΔEBR and `Fmax` against the CI floor
   of [../platform-baseline.md §3](../platform-baseline.md). *Kill criterion:* if the clear puts
   the build under the floor, take the rejected mask variant and pay its context state.
2. **Streaming throughput.** §6.1's motivating workload shape — a loop of *N* × (eight word stores
   + `PREF`) into a mapped ring — in bytes per second, with the clear present and absent.
   *Kill criterion:* any measurable reduction in burst rate means R2 must be realised as the
   zero-mux rather than as a storage clear. SQ-INV is indifferent between them; this measurement is
   what decides.
3. **Switch cost.** Gang-switch latency across a two-guest gang schedule, with and without the
   scrub, from the PMU cycle counter. Expected to be unmeasurable, because R3 adds no instruction;
   the experiment exists to confirm that rather than to assume it.

#### Implementation status: specified, not built

§1 already says the store queue does not exist. **This section is a rule about hardware that does
not exist either, and nothing in it is met because it has been written.** Re-checked 2026-09-09,
case-insensitively throughout, because VHDL is case-insensitive and `git grep` is not — a
case-sensitive search of this tree has produced a confident wrong finding before
([../security/threat-model.md §11](../security/threat-model.md), `cache_index_bits`):

- `jcore-cpu@origin/master` (`e8a5a4e1`): no `*.vhd`/`*.vhm` file matches
  `store_queue|storequeue|sq_`. `QACR` appears in `core/datapath.vhd` and `core/datapath.vhm` in
  a **comment only** — the P4 offsets `0x3C`/`0x40` are noted as the proposed `QACR0`/`QACR1` and
  are decoded by nothing. `HSQCR` appears nowhere. The only `PREF` in the instruction set is
  `decode/gen-go/spec/sh2a/misc.toml`'s SH-2A hint form, whose own comment says it is a NOP.
- `jcore-soc@origin/master` (`7869a729`): no `*.vhd`/`*.vhm` file decodes `0xE0000000`. The two
  files matching `sq_` are the DDR2 controller's `sq_en`/`sq_vld` sequencer signals, which are
  not this.

So the queues are absent on both sides of the CPU/SoC boundary, and so is every register this
section touches.

Three consequences, so that nothing here reads as a closure:

- **L6's store-queue site moves from a specified "undefined" to a specified scrub, and no
  further.** L6's evidence bar is the three residue tests above, each demonstrated red before the
  fix, and there is no hardware to run them red on.
- **R1–R6 must land with §1–§5's baseline queues, not after them.** What unblocks the
  implementation half of C1a is the store queue itself — the region decode, the two buffers,
  `QACR0`/`QACR1` and SH-4 `PREF` — and the reason is §6.4's reason in another subsystem: the
  [../hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md) carve-out is enabled when
  the queues arrive, and after that there is no point at which a guest would notice the scrub was
  missing.
- **Two of L6's three "undefined"s are not this document's**, and are named here so the next task
  does not re-derive the split: the no-saved-image branch of the lazy FPU restore
  ([../fpu/spec.md §7.3](../fpu/spec.md), Wave-3 **C1b**) and `movca.l`'s partially-defined L2 line
  ([../cache/l2-spec.md §17.5](../cache/l2-spec.md), Wave-3 **C2e**). L6 also asks for a grep-level
  CI check that no tenant-visible "undefined" is reintroduced; that check does not exist in
  `scripts/check-doc-facts.py` today and is owed by **B0c**, not by this task.

  *Updated 2026-09-09:* C1b took the first of those two —
  [../fpu/spec.md §7.7](../fpu/spec.md) and [../simd/spec.md §2.6.1](../simd/spec.md).
  That leaves **1** open `undefined` site — `movca.l`'s — on [../security/threat-model.md §8](../security/threat-model.md)'s count. The B0c check is still
  absent, and C1b did not write it either, for C1a's reason: a check owned by whoever happened to
  need it is a check nobody maintains.

**Prior art, pre-2006.** Reading storage whose owner has changed as a defined constant rather than
as whatever it last held is the object-reuse requirement: TCSEC (DoD 5200.28-STD, 1985) makes it a
named criterion from class C2 upward, requiring that storage assigned to a subject contain no
information produced by a prior subject. Clearing state at a change of owner rather than leaving it
legible is the same System/370 (1970) storage-key discipline §6.2 and §7 already cite for the other
half of this mechanism. Neither the rule nor the mechanism is new; what is new here is only which
structure it is applied to.

## 7. Context Switch

A vCPU's store-queue state — 64 bytes of buffer, two `QACR` values, and `HSQCR` — is per-vCPU
context that a hypervisor's scheduler must save on VM exit and restore before resuming that vCPU,
exactly like general-purpose registers. §7.2 lays out the saved image field by field. The sequences below are lazy in the ordinary sense: they
run only when the scheduler actually switches away from and back to a given vCPU, not on every
trap.

**Save sequence:**

1. Read `HSQCR`.
2. If `VALID0` is set, read the 32 bytes at `0xE0000000` (SQ0's buffer).
3. If `VALID1` is set, read the 32 bytes at `0xE0000020` (SQ1's buffer).
4. Read `QACR0` and `QACR1`.

**Restore sequence:**

1. Write `QACR0` and `QACR1`.
2. Write the saved buffer bytes back to `0xE0000000` and/or `0xE0000020`.
3. Write `HSQCR` **last**.

`HSQCR` must be written last because, per §6.2, writes to the buffer range do not set
`VALID`/`DIRTY` — only the explicit `LDC` to `HSQCR` does. That is precisely what makes steps 1
and 2 order-independent with respect to each other: neither has a side effect on `HSQCR`, so the
final `LDC` to `HSQCR` is the single point at which the restored state becomes architecturally
visible as valid/dirty, and it can be issued only once all other state is already in place.

**Invariant.** A guest preempted between its eighth queue store and its `PREF` observes nothing:
all 64 bytes of buffer, both `QACR` values, and `HSQCR` are restored before the guest resumes, so
the queue is bit-for-bit as the guest left it. **The converse invariant is §6.5's**, and the two
are the same `HSQCR` write seen from either side: a vCPU with nothing saved for a queue resumes
with that queue zeroed, never with whatever the previous owner left in it. No flush is forced across the switch — the point
of the lazy model is that preemption never changes what the guest eventually bursts; the burst
happens, if at all, only when the guest's own `PREF` next executes.

### 7.1 Multi-threaded implementations: the queues are per thread context

The save/restore contract above assumes a core that runs **one vCPU at a time**. An FGMT
implementation does not: [../ooo/j32ooo-spec.md §13](../ooo/j32ooo-spec.md) runs two thread contexts
concurrently and [../ooo/j32lt-spec.md §9](../ooo/j32lt-spec.md) runs four. Two or four vCPUs are
resident *simultaneously*, so there is no exit at which the save sequence could run, and no ordering
of it that would help.

**Normative:** on an implementation with `N` thread contexts, the store queue is replicated per
context — `N` × (two 32-byte buffers + `QACR0` + `QACR1` + `HSQCR`). A store to `0xE0000000` is
absorbed into the issuing context's SQ0, and a `PREF` bursts that context's buffer.

Without replication the failure is immediate and has nothing to do with speculation: two vCPUs
writing the same 32-byte buffer interleave their bytes, and whichever issues the `PREF` first bursts
a mixture of both to *its* physical target. That is a cross-vCPU data disclosure and corruption on
the hot path [../hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md)'s P4 carve-out
exists to accelerate — eight untrapped stores plus a `PREF`, by design, for exactly the guest that
must not see another's data.

Cost: the 72-byte store-queue image of §7.2 per additional context, plus `HSQCR`, which is
counted with the per-context hypervisor register block rather than with the queues — the split
[../ooo/j32lt-spec.md §16.12](../ooo/j32lt-spec.md)'s per-thread table uses, and the reason this
line reads 72 and not 76 while the replication list above names `HSQCR`. See
[../hypervisor/hardware-spec.md §2.9](../hypervisor/hardware-spec.md), which applies the same rule
to the rest of the per-vCPU register set, and
[../ooo/j32lt-spec.md §16.12](../ooo/j32lt-spec.md) for the four-context total.

§7's sequences remain correct and remain required — they are what a hypervisor runs when it
switches a *context* between vCPUs. Replication removes the case where two vCPUs share a queue at
the same instant; it does not remove the case where one context hosts two vCPUs over time.

**Cost.** The state is small and fixed: 64 bytes of buffer plus three registers (`QACR0`,
`QACR1`, `HSQCR`), independent of how much of either queue is actually populated. A hypervisor
may skip steps 2–3 of the save sequence for a queue whose `VALID` bit is clear, since there is
nothing live to preserve, but the worst case is bounded and small relative to the general-purpose
register file it is saved alongside.

**Prior art, pre-2006.** Saving and restoring *pending, not-yet-committed* write state across a
context switch, rather than forcing it to complete at the switch point, is IBM System/370 (1970):
the machine-state save/restore discipline around the PSW and the storage keys preserves a
program's in-progress machine state across a supervisor intervention instead of draining it, and
`ISK`/`SSK` are what make the otherwise-invisible portion of that state saveable. The specific
state being preserved here — two 32-byte write-combining queues and their area registers — is
SH-4's own store queue (Renesas SH-4 CPU Core Architecture manual, 1998); SH-4 defined the queues
and the `QACR` registers, and this section adds only the rule that a hypervisor treats them as
per-vCPU context. The deliberate choice *not* to flush on switch also follows the same 1970
lineage: a supervisor intervention is required to be transparent to the interrupted program, and
forcing a burst the guest did not ask for would not be.

### 7.2 The per-context save image (72-byte store-queue image)

The state §7's sequences move, laid out so that the sum is checked rather than asserted. Offsets
are into the hypervisor's own save area and have nothing to do with the SQ region's addresses.

| Offset | Bytes | Content                          |
| ------ | ----- | -------------------------------- |
| 0x00   | 32    | SQ0 buffer (8 × 4 B)             |
| 0x20   | 32    | SQ1 buffer (8 × 4 B)             |
| 0x40   | 4     | `QACR0`                          |
| 0x44   | 4     | `QACR1`                          |
| 0x48   | —     | end (72 bytes)                   |

**`HSQCR` is deliberately not in this image.** It is a hyperprivileged register and is counted with
the rest of that set in [../ooo/j32lt-spec.md §16.12](../ooo/j32lt-spec.md)'s per-thread table, not
with the queues; §7's restore reaches it by the separate `LDC` of step 3, which §6.2 explains and
§6.5 rule **SQ-R3** now gives a second job. Counting it here would double-count it against that
table and turn 72 into 76.

**A queue whose `VALIDn` is clear contributes zeros, not stale bytes.** §7's save may skip reading
such a queue — there is nothing live in it — and §6.5 rule **SQ-R3** guarantees the restore leaves
it zeroed rather than untouched. The image is therefore complete whether or not the save ran the
optional steps, which is what makes the skip safe.
