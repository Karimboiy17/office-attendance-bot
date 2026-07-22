"""Office Manager Bot — SQLite Database"""

import os
import sqlite3
from datetime import datetime, date, timedelta
from config import TIMEZONE
import pytz

# Agar RAILWAY env vars bo'lsa — volume mount point ga yozamiz
VOLUME_PATH = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "")
DB_PATH = os.path.join(VOLUME_PATH, "attendance.db") if VOLUME_PATH else "attendance.db"

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
            late_reason TEXT,
            FOREIGN KEY (employee_id) REFERENCES employees(telegram_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_unique
            ON attendance(employee_id, date);

        CREATE INDEX IF NOT EXISTS idx_attendance_date
            ON attendance(date);

        -- Xodimning kunlik tasklari (shablon)
        CREATE TABLE IF NOT EXISTS employee_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            time_slot TEXT NOT NULL,
            task_text TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (employee_id) REFERENCES employees(telegram_id)
        );

        -- Task bajarilganligi (kundalik)
        CREATE TABLE IF NOT EXISTS task_completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            task_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            FOREIGN KEY (employee_id) REFERENCES employees(telegram_id),
            FOREIGN KEY (task_id) REFERENCES employee_tasks(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_task_unique
            ON task_completions(employee_id, task_id, date);
    """)

    # Migration: custom work times
    for col in ["custom_work_start", "custom_work_end"]:
        try:
            conn.execute(f"ALTER TABLE employees ADD COLUMN {col} TEXT")
        except Exception:
            pass

    conn.commit()
    conn.close()

    init_settings()


# ══════════════════════════════════════
#  BOT SETTINGS (Ish vaqti va boshqa sozlamalar)
# ══════════════════════════════════════

def init_settings():
    """Settings jadvalini yaratish va default qiymatlarni o'rnatish"""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    # Default shift vaqtlarini o'rnatish (agar mavjud bo'lmasa)
    defaults = {
        "shift_morning_start": "8",
        "shift_morning_end": "15",
        "shift_evening_start": "14",
        "shift_evening_end": "1",
        "checkin_deadline_minutes": "5",
        "work_days": "0,1,2,3,4,5",
    }
    for k, v in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)",
            (k, v)
        )
    conn.commit()
    conn.close()


def get_setting(key: str, default: str = None) -> str | None:
    """Bot sozlamasini olish"""
    conn = get_conn()
    row = conn.execute(
        "SELECT value FROM bot_settings WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> bool:
    """Bot sozlamasini saqlash"""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] set_setting error: {e}")
        return False
    finally:
        conn.close()


def get_custom_shift_times() -> dict:
    """Shifts vaqtlarini DB dan olish (global + branch-based)"""
    # Global (default) shift times
    morning_start = int(get_setting("shift_morning_start", "8"))
    morning_end = int(get_setting("shift_morning_end", "15"))
    evening_start = int(get_setting("shift_evening_start", "14"))
    evening_end = int(get_setting("shift_evening_end", "1"))
    # Online branch override
    online_morning_start = int(get_setting("online_morning_start", str(morning_start)))
    online_morning_end = int(get_setting("online_morning_end", str(morning_end)))
    online_evening_start = int(get_setting("online_evening_start", str(evening_start)))
    online_evening_end = int(get_setting("online_evening_end", str(evening_end)))
    deadline = int(get_setting("checkin_deadline_minutes", "5"))
    work_days_str = get_setting("work_days", "0,1,2,3,4,5")
    work_days = [int(x.strip()) for x in work_days_str.split(",") if x.strip().isdigit()]

    return {
        "default": {
            "morning": {"start": morning_start, "end": morning_end,
                         "label": f"Ertalab ({morning_start:02d}:00-{morning_end:02d}:00)"},
            "evening": {"start": evening_start, "end": evening_end,
                         "label": f"Kechki ({evening_start:02d}:00-{evening_end:02d}:00)"},
        },
        "online": {
            "morning": {"start": online_morning_start, "end": online_morning_end,
                         "label": f"Ertalab ({online_morning_start:02d}:00-{online_morning_end:02d}:00)"},
            "evening": {"start": online_evening_start, "end": online_evening_end,
                         "label": f"Kechki ({online_evening_start:02d}:00-{online_evening_end:02d}:00)"},
        },
        "checkin_deadline_minutes": deadline,
        "work_days": work_days,
    }


# ══════════════════════════════════════
#  EMPLOYEES
# ══════════════════════════════════════

