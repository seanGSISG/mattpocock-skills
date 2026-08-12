# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01` — never a single combined tickets file
- Triage state is recorded as a `Status:` line near the top of each issue file (see `triage-labels.md` for the role strings)
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` — the Notes / Decisions-so-far / Fog body.
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open, unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.

## Frontier operations

Used by `/frontier`, which orders and batches the whole open set rather than a single map's children.

- **List with edges**: read every `.scratch/*/issues/*.md`, taking `Status:`, `Area:` and `Blocked by:` from the header lines.
- **Touch set**: an `Area: <slug>, <slug>` line near the top, alongside `Status:`. Local files have no label system, so this is the equivalent — same vocabulary, one entry per meaningful subsystem.
- **Blocking edge**: the existing `Blocked by: NN, NN` line. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier query**: files that are open, unblocked, and unclaimed, batched per `docs/agents/work-order.md`. A batch is blocked if _any_ member is.
- **Priority**: a `Priority: P1` line if the repo uses one; otherwise file order, and say so.
- **Batches**: recorded only in `docs/agents/work-order.md`. Do not encode them in filenames — a file's `NN` prefix is its dependency order and means something else.

Because a local tracker has no numeric database ids, `/frontier` references issues by their `NN` prefix throughout.
