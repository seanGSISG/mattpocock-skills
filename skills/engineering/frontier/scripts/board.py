#!/usr/bin/env python3
"""Frontier board — a read-only local web view of GitHub issues, ordered by dependency.

What it is
----------
A single-file, standard-library-only web server that answers one question:
*what can I work on right now?*  It reads issues from GitHub via the `gh` CLI,
reads their dependency edges (`blocked_by`), reads an optional work-order file
that groups issues into **batches** (sets of issues that should land as one PR),
and lays the result out in dependency layers.  Layer 0 is the **frontier** —
everything with no open blockers.

A batch is a single node in the graph.  Members of a batch are never offered
independently, because the plan says they ship together.

Read-only guarantee
-------------------
**This program never mutates GitHub.**  Every `gh` invocation in this file is a
read: `gh repo view`, `gh issue list`, and `gh api` GETs.  There is no code path
that calls `gh issue edit`, `gh issue close`, `gh pr ...`, or `gh api` with
`--method POST/PATCH/PUT/DELETE`.  The HTTP server exposes only `GET` handlers
and binds to `127.0.0.1` exclusively — never `0.0.0.0`.  Treat any change that
weakens either property as a bug.

Usage
-----
    python3 board.py [--repo OWNER/NAME] [--work-order PATH] [--port 7373] [--no-open]

`--repo` is optional; when omitted `gh` infers the repository from the current
directory's git remote.  `--work-order` defaults to `docs/agents/work-order.md`
relative to the current directory; a missing file is not an error — the board
then shows every issue as its own node and says so in a banner.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

GH_TIMEOUT = 45
CACHE_TTL_SECONDS = 10.0
MAX_WORKERS = 8
ISSUE_LIMIT = 300
PRIORITY_ORDER = {"P1": 1, "P2": 2, "P3": 3}


# --------------------------------------------------------------------------- models


@dataclass
class Issue:
    """One GitHub issue, flattened to the fields the board renders."""

    number: int
    title: str
    state: str
    url: str
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)


@dataclass
class Batch:
    """One `###` block parsed out of the work-order file."""

    id: str
    title: str
    issue_numbers: list[int] = field(default_factory=list)
    gate: str | None = None
    gate_note: str | None = None
    blocked_by: list[int] = field(default_factory=list)
    why: str | None = None


@dataclass
class Node:
    """A unit of takeable work: either a whole batch, or a single loose issue."""

    id: str
    kind: str  # "batch" | "issue"
    title: str
    gate: str | None
    gate_note: str | None  # prose that followed the gate command, e.g. "does not exist yet"
    why: str | None
    priority: str | None
    areas: list[str]
    state: str  # "open" | "closed"
    assignees: list[str]
    blocked_by: list[dict]
    issues: list[Issue]


# --------------------------------------------------------------------------- gh


class GhError(RuntimeError):
    """Raised only for startup preflight failures, never during a request."""


def run_gh(args: list[str]) -> tuple[bool, str, str]:
    """Run a read-only `gh` command. Returns (ok, stdout, error-message)."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT,
        )
    except FileNotFoundError:
        return False, "", "`gh` is not on PATH"
    except subprocess.TimeoutExpired:
        return False, "", f"gh {' '.join(args)} timed out after {GH_TIMEOUT}s"
    except OSError as exc:  # pragma: no cover - environment dependent
        return False, "", f"gh {' '.join(args)} failed: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, "", f"gh {' '.join(args)}: {detail[0] if detail else 'exit %d' % proc.returncode}"
    return True, proc.stdout, ""


def run_gh_json(args: list[str]) -> tuple[object | None, str]:
    """Run a read-only `gh` command expected to emit JSON. Returns (value, error)."""
    ok, out, err = run_gh(args)
    if not ok:
        return None, err
    text = out.strip()
    if not text:
        return None, ""
    try:
        return json.loads(text), ""
    except json.JSONDecodeError as exc:
        return None, f"gh {' '.join(args)}: bad JSON ({exc})"


def preflight() -> None:
    """Fail loudly and legibly if `gh` is missing or unauthenticated."""
    ok, _, err = run_gh(["--version"])
    if not ok:
        raise GhError(
            f"{err}\nInstall the GitHub CLI (https://cli.github.com) and run `gh auth login`."
        )
    ok, _, err = run_gh(["auth", "status"])
    if not ok:
        raise GhError(f"gh is not authenticated ({err}).\nRun `gh auth login` and try again.")


def resolve_repo(repo: str | None) -> tuple[str | None, str]:
    """Resolve OWNER/NAME once, honouring --repo. Returns (name_with_owner, error)."""
    args = ["repo", "view"]
    if repo:
        args.append(repo)
    args += ["--json", "nameWithOwner", "--jq", ".nameWithOwner"]
    ok, out, err = run_gh(args)
    if not ok:
        return None, err
    name = out.strip()
    return (name or None), ("" if name else "could not determine the repository")


def repo_flag(repo: str | None) -> list[str]:
    """`--repo OWNER/NAME`, or nothing at all so gh infers from the git remote."""
    return ["--repo", repo] if repo else []


# --------------------------------------------------------------------------- gh: issues


