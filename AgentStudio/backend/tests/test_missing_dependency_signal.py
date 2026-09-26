# SPDX-License-Identifier: MIT
"""Task B-23: NativeEngine._resolve_catalog_tools() surfaces a dropped
tool reference as "missing dependency" instead of silently vanishing,
when ECOSYSTEM_AGENTSTUDIO_MISSING_DEP is on.

Source-string style (same convention as test_sample_doc.py's own
native-engine plumbing checks) to keep this dependency-free: importing
native_engine directly pulls in the main repo's core.* stack (core.logger
et al.), which this file cannot reach standalone without the full
in-process gateway.py boot path.
"""

from __future__ import annotations

from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]


def _native_engine_source() -> str:
    return (_BACKEND / "app" / "engine" / "native_engine.py").read_text(encoding="utf-8")


def test_missing_dependency_flag_is_read_defensively():
    src = _native_engine_source()
    # Must come from the MAIN repo's core.config (not AgentStudio's own
    # app.core.config, which has no such flag), and must fail closed
    # (flag off) if that import isn't reachable -- AgentStudio's
    # standalone dev-mode service has no such import path at all.
    assert "from core.config import ECOSYSTEM_AGENTSTUDIO_MISSING_DEP" in src, \
        "must import the flag from the main repo's core.config, not app.core.config"
    assert "except ImportError" in src and "ECOSYSTEM_AGENTSTUDIO_MISSING_DEP = False" in src, \
        "must fail closed (flag off) when core.config isn't importable, not crash tool resolution"


def test_resolve_catalog_tools_takes_missing_dependencies_as_an_optional_out_param():
    src = _native_engine_source()
    assert "missing_dependencies: Optional[list] = None" in src, \
        "_resolve_catalog_tools must accept missing_dependencies as an optional, default-None parameter " \
        "-- every existing call site omits it, so this must never be a required/positional change"


def test_both_drop_sites_record_into_missing_dependencies_when_flag_on():
    src = _native_engine_source()
    # Exactly two places drop a requested tool today (an exception during
    # lookup, or a lookup that returned nothing) -- both must record.
    assert src.count("if ECOSYSTEM_AGENTSTUDIO_MISSING_DEP and missing_dependencies is not None:") == 2, \
        "expected both drop sites (lookup exception, tool not found) to record into missing_dependencies"
    assert "missing_dependencies.append(tool_name)" in src


def test_the_original_warning_logs_are_still_present_flag_off_behavior_unchanged():
    # The pre-existing log lines must survive untouched -- this task adds
    # a signal, it does not replace the existing warning-and-continue
    # behavior for callers that don't opt in (i.e. every caller before
    # this task, and the flag-off default).
    src = _native_engine_source()
    assert 'logger.warning(f"[AGENT] Catalog tool lookup failed for \'{tool_name}\': {row}")' in src
    assert 'logger.warning(f"[AGENT] Catalog tool \'{tool_name}\' not in tools_catalog — skipping")' in src


def test_missing_dependencies_is_never_stored_on_self():
    """NativeEngine is a shared singleton across concurrent requests (its
    own docstring: "Singleton tool cache for platform utilities" on
    self._singleton_tool_cache). Storing missing-dependency state on
    `self` would leak across unrelated concurrent requests -- it must
    only ever be a per-call parameter/local, never `self.missing_*` or
    similar.
    """
    src = _native_engine_source()
    assert "self.missing_dependencies" not in src
    assert "self._missing_dependencies" not in src


def test_run_agent_wires_the_out_param_for_the_picker_attached_tools_call_site_only():
    """Task B-23 (UI wiring): of _resolve_catalog_tools's 7 call sites, only
    the one resolving a node's own picker-attached tools (``data.get("tools")``)
    is the right one to surface as "missing dependency" -- the others
    resolve always-present platform singletons (code_executor,
    read_skill_file) which can't meaningfully go "missing". Exactly one
    call site in the whole file may pass missing_dependencies=.
    """
    src = _native_engine_source()
    assert src.count("missing_dependencies=node_missing_deps") == 1, \
        "expected exactly one call site (the picker-attached-tools resolution in _run_agent) to wire the out-param"
    assert 'catalog_tools = await self._resolve_catalog_tools(\n                data.get("tools") or [],' in src


def test_run_agent_declares_node_missing_deps_as_a_local_before_the_cache_branch():
    """``node_missing_deps`` must be initialised unconditionally (an empty
    list) before the resolved_tools_cache branch, so a loop's cache-hit
    re-entries (which skip re-resolving, per REQ-P3-2) still have a defined
    -- just empty -- value to report, instead of raising NameError or
    carrying over a previous node's list by accident.
    """
    src = _native_engine_source()
    idx_decl = src.index("node_missing_deps: list = []")
    idx_cache_check = src.index("if node_id in gctx.resolved_tools_cache:")
    idx_call = src.index("missing_dependencies=node_missing_deps")
    assert idx_decl < idx_cache_check < idx_call, \
        "node_missing_deps must be declared before the cache-hit branch and before the call that populates it"


def test_agent_start_and_agent_progress_only_add_the_field_when_something_is_actually_missing():
    """Byte-identical SSE payloads for the overwhelming common case (flag
    off, or flag on but nothing dropped): the new field must be spread in
    conditionally, never present-but-empty, so no existing SSE consumer
    (frontend or otherwise) sees a payload shape it didn't see before this
    task existed.
    """
    src = _native_engine_source()
    assert '_missing_dep_field = {"missing_dependencies": node_missing_deps} if node_missing_deps else {}' in src
    assert 'yield make_sse("agent_start", {"agent": name, "node_id": node_id, **_missing_dep_field})' in src
    assert '"status": "running",\n                    **_missing_dep_field,' in src
