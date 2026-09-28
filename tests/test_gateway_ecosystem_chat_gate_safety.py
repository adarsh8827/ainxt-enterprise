# SPDX-License-Identifier: MIT
# ============================================================
# gateway.py's ask_ai(): CIL ambiguity-clarification gate + PIPELINE_V2
# fast-path tail ecosystem-skill integration -- safety-scoping regression.
#
# WHY A STRUCTURAL (SOURCE-LEVEL) TEST INSTEAD OF EXERCISING ask_ai() DIRECTLY
# ------------------------------------------------------------------------
# ask_ai() is a single ~16k-line function inside gateway.py, and importing
# gateway.py runs core.ckms.load_at_boot() at import time (needs a live HSM,
# unavailable in CI) -- same constraint documented in
# test_passthrough_scan_ledger.py. ask_ai()'s ecosystem-gate logic also
# closes over dozens of local variables computed earlier in the same
# function (_rc, _model_hint, _messages, request, ...), so it cannot be
# lifted out and exec()'d standalone the way that file's free-standing
# helper functions can.
#
# Instead, this test asserts the EXACT structural invariants that make the
# "flag off -> byte-identical to before" claim true, by parsing gateway.py's
# real AST:
#   1. _is_real_skill_invocation is unconditionally initialized to False,
#      and the ONLY place it can become True is inside a block gated on
#      _ECOSYSTEM_CHAT_SKILLS (mirrors the pre-existing
#      _looks_like_skill_invocation gating this replaced).
#   2. The fast-path-tail ecosystem-skill injection (skill-body rewrite AND
#      the "## Skills" index append, 2026-09-28) is entered ONLY via
#      `if _ECOSYSTEM_CHAT_SKILLS and ...:` -- so with the flag off, that
#      whole block is skipped and _general_stream()'s return is untouched.
#
# If a future edit adds a second, unguarded assignment to
# _is_real_skill_invocation, or moves the injection block out from behind
# its guard, this test fails -- catching exactly the class of regression
# the safety review was worried about.
# ============================================================

from __future__ import annotations

import ast
import pathlib

_GATEWAY_PATH = pathlib.Path(__file__).resolve().parent.parent / "gateway.py"


