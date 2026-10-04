// SPDX-License-Identifier: MIT
// Item 6 follow-up: chat "+" -> "Browse skills" now opens the real
// Marketplace experience (packages/ecosystem-ui's <Marketplace>) inside a
// modal, rather than a second, thinner bespoke browse panel
// (EcosystemBrowseSkillsPanel.jsx, removed). The user asked for this to
// look/feel like the same catalog-browsing UI Marketplace already has --
// Yours/Discover tabs, search/filter/sort, card grid, Add -- instead of a
// flat search-and-list panel duplicating a subset of it.
//
// Self-contained fake router (local useState, not react-router) so
// Marketplace's own Detail-page drill-down (clicking a card) works inside
// the modal without touching the app's URL bar -- this is an overlay, not
// a route. layout="compact" (already a real, tested layout mode -- see
// F-12's workspace-host example) keeps card/toolbar sizing sane at modal
// width rather than full-page width.
import { useMemo, useState } from "react";
import { XMarkIcon } from "@heroicons/react/24/outline";
import { Marketplace as EcosystemMarketplace, RealEcosystemClient, LIGHT_TOKENS } from "./marketplace/index.js";
import { API_BASE } from "../config";

export default function EcosystemBrowseSkillsModal({ onClose, onCreateWithAi }) {
  const [path, setPath] = useState("/");
  const client = useMemo(() => new RealEcosystemClient({ baseUrl: API_BASE }), []);
  const router = useMemo(() => ({ path, navigate: setPath, basePath: "" }), [path]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-[760px] max-w-[95vw] max-h-[85vh] overflow-y-auto bg-white rounded-xl shadow-2xl p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-end mb-1">
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700 rounded-lg hover:bg-gray-100">
            <XMarkIcon width={16} height={16} />
          </button>
        </div>
        <EcosystemMarketplace
          client={client}
          layout="compact"
          theme={LIGHT_TOKENS}
          router={router}
          onCreateWithAi={onCreateWithAi}
        />
      </div>
    </div>
  );
}