def _names(items: object, key: str) -> list[str]:
    """Pull `key` out of gh's list-of-objects fields, tolerating anything odd."""
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get(key), str):
            out.append(item[key])
    return out


def fetch_issues(repo: str | None) -> tuple[list[Issue], list[str]]:
    """One `gh issue list` call for every issue, open and closed."""
    args = [
        "issue", "list",
        "--state", "all",
        "--limit", str(ISSUE_LIMIT),
        "--json", "number,title,labels,state,assignees,url",
        *repo_flag(repo),
    ]
    raw, err = run_gh_json(args)
    if err:
        return [], [f"could not list issues — {err}"]
    if not isinstance(raw, list):
        return [], ["could not list issues — unexpected response shape"]
    issues = [
        Issue(
            number=int(row.get("number", 0)),
            title=str(row.get("title", "")),
            state=str(row.get("state", "")).lower() or "open",
            url=str(row.get("url", "")),
            labels=_names(row.get("labels"), "name"),
            assignees=_names(row.get("assignees"), "login"),
        )
        for row in raw
        if isinstance(row, dict) and row.get("number")
    ]
    return issues, []


def fetch_blocked_by(name_with_owner: str, number: int) -> tuple[list[dict], list[str]]:
    """Read one issue's blockers. Degrades to 'no blockers' on any failure.

    `/dependencies/blocked_by` is the ONLY source of truth here. Do not
    "optimize" this by gating the call on `.issue_dependencies_summary` —
    that field is eventually consistent and lags writes by roughly 20
    seconds. Measured against a real edge written to this repo:

        t+0s   POST .../dependencies/blocked_by  -> 204
        t+0s   .issue_dependencies_summary       -> {"blocked_by": 0}  WRONG
        t+0s   .../dependencies/blocked_by       -> [{"number": 180}]  correct
        t+12s  .issue_dependencies_summary       -> {"blocked_by": 0}  still wrong
        t+~20s .issue_dependencies_summary       -> {"blocked_by": 1}  caught up

    The lag window is exactly when someone opens the board after wiring
    edges, and trusting the summary renders a blocked node as takeable with
    no visible sign anything is wrong. The list endpoint is the same one
    call per open issue, so reading it directly costs nothing extra.
    """
    listing, err = run_gh_json(
        [
            "api",
            f"repos/{name_with_owner}/issues/{number}/dependencies/blocked_by",
            "--jq", "[.[] | {number, state, title}]",
        ]
    )
    if err:
        # Older GitHub Enterprise has no such endpoint (404). Degrade to
        # "no blockers" rather than killing the board, but say so.
        return [], [f"#{number}: blockers unavailable — {err}"]
    if not isinstance(listing, list):
        return [], []
    return [row for row in listing if isinstance(row, dict) and row.get("number")], []


def fetch_all_blockers(
    name_with_owner: str | None, issues: list[Issue]
) -> tuple[dict[int, list[dict]], list[str]]:
    """Fan out the per-issue dependency reads across a small thread pool."""
    if not name_with_owner:
        return {}, ["dependency edges skipped — repository could not be resolved"]
    open_numbers = [i.number for i in issues if i.state == "open"]
    if not open_numbers:
        return {}, []

    blockers: dict[int, list[dict]] = {}
    warnings: list[str] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = pool.map(lambda n: (n, fetch_blocked_by(name_with_owner, n)), open_numbers)
        for number, (rows, warns) in results:
            if rows:
                blockers[number] = rows
            warnings.extend(warns)
    return blockers, collapse_warnings(warnings)


def collapse_warnings(warnings: list[str], limit: int = 3) -> list[str]:
    """A repo without the dependencies endpoint fails on every issue at once.

    Listing all of them buries any other warning, so past `limit` we say it
    once — loudly enough that nobody mistakes it for "no dependencies".
    """
    if len(warnings) <= limit:
        return warnings
    return [
        f"blockers could not be read for {len(warnings)} issues — dependency edges "
        "are NOT being shown; this board cannot tell you what is blocked",
        *warnings[:limit],
        f"… and {len(warnings) - limit} more",
    ]


# --------------------------------------------------------------------------- work order


BATCHES_HEADING = re.compile(r"^##\s+batches\s*$", re.IGNORECASE)
LEVEL2_HEADING = re.compile(r"^##(?!#)\s*")
LEVEL3_HEADING = re.compile(r"^###\s+(.*\S)\s*$")
# Tolerates `- **Issues:** …`, `- **Issues**: …` and bare `- Issues: …`; the
# colon may sit inside or outside the bold markers.
FIELD_LINE = re.compile(
    r"^\s*[-*]\s*\*{0,2}\s*(issues|gate|blocked by|why)\s*(?::\s*\*{0,2}|\*{0,2}\s*:)\s*(.*)$",
    re.IGNORECASE,
)
ISSUE_REF = re.compile(r"#(\d+)")
BACKTICK_SPAN = re.compile(r"`([^`]+)`")


