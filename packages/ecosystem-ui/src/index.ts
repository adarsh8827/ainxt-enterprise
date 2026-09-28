// SPDX-License-Identifier: MIT
// Public API of @ainxt/ecosystem-ui (task F-1). Host apps import only from
// this file -- internal component paths are not a stable contract.
export { Marketplace, type MarketplaceProps } from "./Marketplace";

export type { EcosystemClient } from "./client/EcosystemClient";
export { EcosystemApiError } from "./client/EcosystemClient";
export { RealEcosystemClient, type RealEcosystemClientOptions } from "./client/RealEcosystemClient";
export { MockEcosystemClient, type MockEcosystemClientOptions } from "./client/MockEcosystemClient";
export { MOCK_CONFIG, MOCK_CONFIG_WORKSPACE, MOCK_ITEMS, MOCK_DETAILS } from "./client/fixtures";

export { LIGHT_TOKENS, DARK_TOKENS, tokensToCssVars, type ThemeTokens } from "./theme";
export type { RouterHooks, I18nStrings } from "./context/HostContext";

export * from "./types";
