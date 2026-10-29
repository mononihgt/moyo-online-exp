"""增加分析字段

Revision ID: a1c3e5f7b9d2
Revises: c8f1a2d4e6b9
Create Date: 2026-10-29 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c3e5f7b9d2"
down_revision: str | None = "c8f1a2d4e6b9"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("map_group_versions", sa.Column("factors_json", sa.JSON(), nullable=True))
    op.add_column("maps", sa.Column("landmark_cells_json", sa.JSON(), nullable=True))
    op.add_column("game_trials", sa.Column("engine_version", sa.String(length=20), nullable=True))
    op.add_column("game_trials", sa.Column("mechanics_json", sa.JSON(), nullable=True))
    op.add_column("turns", sa.Column("pre_combat_policy_json", sa.JSON(), nullable=True))
    op.add_column("turns", sa.Column("movements_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("turns", "movements_json")
    op.drop_column("turns", "pre_combat_policy_json")
    op.drop_column("game_trials", "mechanics_json")
    op.drop_column("game_trials", "engine_version")
    op.drop_column("maps", "landmark_cells_json")
    op.drop_column("map_group_versions", "factors_json")
