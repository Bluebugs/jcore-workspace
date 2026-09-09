# J-core IOMMU — Multi-Tenant Security Review

**Date:** 2026-09-09 · **Commissioned by:** [j4-remediation-plan.md §C2](../j4-remediation-plan.md)
(*"Commission the IOMMU security review that currently doesn't exist"*), executed as
Wave-3 task **C2d**. · **Scope:** `docs/iommu/{design,hardware,linux}-spec.md` as a
multi-tenant isolation boundary, plus the parts of
[bus/fabric-spec.md](../bus/fabric-spec.md), [hypervisor/](../hypervisor/) and
`linux@origin/jcore` that the IOMMU's guarantees rest on. · **Threat model:**
[security/threat-model.md](../security/threat-model.md) — the adversary is a **guest
kernel on a shared machine**, one that may own a passed-through device. This review
does **not** restate that model; it applies it.

**Companion:** [mmu/security-review.md](../mmu/security-review.md) is the same
exercise for the CPU MMU and this document deliberately follows its shape. Where a
finding here is the IOMMU instance of one settled there, it says so — three are.

---

## 0. Executive summary

**The single most important fact about this design is that none of it is built.**
There is no IOMMU, no IOTLB and no BMID in `jcore-cpu@origin/master` or
`jcore-soc@origin/master`: a case-insensitive search over *all* files for
`iommu|io_mmu|bmid|iotlb|io_tlb|dvma` returns zero matches in both repositories. Every
value reviewed below is a specification value. That is the good news and it is why
this review recommends changing reset polarities rather than negotiating a migration:
**the fix costs nothing today and everything later.**

**The design as written was on the wrong side of its own threat model in five places,
all of them defaults.** Out of reset the IOMMU was disabled, every BMID bypassed, a
`SUPER_BYPASS` bit could be set by anyone who could reach the block and could never be
locked, an IOTLB entry could be marked `GLOBAL` and match every master at once, and
one reserved BMID was a **permanent** bypass that no reset polarity could have closed.
Each is a silent-open failure: the machine works perfectly and is unprotected. All
five are addressed by [hardware-spec.md §3.10](hardware-spec.md)'s `I-R1`–`I-R10`,
which this review is the argument for.

**Three findings are about mechanisms that were specified and do not exist anywhere.**
The spec's block-and-report told an implementer to return a bus error on a bus whose
response record is `{ d, ack }`; its `DEFAULT_PERM` field applied a permission on a
path with no permission check; and its cache-coherency section promised that a
`CACHEABLE` transaction would invalidate CPU cache lines, delegating to a fabric whose
snoop bus has no seat for a device. None of the three is expensive to fix. All three
would have been discovered by an RTL engineer at the worst possible moment, and the
first of them — read literally — hangs the machine.

**The largest implementation prerequisite is not in any spec.** The J-Core bus carries
**no master identifier at all**. `jcore-cpu:cpu2j0_pkg.vhd`'s `cpu_data_o_t` is
`{ en, a, rd, wr, we, d }`; the DDR mux distinguishes its five masters by *port
position*, documented in a comment. The IOMMU's entire isolation model is keyed on
BMID, and there is no field on the wire to put one in. §3 states what that implies
for sequencing.

**Verdict.** The specification's *plumbing* is sound — per-device contexts, a
software-loaded translation cache, unforgeable fabric-assigned IDs, block-on-miss —
and the design choice not to walk page tables in hardware removes an entire class of
attack surface for free. The gaps were entirely in **which way the switches point**
and in **what happens at the end of a device's life**. Bar item **L2** does not move
to `MET`: everything below is now specified and none of it is implemented.

## 1. Attack-landscape applicability

Rated for the IOMMU boundary specifically. The CPU-side families are
[security/threat-model.md §6](../security/threat-model.md)'s and are not repeated.

