// SPDX-License-Identifier: MIT
// Item-state model for a catalog item (docs/ecosystem/design/LLD/gate.md's
// "Catalog-checking round" section, feature/ecosystem-external-sources
// commit 5b362bb): "no new top-level state enum field was added -- the
// existing signals already say everything a card needs, just read
// together." This is that one shared read, so Card.tsx/Detail.tsx (and
// anything else that needs it later) never re-derive it slightly
// differently from each other.
import type { ItemSummary } from "./types";

/** True for a catalog item nobody has added yet: `item_scope ===
 * "central_index"` (crawled/synced, pointer-only until someone installs
 * it) AND `latest_version === null` (materialize_from_catalog() hasn't
 * run -- no EcosystemItemVersion, and therefore no gate run, exists yet).
 * Per the contract, this state must show "Catalog checks passed" + "+ Add"
 * -- NEVER "Verifying" (nothing is being verified; the crawler's own
 * fast-path scan at crawl time is what already passed) and never
 * "Retry" (that's reserved for a failed INSTALL ATTEMPT, which by
 * definition can't have happened yet here either). */
export function isNotYetAddedCatalogItem(item: Pick<ItemSummary, "item_scope" | "latest_version">): boolean {
  return item.item_scope === "central_index" && item.latest_version === null;
}
