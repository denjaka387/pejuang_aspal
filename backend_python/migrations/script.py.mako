## -*- coding: utf-8 -*-
<%!
from datetime import datetime
%>
"""${message}"

Revision ID: ${up_revision}
down_revision: ${down_revision}
Create Date: ${create_date}

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '${up_revision}'
down_revision = '${down_revision}'
branch_labels = None
depends_on = None


def upgrade() -> None:
    ${upgrades if upgrades else 'pass'}


def downgrade() -> None:
    ${downgrades if downgrades else 'pass'}

