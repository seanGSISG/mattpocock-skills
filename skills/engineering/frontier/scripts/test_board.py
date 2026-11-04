"""Tests for board.py's work-order parser.

Run from the repo root: python3 -m unittest discover skills/engineering/frontier/scripts
"""

import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
