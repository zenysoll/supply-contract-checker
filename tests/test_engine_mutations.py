"""Модифицированные копии документов: то, что на встрече поменяют руками."""
import unittest
from datetime import date

from tests.helpers import sample_texts, run, row, props, mod, docs_from
from checker.engine import analyze, answer_question, DEFAULT_AS_OF

C101, A1, C102, C103, LET, DRAFT = ("01_contract.txt", "02_amendment_signed.txt", "03_contract.txt",
                                    "04_contract.txt", "05_supplier_email.txt", "06_amendment_draft.txt")

NEW_CONTRACT = """ДОГОВОР ПОСТАВКИ № STN-104
Дата: 25.02.2026
Статус: подписан обеими сторонами 25.02.2026.

1.1. Покупатель: ООО «СеверМет». Поставщик: ИП Петров И. И.
1.2. Предмет: поставка инструмента.

2.1. Общая стоимость поставки составляет 2 500 000 (два миллиона пятьсот тысяч) рублей, включая НДС. Указанная сумма — итоговая стоимость договора.
2.2. Аванс составляет 500 000 рублей и входит в общую стоимость по пункту 2.1.

3.1. Поставщик обязуется поставить инструмент не позднее 18 марта 2026 года.
3.2. Оплата производится не позднее 01.03.2026.
"""

AMEND_3 = """ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 3 К ДОГОВОРУ STN-101
Дата: 05.03.2026
Статус: подписано обеими сторонами 05.03.2026.

1. Пункт 3.1 договора изложить в следующей редакции: «Поставщик обязуется поставить оборудование не позднее 15.05.2026».

2. Настоящее соглашение вступает в силу 05.03.2026.
"""


class ChangedValuesTest(unittest.TestCase):
    def setUp(self):
        self.t = sample_texts()

    def test_amount_changed_digits_and_words(self):
        t = mod(self.t, C102, "840 000 (восемьсот сорок тысяч)", "910 000 (девятьсот десять тысяч)")
        a = row(run(t), "STN-102")["amount"]
        self.assertEqual((a["status"], a["value"]), ("ok", 910_000))
        self.assertIn("910 000", a["source"]["quote"])

    def test_digits_changed_but_words_not_means_check(self):
        t = mod(self.t, C102, "840 000 (восемьсот сорок тысяч)", "950 000 (восемьсот сорок тысяч)")
        r = row(run(t), "STN-102")
        self.assertEqual(r["amount"]["status"], "review")
        self.assertTrue(any("не совпадают" in n for n in r["amount"]["notes"]))
        self.assertEqual({a["display"] for a in r["amount"]["alternatives"]},
                         {"цифрами 950 000 ₽", "прописью 840 000 ₽"})
        self.assertTrue(r["need_review"])

    def test_delivery_date_formats(self):
        for new in ["25.03.2026", "25/03/2026", "2026-03-25", "25 марта 2026 года", "«25» марта 2026 г."]:
            t = mod(self.t, C102, "20.03.2026", new)
            d = row(run(t), "STN-102")["delivery"]
            self.assertEqual((d["status"], d["value"]), ("ok", "2026-03-25"), new)

    def test_amount_notations(self):
        for new, val in [("840 000 рублей", 840_000), ("восемьсот сорок тысяч рублей", 840_000),
                         ("0,84 млн руб.", 840_000), ("840000 руб.", 840_000), ("840 000,50 руб.", 840_000.5),
                         ("840 000 ₽", 840_000), ("840 000,00 руб.", 840_000), ("840 000 рублей 00 копеек", 840_000)]:
            t = mod(self.t, C102, "840 000 (восемьсот сорок тысяч) рублей", new)
            a = row(run(t), "STN-102")["amount"]
            self.assertEqual((a["status"], a["value"]), ("ok", val), new)

    def test_other_contract_phrase_forms(self):
        t = mod(self.t, C102, "Общая стоимость поставки составляет", "Цена договора составляет")
        self.assertEqual(row(run(t), "STN-102")["amount"]["value"], 840_000)
        t = mod(self.t, C102, "Общая стоимость поставки составляет 840 000 (восемьсот сорок тысяч) рублей, включая НДС.",
                "Договор заключён на общую сумму 840 000 (восемьсот сорок тысяч) рублей, включая НДС.")
        self.assertEqual(row(run(t), "STN-102")["amount"]["value"], 840_000)
        t = mod(self.t, C102, "Поставщик обязуется поставить комплектующие не позднее 20.03.2026.",
                "Срок поставки — до 22.03.2026.")
        self.assertEqual(row(run(t), "STN-102")["delivery"]["value"], "2026-03-22")

    def test_advance_before_total_is_still_not_the_total(self):
        t = mod(self.t, C102, "2.1. Общая", "2.0. Авансовый платеж составляет 252 000 рублей и входит в общую стоимость.\n2.1. Общая")
        a = row(run(t), "STN-102")["amount"]
        self.assertEqual((a["status"], a["value"]), ("ok", 840_000))

    def test_payment_date_is_not_delivery_even_if_first(self):
        t = mod(self.t, C102, "3.1. Поставщик", "3.0. Оплата производится не позднее 10.04.2026, но поставка раньше.\n3.1. Поставщик")
        d = row(run(t), "STN-102")["delivery"]
        self.assertEqual((d["status"], d["value"]), ("ok", "2026-03-20"))


