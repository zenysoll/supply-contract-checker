"""Связывание документов с договорами и применение правила:
условия меняет только подписанное допсоглашение, вступившее в силу к дате проверки.
Письма и неподписанные проекты показываем отдельно как несогласованные предложения."""
import re
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .extract import FIELDS, Doc, Hit, Src, canon, num_key
from .numbers import find_dates, fmt_date

DEFAULT_AS_OF = date(2026, 3, 10)

KIND_LABEL = {"contract": "Договор", "amendment": "Допсоглашение", "letter": "Письмо",
              "attachment": "Приложение / спецификация", "unknown": "Тип не определён"}
STATUS_LABEL = {"signed": "подписан обеими сторонами", "unsigned": "не подписан", "partial": "подписан одной стороной",
                "unknown": "статус не распознан", "na": "-"}


def field_def(key: str):
    """Описание поля из реестра FIELDS (checker/extract.py)."""
    return next(f for f in FIELDS if f.key == key)


# ---------- сериализация ----------
def jv(v: Any):
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def src_dict(doc: Doc, s: Optional[Src]) -> Optional[dict]:
    if s is None:
        return None
    return {"doc_id": doc.id, "file": doc.name, "para": s.para, "clause": s.clause,
            "start": s.start, "end": s.end, "quote": s.quote}


def where(s: dict) -> str:
    return f"{s['file']}, абзац {s['para']}" + (f" (п. {s['clause']})" if s.get("clause") else "")


# ---------- состояние документа на дату проверки ----------
def doc_state(d: Doc, as_of: date) -> Tuple[str, str, bool]:
    """-> (код состояния, подпись, требует проверки). Код in_force - единственный, который меняет условия."""
    num = f" № {d.number}" if d.number else ""
    if d.kind == "letter":
        return "letter", "Письмо: предложение, не согласовано", False
    if d.kind == "attachment":
        return "attachment", "Приложение/спецификация: значения не разбираются", False
    if d.kind != "amendment":
        return "other", "", False
    word = "Проект допсоглашения" if d.is_draft else "Допсоглашение"
    if d.status == "partial":
        return "partial", f"{word}{num}: подписано одной стороной, не действует", False
    if d.status == "unsigned":
        return "unsigned", f"{word}{num}: не подписано, не действует", False
    if d.status != "signed":
        return "unknown", f"{word}{num}: статус подписания не распознан", True
    if d.signed_date and d.signed_date > as_of:
        return "future", f"Допсоглашение{num} подписано {fmt_date(d.signed_date)}, после даты проверки: не действует", False
    if d.effective_date is None:
        return "no_eff", f"Допсоглашение{num} подписано, но дата вступления в силу неясна: " \
                         f"{d.effective_note or 'не найдена'}", True
    if d.effective_date > as_of:
        return "future", f"Допсоглашение{num} подписано, вступит в силу {fmt_date(d.effective_date)}: " \
                         f"на дату проверки не действует", False
    return "in_force", f"Допсоглашение{num} действует с {fmt_date(d.effective_date)}", False


# ---------- связывание ----------
_TOKEN = re.compile(r"(?<![A-Z0-9А-Я])[A-ZА-Я0-9]+(?:[-/.][A-ZА-Я0-9]+)*(?![A-Z0-9А-Я])")


