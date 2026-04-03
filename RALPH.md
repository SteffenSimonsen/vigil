---
agent: claude --dangerously-skip-permissions -p
commands:
  - name: next_issue
    run: gh issue list --repo SteffenSimonsen/vigil --state open --json number --jq '[.[].number] | sort | map(select(. != 1)) | .[0]'
    timeout: 30
  - name: issue_labels
    run: gh issue view {{ commands.next_issue }} --repo SteffenSimonsen/vigil --json labels --jq '[.labels[].name]'
    timeout: 30
---

You are implementing vigil, a CLI process manager, using TDD.

The next issue to implement is: #{{ commands.next_issue }}

If `{{ commands.next_issue }}` is empty or null, all issues are complete — output <promise>COMPLETE</promise> and stop.

The issue labels are: {{ commands.issue_labels }}

## Step 1 — Read the issue

Run `gh api repos/SteffenSimonsen/vigil/issues/{{ commands.next_issue }}` to read the full issue body and acceptance criteria.

## Step 2 — Implement with TDD

Use the /tdd skill to implement the issue. Follow red-green-refactor strictly:
- Write ONE failing test, make it pass, repeat.
- Test behavior through public interfaces only — never test implementation details.
- Mock only at system boundaries: OS calls (psutil), filesystem, network (httpx).
- Do NOT mock your own modules.
- Skip user-approval checkpoints — proceed autonomously.
- Refactor only after all tests are green.

## Step 3 — Quality gate

Run the full check and fix ALL errors before continuing:
  uv run ruff check src tests
  uv run ruff format src tests
  uv run pyright
  uv run pytest

## Step 4 — Ship

If the issue labels include `bug`, commit: `fix: <description> (closes #{{ commands.next_issue }})`
Otherwise, commit: `feat: <description> (closes #{{ commands.next_issue }})`

Close the issue: `gh issue close {{ commands.next_issue }} --repo SteffenSimonsen/vigil`

ONLY WORK ON A SINGLE ISSUE PER RUN.
