#!/usr/bin/env python3
"""Fixture tests for check-doc-facts.py.

Why fixtures and not the real tree: the first version of this suite mutated
`docs/` and asserted the checker went red. That only ever exercised each check
in the one configuration the real tree happens to have, and it missed six
fail-open paths -- including a `glossary-is-value-free` that could not see the
very bug it was written for. Each case below builds a minimal tree in a temp
directory and asserts the exit status, so the *absence* of a check is a test
failure rather than a silent pass.

    scripts/test-check-doc-facts.py          # run all
    scripts/test-check-doc-facts.py -v       # show checker output
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "check-doc-facts.py")

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


def run(tmp, *flags):
    p = subprocess.run([sys.executable, CHECKER, "--root", tmp] + list(flags),
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


CASES = []


def case(name, expect_fail, **kw):
    """expect_fail=True  -> the checker must exit non-zero.
       expect_fail=False -> it must exit zero."""
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
    "| `glossary-fence` | [glossary.md](glossary.md) | table |\n")

FENCED_GLOSSARY = (GLOSSARY + "\n<!-- value-free: off -->\n| J32 | 32-bit |\n"
                   "<!-- value-free: on -->\n")


@case("declared AND registered fence exempts a region", False)
def _(tmp):
    build(tmp, registry=FENCE_REG, glossary=FENCED_GLOSSARY)


@case("fence with no registry row fails", True)
def _(tmp):
    build(tmp, glossary=FENCED_GLOSSARY)


@case("unclosed fence fails rather than exempting the rest of the file", True)
def _(tmp):
    build(tmp, registry=FENCE_REG,
          glossary=GLOSSARY + "\n<!-- value-free: off -->\n| J32 | 32-bit |\n")


@case("fence does not leak past its close", True)
def _(tmp):
    build(tmp, registry=FENCE_REG,
          glossary=FENCED_GLOSSARY + "\n- **X.** It is 520 bytes.\n")


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


@case("marker naming an unknown repo fails", True)
def _(tmp):
    build(tmp, extra={"spec.md": PENDING.replace("jcore-cpu", "not-a-repo")})


# ------------------------------------------------------- #7 root safety


@case("a root with no docs/ fails rather than passing vacuously", True)
def _(tmp):
    os.makedirs(os.path.join(tmp, "elsewhere"), exist_ok=True)


def main():
    verbose = "-v" in sys.argv
    passed = failed = 0
    for name, expect_fail, fn, kw in CASES:
        tmp = tempfile.mkdtemp(prefix="cdf-")
        try:
            fn(tmp)
            rc, out = run(tmp, *kw.get("flags", ()))
            crashed = "Traceback" in out
            ok = (not crashed) and ((rc != 0) == expect_fail)
            if ok:
                passed += 1
                status = "pass"
            else:
                failed += 1
                status = "FAIL"
            print("%-4s %s%s" % (status, name,
                                 "  [CRASH]" if crashed else ""))
            if verbose or not ok:
                for l in out.splitlines():
                    print("       | %s" % l)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
