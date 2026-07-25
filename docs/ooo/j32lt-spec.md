# J32-LT — Light Out-of-Order, 4-Way Barrel-FGMT J-Core Specification

**Status:** Draft v0.1
**Compatible ISA:** J32 baseline (SH-2 + J-core extensions: SHAD, SHLD, CAS.L) + MMU
**Scope:** CPU core front end, issue, memory pipeline, PMU. FPU, MMU, IOMMU/DMA, SIMD, crypto specified separately.

**J32-LT** is a 2-wide in-order-issue, out-of-order-completion core with **4-way barrel FGMT**, 32-bit datapath. It is a *sibling* of [J32-OOO](j32ooo-spec.md), not a replacement: J32-OOO buys single-thread latency with register renaming and a wakeup-select issue queue; J32-LT buys **throughput per joule** with thread count and deletes both structures. See [glossary §3–§4](../glossary.md) for product-point and threading naming.

---

## 1. Goals and non-goals

### 1.1 Goals

1. **Energy efficiency first.** Minimise dynamic activity per committed instruction. Every structure in [j32ooo-spec](j32ooo-spec.md) that performs an associative search, a multi-way array read, or a speculative table lookup on every cycle or every memory op is either deleted or reduced to a single direct-mapped access.
2. **Aggregate IPC ≥ 1.5** architectural instructions retired per core cycle with 4 runnable threads (§2.4 derives the expected ~1.55).
3. **Single-thread floor:** with one thread runnable, IPC must be no worse than the in-order J32 baseline. Latency-sensitive workloads must not pay for the thread count. **This goal is presently in conflict with §3.1 + §3.3 — see §2.5. It is the one unresolved design question in this document.**
4. Preserve precise exceptions per thread, the J32 MMU model, and CAS.L semantics with no architecturally visible changes.
5. Present to Linux as 4 logical CPUs per core.

### 1.2 Non-goals

- **No register renaming.** No physical register file, no free list, no rename-map checkpoints. §5 explains why in-order issue makes them unnecessary rather than merely optional.
- **No issue queue.** No wakeup-select CAM, no age-priority select, no collapsing shift register.
- **No memory dependence prediction.** §7.3 shows the mechanism it protects against cannot occur here.
- **No SMT.** One thread is selected per cycle and fills both issue slots or leaves the second empty ([glossary §4](../glossary.md)).
- No fetch-alignment rotator, no decode-buffer compaction, no variable-width bundle steering.
- No new architecturally visible instructions.
- No wider-than-2 issue.
- No cycle-accurate emulation of historical SH-4 timing.

### 1.3 Relationship to J32-OOO

| | J32-OOO | J32-LT |
|---|---|---|
| Issue | out-of-order, 16-entry IQ | in-order, no IQ |
| Register handling | rename + PRF + checkpoints | future-file RAT → ROB, no PRF |
| Threads | FGMT 2-way | FGMT 4-way, barrel |
| Pipeline | 12 stages | 10 stages |
| Predictor | tournament (bimodal+gshare+chooser) | gshare only, BTFNT-seeded |
| Memory speculation | store-sets (SSIT+LFST) | none needed |
| Optimised for | single-thread latency | throughput per joule |

Both are J32-class (MMU, Tier 1 FPU-capable). Neither supersedes the other.

### 1.4 Prior-art citations (pre-2006, per [glossary §2](../glossary.md))

| Technique | Citation |
|---|---|
| Barrel multithreading, thread count = front-end depth | CDC 6600 PPU (Thornton, *Design of a Computer*, 1970, describing the 1964 design) |
| Cycle-by-cycle context switch on a RISC pipeline | Denelcor HEP (Smith 1978–1985) |
| Massive thread interleaving | Tera MTA (Smith 1990; ISCA 1994–1998) |
| Ready-thread arbitration / switch-on-event | MIT Alewife Sparcle (Agarwal, Kubiatowicz et al. 1993) |
| 4-way FGMT on a commercial in-order core | Sun UltraSPARC T1 "Niagara" (Kongetira, Aingaran, Olukotun, IEEE Micro 2005) |
| Scoreboard, in-order issue / out-of-order completion | CDC 6600 (Thornton 1964) |
| Future-file result forwarding, in-order commit | Smith & Pleszkun 1985; Intel Pentium Pro 1995 |
| History-buffer squash restore (per-entry previous mapping) | Smith & Pleszkun 1985; MIPS R10000 (1996) |
| gshare branch predictor | McFarling 1993 |
| Static backward-taken/forward-not-taken direction | Smith 1981; Lee & Smith 1984; Ball & Larus 1993 |
| Return Address Stack | Kaeli & Emma 1991 |
| Macro-op fusion (compare + branch) | AMD K7 1999 |
| Lockup-free cache, MSHRs | Kroft 1981 |
| Non-blocking loads on an in-order pipeline | Chen & Baer 1992; Farkas & Jouppi 1994 |
| Stride prefetcher | Chen & Baer 1995 |
| Next-line prefetch / stream buffers | Jouppi 1990 |
| PMU event counters, per-strand | DEC Alpha 21064 1992; PowerPC 750 1997; UltraSPARC T1 per-strand counters 2005 |

Nothing in this document requires a post-2005 citation.

---

## 2. Top-level pipeline

### 2.1 Stages

```
 IF1     IF2     DEC     PAIR    ISS     RR     EX     MA      WB     CMT
 fetch1  fetch2  decode  steer   issue   reg    exec   mem     write  commit
                 ×2      +fuse           read                  back
+-------+-------+-------+-------+-------+------+------+-------+------+------+
| I$tag | I$dat | dec0  | fuse  | RAT   | ARF  | ALU0 | D$    | ROB  | ARF  |
| BTB   | gshare| dec1  | rules | ready | ROB  | ALU1 | LSQ   | upd  | RAT  |
| RAS   | +pred |       | steer | FU    | read | MUL  | MSHR  |      | ret  |
+-------+-------+-------+-------+-------+------+------+-------+------+------+
   \_________ barrel front end __________/  \_____ shared back end ______/
        4 threads, 4 stages, 1:1
```

Ten stages. The four stages IF1–PAIR form the **barrel** (§3). ISS onward is shared and thread-tagged.

### 2.2 What each boundary does

- **IF1 → IF2**: I-cache tag then data. 32-bit aligned read; two SH instructions.
- **IF2**: gshare/BTB/RAS prediction resolves in the same cycle as I$ data.
- **DEC**: two independent decoders, one per bundle slot. Multi-uop cracking (MAC, RTE, TRAPA, MOVMU/MOVML) happens here.
- **PAIR**: the new stage. Decides *what* issues — fusion detection, pairing legality, slot-0 kill on a mid-bundle branch target. Owns every comparator that would otherwise sit on the decode critical path.
- **ISS**: readiness only — consult the RAT/scoreboard, allocate FUs and ROB slots. No CAM, no select tree.
- **RR**: read the ARF and the ROB value fields for operands the RAT says are in flight.
- **EX / MA / WB / CMT**: execute, memory, write result into the ROB, commit in order per thread.

