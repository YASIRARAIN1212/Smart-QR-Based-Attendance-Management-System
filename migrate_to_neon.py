
import os
import sqlite3
from pathlib import Path
from datetime import datetime, date, time

from dotenv import load_dotenv
from sqlalchemy import (
    create_engine,
    text,
    select,
    and_,
    DateTime,
    Date,
    Time,
)

from models import db


# =====================================================
# CONFIGURATION
# =====================================================

BASE_DIR = Path(__file__).resolve().parent
SQLITE_PATH = BASE_DIR / "instance" / "attendance.db"

load_dotenv(BASE_DIR / ".env", override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

TABLES = [
    "users",
    "subjects",
    "family_emails",
    "sessions",
    "enrollments",
    "attendance",
    "audit_logs",
]

DEFERRED_COLUMNS = {
    "users": "created_by_admin_id",
    "sessions": "compensates_session_id",
}


# =====================================================
# DATA TYPE CONVERSION
# =====================================================

def convert_value(value, column):

    if value is None:
        return None

    column_type = column.type

    try:
        if isinstance(column_type, DateTime):
            if isinstance(value, str):
                value = value.replace("Z", "+00:00")
                return datetime.fromisoformat(value)

        elif isinstance(column_type, Date):
            if isinstance(value, str):
                return date.fromisoformat(value)

        elif isinstance(column_type, Time):
            if isinstance(value, str):
                return time.fromisoformat(value)

    except (ValueError, TypeError) as error:
        raise RuntimeError(
            f"Cannot convert {column.name} value "
            f"{value!r}: {error}"
        )

    return value


def normalize_record(record, target_table):

    normalized = {}

    for column in target_table.columns:

        if column.name in record:
            normalized[column.name] = convert_value(
                record[column.name],
                column
            )

    return normalized


# =====================================================
# SOURCE DATABASE
# =====================================================

def get_source_counts(source):

    counts = {}

    for table in TABLES:

        exists = source.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            AND name = ?
            """,
            (table,)
        ).fetchone()

        if not exists:
            raise RuntimeError(
                f"SQLite table missing: {table}"
            )

        counts[table] = source.execute(
            f'SELECT COUNT(*) FROM "{table}"'
        ).fetchone()[0]

    return counts


# =====================================================
# DATABASE VALIDATION
# =====================================================

def validate_columns(source):

    for table in TABLES:

        source_columns = {
            row["name"]
            for row in source.execute(
                f'PRAGMA table_info("{table}")'
            )
        }

        target_columns = {
            column.name
            for column in db.metadata.tables[table].columns
        }

        if source_columns != target_columns:

            raise RuntimeError(
                f"\nColumn mismatch: {table}\n"
                f"SQLite: {source_columns}\n"
                f"Neon: {target_columns}"
            )


def check_destination(engine):

    initial_counts = {}

    with engine.connect() as conn:

        for table in TABLES:

            count = conn.execute(
                text(
                    f'SELECT COUNT(*) FROM "{table}"'
                )
            ).scalar_one()

            initial_counts[table] = count

            # Only audit_logs may contain existing records.
            if table != "audit_logs" and count != 0:

                raise RuntimeError(
                    f"Neon {table} contains {count} records. "
                    "Migration stopped to protect existing data."
                )

    return initial_counts


# =====================================================
# AUDIT LOG MIGRATION
# =====================================================

def migrate_audit_logs(source, conn, target):

    print("\nTransferring audit_logs...")

    cursor = source.execute(
        'SELECT * FROM "audit_logs"'
    )

    inserted = 0
    skipped = 0

    primary_keys = {
        column.name
        for column in target.primary_key.columns
    }

    compare_columns = [
        column
        for column in target.columns
        if column.name not in primary_keys
    ]

    for row in cursor:

        record = normalize_record(
            dict(row),
            target
        )

        # Compare existing records using properly typed values.
        conditions = [
            column.is_not_distinct_from(
                record[column.name]
            )
            for column in compare_columns
        ]

        duplicate = conn.execute(
            select(target.c.id)
            .where(and_(*conditions))
            .limit(1)
        ).first()

        if duplicate:

            skipped += 1
            continue

        # Preserve existing Neon IDs.
        # PostgreSQL generates new IDs for imported audit logs.
        for pk in primary_keys:
            record.pop(pk, None)

        conn.execute(
            target.insert().values(**record)
        )

        inserted += 1

    print(f"Audit logs inserted: {inserted}")
    print(f"Audit logs skipped: {skipped}")

    return inserted, skipped


# =====================================================
# NORMAL TABLE MIGRATION
# =====================================================

def migrate_table(source, conn, table):

    target = db.metadata.tables[table]

    deferred = DEFERRED_COLUMNS.get(table)

    cursor = source.execute(
        f'SELECT * FROM "{table}"'
    )

    inserted = 0

    print(f"\nTransferring {table}...")

    while True:

        rows = cursor.fetchmany(500)

        if not rows:
            break

        batch = []

        for row in rows:

            record = normalize_record(
                dict(row),
                target
            )

            # Temporarily remove self-referencing foreign keys.
            if deferred:
                record[deferred] = None

            batch.append(record)

        if batch:

            conn.execute(
                target.insert(),
                batch
            )

            inserted += len(batch)

    # Restore self-referencing relationships.
    if deferred:

        source_rows = source.execute(
            f'''
            SELECT id, "{deferred}"
            FROM "{table}"
            WHERE "{deferred}" IS NOT NULL
            '''
        ).fetchall()

        for row in source_rows:

            conn.execute(
                target.update()
                .where(target.c.id == row["id"])
                .values({
                    deferred: row[deferred]
                })
            )

    print(f"Inserted: {inserted}")

    return inserted


# =====================================================
# POSTGRESQL ID SEQUENCES
# =====================================================

def synchronize_sequences(conn):

    print("\nSynchronizing PostgreSQL ID sequences...")

    for table in TABLES:

        target = db.metadata.tables[table]

        if "id" not in target.columns:
            continue

        sequence = conn.execute(
            text("""
                SELECT pg_get_serial_sequence(
                    :table_name,
                    'id'
                )
            """),
            {"table_name": table}
        ).scalar_one_or_none()

        if not sequence:
            continue

        max_id = conn.execute(
            text(
                f'SELECT MAX(id) FROM "{table}"'
            )
        ).scalar_one()

        if max_id is not None:

            conn.execute(
                text("""
                    SELECT setval(
                        CAST(:sequence AS regclass),
                        :max_id,
                        true
                    )
                """),
                {
                    "sequence": sequence,
                    "max_id": max_id
                }
            )

        print(f"Sequence checked: {table}")


# =====================================================
# FINAL VERIFICATION
# =====================================================

def verify_migration(engine, source_counts, initial_counts):

    print("\nVERIFYING NEON DATABASE...")

    total = 0

    with engine.connect() as conn:

        for table in TABLES:

            actual = conn.execute(
                text(
                    f'SELECT COUNT(*) FROM "{table}"'
                )
            ).scalar_one()

            expected = (
                initial_counts[table]
                + source_counts[table]
            )

            print(
                f"{table}: "
                f"Expected={expected}, "
                f"Neon={actual}"
            )

            if actual != expected:

                raise RuntimeError(
                    f"Verification failed for {table}"
                )

            total += actual

    print("\n" + "=" * 50)
    print("MIGRATION SUCCESSFUL!")
    print(f"Total records now in Neon: {total}")
    print("All seven tables verified.")
    print("=" * 50)


# =====================================================
# MAIN
# =====================================================

def main():

    if not SQLITE_PATH.exists():

        raise FileNotFoundError(
            f"SQLite database not found: {SQLITE_PATH}"
        )

    if not DATABASE_URL:

        raise ValueError(
            "DATABASE_URL missing from .env"
        )

    if not DATABASE_URL.startswith(
        ("postgresql://", "postgresql+psycopg://")
    ):

        raise ValueError(
            "Invalid PostgreSQL connection URL"
        )

    print("Connecting to SQLite and Neon...")

    source = sqlite3.connect(
        f"file:{SQLITE_PATH.as_posix()}?mode=ro",
        uri=True
    )

    source.row_factory = sqlite3.Row

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 20
        }
    )

    try:

        # Read original database.
        source_counts = get_source_counts(source)

        print("\nSOURCE DATABASE:")

        for table, count in source_counts.items():
            print(f"{table}: {count}")

        # Create missing destination tables.
        db.metadata.create_all(engine)

        # Validate schema.
        validate_columns(source)

        print("\nDatabase schemas validated.")

        # Check destination.
        initial_counts = check_destination(engine)

        print("\nEXISTING NEON RECORDS:")

        for table, count in initial_counts.items():
            print(f"{table}: {count}")

        print("\nExisting audit logs will be preserved.")

        inserted_counts = {}

        # Everything is transferred in ONE transaction.
        # Any failure rolls back the complete migration.
        with engine.begin() as conn:

            for table in TABLES:

                target = db.metadata.tables[table]

                if table == "audit_logs":

                    inserted, skipped = migrate_audit_logs(
                        source,
                        conn,
                        target
                    )

                    inserted_counts[table] = inserted

                else:

                    inserted_counts[table] = migrate_table(
                        source,
                        conn,
                        table
                    )

            synchronize_sequences(conn)

        print("\nDatabase transaction committed.")

        # Verify final database.
        verify_migration(
            engine,
            source_counts,
            initial_counts
        )

        print(
            "\nNew records inserted:",
            sum(inserted_counts.values())
        )

    finally:

        source.close()
        engine.dispose()


if __name__ == "__main__":
    main()
