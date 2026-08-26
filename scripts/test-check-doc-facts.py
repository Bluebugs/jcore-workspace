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

import collections
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

## Code bindings

| Fact ID | Doc pattern | Code | Code pattern | Relation |
|---|---|---|---|---|
| `simd.context` | `image is (\\d+) bytes` | `jcore-cpu:core/sizes.vhd` | `image_bytes\\s*=>\\s*(\\d+)` | `eq` |

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

### 2.5 Save / restore sequence (520-byte SIMD image).

| Offset | Bytes | Content       |
| ------ | ----- | ------------- |
| 0x00   | 512   | V0..V15       |
| 0x200  | 4     | P0            |
| 0x204  | 4     | VCSR          |
| 0x208  | —     | end (520 bytes) |
"""

# The P4 map and the RTL decode the `p4-offsets-match-rtl` check compares. Kept
# minimal: one register that agrees, so the check runs and passes rather than
# being absent from every fixture.
P4_MAP = """# P4 map

| Offset      | Register   | Description       |
|-------------|------------|-------------------|
| `0x010`     | MMUCR      | MMU control       |
| `0x030`     | CPUINFO    | allocated, not in RTL |
"""

P4_RTL = """architecture x of y is begin
                if    ma_ad(7 downto 0) = x"10" then p4_sel_v := P4_MMUCR;
                end if;
