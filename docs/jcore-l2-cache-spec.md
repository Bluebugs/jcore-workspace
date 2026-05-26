# J32OOO L2 Unified Cache — Implementation Specification

**Status:** Draft v0.1
**Scope:** Unified L2 cache controller for the J32OOO core. Sits between the L1-I/L1-D caches and the main memory interface. Parametrizable size, associativity, line size, and bank count; baseline configuration sized for ULX3S 85F (Lattice ECP5).
**Companion to:** `jcore-ooo-spec.md` v0.2.1 (J32OOO microarchitecture spec).

---

## 1. Scope and Relationship to J32OOO

The J32OOO microarchitecture spec (§11.3) defines the L2's externally-visible properties: 128 KB / 8-way set-associative / 32-byte lines / write-back / pseudo-LRU / inclusive of L1 / 6–8 cycle hit latency. This document specifies the **implementation**: state machine, banking, tag and data array organization, miss handling, BRAM mapping, and VHDL entity interface.

The L2 is built on top of the existing J-core memory-clock-layer infrastructure (`cache/dcache_mcl.vhm`) for SDRAM access. The CPU clock domain stops at the L2; the L2 controller is responsible for synchronizing with the slower SDRAM clock domain via the existing clock-domain crossing mechanism.

The dcache lock state machine (`cache/dcache_ccl.vhm` — `RLOCK1`, `RLOCK2`, `WUNCA1`, `WUNCA2`, `NEGLCK`) is preserved unchanged at the L1-D. Locked accesses bypass the L2 entirely and go directly through the existing memory-clock layer to SDRAM, preserving SMP atomicity guarantees.

---

## 2. Functional Summary

The L2 is a **unified, inclusive, write-back, banked, non-blocking** cache:

