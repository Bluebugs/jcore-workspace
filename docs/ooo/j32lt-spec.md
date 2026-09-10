# J32-LT — Light Out-of-Order, 4-Way Barrel-FGMT J-Core Specification

**Status:** Draft v0.3
**Compatible ISA:** J32 baseline (SH-2 + J-core extensions: SHAD, SHLD, CAS.L) + MMU
**Scope:** CPU core front end, issue, memory pipeline, PMU. FPU, MMU, IOMMU/DMA, SIMD, crypto specified separately.

**J32-LT** is a 2-wide in-order-issue, out-of-order-completion core with **4-way barrel FGMT**, 32-bit datapath. It is a *sibling* of [J32-OOO](j32ooo-spec.md), not a replacement: J32-OOO buys single-thread latency with register renaming and a wakeup-select issue queue; J32-LT buys **throughput per joule** with thread count and deletes both structures. See [glossary §3–§4](../glossary.md) for product-point and threading naming.

> **This product point is not being built, and it is paused for a narrower
> reason than J32-OOO. Decision
> [0009](../decisions/0009-in-order-fgmt-is-the-default-path.md), 2026-09-08.**
> The default microarchitecture path is dual-issue in-order with **2-thread**
> switch-on-miss FGMT. Two of the three arguments in
> [j4-remediation-plan.md §E.1](../j4-remediation-plan.md) do not reach this
> design at all — issue is in-order here, and §1.2 already deletes the rename
> machinery and the issue-queue CAM that the area and energy arguments land on.
> What does reach it is the **barrel width** and §12.1's own finding: E.1's
> counter-evidence bullet reads Hölzle as arguing against a wide barrel (per-
> thread IPC must not collapse), and §12.1 records that this core is not smaller
> than J32-OOO, so it does not relieve the ECP5 fit problem either.
>
> **The consequence is the opposite of a demotion for most of this document.**
> 0009 D2 records that the front end, the PAIR stage and the pairing rules of §3
> and §4 are the *nearest existing description of the default path*, and that
> the spec the default path needs should be derived from them — at 2 contexts
> with switch-on-miss selection instead of a 4-way barrel, and with §6.3's ROB
> re-opened, since 40,000 gates of ROB was budgeted against four threads' worth
> of in-flight work rather than two. §15's **P0** trace model is likewise the
> instrument 0009 D3 names for settling the question against OoO.
>
> Nothing here is superseded or wrong, which is why there is no
> [0002](../decisions/0002-supersede-convention.md) marker: that grammar has no
> form for "correct, and not currently being implemented".

---

## 1. Goals and non-goals

### 1.1 Goals

1. **Energy efficiency first.** Minimise dynamic activity per committed instruction. Every structure in [j32ooo-spec](j32ooo-spec.md) that performs an associative search, a multi-way array read, or a speculative table lookup on every cycle or every memory op is either deleted or reduced to a single direct-mapped access.
2. **Aggregate IPC ≥ 1.5** architectural instructions retired per core cycle with 4 runnable threads (§2.4 derives the expected ~1.55).
3. **Single-thread floor:** with one thread runnable, IPC must be no worse than the in-order J32 baseline (~0.7–0.85). Latency-sensitive workloads must not pay for the thread count. Met by the barrel period floor of §2.5, which yields ~0.94.
4. Preserve precise exceptions per thread, the J32 MMU model, and CAS.L semantics with no architecturally visible changes.
5. Present to Linux as 4 logical CPUs per core.
6. **Transient-execution security at a cost the barrel absorbs (§16).** In-order *issue* is not a defence — this core predicts branches and issues non-blocking loads past them (§7.4), which is a complete Spectre-v1 gadget. What the barrel does provide is that the standard stall-based defence, normally rejected as too expensive, costs this design point far less than any other (§7.4a). That is a second claim alongside throughput per joule, and §12.2 gate G8 tests it.

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
| Speculative store bypass (v4) | present, needs `SSBD` | structurally absent (§7.3) |
| Cost of delay-on-miss (§7.4a) | absorbed by 2 contexts | absorbed by 4 |
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
| Address-space-tagged lookup state | MIPS R4000 ASID-tagged TLB 1991; SH-4 hardware manual 1998 |
| Withholding a memory access until speculation resolves | Intel US6035393 (priority 1995, expired); Farkas & Jouppi 1994 |
| Deferred-exception token on a speculative load | IA-64 control speculation `ld.s`/NaT/`chk.s` (Itanium 1999–2001) |
| Serializing / speculation-barrier instruction | PowerPC `isync`; SPARC v9 `MEMBAR #Sync` (1994) |
| Invalidate-array control bit | SH-4 `CCR.ICI` / `CCR.OCI` (1998) |
| Shared-cache leakage between hardware threads | Percival, *Cache Missing for Fun and Profit*, BSDCan 2005; Kocher 1996 |

Nothing in this document requires a post-2005 citation. That includes §16 — the security section was written under the same constraint, and §16.7 records the two mechanisms that had to be rejected because they could not meet it.

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
      4 threads, 4 stages, 1:1 at k=4
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

### 2.5 Single-thread behaviour — the barrel period floor

The arithmetic of §2.4 runs the other way when threads are idle. With **one** runnable thread under an unmodified barrel and one bundle in flight, the thread reaches ISS once every 4 cycles and cannot refetch until that bundle drains, retiring 2 architectural instructions per 4–5 cycles: **~0.47 IPC**, against a ~0.7–0.85 in-order J32 baseline. Goal §1.1(3) would be violated by roughly a factor of two.

The binding constraint is **fetch rate, not issue width**. Even at a perfect `E[width]` of 2.0, a bundle arriving every 4 cycles caps throughput at 0.5. Fusion, pairing rules, and the second ALU cannot move this number. The only lever is bundle period.

**Mechanism.** With *k* ready threads, thread selection uses a period of `max(k, 2)` rather than `k`. A thread may hold up to `⌈4 / max(k,2)⌉` bundles in flight, so the standby queue (§3.2) is **2 deep**.

Modelling as in §2.4 — ~13% of instructions are taken branches, so ~26% of 2-instruction bundles are entered mid-bundle at 0.5 dead slots each, giving **1.87 effective instructions per bundle**:

| *k* | Period | Aggregate IPC | Single-thread IPC |
|---|---|---|---|
| 4 | 4 (floor inactive) | 1.55 | — |
| 3 | 3 (floor inactive) | 1.55 | — |
| 2 | 2 | 1.55 (port still saturated) | — |
| **1** | **2** | — | **0.94** |

The floor never binds at *k* = 3 or 4, so **the primary aggregate target of §2.4 is unaffected**. Only the idle-thread cases change, which is exactly the intent.

**Cost.**

| Item | Cost |
|---|---|
| Standby buffer 1-deep → 2-deep queue | 71 b × 2 × 4 threads ≈ **568 FFs** (up from 284) |
| Per-stage `valid` + TC_ID | 4 stages × 3 b = **12 FFs** |
| Selection: mod-4 counter → ready-mask priority encoder with period floor | **~150 gates** |
| Squash: clear up to 2 in-flight bundles per thread instead of 1 | wider valid-clear, no new structure |

≈ 300 additional flip-flops and ~150 gates against ~220,000. What made the strict barrel cheap was eliminating *arbitration*, not tags; the tags themselves are 12 flip-flops.

**What is given up.** The clean invariant "stage occupant = `(cycle − depth) mod 4`" of §3.1 no longer holds unconditionally — it holds only while *k* = 4. Below that, stage identity is explicit. This is a real loss for reasoning about the design and for the verification argument in §12.3(2), but it is not a material area or energy cost.

**Alternative considered and rejected: a 4-instruction (64-bit aligned) bundle.** Period stays 4, positional identity survives, single-bundle-in-flight survives, and I-cache reads per instruction halve — a genuine energy win. But a 4-instruction bundle entered mid-bundle wastes 1.5 slots on average instead of 0.5, and at that size ~half of all bundles are branch targets, landing single-thread IPC at **~0.81**. It also costs two more decoders (~+18,000 gates, an order of magnitude more than the period floor). Better energy story, worse answer. Revisit only if G4 fails and I-cache fetch energy is identified as the dominant term.

---

## 3. Barrel front end

### 3.1 The barrel

Four thread contexts, four front-end stages ahead of ISS. At *k* = 4, thread *T* launches a fetch at IF1 on cycles where `cycle mod 4 == T`; its bundle advances one stage per cycle and arrives at ISS exactly four cycles later — precisely when it is *T*'s turn again.

```
cycle:      0     1     2     3     4     5     6     7
IF1:       T0    T1    T2    T3    T0    T1    T2    T3
IF2:        –    T0    T1    T2    T3    T0    T1    T2
DEC:        –     –    T0    T1    T2    T3    T0    T1
PAIR:       –     –     –    T0    T1    T2    T3    T0
ISS:        –     –     –     –    T0    T1    T2    T3
```

Consequences, all of them savings:

- **No IF1 arbiter in the J32-OOO sense.** Thread selection is a small ready-mask priority encoder with a period floor (§2.5), not the ready-thread priority computation of [j32ooo-spec §13.2](j32ooo-spec.md). At *k* = 4 it degenerates to a free-running 2-bit counter.
- **Near-free thread identity.** While *k* = 4, a stage's occupant is exactly `(cycle − stage_depth) mod 4` and needs no storage. Below *k* = 4 the period floor breaks that identity and each stage carries an explicit `valid` + 2-bit TC_ID — 12 flip-flops total (§2.5).
- **No cross-thread structural hazard in IF1–PAIR.** Each stage holds at most one thread's bundle each cycle, by construction, at every value of *k*.

