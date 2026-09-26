// SPDX-License-Identifier: MIT
// Task F-5: full Discover screen -- GET /ecosystem/items, grouped by
// category (config-driven order, never hardcoded), with a featured banner.
import { useEffect, useState } from "react";
import type { ItemSummary, ItemType } from "../types";
import { useConfig } from "../hooks/useEcosystemConfig";
import { useEcosystemClient, useI18n } from "../context/HostContext";
import { FeaturedBanner } from "./FeaturedBanner";
import { CategorySection } from "./CategorySection";

export function Discover({ itemType, onOpen }: { itemType: ItemType; onOpen: (item: ItemSummary) => void }) {
  const client = useEcosystemClient();
  const config = useConfig();
  const strings = useI18n();
  const [items, setItems] = useState<ItemSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    client.listItems({ item_type: itemType, limit: 200, sort: "featured" })
      .then((res) => { if (!cancelled) setItems(res.items); })
      .catch((e) => { if (!cancelled) setError(e); });
    return () => { cancelled = true; };
  }, [client, itemType]);

  if (error) {
    return <div data-testid="discover-error" role="alert">Couldn't load the catalog. Please try again.</div>;
  }
  if (items === null) {
    return <div data-testid="discover-loading">{strings.verifying}</div>;
  }
  if (items.length === 0) {
    return <div data-testid="discover-empty-state">{strings.empty_discover}</div>;
  }

  const byCategory = new Map<string, ItemSummary[]>();
  for (const item of items) {
    const bucket = byCategory.get(item.category) ?? [];
    bucket.push(item);
    byCategory.set(item.category, bucket);
  }

  return (
    <div data-testid="discover-screen">
      <FeaturedBanner items={items} onOpen={onOpen} />
      {config.taxonomy.categories
        .filter((category) => byCategory.has(category))
        .map((category) => (
          <CategorySection key={category} category={category} items={byCategory.get(category) ?? []} onOpen={onOpen} />
        ))}
    </div>
  );
}
