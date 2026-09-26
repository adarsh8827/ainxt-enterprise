// SPDX-License-Identifier: MIT
// Shared setup for the M5 Ecosystem Marketplace E2E specs. Arranges test
// state via the real API (fast, deterministic) so each spec's own
// Playwright actions can focus on the UI behavior actually under test —
// standard "arrange via API, act+assert via UI" split.
//
// Requires: a real backend with ENABLE_ECOSYSTEM_MARKETPLACE=true and
// ECOSYSTEM_CHAT_SKILLS=true, a running gate-worker, and the two fixed
// test users created by scripts/ecosystem/seed_e2e_test_users.py (same
// org, "e2e-test-org") — see docs/ecosystem/TESTING_GUIDE.md's
// Playwright section for full setup.
import type { APIRequestContext, BrowserContext } from '@playwright/test';
import { expect } from '@playwright/test';

export const API = '/ainxt/v1/api';

export const USER_A = {
  email: 'e2e-user-a@ainxt.local',
  password: process.env.E2E_USER_A_PASSWORD || 'E2E-test-password-A-1!',
};
export const USER_B = {
  email: 'e2e-user-b@ainxt.local',
  password: process.env.E2E_USER_B_PASSWORD || 'E2E-test-password-B-1!',
};

/** Logs in via the real API — the JWT cookie lands in `context`'s cookie
 * jar automatically, so any `page` opened from this context is already
 * authenticated on first navigation (no need to drive the Login screen). */
export async function loginAs(context: BrowserContext, user: { email: string; password: string }) {
  const resp = await context.request.post(`${API}/auth/login`, {
    data: { email: user.email, password: user.password },
  });
  expect(resp.ok(), `login failed for ${user.email}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
  return resp;
}

function uniqueSuffix() {
  return `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
}

/** Creates a skill via POST /ecosystem/items (create_via: write) and waits
 * for the real gate to resolve it out of "verifying". Returns the item id
 * and the namespace used, so a spec can navigate straight to its Detail
 * page or slash-command it in chat. */
export async function createResolvedSkill(
  request: APIRequestContext,
  opts: { orgSlug?: string; license?: string; displayName?: string } = {},
): Promise<{ itemId: string; namespace: string }> {
  const suffix = uniqueSuffix();
  const namespace = `${opts.orgSlug ?? 'e2e-test-org'}/e2e-skill-${suffix}`;
  const createResp = await request.post(`${API}/ecosystem/items`, {
    data: {
      create_via: 'write', item_type: 'skill', namespace,
      display_name: opts.displayName ?? `E2E Skill ${suffix}`,
      description: 'Created by a Playwright E2E spec.', category: 'productivity',
      tags: [], license: opts.license ?? 'MIT',
      content: { instructions: 'Say hello.', files: [] }, surfaces: ['chat'],
    },
  });
  expect(createResp.ok(), await createResp.text()).toBeTruthy();
  const body = await createResp.json();
  const itemId = body.item_id as string;

  await waitForGateResolved(request, itemId);
  return { itemId, namespace };
}

/** Polls GET /ecosystem/items/{id} until latest_verdict leaves "pending"
 * (or the timeout elapses) — the real gate-worker transition. NOTE:
 * `status` alone is NOT a reliable signal here -- it can already read
 * "active" immediately after creation, before the gate-worker has even
 * picked up the job, since it isn't solely derived from the gate
 * verdict. `latest_verdict` is the field that actually reflects
 * gate-worker completion (pending -> pass/warn/fail). Found the hard way
 * while writing this spec's own setup -- see docs/ecosystem/design/
 * CHANGELOG.md's M5 test-suite entry. */
export async function waitForGateResolved(request: APIRequestContext, itemId: string, timeoutMs = 20_000) {
  const start = Date.now();
  let last: any = null;
  while (Date.now() - start < timeoutMs) {
    const resp = await request.get(`${API}/ecosystem/items/${encodeURIComponent(itemId)}`);
    if (resp.ok()) {
      last = await resp.json();
      if (last.latest_verdict !== 'pending') return last;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`gate never resolved for item ${itemId} within ${timeoutMs}ms (last verdict: ${last?.latest_verdict})`);
}

export async function getInstallId(request: APIRequestContext, itemId: string): Promise<string> {
  const resp = await request.get(`${API}/ecosystem/installs`);
  expect(resp.ok(), await resp.text()).toBeTruthy();
  const body = await resp.json();
  // NOTE: GET /ecosystem/installs returns bare `item_id`, not a nested
  // `item: ItemSummary` object -- despite CONTRACTS.md §9 and
  // packages/ecosystem-ui/src/types.ts's Install type both documenting
  // one. This is a real, disclosed, pre-existing gap (services/ecosystem/
  // installs_service.py's list_installs(), task B-10/M2, out of this
  // milestone's own scope) -- see docs/ecosystem/design/CHANGELOG.md's
  // M5 test-suite entry. Yours.tsx crashes on this for the same reason;
  // this helper works around it by using the field that actually exists.
  const install = (body.installs ?? []).find((i: any) => i.item_id === itemId);
  if (!install) throw new Error(`no install found for item ${itemId}`);
  return install.install_id;
}
