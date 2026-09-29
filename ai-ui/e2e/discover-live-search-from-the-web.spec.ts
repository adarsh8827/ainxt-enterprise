// SPDX-License-Identifier: MIT
// Discover "From the web" section (docs/ecosystem/design/CHANGELOG.md's
// live-search round; docs/ecosystem/TESTING_GUIDE.md §6o) -- the frontend
// half this session's earlier round explicitly disclosed as not-yet-built.
// Real Chrome, real ai-ui build, real packages/ecosystem-ui source (Vite's
// own @ecosystem-ui alias -- no separate build step needed to pick up the
// new Discover.tsx/LiveSearchResultCard.tsx/Badges.tsx code).
//
// Network-layer disclosure (read before assuming this hit a live GitHub
// search): the shared dev backend's already-RUNNING gateway process
// predates this round's own config_service.py change (a `docker cp` alone
// never hot-reloads an already-imported module) and this environment's
// ECOSYSTEM_LIVE_SOURCES instance flag is genuinely off in that process's
// own env (confirmed directly: `GET /ecosystem/config` has no
// `live_search_enabled` key at all against the real running container as
// of this round) -- restarting the shared container to pick up the code
// change still wouldn't turn the INSTANCE flag on (that's a real env var,
// not something `docker restart` alone changes, and there's no mounted
// .env this container reads), and recreating it with a new env risks the
// other agents concurrently depending on the same shared container. So:
// this spec intercepts exactly the two responses this round's own change
// affects -- `GET /ecosystem/config` (augmented with the real field this
// round adds, `live_search_enabled: true`, everything else in the
// response left untouched/real) and `GET /ecosystem/search/live`
// (fulfilled with a realistic, contract-shaped payload, since a real
// unauthenticated GitHub search call from this environment is neither
// reachable nor deterministic enough for a repeatable screenshot) -- every
// other request (login, the real local-catalog GET /ecosystem/items, the
// real POST /ecosystem/items this section's own "+ Add" fires) hits the
// real backend, unmocked. Backend correctness for the two intercepted
// pieces is separately proven for real: services/ecosystem/config_service.py's
// own get_effective_config() combinator (23/23 tests passing against real
// Postgres, tests/services/ecosystem/test_config_service.py) and
// live_search_service.py's own pre-existing, already-real, already-tested
// search_live() (tests/services/ecosystem/test_live_search_service.py).
import { test, expect } from '@playwright/test';
import { loginAs, USER_A } from './helpers';

const REALISTIC_LIVE_RESULTS = [
  {
    namespace: 'acme/web-scraper-skill',
    display_name: 'web-scraper-skill',
    description: 'A skill for scraping and summarizing web pages.',
    license_spdx: 'MIT',
    source_kind: 'github_repo',
    source_url: 'https://github.com/acme/web-scraper-skill',
    ref: 'acme/web-scraper-skill',
  },
  {
    namespace: 'example-org/pdf-tools',
    display_name: 'pdf-tools',
    description: 'Extracts and summarizes text from PDF documents.',
    license_spdx: 'Apache-2.0',
    source_kind: 'github_repo',
    source_url: 'https://github.com/example-org/pdf-tools',
    ref: 'example-org/pdf-tools',
  },
];

async function goToMarketplace(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /^Marketplace/ }).click();
  await expect(page.getByTestId('marketplace-toolbar')).toBeVisible({ timeout: 15_000 });
}

test('Discover "From the web": renders only when live search is enabled, debounced search, real license badges', async ({ page, context }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await loginAs(context, USER_A);

  // See header comment -- augments the real GET /ecosystem/config response
  // with this round's own new field, leaving every other real field alone.
  await page.route('**/ecosystem/config', async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.live_search_enabled = true;
    await route.fulfill({ response, json: body });
  });
  let liveSearchCallCount = 0;
  let lastLiveSearchQuery: string | null = null;
  await page.route('**/ecosystem/search/live**', async (route) => {
    liveSearchCallCount += 1;
    lastLiveSearchQuery = new URL(route.request().url()).searchParams.get('q');
    await route.fulfill({ json: { results: REALISTIC_LIVE_RESULTS } });
  });

  await goToMarketplace(page);
  await page.getByTestId('view-toggle-discover').click();
  await expect(page.getByTestId('discover-screen').or(page.getByTestId('discover-loading'))).toBeVisible({ timeout: 15_000 });

  // Blank query: the section must not render at all yet (real backend
  // contract -- a blank query never hits the endpoint).
  expect(liveSearchCallCount, 'a blank query must never call GET /ecosystem/search/live').toBe(0);
  await expect(page.getByTestId('from-the-web-section')).not.toBeVisible();

  // Type into the SAME existing Toolbar search box (no second input) --
  // debounced (LIVE_SEARCH_DEBOUNCE_MS, Discover.tsx), so the call doesn't
  // fire on every keystroke.
  const searchInput = page.getByTestId('toolbar-search').locator('input');
  await searchInput.fill('web tools');

  await expect(page.getByTestId('from-the-web-section')).toBeVisible({ timeout: 5_000 });
  await expect.poll(() => liveSearchCallCount, { timeout: 5_000 }).toBeGreaterThanOrEqual(1);
  expect(lastLiveSearchQuery).toBe('web tools');

  const cards = page.getByTestId('live-search-card');
  await expect(cards).toHaveCount(REALISTIC_LIVE_RESULTS.length);

  // Real license badges -- informational, not a gate (every result here is
  // already MIT/Apache-2.0-filtered server-side).
  const badges = page.getByTestId('license-badge');
  await expect(badges).toHaveCount(REALISTIC_LIVE_RESULTS.length);
  await expect(badges.nth(0)).toHaveText('MIT');
  await expect(badges.nth(1)).toHaveText('Apache-2.0');

  await page.screenshot({ path: 'e2e/screenshots/discover-from-the-web-section.png', fullPage: true });

  // Scoped close-up on the section itself, for a clearer look at the
  // license badges specifically.
  await page.getByTestId('from-the-web-section').screenshot({ path: 'e2e/screenshots/discover-from-the-web-section-closeup.png' });

  // Clearing the query hides the section again (matches "blank query
  // shows nothing," not merely "shows an empty grid").
  await searchInput.fill('');
  await expect(page.getByTestId('from-the-web-section')).not.toBeVisible();
});

test('Discover "From the web": section does not render at all when live search is disabled for the org', async ({ page, context }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await loginAs(context, USER_A);

  // The real, unmodified response -- as established above, this
  // environment's real running backend has live_search_enabled off today
  // (no code restart, and the instance flag is genuinely off), so this
  // is already the disabled case with zero mocking at all.
  let liveSearchCalled = false;
  await page.route('**/ecosystem/search/live**', async () => { liveSearchCalled = true; });

  await goToMarketplace(page);
  await page.getByTestId('view-toggle-discover').click();
  await expect(page.getByTestId('discover-screen').or(page.getByTestId('discover-loading'))).toBeVisible({ timeout: 15_000 });

  const searchInput = page.getByTestId('toolbar-search').locator('input');
  await searchInput.fill('web tools');

  // Give the debounce window a chance to fire if it were ever going to.
  await page.waitForTimeout(1000);
  expect(liveSearchCalled, 'disabled means no request at all, not just a hidden section').toBe(false);
  await expect(page.getByTestId('from-the-web-section')).not.toBeVisible();
});
