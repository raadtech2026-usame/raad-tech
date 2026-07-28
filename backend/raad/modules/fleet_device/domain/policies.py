"""Domain policies for the `fleet_device` module (Backend LLD §5.1).

None are defined in this phase. The two first-class policies the LLD names (§5.2) belong to
other contexts, not here:

- `SubscriptionAccessPolicy` (**CR-1**) — governs the Parent surface; consumes assignment state
  (owned by `transport_ops`) and the organization's own subscription state (owned by `billing`
  — ADR-0016 removed the former `billing_model` input, RAAD bills Organizations only now).
- `VideoAccessPolicy` (**D5**) — governs video access; owned by the `video` context. It
  *consumes* this module's `Camera.position` provisioning fact (`in_cabin` never exposed to
  parents, Database Design §5.3) but the decision object lives with the video capability.

Device-related authorization (who may assign/suspend/retire a device) is the RBAC permission
matrix + tenant scoping — the authorization layer (`core/security`, pending the approved
matrix), not a domain policy of this module; same reasoning as `iam.domain.policies` and
`organization.domain.policies`.
"""
