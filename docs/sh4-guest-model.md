# SH-4 / Dreamcast compatibility model — the guest is the observer

**Status:** Canonical for the compatibility *model*. Wave-2 task **B2**, from
[j4-remediation-plan.md §B2](j4-remediation-plan.md).

**Scope:** what "SH-4 compatible" obliges J-Core to do. Three things, and no
more: what runs on bare metal, what the hypervisor must present to an SH-4
guest, and which of the two surfaces each SH-4 finding belongs to.

**Authority:** this document owns the **model** — the classification of every
SH-4 surface as *emulated*, *native*, or *unsupported*, and the fidelity bar
each class must meet. It owns **no register address, vector, or encoding**.
Those have owners in [fact-ownership.md](fact-ownership.md) and this document
links them. Where it names a stock SH-4 value, that value is a *requirement on
the emulated surface* and is registered and code-bound as such.

**Audience:** VMM / KVM authors, RTL implementers, and anyone about to write
"this breaks SH-4 compatibility" in a review.

**Prerequisites:** [hypervisor/hardware-spec.md](hypervisor/hardware-spec.md)
(the trap architecture), [soc/p4-mmio-map.md](soc/p4-mmio-map.md) (host P4
allocation), [platform-baseline.md §2](platform-baseline.md) (byte order).

---

## 1. The one rule, and who the observer is

The outlawed outcome is unchanged and is the only one:

> **Silently different from what the observer expects.**

B2 changes the *observer*. It is not a bare-metal SH-4 chip, because no
J-Core core is one and none is planned to be. It is:

1. the **guest**, for everything the hypervisor presents; and
2. the **J-Core toolchain and kernel**, for everything that runs bare metal.

A divergence from an SH-4 hardware manual that neither observer can see is not
a compatibility break. A divergence either observer *can* see, and that fails
loudly, is a defect but not a *silent* one — it is fixable in software and
reviewable. Only the third case is forbidden: a divergence the observer can see
and cannot detect.

Every surface below is therefore classified in exactly one of three ways.

| Class | Meaning | The bar |
|---|---|---|
| **Emulated** | The guest's access traps and the VMM answers it. The hardware need not resemble SH-4 at all. | Bit-exact at the trap boundary: the value the guest reads back, and the side effect it observes, are what the SH-4 manual says. |
| **Native (must decode as SH-4)** | Guest instructions execute on the hardware with no trap. | The hardware must implement the SH-4 semantics, **or** raise an exception the hypervisor sees. Decoding the encoding as *some other J-Core instruction* is the forbidden third case. |
| **Not supported** | The guest cannot use it, and finds that out loudly. | A trap the VMM turns into a guest-visible failure. Never a silent zero, never a nop. |

---

## 2. (a) Bare-metal J4 is SH-2 plus J-Core extensions

**Bare-metal J4 is not an SH-4 at the instruction-set level, and this is not a
gap to be closed.** It is SH-2 (the J2 base ISA) plus the J-Core extensions
plus the SH-4 *privileged* architecture. That is the whole of it.

The evidence is the build variant table itself. `jcore-cpu@origin/master`'s
`variants.toml` defines J4 as the variant binding `PRIV_ARCH` true
([glossary §7](glossary.md)) with the decoder overlay `sh4`, and that overlay
is four files — `bank`, `exceptions`, `mmu`, `mov` — under
`decode/gen-go/spec/sh4/`. Register banking, the register-model exception
entry/return, the MMU control-register moves, and a handful of transfers. There
is no FP file, because there is no FP:

- **No FPU exists in `jcore-cpu@origin/master`** — no RTL source, no decoder
  entry for any `F`-mnemonic, and no FPU generic in `variants.toml`. What
  exists is a generic 5-bit coprocessor port (`cop_o_t`/`cop_i_t` in
  `cpu2j0_pkg.vhd`), which carries no floating-point semantics and has nothing
  attached to it in any testbench.
