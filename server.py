"""Local test page for the briefing pipeline. Standard library only.

  python server.py            -> http://localhost:8000

Uses out/stories.json from a previous `python run.py` (clustering + extraction), so generating
a briefing for a new or edited listener only runs rank -> script -> verify -> TTS.
"""
import json
import re
import threading
import traceback
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from briefing import make
from briefing.cost import COST

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
WEB = ROOT / "web"
LISTENERS = ROOT / "listeners"
JOBS = {}
SAFE = re.compile(r"[^a-z0-9_-]+")


def safe_name(s):
    return SAFE.sub("_", (s or "listener").lower()).strip("_")[:40] or "listener"


def load_stories():
    p = OUT / "stories.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def read_json(p, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def briefing(name):
    return {
        "name": name,
        "summary": read_json(OUT / f"{name}.summary.json", {}),
        "profile": read_json(OUT / f"{name}.profile.json", {}),
        "sources": read_json(OUT / f"{name}.sources.json", []),
        "verify": read_json(OUT / f"{name}.verify.json", []),
        "audio": f"/out/{name}.mp3" if (OUT / f"{name}.mp3").exists() else None,
    }


def run_job(job_id, profile, name, audio):
    try:
        JOBS[job_id]["summary"] = make.make_briefing(profile, name, load_stories(), OUT, audio=audio)
        JOBS[job_id]["status"] = "done"
    except Exception as e:
        traceback.print_exc()
        JOBS[job_id].update(status="error", error=f"{type(e).__name__}: {e}")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/listeners":
            return self._json([{"file": p.stem, "profile": read_json(p)} for p in sorted(LISTENERS.glob("*.json"))])
        if path == "/api/stories":
            return self._json([
                {k: s.get(k) for k in ("story_id", "headline", "topics", "importance", "n_sources", "published")}
                | {"articles": len(s.get("articles", [])), "facts": len(s.get("facts", [])),
                   "conflicts": len(s.get("conflicts", []))}
                for s in load_stories()
            ])
        if path == "/api/briefings":
            return self._json(sorted(p.name[: -len(".summary.json")] for p in OUT.glob("*.summary.json")))
        if path.startswith("/api/briefing/"):
            return self._json(briefing(safe_name(path.rsplit("/", 1)[1])))
        if path.startswith("/api/jobs/"):
            return self._json(JOBS.get(path.rsplit("/", 1)[1], {"status": "unknown"}))
        if path == "/api/cost":
            return self._json(read_json(OUT / "cost.json", {}) | {"session_usd": round(COST.total(), 4)})
        if path.startswith("/out/"):
            f = OUT / Path(path[5:]).name  # flat folder, no traversal
            if f.suffix == ".mp3" and f.exists():
                data = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            return self.send_error(404)
        return super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/generate":
            profile = body.get("profile") or {}
            name = safe_name(body.get("name") or profile.get("name"))
            if not load_stories():
                return self._json({"error": "No out/stories.json yet: run `python run.py` first."}, 400)
            if body.get("save"):
                (LISTENERS / f"{name}.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
            job_id = uuid.uuid4().hex[:8]
            JOBS[job_id] = {"status": "running", "name": name}
            threading.Thread(target=run_job, args=(job_id, profile, name, bool(body.get("audio"))), daemon=True).start()
            return self._json({"job": job_id, "name": name})
        self.send_error(404)

    def log_message(self, fmt, *args):
        if "/api/jobs/" not in self.path:  # polling is noisy
            super().log_message(fmt, *args)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    print("Test page on http://localhost:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
