# J32OOO — Out-of-Order J-Core Implementation Specification

**Status:** Draft v0.2.1
**Compatible ISA:** SH-Compact (SH-2 + J-core extensions: SHAD, SHLD, CAS.L)
**Scope:** CPU core, cache hierarchy, and performance monitoring. FPU (see [../fpu/spec.md](../fpu/spec.md), Tier 1 required for the J32-OOO product point), MMU, IOMMU/DMA, SIMD, and crypto coprocessor blocks are specified separately.

**J32OOO** is a 2-wide fetch, 2-wide commit OOO core with 2-way FGMT, 32-bit datapath.

> **Sibling design point.** [J32-LT](j32lt-spec.md) covers the same ISA and MMU with in-order issue, no register renaming, no issue queue, and 4-way barrel FGMT. It targets throughput per joule where this document targets single-thread latency, at comparable area (~220k vs ~222k gates). Neither supersedes the other. Several mechanisms deferred here (§18) are specified there. Targets the "J32-FM" roadmap slot (~250k ASIC gates including caches and PMU). See [glossary §3–§4](../glossary.md) for product-point and threading naming.

## Changelog

- **v0.5** (2026-08): Hypervisor extension ([hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md)) brought into scope of §20. `DOM` replaced by `{PDID, SR.HPRIV, SR.MD, tid}` (§3.2, §20.10) — the previous `ASID_TAG[7:0]` form shared a predictor domain between host and guest (VMScape) and discarded the ASID generation field that guest-to-guest separation depends on. Added: non-speculative device/aperture/uncacheable regions (§8.2b), `HCALL`/`HRTE` serialization and the complete-on-resume writeback rule (§4.7), unresolved-PA and mode-snapshot rules (§9.4 rules 4–5), commit-attributed predictor updates (§3.2), per-context hypervisor and store-queue state (§13.1, §20.12), the folded-P1 escape (§20.11), and core-granular tenancy (§20.3).
- **v0.4** (2026-08): Added §20, the transient-execution security model, and the mechanisms it requires: domain-tagged predictor indices (§3.2), delay-on-miss (§8.2), permission-resolved load forwarding (§9.3), commit-only predictor and prefetcher training (§3.2, §11.4), a speculation barrier (§4.6), a predictor-invalidate control (§20.4), and an SSB disable for store-sets (§8.4). Every added mechanism carries a pre-2006 citation; §20.7 records the two patent shapes that are deliberately **not** implemented.
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
6. Ship a **stated and verified transient-execution security model** (§20) rather than inheriting the default outcome of every open OoO core to date. Mitigations must satisfy the [glossary §2](../glossary.md) prior-art policy on the same terms as every performance mechanism.

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
| Address-space-tagged lookup state                | MIPS R4000 ASID-tagged TLB 1991; SH-4 hardware manual 1998 |
| Withholding a memory access until speculation resolves | Intel US6035393 (priority 1995, expired)         |
| Deferred-exception token on a speculative load    | IA-64 control speculation `ld.s`/NaT/`chk.s` (Itanium 1999–2001) |
| Serializing / speculation-barrier instruction    | PowerPC `isync`; SPARC v9 `MEMBAR #Sync` (1994)       |
| Invalidate-array control bit                     | SH-4 `CCR.ICI` / `CCR.OCI` (SH-4 hardware manual 1998) |
| Predictor disturbance across context switches    | Two branch-predictor schemes under frequent context switches (1998); OPTS (2002) |
| Shared-cache leakage between hardware threads    | Percival, *Cache Missing for Fun and Profit*, BSDCan 2005; Kocher 1996 |

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

McFarling tournament predictor with **domain-tagged** history. The tag is not the thread ID alone: it is the *security domain* identifier

```
DOM = { PDID[5:0], SR.HPRIV, SR.MD, thread_id }      -- 9 bits
```

`PDID` is the **predictor domain ID** (§20.10), a hyperprivileged control register written by the hypervisor at world switch and by the kernel at `switch_mm`. `SR.HPRIV` is a separate *hardware* term and is deliberately not folded into `PDID`: a hypervisor that fails to update `PDID` must still be unable to share a predictor domain with the guest it just trapped from. See §20.2 for the attack this closes and §20.10 for why the earlier `ASID_TAG[7:0]` formulation was wrong.

- 1024-entry **bimodal table** (2-bit saturating counters), indexed by `PC[10:1] XOR DOM`.
- 1024-entry **gshare table**, indexed by `PC[10:1] XOR GHR[9:0] XOR DOM`. GHR is per-thread (2 × 10 bits).
- 1024-entry **chooser table** (2-bit counters).
- Total state: ~1 KB plus per-thread GHR.

**BTB**: 32-entry, 4-way set-associative, tagged with PC bits **and the full `DOM` field**. A BTB hit requires a domain match; a domain mismatch is a miss, not a weaker prediction.

**RAS**: per-thread, 8-entry circular stack, each entry carrying its `DOM` at push time. On a pop whose entry `DOM` does not match the current domain, the RAS prediction is discarded and the BTB (or no prediction) is used instead. Cross-thread *and* cross-privilege corruption is avoided; the latter is what closes the return-stack transient-execution path (§20.2).

**Update policy**: all four structures (bimodal, gshare, chooser, BTB, RAS) are updated **only from committed instructions**. Squashed instructions leave no predictor state behind. The per-thread GHR keeps a speculative working copy for indexing plus a committed copy restored on squash — the standard speculative-history-repair arrangement, here doing double duty as the mechanism that prevents a squashed path from training the tables.

**The `DOM` used to index an update is the one captured with the instruction at rename** and carried in its ROB entry (§9.1) — never the live register value at write time. Commit-only training alone does not give this: an instruction retiring in the same window as a world switch would otherwise train the domain it is leaving *into* the domain it is entering. This is the race exploited by Branch Privilege Injection (§20.2). Cost: `DOM` width added to the uop and the ROB entry; the speculative-history-repair machinery already carries per-instruction predictor context for unrelated reasons.

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
| BL, RB, MD, **HPRIV** | bits 28–30, **14** | priv group | Privileged; writes are serializing  |

A `stc SR, Rn` reads all groups and constructs a 32-bit value. An `ldc Rn, SR` writes all groups; treat as serializing (drain ROB, single dispatch).

`SR.HPRIV` ([hypervisor/hardware-spec.md §2.1](../hypervisor/hardware-spec.md)) is in the privileged group and is therefore never speculatively renamed. It gates every hyperprivileged register check, the guest-mode translation override, and the emulation aperture; a speculatively-visible value for it would be a guest→host escape rather than a leak (§20.11). `HCALL` and `HRTE` (§4.7) are serializing for the same reason.

### 4.6 Speculation barrier

The architecture needs one instruction that software can rely on to bound speculation, or no software mitigation can be expressed and no compiler intrinsic has a lowering target. J32OOO defines:

- **`SPB`** — speculation barrier. No instruction younger than `SPB` in program order executes (not merely *commits*) until `SPB` retires. Implemented with the existing `serializing` uop flag (§4.3): drain the ROB, single-dispatch, hold fetch redirect until retirement.
- Candidate encoding: `0x003B`, the unassigned member of the `0000000000nn1011` family that already holds `RTS` (`0x000B`), `SLEEP` (`0x001B`) and `RTE` (`0x002B`). **Encoding requires ISA-owner sign-off** before it is treated as fixed; the semantics above do not depend on which slot is chosen.
- `SPB` is unprivileged. It is the lowering target for `__builtin_speculation_safe_value` in the `sh-linux` GCC port and the primitive underneath the array-index masking idiom of §20.6.

