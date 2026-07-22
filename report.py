"""Office Manager Bot — Hisobotlar"""

from datetime import datetime, timedelta, date
from config import TIMEZONE, BRANCHES, ROLE_LABELS, SHIFTS, WORK_DAYS
import pytz
import db

tz = pytz.timezone(TIMEZONE)
today_str = lambda: datetime.now(tz).strftime("%Y-%m-%d")


def _safe(val, default="—"):
    return val if val is not None else default


def _branch_label(branch_key):
    return BRANCHES.get(branch_key, branch_key.capitalize())


def format_employee_info(emp: dict) -> str:
    """Xodim ma'lumoti"""
    if not emp:
        return "❌ Xodim topilmadi."
    branch = _branch_label(emp.get("branch", ""))
    role = ROLE_LABELS.get(emp.get("role", ""), emp.get("role", ""))
    shift_label = SHIFTS.get(emp.get("shift", ""), {}).get("label", emp.get("shift", ""))
    return (
        f"👤 *{emp['name']}*\n"
        f"📍 {branch} | {role}\n"
        f"🕐 {shift_label}\n"
        f"🆔 `{emp['telegram_id']}`"
    )


def format_today_report(shift: str = None) -> str:
    """Bugungi davomat hisoboti"""
    records = db.get_today_attendance()
    if not records:
        return "📊 *Bugun hali hech kim check-in qilmagan.*"

    if shift:
        records = [r for r in records if r.get("shift") == shift]

    lines = [f"📊 *Bugungi davomat* ({datetime.now(tz).strftime('%d.%m.%Y')})", ""]
    for r in records:
        branch = _branch_label(r.get("branch", ""))
        status_emoji = "🟢" if r.get("status") == "on_time" else "🟡" if r.get("status") == "late" else "🔴"
        check_in = (r.get("check_in_time") or "")[:5]
        check_out = (r.get("check_out_time") or "")[:5]
        late = f" ({r['late_minutes']} min)" if r.get("late_minutes") else ""
        out_str = f" → {check_out}" if check_out else ""
        lines.append(f"{status_emoji} {r['name']} ({branch}) — {check_in}{out_str}{late}")

    # Kelmaganlar
    missing = db.get_missing_today(shift)
    if missing:
        lines.append("")
        lines.append(f"❌ *Kelmaganlar ({len(missing)}):*")
        for m in missing:
            branch = _branch_label(m.get("branch", ""))
            shift_label = SHIFTS.get(m.get("shift", ""), {}).get("label", "")
            lines.append(f"  {m['name']} ({branch}, {shift_label})")

    return "\n".join(lines)


def format_date_report(date_str: str) -> str:
    """Kun bo'yicha davomat hisoboti"""
    records = db.get_date_attendance(date_str)
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        dt = date_str

    if not records:
        return f"📊 *{dt} — Ma'lumot yo'q*"

    lines = [f"📊 *Davomat: {dt}*", ""]
    for r in records:
        branch = _branch_label(r.get("branch", ""))
        status_emoji = "🟢" if r.get("status") == "on_time" else "🟡" if r.get("status") == "late" else "🔴"
        check_in = (r.get("check_in_time") or "")[:5]
        check_out = (r.get("check_out_time") or "")[:5]
        late = f" ({r['late_minutes']} min)" if r.get("late_minutes") else ""
        out_str = f" → {check_out}" if check_out else ""
        lines.append(f"{status_emoji} {r['name']} ({branch}) — {check_in}{out_str}{late}")

    # Kelmaganlar
    all_emps = db.get_all_employees()
    checked_ids = set(r["employee_id"] for r in records)
    missing = [e for e in all_emps if e["telegram_id"] not in checked_ids]
    if missing:
        lines.append("")
        lines.append(f"❌ *Kelmaganlar ({len(missing)}):*")
        for m in missing:
            branch = _branch_label(m.get("branch", ""))
            lines.append(f"  {m['name']} ({branch})")

    return "\n".join(lines)


def format_week_report() -> str:
    """Haftalik davomat hisoboti (oxirgi 7 kun)"""
    from datetime import datetime
    end = datetime.now(tz)
    start = end - timedelta(days=7)
    lines = [f"📅 *Haftalik davomat* ({start.strftime('%d.%m')} — {end.strftime('%d.%m')})", ""]
    all_emps = db.get_all_employees()
    present_counts = {}
    late_counts = {}
    for emp in all_emps:
        used_id = emp["telegram_id"]
        present_counts[used_id] = 0
        late_counts[used_id] = 0
        for i in range(7):
            d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            weekday = (start + timedelta(days=i)).weekday()
            if weekday in WORK_DAYS:
                records = db.get_date_attendance(d)
                for r in records:
                    if r["employee_id"] == used_id:
                        if r.get("check_in_time"):
                            present_counts[used_id] += 1
                            if r.get("status") == "late":
                                late_counts[used_id] += 1
                        break
        emp["present"] = present_counts.get(used_id, 0)
        emp["late"] = late_counts.get(used_id, 0)

    # Guruhlab chiqarish
    for branch_key in BRANCHES:
        branch_emps = [e for e in all_emps if e["branch"] == branch_key]
        if not branch_emps:
            continue
        lines.append(f"🏢 *{_branch_label(branch_key)}:*")
        for e in branch_emps:
            p = e["present"]
            l = e["late"]
            bar = "⬜" * p + "⬛" * (6 - p)
            lines.append(f"  {e['name']}: {bar} ({p}/6{' ⚠️' + str(l) + ' kechik' if l else ''})")
        lines.append("")
    return "\n".join(lines)


