"""Случайно собранные наборы документов того же формата. Ожидание считается независимо, прямо из
параметров генератора (а не из кода проверяемого приложения)."""
import random
import unittest
from datetime import date, timedelta

from tests.helpers import run, row

UNITS = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать",
         "семнадцать", "восемнадцать", "девятнадцать"]
TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
HUND = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def triple(n, fem=False):
    h, r = divmod(n, 100)
    out = [HUND[h]]
    if 10 <= r < 20:
        out.append(TEENS[r - 10])
    else:
        t, u = divmod(r, 10)
        out.append(TENS[t])
        w = UNITS[u]
        if fem and u == 1:
            w = "одна"
        if fem and u == 2:
            w = "две"
        out.append(w)
    return [x for x in out if x]


def words(n):  # n кратно 1000, 1000 <= n < 100 млн
    mln, rest = divmod(n, 1_000_000)
    th = rest // 1000
    out = []
    if mln:
        out += triple(mln)
        m10 = mln % 10 if not 10 <= mln % 100 < 20 else 0
        out.append("миллион" if m10 == 1 else "миллиона" if 2 <= m10 <= 4 else "миллионов")
    if th:
        out += triple(th, fem=True)
        t10 = th % 10 if not 10 <= th % 100 < 20 else 0
        out.append("тысяча" if t10 == 1 else "тысячи" if 2 <= t10 <= 4 else "тысяч")
    return " ".join(out)


def money(n, rnd):
    digits = f"{n:,}".replace(",", rnd.choice([" ", " "]))
    return rnd.choice([f"{digits} ({words(n)}) рублей", f"{digits} рублей", f"{digits} руб.", f"{digits} ₽"])


def fdate(d, rnd):
    return rnd.choice([d.strftime("%d.%m.%Y"), d.strftime("%Y-%m-%d"), f"{d.day} {MONTHS[d.month - 1]} {d.year} года",
                       f"«{d.day:02d}» {MONTHS[d.month - 1]} {d.year} г."])


def make_case(rnd, i):
    """Возвращает (номер, {имя: текст}, дата проверки, ожидаемая сумма, ожидаемый срок).
    Ожидание считается из параметров генератора по правилу задания, без участия кода приложения."""
    as_of = date(2026, 3, 10)
    num = f"{rnd.choice(['STN', 'ABC', 'Д', 'XZ'])}-{rnd.randint(100, 999)}{i}"
    amount = rnd.randint(1, 9999) * 1000
    deliv = as_of + timedelta(days=rnd.randint(-5, 90))
    docs = {f"c{i}.txt": (
        f"ДОГОВОР ПОСТАВКИ № {num}\nДата: 05.02.2026\nСтатус: подписан обеими сторонами 05.02.2026.\n\n"
        f"1.1. Покупатель: ООО «А». Поставщик: ООО «Б{i}».\n\n"
        f"2.1. Общая стоимость поставки составляет {money(amount, rnd)}, включая НДС. Указанная сумма — итоговая стоимость договора.\n"
        f"2.2. Авансовый платеж составляет {rnd.randint(1, 99)} 000 рублей и входит в общую стоимость по пункту 2.1.\n\n"
        f"3.1. Поставщик обязуется поставить товар не позднее {fdate(deliv, rnd)}.\n"
        f"3.2. Оплата оставшейся суммы производится не позднее {fdate(as_of + timedelta(days=30), rnd)}.\n")}
    effective = []  # (дата вступления, новая сумма|None, новый срок|None) только для действующих допсоглашений
    for k in range(rnd.randint(0, 3)):
        status = rnd.choice(["signed", "signed", "unsigned", "partial"])
        eff = as_of + timedelta(days=rnd.randint(-20, 20))
        new_a = rnd.choice([None, rnd.randint(1, 9999) * 1000])
        new_d = rnd.choice([None, as_of + timedelta(days=rnd.randint(-5, 120))])
        if new_a is None and new_d is None:
            new_d = as_of + timedelta(days=100)
        line = {"signed": f"Статус: подписано обеими сторонами {fdate(eff - timedelta(days=1), rnd)}.",
                "unsigned": "Статус: проект на согласовании, не подписан ни одной стороной.",
                "partial": "Статус: подписано одной стороной (поставщиком)."}[status]
        body = []
        if new_a is not None:
            body.append(f"Пункт 2.1 договора изложить в следующей редакции: «Общая стоимость поставки составляет {money(new_a, rnd)}, включая НДС».")
        if new_d is not None:
            body.append(f"Пункт 3.1 договора изложить в следующей редакции: «Поставщик обязуется поставить товар не позднее {fdate(new_d, rnd)}».")
        docs[f"a{i}_{k}.txt"] = (
            f"ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № {k + 1} К ДОГОВОРУ {num}\nДата: 01.03.2026\n{line}\n\n"
            + "\n\n".join(f"{j + 1}. {b}" for j, b in enumerate(body))
            + f"\n\n{len(body) + 1}. Настоящее соглашение вступает в силу {fdate(eff, rnd)}.\n")
        if status == "signed" and eff <= as_of:
            effective.append((eff, new_a, new_d))
    exp_a, exp_d, last_a, last_d = amount, deliv, None, None
    for eff, new_a, new_d in sorted(effective, key=lambda x: x[0]):
        if new_a is not None:
            if last_a and last_a[0] == eff and last_a[1] != new_a:
                return num, docs, as_of, "conflict", "conflict"   # одна дата вступления, разные значения: приложение обязано просить проверку
            exp_a, last_a = new_a, (eff, new_a)
        if new_d is not None:
            if last_d and last_d[0] == eff and last_d[1] != new_d:
                return num, docs, as_of, "conflict", "conflict"
            exp_d, last_d = new_d, (eff, new_d)
    return num, docs, as_of, exp_a, exp_d


class GeneratedSetsTest(unittest.TestCase):
    def test_random_sets(self):
        rnd = random.Random(20260310)
        checked = conflicts = 0
        for i in range(300):
            num, docs, as_of, exp_a, exp_d = make_case(rnd, i)
            r = row(run(docs, as_of), num)
            if exp_a == "conflict":
                conflicts += 1
                self.assertTrue(r["need_review"] or r["amount"]["status"] == "review" or r["delivery"]["status"] == "review", docs)
                continue
            self.assertEqual(r["amount"]["value"], exp_a, docs)
            self.assertEqual(r["delivery"]["value"], exp_d.isoformat(), docs)
            checked += 1
        self.assertGreater(checked, 200)


if __name__ == "__main__":
    unittest.main()
