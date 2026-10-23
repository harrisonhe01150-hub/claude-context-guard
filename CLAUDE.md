# CLAUDE.md — context-guard

Notes for a Claude Code agent installing, tuning or changing this repo for its user.
Reply to the user in their own language. The human-facing docs are in `README.md` (Chinese).

## What this is

Three Claude Code hooks in one script, `guard.py`, that keep sessions short so the
weekly usage limit lasts longer. In long sessions most of the cost is re-reading
history (cache reads), so the only thing it manages is session length:

- `guard.py prompt` (UserPromptSubmit): the first time context passes `warn_tokens`,
  inject one note so Claude warns the user on the first line of its reply.
- `guard.py stop` (Stop): after `handoff_compactions` compactions or `handoff_calls`
  main-session calls, block the stop once and make Claude write a handoff into the
  working folder's `CLAUDE.md`「## 最近进展」section, then tell the user to open a new chat.
- `guard.py precompact` (PreCompact, matcher `auto`): block auto-compaction while a
  task is still in progress; allow it above `compact_hard_cap`. Manual `/compact` is never blocked.

No dependencies beyond the Python 3 standard library.

## Installing it for your user

Ask the user before editing their `~/.claude/settings.json`, and show them the diff.

1. Clone this repo to `~/.claude/context-guard/` (the path matters only because the
   hook commands point at it).
2. Find the absolute Python path: `where python` (Windows) / `command -v python3`
   (macOS/Linux). On Windows avoid the `WindowsApps\python.exe` Store stub.
3. Merge the `hooks` block from `settings.example.json` into `~/.claude/settings.json`:
   - replace `python` with the absolute path from step 2 and `C:/Users/<you>` with the
     real home directory (hook args are not shell-expanded, so no `~`);
   - **append** to existing event arrays, never replace the user's existing hooks;
   - keep the file valid JSON (parse it back after editing).
4. Optionally set `autoCompactWindow` (100000–1000000). Ask the user what they want;
   the README lists the author's own values.
5. Optionally copy `config.example.json` to `config.json` and tune it. Keep
   `compact_hard_cap` above `autoCompactWindow`, otherwise the precompact rule never fires.
6. Run the tests (below). The hooks take effect in the next new session.

To uninstall: remove the three `context-guard` entries from `settings.json`.

## Things to adapt for a new user

- The handoff and reminder texts are written in Chinese. If the user wants another
  language, edit `handoff_reason()` and the `note` string in `main()`, and update the
  assertions in `tests/test_guard.py` that match on that text.
- The handoff runs the `obsidian-save` skill only if the user has it; otherwise that
  step is skipped.
- "Task list open" is detected from the desktop app's `mcp__ccd_turn__update_plan` /
  `mcp__ccd_turn__wrap_up` tool calls. In the terminal CLI only the "last assistant
  message ends in a tool call" rule applies.

## Changing the code

- Run tests: `python -m unittest discover -s tests -v` (13 tests, ~1 s).
- Every behaviour change gets a test in `tests/test_guard.py`. Tests run `guard.py` as a
  subprocess with JSON on stdin, the way Claude Code calls it, against synthetic
  transcripts. They isolate state and config through the `CONTEXT_GUARD_STATE` and
  `CONTEXT_GUARD_CONFIG` env vars, so they never touch the real `state/` or `config.json`.
- `guard.py` must never break a session: any exception is caught, appended to
  `guard.log`, and the script exits 0 with no output. Keep it that way.
- Transcript matching is on raw bytes of compact JSON (`"role":"assistant"`, no spaces),
  matching how Claude Code writes `~/.claude/projects/**/*.jsonl`. Test fixtures must use
  `separators=(",", ":")`.
- Per-session state (`warned`, `handed_off`, `compact_blocked`) lives in
  `state/<session_id>.json`, so each reminder and handoff fires once per session.
- Hooks cannot run `/compact` themselves, and the desktop app does not display a hook's
  `systemMessage`. That is why the reminder is injected as context and compaction is
  steered via `autoCompactWindow` + the PreCompact block.

## Do not commit

`state/`, `guard.log`, `config.json` (all in `.gitignore`). They are per-machine and
`state/` holds session IDs.

`tools/usage.py [days]` prints a token-usage breakdown from `~/.claude/projects`. It is
read-only and handy for checking whether the settings helped.