def _batches_section(text: str) -> list[str]:
    """The lines under `## Batches`, stopping at the next level-2 heading."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if BATCHES_HEADING.match(line)), None)
    if start is None:
        return []
    body: list[str] = []
    for line in lines[start + 1 :]:
        if LEVEL2_HEADING.match(line):
            break
        body.append(line)
    return body


def _split_heading(heading: str) -> tuple[str, str]:
    """`id — title`, with ` - ` as a fallback separator. No separator: id == title."""
    for sep in (" — ", " – ", " - "):
        if sep in heading:
            left, right = heading.split(sep, 1)
            return left.strip(), right.strip()
    return heading.strip(), heading.strip()


def _field_blocks(lines: list[str]) -> list[tuple[str, str]]:
    """Collect (label, value) pairs, folding wrapped continuation lines into the value."""
    blocks: list[tuple[str, list[str]]] = []
    for line in lines:
        match = FIELD_LINE.match(line)
        if match:
            blocks.append((match.group(1).lower(), [match.group(2).strip()]))
        elif blocks and line.strip() and not line.lstrip().startswith(("-", "*", "#")):
            blocks[-1][1].append(line.strip())
        elif not line.strip():
            continue
    return [(label, " ".join(part for part in parts if part).strip()) for label, parts in blocks]


def parse_gate(value: str) -> tuple[str | None, str | None]:
    """Split a `Gate:` value into the command and any prose wrapped around it.

    People write the command and then a caveat on the same line — "`cd bot &&
    npm test` — does not exist yet". Stripping the outer backticks off the
    whole value only works when the value is exactly one backticked span, and
    otherwise yields a command that is broken but still has a copy button
    beside it. So: the FIRST backticked span is the gate, everything else
    becomes the note. With no backticks at all, the whole value is the gate.
    """
    match = BACKTICK_SPAN.search(value)
    if not match:
        # No balanced span, so any backtick here is stray punctuation.
        return (value.strip().strip("`").strip() or None), None
    gate = match.group(1).strip() or None
    leftover = f"{value[: match.start()]} {value[match.end() :]}"
    leftover = re.sub(r"\s+", " ", leftover).strip().lstrip("—–-").strip()
    return gate, (leftover or None)


def _parse_batch(heading: str, lines: list[str]) -> Batch:
    """Turn one `###` block into a Batch."""
    batch_id, title = _split_heading(heading)
    batch = Batch(id=batch_id, title=title)
    for label, value in _field_blocks(lines):
        if label == "issues":
            batch.issue_numbers = [int(n) for n in ISSUE_REF.findall(value)]
        elif label == "gate":
            batch.gate, batch.gate_note = parse_gate(value)
        elif label == "blocked by":
            batch.blocked_by = [int(n) for n in ISSUE_REF.findall(value)]
        elif label == "why":
            batch.why = value or None
    return batch


