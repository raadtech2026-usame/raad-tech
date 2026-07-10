# Command: Generate Tests

## Purpose
Produce test coverage for a module/service change, following RAAD's test taxonomy.

## Usage
`/generate-tests <target-path>`

## Behavior
1. Loads `.claude/rules/testing.md`.
2. Determines the correct test category for `<target-path>` (unit / integration / contract /
   architecture for backend; per-service tests for JT808/JT1078; e2e/load for cross-service flows).
3. Generates tests covering: the happy path, documented business-rule edge cases (Ch. 7 of the
   Project Brief), and any safety-critical invariant the target touches.
4. Never generates a test for a scenario that cannot occur per the documented business rules.

## Preconditions
- The target code path exists and its business-rule requirements are identifiable from
  `docs/business/`.
