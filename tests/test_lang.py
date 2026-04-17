"""Tests for shared.services.lang — script-dominance language detection."""
from shared.services.lang import is_thai


def test_pure_thai_is_thai():
    assert is_thai("สวัสดีครับ") is True
    assert is_thai("ค่าเทอมเท่าไหร่") is True


def test_pure_english_is_not_thai():
    assert is_thai("what is the tuition fee") is False
    assert is_thai("hello, I'd like to know") is False


def test_empty_and_none_are_not_thai():
    assert is_thai("") is False
    assert is_thai("   ") is False


def test_english_with_thai_program_name_is_not_thai():
    """Regression: 'What is the TIP หลักสูตร?' is an English query — the
    user is asking in English, they just referenced the Thai program name.
    Routing them to a Thai error message would be jarring.
    """
    assert is_thai("What is the TIP หลักสูตร?") is False
    assert is_thai("tell me about the หลักสูตร TIP") is False


def test_thai_with_english_acronym_is_thai():
    """Inverse: 'สวัสดีค่ะ TIP คืออะไร' is a Thai query that references an
    English acronym. Must route to Thai fallback.
    """
    assert is_thai("สวัสดีค่ะ TIP คืออะไร") is True
    assert is_thai("ค่าเทอม TIP program เท่าไหร่ครับ") is True


def test_numbers_and_punctuation_are_neutral():
    """Digits, punctuation, and whitespace don't count as either script —
    they tip the ratio toward whichever letters are present.
    """
    assert is_thai("123 456 7890") is False
    assert is_thai("สวัสดี 123") is True
    assert is_thai("hello 123") is False


def test_non_thai_non_latin_defaults_to_english():
    """Chinese/Japanese/Khmer have no Thai chars → default to English
    fallback. We don't have Thai-speaking support for them anyway.
    """
    assert is_thai("你好，学费是多少") is False
    assert is_thai("こんにちは") is False
