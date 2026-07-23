"""Office Manager Bot — Google Sheets backup"""

import json
import base64
import os
from datetime import datetime
from config import TIMEZONE, GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SERVICE_ACCOUNT_B64, SHEET_KEY, BRANCHES
import pytz

tz = pytz.timezone(TIMEZONE)

# Google Sheets API (lazy import)
_gc = None


def get_client():
    global _gc
    if _gc is not None:
        return _gc
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

        creds = None
        if GOOGLE_SERVICE_ACCOUNT_JSON:
            if os.path.isfile(GOOGLE_SERVICE_ACCOUNT_JSON):
                creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_JSON, scopes=scope)
            else:
                # To'g'ridan-to'g'ri JSON matni
                creds = Credentials.from_service_account_info(json.loads(GOOGLE_SERVICE_ACCOUNT_JSON), scopes=scope)
        elif GOOGLE_SERVICE_ACCOUNT_B64:
            creds = Credentials.from_service_account_info(
                json.loads(base64.b64decode(GOOGLE_SERVICE_ACCOUNT_B64).decode()), scopes=scope
            )

        if not creds:
            print("[Sheets] Service account topilmadi, Sheets sync o'chirilgan.")
            return None

        _gc = gspread.authorize(creds)
        return _gc
    except Exception as e:
        print(f"[Sheets] get_client error: {e}")
        return None


def sync_attendance_to_sheets(data: dict):
    """Davomat ma'lumotini Google Sheets ga yozish"""
    client = get_client()
    if not client or not SHEET_KEY:
        return False
    try:
        sheet = client.open_by_key(SHEET_KEY)
        # Bugungi sana bo'yicha tab
        today_str = datetime.now(tz).strftime("%d.%m.%Y")
        try:
            ws = sheet.worksheet(today_str)
        except Exception:
            ws = sheet.add_worksheet(title=today_str, rows=100, cols=20)
            ws.append_row(["ID", "Ism", "Filial", "Rol", "Smena", "Check-in", "Check-out", "Holat", "Kechikish (daq)", "Sabab", "Video ID"])

        row = [
            data.get("employee_id", ""),
            data.get("name", ""),
            BRANCHES.get(data.get("branch", ""), data.get("branch", "")),
            data.get("role", ""),
            data.get("shift", ""),
            data.get("check_in_time", ""),
            data.get("check_out_time", ""),
            data.get("status", ""),
            data.get("late_minutes", ""),
            data.get("late_reason", ""),
            data.get("check_in_video_id", ""),
        ]
        ws.append_row(row)
        return True
    except Exception as e:
        print(f"[Sheets] sync error: {e}")
        return False


def sync_employee_to_sheets(emp: dict):
    """Xodim ma'lumotini Sheets ga yozish"""
    client = get_client()
    if not client or not SHEET_KEY:
        return False
    try:
        sheet = client.open_by_key(SHEET_KEY)
        try:
            ws = sheet.worksheet("Xodimlar")
        except Exception:
            ws = sheet.add_worksheet(title="Xodimlar", rows=100, cols=10)
            ws.append_row(["Telegram ID", "Ism", "Rol", "Filial", "Smena", "Qo'shilgan sana"])

        ws.append_row([
            emp["telegram_id"],
            emp["name"],
            emp.get("role", ""),
            BRANCHES.get(emp.get("branch", ""), emp.get("branch", "")),
            emp.get("shift", ""),
            datetime.now(tz).strftime("%Y-%m-%d %H:%M"),
        ])
        return True
    except Exception as e:
        print(f"[Sheets] sync_employee error: {e}")
        return False


def get_employees_from_sheets() -> list[dict]:
    """Xodimlar ro'yxatini Google Sheets dan o'qish"""
    client = get_client()
    if not client or not SHEET_KEY:
        return []
    try:
        sheet = client.open_by_key(SHEET_KEY)
        try:
            ws = sheet.worksheet("Xodimlar")
        except Exception:
            return []
        rows = ws.get_all_values()
        if len(rows) < 2:
            return []
        # First row = header
        employees = []
        for row in rows[1:]:
            if not row or not row[0] or not row[0].strip():
                continue
            try:
                emp = {
                    "telegram_id": int(row[0].strip()),
                    "name": row[1].strip() if len(row) > 1 else "",
                    "role": row[2].strip() if len(row) > 2 else "office_manager",
                    "branch": row[3].strip() if len(row) > 3 else "integro",
                    "shift": row[4].strip() if len(row) > 4 else "morning",
                }
                # Branch nomini kalitga o'tkazish
                for key, label in BRANCHES.items():
                    if label.lower() in emp["branch"].lower():
                        emp["branch"] = key
                        break
                employees.append(emp)
            except (ValueError, IndexError):
                continue
        return employees
    except Exception as e:
        print(f"[Sheets] get_employees error: {e}")
        return []
