"""memory and consolidation tables (M4)

Revision ID: d4e8b1c60a79
Revises: c7d2e5f81a63
Create Date: 2026-10-26 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8b1c60a79'
down_revision: Union[str, None] = 'c7d2e5f81a63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # approval_tasks gains a kind: stage-run decisions (existing rows)
    # vs consolidation-draft decisions (M4, §6.4). stage_run_id becomes
    # nullable for the latter; project_id carries the target instead.
    sa.Enum('STAGE', 'CONSOLIDATION', name='approval_kind').create(
        op.get_bind(), checkfirst=True
    )
    op.add_column(
        'approval_tasks',
        sa.Column(
            'kind',
            sa.Enum('STAGE', 'CONSOLIDATION', name='approval_kind'),
            nullable=False,
            server_default='STAGE',
        ),
    )
    op.add_column(
        'approval_tasks',
        sa.Column('project_id', sa.BigInteger(), nullable=True),
    )
    op.alter_column('approval_tasks', 'stage_run_id', nullable=True)
    op.create_index(
        op.f('ix_approval_tasks_project_id'), 'approval_tasks', ['project_id'],
        unique=False,
    )
    op.create_table('project_archives',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('project_id', sa.BigInteger(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('generated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_archives_project_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_archives')),
    sa.UniqueConstraint('project_id', name='uq_project_archives_project')
    )
    op.create_index(op.f('ix_project_archives_project_id'), 'project_archives', ['project_id'], unique=False)
    op.create_table('consolidation_drafts',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('project_id', sa.BigInteger(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('approval_task_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['approval_task_id'], ['approval_tasks.id'], name=op.f('fk_consolidation_drafts_approval_task_id')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_consolidation_drafts_project_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_consolidation_drafts'))
    )
    op.create_index(op.f('ix_consolidation_drafts_project_id'), 'consolidation_drafts', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_consolidation_drafts_project_id'), table_name='consolidation_drafts')
    op.drop_table('consolidation_drafts')
    op.drop_index(op.f('ix_project_archives_project_id'), table_name='project_archives')
    op.drop_table('project_archives')
    op.drop_index(op.f('ix_approval_tasks_project_id'), table_name='approval_tasks')
    op.alter_column('approval_tasks', 'stage_run_id', nullable=False)
    op.drop_column('approval_tasks', 'project_id')
    op.drop_column('approval_tasks', 'kind')
    sa.Enum(name='approval_kind').drop(op.get_bind(), checkfirst=True)