class MissingDataTest(unittest.TestCase):
    def setUp(self):
        self.t = sample_texts()

    def test_amount_clause_removed_means_no_data(self):
        t = mod(self.t, C102, "Общая стоимость поставки составляет 840 000 (восемьсот сорок тысяч) рублей, включая НДС. "
                              "Указанная сумма — итоговая стоимость договора.", "Стоимость согласуется сторонами отдельно.")
        a = row(run(t), "STN-102")["amount"]
        self.assertEqual((a["status"], a["value"], a["display"]), ("no_data", None, "нет данных"))
        self.assertFalse(row(run(t), "STN-102")["need_review"])
        # аванс 252 000 не подменил отсутствующую сумму
        self.assertNotEqual(a["value"], 252_000)

    def test_delivery_clause_removed(self):
        t = mod(self.t, C102, "3.1. Поставщик обязуется поставить комплектующие не позднее 20.03.2026.",
                "3.1. Комплектующие поставляются партиями.")
        d = row(run(t), "STN-102")["delivery"]
        self.assertEqual((d["status"], d["value"]), ("no_data", None))
        # дата оплаты 10.04.2026 не стала сроком поставки
        self.assertEqual(d["display"], "нет данных")

    def test_supplier_missing(self):
        t = mod(self.t, C102, "1.1. Покупатель: ООО «СеверМет». Поставщик: ООО «Контур Электро».", "1.1. Покупатель: ООО «СеверМет».")
        self.assertEqual(row(run(t), "STN-102")["supplier"]["value"], "нет данных")

    def test_amount_given_only_by_amendment_for_contract_without_price(self):
        extra = """ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1 К ДОГОВОРУ STN-103
Дата: 02.03.2026
Статус: подписано обеими сторонами 02.03.2026.

1. Пункт 2.1 договора изложить в следующей редакции: «Общая стоимость поставки составляет 540 000 (пятьсот сорок тысяч) рублей, включая НДС».

2. Настоящее соглашение вступает в силу с момента подписания.
"""
        t = dict(self.t); t["x.txt"] = extra
        r = row(run(t), "STN-103")
        self.assertEqual((r["amount"]["status"], r["amount"]["value"]), ("changed", 540_000))
        self.assertIsNone(r["amount"]["base"])
        self.assertTrue(any("в самом договоре значения не было" in n for n in r["amount"]["notes"]))
        # лимит 600 000 по-прежнему ни при чём
        self.assertNotEqual(r["amount"]["value"], 600_000)

    def test_foreign_currency_is_not_rubles(self):
        t = mod(self.t, C102, "840 000 (восемьсот сорок тысяч) рублей", "9 000 евро")
        a = row(run(t), "STN-102")["amount"]
        self.assertEqual((a["status"], a["value"]), ("review", None))

    def test_relative_delivery_term_needs_check_not_invented(self):
        t = mod(self.t, C102, "не позднее 20.03.2026", "в течение 30 календарных дней с даты оплаты аванса")
        d = row(run(t), "STN-102")["delivery"]
        self.assertEqual((d["status"], d["value"]), ("review", None))
        self.assertTrue(row(run(t), "STN-102")["need_review"])

    def test_two_different_totals_in_one_contract(self):
        t = mod(self.t, C102, "5.1. Изменения", "4.2. Общая стоимость договора составляет 800 000 рублей.\n5.1. Изменения")
        a = row(run(t), "STN-102")["amount"]
        self.assertEqual((a["status"], a["value"]), ("review", None))
        self.assertEqual(len(a["alternatives"]), 2)

    def test_same_total_repeated_is_not_a_conflict(self):
        t = mod(self.t, C102, "5.1. Изменения", "4.2. Общая стоимость договора составляет 840 000 рублей.\n5.1. Изменения")
        a = row(run(t), "STN-102")["amount"]
        self.assertEqual((a["status"], a["value"]), ("ok", 840_000))


