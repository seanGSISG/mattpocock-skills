---
"mattpocock-skills": patch
---

Fix how `/frontier`'s board parses wrapped bullets in `docs/agents/work-order.md`.

- A wrapped line now belongs to the bullet it continues. Before, the wrapped lines of a bullet that is not a field (`- **PR:** …`, a note) joined the field above it, so issue numbers on them became batch members, and its text joined the gate note or the rationale.
- A wrapped line that starts with `#<number>` now continues its field. Before, it was dropped, and so was the issue on it.
- Add `scripts/test_board.py` (standard library `unittest`) for both cases.
- Say in the board's usage and `--help` that it serves until ctrl-c and never exits on its own.
