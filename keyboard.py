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


# ── Ish vaqtini tahrirlash (doimiy) ──

def edit_employees_keyboard(employees: list[dict]):
    """Ish vaqtini tahrirlash uchun xodimlar ro'yxati — inline tugmalar."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    buttons = []
    for emp in employees:
        from config import BRANCHES, ROLE_LABELS
        branch = BRANCHES.get(emp["branch"], emp["branch"])
        role = ROLE_LABELS.get(emp["role"], emp["role"])
        custom_start = emp.get('custom_work_start')
        shift_label = f" ({custom_start[:5] if custom_start else 'default'})"
        label = f"🕐 {emp['name']} ({branch})"
        buttons.append([InlineKeyboardButton(
            label,
            callback_data=f"editemp_{emp['telegram_id']}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="editcancel")])
    return InlineKeyboardMarkup(buttons)


def edit_shift_keyboard(emp_id: int, current_start: str = None, current_end: str = None):
    """Kelish/Ketish/Default tanlash — doimiy shift vaqtini tahrirlash."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    from config import SHIFTS

    btn_in = f"🕐 Kelish vaqti"
    if current_start:
        btn_in += f" ({current_start[:5]})"
    else:
        btn_in += " (default)"

    btn_out = f"🚶 Ketish vaqti"
    if current_end:
        btn_out += f" ({current_end[:5]})"
    else:
        btn_out += " (default)"

    kb = [
        [InlineKeyboardButton(btn_in, callback_data=f"editfield_{emp_id}_check_in")],
        [InlineKeyboardButton(btn_out, callback_data=f"editfield_{emp_id}_check_out")],
    ]
    # Agar custom vaqt mavjud bo'lsa, "default ga qaytarish" tugmasi
    if current_start:
        kb.append([InlineKeyboardButton("↩️ Kelishni default ga qaytarish", callback_data=f"editdefault_{emp_id}_check_in")])
    if current_end:
        kb.append([InlineKeyboardButton("↩️ Ketishni default ga qaytarish", callback_data=f"editdefault_{emp_id}_check_out")])
    kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="editcancel")])
    return InlineKeyboardMarkup(kb)


def edit_hour_keyboard(emp_id: int, field: str):
    """24 soat — inline tugmalar (3 qator x 8)."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    rows = []
    for i in range(0, 24, 8):
        row = []
        for h in range(i, i + 8):
            row.append(InlineKeyboardButton(
                f"{h:02d}",
                callback_data=f"edithour_{emp_id}_{field}_{h:02d}"
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"editshift_{emp_id}")])
    return InlineKeyboardMarkup(rows)


def edit_minute_keyboard(emp_id: int, field: str, hour: str):
    """Daqiqa tanlash — 00, 15, 30, 45."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    kb = [
        [
            InlineKeyboardButton(":00", callback_data=f"edittime_{emp_id}_{field}_{hour}:00"),
            InlineKeyboardButton(":15", callback_data=f"edittime_{emp_id}_{field}_{hour}:15"),
            InlineKeyboardButton(":30", callback_data=f"edittime_{emp_id}_{field}_{hour}:30"),
            InlineKeyboardButton(":45", callback_data=f"edittime_{emp_id}_{field}_{hour}:45"),
        ],
        [InlineKeyboardButton("🔙 Orqaga", callback_data=f"edithour_{emp_id}_{field}_{hour}")],
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
