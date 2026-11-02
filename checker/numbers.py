"""Даты и суммы в рублях: цифрами, прописью, с множителями. Только регулярные выражения."""
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
          "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}

_MONTH_ALT = "|".join(MONTHS)
DATE_RE = re.compile(
    rf"""(?P<iso>(?<![\d.])(?P<iy>\d{{4}})-(?P<im>\d{{2}})-(?P<id>\d{{2}})(?!\d))
       |(?P<num>(?<![\d.])(?P<nd>\d{{1,2}})[./](?P<nm>\d{{1,2}})[./](?P<ny>\d{{4}})(?!\d))
       |(?P<txt>(?<!\d)(?P<td>\d{{1,2}})\s*[»”\"]?\s+(?P<tm>{_MONTH_ALT})\s+(?P<ty>\d{{4}})(?:\s*(?:года|г\.?))?)
    """, re.X | re.I)


def find_dates(text: str) -> List[Tuple[int, int, date]]:
    """Все корректные даты: 15.04.2026, 15/04/2026, 2026-04-15, «15» апреля 2026 г."""
    out = []
    for m in DATE_RE.finditer(text):
        try:
            if m.group("iso"):
                d = date(int(m.group("iy")), int(m.group("im")), int(m.group("id")))
            elif m.group("num"):
                d = date(int(m.group("ny")), int(m.group("nm")), int(m.group("nd")))
            else:
                d = date(int(m.group("ty")), MONTHS[m.group("tm").lower()], int(m.group("td")))
        except ValueError:
            continue
        out.append((m.start(), m.end(), d))
    return out


def fmt_date(d: Optional[date]) -> str:
    return d.strftime("%d.%m.%Y") if d else "нет данных"


# ---------- числа прописью ----------
_UNITS = {"ноль": 0, "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
          "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
          "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
          "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
          "девятнадцать": 19}
_TENS = {"двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
         "семьдесят": 70, "восемьдесят": 80, "девяносто": 90}
