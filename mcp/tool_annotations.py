# SPDX-License-Identifier: MIT
# ============================================================
# TOOL ANNOTATIONS — read/write/destructive classification
#
# New, additive module. Confirmed via repo-wide search that no read/write/
# destructive classification exists anywhere in mcp/ today — this is
# genuinely new, not an extension of an existing concept.
#
# Used by the ecosystem tool-calling core's approval flow (connectors/MCP
# phase): a "read" tool runs without confirmation, "write"/"destructive"
# tools require an approval card. Classification is conservative by design —
# an unrecognized tool is never treated as safe.
# ============================================================

from dataclasses import dataclass
from typing import Any, Dict, Literal

Classification = Literal["read", "write", "destructive"]


@dataclass(frozen=True)
class ToolAnnotation:
    tool_name: str
    classification: Classification
    source: str  # "mcp_annotations" | "platform_is_write_op" | "default"


def classify_tool(tool_def: Dict[str, Any]) -> ToolAnnotation:
    """Classify a tool definition as read/write/destructive.

    Accepts either shape already present in this codebase:
      - An MCP-protocol tool definition carrying an `annotations` dict with
        the standard `destructiveHint`/`readOnlyHint` boolean hints (the
        shape external MCP servers advertise).
      - This platform's own `mcp/tool_registry.py` ToolDefinition, serialized
        to a dict, which instead carries a flat `is_write_op` boolean.

    Falls back to "write" (never "read") when neither hint is present —
    an unclassified tool must never be silently treated as safe to
    auto-approve.
    """
    name = str(tool_def.get("name", "unknown"))

    annotations = tool_def.get("annotations")
    if isinstance(annotations, dict):
        if annotations.get("destructiveHint") is True:
            return ToolAnnotation(name, "destructive", "mcp_annotations")
        if annotations.get("readOnlyHint") is True:
            return ToolAnnotation(name, "read", "mcp_annotations")
        if annotations.get("destructiveHint") is False and annotations.get("readOnlyHint") is False:
            return ToolAnnotation(name, "write", "mcp_annotations")

    if "is_write_op" in tool_def:
        classification: Classification = "write" if tool_def.get("is_write_op") else "read"
        return ToolAnnotation(name, classification, "platform_is_write_op")

    return ToolAnnotation(name, "write", "default")
