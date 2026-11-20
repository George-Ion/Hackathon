"""Local test page for the briefing pipeline. Standard library only.

  python server.py            -> http://localhost:8000

Uses out/stories.json from a previous `python run.py` (clustering + extraction), so generating
a briefing for a new or edited listener only runs rank -> script -> verify -> TTS.
"""
import json
import os
import importlib.util
import re
import threading
import traceback
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from briefing import ingest, make
from briefing.cost import COST

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
WEB = ROOT / "web"
LISTENERS = ROOT / "listeners"
JOBS = {}
RUN_LOCK = threading.Lock()
SAFE = re.compile(r"[^a-z0-9_-]+")


def safe_name(s):
    return SAFE.sub("_", (s or "listener").lower()).strip("_")[:40] or "listener"


def load_stories():
    p = OUT / "stories.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def read_json(p, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


if (OUT / "cost.json").exists():
    COST.restore(read_json(OUT / "cost.json", {}))


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
    with RUN_LOCK:
        try:
            JOBS[job_id]["summary"] = make.make_briefing(profile, name, load_stories(), OUT, audio=audio)
            JOBS[job_id]["status"] = "done"
        except Exception as e:
            traceback.print_exc()
            message = str(e)
            if "text_to_speech" in message or "missing_permissions" in message:
                message = "ElevenLabs key is missing Text to Speech permission. Update the key, then restart the server."
            JOBS[job_id].update(status="error", error=f"{type(e).__name__}: {message}")
        finally:
            try:
                prior = read_json(OUT / "cost.json", {})
                measured = prior.get("measured", {})
                n_articles = measured.get("articles") or sum(
                    len(s.get("articles", [])) + len(s.get("duplicate_ids", [])) for s in load_stories()
                )
                listener_runs = measured.get("listeners") or len(list(LISTENERS.glob("*.json")))
                full_count = len(ingest.load_articles("data/raw")[0])
                COST.to_json(OUT / "cost.json", n_articles, listener_runs, full_count)
            except Exception:
                traceback.print_exc()


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
        if path == "/api/status":
            stories = load_stories()
            openai_ready = importlib.util.find_spec("openai") is not None
            tts_client_ready = importlib.util.find_spec("requests") is not None
            openai_key = bool(os.environ.get("OPENAI_API_KEY"))
            elevenlabs_key = bool(os.environ.get("ELEVENLABS_API_KEY"))
            return self._json({
                "stories_loaded": bool(stories), "story_count": len(stories),
                "openai_sdk": openai_ready, "tts_client": tts_client_ready,
                "openai_key": openai_key, "elevenlabs_key": elevenlabs_key,
                "text_ready": bool(stories) and openai_ready and openai_key,
                "audio_configured": bool(stories) and tts_client_ready and elevenlabs_key,
            })
        if path == "/api/stories":
            return self._json([
                {k: s.get(k) for k in ("story_id", "headline", "topics", "importance", "n_sources", "published")}
                | {"articles": len(s.get("articles", [])), "facts": len(s.get("facts", [])),
                   "conflicts": len(s.get("conflicts", []))}
                for s in load_stories()
            ])
        if path.startswith("/api/story/"):
            story_id = path.rsplit("/", 1)[1]
            story = next((s for s in load_stories() if s.get("story_id") == story_id), None)
            if not story:
                return self._json({"error": "Story not found."}, 404)
            # Keep licensed article bodies out of the UI/API; show only citation metadata.
            return self._json({k: story.get(k) for k in ("story_id", "headline", "summary", "topics", "importance", "n_sources", "published", "facts", "conflicts")} | {
                "articles": [{k: a.get(k) for k in ("id", "outlet", "title", "url", "published", "language", "translations")} for a in story.get("articles", [])]
            })
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
            existing_profile = read_json(OUT / f"{name}.profile.json")
            saved_profile = read_json(LISTENERS / f"{name}.json")
            if existing_profile is not None and existing_profile != profile and saved_profile != profile:
                return self._json({"error": "This listener name is already used by a different profile; choose a distinct name."}, 409)
            if body.get("save"):
                destination = LISTENERS / f"{name}.json"
                if destination.exists():
                    return self._json({"error": "That listener name already exists; choose a new name."}, 409)
                destination.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
            job_id = uuid.uuid4().hex[:8]
            JOBS[job_id] = {"status": "running", "name": name}
            threading.Thread(target=run_job, args=(job_id, profile, name, bool(body.get("audio"))), daemon=True).start()
            return self._json({"job": job_id, "name": name})
        if self.path == "/api/listeners/save":
            profile = body.get("profile") or {}
            if not isinstance(profile, dict) or not profile.get("name"):
                return self._json({"error": "A listener name is required."}, 400)
            name = safe_name(body.get("file") or profile.get("name"))
            destination = LISTENERS / f"{name}.json"
            destination.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
            return self._json({"file": name, "profile": profile})
        self.send_error(404)

    def log_message(self, fmt, *args):
        if "/api/jobs/" not in self.path:  # polling is noisy
            super().log_message(fmt, *args)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    port = int(os.environ.get("PORT", "8000"))
    print(f"Test page on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
