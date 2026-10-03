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
  const segments = path.split("/").filter(Boolean).map(s => decodeURIComponent(s));
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
    namespace: rest.join("/")
  };
}
export function catalogPath(typeSlug) {
  return `/${typeSlug}`;
}
export function createPath(typeSlug, action) {
  return `/${typeSlug}/${action}`;
}
export function detailPath(typeSlug, namespace) {
  return `/${typeSlug}/${namespace}`;
}
export function adminPath(screen) {
  return `/admin/${screen}`;
}