# Matt Pocock Skills

A collection of agent skills (slash commands and behaviors) loaded by Claude Code. Skills are organized into buckets and consumed by per-repo configuration emitted by `/setup-matt-pocock-skills`.

## Language

**Issue tracker**:
The tool that hosts a repo's issues — GitHub Issues, Linear, a local `.scratch/` markdown convention, or similar. Skills like `to-tickets`, `to-spec`, and `triage` read from and write to it.
_Avoid_: backlog manager, backlog backend, issue host

**Issue**:
A single tracked unit of work inside an **Issue tracker** — a bug, task, spec, or slice produced by `to-tickets`.
_Avoid_: ticket (use only when quoting external systems that call them tickets, or for a **Decision ticket** — see below)

**Decision ticket**:
A `wayfinder` unit — a child **Issue** of a `wayfinder:map` holding a *question* whose resolution is a decision, not a slice of a build to execute. The **decision** qualifier is what keeps it distinct from an implementation ticket; `wayfinder` introduces the term, then uses "ticket".

**Triage role**:
A canonical state-machine label applied to an **Issue** during triage (e.g. `needs-triage`, `ready-for-afk`). Each role maps to a real label string in the **Issue tracker** via `docs/agents/triage-labels.md`.

**Batch**:
A `frontier` unit — a set of **Issues** that should land as a single pull request, because they share a **Touch set**. A batch is one node in the blocking graph: takeable only when every member is unblocked, done only when every member is closed. It declares a **Gate**. Batch membership lives in `docs/agents/work-order.md`, not in the **Issue tracker**, which has no field for it.
_Avoid_: wave, phase, group, cluster

**Touch set**:
The files or subsystems an **Issue** implicates, recorded on the **Issue tracker** as an `area:*` label so that batching is a query rather than a re-read.

**Gate**:
The narrowest command that verifies a **Batch** — narrowest _sufficient_, not the project's blessed full-suite command. A non-deterministic command is not a gate at any width.

## Relationships

- An **Issue tracker** holds many **Issues**
- An **Issue** carries one **Triage role** at a time
- A **Decision ticket** is an **Issue** (a child of a `wayfinder:map`)
- A **Batch** holds many **Issues**; an **Issue** belongs to at most one **Batch**
- A **Batch** declares one **Gate**

## Flagged ambiguities

- "backlog" was previously used to mean both the *tool* hosting issues and the *body of work* inside it — resolved: the tool is the **Issue tracker**; "backlog" is no longer used as a domain term.
- "backlog backend" / "backlog manager" — resolved: collapsed into **Issue tracker**.
