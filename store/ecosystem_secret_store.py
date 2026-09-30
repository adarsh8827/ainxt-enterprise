# SPDX-License-Identifier: MIT
# ============================================================
# ECOSYSTEM SECRET STORE
# Per-org/per-user envelope-encrypted secret store for the Connectors/
# Plugins phase (docs/ecosystem/CONNECTORS_PHASE_PLAN.md §1).
#
# Encryption key: real, root-caused bug fixed 2026-09-30. This originally
# called core.ckms.key_service.KeyService.instance().clear_dek("KEY_CREDS")
# — but KeyService is a BOOT-TIME-ONLY cache of clear DEKs for pre-
# encrypted env vars (core/ckms/crypto.py's own header: "Only DECRYPTION
# is implemented here. Encryption is handled by ops tooling and is
# explicitly out of scope"), populated by core.ckms.bootstrap.load_at_boot()
# ONLY when CKMS_ENABLED=true. In OSS/plaintext mode (CKMS_ENABLED=false,
# the real default in .env and every local/OSS deployment), load_at_boot()
# installs an EMPTY cache by design (env vars are read as plaintext
# instead) — so clear_dek("KEY_CREDS") raised "no active DEK loaded"
# UNCONDITIONALLY in that mode, for every real value this store ever
# needed to encrypt (a new admin OAuth app's client_secret, first and
# foremost) — confirmed live: this was never reachable in this
# deployment's actual, real, default configuration, not a transient
# runtime issue. store/credential_vault.py already solves exactly this
# problem — runtime encrypt/decrypt of admin/user-entered secrets (its own
# docstring: "also used by ... the user_tokens GitLab/Jira encryption",
# i.e. the very same class of connector credential this store protects)
# — via a FERNET_KEY-derived AES-256-GCM key that works identically
# regardless of CKMS_ENABLED. Reusing it here (encrypt_value()/
# decrypt_value()) rather than re-deriving a key is additive and
# byte-for-byte consistent with how every other connector credential in
# this codebase is already encrypted.
#
# Per-org isolation: enforced by every function below REQUIRING org_id
# and filtering all queries by it — the same row-scoping pattern
# credential_vault.py uses with owner_id, not a distinct encryption key
# per org (one shared FERNET_KEY instance-wide; real per-org keys would
# need new KMS/ops infrastructure, out of scope for this phase — see
# core/ckms/hsm_provider.py's pluggable-backend design for where that
# would eventually plug in).
# ============================================================

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from store.credential_vault import decrypt_value as _vault_decrypt, encrypt_value as _vault_encrypt
from core.logger import logger

_KEY_TYPE = "KEY_CREDS"  # row label only, kept for schema/audit continuity -- not used to select a decryption path


class EcosystemSecretStoreError(Exception):
    """Raised on a real store failure (not found is signalled by None, not this)."""


# ── Encryption ────────────────────────────────────────────────

