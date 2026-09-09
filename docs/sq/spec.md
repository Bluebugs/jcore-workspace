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

Reading the queue buffers back (via ordinary load) is architecturally undefined at `SR.MD = 1`
with `SR.HPRIV = 0`, and on any implementation without the hypervisor extension. The single,
narrow exception is hyperprivileged software: §6.2 defines queue-buffer readback at
`SR.HPRIV = 1`. No other software may rely on reading queue contents.

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
within the queue that were never written since the queue's last burst have **undefined** content
— hardware does not track per-byte validity within a queue, so software filling a queue for a
burst must write all 8 words. After the burst completes, the queue's internal valid/dirty state
clears (tracked further in §6.3).

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
`HSQCR`. Restoring valid/dirty state is a separate, explicit `LDC` to `HSQCR`. Keeping the two
paths independent is what lets a restore sequence reproduce any state exactly, including a queue
whose bytes are fully written but whose `VALID`/`DIRTY` bits are clear.

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
successful burst of queue n: VALIDn <- 0, DIRTYn <- 0
trapped burst (HMCR.SQ=1)  : unchanged - the hypervisor decides
LDC to HSQCR at HPRIV=1    : set directly
reset                      : all zero
```

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

## 7. Context Switch

A vCPU's store-queue state — 64 bytes of buffer, two `QACR` values, and `HSQCR` — is per-vCPU
context that a hypervisor's scheduler must save on VM exit and restore before resuming that vCPU,
exactly like general-purpose registers. The sequences below are lazy in the ordinary sense: they
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
the queue is bit-for-bit as the guest left it. No flush is forced across the switch — the point
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

Cost: 72 bytes of state per additional context. See
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
