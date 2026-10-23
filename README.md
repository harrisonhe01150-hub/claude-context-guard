# context-guard

让 Claude Code 会话别拖太长、别白烧额度的一组 hook。

起因：Max 20x 的一周额度 3–4 天就用完。查下来，大头是长会话每一轮都要把整段历史重新读一遍（缓存读取占成本 66%）。所以这套 hook 只管一件事：**会话长度**。

## 它做什么

| 时机 | hook | 行为 |
|---|---|---|
| 上下文第一次超过 `warn_tokens`（默认 20 万） | `UserPromptSubmit` → `guard.py prompt` | 让 Claude 在下一条回复的第一行提醒一次：「⚠️ 这个会话已经约 X 万 token，做完手上这件事建议收工开新会话。」 |
| 已压缩 ≥ `handoff_compactions` 次（默认 2），或主会话调用 ≥ `handoff_calls` 次（默认 500） | `Stop` → `guard.py stop` | 拦一次停止，让 Claude 先交接：覆盖写工作文件夹 `CLAUDE.md` 的「## 最近进展」段（最多 15 行），跑 obsidian-save，再给你一句开新 chat 用的开场白。每个会话只拦一次。 |
| 准备自动压缩时 | `PreCompact`（只匹配 `auto`）→ `guard.py precompact` | 任务没做完就先不压：任务列表开着还没收尾，或 Claude 正在调用工具。任务做完后下一次再压。上下文超过 `compact_hard_cap`（默认 60 万）照样压；手动 `/compact` 永远不拦。 |

出任何错都静默退出（错误记到 `guard.log`），不会弄坏会话。

## 安装

1. 把这个文件夹放到 `~/.claude/context-guard/`（`git clone` 到那里就行）。
2. 把 `settings.example.json` 里的 `hooks` 合并进 `~/.claude/settings.json`，`<you>` 换成你的用户名，`python` 换成你的 Python 完整路径也可以。已有的 hook 不用删，同一事件下多加一项即可。
3. 可选：`autoCompactWindow` 控制多大开始自动压缩（10 万–100 万）。
4. 可选：复制 `config.example.json` 为 `config.json` 改阈值。`compact_hard_cap` 要比 `autoCompactWindow` 大，否则「任务没做完不压缩」不起作用。

自用的配置：自动压缩 80 万、提醒 40 万、保险上限 90 万。

## 配置项（`config.json`）

| 键 | 默认 | 意思 |
|---|---|---|
| `warn_tokens` | 200000 | 上下文到多少提醒一次 |
| `handoff_compactions` | 2 | 压缩几次后触发交接 |
| `handoff_calls` | 500 | 主会话调用多少次后触发交接 |
| `compact_hard_cap` | 600000 | 超过就不再拦自动压缩 |
| `overrides` | `{}` | 按 session_id 单独覆盖，例如 `{"<session_id>": {"warn_tokens": 100000}}` |

环境变量 `CONTEXT_GUARD_STATE`、`CONTEXT_GUARD_CONFIG` 可以换状态目录和配置文件（测试用）。

## 用量统计

```bash
python -I tools/usage.py 14
```

按天、主会话 / 子 agent / workflow、模型、项目、会话汇总最近 N 天 `~/.claude/projects` 里的用量，按近似 API 价格折算成「等效成本」。改完设置一周后跑一次对比效果。

## 测试

```bash
python -m unittest discover -s tests -v
```

用合成的会话记录按 Claude Code 的方式（stdin 进 JSON、stdout 出 JSON）跑三种模式，共 13 条。

## 已知限制

- 桌面 App 的 Code 页不显示 hook 的 `systemMessage`，所以提醒是注入给 Claude、让它自己说出来的。
- hook 不能直接执行 `/compact`，所以「每个任务后压缩」是靠调小 `autoCompactWindow` + 任务中途拦自动压缩来近似的。
- 「任务列表开着」靠桌面 App 的 `mcp__ccd_turn__update_plan` / `mcp__ccd_turn__wrap_up` 判断；在命令行里只有「正在调用工具」这一条起作用。
- 任务中途不压缩，意味着长任务的上下文会一直涨到 `compact_hard_cap`，会多花一些额度。

## 许可证

MIT，见 [LICENSE](LICENSE)。
