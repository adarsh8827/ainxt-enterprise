# SPDX-License-Identifier: MIT
# ============================================================
# Chat-skills task, 2026-09-28: workers/kafka_consumer.py's _handle_chat_history()
# writes the assistant message's skill (if any) to the dedicated
# ecosystem_message_skills table (db/migrate.py's Part AD12) rather than a
# column on chat_messages itself (Part AD11's original approach, replaced
# same day, Part AD13 drops the column). Real Postgres -- this handler runs
# against the real DB in production, no mocking of the write path itself.
# ============================================================

from __future__ import annotations

import uuid

from workers.kafka_consumer import _handle_chat_history


def _fake_record(chat_id: str, **overrides) -> dict:
    rec = {
        "chat_id": chat_id,
        "user_id": "default",  # sidesteps chats.user_id's FK to users.id
        "question": "fix this email",
        "answer": "Here's a polished version.",
        "model": "test-model",
        "in_tok": 10,
        "out_tok": 20,
        "rag_mode": "off",
    }
    rec.update(overrides)
    return rec


def _fetch_message_skill(message_id: str):
    from db.database import SessionLocal
    from db.models import EcosystemMessageSkill

    db = SessionLocal()
    try:
        return db.query(EcosystemMessageSkill).filter(EcosystemMessageSkill.message_id == message_id).first()
    finally:
        db.close()


def test_skill_used_writes_a_row_to_the_dedicated_table_not_a_chat_messages_column():
    chat_id = str(uuid.uuid4())
    ast_msg_id = str(uuid.uuid4())
    _handle_chat_history([_fake_record(
        chat_id, assistant_message_id=ast_msg_id,
        skill_used={"name": "acme/email-tone-polish", "display_name": "Email Tone Polish", "version_id": str(uuid.uuid4())},
    )])

    row = _fetch_message_skill(ast_msg_id)
    assert row is not None, "expected a row in ecosystem_message_skills for this assistant message"
    assert row.namespace == "acme/email-tone-polish"
    assert row.display_name == "Email Tone Polish"
    assert row.version_id is not None

    from db.database import SessionLocal
    from db.models import ChatMessage

    db = SessionLocal()
    try:
        msg = db.query(ChatMessage).filter(ChatMessage.id == ast_msg_id).one()
        assert not hasattr(ChatMessage, "skill_used"), "chat_messages.skill_used column should be gone (Part AD13)"
        assert msg.content == "Here's a polished version."
    finally:
        db.close()


def test_no_skill_used_writes_no_row_at_all():
    chat_id = str(uuid.uuid4())
    ast_msg_id = str(uuid.uuid4())
    _handle_chat_history([_fake_record(chat_id, assistant_message_id=ast_msg_id)])

    assert _fetch_message_skill(ast_msg_id) is None


def test_skill_used_missing_name_key_writes_no_row():
    # Defensive: a malformed/legacy event with a skill_used dict but no
    # "name" key must not crash the handler or insert a garbage row.
    chat_id = str(uuid.uuid4())
    ast_msg_id = str(uuid.uuid4())
    _handle_chat_history([_fake_record(chat_id, assistant_message_id=ast_msg_id, skill_used={"display_name": "orphan"})])

    assert _fetch_message_skill(ast_msg_id) is None
