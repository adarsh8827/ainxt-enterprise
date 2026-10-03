// SPDX-License-Identifier: MIT
// Connector detail page (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1 item 6).
// Reference-layout parity pass (Connectors+Plugins UI redesign,
// 2026-09-30): Connect/Disconnect as a real primary button (was an
// unstyled <button>), "Copy link", Tools as a chip grid (classification
// still conveyed via the same color-coded dot ToolClassificationBadge
// already uses, just compacted into the chip rather than the full text
// badge, kept in each chip's title for anyone hovering/reading via
// assistive tech), a stacked label/value side panel (was a bare <dl>),
// and a lightweight "Related" section (same-category items, client-side --
// see this file's own earlier note: no dedicated "related" endpoint
// exists server-side, so this reuses the ordinary listItems() query
// rather than adding a new backend query just for this section).
import { useEffect, useState } from "react";
import { ArrowTopRightOnSquareIcon, LinkIcon } from "@heroicons/react/24/outline";
import { TrustBadge, VerifiedMark } from "../Badges";
import { ItemIcon } from "../ItemIcon";
import { useEcosystemClient, useHost } from "../lib/context/HostContext";
import { useConfig } from "../lib/hooks/useEcosystemConfig";
import { EcosystemApiError } from "../lib/client/EcosystemClient";
import { adminPath } from "../lib/routing";
import { publisherLabel } from "../lib/publisherLabel";
import { resolveConnectionStatus, setConnectionState, useConnectionOverrideVersion } from "../lib/connectionStore";
import { ToolClassificationBadge } from "./ToolClassificationBadge";
import { Button } from "../Button";
function CopyLinkButton() {
  const [copied, setCopied] = useState(false);
  return <button type="button" data-testid="connector-copy-link" onClick={() => {
    navigator.clipboard?.writeText(window.location.href).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }} className="inline-flex items-center gap-1 bg-none border-none cursor-pointer text-gray-500 hover:text-gray-700 text-sm p-0 transition-colors">
      <LinkIcon width={14} height={14} aria-hidden="true" />
      {copied ? "Copied" : "Copy link"}
    </button>;
}
function SidePanelRow({
  label,
  children
}) {
  return <div className="mb-4">
      <div className="text-xs text-gray-400 uppercase tracking-wide mb-0.5">
        {label}
      </div>
      <div className="text-sm text-gray-900">{children}</div>
    </div>;
}
function RelatedConnectors({
  item
}) {
  const client = useEcosystemClient();
  const [related, setRelated] = useState(null);
  useEffect(() => {
    let alive = true;
    client.listItems({
      item_type: item.item_type,
      category: [item.category],
      limit: 6
    }).then(res => {
      if (!alive) return;
      setRelated(res.items.filter(i => i.id !== item.id).slice(0, 4));
    }).catch(() => {
      if (alive) setRelated([]);
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id, item.category, item.item_type]);
  if (!related || related.length === 0) return null;
  return <div data-testid="connector-related" className="mt-8">
      <h3 className="text-sm text-gray-900">Related</h3>
      <div className="flex flex-col gap-2">
        {related.map(r => <div key={r.id} data-testid="connector-related-row" className="flex items-center gap-2">
            <ItemIcon iconUrl={r.icon_url} namespace={r.namespace} displayName={r.display_name} size={28} />
            <span className="text-sm text-gray-900">{r.display_name}</span>
          </div>)}
      </div>
    </div>;
}
export function ConnectorDetail({
  item
}) {
  const client = useEcosystemClient();
  const {
    router
  } = useHost();
  const config = useConfig();
  useConnectionOverrideVersion();
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    client.listConnections().then(conns => {
      if (!alive) return;
      setStatus(resolveConnectionStatus(item.namespace, conns.find(c => c.connector_ref === item.namespace)));
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.namespace]);

  // Always route through resolveConnectionStatus() rather than falling
  // back to the raw `status` state directly -- the connectionStore
  // override must take priority on every render (a mutation elsewhere on
  // this page, e.g. handleConnect below, updates the store and re-renders
  // via useConnectionOverrideVersion(), but never touches this component's
  // own `status` state). Real bug found live while writing this
  // component's own test: `status ?? resolveConnectionStatus(...)` used
  // the stale fetched value once `status` was non-null, silently ignoring
  // every later override.
  const [connectError, setConnectError] = useState(null);
  const [connectErrorCode, setConnectErrorCode] = useState(null);
  const resolved = resolveConnectionStatus(item.namespace, status ?? undefined);
  const tools = item.manifest?.tools ?? [];
  // Real UX gap found live (2026-09-30): OAUTH_APP_NOT_CONFIGURED is not a
  // transient failure -- clicking "Retry" repeats the exact same request
  // and gets the exact same answer every time, since nothing changes
  // until an admin actually registers the app. Labeling it "Retry" (the
  // same generic label every other connect error gets) reads as "this
  // might work if you click again," which is false for this one specific
  // case, confusing on a normal (non-admin) user's first real run-through.
  const notConfigured = connectErrorCode === "OAUTH_APP_NOT_CONFIGURED";
  const handleConnect = () => {
    setBusy(true);
    setConnectError(null);
    setConnectErrorCode(null);
    const call = resolved.status === "needs_reauth" || resolved.status === "expired" ? client.reconnect(item.namespace) : client.connect(item.namespace);
    call.then(result => {
      if (result.authorize_url) {
        window.location.assign(result.authorize_url);
        return;
      }
      setConnectionState(item.namespace, {
        connector_ref: item.namespace,
        item_id: item.id,
        status: result.status,
        last_connected_at: new Date().toISOString(),
        expires_at: null
      });
    })
    // Real bug found live (2026-09-30): connect() used to always resolve
    // {"status": "connected"} for every native connector (a separate,
    // now-fixed backend bug), so this call never actually rejected in
    // practice -- there was no .catch() here at all. Once connect()
    // started correctly rejecting for real cases (no OAuth client
    // configured, a PAT connector needing manual setup, etc.), every one
    // of those became an uncaught promise rejection that silently broke
    // this button with no feedback shown to the user.
    .catch(err => {
      setConnectError(err instanceof Error ? err.message : "Couldn't connect.");
      setConnectErrorCode(err instanceof EcosystemApiError ? err.code : null);
    }).finally(() => setBusy(false));
  };
  const handleDisconnect = () => {
    setBusy(true);
    setConnectError(null);
    client.disconnect(item.namespace).then(() => setConnectionState(item.namespace, {
      connector_ref: item.namespace,
      item_id: item.id,
      status: "not_connected",
      last_connected_at: null,
      expires_at: null
    })).catch(err => setConnectError(err instanceof Error ? err.message : "Couldn't disconnect.")).finally(() => setBusy(false));
  };
  return <div data-testid="connector-detail">
      <div className="flex justify-end mb-2">
        <CopyLinkButton />
      </div>
      <div className="flex gap-8 flex-wrap">
        <div className="flex-[1_1_480px] min-w-0">
          <div className="flex items-start gap-4 mb-4">
            <ItemIcon iconUrl={item.icon_url} namespace={item.namespace} displayName={item.display_name} size={56} />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h2 className="m-0 text-xl text-gray-900">{item.display_name}</h2>
                <VerifiedMark tier={item.trust_tier} />
              </div>
              <p className="mt-1 mb-0 text-gray-500 text-sm">{item.description}</p>
              <div className="mt-1.5"><TrustBadge tier={item.trust_tier} /></div>
            </div>
            {resolved.status === "connected" ? <Button variant="secondary" data-testid="connector-disconnect" disabled={busy} loading={busy} onClick={handleDisconnect}>
                Disconnect
              </Button> : <Button data-testid="connector-connect" disabled={busy || notConfigured} loading={busy} onClick={handleConnect} title={connectError ?? undefined}>
                {busy ? "Connecting…" : notConfigured ? "Not set up" : connectError ? "Retry" : resolved.status === "needs_reauth" || resolved.status === "expired" ? "Reconnect" : "Connect"}
              </Button>}
          </div>
          {connectError && <p data-testid="connector-connect-error" className="mb-2 mt-0 text-red-600 text-sm">
              {connectError}
            </p>}
          {notConfigured && config.caller_permissions.can_admin_surfaces && <button type="button" data-testid="connector-connect-admin-setup-link" onClick={() => router.navigate(adminPath("oauth-apps"))} className="inline-flex bg-none border-none p-0 mb-4 text-indigo-600 hover:opacity-70 text-sm cursor-pointer underline transition-colors">
              Set up sign-in for {item.display_name} →
            </button>}

          <div data-testid="connector-trust-note" className="p-2 rounded-md bg-amber-50 text-amber-700 text-sm my-4">
            Only connect services you trust — connected tools can read or change data in that service, and the tools it exposes can change over time.
          </div>

          <h3 className="text-sm text-gray-900">Tools</h3>
          {tools.length === 0 ? <p className="text-gray-400 text-sm">No tools listed for this connector yet.</p> :
        // Chip-grid layout (reference parity) -- each chip still carries
        // its OWN real ToolClassificationBadge (not a compressed color
        // dot + a separate generic legend), so a real, per-tool
        // read/write/destructive signal is never lost for the sake of
        // density. data-testid stays "connector-tool-row" -- this
        // module's own pre-existing test asserts on exactly that name.
        <div data-testid="connector-tools-list" className="flex flex-wrap gap-2">
              {tools.map(tool => <span key={tool.name} data-testid="connector-tool-row" title={tool.description} className="inline-flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-full border border-gray-200 bg-gray-50 text-sm text-gray-900">
                  {tool.name}
                  <ToolClassificationBadge classification={tool.classification} />
                </span>)}
            </div>}

          <RelatedConnectors item={item} />
        </div>

        <aside data-testid="connector-side-panel" className="w-60 flex-shrink-0">
          <SidePanelRow label="Made by">{publisherLabel(item.namespace) || item.publisher.slug}</SidePanelRow>
          <SidePanelRow label="Category">{item.category}</SidePanelRow>
          <SidePanelRow label="Sign-in">Required</SidePanelRow>
          {item.source.url && <SidePanelRow label="Connector URL">
              <span className="inline-flex items-center gap-1 break-all font-mono text-xs">
                {item.source.url}
                <ArrowTopRightOnSquareIcon width={12} height={12} aria-hidden="true" className="flex-shrink-0" />
              </span>
            </SidePanelRow>}
        </aside>
      </div>
    </div>;
}