`SPB` is architecturally a no-op with an execution-ordering constraint; it may be encoded freely in code that must also run on cores without it, where it decodes as an illegal instruction — so the kernel and libc must gate its use on a CPU-capability check rather than assuming it.

Prior art: serializing instructions with exactly this "nothing younger executes until this completes" semantic are pre-2006 and ubiquitous — PowerPC `isync`, SPARC v9 `MEMBAR #Sync` (1994), IBM S/370 serialization, x86 `CPUID`.

### 4.7 Hypervisor mode transitions

`HCALL` and `HRTE` ([hypervisor/hardware-spec.md §3.1, §3.2](../hypervisor/hardware-spec.md)) are **serializing**, for three separate reasons that all land on the same requirement:

1. They write `SR.HPRIV`, which is in the privileged rename group (§4.5).
2. They change the address-translation regime: under [hypervisor/hardware-spec.md §4.4.1](../hypervisor/hardware-spec.md) a guest's P1/P2 are translated, while at `SR.HPRIV = 1` they are folded (`PA = VA & 0x1FFFFFFF`) with no translation and no permission check. An access that used a stale `HPRIV` would read host physical memory directly (§20.11).
3. `HRTE` carries the complete-on-resume register writeback ([hypervisor/hardware-spec.md §4.5](../hypervisor/hardware-spec.md) rule 2): hardware writes `HMDR` into the architectural register named by `HMCR.REGN`/`BANK`, sign- or zero-extended per `HMCR.SIZE`.

**Rule for the writeback (rule 3).** It is performed **at `HRTE`'s commit**, writing the destination thread's ARF entry directly and resetting that register's RAT entry to point at the ARF. It is not a bypassed result and never enters the ROB as a producer. An out-of-band ARF write performed while the RAT still redirects readers to an in-flight ROB slot would be silently lost — the hypervisor spec's writeback port assumes a machine with one register file and no rename map, and this is what that assumption costs on an OOO core. The same rule applies to [j32lt-spec §6.6](j32lt-spec.md)'s future-file RAT.

`HCALL` is unprivileged (any mode may execute it), so it is also a serialization point reachable from guest user code; the cost is a drained ROB per hypercall, which the hypercall's own trap entry would have forced anyway.

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

### 8.2a Delay-on-miss

A load that **misses in the L1-D and is still speculative does not issue to the L2 or to memory.** It occupies its LQ entry and waits until it becomes non-speculative — all older branches in its thread resolved, no older instruction able to except — at which point the miss is issued normally.

- L1-D **hits** are unaffected and proceed speculatively at full speed. The overwhelming majority of loads hit, so the common path is untouched.
- The rule is a condition on **MSHR allocation**, not a new structure: no filter buffer, no shadow cache, no deferred promotion, no rollback. A speculative miss simply does not allocate.
- Consequence: no line fill, no L2 lookup, no replacement-state update and no coherence traffic is ever caused by a load that does not commit. This is the property that closes the cache covert channel of §20.2, and it closes it for L1, L2, replacement metadata and the coherence fabric simultaneously.
- Cost: a speculative miss that would have overlapped with the branch resolution now serializes behind it. This is the single largest performance item in §20 and the OOO core pays it more heavily than [j32lt-spec §7.4a](j32lt-spec.md) does, because there is no third and fourth thread to occupy the stall. §20.5 makes it a measurement gate rather than an assumption, and §20.8 records the fallback.
- Interaction with the store-set predictor (§8.4): unchanged. A load that is delayed for §8.2a reasons and a load that is delayed for store-set reasons wait in the same LQ entry for different conditions; whichever clears last releases the load.

**Prior art:** Intel **US6035393** (Glew & Gupta, priority 1995-09-11, **expired**) claims stalling a prefetch operation "until either the dummy instruction retires, or a misprediction of a previous branch is detected" — withholding a memory access performed on behalf of a speculative instruction until the speculation is resolved. The motivation there was avoiding side effects on uncacheable memory-mapped I/O rather than avoiding a timing channel; the mechanism is the one specified here. See also non-blocking-load throttling in Farkas & Jouppi 1994. §8.2b is the case where that patent's original motivation applies to us literally as well.

### 8.2b Non-speculative regions

Delay-on-miss (§8.2a) delays L1-D **misses**. Device space is not cacheable, so a load to it never allocates and §8.2a never engages. A second, stronger rule therefore covers it:

> An access whose translated physical address lies in **P4**, in the **emulation aperture** (`(PA & HEMUM) == HEMUB`, [hypervisor/hardware-spec.md §2.5](../hypervisor/hardware-spec.md)), or in a page mapped **uncacheable** (`PTEL.C = 0`) is **never issued speculatively**, hit or miss. It waits at its LQ/SQ entry until it is the oldest un-retired access of its thread, then issues.

Three things this closes, none of which §8.2a reaches:

1. **Real side effects.** A speculative load of a device register is a real read of a real device. This is why architectures have always refused to speculate into device space, and it is the exact hazard US6035393 was filed against.
2. **Aperture capture-register corruption.** [hypervisor/hardware-spec.md §4.5](../hypervisor/hardware-spec.md) has hardware write `HPAR`, `HMCR` and `HMDR` on an aperture match. Under this rule the comparator is evaluated, and those registers are written, **only for an access that has become non-speculative** — so a squashed access can neither corrupt the parameters of a genuine trap nor present the hypervisor's device model with an address the guest never actually accessed.
3. **Aperture-layout disclosure.** A guest cannot probe for the aperture boundaries by timing squashed accesses, because a speculative access never reaches the comparator.

**Prefetchers do not enter these regions at all.** A prefetch whose target translates into P4, the aperture, or an uncacheable page is **dropped silently** — not issued, and never a trap source. The §11.4 page-boundary rule does not cover this: P4 begins on a page boundary like any other, and a stride walking upward reaches it legitimately.

**Cost.** ~300 gates: a region predicate on the translated PA, and a reuse of §8.2a's "oldest un-retired" condition. The performance cost is nil on the workloads that matter — device accesses are already slow and already serialized by their own semantics.

### 8.3 Cross-thread isolation

Store-to-load forwarding is allowed only within the same thread. The LSQ check explicitly compares thread IDs along with addresses. Cross-thread aliasing goes through the cache/coherence mechanism, exactly as in SMP.

The atomic-group enforcement (§10) prevents cross-thread memory ops from interleaving across an atomic CAS.L from either thread. When thread A holds the bus lock for its CAS.L, thread B's memory ops queue in the LSQ but do not issue to the dcache until thread A's atomic group completes.

### 8.4 Store-set Memory Dependence Predictor

Per Chrysos & Emer 1998 (ISCA), used in Alpha 21264:

- **Store-Set ID Table (SSIT)**: 1024 entries indexed by load/store PC[11:2], holds 6-bit set ID. Per-thread, or PC index incorporates thread ID.
- **Last-Store Table (LFST)**: 64 entries indexed by set ID, holds ROB index of last in-flight store in that set.
- On a memory order violation (load issued past a store that turned out to alias), the violating load and the offending store get merged into the same store-set.