The separation of PAIR from DEC exists for Fmax as much as for clarity. J4 experience is that the critical path is decoder combinational depth, not the datapath ALU (~80% of logic levels); adding fusion and pairing comparators to DEC would land directly on that path.

### 2.3 Why PAIR costs less than it looks

PAIR is a fixed two-slot comparison, not a variable-width steering network, because the bundle model (§3.3) guarantees exactly two candidate instructions in fixed positions. There is no rotator, no priority selection among N candidates, and no compaction. The stage is a flat block of comparators with a one-cycle budget.

### 2.4 IPC derivation

Under the barrel (§3.1) a thread presents a bundle to ISS every 4 cycles. With 4 threads:

- Bundle period per thread: **4 cycles**, carrying 2 architectural instructions.
- Per-thread issue rate: 0.5 instr/cycle.
- Aggregate demand on the single issue port: 4 × 0.5 = **2.0 ports-worth**.

Demand exceeds supply, so the issue port saturates and aggregate IPC is **width-limited, not fetch-limited**:

```
aggregate IPC  =  P(port busy) × E[width | issuing]
               ≈  1.0 × E[width]
```

`E[width]` is the average number of architectural instructions retired per issuing cycle. Three SH-specific effects set it:

1. **Delayed branches pair by construction.** `BRA`/`BSR`/`JMP`/`JSR`/`RTS`/`BRAF`/`BSRF` and their delay slot are adjacent and independent *by definition of the delay slot*. Whenever the branch lands in slot 0, the pair dual-issues unconditionally.
2. **Fusion retires 2 for 1.** A fused `CMP`+`BT` occupies one slot and retires two architectural instructions. This pattern is ~15–20% of dynamic SH-2 instructions.
3. **Mid-bundle branch targets cost a slot.** SH-2 branch targets are 2-byte but not 4-byte aligned, so roughly half of taken branches land in slot 1 and kill slot 0 (§3.3).

Expected `E[width] ≈ 1.55`, giving **aggregate IPC ≈ 1.55**, against a hard ceiling of 2.0.

**This is a projection, not a measurement.** §12.2 makes it a gate, and §14 records the fallback if it does not hold.

### 2.5 Single-thread behaviour — an unresolved conflict

The arithmetic of §2.4 runs the other way when threads are idle. With **one** runnable thread under a strict barrel (§3.1) and one bundle in flight per thread (§3.3):

- the thread reaches ISS once every 4 cycles, and
- its next fetch cannot launch until the current bundle drains,

so it retires 2 architectural instructions per 4–5 cycles: **~0.4–0.5 IPC**. The in-order J32 baseline is ~0.7–0.85. **Goal §1.1(3) is therefore violated by roughly a factor of two, and gate G2 fails by construction rather than by tuning.**

This is not a defect in the barrel; it is the direct cost of the two properties that make the front end cheap. A barrel with idle threads leaves their stages empty by definition, and the single-bundle rule prevents the remaining thread from filling them. The three ways out:

| Option | Single-thread IPC | Cost |
|---|---|---|
| **A. Accept it.** Restate §1.1(3): J32-LT is a throughput part, single-thread latency work belongs on J32-OOO. | ~0.45 | none |
| **B. Barrel compaction.** The counter cycles `mod k` over the *k* ready threads; a thread may hold up to `⌈4/k⌉` bundles in flight, so the standby register (§3.2) becomes a `⌈4/k⌉`-deep queue (4-deep at `k=1`). At `k=1` this degenerates to an ordinary in-order dual-issue pipeline with a 4-deep fetch queue. | ~1.3–1.5 | standby register → 4-deep queue per thread (~1.1k FFs), per-stage thread tags return, barrel invariant of §3.1 and §8.2 is lost |
| **C. Compaction only at `k=1`.** A single-thread mode bit; the barrel is strict for `k≥2`. | ~1.3–1.5 at `k=1`, ~0.45 at `k=2–3` | a mode transition to verify, and the `k=2`/`k=3` cases stay bad |

**No option is selected.** Option B is the only one that satisfies §1.1(3) as written, and it gives back a meaningful part of what §3.1 bought — including the tag-free front end, which is one of the larger energy items in §12.1. Option A keeps the design honest and cheap but requires amending §1.1(3) and dropping gate G2.

This must be decided before P1 (§15). It does not affect P0, which measures aggregate IPC.

---

## 3. Barrel front end

### 3.1 The barrel

Four thread contexts, four front-end stages ahead of ISS. Thread *T* launches a fetch at IF1 on cycles where `cycle mod 4 == T`; its bundle advances one stage per cycle and arrives at ISS exactly four cycles later — precisely when it is *T*'s turn again.

```
cycle:      0     1     2     3     4     5     6     7
IF1:       T0    T1    T2    T3    T0    T1    T2    T3
IF2:        –    T0    T1    T2    T3    T0    T1    T2
DEC:        –     –    T0    T1    T2    T3    T0    T1
PAIR:       –     –     –    T0    T1    T2    T3    T0
ISS:        –     –     –     –    T0    T1    T2    T3
```

Consequences, all of them savings:

- **No IF1 arbiter.** Thread selection is a 2-bit counter. The ready-thread arbitration logic of [j32ooo-spec §13.2](j32ooo-spec.md) disappears; readiness becomes a *mask* on the counter, not a priority computation.
- **No per-stage thread tags in the front end.** A stage's occupant is `(cycle - stage_depth) mod 4`. Tags reappear only at ISS, where the back end is shared.
- **No cross-thread structural hazard in IF1–PAIR.** Each stage holds exactly one thread's bundle each cycle, by construction.

Prior art: CDC 6600 peripheral processors (Thornton 1964) are exactly this structure — 10 threads, 10-deep barrel, one stage per thread. Denelcor HEP (1978) and Tera MTA (1990) generalise it.

### 3.2 Standby overflow register

A pure barrel assumes a bundle at ISS always drains. When it does not — an operand is not ready, an FU is busy, or the bundle splits across two cycles (§3.4) — the follower arriving from PAIR has nowhere to go.

J32-LT adds a **one-deep standby register per thread**, placed after IF2 and holding **raw** bundle state:

| Field | Width |
|---|---|
| instruction pair | 32 b |
| bundle PC | 32 b |
| slot-0 valid (mid-bundle target kill) | 1 b |
| prediction outcome + BTB/RAS sideband | ~5 b |
| valid | 1 b |

≈ 71 bits × 4 threads ≈ **284 flip-flops**. Holding raw (undecoded) bundles rather than decoded control fields is what keeps this narrow; the cost is that a promoted standby bundle re-traverses DEC and PAIR, which is free because those stages would otherwise be idle in that thread's barrel slot.

