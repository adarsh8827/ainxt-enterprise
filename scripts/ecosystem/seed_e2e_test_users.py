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
        "password": os.getenv("E2E_USER_A_PASSWORD", "E2E-test-password-A-1!"),
    },
    {
        "email": "e2e-user-b@ainxt.local",
        "name": "E2E User B",
        "password": os.getenv("E2E_USER_B_PASSWORD", "E2E-test-password-B-1!"),
    },
]

_UPSERT_SQL = text("""
    INSERT INTO users (id, email, name, role, org_id, hashed_password, is_active, account_status, email_verified, ad_level, department)
    VALUES (gen_random_uuid(), :email, :name, 'user', :org_id, :hashed_password, true, 'active', true, 6, 'USER')
    ON CONFLICT (email) DO UPDATE SET
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
                "email": u["email"], "name": u["name"], "org_id": E2E_ORG_ID,
                "hashed_password": pwd.hash(u["password"]),
            })
        db.commit()
        for u in USERS:
            print(f"  seeded {u['email']} (org={E2E_ORG_ID})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
