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

**What this does *not* say.** It says nothing about the byte order of a
**guest**. Per [j4-remediation-plan.md §B2](j4-remediation-plan.md) an
SH-4/Dreamcast image runs as a KVM guest under the hypervisor extension, and
the byte order of that image is a property of the image and of the device model
that serves it. Nor does it say anything about SIMD *lane* order, which is
little-endian within a vector register regardless of memory byte order and is
owned by [simd/spec.md §2.2](simd/spec.md).

---

## 3. Baseline clock frequency `[FPGA]`

*(added by the same task; see §3 of this file's history in the commit that
introduces it)*

---

## 4. What this document is not

It is not a status page and not a plan. It carries facts with an owner and a
citation each. Roadmap sequencing lives in
[jcore-ulx3s-service-plan.md](jcore-ulx3s-service-plan.md); the remediation
worklist lives in [j4-remediation-plan.md](j4-remediation-plan.md).
