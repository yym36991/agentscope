"""trace matrix tables (req/fp/tc/budget side-tables)

Revision ID: e8f3c2a1b7d9
Revises: d4e8b1c60a79
Create Date: 2026-10-27 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f3c2a1b7d9'
down_revision: Union[str, None] = 'd4e8b1c60a79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('trace_requirements',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('project_id', sa.BigInteger(), nullable=False),
    sa.Column('stage_run_id', sa.BigInteger(), nullable=False),
    sa.Column('req_id', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_trace_requirements_project_id')),
    sa.ForeignKeyConstraint(['stage_run_id'], ['stage_runs.id'], name=op.f('fk_trace_requirements_stage_run_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trace_requirements')),
    sa.UniqueConstraint('stage_run_id', 'req_id', name='uq_trace_requirements_run_req')
    )
    op.create_index(op.f('ix_trace_requirements_project_id'), 'trace_requirements', ['project_id'], unique=False)
    op.create_index(op.f('ix_trace_requirements_stage_run_id'), 'trace_requirements', ['stage_run_id'], unique=False)

    op.create_table('function_points',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('project_id', sa.BigInteger(), nullable=False),
    sa.Column('stage_run_id', sa.BigInteger(), nullable=False),
    sa.Column('fp_id', sa.String(length=32), nullable=False),
    sa.Column('category', sa.Enum('ILF', 'EIF', 'EI', 'EO', 'EQ', name='fp_category'), nullable=False),
    sa.Column('complexity', sa.String(length=16), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('fr_refs', sa.JSON(), nullable=False),
    sa.Column('weight', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_function_points_project_id')),
    sa.ForeignKeyConstraint(['stage_run_id'], ['stage_runs.id'], name=op.f('fk_function_points_stage_run_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_function_points')),
    sa.UniqueConstraint('stage_run_id', 'fp_id', name='uq_function_points_run_fp')
    )
    op.create_index(op.f('ix_function_points_project_id'), 'function_points', ['project_id'], unique=False)
    op.create_index(op.f('ix_function_points_stage_run_id'), 'function_points', ['stage_run_id'], unique=False)

    op.create_table('trace_test_cases',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('project_id', sa.BigInteger(), nullable=False),
    sa.Column('stage_run_id', sa.BigInteger(), nullable=False),
    sa.Column('tc_id', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('fp_refs', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_trace_test_cases_project_id')),
    sa.ForeignKeyConstraint(['stage_run_id'], ['stage_runs.id'], name=op.f('fk_trace_test_cases_stage_run_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trace_test_cases')),
    sa.UniqueConstraint('stage_run_id', 'tc_id', name='uq_trace_test_cases_run_tc')
    )
    op.create_index(op.f('ix_trace_test_cases_project_id'), 'trace_test_cases', ['project_id'], unique=False)
    op.create_index(op.f('ix_trace_test_cases_stage_run_id'), 'trace_test_cases', ['stage_run_id'], unique=False)

    op.create_table('trace_budget_rows',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('project_id', sa.BigInteger(), nullable=False),
    sa.Column('stage_run_id', sa.BigInteger(), nullable=False),
    sa.Column('fp_id', sa.String(length=32), nullable=False),
    sa.Column('hours', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_trace_budget_rows_project_id')),
    sa.ForeignKeyConstraint(['stage_run_id'], ['stage_runs.id'], name=op.f('fk_trace_budget_rows_stage_run_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trace_budget_rows')),
    sa.UniqueConstraint('stage_run_id', 'fp_id', name='uq_trace_budget_rows_run_fp')
    )
    op.create_index(op.f('ix_trace_budget_rows_project_id'), 'trace_budget_rows', ['project_id'], unique=False)
    op.create_index(op.f('ix_trace_budget_rows_stage_run_id'), 'trace_budget_rows', ['stage_run_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trace_budget_rows_stage_run_id'), table_name='trace_budget_rows')
    op.drop_index(op.f('ix_trace_budget_rows_project_id'), table_name='trace_budget_rows')
    op.drop_table('trace_budget_rows')
    op.drop_index(op.f('ix_trace_test_cases_stage_run_id'), table_name='trace_test_cases')
    op.drop_index(op.f('ix_trace_test_cases_project_id'), table_name='trace_test_cases')
    op.drop_table('trace_test_cases')
    op.drop_index(op.f('ix_function_points_stage_run_id'), table_name='function_points')
    op.drop_index(op.f('ix_function_points_project_id'), table_name='function_points')
    op.drop_table('function_points')
    op.execute('DROP TYPE IF EXISTS fp_category')
    op.drop_index(op.f('ix_trace_requirements_stage_run_id'), table_name='trace_requirements')
    op.drop_index(op.f('ix_trace_requirements_project_id'), table_name='trace_requirements')
    op.drop_table('trace_requirements')
