"""Исходные 6 документов: ответы на четыре вопроса задания и проверяемость источников."""
import unittest
from datetime import date

from tests.helpers import sample_texts, docs_from, run, row, props, mod
from checker.engine import analyze, answer_question, early_delivery, DEFAULT_AS_OF


class SampleAnswersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texts = sample_texts()
        cls.res = run(cls.texts)

    def test_table_has_three_contracts(self):
        self.assertEqual([r["number"] for r in self.res["contracts"]], ["STN-101", "STN-102", "STN-103"])

    def test_q1_stn101_delivery_on_10_march(self):
        r = row(self.res, "STN-101")
        d = r["delivery"]
        self.assertEqual((d["status"], d["value"]), ("changed", "2026-04-30"))
        self.assertEqual(d["source"]["file"], "02_amendment_signed.txt")
        self.assertIn("30.04.2026", d["source"]["quote"])
        self.assertEqual(d["base"]["value"], "2026-04-15")
        self.assertEqual(d["base"]["source"]["file"], "01_contract.txt")
        self.assertEqual(d["changed_by"]["file"], "02_amendment_signed.txt")
        self.assertEqual(d["changed_by"]["effective"], "2026-03-01")

    def test_stn101_amount_changed_by_signed_amendment_not_by_draft(self):
        a = row(self.res, "STN-101")["amount"]
        self.assertEqual((a["status"], a["value"]), ("changed", 1_380_000))
        self.assertEqual(a["base"]["value"], 1_200_000)

    def test_q2_stn102_amount(self):
        a = row(self.res, "STN-102")["amount"]
        self.assertEqual((a["status"], a["value"]), ("ok", 840_000))
        self.assertEqual(a["source"]["file"], "03_contract.txt")
        self.assertEqual(a["source"]["clause"], "2.1")
        # аванс 252 000 не принят за стоимость, но показан как отброшенный
        self.assertEqual([i["display"] for i in a["ignored"]], ["252 000 ₽"])

    def test_q3_stn103_amount_is_no_data(self):
        a = row(self.res, "STN-103")["amount"]
        self.assertEqual((a["status"], a["value"], a["display"]), ("no_data", None, "нет данных"))
        self.assertIn("не указано", a["source"]["quote"])  # цитата, объясняющая отсутствие
        # лимит 600 000 не должен стать суммой
        self.assertEqual([i["display"] for i in a["ignored"]], ["600 000 ₽"])
        self.assertNotIn("600", a["display"])

    def test_q4_early_delivery(self):
        e = early_delivery(self.res, date(2026, 4, 1))
        self.assertEqual([m["number"] for m in e["matches"]], ["STN-102"])
        self.assertEqual(e["matches"][0]["display"], "20.03.2026")
        un = e["matches"][0]["unagreed"]
        self.assertEqual([(p["file"], p["value"]) for p in un], [("05_supplier_email.txt", "2026-03-27")])
        # у STN-101 тоже есть несогласованное изменение срока (проект), но оно не делает поставку «раньше»
        self.assertEqual([m["number"] for m in e["others_with_unagreed"]], ["STN-101"])
        self.assertEqual(e["others_with_unagreed"][0]["unagreed"][0]["value"], "2026-05-10")

    def test_threshold_is_strict(self):
        self.assertEqual([m["number"] for m in early_delivery(self.res, date(2026, 3, 20))["matches"]], [])
        self.assertEqual([m["number"] for m in early_delivery(self.res, date(2026, 3, 21))["matches"]], ["STN-102"])
        self.assertEqual([m["number"] for m in early_delivery(self.res, date(2026, 5, 1))["matches"]],
                         ["STN-101", "STN-102", "STN-103"])

    def test_unagreed_items_are_separate(self):
        r101 = row(self.res, "STN-101")
        self.assertEqual({(p["field"], p["value"]) for p in r101["proposals"]},
                         {("amount", 1_450_000), ("delivery", "2026-05-10")})
        self.assertTrue(all(p["file"] == "06_amendment_draft.txt" for p in r101["proposals"]))
        r102 = row(self.res, "STN-102")
        self.assertEqual([(p["field"], p["file"], p["old"]) for p in r102["proposals"]],
                         [("delivery", "05_supplier_email.txt", "2026-03-20")])
        self.assertEqual(row(self.res, "STN-103")["proposals"], [])

    def test_supplier_and_no_flags_on_clean_sample(self):
        self.assertEqual([r["supplier"]["value"] for r in self.res["contracts"]],
                         ["ООО «Вектор Прибор»", "ООО «Контур Электро»", "ООО «ПромСнаб Сервис»"])
        self.assertFalse(any(r["need_review"] for r in self.res["contracts"]))

    def test_every_source_quote_is_exact_text_of_the_document(self):
        docs = {d.id: d for d in docs_from(self.texts)}

        def check(s):
            d = docs[s["doc_id"]]
            self.assertEqual(d.text[s["start"]:s["end"]], s["quote"])
            p = d.paras[s["para"] - 1]
            self.assertTrue(p.start <= s["start"] and s["end"] <= p.end, s)
            self.assertEqual(d.name, s["file"])

        n = 0
        for r in self.res["contracts"]:
            for s in [r["supplier"]["source"], r["number_source"]]:
                if s:
                    check(s); n += 1
            for k in ("amount", "delivery"):
                f = r[k]
                for s in [f["source"], (f["base"] or {}).get("source")] + [i["source"] for i in f["ignored"]]:
                    if s:
                        check(s); n += 1
            for p in r["proposals"]:
                check(p["source"]); n += 1
        self.assertGreater(n, 15)

    def test_text_questions_from_the_task(self):
        docs = docs_from(self.texts)
        a1 = answer_question(docs, "Какой срок поставки действует по договору STN-101 на 10 марта 2026 года?", DEFAULT_AS_OF)
        self.assertIn("30.04.2026", a1["answer"])
        self.assertIn("02_amendment_signed.txt", a1["answer"])
        self.assertIn("10.05.2026", a1["answer"])  # несогласованный проект показан отдельно
        a2 = answer_question(docs, "Какова сумма договора STN-102?", DEFAULT_AS_OF)
        self.assertIn("840 000", a2["answer"])
        a3 = answer_question(docs, "Какова сумма договора STN-103?", DEFAULT_AS_OF)
        self.assertIn("нет данных", a3["answer"])
        self.assertNotIn("600 000 ₽ на", a3["answer"])
        a4 = answer_question(docs, "По каким договорам поставка запланирована раньше 1 апреля 2026 года и есть ли "
                                   "несогласованные изменения срока?", DEFAULT_AS_OF)
        self.assertEqual(a4["intent"], "early")
        self.assertIn("STN-102 (20.03.2026)", a4["answer"])
        self.assertIn("27.03.2026", a4["answer"])
        a5 = answer_question(docs, "что-то непонятное", DEFAULT_AS_OF)
        self.assertEqual(a5["intent"], "unknown")

    def test_date_in_question_overrides_ui_date(self):
        docs = docs_from(self.texts)
        a = answer_question(docs, "Какой срок поставки по договору STN-101 на 28 февраля 2026?", DEFAULT_AS_OF)
        self.assertIn("15.04.2026", a["answer"])
        self.assertIn("после даты проверки: не действует", a["answer"])  # подписано 01.03, на 28.02 ещё не действует