This predictor recovers the IPC lost by being conservative on unknown-address stores. Without it, every load behind a pending-address store stalls.

**Both tables are indexed with the `DOM` field of §3.2 folded into the PC index**, and both are updated only from committed memory operations, for the same reasons as the branch predictor.

**Speculative-store-bypass disable (`SSBD`).** A privileged control bit forces the predictor to answer "aliases" for every query, so no load may bypass an older store of unknown address. Setting it costs IPC and closes the store-bypass transient path (§20.2) outright. It exists because the mechanism this section specifies *is* speculative store bypass, and a core that ships it needs a documented way to turn it off for code that cannot tolerate it. `SSBD` is per-thread. Note that [j32lt-spec §7.3](j32lt-spec.md) has no equivalent because it has no address speculation to disable — that is a genuine security advantage of the in-order-issue design point and not merely an area saving.

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
- `dom` (9 bits) — the security domain (§3.2) captured at rename; indexes predictor updates at commit and selects the translation regime for memory ops (§9.4 rules 4–5).
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

### 9.4 Squash and fault rules that the security model depends on

Precision at commit is an *architectural* property. It says nothing about what a squashed or faulting instruction leaves behind microarchitecturally, and three rules are therefore stated explicitly here rather than left implied:

1. **A squash cancels microarchitectural work, not just architectural state.** In addition to flushing the ROB/IQ/LQ/SQ entries of §9.3, a squash deallocates MSHRs allocated by squashed loads whose fills have not yet returned, and cancels prefetches generated by squashed loads. Without this, §8.2a leaks through the MSHR and prefetch paths.
2. **No structure is trained by a squashed instruction.** Branch predictor, BTB, RAS, store-set tables and stride tables update at commit only (§3.2, §8.4, §11.4).
3. **Permission-resolved forwarding.** A load may not forward a value to a dependent uop until its translation and permission check has resolved. A load that faults — TLB miss, protection violation, or any condition that will raise at commit — forwards a **poison** result; a dependent uop that consumes poison produces poison and, critically, may not use it to form an address or a branch condition. Poison is discarded at squash and raises at commit exactly as §9.3 describes.

4. **No cache lookup on an unresolved physical address.** No L1 or L2 tag comparison, fill, or validation may proceed with a physical address that is not the output of a completed and permitted translation. In particular, an access in flight while its translation is still being walked does not present a partially-formed `pa_tag` to a PIPT cache. This is the L1-Terminal-Fault shape — a not-present translation whose PA field is nonetheless used to probe the cache — and J-Core has met it before: an I-side fetch reaching the PIPT I-cache with an undefined `pa_tag` during a walk was tagged and validated at MISS1, producing silent wrong instructions. That instance was fixed and the D-side was measured clear, but the *rule* existed nowhere, so nothing prevented a new pipeline from reintroducing it. It is stated here for that reason.

5. **Every memory access carries the `SR.HPRIV` and `SR.MD` snapshot of its own instruction**, taken at rename, and uses it to select the translation regime. A pending change to either makes younger accesses non-speculative — which §4.7's serialization of `HCALL`/`HRTE` already provides, but which is stated as an invariant here because the consequence of violating it is not a leak: under [hypervisor/hardware-spec.md §4.4.1](../hypervisor/hardware-spec.md) a guest's P1 is translated while a hypervisor's P1 is folded to a physical address with no permission check, so an access executed under a stale `HPRIV` reads host memory directly (§20.11).

   Rule 3 is what keeps a permission-failing load from feeding a transient address calculation once the MMU is integrated. It is stated in this document, not only in the MMU specification, because the two are written independently and this rule belongs to whichever pipeline forwards the value. Prior art: IA-64 control speculation, where `ld.s` deposits a NaT deferred-exception token instead of faulting, computational instructions propagate NaT, and `chk.s` recovers (Itanium, 1999–2001); and, more simply, ordinary in-order SH-4 discipline in which the permission check is part of the load's execution rather than a commit-time afterthought.

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

Three constraints, all of them security-motivated and none of them costly:

- **Trained by committed loads only.** A squashed load never enters the stride table (§9.4 rule 2).
- **Prefetches do not cross a page boundary.** A stride that would run off the end of the page terminates instead. Stream buffers have behaved this way since Jouppi 1990 for translation reasons; here it also bounds what a mistrained stride can touch.
- **Prefetches into P4, the emulation aperture, or an uncacheable page are dropped silently** (§8.2b) — not issued, never a trap source. The page-boundary rule does not imply this: P4 starts on a page boundary like any other and a legitimate upward stride reaches it.
- **Per-thread disable bit**, and the table is cleared by the predictor-invalidate control of §20.4.

The next-line prefetcher of §11.1 is subject to the same page-boundary rule.

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
| 0x15     | SPEC_MISS_DELAY_CYCLES         | Cycles loads spent waiting to become non-speculative (§8.2a). **The delay-on-miss cost meter.** |
| 0x16     | SPEC_MISS_DELAYED              | Loads that were delayed at least one cycle by §8.2a |
| 0x17     | PREDICTOR_INVALIDATES          | §20.4 control writes; validates that the kernel hook actually fires |
| 0x18     | RAS_DOMAIN_MISMATCH            | RAS pops discarded on domain mismatch (§3.2) |

25 events, within the 6-bit event-select field.

**Every counter in this table counts committed events only.** A counter that increments on squashed work is an architectural readout of another domain's speculation — strictly worse than the timing channel it summarises, because it states the answer at one load with no prime-and-probe and no noise. [hypervisor/design-spec.md §6](../hypervisor/design-spec.md) already makes this argument for the TSB-walker counters at `0xFF000054` and requires the hypervisor to virtualize or deny them; the same reasoning binds every counter here, and applies in hardware rather than being left to hypervisor policy.

**Counters 0x12, 0x13, 0x15–0x18 are cross-thread observable** — they expose the timing of a sibling thread's behaviour. The PMU is privileged-access-only (§12.1), and `PMTID` must not be exposed to unprivileged code by any driver or `perf` configuration. Do not relax this to make user-space profiling more convenient.

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
- ASID (16-bit `ASID_TAG`, per [glossary §5](../glossary.md)) and `PDID` (6 bits, §20.10).
- **Hypervisor context (§20.12):** `SR.HPRIV`, `HSPC`, `HSSR`, `VBR_HYP`, `HEDR`, `HEMUB`, `HEMUM`, `HPAR`, `HMDR`, `HMCR`, `HSQCR` — ~42 bytes.
- **Store queue (§20.12):** two 32-byte buffers plus `QACR0`/`QACR1` — 72 bytes.
- MMU fault state per [j32lt-spec §11](j32lt-spec.md)'s table: `PTEH`, `TSBPTR`, `TEA`, `MMUFSR`, `PTEL`, `EXPEVT`, `SPC`, `SSR` — ~32 bytes.

Total per-thread state: ~428 bytes. Two threads: ~856 bytes. Still fits in distributed RAM and flip-flops.