def link_documents(docs: List[Doc]) -> Dict[str, dict]:
    by_key: Dict[str, List[Doc]] = {}
    for c in docs:
        if c.kind == "contract" and c.number:
            by_key.setdefault(num_key(c.number), []).append(c)
    links: Dict[str, dict] = {}
    for d in docs:
        if d.kind not in ("amendment", "letter", "attachment"):
            continue
        keys = dict(d.refs)
        # номер договора мог быть упомянут без слова «договор»: ищем в тексте токены, похожие на номер
        for tok in _TOKEN.findall(canon(d.text, keep_spaces=True)):
            k = num_key(tok)
            if k in by_key and k not in keys and re.search(r"[A-ZА-Я]", tok) and re.search(r"\d", tok):
                keys[k] = by_key[k][0].number
        if not keys:
            links[d.id] = {"status": "orphan", "contracts": [], "note": "в документе не найден номер договора"}
        elif len(keys) > 1:
            cands = [c for k in keys for c in by_key.get(k, [])]
            links[d.id] = {"status": "ambiguous", "contracts": cands,
                           "note": "документ ссылается на несколько договоров: " + ", ".join(keys.values())}
        else:
            k, shown = next(iter(keys.items()))
            if k in by_key:
                links[d.id] = {"status": "ok", "contracts": by_key[k], "note": f"договор {by_key[k][0].number}"}
            else:
                links[d.id] = {"status": "orphan", "contracts": [],
                               "note": f"ссылается на договор {shown}, которого нет среди загруженных"}
    return links


# ---------- разрешение поля ----------
def _hit_entry(doc: Doc, h: Hit) -> dict:
    return {"value": jv(h.value), "display": h.display, "source": src_dict(doc, h.src), "flags": h.flags}


def resolve_field(key: str, contract: Doc, related: List[Tuple[Doc, str, str, bool, str]]) -> dict:
    """related: (документ, код состояния, подпись, требует проверки, статус связи ok|ambiguous)."""
    res: Dict[str, Any] = {"field": key, "label": field_def(key).label, "status": "no_data", "value": None,
                           "display": "нет данных", "source": None, "base": None, "changed_by": None,
                           "notes": [], "alternatives": [], "ignored": [], "proposals": []}
    bh = contract.hits.get(key, [])
    base_vals = [h for h in bh if h.kind == "value"]
    distinct = {h.value for h in base_vals if h.value is not None}
    base_conflict = any(h.value is None for h in base_vals) or len(distinct) > 1
    base_hit = None if not base_vals or base_conflict else base_vals[0]
    for h in bh:
        if h.kind == "ignored":
            res["ignored"].append({"display": h.display, "reason": h.reason, "source": src_dict(contract, h.src)})
    if base_hit:
        res["base"] = _hit_entry(contract, base_hit)
    review_notes: List[str] = []
    if base_conflict:
        res["alternatives"] += [{"display": h.display if h.value is not None else (h.flags[0] if h.flags else h.display),
                                 "source": src_dict(contract, h.src)} for h in base_vals]
        review_notes.append("в договоре несколько разных значений или значение нельзя прочитать однозначно")

    # изменения от действующих допсоглашений
    changes: List[Tuple[Doc, Hit]] = []
    unparsed: List[Tuple[Doc, Hit]] = []
    for d, st, label, rv, lk in related:
        if st != "in_force" or lk != "ok":
            continue
        for h in d.hits.get(key, []):
            if h.kind == "value":
                changes.append((d, h))
            elif h.kind in ("unparsed", "relative"):
                unparsed.append((d, h))
    winner: Optional[Tuple[Doc, Hit]] = None
    amend_conflict = False
    if changes:
        order = lambda dh: (dh[0].effective_date, dh[0].signed_date or date.min)
        changes.sort(key=order)
        top = [dh for dh in changes if order(dh) == order(changes[-1])]
        tvals = {dh[1].value for dh in top}
        if len(tvals) > 1 or None in tvals:
            amend_conflict = True
            res["alternatives"] += [{"display": h.display, "source": src_dict(d, h.src)} for d, h in top]
            review_notes.append("действующие допсоглашения с одной датой вступления в силу дают разные значения")
        else:
            winner = top[-1]
    for d, h in unparsed:
        review_notes.append(f"{d.name}: {h.reason}")
        res["alternatives"].append({"display": "не разобрано", "source": src_dict(d, h.src)})

    if unparsed or amend_conflict or base_conflict:
        res["status"], res["display"] = "review", "нужна проверка"
    elif winner:
        d, h = winner
        res.update(status="changed", value=jv(h.value), display=h.display, source=src_dict(d, h.src),
                   changed_by={"doc_id": d.id, "file": d.name, "number": d.number,
                               "effective": jv(d.effective_date), "signed": jv(d.signed_date)})
        if h.flags:
            res["status"] = "review"
            review_notes += h.flags
            res["alternatives"] += [{"display": a[1], "source": src_dict(d, h.src)} for a in h.alts]
    elif base_hit:
        res.update(status="ok", value=jv(base_hit.value), display=base_hit.display,
                   source=src_dict(contract, base_hit.src))
        if base_hit.flags:
            res["status"] = "review"
            review_notes += base_hit.flags
            res["alternatives"] += [{"display": a[1], "source": src_dict(contract, base_hit.src)} for a in base_hit.alts]
    else:
        ev = [h for h in bh if h.kind == "absent"]
        ev.sort(key=lambda h: 0 if re.search(r"не\s+(?:указан|установлен|определ)", h.src.quote, re.I) else 1)
        rel = [h for h in bh if h.kind == "relative"]
        if rel:
            res["status"], res["display"] = "review", "нужна проверка"
            res["source"] = src_dict(contract, rel[0].src)
            review_notes.append(rel[0].reason)
        elif ev:
            res["source"] = src_dict(contract, ev[0].src)
            res["notes"].append(ev[0].reason + " (см. цитату); значение не придумываем")
        else:
            res["notes"].append("в загруженных документах значение не найдено")
    if winner and res["base"] is None and res["status"] in ("changed", "review"):
        res["notes"].append("в самом договоре значения не было, его задаёт допсоглашение")
    res["notes"] += review_notes

    # несогласованные предложения и документы, которые пока не действуют
    for d, st, label, rv, lk in related:
        if st == "in_force" and lk == "ok":
            continue
        for h in d.hits.get(key, []):
            if h.kind in ("value", "unparsed", "relative"):
                res["proposals"].append({
                    "doc_id": d.id, "file": d.name, "state": st if lk == "ok" else "ambiguous",
                    "label": label if lk == "ok" else f"{KIND_LABEL[d.kind]}: связь с договором неоднозначна",
                    "value": jv(h.value) if h.kind == "value" else None,
                    "display": h.display if h.kind == "value" else "не разобрано",
                    "old": jv(h.old), "old_display": field_def(key).fmt(h.old) if h.old is not None else "",
                    "old_mismatch": h.old is not None and res["value"] is not None and jv(h.old) != res["value"],
                    "reason": h.reason if h.kind != "value" else "",
                    "source": src_dict(d, h.src), "flags": h.flags,
                    "review": rv or lk != "ok" or h.kind != "value"})
    return res


