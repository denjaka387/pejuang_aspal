"""Empty placeholder initial revision.

This repository previously created tables via Base.metadata.create_all().
For Alembic production readiness we provide a first baseline revision.

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_init'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op baseline
    pass


def downgrade() -> None:
    # No-op baseline
    pass

