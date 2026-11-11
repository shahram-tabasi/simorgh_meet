"""Persian prompts and JSON schemas for automatic meeting minutes (صورت‌جلسه)."""

from __future__ import annotations

SYSTEM_PROMPT = """\
تو دبیر حرفه‌ای جلسات سازمانی هستی و از روی متن پیاده‌شده‌ی گفتار جلسه، صورت‌جلسه‌ی رسمی به زبان فارسی معیار می‌نویسی.

قواعد الزامی:
1. فقط از اطلاعات موجود در متن جلسه استفاده کن. هیچ تصمیم، عدد، تاریخ، نام یا اقدامی را از خودت نساز. اگر چیزی مبهم است، آن را در «سؤالات باز» بیاور.
2. متن از سامانه‌ی تبدیل گفتار به نوشتار آمده و ممکن است غلط املایی، کلمات اشتباه شنیده‌شده یا جمله‌های ناقص داشته باشد. معنای محتمل را با احتیاط بازسازی کن ولی معنا را تغییر نده.
3. برخی سخنرانان ممکن است با لهجه یا گویش محلی (به‌ویژه کرمانی) صحبت کنند. واژه‌ها، تلفظ‌ها و ساختارهای گویشی را (با کمک واژه‌نامه‌ی سازمان در صورت وجود) به فارسی معیار و رسمی برگردان و لحن صورت‌جلسه را اداری و بی‌طرف نگه دار.
4. نام افراد را دقیقاً مطابق فهرست شرکت‌کنندگان بنویس. مسئول هر اقدام فقط کسی است که در متن مشخص شده یا آشکارا پذیرفته است؛ در غیر این صورت مسئول را خالی بگذار.
5. اقدام (action item) فقط کاری است که باید پس از جلسه انجام شود. هر اقدام با فعل شروع شود، مشخص و قابل پیگیری باشد.
6. مهلت‌ها: اگر مهلت به‌صورت نسبی گفته شده (مثل «تا آخر هفته» یا «شنبه‌ی آینده»)، با توجه به تاریخ جلسه تاریخ میلادی ISO (YYYY-MM-DD) را در due_date و عبارت اصلی را در due_text بنویس؛ اگر مهلتی گفته نشده هر دو را خالی بگذار.
7. تصمیم (decision) فقط چیزی است که در جلسه قطعی شده؛ پیشنهادهای تأییدنشده تصمیم نیستند.
8. خروجی فقط یک شیء JSON مطابق ساختار خواسته‌شده باشد، بدون هیچ توضیح اضافه.
"""

NOTES_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "points": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "points"],
            },
        },
        "decisions": {"type": "array", "items": {"type": "string"}},
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "owner": {"type": "string"},
                    "due_text": {"type": "string"},
                    "source_quote": {"type": "string"},
                },
                "required": ["title", "owner", "due_text", "source_quote"],
            },
        },
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topics", "decisions", "action_items", "open_questions"],
}

MINUTES_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "agenda": {"type": "array", "items": {"type": "string"}},
        "discussion": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "points": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["topic", "points"],
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "owner": {"type": "string"}},
                "required": ["text", "owner"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "owner": {"type": "string"},
                    "due_date": {"type": "string"},
                    "due_text": {"type": "string"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                    "source_quote": {"type": "string"},
                },
                "required": ["title", "owner", "due_date", "due_text", "priority", "source_quote"],
            },
        },
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "next_meeting": {"type": "string"},
    },
    "required": ["title", "summary", "agenda", "discussion", "decisions", "action_items",
                 "open_questions", "next_meeting"],
}


def meeting_header(*, title: str, date_fa: str, date_iso: str, weekday_iso: str, duration_min: int,
                   speakers: list[str], organization: str, glossary: list[str]) -> str:
    lines = [
        f"عنوان ثبت‌شده‌ی جلسه: {title or 'نامشخص'}",
        f"سازمان: {organization}" if organization else "",
        f"تاریخ جلسه: {date_fa} (میلادی: {date_iso}، روز هفته: {weekday_iso})",
        f"مدت تقریبی: {duration_min} دقیقه",
        "شرکت‌کنندگانی که صحبت کرده‌اند: " + ("، ".join(speakers) if speakers else "نامشخص"),
    ]
    if glossary:
        lines.append("واژه‌نامه‌ی سازمان (املای درست نام‌ها و اصطلاحات): " + "، ".join(glossary))
    return "\n".join(line for line in lines if line)


def single_pass_prompt(header: str, transcript: str) -> str:
    return (
        f"{header}\n\n"
        "متن کامل جلسه (هر خط: [زمان] نام سخنران: گفتار):\n"
        f"<<<\n{transcript}\n>>>\n\n"
        "صورت‌جلسه را مطابق ساختار JSON بنویس. «summary» یک پاراگراف ۳ تا ۶ جمله‌ای باشد. "
        "«title» عنوانی کوتاه و گویا برای جلسه باشد. «agenda» محورهای اصلی بحث، "
        "«discussion» خلاصه‌ی نکات هر محور، «next_meeting» زمان جلسه‌ی بعد اگر تعیین شد (وگرنه خالی)."
    )


def chunk_notes_prompt(header: str, transcript_chunk: str, index: int, total: int) -> str:
    return (
        f"{header}\n\n"
        f"این بخش {index} از {total} متن جلسه است:\n<<<\n{transcript_chunk}\n>>>\n\n"
        "از همین بخش، یادداشت‌های ساخت‌یافته استخراج کن: محورهای بحث و نکات کلیدی هر محور، "
        "تصمیم‌های قطعی، اقدامات (با مسئول و مهلت اگر گفته شده و نقل‌قول کوتاه منبع)، و سؤالات باز."
    )


def reduce_prompt(header: str, notes_json: str) -> str:
    return (
        f"{header}\n\n"
        "یادداشت‌های استخراج‌شده از بخش‌های پیاپی جلسه (به ترتیب زمان):\n"
        f"<<<\n{notes_json}\n>>>\n\n"
        "این یادداشت‌ها را ادغام کن و صورت‌جلسه‌ی نهایی را بنویس. موارد تکراری را یکی کن، "
        "اقدامات را بدون تکرار فهرست کن و مسئول/مهلت را حفظ کن. «summary» یک پاراگراف ۳ تا ۶ جمله‌ای باشد."
    )
