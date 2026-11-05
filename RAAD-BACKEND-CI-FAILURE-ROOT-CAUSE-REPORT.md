# RAAD-TECH — Backend GitHub Actions CI Failure Root Cause Investigation Report

**Date:** 2026-11-05  
**Investigator:** Senior Backend Engineer & QA/CI Architect  
**Investigation Status:** COMPLETE (Read-Only Root Cause Analysis)  
**Target File:** `backend/tests/integration/test_data_transfer_api_integration.py`  
**CI Context:** GitHub Actions `Backend CI` (`backend-pipeline.yml`), job `test`  
**Failed Test Class:** `DataTransferApiIntegrationTests.setUpClass`  

---

## 1. Executive Summary

During the GitHub Actions execution of the Backend CI pipeline (`backend-pipeline.yml`), step `Run integration tests (live Postgres + Redis service containers)` failed with an unhandled `asyncpg.exceptions.ForeignKeyViolationError` during `setUpClass` in `test_data_transfer_api_integration.py`.

The failure was caused by a **missing organization seed in the test fixture**. 

The test fixture attempted to insert a support assignment record linking user `'01M4ZSMKCWDG8ZW51S9YVRENM6'` to hardcoded organization `'01M4ZT3DV63S4D3SY3X0MA9YVX'`, but never inserted `'01M4ZT3DV63S4D3SY3X0MA9YVX'` into the `organizations` table. In GitHub Actions, the PostgreSQL service container starts completely empty, and Alembic migrations do not seed any organization rows. Consequently, PostgreSQL enforced the foreign key constraint `fk_support_assignments__organizations` and rejected the insert.

The test passed in the local Windows Docker environment solely because that long-running local container had an orphaned sample organization (`'Barwaaqo'`, ID: `'01M4ZT3DV63S4D3SY3X0MA9YVX'`) created on October 15, 2026.

This is strictly a **test-fixture isolation defect**, not a production code or database schema bug. The database foreign key constraint worked exactly as designed.

---

## 2. Exact Root Cause Analysis

