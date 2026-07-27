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
pending this specification. This document defines the baseline hardware feature only — the
interaction with a hypervisor guest is out of scope here and is added in §6–7 by a later revision
of this document.

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

Reading the queue buffers back (via ordinary load) is architecturally undefined on the baseline
hardware described in this document. A later section may define a narrow, explicitly-scoped
exception to this for hypervisor-privileged software; until such a section exists, no software
may rely on reading queue contents.

## 3. QACR Layout and Address Formation

**Register layout** (MMIO, privileged; addresses from [../soc/p4-mmio-map.md](../soc/p4-mmio-map.md)):

```
QACR0 (0xFF00003C)   QACR1 (0xFF000040)
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

This matches the SH-4 address-formation algorithm exactly, so existing SH-4 software needs no
change to use the J-Core store queue. Note that PA here is a guest physical address when a guest
is running — §6 covers what happens next.

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
For the motivating workload (a Dreamcast title streaming vertex data to the tile accelerator,
megabytes per frame) that would be the single dominant cost in the system. Making the common
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

**Cost.** The state is small and fixed: 64 bytes of buffer plus three registers (`QACR0`,
`QACR1`, `HSQCR`), independent of how much of either queue is actually populated. A hypervisor
may skip steps 2–3 of the save sequence for a queue whose `VALID` bit is clear, since there is
nothing live to preserve, but the worst case is bounded and small relative to the general-purpose
register file it is saved alongside.