When a thread's ISS bundle fails to drain, its follower parks in the standby register and the barrel keeps turning for the other three threads. When a thread's standby register is occupied *and* its ISS bundle is still stuck, that thread's next barrel slot goes unused — the degradation is confined to the stalling thread.

### 3.3 Bundle model

- Fetch is a **plain 32-bit aligned I-cache read**. No rotator, no shifter, no partial-line assembly.
- A **bundle** is exactly two 16-bit instructions at `{PC[31:2], 00}`.
- A branch to an **odd-halfword target kills slot 0**. That bundle carries at most one instruction. This is the price of not having an alignment network and it is paid on roughly half of all taken branches.
- **Bundles do not collapse.** If slot 0 issues and slot 1 is blocked, slot 0 is not backfilled; the bundle remains at ISS until slot 1 goes. There is no compaction network and no partial refill.

### 3.4 Split bundles

A bundle that cannot dual-issue occupies ISS for two of its thread's barrel slots — that is, 8 cycles of wall clock, during which the other three threads are unaffected. The thread's own throughput halves for that bundle; the core's does not, as long as another thread has work. This is the entire FGMT bargain, stated concretely, and it is why the thread count is 4 rather than 2.

### 3.5 Branch prediction

**gshare only, BTFNT-seeded.**

| Structure | Size | Index |
|---|---|---|
| gshare PHT | 1024 × 2-bit counters | `PC[10:1] XOR GHR[9:0] XOR {tid,tid}` |
| GHR | 10 b × 4 threads | per-thread, speculative + committed copy |
| BTB | 32-entry, 4-way SA | PC tag + 2-bit TC_ID |
| RAS | 8 entries × 4 threads | per-thread, mandatory |

**BTFNT seeding.** On BTB allocation the corresponding PHT counter is initialised to the static backward-taken/forward-not-taken direction — backward branch → weakly taken (`10`), forward branch → weakly not taken (`01`) — rather than to a neutral or zero value. Cold-start accuracy approaches the static heuristic (~65–70% on typical code) instead of coin-flip, and the counter trains away from it wherever dynamic behaviour disagrees.

Relative to [j32ooo-spec §3.2](j32ooo-spec.md) this **deletes the 1024-entry bimodal table and the 1024-entry chooser table**, taking predictor array reads from three per prediction to one. On a structure accessed every fetch cycle this is one of the largest single energy items in the front end.

Per-thread RAS is not optional: a shared RAS is corrupted by interleaved call/return streams from four threads, and the corruption is silent.

### 3.6 Delayed branch handling

SH delayed branches (`BRA`, `BSR`, `JMP`, `JSR`, `RTS`, `BT/S`, `BF/S`, `BRAF`, `BSRF`, `RTE`) carry one delay slot, which executes whether or not the branch is taken.

- **Branch in slot 0**: its delay slot is slot 1 of the same bundle. Guaranteed dual-issue pair (§2.4 item 1).
- **Branch in slot 1**: its delay slot is slot 0 of the *next* bundle. The branch issues, but the pair is tagged `DELAY_BRANCH` / `DELAY_SLOT` and commit is held until both are complete. Fetch redirection to the predicted target happens after the delay-slot bundle is fetched, exactly as in [j32ooo-spec §3.3](j32ooo-spec.md).
- **Mispredict**: squash everything in the thread's ROB *after* the delay slot. The delay slot itself is architecturally executed and must not be squashed.

### 3.7 Misprediction penalty

7 cycles raw (redirect at EX, refill IF1→ISS through the barrel). Under the barrel this is **1.75 of the mispredicting thread's own issue opportunities** — the other three threads occupy the intervening cycles and lose nothing. The throughput cost of a mispredict is therefore roughly a quarter of its latency cost, which is the main reason a single gshare table is sufficient here where a tournament predictor was specified for J32-OOO.

---

## 4. Decode and PAIR

### 4.1 Decode

Two independent decoders, one per slot. Multi-uop instructions crack here, per [j32ooo-spec §4.1](j32ooo-spec.md): `MAC.L`/`MAC.W` → 4, `RTE` → 3, `CAS.L` → 3, `TRAPA` → 4+, `LDS.L @Rm+` → 2, `MOVMU.L`/`MOVML.L` → 1–17.

**A cracking instruction occupies the bundle alone.** If a multi-uop instruction appears in slot 0, slot 1 does not issue with it; if in slot 1, it issues alone after slot 0. This keeps the ROB allocation port 2-wide and avoids a variable-width allocator. Cracking instructions are rare enough in the target workloads that the IPC cost is second-order; `MOVMU`/`MOVML` are the exception and are addressed in §14.

### 4.2 Macro-op fusion

Fusion is detected at PAIR across the two bundle slots. It is **load-bearing for the IPC target**, not an optimisation.

| Slot 0 | Slot 1 | Fused into |
|---|---|---|
| `CMP/EQ`, `CMP/GE`, `CMP/GT`, `CMP/HI`, `CMP/HS`, `CMP/PL`, `CMP/PZ`, `CMP/STR`, `CMP/EQ #imm,R0` | `BT`, `BF` | one branch uop carrying the compare |
| `TST Rm,Rn`, `TST #imm,R0` | `BT`, `BF` | one branch uop carrying the test |
| `DT Rn` | `BT`, `BF` | one branch uop carrying decrement-and-test (writes Rn *and* resolves the branch) |

Effects:

1. The pair retires 2 architectural instructions from 1 issue slot.
2. The T-bit RAW dependency between the two is removed from the RAT entirely — the fused uop produces the branch outcome directly and (for `DT`) the register result.
3. The branch resolves one stage earlier than a `CMP`→`BT` chain would allow, shortening the mispredict window.

**Restrictions.** Only the non-delayed `BT`/`BF` fuse in this revision. `BT/S`/`BF/S` drag a delay slot into the fusion window — the fused uop would have to carry a third instruction's worth of state — and are deferred (§14). Fusion requires both slots valid, so a mid-bundle branch target that kills slot 0 also kills the fusion opportunity.

Prior art: AMD K7 (1999) macro-op fusion of compare-and-branch pairs.

### 4.3 Pairing rules

Slot 0 and slot 1 dual-issue if and only if **all** of:

1. Both slots valid (slot 0 not killed by a mid-bundle target).
2. **No intra-pair RAW.** Slot 1's source set ∩ slot 0's destination set = ∅. The source and destination sets include implicit operands: `R0` in the indexed addressing modes, `T`, `S`, `MACH`, `MACL`, `PR`, `GBR`. There is no same-cycle bypass between the two slots — a co-issued pair reads operands together at RR — so a RAW pair *must* split.
3. No intra-pair T-bit RAW, **unless fused** (§4.2 removes it).
4. FU compatibility per the table below.
5. Neither slot is a cracking instruction (§4.1).
6. Neither slot is serializing (`LDC Rm,SR`, `LDC.L @Rm+,SR`, `LDC Rm,VBR`, `TRAPA`).
7. Both threads' ROB partition has ≥2 free entries.

