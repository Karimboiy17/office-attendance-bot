"""Office Attendance Bot — Hisobot Formatlash"""

from config import BRANCHES, ROLE_LABELS, SHIFTS
import db


def _format_status(record: dict) -> str:
    """Bir attendance yozuvini bir qator formatda chiqarish."""
    status_map = {
        "on_time": "✅",
        "late": "⚠️",
        "absent": "❌",
    }
    icon = status_map.get(record["status"], "❓")
    name = record.get("name", str(record["employee_id"]))
    branch = BRANCHES.get(record.get("branch", ""), record.get("branch", ""))
    check_in = record.get("check_in_time", "")[:5] if record.get("check_in_time") else "—"
    role = ROLE_LABELS.get(record.get("role", ""), record.get("role", ""))

    line = f"{icon} {name} ({branch}) {role} — {check_in}"

    if record["status"] == "late" and record.get("late_minutes", 0) > 0:
        line += f" (⏰ {record['late_minutes']} min kech)"
    elif record["status"] == "absent":
        line += " (❌ kelmadi)"

    # check-out ham bo'lsa
    if record.get("check_out_time"):
        line += f" → {record['check_out_time'][:5]}"

    return line


def _format_missing(emp: dict) -> str:
    """Kelmagan xodim qatori."""
    name = emp["name"]
    branch = BRANCHES.get(emp["branch"], emp["branch"])
    role = ROLE_LABELS.get(emp["role"], emp["role"])
    # custom_work_start/end bor bo'lsa, shift label o'rniga shuni ko'rsat
    if emp.get("custom_work_start"):
        shift = f"Custom ({emp['custom_work_start']}-{emp.get('custom_work_end', '?')})"
    else:
        shift = SHIFTS.get(emp["shift"], {}).get("label", emp["shift"])
    return f"❌ {name} ({branch}) {role} · {shift}"


def format_today_report(shift: str = None) -> str:
    """Bugungi hisobot."""
    from datetime import datetime
    import pytz
    from config import TIMEZONE

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")

    # Hafta kunlari
    days_uz = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
    day_name = days_uz[now.weekday()]

    records = db.get_today_attendance()

    # Kelmaganlarni topish
    if shift:
        missing = db.get_missing_today(shift)
    else:
        missing = db.get_missing_today()

    lines = [f"📅 {today_str}, {day_name}"]
    lines.append("━" * 30)

    if not records and not missing:
        lines.append("Hech qanday yozuv yo'q.")
        return "\n".join(lines)

    if records:
        # Shift bo'yicha guruhlash
        if shift:
            lines.append(f"⏰ {SHIFTS.get(shift, {}).get('label', shift)} smenasi:")
            for r in records:
                lines.append(_format_status(r))
        else:
            for shift_key in ["morning", "afternoon", "afternoon_alt"]:
                shift_records = [r for r in records if r.get("shift") == shift_key]
                if shift_records:
                    lines.append(f"⏰ {SHIFTS[shift_key]['label']}:")
                    for r in shift_records:
                        lines.append(_format_status(r))
                    lines.append("")

    if missing:
        lines.append("━" * 30)
        lines.append("❌ Hali kelmaganlar:")
        for m in missing:
            lines.append(_format_missing(m))

    lines.append("━" * 30)
    total_employees = len(db.get_all_employees())
    present = len(records)
    lines.append(f"Jami: {present}/{total_employees} keldi")

    return "\n".join(lines)


def format_employee_report(employee_id: int) -> str:
    """Bir xodim tarixi."""
    emp = db.get_employee(employee_id)
    if not emp:
        return "❌ Xodim topilmadi."

    history = db.get_employee_history(employee_id, limit=14)

    lines = [f"👤 {emp['name']}"]
    lines.append(f"📍 {BRANCHES.get(emp['branch'], emp['branch'])} | {ROLE_LABELS.get(emp['role'], emp['role'])}")
    lines.append(f"🕐 {SHIFTS.get(emp['shift'], {}).get('label', emp['shift'])}")
    lines.append("━" * 30)

    if not history:
        lines.append("Hali hech qanday yozuv yo'q.")
    else:
        for r in history:
            lines.append(_format_status(r))

    return "\n".join(lines)


