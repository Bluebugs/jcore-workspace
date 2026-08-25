#!/usr/bin/env python3
"""Enforce the documentation-system decisions in docs/decisions/.

  0001 - one authority per fact; the glossary is an index, not an authority
  0002 - supersede, RESOLVED and PENDING-MERGE headers

Run from the workspace root:

    scripts/check-doc-facts.py            # all checks
    scripts/check-doc-facts.py --facts    # 0001 only
    scripts/check-doc-facts.py --supersede
    scripts/check-doc-facts.py -v         # also list waived hits

Exit status is 0 when every check that could be run passed, 1 otherwise.
Checks that cannot be run (a missing submodule, an unfetched remote) are
reported as SKIP and never counted as a pass.

Only Python 3 and git are required.
"""

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
REGISTRY = os.path.join(DOCS, "fact-ownership.md")
GLOSSARY = os.path.join(DOCS, "glossary.md")

# Max length of a registry Constant cell. See `registry-value-is-short`.
VALUE_CELL_MAX = 100

# Per 0002 section 2. A change is "merged" only when it is on this branch.
INTEGRATION_BRANCH = {
    "jcore-cpu": "master",
    "linux": "jcore",
    "jcore-soc": "master",
    "binutils-gdb": "jcore",
    "gcc": "master",
    "llvm-project": "main",
    "jcore-workspace": "main",
}

# ---------------------------------------------------------------- utilities


def rel(path):
    return os.path.relpath(path, ROOT)


