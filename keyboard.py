"""Office Attendance Bot — Klaviaturalar"""

from telegram import ReplyKeyboardMarkup, KeyboardButton


def admin_keyboard():
    """Admin uchun asosiy ReplyKeyboard."""
    return ReplyKeyboardMarkup(
        [
            ["📅 Bugun", "📊 Haftalik", "📆 Oylik"],
            ["⚠️ Kechikkanlar", "❌ Kelmaganlar"],
            ["👥 Xodimlar", "🏢 Filiallar"],
            ["🕐 Ish vaqtini o'zgartirish", "🗑️ Xodimni o'chirish"],
        ],
        resize_keyboard=True,
    )


def coordinator_keyboard(branch: str = None):
    """Koordinator uchun ReplyKeyboard — faqat o'z filiali."""
    return ReplyKeyboardMarkup(
        [
            ["📅 Bugun", "📊 Haftalik"],
            ["⚠️ Kechikkanlar", "❌ Kelmaganlar"],
            ["👥 Xodimlar", "🏢 Filiallar"],
            ["🕐 Ish vaqtini o'zgartirish"],
        ],
        resize_keyboard=True,
    )


def employee_keyboard():
    """Oddiy xodim uchun ReplyKeyboard."""
    return ReplyKeyboardMarkup(
        [
            ["👤 Mening ma'lumotim"],
            ["📋 Qanday ishlatish?"],
        ],
        resize_keyboard=True,
    )


def branches_keyboard():
    """Filial tanlash uchun."""
    return ReplyKeyboardMarkup(
        [
            ["🏢 Integro", "🏢 Amir Temur", "🏢 Xalqlar", "🏢 Online"],
            ["📚 Academic Support"],
            ["🔙 Orqaga"],
        ],
        resize_keyboard=True,
    )


def employees_list_keyboard(employees: list[dict]):
    """Xodimlar ro'yxati — inline tugmalar."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    buttons = []
    for emp in employees:
        from config import BRANCHES, ROLE_LABELS, SHIFTS
        branch = BRANCHES.get(emp["branch"], emp["branch"])
        role = ROLE_LABELS.get(emp["role"], emp["role"])
        shift = "Ert" if emp["shift"] == "morning" else "Kech"
        label = f"{emp['name']} ({branch}, {role}, {shift})"
        buttons.append([InlineKeyboardButton(
            label,
            callback_data=f"emp_{emp['telegram_id']}"
        )])

    return InlineKeyboardMarkup(buttons)


# ── Ish vaqtini tahrirlash uchun keyboardlar ──

def edit_employees_keyboard(employees: list[dict]):
    """Ish vaqtini tahrirlash uchun xodimlar ro'yxati — inline tugmalar."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    buttons = []
    for emp in employees:
        from config import BRANCHES, ROLE_LABELS
        branch = BRANCHES.get(emp["branch"], emp["branch"])
        role = ROLE_LABELS.get(emp["role"], emp["role"])
        shift = "Ert" if emp["shift"] == "morning" else "Kech"
        label = f"🕐 {emp['name']} ({branch}, {role}, {shift})"
        buttons.append([InlineKeyboardButton(
            label,
            callback_data=f"editemp_{emp['telegram_id']}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="editcancel")])
    return InlineKeyboardMarkup(buttons)


def edit_date_keyboard(emp_id: int):
    """Sana tanlash — bugun, kecha yoki boshqa sana."""
    from datetime import datetime, timedelta
    import pytz
    from config import TIMEZONE
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    kb = [
        [InlineKeyboardButton(f"📅 Bugun ({today})", callback_data=f"editdate_{emp_id}_{today}")],
        [InlineKeyboardButton(f"📅 Kecha ({yesterday})", callback_data=f"editdate_{emp_id}_{yesterday}")],
        [InlineKeyboardButton("✏️ Boshqa sana", callback_data=f"editdateother_{emp_id}")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="editcancel")],
    ]
    return InlineKeyboardMarkup(kb)


def edit_field_keyboard(emp_id: int, date_str: str, current_check_in: str = None, current_check_out: str = None):
    """Check-in yoki check-out tanlash uchun inline keyboard."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    btn_in = f"🕐 Kelish vaqti"
    if current_check_in:
        btn_in += f" ({current_check_in[:5]})"
    btn_out = f"🚶 Ketish vaqti"
    if current_check_out:
        btn_out += f" ({current_check_out[:5]})"

    kb = [
        [InlineKeyboardButton(btn_in, callback_data=f"editfield_{emp_id}_{date_str}_check_in")],
        [InlineKeyboardButton(btn_out, callback_data=f"editfield_{emp_id}_{date_str}_check_out")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data=f"editdate_{emp_id}_{date_str}")],
    ]
    return InlineKeyboardMarkup(kb)


def edit_hour_keyboard(emp_id: int, date_str: str, field: str):
    """24 soat — inline tugmalar (3 qator x 8)."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    rows = []
    for i in range(0, 24, 8):
        row = []
        for h in range(i, i + 8):
            row.append(InlineKeyboardButton(
                f"{h:02d}",
                callback_data=f"edithour_{emp_id}_{date_str}_{field}_{h:02d}"
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"editfield_{emp_id}_{date_str}_{field}")])
    return InlineKeyboardMarkup(rows)


def edit_minute_keyboard(emp_id: int, date_str: str, field: str, hour: str):
    """Daqiqa tanlash — 00, 15, 30, 45."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    kb = [
        [
            InlineKeyboardButton(":00", callback_data=f"edittime_{emp_id}_{date_str}_{field}_{hour}:00"),
            InlineKeyboardButton(":15", callback_data=f"edittime_{emp_id}_{date_str}_{field}_{hour}:15"),
            InlineKeyboardButton(":30", callback_data=f"edittime_{emp_id}_{date_str}_{field}_{hour}:30"),
            InlineKeyboardButton(":45", callback_data=f"edittime_{emp_id}_{date_str}_{field}_{hour}:45"),
        ],
        [InlineKeyboardButton("🔙 Orqaga", callback_data=f"edithour_{emp_id}_{date_str}_{field}_{hour}")],
    ]
    return InlineKeyboardMarkup(kb)


def remove_employees_keyboard(employees: list[dict]):
    """O'chirish uchun xodimlar ro'yxati — inline tugmalar."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    buttons = []
    for emp in employees:
        from config import BRANCHES, ROLE_LABELS
        branch = BRANCHES.get(emp["branch"], emp["branch"])
        role = ROLE_LABELS.get(emp["role"], emp["role"])
        shift = "Ert" if emp["shift"] == "morning" else "Kech"
        label = f"🗑️ {emp['name']} ({branch}, {role}, {shift})"
        buttons.append([InlineKeyboardButton(
            label,
            callback_data=f"del_{emp['telegram_id']}"
        )])

    return InlineKeyboardMarkup(buttons)
