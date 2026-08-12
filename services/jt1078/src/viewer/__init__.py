"""Viewer Edge — token-gated delivery of the repackaged stream to an authorized web client
(ADR-0024 §14: WS-FLV for the first live-transport cut). `websocket_server.py` hand-rolls the
minimal RFC 6455 surface this needs (handshake + binary frames + close/ping detection) rather
than adding a new dependency — mirroring `services/device-gateway`'s own precedent of hand-
rolling a closed, well-specified wire protocol at production quality
(`.claude/rules/workflow.md` #1/#2: a WebSocket *library* was not proposed or approved).
"""