_HUNDREDS = {"сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
             "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900}
_SCALES = [(r"миллиард\w*", 10 ** 9), (r"миллион\w*", 10 ** 6), (r"тысяч\w*", 10 ** 3)]


def _is_number_word(w: str) -> bool:
    return (w in _UNITS or w in _TENS or w in _HUNDREDS
            or any(re.fullmatch(p, w) for p, _ in _SCALES))


def words_to_int(s: str) -> Optional[int]:
    """«один миллион двести тысяч» -> 1200000. Любое незнакомое слово -> None."""
    tokens = re.findall(r"[а-яё]+", s.lower().replace("ё", "е"))
    total, cur, seen = 0, 0, False
    for w in tokens:
        if w in _UNITS:
            cur += _UNITS[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w in _HUNDREDS:
            cur += _HUNDREDS[w]
        else:
            for p, mult in _SCALES:
                if re.fullmatch(p, w):
                    total += (cur or 1) * mult
                    cur = 0
                    break
            else:
                return None
        seen = True
    return total + cur if seen else None


# ---------- суммы ----------
_NUM = (r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d{1,2})?"
        r"|\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?"
        r"|\d+(?:[.,]\d{1,2})?")
_MULT = r"(?:тыс(?:яч\w*)?\.?|млн\.?|миллион\w*|млрд\.?|миллиард\w*)"
_UNIT_RUB = r"(?:руб(?:лей|ля|ль|\.)?|₽|р\.|RUB)(?![а-яёa-z])"
_UNIT_OTHER = r"(?:USD|EUR|CNY|долл\w*|евро|юан\w*|€|\$)(?![а-яёa-z])"
_UNIT_RE = re.compile(rf"(?P<rub>{_UNIT_RUB})|(?P<other>{_UNIT_OTHER})", re.I)
_NUM_TAIL = re.compile(rf"(?<![\d.,])(?P<num>{_NUM})(?:\s*(?P<mult>{_MULT}))?\s*$", re.I)
_KOP_AFTER = re.compile(r"\s*(\d{1,2})\s*коп\w*\.?", re.I)


def parse_decimal(s: str) -> Optional[Decimal]:
    s = s.replace(" ", "").replace(" ", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d{1,2})?", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _mult_value(m: Optional[str]) -> int:
    if not m:
        return 1
    m = m.lower()
    if m.startswith("тыс"):
        return 1000
    if m.startswith("млн") or m.startswith("миллион"):
        return 10 ** 6
    return 10 ** 9


def _digits_before(text: str, pos: int):
    """Число цифрами (с множителем), оканчивающееся прямо перед pos."""
    head = text[:pos].rstrip()
    m = _NUM_TAIL.search(head)
    if not m:
        return None
    v = parse_decimal(m.group("num"))
    if v is None:
        return None
    return v * _mult_value(m.group("mult")), m.start()


def _words_before(text: str, pos: int):
    """Число прописью перед pos: идём назад по словам, пока они числительные."""
    head = text[:pos].rstrip()
    toks = list(re.finditer(r"[А-Яа-яЁё]+", head))
    first, i = None, len(toks) - 1
    # между словами не должно быть ничего, кроме пробелов/дефисов
    while i >= 0 and _is_number_word(toks[i].group().lower().replace("ё", "е")):
        if first is not None and head[toks[i].end():first.start()].strip(" \t\n-"):
            break
        first = toks[i]
        i -= 1
    if first is None:
        return None
    seg = head[first.start():]
    v = words_to_int(seg)
    return (Decimal(v), first.start()) if v is not None else None


@dataclass
class Money:
    start: int
    end: int
    digits: Optional[Decimal]
    words: Optional[int]
    currency: str          # "RUB" или код/слово другой валюты
    raw: str

    @property
    def mismatch(self) -> bool:
        return (self.digits is not None and self.words is not None
                and int(self.digits) != self.words)

    @property
    def value(self) -> Optional[Decimal]:
        return self.digits if self.digits is not None else (
            Decimal(self.words) if self.words is not None else None)


def find_money(text: str) -> List[Money]:
    """Суммы: «1 200 000 (один миллион двести тысяч) рублей», «1,2 млн руб.»,
    «один миллион двести тысяч рублей», «один миллион (1 000 000) руб.». Привязка - к слову «руб…»."""
    out: List[Money] = []
    last_end = 0
    for um in _UNIT_RE.finditer(text):
        if um.start() < last_end:
            continue
        cur = "RUB" if um.group("rub") else um.group("other").upper()
        head_end = um.start()
        digits = words = None
        start = head_end
        head = text[:head_end].rstrip()
        if head.endswith(")"):
            op = head.rfind("(")
            if op != -1:
                inner = head[op + 1:-1]
                rd = _digits_before(inner + " ", len(inner) + 1) if re.search(r"\d", inner) else None
                if rd and not re.search(r"[А-Яа-яЁё]{3,}", re.sub(_MULT, "", inner, flags=re.I)):
                    digits, start = rd[0], op
                    before = _words_before(text, op)
                    if before:
                        words, start = int(before[0]), before[1]
                else:
                    iw = inner.lower().replace("ё", "е")
                    iw = re.split(r"руб", iw)[0]
                    wv = words_to_int(iw)
                    if wv is not None:
                        words, start = wv, op
                        before = _digits_before(text, op)
                        if before:
                            digits, start = before[0], before[1]
        if digits is None and words is None:
            bd = _digits_before(text, head_end)
            if bd:
                digits, start = bd
            else:
                bw = _words_before(text, head_end)
                if bw:
                    words, start = int(bw[0]), bw[1]
                    pre = text[:start].rstrip()
                    if pre.endswith("("):  # «1 380 000 (один миллион ... рублей 00 копеек)»
                        bd2 = _digits_before(text, len(pre) - 1)
                        if bd2:
                            digits, start = bd2
        if digits is None and words is None:
            continue
        end = um.end()
        km = _KOP_AFTER.match(text, end)
        if km and digits is not None:
            digits = digits + Decimal(km.group(1)) / 100
            end = km.end()
        out.append(Money(start, end, digits, words, cur, text[start:end]))
        last_end = end
    return out


def fmt_money(v: Optional[Decimal]) -> str:
    if v is None:
        return "нет данных"
    if v == v.to_integral_value():
        return f"{int(v):,}".replace(",", " ") + " ₽"
    q = v.quantize(Decimal("0.01"))
    whole, frac = f"{q:.2f}".split(".")
    return f"{int(whole):,}".replace(",", " ") + f",{frac} ₽"
