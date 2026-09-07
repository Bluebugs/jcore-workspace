#!/usr/bin/env python3
"""Enforce the documentation-system decisions in docs/decisions/.

  0001 - one authority per fact; the glossary is an index, not an authority
  0002 - supersede, RESOLVED and PENDING-MERGE headers

Usage:

    scripts/check-doc-facts.py                 # all checks, workspace root
    scripts/check-doc-facts.py --facts         # 0001 only
    scripts/check-doc-facts.py --supersede     # 0002 only
    scripts/check-doc-facts.py --root DIR      # check another tree (fixtures)
    scripts/check-doc-facts.py --strict        # a SKIP is a failure
    scripts/check-doc-facts.py --check-waivers # a waiver that never fires fails
    scripts/check-doc-facts.py -v              # list waived hits

Exit status is 0 only when every check that ran passed AND nothing was skipped
under --strict. A check that cannot run (missing submodule, unfetched remote,
no git) is reported as SKIP; without --strict that still exits 0, so **CI must
pass --strict** or a checkout without submodules will report success having
verified nothing.

Only Python 3 and git are required.
"""

import argparse
import collections
import os
import re
import subprocess
import sys

# Max length of a registry Constant cell. See `registry-value-is-short`.
# Every check name this script can print, what fails it, and the record that
# defines it. `--list-checks` prints this; `test-check-doc-facts.py` asserts it
# is exactly the set of names the source actually passes to report.fail/skip,
# so a check cannot be added, renamed or deleted without this table moving too.
#
# It exists because eighteen name literals were reconciled by nothing, and seven
# of them appeared in no document at all. A check named in a failure message
# that no document explains is not findable by the person it just fired on.
CHECKS = {
    # 0001 -- one authority per fact
    "registry": ("the registry is missing, unparseable, or has no rows", "0001"),
    "registry-value-is-short": ("a Constant cell over 100 characters", "0001"),
    "owner-has-fact": ("the owning document no longer states its own constant",
                       "0001"),
    "restatement-is-linked": ("a non-owner restates a constant with no link to "
                              "the owner on that line", "0001"),
    "glossary-is-value-free": ("glossary.md carries a value-shaped token", "0001"),
    "readable": ("a document under docs/ cannot be decoded", "0001"),
    "check-waivers": ("a waiver row that never fired (--check-waivers)", "0001"),
    # 0002 -- supersede / merge status
    "marker-grammar": ("a marker keyword no valid marker accounts for", "0002"),
    "resolved-is-merged": ("a RESOLVED marker whose commit or artifact is not "
                           "on the integration branch", "0002"),
    "pending-is-not-merged": ("a PENDING-MERGE marker that IS merged, or whose "
                              "branch is gone", "0002"),
    "stale-claim": ("prose asserting 'not merged' outside the marker grammar",
                    "0002"),
    # 0003 / B0c -- doc vs code
    "code-bindings": ("a malformed or orphaned `## Code bindings` row", "B0c"),
    "doc-matches-code": ("a doc constant disagreeing with the code it is bound "
                         "to", "B0c"),
    "value-guards": ("a malformed or orphaned `## Value guards` row", "B0c"),
    "no-stale-value": ("a document stating a value its owner does not state",
                       "B0c"),
    "p4-offsets-match-rtl": ("a P4 register the RTL decodes that the map omits "
                             "or misplaces", "B0c"),
    "context-image-sums": ("a save-image table that does not sum to its stated "
                           "total, or a registered image fact with no table",
                           "B0c"),
    "one-encoding-database": ("a second encoding database, or the canonical one "
                              "missing", "0003"),
}

DECISION_DOC = {
    "0001": "docs/decisions/0001-one-authority-per-fact.md",
    "0002": "docs/decisions/0002-supersede-convention.md",
    "0003": "docs/decisions/0003-canonical-encoding-database.md",
    # The doc-vs-code checks are not decided by a record; they are defined by
    # the registry's own tables, which say what each drives and why.
    "B0c": "docs/fact-ownership.md",
}

VALUE_CELL_MAX = 100

# How many distinct values a `## Value guards` canonical pattern may find in
# its owner. Two is the normal case (a J32 and a J64 form). More than a few
# means the pattern is matching unrelated sizes and has stopped being a
# guard, which must be a failure rather than a quietly permissive check.
VALUE_GUARD_MAX_LICENSED = 4

# Per 0002 section 2. A change is "merged" only when it is on this branch.
# Kept in sync with the table in 0002; that table is the human-readable copy
# and this dict is authoritative for the check.
INTEGRATION_BRANCH = {
    "jcore-cpu": "master",
    "linux": "jcore",
    "jcore-soc": "master",
    "binutils-gdb": "jcore",
    "gcc": "master",
    "gcc-sh-monitor": "master",
    "llvm-project": "main",
    "jcore-workspace": "main",
}