**FU compatibility** (shift shares the ALU1 pipe; there is one multiplier, one LSU, one branch unit):

| slot 0 ↓ / slot 1 → | ALU | Shift | Mul/MAC | Load/Store | Branch |
|---|---|---|---|---|---|
| **ALU** | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Shift** | ✓ | ✗ | ✓ | ✓ | ✓ |
| **Mul/MAC** | ✓ | ✓ | ✗ | ✓ | ✓ |
| **Load/Store** | ✓ | ✓ | ✓ | ✗ | ✓ |
| **Branch** | ✓ (delay slot) | ✓ | ✓ | ✓ | ✗ |

The `Branch`/`ALU` cell is the delayed-branch case of §3.6 and is the single most frequent productive pairing in SH-2 code.

---

## 5. Register handling — future-file RAT, no renaming

### 5.1 The mechanism

Each thread has a **RAT** mapping each architectural register to its current producer:

```
RAT[reg] = { IN_ARF }                    // committed value lives in the ARF
         | { ROB_SLOT, slot_index[2:0] } // value is (or will be) in this ROB entry
```

23 architectural registers × 4 bits (1 valid + 3 slot index into an 8-entry partition) × 4 threads = **368 bits total**.

At RR, each source operand reads either the thread's ARF or the ROB `value` field indicated by the RAT. At CMT, the committing entry's value moves into the ARF and its RAT entry reverts to `IN_ARF` (if it is still the current producer).

**There is no physical register file, no free list, and no rename-map checkpointing.**

### 5.2 Why renaming is unnecessary here

Renaming exists to break WAR and WAW hazards so that instructions may issue out of program order. J32-LT issues **in order per thread** and commits **in order per thread**. Therefore:

- **WAR is impossible.** A younger write cannot reach the register file before an older read, because the older instruction reads its operands at RR before the younger one issues at all.
- **WAW is impossible.** Two writes to the same register commit in program order by construction of the ROB.

The RAT is doing pure producer-tracking, not name-space expansion. This is the P6 future-file (Smith & Pleszkun 1985; Pentium Pro 1995) with the physical register file removed — values live in the ROB until commit and nowhere else.

Deleted relative to [j32ooo-spec §5](j32ooo-spec.md): the physical register file and its read ports, the free list and its allocation/reclaim logic, and 8 checkpoints × 23 entries × 6 bits **per thread** of rename-map copies.

### 5.3 Architectural registers

`R0`–`R15`, `T`, `S`, `MACH`, `MACL`, `PR`, `GBR`, `VBR` — 23 entries per thread. Full per-thread ARF: 23 × 32 b × 4 = **2944 bits (368 bytes)**.

`T` is tracked independently of the rest of `SR`, so dependent compare chains within a thread do not serialise. `SR`'s other fields follow [j32ooo-spec §4.5](j32ooo-spec.md): `S` independent, `Q`/`M` as a DIV group, `I3`–`I0` as a mask group, `BL`/`RB`/`MD` privileged. `LDC Rn,SR` writes all groups and is serializing.

### 5.4 Squash and restore — history buffer, not checkpoints

Each ROB entry carries the **previous RAT mapping** for its destination register (4 bits). On a mispredict or exception, restoring the thread's RAT is a backward walk over the squashed range, applied as a one-cycle priority mux because the range is at most 8 entries deep.

This is tractable *because* the ROB partition is small, and the ROB partition is small *because* in-order issue bounds how far ahead a thread can run. The two choices are mutually reinforcing.

Prior art: Smith & Pleszkun 1985 history buffer; MIPS R10000 rename-undo (1996).

---

## 6. Issue, execution, and the ROB

### 6.1 Issue

At ISS, for the bundle at the head of the selected thread:

1. Look up each source operand's RAT entry.
2. A source is **ready** if `IN_ARF`, or if the indicated ROB entry has `valid=1`, or if its result is on the bypass network this cycle.
3. Check FU availability and ROB partition space.
4. Issue slot 0, slot 1, or both, per §4.3.

**No CAM. No broadcast tag match against a queue. No age-priority select tree. No collapsing shift register.** This is the single largest energy delta versus J32-OOO, where a 16-entry IQ performs 16 × 2 × 6-bit comparisons against each of 3 broadcast tags every cycle.

The cost is the in-order stall: a thread that cannot issue its head bundle issues nothing, even if a younger instruction is ready. Four threads are the compensation.

### 6.2 Execution units

Shared across threads; only one thread issues per cycle, so there is no cross-thread FU arbitration.

| FU | Issue rate | Latency | Operations |
|---|---|---|---|
| ALU0 | 1/cycle | 1 | add/sub/logic, T-producing compares |
| ALU1 | 1/cycle | 1 | add/sub/logic, T-producing compares |
| Shift | 1/cycle | 1 | `SHLL`/`SHLR`/`SHAL`/`SHAR`/`ROT{C}L/R`, `SHAD`/`SHLD` — shares the ALU1 pipe |
| Mul | 1/cycle | 3 | `MULS.W`, `MULU.W`, `MUL.L`, `DMULS.L`, `DMULU.L` — reuses `core/mult.vhm` |
| MAC | 1/cycle | 3+1 | `MAC.W`, `MAC.L` |
| LSU | 1/cycle | 2 | 1-cycle AGEN + 1-cycle D$ access |
| Branch | 1/cycle | 1 | unconditional + conditional resolution, fused compare-branch |
| Div | 1/16–32 | 16–32 | `DIV1` iterated, non-pipelined, attached to ALU0 |

### 6.3 ROB — partitioned

**8 entries per thread × 4 threads = 32 entries.** Partitioned, not shared-and-tagged.

Rationale: in-order issue bounds a thread's useful in-flight window to a handful of instructions (a thread presents 2 instructions every 4 cycles and drains them in ~4 more), so the dynamic-sharing argument that favours a shared ROB on an OOO machine does not apply. Partitioning replaces a 4-way thread-tagged commit search with four independent head pointers and four independent tail pointers. The cost is that a stalled thread's 8 slots sit idle — 25% of a small structure, in exchange for the entire tagged-commit selector.

Per entry:

| Field | Width | Notes |
|---|---|---|
| `pc` | 32 b | exception reporting |
| `op_type` | 4 b | branch / load / store / ALU / … |
| `dst_logical` | 5 b | destination architectural register |
| `prev_rat` | 4 b | **previous RAT mapping — enables §5.4 squash restore** |
| `value` | 32 b | result; read directly at RR by consumers |
| `valid` | 1 b | result written |
| `exception` | 4 b | exception type, if any |
| `is_cas_fail_candidate` | 1 b | CAS.L conditional-store uop |
| `is_sleep` | 1 b | SLEEP |
| `flags` | — | `atomic_group`, `delay_branch`, `delay_slot`, `serializing`, `branch_mispredict_pending` |

