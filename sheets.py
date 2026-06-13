"""Office Attendance Bot — Google Sheets Backup"""

import base64
import json
import os
from google.oauth2.service_account import Credentials
import gspread
from config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SERVICE_ACCOUNT_B64, SHEET_KEY

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_client = None


def _parse_service_account(raw: str) -> dict | None:
    """JSON ni turli formatlarda parse qilish (Railway da \\n muammosini hal qiladi)."""
    # 1) To'g'ri JSON
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2) \\n ni haqiqiy newline ga almashtirish
    try:
        fixed = raw.replace("\\n", "\n")
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 3) Haqiqiy newline larni olib tashlash
    try:
        fixed = raw.replace("\n", "").replace("\r", "")
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 4) private_key dagi \\n ni newline ga almashtirib, qolganini tekislash
    try:
        import re
        fixed = re.sub(
            r'("private_key"\s*:\s*")(.*?)(")',
            lambda m: m.group(1) + m.group(2).replace("\\n", "\n").replace("\n", "\\n") + m.group(3),
            raw,
            flags=re.DOTALL,
        )
        return json.loads(fixed)
    except (json.JSONDecodeError, Exception):
        pass

    return None


def _try_auth(creds_dict: dict) -> bool:
    """Berilgan credential dict bilan auth qilish."""
    try:
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        global _client
        _client = gspread.authorize(creds)
        return True
    except Exception as e:
        print(f"[Sheets] Auth xatolik: {e}")
        return False


def _get_client():
    global _client
    if _client is not None:
        return _client

    # 1) Base64 (agar qo'llanilsa)
    if GOOGLE_SERVICE_ACCOUNT_B64:
        try:
            raw = base64.b64decode(GOOGLE_SERVICE_ACCOUNT_B64).decode("utf-8")
            creds_dict = json.loads(raw)
            if _try_auth(creds_dict):
                return _client
        except Exception as e:
            print(f"[Sheets] Base64 decode xatolik: {e}")

    # 2) JSON — bir necha formatda urinib ko'rish
    if GOOGLE_SERVICE_ACCOUNT_JSON:
        creds_dict = _parse_service_account(GOOGLE_SERVICE_ACCOUNT_JSON)
        if creds_dict and _try_auth(creds_dict):
            return _client

    print("[Sheets] Google Sheets auth muvaffaqiyatsiz. Configuratsiyani tekshiring.")
    return None


def _get_sheet():
    client = _get_client()
    if not client:
        return None
    try:
        return client.open_by_key(SHEET_KEY)
    except Exception as e:
        print(f"[Sheets] Sheet ochish xatolik: {e}")
        return None


def _get_worksheet(sheet, name: str, headers: list[str]):
    """Worksheet ni olish yoki yaratish."""
    try:
        ws = sheet.worksheet(name)
        # Mavjud worksheet bo'lsa, headerlarni to'ldirish (agar kerak bo'lsa)
        existing_headers = ws.row_values(1)
        if len(existing_headers) < len(headers):
            new_headers = existing_headers + headers[len(existing_headers):]
            ws.update(f"A1:{chr(64+len(new_headers))}1", [new_headers])
            print(f"[Sheets] {name} headerlari yangilandi: {existing_headers} -> {new_headers}")
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=name, rows="1000", cols="20")
        if headers:
            ws.append_row(headers)
    return ws


def _sanitize_sheet_name(name: str) -> str:
    """Google Sheets worksheet nomi uchun tozalash (<=100 chars)."""
    # `/`, `\`, `?`, `*`, `[`, `]`, `:` qabul qilinmaydi
    sanitized = name.replace("/", "_").replace("\\", "_").replace("?", "")
    sanitized = sanitized.replace("*", "").replace("[", "").replace("]", "").replace(":", "")
    return sanitized[:100]