def add_employee(telegram_id: int, name: str, role: str = "office_manager",
                 branch: str = "integro", shift: str = "morning") -> bool:
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT telegram_id FROM employees WHERE telegram_id = ?",
            (telegram_id,)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE employees
                SET name = ?, role = ?, branch = ?, shift = ?, active = 1
                WHERE telegram_id = ?
            """, (name, role, branch, shift, telegram_id))
        else:
            conn.execute("""
                INSERT INTO employees (telegram_id, name, role, branch, shift, active)
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


def update_employee_fields(telegram_id: int, **kwargs) -> bool:
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
        print(f"[DB] update error: {e}")
        return False
    finally:
        conn.close()


# ══════════════════════════════════════
#  ATTENDANCE
# ══════════════════════════════════════

def is_checked_in(employee_id: int) -> bool:
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = get_conn()
    row = conn.execute(
        "SELECT check_in_time FROM attendance WHERE employee_id = ? AND date = ?",
        (employee_id, today_str)
    ).fetchone()
    conn.close()
    return row is not None and row["check_in_time"] is not None


def is_checked_out(employee_id: int) -> bool:
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = get_conn()
    row = conn.execute(
        "SELECT check_out_time FROM attendance WHERE employee_id = ? AND date = ?",
        (employee_id, today_str)
    ).fetchone()
    conn.close()
    return row is not None and row["check_out_time"] is not None


def check_in(employee_id: int, video_id: str) -> dict | None:
    """Check-in qilish. Natija: {"status", "time", "late_minutes", "date"} yoki None."""
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    emp = get_employee(employee_id)
    if not emp:
        return None

    # DB dan sozlangan vaqtlarni olish
    custom = get_custom_shift_times()
    branch_key = "online" if emp.get("branch") == "online" else "default"
    shifts = custom[branch_key]
    deadline = custom["checkin_deadline_minutes"]

    # Kechikishni hisoblash
    shift = emp.get("shift", "morning")
    shift_cfg = shifts.get(shift, {"start": 8, "end": 15})
    start_hour = shift_cfg["start"]
    start_min = 0

    shift_start = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
    diff = (now - shift_start).total_seconds() / 60
    late_minutes = max(0, int(diff) - deadline) if diff > deadline else 0
    status = "on_time" if late_minutes == 0 else "late"

    conn = get_conn()
    try:
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
        return {"status": status, "time": time_str, "late_minutes": late_minutes, "date": today_str}
    except Exception as e:
        print(f"[DB] check_in error: {e}")
        return None
    finally:
        conn.close()


def check_out(employee_id: int, video_id: str) -> dict | None:
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    conn = get_conn()
    try:
        conn.execute("""
            UPDATE attendance
            SET check_out_time = ?, check_out_video_id = ?
            WHERE employee_id = ? AND date = ?
        """, (time_str, video_id, employee_id, today_str))
        conn.commit()
        return {"check_out_time": time_str, "date": today_str}
    except Exception as e:
        print(f"[DB] check_out error: {e}")
        return None
    finally:
        conn.close()


