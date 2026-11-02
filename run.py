#!/usr/bin/env python3
"""Запуск: python3 run.py  ->  http://127.0.0.1:8000
Отчёт без браузера: python3 run.py --report sample_documents/*.txt [--as-of 2026-03-10]"""
import argparse
import os
import sys
import webbrowser
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from checker.engine import DEFAULT_AS_OF, analyze  # noqa: E402
from checker.numbers import fmt_date  # noqa: E402
from checker.server import Store, create_server  # noqa: E402


def print_report(paths, as_of):
    store = Store()
    for p in paths:
        with open(p, "rb") as f:
            store.add(p, f.read())
    res = analyze(store.all(), as_of)
    print(f"Дата проверки: {fmt_date(as_of)}")
    for r in res["contracts"]:
        print(f"\n{r['number']} | {r['supplier']['value']}")
        for key in (fd["key"] for fd in res["fields"]):
            f = r[key]
            src = f["source"]
            where = (f"{src['file']}, абзац {src['para']}" + (f" (п. {src['clause']})" if src["clause"] else "")) if src else "-"
            print(f"  {f['label']}: {f['display']} [{f['status']}] <- {where}")
            if src:
                print(f"      «{src['quote']}»")
        for p in r["proposals"]:
            print(f"  Несогласовано ({p['field']}): {p['label']} -> {p['display']} ({p['file']})")
        for fl in r["flags"]:
            print(f"  ! {fl}")
    for d in res["documents"]:
        if d["link_status"] in ("orphan", "ambiguous"):
            print(f"\nНе связан: {d['name']} - {'; '.join(d['notes'])}")


def main():
    ap = argparse.ArgumentParser(description="Проверка условий договоров поставки (локальный прототип)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--preload", metavar="DIR", help="сразу загрузить все TXT из папки")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--report", nargs="+", metavar="FILE", help="напечатать таблицу в консоль и выйти")
    ap.add_argument("--as-of", default=DEFAULT_AS_OF.isoformat(), help="дата проверки, ГГГГ-ММ-ДД")
    a = ap.parse_args()
    if a.report:
        print_report(a.report, date.fromisoformat(a.as_of))
        return
    srv = create_server(a.host, a.port)
    if a.preload:
        srv.store.add_dir(a.preload)
    url = f"http://{a.host}:{a.port}"
    print(f"Открой {url}  (остановка: Ctrl+C)")
    if not a.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено")


if __name__ == "__main__":
    main()
