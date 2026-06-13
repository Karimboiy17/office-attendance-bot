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


# ── Ish vaqtini tahrirlash (soddalashtirilgan) ──

def edit_employees_keyboard(employees: list[dict]):
    """Ish vaqtini tahrirlash uchun xodimlar ro'yxati — inline tugmalar."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    buttons = []
    for emp in employees:
        from config import BRANCHES
        branch = BRANCHES.get(emp["branch"], emp["branch"])
        label = f"🕐 {emp['name']} ({branch})"
        buttons.append([InlineKeyboardButton(
            label,
            callback_data=f"editemp_{emp['telegram_id']}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="worktime_cancel")])
    return InlineKeyboardMarkup(buttons)


def work_time_keyboard(emp_id: int, current_start: str = None, current_end: str = None):
    """Xodim uchun oddiy ish vaqti tugmalari."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = []
    btn_label = "🕐 08:00 dan 17:00 gacha"
    if current_start == "08:00" and current_end == "17:00":
        btn_label = "✅ " + btn_label
    kb.append([InlineKeyboardButton(btn_label, callback_data=f"setsimple_{emp_id}_08:00_17:00")])
    if current_start or current_end:
        kb.append([InlineKeyboardButton("↩️ Default ga qaytarish", callback_data=f"setdefault_{emp_id}")])
    kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="worktime_cancel")])
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
