"""Реестр полей: новое поле, добавленное одной строкой в FIELDS, проходит весь путь
(извлечение -> правило допсоглашений -> строка таблицы -> ответ на вопрос) без других правок.
Поле здесь игрушечное (размер аванса) и живёт только внутри теста."""
import re
import unittest

from tests.helpers import sample_texts, run, row
from checker import extract
from checker.engine import answer_question, DEFAULT_AS_OF
from checker.extract import FIELDS, FieldDef, Hit, parse_document
from checker.numbers import find_money, fmt_money


def extract_advance(sent):
    if not re.search(r"аванс", sent, re.I):
        return []
    return [Hit("value", m.value, fmt_money(m.value)) for m in find_money(sent)[:1]]


class FieldRegistryTest(unittest.TestCase):
    def setUp(self):
        FIELDS.append(FieldDef("advance", "Аванс", extract_advance, fmt_money, r"аванс"))

    def tearDown(self):
        FIELDS.pop()

    def test_new_field_flows_through(self):
        res = run(sample_texts())
        self.assertIn({"key": "advance", "label": "Аванс"}, res["fields"])
        f = row(res, "STN-102")["advance"]
        self.assertEqual((f["status"], f["display"]), ("ok", "252 000 ₽"))
        self.assertIn("252 000 рублей", f["source"]["quote"])
        self.assertEqual(row(res, "STN-101")["advance"]["display"], "нет данных")

    def test_question_routes_to_new_field(self):
        docs = [parse_document(n, t) for n, t in sample_texts().items()]
        a = answer_question(docs, "Какой аванс по договору STN-102?", DEFAULT_AS_OF)
        self.assertIn("Аванс по договору STN-102", a["answer"])
        self.assertIn("252 000 ₽", a["answer"])

    def test_registry_is_shared(self):
        self.assertIs(extract.FIELDS, FIELDS)
        self.assertEqual([f.key for f in FIELDS][:2], ["amount", "delivery"])


if __name__ == "__main__":
    unittest.main()
