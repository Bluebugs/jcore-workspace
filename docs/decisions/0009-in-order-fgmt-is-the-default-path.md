# 0009 — Dual-issue in-order + 2-thread FGMT is the default path; OoO RTL pauses

**Status:** Accepted 2026-09-08. Wave-2 task **B3**, from
[j4-remediation-plan.md §B3](../j4-remediation-plan.md).

---

## Why this record is here and not inline in a spec

[README](README.md) states the rule: *a decision goes inline in its owning spec
whenever there is one*, and this directory exists only for decisions with **no**
owning spec. Applied here, one test is dispositive and two more agree with it.

- **There is no owning spec, because the thing being made the default has no
  spec.** Dual-issue in-order with 2-thread switch-on-miss FGMT is specified
  nowhere in this workspace. [fgmt/dual-fgmt-proposal.md](../fgmt/dual-fgmt-proposal.md)
  and [fgmt/mt2x2-plan.md](../fgmt/mt2x2-plan.md) are the **J2 line** and say so
  in their own scope notes: single-issue, the existing 5-stage pipeline, `N_TC =
  2`. [ooo/j32lt-spec.md](../ooo/j32lt-spec.md) is dual-issue and in-order at
  *issue*, but with out-of-order completion through a 32-entry ROB and a 4-way
  barrel. [ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md) is the design this record
  pauses. A decision cannot be written inline in a document that does not exist,
  and choosing one of the three to host it would be exactly the arbitrary hosting
  the README warns about.
- **The two specs it most affects are the two it pauses.** A record pausing
  `j32ooo-spec.md`, hosted inside `j32ooo-spec.md`, is not findable by a reader
  of `j32lt-spec.md` — which it also pauses — and the reverse holds too.
- **The service plan is a plan.** [jcore-ulx3s-service-plan.md](../jcore-ulx3s-service-plan.md)
  sequences work and carries no normative authority; it is not written under
  [0002](0002-supersede-convention.md)'s supersede discipline. A reversible
  decision whose whole value is that its reopening trigger stays legible needs a
  document where the trigger survives the next re-sequencing.

This is the shape of [0006](0006-endianness-is-big-endian.md): a product-line
direction with no owning subsystem. It is **not** the shape of the bi-endian
decisions BE-1 to BE-3, which the README puts inline precisely because they
specify a *mechanism* and [bi-endian-spec.md](../bi-endian-spec.md) owns it.
This record specifies no mechanism. It allocates effort between three specs that
already exist and reorders a roadmap.

---

## Context

### What the plan directs

[§B3](../j4-remediation-plan.md) assigns the out-of-order-versus-FGMT question
to this task and states the intended answer, with the evidence base at
[§E.1](../j4-remediation-plan.md): the small OoO core cannot hide 30–50-cycle
SDRAM latency, which is the job used to justify it; it is far larger on the
ECP5; and its `[ASIC]` energy is concentrated in the issue-queue CAM and rename
logic it adds. §E.9 restates it in one line. The plan asks for the burden of
proof to be **flipped**, and for the reopening trigger to be recorded.

### What the platform actually measures — and the number the plan got wrong

[platform-baseline.md §3](../platform-baseline.md) owns the measured `[FPGA]`
baseline, code-bound to `jcore-cpu@master`'s `synth-cpu` workflow. The relevant
reading is the **J4** row — J2 plus MMU plus privileged architecture, which is
what this project builds — and not the J2 row.

§B3 asks "which core actually fits and boots at ~40 MHz". **The question has no
answer, because the premise is wrong**, and the correction is the first thing
this record settles:

- Against that table, ~40 MHz is **J2**'s territory. J2 has no MMU and cannot
  host a hypervisor, a guest or a tenant, so it is not the Phase-1 deliverable
  under any reading of the roadmap.
- **J4 measures well below it**, and the gap is the MMU rather than erosion —
  the workflow records the J4 representative figure moving because the TLB
  stopped being pruned out of the netlist.
- There is no J4 measurement, floor or goal equal to 40 MHz anywhere in
  `jcore-cpu@master`. The only 40 in that workflow is J2's `ECP5_FMIN_MHZ`, its
  CI floor. The `[FPGA]` **goal** in the same workflow is `ECP5_TARGET_MHZ`,
  which is higher than 40, and it is not met.
