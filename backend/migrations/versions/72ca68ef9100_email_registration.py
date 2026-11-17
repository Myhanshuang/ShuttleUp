"""Add verified email identities and registration challenges.

Revision ID: 72ca68ef9100
Revises: 9c2ee09947b2
"""
from alembic import op
import sqlalchemy as sa

revision = '72ca68ef9100'
down_revision = '9c2ee09947b2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('email_identities',
        sa.Column('email', sa.String(254), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('verified_at', sa.Integer(), nullable=False))
    op.create_table('email_challenges',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('email', sa.String(254), nullable=False, unique=True),
        sa.Column('owner_user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('code_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.Integer(), nullable=False),
        sa.Column('sent_at', sa.Integer(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('used_at', sa.Integer(), nullable=True),
        sa.Column('delivered', sa.Boolean(), nullable=False))
    op.create_table('email_send_attempts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('email_hash', sa.String(64), nullable=False),
        sa.Column('ip_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.Integer(), nullable=False))
    for column in ('email_hash', 'ip_hash', 'created_at'):
        op.create_index(f'ix_email_send_attempts_{column}', 'email_send_attempts', [column])


def downgrade():
    op.drop_table('email_send_attempts')
    op.drop_table('email_challenges')
    op.drop_table('email_identities')
