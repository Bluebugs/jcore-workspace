#!/usr/bin/env python3
"""Fixture tests for check-doc-facts.py.

    scripts/test-check-doc-facts.py                      # run all
    scripts/test-check-doc-facts.py -v                   # show checker output
    scripts/test-check-doc-facts.py --against OLD.py     # run against an older
                                                         # checker as a control
    scripts/test-check-doc-facts.py --checker PATH       # exercise this checker
    scripts/test-check-doc-facts.py --mutate-sweep       # mutation sweep


Why fixtures and not the real tree: the first version of this suite mutated
`docs/` and asserted the checker went red. That only ever exercised each check
in the one configuration the real tree happens to have, and it missed six
fail-open paths -- including a `glossary-is-value-free` that could not see the
very bug it was written for. Each case below builds a minimal tree in a temp
directory and asserts the exit status, so the *absence* of a check is a test
failure rather than a silent pass.


THE MUTATION SWEEP, and why it does not touch the working tree
--------------------------------------------------------------

`--mutate-sweep` reads `scripts/mutations.json`, applies each mutation to a
COPY of the checker in a temp directory, and runs the whole suite against that
copy via `--checker`. A mutant that the suite does not turn red is a guard
nothing asserts. A mutation whose target no longer appears exactly once is a
FAILURE, not a skip: otherwise the sweep quietly shrinks as the checker changes
and reports a clean run over fewer and fewer guards.

It exists in this form because of two separate lessons, both learned the hard
way during Wave-1 B0c:

1. **An in-place sweep is indistinguishable, to anyone else, from a real
   regression.** Three interrupted sweeps left a mutant sitting in
   `check-doc-facts.py`. A reviewer found one, checked `ps`, saw no sweep
   running, and reverted it with `git checkout --` -- while a sweep was in
   fact still in flight. That revert turned a killed mutant into a reported
   survivor. `ps` cannot answer "is a sweep running": a sweep spends nearly
   all its wall time between steps rather than on the CPU.

2. **An in-place sweep launders any case that reads `CHECKER` directly.**
   Three cases spawn the checker themselves instead of going through `run()`,
   and they named the module-level constant -- the file on disk. Under an
   in-place sweep that was accidentally correct, because the working tree WAS
   the mutant, so those mutants scored as killed for the wrong reason. Moving
   the mutation out of the tree exposed two guards whose own fixtures had never
   exercised them. Hence `CURRENT_CHECKER`: a case that spawns the checker must
   ask for the one under test, not the one on disk.

The second lesson is the load-bearing one. A marker file would have fixed (1)
and found nothing, because it does not change what the cases exercise.

"""

import collections
import difflib
import importlib.util
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "check-doc-facts.py")

# The checker currently under test. `CHECKER` is the file on disk; this is what
# a case must actually exercise, and the two differ during `--mutate-sweep`,
# which runs every mutant as a copy in a temp directory.
#
# Three cases spawn the checker themselves rather than going through `run()`,
# and they used `CHECKER`. Under an in-place sweep that happened to be right --
# the working tree WAS the mutant -- so the mutants scored as killed, for the
# wrong reason. The out-of-tree sweep exposed it immediately: two guards with
# fixtures named after them were being asserted against the pristine file, and
# both mutants survived. A case that spawns the checker must ask for this one.
CURRENT_CHECKER = CHECKER


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

# The fixture's value-guard pattern, named so the mutation cases below
# mutate THIS rather than a copy of it that drifts when the pattern changes.
VG_CANON = r"(\d+)[-\s]byte\s+SIMD\s+(?:[\w/-]+\s+)*image"

REGISTRY = """# Fact ownership registry

## Registry

| ID | Constant | Owner | Pattern |
|---|---|---|---|
| `simd.context` | SIMD context image: **520 bytes** | [simd.md](simd.md) | `\\b520[- ]byte` |

## Code bindings

| Fact ID | Doc pattern | Code | Code pattern | Relation |
|---|---|---|---|---|
| `simd.context` | `image is (\\d+) bytes` | `jcore-cpu:core/sizes.vhd` | `image_bytes\\s*=>\\s*(\\d+)` | `eq` |

## Value guards

| Fact ID | Canonical (in owner) | Scan (everywhere) |
|---|---|---|
| `simd.context` | `{VG}` | `{VG}` |

## Image layouts

| Fact ID |
|---|
| `simd.context` |

## Unresolved

| Fact | State | Owned by (task) |
|---|---|---|
| Endianness | Contradictory | B1 |

## Waivers

| Fact ID | File | Why |
|---|---|---|
""".replace("{VG}", VG_CANON)

GLOSSARY = """# Glossary

- **SIMD context.** The per-task image; size in [simd.md](simd.md).
"""

