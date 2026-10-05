// SPDX-License-Identifier: MIT
// Task F-13: PUT/DELETE /ecosystem/featured/{item_id} -- an org can pin or
// unpin an item as featured for its own Discover page independent of the
// platform-level ecosystem_items.is_featured flag (CONFIG_AND_PRODUCTS.md
// §7 item 6).
import { useState } from "react";
import { useEcosystemClient } from "../lib/context/HostContext";
import { Button } from "../Button";
import { ItemPicker } from "./ItemPicker";
import { useOptionalToast } from "../lib/useOptionalToast";
export function AdminFeatured() {
  const client = useEcosystemClient();
  const toast = useOptionalToast();
  const [selectedItem, setSelectedItem] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const itemId = selectedItem?.id ?? "";
  const run = action => {
    if (!itemId) return;
    setSubmitting(true);
    setError(null);
    const call = action === "feature" ? client.setFeatured(itemId, true) : client.clearFeaturedOverride(itemId);
    call.then(() => {
      const message = action === "feature" ? "Featured for your org." : "Override removed -- reverted to the platform default.";
      setStatus(message);
      toast.success(message);
    }).catch(e => {
      const message = e instanceof Error ? e.message : "Couldn't update the featured override.";
      setError(message);
      toast.error(message);
    }).finally(() => setSubmitting(false));
  };
  return <div data-testid="admin-featured">
      <h2 className="text-xl font-semibold text-gray-900 mb-3">Featured overrides</h2>
      <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
        <div className="mb-3">
          <ItemPicker value={selectedItem} onChange={item => {
          setSelectedItem(item);
          setStatus(null);
          setError(null);
        }} testId="admin-featured-item" />
        </div>
        <div className="flex gap-2">
          <Button data-testid="admin-featured-set" disabled={submitting || !itemId} onClick={() => run("feature")}>
            Feature for org
          </Button>
          <Button variant="secondary" data-testid="admin-featured-clear" disabled={submitting || !itemId} onClick={() => run("clear")}>
            Remove override
          </Button>
        </div>
        {status && <p data-testid="admin-featured-status" className="text-green-700 mt-2">{status}</p>}
        {error && <p role="alert" className="text-red-600 mt-2">{error}</p>}
      </div>
    </div>;
}
