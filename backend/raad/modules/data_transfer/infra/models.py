"""SQLAlchemy ORM models for data_transfer bounded context.

PostgreSQL types only (ADR-0002).
SqlAlchemy is strictly confined to this infra layer (Domain & Application Purity).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CHAR, DateTime, Integer, VARCHAR, func, text
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base


class ImportBatchModel(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(CHAR(26), primary_key=True)
    organization_id: Mapped[str] = mapped_column(CHAR(26), index=True, nullable=False)
    actor_user_id: Mapped[str] = mapped_column(CHAR(26), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(VARCHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(VARCHAR(32), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    conflict_strategy: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    error_report_available: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False, nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
