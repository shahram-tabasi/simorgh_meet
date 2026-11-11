"""Lightweight Persian text normalization for STT output and LLM input."""

from __future__ import annotations

import re

_CHAR_MAP = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ۀ": "هٔ",
        "ة": "ه",
        "٠": "۰", "١": "۱", "٢": "۲", "٣": "۳", "٤": "۴",
        "٥": "۵", "٦": "۶", "٧": "۷", "٨": "۸", "٩": "۹",
        "‏": "",
        "‎": "",
        "﻿": "",
    }
)

_DIACRITICS = re.compile("[ً-ْٰ]")
_SPACES = re.compile(r"[ \t ]+")
_ZWNJ_RUNS = re.compile("‌{2,}")
# "می " / "نمی " prefix glued with ZWNJ: "می روم" -> "می‌روم"
_MI_PREFIX = re.compile(r"(^|\s)(ن?می)\s+(?=[؀-ۿ])")
# plural / suffix joins: "کتاب ها" -> "کتاب‌ها"
_SUFFIX = re.compile(r"(?<=[؀-ۿ])\s+(ها|های|هایی|ترین)(?=\s|$|[.,،؛!?؟])")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,،؛!?؟:])")
_REPEAT_PUNCT = re.compile(r"([.!?؟،])\1{2,}")


def normalize_persian(text: str) -> str:
    if not text:
        return ""
    text = text.translate(_CHAR_MAP)
    text = _DIACRITICS.sub("", text)
    text = _SPACES.sub(" ", text)
    text = _MI_PREFIX.sub(lambda m: f"{m.group(1)}{m.group(2)}‌", text)
    text = _SUFFIX.sub(lambda m: f"‌{m.group(1)}", text)
    text = _ZWNJ_RUNS.sub("‌", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _REPEAT_PUNCT.sub(r"\1", text)
    return text.strip()


def word_count(text: str) -> int:
    return len([w for w in re.split(r"[\s‌]+", text) if w])