class Config:
    """Where the tree is. Everything path-shaped hangs off this so the checks
    can be run against a fixture directory instead of the real workspace."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.docs = os.path.join(self.root, "docs")
        self.registry = os.path.join(self.docs, "fact-ownership.md")
        self.glossary = os.path.join(self.docs, "glossary.md")
        self.decisions = os.path.join(self.docs, "decisions")

    def rel(self, path):
        return os.path.relpath(path, self.root)

    def markdown_files(self):
        out = []
        for dirpath, dirnames, filenames in os.walk(self.docs):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in sorted(filenames):
                if name.endswith(".md"):
                    out.append(os.path.join(dirpath, name))
        return sorted(out)


# ---------------------------------------------------------------- utilities


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


LINK_RE = re.compile(r"\]\(([^)#]+)")


def links_on(line, from_file):
    """Absolute paths of every relative Markdown link target on one line."""
    base = os.path.dirname(from_file)
    out = []
    for target in LINK_RE.findall(line):
        if "://" in target:
            continue
        out.append(os.path.normpath(os.path.join(base, target.strip())))
    return out


class Report:
    def __init__(self, verbose=False, strict=False):
        self.failures = 0
        self.skips = 0
        self.verbose = verbose
        self.strict = strict

    # GitHub Actions surfaces `::error::` lines on the PR itself. Without them
    # a contributor sees a red X and has to open the log to learn anything --
    # and the sibling scripts in jcore-cpu already annotate, so the two halves
    # of this gate behaved differently for no reason. Local runs are unchanged:
    # the annotation only appears when GITHUB_ACTIONS is set.
    ANNOTATE = bool(os.environ.get("GITHUB_ACTIONS"))

    def fail(self, check, where, message):
        self.failures += 1
        if self.ANNOTATE:
            print("::error title=%s::%s: %s" % (check, where, message))
        print("FAIL  [%s] %s: %s" % (check, where, message))

    def warn(self, check, where, message):
        print("warn  [%s] %s: %s" % (check, where, message))

    def skip(self, check, message):
        # Under --strict a skip is a failure: an unverifiable check must never
        # be reported as a passing one. See the module docstring.
        self.skips += 1
        if self.strict:
            self.failures += 1
            print("FAIL  [%s] (skipped, --strict) %s" % (check, message))
        else:
            print("SKIP  [%s] %s" % (check, message))

    def note(self, message):
        if self.verbose:
            print("      %s" % message)


# ------------------------------------------------------------- the registry


TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")
DIVIDER_CELL = set("-: ")


def parse_table(body, heading):
    """Rows of the FIRST pipe table under `heading`, as lists of cell strings.

    Reads the header row, then the `|---|` divider, then consecutive row lines,
    and stops at the first line that is not a table row. Stopping there is what
    keeps a second table (or a worked example) under the same heading from
    being absorbed as data.
    """
    lines = body.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == heading)
    except StopIteration:
        return None  # distinct from "a table with no rows"

    rows = []
    seen_divider = False
    for line in lines[start + 1:]:
        m = TABLE_ROW.match(line)
        if not m:
            if seen_divider:
                break  # end of the first table
            if line.startswith("## "):
                return None  # next section reached without finding a table
            continue  # prose between the heading and the table
        cells = [c.replace("\x00", "|").strip()
                 for c in m.group(1).replace(r"\|", "\x00").split("|")]
        if all(set(c) <= DIVIDER_CELL for c in cells):
            seen_divider = True
            continue
        if not seen_divider:
            continue  # the header row
        rows.append(cells)
    return rows


def unbacktick(cell):
    return cell.strip().strip("`").strip()


class Fact:
    def __init__(self, fid, value, owner, pattern, regex):
        self.id = fid
        self.value = value
        self.owner = owner
        self.pattern = pattern
        self.regex = regex


def load_registry(cfg, report):
    """Parse the registry. Fails CLOSED: any structural problem is a failure,
    never a silent "no facts to check". A registry that parses to zero rows
    disables the whole of 0001, so it must be loud."""
    if not os.path.exists(cfg.registry):
        report.fail("registry", cfg.rel(cfg.registry),
                    "missing; 0001 cannot be enforced")
        return None, {}
    try:
        body = read(cfg.registry)
    except (OSError, UnicodeDecodeError) as exc:
        report.fail("registry", cfg.rel(cfg.registry), "unreadable: %s" % exc)
        return None, {}

    reg_rows = parse_table(body, "## Registry")
    if reg_rows is None:
        report.fail("registry", cfg.rel(cfg.registry),
                    "no '## Registry' heading followed by a table. 0001 is "
                    "unenforceable without it; this is a failure, not a skip.")
        return None, {}
    if not reg_rows:
        report.fail("registry", cfg.rel(cfg.registry),
                    "'## Registry' table has no rows. Every check in 0001 "
                    "would silently pass.")
        return None, {}

    facts = []
    for cells in reg_rows:
        if len(cells) < 4:
            report.fail("registry", cfg.rel(cfg.registry),
                        "malformed row (%d cells, need 4): %s"
                        % (len(cells), " | ".join(cells)[:80]))
            continue
        fid = unbacktick(cells[0])
        if not fid:
            report.fail("registry", cfg.rel(cfg.registry),
                        "row with an empty fact ID: %s"
                        % " | ".join(cells)[:80])
            continue
        targets = links_on(cells[2], cfg.registry)
        if not targets:
            report.fail("registry", cfg.rel(cfg.registry),
                        "fact %s has no link to an owning document" % fid)
            continue
        pattern = unbacktick(cells[3])
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            report.fail("registry", cfg.rel(cfg.registry),
                        "fact %s has an uncompilable pattern %r: %s"
                        % (fid, pattern, exc))
            continue
        fact = Fact(fid, cells[1], targets[0], pattern, regex)
        # 0001: the registry states a value, it does not explain a mechanism.
        # Long cells are room for prose to drift from the owner, and that
        # drift is not otherwise checkable. See 0001 section Enforcement.
        if len(fact.value) > VALUE_CELL_MAX:
            report.fail("registry-value-is-short", fid,
                        "Constant cell is %d chars (max %d). State the value; "
                        "explanation belongs in the owning spec."
                        % (len(fact.value), VALUE_CELL_MAX))
        facts.append(fact)

    waivers = {}
    waiver_rows = parse_table(body, "## Waivers")
    if waiver_rows is None:
        report.fail("registry", cfg.rel(cfg.registry),
                    "no '## Waivers' heading followed by a table")
        return facts, waivers
    for cells in waiver_rows:
        if len(cells) < 2:
            report.fail("registry", cfg.rel(cfg.registry),
                        "malformed waiver row (%d cells, need 2)" % len(cells))
            continue
        fid = unbacktick(cells[0])
        targets = set(links_on(cells[1], cfg.registry))
        bare = unbacktick(cells[1])
        if bare and "](" not in cells[1]:
            targets.add(os.path.normpath(os.path.join(cfg.root, bare)))
        if not targets:
            report.fail("registry", cfg.rel(cfg.registry),
                        "waiver for %s names no file" % fid)
            continue
        if targets:
            waivers.setdefault(fid, set()).update(targets)
    return facts, waivers


# --------------------------------------------------- 0003 / B0c: code bindings


class Binding:
    """One row of the `## Code bindings` table: an instruction to extract a
    number from the *owning document* and the same number from a file in a
    submodule, and to fail if they disagree.

    Deliberately, a binding row carries **no value of its own**. It names two
    patterns, each with one capture group, and a relation between the captures.
    That is 0001's argument applied one level up: a row that restated the value
    would be a third copy, and copies rot. The row can go stale only by ceasing
    to match, which is a failure, not a silent pass."""

    def __init__(self, fid, doc_re, repo, path, code_re, relation):
        self.id = fid
        self.doc_re = doc_re
        self.repo = repo
        self.path = path
        self.code_re = code_re
        self.relation = relation

    @property
    def code_ref(self):
        return "%s:%s" % (self.repo, self.path)


def _num(text, base):
    try:
        return int(text.strip().replace("_", "").lstrip("#"), base)
    except ValueError:
        return None


# The relations a binding may assert, enumerated. As with VALUE_SHAPES in 0001,
# this list is the *reach* of the mechanism: a relation that is not here cannot
# be written, and an unknown name in the table is a failure rather than a
# no-op. Each entry is (doc_base, code_base, predicate).
RELATIONS = {
    # Both sides are plain decimal counts of the same unit.
    "eq": (10, 10, lambda d, c: d == c),
    # Both sides are hexadecimal (`0x02C` in the map, x"2C" in VHDL). Compared
    # numerically, so 0x02C == 0x2c == 2C and formatting churn is not a defect.
    "eq-hex": (16, 16, lambda d, c: d == c),
    # The doc states a size in bytes, the code states a shift.
    "bytes-from-shift": (10, 10, lambda d, c: d == 1 << c),
}


def load_fact_table(cfg, report, check, heading, min_cells, facts, consequence):
    """Rows of a registry table keyed by fact ID, failing CLOSED, or None.

    ONE implementation of a skeleton that was hand-copied three times. Every
    copy repeated the same four guards -- missing heading, no rows, short row,
    unknown fact ID -- and each copy's fixture coverage was written by hand.
    Mutation testing found the predictable result: the guards in the NEWEST copy
    (`load_image_layouts`) were the ones no fixture reached, so mutants that
    deleted them survived a 99-case suite. Copies of a safety property have
    exactly the failure mode copies of a fact do, which is the argument
    [0001](docs/decisions/0001-one-authority-per-fact.md) is about; the fix is
    the same one, applied to code.

    Yields (fact_id, cells). `consequence` completes the sentence "...would
    then <consequence>", so each caller's failure message still says what is
    lost, which is the part that must not be generic."""
    known = {f.id for f in (facts or [])}
    try:
        body = read(cfg.registry)
    except (OSError, UnicodeDecodeError):
        return None            # load_registry has already failed on this
    rows = parse_table(body, heading)
    if rows is None:
        report.fail(check, cfg.rel(cfg.registry),
                    "no '%s' heading followed by a table; %s. This is a "
                    "failure, not a skip." % (heading, consequence))
        return None
    if not rows:
        report.fail(check, cfg.rel(cfg.registry),
                    "'%s' table has no rows; %s." % (heading, consequence))
        return None
    out = []
    for cells in rows:
        if len(cells) < min_cells:
            report.fail(check, cfg.rel(cfg.registry),
                        "malformed row (%d cells, need %d): %s"
                        % (len(cells), min_cells, " | ".join(cells)[:80]))
            continue
        fid = unbacktick(cells[0])
        if not fid:
            report.fail(check, cfg.rel(cfg.registry), "row with an empty ID")
            continue
        # An orphaned row is the failure mode that would quietly switch a check
        # off: rename a fact in the Registry and the row stops applying to
        # anything. Name it as an error.
        if facts is not None and fid not in known:
            report.fail(check, fid,
                        "names a fact that is not in the Registry table. A "
                        "renamed or deleted fact must not silently disable its "
                        "check.")
            continue
        out.append((fid, cells))
    return out


def load_bindings(cfg, report, facts):
    """Parse `## Code bindings`."""
    rows = load_fact_table(
        cfg, report, "code-bindings", "## Code bindings", 5, facts,
        "no document would be compared against the code")
    if rows is None:
        return None
    out = []
    for fid, cells in rows:
        code_ref = unbacktick(cells[2])
        if ":" not in code_ref:
            report.fail("code-bindings", fid,
                        "Code cell %r is not `<repo>:<path>`" % code_ref)
            continue
        repo, path = code_ref.split(":", 1)
        repo, path = repo.strip(), path.strip()
        if repo not in INTEGRATION_BRANCH:
            report.fail("code-bindings", fid,
                        "unknown repo %r; add it to INTEGRATION_BRANCH before "
                        "binding to it" % repo)
            continue
        relation = unbacktick(cells[4])
        if relation not in RELATIONS:
            report.fail("code-bindings", fid,
                        "unknown relation %r (have: %s)"
                        % (relation, ", ".join(sorted(RELATIONS))))
            continue
        pats = []
        bad = False
        for label, cell in (("Doc pattern", cells[1]), ("Code pattern", cells[3])):
            pat = unbacktick(cell)
            try:
                rx = re.compile(pat)
            except re.error as exc:
                report.fail("code-bindings", fid,
                            "%s %r does not compile: %s" % (label, pat, exc))
                bad = True
                break
            if rx.groups != 1:
                report.fail("code-bindings", fid,
                            "%s %r has %d capture groups; exactly 1 is "
                            "required (it is the value being compared)"
                            % (label, pat, rx.groups))
                bad = True
                break
            pats.append(rx)
        if bad:
            continue
        out.append(Binding(fid, pats[0], repo, path, pats[1], relation))
    return out


def _sole_capture(report, check, where, rx, text, what):
    """The one value `rx` captures in `text`, or None having reported why not.

    Two distinct captures is a failure and not a "take the first": a document
    that says 16 KB in one place and 32 KB in another has no single value to
    compare, and picking one would make the check's verdict depend on file
    order."""
    found = rx.findall(text)
    if not found:
        report.fail(check, where,
                    "%s pattern %s matches nothing" % (what, rx.pattern))
        return None
    distinct = sorted(set(f.strip() for f in found))
    if len(distinct) > 1:
        report.fail(check, where,
                    "%s pattern %s captures %d different values (%s); there is "
                    "no single value to compare"
                    % (what, rx.pattern, len(distinct), ", ".join(distinct)))
        return None
    return distinct[0]


def check_code_bindings(cfg, report, repos, facts, bindings):
    """0001 decides which single document owns a constant; this asks whether
    that document agrees with the code. Wave-1 task B0c."""
    if not bindings:
        return
    owners = {f.id: f for f in facts}
    for b in bindings:
        fact = owners[b.id]
        where = b.id
        try:
            doc_body = read(fact.owner)
        except (OSError, UnicodeDecodeError) as exc:
            report.fail("doc-matches-code", where,
                        "owning document %s unreadable: %s"
                        % (cfg.rel(fact.owner), exc))
            continue
        branch = INTEGRATION_BRANCH[b.repo]
        # Read the code from origin/<integration-branch>, NOT from the
        # submodule's checked-out pointer. 0002 section 2: the pointer is not
        # evidence -- it lags the integration branches by design. Checking the
        # docs against a months-old pointer would report agreement with code
        # nobody is running.
        code_body = repos.file_at(b.repo, branch, b.path, where)
        if code_body is None:
            continue           # already reported as a skip or a failure
        doc_raw = _sole_capture(report, "doc-matches-code", where,
                                b.doc_re, doc_body,
                                "doc (%s)" % cfg.rel(fact.owner))
        code_raw = _sole_capture(report, "doc-matches-code", where,
                                 b.code_re, code_body,
                                 "code (%s@%s)" % (b.code_ref, branch))
        if doc_raw is None or code_raw is None:
            continue
        doc_base, code_base, agree = RELATIONS[b.relation]
        doc_val = _num(doc_raw, doc_base)
        code_val = _num(code_raw, code_base)
        if doc_val is None or code_val is None:
            report.fail("doc-matches-code", where,
                        "captured %r (doc) / %r (code) but relation %s needs "
                        "base-%d / base-%d numbers"
                        % (doc_raw, code_raw, b.relation, doc_base, code_base))
            continue
        if not agree(doc_val, code_val):
            report.fail("doc-matches-code", where,
                        "%s says %s, but %s@%s says %s -- these do not satisfy "
                        "`%s`. One of them is wrong; decide which."
                        % (cfg.rel(fact.owner), doc_raw, b.code_ref, branch,
                           code_raw, b.relation))
        else:
            # Emitted so a green run says which comparisons were actually
            # made. "OK" with no list cannot be told apart from "OK, having
            # compared nothing", and that ambiguity is the failure mode this
            # whole task exists to remove.
            report.note("doc-matches-code: %s -- %s says %s, %s@%s says %s (%s)"
                        % (b.id, cfg.rel(fact.owner), doc_raw, b.code_ref,
                           branch, code_raw, b.relation))


# ------------------------------------------------- B0c: the P4 register map

# The two files this check reads. Named here rather than in the registry
# because this is a structural table-vs-table comparison, not a scalar binding
# -- the same reason `glossary-is-value-free` names cfg.glossary directly.
P4_MAP_DOC = os.path.join("soc", "p4-mmio-map.md")
P4_RTL_REPO = "jcore-cpu"
P4_RTL_PATH = "core/datapath.vhm"

# The doc table is located by its COLUMN HEADER, not by its section heading.
# Renumbering or rewording a heading is an ordinary edit; changing what the
# columns mean is not. Keying on the heading would make the check fail on
# edits that cannot affect its subject, and a check that fires on ordinary
# edits gets deleted.
P4_TABLE_HEADER = ("Offset", "Register", "Description")

# `elsif ma_ad(7 downto 0) = x"2C" then p4_sel_v := P4_MMUFSR;`
P4_DECODE_RE = re.compile(
    r'ma_ad\(7\s+downto\s+0\)\s*=\s*x"([0-9A-Fa-f]{2})"\s*then\s*'
    r'p4_sel_v\s*:=\s*P4_([A-Za-z0-9_]+)\s*;')

# A doc Offset cell that is exactly one register offset. Range rows
# (`0x058`-`0xFFC`) and prose cells are deliberately not matched: they name no
# single register.
P4_DOC_OFFSET_RE = re.compile(r"^`0x([0-9A-Fa-f]{2,3})`$")
P4_DOC_NAME_RE = re.compile(r"^([A-Z][A-Z0-9_]{1,15})$")


def find_tables_by_header(body, headers):
    """Every pipe table whose header cells start with `headers`, as
    (header_line_index, rows).

    Located by COLUMN HEADER rather than by section heading on purpose:
    renumbering or rewording a heading is an ordinary edit and must not move a
    check, while changing what the columns mean is exactly the event a check
    should notice."""
    lines = body.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = TABLE_ROW.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < len(headers):
            continue
        if tuple(cells[:len(headers)]) != tuple(headers):
            continue
        rows = []
        seen_divider = False
        for line2 in lines[i + 1:]:
            m2 = TABLE_ROW.match(line2)
            if not m2:
                if seen_divider:
                    break
                continue
            cells2 = [c.replace("\x00", "|").strip()
                      for c in m2.group(1).replace(r"\|", "\x00").split("|")]
            if all(set(c) <= DIVIDER_CELL for c in cells2):
                seen_divider = True
                continue
            if seen_divider:
                rows.append(cells2)
        out.append((i, rows))
    return out


def find_table_by_header(body, headers):
    """Rows of the first pipe table whose header cells start with `headers`."""
    found = find_tables_by_header(body, headers)
    return found[0][1] if found else None


def check_p4_offsets(cfg, report, repos):
    """Every P4 register the RTL decodes must appear in the map at the same
    offset. Wave-1 task B0c.

    **The implication is deliberately one-way.** RTL-decoded => documented at
    that offset. The converse is NOT asserted, because the map legitimately
    carries paper allocations the RTL has not implemented (CPUINFO, QACR0,
    QACR1 today, each marked as such in its own row). Asserting doc => RTL
    would fire every time somebody allocates an address before building it,
    which is the normal order of work here, and the check would be switched off
    inside a month. What it does assert is the direction where silence is
    dangerous: a register that exists in hardware and is absent from, or
    misplaced in, the map."""
    doc_path = os.path.join(cfg.docs, P4_MAP_DOC)
    if not os.path.exists(doc_path):
        report.fail("p4-offsets-match-rtl", cfg.rel(doc_path),
                    "the P4 map is missing; the RTL decode is unchecked")
        return
    try:
        doc_body = read(doc_path)
    except (OSError, UnicodeDecodeError) as exc:
        report.fail("p4-offsets-match-rtl", cfg.rel(doc_path),
                    "unreadable: %s" % exc)
        return

    rows = find_table_by_header(doc_body, P4_TABLE_HEADER)
    if rows is None:
        report.fail("p4-offsets-match-rtl", cfg.rel(doc_path),
                    "no table with columns %s. Without it nothing is compared "
                    "against the RTL, so this is a failure, not a skip."
                    % " | ".join(P4_TABLE_HEADER))
        return

    doc = {}
    at_offset = {}
    for cells in rows:
        mo = P4_DOC_OFFSET_RE.match(cells[0].strip())
        mn = P4_DOC_NAME_RE.match(unbacktick(cells[1]))
        if not mo or not mn:
            continue           # a range row, or `reserved`
        name, off = mn.group(1), int(mo.group(1), 16)
        if name in doc and doc[name] != off:
            report.fail("p4-offsets-match-rtl", cfg.rel(doc_path),
                        "%s is listed at two different offsets (0x%03X and "
                        "0x%03X)" % (name, doc[name], off))
        doc[name] = off
        if off in at_offset and at_offset[off] != name:
            report.fail("p4-offsets-match-rtl", cfg.rel(doc_path),
                        "offset 0x%03X is allocated twice, to %s and %s"
                        % (off, at_offset[off], name))
        at_offset[off] = name
    if not doc:
        report.fail("p4-offsets-match-rtl", cfg.rel(doc_path),
                    "the register table parsed to zero name/offset pairs. "
                    "Every comparison below would vacuously pass.")
        return

    branch = INTEGRATION_BRANCH[P4_RTL_REPO]
    rtl_body = repos.file_at(P4_RTL_REPO, branch, P4_RTL_PATH,
                             "p4-offsets-match-rtl",
                             check="p4-offsets-match-rtl")
    if rtl_body is None:
        return                 # skip/failure already reported

    rtl = {}
    for off_hex, name in P4_DECODE_RE.findall(rtl_body):
        off = int(off_hex, 16)
        if name in rtl and rtl[name] != off:
            report.fail("p4-offsets-match-rtl", "%s:%s" % (P4_RTL_REPO, name),
                        "decoded at two offsets, 0x%03X and 0x%03X"
                        % (rtl[name], off))
        rtl[name] = off
    if not rtl:
        report.fail("p4-offsets-match-rtl",
                    "%s:%s@%s" % (P4_RTL_REPO, P4_RTL_PATH, branch),
                    "the p4_sel_v decode matched zero registers. Either the "
                    "decode moved or it was rewritten in another form; update "
                    "P4_DECODE_RE. Passing here would mean checking nothing.")
        return

    for name in sorted(rtl):
        if name not in doc:
            report.fail("p4-offsets-match-rtl", name,
                        "decoded by %s at offset 0x%03X but absent from %s. "
                        "The map is the authority for P4 allocation; a live "
                        "register missing from it is how the next allocation "
                        "collides with it."
                        % (P4_RTL_PATH, rtl[name], cfg.rel(doc_path)))
        elif doc[name] != rtl[name]:
            report.fail("p4-offsets-match-rtl", name,
                        "%s says 0x%03X, %s@%s decodes it at 0x%03X"
                        % (cfg.rel(doc_path), doc[name], P4_RTL_PATH, branch,
                           rtl[name]))
    report.note("p4-offsets-match-rtl: %d decoded registers checked against "
                "%d documented" % (len(rtl), len(doc)))


# --------------------------------------------------- B0c: stale-value guards


class ValueGuard:
    """One row of `## Value guards`: how to read a fact's value out of its
    owner, and how to find restatements of it anywhere in `docs/`.

    THE HOLE THIS CLOSES. `restatement-is-linked` matches the registry's
    `Pattern`, which spells the CURRENT value (`\\b520[- ]byte`). A **stale**
    value therefore matches nothing and is invisible -- which is the exact
    escape 0001 identified and invented `VALUE_SHAPES` for. But that shape scan
    runs on `glossary.md` alone, because its rule is "carry no value at all",
    and no other document can be held to that. So the blindness 0001 closed for
    one file stayed open for every other file in the tree, and it hid a
    `**272-byte SIMD image** ... + VFPUL` in `hypervisor/hardware-spec.md` and a
    `132-byte FPU save/restore image` in `jcore-ulx3s-service-plan.md` through
    the whole of B0a and the first B0c commit.

    Two patterns rather than one, and both carry exactly one capture group:

      - `canonical` runs against the OWNER and must yield exactly one value.
        That value is the answer; nothing here restates it, so this row cannot
        drift from the fact the way a hardcoded expectation would.
      - `scan` runs against every document. Any capture that differs from the
        canonical value is a failure -- **whether or not the line links the
        owner**, because a linked wrong number is still a wrong number, and
        `hypervisor/hardware-spec.md:688` was linked.

    The two are separate because the owner states a value in the phrasing its
    own prose wants, while restatements elsewhere use other phrasings, and one
    regex forced to do both ends up loose enough to match unrelated sizes."""

    def __init__(self, fid, canonical, scan):
        self.id = fid
        self.canonical = canonical
        self.scan = scan


def load_value_guards(cfg, report, facts):
    """Parse `## Value guards`."""
    rows = load_fact_table(
        cfg, report, "value-guards", "## Value guards", 3, facts,
        "a retired value would be invisible again, as it was before B0c")
    if rows is None:
        return None
    out = []
    for fid, cells in rows:
        pats = []
        bad = False
        for label, cell in (("Canonical", cells[1]), ("Scan", cells[2])):
            pat = unbacktick(cell)
            try:
                rx = re.compile(pat)
            except re.error as exc:
                report.fail("value-guards", fid,
                            "%s pattern %r does not compile: %s"
                            % (label, pat, exc))
                bad = True
                break
            if rx.groups != 1:
                report.fail("value-guards", fid,
                            "%s pattern %r has %d capture groups; exactly 1 is "
                            "required" % (label, pat, rx.groups))
                bad = True
                break
            pats.append(rx)
        if not bad:
            out.append(ValueGuard(fid, pats[0], pats[1]))
    return out


def _spans(text):
    """(line_number, line_start_offset) index for mapping match offsets."""
    out, pos = [], 0
    for n, line in enumerate(text.split("\n"), 1):
        out.append((n, pos, pos + len(line)))
        pos += len(line) + 1
    return out


def _match_lines(index, start, end):
    """The 1-based line numbers a match spans."""
    return [n for n, lo, hi in index if lo <= end and hi >= start]


def _excused(lines, index, m):
    """True when any line the match spans is a retraction line.

    Scanning runs over the FULL text rather than line by line, so a value and
    its subject noun still pair up across a wrap -- `272-byte context-switch\n
    image` was invisible to the line-based version. That means a match can span
    two lines, and the exemption has to consider both.

    Takes the already-split lines: re-splitting per match made this quadratic in
    file size, which nothing notices at 0.3s and would be a trap later."""
    return any(STALE_VALUE_EXEMPT.search(lines[n - 1])
               for n in _match_lines(index, m.start(), m.end()))


def check_no_stale_value(cfg, report, facts, guards, waivers):
    """No document may state a value for a registered fact other than the one
    its owner states. Wave-1 task B0c."""
    if not guards:
        return
    owners = {f.id: f for f in facts}
    corpus = {}
    for p in cfg.markdown_files():
        # The decision records quote retired values on purpose -- 0001's whole
        # Context section is a table of them -- and `check_facts` already
        # excludes this directory for the same reason.
        if p.startswith(cfg.decisions + os.sep):
            continue
        try:
            corpus[p] = read(p)
        except (OSError, UnicodeDecodeError):
            continue           # `check_facts` reports unreadable files
    for g in guards:
        fact = owners[g.id]
        body = corpus.get(fact.owner)
        if body is None:
            report.fail("no-stale-value", g.id,
                        "owning document %s is missing or unreadable; the "
                        "canonical value cannot be established"
                        % cfg.rel(fact.owner))
            continue
        # The owner LICENSES a small set of values, rather than exactly one.
        # A fact legitimately has a J32 and a J64 form (520 and 1036), and
        # demanding one value would either fail on the owner or force the scan
        # pattern so tight it stopped seeing restatements. The set is capped and
        # printed, so what has been licensed is visible rather than implied.
        #
        # **Retraction lines in the owner license nothing.** This is the whole
        # hole in the first version: the exemption was applied only in the scan
        # loop, so a retired value written into the owner in the sanctioned
        # phrasing -- "this previously read 272-byte SIMD image" -- licensed 272
        # for the entire tree, and the very restatement this check exists to
        # catch then passed. The convention for recording history opened the
        # hole rather than confining it. A line that is retiring a value is by
        # definition not stating it as current, so it must not be a source of
        # licence either.
        owner_lines = body.split("\n")
        owner_index = _spans(body)
        licensed = sorted(set(
            m.group(1).strip()
            for m in g.canonical.finditer(body)
            if not _excused(owner_lines, owner_index, m)))
        if not licensed:
            report.fail("no-stale-value", g.id,
                        "canonical pattern %s matches nothing in the owner %s; "
                        "there is no value to compare restatements against"
                        % (g.canonical.pattern, cfg.rel(fact.owner)))
            continue
        if len(licensed) > VALUE_GUARD_MAX_LICENSED:
            report.fail("no-stale-value", g.id,
                        "canonical pattern %s licenses %d different values in "
                        "%s (%s). A pattern that loose is not a guard: it would "
                        "accept almost any restatement."
                        % (g.canonical.pattern, len(licensed),
                           cfg.rel(fact.owner), ", ".join(licensed)))
            continue
        hits = 0
        for path, text in sorted(corpus.items()):
            lines = text.split("\n")
            index = _spans(text)
            for m in g.scan.finditer(text):
                n = _match_lines(index, m.start(), m.end())[0]
                if m.group(1) in licensed:
                    continue
                if _excused(lines, index, m):
                    report.note("stale value %r for %s excused as a "
                                "quotation at %s:%d"
                                % (m.group(1), g.id, cfg.rel(path), n))
                    continue
                # An escape that is NOT a retraction claim. The only way to
                # say "this number is a different quantity" used to be to
                # assert the value had been retired, which is a lie when it
                # has not. This is the existing waiver machinery, keyed by
                # check name x file exactly as `stale-claim` is, so
                # --check-waivers fails on a row that stops firing.
                if waivers.allows("no-stale-value", path):
                    report.note("waived: stale value %r for %s at %s:%d"
                                % (m.group(1), g.id, cfg.rel(path), n))
                    continue
                hits += 1
                report.fail("no-stale-value", "%s:%d" % (cfg.rel(path), n),
                            "states %r for %s; the owner %s states only %s. "
                            "A stale value matches no registry pattern, so "
                            "nothing else in this checker can see it."
                            % (m.group(1), g.id, cfg.rel(fact.owner),
                               "/".join(licensed)))
        if not hits:
            report.note("no-stale-value: %s licenses %s, no divergent "
                        "restatement" % (g.id, "/".join(licensed)))


# ------------------------------------------ B0c / 0003: the encoding database

ENCODING_DB_REPO = "jcore-cpu"
ENCODING_DB_PATH = "docs/insns.json"


def check_one_encoding_database(cfg, report, repos):
    """0003: `jcore-cpu/docs/insns.json` is the only encoding database.

    Two assertions, and the second is the load-bearing one. Failing only on "a
    second copy exists here" would go green forever the moment the canonical
    file were deleted or renamed -- having confirmed that a file which no longer
    exists is not duplicated. So the canonical copy's presence on the
    integration branch is asserted too."""
    # Walk, rather than stat one path: a copy re-added at docs/isa/insns.json
    # is the same defect and used to pass.
    strays = []
    for dirpath, dirnames, filenames in os.walk(cfg.docs):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if "insns.json" in filenames:
            strays.append(os.path.join(dirpath, "insns.json"))
    for stray in sorted(strays):
        report.fail("one-encoding-database", cfg.rel(stray),
                    "a second encoding database. 0003 makes %s:%s canonical; "
                    "this copy had drifted 6 instructions and 42 timing values "
                    "behind it and failed both oracles. Cite the submodule path "
                    "instead of re-adding a copy."
                    % (ENCODING_DB_REPO, ENCODING_DB_PATH))

    branch = INTEGRATION_BRANCH[ENCODING_DB_REPO]
    present = repos.has_path(ENCODING_DB_REPO, branch, ENCODING_DB_PATH)
    if present is None:
        report.skip("one-encoding-database",
                    "cannot ask %s for %s on origin/%s; the canonical database "
                    "is unverified" % (ENCODING_DB_REPO, ENCODING_DB_PATH,
                                       branch))
    elif not present:
        report.fail("one-encoding-database",
                    "%s:%s" % (ENCODING_DB_REPO, ENCODING_DB_PATH),
                    "the canonical encoding database is not on origin/%s. "
                    "Everything that cites it is now citing nothing." % branch)
    else:
        report.note("one-encoding-database: canonical copy present at %s:%s@%s"
                    % (ENCODING_DB_REPO, ENCODING_DB_PATH, branch))


# ------------------------------------------- B0c: context-image field tables

# A save-image layout table: `| Offset | Bytes | Content |`.
IMAGE_TABLE_HEADER = ("Offset", "Bytes", "Content")
IMAGE_OFFSET_RE = re.compile(r"^`?0x([0-9A-Fa-f]+)`?$")
IMAGE_BYTES_RE = re.compile(r"^`?(\d+)`?$")
# `end (136 bytes)` -- the terminator row's own statement of the total.
IMAGE_TOTAL_RE = re.compile(r"\((\d+)\s*bytes?\)")
# `### 7.4 Save / restore sequence (136-byte FPU image). [T2]`
IMAGE_HEADING_RE = re.compile(r"^#{2,4} .*?\((\d+)-byte\b[^)]*\bimage\)")


def load_image_layouts(cfg, report, facts):
    """Parse `## Image layouts`: the facts whose owner MUST carry a field table.

    Without this the check was driven by a global table count, and so was
    satisfied forever by the one table that already existed. `simd/spec.md` had
    no field table at all while `fact-ownership.md` asserted the SIMD sizes were
    "covered instead by `context-image-sums`" -- an uncovered fact, asserted to
    be covered, under a heading promising the gaps were visible."""
    rows = load_fact_table(
        cfg, report, "context-image-sums", "## Image layouts", 1, facts,
        "no image fact would be required to have a layout table, so only "
        "whatever tables happen to exist would be verified")
    if rows is None:
        return None
    return [fid for fid, _ in rows]


def check_context_image_sums(cfg, report, facts, guards, layouts):
    """A save-image layout table must sum to the total it declares.

    This is **doc-internal arithmetic, not doc-vs-code**, and is labelled that
    way deliberately: there is no FPU or SIMD RTL in jcore-cpu and no size
    constant in the kernel, so there is nothing to compare against. What there
    is, is a table whose rows already determine the answer -- and which was
    wrong anyway. `fpu/spec.md` §7.4 declared a 132-byte image above a field
    list summing to 136, whose own terminator row gave the end as `0x88`. The
    save sequence below it had already been bent to fit the wrong budget,
    storing FPSCR on top of FPUL with `; oops, recompute` left in the listing.

    Scans every markdown file, so a new image table is covered the day it is
    written rather than when someone remembers to register it."""
    tables = 0
    totals = {}          # owner path -> [total per table found]
    for path in cfg.markdown_files():
        try:
            body = read(path)
        except (OSError, UnicodeDecodeError):
            continue           # `check_facts` reports unreadable files
        lines = body.splitlines()
        for idx, rows in find_tables_by_header(body, IMAGE_TABLE_HEADER):
            tables += 1
            where = "%s:%d" % (cfg.rel(path), idx + 1)
            running = 0
            total = None
            for cells in rows:
                mo = IMAGE_OFFSET_RE.match(cells[0].strip())
                if not mo:
                    continue   # a prose row; not an offset
                off = int(mo.group(1), 16)
                if off != running:
                    report.fail("context-image-sums", where,
                                "row `%s` (%s) starts at 0x%02X, but the "
                                "fields above it occupy 0x%02X bytes"
                                % (cells[0].strip(), cells[2][:30], off,
                                   running))
                    running = off      # resync, so one slip is one failure
                mb = IMAGE_BYTES_RE.match(cells[1].strip())
                if mb:
                    running += int(mb.group(1))
                else:
                    # No size: this is the terminator row, and its own text
                    # states the total. That is the cell that was wrong.
                    mt = IMAGE_TOTAL_RE.search(cells[2])
                    if mt:
                        total = int(mt.group(1))
                        if total != off:
                            report.fail("context-image-sums", where,
                                        "the table ends at offset 0x%02X = %d "
                                        "bytes, but calls itself %d bytes"
                                        % (off, off, total))
            if total is None:
                report.fail("context-image-sums", where,
                            "no terminator row stating the total (a final row "
                            "whose Content reads `end (N bytes)`). Without it "
                            "the table's sum is compared against nothing.")
                continue
            # The headline above the table is a second copy of the total, and
            # it is the copy that was wrong. Check it where it exists.
            for back in range(idx - 1, max(idx - 25, -1), -1):
                mh = IMAGE_HEADING_RE.match(lines[back])
                if lines[back].startswith("#") and mh:
                    if int(mh.group(1)) != total:
                        report.fail("context-image-sums", where,
                                    "heading on line %d says %s bytes; the "
                                    "table says %d"
                                    % (back + 1, mh.group(1), total))
                    break
                if lines[back].startswith("#"):
                    break      # a heading that makes no size claim
            totals.setdefault(path, []).append(total)
            report.note("context-image-sums: %s sums to %d bytes"
                        % (where, total))
    # The part that makes this non-vacuous per FACT rather than per tree. A
    # global "at least one table exists" test is satisfied forever by the first
    # table anyone writes, which is exactly how the SIMD image came to be listed
    # as covered while having no table at all.
    # `layouts is None` now means exactly one thing -- `load_image_layouts`
    # already failed and reported -- so returning here suppresses a duplicate
    # message rather than suppressing the check. It used to mean that OR "the
    # caller omitted the argument", because the parameters were optional, and
    # an arm that switches itself off when a caller passes nothing is the
    # fail-open shape this file exists to remove. The parameters are required
    # now, so a caller with nothing to pass gets a TypeError at the call site.
    if layouts is None:
        return
    owners = {f.id: f for f in (facts or [])}
    canon = {}
    for g in (guards or []):
        fact = owners.get(g.id)
        if fact is None:
            continue
        try:
            body = read(fact.owner)
        except (OSError, UnicodeDecodeError):
            continue
        found = sorted(set(x.strip() for x in g.canonical.findall(body)))
        if found:
            canon[g.id] = found
    for fid in layouts:
        fact = owners.get(fid)
        if fact is None:
            continue
        got = totals.get(fact.owner, [])
        if not got:
            report.fail("context-image-sums", fid,
                        "%s is registered as having a save-image layout, but "
                        "carries no `%s` table. Its size is then stated only in "
                        "prose, where nothing checks that the fields add up."
                        % (cfg.rel(fact.owner), " | ".join(IMAGE_TABLE_HEADER)))
            continue
        if len(got) > 1:
            report.fail("context-image-sums", fid,
                        "%s carries %d layout tables; which one is %s is "
                        "ambiguous" % (cfg.rel(fact.owner), len(got), fid))
            continue
        want = canon.get(fid)
        if want is None:
            report.fail("context-image-sums", fid,
                        "no usable `## Value guards` row, so the table total "
                        "in %s is compared against nothing. Every image layout "
                        "needs one." % cfg.rel(fact.owner))
            continue
        if str(got[0]) not in want:
            report.fail("context-image-sums", fid,
                        "%s's layout table sums to %d bytes, but the document "
                        "states %s for this image"
                        % (cfg.rel(fact.owner), got[0], "/".join(want)))
        else:
            report.note("context-image-sums: %s layout table sums to %d, "
                        "matching the owner's stated %s"
                        % (fid, got[0], "/".join(want)))


class Waivers:
    """Waiver lookup that records which waivers were actually used, so an
    obsolete one can be failed on (--check-waivers) instead of accumulating."""

    def __init__(self, table):
        self.table = table
        self.fired = set()

    def allows(self, wid, path):
        if path in self.table.get(wid, ()):
            self.fired.add((wid, path))
            return True
        return False

    def unfired(self):
        return sorted((wid, p) for wid, paths in self.table.items()
                      for p in paths if (wid, p) not in self.fired)


# ------------------------------------------------------------- 0001 checks

# Value-SHAPED tokens. `glossary-is-value-free` scans for these rather than for
# the registry's current patterns, because the failure this rule exists to stop
# is a value going *stale* -- and a stale value matches no current pattern by
# definition. Scanning for the shape catches "272 bytes" as readily as "520".
#
# This list is the *reach* of the rule and is deliberately enumerated in 0001,
# because a shape that is absent here is a third escape and readers are entitled
# to know which ones exist.
VALUE_SHAPES = [
    ("size", re.compile(
        r"\b\d[\d,]*\s*-?\s*(?:bytes?|[KMGT]i?B|kb|kilobytes?|megabytes?"
        r"|gigabytes?)\b", re.IGNORECASE)),
    ("width", re.compile(r"\b\d+\s*-?\s*bits?\b")),
    ("address", re.compile(r"\b0[xX][0-9A-Fa-f]+\b")),
    ("bit position", re.compile(r"\bbits?\s+\d+\b")),
    ("bit range", re.compile(r"\[\s*\d+\s*:\s*\d+\s*\]")),
    ("count", re.compile(
        r"\b\d[\d,]*\s*(?:entries|entry|ways|slots?|levels?|contexts?"
        r"|registers?)\b")),
    ("frequency", re.compile(r"\b\d[\d,.]*\s*[kMGT]?Hz\b")),
    ("bare count", re.compile(r"\*\*\d{2,}\*\*")),
]

# TWO escapes, and the two lists below are written out separately ON PURPOSE.
#
# They used to be one regex gating both `glossary-is-value-free` and
# `stale-claim`. Widening it so the glossary could carry its own retirement
# notes silently exempted 119 lines across 22 files from the merge-status check
# -- a line saying "the old walker is retired" excused an unrelated "NOT MERGED"
# on the same line. The coupling was the defect, not the wording.
#
# The contents are identical today and that is a coincidence of the current
# requirements, not a constraint. DO NOT refactor them back into one shared
# literal to remove the duplication: the duplication *is* the mechanism. 0001
# argues the glossary must be able to record its own history, so somebody will
# eventually want "retired" in the glossary list -- and that edit must not be
# able to reach the merge-status list by accident. Adding a phrase means adding
# it to one list and deciding, deliberately, about the other.
#
# `scripts/test-check-doc-facts.py` asserts this is real by widening the
# glossary list in a copy of this file and checking `stale-claim` is unmoved.
#
# Both are narrow on purpose: each phrase makes the *retirement* the subject of
# the line. "retired" and "no longer" do not -- they can appear in a line whose
# subject is something else entirely, which is exactly how the hole opened.
GLOSSARY_QUOTE_PHRASES = [
    "promoted from", "previously read", "previously said",
    "formerly read", "used to read",
]
STALE_CLAIM_PHRASES = [
    "promoted from", "previously read", "previously said",
    "formerly read", "used to read",
]
GLOSSARY_QUOTE_EXEMPT = re.compile("|".join(GLOSSARY_QUOTE_PHRASES),
                                   re.IGNORECASE)
STALE_CLAIM_EXEMPT = re.compile("|".join(STALE_CLAIM_PHRASES), re.IGNORECASE)

# The THIRD separately-written copy of the same short list, for `no-stale-value`.
# 0001 and 0002 both record why these must not be one shared literal: widening
# the shared regex to `retired|no longer` for the glossary silently exempted 119
# lines across 22 files from the merge-status check, and building both from one
# constant under two names left the coupling exactly where it was. If you are
# adding a phrase, add it here and decide about the other two on purpose.
STALE_VALUE_PHRASES = [
    "promoted from", "previously read", "previously said",
    "formerly read", "used to read",
]
STALE_VALUE_EXEMPT = re.compile("|".join(STALE_VALUE_PHRASES), re.IGNORECASE)

# Declared, visible exemption for a region of the glossary. Unlike a waiver it
# lives at the point of use, so a reader sees it -- but it is NOT self-
# authorising: each fence carries an id, and that id must have its own
# `glossary-fence:<id>` row in the registry. One row therefore licenses one
# region, not the file.
FENCE_OFF = re.compile(r"<!--\s*value-free:\s*off\s*\(([A-Za-z0-9._-]+)\)\s*-->")
FENCE_OFF_UNNAMED = re.compile(r"<!--\s*value-free:\s*off\s*-->")
FENCE_ON = re.compile(r"<!--\s*value-free:\s*on\s*-->")


def check_glossary_is_value_free(cfg, report, waivers):
    """0001's structural rule. Deliberately independent of the registry and of
    whether the line links its owner: a glossary entry may *name* a term and
    point at its owner, but carrying the number at all is the defect."""
    if not os.path.exists(cfg.glossary):
        report.fail("glossary-is-value-free", cfg.rel(cfg.glossary), "missing")
        return
    fenced = False
    fence_opened_at = None
    seen_ids = set()
    try:
        body = read(cfg.glossary)
    except (OSError, UnicodeDecodeError) as exc:
        report.fail("glossary-is-value-free", cfg.rel(cfg.glossary),
                    "unreadable: %s" % exc)
        return
    for n, line in enumerate(body.splitlines(), 1):
        where = "%s:%d" % (cfg.rel(cfg.glossary), n)
        m = FENCE_OFF.search(line)
        if m or FENCE_OFF_UNNAMED.search(line):
            fence_id = m.group(1) if m else None
            if fence_id is None:
                report.fail("glossary-is-value-free", where,
                            "'value-free: off' with no id. Write "
                            "'<!-- value-free: off (some-id) -->' and add a "
                            "matching `glossary-fence:some-id` row to the "
                            "registry: one row licenses one region, not the "
                            "whole file.")
            elif fence_id in seen_ids:
                report.fail("glossary-is-value-free", where,
                            "fence id %r is used more than once; ids must be "
                            "unique so each region is separately reviewable"
                            % fence_id)
            elif not waivers.allows("glossary-fence:" + fence_id,
                                    cfg.glossary):
                report.fail("glossary-is-value-free", where,
                            "fence %r has no `glossary-fence:%s` row in the "
                            "registry's Waivers table. An exemption has to be "
                            "counted somewhere it will be reviewed."
                            % (fence_id, fence_id))
            if fence_id:
                seen_ids.add(fence_id)
            if fenced:
                report.fail("glossary-is-value-free", where,
                            "fence opened while one opened at line %d is still "
                            "open" % fence_opened_at)
            fenced = True
            fence_opened_at = n
            continue
        if FENCE_ON.search(line):
            if not fenced:
                report.fail("glossary-is-value-free", where,
                            "'value-free: on' with no matching 'off'")
            fenced = False
            fence_opened_at = None
            continue
        if fenced or GLOSSARY_QUOTE_EXEMPT.search(line):
            continue
        for kind, rx in VALUE_SHAPES:
            m = rx.search(line)
            if not m:
                continue
            report.fail("glossary-is-value-free",
                        "%s:%d" % (cfg.rel(cfg.glossary), n),
                        "carries a %s (%r). The glossary names the term and "
                        "links the owning spec; the value lives there."
                        % (kind, m.group(0).strip()))
            break
    if fenced:
        report.fail("glossary-is-value-free",
                    "%s:%d" % (cfg.rel(cfg.glossary), fence_opened_at),
                    "'value-free: off' fence is never closed, so it exempts "
                    "the rest of the file")


def check_facts(cfg, report, facts, waivers):
    corpus = {}
    for p in cfg.markdown_files():
        try:
            corpus[p] = read(p)
        except (OSError, UnicodeDecodeError) as exc:
            report.fail("readable", cfg.rel(p), "unreadable: %s" % exc)

    # 1. owner-has-fact
    for fact in facts:
        body = corpus.get(fact.owner)
        if body is None:
            report.fail("owner-has-fact", fact.id,
                        "owning document %s does not exist"
                        % cfg.rel(fact.owner))
            continue
        if not fact.regex.search(body):
            report.fail("owner-has-fact", fact.id,
                        "owner %s no longer states it (pattern %s). Either the "
                        "value changed and the registry was not updated, or "
                        "ownership moved."
                        % (cfg.rel(fact.owner), fact.pattern))

    # NB: `glossary-is-value-free` is deliberately NOT called from here. It does
    # not read the registry, so it must not be gated on the registry parsing --
    # main() runs it independently.

    # 3. restatement-is-linked
    for fact in facts:
        for path, body in sorted(corpus.items()):
            if path in (fact.owner, cfg.glossary, cfg.registry):
                continue
            if path.startswith(cfg.decisions + os.sep):
                continue
            hits = []
            for n, line in enumerate(body.splitlines(), 1):
                if fact.regex.search(line) and fact.owner not in links_on(
                        line, path):
                    hits.append(n)
            if not hits:
                continue
            if waivers.allows(fact.id, path):
                report.note("waived: %s in %s (%d line(s))"
                            % (fact.id, cfg.rel(path), len(hits)))
                continue
            shown = ", ".join(str(h) for h in hits[:5])
            more = "" if len(hits) <= 5 else " (+%d more)" % (len(hits) - 5)
            report.fail("restatement-is-linked",
                        "%s:%s%s" % (cfg.rel(path), shown, more),
                        "restates %s without linking %s on the same line"
                        % (fact.id, cfg.rel(fact.owner)))


# ------------------------------------------------------------- 0002 checks


SUPERSEDED_RE = re.compile(r"\*\*SUPERSEDED BY (.+?) — (\d{4}-\d{2}-\d{2})\.\*\*")
HISTORICAL_RE = re.compile(r"\*\*HISTORICAL (\d{4}-\d{2}-\d{2})\.?\*\*")
RESOLVED_RE = re.compile(
    r'\*\*RESOLVED (\d{4}-\d{2}-\d{2}) — ([A-Za-z0-9._-]+)@([A-Za-z0-9._/-]+): '
    r'"([^"]+)"')
RESOLVED_ARTIFACT_RE = re.compile(
    r'\*\*RESOLVED (\d{4}-\d{2}-\d{2}) — ([A-Za-z0-9._-]+)@([A-Za-z0-9._/-]+): '
    r'artifact `([^`]+)`(?: containing `([^`]+)`)?')

# Any use of the keywords, so an unstructured legacy marker stays visible.
LOOSE_RE = re.compile(r"\*\*(SUPERSEDED BY|RESOLVED|PENDING-MERGE|HISTORICAL)\b")
PENDING_RE = re.compile(
    r'\*\*PENDING-MERGE (\d{4}-\d{2}-\d{2}) — ([A-Za-z0-9._-]+) branch '
    r'([A-Za-z0-9._/-]+): "([^"]+)"\. Not on ([A-Za-z0-9._/-]+)\.')

# A prose status claim that work is implemented-but-unmerged. This is the form
# eleven notices in this tree used, and it matches none of the markers above.
STALE_CLAIM_RE = re.compile(r"\bNOT[ _-]?MERGED\b", re.IGNORECASE)


# Environment variables that redirect git AWAY from the repository named on the
# command line. `git -C <path>` does NOT override GIT_DIR: with it set, every
# command below operates on whatever repository GIT_DIR names, while still
# looking, in the output and in the code, exactly as though it operated on
# `repo`. Demonstrated on this checker: with GIT_DIR pointed elsewhere a bogus
# RESOLVED marker PASSED while 42 correct ones FAILED -- the verdicts inverted
# and nothing said so.
#
# This is reachable without anyone doing anything strange: `git rebase --exec`,
# `git bisect run`, `git submodule foreach` and every hook run with GIT_DIR
# already set, and all four are natural ways to wire a documentation gate.
GIT_ENV_OVERRIDES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
)


# The commits a marker can legitimately cite are the ones THIS PROJECT made, and
# for a kernel fork those are a rounding error next to the history they sit on:
# `origin/jcore` carries 1,462,492 commits, of which **74** are the project's.
# Searching the whole branch means searching 1.4M upstream subjects for a
# project subject -- the wrong haystack, and the reason an unrelated real commit
# ("sh: Fix build with CONFIG_UBSAN=y", Kees Cook, 2024) satisfied a RESOLVED
# marker. 445 upstream subjects already begin `sh: fix`, which is this project's
# own convention.
#
# A value here names the ref to subtract: the search becomes
# `<base>..<integration-branch>`. Absent means the whole branch is the project's
# own work, which is true of jcore-cpu (1080 commits, no duplicate subject).
#
# Verified when this landed: all 12 distinct live markers resolve to exactly one
# commit under this scoping, and none of the 7 linux ones exists upstream.
UPSTREAM_BASE = {
    "linux": "master",
}


def git_env(**extra):
    """The inherited environment with every repository redirection removed."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_OVERRIDES}
    env.update(extra)
    return env


