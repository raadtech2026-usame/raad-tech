"""Value objects for the data_transfer bounded context.

Pure Python primitives and enums representing batch states, resource types, and conflict policies.
Framework-free (Domain Purity).
"""

from __future__ import annotations

from enum import Enum
from typing import NewType

ImportBatchId = NewType("ImportBatchId", str)
OrganizationId = NewType("OrganizationId", str)
UserId = NewType("UserId", str)


class ImportStatus(str, Enum):
    """Lifecycle state of a bulk data import batch."""

    PENDING = "pending"
    VALIDATED = "validated"
    COMMITTED = "committed"
    FAILED = "failed"


class ConflictStrategy(str, Enum):
    """Resolution strategy when import encounters conflicting or invalid rows."""

    STRICT = "strict"          # Abort entire transaction on any fatal error
    SKIP_INVALID = "skip_invalid"  # Ingest valid rows and skip invalid ones
    UPSERT = "upsert"          # Update existing records, insert new ones


class ImportResourceType(str, Enum):
    """Supported entity resource types for bulk data transfer."""

    STUDENTS = "students"
    PARENTS = "parents"
