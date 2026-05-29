# J32OOO — Out-of-Order J-Core Implementation Specification

**Status:** Draft v0.2.1
**Compatible ISA:** SH-Compact (SH-2 + J-core extensions: SHAD, SHLD, CAS.L)
**Scope:** CPU core, cache hierarchy, and performance monitoring. FPU (see [../fpu/spec.md](../fpu/spec.md), Tier 1 required for the J32-OOO product point), MMU, IOMMU/DMA, SIMD, and crypto coprocessor blocks are specified separately.

**J32OOO** is a 2-wide fetch, 2-wide commit OOO core with 2-way FGMT, 32-bit datapath. Targets the "J32-FM" roadmap slot (~250k ASIC gates including caches and PMU). See [glossary §3–§4](../glossary.md) for product-point and threading naming.

## Changelog

- **v0.2.1** (2026-05): Scoped document to J32OOO only. Forward references to J64 (4-wide variant) removed; a separate specification will cover that design point when J32OOO implementation reaches verification.
- **v0.3** (2026-05): Replaced SMT/ICOUNT with FGMT (fine-grained multi-threading) per project-wide threading decision (see [glossary §4](../glossary.md)). One thread selected per cycle at IF1; that thread fills both issue slots. Backend resources stay shared with thread tags. Auto-priority adjustment (CAS.L spin, SLEEP) preserved with simpler ready-thread arbitration.
- **v0.2** (2026-05): Added 2-way hardware multi-threading. Added automatic priority adjustment via CAS.L spin detection and SLEEP execution (no software-exposed priority hints). Added L1/L2 cache hierarchy specification with prefetchers. Added performance monitoring unit with Linux `perf` driver support.
- **v0.1**: Initial OOO design point. 2-wide single-thread, ROB-based rename, atomic-group handling for CAS.L.

---

## 1. Design Philosophy and Constraints

### 1.1 Goals

