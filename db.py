"""Office Attendance Bot — SQLite Database"""

import sqlite3
from datetime import datetime, date
from config import TIMEZONE
import pytz

DB_PATH = "attendance.db"

tz = pytz.timezone(TIMEZONE)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS employees (
            telegram_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'office_manager',
            branch TEXT NOT NULL DEFAULT 'integro',
            shift TEXT NOT NULL DEFAULT 'morning',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            check_in_time TEXT,
            check_out_time TEXT,
            check_in_video_id TEXT,
            check_out_video_id TEXT,
            status TEXT NOT NULL DEFAULT 'absent',
            late_minutes INTEGER DEFAULT 0,
            FOREIGN KEY (employee_id) REFERENCES employees(telegram_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_unique
            ON attendance(employee_id, date);

        CREATE INDEX IF NOT EXISTS idx_attendance_date
            ON attendance(date);

        CREATE INDEX IF NOT EXISTS idx_attendance_status
            ON attendance(status);
    """)
    conn.commit()
    conn.close()


# ── Employees CRUD ──

def add_employee(telegram_id: int, name: str, role: str = "office_manager",
                 branch: str = "integro", shift: str = "morning") -> bool:
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO employees (telegram_id, name, role, branch, shift, active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (telegram_id, name, role, branch, shift))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] add_employee error: {e}")
        return False
    finally:
        conn.close()


def remove_employee(telegram_id: int) -> bool:
    conn = get_conn()
    try:
        conn.execute("UPDATE employees SET active = 0 WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] remove_employee error: {e}")
        return False
    finally:
        conn.close()


def get_employee(telegram_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM employees WHERE telegram_id = ? AND active = 1", (telegram_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_employees() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM employees WHERE active = 1 ORDER BY branch, shift, name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_employees_by_shift(shift: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM employees WHERE active = 1 AND shift = ? ORDER BY branch, name",
        (shift,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_employees_by_branch(branch: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM employees WHERE active = 1 AND branch = ? ORDER BY shift, name",
        (branch,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Attendance CRUD ──

def check_in(employee_id: int, video_id: str = "") -> dict | None:
    """Check-in qilish. Status avtomatik hisoblanadi."""
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    conn = get_conn()
    try:
        emp = dict(conn.execute(
            "SELECT * FROM employees WHERE telegram_id = ? AND active = 1",
            (employee_id,)
        ).fetchone())

        if not emp:
            conn.close()
            return None

        shift_info = {"morning": (8, 0), "afternoon": (14, 0)}
        start_hour, start_min = shift_info.get(emp["shift"], (8, 0))

        late_minutes = 0
        if now.hour > start_hour or (now.hour == start_hour and now.minute > start_min):
            late_minutes = (now.hour - start_hour) * 60 + (now.minute - start_min)

        status = "late" if late_minutes > 0 else "on_time"

        conn.execute("""
            INSERT INTO attendance (employee_id, date, check_in_time, check_in_video_id, status, late_minutes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(employee_id, date) DO UPDATE SET
                check_in_time = excluded.check_in_time,
                check_in_video_id = excluded.check_in_video_id,
                status = excluded.status,
                late_minutes = excluded.late_minutes
        """, (employee_id, today_str, time_str, video_id, status, late_minutes))

        conn.commit()

        return {
            "employee": emp,
            "date": today_str,
            "time": time_str,
            "status": status,
            "late_minutes": late_minutes,
            "shift": emp["shift"],
        }
    except Exception as e:
        print(f"[DB] check_in error: {e}")
        return None
    finally:
        conn.close()


def check_out(employee_id: int, video_id: str = "") -> dict | None:
    """Check-out qilish."""
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    conn = get_conn()
    try:
        emp = get_employee(employee_id)
        if not emp:
            conn.close()
            return None

        conn.execute("""
            UPDATE attendance
            SET check_out_time = ?, check_out_video_id = ?
            WHERE employee_id = ? AND date = ?
        """, (time_str, video_id, employee_id, today_str))

        conn.commit()

        return {
            "employee": emp,
            "date": today_str,
            "check_out_time": time_str,
        }
    except Exception as e:
        print(f"[DB] check_out error: {e}")
        return None
    finally:
        conn.close()


def is_checked_in(employee_id: int, target_date: str = None) -> bool:
    """Bugun (yoki berilgan sana) uchun check-in qilinganmi?"""
    if target_date is None:
        target_date = datetime.now(tz).strftime("%Y-%m-%d")

    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM attendance WHERE employee_id = ? AND date = ? AND check_in_time IS NOT NULL",
        (employee_id, target_date)
    ).fetchone()
    conn.close()
    return row is not None


def is_checked_out(employee_id: int, target_date: str = None) -> bool:
    """Bugun uchun check-out qilinganmi?"""
    if target_date is None:
        target_date = datetime.now(tz).strftime("%Y-%m-%d")

    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM attendance WHERE employee_id = ? AND date = ? AND check_out_time IS NOT NULL",
        (employee_id, target_date)
    ).fetchone()
    conn.close()
    return row is not None


# ── Hisobot uchun query lar ──

def get_today_attendance() -> list[dict]:
    """Bugungi kun hisoboti."""
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.role, e.branch, e.shift
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE a.date = ?
        ORDER BY e.branch, e.shift, e.name
    """, (today_str,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_date_attendance(target_date: str) -> list[dict]:
    """Berilgan sana hisoboti."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.role, e.branch, e.shift
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE a.date = ?
        ORDER BY e.branch, e.shift, e.name
    """, (target_date,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_week_attendance() -> list[dict]:
    """Shu hafta (Mon-Sat) hisoboti."""
    now = datetime.now(tz)
    monday = now.date() - timedelta(days=now.weekday())
    saturday = monday + timedelta(days=5)
    return get_range_attendance(monday.strftime("%Y-%m-%d"), saturday.strftime("%Y-%m-%d"))


def get_month_attendance(year: int = None, month: int = None) -> list[dict]:
    """Shu oy hisoboti."""
    now = datetime.now(tz)
    if year is None:
        year = now.year
    if month is None:
        month = now.month
    start = f"{year}-{month:02d}-01"
    if month == 12:
        end = f"{year}-12-31"
    else:
        end = f"{year}-{month+1:02d}-01"
    return get_range_attendance(start, end)


def get_range_attendance(start_date: str, end_date: str) -> list[dict]:
    """Oraliq sana hisoboti."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.role, e.branch, e.shift
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE a.date >= ? AND a.date <= ?
        ORDER BY a.date DESC, e.branch, e.shift, e.name
    """, (start_date, end_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_late_attendance(start_date: str = None, end_date: str = None) -> list[dict]:
    """Kechikkanlar ro'yxati."""
    conn = get_conn()
    if start_date and end_date:
        rows = conn.execute("""
            SELECT a.*, e.name, e.role, e.branch, e.shift
            FROM attendance a
            JOIN employees e ON a.employee_id = e.telegram_id
            WHERE a.status = 'late' AND a.date >= ? AND a.date <= ?
            ORDER BY a.date DESC, a.late_minutes DESC
        """, (start_date, end_date)).fetchall()
    else:
        rows = conn.execute("""
            SELECT a.*, e.name, e.role, e.branch, e.shift
            FROM attendance a
            JOIN employees e ON a.employee_id = e.telegram_id
            WHERE a.status = 'late'
            ORDER BY a.date DESC, a.late_minutes DESC
        """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_employee_history(employee_id: int, limit: int = 30) -> list[dict]:
    """Bir xodim tarixi."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.role, e.branch, e.shift
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE a.employee_id = ?
        ORDER BY a.date DESC
        LIMIT ?
    """, (employee_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_branch_attendance(branch: str, target_date: str = None) -> list[dict]:
    """Bir filial hisoboti."""
    if target_date is None:
        target_date = datetime.now(tz).strftime("%Y-%m-%d")

    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.role, e.branch, e.shift
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE e.branch = ? AND a.date = ?
        ORDER BY e.shift, e.name
    """, (branch, target_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_branch_attendance_range(branch: str, start_date: str, end_date: str) -> list[dict]:
    """Bir filial oralig'idagi hisoboti."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.role, e.branch, e.shift
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE e.branch = ? AND a.date >= ? AND a.date <= ?
        ORDER BY a.date DESC, e.shift, e.name
    """, (branch, start_date, end_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_missing_today(shift: str = None) -> list[dict]:
    """Bugun hali kelmagan xodimlar."""
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = get_conn()

    if shift:
        query = """
            SELECT e.telegram_id, e.name, e.role, e.branch, e.shift
            FROM employees e
            LEFT JOIN attendance a ON e.telegram_id = a.employee_id AND a.date = ?
            WHERE e.active = 1 AND e.shift = ? AND a.id IS NULL
        """
        rows = conn.execute(query, (today_str, shift)).fetchall()
    else:
        query = """
            SELECT e.telegram_id, e.name, e.role, e.branch, e.shift
            FROM employees e
            LEFT JOIN attendance a ON e.telegram_id = a.employee_id AND a.date = ?
            WHERE e.active = 1 AND a.id IS NULL
        """
        rows = conn.execute(query, (today_str,)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


from datetime import timedelta
