#!/usr/bin/env python3
"""Fixture tests for check-doc-facts.py.

    scripts/test-check-doc-facts.py                      # run all
    scripts/test-check-doc-facts.py -v                   # show checker output
    scripts/test-check-doc-facts.py --against OLD.py     # run against an older
                                                         # checker as a control


Why fixtures and not the real tree: the first version of this suite mutated
`docs/` and asserted the checker went red. That only ever exercised each check
in the one configuration the real tree happens to have, and it missed six
fail-open paths -- including a `glossary-is-value-free` that could not see the
very bug it was written for. Each case below builds a minimal tree in a temp
directory and asserts the exit status, so the *absence* of a check is a test
failure rather than a silent pass.

"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "check-doc-facts.py")


def backport_root(src, dst):
    """Copy an older checker and teach it --root, so the suite can be run
    against it as a control.

    Without this the comparison measures argparse, not the checks: a script
    predating --root exits 2 on every case, and a harness that only asserts
    "non-zero" scores all of those as passes. That is how a run against the
    previous revision reports 22/28 while the honest number is 10/28.
    """
    text = open(src).read()
    if "--root" in text:
        shutil.copy(src, dst)
        return dst
    text = text.replace(
        "ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))",
        "import sys as _s\n"
        "_r = [a for i, a in enumerate(_s.argv) if i and _s.argv[i-1] == '--root']\n"
        "ROOT = os.path.abspath(_r[0]) if _r else "
        "os.path.dirname(os.path.dirname(os.path.abspath(__file__)))")
    text = re.sub(r'(\n    ap\.add_argument\("--facts")',
                  '\n    ap.add_argument("--root", default=None)'
                  '\n    ap.add_argument("--strict", action="store_true")'
                  '\n    ap.add_argument("--check-waivers", action="store_true")'
                  r'\1', text, count=1)
    open(dst, "w").write(text)
    return dst

REGISTRY = """# Fact ownership registry

## Registry

| ID | Constant | Owner | Pattern |
|---|---|---|---|
| `simd.context` | SIMD context image: **520 bytes** | [simd.md](simd.md) | `\\b520[- ]byte` |

## Unresolved

| Fact | State | Owned by (task) |
|---|---|---|
| Endianness | Contradictory | B1 |

## Waivers

| Fact ID | File | Why |
|---|---|---|
"""

GLOSSARY = """# Glossary

- **SIMD context.** The per-task image; size in [simd.md](simd.md).
"""

SIMD = """# SIMD

