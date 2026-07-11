"""Declarative base + metadata naming convention (Backend LLD §17 `db`; naming per
`.claude/rules/naming.md` and Database Design §1: `ix_<table>__<cols>` / `ux_<table>__<cols>`
/ `fk_<table>__<ref>`).

Every ORM model in every module inherits from this single `Base` — one `MetaData`, so Alembic
autogenerate sees the whole schema and constraint names are consistent across modules without
each module having to repeat the convention.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Explicit names for every constraint kind so Alembic-generated DDL and hand-written DDL never
# collide or produce the database-assigned default names (e.g. MySQL's `<table>_ibfk_1`).
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s__%(column_0_N_name)s",
    "uq": "ux_%(table_name)s__%(column_0_N_name)s",
    "ck": "ck_%(table_name)s__%(constraint_name)s",
    "fk": "fk_%(table_name)s__%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
