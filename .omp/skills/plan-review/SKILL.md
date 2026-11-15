---
name: plan-review
description: Use automatically whenever plan mode is active or a plan is written, reviewed, or proposed (/plan, Plan Review, plan draft at local://<slug>-plan.md, xd://propose). Review plans for clear logical step order.
---

# Plan review

"Way of working" — every plan step MUST carry explicit guidance, guardrails, and a success Check, and MUST be tracked as a task.

Review a plan against all sections below BEFORE writing it to `xd://propose`. A plan that leaves a design decision to the implementer FAILED — deepen the step instead.

## 1. Clear, logical steps
- Steps MUST be ordered so the change builds incrementally and existing tests still pass after each step; state dependencies and independencies explicitly.
- Each step MUST be one concrete action: verb + exact target (file, symbol, anchor) + new behavior — NEVER just an area to "update" or "handle".
- Every requested outcome MUST map to a step; add nothing beyond the ask.
- Reuse existing patterns first (discover via glob/grep/read/scout); write new code only with a one-line statement that no equivalent exists.

## 2. Later steps MUST NOT rewrite earlier steps
- A later step MUST NOT recreate, replace, or re-patch an artifact an earlier step created (no duplicate implementation, no second convention).
- If a later step must touch an earlier artifact, it MUST say "update" and name the exact anchor (path + symbol/lines), and MUST NOT undo or contradict the earlier step.
- Steps editing the same file MUST instruct re-reading before the next edit (anchors shift after every edit); if a multi-part edit is rejected, apply it as separate single edits.

## 3. Guidance, guardrails, success Check per step
- Every step MUST carry all three: explicit guidance (how), guardrails (MUST / MUST NOT / NEVER boundaries), and a success Check (observable result proving the step).
- Use imperative RFC 2119 keywords (MUST, MUST NOT/NEVER, SHOULD, MAY) — required for skills and plans in this repo.
- New/changed symbols MUST give the exact signature or literal (enum member, config key, wire/JSON field); renames/removals MUST list every callsite (exact grep) plus deletions; default clean cutover — no shims, aliases, or dead code.

## 4. Steps MUST become tasks, closed before the next step
- Every plan MUST instruct: create one todo task per plan step before executing (`todo init`/`append`); start the earliest pending step.
- Every step MUST close its matching todo task (`todo done`) before a new step is executed — mark it `done` only after the step's success Check passes (RULES.md: mark the step completed before finishing it); a step whose Check has not passed MUST NOT be closed and MUST NOT let the next step start.
- `todo` MUST be emitted in the same response as the step's real tool call — a todo-only turn is wasted.

## 5. Subagent flag per step
- Each step MUST state whether it benefits from a subagent:
  - independent, self-contained slices → fan out in one `task` batch (user says "parallel" → MUST use subagents); max 32 concurrent;
  - dependent steps → sequential, never parallelized;
  - read-only exploration of unknown code → `scout` only;
  - shared edits → one integration owner; siblings coordinate via `write agent://<id>`.

## 6. Required sections and banned content
- Plan MUST contain: Goal (one clear sentence stating the end state the plan delivers — distinct from Context, which is the literal ask), Context (2–4 sentences, the literal ask), Approach (ordered steps per sections 1–5), Critical files & anchors (at most 5 files: path + symbol/region + one-line reason), Verification (end-to-end proof: concrete input → observable output, exact commands + cwd + fixtures, at least 1 new-behavior check), Assumptions & contingencies (only user-overridable decisions, each with a pre-decided fallback "if reality is X, do Y").
- Plan MUST NOT contain decision-free sections (Non-Goals, Out of Scope, Alternatives, Risks, Future Work) — a scope boundary is one inline line at the temptation point.
- Ground every claim in this session's discovery (glob/grep/read/scout); unconfirmed facts MUST be marked "unverified — confirm first", NEVER stated as settled.
- NEVER reference the planning conversation ("as discussed") — the implementer sees only the plan file.
