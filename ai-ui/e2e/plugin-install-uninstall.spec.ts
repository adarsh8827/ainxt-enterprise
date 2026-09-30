// SPDX-License-Identifier: MIT
// Connectors+Plugins phase, Stage 5 E2E: install a real plugin item ->
// its bundled skill part appears in Yours, tagged and uninstall-locked
// (services/ecosystem/installs_service.py's managed_by_plugin_install_id
// fan-out) -> uninstalling the PLUGIN itself frees the part (individually
// uninstallable again). Same real-Chrome-against-real-backend convention
// as install-state-consistency.spec.ts.
//
// Requires ECOSYSTEM_TYPE_PLUGIN=true on the gateway it runs against
// (default off) -- real .env + docker-compose.yml allowlist + a real
// image rebuild, all landed this round. Run for real, confirmed passing.
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, waitForGateResolved } from './helpers';

async function goToMarketplace(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /^Marketplace/ }).click();
  await expect(page.getByTestId('marketplace-toolbar')).toBeVisible({ timeout: 15_000 });
}

async function createSkillAndPlugin(request: import('@playwright/test').APIRequestContext) {
  const suffix = Math.random().toString(36).slice(2, 10);
  const skillNamespace = `e2e-plugin-test/skill-${suffix}`;
  const pluginNamespace = `e2e-plugin-test/plugin-${suffix}`;

  // Real bug found running this spec for the first time: plugins (unlike
  // skills) never get the private/no-script fast path, so they always run
  // the FULL gate including the ethics stage -- which correctly flagged
  // this fixture's original lazy placeholder text ("d" / "x") as a
  // "meaningless... likely test payload" and failed the gate for real,
  // so the plugin never appeared in Discover at all. Fixed by using
  // realistic-looking content instead of shortening the gate/ethics check.
  const skillResp = await request.post('/ainxt/v1/api/ecosystem/items', {
    data: {
      create_via: 'write', item_type: 'skill', namespace: skillNamespace,
      display_name: `E2E Plugin-Part Skill ${suffix}`,
      description: 'Drafts a short status update summarizing recent project activity.',
      category: 'productivity', tags: [],
      license: 'MIT',
      content: { instructions: 'Summarize the user\'s recent activity in three sentences, in a neutral, professional tone.', files: [] },
      surfaces: ['chat'],
    },
  });
  expect(skillResp.ok(), await skillResp.text()).toBeTruthy();
  const skillBody = await skillResp.json();
  await waitForGateResolved(request, skillBody.item_id);

  // Real design fact found running this spec (NOT a bug --
  // services/ecosystem/installs_service.py's _fan_out_plugin_parts()
  // docstring is explicit: "If an install for that part's item already
  // exists for this caller... this does NOT touch it... ownership is
  // never reassigned"). The private/no-script "write" fast path just
  // used above auto-installs the skill for its own creator immediately,
  // so by the time the plugin's own fan-out runs, the skill already has
  // a standalone (unmanaged) install -- deliberately left alone, per the
  // real, intentional design. To exercise the actual managed-lock
  // behavior this spec is testing, the skill's pre-existing install must
  // be gone before the plugin claims the part, matching the real-world
  // "plugin composed from a skill I never separately installed" case.
  const installsResp = await request.get('/ainxt/v1/api/ecosystem/installs?item_type=skill');
  const ownSkillInstall = ((await installsResp.json()).installs ?? []).find(
    (i: any) => i.item?.id === skillBody.item_id,
  );
  if (ownSkillInstall) {
    const uninstallResp = await request.post(`/ainxt/v1/api/ecosystem/installs/${ownSkillInstall.install_id}/uninstall`);
    expect(uninstallResp.ok(), await uninstallResp.text()).toBeTruthy();
  }

  const pluginResp = await request.post('/ainxt/v1/api/ecosystem/items', {
    data: {
      create_via: 'write', item_type: 'plugin', namespace: pluginNamespace,
      display_name: `E2E Test Plugin ${suffix}`,
      description: 'Bundles the status-update skill for teams that want it pre-installed together.',
      category: 'productivity', tags: [],
      license: 'MIT', content: { parts: { skills: [skillNamespace] } }, surfaces: ['chat'],
    },
  });
  expect(pluginResp.ok(), await pluginResp.text()).toBeTruthy();
  const pluginBody = await pluginResp.json();
  // A plugin's full gate runs several sequential stages (ethics alone
  // observed taking ~5-6s on this machine) -- helpers.ts's 20s default
  // is tuned for a skill's own lighter gate; give the plugin more room.
  await waitForGateResolved(request, pluginBody.item_id, 40_000);

  return { skillDisplayName: `E2E Plugin-Part Skill ${suffix}`, pluginDisplayName: `E2E Test Plugin ${suffix}` };
}

