import pytest
from app.utils import parse_mentions

def test_parse_mentions_basic():
    """Verify basic mention parsing."""
    text = "Hey @john please review this PR"
    mentions = parse_mentions(text)
    assert mentions == ["john"]

def test_parse_mentions_case_insensitivity():
    """Verify all usernames are returned as lowercase."""
    text = "Hey @John, can you check with @ALICE?"
    mentions = parse_mentions(text)
    assert sorted(mentions) == ["alice", "john"]

def test_parse_mentions_deduplication():
    """Verify duplicate mentions within the same comment are filtered out."""
    text = "Calling @john and @John and @john again."
    mentions = parse_mentions(text)
    assert mentions == ["john"]

def test_parse_mentions_boundaries_and_emails():
    """Verify boundaries are respected and email addresses are not parsed as mentions."""
    text = "Send an email to user@domain.com or talk to @john. Also skip invalid mentions like @ or @.bob."
    mentions = parse_mentions(text)
    assert mentions == ["john"]  # bob is preceded by a dot immediately after @ which is invalid in our regex

def test_parse_mentions_self_mention_filtering():
    """Verify that a user mentioning themselves does not trigger a mention notification."""
    text = "Hey @john, this is @john posting a reminder."
    # Author is john, so john is filtered out of mentions list!
    mentions = parse_mentions(text, author="john")
    assert mentions == []
    
    # If author is alice, then @john is preserved
    mentions_other = parse_mentions(text, author="alice")
    assert mentions_other == ["john"]

def test_parse_mentions_empty_and_null():
    """Verify safe handling of empty or None texts."""
    assert parse_mentions("") == []
    assert parse_mentions(None) == []
