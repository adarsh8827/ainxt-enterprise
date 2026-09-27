# SPDX-License-Identifier: MIT
# ============================================================
# Task B-14: Create-with-AI drafts. drafts_service.py's only dependency on
# generation is services.ecosystem.skill_factory_adapter -- every test
# here mocks SkillFactoryAdapter.generate() itself (never the underlying
# AgentStudio pipeline, which needs a real LLM call and the full
# AgentStudio import chain), per this task's own stated test requirement.
# Tier-2, real Postgres.
# ============================================================

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from services.ecosystem import create_service, drafts_service
from services.ecosystem.errors import EcosystemError, NotFoundError
from services.ecosystem.skill_factory_adapter import DraftTurn

_REPO_ROOT = Path(__file__).resolve().parents[3]


async def _fake_generate(self, intent: str):
    yield DraftTurn(stage="intent", text="Understanding...")
    yield DraftTurn(stage="blueprint", text="Blueprint ready", data={"blueprint": {"name": "test-skill"}})
    yield DraftTurn(
        stage="assembled", text="Draft ready: Test Skill",
        data={"assembled": {
            "name": "test-skill", "display_name": "Test Skill", "description": "does a thing",
            "category": "productivity", "content": intent, "generated": True,
            "tags": ["test"], "bundle_files": [], "quality": {"lint_issues": 0, "issues": []},
        }},
    )


def _mock_adapter():
    return patch("services.ecosystem.skill_factory_adapter.SkillFactoryAdapter.generate", _fake_generate)


def test_drafts_service_never_imports_anything_under_agentstudio_directly():
    """B-14's own stated test requirement, verbatim: 'a test that mocks
    skill_factory_adapter.py's interface (not the underlying pipeline) to
    confirm drafts_service.py has no direct import of anything under
    AgentStudio/'."""
    src = (_REPO_ROOT / "services" / "ecosystem" / "drafts_service.py").read_text(encoding="utf-8")
    assert "import AgentStudio" not in src and "from AgentStudio" not in src
    assert "from skill_factory" not in src and "import skill_factory" not in src or "skill_factory_adapter" in src
    assert "from services.ecosystem.skill_factory_adapter import" in src or "from services.ecosystem import skill_factory_adapter" in src


def test_create_draft_starts_in_drafting_status_with_empty_content():
    draft = drafts_service.create_draft(org_id="org-drafts", created_by="user-a", item_type="skill")
    assert draft["status"] == "drafting"
    assert draft["draft_content"] == {}
    assert draft["item_type"] == "skill"


@pytest.mark.asyncio
async def test_stream_draft_generation_populates_draft_content_and_sets_ready():
    draft = drafts_service.create_draft(org_id="org-drafts", created_by="user-a")
    with _mock_adapter():
        turns = [t async for t in drafts_service.stream_draft_generation(draft["id"], "a thing that does stuff", org_id="org-drafts")]

    assert [t.stage for t in turns] == ["intent", "blueprint", "assembled"]

    updated = drafts_service.get_draft(draft["id"], org_id="org-drafts")
    assert updated["status"] == "ready"
    assert updated["draft_content"]["display_name"] == "Test Skill"
    assert updated["draft_content"]["license"] == "MIT"
    assert updated["draft_content"]["namespace"] == "org-drafts/test-skill"
    assert updated["draft_content"]["instructions"] == "a thing that does stuff"


@pytest.mark.asyncio
async def test_stream_draft_generation_raises_not_found_for_a_draft_in_another_org():
    draft = drafts_service.create_draft(org_id="org-drafts-a", created_by="user-a")
    with pytest.raises(NotFoundError):
        async for _ in drafts_service.stream_draft_generation(draft["id"], "x", org_id="org-drafts-b"):
            pass


def test_patch_draft_merges_fields_without_clobbering_others():
    draft = drafts_service.create_draft(org_id="org-drafts", created_by="user-a")
    drafts_service.patch_draft(draft["id"], org_id="org-drafts", patch={"namespace": "acme/foo", "license": "MIT"})
    updated = drafts_service.patch_draft(draft["id"], org_id="org-drafts", patch={"display_name": "Foo"})
    assert updated["draft_content"] == {"namespace": "acme/foo", "license": "MIT", "display_name": "Foo"}