def git(repo, *args):
    """Run git. Returns (returncode, stdout), or (None, None) if git could not
    be run at all -- the caller must distinguish those, because a non-zero exit
    is an answer and a failure to run is not."""
    try:
        out = subprocess.run(["git", "-C", repo] + list(args), env=git_env(),
                             capture_output=True, text=True, timeout=60,
                             # errors="replace" is load-bearing, not tidiness.
                             # Commit subjects are bytes, not text: the Linux
                             # history contains subjects that are not valid
                             # UTF-8, and the default strict decode raises
                             # UnicodeDecodeError *inside subprocess*, which is
                             # neither an answer nor a skip -- it is a
                             # traceback, and a traceback is not a verdict.
                             # This was invisible while the clone was shallow
                             # and appeared the moment it was not.
                             errors="replace")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None, None
    return out.returncode, out.stdout


class Repos:
    """Git lookups against submodules, cached, with honest unknowns."""

    def __init__(self, cfg, report):
        self.cfg = cfg
        self.report = report
        self._subjects = {}
        self._branches = {}
        self._shallow = {}

    def subjects(self, repo_name, branch, where):
        key = (repo_name, branch)
        if key in self._subjects:
            return self._subjects[key]
        repo = os.path.join(self.cfg.root, repo_name)
        result = None
        if not os.path.exists(os.path.join(repo, ".git")):
            self.report.skip("resolved-is-merged",
                             "%s is not checked out; cannot verify markers "
                             "naming it (first seen %s)" % (repo_name, where))
        else:
            rc, _ = git(repo, "rev-parse", "--verify", "origin/%s" % branch)
            if rc is None:
                self.report.skip("resolved-is-merged",
                                 "git could not be run for %s" % repo_name)
            elif rc != 0:
                self.report.skip("resolved-is-merged",
                                 "%s has no origin/%s (fetch it); cannot "
                                 "verify markers naming it"
                                 % (repo_name, branch))
            else:
                # Scope to the project's own commits where a base is declared;
                # see UPSTREAM_BASE. `A..B` is empty rather than an error if A
                # is missing, which would silently search nothing, so the base
                # is verified first and a missing one is a skip.
                base = UPSTREAM_BASE.get(repo_name)
                rev = "origin/%s" % branch
                if base is not None:
                    rc_b, _ = git(repo, "rev-parse", "--verify",
                                  "origin/%s" % base)
                    if rc_b is None or rc_b != 0:
                        self.report.skip(
                            "resolved-is-merged",
                            "%s has no origin/%s, which is the base its own "
                            "commits are measured against; scoping the subject "
                            "search is impossible and searching all of "
                            "origin/%s instead would be the wrong haystack"
                            % (repo_name, base, branch))
                        self._subjects[key] = None
                        return None
                    rev = "origin/%s..origin/%s" % (base, branch)
                rc, log = git(repo, "log", "--format=%s", rev)
                if rc != 0:
                    self.report.skip("resolved-is-merged",
                                     "could not read %s %s" % (repo_name, rev))
                else:
                    # split("\n"), NOT splitlines(): the latter also breaks
                    # on \v \f \x1c \x1d \x1e \x85 U+2028 U+2029, none of
                    # which git emits as a record separator. A commit whose
                    # subject contains one of them would be split into
                    # fragments, and a marker citing only the prefix would
                    # match a "subject" no commit has. Note the interaction
                    # with errors="replace" above: \xc2\x85 decodes to U+0085,
                    # which IS a splitlines() boundary.
                    #
                    # A COUNT, not a set. "Which commit does this cite?" has no
                    # answer when several share the subject, and the previous
                    # set collapsed that into "present". 19,683 subjects on
                    # linux's branch are shared by more than one commit.
                    result = collections.Counter(
                        l.strip() for l in log.split("\n") if l.strip())
                    self.report.note(
                        "resolved-is-merged: %s subject namespace is %d commit(s) "
                        "(%s)" % (repo_name, sum(result.values()), rev))
        self._subjects[key] = result
        return result

    def is_shallow(self, repo_name):
        """True / False / None, where None means 'could not find out'.

        A shallow clone answers `git log` with a TRUNCATED history and exit 0,
        so the answer looks complete and is not. But it is only *incomplete in
        one direction*: every commit the walk emits is genuinely reachable from
        the branch, because grafting removes commits and never invents them. So
        a subject that IS found is a true positive whatever the depth, and only
        a subject that is ABSENT is ambiguous -- it may be beyond the graft
        boundary, or it may not exist. Callers resolve that three ways; see
        `check_resolved_subject`.

        The earlier version skipped every marker naming a shallow repo, which
        was fail-closed but stricter than the question requires: it made
        `--strict` unusable until someone unshallowed a 6 GB repository, for
        markers whose answer was already known."""
        if repo_name in self._shallow:
            return self._shallow[repo_name]
        repo = os.path.join(self.cfg.root, repo_name)
        rc, out = git(repo, "rev-parse", "--is-shallow-repository")
        result = None if (rc is None or rc != 0) else (out.strip() == "true")
        self._shallow[repo_name] = result
        return result

    def has_path(self, repo_name, branch, path):
        repo = os.path.join(self.cfg.root, repo_name)
        rc, out = git(repo, "ls-tree", "origin/%s" % branch, "--", path)
        if rc is None or rc != 0:
            return None
        return bool(out.strip())

    def path_contains(self, repo_name, branch, path, needle):
        repo = os.path.join(self.cfg.root, repo_name)
        rc, _ = git(repo, "grep", "--fixed-strings", "-e", needle,
                    "origin/%s" % branch, "--", path)
        if rc is None:
            return None       # git could not run
        if rc == 0:
            return True       # found
        if rc == 1:
            return False      # ran fine, no match
        return None           # any other exit is a git error, not an answer

    def file_at(self, repo_name, branch, path, where,
                check="doc-matches-code"):
        """Contents of `path` on `origin/<branch>`, or None having reported.

        Three outcomes, kept apart on purpose, because collapsing them is how
        this file's other git callers have failed before:
          - the repo or its origin ref is absent  -> SKIP (a --strict failure);
            we could not look, and must not claim agreement.
          - the ref is there and the path is not  -> FAIL; the binding points at
            a file that no longer exists, which is a real defect, not an
            environment problem.
          - git itself could not run              -> SKIP, never "no match"."""
        repo = os.path.join(self.cfg.root, repo_name)
        if not os.path.exists(os.path.join(repo, ".git")):
            self.report.skip(check,
                             "%s is not checked out; cannot compare %s against "
                             "it (%s)" % (repo_name, path, where))
            return None
        rc, _ = git(repo, "rev-parse", "--verify", "origin/%s" % branch)
        if rc is None:
            self.report.skip(check,
                             "git could not be run for %s (%s)"
                             % (repo_name, where))
            return None
        if rc != 0:
            self.report.skip(check,
                             "%s has no origin/%s (fetch it); cannot compare "
                             "%s against it (%s)"
                             % (repo_name, branch, path, where))
            return None
        # The ref exists, so from here a failure is about the tree, not the
        # environment. `git show` cannot distinguish "no such path" from other
        # errors by exit status alone, so ask ls-tree first.
        rc, out = git(repo, "ls-tree", "--name-only", "origin/%s" % branch,
                      "--", path)
        if rc is None:
            self.report.skip(check,
                             "git could not be run for %s (%s)"
                             % (repo_name, where))
            return None
        if rc != 0 or not out.strip():
            self.report.fail(check, where,
                             "%s does not exist on %s origin/%s. The binding "
                             "points at a file that is not there."
                             % (path, repo_name, branch))
            return None
        rc, body = git(repo, "show", "origin/%s:%s" % (branch, path))
        if rc is None or rc != 0:
            self.report.skip(check,
                             "could not read %s from %s origin/%s (%s)"
                             % (path, repo_name, branch, where))
            return None
        return body

    def branch_exists(self, repo_name, branch, where):
        """True / False / None, where None means 'could not find out'. The
        caller must treat None as a skip -- returning it silently is how this
        check used to fail open under a broken git transport."""
        key = (repo_name, branch)
        if key in self._branches:
            return self._branches[key]
        repo = os.path.join(self.cfg.root, repo_name)
        rc, out = git(repo, "ls-remote", "--heads", "origin", branch)
        result = None if (rc is None or rc != 0) else bool(out.strip())
        if result is None:
            self.report.skip("pending-is-not-merged",
                             "cannot reach %s origin to test whether branch %s "
                             "still exists (%s)" % (repo_name, branch, where))
        self._branches[key] = result
        return result


