# Batching

A **batch** is a set of Issues that should land as a single pull request. Getting this right is most of the value of `/frontier` — it is routinely the difference between five review cycles and two.

The bias is toward **not** batching. A batch that should have been two pull requests costs a confused review and a risky revert; two pull requests that should have been one batch cost a little duplicated context. The failure modes are not symmetric.

## Batch when

**They touch the same file.** Two Issues in the same file — often the same function — cost almost nothing to fix together once one of them has been understood. The second fix is a few lines on top of context you already paid for, and it saves a whole review cycle.

**They share an untested subsystem, and the batch adds the first test.** When several Issues arise in the same place and that place has no tests, the missing test _is_ the shared root cause. Batch them and land the first test in the same pull request. One contract test frequently covers the whole class of defect that produced them.

**Neither Issue alone changes the observable outcome.** Some Issues are only meaningful together: five failing security tests and thirty typecheck errors both have to land before the quality gate goes green. Landing either alone buys nothing measurable. That is a batch — not a blocking edge, because neither one gates the other.

**They are the same mechanical change in several places.** One rename, one signature change, applied across a handful of call sites. Splitting these produces pull requests that cannot be reviewed independently anyway.

## Do not batch when

**One member is risky and the others are trivial.** The risky change drags the trivia through a slow, careful review, and if it has to be reverted the trivia goes with it. Land the trivia separately and let the risky one take the time it needs.

**Members need different reviewers or different context.** A batch is one review. If no single reviewer can competently judge all of it, it is not one review.

**The blast radius is too wide.** Default cap: four Issues, or more than one subsystem. Past that, a reviewer stops reading carefully and the batch becomes a rubber stamp.

**One member is blocked.** A batch inherits every member's blockers, so adding a blocked Issue to an otherwise-takeable batch removes the whole batch from the frontier. Leave it out and batch it later.

**They only share a label.** `area:*` labels are an input to batching, not a definition of it. Two unrelated bugs in a large subsystem are two pull requests.

## Ordering within a batch

**Correctness before optimization**, when both sit on the same call path. Fix what is wrong before making it fast — the optimization is easier to review against already-correct code, and if the batch is cut short, the important half has landed.

**Structural before behavioural.** If one member makes the others easy — extracting a seam, adding a helper — do it first. "Make the change easy, then make the easy change."

**Otherwise, most severe first.** If the batch gets abandoned partway, the part that landed should be the part that mattered.

## The gate

Every batch declares a **gate**: the command that actually verifies it.

The gate is the **narrowest sufficient** command, not the project's blessed full-suite command. A gate exists to be run repeatedly during implementation, so a five-minute suite is not a gate even when it is green.

Choose it deliberately:

- Prefer the test file that directly covers the touched code.
- A gate must be **deterministic**. A suite that returns different answers on identical code is not a gate at any width — a green run is not evidence the code is good. If the project's blessed command has this problem, say so explicitly and gate on the narrow deterministic subset instead.
- If nothing covers the touched code, the gate is the test the batch is going to add. Say that plainly; it is a finding, not a gap to paper over.

**Run the gate before you record it.** Two things go wrong otherwise, and both are common enough to be worth the thirty seconds:

- **The command may not exist.** A plausible test path is not a real one. Check.
- **A deterministic gate is often already red.** Pre-existing failures are the normal case in a repo worth running this skill on. That does not disqualify the gate — it means the gate needs a **baseline**. Record the counts you measured and the date, so the batch's job is "introduces no new failures" rather than an unreachable green. A gate whose recorded state is a guess is worse than no gate, because someone will act on it.

## Batches and blocking edges are different things

Both express "these Issues are connected", and confusing them is the most common way this goes wrong.

|  | Batch | Blocking edge |
|---|---|---|
| Means | Land together, one pull request | One cannot start until the other closes |
| Sequence | Members are worked in order, in one sitting | Blocker closes, then the blocked work begins |
| On the graph | One node | An edge between two nodes |
| Test | Would splitting these waste review effort? | Would doing the second one first be wasted work? |

If two Issues must land together for anything to change, that is a batch. If one must land *before* the other is even worth starting, that is an edge. If neither is true, they are unrelated and the ordering is just priority.