end architecture;
"""

SIZES_VHD = """entity sizes is generic (image_bytes => 520); end entity;
"""


def fake_repo(root, name, branch, files, with_origin=False):
    """A throwaway git repo standing in for a submodule.

    The checks read code from `origin/<branch>`, so the fixture must publish
    one: `git update-ref refs/remotes/origin/<branch>` gives a remote-tracking
    ref with no remote to talk to. Without this every code check would SKIP,
    and a suite of skips is exactly the vacuous green this task exists to stop.

    `with_origin=True` additionally creates a LOCAL bare repo and wires it up as
    `origin`, so `git ls-remote --heads origin` -- which `pending-is-not-merged`
    uses to ask whether a branch still exists -- answers offline and
    deterministically.

    **The existence check below is a safety interlock, not a tidiness
    assertion.** An earlier revision of this suite had a case that symlinked
    the REAL `jcore-cpu` submodule into a fixture tree so a branch lookup could
    run against it. When this helper began creating a repo at that same path,
    `os.makedirs(exist_ok=True)` happily followed the symlink and `git init` +
    `update-ref` rewrote `refs/remotes/origin/master` in the developer's actual
    submodule, replacing it with a commit called "fixture". The suite stayed
    green; the tree it was run in did not. A test harness must not be able to
    write outside its temp directory, and refusing a path that already exists
    is what makes that structural rather than remembered."""
    repo = os.path.join(root, name)
    if os.path.lexists(repo):
        raise AssertionError(
            "fake_repo refuses to write into an existing path: %s. It creates "
            "fixture repositories and nothing else -- if this path is a "
            "symlink to a real repository, the harness is about to rewrite "
            "that repository's refs." % repo)
    os.makedirs(repo)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    def g(*args):
        subprocess.run(["git", "-C", repo] + list(args), check=True, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    g("init", "-q")
    for rel, text in files.items():
        path = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write(text)
    g("add", "-A")
    g("commit", "-qm", "fixture", "--allow-empty")
    g("update-ref", "refs/remotes/origin/%s" % branch, "HEAD")
    if with_origin:
        bare = os.path.join(root, "%s-origin.git" % name)
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True,
                       env=env, stdout=subprocess.DEVNULL)
        g("remote", "add", "origin", bare)
        g("push", "-q", "origin", "HEAD:refs/heads/%s" % branch)
    return repo


def build(tmp, registry=REGISTRY, glossary=GLOSSARY, simd=SIMD, extra=None,
          p4_map=P4_MAP, cpu_files=None, no_cpu_repo=False, cpu_origin=False):
    docs = os.path.join(tmp, "docs")
    os.makedirs(os.path.join(docs, "decisions"), exist_ok=True)
    open(os.path.join(docs, "fact-ownership.md"), "w").write(registry)
    open(os.path.join(docs, "glossary.md"), "w").write(glossary)
    open(os.path.join(docs, "simd.md"), "w").write(simd)
    if p4_map is not None:
        os.makedirs(os.path.join(docs, "soc"), exist_ok=True)
        open(os.path.join(docs, "soc", "p4-mmio-map.md"), "w").write(p4_map)
    if not no_cpu_repo:
        files = {"core/datapath.vhm": P4_RTL, "core/sizes.vhd": SIZES_VHD,
                 "docs/insns.json": '{"instructions": []}\n'}
        files.update(cpu_files or {})
        fake_repo(tmp, "jcore-cpu", "master", files, with_origin=cpu_origin)
    for name, text in (extra or {}).items():
        path = os.path.join(docs, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write(text)
    return tmp


def patched_checker(dstdir, *subs):
    """A copy of the checker with literal text substitutions applied.

    Used to prove a decoupling claim: widen one constant and assert the other
    check is unmoved. Asserting the two regexes merely *differ* would be a
    weaker test -- they are identical today -- so the test widens one and looks
    at behaviour instead.
    """
    text = open(CHECKER).read()
    for old, new in subs:
        if old not in text:
            raise AssertionError("patch target not found: %r" % old)
        text = text.replace(old, new, 1)
    dst = os.path.join(dstdir, "patched.py")
    open(dst, "w").write(text)
    return dst


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


@case("glossary carrying a CURRENT value fails", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    build(tmp, glossary=GLOSSARY + "\n- **X.** It is 520 bytes.\n")


@case("glossary carrying a STALE value fails (the VFPUL/272 bug)", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    # The exact reproduction from review: a value that matches no registry
    # pattern, because it is the *old* value. This passed before the fix.
    build(tmp, glossary=GLOSSARY +
          "\nThe per-task SIMD context image is **272 bytes**.\n")


@case("glossary value is NOT excused by linking its owner", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    build(tmp, glossary=GLOSSARY +
          "\n- **X.** It is 272 bytes, see [simd.md](simd.md).\n")


@case("glossary bit position fails", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    build(tmp, glossary=GLOSSARY + "\n- **SR.FD.** SR bit 15.\n")


@case("glossary hex address fails", True,
      expect_check="glossary-is-value-free")
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


@case("unclosed fence fails rather than exempting the rest of the file", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    build(tmp, registry=FENCE_REG,
          glossary=GLOSSARY + "\n<!-- value-free: off (tbl) -->\n"
                              "| J32 | 32-bit |\n")


@case("fence does not leak past its close", True,
      expect_check="glossary-is-value-free")
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


@case("widening the GLOSSARY escape does not widen stale-claim", True,
      expect_check="stale-claim",
      mutate=(('GLOSSARY_QUOTE_PHRASES = [\n    "promoted from"',
               'GLOSSARY_QUOTE_PHRASES = [\n    "retired", "promoted from"'),))
def _(tmp):
    # The decoupling claim, tested as behaviour rather than as "the two regexes
    # differ" -- they are identical today, so that assertion would pass for the
    # wrong reason. Widen the glossary list only; stale-claim must be unmoved.
    build(tmp, extra={"spec.md": "# S\n\nStatus: NOT MERGED. The old walker "
                                 "is retired.\n"})


@case("widening the GLOSSARY escape does widen the glossary check", False,
      mutate=(('GLOSSARY_QUOTE_PHRASES = [\n    "promoted from"',
               'GLOSSARY_QUOTE_PHRASES = [\n    "retired", "promoted from"'),))
def _(tmp):
    # The other half: the patch must actually take effect, or the test above
    # would pass even if `mutate` silently did nothing.
    build(tmp, glossary=GLOSSARY + "\n- **X.** 272 bytes; VFPUL is retired.\n")


@case("widening the STALE-CLAIM escape does not widen the glossary check", True,
      expect_check="glossary-is-value-free",
      mutate=(('STALE_CLAIM_PHRASES = [\n    "promoted from"',
               'STALE_CLAIM_PHRASES = [\n    "retired", "promoted from"'),))
def _(tmp):
    build(tmp, glossary=GLOSSARY + "\n- **X.** 272 bytes; VFPUL is retired.\n")


# ------------------------------------------- #2 two markers on one line


TWO_MARKERS = """# Spec

