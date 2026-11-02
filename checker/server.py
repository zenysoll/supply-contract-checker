"""Локальный HTTP-сервер на стандартной библиотеке. Состояние - в памяти процесса."""
import base64
import json
import os
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List
from urllib.parse import parse_qs, urlparse

from .engine import (DEFAULT_AS_OF, KIND_LABEL, STATUS_LABEL, analyze, answer_question, early_delivery)
from .extract import Doc, parse_document
from .textutil import decode_bytes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SAMPLES = os.path.join(ROOT, "sample_documents")
MAX_BODY = 20 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024


class Store:
    """Загруженные документы. Повторная загрузка файла с тем же именем заменяет прежний."""

    def __init__(self):
        self._docs: Dict[str, Doc] = {}
        self._lock = threading.Lock()

    def add(self, name: str, data: bytes) -> Doc:
        if len(data) > MAX_FILE:
            raise ValueError(f"{name}: файл больше {MAX_FILE // 1024 // 1024} МБ")
        doc = parse_document(os.path.basename(name), decode_bytes(data))
        with self._lock:
            self._docs.pop(doc.id, None)
            self._docs[doc.id] = doc
        return doc

    def add_dir(self, path: str) -> List[Doc]:
        out = []
        for fn in sorted(os.listdir(path)):
            if fn.lower().endswith(".txt"):
                with open(os.path.join(path, fn), "rb") as f:
                    out.append(self.add(fn, f.read()))
        return out

    def all(self) -> List[Doc]:
        with self._lock:
            return list(self._docs.values())

    def get(self, doc_id: str):
        with self._lock:
            return self._docs.get(doc_id)

    def remove(self, doc_id: str):
        with self._lock:
            self._docs.pop(doc_id, None)

    def clear(self):
        with self._lock:
            self._docs.clear()


def _parse_iso(s, default: date) -> date:
    try:
        return date.fromisoformat(s) if s else default
    except ValueError:
        return default


def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ContractChecker/1.0"

        def log_message(self, fmt, *args):  # тише в консоли
            pass

        def _json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("слишком большой запрос")
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/index.html"):
                    with open(os.path.join(STATIC, "index.html"), "rb") as f:
                        body = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif u.path == "/api/state":
                    as_of = _parse_iso(q.get("as_of"), DEFAULT_AS_OF)
                    self._json(analyze(store.all(), as_of))
                elif u.path == "/api/doc":
                    d = store.get(q.get("id", ""))
                    if not d:
                        return self._json({"error": "документ не найден"}, 404)
                    self._json({"id": d.id, "name": d.name, "text": d.text,
                                "kind_label": KIND_LABEL[d.kind], "status_label": STATUS_LABEL.get(d.status, d.status),
                                "paragraphs": [{"idx": p.idx, "start": p.start, "end": p.end, "clause": p.clause}
                                               for p in d.paras]})
                elif u.path == "/api/ask":
                    as_of = _parse_iso(q.get("as_of"), DEFAULT_AS_OF)
                    self._json(answer_question(store.all(), q.get("q", ""), as_of))
                elif u.path == "/api/early":
                    as_of = _parse_iso(q.get("as_of"), DEFAULT_AS_OF)
                    before = _parse_iso(q.get("before"), date(2026, 4, 1))
                    self._json(early_delivery(analyze(store.all(), as_of), before))
                else:
                    self._json({"error": "не найдено"}, 404)
            except Exception as e:  # noqa: BLE001 - отдаём понятную ошибку, а не рвём соединение
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def do_POST(self):
            u = urlparse(self.path)
            try:
                if u.path == "/api/upload":
                    payload = self._body()
                    added, errors = [], []
                    for f in payload.get("files", []):
                        try:
                            d = store.add(f["name"], base64.b64decode(f["b64"]))
                            added.append({"id": d.id, "name": d.name, "kind": d.kind})
                        except Exception as e:  # noqa: BLE001
                            errors.append(str(e))
                    self._json({"added": added, "errors": errors})
                elif u.path == "/api/samples":
                    docs = store.add_dir(SAMPLES) if os.path.isdir(SAMPLES) else []
                    self._json({"added": [{"id": d.id, "name": d.name, "kind": d.kind} for d in docs], "errors": []})
                elif u.path == "/api/remove":
                    store.remove(self._body().get("id", ""))
                    self._json({"ok": True})
                elif u.path == "/api/clear":
                    store.clear()
                    self._json({"ok": True})
                else:
                    self._json({"error": "не найдено"}, 404)
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    return Handler


def create_server(host="127.0.0.1", port=8000, store=None):
    store = store or Store()
    srv = ThreadingHTTPServer((host, port), make_handler(store))
    srv.store = store
    return srv