class ProposalPhrasingTest(unittest.TestCase):
    def setUp(self):
        self.t = sample_texts()

    def letter(self, sentence):
        return mod(self.t, LET, "по договору STN-102 предлагаем перенести срок поставки с 20.03.2026 на 27.03.2026 из-за задержки комплектующих.",
                   sentence)

    def test_letter_amount_from_to(self):
        r = row(run(self.letter("по договору STN-102 предлагаем изменить стоимость договора с 840 000 рублей на 900 000 рублей.")), "STN-102")
        p = props(r, "amount")
        self.assertEqual([(x["value"], x["old"]) for x in p], [(900_000, 840_000)])
        self.assertEqual(r["amount"]["value"], 840_000)

    def test_letter_amount_delta_is_not_taken_as_total(self):
        r = row(run(self.letter("по договору STN-102 предлагаем увеличить стоимость договора на 60 000 рублей.")), "STN-102")
        p = props(r, "amount")
        self.assertEqual(len(p), 1)
        self.assertIsNone(p[0]["value"])
        self.assertEqual(p[0]["display"], "не разобрано")
        self.assertEqual(r["amount"]["value"], 840_000)

    def test_effective_amendment_with_delta_needs_check(self):
        t = mod(self.t, A1, "Общая стоимость поставки составляет 1 380 000 (один миллион триста восемьдесят тысяч) рублей, включая НДС. Указанная сумма — итоговая стоимость договора",
                "Стоимость договора увеличить на 180 000 рублей")
        r = row(run(t), "STN-101")
        self.assertEqual((r["amount"]["status"], r["amount"]["value"]), ("review", None))
        self.assertEqual(r["delivery"]["value"], "2026-04-30")

    def test_letter_delivery_in_days_is_not_a_date(self):
        r = row(run(self.letter("по договору STN-102 предлагаем перенести срок поставки на 7 дней.")), "STN-102")
        p = props(r, "delivery")
        self.assertEqual((p[0]["value"], p[0]["display"]), (None, "не разобрано"))

    def test_letter_refers_to_old_date_that_is_not_current(self):
        t = mod(self.t, C102, "20.03.2026", "25.03.2026")   # в договоре 25.03, а письмо переносит «с 20.03»
        r = row(run(t), "STN-102")
        self.assertEqual(r["delivery"]["value"], "2026-03-25")
        self.assertTrue(r["need_review"])
        self.assertTrue(any("прежнего значения 20.03.2026" in f for f in r["flags"]), r["flags"])
        self.assertFalse(row(run(self.t), "STN-102")["need_review"])  # на исходных данных замечания нет

    def test_passive_voice_delivery(self):
        t = mod(self.t, C102, "Поставщик обязуется поставить комплектующие не позднее 20.03.2026.",
                "Комплектующие должны быть поставлены до 21.03.2026.")
        self.assertEqual(row(run(t), "STN-102")["delivery"]["value"], "2026-03-21")


