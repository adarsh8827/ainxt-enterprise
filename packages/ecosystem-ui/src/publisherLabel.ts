// SPDX-License-Identifier: MIT
// Reference-layout parity (Connectors+Plugins UI redesign, 2026-09-30):
// the reference card design shows "by <Maker>" under every item's
// description. ItemSummary (the card's own data shape) has no dedicated
// publisher/maker field -- only `namespace` ("publisher-slug/name-slug"),
// which already encodes this (e.g. "google/drive" -> "by Google") for
// every real item this catalog has, so a small derivation here avoids
// needing a backend schema change just for this one label. ItemDetail's
// own richer `publisher.slug` (used by ConnectorDetail.tsx's side panel)
// is the more authoritative source where it's already available.
export function publisherLabel(namespace: string): string {
  const slug = namespace.split("/", 1)[0] || namespace;
  return slug
    .split(/[-_]/)
    .filter(Boolean)
    .map((word) => (word[0] ?? "").toUpperCase() + word.slice(1))
    .join(" ");
}