| Family | Applies? | Mechanism here | Status after this review |
|---|---|---|---|
| **Thunderclap** (NDSS 2019) — IOMMU on, mappings too coarse → arbitrary kernel R/W | **APPLIES** | The `GLOBAL` bit is the coarse mapping in its purest form: one entry, every master | Closed — `I-R5` |
| **Boot/reset bypass window** (Garrett; Linux deferred-attach; DATE 2024) | **APPLIED, permanently** | Reset was all-bypass and unclaimed devices stayed bypassed forever | Closed — `I-R1` |
| **Unclaimed / unenumerated device** | **APPLIES from two directions** | Hardware: a BMID no driver touches. Kernel: a DT node with no `iommus` property, whose `-ENODEV` the OF layer swallows | Hardware half closed by `I-R1`; kernel half is **residual** — see IS-I8 |
| **Teardown / handover window** | **APPLIES** | A device released to a new owner before its mappings are revoked | Closed — `I-R7` |
| **Debug-path DMA** | **APPLIES** | BMID `0xFF` was a permanent bypass with no rule against assigning it to a master port | Closed — `I-R6` |
| **Confused-deputy via the hypercall interface** | **APPLIES** | `HCALL_HV_IOMMU_MAP` takes a guest-supplied `bmid` | Closed — `I-R10` |
| **Cross-device denial of service / capacity channel** | **APPLIES** | One 64-entry pool, one free list, first fit; exhaustion makes a *victim's* map fail and its device fault-and-disable | Closed — `I-R8` |
| **Stale-data / coherence** | **APPLIES** | Device writes a buffer; CPU reads a stale cached line | **Open by design, and owned** — [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md) |
| **IOTLB timing side channel** (occupancy, hit/miss timing) | **PARTIAL** | Steady-state miss rate is zero by design (§3.1), so there is no miss-timing signal to mine on the hot path. The *capacity* signal is the DoS above, which is architectural, not timing | Bounded; the residual is `I-R2`'s constant-time block requirement |
| **BMID spoofing** | **DOES NOT APPLY** | BMID is a per-port constant inside the fabric, overwriting anything the master asserts ([bus/fabric-spec.md §4.1–§4.2](../bus/fabric-spec.md)) | Strength, and it is load-bearing for everything else |
| **Malicious page-table content / walker attacks** (VT-d, SMMU class) | **DOES NOT APPLY** | There is no hardware walker and no IOMMU-visible page-table format (§3.1, §3.4) | Strength by construction |
| **I/O page faults / PRI abuse** | **DOES NOT APPLY** | No demand paging from devices; no ATS/PRI | Out of scope by design |
| **Rowhammer via DMA** | **APPLIES** | An IOMMU bounds *which* rows a device can hammer; it does not stop hammering within a mapped buffer | Out of scope — SDRAM controller and physical allocator, as on the CPU side |

## 2. Specification review (findings)

**Confirmed correct (defences present before this review):** per-BMID tagging of every
IOTLB entry with fabric-assigned, unforgeable IDs; block-on-miss as the default
outcome of a lookup, which is what makes "deny" free; per-entry R/W permissions
checked on the translated path; no hardware walker and no software-visible page-table
format, removing the largest IOMMU attack surface by construction; the reserved-value
policy for the BMID space; and the hypervisor's fail-closed P4 trap, which keeps every
IOMMU register out of a guest's reach without the IOMMU spec having to say anything.

**A note on the `Status` column, because it deliberately does not say `RESOLVED`.**
[decisions/0002](../decisions/0002-supersede-convention.md)'s `RESOLVED` marker means
*a named artifact is merged on an integration branch*, and the checker verifies it.
Nothing below has an artifact: every closure here is a change to a specification for
hardware that does not exist. **"Closed in spec"** is therefore the accurate word, and
using `RESOLVED` would have been a claim the tree could not support — the failure mode
[decisions/0002](../decisions/0002-supersede-convention.md) was written about. These
rows become `RESOLVED` when RTL lands and the matching `I-E` guard goes green, and not
before.