class DocumentStatusTest(unittest.TestCase):
    SIGNED_LINE = "Статус: подписано обеими сторонами 01.03.2026."

    def setUp(self):
        self.t = sample_texts()

    def test_unsigned_amendment_does_not_change_terms(self):
        t = mod(self.t, A1, self.SIGNED_LINE, "Статус: проект на согласовании, не подписан ни одной стороной.")
        r = row(run(t), "STN-101")
        self.assertEqual((r["amount"]["value"], r["delivery"]["value"]), (1_200_000, "2026-04-15"))
        self.assertEqual(r["delivery"]["status"], "ok")
        self.assertEqual({p["value"] for p in props(r, "delivery")}, {"2026-04-30", "2026-05-10"})

    def test_signed_by_one_side_does_not_change_terms(self):
        t = mod(self.t, A1, self.SIGNED_LINE, "Статус: подписано одной стороной (поставщиком).")
        r = row(run(t), "STN-101")
        self.assertEqual(r["delivery"]["value"], "2026-04-15")
        self.assertIn("partial", {p["state"] for p in props(r, "delivery")})

    def test_signed_after_check_date_is_not_applied(self):
        t = mod(self.t, A1, self.SIGNED_LINE, "Статус: подписано обеими сторонами 15.03.2026.")
        r = row(run(t), "STN-101")
        self.assertEqual(r["delivery"]["value"], "2026-04-15")
        self.assertEqual(row(run(t, date(2026, 3, 15)), "STN-101")["delivery"]["value"], "2026-04-30")

    def test_unrecognised_status_is_check_and_not_applied(self):
        t = mod(self.t, A1, self.SIGNED_LINE, "Статус: действует.")
        r = row(run(t), "STN-101")
        self.assertEqual(r["delivery"]["value"], "2026-04-15")
        self.assertTrue(r["need_review"])

    def test_effective_date_in_future(self):
        t = mod(self.t, A1, "Настоящее соглашение вступает в силу 01.03.2026.", "Настоящее соглашение вступает в силу 20.03.2026.")
        r = row(run(t), "STN-101")
        self.assertEqual((r["delivery"]["status"], r["delivery"]["value"]), ("ok", "2026-04-15"))
        future = [p for p in props(r, "delivery") if p["state"] == "future"]
        self.assertEqual(len(future), 1)
        self.assertIn("20.03.2026", future[0]["label"])
        self.assertFalse(any(f for f in r["flags"] if "дат" in f and "вступлен" in f))
        # на дату вступления в силу условия применяются
        r2 = row(run(t, date(2026, 3, 20)), "STN-101")
        self.assertEqual(r2["delivery"]["value"], "2026-04-30")

    def test_effective_date_missing_is_check(self):
        t = mod(self.t, A1, "4. Настоящее соглашение вступает в силу 01.03.2026.", "")
        r = row(run(t), "STN-101")
        self.assertEqual(r["delivery"]["value"], "2026-04-15")
        self.assertTrue(r["need_review"])
        self.assertTrue(any("вступлен" in f or "вступит" in f for f in r["flags"]), r["flags"])

    def test_effective_from_signing(self):
        t = mod(self.t, A1, "вступает в силу 01.03.2026", "вступает в силу с момента подписания")
        r = row(run(t), "STN-101")
        self.assertEqual(r["delivery"]["value"], "2026-04-30")
        self.assertFalse(r["need_review"])

    def test_effective_date_in_other_format(self):
        t = mod(self.t, A1, "вступает в силу 01.03.2026", "вступает в силу «5» марта 2026 года")
        d = row(run(t), "STN-101")["delivery"]
        self.assertEqual((d["value"], d["changed_by"]["effective"]), ("2026-04-30", "2026-03-05"))

    def test_conditional_effective_date_is_check(self):
        t = mod(self.t, A1, "вступает в силу 01.03.2026", "вступает в силу после оплаты аванса")
        r = row(run(t), "STN-101")
        self.assertEqual(r["delivery"]["value"], "2026-04-15")
        self.assertTrue(r["need_review"])

    def test_letter_never_changes_terms_even_if_it_claims_to_be_signed(self):
        t = mod(self.t, LET, "Дата: 05.03.2026", "Дата: 05.03.2026\nСтатус: подписано обеими сторонами 05.03.2026.")
        r = row(run(t), "STN-102")
        self.assertEqual(r["delivery"]["value"], "2026-03-20")
        self.assertEqual(props(r, "delivery")[0]["state"], "letter")

    def test_unsigned_contract_is_flagged(self):
        t = mod(self.t, C102, "Статус: подписан обеими сторонами 10.02.2026.", "Статус: проект, не подписан.")
        r = row(run(t), "STN-102")
        self.assertTrue(r["need_review"])
        self.assertEqual(r["amount"]["value"], 840_000)  # значение показываем, но с флагом


