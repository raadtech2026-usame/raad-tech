# Rule: API

Derived from `docs/business/RAAD_Phase3.3_API_Contracts_v1.md`.

1. **URI versioning:** base path `/api/v1`. Breaking changes move to `/api/v2`; additive changes stay
   in `/api/v1`. Deprecated versions carry `Deprecation`/`Sunset` headers.
2. **Resource routers map 1:1 to bounded contexts:** `/auth` (iam), `/organizations` + `/regions`
   (organization), `/vehicles` + `/devices` (fleet_device), `/students` + `/parents` + `/routes` +
   `/trips` (transport_ops), `/tracking` + `/ws/tracking` (tracking), `/video` (video, Org-Admin
   only), `/notifications` + `/ws/notifications` (notifications), `/billing` (billing), `/reports`
   (reporting), `/admin` (platform_audit).
3. **Auth:** `Authorization: Bearer <access_jwt>` on every authenticated request.
4. **Error envelope is standard:** `{ error: { code, message, correlation_id, details? } }` — do not
   invent a different error shape per module.
5. **OpenAPI (and event AsyncAPI) specs are generated at build time** from module contracts
   (`api/routers.py`, `api/schemas.py`) — never hand-author a spec file that can drift from the code.
6. **Idempotency keys are required** on payment-affecting endpoints (e.g. `/billing/payments`,
   `/billing/payments/callback`) to prevent duplicate charges on retry.
