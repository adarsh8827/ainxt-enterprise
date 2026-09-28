#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Ecosystem marketplace — seed default builtin skills (task B-22).

Walks ecosystem/builtin/skills/<category>/<name>/SKILL.md, upserts each as
a scope='builtin' ecosystem_items row, and gates it through the exact same
B-8/B-9 pipeline as any other item — no bypass. Idempotent: re-running
produces no duplicate versions (content-hash matched, versions_service's
existing dedup), matched to the same item row (namespace+item_type matched,
items_service.upsert_builtin_item's existing dedup).

Usage:
    python scripts/ecosystem/seed_builtin_skills.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_BUILTIN_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "ecosystem" / "builtin" / "skills"
_PUBLISHER_SLUG = "ainxt"


def _iter_skill_dirs():
    if not _BUILTIN_SKILLS_ROOT.exists():
        return
    for category_dir in sorted(_BUILTIN_SKILLS_ROOT.iterdir()):
        if not category_dir.is_dir():
            continue
        for skill_dir in sorted(category_dir.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                yield category_dir.name, skill_dir.name, skill_md


def seed_all() -> list[dict]:
    from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter
    from services.ecosystem.gate_service import enqueue_gate_run
    from services.ecosystem.items_service import upsert_builtin_item
    from services.ecosystem.publishers_service import resolve_publisher
    from services.ecosystem.versions_service import create_version_for_content, encode_envelope

    results = []
    for category, skill_slug, skill_md_path in _iter_skill_dirs():
        text = skill_md_path.read_text(encoding="utf-8")
        frontmatter = parse_skill_md_frontmatter(text)

        name = frontmatter.get("name", skill_slug)
        description = frontmatter.get("description", "")
        license = frontmatter.get("license", "MIT")
        namespace = f"{_PUBLISHER_SLUG}/{skill_slug}"

        resolve_publisher(namespace, owner_type="org", owner_ref="platform")
        item_id, item_created = upsert_builtin_item(
            namespace=namespace, item_type="skill", category=category,
            display_name=name, description=description, license=license,
        )

        manifest = {"name": name, "description": description, "instructions": text}
        payload = encode_envelope(manifest, {})
        version_id = create_version_for_content(
            item_id=item_id, content=payload, manifest=manifest, license=license,
        )
        gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision")

        results.append({
            "namespace": namespace, "item_id": item_id, "item_created": item_created,
            "version_id": version_id, "gate_run_id": gate_run_id,
        })
    return results


def main() -> int:
    results = seed_all()
    if not results:
        print(f"No builtin skills found under {_BUILTIN_SKILLS_ROOT}")
        return 1

    from db.database import SessionLocal
    from db.models import EcosystemGateRun

    db = SessionLocal()
    try:
        for r in results:
            verdict = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == r["gate_run_id"]).one().verdict
            status = "created" if r["item_created"] else "updated"
            print(f"{r['namespace']}: {status}, gate verdict = {verdict}")
    finally:
        db.close()

    print(f"Seeded {len(results)} builtin skill(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
