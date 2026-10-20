"""增加绩效保底与格子背景颜色

Revision ID: f4d2c8a1b7e3
Revises: 5b8e2f4c9a71
Create Date: 2026-10-20 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4d2c8a1b7e3"
down_revision: Union[str, None] = "5b8e2f4c9a71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "map_group_versions",
        sa.Column(
            "performance_floor_cents",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "maps",
        sa.Column(
            "colors_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("maps", "colors_json")
    op.drop_column("map_group_versions", "performance_floor_cents")
