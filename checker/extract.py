"""Разбор одного документа: тип и статус - по содержанию, значения полей - по правилам.

Имя файла нигде не используется для логики; оно нужно только для показа пользователю.
Чтобы добавить новое поле (например, ставку неустойки), нужно написать функцию
extract_<поле>(предложение) -> [Hit] и добавить строку в реестр FIELDS внизу файла.
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

from .numbers import find_dates, find_money, fmt_date, fmt_money
from .textutil import Para, split_paragraphs, split_sentences


@dataclass
class Src:
    para: int
    clause: Optional[str]
    start: int
    end: int
    quote: str


@dataclass
class Hit:
    kind: str                      # value | ignored | absent | relative | unparsed
    value: Any = None
    display: str = ""
    flags: List[str] = field(default_factory=list)
    alts: List[Tuple[Any, str]] = field(default_factory=list)  # если в предложении несколько кандидатов
    old: Any = None                # прежнее значение в обороте «с X на Y»
    reason: str = ""
    amends: Optional[str] = None   # какой пункт договора меняется
    src: Optional[Src] = None
    field: str = ""


@dataclass(eq=False)  # сравнение по identity: иначе `doc in list` сравнивает все поля и тормозит
class Doc:
    id: str
    name: str
    text: str
    paras: List[Para]
    kind: str = "unknown"          # contract | amendment | letter | attachment | unknown
    is_draft: bool = False
    status: str = "unknown"        # signed | unsigned | partial | unknown | na
    status_src: Optional[Src] = None
    signed_date: Optional[date] = None
    effective_date: Optional[date] = None
    effective_src: Optional[Src] = None
    effective_note: str = ""
    doc_date: Optional[date] = None
    number: Optional[str] = None   # собственный номер: договора или допсоглашения
    number_src: Optional[Src] = None
    refs: List[Tuple[str, str]] = field(default_factory=list)  # (ключ, как написано) - ссылки на договоры
    supplier: Optional[Tuple[str, Src]] = None
    buyer: Optional[Tuple[str, Src]] = None
    sender: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    hits: Dict[str, List[Hit]] = field(default_factory=dict)


# ---------- номера договоров ----------
_LOOK = str.maketrans("АВЕКМНОРСТХУ", "ABEKMHOPCTXY")
_HYPHENS = "‐‑‒–—−"


def canon(s: str, keep_spaces: bool = False) -> str:
    """Каноническая запись номера: латиница вместо похожей кириллицы, один вид дефиса."""
    s = s.upper().translate(_LOOK)
    for h in _HYPHENS:
        s = s.replace(h, "-")
    return s if keep_spaces else re.sub(r"\s+", "", s)


def num_key(s: str) -> str:
    return re.sub(r"[^A-Z0-9А-Я]", "", canon(s))


_TOK = r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-‐‑‒–—−/_.]*[A-Za-zА-Яа-яЁё0-9]|\d"
REF_RE = re.compile(
    rf"(?:договор\w*|контракт\w*)\s+(?:(?:на\s+)?(?:поставк\w*|купли[-‐‑]продажи|подряда|оказания\s+услуг)\s+)?"
    rf"(?:(?P<sign>№|N|No\.?|#)\s*)?(?P<tok>{_TOK})", re.I)


def find_contract_refs(text: str) -> List[Tuple[int, int, str]]:
    out = []
    for m in REF_RE.finditer(text):
        tok = m.group("tok")
        has_digit = re.search(r"\d", tok) is not None
        has_letter = re.search(r"[A-Za-zА-Яа-яЁё]", tok) is not None
        if m.group("sign"):
            ok = has_digit
        else:
            ok = has_digit and has_letter
        if ok:
            out.append((m.start("tok"), m.end("tok"), tok))
    return out


# ---------- тип документа ----------
_TITLES = [
    ("amendment", True, re.compile(r"^\s*проект\s+(?:дополнительного\s+соглашения|доп\.?\s*соглашения|дс\b)", re.I)),
    ("contract", True, re.compile(r"^\s*проект\s+(?:договора|контракта)", re.I)),
    ("amendment", False, re.compile(r"^\s*(?:дополнительное\s+соглашение|доп\.?\s*соглашение|дс)\b", re.I)),
    ("letter", False, re.compile(r"^\s*(?:письмо|уведомление|претензия|запрос)\b", re.I)),
    ("attachment", False, re.compile(r"^\s*(?:спецификация|приложение)\b", re.I)),
    ("contract", False, re.compile(r"^\s*(?:договор|контракт)\b", re.I)),
]


def detect_kind(paras: List[Para]) -> Tuple[str, bool, str]:
    for p in paras[:4]:
        if len(p.text) > 250:
            continue
        for kind, draft, rx in _TITLES:
            if rx.search(p.text):
                return kind, draft, "по заголовку"
    head = "\n".join(p.text for p in paras[:12])
    if len(re.findall(r"^\s*(?:От|Кому|Тема|From|To|Subject)\s*:", head, re.I | re.M)) >= 2:
        return "letter", False, "по реквизитам письма (От/Кому/Тема)"
    full = "\n".join(p.text for p in paras)
    if re.search(r"договор", full, re.I) and re.search(r"покупател", full, re.I) \
            and re.search(r"поставщик", full, re.I):
        return "contract", False, "по содержанию (стороны и предмет), заголовок нестандартный"
    return "unknown", False, "тип не определён"


# ---------- статус подписания ----------
_NOT_SIGNED = re.compile(r"не\s+подписан\w*|без\s+подписи|проект|на\s+согласовани|не\s+вступил", re.I)
_PARTIAL = re.compile(r"подписан[оы]?\s+(?:только\s+|пока\s+)?(?:одной\s+стороной|поставщиком|покупателем|"
                      r"продавцом|со\s+стороны|с\s+нашей\s+стороны)", re.I)
_SIGNED_BOTH = re.compile(r"\bподписан[оы]?\b\s+(?:\w+\s+){0,2}?(?:обеими|двумя|всеми|сторонами)"
                          r"|\bподписан[оы]?\s+сторонами", re.I)
_STATUS_LINE = re.compile(r"^\s*(?:статус|состояние)\s*[:—–-]\s*(.+)$", re.I | re.S)


def _src_for_span(doc_text: str, p: Para, s: int, e: int) -> Src:
    return Src(p.idx, p.clause, s, e, doc_text[s:e])


def _classify_status(s: str) -> str:
    if _PARTIAL.search(s):
        return "partial"
    if _NOT_SIGNED.search(s):
        return "unsigned"
    if _SIGNED_BOTH.search(s):
        return "signed"
    return "unknown"


def parse_status(doc: Doc):
    for p in doc.paras[:10]:
        m = _STATUS_LINE.match(p.text)
        if m:
            st = _classify_status(m.group(1))
            ds = find_dates(m.group(1))
            doc.status = st
            doc.status_src = Src(p.idx, p.clause, p.start, p.end, p.text)
            if st == "signed" and ds:
                doc.signed_date = ds[0][2]
            return
    # строки «Статус» нет: ищем явную фразу в тексте
    for p in doc.paras:
        for s, e in split_sentences(doc.text, p.start, p.end):
            sent = doc.text[s:e]
            if _PARTIAL.search(sent):
                st = "partial"
            elif re.search(r"\bне\s+подписан[оы]?\b", sent, re.I):
                st = "unsigned"
            elif _SIGNED_BOTH.search(sent):
                st = "signed"
            else:
                continue
            doc.status, doc.status_src = st, Src(p.idx, p.clause, s, e, sent)
            if st == "signed":
                ds = find_dates(sent)
                if ds:
                    doc.signed_date = ds[0][2]
            return
    doc.status = "unknown"


# ---------- дата вступления в силу ----------
_EFF_VERB = re.compile(r"вступа(?:ет|ют)\s+в\s+силу|вступит\s+в\s+силу|вступят\s+в\s+силу|вступил[аио]?\s+в\s+силу", re.I)
_AT_SIGNING = re.compile(r"(?:с\s+(?:момента|даты|дня)\s+)?подписани\w+|после\s+подписания", re.I)
_COND = re.compile(r"при\s+условии|в\s+случае|после\s+(?!подписани)\w+|не\s+ранее\s+чем|по\s+факту", re.I)


def parse_effective(doc: Doc):
    cands: List[Tuple[Optional[date], str, Src]] = []
    for p in doc.paras:
        for s, e in split_sentences(doc.text, p.start + p.body_off, p.end):
            sent = doc.text[s:e]
            m = _EFF_VERB.search(sent)
            if not m:
                continue
            src = Src(p.idx, p.clause, s, e, sent)
            ds = find_dates(sent)
            after = [d for (a, b, d) in ds if a >= m.end()]
            before = [d for (a, b, d) in ds if b <= m.start()]
            tail = sent[m.end():]
            if after or before:
                if after and len({*after}) == 1 or (not after and len({*before}) == 1):
                    cands.append(((after or before)[0], "date", src))
                else:
                    cands.append((None, "несколько дат вступления в силу", src))
            elif _COND.search(tail) and not _AT_SIGNING.search(tail):
                cands.append((None, "вступление в силу поставлено в зависимость от условия", src))
            elif _AT_SIGNING.search(tail):
                cands.append((None, "at_signing", src))
    if not cands:
        doc.effective_note = "дата вступления в силу в документе не найдена"
        return
    dated = [c for c in cands if c[0] is not None]
    if dated:
        if len({c[0] for c in dated}) > 1:
            doc.effective_note = "в документе несколько разных дат вступления в силу"
            doc.effective_src = dated[0][2]
            return
        doc.effective_date, doc.effective_src = dated[0][0], dated[0][2]
        return
    note, src = cands[0][1], cands[0][2]
    if note == "at_signing":
        if doc.status == "signed" and doc.signed_date:
            doc.effective_date, doc.effective_src = doc.signed_date, src
            doc.effective_note = "вступает в силу с момента подписания"
        elif doc.status == "signed":
            doc.effective_src = src
            doc.effective_note = "вступает в силу с подписания, но дата подписания не указана"
        else:
            doc.effective_src = src
            doc.effective_note = "вступит в силу после подписания"
    else:
        doc.effective_src, doc.effective_note = src, note


# ---------- стороны, номера, даты документа ----------
_PARTY_STOP = re.compile(r";|\n|\s(?:Покупатель|Поставщик)\s*[:—–-]|,\s*(?:ИНН|ОГРН|КПП|в\s+лице|именуем|далее|адрес)", re.I)


def _party(doc: Doc, word: str) -> Optional[Tuple[str, Src]]:
    rx = re.compile(rf"{word}\s*[:—–-]\s*", re.I)
    for p in doc.paras:
        for s, e in split_sentences(doc.text, p.start + p.body_off, p.end):
            sent = doc.text[s:e]
            m = rx.search(sent)
            if m:
                rest = sent[m.end():]
                stop = _PARTY_STOP.search(rest)
                val = (rest[:stop.start()] if stop else rest).strip().rstrip(",;")
                if not re.search(r"(?:^|[\s.])[А-ЯЁA-Z]\.$", val):  # «Петров И. И.» - точка инициала остаётся
                    val = val.rstrip(".")
                if val:
                    return val, Src(p.idx, p.clause, s, e, sent)
    # «ООО «Х», именуемое в дальнейшем «Поставщик»»
    rx2 = re.compile(rf"((?:ООО|АО|ПАО|ЗАО|ОАО|НАО)\s*«[^»]+»|ИП\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ]\.?\s*[А-ЯЁ]\.?)?)"
                     rf"[^.;«»]{{0,80}}?(?:именуем\w*|далее)[^.;«»]{{0,30}}[«\"]?{word}", re.I)
    for p in doc.paras:
        for s, e in split_sentences(doc.text, p.start + p.body_off, p.end):
            sent = doc.text[s:e]
            m = rx2.search(sent)
            if m:
                return m.group(1).strip(), Src(p.idx, p.clause, s, e, sent)
    return None


def parse_header(doc: Doc):
    title = doc.paras[0] if doc.paras else None
    # дата документа
    for p in doc.paras[:10]:
        m = re.match(r"^\s*(?:дата(?:\s+проекта|\s+документа)?|от)\s*:?\s*(.+)$", p.text, re.I)
        if m:
            ds = find_dates(m.group(1))
            if ds:
                doc.doc_date = ds[0][2]
                break
    if doc.doc_date is None and title:
        ds = find_dates(title.text)
        if ds:
            doc.doc_date = ds[0][2]
    if doc.kind in ("contract", "amendment", "attachment"):
        for p in doc.paras[:4]:
            if p.text and len(p.text) < 250:
                if doc.kind == "contract":
                    refs = find_contract_refs(p.text)
                    if refs:
                        a, b, tok = refs[0]
                        doc.number = tok
                        doc.number_src = Src(p.idx, p.clause, p.start + a, p.start + b, tok)
                        break
                else:
                    m = re.search(r"№\s*([^\s,;]*\d[^\s,;]*)", p.text)
                    if m:
                        doc.number = m.group(1).rstrip(".")
                        doc.number_src = Src(p.idx, p.clause, p.start + m.start(1), p.start + m.end(1), doc.number)
                        break
        if doc.kind == "contract" and doc.number is None:
            for p in doc.paras:
                refs = find_contract_refs(p.text)
                if refs:
                    a, b, tok = refs[0]
                    doc.number, doc.number_src = tok, Src(p.idx, p.clause, p.start + a, p.start + b, tok)
                    break
    if doc.kind == "contract":
        doc.supplier = _party(doc, "Поставщик")
        doc.buyer = _party(doc, "Покупатель")
    if doc.kind == "letter":
        for p in doc.paras[:10]:
            m = re.match(r"^\s*(?:от|from)\s*:\s*(.+)$", p.text, re.I)
            if m:
                doc.sender = m.group(1).strip()
                break
    if doc.kind != "contract":
        seen = {}
        for a, b, tok in find_contract_refs(doc.text):
            seen.setdefault(num_key(tok), tok)
        doc.refs = list(seen.items())


# ---------- извлечение значений полей ----------
_NEG_AMOUNT = re.compile(r"аванс|предоплат|лимит|бюджет|частичн|этап|неустойк|штраф|пени|задаток|остаток|"
                         r"остав\w+\s+(?:част|сумм)|гарантийн|обеспечен", re.I)
_PART_TAIL = re.compile(r"(?:в\s+том\s+числе|из\s+них|ндс)[^.;,]{0,20}$", re.I)
_TOTAL_KW = re.compile(
    r"общ\w+\s+(?:стоимост|сумм|цен)\w*"
    r"|итогов\w+\s+(?:стоимост|сумм|цен)\w*"
    r"|(?:стоимост|сумм|цен)\w*\s+(?:\w+\s+){0,3}?(?:договор|контракт|поставк|товар|оборудован|заказ)\w*"
    r"|на\s+(?:общую\s+)?сумму|цен[аыуе]\s+договор", re.I)
_ABSENT = re.compile(r"не\s+(?:указан|установлен|определен|определён|согласован)\w*"
                     r"|определяется\s+(?:\w+\s+){0,2}?(?:спецификаци|приложени|отдельн)\w*"
                     r"|будет\s+(?:определен|определён|согласован)\w*", re.I)
_CHANGE_VERB = re.compile(r"изложить|изложен\w*|изменить|изменя\w+|измен[её]н[аоы]?\b|увеличи\w+|уменьши\w+|"
                          r"продлить|продлева\w+|продлен\w*|перенести|перенос\w*|заменить|установить|"
                          r"устанавлива\w+|предлага\w+|просим", re.I)
_NEGATED = re.compile(r"\bне\s+\w+", re.I)


def has_change_verb(sent: str) -> bool:
    """«не изменяет срок» - это не изменение, поэтому отрицаемые слова вырезаем."""
    return _CHANGE_VERB.search(_NEGATED.sub(" ", sent)) is not None


_DELTA = re.compile(r"(?:увеличи\w+|уменьши\w+|повыс\w+|сниз\w+|удорож\w+|удешев\w+)[^.]*\sна\s*$", re.I)
_AMEND_CLAUSE = re.compile(r"(?:пункт\w*|п\.)\s*(\d+(?:\.\d+)*)", re.I)

_REASONS = [
    (re.compile(r"аванс|предоплат", re.I), "аванс: часть общей стоимости, а не итоговая сумма"),
    (re.compile(r"лимит|бюджет", re.I), "лимит/бюджет покупателя, не стоимость договора"),
    (re.compile(r"неустойк|штраф|пени", re.I), "неустойка/штраф"),
    (re.compile(r"гарантийн|обеспечен", re.I), "обеспечение/гарантия"),
    (re.compile(r"в\s+том\s+числе|из\s+них|ндс", re.I), "часть суммы (НДС, «в том числе»)"),
    (re.compile(r"оплат|платеж|платёж", re.I), "платёж, а не итоговая стоимость"),
]


def _reason_not_total(sent: str) -> str:
    for rx, text in _REASONS:
        if rx.search(sent):
            return text
    return "не названа общей стоимостью договора"


def extract_amount(sent: str) -> List[Hit]:
    hits: List[Hit] = []
    moneys = find_money(sent)
    kws = list(_TOTAL_KW.finditer(sent))
    for mo in moneys:
        prefix = sent[:mo.start]
        why = None
        if not any(k.end() <= mo.start for k in kws):
            why = _reason_not_total(sent)
        elif _NEG_AMOUNT.search(prefix):
            why = _reason_not_total(prefix)
        elif _PART_TAIL.search(prefix):
            why = "часть суммы (НДС, «в том числе»)"
        if why:
            hits.append(Hit("ignored", mo.value, fmt_money(mo.value) if mo.currency == "RUB" else mo.raw,
                            reason=why))
            continue
        if mo.currency != "RUB":
            hits.append(Hit("value", None, mo.raw, flags=[f"сумма указана не в рублях ({mo.currency})"]))
            continue
        if _DELTA.search(prefix):
            hits.append(Hit("unparsed", reason="изменение суммы на величину («увеличить/уменьшить на ...»): "
                                               "итоговая сумма в тексте не названа"))
            continue
        flags = []
        if mo.mismatch:
            flags.append(f"цифрами {fmt_money(mo.digits)}, прописью {fmt_money(Decimal(mo.words))}: не совпадают")
        h = Hit("value", mo.value, fmt_money(mo.value), flags=flags)
        if mo.mismatch:
            h.alts = [(mo.digits, "цифрами " + fmt_money(mo.digits)), (Decimal(mo.words), "прописью " + fmt_money(Decimal(mo.words)))]
        m = _AMEND_CLAUSE.search(sent)
        h.amends = m.group(1) if m else None
        hits.append(h)
    vals = [h for h in hits if h.kind == "value" and h.value is not None]
    if len(vals) == 2 and re.fullmatch(r"\s*(?:на|до|—|–|-)\s*", sent[moneys[0].end:moneys[1].start]) \
            and re.search(r"(?:\bс|\bсо|\bот)\s*$", sent[:moneys[0].start], re.I):
        hits.remove(vals[0])          # «с 840 000 на 900 000 рублей»: новое значение - второе
        vals[1].old = vals[0].value
    if not moneys:
        if re.search(r"стоимост|сумм\w+|цен[аыуе]", sent, re.I) and _ABSENT.search(sent):
            hits.append(Hit("absent", reason="в тексте прямо сказано, что числового значения нет"))
        elif has_change_verb(sent) and re.search(r"стоимост|цен[аыуе]\b|сумм\w+", sent, re.I) \
                and not re.search(r"неустойк|штраф|пени|просроч", sent, re.I):
            hits.append(Hit("unparsed", reason="изменение стоимости есть, но сумма в рублях не распознана"))
    return hits


_DELIV_STRONG = re.compile(
    r"поставить|поставит\b|поставлен\w*|поставля\w+|"
    r"срок\w*\s+(?:\w+\s+){0,2}?(?:поставк|передач)\w*|дат\w+\s+поставк\w*|"
    r"поставк\w*\s+(?:\w+\s+){0,3}?(?:осуществля|производ|должн|будет|состоит|запланирован)\w*|"
    r"поставк\w*\s*[:—–-]\s*\S|передать|доставить", re.I)
_DATE_GUARD = re.compile(r"оплат|платеж|платёж|аванс|приемк|приёмк|гарант|вступ\w+\s+в\s+силу|"
                         r"состоянию\s+на|действ\w+\s+договор", re.I)
_RELATIVE = re.compile(r"в\s+течение\s+(?:\w+\s+){0,3}?(?:\d+|[а-яё]+)\s*(?:\([^)]*\)\s*)?"
                       r"(?:календарных\s+|рабочих\s+|банковских\s+)?(?:дн\w*|дней|недел\w*|месяц\w*)"
                       r"|через\s+\d+\s+(?:дн\w*|недел\w*)|на\s+\d+\s+(?:календарных\s+|рабочих\s+)?(?:дн\w*|дней|недел\w*)", re.I)


def _guard_reason(pre: str) -> str:
    low = pre.lower()
    if re.search(r"оплат|платеж|платёж|аванс", low):
        return "срок оплаты, а не поставки"
    if re.search(r"приемк|приёмк", low):
        return "дата приёмки, а не поставки"
    if re.search(r"вступ", low):
        return "дата вступления в силу"
    if re.search(r"состоянию\s+на", low):
        return "дата, на которую дано пояснение"
    return "не относится к сроку поставки"


def extract_delivery(sent: str) -> List[Hit]:
    hits: List[Hit] = []
    if not _DELIV_STRONG.search(sent):
        return hits
    ds = find_dates(sent)
    good = []
    for (a, b, d) in ds:
        pre = sent[max(0, a - 40):a]
        if _DATE_GUARD.search(pre):
            hits.append(Hit("ignored", d, fmt_date(d), reason=_guard_reason(pre)))
        else:
            good.append((a, b, d))
    am = _AMEND_CLAUSE.search(sent)
    amends = am.group(1) if am else None
    if good:
        uniq = []
        for g in good:
            if g[2] not in [u[2] for u in uniq]:
                uniq.append(g)
        if len(uniq) == 1:
            h = Hit("value", uniq[0][2], fmt_date(uniq[0][2]), amends=amends)
        elif len(uniq) == 2 and re.fullmatch(r"\s*(?:на|по|до|—|–|-)\s*", sent[uniq[0][1]:uniq[1][0]]) \
                and re.search(r"(?:\bс|\bсо|\bот)\s*$", sent[max(0, uniq[0][0] - 6):uniq[0][0]], re.I):
            h = Hit("value", uniq[1][2], fmt_date(uniq[1][2]), old=uniq[0][2], amends=amends)  # «с X на Y»
        else:
            h = Hit("value", None, "несколько дат", amends=amends,
                    alts=[(u[2], fmt_date(u[2])) for u in uniq],
                    flags=["в одном предложении несколько дат поставки: " + ", ".join(fmt_date(u[2]) for u in uniq)])
        hits.append(h)
        return hits
    if ds:
        return hits
    if re.search(r"срок\w*\s+(?:\w+\s+){0,2}?поставк\w*", sent, re.I) and _ABSENT.search(sent):
        hits.append(Hit("absent", reason="в тексте прямо сказано, что срок не установлен"))
    elif _RELATIVE.search(sent):
        hits.append(Hit("relative", reason="срок задан относительно (в днях), конкретной даты нет"))
    elif has_change_verb(sent):
        hits.append(Hit("unparsed", reason="изменение срока есть, но дата не распознана"))
    return hits


@dataclass
class FieldDef:
    """Описание поля. Всё остальное (цитаты, правило допсоглашений, таблица, API, вопросы)
    работает по этому списку и правок не требует."""
    key: str                              # ключ в JSON: row[key]
    label: str                            # заголовок колонки и подпись в ответах
    extract: Callable[[str], List[Hit]]   # предложение -> найденные значения
    fmt: Callable[[Any], str]             # как показать значение (нужно для «было ...»)
    ask_words: str                        # регулярка: по каким словам в вопросе понять, что спрашивают это поле


# Реестр полей. Новое поле = функция extract_<поле> выше + одна строка здесь.
FIELDS = [
    FieldDef("amount", "Сумма", extract_amount, fmt_money,
             r"сумм|стоимост|цен[аыу]|рубл|сколько|стоит"),
    FieldDef("delivery", "Срок поставки", extract_delivery, fmt_date,
             r"срок|поставк|постав|когда|дата"),
]


def scan_hits(doc: Doc):
    doc.hits = {f.key: [] for f in FIELDS}
    if doc.kind == "unknown":
        return
    for p in doc.paras:
        for s, e in split_sentences(doc.text, p.start + p.body_off, p.end):
            sent = doc.text[s:e]
            for f in FIELDS:
                for h in f.extract(sent):
                    h.field = f.key
                    h.src = Src(p.idx, p.clause, s, e, sent)
                    doc.hits[f.key].append(h)


# ---------- вход ----------
def parse_document(name: str, text: str) -> Doc:
    paras = split_paragraphs(text)
    doc_id = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    doc = Doc(doc_id, name, text, paras)
    if not paras:
        doc.notes.append("файл пустой")
        return doc
    kind, draft, how = detect_kind(paras)
    doc.kind, doc.is_draft = kind, draft
    if kind == "unknown":
        doc.notes.append("тип документа не определён по содержанию")
    elif "заголовок нестандартный" in how:
        doc.notes.append("тип определён по содержанию, заголовок нестандартный: проверьте")
    if kind in ("contract", "amendment"):
        parse_status(doc)
        if draft:
            if doc.status == "signed":
                doc.notes.append("в заголовке «проект», а в статусе «подписано»: противоречие")
                doc.status = "unknown"
            elif doc.status in ("unknown",):
                doc.status = "unsigned"
        if doc.status == "unknown":
            doc.notes.append("статус подписания не распознан")
    elif kind == "letter":
        doc.status = "na"
    parse_header(doc)
    if kind in ("contract", "amendment"):
        parse_effective(doc)
    scan_hits(doc)
    return doc
