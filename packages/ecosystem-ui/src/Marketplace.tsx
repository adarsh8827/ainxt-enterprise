// SPDX-License-Identifier: MIT
// Task F-1: the root component -- the full host-injection prop set
// (client, config, router hooks, theme tokens, layout, i18n strings).
import { useCallback, useEffect, useState } from "react";
import type { EcosystemClient } from "./client/EcosystemClient";
import type { EcosystemConfig, ItemSummary, ItemType, McpRuntimeInstance, TrustTier } from "./types";
import { HostProvider, useHost, useEcosystemClient, type I18nStrings, type RouterHooks } from "./context/HostContext";
import type { ThemeTokens } from "./theme";
import { EcosystemConfigProvider, useConfigState, useTypeSlugLookup } from "./hooks/useEcosystemConfig";
import { parseRoute, catalogPath, createPath, detailPath, type CreateAction } from "./routing";
import { TypeTabs } from "./components/TypeTabs";
import { Toolbar } from "./components/Toolbar";
import { CatalogScreen } from "./components/CatalogScreen";
import { ComingSoonTab } from "./components/ComingSoonTab";
import { Detail } from "./components/Detail";
import { CreateForm } from "./components/create/CreateForm";
import { UploadFlow } from "./components/create/UploadFlow";
import { ImportFlow } from "./components/create/ImportFlow";
import { AdminScreen } from "./components/admin/AdminScreen";
import { AdvancedMcpServers } from "./components/Connectors/AdvancedMcpServers";
import { EcosystemErrorBoundary } from "./components/ErrorBoundary";

// Stable, shared empty-set references for the coming-soon Toolbar below
// (which never mutates them) -- avoids a new Set() on every render.
const EMPTY_CATEGORIES: Set<string> = new Set();
const EMPTY_TRUST: Set<TrustTier> = new Set();

export interface MarketplaceProps {
  client: EcosystemClient;
  layout: "full" | "compact";
  router: RouterHooks;
  theme?: ThemeTokens;
  strings?: I18nStrings;
  /** Optional pre-fetched config, e.g. if the host already called
   * GET /ecosystem/config for its own purposes (nav badges, etc.) -- skips
   * this package's own fetch when supplied. */
  config?: EcosystemConfig;
  /** Opens the host's own Create-with-AI flow (e.g. ai-ui's
   * CreateWithAiModal, already built for the chat surface, task F-11 --
   * this package has no LLM-backed draft-generation UI of its own, by
   * design, matching how create-with-ai's chat entry point is also
   * host-specific). The "Create with AI" entry in AddMenu only renders at
   * all when this is supplied AND config.features.create_with_ai is on --
   * omitted entirely for a host that doesn't wire it up, never a dead
   * button. */
  onCreateWithAi?: () => void;
  /** Detail's Overview tab "Try in chat" button (UI-polish round) --
   * this package has no chat surface of its own, same reasoning as
   * onCreateWithAi above. Omitted entirely for a host that doesn't wire
   * it up, never a dead button. */
  onTryInChat?: () => void;
}

export function Marketplace(props: MarketplaceProps) {
  return (
    <HostProvider value={{ client: props.client, layout: props.layout, router: props.router, theme: props.theme, strings: props.strings }}>
      <EcosystemConfigProvider initialConfig={props.config}>
        <EcosystemErrorBoundary>
          <MarketplaceBody onCreateWithAi={props.onCreateWithAi} onTryInChat={props.onTryInChat} />
        </EcosystemErrorBoundary>
      </EcosystemConfigProvider>
    </HostProvider>
  );
}

function MarketplaceBody({ onCreateWithAi, onTryInChat }: { onCreateWithAi?: () => void; onTryInChat?: () => void }) {
  const { config, loading, error } = useConfigState();

  if (error) return <div data-testid="marketplace-error" role="alert">Couldn't load the marketplace. Please try again.</div>;
  if (loading || !config) return <div data-testid="marketplace-loading">Loading…</div>;

  return <RouteSwitch config={config} onCreateWithAi={onCreateWithAi} onTryInChat={onTryInChat} />;
}

