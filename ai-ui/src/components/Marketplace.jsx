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
import { Marketplace as EcosystemMarketplace, RealEcosystemClient, LIGHT_TOKENS } from "./marketplace/index.js";
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
  // BUG-U04 fix: this used to drop `location.search` entirely, so a
  // navigate() call carrying a "?tab=..." deep-link seed (e.g. Yours'
  // "Versions & rollback") landed on the right URL in the address bar but
  // the ecosystem-ui package's own router.path (what parseRoute() actually
  // reads) never saw the query string, silently losing it.
  const relativePath = (location.pathname.startsWith(MOUNT_PATH)
    ? location.pathname.slice(MOUNT_PATH.length) || "/"
    : "/") + location.search;

  const router = useMemo(() => ({
    path: relativePath,
    navigate: (path) => navigate(`${MOUNT_PATH}${path}`),
    basePath: MOUNT_PATH,
  }), [relativePath, navigate]);

  return (
    // The app shell's own route slot (App.jsx) is `h-full overflow-hidden`
    // -- every other route provides its own scroll region (e.g.
    // AgentsCatalog.jsx's "flex-1 overflow-y-auto"), and this one didn't,
    // so Detail/Discover/Yours/long SKILL.md content/CreateForm all got
    // silently clipped at the viewport edge instead of scrolling.
    //
    // User-flow QA round 6 (2026-10-03, real screenshots from the user's
    // own machine): the bottom of every page here -- Yours/Discover's last
    // row, the Edit tab's Save/Cancel buttons -- was getting covered by the
    // user's own OS taskbar, which this page has no way to detect (the
    // browser's own reported viewport height included that strip, so this
    // container correctly judged its content as "fits, no scroll needed" --
    // nothing left to scroll to reveal it). pb-24 wasn't enough on the
    // user's own machine, so bumped to pb-48 (192px) -- deliberately far
    // past any plausible taskbar/browser-chrome edge case, so content
    // flush against the bottom is never anywhere near the literal last
    // pixel on screen.
    <div className="h-full overflow-y-auto px-6 pt-6 pb-48">
      <EcosystemMarketplace
        client={client}
        layout="full"
        theme={LIGHT_TOKENS}
        router={router}
        // Create-with-AI (user-flow QA round 2, 2026-10-03): navigates to
        // the real /marketplace/skills/new/ai page now, not a modal --
        // see CreateSkillWithAiPage.jsx's own header comment for why.
        onCreateWithAi={() => navigate("/marketplace/skills/new/ai")}
      />
    </div>
  );
}