SIMD = """# SIMD

The per-task context image is 520 bytes.
The 520-byte SIMD image is the architectural size.

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


def fake_repo(root, name, branch, files, with_origin=False, shallow=False,
              raw_subject=None, dup_subject=None, base_branch=None,
              origin_branches=(), grafted=False):
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
    # BEFORE makedirs and BEFORE `git init`. The previous ordering ran both and
    # only then reached a guarded write -- and with an empty `files` dict it
    # never reached one at all, so `git init` + `update-ref` on a path outside
    # the sandbox went entirely unguarded. That is the exact mechanism of the
    # original incident, still open after the fix that was supposed to close it.
    sandboxed(root, repo)
    os.makedirs(repo)
    # The FOURTH sandbox escape, and the same mechanism as the incident this
    # harness exists to prevent: `git -C repo` does NOT override GIT_DIR, so
    # with it set every init/commit/update-ref below lands in whatever
    # repository GIT_DIR names. `sandboxed()` cannot see it, because no path is
    # passed -- the fixture directory simply ends up with no .git and nothing
    # looks wrong. Borrowed from the checker rather than re-typed: this is a
    # safety mechanism, and two copies of one would drift.
    env = load_checker_module().git_env(
        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    def g(*args):
        subprocess.run(["git", "-C", repo] + list(args), check=True, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    g("init", "-q")
    for rel, text in files.items():
        write_in(root, os.path.join(repo, rel), text)
    g("add", "-A")
    g("commit", "-qm", "fixture", "--allow-empty")
    g("update-ref", "refs/remotes/origin/%s" % branch, "HEAD")
    if base_branch is not None:
        # An "upstream" ref to subtract, so a fixture can exercise the scoping
        # in UPSTREAM_BASE: everything committed up to here is upstream, and
        # everything after it is the project's own work.
        g("update-ref", "refs/remotes/origin/%s" % base_branch, "HEAD")
        g("commit", "-qm", "project commit", "--allow-empty")
        g("update-ref", "refs/remotes/origin/%s" % branch, "HEAD")
    if grafted:
        # `git replace --graft` truncates history exactly as effectively as a
        # shallow clone, and `--is-shallow-repository` reports "false" for it.
        # Untreated, a grafted repo takes the complete+absent row and FAILS a
        # correct marker, offering `fetch --unshallow` as a remedy that would
        # not help.
        g("commit", "-qm", "grafted tip", "--allow-empty")
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True, env=env)
        g("replace", "--graft", head.stdout.strip())
        g("update-ref", "refs/remotes/origin/%s" % branch, head.stdout.strip())
    if dup_subject is not None:
        # Two commits sharing one subject: the citation then names no single
        # change. 19,683 subjects on linux's branch are in this state.
        g("commit", "-qm", dup_subject, "--allow-empty")
        g("commit", "-qm", dup_subject, "--allow-empty")
        g("update-ref", "refs/remotes/origin/%s" % branch, "HEAD")
    if raw_subject is not None:
        # A commit subject written byte-for-byte, for the two properties that
        # only raw bytes can exercise: a subject that is not valid UTF-8 (the
        # Linux history has some, and a strict decode raised UnicodeDecodeError
        # *inside subprocess* the moment the clone stopped being shallow), and
        # a subject containing a character `str.splitlines()` treats as a line
        # boundary but git does not.
        #
        # Neither `git commit -F` nor `commit-tree` will do: both warn
        # "commit message did not conform to UTF-8" and transcode from latin-1,
        # so the byte arrives valid and the fixture tests nothing. Writing the
        # object with `hash-object` stores it verbatim, which is the only way
        # to reproduce what is already sitting in the Linux history.
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True, env=env)
        tree = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD^{tree}"],
                              capture_output=True, text=True, env=env)
        body = (b"tree " + tree.stdout.strip().encode()
                + b"\nparent " + head.stdout.strip().encode()
                + b"\nauthor t <t@t> 0 +0000\ncommitter t <t@t> 0 +0000\n"
                + b"\n" + raw_subject + b"\n")
        made = subprocess.run(
            ["git", "-C", repo, "hash-object", "-t", "commit", "-w", "--stdin"],
            input=body, capture_output=True, env=env)
        sha = made.stdout.decode().strip()
        g("update-ref", "HEAD", sha)
        g("update-ref", "refs/remotes/origin/%s" % branch, sha)

    if with_origin:
        bare = os.path.join(root, "%s-origin.git" % name)
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True,
                       env=env, stdout=subprocess.DEVNULL)
        g("remote", "add", "origin", bare)
        g("push", "-q", "origin", "HEAD:refs/heads/%s" % branch)
        # Further branches the fixture's markers name, so a case testing the
        # merge question is not also tripping the branch-existence arm.
        for extra in origin_branches:
            g("push", "-q", "origin", "HEAD:refs/heads/%s" % extra)
    # BEFORE the shallow block: git refuses to push from a shallow
    # repository, so a fixture that wants both an origin and a truncated
    # history has to publish first and truncate second.
    if shallow:
        # A genuine shallow clone: git treats a repo as shallow exactly when
        # $GIT_DIR/shallow exists and names graft points. Two commits, with the
        # root grafted away, gives a `git log` that returns a truncated history
        # and no error -- the condition both submodules in this workspace were
        # in, and the one `subjects()` used to mistake for complete.
        g("commit", "-qm", "second", "--allow-empty")
        g("update-ref", "refs/remotes/origin/%s" % branch, "HEAD")
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True, env=env)
        gitdir = subprocess.run(["git", "-C", repo, "rev-parse", "--git-dir"],
                                capture_output=True, text=True, env=env)
        gd = os.path.join(repo, gitdir.stdout.strip())
        write_in(root, os.path.join(gd, "shallow"), head.stdout)
    return repo


def sandboxed(tmp, path):
    """`path`, having proved it really lands inside `tmp`.

    The first version of this guard was a single existence check inside
    `fake_repo`, and the commit that added it claimed the harness could not
    write outside its temp directory "by construction". It could, two ways: a
    symlinked `docs/` made every write in `build()` land wherever the symlink
    pointed, and an `extra` key of `../../<dir>/pwned.md` walked straight out.
    Both are closed here instead, at the one place every write goes through,
    because a guard on one function is a guard on one function.

    `realpath` is what does the work -- it resolves symlinks anywhere in the
    path, so neither a symlinked component nor a `..` component can escape.

    **What this does and does not promise.** It guards every write that goes
    through `write_in` / `build` / `fake_repo`, which is every write the helpers
    make. It cannot guard a case that calls `open()` itself -- two did, and they
    now call this explicitly. Claiming more than that is what went wrong last
    time, so the backstop is `assert_tree_untouched()` in the runner, which
    fingerprints the real docs/ and both submodules' refs before and after the
    suite and fails if anything moved. Prevention where it is structural, a
    tripwire where it is not."""
    real_tmp = os.path.realpath(tmp)
    real = os.path.realpath(path)
    if real != real_tmp and not real.startswith(real_tmp + os.sep):
        raise AssertionError(
            "fixture write escapes the sandbox: %s resolves to %s, which is "
            "outside %s. A test harness must not be able to touch the tree it "
            "is testing." % (path, real, real_tmp))
    return path


def write_in(tmp, path, text):
    os.makedirs(os.path.dirname(sandboxed(tmp, path)), exist_ok=True)
    with open(sandboxed(tmp, path), "w") as fh:
        fh.write(text)


def build(tmp, registry=REGISTRY, glossary=GLOSSARY, simd=SIMD, extra=None,
          p4_map=P4_MAP, cpu_files=None, no_cpu_repo=False, cpu_origin=False,
          cpu_shallow=False, cpu_raw_subject=None, cpu_dup=None,
          cpu_base=None, cpu_origin_branches=(), cpu_grafted=False):
    docs = os.path.join(tmp, "docs")
    os.makedirs(sandboxed(tmp, os.path.join(docs, "decisions")), exist_ok=True)
    write_in(tmp, os.path.join(docs, "fact-ownership.md"), registry)
    write_in(tmp, os.path.join(docs, "glossary.md"), glossary)
    write_in(tmp, os.path.join(docs, "simd.md"), simd)
    if p4_map is not None:
        write_in(tmp, os.path.join(docs, "soc", "p4-mmio-map.md"), p4_map)
    if not no_cpu_repo:
        files = {"core/datapath.vhm": P4_RTL, "core/sizes.vhd": SIZES_VHD,
                 "docs/insns.json": '{"instructions": []}\n'}
        files.update(cpu_files or {})
        fake_repo(tmp, "jcore-cpu", "master", files, with_origin=cpu_origin,
                  shallow=cpu_shallow, raw_subject=cpu_raw_subject,
                  dup_subject=cpu_dup, base_branch=cpu_base,
                  origin_branches=cpu_origin_branches,
                  grafted=cpu_grafted)
    for name, text in (extra or {}).items():
        write_in(tmp, os.path.join(docs, name), text)
    return tmp


def patched_checker(dstdir, *subs, base=None):
    """A copy of the checker with literal text substitutions applied.

    Used to prove a decoupling claim: widen one constant and assert the other
    check is unmoved. Asserting the two regexes merely *differ* would be a
    weaker test -- they are identical today -- so the test widens one and looks
    at behaviour instead.
    """
    text = open(base or CHECKER).read()
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


def case(name, expect_fail, expect_check=None, expect_text=None,
         reject_text=None, **kw):
    """expect_fail=True  -> the checker must exit non-zero.
       expect_fail=False -> it must exit zero.

    expect_check names the check that must appear in a FAIL line. Exit status
    alone cannot tell "the check I meant fired" from "something else did", so
    a later change could silently move a case onto a different failure.

    expect_text goes one level finer: a substring that must appear in the
    output. It exists because `expect_check` is not always enough -- several
    distinct arms report under one check name, and mutation testing found two
    that a case could not tell apart. Dropping the ambiguity arm from
    `resolved-is-merged` left the case red under the SAME check, with the
    message "is not on ... origin/master" instead of "which N commits share";
    the case passed and the mutant lived. Use it wherever the check name does
    not identify the arm."""
    kw["expect_check"] = expect_check
    kw["expect_text"] = expect_text
    # reject_text asserts a substring is ABSENT. Some defects add output rather
    # than removing it: dropping the early return after a missing upstream base
    # left the correct skip in place and then stumbled on into
    # `origin/None..origin/master`, so every positive assertion still held and
    # the mutant lived. "Nothing else fired" is sometimes the whole claim.
    kw["reject_text"] = reject_text
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
    with open(sandboxed(tmp, os.path.join(tmp, "docs", "latin1.md")), "wb") as fh:
        fh.write(b"# Latin\n\nCaf\xe9 -- not valid UTF-8.\n")


@case("a non-UTF-8 GLOSSARY fails cleanly instead of crashing", True,
      expect_check="glossary-is-value-free")
def _(tmp):
    build(tmp)
    with open(sandboxed(tmp, os.path.join(tmp, "docs", "glossary.md")), "wb") as fh:
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


@case("a short row is rejected, not skipped", True, expect_check="code-bindings")
def _(tmp):
    # The one guard in the shared loader that no fixture reached: mutation
    # testing found `if len(cells) < min_cells: continue` survived the whole
    # suite. A row with too few cells is a row somebody is mid-edit on, and
    # dropping it silently removes a check with no message.
    build(tmp, registry=REGISTRY.replace(
        "| `simd.context` | `image is (\\d+) bytes` | "
        "`jcore-cpu:core/sizes.vhd` | `image_bytes\\s*=>\\s*(\\d+)` | `eq` |",
        "| `simd.context` | `image is (\\d+) bytes` | `eq` |"))


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


# ------------------------------------------------------- B0c: no-stale-value
#
# The class these close: a value that has been RETIRED matches no registry
# pattern, because the pattern spells the current value. Every case below uses a
# value that is stale rather than merely absent, which is the only kind the old
# machinery could not see.


@case("a STALE value in an ordinary document fails (272 for 520)", True,
      expect_check="no-stale-value")
def _(tmp):
    build(tmp, extra={"hyp.md": "# H\n\nsave/restore of the 272-byte SIMD image.\n"})


@case("a stale value is NOT excused by linking the owner", True,
      expect_check="no-stale-value")
def _(tmp):
    # The reproduction from the real tree: hypervisor/hardware-spec.md linked
    # simd/spec.md on the same line, which satisfied restatement-is-linked, and
    # the number was still wrong. A linked wrong number is a wrong number.
    build(tmp, extra={"hyp.md": "# H\n\nthe 272-byte SIMD image "
                                "([simd.md](simd.md)).\n"})


@case("a BARE stale value in the owner does not license itself", True,
      expect_check="no-stale-value",
      expect_text="appears in no Registry `Constant` cell")
def _(tmp):
    # M1 narrowed but not eliminated: the retraction rule only removes values
    # on retraction lines. A bare one -- no exempt phrase, so nothing skips it
    # -- was still licensed tree-wide. The Registry's Constant cells are a
    # second, independently maintained statement of the same value, so a stale
    # one now has to be written into both before it licenses anything.
    build(tmp,
          simd=SIMD + "\nThe 272-byte SIMD image is what Tier 1 shipped.\n",
          extra={"hyp.md": "# H\n\nsaves the 272-byte SIMD image.\n"})


@case("a stale value on a retirement line IS excused", False)
def _(tmp):
    build(tmp, extra={"hyp.md": "# H\n\nThis previously read 272-byte SIMD "
                                "image; it is 520.\n"})


@case("a value the owner also licenses (J64 form) does not fail", False)
def _(tmp):
    # The Registry must state 1036 too. That is the cross-check added for M1
    # working as intended: a value the owner states and the Registry does not
    # is exactly the bare-stale-value shape, and this case is the proof it does
    # not reject the legitimate J64 form once both agree.
    build(tmp, registry=REGISTRY.replace(
              "SIMD context image: **520 bytes**",
              "SIMD context image: **520 bytes**, 1036 on J64"),
          simd=SIMD + "\nOn J64 this is a 1036-byte SIMD image.\n",
          extra={"hyp.md": "# H\n\nships the 1036-byte SIMD image.\n"})


@case("a missing '## Value guards' section fails closed", True,
      expect_check="value-guards")
def _(tmp):
    build(tmp, registry=REGISTRY.replace("## Value guards", "## Notes"))


@case("an empty Value guards table fails", True, expect_check="value-guards")
def _(tmp):
    build(tmp, registry=re.sub(r"\| `simd\.context` \| `\(.*image` \|.*\n",
                               "", REGISTRY))


@case("a value guard naming an unknown fact fails", True,
      expect_check="value-guards")
def _(tmp):
    build(tmp, registry=REGISTRY.replace(
        "| `simd.context` | `" + VG_CANON,
        "| `simd.absent` | `" + VG_CANON))


@case("a value-guard pattern with the wrong group count fails", True,
      expect_check="value-guards")
def _(tmp):
    build(tmp, registry=REGISTRY.replace(VG_CANON,
                                         VG_CANON.replace(r"(\d+)", r"\d+"), 1))


@case("a canonical pattern matching nothing in the owner fails", True,
      expect_check="no-stale-value")
def _(tmp):
    # Fails CLOSED: with no canonical value there is nothing to compare
    # restatements against, so silence would license every restatement.
    #
    # BOTH patterns are replaced, not just the canonical one. With only the
    # canonical mutated the scan still matched and failed on its own, so the
    # case went red either way and a mutant deleting this guard survived the
    # whole suite. With neither matching, the guard is the only thing that can
    # speak -- and if it is gone, a fact whose pattern has rotted passes in
    # silence, which is the fail-open shape this file exists to remove.
    build(tmp, registry=REGISTRY.replace(VG_CANON,
                                         r"(\d+)-byte NOTHING image"))


@case("a canonical pattern licensing too many values fails as too loose", True,
      expect_check="no-stale-value")
def _(tmp):
    # A guard that accepts everything is worse than no guard: it reports OK.
    build(tmp, registry=REGISTRY.replace(VG_CANON, r"(\d+)", 1))


# ------------------------------------------ B0c: image layouts, per FACT


@case("a registered image fact whose owner has NO table fails", True,
      expect_check="context-image-sums")
def _(tmp):
    # The exact hole: simd/spec.md had no field table while the registry said
    # the SIMD sizes were covered by this check. Under the old global rule the
    # FPU table alone kept it green.
    build(tmp, simd="# SIMD\n\nThe per-task context image is 520 bytes.\n"
                    "\n### 2.5 (520-byte SIMD image) stated in prose only.\n")


@case("a missing '## Image layouts' section fails closed", True,
      expect_check="context-image-sums")
def _(tmp):
    build(tmp, registry=REGISTRY.replace("## Image layouts", "## Notes"))


@case("an owner carrying two layout tables is ambiguous and fails", True,
      expect_check="context-image-sums")
def _(tmp):
    # The second table gets its own heading, and that heading makes no size
    # claim. Without it the table inherited the first one's "(520-byte SIMD
    # image)" heading, the heading arm fired, and a mutant deleting the
    # ambiguity guard survived -- the case was red for a reason it was not
    # written to test.
    build(tmp, simd=SIMD + "\n### 3 Another layout\n\n"
                           "| Offset | Bytes | Content |\n| --- | --- | --- |\n"
                           "| 0x00 | 4 | X |\n| 0x04 | — | end (4 bytes) |\n")


@case("a layout table summing to a value the owner never states fails", True,
      expect_check="context-image-sums")
def _(tmp):
    # Internally consistent and still wrong. The offsets run, the terminator
    # agrees with the offset it sits at, and the heading makes no size claim --
    # so every self-consistency arm passes. Only the per-fact comparison against
    # what the OWNER states (520) can catch it, which is what this case isolates.
    build(tmp, simd="# SIMD\n\nThe per-task context image is 520 bytes.\n"
                    "The 520-byte SIMD image is the architectural size.\n"
                    "\n### 2.5 Save / restore sequence\n\n"
                    "| Offset | Bytes | Content |\n| --- | --- | --- |\n"
                    "| 0x00 | 4 | A |\n| 0x04 | 4 | B |\n"
                    "| 0x08 | — | end (8 bytes) |\n")


# ------------------------------------------------ B0c: encoding db, nested


@case("an encoding database nested deeper in docs/ also fails", True,
      expect_check="one-encoding-database")
def _(tmp):
    # Used to pass: the check stat()ed exactly docs/insns.json.
    build(tmp, extra={"isa/insns.json": '{"instructions": []}\n'})


# ------------------------------------------- the harness's own sandbox
#
# These assert the harness cannot write outside its temp directory. They are
# here rather than in a comment because the previous commit claimed this
# property "by construction" while two routes out were open.


@case("harness refuses to write through a symlinked docs/", False)
def _(tmp):
    inner = os.path.join(tmp, "inner")
    os.makedirs(inner)
    outside = os.path.join(tmp, "outside")
    os.makedirs(outside)
    os.symlink(outside, os.path.join(inner, "docs"))
    try:
        build(inner)
    except AssertionError:
        build(tmp)          # the guard fired; leave a clean tree behind
        return
    raise AssertionError("symlinked docs/ was not refused")


@case("harness refuses an extra key that walks out with ..", False)
def _(tmp):
    inner = os.path.join(tmp, "inner")
    os.makedirs(inner)
    try:
        build(inner, extra={"../../escapee.md": "x"})
    except AssertionError:
        build(tmp)
        return
    raise AssertionError("../.. escape was not refused")


# ------------------------------- review round 2: the two fail-open holes


@case("a stale value in the OWNER does not license it elsewhere", True,
      expect_check="no-stale-value")
def _(tmp):
    # M1. The retraction convention was the thing that opened the hole: the
    # exemption was applied only when scanning, so a retired value written into
    # the owner in the sanctioned phrasing licensed itself for the whole tree,
    # and the restatement this check exists to catch then passed with exit 0.
    build(tmp,
          simd=SIMD + "\nThis previously read 272-byte SIMD image; now 520.\n",
          extra={"hyp.md": "# H\n\nsaves the 272-byte SIMD image on switch.\n"})


@case("the owner's retraction line is still allowed to exist", False)
def _(tmp):
    # The other half of M1: closing the hole must not make recording history
    # impossible. The owner may say what it used to say; that just licenses
    # nothing.
    build(tmp,
          simd=SIMD + "\nThis previously read 272-byte SIMD image; now 520.\n")


@case("a SHALLOW submodule skips rather than answering from a truncation",
      True, expect_check="resolved-is-merged", flags=("--strict",))
def _(tmp):
    # M2. `git log origin/<branch>` on a shallow clone returns a truncated
    # history and no error, so the answer looks complete. Both submodules in
    # this workspace were shallow, which made every local verdict differ from
    # CI's in the fail-open direction with nothing saying why.
    build(tmp, cpu_shallow=True, extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 — jcore-cpu@master: "fixture".**\n'})


@case("a GRAFTED history is treated as incomplete, not as complete", True,
      expect_check="resolved-is-merged", flags=("--strict",),
      expect_text="history is INCOMPLETE (shallow, or grafted")
def _(tmp):
    # `git replace --graft` truncates just as effectively as a shallow clone
    # and reports `--is-shallow-repository` = false. Without this the repo
    # takes the complete+absent row: a correct marker FAILS, with a remedy
    # (`fetch --unshallow`) that would not help.
    build(tmp, cpu_grafted=True, extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 \u2014 jcore-cpu@master: "fixture".**\n'})


@case("a strict skip is annotated for the PR UI", False)
def _(tmp):
    # Under --strict a skip IS a failure, and it was the one failure class with
    # no `::error::` line -- so exactly the failures meaning "nothing was
    # verified" were invisible in the PR UI. Run directly, because the harness
    # does not set GITHUB_ACTIONS.
    inner = os.path.join(tmp, "inner")
    os.makedirs(inner)
    build(inner, no_cpu_repo=True)
    p = subprocess.run([sys.executable, CURRENT_CHECKER, "--root", inner,
                        "--strict"],
                       capture_output=True, text=True,
                       env=dict(os.environ, GITHUB_ACTIONS="1"))
    if p.returncode == 0:
        raise AssertionError("expected the strict skip to fail the run")
    if "::error" not in p.stdout:
        raise AssertionError(
            "a --strict skip produced no ::error:: annotation:\n%s" % p.stdout)
    build(tmp)


@case("a shallow clone still PASSES a subject it can see", False,
      flags=("--strict",))
def _(tmp):
    # The other half of M2, and the reason the check is three-way rather than
    # two-way. `git log` on a shallow clone emits only commits genuinely
    # reachable from the branch -- grafting removes commits, it never invents
    # them -- so a subject that IS found is a true positive at any depth.
    # Skipping it would make --strict unusable on a shallow clone for markers
    # whose answer is already known, which is stricter than the question needs
    # and is how a gate gets worked around.
    build(tmp, cpu_shallow=True, extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 — jcore-cpu@master: "second".**\n'})


@case("undeterminable depth is treated as shallow, not as complete", False,
      mutate=(("        result = out.strip() == \"true\"",
               "        result = None\n        if True:\n"
               "            self._shallow[repo_name] = None\n"
               "            return None"),))
def _(tmp):
    # The third state of `is_shallow`: not True/False but "could not find out".
    # It is nearly unreachable in practice -- if `git log` answered, `rev-parse`
    # will too -- so it has no natural fixture, and a mutant narrowing the guard
    # from `is not False` to `is True` survived the whole suite. Unknown depth
    # must be treated as shallow: a missing subject might be truncation, and
    # failing a correct RESOLVED marker on a guess is how a check gets ignored.
    #
    # Asserted WITHOUT --strict, where the two outcomes differ in exit status:
    # a skip exits 0, a failure does not.
    build(tmp, extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 — jcore-cpu@master: "no such commit".**\n'})


@case("complete history + absent subject FAILS", True,
      expect_check="resolved-is-merged",
      expect_text="Either it is not merged")
def _(tmp):
    # The check's CORE claim, and nothing asserted it: a mutant that always
    # skipped on absence survived the whole suite, because every other absence
    # case was shallow. This is the complete+absent cell of 0002's table.
    build(tmp, extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 \u2014 jcore-cpu@master: "no such commit".**\n'})


@case("a subject shared by two commits FAILS as ambiguous", True,
      expect_check="resolved-is-merged",
      expect_text="which 2 commits on jcore-cpu share")
def _(tmp):
    # "Which commit does this cite?" has no answer. Both are on the branch, so
    # the merge question is technically yes -- and the citation has stopped
    # naming a change, which is what 0002 asks of it.
    build(tmp, cpu_dup="ambiguous subject", extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 \u2014 jcore-cpu@master: "ambiguous subject".**\n'})


@case("an UPSTREAM subject is out of scope and FAILS", True,
      expect_check="resolved-is-merged",
      mutate=(('UPSTREAM_BASE = {\n    "linux": "master",\n}',
               'UPSTREAM_BASE = {\n    "linux": "master",\n    "jcore-cpu": "base",\n}'),))
def _(tmp):
    # The 1a defect, in miniature. "fixture" is committed before the base ref,
    # so it is upstream, not this project's work. Unscoped it matched and a
    # RESOLVED marker citing an unrelated real commit passed; against the real
    # linux fork the haystack was 1,462,492 commits instead of 74.
    build(tmp, cpu_base="base", extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 \u2014 jcore-cpu@master: "fixture".**\n'})


@case("a PROJECT subject is in scope and passes", False,
      mutate=(('UPSTREAM_BASE = {\n    "linux": "master",\n}',
               'UPSTREAM_BASE = {\n    "linux": "master",\n    "jcore-cpu": "base",\n}'),))
def _(tmp):
    # The other half: scoping must not reject the project's own commits, or it
    # would fail every correct marker and be reverted within a week.
    build(tmp, cpu_base="base", extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 \u2014 jcore-cpu@master: "project commit".**\n'})


@case("a missing upstream base SKIPS rather than searching the wrong haystack",
      True, expect_check="resolved-is-merged", flags=("--strict",),
      expect_text="has no origin/absent-base",
      reject_text="could not read",
      mutate=(('UPSTREAM_BASE = {\n    "linux": "master",\n}',
               'UPSTREAM_BASE = {\n    "linux": "master",\n    "jcore-cpu": "absent-base",\n}'),))
def _(tmp):
    # `A..B` with a missing A is empty, not an error, so a vanished base would
    # silently search nothing and fail every marker. Falling back to the whole
    # branch would silently search the wrong haystack. Neither: skip.
    build(tmp, extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 \u2014 jcore-cpu@master: "fixture".**\n'})


@case("PENDING-MERGE whose subject IS on the branch fails", True,
      expect_check="pending-is-not-merged")
def _(tmp):
    # The arm that catches a marker somebody forgot to promote. Unfixtured
    # until now: a mutant dropping it survived.
    build(tmp, cpu_origin=True, cpu_origin_branches=("f/x",),
          extra={"spec.md":
        '# S\n\n> **PENDING-MERGE 2026-08-25 \u2014 jcore-cpu branch f/x: '
        '"fixture". Not on master.**\n'})


@case("PENDING-MERGE on a shallow clone cannot confirm absence", True,
      expect_check="pending-is-not-merged", flags=("--strict",),
      expect_text="absence may only mean truncation")
def _(tmp):
    # The mirror image advertised in 0002's table, and unfixtured until now.
    # This marker's whole claim is absence, and on a truncated history absence
    # is exactly what cannot be confirmed.
    build(tmp, cpu_shallow=True, cpu_origin=True, cpu_origin_branches=("f/x",),
          extra={"spec.md":
        '# S\n\n> **PENDING-MERGE 2026-08-25 \u2014 jcore-cpu branch f/x: '
        '"fixture". Not on master.**\n'})


@case("a Registry Constant cell over 100 chars fails", True,
      expect_check="registry-value-is-short")
def _(tmp):
    # Round-1 R1c: this check had zero fixtures naming it. It is the substitute
    # 0001 accepted for a prose-vs-owner check it could not write cleanly, so
    # it carries more weight than its size suggests.
    build(tmp, registry=REGISTRY.replace(
        "SIMD context image: **520 bytes**",
        "SIMD context image: **520 bytes** " + "and a great deal of explanation "
        "that belongs in the owning spec rather than in this table" ))


@case("a subject split by splitlines() but not by git does not match", True,
      expect_check="resolved-is-merged", flags=("--strict",))
def _(tmp):
    # `str.splitlines()` breaks on eight characters git never emits as a record
    # separator (\v \f \x1c \x1d \x1e \x85 U+2028 U+2029). Reading the log
    # with it manufactures "subjects" no commit has: the real subject here is
    # "prefix\x0bsuffix", and under splitlines() a marker citing just "prefix"
    # matched a fragment and PASSED. Zero occurrences in 1.46M commits today,
    # so this is latent -- which is exactly why it needs a fixture rather than
    # an argument.
    build(tmp, cpu_raw_subject=b"prefix\x0bsuffix", extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 \u2014 jcore-cpu@master: "prefix".**\n'})


@case("a non-UTF-8 commit subject does not crash the checker", False,
      flags=("--strict",))
def _(tmp):
    # Found by unshallowing linux: `git log --format=%s` over 1.46M commits
    # includes subjects that are not valid UTF-8, and the strict decode raised
    # UnicodeDecodeError inside subprocess. The clone being shallow had hidden
    # it. A crash is neither an answer nor a skip.
    build(tmp, cpu_raw_subject=b"subject with a raw \xb4 byte",
           extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 — jcore-cpu@master: "fixture".**\n'})


@case("a byte quantity that is not the image does not fire", False)
def _(tmp):
    # S4. The scan pattern must be anchored on the subject noun. Unanchored, it
    # reported that "a 4-byte SIMD store" states 4 for simd.context -- which is
    # not what the sentence says, and a check that fires on correct prose is
    # switched off within a month.
    build(tmp, extra={"hyp.md": "# H\n\nIssues a 4-byte SIMD store into a "
                                "64-byte SIMD staging buffer.\n"})


@case("a no-stale-value waiver silences a site without claiming a retraction",
      False, flags=("--check-waivers",))
def _(tmp):
    # The escape that is not a lie. Keyed check x file, like `stale-claim`, so
    # --check-waivers fails on a row that stops firing.
    build(tmp, registry=REGISTRY.replace(
              "| Fact ID | File | Why |\n|---|---|---|\n",
              "| Fact ID | File | Why |\n|---|---|---|\n"
              "| `no-stale-value` | [hyp.md](hyp.md) | different quantity |\n"),
          extra={"hyp.md": "# H\n\nthe 272-byte SIMD image.\n"})


@case("GIT_DIR cannot redirect the harness out of the sandbox", False)
def _(tmp):
    # The fourth escape route. `git -C <path>` does NOT override GIT_DIR, so
    # with it set every init/commit/update-ref in fake_repo lands in whatever
    # repository GIT_DIR names -- the same word, the same ref, the same
    # mechanism as the incident this harness exists to prevent -- while the
    # fixture directory quietly ends up with no .git at all.
    victim = os.path.join(tmp, "victim")
    os.makedirs(victim)
    env = load_checker_module().git_env(
        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "-C", victim, "init", "-q"], check=True, env=env)
    subprocess.run(["git", "-C", victim, "commit", "-qm", "base",
                    "--allow-empty"], check=True, env=env)
    before = subprocess.run(["git", "-C", victim, "for-each-ref"],
                            capture_output=True, text=True, env=env).stdout
    inner = os.path.join(tmp, "inner")
    os.makedirs(inner)
    old = os.environ.get("GIT_DIR")
    os.environ["GIT_DIR"] = os.path.join(victim, ".git")
    try:
        build(inner)
    finally:
        if old is None:
            os.environ.pop("GIT_DIR", None)
        else:
            os.environ["GIT_DIR"] = old
    after = subprocess.run(["git", "-C", victim, "for-each-ref"],
                           capture_output=True, text=True, env=env).stdout
    if before != after:
        raise AssertionError("GIT_DIR redirected the harness into %s" % victim)
    if not os.path.exists(os.path.join(inner, "jcore-cpu", ".git")):
        raise AssertionError("fixture repo was not created where it was asked "
                             "for; GIT_DIR silently redirected it")
    build(tmp)


@case("GIT_DIR cannot invert the checker's verdicts", False)
def _(tmp):
    # Read-only, but the verdicts flip: with GIT_DIR pointed at an unrelated
    # repository a bogus RESOLVED marker PASSED while every correct one FAILED.
    # A checker that answers about the wrong repository is worse than one that
    # declines to answer.
    inner = os.path.join(tmp, "inner")
    os.makedirs(inner)
    build(inner, extra={"spec.md":
        '# S\n\n> **RESOLVED 2026-08-25 \u2014 jcore-cpu@master: "fixture".**\n'})
    decoy = os.path.join(tmp, "decoy")
    os.makedirs(decoy)
    env = load_checker_module().git_env(
        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "-C", decoy, "init", "-q"], check=True, env=env)
    subprocess.run(["git", "-C", decoy, "commit", "-qm", "unrelated",
                    "--allow-empty"], check=True, env=env)
    subprocess.run(["git", "-C", decoy, "update-ref",
                    "refs/remotes/origin/master", "HEAD"], check=True, env=env)
    # Run the checker ourselves with GIT_DIR poisoned, and restore immediately:
    # leaking it into the remaining cases would silently re-point every one of
    # them at the decoy.
    poisoned = dict(os.environ, GIT_DIR=os.path.join(decoy, ".git"))
    p = subprocess.run([sys.executable, CURRENT_CHECKER, "--root", inner,
                        "--strict"],
                       capture_output=True, text=True, env=poisoned)
    if p.returncode != 0:
        raise AssertionError(
            "GIT_DIR redirected the checker: a marker that IS on the fixture "
            "repo was judged against the decoy.\n%s" % (p.stdout + p.stderr))
    build(tmp)


@case("fake_repo refuses an empty-files repo outside the sandbox", False)
def _(tmp):
    # S8. With no files, `fake_repo` never reached a guarded write, so
    # `git init` + `update-ref` ran on an unguarded path -- the exact mechanism
    # of the original incident, still open after the fix meant to close it.
    inner = os.path.join(tmp, "inner")
    os.makedirs(inner)
    outside = os.path.join(tmp, "outside")
    os.makedirs(outside)
    try:
        fake_repo(inner, "../outside/esc", "master", {})
    except AssertionError:
        build(tmp)
        return
    raise AssertionError("empty-files fake_repo escaped the sandbox")


# --------------------------------------- #19 platform-tag-foreign-part


@case("[FPGA] tag sharing a line with a foreign FPGA family fails", True,
      expect_check="platform-tag-foreign-part")
def _(tmp):
    # decisions/0004 rule 3: a `[FPGA]`/`[ASIC]` tag asserts the figure
    # describes THIS project's hardware. This is the exact mistake B0b's own
    # first draft shipped -- four sites in simd/hardware-impl.md tagged a
    # Spartan-6/Artix-7 row `[FPGA]` -- and design review caught it only by
    # reading the diff by hand. This case is the regression test for that.
    build(tmp, extra={"foo.md": "Some `[FPGA]` figure for Artix-7 class parts.\n"})


@case("[ASIC] tag sharing a line with a foreign FPGA family also fails", True,
      expect_check="platform-tag-foreign-part")
def _(tmp):
    # The rule covers both tag forms, not just `[FPGA]` -- a Spartan/Artix/
    # Kintex/Virtex/Zynq figure is never this project's ASIC target either.
    build(tmp, extra={"foo.md": "An `[ASIC]` estimate for Zynq UltraScale+.\n"})


@case("naming a foreign part in prose, with no bracket tag, passes", False)
def _(tmp):
    # The check is about the TAG, not the family name: a sentence that names
    # Spartan-6 while making no claim about this project's hardware must not
    # trip it. (decisions/0005 removed the marked-figure form this case used to
    # use, so the fixture no longer carries the retired wording -- which the
    # 0005 arm below would now fail, for a different and correct reason.)
    build(tmp, extra={"foo.md": "The J2 reference flow ran on Spartan-6; no "
                                "figure from it is carried here.\n"})


@case("[FPGA] tag with no foreign-family name on the line passes", False)
def _(tmp):
    # The correctly-tagged case: `[FPGA]` describing the actual ULX3S/ECP5
    # target must not be flagged just because the word appears at all.
    build(tmp, extra={"foo.md": "A `[FPGA]` figure for the ULX3S/ECP5 target "
                                "at ~40 MHz.\n"})


@case("a foreign family named on a DIFFERENT line from the tag passes", False)
def _(tmp):
    # Line-scoped by design (0004 says so): splitting the tag and the family
    # name across lines -- as a wrapped sentence or a multi-line table cell
    # note commonly does -- must not trip the check. This also documents the
    # limitation: the check cannot see a tag/family pair separated like this,
    # which is why it is described in 0004 as narrow, not as a substitute for
    # the manual sweep.
    build(tmp, extra={"foo.md": "This figure is `[FPGA]`.\n"
                                "It was originally measured on Artix-7.\n"})


# ------------------------------------ #20 unmeasured-figure-wording (0005)


@case("'unknown at this stage' without its second half fails", True,
      expect_check="unmeasured-figure-wording")
def _(tmp):
    # decisions/0005 rule 2: ONE wording, so the burn-down is one grep. Half a
    # phrase is how the drift starts, and this tree already spells "TBD",
    # "unmeasured" and "pending" for unrelated things.
    build(tmp, extra={"foo.md": "| Tier A | unknown at this stage |\n"})


@case("'needs measurement' without its first half fails", True,
      expect_check="unmeasured-figure-wording")
def _(tmp):
    # The other half, asserted separately: a check that only looked for the
    # first half would pass a cell reading just "needs measurement", which is
    # the same drift from the other end.
    build(tmp, extra={"foo.md": "| Tier A | needs measurement |\n"})


@case("the canonical unknown phrase passes", False)
def _(tmp):
    # The form 0005 mandates, in the position it mandates it: a table cell.
    build(tmp, extra={"foo.md": "| Tier A | unknown at this stage \u2014 "
                                "needs measurement |\n"})


@case("a hyphen instead of the em dash fails", True,
      expect_check="unmeasured-figure-wording")
def _(tmp):
    # "em dash and all" is not decoration: `grep` for the canonical phrase must
    # find every cell, and a hyphenated near-miss is invisible to it. This is
    # the case that would have let the wording drift while the check stayed
    # green, since both halves are present and only the join differs.
    build(tmp, extra={"foo.md": "| Tier A | unknown at this stage - needs "
                                "measurement |\n"})


@case("the marking convention 0005 retired fails wherever it reappears", True,
      expect_check="unmeasured-figure-wording")
def _(tmp):
    # 0005 rule 3 closing behind itself. Emphasis markers included, because
    # that is how the tree's own occurrences were written -- a regex without
    # them would have missed every real instance while passing this test if the
    # fixture had been written plainly.
    build(tmp, extra={"foo.md": "**Marked**, not retagged: the Spartan-7 "
                                "figure is kept with a note.\n"})


@case("a record quoting the retired wording on the same line passes", False)
def _(tmp):
    # A decision record must be able to say what it superseded. Per 0002's
    # account of the shared-regex incident, the escape is 0005's own list and
    # must sit on the SAME line as the thing it excuses.
    build(tmp, extra={"foo.md": "Its retired wording: \"marked, not "
                                "retagged\".\n"})


@case("the escape does not reach the next line", True,
      expect_check="unmeasured-figure-wording")
def _(tmp):
    # The same-line rule, asserted rather than assumed: an excuse one line
    # above the thing it excuses is exactly the drift 0002 warns about, and a
    # line-scoped check must not honour it.
    build(tmp, extra={"foo.md": "The retired wording is quoted below.\n"
                                "Marked, not retargeted: keep the figure.\n"})


# ------------------------------------------- the check registry reconciles
#
# Not a fixture case: this reads the checker's own source. Eighteen check-name
# literals were reconciled by nothing, so a check could be added, renamed or
# deleted with no document and no listing moving. `CHECKS` is now the one place
# that names them, and this asserts it really is the same set the code emits --
# otherwise `--list-checks` becomes a second, stale copy, which is the defect
# 0001 is about, one level up.


def load_checker_module():
    """Import the checker UNDER TEST as a module. Its top level is constants
    and definitions behind an `if __name__ == "__main__"` guard, so importing
    runs no checks.

    Under test, not on disk: `fake_repo` takes its git environment from here,
    so loading the pristine file during a sweep would hand the harness a
    working `git_env()` no matter what the mutant did."""
    spec = importlib.util.spec_from_file_location("cdf", CURRENT_CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_registry_is_complete():
    src = open(CHECKER).read()
    used = set(re.findall(r'report\.(?:fail|skip)\(\s*"([a-z0-9-]+)"', src))
    mod = load_checker_module()
    listed, records = mod.CHECKS, mod.DECISION_DOC
    problems = []
    for name in sorted(used - set(listed)):
        problems.append("check %r is emitted by the code but missing from "
                        "CHECKS (it would not appear in --list-checks)" % name)
    for name in sorted(set(listed) - used):
        problems.append("check %r is in CHECKS but emitted nowhere -- either "
                        "it was renamed, or it is a check that cannot fire"
                        % name)
    for name, (why, rec) in sorted(listed.items()):
        if rec not in records:
            problems.append("check %r cites unknown record %r" % (name, rec))
        if not why.strip():
            problems.append("check %r has no description" % name)
    for rec, path in sorted(records.items()):
        if not os.path.exists(os.path.join(os.path.dirname(HERE), path)):
            problems.append("record %s points at %s, which does not exist"
                            % (rec, path))
    # Every check must be findable by the person it fires on. Seven of eighteen
    # names appeared in no document at all, which makes a failure message a
    # dead end -- you are told a rule was broken and given no way to read it.
    docs = os.path.join(os.path.dirname(HERE), "docs")
    if not os.path.isdir(docs):
        # This assertion is location-dependent: it reads docs/ relative to the
        # suite. Run from a COPY of scripts/ it would otherwise report all 18
        # checks as "named in no document" -- eighteen confident, wrong
        # findings instead of one true one. A reviewer hit exactly this and had
        # to discard a whole mutation sweep. Say what is actually wrong.
        return ["cannot reconcile the check registry from this location: no "
                "docs/ beside %s. This assertion reads the real tree, so run "
                "the suite from the workspace rather than from a copy."
                % os.path.dirname(HERE)]
    corpus = []
    for dirpath, dirnames, filenames in os.walk(docs):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".md"):
                try:
                    with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                        corpus.append(fh.read())
                except (OSError, UnicodeDecodeError):
                    pass
    joined = "\n".join(corpus)
    for name in sorted(listed):
        if name not in joined:
            problems.append("check %r is named in no document under docs/; a "
                            "failure message that cites it is a dead end"
                            % name)
    return problems


def tree_fingerprint():
    """A cheap fingerprint of everything this suite must never touch.

    Prevention is structural where it can be (`sandboxed`), but a case can
    always call `open()` itself, and the incident that started all of this was
    invisible precisely because the suite reported 82 passed while rewriting a
    submodule's refs. This is the backstop that would have caught it: it costs
    a few stats and a handful of `git for-each-ref`s, and it turns "we hope
    nothing escaped" into "the suite would have said so"."""
    root = os.path.dirname(HERE)
    parts = []
    docs = os.path.join(root, "docs")
    for dirpath, dirnames, filenames in os.walk(docs):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            fp = os.path.join(dirpath, fn)
            try:
                st = os.stat(fp)
                parts.append("%s %d %d" % (os.path.relpath(fp, root),
                                           st.st_size, int(st.st_mtime)))
            except OSError:
                parts.append("%s MISSING" % os.path.relpath(fp, root))
    for sub in ("jcore-cpu", "linux"):
        repo = os.path.join(root, sub)
        if not os.path.exists(os.path.join(repo, ".git")):
            continue
        out = subprocess.run(
            ["git", "-C", repo, "for-each-ref",
             "--format=%(refname) %(objectname)"],
            capture_output=True, text=True)
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True)
        parts.append("%s HEAD %s" % (sub, head.stdout.strip()))
        parts.append("%s REFS %s" % (sub, out.stdout))
    return "\n".join(parts)


