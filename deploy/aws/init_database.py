"""Run once with migration credentials; never prints credentials."""

import os
from uuid import uuid4

from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infrastructure.auth_security import get_password_hasher
from app.infrastructure.database.models import User

engine = create_engine(os.environ["DATABASE_URL"], hide_parameters=True)
with engine.begin() as connection:
    raw = connection.connection.driver_connection
    with raw.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'euapp'")
        if not cursor.fetchone():
            cursor.execute(
                sql.SQL("CREATE ROLE euapp LOGIN PASSWORD {}").format(
                    sql.Literal(os.environ["DB_APP_PASSWORD"])
                )
            )
        cursor.execute("GRANT CONNECT ON DATABASE encuentrau TO euapp")
        cursor.execute("GRANT USAGE ON SCHEMA public TO euapp")
        cursor.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "
            "public TO euapp"
        )
        cursor.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO euapp")
        cursor.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, "
            "INSERT, UPDATE, DELETE ON TABLES TO euapp"
        )
        cursor.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, "
            "SELECT ON SEQUENCES TO euapp"
        )
with Session(engine) as session:
    if not session.query(User).filter_by(email="camila@example.com").first():
        session.add(
            User(
                id=uuid4(),
                full_name="Camila",
                email="camila@example.com",
                student_code="ADMIN-CAMILA",
                password_hash=get_password_hasher().hash(
                    os.environ["INITIAL_ADMIN_PASSWORD"]
                ),
                role="admin",
                is_active=True,
            )
        )
        session.commit()
print("Database permissions and initial administrator ready")
