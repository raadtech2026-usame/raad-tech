"""Module docstring only — deliberately no concrete `VideoProviderPort` implementation this
phase, mirroring `billing.infra.adapters`'s identical empty-module treatment for
`PaymentProviderPort`/`EvcPlusPaymentAdapter`.

The user's own task scope for this phase is explicit: "Do NOT implement native JT1078. For MVP
the system will use the hardware/vendor video API... Implement only the abstraction layer if
needed. Native JT1078 implementation is intentionally postponed." No vendor has been named or
approved yet, so there is nothing concrete to adapt to — `application/ports.VideoProviderPort`
is the completed abstraction; binding a real adapter here is a future phase's job once a specific
vendor/hardware video API is chosen. Until then, `core/di/bootstrap.py` leaves `VideoProviderPort`
unbound, and `VideoApplicationService.request_live_video`/`request_playback_video` raise
`NotImplementedError` at the one call site that would otherwise need it — the same "fail loudly,
don't fake" doctrine every other pending-infra port in this codebase already follows.
"""

from __future__ import annotations
