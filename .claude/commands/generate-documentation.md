# Command: Generate Documentation

## Purpose
Produce or refresh documentation for a module/service, keeping it traceable to approved sources.

## Usage
`/generate-documentation <target-path>`

## Behavior
1. Loads `.claude/skills/documentation-review.md` as the quality bar.
2. Reads the current implementation state of `<target-path>` and the relevant `docs/business/`
   section(s).
3. Writes or updates the corresponding README/doc, stating implementation status accurately.
4. Flags (does not silently resolve) any conflict discovered between the code and the approved
   documentation.

## Preconditions
- `<target-path>` exists in the repository.
