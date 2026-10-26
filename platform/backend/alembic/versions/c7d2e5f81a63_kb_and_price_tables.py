"""kb grants/links and price baseline tables (M3)

Revision ID: c7d2e5f81a63
Revises: b3f1a7c90d42
Create Date: 2026-10-26 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d2e5f81a63'
down_revision: Union[str, None] = 'b3f1a7c90d42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('kbs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('kb_type', sa.Enum('SPEC', 'PRICE', 'CASE', 'TEMPLATE', 'DISTILL', name='kb_type'), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('agentscope_kb_id', sa.String(length=64), nullable=True),
    sa.Column('owner_group_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_group_id'], ['groups.id'], name=op.f('fk_kbs_owner_group_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kbs'))
    )
    op.create_index(op.f('ix_kbs_name'), 'kbs', ['name'], unique=True)
    op.create_table('kb_grants',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('kb_id', sa.BigInteger(), nullable=False),
    sa.Column('group_id', sa.BigInteger(), nullable=False),
    sa.Column('level', sa.Enum('READ', 'WRITE', name='grant_level'), nullable=False),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], name=op.f('fk_kb_grants_group_id')),
    sa.ForeignKeyConstraint(['kb_id'], ['kbs.id'], name=op.f('fk_kb_grants_kb_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kb_grants')),
    sa.UniqueConstraint('kb_id', 'group_id', name='uq_kb_grants_kb_group')
    )
    op.create_index(op.f('ix_kb_grants_group_id'), 'kb_grants', ['group_id'], unique=False)
    op.create_index(op.f('ix_kb_grants_kb_id'), 'kb_grants', ['kb_id'], unique=False)
    op.create_table('project_kb_links',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('project_id', sa.BigInteger(), nullable=False),
    sa.Column('kb_id', sa.BigInteger(), nullable=False),
    sa.Column('stage', sa.Enum('NONE', 'REQUIREMENT', 'PROTOTYPE', 'BUDGET', 'TESTCASES', 'TESTING', 'ACCEPTANCE', name='stage_key', create_type=False), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['kb_id'], ['kbs.id'], name=op.f('fk_project_kb_links_kb_id')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_kb_links_project_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_project_kb_links'))
    )
    op.create_index(op.f('ix_project_kb_links_kb_id'), 'project_kb_links', ['kb_id'], unique=False)
    op.create_index(op.f('ix_project_kb_links_project_id'), 'project_kb_links', ['project_id'], unique=False)
    op.create_table('price_items',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('region', sa.String(length=64), nullable=False),
    sa.Column('item_type', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('value', sa.Float(), nullable=False),
    sa.Column('unit', sa.String(length=64), nullable=False),
    sa.Column('effective_year', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=200), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('imported_by_user_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['imported_by_user_id'], ['users.id'], name=op.f('fk_price_items_imported_by_user_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_price_items')),
    sa.UniqueConstraint('region', 'item_type', 'name', 'effective_year', name='uq_price_items_key')
    )
    op.create_index(op.f('ix_price_items_item_type'), 'price_items', ['item_type'], unique=False)
    op.create_index(op.f('ix_price_items_region'), 'price_items', ['region'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_price_items_region'), table_name='price_items')
    op.drop_index(op.f('ix_price_items_item_type'), table_name='price_items')
    op.drop_table('price_items')
    op.drop_index(op.f('ix_project_kb_links_project_id'), table_name='project_kb_links')
    op.drop_index(op.f('ix_project_kb_links_kb_id'), table_name='project_kb_links')
    op.drop_table('project_kb_links')
    op.drop_index(op.f('ix_kb_grants_kb_id'), table_name='kb_grants')
    op.drop_index(op.f('ix_kb_grants_group_id'), table_name='kb_grants')
    op.drop_table('kb_grants')
    op.drop_index(op.f('ix_kbs_name'), table_name='kbs')
    op.drop_table('kbs')