def check_resolved_subject(cfg, report, repos, where, m):
    _, repo_name, branch, subject = m.groups()
    expected = INTEGRATION_BRANCH.get(repo_name)
    if expected is None:
        report.fail("marker-grammar", where, "unknown repo %r" % repo_name)
        return
    if branch != expected:
        report.fail("resolved-is-merged", where,
                    "RESOLVED names %s@%s; %s's integration branch is %s. Use "
                    "PENDING-MERGE for anything else."
                    % (repo_name, branch, repo_name, expected))
        return
    subjects = repos.subjects(repo_name, branch, where)
    if subjects is None:
        return                 # already reported as a skip
    seen = subjects.get(subject, 0)
    if seen > 1:
        # "Which commit does this cite?" has no answer. All of them are on the
        # branch, so the merge question is technically yes -- but the citation
        # has stopped identifying a change, which is what 0002 asks it to do.
        # Fail with the remedy rather than pass on a coin flip.
        report.fail("resolved-is-merged", where,
                    'RESOLVED cites "%s", which %d commits on %s share. The '
                    "citation no longer names one change; reword the subject "
                    "or cite the artifact instead (0002 section 3)."
                    % (subject, seen, repo_name))
        return
    if seen == 1:
        return                 # reachable from the branch: merged, at any depth
    # Absent. On a COMPLETE history that is an answer; on a truncated one it is
    # not -- the commit may sit beyond the graft boundary. Only this branch is
    # genuinely unknowable, so only this branch skips.
    shallow = repos.is_shallow(repo_name)
    if shallow is not False:
        report.skip("resolved-is-merged",
                    '%s: "%s" is not in the history available for %s, and that '
                    "history is %s. Cannot distinguish 'beyond the graft "
                    "boundary' from 'does not exist' -- run `git -C %s fetch "
                    "--unshallow --filter=tree:0`."
                    % (where, subject, repo_name,
                       "shallow" if shallow else "of unknown depth", repo_name))
        return
    report.fail("resolved-is-merged", where,
                'RESOLVED cites "%s" but it is not on %s origin/%s. Either '
                "it is not merged (use PENDING-MERGE) or the subject was "
                "reworded." % (subject, repo_name, branch))


