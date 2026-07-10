# Rule: Git

1. Create new commits rather than amending, unless explicitly asked otherwise.
2. Never force-push, reset --hard, or skip hooks without explicit instruction.
3. Commit messages describe *why*, not just *what* — reference the business rule or architecture
   section a change satisfies where relevant (e.g. "enforce D4 safety-over-billing invariant per
   Phase 2 §12.6").
4. Never commit `.env` files, credentials, or other secrets. `.env.example` files contain no real
   values.
5. Migrations are committed as part of the same change that requires them — never as an
   afterthought in a separate, unrelated commit.
6. Structural/scaffold-only commits (folders, placeholders, no logic) should be labeled as such in
   the commit message so history clearly separates scaffolding from implementation.
