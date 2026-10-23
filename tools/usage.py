"""Where did my Claude Code tokens go? Aggregates ~/.claude/projects transcripts.

    python tools/usage.py [days]   (default 14)
"""
import json, os, sys, time, collections, re
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 14
cutoff = time.time() - DAYS * 86400

# 权重：近似 API 价格比例（以普通输入=1）。额度大致按成本扣，用它当“等效成本”
W = dict(inp=1.0, cw5=1.25, cw1h=2.0, cr=0.1, out=5.0)

msgs = {}  # message id -> record (流式会写多行，取最后一行)
for f in ROOT.rglob("*.jsonl"):
    if f.stat().st_mtime < cutoff:
        continue
    rel = f.relative_to(ROOT).parts
    project = rel[0]
    session = rel[1].replace(".jsonl", "")
    if "workflows" in rel:
        kind = "workflow"
    elif "subagents" in rel:
        kind = "subagent"
    else:
        kind = "main"
    try:
        fh = open(f, encoding="utf-8", errors="replace")
    except OSError:
        continue
    with fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = d.get("message") or {}
            u = m.get("usage")
            if not u or m.get("role") != "assistant":
                continue
            ts = d.get("timestamp", "")
            mid = m.get("id") or (str(f) + ts)
            cc = u.get("cache_creation") or {}
            cw1h = cc.get("ephemeral_1h_input_tokens", 0) or 0
            cwall = u.get("cache_creation_input_tokens", 0) or 0
            msgs[mid] = dict(
                project=project, session=session, kind=kind, file=str(f),
                model=m.get("model", "?"), day=ts[:10],
                inp=u.get("input_tokens", 0) or 0,
                cw5=cwall - cw1h, cw1h=cw1h,
                cr=u.get("cache_read_input_tokens", 0) or 0,
                out=u.get("output_tokens", 0) or 0,
            )

def cost(r):
    return sum(r[k] * W[k] for k in W)

def agg(keyf):
    a = collections.defaultdict(lambda: collections.Counter())
    for r in msgs.values():
        k = keyf(r)
        c = a[k]
        for x in ("inp", "cw5", "cw1h", "cr", "out"):
            c[x] += r[x]
        c["cost"] += cost(r)
        c["n"] += 1
    return a

total = sum(cost(r) for r in msgs.values())
M = lambda x: f"{x/1e6:8.1f}M"

def show(title, a, top=15):
    print(f"\n=== {title} ===")
    print(f"{'key':60} {'share':>6} {'cost':>9} {'calls':>6} {'cacheRd':>9} {'cacheWr':>9} {'out':>9}")
    for k, c in sorted(a.items(), key=lambda kv: -kv[1]["cost"])[:top]:
        print(f"{str(k)[:60]:60} {c['cost']/total*100:5.1f}% {M(c['cost'])} {c['n']:6} {M(c['cr'])} {M(c['cw5']+c['cw1h'])} {M(c['out'])}")

print(f"messages: {len(msgs)}  total equiv cost: {M(total)}  (last {DAYS} days)")
tot = agg(lambda r: "ALL")["ALL"]
print("token mix share of cost: " + ", ".join(f"{k}={tot[k]*W[k]/total*100:.0f}%" for k in W))
show("by day", agg(lambda r: r["day"]), 20)
show("by kind (main / subagent / workflow)", agg(lambda r: r["kind"]))
show("by model", agg(lambda r: r["model"]))
show("by project", agg(lambda r: r["project"]))
show("by session (top)", agg(lambda r: (r["project"][-25:], r["session"][:8])), 15)
show("by single transcript file (top)", agg(lambda r: r["file"].split("projects")[1][-90:]), 12)

# 主会话里每次调用平均上下文多大（越大说明会话越长）
ctx = [r["inp"] + r["cw5"] + r["cw1h"] + r["cr"] for r in msgs.values() if r["kind"] == "main"]
ctx.sort()
if ctx:
    print(f"\nmain-session context per call: median {ctx[len(ctx)//2]/1e3:.0f}k, p90 {ctx[int(len(ctx)*.9)]/1e3:.0f}k, max {ctx[-1]/1e3:.0f}k")
