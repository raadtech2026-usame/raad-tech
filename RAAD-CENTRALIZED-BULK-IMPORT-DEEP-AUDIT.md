# RAAD-TECH — Centralized Organization Bulk Data Import
## Deep System Audit & Implementation Blueprint

**Document ID:** RAAD-AUDIT-2026-11-CENTRALIZED-IMPORT  
**Author:** Antigravity (Principal Engineering Audit)  
**Repository:** `RAAD-TECH` — FastAPI Modular Monolith + React/TypeScript  
**Branch:** `main` (clean — no uncommitted changes at audit time)  
**Audit Date:** 2026-11-05  
**Status:** READ-ONLY — No code modified. Awaiting implementation approval.

---

## Section 1 — Executive Summary

### 1.1 Business Objective

The business requirement is a **centralized, RAAD-TECH Super Admin Bulk Data Import Center** — a capability exclusively owned by RAAD-TECH platform administrators (Founder, Regional Manager, Support Staff). Organizations (schools/clients) **do not** perform imports. They receive Excel templates, fill them in, and return them. RAAD-TECH staff then perform all technical import operations on their behalf via the central Admin Dashboard.

### 1.2 Current Implementation State

A bulk import prototype exists, but it is **architecturally misplaced, insufficiently secured, and incomplete**. Specifically:

| Concern | Finding |
|---|---|
| **Location** | Mounted at `/api/v1/imports` — accessible via the Org Admin dashboard |
| **Permission gate** | Checks `transport_ops.students.create` / `transport_ops.parents.create` — Org Admin permissions |
| **Supported entities** | Students and Parents only |
| **Organization targeting** | Reads `principal.org_id` — can only import into the caller's own org |
| **Import history** | None — no database table, no batch record |
| **Async processing** | None — synchronous, risks timeout on large batches |
| **Formula sanitization** | None |
| **File size limits** | None |
| **Admin Dashboard integration** | None — not reachable from `/platform/organizations/:organizationId` |
| **Multi-sheet workbook** | Not supported |

### 1.3 High-Level Conclusion

The existing code is a **reusable foundation**, not a complete solution. Approximately 35% of the target system exists. The remaining 65% — including the correct placement, correct RBAC, organization targeting, batch history, broader entity support, and Admin Dashboard integration — must be built.

> [!IMPORTANT]
> The existing `ImportApplicationService` and `BulkImportDialog` must **not** be deleted. They must be **relocated and upgraded** as part of a new `data_transfer` bounded context, with the existing frontend dialog reused for the new Admin Dashboard panel.

---

## Section 2 — Existing Implementation Inventory

### 2.1 Backend — Import/Export Files

| File | Description |
|---|---|
| [`backend/raad/modules/transport_ops/application/import_services.py`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/transport_ops/application/import_services.py) | `ImportApplicationService` — template generator, file parser, dry-run validator, atomic commit for Students and Parents |
| [`backend/raad/modules/transport_ops/api/imports_router.py`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/transport_ops/api/imports_router.py) | `imports_router` — 3 routes: `GET /{type}/template`, `POST /{type}/validate`, `POST /{type}/commit` |
| [`backend/raad/modules/transport_ops/api/schemas.py`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/transport_ops/api/schemas.py) | `ImportValidationSummary`, `ImportCommitSummary`, `ImportRowError`, `ImportRowPreview` Pydantic schemas |
| [`backend/raad/modules/transport_ops/api/deps.py`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/transport_ops/api/deps.py) | `get_import_service` DI factory |
| [`backend/raad/modules/reporting/application/export_service.py`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/reporting/application/export_service.py) | `ReportExportService` — renders `ReportTable` to XLSX/PDF via `openpyxl`/`reportlab` |
| [`backend/raad/modules/reporting/infra/renderers.py`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/reporting/infra/renderers.py) | `ExcelReportRenderer` — `openpyxl` XLSX renderer with RAAD brand styling |

### 2.2 Backend — API Mounting

