"""Office Attendance Bot — Asosiy fayl"""

import logging
from datetime import datetime, time as dt_time, timedelta
import re

import pytz

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

import config
import db
import sheets
import report
import keyboard

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

tz = pytz.timezone(config.TIMEZONE)

# Ro'yxatdan o'tish vaqtida xodim ma'lumotlarini saqlash
# {user_id: {"branch": "...", "name": "...", "shift": "..."}}
pending_registration = {}

# Admin tasdiqlash vaqtida xodim ma'lumotlarini saqlash
# {admin_id: {"telegram_id": ..., "branch": "...", "shift": "...", "telegram_name": "..."}}
pending_approvals = {}


# ══════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════

def is_coordinator(user_id: int) -> bool:
    return user_id in config.COORDINATOR_IDS


def is_support_coordinator(user_id: int) -> bool:
    return user_id == config.SUPPORT_COORDINATOR_ID


def get_coordinator_branch(user_id: int) -> str | None:
    """Koordinator qaysi filialga tegishli ekanini qaytaradi.
    Agar bitta filialga biriktirilgan bo'lsa — o'sha filial.
    Agar bir nechta yoki hech qaysiga — None.
    Support coordinator uchun — "academic_support"."""
    if is_support_coordinator(user_id):
        return "academic_support"
    branches = []
    for branch, ids in config.COORDINATORS.items():
        if user_id in ids:
            branches.append(branch)
    return branches[0] if len(branches) == 1 else None


def is_coordinator_for_branch(user_id: int, branch: str) -> bool:
    """Koordinator aynan shu filialga biriktirilganmi?"""
    return user_id in config.COORDINATORS.get(branch, [])


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def has_access(user_id: int) -> bool:
    """Admin, coordinator yoki support coordinator — hisobot ko'ra oladi."""
    return is_admin(user_id) or is_coordinator(user_id) or is_support_coordinator(user_id)


def is_work_day() -> bool:
    """Bugun ish kunimi? (Dushanba-Shanba)"""
    return datetime.now(tz).weekday() in config.WORK_DAYS


def is_sunday() -> bool:
    """Bugun yakshanbami?"""
    return datetime.now(tz).weekday() == 6


# ══════════════════════════════════════
#  VIDEO CHECK-IN (Guruhda)
# ══════════════════════════════════════