def sync_employee_to_sheets(employee: dict):
    """Bitta xodimni Sheets ga yozish — filiali bo'yicha alohida worksheet ga."""
    sheet = _get_sheet()
    if not sheet:
        return

    branch = employee.get("branch", "integro")
    sheet_name = _sanitize_sheet_name(f"Xodimlar_{branch}")

    ws = _get_worksheet(sheet, sheet_name, [
        "telegram_id", "name", "role", "branch", "shift", "active", "created_at",
        "custom_work_start", "custom_work_end",
    ])

    try:
        all_rows = ws.get_all_records()
    except Exception:
        all_rows = []

    found = False
    for i, row in enumerate(all_rows, start=2):
        if str(row.get("telegram_id", "")) == str(employee["telegram_id"]):
            ws.update(f"A{i}:I{i}", [[
                str(employee["telegram_id"]),
                employee["name"],
                employee.get("role", "office_manager"),
                employee.get("branch", "integro"),
                employee.get("shift", "morning"),
                str(employee.get("active", 1)),
                employee.get("created_at", ""),
                employee.get("custom_work_start", ""),
                employee.get("custom_work_end", ""),
            ]])
            found = True
            break

    if not found:
        ws.append_row([
            str(employee["telegram_id"]),
            employee["name"],
            employee.get("role", "office_manager"),
            employee.get("branch", "integro"),
            employee.get("shift", "morning"),
            str(employee.get("active", 1)),
            employee.get("created_at", ""),
            employee.get("custom_work_start", ""),
            employee.get("custom_work_end", ""),
        ])


def sync_custom_time_to_sheets(telegram_id: int, custom_work_start: str | None = None,
                               custom_work_end: str | None = None):
    """Xodimning custom ish vaqtini Google Sheets'ga yozish (faqat H va I column)."""
    from db import get_employee
    emp = get_employee(telegram_id)
    if not emp:
        return

    sheet = _get_sheet()
    if not sheet:
        return

    branch = emp.get("branch", "integro")
    sheet_name = _sanitize_sheet_name(f"Xodimlar_{branch}")

    try:
        ws = sheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        return

    try:
        all_rows = ws.get_all_records()
    except Exception:
        return

    for i, row in enumerate(all_rows, start=2):
        if str(row.get("telegram_id", "")) == str(telegram_id):
            start_val = custom_work_start if custom_work_start else ""
            end_val = custom_work_end if custom_work_end else ""
            ws.update(f"H{i}:I{i}", [[start_val, end_val]])
            print(f"[Sheets] Custom vaqt yangilandi: {telegram_id} -> {start_val} / {end_val}")
            return

    # Agar Sheets'da topilmasa, employee ma'lumotlari bilan qator qo'shamiz
    from datetime import datetime
    ws.append_row([
        str(telegram_id),
        emp["name"],
        emp.get("role", "office_manager"),
        emp.get("branch", "integro"),
        emp.get("shift", "morning"),
        str(emp.get("active", 1)),
        emp.get("created_at", datetime.now().isoformat()),
        custom_work_start or "",
        custom_work_end or "",
    ])

def sync_attendance_to_sheets(record: dict):
    """Bitta attendance yozuvini Sheets ga yozish — filiali bo'yicha alohida."""
    sheet = _get_sheet()
    if not sheet:
        return

    branch = record.get("branch", "integro")
    sheet_name = _sanitize_sheet_name(f"Davomat_{branch}")

    ws = _get_worksheet(sheet, sheet_name, [
        "employee_id", "date", "check_in_time", "check_out_time",
        "check_in_video_id", "check_out_video_id", "status", "late_minutes",
        "name", "role", "branch", "shift"
    ])

    try:
        ws.append_row([
            str(record.get("employee_id", "")),
            record.get("date", ""),
            record.get("check_in_time", ""),
            record.get("check_out_time", ""),
            record.get("check_in_video_id", ""),
            record.get("check_out_video_id", ""),
            record.get("status", ""),
            str(record.get("late_minutes", 0)),
            record.get("name", ""),
            record.get("role", ""),
            record.get("branch", ""),
            record.get("shift", ""),
        ])
    except Exception as e:
        print(f"[Sheets] sync_attendance xatolik ({sheet_name}): {e}")


