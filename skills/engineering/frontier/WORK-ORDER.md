# The work order file

`docs/agents/work-order.md` records the judgments `/frontier` makes that the issue tracker has no field for: which Issues form a **batch**, what **gate** verifies each one, and why.

It holds **judgments only, never state**. No `status:`, no assignee, no open/closed. Those are read live from the tracker every time the board renders, which is what stops this file going stale — closing an Issue drops it off the board with nothing to regenerate.

It is meant to be hand-edited. `scripts/board.py` parses it on every refresh, so correcting a batch by hand and hitting reload works.

## Format

The parser is deliberately simple. It looks for a `## Batches` heading, then reads each `###` heading under it until the next `##`.

<work-order-template>

# Work order

Judgments recorded by `/frontier`. Live state comes from the issue tracker at render time — never
copy it here.

## Batches

### <batch-id> — <Batch title>

- **Issues:** #<n>, #<n>, #<n>
- **Gate:** `<the narrowest sufficient verification command>`
- **Blocked by:** #<n>
- **Why:** <one sentence that will still make sense in six months>

</work-order-template>

## Field rules

| Field | Required | Meaning |
|---|---|---|
| `Issues` | yes | Members, **in the order they should be worked**. The order is meaningful — see BATCHING.md. |
| `Gate` | no | The command that verifies the batch. Backticks are stripped. Omit only when there genuinely is none, and prefer naming the test the batch will add. |
| `Blocked by` | no | Batch-level blocking edges, in addition to any its members carry on the tracker. Use for a gate that blocks the batch as a whole. |
| `Why` | no | Rationale. Wraps onto following lines until the next `- **` or heading. |

- The batch **id** is the text before the ` — ` in the heading; the **title** is the rest. Ids should be short slugs (`graph`, `bot`, `ci`) — they appear on the board and in commit messages.
- Field labels are case-insensitive, and the `**` bolding is optional.
- Issue references are `#<number>` anywhere on the line.
- An Issue may belong to **at most one batch**. Listing it twice is a conflict; the board keeps the first and warns.
- Issues absent from every batch are fine. They are single-Issue nodes and appear on the board on their own.
- Anything outside `## Batches` is ignored by the parser, so notes and context can live in the same file.

## Worked example

<work-order-example>

# Work order

Judgments recorded by `/frontier`. Live state comes from the issue tracker at render time — never
copy it here.

## Batches

### graph — Graph client correctness

- **Issues:** #158, #159, #162
- **Gate:** `pytest tests/unit/services/test_graph_client.py`
- **Why:** All three touch `src/services/graph_client.py`, two of them the same function, so the
  second and third fixes are a few lines on top of context the first one already paid for. #158 is
  a correctness bug and #162 is an optimisation on the same call path, so #158 goes first.

### bot — Teams bot payload contract

- **Issues:** #160, #161
- **Gate:** `cd bot && npm test`
- **Why:** Both live in `bot/`, which has no test suite at all — which is exactly why both shipped.
  This batch adds the first contract test pinning the TypeScript types to the API schema, which
  covers the whole class of drift that produced them.

### gate — Make the quality gate satisfiable

- **Issues:** #168, #170
- **Gate:** `just check-all`
- **Blocked by:** #180
- **Why:** Neither alone changes anything observable — the gate stays red until both land, so
  "run it before every commit" stays unenforceable. Blocked by #180 because the suite is
  non-deterministic until that lands, and a gate that returns different answers on identical code
  cannot verify this batch.

</work-order-example>

## Anti-examples

**State in the file.** `- **Status:** in progress` — delete it. The tracker knows.

**A batch that is really an edge.** If one member must close before another is worth starting, they are two nodes with an edge, not one batch. See the table at the end of BATCHING.md.

**A gate nobody would run.** `- **Gate:** `just test`` on a five-minute flaky suite is not a gate. Name the narrow deterministic command, or name the test that needs writing.

**A rationale that repeats the title.** "Why: fixes the graph client bugs" says nothing the Issues do not. Write the reason they belong *together*.
