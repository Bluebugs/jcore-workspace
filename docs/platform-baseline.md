# J-Core platform baseline

**What this document owns.** Two facts that belong to the *platform* rather
than to any one subsystem, and that were previously restated in several
documents with no owner between them: the **byte order** (§2) and the
**measured baseline clock frequency** (§3) of the cores this project actually
builds.

It exists because [decisions/0001](decisions/0001-one-authority-per-fact.md)
requires every normative constant to have exactly one owning spec, and neither
of these had one. Endianness was stated by the glossary's product table, the
FPU spec and two FGMT plans; baseline `Fmax` was stated by the service plan and
the component inventory. In both cases the documents disagreed, and none of
them was the place a person would go to change the answer.

Registered in [fact-ownership.md](fact-ownership.md). Restating anything here
elsewhere requires a link back, per
[decisions/0001](decisions/0001-one-authority-per-fact.md).

---

## 1. The two targets

Both are named by [j4-remediation-plan.md](j4-remediation-plan.md), guiding
principle 1, and the platform-tag convention is
[decisions/0004](decisions/0004-platform-tag-convention.md).

| Tag | Target | Role |
|---|---|---|
| `[FPGA]` | ULX3S board, Lattice **ECP5 LFE5U-85F**, CABGA381 package | Phase-1 deliverable. Goals: correctness, area fit, boot-to-Linux. Energy is out of scope. |
| `[ASIC]` | **gf180** | Methodology vehicle — a proof the RTL reaches an ASIC flow. Not the product. Frequency and energy are first-class here. |

Everything in §3 is `[FPGA]`. There is no `[ASIC]` frequency baseline yet:
that is unknown at this stage — needs measurement, and a gate-level run under
the gf180 flow per Track D0 is what would produce it.

---

## 2. Byte order

**J-Core is big-endian, at every product point.** J2, J2-MT2x2, J3, J32,
J32-OOO, J32-LT, J32-FM and J64. There is no per-product-point byte order,
and no migration to little-endian is planned.

The decision, the evidence it rests on, and the little-endian alternative it
rejects are [decisions/0006](decisions/0006-endianness-is-big-endian.md).
In one line: the kernel is configured big-endian, the toolchain target is
`sh2eb-linux-muslfdpic`, the SH-2A encodings the density extension targets have
no little-endian form, and the instruction-fetch halfword selection in the RTL
is big-endian with no mode bit to change it.

The value is bound to `linux@jcore`'s `arch/sh/configs/jcore_defconfig` by
`platform.endianness` in [fact-ownership.md](fact-ownership.md) §Code bindings,
so this section and the kernel configuration cannot drift apart silently.

**What this says, and what it does not.** It is a statement about the
**product**: what the kernel is configured for, what the toolchain targets, and
what instruction fetch does. It is *not* a statement that the hardware can only
ever be big-endian.

Project direction is that the **data path** gains a little-endian mode, owned by
the hypervisor and selected per guest —
[sh4-guest-model.md §3.1](sh4-guest-model.md), Decision B2-1. Instruction fetch
stays big-endian, so a big-endian-compiled guest may run with little-endian
data, while a stock little-endian binary still cannot run natively. None of this
exists in `jcore-cpu` yet. The value bound below is the kernel configuration and
it is unaffected: J32 and J64 ship big-endian, and the mode is a per-guest
software configuration rather than a second product point. Nor does it say anything about SIMD *lane* order, which is
little-endian within a vector register regardless of memory byte order and is
owned by [simd/spec.md §2.2](simd/spec.md).

---

## 3. Baseline clock frequency `[FPGA]`

**The baseline is measured, and it is not one number — it is one number per
core variant.** All figures below are post-place-and-route
`nextpnr-ecp5 --85k --package CABGA381` results on the `cpu_timing_top`
harness, produced by `jcore-cpu`'s `synth-cpu` workflow on every push to
`master`. They are `[FPGA]` by construction; there is no `[ASIC]` counterpart
(§1).

| Core variant | Representative `Fmax` `[FPGA]` | CI regression floor |
|---|---|---|
| J1 | ~38–40 MHz | 33 MHz |
| **J2** — the shipping baseline | **~42–43 MHz** | **40 MHz** (`ECP5_FMIN_MHZ`) |
| **J4** — J2 + MMU + priv-arch, i.e. what this project is building | **~33 MHz** | 30 MHz |
| J2 + caches, J4 + caches | lower, CDC-limited | 18 MHz |

**Read the J4 row, not the J2 row, for anything this project is designing.**
The MMU costs about a quarter of the clock: `jcore-cpu`'s workflow records the
J4 representative `Fmax` moving *"37.66 -> 33.38 MHz because the MMU is now
actually in the netlist"* when the J4 leg stopped building with the J2 decoder
and `yosys` stopped pruning the TLB. That is a scope change, not erosion — but
it is the number a J4 throughput estimate has to use.

**Why the harness and not the bare core.** `jcore-cpu`'s `synth/README.md`
explains it: the bare `cpu` exposes ~348 ports as pads, which on the sparse 85F
scatters the core and inflates routing, so its reported `Fmax` is a measurement
artifact — demonstrably so, since it is *flat* at ~42 MHz across 6%–23% device
utilisation. `cpu_timing_top` registers the boundary down to 4 IO and gives the
true register→core→register path. The bare-core number is reported by CI and
deliberately not gated.

**The goal, kept and labelled as one** per
[decisions/0005](decisions/0005-unmeasured-figures-are-removed.md) rule 4:
`ECP5_TARGET_MHZ` is **50 MHz**, and it is not met. `synth/README.md` says what
it would take — the path is *"~6 ns logic + ~18 ns intrinsic routing through
the regfile-read/MAC-accumulate datapath"*, so reaching 50 MHz needs
microarchitectural work (pipelining), not tuning. The `[ASIC]` ambition of
~400 MHz+ is a different target on different silicon and is not derived from
any of this.

**80 MHz was never measured and is gone.** The figure appeared in
[jcore-ulx3s-service-plan.md](jcore-ulx3s-service-plan.md) as an in-order J32
baseline and as the clock under a throughput table. No J32 RTL exists to
synthesize, so nothing produced it; per
[decisions/0005](decisions/0005-unmeasured-figures-are-removed.md) it is
removed rather than annotated, and the estimates derived from it went with it.

`platform.fmax.floor` and `platform.fmax.j4.floor` in
[fact-ownership.md](fact-ownership.md) §Code bindings tie **all four** floors
in this table to `jcore-cpu@master`'s `.github/workflows/synth-cpu.yml` — two
owned facts carrying four bindings, because J1 and the cache leg ride on
`platform.fmax.floor` rather than owning rows of their own — so a
re-baseline in CI that is not reflected here is a red run rather than a silent
divergence. The *representative* figures are ranges and are not bound; the
floors are the exact integers, and they move whenever the representative
figures do — that is what re-baselining means, and it is why binding the floor
is not a weaker check than binding a range would have been.

---

## 4. What this document is not

It is not a status page and not a plan. It carries facts with an owner and a
citation each. Roadmap sequencing lives in
[jcore-ulx3s-service-plan.md](jcore-ulx3s-service-plan.md); the remediation
worklist lives in [j4-remediation-plan.md](j4-remediation-plan.md).
