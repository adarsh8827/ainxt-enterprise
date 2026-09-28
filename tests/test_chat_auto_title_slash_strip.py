# SPDX-License-Identifier: MIT
# Real bug found live: a chat opened via the Ecosystem "/skill-name rest"
# chat-skill convention auto-titled itself starting with the literal
# slash-command token, since the raw first message was fed straight into
# the title-generation LLM prompt. routers/chat_router.py's
# _strip_leading_slash_command() strips it before the prompt is built.
import ast
import pathlib

from routers.chat_router import _strip_leading_slash_command


def test_strips_a_leading_slash_command_and_the_space_after_it():
    assert _strip_leading_slash_command("/email-tone-polish write an email for my boss") == "write an email for my boss"


def test_leaves_a_plain_message_with_no_leading_slash_untouched():
    assert _strip_leading_slash_command("write an email for my boss") == "write an email for my boss"


def test_a_slash_with_nothing_after_it_strips_to_empty_string():
    # The caller (auto_title_chat) falls back to the original text when
    # this happens, rather than building a prompt from an empty question.
    assert _strip_leading_slash_command("/email-tone-polish") == ""


def test_does_not_strip_a_slash_that_is_not_at_the_very_start():
    assert _strip_leading_slash_command("check /email-tone-polish please") == "check /email-tone-polish please"


def test_only_strips_the_first_token_not_a_second_slash_later_in_the_message():
    assert _strip_leading_slash_command("/email-tone-polish also see /other-thing") == "also see /other-thing"


def test_gateways_inline_title_hint_also_strips_the_leading_slash_command():
    # Item, 2026-09-28: auto_title_chat() above strips the leading slash
    # command before its OWN, later LLM-based title regeneration -- but
    # gateway.py's inline title_hint (set once, at first-message time,
    # before any regeneration ever runs) used to build the chat's INITIAL
    # title straight from stored_question with no stripping at all, so a
    # skill-invoked first message titled the chat "/email-tone-polish fix
    # this email..." verbatim until/unless a later regeneration ran.
    #
    # Scoped to the two call sites that actually got fixed (the main
    # ainxt.chat_history produce call and its Kafka-down direct-Postgres
    # fallback, both keyed off the same already-redacted `stored_question`
    # variable) -- NOT every "title_hint" dict literal in gateway.py.
    # Several OTHER, unrelated persistence call sites (voice-mode/KB-
    # grounded branch, the doc-job/runtime-canary/edit-message paths) store
    # `safe_question`/`q.question` directly and were never touched by this
    # fix -- a real, wider, pre-existing gap (those branches would show a
    # skill's expanded body or un-stripped slash prefix in stored history
    # too) disclosed but not fixed here: fixing them safely means auditing
    # each branch's own PII-redaction semantics individually, since some of
    # them read `safe_question` AFTER it has been overwritten with
    # unredacted text by apply_chat_skill_integration's own `rest = ...`
    # (taken from `original`, not the PII-masked `safe_question`) -- a
    # separate, pre-existing PII-redaction subtlety, not caused by this fix
    # and not addressed by it either.
    #
    # gateway.py can't be imported directly in tests (core.ckms.load_at_boot()
    # needs a live HSM at import time) -- same constraint documented in
    # test_gateway_ecosystem_chat_gate_safety.py -- so this asserts the fix
    # structurally via gateway.py's real source AST instead.
    gateway_path = pathlib.Path(__file__).resolve().parent.parent / "gateway.py"
    tree = ast.parse(gateway_path.read_text(encoding="utf-8"))

    fixed_sites = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant) and key.value == "title_hint"
                    and "stored_question" in ast.dump(value)
                ):
                    assert "_chat_router_strip_slash" in ast.dump(value), (
                        "a 'title_hint' dict entry keyed off stored_question no longer calls "
                        "the chat_router slash-stripping helper -- has the fix been reverted?"
                    )
                    fixed_sites += 1
    assert fixed_sites == 2, (
        f"expected exactly 2 stored_question-based 'title_hint' sites (the main produce call "
        f"and its Kafka-fallback duplicate), found {fixed_sites} -- if this number changed, "
        f"a call site was added/removed/refactored; update this test and re-check whether it "
        f"needs the same slash-stripping fix"
    )

    # And the import itself must actually resolve to the real helper this
    # file's own tests above already exercise, not a stray same-named stub.
    import_found = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "routers.chat_router"
        and any(alias.name == "_strip_leading_slash_command" and alias.asname == "_chat_router_strip_slash" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert import_found, "gateway.py no longer imports _strip_leading_slash_command as _chat_router_strip_slash"
