// SPDX-License-Identifier: MIT
// Connectors phase (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 3):
// approval card for a write/destructive tool call. Read-only tool calls
// never reach this component -- the backend only ever queues write/
// destructive calls for approval (mcp/tool_annotations.py's
// classify_tool()), so there is no "auto-approve read" branch here to get
// wrong. Params are rendered as a readable key/value list rather than a
// raw JSON dump wherever the value is a primitive; a nested object/array
// value still falls back to JSON.stringify for that one field only.
const CLASSIFICATION_STYLE = {
  write: "bg-amber-50 border-amber-200 text-amber-700",
  destructive: "bg-red-50 border-red-200 text-red-700",
};

function formatParamValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function ToolApprovalCard({ toolName, classification, params = {}, target, onApprove, onDeny, busy = false }) {
  const badgeClass = CLASSIFICATION_STYLE[classification] || CLASSIFICATION_STYLE.write;
  const paramEntries = Object.entries(params || {});

  return (
    <div data-testid="tool-approval-card" className="border border-gray-200 rounded-lg p-3 bg-white">
      <div className="flex items-center gap-2 mb-2">
        <span className="font-medium text-sm text-gray-900">{toolName}</span>
        <span data-testid="tool-approval-classification" className={`text-xs px-2 py-0.5 rounded-full border ${badgeClass}`}>
          {classification}
        </span>
        {target && <span className="text-xs text-gray-500 ml-auto">on {target}</span>}
      </div>

      {paramEntries.length > 0 && (
        <dl data-testid="tool-approval-params" className="text-xs text-gray-600 mb-3 space-y-0.5">
          {paramEntries.map(([key, value]) => (
            <div key={key} className="flex gap-1">
              <dt className="font-medium">{key}:</dt>
              <dd className="truncate">{formatParamValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="flex gap-2 justify-end">
        <button
          type="button"
          data-testid="tool-approval-deny"
          onClick={onDeny}
          disabled={busy}
          className="px-3 py-1 text-xs bg-gray-50 hover:bg-gray-100 disabled:opacity-60 text-gray-700 rounded-full border border-gray-200 transition"
        >
          Deny
        </button>
        <button
          type="button"
          data-testid="tool-approval-approve"
          onClick={onApprove}
          disabled={busy}
          className="px-3 py-1 text-xs bg-blue-500 hover:bg-blue-600 disabled:opacity-60 text-white rounded-full transition"
        >
          Approve
        </button>
      </div>
    </div>
  );
}
