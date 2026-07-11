"""Domain services for the `iam` module (Backend LLD §5.1).

None are defined in this phase. The one candidate — enforcing global email/phone uniqueness
across `User`s — needs a repository query (I/O) to check existing rows, which makes it an
*application*-layer concern (orchestration via the repository), not a domain service (domain
services are stateless operations over already-loaded entities, LLD §5.1). `User`'s own
constructor already enforces everything that's a pure function of its own fields (email-or-
phone presence, org-scope-vs-role). Add a domain service here only if a future rule genuinely
needs to span two loaded aggregates without I/O.
"""
