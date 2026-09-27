# SPDX-License-Identifier: MIT
# Real bug found live: a chat opened via the Ecosystem "/skill-name rest"
# chat-skill convention auto-titled itself starting with the literal
# slash-command token, since the raw first message was fed straight into
# the title-generation LLM prompt. routers/chat_router.py's
# _strip_leading_slash_command() strips it before the prompt is built.
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
