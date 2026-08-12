# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies** — the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only — the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me` — the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.

## Frontier operations

Used by `/frontier`, which orders and batches the whole open set rather than a single map's children.

- **List with edges**: `gh issue list --state all --limit 300 --json number,title,labels,state,assignees,url`. `issue_dependencies_summary` is only on the single-issue endpoint, so fetch blockers per open issue with `gh api repos/<owner>/<repo>/issues/<n> --jq .issue_dependencies_summary`, then `gh api repos/<owner>/<repo>/issues/<n>/dependencies/blocked_by` for the list. Run these concurrently — serially they dominate the runtime.
- **Touch set**: an `area:<slug>` label. Create with `gh label create "area:<slug>" --color BFD4F2 --description "<subsystem>"`, apply with `gh issue edit <n> --add-label "area:<slug>"`. One label per meaningful subsystem, not per file. Reuse any `area:*` labels the repo already has instead of coining near-duplicates.
- **Blocking edge**: the same native issue dependencies described under Wayfinding operations — `gh api --method POST repos/<owner>/<repo>/issues/<blocked>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, with the blocker's numeric **database id** from `gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`. Remove one with `gh api --method DELETE repos/<owner>/<repo>/issues/<blocked>/dependencies/blocked_by/<blocker-db-id>`.
- **Frontier query**: open issues with no open blocker, batched per `docs/agents/work-order.md`. A batch is blocked if _any_ member is. Count blockers from the `/dependencies/blocked_by` list, **not** from `issue_dependencies_summary` — see the gotcha below.
- **Priority**: whatever label scheme the repo already uses (`P1`/`P2`/`P3`, `priority:high`, …). Do not invent one; if there is none, sort by issue number and say so.
- **Batches**: GitHub has no representation for "these three are one pull request". They live only in `docs/agents/work-order.md`. Do not create parent issues or sub-issues for them.

Where issue dependencies aren't available (older GitHub Enterprise returns 404 on the endpoint), fall back to a `Blocked by: #<n>, #<n>` line at the top of the issue body and parse it.

### Gotchas

- **`issue_dependencies_summary` is eventually consistent.** It lags a dependency write by roughly twenty seconds, while `GET /dependencies/blocked_by` reflects it immediately. Measured on a live repo: the `POST` returned `204` and the list endpoint showed the blocker at once, but the summary still read `blocked_by: 0` twelve seconds later and only caught up around twenty. Read blockers from the list endpoint and count the entries whose `state` is `open`. Using the summary as a gate means that in the window right after `/frontier` writes its edges — exactly when someone opens the board — a blocked issue renders as takeable, with nothing to indicate it is wrong.
- **The blocker id is the numeric database id, not the issue number.** `-F issue_id=180` will silently target whatever issue happens to have database id 180, usually in a different repo. Always resolve it with `gh api repos/<owner>/<repo>/issues/<n> --jq .id` first.
