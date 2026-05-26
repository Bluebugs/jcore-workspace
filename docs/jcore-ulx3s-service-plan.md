# J-Core Experimentation Service on ULX3S 85F — Plan

**Status:** Draft  
**Target board:** ULX3S with LFE5U-85F-6BG381C  
**Audience:** Reference for build-out; assumes familiarity with the Phase 1 MMU, Phase 2 IOMMU, and Phase 3 hypervisor design documents (specs 01–09)

---

## 1. Summary

Build a small fleet of ULX3S 85F boards running a J-Core SoC with hypervisor support, exposed as a public service where software developers can reserve short-lived KVM-style guest VMs to experiment with the J-core / SuperH ecosystem.

The **primary goal is providing an excellent SH4 development environment**. SH4 has an existing binary ecosystem (Dreamcast, embedded Renesas, retro dev) and an audience that wants real hardware to run it on. J64 is a deferred research track; the post-MVP roadmap is built around making SH4 fast and rich on this platform first.

The service ships in three tiers that share the same auth, tooling, and observability:

- **Tier 0 — QEMU SH4 user-mode** on the OVH VPS. High-concurrency, fast, free or near-free. Ships within weeks of the infrastructure spine. Reuses the same Debian SH4 rootfs as the hardware tier.
- **Tier 1 — Real hardware VM** on j-core. Paravirtualized Debian SH4 guest with cross-compilers, dev tools, and standard packages preinstalled, on a read-only shared rootfs. Real MMU, real timings, real hardware-bug surface. Ships at Phase 5.
- **Tier 1.5 — Dual-issue OoO J32** (Phase 6), then dual-core + FGMT (6.5), then SH4 FPU coprocessor (7) and SIMD prefix unit (7.5). Tenants opt into richer profiles at reservation time.

A **differential testing harness** (Phase 5.5) runs the same binary on Tier 0 and Tier 1 and diffs the architectural output — turning tenant workloads into an automated continuous hardware-conformance test. This is also the safety net for deploying the OoO core in Phase 6.

Per-tenant traces, console logs, hypercall samples, IOMMU faults, and hardware metrics are streamed to **SigNoz on the OVH VPS** — both in-band from the J-core itself and out-of-band via the on-board ESP32, so observability survives any j-core failure mode.

**Tenants are always GitHub-authenticated**; no anonymous access. SSH keys are pulled live from GitHub (`<user>.keys`). Tenants SSH to **sshpiperd on the OVH VPS**, which validates against the cached GitHub keys and routes via a dedicated raw WireGuard tunnel to the right board's VM (or a QEMU container, for Tier 0).

The fleet sits behind **two separate MikroTik devices** at home for hardware-level isolation between the planes:

- A **tenant Ethernet gateway** (no Tailscale, no mgmt traffic ever) — pure VLAN/WG/firewall device terminating the tenant raw-WireGuard tunnel and switching per-board VLANs
- A **management MikroTik** running the Tailscale subnet router and the management WiFi AP for ESP32s

The OVH VPS is the consolidated public hub. It runs sshpiperd (public port 22), SigNoz, the jcore-mgmt REST API, the MCP server, the raw-WG endpoint for tenant traffic, the Tailscale node for management, the QEMU Tier 0 containers, and Cloudflare Tunnel for the HTTPS reservation web UI. A separate **super-user track** provides programmatic remote access — the MCP server above the REST API exposes board control, bitstream lifecycle, VM lifecycle, and log queries to Claude Code, reached over the Tailscale management plane.

The plan is staged so that each phase delivers a working, demonstrable system. Tier 0 ships at Phase 1B, Tier 1 MVP at Phase 5, OoO at Phase 6, and J64 only after the SH4 path is fully fleshed out.

---

## 2. Goals and non-goals

### Goals

- **Primary: provide an excellent SH4 development environment.** SH4 has existing binaries and an existing audience. Make it fast and rich here first.
- Software-developer audience: discover the J-core / SuperH ecosystem without owning hardware
- Tenant runtime is upstream Debian SH4 across all tiers (QEMU emulation and real hardware use the same image)
- **Three-tier service architecture sharing one platform:** Tier 0 (QEMU emulation), Tier 1 (real hardware VM), Tier 1.5 (richer cores: OoO, dual-core, FPU, SIMD). Tenants choose at reservation time.
- Real hardware-virtualized isolation between concurrent tenants on real-hardware tiers (Option C from earlier discussion)
- Per-tenant traces and logs sufficient to find and diagnose hardware bugs early
- **Automated differential testing** between Tier 0 (QEMU) and Tier 1 (j-core) on every opted-in tenant binary, turning the service into a continuous hardware-conformance test rig
- Architecture survivable to j-core wedges, panics, and reflash bricking
- Programmatic super-user access (REST API + MCP server) for iterative hardware-and-software development, including agent-driven workflows via Claude Code
- **GitHub-authenticated tenants only**; SSH keys pulled live from GitHub; no anonymous access ever
- **Two-MikroTik hardware split for plane isolation:** tenant data plane and management plane terminate on physically separate devices that share only the WAN uplink
- **Tailscale for management, raw WireGuard for tenant data:** the tenant data path has no dependency on Tailscale's coordination plane
- **Minimal public attack surface on the VPS:** only port 22 (sshpiperd) is publicly listening; HTTPS reaches the reservation UI via Cloudflare Tunnel with no inbound port 443
- All major design decisions trace to documented pre-2006 prior art (sun4v, PowerPC HV, SH-4, AltiVec)

### Deferred / research goals (post-SH4-excellence)

- **J64 ISA** (mode bit, COMPAT, eventually ifunc-dispatched J32+ acceleration). Scheduled as Phase 8/8.5 once the SH4 path is complete. Demoted from the original roadmap because SH4 has the installed binary base; J64 has none.
- **OoO J64** — explicitly out of scope for the 85F; quad-issue OoO J64 would consume the entire device. If pursued at all, would be on a separate beefier FPGA platform.

### Non-goals

