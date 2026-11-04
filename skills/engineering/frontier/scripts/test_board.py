"""Tests for board.py's work-order parser.

Run from the repo root: python3 -m unittest discover skills/engineering/frontier/scripts
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import board


def parse(text: str) -> list[board.Batch]:
    """Write `text` to a work-order file and parse it the way the board does."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "work-order.md")
        path.write_text(text, encoding="utf-8")
        batches, _, _ = board.parse_work_order(path)
    return batches


class WrappedBulletTest(unittest.TestCase):
    def test_wrapped_line_of_a_note_bullet_stays_with_that_bullet(self) -> None:
        [batch] = parse(
            "## Batches\n"
            "\n"
            "### ci — CI fixes\n"
            "\n"
            "- **Issues:** #1, #2\n"
            "- **PR:** #40 merged; its follow-ups\n"
            "  are #41 and #42.\n"
            "- **Gate:** `just test`\n"
            "- **Done:** the first half, in\n"
            "  PR #44.\n"
            "- **Why:** both touch `ci.yaml`, so\n"
            "  one review covers them.\n"
            "- **Note:** filed out of it,\n"
            "  see #43.\n"
        )
        self.assertEqual(batch.issue_numbers, [1, 2])
        self.assertEqual(batch.gate, "just test")
        self.assertIsNone(batch.gate_note)
        self.assertEqual(batch.why, "both touch `ci.yaml`, so one review covers them.")

    def test_wrapped_line_that_starts_with_an_issue_ref_continues_its_field(self) -> None:
        [batch] = parse(
            "## Batches\n"
            "\n"
            "### ci — CI fixes\n"
            "\n"
            "- **Issues:** #1, #2,\n"
            "  #3\n"
            "- **Why:** #1 goes first, then\n"
            "  #2 and #3.\n"
        )
        self.assertEqual(batch.issue_numbers, [1, 2, 3])
        self.assertEqual(batch.why, "#1 goes first, then #2 and #3.")


class IssueLabelTest(unittest.TestCase):
    def test_singular_issue_label_lists_the_member(self) -> None:
        [batch] = parse(
            "## Batches\n"
            "\n"
            "### schedule — The Schedule\n"
            "\n"
            "- **Issue:** #444\n"
            "- **Gate:** `just test`\n"
        )
        self.assertEqual(batch.issue_numbers, [444])


def page(nodes: list[dict], cursor: str | None = None) -> str:
    """One `gh api graphql` response page of ISSUES_QUERY."""
    info = {"hasNextPage": cursor is not None, "endCursor": cursor}
    issues = {"pageInfo": info, "nodes": nodes}
    return json.dumps({"data": {"repository": {"nameWithOwner": "o/r", "issues": issues}}})


def issue(number: int, state: str, blocked_by: list[dict] | None = None) -> dict:
    node = {
        "number": number,
        "title": f"t{number}",
        "state": state,
        "url": f"u{number}",
        "labels": {"nodes": [{"name": "P1"}]},
        "assignees": {"nodes": [{"login": "sean"}]},
    }
    if blocked_by is not None:
        node["blockedBy"] = {"nodes": blocked_by}
    return node


class FetchTrackerTest(unittest.TestCase):
    def test_one_paged_query_gives_issues_and_their_blockers(self) -> None:
        responses = [
            page([issue(2, "OPEN", [{"number": 1, "state": "CLOSED", "title": "t1"}])], "c1"),
            page([issue(1, "CLOSED", [])]),
        ]
        calls: list[list[str]] = []

        def run_gh(args: list[str]) -> tuple[bool, str, str]:
            calls.append(args)
            return True, responses[len(calls) - 1], ""

        with mock.patch.object(board, "run_gh", run_gh):
            name, issues, blockers, warnings = board.fetch_tracker("o/r")

        self.assertEqual(name, "o/r")
        self.assertEqual(
            issues,
            [
                board.Issue(2, "t2", "open", "u2", ["P1"], ["sean"]),
                board.Issue(1, "t1", "closed", "u1", ["P1"], ["sean"]),
            ],
        )
        self.assertEqual(blockers, {2: [{"number": 1, "state": "closed", "title": "t1"}]})
        self.assertEqual(warnings, [])
        self.assertIn("after=c1", calls[1])
        self.assertTrue(all(args[:2] == ["api", "graphql"] for args in calls))

    def test_a_server_without_blockedBy_still_lists_the_issues_and_says_so(self) -> None:
        def run_gh(args: list[str]) -> tuple[bool, str, str]:
            if any("blockedBy" in arg for arg in args):
                return False, "", "Field 'blockedBy' doesn't exist on type 'Issue'"
            return True, page([issue(3, "OPEN")]), ""

        with mock.patch.object(board, "run_gh", run_gh):
            _, issues, blockers, warnings = board.fetch_tracker(None)

        self.assertEqual([i.number for i in issues], [3])
        self.assertEqual(blockers, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("NOT being shown", warnings[0])


if __name__ == "__main__":
    unittest.main()