| # | Sev | Finding | Security consequence | Status |
|---|---|---|---|---|
| **IS-C1** | Critical | `hardware-spec §3.9` reset value was *"all bits set (all BMIDs bypass)"* and `§3.1`'s `ENABLE` reset was `0`, *"IOMMU bypassed for all masters"* | The boot-window vulnerability made permanent: every device unprotected from power-on, and every device no driver ever claims unprotected forever | **Closed in spec** — [hardware-spec.md §3.10](hardware-spec.md) `I-R1`, `I-R3`. Guard `I-E0`, `I-E1` |
| **IS-C2** | Critical | `IOMMU_CTRL[2] SUPER_BYPASS` — *"all transactions bypass regardless of `BMID_BYPASS`"* — had **no lock** | A single register write disables the entire IOMMU for every master, at any time, with no way to make it un-writable | **Closed in spec** — `I-R4`, a write-once lock that also arms itself on the first IOTLB entry written. Guard `I-E2` |
| **IS-C3** | Critical | `IOTLB_TAG_HI[1] GLOBAL` — *"If set, match any BMID"* | Thunderclap's shape: one mistyped bit maps a buffer into every device's address space, including devices attached later and devices owned by other tenants | **Closed in spec** — `I-R5`: the entry never matches and the install is refused. Guard `I-E4` |
| **IS-C4** | Critical | [bus/fabric-spec.md §4.3](../bus/fabric-spec.md) made BMID `0xFF` a **permanent bypass** and — unlike `0x00` — stated **no rule** forbidding the fabric from assigning it to a master port | A bypass no reset polarity can close, one integration decision away from a master with unconditional physical DMA, on a diagnostic path that a board's JTAG connector makes physically reachable | **Closed in spec** — `I-R6` and the revised §4.3 |
| **IS-C5** | Critical | `HCALL_HV_IOMMU_MAP(iova, ra, perms, bmid)` ([hypervisor/design-spec.md §4.6](../hypervisor/design-spec.md)) takes **`bmid` from the guest**, and no document said the hypervisor validates it | A guest installs an IOTLB entry under a *peer's* BMID: the peer's device DMAs into the attacker's buffer, or `UNMAP` revokes the peer's live ring and the resulting fault disables the peer's device. The one IOMMU control that is delegated to the adversary | **Closed in spec** — `I-R10` and the revised §4.6 |
| **IS-I1** | Important | `hardware-spec §2.2` specified *"a bus error (AXI `SLVERR` or equivalent). The data phase is suppressed for reads"* | The bus has no error field (`cpu_data_i_t` is `{ d, ack }`), so this is unimplementable; read literally it means never asserting `ack`, which stalls the master forever and can wedge every master behind it in a fixed-priority mux. A denial of service as the *default* path | **Closed in spec** — `I-R2`: complete with zero data, discard the write, constant-time |
| **IS-I2** | Important | Detach and teardown were **unspecified**, and the only text about them — `linux-spec §10.1`, *"attach and detach toggle the `BMID_BYPASS` bit"* — specifies the **wrong direction** | A toggle back to 1 releases the device into unrestricted DMA. The Thunderclap window at the *end* of a device's life, which is exactly when a device is handed to another tenant | **Closed in spec** — `I-R7` and [linux-spec.md §5.4a](linux-spec.md). Guard `I-E3` |
| **IS-I3** | Important | One 64-entry IOTLB, one `entry_used` bitmap, first-fit, no per-BMID accounting | One tenant's device exhausts the pool; the *victim's* `dma_map_*` returns `-ENOSPC`, the victim's next unmapped DMA faults, and the documented response to a fault is *"disable the offending device"*. A tenant can switch off another tenant's device, at will | **Closed in spec** — `I-R8`. Guard `I-E5` |
| **IS-I4** | Important | `hardware-spec §7` promised *"`CACHEABLE = 1`: Transaction is coherent … writes invalidate matching cache lines on CPUs"*, delegating to *"the bus fabric [which] is responsible for routing snoop traffic"* | A guarantee sited in a block with no path to any cache, delegated to a transport whose single snoop originator is the L2 and whose only destinations are CPU L1-D ports. A driver trusting it reads stale data; a tenant device exploiting it has a stale-read primitive | **Withdrawn** — `I-R9`; the contract is owned by [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md), which finds the kernel half is currently a no-op |
| **IS-I5** | Important | `IOMMU_CTRL[7:4] DEFAULT_PERM`, *"permission applied when bypass active"*, reset `0xC` | No pipeline stage consulted it — the bypass path has no permission check for a default to apply to. A control with no enforcing logic, whose only real effect was to make the reset word read as deliberately open | **Closed in spec** — deleted, [hardware-spec.md §3.1a](hardware-spec.md) |
| **IS-I6** | Important | `design-spec §4.1`'s topology diagram routes the CPU cores through the fabric into the IOMMU; the sentence beneath it says *"the CPU's accesses do not pass through the IOMMU"* | Harmless while everything bypassed — both readings produced the same machine. Under `I-R1` the diagram's reading denies a core its own boot fetch | **Closed in spec** — `I-R1a` makes the client set normative |
| **IS-I7** | Important | `hardware-spec §4.3`: multiple entries matching → *"behavior undefined"* | A duplicate-install software bug selects which tenant's frame a device reaches. The IOMMU instance of [mmu/security-review.md](../mmu/security-review.md) **S-I5**, which was resolved on the CPU side with a detector and a defined exception | **Closed in spec** — blocked, invalid-request fault. Costs one sticky bit over a scan that is already `entries`-wide |
| **IS-I8** | Important | `of_iommu_configure()` returns `-ENODEV` for a device with no `iommus` property and `of_dma_configure_id()` **swallows it**, configuring plain `dma-direct` | A DMA-capable device someone forgot to annotate gets raw physical DMA, silently, with no failed probe. The decision is made in the OF layer before this driver is consulted | **Mitigated, not fixed.** `I-R1` makes the forgotten device fail loudly on its first DMA instead of working unprotected. The kernel-side half is residual — see §5 |
| **IS-M1** | Minor | `IOTLB_TAG_HI`'s bit list assigned `[7:0]` to `reserved` **and** `[1]`/`[0]` to `GLOBAL`/`VALID` — overlapping ranges | A conformant implementation could have read `VALID` as reserved-zero (matches nothing) or the reserved range as writable (matches everything) | Fixed; ranges are disjoint |
| **IS-M2** | Minor | `linux-spec §5.2`'s `.map` allocates **one** `entry_idx` and writes it once per attached BMID | A multi-BMID domain ends with one working mapping. The natural fix an implementer reaches for is `GLOBAL`, which is why this and IS-C3 had to land together | Fixed in the text; one index per BMID |
| **IS-M3** | Minor | `linux-spec §5.4` indexed the bypass bitmap with `bmid / 8` and the bit with `bmid % 32` | For every BMID above 7 this touches the wrong register and the wrong master's bit. Under all-bypass reset it silently leaves the attaching device unprotected and makes an innocent device fault; under `I-R1` it can only fail closed | Fixed; the arithmetic is now stated in [hardware-spec.md §3.9](hardware-spec.md) |
| **IS-M4** | Minor | `hardware-spec §2.1` lists `SIZE` (*"standard AXI burst size encoding"*), `LEN` and a 4-bit `ID`; §11's cost table budgets *"AXI master/slave"* | There is no AXI anywhere in either repository, and no transaction ID on the J-Core bus. Aspirational signals in a normative signal table | Noted in §2.2 and §3 below; the signal table is left as the intended target interface |
| **IS-M5** | Minor | `linux-spec` is written against a removed kernel API: `.detach_dev`, `.map`/`.unmap`, `bus_set_iommu()`, `struct iommu_fault_event`, and `.domain_alloc` for new drivers | Not a vulnerability, but the missing member is `.detach_dev` — where an implementer would have put IS-I2's re-protection | Documented, [linux-spec.md §4.3a](linux-spec.md) |
| **IS-M6** | Minor | `iommu.passthrough=` (`drivers/iommu/iommu.c:806`) and `CONFIG_IOMMU_DEFAULT_PASSTHROUGH` turn every default domain into an identity domain | A software `SUPER_BYPASS` with no lock, reachable from the command line | Documented, [linux-spec.md §2a](linux-spec.md); an integration that cares must refuse it |
| **IS-M7** | Minor | `linux-spec §8.1`'s resume wrote `pm_state.ctrl` back to `IOMMU_CTRL` wholesale | Restores whatever `SUPER_BYPASS` held at suspend and treats a reset-cleared lock as saveable state | Fixed; the lock is re-taken, never restored |