- Hardware-engineer **tenant** audience (bitstream-level access by paying users) — possible later as a "power-tenant" tier, not in scope here. Note: super-users (the platform's own developers) DO get bitstream-level access via the MCP track.
- Framebuffer / desktop / video — explicitly dropped; the SDRAM bandwidth and LUT cost don't justify the value
- Live migration between boards
- Unmodified vintage SH kernel support — paravirt-only guests
- Full Debian J64-native port (new `sh64-linux-gnu` triple) — multi-year upstream effort, out of scope; the J64 phase provides COMPAT for existing sh4 binaries instead
- Cloud-density tenant counts — 2–3 concurrent VMs per board is the realistic ceiling

---

## 3. System architecture

The architecture consolidates around a single public-facing **OVH VPS hub**, with **two physically separate MikroTik devices** at home providing the management/tenant plane isolation, and **two independent tunnels** to the VPS — Tailscale for management, raw WireGuard for tenant data — that share no coordination or trust.

### High-level topology

```
                          Public internet
                                 │
                         ┌───────┴────────┐
                         │  ISP modem/ONT │
                         └───────┬────────┘
                                 │
                       ┌─────────┴──────────┐
                       │ Dumb switch / VLAN │
                       │  trunk (shared WAN)│
                       └──┬──────────────┬──┘
                          │              │
                ┌─────────▼─────┐  ┌─────▼────────────┐
                │  Mgmt MTK     │  │  Tenant MTK      │
                │  (hAP ax3)    │  │  (CRS / hEX S)   │
                │               │  │                  │
                │ • Tailscale   │  │ • wg-tenant      │
                │   container   │  │   raw WG to VPS  │
                │ • Mgmt WiFi   │  │ • Per-board VLAN │
                │   (WPA2-Ent)  │  │ • Strict fw      │
                │ • Subnet-RT   │  │ • No mgmt traffic│
                │   mgmt VLAN   │  │   ever           │
                └───┬───────────┘  └────┬─────────────┘
                    │                   │
                    │ Mgmt VLAN (WiFi)  │ Tenant VLANs (Ethernet)
                    ▼                   ▼
                ESP32 #1 ─────┐    ┌──── ULX3S #1 j-core
                ESP32 #2 ─────┤    ├──── ULX3S #2 j-core
                ESP32 #N ─────┘    └──── ULX3S #N j-core
                                  (each board has both)

                          ▲                ▲
                  Tailscale│                │raw WG
                          │                │
                ┌─────────┴────────────────┴───────────┐
                │           OVH VPS-1                  │
                │                                      │
                │   PUBLIC (single port: 22)           │
                │   ├─ sshpiperd     ←─── tenants      │
                │                                      │
                │   PUBLIC (Cloudflare Tunnel, no port)│
                │   ├─ cloudflared   ←─── tenant web UI│
                │                                      │
                │   TAILSCALE INTERFACE ONLY           │
                │   ├─ SigNoz (OTLP, ClickHouse, UI)   │
                │   ├─ jcore-mgmt REST API             │
                │   ├─ MCP server                      │
                │   └─ mosquitto (ESP32 telemetry)     │
                │                                      │
                │   wg-tenant INTERFACE ONLY           │
                │   └─ sshpiperd egress to boards      │
                └────────────────────┬─────────────────┘
                                     │
                              Tailscale tailnet
                              (admin nodes only)
                                     │
                            ┌────────┴────────┐
                            │                 │
                       Dev laptop        (other admin
                       (Claude Code,      laptops)
                        MCP client)
```

### Per-board plane isolation

Each ULX3S board has **two independent network attachments** terminating on different physical devices:

```
   ULX3S board
   ├─ WiFi (ESP32) ──────→ Mgmt MikroTik (mgmt VLAN, Tailscale)
   └─ Ethernet (LAN8720) ─→ Tenant MikroTik (board-N VLAN, wg-tenant)
```

Separate media (radio vs copper), separate switches, separate firewall rulesets. Tenant traffic on a board's Ethernet cannot influence ESP32 traffic, and vice versa, under any bug or compromise scenario short of physical access to the board itself.

### Why two MikroTiks (hardware-level plane isolation)

A single MikroTik with VLANs would be logically isolating but mechanically shared. Two devices give:

- **No shared CPU/RAM between the planes.** Tenant-side firewalling and management-side Tailscale never compete for resources.
- **No shared firmware bug surface.** A vulnerability in RouterOS's container subsystem (Tailscale lives in a container) doesn't expose tenant traffic.
- **Clean failure modes.** Tenant gateway dies → mgmt MikroTik still reports the outage. Mgmt MikroTik dies → in-progress tenant sessions unaffected.
- **Right-sizing per role.** Tenant gateway can be a cheap L2/L3 switch (no containers needed). Mgmt MikroTik needs ARM64 + container support, gets dedicated CPU for Tailscale relay.

### Why two tunnels (no Tailscale in the tenant data path)

The two tunnels share no software, no keys, no coordination:

| Aspect | Tenant data tunnel | Management tunnel |
|---|---|---|
| Protocol | Raw WireGuard (kernel iface) | Tailscale (container + DERP) |
| Initiated by | Tenant MTK outbound to VPS | Tailscale mesh (NAT-traversal) |
| Keys managed by | Us, in jcore-mgmt config | Tailscale (or self-hosted Headscale) |
| Reaches | Tenant VLANs only | Mgmt VLAN + admin laptops + VPS |
| Coordination dependency | None | Tailscale's control plane |
| Lifecycle | Static; one tunnel for the fleet | Dynamic; nodes added/removed per laptop |

If the Tailscale coordination plane ever has a hiccup, tenant SSH continues. If we ever switch from Tailscale to Headscale (or vice versa) for management, the tenant path doesn't move.

### Public attack surface on the VPS

Exactly **one** publicly listening port:

| Port | Service | Notes |
|---|---|---|
| 22/tcp | sshpiperd | Tenant SSH ingress; hardened (see §7.5) |

HTTPS reaches the reservation web UI through Cloudflare Tunnel: `cloudflared` agent on the VPS connects outbound to Cloudflare, which routes inbound public HTTPS via the tunnel. **No inbound port 443.**

Everything else — SigNoz UI, jcore-mgmt REST, MCP server, mosquitto for ESP32 telemetry — listens only on the Tailscale interface and is unreachable from the public internet.

### Three telemetry flows (updated for the consolidated hub)

1. **In-band via ESP32 relay.** J-core OTel collector → ESP32 over UART → mgmt WiFi → mgmt MikroTik → Tailscale → VPS SigNoz. Full-fidelity metrics, traces, logs.
2. **Out-of-band native ESP32.** ESP32 own telemetry (power, thermal, FPGA heartbeat, bitstream events) → same path. Independent of j-core health.
3. **Crash gasp.** When j-core wedges, ESP32 still streams last console lines via the same Tailscale path to SigNoz.

The ESP32 UART link from board to ESP32 is the **only** path j-core telemetry takes off-board. The j-core never exposes anything publicly itself.

The console mirror on the ESP32 simultaneously goes to the tenant's interactive session and to the observability sink. Guest panic messages survive to the observability VM regardless of j-core network state.

---

## 4. Hardware platform

### ULX3S LFE5U-85F

| Resource | Quantity |
|---|---|
| Logic | 84,000 LUT4 |
| DSP | 156 × 18×18 |
| BRAM (EBR) | 3.7 Mbit |
| PLLs | 4 |
| Main RAM | 32 MB SDRAM @ ~166 MHz, ~200 MB/s peak shared |
| Storage | MicroSD + 4–16 MB QSPI flash |
| Networking | LAN8720 RMII module on J1 (100 Mbit, ~$2) + onboard ESP32 WiFi |
| Out-of-band MCU | ESP32 (WiFi/BT, own GPIO, owns FTDI passthrough) |
| Video | GPDI (unused in this plan) |
| Audio | 3.5 mm jack (unused in this plan) |

### Companion hardware

- **Tenant Ethernet gateway** (one MikroTik): pure VLAN/firewall/WG device. Suggested models:
  - **CRS326-24G-2S+** (~$200) — 24 GbE for medium fleets
  - **RB5009** (~$250) — ARM64, more headroom
  - **hEX S** (~$60) — 5 GbE, sufficient for ≤4 boards
  - Terminates the `wg-tenant` raw-WireGuard tunnel to the VPS. No Tailscale, no mgmt traffic.
- **Management MikroTik** (one device): runs the Tailscale subnet router and the WPA2/3-Enterprise WiFi AP for ESP32s. Natural choice:
  - **hAP ax3** (~$120) — WiFi 6 onboard, ARM64, container support; consolidates AP + Tailscale relay in one box
- **Upstream WAN sharing:** small dumb switch (or the ISP router's LAN ports if there are enough) so both MikroTiks can reach the internet. Neither needs inbound from internet — both initiate tunnels outbound.
- **OVH VPS-1** (~€4/mo): 8 GB RAM, 4 vCPU, 75 GB NVMe, unlimited bandwidth. Hosts sshpiperd, SigNoz, jcore-mgmt REST API, MCP server, mosquitto for ESP32 telemetry, cloudflared for the HTTPS reservation UI, raw-WG endpoint for tenants, Tailscale node for management.
- **Cloudflare account** (free tier): for Cloudflare Tunnel fronting HTTPS. Eliminates inbound port 443 on the VPS.
- **Tailscale** (free tier sufficient) **or self-hosted Headscale** (no third-party dependency if preferred): coordination plane for the management mesh.
- **Optional console fallback:** USB-FTDI cable per board for physical-presence recovery when ESP32 reflash bricks the bitstream.

### Ancillary verification hardware (optional, off the critical path)

These don't block any phase but extend the differential-testing matrix and accelerate j-core onboarding:

- **Numato Mimas V2** (~$50): Spartan-6 LX9 with 512 Mb DDR SDRAM, 64 MB usable. Canonical j-core J2 reference platform per the upstream docs. SH-2 ISA only (no MMU, no FPU, no Ethernet). Worth it as onboarding to the upstream j-core build flow before our own RTL work. Requires Xilinx ISE (legacy 32-bit toolchain) — friction worth knowing about. *Alternative: a second ULX3S 85F (~$130) acts as a "reference board" with the same open-source nextpnr/yosys toolchain; more expensive but lower friction.*
- **Sega Dreamcast** (~$30–50) **+ HIT-0400 Broadband Adapter** (~$200–400): real SH-4 silicon, runs LinuxDC over NFS root. 16 MB RAM, 200 MHz, 10 Mbit Ethernet. Gold-standard SH-4 conformance reference once the differential harness exists (Phase 5.5+). Hardware ground truth especially valuable when the Phase 7 FPU lands and softfloat-vs-hardware divergences need adjudication.

The previously planned standalone "observability host" at home is **eliminated** — SigNoz lives on the VPS. The local network at home becomes purely the boards, ESP32s, and the two MikroTiks.

---

## 5. Resource budgets

### LUT4 budget (cumulative through phases)

| Component | LUT4 | BRAM | DSP | Phase added |
|---|---:|---:|---:|---|
| J32 in-order baseline core | 3,000–5,000 | small | 0 | 2 |
| Phase-1 MMU additions | +1,500–2,000 | small | 0 | 2 |
| SDRAM controller | ~3,000 | small | 0 | 2 |
| LiteEth MAC + LAN8720 | ~3,000 | small | 0 | 2 |
| SD card, UART, AIC2, misc | ~2,000 | small | 0 | 2 |
| **Phase 2 subtotal** | **~12,500–15,000** | ~10% | 0 | |
| Phase-2 IOMMU | +2,500–3,500 | small | 0 | 3 |
| Phase-3 hypervisor (HPRIV, trap delegation) | +100–300 | small | 0 | 4 |
| **Phase 4 subtotal (MVP ships here)** | **~15,000–18,500** | ~15% | 0 | |
| **Dual-issue OoO J32 upgrade (replaces in-order)** | **+~5,000–7,000 (delta)** | **+15%/core** | 0 | **6** |
| 2nd core + FGMT (per core +1,500–2,500) | +12,000–17,000 | +15% | 0 | 6.5 |
| SH4-compat FPU coprocessor | +11,000–19,000 | small | 4–8 | 7 |
| SIMD prefix unit | +4,000–6,000 | ~3% | 4–8 | 7.5 |
| J64 datapath widening (optional, deferred) | +2,000–3,000 | small | 0 | 8 |
| **Full SH4-rich stack (Phase 7.5)** | **~50,000–65,000 LUT4** | **~50%** | **8–16 DSP** | |

The OoO J32 design is BRAM-heavy by deliberate choice (state in BRAM, logic in LUTs), giving ~10K LUT4 per core including the dual-issue logic. At Phase 7.5 (full SH4 stack: dual-core OoO + FPU + SIMD), the 85F sits at ~60–75% LUT4 utilization with ~50% BRAM, leaving real timing-closure margin.

OoO J64 is **explicitly out of scope** for the 85F — a quad-issue OoO J64 core would consume the entire device (~50–80K LUT4 alone). If pursued, it lives on a separate FPGA platform as a research target.

### Memory budget (per board, 32 MB)

| Mode | Layout |
|---|---|
| Single-tenant (Phase 2) | kernel 6 MB + userspace 6 MB + tenant work 18–20 MB |
| Multi-tenant, no DAX (naive) | host 6 MB + 3 × (kernel 4 MB + RO 4 MB + RW 2 MB) ≈ 36 MB (doesn't fit) |
| Multi-tenant, virtio-pmem DAX RO rootfs | host 6 MB + RO-shared 6 MB + 3 × (kernel 4 MB + RW 2 MB) ≈ 24 MB |
| Multi-tenant, XIP kernel + DAX | host 6 MB + RO-shared 8 MB + 3 × (kernel data 1 MB + RW 2 MB) ≈ 17 MB |

Realistic concurrent VM count: **2–3 typical, 4 achievable with XIP kernel.**

---

## 6. Tenant experience

### Authentication

- **GitHub OAuth required**; no anonymous access ever. Tenant identity is the GitHub username + verified email.
- **SSH keys pulled live from GitHub** at lease provisioning time: `https://github.com/<user>.keys`. No separate key management, no key upload UI, no key rotation problems — the tenant's GitHub keys are the source of truth.
- Lease provisioning checks: account age (e.g. >7 days to prevent throwaway accounts), basic GitHub activity heuristic, no prior abuse flag.
- Abuse handling: block at the GitHub-username level; all leases by that user revoked immediately.

### What the tenant receives

- One paravirtualized Debian SH4 guest VM for the lease window
- SSH access using their existing GitHub-registered keys (no new key to manage)
- Tenant traffic NAT'd through their board's dedicated VLAN — fully isolated from other tenants at the switch level
- Pre-installed: SH2/SH4/J32/(J64) cross-compilers, gdb, git, editors, common dev tools (see package list in §11)
- Working outbound network (NAT'd; SMTP blocked; no inbound exposure)
- A welcome banner explaining GitHub username, board ID, bitstream hash, ISA variant, lease expiry time

### What the tenant does NOT receive

- Root on the host
- Ability to load kernel modules (paravirt guest kernel is locked-config)
- Persistent state across leases — overlay tmpfs wipes on lease end
- Runtime `apt install` (see Rootfs strategy below)
- Bitstream reflash rights (initially; could be a "power-tenant" tier later)
- Visibility of other tenants on the network (per-board VLAN isolation enforced at MikroTik)

### Guest kernel configuration

- `CONFIG_JCORE_PARAVIRT=y` — hypercalls for memory management, context switch, virtio device discovery
- `CONFIG_FS_DAX=y`, `CONFIG_DEV_DAX=y` — for the shared rootfs
- erofs RO root mounted with `-o dax`
- Possibly built XIP for the kernel text segment when memory pressure justifies it
- Standard virtio devices: virtio-console, virtio-net, virtio-pmem

### Rootfs strategy: Debian SH4

The shared tenant rootfs is built from **Debian Ports `sh4`** via `debootstrap --arch=sh4`. Familiar environment, real package ecosystem, working `apt-cache`/`apt-search`, standard toolchain (`gcc-sh4-linux-gnu`, `binutils-sh4-linux-gnu`).

Properties:

- Single erofs image, signed and bitstream-pinned
- Mounted via virtio-pmem with DAX into every guest
- Read-only with overlay tmpfs for tenant-writable layer
- Single physical copy in host RAM serves all VMs
- Rebuild & redeploy in atomic swap; existing leases keep old image until lease ends

**Critical trade-off: no runtime `apt-get install`.** A debootstrapped Debian SH4 base is ~150 MB on disk (~60–80 MB as erofs); apt-unpack peaks at 10–30 MB per package, which doesn't fit in the tenant's 2–4 MB writable budget. The platform deliberately bakes everything tenants might want into the base image; `apt install` returns ENOSPC by design. Tenants needing a package file a request → it enters the next image build → all tenants get it on next lease. This is also a reproducibility win.

When J64 lands (Phase 6), the same Debian SH4 image runs unmodified in J64-compat mode — this is what we call **"Debian J32+"**. Optional J64-accelerated libraries (memcpy, AES, hashing) layered in via ifunc dispatch as Phase 6.5; no ABI change.

---

## 7. Super-user access (admin / development track)

A separate track from the tenant API, used by the platform's own developers to iterate hardware and software. Designed for both human use (scripts, browser) and agent use (Claude Code via MCP).

### Architecture

The REST API is the source of truth. The MCP server is a thin wrapper over it — same auth, same audit log, same rate limits. Anyone can script directly against REST; Claude Code gets a friendlier interface via MCP. Everything reaches the management plane via **Tailscale**, never via public ports.

```
   Claude Code on dev laptop
        │  MCP (stdio over Tailscale)
        ▼
   ┌──────────────────────┐
   │  jcore-mcp server    │  (Rust or Go; runs on VPS or locally)
   └─────────┬────────────┘
             │ HTTPS over Tailscale (tag:admin → tag:vps)
             │ + optional FIDO2 step-up
             ▼
   ┌──────────────────────────────────┐
   │  jcore-mgmt REST API             │  (on VPS, Tailscale iface)
   │  • board fleet                   │
   │  • bitstream catalog & flash     │
   │  • VM lifecycle                  │
   │  • log/metric proxy to SigNoz    │
   │  • reservation override          │
   └──┬──────────┬─────────────────┬──┘
      │          │                 │
      │          │                 │
   ESP32     Tenant MTK         SigNoz
   (via mgmt (via Tailscale     (local on VPS;
    MikroTik  for control,      Tailscale-only
    subnet-   never for data    listener)
    route on  plane)
    tailnet)
```

### Tailscale ACL sketch

```
"tagOwners": {
  "tag:vps":         ["group:admins"],
  "tag:mgmt-mtk":    ["group:admins"],
  "tag:admin":       ["group:admins"]
},
"acls": [
  // Admin laptops reach VPS services and ESP32s
  {"action":"accept", "src":["tag:admin"],
   "dst":["tag:vps:*", "tag:mgmt-mtk:*", "192.168.X.0/24:*"]},

  // VPS reaches mgmt MikroTik and ESP32s for control + telemetry pull
  {"action":"accept", "src":["tag:vps"],
   "dst":["tag:mgmt-mtk:*", "192.168.X.0/24:*"]},

  // ESP32s push telemetry to VPS
  {"action":"accept", "src":["192.168.X.0/24"],
   "dst":["tag:vps:4317,4318,1883"]},   // OTLP grpc/http + MQTT

  // Default deny
]
```

Note that **none** of these ACLs mention the tenant VLANs. The tenant data plane is on a separate raw-WireGuard tunnel terminating on the tenant MikroTik — it doesn't exist in the tailnet at all.

### MCP tool surface (initial)

Hardware control:

- `list_boards()` — fleet inventory with current status
- `power_cycle(board_id)` — via ESP32
- `flash_bitstream(board_id, image_ref)` — uploads to ESP32, JTAG flashes, returns new hash
- `read_bitstream_hash(board_id)`

Observability:

- `query_logs(filter, time_range)` — wraps SigNoz queries
- `query_metrics(query, time_range)`
- `get_panic_snapshot(vm_id)` — full panic record by vm_id
- `tail_console(board_id, vm_id, follow=true)` — streaming

VM lifecycle:

- `spawn_debug_vm(board_id, image_ref, profile)` — admin VM bypassing reservation system
- `list_active_vms(board_id?)`
- `force_destroy_vm(vm_id, reason)` — audited

Development workflow:

- `compare_bitstreams(hash_a, hash_b)` — diff RTL provenance
- `replay_workload(crash_id, target_board)` — spawn VM in conditions of a past crash, optionally on a different bitstream
- `enable_trace(vm_id, level)` — escalate tracing fidelity on a live VM
- `run_on_host(board_id, command)` — glass-break tool; heavily audited, rate-limited, requires reason string

### Auth and audit

- **Access path: Tailscale onto the management mesh.** The jcore-mgmt REST API is bound to the VPS's Tailscale interface and is unreachable from the public internet.
- **On top of Tailscale, optional FIDO2 hardware-key step-up for destructive operations** (`flash_bitstream`, `force_destroy_vm`, `run_on_host`). Cheap to require for the few operations where physical-presence guarantees matter.
- **Every super-user action audit-logged** to SigNoz with the same `bitstream_hash` tagging as everything else — the audit trail is queryable alongside bug forensics
- `run_on_host` is a glass-break tool: logged loudly, rate-limited, mandatory reason string

### The iteration loop this enables

By Phase 4 the development cycle becomes:

1. Edit RTL locally → CI builds bitstream
2. `flash_bitstream(board_2, build/abc123.bit)`
3. `spawn_debug_vm(board_2, debian-sh4, profile=trace)`
4. SSH into the VM, run the failing test
5. `query_logs(board_2, last_10m)` → see what hardware did
6. `compare_bitstreams(abc123, last_known_good)` → narrow the regression
7. Loop

That's the right tool for finding hardware bugs early — the core goal.

### 7.5 Tenant ingress: sshpiperd + raw-WG tunnel

The tenant SSH path is independent of everything above. Same VPS, separate concerns.

**Flow:**

1. Tenant SSHes to `lease-<id>@bastion.example.com:22`
2. **sshpiperd** on the VPS accepts the connection, parses `lease-<id>` from the username
3. sshpiperd's `restful` plugin calls `POST /v1/ssh-route` on the jcore-mgmt API (over loopback on the VPS): `{lease_id, client_pubkey_fingerprint, client_ip}` → `{upstream_host, upstream_port, mapping_key}` or auth failure
4. The API validates lease is still active, fetches and caches `https://github.com/<user>.keys` (1-hour TTL), checks the client's offered pubkey against the user's GitHub keys
5. On match: sshpiperd proxies the connection through the **`wg-tenant`** WireGuard interface to the VM on the right board
6. Optionally records the session as asciicast in `/var/log/sshpiperd/<lease_id>/` for audit

**Egress firewall:** sshpiperd runs as its own user; nftables rules restrict that user's egress to `wg-tenant` only. Even if sshpiperd were somehow compromised, it can't reach the Tailscale interface, the loopback admin services, or the internet.

**SSH hardening stack** (Cloudflare doesn't proxy raw SSH for our model, so we're on our own here):

- sshpiperd as the **first-line gatekeeper**: strict username regex (`^lease-[a-z0-9]{8}$`), key-only auth, no password. Rejects 99.99% of scanner traffic at the protocol layer.
- **nftables rate-limit** on inbound port 22: max 6 new connections per minute per source IP, with established connections unaffected.
- **CrowdSec** (modern fail2ban) watches sshpiperd logs, bans IPs hitting many invalid-username attempts, shares ban intel with the community feed so we benefit from collective scanner detection.
- **No password auth, ever.** Key-only at sshpiperd, key-only at the backend VMs.
- **Audit trail** of every connection attempt — successful or not — shipped to SigNoz via the Tailscale interface for forensics.

At our scale this is comfortably sufficient. Targeted attackers would find the endpoint regardless of port choice; random scanners bounce off the username regex with no measurable load on the VPS.

---

## 8. Observability

### SigNoz stack

- **Lives on the OVH VPS**, bound to the Tailscale interface only (not publicly listening)
- Single-binary or docker-compose deployment
- ClickHouse storage with retention sized for forensics (months, not days)
- OTLP gRPC :4317 + OTLP HTTP :4318, both Tailscale-only
- **mosquitto** MQTT broker co-resident on the VPS for ESP32 telemetry; ESP32s publish via the Tailscale subnet route through the mgmt MikroTik
- Alerting on TLB miss outliers, IOMMU fault spikes, unexpected resets
- Storage budget at our scale: ~500 MB–1 GB/day means 75 GB NVMe holds 75+ days; tier ClickHouse retention (full traces 7–14 days, aggregates 90+ days) if needed

### Telemetry schema

Every signal is tagged with **bitstream_hash** at minimum. Without it, hardware-bug forensics is impossible.

| Signal | Source | Required tags |
|---|---|---|
| Console line | Hypervisor vUART + ESP32 mirror | tenant_id, vm_id, bitstream_hash, board_id |
| Hypercall sample | Hypervisor trace ring | tenant_id, vm_id, hcall_type |
| IOMMU fault | Phase-2 IOMMU fault log | bmid, fault_addr, fault_type, bitstream_hash |
| TLB / G-TLB miss rate | Hardware counters | vm_id, asid, vmid |
| Guest panic snapshot | Hypervisor panic detector | tenant_id, vm_id, registers, last_N_console |
| Power / reset event | ESP32 | board_id, cause |
| Thermal sample | ESP32 + ADC | board_id, temp_c |
| Bitstream reflash | ESP32 | board_id, new_hash, prev_hash, source |
| FPGA heartbeat | ESP32 (polls j-core) | board_id, last_response_ms |
| Lease event (start/end) | Reservation service | tenant_id, vm_id, board_id, profile |

### Telemetry behavior requirements

- J-core OTel collector: **bounded local ring buffer**, drop-oldest on overflow, **never blocks** the CPU on network failure
- ESP32 forwarder: same — local buffer, best-effort forward, never blocks IPMI control path
- Both push at low rate by default; tenant opt-in for high-fidelity per-VM ftrace
- Sampled hypercall traces only — full traces only when tenant opts in

---

## 9. Phased plan

Each phase ends with a demonstrable deliverable. Phases marked **parallel** can run alongside the previous phase.

### Phase 0 — Bring-up + infrastructure provisioning (2–3 weeks)

Scope: validate the physical board (stock j-core bitstream, Linux on serial via FTDI, SDRAM/SD/ESP32 smoketest). **Provision the full infrastructure spine:**

- **Tenant Ethernet gateway MikroTik:** per-board VLANs, kernel WireGuard interface (`wg-tenant`) with placeholder peer (VPS not provisioned yet), egress NAT and outbound filter policy (no SMTP, no inbound, conn rate-limit), `.rsc` config in version control.
- **Management MikroTik:** WPA2/3-Enterprise SSID for ESP32s on the mgmt VLAN, Tailscale container installed and authenticated to the tailnet as `tag:mgmt-mtk`, advertising the mgmt VLAN subnet as a Tailscale subnet route. `.rsc` config + container env in version control.
- **OVH VPS-1 provisioned:** Debian stable base, Tailscale installed and authenticated as `tag:vps`, `wg-tenant` interface configured as the peer of the tenant MTK, Cloudflare Tunnel client (`cloudflared`) installed (no service yet — wired up later), firewall: only port 22 publicly exposed (sshpiperd not installed yet, port closed for now).
- **Tailscale tailnet:** ACL policy uploaded, tags defined, OAuth-based auth keys configured for headless devices.
- **Cloudflare account + zone for `*.example.com`:** API token for cloudflared, DNS record for the future reservation UI.
- **Dev laptop:** Tailscale installed with `tag:admin`, verified reachability of VPS and mgmt MTK over the tailnet.

Deliverable: reproducible Make/Ansible target ending in `uname -a` over serial on a board. Both MikroTik configs and the VPS bootstrap script under version control. Tailscale reachability verified (laptop → VPS, laptop → mgmt MTK, laptop → ESP32-stand-in via subnet route).

### Phase 0.5 — SigNoz on VPS (1 week, parallel to Phase 1)

Scope: install SigNoz on the VPS bound to the Tailscale interface only (never publicly listening). Stand up the mosquitto MQTT broker for ESP32 ingest. Configure ClickHouse retention. Smoke-test OTLP and MQTT ingest from a dev-laptop test client over the tailnet.

Deliverable: SigNoz UI reachable from a dev laptop via Tailscale; test OTLP and MQTT writes from the laptop succeed; nothing exposed publicly.

### Phase 0.7 — Numato J2 onboarding rig (parallel to Phase 0–1, ~1 week, optional)

Scope: stand up a Numato Mimas V2 with the upstream stock J2 bitstream as an off-critical-path j-core reference.

- Flash the published j-core J2 bitstream onto the Mimas V2 over USB
- Prepare a microSD with a stock uClinux `vmlinux + initramfs`
- Boot to serial console, run upstream Dhrystone for sanity check
- Document the build flow with Xilinx ISE so the team has hands-on familiarity with the upstream j-core toolchain before our own RTL work

Dependencies: none (parallel to all other phases).

Deliverable: a Numato board on a shelf, reproducibly bootable to a uClinux shell on stock J2, kept as a reference. Optional alternative: a second ULX3S 85F with the stock j-core bitstream serving the same "known-good reference" role with our existing toolchain.

**Note on differential-testing value:** J2 is SH-2 only, so this rig does NOT serve as a third leg for SH-4 binary differential testing. It's an onboarding and upstream-regression-check tool, not a conformance reference for the tenant ISA.

### Phase 1 — ESP32 IPMI + ESP32 telemetry over Tailscale (3–4 weeks)

Scope: ESP32 firmware exposing power cycle, JTAG-over-WiFi reflash, serial console proxy, status reporting. ESP32 publishes board-level telemetry (power, thermal, heartbeat, bitstream hash) over MQTT to mosquitto on the VPS, reaching it via the mgmt MikroTik subnet route on the tailnet. Console mirror also pushed to VPS for capture.

Dependencies: Phase 0, Phase 0.5.

Deliverable: from a dev laptop on Tailscale, query ESP32 status, push a bitstream, attach to console. ESP32 telemetry visible in SigNoz. Verify ESP32 cannot reach the public internet directly (only via the mgmt MikroTik's NAT, and only routable into via Tailscale).

### Phase 1.5 — Management REST API skeleton on Tailscale (1–2 weeks, parallel to Phase 2)

Scope: stand up the `jcore-mgmt` REST API on the **VPS, bound to the Tailscale interface only** (not publicly listening). Initial endpoints: list_boards, power_cycle, flash_bitstream, read_bitstream_hash. Wire to ESP32 IPMI via the mgmt MikroTik subnet route. All actions audit-logged to SigNoz with `bitstream_hash` and reason string.

Dependencies: Phase 1.

Deliverable: super-user can `curl --cert ...` to reboot a board, push a bitstream, read its hash. OpenAPI spec published. All actions audit-logged to SigNoz with `bitstream_hash` and reason string.

### Phase 1B — Tier 0 QEMU SH4 user-mode service (1–2 weeks)

Scope: stand up the QEMU SH4 user-mode container infrastructure on the VPS, the foundation of Tier 0.

- `qemu-sh4-static` registered via `binfmt_misc` on the host
- Per-tenant container image (rootless Docker or Podman) with the Debian SH4 erofs base mounted read-only, an overlayfs writable layer per session, SH4 cross-compilers and dev tools preinstalled
- Container lifecycle managed via the jcore-mgmt REST API (lease → spawn → expiry → tear down)
- Initial access via Tailscale only (super-user testing); public access lands when Phase 4.7 sshpiperd ships and routes Tier 0 leases to containers instead of board VMs
- Memory: ~50–100 MB per container; VPS-1 fits 30–60 concurrent sessions comfortably
- Same Debian SH4 rootfs used here is the Tier 1 image; Phase 1B doubles as image-build validation

Dependencies: Phase 1.5.

Deliverable: super-user on the tailnet can spawn a Tier 0 lease, SSH into it via Tailscale-only path, build and run a "hello world" SH4 binary, container is torn down at lease expiry. The same image and toolchain that will land in Tier 1 are now exercised end-to-end on QEMU.

### Phase 2 — J32 + Phase-1 MMU + Ethernet + Debian SH4 rootfs + OTel collector (1–2 months)

Scope: integrate the Phase-1 MMU spec into the existing J-core. LAN8720 RMII on J1. **Debian SH4 base built via `debootstrap --arch=sh4`**, packaged as erofs with DAX support. Lightweight OTel collector cross-compiled for SH, shipped in the rootfs, pointed at the observability VM.

Dependencies: Phase 1.

Deliverable: SSH into single-tenant Debian SH4 on J32. OTel data flowing to SigNoz tagged with bitstream hash. The erofs image is the exact one later phases will use as shared image.

### Phase 2.5 — MCP server v1 (1 week, parallel or immediately after Phase 2)

Scope: thin MCP wrapper around the existing REST endpoints. Tools at minimum: `list_boards`, `power_cycle`, `flash_bitstream`, `read_bitstream_hash`, `query_logs`, `query_metrics`, `tail_console`. Distributed as a small Rust or Go binary.

Dependencies: Phase 1.5, Phase 2.

Deliverable: Claude Code can flash bitstreams and tail console while developing later phases. Every subsequent phase's bring-up benefits from this iteration loop.

### Phase 3 — Phase-2 IOMMU (1 month)

Scope: implement BMID-tagged IOMMU per spec. Wire the Ethernet and SD paths through it. Validate device DMA cannot cross BMID boundary via a deliberate misbehavior test from a kernel module.

Dependencies: Phase 2.

Deliverable: IOMMU active in single-tenant mode; fault log entries appearing in SigNoz when a test driver tries unauthorized DMA. Network stack and SD path unaffected.

### Phase 4 — Phase-3 hypervisor + KVM port + virtio-pmem + per-VM tagging (2–3 months)

Scope: HPRIV mode, trap delegation register, hypervisor in HS mode, paravirt-aware KVM userspace. virtio-pmem device emulation in KVM userspace mapping the shared erofs image. Per-VM telemetry tagging propagated through hypercall traces, IOMMU faults, panic snapshots.

Dependencies: Phase 3.

Deliverable: launch a paravirt guest VM via `kvm-tool` from the host shell; tenant SSHes into the guest directly; shared rootfs visible read-only with DAX; per-VM data in SigNoz tagged with vm_id.

### Phase 4.5 — VM lifecycle + replay tools in MCP (2–3 weeks)

Scope: extend the MCP/REST surface with VM-spawning, listing, force-destroy, `get_panic_snapshot`, `enable_trace`, `compare_bitstreams`, `replay_workload`. The replay tool is the single highest-value addition — it lets Claude Code reproduce tenant crashes on chosen bitstreams.

Dependencies: Phase 4.

Deliverable: Claude Code can spawn a debug VM, replay a recorded crash on a different bitstream, and diff the resulting telemetry against the original.

### Phase 4.7 — Tenant ingress: sshpiperd + Cloudflare Tunnel (2–3 weeks)

Scope: bring up the tenant-facing public surface.

- **sshpiperd** on the VPS, listening on public port 22. Configured with the `restful` plugin pointing at `POST /v1/ssh-route` on the local jcore-mgmt API (loopback). Egress restricted via nftables to the `wg-tenant` interface only.
- **`/v1/ssh-route` endpoint** in jcore-mgmt: input `{username, client_pubkey_fingerprint, client_ip}`, output `{upstream_host, upstream_port, mapping_key}` or auth failure. Caches GitHub `.keys` lookups for 1 hour.
- **Mapping-key infrastructure:** per-board mapping keys generated and stored in jcore-mgmt.
- **`cloudflared`** on the VPS for the HTTPS reservation UI. Cloudflare zone configured; tunnel established outbound; no inbound port 443 on the VPS.
- **SSH hardening:** nftables rate-limit on port 22 (6 new conns/min/IP), CrowdSec installed and watching sshpiperd logs.

Dependencies: Phase 4.5.

Deliverable: connect from internet to a test VM via `ssh lease-test01@bastion.example.com`, with sshpiperd validating against a stub `.keys` set. Reservation UI placeholder reachable at `https://example.com` via Cloudflare Tunnel with no inbound 443 on the VPS.

### Phase 5 — Reservation UX + GitHub OAuth + lease lifecycle (1 month)

Scope: web UI for board fleet behind Cloudflare Tunnel, **GitHub OAuth integration** as the only authentication method, **SSH key fetch from `<user>.keys` at lease provisioning**, lease lifecycle managed by ESP32 IPMI in coordination with the host (lease start → fetch keys → spawn VM with keys baked in → register lease+pubkey set in `/v1/ssh-route` → present SSH endpoint → lease end → VM teardown → board reset). Abuse-list of GitHub usernames maintained out-of-band.

Dependencies: Phase 4.7.

Deliverable: public URL where any GitHub user can sign in, reserve a VM, and SSH in using their existing GitHub keys within seconds. Abuse-list enforcement verified.

**End of MVP. Public service ships here.**

### Phase 5.5 — Differential testing harness (3–4 weeks)

Scope: orchestrator service on the VPS that runs the same binary on Tier 0 (QEMU container) and Tier 1 (real-hardware VM) and diffs the architectural output. Foundation for both continuous SH4 conformance testing and the OoO bring-up safety net in Phase 6.

- **Orchestrator** (Go or Python) on the VPS, Tailscale-only listener for super-user API + opt-in tenant submission endpoint behind GitHub auth
- **Normalization layer:** mask non-determinism — PIDs, timestamps, ASLR, `/dev/urandom`; FP tolerance bands for the eventual Phase 7 FPU vs QEMU softfloat divergence
- **Bounded execution:** per-tier wall-clock limits (real hardware ~100× slower than QEMU); timeout = divergence
- **Test corpus:** seeded with cross-compiled SH4 versions of glibc tests, kernel selftests, gcc/LLVM test-suite, CSmith/Yarpgen-generated programs; grown by opt-in tenant submissions
- **Result reporting:** every divergence shipped to SigNoz tagged with `bitstream_hash`, QEMU version, binary hash; queryable as a first-class signal
- **Sharing back:** anonymized divergences (tenant identity stripped) optionally published upstream to benefit the broader j-core community

Dependencies: Phase 5, Phase 1B.

Deliverable: a nightly run of the seed corpus produces zero divergences on a known-good bitstream. A deliberately broken bitstream (e.g., delay-slot bug introduced) triggers divergence alerts in SigNoz with full forensic context. Tenants can opt into "contribute to bug-finding corpus" at lease time.

**Differential testing matrix** — the harness is designed to compare 2+ reference points per binary. Initially 2-way (QEMU vs ULX3S); extends to 3-way when the Dreamcast reference (Phase 5.7) comes online:

| Target | ISA | What it tells you |
|---|---|---|
| QEMU SH4 user-mode (Tier 0) | SH-4 emulated | Reference architectural semantics |
| ULX3S j-core | SH-4 + j-core extensions | Our actual platform |
| Dreamcast (Phase 5.7) | Real SH-4 silicon (SH7091) | Hardware ground truth, esp. FPU |
| Numato J2 (Phase 0.7) | SH-2 only | Upstream regression check (limited scope) |

Three-way agreement on QEMU + Dreamcast + ULX3S is strong evidence of correctness. Any single divergence flags a candidate bug, and the *direction* of divergence often hints at which implementation is at fault.

### Phase 5.7 — Dreamcast as SH-4 hardware reference (2–3 weeks, optional)

Scope: integrate a real Dreamcast as the third leg of the differential test harness, providing SH-4 silicon ground truth.

- Acquire and refurbish a Dreamcast (capacitor check, GD-ROM service if needed). Have a spare on the shelf.
- Coder's Cable for initial serial-only bring-up; Broadband Adapter (HIT-0400) when available for NFS-rooted Linux.
- LinuxDC distro with NFS root over the BBA; SSH access from the management network. Treated as a management-VLAN device (it's a verification reference, not a tenant target).
- Diff-harness extension: third target type in the orchestrator, with the same normalization + tolerance bands. Account for the 16 MB RAM ceiling — diff-test binaries used against Dreamcast must fit in a small working set.

Dependencies: Phase 5.5 (the diff harness must exist to extend).

Deliverable: the diff harness can run a seed-corpus binary on all three targets (QEMU, ULX3S, Dreamcast) and report agreement or divergence. Especially exercised once Phase 7 FPU work begins — Dreamcast is the SH-4 FPU ground truth.

**Note for Phase 8 onward:** Dreamcast is SH-4 only and opts out of the diff harness for J64-mode binaries. QEMU vs ULX3S 2-way diff remains the J64 path; Dreamcast's role is bounded to SH-4 conformance.

### Phase 6 — Dual-issue OoO J32 core (3–6 months)

Scope: replace the in-order J32 with a dual-issue out-of-order J32 designed around memory-latency hiding (not arithmetic parallelism). The 85F's 32 MB SDRAM at ~200 MB/s shared is the binding workload constraint; OoO's value is keeping the ALU busy during 30–50 cycle SDRAM stalls, not feeding multiple multipliers.

Microarchitecture sketch:

- **Two integer ALUs**, one of each specialized unit (mul, shift, eventual FPU, eventual SIMD)
- **BRAM-heavy state:** rename map, reorder buffer, issue queue, load-store queue, physical register file, branch predictor all in BRAM. ~15% of total BRAM per core.
- **~10K LUT4 per core** for the dual-issue logic, wakeup, bypass, scoreboarding
- **SH4 memory model preserved:** stores commit in program order; loads OoO with LSQ hazard checks; `synco` drains the LSQ; CAS.L drains and re-issues without speculation past
- **Fmax expectation:** ~50–65 MHz on ECP5-6 (down from in-order's ~80 MHz), but ~1.4–1.8× wall-clock improvement on memory-bound tenant workloads via latency hiding

Spec deliverable: a new `10-ooo-design-spec.md` document the microarchitecture explicitly (issue rules, retire rules, memory ordering guarantees, hypervisor visibility — none).

Dependencies: Phase 5.5 (differential harness must exist as the safety net before deploying OoO to tenants).

Deliverable: tenants opt into "OoO J32" profile at reservation; differential harness reports zero retired-state divergence vs QEMU on the seed corpus; in-order J32 remains available as fallback. Measurable wall-clock improvement on representative workloads (compile, network, crypto).

### Phase 6.5 — Dual-core + 2-way FGMT on OoO core (1–2 months)

Scope: promote `cpus_two_fpga.vhd` to coherent SMP with the dual-issue OoO core. Add 2-way FGMT per core. Hypervisor scheduler updated to assign vCPUs to hardware threads. Realistic concurrent-VM count nudges from 2–3 to 3–4 (RAM still binding constraint, but more CPU to spread across guests).

Dependencies: Phase 6.

Deliverable: 4 CPUs visible in `/proc/cpuinfo` on host; or 2 VMs each with 2 vCPUs; or one VM with all four. Kernel self-build `make -j4` on the host.

### Phase 7 — SH4-compat FPU coprocessor (2–3 months)

Scope: SH4-compat FPU exposed via coprocessor interface, power-gateable. Includes FIPR, FTRV, FSCA, FSRRA — the full SH4 FP instruction set so Dreamcast / Renesas SH4 binaries can use hardware FP. Single FPU shared across cores via coprocessor bus arbitration (not duplicated per core, per the OoO design philosophy).

Dependencies: Phase 6 (the OoO core's coprocessor interface).

Deliverable: SH4 binaries with hardware floating point run at native speed; differential harness reports controlled tolerance-band divergence vs QEMU softfloat (and we now have ground truth on which one is correct per IEEE 754); new tenant profile "OoO J32 + FPU" available.

### Phase 7.5 — SIMD prefix unit (2–3 months)

Scope: SIMD prefix instruction scheme as a separate coprocessor, 128-bit lanes, opt-in per tenant. Crypto throughput on SSH improves substantially (3–5× on SSH bulk transfers); checksums and memcpy on TCP improve materially.

Dependencies: Phase 7 (FPU and SIMD share DSPs; sequence to share is established here).

Deliverable: tenants opt into "OoO J32 + FPU + SIMD" — the full SH4-rich profile. SIMD micro-benchmarks runnable; SSH bulk transfer measurably faster than the non-SIMD baseline.

**End of SH4-excellence track. The platform now provides a genuinely first-class SH4 development environment with hardware-virtualized tenant isolation, observability, OoO performance, FPU, SIMD, and SMP.**

### Phase 8 — J64 + COMPAT (deferred research, 1–2 months)

Scope: J64 mode bit (SR.SF), widened ALU and register file, MMU widening, Linux `arch/sh64` with `CONFIG_COMPAT`. The existing Debian SH4 rootfs runs unmodified in J64-compat mode — **this is "Debian J32+"** and it's essentially free from this phase: same ABI, same binaries, hosted by a 64-bit kernel. New tenant profile "J64 native" added for tenants experimenting with the wider ISA, even though no Debian J64 archive yet exists (tenants compile their own J64 binaries from the SH4 toolchain with `-mabi=64` once that backend lands).

**Note on prioritization:** J64 has no existing binary ecosystem — every J64 binary is one a user compiles fresh. SH4 has a real installed base. This phase is therefore deferred until the SH4 path (Phases 6–7.5) is complete and the platform's primary value proposition is delivered. J64 then becomes a research-track expansion, not the MVP roadmap.

Dependencies: Phase 7.5.

Deliverable: tenant can select "J64 host kernel + Debian SH4 userspace" at reservation (Debian J32+); existing tenant images keep working. Separate experimental profile lets advanced users build and run J64 native binaries directly.

### Phase 8.5 — Debian J32+ ifunc-dispatched J64 acceleration (3–6 months, upstream work, optional)

Scope: upstream gcc / glibc work to mark binaries with `.note.gnu.property` indicating J64-capable, and add ifunc resolvers in glibc for the hot paths (memcpy, memset, AES, SHA, ChaCha). Same SH4 ABI, opt-in J64-accelerated execution. Modeled on x86_64-v2/v3/v4 and arm64 HWCAP dispatch.

Dependencies: Phase 8.

Deliverable: rebuilt Debian SH4 image where hot library paths automatically use J64 acceleration on J64 hardware while still running on stock J32. Measurable performance lift on memcpy / crypto without ABI fork.

Note: this is upstream Debian/gcc/glibc work, not bounded to a single board. Could be skipped if the platform never gains enough J64 traction to justify the investment.

---

## 10. Anticipated throughput at Phase 5

For tenant expectations at the public-service launch (single core, paravirt guest, no SIMD, no FPU acceleration), at ~80 MHz J32:

| Workload | Estimate |
|---|---|
| UDP iperf3 | 60–80 Mbit/s |
| TCP iperf3 | 40–60 Mbit/s |
| SSH bulk transfer | 5–15 Mbit/s (crypto-bound) |
| Interactive SSH | excellent (latency-dominated) |
| Small program compile | seconds–minutes depending on size |
| Linux kernel build on-board | not realistic; cross-compile off-board instead |

Phase 8 SIMD work roughly **doubles** TCP and **3–5×s** SSH throughput.

---

## 11. Open questions and decisions deferred

- **Verify j-core upstream state.** The LUT estimates assume the j-core repo hasn't moved significantly. Worth a `git log` and mailing-list review before Phase 2 lands. Any new FPU work upstream would shift Phase 7 sizing.
- **ECP5-6 fmax of the dual-issue OoO J32.** Conservative estimate is 50–65 MHz; the actual number depends heavily on whether the wakeup CAM ends up in LUT logic (longer paths) or BRAM-backed (shorter, lookup-time-dominated). Empirically validate by Phase 6 midpoint.
- **OoO microarchitecture spec.** Write `10-ooo-design-spec.md` before implementation: issue rules, retire ordering, LSQ disambiguation strategy, memory ordering guarantees, hypervisor-visibility (none). Blocks Phase 6.
- **OoO trace cache / uop cache decision.** Adds BRAM cost but amortizes decode; might be worth it for tight loops. Decide during Phase 6 design.
- **Bitstream reflash brick rate.** Estimated 5% on remote reflash. Validate with a torture test in Phase 1; if higher than expected, implement the watchdog-revert-to-golden mechanism before Phase 5 public launch.
- **Tenant Ethernet gateway MikroTik model.** CRS326 (24 GbE, ~$200), RB5009 (ARM64, ~$250), or hEX S (5 GbE, ~$60) depending on planned fleet size. For ≤4 boards: hEX S. Decide before ordering hardware for Phase 0.
- **Management MikroTik model.** Default recommendation: hAP ax3 (~$120, WiFi 6 + container support in one box). Confirm before Phase 0.
- **ISP uplink port count.** Both MikroTiks need WAN access. Verify the ISP modem/ONT has ≥2 LAN ports, or add a $20 dumb switch upstream.
- **Tailscale vs Headscale.** Tailscale's free tier (≤3 users, ≤100 devices) covers our needs comfortably; Headscale is the self-hosted option if we want zero third-party dependency in the management plane. Tailscale default for Phase 0; revisit if scope grows.
- **Cloudflare Tunnel vs CF proxy mode for HTTPS.** Tunnel preferred (no inbound port 443 needed); proxy mode is the fallback if Tunnel ever proves operationally awkward. Decide at Phase 4.7.
- **GitHub OAuth app registration.** Need to register the OAuth app, decide scopes (`read:user` should be sufficient — we read public keys via the unauthenticated `<user>.keys` endpoint anyway), set callback URL, plan rate-limit handling. Blocks Phase 5.
- **GitHub account quality bar.** Need to define the heuristic for rejecting throwaway accounts: minimum age, minimum activity, minimum number of public events. Tunable per abuse experience. Initial cut: account age >30 days, at least one public commit or repo.
- **Debian SH4 archive currency.** Debian Ports `sh4` is maintained but lags main. Verify base packages we need are recent enough before Phase 2 (gcc, glibc, openssh, the OTel collector toolchain). If a package is too old, we either backport or wait.
- **Differential test corpus seeding.** Need explicit list of starter tests: glibc test-suite cross-compiled, kernel selftests, gcc test-suite, LLVM test-suite, CSmith/Yarpgen fuzz output. Curate before Phase 5.5.
- **Floating-point divergence tolerance bands.** When Phase 7 FPU lands, QEMU softfloat vs hardware FPU will differ in low bits of denormals and some transcendentals. Decide the tolerance threshold before Phase 5.5 normalization layer is finalized — too strict triggers false-positive alerts, too loose hides real bugs.
- **Pre-installed package set in the tenant image.** Needs explicit list since there's no runtime `apt install`. Initial cut: build tools (gcc, make, git, gdb), interpreters (python3, perl), editors (vim, nano), networking (curl, wget, openssh-client), and a SH4 assembly playground. Iterate based on user feedback once Phase 5 ships.
- **MCP server hosting model.** Run on the VPS (HTTP MCP, shared audit logs, easier multi-admin) vs on each dev laptop (stdio MCP, credential-local). I lean toward VPS-hosted with the MCP server bound to Tailscale interface; decide before Phase 2.5.
- **VPS storage retention cliff.** 75 GB NVMe holds ~75 days of full telemetry at our estimated rate. Monitor early; if retention is a problem, either bump to VPS-2 (€8/mo, more disk) or set up tiered retention in ClickHouse (full traces 7–14 days, aggregates 90+ days).
- **Numato Mimas V2 vs second ULX3S as upstream reference (Phase 0.7).** Numato is canonical and cheap ($50) but requires Xilinx ISE legacy toolchain; a second ULX3S ($130) uses our existing open-source toolchain. Personal preference call; pick whichever fits the team's tolerance for legacy tooling.
- **Dreamcast acquisition window (Phase 5.7).** The HIT-0400 BBA is the supply-chain pain point and prices vary. Watch eBay / Yahoo Auctions Japan; acquire during a price dip rather than urgently. Until BBA arrives, Phase 5.7 can run in serial-cable-only mode for early bring-up.
- **Dreamcast Linux distro choice.** LinuxDC, dreamcast.linux-mips.org branch, or a custom buildroot — pick the one whose toolchain matches our Debian SH4 closely enough that diff-test binaries built once can run on both. Decide before Phase 5.7.
- **J64 demand validation.** Phase 8 is currently deferred behind the entire SH4 excellence track. Worth revisiting after Phase 7.5 ships: is there actual tenant demand for J64, or has the SH4 path absorbed the interest? Decide whether to invest in J64 work based on observed usage.
- **Power-tenant tier with bitstream upload.** Could be a Phase 9. Requires bitstream signing infrastructure and a sandboxed FPGA reconfig path that can't brick the ESP32's recovery channel.
- **OoO J64 research target.** Explicitly out of scope for the 85F. If ever pursued, would require a separate FPGA platform (ECP6 / Nexus / Artix Ultrascale+ / similar). Deferred indefinitely; not blocking anything in this plan.

---

## 12. References

- Phase 1 MMU spec: `01-design-spec.md`, `02-hardware-spec.md`, `03-linux-spec.md`
- Phase 2 IOMMU spec: `04-iommu-design-spec.md`, `05-iommu-hardware-spec.md`, `06-iommu-linux-spec.md`
- Phase 3 hypervisor spec: `07-hypervisor-design-spec.md`, `08-hypervisor-hardware-spec.md`, `09-hypervisor-linux-spec.md`
- OoO microarchitecture spec (to be written): `10-ooo-design-spec.md` — see Phase 6 for content scope
- J-core repo: `github.com/j-core/jcore-cpu`, `github.com/j-core/jcore-soc`
- J-core roadmap: `j-core.org/roadmap.html`
- OpenSPARC T1 Hypervisor API spec (primary virtualization reference)
- ULX3S documentation: `github.com/emard/ulx3s`
- Numato Mimas V2 product page: `numato.com/product/mimas-v2-spartan-6-fpga-development-board-with-ddr-sdram`
- j-core stock J2 bitstream + uClinux downloads: `j-core.org`, `0pf.org/community.html`
- LinuxDC project (Linux on Dreamcast): `linuxdc.org`, `dreamcast.linux-mips.org` (alternative branch)
- Dreamcast Broadband Adapter (HIT-0400) docs: community wiki at `dreamcastwiki.org`
- MikroTik RouterOS WireGuard: `help.mikrotik.com/docs/display/ROS/WireGuard`
- Tailscale on MikroTik (container, subnet router): `github.com/acunet/tailscale-mikrotik`, `github.com/wojtekerbetowski/tailscale-mikrotik`
- Tailscale ACL syntax: `tailscale.com/kb/1018/acls`
- Headscale (self-hosted Tailscale control plane): `github.com/juanfont/headscale`
- sshpiperd (the username-routing SSH reverse proxy): `github.com/tg123/sshpiper`
- CrowdSec (modern fail2ban with shared threat feed): `crowdsec.net`
- Cloudflare Tunnel: `developers.cloudflare.com/cloudflare-one/connections/connect-networks/`
- OVH VPS: `ovhcloud.com/en/vps/`
- GitHub user public keys endpoint: `https://github.com/<user>.keys` (unauthenticated, plain text)
- GitHub OAuth scopes: `docs.github.com/en/developers/apps/building-oauth-apps/scopes-for-oauth-apps`
- Debian Ports sh4: `ports.debian.org/sh4`
- erofs documentation: `docs.kernel.org/filesystems/erofs.html`
- SigNoz documentation: `signoz.io/docs/`
- Model Context Protocol specification: `modelcontextprotocol.io`
- OpenTelemetry SH cross-compilation: TBD (likely Go OTel collector with TinyGo or stripped C++ build)
