"""Office Manager Bot — Keyboard layout"""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import db


# ══════════════════════════════════════
#  DOIMIY REPLY TUGMALAR (private chat)
# ══════════════════════════════════════

def employee_keyboard():
    """Xodim uchun doimiy tugmalar"""
    kb = [
        [KeyboardButton("📋 Bugungi vazifalarim")],
        [KeyboardButton("👤 Mening ma'lumotim")],
        [KeyboardButton("📊 Bugungi holatim")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


def admin_keyboard():
    """Admin uchun doimiy tugmalar"""
    kb = [
        [KeyboardButton("📊 Bugungi davomat"), KeyboardButton("📋 Bugungi tasklar")],
        [KeyboardButton("❌ Kelmaganlar"), KeyboardButton("⏰ Kechikkanlar")],
        [KeyboardButton("📅 Haftalik hisobot"), KeyboardButton("📆 Oylik hisobot")],
        [KeyboardButton("👥 Xodimlar ro'yxati")],
        [KeyboardButton("➕ Xodim qo'shish"), KeyboardButton("➖ Xodim o'chirish")],
        [KeyboardButton("📋 Tasklarni sozlash"), KeyboardButton("⏰ Ish vaqtini sozlash")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


def coordinator_keyboard(branch: str = None):
    """Coordinator uchun doimiy tugmalar"""
    kb = [
        [KeyboardButton("📊 Bugungi davomat")],
        [KeyboardButton("❌ Kelmaganlar")],
        [KeyboardButton("📅 Haftalik hisobot")],
        [KeyboardButton("👥 Xodimlar ro'yxati")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


# ══════════════════════════════════════
#  INLINE TUGMALAR
# ══════════════════════════════════════

def branch_selection_keyboard():
    """Filial tanlash uchun inline tugmalar"""
    from config import BRANCHES
    kb = []
    for key, label in BRANCHES.items():
        kb.append([InlineKeyboardButton(f"🏢 {label}", callback_data=f"branch_{key}")])
    return InlineKeyboardMarkup(kb)


def registration_branches_keyboard():
    """Ro'yxatdan o'tish uchun filial tugmalari (ReplyKeyboard)"""
    from config import BRANCHES
    kb = []
    row = []
    for key, label in BRANCHES.items():
        row.append(KeyboardButton(f"🏢 {label}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True)


def registration_shifts_keyboard():
    """Ro'yxatdan o'tish uchun smena tanlash tugmalari (ReplyKeyboard)"""
    kb = [
        [KeyboardButton("🌅 Ertalab (08:00-17:00)")],
        [KeyboardButton("🌆 Kechki (14:00-21:00)")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True)


def shift_selection_keyboard():
    """Smena tanlash uchun inline tugmalar"""
    kb = [
        [InlineKeyboardButton("🌅 Ertalab (08:00-17:00)", callback_data="shift_morning")],
        [InlineKeyboardButton("🌆 Kechki (14:00-21:00)", callback_data="shift_evening")],
    ]
    return InlineKeyboardMarkup(kb)


def task_action_keyboard(task_id: int, current_status: str, employee_id: int):
    """Taskni bajarish/bekor qilish tugmalari"""
    if current_status == "completed":
        btn = InlineKeyboardButton("✅ Bajarilgan — bekor qilish", callback_data=f"task_undo_{task_id}_{employee_id}")
    else:
        btn = InlineKeyboardButton("⬜ Bajarildi deb belgilash", callback_data=f"task_done_{task_id}_{employee_id}")
    kb = [[btn]]
    return InlineKeyboardMarkup(kb)


def tasks_navigation_keyboard(employee_id: int, page: int = 0, total_pages: int = 1):
    """Tasklar navigatsiyasi"""
    kb = []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"taskpage_{page-1}_{employee_id}"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton("➡️ Keyingi", callback_data=f"taskpage_{page+1}_{employee_id}"))
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("🔄 Yangilash", callback_data=f"taskrefresh_{employee_id}")])
    return InlineKeyboardMarkup(kb)


def confirm_keyboard(action: str, data: str = ""):
    """Tasdiqlash tugmalari"""
    kb = [
        [
            InlineKeyboardButton("✅ Ha", callback_data=f"confirm_{action}_{data}"),
            InlineKeyboardButton("❌ Yo'q", callback_data=f"cancel_{action}_{data}"),
        ]
    ]
    return InlineKeyboardMarkup(kb)


# ══════════════════════════════════════
#  TASK MANAGEMENT (Admin)
# ══════════════════════════════════════

def admin_task_management_keyboard():
    """Admin task boshqaruvi tugmalari"""
    from config import DEFAULT_TASKS
    shift_labels = {"morning": "☀️ Ertalab", "evening": "🌙 Kechki"}
    kb = []
    for shift_key in DEFAULT_TASKS:
        label = shift_labels.get(shift_key, shift_key.capitalize())
        kb.append([InlineKeyboardButton(f"📝 {label} tasklarini o'rnatish", callback_data=f"set_tasks_{shift_key}")])
    kb.append([InlineKeyboardButton("✏️ Xodim tasklarini tahrirlash", callback_data="edit_employee_tasks")])
    kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])
    return InlineKeyboardMarkup(kb)


def edit_task_employee_list_keyboard(employees: list):
    """Xodimlar ro'yxatini inline tugmalar shaklida"""
    kb = []
    for emp in employees:
        name = emp.get("name", "Noma'lum")
        kb.append([InlineKeyboardButton(f"👤 {name}", callback_data=f"edittasks_emp_{emp['telegram_id']}")])
    kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])
    return InlineKeyboardMarkup(kb)


def edit_tasks_list_keyboard(tasks: list, user_id: int):
    """Xodim tasklarini tahrirlash tugmalari"""
    kb = []
    for t in tasks:
        time_slot = t.get("time_slot", "??:??-??:??")
        task_text = t.get("task_text", "")
        # Qisqa preview
        preview = task_text[:40] + "..." if len(task_text) > 40 else task_text
        label = f"🕐 {time_slot} — {preview}"
        kb.append([InlineKeyboardButton(label, callback_data=f"edittask_{t['id']}")])
    kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="edit_employee_tasks")])
    return InlineKeyboardMarkup(kb)


