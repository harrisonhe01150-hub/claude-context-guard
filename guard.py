"""context-guard: hooks that keep Claude Code sessions short.

- `guard.py prompt` (UserPromptSubmit): context first reaches warn_tokens -> one reminder,
  injected as context so Claude says it on the first line of its reply
  (the desktop app does not show a hook's systemMessage).
- `guard.py stop` (Stop): session compacted >= handoff_compactions times, or main-session
  calls >= handoff_calls -> once per session, block the stop and have Claude write the
  handoff into the working folder's CLAUDE.md「最近进展」section, run obsidian-save, and
  tell the user to open a new chat.
- `guard.py precompact` (PreCompact, auto only): block auto-compaction while a mission is
  still in progress, so it happens between missions instead; above compact_hard_cap it is
  always allowed.
Thresholds can be overridden in config.json next to this file.
Any error -> exit 0 silently (never break a session).
"""
import json, os, re, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("CONTEXT_GUARD_STATE", HERE / "state"))
LOG = HERE / "guard.log"
CONFIG = Path(os.environ.get("CONTEXT_GUARD_CONFIG", HERE / "config.json"))

DEFAULTS = {"warn_tokens": 200_000, "handoff_compactions": 2, "handoff_calls": 500,
            "compact_hard_cap": 600_000}
SECTION = "## 最近进展"

MSG_ID = re.compile(rb'"id":"(msg_[A-Za-z0-9]+)"')
PLAN_CALL = b'"name":"mcp__ccd_turn__update_plan"'
WRAP_CALL = b'"name":"mcp__ccd_turn__wrap_up"'


def mission_in_progress(data):
    """True while a mission is unfinished: the desktop task list was opened and not yet
    wrapped up, or Claude is mid tool loop (its last message ends in a tool call)."""
    if data.rfind(PLAN_CALL) > data.rfind(WRAP_CALL):
        return True
    for line in reversed(data.splitlines()):
        if b'"role":"assistant"' not in line:
            continue
        try:
            content = json.loads(line)["message"]["content"]
        except (ValueError, KeyError, TypeError):
            continue
        last = content[-1] if isinstance(content, list) and content else {}
        return last.get("type") == "tool_use" and last.get("name") != "mcp__ccd_turn__wrap_up"
    return False


def config(session_id):
    cfg = dict(DEFAULTS)
    try:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in raw.items() if k in DEFAULTS})
        cfg.update(raw.get("overrides", {}).get(session_id, {}))
    except (OSError, ValueError):
        pass
    return cfg


def scan(transcript):
    """Return (current context tokens, compactions, main-session calls)."""
    data = Path(transcript).read_bytes()
    compactions = data.count(b'"subtype":"compact_boundary"')
    calls = len({m for m in MSG_ID.findall(data)})
    ctx = 0
    for line in reversed(data.splitlines()):
        if b'"usage"' not in line or b'"role":"assistant"' not in line:
            continue
        try:
            u = json.loads(line)["message"]["usage"]
        except (ValueError, KeyError, TypeError):
            continue
        ctx = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
        break
    return ctx, compactions, calls


def handoff_reason(cwd, session_id, why):
    claude_md = Path(cwd) / "CLAUDE.md"
    today = time.strftime("%Y-%m-%d")
    return f"""[context-guard] 这个会话已经很长（{why}），继续用会很费额度。停下之前做完这三步，然后结束这一轮，不要开始新的工作：

1. 更新交接：文件 `{claude_md}`。
   - 找到以「{SECTION}」开头的段（到下一个「## 」标题或文件末尾为止），整段**覆盖**；没有这一段就加在文件末尾；文件不存在就新建，只写这一段。
   - 段内最多 15 行，格式：
     {SECTION}（context-guard 自动维护，覆盖写，最多 15 行）
     更新：{today} · 会话 {session_id[:8]}
     - 在做：…
     - 做到：…（已完成 / 已验证 / 没验证的分开写）
     - 下一步：…
     - 关键决定：…
     - 关键文件：…
   - 不动这个文件里的其他任何内容；不写任何账号、密码、key、token 的具体值；不要 git commit。
   - 改完用 Read 看一眼这一段，确认写对了（OneDrive 文件尤其要确认）。
2. 如果有 obsidian-save 技能，运行它存这次会话的总结（session {session_id}）；没有就跳过这一步。
3. 用一两句话告诉用户：会话太长了，请开一个新 chat；并给出一句可以直接粘贴的开场白，例如「接着做：先读 CLAUDE.md 的『最近进展』段，然后继续下一步」。"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        mode = sys.argv[1] if len(sys.argv) > 1 else "stop"
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
        if payload.get("stop_hook_active"):
            return
        session_id = payload.get("session_id") or ""
        transcript = payload.get("transcript_path")
        cwd = payload.get("cwd") or os.getcwd()
        if not session_id or not transcript or not Path(transcript).exists():
            return

        cfg = config(session_id)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file = STATE_DIR / f"{session_id}.json"
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}

        ctx, compactions, calls = scan(transcript)
        out = None
        if mode == "stop":
            if not state.get("handed_off") and (compactions >= cfg["handoff_compactions"] or calls >= cfg["handoff_calls"]):
                why = f"已压缩 {compactions} 次" if compactions >= cfg["handoff_compactions"] else f"已调用 {calls} 次"
                state["handed_off"] = state["warned"] = True
                out = {"decision": "block", "reason": handoff_reason(cwd, session_id, why)}
        elif mode == "precompact":
            if payload.get("trigger") == "auto" and ctx < cfg["compact_hard_cap"] \
                    and mission_in_progress(Path(transcript).read_bytes()):
                state["compact_blocked"] = state.get("compact_blocked", 0) + 1
                out = {"decision": "block", "reason": "context-guard：任务还没做完，等这个任务结束后再压缩。"}
        elif mode == "prompt":
            # 桌面 App 不显示 hook 的 systemMessage，所以让 Claude 在回复第一行说
            if not state.get("warned") and ctx >= cfg["warn_tokens"]:
                state["warned"] = True
                note = (f"[context-guard] 这个会话上下文已经约 {ctx // 10000} 万 token。请在这次回复的第一行，"
                        f"用一句话提醒用户：「⚠️ 这个会话已经约 {ctx // 10000} 万 token，做完手上这件事建议收工开新会话。」然后正常回答。")
                out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": note}}

        if out:
            state.update(ctx=ctx, compactions=compactions, calls=calls, at=time.strftime("%Y-%m-%d %H:%M:%S"))
            state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            print(json.dumps(out, ensure_ascii=False))
    except Exception as e:  # never break the session
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {type(e).__name__}: {e}\n")
        except OSError:
            pass


if __name__ == "__main__":
    main()
