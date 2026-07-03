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

    # Migration: custom work times (agar column mavjud bo'lmasa)
    for col in ["custom_work_start", "custom_work_end"]:
        try:
            conn.execute(f"ALTER TABLE employees ADD COLUMN {col} TEXT")
        except Exception:
            pass

    # Migration: late_reason (agar column mavjud bo'lmasa)
    try:
        conn.execute("ALTER TABLE attendance ADD COLUMN late_reason TEXT")
    except Exception:
        pass

    conn.commit()
    conn.close()


# ── Employees CRUD ──

def add_employee(telegram_id: int, name: str, role: str = "office_manager",
                 branch: str = "integro", shift: str = "morning",
                 custom_work_start: str | None = None,
                 custom_work_end: str | None = None) -> bool:
    conn = get_conn()
    try:
        # Avval mavjudligini tekshiramiz
        existing = conn.execute(
            "SELECT custom_work_start, custom_work_end FROM employees WHERE telegram_id = ?",
            (telegram_id,)
        ).fetchone()
        
        if existing:
            # Mavjud — custom vaqtlarni saqlab, UPDATE qilamiz
            conn.execute("""
                UPDATE employees
                SET name = ?, role = ?, branch = ?, shift = ?, active = 1
                WHERE telegram_id = ?
            """, (name, role, branch, shift, telegram_id))
            
            # Agar Sheets dan custom vaqt kelgan bo'lsa, uni ham yangilaymiz
            if custom_work_start is not None and custom_work_start != "":
                conn.execute("UPDATE employees SET custom_work_start = ? WHERE telegram_id = ?",
                             (custom_work_start, telegram_id))
            if custom_work_end is not None and custom_work_end != "":
                conn.execute("UPDATE employees SET custom_work_end = ? WHERE telegram_id = ?",
                             (custom_work_end, telegram_id))
        else:
            # Yangi xodim
            conn.execute("""
                INSERT INTO employees (telegram_id, name, role, branch, shift, active,
                                       custom_work_start, custom_work_end)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """, (telegram_id, name, role, branch, shift,
                  custom_work_start, custom_work_end))
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


def _resolve_academic_branches(branch: str) -> list[str]:
    """academic va academic_support ni bitta filial deb hisoblash."""
    if branch in ("academic", "academic_support"):
        return ["academic", "academic_support"]
    return [branch]

def get_employees_by_branch(branch: str) -> list[dict]:
    branches = _resolve_academic_branches(branch)
    placeholders = ",".join("?" for _ in branches)
    conn = get_conn()
    rows = conn.execute(
        f"SELECT * FROM employees WHERE active = 1 AND branch IN ({placeholders}) ORDER BY shift, name",
        branches
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_employee_fields(telegram_id: int, **kwargs) -> bool:
    """Xodim maydonlarini yangilash (name, role, branch, shift)."""
    allowed = {"name", "role", "branch", "shift", "active", "custom_work_start", "custom_work_end"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [telegram_id]
    conn = get_conn()
    try:
        conn.execute(f"UPDATE employees SET {set_clause} WHERE telegram_id = ?", values)
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] update_employee_fields error: {e}")
        return False
    finally:
        conn.close()


def add_attendance_record(employee_id: int, target_date: str, check_in_time: str,
                          status: str = "on_time", late_minutes: int = 0,
                          check_in_video_id: str = None, check_out_time: str = None) -> bool:
    """Sheets dan qayta tiklash uchun — to'g'ridan-to'g'ri attendance yozuvini qo'shadi."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO attendance (employee_id, date, check_in_time, check_out_time,
                                    check_in_video_id, status, late_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(employee_id, date) DO UPDATE SET
                check_in_time = excluded.check_in_time,
                check_out_time = excluded.check_out_time,
                check_in_video_id = excluded.check_in_video_id,
                status = excluded.status,
                late_minutes = excluded.late_minutes
        """, (employee_id, target_date, check_in_time, check_out_time,
              check_in_video_id, status, late_minutes))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] add_attendance_record error: {e}")
        return False
    finally:
        conn.close()