# ══════════════════════════════════════
#  ISH VAQTINI SOZLASH (Admin)
# ══════════════════════════════════════

def work_time_settings_keyboard():
    """Ish vaqtini sozlash menyusi"""
    kb = [
        [InlineKeyboardButton("🏢 Integro/AT/XD/Central — 🌅 Ertalab", callback_data="wts_morning")],
        [InlineKeyboardButton("🏢 Integro/AT/XD/Central — 🌆 Kechki", callback_data="wts_evening")],
        [InlineKeyboardButton("🏡 Online — 🌅 Ertalab", callback_data="wts_online_morning")],
        [InlineKeyboardButton("🏡 Online — 🌆 Kechki", callback_data="wts_online_evening")],
        [InlineKeyboardButton("⏱ Check-in muddatini o'zgartirish", callback_data="wts_deadline")],
        [InlineKeyboardButton("📅 Ish kunlarini o'zgartirish", callback_data="wts_workdays")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(kb)


def shift_edit_keyboard(shift_key: str):
    """Smena vaqtini tahrirlash tugmalari (+1 / -1)"""
    kb = [
        [
            InlineKeyboardButton("⬅️ -1 soat", callback_data=f"wts_{shift_key}_start_dec"),
            InlineKeyboardButton("Boshi", callback_data=f"wts_{shift_key}_start_show"),
            InlineKeyboardButton("➕ +1 soat", callback_data=f"wts_{shift_key}_start_inc"),
        ],
        [
            InlineKeyboardButton("⬅️ -1 soat", callback_data=f"wts_{shift_key}_end_dec"),
            InlineKeyboardButton("Oxiri", callback_data=f"wts_{shift_key}_end_show"),
            InlineKeyboardButton("➕ +1 soat", callback_data=f"wts_{shift_key}_end_inc"),
        ],
        [InlineKeyboardButton("✅ Saqlash", callback_data=f"wts_{shift_key}_save")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="wts_menu")],
    ]
    return InlineKeyboardMarkup(kb)

# ══════════════════════════════════════
#  TASDIQLANMAGAN XODIMLAR
# ══════════════════════════════════════

def pending_employees_keyboard() -> InlineKeyboardMarkup:
    """Tasdiqlanmagan xodimlar ro'yxati"""
    kb = []
    for emp in db.get_pending_employees():
        label = f"{emp['name']} — {emp['branch']} ({emp['shift']})"
        kb.append([
            InlineKeyboardButton(f"✅ {label}", callback_data=f"apr_{emp['telegram_id']}"),
            InlineKeyboardButton(f"❌", callback_data=f"rej_{emp['telegram_id']}"),
        ])
    if not kb:
        kb.append([InlineKeyboardButton("✅ Barcha xodimlar tasdiqlangan", callback_data="noop")])
    kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])
    return InlineKeyboardMarkup(kb)