The last three groups are all consequences of one rule: **anything the hypervisor specification calls "per-vCPU" is per thread context here**, because FGMT runs two vCPUs concurrently rather than switching between them, and a save/restore sequence has no exit to run at. §20.12 gives the full list and the reasoning.

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
| Security mechanisms (§20.5)      |        8,400 |
| Misc (bypass, control, debug)    |       17,000 |
| **Subtotal (CPU core)**          |  **230,350** |
| Cache subsystem (§11)            |       18,500 |
| Existing SoC glue                |        8,000 |
| FPU (deferred — see [../fpu/spec.md](../fpu/spec.md), Tier 1) |            – |
| MMU (deferred, separate spec)    |            – |
| **Total core + caches**          |  **256,850** |

On ULX3S 85F (estimates — **awaiting empirical validation**, see §15.1):

- ~35–45k LUTs for the core + caches (~50% of 84k LUT capacity)
- ~104 BRAMs (~50% of 208 BRAMs) — **stale**; reconcile with [cache/l2-spec.md §20.1](../cache/l2-spec.md) which counts ~141 EBRs (~70%) for dual-core L1+L2 alone
- 2–3 DSP slices

### 15.1 Caveat — synthesis validation required

The 256,850-gate total above is an a-priori block estimate, converted to LUTs with an assumed ratio of ~5–7 gates/LUT4. Two consumers of this number (this section's "~35–45k LUTs" claim, and the [service plan's §5 LUT4 budget](../jcore-ulx3s-service-plan.md)) currently disagree by ~4× with the service-plan narrative claim of "~10K LUT4 per core" — see the "OoO LUT-count uncertainty" subsection in the service plan §5 for the full discussion of the three options and the Phase 6 decision-gate.

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

### 17.3 Security corpus

Gates S1–S6 of §20.8 are part of the verification plan, not a separate activity, and S5 (the delay-on-miss cost measurement) gates Phase 6 in the same way G-series gates do in [j32lt-spec §12.2](j32lt-spec.md).

---

## 18. Open Decisions and Future Work

1. **Way prediction in I-cache and D-cache**: 5–10% energy win, 1–2% IPC win. Defer. Also deferred in [j32lt-spec.md §14.6](j32lt-spec.md), though the trade is more attractive there given its energy-first goal.
2. **Macro-op fusion beyond CAS.L**: cmp+branch fusion (K7 1999), test+branch. Worth ~5% IPC. Defer. **Specified in full in [j32lt-spec.md §4.2](j32lt-spec.md)** (`CMP`/`TST`/`DT` + `BT`/`BF`), where it is load-bearing rather than optional because in-order dual issue cannot otherwise fill the second slot; the mechanism transfers to this core unchanged if the deferral is revisited.
3. **Software-exposed priority hints**: deferred. If experience with hardware-only auto-priority shows benefit gaps, add POWER5-style `HMT_*` macros in a future revision.
4. **TAGE-class branch predictor**: TAGE is 2006 (just at the cutoff); a tournament predictor today, possible upgrade later. Note the opposite move in [j32lt-spec.md §3.5](j32lt-spec.md): a *single* gshare table with BTFNT-seeded counters, dropping the bimodal and chooser arrays entirely. That is affordable there because 4-way FGMT absorbs most of a mispredict's cost (other threads occupy the refill cycles), which is not true at 2-way — so the predictor choice does not transfer in this direction.
5. **Hardware stride detector tuning**: 8-entry table sizing may be wrong for some workloads; revisit after benchmarking.
6. **Delay-on-miss cost (§8.2a)**: the one security mechanism whose cost is not small and not yet measured. Gate S5 (§20.8) decides. If it exceeds 20% aggregate, the options are, in order: restrict the delay to loads whose address derives from a value produced under an unresolved branch (a narrower trigger, not a weaker one); accept the loss; or reconsider the design point in favour of [j32lt-spec](j32lt-spec.md), where §7.4a costs materially less. Adding a speculative fill buffer is **not** an option — see §20.7.
7. **Core-granular tenancy (§20.3)**: adopted deliberately, and the weakest link in the security model, since it is enforced by a scheduler — the hypervisor's under virtualization, Linux's otherwise — rather than by hardware. Gang scheduling ([hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)) recovers tenant density over time, so the cost is now scheduling latency and a cold cache per quantum rather than a halved tenant count. If a future product point needs mutually distrusting *concurrently resident* contexts, the levers are per-thread L1 way partitioning and per-thread predictor arrays, at a cost that would substantially undo the FGMT gain. Do not adopt it silently. Note the L2 is a separate problem with a separate answer already adopted: [cache/l2-spec.md §16.1](../cache/l2-spec.md).
8. **`SPB` encoding (§4.6)**: `0x003B` is a candidate, not a decision. Needs ISA-owner sign-off alongside the [isa-density](../isa-density/spec.md) encodings.

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
| P7.5  | Security mechanisms (§20): `DOM` tagging, delay-on-miss, poison forwarding, squash cleanup, invalidate control, `SPB` | 1.5 months |
| P8    | Verification + Linux boot + perf tuning, incl. security gates S1–S6 (§20.8) |    3 months |
| P9    | FPGA bring-up on ULX3S 85F                                             |    2 months |
| P10   | Tapeout-ready ASIC version                                             |    3 months |

Total: ~25.5 months for J32OOO with this scope.

---

## 20. Security Model — Transient Execution

### 20.1 Why this section exists

