# Security review: platform API (`tablesight/platform/*`)

Scope: adversarial pass over the HTTP API, auth, tenancy and edge ingestion. Covers RED_TEAM items 7-11.
Method: attack tests written first in `tests/test_security_auth.py` and `tests/test_security_api.py`, then fixes.
Honesty notes:
- The first run of the new tests could not execute against the old code at all (`create_app` had no `clock`
  parameter, and `/sessions`, `/members` etc. did not exist), so "red before green" is by construction, not a
  recorded diff. The concurrency test was mutation-checked: with the lock removed it fails with
  `sqlite3.InterfaceError: bad parameter or other API misuse`.
- Concurrency tests are probabilistic regression tests, not proofs.
- Severity is my judgement for a multi-tenant SaaS deployment.

Run: `python -m pytest -q tests/test_security_auth.py tests/test_security_api.py` (49 tests, all passing at time of writing).

## Findings

| # | Sev | Finding | Fix | Tests |
|---|-----|---------|-----|-------|
| 1 | High | **Shared sqlite connection used by all worker threads** (RED_TEAM 7): concurrent requests raise `InterfaceError`, interleave transactions, and one thread's `commit()` persists another's half-finished writes. | `db.LockedDB`: every statement under an `RLock`, results fully fetched before release, `db.tx()` for atomic multi-statement blocks (one commit; rollback on any exception). All write endpoints use `tx()`. File DB gets WAL and mode 0600. Postgres is still the real answer for scale. | `test_shared_db_survives_concurrent_requests`, `test_failed_transaction_leaves_no_partial_rows` |
| 2 | High | **Single-use tokens were check-then-delete**: two concurrent requests could both redeem one invite, pairing code or reset token. | `claim()` / pairing consume with `DELETE ... ` and require `rowcount == 1` inside a transaction. | `test_pairing_code_and_invite_cannot_be_redeemed_twice_in_a_race` |
| 3 | High | **Owner could upgrade own plan to enterprise for free** via `POST /billing/plan`. | `create_app(allow_self_serve_plan=False)` allows only downgrades; `python -m tablesight.platform` sets it False unless `TABLESIGHT_ALLOW_SELF_SERVE_PLAN=1`. Library default stays True (existing tests and demo need it). | `test_self_serve_plan_upgrade_can_be_disabled_for_production` |
| 4 | High | **Invite authority not re-checked at accept time**: an invite sent by a since-removed or demoted member stayed valid. `INSERT OR REPLACE` could also overwrite an existing higher-role membership (demote an owner). | Invites record `inviter`; accept requires the inviter to still be a member who can `invite` and `can_assign` that role (and still in scope). Existing membership of equal/higher rank gives 409. Org-wide roles no longer store a (possibly foreign) `location_id`. | `test_invite_dies_when_inviter_loses_access_or_authority`, `test_accepting_an_invite_never_downgrades_an_existing_member`, `test_org_level_invite_does_not_store_a_foreign_location` |
| 5 | High | **No way to remove a member or revoke a device.** A stolen edge token or fired employee kept access indefinitely. | `GET/PATCH/DELETE /members`, `DELETE /devices/{id}`. Rank rule: you can only manage members strictly below you, in your location scope; owners cannot be changed via API (cannot orphan an org). Removal also deletes that user's sessions in the org. All audited. | `test_member_management_is_rank_and_scope_checked_and_audited`, `test_device_revocation_is_tenant_and_scope_checked`, `test_invite_escalation_matrix` |
| 6 | Medium | **IDOR: location-scoped GM could list every device in the org** (`/devices` was org-wide). | Scoped roles filtered to their location; same rule on revoke. | `test_gm_cannot_see_devices_or_pair_for_other_locations` |
| 7 | Medium | **Login enumeration/timing**: unknown email ran two scrypts (hash+verify) vs one; `423 locked` only for real accounts; signup returned `409 email already registered`. | Single `verify_password` against a precomputed dummy hash for unknown users; lock state keyed by email in `login_fail` so ghosts lock identically; duplicate signup returns the normal shape and mails "account_exists" (rate-limited). | `test_login_does_identical_password_work_for_unknown_and_known_user`, `test_lockout_applies_identically_to_unknown_emails`, `test_duplicate_signup_does_not_reveal_registration` |
| 8 | Medium | **Rate limiting** (RED_TEAM 8): login limited per email only; reset/signup/pairing/verify unlimited; limiter was not thread-safe and grew without bound. | Per-IP **and** per-identity limits on login, signup, reset request (per-email cap is silent so it cannot enumerate; stops mail-bombing), token endpoints, pairing failures (per IP + global), invites per user, ingest per device. Limiter is locked, prunes idle keys, caps keys (fails closed). `X-Forwarded-For` is ignored by the app (spoofing it does not reset limits); behind a proxy, configure uvicorn `--forwarded-allow-ips`. | `test_per_ip_login_limit_spans_emails_and_ignores_spoofed_forwarded_for`, `test_per_ip_signup_limit`, `test_reset_request_per_email_cap_is_silent_and_per_ip_cap_is_enforced`, `test_pairing_code_brute_force_is_throttled_then_recovers` |
| 9 | Medium | **Pairing code entropy**: 8 digits (26.6 bits) with unlimited guesses for 15 min, unbounded live codes. | 10 chars from a 30-symbol unambiguous alphabet (about 49 bits, `XXXXX-XXXXX`, case/hyphen-insensitive), failure throttling above, max 10 live codes per org, expired codes purged. Edge client is unchanged (code is opaque; `quote()`d). | `test_pairing_code_entropy_and_format`, `test_pairing_codes_outstanding_are_capped_and_pairing_accepts_lowercase` |
| 10 | Medium | **Sessions** (RED_TEAM 10): no revocation, no idle timeout, unlimited sessions, any `Authorization` value accepted (no scheme check). | Public session ids; `GET /sessions`, `DELETE /sessions/{id}` (own only, 404 otherwise), `POST /logout-all`; 12 h absolute + 4 h idle; max 20 per user; `Bearer` scheme required; reset/removal kill sessions. | `test_session_absolute_and_idle_expiry`, `test_logout_all_and_session_list_and_revoke`, `test_cannot_list_or_revoke_another_users_sessions`, `test_authorization_scheme_must_be_bearer`, `test_sessions_per_user_are_capped` |
| 11 | Medium | **2FA weaknesses**: wrong TOTP never counted toward lockout (6-digit brute force); codes replayable in-window; any live session could overwrite the 2FA secret (persistence after token theft). | TOTP failures/replays feed the same lockout; last used step stored (`totp_last`); replacing an existing secret needs a current code. | `test_totp_code_cannot_be_replayed_and_failures_lock`, `test_stolen_session_cannot_replace_existing_2fa_secret` |
| 12 | Medium | **Token reuse / pre-hijack**: old reset tokens survived a newer request; a password pre-registered by an attacker for a victim's address survived the victim's reset or invite. | New reset request supersedes older ones; confirm deletes all; reset also marks the account verified (mailbox ownership proven) and kills sessions; accepting an invite on an unverified pre-registered account replaces its password. | `test_verification_and_reset_tokens_are_single_use_and_superseded`, `test_reset_proves_mailbox_ownership_so_preregistered_password_dies` |
| 13 | Medium | **Secrets in URLs and error bodies**: reset/accept took passwords as query parameters (proxy/access logs); FastAPI 422 echoes the rejected `input` (passwords). | Body form accepted for reset-confirm and invite-accept (query form kept so existing clients/tests work); custom 422 handler drops `input`; uvicorn access log disabled in `__main__`. | `test_reset_confirm_accepts_body_so_secrets_need_not_be_in_urls`, `test_validation_errors_never_echo_secrets` |
| 14 | Medium | **CSV/formula injection** in export (`=`, `+`, `-`, `@`, TAB, CR in `event_id/table_id/kind/detail`). | `security.csv_safe` prefixes `'`; response is `text/csv` + `Content-Disposition: attachment`. | `test_csv_export_neutralises_formula_injection` |
| 15 | Medium | **Input limits**: unbounded passwords (scrypt CPU DoS), emails, names, camera URLs (any scheme), event ids/kind/detail, corrections payload, heartbeat health, events list/export size, request bodies. | Pydantic/Query constraints everywhere; detail max 2 KB and depth 5; batch max 1000 (413); body cap 4 MiB enforced on Content-Length and while streaming; camera URL must be rtsp(s)/http(s) with a host; tz validated via `zoneinfo`; `/events` paginated (`limit` <= 5000), export capped at 100k rows; recursion-bomb JSON gives 400. | `test_password_and_email_size_limits`, `test_event_validation_limits`, `test_events_list_is_paginated_and_bounded`, `test_heartbeat_limits_and_clock_skew_flag`, `test_camera_and_location_input_validation`, `test_correction_payload_is_bounded`, `test_oversized_bodies_are_rejected_before_parsing`, `test_deeply_nested_json_is_a_400_not_a_crash` |
| 16 | Medium | **Timestamp sanity / clock drift** (RED_TEAM 11): any float accepted (NaN, negative, year 3000). | Future (> now+300 s), negative and non-finite timestamps are rejected per event (`rejected` count in the response; valid events in the same batch still stored so edge retries cannot poison-loop). Heartbeat takes optional `device_t` and records `clock_skew_s`. | `test_event_validation_limits`, `test_heartbeat_limits_and_clock_skew_flag` |
| 17 | Low | **Security headers absent.** | ASGI middleware on every response incl. 4xx/5xx: CSP `default-src 'none'; frame-ancestors 'none'`, nosniff, X-Frame-Options DENY, no-referrer, `Cache-Control: no-store`, HSTS, Permissions-Policy, CORP. Interactive docs/openapi disabled unless `enable_docs=True`. Last-resort 500 leaks nothing. | `test_security_headers_on_every_response_and_no_store_on_auth`, `test_interactive_docs_disabled_by_default` |
| 18 | Low | **Dynamic SQL**: `f"DELETE FROM {t}"` in org purge (constant today, injection-prone tomorrow). | Literal statements only; a source-scan test forbids interpolated `execute()` strings in `app.py`. Injection probes against every string parameter are inert (all queries were already parameterised). | `test_sql_injection_strings_are_inert`, `test_no_dynamic_sql_in_platform_source` |
| 19 | Low | **Login with no membership** (e.g. removed member) crashed with a 500. | Returns 403. | covered by member-removal tests |
| 20 | Low | **Audit gaps**: no login/logout, feed reads, staff analytics, corrections, pairing, billing, 2FA, session/device/member changes; no source IP. | All now audited with client IP; read events (`events.read`, `staff_analytics.read`) de-duplicated per user/location per 60 s; role changes record `old->new`; audit rows survive `DELETE /org/data`. There is no video endpoint yet; add `video.view` audit entries when one exists. | `test_audit_log_records_login_logout_feed_access_and_ip`, `test_audit_covers_account_security_events`, `test_audit_survives_org_data_deletion_and_is_tenant_scoped` |
| 21 | Low | Server role saw nothing because no API could set `section`; filter ran in Python after loading all rows. | `section` accepted on invite/PATCH member; filter is SQL (`json_extract`), so limits apply correctly. | `test_server_role_sees_only_own_section_and_cannot_export` |