class CheckDateTest(unittest.TestCase):
    def test_before_amendment_effective_date_original_terms(self):
        res = run(sample_texts(), date(2026, 2, 28))
        r = row(res, "STN-101")
        self.assertEqual((r["delivery"]["status"], r["delivery"]["value"]), ("ok", "2026-04-15"))
        self.assertEqual(r["amount"]["value"], 1_200_000)
        # допсоглашение подписано и вступит в силу: показываем как изменение, которое пока не действует
        states = {p["state"] for p in props(r, "delivery")}
        self.assertEqual(states, {"future", "unsigned"})

    def test_on_effective_date_amendment_applies(self):
        r = row(run(sample_texts(), date(2026, 3, 1)), "STN-101")
        self.assertEqual(r["delivery"]["value"], "2026-04-30")

    def test_contract_not_yet_signed_is_flagged(self):
        res = run(sample_texts(), date(2026, 2, 1))
        self.assertTrue(any("ещё не был подписан" in f for f in row(res, "STN-101")["flags"]))


class NameIndependenceTest(unittest.TestCase):
    def test_renamed_and_shuffled_files_give_same_result(self):
        t = sample_texts()
        names = list(t)
        swapped = {"06_amendment_draft.txt": t["02_amendment_signed.txt"],   # подписанное под именем «проекта»
                   "02_amendment_signed.txt": t["06_amendment_draft.txt"],   # проект под именем «подписанного»
                   "05_supplier_email.txt": t["05_supplier_email.txt"]}
        for n in names:
            swapped.setdefault(n, t[n])
        swapped = {k: swapped[k] for k in reversed(names)}
        a, b = run(t), run(swapped)
        for num in ("STN-101", "STN-102", "STN-103"):
            for k in ("amount", "delivery"):
                self.assertEqual((row(a, num)[k]["status"], row(a, num)[k]["value"]),
                                 (row(b, num)[k]["status"], row(b, num)[k]["value"]), (num, k))

    def test_other_names_entirely(self):
        t = {f"doc{i}.txt": v for i, v in enumerate(sample_texts().values())}
        res = run(t)
        self.assertEqual(row(res, "STN-101")["delivery"]["value"], "2026-04-30")


if __name__ == "__main__":
    unittest.main()
