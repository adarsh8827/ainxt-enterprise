// SPDX-License-Identifier: MIT
// Task F-1: the root component -- the full host-injection prop set
// (client, config, router hooks, theme tokens, layout, i18n strings).
import { useCallback } from "react";
import type { EcosystemClient } from "./client/EcosystemClient";
import type { EcosystemConfig, ItemSummary, ItemType, TrustTier } from "./types";
import { HostProvider, useHost, type I18nStrings, type RouterHooks } from "./context/HostContext";
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

  if (route.kind === "admin") return <AdminScreen screen={route.screen} />;

  if (route.kind === "root") {
    const defaultSlug = config.item_types[0]?.slug ?? "skills";
    navigateToCatalog(defaultSlug);
    return null;
  }

  const typeConfig = config.item_types.find((t) => t.slug === route.typeSlug);
  const itemType = typeSlugLookup[route.typeSlug] as ItemType | undefined;

  // Unknown type / coming-soon: TypeTabs stays visible so the caller can
  // still switch away, but neither state reaches the full Toolbar
  // (search/filter/sort/view-switch have no real list to act on yet).
  if (!typeConfig || !itemType) {
    return (
      <div data-testid="marketplace-root">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <TypeTabs activeSlug={route.typeSlug} onSelect={navigateToCatalog} />
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
      ) : (
        <CatalogScreen
          itemType={itemType}
          typeSlug={route.typeSlug}
          onOpen={navigateToItem}
          onCreate={() => router.navigate(createPath(route.typeSlug, "new"))}
          onSelectType={navigateToCatalog}
          onCreateAction={(action) => router.navigate(createPath(route.typeSlug, action))}
          onCreateWithAi={onCreateWithAi}
        />
      )}
    </div>
  );
}
