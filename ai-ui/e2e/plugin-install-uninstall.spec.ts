// SPDX-License-Identifier: MIT
// Connectors+Plugins phase, Stage 5 E2E: install a real plugin item ->
// its bundled skill part appears in Yours, tagged and uninstall-locked
// (services/ecosystem/installs_service.py's managed_by_plugin_install_id
// fan-out) -> uninstalling the PLUGIN itself frees the part (individually
// uninstallable again). Same real-Chrome-against-real-backend convention
// as install-state-consistency.spec.ts.
//
// NOTE (disclosed, not silently assumed): this spec requires
// ECOSYSTEM_TYPE_PLUGIN=true on the gateway it runs against (default off).
// docker-compose.override.yml in this repo now carries that flag for local
// verification, but flipping it live requires the gateway container to be
// recreated with the new env AND rebuilt from the current source (a plain
// `docker compose restart` reuses the container's existing environment;
// `docker compose up -d` without `--build` would also lose every change
// made to the running container via `docker cp` during this session that
// was never baked into the image). That rebuild is reserved for this
// project's own planned one-time "final pass" step so it isn't done twice
// -- this spec is written and ready, but has NOT been run against a live
// browser+backend as of this commit. Run it for real once that rebuild
// lands, before treating Stage 5's E2E item as verified.
import { test, expect } from '@playwright/test';
import { loginAs, USER_A } from './helpers';

async function goToMarketplace(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /^Marketplace/ }).click();
  await expect(page.getByTestId('marketplace-toolbar')).toBeVisible({ timeout: 15_000 });
}

async function createSkillAndPlugin(request: import('@playwright/test').APIRequestContext) {
  const suffix = Math.random().toString(36).slice(2, 10);
  const skillNamespace = `e2e-plugin-test/skill-${suffix}`;
  const pluginNamespace = `e2e-plugin-test/plugin-${suffix}`;

  const skillResp = await request.post('/ainxt/v1/api/ecosystem/items', {
    data: {
      create_via: 'write', item_type: 'skill', namespace: skillNamespace,
      display_name: `E2E Plugin-Part Skill ${suffix}`, description: 'd', category: 'productivity', tags: [],
      license: 'MIT', content: { instructions: 'x', files: [] }, surfaces: ['chat'],
    },
  });
  expect(skillResp.ok(), await skillResp.text()).toBeTruthy();

  const pluginResp = await request.post('/ainxt/v1/api/ecosystem/items', {
    data: {
      create_via: 'write', item_type: 'plugin', namespace: pluginNamespace,
      display_name: `E2E Test Plugin ${suffix}`, description: 'd', category: 'productivity', tags: [],
      license: 'MIT', content: { parts: { skills: [skillNamespace] } }, surfaces: ['chat'],
    },
  });
  expect(pluginResp.ok(), await pluginResp.text()).toBeTruthy();

  return { skillDisplayName: `E2E Plugin-Part Skill ${suffix}`, pluginDisplayName: `E2E Test Plugin ${suffix}` };
}

test.describe('Plugin install fans out to a managed, locked child install -- real backend', () => {
  test('install plugin -> part appears tagged+locked in Yours -> uninstall plugin frees it', async ({ page, context }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await loginAs(context, USER_A);
    const { skillDisplayName, pluginDisplayName } = await createSkillAndPlugin(context.request);

    await goToMarketplace(page);
    await page.getByTestId('view-toggle-discover').click();
    await page.getByTestId('type-tab-plugins').click();
    await page.getByTestId('toolbar-search').locator('input').fill(pluginDisplayName);

    const pluginCard = page.locator('[data-testid="item-card"]', { hasText: pluginDisplayName });
    await expect(pluginCard).toBeVisible({ timeout: 15_000 });
    await pluginCard.getByTestId('card-quick-add').click();
    await expect(pluginCard.getByTestId('card-uninstall')).toBeVisible({ timeout: 15_000 });

    // Yours (Skills tab): the bundled skill part shows up as its own
    // install row, uninstall locked because managed_by_plugin_install_id
    // is set.
    await page.getByTestId('view-toggle-yours').click();
    await page.getByTestId('type-tab-skills').click();
    const skillRow = page.locator('[data-testid="yours-install-row"]', { hasText: skillDisplayName });
    await expect(skillRow).toBeVisible({ timeout: 15_000 });
    await skillRow.getByTestId('detail-installed-trigger').click();
    const uninstallItem = page.getByRole('menuitem', { name: /Uninstall/ });
    await expect(uninstallItem).toBeDisabled();
    await expect(page.getByText(/Managed by (the ".*" plugin|a plugin)\. Uninstall the plugin instead\./)).toBeVisible();
    await page.keyboard.press('Escape');
    await page.screenshot({ path: 'e2e/screenshots/plugin-child-part-locked.png', fullPage: true });

    // Yours (Plugins tab): uninstall the plugin itself -- its own install
    // is NOT managed_by_plugin_install_id, so Uninstall is enabled.
    await page.getByTestId('type-tab-plugins').click();
    const pluginRow = page.locator('[data-testid="yours-install-row"]', { hasText: pluginDisplayName });
    await expect(pluginRow).toBeVisible({ timeout: 15_000 });
    await pluginRow.getByTestId('detail-installed-trigger').click();
    await page.getByRole('menuitem', { name: 'Uninstall' }).click();
    await expect(pluginRow).toHaveCount(0, { timeout: 10_000 });

    // The freed skill part is individually uninstallable again now.
    await page.getByTestId('type-tab-skills').click();
    const freedSkillRow = page.locator('[data-testid="yours-install-row"]', { hasText: skillDisplayName });
    await expect(freedSkillRow).toBeVisible({ timeout: 15_000 });
    await freedSkillRow.getByTestId('detail-installed-trigger').click();
    const freedUninstallItem = page.getByRole('menuitem', { name: 'Uninstall' });
    await expect(freedUninstallItem).toBeEnabled();
    await page.screenshot({ path: 'e2e/screenshots/plugin-part-freed-after-plugin-uninstall.png', fullPage: true });
  });
});