# ---------- сборка ----------
def analyze(docs: List[Doc], as_of: date = DEFAULT_AS_OF) -> dict:
    links = link_documents(docs)
    contracts = [d for d in docs if d.kind == "contract"]
    count_by_key: Dict[str, int] = {}
    for c in contracts:
        if c.number:
            count_by_key[num_key(c.number)] = count_by_key.get(num_key(c.number), 0) + 1
    linked_to: Dict[int, list] = {}
    for d in docs:
        lk = links.get(d.id)
        if lk and lk["status"] in ("ok", "ambiguous"):
            st, label, rv = doc_state(d, as_of)
            for c in lk["contracts"]:
                linked_to.setdefault(id(c), []).append((d, st, label, rv, lk["status"]))
    rows = []
    for c in contracts:
        related = linked_to.get(id(c), [])
        flags: List[str] = []
        if c.number and count_by_key[num_key(c.number)] > 1:
            flags.append("среди загруженных несколько договоров с таким номером")
        if c.number is None:
            flags.append("в договоре не найден номер")
        if c.status != "signed":
            flags.append(f"договор: {STATUS_LABEL.get(c.status, c.status)}")
        if (c.signed_date or c.doc_date) and (c.signed_date or c.doc_date) > as_of:
            flags.append(f"на дату проверки договор ещё не был подписан ({fmt_date(c.signed_date or c.doc_date)})")
        if c.effective_date and c.effective_date > as_of:
            flags.append(f"договор вступает в силу {fmt_date(c.effective_date)}, после даты проверки")
        for d, st, label, rv, lk in related:
            if lk == "ambiguous":
                flags.append(f"{d.name}: {links[d.id]['note']}; не применяю, нужна проверка")
            elif rv:
                flags.append(f"{d.name}: {label}")
            elif st == "attachment":
                flags.append(f"{d.name}: загружено приложение/спецификация, оно не разбирается; проверьте сумму вручную")
        for n in c.notes:
            flags.append(f"{c.name}: {n}")
        fields = {f.key: resolve_field(f.key, c, related) for f in FIELDS}
        for k in fields:
            for p in fields[k]["proposals"]:
                if p["old_mismatch"]:
                    flags.append(f"{p['file']}: предложение отсчитывается от прежнего значения {p['old_display']}, "
                                 f"а по документам действует {fields[k]['display']}")
        for f in FIELDS:
            if fields[f.key]["status"] == "review":
                flags.append(f"{f.label}: нужна проверка")
        row = {
            "id": c.id, "file": c.name, "number": c.number or "нет данных",
            "number_source": src_dict(c, c.number_src),
            "supplier": ({"value": c.supplier[0], "source": src_dict(c, c.supplier[1])} if c.supplier
                         else {"value": "нет данных", "source": None}),
            "buyer": c.buyer[0] if c.buyer else None,
            "proposals": [dict(p, field=k) for k in fields for p in fields[k]["proposals"]],
            "related": [{"doc_id": d.id, "file": d.name, "kind": d.kind, "state": st, "label": label}
                        for d, st, label, rv, lk in related],
            "flags": flags, "need_review": bool(flags)}
        row.update(fields)  # row["amount"], row["delivery"] и любое новое поле из FIELDS
        rows.append(row)
    documents = []
    for d in docs:
        lk = links.get(d.id)
        st, label, rv = doc_state(d, as_of)
        notes = list(d.notes)
        if lk and lk["status"] != "ok":
            notes.append(lk["note"])
        documents.append({
            "id": d.id, "name": d.name, "kind": d.kind, "kind_label": KIND_LABEL[d.kind] + (" (проект)" if d.is_draft and d.kind != "contract" else ""),
            "status": d.status, "status_label": STATUS_LABEL.get(d.status, d.status),
            "status_source": src_dict(d, d.status_src),
            "number": d.number, "doc_date": jv(d.doc_date), "signed_date": jv(d.signed_date),
            "effective": jv(d.effective_date), "effective_note": d.effective_note if d.kind == "amendment" else "",
            "effective_source": src_dict(d, d.effective_src),
            "state": st, "state_label": label,
            "linked": (lk["note"] if lk and lk["status"] == "ok" else None),
            "link_status": lk["status"] if lk else None,
            "notes": notes, "needs_attention": bool(notes) or rv})
    return {"as_of": as_of.isoformat(), "fields": [{"key": f.key, "label": f.label} for f in FIELDS],
            "contracts": rows, "documents": documents}


