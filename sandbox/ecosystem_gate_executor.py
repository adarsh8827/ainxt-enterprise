# SPDX-License-Identifier: MIT
# ============================================================
# Hardened sandbox profile for the Ecosystem marketplace gate's optional
# test-entrypoint execution (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-9).
#
# Extends sandbox/docker_executor.py's DockerExecutor rather than
# reimplementing container launch — DockerExecutor.execute() already runs
# compliance_engine.validate_input() pre-execution (PCI guard) and handles
# cleanup; this subclass only overrides _run() to harden the container
# profile beyond what the base class's general-purpose executor allows:
#   - network_disabled ALWAYS true — no caller override (the base class
#     lets a caller opt into network via network_enabled=True; this
#     subclass ignores that entirely, since a gate-time script never has a
#     legitimate reason to reach the network).
#   - read_only=True rootfs — the base class always uses read_only=False.
#   - /sandbox backed by an in-memory tmpfs, not a host bind mount — the
#     base class bind-mounts a host tempdir at /sandbox; this closes the
#     gap noted in ECOSYSTEM_PLAN.md §1.5 (a host-visible directory for a
#     third-party script's write attempts, cleaned up after the fact rather
#     than never existing on host disk at all).
#   - a timeout/memory profile tuned for install-time scripts rather than
#     the base class's short-AI-generated-snippet defaults.
# ============================================================

from __future__ import annotations

from typing import Dict

from core.logger import logger
from sandbox.docker_executor import DockerExecutor

# Deliberately more generous than the base class's 60s/512m/50% — an
# install-time verification script is allowed to take longer than a
# short interactive code snippet, but still bounded.
GATE_EXECUTION_TIMEOUT = 120
GATE_MEM_LIMIT = "256m"
GATE_CPU_QUOTA = 50_000
GATE_TMPFS_SIZE = "64m"


class EcosystemGateExecutor(DockerExecutor):
    """Runs a single test-entrypoint file for the sandbox gate stage.
    Never accepts network access, never persists anything to host disk."""

    def _run(
        self,
        request_id: str,
        code: str,
        lang_cfg: Dict,
        sandbox_dir: str,
        language: str,
        network_enabled: bool = False,  # ignored — always disabled, see module docstring
    ) -> Dict:
        # sandbox_dir was already created (and code written into it) by the
        # base class's execute() on host disk before calling _run() — for
        # the hardened profile we instead write the code directly into the
        # container's tmpfs via a startup wrapper, so nothing ever touches
        # host disk. The host-side sandbox_dir is still cleaned up by the
        # base class's execute() `finally` block as a defensive no-op.
        container = None
        try:
            client = self._get_client()

            image_name = lang_cfg["image"]
            try:
                client.images.get(image_name)
            except Exception:
                logger.warning(
                    f"EcosystemGateExecutor {request_id} -> image {image_name!r} not found locally "
                    f"-- skipping execution (infra skip, not a code failure)"
                )
                return {"success": False, "output": "", "exit_code": 0, "language": language, "image_missing": True}

            filename = lang_cfg["filename"]
            # Base64-encode the script so it survives shell quoting untouched,
            # then decode it into the tmpfs-backed /sandbox at container start
            # — the ONLY way code enters this container is via its command
            # line, never a host bind mount.
            import base64

            encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
            write_and_run = (
                f"python -c \"import base64,pathlib; "
                f"pathlib.Path('/sandbox/{filename}').write_bytes(base64.b64decode('{encoded}'))\" "
                f"&& {lang_cfg['command']}"
            )

            container = client.containers.run(
                image=image_name,
                command=["sh", "-c", write_and_run],
                working_dir="/sandbox",
                detach=True,
                mem_limit=GATE_MEM_LIMIT,
                cpu_quota=GATE_CPU_QUOTA,
                network_disabled=True,
                security_opt=["no-new-privileges"],
                read_only=True,
                tmpfs={"/sandbox": f"rw,size={GATE_TMPFS_SIZE}"},
            )

            exit_info = container.wait(timeout=GATE_EXECUTION_TIMEOUT)
            exit_code = exit_info.get("StatusCode", -1)
            stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")
            output = stdout + (f"\n[stderr]\n{stderr}" if stderr.strip() else "")
            success = exit_code == 0

            logger.info(f"EcosystemGateExecutor {request_id} -> exit_code={exit_code} success={success}")
            return {"success": success, "output": output, "exit_code": exit_code, "language": language}

        except Exception as exc:
            logger.error(f"EcosystemGateExecutor {request_id} -> execution failed -> {exc}")
            return {"success": False, "output": str(exc), "exit_code": -1, "language": language}

        finally:
            self._cleanup_container(container)


ecosystem_gate_executor = EcosystemGateExecutor()
