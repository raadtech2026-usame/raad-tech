# Command: Create Module

## Purpose
Invoke the "Creating Modules" skill to scaffold or extend a backend bounded-context module.

## Usage
`/create-module <context-name>`

## Behavior
1. Loads `.claude/skills/creating-modules.md`.
2. Validates `<context-name>` against the fixed ten bounded contexts
   (`.claude/rules/architecture.md`). Refuses to proceed on an unrecognized name without an ADR.
3. Executes the module-creation workflow: domain → application → infra → api → events → tests.
4. Reports the files created/changed and any open questions (e.g. missing contract detail in
   `docs/business/`) back to the requester instead of guessing.

## Preconditions
- `.claude/skills/reading-architecture.md` context has been established for this session.
