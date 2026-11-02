"""增加地图组棋子颜色参数

Revision ID: d2f4a6b8c0e1
Revises: a1c3e5f7b9d2
Create Date: 2026-11-02 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2f4a6b8c0e1"
down_revision: Union[str, None] = "a1c3e5f7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "map_group_versions",
        sa.Column(
            "piece_ink",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'white'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("map_group_versions", "piece_ink")
