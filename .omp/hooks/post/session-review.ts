/**
 * session-review hook — end-of-session self-learning for this repo.
 *
 * - `session_shutdown`: spawn a detached `omp -p` review run that hands the
 *   just-finished session file to the `session-review` subagent (positional
 *   arg = parse as-is), which appends noteworthy findings to the raw journal
 *   (.omp/agents/session-review/journal.md) via `learnings.py append`, then
 *   integrates them into matching topical sections of AGENTS.md as undated
 *   auto bullets. Before spawning, a pending marker
 *   (`.omp/hooks/.pending-review`, git-ignored) is written so a failed
 *   detached spawn is retried on the next `session_start`. When the journal
 *   reaches JOURNAL_CAP bullets or file-wide auto bullets in AGENTS.md reach
 *   AUTO_BULLET_BUDGET, a consolidation run is spawned instead (rewrites
 *   only auto bullets in AGENTS.md and drains the journal).
 * - `session_start`: if a pending marker exists, consume it and retry the
 *   detached review of that session file.
 * - `/session-review [N]`: manually enqueue a review of the current session
 *   plus the last N-1 newest top-level sessions of this project's bucket.
 *   `/session-review consolidate`: enqueue a consolidation run.
 *
 * Recursion guards (each an early silent return):
 *   1. OMP_SESSION_REVIEW=1 — we are a detached review run (fires in every
 *      mode incl. print mode, so the review run itself would re-trigger).
 *   2. session_init entry carries `agent` — subagent session (extension
 *      factories are rebound into restricted task/eval children).
 *   3. no assistant message in the branch — empty session, nothing to learn.
 * The parser additionally never reads subagent transcript subdirectories,
 * skips forks (parentSession) and marker-marked review runs.
 */
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { execFileSync, spawn } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

const MARKER = "SESSION-REVIEW-RUN:";
const ENV_GUARD = "OMP_SESSION_REVIEW";
const PARSER = ".omp/agents/session-review/scripts/parse_sessions.py";
const LEARNINGS = ".omp/agents/session-review/scripts/learnings.py";
const PENDING_FILE = ".omp/hooks/.pending-review";
const JOURNAL_CAP = 100; // journal bullets that trigger consolidation
const AUTO_BULLET_BUDGET = 60; // file-wide "(src: …)" auto bullets in AGENTS.md that trigger consolidation
const JOURNAL_FILE = ".omp/agents/session-review/journal.md";
const JOURNAL_HEADING = "## Journal";

function isSubagentSession(ctx: ExtensionContext): boolean {
	for (const entry of ctx.sessionManager.getBranch()) {
		if (entry.type === "session_init" && typeof entry.agent === "string") return true;
	}
	return false;
}

function hasAssistantMessage(ctx: ExtensionContext): boolean {
	for (const entry of ctx.sessionManager.getBranch()) {
		if (entry.type === "message" && entry.message.role === "assistant") return true;
	}
	return false;
}

/** CLI argv that reproduces this omp invocation (bun cli.js entry, else `omp` on PATH). */
function cliCommand(): string[] {
	const argv1 = process.argv[1];
	if (argv1 && argv1.endsWith("cli.js")) return [process.execPath, argv1];
	return ["omp"];
}

/** Detached, unref'd print-mode run; survives the 2s session_shutdown budget. */
function spawnDetachedReview(prompt: string, cwd: string): void {
	const cli = cliCommand();
	spawn(cli[0], [...cli.slice(1), "-p", prompt], {
		cwd,
		detached: true,
		stdio: "ignore",
		env: { ...process.env, [ENV_GUARD]: "1" },
	}).unref();
}

/** Atomic pending-marker write: JSON to PENDING_FILE.tmp, then rename. */
function writePending(cwd: string, sessionFile: string): void {
	const target = path.resolve(cwd, PENDING_FILE);
	const tmp = target + ".tmp";
	// "wx" = O_CREAT|O_EXCL: refuse to write through a pre-existing file/symlink
	const fd = fs.openSync(tmp, "wx");
	try {
		fs.writeFileSync(fd, JSON.stringify({ sessionFile, at: new Date().toISOString() }));
	} finally {
		fs.closeSync(fd);
	}
	fs.renameSync(tmp, target);
}

