"""fleet_device: ADR-0033 terminal audio capability capture

Revision ID: 3aef3f7c7bb1
Revises: a6682ad19581
Create Date: 2026-08-27 15:30:00.000000

ADR-0033. Seven purely additive, nullable columns on `devices`, recording the terminal's own
real `0x1003` audio/video attributes report verbatim (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.1.2
Table 6.1) — device-gateway's `commands/av_attributes.AvAttributesReport` already parsed all of
these; `DeviceAvAttributesReported` (ADR-0030) originally discarded everything except
`max_video_channels`/`max_audio_channels`, so no trace of a real terminal's audio capability
ever reached this backend before this ADR.

No codec/sample-rate assumption is made anywhere in this migration or its callers — `audio_codec`/
`video_codec` are Table 6.21's raw enum byte, not decoded to a name (no approved document maps
every one of that table's codec IDs to a name yet, and this codebase never assumes AAC or any
other specific codec).

All seven columns are set/cleared together as one unit (`AudioCapability`/
`record_audio_capability`, `mappers.py`'s `device_to_model`) — a row is either all-NULL (no real
report received yet) or fully populated, never partially populated.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "3aef3f7c7bb1"
down_revision: Union[str, None] = "a6682ad19581"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("audio_codec", sa.Integer(), nullable=True))
    op.add_column("devices", sa.Column("audio_channels", sa.Integer(), nullable=True))
    op.add_column("devices", sa.Column("audio_sample_rate", sa.Integer(), nullable=True))
    op.add_column("devices", sa.Column("audio_sample_bits", sa.Integer(), nullable=True))
    op.add_column("devices", sa.Column("audio_frame_length", sa.Integer(), nullable=True))
    op.add_column(
        "devices", sa.Column("supports_audio_output", sa.Boolean(), nullable=True)
    )
    op.add_column("devices", sa.Column("video_codec", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "video_codec")
    op.drop_column("devices", "supports_audio_output")
    op.drop_column("devices", "audio_frame_length")
    op.drop_column("devices", "audio_sample_bits")
    op.drop_column("devices", "audio_sample_rate")
    op.drop_column("devices", "audio_channels")
    op.drop_column("devices", "audio_codec")
