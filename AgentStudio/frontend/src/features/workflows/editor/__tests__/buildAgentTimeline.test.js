// SPDX-License-Identifier: MIT
// Task B-23: "missing dependency" surfacing. buildAgentTimeline is the pure
// reducer that turns the raw execution-log stream (one entry per SSE event)
// into the rows the thinking-timeline UI renders. These tests cover the
// reducer only -- the SSE-parsing branches that call addExecutionLog(...)
// with `missingDependencies: data.data?.missing_dependencies || null` are
// exercised end-to-end by AgentStudio/backend/tests/test_missing_dependency_signal.py
// plus manual verification (backend emits the field; this reducer consumes it).
import { buildAgentTimeline } from '../ChatPanel.jsx';

describe('buildAgentTimeline missing-dependency handling (task B-23)', () => {
  it('carries no missingDependencies when the log entry has none (flag-off / nothing missing)', () => {
    const steps = buildAgentTimeline([
      { type: 'agent_start', agent: 'Researcher', nodeId: 'n1', missingDependencies: null },
    ], null);
    expect(steps).toHaveLength(1);
    expect(steps[0].missingDependencies).toEqual([]);
  });

  it('carries the missing tool names through onto the matching agent step', () => {
    const steps = buildAgentTimeline([
      { type: 'agent_start', agent: 'Researcher', nodeId: 'n1', missingDependencies: ['acme/removed-skill'] },
    ], null);
    expect(steps).toHaveLength(1);
    expect(steps[0].agent).toBe('Researcher');
    expect(steps[0].missingDependencies).toEqual(['acme/removed-skill']);
  });

  it('refreshes missingDependencies on each loop round instead of accumulating stale entries', () => {
    const steps = buildAgentTimeline([
      { type: 'loop_iter', nodeId: 'loop-1', mode: 'count', total: 2, index: 0 },
      { type: 'agent_start', agent: 'Worker', nodeId: 'n1', missingDependencies: ['tool-a'] },
      { type: 'agent_complete', agent: 'Worker', nodeId: 'n1' },
      { type: 'loop_iter', nodeId: 'loop-1', mode: 'count', total: 2, index: 1 },
      { type: 'agent_start', agent: 'Worker', nodeId: 'n1', missingDependencies: [] },
    ], null);
    const workerRows = steps.filter((s) => s.kind === 'agent' && s.agent === 'Worker');
    expect(workerRows).toHaveLength(1);
    expect(workerRows[0].missingDependencies).toEqual([]);
  });
});
