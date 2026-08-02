"""Safe add orders.order_amount

If the existing table already has the column, this migration is effectively a no-op.
Otherwise:
- Add order_amount as nullable with server_default 0
- Backfill existing rows to 0
- Set NOT NULL

This avoids breaking existing order rows.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = '0002_safe_add_order_amount'
down_revision = '0001_init'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    res = conn.execute(
        text(
            "SELECT 1 FROM pragma_table_info(:t) WHERE name=:c"
        ),
        {"t": table_name, "c": column_name},
    )
    return res.first() is not None


def upgrade() -> None:
    if column_exists('orders', 'order_amount'):
        # Already present
        return

    # Step 1: add column with default 0 to avoid NULLs for existing rows
    op.add_column(
        'orders',
        sa.Column('order_amount', sa.Float(), nullable=True, server_default=sa.text('0')),
    )

    # Step 2: backfill (for DBs that may not apply server_default retroactively)
    conn = op.get_bind()
    conn.execute(text("UPDATE orders SET order_amount = 0 WHERE order_amount IS NULL"))

    # Step 3: set NOT NULL
    op.alter_column('orders', 'order_amount', nullable=False)


def downgrade() -> None:
    # Conservative downgrade: remove column only if it exists.
    if not column_exists('orders', 'order_amount'):
        return
    op.drop_column('orders', 'order_amount')

