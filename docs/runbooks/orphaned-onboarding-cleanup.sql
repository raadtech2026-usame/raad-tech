-- ============================================================================================
-- Orphaned-organization cleanup — generated 2026-09-09
--
-- REVIEW BEFORE RUNNING. Nothing here has been executed. This file is a report first and a
-- script second; read the inventory, decide, then uncomment the block you want.
--
-- WHAT THESE ROWS ARE
-- -------------------
-- Between 2026-09-08 08:21 and 09:05 an operator tried to onboard two organizations and
-- retried several times. Each attempt committed the `organizations` row first, then failed at
-- the admin-user step, and the old code reported success anyway. The result is five
-- organizations that have never had a user, a student, a vehicle or a subscription — nobody can
-- log in to any of them and nothing references them.
--
-- The defect that produced them is fixed (2026-09-09): onboarding now validates the plan before
-- writing anything, compensates by deactivating the organization and disabling the admin if a
-- later step fails, and re-raises so the API never answers 201 for an incomplete onboarding.
-- These five are historical residue, not an ongoing leak.
--
-- INVENTORY (verified against the live database at generation time)
-- -----------------------------------------------------------------
--   id                          name                created              users subs students vehicles
--   01M201PBN30EBAG0T9D345B66M  al jazeera school   2026-09-08 08:21:00   0     0     0        0
--   01M201PVF024F77GZX08417QXX  al jazeera school   2026-09-08 08:21:16   0     0     0        0
--   01M2045Y2K4S9QMHX50KNYTR62  nuro warsame        2026-09-08 09:04:28   0     0     0        0
--   01M204692QHPGJTBGH3KNVNCDW  nuro warsame        2026-09-08 09:04:39   0     0     0        0
--   01M2046YVH2E5VV4T2AQ6ETQDK  nuro warsame        2026-09-08 09:05:01   0     0     0        0
--
-- The surviving real organizations — "al jazeera school" 01M201Q7R4S8NN95GXWRBR6NKF and
-- "nuro warsame" 01M2047ATW42D6Q0F3PARZYFN6, the last attempt of each pair — are NOT in this
-- list. They have users and were given subscriptions by the backfill. Do not touch them.
--
-- WHICH OPTION TO USE
-- -------------------
-- Option A (deactivate) is the recommended default and is reversible. It keeps the audit trail
-- intact, which matters because these rows are evidence of a real production incident.
-- Option B (delete) is irreversible and is only appropriate if you are certain you want the
-- incident's residue gone from the database entirely.
--
-- Run ONE of them. Both are wrapped in a transaction and both re-verify the safety condition
-- (no users) inside the statement, so a row that has gained a user since this file was written
-- is skipped automatically rather than acted on from a stale list.
-- ============================================================================================

\set ON_ERROR_STOP on

-- --------------------------------------------------------------------------------------------
-- FIRST: re-verify. Run this on its own and confirm it returns exactly the five rows above.
-- If it returns anything else, STOP — the database has changed since this file was generated.
-- --------------------------------------------------------------------------------------------
SELECT o.id,
       o.name,
       o.status,
       o.created_at::timestamp(0) AS created,
       (SELECT count(*) FROM users         u  WHERE u.organization_id  = o.id) AS users,
       (SELECT count(*) FROM subscriptions s  WHERE s.organization_id  = o.id) AS subscriptions,
       (SELECT count(*) FROM students      st WHERE st.organization_id = o.id) AS students,
       (SELECT count(*) FROM vehicles      v  WHERE v.organization_id  = o.id) AS vehicles
FROM organizations o
WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.organization_id = o.id)
ORDER BY o.created_at;


-- ============================================================================================
-- OPTION A — RECOMMENDED. Deactivate, keep everything. Reversible.
--
-- The organizations stop appearing as active in the Founder's list and cannot be used, but every
-- row and every audit entry survives. Note this bypasses the domain aggregate, so no
-- `OrganizationDeactivated` event is raised and no audit row is written for the deactivation
-- itself — acceptable for a one-off remediation of rows that were never legitimately created,
-- and the reason the statement stamps `updated_by` so the change is still attributable.
-- ============================================================================================
-- BEGIN;
--
-- UPDATE organizations
--    SET status     = 'inactive',
--        updated_at = now(),
--        updated_by = NULL
--  WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.organization_id = organizations.id)
--    AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.organization_id = organizations.id)
--    AND status <> 'inactive';
--
-- -- Expect: UPDATE 5
-- COMMIT;


-- ============================================================================================
-- OPTION B — IRREVERSIBLE. Delete the organizations and their audit trail.
--
-- Only use this if you want no trace of the failed attempts. `audit_entries` is documented as
-- append-only and immutable (`.claude/rules/database.md` #7), so deleting from it is a
-- deliberate exception to a stated invariant — which is the main reason Option A is preferred.
-- ============================================================================================
-- BEGIN;
--
-- CREATE TEMP TABLE _orphans AS
-- SELECT o.id
--   FROM organizations o
--  WHERE NOT EXISTS (SELECT 1 FROM users         u  WHERE u.organization_id  = o.id)
--    AND NOT EXISTS (SELECT 1 FROM subscriptions s  WHERE s.organization_id  = o.id)
--    AND NOT EXISTS (SELECT 1 FROM students      st WHERE st.organization_id = o.id)
--    AND NOT EXISTS (SELECT 1 FROM vehicles      v  WHERE v.organization_id  = o.id);
--
-- SELECT count(*) AS about_to_delete FROM _orphans;   -- expect 5; abort if not
--
-- DELETE FROM audit_entries WHERE organization_id IN (SELECT id FROM _orphans);
-- DELETE FROM outbox        WHERE aggregate_id    IN (SELECT id FROM _orphans);
-- DELETE FROM organizations WHERE id              IN (SELECT id FROM _orphans);
--
-- COMMIT;