def get_today_attendance() -> list[dict]:
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.branch, e.shift, e.role
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE a.date = ? AND e.active = 1
        ORDER BY a.check_in_time
    """, (today_str,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_missing_today(shift: str = None) -> list[dict]:
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = get_conn()
    if shift:
        rows = conn.execute("""
            SELECT e.* FROM employees e
            WHERE e.active = 1 AND e.shift = ?
            AND e.telegram_id NOT IN (
                SELECT employee_id FROM attendance
                WHERE date = ? AND check_in_time IS NOT NULL
            )
            ORDER BY e.branch, e.name
        """, (shift, today_str)).fetchall()
    else:
        rows = conn.execute("""
            SELECT e.* FROM employees e
            WHERE e.active = 1
            AND e.telegram_id NOT IN (
                SELECT employee_id FROM attendance
                WHERE date = ? AND check_in_time IS NOT NULL
            )
            ORDER BY e.branch, e.name
        """, (today_str,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_employee_history(employee_id: int, limit: int = 14) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.branch, e.shift, e.role
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE a.employee_id = ?
        ORDER BY a.date DESC
        LIMIT ?
    """, (employee_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_branch_attendance(branch: str, date_str: str = None) -> list[dict]:
    if date_str is None:
        date_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.branch, e.shift, e.role
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE a.date = ? AND e.branch = ? AND e.active = 1
        ORDER BY a.check_in_time
    """, (date_str, branch)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_branch_attendance_range(branch: str, start_date: str, end_date: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.branch, e.shift, e.role
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE a.date >= ? AND a.date <= ? AND e.branch = ? AND e.active = 1
        ORDER BY a.date, a.check_in_time
    """, (start_date, end_date, branch)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_date_attendance(date_str: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.branch, e.shift, e.role
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE a.date = ? AND e.active = 1
        ORDER BY a.check_in_time
    """, (date_str,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_late_employees() -> list[dict]:
    """Oxirgi 7 kundagi kechikkan xodimlar."""
    week_ago = (datetime.now(tz) - timedelta(days=7)).strftime("%Y-%m-%d")
    conn = get_conn()
    rows = conn.execute("""
        SELECT a.*, e.name, e.branch, e.shift, e.role
        FROM attendance a
        JOIN employees e ON a.employee_id = e.telegram_id
        WHERE a.date >= ? AND a.status = 'late' AND e.active = 1
        ORDER BY a.date DESC, a.late_minutes DESC
    """, (week_ago,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_absent_employees(shift: str = None) -> list[dict]:
    """Bugungi kelmagan xodimlar."""
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = get_conn()
    if shift:
        rows = conn.execute("""
            SELECT e.* FROM employees e
            WHERE e.active = 1 AND e.shift = ?
            AND e.telegram_id NOT IN (
                SELECT employee_id FROM attendance
                WHERE date = ? AND check_in_time IS NOT NULL
            )
            ORDER BY e.branch, e.name
        """, (shift, today_str)).fetchall()
    else:
        rows = conn.execute("""
            SELECT e.* FROM employees e
            WHERE e.active = 1
            AND e.telegram_id NOT IN (
                SELECT employee_id FROM attendance
                WHERE date = ? AND check_in_time IS NOT NULL
            )
            ORDER BY e.branch, e.name
        """, (today_str,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════
#  TASKS
# ══════════════════════════════════════

def set_employee_tasks(employee_id: int, tasks: list[dict]) -> bool:
    """Xodimning task shablonini o'rnatish.
    tasks: [{"time": "08:00-09:00", "task": "...", "sort_order": 0}, ...]
    """
    conn = get_conn()
    try:
        # Eski tasklarni o'chirish
        conn.execute("DELETE FROM employee_tasks WHERE employee_id = ?", (employee_id,))
        # Yangi tasklarni qo'shish
        for i, t in enumerate(tasks):
            conn.execute("""
                INSERT INTO employee_tasks (employee_id, time_slot, task_text, sort_order)
                VALUES (?, ?, ?, ?)
            """, (employee_id, t["time"], t["task"], t.get("sort_order", i)))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] set_employee_tasks error: {e}")
        return False
    finally:
        conn.close()


def get_employee_tasks(employee_id: int) -> list[dict]:
    """Xodimning task shablonini olish."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM employee_tasks
        WHERE employee_id = ?
        ORDER BY sort_order
    """, (employee_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_today_tasks(employee_id: int) -> list[dict]:
    """Bugungi tasklarni completion statusi bilan qaytaradi."""
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = get_conn()
    rows = conn.execute("""
        SELECT t.id as task_id, t.time_slot, t.task_text, t.sort_order,
               COALESCE(tc.status, 'pending') as status,
               tc.completed_at, tc.id as completion_id
        FROM employee_tasks t
        LEFT JOIN task_completions tc
            ON tc.task_id = t.id AND tc.date = ? AND tc.employee_id = ?
        WHERE t.employee_id = ?
        ORDER BY t.sort_order
    """, (today_str, employee_id, employee_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def complete_task(employee_id: int, task_id: int) -> bool:
    """Taskni bajarildi deb belgilash."""
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    now_str = datetime.now(tz).strftime("%H:%M:%S")
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO task_completions (employee_id, task_id, date, completed_at, status)
            VALUES (?, ?, ?, ?, 'completed')
            ON CONFLICT(employee_id, task_id, date) DO UPDATE SET
                status = 'completed',
                completed_at = excluded.completed_at
        """, (employee_id, task_id, today_str, now_str))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] complete_task error: {e}")
        return False
    finally:
        conn.close()


