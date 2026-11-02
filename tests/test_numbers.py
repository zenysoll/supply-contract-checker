import unittest
from datetime import date
from decimal import Decimal

from tests import helpers  # noqa: F401
from checker.numbers import find_dates, find_money, words_to_int, fmt_money


class DatesTest(unittest.TestCase):
    def d(self, s):
        return [x[2] for x in find_dates(s)]

    def test_formats(self):
        for s in ["15.04.2026", "15/04/2026", "2026-04-15", "15 апреля 2026", "«15» апреля 2026 г.",
                  "15 апреля 2026 года", "15.4.2026"]:
            self.assertEqual(self.d(s), [date(2026, 4, 15)], s)

    def test_single_digit_day_and_month(self):
        self.assertEqual(self.d("с 1.4.2026"), [date(2026, 4, 1)])

    def test_invalid_date_ignored(self):
        self.assertEqual(self.d("31.02.2026"), [])
        self.assertEqual(self.d("32.01.2026"), [])

    def test_several(self):
        self.assertEqual(self.d("с 20.03.2026 на 27.03.2026"), [date(2026, 3, 20), date(2026, 3, 27)])

    def test_clause_number_is_not_date(self):
        self.assertEqual(self.d("пункт 3.1 и 2.1"), [])


class WordsTest(unittest.TestCase):
    def test_words(self):
        cases = {"один миллион двести тысяч": 1_200_000, "восемьсот сорок тысяч": 840_000,
                 "один миллион триста восемьдесят тысяч": 1_380_000, "сто двадцать три": 123,
                 "две тысячи": 2000, "тысяча": 1000, "пятьсот тысяч": 500_000,
                 "два миллиона пятьсот тысяч": 2_500_000, "ноль": 0}
        for s, v in cases.items():
            self.assertEqual(words_to_int(s), v, s)

    def test_unknown_word(self):
        self.assertIsNone(words_to_int("один мешок"))
        self.assertIsNone(words_to_int(""))


class MoneyTest(unittest.TestCase):
    def one(self, s):
        m = find_money(s)
        self.assertEqual(len(m), 1, s)
        return m[0]

    def test_digits_and_words_agree(self):
        m = self.one("составляет 1 200 000 (один миллион двести тысяч) рублей, включая НДС.")
        self.assertEqual(m.digits, Decimal(1_200_000))
        self.assertEqual(m.words, 1_200_000)
        self.assertFalse(m.mismatch)

    def test_mismatch(self):
        m = self.one("1 200 000 (один миллион триста тысяч) рублей")
        self.assertTrue(m.mismatch)
        self.assertEqual(m.value, Decimal(1_200_000))

    def test_variants(self):
        self.assertEqual(self.one("840000 руб.").value, Decimal(840000))
        self.assertEqual(self.one("840 000 рублей").value, Decimal(840000))
        self.assertEqual(self.one("840 000₽").value, Decimal(840000))
        self.assertEqual(self.one("1,2 млн руб.").value, Decimal(1_200_000))
        self.assertEqual(self.one("1 200 тыс. рублей").value, Decimal(1_200_000))
        self.assertEqual(self.one("1.200.000,50 руб.").value, Decimal("1200000.50"))
        self.assertEqual(self.one("1 200 000 руб. 50 коп.").value, Decimal("1200000.5"))

    def test_words_only_and_reverse_order(self):
        self.assertEqual(self.one("один миллион двести тысяч рублей").value, Decimal(1_200_000))
        m = self.one("Один миллион двести тысяч (1 200 000) руб.")
        self.assertEqual((m.digits, m.words), (Decimal(1_200_000), 1_200_000))

    def test_kopecks_in_words(self):
        m = self.one("1 380 000 (один миллион триста восемьдесят тысяч рублей 00 копеек)")
        self.assertEqual(m.digits, Decimal(1_380_000))
        self.assertFalse(m.mismatch)

    def test_other_currency(self):
        self.assertEqual(self.one("5000 EUR").currency, "EUR")
        self.assertEqual(self.one("5 000 евро").currency, "ЕВРО")

    def test_no_currency_no_money(self):
        self.assertEqual(find_money("приложение № 1, 20 дней, 0,1% стоимости"), [])

    def test_sentence_period_not_eaten(self):
        self.assertEqual(self.one("лимит 600 000 рублей.").raw, "600 000 рублей")

    def test_format(self):
        self.assertEqual(fmt_money(Decimal(1380000)), "1 380 000 ₽")
        self.assertEqual(fmt_money(Decimal("840000.5")), "840 000,50 ₽")


if __name__ == "__main__":
    unittest.main()
