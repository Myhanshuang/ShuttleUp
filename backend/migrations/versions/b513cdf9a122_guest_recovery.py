"""Guest identity recovery."""
from alembic import op
import sqlalchemy as sa
revision = 'b513cdf9a122'
down_revision = '72ca68ef9100'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('guest_recovery',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('code_hash', sa.String(64), nullable=False, unique=True))

def downgrade():
    op.drop_table('guest_recovery')
