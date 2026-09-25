from app.transcripts.models import TranscriptSegment
from app.transcripts.normalize import fill_ends, parse_clock, split_paragraph, split_sentences


def test_parse_clock():
    assert parse_clock("0:03") == 3
    assert parse_clock("14:30") == 870
    assert parse_clock("1:02:45") == 3765


def test_fill_ends_next_start_and_duration():
    segs = [TranscriptSegment(start=5, end=0, text="b"), TranscriptSegment(start=0, end=0, text="a")]
    out = fill_ends(segs, 12)
    assert [(s.start, s.end) for s in out] == [(0, 5), (5, 12)]


def test_split_sentences_and_long_unpunctuated():
    assert split_sentences("Hi there. How are you? Fine!") == ["Hi there.", "How are you?", "Fine!"]
    parts = split_sentences(" ".join(f"w{i}" for i in range(40)))
    assert len(parts) == 3 and all(len(p.split()) <= 16 for p in parts)
    assert " ".join(parts).split() == [f"w{i}" for i in range(40)]


def test_split_paragraph_proportional():
    segs = split_paragraph(10, 20, "Short. A much much longer sentence here.")
    assert segs[0].start == 10 and abs(segs[-1].end - 20) < 1e-6
    assert all(s.approximate for s in segs)
    assert (segs[1].end - segs[1].start) > (segs[0].end - segs[0].start)
    assert segs[0].end == segs[1].start
