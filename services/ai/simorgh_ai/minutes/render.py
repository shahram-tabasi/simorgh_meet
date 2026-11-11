"""Render minutes JSON as Persian Markdown (RTL-friendly) for archive and download."""

from __future__ import annotations

from ..jalali import PERSIAN_DIGITS, format_jalali

PRIORITY_FA = {"high": "بالا", "normal": "عادی", "low": "پایین"}


def _fa_date(iso: str) -> str:
    if not iso:
        return "—"
    from datetime import date

    try:
        return format_jalali(date.fromisoformat(iso), with_weekday=False)
    except ValueError:
        return iso


def render_markdown(minutes: dict, room_name: str = "") -> str:
    out: list[str] = [f"# {minutes.get('title') or 'صورت‌جلسه'}", ""]
    meta = [f"**تاریخ:** {minutes.get('meeting_date_fa', '')}"]
    if room_name:
        meta.append(f"**اتاق:** {room_name}")
    out.append(" | ".join(meta))
    if minutes.get("attendees"):
        out.append(f"**حاضران (سخنرانان):** {'، '.join(minutes['attendees'])}")
    if minutes.get("absentees"):
        out.append(f"**غایبان:** {'، '.join(minutes['absentees'])}")
    out.append("")
    if minutes.get("ai_generated"):
        out += ["> این صورت‌جلسه به‌صورت خودکار با هوش مصنوعی تولید شده و پیش از تأیید باید بازبینی شود.", ""]

    if minutes.get("summary"):
        out += ["## خلاصه", "", minutes["summary"], ""]
    if minutes.get("agenda"):
        out += ["## دستور جلسه", ""] + [f"{str(i).translate(PERSIAN_DIGITS)}. {a}"
                                         for i, a in enumerate(minutes["agenda"], 1)] + [""]
    if minutes.get("discussion"):
        out += ["## شرح مذاکرات", ""]
        for d in minutes["discussion"]:
            out += [f"### {d['topic']}", ""] + [f"- {p}" for p in d.get("points", [])] + [""]
    if minutes.get("decisions"):
        out += ["## مصوبات", ""]
        for i, d in enumerate(minutes["decisions"], 1):
            owner = f" (مسئول: {d['owner']})" if d.get("owner") else ""
            out.append(f"{str(i).translate(PERSIAN_DIGITS)}. {d['text']}{owner}")
        out.append("")
    if minutes.get("action_items"):
        out += ["## اقدامات و پیگیری‌ها", "", "| ردیف | اقدام | مسئول | مهلت | اولویت |", "|---|---|---|---|---|"]
        for i, a in enumerate(minutes["action_items"], 1):
            due = _fa_date(a.get("due_date", "")) if a.get("due_date") else (a.get("due_text") or "—")
            out.append(f"| {str(i).translate(PERSIAN_DIGITS)} | {a['title']} | {a.get('owner') or '—'} | "
                       f"{due} | {PRIORITY_FA.get(a.get('priority', 'normal'), 'عادی')} |")
        out.append("")
    if minutes.get("open_questions"):
        out += ["## موارد باز / نیازمند پیگیری", ""] + [f"- {q}" for q in minutes["open_questions"]] + [""]
    if minutes.get("next_meeting"):
        out += ["## جلسه‌ی بعد", "", minutes["next_meeting"], ""]
    return "\n".join(out).rstrip() + "\n"
