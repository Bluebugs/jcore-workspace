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
import os
import re
import subprocess
import sys

# Max length of a registry Constant cell. See `registry-value-is-short`.
VALUE_CELL_MAX = 100

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

    def fail(self, check, where, message):
        self.failures += 1
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
    except OSError as exc:
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
VALUE_SHAPES = [
    ("size", re.compile(r"\b\d[\d,]*\s*-?\s*(?:bytes?|KB|MB|GB|KiB|MiB)\b")),
    ("width", re.compile(r"\b\d+\s*-?\s*bits?\b")),
    ("address", re.compile(r"\b0[xX][0-9A-Fa-f]{2,}\b")),
    ("bit position", re.compile(r"\bbits?\s+\d+\b")),
]

# A line may quote a value it is in the act of retiring.
QUOTATION_RE = re.compile(
    r"promoted from|previously read|previously said|formerly read|"
    r"used to read|retired|no longer",
    re.IGNORECASE)

# Declared, visible exemption for a region of the glossary. Unlike a waiver it
# lives at the point of use, so a reader sees it. Each fence still needs a
# registry row under `glossary-fence`.
FENCE_OFF = re.compile(r"<!--\s*value-free:\s*off\s*-->")
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
    for n, line in enumerate(read(cfg.glossary).splitlines(), 1):
        if FENCE_OFF.search(line):
            # A fence is an exemption, so it must be registered like one --
            # otherwise it is a waiver that hides in the file it exempts.
            if not waivers.allows("glossary-fence", cfg.glossary):
                report.fail("glossary-is-value-free",
                            "%s:%d" % (cfg.rel(cfg.glossary), n),
                            "'value-free: off' fence with no `glossary-fence` "
                            "row in the registry's Waivers table. An exemption "
                            "has to be counted somewhere it will be reviewed.")
            fenced = True
            fence_opened_at = n
            continue
        if FENCE_ON.search(line):
            if not fenced:
                report.fail("glossary-is-value-free",
                            "%s:%d" % (cfg.rel(cfg.glossary), n),
                            "'value-free: on' with no matching 'off'")
            fenced = False
            fence_opened_at = None
            continue
        if fenced or QUOTATION_RE.search(line):
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
        except OSError as exc:
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

    # 2. glossary-is-value-free -- registry-independent, see above.
    check_glossary_is_value_free(cfg, report, waivers)

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


def git(repo, *args):
    """Run git. Returns (returncode, stdout), or (None, None) if git could not
    be run at all -- the caller must distinguish those, because a non-zero exit
    is an answer and a failure to run is not."""
    try:
        out = subprocess.run(["git", "-C", repo] + list(args),
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None, None
    return out.returncode, out.stdout


class Repos:
    """Git lookups against submodules, cached, with honest unknowns."""

    def __init__(self, cfg, report):
        self.cfg = cfg
        self.report = report
        self._subjects = {}
        self._branches = {}

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
                rc, log = git(repo, "log", "--format=%s", "origin/%s" % branch)
                if rc != 0:
                    self.report.skip("resolved-is-merged",
                                     "could not read %s origin/%s"
                                     % (repo_name, branch))
                else:
                    result = set(l.strip() for l in log.splitlines()
                                 if l.strip())
        self._subjects[key] = result
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
    if subjects is not None and subject not in subjects:
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
    if subjects is not None and subject in subjects:
        report.fail("pending-is-not-merged", where,
                    'PENDING-MERGE cites "%s", which IS on %s origin/%s. '
                    "Promote it to RESOLVED."
                    % (subject, repo_name, integration))
        return
    if repos.branch_exists(repo_name, branch, where) is False:
        report.warn("pending-is-not-merged", where,
                    "branch %s no longer exists on %s origin: it either merged "
                    "(promote) or was abandoned (delete)."
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
        except OSError as exc:
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
            if STALE_CLAIM_RE.search(line) and not QUOTATION_RE.search(line):
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
    ap.add_argument("--strict", action="store_true",
                    help="treat a SKIP as a failure (use this in CI)")
    ap.add_argument("--check-waivers", action="store_true",
                    help="fail on a waiver that never fired")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list waived hits")
    args = ap.parse_args()

    default_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(args.root or default_root)
    if not os.path.isdir(cfg.docs):
        print("FAIL  [root] %s: no docs/ directory here" % cfg.root)
        return 1

    run_facts = args.facts or not args.supersede
    run_super = args.supersede or not args.facts

    report = Report(verbose=args.verbose, strict=args.strict)
    facts, waiver_table = load_registry(cfg, report)
    waivers = Waivers(waiver_table)

    if run_facts and facts:
        check_facts(cfg, report, facts, waivers)
    if run_super:
        check_supersede(cfg, report, waivers)

    if args.check_waivers:
        for wid, path in waivers.unfired():
            report.fail("check-waivers", cfg.rel(path),
                        "waiver for %s never fired -- the restatement is gone, "
                        "or the check that would have used it is not running. "
                        "Delete the row." % wid)

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