# ---------- вопрос 4: поставки раньше даты ----------
def _props_title(ps: list) -> str:
    """Подписанное, но ещё не вступившее допсоглашение - не «несогласованное»: называем честно."""
    if any(p["state"] in ("future", "no_eff", "unknown", "ambiguous") for p in ps):
        return "Несогласованные или ещё не действующие изменения"
    return "Несогласованные изменения"


def _prop_line(p: dict) -> str:
    what = p["display"] if p["value"] is not None else "значение не разобрано"
    return f"{p['label']} ({p['file']}): срок поставки - {what}"


def early_delivery(res: dict, before: date) -> dict:
    def prop_line(p: dict) -> str:
        line = _prop_line(p)
        if p["value"] is not None and date.fromisoformat(p["value"]) < before:
            line += f" (это тоже раньше {fmt_date(before)})"
        return line

    matches, maybe, others = [], [], []
    for r in res["contracts"]:
        dl = r["delivery"]
        props = [p for p in r["proposals"] if p["field"] == "delivery"]
        entry = {"number": r["number"], "id": r["id"], "display": dl["display"], "status": dl["status"],
                 "source": dl["source"], "unagreed": props, "need_review": r["need_review"]}
        if dl["value"] is not None and date.fromisoformat(dl["value"]) < before:
            matches.append(entry)
        elif dl["value"] is None and dl["status"] == "review":
            maybe.append(entry)
        elif props:
            others.append(entry)
        # договоры без данных и без предложений в ответ не попадают
    # предложения, которые сдвигают срок раньше порога, хотя действующий срок позже
    earlier_prop = []
    for r in res["contracts"]:
        dl = r["delivery"]
        if dl["value"] is not None and date.fromisoformat(dl["value"]) < before:
            continue
        for p in r["proposals"]:
            if p["field"] == "delivery" and p["value"] is not None and date.fromisoformat(p["value"]) < before:
                earlier_prop.append((r["number"], p))
    b = fmt_date(before)
    lines = []
    if matches:
        lines.append(f"Поставка запланирована раньше {b} по договорам: " + "; ".join(
            f"{m['number']} ({m['display']})" for m in matches) + ".")
    else:
        lines.append(f"Среди загруженных договоров нет таких, где действующий срок поставки раньше {b}.")
    for m in maybe:
        lines.append(f"{m['number']}: срок определить не удалось, нужна проверка.")
    unag = [(m["number"], p) for m in matches for p in m["unagreed"]]
    if unag:
        lines.append(_props_title([p for _, p in unag]) + " срока по этим договорам: " + "; ".join(
            f"{n}: {prop_line(p)}" for n, p in unag) + ".")
    elif matches:
        lines.append("Несогласованных изменений срока по этим договорам нет.")
    oth = [(m["number"], p) for m in others for p in m["unagreed"]]
    if oth:
        lines.append("По остальным договорам тоже есть " + _props_title([p for _, p in oth]).lower() + " срока: " + "; ".join(
            f"{n}: {prop_line(p)}" for n, p in oth) + ".")
    for n, p in earlier_prop:
        lines.append(f"Внимание: по договору {n} действующий срок позже {b}, но {p['label']} предлагает {p['display']}.")
    sources = [m["source"] for m in matches if m["source"]] + [p["source"] for _, p in unag + oth if p["source"]]
    return {"intent": "early", "before": before.isoformat(), "as_of": res["as_of"],
            "matches": matches, "maybe": maybe, "others_with_unagreed": others,
            "answer": " ".join(lines), "sources": sources}


