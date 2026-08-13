# Rule: Security

Derived from `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §12 and
`docs/business/Project_Brief_v1.md` Ch. 7.13.

1. **Least privilege by default.** Every role's permission set is explicit; nothing is inherited
   implicitly.
2. **Tenant isolation is defense-in-depth:** `organization_id` enforced at both the repository layer
   and the authorization layer, never only one.
3. **Region scoping is a second filter on top of tenant scoping** for RAAD staff (Founder = all,
   Regional Manager = assigned regions, Support = assigned orgs, Finance = billing scope only).
4. **The tracking-visibility predicate is: capability ∧ scope ∧ ownership ∧ time-window.** Every
   live-tracking surface (web, mobile, WebSocket, REST) must implement this exact predicate — no
   surface may take a shortcut version of it.
5. **Video is Org-Admin-only by default and by construction, not by a runtime flag that could be
   misconfigured.** A narrow, explicit exception exists for Parent (ADR-0026, 2026-08-12):
   `video_live_access`/`video_playback_access`, two independent booleans on the `Parent`
   aggregate, off by default for every parent and grantable only by that parent's own
   organization admin (`PATCH /parents/{id}/video-access`, a dedicated, more restrictive
   permission than ordinary parent-profile edits). This remains construction, not
   configuration: the server-side chain (self identity → explicit permission → child/device
   ownership, `interfaces/http/policy_guards.resolve_d5_decision`) is still a fixed code path,
   not a toggle that changes behavior at the framework level, and it is not reachable or
   bypassable from the client. Driver's video exclusion is unchanged.
6. **Safety capabilities are never billing-gated.** Subscription lapse restricts premium/convenience
   features only — enforced by one policy object, tested explicitly.
7. **Encryption everywhere:** HTTPS/TLS on all client-plane traffic; encryption at rest for the
   database and backups.
8. **Every important action is audit-logged**, append-only, tamper-evident, and itself
   permission-gated to view.
9. **Device-plane trust model: identity + secure credential is primary; network-layer controls are
   optional defense-in-depth only (ADR-0015).** Do not assume a stable/static device IP or a
   private APN — RAAD's device fleet runs over ordinary public cellular data by default, where IPs
   are dynamic and carrier-NAT'd. The mandatory control is verifying device identity (terminal ID/
   IMEI) plus a secure device credential wherever the vendor's protocol supports one (JT/T 808's
   `auth_key_hash`/auth-code exchange is the reference implementation — never bypassable, never
   IP-dependent). IP/APN allow-listing, mutual TLS at the network layer, and DMZ isolation may be
   layered on **only** for a specific deployment that genuinely has a private APN or static device
   IPs (a carrier-level arrangement) — they are never a required baseline and never a substitute
   for a missing credential. Heartbeat/traffic anomaly detection remains a useful, independent
   compensating signal regardless of topology. Where a vendor's protocol has no credential
   mechanism at all (see `.claude/rules/jt808.md`'s LSZ note), this is an accepted, explicitly
   flagged gap — closed by the strongest identity check the protocol actually supports, never by
   inventing a credential the hardware doesn't have or by leaning on network-layer controls that
   don't hold for a dynamic-IP fleet.
10. **Payment callbacks are untrusted input** until signature/secret-verified; unverified callbacks
    are rejected and audited.
11. **Account-sharing protection is a bounded concurrent-session cap, not device attestation
    (ADR-0019).** Every login/refresh enforces a per-role maximum on non-revoked, non-expired
    `refresh_tokens` rows for that user (oldest revoked first when exceeded), via one tested
    `SessionLimitPolicy` object (`core/policies/`) — never a scattered ad hoc count check. The
    cap is configurable per role via the existing `SystemSetting` store, never hardcoded. A
    login from an unrecognized device/IP combination is audit-logged as a visibility signal only
    — no automated hard block exists absent a documented fraud-detection policy. Heavier tiers
    (device fingerprinting/trusted-device approval, hardware-backed attestation) are a deliberate
    later decision, not an oversight — see ADR-0019's Consequences.