def test_patch_draft_rejects_editing_a_submitted_draft():
    draft = drafts_service.create_draft(org_id="org-drafts", created_by="user-a")
    drafts_service.patch_draft(draft["id"], org_id="org-drafts", patch={
        "namespace": "org-drafts/submit-then-edit", "display_name": "D", "description": "d",
        "category": "productivity", "instructions": "x",
    })
    with patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}'):
        drafts_service.submit_draft(draft["id"], org_id="org-drafts", created_by="user-a")

    with pytest.raises(EcosystemError):
        drafts_service.patch_draft(draft["id"], org_id="org-drafts", patch={"display_name": "changed"})


def test_submit_draft_creates_a_real_item_and_stamps_submitted_item_id():
    # Task D: this draft is private (no provision_scope in its content)
    # with no bundled files -- create_via_write()'s own fast-path
    # eligibility applies to a submitted draft exactly as it does to the
    # Write flow, so this resolves "active" synchronously, not
    # "verifying" (pre-task-D behavior; see drafts_service.submit_draft()'s
    # own updated docstring).
    draft = drafts_service.create_draft(org_id="org-drafts", created_by="user-a")
    drafts_service.patch_draft(draft["id"], org_id="org-drafts", patch={
        "namespace": "org-drafts/submit-me", "display_name": "Submit Me", "description": "d",
        "category": "productivity", "license": "MIT", "instructions": "do the thing", "files": [],
    })
    with patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}'):
        result = drafts_service.submit_draft(draft["id"], org_id="org-drafts", created_by="user-a")

    assert result["status"] == "active"
    updated = drafts_service.get_draft(draft["id"], org_id="org-drafts")
    assert updated["status"] == "submitted"
    assert updated["submitted_item_id"] == result["item_id"]


def test_submit_draft_with_bundled_files_keeps_the_normal_async_gate():
    # The other half of the same fast-path eligibility check: a draft
    # WITH files is never fast-pathed, so it still returns "verifying".
    draft = drafts_service.create_draft(org_id="org-drafts", created_by="user-a")
    drafts_service.patch_draft(draft["id"], org_id="org-drafts", patch={
        "namespace": "org-drafts/submit-me-with-files", "display_name": "Submit Me", "description": "d",
        "category": "productivity", "license": "MIT", "instructions": "do the thing",
        "files": [{"name": "notes.md", "content": "extra context"}],
    })
    with patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}'):
        result = drafts_service.submit_draft(draft["id"], org_id="org-drafts", created_by="user-a")

    assert result["status"] == "verifying"
    updated = drafts_service.get_draft(draft["id"], org_id="org-drafts")
    assert updated["status"] == "submitted"
    assert updated["submitted_item_id"] == result["item_id"]


def test_submit_draft_without_a_namespace_fails_clearly():
    draft = drafts_service.create_draft(org_id="org-drafts", created_by="user-a")
    drafts_service.patch_draft(draft["id"], org_id="org-drafts", patch={"display_name": "No Namespace"})
    with pytest.raises(EcosystemError, match="namespace"):
        drafts_service.submit_draft(draft["id"], org_id="org-drafts", created_by="user-a")


def test_submit_draft_twice_raises_rather_than_creating_a_second_item():
    draft = drafts_service.create_draft(org_id="org-drafts", created_by="user-a")
    drafts_service.patch_draft(draft["id"], org_id="org-drafts", patch={
        "namespace": "org-drafts/submit-twice", "display_name": "D", "description": "d",
        "category": "productivity", "license": "MIT", "instructions": "x",
    })
    with patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}'):
        drafts_service.submit_draft(draft["id"], org_id="org-drafts", created_by="user-a")
        with pytest.raises(EcosystemError, match="already submitted"):
            drafts_service.submit_draft(draft["id"], org_id="org-drafts", created_by="user-a")


def test_purge_abandoned_drafts_dry_run_does_not_delete():
    from db.database import SessionLocal
    from db.models import EcosystemDraft

    draft = drafts_service.create_draft(org_id="org-drafts", created_by="user-a")
    db = SessionLocal()
    try:
        row = db.query(EcosystemDraft).filter(EcosystemDraft.id == draft["id"]).first()
        row.status = "abandoned"
        from datetime import datetime, timedelta, timezone
        row.updated_at = datetime.now(timezone.utc) - timedelta(days=31)
        db.commit()
    finally:
        db.close()

    result = drafts_service.purge_abandoned_drafts(dry_run=True)
    assert result["candidates"] >= 1
    assert result["deleted"] == 0
    assert drafts_service.get_draft(draft["id"], org_id="org-drafts") is not None
