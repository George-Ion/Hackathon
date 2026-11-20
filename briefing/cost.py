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

    def report(self, n_articles, n_listeners):
        total = self.total()
        lines = [f"{'step':45} {'calls':>6} {'tok_in':>10} {'tok_out':>9} {'usd':>9}"]
        for k, s in sorted(self.by_step.items()):
            lines.append(f"{k:45} {s['calls']:>6} {s['in']:>10} {s['out']:>9} {s['usd']:>9.4f}")
        lines.append(f"TOTAL for {n_articles} articles, {n_listeners} listeners: ${total:.4f}")
        # Per-article steps scale linearly with volume; per-listener steps scale with listeners.
        lines.append(f"Naive 10x volume estimate: ${total * 10:.4f} (see README for the per-step reasoning)")
        return "\n".join(lines)

    def to_json(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"steps": self.by_step, "total_usd": self.total()}, f, indent=2)


COST = CostTracker()