- **The whole `1111` opcode plane traps on J4** as a general illegal
  instruction, and there is a test that says so:
  `sim/tests/j4_illegal_trap.S` calls it "the FPU space, which J4
  (integer-only) now traps as illegal", and the guard word is 0xF000.
- **Two encodings escape that trap**, and they are the subject of §5.

So [fpu/spec.md](fpu/spec.md) is a specification for hardware that does not
exist yet, at every one of its three tiers. That is a legitimate state for a
spec to be in; it is not a legitimate thing to forget when classifying a
finding, because "the FPU must decode this as SH-4 does" is a requirement on an
FPU nobody has built, not a description of a break in shipping hardware.

**What this means for reviewers.** A finding of the form "J-Core's *X* differs
from SH-4's *X*" is, on the bare-metal surface, **not a defect by itself**. It
is a defect only if a J-Core toolchain, kernel or debugger assumes SH-4 and is
silently wrong. §7 marks which findings survive that test.

---

## 3. (b) SH-4 / Dreamcast is a KVM guest

### 3.1 Three things the hardware decides before the VMM gets a vote

**Guest byte order is the host's byte order, and there is no knob.** A KVM
guest's instructions execute on the host's fetch, load and store path. J-Core
has no byte-order mode bit anywhere: not in `SR`, not as a generic, not in the
RTL's instruction-halfword selection — see
[platform-baseline.md §2](platform-baseline.md) and
[decisions/0006](decisions/0006-endianness-is-big-endian.md). Therefore:

> **Decision B2-1. SH-4 guests on J4 are big-endian SH-4 guests.
> Little-endian SH-4 images are not supported on the KVM path.**

This is the consequential one, and it narrows a claim this project has been
making loosely. **Dreamcast retail software is little-endian**
([decisions/0006](decisions/0006-endianness-is-big-endian.md) records that as
the engineering argument once offered for migrating J-Core to little-endian).
It therefore does **not** run on the KVM path at all. It runs, if it runs, under
full software emulation — a TCG-style interpreter or JIT in which byte order is
the emulator's business and J4 is merely a fast host CPU with an MMU. Nothing
in this document, in [hypervisor/hardware-spec.md](hypervisor/hardware-spec.md)
or in [sq/spec.md](sq/spec.md) applies to that path: a software emulator does
not use the guest-trap architecture, does not use the store-queue carve-out, and
does not care what the host decodes.

The KVM path's real target is a **big-endian SH-4 guest** — an SH-4 Linux, an
SH-4 RTOS, or a J-Core-aware guest — which is also the multi-tenant workload the
hypervisor exists for. The Dreamcast case motivates the *device model* work and
the store queue; it does not, by itself, justify a byte-order change. Reopening
that would require both conditions
[decisions/0006](decisions/0006-endianness-is-big-endian.md) names, and §4 below
answers one of them "no".

**Guest P4 traps wholesale, with one carve-out.** Per
[hypervisor/hardware-spec.md §4.4.3](hypervisor/hardware-spec.md), every guest
access to `0xE0000000`–`0xFFFFFFFF` raises the emulated-MMIO trap *except*
`0xE0000000`–`0xE3FFFFFF`, the store-queue-decoded range. This single rule is
what makes almost the whole SH-4 register surface *emulated* rather than
*native*, and it is why the host's P4 offsets and the guest's SH-4 offsets are
free to differ (§3.2).

**Guest FP traps.** §4.

### 3.2 The emulated surface

Everything in this table is reached through the guest P4 trap. The VMM decides
what the guest sees; the hardware behind it need not resemble SH-4.

