"""Разбиение текста на абзацы и предложения с сохранением смещений.

Все смещения (start/end) считаются в нормализованном тексте документа,
поэтому цитата всегда равна text[start:end] и её можно подсветить в абзаце.
"""
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


def normalize_text(raw: str) -> str:
    """BOM убираем, переводы строк приводим к \\n. Остальное не трогаем."""
    if raw.startswith("﻿"):
        raw = raw[1:]
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def decode_bytes(data: bytes) -> str:
    """UTF-8 (с BOM или без), иначе cp1251 - типичная кодировка старых русских файлов."""
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return normalize_text(data.decode(enc))
        except UnicodeDecodeError:
            continue
    return normalize_text(data.decode("utf-8", errors="replace"))


@dataclass
class Para:
    idx: int            # номер абзаца, с 1
    start: int
    end: int
    text: str
    clause: Optional[str]  # номер пункта в начале абзаца: "2.1", "3"
    body_off: int       # смещение текста после номера пункта (внутри абзаца)


_CLAUSE_RE = re.compile(r"^\s*(?:п\.\s*)?(\d+(?:\.\d+)*)[.)]\s+")
_DATE_LIKE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")


_NUM_CONT = re.compile(r"\d[\d\s.,/-]*\s*[а-яёa-z(₽%]")


def _is_continuation(line: str) -> bool:
    """Строка продолжает предыдущую, если начинается со строчной буквы либо с числа,
    за которым идёт слово/единица («1 200 000 рублей»); «1.2 Предмет» - это новый пункт."""
    return line[0].islower() or bool(_NUM_CONT.match(line))


def split_paragraphs(text: str) -> List[Para]:
    """Абзац - непустая строка. Строка, похожая на продолжение (см. _is_continuation) после строки
    без завершающей точки, присоединяется к предыдущей (жёсткий перенос)."""
    raw: List[List[int]] = []  # [start, end, prev_blank]
    pos = 0
    prev_blank = True
    for line in text.split("\n"):
        end = pos + len(line)
        if line.strip():
            lead = len(line) - len(line.lstrip())
            s = pos + lead
            e = pos + len(line.rstrip())
            if raw and not prev_blank and _is_continuation(line.lstrip()) \
                    and not text[raw[-1][0]:raw[-1][1]].rstrip().endswith((".", "!", "?")):
                raw[-1][1] = e
            else:
                raw.append([s, e, 0])
            prev_blank = False
        else:
            prev_blank = True
        pos = end + 1
    paras = []
    for i, (s, e, _) in enumerate(raw, 1):
        t = text[s:e]
        m = _CLAUSE_RE.match(t)
        clause, off = None, 0
        if m and not _DATE_LIKE.match(m.group(1)):
            clause, off = m.group(1), m.end()
        paras.append(Para(i, s, e, t, clause, off))
    return paras


_ABBR = {"руб", "коп", "тыс", "млн", "млрд", "п", "пп", "ст", "г", "гг", "ул", "д", "кв",
         "т", "им", "см", "напр", "др", "пр", "тел", "обл", "рф", "стр", "ч", "абз", "подп"}
_BOUNDARY = re.compile(r"[.!?]+[»”\")]*\s+")


def split_sentences(text: str, start: int, end: int) -> List[Tuple[int, int]]:
    """Предложения внутри text[start:end] (абсолютные смещения). Точка не делит текст
    после сокращений (руб., тыс., п.) и инициалов; после неё должна идти заглавная буква или кавычка."""
    seg = text[start:end]
    cuts = [0]
    for m in _BOUNDARY.finditer(seg):
        nxt = seg[m.end():m.end() + 1]
        if not nxt or not (nxt.isupper() or nxt in "«“\""):
            continue
        before = seg[:m.start()]
        word = re.search(r"([A-Za-zА-Яа-яЁё]+)$", before)
        if word:
            w = word.group(1)
            if w.lower() in _ABBR or len(w) == 1:
                continue
        cuts.append(m.end())
    cuts.append(len(seg))
    out = []
    for a, b in zip(cuts, cuts[1:]):
        chunk = seg[a:b]
        lead = len(chunk) - len(chunk.lstrip())
        trail = len(chunk) - len(chunk.rstrip())
        if chunk.strip():
            out.append((start + a + lead, start + b - trail))
    return out
