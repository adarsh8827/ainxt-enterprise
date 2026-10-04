// SPDX-License-Identifier: MIT
// This package deliberately does not depend on react-router-dom (or any
// specific router library) -- a host injects a path string + navigate()
// function (context/HostContext.tsx's RouterHooks) and this file parses
// that path itself, matching CONTRACTS.md §2's route shape:
//   /:typeSlug                 -> catalog (Discover/Yours toggle, local state)
//   /:typeSlug/new             -> CreateForm
//   /:typeSlug/upload          -> UploadFlow
//   /:typeSlug/import          -> ImportFlow
//   /:typeSlug/<namespace>     -> Detail (namespace itself may contain "/")
//   /admin/<screen>            -> Admin UI (task F-13; route shape not
//                                 pinned by CONTRACTS.md/CONFIG_AND_PRODUCTS.md,
//                                 a reasonable choice made here and disclosed)

const CREATE_ACTIONS = ["new", "upload", "import"];
export function parseRoute(path) {
  // "?tab=..." is a one-time deep-link seed for Detail's initial tab only
  // (BUG-U04 fix) -- Detail itself still switches tabs via local state,
  // never by navigating/mutating this query string, so the "tabs are
  // conditional rendering, not route changes" contract is unaffected once
  // the page has loaded.
  const [rawPath, queryString] = path.split("?");
  const segments = rawPath.split("/").filter(Boolean).map(s => decodeURIComponent(s));
  if (segments.length === 0) return {
    kind: "root"
  };
  const [first, ...rest] = segments;
  if (first === "admin") return {
    kind: "admin",
    screen: rest[0] ?? "policies"
  };
  const typeSlug = first;
  if (rest.length === 0) return {
    kind: "catalog",
    typeSlug,
    action: null,
    namespace: null
  };
  if (rest.length === 1 && CREATE_ACTIONS.includes(rest[0])) {
    return {
      kind: "catalog",
      typeSlug,
      action: rest[0],
      namespace: null
    };
  }
  return {
    kind: "catalog",
    typeSlug,
    action: null,
    namespace: rest.join("/"),
    initialTab: new URLSearchParams(queryString ?? "").get("tab") || null
  };
}
export function catalogPath(typeSlug) {
  return `/${typeSlug}`;
}
export function createPath(typeSlug, action) {
  return `/${typeSlug}/${action}`;
}
export function detailPath(typeSlug, namespace, initialTab) {
  const base = `/${typeSlug}/${namespace}`;
  return initialTab ? `${base}?tab=${encodeURIComponent(initialTab)}` : base;
}
export function adminPath(screen) {
  return `/admin/${screen}`;
}