def format_branch_report(branch: str, shift: str = None, date_str: str = None) -> str:
    """Bir filial hisoboti (bugungi yoki berilgan sana)."""
    branch_label = BRANCHES.get(branch, branch)

    if date_str:
        records = db.get_branch_attendance(branch, date_str)
        lines = [f"🏢 {branch_label} — {date_str} hisobot"]
    else:
        records = db.get_branch_attendance(branch)
        lines = [f"🏢 {branch_label} — Bugungi hisobot"]

    lines.append("━" * 30)

    if not records:
        lines.append("Hech qanday yozuv yo'q.")
        return "\n".join(lines)

    if shift:
        records = [r for r in records if r.get("shift") == shift]

    for r in records:
        lines.append(_format_status(r))

    return "\n".join(lines)


def format_branch_week_report(branch: str) -> str:
    """Bir filial haftalik hisoboti."""
    from datetime import datetime, timedelta
    import pytz
    from config import TIMEZONE

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    monday = now.date() - timedelta(days=now.weekday())
    saturday = monday + timedelta(days=5)

    branch_label = BRANCHES.get(branch, branch)
    records = db.get_branch_attendance_range(branch, monday.strftime("%Y-%m-%d"), saturday.strftime("%Y-%m-%d"))

    lines = [f"📅 Haftalik hisobot — {branch_label}: {monday} → {saturday}"]
    lines.append("━" * 30)

    if not records:
        lines.append("Hech qanday yozuv yo'q.")
        return "\n".join(lines)

    by_date = {}
    for r in records:
        d = r["date"]
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(r)

    for date_str in sorted(by_date.keys()):
        lines.append(f"\n📌 {date_str}:")
        for r in by_date[date_str]:
            lines.append(_format_status(r))

    late_count = len([r for r in records if r["status"] == "late"])
    absent_count = len([r for r in records if r["status"] == "absent"])
    on_time_count = len([r for r in records if r["status"] == "on_time"])

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"✅ O'z vaqtinda: {on_time_count}")
    lines.append(f"⚠️ Kechikdi: {late_count}")
    lines.append(f"❌ Kelmadi: {absent_count}")

    return "\n".join(lines)


def format_branch_month_report(branch: str, year: int = None, month: int = None) -> str:
    """Bir filial oylik hisoboti."""
    from datetime import datetime
    import pytz
    from config import TIMEZONE

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    months_uz = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
                 "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"]

    branch_label = BRANCHES.get(branch, branch)
    start = f"{year}-{month:02d}-01"
    if month == 12:
        end = f"{year}-12-31"
    else:
        end = f"{year}-{month+1:02d}-01"

    records = db.get_branch_attendance_range(branch, start, end)

    lines = [f"📅 Oylik hisobot — {branch_label}: {months_uz[month]} {year}"]
    lines.append("━" * 30)

    if not records:
        lines.append("Hech qanday yozuv yo'q.")
        return "\n".join(lines)

    by_employee = {}
    for r in records:
        eid = r["employee_id"]
        if eid not in by_employee:
            by_employee[eid] = {
                "name": r.get("name", str(eid)),
                "total": 0, "on_time": 0, "late": 0, "absent": 0,
                "total_late_minutes": 0,
            }
        stats = by_employee[eid]
        stats["total"] += 1
        if r["status"] == "on_time":
            stats["on_time"] += 1
        elif r["status"] == "late":
            stats["late"] += 1
            stats["total_late_minutes"] += r.get("late_minutes", 0)
        elif r["status"] == "absent":
            stats["absent"] += 1

    for eid, stats in sorted(by_employee.items(), key=lambda x: x[1]["name"]):
        lines.append(f"\n👤 {stats['name']}:")
        lines.append(f"   ✅ O'z vaqtinda: {stats['on_time']}")
        lines.append(f"   ⚠️ Kechikdi: {stats['late']}")
        if stats["late"] > 0:
            lines.append(f"   ⏰ Jami kechikish: {stats['total_late_minutes']} min")
        lines.append(f"   ❌ Kelmadi: {stats['absent']}")

    total = len(records)
    late = len([r for r in records if r["status"] == "late"])
    absent = len([r for r in records if r["status"] == "absent"])
    on_time = len([r for r in records if r["status"] == "on_time"])

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 Umumiy: {total} ta kun")
    lines.append(f"✅ O'z vaqtinda: {on_time} ({on_time*100//total if total else 0}%)")
    lines.append(f"⚠️ Kechikdi: {late} ({late*100//total if total else 0}%)")
    lines.append(f"❌ Kelmadi: {absent} ({absent*100//total if total else 0}%)")

    return "\n".join(lines)