**Selection rule.** Thread *T* is granted an IF1 slot no more often than once every `max(k, 2)` cycles, where *k* is the number of unmasked threads (§9.3). At *k* ≥ 2 this is plain round-robin over the ready set; at *k* = 1 the floor holds the single thread to alternate cycles, which is what bounds the standby queue at 2 deep.

Prior art: CDC 6600 peripheral processors (Thornton 1964) are this structure — 10 threads, 10-deep barrel, one stage per thread. Denelcor HEP (1978) and Tera MTA (1990) generalise it; the period floor is the Alewife-style departure from a pure barrel for the low-thread case (Agarwal et al. 1993).

### 3.2 Standby queue

Two mechanisms need a landing pad between IF2 and ISS:

1. A pure barrel assumes a bundle at ISS always drains. When it does not — an operand is not ready, an FU is busy, or the bundle splits across two cycles (§3.4) — the follower arriving from PAIR has nowhere to go.
2. The period floor of §2.5 lets a thread hold up to `⌈4 / max(k,2)⌉` = **2** bundles in flight at *k* = 1.

J32-LT therefore places a **2-deep standby queue per thread** after IF2, holding **raw** bundle state:

| Field | Width |
|---|---|
| instruction pair | 32 b |
| bundle PC | 32 b |
| slot-0 valid (mid-bundle target kill) | 1 b |
| prediction outcome + BTB/RAS sideband | ~5 b |
| valid | 1 b |

≈ 71 bits × 2 entries × 4 threads ≈ **568 flip-flops**. Holding raw (undecoded) bundles rather than decoded control fields is what keeps this narrow; the cost is that a promoted standby bundle re-traverses DEC and PAIR, which is free because those stages would otherwise be idle in that thread's barrel slot.

When a thread's ISS bundle fails to drain, its follower parks in the queue and the barrel keeps turning for the other threads. When a thread's queue is full *and* its ISS bundle is still stuck, that thread's next barrel slot goes unused — the degradation is confined to the stalling thread.

The queue depth is set by the period floor, not by the stall case: 2 is exactly what *k* = 1 requires, and it happens to give the stall case one entry of slack at every *k*. There is no separate sizing argument.

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
| gshare PHT | 1024 × 2-bit counters | `PC[10:1] XOR GHR[9:0] XOR DOM` |
| GHR | 10 b × 4 threads | per-thread, speculative + committed copy |
| BTB | 32-entry, 4-way SA | PC tag + full `DOM` tag |
| RAS | 8 entries × 4 threads | per-thread, mandatory; each entry carries its push-time `DOM` |

```
DOM = { PDID[5:0], SR.HPRIV, SR.MD, TC_ID[1:0] }      -- 10 bits
```

`DOM` is the *security domain* identifier of [j32ooo-spec §3.2](j32ooo-spec.md), not the thread ID alone. Four contexts smeared over a single 1024-entry table by a 2-bit tag is not isolation; `{tid,tid}` in an earlier draft of this table let any thread place a counter at any other thread's index. `PDID` is the hyperprivileged predictor-domain register of [j32ooo-spec §20.10](j32ooo-spec.md); `SR.HPRIV` is a separate hardware term so that a hypervisor which fails to update `PDID` still cannot share a domain with its guest. A BTB domain mismatch is a miss. A RAS pop whose entry `DOM` does not match the current domain is discarded in favour of the BTB — which is what closes the return-stack transient path (§16.2).

**All four structures update from committed instructions only, indexed by the committing instruction's `DOM`** — the value captured at ISS and carried in its ROB entry (§6.3), never the live register value at write time. Commit-only training alone is insufficient: an instruction retiring in the same window as a world switch would otherwise train the domain it is leaving into the domain it is entering, which is the Branch Privilege Injection race (§16.2). The GHR's committed copy already exists for squash repair and does double duty as the mechanism that keeps a squashed path from training the table.

**BTFNT seeding.** On BTB allocation the corresponding PHT counter is initialised to the static backward-taken/forward-not-taken direction — backward branch → weakly taken (`10`), forward branch → weakly not taken (`01`) — rather than to a neutral or zero value. Cold-start accuracy approaches the static heuristic (~65–70% on typical code) instead of coin-flip, and the counter trains away from it wherever dynamic behaviour disagrees.

Relative to [j32ooo-spec §3.2](j32ooo-spec.md) this **deletes the 1024-entry bimodal table and the 1024-entry chooser table**, taking predictor array reads from three per prediction to one. On a structure accessed every fetch cycle this is one of the largest single energy items in the front end.

Per-thread RAS is not optional: a shared RAS is corrupted by interleaved call/return streams from four threads, and the corruption is silent.

