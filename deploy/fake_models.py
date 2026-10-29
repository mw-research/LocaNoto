"""A stand-in model server (OpenAI compatible) for installation tests.

    python fake_models.py [PORT] [DIMENSIONS]

Answers /v1/models, /v1/chat/completions (also streamed) and
/v1/embeddings with word-hash vectors -- enough for LocaNoto to install,
pass doctor.py and answer a question end to end, without a GPU. Only for
tests; it understands nothing.
"""
import hashlib
import json
import math
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
DIM = int(sys.argv[2]) if len(sys.argv) > 2 else 64
ANSWER = "Die Prüffrist beträgt vier Jahre."


def vector(text):
    v = [0.0] * DIM
    for w in re.findall(r"\w+", text.lower()):
        v[int.from_bytes(hashlib.sha256(w.encode()).digest()[:4], "big") % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._json({"object": "list", "data": [
                {"id": "fake-chat", "object": "model"}, {"id": "fake-embed", "object": "model"}]})
        if self.path == "/health":
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path.endswith("/embeddings"):
            texts = req.get("input")
            texts = [texts] if isinstance(texts, str) else texts
            return self._json({"object": "list", "model": req.get("model"), "data": [
                {"object": "embedding", "index": i, "embedding": vector(str(t))}
                for i, t in enumerate(texts)]})
        if self.path.endswith("/chat/completions"):
            base = {"id": "fake", "created": int(time.time()), "model": req.get("model")}
            if req.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for piece in (ANSWER[:10], ANSWER[10:]):
                    chunk = dict(base, object="chat.completion.chunk", choices=[
                        {"index": 0, "delta": {"content": piece}, "finish_reason": None}])
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                return
            return self._json(dict(base, object="chat.completion", choices=[
                {"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": ANSWER}}],
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}))
        self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
