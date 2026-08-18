"""widen vector_id to bigint

Revision ID: b8ebbcf96a03
Revises: 00788d4a54e0
Create Date: 2026-08-17 12:23:38.086004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8ebbcf96a03'
down_revision: Union[str, Sequence[str], None] = '00788d4a54e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQL Server refuses ALTER COLUMN while a dependent index exists --
    # ix_resume_chunks_vector_id must be dropped and recreated around it.
    op.drop_index('ix_resume_chunks_vector_id', table_name='resume_chunks')
    op.alter_column('resume_chunks', 'vector_id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=True)
    op.create_index('ix_resume_chunks_vector_id', 'resume_chunks', ['vector_id'])
    op.alter_column('roles', 'vector_id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=True)
    op.alter_column('technical_skills', 'vector_id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('technical_skills', 'vector_id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=True)
    op.alter_column('roles', 'vector_id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=True)
    op.drop_index('ix_resume_chunks_vector_id', table_name='resume_chunks')
    op.alter_column('resume_chunks', 'vector_id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=True)
    op.create_index('ix_resume_chunks_vector_id', 'resume_chunks', ['vector_id'])