def _find_ask_ai() -> ast.AsyncFunctionDef:
    tree = ast.parse(_GATEWAY_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "ask_ai":
            return node
    raise AssertionError("ask_ai() not found in gateway.py -- has it been renamed/moved?")


def _build_parent_map(func: ast.AST) -> dict:
    parent_map: dict = {}
    for parent in ast.walk(func):
        for child in ast.iter_child_nodes(parent):
            parent_map[child] = parent
    return parent_map


def _enclosing_ifs(node: ast.AST, func: ast.AST, parent_map: dict) -> list[ast.If]:
    """All `If` nodes enclosing `node`, innermost first, up to (not
    including) `func` itself."""
    chain = []
    cur = parent_map.get(node)
    while cur is not None and cur is not func:
        if isinstance(cur, ast.If):
            chain.append(cur)
        cur = parent_map.get(cur)
    return chain


def _assignments_to(func: ast.AST, name: str) -> list[tuple[ast.Assign, list[ast.If]]]:
    """Returns [(assign_node, enclosing_if_chain)] for every `name = ...`
    assignment inside func."""
    parent_map = _build_parent_map(func)
    results = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            results.append((node, _enclosing_ifs(node, func, parent_map)))
    return results


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def test_is_real_skill_invocation_is_only_ever_set_true_behind_the_ecosystem_flag():
    # Both assignments legitimately sit inside gateway.py's own pre-existing
    # `if not repo_filter and not q.project_id and q.mode != "office" and
    # not _pv2_force_orchestrator:` wrapper (unrelated to ecosystem gating,
    # predates this task) -- so "unconditional" here means "gated by
    # nothing ECOSYSTEM-related", not "zero enclosing ifs in the whole
    # function". What must hold: the False-initializer's enclosing-if chain
    # contains no _ECOSYSTEM_CHAT_SKILLS check, while the real-check
    # assignment's chain has exactly one extra `if` beyond that shared
    # baseline, and that extra `if` is the _ECOSYSTEM_CHAT_SKILLS gate.
    ask_ai = _find_ask_ai()
    assigns = _assignments_to(ask_ai, "_is_real_skill_invocation")
    assert len(assigns) == 2, (
        f"expected exactly 2 assignments to _is_real_skill_invocation in ask_ai() "
        f"(the False init + the flag-gated real check), found {len(assigns)} -- "
        "review whether a new, possibly-unguarded assignment was added"
    )

    init_candidates = [a for a in assigns if not any("_ECOSYSTEM_CHAT_SKILLS" in _names_in(i.test) for i in a[1])]
    gated_candidates = [a for a in assigns if any("_ECOSYSTEM_CHAT_SKILLS" in _names_in(i.test) for i in a[1])]
    assert len(init_candidates) == 1, (
        "expected exactly one assignment to _is_real_skill_invocation with no "
        "_ECOSYSTEM_CHAT_SKILLS-gated ancestor (the False initializer)"
    )
    assert len(gated_candidates) == 1, (
        "expected exactly one assignment to _is_real_skill_invocation gated (directly or "
        "transitively) on _ECOSYSTEM_CHAT_SKILLS (the real membership check)"
    )

    init_node, init_ifs = init_candidates[0]
    gated_node, gated_ifs = gated_candidates[0]
    init_value = init_node.value
    assert isinstance(init_value, ast.Constant) and init_value.value is False, (
        "the non-ecosystem-gated assignment must initialize _is_real_skill_invocation to False"
    )
    # The gated assignment's enclosing-if chain must be a strict superset of
    # the init's chain (same outer wrapper) plus exactly one more `if`
    # (the ecosystem-flag gate itself) -- proving the flag gate is the ONLY
    # additional condition standing between "False" and "real check".
    assert len(gated_ifs) == len(init_ifs) + 1, (
        f"expected the flag-gated assignment to sit exactly one `if` deeper than the False "
        f"initializer's shared wrapper (init depth={len(init_ifs)}, gated depth={len(gated_ifs)}) -- "
        "an extra layer of conditions may have been introduced around the real membership check"
    )
    innermost_extra_if = gated_ifs[0]
    assert "_ECOSYSTEM_CHAT_SKILLS" in _names_in(innermost_extra_if.test), (
        "the single extra `if` gating the real membership-check assignment must test "
        "_ECOSYSTEM_CHAT_SKILLS directly -- with the flag off, _is_real_skill_invocation must "
        "stay False so the CIL gate behaves byte-identically to pre-ecosystem behavior"
    )


def test_fast_path_tail_skill_injection_is_gated_solely_on_the_ecosystem_flag():
    # Item, 2026-09-28: this guard used to be a bare `if _is_real_skill_invocation:`
    # (so a plain, non-slash message under PIPELINE_V2 never even computed
    # the "## Skills" index, since apply_chat_skill_integration() -- the one
    # function that sets state.metadata["ecosystem_skill_index"] -- was
    # never called for it at all). Fixed by gating this block the same way
    # agents/orchestrator.py gates its own unconditional call to the same
    # function: directly on _ECOSYSTEM_CHAT_SKILLS (+ mode/surface), not on
    # whether THIS message happens to be a slash invocation. This is a
    # strictly more direct "flag off -> unchanged" invariant than the old
    # one (one hop from the actual flag instead of via an intermediate
    # variable), so this test asserts it structurally the same way.
    ask_ai = _find_ask_ai()
    guards = [
        node for node in ast.walk(ask_ai)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.BoolOp)
        and isinstance(node.test.op, ast.And)
        and "_ECOSYSTEM_CHAT_SKILLS" in _names_in(node.test)
        and "apply_chat_skill_integration" in ast.dump(node)
    ]

    assert len(guards) == 1, (
        f"expected exactly one `if _ECOSYSTEM_CHAT_SKILLS and ...:` block in ask_ai() calling "
        f"apply_chat_skill_integration (the fast-path-tail ecosystem injection), found {len(guards)}"
    )
    # With the flag off, this whole block -- the only place _fp_skill_used_event
    # can become non-None, and the only place _messages[-1]/safe_question get
    # rewritten (slash-command body OR the "## Skills" index) for the fast
    # path -- is skipped entirely, leaving _general_stream()'s return
    # byte-identical to the pre-ecosystem code path.


