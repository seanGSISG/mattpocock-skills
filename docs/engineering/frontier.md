## What it does

`/frontier` answers the question you ask every time you open a full issue tracker: what should I do next, and in what order? It reads every open issue, works out which files each one touches, wires up the blocking edges your tracker is missing, groups the issues that ought to land as a single pull request, and serves a live local board of the result.

It records the answer instead of narrating it. Ask any agent to order your backlog and you get a good reply that evaporates the moment you clear the [context window](https://www.aihero.dev/ai-coding-dictionary/context-window) — the reasoning lived only in the reply. `/frontier` writes the durable half back to the tracker itself, as labels and native blocking links, so the ordering survives in a place both a human and the next session can read.

## When to reach for it

You invoke this by typing `/frontier` — the agent won't reach for it on its own.

| Situation | Reach for |
|---|---|
| The tracker has enough in it that the next move isn't obvious | `/frontier` |
| Several small issues clearly belong in one pull request, but nothing records that | `/frontier` |
| Issues exist but are raw, unlabelled, or unspecified | [triage](https://aihero.dev/skills-triage) first |
| The work isn't broken into issues yet | [to-tickets](https://aihero.dev/skills-to-tickets) first |
| One huge effort whose shape isn't visible yet | [wayfinder](https://aihero.dev/skills-wayfinder) |

The boundary that matters: `/frontier` reads what is already on the tracker and records an order. It is not a planning session and it does not improve your issues. If the issues themselves are wrong, no ordering of them will help.

It's cheap and it's meant to be re-run. Run it again whenever the tracker moves.

## Prerequisites

An issue tracker configured by [setup-matt-pocock-skills](https://aihero.dev/skills-setup-matt-pocock-skills), whose tracker doc carries a "Frontier operations" section describing how your tracker expresses touch sets and blocking edges. A repo set up before this skill existed won't have that section; the skill falls back to the local-markdown convention rather than failing.

It writes `docs/agents/work-order.md` into your repo, and it adds `area:*` labels and blocking edges to your tracker — always after showing you the full write set and asking.

The board needs Python 3.12 and the standard library. Nothing to install.

## Batches, and why they're the point

A **batch** is a set of issues that should land as a single pull request, because they share a **touch set** — the files or subsystems they implicate.

This is where the leverage is. Three bugs in the same file are three review cycles if you work them separately and one if you don't, and the second and third fixes are a few lines on top of context the first one already paid for. Spotting that requires knowing what each issue touches, which is exactly the fact most trackers never record. `/frontier` records it as an `area:*` label, which turns "what else is in this file?" from a re-read of every issue into a query.

A batch is **one node in the blocking graph**. Its members collapse together: takeable only when every member is unblocked, done only when every member is closed. Modelling it any other way makes each member look independently takeable, and the board ends up contradicting its own advice.

Every batch declares a **gate**: the narrowest command that actually verifies it. Narrowest *sufficient* — not the project's blessed full-suite command, because a gate exists to be run over and over while you work, and a five-minute suite won't be. A suite that returns different answers on identical code isn't a gate at any width, and saying so out loud is part of the answer rather than an aside.

## Where the answer lives

Three stores, and the split between them is what stops the answer going stale.

| What | Where | Why there |
|---|---|---|
| Touch sets, blocking edges, priority | The issue tracker | Renders in the tracker's own UI, so the frontier is visible to someone who never opens the board |
| Batch membership, gate, rationale | `docs/agents/work-order.md` | No tracker has a field for "these three are one pull request" |
| Open, closed, claimed, blocked | Nowhere — read live | State copied into a file is stale by the next morning |

That last row is the one people get wrong. Closing an issue drops it off the board with nothing to regenerate, because the board never believed it knew the state in the first place.

## Common questions

**Why does it write to my tracker at all? Couldn't it just tell me?**

It could, and you'd re-derive the same answer next week. Labels and blocking edges render in the tracker's own UI, so a human who never runs this skill still sees which issues are blocked. That's the difference between an answer and a record.

Every write is shown to you as a complete set and waits for approval. Both kinds are trivially reversible.

**Isn't a batch just a blocking edge?**

No, and confusing the two is the most common way this goes wrong. A batch means *land together, one pull request*. An edge means *this one can't start until that one closes*. If two issues must both land before anything observable changes, that's a batch. If one must land before the other is even worth starting, that's an edge.

**Why doesn't the board have buttons?**

It's read-only on purpose. It renders live tracker state joined to a file in your repo, so the way to change the plan is to re-run the skill or edit `docs/agents/work-order.md` by hand — both of which leave a trace. A board that mutated the tracker on a click would be a second, undocumented path for changing the same facts.

**What if it batches things I don't want batched?**

Say so at the confirmation step and it'll rework them. After the fact, edit `docs/agents/work-order.md` — it's designed to be hand-edited, the board re-parses it on every refresh, and a later run preserves batches you've changed.

## It's working if

- You open the board and the first thing you see is a short list you could start on right now, not the whole backlog.
- Issues you'd have opened separate pull requests for are sitting in one batch, with a sentence explaining why.
- Every batch has a gate you'd actually be willing to run on a loop.
- Closing an issue on the tracker moves it to Done on the board within a few seconds, with nothing regenerated.
- Something on the board is blocked, and it names what blocks it — and you agree.

## Where it fits

A **chain step**, between ticket-writing and building: `to-spec → to-tickets → frontier → implement`. It's the step that decides which issue `/implement` picks up next and which gate it runs.

Its neighbours: [to-tickets](https://aihero.dev/skills-to-tickets), because the blocking edges it declares are the ones `/frontier` reads and extends; and [implement](https://aihero.dev/skills-implement), which takes one batch per fresh context window. [triage](https://aihero.dev/skills-triage) sits upstream of both — an issue nobody has triaged has no priority to sort by.

For the whole map, see [ask-matt](https://aihero.dev/skills-ask-matt).