Note the absence of a `dst_physical` field — there are no physical registers.

### 6.4 Commit

Four independent commit ports, one per thread, each examining its own partition head. Up to 2 entries per thread per cycle, in order, when `valid=1` and `exception=0`. A stalled commit on one thread does not block any other.

Atomic groups (§8) do not commit until every uop in the group is valid.

### 6.5 Exceptions

Precise per thread. On exception at commit:

1. Flush that thread's ROB partition, LQ, SQ, standby register, and barrel-resident bundles.
2. Restore that thread's RAT via the §5.4 history walk.
3. Set `SR.BL`, save `SPC`/`SSR`, vector through `VBR`.

The other three threads are entirely unaffected — they share no front-end stage state with the excepting thread beyond the barrel counter, which is not thread-specific.

---

## 7. Memory pipeline

### 7.1 Per-thread LSQ

**LQ 4 entries + SQ 4 entries per thread**, partitioned rather than shared-and-tagged.

Store-to-load forwarding is therefore **structurally** within-thread: the cross-thread ID comparison specified in [j32ooo-spec §8.3](j32ooo-spec.md) does not exist because there is nothing to compare. Cross-thread aliasing goes through the cache and coherence fabric, exactly as it does between cores in SMP.

### 7.2 Forwarding

On a load issue, the thread's SQ is searched for older stores to the same address:

- **Match, data valid** → forward from SQ.
- **Match, data not valid** → the load waits for the store's data (the store's producer is still in flight).
- **No match** → issue to the D-cache.

There is no fourth case.

### 7.3 The store-set predictor is deleted

[j32ooo-spec §8.4](j32ooo-spec.md) specifies a Chrysos & Emer (1998) store-set predictor: a 1024-entry SSIT plus a 64-entry LFST, consulted on memory operations, to decide whether a load may speculatively bypass a store whose address is not yet known.

**That case cannot arise in J32-LT.** Memory operations issue in program order per thread, and a store computes its address at issue. Therefore every older store's address is known before any younger load of the same thread issues. There is no address speculation, no memory-order violation, and no recovery path.

This removes two arrays, their per-memory-op lookups, the violation-detection comparators, and the squash-and-replay machinery. It is the cleanest area and energy win in the design, and it falls directly out of in-order issue rather than being a separate design decision.

The cost is real and should be stated: a load cannot bypass an older store that is waiting on its data. That thread stalls. The other three threads cover it.

### 7.4 MSHRs — 2 per thread + 2 shared

Non-blocking loads still pay off under in-order issue, because a thread stalls only at the first instruction that *consumes* a missing load. Independent younger loads and all younger stores continue to issue past a miss.

| MSHR pool | Count | Purpose |
|---|---|---|
| Per-thread L1-D | 2 × 4 = 8 | demand misses |
| Shared prefetch | 2 | stride and next-line prefetch fills |

Per-thread allocation, rather than a shared pool, guarantees that one thread's miss burst cannot starve another thread's demand miss — the same isolation argument as the partitioned ROB and LSQ, and the reason the whole design partitions per thread wherever the structure is small.

Prior art: Kroft 1981 (lockup-free cache with MSHRs); Farkas & Jouppi 1994 (non-blocking loads on in-order pipelines).

### 7.5 Cache hierarchy

Inherited from [j32ooo-spec §11](j32ooo-spec.md) and [cache/l2-spec.md](../cache/l2-spec.md) with the thread count raised to 4:

| Structure | Parameter |
|---|---|
| L1-I | 32 KB, 4-way SA, 32 B lines, pseudo-LRU, next-line prefetch |
| L1-D | 32 KB, 4-way SA, 32 B lines, write-through, write-allocate, pseudo-LRU |
| L2 | 128 KB unified, 8-way SA, write-back, inclusive |
| Stride prefetcher | 8-entry table **× 4 threads** |

Four threads sharing a 32 KB L1 halves the effective per-thread capacity relative to the 2-way case. §12.2 makes L1 miss rate under 4-thread load an explicit measurement gate; if it degrades more than projected, the levers are associativity, capacity, or way-prediction (§14), in that order of preference.

### 7.6 Memory ordering

Unchanged: SH-2 weak ordering. Loads and stores of a given thread issue in program order but may *complete* out of order; independent accesses across threads are unordered except through the coherence fabric and the CAS.L atomic window.

---

## 8. CAS.L and atomics

CAS.L cracks into 3 uops per [j32ooo-spec §10.2](j32ooo-spec.md), and atomicity is provided by the **L2 per-line lock** of [cache/l2-spec.md §6](../cache/l2-spec.md), not the legacy bus lock:

1. `MOV` — save `Rn` to a scratch slot.
2. `LD.L @R0, LOCK` — locked load, drives `GetM-Locked` to L2.
3. `CMP_CSTORE` — conditional store, drives `Unlock` (with new data on `T=1`, without on `T=0`). Tagged `is_cas_fail_candidate=1`.

All three carry `atomic_group=1` and commit atomically.

### 8.1 Four-thread contention

While one thread holds an atomic group, the other three threads' memory uops queue in their own LSQs and do not issue to the D-cache; their non-memory uops continue to issue and retire normally. [cache/l2-spec.md §6.6](../cache/l2-spec.md) specifies per-thread qualification of the line lock for 2 threads; it needs generalising to 4 (§13, item 6).

The worst case is four threads on one core contending the same line, which the L2 line lock serialises. Auto-priority (§9.3) is what keeps this from degenerating.

### 8.2 Barrel interaction

A parked or lock-spinning thread is masked out of the barrel counter rather than removed from it: the barrel continues to turn at 4 and that thread's slot goes unused. This keeps the "stage occupant = `(cycle - depth) mod 4`" invariant intact, which is what makes the front end tag-free (§3.1). The alternative — compacting the barrel to the ready-thread count — would reintroduce per-stage thread tags and an arbiter, for a gain confined to the case where threads are idle anyway.

---

## 9. Four-way FGMT

### 9.1 Per-thread context

| Item | Size |
|---|---|
| ARF (23 × 32 b) | 92 B |
| PC + next-PC | 8 B |
| RAT (23 × 4 b) | 12 B |
| ROB partition (8 entries) | — (in §6.3 total) |
| LQ 4 + SQ 4 | — (in §7.1 total) |
| MSHR × 2 | — |
| GHR (10 b) | 2 B |
| RAS (8 × 32 b) | 32 B |
| Standby bundle register | 9 B |
| `ASIDR` (16 b `ASID_TAG`) | 2 B |
| Auto-priority state (`last_cas_pc`, `cas_fail_count`, `prio_dropped`, `parked`) | 5 B |
| **Per thread** | **~162 B** |
| **Four threads** | **~648 B** |

Fits in distributed RAM and flip-flops.

