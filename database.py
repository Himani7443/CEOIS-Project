"""SQLite helpers for the CEOIS prototype."""
import os
import sqlite3
import secrets
from contextlib import closing

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ceois.db")


def get_connection():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_database():
    """Create required tables and safely migrate existing report records."""
    with closing(get_connection()) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                area TEXT NOT NULL,
                problem TEXT NOT NULL,
                report_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'Pending',
                tracking_code TEXT
            )
        """)

        # Add tracking_code to an existing database without deleting reports.
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(reports)").fetchall()
        }

        if "tracking_code" not in columns:
            connection.execute(
                "ALTER TABLE reports ADD COLUMN tracking_code TEXT"
            )

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_reports_tracking_code
            ON reports(tracking_code)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS outage_announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                area TEXT NOT NULL,
                outage_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                restoration_time TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Awaiting Verification',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.commit()




def save_report(name, area, problem):
    """Save a report and return its unique tracking code."""
    with closing(get_connection()) as connection:
        tracking_code = f"CEOIS-{secrets.token_hex(4).upper()}"

        cursor = connection.execute(
            """
            INSERT INTO reports (name, area, problem, tracking_code)
            VALUES (?, ?, ?, ?)
            """,
            (name, area, problem, tracking_code),
        )

        connection.commit()
        return tracking_code



def get_reports(area=None, status=None):
    query = "SELECT id, name, area, problem, report_date, status FROM reports WHERE 1=1"
    params = []
    if area:
        query += " AND area = ?"
        params.append(area)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id DESC"
    with closing(get_connection()) as connection:
        return connection.execute(query, params).fetchall()


def update_report_status(report_id, status):
    with closing(get_connection()) as connection:
        cursor = connection.execute(
            "UPDATE reports SET status = ? WHERE id = ?", (status, report_id)
        )
        connection.commit()
        return cursor.rowcount == 1


def delete_report(report_id):
    with closing(get_connection()) as connection:
        cursor = connection.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        connection.commit()
        return cursor.rowcount == 1


def get_announcement(announcement_id):
    with closing(get_connection()) as connection:
        return connection.execute(
            "SELECT * FROM outage_announcements WHERE id = ?", (announcement_id,)
        ).fetchone()


def get_announcements(area=None):
    query = "SELECT * FROM outage_announcements"
    params = []
    if area:
        query += " WHERE area = ?"
        params.append(area)
    query += " ORDER BY outage_date ASC, start_time ASC, id DESC"
    with closing(get_connection()) as connection:
        return connection.execute(query, params).fetchall()


def save_announcement(area, outage_date, start_time, restoration_time, reason, status,
                      announcement_id=None):
    with closing(get_connection()) as connection:
        if announcement_id is None:
            cursor = connection.execute("""
                INSERT INTO outage_announcements
                    (area, outage_date, start_time, restoration_time, reason, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (area, outage_date, start_time, restoration_time, reason, status))
        else:
            cursor = connection.execute("""
                UPDATE outage_announcements
                SET area = ?, outage_date = ?, start_time = ?, restoration_time = ?,
                    reason = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (area, outage_date, start_time, restoration_time, reason, status,
                  announcement_id))
        connection.commit()
        return cursor.rowcount == 1 if announcement_id is not None else cursor.lastrowid


def delete_announcement(announcement_id):
    with closing(get_connection()) as connection:
        cursor = connection.execute(
            "DELETE FROM outage_announcements WHERE id = ?", (announcement_id,)
        )
        connection.commit()
        return cursor.rowcount == 1


if __name__ == "__main__":
    create_database()
    print("CEOIS database tables are ready. Existing records were preserved.")