MUTATIONS = os.path.join(HERE, "mutations.json")


def mutate_sweep(path, verbose=False):
    """Run the whole suite once per mutation and report which survive.

    **The working tree is never modified.** Every mutant is a copy in a temp
    directory, run via `--checker`. That is not tidiness: three separate
    interrupted sweeps during this task left a mutant sitting in
    `check-doc-facts.py`, and a reviewer who found one -- checked `ps`, saw no
    sweep, and reverted it -- silently turned a KILLED into a SURVIVED in a run
    that was still in flight. An in-place sweep is indistinguishable, to anyone
    else looking at the tree, from a real regression; and `ps` cannot tell you
    a sweep is running, because a sweep spends nearly all its time between
    steps rather than on the CPU.

    A mutation whose target no longer appears exactly once is a FAILURE, not a
    skip. Otherwise the sweep quietly shrinks as the checker changes and reports
    a clean run over fewer and fewer guards -- the same fail-open shape this
    whole file exists to remove."""
    try:
        with open(path) as fh:
            spec = json.load(fh)
    except (OSError, ValueError) as exc:
        print("FAIL cannot read mutations from %s: %s" % (path, exc))
        return 1
    muts = spec.get("mutations")
    if not muts:
        print("FAIL %s lists no mutations; the sweep would pass vacuously"
              % path)
        return 1

    source = open(CHECKER).read()
    survived, moved = [], []
    tmp = tempfile.mkdtemp(prefix="cdf-sweep-")
    try:
        for i, m in enumerate(muts):
            name, old, new = m["name"], m["old"], m["new"]
            hits = source.count(old)
            if hits != 1:
                moved.append(name)
                print("%-52s TARGET MOVED (%d matches)" % (name, hits))
                continue
            dst = os.path.join(tmp, "mutant-%02d.py" % i)
            with open(dst, "w") as fh:
                fh.write(source.replace(old, new, 1))
            p = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--checker", dst],
                capture_output=True, text=True)
            killed = p.returncode != 0 or "Traceback" in (p.stdout + p.stderr)
            if not killed:
                survived.append(name)
            print("%-52s %s" % (name, "killed" if killed else "SURVIVED"))
            if verbose and not killed:
                print(p.stdout[-2000:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d mutation(s): %d killed, %d survived, %d with a moved target"
          % (len(muts), len(muts) - len(survived) - len(moved),
             len(survived), len(moved)))
    for n in survived:
        print("    SURVIVED: %s -- this guard is asserted by no case" % n)
    for n in moved:
        print("    MOVED:    %s -- update scripts/mutations.json" % n)
    return 1 if (survived or moved) else 0


def main():
    argv = sys.argv[1:]
    if "--mutate-sweep" in argv:
        i = argv.index("--mutate-sweep")
        path = (argv[i + 1] if len(argv) > i + 1
                and not argv[i + 1].startswith("-") else MUTATIONS)
        return mutate_sweep(path, verbose="-v" in argv)
    verbose = "-v" in argv
    checker = CHECKER
    allow_mutate = True
    shim_dir = None
    if "--checker" in argv:
        checker = argv[argv.index("--checker") + 1]
        global CURRENT_CHECKER
        CURRENT_CHECKER = checker
    if "--against" in argv:
        allow_mutate = False
        old = argv[argv.index("--against") + 1]
        shim_dir = tempfile.mkdtemp(prefix="cdf-old-")
        checker = backport_root(old, os.path.join(shim_dir, "checker.py"))
        print("running against %s (via --root back-port)\n" % old)

    # Fingerprinted before any case runs; compared after the last one.
    tree_before = tree_fingerprint()
    passed = failed = skipped = 0
    caught_by = collections.Counter()
    try:
        for name, expect_fail, fn, kw in CASES:
            tmp = tempfile.mkdtemp(prefix="cdf-")
            try:
                if kw.get("mutate") and not allow_mutate:
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
                    this = patched_checker(tmp, *kw["mutate"], base=checker)
                rc, out = run(tmp, this, *kw.get("flags", ()))
                crashed = "Traceback" in out
                want = kw.get("expect_check")
                want_text = kw.get("expect_text")
                banned = kw.get("reject_text")
                # argparse rejecting a flag is not a check firing.
                argparse_error = rc == 2 and "unrecognized arguments" in out
                status_ok = (rc != 0) == expect_fail
                right_check = (want is None or ("[%s]" % want) in out)
                right_text = (want_text is None or want_text in out)
                clean = (banned is None or banned not in out)
                # `expect_check` is only *load-bearing* where exit status agrees
                # and the check identity is what disagrees. Labelling a case
                # "wrong check fired" when the exit status also mismatched
                # credits expect_check with catches that exit status made on
                # its own -- which is how a "6 of 11" figure got reported when
                # the honest number was 1.
                only_check = status_ok and expect_fail and not right_check
                ok = ((not crashed) and (not argparse_error)
                      and status_ok and (right_check or not expect_fail)
                      and right_text and clean)
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
                    elif not right_text:
                        caught_by["expect_text"] += 1
                    elif not clean:
                        caught_by["reject_text"] += 1
                    else:
                        caught_by["exit status"] += 1
                why = ""
                if crashed:
                    why = "  [CRASH]"
                elif argparse_error:
                    why = "  [argparse rejected a flag -- not a check]"
                elif only_check:
                    why = "  [exit status agreed; WRONG CHECK fired, wanted %s]" % want
                elif not right_text:
                    why = ("  [exit status and check agreed; wanted message %r]"
                           % want_text)
                elif not clean:
                    why = "  [output contained %r, which must not appear]" % banned
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
    tree_after = tree_fingerprint() if tree_before is not None else None
    if tree_before is not None and tree_after != tree_before:
        failed += 1
        print("FAIL sandbox tripwire: the suite modified the real tree "
              "(docs/ contents or a submodule ref changed while it ran)")
        # Say WHAT moved. A tripwire that reports only "something changed"
        # sends the next reader hunting, and one that cannot be diagnosed is
        # one that eventually gets ignored -- which is the failure mode this
        # whole effort keeps re-learning.
        for line in itertools.islice(
                difflib.unified_diff(tree_before.split("\n"),
                                     tree_after.split("\n"),
                                     fromfile="before", tofile="after",
                                     lineterm=""), 25):
            print("       | %s" % line)
        caught_by["sandbox tripwire"] += 1
    elif tree_before is not None:
        passed += 1
        print("pass sandbox tripwire: real docs/ and both submodules untouched")

    reg = check_registry_is_complete()
    for problem in reg:
        failed += 1
        print("FAIL check-registry reconciliation: %s" % problem)
        caught_by["check registry"] += 1
    if not reg:
        passed += 1
        print("pass check registry reconciles with the code (%d checks)"
              % len(load_checker_module().CHECKS))

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
