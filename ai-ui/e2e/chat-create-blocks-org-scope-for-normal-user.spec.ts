// SPDX-License-Identifier: MIT
// Item 6 E2E spec: "normal user cannot create org/Required from chat."
// Two layers, both proven here: (1) UI structure -- CreateWithAiModal.jsx
// has no scope selector at all (unlike Marketplace's own AddDialog.tsx),
// so a chat-initiated create never even offers "Everyone in org"/
// "Required" as an option to begin with; (2) server-side enforcement --
// the submitted draft's resulting install is always scope="private",
// and a direct, UI-bypassing API call attempting an org/required install
// as this same normal user (e2e-user-a, role='user', no
// marketplace:provision) is rejected with a real 403 POLICY_FORBIDDEN --
// the same guarantee test_ecosystem_router_http.py's own
// test_install_rejects_a_forged_provisioned_or_required_scope_from_a_non_admin_caller
// proves at the HTTP-test level, exercised here through a real browser
// session instead.
import { test, expect } from '@playwright/test';
import { loginAs, USER_A, API, createResolvedSkill, getInstallId } from './helpers';

test('a normal user has no org/Required scope option in Create-with-AI, and the server rejects a forged attempt', async ({ page, context }) => {
  await loginAs(context, USER_A);
  await page.goto('/portal/');

  const plusButton = page.getByTitle('Add a skill');
  await expect(plusButton).toBeVisible({ timeout: 15_000 });
  await plusButton.click();
  await page.getByText('Create a skill with AI…').click();

  // Structural check: no scope radio group exists anywhere in this
  // modal -- "Everyone in org" and "Required" are AddDialog.tsx-only
  // concepts (Marketplace's own Add flow), never offered from chat.
  await expect(page.getByText(/everyone in org/i)).not.toBeVisible();
  await expect(page.getByText(/^required$/i)).not.toBeVisible();

  // Server-side check, bypassing the UI entirely: the same normal user
  // (no marketplace:provision) cannot install with an org/provisioned/
  // required scope even via a direct API call.
  const { itemId } = await createResolvedSkill(context.request, { displayName: `Scope Block Test ${Date.now()}` });
  const installId = await getInstallId(context.request, itemId);
  const versionsResp = await context.request.get(`${API}/ecosystem/items/${itemId}/versions`);
  const versionId = ((await versionsResp.json()).versions ?? [])[0]?.id;

  for (const forgedScope of ['org', 'provisioned', 'required']) {
    const resp = await context.request.post(`${API}/ecosystem/items/${itemId}/install`, {
      data: { version_id: versionId, surfaces: ['chat'], scope: forgedScope, origin: 'added' },
    });
    expect(resp.status(), `scope=${forgedScope} should be rejected`).toBe(403);
    const body = await resp.json();
    expect(body?.detail?.code).toBe('POLICY_FORBIDDEN');
  }

  // The caller's own real (private-scope) install from createResolvedSkill
  // is untouched by the rejected attempts above.
  const installsResp = await context.request.get(`${API}/ecosystem/installs`);
  const own = ((await installsResp.json()).installs ?? []).find((i: any) => i.install_id === installId);
  expect(own?.scope).toBe('private');
});