def parse_work_order(path: Path) -> tuple[list[Batch], bool, list[str]]:
    """Parse the work-order file. A missing file yields ([], False, []) — not an error."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], False, []
    except OSError as exc:
        return [], False, [f"could not read {path} — {exc}"]

    batches: list[Batch] = []
    heading: str | None = None
    buffer: list[str] = []
    for line in _batches_section(text):
        match = LEVEL3_HEADING.match(line)
        if match:
            if heading is not None:
                batches.append(_parse_batch(heading, buffer))
            heading, buffer = match.group(1), []
        elif heading is not None:
            buffer.append(line)
    if heading is not None:
        batches.append(_parse_batch(heading, buffer))
    return dedupe_batches(batches)


def dedupe_batches(batches: list[Batch]) -> tuple[list[Batch], bool, list[str]]:
    """An issue may belong to one batch only. First mention wins; the rest are warnings."""
    warnings: list[str] = []
    seen: dict[int, str] = {}
    for batch in batches:
        kept: list[int] = []
        for number in batch.issue_numbers:
            owner = seen.get(number)
            if owner is None:
                seen[number] = batch.id
                kept.append(number)
            else:
                warnings.append(
                    f"#{number} is listed in both `{owner}` and `{batch.id}` — kept in `{owner}`"
                )
        batch.issue_numbers = kept
    return batches, True, warnings


# --------------------------------------------------------------------------- graph


def priority_of(labels: list[str]) -> str | None:
    """The highest-urgency P-label on an issue, if any."""
    found = [label.upper() for label in labels if label.upper() in PRIORITY_ORDER]
    return min(found, key=lambda p: PRIORITY_ORDER[p]) if found else None


def areas_of(labels: list[str]) -> list[str]:
    return [label for label in labels if label.lower().startswith("area:")]


def _best_priority(values: list[str | None]) -> str | None:
    present = [v for v in values if v]
    return min(present, key=lambda p: PRIORITY_ORDER.get(p, 99)) if present else None


def _batch_node(batch: Batch, members: list[Issue]) -> Node:
    """A batch is ONE node — its members are never offered independently."""
    labels = [label for issue in members for label in issue.labels]
    return Node(
        id=f"batch:{batch.id}",
        kind="batch",
        title=batch.title,
        gate=batch.gate,
        gate_note=batch.gate_note,
        why=batch.why,
        priority=_best_priority([priority_of(issue.labels) for issue in members]),
        areas=sorted(set(areas_of(labels))),
        state="closed" if members and all(i.state == "closed" for i in members) else "open",
        assignees=sorted({a for issue in members for a in issue.assignees}),
        blocked_by=[],
        issues=members,
    )


def _issue_node(issue: Issue) -> Node:
    return Node(
        id=f"issue:{issue.number}",
        kind="issue",
        title=issue.title,
        gate=None,
        gate_note=None,
        why=None,
        priority=priority_of(issue.labels),
        areas=areas_of(issue.labels),
        state=issue.state,
        assignees=list(issue.assignees),
        blocked_by=[],
        issues=[issue],
    )


def build_nodes(
    issues: list[Issue], batches: list[Batch]
) -> tuple[list[Node], dict[int, str], list[str]]:
    """Batch nodes first, then every issue that no batch claimed."""
    by_number = {issue.number: issue for issue in issues}
    warnings: list[str] = []
    nodes: list[Node] = []
    issue_to_node: dict[int, str] = {}

    for batch in batches:
        members = [by_number[n] for n in batch.issue_numbers if n in by_number]
        missing = [n for n in batch.issue_numbers if n not in by_number]
        for number in missing:
            warnings.append(f"batch `{batch.id}` lists #{number}, which is not in this repository")
        if not members:
            warnings.append(f"batch `{batch.id}` has no resolvable issues — skipped")
            continue
        node = _batch_node(batch, members)
        nodes.append(node)
        for member in members:
            issue_to_node[member.number] = node.id

    for issue in issues:
        if issue.number not in issue_to_node:
            node = _issue_node(issue)
            nodes.append(node)
            issue_to_node[issue.number] = node.id
    return nodes, issue_to_node, warnings


def _blocker_refs(
    batches: list[Batch], by_number: dict[int, Issue], blockers: dict[int, list[dict]]
) -> dict[str, list[dict]]:
    """Every blocker reference, keyed by node id: member-level edges plus batch-level ones."""
    refs: dict[str, list[dict]] = {}
    batch_of: dict[int, str] = {}
    for batch in batches:
        for number in batch.issue_numbers:
            batch_of[number] = f"batch:{batch.id}"
    for number, rows in blockers.items():
        if by_number.get(number) and by_number[number].state != "open":
            continue
        node_id = batch_of.get(number, f"issue:{number}")
        refs.setdefault(node_id, []).extend(rows)
    for batch in batches:
        for number in batch.blocked_by:
            blocker = by_number.get(number)
            refs.setdefault(f"batch:{batch.id}", []).append(
                {
                    "number": number,
                    "state": blocker.state if blocker else "open",
                    "title": blocker.title if blocker else "",
                }
            )
    return refs


def build_edges(
    nodes: list[Node],
    issue_to_node: dict[int, str],
    by_number: dict[int, Issue],
    batches: list[Batch],
    blockers: dict[int, list[dict]],
) -> tuple[dict[str, set[str]], set[str], list[str]]:
    """Wire open blockers into node→blocker edges. Returns (edges, phantom ids, warnings)."""
    edges: dict[str, set[str]] = {node.id: set() for node in nodes}
    node_by_id = {node.id: node for node in nodes}
    phantoms: set[str] = set()
    warnings: list[str] = []

    for node_id, rows in _blocker_refs(batches, by_number, blockers).items():
        node = node_by_id.get(node_id)
        if node is None or node.state == "closed":
            continue
        for row in rows:
            number = int(row.get("number") or 0)
            if not number or str(row.get("state", "open")).lower() != "open":
                continue  # a closed blocker is satisfied
            target = issue_to_node.get(number)
            if target is None:
                target = f"issue:{number}"
                phantoms.add(target)
                warnings.append(f"#{number} blocks {node_id} but is not in this issue list")
            elif target == node_id:
                warnings.append(
                    f"{node_id}: #{number} blocks a sibling in the same batch — "
                    "treated as intra-batch ordering, not a graph edge"
                )
                continue
            edges[node_id].add(target)
            _record_blocked_by(node, target, number, by_number)
    return edges, phantoms, warnings


def _record_blocked_by(node: Node, target: str, number: int, by_number: dict[int, Issue]) -> None:
    """Append a display-level blocker reference, de-duplicated."""
    if any(entry["number"] == number for entry in node.blocked_by):
        return
    blocker = by_number.get(number)
    node.blocked_by.append(
        {"id": target, "number": number, "title": blocker.title if blocker else ""}
    )


# --------------------------------------------------------------------------- layering


def sort_key(node: Node) -> tuple[int, int, int]:
    """Priority first, then batches before singles, then ascending issue number."""
    priority = PRIORITY_ORDER.get(node.priority or "", 99)
    kind = 0 if node.kind == "batch" else 1
    number = min((issue.number for issue in node.issues), default=10**9)
    return priority, kind, number


def kahn_layers(
    open_ids: set[str], edges: dict[str, set[str]]
) -> tuple[list[list[str]], set[str]]:
    """Layer 0 = no open blockers. Returns (layers, node ids left over in cycles)."""
    pending = {nid: {b for b in edges.get(nid, set()) if b in open_ids} for nid in open_ids}
    layers: list[list[str]] = []
    placed: set[str] = set()
    while pending:
        ready = [nid for nid, blocks in pending.items() if not (blocks - placed)]
        if not ready:
            break  # everything that remains sits in a cycle
        layers.append(ready)
        placed.update(ready)
        for nid in ready:
            pending.pop(nid)
    return layers, set(pending)


def find_cycles(remaining: set[str], edges: dict[str, set[str]]) -> list[dict]:
    """Group the leftover nodes into connected components and list their edges."""
    adjacency: dict[str, set[str]] = {nid: set() for nid in remaining}
    for nid in remaining:
        for blocker in edges.get(nid, set()) & remaining:
            adjacency[nid].add(blocker)
            adjacency[blocker].add(nid)

    seen: set[str] = set()
    groups: list[dict] = []
    for start in sorted(remaining):
        if start in seen:
            continue
        stack, component = [start], []
        seen.add(start)
        while stack:
            nid = stack.pop()
            component.append(nid)
            for neighbour in adjacency[nid] - seen:
                seen.add(neighbour)
                stack.append(neighbour)
        members = sorted(component)
        group_edges = [[nid, b] for nid in members for b in sorted(edges.get(nid, set()) & remaining)]
        groups.append({"nodes": members, "edges": group_edges})
    return groups


def layer_open_nodes(
    nodes: list[Node], edges: dict[str, set[str]], phantoms: set[str]
) -> tuple[list[list[Node]], list[dict]]:
    """Run Kahn over open nodes, drop phantom placeholders, and surface any cycles."""
    node_by_id = {node.id: node for node in nodes}
    open_ids = {node.id for node in nodes if node.state == "open"} | phantoms
    raw_layers, remaining = kahn_layers(open_ids, edges)

    layers: list[list[Node]] = []
    for ids in raw_layers:
        real = [node_by_id[nid] for nid in ids if nid in node_by_id]
        if real:
            layers.append(sorted(real, key=sort_key))

    cycles = find_cycles(remaining, edges) if remaining else []
    stuck = [node_by_id[nid] for nid in sorted(remaining) if nid in node_by_id]
    if stuck:
        layers.append(sorted(stuck, key=sort_key))
    return layers, cycles


# --------------------------------------------------------------------------- payload


def assemble(repo_arg: str | None, work_order: Path) -> dict:
    """Gather everything and shape it into the /api/board payload."""
    warnings: list[str] = []
    name_with_owner, err = resolve_repo(repo_arg)
    if err:
        warnings.append(f"repository lookup failed — {err}")

    issues, issue_warnings = fetch_issues(repo_arg)
    warnings.extend(issue_warnings)

    batches, found, order_warnings = parse_work_order(work_order)
    warnings.extend(order_warnings)

    blockers, blocker_warnings = fetch_all_blockers(name_with_owner, issues)
    warnings.extend(blocker_warnings)

    nodes, issue_to_node, node_warnings = build_nodes(issues, batches)
    warnings.extend(node_warnings)

    by_number = {issue.number: issue for issue in issues}
    edges, phantoms, edge_warnings = build_edges(
        nodes, issue_to_node, by_number, batches, blockers
    )
    warnings.extend(edge_warnings)

    layers, cycles = layer_open_nodes(nodes, edges, phantoms)
    done = sorted(
        (node for node in nodes if node.state == "closed"),
        key=lambda n: -max((i.number for i in n.issues), default=0),
    )
    now = time.time()
    return {
        "repo": name_with_owner or (repo_arg or "(unknown)"),
        "fetched_at": now,
        "age_seconds": 0.0,
        "work_order_path": str(work_order),
        "work_order_found": found,
        "layers": [[asdict(node) for node in layer] for layer in layers],
        "done": [asdict(node) for node in done],
        "cycles": cycles,
        "warnings": warnings,
        "counts": {
            "open": sum(1 for i in issues if i.state == "open"),
            "closed": sum(1 for i in issues if i.state == "closed"),
            "batches": sum(1 for n in nodes if n.kind == "batch"),
        },
    }


class BoardCache:
    """Memoises the whole payload so a 5s page poll does not hammer the API."""

    def __init__(self, repo: str | None, work_order: Path, ttl: float = CACHE_TTL_SECONDS) -> None:
        self._repo = repo
        self._work_order = work_order
        self._ttl = ttl
        self._lock = threading.Lock()
        self._payload: dict | None = None

    def get(self) -> dict:
        with self._lock:
            fresh = self._payload is not None and (
                time.time() - self._payload["fetched_at"] < self._ttl
            )
            if not fresh:
                self._payload = assemble(self._repo, self._work_order)
            payload = dict(self._payload)
        payload["age_seconds"] = round(time.time() - payload["fetched_at"], 1)
        return payload


# --------------------------------------------------------------------------- http


def make_handler(cache: BoardCache) -> type[BaseHTTPRequestHandler]:
    """Build a GET-only handler bound to this cache. There are no write routes."""

    class BoardHandler(BaseHTTPRequestHandler):
        server_version = "FrontierBoard/1.0"

        def log_message(self, fmt: str, *args: object) -> None:
            """Silence per-request logging — it is pure noise on a 5s poll."""

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlparse(self.path).path
            if path == "/":
                self._send(200, PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/board":
                body = json.dumps(cache.get()).encode("utf-8")
                self._send(200, body, "application/json")
            else:
                body = json.dumps({"error": "not found", "path": path}).encode("utf-8")
                self._send(404, body, "application/json")

    return BoardHandler


def open_browser(url: str) -> None:
    """Best-effort browser launch. A missing opener is never an error."""
    opener = {"darwin": ["open"], "win32": ["cmd", "/c", "start", ""]}.get(
        sys.platform, ["xdg-open"]
    )
    try:
        with open(os.devnull, "wb") as devnull:
            subprocess.Popen([*opener, url], stdout=devnull, stderr=devnull)
    except Exception:  # noqa: BLE001 - the board must start regardless
        pass


# --------------------------------------------------------------------------- page

PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Frontier</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  :root { color-scheme: dark; }
  body { background: #0b0e14; }
  .dot-live { box-shadow: 0 0 0 3px rgba(52,211,153,.15); }
  .dot-stale { box-shadow: 0 0 0 3px rgba(248,113,113,.15); }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-thumb { background: #232a36; border-radius: 6px; }
  /* A long gate scrolls; keep its scrollbar visible so that is discoverable. */
  .gate-scroll { scrollbar-width: thin; scrollbar-color: #3b4759 transparent; }
  .gate-scroll::-webkit-scrollbar { height: 6px; }
  .gate-scroll::-webkit-scrollbar-thumb { background: #3b4759; border-radius: 3px; }
</style>
</head>
<body class="text-slate-200 font-sans antialiased">
<div class="max-w-6xl mx-auto px-4 py-6">

  <header class="flex flex-wrap items-baseline gap-x-4 gap-y-2 border-b border-slate-800 pb-4">
    <h1 class="text-xl font-semibold tracking-tight text-slate-100">
      frontier <span id="repo" class="font-mono text-sky-400 text-base"></span>
    </h1>
    <div class="flex items-center gap-2 text-xs text-slate-400">
      <span id="dot" class="inline-block w-2 h-2 rounded-full bg-emerald-400 dot-live"></span>
      <span id="freshness">connecting…</span>
    </div>
    <div id="counts" class="text-xs text-slate-400 font-mono"></div>
    <div id="workorder" class="text-xs text-slate-500 font-mono ml-auto"></div>
  </header>

  <div id="banners" class="mt-4 space-y-2"></div>

  <div class="mt-5 flex flex-wrap items-center gap-3">
    <div id="prio" class="flex gap-1 text-xs"></div>
    <input id="search" type="search" placeholder="filter by title or #number"
      class="flex-1 min-w-[12rem] bg-slate-900 border border-slate-700 rounded px-3 py-1.5
             text-sm placeholder:text-slate-600 focus:outline-none focus:border-sky-600">
  </div>

  <main id="board" class="mt-6 space-y-8"></main>
  <section id="done-wrap" class="mt-10"></section>

  <footer class="mt-12 text-[11px] text-slate-600 border-t border-slate-800 pt-3">
    read-only view — this board never writes to GitHub
  </footer>
</div>

<script>
"use strict";
const PRIORITIES = ["all", "P1", "P2", "P3"];
let last = null, prio = "all", query = "", repoName = "";

// --- tiny DOM helpers: everything user-facing goes in via textContent -------
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function link(href, cls, text) {
  const a = el("a", cls, text);
  a.href = href || "#";
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

const PRIO_CLASS = {
  P1: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  P2: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  P3: "bg-slate-500/15 text-slate-400 border-slate-500/30",
};
function pill(text, cls) {
  return el("span", "px-1.5 py-0.5 rounded border text-[10px] font-mono tracking-wide " + cls, text);
}

// --- filters ---------------------------------------------------------------
function matches(node) {
  if (prio !== "all" && node.priority !== prio) return false;
  if (!query) return true;
  const q = query.toLowerCase();
  if ((node.title || "").toLowerCase().includes(q)) return true;
  if ((node.id || "").toLowerCase().includes(q)) return true;
  return (node.issues || []).some(function (i) {
    return String(i.number).includes(q) || (i.title || "").toLowerCase().includes(q);
  });
}

function buildFilters() {
  const box = document.getElementById("prio");
  box.replaceChildren();
  PRIORITIES.forEach(function (p) {
    const active = p === prio;
    const b = el("button",
      "px-2 py-1 rounded border font-mono " +
      (active ? "bg-sky-500/20 border-sky-500/50 text-sky-300"
              : "bg-slate-900 border-slate-700 text-slate-400 hover:text-slate-200"), p);
    b.onclick = function () { prio = p; buildFilters(); if (last) render(last); };
    box.appendChild(b);
  });
}

// --- cards -----------------------------------------------------------------
function issueRow(issue) {
  const row = el("div", "flex items-baseline gap-2 py-1 border-t border-slate-800/70 first:border-0");
  row.appendChild(link(issue.url, "font-mono text-xs text-sky-400 hover:text-sky-300 shrink-0",
    "#" + issue.number));
  const title = el("span", "text-sm text-slate-300 flex-1 min-w-0", issue.title);
  row.appendChild(title);
  if (issue.state === "closed") row.appendChild(pill("closed", PRIO_CLASS.P3));
  const p = (issue.labels || []).find(function (l) { return PRIO_CLASS[l.toUpperCase()]; });
  if (p) row.appendChild(pill(p.toUpperCase(), PRIO_CLASS[p.toUpperCase()]));
  return row;
}

function gateBlock(gate, note) {
  const outer = el("div", "mt-3");
  const wrap = el("div", "flex items-stretch gap-2");
  // `block` is load-bearing: overflow does not apply to an inline box, so
  // without it a long gate is clipped mid-word with no way to see the rest.
  const code = el("code",
    "block flex-1 min-w-0 max-w-full bg-black/40 border border-slate-800 rounded px-2 py-1.5 " +
    "font-mono text-[11px] text-emerald-300 overflow-x-auto whitespace-pre gate-scroll", gate);
  const btn = el("button",
    "shrink-0 px-2 rounded border border-slate-700 text-[11px] text-slate-400 hover:text-slate-100", "copy");
  btn.onclick = function () {
    const done = function () { btn.textContent = "copied"; setTimeout(function () { btn.textContent = "copy"; }, 1200); };
    if (navigator.clipboard) navigator.clipboard.writeText(gate).then(done, done); else done();
  };
  wrap.append(code, btn);
  outer.appendChild(wrap);
  // The caveat is often the most important thing on the card ("does not exist yet").
  if (note) outer.appendChild(el("p", "mt-1 text-[11px] text-amber-300/80 leading-snug", note));
  return outer;
}

function blockedBlock(blockers) {
  const wrap = el("div", "mt-3 text-xs text-amber-300/80 space-y-1");
  blockers.forEach(function (b) {
    // One inline run, so it wraps like a sentence instead of a flex row that
    // orphans "by" onto its own line.
    const line = el("p", "leading-snug");
    line.appendChild(document.createTextNode("blocked by "));
    const href = repoName ? "https://github.com/" + repoName + "/issues/" + b.number : null;
    line.appendChild(link(href, "font-mono text-amber-300 hover:underline", "#" + b.number));
    if (b.title) line.appendChild(document.createTextNode(" — " + b.title));
    wrap.appendChild(line);
  });
  return wrap;
}

function trailingTags(head, node) {
  if (node.priority) head.appendChild(pill(node.priority, PRIO_CLASS[node.priority] || PRIO_CLASS.P3));
  (node.areas || []).forEach(function (a) {
    head.appendChild(el("span", "text-[10px] font-mono text-slate-500", a));
  });
}

// A batch needs a title AND member rows. A single issue has nothing to list
// under its own title, so it gets one line — anything else prints it twice.
function batchHead(node) {
  const head = el("div", "flex items-start gap-2 flex-wrap");
  head.appendChild(el("span",
    "font-mono text-[10px] px-1.5 py-0.5 rounded border shrink-0 " +
    "border-violet-500/40 text-violet-300 bg-violet-500/10", "batch"));
  // A floor on the title width pushes the pills onto their own line when the
  // card is narrow, instead of squeezing the title to two words per line.
  head.appendChild(el("h3", "font-medium text-slate-100 flex-1 min-w-[14rem]", node.title));
  trailingTags(head, node);
  return head;
}

function issueHead(node) {
  const issue = (node.issues || [])[0] || {};
  const head = el("div", "flex items-baseline gap-2 flex-wrap");
  head.appendChild(link(issue.url,
    "font-mono text-xs text-sky-400 hover:text-sky-300 shrink-0", "#" + issue.number));
  // A floor on the title width pushes the pills onto their own line when the
  // card is narrow, instead of squeezing the title to two words per line.
  head.appendChild(el("h3", "font-medium text-slate-100 flex-1 min-w-[14rem]", node.title));
  if (issue.state === "closed") head.appendChild(pill("closed", PRIO_CLASS.P3));
  trailingTags(head, node);
  return head;
}

function card(node, dim) {
  const box = el("article",
    "rounded-lg border border-slate-800 bg-slate-900/50 p-4 " + (dim ? "opacity-70" : ""));
  if (node.kind === "batch") {
    box.appendChild(batchHead(node));
    const rows = el("div", "mt-2");
    (node.issues || []).forEach(function (i) { rows.appendChild(issueRow(i)); });
    box.appendChild(rows);
  } else {
    box.appendChild(issueHead(node));
  }

  if (node.gate) box.appendChild(gateBlock(node.gate, node.gate_note));
  if ((node.blocked_by || []).length) box.appendChild(blockedBlock(node.blocked_by));
  if (node.why) box.appendChild(el("p", "mt-3 text-xs text-slate-500 leading-relaxed", node.why));
  if ((node.assignees || []).length) {
    box.appendChild(el("p", "mt-2 text-[11px] font-mono text-slate-600", "@" + node.assignees.join(" @")));
  }
  return box;
}

// --- sections --------------------------------------------------------------
function section(titleText, subtitle, nodes, opts) {
  const wrap = el("section", "");
  if (opts.opacity) wrap.style.opacity = opts.opacity;
  const head = el("div", "flex items-baseline gap-3 mb-3");
  head.appendChild(el("h2", opts.titleClass, titleText));
  if (subtitle) head.appendChild(el("span", "text-xs text-slate-500", subtitle));
  wrap.appendChild(head);
  // items-start: cards size to their own content instead of stretching to
  // match the tallest in the row.
  const grid = el("div", "grid gap-3 items-start " + (opts.cols || "lg:grid-cols-2"));
  nodes.forEach(function (n) { grid.appendChild(card(n, opts.dim)); });
  wrap.appendChild(grid);
  return wrap;
}

function renderBanners(data) {
  const box = document.getElementById("banners");
  box.replaceChildren();
  if (!data.work_order_found) {
    const b = el("div", "rounded border border-amber-600/40 bg-amber-500/10 text-amber-200 text-xs px-3 py-2");
    b.appendChild(el("span", "font-semibold", "no work order — "));
    b.appendChild(el("span", null,
      "could not read " + data.work_order_path + ", so every issue is shown unbatched."));
    box.appendChild(b);
  }
  (data.cycles || []).forEach(function (c) {
    const b = el("div", "rounded border border-rose-600/50 bg-rose-500/10 text-rose-200 text-xs px-3 py-2");
    b.appendChild(el("div", "font-semibold", "dependency cycle: " + c.nodes.join(" ↔ ")));
    (c.edges || []).forEach(function (e) {
      b.appendChild(el("div", "font-mono text-[11px] text-rose-300/80", e[0] + " ← blocked by ← " + e[1]));
    });
    box.appendChild(b);
  });
  if ((data.warnings || []).length) {
    const b = el("div", "rounded border border-amber-600/40 bg-amber-500/10 text-amber-200/90 text-xs px-3 py-2 space-y-0.5");
    b.appendChild(el("div", "font-semibold", data.warnings.length + " warning(s)"));
    data.warnings.forEach(function (w) { b.appendChild(el("div", "text-amber-200/70", w)); });
    box.appendChild(b);
  }
}

function renderDone(data) {
  const wrap = document.getElementById("done-wrap");
  wrap.replaceChildren();
  const done = (data.done || []).filter(matches);
  if (!done.length) return;
  const details = el("details", "rounded-lg border border-slate-800/70 bg-slate-900/30 px-4 py-3");
  const summary = el("summary", "cursor-pointer text-sm font-semibold text-slate-500 select-none",
    "DONE — " + done.length);
  details.appendChild(summary);
  const grid = el("div", "grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mt-3 items-start opacity-50");
  done.forEach(function (n) { grid.appendChild(card(n, true)); });
  details.appendChild(grid);
  wrap.appendChild(details);
}

function render(data) {
  repoName = /^[\w.-]+\/[\w.-]+$/.test(data.repo || "") ? data.repo : "";
  document.getElementById("repo").textContent = data.repo;
  document.getElementById("counts").textContent =
    data.counts.open + " open / " + data.counts.closed + " closed / " + data.counts.batches + " batches";
  document.getElementById("workorder").textContent = data.work_order_path;
  renderBanners(data);

  const board = document.getElementById("board");
  board.replaceChildren();
  const layers = (data.layers || []).map(function (l) { return l.filter(matches); });
  const firstIdx = layers.findIndex(function (l) { return l.length > 0; });

  layers.forEach(function (nodes, idx) {
    if (!nodes.length) return;
    if (idx === firstIdx) {
      board.appendChild(section("FRONTIER", "nothing blocks these — start here", nodes, {
        titleClass: "text-2xl font-bold tracking-tight text-emerald-300",
        cols: "lg:grid-cols-2", dim: false,
      }));
    } else {
      board.appendChild(section(idx === firstIdx + 1 ? "NEXT" : "THEN " + (idx + 1),
        "blocked until the layers above land", nodes, {
          titleClass: "text-base font-semibold tracking-wide text-slate-400",
          // Same grid as the frontier — dimming should be the only difference.
          cols: "lg:grid-cols-2",
          opacity: String(Math.max(0.55, 1 - 0.12 * (idx - firstIdx))),
          dim: true,
        }));
    }
  });
  if (firstIdx === -1) {
    board.appendChild(el("p", "text-sm text-slate-500", "nothing open matches this filter."));
  }
  renderDone(data);
}

// --- polling ---------------------------------------------------------------
function setLive(ok, age) {
  const dot = document.getElementById("dot");
  dot.className = "inline-block w-2 h-2 rounded-full " +
    (ok ? "bg-emerald-400 dot-live" : "bg-rose-500 dot-stale");
  document.getElementById("freshness").textContent =
    ok ? "refreshed " + Math.round(age) + "s ago" : "stale — cannot reach the board";
}

async function poll() {
  try {
    const res = await fetch("/api/board", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    last = data;
    setLive(true, data.age_seconds || 0);
    render(data);
  } catch (err) {
    setLive(false, 0);  // keep the last good render on screen
  }
}

document.getElementById("search").addEventListener("input", function (e) {
  query = e.target.value.trim();
  if (last) render(last);
});
buildFilters();
poll();
setInterval(poll, 5000);
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- cli


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="board.py",
        description="Read-only local board of GitHub issues ordered by dependency.",
    )
    parser.add_argument("--repo", help="OWNER/NAME; defaults to the git remote of the cwd")
    parser.add_argument(
        "--work-order",
        default="docs/agents/work-order.md",
        help="path to the work-order markdown (default: docs/agents/work-order.md)",
    )
    parser.add_argument("--port", type=int, default=7373, help="port to bind (default: 7373)")
    parser.add_argument("--no-open", action="store_true", help="do not launch a browser")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        preflight()
    except GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    cache = BoardCache(args.repo, Path(args.work_order).resolve())
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(cache))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"frontier board (read-only) → {url}", flush=True)
    print("ctrl-c to stop", flush=True)
    if not args.no_open:
        open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