def check_resolved_artifact(cfg, report, repos, where, m):
    # NB: never bind `path` here -- see the loop variable in check_supersede.
    _, repo_name, branch, artifact, symbol = m.groups()
    expected = INTEGRATION_BRANCH.get(repo_name)
    if expected is None:
        report.fail("marker-grammar", where, "unknown repo %r" % repo_name)
        return
    if branch != expected:
        report.fail("resolved-is-merged", where,
                    "RESOLVED names %s@%s; %s's integration branch is %s."
                    % (repo_name, branch, repo_name, expected))
        return
    if repos.subjects(repo_name, branch, where) is None:
        return  # already skipped, and the skip named the reason
    present = repos.has_path(repo_name, branch, artifact)
    if present is None:
        report.skip("resolved-is-merged",
                    "could not list %s on %s origin/%s (%s)"
                    % (artifact, repo_name, branch, where))
        return
    if not present:
        report.fail("resolved-is-merged", where,
                    "RESOLVED cites artifact %s, which is not on %s origin/%s."
                    % (artifact, repo_name, branch))
        return
    if not symbol:
        return
    found = repos.path_contains(repo_name, branch, artifact, symbol)
    if found is None:
        report.skip("resolved-is-merged",
                    "could not grep %s on %s origin/%s (%s)"
                    % (artifact, repo_name, branch, where))
    elif not found:
        report.fail("resolved-is-merged", where,
                    "RESOLVED cites artifact %s containing %r, but %s "
                    "origin/%s's copy does not contain it."
                    % (artifact, symbol, repo_name, branch))