Note the absence of rename-map checkpoints, which at [j32ooo-spec §13.1](j32ooo-spec.md)'s 8 × 23 × 6 bits were 138 B per thread — the largest single item in the J32-OOO per-thread context and, at 4 threads, would have been 552 B on its own.

### 9.2 Resource sharing

| Resource | Model |
|---|---|
| IF1–PAIR (barrel) | one thread per stage per cycle, positional, **no arbiter** |
| Standby register | per thread |
| RAT | per thread |
| ROB | **partitioned**, 8/thread |
| LQ / SQ | **partitioned**, 4+4/thread |
| MSHR | **partitioned**, 2/thread + 2 shared prefetch |
| ARF | per thread |
| Functional units | shared; one issuing thread per cycle |
| L1-I / L1-D / L2 | shared, unpartitioned |
| gshare PHT / BTB | shared, thread-ID-hashed index / thread-tagged |
| GHR / RAS | **per thread (mandatory)** |
| Stride prefetch table | per thread |
| `ASIDR` | **per thread** — see §11 |
| PMU counters | per-thread shadowing |

The design partitions every small per-thread structure and shares every large one. The threshold is roughly "does dynamic sharing recover more than the tagging costs" — for an 8-entry ROB under in-order issue it does not; for a 32 KB cache it obviously does.

### 9.3 Automatic priority adjustment

Two hardware-managed events mask a thread out of the barrel. No software-exposed priority hints (§1.2).

**1. CAS.L spin detection.** Per thread: `last_cas_pc` (32 b), `cas_fail_count` (3 b, saturating), `prio_dropped` (1 b). On CAS.L uop-3 retirement with `T=0` at the same PC as `last_cas_pc`, increment; at ≥2 consecutive same-PC failures, the thread is masked out of every second barrel slot. A successful CAS, a far branch, or an interrupt restores it and clears the state. ~200 gates.

**2. SLEEP.** On `SLEEP` decode, the thread is marked `parked` and masked out of the barrel entirely. Its slot goes unused (§8.2). Any interrupt routed to that thread clears `parked` and resumes fetch at the post-SLEEP PC. The unpark signal is the `per_tc_pending[t]` bundle from AIC2 ([aic/aic2-spec.md §4.3](../aic/aic2-spec.md)). ~150 gates.

Prior art: MIT Alewife Sparcle block-multithreaded scheduling (1993); HEP spin-wait coalescing (1978). Tullsen, Lo, Eggers & Levy (1996) is the fetch-policy family; the mechanism here is keyed on atomic-failure history rather than cache-miss history.

---

## 10. Performance monitoring

PowerPC 750-class PMU with **per-thread shadowing across 4 threads**, per [j32ooo-spec §12](j32ooo-spec.md). Register set (`PMCR`, `PMSEL0-3`, `PMCNT0-3`, `PMCYC`, `PMINS`, `PMOVF`, `PMTID`) unchanged; `PMTID` selects among 4 contexts instead of 2. Overflow wires as a direct per-core source into AIC2 ([aic/aic2-spec.md §6.4](../aic/aic2-spec.md)).

Events inherited from [j32ooo-spec §12.2](j32ooo-spec.md), with these changes:

| Event ID | Event | Change |
|---|---|---|
| 0x0B | `LSQ_STALL_CYCLES` | retained |
| 0x0C | `ROB_FULL_STALL_CYCLES` | now per-partition |
| 0x0D | ~~`IQ_FULL_STALL_CYCLES`~~ | **removed** — no issue queue |
| 0x0E | ~~`RENAME_STALL_CYCLES`~~ | **removed** — no rename |
| 0x15 | `BUNDLE_SPLIT` | *new* — bundles that failed to dual-issue (§3.4). **The primary IPC diagnostic.** |
| 0x16 | `SLOT0_KILLED` | *new* — mid-bundle branch targets (§3.3) |
| 0x17 | `FUSION_HITS` | *new* — fused compare-branch pairs (§4.2) |
| 0x18 | `BARREL_SLOT_IDLE` | *new* — barrel slots unused because the owning thread was masked or stalled |

The four new events exist specifically to make §2.4's IPC projection falsifiable on hardware. `BUNDLE_SPLIT`, `FUSION_HITS`, and `SLOT0_KILLED` together reconstruct `E[width]` directly.

Linux integration unchanged: `arch/sh/kernel/perf_event_j32.c` with a 4-context event map.

---

## 11. MMU interaction

J32-LT is J32-class and carries the SH-4-model MMU of [mmu/hardware-spec.md](../mmu/hardware-spec.md). One change is required:

**`ASIDR` becomes per-thread-context.** [mmu/hardware-spec.md §2.1a](../mmu/hardware-spec.md) defines `ASIDR` as a single per-CPU register holding the live 16-bit `ASID_TAG`. Under FGMT each thread runs an independent address space, so the core holds **4 `ASIDR` copies**, and the TLB lookup of [mmu/hardware-spec.md §4](../mmu/hardware-spec.md) selects by the issuing thread's TC_ID:

```
match = match && (entry.GLOBAL || entry.ASID_TAG == ASIDR[tid])
```

`LDC Rm, ASIDR` / `STC ASIDR, Rn` write and read the issuing thread's copy; no encoding change, no new instruction. `LDTLB` latches `{ASIDR[tid], PTEH.VPN, PTEL}`.

The TLB itself remains shared and unpartitioned — entries are already `ASID_TAG`-tagged, so four contexts coexist correctly with no further change. Cost: 3 additional 16-bit registers and a 4:1 mux on the TLB compare input.

Everything else in the MMU spec — `PTEH` VPN-only, generation-tagged `ASID_TAG`, `STALE` enforcement, the TSB miss path, `LDTLB.RN` — is unaffected.

---

## 12. Cost and validation

### 12.1 Gate estimate

| Block | J32-LT | J32-OOO | Δ |
|---|---|---|---|
| I-cache control + BTB | 14,000 | 14,000 | — |
| Branch predictor (gshare only) + RAS ×4 | 6,000 | 10,000 | −4,000 |
| Decode + uop crack | 18,000 | 18,000 | — |
| **PAIR stage** (fusion, rules, steer) | 6,000 | — | +6,000 |
| RAT (future-file) ×4 + scoreboard | 8,000 | 18,000 | −10,000 |
| ROB (32 entries, partitioned) | 40,000 | 26,000 | +14,000 |
| **Issue queue** | **0** | 20,000 | **−20,000** |
| ARF ×4 + register read | 18,000 | 10,000 | +8,000 |
| ALU pipes ×2 | 12,000 | 12,000 | — |
| Shift + Mul + Div | 18,000 | 18,000 | — |
| LSU + LQ/SQ ×4 + MSHR (no store-sets) | 24,000 | 26,000 | −2,000 |
| Commit + retire | 8,000 | 10,000 | −2,000 |
| FGMT machinery (barrel, standby, per-thread state) | 16,000 | 13,450 | +2,550 |
| PMU ×4 threads | 14,000 | 9,500 | +4,500 |
| Misc (bypass, control, debug) | 17,000 | 17,000 | — |
| **Subtotal (core)** | **~219,000** | **221,950** | **−3,000** |
| Cache subsystem | 18,500 | 18,500 | — |
| **Total core + caches** | **~237,500** | **~240,450** | — |

