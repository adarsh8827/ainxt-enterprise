// SPDX-License-Identifier: MIT
// Task F-13: PUT/DELETE /ecosystem/featured/{item_id} -- an org can pin or
// unpin an item as featured for its own Discover page independent of the
// platform-level ecosystem_items.is_featured flag (CONFIG_AND_PRODUCTS.md
// §7 item 6).
import { useState } from "react";
import { useEcosystemClient } from "../lib/context/HostContext";
import { Button } from "../Button";
const inputClass = "w-full bg-white border border-gray-300 rounded px-3 py-2 text-sm text-gray-900 focus:outline-none focus-visible:outline-none! focus:border-indigo-300";
export function AdminFeatured() {
  const client = useEcosystemClient();
  const [itemId, setItemId] = useState("");
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const run = action => {
    if (!itemId.trim()) return;
    setSubmitting(true);
    setError(null);
    const call = action === "feature" ? client.setFeatured(itemId, true) : client.clearFeaturedOverride(itemId);
    call.then(() => setStatus(action === "feature" ? "Featured for your org." : "Override removed -- reverted to the platform default.")).catch(e => setError(e instanceof Error ? e.message : "Couldn't update the featured override.")).finally(() => setSubmitting(false));
  };
  return <div data-testid="admin-featured">
      <h2 className="text-xl text-gray-900">Featured overrides</h2>
      <input data-testid="admin-featured-item-id" value={itemId} onChange={e => setItemId(e.target.value)} placeholder="item id" className={[inputClass, "mb-2"].join(" ")} />
      <div className="flex gap-2">
        <Button data-testid="admin-featured-set" disabled={submitting} onClick={() => run("feature")}>
          Feature for org
        </Button>
        <Button variant="secondary" data-testid="admin-featured-clear" disabled={submitting} onClick={() => run("clear")}>
          Remove override
        </Button>
      </div>
      {status && <p data-testid="admin-featured-status" className="text-green-700">{status}</p>}
      {error && <p role="alert" className="text-red-600">{error}</p>}
    </div>;
}
