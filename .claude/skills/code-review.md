# Skill: Code Review

## Purpose
Review backend/frontend/mobile code changes for correctness and architectural compliance before
merge.

## Workflow
1. Confirm the change maps to an approved requirement (business rule, API contract, or ADR) — flag
   anything that looks like invented scope.
2. Check module boundaries: no cross-module DB reads, no domain-layer import of infra/framework code,
   dependency direction respected (`api -> application -> domain`).
3. Check tenancy: every new query against a tenant-owned table is scoped by `organization_id`.
4. Check the safety-vs-billing invariant is untouched or correctly extended (safety capabilities
   never billing-gated).
5. Check video-access changes never introduce a Parent-reachable code path.
6. Check naming conventions against `.claude/rules/naming.md`.
7. Check for missing tests on safety-critical invariants per `.claude/rules/testing.md`.
8. Check for unnecessary complexity: no speculative abstractions, no unrequested features, no
   backwards-compatibility shims for code that can simply be changed.

## When to use
Before merging any non-trivial change; always before merging anything touching tenancy, video
access, or billing/safety policy.
