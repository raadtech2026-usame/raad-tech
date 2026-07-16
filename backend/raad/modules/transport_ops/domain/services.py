"""Domain services for the `transport_ops` module (Backend LLD §5.1).

None are defined in this phase. `Student`'s own constructor already enforces everything that's
a pure function of its own fields (non-empty/length-bounded `full_name`/`external_ref`). The
one candidate that might look like a domain service — "does this student already exist" /
uniqueness checking — needs a repository query (I/O) to check existing rows, which makes it an
*application*-layer concern (orchestration via the repository), not a domain service (domain
services are stateless operations over already-loaded entities, LLD §5.1), mirroring
`organization.domain.services`'s identical reasoning for region-name uniqueness. Add a domain
service here only if a future rule genuinely needs to span two loaded aggregates without I/O —
e.g. once `StudentAssignment` (a later phase, deliberately out of this phase's scope per
`entities.py`'s module docstring) exists alongside `Student`.
"""