Every open out-of-order core published since 2018 has shipped Spectre-vulnerable and been shown to be so afterwards: BOOM in [Gonzalez et al., CARRV 2019](https://boom-core.org/docs/replicating_mitigating_spectre_carrv19.pdf) (v1 bounds-check bypass and v2 branch-target injection), BOOM again for BTI and RSB in [Le et al. 2022](https://arxiv.org/pdf/2206.04507), BOOM cross-process through the shared cache, and XiangShan for v1 in 2026. In each case the exposure was a consequence of ordinary microarchitecture — predict, execute past the prediction, leave a trace in the cache — and not of any unusual design choice. J32OOO has all three ingredients, so the default outcome is the same one, and §20 exists to make the outcome a decision rather than an accident.

The mitigations here were selected under the [glossary §2](../glossary.md) prior-art policy; §20.7 records what was rejected and why, which is as load-bearing as what was adopted.

### 20.2 Threat model

**In scope.** Two mutually distrusting security domains — user vs kernel, process vs process, or **thread vs sibling FGMT thread** — where one attempts to read the other's data through a microarchitectural channel using mispredicted or otherwise transient execution. Concretely:

| Path | Ingredient in this core | Closed by |
|---|---|---|
| Bounds-check bypass (v1) | conditional branch prediction + speculative load | §8.2a, §20.6 |
| Branch target injection (v2) | shared/aliasing BTB and PHT | §3.2 `DOM` tagging, §20.4 |
| Return-stack transient | untagged RAS entries across domains | §3.2 RAS domain tag |
| Speculative store bypass (v4) | store-set predictor (§8.4) | §8.4 `SSBD` |
| Permission-failing load feeds a transient address | fault detected at commit (§9.3) | §9.4 rule 3 |
| Cross-thread cache/TLB/predictor contention | shared L1/L2/BP/TLB (§13.3) | §20.3 — **by policy, not by hardware** |
| **Cross-thread issue-bandwidth contention** | the ready-thread arbiter (§13.2) gives a stalled thread's fetch slots to the other, so one thread's stalls appear as the other's speed-up | §20.3 — by policy; see §20.2a |
| **Cross-tenant L2 contention** | one set of L2 arrays serves both cores ([cache/l2-spec.md §2](../cache/l2-spec.md)), so core-granular tenancy does not reach it | [cache/l2-spec.md §16.1](../cache/l2-spec.md) way-partitioning |
| **Guest trains the hypervisor's indirect branches** (VMScape) | predictor shared across `SR.HPRIV` | §3.2, §20.10 |
| **Guest trains another guest's branches** | no VMID; ASID partitioning is the only separator | §20.10 `PDID` |
| **Predictor update crosses a world switch** (Branch Privilege Injection) | update applied after the domain changes | §3.2 update policy, ROB-carried `DOM` |
| **Speculative access to an emulated device or P4** | aperture comparator on a speculative PA; device reads have side effects | §8.2b |
| **Guest folds P1 to host physical memory** | mode-dependent address path (§4.4.1 of the hypervisor spec) | §20.11 — *escape, not leak* |
| **One vCPU reads another's store-queue bytes** | SQ buffers per-CPU, FGMT contexts concurrent | §20.12 — *not a speculation bug* |

**Out of scope, explicitly.** Physical attacks, power and EM analysis, Rowhammer, fault injection, and pure (non-transient) timing analysis of *committed* execution — a victim whose committed control flow or memory access pattern depends on a secret leaks through the cache with or without speculation. That is a software property; the reference is Kocher 1996 and [Percival 2005](https://www.daemonology.net/papers/htt.pdf), both pre-2006, and the answer is constant-time code, not microarchitecture.

Note the dates: the *attack* class in the last row is pre-2006 public knowledge. Percival demonstrated key recovery across a shared L1 between two hardware threads on one core in 2005 and observed that it applies "to any system where caches are shared between two or more non-mutually-trusted execution threads". That is a precise description of §13.3.

### 20.2a The issue-bandwidth channel

The cache and TLB channels of §20.2 need prime-and-probe apparatus. FGMT has a more direct one that does not.

The ready-thread arbiter (§13.2) drops a thread from the ready set when it is parked, halted, waiting on an I-cache miss, or backed up at the ROB; the other thread then receives the fetch slots. One thread's stalls are therefore the other's measurable speed-up, as a direct function of the arbiter's input rather than as an emergent property of a shared array. The auto-priority mechanism of §13.4 adds a second, coarser version of the same signal: a thread that drops its priority on repeated CAS.L failure hands fetch bandwidth to its sibling, and event `0x12 SMT_THREAD_PRIORITY_DROPS` reports that it did.

The PMU makes it loud rather than subtle. `PMCYC`/`PMINS` give an observer its own IPC, and events 0x12, 0x13, 0x15 and 0x16 are more direct still. They are privileged, but a tenant owns its guest kernel, so privilege is not the boundary here. This is the argument [hypervisor/design-spec.md §6](../hypervisor/design-spec.md) already makes about the TSB walker counters — a counter that *states* cross-domain behaviour beats the timing channel it summarises, needing no apparatus and carrying no noise.

**Not separately mitigated.** Removing it means decoupling thread selection from the other thread's readiness, which is the mechanism §13.2 exists to provide. §20.3's tenancy rule is the answer: observer and victim are the same tenant. What the design does do is keep the channel narrow — §8.2a removes its cache-state half, so a stalled thread leaks stall *timing* but not the addresses behind it.

At 2-way the channel is weaker than [j32lt-spec §16.2a](j32lt-spec.md)'s: with only two threads there is one bit of ready-set state to observe rather than a four-valued *k*.

### 20.3 The FGMT sharing decision — the core is the unit of tenancy

§13.3 shares the L1 caches, L2, predictor tables, TLB and MSHRs between the two threads, while §13 presents those threads to Linux as two CPUs. **These two statements are only compatible if co-resident threads are same-trust.**

J32OOO takes that position deliberately, and states it as an allocation rule rather than a scheduling hint:

> **A physical core is the unit of tenant allocation *at any instant*. Every thread context of a core belongs to the same tenant — the same virtual machine, or the same trust domain on an unvirtualized system — for as long as that tenant is resident. A tenant that needs only one vCPU is given a whole core, with the sibling contexts idle or running that same tenant's other vCPUs.**

A core may be shared between tenants **over time**, provided the transition is a gang switch: all contexts change tenant together, with the predictor, L1 and TLB invalidations of [hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md) at the boundary. Gang scheduling raises the number of tenants a board can host; it never raises the number that run at one instant, which is what this rule bounds.

The consequence is arithmetic and should be read off directly: at any instant a dual-core J32-OOO board runs **two tenants of up to two vCPUs each**, not four tenants of one. [j32lt-spec §16.3](j32lt-spec.md) hosts two tenants of up to four vCPUs each. Under the hypervisor extension the scheduler that must enforce this is the hypervisor's, not Linux's, and it belongs in admission control ([hypervisor/hardware-spec.md §4.7](../hypervisor/hardware-spec.md)); [jcore-ulx3s-service-plan.md §3](../jcore-ulx3s-service-plan.md) carries the corrected tenant count.

The alternative — partitioning or flushing the shared structures per thread — costs most of what the second thread earns, on a design point whose entire justification is throughput per area. The exposure being accepted is pre-2006 documented: [Percival 2005](https://www.daemonology.net/papers/htt.pdf) recovered an RSA key across a shared L1 between two hardware contexts of one core, and observed that it applies "to any system where caches are shared between two or more non-mutually-trusted execution threads". The rule above is what makes that observation inapplicable rather than unaddressed.

What the hardware still provides, so the policy is enforceable and auditable:

- Cross-thread store-to-load forwarding is prohibited structurally (§8.3).
- The `DOM` field (§3.2) includes the thread ID, so predictor state is not *shared* between threads even though the arrays are.
- The predictor-invalidate control (§20.4) can be issued for either thread.
- PMU events (§12.2) expose cross-thread interference so the policy can be tested rather than assumed.

This must be stated in the Linux port documentation, not only here. A kernel that schedules two containers on the two contexts of one core is operating the part outside its specification.

### 20.4 Predictor invalidate control

A single privileged control-register bit per thread. Writing 1 invalidates, in one action, that thread's bimodal, gshare and chooser entries, its BTB entries, its RAS, and its stride-prefetch table. The bit self-clears. The kernel writes it on address-space switch and on exit from a domain more privileged than the one being entered.

**Under virtualization this is defence in depth, not the primary mechanism.** The x86 answer to cross-domain predictor training is IBPB on every VM exit, which costs roughly 10% on emulated-device workloads because tagging is absent and the barrier is all there is. Here §3.2's `DOM` already carries `SR.HPRIV` and `PDID`, so host and guest occupy different predictor domains by construction and no per-exit barrier is required for correctness. The invalidate therefore stays a **policy** choice: a hypervisor that does not trust its own `PDID` discipline may set a per-guest control bit that issues the invalidate on every world switch, and pays for it; the default does not. This ordering — tag first, barrier optional — is the whole reason to have specified `DOM` properly.

Three constraints on the implementation, and they are not stylistic:

1. **Software-triggered only.** The hardware does not detect security-domain transitions and does not act on them by itself.
2. **Unconditional and complete.** One action, everything cleared. No modes, no partial subsets, no progressive re-enabling as a reset proceeds.
3. **No save/restore.** Predictor state is discarded, never preserved and reloaded.

Prior art: the control is modelled directly on **SH-4 `CCR.ICI` and `CCR.OCI`** (SH-4 hardware manual, 1998), which invalidate the instruction and operand caches by a privileged register write. The desirability of clearing predictor state across context switches is pre-2006 in the literature (Two branch-predictor schemes under frequent context switches, 1998; OPTS, 2002). See §20.7 for why constraints 1–3 are written as requirements.

### 20.5 What this costs

| Mechanism | Area | Performance |
|---|---|---|
| `DOM`-tagged predictor index (§3.2) | ~250 gates (wider hash, wider BTB tag) | Slight — a wider tag reduces BTB capacity pressure aliasing in one direction and increases cold-start misses in the other |
| RAS domain tags (§3.2) | ~200 gates | Negligible; a discarded pop falls back to BTB |
| Commit-only training (§3.2, §8.4, §11.4) | ~0 (the GHR repair copy already exists) | Small predictor-accuracy loss on tight loops |
| **Delay-on-miss (§8.2a)** | **~400 gates** (a condition on MSHR allocation) | **The dominant item — see below** |
| Permission-resolved forwarding (§9.4) | ~600 gates (poison bit through bypass and LQ) | Negligible once the MMU walker resolves in the common case |
| Squash cleanup (§9.4) | ~500 gates | Negligible |
| `SSBD` (§8.4) | ~50 gates | Only when set |
| `SPB` (§4.6) | ~150 gates (reuses `serializing`) | Only where software uses it |
| Predictor invalidate (§20.4) | ~1,200 gates (clear ports on five arrays) | Cost is the post-invalidate cold predictor, paid at context switch |
| PMU events 0x15–0x18 (§12.2) | ~800 gates | — |
| `PDID` register and wider `DOM` tags (§20.10) | ~600 gates | as above |
| `DOM` carried through uop and ROB (§3.2, §9.1) | ~150 gates | — |
| Non-speculative region gating (§8.2b) | ~300 gates | nil — device accesses are already serialized by their own semantics |
| `HRTE` writeback through ARF+RAT (§4.7) | ~200 gates | one drained ROB per hypercall and per MMIO trap resume |
| Per-context hypervisor registers + store queue (§20.12) | **~3,000 gates** | — |
| **Total** | **~8,400 gates** (~3.7% of the core) | |

Delay-on-miss is the whole performance question. The published estimate for the technique's family is single-digit to low-double-digit percent on an OoO core, and J32OOO has 2-way FGMT to absorb part of it but not the four contexts that [j32lt-spec §7.4a](j32lt-spec.md) has. **This is a measurement, not a projection** — see §20.8 gate S5. If it lands badly, the fallback is not to weaken the mechanism but to reconsider the design point, because the mechanism has no cheaper form.

### 20.6 Software contract

The hardware mitigations above close the microarchitectural paths. Software still owns the gadget:

- **Array index masking.** After a bounds check, mask the index with a value derived from the check rather than relying on the branch. This is the standard v1 idiom and needs no hardware support.
- **`SPB` (§4.6)** where masking is not expressible: between a bounds check and the dependent access. GCC's `__builtin_speculation_safe_value` lowers to the mask-plus-`SPB` sequence in the `sh-linux` port.
- **`SSBD` (§8.4)** for code that cannot tolerate store-bypass speculation.
- **Predictor invalidate (§20.4)** on address-space switch, from the existing `switch_mm` hook.
- **Core scheduling** per §20.3.

The kernel must gate all four on a CPU capability bit; J2 and J32 in-order parts have none of them.

### 20.7 Mechanisms deliberately not implemented

The [glossary §2](../glossary.md) prior-art policy exists because J-Core's value proposition is patent freedom. For transient-execution defences the policy needs care, because the *structures* involved are frequently pre-2006 while the *security-triggered combination* is recent and claimed. Two rejections follow from that, and both are requirements on future revisions, not merely notes:

1. **No L0 speculative filter cache.** The obvious alternative to §8.2a is a small buffer that catches speculative fills and promotes them into L1 only when the load becomes non-speculative, clearing on squash and on domain switch — the SpecBuf shape proposed for BOOM in CARRV 2019, and the MuonTrap shape. The *structure* is thoroughly pre-2006: Jouppi 1990 stream buffers and Cray US5761706 (filed 1994, expired) hold prefetched blocks outside the cache; Intel US6223258 (filed 1998, expired) services a non-temporal load from a dedicated buffer "without accessing said cache". The combination that makes it a Spectre defence is not, and is claimed by live patents (Microsoft US11061824, priority 2019, deferring cache state update with a speculative buffer until non-speculative; and neighbouring split-cache and reserved-set variants). **Do not implement this**, and do not "optimise" §8.2a into it by adding a buffer for delayed misses.
2. **The predictor-invalidate control keeps the shape of §20.4.** Hardware detection of a domain transition combined with a multi-mode, progressively re-enabled reset is claimed (SiFive US11429392, priority 2018). Save/restore of predictor state across context switches is claimed (Arm US10838730; Microsoft US11068273). The plain software-triggered unconditional invalidate is what SH-4's `CCR.ICI` has done to a different array since 1998. **Do not add transition detection, modes, or save/restore.**

Similarly, §9.4 rule 3 is written as an ordering constraint on load forwarding and **not** as taint bits on architectural registers with a policy register selecting which speculation features to disable, which is the AMD US10956157 shape.

The general rules, which belong in [glossary §2](../glossary.md) rather than here: prior art matches at the level of **mechanism, not motivation** — a claim covers structure and steps, so US6035393's 1995 stall-until-speculation-resolves reads on §8.2a regardless of why it was filed; and conversely a pre-2006 *structure* is necessary but not sufficient when the security-specific *combination* is separately claimed.

This analysis is a documentation exercise, not a freedom-to-operate opinion. The two load-bearing findings — US6035393 as the §8.2a anchor and US11061824 as the reason for rejection 1 — warrant a professional search before Phase 6 RTL commits.

### 20.8 Verification gates

Added to §17. Each is a pass/fail gate, not an inspection.

| # | Gate | Method | Threshold |
|---|---|---|---|
| S1 | v1, v2 and RSB proof-of-concepts fail | Port the `riscv-boom/boom-attacks` PoCs to SH-Compact; run in cosim | Secret not recovered above the noise floor |
| S2 | v4 PoC fails with `SSBD` set, succeeds with it clear | Directed test | Both directions observed |
| S3 | No speculative fill | RTL assertion: no L1/L2 tag, valid or replacement-state change attributable to a load that is still speculative | Zero violations across the full regression |
| S4 | Cross-thread channel bounded | Thread A attempts to observe thread B's secret-dependent access pattern via shared L1/TLB/BP | Consistent with the §20.3 same-trust policy; measured and recorded, not assumed zero |
| S5 | **Delay-on-miss cost** | PMU 0x15/0x16 plus CoreMark, Dhrystone, SSH bulk crypto, JSON parse, 1 and 2 threads | **Report the number. <10% aggregate IPC loss is the target; >20% escalates to §20.5's design-point question** |
| S6 | Negative controls | For each of S1–S5, corrupt the expected constant or disable the mitigation and confirm the test **does** detect the leak | Every security test proven non-vacuous |
| S7 | **Guest cannot train host predictions** | A guest trains an indirect branch at the virtual address of a hypervisor dispatch site; measure the hypervisor's misprediction rate at that site with and without the guest's training loop | No measurable difference — the VMScape regression |
| S8 | **Guest cannot train another guest's** | Same, across two guests in different ASID ranges and different `PDID`s, including a pair whose `ASID_TAG` values differ only above bit 7 | No measurable difference — the truncation regression |
| S9 | **No speculative device access** | RTL assertion: no bus request, no aperture comparison, and no `HPAR`/`HMCR`/`HMDR` write for an access that is not the oldest un-retired access of its thread (§8.2b). Plus a directed test with a mispredicted branch over a load from the aperture | Zero violations; capture registers unchanged after the squash |
| S10 | **Mode-snapshot invariant** | Directed: a guest memory access issued in the shadow of an unresolved `HRTE`; check it uses the guest's translation regime, never the folded-P1 path (§20.11) | No access resolves through P1 folding under `SR.HPRIV = 0` |
| S11 | **Store-queue context isolation** | Two contexts running different vCPUs each fill SQ0 and burst; each burst contains exactly its own 32 bytes (§20.12) | Byte-exact, both directions |
| S12 | **Counters count committed events only** | Run a workload with a high mispredict rate; compare every §12.2 counter against the architectural event count from the reference model | Exact match, no over-count |

S6 is not optional. The MMU guard suite in this project once false-passed six sub-tests that had never executed; a security test that cannot fail is worse than no test, because it is believed.

### 20.10 `PDID` — predictor domain ID

> **SUPERSEDED BY [../mmu/hardware-spec.md §2.1a](../mmu/hardware-spec.md) (one premise only) — 2026-08-25.**
> "**Why not a truncated ASID**" below argues from
> `ASID_TAG`'s top-4-bit generation discriminator, citing `glossary §5`. **That
> field no longer exists** —
> **RESOLVED 2026-08-25 — linux@jcore: "sh: jcore: retire the ASID generation nibble"** —
> and the glossary is no longer an authority for values
> ([../decisions/0001](../decisions/0001-one-authority-per-fact.md)); the owner
> is [../mmu/hardware-spec.md §2.1a](../mmu/hardware-spec.md).
>
> **The conclusion stands on its other leg.** Truncating to `ASID_TAG[7:0]` no
> longer "discards the generation field", but it still discards `ASID[11:8]` —
> "half the range" in the text is in fact 15/16ths of it — and guests are still
> separated **only** by ASID range partitioning, there being no VMID. Two guests
> in different ASID ranges can still collide in the predictor index by
> construction. So `PDID` is still needed and truncation is still wrong; the
> sentence *"the single mechanism guest-to-guest separation rests on"* is now the
> **range**, not the generation field.
>
> Not re-derived here — Wave-1 **C0** owns the security argument. Flagged so a
> reader does not inherit the reasoning along with the conclusion.

The domain identifier `DOM` of §3.2 needs a source. It cannot be `ASID_TAG` alone, for two reasons that only become visible once the hypervisor extension is in scope.

**Why not `SR.MD` and the ASID alone.** [hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md) does not change `ASIDR` on trap entry, so the hypervisor executes with whatever `ASID_TAG` the guest left in it. Host and guest would share a predictor domain, and a guest could train the branch target of the HCALL dispatcher, the `LDTLB` trap handler, or the emulated-MMIO device model — all of which run at `SR.HPRIV = 1` on addresses the guest chose. This is [VMScape (CVE-2025-40300)](https://comsec.ethz.ch/research/microarch/vmscape-exposing-and-exploiting-incomplete-branch-predictor-isolation-in-cloud-environments/) exactly, where the finding was that "the branch predictor cannot distinguish between host and guest execution" on every AMD Zen generation.

**Why not a truncated ASID.** An earlier revision of §3.2 used `ASID_TAG[7:0]`. `ASID_TAG` is 16 bits of which the top 4 are the generation discriminator ([glossary §5](../glossary.md)), and guests are separated **only** by ASID range partitioning — the design has no VMID, deliberately ([hypervisor/hardware-spec.md §12](../hypervisor/hardware-spec.md)). Truncating discards the generation field and half the range, so two guests in different ASID ranges can collide in the predictor index by construction. The truncation threw away the single mechanism guest-to-guest separation rests on.

**The register.**

| | |
|---|---|
| Width | 6 bits (64 predictor domains) |
| Access | Hyperprivileged. Joins the [hypervisor/hardware-spec.md §2.2](../hypervisor/hardware-spec.md) LDC/STC family in slot 10; guest access raises `EXPEVT = 0x1F0` like every other register in that family |
| Written by | The hypervisor at world switch; the kernel at `switch_mm` on an unvirtualized system |
| Per | Thread context (§20.12) |
| Reset | 0 |

`SR.HPRIV` is a **hardware** term of `DOM` and is deliberately *not* folded into `PDID`: a hypervisor that forgets to update `PDID` must still be unable to share a predictor domain with the guest it just trapped from. The escape path fails closed in hardware; only the guest-to-guest path depends on software discipline, and that path is software's to own anyway since ASID allocation already is.

Six bits rather than the full 19-bit `{ASID_TAG, HPRIV, MD, tid}` because folding 19 bits into a 10-bit index buys nothing over a well-chosen 6, and the BTB tag has to carry the field in full. A short software-written domain number indexing microarchitectural state is precisely the sun4v context-register model this project already adopted: `PRIMARY_CONTEXT`/`SECONDARY_CONTEXT` with the hyperprivileged nucleus context distinct from any guest context (UltraSPARC Architecture 2005, hyperprivileged edition), and ASID-tagged lookup state from MIPS R4000 (1991) and SH-4 (1998).

### 20.11 Guest-mode translation and the folded-P1 escape

[hypervisor/hardware-spec.md §4.4.1](../hypervisor/hardware-spec.md) forces translation on for a guest's P0–P3, overriding `MMUCR.AT`. At `SR.HPRIV = 1`, P1 and P2 are *folded* instead — `PA = VA & 0x1FFFFFFF`, no TLB, no permission check.

So the address path is mode-dependent, and the two modes differ by whether a permission check happens at all. An access that executed under a stale `HPRIV` — issued before an older `HRTE` resolved — would fold a guest virtual address straight onto host physical memory. **That is a guest→host escape, not a leak**, and it is the one place in this specification where getting speculation wrong loses the isolation boundary outright rather than leaking through a channel.

Three rules already stated elsewhere close it, and are collected here because each alone is insufficient: §4.5 puts `SR.HPRIV` in the privileged rename group; §4.7 makes `HCALL`/`HRTE` serializing; §9.4 rule 5 requires every access to carry its own instruction's `HPRIV`/`MD` snapshot from rename.

This is independent of [hypervisor/hardware-spec.md §4.4.5](../hypervisor/hardware-spec.md)'s pinned guest P1 mappings. That rule restores the *non-faulting-handler* proof; this one determines *which translation path* an access takes. Both are needed and neither implies the other.

### 20.12 Per-context hypervisor state

[hypervisor/hardware-spec.md](../hypervisor/hardware-spec.md) describes `HEMUB`, `HEMUM`, `HPAR`, `HMDR`, `HMCR` and `HSQCR` as "per-vCPU state, saved and restored across VM exit and entry". That is correct for a core that runs one vCPU at a time. **FGMT runs two concurrently** — there is no exit at which to save.

Therefore every register the hypervisor specification calls per-vCPU is **per thread context** here:

| Register | Hazard if shared |
|---|---|
| `SR.HPRIV` | one context's mode gates the other's translation regime — §20.11 |
| `HSPC`, `HSSR` | context B's trap destroys the resume state of context A's |
| `VBR_HYP`, `HEDR` | one vCPU's delegation policy applied to another's traps |
| `HEMUB`, `HEMUM` | one vCPU's device map applied to another's accesses |
| `HPAR`, `HMDR`, `HMCR` | context B's aperture trap overwrites the capture registers context A's hypervisor is about to consume |
| `HSQCR`, **the two 32-byte SQ buffers, `QACR0`/`QACR1`** | see below |
| `PDID` | §20.10 |

**The store queue is the serious one, and it is not a speculation bug.** [sq/spec.md](../sq/spec.md) gives the core two 32-byte buffers at `0xE0000000`/`0xE0000020`, and [hypervisor/hardware-spec.md §4.4.3](../hypervisor/hardware-spec.md) carves them out of the guest-mode P4 trap precisely so guests can use them at native speed. With two contexts resident, two vCPUs write the *same* buffer; their bytes interleave, and whichever issues the `PREF` bursts a mixture of both tenants' data to its own physical target. That is a direct cross-VM disclosure and corruption on the hot path the carve-out exists to accelerate, with no misprediction involved anywhere. §20.3's core-granular tenancy makes the two contexts the same tenant and so bounds the damage, but it does not make the behaviour correct even within one tenant's pair of vCPUs.

Cost: ~42 bytes of hypervisor registers plus 72 bytes of store queue per additional context — ~3,000 gates at 2-way. [j32lt-spec §16.12](j32lt-spec.md) pays this three times over, which is the largest single security cost in either design.

This is the same correction [j32lt-spec §11](j32lt-spec.md) already made for `PTEH`/`TEA`/`MMUFSR`/`TSBPTR`, extended to the Phase 3 register set; the reasoning is identical and so is the failure mode — silent installation or attribution of one context's state to another.

### 20.13 Prior-art summary

| Mechanism | Pre-2006 source |
|---|---|
| Domain-tagged lookup state, `PDID` (§3.2, §20.10) | sun4v `PRIMARY_CONTEXT`/`SECONDARY_CONTEXT` with a distinct hyperprivileged nucleus context (UltraSPARC Architecture 2005, hyperprivileged edition); MIPS R4000 ASID-tagged TLB (1991); SH-4 hardware manual (1998) |
| No speculative access to device space (§8.2b) | Intel US6035393 (priority 1995, **expired**) — the patent's *literal* motivation was preventing speculative prefetch to uncacheable MMIO; SH-4's architectural P1/P2 cached/uncached split (1998) |
| Mode transitions serialized (§4.7, §20.11) | PowerPC `isync`; IBM S/370 serialization; SH-4 exception-entry semantics (1998) |
| Per-context privileged state (§20.12) | the argument [j32lt-spec §11](j32lt-spec.md) already applies to `PTEH`/`TEA`/`MMUFSR`; sun4v per-vCPU hyperprivileged state (2005) |
| Commit-time predictor update (§3.2) | Speculative-history repair literature, 1996–1998 |
| Delay-on-miss (§8.2a) | Intel US6035393, priority 1995-09-11, **expired** — stall the access until the marker retires or a mispredict is detected; Farkas & Jouppi 1994 |
| Poisoned speculative load result (§9.4) | IA-64 control speculation, `ld.s` / NaT / `chk.s` (1999–2001); Smith & Pleszkun 1985 precise exceptions |
| Speculation barrier (§4.6) | PowerPC `isync`; SPARC v9 `MEMBAR #Sync` (1994); IBM S/370 serialization |
| Array-invalidate control bit (§20.4) | SH-4 `CCR.ICI` / `CCR.OCI` (1998) |
| Clearing predictor state across context switches (§20.4) | Two branch-predictor schemes under frequent context switches (1998); OPTS (2002) |
| Prefetch bounded at page boundary (§11.4) | Jouppi 1990 stream buffers; Cray US5761706 (filed 1994, expired) |
| Threat model (§20.2) | Kocher 1996; Percival, *Cache Missing for Fun and Profit*, BSDCan 2005 |
| L2 way partitioning by tenant ([cache/l2-spec.md §16.1](../cache/l2-spec.md)) | MIT column caching, Chiou et al. 1999–2000; US6370622 (filed 1998, expired); Suh & Devadas 2002–2004 |
| Gang scheduling of a core's contexts ([hypervisor/hardware-spec.md §4.7.1](../hypervisor/hardware-spec.md)) | Ousterhout, "Scheduling Techniques for Concurrent Systems", ICDCS 1982 |

---

## Appendix A: SH-Compact Instructions by uop Count

**1 uop** (single-cycle): most ADD/SUB/AND/OR/XOR/CMP, MOV reg-reg, MOV.L/W/B reg-mem-disp, branches, SLEEP.

**2 uops**: LDS/STS .L variants (load/store + transfer), some bit instructions (TAS.B), MOV.L @(disp,PC) when in delay slot.

**3 uops**: CAS.L (with fusion), RTE (pop SR, pop PC, branch).

**4 uops**: MAC.L, MAC.W, DIV (sequence).

> **SUPERSEDED BY [§4.1](#41-architecture-to-uop-mapping) — 2026-09-07.**
> This appendix previously listed `RTE` under **4 uops**, against §4.1's
> per-instruction table, which gives it 3 and says which three. §4.1 is the
> normative mapping and [j32lt-spec §4.1](j32lt-spec.md) already cites it as 3;
> this appendix is a summary derived from that table, so the table wins.

**Multi-cycle iterative**: DIV (32 cycles), SLEEP (until wake interrupt — see §10.6).

**Serializing**: LDC Rm,SR; LDC.L @Rm+,SR; LDC Rm,VBR; LDC Rm,GBR (partial); TRAPA.

## Appendix B: Glossary

- **ARF** — Architectural Register File. Committed state. Per-thread under FGMT.
- **BTB** — Branch Target Buffer.
- **`DOM`** — security-domain identifier `{PDID[5:0], SR.HPRIV, SR.MD, thread_id}`, used to tag and index every predictor structure (§3.2) and carried per instruction in the ROB. Not the thread ID alone.
- **`PDID`** — Predictor Domain ID (§20.10). Hyperprivileged 6-bit register naming the current security domain; written by the hypervisor at world switch and the kernel at `switch_mm`.
- **Delay-on-miss** — a load that misses L1 while still speculative does not issue to L2 until it is non-speculative (§8.2a). A condition on MSHR allocation, not a structure.
- **Poison** — the value a faulting or permission-unresolved load forwards in place of data; propagates to dependents, may not form an address or branch condition, raises at commit (§9.4).
- **`SPB`** — speculation barrier (§4.6): nothing younger than it executes until it retires.
- **`SSBD`** — speculative-store-bypass disable (§8.4).
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
