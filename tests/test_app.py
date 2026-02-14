import pytest
from app import clean_slack_markdown


def test_clean_slack_markdown():
    # Test bold, italics, strikethrough, and code
    assert clean_slack_markdown("*bold*") == "bold"
    assert clean_slack_markdown("_italic_") == "italic"
    assert clean_slack_markdown("~strike~") == "strike"
    assert clean_slack_markdown("`code`") == "code"
    assert clean_slack_markdown("  *clean me* ") == "clean me"


def test_empty_markdown():
    assert clean_slack_markdown("") == ""
    assert clean_slack_markdown(None) == ""
