#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ============================================================
# Seeds two fixed, same-org test users for the Playwright E2E specs under
# ai-ui/e2e/ (M5's own 7 named specs, docs/ecosystem/SKILLS_PHASE_PLAN.md).
# Mirrors scripts/seed.py's own idempotent INSERT ... ON CONFLICT DO UPDATE
# pattern -- safe to re-run, never touches scripts/seed.py's own
# admin@ainxt.local / dev@ainxt.local accounts.
#
# Usage: python scripts/ecosystem/seed_e2e_test_users.py
# Passwords come from E2E_USER_A_PASSWORD / E2E_USER_B_PASSWORD env vars,
# falling back to a fixed dev-only default -- these are throwaway test
# accounts for a local/CI Playwright run, never production identities.
# ============================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"), override=False)
except ImportError:
    pass

from passlib.context import CryptContext
from sqlalchemy import text
from db.database import SessionLocal
import db.models  # noqa — populate metadata

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

E2E_ORG_ID = "e2e-test-org"
USERS = [
    {
        "email": "e2e-user-a@ainxt.local",
        "name": "E2E User A",
        "role": "user",
        "org_id": E2E_ORG_ID,
        "password": os.getenv("E2E_USER_A_PASSWORD", "E2E-test-password-A-1!"),
    },
    {
        "email": "e2e-user-b@ainxt.local",
        "name": "E2E User B",
        "role": "user",
        "org_id": E2E_ORG_ID,
        "password": os.getenv("E2E_USER_B_PASSWORD", "E2E-test-password-B-1!"),
    },
    # Connectors+Plugins phase E2E round (2026-09-30): a plain "user" role
    # can never see the Advanced: MCP servers sub-view (gated on
    # caller_permissions.can_admin_surfaces) or the admin Sources screen --
    # these two were created ad hoc, directly against the live dev DB,
    # earlier in that same round, with no reusable seeding script and no
    # password recorded anywhere durable. Added here properly so their
    # passwords are known, documented, and reproducible via a normal
    # `python scripts/ecosystem/seed_e2e_test_users.py` re-run rather than
    # a one-off snippet nobody can repeat. org_id="default" (not
    # "e2e-test-org") matches how they were originally created -- the
    # admin-only surfaces this pair exists to test (Advanced MCP servers,
    # admin Sources) are evaluated against the caller's real org, and
    # "default" is this deployment's own real single-tenant org.
    {
        "email": "e2e-admin@ainxt.local",
        "name": "E2E Admin",
        "role": "admin",
        "org_id": "default",
        "password": os.getenv("E2E_ADMIN_PASSWORD", "E2E-test-password-Admin-1!"),
    },
    {
        "email": "e2e-user@ainxt.local",
        "name": "E2E User",
        "role": "user",
        "org_id": "default",
        "password": os.getenv("E2E_PLAIN_USER_PASSWORD", "E2E-test-password-User-1!"),
    },
]

_UPSERT_SQL = text("""
    INSERT INTO users (id, email, name, role, org_id, hashed_password, is_active, account_status, email_verified, ad_level, department)
    VALUES (gen_random_uuid(), :email, :name, :role, :org_id, :hashed_password, true, 'active', true, 6, 'USER')
    ON CONFLICT (email) DO UPDATE SET
        role = EXCLUDED.role,
        hashed_password = EXCLUDED.hashed_password,
        org_id = EXCLUDED.org_id,
        is_active = true,
        account_status = 'active'
""")


def main():
    db = SessionLocal()
    try:
        for u in USERS:
            db.execute(_UPSERT_SQL, {
                "email": u["email"], "name": u["name"], "role": u["role"], "org_id": u["org_id"],
                "hashed_password": pwd.hash(u["password"]),
            })
        db.commit()
        for u in USERS:
            print(f"  seeded {u['email']} (role={u['role']}, org={u['org_id']})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
