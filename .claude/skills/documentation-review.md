# Skill: Documentation Review

## Purpose
Keep documentation accurate, traceable, and free of invented architecture.

## Workflow
1. Confirm every claim in the document traces to `CLAUDE.md`, `docs/business/`, or an adopted ADR in
   `docs/architecture/adr/` — flag anything that reads as invented.
2. Confirm the document doesn't contradict another approved document; if it does, report the
   conflict rather than silently resolving it.
3. Confirm implementation-status language is accurate (don't describe a scaffold as "implemented",
   don't describe implemented code as "planned").
4. Confirm terminology matches the Ch. 6 ubiquitous language (Organization, Vehicle, Device, Driver,
   Student, Parent, Route, Stop, Trip, Subscription) — no ad hoc synonyms.
5. Confirm generated docs (`docs/api/`) are not hand-edited away from their generation source.

## When to use
Before merging any change to `docs/`, module READMEs, or `.claude/` content.
