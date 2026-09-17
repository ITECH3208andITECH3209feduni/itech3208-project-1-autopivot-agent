from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from api.env import load_environment
from database.base import Base
import database.models
from database.connection import get_database_url


load_environment()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option(
    "sqlalchemy.url",
    get_database_url().replace("%", "%%"),
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite cannot ALTER or DROP a constraint in place; Alembic's batch
            # mode works around it by rebuilding the table. The existing
            # migrations still will not run on SQLite — they use PostgreSQL-only
            # syntax such as UPDATE ... FROM — which is why
            # `python -m scripts.init_db` builds the SQLite schema from the
            # models instead. This keeps any *future* migration usable on both.
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()