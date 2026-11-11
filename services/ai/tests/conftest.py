import json
from datetime import date

import httpx
import numpy as np
import pytest

RATE = 16000


def tone(seconds: float, amp: float = 0.3, freq: float = 220.0) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.standard_normal(int(seconds * RATE)) * 0.0005).astype(np.float32)


FAKE_MINUTES = {
    "title": "جلسه هماهنگی پروژه",
    "summary": "وضعیت پروژه مرور شد و مقرر شد گزارش تا هفته آینده آماده شود.",
    "agenda": ["وضعیت پروژه"],
    "discussion": [{"topic": "وضعیت پروژه", "points": ["پیشرفت هفتاد درصد است"]}],
    "decisions": [{"text": "گزارش نهایی تهیه شود", "owner": "علی"}],
    "action_items": [
        {"title": "تهیه گزارش نهایی", "owner": "علی", "due_date": "2099-01-01", "due_text": "هفته آینده",
         "priority": "high", "source_quote": "من گزارش را آماده می‌کنم"},
        {"title": "اقدام با تاریخ غلط", "owner": "", "due_date": "2000-01-01", "due_text": "",
         "priority": "urgent", "source_quote": ""},
        {"title": "", "owner": "", "due_date": "", "due_text": "", "priority": "low", "source_quote": ""},
    ],
    "open_questions": [],
    "next_meeting": "",
}

FAKE_NOTES = {"topics": [{"title": "بخش", "points": ["نکته"]}], "decisions": [], "action_items": [],
              "open_questions": []}


class FakeLlm:
    """httpx transport emulating llama.cpp's OpenAI-compatible endpoint."""

    def __init__(self):
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        user = body["messages"][1]["content"]
        payload = FAKE_NOTES if "این بخش" in user else FAKE_MINUTES
        content = "<think>x</think>```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def fake_llm():
    return FakeLlm()


@pytest.fixture
def llm_client(fake_llm):
    from simorgh_ai.config import LlmConfig
    from simorgh_ai.minutes.llm import LlmClient

    return LlmClient(LlmConfig(base_url="http://llm/v1"), transport=httpx.MockTransport(fake_llm))


@pytest.fixture
def today() -> date:
    return date(2026, 11, 11)