class LinkingTest(unittest.TestCase):
    def setUp(self):
        self.t = sample_texts()

    def test_two_signed_amendments_later_effective_wins_regardless_of_names(self):
        for names in [("02_a.txt", "zz_amend3.txt"), ("zz.txt", "00_first.txt")]:
            t = dict(self.t); del t[A1]
            t[names[0]] = self.t[A1]
            t[names[1]] = AMEND_3
            r = row(run(t), "STN-101")
            self.assertEqual(r["delivery"]["value"], "2026-05-15", names)
            self.assertEqual(r["delivery"]["changed_by"]["number"], "3")
            self.assertEqual(r["amount"]["value"], 1_380_000)  # сумму меняет только №1

    def test_amendment_of_earlier_date_does_not_override_later(self):
        t = dict(self.t)
        t["x.txt"] = AMEND_3.replace("05.03.2026", "15.02.2026").replace("15.05.2026", "01.06.2026")
        # №3 вступил 15.02, №1 - 01.03: действует №1
        self.assertEqual(row(run(t), "STN-101")["delivery"]["value"], "2026-04-30")

    def test_same_effective_date_different_values_is_check(self):
        t = dict(self.t)
        t["x.txt"] = AMEND_3.replace("05.03.2026", "01.03.2026")
        r = row(run(t), "STN-101")
        self.assertEqual((r["delivery"]["status"], r["delivery"]["value"]), ("review", None))

    def test_orphan_amendment_is_not_applied_and_listed(self):
        t = mod(self.t, A1, "К ДОГОВОРУ STN-101", "К ДОГОВОРУ STN-999")
        res = run(t)
        self.assertEqual(row(res, "STN-101")["delivery"]["value"], "2026-04-15")
        doc = [d for d in res["documents"] if d["name"] == A1][0]
        self.assertEqual(doc["link_status"], "orphan")
        self.assertIn("STN-999", " ".join(doc["notes"]))

    def test_document_mentioning_two_contracts_is_ambiguous(self):
        t = mod(self.t, A1, "3. Остальные условия", "3. Договор STN-102 не затрагивается. Остальные условия")
        res = run(t)
        r = row(res, "STN-101")
        self.assertEqual(r["delivery"]["value"], "2026-04-15")
        self.assertTrue(r["need_review"])
        self.assertTrue(any("несколько договоров" in f for f in r["flags"]))

    def test_cyrillic_lookalike_in_contract_number(self):
        t = mod(self.t, A1, "К ДОГОВОРУ STN-101", "К ДОГОВОРУ SТN-101")  # кириллическая Т
        self.assertEqual(row(run(t), "STN-101")["delivery"]["value"], "2026-04-30")

    def test_lowercase_and_no_dash(self):
        t = mod(self.t, A1, "К ДОГОВОРУ STN-101", "к договору № STN101")
        self.assertEqual(row(run(t), "STN-101")["delivery"]["value"], "2026-04-30")

    def test_letter_linked_by_number_in_text_without_word_dogovor(self):
        t = mod(self.t, LET, "Тема: договор STN-102", "Тема: поставка")
        t = mod(t, LET, "по договору STN-102 предлагаем", "по заказу STN-102 предлагаем")
        r = row(run(t), "STN-102")
        self.assertEqual([p["value"] for p in props(r, "delivery")], ["2026-03-27"])

    def test_duplicate_contract_number_flagged(self):
        t = dict(self.t); t["copy.txt"] = self.t[C102]
        res = run(t)
        flagged = [r for r in res["contracts"] if r["number"] == "STN-102"]
        self.assertEqual(len(flagged), 2)
        self.assertTrue(all(r["need_review"] for r in flagged))

    def test_renumbering_everything_keeps_results(self):
        t = {k: v.replace("STN-10", "ABC/77-").replace("STN", "ABC") for k, v in self.t.items()}
        res = run(t)
        self.assertEqual([r["number"] for r in res["contracts"]], ["ABC/77-1", "ABC/77-2", "ABC/77-3"])
        self.assertEqual(row(res, "ABC/77-1")["delivery"]["value"], "2026-04-30")
        self.assertEqual(row(res, "ABC/77-2")["amount"]["value"], 840_000)
        self.assertEqual(row(res, "ABC/77-3")["amount"]["status"], "no_data")
        self.assertEqual(len(props(row(res, "ABC/77-2"), "delivery")), 1)

    def test_numeric_only_contract_number(self):
        t = {k: v.replace("№ STN-101", "№ 15/2026").replace("ДОГОВОРУ STN-101", "ДОГОВОРУ № 15/2026").replace("STN-101", "№ 15/2026")
             for k, v in self.t.items()}
        res = run(t)
        r = row(res, "15/2026")
        self.assertEqual(r["delivery"]["value"], "2026-04-30")

    def test_new_contract_same_format(self):
        t = dict(self.t); t["new.txt"] = NEW_CONTRACT
        res = run(t)
        self.assertEqual(len(res["contracts"]), 4)
        r = row(res, "STN-104")
        self.assertEqual((r["amount"]["value"], r["delivery"]["value"]), (2_500_000, "2026-03-18"))
        self.assertEqual(r["supplier"]["value"], "ИП Петров И. И.")
        self.assertEqual([i["display"] for i in r["amount"]["ignored"]], ["500 000 ₽"])
        # остальные договоры не изменились
        self.assertEqual(row(res, "STN-102")["amount"]["value"], 840_000)

    def test_new_contract_changes_early_filter(self):
        t = dict(self.t); t["new.txt"] = NEW_CONTRACT
        a = answer_question(docs_from(t), "Какие поставки раньше 1 апреля 2026?", DEFAULT_AS_OF)
        self.assertIn("STN-102 (20.03.2026)", a["answer"])
        self.assertIn("STN-104 (18.03.2026)", a["answer"])


