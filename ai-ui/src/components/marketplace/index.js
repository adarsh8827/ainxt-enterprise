// SPDX-License-Identifier: MIT
// Public API of the marketplace feature (formerly @ainxt/ecosystem-ui,
// folded into ai-ui directly -- see MIGRATION_NOTES.md). Host code (just
// Marketplace.jsx and EcosystemBrowseSkillsModal.jsx) imports only from
// this file -- internal component paths are not a stable contract.
export { Marketplace } from "./MarketplaceScreen";

export { EcosystemApiError } from "./lib/client/EcosystemClient";
export { RealEcosystemClient } from "./lib/client/RealEcosystemClient";
export { MockEcosystemClient } from "./lib/client/MockEcosystemClient";
export { MOCK_CONFIG, MOCK_CONFIG_WORKSPACE, MOCK_ITEMS, MOCK_DETAILS } from "./lib/client/fixtures";

export { LIGHT_TOKENS, DARK_TOKENS, tokensToCssVars } from "./lib/theme";
export { ROUTE_SLUGS } from "./lib/types";
