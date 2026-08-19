"""fleet_device: ADR-0030 automatic camera/channel discovery

Revision ID: 7d3a9c1e5b42
Revises: 50261534916f
Create Date: 2026-08-18 12:00:00.000000

ADR-0030 (Automatic Camera/Channel Discovery). One purely additive column:

`devices.av_attributes_requested_at` — the idempotency guard for the new automatic JT/T 1078
channel-discovery workflow (`fleet_device/events/subscribers.py`'s new
`DeviceAvAttributesRequestProcessor`): set the moment RAAD publishes a `0x9003` "query A/V
attributes" request for a device, so the same device transitioning `DeviceOnline` again on a
later reconnect does not re-trigger discovery signaling on every reconnect (the accepted design:
"once per device, first successful auth"). Nullable, no default — `NULL` means "never requested",
the same "connectivity/provisioning telemetry, not business state" reasoning `is_online`/
`last_seen_at` already established (`b288c2e44aa5`), so this column follows their exact shape
rather than inventing a new convention.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7d3a9c1e5b42"
down_revision: Union[str, None] = "50261534916f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "av_attributes_requested_at", sa.DateTime(timezone=False), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("devices", "av_attributes_requested_at")
