# Working agreement

## Plan before acting

- Present a plan **before** touching code, and wait for approval.
- Format: short one-sentence bullets, plus an analogy where it aids understanding.
- No long autonomous runs that end in "here's what went wrong and what I fixed" —
  the fix may not be the one wanted.

## Report problems, don't fix them

- Finding a bug is a **report**, not a work order.
- Say what's broken, what it affects, and the proposed fix. Then stop.
- Fixing without asking removes the chance to say "don't bother" or "not like that".

## Git

- **Never commit or merge without explicit permission.**
- One logical change per branch, one concern per commit.
- Merge to `main` only when asked.

### Branch before the first edit

Create the branch before touching a file — not once the code works, not just
before committing. Nearly every git mess in this repo traces back to starting
work on `main` and trying to relocate it afterwards, which turns a one-command
job into a stash, a reset, and a conflict.

- New files get created **on the branch**. A new file left on `main` is
  untracked, and later blocks the pull that would bring in its tracked twin.
- If work has already begun on `main`, stop and move it before going further.

### Branch from what the work depends on

Branch from the thing the work builds on, not from `main` by reflex. Work that
depends on an unmerged branch belongs on top of that branch, with the PR
targeting it — a stacked PR whose diff shows only the new change. Branching
such work from `main` produces conflicts that look like a merge problem but are
really a base problem.

### Deleting branches

Never auto-delete a branch that another PR targets — deleting a base branch
closes the PR stacked on it, and GitHub then refuses to reopen it (the base is
gone) or retarget it (it is closed), leaving a fresh PR as the only way out.

- Do not pass `--delete-branch` when merging a branch that anything is stacked
  on. Delete once the whole stack has landed.

### After every merge

Re-check the state of the *other* open PRs. A merge can close or invalidate
them as collateral, and that is silent.

## Keep the backlog current

`BACKLOG.md` is the project's memory across sessions. Read it before planning
anything, and update it when:

- a workflow lands or changes
- a decision is made or reversed
- a new constraint or known issue is found
- a number worth not re-measuring is measured

It is not a changelog — git already does that. It records what exists, what is
planned, what was decided and why, so a session starting cold does not
re-litigate settled ground or re-derive known facts.

## Scope

- One workflow at a time. Don't build ahead of need.
- Flag genuine forks (a real either/or) rather than silently choosing.

## Environment

- Never interrupt `pip`, `npm install`, or similar. A killed install leaves a
  half-deleted package that still reports as installed, and the wreckage then
  looks like an upstream bug. Run them to completion in the background instead.
