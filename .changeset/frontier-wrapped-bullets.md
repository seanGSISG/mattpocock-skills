---
"mattpocock-skills": patch
---

Fix how `/frontier`'s board parses `docs/agents/work-order.md`.

- A wrapped line now belongs to the bullet it continues. Before, the wrapped lines of a bullet that is not a field (`- **PR:** …`, a note) joined the field above it, so issue numbers on them became batch members, and its text joined the gate note or the rationale.
- A wrapped line that starts with `#<number>` now continues its field. Before, it was dropped, and so was the issue on it.
- Accept `Issue:` as well as `Issues:`. Before, a batch that wrote `**Issue:** #444` had no members, and the board skipped it.
- Add `scripts/test_board.py` (standard library `unittest`) for these cases.
- Say in the board's usage and `--help` that it serves until ctrl-c and never exits on its own.