Also checked, no bug found: tenant isolation across all resources (existing tests plus 404-not-403 on foreign ids),
`org_id` never read from requests, tokens stored only as SHA-256, camera URLs sealed with Fernet, device tokens cannot
call user routes and vice versa, scoped roles cannot invite outside their location or above their rank.

## Webhooks / SSRF
No webhook endpoints exist (the `webhooks` table is only purged), so no outbound-request SSRF surface was added.
If added: allow `https` only, resolve DNS and block loopback/link-local/RFC1918/metadata ranges **after** resolution
and again at connect time (anti-rebinding), no redirects, short timeouts, response bodies discarded, HMAC-signed
payloads, per-org rate limit, and store secrets sealed with the Vault. Camera URLs are dialled by the edge agent on the
customer LAN by design; the platform only stores them, now restricted to rtsp(s)/http(s).

## Residual risks (not fixed)
- **Rate limits and lockout state are per-process memory** (limiters) or per-DB (lockout). A multi-node deploy needs a
  shared store (Redis/Postgres); a botnet beats per-IP limits. Lockout can still be abused to deny a victim login for
  15 min (accepted trade-off; mitigation would be per-device cookies or proof-of-work).
- **Key-flooding fails closed**: > 50k distinct limiter keys in one window blocks new keys (availability over safety).
- **Back-dated events**: only future/negative timestamps are rejected. Old `t` is accepted because edge replay after
  long outages and the existing tests use small `t`. A device can therefore back-fill history. Also `INSERT OR IGNORE` on
  `(org_id, event_id)` means a device can pre-claim an id used by another location of the same org.