| Guest-visible SH-4 surface | Emulated address / mechanism | What the VMM must do |
|---|---|---|
| `PTEH`, `PTEL`, `TTB`, `TEA`, `MMUCR` | stock SH-4 offsets in the guest's P4 | Maintain shadow state per [hypervisor/linux-spec.md §3](hypervisor/linux-spec.md); the guest's `MMUCR` is a shadow value, never the host register. |
| `PTEA` | stock SH-4 `0xFF000034` | Accept and ignore, or model, per the guest's CPU subtype. J-Core allocates nothing there — [soc/p4-mmio-map.md §3.2](soc/p4-mmio-map.md) holds it for the proposed `PTEU`. |
| **`CCR`** (cache control) | stock SH-4 offset **`0xFF00001C`** | **Emulated only. There is no host register.** Reads must return a value describing J-Core's actual caches; writes are advisory and must not be silently dropped where the guest can tell (cache-invalidate requests in particular). |
| **`QACR0`** (store-queue area 0) | stock SH-4 offset **`0xFF000038`** | Trap, validate, and program the *host* `QACR0`, which is at a different offset ([soc/p4-mmio-map.md §3.2](soc/p4-mmio-map.md)). Per [sq/spec.md §6.1](sq/spec.md) the value is loaded verbatim — the burst target is translated, so no arithmetic is done on it. |
| **`QACR1`** (store-queue area 1) | stock SH-4 offset **`0xFF00003C`** | As `QACR0`. |
| `TRA`, `EXPEVT`, `INTEVT` | stock SH-4 offsets, which J-Core also uses | Virtualized. The offsets agreeing is a convenience for the VMM, not a licence to let the guest read the host register. |
| `LDTLB` | trapped instruction, not a register | Per [hypervisor/hardware-spec.md §3.3](hypervisor/hardware-spec.md), guest `LDTLB` traps to the hypervisor, which installs a shadow entry. This is the mechanism, and it is already specified. |
| Store-queue **buffers** | the SQ carve-out, `0xE0000000`–`0xE3FFFFFF` | *Native* — see §3.3. Only the `QACR`s are emulated. |
| Exception cause codes | `EXPEVT`/`INTEVT` on guest entry | **Translated, per §3.4.** J-Core's cause assignment is not SH-4's. |
| Interrupt controller | guest MMIO | Fully emulated. J-Core's AIC2 is not an SH-4 INTC and is not the guest's controller — §3.4. |
| Platform devices (Dreamcast Holly, GD-ROM, AICA, …) | guest MMIO | Fully emulated, if at all. None of them exist in any J-Core RTL. |

**Where the stock offsets come from.** They are not recalled; they are read out of Linux's
SH-4 headers on `linux@jcore`, which is the artifact this document's code bindings compare
against. `arch/sh/include/cpu-sh4/cpu/cache.h` puts SH_CCR at 0xff00001c.
`arch/sh/include/cpu-sh4/cpu/sq.h` puts SQ_QACR0 at offset 0x38 and SQ_QACR1 at offset 0x3c of
`P4SEG_REG_BASE`, which `arch/sh/include/cpu-sh4/cpu/addrspace.h` defines as `0xff000000`. If
upstream ever moved one, the binding in [fact-ownership.md](fact-ownership.md) turns red rather
than this table turning quietly wrong.

**Why the offsets are allowed to differ.** J-Core's host P4 map places `QACR0`
and `QACR1` at offsets that are *not* the stock SH-4 ones, and places its own
`ASIDR` and `TSBPTR` on offsets stock SH-4 uses for `QACR0` and `CCR`
respectively. On bare metal that is a divergence with consequences
([soc/p4-mmio-map.md §5](soc/p4-mmio-map.md) rule 8 now says so). For a guest it
has **no consequence at all**, because the guest's P4 access never reaches the
host decoder — it traps first. The VMM presents the stock map; the hardware
keeps the J-Core map; neither has to move.

### 3.3 The native surface — what runs without a trap

This is the short list, and it is short on purpose. Everything here is a place
where a guest instruction reaches the hardware, so everything here carries the
decode-fidelity obligation of §5.

