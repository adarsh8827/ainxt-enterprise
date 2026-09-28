# LLD — Desktop local cache

**Purpose**: how the desktop app keeps a verified local copy of installed item content for offline use, without ever becoming a second source of truth. Design only as of this revision (Review round following M1, item H) — built in the Desktop phase (`ECOSYSTEM_PLAN.md` §10/§13's desktop work, not yet scheduled as a numbered task in `SKILLS_PHASE_PLAN.md`).

## Files / functions
_Not yet implemented._ Expected shape, extending what already exists rather than introducing a new mechanism:
- `desktop/src/main.js` already maintains the gateway WebSocket-equivalent connection (`:911-983`'s local-MCP-server pattern is the direct precedent) and already depends on `electron-store` (`desktop/package.json`) for small local caches (`ECOSYSTEM_PLAN.md` §9's "Offline: cached, read-only catalog + Yours list" note). The local content cache described here is a new, larger store built the same way — not a new dependency.
- Credential handling reuses `desktop/src/buddy/auth.js:57-85`'s existing `safeStorage` pattern (DPAPI/Keychain-backed, no `keytar`) verbatim — this file does not introduce a second credential-storage mechanism.

## API and DB changes
No new server-side tables — this is a desktop-local cache, not a server concern. The server-side `desktop_devices` table (task B-1, unused until the Desktop phase) backs per-device revocation, which indirectly invalidates a device's local cache (see Edge cases below).

## Sequence diagrams
```
Install/update (server is source of truth):
  Server: ecosystem_installs row created/updated
    → ecosystem.changed (task B-13) → desktop client (existing WS channel)
    → desktop fetches the version's content via the normal authenticated API
      (same object-storage-backed read path as web — no special desktop endpoint)
    → desktop verifies sha256(content) == ecosystem_item_versions.content_hash
      before writing to local cache (never trust the transport alone)
    → org-private content is encrypted at rest with a key held in safeStorage
      before being written to the per-OS app-data folder; builtin/public content
      is stored as plain content-hash-addressed files (nothing sensitive to
      protect, and it may be shared across multiple local users of one machine)

Uninstall/disable/force-disable:
  Server: ecosystem_installs.enabled=false, or row deleted
    → ecosystem.changed → desktop removes the corresponding local cache entry
      immediately, does not wait for the next full sync

Offline read:
  Desktop: read from local cache only if the stored content's hash still
    matches its recorded content_hash (re-verified before every use, not
    just at write time — catches on-disk corruption/tampering the same way
    store/ecosystem_object_storage.py's server-side read does)
    → if the hash check fails, the entry is treated as absent, not served
      corrupted; the item shows as unavailable until back online
```

## Edge cases and errors
- **No local-only installs.** Every local-execution item is still registered and gated server-side at install time (`ECOSYSTEM_PLAN.md` §9's existing "Local items still pass the same gate/license check before the desktop runs them — enforced server-side at install time, not bypassable by the desktop client" — this design doesn't change that, it only adds a content cache on top of an install that already exists server-side). The local cache is a performance/offline convenience, never an alternate installation path a user could use to bypass the gate.
- **Content-hash re-verification, not one-time.** A local cache entry is checked against `content_hash` on every read that matters (not just once when written) — this catches disk corruption and local tampering equally, matching the server-side object store's own tamper-detection design (`store/ecosystem_object_storage.py`, task B-2).
- **Device revocation invalidates the cache.** When an admin revokes a device (`desktop_devices.revoked_at`, already in the schema per task B-1), that device's session can no longer authenticate to fetch new content or receive `ecosystem.changed` — its existing local cache is not remotely wiped (no remote-wipe mechanism exists or is proposed here), but it can no longer refresh, and the next time that device does successfully authenticate (e.g. after being un-revoked), a full resync is the safe recovery path rather than trusting whatever is on disk from before the gap.
- **Offline = read-only, not stale-write.** No local mutation of installed content is ever queued for later sync — a user cannot edit a cached skill offline and have it "catch up" to the server later, since the server is the only writer of `ecosystem_item_versions` (immutable versions, `ECOSYSTEM_PLAN.md` §4). Offline use is read/execute only.
- **Org-private content encryption key**: held in `safeStorage`, per-device (not synced between a user's multiple devices, matching the existing `safeStorage` pattern's own device-bound nature) — a user who installs an org-private item on a second device re-fetches and re-encrypts under that device's own key, rather than any key-sharing mechanism between devices.

## Flags
None yet — no code exists to gate. When implemented, expect this to ship behind whatever flag the broader Desktop phase uses (not yet named), consistent with every other phase in this plan shipping behind an explicit flag.

## Tests
_Not yet implemented._ Expected coverage once built: a tamper test (corrupt a cached file on disk, assert the read is refused rather than served); an offline test (disconnect, assert cached content is still usable and uncached content correctly shows unavailable rather than erroring); a revocation test (revoke a device, assert it can no longer refresh, without asserting anything about wiping its existing cache, which this design explicitly does not attempt); a credential test asserting a local-execution credential is never written to the content cache or any plain file, only to `safeStorage`.

## How to extend
Any future "sync more than installed-item content to desktop" feature (e.g. caching Discover's catalog listing for offline browsing, already noted as a smaller, separate concern in `ECOSYSTEM_PLAN.md` §9) should reuse this same content-hash-verified, server-is-truth pattern rather than inventing a second local-storage mechanism.
