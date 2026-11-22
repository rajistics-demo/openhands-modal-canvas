"""Store Modal sandbox and memory snapshot identifiers for the Compose pilot."""
from alembic import op
import sqlalchemy as sa

revision = 'modal_pilot_001'
down_revision = '213'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('v1_remote_sandbox', sa.Column('provider_resource_id', sa.String()))
    op.add_column('v1_remote_sandbox', sa.Column('modal_snapshot_id', sa.String()))


def downgrade():
    op.drop_column('v1_remote_sandbox', 'modal_snapshot_id')
    op.drop_column('v1_remote_sandbox', 'provider_resource_id')
