"""Realtime WebSocket surface for `notifications` (`/ws/notifications`, API Contracts §11.3;
Backend LLD §16.1/§16.2).

**Deliberately not implemented this phase — documented limitation, not an oversight.**
`interfaces/http/api_v1.py`'s own module docstring already establishes this exact deferral for
both realtime channels: "WebSocket endpoints (/ws/tracking, /ws/notifications) are wired
separately in interfaces/http/ws.py once the tracking/notifications modules have realtime
handlers... not added in this phase" — and `tracking` (an already-completed, further-along
bounded context) still has not wired `/ws/tracking` either, confirming this is a genuine,
consistently-applied backend-wide gap, not a `notifications`-specific shortfall.

Building a live handler here would require:
1. A bound `BrokerPort` (Phase 2 §4.3, still an open item — explicitly out of this phase's
   scope per the task's own "Out of Scope: Broker wiring" line) to receive the upstream events
   (`trip.started`, `geofence.approaching_stop`, etc., API Contracts §13.2) a live push would
   react to.
2. The Notification Worker itself (recipient resolution, `SubscriptionAccessPolicy` withholding
   — Backend LLD §11.2/§11.3) to decide *what* to push and to *whom*, also out of scope
   (`domain/policies.py`'s module docstring).

Without either, a WebSocket handler here would have nothing real to deliver — accepting a
connection and never sending a `{"type":"notification",...}` frame (API Contracts §11.3's
documented server→client shape) would be inventing a connection that silently does nothing,
not implementing documented behavior. Deferred until both prerequisites exist.
"""