def format_branch_late_report(branch: str) -> str:
    """Bir filial kechikkanlar hisoboti (shu hafta)."""
    from datetime import datetime, timedelta
    import pytz
    from config import TIMEZONE

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    monday = now.date() - timedelta(days=now.weekday())
    saturday = monday + timedelta(days=5)

    branch_label = BRANCHES.get(branch, branch)
    records = db.get_branch_attendance_range(branch, monday.strftime("%Y-%m-%d"), saturday.strftime("%Y-%m-%d"))
    records = [r for r in records if r["status"] == "late"]

    lines = [f"⚠️ Kechikkanlar — {branch_label} (shu hafta)"]
    lines.append("━" * 30)

    if not records:
        lines.append("Kechikishlar yo'q! 🎉")
        return "\n".join(lines)

    for r in records:
        lines.append(_format_status(r))

    lines.append("━" * 30)
    lines.append(f"Jami: {len(records)} ta kechikish")
    return "\n".join(lines)


def format_branch_missing_report(branch: str, shift: str) -> str:
    """Bir filial kelmaganlar hisoboti."""
    employees = db.get_employees_by_branch(branch)
    shift_label = SHIFTS.get(shift, {}).get("label", shift)
    branch_label = BRANCHES.get(branch, branch)

    lines = [f"❌ {branch_label} — {shift_label}: Hali kelmaganlar"]
    lines.append("━" * 30)

    shift_emps = [e for e in employees if e["shift"] == shift]
    missing = []
    for emp in shift_emps:
        if not db.is_checked_in(emp["telegram_id"]):
            missing.append(emp)

    if not missing:
        lines.append("Hamma keldi! ✅")
    else:
        for m in missing:
            lines.append(_format_missing(m))

    return "\n".join(lines)


def format_date_report(date_str: str) -> str:
    """Berilgan sana hisoboti."""
    records = db.get_date_attendance(date_str)

    lines = [f"📅 {date_str}"]
    lines.append("━" * 30)

    if not records:
        lines.append("Hech qanday yozuv yo'q.")
        return "\n".join(lines)

    for shift_key in ["morning", "afternoon", "afternoon_alt"]:
        shift_records = [r for r in records if r.get("shift") == shift_key]
        if shift_records:
            lines.append(f"⏰ {SHIFTS[shift_key]['label']}:")
            for r in shift_records:
                lines.append(_format_status(r))
            lines.append("")

    return "\n".join(lines)


def format_week_report() -> str:
    """Haftalik hisobot."""
    from datetime import datetime, timedelta
    import pytz
    from config import TIMEZONE

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    monday = now.date() - timedelta(days=now.weekday())
    saturday = monday + timedelta(days=5)

    records = db.get_week_attendance()

    lines = [f"📅 Haftalik hisobot: {monday} → {saturday}"]
    lines.append("━" * 30)

    if not records:
        lines.append("Hech qanday yozuv yo'q.")
        return "\n".join(lines)

    # Sana bo'yicha guruhlash
    by_date = {}
    for r in records:
        d = r["date"]
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(r)

    for date_str in sorted(by_date.keys()):
        lines.append(f"\n📌 {date_str}:")
        for r in by_date[date_str]:
            lines.append(_format_status(r))

    # Statistika: kechikishlar
    late_count = len([r for r in records if r["status"] == "late"])
    absent_count = len([r for r in records if r["status"] == "absent"])
    on_time_count = len([r for r in records if r["status"] == "on_time"])

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"✅ O'z vaqtida: {on_time_count}")
    lines.append(f"⚠️ Kechikdi: {late_count}")
    lines.append(f"❌ Kelmadi: {absent_count}")

    return "\n".join(lines)


