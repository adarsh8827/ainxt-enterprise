# SPDX-License-Identifier: MIT
# ============================================================
# Item-level neutrality check for the external-sources crawler
# (docs/ecosystem/EXTERNAL_SOURCES_PLAN.md §4). Same rule the starter-
# catalog scan already applied by hand: a skill whose content
# extensively names specific AI products/vendors was excluded from that
# batch (docs/ecosystem/catalog/starter-approved.md's own note, re:
# nidhinjs/prompt-master) for violating this platform's neutrality
# requirement. This module makes that rule automatic and consistent at
# crawl time, for every source, instead of a one-off manual judgment.
#
# Heuristic, disclosed as such (same class of tradeoff as
# gate/static_safety_stage.py's own injection-pattern scanner): a name
# list can't catch every AI vendor that will ever exist, and a skill
# that avoids every listed term while still being vendor-specific in
# spirit would pass. Excluded items are logged with which name(s)
# matched (crawl report), never silently dropped without a reason.
# ============================================================

from __future__ import annotations

import re

# Real AI assistant/model/coding-tool vendor and product names -- not
# generic words like "AI", "agent", or "assistant" (those would flag
# nearly everything and defeat the purpose). Word-boundary matched,
# case-insensitive. Deliberately a flat list, not an exhaustive
# taxonomy -- extend it here as new, clearly-named products turn up in
# crawled content, the same way the injection-pattern list is maintained.
_AI_VENDOR_NAMES = [
    "OpenAI", "ChatGPT", "GPT-4", "GPT-3", "GPT-5",
    "Anthropic", "Claude",
    "Google Gemini", "Gemini", "Bard",
    "GitHub Copilot", "Copilot",
    "Meta AI", "Llama",
    "Mistral AI",
    "Cohere",
    "Perplexity AI",
    "Cursor AI", "Cursor IDE",
    "Windsurf",
    "Codeium",
    "Devin AI",
    "Replit AI",
    "Amazon Q",
    "Hugging Face",
    "DeepSeek",
    "Grok",
    "Qwen",
]

_PATTERNS = [re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE) for name in _AI_VENDOR_NAMES]


def scan_for_ai_vendor_names(text: str) -> list[str]:
    """Returns the distinct vendor/product names found in `text`
    (empty list if none). Case-insensitive, whole-word matching."""
    if not text:
        return []
    found: list[str] = []
    for name, pattern in zip(_AI_VENDOR_NAMES, _PATTERNS):
        if pattern.search(text) and name not in found:
            found.append(name)
    return found
