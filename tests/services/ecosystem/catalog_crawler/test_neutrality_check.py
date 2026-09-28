# SPDX-License-Identifier: MIT
from __future__ import annotations

from services.ecosystem.catalog_crawler.neutrality_check import scan_for_ai_vendor_names


def test_empty_text_returns_no_hits():
    assert scan_for_ai_vendor_names("") == []


def test_generic_ai_wording_is_not_a_hit():
    text = "This skill helps an AI agent or assistant review code changes."
    assert scan_for_ai_vendor_names(text) == []


def test_detects_a_named_vendor_case_insensitively():
    assert "Claude" in scan_for_ai_vendor_names("Optimized for use with claude.")
    assert "OpenAI" in scan_for_ai_vendor_names("Built on top of OPENAI's models.")


def test_detects_multiple_distinct_vendors_without_duplicates():
    text = "Works with Claude, ChatGPT, and also Claude again in the examples below."
    hits = scan_for_ai_vendor_names(text)
    assert hits.count("Claude") == 1
    assert "ChatGPT" in hits


def test_word_boundary_avoids_a_substring_false_positive():
    # "Grok" is a listed vendor name; "Grokking" should not match it as a
    # substring -- word-boundary matching prevents that.
    assert scan_for_ai_vendor_names("A deep dive into Grokking Algorithms.") == []