def check_pending(cfg, report, repos, where, m):
    _, repo_name, branch, subject, stated_integration = m.groups()
    integration = INTEGRATION_BRANCH.get(repo_name)
    if integration is None:
        report.fail("marker-grammar", where, "unknown repo %r" % repo_name)
        return
    if stated_integration != integration:
        report.fail("marker-grammar", where,
                    "PENDING-MERGE says 'Not on %s'; %s's integration branch "
                    "is %s." % (stated_integration, repo_name, integration))
    subjects = repos.subjects(repo_name, integration, where)
    if subjects is not None:
        if subjects.get(subject, 0) >= 1:
            # A true positive at any depth, so this verdict needs no caveat.
            report.fail("pending-is-not-merged", where,
                        'PENDING-MERGE cites "%s", which IS on %s origin/%s. '
                        "Promote it to RESOLVED."
                        % (subject, repo_name, integration))
            return
        # Mirror image of the RESOLVED case: "absent" is what this marker
        # asserts, and on a truncated history absent is exactly what we cannot
        # confirm. The branch-existence check below is independent of depth, so
        # it still runs.
        shallow = repos.is_shallow(repo_name)
        if shallow is not False:
            report.skip("pending-is-not-merged",
                        '%s: cannot confirm "%s" is absent from %s -- its '
                        "history is %s, so absence may only mean truncation."
                        % (where, subject, repo_name,
                           "shallow" if shallow else "of unknown depth"))
    if repos.branch_exists(repo_name, branch, where) is False:
        report.fail("pending-is-not-merged", where,
                    "branch %s no longer exists on %s origin, so this marker "
                    "describes nothing: it either merged (promote to RESOLVED) "
                    "or was abandoned (delete the marker). 0002 section 4 "
                    "calls this a defect in one direction or the other."
                    % (branch, repo_name))


