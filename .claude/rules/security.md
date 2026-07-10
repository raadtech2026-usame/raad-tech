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
5. **Video is Org-Admin-only, by construction**, not by a runtime flag that could be misconfigured.
6. **Safety capabilities are never billing-gated.** Subscription lapse restricts premium/convenience
   features only — enforced by one policy object, tested explicitly.
7. **Encryption everywhere:** HTTPS/TLS on all client-plane traffic; encryption at rest for the
   database and backups.
8. **Every important action is audit-logged**, append-only, tamper-evident, and itself
   permission-gated to view.
9. **Device-plane compensating controls required** given JT808/JT1078's weak native security: device
   auth keys, IP/APN allow-listing where supported, DMZ isolation, heartbeat/traffic anomaly
   detection.
10. **Payment callbacks are untrusted input** until signature/secret-verified; unverified callbacks
    are rejected and audited.
