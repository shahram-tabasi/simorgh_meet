"""Transcript -> structured minutes (map-reduce for long meetings)."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..config import LlmConfig
from ..jalali import format_jalali
from . import prompts
from .llm import LlmClient
from .transcript import Transcript

log = logging.getLogger(__name__)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class MinutesResult:
    content: dict
    model: str
    meta: dict


def chunk_lines(lines: list[str], max_chars: int) -> list[str]:
    chunks, current, size = [], [], 0
    for line in lines:
        if len(line) > max_chars:  # extremely long monologue: hard split
            for i in range(0, len(line), max_chars):
                piece = line[i : i + max_chars]
                if current:
                    chunks.append("\n".join(current))
                    current, size = [], 0
                chunks.append(piece)
            continue
        if size + len(line) + 1 > max_chars and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


class MinutesGenerator:
    def __init__(self, llm: LlmClient, cfg: LlmConfig, organization: str = "", tz: str = "Asia/Tehran"):
        self.llm = llm
        self.cfg = cfg
        self.organization = organization
        self.tz = ZoneInfo(tz)

    def generate(self, transcript: Transcript, title: str = "", glossary: list[str] | None = None) -> MinutesResult:
        started = time.monotonic()
        local_start = transcript.started_at.astimezone(self.tz)
        ended = transcript.ended_at or (
            datetime.fromtimestamp(transcript.utterances[-1].end_ms / 1000, tz=self.tz)
            if transcript.utterances else transcript.started_at)
        duration_min = max(1, int((ended - transcript.started_at).total_seconds() // 60))
        header = prompts.meeting_header(
            title=title,
            date_fa=format_jalali(local_start.date()),
            date_iso=local_start.date().isoformat(),
            weekday_iso=local_start.strftime("%A"),
            duration_min=duration_min,
            speakers=transcript.speakers,
            organization=self.organization,
            glossary=glossary or [],
        )
        chunks = chunk_lines(transcript.to_lines(), self.cfg.chunk_chars)
        if len(chunks) <= 1:
            content = self.llm.chat_json(prompts.SYSTEM_PROMPT,
                                         prompts.single_pass_prompt(header, chunks[0] if chunks else ""),
                                         prompts.MINUTES_SCHEMA)
            strategy = "single"
        else:
            notes = []
            for i, chunk in enumerate(chunks, start=1):
                log.info("minutes map step %d/%d", i, len(chunks))
                notes.append(self.llm.chat_json(prompts.SYSTEM_PROMPT,
                                                prompts.chunk_notes_prompt(header, chunk, i, len(chunks)),
                                                prompts.NOTES_SCHEMA, max_tokens=1500))
            content = self.llm.chat_json(prompts.SYSTEM_PROMPT,
                                         prompts.reduce_prompt(header, json.dumps(notes, ensure_ascii=False)),
                                         prompts.MINUTES_SCHEMA)
            strategy = f"map-reduce/{len(chunks)}"

        content = sanitize_minutes(content, transcript, local_start.date())
        meta = {
            "strategy": strategy,
            "elapsed_s": round(time.monotonic() - started, 1),
            "transcript_words": transcript.word_count(),
            "stt_engine": transcript.engine,
            "stt_model": transcript.model,
        }
        return MinutesResult(content=content, model=self.cfg.model, meta=meta)


def _str(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _str_list(value) -> list[str]:
    return [s for s in (_str(v) for v in (value or [])) if s] if isinstance(value, list) else []


def sanitize_minutes(raw: dict, transcript: Transcript, meeting_date: date) -> dict:
    """Coerce LLM output into the stored schema (version 1) and add facts we know."""
    speakers = transcript.speakers

    def match_owner(owner: str) -> str:
        owner = _str(owner)
        if not owner:
            return ""
        for name in speakers:  # snap to the real participant spelling when it is a clear match
            if owner == name or owner in name or name in owner:
                return name
        return owner

    actions = []
    for item in raw.get("action_items") or []:
        if not isinstance(item, dict) or not _str(item.get("title")):
            continue
        due = _str(item.get("due_date"))
        if not _ISO_DATE.match(due):
            due = ""
        elif due < meeting_date.isoformat():
            due = ""  # a deadline before the meeting is a model error
        priority = _str(item.get("priority")) or "normal"
        actions.append({
            "title": _str(item.get("title")),
            "owner": match_owner(item.get("owner")),
            "due_date": due,
            "due_text": _str(item.get("due_text")),
            "priority": priority if priority in {"low", "normal", "high"} else "normal",
            "source_quote": _str(item.get("source_quote"))[:500],
        })

    decisions = []
    for d in raw.get("decisions") or []:
        if isinstance(d, dict) and _str(d.get("text")):
            decisions.append({"text": _str(d.get("text")), "owner": match_owner(d.get("owner"))})
        elif isinstance(d, str) and d.strip():
            decisions.append({"text": d.strip(), "owner": ""})

    discussion = []
    for d in raw.get("discussion") or []:
        if isinstance(d, dict) and _str(d.get("topic")):
            discussion.append({"topic": _str(d.get("topic")), "points": _str_list(d.get("points"))})

    return {
        "schema_version": 1,
        "title": _str(raw.get("title")) or "صورت‌جلسه",
        "summary": _str(raw.get("summary")),
        "agenda": _str_list(raw.get("agenda")),
        "discussion": discussion,
        "decisions": decisions,
        "action_items": actions,
        "open_questions": _str_list(raw.get("open_questions")),
        "next_meeting": _str(raw.get("next_meeting")),
        "attendees": speakers,
        "meeting_date": meeting_date.isoformat(),
        "meeting_date_fa": format_jalali(meeting_date),
        "ai_generated": True,
        "review_required": True,
    }
