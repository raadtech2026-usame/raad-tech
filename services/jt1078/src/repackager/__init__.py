"""Repackager — translates reassembled JT/T 1078 frame payloads (`ingest/frame_reassembly.
ReassembledFrame`) into the chosen viewer-facing container without re-encoding the underlying
video/audio (`.claude/rules/jt1078.md` #5: "media is repackaged, never passed through raw... media
is repackaged, never transcode"). `flv_muxer.py` implements FLV (ADR-0024 §14: WS-FLV for the
first live-transport cut, and the same container HLS's own `.ts`/fMP4 segments would eventually
wrap for playback).
"""
