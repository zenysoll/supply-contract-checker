import unittest
from datetime import date

from tests.helpers import sample_texts, mod
from checker.extract import parse_document, num_key, canon
from checker.textutil import split_paragraphs, split_sentences


def parse(name):
    t = sample_texts()
    return parse_document(name, t[name])


class ClassificationTest(unittest.TestCase):
    def test_kinds_by_content(self):
        got = {n: parse_document(n, t) for n, t in sample_texts().items()}
        self.assertEqual(got["01_contract.txt"].kind, "contract")
        self.assertEqual(got["02_amendment_signed.txt"].kind, "amendment")
        self.assertEqual(got["05_supplier_email.txt"].kind, "letter")
        d = got["06_amendment_draft.txt"]
        self.assertEqual((d.kind, d.is_draft, d.status), ("amendment", True, "unsigned"))
        self.assertEqual(got["02_amendment_signed.txt"].status, "signed")
        self.assertEqual(got["02_amendment_signed.txt"].signed_date, date(2026, 3, 1))
        self.assertEqual(got["02_amendment_signed.txt"].effective_date, date(2026, 3, 1))

    def test_file_name_is_ignored(self):
        t = sample_texts()
        a = parse_document("zzz.txt", t["06_amendment_draft.txt"])
        b = parse_document("договор_подписан_финал.txt", t["05_supplier_email.txt"])
        self.assertEqual((a.kind, a.status), ("amendment", "unsigned"))
        self.assertEqual(b.kind, "letter")

    def test_numbers_and_refs(self):
        self.assertEqual(parse("01_contract.txt").number, "STN-101")
        self.assertEqual(parse("02_amendment_signed.txt").number, "1")
        self.assertEqual(parse("02_amendment_signed.txt").refs, [("STN101", "STN-101")])
        self.assertEqual(parse("05_supplier_email.txt").refs, [("STN102", "STN-102")])
        self.assertEqual(parse("06_amendment_draft.txt").refs, [("STN101", "STN-101")])

    def test_parties(self):
        d = parse("03_contract.txt")
        self.assertEqual(d.supplier[0], "ООО «Контур Электро»")
        self.assertEqual(d.buyer[0], "ООО «СеверМет»")
        self.assertIn("Контур Электро", d.supplier[1].quote)

    def test_unknown_doc(self):
        d = parse_document("x.txt", "Просто заметки\nкупить молоко 3 литра")
        self.assertEqual(d.kind, "unknown")
        self.assertTrue(d.notes)

    def test_empty_doc(self):
        d = parse_document("x.txt", "")
        self.assertEqual(d.kind, "unknown")

    def test_draft_header_with_signed_status_is_conflict(self):
        t = sample_texts()
        txt = t["06_amendment_draft.txt"].replace("Статус: проект на согласовании, не подписан ни одной стороной.",
                                                  "Статус: подписано обеими сторонами 06.03.2026.")
        d = parse_document("a.txt", txt)
        self.assertEqual(d.status, "unknown")
        self.assertTrue(any("противоречие" in n for n in d.notes))

    def test_status_variants(self):
        t = sample_texts()["02_amendment_signed.txt"]
        for line, want in [("Статус: подписано сторонами 01.03.2026.", "signed"),
                           ("Статус: подписано одной стороной (поставщиком).", "partial"),
                           ("Статус: не подписано.", "unsigned"),
                           ("Статус: на согласовании.", "unsigned"),
                           ("Статус: действует.", "unknown")]:
            d = parse_document("a.txt", t.replace("Статус: подписано обеими сторонами 01.03.2026.", line))
            self.assertEqual(d.status, want, line)


class SentenceTest(unittest.TestCase):
    def test_abbreviations_and_initials_do_not_split(self):
        text = "Сумма 5 000 руб. Поставщик И. И. Иванов обязан. Новое предложение."
        parts = [text[a:b] for a, b in split_sentences(text, 0, len(text))]
        self.assertEqual(len(parts), 2, parts)

    def test_clause_prefix(self):
        ps = split_paragraphs("3.1. Поставщик обязуется.\n\n10.03.2026 заметка\nДата: 05.02.2026")
        self.assertEqual([p.clause for p in ps], ["3.1", None, None])
        self.assertEqual(ps[0].text[ps[0].body_off:], "Поставщик обязуется.")

    def test_hard_wrapped_lines_join(self):
        ps = split_paragraphs("2.1. Общая стоимость поставки составляет\n1 200 000 рублей.\n2.2. Оплата.")
        self.assertEqual(len(ps), 2)


class NumberKeyTest(unittest.TestCase):
    def test_canon(self):
        self.assertEqual(num_key("STN-101"), num_key("STN‑101"))
        self.assertEqual(num_key("STN-101"), num_key("SТN-101"))  # кириллическая Т
        self.assertEqual(num_key("stn-101"), num_key("STN-101"))


if __name__ == "__main__":
    unittest.main()