- **Reset-request timing** still differs slightly for existing accounts (token insert + mail). Send mail from a queue.
- **Pre-hijack via signup** is only partly closed (reset/invite fixes above); a victim who clicks the signup
  verification mail for an attacker-registered address still lands in an attacker-known password until they reset.
  Proper fix: require setting the password after verification.
- **No CSRF** surface while auth is bearer-header only; revisit if cookies are introduced. No CORS is configured.
- **Query-string compatibility**: `password`/`new_password` in query still works for old clients. Remove once clients move
  to the JSON body (`/invites/accept`, `/password-reset/confirm`). Pairing codes and email-verification tokens remain in
  query strings by design (single use, short lived).
- **Session tokens in `localStorage`** (if the web client does that) are XSS-exposed; not in this module's scope.
- **Process/deploy**: `__main__` still binds 0.0.0.0 because `deploy/Dockerfile` relies on it (set `HOST=127.0.0.1` behind
  a TLS proxy); TLS termination, `--forwarded-allow-ips`, secret rotation for `TABLESIGHT_VAULT_KEY` and backups are ops
  items. Camera URLs are sealed but never re-sealed on key rotation. SQLite single-writer is a throughput cap.
- **Demo/library default** `allow_self_serve_plan=True` remains insecure by default for embedders other than `__main__`.
- Audit log is append-only by convention, not tamper-evident (no hash chain / external sink); no pagination beyond 500.
- `delete_data` leaves users, memberships, sessions and the org row (by design: the account owner must still sign in);
  no re-authentication is required for it.
- Email normalisation is `strip().lower()` (no Unicode confusable handling).