def update_employee_work_time(employee_id: int, field: str, time_str: str) -> bool:
    """Xodimning custom_work_start yoki custom_work_end ni doimiy o'zgartirish.
    field: 'checkin' -> custom_work_start, 'checkout' -> custom_work_end
    Agar time_str='clear' bo'lsa, custom qiymatni o'chirib, default shift ga qaytaradi.
    """
    column = "custom_work_start" if field == "checkin" else "custom_work_end"
    conn = get_conn()
    try:
        if time_str == "clear":
            conn.execute(
                f"UPDATE employees SET {column} = NULL WHERE telegram_id = ?",
                (employee_id,)
            )
        else:
            conn.execute(
                f"UPDATE employees SET {column} = ? WHERE telegram_id = ?",
                (time_str, employee_id)
            )
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] update_employee_work_time error: {e}")
        return False
    finally:
        conn.close()


# ── Attendance CRUD ──

GRACE_MINUTES = 5  # 5 daqiqa kechikishga ruxsat (hali on_time)
TOO_LATE_MINUTES = 60  # 60 daqiqadan keyin umuman qabul qilinmaydi

MAX_EARLY_MINUTES = 20  # Smena boshlanishidan necha daqiqa oldin ruxsat


def validate_checkin_time(emp: dict) -> dict | None:
    """Check-in vaqtini tekshiradi. Agar ruxsat bo'lmasa None qaytaradi.
    Qaytarsa: {"valid": True, "late_minutes": N, "status": "on_time"|"late"}
    """
    from config import SHIFTS
    now = datetime.now(tz)
    total_now = now.hour * 60 + now.minute

    # Custom work start mavjudmi?
    if emp.get("custom_work_start"):
        parts = emp["custom_work_start"].split(":")
        start_hour = int(parts[0])
        start_min = int(parts[1])
        total_start = start_hour * 60 + start_min
    else:
        shift_cfg = SHIFTS.get(emp["shift"])
        if not shift_cfg:
            return {"valid": True, "late_minutes": 0, "status": "on_time"}
        start_hour = shift_cfg["start"]
        total_start = start_hour * 60

    # Juda erta — ruxsat yo'q
    if total_now < total_start - MAX_EARLY_MINUTES:
        return None

    # Juda kech — ruxsat yo'q
    if total_now > total_start + TOO_LATE_MINUTES:
        return None

    # Kechikishni hisoblash
    if total_now > total_start + GRACE_MINUTES:
        late_minutes = total_now - total_start
        return {"valid": True, "late_minutes": late_minutes, "status": "late"}
    else:
        return {"valid": True, "late_minutes": 0, "status": "on_time"}


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

        validation = validate_checkin_time(emp)
        if not validation:
            conn.close()
            return None

        late_minutes = validation["late_minutes"]
        status = validation["status"]

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


# ── Ish vaqtini tahrirlash ──

