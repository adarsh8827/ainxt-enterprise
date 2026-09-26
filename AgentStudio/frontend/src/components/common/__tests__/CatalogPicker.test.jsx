// SPDX-License-Identifier: MIT
// Task B-24: CatalogPicker.jsx merges Ecosystem-sourced skills client-side
// when ECOSYSTEM_AGENTSTUDIO_SKILLS is on -- GET /skills-catalog and its
// response shape are never touched by this task.
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import CatalogPicker from '../CatalogPicker.jsx';

const NATIVE_SKILL = { name: 'native_skill', description: 'a native AgentStudio skill', is_usable: true };
const ECOSYSTEM_CAPABILITIES = {
    surface: 'agent_studio',
    skills: [
        { namespace: 'acme/exec-assistant', display_name: 'Exec Assistant', description: 'an ecosystem skill', slash_command: '/exec-assistant' },
    ],
    plugins: [], connectors: [], mcp_tools: [],
};

function mockFetchFor(url) {
    if (url.includes('/ecosystem/capabilities')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(ECOSYSTEM_CAPABILITIES) });
    }
    if (url.includes('/skills-catalog')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ skills: [NATIVE_SKILL] }) });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
}

async function openPicker() {
    const trigger = await screen.findByRole('button', { name: /add skill/i });
    fireEvent.click(trigger);
}

describe('CatalogPicker (task B-24)', () => {
    beforeEach(() => {
        global.fetch = vi.fn((url) => mockFetchFor(String(url)));
    });

    afterEach(() => {
        vi.unstubAllEnvs();
        vi.restoreAllMocks();
    });

    it('flag off: only the native catalog loads, zero ecosystem network calls, behavior unchanged', async () => {
        vi.stubEnv('VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS', 'false');
        render(<CatalogPicker kind="skills" attached={[]} onChange={() => {}} />);

        await openPicker();
        await waitFor(() => expect(screen.getByText('native_skill')).toBeInTheDocument());

        expect(screen.queryByText('acme/exec-assistant')).not.toBeInTheDocument();
        expect(screen.queryByText('Marketplace')).not.toBeInTheDocument();
        const calledUrls = global.fetch.mock.calls.map((c) => String(c[0]));
        expect(calledUrls.some((u) => u.includes('/ecosystem/capabilities'))).toBe(false);
    });

    it('flag on: both native and ecosystem-sourced skills appear, the latter badged', async () => {
        vi.stubEnv('VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS', 'true');
        render(<CatalogPicker kind="skills" attached={[]} onChange={() => {}} />);

        await openPicker();
        await waitFor(() => expect(screen.getByText('native_skill')).toBeInTheDocument());
        await waitFor(() => expect(screen.getByText('acme/exec-assistant')).toBeInTheDocument());

        expect(screen.getByText('Marketplace')).toBeInTheDocument();
    });

    it('flag on but kind="tools": ecosystem merge never fires (skills-only feature)', async () => {
        vi.stubEnv('VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS', 'true');
        render(<CatalogPicker kind="tools" attached={[]} onChange={() => {}} />);

        await waitFor(() => expect(global.fetch).toHaveBeenCalled());
        const calledUrls = global.fetch.mock.calls.map((c) => String(c[0]));
        expect(calledUrls.some((u) => u.includes('/ecosystem/capabilities'))).toBe(false);
    });

    it('picking an ecosystem-sourced skill calls onChange with it, attaching it exactly like a native one', async () => {
        vi.stubEnv('VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS', 'true');
        const onChange = vi.fn();
        render(<CatalogPicker kind="skills" attached={[]} onChange={onChange} />);

        await openPicker();
        const ecoOption = await screen.findByText('acme/exec-assistant');
        fireEvent.click(ecoOption.closest('button'));
        fireEvent.click(screen.getByRole('button', { name: /add selected/i }));

        expect(onChange).toHaveBeenCalledWith([
            expect.objectContaining({ name: 'acme/exec-assistant', _ecosystemSourced: true }),
        ]);

        // Picking an ecosystem-sourced skill must never write to
        // AgentStudio's own skills_catalog/skill_files -- the picker only
        // ever calls onChange() with an in-memory object; it issues no
        // POST of its own for this action regardless of which list the
        // skill came from.
        const postCalls = global.fetch.mock.calls.filter(([, opts]) => opts?.method === 'POST');
        expect(postCalls).toHaveLength(0);
    });

    it('degrades silently when the ecosystem endpoint fails -- native picker still works', async () => {
        vi.stubEnv('VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS', 'true');
        global.fetch = vi.fn((url) => {
            if (String(url).includes('/ecosystem/capabilities')) return Promise.reject(new Error('network down'));
            return mockFetchFor(String(url));
        });
        render(<CatalogPicker kind="skills" attached={[]} onChange={() => {}} />);

        await openPicker();
        await waitFor(() => expect(screen.getByText('native_skill')).toBeInTheDocument());
        expect(screen.queryByText('acme/exec-assistant')).not.toBeInTheDocument();
    });
});
