from pathlib import Path

import httpx
import pytest

from app.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_settings(**kw) -> Settings:
    base = {"transcriptapi_api_key": "", "transcript_providers_order": "youtube_transcript_ai,transcriptapi"}
    return Settings(_env_file=None, **(base | kw))


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def settings():
    return make_settings()
