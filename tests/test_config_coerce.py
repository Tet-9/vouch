"""Tests for the shared config-boolean coercer (used by compile/session_split/
admission/inbox/recall/capture/volunteer_context/proposals config loaders)."""

from __future__ import annotations

import pytest

from vouch.config_coerce import coerce_bool


class TestCoerceBool:
    def test_real_true_passes_through(self):
        assert coerce_bool(True, False) is True

    def test_real_false_passes_through(self):
        assert coerce_bool(False, True) is False

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "yes", "on", "1"])
    def test_recognized_true_strings(self, value):
        assert coerce_bool(value, False) is True

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "no", "off", "0"])
    def test_recognized_false_strings(self, value):
        """Regression: bool("false") is True in plain Python -- the exact bug
        this module exists to close off for every config loader that uses it."""
        assert coerce_bool(value, True) is False

    def test_whitespace_is_stripped(self):
        assert coerce_bool("  false  ", True) is False
        assert coerce_bool("  true  ", False) is True

    def test_unrecognized_string_falls_back_to_default(self):
        assert coerce_bool("maybe", True) is True
        assert coerce_bool("maybe", False) is False

    def test_non_bool_non_string_falls_back_to_default(self):
        assert coerce_bool(None, True) is True
        assert coerce_bool(1, False) is False  # int, not bool -- not the same type
        assert coerce_bool([], True) is True
        assert coerce_bool({}, False) is False
