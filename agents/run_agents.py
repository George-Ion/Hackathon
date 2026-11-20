"""Worker + critic agents on the OpenAI API, driven by AGENT_PLAN.md and DONE.md.

  python agents/run_agents.py --tasks P0-1,P0-2 --budget 10
  python agents/run_agents.py --tasks P0-1 --dry-run        # print the task text only

For each task: the worker edits code and reports; the critic checks independently and returns
PASS / FAIL / ESCALATE. PASS -> local git commit. FAIL -> the worker gets the critic's fix (max 3 rounds).
BLOCKED / ESCALATE / budget reached -> stop and leave the working tree for a human.

Guardrails: agents can only touch files inside the repo; they can never read .env or write to
data, listeners, the plan, the checker or this runner; commands are an allowlist (no shell);
nothing is ever pushed. Agent token spend is logged to agents/logs/spend.jsonl.
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "agents" / "logs"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe") if os.name == "nt" else str(ROOT / ".venv" / "bin" / "python")

sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):  # Windows consoles/redirects default to cp1252
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

WORKER_MODEL = os.getenv("AGENT_WORKER_MODEL", "gpt-5")
CRITIC_MODEL = os.getenv("AGENT_CRITIC_MODEL", "gpt-5")
# USD per 1M tokens: input, cached input, output
PRICES = {"gpt-5": (1.25, 0.125, 10.0), "gpt-5-mini": (0.25, 0.025, 2.0), "gpt-5.1": (1.25, 0.125, 10.0)}

NO_READ = {".env"}
NO_WRITE_DIRS = ("data/", "liquid-briefing-data/", "listeners/", ".git/", ".venv/", "resources/", "agents/", "tools/", "out/")
NO_WRITE_FILES = {".env", "AGENT_PLAN.md", "DONE.md", "PROJECT_DEFINITION_OF_DONE.md", ".gitignore", "requirements.txt"}
SKIP_LIST = (".git", ".venv", "__pycache__", "node_modules", "agents/logs")
MAX_OUT = 12000


class Stop(Exception):
    pass


# ---------------------------------------------------------------- spend

class Spend:
    def __init__(self, budget):
        self.budget = budget
        self.usd = 0.0
        LOGS.mkdir(parents=True, exist_ok=True)

    def add(self, model, usage, label):
        p_in, p_cached, p_out = PRICES.get(model, PRICES["gpt-5"])
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        fresh = usage.prompt_tokens - cached
        usd = fresh / 1e6 * p_in + cached / 1e6 * p_cached + usage.completion_tokens / 1e6 * p_out
        self.usd += usd
        with open(LOGS / "spend.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "label": label, "model": model,
                                "in": usage.prompt_tokens, "cached": cached, "out": usage.completion_tokens,
                                "usd": round(usd, 5)}) + "\n")

    def check(self):
        if self.usd >= self.budget:
            raise Stop(f"BUDGET: agent spend ${self.usd:.2f} reached the ${self.budget:.2f} limit")


# ---------------------------------------------------------------- tools

def rel(path):
    p = (ROOT / path).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError(f"{path} is outside the repository")
    return p, p.relative_to(ROOT).as_posix()


def t_read_file(path, start_line=1, end_line=None):
    p, r = rel(path)
    if r in NO_READ:
        return "Refused: .env holds secrets and is never readable."
    if not p.is_file():
        return f"No such file: {r}"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    end_line = end_line or len(lines)
    chunk = lines[start_line - 1:end_line]
    body = "\n".join(f"{i:5}\t{l}" for i, l in enumerate(chunk, start_line))
    if len(body) > MAX_OUT:
        body = body[:MAX_OUT] + f"\n... truncated; file has {len(lines)} lines, read a smaller range"
    return body or "(empty)"


def t_list_files(pattern="**/*"):
    out = []
    for p in ROOT.glob(pattern):
        r = p.relative_to(ROOT).as_posix()
        if any(r == s or r.startswith(s + "/") or f"/{s}/" in f"/{r}/" for s in SKIP_LIST):
            continue
        out.append(r + ("/" if p.is_dir() else ""))
        if len(out) >= 300:
            out.append("... (more)")
            break
    return "\n".join(sorted(out)) or "no matches"


def t_search(pattern, glob="**/*.py"):
    rx = re.compile(pattern)
    hits = []
    for p in ROOT.glob(glob):
        r = p.relative_to(ROOT).as_posix()
        if not p.is_file() or r in NO_READ or any(r.startswith(s) for s in SKIP_LIST) or r.startswith(("data/", "liquid-briefing-data/")):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if rx.search(line):
                hits.append(f"{r}:{i}: {line.strip()[:200]}")
                if len(hits) >= 150:
                    return "\n".join(hits) + "\n... (more)"
    return "\n".join(hits) or "no matches"


def writable(r):
    if r in NO_WRITE_FILES or r.startswith(NO_WRITE_DIRS) or r.endswith(".env"):
        raise ValueError(f"Refused: {r} is protected and may not be written by agents.")


def t_write_file(path, content):
    p, r = rel(path)
    writable(r)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {r} ({len(content.splitlines())} lines)"


def t_replace_in_file(path, old, new):
    p, r = rel(path)
    writable(r)
    if not p.is_file():
        return f"No such file: {r}"
    text = p.read_text(encoding="utf-8")
    n = text.count(old)
    if n != 1:
        return f"Refused: `old` matches {n} times in {r}; it must match exactly once. Read the file and include more context."
    p.write_text(text.replace(old, new), encoding="utf-8")
    return f"Replaced 1 block in {r}"


def make_run_command(ctx):
    def t_run_command(args):
        if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
            return "args must be a non-empty list of strings, e.g. [\"python\", \"-m\", \"unittest\"]"
        a = list(args)
        if a[0] == "python":
            a[0] = PY
            if any(".env" in x and ".env.example" not in x for x in a[1:]):
                return "Refused: commands may not touch .env."
            sub = a[1:]
            if sub[:1] == ["run.py"]:
                cheap = "--reuse" in sub and "--no-audio" in sub
                if ctx["role"] != "worker":
                    return "Refused: only the worker may start paid pipeline runs. Check the saved outputs instead."
                if not cheap and ctx["allow_paid"] != "full":
                    return "Refused: only `python run.py --reuse --no-audio` is allowed in this task (fresh extraction and audio need human approval)."
                if ctx["paid_runs"] >= ctx["max_paid_runs"]:
                    return f"Refused: this task already used its {ctx['max_paid_runs']} paid pipeline runs."
                ctx["paid_runs"] += 1
                timeout = 1800
            elif sub[:2] == ["-m", "unittest"] or sub[:1] == ["tools/check_done.py"] or sub[:1] == ["-c"] or (sub and sub[0].startswith("scripts/")):
                timeout = 600
            else:
                return "Refused: allowed python commands are `-m unittest ...`, `tools/check_done.py ...`, `-c <code>`, `scripts/*.py`, and `run.py --reuse --no-audio`."
        elif a[0] == "git" and len(a) > 1 and a[1] in {"diff", "status", "log", "show"}:
            timeout = 60
        else:
            return "Refused: allowed commands are python (see above) and read-only git (diff, status, log, show)."
        try:
            r = subprocess.run(a, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                               encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s"
        out = f"exit code {r.returncode}\n--- stdout\n{r.stdout}\n--- stderr\n{r.stderr}"
        if len(out) > MAX_OUT:
            out = out[:MAX_OUT // 2] + "\n... [truncated] ...\n" + out[-MAX_OUT // 2:]
        return out
    return t_run_command


def schema(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required, "additionalProperties": False}}}


S = {"type": "string"}
I = {"type": "integer"}
READ_TOOLS = [
    schema("read_file", "Read a text file in the repo, with line numbers. Use start_line/end_line for big files.",
           {"path": S, "start_line": I, "end_line": I}, ["path"]),
    schema("list_files", "List repo files matching a glob, e.g. 'briefing/*.py' or 'out/*'.", {"pattern": S}, ["pattern"]),
    schema("search", "Regex search over repo files (default glob **/*.py).", {"pattern": S, "glob": S}, ["pattern"]),
    schema("run_command", "Run an allowlisted command (no shell). args is a list, e.g. "
           "[\"python\",\"-m\",\"unittest\",\"discover\",\"-s\",\"tests\"] or [\"python\",\"tools/check_done.py\",\"--text-only\"] or [\"git\",\"diff\"].",
           {"args": {"type": "array", "items": S}}, ["args"]),
]
WRITE_TOOLS = [
    schema("write_file", "Create or overwrite a file with the full content.", {"path": S, "content": S}, ["path", "content"]),
    schema("replace_in_file", "Replace one exact, unique block of text in a file.", {"path": S, "old": S, "new": S}, ["path", "old", "new"]),
]
REPORT = schema("submit_report", "Finish your turn with your report.", {
    "status": {"type": "string", "enum": ["DONE", "BLOCKED"]},
    "summary": S, "files_changed": S, "commands_and_output": S, "open_items": S}, ["status", "summary", "files_changed", "commands_and_output", "open_items"])
VERDICT = schema("submit_verdict", "Finish your review with a verdict.", {
    "verdict": {"type": "string", "enum": ["PASS", "FAIL", "ESCALATE"]},
    "evidence": S, "fix_needed": S, "later": S}, ["verdict", "evidence", "fix_needed", "later"])


# ---------------------------------------------------------------- prompts

COMMON = """You work on the Liquid Briefing hackathon repo: a Python pipeline (briefing/ package, run.py, server.py,
web/index.html) that turns news articles into personalized, source-linked audio briefings.
Environment: Windows, Python 3.14 venv (use "python" in run_command; it maps to the venv). No shell, no pip installs,
no network except what the pipeline itself does. Standard library unittest only (no pytest).
The shared definition of done (DONE.md) and the full plan (AGENT_PLAN.md) are below. `python tools/check_done.py`
checks most DONE.md items for free (add --text-only before audio exists).
Deadline: Sat 21 Nov 10:30. Spend money carefully: unit tests first, paid pipeline runs only when the task needs them.