## 1. Thing

> **RESOLVED 2026-08-25 — jcore-cpu@master: artifact `f`.** **RESOLVED** legacy.
"""


@case("a bare marker beside a valid one is not hidden", True,
      expect_check="marker-grammar")
def _(tmp):
    build(tmp, extra={"spec.md": TWO_MARKERS})


@case("a stale claim on a marker line is not hidden", True,
      expect_check="stale-claim")
def _(tmp):
    build(tmp, extra={"spec.md":
        "# Spec\n\n> **HISTORICAL 2026-08-25.** Status: IMPLEMENTED but NOT MERGED.\n"})


# ------------------------------------------------ #3 waiver granularity


WAIVED_REG = REGISTRY.replace(
    "| Fact ID | File | Why |\n|---|---|---|\n",
    "| Fact ID | File | Why |\n|---|---|---|\n"
    "| `legacy-marker` | [a.md](a.md) | legacy |\n")


@case("legacy-marker waiver does not silence stale-claim", True,
      expect_check="stale-claim")
def _(tmp):
    build(tmp, registry=WAIVED_REG,
          extra={"a.md": "# A\n\n> **RESOLVED** legacy form.\n"
                         "\nStatus: IMPLEMENTED but NOT MERGED.\n"})


@case("legacy-marker waiver does silence the marker it names", False)
def _(tmp):
    build(tmp, registry=WAIVED_REG,
          extra={"a.md": "# A\n\n> **RESOLVED** legacy form.\n"})


# ----------------------------------------------- #4 registry fails closed


@case("renamed Registry heading fails, does not silently disable", True,
      expect_check="registry")
def _(tmp):
    build(tmp, registry=REGISTRY.replace("## Registry", "## Registry (seed)"))


@case("empty Registry table fails", True,
      expect_check="registry")
def _(tmp):
    build(tmp, registry=REGISTRY.replace(
        "| `simd.context` | SIMD context image: **520 bytes** | "
        "[simd.md](simd.md) | `\\b520[- ]byte` |\n", ""))


@case("row missing a cell fails, is not skipped", True,
      expect_check="registry")
def _(tmp):
    build(tmp, registry=REGISTRY.replace(
        "| `simd.context` | SIMD context image: **520 bytes** | "
        "[simd.md](simd.md) | `\\b520[- ]byte` |",
        "| `simd.context` | SIMD context image | [simd.md](simd.md) |"))


@case("missing Waivers heading fails", True,
      expect_check="registry")
def _(tmp):
    build(tmp, registry=REGISTRY.replace("## Waivers", "## Notes"))


@case("uncompilable pattern fails instead of crashing", True,
      expect_check="registry")
def _(tmp):
    build(tmp, registry=REGISTRY.replace("`\\b520[- ]byte`", "`520[`"))


@case("owner dropping its own value fails", True,
      expect_check="owner-has-fact")
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
      expect_check="check-waivers",
      flags=("--check-waivers",))
def _(tmp):
    build(tmp, registry=WAIVED_REG, extra={"a.md": "# A\n\nNothing here.\n"})


# ------------------------------------------------------ #6 strict/skips


PENDING = """# Spec

