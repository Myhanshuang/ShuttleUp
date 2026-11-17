"""Email password recovery."""
from alembic import op
import sqlalchemy as sa

revision = "ca62f119a430"
down_revision = "b513cdf9a122"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("password_reset_challenges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("used_at", sa.Integer()),
        sa.Column("delivered", sa.Boolean(), nullable=False))

def downgrade():
    op.drop_table("password_reset_challenges")
