"""Tests for the plain-Python part of voice_wake.py (no ROS, no microphone)."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "voice_wake", Path(__file__).with_name("voice_wake.py"))
vw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vw)


def test_normalize_splits_digits_and_punctuation():
    assert vw.normalize("Go2, come HERE!") == ["go", "2", "come", "here"]


def test_name_in_sentence_returns_rest():
    m = vw.WakeMatcher(["momo"])
    assert m.find("hey momo come here") == ("momo", "come here")


def test_name_only():
    m = vw.WakeMatcher(["momo"])
    assert m.find("momo") == ("momo", "")


def test_no_name():
    m = vw.WakeMatcher(["momo"])
    assert m.find("please walk to the lift") is None


def test_close_misheard_word_matches():
    m = vw.WakeMatcher(["momo"], threshold=0.7)   # "momu" vs "momo" = 0.75 similar
    assert m.find("hey momu stop") is not None


def test_unrelated_word_does_not_match():
    m = vw.WakeMatcher(["momo"], threshold=0.8)
    assert m.find("the mobile phone") is None


@pytest.mark.parametrize("heard", ["go two", "go to", "go too", "go 2", "go2"])
def test_go_two_variants(heard):
    m = vw.WakeMatcher(["go two"])
    assert m.find(heard) is not None


def test_multiword_name_needs_consecutive_words():
    m = vw.WakeMatcher(["go two"])
    assert m.find("go home and then two") is None


def test_alias():
    m = vw.WakeMatcher(["go two", "momo"])
    assert m.find("momo sit") == ("momo", "sit")


def test_cooldown_blocks_second_trigger():
    m = vw.WakeMatcher(["momo"], cooldown=2.0)
    assert m.check("momo", now=100.0) == ""
    assert m.check("momo", now=101.0) is None   # inside cooldown
    assert m.check("momo", now=103.0) == ""     # after cooldown


def test_empty_names_rejected():
    with pytest.raises(ValueError):
        vw.WakeMatcher([])


def test_handle_publishes_transcript_and_wake():
    m = vw.WakeMatcher(["momo"])
    texts, wakes = [], []
    vw.handle("momo come here", m, texts.append, wakes.append)
    vw.handle("nothing to see", m, texts.append, wakes.append)
    assert texts == ["momo come here", "nothing to see"]
    assert wakes == ["come here"]
