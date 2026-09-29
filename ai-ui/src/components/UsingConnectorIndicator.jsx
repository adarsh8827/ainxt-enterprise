// SPDX-License-Identifier: MIT
// Connectors phase: small "Using <connector>" pill shown while a tool
// call against that connector is in flight during a chat turn -- same
// chip shape/coloring as the attached-skill chip (Chat.jsx), so it reads
// as part of the same visual language rather than a new pattern.
export default function UsingConnectorIndicator({ connectorName }) {
  return (
    <span
      data-testid="using-connector-indicator"
      className="inline-flex items-center gap-1 bg-blue-50 border border-blue-200 text-blue-700 text-xs px-2 py-0.5 rounded-full"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" aria-hidden="true" />
      Using {connectorName}
    </span>
  );
}