def format_month_report() -> str:
    """Oylik davomat hisoboti"""
    today = datetime.now(tz)
    month_start = today.replace(day=1)
    total_days = (today - month_start).days + 1
    workdays = sum(1 for i in range(int(total_days))
                  if (month_start + timedelta(days=i)).weekday() in WORK_DAYS)

    lines = [f"📆 *Oylik davomat* ({today.strftime('%B %Y')})", ""]
    all_emps = db.get_all_employees()

    for emp in all_emps:
        used_id = emp["telegram_id"]
        present = 0
        late = 0
        for i in range(int(total_days)):
            d = (month_start + timedelta(days=i)).strftime("%Y-%m-%d")
            if (month_start + timedelta(days=i)).weekday() in WORK_DAYS:
                records = db.get_date_attendance(d)
                for r in records:
                    if r["employee_id"] == used_id and r.get("check_in_time"):
                        present += 1
                        if r.get("status") == "late":
                            late += 1
                        break

        branch = _branch_label(emp.get("branch", ""))
        percent = round((present / max(workdays, 1)) * 100)
        late_str = f", {late} kechik" if late else ""
        lines.append(f"  {emp['name']} ({branch}): {present}/{workdays} ({percent}%){late_str}")

    return "\n".join(lines)


def format_late_report() -> str:
    """Kechikishlar hisoboti"""
    lates = db.get_late_employees()
    if not lates:
        return "✅ *Oxirgi 7 kunda kechikkanlar yo'q*"

    lines = ["⏰ *Oxirgi 7 kundagi kechikishlar*", ""]
    by_employee = {}
    for l in lates:
        key = (l["employee_id"], l["name"])
        if key not in by_employee:
            by_employee[key] = []
        by_employee[key].append(l)

    for (eid, name), records in sorted(by_employee.items(), key=lambda x: -len(x[1])):
        total = sum(r.get("late_minutes", 0) for r in records)
        count = len(records)
        lines.append(f"  {name}: {count} marta, jami {total} daqiqa")
        for r in records[:5]:
            d = r.get("date", "")[-5:]
            lines.append(f"    • {d}: {r.get('late_minutes', 0)} min")

    return "\n".join(lines)


def format_missing_report(shift: str = None) -> str:
    """Bugungi kelmaganlar"""
    missing = db.get_missing_today(shift)
    if not missing:
        return "✅ *Bugun hamma kelgan!*"

    shift_label = ""
    if shift:
        sl = SHIFTS.get(shift, {}).get("label", shift)
        shift_label = f" ({sl})"

    lines = [f"❌ *Bugungi kelmaganlar{shift_label}:*", ""]
    for m in missing:
        branch = _branch_label(m.get("branch", ""))
        sl = SHIFTS.get(m.get("shift", ""), {}).get("label", "")
        lines.append(f"  • {m['name']} — {branch} ({sl})")
    lines.append("")
    lines.append(f"Jami: {len(missing)} ta")

    return "\n".join(lines)


def format_employee_report(employee_id: int) -> str:
    """Xodimning oxirgi 14 kunlik hisoboti"""
    emp = db.get_employee(employee_id)
    if not emp:
        return "❌ Xodim topilmadi."

    lines = [f"👤 *{emp['name']}* oxirgi 14 kunlik hisobot:", ""]
    history = db.get_employee_history(employee_id, limit=14)
    if not history:
        lines.append("📭 Ma'lumot yo'q.")
    else:
        on_time = sum(1 for h in history if h.get("status") == "on_time")
        late = sum(1 for h in history if h.get("status") == "late")
        absent = 14 - len(history)
        lines.append(f"✅ O'z vaqtida: {on_time}")
        lines.append(f"⚠️ Kechikkan: {late}")
        lines.append(f"❌ Kelmagan: {absent}")
        lines.append("")
        for h in history:
            d = h.get("date", "")[-5:]
            ci = (h.get("check_in_time") or "")[:5]
            co = (h.get("check_out_time") or "")[:5]
            s = "🟢" if h.get("status") == "on_time" else "🟡"
            lines.append(f"  {s} {d}: {ci} → {co}")

    return "\n".join(lines)


# ══════════════════════════════════════
#  TASK REPORTS
# ══════════════════════════════════════

