// SPDX-License-Identifier: MIT
// Task F-2: thin host wrapper around packages/ecosystem-ui's <Marketplace />
// -- real EcosystemClient, ai-ui's theme tokens, layout:"full". No business
// logic lives here; everything else moved into packages/ecosystem-ui as
// part of the same rewrite (task F-3's own removal of the old
// localStorage-backed data module and inline components happens together
// with this file, per CONFIG_AND_PRODUCTS.md §11 -- the old data source
// had to keep working until this adapter was ready to swap in, and it's
// ready now).
import { useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Marketplace as EcosystemMarketplace, RealEcosystemClient, LIGHT_TOKENS } from "@ecosystem-ui";
import { API_BASE } from "../config";

const MOUNT_PATH = "/marketplace";

export default function Marketplace() {
  const location = useLocation();
  const navigate = useNavigate();

  const client = useMemo(() => new RealEcosystemClient({ baseUrl: API_BASE }), []);

  // Strip the host's own mount prefix so packages/ecosystem-ui's router.ts
  // parser only ever sees paths relative to it -- it must never assume
  // "/marketplace" itself (host-agnostic by design, see LLD/ui-package.md's
  // Edge cases for the bug this exact assumption caused inside the package
  // before RouterHooks.basePath existed).
  const relativePath = location.pathname.startsWith(MOUNT_PATH)
    ? location.pathname.slice(MOUNT_PATH.length) || "/"
    : "/";

  const router = useMemo(() => ({
    path: relativePath,
    navigate: (path) => navigate(`${MOUNT_PATH}${path}`),
    basePath: MOUNT_PATH,
  }), [relativePath, navigate]);

  return (
    <EcosystemMarketplace
      client={client}
      layout="full"
      theme={LIGHT_TOKENS}
      router={router}
    />
  );
}