1. Improve aggregate throughput over the existing in-order J32 on the target workload mix (Dreamcast binaries, SSH/encrypted traffic termination, JSON/OpenTelemetry metric serialization) by a factor of roughly 2.0×–3.0× with 2-way FGMT. (Lower than the SMT projection in v0.2; FGMT fills one issue slot per cycle from the selected thread, so per-thread IPC is preserved but the second issue slot only fills when the chosen thread's two decoded uops are both independent and ready — typical for SH-2 code with short delay-slot patterns.)
2. Stay within ~250k gates including L1+L2 caches and PMU.
3. Preserve SH-Compact's strict precise-interrupt guarantees.
4. Maintain SMP correctness for the J-core CAS.L primitive with no architectural changes.
5. Provide Linux `perf`-tool compatibility for production tuning and observability.

### 1.2 Non-goals (explicit deferrals)

- No new architecturally-visible instructions exposed to user code. The auto-priority mechanism (§13.4) operates transparently — no `HMT_*`-style software priority hints exposed in this revision.
- No software-exposed thread priority register; priority is hardware-managed.
- No FPU integration (specified separately in [../fpu/spec.md](../fpu/spec.md); Tier 1 SH-4-complete FPU is required for Dreamcast workloads but the integration into the OoO pipeline is out of scope for this document).
- No MMU integration (separate specification).
- No IOMMU/DMA integration (separate specification).
- No SIMD or crypto extensions (handled by separate coprocessor blocks).
- No FGMT-aware cache partitioning beyond standard set-associative sharing.
- No new memory-ordering model. SH-Compact's weak ordering is preserved.
- No cycle-accurate emulation of historical SH-4 timing for Dreamcast workloads.
- No wider-than-2-wide variant in this document (future work).

### 1.3 Pre-2006 technique citations

Every microarchitectural technique used in this specification has prior art published before 2006:

| Technique                                        | Citation                                              |
| ------------------------------------------------ | ----------------------------------------------------- |
| ROB-based rename (P6 future-file)                | Smith & Pleszkun 1985; Intel Pentium Pro 1995         |
| Reservation stations / Tomasulo                  | IBM 360/91, Tomasulo 1967                             |
| gshare branch predictor                          | McFarling 1993                                        |
| Tournament/hybrid predictor                      | McFarling 1993; Alpha 21264 1998                      |
| Return Address Stack                             | Kaeli & Emma 1991                                     |
| Store-set memory dependence prediction           | Chrysos & Emer 1998                                   |
| Macro-op fusion (atomic-group)                   | AMD K7 1999                                           |
| Rename-checkpoint fast misprediction recovery    | Hwu & Patt 1987; MIPS R10000                          |
| Fine-grained multi-threading (FGMT, barrel)      | CDC 6600 PPU (Thornton 1964); Denelcor HEP (Smith 1978); Tera MTA (Smith 1990) |
| FGMT on a single-issue in-order RISC pipeline    | MIPS MT ASE / 34K (Kissell, MIPS Tech 2005); Sun UltraSPARC T1 "Niagara" (Kongetira et al., IEEE Micro 2005) |
| Switch-on-stall / ready-thread arbitration       | MIT Alewife Sparcle (Agarwal et al. 1993); UltraSPARC T1 thread scheduler 2005 |
| Auto-priority on idle/spin states                | MIT Alewife block-multithreaded scheduling 1993; HEP spin-wait coalescing 1978 |
| On-die L2 cache                                  | Alpha 21164 1995 (96 KB); AMD Thunderbird 2000 (256 KB) |
| Stride prefetcher                                | Chen & Baer 1995                                      |
| Next-line prefetcher / stream buffers            | Jouppi 1990                                           |
| Performance Monitoring Unit (event counters)     | DEC Alpha 21064 1992                                  |
| PerfEvtSel / PerfCtr model                       | Intel P6 1995                                         |
| PowerPC PMC1–PMC4 with MMCR0/1                   | PowerPC 750 1997                                      |
| Per-thread PMU counters                          | UltraSPARC T1 per-strand counters 2005                |

---

## 2. Top-Level Pipeline

### 2.1 Pipeline stages

```
   IF1   IF2   PD    DEC   REN   DIS   ISS   RR   EX1   EX2/MA   WB    CMT
  Fetch1 Fetch2 Pre- Decode Re-  Dis-  Issue Reg  Exec  Exec/Mem Write  Commit
                 dec         name patch       read              back
  +------+------+----+------+-----+-----+----+----+-----+-------+-----+-----+
  | I$tag| I$dat| BP | uop  | RAT |IQ   | Wk |ARF | ALU |  Mem  | ROB | ARF |
  | BTB  | ICNT |    | emit | ROB |alloc| Sel|    | Mul |  EX2  | upd |     |
  +------+------+----+------+-----+-----+----+----+-----+-------+-----+-----+
```

Twelve named stages. FGMT thread selection occurs at IF1 (see §13.2). Most instructions traverse 10 stages (no second EX). The OOO portion is REN through CMT.

Key boundaries:

- **IF1 → IF2**: I-cache access. Existing 2-cycle access from `cache/icache.vhd` is extended for 32 KB capacity (see §11).
- **PD**: Predecode and branch prediction. Same cycle as IF2 result becomes available.
- **DEC → REN**: in-order portion ends at the end of DEC. From REN onward, instructions may reorder.
- **DIS → ISS**: dispatch into the unified issue queue; instructions wait here until operands ready and a functional unit is free.
- **CMT**: in-order per-thread, 2-wide retirement from the ROB head. Threads commit independently.

---

## 3. Front End

### 3.1 Instruction Fetch

- **I-cache**: 32 KB / 4-way set-associative (see §11.1).
- **Fetch width**: 32 bits per cycle (two SH instructions).
- **Fetch alignment**: SH instructions are 16-bit aligned.
- **Per-thread PC**: each thread has its own PC. The thread selector (§13.2) drives the I-cache access from the chosen thread's PC each cycle.

### 3.2 Branch Prediction

McFarling tournament predictor with thread-tagged history:

- 1024-entry **bimodal table** (2-bit saturating counters), indexed by `PC[10:1] XOR thread_id`.
- 1024-entry **gshare table**, indexed by `PC[10:1] XOR GHR[9:0] XOR thread_id`. GHR is per-thread (2 × 10 bits).
- 1024-entry **chooser table** (2-bit counters).
- Total state: ~1 KB plus per-thread GHR.

**BTB**: 32-entry, 4-way set-associative, tagged with PC bits and thread ID.

**RAS**: per-thread, 8-entry circular stack. Cross-thread corruption is avoided.

**Misprediction penalty**: 7 cycles raw; 4 cycles with rename-map checkpoint recovery.

### 3.3 Delayed Branch Handling

SH delayed branches (BRA, BSR, JMP, JSR, RTS, BT/S, BF/S, BRAF, BSRF, RTE) have one delay slot. The slot instruction executes whether or not the branch is taken.

**Fetch policy**: After predicting a delayed branch, fetch the slot instruction next, then fetch from the predicted target.

**Decode policy**: Tag the branch uop with `DELAY_BRANCH`. Tag the next instruction with `DELAY_SLOT`. Rename and dispatch them as a pair into adjacent ROB slots, both tagged with the same thread ID.

**Mispredict policy**: If the branch resolves as mispredicted, squash everything in the ROB *after* the slot. The slot itself executes and commits regardless. The PC is restored to the corrected target.

**Illegal slot detection**: The decoder must flag delayed-branch instructions appearing in delay slots (architecturally illegal). This logic exists in current J-core decode (`decode_table_simple.vhd`'s `illegal_delay_slot` signal). Reuse.

---

## 4. Decode and Microcode Expansion

### 4.1 Architecture-to-uop mapping

Most SH instructions decode to a single uop. Multi-cycle instructions decode to multiple uops, walked by a microcode sequencer at decode time. Examples:

| SH Instruction         | uops | Notes                                                      |
| ---------------------- | ---- | ---------------------------------------------------------- |
| `add Rm, Rn`           | 1    | One ALU uop                                                |
| `mov.l @(disp,Rn), Rm` | 1    | One load uop                                               |
| `mac.l @Rm+, @Rn+`     | 4    | Load Rm, post-inc Rm, load Rn, post-inc Rn, multiply-accum |
| `cas.l Rm, Rn, @R0`    | 3    | Fused (see §10); was 4 in current J32                      |
| `div1 Rm, Rn`          | 1    | Iterative; uses non-pipelined divider FU                   |
| `lds.l @Rm+, MACL`     | 2    | Load, then move-to-MAC                                     |
| `rte`                  | 3    | Pop SR, pop PC, branch                                     |
| `trapa #imm`           | 4+   | Save context, vector, jump; serializing                    |
| `sleep`                | 1    | Parks thread (see §10.6)                                   |
| `movmu.l`/`movml.l`    | 1–17 | Store/load-multiple; crack to N mem uops + 1 pointer-update uop. See [../isa-density/spec.md](../isa-density/spec.md) §4.2 and [../isa-density/hardware-impl.md](../isa-density/hardware-impl.md) §6 |
| `movi20`/`movi20s`     | 1    | 32-bit (two-word) immediate load; fetch delivers both words, decode emits one imm uop. See [../isa-density/spec.md](../isa-density/spec.md) |

The `movi20`/`movmu`/`movml` density extensions are specified in full in the
[isa-density triad](../isa-density/spec.md) (architectural spec, hardware-impl,
software-impl); §6 of its hardware-impl details the uop-cracking that this
section's general mechanism (§4.1, §5.1) makes natural.

### 4.2 Decode-time uop annotations

Every uop carries FGMT-specific bits:

- `thread_id` (1 bit): which thread this uop belongs to.
- `is_cas_fail_candidate` (1 bit): set on the CAS.L compare-and-store uop. Used by §13.4.
- `is_sleep` (1 bit): set on the SLEEP instruction. Used by §13.4.

### 4.3 uop format

Internal uops carry the following fields:

```
struct uop {
    uop_op_t      op;            // 7 bits — ALU op, mem op, branch type, etc.
    arch_reg_t    src1, src2;    // 5 bits each (32 logical regs incl. T, MAC, PR, etc.)
    arch_reg_t    dst;           // 5 bits
    phys_reg_t    psrc1, psrc2;  // 6 bits
    phys_reg_t    pdst, pold;    // 6 bits; pold for free-on-commit
    imm32_t       imm;           // 32-bit sign/zero-extended immediate
    flags_t       flags;         // reads_T, writes_T, atomic_group, delay_branch,
                                 // delay_slot, serializing, ma_lock
    thread_id_t   tid;           // 1 bit
    rob_idx_t     rob;           // 5 bits (20-entry ROB)
    iq_idx_t      iq;            // 4 bits
    misc_flags_t  misc;          // is_cas_fail_candidate, is_sleep
};
```

### 4.4 Logical register set

The OOO design treats the following as the architectural state to be renamed:

| Register | Width | Notes                                                        |
| -------- | ----- | ------------------------------------------------------------ |
| R0–R15   | 32    | GPRs. R0 is implicit in many addressing modes.               |
| T        | 1     | Condition bit, renamed independently of SR.                  |
| S        | 1     | MAC saturation bit; rarely written, renamed.                 |
| MACH     | 32    | Renamed independently of MACL.                               |
| MACL     | 32    | Renamed independently of MACH.                               |
| PR       | 32    | Procedure register, renamed (frequent BSR/JSR writes).       |
| GBR      | 32    | Global base, infrequently written, renamed.                  |
| VBR      | 32    | Vector base, rare writes, treat writes as serializing.       |
| SR       | 32    | Status register; partial renames per field (see §4.5).       |

23 logical registers requiring rename per thread.

### 4.5 SR rename strategy

SR is broken into independent rename groups to avoid serializing on every flag-touching instruction:

| Field      | Bits  | Rename group  | Notes                                  |
| ---------- | ----- | ------------- | -------------------------------------- |
| T          | bit 0 | T-only        | Hot path; renamed every cycle          |
| S          | bit 1 | S-only        | MAC saturation; renamed                |
| Q, M       | bits 8–9 | DIV-only   | Used only by div0s/div1; renamed       |
| I3–I0      | bits 4–7 | mask group | Renamed at sts/stc SR; rare           |
| BL, RB, MD | bits 28–30 | priv group | Privileged; writes are serializing  |

A `stc SR, Rn` reads all groups and constructs a 32-bit value. An `ldc Rn, SR` writes all groups; treat as serializing (drain ROB, single dispatch).

---

## 5. Rename

### 5.1 FGMT-aware approach: per-thread RAT + shared ROB

For 2-way FGMT with future-file rename:

- **Architectural Register File (ARF)**: 2 × 23 entries = 46 logical registers (one full copy per thread).
- **Rename Alias Table (RAT)**: 2 × 23 entries. Each entry holds either an ARF index for the owning thread or a ROB slot index.
- **ROB**: 20 entries, thread-tagged. Each ROB slot has a 32-bit `value` field, a `valid` flag, exception flags, the destination logical register number, and a `thread_id` bit.

The ROB is shared rather than partitioned. Both threads compete for ROB slots dynamically. POWER5 used this approach; partitioned ROBs (as in the cancelled Alpha 21464) suffered from under-utilization when one thread had little work to do.

Reads at rename: each thread's RAT is consulted independently; the thread reads either from its own ARF or from any ROB slot (regardless of which thread allocated that slot — rename guarantees only the right thread reads its own producers).

Commits move ROB.value into the appropriate per-thread ARF and update the per-thread RAT.

### 5.2 T-bit rename

Each thread has its own renamed T-bit. The T-bit RAT entry is per-thread. Dependent compare chains within a thread don't serialize.

### 5.3 Rename-map checkpointing

8 checkpoints per thread (16 total). Each checkpoint is per-thread because branches are per-thread.

If a thread exhausts its checkpoints, that thread's rename stalls until a branch resolves; the other thread continues unimpaired.

---

## 6. Dispatch and Issue Queue

### 6.1 Dispatch

Dispatch width matches rename width: 2. Dispatch can mix threads in the same cycle (e.g. one uop from each thread). If either the ROB or the IQ is full for the source thread, dispatch stalls that thread but the other thread continues.

### 6.2 Issue Queue

16-entry unified issue queue. Each entry has a `thread_id` bit. Wakeup-select operates on tags regardless of thread; instructions from either thread can issue in the same cycle if their operands are ready.

Per-thread guaranteed reservation: at least 4 IQ entries are reserved for each thread to prevent one thread from completely starving the other. The remaining 8 are dynamically allocated. Same starvation-avoidance technique as POWER5.

- Each entry holds: `op`, `psrc1`, `psrc2`, `pdst`, `imm`, `ready1`, `ready2`, `iq_age`, `fu_type`, `thread_id`.
- On result broadcast from any FU, every IQ entry compares its `psrc1`/`psrc2` against the broadcast tag and sets `ready1`/`ready2`.
- Select logic: pick the oldest 2 ready instructions per cycle, matched to available FUs (one ALU pipe, one ALU+shift/mul pipe, one LSU pipe — but only 2 can issue per cycle; the LSU competes with one of the ALU pipes).

### 6.3 Wakeup-Select Logic

Wakeup-select uses 2 CAMs per IQ entry (one per source operand), comparing against the broadcast tag(s). 16 entries × 2 sources × 6-bit tags = 192 comparators per broadcast tag, × 3 broadcast tags per cycle = manageable.

Select: age-based priority encoder. Older entries win ties. Oldest-2 selection over a 16-entry queue is a tree of comparators.

### 6.4 Issue collapsing

After issue, the freed IQ slot is collapsed out by shifting younger entries down. This keeps the priority encoder simple (just pick from the top). Cost: a 16-entry shift register per IQ field. Acceptable at this size.

---

## 7. Execution Units

Functional units are shared across threads (no per-thread duplication). The IQ schedules opportunistically from either thread.

| FU       | Issue rate | Latency | Operations                                            |
| -------- | ---------- | ------- | ----------------------------------------------------- |
| ALU0     | 1/cycle    | 1       | add/sub/logic, T-producing compares                   |
| ALU1     | 1/cycle    | 1       | add/sub/logic, T-producing compares                   |
| Shift    | 1/cycle    | 1       | shll/shlr/shal/shar/rot{c}l/{c}r, SHAD/SHLD           |
| Mul      | 1/cycle    | 3       | muls.w, mulu.w, mul.l, dmuls.l, dmulu.l               |
| MAC      | 1/cycle    | 3+1     | mac.w, mac.l (3-cycle multiply + 1-cycle accumulate)  |
| LSU      | 1/cycle    | 2       | load/store, 1-cycle address gen + 1-cycle d$ access   |
| Div      | 1/16-32    | 16–32   | div1 iterated; non-pipelined                          |
| Branch   | 1/cycle    | 1       | unconditional + cond branch resolution                |

Shift and Mul share a pipe with ALU1 (the second integer pipe) — issuing a shift in cycle N blocks ALU1 in cycle N but not N+1.

The divider is a separate non-pipelined unit attached to ALU0. While a div1 sequence is in flight, ALU0 is unaffected for other ops because each div1 retires in 1 cycle from the OOO scheduler's perspective; the iteration is software-driven.

### 7.1 Multiplier and MAC

The existing `core/mult.vhm` is a 3-cycle multiplier. Reuse. For the MAC accumulate stage, an extra cycle adds the product to MACH:MACL. Total `mac.l` latency: 4 cycles. MACH and MACL are renamed independently, so back-to-back independent MACs (rare in practice) don't false-conflict.

### 7.2 Divider

The SH iterative divide (`div0s`/`div0u`/`div1`) is one-cycle-per-`div1` in the existing J-core. Keep that. The OOO scheduler treats each `div1` as a normal ALU op with a Q/M dependency through SR. The first `div0` writes Q and M, which the subsequent `div1`s read; rename handles the chain.

---

## 8. Load-Store Queue

### 8.1 Structure

- **Load Queue (LQ)**: 12 entries, thread-tagged. Tracks in-flight loads from issue to commit.
- **Store Queue (SQ)**: 12 entries, thread-tagged. Tracks in-flight stores; values held in SQ until commit.

Each LQ entry: address, size, valid bit, finished bit, ROB index, destination physreg, thread_id.
Each SQ entry: address, size, valid bit, data (32 bits), data-valid bit, ROB index, atomic-group bit, thread_id.

### 8.2 Address generation and disambiguation

Loads compute address at issue. Once address is known, the LQ checks against the SQ for in-flight stores to the same address (or unknown-address stores older than this load).

- **Match found, data valid**: store-to-load forward from SQ.
- **Match found, data not valid**: stall load until store data arrives.
- **No match against any known-address older store**: issue load to dcache.
- **Older store with unknown address**: consult memory dependence predictor (§8.4).

### 8.3 Cross-thread isolation

Store-to-load forwarding is allowed only within the same thread. The LSQ check explicitly compares thread IDs along with addresses. Cross-thread aliasing goes through the cache/coherence mechanism, exactly as in SMP.

The atomic-group enforcement (§10) prevents cross-thread memory ops from interleaving across an atomic CAS.L from either thread. When thread A holds the bus lock for its CAS.L, thread B's memory ops queue in the LSQ but do not issue to the dcache until thread A's atomic group completes.

### 8.4 Store-set Memory Dependence Predictor

Per Chrysos & Emer 1998 (ISCA), used in Alpha 21264:

- **Store-Set ID Table (SSIT)**: 1024 entries indexed by load/store PC[11:2], holds 6-bit set ID. Per-thread, or PC index incorporates thread ID.
- **Last-Store Table (LFST)**: 64 entries indexed by set ID, holds ROB index of last in-flight store in that set.
- On a memory order violation (load issued past a store that turned out to alias), the violating load and the offending store get merged into the same store-set.

This predictor recovers the IPC lost by being conservative on unknown-address stores. Without it, every load behind a pending-address store stalls.

### 8.5 Memory order rules (SH-2 weak ordering)

SH-2 doesn't define strict ordering between independent loads and stores. The LSQ may issue loads out of order with respect to each other and with respect to non-aliasing stores. For SMP correctness, the lock signal handles the atomic windows; everything else is fair game.

A `MOV.L` to/from peripheral space may need ordering with respect to other peripheral accesses; this is handled at the bus arbiter, not in the LSQ.

---

## 9. Reorder Buffer and Commit

### 9.1 ROB structure

20 entries, 2-wide allocation/commit, thread-tagged. Each entry:

- `pc` (32 bits) — for exception reporting.
- `op_type` (4 bits) — distinguishes branch, load, store, ALU, etc.
- `dst_logical` (5 bits) — destination architectural register.
- `dst_physical` (6 bits) — destination physreg (or ROB slot self-ref in future-file).
- `value` (32 bits) — result value.
- `valid` (1 bit) — set when result is written.
- `exception` (4 bits) — exception type if any.
- `thread_id` (1 bit) — which thread owns this slot.
- `is_cas_fail_candidate` (1 bit) — set on CAS.L compare-and-store uop.
- `is_sleep` (1 bit) — set on SLEEP.
- `flags` — atomic_group, delay_branch, delay_slot, serializing, branch_mispredict_pending.

### 9.2 Commit logic

Two independent commit ports, one per thread. Each commit port examines its thread's oldest unretired ROB slot in program order; if `valid=1` and `exception=0`, commit up to 2 entries from that thread per cycle. The two threads commit independently — a stalled commit on thread A does not block thread B's commit.

Atomic-group commit: if a uop has `atomic_group_start`, do not commit until the entire group at the head can commit atomically (i.e. all uops of the CAS.L are valid).

On commit (future-file): copy ROB.value into ARF[dst_logical] for that thread; update RAT if it still points at this ROB slot.

### 9.3 Exceptions

Precise per-thread. On exception at commit:

1. Flush the affected thread's ROB, IQ, LQ, SQ entries.
2. Reset the affected thread's RAT to ARF map.
3. Restore the affected thread's SR.BL, set the appropriate exception code.
4. Jump to that thread's VBR + offset for the exception class.
5. The other thread is unaffected and continues executing.

This is precise because the exception is detected at commit, after all older instructions in that thread have already retired.

---

## 10. CAS.L Atomic Handling (Detailed)

**Atomicity mechanism (J32-OOO / J32-FM):** the cache-side actor is the **L2 per-line lock** specified in [cache/l2-spec.md §6](../cache/l2-spec.md), not the legacy bus lock. uop2 (locked load) drives the L1-D to issue `GetM-Locked` to L2; uop3 (conditional store) drives `Unlock` (with new data on T=1, without on T=0). The atomic-group state machine, LSQ enforcement, per-thread auto-priority, and SLEEP interactions below are unchanged from earlier drafts; only the underlying memory-side actor has been replaced. The state-name reuse (`RLOCK1/RLOCK2/WUNCA1/WUNCA2/NEGLCK`) is intentional — the same dcache state machine now drives line-lock messages rather than `db_lock`. The J2 (no-L2) path continues to use bus-lock for backward compatibility.

### 10.1 Existing in-order semantics

The current J32 implementation (`decode/decode_table_simple.vhd` lines 1919–1978) cracks CAS.L into 4 micro-cycles:

1. Save Rn into scratch reg R19.
2. Locked load from `@R0` into Rn (clobbers Rn).
3. Compute `T = (Rn XOR Rm) == 0`, hold lock.
4. If T=1, store R19 to `@R0`, release lock. Advance PC.

The bus lock is held continuously via `ex.mem_lock = '1'` in all four planes, propagated to `db_lock` at `core/datapath.vhm:443` and consumed by `cache/dcache_ccl.vhm`'s state machine (`RLOCK1→RLOCK2→...→WUNCA1→WUNCA2` or `→NEGLCK` on failure).

### 10.2 OOO decode

CAS.L cracks into 3 uops (fusion of original planes 2 and 3 into a single "conditional-store-with-compare" uop):

```
uop1: MOV   prn_temp ← Rn                  ; rename: pdst = new physreg
uop2: LD.L  prn_loaded ← MEM[R0]           ; LOCK; clobbers Rn
       (architectural Rn dest = uop2's pdst)
uop3: CMP_CSTORE  T_new, MEM[R0], Rm, prn_temp
       reads: prn_loaded (=new Rn), Rm, prn_temp, R0
       writes: T_new, conditionally MEM[R0]
       LOCK, atomic_group_end, is_cas_fail_candidate=1
```

All three uops have `atomic_group=1`. uop1 has `atomic_group_start`, uop3 has `atomic_group_end`. uop3 additionally has `is_cas_fail_candidate=1`.

### 10.3 LSQ enforcement

When a uop with `atomic_group_start` is dispatched:

1. The LSQ marks an "atomic pending" flag for that thread.
2. Subsequent memory uops (younger than the atomic group, same thread) cannot issue from the IQ until the atomic group commits.
3. Before issuing uop2 (the locked load), the LSQ drains all older stores for that thread.
4. uop2 issues to dcache with `lock=1`. The dcache state machine takes `IDLE → RLOCK1 → RLOCK2 → IDLE` as today, with `memlock_state := '1'`.
5. uop3 issues only after uop2 has provided the loaded data (the prn_loaded physreg is valid). uop3's conditional store fires through the LSU with `lock=1`, taking the dcache through `WUNCA1 → WUNCA2 → IDLE`. The dcache's `memlock_state` clears at this point.
6. On `T=0` (compare fail), uop3 still issues to the LSU but with the store suppressed; the LSU drops the lock signal one cycle later, triggering `NEGLCK` in the dcache.
7. After uop3 commits, the "atomic pending" flag clears and that thread's younger memory uops can issue.

### 10.4 Per-thread and cross-thread atomic groups

When thread A is in an atomic group, thread B's memory uops continue to queue in the LSQ but do not issue. Thread B's non-memory uops continue to issue and retire normally. As soon as thread A's atomic group commits, thread B's queued memory uops resume issuing.

### 10.5 Auto-priority on CAS.L failure

The retirement stage observes the T-bit outcome of each CAS.L's uop3. The hardware maintains per-thread state:

| State            | Width | Purpose                                            |
| ---------------- | ----: | -------------------------------------------------- |
| `last_cas_pc`    | 32b   | PC of the most recent CAS.L this thread retired    |
| `cas_fail_count` | 3b    | Consecutive same-PC failures, saturating at 7      |
| `prio_dropped`   | 1b    | Whether priority has been auto-dropped              |

Logic at CAS.L commit (uop3 retirement):

- If T=0 (compare failed) and current PC == `last_cas_pc` → increment `cas_fail_count`.
- If T=1 (compare succeeded) → clear `cas_fail_count`; if `prio_dropped` was set, restore priority and clear `prio_dropped`.
- If `cas_fail_count` ≥ 2 and `prio_dropped`=0 → lower thread priority by 1 level, set `prio_dropped`.
- On any far branch (≥ 64 instructions), context switch, or interrupt entry → clear all three state items for the affected thread.

Priority restoration: a successful CAS or a far-branch event restores the thread to its baseline priority. A baseline priority of "medium" (priority level 3 of 7, encoded as 011) is the default and applies to every thread at reset and after any interrupt.

Prior art grounding: this is a Tullsen-family fetch-policy heuristic, semantically equivalent to MISS_COUNT (Tullsen, Lo, Eggers, Levy 1996) but keyed on atomic-failure-history rather than cache-miss-history. The mechanism by which the priority drop affects fetch arbitration is detailed in §13.

### 10.6 SLEEP handling

SH-Compact's SLEEP instruction (opcode 0x001B) puts the executing thread into a wait state until an interrupt is received. The hardware uses this as a strong idle signal:

- When SLEEP is decoded, the issuing thread's priority is immediately set to 0 (lowest).
- The thread is marked as parked. No further fetch occurs from this thread.
- The other thread receives 100% of the fetch and dispatch bandwidth.
- On any interrupt targeted to this thread (or shared, depending on interrupt routing), the thread is woken: priority is restored to its baseline, parked flag clears, fetch resumes from the post-SLEEP PC.

Prior art grounding: POWER5's `HMT_very_low()` in the Linux kernel idle path performs the equivalent operation in software; J32OOO performs it automatically at the SLEEP decode stage.

### 10.7 Performance

Uncontended CAS.L latency: 8–10 cycles (3 uops with the load round-trip dominating). The OOO core overlaps surrounding work, so throughput improves even though latency is unchanged.

Contended CAS.L: bounded by bus arbitration latency for losing a lock contention. Spinning thread auto-drops priority and consumes less front-end bandwidth, accelerating the holder thread's progress.

---

## 11. Cache Hierarchy

The previous in-order J32 ships with 8 KB I-cache and 8 KB D-cache. For 2-way FGMT on the target workload, both threads share the L1 caches and effective per-thread capacity halves (FGMT interleaves threads cycle-by-cycle, so working-set pressure is similar to SMT here). The cache hierarchy is upgraded to accommodate this.

### 11.1 L1 Instruction Cache

| Parameter        | Value                              |
| ---------------- | ---------------------------------- |
| Capacity         | 32 KB                              |
| Associativity    | 4-way set-associative              |
| Line size        | 32 bytes                           |
| Replacement      | Pseudo-LRU (tree-LRU)              |
| Tag width        | (PA[31:13]) 19b                    |
| Next-line prefetch | Yes (always)                     |
| BRAMs (18 Kb)    | ~18 (16 data + 2 tag)              |

Replacement: pseudo-LRU is within 1–2% of true LRU and ~10× cheaper. P6 used this. Cost: 3 bits per 4-way set.

Next-line prefetcher: trivial. On every fetch from line N, if line N+1 is not in the cache, issue a non-blocking prefetch for line N+1. Helps cold dispatch tables and game-emulator opcode handlers. Prior art: Jouppi 1990 stream buffers and IBM mainframe sequential prefetch lineage.

### 11.2 L1 Data Cache

| Parameter        | Value                              |
| ---------------- | ---------------------------------- |
| Capacity         | 32 KB                              |
| Associativity    | 4-way set-associative              |
| Line size        | 32 bytes                           |
| Write policy     | Write-through to L2                |
| Allocation       | Write-allocate                     |
| Replacement      | Pseudo-LRU                         |
| Stride prefetcher | Yes (see §11.4)                   |
| BRAMs (18 Kb)    | ~18                                |

Write policy: write-through to L2 simplifies coherence for SMP, at the cost of L1→L2 write bandwidth. The L2 absorbs writes into its write-back domain.

### 11.3 L2 Unified Cache

| Parameter        | Value                              |
| ---------------- | ---------------------------------- |
| Capacity         | 128 KB                             |
| Associativity    | 8-way set-associative              |
| Line size        | 32 bytes                           |
| Write policy     | Write-back                         |
| Replacement      | Pseudo-LRU                         |
| Hit latency      | 6–8 cycles                         |
| Inclusion        | Inclusive of L1 (simpler invalidation) |
| BRAMs (18 Kb)    | ~68 (64 data + 4 tag)              |

The L2 is the biggest single performance win. For SSH bulk crypto (regular access, large buffers) and JSON parsing (random access within document), 80–95% L2 hit rates are realistic, which means SDRAM bandwidth pressure drops by 5–20×. On ULX3S, where SDRAM is the dominant throughput bottleneck, this directly unblocks the workload.

Pre-2006 prior art: Alpha 21164 (1995) had 96 KB on-die L2; PowerPC 750 (1997) backside L2; AMD Athlon Thunderbird (2000) 256 KB on-die L2.

### 11.4 Stride prefetcher (L1-D)

8-entry per-thread stride table. Each entry tracks last access PC, last address, last delta, and confidence (2-bit counter). On a confirmed stride (two consecutive matching deltas), prefetch the next N=2 strides ahead.

Cost: ~3k gates per thread, ~5–10% IPC win on bulk-data workloads (SSH bulk crypto, packet copy, JSON document scan).

Prior art: Chen & Baer 1995 reference prediction tables; Jouppi 1990 stream buffers.

### 11.5 Cache hierarchy gate/BRAM totals

| Component                          | BRAMs   | LUTs   |
| ---------------------------------- | ------: | -----: |
| L1-I cache (32 KB / 4-way)         |      18 |  4,000 |
| L1-D cache (32 KB / 4-way)         |      18 |  5,000 |
| L2 unified (128 KB / 8-way)        |      68 |  6,000 |
| Stride prefetcher (×2 threads)     |       0 |  3,000 |
| Next-line prefetcher (L1-I)        |       0 |    500 |
| **Total cache subsystem**          | **~104** | **~18,500** |

On ULX3S 85F (208 BRAMs available), ~50% of BRAMs go to cache hierarchy. ~18k LUTs (~22% of 84k LUT capacity). Comfortable.

---

## 12. Performance Monitoring Unit

J32OOO provides a PowerPC 750-class PMU with per-thread shadowing, sized for Linux `perf` integration.

### 12.1 Register layout

Memory-mapped registers in a control region (typical embedded Linux convention). Privileged access only.

| Register         | Width | Purpose                                                    |
| ---------------- | ----: | ---------------------------------------------------------- |
| PMCR             |  32   | Global control: enable, freeze-on-overflow, interrupt-enable, thread-context-select |
| PMSEL0–PMSEL3    |  32   | Event-select for general-purpose counters 0–3 (6-bit event ID + filters) |
| PMCNT0–PMCNT3    |  64   | General-purpose counters                                   |
| PMCYC            |  64   | Fixed cycle counter, free-running                          |
| PMINS            |  64   | Fixed retired-instruction counter                          |
| PMOVF            |  32   | Overflow status, one bit per counter                       |
| PMTID            |   8   | Thread ID select for context-sensitive register reads      |

Per-thread shadowing: each thread has its own copy of all counter registers. The PMTID field selects which thread's view is exposed on register reads. Counter overflow triggers a maskable interrupt to the OS, used by `perf record` for sampling profilers. The overflow wire is a **direct, per-core source line into AIC2** (not routed through the bus fabric) — see [aic/aic2-spec.md §6.4](../aic/aic2-spec.md) for the integration contract and §10 open question #2 for per-counter vs aggregate-overflow source allocation.

### 12.2 Event inventory

A minimum useful event set, sufficient for `perf record`, `perf stat`, `perf top`, `perf annotate`:

| Event ID | Event                          | Notes                            |
| -------- | ------------------------------ | -------------------------------- |
| 0x00     | CPU_CYCLES                     | Same as PMCYC; redundant for convenience |
| 0x01     | INSTRUCTIONS_RETIRED           | Same as PMINS                    |
| 0x02     | BRANCH_INSTRUCTIONS_RETIRED    |                                  |
| 0x03     | BRANCH_MISPREDICTS             |                                  |
| 0x04     | L1_I_ACCESSES                  |                                  |
| 0x05     | L1_I_MISSES                    |                                  |
| 0x06     | L1_D_ACCESSES                  |                                  |
| 0x07     | L1_D_MISSES                    |                                  |
| 0x08     | L2_ACCESSES                    |                                  |
| 0x09     | L2_MISSES                      |                                  |
| 0x0A     | LSQ_FORWARDS                   | Store-to-load forwarding events  |
| 0x0B     | LSQ_STALL_CYCLES               |                                  |
| 0x0C     | ROB_FULL_STALL_CYCLES          |                                  |
| 0x0D     | IQ_FULL_STALL_CYCLES           |                                  |
| 0x0E     | RENAME_STALL_CYCLES            |                                  |
| 0x0F     | CAS_L_RETIRED                  |                                  |
| 0x10     | CAS_L_FAILED                   |                                  |
| 0x11     | LOCKED_BUS_CYCLES              |                                  |
| 0x12     | SMT_THREAD_PRIORITY_DROPS      | §10.5 mechanism observability    |
| 0x13     | SMT_THREAD_FETCH_SLOTS         | Per-thread fetch slot accounting |
| 0x14     | SLEEP_CYCLES                   | Cycles thread is parked in SLEEP |

21 events, within the 6-bit event-select field.

### 12.3 Linux `perf` integration

Add a J32-PMU driver under `arch/sh/kernel/perf_event_j32.c`. The existing SH PMU code structure already supports SH-4A's UBC perf counters and is the template. New code:

- A `struct sh_pmu` populated with the event mapping table (event ID → hardware encoding).
- Counter management (start, stop, read, write).
- Overflow interrupt handler that delivers to `perf_event_overflow()`.

Once added, `perf record`, `perf stat`, `perf top`, `perf annotate`, `perf c2c`, etc. all work without further changes.

### 12.4 Gate cost

| Block                              | Gates       |
| ---------------------------------- | ----------: |
| Counter file (4 GP + 2 fixed) ×2 threads | 6,000 |
| Event-select decoders               |       1,500 |
| Overflow interrupt logic            |         500 |
| Register access path                |       1,500 |
| **Total**                           |     **~9,500** |

On FPGA, ~1,500 LUTs and 0 additional BRAMs (counter state fits in distributed RAM and flip-flops).

---

## 13. Fine-Grained Multi-Threading (FGMT)

J32OOO is 2-way **FGMT** (fine-grained multi-threading): each cycle the front-end selects one of the two hardware thread contexts; that thread's fetch goes to the I-cache and its two decoded uops fill the two issue slots. The backend (rename / ROB / IQ / LSU) is shared with thread tags. Auto-priority adjustment biases the per-cycle selection without software-exposed hints.

This design deliberately rejects SMT (multiple threads issuing uops in the *same* cycle, à la Tullsen 1995 / Intel HT 2002 / POWER5 2004). FGMT is simpler, smaller, and has cleaner pre-2006 prior art (CDC 6600 PPU 1964, Denelcor HEP 1978, Tera MTA 1990, MIT Alewife Sparcle 1993, MIPS 34K ASE 2005, Sun UltraSPARC T1 2005). It matches the threading model in [glossary §4](../glossary.md) and in the companion J2 [dual-fgmt-proposal](../fgmt/dual-fgmt-proposal.md).

The throughput trade-off vs SMT: SMT can fill the second issue slot from the *other* thread when the chosen thread has only one ready uop; FGMT cannot. In return, FGMT eliminates per-cycle cross-thread dependency-tracking and lets most pipeline stages process at most one thread per cycle (cheap thread-tag forwarding, no cross-thread issue-queue arbitration). On SH-2 code, which has frequent delay-slot pairs of independent uops, the lost throughput is modest.

### 13.1 Thread context

Each thread has its own:

- PC and pipelined next-PC (per stage in IF1/IF2/PD).
- Architectural register file (R0–R15, T, S, MACH, MACL, PR, GBR, VBR, SR fields) — 23 logical registers × 32 bits = 92 bytes per thread.
- RAT (23 entries × 6 bits = ~18 bytes per thread).
- Rename-map checkpoints (8 × 23 × 6 bits = ~138 bytes per thread).
- Branch predictor state contribution: per-thread GHR (10 bits) and per-thread RAS (8 entries).
- Priority register (3 bits): current priority level.
- Auto-priority state: `last_cas_pc`, `cas_fail_count`, `prio_dropped`, `parked` (~40 bits total).
- ASID (16-bit `ASID_TAG`, per [glossary §5](../glossary.md)).

Total per-thread state: ~282 bytes. Two threads: ~564 bytes. Fits trivially in distributed RAM and flip-flops.

### 13.2 Thread selection (ready-thread arbitration)

At the IF1 stage, a one-cycle arbiter selects which thread fetches this cycle. A thread is **ready** unless any of:

- It is `parked` (SLEEP, awaiting interrupt — see §13.4 #2).
- It is halted by the MMIO halt-register (analogous to `cpu1en_sbu` in jcore-cpu).
- Its current PC has an outstanding I-cache miss (the other thread can run while this one's miss completes).
- Its ROB partition is full (back-pressure; rare in practice with 20-entry ROB).

Selection among ready threads:

```
if exactly_one_ready:    pick that one
else if both_ready:      pick the one with higher priority_level[t];
                         on tie, alternate (last-served-was-other-thread wins)
else (none ready):       no fetch this cycle (rare; both stalled)
```

`priority_level[t]` is 3 bits (0–7, default 4). Auto-priority adjustments (§13.4) move this without software involvement. This is **ready-thread arbitration**, not ICOUNT: we do not count in-flight uops per thread, because under FGMT a single thread cannot saturate the backend on its own and per-thread ROB occupancy is bounded by per-thread rename pressure, not by issue-bandwidth contention.

Parked threads are excluded from arbitration entirely; the other thread gets 100% of fetch bandwidth.

**Prior art:** UltraSPARC T1 thread scheduler (Kongetira et al. 2005) uses essentially this policy — round-robin among ready threads with per-strand priority tie-breaks. MIT Alewife Sparcle (Agarwal et al. 1993) is the canonical pre-2006 reference for ready-thread arbitration with auto-priority on long-latency events.

### 13.3 Resource sharing

| Resource                | Sharing model                                                       |
| ----------------------- | ------------------------------------------------------------------- |
| Fetch unit              | One thread per cycle, ready-thread arbiter (§13.2)                  |
| Decoder                 | Single-thread per cycle; uops carry thread tag downstream           |
| Rename                  | Per-thread RAT (two RATs)                                           |
| ROB                     | Shared with thread tags; per-thread commit head; both threads commit independently |
| Issue queue             | Shared with thread tags; oldest-ready wins (no per-thread reservation needed under FGMT) |
| Functional units        | Shared; only one issuing thread per cycle, so no cross-thread arbitration |
| LSQ                     | Shared with thread tags; no cross-thread forwarding                 |
| L1 caches               | Shared; no partitioning                                             |
| L2 cache                | Shared; no partitioning                                             |
| Branch predictor tables | Shared with thread-tagged index hashing                             |
| Return address stack    | Per-thread (mandatory)                                              |
| PMU counters            | Per-thread shadowing                                                |

Note vs the v0.2 SMT design: the issue queue no longer needs per-thread reserved entries (each cycle only one thread issues, so a single thread cannot deadlock the other by starving the IQ). This saves ~1k gates and simplifies wake-up logic.

### 13.4 Automatic priority adjustment

Two events nudge per-thread priority without software intervention:

**1. Repeated CAS.L failure (per §10.5).** When a thread fails the same-PC CAS.L ≥2 consecutive times, its priority drops one level (down to a floor of 1). A successful CAS or a far branch restores priority to baseline. Cost: ~200 gates.

Behavior under contention: a spinning thread automatically yields fetch cycles to the holder thread, accelerating the holder's progress and resolving the contention faster. Expected gain on lock-contention microbenchmarks: 15–25% throughput improvement for the productive thread (slightly lower than the SMT projection because FGMT already gives the holder full cycles when the spinner is parked).

**2. SLEEP execution (per §10.6).** When SLEEP is decoded, the thread's priority drops to 0 immediately and the thread is marked `parked`. The other thread receives 100% of fetch bandwidth. On any interrupt routed to the parked thread, priority is restored to baseline and `parked` clears. Cost: ~150 gates. The unpark signal is the `per_tc_pending[t]` bundle exposed by AIC2 directly to the ready-thread arbiter — see [aic/aic2-spec.md §4.3](../aic/aic2-spec.md) for the contract.

No software-exposed priority hint interface is provided in this revision. All priority adjustment is hardware-managed. This is intentional: the two automatic cases (CAS spin, SLEEP) cover the dominant scenarios, and exposing manual hints would require ISA-level changes that we want to defer. (Prior art for software-visible priority hints exists post-2006 in POWER ISA — not citeable under the prior-art policy in [glossary §2](../glossary.md).)

### 13.5 Per-thread cost summary

| Block                                                | Extra gates    |
| ---------------------------------------------------- | -------------: |
| Per-thread state (registers, RATs, ASID, etc.)       |        4,600 |
| Ready-thread arbiter (§13.2)                         |          800 |
| Thread-tagged ROB / IQ / LSQ                         |        4,200 |
| Per-thread BTB tagging and RAS                       |        2,000 |
| Auto-priority logic (CAS.L + SLEEP)                  |          350 |
| Cross-thread isolation checks (LSQ, forwarding)      |        1,500 |
| **Total FGMT incremental cost**                      |   **~13,450** |

Plus the PMU's per-thread shadowing (already counted in §12.4). Net saving vs v0.2 SMT cost (~14,850): ~1,400 gates from the simpler arbiter and no IQ reservation.

### 13.6 Prior art summary

| Mechanism                                | Pre-2006 source                                                             |
| ---------------------------------------- | --------------------------------------------------------------------------- |
| Barrel-style FGMT                        | CDC 6600 PPUs (Thornton, *Design of a Computer*, 1970, describing 1964 design) |
| Cycle-by-cycle context switch on RISC    | Denelcor HEP (Smith 1978–1985)                                              |
| Massive thread interleaving              | Tera MTA (Smith 1990, ISCA papers 1994–1998)                                |
| Switch-on-event / ready-thread variant   | MIT Alewife Sparcle (Agarwal, Kubiatowicz et al. 1993)                      |
| FGMT on commercial in-order RISC         | MIPS MT ASE / 34K (Kissell, MIPS Tech 2005)                                 |
| FGMT on multi-core commercial CPU        | Sun UltraSPARC T1 "Niagara" (Kongetira, Aingaran, Olukotun, IEEE Micro 2005) |
| Per-thread CP0/privileged state model    | MIPS MT VPE concept (2005)                                                  |
| Auto-priority on synchronization stalls  | Alewife block-multithreaded scheduling (1993); HEP spin-wait coalescing (1978) |

---

## 14. SMP

J32OOO is single-core or dual-core SMP with **MSI cache coherence** between per-core L1-D caches and **L2-line-lock atomicity** for CAS.L. The directory and snoop fabric live at the L2; the per-core L1-D state machine in `cache/dcache_ccl.vhm` is repurposed to drive `GetM-Locked` / `Unlock` coherence messages to the L2 in place of asserting the legacy `db_lock` bus signal. See [cache/l2-spec.md §6, §7](../cache/l2-spec.md) for the full protocol.

The bus-lock CAS.L path is retired for J32-OOO and J32-FM (it remains the J2 mechanism on cores without an L2; see [cache/l2-spec.md §6.4](../cache/l2-spec.md)). The atomic-group handling in §10 of this spec is unchanged at the OoO-core level — only the cache-side mechanism that uop2 and uop3 talk to has moved from bus-lock to line-lock.

Under FGMT, both threads on the same core share the same view of memory through the shared L1/L2 caches. Cross-thread synchronization uses the same CAS.L primitive as inter-core synchronization. The L2 line lock is qualified with `{core_id, thread_id}` so an FGMT context switch on the same core does not silently release a sibling thread's lock ([cache/l2-spec.md §6.6](../cache/l2-spec.md)).

---

## 15. Gate Budget Estimate

| Block                            | Gates       |
| -------------------------------- | ----------: |
| Fetch + I-cache control + BTB    |       14,000 |
| Branch predictor + RAS           |       10,000 |
| Decode + uop crack               |       18,000 |
| Rename + RAT + checkpoints (per-thread) |    18,000 |
| ROB (20 entries)                 |       26,000 |
| Issue queue (16 entries)         |       20,000 |
| ARF + register read              |       10,000 |
| ALU pipes ×2                     |       12,000 |
| Shift + Mul + Div                |       18,000 |
| LSU + LQ + SQ + store-sets (per-thread tagged) |  26,000 |
| Commit + retire RAT              |       10,000 |
| FGMT machinery (§13)             |       13,450 |
| PMU (§12)                        |        9,500 |
| Misc (bypass, control, debug)    |       17,000 |
| **Subtotal (CPU core)**          |  **221,950** |
| Cache subsystem (§11)            |       18,500 |
| Existing SoC glue                |        8,000 |
| FPU (deferred — see [../fpu/spec.md](../fpu/spec.md), Tier 1) |            – |
| MMU (deferred, separate spec)    |            – |
| **Total core + caches**          |  **248,450** |

On ULX3S 85F (estimates — **awaiting empirical validation**, see §15.1):

- ~35–45k LUTs for the core + caches (~50% of 84k LUT capacity)
- ~104 BRAMs (~50% of 208 BRAMs) — **stale**; reconcile with [cache/l2-spec.md §20.1](../cache/l2-spec.md) which counts ~141 EBRs (~70%) for dual-core L1+L2 alone
- 2–3 DSP slices

### 15.1 Caveat — synthesis validation required

The 248,450-gate total above is an a-priori block estimate, converted to LUTs with an assumed ratio of ~5–7 gates/LUT4. Two consumers of this number (this section's "~35–45k LUTs" claim, and the [service plan's §5 LUT4 budget](../jcore-ulx3s-service-plan.md)) currently disagree by ~4× with the service-plan narrative claim of "~10K LUT4 per core" — see the "OoO LUT-count uncertainty" subsection in the service plan §5 for the full discussion of the three options and the Phase 6 decision-gate.

**Action item before Phase 6 RTL commits:** synthesize a representative OoO subset (rename + ROB + 1 ALU + L1$) on ECP5-6 with nextpnr; measure actual LUT4 count; update this section with the empirical number; reconcile with the service plan and the L2 v2 spec BRAM estimate. Until that measurement exists, treat both the ~35–45k LUT figure and the "~10K LUT4 per core" figure as bounds, not predictions.

Plenty of headroom for SoC peripherals (Ethernet, UART, GPIO, SDRAM controller).

---

## 16. Reusable Existing Code

| File                                          | Status                                            |
| --------------------------------------------- | ------------------------------------------------- |
| `cache/icache.vhd`, `cache/icache_*.vhm`      | Largely rewritten for 32 KB / 4-way SA (was 8 KB / direct-mapped) |
| `cache/dcache.vhd`, `cache/dcache_ccl.vhm`    | Rewritten for 32 KB / 4-way SA; lock state machine preserved verbatim |
| `cache/dcache_mcl.vhm`                        | Reviewed for L2 interface; mostly reused          |
| New: L2 cache controller                       | Written from scratch; ~6k gates                   |
| New: Stride prefetcher                         | Written from scratch                              |
| `core/register_file.vhd`                      | Replaced (per-thread ARF)                         |
| `core/mult.vhm`, `core/mult_pkg.vhd`          | Reused as the Mul FU                              |
| `core/datapath.vhm`                           | Largely rewritten; bus-output `db_lock` path reused verbatim |
| `decode/decode_body.vhd`                      | Reused as predecode for instruction classification |
| `decode/decode_table_simple.vhd`              | Used as reference for uop cracking; new emitter generates FGMT-tagged uops |
| `decode/decode_core.vhm`                      | Replaced                                          |
| `sim/sh2instr.c`                              | Reused as reference model for verification        |
| `testrom/tests/*.s`                           | Reused for compliance testing (including CAS.L atomicity tests at `testmov.s:580-635`) |
| `tests/*.vhd`                                 | Reused for FU-level testing                       |
| New: PMU + Linux driver                       | Written from scratch (PMU: ~10k gates; driver: ~1k lines C) |

---

## 17. Verification Plan

### 17.1 Tiered approach

1. **FU-level**: existing test taps (`tests/arith_tap.vhd` etc.) verify ALU, shift, mul, div correctness. Unchanged.
2. **uop-level**: new testbench for rename, ROB, IQ, LSQ, atomic groups, FGMT thread tagging.
3. **Architectural**: run `testrom/tests/*.s` against the OOO core. CAS.L atomicity test in `testmov.s` (lines 580–635) is the regression test for atomic-group enforcement. Run with 2-way FGMT both enabled and disabled.
4. **Compliance**: SH-2 reference model in `sim/sh2instr.c` runs in lockstep with the OOO core. Mismatches at retirement halt simulation.
5. **Stress**: Linux boot, Dhrystone, CoreMark, atomic-heavy SMP tests (kernel locking primitives, libatomic), SSH-bulk-data, JSON parsing benchmarks.

### 17.2 FGMT-specific test corpus

- **Thread isolation tests**: each thread runs an independent test program; verify no cross-thread state corruption.
- **CAS.L contention tests**: two threads CAS.L the same address in a tight loop; verify atomicity and forward progress.
- **CAS.L auto-priority validation**: thread A spins on a futex; thread B does useful work; measure thread B's IPC with auto-priority enabled vs. disabled; expect 20–30% gain.
- **SLEEP auto-priority validation**: thread A enters SLEEP; thread B continues; verify thread B receives ~100% of fetch slots and IPC matches single-threaded baseline.
- **PMU validation**: each event counter is exercised by a microbenchmark with a known expected count; verify counter accuracy and per-thread isolation.
- **Cache hierarchy tests**: L1-I, L1-D, L2 hit/miss counts validated against working-set-sized workloads. Stride prefetcher hit rate validated on linear-scan benchmark.
- **Linux `perf` integration**: boot Linux, run `perf stat -e cycles,instructions,L1-dcache-misses` on a known workload, verify counters return sensible values.

---

## 18. Open Decisions and Future Work

1. **Way prediction in I-cache and D-cache**: 5–10% energy win, 1–2% IPC win. Defer.
2. **Macro-op fusion beyond CAS.L**: cmp+branch fusion (K7 1999), test+branch. Worth ~5% IPC. Defer.
3. **Software-exposed priority hints**: deferred. If experience with hardware-only auto-priority shows benefit gaps, add POWER5-style `HMT_*` macros in a future revision.
4. **TAGE-class branch predictor**: TAGE is 2006 (just at the cutoff); a tournament predictor today, possible upgrade later.
5. **Hardware stride detector tuning**: 8-entry table sizing may be wrong for some workloads; revisit after benchmarking.

---

## 19. Implementation Phasing

| Phase | Scope                                                                  | Est. effort |
| ----- | ---------------------------------------------------------------------- | ----------: |
| P0    | Architecture spec finalized (this doc) + microarch review              |     1 month |
| P1    | Single-thread OOO prototype: rename + ROB + IQ + 1 ALU + 1 LSU         |    4 months |
| P2    | Add second ALU pipe, T-rename, branch predictor, RAS                   |    3 months |
| P3    | Atomic groups (CAS.L), LSQ with store-sets, MAC                        |    2 months |
| P4    | FGMT integration: thread tagging, ready-thread arbiter, per-thread state |    2 months |
| P5    | Cache hierarchy: 32 KB L1 caches, 128 KB L2, prefetchers               |    2 months |
| P6    | PMU: counter file, event-select, overflow interrupt, Linux driver      |   1.5 months |
| P7    | Auto-priority: CAS.L spin detection, SLEEP handling                    |   0.5 months |
| P8    | Verification + Linux boot + perf tuning                                |    3 months |
| P9    | FPGA bring-up on ULX3S 85F                                             |    2 months |
| P10   | Tapeout-ready ASIC version                                             |    3 months |

Total: ~24 months for J32OOO with this scope.

---

## Appendix A: SH-Compact Instructions by uop Count

**1 uop** (single-cycle): most ADD/SUB/AND/OR/XOR/CMP, MOV reg-reg, MOV.L/W/B reg-mem-disp, branches, SLEEP.

**2 uops**: LDS/STS .L variants (load/store + transfer), some bit instructions (TAS.B), MOV.L @(disp,PC) when in delay slot.

**3 uops**: CAS.L (with fusion).

**4 uops**: MAC.L, MAC.W, RTE, DIV (sequence).

**Multi-cycle iterative**: DIV (32 cycles), SLEEP (until wake interrupt — see §10.6).

**Serializing**: LDC Rm,SR; LDC.L @Rm+,SR; LDC Rm,VBR; LDC Rm,GBR (partial); TRAPA.

## Appendix B: Glossary

- **ARF** — Architectural Register File. Committed state. Per-thread under FGMT.
- **BTB** — Branch Target Buffer.
- **FGMT** — Fine-Grained Multi-Threading. See [glossary §4](../glossary.md). Project-wide canonical term.
- **GHR** — Global History Register. Per-thread under FGMT.
- **IQ** — Issue Queue.
- **LFST** — Last-Fetched Store Table.
- **LQ** — Load Queue.
- **LSU** — Load-Store Unit.
- **MAC** — Multiply-Accumulate.
- **NEGLCK** — Negate Lock (dcache state for releasing bus lock without a write).
- **PMU** — Performance Monitoring Unit.
- **RAS** — Return Address Stack. Per-thread under FGMT.
- **RAT** — Register Alias Table. Per-thread under FGMT.
- **ROB** — Reorder Buffer.
- **SQ** — Store Queue.
- **SSIT** — Store-Set ID Table.
- **T-bit** — SH-Compact condition flag (SR bit 0).
- **WUNCA** — Write UNCAched (dcache state for locked writes).
