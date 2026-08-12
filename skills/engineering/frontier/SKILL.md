---
name: frontier
description: Work out what to do next across an issue tracker — derive each Issue's touch set, wire the blocking edges the tracker is missing, batch the Issues that should land as one pull request, and serve a live board of the result.
disable-model-invocation: true
---

# Frontier

The **frontier** is the set of Issues that are open, unblocked, and unclaimed — the work that can start right now. Every tracker can list its Issues; almost none can tell you which to pick up first, which can run in parallel, and which should share a single pull request. This skill works that out, records the durable parts **on the tracker itself**, and serves a live board over the result.

The issue tracker should have been provided to you — run `/setup-matt-pocock-skills` if not. Consult the tracker doc's "Frontier operations" section for how _this_ repo expresses touch sets and blocking edges. If no tracker has been provided, or the doc has no such section, default to the local-markdown tracker.

## What gets recorded where

Three stores, and the split between them is the whole point.

- **The tracker holds the facts.** A **touch set** becomes an `area:*` label; hard sequencing becomes a native blocking edge. Both render in the tracker's own UI, so the frontier is visible to a human who never opens the board.
- **The work order holds the judgments.** Batch membership, the gate command, and the reasoning — the things a tracker has no field for. Written to `docs/agents/work-order.md`; format in [WORK-ORDER.md](WORK-ORDER.md).
- **Nothing holds the state.** Open, closed, claimed, blocked — always read live. That is what stops the work order going stale: closing an Issue simply drops it off the board, with nothing to regenerate.

Never copy live state into the work order. If you catch yourself writing "status: open" into a file, stop.

## Batch

A **batch** is a set of Issues that should land as a **single pull request**, because they share a touch set. Batching is the highest-leverage judgment this skill makes — it is routinely the difference between five review cycles and two.

A batch is **one node in the dependency graph**. Its members collapse together, so a batch is takeable only when every member is unblocked, and it is done only when every member is closed. Modelling it any other way makes each member look independently takeable and the board contradicts its own advice.

Every batch declares a **gate**: the narrowest command that actually verifies it. Not the project's blessed full-suite command — the narrowest _sufficient_ one. In a repo whose suite is slow or flaky, the blessed command is not a gate at all, and saying so is part of the answer.

The rules for what to batch, what to leave alone, and how to order within a batch are in [BATCHING.md](BATCHING.md). Read it before step 4.

## Process

### 1. Gather the Issues

Fetch every open Issue with its labels, assignees, and body, plus the existing blocking edges. Use the tracker doc's list command. Read the bodies properly — the ordering signal is usually buried in prose, not in fields.

If the user passed arguments (issue numbers, a label, a milestone), scope to those. Otherwise take everything open.

### 2. Derive each Issue's touch set

The **touch set** is the files or subsystems an Issue implicates. Work in this order:

- **Cited paths win.** A well-written Issue names its own files (`src/services/graph_client.py:370`). Take them.
- **Otherwise, search the codebase.** Map the Issue's subject to the module that owns it.
- **Fall back to the subsystem.** A whole directory (`bot/`, `admin/`) is a perfectly good touch set when that is the true granularity.

Collapse touch sets into a small vocabulary of `area:*` labels — one per meaningful subsystem, not one per file. Ten Issues should not produce ten areas. Reuse any `area:*` labels the tracker already has rather than coining near-duplicates.

### 3. Find the hard blocking edges

A **blocking edge** means the blocked Issue genuinely cannot start, or would be wasted work, until the blocker closes. It is not "these are related" and not "I would rather do this one first" — that is ordering, and ordering falls out of priority and batching on its own.

Sources, in descending reliability:

- Edges already wired on the tracker. Never re-derive or overwrite these.
- Prose in Issue bodies — "depends on", "blocked by", "after #N lands", "requires".
- Genuine logical dependency you can defend in one sentence. If you cannot, it is not an edge.

Be sparing. A graph where everything blocks everything is worth nothing, and a wrong edge hides work that was actually takeable.

### 4. Propose batches

Apply [BATCHING.md](BATCHING.md). Batch only Issues that are **unblocked as a group** — a batch inherits every member's blockers.

For each batch, produce an id (a short slug), a title, its member Issues **in the order they should be worked**, the gate command, and one sentence of rationale that would survive being read six months from now.

**Run each gate before recording it.** A plausible test path is not a real one, and a gate that is already red needs its baseline measured rather than assumed. This is the cheapest step here and the one that most often changes the answer.

### 5. Present the whole write set and stop

Show the user, before touching anything:

- The `area:*` labels to create and which Issues get each.
- Each blocking edge as `#blocked ← #blocker`, with the one-sentence reason.
- Each batch: members, gate, rationale, and the review cycles it saves.
- The resulting order — the frontier first, then what unlocks as each thing closes.

Ask directly whether the batches are right and whether any edge is wrong. Then ask for approval to write. **Do not write anything before the user approves.** Labels and edges are cheap to add and annoying to unpick; the confirmation is the safety.

### 6. Write to the tracker

Follow the tracker doc's "Frontier operations" section. **Create then wire, in two passes** — labels must exist before they can be applied, and Issues need identifiers before they can reference each other.

Report every write as you make it. If a write fails, say so and carry on with the rest rather than aborting halfway into an inconsistent state.

### 7. Write the work order

Write `docs/agents/work-order.md` in the format in [WORK-ORDER.md](WORK-ORDER.md). Judgments only.

Preserve any batch the user has since hand-edited — this file is meant to be edited by hand, and a regeneration that silently discards a human's correction is worse than no regeneration.

### 8. Offer the board

Run `scripts/board.py` from **this skill's own directory** — the base directory given to you when the skill was invoked — with the user's repo as the working directory:

```bash
python3 <skill-dir>/scripts/board.py --repo <owner>/<name>
```

Standard library only, read-only, binds `127.0.0.1`, defaults to port 7373. It joins live tracker state to the work order and refreshes itself every few seconds. Start it in the background, tell the user the URL, and leave it running.

Pass `--port` if 7373 is taken, and `--work-order` if the file is not at the default `docs/agents/work-order.md`. The board runs fine with no work order at all — every Issue simply appears unbatched.

The board never writes. Everything on it is a view of the tracker plus `docs/agents/work-order.md`, so the way to change the plan is to re-run this skill or hand-edit the work order.

## Where this sits

`/to-tickets` produces Issues; `/frontier` decides the order and the batching; `/implement` builds one batch per fresh context window, gated on the batch's gate command. `/triage` is upstream of all three — an Issue nobody has triaged has no priority to sort by.

Run it again whenever the tracker moves. It is cheap, and its whole job is to be re-run.