def markdown_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(DOCS):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in sorted(filenames):
            if name.endswith(".md"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


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
    def __init__(self, verbose=False):
        self.failures = 0
        self.skips = 0
        self.verbose = verbose

    def fail(self, check, where, message):
        self.failures += 1
        print("FAIL  [%s] %s: %s" % (check, where, message))

    def warn(self, check, where, message):
        print("warn  [%s] %s: %s" % (check, where, message))

    def skip(self, check, message):
        self.skips += 1
        print("SKIP  [%s] %s" % (check, message))

    def note(self, message):
        if self.verbose:
            print("      %s" % message)


# ------------------------------------------------------------- the registry


TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")


def parse_table(body, heading):
    """Rows of the first pipe table under a `## heading` line, as cell lists."""
    lines = body.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == heading)
    except StopIteration:
        return []
    rows = []
    seen_table = False
    for line in lines[start + 1:]:
        if line.startswith("## ") and seen_table:
            break
        m = TABLE_ROW.match(line)
        if not m:
            if seen_table and line.strip() == "":
                continue
            continue
        # Split on unescaped pipes, then unescape `\|` inside each cell.
        cells = [c.replace("\x00", "|").strip()
                 for c in m.group(1).replace(r"\|", "\x00").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            seen_table = True
            continue
        if not seen_table:
            continue  # header row
        rows.append(cells)
    return rows


def unbacktick(cell):
    return cell.strip().strip("`").strip()


class Fact:
    def __init__(self, fid, value, owner_cell, pattern, source_file):
        self.id = fid
        self.value = value
        self.owner_display = owner_cell
        targets = links_on(owner_cell, source_file)
        self.owner = targets[0] if targets else None
        self.pattern = pattern
        self.regex = re.compile(pattern)


def load_registry(report):
    if not os.path.exists(REGISTRY):
        report.fail("registry", rel(REGISTRY), "missing; 0001 cannot be enforced")
        return [], {}
    body = read(REGISTRY)

    facts = []
    for cells in parse_table(body, "## Registry"):
        if len(cells) < 4:
            continue
        fid = unbacktick(cells[0])
        if not fid or fid.upper() == "UNRESOLVED":
            continue
        fact = Fact(fid, cells[1], cells[2], unbacktick(cells[3]), REGISTRY)
        if fact.owner is None:
            report.fail("registry", rel(REGISTRY),
                        "fact %s has no link to an owning document" % fid)
            continue
        # 0001: the registry states a value, it does not explain a mechanism.
        # A long cell is room for prose to drift away from the owner, and that
        # drift is not otherwise checkable -- `owner-has-fact` greps the
        # pattern, never this text. Keeping the cell short is the structural
        # substitute. See 0001 section Enforcement.
        if len(fact.value) > VALUE_CELL_MAX:
            report.fail("registry-value-is-short", fid,
                        "Constant cell is %d chars (max %d). State the value; "
                        "explanation belongs in the owning spec."
                        % (len(fact.value), VALUE_CELL_MAX))
        facts.append(fact)

    waivers = {}
    for cells in parse_table(body, "## Waivers"):
        if len(cells) < 2:
            continue
        fid = unbacktick(cells[0])
        targets = set(links_on(cells[1], REGISTRY))
        # Also accept a bare path, for files that are not linked.
        bare = unbacktick(cells[1])
        if bare and "](" not in cells[1]:
            targets.add(os.path.normpath(os.path.join(ROOT, bare)))
        # 0001 leans on the glossary being *structurally* unable to carry a
        # value. A waiver would make that a preference again, so the mechanism
        # refuses one rather than the tree merely happening not to have one.
        if GLOSSARY in targets:
            report.fail("registry", rel(REGISTRY),
                        "waiver for %s targets the glossary. "
                        "`glossary-is-value-free` does not accept waivers; "
                        "link the owner on the line instead." % fid)
            targets.discard(GLOSSARY)
        if targets:
            waivers.setdefault(fid, set()).update(targets)
    return facts, waivers


# ------------------------------------------------------------- 0001 checks


def check_facts(report, facts, waivers):
    if not facts:
        return

    corpus = {p: read(p) for p in markdown_files()}

    # 1. owner-has-fact
    for fact in facts:
        body = corpus.get(fact.owner)
        if body is None:
            report.fail("owner-has-fact", fact.id,
                        "owning document %s does not exist" % rel(fact.owner))
            continue
        if not fact.regex.search(body):
            report.fail("owner-has-fact", fact.id,
                        "owner %s no longer states it (pattern %s). Either the "
                        "value changed and the registry was not updated, or "
                        "ownership moved." % (rel(fact.owner), fact.pattern))

    # 2. glossary-is-value-free  -- the structural rule of 0001
    gloss = corpus.get(GLOSSARY)
    if gloss is None:
        report.fail("glossary-is-value-free", rel(GLOSSARY), "missing")
    else:
        for fact in facts:
            if fact.owner == GLOSSARY:
                report.fail("glossary-is-value-free", fact.id,
                            "the glossary may not own a normative value")
                continue
            if GLOSSARY in waivers.get(fact.id, ()):
                report.note("waived: %s in glossary" % fact.id)
                continue
            for n, line in enumerate(gloss.splitlines(), 1):
                if not fact.regex.search(line):
                    continue
                # Naming the term and linking its owner is exactly what a
                # glossary is for; carrying the value is not.
                if fact.owner in links_on(line, GLOSSARY):
                    continue
                report.fail("glossary-is-value-free",
                            "%s:%d" % (rel(GLOSSARY), n),
                            "restates %s (%s) without linking %s on the same "
                            "line. The glossary names the owner and links; it "
                            "does not carry the value."
                            % (fact.id, fact.value, rel(fact.owner)))
                break

    # 3. restatement-is-linked
    for fact in facts:
        waived = waivers.get(fact.id, set())
        for path, body in corpus.items():
            if path == fact.owner or path == GLOSSARY or path == REGISTRY:
                continue
            if path.startswith(os.path.join(DOCS, "decisions")):
                continue
            for n, line in enumerate(body.splitlines(), 1):
                if not fact.regex.search(line):
                    continue
                if fact.owner in links_on(line, path):
                    continue
                if path in waived:
                    report.note("waived: %s in %s:%d" % (fact.id, rel(path), n))
                    break
                report.fail("restatement-is-linked", "%s:%d" % (rel(path), n),
                            "restates %s without linking %s on the same line"
                            % (fact.id, rel(fact.owner)))
                break


# ------------------------------------------------------------- 0002 checks


SUPERSEDED_RE = re.compile(r"\*\*SUPERSEDED BY (.+?) — (\d{4}-\d{2}-\d{2})\.\*\*")
HISTORICAL_RE = re.compile(r"\*\*HISTORICAL (\d{4}-\d{2}-\d{2})\.?\*\*")
RESOLVED_RE = re.compile(
    r'\*\*RESOLVED (\d{4}-\d{2}-\d{2}) — ([A-Za-z0-9._-]+)@([A-Za-z0-9._/-]+): '
    r'"([^"]+)"')
# Fallback form for a change a rebase left with no naming commit on the
# integration branch: cite the artifact instead. See 0002 section 3.
RESOLVED_ARTIFACT_RE = re.compile(
    r'\*\*RESOLVED (\d{4}-\d{2}-\d{2}) — ([A-Za-z0-9._-]+)@([A-Za-z0-9._/-]+): '
    r'artifact `([^`]+)`(?: containing `([^`]+)`)?')

# A prose status claim that work is implemented-but-unmerged. This is the form
# eleven notices in this tree used, and it matches none of the markers above --
# see 0002 section Enforcement. Spans lines in practice ("IMPLEMENTED on\n
# branch X, NOT MERGED"), so the trailing half is what is matched.
STALE_CLAIM_RE = re.compile(r"\bNOT[ _-]?MERGED\b", re.IGNORECASE)
# ... unless the line is quoting a claim it has just retired.
QUOTATION_RE = re.compile(
    r"promoted from|previously read|previously said|formerly read|used to read",
    re.IGNORECASE)
PENDING_RE = re.compile(
    r'\*\*PENDING-MERGE (\d{4}-\d{2}-\d{2}) — ([A-Za-z0-9._-]+) branch '
    r'([A-Za-z0-9._/-]+): "([^"]+)"')

# Any use of the bare keywords, so unstructured legacy markers are visible.
LOOSE_RE = re.compile(r"\*\*(SUPERSEDED BY|RESOLVED|PENDING-MERGE|HISTORICAL)\b")


def git(repo, *args):
    try:
        out = subprocess.run(["git", "-C", repo] + list(args),
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


_subject_cache = {}


def subjects_on(repo_name, branch, report):
    """Set of commit subjects on <repo>/origin/<branch>, or None if unknowable."""
    key = (repo_name, branch)
    if key in _subject_cache:
        return _subject_cache[key]
    repo = os.path.join(ROOT, repo_name)
    result = None
    if not os.path.isdir(os.path.join(repo, ".git")) and not os.path.exists(
            os.path.join(repo, ".git")):
        report.skip("supersede", "%s is not checked out; cannot verify markers "
                                 "naming it" % repo_name)
    elif git(repo, "rev-parse", "--verify", "origin/%s" % branch) is None:
        report.skip("supersede", "%s has no origin/%s (fetch it); cannot verify "
                                 "markers naming it" % (repo_name, branch))
    else:
        log = git(repo, "log", "--format=%s", "origin/%s" % branch)
        if log is None:
            report.skip("supersede", "could not read %s origin/%s"
                        % (repo_name, branch))
        else:
            result = set(l.strip() for l in log.splitlines() if l.strip())
    _subject_cache[key] = result
    return result


def branch_exists(repo_name, branch):
    repo = os.path.join(ROOT, repo_name)
    out = git(repo, "ls-remote", "--heads", "origin", branch)
    if out is None:
        return None
    return bool(out.strip())


def check_supersede(report, waived_files):
    for path in markdown_files():
        # The decision records define the grammar and the registry catalogues
        # exceptions to it; neither is a spec section carrying a live marker.
        if path.startswith(os.path.join(DOCS, "decisions")) or path == REGISTRY:
            continue
        for n, line in enumerate(read(path).splitlines(), 1):
            where = "%s:%d" % (rel(path), n)
            loose = LOOSE_RE.search(line)

            m = RESOLVED_ARTIFACT_RE.search(line)
            if m:
                # NB: do not bind `path` here -- it is the loop variable naming
                # the file being scanned, and shadowing it misattributes every
                # later marker in the file and drops its waiver lookup.
                _, repo_name, branch, artifact, symbol = m.groups()
                expected = INTEGRATION_BRANCH.get(repo_name)
                if expected is None:
                    report.fail("marker-grammar", where,
                                "unknown repo %r" % repo_name)
                elif branch != expected:
                    report.fail("resolved-is-merged", where,
                                "RESOLVED names %s@%s; %s's integration branch "
                                "is %s." % (repo_name, branch, repo_name,
                                            expected))
                elif subjects_on(repo_name, branch, report) is not None:
                    repo = os.path.join(ROOT, repo_name)
                    listing = git(repo, "ls-tree", "origin/%s" % branch, "--",
                                  artifact)
                    if not (listing or "").strip():
                        report.fail("resolved-is-merged", where,
                                    "RESOLVED cites artifact %s, which is not "
                                    "on %s origin/%s."
                                    % (artifact, repo_name, branch))
                    elif symbol and git(repo, "grep", "-q", "--fixed-strings",
                                        "-e", symbol, "origin/%s" % branch,
                                        "--", artifact) is None:
                        report.fail("resolved-is-merged", where,
                                    "RESOLVED cites artifact %s containing %r, "
                                    "but %s origin/%s's copy does not contain "
                                    "it." % (artifact, symbol, repo_name,
                                             branch))
                continue

            m = RESOLVED_RE.search(line)
            if m:
                _, repo_name, branch, subject = m.groups()
                expected = INTEGRATION_BRANCH.get(repo_name)
                if expected is None:
                    report.fail("marker-grammar", where,
                                "unknown repo %r" % repo_name)
                elif branch != expected:
                    report.fail("resolved-is-merged", where,
                                "RESOLVED names %s@%s; %s's integration branch "
                                "is %s. Use PENDING-MERGE for anything else."
                                % (repo_name, branch, repo_name, expected))
                else:
                    subjects = subjects_on(repo_name, branch, report)
                    if subjects is not None and subject not in subjects:
                        report.fail("resolved-is-merged", where,
                                    'RESOLVED cites "%s" but it is not on '
                                    "%s origin/%s. Either it is not merged "
                                    "(use PENDING-MERGE) or the subject was "
                                    "reworded." % (subject, repo_name, branch))
                continue

            m = PENDING_RE.search(line)
            if m:
                _, repo_name, branch, subject = m.groups()
                integration = INTEGRATION_BRANCH.get(repo_name)
                if integration is None:
                    report.fail("marker-grammar", where,
                                "unknown repo %r" % repo_name)
                    continue
                subjects = subjects_on(repo_name, integration, report)
                if subjects is not None and subject in subjects:
                    report.fail("pending-is-not-merged", where,
                                'PENDING-MERGE cites "%s", which IS on %s '
                                "origin/%s. Promote it to RESOLVED."
                                % (subject, repo_name, integration))
                elif branch_exists(repo_name, branch) is False:
                    report.warn("pending-is-not-merged", where,
                                "branch %s no longer exists on %s origin: it "
                                "either merged (promote) or was abandoned "
                                "(delete)." % (branch, repo_name))
                continue

            if SUPERSEDED_RE.search(line) or HISTORICAL_RE.search(line):
                continue

            if loose:
                if path in waived_files:
                    report.note("waived legacy marker at %s" % where)
                    continue
                report.fail("marker-grammar", where,
                            "%r marker does not match the 0002 grammar"
                            % loose.group(1))
                continue

            # Prose "NOT MERGED" claims. These carry no marker at all, so they
            # are invisible to everything above -- which is exactly how eleven
            # of them outlived their merges.
            if STALE_CLAIM_RE.search(line) and not QUOTATION_RE.search(line):
                if path in waived_files:
                    report.note("waived prose status claim at %s" % where)
                    continue
                report.fail("stale-claim", where,
                            "prose 'not merged' status claim. Use the "
                            "PENDING-MERGE marker so it can be checked, or "
                            "promote it. Quoting a retired claim needs "
                            "'promoted from' / 'previously read' on the line.")


# --------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facts", action="store_true", help="run 0001 checks only")
    ap.add_argument("--supersede", action="store_true",
                    help="run 0002 checks only")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list waived hits")
    args = ap.parse_args()

    run_facts = args.facts or not args.supersede
    run_super = args.supersede or not args.facts

    report = Report(verbose=args.verbose)

    facts, waivers = load_registry(report)
    legacy = set(waivers.get("legacy-marker", ()))

    if run_facts:
        check_facts(report, facts, waivers)
    if run_super:
        check_supersede(report, legacy)

    if report.failures:
        print("\n%d failure(s). See docs/decisions/0001-one-authority-per-fact.md "
              "and 0002-supersede-convention.md." % report.failures)
        return 1
    if report.skips:
        print("\nOK, with %d check(s) skipped (see SKIP lines above)."
              % report.skips)
    else:
        print("\nOK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
