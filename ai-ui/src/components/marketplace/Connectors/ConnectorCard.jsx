// SPDX-License-Identifier: MIT
// Discover card for a connector item -- mirrors Card.tsx's QuickAddButton
// pattern (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6) but reflects
// live ConnectionStatus instead of install state, via connectionStore.ts
// (the connector-status analogue of installStore.ts, same
// cross-tab-consistency treatment this session's own install-state fix
// established as the required pattern for anything with a status that can
// change from another screen/tab).
import { useEffect, useState } from "react";
import { LinkIcon } from "@heroicons/react/24/outline";
import { ItemIcon } from "../ItemIcon";
import { CompatibilityBadge, NewBadge, TrustBadge, VerifiedMark } from "../Badges";
import { useEcosystemClient } from "../lib/context/HostContext";
import { EcosystemApiError } from "../lib/client/EcosystemClient";
import { publisherLabel } from "../lib/publisherLabel";
import { resolveConnectionStatus, setConnectionState, useConnectionOverrideVersion } from "../lib/connectionStore";
const STATUS_LABEL = {
  connected: "Connected",
  needs_reauth: "Needs reconnect",
  expired: "Expired",
  revoked: "Revoked",
  insufficient_scope: "Needs more access",
  not_connected: "Connect",
  connecting: "Connecting…",
  error: "Error"
};
function ConnectButton({
  connectorRef
}) {
  const client = useEcosystemClient();
  useConnectionOverrideVersion();
  const [fetched, setFetched] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [errorCode, setErrorCode] = useState(null);
  // Real UX gap found live (2026-09-30): OAUTH_APP_NOT_CONFIGURED isn't a
  // transient failure -- clicking "Retry" repeats the exact same request
  // and gets the exact same answer every time, since nothing changes
  // until an admin registers the app. See the connector's own Detail page
  // for the real "Set up sign-in" admin link -- this compact card just
  // needs an honest label, not another copy of that link.
  const notConfigured = errorCode === "OAUTH_APP_NOT_CONFIGURED";
  useEffect(() => {
    let alive = true;
    client.listConnections().then(conns => {
      if (!alive) return;
      const found = conns.find(c => c.connector_ref === connectorRef);
      setFetched(resolveConnectionStatus(connectorRef, found));
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectorRef]);
  const status = resolveConnectionStatus(connectorRef, fetched ?? undefined).status;
  const handleClick = e => {
    e.stopPropagation();
    setBusy(true);
    setError(null);
    setErrorCode(null);
    const call = status === "needs_reauth" || status === "expired" ? client.reconnect(connectorRef) : client.connect(connectorRef);
    call.then(result => {
      if (result.authorize_url) {
        setConnectionState(connectorRef, {
          connector_ref: connectorRef,
          item_id: null,
          status: "connecting",
          last_connected_at: null,
          expires_at: null
        });
        window.location.assign(result.authorize_url);
        return;
      }
      setConnectionState(connectorRef, {
        connector_ref: connectorRef,
        item_id: null,
        status: result.status,
        last_connected_at: new Date().toISOString(),
        expires_at: null
      });
    }).catch(err => {
      setError(err instanceof Error ? err.message : "Couldn't connect.");
      setErrorCode(err instanceof EcosystemApiError ? err.code : null);
    }).finally(() => setBusy(false));
  };
  if (status === "connected") {
    return <span data-testid="connector-connected-badge" className="inline-flex items-center gap-1 text-xs text-green-700">
        Connected
      </span>;
  }
  return <button type="button" data-testid="connector-connect-button" data-status={status} disabled={busy} onClick={handleClick} title={error ?? undefined} className={["inline-flex items-center gap-1 px-3 py-2 rounded text-xs font-medium border border-transparent transition-colors", error ? "bg-red-50 text-red-600 hover:opacity-70" : "text-white brand-grad hover:opacity-70", busy ? "cursor-default" : "cursor-pointer"].join(" ")}>
      <LinkIcon width={14} height={14} aria-hidden="true" />
      {busy ? "Connecting…" : notConfigured ? "Not set up" : error ? "Retry" : STATUS_LABEL[status]}
    </button>;
}
export function ConnectorCard({
  item,
  onOpen
}) {
  return <div role="button" tabIndex={0} data-testid="connector-card" data-item-id={item.id} onClick={() => onOpen(item)} onKeyDown={e => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen(item);
    }
  }} className="flex flex-col gap-2 p-4 rounded-xl border border-gray-200 bg-white shadow-sm text-left w-full cursor-pointer transition-colors hover:bg-gray-50">
      {/* Same reference-layout shape as Card.tsx (2026-09-30): icon left,
          name+verified/description/"by maker" as a text column, action
          control pinned top-right of the row -- kept visually consistent
          across skill/plugin (Card.tsx) and connector/mcp_server (this
          component) cards, just swapping install-state for connection-state. */}
      <div className="flex items-start gap-2">
        <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span title={item.display_name} className="block font-semibold text-sm text-gray-900 overflow-hidden text-ellipsis whitespace-nowrap">
              {item.display_name}
            </span>
            <VerifiedMark tier={item.trust_tier} />
          </div>
          <p className="mt-0.5 mb-0 text-sm text-gray-500 overflow-hidden text-ellipsis" style={{
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical"
        }}>
            {item.description}
          </p>
          <span className="block mt-1 text-xs text-gray-400">
            by {publisherLabel(item.namespace)}
          </span>
        </div>
        <div className="flex-shrink-0">
          <ConnectButton connectorRef={item.namespace} />
        </div>
      </div>
      <div className="flex items-center gap-1.5 flex-nowrap overflow-hidden">
        <TrustBadge tier={item.trust_tier} />
        {item.is_new && <NewBadge />}
        <CompatibilityBadge compatibility={item.compatibility} />
      </div>
    </div>;
}