/** Session file recorded in the pending marker, or null when absent/invalid. */
function readPending(cwd: string): string | null {
	try {
		const raw = fs.readFileSync(path.resolve(cwd, PENDING_FILE), "utf8");
		const obj = JSON.parse(raw) as { sessionFile?: unknown };
		return typeof obj.sessionFile === "string" ? obj.sessionFile : null;
	} catch {
		return null;
	}
}

function deletePending(cwd: string): void {
	fs.rmSync(path.resolve(cwd, PENDING_FILE), { force: true });
}

/** Count "- " bullets in the "## Journal" section of <cwd>/JOURNAL_FILE (0 on any error). */
function journalBulletCount(cwd: string): number {
	try {
		const text = fs.readFileSync(path.resolve(cwd, JOURNAL_FILE), "utf8");
		const start = text.indexOf(JOURNAL_HEADING);
		if (start < 0) return 0;
		const lines = text.slice(start).split("\n").slice(1);
		let end = lines.length;
		for (let i = 0; i < lines.length; i++) {
			if (lines[i].startsWith("## ")) {
				end = i;
				break;
			}
		}
		return lines.slice(0, end).filter((l) => l.startsWith("- ")).length;
	} catch {
		return 0;
	}
}

/** Count file-wide auto bullets ("- … (src: <8 hex>)") in <cwd>/AGENTS.md via `count --all` (0 on any error). */
function autoBulletCount(cwd: string): number {
	try {
		const out = execFileSync(
			"python3",
			[LEARNINGS, "count", "--all", "--file", path.resolve(cwd, "AGENTS.md")],
			{ encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 1500 },
		);
		return Number.parseInt(out.trim(), 10) || 0;
	} catch {
		return 0;
	}
}

/** Review prompt for one finished session file (positional parser arg). */
function buildReviewPrompt(sessionFile: string, cwd: string): string {
	return [
		`${MARKER} automatic end-of-session review.`,
		`Call the \`task\` tool exactly once with agent "session-review".`,
		`Task text: review exactly this finished omp session transcript: ${sessionFile}`,
		`Run \`python3 ${PARSER} "${sessionFile}"\` from cwd ${cwd} (positional file arg = parse as-is, no selection),`,
		`read the condensed output, then follow the session-review agent's instructions.`,
		`Do not spawn any other subagent; do not review any other session.`,
	].join(" ");
}

/** Consolidation prompt: rewrite only auto bullets ("(src: …)" lines) file-wide. */
function buildConsolidatePrompt(cwd: string): string {
	return `${MARKER} consolidation run. Call the \`task\` tool exactly once with agent "session-review" and task text: "consolidation mode" per your agent file — in ${cwd}/AGENTS.md rewrite ONLY auto bullets (lines matching "- … (src: <8 hex>)"): merge duplicates, resolve contradictions keeping the newer finding, retire stale items, drop anything already covered by AGENTS.md prose or .omp/skills/ or .omp/agents/, enforce AUTO_BULLET_BUDGET (${AUTO_BULLET_BUDGET}) file-wide, and drain ${JOURNAL_FILE} under JOURNAL_CAP (${JOURNAL_CAP}) by moving durable items into matching AGENTS.md sections; auto bullets stay single-line (NEVER hard-wrap a bullet — the "(src: …)" tag must end its only line) and NEVER add a new "## " heading to AGENTS.md (in particular no "## Session-review" or "## Session learnings" chapter — automation meta-content lives in .omp/, never AGENTS.md); every non-auto line of AGENTS.md MUST stay byte-identical (journal.md is 100% auto-owned and may be rewritten wholesale); finish by running \`git -C ${cwd} diff AGENTS.md | python3 ${LEARNINGS} verify\` and requiring exit 0 (only single-line "(src:" bullets changed, no new headings).`;
}