def _encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* via store/credential_vault.py's FERNET_KEY-derived
    AES-256-GCM key -- see module docstring for why this replaced
    KeyService.clear_dek()."""
    return _vault_encrypt(plaintext)


def _decrypt(ciphertext: str) -> str:
    return _vault_decrypt(ciphertext)


# ── Internal serialisation ───────────────────────────────────

def _row_to_dict(row) -> dict:
    return {
        "id":           str(row.id),
        "org_id":       row.org_id,
        "user_id":      row.user_id,
        "kind":         row.kind,
        "name":         row.name,
        "last_rotated": row.last_rotated.isoformat() if row.last_rotated else None,
        "created_at":   row.created_at.isoformat() if row.created_at else None,
        "updated_at":   row.updated_at.isoformat() if row.updated_at else None,
    }


# In-process fallback, keyed by (org_id, user_id, kind, name) — mirrors
# credential_vault.py's fallback pattern, same transparent-degrade behavior.
_fallback_store: Dict[tuple, dict] = {}


def _fallback_public(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k != "ciphertext"}


def _fallback_key(org_id: str, user_id: Optional[str], kind: str, name: str) -> tuple:
    return (org_id, user_id, kind, name)


# ── CRUD ──────────────────────────────────────────────────────

def create_secret(
    org_id: str,
    kind: str,
    name: str,
    value: str,
    user_id: Optional[str] = None,
) -> dict:
    """Encrypt *value* and persist a new secret row scoped to *org_id*
    (and *user_id* when *kind* is per_user/device_local).

    Raises ValueError if a secret with this (org_id, user_id, kind, name)
    already exists.
    """
    try:
        from db.database import SessionLocal
        from db.models import EcosystemSecret

        ciphertext = _encrypt(value)
        db = SessionLocal()
        try:
            existing = (
                db.query(EcosystemSecret)
                .filter(
                    EcosystemSecret.org_id == org_id,
                    EcosystemSecret.user_id == user_id,
                    EcosystemSecret.kind == kind,
                    EcosystemSecret.name == name,
                )
                .first()
            )
            if existing:
                raise ValueError(f"Secret '{name}' already exists for this scope")

            record = EcosystemSecret(
                id=str(uuid.uuid4()),
                org_id=org_id,
                user_id=user_id,
                kind=kind,
                name=name,
                ciphertext=ciphertext,
                key_type=_KEY_TYPE,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            logger.info(f"EcosystemSecretStore: created secret '{name}' (org={org_id}, kind={kind})")
            return _row_to_dict(record)
        finally:
            db.close()

    except ValueError:
        raise
    except Exception as exc:
        logger.warning(f"EcosystemSecretStore: DB unavailable, using fallback store — {exc}")

    fkey = _fallback_key(org_id, user_id, kind, name)
    if fkey in _fallback_store:
        raise ValueError(f"Secret '{name}' already exists for this scope")
    now = datetime.utcnow().isoformat()
    entry = {
        "id": str(uuid.uuid4()), "org_id": org_id, "user_id": user_id, "kind": kind, "name": name,
        "ciphertext": _encrypt(value), "last_rotated": None, "created_at": now, "updated_at": now,
    }
    _fallback_store[fkey] = entry
    logger.info(f"EcosystemSecretStore[fallback]: created secret '{name}'")
    return _fallback_public(entry)


def get_secret(org_id: str, kind: str, name: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Return secret metadata (never the ciphertext/plaintext). None if not found
    or if it belongs to a different org_id — cross-org lookups always miss."""
    try:
        from db.database import SessionLocal
        from db.models import EcosystemSecret

        db = SessionLocal()
        try:
            row = (
                db.query(EcosystemSecret)
                .filter(
                    EcosystemSecret.org_id == org_id,
                    EcosystemSecret.user_id == user_id,
                    EcosystemSecret.kind == kind,
                    EcosystemSecret.name == name,
                )
                .first()
            )
            return _row_to_dict(row) if row else None
        finally:
            db.close()
    except Exception as exc:
        logger.warning(f"EcosystemSecretStore: DB unavailable, reading from fallback store — {exc}")

    entry = _fallback_store.get(_fallback_key(org_id, user_id, kind, name))
    return _fallback_public(entry) if entry else None


def get_secret_value(org_id: str, kind: str, name: str, user_id: Optional[str] = None) -> Optional[str]:
    """Return the decrypted plaintext, scoped strictly to *org_id*. Callers
    must emit an audit log entry before calling this (same rule as
    credential_vault.get_credential_value).

    NOTE: ciphertext lookup and decryption are deliberately two separate
    steps (unlike this module's other functions) — a bare `except Exception`
    spanning both would also swallow a real AES-GCM auth-tag failure
    (tampered/corrupted row) as if it were "DB unavailable" and silently
    fall through to the empty fallback store, returning None instead of
    raising. Only the lookup is allowed to degrade to the fallback path.
    """
    ciphertext = _fetch_ciphertext(org_id, kind, name, user_id)
    if ciphertext is None:
        return None
    return _decrypt(ciphertext)


def _fetch_ciphertext(org_id: str, kind: str, name: str, user_id: Optional[str]) -> Optional[str]:
    try:
        from db.database import SessionLocal
        from db.models import EcosystemSecret

        db = SessionLocal()
        try:
            row = (
                db.query(EcosystemSecret)
                .filter(
                    EcosystemSecret.org_id == org_id,
                    EcosystemSecret.user_id == user_id,
                    EcosystemSecret.kind == kind,
                    EcosystemSecret.name == name,
                )
                .first()
            )
            return row.ciphertext if row else None
        finally:
            db.close()
    except Exception as exc:
        logger.warning(f"EcosystemSecretStore: DB unavailable, reading from fallback store — {exc}")

    entry = _fallback_store.get(_fallback_key(org_id, user_id, kind, name))
    return entry["ciphertext"] if entry else None