def check_supersede(cfg, report, waivers):
    repos = Repos(cfg, report)
    for path in cfg.markdown_files():
        # The decision records define the grammar and the registry catalogues
        # exceptions to it; neither is a spec section carrying a live marker.
        if path == cfg.registry or path.startswith(cfg.decisions + os.sep):
            continue
        try:
            body = read(path)
        except (OSError, UnicodeDecodeError) as exc:
            report.fail("readable", cfg.rel(path), "unreadable: %s" % exc)
            continue
        for n, line in enumerate(body.splitlines(), 1):
            where = "%s:%d" % (cfg.rel(path), n)

            # EVERY marker on the line, not the first. A line carrying a valid
            # marker AND a bare legacy one used to hide the second -- which is
            # exactly the shape 0002 section 4 tells people to write when they
            # promote something.
            structured = 0
            for m in RESOLVED_ARTIFACT_RE.finditer(line):
                structured += 1
                check_resolved_artifact(cfg, report, repos, where, m)
            for m in RESOLVED_RE.finditer(line):
                structured += 1
                check_resolved_subject(cfg, report, repos, where, m)
            for m in PENDING_RE.finditer(line):
                structured += 1
                check_pending(cfg, report, repos, where, m)
            structured += len(SUPERSEDED_RE.findall(line))
            structured += len(HISTORICAL_RE.findall(line))

            # A keyword occurrence that no structured marker accounted for.
            loose = [k.group(1) for k in LOOSE_RE.finditer(line)]
            if len(loose) > structured:
                if not waivers.allows("legacy-marker", path):
                    report.fail("marker-grammar", where,
                                "%d marker keyword(s) on this line, %d parse "
                                "as 0002 markers (%s)"
                                % (len(loose), structured, ", ".join(loose)))
                else:
                    report.note("waived legacy marker at %s" % where)

            # Prose "not merged" claims carry no keyword at all, so nothing
            # above sees them. Checked independently of the marker branches so
            # a marker on the same line cannot mask one.
            if (STALE_CLAIM_RE.search(line)
                    and not STALE_CLAIM_EXEMPT.search(line)):
                if waivers.allows("stale-claim", path):
                    report.note("waived prose status claim at %s" % where)
                else:
                    report.fail("stale-claim", where,
                                "prose 'not merged' status claim. Use the "
                                "PENDING-MERGE marker so it can be checked, or "
                                "promote it. Quoting a retired claim needs "
                                "'promoted from' / 'previously read' on the "
                                "line.")


