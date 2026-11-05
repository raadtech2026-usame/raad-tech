"""HTTP surface for centralized enterprise bulk data import and template management.

Managed exclusively by RAAD-TECH platform administration (Super Admin).
All endpoints strictly enforce:
1. `data_transfer.*` platform permissions via `require_permission`.
2. Explicit target organization resolution and tenant/region authorization via `resolve_target_organization`.
3. Complete transactional commit and persistent batch audit logging.
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from raad.core.errors.exceptions import ValidationError
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import get_principal, require_permission
from raad.modules.data_transfer.api.deps import (
    get_data_transfer_service,
    get_data_transfer_uow,
    resolve_target_organization,
)
from raad.modules.data_transfer.api.schemas import (
    ImportBatchListResponse,
    ImportBatchResponse,
    ImportCommitSummary,
    ImportRowError,
    ImportRowPreview,
    ImportValidationSummary,
)
from raad.modules.data_transfer.application.ports import DataTransferUnitOfWork
from raad.modules.data_transfer.application.services import (
    DataTransferApplicationService,
)
from raad.modules.data_transfer.domain.value_objects import ConflictStrategy
from raad.modules.transport_ops.api.deps import get_transport_ops_uow
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork

data_transfer_admin_router = APIRouter()

_MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB


async def _extract_upload(request: Request, default_filename: str) -> tuple[bytes, str]:
    """Extracts uploaded file bytes and filename from multipart/form-data or raw stream."""
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    filename = request.headers.get("x-filename") or default_filename

    if len(body) > _MAX_UPLOAD_BYTES:
        raise ValidationError(
            f"Uploaded file exceeds maximum allowed size of {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

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


@data_transfer_admin_router.get(
    "/{organization_id}/imports/templates/{resource_type}",
    status_code=status.HTTP_200_OK,
    summary="Download starter template for organization bulk data collection",
    description="Generates and returns an official standardized Excel or CSV starter template.",
)
async def get_import_template(
    organization_id: str,
    resource_type: str,
    format: Literal["xlsx", "csv"] = Query(
        default="xlsx", description="Template format ('xlsx' or 'csv')"
    ),
    target_org_id: str = Depends(resolve_target_organization),
    service: DataTransferApplicationService = Depends(get_data_transfer_service),
    _permission: Principal = Depends(
        require_permission(Permission("data_transfer.templates.read"))
    ),
) -> Response:
    content, media_type, filename = service.generate_template(
        resource_type, format_type=format
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@data_transfer_admin_router.post(
    "/{organization_id}/imports/validate",
    response_model=ImportValidationSummary,
    status_code=status.HTTP_200_OK,
    summary="Dry-run validate an uploaded workbook targeting selected organization",
    description=(
        "Parses the spreadsheet, performs Somali phone normalization, duplicate checks, "
        "and relational integrity validation against the target organization scope without persisting."
    ),
)
async def validate_organization_import(
    organization_id: str,
    request: Request,
    resource_type: str = Query(default="students", description="Target resource type ('students', 'parents')"),
    filename: str = Query(default="import.xlsx"),
    target_org_id: str = Depends(resolve_target_organization),
    service: DataTransferApplicationService = Depends(get_data_transfer_service),
    transport_ops_uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    _permission: Principal = Depends(
        require_permission(Permission("data_transfer.import.execute"))
    ),
) -> ImportValidationSummary:
    file_bytes, resolved_name = await _extract_upload(request, default_filename=filename)

    result = await service.validate_import(
        organization_id=target_org_id,
        resource_type=resource_type,
        file_bytes=file_bytes,
        filename=resolved_name,
        transport_ops_uow=transport_ops_uow,
    )

    return ImportValidationSummary(
        resource_type=result.resource_type,
        organization_id=target_org_id,
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


@data_transfer_admin_router.post(
    "/{organization_id}/imports/commit",
    response_model=ImportCommitSummary,
    status_code=status.HTTP_200_OK,
    summary="Execute bulk import into selected organization with atomic transaction and batch persistence",
    description=(
        "Atomically ingests validated rows into the selected organization's tenant context. "
        "Creates parent IAM logins where required, establishes cross-entity relations, "
        "and persists an immutable batch audit record."
    ),
)
async def commit_organization_import(
    organization_id: str,
    request: Request,
    resource_type: str = Query(default="students", description="Target resource type ('students', 'parents')"),
    conflict_strategy: ConflictStrategy = Query(
        default=ConflictStrategy.SKIP_INVALID,
        description="Resolution policy for conflicts or invalid rows",
    ),
    filename: str = Query(default="import.xlsx"),
    target_org_id: str = Depends(resolve_target_organization),
    service: DataTransferApplicationService = Depends(get_data_transfer_service),
    data_transfer_uow: DataTransferUnitOfWork = Depends(get_data_transfer_uow),
    transport_ops_uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    principal: Principal = Depends(
        require_permission(Permission("data_transfer.import.execute"))
    ),
) -> ImportCommitSummary:
    file_bytes, resolved_name = await _extract_upload(request, default_filename=filename)

    commit_result, batch = await service.commit_import(
        organization_id=target_org_id,
        resource_type=resource_type,
        file_bytes=file_bytes,
        filename=resolved_name,
        conflict_strategy=conflict_strategy,
        principal=principal,
        data_transfer_uow=data_transfer_uow,
        transport_ops_uow=transport_ops_uow,
    )

    return ImportCommitSummary(
        batch_id=batch.id,
        resource_type=commit_result.resource_type,
        organization_id=target_org_id,
        created_count=commit_result.created_count,
        updated_count=commit_result.updated_count,
        skipped_count=commit_result.skipped_count,
        total_processed=commit_result.total_processed,
        status=batch.status.value,
        errors=commit_result.errors,
    )


@data_transfer_admin_router.get(
    "/{organization_id}/imports/batches",
    response_model=ImportBatchListResponse,
    status_code=status.HTTP_200_OK,
    summary="List historical bulk import batches for selected organization",
    description="Returns previous batch records, author metadata, metrics and error status for the organization.",
)
async def list_organization_import_batches(
    organization_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    target_org_id: str = Depends(resolve_target_organization),
    service: DataTransferApplicationService = Depends(get_data_transfer_service),
    data_transfer_uow: DataTransferUnitOfWork = Depends(get_data_transfer_uow),
    _permission: Principal = Depends(
        require_permission(Permission("data_transfer.import.history"))
    ),
) -> ImportBatchListResponse:
    batches = await service.list_batches(
        target_org_id,
        data_transfer_uow=data_transfer_uow,
        limit=limit,
        offset=offset,
    )

    return ImportBatchListResponse(
        items=[
            ImportBatchResponse(
                id=b.id,
                organization_id=b.organization_id,
                actor_user_id=b.actor_user_id,
                resource_type=b.resource_type,
                status=b.status.value,
                original_filename=b.original_filename,
                file_size_bytes=b.file_size_bytes,
                total_rows=b.total_rows,
                created_count=b.created_count,
                updated_count=b.updated_count,
                skipped_count=b.skipped_count,
                failed_count=b.failed_count,
                conflict_strategy=b.conflict_strategy.value if b.conflict_strategy else None,
                error_report_available=b.error_report_available,
                committed_at=b.committed_at,
                created_at=b.created_at,
            )
            for b in batches
        ],
        total=len(batches),
    )