# ---------- вопросы свободным текстом ----------
def _find_contracts_in_query(q: str, res: dict) -> List[dict]:
    cq = canon(q, keep_spaces=True)
    found = []
    for r in res["contracts"]:
        if r["number"] == "нет данных":
            continue
        n = canon(r["number"])
        if re.search(r"[A-ZА-Я]", n):
            ok = re.search(rf"(?<![A-Z0-9А-Я]){re.escape(n)}(?![A-Z0-9А-Я])", cq)
        else:
            ok = re.search(rf"(?:ДОГОВОР\w*|КОНТРАКТ\w*)\s*(?:№|N|NO)?\s*{re.escape(n)}(?![0-9])", cq)
        if ok:
            found.append(r)
    return found


def parse_query_dates(q: str) -> dict:
    out = {"before": None, "as_of": None}
    low = q.lower()
    for a, b, d in find_dates(q):
        pre = low[max(0, a - 30):a]
        if re.search(r"(?:раньше|ранее|до|перед|прежде)\s*(?:чем\s*)?[«\"]?\s*$", pre):
            out["before"] = d
        elif re.search(r"(?:на|состоянию\s+на|к)\s*[«\"]?\s*$", pre):
            out["as_of"] = d
        elif re.search(r"раньше|ранее", low):
            out["before"] = d
        else:
            out["as_of"] = out["as_of"] or d
    return out


