"""Office Attendance Bot — Klaviaturalar"""

from telegram import ReplyKeyboardMarkup, KeyboardButton


def admin_keyboard():
    """Admin uchun asosiy ReplyKeyboard."""
    return ReplyKeyboardMarkup(
        [
            ["📅 Bugun", "📊 Haftalik", "📆 Oylik"],
            ["⚠️ Kechikkanlar", "❌ Kelmaganlar"],
            ["👥 Xodimlar", "🏢 Filiallar"],
            ["🗑️ Xodimni o'chirish"],
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
