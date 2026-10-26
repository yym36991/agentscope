"""stage_runs.workspace_id (§8.5 explicit workspace binding)

Revision ID: b3f1a7c90d42
Revises: 052b0d4a1283
Create Date: 2026-10-26 16:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f1a7c90d42'
down_revision: Union[str, None] = '052b0d4a1283'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'stage_runs',
        sa.Column('workspace_id', sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('stage_runs', 'workspace_id')