=== DONE.md ===
{done}

=== AGENT_PLAN.md ===
{plan}
"""

WORKER = """You are the WORKER. You own exactly one task (given below) and change code to complete it.
Rules:
- Read the relevant code before editing. Make the smallest change that completes the task; don't refactor or restyle other code.
- Never edit .env, data/, liquid-briefing-data/, listeners/, AGENT_PLAN.md, DONE.md, tools/, agents/ (the tools refuse anyway).
- Never weaken a check, test, threshold or prompt rule to make something pass. Never delete claims/facts just to pass a check.
- Run the task's acceptance check yourself and paste the real output in your report. "Should work" is not evidence.
- Paid pipeline run allowed only as `python run.py --reuse --no-audio`, and only when the acceptance check needs it.
- If the task needs a key, money, data or a human decision, or you're stuck after two attempts, submit status BLOCKED with the reason.
- Finish by calling submit_report exactly once."""

CRITIC = """You are the CRITIC. You do not edit code. You check the worker's work on one task against that task's
acceptance check in AGENT_PLAN.md and against DONE.md.
Rules:
- Run checks yourself (unit tests, tools/check_done.py, python -c snippets, git diff). Never trust the worker's pasted output alone.
- Read the diff (`git diff HEAD`) and the relevant files/outputs.
- PASS only if the acceptance check is met with evidence. FAIL must say exactly what is wrong and what would make it pass.
- Look for gaming: deleted claims/facts, loosened regexes/thresholds, tests rewritten to match wrong behavior, removed prompt rules.
- Prioritize by judging weight: trust/accuracy 25%, listener fit 20%, making sense of the news 20%, cost 15%, listening 10%, product 10%.
- Don't add new requirements: put ideas in `later`, they never block a PASS.
- Use ESCALATE only if the task can't be done without a human (key, money, data, decision).
- Finish by calling submit_verdict exactly once."""


def task_text(plan, task_id):
    m = re.search(rf"^\*\*{re.escape(task_id)}\.(.*?)(?=^\*\*P\d-\d+\.|^### |^## )", plan, re.S | re.M)
    if not m:
        raise SystemExit(f"Task {task_id} not found in AGENT_PLAN.md")
    return f"**{task_id}.{m.group(1).strip()}"


# ---------------------------------------------------------------- agent loop

def run_agent(role, model, system, user, tools, impl, finish, spend, label, max_steps=45):
    from openai import OpenAI
    client = OpenAI(timeout=300, max_retries=3)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    transcript = LOGS / f"{label}.json"
    for step in range(max_steps):
        spend.check()
        if step == max_steps - 5:
            messages.append({"role": "user", "content": f"You have 5 steps left. Wrap up and call {finish} now."})
        r = client.chat.completions.create(model=model, messages=messages, tools=tools,
                                           reasoning_effort="medium", parallel_tool_calls=False)
        spend.add(model, r.usage, label)
        msg = r.choices[0].message
        entry = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [{"id": c.id, "type": "function",
                                    "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                   for c in msg.tool_calls]
        messages.append(entry)
        if not msg.tool_calls:
            messages.append({"role": "user", "content": f"Use the tools to do the work, then call {finish}."})
            continue
        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = None
            if name == finish and isinstance(args, dict):
                transcript.write_text(json.dumps(messages, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
                return args
            try:
                result = impl[name](**args) if isinstance(args, dict) and name in impl else f"Unknown tool or bad arguments: {name}"
            except Exception as e:
                result = f"{type(e).__name__}: {e}"
            print(f"    [{role}] {name}({_short(args)}) -> {_short(result, 90)}", flush=True)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": str(result)})
        transcript.write_text(json.dumps(messages, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return {"status": "BLOCKED", "verdict": "ESCALATE", "summary": "ran out of steps", "evidence": "ran out of steps",
            "files_changed": "", "commands_and_output": "", "open_items": "", "fix_needed": "", "later": ""}


def _short(x, n=70):
    s = json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x
    s = s.replace("\n", " ")
    return s[:n] + ("…" if len(s) > n else "")


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def do_task(task_id, plan, done, spend, allow_paid, max_paid_runs):
    task = task_text(plan, task_id)
    base = COMMON.format(done=done, plan=plan)
    feedback = ""
    ctx = {"role": "worker", "allow_paid": allow_paid, "paid_runs": 0, "max_paid_runs": max_paid_runs}
    read_impl = {"read_file": t_read_file, "list_files": t_list_files, "search": t_search, "run_command": make_run_command(ctx)}
    write_impl = {"write_file": t_write_file, "replace_in_file": t_replace_in_file}
    for rnd in range(1, 4):
        print(f"\n=== {task_id} round {rnd}: worker ({WORKER_MODEL})", flush=True)
        ctx["role"] = "worker"
        user = f"YOUR TASK:\n{task}\n"
        if feedback:
            user += f"\nThe critic FAILED your previous attempt. Current diff vs last commit:\n{git('diff', '--stat', 'HEAD')}\nCritic feedback:\n{feedback}\nFix exactly this."
        report = run_agent("worker", WORKER_MODEL, base + "\n\n" + WORKER, user, READ_TOOLS + WRITE_TOOLS + [REPORT],
                           {**read_impl, **write_impl}, "submit_report", spend, f"{task_id}-r{rnd}-worker")
        print(f"  worker: {report.get('status')} - {_short(report.get('summary', ''), 200)}", flush=True)
        if report.get("status") == "BLOCKED":
            return "BLOCKED", report
        print(f"=== {task_id} round {rnd}: critic ({CRITIC_MODEL})", flush=True)
        ctx["role"] = "critic"
        cuser = (f"TASK UNDER REVIEW:\n{task}\n\nWORKER REPORT:\n{json.dumps(report, indent=1, ensure_ascii=False)}\n\n"
                 f"Changed files vs last commit:\n{git('status', '--short')}")
        verdict = run_agent("critic", CRITIC_MODEL, base + "\n\n" + CRITIC, cuser, READ_TOOLS + [VERDICT],
                            read_impl, "submit_verdict", spend, f"{task_id}-r{rnd}-critic", max_steps=35)
        print(f"  critic: {verdict.get('verdict')} - {_short(verdict.get('evidence', ''), 300)}", flush=True)
        if verdict.get("verdict") == "PASS":
            git("add", "-A", "--", ".", ":!.vscode")
            msg = f"{task_id}: {report.get('summary', '')[:70]}\n\nWorker/critic agents ({WORKER_MODEL}/{CRITIC_MODEL}), critic PASS.\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
            git("commit", "-q", "-m", msg)
            return "PASS", verdict
        if verdict.get("verdict") == "ESCALATE":
            return "ESCALATE", verdict
        feedback = f"{verdict.get('evidence', '')}\nFIX NEEDED: {verdict.get('fix_needed', '')}"
    return "ESCALATE", {"evidence": "3 failed rounds", "fix_needed": feedback}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True, help="comma-separated task ids, e.g. P0-1,P0-2")
    ap.add_argument("--budget", type=float, default=10.0, help="max USD of agent tokens for this run")
    ap.add_argument("--allow-paid", choices=["cheap", "full"], default="cheap",
                    help="cheap: only `run.py --reuse --no-audio`; full: fresh extraction and audio too")
    ap.add_argument("--max-paid-runs", type=int, default=2, help="paid pipeline runs allowed per task")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    plan = (ROOT / "AGENT_PLAN.md").read_text(encoding="utf-8")
    done = (ROOT / "DONE.md").read_text(encoding="utf-8")
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    if args.dry_run:
        for t in tasks:
            print(task_text(plan, t), "\n")
        return
    if git("status", "--porcelain", "--", ".", ":!.vscode").strip():
        raise SystemExit("Working tree has uncommitted changes. Commit or stash them first so each task starts clean.")

    spend = Spend(args.budget)
    results = []
    for t in tasks:
        try:
            status, info = do_task(t, plan, done, spend, args.allow_paid, args.max_paid_runs)
        except Stop as e:
            status, info = "BUDGET", {"evidence": str(e)}
        results.append((t, status, info))
        print(f"\n### {t}: {status}  (agent spend so far ${spend.usd:.2f})", flush=True)
        if status != "PASS":
            break
    (LOGS / "last_run.json").write_text(json.dumps([{"task": t, "status": s, "info": i} for t, s, i in results],
                                                   indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nSUMMARY")
    for t, s, i in results:
        print(f"  {t}: {s}" + ("" if s == "PASS" else f" - {_short(i.get('evidence') or i.get('summary', ''), 300)}"))
    print(f"  agent spend: ${spend.usd:.2f} of ${args.budget:.2f}")


if __name__ == "__main__":
    main()