# --------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None,
                    help="tree to check (default: the workspace this script "
                         "lives in). Use a fixture directory to test the "
                         "checks themselves.")
    ap.add_argument("--facts", action="store_true", help="run 0001 checks only")
    ap.add_argument("--supersede", action="store_true",
                    help="run 0002 checks only")
    ap.add_argument("--code", action="store_true",
                    help="run the B0c doc-vs-code checks only")
    ap.add_argument("--strict", action="store_true",
                    help="treat a SKIP as a failure (use this in CI)")
    ap.add_argument("--check-waivers", action="store_true",
                    help="fail on a waiver that never fired")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list waived hits")
    ap.add_argument("--list-checks", action="store_true",
                    help="print every check, what fails it, and where it is "
                         "defined, then exit")
    args = ap.parse_args()

    if args.list_checks:
        width = max(len(n) for n in CHECKS)
        for name in sorted(CHECKS):
            why, rec = CHECKS[name]
            print("%-*s  %s\n%*s  -> %s" % (width, name, why, width, "",
                                            DECISION_DOC[rec]))
        return 0

    default_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(args.root or default_root)
    if not os.path.isdir(cfg.docs):
        print("FAIL  [root] %s: no docs/ directory here" % cfg.root)
        return 1

    scoped = args.facts or args.supersede or args.code
    run_facts = args.facts or not scoped
    run_super = args.supersede or not scoped
    run_code = args.code or not scoped

    report = Report(verbose=args.verbose, strict=args.strict)
    facts, waiver_table = load_registry(cfg, report)
    waivers = Waivers(waiver_table)

    if run_facts:
        # Registry-independent, so it runs even when the registry is broken --
        # that is the whole point of scanning for value *shapes*. Gating it on
        # `facts` would have made the strongest rule in 0001 collapse along
        # with the weakest.
        check_glossary_is_value_free(cfg, report, waivers)
        if facts:
            check_facts(cfg, report, facts, waivers)
    if run_super:
        check_supersede(cfg, report, waivers)
    if run_code:
        # B0c. Registry-independent in the same sense as the glossary check:
        # `load_bindings` must run (and fail closed) even when the Registry
        # table is broken, or a malformed registry would silently take
        # doc-vs-code checking down with it while the failure it printed
        # pointed somewhere else entirely.
        repos = Repos(cfg, report)
        bindings = load_bindings(cfg, report, facts)
        guards = load_value_guards(cfg, report, facts)
        layouts = load_image_layouts(cfg, report, facts)
        if facts and bindings:
            check_code_bindings(cfg, report, repos, facts, bindings)
        if facts and guards:
            check_no_stale_value(cfg, report, facts, guards, waivers)
        check_p4_offsets(cfg, report, repos)
        check_context_image_sums(cfg, report, facts, guards, layouts)
        check_one_encoding_database(cfg, report, repos)

    if args.check_waivers:
        # Only judge waivers whose consuming check actually ran, or a scoped
        # run reports every waiver for the other half as dead.
        consumers = {"legacy-marker": run_super, "stale-claim": run_super,
                     "no-stale-value": run_code}
        for wid, path in waivers.unfired():
            if wid.startswith("glossary-fence"):
                ran = run_facts
            else:
                ran = consumers.get(wid, run_facts)
            if not ran:
                report.note("waiver %s not judged: its check did not run in "
                            "this invocation" % wid)
                continue
            report.fail("check-waivers", cfg.rel(path),
                        "waiver for %s never fired -- the restatement is gone, "
                        "or the fence it authorises is gone. Delete the row."
                        % wid)

    if report.failures:
        print("\n%d failure(s). See docs/decisions/0001-one-authority-per-fact.md"
              " and 0002-supersede-convention.md." % report.failures)
        return 1
    if report.skips:
        print("\nOK, with %d check(s) skipped -- nothing above was verified for "
              "those. Re-run with --strict to make that a failure."
              % report.skips)
    else:
        print("\nOK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
