#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real incident, 2026-09-29 (see services/ecosystem/service_health.py's own
header comment): three separate "stale process serving old code" bugs
surfaced as false live bugs in the same session -- most severely, the
`ainxt-gate-worker` container ran 27 hours (predating the priority-lane
feature) while every real Add enqueued into the new `_high`/`_low` lanes,
producing a growing, invisible backlog. Each was only found by manually
inspecting `docker top`/logs/queue depths.

This script is the fix for the *process*, not just that one incident: after
every merge/round, run it once to put the gateway, gate-worker, and
gate-sweeper containers on the exact same, exact-known commit, restart all
three, and print each one's self-reported state (via
services/ecosystem/service_health.get_all_service_health()) so a stale
container is caught immediately instead of discovered hours later as a
"mystery" bug.

Deliberately uses `git archive <commit> | docker exec -i <container> tar -x
-C /app` rather than piecemeal `docker cp` of individual files -- this
session repeatedly found single-file `docker cp` reliable but whole-
directory `docker cp` unreliable (partial copies, stale leftovers). A `git
archive` extraction is atomic-per-file and always reflects exactly the
named commit's tracked tree, nothing more, nothing stale left behind from
a previous sync.

Only manages the three Dockerized ecosystem-critical processes (gateway,
gate-worker, gate-sweeper). It deliberately does NOT touch:
  - catalog sync: not a persistent process -- triggered by the scheduler
    container or an admin's own "Sync now" click, nothing to restart.
  - the `ai-ui` dev server: runs natively (not Dockerized) in whatever
    terminal/worktree the operator started it from. This script cannot
    safely discover or stop an arbitrary native process on the operator's
    machine (a real permission denial this session: killing one by PID
    without the operator's own confirmation is exactly the kind of action
    that requires them, not an automated script, to do it) -- prints a
    reminder instead.

Usage:
    python -m scripts.ecosystem.sync_and_restart_ecosystem_services [--allow-dirty] [--commit REF]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYNC_MARKER_NAME = ".ecosystem_sync_commit"

_CONTAINERS: dict[str, str] = {
    "gateway": "ainxt-gateway",
    "gate_worker": "ainxt-gate-worker",
    "gate_sweeper": "ainxt-gate-sweeper",
}

_HEALTH_POLL_TIMEOUT_S = 180  # gateway startup does a full re-seed (users/agents/skills) -- a real restart took ~70-90s once, live
_HEALTH_POLL_INTERVAL_S = 3


class SyncRestartError(RuntimeError):
    pass


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True, **kwargs)


def _resolve_commit(ref: str) -> str:
    result = _run(["git", "rev-parse", ref])
    if result.returncode != 0:
        raise SyncRestartError(f"could not resolve git ref {ref!r}: {result.stderr.strip()}")
    return result.stdout.strip()


def _check_clean_tree(allow_dirty: bool) -> None:
    result = _run(["git", "status", "--porcelain", "--untracked-files=no"])
    dirty = [line for line in result.stdout.splitlines() if line.strip()]
    if dirty and not allow_dirty:
        raise SyncRestartError(
            "working tree has uncommitted tracked changes -- `git archive` syncs the "
            "COMMITTED tree, so syncing now would silently discard those changes from "
            "every container without them ever landing anywhere:\n" + "\n".join(dirty) +
            "\n\nCommit first, or pass --allow-dirty if this is intentional."
        )


def _container_running(container: str) -> bool:
    result = _run(["docker", "inspect", "-f", "{{.State.Running}}", container])
    return result.returncode == 0 and result.stdout.strip() == "true"