**J32-LT is not smaller than J32-OOO.** This is the single most important number in this document and it should not be buried: the design trades scheduler area for thread-context area, and the two roughly cancel. Doubling the thread count consumes essentially everything that deleting the issue queue, the rename machinery, the store-set predictor, and two predictor tables gives back.

**The win is energy per instruction, not die area.** Per-cycle dynamic activity is where the two designs diverge:

| Per-cycle or per-op activity | J32-OOO | J32-LT |
|---|---|---|
| Predictor array reads per prediction | 3 (bimodal + gshare + chooser) | **1** |
| IQ tag comparisons per cycle | 16 × 2 × 6 b × 3 broadcast tags | **0** |
| IQ collapse shift per issue | 16-entry shift register, all fields | **0** |
| Register file read ports | PRF + ARF | **ARF only** |
| Memory-dependence lookups per memory op | SSIT + LFST | **0** |
| Rename checkpoint copies per branch | 23 × 6 b | **0** |
| Front-end arbitration per cycle | ready-thread priority computation | **2-bit counter** |
| Front-end thread tags per stage | yes | **none (positional)** |
| Wasted I$ reads | speculative fetch | speculative fetch (same) |

The claim this design makes is **throughput per joule at comparable area**, and §12.2 must test that claim directly, not merely test IPC.

### 12.2 Validation gates

Every number in §12.1 and §2.4 is an a-priori estimate. [j32ooo-spec §15.1](j32ooo-spec.md) already records that the gate-to-LUT4 conversion for this family is unvalidated and roughly 4× the [service plan §5](../jcore-ulx3s-service-plan.md) budget. J32-LT inherits that caveat in full and adds these gates:

| # | Gate | Measured how | Threshold |
|---|---|---|---|
| G1 | Aggregate IPC ≥ 1.5, 4 threads | CoreMark ×4 + PMU `PMINS`/`PMCYC` | ≥1.5; **stop and reconsider §14 if <1.4** |
| G2 | Single-thread IPC ≥ in-order J32 | CoreMark, 1 thread, others parked | ≥ baseline — **conditional on the §2.5 decision; unreachable as specified** |
| G3 | `E[width]` decomposition matches §2.4 | PMU 0x15/0x16/0x17 | model within ±0.1 |
| G4 | Energy per instruction < J32-OOO | post-synthesis power estimate, same workload | strictly lower — **this is the design's whole claim** |
| G5 | L1-D miss rate under 4-thread load | PMU 0x06/0x07 | within 1.5× of 1-thread rate |
| G6 | LUT4 + BRAM on ECP5 85F | synthesis | fits alongside SoC peripherals |
| G7 | Fmax vs in-order J32 | synthesis, ECP5-6 | no worse than −10% |

**G4 is the gate that matters.** If J32-LT is the same area as J32-OOO and does not clearly win on energy per instruction, the design has no reason to exist and the roadmap should carry J32-OOO alone.

G1 and G3 should be run in simulation against `sim/sh2instr.c` traces well before RTL exists — the bundle model, barrel timing, fusion rate, and pairing rules are all analytically tractable, and a trace-driven model is far cheaper than discovering at G1 that `E[width]` is 1.3.

### 12.3 Verification

1. **FU level**: reuse `tests/arith_tap.vhd` and the existing FU testbenches.
2. **Structural**: directed tests for the barrel (slot ownership invariant under masking, standby promotion, mid-bundle target kill), PAIR (every cell of the §4.3 FU table, every fusion pattern in §4.2, intra-pair RAW on each implicit operand), RAT/ROB (squash restore across all 8 partition depths).
3. **Architectural**: `testrom/tests/*.s` against the core with 1, 2, and 4 threads active. CAS.L atomicity (`testmov.s:580–635`) is the atomic-group regression.
4. **Differential**: `sim/sh2instr.c` as the retirement oracle; mismatch at commit halts the simulation. This is the same methodology that found the four precise-exception defect classes during MMU M8, and it is the right tool for a machine whose whole correctness argument rests on in-order commit.
5. **Thread isolation**: four independent test programs concurrently; verify no cross-thread state corruption, particularly RAS, GHR, ASIDR, and LSQ forwarding.
6. **Stress**: Linux boot as 4 CPUs, Dhrystone, CoreMark, `stress-ng --futex`, LTP SMP subset, SSH bulk crypto, JSON parse.
7. **Regression against N_TC=1**: with a single thread configured at build time, results must match the in-order J32 path bit-for-bit — the same gate `fgmt/mt2x2-plan.md` §1 applies to the J2 line.

---

## 13. Documents this specification changes

| # | Document | Change |
|---|---|---|
| 1 | [glossary.md](../glossary.md) §3 | add the `J32-LT` product-point row |
| 2 | [glossary.md](../glossary.md) §4 | FGMT definition hardcodes "2-way on a 2-wide OoO machine"; generalise to N-way and describe the barrel case |
| 3 | [aic/aic2-spec.md](../aic/aic2-spec.md) §4 | T1 to `n_tc=4`: `TC_TARGET` widens to `log2(n_tc)` (currently packed into bit 7 of the per-source `TARGET` byte — **that packing breaks at 2 bits and must be respecified**), `IPI_SEND[cpu][tc]` region resizes to 4 words/core, `NUM_TC_LOG2` already accommodates it, `per_tc_pending[4]` wires to the barrel mask rather than to a ready-thread arbiter |
| 4 | [ooo/j32ooo-spec.md](j32ooo-spec.md) §18 | cross-reference J32-LT from the deferred fusion (18.2) and predictor items; header note distinguishing the design points. No structural rewrite |
| 5 | [jcore-ulx3s-service-plan.md](../jcore-ulx3s-service-plan.md) §5, Phase 6.5 | LUT4 budget line for J32-LT; Phase 6.5 reads "2-way FGMT on OoO core" and needs the light core as a distinct Tier 1.5 profile |
| 6 | [cache/l2-spec.md](../cache/l2-spec.md) §6.6, §20.1 | per-thread line-lock qualification generalised from 2 to 4 threads; L1-D↔MSHR interface contract; ×4 stride tables; EBR allocation revisited |
| 7 | [mmu/hardware-spec.md](../mmu/hardware-spec.md) §2.1a, §4 | scoped addition: on FGMT implementations `ASIDR` is per-TC and TLB compare selects by TC_ID (§11). Not a rewrite of the single-context definition |
| 8 | [fgmt/dual-fgmt-proposal.md](../fgmt/dual-fgmt-proposal.md), [fgmt/mt2x2-plan.md](../fgmt/mt2x2-plan.md) | pointer note: these are the J2-line `N_TC=2` documents; J32-LT is the 4-way OOO-line target |

