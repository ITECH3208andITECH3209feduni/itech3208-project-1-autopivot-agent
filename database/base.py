"""Shared SQLAlchemy declarative base, column types and constraint naming rules."""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


# Every primary key in this schema is a BigInteger, which PostgreSQL turns into
# an auto-incrementing bigserial. SQLite does not: it only auto-assigns a value
# for a column declared exactly "INTEGER PRIMARY KEY", so "BIGINT PRIMARY KEY"
# comes out as an ordinary column and the first insert fails on a NOT NULL
# violation with no id to speak of.
#
# The variant below is the standard remedy — PostgreSQL still gets BIGINT,
# SQLite gets INTEGER, and nothing is lost either way because SQLite's INTEGER
# is already a 64-bit signed value. Foreign keys have to use the same type as
# the column they reference, so this is used for those as well.
BigIntId = BigInteger().with_variant(Integer, "sqlite")


class UtcDateTime(TypeDecorator):
    """A timestamp that is always UTC-aware in Python, on either database.

    PostgreSQL has a real `timestamptz` and hands back an aware datetime.
    SQLite has no timestamp type at all — it keeps the text
    "2026-09-11 07:14:22" and returns it naive, with the offset thrown away.

    Left alone that is a visible bug rather than a technical one: a naive
    timestamp is serialised to JSON without a "Z", and `new Date(...)` in the
    browser reads a bare ISO string as *local* time. In Sydney every "created"
    date would read ten hours ahead of the truth.

    So values are normalised to UTC on the way in and re-tagged as UTC on the
    way out. The generated DDL is unchanged — this still emits
    `TIMESTAMP WITH TIME ZONE` on PostgreSQL — so an existing PostgreSQL
    database and these models still describe the same schema.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not isinstance(value, datetime):
            return value
        if value.tzinfo is None:
            # Naive values are assumed UTC: everything in this codebase that
            # writes a timestamp uses datetime.now(timezone.utc).
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if not isinstance(value, datetime):
            return value
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
