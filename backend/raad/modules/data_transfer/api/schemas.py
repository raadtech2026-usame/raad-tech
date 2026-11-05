"""Pydantic schemas for data_transfer HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImportRowError(BaseModel):
    model_config = ConfigDict(frozen=True)

    row_number: int = Field(..., description="1-indexed row number in the uploaded spreadsheet")
    column: str = Field(..., description="Attribute or column header that failed validation")
    error_message: str = Field(..., description="Human-readable explanation of why this row failed")


class ImportRowPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    row_number: int
    is_valid: bool
    data: dict[str, Any]
    errors: list[str] = Field(default_factory=list)


class ImportValidationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource_type: str
    organization_id: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    errors: list[ImportRowError]
    preview: list[ImportRowPreview]


class ImportCommitSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    batch_id: str
    resource_type: str
    organization_id: str
    created_count: int
    updated_count: int
    skipped_count: int
    total_processed: int
    status: str
    errors: list[str] = Field(default_factory=list)


class ImportBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    actor_user_id: str
    resource_type: str
    status: str
    original_filename: str | None
    file_size_bytes: int | None
    total_rows: int
    created_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    conflict_strategy: str | None
    error_report_available: bool
    committed_at: datetime | None
    created_at: datetime


class ImportBatchListResponse(BaseModel):
    items: list[ImportBatchResponse]
    total: int