**Note on BTFNT seeding and §16.** A documented, deterministic initial counter state removes the predictor-training instability that the [CARRV 2019 BOOM authors](https://boom-core.org/docs/replicating_mitigating_spectre_carrv19.pdf) had to work around to make their attacks reliable — an attacker knows the state of a freshly allocated entry. This is not a reason to change the seeding, which is the right performance call and worth ~65–70% cold accuracy; predictor-state secrecy was never a defence and §16 does not rely on it. It is recorded so the trade is explicit.

### 3.6 Delayed branch handling

SH delayed branches (`BRA`, `BSR`, `JMP`, `JSR`, `RTS`, `BT/S`, `BF/S`, `BRAF`, `BSRF`, `RTE`) carry one delay slot, which executes whether or not the branch is taken.

- **Branch in slot 0**: its delay slot is slot 1 of the same bundle. Guaranteed dual-issue pair (§2.4 item 1).
- **Branch in slot 1**: its delay slot is slot 0 of the *next* bundle. The branch issues, but the pair is tagged `DELAY_BRANCH` / `DELAY_SLOT` and commit is held until both are complete. Fetch redirection to the predicted target happens after the delay-slot bundle is fetched, exactly as in [j32ooo-spec §3.3](j32ooo-spec.md).
- **Mispredict**: squash everything in the thread's ROB *after* the delay slot. The delay slot itself is architecturally executed and must not be squashed.

### 3.7 Misprediction penalty

7 cycles raw (redirect at EX, refill IF1→ISS through the barrel). At *k* = 4 this is **1.75 of the mispredicting thread's own issue opportunities** — the other three threads occupy the intervening cycles and lose nothing, so the throughput cost is roughly a quarter of the latency cost. This is the main reason a single gshare table suffices here where a tournament predictor was specified for J32-OOO.

The relief shrinks as *k* falls. At *k* = 1 with the period floor, 7 raw cycles are ~3.5 issue opportunities and there is no other thread to absorb them, so single-thread performance is materially more predictor-sensitive than aggregate performance. If G2 (§12.2) comes in below expectation, predictor accuracy — not the period floor — is the first thing to examine.

---

## 4. Decode and PAIR

### 4.1 Decode

Two independent decoders, one per slot. Multi-uop instructions crack here, per [j32ooo-spec §4.1](j32ooo-spec.md): `MAC.L`/`MAC.W` → 4, `RTE` → 3, `CAS.L` → 3, `TRAPA` → 4+, `LDS.L @Rm+` → 2, `MOVMU.L`/`MOVML.L` → 1–17.

**`SPB`, the speculation barrier** ([j32ooo-spec §4.6](j32ooo-spec.md)), is architecturally identical here: no instruction younger than `SPB` executes until `SPB` retires. It is serializing per §4.3 rule 6, so it occupies its bundle alone and the thread's other three barrel slots continue to turn. Software needs it — without a barrier, neither `__builtin_speculation_safe_value` nor any index-masking idiom has a lowering target (§16.6).

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
6. Neither slot is serializing (`LDC Rm,SR`, `LDC.L @Rm+,SR`, `LDC Rm,VBR`, `TRAPA`, `SPB`, `HCALL`, `HRTE`, any `LDC` to a hyperprivileged register).
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
| `dom` | 10 b | security domain captured at ISS (§3.5); indexes predictor updates at commit and selects the translation regime for memory ops (§6.6 rules 4–5) |
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

1. Flush that thread's ROB partition, LQ, SQ, standby queue, and barrel-resident bundles.
2. Restore that thread's RAT via the §5.4 history walk.
3. Set `SR.BL`, save `SPC`/`SSR`, vector through `VBR`.

The other three threads are entirely unaffected — they share no front-end stage state with the excepting thread beyond the selection logic, which holds no per-thread architectural state.

### 6.6 Squash and fault rules the security model depends on

Precise-per-thread is an *architectural* property and says nothing about what a squashed or faulting instruction leaves behind microarchitecturally. Three rules, stated here rather than implied:

1. **A squash cancels microarchitectural work.** Beyond §6.5, it deallocates MSHRs held by squashed loads whose fills have not returned and cancels prefetches generated by squashed loads **and by squashed fetches** (§7.5a). Without this, §7.4a leaks through the MSHR and prefetch paths. *(Widened 2026-09-09, Wave-3 C2b, for the reason given in [j32ooo-spec.md §9.4](j32ooo-spec.md) rule 1.)*
2. **No structure is trained by a squashed instruction** — gshare, BTB, RAS and the stride tables update at commit only (§3.5, §7.5a).
3. **Permission-resolved forwarding.** A load may not forward a value to a dependent uop until its translation and permission check has resolved; a faulting load forwards **poison**, and a uop consuming poison produces poison and may not use it to form an address or a branch condition. Poison is discarded at squash and raises at commit per §6.5. This keeps a permission-failing load from feeding a transient address once the MMU (§11) is integrated, and it belongs in this document because forwarding is this pipeline's business. Prior art: IA-64 `ld.s`/NaT/`chk.s` deferred-exception tokens (1999–2001); and plain SH-4 discipline, where the permission check is part of the load's execution rather than a commit-time afterthought.
4. **No cache lookup on an unresolved physical address.** No L1 or L2 tag comparison, fill or validation may proceed with a physical address that is not the output of a completed and permitted translation — in particular, an access whose walk is still in flight does not present a partially-formed `pa_tag` to a PIPT cache ([../mmu/hardware-spec.md §4.1a](../mmu/hardware-spec.md)). This is the L1-Terminal-Fault shape, and J-Core has met it: an I-side fetch reaching the PIPT I-cache with an undefined `pa_tag` during a walk was tagged and validated at MISS1, yielding silent wrong instructions. Fixed on the I-side, measured clear on the D-side — but the rule was in no specification, so nothing stopped a new pipeline reintroducing it.
5. **Every memory access carries its own instruction's `SR.HPRIV`/`SR.MD` snapshot**, taken at ISS, and selects its translation regime from it. A pending change to either makes younger accesses non-speculative. Violating this is not a leak: under [hypervisor/hardware-spec.md §4.4.1](../hypervisor/hardware-spec.md) a guest's P1 is translated while a hypervisor's P1 is *folded* to a physical address with no permission check, so an access under a stale `HPRIV` reads host memory directly ([j32ooo-spec §20.11](j32ooo-spec.md)).

**`HCALL` and `HRTE` are serializing** (§4.3 rule 6). Beyond the mode change, `HRTE` carries the complete-on-resume writeback of [hypervisor/hardware-spec.md §4.5](../hypervisor/hardware-spec.md) rule 2: hardware writes `HMDR` into the register named by `HMCR.REGN`/`BANK`. On this core that write is performed **at `HRTE`'s commit**, into the thread's ARF, resetting that register's RAT entry to `IN_ARF`. An out-of-band ARF write while the RAT still points the register at an in-flight ROB entry would be silently lost — §5.1's future-file is exactly the structure the hypervisor spec's writeback port does not know about.

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

**This is also a security property, not only an area one.** Speculative store bypass is the v4 transient-execution path, and it exists on [j32ooo-spec §8.4](j32ooo-spec.md) precisely because that core speculates on store addresses; that spec therefore needs an `SSBD` control bit to turn the mechanism off. J32-LT has nothing to disable — the path is structurally absent, for the same reason the predictor is. It is the one place where this design point is unambiguously safer than its sibling, and it costs nothing to claim because it was already true (§16.2).

### 7.4 MSHRs — 2 demand + 1 prefetch per thread

Non-blocking loads still pay off under in-order issue, because a thread stalls only at the first instruction that *consumes* a missing load. Independent younger loads and all younger stores continue to issue past a miss.

| MSHR pool | Count | Purpose |
|---|---|---|
| Per-thread L1-D | 2 × 4 = 8 | demand misses |
| Per-thread prefetch | 1 × 4 = 4 | stride and next-line prefetch fills |

Per-thread allocation, rather than a shared pool, guarantees that one thread's miss burst cannot starve another thread's demand miss — the same isolation argument as the partitioned ROB and LSQ, and the reason the whole design partitions per thread wherever the structure is small. The prefetch MSHRs are per-thread for the same reason and for one more: a shared, contended, 2-entry structure in an otherwise fully partitioned memory pipeline is a cross-thread timing channel, and it was the one inconsistency in this section (§16.3).

Prior art: Kroft 1981 (lockup-free cache with MSHRs); Farkas & Jouppi 1994 (non-blocking loads on in-order pipelines).

### 7.4a Delay-on-miss

**A load that misses in the L1-D while still speculative does not issue to the L2 or to memory.** It holds its LQ entry until every older branch in its thread has resolved and no older instruction can except, then issues the miss normally. L1-D hits proceed speculatively at full speed and are unaffected.

The rule is a condition on MSHR allocation — a speculative miss does not allocate — and nothing else. No filter buffer, no shadow cache, no promotion logic, no rollback. Area is ~400 gates. What it buys: no fill, no L2 lookup, no allocation-time replacement-metadata update and no coherence traffic is ever caused by a load that **misses** and does not commit — the fill/allocation half of the cache covert channel, at every level of the hierarchy at once (§16.2).

**Scoped 2026-09-09, Wave-3 C2b.** The sentence above previously ended *"is ever caused by a load that does not commit, which closes the cache covert channel at every level of the hierarchy at once"*, which contradicted its own preceding sentence: speculative hits are unaffected, §7.5 makes both L1s pseudo-LRU, and a hitting load that never commits therefore does update replacement metadata. It was also a completeness claim of the kind [../security/threat-model.md §7.3](../security/threat-model.md) strikes. The full derivation, the one mechanism that would close the hit-time channel, and the reason no figure is available to price it are in [j32ooo-spec.md §8.2a](j32ooo-spec.md), which owns this rule; this design point inherits both the rule and its scope.

**Why this is the right design point for this mechanism, and the strongest form of the §3.7 argument.** Delay-on-miss is normally rejected as too expensive: it converts a speculative miss into a serialized one, and on a single-threaded or 2-way machine the core simply stalls. Here §3.7's arithmetic applies unchanged. A delayed load costs its own thread real time, but the other three threads occupy the intervening cycles and lose nothing, so the *aggregate* cost is roughly a quarter of the per-thread cost. The cheapest strong defence in the literature is close to free on a 4-way barrel, for exactly the reason the barrel was chosen in the first place.

This is a projection, and §12.2 gate **G8** makes it falsifiable. Non-blocking loads (§7.4) are what make it survivable: a thread stalls only at the instruction that *consumes* the delayed load, so independent younger work continues to issue.

**Prior art:** Intel **US6035393** (Glew & Gupta, priority 1995-09-11, **expired**), claim 1 — stall prefetching "until either the dummy instruction retires, or a misprediction of a previous branch is detected". Withholding a memory access made on behalf of a speculative instruction until the speculation resolves, claimed in 1995. The motivation there was avoiding side effects on uncacheable MMIO; the mechanism is this one. Sakalis & Kaxiras (2019) supply only the security framing. §7.4b is the case where that motivation applies to us word for word.

### 7.4b Non-speculative regions

Delay-on-miss delays L1-D **misses**. Device space is uncacheable, so a load to it never allocates and §7.4a never engages. A second, stronger rule covers it:

> An access whose translated physical address lies in **P4**, in the **emulation aperture** (`(PA & HEMUM) == HEMUB`, [hypervisor/hardware-spec.md §2.5](../hypervisor/hardware-spec.md)), or in a page mapped **uncacheable** (`PTEL.C = 0`) is **never issued speculatively**, hit or miss. It waits at its LQ/SQ entry until it is the oldest un-retired access of its thread.

It closes three things §7.4a does not reach: a speculative load of a device register is a real read with real side effects; a squashed aperture match would otherwise write `HPAR`/`HMCR`/`HMDR`, corrupting the capture registers a genuine trap is about to consume and handing the hypervisor's device model an address the guest never accessed; and timing a squashed aperture hit would disclose the hypervisor's device-model layout.

**Prefetchers never enter these regions.** A prefetch whose target translates into P4, the aperture, or an uncacheable page is **dropped silently** — not issued, never a trap source. §7.5a's page-boundary rule does not imply this: P4 starts on a page boundary like any other, and a legitimate upward stride reaches it.

In-order issue makes the wait cheaper here than on [j32ooo-spec §8.2b](j32ooo-spec.md): the access is already near the head of its thread's window, and the barrel gives the other three threads the cycles. ~300 gates.

### 7.5 Cache hierarchy

Inherited from [j32ooo-spec §11](j32ooo-spec.md) and [cache/l2-spec.md](../cache/l2-spec.md) with the thread count raised to 4:

| Structure | Parameter |
|---|---|
| L1-I | 32 KB, 4-way SA, 32 B lines, pseudo-LRU, next-line prefetch |
| L1-D | 32 KB, 4-way SA, 32 B lines, write-through, write-allocate, pseudo-LRU |
| L2 | 128 KB unified, 8-way SA, write-back, inclusive |
| Stride prefetcher | 8-entry table **× 4 threads** |

### 7.5a Prefetcher constraints

Trained by **committed** loads only (§6.6 rule 2); prefetches **never cross a page boundary** (stream buffers have stopped at page boundaries since Jouppi 1990, here also bounding what a mistrained stride can touch); prefetches into P4, the emulation aperture or an uncacheable page are **dropped silently** (§7.4b); per-thread disable bit; and the table is cleared by the predictor-invalidate control of §16.4.

**The next-line L1-I prefetcher does not obey the same rules, and this sentence used to say it did.** *(Corrected 2026-09-09, Wave-3 C2b.)* It has no table, no confidence counter and no history, so "trained by committed loads only" is **vacuous** for it rather than satisfied — a rule stated against a property the structure does not have, which reads as coverage and is not. What it does obey is the page-boundary and region rules above, plus the rule that reaches the gap: **a next-line prefetch may be issued only on behalf of a fetch that has dispatched**, and one outstanding on behalf of a squashed fetch is cancelled with its MSHR deallocated (§6.6 rule 1). The derivation, the cost of the lost lead time, and the wrong-path *demand* fill that stays an accepted residual are in [j32ooo-spec.md §11.1a](j32ooo-spec.md), which owns the structure this design point inherits.

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

A parked or lock-spinning thread is removed from the ready set, so *k* drops and the remaining threads are selected more often, subject to the period floor of §2.5. A thread spinning on a contended CAS.L therefore hands its barrel slots to the lock holder rather than burning them on failed retries — which is the whole point of the auto-priority mechanism, and it composes with the floor at no extra cost.

The floor is what stops this from degenerating: without it, four threads collapsing to one would leave the survivor at 0.47 IPC.

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
| Standby queue (2 × 71 b) | 18 B |
| `ASIDR` (16 b `ASID_TAG`) + `PDID` (6 b) | 3 B |
| Auto-priority state (`last_cas_pc`, `cas_fail_count`, `prio_dropped`, `parked`) | 5 B |
| MMU fault state (§11: `PTEH`, `TSBPTR`, `TEA`, `MMUFSR`, `PTEL`, `EXPEVT`, `SPC`, `SSR`) | 32 B |
| Hypervisor context (§16.12: `SR.HPRIV`, `HSPC`, `HSSR`, `VBR_HYP`, `HEDR`, `HEMUB`, `HEMUM`, `HPAR`, `HMDR`, `HMCR`, `HSQCR`) | 42 B |
| **Store queue — the 72-byte store-queue image of [../sq/spec.md §7.2](../sq/spec.md); §16.12: two 32 B buffers + `QACR0`/`QACR1`** | **72 B** |
| **Per thread** | **~318 B** |
| **Four threads** | **~1,272 B** |

Still fits in distributed RAM and flip-flops, but note the growth: the last three rows are ~146 B per thread, and at four threads they are the largest single block of per-context state in the design. They exist because **anything the hypervisor and MMU specifications call "per-vCPU" or "per-CPU" is per thread context here** — four vCPUs are resident concurrently, so there is no exit at which a save/restore sequence could run. §16.12 gives the reasoning and the failure mode for each.

Note the absence of rename-map checkpoints, which at [j32ooo-spec §13.1](j32ooo-spec.md)'s 8 × 23 × 6 bits were 138 B per thread — the largest single item in the J32-OOO per-thread context and, at 4 threads, would have been 552 B on its own.

### 9.2 Resource sharing

| Resource | Model |
|---|---|
| IF1–PAIR (barrel) | one thread per stage per cycle; positional at *k*=4, explicit 3-bit tag below (§2.5) |
| Standby queue | per thread, 2 deep |
| RAT | per thread |
| ROB | **partitioned**, 8/thread |
| LQ / SQ | **partitioned**, 4+4/thread |
| MSHR | **partitioned**, 2 demand + 1 prefetch per thread (§7.4) |
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
| 0x19 | `SPEC_MISS_DELAY_CYCLES` | *new* — cycles loads spent waiting to become non-speculative (§7.4a). **The delay-on-miss cost meter; gate G8.** |
| 0x1A | `SPEC_MISS_DELAYED` | *new* — loads delayed at least one cycle by §7.4a |
| 0x1B | `PREDICTOR_INVALIDATES` | *new* — §16.4 control writes; proves the kernel hook fires |
| 0x1C | `RAS_DOMAIN_MISMATCH` | *new* — RAS pops discarded on domain mismatch (§3.5) |

The four `BUNDLE_SPLIT`/`SLOT0_KILLED`/`FUSION_HITS`/`BARREL_SLOT_IDLE` events exist specifically to make §2.4's IPC projection falsifiable on hardware; together the first three reconstruct `E[width]` directly. Events 0x19–0x1A do the same job for §7.4a's cost claim, which is the security section's equivalent load-bearing projection.

**Events 0x19–0x1C are cross-thread observable.** The PMU is privileged-only and `PMTID` must not be reachable from unprivileged code — see §16.3.

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

Everything else in the MMU spec — `PTEH` VPN-only, `ASID_TAG` ([../mmu/hardware-spec.md §2.1a](../mmu/hardware-spec.md); this line called it "generation-tagged", and the generation nibble was retired 2026-08-25), `STALE` enforcement, the TSB miss path, `LDTLB.RN` — is unaffected.

> **Correction: `ASIDR` is not the only per-thread MMU register.** The
> sentence above understates what FGMT requires. Four threads can have faults
> outstanding simultaneously, so the following are **per-fault** state and
> must be replicated per thread, not merely `ASIDR`:
>
> | register | per-thread? | if shared |
> |---|---|---|
> | `ASIDR` | ✅ specified above | — |
> | `PTEH` (VPN, hardware-set on miss) | **required** | thread B's miss overwrites the VPN thread A is about to `LDTLB` → wrong translation installed |
> | `TSBPTR` | **required** | thread A's handler reads thread B's TSB slot |
> | `TEA` | **required** | wrong fault address reported to `do_page_fault` |
> | `MMUFSR` | **required** | wrong fault cause |
> | `TSBBR` | **required** | only if threads may run different guests under a hypervisor; otherwise shared is fine |
> | `PTEL` | **required** for plain `LDTLB` | `LDTLB.RN Rm` sources `PTEL` from a GPR, which is already per-thread, so the hot path is already safe |
> | `EXPEVT`, `SPC`, `SSR` | **required** | implied by §6.5's "precise per thread" but not stated here |
> | `MMUCR`, `TTB`, `TSBCFG` | correctly shared | cold, set once at boot |
>
> **The same argument extends to the Phase 3 hypervisor register set** — see §16.12. Every
> register [hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md) describes as "per-vCPU,
> saved and restored across VM exit and entry" is per thread context here, because four vCPUs are
> resident at once and there is no exit to save at. That list includes the two 32-byte **store-queue
> buffers** and `QACR0`/`QACR1`, whose sharing is a cross-vCPU data-corruption bug with no
> speculation involved at all.
>
> Cost is roughly 6 registers × 3 extra copies (~600 flops against ~220k
> gates) — the same order as the period-floor cost §2.5 already accepts. The
> hazard if omitted is silent installation of cross-thread translations.
>
> **The hardware TSB walker ([../mmu/hardware-spec.md §5.0](../mmu/hardware-spec.md)
> — DESIGNED, partially implemented on J4, not shipped)
> reduces the exposure but does not remove it:** on a walker hit no
> architectural fault state is written at all, so only the walk-failure path
> needs the per-thread copies. It also changes the cost calculus in LT's
> favour — §3.7's argument that a redirect costs the faulting thread ~1.75 of
> its own issue opportunities while the other three lose nothing means the
> walker's benefit here is latency, not throughput.

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
| FGMT machinery (barrel + period floor, standby queues, per-thread state) | 17,000 | 13,450 | +3,550 |
| PMU ×4 threads | 14,000 | 9,500 | +4,500 |
| Security mechanisms (§16.5) | 15,200 | 8,400 | +6,800 |
| Misc (bypass, control, debug) | 17,000 | 17,000 | — |
| **Subtotal (core)** | **~235,200** | **230,350** | **+4,850** |
| Cache subsystem | 18,500 | 18,500 | — |
| **Total core + caches** | **~253,700** | **~248,850** | **+4,850** |

**J32-LT is not smaller than J32-OOO — and with virtualization in scope it is now measurably larger.** This is the single most important number in this document and it should not be buried: the design trades scheduler area for thread-context area, and the two roughly cancelled until §16.12 required four copies of the per-vCPU hypervisor register set and the store queue. Doubling the thread count consumed everything that deleting the issue queue, the rename machinery, the store-set predictor and two predictor tables gave back; quadrupling the per-context privileged state now costs ~4,850 gates beyond that. The energy-per-instruction argument (§12.1's activity table, gate G4) is unaffected — none of this state is read on a per-cycle path — but the "comparable area" framing of §1.3 no longer holds without the qualifier.

**The win is energy per instruction, not die area.** Per-cycle dynamic activity is where the two designs diverge:

| Per-cycle or per-op activity | J32-OOO | J32-LT |
|---|---|---|
| Predictor array reads per prediction | 3 (bimodal + gshare + chooser) | **1** |
| IQ tag comparisons per cycle | 16 × 2 × 6 b × 3 broadcast tags | **0** |
| IQ collapse shift per issue | 16-entry shift register, all fields | **0** |
| Register file read ports | PRF + ARF | **ARF only** |
| Memory-dependence lookups per memory op | SSIT + LFST | **0** |
| Rename checkpoint copies per branch | 23 × 6 b | **0** |
| Front-end arbitration per cycle | ready-thread priority computation | **ready-mask encoder; 2-bit counter at *k*=4** |
| Front-end thread tags per stage | yes | **12 FFs (positional at *k*=4)** |
| Wasted I$ reads | speculative fetch | speculative fetch (same) |

The claim this design makes is **throughput per joule at comparable area**, and §12.2 must test that claim directly, not merely test IPC.

### 12.2 Validation gates

Every number in §12.1 and §2.4 is an a-priori estimate. [j32ooo-spec §15.1](j32ooo-spec.md) already records that the gate-to-LUT4 conversion for this family is unvalidated and roughly 4× the [service plan §5](../jcore-ulx3s-service-plan.md) budget. J32-LT inherits that caveat in full and adds these gates:

| # | Gate | Measured how | Threshold |
|---|---|---|---|
| G1 | Aggregate IPC ≥ 1.5, 4 threads | CoreMark ×4 + PMU `PMINS`/`PMCYC` | ≥1.5; **stop and reconsider §14 if <1.4** |
| G2 | Single-thread IPC ≥ in-order J32 | CoreMark, 1 thread, others parked | ≥ baseline (~0.75); §2.5 projects 0.94 |
| G2b | Period floor active at *k*≤2 | PMU 0x18 `BARREL_SLOT_IDLE` vs *k* | idle slots ≈ 0 at *k*=1 |
| G3 | `E[width]` decomposition matches §2.4 | PMU 0x15/0x16/0x17 | model within ±0.1 |
| G4 | Energy per instruction < J32-OOO | post-synthesis power estimate, same workload | strictly lower — **this is the design's whole claim** |
| G5 | L1-D miss rate under 4-thread load | PMU 0x06/0x07 | within 1.5× of 1-thread rate |
| G6 | LUT4 + BRAM on ECP5 85F | synthesis | fits alongside SoC peripherals |
| G7 | Fmax vs in-order J32 | synthesis, ECP5-6 | no worse than −10% |
| G8 | **Delay-on-miss cost (§7.4a)** | PMU 0x19/0x1A + CoreMark ×4, SSH bulk crypto, JSON parse, at *k* = 1 and 4 | Aggregate IPC loss **<5% at *k*=4**; report the *k*=1 number, where the barrel gives no relief |
| S1 | v1, v2, RSB proof-of-concepts fail | `riscv-boom/boom-attacks` PoCs ported to SH-Compact, in cosim | secret not recovered above the noise floor |
| S2 | No speculative fill | RTL assertion: no L1/L2 tag, valid or replacement-state change attributable to a still-speculative load | zero violations across the regression |
| S3 | Cross-thread channel bounded | thread A attempts to observe thread B's secret-dependent access pattern via shared L1/TLB/gshare/BTB | measured and recorded, consistent with the §16.3 same-trust policy — not assumed zero |
| S4 | Negative controls | for each of S1–S3 and S5–S8, disable the mitigation or corrupt the expected constant and confirm the test **does** detect the leak | every security test proven non-vacuous |
| S5 | **Guest cannot train host or peer-guest predictions** | a guest trains an indirect branch at a hypervisor dispatch site's VA, and at a peer guest's; measure both mispredict rates with and without the training loop. Include a guest pair whose `ASID_TAG`s differ only above bit 7 | no measurable difference — the VMScape and truncation regressions |
| S6 | **No speculative device access** | RTL assertion: no bus request, no aperture comparison, no `HPAR`/`HMCR`/`HMDR` write for an access that is not the oldest un-retired access of its thread (§7.4b) | zero violations; capture registers unchanged after a squash |
| S7 | **Mode-snapshot invariant** | a guest access issued in the shadow of an unresolved `HRTE` (§6.6 rule 5) | no access resolves through P1 folding at `SR.HPRIV = 0` |
| S8 | **Store-queue context isolation** | four contexts running four vCPUs each fill SQ0 and burst (§16.12) | each burst contains exactly its own 32 bytes |

**G4 is the gate that matters.** If J32-LT is the same area as J32-OOO and does not clearly win on energy per instruction, the design has no reason to exist and the roadmap should carry J32-OOO alone.

**G8 is the second-most important number in this document**, because §1.1(6) and §7.4a claim that the barrel makes the standard strong defence affordable. If G8 fails at *k* = 4, that claim is wrong and §14 item 10 applies. It is trace-modellable alongside G1/G3 in P0 at almost no extra cost — the model already knows which loads miss and which branches are unresolved.

S4 is not optional. The MMU guard suite in this project once false-passed six sub-tests that had never executed; a security test that cannot fail is worse than no test, because it is believed.

G1 and G3 should be run in simulation against `sim/sh2instr.c` traces well before RTL exists — the bundle model, barrel timing, fusion rate, and pairing rules are all analytically tractable, and a trace-driven model is far cheaper than discovering at G1 that `E[width]` is 1.3.

### 12.3 Verification

1. **FU level**: reuse `tests/arith_tap.vhd` and the existing FU testbenches.
2. **Structural**: directed tests for the barrel — slot ownership at every *k* ∈ {1,2,3,4}, the period floor engaging as *k* drops through 2, transitions in both directions as threads park and unpark mid-stream, standby-queue promotion at both depths, mid-bundle target kill. The *k* transition is the highest-risk piece: it changes both the selection period and the number of a thread's in-flight bundles, and §2.5 trades away the positional invariant that would otherwise make it self-checking. Also PAIR (every cell of the §4.3 FU table, every fusion pattern in §4.2, intra-pair RAW on each implicit operand), RAT/ROB (squash restore across all 8 partition depths).
3. **Architectural**: `testrom/tests/*.s` against the core with 1, 2, and 4 threads active. CAS.L atomicity (`testmov.s:580–635`) is the atomic-group regression.
4. **Differential**: `sim/sh2instr.c` as the retirement oracle; mismatch at commit halts the simulation. This is the same methodology that found the four precise-exception defect classes during MMU M8, and it is the right tool for a machine whose whole correctness argument rests on in-order commit.
5. **Thread isolation**: four independent test programs concurrently; verify no cross-thread state corruption, particularly RAS, GHR, ASIDR, and LSQ forwarding.
6. **Stress**: Linux boot as 4 CPUs, Dhrystone, CoreMark, `stress-ng --futex`, LTP SMP subset, SSH bulk crypto, JSON parse.
7. **Security**: gates S1–S4 of §12.2, plus directed tests for `DOM` mismatch on BTB and RAS (§3.5), poison propagation and non-use as an address (§6.6 rule 3), squash-time MSHR and prefetch cancellation (§6.6 rule 1), and the invalidate control clearing all five arrays (§16.4).
8. **Regression against N_TC=1**: with a single thread configured at build time, results must match the in-order J32 path bit-for-bit — the same gate `fgmt/mt2x2-plan.md` §1 applies to the J2 line.

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
| 9 | [glossary.md](../glossary.md) §2 | two rules the prior-art policy needs for security mechanisms: prior art matches at the level of **mechanism, not motivation**; and a pre-2006 *structure* is necessary but not sufficient where the security-specific *combination* is separately claimed. See §16.7 |
| 10 | [glossary.md](../glossary.md) §4 | the FGMT definition should record that co-resident contexts are **one security domain** unless a product point says otherwise (§16.3) — it is a property of the threading model, not of this core |
| 11 | Linux port documentation | `switch_mm` must issue the predictor invalidate (§16.4); core-scheduling is required by §16.3; `SPB` and the invalidate control are gated on a CPU capability bit |

---

## 14. Open decisions and fallbacks

0. **Period floor value (§2.5) — resolved at 2, revisit only on measurement.** A floor of 2 buys ~0.94 single-thread for ~300 FFs. A floor of 1 (full compaction) would buy ~1.5 for a 4-deep standby queue (~1.1k FFs) and is the escalation if G2 proves single-thread performance matters more than projected. The floor is a parameter, not a structural choice — nothing else in the design depends on its value.
1. **If G1 misses (aggregate IPC < 1.5)** — the documented lever is **hybrid slot fill**: when the selected thread's second slot would go empty, fill it from the next ready thread. Operands are then guaranteed independent (different register namespaces), so no cross-slot dependency check is needed at all — it is the cheapest possible route to a higher `E[width]`. **This is SMT by [glossary §4/§9](../glossary.md) and adopting it requires amending the glossary and extending the prior-art set** (Tullsen, Eggers & Levy 1995 is the citation and is pre-2006, so the policy in [glossary §2](../glossary.md) is satisfied; the naming policy is the obstacle, not patent freedom). Recorded here deliberately rather than adopted, so that the measurement decides.
2. **`BT/S`/`BF/S` fusion** — deferred (§4.2). Requires the fused uop to carry delay-slot state. Worth revisiting if `FUSION_HITS` shows the non-delayed forms are a small fraction of dynamic conditional branches.
3. **ROB partition depth** — 8 is a projection from the in-order in-flight window. `ROB_FULL_STALL_CYCLES` per partition is the tuning signal; a long-latency L2 miss with non-blocking loads is the case that wants more.
4. **Thread count** — 4 matches the front-end depth exactly, which is what makes the barrel tag-free (§3.1). Changing the pipeline depth ahead of ISS breaks that 1:1 property and reintroduces an arbiter. Any future stage addition must either add a thread or accept the arbiter.
5. **`MOVMU.L`/`MOVML.L` cracking** — up to 17 uops, and §4.1 makes them occupy a bundle alone. On code that uses them for prologue/epilogue this may be a measurable IPC cost; see [isa-density/hardware-impl.md §6](../isa-density/hardware-impl.md).
6. **Way prediction in L1-I/L1-D** — 5–10% energy win, 1–2% IPC cost. Deferred, but a more attractive trade here than on J32-OOO given the energy-first goal. Revisit after G4.
7. **L1 capacity under 4 threads** — if G5 fails, the preference order is associativity, then capacity, then way prediction. **L1** partitioning *per thread* remains explicitly rejected: it converts a shared-capacity advantage into a fixed one, and under §16.3 the four contexts are one tenant anyway, so it would buy no isolation. This does not extend to the **L2**, which is shared across *cores* and therefore across tenants: [cache/l2-spec.md §16.1](../cache/l2-spec.md) partitions it by way, per tenant, and that is adopted rather than deferred.
8. **Software-exposed thread priority** — not provided (§1.2). The two automatic cases cover the dominant scenarios.
9. **Dual-core J32-LT** — 8 logical CPUs, MSI coherence per [cache/l2-spec.md §7](../cache/l2-spec.md). Not specified here; the AIC2 change in §13 item 3 is the prerequisite.
10. **If G8 misses (delay-on-miss costs more than 5% at *k* = 4)** — the levers, in order: narrow the trigger to loads whose address derives from a value produced under an unresolved branch (a more precise condition, not a weaker one); raise the per-thread MSHR count so more independent work proceeds behind a delayed load; accept the loss, which is still the cheapest defence available. **Adding a speculative fill buffer is not on the list** — §16.7 explains why, and the exclusion is a requirement rather than a preference.
11. **Core-granular tenancy (§16.3)** — four contexts sharing one L1, one TLB and one predictor set are one security domain, enforced by a scheduler (the hypervisor's under virtualization) rather than by hardware. *(Wave-3 **C2c**: [hypervisor/hardware-spec.md §4.7.2](../hypervisor/hardware-spec.md) now backs the virtualized half in hardware by refusing an `HRTE` that would seat two tenant numbers on one core's contexts. Four contexts make the check cheaper to get wrong, not cheaper to satisfy: every one of the three siblings must already hold this tenant's number. The unvirtualized half is unchanged.)* This is the weakest link in §16 and it is deliberate: partitioning per thread would undo the sharing advantage that §9.2 is built on. §14 item 7 already rejects cache partitioning on performance grounds; note it is *also* the escape hatch here, and that it is patent-clear (§16.13). Do not adopt distrusting co-residency silently. **The commercial consequence is sharper here than on J32-OOO**: the rule converts four sellable tenant slots per core into one tenant's four vCPUs, so LT's throughput advantage now shows up as vCPUs-per-tenant rather than tenants-per-board. Whether that is the product the service wants is a Phase 6.5 question, not a hardware one — see [jcore-ulx3s-service-plan.md §3](../jcore-ulx3s-service-plan.md).
12. **Per-context privileged state (§16.12) is the cost that grew** — ~10,000 gates, four-way FGMT's doing. If G6 (ECP5 fit) comes under pressure, this is not the place to economise: it is the only item in §16 whose omission causes silent data corruption rather than a channel. The place to look is thread count.

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
| P6 | Barrel FGMT ×4: contexts, 2-deep standby queues, ready-mask selection with period floor (§2.5), per-thread ASIDR | 3 mo |
| P7 | Atomic groups (CAS.L), L2 line lock, 4-thread qualification | 1.5 mo |
| P8 | Cache hierarchy ×4-thread tuning, prefetchers | 1.5 mo |
| P9 | PMU ×4 + Linux driver, incl. the four new events | 1.5 mo |
| P10 | Auto-priority (CAS spin, SLEEP) | 0.5 mo |
| P10.5 | Security mechanisms (§16): `DOM` tagging, delay-on-miss, poison forwarding, squash cleanup, invalidate control, `SPB` | 1.5 mo |
| P11 | Verification, Linux boot as 4 CPUs, G1–G8 and S1–S4 | 3 mo |
| P12 | ULX3S 85F bring-up | 2 mo |

**Total ~26.5 months.** P0 is deliberately first and deliberately cheap: §2.4's IPC projection is the load-bearing assumption of the entire design, it is analytically tractable, and discovering it is wrong after P6 would be expensive. **P0 should also model §7.4a and produce the G8 answer** — the same trace model already knows which loads miss and which branches are unresolved, so the marginal cost is close to zero and the payoff is knowing before P1 whether the security claim of §1.1(6) holds.

---

## 16. Security model — transient execution

### 16.1 In-order issue is not a defence

The tempting reading of §1.3 is that a core without renaming, without an issue queue and without memory-dependence prediction has little to fear from Spectre. That reading is wrong, and it should be dealt with in the first paragraph of this section rather than discovered later.

J32-LT predicts branches (§3.5), fetches and executes past the prediction, and issues **non-blocking loads** past an L1 miss (§7.4). Those three facts are a complete Spectre-v1 gadget; nothing in the in-order issue rule prevents a transient load from leaving a trace in the cache. The published evidence agrees: [SpecLFB (USENIX Security 2024)](https://www.usenix.org/system/files/sec24summer-prepub-556-cheng-xiaoyu.pdf) evaluates transient-execution defences on an in-order core alongside an out-of-order one because both need them.

What in-order issue *does* buy is narrower and real: the v4 speculative-store-bypass path is structurally absent (§7.3), and the mispredict window is shorter because fusion resolves branches a stage earlier (§4.2).

### 16.2 Threat model

**In scope.** Two mutually distrusting security domains — user vs kernel, process vs process, or **thread vs sibling barrel thread** — where one reads the other's data through a microarchitectural channel using transient execution.

| Path | Ingredient here | Closed by |
|---|---|---|
| Bounds-check bypass (v1) | branch prediction + speculative non-blocking loads | §7.4a, §16.6 |
| Branch target injection (v2) | 1024-entry gshare and 32-entry BTB shared by 4 contexts | §3.5 `DOM` tagging, §16.4 |
| Return-stack transient | RAS entries usable across privilege | §3.5 RAS domain tag |
| Speculative store bypass (v4) | — | **structurally absent** (§7.3) |
| Permission-failing load feeds a transient address | fault raised at commit (§6.5) | §6.6 rule 3 |
| Cross-thread cache/TLB/predictor contention | 4 contexts, one L1, one TLB, one predictor set (§9.2) | §16.3 — **by policy, not by hardware** |
| **Cross-thread issue-bandwidth contention** | the ready-mask arbiter (§3.1) hands a stalled thread's barrel slots to the others, so one thread's stalls appear as another's speed-up | §16.3 — by policy; see §16.2a |
| **Cross-tenant L2 contention** | one set of L2 arrays serves both cores ([cache/l2-spec.md §2](../cache/l2-spec.md)), so core-granular tenancy does not reach it | [cache/l2-spec.md §16.1](../cache/l2-spec.md) way-partitioning |
| **Guest trains the hypervisor's indirect branches** (VMScape) | predictor shared across `SR.HPRIV` | §3.5, [j32ooo-spec §20.10](j32ooo-spec.md) |
| **Guest trains another guest's branches** | no VMID; ASID partitioning is the only separator ([../mmu/hardware-spec.md §4.2](../mmu/hardware-spec.md) — VMID was removed project-wide, and this is the argument that made it load-bearing) | `PDID` in `DOM` |
| **Predictor update crosses a world switch** (Branch Privilege Injection) | update applied after the domain changes | §3.5 update policy, ROB-carried `DOM` |
| **Speculative access to an emulated device or P4** | aperture comparator on a speculative PA; device reads have side effects | §7.4b |
| **Guest folds P1 to host physical memory** | mode-dependent address path (hypervisor §4.4.1) | §6.6 rule 5 — *escape, not leak* |
| **One vCPU reads another's store-queue bytes** | SQ buffers per-CPU, 4 contexts concurrent | §16.12 — *not a speculation bug* |

**Out of scope, explicitly.** Physical attacks, power and EM analysis, Rowhammer, fault injection, and timing analysis of *committed* execution — a victim whose committed control flow or access pattern depends on a secret leaks with or without speculation, and the answer is constant-time software (Kocher 1996; [Percival 2005](https://www.daemonology.net/papers/htt.pdf)).

### 16.2a The issue-bandwidth channel, and why the PMU makes it loud

The cache and TLB channels of §16.2 are the ones the literature names, and they need prime-and-probe
apparatus to exploit. The barrel has a more direct one that needs none.

Thread selection is a ready-mask priority encoder over the runnable set (§3.1) with a period floor
(§2.5). When a thread stalls — a delayed load (§7.4a), an L1 miss, a parked `SLEEP` (§9.3), a
lock-spin priority drop — it leaves the ready set, *k* falls, and **the remaining threads are
selected more often**. One thread's stall is therefore the other threads' measurable speed-up, and
the relationship is close to architectural: it is a direct function of the arbiter's input, not an
emergent property of a shared array.

Two things make this louder here than the equivalent on an SMT machine:

1. **The signal is coarse and clean.** At *k* = 4 a thread gets one slot in four; at *k* = 2 it gets
   one in two. A victim entering and leaving the ready set moves the observer's issue rate by a
   step, not by a noisy fraction.
2. **The PMU states the answer.** `PMCYC`/`PMINS` give an observer its own IPC directly, and events
   `0x18 BARREL_SLOT_IDLE` and `0x19 SPEC_MISS_DELAY_CYCLES` are more direct still. These are
   privileged, but a tenant owns its guest kernel, so "privileged" is not a boundary here. This is
   the same argument [hypervisor/design-spec.md §6](../hypervisor/design-spec.md) makes about the
   TSB walker counters: a counter that *states* cross-domain behaviour is worse than the timing
   channel it summarises, because it needs no measurement apparatus and carries no noise.

**This is not separately mitigated, and it cannot be cheaply.** Removing it means making thread
selection independent of the other threads' readiness — that is, fixing the barrel period regardless
of *k*, which discards §2.5's period floor and with it the single-thread performance the floor
exists to protect. §16.3's tenancy rule is the answer instead: the observer and the victim are the
same tenant.

What the design *does* do is keep the channel from widening: §7.4a's delay-on-miss removes the
cache-state half of it, so a stalled thread leaks its stall *timing* but not the addresses that
caused it.

### 16.3 The four-context sharing decision — the core is the unit of tenancy

§9.2 shares the L1 caches, L2, gshare PHT, BTB, TLB and prefetch state across four contexts while §1.1(5) presents those contexts to Linux as four CPUs. Those statements are compatible **only if co-resident contexts are same-trust**, and this specification takes that position deliberately, as an allocation rule rather than a scheduling hint:

> **A physical core is the unit of tenant allocation *at any instant*. Every thread context of a core belongs to the same tenant — the same virtual machine, or the same trust domain on an unvirtualized system — for as long as that tenant is resident. A tenant that needs only one vCPU is given a whole core, with the sibling contexts idle or running that same tenant's other vCPUs.**

A core may be shared between tenants **over time** via a gang switch: all four contexts change tenant together, with the invalidation sequence of [hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md) at the boundary. That raises the number of tenants a board can host, never the number running at one instant.

A dual-core J32-LT board therefore *runs* **two tenants of up to four vCPUs each** at any instant, not eight tenants of one. Under the hypervisor extension the scheduler enforcing this is the hypervisor's, and it belongs in admission control ([hypervisor/hardware-spec.md §4.7](../hypervisor/hardware-spec.md)); [jcore-ulx3s-service-plan.md §3](../jcore-ulx3s-service-plan.md) carries the corrected tenant count. Note this cuts harder here than on [j32ooo-spec §20.3](j32ooo-spec.md): four contexts per core is what makes the aggregate-throughput case, and the rule converts them from four sellable tenant slots into one tenant's four vCPUs. That is the honest price of the sharing in §9.2, and it does not change the IPC argument of §2.4 at all — a tenant with four runnable vCPUs saturates the barrel exactly as four tenants would.

The exposure this accepts is pre-2006 public knowledge, which is worth stating plainly rather than treating as a novel risk. Percival demonstrated RSA key recovery across a shared L1 between two hardware contexts on one core in 2005, and observed that the technique applies "to any system where caches are shared between two or more non-mutually-trusted execution threads". §9.2 is that configuration with four contexts instead of two.

The alternative is partitioning, and §14 item 7 already rejects per-thread cache partitioning because it "converts a shared-capacity advantage into a fixed one" — which is the whole reason four contexts share 32 KB rather than owning 8 KB each. The design cannot have both.

What the hardware still provides so the policy is enforceable and testable:

- LSQ partitioning makes cross-thread store-to-load forwarding structurally impossible (§7.1).
- `DOM` (§3.5) includes `TC_ID`, so predictor *state* is not shared even though the *arrays* are.
- The invalidate control (§16.4) is per-context.
- PMU 0x19–0x1C expose cross-thread interference, so §16.3 can be tested rather than assumed.

This belongs in the Linux port documentation as well (§13 item 11). A kernel that schedules two tenants across contexts of one core is operating the part outside its specification.

### 16.4 Predictor invalidate control

One privileged control-register bit per context. Writing 1 invalidates, in a single action, that context's gshare entries, its BTB entries, its RAS and its stride table. The bit self-clears. The kernel writes it from `switch_mm` and on leaving a more privileged domain.

Three constraints on the implementation, and they are requirements, not preferences:

1. **Software-triggered only.** Hardware does not detect security-domain transitions and does not act on them by itself.
2. **Unconditional and complete.** One action, everything cleared. No modes, no partial subsets, no progressive re-enable as a reset proceeds.
3. **No save/restore.** State is discarded, never preserved and reloaded.

Prior art: **SH-4 `CCR.ICI` / `CCR.OCI`** (SH-4 hardware manual, 1998) — a privileged register write that invalidates a cache array wholesale. The value of clearing predictor state across context switches is pre-2006 in the literature (Two branch-predictor schemes under frequent context switches, 1998; OPTS, 2002). §16.7 explains why constraints 1–3 are stated as hard requirements.

**Under virtualization this is defence in depth, not the primary mechanism.** The x86 answer to cross-domain predictor training is IBPB on every VM exit, at roughly 10% on emulated-device workloads, because tagging is absent and the barrier is all there is. Here `DOM` already carries `SR.HPRIV` and `PDID`, so host and guest occupy different predictor domains by construction. The invalidate stays a **policy** choice — a per-guest control bit a hypervisor may set to issue it on every world switch, paying for it; the default does not. Tag first, barrier optional, is the whole reason to have specified `DOM` properly.


### 16.5 What this costs

| Mechanism | Area | Performance |
|---|---|---|
| `DOM`-tagged index and BTB tag (§3.5) | ~300 gates | slight; more cold-start misses, less cross-context aliasing |
| RAS domain tags ×4 (§3.5) | ~350 gates | negligible — a discarded pop falls back to the BTB |
| Commit-only training (§3.5, §7.5a) | ~0 | small accuracy loss on tight loops |
| **Delay-on-miss (§7.4a)** | **~400 gates** | **the only material item — G8** |
| Permission-resolved forwarding (§6.6) | ~700 gates (poison through bypass and LQ ×4) | negligible |
| Squash cleanup (§6.6) | ~450 gates | negligible |
| `SPB` (§4.1) | ~150 gates | only where software uses it |
| Invalidate control ×4 contexts (§16.4) | ~950 gates | cold predictor after each context switch |
| PMU events 0x19–0x1C (§10) | ~600 gates | — |
| `PDID` and wider `DOM` tags (§3.5) | ~600 gates | as above |
| `DOM` carried through the ROB (§6.3) | ~200 gates | — |
| Non-speculative region gating (§7.4b) | ~300 gates | nil |
| `HRTE` writeback through ARF+RAT (§6.6) | ~200 gates | one drained pipeline per hypercall / MMIO resume |
| **Per-context hypervisor registers + store queue ×4 (§16.12)** | **~10,000 gates** | — |
| **Total** | **~15,200 gates** (~6.5% of the core) | |

The area is no longer noise: §16.12 alone is ~4.5% of the core, and it is the one item four-way FGMT makes expensive rather than cheap — [j32ooo-spec §20.12](j32ooo-spec.md) pays a third of it. It is also the one item that is not a channel: omitting it produces silent cross-vCPU data corruption. Everything else on this list totals ~5,200 gates.

The claim that still holds is about *performance*: the speculation defences cost little here and would not on a latency-first core — see §7.4a and G8. The claim that no longer holds unqualified is §12.1's "comparable area": once virtualization is in scope, four thread contexts cost four copies of the per-vCPU register set, and that is a real widening of the gap against J32-OOO.

### 16.6 Software contract

Hardware closes the microarchitectural paths; software still owns the gadget.

- **Array index masking** after a bounds check, rather than relying on the branch.
- **`SPB`** (§4.1) where masking is not expressible. GCC's `__builtin_speculation_safe_value` lowers to mask-plus-`SPB` in the `sh-linux` port.
- **Predictor invalidate** (§16.4) from `switch_mm`.
- **Core scheduling** per §16.3.

All of it gated on a CPU capability bit: J2 and in-order J32 parts have none of these.

### 16.7 Mechanisms deliberately not implemented

The [glossary §2](../glossary.md) prior-art policy exists because J-Core's value proposition is patent freedom, and it needs care for this class of mechanism: the *structures* involved are often pre-2006 while the *security-triggered combination* is recent and claimed.

1. **No L0 speculative filter cache.** The obvious alternative to §7.4a is a small buffer catching speculative fills and promoting them to L1 on non-speculative, cleared on squash and domain switch — the SpecBuf shape proposed for BOOM in CARRV 2019, and the MuonTrap shape. The structure is thoroughly pre-2006: Jouppi 1990 stream buffers and Cray US5761706 (filed 1994, expired) hold prefetched blocks outside the cache; Intel US6223258 (filed 1998, expired) services a non-temporal load from a dedicated buffer "without accessing said cache". The security-triggered combination is not, and is claimed by live patents (Microsoft US11061824, priority 2019; plus split-cache and reserved-set variants). **Do not build it, and do not "optimise" §7.4a into it** by adding a buffer for delayed misses. This is also why §14 item 10 excludes it from the G8 fallback list.
2. **The invalidate control keeps the §16.4 shape.** Hardware detection of a domain transition combined with a multi-mode, progressively re-enabled reset is claimed (SiFive US11429392, priority 2018); save/restore of predictor state across context switches is claimed (Arm US10838730; Microsoft US11068273). The plain software-triggered unconditional invalidate is what SH-4 `CCR.ICI` has done to a different array since 1998.
3. **§6.6 rule 3 is an ordering constraint on forwarding, not register taint, and the name "degenerate STT" is not used for it.** Taint bits on architectural registers with a policy register selecting which speculation features to disable is the shape claimed by **AMD US10956157B1** (priority 2018-03-06, granted 2021-03-23, in force) — filing data verified at source, post-F 2026-09-10. Ours is a rule about when one load may forward, and it adds no register state. The full treatment, including the 2019 date of the name and the pre-2006 structure it would have built on (IA-64's NaT bit, 2000), is [j32ooo-spec.md §20.7](j32ooo-spec.md) rejection 3; it is not repeated here.

The two general rules this yields belong in [glossary §2](../glossary.md) (§13 item 9): prior art matches at the level of **mechanism, not motivation** — a claim covers structure and steps, which is why US6035393's 1995 stall-until-speculation-resolves reads on §7.4a regardless of why it was filed — and conversely a pre-2006 *structure* is necessary but not sufficient where the security-specific *combination* is separately claimed.

This is a documentation exercise, not a freedom-to-operate opinion. The two load-bearing findings — US6035393 as the §7.4a anchor, US11061824 as the reason for rejection 1 — warrant a professional search before RTL commits.

### 16.8 Relationship to J32-OOO

| | J32-OOO | J32-LT |
|---|---|---|
| v4 speculative store bypass | present; needs an `SSBD` control ([§8.4](j32ooo-spec.md)) | **structurally absent** (§7.3) |
| Delay-on-miss cost | absorbed by 2 contexts; [j32ooo-spec §20.8](j32ooo-spec.md) gate S5, threshold <10% | absorbed by 4; G8, threshold <5% |
| Contexts sharing L1/TLB/predictors | 2 | 4 — larger surface for the same §16.3 policy |
| Tenants per core under §16.3 | 1 (up to 2 vCPUs) | 1 (up to 4 vCPUs) |
| Per-context privileged state (§16.12) | ~3,000 gates | **~10,000 gates** — the item four-way FGMT makes expensive |
| Predictor isolation before `DOM` | 1 bit of thread ID | 2 bits over 4 contexts — was the weaker of the two |
| Mispredict window | tournament predictor, 7/4-cycle recovery | shorter: fusion resolves a stage earlier (§4.2) |

Neither is the secure one and the other the insecure one. LT is structurally ahead on v4 and on the cost of the main defence; OOO is ahead on contention surface simply by having half as many contexts.

### 16.12 Per-context hypervisor state, and the store queue

[hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md) describes `HEMUB`, `HEMUM`, `HPAR`, `HMDR`, `HMCR` and `HSQCR` as "per-vCPU state, saved and restored across VM exit and entry" — correct for a core running one vCPU at a time. **This core runs four concurrently.** There is no exit at which to save, so every one of them is **per thread context**:

| Register | Hazard if shared |
|---|---|
| `SR.HPRIV` | one context's mode selects another's translation regime — §6.6 rule 5 |
| `HSPC`, `HSSR` | one context's trap destroys another's resume state |
| `VBR_HYP`, `HEDR` | one vCPU's delegation policy applied to another's traps |
| `HEMUB`, `HEMUM` | one vCPU's device map applied to another's accesses |
| `HPAR`, `HMDR`, `HMCR` | a second aperture trap overwrites the capture registers the hypervisor is about to consume for the first |
| `HSQCR`, **two 32 B SQ buffers, `QACR0`/`QACR1`** | below |
| `PDID` | [j32ooo-spec §20.10](j32ooo-spec.md) |

**The store queue is the serious one, and it is not a speculation bug.** [sq/spec.md](../sq/spec.md) gives the core two 32-byte buffers, and [hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md) carves them out of the guest-mode P4 trap precisely so a guest can use them at native speed — eight stores plus a `PREF` per burst, untrapped. With four contexts resident, up to four vCPUs write the *same* buffer; their bytes interleave, and whichever issues the `PREF` bursts a mixture to its own physical target. That is cross-vCPU disclosure and corruption on the hot path the carve-out exists to accelerate, with no misprediction anywhere in it. §16.3's core-granular tenancy makes those vCPUs the same tenant and so bounds the blast radius, but the behaviour is still wrong between two vCPUs of one tenant.

**Cost: ~114 B per context beyond §9.1's baseline, ×3 additional contexts ≈ 2,700 bits ≈ 10,000 gates.** This is the largest single security line item in either design, and it is four-way FGMT that makes it so — [j32ooo-spec §20.12](j32ooo-spec.md) pays a third of it. It is not optional and it is not deferrable: unlike every other item in §16, omitting it produces silent data corruption rather than a channel.

The reasoning is identical to §11's MMU-register correction, extended to the Phase 3 set, and so is the failure mode: silent attribution of one context's state to another.

### 16.13 Prior-art summary

| Mechanism | Pre-2006 source |
|---|---|
| Domain-tagged lookup state, `PDID` (§3.5) | sun4v `PRIMARY_CONTEXT`/`SECONDARY_CONTEXT` with a distinct hyperprivileged nucleus context (UltraSPARC Architecture 2005, hyperprivileged edition); MIPS R4000 ASID-tagged TLB (1991); SH-4 (1998) |
| No speculative access to device space (§7.4b) | Intel US6035393 (priority 1995, **expired**) — its *literal* motivation; SH-4's architectural P1/P2 cached/uncached split (1998) |
| Mode transitions serialized (§4.3, §6.6) | PowerPC `isync`; IBM S/370 serialization; SH-4 exception-entry semantics (1998) |
| Per-context privileged state (§16.12) | the argument §11 already applies to `PTEH`/`TEA`/`MMUFSR`; sun4v per-vCPU hyperprivileged state (2005) |
| Commit-time predictor update (§3.5) | speculative-history repair literature, 1996–1998 |
| Delay-on-miss (§7.4a) | Intel US6035393, priority 1995-09-11, **expired**; Farkas & Jouppi 1994 |
| Poisoned speculative load result (§6.6) | IA-64 `ld.s`/NaT/`chk.s` (1999–2001); Smith & Pleszkun 1985 |
| Speculation barrier (§4.1) | PowerPC `isync`; SPARC v9 `MEMBAR #Sync` (1994) |
| Array-invalidate control bit (§16.4) | SH-4 `CCR.ICI` / `CCR.OCI` (1998) |
| Clearing predictor state at context switch (§16.4) | Two branch-predictor schemes under frequent context switches (1998); OPTS (2002) |
| Prefetch bounded at page boundary (§7.5a) | Jouppi 1990; Cray US5761706 (filed 1994, expired) |
| Threat model (§16.2) | Kocher 1996; Percival, BSDCan 2005 |
| L2 way partitioning by tenant ([cache/l2-spec.md §16.1](../cache/l2-spec.md)) | MIT column caching, Chiou et al. 1999–2000; US6370622 (filed 1998, expired); Suh & Devadas 2002–2004 |
| Gang scheduling of a core's contexts ([hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)) | Ousterhout, "Scheduling Techniques for Concurrent Systems", ICDCS 1982 |

---

## Appendix A: What is deleted relative to J32-OOO

| Structure | J32-OOO size | Reason it is gone |
|---|---|---|
| Issue queue | 16 entries, 2 CAMs/entry, 3 broadcast tags/cycle | in-order issue |
| IQ collapse shift register | 16 entries, all fields | no IQ |
| Physical register file | — | future-file: values live in the ROB |
| Free list | — | no physical registers to allocate |
| Rename-map checkpoints | 8 × 23 × 6 b **per thread** | §5.4 history buffer instead |
| SSIT | 1024 entries | §7.3: no address speculation possible — and with it the v4 transient path (§16.2) |
| LFST | 64 entries | §7.3 |
| `SSBD` control bit | — | nothing to disable ([j32ooo-spec §8.4](j32ooo-spec.md)) |
| Bimodal PHT | 1024 × 2 b | gshare alone (§3.5) |
| Chooser PHT | 1024 × 2 b | gshare alone (§3.5) |
| Ready-thread arbiter | priority computation/cycle | ready-mask encoder; free-running counter at *k*=4 (§3.1) |
| Front-end thread tags | per stage, full | 12 FFs; positional at *k*=4 (§2.5) |
| Cross-thread LSQ ID compare | per forward | partitioned LSQ (§7.1) |
| Fetch alignment rotator | — | 32-bit aligned bundles (§3.3) |
| Decode-buffer compaction | — | non-collapsing bundles (§3.3) |

## Appendix B: Glossary additions

- **Barrel** — front end in which thread count equals stage depth, so each stage holds a different thread each cycle and thread identity is positional rather than tagged. CDC 6600 PPU (1964). J32-LT departs from the pure form via the period floor (§2.5).
- **Period floor** — lower bound of 2 cycles on how often a thread may be granted an IF1 slot, regardless of how few threads are ready. Prevents single-thread throughput collapsing to the barrel's `1/depth`.
- **Bundle** — the two 16-bit instructions at a 32-bit-aligned address, fetched, decoded, paired, and issued as a unit. Does not collapse.
- **BTFNT** — Backward-Taken / Forward-Not-Taken. Static branch direction heuristic, here used to seed gshare counters at BTB allocation rather than as a standalone predictor.
- **`E[width]`** — average architectural instructions retired per issuing cycle. The quantity §2.4's IPC projection turns on.
- **Future-file** — a register-status table mapping architectural registers to in-flight producers, with results held in the ROB until commit. Not renaming: it expands no name space.
- **PAIR** — pipeline stage between DEC and ISS that performs fusion detection, pairing legality, and slot steering.
- **`DOM`** — security-domain identifier `{PDID[5:0], SR.HPRIV, SR.MD, TC_ID[1:0]}` used to tag and index every predictor structure (§3.5) and carried per instruction in the ROB. Not the thread ID alone.
- **`PDID`** — Predictor Domain ID ([j32ooo-spec §20.10](j32ooo-spec.md)). Hyperprivileged 6-bit register naming the current security domain.
- **Delay-on-miss** — a load that misses L1 while still speculative does not issue to L2 until it is non-speculative (§7.4a). A condition on MSHR allocation, not a structure.
- **Poison** — the value a faulting or permission-unresolved load forwards in place of data; propagates through dependents, may not form an address or branch condition, raises at commit (§6.6).
- **`SPB`** — speculation barrier: nothing younger executes until it retires ([j32ooo-spec §4.6](j32ooo-spec.md)).
- **Standby register** — one-deep per-thread raw-bundle buffer that catches the barrel follower when an issue bundle fails to drain.
- **Split bundle** — a bundle that issues its two slots in two separate cycles because dual-issue was illegal or an operand was not ready.