def get_attendance_record(employee_id: int, target_date: str = None) -> dict | None:
    """Bir xodimning berilgan sanadagi attendance yozuvini qaytaradi."""
    if target_date is None:
        target_date = datetime.now(tz).strftime("%Y-%m-%d")

    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM attendance WHERE employee_id = ? AND date = ?",
        (employee_id, target_date)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_attendance_time(employee_id: int, date: str, field: str, time_str: str) -> bool:
    """Check-in yoki check-out vaqtini yangilash.
    field: 'check_in' yoki 'check_out'
    Agar yozuv mavjud bo'lmasa — insert, bo'lsa — update.
    """
    conn = get_conn()
    try:
        # Avval mavjud yozuvni tekshiramiz
        existing = conn.execute(
            "SELECT id FROM attendance WHERE employee_id = ? AND date = ?",
            (employee_id, date)
        ).fetchone()

        if existing:
            # Update
            conn.execute(
                f"UPDATE attendance SET {field}_time = ? WHERE employee_id = ? AND date = ?",
                (time_str, employee_id, date)
            )
        else:
            # Insert — agar check_in o'rnatilayotgan bo'lsa, status ni on_time qilamiz
            status = "on_time" if field == "check_in" else "absent"
            late_min = 0
            conn.execute("""
                INSERT INTO attendance (employee_id, date, check_in_time, check_out_time, status, late_minutes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                employee_id, date,
                time_str if field == "check_in" else None,
                time_str if field == "check_out" else None,
                status,
                late_min,
            ))

        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] update_attendance_time error: {e}")
        return False
    finally:
        conn.close()


def _update_status(employee_id: int, date: str, status: str, late_minutes: int):
    """Attendance status ni yangilash (kichik helper)."""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE attendance SET status = ?, late_minutes = ? WHERE employee_id = ? AND date = ?",
            (status, late_minutes, employee_id, date)
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] _update_status error: {e}")
    finally:
        conn.close()


def set_late_reason(employee_id: int, date_str: str, reason: str) -> bool:
    """Kechikkan xodimning sababini saqlash."""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE attendance SET late_reason = ? WHERE employee_id = ? AND date = ?",
            (reason, employee_id, date_str)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] set_late_reason error: {e}")
        return False
    finally:
        conn.close()


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

    branches = _resolve_academic_branches(branch)
    placeholders = ",".join("?" for _ in branches)

    conn = get_conn()
    rows = conn.execute(f"""
        SELECT a.*, e.name, e.role, e.branch, e.shift
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE e.branch IN ({placeholders}) AND a.date = ?
        ORDER BY e.shift, e.name
    """, (*branches, target_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_branch_attendance_range(branch: str, start_date: str, end_date: str) -> list[dict]:
    """Bir filial oralig'idagi hisoboti."""
    branches = _resolve_academic_branches(branch)
    placeholders = ",".join("?" for _ in branches)

    conn = get_conn()
    rows = conn.execute(f"""
        SELECT a.*, e.name, e.role, e.branch, e.shift
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE e.branch IN ({placeholders}) AND a.date >= ? AND a.date <= ?
        ORDER BY a.date DESC, e.shift, e.name
    """, (*branches, start_date, end_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_missing_today(shift: str = None) -> list[dict]:
    """Bugun hali kelmagan xodimlar."""
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = get_conn()

    # Coordinatorlarni kelmaganlar ro'yxatidan chiqarish
    coordinator_filter = "AND e.role NOT IN ('coordinator', 'academic_support_coordinator')"

    if shift:
        # custom_work_start ni ham hisobga olish:
        # morning: shift="morning" YOKI custom_work_start < "12:00"
        # afternoon: shift="afternoon" YOKI custom_work_start >= "12:00" (lekin afternoon_alt emas)
        # afternoon_alt: shift="afternoon_alt"
        if shift == "morning":
            query = f"""
                SELECT e.telegram_id, e.name, e.role, e.branch, e.shift,
                       e.custom_work_start, e.custom_work_end
                FROM employees e
                LEFT JOIN attendance a ON e.telegram_id = a.employee_id AND a.date = ?
                WHERE e.active = 1 AND a.id IS NULL
                  {coordinator_filter}
                  AND (e.shift = ?
                       OR (e.custom_work_start IS NOT NULL AND e.custom_work_start < '12:00'))
            """
        elif shift == "afternoon_alt":
            query = f"""
                SELECT e.telegram_id, e.name, e.role, e.branch, e.shift,
                       e.custom_work_start, e.custom_work_end
                FROM employees e
                LEFT JOIN attendance a ON e.telegram_id = a.employee_id AND a.date = ?
                WHERE e.active = 1 AND a.id IS NULL
                  {coordinator_filter}
                  AND (e.shift = ?
                       OR (e.custom_work_start IS NOT NULL AND e.custom_work_start >= '12:00'
                           AND e.custom_work_start < '14:00'))
            """
        else:  # afternoon
            query = f"""
                SELECT e.telegram_id, e.name, e.role, e.branch, e.shift,
                       e.custom_work_start, e.custom_work_end
                FROM employees e
                LEFT JOIN attendance a ON e.telegram_id = a.employee_id AND a.date = ?
                WHERE e.active = 1 AND a.id IS NULL
                  {coordinator_filter}
                  AND (e.shift = ?
                       OR (e.custom_work_start IS NOT NULL AND e.custom_work_start >= '14:00'))
            """
        rows = conn.execute(query, (today_str, shift)).fetchall()
    else:
        query = f"""
            SELECT e.telegram_id, e.name, e.role, e.branch, e.shift,
                   e.custom_work_start, e.custom_work_end
            FROM employees e
            LEFT JOIN attendance a ON e.telegram_id = a.employee_id AND a.date = ?
            WHERE e.active = 1 AND a.id IS NULL
              {coordinator_filter}
        """
        rows = conn.execute(query, (today_str,)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


from datetime import timedelta
