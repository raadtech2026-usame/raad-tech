"""IAM infrastructure layer (Backend LLD §6.2/§7/§8; Database Design §4.3/§4.5) — Phase 5.3
scope. SQLAlchemy ORM models, ORM↔domain mappers, and the concrete repositories/UnitOfWork
that implement the domain's and application's interfaces. Importing this package registers
`UserModel`/`RefreshTokenModel` onto `core.db.base.Base.metadata` (needed by Alembic
autogenerate, `migrations/env.py`). No HTTP/FastAPI, no new business rules — `domain/` and
`application/` are unchanged. Public surface of this package.
"""

from raad.modules.iam.infra.mappers import (
    model_to_refresh_token,
    model_to_user,
    refresh_token_to_model,
    user_to_model,
)
from raad.modules.iam.infra.models import RefreshTokenModel, UserModel
from raad.modules.iam.infra.repositories import (
    SqlAlchemyIamUnitOfWork,
    SqlAlchemyRefreshTokenRepository,
    SqlAlchemyUserRepository,
)

__all__ = [
    "RefreshTokenModel",
    "SqlAlchemyIamUnitOfWork",
    "SqlAlchemyRefreshTokenRepository",
    "SqlAlchemyUserRepository",
    "UserModel",
    "model_to_refresh_token",
    "model_to_user",
    "refresh_token_to_model",
    "user_to_model",
]