## 3. Implementation review

**There is no implementation.** This section exists rather than being omitted, because
"no RTL" is a different statement from "not reviewed", and because four facts about
the *existing* hardware bear directly on what an IOMMU implementation would have to do
first. All are read at `origin/master`.

| # | Sev | Finding | Consequence |
|---|---|---|---|
| **IH-1** | **Critical prerequisite** | **No bus protocol in either repository carries a master identifier.** `jcore-cpu:cpu2j0_pkg.vhd` declares `cpu_data_o_t` as `{ en, a, rd, wr, we, d }` and `cpu_data_i_t` as `{ d, ack }`. There is no `ID`, no `prot`, no `user`, no BMID. The DDR-side mux `jcore-soc:components/misc/bus_mux_typec.vhm` distinguishes its five masters by **port position**, recorded in a comment (*"m1 cpu0 data / m2 cpu0 inst / m3 cpu1 data / m4 cpu1 inst / m5 dma"*); the identity is wiring, and is not recoverable downstream | The IOMMU's entire isolation model is keyed on BMID, and there is nothing on the wire to carry one. **Widening the bus record is the first commit of any IOMMU implementation**, it touches every master and slave in both repositories, and it is a prerequisite no specification currently names. [bus/fabric-spec.md §0](../bus/fabric-spec.md) calls BMID tagging the T0→T1 step; this is what that step costs |
| **IH-2** | Important | The response record has **no error field** (above) | IS-I1's substrate finding. `I-R2` is written the way it is because of this line of VHDL |
| **IH-3** | Important | **No DMA master exists.** `jcore-soc:components/dma/` holds a `README` reading *"Stub implementation of CoreSemi DMA engine"*, a `dma_pkg.vhd` of types, and no entity. `dma_dbus_o` is tied to a constant zero on all four boards (`targets/boards/{ulx3s,mimas_v2,turtle_1v0,microboard}/soc.vhd`) and looped back in the non-cached architectures. Every peripheral that exists — the Ethernet MAC, SPI, GPIO, the AICs — is a bus **slave** | The only bus masters in any J-Core configuration today are the CPU's I- and D-cache legs. This is why bar item **L2** is not *blocking* today, and it is the reason to fix the specification now rather than later: there is no deployed behaviour to migrate |
| **IH-4** | Important | **An L1-D snoop port exists and is tied off.** `cache_pkg.vhd:467-470`'s `dcache_snoop_io_t` is `{ al, en }` — address and enable — and is a real external port (`sa`/`sy` on `dcache.vhd`, `snpc_o`/`snpc_i` on `dcache_adapter.vhd`); an incoming address clears the matching line's valid bit (`dcache_ccl.vhm:534-536`). It is cross-wired CPU↔CPU in the two-CPU build and tied to `NULL_SNOOP_IO` in the one-CPU build and in the production wrapper. `dma_dbus_o` connects to none of it | The hardware a DMA write would need to invalidate a stale CPU line is present, invalidate-only, and one wire from the DMA leg of the DDR mux. [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md) names the wire |
| **IH-5** | Minor | `jcore-soc:components/misc/flash_boot_reader.vhd` is a non-CPU initiator whose ports are a **private SPRAM write port**, not a bus master port | A memory writer no bus-level IOMMU can see. Bypass path 7 in [hardware-spec.md §3.10](hardware-spec.md); named rather than closed |

