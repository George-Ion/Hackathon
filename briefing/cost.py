"""Tracks every paid call so we can report full-dataset cost and the 10x estimate (15% of the score).
Also provides a cumulative spend ledger to enforce the API budget across processes.
"""
import contextvars
import json
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .config import PRICES, TTS_PER_1K_CHARS, API_BUDGET_USD


# Append-only JSON Lines ledger under out/
LEDGER_PATH = Path("out") / "spend.log"
_LEDGER_LOCK = threading.Lock()


# Which listener's briefing the current call belongs to (None for shared steps like extraction).
# Set by make.py; copied into worker threads by verify.py.
LISTENER = contextvars.ContextVar("listener", default=None)


class BudgetExceeded(RuntimeError):
    pass


class CostTracker:
    def __init__(self):
        self.by_step = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
        self._lock = threading.Lock()
        self._session_usd = 0.0
        self.by_listener = defaultdict(lambda: {"text": 0.0, "voice": 0.0})

    def _add_usd_session(self, usd):
        # Called with external locks already held where needed
        self._session_usd += float(usd or 0.0)

    def session_usd(self):
        return round(self._session_usd, 6)

    def add_tokens(self, step, model, tokens_in, tokens_out=0):
        p_in, p_out = PRICES.get(model, (0.0, 0.0))
        usd = tokens_in / 1e6 * p_in + tokens_out / 1e6 * p_out
        with self._lock:
            s = self.by_step[f"{step} ({model})"]
            s["calls"] += 1
            s["in"] += int(tokens_in)
            s["out"] += int(tokens_out)
            s["usd"] += usd
            self._add_usd_session(usd)
            if LISTENER.get():
                self.by_listener[LISTENER.get()]["text"] += usd
        # Ledger write outside of lock to minimize contention; the write itself is protected
        log_spend(step, model, usd)

    def add_tts(self, chars):
        usd = chars / 1000 * TTS_PER_1K_CHARS
        with self._lock:
            s = self.by_step["tts (elevenlabs)"]
            s["calls"] += 1
            s["in"] += int(chars)
            s["usd"] += usd
            self._add_usd_session(usd)
            if LISTENER.get():
                self.by_listener[LISTENER.get()]["voice"] += usd
        log_spend("tts", "elevenlabs", usd)

    def listener_usd(self, name):
        """Exact spend so far in this process for one listener: {'text': usd, 'voice': usd}."""
        with self._lock:
            return dict(self.by_listener[name])

    def total(self):
        with self._lock:
            return sum(s["usd"] for s in self.by_step.values())

    def restore(self, report):
        """Restore previously measured calls when a run reuses extracted stories.
        This resets the step table but leaves the session counter at 0 for this process.
        """
        steps = report.get("measured", {}).get("steps", report.get("steps", {}))
        with self._lock:
            self.by_step = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
            for name, values in steps.items():
                self.by_step[name] = {
                    "calls": int(values.get("calls", 0)),
                    "in": int(values.get("in", 0)),
                    "out": int(values.get("out", 0)),
                    "usd": float(values.get("usd", 0.0)),
                }
            # Do not change self._session_usd here; it should only reflect this process
        if report.get("extract_cap_ratio"):
            self.extract_cap_ratio = report["extract_cap_ratio"]

    def projections(self, measured_articles, listener_runs, full_dataset_articles):
        """Project measured article stages linearly; hold measured listener stages fixed."""
        if not measured_articles or not full_dataset_articles:
            return {
                "method": "Article-level stages scale linearly by merged article count; listener-level stages stay fixed.",
                "status": "unavailable",
                "reason": "A non-zero measured article count and full dataset count are required.",
                "full_dataset": None,
                "ten_x_volume": None,
            }

        scale = full_dataset_articles / measured_articles
        full_steps, ten_steps = {}, {}
        with self._lock:
            items = list(self.by_step.items())
        cap = getattr(self, "extract_cap_ratio", None)
        for name, values in items:
            if name.startswith("extract (") and cap:
                # Pre-ranked: extraction covers a shortlist capped by listener count, whatever the volume
                full, ten = cap, cap
            elif name.startswith("cluster_confirm ("):
                # Borderline-pair checks are capped at CONFIRM_MAX_PAIRS per run (10 batches)
                full = min(scale, 10 / max(1, values.get("calls", 1)))
                ten = min(scale * 10, 10 / max(1, values.get("calls", 1)))
            elif name.startswith("embed (") or name.startswith("extract ("):
                full, ten = scale, scale * 10
            else:
                full, ten = 1.0, 1.0
            full_steps[name] = round(values["usd"] * full, 6)
            ten_steps[name] = round(values["usd"] * ten, 6)
        return {
            "method": ("Embeddings scale with article count. With pre-ranking, extraction covers a shortlist capped by "
                       "the number of listeners (top 12 per listener + top 15 overall), so it does not grow with volume; "
                       "borderline grouping checks are capped at 200 pairs. Script, verification and voice stay fixed "
                       "for the measured listener count." if getattr(self, "extract_cap_ratio", None) else
                       "Embedding and extraction costs scale with merged article count. Script, verification, and TTS "
                       "costs stay fixed for the measured listener count."),
            "status": "estimated",
            "full_dataset": {
                "articles": full_dataset_articles,
                "listeners": listener_runs,
                "scale_from_measured": round(scale, 6),
                "steps_usd": full_steps,
                "estimated_usd": round(sum(full_steps.values()), 6),
            },
            "ten_x_volume": {
                "articles": full_dataset_articles * 10,
                "listeners": listener_runs,
                "scale_from_full_dataset": 10,
                "steps_usd": ten_steps,
                "estimated_usd": round(sum(ten_steps.values()), 6),
            },
        }

    def report(self, n_articles, n_listeners, full_dataset_articles=None):
        with self._lock:
            snapshot = {k: dict(v) for k, v in self.by_step.items()}
        total = sum(s["usd"] for s in snapshot.values())
        lines = [f"{'step':45} {'calls':>6} {'tok_in':>10} {'tok_out':>9} {'usd':>9}"]
        for k, s in sorted(snapshot.items()):
            lines.append(f"{k:45} {s['calls']:>6} {s['in']:>10} {s['out']:>9} {s['usd']:>9.4f}")
        lines.append(f"TOTAL for {n_articles} articles, {n_listeners} listeners: ${total:.4f}")
        if full_dataset_articles is not None:
            projection = self.projections(n_articles, n_listeners, full_dataset_articles)
            if projection["status"] == "estimated":
                lines.append(f"Estimated full dataset ({full_dataset_articles} articles): ${projection['full_dataset']['estimated_usd']:.4f}")
                lines.append(f"Estimated 10x volume ({full_dataset_articles * 10} articles): ${projection['ten_x_volume']['estimated_usd']:.4f}")
            else:
                lines.append(f"Dataset projections unavailable: {projection['reason']}")
        return "\n".join(lines)

    def to_json(self, path, measured_articles=None, listener_runs=None, full_dataset_articles=None):
        with self._lock:
            steps = {name: dict(values) for name, values in self.by_step.items()}
        measured_articles = measured_articles or 0
        listener_runs = listener_runs or 0
        projection = self.projections(measured_articles, listener_runs, full_dataset_articles or 0)
        # Keep legacy top-level fields for the preview API while retaining measured
        # actuals and clearly labeled projections for the hackathon cost deliverable.
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "steps": steps,
                "total_usd": round(sum(s["usd"] for s in steps.values()), 6),
                "measured": {
                    "articles": measured_articles,
                    "listeners": listener_runs,
                    "steps": steps,
                    "total_usd": round(sum(s["usd"] for s in steps.values()), 6),
                },
                "projections": projection,
                "extract_cap_ratio": getattr(self, "extract_cap_ratio", None),
            }, f, indent=2)


