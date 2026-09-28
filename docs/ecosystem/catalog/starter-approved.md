# Marketplace starter catalog — approved and imported

The initial Discover-catalog starter set (community tier, not org-wide auto-provisioned). Each item was imported via `scripts/ecosystem/admin_import.py`'s `starter` batch (pinned commit SHA, full 7-stage gate, license inheritance verified against the actual source content — not a caller-declared claim) and reviewed for provenance and neutrality before approval.

One candidate reviewed for this batch was excluded: its content extensively named specific AI products/vendors throughout, a direct violation of this platform's neutrality requirement. Excluded before import, not part of the 8 below.

| Skill | Source (pinned) | Category | License | Compatibility | Gate verdict |
|---|---|---|---|---|---|
| code-review-and-quality | `addyosmani/agent-skills@2686b620#skills/code-review-and-quality` | engineering | MIT | works in chat | pass |
| security-and-hardening | `addyosmani/agent-skills@2686b620#skills/security-and-hardening` | engineering | MIT | needs file/terminal tools | pass |
| documentation-and-adrs | `addyosmani/agent-skills@2686b620#skills/documentation-and-adrs` | engineering | MIT | needs file/terminal tools | pass |
| api-and-interface-design | `addyosmani/agent-skills@2686b620#skills/api-and-interface-design` | engineering | MIT | works in chat | pass |
| postmortem-writing | `wshobson/agents@9b15b34b#plugins/incident-response/skills/postmortem-writing` | operations | MIT | works in chat | warn — instructions reference an external file not bundled with the skill; see finding below |
| incident-runbook-templates | `wshobson/agents@9b15b34b#plugins/incident-response/skills/incident-runbook-templates` | operations | MIT | needs file/terminal tools | pass |
| sql-optimization-patterns | `wshobson/agents@9b15b34b#plugins/developer-essentials/skills/sql-optimization-patterns` | engineering | MIT | works in chat | warn — instructions appear truncated mid-sentence; see finding below |
| diagnosing-bugs | `mattpocock/skills@c55ee460#skills/engineering/diagnosing-bugs` | engineering | MIT | works in chat | pass |

## Warn findings (real, not fixed — upstream content issue, not a platform bug)

- **postmortem-writing**: `ETHICS_REVIEW_FLAGGED` — the skill's instructions appear to be truncated mid-content (a table is cut off) and reference an external reference file. Still usable; flagged for visibility, not blocked.
- **sql-optimization-patterns**: `ETHICS_REVIEW_FLAGGED` — the instructions appear truncated mid-sentence, suggesting incomplete content in the source repository at the pinned commit. Still usable; flagged for visibility, not blocked.

Both are upstream content quality issues in the source repositories at the specific pinned commits, not platform defects — re-pinning to a later upstream commit (if one exists that completes the content) is a future catalog-maintenance action, not tracked here.

## How this was imported

```
docker exec ainxt-gateway python -m scripts.ecosystem.admin_import starter \
  --org-id <org_id> --created-by <user_id>
```

See `docs/ecosystem/TESTING_GUIDE.md` §6a.1 for the full command reference and negative-case verification, and `docs/ecosystem/design/CHANGELOG.md`'s dated entries for why this admin-only, in-container command exists (a prior host-side script wrote imported object bytes to a location the gate-worker could never see).
