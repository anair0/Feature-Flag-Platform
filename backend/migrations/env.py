from alembic import context
from sqlalchemy import create_engine

from app.core.config import settings

url = context.config.get_main_option("sqlalchemy.url") or settings.migration_database_url


def run() -> None:
    if context.is_offline_mode():
        context.configure(url=url, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


run()