def _extract_function(func_name: str, *, within: ast.AST | None = None) -> ast.FunctionDef | ast.AsyncFunctionDef:
    root = within if within is not None else ast.parse(_GATEWAY_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(root):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return node
    raise AssertionError(f"{func_name}() not found")


def test_skill_chip_wrapper_forwards_every_item_from_the_original_stream_without_hanging():
    # Live bug found + fixed 2026-09-27: _general_stream_with_skill_chip()
    # originally did `async for _chunk in _underlying_general_stream:`,
    # closing over the FREE VARIABLE _underlying_general_stream -- but the
    # very next statement in ask_ai() reassigned that same name to the
    # wrapper generator itself. Python closures are late-binding (looked up
    # by name at call time, not captured by value at def time), so by the
    # time the wrapper was actually iterated, `_underlying_general_stream`
    # in the enclosing scope pointed at the wrapper -- making it iterate
    # itself. Every real skill-chip request hung forever after the chip
    # frame with no error, no timeout, and no further log line (confirmed
    # live: ECOSYSTEM_SKILL_INJECTED_AS_USER_MESSAGE logged, then total
    # silence for 100+ seconds against the running gateway container).
    #
    # This test extracts the CURRENT _general_stream_with_skill_chip
    # function verbatim from gateway.py's real source via AST (gateway.py
    # itself can't be imported in CI -- HSM boot at import time, same
    # constraint as test_passthrough_scan_ledger.py) and drives it with a
    # fake multi-item source stream. If the closure bug is ever
    # reintroduced under the old variable name, this either hangs (caught
    # by pytest-timeout-free asyncio.wait_for below) or raises NameError
    # (the extraction only ever provides `_fp_source_stream` as a global,
    # never `_underlying_general_stream`) -- either way, a loud failure
    # instead of a silent production hang.
    ask_ai = _find_ask_ai()
    wrapper_def = _extract_function("_general_stream_with_skill_chip", within=ask_ai)

    module = ast.Module(body=[wrapper_def], type_ignores=[])
    ast.fix_missing_locations(module)

    async def _fake_source_stream():
        for item in ("data: one\n\n", "data: two\n\n", "data: three\n\n"):
            yield item

    namespace: dict = {
        "json": __import__("json"),
        "_fp_skill_used_event": {"skill_used": {"name": "acme/demo", "display_name": "Demo"}},
        "_fp_source_stream": _fake_source_stream(),
    }
    exec(compile(module, str(_GATEWAY_PATH), "exec"), namespace)  # noqa: S102
    wrapped = namespace["_general_stream_with_skill_chip"]()

    async def _drain():
        import asyncio
        items = []
        while True:
            item = await asyncio.wait_for(wrapped.__anext__(), timeout=5.0)
            items.append(item)
            if len(items) >= 4:
                break
        return items

    import asyncio
    items = asyncio.run(_drain())

    assert items[0] == "data: " + __import__("json").dumps(namespace["_fp_skill_used_event"]) + "\n\n"
    assert items[1:] == ["data: one\n\n", "data: two\n\n", "data: three\n\n"]


def test_cil_clarification_condition_still_checks_is_real_skill_invocation():
    # Pins the CIL gate's own guard clause -- if a future refactor drops
    # `not _is_real_skill_invocation` from the clarification condition, the
    # gate would either always skip clarification for slash-shaped text
    # (regressing the original CIL bug) or never skip it for real skill
    # invocations (regressing the fix this test suite exists for).
    ask_ai = _find_ask_ai()
    found = False
    for node in ast.walk(ask_ai):
        if isinstance(node, ast.If):
            test_src = ast.dump(node.test)
            if "clarification_needed" in test_src:
                assert "_is_real_skill_invocation" in test_src, (
                    "the CIL clarification-needed condition no longer references "
                    "_is_real_skill_invocation -- the skill-invocation bypass has been lost"
                )
                found = True
    assert found, "no `if ...clarification_needed...` block found in ask_ai() -- has the CIL gate moved?"
