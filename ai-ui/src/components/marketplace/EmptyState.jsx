// SPDX-License-Identifier: MIT
// Task F-6: Yours' empty state -- two CTAs, Discover + Create.
import { Button } from "./Button";
export function EmptyState({
  message,
  onDiscover,
  onCreate
}) {
  return <div data-testid="yours-empty-state" className="text-center py-8 text-gray-500">
      <p>{message}</p>
      <div className="flex gap-2 justify-center mt-4">
        <Button variant="secondary" data-testid="empty-state-discover" onClick={onDiscover}>
          Browse Discover
        </Button>
        <Button data-testid="empty-state-create" onClick={onCreate}>
          Create your own
        </Button>
      </div>
    </div>;
}