def format_month_report(year: int = None, month: int = None) -> str:
    """Oylik hisobot."""
    from datetime import datetime
    import pytz
    from config import TIMEZONE

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    months_uz = [
        "", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
        "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"
    ]

    records = db.get_month_attendance(year, month)

    lines = [f"📅 Oylik hisobot: {months_uz[month]} {year}"]
    lines.append("━" * 30)

    if not records:
        lines.append("Hech qanday yozuv yo'q.")
        return "\n".join(lines)

    # Har bir xodim bo'yicha statistika
    by_employee = {}
    for r in records:
        eid = r["employee_id"]
        if eid not in by_employee:
            by_employee[eid] = {
                "name": r.get("name", str(eid)),
                "branch": r.get("branch", ""),
                "total": 0,
                "on_time": 0,
                "late": 0,
                "absent": 0,
                "total_late_minutes": 0,
            }
        stats = by_employee[eid]
        stats["total"] += 1
        if r["status"] == "on_time":
            stats["on_time"] += 1
        elif r["status"] == "late":
            stats["late"] += 1
            stats["total_late_minutes"] += r.get("late_minutes", 0)
        elif r["status"] == "absent":
            stats["absent"] += 1

    for eid, stats in sorted(by_employee.items(), key=lambda x: x[1]["name"]):
        branch = BRANCHES.get(stats["branch"], stats["branch"])
        lines.append(f"\n👤 {stats['name']} ({branch}):")
        lines.append(f"   ✅ O'z vaqtida: {stats['on_time']}")
        lines.append(f"   ⚠️ Kechikdi: {stats['late']}")
        if stats["late"] > 0:
            lines.append(f"   ⏰ Jami kechikish: {stats['total_late_minutes']} min")
        lines.append(f"   ❌ Kelmadi: {stats['absent']}")

    # Umumiy statistika
    total = len(records)
    late = len([r for r in records if r["status"] == "late"])
    absent = len([r for r in records if r["status"] == "absent"])
    on_time = len([r for r in records if r["status"] == "on_time"])

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 Umumiy: {total} ta kun")
    lines.append(f"✅ O'z vaqtida: {on_time} ({on_time*100//total if total else 0}%)")
    lines.append(f"⚠️ Kechikdi: {late} ({late*100//total if total else 0}%)")
    lines.append(f"❌ Kelmadi: {absent} ({absent*100//total if total else 0}%)")

    return "\n".join(lines)


def format_late_report() -> str:
    """Kechikkanlar hisoboti (shu hafta)."""
    from datetime import datetime, timedelta
    import pytz
    from config import TIMEZONE

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    monday = now.date() - timedelta(days=now.weekday())
    saturday = monday + timedelta(days=5)

    records = db.get_late_attendance(
        monday.strftime("%Y-%m-%d"),
        saturday.strftime("%Y-%m-%d")
    )

    lines = [f"⚠️ Kechikkanlar — Shu hafta"]
    lines.append("━" * 30)

    if not records:
        lines.append("Kechikishlar yo'q! 🎉")
        return "\n".join(lines)

    for r in records:
        lines.append(_format_status(r))

    lines.append("━" * 30)
    lines.append(f"Jami: {len(records)} ta kechikish")

    return "\n".join(lines)


def format_missing_report(shift: str) -> str:
    """Kelmaganlar hisoboti (hozirgi holat)."""
    missing = db.get_missing_today(shift)
    shift_label = SHIFTS.get(shift, {}).get("label", shift)

    lines = [f"❌ {shift_label} — Hali kelmaganlar"]
    lines.append("━" * 30)

    if not missing:
        lines.append("Hamma keldi! ✅")
    else:
        for m in missing:
            lines.append(_format_missing(m))

    return "\n".join(lines)
