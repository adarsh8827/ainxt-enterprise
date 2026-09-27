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
#   2. The fast-path-tail ecosystem-skill injection is entered ONLY via
#      `if _is_real_skill_invocation:` -- so with the flag off (where
#      invariant 1 guarantees the variable stays False), that whole block
#      is skipped and _general_stream()'s return is untouched.
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


def test_fast_path_tail_skill_injection_is_gated_solely_on_is_real_skill_invocation():
    ask_ai = _find_ask_ai()
    guards = [
        node for node in ast.walk(ask_ai)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "_is_real_skill_invocation"
    ]

    assert len(guards) == 1, (
        f"expected exactly one `if _is_real_skill_invocation:` block in ask_ai() (the "
        f"fast-path-tail ecosystem injection), found {len(guards)}"
    )
    block_src = ast.dump(guards[0])
    assert "apply_chat_skill_integration" in block_src, (
        "the `if _is_real_skill_invocation:` block no longer calls apply_chat_skill_integration -- "
        "has the fast-path injection been moved elsewhere without updating this guard?"
    )
    # With the flag off, the previous test's invariant guarantees this
    # variable is False, so this whole block -- the only place
    # _fp_skill_used_event can become non-None, and the only place
    # _messages[-1]/safe_question get rewritten for the fast path -- is
    # skipped entirely, leaving _general_stream()'s return byte-identical
    # to the pre-ecosystem code path.


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
