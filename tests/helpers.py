import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from checker.engine import DEFAULT_AS_OF, analyze  # noqa: E402
from checker.extract import parse_document  # noqa: E402

SAMPLES = os.path.join(ROOT, "sample_documents")


def sample_texts():
    out = {}
    for fn in sorted(os.listdir(SAMPLES)):
        with open(os.path.join(SAMPLES, fn), encoding="utf-8") as f:
            out[fn] = f.read()
    return out


def docs_from(texts):
    return [parse_document(n, t) for n, t in texts.items()]


def run(texts, as_of=DEFAULT_AS_OF):
    return analyze(docs_from(texts), as_of)


def row(res, number):
    for r in res["contracts"]:
        if r["number"] == number:
            return r
    raise KeyError(number)


def mod(texts, name, old, new):
    """Копия набора документов с заменой одного фрагмента; падает, если фрагмента нет."""
    assert old in texts[name], f"в {name} нет фрагмента {old!r}"
    t = dict(texts)
    t[name] = t[name].replace(old, new, 1)
    return t


def props(r, field):
    return [p for p in r["proposals"] if p["field"] == field]