class RobustnessTest(unittest.TestCase):
    def setUp(self):
        self.t = sample_texts()

    def test_hard_wrapped_contract(self):
        t = mod(self.t, C102, "Общая стоимость поставки составляет 840 000 (восемьсот сорок тысяч) рублей, включая НДС.",
                "Общая стоимость поставки составляет\n840 000 (восемьсот сорок тысяч) рублей,\nвключая НДС.")
        a = row(run(t), "STN-102")["amount"]
        self.assertEqual(a["value"], 840_000)
        self.assertIn("\n", a["source"]["quote"])  # цитата дословная, вместе с переносами

    def test_crlf_and_bom_files(self):
        from checker.server import Store
        s = Store()
        raw = ("﻿" + self.t[C102].replace("\n", "\r\n")).encode("utf-8")
        s.add("x.txt", raw)
        res = analyze(s.all(), DEFAULT_AS_OF)
        self.assertEqual(res["contracts"][0]["amount"]["value"], 840_000)

    def test_cp1251_file(self):
        from checker.server import Store
        s = Store()
        s.add("x.txt", self.t[C102].encode("cp1251"))
        self.assertEqual(analyze(s.all(), DEFAULT_AS_OF)["contracts"][0]["delivery"]["value"], "2026-03-20")

    def test_empty_upload_and_junk_do_not_crash(self):
        t = dict(self.t); t["empty.txt"] = ""; t["junk.txt"] = "\x00\x01 ??? 12345"
        res = run(t)
        self.assertEqual(len(res["contracts"]), 3)
        kinds = {d["name"]: d["kind"] for d in res["documents"]}
        self.assertEqual(kinds["empty.txt"], "unknown")

    def test_unparsed_change_in_effective_amendment_is_check(self):
        t = mod(self.t, A1, "Пункт 3.1 договора изложить в следующей редакции: «Поставщик обязуется поставить оборудование не позднее 30.04.2026».",
                "Срок поставки по пункту 3.1 продлить на 10 календарных дней.")
        r = row(run(t), "STN-101")
        self.assertEqual((r["delivery"]["status"], r["delivery"]["value"]), ("review", None))
        self.assertEqual(r["amount"]["value"], 1_380_000)  # соседнее поле не пострадало

    def test_penalty_amendment_does_not_trigger_review(self):
        t = mod(self.t, A1, "3. Остальные условия договора, в том числе размер неустойки, остаются без изменений.",
                "3. Пункт 4.1 договора изложить в редакции: «Неустойка составляет 0,2% стоимости просроченной части поставки за каждый день».")
        r = row(run(t), "STN-101")
        self.assertFalse(r["need_review"], r["flags"])

    def test_check_date_changes_result_only_by_status(self):
        for as_of, want in [(date(2026, 3, 9), "2026-04-30"), (date(2026, 3, 10), "2026-04-30")]:
            self.assertEqual(row(run(self.t, as_of), "STN-101")["delivery"]["value"], want)


