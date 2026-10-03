// SPDX-License-Identifier: MIT
// Shared read/write/destructive badge -- mirrors mcp/tool_annotations.py's
// classify_tool() output. Used by ConnectorDetail's Tools list and (in
// ai-ui) the chat ToolApprovalCard, so the same visual language means the
// same thing in both places.
//
// Full Tailwind pass (2026-10-03): rewritten to literal Tailwind classes,
// matching ../Badges.jsx's own BADGE_BASE pill convention instead of
// var(--eco-*).

const BADGE_BASE = "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold leading-4 border";
const MAP = {
  read: {
    label: "Read-only",
    className: "text-blue-700 bg-blue-50 border-blue-200",
    dot: "bg-blue-700"
  },
  write: {
    label: "Write",
    className: "text-amber-700 bg-amber-50 border-amber-200",
    dot: "bg-amber-700"
  },
  destructive: {
    label: "Destructive",
    className: "text-red-700 bg-red-50 border-red-200",
    dot: "bg-red-700"
  }
};
export function ToolClassificationBadge({
  classification
}) {
  const {
    label,
    className,
    dot
  } = MAP[classification];
  return <span data-testid="tool-classification-badge" data-classification={classification} className={[BADGE_BASE, className].join(" ")}>
      <span aria-hidden="true" className={["w-1.5 h-1.5 rounded-full", dot].join(" ")} />
      {label}
    </span>;
}
