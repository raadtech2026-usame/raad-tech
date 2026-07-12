"""Domain services for the `organization` module (Backend LLD §5.1).

None are defined in this phase. The one candidate — enforcing global region-name uniqueness
across `Region`s — needs a repository query (I/O) to check existing rows, which makes it an
*application*-layer concern (orchestration via the repository), not a domain service (domain
services are stateless operations over already-loaded entities, LLD §5.1), mirroring
`iam.domain.services`'s identical reasoning for email/phone uniqueness. `Organization`'s and
`Region`'s own constructors already enforce everything that's a pure function of their own
fields. Add a domain service here only if a future rule genuinely needs to span two loaded
aggregates without I/O.
"""
