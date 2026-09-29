// SPDX-License-Identifier: MIT
// Connectors phase (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6):
// inline chat card shown when the model's tool call targets a connector
// the caller hasn't connected yet. Standalone component -- the caller
// wires it into the message list and supplies onConnect (opening the same
// connect flow Discover's own ConnectorCard uses); this file makes no
// fetch calls of its own, matching the read-only chip convention already
// used for the attached-skill chip in Chat.jsx.
export default function ConnectPromptCard({ connectorName, onConnect, connecting = false }) {
  return (
    <div
      data-testid="connect-prompt-card"
      className="flex items-center gap-2 bg-blue-50 border border-blue-200 text-blue-700 text-sm px-3 py-2 rounded-lg"
    >
      <span>
        This needs access to <span className="font-medium">{connectorName}</span>.
      </span>
      <button
        type="button"
        data-testid="connect-prompt-connect-button"
        onClick={onConnect}
        disabled={connecting}
        className="ml-auto px-3 py-1 text-xs bg-blue-500 hover:bg-blue-600 disabled:opacity-60 text-white rounded-full transition"
      >
        {connecting ? "Connecting…" : `Connect ${connectorName}`}
      </button>
    </div>
  );
}