The per-task context image is 520 bytes.
"""


def build(tmp, registry=REGISTRY, glossary=GLOSSARY, simd=SIMD, extra=None):
    docs = os.path.join(tmp, "docs")
    os.makedirs(os.path.join(docs, "decisions"), exist_ok=True)
    open(os.path.join(docs, "fact-ownership.md"), "w").write(registry)
    open(os.path.join(docs, "glossary.md"), "w").write(glossary)
    open(os.path.join(docs, "simd.md"), "w").write(simd)
    for name, text in (extra or {}).items():
        path = os.path.join(docs, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write(text)
    return tmp


def run(tmp, checker, *flags):
    p = subprocess.run([sys.executable, checker, "--root", tmp] + list(flags),
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


CASES = []


def case(name, expect_fail, expect_check=None, **kw):
    """expect_fail=True  -> the checker must exit non-zero.
       expect_fail=False -> it must exit zero.

    expect_check names the check that must appear in a FAIL line. Exit status
    alone cannot tell "the check I meant fired" from "something else did", so
    a later change could silently move a case onto a different failure."""
    kw["expect_check"] = expect_check
    def wrap(fn):
        CASES.append((name, expect_fail, fn, kw))
        return fn
    return wrap


# ------------------------------------------------------------ baseline


@case("clean tree passes", False)
def _(tmp):
    build(tmp)


# --------------------------------------------- #1 glossary-is-value-free


@case("glossary carrying a CURRENT value fails", True)
def _(tmp):
    build(tmp, glossary=GLOSSARY + "\n- **X.** It is 520 bytes.\n")


@case("glossary carrying a STALE value fails (the VFPUL/272 bug)", True)
def _(tmp):
    # The exact reproduction from review: a value that matches no registry
    # pattern, because it is the *old* value. This passed before the fix.
    build(tmp, glossary=GLOSSARY +
          "\nThe per-task SIMD context image is **272 bytes**.\n")


@case("glossary value is NOT excused by linking its owner", True)
def _(tmp):
    build(tmp, glossary=GLOSSARY +
          "\n- **X.** It is 272 bytes, see [simd.md](simd.md).\n")


@case("glossary bit position fails", True)
def _(tmp):
    build(tmp, glossary=GLOSSARY + "\n- **SR.FD.** SR bit 15.\n")


@case("glossary hex address fails", True)
def _(tmp):
    build(tmp, glossary=GLOSSARY + "\n- **P4.** Region 0xE0000000.\n")


@case("glossary retirement note is allowed to quote a value", False)
def _(tmp):
    build(tmp, glossary=GLOSSARY +
          "\n- **Gen counter.** Retired; formerly read: top 4 bits.\n")


FENCE_REG = REGISTRY.replace(
    "| Fact ID | File | Why |\n|---|---|---|\n",
    "| Fact ID | File | Why |\n|---|---|---|\n"
    "| `glossary-fence:tbl` | [glossary.md](glossary.md) | table |\n")

FENCED_GLOSSARY = (GLOSSARY + "\n<!-- value-free: off (tbl) -->\n"
                   "| J32 | 32-bit |\n<!-- value-free: on -->\n")


@case("declared AND registered fence exempts a region", False)
def _(tmp):
    build(tmp, registry=FENCE_REG, glossary=FENCED_GLOSSARY)


@case("fence with no registry row fails", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    build(tmp, glossary=FENCED_GLOSSARY)


@case("unnamed fence fails -- a fence must carry an id", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    build(tmp, registry=FENCE_REG,
          glossary=GLOSSARY + "\n<!-- value-free: off -->\n| J32 | 32-bit |\n"
                              "<!-- value-free: on -->\n")


@case("a SECOND fence is not licensed by the first row", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    # One registry row must not authorise unlimited fenced regions: this is
    # the reviewer's reproduction, appending extra fences full of values.
    build(tmp, registry=FENCE_REG,
          glossary=FENCED_GLOSSARY +
          "\n<!-- value-free: off (other) -->\n272 bytes, SR bit 13, "
          "0xDEADBEEF\n<!-- value-free: on -->\n")


@case("reusing a fence id fails", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    build(tmp, registry=FENCE_REG,
          glossary=FENCED_GLOSSARY +
          "\n<!-- value-free: off (tbl) -->\n0xDEADBEEF\n"
          "<!-- value-free: on -->\n")


@case("unclosed fence fails rather than exempting the rest of the file", True)
def _(tmp):
    build(tmp, registry=FENCE_REG,
          glossary=GLOSSARY + "\n<!-- value-free: off (tbl) -->\n"
                              "| J32 | 32-bit |\n")


@case("fence does not leak past its close", True)
def _(tmp):
    build(tmp, registry=FENCE_REG,
          glossary=FENCED_GLOSSARY + "\n- **X.** It is 520 bytes.\n")


@case("a value-shaped token the old list missed still fails", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    # Every shape review listed as slipping through unfenced.
    build(tmp, glossary=GLOSSARY + "\n- **X.** The space is **4096**.\n")


@case("counts, spelled units, single-digit hex, MHz and bit ranges fail", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    build(tmp, glossary=GLOSSARY + "\n- **X.** 32 entries, 16 kilobytes, 0x0, "
                                   "400 MHz, ASID_TAG[15:12].\n")


@case("prior-art years and product names are not values", False)
def _(tmp):
    build(tmp, glossary=GLOSSARY +
          "\n- **X.** Prior art: CDC 6600 (1964); SPARC v9 (1994); "
          "ULX3S ECP5 LFE5U-85F-6BG381C; Tier 0/1/2/3.\n")


# ------------- #1 the two quotation escapes must not be one regex


@case("'retired' does NOT excuse a merge-status claim", True,
      expect_check="stale-claim")
def _(tmp):
    # The reviewer's reproduction: widening the glossary escape had silently
    # widened this one, so appending a retirement clause bought an exemption.
    build(tmp, extra={"spec.md": "# S\n\nStatus: IMPLEMENTED on mmu/x, NOT "
                                 "MERGED. The old walker is retired.\n"})


@case("'no longer' does NOT excuse a merge-status claim", True,
      expect_check="stale-claim")
def _(tmp):
    build(tmp, extra={"spec.md": "# S\n\nStatus: NOT MERGED. That flow is no "
                                 "longer used.\n"})


@case("'retired' does NOT excuse a glossary value", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    build(tmp, glossary=GLOSSARY +
          "\n- **X.** The image is 272 bytes; VFPUL is retired.\n")


@case("a scoped quotation DOES excuse a glossary value", False)
def _(tmp):
    build(tmp, glossary=GLOSSARY +
          "\n- **X.** Retired; the entry previously read **272 bytes**.\n")


@case("a scoped quotation DOES excuse a merge-status quote", False)
def _(tmp):
    build(tmp, extra={"spec.md": "# S\n\nPromoted from \"IMPLEMENTED, NOT "
                                 "MERGED\".\n"})


# ------------------------------------------- #2 two markers on one line


TWO_MARKERS = """# Spec

