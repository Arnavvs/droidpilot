"""Read hooks and composer detection.

    python -m pytest tests/test_reads.py
"""

from __future__ import annotations

from droidpilot.policy import reads
from droidpilot.ui import Element


def field(text="", rid="", cls="android.widget.EditText"):
    return Element(i=0, rid=rid, anchor=rid, text=text, desc="", cls=cls,
                   bounds=(0, 0, 100, 40), clickable=True)


def test_default_hooks_allow_and_record_without_a_limiter():
    d = reads.acquire("profile_open", "ex", target="x", n=3)
    assert d.allowed and not d.counted
    assert reads.unit(d) and d.recorded == 1
    reads.commit(d, n=2)
    assert d.recorded == 3
    assert reads.bucketed("scroll", "ex") is None


def test_a_refusal_carries_the_decision():
    d = reads.ReadDecision(False, "search", "ex", why="ceiling reached")
    r = reads.refusal(d, opened=False)
    assert r["read"]["allowed"] is False and r["read"]["why"] == "ceiling reached"
    assert r["opened"] is False


def test_a_refused_batch_stops_its_loop():
    d = reads.ReadDecision(False, "search", "ex")
    assert reads.unit(d) is False


def test_comment_and_message_boxes_are_composers():
    for hint in ("Add a comment...", "Add a comment for someone…", "Message…",
                 "Reply to Sam", "Write a message"):
        assert reads.composer_on_screen([field(hint)], "any.pkg"), hint


def test_other_text_fields_are_not_composers():
    assert reads.composer_on_screen([field("Search")], "any.pkg") is None
    assert reads.composer_on_screen([field("Add a comment", cls="TextView")], "p") is None


def test_autocomplete_fields_count_as_editable():
    box = field("Add a comment", cls="android.widget.AutoCompleteTextView")
    assert reads.composer_on_screen([box], "any.pkg")