class MeetingScenarioTest(unittest.TestCase):
    """Как на встрече: поменяли одно поле и добавили новый договор с допсоглашением, подписанным после даты проверки."""

    def test_changed_field_plus_new_contract_with_future_amendment(self):
        t = mod(sample_texts(), C102, "840 000 (восемьсот сорок тысяч)", "915 500 (девятьсот пятнадцать тысяч пятьсот)")
        t["07_new.txt"] = NEW_CONTRACT
        t["08_new_amendment.txt"] = AMEND_3.replace("STN-101", "STN-104").replace("05.03.2026", "12.03.2026")
        res = run(t)
        self.assertEqual(row(res, "STN-102")["amount"]["display"], "915 500 ₽")
        self.assertEqual(row(res, "STN-104")["delivery"]["display"], "18.03.2026")
        self.assertEqual([p["state"] for p in props(row(res, "STN-104"), "delivery")], ["future"])
        a = answer_question(docs_from(t), "Где поставка раньше 01.04.2026?", DEFAULT_AS_OF)["answer"]
        self.assertIn("STN-104 (18.03.2026)", a)
        self.assertIn("ещё не действующие", a)
        self.assertEqual(row(run(t, date(2026, 3, 15)), "STN-104")["delivery"]["display"], "15.05.2026")


if __name__ == "__main__":
    unittest.main()