**What this review cannot say**, stated so a green summary is not read as more than it
is: nothing here is an implementation review in the sense
[mmu/security-review.md §3](../mmu/security-review.md) is. That document could find
that the RTL was in places *more* correct than the spec. Here there is no RTL to be
more correct, so every finding above is a finding about text, and the guard tests
`I-E0`–`I-E6` are the only thing that will ever distinguish a spec that says the right
words from hardware that does the right thing. That is the limit
[fact-ownership.md](../fact-ownership.md) records for every name fact describing
hardware that does not exist, and it applies to all ten `I-R` rules.

## 4. Design ↔ implementation ↔ test alignment

| Property | Specified? | Implemented? | Tested? |
|---|---|---|---|
| Deny at reset | ✅ `I-R1` | ❌ no RTL | `I-E0`, `I-E1` — written, not runnable |
| Block completes with defined data | ✅ `I-R2` | ❌ | `I-E1` |
| `ENABLE` cannot be cleared | ✅ `I-R3` | ❌ | `I-E0` |
| `SUPER_BYPASS` locked | ✅ `I-R4` | ❌ | `I-E2` |
| `GLOBAL` never grants | ✅ `I-R5` | ❌ | `I-E4` |
| Reserved BMIDs blocked | ✅ `I-R6` | ❌ | `I-E1` (parameterised on BMID) |
| Detach re-protects before release | ✅ `I-R7` + kernel `blocked_domain` | ❌ no driver, no hardware | `I-E3` |
| IOTLB quota | ✅ `I-R8` | ❌ | `I-E5` |
| Coherence is software's | ✅ `I-R9`, [0010](../decisions/0010-dma-coherence-is-software-maintained.md) | ⚠️ **the kernel half is a no-op today** — 0010 §Context | `I-E6` — fails at every tier |
| Hypercall `bmid` validated | ✅ `I-R10` | ❌ no hypervisor | none yet — see §5 |
| BMID unforgeable | ✅ [bus/fabric-spec.md §4](../bus/fabric-spec.md) | ❌ **no master ID on the bus at all** (IH-1) | none possible |