- **Unified**: serves both L1-I (read-only) and L1-D (read/write-through). Single tag and data array shared.
- **Inclusive of L1**: every line cached in L1-I or L1-D is also present in L2. Simplifies coherence — L2 evictions force corresponding L1 invalidations.
- **Write-back**: dirty lines stay in L2 until evicted; only writebacks go to SDRAM.
- **Banked**: 4 banks indexed by address bits, allowing parallel servicing of non-conflicting requests.
- **Non-blocking**: up to 4 outstanding misses via Miss Status Holding Registers (MSHRs); subsequent misses to in-flight addresses merge.
- **Pseudo-LRU replacement**: tree-LRU per set; cheap to update.
- **Locked accesses bypass**: locked loads/stores (CAS.L's RLOCK/WUNCA) skip L2 and access SDRAM directly.

Pre-2006 prior art:

| Mechanism                       | Citation                                              |
| ------------------------------- | ----------------------------------------------------- |
| Non-blocking cache with MSHRs   | Kroft 1981 "Lockup-Free Instruction Fetch/Prefetch Cache Organization" |
| Set-associative on-die L2       | DEC Alpha 21164 1995 (96 KB / 3-way)                  |
| Backside dedicated L2           | PowerPC 750 1997                                      |
| Banked cache for port-conflict reduction | Sohi & Franklin 1991                         |
| Pseudo-LRU (tree-LRU)           | Intel P6 1995; widely documented prior art            |
| Inclusive multilevel cache      | Baer & Wang 1988                                      |
| Bus-lock atomicity bypass       | IBM S/360 1964; preserved in current J-core CAS.L     |

---

## 3. Configuration Parameters

The L2 controller is a parametrized VHDL entity. The baseline configuration matches the J32OOO spec; smaller variants are supported for staged bring-up.

| Generic            | Type    | Baseline | Range                          | Notes                                  |
| ------------------ | ------- | --------:| ------------------------------ | -------------------------------------- |
| `L2_SIZE_KB`       | integer |     128  | 32, 64, 128, 256               | Total L2 capacity                      |
| `L2_WAYS`          | integer |       8  | 2, 4, 8, 16                    | Associativity                          |
| `L2_LINE_BYTES`    | integer |      32  | 32, 64                         | Line size                              |
| `NUM_BANKS`        | integer |       4  | 1, 2, 4, 8                     | Banking factor                         |
| `NUM_MSHRS`        | integer |       4  | 2, 4, 8                        | Outstanding miss capacity              |
| `WAY_SELECT_PIPE`  | boolean |   false  | true (timing escape hatch)      | Adds 1 cycle to L2 hit latency         |
| `ADDR_WIDTH`       | integer |      32  | fixed                          | Physical address width                 |

Derived quantities for the baseline:

```
NUM_SETS         = L2_SIZE_KB * 1024 / (L2_WAYS * L2_LINE_BYTES) = 512
SETS_PER_BANK    = NUM_SETS / NUM_BANKS = 128
OFFSET_BITS      = log2(L2_LINE_BYTES) = 5
BANK_BITS        = log2(NUM_BANKS) = 2
INDEX_BITS       = log2(SETS_PER_BANK) = 7
TAG_BITS         = ADDR_WIDTH - INDEX_BITS - BANK_BITS - OFFSET_BITS = 18
LINE_WORDS       = L2_LINE_BYTES / 4 = 8 (32-bit words)
```

**Staged bring-up recommendation**: start with `L2_SIZE_KB=64, L2_WAYS=4, NUM_BANKS=2` for first integration. This reduces BRAM use from ~69 to ~25 EBRs and simplifies arbitration. Once verified end-to-end on FPGA, switch to baseline.

---

## 4. Address Layout

Physical address (32 bits) is split as:

```
  31                       14 13  12  11      5  4         0
 +---------------------------+------+----------+-----------+
 |          TAG (18)         |BANK 2| INDEX 7  | OFFSET 5  |
 +---------------------------+------+----------+-----------+
```

The bank bits are placed below the index bits so that consecutive cache lines spread across all banks (improving parallel-access utilization). Consecutive accesses with stride ≤ line size go to different banks roughly half the time.

Alternative bank-bit placement (above tag, below tag, interleaved within index) is supported by the generic but the baseline layout above gives the best parallelism for typical access patterns.

---

## 5. Top-Level Block Diagram

```
                         ┌──────────────────────┐
              L1-I  ───→ │                      │
              L1-D  ←──→ │  L2 Arbiter +        │
                         │  Bank Steering       │
                         │                      │
                         └──────┬───────────────┘
                                │
              ┌─────────────────┼─────────────────┬─────────────────┐
              ▼                 ▼                 ▼                 ▼
        ┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐
        │  Bank 0  │      │  Bank 1  │      │  Bank 2  │      │  Bank 3  │
        │          │      │          │      │          │      │          │
        │  Tag     │      │  Tag     │      │  Tag     │      │  Tag     │
        │  Data    │      │  Data    │      │  Data    │      │  Data    │
        │  pLRU    │      │  pLRU    │      │  pLRU    │      │  pLRU    │
        │  State   │      │  State   │      │  State   │      │  State   │
        └────┬─────┘      └────┬─────┘      └────┬─────┘      └────┬─────┘
             │                 │                 │                 │
             └─────────────────┼─────────────────┼─────────────────┘
                               │                 │
                               ▼                 ▼
                         ┌──────────┐      ┌──────────┐
                         │  MSHR    │      │ Writeback│
                         │  Pool    │      │  Queue   │
                         └─────┬────┘      └────┬─────┘
                               │                 │
                               └────────┬────────┘
                                        ▼
                              ┌────────────────────┐
                              │  Memory-Clock      │
                              │  Layer (existing   │
                              │  dcache_mcl.vhm)   │
                              └─────────┬──────────┘
                                        ▼
                                    SDRAM
```

The L2 arbiter accepts requests from L1-I and L1-D, steers each request to the appropriate bank based on `address[11:10]`, and tracks in-flight requests. Banks operate independently; same-bank conflicts queue at the bank's input arbiter.

Miss handling and writebacks merge at the memory-clock-layer interface.

---

## 6. Tag Array

### 6.1 Per-line tag format

Each tag entry holds:

| Field      | Bits | Description                                                    |
| ---------- | ---: | -------------------------------------------------------------- |
| `tag`      |   18 | Upper PA bits (PA[31:14])                                      |
| `valid`    |    1 | Line contains valid data                                       |
| `dirty`    |    1 | Line has been modified since fill (write-through from L1-D)    |
| `in_l1i`   |    1 | This line is also present in L1-I (inclusion tracking)         |
| `in_l1d`   |    1 | This line is also present in L1-D                              |
| **Total**  | **22** | per way, per set                                            |

The `in_l1i`/`in_l1d` bits are inclusion-tracking flags. When the L2 evicts a line, it must invalidate that line in any L1 that holds it. Without these bits, every eviction would have to send invalidations to both L1s; with them, evictions only invalidate where needed.

### 6.2 Per-set state

| Field           | Bits | Description                                          |
| --------------- | ---: | ---------------------------------------------------- |
| `plru_state`    |    7 | Tree-LRU state for 8-way; 2^3 − 1 = 7 bits           |
| **Total**       | **7** | per set                                             |

For 4-way (alternative config), pLRU needs 3 bits per set.

### 6.3 Tag array storage

Per bank (baseline 128 sets, 8 ways):

- Tag width per set: 8 ways × 22 bits = 176 bits
- Sets per bank: 128
- Total per bank: 22,528 bits ≈ 1.2 EBRs

Plus the per-set pLRU state: 128 × 7 = 896 bits — small enough to use distributed LUT-RAM.

Per-bank tag storage: 1 EBR for tags + distributed RAM for pLRU.
Four banks: 4 EBRs total for tag storage.

In practice, EBRs are organized as 36×512 or 18×1024 or 9×2048, and tag width per access is 22 bits per way × 8 ways = 176 bits — which is wider than any single EBR port. Tags are split across multiple narrow EBRs read in parallel. Realistic mapping: 4–6 EBRs per bank for tags, **16–24 EBRs total** for tag storage across 4 banks. Synthesis details may revise this.

---

## 7. Data Array

### 7.1 Organization

Per bank (32 KB):

- 128 sets × 8 ways × 32-byte line = 32 KB per bank
- Each line is 8 × 32-bit words
- Each way of each set is a separate addressable storage region

For ECP5 EBRs (18 Kbit each):

- 32 KB per bank = 256 Kbit per bank
- 256 / 18 ≈ 14.3 → 15 EBRs per bank for data
- Four banks: **60 EBRs total** for data storage

### 7.2 Access width

Each L2 hit returns a full line (32 bytes) to the requesting L1. The L2 data array is read 32 bytes at a time. On ECP5 with 18-bit-wide EBR ports, a 256-bit-wide line read requires reading from 8 EBRs in parallel (2 EBRs per quarter-line).

For writes (write-through from L1-D), the data array supports per-byte enables. A 32-bit word write affects 4 byte lanes; the rest of the line is untouched.

### 7.3 Way selection

Tag compare runs in parallel with data read. The matching way's data is muxed at the end of the access cycle. If `WAY_SELECT_PIPE=true`, the data mux is moved to the next cycle (escape hatch for timing closure).

---

## 8. Banking and Arbitration

### 8.1 Bank steering

Each incoming request carries an address. Bits `address[11:10]` select the bank (for 4-bank config). Requests to different banks proceed in parallel; requests to the same bank queue at the bank arbiter.

### 8.2 Arbiter priority

The L2 arbiter prioritizes requests in this order:

1. **SDRAM fill responses** (line being installed in data array): highest priority, must complete to free MSHR.
2. **L1-D writeback (write-through)**: must complete or be queued to avoid stalling L1-D writes.
3. **L1-D read miss**: critical for OOO load latency.
4. **L1-I read miss**: less latency-critical (front-end can absorb stalls).
5. **Prefetch fills** (from L1-D stride prefetcher): lowest priority, can be dropped under contention.

When multiple requests target the same bank in the same cycle, the arbiter picks the highest-priority and queues the rest for the next cycle.

### 8.3 Conflict frequency

For random access patterns, 4-bank conflict probability is ~25% per pair of requests. Realistic workloads (sequential bulk crypto, instruction fetch) have lower conflict rates due to bank-bit interleaving in the address layout.

---

## 9. Replacement Policy

### 9.1 Tree pseudo-LRU for 8-way

Standard tree-LRU uses 7 bits to encode the binary-tree decision state for 8 ways:

```
                  [b6]
                 /      \
              [b5]       [b4]
              /  \       /   \
           [b3] [b2]  [b1]  [b0]
           / \  / \   / \   / \
          0   1 2   3 4   5 6   7    ← way indices
```

Each branch bit (`b0`..`b6`) points to the LRU half of its subtree. On access to a way, all bits on the path from root to that way are flipped to point *away* from the accessed way (marking the other half as LRU).

On replacement, the tree is walked from the root following the bit values, arriving at the LRU way.

### 9.2 Update logic

On every L2 hit or fill, the pLRU state for that set is updated. The update is a small piece of combinational logic that XORs the pLRU bits with a precomputed update mask derived from the accessed way.

Update mask for accessing way W is precomputed at synthesis as a 7-bit pattern. Lookup is a 3-bit-input combinational decoder.

### 9.3 Initialization

At reset, all pLRU state is zeroed. The first 8 accesses to any set will fill different ways (no immediate evictions) regardless of initial state; pLRU only matters once all ways are populated.

---

## 10. Write Policy and Dirty Bit Handling

### 10.1 Write-through from L1-D

L1-D performs writes by sending the new data plus byte enables to L2. The L2 looks up the line in its tag array:

- **Hit**: update the affected bytes in the data array; set `dirty=1`; update pLRU.
- **Miss**: allocate a line (write-allocate) via standard miss flow; install the line from SDRAM; merge the incoming write; mark `dirty=1`.

### 10.2 Eviction of dirty lines

When the L2 must evict a line (e.g. miss requires installing a new line into a full set), the selected pLRU victim is examined:

- **Victim is clean** (`dirty=0`): silently discard from tag array. Send invalidation to L1s if `in_l1i` or `in_l1d` is set. Free the way slot.
- **Victim is dirty** (`dirty=1`): place the line in the writeback queue (see §11.4) for asynchronous write to SDRAM. Send invalidation to L1s if applicable. Free the way slot.

The writeback queue allows eviction to proceed without waiting for SDRAM — the new line fill can start immediately on the freed slot.

### 10.3 L1-I never writes

L1-I is read-only. L2 never receives writes from L1-I. Lines fetched for L1-I miss are installed clean. If a line is later also read by L1-D and not modified, it stays clean; if modified, it becomes dirty.

### 10.4 Inclusion invariant maintenance

When the L2 invalidates a line that is also in an L1, it must guarantee the L1 doesn't continue to serve that line. The L1-I and L1-D invalidation interfaces (§13) require this guarantee. The L2 sends an invalidation message and waits for ack before completing the eviction sequence.

---

## 11. State Machine

The L2 controller per bank is a state machine with the following states:

```
                ┌──────┐
                │ IDLE │←──────────────────┐
                └──┬───┘                   │
                   │ request                │
                   ▼                        │
              ┌──────────┐                  │
              │ TAG_READ │                  │
              └────┬─────┘                  │
                   │                        │
                   ▼                        │
          ┌─────────────────┐               │
          │ TAG_COMPARE     │               │
          │ + DATA_READ     │               │
          └────┬─────┬──────┘               │
               │     │                      │
        hit    │     │   miss               │
               ▼     ▼                      │
     ┌────────────┐  ┌─────────────┐        │
     │ DATA_FWD   │  │ ALLOC_WAY   │        │
     │ (1 cycle)  │  └──────┬──────┘        │
     └─────┬──────┘         │               │
           │                ▼               │
           │      ┌──────────────────┐      │
           │      │ EVICT (if dirty) │      │
           │      └──────┬───────────┘      │
           │             │                  │
           │             ▼                  │
           │      ┌──────────────────┐      │
           │      │ MSHR_ALLOC       │      │
           │      └──────┬───────────┘      │
           │             │                  │
           │             ▼                  │
           │      ┌──────────────────┐      │
           │      │ AWAIT_FILL       │      │
           │      └──────┬───────────┘      │
           │             │                  │
           │             ▼                  │
           │      ┌──────────────────┐      │
           │      │ INSTALL_FILL +   │      │
           │      │ DATA_FWD         │      │
           │      └──────┬───────────┘      │
           │             │                  │
           └─────────────┴──────────────────┘
```

State descriptions:

- **IDLE**: wait for incoming request from arbiter.
- **TAG_READ**: read tag array for the addressed set. 1 cycle.
- **TAG_COMPARE + DATA_READ**: compare 8 tags in parallel, kick off data read for all ways (or just the matching way if narrowed). 1 cycle.
- **DATA_FWD**: forward matching way's data to requesting L1; update pLRU. 1 cycle.
- **ALLOC_WAY**: select pLRU victim. 1 cycle (combinational, overlaps).
- **EVICT**: if victim is dirty, enqueue writeback to SDRAM; if any L1 has the line, send invalidation. 1–2 cycles.
- **MSHR_ALLOC**: allocate MSHR for this miss; issue read to SDRAM via mcl. 1 cycle.
- **AWAIT_FILL**: wait for SDRAM response (8–20 cycles for SDRAM access).
- **INSTALL_FILL + DATA_FWD**: write line into data array, update tag, forward data to requesting L1, free MSHR. 1 cycle.

Hit latency from request to L1 receiving data: 3 cycles (TAG_READ, TAG_COMPARE+DATA_READ, DATA_FWD).
Miss latency: 3 cycles + SDRAM round-trip (typically 10–20 cycles) + 1 cycle install = ~14–24 cycles end-to-end.

When `WAY_SELECT_PIPE=true`, an extra DATA_FWD pipeline stage adds 1 cycle to hit latency.

---

## 12. Miss Status Holding Registers (MSHRs)

### 12.1 Purpose

MSHRs let the L2 handle multiple outstanding misses without blocking. Per Kroft 1981, each MSHR represents one in-flight miss and tracks the requesters waiting on it.

### 12.2 MSHR fields

Each MSHR has:

| Field            | Bits     | Description                                       |
| ---------------- | -------: | ------------------------------------------------- |
| `valid`          |        1 | This MSHR is in use                               |
| `addr`           |       27 | Address being fetched (line-aligned)              |
| `bank`           |        2 | Which bank initiated this miss                    |
| `way_to_install` |        3 | Which way to fill on response                     |
| `dirty_to_evict` |        1 | Whether the victim was dirty (writeback pending)  |
| `requestors`     |        N | Bit vector: one bit per possible waiter           |
| `requestor_data` |  several |  per-requestor info: thread ID, L1 source, etc.   |

The requestors vector handles **MSHR coalescing**: if a new miss arrives for an address already in an MSHR, the new requestor is added to the vector rather than allocating a new MSHR or issuing another SDRAM read. When the SDRAM response arrives, all coalesced requestors receive the line.

### 12.3 MSHR pool

4 MSHRs total in the baseline. Shared across banks (any bank can use any MSHR). If all MSHRs are full, the L2 stalls accepting new misses; hits continue to be served from L2 data.

For SMT with two threads and stride prefetching active, 4 MSHRs is comfortable. Lower counts (2) work but cause more stalls under heavy miss bursts. Higher counts (8) help marginally.

### 12.4 Subentry handling

Within an MSHR, each requestor records what it actually wants (full line vs. partial word). Most J32OOO accesses are full line fills (L1 miss). The stride prefetcher also requests full lines. Partial-line requests (rare, for memory-mapped IO) bypass the L2 entirely via the locked-access path.

---

## 13. Interfaces

### 13.1 L1-I read interface

```vhdl
type l2_l1i_req_t is record
    req_valid : std_logic;
    addr      : std_logic_vector(31 downto 0);
end record;

type l2_l1i_resp_t is record
    resp_valid : std_logic;
    line_data  : std_logic_vector(255 downto 0);  -- 32 bytes
    error      : std_logic;
end record;
```

L1-I issues a line read by asserting `req_valid` with a line-aligned address. The L2 responds asynchronously (typically several cycles later for hit, more for miss) with `resp_valid` and the line data.

### 13.2 L1-D read/write interface

```vhdl
type l2_l1d_req_t is record
    req_valid    : std_logic;
    addr         : std_logic_vector(31 downto 0);
    is_write     : std_logic;
    write_data   : std_logic_vector(31 downto 0);  -- single 32-bit word for write-through
    write_be     : std_logic_vector(3 downto 0);   -- byte enables
    locked       : std_logic;                       -- if asserted, bypass L2
end record;

type l2_l1d_resp_t is record
    resp_valid : std_logic;
    line_data  : std_logic_vector(255 downto 0);   -- valid on read
    write_ack  : std_logic;                         -- write completed
    error      : std_logic;
end record;
```

If `locked='1'`, the L2 forwards the request directly to the memory-clock layer (bypass mode); response comes back through the same bypass path. This preserves CAS.L atomicity guarantees.

For writes, the L2 returns `write_ack` once the data has been merged into the L2 data array (or installed via miss). The write-through is non-blocking from L1-D's perspective in steady state.

### 13.3 L1 invalidation interface

```vhdl
type l2_inval_t is record
    inval_valid : std_logic;
    addr        : std_logic_vector(31 downto 0);  -- line address to invalidate
    target_l1i  : std_logic;
    target_l1d  : std_logic;
end record;

type l2_inval_ack_t is record
    ack_valid : std_logic;
end record;
```

When the L2 evicts a line that is also in L1s (per `in_l1i`/`in_l1d` bits), it asserts `inval_valid` to the target L1(s). The L1 must remove the line from its tag array and respond with `ack_valid` before the L2 completes the eviction. Without this synchronization, the L1 could serve stale data.

### 13.4 Memory-clock-layer interface

```vhdl
type l2_mcl_req_t is record
    req_valid : std_logic;
    is_write  : std_logic;
    addr      : std_logic_vector(31 downto 0);
    data      : std_logic_vector(255 downto 0);  -- on write
end record;

type l2_mcl_resp_t is record
    resp_valid : std_logic;
    data       : std_logic_vector(255 downto 0);
    error      : std_logic;
end record;
```

This is the existing `dcache_mcl.vhm` interface, slightly widened to 256-bit line size. The mcl handles SDRAM access, clock-domain crossing, and bus arbitration with other masters.

### 13.5 Control/CSR interface

For software control and observability, the L2 exposes memory-mapped registers (privileged access):

| Register     | Width | Purpose                                          |
| ------------ | ----: | ------------------------------------------------ |
| `L2_CTRL`    |    32 | Enable, flush-all, freeze (for debug)            |
| `L2_STATUS`  |    32 | Busy, MSHR-full, writeback-pending flags         |
| `L2_FLUSH_ADDR` |  32 | Address for targeted-line flush                  |
| `L2_FLUSH_CMD` |   32 | Flush command (clean, invalidate, clean-invalidate) |
| `L2_HIT_CNT` |    64 | Counter: L2 hits (read by PMU)                   |
| `L2_MISS_CNT`|    64 | Counter: L2 misses                               |
| `L2_WB_CNT`  |    64 | Counter: writebacks to SDRAM                     |
| `L2_INVAL_CNT`|   64 | Counter: L1 invalidations sent                   |

The counter registers integrate with the J32OOO PMU (jcore-ooo-spec.md §12); PMU event 0x08 `L2_ACCESSES` reads `L2_HIT_CNT + L2_MISS_CNT`, event 0x09 `L2_MISSES` reads `L2_MISS_CNT`.

---

## 14. Locked Accesses (Bypass)

When `locked='1'` on an incoming L1-D request, the L2 does not look up its tag array. Instead, the request is forwarded directly to the memory-clock-layer interface with the lock signal asserted.

This preserves the behavior of the existing dcache state machine: locked reads and writes are uncached, going straight to the bus, where the bus arbiter enforces atomicity.

L1-D requests with `locked='1'` are always 32-bit-word accesses (not full-line). The L2 forwards the partial request through to the mcl, which handles the locked access correctly via its existing `RLOCK1`/`RLOCK2`/`WUNCA1`/`WUNCA2`/`NEGLCK` state machine.

**Important interaction with inclusion invariant**: a locked write modifies SDRAM but does not modify the L2 (because it bypasses). If the line is currently in L2 with a cached copy, the L2's copy is now stale. The L1-D, on completion of the locked access, must invalidate any cached L2 line for that address. This is done via an explicit `L2_FLUSH_CMD` with the locked address, sent automatically by the L1-D after each locked write.

For CAS.L specifically, the sequence is:

1. uop2 (locked load): bypass L2, fetch from SDRAM, return data to L1-D. L2 is not consulted; any stale L2 copy is acceptable (will be cleaned up at step 3).
2. uop3 (conditional store, T=1): bypass L2, write to SDRAM. After write completes, L1-D sends `L2_FLUSH_CMD` with `LINE_INVALIDATE` for that line. L2 invalidates the line if present.
3. uop3 (conditional store, T=0): no SDRAM write, no L2 invalidation needed.

This adds maybe 2 cycles to CAS.L tail latency for the L2 cleanup, but is critical for correctness.

---

## 15. Coherence Model

The L2 supports the J32OOO SMP model as specified in jcore-ooo-spec.md §14: **single or dual-core SMP with bus-lock-based atomicity, no MESI snooping**.

For dual-core, each core has its own L2 (no shared L2 in this revision). Coherence between cores is software-managed:

- Atomic operations (CAS.L) bypass all caches and synchronize at the bus.
- Non-atomic shared-memory accesses are not guaranteed to be coherent. Software must use atomics or explicit cache management.

A shared L2 for dual-core SMP could be added in a future revision but would require:
- True multi-port L2 (2× the BRAM banking)
- An L1-L2 protocol that handles cross-core invalidations
- Either MESI-style state per L1 line, or directory tracking at L2

This is deferred.

---

## 16. Performance Characteristics

### 16.1 Latency

| Path                                        | Cycles    |
| ------------------------------------------- | --------: |
| L2 hit (read, full line)                    | 3 (4 with `WAY_SELECT_PIPE`)  |
| L2 hit (write-through merge)                | 3         |
| L2 miss → SDRAM hit → fill                  | 14–24     |
| L2 miss with dirty eviction                 | 16–28     |
| Locked access (bypass)                      | matches existing dcache locked path |
| L1 invalidation latency                     | 2–4       |

### 16.2 Throughput

- 4 banks operating in parallel: peak 4 requests per cycle on independent banks
- Realistic throughput under typical workload mix (instruction stream + data stream + occasional writes): ~2 requests/cycle sustained
- SDRAM line fill: ~1 line per 8 SDRAM-clock cycles = ~1 line per 12 CPU cycles at 90 MHz CPU + 62.5 MHz SDRAM

### 16.3 Capacity working-set behavior

Approximate L2 hit rate by working set size:

| Working set | Hit rate (est.) |
| ----------- | --------------: |
| < 32 KB     |          ~99%   |
| 64 KB       |          ~97%   |
| 128 KB      |          ~90%   |
| 256 KB      |          ~70%   |
| 512 KB      |          ~45%   |
| 1 MB        |          ~25%   |
| >> 1 MB     |    streaming    |

These are first-order estimates based on typical workload behavior (mix of locality and capacity misses). Actual numbers depend on access pattern.

---

## 17. BRAM Mapping for ECP5

### 17.1 EBR allocation summary

| Component                            | EBRs per bank | × 4 banks | Total |
| ------------------------------------ | -------------:| ---------:| ----: |
| Data array (32 KB / 8-way)           |            15 |        60 |    60 |
| Tag array (128 sets × 8 ways × 22b)  |             2 |         8 |     8 |
| pLRU state                           |  (distributed) |   distributed | 0 |
| MSHR storage                         |  (shared, distributed) |  | 1 |
| Writeback queue                      |  (shared, distributed) |  | 0 |
| **Total**                            |               |           | **~69** |

Plus possible additional 1–2 EBRs for buffering at the L1/L2 and L2/mcl interfaces.

On ULX3S 85F (208 EBRs total), the L2 uses ~33% of available BRAM. Combined with L1-I (~18 EBRs) and L1-D (~18 EBRs), the full cache hierarchy uses **~50% of ULX3S BRAMs** (105 of 208).

### 17.2 Synthesis considerations

- ECP5 EBRs support up to 36-bit-wide ports, but only 1 read and 1 write port (pseudo-dual-port). True dual-port requires special configuration with reduced depth/width.
- The L2 data arrays need: 1 read port for L1 read service, 1 read port for writeback eviction, 1 write port for fill, 1 write port for L1-D write-through. That's 2 read + 2 write = 4 ports.
- This is handled by either banking (different operations to different banks in same cycle) or by time-multiplexing within a bank (typical for FPGA caches).
- Recommend: time-multiplex within each bank, with a 1-cycle pipeline stage for arbitration.

### 17.3 Power estimate

ECP5-85F at 90 MHz: nominal core power ~250 mW. L2 cache contribution (EBR static + dynamic): estimated +30–50 mW, including data + tag arrays toggling. Negligible at FPGA scale; relevant for future ASIC.

---

## 18. VHDL Entity Skeleton

```vhdl
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.l2_pkg.all;

entity l2_cache is
    generic (
        L2_SIZE_KB      : integer := 128;
        L2_WAYS         : integer := 8;
        L2_LINE_BYTES   : integer := 32;
        NUM_BANKS       : integer := 4;
        NUM_MSHRS       : integer := 4;
        WAY_SELECT_PIPE : boolean := false;
        ADDR_WIDTH      : integer := 32
    );
    port (
        clk         : in  std_logic;  -- CPU clock (~90 MHz on ULX3S)
        rst         : in  std_logic;

        -- L1-I read interface
        l1i_req_i   : in  l2_l1i_req_t;
        l1i_resp_o  : out l2_l1i_resp_t;

        -- L1-D read/write interface
        l1d_req_i   : in  l2_l1d_req_t;
        l1d_resp_o  : out l2_l1d_resp_t;

        -- L1 invalidation interfaces
        inval_l1i_o : out l2_inval_t;
        inval_l1i_i : in  l2_inval_ack_t;
        inval_l1d_o : out l2_inval_t;
        inval_l1d_i : in  l2_inval_ack_t;

        -- Memory-clock-layer interface (to SDRAM)
        mcl_req_o   : out l2_mcl_req_t;
        mcl_resp_i  : in  l2_mcl_resp_t;

        -- Control/CSR interface (memory-mapped)
        csr_addr_i  : in  std_logic_vector(7 downto 0);
        csr_wdata_i : in  std_logic_vector(31 downto 0);
        csr_rdata_o : out std_logic_vector(31 downto 0);
        csr_wr_i    : in  std_logic;
        csr_rd_i    : in  std_logic;

        -- PMU event signals (1-cycle pulse per event)
        pmu_hit_o     : out std_logic;
        pmu_miss_o    : out std_logic;
        pmu_wb_o      : out std_logic;
        pmu_inval_o   : out std_logic
    );
end l2_cache;
```

Architecture is structured as:

```vhdl
architecture rtl of l2_cache is
    -- Bank instances (NUM_BANKS of them)
    component l2_bank is
        generic (...);
        port (...);
    end component;

    -- Arbiter for incoming requests
    signal arb_requests   : ...;
    signal arb_bank_sel   : ...;

    -- MSHR pool
    component mshr_pool is ...
    end component;

    -- Writeback queue
    component writeback_queue is ...
    end component;

    -- CSR block
    component l2_csr is ...
    end component;

begin
    arbiter_inst : process(...) ...
    
    bank_gen : for i in 0 to NUM_BANKS-1 generate
        bank_inst : l2_bank ...
    end generate;

    mshr_inst : mshr_pool ...
    wb_inst   : writeback_queue ...
    csr_inst  : l2_csr ...
end architecture;
```

Substantial submodules: `l2_bank`, `mshr_pool`, `writeback_queue`, `l2_arbiter`, `l2_csr`, `tree_plru` (combinational helper).

---

## 19. Verification Plan

### 19.1 Unit-level

- **Tag array**: random writes and reads; verify tag/valid/dirty/inclusion bits round-trip correctly.
- **Data array**: byte-enable writes verify partial updates; full-line reads and writes; multi-way independence.
- **pLRU**: write a sequence of accesses with known pattern; verify replacement order matches expected pLRU walk.
- **MSHR**: allocate, coalesce, free; verify multiple requestors receive same response; verify saturation behavior when pool is full.
- **Writeback queue**: enqueue dirty lines under contention; verify SDRAM writes happen in order.

### 19.2 Integration-level

- **L1-I hit/miss cycle**: instrumented L1-I issues line reads; verify L2 returns correct data and observed latency.
- **L1-D hit/miss/write cycle**: instrumented L1-D issues mixed read/write traffic; verify correct data and write-through propagation.
- **Inclusion enforcement**: cause L2 evictions and verify the L1s receive invalidations and stop serving the evicted lines.
- **Locked access bypass**: drive a CAS.L sequence; verify L2 is bypassed for the locked load and store, and that the L1-D's post-locked-write L2 invalidation fires.
- **Bank conflict**: drive simultaneous same-bank requests; verify queueing and eventual completion.
- **MSHR coalescing**: issue multiple misses to the same line; verify only one SDRAM read; verify all requestors receive the response.

### 19.3 System-level

- **Linux boot**: full Linux boot through to userspace shell. Verify no cache-coherence bugs cause kernel panics or data corruption.
- **CAS.L atomicity stress**: two threads CAS-spin on shared addresses for 10⁹ iterations; verify no torn updates.
- **L2 capacity sweep**: parametrize benchmark working-set size; verify hit-rate curve matches §16.3.
- **PMU validation**: read `L2_HIT_CNT`, `L2_MISS_CNT`, `L2_WB_CNT` after known workloads; verify counts match theoretical expectations.

### 19.4 Regression integration

The existing J-core verification corpus (`testrom/tests/*.s`, `tests/*.vhd`) runs against the L2-augmented system. CAS.L atomicity test at `testmov.s:580-635` is the critical regression — must pass with L2 enabled and disabled.

---

## 20. Open Issues and Future Work

1. **Shared L2 for dual-core SMP**: deferred. Requires multi-port L2 or banked-with-arbitration design plus cross-core invalidation protocol.
2. **L2 prefetcher**: an L2-level stride prefetcher (separate from the L1-D one) could improve bulk-streaming workloads. Defer.
3. **L2 capacity-aware allocation policy**: thrashing-aware replacement (Wong & Baer 2000, DIP variants) could improve hit rate on capacity-bound workloads. Defer.
4. **L2 way-prediction**: predict the matching way before tag compare to start data read earlier. ~5% power saving, marginal hit-latency improvement. Defer.
5. **Hardware-managed L2 flush on context switch**: software currently must flush L2 explicitly across address-space changes when MMU lands. Hardware-managed ASID-tagged L2 could remove this requirement; needs MMU spec alignment first.
6. **ECC for L2 data array**: relevant for ASIC reliability; not needed on FPGA. Defer.

---

## Appendix A: Glossary

- **EBR** — Embedded Block RAM (Lattice ECP5 terminology for BRAM).
- **MCL** — Memory-Clock Layer; the existing J-core SDRAM controller interface.
- **MSHR** — Miss Status Holding Register; Kroft 1981.
- **pLRU** — Pseudo-LRU (tree-LRU) replacement policy.
- **Way** — One associativity slot in a set-associative cache.
- **Set** — Group of ways sharing the same index.
- **Bank** — Independently-accessible cache partition.
- **Line** — Unit of allocation/transfer (32 bytes here).
- **Writeback** — Sending a dirty line back to lower memory on eviction.
- **Inclusion** — Invariant that L1 contents are a subset of L2 contents.

## Appendix B: Resource Cost Summary on ULX3S 85F

| Resource         | Count  | % of ULX3S 85F |
| ---------------- | -----: | -------------: |
| EBRs (18 Kb)     |    ~69 |           ~33% |
| LUT4 equivalents | ~3,300 |            ~4% |
| DSP slices       |      0 |             0% |
| FFs (registers)  | ~2,000 |            ~2% |
| Engineering effort | ~10 weeks | —          |
| Static power adder | ~30–50 mW | —          |