def load_employees_from_sheets():
    """Sheets dan barcha xodimlarni yuklash (bot restart da) — barcha Xodimlar_* worksheet lardan."""
    from db import add_employee

    sheet = _get_sheet()
    if not sheet:
        return []

    employees = []

    # Eski "Employees" worksheet dan yuklash (backward compatibility)
    try:
        ws = sheet.worksheet("Employees")
        rows = ws.get_all_records()
        for row in rows:
            try:
                tid = int(row["telegram_id"])
                name = row["name"]
                role = row.get("role", "office_manager")
                branch = row.get("branch", "integro")
                shift = row.get("shift", "morning")
                active = int(row.get("active", 1))
                if active:
                    cws = row.get("custom_work_start", "") or None
                    cwe = row.get("custom_work_end", "") or None
                    add_employee(tid, name, role, branch, shift, cws, cwe)
                    employees.append({"telegram_id": tid, "name": name, "role": role, "branch": branch, "shift": shift, "custom_work_start": cws, "custom_work_end": cwe})
            except (ValueError, KeyError) as e:
                print(f"[Sheets] Employees qator xatolik: {e}")
    except gspread.exceptions.WorksheetNotFound:
        pass
    except Exception as e:
        print(f"[Sheets] Employees worksheet o'qish xatolik: {e}")

    # Yangi format: Xodimlar_Integro, Xodimlar_Amir Temur, ...
    for ws in sheet.worksheets():
        title = ws.title
        if title.startswith("Xodimlar_"):
            try:
                rows = ws.get_all_records()
                for row in rows:
                    try:
                        tid = int(row["telegram_id"])
                        name = row["name"]
                        role = row.get("role", "office_manager")
                        branch = row.get("branch", "integro")
                        shift = row.get("shift", "morning")
                        active = int(row.get("active", 1))
                        if active:
                            cws = row.get("custom_work_start", "") or None
                            cwe = row.get("custom_work_end", "") or None
                            add_employee(tid, name, role, branch, shift, cws, cwe)
                            employees.append({"telegram_id": tid, "name": name, "role": role, "branch": branch, "shift": shift, "custom_work_start": cws, "custom_work_end": cwe})
                    except (ValueError, KeyError) as e:
                        print(f"[Sheets] {title} qator xatolik: {e}")
            except Exception as e:
                print(f"[Sheets] {title} o'qish xatolik: {e}")

    return employees


def sync_deletions_from_sheets():
    """Sheets dan o'chirilgan xodimlarni DB dan o'chirish (bot restart da)."""
    from db import get_all_employees, remove_employee

    sheet = _get_sheet()
    if not sheet:
        print("[Sheets] sync_deletions: sheet ochilmadi, o'tkazib yuborildi.")
        return

    # Sheets dan barcha telegram_id larni yig'ish
    sheet_ids = set()
    for ws in sheet.worksheets():
        title = ws.title
        if title.startswith("Xodimlar_") or title == "Employees":
            try:
                rows = ws.get_all_records()
                for row in rows:
                    try:
                        active = int(row.get("active", 1))
                        if active:
                            sheet_ids.add(int(row["telegram_id"]))
                    except (ValueError, KeyError):
                        pass
            except Exception as e:
                print(f"[Sheets] {title} o'qish xatolik: {e}")

    # DB dagi xodimlar bilan solishtirish
    db_employees = get_all_employees()
    for emp in db_employees:
        tid = emp["telegram_id"]
        if tid not in sheet_ids:
            print(f"[Sheets] Xodim Sheets da yo'q, DB dan o'chirish: {emp['name']} ({tid})")
            remove_employee(tid)
