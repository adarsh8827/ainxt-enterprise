# SPDX-License-Identifier: MIT
# ============================================================
# Gate stage 7 — MCP/connector checks (docs/ecosystem/SKILLS_PHASE_PLAN.md
# task B-9; docs/ecosystem/ECOSYSTEM_PLAN.md §6 stage 7).
#
# item_type == "skill" stays an always-pass no-op, byte-identical to
# before this change -- do not touch that branch.
#
# For item_type in ("connector", "mcp_server") (docs/ecosystem/
# CONNECTORS_PHASE_PLAN.md §1 item 5), real checks:
#   (a) every declared URL (manifest["connector_url"] / manifest["server_url"]
#       / any url found under manifest["endpoints"]) must be a public https://
#       address -- reuses the same SSRF guard the external-import adapters
#       already use, rather than inventing a second one.
#   (b) if the manifest declares oauth (manifest["oauth"] truthy), the
#       protected-resource metadata for that URL must actually be
#       reachable -- reuses credential_broker_service's existing discovery
#       function, never re-implemented here.
#   (c) every declared tool (manifest["tools"], a list of tool-def dicts) is
#       run through mcp.tool_annotations.classify_tool() -- classify_tool()
#       always returns *something* (defaulting to "write" when unclassified,
#       per that module's own conservative-by-design contract), so an
#       unclassifiable tool is logged as an 'info' finding, never a 'block'.
# ============================================================

from __future__ import annotations

from typing import Any

from services.ecosystem.gate.types import Finding, StageResult

_URL_MANIFEST_KEYS = ("connector_url", "server_url")


def _collect_declared_urls(manifest: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in _URL_MANIFEST_KEYS:
        value = manifest.get(key)
        if isinstance(value, str) and value:
            urls.append(value)
    endpoints = manifest.get("endpoints")
    if isinstance(endpoints, list):
        urls.extend(e for e in endpoints if isinstance(e, str) and e)
    elif isinstance(endpoints, dict):
        urls.extend(v for v in endpoints.values() if isinstance(v, str) and v)
    return urls


def run(item_type: str, manifest: dict[str, Any]) -> StageResult:
    if item_type not in ("connector", "mcp_server"):
        return StageResult(verdict="pass", findings=[])

    findings: list[Finding] = []

    from services.ecosystem.import_adapters.ssrf_guard import assert_safe_https_url
    from services.ecosystem.errors import ImportFetchError

    for url in _collect_declared_urls(manifest):
        try:
            assert_safe_https_url(url)
        except ImportFetchError as exc:
            findings.append(Finding(
                stage="mcp_connector", severity="block", code="UNSAFE_CONNECTOR_URL",
                message=f"declared URL {url!r} failed the SSRF/HTTPS-only check: {exc}",
                details={"url": url},
            ))

    if manifest.get("oauth"):
        oauth_cfg = manifest["oauth"] if isinstance(manifest["oauth"], dict) else {}
        resource_url = oauth_cfg.get("resource_url") or (
            manifest.get("connector_url") or manifest.get("server_url")
        )
        if not resource_url:
            findings.append(Finding(
                stage="mcp_connector", severity="block", code="OAUTH_RESOURCE_URL_MISSING",
                message="manifest declares oauth but has no connector_url/server_url/oauth.resource_url to discover protected-resource metadata against",
                details={},
            ))
        else:
            try:
                from services.ecosystem.credential_broker_service import (
                    CredentialBrokerError, discover_protected_resource_metadata,
                )

                discover_protected_resource_metadata(resource_url)
            except ImportFetchError as exc:
                findings.append(Finding(
                    stage="mcp_connector", severity="block", code="UNSAFE_CONNECTOR_URL",
                    message=f"oauth resource_url {resource_url!r} failed the SSRF/HTTPS-only check: {exc}",
                    details={"url": resource_url},
                ))
            except CredentialBrokerError as exc:
                findings.append(Finding(
                    stage="mcp_connector", severity="block", code="OAUTH_METADATA_UNREACHABLE",
                    message=f"protected-resource metadata for {resource_url!r} is not reachable: {exc}",
                    details={"url": resource_url},
                ))

    tools = manifest.get("tools")
    if isinstance(tools, list):
        from mcp.tool_annotations import classify_tool

        for tool_def in tools:
            if not isinstance(tool_def, dict):
                continue
            annotation = classify_tool(tool_def)
            if annotation.source == "default":
                findings.append(Finding(
                    stage="mcp_connector", severity="info", code="TOOL_CLASSIFICATION_DEFAULTED",
                    message=f"tool {annotation.tool_name!r} has no read/write/destructive hint -- classified conservatively as {annotation.classification!r}",
                    details={"tool_name": annotation.tool_name},
                ))

    if any(f.severity == "block" for f in findings):
        verdict = "fail"
    elif any(f.severity == "warn" for f in findings):
        verdict = "warn"
    else:
        verdict = "pass"
    return StageResult(verdict=verdict, findings=findings)
