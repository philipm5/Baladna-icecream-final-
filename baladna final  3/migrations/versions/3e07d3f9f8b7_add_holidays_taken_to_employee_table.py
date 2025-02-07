"""Add holidays_taken to Employee table

Revision ID: 3e07d3f9f8b7
Revises: 63a8a40ec8e9
Create Date: 2024-09-17 10:59:22.266286

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3e07d3f9f8b7'
down_revision = '63a8a40ec8e9'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('employee', schema=None) as batch_op:
        batch_op.add_column(sa.Column('holidays_taken', sa.Integer(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('employee', schema=None) as batch_op:
        batch_op.drop_column('holidays_taken')

    # ### end Alembic commands ###
