"""Behaviour tests for guard.py: run each hook mode the way Claude Code does
(JSON on stdin, JSON on stdout) against synthetic transcripts.

    python -m unittest discover -s tests
"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "guard.py"


def line(obj):
    # real transcripts are compact JSON, and guard.py matches on that
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def assistant(i, ctx=1000, content=None):
    return line({"type": "assistant", "message": {
        "id": f"msg_{i:05d}", "role": "assistant",
        "content": content or [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 10, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": ctx - 10, "output_tokens": 5}}})


def tool(name):
    return [{"type": "tool_use", "id": "toolu_1", "name": name, "input": {}}]


COMPACT = line({"type": "system", "subtype": "compact_boundary"})


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = dict(os.environ, CONTEXT_GUARD_STATE=str(self.dir / "state"),
                        CONTEXT_GUARD_CONFIG=str(self.dir / "config.json"))
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def transcript(self, *lines):
        self.n += 1
        p = self.dir / f"t{self.n}.jsonl"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def run_guard(self, mode, transcript, session="s1", **extra):
        payload = dict(session_id=session, transcript_path=str(transcript),
                       cwd=str(self.dir), **extra)
        r = subprocess.run([sys.executable, str(GUARD), mode], input=json.dumps(payload).encode(),
                           capture_output=True, env=self.env, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.decode("utf-8").strip()
        return json.loads(out) if out else None

    # prompt: one reminder once context passes warn_tokens
    def test_prompt_quiet_when_small(self):
        self.assertIsNone(self.run_guard("prompt", self.transcript(assistant(1, ctx=50_000))))

    def test_prompt_warns_once(self):
        t = self.transcript(assistant(1, ctx=250_000))
        out = self.run_guard("prompt", t)
        self.assertIn("25 万", out["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.run_guard("prompt", t))

    def test_config_overrides_threshold(self):
        (self.dir / "config.json").write_text('{"warn_tokens": 400000}', encoding="utf-8")
        self.assertIsNone(self.run_guard("prompt", self.transcript(assistant(1, ctx=250_000))))

    # stop: hand off once after too many compactions or calls
    def test_stop_quiet_in_short_session(self):
        self.assertIsNone(self.run_guard("stop", self.transcript(assistant(1), COMPACT)))

    def test_stop_hands_off_after_two_compactions(self):
        t = self.transcript(assistant(1), COMPACT, assistant(2), COMPACT, assistant(3))
        out = self.run_guard("stop", t)
        self.assertEqual(out["decision"], "block")
        self.assertIn("已压缩 2 次", out["reason"])
        self.assertIn("CLAUDE.md", out["reason"])
        self.assertIsNone(self.run_guard("stop", t))

    def test_stop_hands_off_after_many_calls(self):
        out = self.run_guard("stop", self.transcript(*(assistant(i) for i in range(500))))
        self.assertIn("已调用 500 次", out["reason"])

    def test_stop_respects_stop_hook_active(self):
        t = self.transcript(assistant(1), COMPACT, COMPACT)
        self.assertIsNone(self.run_guard("stop", t, stop_hook_active=True))

    # precompact: no auto-compaction mid-mission, unless over the hard cap
    def test_precompact_blocks_while_task_list_open(self):
        t = self.transcript(assistant(1, content=tool("mcp__ccd_turn__update_plan")), assistant(2))
        self.assertEqual(self.run_guard("precompact", t, trigger="auto")["decision"], "block")

    def test_precompact_blocks_mid_tool_call(self):
        t = self.transcript(assistant(1, content=tool("Bash")))
        self.assertEqual(self.run_guard("precompact", t, trigger="auto")["decision"], "block")

    def test_precompact_allows_after_wrap_up(self):
        t = self.transcript(assistant(1, content=tool("mcp__ccd_turn__update_plan")),
                            assistant(2, content=tool("mcp__ccd_turn__wrap_up")), assistant(3))
        self.assertIsNone(self.run_guard("precompact", t, trigger="auto"))

    def test_precompact_never_blocks_manual(self):
        t = self.transcript(assistant(1, content=tool("Bash")))
        self.assertIsNone(self.run_guard("precompact", t, trigger="manual"))

    def test_precompact_allows_over_hard_cap(self):
        t = self.transcript(assistant(1, ctx=700_000, content=tool("Bash")))
        self.assertIsNone(self.run_guard("precompact", t, trigger="auto"))

    # never break a session
    def test_bad_input_exits_quietly(self):
        self.assertIsNone(self.run_guard("stop", self.dir / "missing.jsonl"))


if __name__ == "__main__":
    unittest.main()
