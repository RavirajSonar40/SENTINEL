"""Initialize a genuinely empty deployment database.

The historical 015 baseline represents a schema that was created outside
Alembic. On a brand-new Render database those legacy tables do not exist, so
the later incremental migrations cannot run. This bootstrap creates the
current declarative schema and records the migration head. Existing databases
continue through the normal Alembic upgrade path.
"""

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.database import Base, engine


def initialize_database() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if existing_tables:
        return

    Base.metadata.create_all(bind=engine)
    alembic_config = Config("alembic.ini")
    command.stamp(alembic_config, "head")


if __name__ == "__main__":
    initialize_database()