> **PENDING-MERGE 2026-08-25 — jcore-cpu branch f/x: "subj". Not on master.**
"""


@case("unverifiable marker skips, exits 0 without --strict", False)
def _(tmp):
    # no_cpu_repo: this pair is about a marker that CANNOT be resolved, so the
    # submodule must genuinely be absent. Leaving B0c's fixture repo in place
    # would resolve the lookup and move the case onto a different check.
    build(tmp, extra={"spec.md": PENDING}, no_cpu_repo=True)


@case("unverifiable marker fails under --strict", True,
      expect_check="resolved-is-merged", flags=("--strict",))
def _(tmp):
    build(tmp, extra={"spec.md": PENDING}, no_cpu_repo=True)


@case("PENDING-MERGE naming the wrong integration branch fails", True,
      expect_check="marker-grammar")
def _(tmp):
    build(tmp, extra={"spec.md": PENDING.replace("Not on master.",
                                                 "Not on trunk.")})


@case("PENDING-MERGE on a branch that no longer exists FAILS, not warns", True,
      expect_check="pending-is-not-merged")
def _(tmp):
    # `pending-is-not-merged` asks `git ls-remote --heads origin <branch>`, so
    # this case needs a repo with a REACHABLE origin -- not merely a
    # remote-tracking ref.
    #
    # It used to get one by symlinking the developer's real `jcore-cpu`
    # submodule into the fixture tree. That made the suite depend on the network
    # and on whichever branches happened to exist upstream, and it put a
    # writable path to a real repository inside a temp directory -- which is
    # exactly how this harness came to rewrite that submodule's origin/master
    # with a commit called "fixture" once `build()` started creating a repo at
    # the same path. A local bare origin answers the same question offline,
    # deterministically, and cannot reach anything real.
    build(tmp, cpu_origin=True, extra={"spec.md":
        '# S\n\n> **PENDING-MERGE 2026-08-25 — jcore-cpu branch '
        'mmu/tsb-hw-walker: "no such subject here". Not on master.**\n'})


@case("marker naming an unknown repo fails", True,
      expect_check="marker-grammar")
def _(tmp):
    build(tmp, extra={"spec.md": PENDING.replace("jcore-cpu", "not-a-repo")})


# ------------------------------------------------ decode / crash safety


@case("a non-UTF-8 file fails cleanly instead of crashing", True,
      expect_check="readable")
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


# ============================================ B0c: doc-vs-code (0003 + B0c)
#
# Every case below injects one defect into an otherwise-clean fixture and
# asserts the intended check catches it. The scaffolding in `build()` is what
# makes that meaningful: without a resolvable `origin/master` in the fixture
# repo, every one of these checks would SKIP, the suite would be green, and it
# would have proved nothing. The first case exists to prove exactly that -- it
# runs the clean fixture under --strict, where a skip is a failure, so a
# regression that turns these checks into skips fails here rather than passing
# quietly everywhere else.


@case("clean fixture passes under --strict: the code checks RESOLVE, not skip",
      False, flags=("--strict",))
def _(tmp):
    build(tmp)


# --------------------------------------------------------- doc-matches-code


@case("code disagreeing with the doc fails", True,
      expect_check="doc-matches-code")
def _(tmp):
    build(tmp, cpu_files={"core/sizes.vhd":
                          "entity sizes is generic (image_bytes => 512); end;\n"})


@case("doc disagreeing with the code fails", True,
      expect_check="doc-matches-code")
def _(tmp):
    # The other direction. Both are needed: a binding that only ever read one
    # side would pass whenever the side it ignored was the one that moved.
    build(tmp, simd=SIMD.replace("image is 520 bytes", "image is 512 bytes"))


@case("a missing '## Code bindings' section fails, it does not disable B0c",
      True, expect_check="code-bindings")
def _(tmp):
    build(tmp, registry=REGISTRY.replace("## Code bindings", "## Notes"))


@case("an empty Code bindings table fails", True, expect_check="code-bindings")
def _(tmp):
    build(tmp, registry=re.sub(r"\| `simd\.context` \| `image is.*\n", "",
                               REGISTRY))


@case("a binding naming a fact absent from the Registry fails", True,
      expect_check="code-bindings")
def _(tmp):
    # The quiet way to switch a code check off is to rename its fact. Renaming
    # must be loud.
    build(tmp, registry=REGISTRY.replace("| `simd.context` | `image is",
                                         "| `simd.renamed` | `image is"))


@case("a binding pattern with no capture group fails", True,
      expect_check="code-bindings")
def _(tmp):
    build(tmp, registry=REGISTRY.replace("`image is (\\d+) bytes`",
                                         "`image is \\d+ bytes`"))


@case("a binding pattern with two capture groups fails", True,
      expect_check="code-bindings")
def _(tmp):
    build(tmp, registry=REGISTRY.replace("`image is (\\d+) bytes`",
                                         "`image (is) (\\d+) bytes`"))


@case("an unknown relation fails rather than being ignored", True,
      expect_check="code-bindings")
def _(tmp):
    build(tmp, registry=REGISTRY.replace("| `eq` |", "| `roughly` |"))


@case("an uncompilable binding pattern fails", True,
      expect_check="code-bindings")
def _(tmp):
    build(tmp, registry=REGISTRY.replace("`image is (\\d+) bytes`",
                                         "`image is (\\d+ bytes`"))


@case("a binding naming a repo with no integration branch fails", True,
      expect_check="code-bindings")
def _(tmp):
    build(tmp, registry=REGISTRY.replace("`jcore-cpu:core/sizes.vhd`",
                                         "`not-a-repo:core/sizes.vhd`"))


@case("a binding pointing at a file not on the branch FAILS (not a skip)",
      True, expect_check="doc-matches-code")
def _(tmp):
    # The ref resolves and the path does not: that is a defect in the tree, not
    # a gap in the environment, and must not be softened into a skip.
    build(tmp, registry=REGISTRY.replace("`jcore-cpu:core/sizes.vhd`",
                                         "`jcore-cpu:core/gone.vhd`"))


@case("a code pattern matching nothing fails", True,
      expect_check="doc-matches-code")
def _(tmp):
    build(tmp, cpu_files={"core/sizes.vhd": "entity sizes is end entity;\n"})


@case("a doc pattern capturing two different values fails as ambiguous", True,
      expect_check="doc-matches-code")
def _(tmp):
    # Picking the first match would make the verdict depend on file order.
    build(tmp, simd=SIMD + "\nElsewhere the image is 512 bytes.\n")


@case("an absent submodule SKIPS, and the skip fails under --strict", True,
      expect_check="doc-matches-code", flags=("--strict",))
def _(tmp):
    build(tmp, no_cpu_repo=True)


@case("an absent submodule without --strict exits 0 -- the documented trap",
      False)
def _(tmp):
    # Kept as a case, not as prose: 0002 says CI must pass --strict because a
    # checkout without submodules verifies nothing and reports success. This
    # asserts that trap is still exactly as described, so the workflow's use of
    # --strict cannot be quietly dropped as unnecessary.
    build(tmp, no_cpu_repo=True)


BYTES_FROM_SHIFT = REGISTRY.replace(
    "| `simd.context` | `image is (\\d+) bytes` | `jcore-cpu:core/sizes.vhd` "
    "| `image_bytes\\s*=>\\s*(\\d+)` | `eq` |",
    "| `simd.context` | `image is (\\d+) bytes` | `jcore-cpu:core/sizes.vhd` "
    "| `shift_left\\(x, (\\d+)\\)` | `bytes-from-shift` |")


@case("bytes-from-shift accepts 512 against a shift of 9", False)
def _(tmp):
    build(tmp, registry=BYTES_FROM_SHIFT,
          simd=SIMD.replace("image is 520 bytes", "image is 512 bytes"),
          cpu_files={"core/sizes.vhd": "y := shift_left(x, 9);\n"})


@case("bytes-from-shift rejects 512 against a shift of 8", True,
      expect_check="doc-matches-code")
def _(tmp):
    build(tmp, registry=BYTES_FROM_SHIFT,
          simd=SIMD.replace("image is 520 bytes", "image is 512 bytes"),
          cpu_files={"core/sizes.vhd": "y := shift_left(x, 8);\n"})


EQ_HEX = (REGISTRY.replace("| `eq` |", "| `eq-hex` |")
          .replace("`image_bytes\\s*=>\\s*(\\d+)`", "`x\"([0-9A-F]+)\"`")
          # The doc pattern must accept hex digits too. It did not in the first
          # draft of these two cases, so BOTH matched nothing -- and the case
          # expecting a failure passed anyway, on "doc pattern matches nothing"
          # rather than on the hex comparison it was written to exercise. Only
          # the companion pass-case exposed it. That is the same wrong-reason
          # pass this suite exists to prevent, reproduced while writing it.
          .replace("`image is (\\d+) bytes`", "`image is ([0-9A-F]+) bytes`"))


@case("eq-hex compares numerically, so 0x02C and x\"2C\" agree", False)
def _(tmp):
    build(tmp, registry=EQ_HEX,
          simd=SIMD.replace("image is 520 bytes", "image is 02C bytes"),
          cpu_files={"core/sizes.vhd": 'a <= x"2C";\n'})


@case("eq-hex still catches a real hex disagreement", True,
      expect_check="doc-matches-code")
def _(tmp):
    build(tmp, registry=EQ_HEX,
          simd=SIMD.replace("image is 520 bytes", "image is 02C bytes"),
          cpu_files={"core/sizes.vhd": 'a <= x"28";\n'})


# --------------------------------------------------- p4-offsets-match-rtl


@case("a register the RTL decodes and the map omits fails", True,
      expect_check="p4-offsets-match-rtl")
def _(tmp):
    # The TLBINST shape: this is what the check found in the real tree on its
    # first run -- decoded at 0x058 while the map called 0x058 reserved.
    build(tmp, cpu_files={"core/datapath.vhm": P4_RTL.replace(
        "end if;",
        'elsif ma_ad(7 downto 0) = x"58" then p4_sel_v := P4_TLBINST;\n'
        "                end if;")})


@case("a register at a different offset in doc and RTL fails", True,
      expect_check="p4-offsets-match-rtl")
def _(tmp):
    # The CPUINFO shape: a name in the map sitting somewhere the RTL does not
    # decode it.
    build(tmp, p4_map=P4_MAP.replace("| `0x010`     | MMUCR",
                                     "| `0x020`     | MMUCR"))


@case("a documented-but-unimplemented register does NOT fail", False)
def _(tmp):
    # CPUINFO/QACR0/QACR1 are paper allocations. Failing on these would make
    # the check fire on the normal order of work, and it would be switched off.
    build(tmp, p4_map=P4_MAP + "| `0x040`     | QACR1      | not in RTL |\n")


@case("a missing Offset/Register/Description table fails", True,
      expect_check="p4-offsets-match-rtl")
def _(tmp):
    build(tmp, p4_map=P4_MAP.replace("| Offset      | Register   |",
                                     "| Addr        | Register   |"))


@case("a missing P4 map fails", True, expect_check="p4-offsets-match-rtl")
def _(tmp):
    build(tmp, p4_map=None)


@case("a decode the regex no longer recognises fails, it does not pass", True,
      expect_check="p4-offsets-match-rtl")
def _(tmp):
    # Rewriting the if-chain as a case statement must fail loudly and be
    # followed by updating P4_DECODE_RE. Zero matches can never mean "all fine".
    build(tmp, cpu_files={"core/datapath.vhm":
                          "case ma_ad(7 downto 0) is\n"
                          '  when x"10" => p4_sel_v := P4_MMUCR;\n'
                          "end case;\n"})


@case("two registers allocated to one offset in the map fails", True,
      expect_check="p4-offsets-match-rtl")
def _(tmp):
    build(tmp, p4_map=P4_MAP + "| `0x010`     | SOMETHING  | clash |\n")


@case("one register at two offsets in the map fails", True,
      expect_check="p4-offsets-match-rtl")
def _(tmp):
    build(tmp, p4_map=P4_MAP + "| `0x044`     | MMUCR      | clash |\n")


# ----------------------------------------------------- context-image-sums


@case("an image table whose total contradicts its end offset fails", True,
      expect_check="context-image-sums")
def _(tmp):
    # The shipped FPU defect, reproduced: fields sum to 520 and end at 0x208,
    # while the terminator row calls the image 516 bytes.
    build(tmp, simd=SIMD.replace("end (520 bytes)", "end (516 bytes)"))


@case("an image table contradicting its own heading fails", True,
      expect_check="context-image-sums")
def _(tmp):
    build(tmp, simd=SIMD.replace("(520-byte SIMD image)", "(516-byte SIMD image)"))


@case("a field size that no longer matches the following offset fails", True,
      expect_check="context-image-sums")
def _(tmp):
    build(tmp, simd=SIMD.replace("| 0x200  | 4     | P0            |",
                                 "| 0x200  | 8     | P0            |"))


@case("an image table with no terminator row fails", True,
      expect_check="context-image-sums")
def _(tmp):
    build(tmp, simd=SIMD.replace("| 0x208  | —     | end (520 bytes) |\n", ""))


@case("no image table anywhere fails rather than verifying nothing", True,
      expect_check="context-image-sums")
def _(tmp):
    build(tmp, simd="# SIMD\n\nThe per-task context image is 520 bytes.\n")


# ---------------------------------------------------- one-encoding-database


@case("a second encoding database in this repo fails", True,
      expect_check="one-encoding-database")
def _(tmp):
    build(tmp, extra={"insns.json": '{"instructions": []}\n'})


@case("the canonical database missing from jcore-cpu fails", True,
      expect_check="one-encoding-database")
def _(tmp):
    # The half that matters: without this the check would go green forever the
    # moment the canonical file were deleted, having confirmed that a file
    # which does not exist is not duplicated.
    tmp = build(tmp)
    shutil.rmtree(os.path.join(tmp, "jcore-cpu"))
    fake_repo(tmp, "jcore-cpu", "master",
              {"core/datapath.vhm": P4_RTL, "core/sizes.vhd": SIZES_VHD})


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

    passed = failed = skipped = 0
    caught_by = collections.Counter()
    try:
        for name, expect_fail, fn, kw in CASES:
            tmp = tempfile.mkdtemp(prefix="cdf-")
            try:
                if kw.get("mutate") and checker != CHECKER:
                    # The patch targets source that an older checker does not
                    # contain. Running the case unmutated would score it for a
                    # reason unrelated to what it tests, so say so instead.
                    skipped += 1
                    print("skip %s  [needs mutate; not applicable to "
                          "--against]" % name)
                    continue
                fn(tmp)
                this = checker
                if kw.get("mutate"):
                    this = patched_checker(tmp, *kw["mutate"])
                rc, out = run(tmp, this, *kw.get("flags", ()))
                crashed = "Traceback" in out
                want = kw.get("expect_check")
                # argparse rejecting a flag is not a check firing.
                argparse_error = rc == 2 and "unrecognized arguments" in out
                status_ok = (rc != 0) == expect_fail
                right_check = (want is None or ("[%s]" % want) in out)
                # `expect_check` is only *load-bearing* where exit status agrees
                # and the check identity is what disagrees. Labelling a case
                # "wrong check fired" when the exit status also mismatched
                # credits expect_check with catches that exit status made on
                # its own -- which is how a "6 of 11" figure got reported when
                # the honest number was 1.
                only_check = status_ok and expect_fail and not right_check
                ok = ((not crashed) and (not argparse_error)
                      and status_ok and (right_check or not expect_fail))
                if ok:
                    passed += 1
                    status = "pass"
                else:
                    failed += 1
                    status = "FAIL"
                    if crashed:
                        caught_by["crash detection"] += 1
                    elif argparse_error:
                        caught_by["argparse guard"] += 1
                    elif only_check:
                        caught_by["expect_check"] += 1
                    else:
                        caught_by["exit status"] += 1
                why = ""
                if crashed:
                    why = "  [CRASH]"
                elif argparse_error:
                    why = "  [argparse rejected a flag -- not a check]"
                elif only_check:
                    why = "  [exit status agreed; WRONG CHECK fired, wanted %s]" % want
                elif expect_fail and not status_ok:
                    why = "  [exited 0; expected a failure]"
                elif not expect_fail and not status_ok:
                    why = "  [exited non-zero; expected a pass]"
                print("%-4s %s%s" % (status, name, why))
                if verbose or not ok:
                    for l in out.splitlines():
                        print("       | %s" % l)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    finally:
        if shim_dir:
            shutil.rmtree(shim_dir, ignore_errors=True)
    print("\n%d passed, %d failed%s"
          % (passed, failed,
             ", %d not applicable" % skipped if skipped else ""))
    if failed:
        # Which assertion actually did the work. Printed so the attribution is
        # computed rather than eyeballed off diagnostic labels.
        for k, v in sorted(caught_by.items()):
            print("    %-18s %d" % (k, v))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
