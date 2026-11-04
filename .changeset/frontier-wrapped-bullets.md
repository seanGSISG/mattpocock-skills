---
"mattpocock-skills": patch
---

Fix how `/frontier`'s board parses `docs/agents/work-order.md`.

- A wrapped line now belongs to the bullet it continues. Before, the wrapped lines of a bullet that is not a field (`- **PR:** …`, a note) joined the field above it, so issue numbers on them became batch members, and its text joined the gate note or the rationale.
- A wrapped line that starts with `#<number>` now continues its field. Before, it was dropped, and so was the issue on it.
- Accept `Issue:` as well as `Issues:`. Before, a batch that wrote `**Issue:** #444` had no members, and the board skipped it.
- Load the board's data with one paged GraphQL query (issues, labels, assignees and `blockedBy`) instead of `gh repo view`, `gh issue list` and one REST `dependencies/blocked_by` call per open issue. On a 22-open-issue repo a load goes from 5 s in 24 calls to 3.5 s in 3, and a board left open no longer goes over the REST rate limit after about 40 minutes. `blockedBy` was measured correct 0.6 s after a write, while `issueDependenciesSummary` still lagged. The output is the same. The GitHub tracker seed's "Frontier operations" now describes the same query.
- Add `scripts/test_board.py` (standard library `unittest`) for these cases.
- Say in the board's usage and `--help` that it serves until ctrl-c and never exits on its own.