## 1. Thing

> **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `f`.** **RESOLVED** legacy.
"""


@case("a bare marker beside a valid one is not hidden", True)
def _(tmp):
    build(tmp, extra={"spec.md": TWO_MARKERS})


@case("a stale claim on a marker line is not hidden", True)
def _(tmp):
    build(tmp, extra={"spec.md":
        "# Spec\n\n> **HISTORICAL 2026-08-25.** Status: IMPLEMENTED but NOT MERGED.\n"})


# ------------------------------------------------ #3 waiver granularity


WAIVED_REG = REGISTRY.replace(
    "| Fact ID | File | Why |\n|---|---|---|\n",
    "| Fact ID | File | Why |\n|---|---|---|\n"
    "| `legacy-marker` | [a.md](a.md) | legacy |\n")


@case("legacy-marker waiver does not silence stale-claim", True)
def _(tmp):
    build(tmp, registry=WAIVED_REG,
          extra={"a.md": "# A\n\n> **RESOLVED** legacy form.\n"
                         "\nStatus: IMPLEMENTED but NOT MERGED.\n"})


@case("legacy-marker waiver does silence the marker it names", False)
def _(tmp):
    build(tmp, registry=WAIVED_REG,
          extra={"a.md": "# A\n\n> **RESOLVED** legacy form.\n"})


# ----------------------------------------------- #4 registry fails closed


@case("renamed Registry heading fails, does not silently disable", True)
def _(tmp):
    build(tmp, registry=REGISTRY.replace("## Registry", "## Registry (seed)"))


@case("empty Registry table fails", True)
def _(tmp):
    build(tmp, registry=REGISTRY.replace(
        "| `simd.context` | SIMD context image: **520 bytes** | "
        "[simd.md](simd.md) | `\\b520[- ]byte` |\n", ""))


@case("row missing a cell fails, is not skipped", True)
def _(tmp):
    build(tmp, registry=REGISTRY.replace(
        "| `simd.context` | SIMD context image: **520 bytes** | "
        "[simd.md](simd.md) | `\\b520[- ]byte` |",
        "| `simd.context` | SIMD context image | [simd.md](simd.md) |"))


@case("missing Waivers heading fails", True)
def _(tmp):
    build(tmp, registry=REGISTRY.replace("## Waivers", "## Notes"))


@case("uncompilable pattern fails instead of crashing", True)
def _(tmp):
    build(tmp, registry=REGISTRY.replace("`\\b520[- ]byte`", "`520[`"))


@case("owner dropping its own value fails", True)
def _(tmp):
    build(tmp, simd="# SIMD\n\nThe image is 999 bytes.\n")


# ------------------------------------------------- #9 parse_table greed


SECOND_TABLE_REG = REGISTRY.replace(
    "## Unresolved",
    "An example of the format:\n\n| ID | Constant | Owner | Pattern |\n"
    "|---|---|---|---|\n| `bogus` | x | y | z |\n\n## Unresolved")


@case("a second table under Registry is not absorbed as facts", False)
def _(tmp):
    # `bogus` has no link and would fail the registry check if absorbed.
    build(tmp, registry=SECOND_TABLE_REG)


# --------------------------------------------------- #11 waiver hygiene


@case("a waiver that never fires fails under --check-waivers", True,
      flags=("--check-waivers",))
def _(tmp):
    build(tmp, registry=WAIVED_REG, extra={"a.md": "# A\n\nNothing here.\n"})


# ------------------------------------------------------ #6 strict/skips


PENDING = """# Spec