def answer_field(row: dict, key: str, as_of_iso: str) -> dict:
    f = row[key]
    n = row["number"]
    asd = fmt_date(date.fromisoformat(as_of_iso))
    label = f"{field_def(key).label} по договору {n}"
    srcs = []
    if f["status"] in ("ok", "changed"):
        txt = f"{label} на {asd}: {f['display']}. Основание: {where(f['source'])}."
        srcs.append(f["source"])
        if f["status"] == "changed":
            ch, b = f["changed_by"], f["base"]
            txt += (f" Значение изменено допсоглашением{' № ' + ch['number'] if ch['number'] else ''} "
                    f"({ch['file']}), вступило в силу {fmt_date(date.fromisoformat(ch['effective']))}.")
            if b:
                txt += f" В исходном договоре было {b['display']} ({where(b['source'])})."
                srcs.append(b["source"])
        if f["notes"]:
            txt += " Внимание: " + "; ".join(f["notes"]) + "."
    elif f["status"] == "no_data":
        txt = f"{label}: нет данных."
        if f["notes"]:
            txt += " " + "; ".join(f["notes"]).capitalize() + "."
        if f["source"]:
            txt += f" Что сказано в договоре: «{f['source']['quote']}» ({where(f['source'])})."
            srcs.append(f["source"])
        if f["ignored"]:
            txt += " Найденные суммы не приняты за стоимость договора: " + "; ".join(
                f"{i['display']} - {i['reason']} ({where(i['source'])})" for i in f["ignored"]) + "."
    else:
        txt = f"{label}: нужна проверка. " + "; ".join(f["notes"]) + "."
        if f["display"] not in ("нужна проверка", "нет данных"):
            txt += f" Предварительное значение: {f['display']}."
        srcs += [a["source"] for a in f["alternatives"] if a.get("source")]
        if f["source"]:
            srcs.append(f["source"])
    props = [p for p in row["proposals"] if p["field"] == key]
    if props:
        txt += " " + _props_title(props) + ": " + "; ".join(_prop_line(p) for p in props) + "."
        srcs += [p["source"] for p in props if p["source"]]
    else:
        txt += " Несогласованных изменений нет."
    return {"text": txt, "sources": [s for s in srcs if s]}


def ask(res: dict, q: str) -> dict:
    """res - результат analyze() на нужную дату (дату из вопроса подставляет вызывающий, см. answer_question)."""
    qd = parse_query_dates(q)
    low = q.lower()
    if qd["before"]:
        return early_delivery(res, qd["before"])
    found = _find_contracts_in_query(q, res)
    if not found:
        return {"intent": "unknown", "as_of": res["as_of"], "sources": [],
                "answer": "Не нашёл в вопросе номер загруженного договора или дату. Укажите, например, "
                          "«срок поставки по договору <номер>» или «поставка раньше <дата>»."}
    keys = [f.key for f in FIELDS if re.search(f.ask_words, low)] or [f.key for f in FIELDS]
    parts, srcs = [], []
    for r in found:
        for k in keys:
            a = answer_field(r, k, res["as_of"])
            parts.append(a["text"])
            srcs += a["sources"]
    return {"intent": "field", "as_of": res["as_of"], "answer": "\n".join(parts), "sources": srcs}


def answer_question(docs: List[Doc], q: str, ui_as_of: date) -> dict:
    """Дата «на ...» в тексте вопроса важнее даты в интерфейсе."""
    as_of = parse_query_dates(q)["as_of"] or ui_as_of
    return ask(analyze(docs, as_of), q)