def log_spend(step: str, model: str, usd: float):
    """Append one JSON line to the cumulative spend ledger in a thread-safe way."""
    LEDGER_PATH.parent.mkdir(exist_ok=True, parents=True)
    line = {
        "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "step": step,
        "model": model,
        "usd": round(float(usd or 0.0), 6),
    }
    data = (json.dumps(line) + "\n").encode("utf-8")
    with _LEDGER_LOCK:
        with open(LEDGER_PATH, "ab") as f:
            f.write(data)


def spent_to_date() -> float:
    """Sum the USD amounts in the append-only ledger. Missing file -> 0.0"""
    try:
        total = 0.0
        with _LEDGER_LOCK:
            if not LEDGER_PATH.exists():
                return 0.0
            with open(LEDGER_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        total += float(json.loads(line).get("usd", 0.0))
                    except Exception:
                        # Skip malformed lines to keep the ledger robust
                        continue
        return round(total, 6)
    except Exception:
        # Never crash callers on ledger read errors; treat as 0 so separate budget
        # checks can still run and will re-append.
        return 0.0


def ensure_budget(estimate_usd: float, step: str, model: str):
    """Raise BudgetExceeded if the next call would push us past the configured budget."""
    est = float(estimate_usd or 0.0)
    current = spent_to_date()
    if API_BUDGET_USD and current + est > API_BUDGET_USD:
        raise BudgetExceeded(
            f"Budget exceeded: ${current:.2f} already spent; next {step} ({model}) call estimated ${est:.2f} would exceed ${API_BUDGET_USD:.2f}."
        )


COST = CostTracker()
