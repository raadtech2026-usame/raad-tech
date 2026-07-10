# Skill: Reading Architecture

## Purpose
Establish correct context before any implementation or review task by reading the approved
documentation in the right order and noting anything that looks inconsistent.

## Workflow
1. Read `CLAUDE.md` first — product scope and durable guardrails.
2. Read `docs/business/Project_Brief_v1.md` for business context, entities, and rules (Ch. 1–11).
3. Read `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` (including its addendum) for
   system/module/deployment/security architecture and the locked decisions (D1–D6).
4. Read the relevant Phase 3 design doc for the area in question: Backend LLD (3.1), Database Design
   (3.2), API Contracts (3.3), JT808 Technical Design (3.4), or JT1078 Technical Design (3.5).
5. Check `docs/architecture/adr/` for any formally adopted decisions that supersede or refine the
   above.
6. If any two sources disagree (e.g. a later revision note superseding an earlier decision), stop and
   report the conflict rather than picking one silently.
7. Only after this pass, proceed to the actual task.

## When to use
Before any non-trivial implementation, review, or structural change — especially before creating new
modules, tables, endpoints, or services.
