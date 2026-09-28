# Marketplace starter catalog — approved and imported

The initial Discover-catalog starter set (community tier, not org-wide auto-provisioned). Each item was imported via `scripts/ecosystem/admin_import.py`'s `starter` batch (pinned commit SHA, full 7-stage gate, license inheritance verified against the actual source content — not a caller-declared claim) and reviewed for provenance and neutrality before approval.

One candidate reviewed for this batch was excluded: its content extensively named specific AI products/vendors throughout, a direct violation of this platform's neutrality requirement. Excluded before import, not part of the 8 below.

| Skill | Source (pinned) | Category | License | Compatibility | Gate verdict |
|---|---|---|---|---|---|
| code-review-and-quality | `addyosmani/agent-skills@2686b620#skills/code-review-and-quality` | engineering | MIT | works in chat | pass |
| security-and-hardening | `addyosmani/agent-skills@2686b620#skills/security-and-hardening` | engineering | MIT | needs file/terminal tools | pass |
| documentation-and-adrs | `addyosmani/agent-skills@2686b620#skills/documentation-and-adrs` | engineering | MIT | needs file/terminal tools | pass |
| api-and-interface-design | `addyosmani/agent-skills@2686b620#skills/api-and-interface-design` | engineering | MIT | works in chat | pass |
| postmortem-writing | `wshobson/agents@9b15b34b#plugins/incident-response/skills/postmortem-writing` | operations | MIT | works in chat | warn — ethics-reviewer false positive, content verified complete; see finding below |
| incident-runbook-templates | `wshobson/agents@9b15b34b#plugins/incident-response/skills/incident-runbook-templates` | operations | MIT | needs file/terminal tools | pass |
| sql-optimization-patterns | `wshobson/agents@9b15b34b#plugins/developer-essentials/skills/sql-optimization-patterns` | engineering | MIT | works in chat | warn — ethics-reviewer false positive, content verified complete; see finding below |
| diagnosing-bugs | `mattpocock/skills@c55ee460#skills/engineering/diagnosing-bugs` | engineering | MIT | works in chat | pass |

## Warn findings — verified false positives, not a platform bug, content confirmed complete

Both `ETHICS_REVIEW_FLAGGED` findings claimed the content was truncated mid-sentence/mid-table. Investigated directly (2026-09-28): fetched both skills' `SKILL.md` and bundled `references/details.md` straight from GitHub at the exact pinned commit and byte-compared against what's actually stored in our object storage — **byte-identical in all four cases** (no length difference, no diff at any offset). Our fetch/import pipeline did not truncate anything.

What actually happened: both `SKILL.md` files use a legitimate "progressive disclosure" pattern — a short navigation-tier document that explicitly defers detail to a bundled reference file (e.g. "Detailed pattern documentation lives in `references/details.md`. Read that file when the navigation tier above is insufficient."). The ethics-reviewer LLM misread that intentional deferral as if the document itself had been cut off mid-sentence, when in fact both files are complete, well-formed, and end cleanly. This is a probabilistic model judgment call, not a deterministic bug — no code fix applies; re-gating would not change the outcome since the input content is unchanged and correct. Both skills are safe and usable as-is; the `warn` (not `block`) severity already reflects that this never blocked anything.

## How this was imported

```
docker exec ainxt-gateway python -m scripts.ecosystem.admin_import starter \
  --org-id <org_id> --created-by <user_id>
```

See `docs/ecosystem/TESTING_GUIDE.md` §6a.1 for the full command reference and negative-case verification, and `docs/ecosystem/design/CHANGELOG.md`'s dated entries for why this admin-only, in-container command exists (a prior host-side script wrote imported object bytes to a location the gate-worker could never see).