async def handle_group_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guruhdagi YOKI botga private video xabarlarni qayta ishlash."""
    chat_id = update.effective_chat.id
    is_group = (chat_id == config.GROUP_ID)

    user = update.effective_user
    user_id = user.id
    video = update.message.video or update.message.video_note

    if not video:
        return

    # Xodim ro'yxatda bormi?
    emp = db.get_employee(user_id)
    if not emp:
        if not is_group:
            await update.message.reply_text("❌ Siz ro'yxatda yo'qsiz.")
        return

    video_id = str(video.file_id)

    # Check-in yoki check-out?
    if not db.is_checked_in(user_id):
        # CHECK-IN

        # ── Vaqt cheklovlarini tekshirish ──
        shift_cfg = config.SHIFTS.get(emp["shift"])
        if shift_cfg:
            now = datetime.now(tz)
            shift_start = now.replace(hour=shift_cfg["start"], minute=0, second=0, microsecond=0)
            allowed_from = shift_start - timedelta(minutes=20)
            too_late = shift_start + timedelta(minutes=60)
            shift_label = shift_cfg["label"]

            if now < allowed_from:
                await update.message.reply_text(
                    f"⏰ {user.first_name}, sizning smenangiz {shift_label}.\n"
                    f"Smena boshlanishiga hali vaqt bor. "
                    f"Faqat ish vaqtida video yuboring. Qabul qilinmadi."
                )
                return

            if now > too_late:
                await update.message.reply_text(
                    f"❌ {user.first_name}, siz juda kech qoldingiz ({now.strftime('%H:%M')}). "
                    f"Qabul qilinmadi."
                )
                return

        result = db.check_in(user_id, video_id)

        if not result:
            await update.message.reply_text("❌ Check-in xatolik yuz berdi.")
            return

        branch = config.BRANCHES.get(emp["branch"], emp["branch"])
        role = config.ROLE_LABELS.get(emp["role"], emp["role"])
        time_str = result["time"][:5]

        if result["status"] == "on_time":
            msg = (
                f"✅ {user.first_name} — Check-in: {time_str}\n"
                f"📍 {branch} | 👤 {role} | O'z vaqtida"
            )
        else:
            msg = (
                f"⚠️ {user.first_name} — Check-in: {time_str}\n"
                f"📍 {branch} | 👤 {role} | ⏰ {result['late_minutes']} daqiqa kechikdi"
            )

        if not is_work_day():
            msg += "\n⚠️ Bugun dam olish kuni!"

        await update.message.reply_text(msg)

        # Guruhga ham e'lon qilish
        if not is_group and config.GROUP_ID:
            try:
                await context.bot.send_message(config.GROUP_ID, msg)
            except Exception:
                pass

        # Academic Support → support coordinator ga xabar
        if emp["branch"] == "academic_support":
            status_text = "O'z vaqtida" if result["status"] == "on_time" else f"{result['late_minutes']} daqiqa kechikdi"
            try:
                await context.bot.send_message(
                    config.SUPPORT_COORDINATOR_ID,
                    "📚 *Academic Support* — Check-in\n\n"
                    f"👤 {emp['name']}\n"
                    f"🕐 {result['time'][:5]}\n"
                    f"📊 {status_text}",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        # Sheets ga yozish
        sheets.sync_attendance_to_sheets({
            "employee_id": user_id,
            "date": result["date"],
            "check_in_time": result["time"],
            "status": result["status"],
            "late_minutes": result["late_minutes"],
            "check_in_video_id": video_id,
            "name": emp["name"],
            "role": emp["role"],
            "branch": emp["branch"],
            "shift": emp["shift"],
        })

    elif not db.is_checked_out(user_id):
        # CHECK-OUT
        result = db.check_out(user_id, str(video.file_id))

        if not result:
            await update.message.reply_text("❌ Check-out xatolik yuz berdi.")
            return

        time_str = result["check_out_time"][:5]

        msg = f"👋 {user.first_name} — Check-out: {time_str}"

        await update.message.reply_text(msg)

        # Guruhga ham e'lon qilish
        if not is_group and config.GROUP_ID:
            try:
                await context.bot.send_message(config.GROUP_ID, msg)
            except Exception:
                pass

        # Academic Support → support coordinator ga xabar (check-out)
        if emp["branch"] == "academic_support":
            try:
                await context.bot.send_message(
                    config.SUPPORT_COORDINATOR_ID,
                    "📚 *Academic Support* — Check-out\n\n"
                    f"👤 {emp['name']}\n"
                    f"🕐 {time_str}",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        # Sheets ga yozish (check_out)
        sheets.sync_attendance_to_sheets({
            "employee_id": user_id,
            "date": result["date"],
            "check_out_time": result["check_out_time"],
            "check_out_video_id": str(video.file_id),
            "name": emp["name"],
            "role": emp["role"],
            "branch": emp["branch"],
            "shift": emp["shift"],
        })

    else:
        await update.message.reply_text(
            f"ℹ️ {user.first_name}, siz bugun allaqachon check-in va check-out qilgansiz."
        )


# ══════════════════════════════════════
#  ADMIN KOMANDALARI (Private chat)
# ══════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start komandasi."""
    user_id = update.effective_user.id

    # Coordinator yoki admin
    if has_access(user_id):
        if is_admin(user_id):
            await update.message.reply_text(
                f"🏢 *Office Attendance Bot* — Admin\n\n"
                "Tugmalar yoki komandalar orqali boshqaring:",
                parse_mode="Markdown",
                reply_markup=keyboard.admin_keyboard(),
            )
        elif is_support_coordinator(user_id):
            await update.message.reply_text(
                f"🏢 *Office Attendance Bot* — Academic Support Koordinator\n"
                f"📍 *Academic Support*\n\n"
                "Academic Support xodimlari hisobotini ko'rasiz:",
                parse_mode="Markdown",
                reply_markup=keyboard.coordinator_keyboard("academic_support"),
            )
        else:
            branch = get_coordinator_branch(user_id)
            branch_label = config.BRANCHES.get(branch, branch) if branch else "Noma'lum filial"
            await update.message.reply_text(
                f"🏢 *Office Attendance Bot* — Koordinator\n"
                f"📍 *{branch_label}*\n\n"
                "Faqat o'z filialingiz hisobotini ko'rasiz:",
                parse_mode="Markdown",
                reply_markup=keyboard.coordinator_keyboard(branch),
            )
        return

    # Oddiy xodim
    emp = db.get_employee(user_id)
    if emp:
        branch = config.BRANCHES.get(emp["branch"], emp["branch"])
        role = config.ROLE_LABELS.get(emp["role"], emp["role"])
        shift = config.SHIFTS.get(emp["shift"], {}).get("label", emp["shift"])
        await update.message.reply_text(
            f"👤 {emp['name']}\n"
            f"📍 {branch} | {role}\n"
            f"🕐 {shift}\n\n"
            "Check-in uchun botga video yuboring.",
            reply_markup=keyboard.employee_keyboard(),
        )
        return

    # Ro'yxatdan o'tmagan → tugmalar bilan
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    name = update.effective_user.first_name
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏢 Integro", callback_data="regbranch_integro")],
        [InlineKeyboardButton("🏢 Amir Temur", callback_data="regbranch_amir_temur")],
        [InlineKeyboardButton("🏢 Xalqlar", callback_data="regbranch_xalqlar")],
        [InlineKeyboardButton("💻 Online", callback_data="regbranch_online")],
        [InlineKeyboardButton("📚 Academic Support", callback_data="regbranch_academic_support")],
    ])

    await update.message.reply_text(
        f"👋 *Xush kelibsiz, {name}!*\n\n"
        "Ro'yxatdan o'tish uchun bo'limingizni tanlang:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return
    await start(update, context)


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return
    shift = context.args[0] if context.args and context.args[0] in ("morning", "afternoon") else None
    user_id = update.effective_user.id
    if not is_admin(user_id):
        branch = get_coordinator_branch(user_id)
        if branch:
            text = report.format_branch_report(branch, shift=shift)
            await update.message.reply_text(text)
            return
    text = report.format_today_report(shift)
    await update.message.reply_text(text)


async def date_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Format: /date YYYY-MM-DD")
        return
    date_str = context.args[0]
    user_id = update.effective_user.id
    if not is_admin(user_id):
        branch = get_coordinator_branch(user_id)
        if branch:
            text = report.format_branch_report(branch, date_str=date_str)
            await update.message.reply_text(text)
            return
    text = report.format_date_report(date_str)
    await update.message.reply_text(text)


async def week_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return
    user_id = update.effective_user.id
    if not is_admin(user_id):
        branch = get_coordinator_branch(user_id)
        if branch:
            text = report.format_branch_week_report(branch)
            await update.message.reply_text(text)
            return
    text = report.format_week_report()
    await update.message.reply_text(text)


async def month_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return
    user_id = update.effective_user.id
    if not is_admin(user_id):
        branch = get_coordinator_branch(user_id)
        if branch:
            text = report.format_branch_month_report(branch)
            await update.message.reply_text(text)
            return
    text = report.format_month_report()
    await update.message.reply_text(text)


async def late_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return
    user_id = update.effective_user.id
    if not is_admin(user_id):
        branch = get_coordinator_branch(user_id)
        if branch:
            text = report.format_branch_late_report(branch)
            await update.message.reply_text(text)
            return
    text = report.format_late_report()
    await update.message.reply_text(text)


async def absent_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return
    shift = context.args[0] if context.args else None
    if shift and shift not in ("morning", "afternoon"):
        shift = None

    # Hozirgi vaqtga qarab default shift
    if shift is None:
        now = datetime.now(tz)
        shift = "morning" if now.hour < 14 else "afternoon"

    user_id = update.effective_user.id
    if not is_admin(user_id):
        branch = get_coordinator_branch(user_id)
        if branch:
            text = report.format_branch_missing_report(branch, shift)
            await update.message.reply_text(text)
            return
    text = report.format_missing_report(shift)
    await update.message.reply_text(text)


async def branch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return
    user_id = update.effective_user.id

    # Koordinator faqat o'z filialini ko'radi
    if not is_admin(user_id):
        if is_coordinator(user_id):
            branch = get_coordinator_branch(user_id)
            if branch:
                text = report.format_branch_report(branch)
                await update.message.reply_text(text)
                return
            else:
                # Bir nechta filial coordinatori — hammasini ko'rsatish
                await update.message.reply_text(
                    "Filialni tanlang:",
                    reply_markup=keyboard.branches_keyboard(),
                )
                return
        await update.message.reply_text("Siz hech qaysi filialga biriktirilmagansiz.")
        return

    if not context.args:
        branches = ", ".join(config.BRANCH_LIST)
        await update.message.reply_text(f"Filiallar: {branches}")
        return

    branch = context.args[0].lower()
    if branch not in config.BRANCHES:
        await update.message.reply_text(f"Noto'g'ri filial. Mavjud: {', '.join(config.BRANCH_LIST)}")
        return

    text = report.format_branch_report(branch)
    await update.message.reply_text(text)


async def employee_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Format: /employee TELEGRAM_ID")
        return

    try:
        emp_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID raqam bo'lishi kerak.")
        return

    text = report.format_employee_report(emp_id)
    await update.message.reply_text(text)


async def list_employees_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return

    user_id = update.effective_user.id
    if not is_admin(user_id):
        if is_coordinator(user_id):
            branch = get_coordinator_branch(user_id)
            if branch:
                employees = db.get_employees_by_branch(branch)
                if not employees:
                    await update.message.reply_text(f"🏢 *{config.BRANCHES[branch]}* filialida xodimlar yo'q.")
                    return
                lines = [f"👥 *Xodimlar — {config.BRANCHES[branch]}*:", ""]
                for e in employees:
                    role = config.ROLE_LABELS.get(e["role"], e["role"])
                    shift = "Ert" if e["shift"] == "morning" else "Kech"
                    lines.append(f"  {e['telegram_id']} — {e['name']} ({role}, {shift})")
                await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
                return
            else:
                # Bir nechta filial coordinatori — hammasini ko'rsatish
                employees = db.get_all_employees()
                if not employees:
                    await update.message.reply_text("👥 Xodimlar yo'q.")
                    return
                lines = ["👥 *Barcha xodimlar*:", ""]
                for e in employees:
                    branch = config.BRANCHES.get(e["branch"], e["branch"])
                    role = config.ROLE_LABELS.get(e["role"], e["role"])
                    shift = "Ert" if e["shift"] == "morning" else "Kech"
                    lines.append(f"  {e['telegram_id']} — {e['name']} ({branch}, {role}, {shift})")
                await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
                return
        await update.message.reply_text("Siz hech qaysi filialga biriktirilmagansiz.")
        return

    employees = db.get_all_employees()
    if not employees:
        await update.message.reply_text("Hali xodimlar qo'shilmagan.")
        return

    lines = ["👥 *Barcha xodimlar:*", ""]
    for branch_key in config.BRANCHES:
        branch_emps = [e for e in employees if e["branch"] == branch_key]
        if branch_emps:
            lines.append(f"🏢 *{config.BRANCHES[branch_key]}*:")
            for e in branch_emps:
                role = config.ROLE_LABELS.get(e["role"], e["role"])
                shift = "Ert" if e["shift"] == "morning" else "Kech"
                lines.append(f"  {e['telegram_id']} — {e['name']} ({role}, {shift})")
            lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def add_employee_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return

    # Format: /add TELEGRAM_ID NAME ROLE BRANCH SHIFT
    args = context.args
    if len(args) < 5:
        await update.message.reply_text(
            "Format: /add TELEGRAM_ID NAME ROLE BRANCH SHIFT\n\n"
            "Misol: /add 123456 \"Alisher Karimov\" office_manager integro morning\n\n"
            "Role: office_manager yoki cashier\n"
            "Branch: integro, amir_temur, xalqlar\n"
            "Shift: morning yoki afternoon"
        )
        return

    try:
        tid = int(args[0])
    except ValueError:
        await update.message.reply_text("Telegram ID raqam bo'lishi kerak.")
        return

    name = args[1]
    role = args[2].lower()
    branch = args[3].lower()
    shift = args[4].lower()

    if role not in config.ROLES:
        await update.message.reply_text(f"Noto'g'ri role. Mavjud: {', '.join(config.ROLES)}")
        return

    if branch not in config.BRANCHES:
        await update.message.reply_text(f"Noto'g'ri filial. Mavjud: {', '.join(config.BRANCH_LIST)}")
        return

    if shift not in ("morning", "afternoon"):
        await update.message.reply_text("Shift: morning yoki afternoon")
        return

    success = db.add_employee(tid, name, role, branch, shift)
    if success:
        emp = db.get_employee(tid)
        if emp:
            sheets.sync_employee_to_sheets(emp)

        branch_label = config.BRANCHES[branch]
        role_label = config.ROLE_LABELS[role]
        shift_label = config.SHIFTS[shift]["label"]

        await update.message.reply_text(
            f"✅ Xodim qo'shildi:\n"
            f"ID: {tid}\n"
            f"Ism: {name}\n"
            f"Rol: {role_label}\n"
            f"Filial: {branch_label}\n"
            f"Smene: {shift_label}"
        )
    else:
        await update.message.reply_text("❌ Xatolik yuz berdi.")


async def remove_employee_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_access(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Format: /remove TELEGRAM_ID")
        return

    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID raqam bo'lishi kerak.")
        return

    emp = db.get_employee(tid)
    if not emp:
        await update.message.reply_text("Xodim topilmadi.")
        return

    success = db.remove_employee(tid)
    if success:
        await update.message.reply_text(f"✅ {emp['name']} o'chirildi.")
    else:
        await update.message.reply_text("❌ Xatolik yuz berdi.")


# ══════════════════════════════════════
#  TUGMALAR BILAN ISHLASH (private chat)
# ══════════════════════════════════════

async def handle_admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin tugmalarini qayta ishlash."""
    user_id = update.effective_user.id
    text = update.message.text

    if not has_access(user_id):
        # Xodim tugmalarini tekshirish
        emp = db.get_employee(user_id)
        if emp:
            if text == "👤 Mening ma'lumotim":
                branch = config.BRANCHES.get(emp["branch"], emp["branch"])
                role = config.ROLE_LABELS.get(emp["role"], emp["role"])
                shift = config.SHIFTS.get(emp["shift"], {}).get("label", emp["shift"])
                checked_in = db.is_checked_in(user_id)
                checked_out = db.is_checked_out(user_id)
                status_text = ""
                if checked_in and not checked_out:
                    status_text = "\n🟢 Bugun check-in qilingan"
                elif checked_in and checked_out:
                    status_text = "\n✅ Bugun to'liq"
                else:
                    status_text = "\n⚪ Hali check-in qilinmagan"

                await update.message.reply_text(
                    f"👤 {emp['name']}\n"
                    f"📍 {branch} | {role}\n"
                    f"🕐 {shift}"
                    f"{status_text}",
                    reply_markup=keyboard.employee_keyboard(),
                )
                return
            elif text == "📋 Qanday ishlatish?":
                await update.message.reply_text(
                    "📋 *Qanday ishlatish?*\n\n"
                    "1. Ishga kelganingizda *botga video* yuboring\n"
                    "2. Ketayotganingizda yana *video* yuboring\n\n"
                    "Bot avtomatik check-in/out qiladi ✅",
                    parse_mode="Markdown",
                    reply_markup=keyboard.employee_keyboard(),
                )
                return
        return

    if text == "📅 Bugun":
        await today_cmd(update, context)
    elif text == "📊 Haftalik":
        await week_cmd(update, context)
    elif text == "📆 Oylik":
        await month_cmd(update, context)
    elif text == "⚠️ Kechikkanlar":
        await late_cmd(update, context)
    elif text == "❌ Kelmaganlar":
        await absent_cmd(update, context)
    elif text == "👥 Xodimlar":
        await list_employees_cmd(update, context)
    elif text == "🗑️ Xodimni o'chirish":
        await show_remove_employees(update, context)
    elif text == "🕐 Ish vaqtini o'zgartirish":
        await show_simple_work_time_employees(update, context)
    elif text == "🏢 Filiallar":
        user_id = update.effective_user.id
        if not is_admin(user_id):
            branch = get_coordinator_branch(user_id)
            if branch:
                await show_branch_report(update, branch)
                return
        await update.message.reply_text(
            "Filialni tanlang:",
            reply_markup=keyboard.branches_keyboard(),
        )
    elif text == "🏢 Integro":
        await show_branch_report(update, "integro")
    elif text == "🏢 Amir Temur":
        await show_branch_report(update, "amir_temur")
    elif text == "🏢 Xalqlar":
        await show_branch_report(update, "xalqlar")
    elif text == "🏢 Online":
        await show_branch_report(update, "online")
    elif text == "📚 Academic Support":
        await show_branch_report(update, "academic_support")
    elif text == "🔙 Orqaga":
        user_id = update.effective_user.id
        if is_admin(user_id):
            await update.message.reply_text(
                "Asosiy menyu:",
                reply_markup=keyboard.admin_keyboard(),
            )
        else:
            branch = get_coordinator_branch(user_id)
            await update.message.reply_text(
                "Asosiy menyu:",
                reply_markup=keyboard.coordinator_keyboard(branch),
            )


async def show_branch_report(update: Update, branch: str):
    """Filial hisobotini ko'rsatish va keyboardni qaytarish."""
    text = report.format_branch_report(branch)
    await update.message.reply_text(
        text,
        reply_markup=keyboard.admin_keyboard(),
    )


async def show_remove_employees(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """O'chirish uchun xodimlar ro'yxati."""
    if not has_access(update.effective_user.id):
        return

    user_id = update.effective_user.id
    if not is_admin(user_id):
        branch = get_coordinator_branch(user_id)
        if branch:
            employees = db.get_employees_by_branch(branch)
        else:
            employees = []
    else:
        employees = db.get_all_employees()

    if not employees:
        await update.message.reply_text("Hali xodimlar qo'shilmagan.")
        return

    kb = keyboard.remove_employees_keyboard(employees)
    await update.message.reply_text(
        "🗑️ *O'chiriladigan xodimni tanlang:*",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def show_simple_work_time_employees(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ish vaqtini tahrirlash uchun xodimlar ro'yxati (soddalashtirilgan)."""
    if not has_access(update.effective_user.id):
        return

    user_id = update.effective_user.id
    if not is_admin(user_id):
        branch = get_coordinator_branch(user_id)
        if branch:
            employees = db.get_employees_by_branch(branch)
        else:
            employees = []
    else:
        employees = db.get_all_employees()

    if not employees:
        await update.message.reply_text("Hali xodimlar qo'shilmagan.")
        return

    kb = keyboard.edit_employees_keyboard(employees)
    await update.message.reply_text(
        "🕐 *Ish vaqti o'zgartiriladigan xodimni tanlang:*",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def handle_simple_work_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Soddalashtirilgan ish vaqti callback handler."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if not has_access(user_id):
        return

    data = query.data

    # ── Bekor qilish ──
    if data == "worktime_cancel":
        await query.edit_message_text("🔙 Bekor qilindi.", reply_markup=None)
        return

    # ── Xodimni tanlash ──
    if data.startswith("editemp_"):
        emp_id = int(data[8:])
        emp = db.get_employee(emp_id)
        if not emp:
            await query.edit_message_text("❌ Xodim topilmadi.")
            return
        name = emp["name"]
        from config import SHIFTS
        default_shift = SHIFTS.get(emp["shift"], {})
        default_start = f"{default_shift.get('start', '?'):02d}:00"
        default_end = f"{default_shift.get('end', '?'):02d}:00"
        current_start = emp.get("custom_work_start")
        current_end = emp.get("custom_work_end")
        msg = (
            f"👤 *{name}*\n\n"
            f"📌 Joriy:\n"
            f"   🕐 Kelish: {current_start or f'`{default_start}`'}\n"
            f"   🚶 Ketish: {current_end or f'`{default_end}`'}\n\n"
            "Ish vaqtini belgilang:"
        )
        kb = keyboard.work_time_keyboard(emp_id, current_start, current_end)
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    # ── 08:00 dan 17:00 gacha ──
    if data.startswith("setsimple_"):
        parts = data.split("_", 4)
        emp_id = int(parts[1])
        start_str = parts[2]  # "08:00" (kolon bilan)
        end_str = parts[3]   # "17:00"
        emp = db.get_employee(emp_id)
        name = emp["name"] if emp else str(emp_id)
        db.update_employee_work_time(emp_id, "checkin", start_str)
        db.update_employee_work_time(emp_id, "checkout", end_str)
        await query.edit_message_text(
            f"✅ *{name}* — ish vaqti `{start_str} dan {end_str} gacha` qilib belgilandi!",
            parse_mode="Markdown",
        )
        return

    # ── Default ga qaytarish ──
    if data.startswith("setdefault_"):
        emp_id = int(data[11:])
        emp = db.get_employee(emp_id)
        name = emp["name"] if emp else str(emp_id)
        db.update_employee_work_time(emp_id, "checkin", "clear")
        db.update_employee_work_time(emp_id, "checkout", "clear")
        await query.edit_message_text(
            f"✅ *{name}* — ish vaqti default shift ga qaytarildi!",
            parse_mode="Markdown",
        )
        return


async def handle_employee_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline xodim tugmasi bosilganda."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if not has_access(user_id):
        return

    data = query.data
    if data.startswith("emp_"):
        emp_id = int(data[4:])
        text = report.format_employee_report(emp_id)
        await query.message.reply_text(text)

    elif data.startswith("del_"):
        emp_id = int(data[4:])
        emp = db.get_employee(emp_id)
        if not emp:
            await query.edit_message_text("Xodim topilmadi.")
            return

        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Ha, o'chirilsin",
                    callback_data=f"delconfirm_{emp_id}"
                ),
                InlineKeyboardButton(
                    "❌ Bekor qilish",
                    callback_data="delcancel"
                ),
            ]
        ])

        branch = config.BRANCHES.get(emp["branch"], emp["branch"])
        role = config.ROLE_LABELS.get(emp["role"], emp["role"])
        shift = config.SHIFTS.get(emp["shift"], {}).get("label", emp["shift"])

        await query.edit_message_text(
            f"❗️ *{emp['name']}* ni o'chirishni tasdiqlaysizmi?\n\n"
            f"📍 {branch} | {role} | {shift}\n"
            f"🆔 `{emp_id}`",
            parse_mode="Markdown",
            reply_markup=kb,
        )

    elif data.startswith("delconfirm_"):
        emp_id = int(data[11:])
        emp = db.get_employee(emp_id)
        name = emp["name"] if emp else str(emp_id)

        db.remove_employee(emp_id)
        await query.edit_message_text(
            f"✅ *{name}* o'chirildi.",
            parse_mode="Markdown",
        )

    elif data == "delcancel":
        await query.edit_message_text("❌ O'chirish bekor qilindi.")


# ══════════════════════════════════════
#  BUTTON-BASED RO'YXATDAN O'TISH
# ══════════════════════════════════════

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registration tugmalarini qayta ishlash (filial → smena → tasdiqlash)."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("regbranch_"):
        # Filial tanlandi → ism so'rash
        parts = data.split("_", 2)  # regbranch_BRANCH
        branch = parts[1]

        user_id = query.from_user.id
        pending_registration[user_id] = {"branch": branch}

        await query.edit_message_text(
            f"📍 *{config.BRANCHES.get(branch, branch)}* tanlandi.\n\n"
            "✏️ *Ismingizni kiriting:*",
            parse_mode="Markdown",
        )

    elif data.startswith("regshift_"):
        # Smena tanlandi → admin ga tasdiqlashga yuborish
        parts = data.split("_", 2)  # regshift_BRANCH_SHIFT
        branch = parts[1]
        shift = parts[2]
        user_id = query.from_user.id

        reg = pending_registration.get(user_id, {})
        name = reg.get("name", query.from_user.first_name)

        from telegram import InlineKeyboardMarkup, InlineKeyboardButton

        branch_label = config.BRANCHES.get(branch, branch)
        shift_label = config.SHIFTS.get(shift, {}).get("label", shift)

        # Tasdiqlash so'rovi admin yoki support coordinator ga
        approve_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Tasdiqlash",
                    callback_data=f"approve_{user_id}_{branch}_{shift}_{name}"
                ),
                InlineKeyboardButton(
                    "❌ Rad etish",
                    callback_data=f"reject_{user_id}_{name}"
                ),
            ]
        ])

        admin_msg = (
            f"🆕 *Yangi xodim:*\n"
            f"👤 {name}\n"
            f"📍 {branch_label}\n"
            f"🕐 {shift_label}\n"
            f"🆔 `{user_id}`"
        )

        if branch == "academic_support":
            # Academic Support → support coordinator ga
            target_ids = [config.SUPPORT_COORDINATOR_ID]
            reply_text = (
                f"👤 *{name}*\n"
                f"📍 {branch_label}\n"
                f"🕐 {shift_label}\n\n"
                "✅ Ma'lumotlaringiz *Support Coordinator*ga yuborildi.\n"
                "Tasdiqlangach sizga xabar keladi."
            )
        else:
            # Office manager → admin ga
            target_ids = config.ADMIN_IDS
            reply_text = (
                f"👤 *{name}*\n"
                f"📍 {branch_label}\n"
                f"🕐 {shift_label}\n\n"
                "✅ Ma'lumotlaringiz *admin*ga yuborildi.\n"
                "Tasdiqlangach sizga xabar keladi."
            )

        for target_id in target_ids:
            try:
                await context.bot.send_message(
                    target_id, admin_msg,
                    parse_mode="Markdown",
                    reply_markup=approve_kb,
                )
            except Exception as e:
                logger.error(f"Admin {target_id} ga so'rov: {e}")

        await query.edit_message_text(
            reply_text,
            parse_mode="Markdown",
        )

    elif data.startswith("approve_"):
        # Admin tasdiqladi — ism callback data dan olinadi
        parts = data.split("_", 4)  # approve_USERID_BRANCH_SHIFT_NAME
        new_user_id = int(parts[1])
        branch = parts[2]
        shift = parts[3]
        telegram_name = parts[4] if len(parts) > 4 else str(new_user_id)

        user_id = query.from_user.id
        if not is_admin(user_id) and user_id != config.SUPPORT_COORDINATOR_ID:
            await query.answer("❌ Ruxsat yo'q", show_alert=True)
            return

        # To'g'ridan-to'g'ri saqlaymiz — ism callback data dan
        pending_registration.pop(new_user_id, None)  # tozalash
        role = "academic_support" if branch == "academic_support" else "office_manager"
        success = db.add_employee(new_user_id, telegram_name, role, branch, shift)
        if success:
            emp = db.get_employee(new_user_id)
            if emp:
                sheets.sync_employee_to_sheets(emp)

            branch_label = config.BRANCHES.get(branch, branch)
            shift_label = config.SHIFTS.get(shift, {}).get("label", shift)

            await query.edit_message_text(
                f"✅ *{telegram_name}* tasdiqlandi!\n\n"
                f"📍 {branch_label}\n"
                f"🕐 {shift_label}",
                parse_mode="Markdown",
            )

            # Xodimga xabar
            try:
                await context.bot.send_message(
                    new_user_id,
                    f"✅ *Ro'yxatdan o'tdingiz!*\n\n"
                    f"👤 {telegram_name}\n"
                    f"📍 {branch_label}\n"
                    f"🕐 {shift_label}\n\n"
                    "Endi *botga video* yuborib check-in qiling!",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Xodimga xabar: {e}")
        else:
            await query.edit_message_text(
                query.message.text + "\n\n❌ *Xatolik yuz berdi*",
                parse_mode="Markdown",
            )

    elif data.startswith("approvecancel_"):
        user_id = query.from_user.id
        pending_approvals.pop(user_id, None)
        await query.edit_message_text(
            query.message.text.replace(
                "\n\n✏️ *Ism-familiyani kiriting:*", ""
            ) + "\n\n❌ Bekor qilindi.",
            parse_mode="Markdown",
        )

    elif data.startswith("reject_"):
        # Admin rad etdi
        parts = data.split("_", 2)  # reject_USERID_NAME
        new_user_id = int(parts[1])
        name = parts[2] if len(parts) > 2 else str(new_user_id)

        user_id = query.from_user.id
        if not is_admin(user_id) and user_id != config.SUPPORT_COORDINATOR_ID:
            await query.answer("❌ Ruxsat yo'q", show_alert=True)
            return

        try:
            await context.bot.send_message(
                new_user_id,
                "❌ Ro'yxatdan o'tish rad etildi. Admin bilan bog'laning.",
            )
        except Exception:
            pass

        await query.edit_message_text(
            query.message.text + f"\n\n❌ *Rad etildi*",
            parse_mode="Markdown",
        )


# ══════════════════════════════════════
#  RO'YXATDAN O'TISH — ISM KIRITISH
# ══════════════════════════════════════

async def handle_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ro'yxatdan o'tish va admin tasdiqlash vaqtida ism matnini qabul qilish."""
    user_id = update.effective_user.id

    # Admin tasdiqlash jarayonida — ism kiritish
    if user_id in pending_approvals:
        approval = pending_approvals.pop(user_id)
        name = update.message.text.strip()
        if len(name) < 2 or len(name) > 50:
            await update.message.reply_text("Ism 2-50 belgi oralig'ida bo'lishi kerak. Qaytadan yozing:")
            return

        new_user_id = approval["telegram_id"]
        branch = approval["branch"]
        shift = approval["shift"]

        success = db.add_employee(new_user_id, name, "office_manager", branch, shift)
        if success:
            emp = db.get_employee(new_user_id)
            if emp:
                sheets.sync_employee_to_sheets(emp)

            branch_label = config.BRANCHES.get(branch, branch)
            shift_label = config.SHIFTS.get(shift, {}).get("label", shift)

            await update.message.reply_text(
                f"✅ *{name}* tasdiqlandi!\n\n"
                f"📍 {branch_label}\n"
                f"🕐 {shift_label}",
                parse_mode="Markdown",
            )

            # Xodimga xabar
            try:
                await context.bot.send_message(
                    new_user_id,
                    f"✅ *Ro'yxatdan o'tdingiz!*\n\n"
                    f"👤 {name}\n"
                    f"📍 {branch_label}\n"
                    f"🕐 {shift_label}\n\n"
                    "Endi *botga video* yuborib check-in qiling!",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Xodimga xabar: {e}")
        else:
            await update.message.reply_text("❌ Xatolik yuz berdi.")
        return

    # Ro'yxatdan o'tish jarayonida emasmi?
    if user_id not in pending_registration:
        return  # Boshqa handler ishlasin

    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 50:
        await update.message.reply_text("Ism 2-50 belgi oralig'ida bo'lishi kerak. Qaytadan yozing:")
        return

    reg = pending_registration[user_id]
    reg["name"] = name
    branch = reg["branch"]

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🌅 Ertalab (08:00-14:00)",
            callback_data=f"regshift_{branch}_morning"
        )],
        [InlineKeyboardButton(
            "🌙 Kechki (14:00-21:00)",
            callback_data=f"regshift_{branch}_afternoon"
        )],
    ])

    await update.message.reply_text(
        f"👤 *{name}* — qabul qilindi!\n\n"
        "Endi *smenangizni* tanlang:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ══════════════════════════════════════
#  AUTO-CHECK TASKS (scheduler dan chaqiriladi)
# ══════════════════════════════════════

async def auto_check_morning(context: ContextTypes.DEFAULT_TYPE):
    """Avtomatik 08:10 — ertalabki smena kelmaganlar."""
    if is_sunday():
        return  # Yakshanba tekshirmaymiz
    missing = db.get_missing_today("morning")
    if not missing:
        return

    lines = [f"⚠️ *Ertalabki smena* — hali kelmaganlar (08:10):", ""]
    for m in missing:
        branch = config.BRANCHES.get(m["branch"], m["branch"])
        role = config.ROLE_LABELS.get(m["role"], m["role"])
        lines.append(f"❌ {m['name']} ({branch}, {role})")

    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                "\n".join(lines),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Admin {admin_id} ga xabar yuborib bo'lmadi: {e}")


async def auto_check_afternoon(context: ContextTypes.DEFAULT_TYPE):
    """Avtomatik 14:10 — kechki smena kelmaganlar."""
    if is_sunday():
        return
    missing = db.get_missing_today("afternoon")
    if not missing:
        return

    lines = [f"⚠️ *Kechki smena* — hali kelmaganlar (14:10):", ""]
    for m in missing:
        branch = config.BRANCHES.get(m["branch"], m["branch"])
        role = config.ROLE_LABELS.get(m["role"], m["role"])
        lines.append(f"❌ {m['name']} ({branch}, {role})")

    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                "\n".join(lines),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Admin {admin_id} ga xabar yuborib bo'lmadi: {e}")


async def shift_reminder(context: ContextTypes.DEFAULT_TYPE, shift: str):
    """Smenadan 10 daqiqa oldin xodimlarga eslatma."""
    if is_sunday():
        return

    employees = db.get_employees_by_shift(shift)
    if not employees:
        return

    shift_label = config.SHIFTS.get(shift, {}).get("label", shift)
    shift_time = "08:00" if shift == "morning" else "14:00"

    for emp in employees:
        try:
            await context.bot.send_message(
                emp["telegram_id"],
                f"⏰ *Eslatma!* {shift_time} da smenangiz boshlanadi.\n\n"
                f"Ishga kelganingizda *botga video* yuborishni unutmang!",
                parse_mode="Markdown",
            )
        except Exception:
            pass  # Xodim botni bloklagan bo'lishi mumkin


# ══════════════════════════════════════
#  SHEETS STATUS
# ══════════════════════════════════════

async def sheets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Google Sheets ulanish holatini tekshirish (faqat admin)."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Faqat adminlar uchun.")
        return

    has = "✅ bor"
    no = "❌ yoq"
    lines = ["📊 *Google Sheets Status*"]
    lines.append("")
    lines.append(f"🔑 SHEET_KEY: {has if config.SHEET_KEY else no}")
    lines.append(f"🔑 GOOGLE_SERVICE_ACCOUNT_JSON: {has if config.GOOGLE_SERVICE_ACCOUNT_JSON else no}")
    lines.append(f"🔑 GOOGLE_SERVICE_ACCOUNT_B64: {has if config.GOOGLE_SERVICE_ACCOUNT_B64 else no}")
    lines.append("")

    try:
        client = sheets._get_client()
        if client is None:
            lines.append("❌ *Auth:* Google Sheets ga ulanish muvaffaqiyatsiz!")
            lines.append("   Service Account ma'lumotlarini tekshiring.")
        else:
            sheet = sheets._get_sheet()
            if sheet is None:
                lines.append("❌ *Sheet:* Sheet ochilmadi!")
                lines.append("   SHEET_KEY va service account ruxsatlarini tekshiring.")
            else:
                lines.append(f"✅ *Sheet:* {sheet.title}")
                lines.append(f"📄 Worksheets: {len(sheet.worksheets())} ta")
                for ws in sheet.worksheets():
                    lines.append(f"   • {ws.title} ({ws.row_count} qator)")
                lines.append("")
                lines.append("✅ Google Sheets ulanish OK!")
    except Exception as e:
        lines.append(f"❌ *Xatolik:* {e}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════
#  MAIN
# ══════════════════════════════════════

def main():
    """Botni ishga tushirish."""
    logger.info("Bot ishga tushmoqda...")

    # Bazani yaratish
    db.init_db()

    # Sheets dan xodimlarni yuklash va o'chirilganlarni sinxronlash
    sheets_ok = sheets._get_client() is not None
    if sheets_ok:
        logger.info("✅ Google Sheets auth muvaffaqiyatli!")
        sheets.load_employees_from_sheets()
    else:
        logger.warning("❌ Google Sheets auth muvaffaqiyatsiz! Sheets sinxronizatsiyasi o'tkazib yuborildi.")

    # Application
    app = Application.builder().token(config.BOT_TOKEN).build()

    # --- Admin komandalari (faqat private) ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("date", date_cmd))
    app.add_handler(CommandHandler("week", week_cmd))
    app.add_handler(CommandHandler("month", month_cmd))
    app.add_handler(CommandHandler("late", late_cmd))
    app.add_handler(CommandHandler("absent", absent_cmd))
    app.add_handler(CommandHandler("branch", branch_cmd))
    app.add_handler(CommandHandler("employee", employee_cmd))
    app.add_handler(CommandHandler("list", list_employees_cmd))
    app.add_handler(CommandHandler("add", add_employee_cmd))
    app.add_handler(CommandHandler("remove", remove_employee_cmd))
    app.add_handler(CommandHandler("sheets", sheets_cmd))

    # --- Guruhdagi video handler ---
    app.add_handler(MessageHandler(
        filters.VIDEO | filters.VIDEO_NOTE,
        handle_group_video
    ))

    # --- Tugma handlerlari (faqat private) ---
    button_texts = [
        "📅 Bugun", "📊 Haftalik", "📆 Oylik",
        "⚠️ Kechikkanlar", "❌ Kelmaganlar",
        "👥 Xodimlar", "🏢 Filiallar", "🗑️ Xodimni o'chirish",
        "🕐 Ish vaqtini o'zgartirish",
        "🏢 Integro", "🏢 Amir Temur", "🏢 Xalqlar", "🏢 Online",
        "📚 Academic Support",
        "🔙 Orqaga",
        # Xodim tugmalari
        "👤 Mening ma'lumotim", "📋 Qanday ishlatish?",
    ]
    # Har bir matnni escape qilamiz — '?' kabi regex maxsus belgilari uchun
    escaped = "|".join(re.escape(t) for t in button_texts)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE & filters.Regex(f"^({escaped})$"),
        handle_admin_buttons,
    ))

    # Ro'yxatdan o'tish — ism kiritish (Private, TEXT, tugma emas, komanda emas)
    # FAQAT pending_registration yoki pending_approvals bo'lsa qabul qilamiz
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_name_input,
    ))

    # Inline callback — xodimlar ro'yxati + o'chirish
    app.add_handler(CallbackQueryHandler(handle_employee_callback, pattern="^(emp_|del_|delconfirm_|delcancel)"))

    # Inline callback — ish vaqtini tahrirlash
    app.add_handler(CallbackQueryHandler(handle_simple_work_time, pattern="^(edit|set|worktime)"))

    # Registration + Approve/Reject (hammasi bitta handler)
    app.add_handler(CallbackQueryHandler(handle_registration, pattern="^(regbranch|regshift|approve|reject|approvecancel)_"))

    # --- Scheduler: PTB JobQueue orqali avtomatik tekshirish ---
    app.job_queue.run_daily(
        auto_check_morning,
        time=dt_time(hour=8, minute=10, tzinfo=tz),
        days=(0, 1, 2, 3, 4, 5),  # Dushanba-Shanba
    )
    app.job_queue.run_daily(
        auto_check_afternoon,
        time=dt_time(hour=14, minute=10, tzinfo=tz),
        days=(0, 1, 2, 3, 4, 5),
    )

    # Shift eslatmalari (10 daqiqa oldin)
    app.job_queue.run_daily(
        lambda ctx: shift_reminder(ctx, "morning"),
        time=dt_time(hour=7, minute=50, tzinfo=tz),
        days=(0, 1, 2, 3, 4, 5),
    )
    app.job_queue.run_daily(
        lambda ctx: shift_reminder(ctx, "afternoon"),
        time=dt_time(hour=13, minute=50, tzinfo=tz),
        days=(0, 1, 2, 3, 4, 5),
    )

    logger.info("Bot polling boshlanmoqda...")
    app.run_polling()


if __name__ == "__main__":
    main()
