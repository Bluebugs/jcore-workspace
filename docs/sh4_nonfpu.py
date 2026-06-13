#!/usr/bin/env python3
"""Extract SH-4 instructions that J2 lacks and that are not floating-point.

Reads an insns.json (the SH instruction database with per-ISA presence flags)
and writes sh4-nonfpu.json containing every instruction that is:

  * present in SH-4            (SH4 == true)
  * absent from J2            (J32 == false)   -- J32 is the J-core J2 flag
  * not a floating-point insn  (not in a "Floating-Point" group, and the
                                mnemonic does not start with 'f')

Usage:
    ./sh4_nonfpu.py [insns.json] [-o sh4-nonfpu.json]
"""
import argparse
import json
import sys


def is_floating_point(insn):
    """True if the instruction is floating-point (FPU)."""
    if "Floating-Point" in insn.get("group", ""):
        return True
    mnemonic = insn.get("format", "").split("\t")[0].strip().lower()
    return mnemonic.startswith("f")


def classify_tier(insn):
    """Tag an instruction by its role relative to the J-Core MMU/cache work.

    Tiers (see docs/mmu/hardware-spec.md §3.0 and docs/cache/l2-spec.md §17.5):
      mmu-required - load-bearing for the UltraSPARC-style software-loaded TLB
      cache        - operand-cache maintenance, rides with the cache/L2 milestone
      orthogonal   - SH-4 baggage unrelated to translation; defer or drop
    """
    fmt = insn.get("format", "")
    mnemonic = fmt.split("\t")[0].strip()

    if mnemonic in {"ocbi", "ocbp", "ocbwb", "pref", "movca.l"}:
        return "cache"
    if mnemonic == "ldtbl":  # LDTLB - the TLB-fill primitive
        return "mmu-required"
    if mnemonic in {"clrs", "sets"}:  # MAC saturation S-bit, not translation
        return "orthogonal"
    if mnemonic in {"ldc", "ldc.l", "stc", "stc.l"}:
        if "SSR" in fmt or "SPC" in fmt or "BANK" in fmt:
            return "mmu-required"
        if "DBR" in fmt or "SGR" in fmt:
            return "orthogonal"
    return "orthogonal"


def select(insns):
    """SH-4 instructions missing from J2 that are not floating-point.

    Each returned instruction gains a ``jcore_tier`` field; see classify_tier.
    """
    selected = [
        insn
        for insn in insns
        if insn.get("SH4") and not insn.get("J32") and not is_floating_point(insn)
    ]
    for insn in selected:
        insn["jcore_tier"] = classify_tier(insn)
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", nargs="?", default="insns.json",
                        help="path to insns.json (default: insns.json)")
    parser.add_argument("-o", "--output", default="sh4-nonfpu.json",
                        help="output path (default: sh4-nonfpu.json)")
    args = parser.parse_args(argv)

    with open(args.input) as f:
        data = json.load(f)

    insns = data["instructions"] if isinstance(data, dict) else data
    selected = select(insns)

    with open(args.output, "w") as f:
        json.dump({"instructions": selected}, f, indent=2)
        f.write("\n")

    print(f"{len(selected)} SH-4 non-FP instructions absent from J2 "
          f"-> {args.output}", file=sys.stderr)
    for tier in ("mmu-required", "cache", "orthogonal"):
        rows = [i for i in selected if i["jcore_tier"] == tier]
        print(f"  [{tier}] ({len(rows)})", file=sys.stderr)
        for insn in rows:
            print(f"    {insn['format']}", file=sys.stderr)


if __name__ == "__main__":
    main()
