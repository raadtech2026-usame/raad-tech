"""Transport Operations application commands (Backend LLD §4.2 "intent DTOs"). Immutable
request objects describing what the caller wants done, matching `organization.application.
commands`'s exact shape: every command carries the calling `Principal` as `actor`, and
identifiers are plain `str` (converted to value objects inside the service).

Phase 10.2 scope: `Student` lifecycle commands only, matching `domain/entities.py`'s
`Student`-only scope (Phase 10.1).

**No approved document names any of these commands** (Backend LLD §5.2 gives no `Student`
use-case skeleton — confirmed again for this phase; see `services.py`'s module docstring for
the full research record). Names below follow the established `<Verb><Noun>Command` convention
and match `Student`'s own domain method names 1:1 (`Student.enroll` ↔ `EnrollStudentCommand`,
etc.), the same relationship `organization.application.commands` has to `Organization`'s
methods.

**API Contracts §4.3 note:** the only documented Student HTTP surface is `POST /students`
(create) and `POST /students/{id}/status` (body `{status}` → disable/graduate/transfer) — one
endpoint fanning out to three of these four status-change commands, not a per-verb endpoint
each (unlike `fleet_device`'s `/devices/{id}/activate`-style routes). That fan-out is an HTTP
API-layer concern (a later phase); at the application layer each transition is still its own
command, matching `Student`'s own domain method granularity and every sibling module's
1:1 command-per-domain-method convention.

**Phase 10.6 addition: `Parent` commands.** `RegisterParentCommand`/`UpdateParentCommand`/
`ActivateParentCommand`/`DisableParentCommand`, 1:1 with `Parent`'s own domain method names
(`domain/entities.py`) — no `Transfer`/`Graduate` equivalent, since `ParentStatus` is a flat
active/inactive toggle (`domain/value_objects.py`), unlike `StudentStatus`'s four values.
`RegisterParentCommand` (not `EnrollParentCommand`) mirrors `Parent.register`'s own naming,
itself mirroring `Organization.register`/`Vehicle.register`/`Device.register`'s established
"register a new instance of this aggregate" convention — `enroll` is `Student`-specific
ubiquitous language (Ch. 6), not a generic verb this aggregate reuses.
"""

from __future__ import annotations

from dataclasses import dataclass

from raad.core.tenancy.principal import Principal


@dataclass(frozen=True)
class EnrollStudentCommand:
    organization_id: str
    full_name: str
    external_ref: str | None
    actor: Principal


@dataclass(frozen=True)
class UpdateStudentCommand:
    student_id: str
    full_name: str
    external_ref: str | None
    actor: Principal


@dataclass(frozen=True)
class TransferStudentCommand:
    student_id: str
    actor: Principal


@dataclass(frozen=True)
class GraduateStudentCommand:
    student_id: str
    actor: Principal


@dataclass(frozen=True)
class ActivateStudentCommand:
    student_id: str
    actor: Principal


@dataclass(frozen=True)
class DisableStudentCommand:
    student_id: str
    actor: Principal


@dataclass(frozen=True)
class RegisterParentCommand:
    organization_id: str
    user_id: str
    full_name: str
    phone: str | None
    actor: Principal


@dataclass(frozen=True)
class UpdateParentCommand:
    parent_id: str
    full_name: str
    phone: str | None
    actor: Principal


@dataclass(frozen=True)
class ActivateParentCommand:
    parent_id: str
    actor: Principal


@dataclass(frozen=True)
class DisableParentCommand:
    parent_id: str
    actor: Principal
