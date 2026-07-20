"""External adapters for `notifications` (Backend LLD §6.2/§6.3 Anti-Corruption Layer).

Deliberately empty this phase. The task's own Delivery scope explicitly forbids implementing
Firebase Cloud Messaging, APNS, SMS, email, WhatsApp, or any push-SDK integration —
"persist notifications only." No push-provider port exists to adapt either
(`application/ports.py`'s own docstring explains why none was declared). A future
`FcmPushSender` adapter belongs here once a documented port interface and an approved
integration exist — mirroring `billing.infra.adapters`'s identical "deliberately absent, not
stubbed" precedent for `EvcPlusPaymentAdapter`.
"""
