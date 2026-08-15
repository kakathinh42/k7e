"""Tests for k7e_api.redaction module.

TDD: these tests are written before the module is implemented.
"""

from k7e_api.redaction import redact


class TestRedactEmail:
    """Test that email addresses are replaced with [REDACTED_EMAIL]."""

    def test_simple_email_replaced(self):
        text = "Contact us at user@example.com for help."
        result, categories = redact(text)
        assert "[REDACTED_EMAIL]" in result
        assert "user@example.com" not in result

    def test_email_category_included(self):
        _, categories = redact("Send to alice@domain.org please.")
        assert "email" in categories

    def test_multiple_emails_all_replaced(self):
        text = "From: a@b.com, To: c@d.net"
        result, categories = redact(text)
        assert "@" not in result.replace("[REDACTED_EMAIL]", "PLACEHOLDER")
        assert "email" in categories

    def test_email_category_once(self):
        """Even with multiple emails, 'email' appears only once in categories."""
        _, categories = redact("a@b.com and x@y.org")
        assert categories.count("email") == 1


class TestRedactCreditCard:
    """Test that credit-card-like numbers are replaced with [REDACTED_CC]."""

    def test_16_digit_number_replaced(self):
        text = "Card: 1234567890123456"
        result, categories = redact(text)
        assert "[REDACTED_CC]" in result
        assert "1234567890123456" not in result

    def test_cc_category_included(self):
        _, categories = redact("Card: 4111111111111111")
        assert "cc" in categories

    def test_13_digit_number_replaced(self):
        """13-digit numbers (Amex-like) should also be redacted."""
        text = "Number: 1234567890123"
        result, categories = redact(text)
        assert "[REDACTED_CC]" in result
        assert "cc" in categories

    def test_cc_category_once(self):
        """Even with multiple CC numbers, 'cc' appears only once in categories."""
        _, categories = redact("4111111111111111 and 5500005555555559")
        assert categories.count("cc") == 1


class TestRedactEmailAndCC:
    """Test combined email and credit card redaction."""

    def test_redacts_email_and_cc(self):
        """Canonical test: email replaced, 16-digit CC replaced, both categories present."""
        text = "User: admin@corp.io, Card: 4111111111111111"
        result, categories = redact(text)

        assert "[REDACTED_EMAIL]" in result
        assert "admin@corp.io" not in result

        assert "[REDACTED_CC]" in result
        assert "4111111111111111" not in result

        assert "email" in categories
        assert "cc" in categories


class TestRedactNoSensitiveData:
    """Test that text without sensitive data is returned unchanged."""

    def test_plain_text_unchanged(self):
        text = "Hello, world! No sensitive data here."
        result, categories = redact(text)
        assert result == text
        assert categories == []

    def test_empty_string(self):
        result, categories = redact("")
        assert result == ""
        assert categories == []

    def test_categories_empty_when_nothing_redacted(self):
        _, categories = redact("Just some ordinary text with numbers 123 456.")
        assert categories == []


class TestRedactReturnType:
    """Test return type contract."""

    def test_returns_tuple(self):
        result = redact("test@email.com")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_first_element_is_str(self):
        text, _ = redact("hello world")
        assert isinstance(text, str)

    def test_second_element_is_list(self):
        _, cats = redact("hello world")
        assert isinstance(cats, list)

    def test_categories_unique(self):
        """Categories list must contain unique values."""
        _, cats = redact("a@b.com x@y.org 4111111111111111 5500005555555559")
        assert len(cats) == len(set(cats))