### 2.1 File and Line Numbers
- **File:** [`backend/tests/integration/test_data_transfer_api_integration.py`](file:///C:/Dev/RAAD-TECH/backend/tests/integration/test_data_transfer_api_integration.py)
- **Lines 34–35:** Hardcoded organization ID:
  ```python
  EXISTING_ORG_ID = "01M4ZT3DV63S4D3SY3X0MA9YVX"
  NONEXISTENT_ORG_ID = "01J8Z3K9G6X8YV5T4N2R7QW999"
  ```
- **Lines 134–145 (`setUpClass`):** Direct insert into child table `support_assignments`:
  ```python
  async def seed_support():
      async with engine.begin() as conn:
          await conn.execute(
              text(
                  "INSERT INTO support_assignments (user_id, organization_id, granted_at) "
                  "VALUES ('01M4ZSMKCWDG8ZW51S9YVRENM6', '01M4ZT3DV63S4D3SY3X0MA9YVX', now()) "
                  "ON CONFLICT DO NOTHING;"
              )
          )
      await engine.dispose()

  asyncio.run(seed_support())
  ```

### 2.2 Foreign Key Architecture
Table `support_assignments` was created in migration `20260721_0930_054a850353e7_organization_create_region_and_.py` with an explicit foreign key:
```python
sa.ForeignKeyConstraint(
    ["organization_id"],
    ["organizations.id"],
    name=op.f("fk_support_assignments__organizations"),
)
```
Additionally, `organizations` requires a valid `region_id` referencing `regions.id`:
```python
sa.ForeignKeyConstraint(
    ["region_id"], ["regions.id"], name=op.f("fk_organizations__regions")
)
```
Starter regions are seeded into `regions` by migration `20260723_2058_8768136a6464_organization_seed_starter_regions.py` (e.g. `'East Africa'`, `'Middle East'`). However, **no migration seeds any rows into `organizations`**.

When `seed_support()` executed:
```sql
INSERT INTO support_assignments (user_id, organization_id, granted_at)
VALUES ('01M4ZSMKCWDG8ZW51S9YVRENM6', '01M4ZT3DV63S4D3SY3X0MA9YVX', now())
ON CONFLICT DO NOTHING;
```
PostgreSQL checked whether `'01M4ZT3DV63S4D3SY3X0MA9YVX'` existed in `organizations`. In CI, `organizations` was completely empty, triggering:
```text
asyncpg.exceptions.ForeignKeyViolationError:
insert or update on table "support_assignments" violates foreign key constraint "fk_support_assignments__organizations"
DETAIL: Key (organization_id)=(01M4ZT3DV63S4D3SY3X0MA9YVX) is not present in table "organizations".
```

### 2.3 Secondary Impact on API Routes
Even if the `support_assignments` foreign key check had been deferred, any HTTP request to the endpoints in `test_data_transfer_api_integration.py` would have failed. 
The endpoint dependency [`resolve_target_organization`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/data_transfer/api/deps.py#L58-L62) queries the database to verify the organization exists:
```python
async with org_uow:
    org = await org_uow.organizations.get_by_id(clean_org_id)
    if org is None:
        raise NotFoundError(f"Organization '{clean_org_id}' not found.")
```
Without the organization in table `organizations`, all tests targeting `EXISTING_ORG_ID` would return `404 Not Found`.

---

## 3. Why Local Testing Passed While GitHub Actions Failed

Evidence directly queried from the local Docker PostgreSQL database (`localhost:5433`):
```text
SELECT * FROM organizations WHERE id = '01M4ZT3DV63S4D3SY3X0MA9YVX';
```
Result:
```text
{
  'id': '01M4ZT3DV63S4D3SY3X0MA9YVX',
  'name': 'Barwaaqo',
  'org_type': 'school',
  'region_id': '01M4ZPZGYJENXVC8JC31DXBY94',
  'status': 'active',
  'created_at': datetime.datetime(2026, 10, 15, 12, 55, 25, 286298),
  'created_by': '01M4ZSMKCWDG8ZW51S9YVRENM3'
}
```

### Key Differences:
1. **Local Development Container (`raad-postgres`)**:
   - Started and populated on October 15, 2026.
   - Retained persistent volume state.
   - Contained pre-existing organization `'01M4ZT3DV63S4D3SY3X0MA9YVX'` (`'Barwaaqo'`).
   - The test fixture passed because the prerequisite parent record already existed from previous activity.
2. **GitHub Actions CI Environment**:
   - Starts an ephemeral, pristine `postgres:16` service container on every run.
   - Runs `alembic upgrade head` from a blank database.
   - Contains zero rows in `organizations`.
   - The missing prerequisite parent record immediately resulted in a foreign key constraint violation.

---

## 4. Production vs. Test-Fixture Classification

| Dimension | Assessment | Evidence |
| :--- | :---: | :--- |
| **Is production code affected?** | **NO** | Production endpoints (`resolve_target_organization`, `commit_import`, etc.) correctly enforce tenancy and foreign key integrity. |
| **Is database migration affected?** | **NO** | All migrations apply cleanly and maintain strict referential integrity. |
| **Is database constraint correct?** | **YES** | `fk_support_assignments__organizations` correctly prevented an orphaned foreign key. |
| **Defect Classification** | **Test Fixture Isolation Defect** | The integration test suite assumed pre-existing database state rather than creating its own isolated test fixtures. |

---

## 5. Architectural & Regression Review

1. **Multi-Tenant Architecture**:
   - RAAD-TECH strictly isolates data by `organization_id`.
   - Hardcoding an ID without seeding violates fixture independence.
2. **Support Staff Assignment Rules**:
   - `SUPPORT_STAFF` and `FINANCE_STAFF` can only access organizations explicitly linked via `support_assignments`.
   - Testing authorized finance staff requires both a valid `Organization` record and a `SupportAssignment` record.
3. **Database Constraints Integrity**:
   - Under no circumstances should `fk_support_assignments__organizations` be removed, altered, or relaxed.
   - The fix must respect the database foreign key hierarchy: `regions` → `organizations` → `support_assignments`.

---

## 6. Minimal Recommended Fix

Update `backend/tests/integration/test_data_transfer_api_integration.py` to be fully self-contained:

### 6.1 `setUpClass` Seeding Sequence:
1. Retrieve a valid `region_id` from `regions` (seeded by migration `8768136a6464`).
2. Upsert the test organization into `organizations` matching `EXISTING_ORG_ID`:
   ```sql
   INSERT INTO organizations (id, name, org_type, region_id, status, created_at, updated_at, row_version)
   VALUES (:org_id, 'Integration Test School', 'school', :region_id, 'active', now(), now(), 1)
   ON CONFLICT (id) DO NOTHING;
   ```
3. Upsert the support assignment into `support_assignments`:
   ```sql
   INSERT INTO support_assignments (user_id, organization_id, granted_at)
   VALUES ('01M4ZSMKCWDG8ZW51S9YVRENM6', :org_id, now())
   ON CONFLICT DO NOTHING;
   ```

### 6.2 `tearDownClass` Cleanup Sequence:
Clean up all records created during the test run in reverse dependency order:
```sql
DELETE FROM support_assignments WHERE organization_id = :org_id;
DELETE FROM import_batches WHERE organization_id = :org_id;
DELETE FROM student_parents WHERE student_organization_id = :org_id OR parent_organization_id = :org_id;
DELETE FROM students WHERE organization_id = :org_id;
DELETE FROM parents WHERE organization_id = :org_id;
DELETE FROM organizations WHERE id = :org_id;
```

---

## 7. Exact Commands to Reproduce & Verify

### 7.1 Reproduction in a Clean Database:
To reproduce the exact GitHub Actions failure locally, temporarily drop the pre-existing organization from PostgreSQL:
```powershell
$env:RAAD_DB__URL="postgresql+asyncpg://raad:raad@localhost:5433/raad"
cd C:\Dev\RAAD-TECH\backend
.\.venv\Scripts\python.exe -c "import asyncio, asyncpg; asyncio.run(asyncpg.connect('postgresql://raad:raad@localhost:5433/raad').then(lambda c: c.execute('DELETE FROM organizations WHERE id = ''01M4ZT3DV63S4D3SY3X0MA9YVX''')))"
.\.venv\Scripts\python.exe -m unittest tests/integration/test_data_transfer_api_integration.py -v
```
*Expected Result:* Reproduces `ForeignKeyViolationError: Key (organization_id)=(01M4ZT3DV63S4D3SY3X0MA9YVX) is not present in table "organizations"`.

### 7.2 Post-Fix Verification:
```powershell
$env:RAAD_AUTH__JWT_SECRET_KEY="dev-only-change-me"
$env:RAAD_DB__URL="postgresql+asyncpg://raad:raad@localhost:5433/raad"
cd C:\Dev\RAAD-TECH\backend
.\.venv\Scripts\python.exe -m unittest tests/integration/test_data_transfer_api_integration.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests/integration -v
```
*Expected Result:* All 14 tests in `test_data_transfer_api_integration.py` and all 428 integration tests pass on fresh or existing databases.

---

## 8. Summary of Findings

- **Root Cause Confirmed**: `test_data_transfer_api_integration.py` seeded `support_assignments` before `organizations` had the target organization record.
- **Production Safety**: Zero production risk. Database foreign keys and API authorization logic functioned as intended.
- **Readiness for Fix**: Fix is strictly confined to the test setup in `test_data_transfer_api_integration.py`. Awaiting user approval before editing.