def update_secret(
    org_id: str, kind: str, name: str, value: str, user_id: Optional[str] = None
) -> Optional[dict]:
    try:
        from db.database import SessionLocal
        from db.models import EcosystemSecret

        db = SessionLocal()
        try:
            row = (
                db.query(EcosystemSecret)
                .filter(
                    EcosystemSecret.org_id == org_id,
                    EcosystemSecret.user_id == user_id,
                    EcosystemSecret.kind == kind,
                    EcosystemSecret.name == name,
                )
                .first()
            )
            if not row:
                return None
            row.ciphertext = _encrypt(value)
            row.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(row)
            return _row_to_dict(row)
        finally:
            db.close()
    except Exception as exc:
        logger.warning(f"EcosystemSecretStore: DB unavailable, updating fallback store — {exc}")

    entry = _fallback_store.get(_fallback_key(org_id, user_id, kind, name))
    if not entry:
        return None
    entry["ciphertext"] = _encrypt(value)
    entry["updated_at"] = datetime.utcnow().isoformat()
    return _fallback_public(entry)


def delete_secret(org_id: str, kind: str, name: str, user_id: Optional[str] = None) -> bool:
    try:
        from db.database import SessionLocal
        from db.models import EcosystemSecret

        db = SessionLocal()
        try:
            row = (
                db.query(EcosystemSecret)
                .filter(
                    EcosystemSecret.org_id == org_id,
                    EcosystemSecret.user_id == user_id,
                    EcosystemSecret.kind == kind,
                    EcosystemSecret.name == name,
                )
                .first()
            )
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True
        finally:
            db.close()
    except Exception as exc:
        logger.warning(f"EcosystemSecretStore: DB unavailable, deleting from fallback store — {exc}")

    fkey = _fallback_key(org_id, user_id, kind, name)
    if fkey not in _fallback_store:
        return False
    del _fallback_store[fkey]
    return True


def list_secrets(org_id: str, kind: Optional[str] = None) -> List[dict]:
    """List secret metadata for *org_id* only — never returns another org's rows."""
    try:
        from db.database import SessionLocal
        from db.models import EcosystemSecret

        db = SessionLocal()
        try:
            query = db.query(EcosystemSecret).filter(EcosystemSecret.org_id == org_id)
            if kind:
                query = query.filter(EcosystemSecret.kind == kind)
            rows = query.order_by(EcosystemSecret.created_at.desc()).all()
            return [_row_to_dict(r) for r in rows]
        finally:
            db.close()
    except Exception as exc:
        logger.warning(f"EcosystemSecretStore: DB unavailable, listing from fallback store — {exc}")

    entries = [e for k, e in _fallback_store.items() if k[0] == org_id]
    if kind:
        entries = [e for e in entries if e.get("kind") == kind]
    entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return [_fallback_public(e) for e in entries]


def rotate_secret(
    org_id: str, kind: str, name: str, new_value: str, user_id: Optional[str] = None
) -> Optional[dict]:
    try:
        from db.database import SessionLocal
        from db.models import EcosystemSecret

        db = SessionLocal()
        try:
            row = (
                db.query(EcosystemSecret)
                .filter(
                    EcosystemSecret.org_id == org_id,
                    EcosystemSecret.user_id == user_id,
                    EcosystemSecret.kind == kind,
                    EcosystemSecret.name == name,
                )
                .first()
            )
            if not row:
                return None
            now = datetime.utcnow()
            row.ciphertext = _encrypt(new_value)
            row.last_rotated = now
            row.updated_at = now
            db.commit()
            db.refresh(row)
            return _row_to_dict(row)
        finally:
            db.close()
    except Exception as exc:
        logger.warning(f"EcosystemSecretStore: DB unavailable, rotating in fallback store — {exc}")

    entry = _fallback_store.get(_fallback_key(org_id, user_id, kind, name))
    if not entry:
        return None
    now_iso = datetime.utcnow().isoformat()
    entry["ciphertext"] = _encrypt(new_value)
    entry["last_rotated"] = now_iso
    entry["updated_at"] = now_iso
    return _fallback_public(entry)