function RouteSwitch({ config, onCreateWithAi, onTryInChat }: { config: EcosystemConfig; onCreateWithAi?: () => void; onTryInChat?: () => void }) {
  const router = useHost().router;
  const typeSlugLookup = useTypeSlugLookup();
  const route = parseRoute(router.path);

  const navigateToCatalog = useCallback((slug: string) => router.navigate(catalogPath(slug)), [router]);
  const navigateToItem = useCallback((item: ItemSummary) => {
    const slug = config.route_slugs[item.item_type] ?? item.item_type;
    router.navigate(detailPath(slug, item.namespace));
  }, [router, config]);

  // Connectors phase item 5: collapse "connector"+"mcp_server" into one
  // "Connectors" tab + an "Advanced: MCP servers" sub-view, gated on the
  // SAME per-caller RBAC signal (caller_permissions.can_admin_surfaces)
  // already used for every other admin-only "Advanced" surface-override
  // elsewhere in this package -- not a new backend flag. Fails closed:
  // an absent/undefined value (matches CallerPermissions' own optionality)
  // is `false`, same as every other consumer of this field.
  const collapseConnectorsAdvanced = Boolean(config.caller_permissions.can_admin_surfaces);
  const connectorSlug = config.item_types.find((t) => t.type === "connector")?.slug;
  // Existence-only (not state) -- matches TypeTabs.tsx's own identical
  // check. The Advanced sub-view is gated on the admin/dev
  // collapseConnectorsAdvanced capability, not on mcp_server's own
  // coming_soon/available state: an admin/dev is exactly who should be
  // able to configure and test MCP servers before ECOSYSTEM_TYPE_MCP is
  // flipped on for everyone else (see TypeTabs.test.tsx's own existing,
  // deliberately-written regression coverage for this).
  const mcpServerType = config.item_types.find((t) => t.type === "mcp_server");
  const [advancedActive, setAdvancedActive] = useState(false);

  const currentTypeSlug = route.kind === "catalog" ? route.typeSlug : null;
  useEffect(() => {
    // Leaving the connectors tab (or the whole feature being off) always
    // resets the sub-view -- Advanced must never silently persist onto an
    // unrelated tab the caller navigates to next.
    if (!collapseConnectorsAdvanced || currentTypeSlug !== connectorSlug) {
      setAdvancedActive(false);
    }
  }, [collapseConnectorsAdvanced, connectorSlug, currentTypeSlug]);

  if (route.kind === "admin") return <AdminScreen screen={route.screen} />;

  if (route.kind === "root") {
    const defaultSlug = config.item_types[0]?.slug ?? "skills";
    navigateToCatalog(defaultSlug);
    return null;
  }

  // Advanced sub-view active on the (collapsed) connectors tab: swap the
  // rendered CONTENT for AdvancedMcpServers' own admin panel (add-form +
  // local/stdio server list) while the tab bar still shows "Connectors" as
  // the active tab (TypeTabs' own toggle button reflects advancedActive
  // separately) -- this is a content swap, never a real navigation
  // (matches TypeTabs' own header comment). typeConfig/itemType stay
  // pointed at "connector" throughout; AdvancedMcpServers is not a
  // Discover/Yours catalog browser, it's a distinct admin panel.
  const showingAdvanced = collapseConnectorsAdvanced && advancedActive && route.typeSlug === connectorSlug && Boolean(mcpServerType);

  const typeConfig = config.item_types.find((t) => t.slug === route.typeSlug);
  const itemType = typeSlugLookup[route.typeSlug] as ItemType | undefined;

  // Unknown type / coming-soon: TypeTabs stays visible so the caller can
  // still switch away, but neither state reaches the full Toolbar
  // (search/filter/sort/view-switch have no real list to act on yet).
  if (!typeConfig || !itemType) {
    return (
      <div data-testid="marketplace-root">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <TypeTabs
            activeSlug={route.typeSlug}
            onSelect={navigateToCatalog}
            collapseConnectorsAdvanced={collapseConnectorsAdvanced}
            advancedActive={advancedActive}
            onSelectAdvanced={setAdvancedActive}
          />
        </div>
        <div data-testid="marketplace-unknown-type">Unknown item type.</div>
      </div>
    );
  }

  if (typeConfig.state === "coming_soon") {
    // Same header/toolbar row as every other tab (UI-polish round) --
    // search disabled, filter/sort hidden (nothing to search/filter/sort
    // yet), type tabs/Yours-Discover switch/Add stay exactly where they
    // always are. `view` here is local, cosmetic-only state -- a
    // coming-soon type has no real Discover/Yours data to switch between.
    return (
      <div data-testid="marketplace-root">
        <Toolbar
          activeSlug={route.typeSlug}
          onSelectType={navigateToCatalog}
          view="discover"
          onSelectView={() => {}}
          query=""
          onQueryChange={() => {}}
          categories={EMPTY_CATEGORIES}
          onCategoriesChange={() => {}}
          trust={EMPTY_TRUST}
          onTrustChange={() => {}}
          sort="featured"
          onSortChange={() => {}}
          onSelectCreateAction={(action: CreateAction) => router.navigate(createPath(route.typeSlug, action))}
          onCreateWithAi={onCreateWithAi}
          searchDisabled
          hideFilterSort
          collapseConnectorsAdvanced={collapseConnectorsAdvanced}
          advancedActive={advancedActive}
          onSelectAdvanced={setAdvancedActive}
        />
        <ComingSoonTab itemType={itemType as "plugin" | "connector" | "mcp_server"} />
      </div>
    );
  }

  // Detail/CreateForm/UploadFlow/ImportFlow are drill-in screens -- no
  // Toolbar, matching the reference mock's own renderDetail() (a back-link
  // row only, never header()/tabs/search/add-menu). CatalogScreen (the list
  // page) owns the full Toolbar itself -- see components/Toolbar.tsx.
  return (
    <div data-testid="marketplace-root">
      {route.namespace ? (
        <Detail idOrNamespace={route.namespace} typeSlug={route.typeSlug} onBack={() => navigateToCatalog(route.typeSlug)} onTryInChat={onTryInChat} />
      ) : route.action === "new" ? (
        <CreateForm itemType={itemType} canProvision={config.features.provisioning && config.caller_permissions.can_provision} onCreated={(id) => router.navigate(detailPath(route.typeSlug, id))} onCancel={() => navigateToCatalog(route.typeSlug)} />
      ) : route.action === "upload" ? (
        <UploadFlow itemType={itemType} onUploaded={(id) => router.navigate(detailPath(route.typeSlug, id))} onCancel={() => navigateToCatalog(route.typeSlug)} />
      ) : route.action === "import" ? (
        <ImportFlow itemType={itemType} onImported={(id) => router.navigate(detailPath(route.typeSlug, id))} onCancel={() => navigateToCatalog(route.typeSlug)} />
      ) : showingAdvanced ? (
        <div data-testid="marketplace-advanced-mcp">
          <Toolbar
            activeSlug={route.typeSlug}
            onSelectType={navigateToCatalog}
            view="discover"
            onSelectView={() => {}}
            query=""
            onQueryChange={() => {}}
            categories={EMPTY_CATEGORIES}
            onCategoriesChange={() => {}}
            trust={EMPTY_TRUST}
            onTrustChange={() => {}}
            sort="featured"
            onSortChange={() => {}}
            onSelectCreateAction={(action: CreateAction) => router.navigate(createPath(route.typeSlug, action))}
            onCreateWithAi={onCreateWithAi}
            searchDisabled
            hideFilterSort
            collapseConnectorsAdvanced={collapseConnectorsAdvanced}
            advancedActive={advancedActive}
            onSelectAdvanced={setAdvancedActive}
          />
          <AdvancedMcpServersPanel />
        </div>
      ) : (
        <CatalogScreen
          itemType={itemType}
          typeSlug={route.typeSlug}
          onOpen={navigateToItem}
          onCreate={() => router.navigate(createPath(route.typeSlug, "new"))}
          onSelectType={navigateToCatalog}
          onCreateAction={(action) => router.navigate(createPath(route.typeSlug, action))}
          onCreateWithAi={onCreateWithAi}
          collapseConnectorsAdvanced={collapseConnectorsAdvanced}
          advancedActive={advancedActive}
          onSelectAdvanced={setAdvancedActive}
        />
      )}
    </div>
  );
}

/** Fetches the real local/stdio MCP server list (GET /ecosystem/admin/
 * mcp-runtime, Stage 3) once on mount -- kept as its own small component
 * so RouteSwitch itself stays free of this fetch's loading state.
 * listMcpRuntimeInstances() is admin-only server-side; a non-admin caller
 * never reaches this render path at all (collapseConnectorsAdvanced is
 * false for them), so a 403 here would be a real bug, not an expected
 * case -- still degrades to an empty list rather than crashing the whole
 * Advanced sub-view if it somehow happens (e.g. a permission changed
 * mid-session). */
function AdvancedMcpServersPanel() {
  const client = useEcosystemClient();
  const [instances, setInstances] = useState<McpRuntimeInstance[]>([]);

  useEffect(() => {
    let cancelled = false;
    client.listMcpRuntimeInstances()
      .then((rows) => { if (!cancelled) setInstances(rows); })
      .catch(() => { if (!cancelled) setInstances([]); });
    return () => { cancelled = true; };
  }, [client]);

  return (
    <AdvancedMcpServers
      localServers={instances.map((i) => ({
        name: i.package_ref, status: i.status, last_health_check: i.last_health_check_at,
      }))}
    />
  );
}
