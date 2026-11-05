"""HTTP surface for bulk data import wizard (Students and Parents).

Exposes:
- GET  /api/v1/imports/{resource_type}/template: Downloadable .xlsx or .csv template
- POST /api/v1/imports/{resource_type}/validate: Dry-run validation of uploaded file
- POST /api/v1/imports/{resource_type}/commit:   Atomic batch upsert/insert in single DB transaction
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from raad.core.errors.exceptions import AuthorizationError, ValidationError
from raad.core.security.permissions import Permission, PermissionEvaluator
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import get_container, get_principal
from raad.modules.transport_ops.api.deps import (
    get_import_service,
    get_transport_ops_uow,
)
from raad.modules.transport_ops.api.schemas import (
    ImportCommitSummary,
    ImportRowError,
    ImportRowPreview,
    ImportValidationSummary,
)
from raad.modules.transport_ops.application.import_services import (
    ImportApplicationService,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork

imports_router = APIRouter()


async def check_import_permission(
    resource_type: str,
    request: Request,
    principal: Principal = Depends(get_principal),
) -> Principal:
    """RBAC check ensuring caller has platform administration import rights.

    Explicitly requires `data_transfer.import.execute`, which is granted strictly to
    platform administration roles (Founder, Regional Manager, Support Staff) and withheld
    from Org Admin.
    """
    perm = Permission("data_transfer.import.execute")

    container = get_container(request)
    evaluator = container.resolve(PermissionEvaluator)
    if not await evaluator.has_permission(principal, perm):
        raise AuthorizationError(f"Missing required permission: {perm}")

    return principal


async def _extract_upload(request: Request, default_filename: str) -> tuple[bytes, str]:
    """Extracts uploaded file bytes and filename from multipart/form-data or raw stream."""
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    filename = request.headers.get("x-filename") or default_filename

    if "multipart/form-data" in content_type and b"--" in body:
        boundary_match = re.search(r"boundary=([^;]+)", content_type)
        if boundary_match:
            boundary = boundary_match.group(1).strip().strip('"')
            delimiter = f"--{boundary}".encode()
            parts = body.split(delimiter)
            for part in parts:
                if b'filename="' in part:
                    header_end = part.find(b"\r\n\r\n")
                    if header_end != -1:
                        header_bytes = part[:header_end].decode("utf-8", errors="replace")
                        name_match = re.search(r'filename="([^"]+)"', header_bytes)
                        if name_match:
                            filename = name_match.group(1)
                        content = part[header_end + 4 :]
                        if content.endswith(b"--\r\n"):
                            content = content[:-4]
                        elif content.endswith(b"\r\n"):
                            content = content[:-2]
                        return content, filename

    return body, filename


@imports_router.get(
    "/{resource_type}/template",
    status_code=status.HTTP_200_OK,
    summary="Download starter template for bulk import",
    description="Generates and returns a downloadable starter template (.xlsx or .csv) with documented headers.",
)
async def get_import_template(
    resource_type: str,
    format: Literal["xlsx", "csv"] = Query(
        default="xlsx", description="Template format ('xlsx' or 'csv')"
    ),
    import_service: ImportApplicationService = Depends(get_import_service),
    principal: Principal = Depends(check_import_permission),
) -> Response:
    content, media_type, filename = import_service.generate_template(
        resource_type, format_type=format
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@imports_router.post(
    "/{resource_type}/validate",
    response_model=ImportValidationSummary,
    status_code=status.HTTP_200_OK,
    summary="Validate uploaded bulk import file (dry-run)",
    description="Dry-run validation of uploaded file without persisting to DB.",
)
async def validate_import(
    resource_type: str,
    request: Request,
    filename: str = Query(default="import.xlsx"),
    import_service: ImportApplicationService = Depends(get_import_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    principal: Principal = Depends(check_import_permission),
) -> ImportValidationSummary:
    file_bytes, resolved_name = await _extract_upload(request, default_filename=filename)
    org_id = principal.org_id or ""

    result = await import_service.validate_import(
        resource_type=resource_type,
        file_bytes=file_bytes,
        filename=resolved_name,
        organization_id=org_id,
        uow=uow,
    )

    return ImportValidationSummary(
        resource_type=result.resource_type,
        total_rows=result.total_rows,
        valid_rows=result.valid_rows,
        invalid_rows=result.invalid_rows,
        errors=[
            ImportRowError(
                row_number=e.row_number,
                column=e.column,
                error_message=e.error_message,
            )
            for e in result.errors
        ],
        preview=[
            ImportRowPreview(
                row_number=p.row_number,
                is_valid=p.is_valid,
                data=p.data,
                errors=p.errors,
            )
            for p in result.preview
        ],
    )


@imports_router.post(
    "/{resource_type}/commit",
    response_model=ImportCommitSummary,
    status_code=status.HTTP_200_OK,
    summary="Execute bulk import with atomic transaction",
    description="Batch upsert/insert in a single database transaction with clean rollback on error.",
)
async def commit_import(
    resource_type: str,
    request: Request,
    filename: str = Query(default="import.xlsx"),
    import_service: ImportApplicationService = Depends(get_import_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    principal: Principal = Depends(check_import_permission),
) -> ImportCommitSummary:
    file_bytes, resolved_name = await _extract_upload(request, default_filename=filename)
    org_id = principal.org_id or ""

    result = await import_service.commit_import(
        resource_type=resource_type,
        file_bytes=file_bytes,
        filename=resolved_name,
        organization_id=org_id,
        principal=principal,
        uow=uow,
    )

    return ImportCommitSummary(
        resource_type=result.resource_type,
        created_count=result.created_count,
        updated_count=result.updated_count,
        skipped_count=result.skipped_count,
        total_processed=result.total_processed,
        errors=result.errors,
    )
