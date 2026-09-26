# SPDX-License-Identifier: MIT
# ============================================================
# Task B-14: a thin adapter over AgentStudio's existing Skill Factory
# pipeline (AgentStudio/backend/skill_factory/pipeline.py), so
# drafts_service.py never imports anything under AgentStudio/ directly --
# if AgentStudio's process model ever changes, only this file's
# implementation needs to change.
#
# Process model (verified, not assumed): production serves AgentStudio
# in-process with the main gateway (gateway.py inserts AgentStudio's
# packages onto sys.path and mounts its routers directly --
# AgentStudio/backend/Dockerfile's own comment: "Production serves
# ABStudio through the gateway... This image runs ABStudio's own app on
# :8002 and is not referenced by any compose file or service unit" -- the
# standalone :8002 service is dev-only). So this adapter integrates via a
# direct in-process call, importing through that same already-established
# sys.path -- it never re-inserts sys.path itself.
#
# Deliberately skips AgentStudio's own interactive clarification step
# (SkillClarificationEngine's back-and-forth Q&A) -- CONTRACTS.md §10's
# draft flow has no "reply to a clarifying question" endpoint; the next
# interaction point after a draft is generated is PATCH /ecosystem/drafts/
# {id} (the user edits draft_content directly), not more chat turns. A
# minimal `requirements` dict is built directly from the caller's intent
# string instead, mirroring the exact fallback shape
# AgentStudio/backend/app/api/factories.py's own "plan_card"/
# "suggest_existing" branches already use when no interactive answers
# exist yet.
#
# Never touches AgentStudio's own session store (workflow_repo's factory-
# session table) or skills_catalog/skill_files -- constructs its own
# throwaway SkillFactorySession instance and never calls
# get_or_restore_skill_session()/persist_skill_session(), both of which
# read/write that table.
# ============================================================

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional


@dataclass
class DraftTurn:
    """One streamed turn of the draft-generation conversation
    (CONTRACTS.md §10: "intent/clarify/blueprint/content/bundle/critique").
    `data`, when present, carries structured payload (the blueprint, the
    quality summary, the final assembled draft) alongside the human-
    readable `text` progress line.
    """
    stage: str
    text: str
    data: Optional[dict[str, Any]] = None


class SkillFactoryAdapter:
    """The single implementation this phase provides. `generate()` is the
    one method drafts_service.py calls -- never anything under
    AgentStudio/ directly.
    """

    async def generate(self, intent: str) -> AsyncIterator[DraftTurn]:
        # Imported inside the method, not at module level: this module
        # must remain importable even in a process that never mounts
        # AgentStudio (e.g. a lightweight test/tooling process) -- the
        # ImportError only surfaces when generate() is actually called.
        from skill_factory.pipeline import SkillAssembler, SkillBlueprintGenerator, SkillFactorySession, SkillIntentParser
        from app.api.factories import _draft_and_bundle, _lint_summary

        session = SkillFactorySession(session_id=str(uuid.uuid4()))

        yield DraftTurn(stage="intent", text="Understanding what you want to build…")
        session.intent = await SkillIntentParser().parse(intent)

        # Minimal requirements dict built straight from the intent -- see
        # this module's own header comment for why the interactive
        # clarification stage is skipped entirely.
        session.requirements = {"purpose": intent, "triggers": intent}

        yield DraftTurn(stage="blueprint", text="Designing the skill blueprint…")
        session.blueprint = await SkillBlueprintGenerator().generate(session.requirements)
        blueprint_label = session.blueprint.get("display_name") or session.blueprint.get("name") or "your skill"
        yield DraftTurn(
            stage="blueprint", text=f"Blueprint ready: {blueprint_label}",
            data={"blueprint": session.blueprint},
        )

        if session.blueprint.get("needs_bundle"):
            yield DraftTurn(stage="bundle", text="Deciding which scripts/references this skill should ship with…")
        yield DraftTurn(stage="content", text="Writing skill documentation…")
        session.bundle_files, session.content = await _draft_and_bundle(session.blueprint)
        if session.bundle_files:
            names = ", ".join(f["rel_path"] for f in session.bundle_files)
            yield DraftTurn(stage="bundle", text=f"Bundled {len(session.bundle_files)} file(s): {names}")

        quality = _lint_summary(session.content)
        yield DraftTurn(stage="critique", text="Reviewing quality…", data={"quality": quality})

        session.assembled = SkillAssembler().assemble(
            session.blueprint, session.content, bundle_files=session.bundle_files, quality=quality,
        )
        yield DraftTurn(
            stage="assembled", text=f"Draft ready: {session.assembled['display_name']}",
            data={"assembled": session.assembled},
        )
