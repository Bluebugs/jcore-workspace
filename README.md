# jcore-workspace

Design docs and roadmaps for new J-Core subsystems (MMU, IOMMU, hypervisor, L2 cache, FPU, SIMD, out-of-order, fine-grained multi-threading) and for the hobbyist-hosted ULX3S FPGA service that will run them.

## Where to start

- [`docs/glossary.md`](docs/glossary.md) — naming, product points, threading model, memory terms, **prior-art policy**.
- [`docs/jcore-ulx3s-service-plan.md`](docs/jcore-ulx3s-service-plan.md) — the overall platform plan.
- Subsystem specs live under `docs/{mmu,iommu,hypervisor,cache,fpu,simd,ooo,fgmt}/`.

## Scope

This repo is **design docs only**. Implementation lives in sibling repos: `jcore-cpu/` (J2 VHDL core), `jcore-soc/` (SoC integration), and others — see the glossary §8 for the full list.

The platform is **hobbyist-hosted at home**: a small fleet of ULX3S boards run J-Core bitstreams and expose an SH4 development service to remote tenants. The J-core does not develop itself — cross-compilation, RTL synthesis, and bitstream generation all happen on a separate x86 developer machine. See glossary §1.

## Prior-art policy

Every technology added to this project must be backed by published prior art predating 2006. This is a hard requirement. Each design doc carries a "Prior art" section citing pre-2006 sources. See glossary §2.
