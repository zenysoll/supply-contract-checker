"""Сквозная проверка через HTTP: загрузка файлов, таблица, вопросы, просмотр абзаца."""
import base64
import json
import threading
import unittest
import urllib.request
from urllib.parse import quote

from tests.helpers import sample_texts
from checker.server import create_server


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = create_server("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return json.loads(r.read())

    def post(self, path, obj=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(obj or {}).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def upload(self, texts):
        files = [{"name": n, "b64": base64.b64encode(t.encode("utf-8")).decode()} for n, t in texts.items()]
        return self.post("/api/upload", {"files": files})

    def setUp(self):
        self.post("/api/clear")

    def test_empty_state(self):
        st = self.get("/api/state")
        self.assertEqual((st["contracts"], st["documents"]), ([], []))

    def test_upload_then_table(self):
        r = self.upload(sample_texts())
        self.assertEqual(len(r["added"]), 6)
        st = self.get("/api/state?as_of=2026-03-10")
        self.assertEqual([c["number"] for c in st["contracts"]], ["STN-101", "STN-102", "STN-103"])
        vals = {c["number"]: (c["amount"]["display"], c["delivery"]["display"]) for c in st["contracts"]}
        self.assertEqual(vals["STN-101"], ("1 380 000 ₽", "30.04.2026"))
        self.assertEqual(vals["STN-102"], ("840 000 ₽", "20.03.2026"))
        self.assertEqual(vals["STN-103"], ("нет данных", "30.04.2026"))

    def test_incremental_upload_and_replace(self):
        t = sample_texts()
        self.upload({"01_contract.txt": t["01_contract.txt"]})
        self.assertEqual(self.get("/api/state")["contracts"][0]["delivery"]["display"], "15.04.2026")
        self.upload({"02_amendment_signed.txt": t["02_amendment_signed.txt"]})
        self.assertEqual(self.get("/api/state")["contracts"][0]["delivery"]["display"], "30.04.2026")
        # тот же файл с другим содержимым заменяет прежний
        self.upload({"01_contract.txt": t["01_contract.txt"].replace("15.04.2026", "16.04.2026")})
        st = self.get("/api/state")
        self.assertEqual(len(st["contracts"]), 1)
        self.assertEqual(st["contracts"][0]["delivery"]["base"]["display"], "16.04.2026")

    def test_check_date_param(self):
        self.upload(sample_texts())
        st = self.get("/api/state?as_of=2026-02-20")
        self.assertEqual(st["contracts"][0]["delivery"]["display"], "15.04.2026")

    def test_ask_and_early(self):
        self.upload(sample_texts())
        a = self.get("/api/ask?q=" + quote("Какова сумма договора STN-103?"))
        self.assertIn("нет данных", a["answer"])
        e = self.get("/api/early?before=2026-04-01&as_of=2026-03-10")
        self.assertEqual([m["number"] for m in e["matches"]], ["STN-102"])

    def test_doc_view_gives_paragraphs_matching_source_offsets(self):
        self.upload(sample_texts())
        st = self.get("/api/state")
        src = st["contracts"][0]["delivery"]["source"]
        d = self.get("/api/doc?id=" + src["doc_id"])
        p = d["paragraphs"][src["para"] - 1]
        self.assertEqual(d["text"][src["start"]:src["end"]], src["quote"])
        self.assertTrue(p["start"] <= src["start"] and src["end"] <= p["end"])

    def test_samples_endpoint_and_errors(self):
        r = self.post("/api/samples")
        self.assertEqual(len(r["added"]), 6)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/api/doc?id=nope")
        self.assertEqual(cm.exception.code, 404)
        r = self.post("/api/upload", {"files": [{"name": "big.txt", "b64": base64.b64encode(b"a" * 3_000_000).decode()}]})
        self.assertEqual(len(r["errors"]), 1)

    def test_index_page(self):
        with urllib.request.urlopen(self.base + "/") as r:
            html = r.read().decode("utf-8")
        self.assertIn("Проверка условий договоров поставки", html)


if __name__ == "__main__":
    unittest.main()
