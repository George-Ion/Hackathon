"""Tracks every paid call so we can report full-dataset cost and the 10x estimate (15% of the score)."""
import json
from collections import defaultdict

from .config import PRICES, TTS_PER_1K_CHARS


class CostTracker:
    def __init__(self):
        self.by_step = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "usd": 0.0})

    def add_tokens(self, step, model, tokens_in, tokens_out=0):
        p_in, p_out = PRICES.get(model, (0.0, 0.0))
        s = self.by_step[f"{step} ({model})"]
        s["calls"] += 1
        s["in"] += tokens_in
        s["out"] += tokens_out
        s["usd"] += tokens_in / 1e6 * p_in + tokens_out / 1e6 * p_out

    def add_tts(self, chars):
        s = self.by_step["tts (elevenlabs)"]
        s["calls"] += 1
        s["in"] += chars
        s["usd"] += chars / 1000 * TTS_PER_1K_CHARS

    def total(self):
        return sum(s["usd"] for s in self.by_step.values())

    def restore(self, report):
        """Restore previously measured calls when a run reuses extracted stories."""
        steps = report.get("measured", {}).get("steps", report.get("steps", {}))
        self.by_step = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
        for name, values in steps.items():
            self.by_step[name] = {
                "calls": int(values.get("calls", 0)),
                "in": int(values.get("in", 0)),
                "out": int(values.get("out", 0)),
                "usd": float(values.get("usd", 0.0)),
            }

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
        for name, values in self.by_step.items():
            article_stage = name.startswith("embed (") or name.startswith("extract (")
            factor = scale if article_stage else 1.0
            full_steps[name] = round(values["usd"] * factor, 6)
            ten_steps[name] = round(values["usd"] * factor * (10 if article_stage else 1), 6)
        return {
            "method": "Embedding and extraction costs scale with merged article count. Script, verification, and TTS costs stay fixed for the measured listener count.",
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
        total = self.total()
        lines = [f"{'step':45} {'calls':>6} {'tok_in':>10} {'tok_out':>9} {'usd':>9}"]
        for k, s in sorted(self.by_step.items()):
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
        steps = {name: dict(values) for name, values in self.by_step.items()}
        measured_articles = measured_articles or 0
        listener_runs = listener_runs or 0
        projection = self.projections(measured_articles, listener_runs, full_dataset_articles or 0)
        # Keep legacy top-level fields for the preview API while retaining measured
        # actuals and clearly labeled projections for the hackathon cost deliverable.
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "steps": steps,
                "total_usd": round(self.total(), 6),
                "measured": {
                    "articles": measured_articles,
                    "listeners": listener_runs,
                    "steps": steps,
                    "total_usd": round(self.total(), 6),
                },
                "projections": projection,
            }, f, indent=2)


COST = CostTracker()