- The ~40 MHz framing therefore has to go, and it is retired by this record.
  [platform-baseline.md §3](../platform-baseline.md) carries the retirement and
  names the four other sites that inherited it.

**And the J4 gate is thinner than a roadmap quoting it might assume.** It reads
one `nextpnr` seed against a floor, on a distribution whose seed-to-seed `sd`
the workflow measures at ~1.2 MHz. Under the placement weighting CI runs, the
16-seed minimum clears the floor by about one `sd`; under `nextpnr`'s default
weighting the 16-seed minimum fell *below* the floor, which is why the
non-default weighting was chosen. Fixing that is not this task's, but the
consequence for this one is direct: **every structure this record's default path
adds is spent out of about one standard deviation of timing margin**, so
dual-issue and FGMT each have to be re-measured against the J4 floor rather than
assumed free.

### What is and is not measured about area — the part that must not be blurred

Three different things are in circulation and only one of them is a measurement.

1. **The ~10× figure is a third-party measurement of other people's cores, and
   the way §E.1 states it does not survive checking.** [§E.1](../j4-remediation-plan.md)
   reads: *"BOOM (OoO) ≈ 49,865 LUTs vs Rocket (in-order) ≈ 5,073 — ~10× — on an
   84K-LUT ECP5-85F (RISC-V soft-core survey, TU-Braunschweig)."* Checked at
   source on 2026-09-08, **the named survey does not contain that sentence's
   device**. It is Dörflinger, Albers, Kleinbeck, Guan, Michalik, Klink,
   Blochwitz, Nechi & Berekovic, *A Comparative Survey of Open-Source
   Application-Class RISC-V Processor Implementations*, ACM Computing Frontiers
   (CF '21), 2021 — and its own abstract states that its results are for **"the
   Xilinx Virtex UltraScale+ family and GlobalFoundries 22FDX ASIC technology"**.
   Not an ECP5. Not a Lattice part at all, and Virtex UltraScale+ has **6-input**
   LUTs where the ECP5 has 4-input ones, so the unit is not even the same unit.

   That is a defect [0004](0004-platform-tag-convention.md) rule 3 names
   precisely: *"a figure measured on a different FPGA family — Spartan, Artix,
   Kintex, Virtex, all Xilinx, none of them what this project builds on — is not
   made `` `[FPGA]` `` by tagging it."* §E.1 did more than tag it: it wrote the
   ECP5-85F into the sentence.

   **What survives, and it is still worth something.** A published, peer-reviewed
   comparison of an out-of-order and an in-order RISC-V core under forced-common
   parameters exists, it is by third parties, and it puts the out-of-order core
   at a *multiple* of the in-order one on both FPGA and ASIC. That is real
   evidence about the shape of the cost, and it is what this decision leans on.
   What does **not** survive is the specific magnitude, the specific LUT counts,
   and the device — so none of them is repeated as a J-Core-relevant number
   anywhere this task touched, and the corrections are recorded in the plan's own
   §B3 rather than applied silently to §E.1.

   The general rule this instance is an instance of: it is a measurement of
   **BOOM against Rocket, by its authors, on their device** — not of J32-OOO
   against a J-Core in-order baseline, on the ECP5-85F, by us. Quoting it as
   though it were a J-Core ratio is exactly the substitution
   [0005](0005-unmeasured-figures-are-removed.md) exists to prevent, and this
   project has caught the same substitution more than once.
2. **Our own OoO LUT4 number does not exist.** [ooo/j32ooo-spec.md §15](../ooo/j32ooo-spec.md)
   reads, of the LUT4 count for the core plus caches, that it is
   *unknown at this stage — needs measurement*.
   Wave-2 **B1** removed the figure that stood there under
   [0005](0005-unmeasured-figures-are-removed.md), because it was the gate
   subtotal divided by an unvalidated gates-per-LUT4 ratio. There is no OoO RTL
   in `jcore-cpu@master` to synthesize: a case-insensitive `git grep` over
   `origin/master`'s VHDL for `rename`, `issue_queue`, `n_tc`, `thread_id` and
   `fgmt` returns nothing, and the only `barrel` in the tree is the barrel
   *shifter*.
3. **`ooo.gates.core` is a budget.** The registry keeps the OoO core-plus-caches
   gate-equivalent total, and labels it in its own `Constant` cell as *an
   estimate, not a measurement*, retained under
   [0005](0005-unmeasured-figures-are-removed.md) rule 4 because the project
   needs something to be judged against. It is not evidence for or against this
   decision; it is the thing the eventual measurement will be compared to.

**The area argument in §E.1 therefore rests on a proxy, and the proxy got weaker
during this task rather than stronger.** That is recorded rather than smoothed
over, and it is survivable for one reason: **this decision does not rest on the
area leg.** §E.1 has three legs — the instruction window cannot hide SDRAM
latency (the strongest, and the only one that is about the design's own stated
purpose), area on the ECP5, and where the `[ASIC]` energy goes. The area leg is
now "a real third-party result showing a multiple, on the wrong device, at an
unverified magnitude". A decision that *closed* the question would be in trouble.
A decision that **shifts a burden of proof** is not, and shifting the burden is
all D3 does. If the area leg were the load-bearing one, the honest outcome here
would have been to leave the question open — and it is worth saying that plainly,
because the temptation on finding a broken citation is to defend the conclusion
it was supporting.

### What the light-OoO sibling does and does not fix

[ooo/j32lt-spec.md §12.1](../ooo/j32lt-spec.md) is unusually honest about its
own result and it matters here: J32-LT is **not smaller** than J32-OOO. Deleting
the issue queue, the rename machinery, the store-set predictor and two predictor
tables is cancelled by quadrupling the thread contexts, and the per-context
hypervisor and store-queue state of §16.12 pushes it past. [The service plan
§5](../jcore-ulx3s-service-plan.md) already records the conclusion — *do not
treat "light OoO" as a LUT-budget mitigation*. So J32-LT does not answer the
area half of §E.1 either, and its 4-way barrel is on the wrong side of §E.1's
own counter-evidence bullet, which reads Hölzle as arguing against a wide barrel
while leaving the FGMT-over-OoO conclusion standing.

### Where the roadmap currently disagrees with all of this

[jcore-ulx3s-service-plan.md §9](../jcore-ulx3s-service-plan.md) staged Tier 0
at Phase 1B, the Tier 1 MVP at Phase 5, the **dual-issue OoO core at Phase 6**,
and dual-core-plus-FGMT at Phase 6.5 — FGMT arriving *after* OoO and *on top of*
it. On the evidence above that ordering is backwards, and leaving it standing
beside a paused OoO path would have been two statements about the same work.
D5 below re-stages it, and the plan now reads that way; this paragraph describes
the state this record found.

---

## Decision

**D1. The default microarchitecture path is dual-issue in-order with 2-thread
switch-on-miss FGMT, on both platforms.** The argument that carries the most
weight is the one that applies to *both* and is about the OoO design's own
stated purpose: a window this size does not hide SDRAM latency, and two contexts
do. The platform-specific arguments sit on top of that — fit and timing margin
on the ECP5-85F, energy on gf180 — and the ECP5 one is the weaker of the two
after this task's citation check (see §Context).

**D2. New OoO RTL effort pauses.** [ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md)
and [ooo/j32lt-spec.md](../ooo/j32lt-spec.md) are **not** superseded, not
withdrawn and not wrong. They remain the specification of design points the
project is not currently building, and they keep their prior-art sets, their
security models and their validation gates intact. What stops is RTL written
against them.

The two are paused for different reasons and the difference is worth keeping:

- **J32-OOO** is the design §E.1 argues against directly — a ROB, register
  renaming and a wakeup-select issue-queue CAM, which are the three structures
  the SDRAM-latency, ECP5-area and ASIC-energy arguments each land on.
- **J32-LT** is paused as a *product point*, not as a body of ideas. Its issue
  is in-order and it has neither rename nor an issue queue, so two of the three
  arguments do not reach it. What reaches it is the barrel width and the fact
  that it is not an area saving (§12.1, above). Its front end, its PAIR stage
  and its pairing rules are the nearest existing description of D1's path, and
  the spec that D1 needs should be derived from them rather than written fresh.

**D3. The burden of proof is on out-of-order execution.** To resume, OoO must
demonstrate, on a **model driven by real memory-bound traces**, that it beats
dual-issue in-order + FGMT at **equal area and comparable effort**. Three
qualifiers, each of which has been got wrong in this workspace before:

- *Memory-bound traces.* Not CoreMark, not Dhrystone —
  [§E.3](../j4-remediation-plan.md) records that both fit in cache by design and
  that EEMBC built CoreMark-PRO to fix it. Kernel builds, CoreMark-PRO-class
  loads and the network/crypto mix the service actually sells.
- *Equal area, measured.* Both arms through `yosys` + `nextpnr-ecp5` on the
  ULX3S 85F. Not two gate-equivalent budgets compared with each other:
  [0005](0005-unmeasured-figures-are-removed.md) is a whole record about what
  happens when an estimate is asked to settle a question only a measurement can.
- *Comparable effort.* The comparison is between what each path delivers for a
  similar amount of engineering, not between a fully-tuned OoO and a first-cut
  in-order core.

The model already has a specified shape: [ooo/j32lt-spec.md §15](../ooo/j32lt-spec.md)
phase **P0** is a trace-driven model over `sim/sh2instr.c` traces, deliberately
placed first and deliberately cheap, as a go/no-go gate. D3 is the same
instrument pointed at the OoO question, with both arms in it.

**D4. The Phase-1 `[FPGA]` deliverable is J4 as it exists today** — single-issue
in-order, MMU, privileged architecture — at the measured J4 figure in
[platform-baseline.md §3](../platform-baseline.md), not at ~40 MHz. Its goals
are the `[FPGA]` goals of [0004](0004-platform-tag-convention.md): correctness,
area fit, and boot-to-Linux. **Frequency and energy targets are `[ASIC]`-only**
and belong to gf180, where [platform-baseline.md §1](../platform-baseline.md)
records that there is no baseline yet.

Dual-issue and FGMT are **upgrades beyond Phase 1**, not part of it. Stating
that separation is most of what §B3 asked for: the Phase-1 deliverable is a core
that exists and is measured, and everything in D1 is a core that does not exist
yet.

**The "boots" half of §B3's question is not answered either, and it is worth
being exact about what is and is not demonstrated.** What `jcore-cpu@master` CI
establishes for J4 is that it *fits and closes timing* — synthesis and P&R on
the 85F, gated against a floor — and that its MMU behaves, via bare-metal
simulation harnesses that link the **real** `linux@jcore` objects: the TLB-miss
handler, the `head_32.S` MMU-enable path, huge-page installs. That is
considerably stronger than a hand-written stub. It is **not a Linux boot**:
nothing in that repository's workflows boots a kernel on J4, on hardware or in
simulation. So boot-to-Linux is a Phase-1 *goal* with a partial evidence trail,
not an achieved property, and a roadmap should not read it as done.

**D5. The roadmap order flips: FGMT before OoO.** In
[jcore-ulx3s-service-plan.md](../jcore-ulx3s-service-plan.md), the work that was
Phase 6 (dual-issue OoO) and Phase 6.5 (dual-core + FGMT *on the OoO core*)
becomes dual-issue in-order + 2-thread FGMT first, then dual-core SMP —
independent of any OoO core. OoO leaves the numbered sequence entirely and
returns only through D3.

---

## Enforcement

Stated in full, including the half that has none, because a decision whose
enforcement is overstated is worse than one that admits the gap —
[0007](0007-l1d-write-policy-under-msi.md) sets the precedent of recording
"neither, and here is why".

**Checked mechanically:**

- `platform.fmax.target` is a new registry row and a new code binding, added by
  this task: [platform-baseline.md §3](../platform-baseline.md)'s `[FPGA]`
  frequency goal is now tied to `jcore-cpu@master`'s workflow `env:` block, so a
  second, different frequency "target" cannot re-enter a document and sit there
  unchallenged. That is the exact failure the ~40 MHz framing was — a goal with
  no source, restated in five places for weeks.
- `ooo.gates.core` remains registry-owned and value-guarded, with its `Constant`
  cell saying *an estimate, not a measurement*. No document may state a
  different OoO area total, and the one it may state is labelled.

**Not checked, and not checkable from this repository:** the D2 pause itself.
The thing to detect is OoO RTL being written, and that happens in `jcore-cpu`,
which this repository can read but not police — nothing here can distinguish
"no OoO RTL because it is paused" from "no OoO RTL yet", since both look
identical and both are true today. The substitute is placement rather than
automation: both OoO specs carry a notice as their first content, ahead of any
design text, so the pause is read before the design is.

**Also not checked: the ~10× proxy.** There is no registry pattern that would
catch it being restated as a J-Core figure, because it is not a J-Core constant
— there is nothing for the registry to own, and inventing an owner for a number
we did not produce would be the substitution rather than a guard against it.
What is done instead is editorial and is stated so a reader knows the strength
of it: every site carrying the figure names the two cores, the measurer and the
device on the same line as the number.

---

## Rejected alternatives

**A. Keep OoO as the default and let FGMT follow it (the status quo).** Rejected
on §E.1. The specific defeater is that the OoO core's stated purpose in the
service plan's own Phase 6 scope — *"keeping the ALU busy during 30–50 cycle
SDRAM stalls"* — is the one thing a small window cannot do: hiding a 40-cycle
miss at 2 IPC needs on the order of 80 instructions in flight, and the
specified machine is a fraction of that. A design justified by a job it cannot
perform does not get to be the default while a cheaper design that performs it
by construction waits behind it.

**B. Decide it on the ~10× LUT figure alone.** Rejected, and this is the
alternative it would have been easiest to take. The figure is not ours; using it
to *close* the question would import another project's measurement as a J-Core
result. It is used here only to move the burden of proof, which is what evidence
of that kind can carry.

**C. Adopt J32-LT as the default.** Rejected. It is dual-issue and in-order at
issue, which is most of D1, but it is not an area saving (§12.1), its 4-way
barrel is what §E.1's counter-evidence argues against, and its ROB and
out-of-order completion are unbudgeted against the J4 timing margin measured
above. Its front end is the right starting material for D1's spec, which is a
different claim and is made in D2.

**D. Withdraw or supersede the OoO specs.** Rejected. They are not wrong, they
carry work — a transient-execution security model, a validated prior-art set, a
gate budget — that D1's path will need, and
[0002](0002-supersede-convention.md) reserves `SUPERSEDED BY` for text that is
now *wrong*. Pausing is the honest status and there is no marker for it, so the
notice is written as prose rather than dressed up as a
[0002](0002-supersede-convention.md) marker it is not.

**E. Write the decision inline in `j32ooo-spec.md`.** Rejected for the reasons
in the opening section; recorded here as an alternative rather than only as a
justification, because the README's rule genuinely points that way at first
reading and someone will re-derive it.

---

## What this does not decide

- **The default path has no spec, and this record does not write one.** D1 names
  a microarchitecture that exists in no document here. Whoever writes it starts
  from [ooo/j32lt-spec.md](../ooo/j32lt-spec.md)'s front end and pairing rules
  (D2), at 2 contexts with switch-on-miss selection rather than a 4-way barrel,
  and must re-open whether the ROB earns its area at that thread count.
- **Whether dual-issue fits the J4 timing margin.** That is
  unknown at this stage — needs measurement.
  `yosys` + `nextpnr-ecp5` on the ULX3S 85F against the J4
  floor is what answers it, and the margin it is spending is the ~1 `sd`
  measured above.
- **Anything about the `[ASIC]` frequency.** There is no `[ASIC]` baseline —
  [platform-baseline.md §1](../platform-baseline.md) — so no claim here is
  quantitative on gf180. The energy argument of §E.1 is structural (where the
  activity is), not measured.

---

## What would reopen this

**Any one of these, and each is a positive result rather than an absence:**

1. **The D3 model comes back for OoO.** A trace-driven model over memory-bound
   traces showing the OoO arm ahead of dual-issue in-order + FGMT at equal
   *measured* area and comparable effort. This is the trigger the decision is
   built around and it is the reason D2 says "pauses" rather than "is
   cancelled".
2. **The workload turns out not to be memory-bound.** The whole of §E.1 rests on
   SDRAM stalls dominating. If measurement on the real tenant mix — Track D0's
   job — shows miss traffic low enough that latency-hiding is not where the
   cycles go, then the argument does not apply and the question is open on
   different grounds. Note this cuts *both* ways: it would also remove the
   in-order+FGMT path's main advantage.
3. **A J-Core area measurement contradicts the proxy.** [ooo/j32ooo-spec.md
   §15.1](../ooo/j32ooo-spec.md) already carries the action item — synthesize a
   representative OoO subset (rename + ROB + 1 ALU + L1$) on the ECP5 and read
   the real LUT4 count. If it lands near the in-order core rather than at a
   multiple of it, the BOOM-versus-Rocket proxy stops carrying the area
   argument and one of this decision's three legs is gone.
4. **The `[FPGA]` platform moves off the ECP5-85F** to a device where area is
   not the binding constraint. That reopens the `[FPGA]` half only. The
   `[ASIC]` half rests on where the energy is spent, not on how many LUTs the
   ECP5 has, and survives a platform change.

**What does not reopen it**, stated because these are the arguments that will be
offered:

- A better CoreMark or Dhrystone score. [§E.3](../j4-remediation-plan.md)
  disqualifies both for this question, in advance, by name.
- A revised gate-count estimate for either design. An estimate cannot settle a
  question whose whole difficulty is that nobody has measured it —
  [0005](0005-unmeasured-figures-are-removed.md), and rule 6 in particular.
- The observation that J32-OOO's spec is more complete than the path D1 names.
  It is, and that is a statement about which document was written first.

---

## Prior art

**Why this section exists on a decision record.** [glossary §2](../glossary.md)
requires published pre-2006 prior art for every non-trivial mechanism, in a
**Prior art** section. FGMT is not new to this workspace — it is in the
glossary's threading section and in three specs — but this record *promotes* it
from one option among several to the default path, so it is cited here on the
same terms rather than by reference to somebody else's citation table.

The mechanism being adopted is **fine-grained multithreading with a small thread
count and switch on a long-latency event**. Its pre-2006 art is deep and is
independent of this project:

**Every citation below was checked against a primary source on 2026-09-08**, and
three of them changed as a result; the changes are recorded under §Citations
that did not survive checking.

| Element of D1 | Prior art |
|---|---|
| Hardware thread contexts interleaved into one pipeline (the barrel) | CDC 6600 peripheral processors — J. E. Thornton, *Parallel Operation in the Control Data 6600*, AFIPS Proc. FJCC 1964, part 2, vol. 26, pp. 33–40. The barrel is described in the 1964 paper itself: ten processors' dynamic state moves around a "barrel", each getting one 100 ns minor cycle of every ten, so "the single arithmetic and the single distribution and assembly network are made to appear as ten" |
| Issuing each cycle from a different thread specifically to cover memory latency | Denelcor HEP — B. J. Smith, *A Pipelined, Shared Resource MIMD Computer*, Proc. 1978 International Conference on Parallel Processing, pp. 6–8. The mechanism is a **process queue**, not a fixed rotation: a new instruction begins every 100 ns while an instruction takes 800 ns to complete, so at least eight independent processes are needed for full issue rate |
| Thread interleaving as the *sole* latency-tolerance mechanism, no data cache | Tera MTA — Alverson, Callahan, Cummings, Koblenz, Porterfield & Smith, *The Tera Computer System*, Proc. 4th International Conference on Supercomputing (ICS '90), 1990, pp. 1–6. Up to 128 program counters per processor, sized against an average instruction latency of "perhaps 70 ticks" |
| **Switch on a long-latency event rather than every cycle — the mechanism D1 actually adopts** | MIT Alewife / Sparcle — Agarwal, Kubiatowicz, Kranz, Lim, Yeung, D'Souza & Parkin, *Sparcle: An Evolutionary Processor Design for Large-Scale Multiprocessors*, IEEE Micro 13(3), June 1993, pp. 48–61. The paper draws the distinction this record needs, against HEP by name: cycle-by-cycle interleaving is "fine multithreading", whereas "Sparcle employs **block multithreading or coarse multithreading**. That is, context switches occur only when a thread executes a memory request that must be serviced by a remote node … Thus, a given thread continues to execute as long as its memory requests hit in the cache" |
| Small thread count on a single-issue in-order commercial core, chosen because memory stalls dominate | Sun UltraSPARC T1 "Niagara" — Kongetira, Aingaran & Olukotun, *Niagara: A 32-Way Multithreaded Sparc Processor*, IEEE Micro 25(2), March–April 2005, pp. 21–29. Eight thread groups of four threads on a single-issue six-stage pipeline, justified because "the combination of low available ILP and high cache-miss rates causes memory access time to limit performance". **The paper describes no branch predictor**; branches are listed among the long-latency events that deschedule a thread |
| Two hardware threads on an in-order embedded RISC core, as a shipped architecture | MIPS MT ASE — MIPS Technologies, *MIPS32 Architecture for Programmers Volume IV-f: The MIPS MT Application-Specific Extension to the MIPS32 Architecture*, document MD00378, revision 1.00, **28 September 2005** |
| In-order issue with out-of-order completion via a scoreboard (the mechanism D1 must re-examine, per §What this does not decide) | CDC 6600 scoreboard — Thornton 1964, above |
| Non-blocking loads on an in-order pipeline, which is the structure switch-on-miss needs | Kroft, *Lockup-Free Instruction Fetch/Prefetch Cache Organization*, ISCA 1981; Farkas & Jouppi, *Complexity/Performance Tradeoffs with Non-Blocking Loads*, ISCA 1994 |

**Matched on mechanism, per [glossary §2.1](../glossary.md).** Every row above
is a machine that interleaved hardware contexts into one pipeline to cover
memory latency, which is the mechanism *and* the motivation here — so rule 1
(mechanism over motivation) is not even being leaned on. Rule 2 is the one to
check: is there a purpose-specific *combination* claimed separately? The
combination D1 adds to the pre-2006 art is "two contexts, switch on cache miss,
on a dual-issue in-order core". Two-context switch-on-miss is Alewife's
mechanism at Alewife's thread count; dual issue with in-order completion is
older than any of it. **The combination this project should keep watching is not
this one** — it is the *security* property built on top, where
[ooo/j32lt-spec.md §16.13](../ooo/j32lt-spec.md) and
[ooo/j32ooo-spec.md §20.13](../ooo/j32ooo-spec.md) already do the rule-2 check
for the mitigations, and those sections remain live under D2.

### Citations that did not survive checking

Three of the citations this record started from were wrong, and they are listed
because a corrected citation looks identical to one that was right all along.

1. **MIPS MT, cited as "Kissell, MIPS Tech 2005".** That form appears in
   [ooo/j32ooo-spec.md §1.3](../ooo/j32ooo-spec.md),
   [ooo/j32lt-spec.md §1.4](../ooo/j32lt-spec.md) and
   [fgmt/dual-fgmt-proposal.md §2](../fgmt/dual-fgmt-proposal.md), and as a
   *paper* it does not exist: Kissell's *MIPS MT: A Multithreaded RISC
   Architecture for Embedded Real-Time Processing* is **HiPEAC 2008**, LNCS 4917,
   pp. 9–21 — after the cutoff, and therefore not usable under
   [glossary §2](../glossary.md) at all. The pre-2006 artifact is real but is a
   different document: MIPS Technologies' **MD00378 rev 1.00, 28 September
   2005**, the MIPS MT ASE specification, which is what the table above now
   cites. Worse, the cited *core* is on the wrong side of the line too — the
   34K was announced in February **2006**. A reader checking "Kissell 2005"
   would have found the 2008 paper and concluded the policy had been broken,
   when the fix was to name the 2005 specification.
2. **The 34K throughput/area result, cited as "EE Journal, 2006".** The claim is
   real and the source is Kissell, *Demystifying multithreading and multi-core*,
   **EDN, 26 September 2007**: *"an increase in area of 14% can buy an increase
   of throughput of 60% relative to a comparable single-threaded core (as
   measured using the EEMBC PKFLOW and OSPF benchmarks, run sequentially on a
   MIPS32 24KE core versus concurrently on a **dual-threaded** MIPS32 34K
   core)."* It is a vendor-authored trade-press claim on two networking kernels,
   not a peer-reviewed general result, and it should be quoted with that
   qualifier. Note what the qualifier does *not* do: the configuration measured
   is **two threads on an in-order embedded core**, which is D1's configuration
   exactly, so of the evidence in §E.1 this is the piece that transfers most
   directly and the piece that was cited least precisely.
3. **The BOOM-versus-Rocket LUT ratio.** Covered above under §Context. The
   survey is real and is not what §E.1 says it measured.

**One site carrying the same broken shape is deliberately not corrected here.**
[aic/aic2-spec.md](../aic/aic2-spec.md) cites MIPS MT twice as *"Kissell, MIPS
Tech 2005 … MD00452"*, mixing the 2008 paper's title with a document number this
task did not verify — it is a different number from the MD00378 established
above, and it is cited there for per-thread *interrupt steering* rather than for
FGMT. Correcting a citation to a document nobody has opened would substitute one
unchecked reference for another, which is the failure this section is about.
Recorded so the site is visible; it belongs to whoever next touches AIC2's
prior-art table.

**What did survive**, checked the same way and unchanged: Thornton 1964 (and the
barrel is in the 1964 paper, not only in the 1970 book), Smith 1978, Alverson et
al. 1990, Agarwal et al. 1993, Kongetira et al. 2005, and Mutlu et al., HPCA
2003, pp. 129–140 — whose 128-entry window result is the strongest leg of this
decision and whose stated finding is that a machine with a 128-entry window
"spends 71% of its cycles in full instruction window stalls", most of them
attributable to main-memory latency. One precision point on that: the 128
entries are **micro-operations**, not instructions, which makes the window
smaller in the units §E.1 reasons in, not larger.

**Not cited as prior art, and the distinction is deliberate.** The MIPS 34K
throughput/area result and the ARM A53-versus-A9 comparison in
[§E.1](../j4-remediation-plan.md) are *evidence* about how the mechanism
performs. They are not the mechanism's prior art and are not load-bearing for
patent freedom; the rows above are.

---

## Consequences recorded elsewhere

| Document | What changed |
|---|---|
| [platform-baseline.md §3](../platform-baseline.md) | Retires ~40 MHz as a J4 figure; records the J4 gate's margin; binds `ECP5_TARGET_MHZ` |
| [fact-ownership.md](../fact-ownership.md) | New `platform.fmax.target` registry row and code binding |
| [ooo/j32ooo-spec.md](../ooo/j32ooo-spec.md) | Pause notice; the ~10× proxy stated with its provenance beside the missing J-Core number |
| [ooo/j32lt-spec.md](../ooo/j32lt-spec.md) | Pause notice, with the narrower reason of D2 |
| [jcore-ulx3s-service-plan.md](../jcore-ulx3s-service-plan.md) | Tier 1.5, §5, Phases 6 and 6.5, §11 and the spec map re-staged per D5 |
| [glossary.md §3](../glossary.md) | J32-OOO and J32-LT status; the default path named in the threading section |
| [j4-remediation-plan.md §B3](../j4-remediation-plan.md) | Completion note, with four corrections to §B3's own text |
| [j4-remediation-plan.md §E.1](../j4-remediation-plan.md) | Correction note on the two citations that did not hold; the bullet itself left as quoted review text |
| [j4-remediation-plan.md](../j4-remediation-plan.md) principle 1 | The ~40 MHz clause marked retired; the goals list it carries is untouched |
| [0004](0004-platform-tag-convention.md) rule 3, [0005](0005-unmeasured-figures-are-removed.md) rule 4 | Both illustrate their rule with the retired ~40 MHz; the illustration is corrected, neither rule changes |
| [simd/hardware-impl.md](../simd/hardware-impl.md), [simd/software-impl.md](../simd/software-impl.md) | The two `[FPGA]` goal lines that inherited ~40 MHz |
| [security/threat-model.md §9](../security/threat-model.md) | A platform-tagging complaint withdrawn: with ~40 MHz retired, the row's own 30 MHz is J4's CI floor |
| [fgmt/dual-fgmt-proposal.md §2](../fgmt/dual-fgmt-proposal.md) | The MIPS MT and barrel prior-art citations corrected to primary sources |
