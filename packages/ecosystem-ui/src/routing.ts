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

export type CreateAction = "new" | "upload" | "import";

export type ParsedRoute =
  | { kind: "root" }
  | { kind: "catalog"; typeSlug: string; action: CreateAction | null; namespace: string | null }
  | { kind: "admin"; screen: string };

const CREATE_ACTIONS: readonly CreateAction[] = ["new", "upload", "import"];

export function parseRoute(path: string): ParsedRoute {
  const segments = path.split("/").filter(Boolean).map((s) => decodeURIComponent(s));
  if (segments.length === 0) return { kind: "root" };

  const [first, ...rest] = segments;
  if (first === "admin") return { kind: "admin", screen: rest[0] ?? "policies" };

  const typeSlug = first as string;
  if (rest.length === 0) return { kind: "catalog", typeSlug, action: null, namespace: null };
  if (rest.length === 1 && (CREATE_ACTIONS as readonly string[]).includes(rest[0] as string)) {
    return { kind: "catalog", typeSlug, action: rest[0] as CreateAction, namespace: null };
  }
  return { kind: "catalog", typeSlug, action: null, namespace: rest.join("/") };
}

export function catalogPath(typeSlug: string): string {
  return `/${typeSlug}`;
}
export function createPath(typeSlug: string, action: CreateAction): string {
  return `/${typeSlug}/${action}`;
}
export function detailPath(typeSlug: string, namespace: string): string {
  return `/${typeSlug}/${namespace}`;
}
export function adminPath(screen: string): string {
  return `/admin/${screen}`;
}
