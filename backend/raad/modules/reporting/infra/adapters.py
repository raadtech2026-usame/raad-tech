"""External adapters for `reporting` (Backend LLD §6.2/§6.3 Anti-Corruption Layer).

Deliberately empty this phase. `application/ports.ReportRendererPort` now exists (Backend
Stabilization phase), but no concrete implementation is bound here — actual PDF/Excel
generation remains out of scope (no rendering engine or object-store integration has been
approved), the same "define the interface, leave the adapter unbound" doctrine `billing.infra.
adapters.PaymentProviderPort`/`video.infra.adapters.VideoProviderPort` already establish. The
Report Worker (`interfaces/workers/report_worker.py`) therefore starts every `queued` run,
attempts to resolve this port, and marks the run `failed` (not a crash) when none is bound —
the identical "fail loudly per unit of work, don't fake a render" posture `BillingApplicationService.
initiate_payment` already established for its own unbound `PaymentProviderPort`.
"""
