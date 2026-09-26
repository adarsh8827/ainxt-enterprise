// SPDX-License-Identifier: MIT
// Task F-1: the root component -- the full host-injection prop set
// (client, config, router hooks, theme tokens, layout, i18n strings).
import { useCallback } from "react";
import type { EcosystemClient } from "./client/EcosystemClient";
import type { EcosystemConfig, ItemSummary, ItemType } from "./types";
import { HostProvider, useHost, type I18nStrings, type RouterHooks } from "./context/HostContext";
import type { ThemeTokens } from "./theme";
import { EcosystemConfigProvider, useConfigState, useTypeSlugLookup } from "./hooks/useEcosystemConfig";
import { parseRoute, catalogPath, createPath, detailPath, type CreateAction } from "./routing";
import { TypeTabs } from "./components/TypeTabs";
import { AddMenu } from "./components/AddMenu";
import { CatalogScreen } from "./components/CatalogScreen";
import { ComingSoonTab } from "./components/ComingSoonTab";
import { Detail } from "./components/Detail";
import { CreateForm } from "./components/create/CreateForm";
import { UploadFlow } from "./components/create/UploadFlow";
import { ImportFlow } from "./components/create/ImportFlow";
import { AdminScreen } from "./components/admin/AdminScreen";

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
}

export function Marketplace(props: MarketplaceProps) {
  return (
    <HostProvider value={{ client: props.client, layout: props.layout, router: props.router, theme: props.theme, strings: props.strings }}>
      <EcosystemConfigProvider initialConfig={props.config}>
        <MarketplaceBody />
      </EcosystemConfigProvider>
    </HostProvider>
  );
}

function MarketplaceBody() {
  const { config, loading, error } = useConfigState();

  if (error) return <div data-testid="marketplace-error" role="alert">Couldn't load the marketplace. Please try again.</div>;
  if (loading || !config) return <div data-testid="marketplace-loading">Loading…</div>;

  return <RouteSwitch config={config} />;
}

function RouteSwitch({ config }: { config: EcosystemConfig }) {
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

  return (
    <div data-testid="marketplace-root">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <TypeTabs activeSlug={route.typeSlug} onSelect={navigateToCatalog} />
        <AddMenu activeSlug={route.typeSlug} onSelect={(action: CreateAction) => router.navigate(createPath(route.typeSlug, action))} />
      </div>

      {!typeConfig || !itemType ? (
        <div data-testid="marketplace-unknown-type">Unknown item type.</div>
      ) : typeConfig.state === "coming_soon" ? (
        <ComingSoonTab itemType={itemType as "plugin" | "connector" | "mcp_server"} />
      ) : route.namespace ? (
        <Detail idOrNamespace={route.namespace} typeSlug={route.typeSlug} onBack={() => navigateToCatalog(route.typeSlug)} />
      ) : route.action === "new" ? (
        <CreateForm itemType={itemType} canProvision={config.features.provisioning} onCreated={(id) => router.navigate(detailPath(route.typeSlug, id))} onCancel={() => navigateToCatalog(route.typeSlug)} />
      ) : route.action === "upload" ? (
        <UploadFlow itemType={itemType} onUploaded={(id) => router.navigate(detailPath(route.typeSlug, id))} onCancel={() => navigateToCatalog(route.typeSlug)} />
      ) : route.action === "import" ? (
        <ImportFlow itemType={itemType} onImported={(id) => router.navigate(detailPath(route.typeSlug, id))} onCancel={() => navigateToCatalog(route.typeSlug)} />
      ) : (
        <CatalogScreen itemType={itemType} onOpen={navigateToItem} onCreate={() => router.navigate(createPath(route.typeSlug, "new"))} />
      )}
    </div>
  );
}
