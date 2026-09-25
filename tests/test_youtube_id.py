import pytest

from app.utils.youtube_id import extract_video_id

ID = "SwpW4rEzNGM"


@pytest.mark.parametrize("value", [
    ID,
    f"https://www.youtube.com/watch?v={ID}",
    f"https://youtube.com/watch?feature=share&v={ID}&t=42s",
    f"https://m.youtube.com/watch?v={ID}",
    f"https://youtu.be/{ID}?si=abc",
    f"https://www.youtube.com/shorts/{ID}",
    f"https://www.youtube.com/embed/{ID}?start=10",
    f"https://www.youtube-nocookie.com/embed/{ID}",
    f"https://www.youtube.com/live/{ID}",
    f"youtube.com/watch?v={ID}",
    f"https://music.youtube.com/watch?v={ID}",
])
def test_extracts(value):
    assert extract_video_id(value) == ID


@pytest.mark.parametrize("value", [
    "", "hello", "https://vimeo.com/123", "https://www.youtube.com/watch?v=short",
    "https://www.youtube.com/channel/UCxyz", "https://evil.com/watch?v=" + ID,
])
def test_rejects(value):
    assert extract_video_id(value) is None
