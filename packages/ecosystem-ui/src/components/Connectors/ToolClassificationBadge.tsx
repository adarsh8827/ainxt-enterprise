// SPDX-License-Identifier: MIT
// Shared read/write/destructive badge -- mirrors mcp/tool_annotations.py's
// classify_tool() output. Used by ConnectorDetail's Tools list and (in
// ai-ui) the chat ToolApprovalCard, so the same visual language means the
// same thing in both places.
import type { CSSProperties } from "react";
import type { ToolClassification } from "../../types";

const MAP: Record<ToolClassification, { label: string; color: string; bg: string }> = {
  read: { label: "Read-only", color: "var(--eco-color-info)", bg: "var(--eco-color-infoBg)" },
  write: { label: "Write", color: "var(--eco-color-warning)", bg: "var(--eco-color-warningBg)" },
  destructive: { label: "Destructive", color: "var(--eco-color-danger)", bg: "var(--eco-color-dangerBg)" },
};

export function ToolClassificationBadge({ classification }: { classification: ToolClassification }) {
  const { label, color, bg } = MAP[classification];
  const style: CSSProperties = {
    display: "inline-flex", alignItems: "center", gap: "4px",
    padding: "2px 8px", borderRadius: "var(--eco-radius-full)",
    fontSize: "var(--eco-font-sizeXs)", fontWeight: 600, lineHeight: "16px",
    border: `1px solid ${color}`, color, background: bg,
  };
  return (
    <span data-testid="tool-classification-badge" data-classification={classification} style={style}>
      <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: "50%", background: color }} />
      {label}
    </span>
  );
}