| Native surface | Status | Obligation |
|---|---|---|
| The SH-2 base integer ISA | implemented | It *is* the guest's ISA for these encodings. Nothing to do. |
| SH-4 privileged instructions J4 implements (`LDC`/`STC` forms, `RTE`, banking) | implemented | Guest execution is gated by the privilege architecture; the hyperprivileged trap rules of [hypervisor/hardware-spec.md §3](hypervisor/hardware-spec.md) contain them. |
| **Store-queue data stores**, `0xE0000000`–`0xE3FFFFFF` | **specified, not implemented** | [sq/spec.md](sq/spec.md) is a paper spec: `jcore-cpu@origin/master` has no store queue, no SQ region decode, and no SH-4 `PREF`. Until it exists, a guest store into the carve-out reaches a range nothing decodes. **The carve-out must not be enabled before the queues are.** |
| **The `1111` opcode plane** | traps as illegal, except two encodings | §5. |
| SH-4 FP | **trapped** | §4. |
| Any J-Core extension encoding (SIMD, density, PC-relative) | not the guest's | A guest must never execute one. §5 states the rule that keeps that true. |

### 3.4 Two delegations that are only safe for a J-Core-aware guest

Both mechanisms below let a guest be entered *without* the hypervisor
translating anything. Both are correct for a paravirtualized, J-Core-aware
guest, and both are silently wrong for a stock SH-4 guest.

**Exception cause codes.** J-Core's `EXPEVT` assignment for the data-side TLB
causes is its own, not SH-4's — [mmu/hardware-spec.md §5](mmu/hardware-spec.md)
defines it, and it is the table `jcore-cpu`'s
`decode/gen-go/spec/sh4/exceptions.toml` implements. Stock SH-4 has a cause that
table has no entry for at all (the *initial page write* exception; Linux still
carries its handler, at `arch/sh/kernel/cpu/sh3/entry.S`), and J-Core has no
FPU-disable cause, because it has no FPU
([fpu/spec.md §6.3](fpu/spec.md) names the SH-4 codes and the RTL implements
neither).

**A translation table cannot be written today**, because the workspace states
J-Core's own assignment twice and the two disagree — see the *J-Core `EXPEVT`
cause table* row in [fact-ownership.md](fact-ownership.md)'s `Unresolved` list.
That is a hole this task found and did not close: picking a winner means
changing HEDR bit meanings, which belongs to the hypervisor and priv-arch specs,
not to a compatibility model. **Decision B2-2 below stands regardless of which
table wins** — it says *translate, do not delegate*, and that is true under
either assignment.

> **Decision B2-2. For a stock SH-4 guest, exception causes are translated by
> the hypervisor, not delegated.** `HEDR`
> ([hypervisor/hardware-spec.md §2.3](hypervisor/hardware-spec.md)) may delegate
> a cause directly to a guest's `VBR` only when the guest is known to be
> J-Core-aware. Delegating to a stock guest hands it a cause code that means
> something else on the architecture it was built for — the forbidden third
> case, arriving through the fast path.