> **PENDING-MERGE 2026-08-25 — jcore-cpu branch f/x: "subj". Not on master.**
"""


@case("unverifiable marker skips, exits 0 without --strict", False)
def _(tmp):
    build(tmp, extra={"spec.md": PENDING})


@case("unverifiable marker fails under --strict", True, flags=("--strict",))
def _(tmp):
    build(tmp, extra={"spec.md": PENDING})


@case("PENDING-MERGE naming the wrong integration branch fails", True)
def _(tmp):
    build(tmp, extra={"spec.md": PENDING.replace("Not on master.",
                                                 "Not on trunk.")})


@case("PENDING-MERGE on a branch that no longer exists FAILS, not warns", True,
      expect_check="pending-is-not-merged")
def _(tmp):
    # A real submodule so the lookup can run: this repo itself.
    root = os.path.dirname(HERE)
    os.symlink(os.path.join(root, "jcore-cpu"),
               os.path.join(tmp, "jcore-cpu"))
    build(tmp, extra={"spec.md":
        '# S\n\n> **PENDING-MERGE 2026-08-25 — jcore-cpu branch '
        'mmu/tsb-hw-walker: "no such subject here". Not on master.**\n'})


@case("marker naming an unknown repo fails", True)
def _(tmp):
    build(tmp, extra={"spec.md": PENDING.replace("jcore-cpu", "not-a-repo")})


# ------------------------------------------------ decode / crash safety


@case("a non-UTF-8 file fails cleanly instead of crashing", True)
def _(tmp):
    build(tmp)
    with open(os.path.join(tmp, "docs", "latin1.md"), "wb") as fh:
        fh.write(b"# Latin\n\nCaf\xe9 -- not valid UTF-8.\n")


@case("a non-UTF-8 GLOSSARY fails cleanly instead of crashing", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    build(tmp)
    with open(os.path.join(tmp, "docs", "glossary.md"), "wb") as fh:
        fh.write(b"# G\n\nCaf\xe9\n")


# ------------------------------------- #8 registry-independence, #9, #10


@case("glossary check still runs when the registry is broken", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    # A registry failure must not take the registry-INDEPENDENT check with it.
    build(tmp, registry=REGISTRY.replace("## Registry", "## Registry (seed)"),
          glossary=GLOSSARY + "\n- **X.** It is 272 bytes.\n")


@case("--check-waivers with --supersede does not judge fact waivers", False,
      flags=("--supersede", "--check-waivers"))
def _(tmp):
    build(tmp, registry=REGISTRY.replace(
        "| Fact ID | File | Why |\n|---|---|---|\n",
        "| Fact ID | File | Why |\n|---|---|---|\n"
        "| `simd.context` | [other.md](other.md) | x |\n"),
        extra={"other.md": "# O\n\nnothing.\n"})


# ------------------------------------------------------- #7 root safety


@case("a root with no docs/ fails rather than passing vacuously", True)
def _(tmp):
    os.makedirs(os.path.join(tmp, "elsewhere"), exist_ok=True)


def main():
    argv = sys.argv[1:]
    verbose = "-v" in argv
    checker = CHECKER
    shim_dir = None
    if "--against" in argv:
        old = argv[argv.index("--against") + 1]
        shim_dir = tempfile.mkdtemp(prefix="cdf-old-")
        checker = backport_root(old, os.path.join(shim_dir, "checker.py"))
        print("running against %s (via --root back-port)\n" % old)

    passed = failed = 0
    try:
        for name, expect_fail, fn, kw in CASES:
            tmp = tempfile.mkdtemp(prefix="cdf-")
            try:
                fn(tmp)
                rc, out = run(tmp, checker, *kw.get("flags", ()))
                crashed = "Traceback" in out
                want = kw.get("expect_check")
                # argparse rejecting a flag is not a check firing.
                argparse_error = rc == 2 and "unrecognized arguments" in out
                right_check = (want is None
                               or ("[%s]" % want) in out)
                ok = ((not crashed) and (not argparse_error)
                      and ((rc != 0) == expect_fail)
                      and (right_check or not expect_fail))
                if ok:
                    passed += 1
                    status = "pass"
                else:
                    failed += 1
                    status = "FAIL"
                why = ""
                if crashed:
                    why = "  [CRASH]"
                elif argparse_error:
                    why = "  [argparse rejected a flag -- not a check]"
                elif expect_fail and not right_check:
                    why = "  [wrong check fired; wanted %s]" % want
                print("%-4s %s%s" % (status, name, why))
                if verbose or not ok:
                    for l in out.splitlines():
                        print("       | %s" % l)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    finally:
        if shim_dir:
            shutil.rmtree(shim_dir, ignore_errors=True)
    print("\n%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
