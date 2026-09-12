"""Existing-file connections and explicit, opt-in demo setup."""

import argparse
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def default_path() -> Path:
    return Path(os.environ.get("TRIAL_BOOKING_DB", ROOT / "var/trial-booking.sqlite3"))


@contextmanager
def connect(db_path: Path, *, readonly: bool = False):
    db = sqlite3.connect(
        Path(db_path).resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
        uri=True,
        timeout=5,
        isolation_level=None,
    )
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        yield db
    finally:
        if db.in_transaction:
            db.rollback()
        db.close()


def setup_database(db_path: Path, *, reset: bool = False) -> None:
    path = Path(db_path).absolute()
    if path.is_symlink():
        raise ValueError("Refusing to set up a database through a symbolic link.")
    if sqlite3.sqlite_version_info < (3, 37):
        raise RuntimeError("SQLite 3.37 or later is required.")
    if reset and path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents an ordinary setup from erasing existing data.
    with path.open("xb"):
        pass
    try:
        with connect(path) as db:
            scripts = [
                (Path(__file__).parent / name).read_text(encoding="utf-8")
                for name in ("schema.sql", "seed.sql")
            ]
            db.executescript("BEGIN IMMEDIATE;\n" + "\n".join(scripts))
            for row in db.execute("SELECT starts_at FROM trial_classes"):
                datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%S.%fZ")
            db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explicit synthetic database setup")
    parser.add_argument("--db", type=Path, default=default_path())
    parser.add_argument(
        "--reset", action="store_true", help="Erase only the selected database"
    )
    args = parser.parse_args()
    try:
        setup_database(args.db, reset=args.reset)
    except FileExistsError:
        parser.exit(
            1, "Database already exists; use --reset only to erase this demo.\n"
        )
    print(f"Initialized synthetic data: {args.db.resolve()}")
