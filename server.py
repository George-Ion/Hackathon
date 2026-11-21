"""Local test page for the briefing pipeline. Standard library only.

  python server.py            -> http://localhost:8000

Uses out/stories.json from a previous `python run.py` (clustering + extraction), so generating
a briefing for a new or edited listener only runs rank -> script -> verify -> TTS.
"""
import json
import os
import importlib.util
import re
import tempfile
import threading
import traceback
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from briefing import config, ingest, make, must_hear, ondemand, tts, voice_request
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


def run_job(job_id, profile, name, audio, voice_only=False):
    with RUN_LOCK:
        try:
            if voice_only:
                # ElevenLabs only: voice the saved, verified script; no OpenAI calls
                JOBS[job_id]["summary"] = make.synthesize_saved_briefing(profile, name, load_stories(), OUT)
            else:
                # A new or edited listener may need stories the batch run never extracted
                stories = ondemand.ensure_stories(profile, load_stories(), OUT,
                                                  progress=lambda m: JOBS[job_id].update(stage=m))
                JOBS[job_id]["stage"] = "writing the script"
                JOBS[job_id]["summary"] = make.make_briefing(profile, name, stories, OUT, audio=audio)
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
                full_count = len(ingest.load_articles("data/raw")[0])  # still ok: we only need the first element
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
                   "conflicts": len(s.get("conflicts", [])),
                   "duplicates": len(s.get("duplicate_ids", [])),
                   "translations": sum(len(a.get("translations", [])) for a in s.get("articles", [])),
                   "outlets": sorted({a.get("outlet") for a in s.get("articles", []) if a.get("outlet")})}
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
        if path == "/api/voices":
            return self._json(config.VOICES)
        if path.startswith("/api/voice-preview/"):
            return self._voice_preview(path.rsplit("/", 1)[1])
        if path == "/api/prerank":
            pr = read_json(OUT / "prerank.json", {}) or {}
            return self._json({k: pr.get(k) for k in ("groups", "shortlisted", "k_per_listener", "k_global", "listeners")})
        if path == "/api/briefings":
            return self._json(sorted(p.name[: -len(".summary.json")] for p in OUT.glob("*.summary.json")))
        if path.startswith("/api/briefing/"):
            return self._json(briefing(safe_name(path.rsplit("/", 1)[1])))
        if path.startswith("/api/jobs/"):
            return self._json(JOBS.get(path.rsplit("/", 1)[1], {"status": "unknown"}))
        if path == "/api/cost":
            # Expose session spend separate from restored totals
            return self._json(read_json(OUT / "cost.json", {}) | {"session_usd": round(COST.session_usd(), 4)})
        if path.startswith("/out/"):
            f = OUT / Path(path[5:]).name  # flat folder, no traversal
            if f.suffix == ".mp3" and f.exists():
                file_size = f.stat().st_size
                range_header = self.headers.get("Range")
                # Always advertise byte ranges
                if range_header:
                    # Support single-range requests: bytes=start-end, start- or -suffix
                    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
                    if m:
                        start_s, end_s = m.groups()
                        try:
                            if start_s == "" and end_s:
                                # suffix length: last N bytes
                                length = int(end_s)
                                if length <= 0:
                                    raise ValueError
                                start = max(0, file_size - length)
                                end = file_size - 1
                            else:
                                start = int(start_s or 0)
                                end = int(end_s) if end_s else file_size - 1
                                if start < 0 or end < start:
                                    raise ValueError
                                if start >= file_size:
                                    # Not satisfiable
                                    self.send_response(416)
                                    self.send_header("Content-Range", f"bytes */{file_size}")
                                    self.send_header("Accept-Ranges", "bytes")
                                    self.end_headers()
                                    return
                                end = min(end, file_size - 1)
                            length = end - start + 1
                        except Exception:
                            # Malformed; fall back to full content
                            start, end = 0, file_size - 1
                            length = file_size
                            m = None
                        if m:
                            with open(f, "rb") as fh:
                                fh.seek(start)
                                chunk = fh.read(length)
                            self.send_response(206)
                            self.send_header("Content-Type", "audio/mpeg")
                            self.send_header("Accept-Ranges", "bytes")
                            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                            self.send_header("Content-Length", str(len(chunk)))
                            self.end_headers()
                            return self.wfile.write(chunk)
                # No (valid) Range header: send full file
                with open(f, "rb") as fh:
                    data = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            return self.send_error(404)
        return super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if self.path == "/api/voice-request":
            return self._voice_request(length)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/must-hear":
            pr = (read_json(OUT / "prerank.json", {}) or {}).get("stories", [])
            return self._json(must_hear.check(load_stories(), pr, must_hear.clean(body.get("phrases"))))
        if self.path == "/api/voice":
            name = safe_name(body.get("name"))
            profile = read_json(OUT / f"{name}.profile.json")
            if not profile or not (OUT / f"{name}.script.json").exists():
                return self._json({"error": "No saved script for this listener yet: generate the text edition first."}, 400)
            job_id = uuid.uuid4().hex[:8]
            JOBS[job_id] = {"status": "running", "name": name}
            threading.Thread(target=run_job, args=(job_id, profile, name, True, True), daemon=True).start()
            return self._json({"job": job_id, "name": name})
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

    def _voice_preview(self, voice_id):
        """A short sample of a voice, made once per voice and cached in out/ (about $0.01 each)."""
        voice = next((v for v in config.VOICES if v["id"] == voice_id), None)
        if not voice:
            return self._json({"error": "Unknown voice."}, 404)
        name = f"preview_{voice_id}.mp3"
        if not (OUT / name).exists():
            text = f"Good morning. I'm {voice['name']}, and this is your news briefing for today."
            try:
                tts.synthesize_briefing([{"story_id": None, "text": text}], OUT / name,
                                        OUT / f"preview_{voice_id}.timeline.json", "en", voice_id=voice_id)
            except Exception as e:
                traceback.print_exc()
                return self._json({"error": f"Could not make a preview: {type(e).__name__}: {e}"}, 502)
        return self._json({"url": f"/out/{name}"})

    def _voice_request(self, length):
        """A recorded 'what I want to hear today' memo -> transcript + listener profile (no briefing yet).
        The audio is written to a temp file only for transcription and deleted right after."""
        if not 0 < length <= 8_000_000:
            return self._json({"error": "Recording missing or too large (keep it under a minute)."}, 400)
        data = self.rfile.read(length)
        seconds = min(float(self.headers.get("X-Duration") or 30), 120)
        suffix = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/mpeg": ".mp3",
                  "audio/wav": ".wav"}.get((self.headers.get("Content-Type") or "").split(";")[0], ".webm")
        tmp = Path(tempfile.gettempdir()) / f"lb_request_{uuid.uuid4().hex}{suffix}"
        usd_before = COST.session_usd()
        try:
            tmp.write_bytes(data)
            transcript = voice_request.transcribe(tmp, seconds)
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": f"Could not transcribe the recording: {type(e).__name__}: {e}"}, 502)
        finally:
            tmp.unlink(missing_ok=True)
        try:
            profile, understood = voice_request.profile_from_request(transcript, load_stories())
        except ValueError as e:
            return self._json({"error": str(e), "transcript": transcript}, 422)
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": f"Could not understand the request: {type(e).__name__}: {e}", "transcript": transcript}, 502)
        pr = (read_json(OUT / "prerank.json", {}) or {}).get("stories", [])
        return self._json({"transcript": transcript, "profile": profile, "understood": understood,
                           "must_hear": must_hear.check(load_stories(), pr, profile.get("must_hear")),
                           "usd": round(COST.session_usd() - usd_before, 4)})

    def log_message(self, fmt, *args):
        if "/api/jobs/" not in self.path:  # polling is noisy
            super().log_message(fmt, *args)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    port = int(os.environ.get("PORT", "8000"))
    print(f"Test page on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