export default function sessionReviewHook(pi: ExtensionAPI): void {
	pi.on("session_shutdown", (_event, ctx) => {
		try {
			if (process.env[ENV_GUARD] === "1") return; // we are a review run
			if (isSubagentSession(ctx)) return; // subagent session
			if (!hasAssistantMessage(ctx)) return; // empty session
			const sessionFile = ctx.sessionManager.getSessionFile();
			if (!sessionFile) {
				pi.logger.warn("session-review: no session file at shutdown, skipping");
				return;
			}
		// Journal full or auto-bullet budget reached: consolidate instead of
		// appending more (no pending marker).
		if (journalBulletCount(ctx.cwd) >= JOURNAL_CAP || autoBulletCount(ctx.cwd) >= AUTO_BULLET_BUDGET) {
			spawnDetachedReview(buildConsolidatePrompt(ctx.cwd), ctx.cwd);
			pi.logger.info("session-review: budget reached, spawned consolidation run");
			return;
		}
			// Record a pending marker so a failed detached spawn is retried at
			// the next session_start; the marker is consumed on retry.
			try {
				writePending(ctx.cwd, sessionFile);
			} catch (err) {
				pi.logger.warn("session-review: could not write pending marker", { error: String(err) });
			}
			// At session_shutdown the transcript is already durable on disk; pass
			// the file positionally so the parser reviews exactly this session.
			spawnDetachedReview(buildReviewPrompt(sessionFile, ctx.cwd), ctx.cwd);
			pi.logger.info("session-review: spawned detached review", { sessionFile });
		} catch (err) {
			// session_shutdown has a 2s budget and must never break shutdown.
			pi.logger.warn("session-review: shutdown hook failed", { error: String(err) });
		}
	});

	pi.on("session_start", (_event, ctx) => {
		try {
			if (process.env[ENV_GUARD] === "1") return; // we are a review run
			if (isSubagentSession(ctx)) return; // subagent session
			const pending = readPending(ctx.cwd);
			if (!pending) return;
			deletePending(ctx.cwd);
			spawnDetachedReview(buildReviewPrompt(pending, ctx.cwd), ctx.cwd);
			pi.logger.info("session-review: retried pending review from session_start", { sessionFile: pending });
		} catch (err) {
			// session_start must never break startup.
			pi.logger.warn("session-review: session_start hook failed", { error: String(err) });
		}
	});

	pi.registerCommand("session-review", {
		description: "Review the last N omp sessions (default 1) with the session-review subagent: findings go to the raw journal (.omp/agents/session-review/journal.md) and are integrated into matching AGENTS.md sections; 'consolidate' rewrites auto bullets instead",
		handler: async (args, ctx) => {
			const raw = args.trim();
			if (raw === "consolidate") {
				await ctx.waitForIdle();
				pi.sendUserMessage(buildConsolidatePrompt(ctx.cwd));
				if (ctx.hasUI) ctx.ui.notify("Queued consolidation", "info");
				return;
			}
			let n = 1;
			if (raw.length > 0) {
				if (!/^\d+$/.test(raw)) {
					ctx.ui.notify("Usage: /session-review [N | consolidate] — N is a whole number from 1 to 20", "warning");
					return;
				}
				n = Math.min(20, Math.max(1, Number.parseInt(raw, 10)));
			}
			const sessionFile = ctx.sessionManager.getSessionFile();
			if (!sessionFile) {
				ctx.ui.notify("session-review: no session file for this session", "error");
				return;
			}
			const dir = path.dirname(sessionFile);
			// --include guarantees the current session is reviewed first; --last N
			// selects the N newest top-level main sessions of this bucket (the
			// parser never reads subagent subdirs, forks, or marker review runs).
			const message = [
				"Run a session review now: call the `task` tool exactly once with agent \"session-review\".",
				`Task text: review the last ${n} session(s) of this project by running, from ${ctx.cwd}:`,
				`python3 ${PARSER} --dir "${dir}" --last ${n} --include "${sessionFile}"`,
				"then follow the session-review agent's instructions.",
			].join(" ");
			await ctx.waitForIdle();
			// sendUserMessage starts a turn when idle (we just waited for idle).
			pi.sendUserMessage(message);
			if (ctx.hasUI) ctx.ui.notify(`Queued session review of the last ${n} session(s)`, "info");
		},
	});
}