| Route Prefix | Router | Mounted in |
|---|---|---|
| `/api/v1/imports` | `imports_router` | [`backend/raad/interfaces/http/api_v1.py`](file:///C:/Dev/RAAD-TECH/backend/raad/interfaces/http/api_v1.py) |

### 2.3 Backend — Core Infrastructure (Reusable)

| File | Capability |
|---|---|
| [`backend/raad/core/db/unit_of_work.py`](file:///C:/Dev/RAAD-TECH/backend/raad/core/db/unit_of_work.py) | `SqlAlchemyUnitOfWork` — atomic transactions + topological flush ordering (`_flush_in_dependency_order`) |
| [`backend/raad/core/tenancy/scope.py`](file:///C:/Dev/RAAD-TECH/backend/raad/core/tenancy/scope.py) | `TenantRegionScope` — `organization_ids: frozenset[str] | None`; unrestricted for Founder |
| [`backend/raad/core/tenancy/principal.py`](file:///C:/Dev/RAAD-TECH/backend/raad/core/tenancy/principal.py) | `Role` enum — `FOUNDER`, `REGIONAL_MANAGER`, `SUPPORT_STAFF`, `FINANCE_STAFF`, `ORG_ADMIN`, `DRIVER`, `PARENT` |
| [`backend/raad/core/security/permissions.py`](file:///C:/Dev/RAAD-TECH/backend/raad/core/security/permissions.py) | `PermissionEvaluator` — queries `role_permissions` table (ADR-0004) |
| [`backend/raad/core/audit/writer.py`](file:///C:/Dev/RAAD-TECH/backend/raad/core/audit/writer.py) | `AuditWriter` — transactional audit log within `UnitOfWork.commit()` |
| [`backend/raad/core/ids/generator.py`](file:///C:/Dev/RAAD-TECH/backend/raad/core/ids/generator.py) | `IdGenerator` — ULID generation |

### 2.4 Frontend — Import Files

| File | Description |
|---|---|
| [`frontend/src/features/transport-ops/imports/BulkImportDialog.tsx`](file:///C:/Dev/RAAD-TECH/frontend/src/features/transport-ops/imports/BulkImportDialog.tsx) | 3-step modal wizard: Upload → Validate/Preview → Summary |
| [`frontend/src/features/transport-ops/imports/api.ts`](file:///C:/Dev/RAAD-TECH/frontend/src/features/transport-ops/imports/api.ts) | `downloadImportTemplate`, `validateImport`, `commitImport` API calls |
| [`frontend/src/features/transport-ops/students/StudentsPage.tsx`](file:///C:/Dev/RAAD-TECH/frontend/src/features/transport-ops/students/StudentsPage.tsx) | Mounts `BulkImportDialog` with `resourceType="students"` |
| [`frontend/src/features/transport-ops/parents/ParentsPage.tsx`](file:///C:/Dev/RAAD-TECH/frontend/src/features/transport-ops/parents/ParentsPage.tsx) | Mounts `BulkImportDialog` with `resourceType="parents"` |

### 2.5 Frontend — Admin Dashboard Organization Pages

| File | Description |
|---|---|
| [`frontend/src/features/organizations/details/OrganizationDetailsPage.tsx`](file:///C:/Dev/RAAD-TECH/frontend/src/features/organizations/details/OrganizationDetailsPage.tsx) | Platform-only detail page for one organization — mounted at `/platform/organizations/:organizationId` |
| [`frontend/src/features/organizations/details/tabs.tsx`](file:///C:/Dev/RAAD-TECH/frontend/src/features/organizations/details/tabs.tsx) | Defines `OrganizationDetailTabId` union — currently 15 tabs across 4 groups |
| [`frontend/src/features/organizations/details/OrganizationTabPanel.tsx`](file:///C:/Dev/RAAD-TECH/frontend/src/features/organizations/details/OrganizationTabPanel.tsx) | Renders tab content — `switch (tab)` dispatcher |
| [`frontend/src/app/layout/navConfig.ts`](file:///C:/Dev/RAAD-TECH/frontend/src/app/layout/navConfig.ts) | `platformNav` (platform roles) and `organizationNav` (org_admin only) |
| [`frontend/src/app/router.tsx`](file:///C:/Dev/RAAD-TECH/frontend/src/app/router.tsx) | Route definitions — `PLATFORM_ROLES = ["founder","regional_manager","support_staff","finance_staff"]`, `ORGANIZATION_ROLES = ["org_admin"]` |

### 2.6 Backend — Domain Entities (Confirmed Existing)

| Entity | Table | Module | Key Fields |
|---|---|---|---|
| Organization | `organizations` | `organization` | `id`, `name`, `org_type`, `status`, `region_id` |
| IAM User | `users` | `iam` | `id`, `organization_id`, `role`, `email`, `phone` |
| Student | `students` | `transport_ops` | `id`, `organization_id`, `full_name`, `external_ref`, `gender`, `dob`, `notes` |
| Parent | `parents` | `transport_ops` | `id`, `organization_id`, `user_id`, `full_name`, `phone`, `alternate_phone`, `address` |
| StudentParent | `student_parents` | `transport_ops` | `student_id`, `parent_id`, `relationship`, `is_primary` |
| Transport Staff | `transport_staff` | `transport_ops` | `id`, `organization_id`, `full_name`, `phone`, `employee_ref`, `role_id` |
| Driver | `drivers` | `transport_ops` | `id`, `organization_id`, `user_id`, `staff_id`, `license_no` |
| Vehicle | `vehicles` | `fleet_device` | `id`, `organization_id`, `plate_no`, `label`, `capacity` |
| Route | `routes` | `transport_ops` | `id`, `organization_id`, `name`, `status` |
| Stop | `stops` | `transport_ops` | `id`, `organization_id`, `route_id`, `name`, `latitude`, `longitude`, `sequence_no` |
| StudentAssignment | `student_assignments` | `transport_ops` | `id`, `organization_id`, `student_id`, `route_id`, `pickup_stop_id`, `dropoff_stop_id`, `vehicle_id` |

### 2.7 Confirmed Missing Entities

| Entity | Status | Impact |
|---|---|---|
| Academic Year | **MISSING** | Cannot scope students to academic year |
| Grade / Class | **MISSING** — stored in `students.notes` as text | Cannot create structured grade dropdowns |
| Import Batch | **MISSING** | No persistent import history |
| Import Batch Error | **MISSING** | No downloadable error report |

---

## Section 3 — Existing vs Required Comparison

| Requirement | Existing Implementation | Status | Evidence | Required Action |
|---|---|---|---|---|
| Super Admin can initiate import | Org Admin can initiate import | **DEFECTIVE** | `check_import_permission` checks `transport_ops.students.create` — an Org Admin permission | Add `data_transfer.import.execute` permission; seed for platform roles only |
| Import initiates from Admin Dashboard | Mounted in Org Admin Student/Parent pages | **DEFECTIVE** | `StudentsPage.tsx`, `ParentsPage.tsx` mount `BulkImportDialog` | Add "Data Import" tab to `OrganizationDetailsPage` tabs |
| Super Admin selects target organization | Not supported — uses `principal.org_id` | **MISSING** | `imports_router.py` L132: `org_id = principal.org_id or ""` | Accept explicit `organization_id` path param; validate against scope |
| Tenant isolation enforced in backend | Org_id from JWT, not from explicit org selection | **DEFECTIVE** | `import_services.py` L557: `organization_id: str` passed from router which reads `principal.org_id` | Replace with scope-validated org_id: `scope.allows(organization_id)` |
| Import students | Supported | **IMPLEMENTED** | `import_services.py` — `norm_type == "students"` branch | Relocate to new module |
| Import parents | Supported | **IMPLEMENTED** | `import_services.py` — `norm_type == "parents"` branch | Relocate to new module |
| Import transport staff | Not supported | **MISSING** | No `transport_staff` branch in `import_services.py` | Build staff importer |
| Import vehicles | Not supported | **MISSING** | No vehicle entity import | Build fleet importer |
| Import routes and stops | Not supported | **MISSING** | No route/stop import | Build route importer |
| Import student assignments | Not supported | **MISSING** | No assignment import | Build assignment importer |
| Excel template generation | Supported — students and parents | **PARTIALLY IMPLEMENTED** | `import_services.py` L217 `generate_template()` | Extend to all entities; add dropdowns and validation |
| In-cell Excel dropdowns | Not present | **MISSING** | No `DataValidation` in `generate_template()` | Add `openpyxl.DataValidation` for gender, status, role enums |
| Template versioning | Not present | **MISSING** | Templates have no version identifier | Add `TEMPLATE_VERSION` metadata cell |
| Multi-sheet workbook upload | Not supported | **MISSING** | Parser reads `wb.active` only | Build multi-sheet parser |
| File size limit | Not enforced | **MISSING** | No `Content-Length` check in `_extract_upload()` | Reject files > 15 MB |
| Formula injection sanitization | Not implemented | **MISSING** | Audit doc identified this gap; no implementation found | Add cell sanitizer stripping `=`, `+`, `-`, `@` prefix |
| Validation dry-run | Supported | **IMPLEMENTED** | `validate_import()` returns `ImportValidationResult` | Relocate; extend for new entities |
| DB duplicate detection | Supported (phone, admission_no) | **PARTIALLY IMPLEMENTED** | Checks in-file duplicates; queries existing records | Extend for vehicles (plate_no), staff (employee_ref) |
| Cross-entity relational validation | Partial — route name checked for students | **PARTIALLY IMPLEMENTED** | `import_services.py` L462 route validation | Extend for stop→route, assignment→student/route |
| Atomic batch commit | Supported | **IMPLEMENTED** | `uow.commit()` after all inserts | Relocate |
| Topological insert ordering | Supported | **IMPLEMENTED** | `_flush_in_dependency_order()` in `SqlAlchemyUnitOfWork` | No change needed |
| Parent IAM user provisioning | Supported | **IMPLEMENTED** | `UserProvisioningPort.create_user_with_temporary_password()` | Relocate |
| Import audit trail | Partial — `AuditWriter` records individual entity events | **PARTIALLY IMPLEMENTED** | No `ImportBatch` aggregate record | Add `ImportBatch` domain entity and DB table |
| Import history table | Not present | **MISSING** | No `import_batches` table in any migration | Create migration + domain entity |
| Downloadable error report workbook | Not present | **MISSING** | No XLSX error export in current service | Build error workbook generator |
| Synchronous execution risk | Not mitigated | **MISSING** | All execution in ASGI request cycle | Accept for MVP; flag for async worker phase |
| Organization Admin blocked from import | Not enforced | **DEFECTIVE** | Org Admin holds `transport_ops.students.create` permission — can call existing endpoints | Remove import endpoints from Org Admin permission scope; create separate platform-only permission |
| Round-trip export (RAAD_SYSTEM_ID) | Not implemented | **MISSING** | `export_service.py` renders report tables, no entity ULID column | Build export engine with ULID column |
| Import history UI | Not present | **MISSING** | No frontend component | Build history panel in Admin Dashboard org detail |
| Admin Dashboard "Data Import" tab | Not present | **MISSING** | `tabs.tsx` has no `data_import` tab | Add tab to `OrganizationDetailTabId` |
| Somali phone E.164 normalization | Implemented | **IMPLEMENTED** | `normalize_somali_phone()` in `import_services.py` L115 | Relocate |
| Date parsing (multi-format) | Implemented | **IMPLEMENTED** | `_parse_date()` in `import_services.py` L154 | Relocate |
| Column alias mapping | Implemented (basic) | **PARTIALLY IMPLEMENTED** | `_normalize_row_keys()` alias dictionary | Extend for new entity columns |
| Validation error display (frontend) | Implemented | **IMPLEMENTED** | `BulkImportDialog.tsx` step 2 | Reuse in new Admin panel |
| Security — no cross-org data leak | Partial — only scoped by JWT org_id | **DEFECTIVE** | Platform roles have `org_id=None`; org_id comes from `principal.org_id` which is `None` for RAAD staff | Add explicit org_id URL param with backend scope validation |

---

## Section 4 — Current Architecture

### 4.1 Backend Layering

```
raad/
├── core/                        # Shared kernel — never imports modules
│   ├── db/unit_of_work.py       # SqlAlchemyUnitOfWork — transactions + topological flush
│   ├── tenancy/principal.py     # Principal dataclass + Role enum
│   ├── tenancy/scope.py         # TenantRegionScope — frozenset of allowed org IDs
│   ├── tenancy/resolver.py      # ScopeResolver — resolves scope from principal
│   ├── security/permissions.py  # PermissionEvaluator + Permission type
│   └── audit/writer.py          # AuditWriter — transactional audit entries
│
├── interfaces/http/
│   ├── api_v1.py               # Mounts ALL module routers
│   └── deps.py                 # get_principal, get_scope, require_permission
│
└── modules/
    ├── transport_ops/
    │   ├── api/imports_router.py          # ← EXISTING import endpoints (WRONG LOCATION)
    │   └── application/import_services.py # ← EXISTING service (REUSABLE)
    └── reporting/
        ├── application/export_service.py  # ReportExportService
        └── infra/renderers.py             # ExcelReportRenderer (openpyxl)
```

### 4.2 RBAC Architecture (ADR-0004)

The `role_permissions` database table is seeded with the full matrix. `PermissionEvaluator` queries it on every request. No in-memory cache exists (acceptable per ADR-0004).

**Platform roles** (`founder`, `regional_manager`, `support_staff`, `finance_staff`) have `org_id = None` in their JWT Principal. Their scope is resolved by `ScopeResolver` to `TenantRegionScope(organization_ids=None)` — meaning **unrestricted access to all organizations**.

**Org Admin** has `org_id = <their organization's ULID>` in the JWT. Their scope resolves to a single-org frozenset.

### 4.3 Current Import Permission Flaw

The current `check_import_permission` in [`imports_router.py`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/transport_ops/api/imports_router.py#L38-L59) checks:
- `transport_ops.students.create` for student imports
- `transport_ops.parents.create` for parent imports

Both of these permissions are held by **Org Admin** (per the ADR-0004 migration `5437a5d1651b` seed matrix). This means an Org Admin can currently call the import endpoint directly — the exact scenario the business requirement prohibits.

Additionally, `org_id = principal.org_id or ""` on line 132 means that when a **platform role** (who has `org_id=None`) calls this endpoint, the organization ID becomes an **empty string**, importing data into no organization.

### 4.4 Frontend Architecture

```
frontend/src/
├── app/
│   ├── router.tsx               # Defines /platform (PLATFORM_ROLES) and /org (ORGANIZATION_ROLES) trees
│   └── layout/navConfig.ts      # platformNav (no "Data Import"), organizationNav (no "Data Import")
└── features/
    ├── organizations/
    │   └── details/
    │       ├── OrganizationDetailsPage.tsx  # /platform/organizations/:id — PLATFORM_ROLES only
    │       ├── tabs.tsx                     # 15 existing tabs — no "data_import" tab
    │       └── OrganizationTabPanel.tsx     # Tab content dispatcher
    └── transport-ops/
        └── imports/
            ├── BulkImportDialog.tsx         # 3-step wizard — REUSABLE
            └── api.ts                       # API calls to /api/v1/imports/*
```

The `OrganizationDetailsPage` is **already the correct location** for the new feature. It lives exclusively in `PLATFORM_ROUTES`, is gated by `PLATFORM_ROLES`, and receives `organizationId` from the URL — exactly the organization-targeting mechanism needed.

---

## Section 5 — Critical Gaps

### 5.1 Security — CRITICAL

1. **Wrong permission gate**: Import endpoints currently gated on Org Admin permissions (`transport_ops.students.create`). An Org Admin can bypass the UI and call the API directly.
2. **Missing org_id from URL**: For platform roles, `principal.org_id` is `None`. The existing code uses `principal.org_id or ""` — producing an empty string organization ID on every platform-role import attempt. This means the existing endpoint is **currently broken for the intended platform-role caller**.
3. **No scope validation**: The import service receives an `organization_id` string but does not validate it against `TenantRegionScope.allows()`. A determined attacker with the right permission could supply any org ID.

### 5.2 Business Logic — HIGH

4. **No import history**: There is no `ImportBatch` table. RAAD-TECH staff cannot see what was imported, when, by whom, or into which organization.
5. **No downloadable error report**: When validation finds errors, staff must manually copy error messages. No XLSX error workbook download exists.
6. **Only 2 of 10 entity types**: Only students and parents are supported. Routes, stops, vehicles, staff, drivers, assignments, and billing profiles cannot be bulk-imported.

### 5.3 Data Integrity — HIGH

7. **No formula injection protection**: Cells starting with `=`, `+`, `-`, `@` are not sanitized. Malicious content in uploaded files could execute code when staff open error reports in Excel.
8. **No file size limit**: The router accepts files of any size, risking memory exhaustion on large uploads.
9. **Synchronous commit on large batches**: Password hashing for 500 parents × ~150ms = 75 seconds — well over typical Nginx timeout of 60 seconds.

### 5.4 UX and Workflow — MEDIUM

10. **No Admin Dashboard entry point**: There is no "Data Import" tab on `OrganizationDetailsPage`. Staff have no UI to reach this feature from the platform dashboard.
11. **No organization selection**: The existing dialog is designed for an Org Admin operating within their own tenant. It has no concept of "import data into this selected organization."
12. **No template variety**: Only students and parents templates exist. No fleet, routes, or staff templates are generated.

### 5.5 Architecture — MEDIUM

13. **Wrong bounded context**: Import services live in `transport_ops`, which is correct for transport-domain entities but wrong for a cross-module capability spanning fleet, IAM, and finance.
14. **Existing audit document was for Org Admin, not Super Admin**: The `CLIENT-DATA-IMPORT-EXPORT-AUDIT.md` proposed `/org/data-management` and seeded `org_admin` permissions for the import feature. This is the **wrong actor** per the current business requirement. The new audit reverses this design decision completely.

---

## Section 6 — Proposed Centralized Workflow

```
Super Admin opens /platform/organizations
        ↓
Finds target organization → clicks row → navigates to /platform/organizations/:organizationId
        ↓
Sees OrganizationDetailsPage with existing tabs (Overview, Users, Vehicles, etc.)
        ↓
NEW TAB: "Data Import" (added to "operations" tab group)
        ↓
Clicks "Data Import" tab
        ↓
Sees: [Download Templates] | [Upload & Import] | [Import History]
        ↓
Step 1: Select template type (Students, Parents, Staff, Fleet, Routes+Stops, Assignments)
         Download official RAAD XLSX template
        ↓
Step 2: Upload completed Excel workbook (sent back by the organization)
        ↓
Step 3: Backend validates → returns row-level diagnostics (valid/invalid/duplicate counts)
         Frontend displays validation preview table
        ↓
Step 4: Super Admin reviews — if errors exist:
         Option A: Download annotated error XLSX → correct externally → re-upload
         Option B: Proceed with skip-invalid strategy (import valid rows, skip failed rows)
        ↓
Step 5: Super Admin confirms import
        ↓
Step 6: Backend executes atomic import into the SELECTED organization's tenant scope
         - organization_id comes from URL param, NOT from principal.org_id
         - backend validates: scope.allows(organization_id) must be True
         - all entities written with correct organization_id
         - audit entry recorded: actor=super_admin, org=target_org, batch_id=...
        ↓
Step 7: Import Summary displayed
         - Created / Updated / Skipped counts
         - If any errors: download error report XLSX
         - Import batch recorded in import_batches table with full metadata
```

---

## Section 7 — Recommended Architecture

### 7.1 New Module: `raad.modules.data_transfer`

Create a new bounded context. This keeps import logic separate from `transport_ops` and correctly models it as a cross-module orchestration capability.

```
backend/raad/modules/data_transfer/
├── __init__.py
├── api/
│   ├── __init__.py
│   ├── deps.py              # DI wiring + RBAC gate: require data_transfer.import.execute
│   ├── routers.py           # HTTP endpoints (see Section 8)
│   └── schemas.py           # Request/response Pydantic models
├── application/
│   ├── __init__.py
│   ├── ports.py             # TransferUnitOfWork, UserProvisioningPort (re-exported)
│   ├── import_orchestrator.py   # Cross-entity import orchestration
│   ├── import_service.py    # Relocated from transport_ops + extended (REUSE EXISTING)
│   ├── template_service.py  # Template generator — all entity types
│   ├── error_reporter.py    # XLSX error workbook generator
│   └── validators.py        # Row-level + cross-entity validation rules
├── domain/
│   ├── __init__.py
│   ├── entities.py          # ImportBatch aggregate
│   └── value_objects.py     # ImportStatus, ResourceType, ConflictStrategy
├── events/
│   ├── __init__.py
│   └── publishers.py        # ImportBatchCompleted domain event
└── infra/
    ├── __init__.py
    ├── models.py            # ImportBatchModel ORM
    └── repositories.py      # SqlAlchemy ImportBatch repository
```

### 7.2 Architecture Gate Compliance

The new `data_transfer` module must pass existing architectural tests:

- **Domain purity**: `entities.py` and `value_objects.py` must not import SQLAlchemy, FastAPI, or Pydantic.
- **Application purity**: `import_service.py` must not import SQLAlchemy directly — use ports.
- **Cross-module isolation**: `data_transfer` may reference other modules' domain entities only via their plain-string IDs (ULIDs). It may import **application service ports** from other modules only via the DI container.
- **No duplicate services**: Reuse `UserProvisioningPort`, `TransportOpsUnitOfWork`, `AuditWriter`. Do not re-implement.

### 7.3 Key Design Decisions

**Organization ID must come from URL path, not from JWT**: The route must be `/api/v1/admin/organizations/{organization_id}/imports/...`. The backend must call `scope.allows(organization_id)` before proceeding. This eliminates both the platform-role `org_id=None` bug and the cross-org injection risk.

**Reuse `BulkImportDialog.tsx`**: The existing 3-step dialog is well-built. It needs two additions: (1) the organization context passed in as a prop (the Admin Dashboard already has `organizationId` from URL params), and (2) a 4th step for history. The API calls in `api.ts` need to point to new endpoints.

**Existing `import_services.py` logic is reusable**: The phone normalizer, date parser, alias mapper, file parser, validation engine, and atomic commit are all sound. Move them to `data_transfer/application/import_service.py` as the base. Extend with new entity support.

---

## Section 8 — API Design

All new endpoints follow the established pattern: `require_permission`, `get_scope`, org ID from path, tenant validation.

### 8.1 Endpoint Specifications

```
# Template management
GET  /api/v1/admin/imports/templates
     Permission: data_transfer.templates.read
     Returns: list of available template definitions

GET  /api/v1/admin/imports/templates/{template_key}/download
     Permission: data_transfer.templates.read
     Query:  format=xlsx|csv
     Returns: binary file download

# Org-scoped import (organization_id in path, validated against scope)
POST /api/v1/admin/organizations/{organization_id}/imports/validate
     Permission: data_transfer.import.execute
     Body: multipart/form-data (file bytes)
     Query: resource_type=students|parents|staff|vehicles|routes|assignments
     Returns: ImportValidationSummary

POST /api/v1/admin/organizations/{organization_id}/imports/commit
     Permission: data_transfer.import.execute
     Body: multipart/form-data (file bytes)
     Query: resource_type=..., conflict_strategy=strict|skip_invalid|upsert
     Returns: ImportBatchSummary (includes batch_id)

GET  /api/v1/admin/organizations/{organization_id}/imports/batches
     Permission: data_transfer.import.history
     Returns: paginated ImportBatch list

GET  /api/v1/admin/organizations/{organization_id}/imports/batches/{batch_id}/errors
     Permission: data_transfer.import.history
     Returns: XLSX error workbook download
```

### 8.2 Permission Seeds Required

Add to migration (new migration file, do not modify `5437a5d1651b`):

```sql
-- New permissions for data_transfer module
-- Only platform roles hold these — org_admin does NOT
INSERT INTO role_permissions (role, permission) VALUES
  ('FOUNDER', 'data_transfer.templates.read'),
  ('FOUNDER', 'data_transfer.import.execute'),
  ('FOUNDER', 'data_transfer.import.history'),
  ('REGIONAL_MANAGER', 'data_transfer.templates.read'),
  ('REGIONAL_MANAGER', 'data_transfer.import.execute'),
  ('REGIONAL_MANAGER', 'data_transfer.import.history'),
  ('SUPPORT_STAFF', 'data_transfer.templates.read'),
  ('SUPPORT_STAFF', 'data_transfer.import.execute'),
  ('SUPPORT_STAFF', 'data_transfer.import.history');
-- FINANCE_STAFF: templates.read only (they receive but don't execute imports)
INSERT INTO role_permissions (role, permission) VALUES
  ('FINANCE_STAFF', 'data_transfer.templates.read');
-- ORG_ADMIN: NO data_transfer permissions at all
```

> [!CAUTION]
> **Also revoke** the accidental import access Org Admin currently has: the existing endpoints at `/api/v1/imports` must either be **removed** or **re-permissioned** to block Org Admin. The simplest approach is to delete them once the new platform-scoped endpoints are live.

### 8.3 Backend Validation of Organization ID

Every import endpoint must include this guard before dispatching to the service:

```python
# In the router or a shared dependency:
async def resolve_target_org(
    organization_id: str,
    scope: TenantRegionScope = Depends(get_scope),
) -> str:
    if not scope.allows(organization_id):
        raise AuthorizationError(f"Access denied to organization '{organization_id}'")
    return organization_id
```

This is structurally identical to how the `OrganizationDetailsPage` backend (`GET /organizations/:id`) already validates org access.

---

## Section 9 — Database and Domain Requirements

### 9.1 New Migration Required

**Migration name**: `data_transfer_import_batches`

```sql
CREATE TABLE import_batches (
    id              CHAR(26) PRIMARY KEY,          -- ULID
    organization_id CHAR(26) NOT NULL,             -- Target org (indexed)
    actor_user_id   CHAR(26) NOT NULL,             -- Initiating RAAD staff user
    resource_type   VARCHAR(64) NOT NULL,          -- 'students', 'parents', 'vehicles', etc.
    status          VARCHAR(32) NOT NULL,          -- 'pending', 'validated', 'committed', 'failed'
    original_filename VARCHAR(255),
    file_size_bytes BIGINT,
    total_rows      INTEGER NOT NULL DEFAULT 0,
    created_count   INTEGER NOT NULL DEFAULT 0,
    updated_count   INTEGER NOT NULL DEFAULT 0,
    skipped_count   INTEGER NOT NULL DEFAULT 0,
    failed_count    INTEGER NOT NULL DEFAULT 0,
    conflict_strategy VARCHAR(32),                 -- 'strict', 'skip_invalid', 'upsert'
    error_report_available BOOLEAN NOT NULL DEFAULT FALSE,
    committed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_import_batches_organization_id ON import_batches(organization_id);
CREATE INDEX ix_import_batches_actor_user_id ON import_batches(actor_user_id);
CREATE INDEX ix_import_batches_created_at ON import_batches(created_at DESC);
```

### 9.2 Academic Structure (Pre-existing Gap — Separate Decision)

The audit document `CLIENT-DATA-IMPORT-EXPORT-AUDIT.md` correctly identifies that `classes`, `grades`, and `academic_years` tables do not exist. The existing `students.notes` field stores grade level as free text (e.g. `"Grade: Grade 7"`).

**Recommendation**: Academic structure is a **separate ADR and migration** from the import system. For the import P0 phase, grade_level should remain a string in the student template and be stored in `students.notes` as it currently is — consistent with existing behavior.

Academic structure can be formalized in a later phase without blocking import implementation.

### 9.3 No Other New Tables Required for P0

The existing domain entities (students, parents, routes, stops, vehicles, staff, drivers, student_assignments) have sufficient schemas for bulk import. No structural changes to those tables are needed.

---

## Section 10 — Frontend Design

### 10.1 Admin Dashboard Navigation — No Nav Change Required

The entry point is `/platform/organizations/:organizationId` — an **existing route** already gated to `PLATFORM_ROLES`. No new nav entry is needed. The feature is accessed as a tab on the Organization Details page.

### 10.2 New Tab in `tabs.tsx`

Add `"data_import"` to `OrganizationDetailTabId` and to `ORGANIZATION_DETAIL_TABS`:

```typescript
// In tabs.tsx — add to OrganizationDetailTabId union:
| "data_import"

// Add to ORGANIZATION_DETAIL_TABS array (in "operations" group):
{
  id: "data_import",
  label: "Data Import",
  description: "Bulk import organization data from RAAD Excel templates",
  icon: <Upload size={18} />,
  group: "operations",
},
```

### 10.3 New Tab Panel in `OrganizationTabPanel.tsx`

Add a `case "data_import":` branch that renders a new component:

```typescript
case "data_import":
  return (
    <OrganizationDataImportPanel
      organizationId={organizationId}
      organization={organization}
    />
  );
```

### 10.4 New Component: `OrganizationDataImportPanel`

Location: `frontend/src/features/organizations/details/OrganizationDataImportPanel.tsx`

This component should have three sub-sections (implemented as internal tabs or sections):

1. **Templates** — Download available RAAD templates (XLSX/CSV) for each entity type.
2. **Import Wizard** — Reuse and adapt `BulkImportDialog.tsx` logic. Key additions:
   - `organizationId` prop passed through to API calls.
   - Resource type selector (Students, Parents, Staff, Fleet, Routes+Stops, Assignments).
   - API calls go to `/api/v1/admin/organizations/{organizationId}/imports/...`.
3. **Import History** — Table of past import batches for this organization (batch ID, date, resource type, actor, counts, status, download error report link).

### 10.5 New API client file

Location: `frontend/src/features/organizations/details/importApi.ts`

Mirrors the shape of the existing `transport-ops/imports/api.ts` but calls the new platform-scoped endpoints with `organizationId` in the URL.

### 10.6 What Does NOT Change

- `organizationNav` (Org Admin nav) — no data import entry.
- `/org/*` routes — no import routes.
- `BulkImportDialog.tsx` on `StudentsPage`/`ParentsPage` — these are for Org Admin use. Per the business requirement, **they may remain** for Org Admin self-service data entry (this is not the same as the centralized platform import). However, their backend permissions must be reviewed to ensure they cannot bypass the new access control.

---

## Section 11 — RBAC and Tenant Isolation

### 11.1 Authorization Requirements

| Check | Implementation |
|---|---|
| Caller must be RAAD platform staff | `require_permission(Permission("data_transfer.import.execute"))` — only seeded for `FOUNDER`, `REGIONAL_MANAGER`, `SUPPORT_STAFF` |
| Organization must exist | `GET /organizations/{id}` — already validated by existing org service |
| Caller must have scope access to org | `scope.allows(organization_id)` — `Founder` unrestricted, `Regional_Manager` scoped to their regions |
| Org Admin cannot call import endpoints | `data_transfer.import.execute` is not in Org Admin's permission set |
| Imported data must be scoped to target org | All entity creation uses `organization_id` from URL, not from JWT |

### 11.2 Negative Security Tests (Required for Implementation Phase)

```
TEST: Org Admin cannot call validate endpoint
  - Authenticate as org_admin
  - POST /api/v1/admin/organizations/{org_id}/imports/validate
  - Expected: 403 Forbidden

TEST: Platform staff cannot import into an org outside their scope
  - Authenticate as regional_manager (scoped to Region A)
  - POST /api/v1/admin/organizations/{org_in_region_B_id}/imports/validate
  - Expected: 403 Forbidden (scope.allows() fails)

TEST: Supplying a foreign org's route name in student template
  - Import students template with route_name = "Route from Org B"
  - Expected: validation error "Route not found in this organization"
  - Expected: zero records committed to database

TEST: Null/empty organization_id
  - POST /api/v1/admin/organizations//imports/validate
  - Expected: 422 Unprocessable Entity (FastAPI path param validation)

TEST: Concurrent imports for same org
  - Two simultaneous commit requests for same organization_id
  - Expected: second request receives 409 Conflict or queues cleanly
```

---

## Section 12 — Implementation Roadmap

### P0 — Foundation & Security (Must have before any user-facing work)

| Task | Files Changed | Effort |
|---|---|---|
| Create `raad/modules/data_transfer/` structure | New files | Low |
| Migrate `import_services.py` → `data_transfer/application/import_service.py` | Move + extend | Low |
| Add org_id from URL path param validation | New router deps | Low |
| Seed `data_transfer.import.*` permissions for platform roles only | New migration | Low |
| Add `import_batches` DB table + ORM model | Migration + model | Medium |
| Wire new router at `/api/v1/admin/organizations/{org_id}/imports` | `api_v1.py` | Low |
| Remove or block Org Admin access to old `/api/v1/imports` | Permission revoke | Low |

### P1 — Core Feature (Admin Dashboard integration)

| Task | Files Changed | Effort |
|---|---|---|
| Add `"data_import"` tab to `OrganizationDetailsPage` | `tabs.tsx`, `OrganizationTabPanel.tsx` | Low |
| Build `OrganizationDataImportPanel.tsx` with 3 sub-sections | New component | Medium |
| Extend import service for: staff, vehicles, routes+stops | `import_service.py` | High |
| Build template generator for all entity types with dropdowns | `template_service.py` | High |
| Build XLSX error report workbook generator | `error_reporter.py` | Medium |
| Frontend import history table | `OrganizationDataImportPanel.tsx` | Medium |
| Frontend template download section | `OrganizationDataImportPanel.tsx` | Low |
| Integration tests for tenant isolation | `tests/integration/` | High |
| Architecture tests for new module | `tests/architecture/` | Low |

### P2 — Enhanced Capability

| Task | Files Changed | Effort |
|---|---|---|
| Multi-sheet Master Onboarding Workbook | `template_service.py`, `import_service.py` | High |
| Formula injection sanitization | `import_service.py` | Medium |
| File size limit enforcement (15 MB) | Router `_extract_upload` | Low |
| Conflict strategy selector (strict / skip / upsert) | Service + schema + UI | Medium |
| Background async execution for large batches (>500 rows) | `core/workers/` | High |
| Round-trip export engine with RAAD_SYSTEM_ID | New `export_service.py` in data_transfer | High |
| Academic structure (grades/classes) — separate ADR | New migration + entities | High |

---

## Section 13 — Testing Strategy

### 13.1 Unit Tests (`backend/tests/unit/`)

```
test_data_transfer_normalize_somali_phone.py
  - Valid 8-digit, 9-digit, +252 prefix, 00252 prefix
  - Invalid: letters, too short, too long
  - International non-Somali numbers

test_data_transfer_import_service.py
  - generate_template() returns correct headers for each entity type
  - _parse_file() handles .xlsx and .csv correctly
  - _parse_file() skips empty rows and "e.g." descriptor rows
  - validate_import() returns correct error counts
  - Formula injection cells sanitized (P2)

test_data_transfer_import_batch.py
  - ImportBatch domain entity state transitions
```

### 13.2 Integration Tests (`backend/tests/integration/`)

```
test_data_transfer_tenant_isolation.py
  - Founder can import into any org
  - Regional Manager can import into their region's orgs
  - Regional Manager CANNOT import into another region's org (403)
  - Org Admin CANNOT call import endpoints (403)

test_data_transfer_import_commit.py
  - Commit 50 students → verify 50 students in DB, 0 in other orgs
  - Commit with duplicate admission_no → second row skipped, first committed
  - Commit fails mid-transaction → zero rows in DB (rollback verified)
  - Parent IAM user provisioned with correct organization_id

test_data_transfer_import_batch_history.py
  - After commit, ImportBatch record exists in DB with correct counts
  - Actor user_id matches the authenticated platform staff user
```

### 13.3 Architecture Tests (`backend/tests/architecture/`)

```
test_data_transfer_module_isolation.py
  - data_transfer.domain does not import SQLAlchemy, FastAPI, Pydantic
  - data_transfer.application does not import SQLAlchemy directly
  - data_transfer does not import transport_ops.infra (only ports)
```

### 13.4 Frontend Tests

```
OrganizationDataImportPanel.test.tsx
  - Renders "Data Import" tab on platform dashboard
  - Does NOT render on /org/* (org admin) dashboard
  - Template download buttons present
  - Import history table renders with mock data

OrganizationDetailsPage.test.tsx
  - "data_import" tab appears in tab list
  - Tab switch renders correct panel
```

### 13.5 Security Tests

The negative tests listed in Section 11.2 must be implemented as integration tests in `tests/integration/test_data_transfer_rbac.py`.

---

## Section 14 — Final Recommendations

### 14.1 What Already Exists (Reuse)

| Asset | Reuse Plan |
|---|---|
| `normalize_somali_phone()` | Move to `data_transfer.application.import_service` unchanged |
| `_parse_date()` | Same |
| `_parse_file()` | Same — extend for multi-sheet in P2 |
| `_normalize_row_keys()` alias map | Same — extend for new entity columns |
| `ImportApplicationService.validate_import()` | Relocate; add org_id URL param and scope check |
| `ImportApplicationService.commit_import()` | Relocate; fix org_id bug |
| `ImportValidationResult`, `ImportCommitResult` | Move to `data_transfer.application.import_service` |
| `BulkImportDialog.tsx` wizard UI | Reuse as base; adapt props for explicit org_id |
| `ExcelReportRenderer` from reporting module | Reuse for error report XLSX generation |
| `SqlAlchemyUnitOfWork` + topological flush | No change — already works |
| `AuditWriter` | No change — already called in commit |
| `UserProvisioningPort` | No change — already used for parent IAM accounts |
| `PermissionEvaluator` + `require_permission` | No change — extend with new permission strings |
| `TenantRegionScope.allows()` | No change — call it in new router deps |

### 14.2 What is Broken (Fix Immediately in P0)

1. **Permission gate on existing `/api/v1/imports`**: Currently gates on Org Admin permissions. Must be changed before the new endpoints go live. Simplest fix: delete the old router or add a `FOUNDER/REGIONAL_MANAGER/SUPPORT_STAFF` permission check.
2. **`principal.org_id or ""`**: For platform roles, this produces an empty string. Any call to the existing endpoint by a platform role imports into org ID `""`. This is a silent data corruption bug.
3. **Missing scope validation**: `organization_id` received by the service is not validated against `TenantRegionScope`.

### 14.3 What Does Not Exist (Build)

1. `raad/modules/data_transfer/` bounded context (see Section 7.1 structure).
2. `import_batches` database table + migration.
3. `OrganizationDataImportPanel.tsx` frontend component.
4. `"data_import"` tab in `OrganizationDetailsPage` tabs.
5. New platform-scoped API endpoints under `/api/v1/admin/organizations/{org_id}/imports/`.
6. Permission seeds for `data_transfer.*` permissions (platform roles only).
7. XLSX error report workbook generator.
8. Import service support for: transport staff, vehicles, routes, stops, student assignments.
9. Template generator for all entity types (with openpyxl DataValidation dropdowns).
10. Frontend `importApi.ts` calling the new platform-scoped endpoints.

### 14.4 What Must NOT Change

- `organizationNav` — Org Admin nav gets no "Data Import" entry.
- `/org/*` routes — No import routes for Org Admin.
- Existing `StudentsPage` and `ParentsPage` Org Admin-facing import dialog — This can remain as a convenience feature for Org Admins to self-manage their data IF the business approves it. It is a separate concern from the centralized Super Admin import.
- All existing working functionality — zero regressions.

### 14.5 Recommended Implementation Order

```
Day 1-2:   Create data_transfer module structure
           Move import_services.py → data_transfer (with org_id bug fix)
           Add import_batches migration
           Seed new platform-only permissions
           Wire new router at /api/v1/admin/organizations/{org_id}/imports

Day 3-4:   Add "Data Import" tab to OrganizationDetailsPage
           Build OrganizationDataImportPanel skeleton
           Wire frontend to new API endpoints
           Basic import history table (no error download yet)

Day 5-7:   Extend import service for staff and vehicles
           Build template generator for all entity types
           Add Excel DataValidation dropdowns to templates
           XLSX error workbook generator

Day 8-9:   Integration tests (tenant isolation, rollback, batch history)
           Architecture tests (module isolation)
           Security tests (Org Admin blocked, scope enforcement)

Day 10:    Manual testing on staging with real school data
           Remove/block old /api/v1/imports endpoint
           Production deployment
```

---

## Appendix A — Previous Audit Document Comparison

The document `CLIENT-DATA-IMPORT-EXPORT-AUDIT.md` (dated 2026-11-05) was an excellent technical foundation but was written for a **different business model** — one where Org Admin manages their own imports via `/org/data-management`.

| Previous Audit Recommendation | New Audit Decision |
|---|---|
| Place import UI at `/org/data-management` | **REVERSED** — place at `/platform/organizations/:id/data-import` tab |
| Seed `org_admin` import permissions | **REVERSED** — seed `founder`, `regional_manager`, `support_staff` only |
| Data Transfer Bounded Context | **RETAINED** — `raad/modules/data_transfer/` |
| Template designs and column specs | **RETAINED** — same templates, different download location |
| 12-stage validation pipeline | **RETAINED** — same pipeline |
| openpyxl DataValidation dropdowns | **RETAINED** |
| Formula injection sanitization | **RETAINED** |
| Import Batch history table | **RETAINED** |
| Round-trip export with RAAD_SYSTEM_ID | **RETAINED** for P2 |
| Async background execution | **RETAINED** for P2 |
| Academic structure (classes/grades) | **RETAINED** as separate ADR |

> [!NOTE]
> The technical architecture recommendations in the previous audit remain sound. Only the access model and UI placement change. This saves significant re-work.

---

## Appendix B — File Change Summary for Implementation

### New Files (P0 + P1)

```
backend/raad/modules/data_transfer/__init__.py
backend/raad/modules/data_transfer/api/__init__.py
backend/raad/modules/data_transfer/api/deps.py
backend/raad/modules/data_transfer/api/routers.py
backend/raad/modules/data_transfer/api/schemas.py
backend/raad/modules/data_transfer/application/__init__.py
backend/raad/modules/data_transfer/application/import_service.py   ← relocated
backend/raad/modules/data_transfer/application/template_service.py
backend/raad/modules/data_transfer/application/error_reporter.py
backend/raad/modules/data_transfer/application/ports.py
backend/raad/modules/data_transfer/domain/__init__.py
backend/raad/modules/data_transfer/domain/entities.py
backend/raad/modules/data_transfer/domain/value_objects.py
backend/raad/modules/data_transfer/infra/__init__.py
backend/raad/modules/data_transfer/infra/models.py
backend/raad/modules/data_transfer/infra/repositories.py
backend/migrations/versions/<timestamp>_data_transfer_import_batches.py
frontend/src/features/organizations/details/OrganizationDataImportPanel.tsx
frontend/src/features/organizations/details/OrganizationDataImportPanel.module.css
frontend/src/features/organizations/details/importApi.ts
backend/tests/unit/test_data_transfer_import_service.py
backend/tests/integration/test_data_transfer_tenant_isolation.py
backend/tests/integration/test_data_transfer_import_commit.py
backend/tests/architecture/test_data_transfer_module_isolation.py
frontend/src/features/organizations/details/OrganizationDataImportPanel.test.tsx
```

### Modified Files (P0 + P1)

```
backend/raad/interfaces/http/api_v1.py                              ← add new router, optionally remove old
backend/raad/core/di/bootstrap.py                                   ← register data_transfer services
frontend/src/features/organizations/details/tabs.tsx                ← add "data_import" tab definition
frontend/src/features/organizations/details/OrganizationTabPanel.tsx ← add case "data_import"
frontend/src/features/organizations/details/OrganizationDetailsPage.tsx ← minor: import new panel
backend/migrations/versions/<timestamp>_data_transfer_rbac_grants.py ← new permission seeds
```

### Deleted or Deprecated (after P0 cutover)

```
backend/raad/modules/transport_ops/application/import_services.py  ← source moved, file deleted
backend/raad/modules/transport_ops/api/imports_router.py           ← replaced by data_transfer router
```

> [!WARNING]
> `BulkImportDialog.tsx`, `StudentsPage.tsx`, and `ParentsPage.tsx` are **not deleted**. The existing Org Admin import UI remains in place unless a business decision is made to remove it. The critical change is the backend permission gate.

---

*Audit complete. No code has been modified. This document is a read-only blueprint.*  
*Next step: Review this audit and approve the implementation plan before any code changes are made.*