**Interrupt vectoring.** [aic/aic2-spec.md §3.4](aic/aic2-spec.md) delivers at
`VBR + 0x600 + vector_number * 0x20`. SH-4 has one interrupt entry point at
`VBR + 0x600` and discriminates with `INTEVT` — Linux's SH exception table
still labels it exactly that way (`arch/sh/kernel/cpu/sh3/entry.S`, "0x600:
Interrupt / NMI vector"). The per-vector stride is a J-Core convention.

> **Decision B2-3. AIC2 is the host's interrupt controller and is never the
> guest's.** A guest's interrupt controller is emulated. AIC2's direct
> guest-injection path ([aic/aic2-spec.md §5](aic/aic2-spec.md)) is a
> paravirtual facility for a J-Core-aware guest only; a stock SH-4 guest must be
> entered by the hypervisor at the SH-4 entry point with an SH-4 `INTEVT`.

### 3.5 Not supported

Stated so the list is enumerable rather than inferred from silence. Each must
fail loudly.

- **Little-endian SH-4 guests**, including all Dreamcast retail software, on the
  KVM path (Decision B2-1).
- **Guest use of the SH-4 FPU at native speed** (Decision B2-4, §4).
- **The SH-4 user-mode store-queue path.** [sq/spec.md §5](sq/spec.md) keeps
  SH-4's `SQMD` reserved and unimplemented, so there is no user-mode SQ access
  on J-Core at all; a guest that programs `SQMD` and then issues a user-mode SQ
  store must take a trap, not a silent privileged store.
- **Direct guest access to the on-chip caches** through SH-4's cache/TLB array
  windows. J-Core allocates that region to nothing
  ([soc/p4-mmio-map.md §7](soc/p4-mmio-map.md)) and the guest P4 trap covers it.
- **Any J-Core extension**: SIMD, the density instructions, the PC-relative
  extension, `HCALL`/`HRTE`, `LDTLB.RN`. A guest that executes one is either
  J-Core-aware or wrong; §5 is the rule that makes "wrong" loud.

---

## 4. The floating-point decision

> **Decision B2-4. Guest SH-4 floating point is trapped and emulated. It does
> not execute natively on any J-Core core specified today, and enabling native
> guest FP is a separate decision with its own evidence bar.**

Four reasons, in descending order of how hard they are to argue with.

1. **There is no FPU to run it on.** `jcore-cpu@origin/master` has no FPU RTL,
   no FP decoder entry, and no FPU build flag. The question "native or trapped"
   has, today, only one answer that describes reality.
2. **The trap already exists and is already loud.** J4 raises a general illegal
   instruction on the `1111` plane (§2). Trap-and-emulate needs a trap; this is
   it, at zero cost, already tested. The two exceptions are §5's subject and are
   the only work this decision creates.
3. **The cores that would host guests do not have an FPU either.** The plan
   records that the OoO and LT cores have no SH-4 FPU until Phase 7, and
   [fpu/spec.md §6.1](fpu/spec.md) makes Tier 1 a requirement of product points,
   not of the shipping core.
4. **Native guest FP buys the motivating workload nothing.** The workload that
   wants fast FP is a Dreamcast title, and Decision B2-1 puts Dreamcast images on
   the emulation path, where the host FPU is not what executes them.

**What this decision costs, stated plainly.** FP-heavy big-endian SH-4 guests
run their floating point through a trap per instruction. That is expensive, and
if such a guest ever becomes a real workload this decision is the thing to
revisit — with a measurement, not an argument.

**What would reopen it.** All three, not any:

1. A Tier-1 FPU exists in `jcore-cpu` and is enabled on a hypervisor-bearing
   variant.
2. That FPU implements a trappable FP-disable control, so the hypervisor can
   still take ownership per [fpu/spec.md §7](fpu/spec.md)'s lazy model — native
   FP without a disable control is native FP the hypervisor cannot virtualize.
3. A measurement on a real guest workload shows the trap cost is material.

### 4.1 Consequences for `decisions/0006` (endianness)

[decisions/0006](decisions/0006-endianness-is-big-endian.md) rejects a
little-endian J-Core and names two conditions that would together reopen it:
that B2 decides guest SH-4 FP runs *natively*, **and** a measurement showing the
byte-swap emulation cost is material.

**Decision B2-4 answers the first condition "no."** The rejected alternative is
therefore not merely still rejected — it is rejected on a ground that has been
settled rather than deferred. `0006` is updated to say so, and to narrow one
sentence of its argument that this task found to be over-broad: 0006 says a
guest's byte order is a property of the guest image and its device model "not of
the host's fetch path". That is true of an *emulated* guest and false of a *KVM*
guest, which by construction uses the host's fetch path. The conclusion 0006
draws survives — big-endian is right — but by the stronger route of Decision
B2-1: a KVM guest **must** share the host's byte order, so a little-endian host
would exclude big-endian SH-4 Linux guests rather than admitting Dreamcast ones.

### 4.2 Consequences for the SIMD encoding collisions

Because guest FP is *trapped*, the FP encoding space is not a place where
hardware must produce SH-4 answers — it is a place where hardware must produce a
**trap**. That is a weaker obligation than SH-4 fidelity and a stronger one than
"anything goes", and it is exactly the rule in §5. The SIMD collisions with
`FMOV.S` and `FSCA` are consequently not FP-correctness problems; they are
*trap-suppression* problems, which is worse, because a suppressed trap is
silent. §5.

---

## 5. The decode-fidelity rule, and the encodings that break it

> **Decision B2-5 (normative).** On any core that can host an SH-4 guest, every
> encoding SH-4 defines must, when executed by a guest, either (a) behave as
> SH-4 defines it, or (b) raise an exception the hypervisor observes. **No such
> encoding may decode as a different J-Core instruction.**

The rule is deliberately not "J-Core may not reuse SH-4 encodings". Reuse is
fine where it is *contextual and unreachable* — a reinterpretation that requires
an open SIMD block cannot be reached by a guest that never opens one. The rule
bites only on encodings a guest can execute from a cold start.

Applied to the tree, the rule has **two live violations in shipping RTL** and
**two on paper**.

### 5.1 Live, in `jcore-cpu@origin/master`: `CLDS` / `CSTS`

The canonical encoding database ([decisions/0003](decisions/0003-canonical-encoding-database.md),
`jcore-cpu/docs/insns.json`) already records the collision in its own
`collides` annotation: the annotation on flds FRm,FPUL names clds, and the
annotation on fsts FPUL,FRn names csts. Both J-Core forms are marked live on
J2 and J4; both SH-4 forms are marked live on SH-4. They are the same sixteen
bits.

The coprocessor decode that makes them live is on by default —
`copro_decode` defaults true in `core/cpu.vhd` and only the timing-synthesis
harness sets it false — so on a J4 build these two encodings do **not** take the
general-illegal path the rest of the `1111` plane takes. What they do instead
depends on whether a coprocessor is attached, and nothing specifies it. Either
way it is not `FLDS`/`FSTS`, and it is not a trap.

**This is the one finding in this whole task that is a defect in hardware that
exists**, rather than a requirement on hardware that does not. Everything else
here is a rule for future work.

**Why no existing check caught it.** `jcore-cpu`'s collision sweep
([decisions/0003 §Enforcement](decisions/0003-canonical-encoding-database.md))
fails only on two instructions with an identical encoding that **share an
enabled variant**. `CLDS` is a J2/J4 instruction and `FLDS` is an SH-4
instruction, so under that rule they never ship together — which is true of
*bare metal* and false of *a J4 hosting an SH-4 guest*. **Virtualization makes
the SH4 and J4 variant columns co-resident, and the variant rule has no way to
express that.** Teaching the sweep about the guest-hosting pair is work for
**B4**; this document supplies the requirement.

### 5.2 On paper, in `simd/spec.md`

Neither is in any RTL. Both are declared valid **outside** a SIMD block, which
is what makes them violations rather than contextual reuse.

- **`VLD.Q` / `VST.Q`** are given the six SH-4 `FMOV.S` addressing-mode
  encodings and [simd/spec.md §5.6](simd/spec.md) calls them "valid in or out
  of SIMD blocks", contradicting [§5.4](simd/spec.md) of the same document,
  which redefines those encodings *inside* blocks only.
- **`VMKCHG`** is given an encoding in SH-4's FP unary row and
  [simd/spec.md §5.6](simd/spec.md) places it outside SIMD blocks. It is one
  operand form of SH-4's `FSCA`.

A third case is **not** a violation of B2-5 but is a false statement that B4
should not build on: [simd/spec.md §5.4.2](simd/spec.md) introduces its Tier-1
unary operations into the SH-4 FP unary row on the stated grounds that those
slots are free. Four of them are not — SH-4 defines `FLDI0`, `FLDI1`, `FCNVSD`
and `FCNVDS` there, as [fpu/spec.md §5.2–§5.3](fpu/spec.md) and the canonical
database both record. Because these are governed (in-block-only) instructions, a
guest cannot reach them and B2-5 is satisfied; the spec's justification is
simply wrong.

**Re-homing all of these is B4's job**, per
[j4-remediation-plan.md §B4](j4-remediation-plan.md), and B4 was already told to
decide them "jointly with the SH-4-guest decode-fidelity policy". This is that
policy. The list above is what it selects.

---

## 6. The fidelity bar, and the qemu tiebreaker

**The bar is bit-exact wherever the guest can observe it**, and the observable
set is defined by the class in §1: at a trap boundary, the register value read
back and the architectural side effect; on the native surface, the instruction's
architectural result. Timing is explicitly **not** in the observable set — this
matches [fpu/spec.md §1.5](fpu/spec.md)'s non-goal and is the same choice.

**Every emulated surface names an oracle.** An emulation-fidelity requirement
with no way to decide a disputed case is a requirement that will be decided by
whoever writes the code first. The precedence order is:

1. The **SH-4 hardware manual** (Renesas / Hitachi, 1998; SH-4 Software Manual
   Rev. 5.0, 2001) — normative wherever it is unambiguous.
2. **qemu's `target/sh4`** — the tiebreaker where the manual is ambiguous or
   implementation-defined. [fpu/spec.md §1.3](fpu/spec.md) already adopts this
   for the FPU and this document extends it to the emulated register surface.
3. **What real guest software actually depends on**, where 1 and 2 disagree and
   a guest can tell. The observer is the guest.

**Scrutiny of the qemu tiebreaker, since B2 was asked for it.** Three findings,
none of which is "drop it":

- **qemu is not prior art and the pre-2006 policy does not apply to it.**
  [glossary §2](glossary.md) governs *mechanisms adopted into the design*. An
  oracle used to settle a disputed bit is not a mechanism; nothing is adopted
  from it. This is written down so that nobody "fixes" the FPU spec by deleting
  its tiebreaker on a date test.
- **The tiebreaker is not pinned, and an unpinned oracle is not a tiebreaker.**
  "qemu's post-2017 `target/sh4`" names no tag and no commit, so two engineers
  can consult it in different years and get different answers — which is the
  drift this whole effort removes. A specific qemu tag must be cited at the
  point of use. Owner: [fpu/spec.md §1.3](fpu/spec.md) for the FPU surface, and
  the VMM work for the register surface.
- **Its scope is the CPU, not the platform.** `target/sh4` models an SH-4 core.
  It is not an oracle for any Dreamcast platform device, and under Decision B2-1
  that surface is off the KVM path entirely. No oracle is named for it, and none
  is needed until somebody specifies the device model.

---

## 7. The findings map

Every SH-4 finding the cross-subsystem review raised, classified. "Native" here
always carries the §5 obligation.

| Finding | Class | Where it is settled |
|---|---|---|
| `QACR0` / `QACR1` at non-stock J-Core offsets | **Emulated** | §3.2. The VMM presents `0xFF000038` / `0xFF00003C`; the host keeps its own offsets. Closed. |
| `QACR0` / `QACR1` allocated but undecoded in RTL | **Emulated**, and the host side is *not supported until the SQ is built* | §3.3. [sq/spec.md](sq/spec.md) is unimplemented in its entirety. |
| `CCR` allocated nowhere in the map and nowhere in RTL | **Emulated**, with no host register at all | §3.2. Closed: `CCR` is a VMM-side model, and the map is right not to allocate it. |
| Store-queue behaviour | **Native** (data stores) + **emulated** (`QACR`s) | §3.2, §3.3, and [hypervisor/hardware-spec.md §4.4.3](hypervisor/hardware-spec.md). The carve-out must not be enabled before the queues exist. |
| `LDTLB` semantics | **Emulated** | Already specified: [hypervisor/hardware-spec.md §3.3](hypervisor/hardware-spec.md). |
| SH-4 MMU register interface | **Emulated** | §3.2. |
| `EXPEVT` code semantics | **Emulated**, by translation | Decision B2-2, §3.4. |
| AIC2 vectoring | **Emulated** | Decision B2-3, §3.4. |
| Little-endian paired-`FMOV` divergence | **Not supported**, and moot | Decisions B2-1 and B2-4: there is no little-endian guest and no native guest FP. [fpu/spec.md §6.2](fpu/spec.md)'s analysis stays as analysis. |
| SIMD-vs-scalar encoding collisions | **Native — must decode as SH-4 or trap** | Decision B2-5, §5.2. Re-homing is B4. |
| `CLDS`/`CSTS` vs `FLDS`/`FSTS` | **Native — violation in shipping RTL** | §5.1. New in this task; the review did not have it. |
| Guest SH-4 FP native or trapped | **Trapped** | Decision B2-4, §4. |
| J-Core P4 offsets that sit on stock SH-4 registers | **Emulated — no guest consequence**; a bare-metal divergence only | §3.2 and [soc/p4-mmio-map.md §5](soc/p4-mmio-map.md) rule 8. |

---

## 8. Open items, with owners

- **Teach the collision sweep about guest-hosting.** The SH4 and J4 variant
  columns are co-resident under virtualization and the sweep's variant rule
  cannot say so (§5.1). Owner: **B4**.
- **Re-home `CLDS`/`CSTS`, `VLD.Q`/`VST.Q`, `VMKCHG`**, and correct
  [simd/spec.md §5.4.2](simd/spec.md)'s free-slot claim. Owner: **B4**.
- **Pin the qemu tiebreaker to a tag** (§6). Owner: [fpu/spec.md](fpu/spec.md)
  for the FPU surface; the VMM work for the register surface.
- **The store-queue carve-out is enabled against hardware that does not exist**
  (§3.3). Owner: RTL / SoC integration, jointly with
  [sq/spec.md](sq/spec.md).
- **The guest device model itself is unspecified.** This document classifies
  surfaces; it does not specify a single device. Owner: the VMM work
  ([hypervisor/linux-spec.md](hypervisor/linux-spec.md)).
- **J-Core has two disagreeing `EXPEVT` cause tables** (§3.4), and guest cause
  translation needs one. Recorded in [fact-ownership.md](fact-ownership.md)'s
  `Unresolved` list. Owner: **hypervisor / priv-arch spec reconciliation** —
  explicitly not B2, because resolving it moves HEDR bit meanings.
- **`0x014` / `0x018` are unclassified against SH-4** in
  [soc/p4-mmio-map.md §5](soc/p4-mmio-map.md) rule 8: SH-4 places UBC registers
  in that area and this workspace holds no artifact stating their offsets. It
  changes nothing here — a squat and a J-Core addition are equally invisible to
  a guest — but the rule's classification is incomplete until somebody checks.
  Owner: whoever next revises that rule.

---

## 9. Prior art (pre-2006)

| Mechanism | Prior art |
|---|---|
| Trap-and-emulate virtualization of a privileged register surface | IBM VM/370 (1972); Popek & Goldberg, *Formal Requirements for Virtualizable Third Generation Architectures*, CACM 17(7), 1974 |
| Presenting a guest a register map different from the host's | IBM VM/370 CP simulation of channel and control registers (1972) |
| Trapping an entire unimplemented instruction class and emulating it in software | SH-4's own `SR.FD` FPU-disable trap (Renesas SH-4 hardware manual, 1998); Motorola 68040 FPSP (1990); Alpha PALcode instruction emulation (1992) |
| Software emulation of a foreign byte order rather than a hardware mode | DEC FX!32 x86-on-Alpha (1997); IBM DAISY dynamic binary translation (1997) |
| A hardware guest byte-order control, if it were ever added | PowerPC `MSR[LE]` / `HID0[ILE]` (PowerPC architecture, 1993) |
| Exception-cause translation between architectures at the hypervisor boundary | IBM S/370 interpretive execution facility (SIE), 1985 |