def format_today_tasks(employee_id: int) -> str:
    """Xodimning bugungi tasklari"""
    tasks = db.get_today_tasks(employee_id)
    if not tasks:
        return "📋 *Bugungi vazifalar:*  Hali tasklar o'rnatilmagan."

    lines = ["📋 *Bugungi vazifalarim:*", ""]
    total = len(tasks)
    completed = sum(1 for t in tasks if t["status"] == "completed")
    for i, t in enumerate(tasks, 1):
        status_icon = "✅" if t["status"] == "completed" else "⬜"
        time_slot = t.get("time_slot", "")
        task_text = t.get("task_text", "")
        lines.append(f"{status_icon} *{time_slot}*")
        lines.append(f"   {task_text}")

    lines.append("")
    lines.append(f"*Natija:* {completed}/{total} bajarildi ({round(completed/max(total,1)*100)}%)")
    return "\n".join(lines)


def format_tasks_compact(employee_id: int) -> tuple[str, list[dict]]:
    """Tasklarni compact formatda qaytaradi (inline buttonlar uchun)"""
    tasks = db.get_today_tasks(employee_id)
    if not tasks:
        return "📋 *Vazifalar:* Tasklar o'rnatilmagan.", []

    lines = ["📋 *Bugungi vazifalar:*", ""]
    total = len(tasks)
    completed = sum(1 for t in tasks if t["status"] == "completed")

    # Hamma tasklarni ko'rsatamiz
    for i, t in enumerate(tasks, 1):
        status_icon = "✅" if t["status"] == "completed" else "⬜"
        time_slot = t.get("time_slot", "")
        short_task = t.get("task_text", "")[:200]
        if len(t.get("task_text", "")) > 200:
            short_task += "..."
        lines.append(f"{status_icon} *{time_slot}* — {short_task}")

    lines.append("")
    lines.append(f"*Progress:* {completed}/{total} ({round(completed/max(total,1)*100)}%)")
    return "\n".join(lines), tasks


def format_branch_tasks_report(branch: str) -> str:
    """Filialdagi barcha xodimlarning bugungi task holati"""
    emps = db.get_employees_by_branch(branch)
    if not emps:
        return f"🏢 *{_branch_label(branch)}* bo'limida xodimlar yo'q."

    lines = [f"🏢 *{_branch_label(branch)}* — Bugungi task holati", ""]
    for emp in emps:
        tasks = db.get_today_tasks(emp["telegram_id"])
        total = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "completed")
        percent = round(completed / max(total, 1) * 100) if total > 0 else 0
        bar = "🟩" * (percent // 20) + "⬜" * (5 - percent // 20) if total > 0 else "⬜"
        lines.append(f"  {emp['name']}: {completed}/{total} {bar} ({percent}%)")

    return "\n".join(lines)


def format_all_tasks_report() -> str:
    """Barcha xodimlarning bugungi task holati — smena bo'yicha guruhlangan"""
    all_emps = db.get_all_employees()
    lines = ["📋 *Barcha xodimlar — Bugungi task holati*", ""]

    # Smenalar bo'yicha guruhlash
    shift_order = ["morning", "evening"]
    shift_labels = {"morning": "☀️ Ertalab (08:00-15:00)", "evening": "🌙 Kechki (14:00-01:00)"}

    for shift_key in shift_order:
        shift_emps = [e for e in all_emps if e.get("shift") == shift_key]
        if not shift_emps:
            continue
        lines.append(f"*{shift_labels[shift_key]}:*")
        for emp in shift_emps:
            tasks = db.get_today_tasks(emp["telegram_id"])
            total = len(tasks)
            completed = sum(1 for t in tasks if t["status"] == "completed")
            percent = round(completed / max(total, 1) * 100) if total > 0 else 0
            bar = "🟩" * (percent // 20) + "⬜" * (5 - percent // 20) if total > 0 else "⬜"
            branch = _branch_label(emp.get("branch", ""))
            lines.append(f"  {emp['name']} ({branch}): {completed}/{total} {bar} ({percent}%)")
        lines.append("")

    if not all_emps:
        lines.append("❌ Hozircha xodimlar yo'q.")

    return "\n".join(lines)


def format_task_completion_week() -> str:
    """Oxirgi 7 kundagi task bajarilish statistikasi — smena bo'yicha"""
    lines = ["📊 *Oxirgi 7 kundagi task bajarilish*", ""]
    all_emps = db.get_all_employees()

    shift_order = ["morning", "evening"]
    shift_labels = {"morning": "☀️ Ertalab (08:00-15:00)", "evening": "🌙 Kechki (14:00-01:00)"}

    for shift_key in shift_order:
        shift_emps = [e for e in all_emps if e.get("shift") == shift_key]
        if not shift_emps:
            continue
        lines.append(f"*{shift_labels[shift_key]}:*")
        for emp in shift_emps:
            stats = db.get_task_completion_rate(emp["telegram_id"], days=7)
            if stats["total_tasks_per_day"] > 0:
                lines.append(
                    f"  {emp['name']}: "
                    f"{stats['total_completed']}/{stats['total_tasks_per_day'] * max(stats['active_days'], 1)} "
                    f"({stats['completion_rate']}%)"
                )
        lines.append("")

    if not all_emps:
        lines.append("❌ Hozircha xodimlar yo'q.")

    return "\n".join(lines)