---

## 14. Open decisions and fallbacks

0. **Single-thread IPC (§2.5) — decide before P1.** Options A (accept ~0.45 and amend §1.1(3)), B (barrel compaction, `⌈4/k⌉`-deep standby queue), C (`k=1` mode bit). Unresolved; this is the highest-priority open item in the document.
1. **If G1 misses (aggregate IPC < 1.5)** — the documented lever is **hybrid slot fill**: when the selected thread's second slot would go empty, fill it from the next ready thread. Operands are then guaranteed independent (different register namespaces), so no cross-slot dependency check is needed at all — it is the cheapest possible route to a higher `E[width]`. **This is SMT by [glossary §4/§9](../glossary.md) and adopting it requires amending the glossary and extending the prior-art set** (Tullsen, Eggers & Levy 1995 is the citation and is pre-2006, so the policy in [glossary §2](../glossary.md) is satisfied; the naming policy is the obstacle, not patent freedom). Recorded here deliberately rather than adopted, so that the measurement decides.
2. **`BT/S`/`BF/S` fusion** — deferred (§4.2). Requires the fused uop to carry delay-slot state. Worth revisiting if `FUSION_HITS` shows the non-delayed forms are a small fraction of dynamic conditional branches.
3. **ROB partition depth** — 8 is a projection from the in-order in-flight window. `ROB_FULL_STALL_CYCLES` per partition is the tuning signal; a long-latency L2 miss with non-blocking loads is the case that wants more.
4. **Thread count** — 4 matches the front-end depth exactly, which is what makes the barrel tag-free (§3.1). Changing the pipeline depth ahead of ISS breaks that 1:1 property and reintroduces an arbiter. Any future stage addition must either add a thread or accept the arbiter.
5. **`MOVMU.L`/`MOVML.L` cracking** — up to 17 uops, and §4.1 makes them occupy a bundle alone. On code that uses them for prologue/epilogue this may be a measurable IPC cost; see [isa-density/hardware-impl.md §6](../isa-density/hardware-impl.md).
6. **Way prediction in L1-I/L1-D** — 5–10% energy win, 1–2% IPC cost. Deferred, but a more attractive trade here than on J32-OOO given the energy-first goal. Revisit after G4.
7. **L1 capacity under 4 threads** — if G5 fails, the preference order is associativity, then capacity, then way prediction. Cache partitioning per thread is explicitly rejected: it converts a shared-capacity advantage into a fixed one.
8. **Software-exposed thread priority** — not provided (§1.2). The two automatic cases cover the dominant scenarios.
9. **Dual-core J32-LT** — 8 logical CPUs, MSI coherence per [cache/l2-spec.md §7](../cache/l2-spec.md). Not specified here; the AIC2 change in §13 item 3 is the prerequisite.

---

## 15. Implementation phasing

| Phase | Content | Est. |
|---|---|---|
| P0 | **Trace-driven model**: bundle/barrel/pairing/fusion model over `sim/sh2instr.c` traces. Produces `E[width]` and the G1/G3 answer before any RTL exists. **Go/no-go gate.** | 1 mo |
| P1 | Single-thread core: 10-stage pipeline, future-file RAT, 8-entry ROB, in-order dual issue, 1 ALU + 1 LSU | 4 mo |
| P2 | Second ALU pipe, PAIR stage, pairing rules, T-tracking | 2 mo |
| P3 | gshare + BTFNT seeding, BTB, RAS, delayed-branch handling, squash restore | 2 mo |
| P4 | Fusion (§4.2) | 1 mo |
| P5 | Per-thread LSQ, MSHRs, non-blocking loads | 2 mo |
| P6 | Barrel FGMT ×4: contexts, standby registers, barrel counter + masking, per-thread ASIDR | 3 mo |
| P7 | Atomic groups (CAS.L), L2 line lock, 4-thread qualification | 1.5 mo |
| P8 | Cache hierarchy ×4-thread tuning, prefetchers | 1.5 mo |
| P9 | PMU ×4 + Linux driver, incl. the four new events | 1.5 mo |
| P10 | Auto-priority (CAS spin, SLEEP) | 0.5 mo |
| P11 | Verification, Linux boot as 4 CPUs, G1–G7 | 3 mo |
| P12 | ULX3S 85F bring-up | 2 mo |

**Total ~25 months.** P0 is deliberately first and deliberately cheap: §2.4's IPC projection is the load-bearing assumption of the entire design, it is analytically tractable, and discovering it is wrong after P6 would be expensive.

---

## Appendix A: What is deleted relative to J32-OOO

| Structure | J32-OOO size | Reason it is gone |
|---|---|---|
| Issue queue | 16 entries, 2 CAMs/entry, 3 broadcast tags/cycle | in-order issue |
| IQ collapse shift register | 16 entries, all fields | no IQ |
| Physical register file | — | future-file: values live in the ROB |
| Free list | — | no physical registers to allocate |
| Rename-map checkpoints | 8 × 23 × 6 b **per thread** | §5.4 history buffer instead |
| SSIT | 1024 entries | §7.3: no address speculation possible |
| LFST | 64 entries | §7.3 |
| Bimodal PHT | 1024 × 2 b | gshare alone (§3.5) |
| Chooser PHT | 1024 × 2 b | gshare alone (§3.5) |
| Ready-thread arbiter | priority computation/cycle | barrel counter (§3.1) |
| Front-end thread tags | per stage | positional (§3.1) |
| Cross-thread LSQ ID compare | per forward | partitioned LSQ (§7.1) |
| Fetch alignment rotator | — | 32-bit aligned bundles (§3.3) |
| Decode-buffer compaction | — | non-collapsing bundles (§3.3) |

## Appendix B: Glossary additions

- **Barrel** — front end in which thread count equals stage depth, so each stage holds a different thread each cycle and thread identity is positional rather than tagged. CDC 6600 PPU (1964).
- **Bundle** — the two 16-bit instructions at a 32-bit-aligned address, fetched, decoded, paired, and issued as a unit. Does not collapse.
- **BTFNT** — Backward-Taken / Forward-Not-Taken. Static branch direction heuristic, here used to seed gshare counters at BTB allocation rather than as a standalone predictor.
- **`E[width]`** — average architectural instructions retired per issuing cycle. The quantity §2.4's IPC projection turns on.
- **Future-file** — a register-status table mapping architectural registers to in-flight producers, with results held in the ROB until commit. Not renaming: it expands no name space.
- **PAIR** — pipeline stage between DEC and ISS that performs fusion detection, pairing legality, and slot steering.
- **Standby register** — one-deep per-thread raw-bundle buffer that catches the barrel follower when an issue bundle fails to drain.
- **Split bundle** — a bundle that issues its two slots in two separate cycles because dual-issue was illegal or an operand was not ready.