def _sync_commit_into_container(container: str, commit: str) -> None:
    # The runtime image deliberately runs as a non-root `appuser`, with
    # /app owned root:root, mode 0755 (least-privilege hardening -- the
    # app process itself should never be able to rewrite its own code).
    # `docker exec` defaults to that same non-root user, so a plain `tar
    # -x` into /app fails with EACCES on every existing file. `-u root`
    # is scoped to this one sync operation only -- the container's own
    # running app process is untouched and stays non-root.
    archive = subprocess.Popen(
        ["git", "archive", commit], cwd=_REPO_ROOT, stdout=subprocess.PIPE,
    )
    extract = subprocess.Popen(
        ["docker", "exec", "-u", "root", "-i", container, "tar", "-x", "-C", "/app"],
        stdin=archive.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    archive.stdout.close()
    _, extract_err = extract.communicate()
    archive.wait()
    if archive.returncode != 0:
        raise SyncRestartError(f"{container}: `git archive {commit}` failed (exit {archive.returncode})")
    if extract.returncode != 0:
        raise SyncRestartError(f"{container}: tar extraction failed (exit {extract.returncode}): {extract_err.strip()}")

    marker = _run([
        "docker", "exec", "-u", "root", container, "sh", "-c",
        f"printf '%s' {commit} > /app/{_SYNC_MARKER_NAME}",
    ])
    if marker.returncode != 0:
        raise SyncRestartError(f"{container}: failed to write {_SYNC_MARKER_NAME}: {marker.stderr.strip()}")


def _restart_container(container: str) -> None:
    result = _run(["docker", "restart", container])
    if result.returncode != 0:
        raise SyncRestartError(f"{container}: `docker restart` failed: {result.stderr.strip()}")


def _wait_for_gateway_health(container: str) -> None:
    deadline = time.monotonic() + _HEALTH_POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        result = _run(["docker", "exec", container, "curl", "-sf", "http://localhost:8000/ainxt/v1/api/health"])
        if result.returncode == 0:
            return
        time.sleep(_HEALTH_POLL_INTERVAL_S)
    raise SyncRestartError(f"{container}: did not become healthy within {_HEALTH_POLL_TIMEOUT_S}s of restart")


def _wait_for_self_report(service_name: str, expected_commit: str) -> None:
    deadline = time.monotonic() + _HEALTH_POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        report = _fetch_service_health()
        info = report.get("services", {}).get(service_name)
        if info is not None and info.get("commit") == expected_commit:
            return
        time.sleep(_HEALTH_POLL_INTERVAL_S)
    raise SyncRestartError(
        f"{service_name}: did not self-report commit {expected_commit!r} within "
        f"{_HEALTH_POLL_TIMEOUT_S}s of restart -- it may still be starting, or it never "
        f"reached the report_service_startup() call at all."
    )


def _fetch_service_health() -> dict:
    result = _run([
        "docker", "exec", _CONTAINERS["gateway"], "python", "-c",
        "import json; from services.ecosystem.service_health import get_all_service_health; print(json.dumps(get_all_service_health()))",
    ])
    if result.returncode != 0:
        raise SyncRestartError(f"failed to read back service health from the gateway container: {result.stderr.strip()}")
    import json as _json

    return _json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-dirty", action="store_true", help="sync even if the working tree has uncommitted tracked changes")
    parser.add_argument("--commit", default="HEAD", help="git ref to sync (default: HEAD)")
    parser.add_argument(
        "--only", choices=list(_CONTAINERS), nargs="+", default=None,
        help="restart only these services (default: all three)",
    )
    args = parser.parse_args()

    targets = {name: _CONTAINERS[name] for name in (args.only or _CONTAINERS)}

    try:
        _check_clean_tree(args.allow_dirty)
        commit = _resolve_commit(args.commit)
        print(f"Syncing commit {commit} into: {', '.join(targets.values())}")

        for name, container in targets.items():
            if not _container_running(container):
                raise SyncRestartError(f"{container}: not running -- start it before syncing (this script never starts a stopped container)")
            print(f"  [{name}] syncing files ({container}) ...")
            _sync_commit_into_container(container, commit)
            print(f"  [{name}] restarting ({container}) ...")
            _restart_container(container)

        for name, container in targets.items():
            print(f"  [{name}] waiting for it to come back up ...")
            if name == "gateway":
                _wait_for_gateway_health(container)
            _wait_for_self_report(name, commit)

        print("\nFinal self-reported state:")
        report = _fetch_service_health()
        for name, info in report["services"].items():
            if info is None:
                print(f"  {name}: NEVER REPORTED")
            else:
                flag = " <-- COMMIT MISMATCH" if info.get("commit_mismatch") else ""
                print(f"  {name}: commit={info['commit']} started_at={info['started_at']}{flag}")
        if report["warnings"]:
            print("\nWarnings:")
            for w in report["warnings"]:
                print(f"  - {w}")
        else:
            print("\nNo warnings -- all synced services report a matching commit.")

        print(
            "\nReminder: catalog sync has no persistent process to restart (triggered by "
            "the scheduler or an admin's own 'Sync now'). If the ai-ui dev server is "
            "running, restart it yourself in its own terminal -- this script does not "
            "manage native (non-Docker) processes."
        )
        return 0
    except SyncRestartError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
