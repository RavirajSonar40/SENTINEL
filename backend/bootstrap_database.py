"""Initialize a genuinely empty deployment database.

The historical 015 baseline represents a schema that was created outside
Alembic. On a brand-new Render database those legacy tables do not exist, so
the later incremental migrations cannot run. This bootstrap creates the
current declarative schema and records the migration head. Existing databases
continue through the normal Alembic upgrade path.
"""

from sqlalchemy import inspect, text

from app.core.database import Base, engine


def initialize_database() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if existing_tables:
        return

    Base.metadata.create_all(bind=engine)
    # Alembic's default version column is VARCHAR(32), but this repository's
    # descriptive revision identifiers are longer than 32 characters.
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE alembic_version ("
            "version_num VARCHAR(255) NOT NULL PRIMARY KEY)"
        ))
    # The declarative schema includes all tables, but migration 036 also
    # installs the database-level forensic immutability triggers. Record the
    # pre-036 revision directly; the container command runs `upgrade head`
    # immediately afterward and applies 036 normally.
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO alembic_version (version_num) "
                "VALUES (:version)"
            ),
            {"version": "035_add_phase16_advanced_reliability"},
        )


if __name__ == "__main__":
    initialize_database()