**The alignment story is uniform and it is the honest summary of this review:
everything is specified, nothing is implemented, and every test is written against
hardware that does not exist.** The one row that is not uniform is coherence, where
the *kernel* half exists, is reachable, and is wrong.

## 5. Recommendations

### 5a. Already done by this review
`I-R1`–`I-R10` in [hardware-spec.md §3.10](hardware-spec.md); the negative tests
`I-E0`–`I-E6` in §10.1; [decisions/0010](../decisions/0010-dma-coherence-is-software-maintained.md);
the `bmid` validation in [hypervisor/design-spec.md §4.6](../hypervisor/design-spec.md);
the reserved-BMID rules in [bus/fabric-spec.md §4.3](../bus/fabric-spec.md) and
conformance point T1-5.

### 5b. Open, with an owner named
1. **IS-I8 residual — the OF layer's fail-open path.** `I-R1` makes the consequence
   loud but the kernel still configures raw `dma-direct` for an un-annotated device.
   The kernel-side fix is a `def_domain_type` / probe-time policy that refuses rather
   than falls back on a J-Core SoC. Owner: whoever writes `jcore-iommu.c`.
2. **The kernel's DMA cache maintenance is a no-op on J4.** [0010](../decisions/0010-dma-coherence-is-software-maintained.md)
   decision 4. This is reachable *today*, unlike everything else in this review, and
   becomes a correctness bug the day a DMA master exists.
3. **IH-1 — no master ID on the bus.** Sequencing prerequisite for every other item.
   Owner: the first task that builds T1 fabric.
4. **A test for `I-R10`.** The other nine rules have a guard in §10.1; the hypercall
   check does not, because it is software in a hypervisor that does not exist. It
   should land with the hypercall handler, as a negative test: guest *A* calling
   `HCALL_HV_IOMMU_MAP` with guest *B*'s BMID must be refused.

### 5c. Documented residuals (non-guarantees)
- **Bypass path 7** — a master with a private path to memory is outside the IOMMU's
  guarantee, by construction. `flash_boot_reader` is the existing instance.
- **Capacity, not access.** `I-R8` bounds starvation; it does not make IOTLB
  occupancy unobservable, and a tenant can still learn *something* from its own
  allocation failures.
- **Rowhammer within a mapped buffer.** An IOMMU bounds which rows a device reaches
  and nothing else.
- **Coherence.** Not a guarantee of this block, at any tier. [0010](../decisions/0010-dma-coherence-is-software-maintained.md).

## Appendix — what was searched, so the negatives are checkable

All at `origin/master` (`origin/jcore` for `linux`), never the checked-out submodule
pointer, per [decisions/0002 §2](../decisions/0002-supersede-convention.md).
Case-insensitively, because VHDL is case-insensitive and `git grep` is not.

- `iommu`, `io_mmu`, `bmid`, `iotlb`, `io_tlb`, `dvma`, `bus master id` over **all**
  files in `jcore-cpu` and `jcore-soc` — **zero matches in both**.
- `l2`, `l2cache`, `l2_cache` — no file with `l2` in its path in either repository;
  every VHDL token hit is a `textio` `line` variable, an FPGA ball name, or a comment
  about the *TLB*'s second tier.
- `axi`, `axi4`, `axi_`, `wishbone`, `wb_`, `avalon` — no bus of any of those names;
  the `wb_` hits are pipeline **writeback** signals in `core/datapath.vhd` and
  `core/register_file_ebr.vhd`, and the `mid` hits are "mid-frame"/"mid-bit" in the
  Ethernet PHY.
- `snoop`, `snp`, `coheren`, `directory`, `dir_`, `probe`, `inv_req` — the only
  coherence hardware is IH-4's L1-D invalidate broadcast. `SNOOP` in
  `components/ring_bus/ring_bus_pkg.vhd` is a **ring routing mode**, and the ring bus
  is instantiated by no board. `probe` in `core/cpu.vhd` is English.
- `drivers/iommu/*jcore*` and `grep -i jcore drivers/iommu/` in `linux@origin/jcore` —
  **zero matches**. `IOMMU` over `arch/sh/**Kconfig*` — **zero matches**.