test.describe('Plugin install fans out to a managed, locked child install -- real backend', () => {
  test('install plugin -> part appears tagged+locked in Yours -> uninstall plugin frees it', async ({ page, context }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await loginAs(context, USER_A);
    const { skillDisplayName, pluginDisplayName } = await createSkillAndPlugin(context.request);

    // Real design fact found running this spec (same one this session
    // already found for skills, ai-ui/e2e/install-state-consistency.spec.ts):
    // a private, self-authored `create_via: "write"` item auto-installs its
    // own creator immediately on a pass/warn verdict (CONTRACTS.md §10) and
    // never appears in Discover (Discover surfaces catalog/shared items,
    // not a caller's own private drafts) -- confirmed live via the real API
    // (GET /ecosystem/items?item_type=plugin returned 0 items for this
    // exact plugin, while GET /ecosystem/items/{id} showed it already
    // install_id-set + enabled:true). This spec's own real purpose is the
    // Yours-page fan-out/lock behavior, not Discover browsing -- go there
    // directly rather than fighting Discover's own correct, by-design
    // exclusion of private drafts.
    await goToMarketplace(page);

    // Yours (Skills tab): the bundled skill part shows up as its own
    // install row, uninstall locked because managed_by_plugin_install_id
    // is set.
    await page.getByTestId('view-toggle-yours').click();
    await page.getByTestId('type-tab-skills').click();
    const skillRow = page.locator('[data-testid="yours-install-row"]', { hasText: skillDisplayName });
    await expect(skillRow).toBeVisible({ timeout: 15_000 });
    await skillRow.getByTestId('detail-installed-trigger').click();
    // The popover is portaled to a single page-level root, not a child of
    // skillRow -- page.getByTestId('detail-installed-menu') is already
    // unique (confirmed live: an earlier "14 x locator resolved" log
    // turned out to be Playwright's own retry-attempt count while polling
    // for a real state change, not 14 simultaneous elements -- the real
    // root cause was the fixture-ordering issue fixed above, not locator
    // ambiguity).
    const skillMenu = page.getByTestId('detail-installed-menu');
    const uninstallItem = skillMenu.getByRole('menuitem', { name: /Uninstall/ });
    await expect(uninstallItem).toBeDisabled();
    await expect(skillMenu.getByText(/Managed by (the ".*" plugin|a plugin)\. Uninstall the plugin instead\./)).toBeVisible();
    await page.keyboard.press('Escape');
    await page.screenshot({ path: 'e2e/screenshots/plugin-child-part-locked.png', fullPage: true });

    // Yours (Plugins tab): uninstall the plugin itself -- its own install
    // is NOT managed_by_plugin_install_id, so Uninstall is enabled.
    await page.getByTestId('type-tab-plugins').click();
    const pluginRow = page.locator('[data-testid="yours-install-row"]', { hasText: pluginDisplayName });
    await expect(pluginRow).toBeVisible({ timeout: 15_000 });
    await pluginRow.getByTestId('detail-installed-trigger').click();
    await page.getByTestId('detail-installed-menu').getByRole('menuitem', { name: 'Uninstall' }).click();
    await expect(pluginRow).toHaveCount(0, { timeout: 10_000 });

    // Real design fact found running this for real (not a bug): when the
    // plugin was its part's ONLY claimant, services/ecosystem/
    // installs_service.py's _reconcile_orphaned_plugin_child() doesn't
    // "free but keep" the child -- it actually uninstalls it for real
    // ("else actually uninstall the child for real, publishing its own
    // event/audit row", per that function's own docstring). The original
    // version of this assertion (expecting the skill row to still be
    // present and merely unlocked) never matched the real reconciliation
    // code. Assert the real behavior: the part is gone from Yours too,
    // exactly as if it had never been separately installed.
    await page.getByTestId('type-tab-skills').click();
    const freedSkillRow = page.locator('[data-testid="yours-install-row"]', { hasText: skillDisplayName });
    await expect(freedSkillRow).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: 'e2e/screenshots/plugin-part-freed-after-plugin-uninstall.png', fullPage: true });
  });
});