def uncomplete_task(employee_id: int, task_id: int) -> bool:
    """Taskni bajarilmagan qaytarish."""
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO task_completions (employee_id, task_id, date, status)
            VALUES (?, ?, ?, 'pending')
            ON CONFLICT(employee_id, task_id, date) DO UPDATE SET
                status = 'pending',
                completed_at = NULL
        """, (employee_id, task_id, today_str))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] uncomplete_task error: {e}")
        return False
    finally:
        conn.close()


def get_task_completion_rate(employee_id: int, days: int = 7) -> dict:
    """Oxirgi N kundagi task bajarilish statistikasi."""
    start_date = (datetime.now(tz) - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_conn()
    try:
        # Jami tasklar soni (shablon bo'yicha)
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM employee_tasks WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()["cnt"]

        # Oxirgi N kunda bajarilgan tasklar
        completed = conn.execute("""
            SELECT COUNT(*) as cnt FROM task_completions tc
            JOIN employee_tasks t ON tc.task_id = t.id
            WHERE tc.employee_id = ? AND tc.date >= ? AND tc.status = 'completed'
        """, (employee_id, start_date)).fetchone()["cnt"]

        # Kunlik o'rtacha
        total_days = conn.execute("""
            SELECT COUNT(DISTINCT date) as cnt FROM task_completions
            WHERE employee_id = ? AND date >= ?
        """, (employee_id, start_date)).fetchone()["cnt"]

        conn.close()
        return {
            "total_tasks_per_day": total,
            "total_completed": completed,
            "active_days": total_days,
            "completion_rate": round((completed / (total * max(total_days, 1))) * 100, 1) if total > 0 else 0,
        }
    except Exception as e:
        conn.close()
        return {"total_tasks_per_day": 0, "total_completed": 0, "active_days": 0, "completion_rate": 0}


# ══════════════════════════════════════
#  TASK REMINDERS (persistent)
# ══════════════════════════════════════

def ensure_task_reminders_table():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS task_reminders (
        reminder_key TEXT PRIMARY KEY,
        sent_at REAL NOT NULL,
        updated_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.commit()
    conn.close()


def get_task_reminder(reminder_key: str) -> float:
    ensure_task_reminders_table()
    conn = get_conn()
    row = conn.execute(
        "SELECT sent_at FROM task_reminders WHERE reminder_key = ?",
        (reminder_key,)
    ).fetchone()
    conn.close()
    return row["sent_at"] if row else 0.0


def set_task_reminder(reminder_key: str, timestamp: float):
    ensure_task_reminders_table()
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO task_reminders (reminder_key, sent_at, updated_at) VALUES (?, ?, datetime('now'))",
        (reminder_key, timestamp)
    )
    conn.commit()
    conn.close()


# ══════════════════════════════════════
#  EMPLOYEE TASK EDITING (Coordinator)
# ══════════════════════════════════════

def update_employee_task(task_id: int, task_text: str, time_slot: str = None) -> bool:
    """Xodim taskini tahrirlash"""
    try:
        conn = get_conn()
        if time_slot:
            conn.execute(
                "UPDATE employee_tasks SET task_text = ?, time_slot = ? WHERE id = ?",
                (task_text, time_slot, task_id)
            )
        else:
            conn.execute(
                "UPDATE employee_tasks SET task_text = ? WHERE id = ?",
                (task_text, task_id)
            )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"update_employee_task error: {e}")
        return False


def get_employee_by_id(employee_id: int) -> dict | None:
    """Xodimni telegram_id bo'yicha olish"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM employees WHERE telegram_id = ?",
        (employee_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ══════════════════════════════════════
#  PENDING APPROVAL
# ══════════════════════════════════════

def register_pending_employee(telegram_id: int, name: str, role: str = "office_manager",
                               branch: str = "integro", shift: str = "morning") -> bool:
    """Self-registration — active=0, admin tasdiqlashi kerak"""
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT telegram_id FROM employees WHERE telegram_id = ?",
            (telegram_id,)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE employees
                SET name = ?, role = ?, branch = ?, shift = ?, active = 0
                WHERE telegram_id = ?
            """, (name, role, branch, shift, telegram_id))
        else:
            conn.execute("""
                INSERT INTO employees (telegram_id, name, role, branch, shift, active)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (telegram_id, name, role, branch, shift))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] register_pending_employee error: {e}")
        return False
    finally:
        conn.close()


def get_pending_employees() -> list[dict]:
    """Admin tasdiqlashni kutayotgan xodimlar"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM employees WHERE active = 0 ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_employee(telegram_id: int) -> bool:
    """Xodimni tasdiqlash (active=1)"""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE employees SET active = 1 WHERE telegram_id = ?",
            (telegram_id,)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] approve_employee error: {e}")
        return False
    finally:
        conn.close()


def reject_employee(telegram_id: int) -> bool:
    """Xodimni butunlay o'chirish (rad etish)"""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM employees WHERE telegram_id = ?", (telegram_id,))
        conn.execute("DELETE FROM employee_tasks WHERE employee_id = ?", (telegram_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] reject_employee error: {e}")
        return False
    finally:
        conn.close()
