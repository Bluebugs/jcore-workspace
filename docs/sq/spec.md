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
