#!/usr/bin/env python3
"""Office Manager Bot — Attendance + Task Management"""

import os
import sys
import logging
import random
from datetime import datetime, timedelta
from functools import wraps

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler,
)

import config
import db
import keyboard as kb
import report
import sheets

# ── Logging ──
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from config import TIMEZONE
import pytz
tz = pytz.timezone(TIMEZONE)

# ── Bosqichlar (ConversationHandler) ──
(REG_BRANCH, REG_SHIFT, REG_NAME,
 ADD_EMP_ID, ADD_EMP_NAME, ADD_EMP_ROLE, ADD_EMP_BRANCH, ADD_EMP_SHIFT,
 REMOVE_EMP_ID) = range(9)

LATE_REASON = range(10, 11)

# ── Motivatsion iboralar ──
MOTIVATIONAL_PHRASES = [
    "Ajoyib! Bugun ham ishga o'z vaqtida yetib keldiz! 💪",
    "Barakalla! Ertangi kunning o'zidan boshlang'ich yaxshi! 🌟",
    "Zo'r! Bugun kun maroqli o'tadi! 🔥",
    "Rahmat, xodimlarimizning intizomi uchun! 👍",
    "A'lo! Shu jadallik bilan davom eting! ⚡",
    "Yaxshi ish! Bugungi kunda eng zo'ri siz! 🏆",
]

# ══════════════════════════════════════
#  CHECKLAR
# ══════════════════════════════════════

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def is_employee(user_id: int) -> bool:
    emp = db.get_employee(user_id)
    return emp is not None


def is_work_day() -> bool:
    """Bugun ish kuni ekanligini tekshirish"""
    custom = db.get_custom_shift_times()
    return datetime.now(tz).weekday() in custom["work_days"]
def has_access(user_id: int) -> bool:
    return is_admin(user_id)


# ══════════════════════════════════════
#  START / HELP
# ══════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Avvalgi add flow ni tozalash
    if "add_state" in context.user_data:
        context.user_data.pop("add_state", None)
        context.user_data.pop("add_emp_id", None)
        context.user_data.pop("add_emp_name", None)
        context.user_data.pop("add_emp_branch", None)

    user_id = update.effective_user.id
    user = update.effective_user

    # Admin
    if is_admin(user_id):
        await update.message.reply_text(
            f"🏢 *Office Manager Bot* — Admin panel\n\n"
            "Quyidagi tugmalar orqali boshqaring:",
            parse_mode="Markdown",
            reply_markup=kb.admin_keyboard(),
        )
        return

    # Ro'yxatdan o'tgan xodim
    emp = db.get_employee(user_id)
    if emp:
        branch = config.BRANCHES.get(emp.get("branch", ""), emp.get("branch", ""))
        role = config.ROLE_LABELS.get(emp.get("role", ""), emp.get("role", ""))
        branch_name = emp.get("branch", "default")
        shift_label = db.get_custom_shift_times().get(branch_name, {}).get(emp.get("shift", ""), {}).get("label", "")
        await update.message.reply_text(
            f"👤 *{emp['name']}*\n"
            f"📍 {branch} | {role}\n"
            f"🕐 {shift_label}\n\n"
            "Check-in uchun *video* yuboring yoki quyidagi tugmalardan foydalaning:",
            parse_mode="Markdown",
            reply_markup=kb.employee_keyboard(),
        )
        return

    # Ro'yxatdan o'tmagan
    name = user.first_name or "Foydalanuvchi"
    context.user_data["reg_state"] = "branch"
    await update.message.reply_text(
        f"👋 *Xush kelibsiz, {name}!*\n\n"
        "Office Manager botiga xush kelibsiz.\n"
        "Ro'yxatdan o'tish uchun bo'limingizni tanlang:",
        parse_mode="Markdown",
        reply_markup=kb.registration_branches_keyboard(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


# ══════════════════════════════════════
#  VIDEO CHECK-IN / CHECK-OUT
# ══════════════════════════════════════

pending_late_reason = {}  # {user_id: {"attempts": 0, "date": "..."}}


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Video qabul qilish — check-in yoki check-out"""
    user_id = update.effective_user.id
    user = update.effective_user
    is_group = update.effective_chat.type in ("group", "supergroup")

    # Faqat ro'yxatdan o'tgan xodimlar
    emp = db.get_employee(user_id)
    if not emp:
        await update.message.reply_text(
            "❌ Siz ro'yxatdan o'tmagansiz. Iltimos, avval /start buyrug'i bilan ro'yxatdan o'ting."
        )
        return

    # Faqat shaxsiy xabarlarda qabul qilish
    if update.effective_chat.type != "private":
        context.user_data["awaiting_violation_reason"] = True
        await update.message.reply_text(
            "❌‼️ Nega boshqa chatdan video yuborishga harakat qilayapsiz?! Darhol sababini yozing!"
        )
        return

    if not is_work_day():
        await update.message.reply_text(
            "⚠️ Bugun dam olish kuni! Ish kunlarida video yuboring."
        )
        return

    # Video ID ni olish
    if update.message.video_note:
        video_id = update.message.video_note.file_id
    elif update.message.video:
        video_id = update.message.video.file_id
    else:
        await update.message.reply_text("❌ Iltimos, video yoki video_note yuboring.")
        return

    # ── CHECK-IN yoki CHECK-OUT ──
    if not db.is_checked_in(user_id):
        # CHECK-IN
        custom = db.get_custom_shift_times()
        branch_key = "online" if emp.get("branch") == "online" else "default"
        shifts = custom[branch_key]
        deadline = custom["checkin_deadline_minutes"]

        shift = emp.get("shift", "morning")
        shift_cfg = shifts.get(shift)
        if shift_cfg:
            start_hour = shift_cfg["start"]

        now = datetime.now(tz)
        if shift_cfg:
            shift_start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            allowed_from = shift_start - timedelta(minutes=20)
            too_late = shift_start + timedelta(minutes=120)  # 2 soatgacha ruxsat

            if now < allowed_from:
                await update.message.reply_text(
                    f"⏰ {user.first_name}, sizning smenangiz {shift_cfg['label']}.\n"
                    "Smena boshlanishiga hali vaqt bor. Keyinroq video yuboring."
                )
                return

            if now > too_late:
                await update.message.reply_text(
                    f"❌ {user.first_name}, siz juda kech qoldingiz ({now.strftime('%H:%M')}).\n"
                    "Qabul qilinmadi."
                )
                return

        result = db.check_in(user_id, video_id)
        if not result:
            await update.message.reply_text("❌ Check-in xatolik yuz berdi.")
            return

        branch = config.BRANCHES.get(emp.get("branch", ""), emp.get("branch", ""))
        role = config.ROLE_LABELS.get(emp.get("role", ""), emp.get("role", ""))
        time_str = result["time"][:5]

        if result["status"] == "on_time":
            phrase = random.choice(MOTIVATIONAL_PHRASES)
            msg = (
                f"✅ *{user.first_name}* — Check-in: {time_str}\n"
                f"📍 {branch} | O'z vaqtida\n\n"
                f"💬 {phrase}"
            )
        else:
            msg = (
                f"⚠️ *{user.first_name}* — Check-in: {time_str}\n"
                f"📍 {branch} | ⏰ {result['late_minutes']} daqiqa kechikdi"
            )

        await update.message.reply_text(msg, parse_mode="Markdown")

        # Kechikkan — sabab so'rash
        if result["status"] == "late":
            pending_late_reason[user_id] = {"attempts": 0, "date": result["date"]}
            await update.message.reply_text(
                f"⚠️ Siz {result['late_minutes']} daqiqa kechikdingiz.\n"
                "Iltimos, *kechikish sababini* yozib yuboring:",
                parse_mode="Markdown",
            )
            context.job_queue.run_once(
                late_reason_reminder,
                when=300,
                data={"user_id": user_id, "attempt": 1},
                name=f"late_reason_{user_id}",
            )

        # Guruhga e'lon + video
        if not is_group and config.GROUP_ID:
            try:
                await context.bot.send_message(config.GROUP_ID, msg, parse_mode="Markdown")
                await update.message.forward_copy(config.GROUP_ID)
            except Exception:
                pass

        # Tasklarni ko'rsatish (check-in dan keyin)
        tasks = db.get_today_tasks(user_id)
        if tasks:
            await show_tasks_to_user(update, context, user_id)

        # Sheets
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
        result = db.check_out(user_id, video_id)
        if not result:
            await update.message.reply_text("❌ Check-out xatolik yuz berdi.")
            return

        time_str = result["check_out_time"][:5]
        msg = f"👋 *{user.first_name}* — Check-out: {time_str}"

        # Task yakuniy natijasi
        tasks = db.get_today_tasks(user_id)
        total = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "completed")
        if total > 0:
            percent = round(completed / total * 100)
            msg += f"\n\n📋 *Bugungi tasklar:* {completed}/{total} ({percent}%)"
            if percent == 100:
                msg += "\n🎉 Barcha vazifalarni bajardingiz! Zo'r!"
            elif percent >= 70:
                msg += "\n👍 Yaxshi natija!"
            else:
                msg += "\n💪 Ertaga ko'proq bajarishga harakat qiling!"

        await update.message.reply_text(msg, parse_mode="Markdown")

        # Guruhga e'lon + video
        if not is_group and config.GROUP_ID:
            try:
                await context.bot.send_message(config.GROUP_ID, msg, parse_mode="Markdown")
                await update.message.forward_copy(config.GROUP_ID)
            except Exception:
                pass

        # Sheets
        sheets.sync_attendance_to_sheets({
            "employee_id": user_id,
            "date": result["date"],
            "check_out_time": result["check_out_time"],
            "check_out_video_id": video_id,
            "name": emp["name"],
            "role": emp["role"],
            "branch": emp["branch"],
            "shift": emp["shift"],
        })

    else:
        await update.message.reply_text(
            f"ℹ️ *{user.first_name}*, siz bugun allaqachon check-in va check-out qilgansiz.",
            parse_mode="Markdown",
        )


async def show_tasks_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Foydalanuvchiga tasklarni inline buttonlar bilan ko'rsatish"""
    text, tasks = report.format_tasks_compact(user_id)
    if not tasks:
        return

    total = len(tasks)
    completed = sum(1 for t in tasks if t["status"] == "completed")

    # Birinchi 5 task uchun tugmalar
    rows = []
    for i, t in enumerate(tasks):
        if i >= 5:
            break
        status_icon = "✅" if t["status"] == "completed" else "⬜"
        time_slot = t.get("time_slot", "")
        short = time_slot
        cb_data = f"task_toggle_{t['task_id']}"
        rows.append([InlineKeyboardButton(f"{status_icon} {short}", callback_data=cb_data)])

    # Pagination va refresh
    nav_row = []
    if total > 5:
        nav_row.append(InlineKeyboardButton(f"📋 Hammasi ({total})", callback_data="task_list_full"))
    nav_row.append(InlineKeyboardButton("🔄", callback_data="task_refresh"))
    if nav_row:
        rows.append(nav_row)

    markup = InlineKeyboardMarkup(rows)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)


# ══════════════════════════════════════
#  KEChIKISH SABABI
# ══════════════════════════════════════

async def late_reason_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    user_id = data["user_id"]
    attempt = data["attempt"]

    if user_id in pending_late_reason:
        pending_late_reason[user_id]["attempts"] = attempt
        await context.bot.send_message(
            user_id,
            f"⏰ Eslatma ({attempt}/3): Kechikish sababini yozib yuboring. "
            "Aks holda kechikish qayd etiladi."
        )
        if attempt < 3:
            context.job_queue.run_once(
                late_reason_reminder,
                when=300,
                data={"user_id": user_id, "attempt": attempt + 1},
                name=f"late_reason_{user_id}",
            )


async def handle_late_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kechikish sababini qabul qilish"""
    user_id = update.effective_user.id
    if user_id not in pending_late_reason:
        return  # Kechikish sababi so'ralmagan

    reason = update.message.text.strip()
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    conn = db.get_conn()
    try:
        conn.execute(
            "UPDATE attendance SET late_reason = ? WHERE employee_id = ? AND date = ?",
            (reason, user_id, today_str)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Late reason save error: {e}")
    finally:
        conn.close()

    # Jobs to'xtatish
    for job in context.job_queue.jobs():
        if job.name == f"late_reason_{user_id}":
            job.schedule_removal()

    del pending_late_reason[user_id]
    await update.message.reply_text(
        "✅ Kechikish sababi qabul qilindi. Rahmat! 👍"
    )


# ══════════════════════════════════════
#  XODIM TUGMALARI (Reply buttons)
# ══════════════════════════════════════

async def handle_employee_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    emp = db.get_employee(user_id)
    if not emp:
        await update.message.reply_text("❌ Siz ro'yxatdan o'tmagansiz.")
        return

    if text == "📋 Bugungi vazifalarim":
        await show_tasks_full(update, context, user_id)

    elif text == "👤 Mening ma'lumotim":
        await update.message.reply_text(
            report.format_employee_info(emp),
            parse_mode="Markdown",
        )

    elif text == "📊 Bugungi holatim":
        await show_employee_status(update, context, user_id)

    else:
        await update.message.reply_text("❌ Noto'g'ri buyruq.")


async def show_tasks_full(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Barcha tasklarni inline buttonlar bilan ko'rsatish"""
    tasks = db.get_today_tasks(user_id)
    if not tasks:
        await update.message.reply_text("📋 Bugungi vazifalar o'rnatilmagan.")
        return

    total = len(tasks)
    completed = sum(1 for t in tasks if t["status"] == "completed")

    lines = [f"📋 *Bugungi vazifalar:* {completed}/{total}", ""]
    rows = []
    for i, t in enumerate(tasks, 1):
        status_icon = "✅" if t["status"] == "completed" else "⬜"
        time_slot = t.get("time_slot", "")
        task_text = t.get("task_text", "")
        lines.append(f"{status_icon} *{time_slot}*")
        lines.append(f"   {task_text}")
        cb_data = f"task_toggle_{t['task_id']}"
        rows.append([InlineKeyboardButton(f"{status_icon} {time_slot}", callback_data=cb_data)])

    lines.append("")
    percent = round(completed / max(total, 1) * 100)
    lines.append(f"*Progress:* {percent}%")

    rows.append([InlineKeyboardButton("🔄 Yangilash", callback_data="task_refresh")])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def show_employee_status(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Xodimning bugungi holati"""
    emp = db.get_employee(user_id)
    if not emp:
        return

    lines = [f"👤 *{emp['name']}* — Bugungi holat", ""]

    # Attendance
    checked_in = db.is_checked_in(user_id)
    checked_out = db.is_checked_out(user_id)
    if checked_in and checked_out:
        lines.append("✅ Check-in va Check-out qilingan")
    elif checked_in:
        lines.append("🟢 Check-in qilingan (hali check-out qilinmagan)")
    else:
        lines.append("❌ Hali check-in qilinmagan")

    # Tasks
    tasks = db.get_today_tasks(user_id)
    total = len(tasks)
    completed = sum(1 for t in tasks if t["status"] == "completed")
    if total > 0:
        percent = round(completed / total * 100)
        bar = "🟩" * (percent // 20) + "⬜" * (5 - percent // 20)
        lines.append(f"📋 Tasklar: {completed}/{total} {bar} ({percent}%)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════
#  INLINE TUGMALAR
# ══════════════════════════════════════

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        data = query.data
        user_id = update.effective_user.id
        logger.info(f"📩 Callback received: data='{data}', user_id={user_id}")

        # ── Task toggle ──
        if data.startswith("task_toggle_"):
            task_id = int(data.replace("task_toggle_", ""))
            tasks = db.get_today_tasks(user_id)
            for t in tasks:
                if t["task_id"] == task_id:
                    if t["status"] == "completed":
                        db.uncomplete_task(user_id, task_id)
                    else:
                        db.complete_task(user_id, task_id)
                    break
            await refresh_task_message(query, user_id)
            return

        # ── Task refresh ──
        if data == "task_refresh":
            await refresh_task_message(query, user_id)
            return

        # ── Task bajarishni boshladim ──
        if data.startswith("task_started_"):
            task_id = int(data.replace("task_started_", ""))
            await query.edit_message_text(
                "✅ *Yaxshi, omad tilaymiz!*\\n\\n"
                "Taskni bajarib bo'lganingizdan so'ng "
                "✅ belgilashni unutmang.",
                parse_mode="Markdown",
            )
            return

        # ── Task bajara olmayman ──
        if data.startswith("task_cant_do_"):
            task_id = int(data.replace("task_cant_do_", ""))
            pending_task_reason[user_id] = task_id
            await query.edit_message_text(
                "❌ Sababini yozib yuboring:",
                parse_mode="Markdown",
            )
            return

        # ── Task full list ──
        if data == "task_list_full":
            tasks = db.get_today_tasks(user_id)
            if not tasks:
                await query.edit_message_text("📋 Vazifalar yo'q.")
                return

            total = len(tasks)
            completed = sum(1 for t in tasks if t["status"] == "completed")
            lines = [f"📋 *Bugungi vazifalar:* {completed}/{total}", ""]
            rows = []
            for i, t in enumerate(tasks, 1):
                status_icon = "✅" if t["status"] == "completed" else "⬜"
                time_slot = t.get("time_slot", "")
                task_text = t.get("task_text", "")
                lines.append(f"{status_icon} *{time_slot}*")
                lines.append(f"   {task_text}")
                cb_data = f"task_toggle_{t['task_id']}"
                rows.append([InlineKeyboardButton(f"{status_icon} {time_slot}", callback_data=cb_data)])

            lines.append("")
            percent = round(completed / max(total, 1) * 100)
            lines.append(f"*Progress:* {percent}%")

            rows.append([InlineKeyboardButton("🔄 Yangilash", callback_data="task_refresh")])
            await query.edit_message_text(
                "\n".join(lines),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(rows),
            )
            return

        # ── Admin: Tasklarni sozlash ──
        if data.startswith("set_tasks_"):
            name_key = data.replace("set_tasks_", "")
            if not is_admin(user_id):
                await query.edit_message_text("❌ Ruxsat yo'q.")
                return

            # Default tasklarni o'rnatish (smena bo'yicha)
            if name_key not in config.DEFAULT_TASKS:
                await query.edit_message_text(f"❌ '{name_key}' noto'g'ri smena.")
                return
            default_tasks = config.DEFAULT_TASKS[name_key]

            shift_label = {"morning": "☀️ Ertalab", "evening": "🌙 Kechki"}.get(name_key, name_key)
            all_emps = db.get_all_employees()
            target_emps = [e for e in all_emps if e.get("shift") == name_key]

            if not target_emps:
                await query.edit_message_text(
                    f"❌ {shift_label} smenasida xodimlar yo'q."
                )
                return

            count = 0
            for emp in target_emps:
                if db.set_employee_tasks(emp["telegram_id"], default_tasks):
                    count += 1

            if count:
                await query.edit_message_text(
                    f"✅ {shift_label} smenasidagi {count} ta xodimga tasklar o'rnatildi!"
                )
            else:
                await query.edit_message_text("❌ Xatolik yuz berdi.")
            return

        # ── Admin back ──
        if data == "admin_back":
            await query.edit_message_text(
                "🏢 *Admin panel*",
                parse_mode="Markdown",
            )
            return

        # ── Xodimni tasdiqlash ──
        if data.startswith("apr_"):
            emp_id = int(data.replace("apr_", ""))
            if db.approve_employee(emp_id):
                emp = db.get_employee(emp_id)
                name = emp["name"] if emp else emp_id
                await query.edit_message_text(
                    f"✅ *{name}* tasdiqlandi!",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Qayta yuklash", callback_data="refresh_pending")]
                    ]),
                )
                # Xodimga xabar yuborish
                try:
                    await context.bot.send_message(
                        emp_id,
                        "✅ *Tasdiqlandingiz!* Endi /start bosib ishga kirishingiz mumkin.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
            else:
                await query.edit_message_text("❌ Xatolik yuz berdi.")
            return

        # ── Xodimni rad etish ──
        if data.startswith("rej_"):
            emp_id = int(data.replace("rej_", ""))
            emp = db.get_employee(emp_id)
            if emp:
                db.remove_employee(emp_id)
                await query.edit_message_text(
                    f"❌ *{emp['name']}* rad etildi.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Qayta yuklash", callback_data="refresh_pending")]
                    ]),
                )
                try:
                    await context.bot.send_message(
                        emp_id,
                        "❌ Arizangiz rad etildi. Batafsil ma'lumot uchun admin bilan bog'laning.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
            return

        # ── Tasdiqlanmagan xodimlar ro'yxatini yangilash ──
        if data == "refresh_pending":
            pending = db.get_pending_employees()
            if not pending:
                await query.edit_message_text(
                    "✅ Barcha xodimlar tasdiqlangan.",
                )
                return
            text_lines = ["🆕 *Tasdiqlanmagan xodimlar:*\n"]
            for emp in pending:
                text_lines.append(f"👤 {emp['name']} — {emp['branch']} ({emp['shift']})")
            await query.edit_message_text(
                "\n".join(text_lines),
                parse_mode="Markdown",
                reply_markup=kb.pending_employees_keyboard(),
            )
            return

        # ── Work Time Settings ──
        if data == "wts_menu":
            await show_wts_menu(query)
            return

        if data == "wts_morning":
            settings = db.get_custom_shift_times()
            s = settings["default"]["morning"]
            await query.edit_message_text(
                f"🌅 *Ertalab smenasi (Integro/AT/XD/Central)*\n\n"
                f"Boshlanishi: `{s['start']:02d}:00`\n"
                f"Tugashi: `{s['end']:02d}:00`\n\n"
                "Vaqtni o'zgartirish uchun tugmalardan foydalaning:",
                parse_mode="Markdown",
                reply_markup=kb.shift_edit_keyboard("morning"),
            )
            return

        if data == "wts_evening":
            settings = db.get_custom_shift_times()
            s = settings["default"]["evening"]
            await query.edit_message_text(
                f"🌆 *Kechki smena (Integro/AT/XD/Central)*\n\n"
                f"Boshlanishi: `{s['start']:02d}:00`\n"
                f"Tugashi: `{s['end']:02d}:00`\n\n"
                "Vaqtni o'zgartirish uchun tugmalardan foydalaning:",
                parse_mode="Markdown",
                reply_markup=kb.shift_edit_keyboard("evening"),
            )
            return

        if data == "wts_online_morning":
            settings = db.get_custom_shift_times()
            s = settings["online"]["morning"]
            await query.edit_message_text(
                f"🌅 *Online - Ertalab smenasi*\n\n"
                f"Boshlanishi: `{s['start']:02d}:00`\n"
                f"Tugashi: `{s['end']:02d}:00`\n\n"
                "Vaqtni o'zgartirish uchun tugmalardan foydalaning:",
                parse_mode="Markdown",
                reply_markup=kb.shift_edit_keyboard("online_morning"),
            )
            return

        if data == "wts_online_evening":
            settings = db.get_custom_shift_times()
            s = settings["online"]["evening"]
            await query.edit_message_text(
                f"🌆 *Online - Kechki smenasi*\n\n"
                f"Boshlanishi: `{s['start']:02d}:00`\n"
                f"Tugashi: `{s['end']:02d}:00`\n\n"
                "Vaqtni o'zgartirish uchun tugmalardan foydalaning:",
                parse_mode="Markdown",
                reply_markup=kb.shift_edit_keyboard("online_evening"),
            )
            return

        if data == "wts_deadline":
            settings = db.get_custom_shift_times()
            d = settings["checkin_deadline_minutes"]
            await query.edit_message_text(
                f"⏱ *Check-in muddati*\n\n"
                f"Hozirgi: smena boshlangandan keyin `{d}` daqiqa\n\n"
                "Yangi qiymatni *daqiqa* sonida yozib yuboring (masalan: `10`):",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Orqaga", callback_data="wts_menu")]
                ]),
            )
            context.user_data["awaiting_deadline"] = True
            return

        if data == "wts_workdays":
            settings = db.get_custom_shift_times()
            days = settings["work_days"]
            day_names = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba",
                         "Juma", "Shanba", "Yakshanba"]
            lines = ["📅 *Ish kunlari*\n"]
            for d in range(7):
                status = "✅" if d in days else "❌"
                lines.append(f"{status} {day_names[d]}")
            lines.append("")
            lines.append("O'zgartirish uchun kun raqamini yozing (0-6, masalan: `0,1,2,3,4,5,6`):")
            await query.edit_message_text(
                "\n".join(lines),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Orqaga", callback_data="wts_menu")]
                ]),
            )
            context.user_data["awaiting_workdays"] = True
            return

        # Shift soatlarni tahrirlash
        if data.startswith("wts_morning_start_dec"):
            adj_shift_hour("morning", "start", -1, query)
            return
        if data.startswith("wts_morning_start_inc"):
            adj_shift_hour("morning", "start", 1, query)
            return
        if data.startswith("wts_morning_end_dec"):
            adj_shift_hour("morning", "end", -1, query)
            return
        if data.startswith("wts_morning_end_inc"):
            adj_shift_hour("morning", "end", 1, query)
            return
        if data.startswith("wts_morning_start_show"):
            show_shift_current(query, "morning", "start")
            return
        if data.startswith("wts_morning_end_show"):
            show_shift_current(query, "morning", "end")
            return
        if data == "wts_morning_save":
            await save_shift(query, "morning")
            return

        if data.startswith("wts_evening_start_dec"):
            adj_shift_hour("evening", "start", -1, query)
            return
        if data.startswith("wts_evening_start_inc"):
            adj_shift_hour("evening", "start", 1, query)
            return
        if data.startswith("wts_evening_end_dec"):
            adj_shift_hour("evening", "end", -1, query)
            return
        if data.startswith("wts_evening_end_inc"):
            adj_shift_hour("evening", "end", 1, query)
            return
        if data.startswith("wts_evening_start_show"):
            show_shift_current(query, "evening", "start")
            return
        if data.startswith("wts_evening_end_show"):
            show_shift_current(query, "evening", "end")
            return
        if data == "wts_evening_save":
            await save_shift(query, "evening")
            return

        # ── Online branch handlers ──
        if data.startswith("wts_online_morning_start_dec"):
            adj_shift_hour("online_morning", "start", -1, query)
            return
        if data.startswith("wts_online_morning_start_inc"):
            adj_shift_hour("online_morning", "start", 1, query)
            return
        if data.startswith("wts_online_morning_end_dec"):
            adj_shift_hour("online_morning", "end", -1, query)
            return
        if data.startswith("wts_online_morning_end_inc"):
            adj_shift_hour("online_morning", "end", 1, query)
            return
        if data.startswith("wts_online_morning_start_show"):
            show_shift_current(query, "online_morning", "start")
            return
        if data.startswith("wts_online_morning_end_show"):
            show_shift_current(query, "online_morning", "end")
            return
        if data == "wts_online_morning_save":
            await save_shift(query, "online_morning")
            return

        if data.startswith("wts_online_evening_start_dec"):
            adj_shift_hour("online_evening", "start", -1, query)
            return
        if data.startswith("wts_online_evening_start_inc"):
            adj_shift_hour("online_evening", "start", 1, query)
            return
        if data.startswith("wts_online_evening_end_dec"):
            adj_shift_hour("online_evening", "end", -1, query)
            return
        if data.startswith("wts_online_evening_end_inc"):
            adj_shift_hour("online_evening", "end", 1, query)
            return
        if data.startswith("wts_online_evening_start_show"):
            show_shift_current(query, "online_evening", "start")
            return
        if data.startswith("wts_online_evening_end_show"):
            show_shift_current(query, "online_evening", "end")
            return
        if data == "wts_online_evening_save":
            await save_shift(query, "online_evening")
            return

        # ── Coordinator: Xodim tasklarini tahrirlash ──
        if data == "edit_employee_tasks":
            if not is_admin(user_id):
                await query.edit_message_text("❌ Ruxsat yo'q.")
                return
            employees = db.get_all_employees()
            if not employees:
                await query.edit_message_text("👥 Xodimlar yo'q.")
                return
            text = "✏️ *Xodim tasklarini tahrirlash*\\n\\nQaysi xodimning tasklarini o'zgartirmoqchisiz?"
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=kb.edit_task_employee_list_keyboard(employees),
            )
            return

        if data.startswith("edittasks_emp_"):
            if not is_admin(user_id):
                await query.edit_message_text("❌ Ruxsat yo'q.")
                return
            emp_id = int(data.replace("edittasks_emp_", ""))
            emp = db.get_employee_by_id(emp_id)
            if not emp:
                await query.edit_message_text("❌ Xodim topilmadi.")
                return
            tasks = db.get_today_tasks(emp_id)
            if not tasks:
                await query.edit_message_text(f"👤 {emp['name']} — tasklari yo'q.")
                return

            lines = [f"✏️ *{emp['name']} tasklari*\\n"]
            for t in tasks:
                status_icon = "✅" if t["status"] == "completed" else "⬜"
                lines.append(f"{status_icon} *{t['time_slot']}*")
                lines.append(f"   {t['task_text']}")
            await query.edit_message_text(
                "\\n".join(lines),
                parse_mode="Markdown",
                reply_markup=kb.edit_tasks_list_keyboard(tasks, emp_id),
            )
            return

        if data.startswith("edittask_"):
            if not is_admin(user_id):
                await query.edit_message_text("❌ Ruxsat yo'q.")
                return
            task_id = int(data.replace("edittask_", ""))
            context.user_data["editing_task_id"] = task_id
            context.user_data["awaiting_task_edit"] = True
            await query.edit_message_text(
                "✏️ *Task matnini yozib yuboring:*\\n\\n"
                "Yangi task textini to'liq yozing. Vaqt slotini o'zgartirish kerak bo'lsa, "
                "avval `HH:MM-HH:MM` formatida vaqtni + yangi matnni yozing, masalan:\\n"
                "`10:00-11:00 Telegramga javob berish`",
                parse_mode="Markdown",
            )
            return

        # ── Admin: Xodimni tasdiqlash / rad etish ──
        if data.startswith("apr_"):
            if not is_admin(user_id):
                await query.edit_message_text("❌ Ruxsat yo'q.")
                return
            emp_id = int(data.replace("apr_", ""))
            emp = db.get_employee_by_id(emp_id)
            if not emp:
                await query.edit_message_text("❌ Xodim topilmadi.")
                return
            if db.approve_employee(emp_id):
                await query.edit_message_text(
                    f"✅ *{emp['name']}* tasdiqlandi!\\\\n\\\\n"
                    f"Endi tizimga kirishi mumkin.",
                    parse_mode="Markdown",
                )
                # Xodimga xabar
                try:
                    await context.bot.send_message(
                        emp_id,
                        f"✅ *Tasdiqlandingiz!*\\\\n\\\\n"
                        f"Endi check-in qilishingiz mumkin.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
            else:
                await query.edit_message_text("❌ Xatolik yuz berdi.")
            return

        if data.startswith("rej_"):
            if not is_admin(user_id):
                await query.edit_message_text("❌ Ruxsat yo'q.")
                return
            emp_id = int(data.replace("rej_", ""))
            emp = db.get_employee_by_id(emp_id)
            if not emp:
                await query.edit_message_text("❌ Xodim topilmadi.")
                return
            if db.reject_employee(emp_id):
                await query.edit_message_text(
                    f"❌ *{emp['name']}* rad etildi va o'chirildi.",
                    parse_mode="Markdown",
                )
            else:
                await query.edit_message_text("❌ Xatolik yuz berdi.")
            return

        if data == "noop":
            await query.edit_message_text("✅ Hech qanday o'zgarish yo'q.")
            return

        # ── Unknown callback ──
        logger.warning(f"⚠️ Unknown callback data: {data}")
        await query.edit_message_text(
            "❌ Noma'lum buyruq. Iltimos, /start ni bosing.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Boshiga", callback_data="admin_back")],
            ]),
        )

    except Exception as e:
        logger.error(f"❌ Callback error ({data if 'data' in dir() else '?'}): {e}", exc_info=True)
        try:
            await query.answer(text="❌ Xatolik yuz berdi", show_alert=True)
        except Exception:
            pass


async def refresh_task_message(query, user_id: int):
    """Task xabarini yangilash"""
    tasks = db.get_today_tasks(user_id)
    if not tasks:
        await query.edit_message_text("📋 Vazifalar yo'q.")
        return

    total = len(tasks)
    completed = sum(1 for t in tasks if t["status"] == "completed")

    text, _ = report.format_tasks_compact(user_id)
    percent = round(completed / max(total, 1) * 100)

    rows = []
    for i, t in enumerate(tasks):
        if i >= 5:
            break
        status_icon = "✅" if t["status"] == "completed" else "⬜"
        time_slot = t.get("time_slot", "")
        cb_data = f"task_toggle_{t['task_id']}"
        rows.append([InlineKeyboardButton(f"{status_icon} {time_slot}", callback_data=cb_data)])

    nav_row = []
    if total > 5:
        nav_row.append(InlineKeyboardButton(f"📋 Hammasi ({total})", callback_data="task_list_full"))
    nav_row.append(InlineKeyboardButton("🔄", callback_data="task_refresh"))
    if nav_row:
        rows.append(nav_row)

    try:
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(rows),
        )
    except Exception:
        pass  # Message not modified


# ══════════════════════════════════════
#  TEXT HANDLER (registration name, late reason)
# ══════════════════════════════════════

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Umumiy matn handler — registration va late reason"""
    user_id = update.effective_user.id
    text = update.message.text

    # ── Check-in deadline ni o'zgartirish ──
    if context.user_data.get("awaiting_deadline"):
        if text.isdigit():
            val = int(text)
            if 1 <= val <= 120:
                db.set_setting("checkin_deadline_minutes", str(val))
                context.user_data.pop("awaiting_deadline", None)
                await update.message.reply_text(
                    f"✅ Check-in deadline `{val}` daqiqaga o'zgartirildi!",
                    parse_mode="Markdown",
                )
                return
        await update.message.reply_text("❌ 1-120 oralig'ida son kiriting.")
        return

    # ── Ish kunlarini o'zgartirish ──
    if context.user_data.get("awaiting_workdays"):
        parts = [x.strip() for x in text.replace(",", " ").split()]
        valid_days = []
        for p in parts:
            if p.isdigit() and 0 <= int(p) <= 6:
                valid_days.append(int(p))
            else:
                await update.message.reply_text(
                    f"❌ '{p}' noto'g'ri. 0-6 oralig'ida raqam kiriting (0=Dushanba)."
                )
                return
        if not valid_days:
            await update.message.reply_text("❌ Hech bo'lmaganda 1 kun tanlang.")
            return
        days_str = ",".join(str(d) for d in sorted(set(valid_days)))
        db.set_setting("work_days", days_str)
        context.user_data.pop("awaiting_workdays", None)
        day_names = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba",
                     "Juma", "Shanba", "Yakshanba"]
        days_list = sorted(set(valid_days))
        names = [day_names[d] for d in days_list]
        await update.message.reply_text(
            f"✅ Ish kunlari o'zgartirildi: {', '.join(names)}",
        )
        return

    # ── Kechikish sababi ──
    if user_id in pending_late_reason:
        await handle_late_reason(update, context)
        return

    # ── Ro'yxatdan o'tish: ism kiritish ──
    if context.user_data.get("awaiting_name"):
        await handle_registration_name(update, context)
        return

    # ── Xodim tugmalari ──
    emp = db.get_employee(user_id)
    if emp:
        await handle_employee_buttons(update, context)
        return

    # ── Hech narsa topilmadi ──
    await update.message.reply_text(
        "❌ Buyruq tushunarsiz. /start ni bosing."
    )


# ══════════════════════════════════════
#  ADMIN KOMANDALARI
# ══════════════════════════════════════

def admin_required(func):
    """Admin tekshiruvchi decorator"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_admin(user_id):
            await update.message.reply_text("❌ Bu buyruq faqat admin uchun.")
            return
        return await func(update, context)
    return wrapper


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bugungi davomat"""
    if not has_access(update.effective_user.id):
        return
    shift = context.args[0] if context.args and context.args[0] in ("morning", "evening") else None
    text = report.format_today_report(shift)
    await update.message.reply_text(text, parse_mode="Markdown")


async def date_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kun bo'yicha davomat"""
    if not has_access(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Format: /date YYYY-MM-DD")
        return
    text = report.format_date_report(context.args[0])
    await update.message.reply_text(text, parse_mode="Markdown")


async def week_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Haftalik davomat"""
    if not has_access(update.effective_user.id):
        return
    text = report.format_week_report()
    await update.message.reply_text(text, parse_mode="Markdown")


async def month_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Oylik davomat"""
    if not has_access(update.effective_user.id):
        return
    text = report.format_month_report()
    await update.message.reply_text(text, parse_mode="Markdown")


async def late_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kechikkanlar"""
    if not has_access(update.effective_user.id):
        return
    text = report.format_late_report()
    await update.message.reply_text(text, parse_mode="Markdown")


async def absent_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kelmaganlar"""
    if not has_access(update.effective_user.id):
        return
    shift = context.args[0] if context.args and context.args[0] in ("morning", "evening") else None
    text = report.format_missing_report(shift)
    await update.message.reply_text(text, parse_mode="Markdown")


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xodimlar ro'yxati"""
    if not has_access(update.effective_user.id):
        return
    employees = db.get_all_employees()
    if not employees:
        await update.message.reply_text("👥 Xodimlar yo'q.")
        return

    lines = ["👥 *Office Managerlar:*", ""]
    for emp in employees:
        branch = config.BRANCHES.get(emp.get("branch", ""), emp.get("branch", ""))
        branch_name = emp.get("branch", "default")
        shift_label = db.get_custom_shift_times().get(branch_name, {}).get(emp.get("shift", ""), {}).get("label", "")
        lines.append(f"  • {emp['name']} — {branch} ({shift_label})")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def add_employee_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xodim qo'shish boshlash"""
    if not has_access(update.effective_user.id):
        return
    context.user_data["add_state"] = "id"
    await update.message.reply_text(
        "Xodim qo'shish uchun ma'lumotlarni ketma-ket kiriting.\n\n"
        "1️⃣ *Telegram ID* (raqam):\n"
        "Misol: `123456789`",
        parse_mode="Markdown",
    )


async def add_employee_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xodim qo'shish matn qabul qilish"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    state = context.user_data.get("add_state", "id")

    if state == "id":
        if not text.isdigit():
            await update.message.reply_text("❌ ID raqam bo'lishi kerak. Qaytadan kiriting:")
            return
        context.user_data["add_emp_id"] = int(text)
        context.user_data["add_state"] = "name"
        await update.message.reply_text("2️⃣ *Ismi* (masalan: `Shaxzoda`):", parse_mode="Markdown")
        return

    elif state == "name":
        if len(text) > 50:
            await update.message.reply_text("❌ Ism juda uzun. Qaytadan kiriting:")
            return
        context.user_data["add_emp_name"] = text
        context.user_data["add_state"] = "branch"
        # Branch tanlash
        from config import BRANCHES
        lines = ["3️⃣ *Filialni* tanlang (raqamini yozing):"]
        for i, (key, label) in enumerate(BRANCHES.items(), 1):
            lines.append(f"  {i}. {label}")
        lines.append("")
        lines.append("Misol: `1`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    elif state == "branch":
        branch_map = list(config.BRANCHES.keys())
        if text.isdigit() and 1 <= int(text) <= len(branch_map):
            context.user_data["add_emp_branch"] = branch_map[int(text) - 1]
        elif text in branch_map:
            context.user_data["add_emp_branch"] = text
        else:
            await update.message.reply_text(f"❌ Noto'g'ri filial. 1-{len(branch_map)} oralig'ida kiriting:")
            return

        context.user_data["add_state"] = "shift"
        await update.message.reply_text(
            "4️⃣ *Smenani* tanlang:\n\n"
            "1. Ertalab (08:00-17:00)\n"
            "2. Kechki (14:00-21:00)\n\n"
            "Misol: `1`",
            parse_mode="Markdown",
        )
        return

    elif state == "shift":
        shift = None
        if text == "1":
            shift = "morning"
            shift_label = "Ertalab (08:00-17:00)"
        elif text == "2":
            shift = "evening"
            shift_label = "Kechki (14:00-21:00)"
        else:
            await update.message.reply_text("❌ 1 yoki 2 kiriting:")
            return

        # Xodimni qo'shish
        emp_id = context.user_data["add_emp_id"]
        name = context.user_data["add_emp_name"]
        branch = context.user_data["add_emp_branch"]

        success = db.add_employee(emp_id, name, role="office_manager", branch=branch, shift=shift)
        if success:
            # Default tasklarni o'rnatish (smena bo'yicha)
            default_tasks = config.DEFAULT_TASKS.get(shift, [])
            if default_tasks:
                db.set_employee_tasks(emp_id, default_tasks)

            branch_label = config.BRANCHES.get(branch, branch)
            await update.message.reply_text(
                f"✅ *Xodim qo'shildi!*\n\n"
                f"👤 {name}\n🆔 {emp_id}\n📍 {branch_label}\n🕐 {shift_label}",
                parse_mode="Markdown",
            )

            # Sheets ga qo'shish
            emp = db.get_employee(emp_id)
            if emp:
                sheets.sync_employee_to_sheets(emp)
        else:
            await update.message.reply_text("❌ Xatolik yuz berdi.")

        # Tozalash
        context.user_data.pop("add_state", None)
        context.user_data.pop("add_emp_id", None)
        context.user_data.pop("add_emp_name", None)
        context.user_data.pop("add_emp_branch", None)
        return


async def remove_employee_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xodim o'chirish"""
    if not has_access(update.effective_user.id):
        return
    if context.args:
        try:
            emp_id = int(context.args[0])
            emp = db.get_employee(emp_id)
            if emp:
                db.remove_employee(emp_id)
                await update.message.reply_text(f"✅ {emp['name']} o'chirildi.")
            else:
                await update.message.reply_text("❌ Xodim topilmadi.")
        except ValueError:
            await update.message.reply_text("❌ ID raqam bo'lishi kerak.")
    else:
        # Xodimlar ro'yxatini ko'rsatish
        employees = db.get_all_employees()
        if not employees:
            await update.message.reply_text("👥 Xodimlar yo'q.")
            return
        lines = ["Xodimni tanlang (ID sini yozing):", ""]
        for emp in employees:
            lines.append(f"  {emp['telegram_id']} — {emp['name']}")
        lines.append("")
        lines.append("Misol: /remove 123456789")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bugungi tasklar holati (admin uchun)"""
    if not has_access(update.effective_user.id):
        return
    text = report.format_all_tasks_report()
    await update.message.reply_text(text, parse_mode="Markdown")


async def task_week_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Haftalik task statistikasi"""
    if not has_access(update.effective_user.id):
        return
    text = report.format_task_completion_week()
    await update.message.reply_text(text, parse_mode="Markdown")


async def setup_tasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tasklarni sozlash (admin)"""
    if not has_access(update.effective_user.id):
        return
    text = "📝 *Tasklarni sozlash*\n\n"
    text += "Quyidagi smenalar uchun default tasklarni o'rnatishingiz mumkin:\\n"
    shift_labels = {"morning": "☀️ Ertalab (08:00-17:00)", "evening": "🌙 Kechki (14:00-21:00)"}
    for key in config.DEFAULT_TASKS:
        label = shift_labels.get(key, key.capitalize())
        text += f"  • {label}\\n"
    text += "\nTugmalardan foydalaning:"
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=kb.admin_task_management_keyboard(),
    )


async def handle_registration_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ro'yxatdan o'tish: ism kiritish"""
    user_id = update.effective_user.id
    text = update.message.text
    name = text.strip()
    if not name or len(name) > 50:
        await update.message.reply_text("❌ Iltimos, to'g'ri ism kiriting.")
        return

    branch = context.user_data.get("reg_branch", "online")
    shift = context.user_data.get("reg_shift", "morning")

    # Self-registration: admin tasdiqlashi kerak (active=0)
    db.register_pending_employee(user_id, name, role="office_manager", branch=branch, shift=shift)

    # Default tasklarni o'rnatish (smena bo'yicha) — tasdiqlanganda ochiladi
    default_tasks = config.DEFAULT_TASKS.get(shift, [])
    if default_tasks:
        db.set_employee_tasks(user_id, default_tasks)

    branch_label = config.BRANCHES.get(branch, branch)

    context.user_data.pop("awaiting_name", None)
    context.user_data.pop("reg_branch", None)
    context.user_data.pop("reg_shift", None)

    # Adminlarga xabar yuborish
    await update.message.reply_text(
        f"✅ *Ma'lumotlaringiz qabul qilindi!*\n\n"
        f"📍 {branch_label}\n"
        f"👤 {name}\n\n"
        "Admin tasdiqlashidan so'ng tizimga kirasiz. Kuting...",
        parse_mode="Markdown",
    )

    # Adminlarga xabar
    for admin_id in config.ADMIN_IDS:
        try:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"apr_{user_id}"),
                 InlineKeyboardButton("❌ Rad etish", callback_data=f"rej_{user_id}")],
            ])
            await context.bot.send_message(
                admin_id,
                f"🆕 *Yangi xodim tasdiqlanishi kutilmoqda*\n\n"
                f"👤 {name}\n"
                f"📍 {branch_label}\n"
                f"🆔 {user_id}\n\n"
                f"Quyidagi tugmalar orqali tasdiqlang:",
                parse_mode="Markdown",
                reply_markup=kb,
            )
        except Exception:
            pass
    return
# ══════════════════════════════════════
#  ADMIN TUGMALARI
# ══════════════════════════════════════

async def handle_admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # ── Video qoidabuzarlik sababini qabul qilish ──
    if context.user_data.get("awaiting_violation_reason"):
        reason = text.strip()
        context.user_data.pop("awaiting_violation_reason", None)
        logger.warning(f"⚠️ Qoidabuzarlik sababi: user_id={user_id}, reason='{reason}'")
        await update.message.reply_text(
            f"✅ Sabab qayd etildi. Endi jonli video yuboring!",
            parse_mode="Markdown",
        )
        return

    # ── "Bajara olmayman" sababini qabul qilish ──
    if user_id in pending_task_reason:
        task_id = pending_task_reason.pop(user_id)
        reason = text.strip()
        # Sababni saqlash
        try:
            await update.message.reply_text(
                f"❌ Sabab qayd etildi: *{reason}*",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Task reason save error: {e}")
        return

    # ── Admin task tahrirlash ──
    if context.user_data.get("awaiting_task_edit"):
        task_id = context.user_data.pop("editing_task_id", None)
        context.user_data.pop("awaiting_task_edit", None)
        if not task_id:
            await update.message.reply_text("❌ Xatolik: task topilmadi.")
            return

        new_text = text.strip()
        success = db.update_employee_task(task_id, new_text)
        if success:
            await update.message.reply_text(
                f"✅ *Task yangilandi!*\n\n{new_text}",
                parse_mode="Markdown",
                reply_markup=kb.admin_keyboard(),
            )
        else:
            await update.message.reply_text(
                "❌ Xatolik yuz berdi.",
                reply_markup=kb.admin_keyboard(),
            )
        return

    # ── Xodim qo'shish (admin) ──
    if context.user_data.get("add_state"):
        await add_employee_text(update, context)
        return

    # ── Ro'yxatdan o'tish: filial tanlash ──
    if context.user_data.get("reg_state") == "branch":
        branch = None
        for key, label in config.BRANCHES.items():
            if label in text or key in text.lower():
                branch = key
                break
        if not branch:
            await update.message.reply_text("❌ Iltimos, filialni tugmalardan tanlang.")
            return
        context.user_data["reg_branch"] = branch
        context.user_data["reg_state"] = "shift"
        await update.message.reply_text(
            "Smenani tanlang:",
            reply_markup=kb.registration_shifts_keyboard(),
        )
        return

    # ── Ro'yxatdan o'tish: smena tanlash ──
    if context.user_data.get("reg_state") == "shift":
        shift = None
        if "ertalab" in text.lower():
            shift = "morning"
        elif "kechki" in text.lower():
            shift = "evening"
        if not shift:
            await update.message.reply_text("❌ Iltimos, smenani tugmalardan tanlang.")
            return
        context.user_data["reg_shift"] = shift
        branch = context.user_data.get("reg_branch", "online")
        shift_label = db.get_custom_shift_times().get(branch, {}).get(shift, {}).get("label", shift)
        context.user_data.pop("reg_state", None)
        context.user_data["awaiting_name"] = True
        await update.message.reply_text(
            f"📍 {config.BRANCHES.get(branch, branch)}\n"
            f"🕐 {shift_label}\n\n"
            "Iltimos, *ismingizni* yozib yuboring:",
            parse_mode="Markdown",
        )
        return

    # ── Ro'yxatdan o'tish (ism kiritish) har doim ishlashi kerak ──
    if context.user_data.get("awaiting_name"):
        await handle_registration_name(update, context)
        return

    if not has_access(user_id):
        # Xodim tugmalariga o'tkazish
        await handle_employee_buttons(update, context)
        return

    if text == "📊 Bugungi davomat":
        await today_cmd(update, context)
    elif text == "📋 Bugungi tasklar":
        await tasks_cmd(update, context)
    elif text == "❌ Kelmaganlar":
        await absent_cmd(update, context)
    elif text == "⏰ Kechikkanlar":
        await late_cmd(update, context)
    elif text == "📅 Haftalik hisobot":
        await week_cmd(update, context)
    elif text == "📆 Oylik hisobot":
        await month_cmd(update, context)
    elif text == "👥 Xodimlar ro'yxati":
        await list_cmd(update, context)
    elif text == "➕ Xodim qo'shish":
        await add_employee_start(update, context)
    elif text == "➖ Xodim o'chirish":
        await remove_employee_cmd(update, context)
    elif text == "📋 Tasklarni sozlash":
        await setup_tasks_cmd(update, context)
    elif text == "⏰ Ish vaqtini sozlash":
        await work_time_settings_menu(update, context)
    else:
        # Xodim tugmalari
        await handle_employee_buttons(update, context)


# ══════════════════════════════════════
#  WORK TIME SETTINGS
# ══════════════════════════════════════

async def work_time_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ish vaqtini sozlash menyusini ko'rsatish"""
    settings = db.get_custom_shift_times()
    ms_d = settings["default"]["morning"]
    es_d = settings["default"]["evening"]
    ms_o = settings["online"]["morning"]
    es_o = settings["online"]["evening"]
    dl = settings["checkin_deadline_minutes"]
    days = settings["work_days"]
    day_count = len(days)

    text = (
        "⏰ *Ish vaqti sozlamalari*\n\n"
        "*🏢 Integro / AT / XD / Central*\n"
        f"🌅 Ertalab: {ms_d['start']:02d}:00 - {ms_d['end']:02d}:00\n"
        f"🌆 Kechki: {es_d['start']:02d}:00 - {es_d['end']:02d}:00\n\n"
        "*🏡 Online*\n"
        f"🌅 Ertalab: {ms_o['start']:02d}:00 - {ms_o['end']:02d}:00\n"
        f"🌆 Kechki: {es_o['start']:02d}:00 - {es_o['end']:02d}:00\n\n"
        f"⏱ *Check-in deadline:* {dl} daqiqa\n"
        f"📅 *Ish kunlari:* {day_count}/7\n\n"
        "O'zgartirish uchun tugmalardan foydalaning:"
    )
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=kb.work_time_settings_keyboard(),
    )


async def show_wts_menu(query):
    """WTS menyusini callback sifatida ko'rsatish"""
    settings = db.get_custom_shift_times()
    ms_d = settings["default"]["morning"]
    es_d = settings["default"]["evening"]
    ms_o = settings["online"]["morning"]
    es_o = settings["online"]["evening"]
    dl = settings["checkin_deadline_minutes"]
    days = settings["work_days"]
    day_count = len(days)

    text = (
        "⏰ *Ish vaqti sozlamalari*\n\n"
        "*🏢 Integro / AT / XD / Central*\n"
        f"🌅 Ertalab: {ms_d['start']:02d}:00 - {ms_d['end']:02d}:00\n"
        f"🌆 Kechki: {es_d['start']:02d}:00 - {es_d['end']:02d}:00\n\n"
        "*🏡 Online*\n"
        f"🌅 Ertalab: {ms_o['start']:02d}:00 - {ms_o['end']:02d}:00\n"
        f"🌆 Kechki: {es_o['start']:02d}:00 - {es_o['end']:02d}:00\n\n"
        f"⏱ *Check-in deadline:* {dl} daqiqa\n"
        f"📅 *Ish kunlari:* {day_count}/7\n\n"
        "O'zgartirish uchun tugmalardan foydalaning:"
    )
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=kb.work_time_settings_keyboard(),
    )


def adj_shift_hour(shift_key: str, field: str, delta: int, query):
    """Shift soatini o'zgartirish (callback_data da saqlanadi)"""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    # Map shift_key -> branch + shift
    is_online = shift_key.startswith("online_")
    branch_key = "online" if is_online else "default"
    inner_shift = shift_key.replace("online_", "") if is_online else shift_key
    db_prefix = "online_" if is_online else "shift_"

    # DB key name
    db_key = f"{db_prefix}{inner_shift}_{field}"

    # Hozirgi qiymatni DB dan olish
    settings = db.get_custom_shift_times()
    current = settings[branch_key][inner_shift][field]
    new_hour = (current + delta) % 24

    shift_label = "🌅 Ertalab" if inner_shift == "morning" else "🌆 Kechki"
    branch_label = " (Online)" if is_online else " (Integro/AT/XD/Central)"
    status_text = (
        f"{shift_label}{branch_label}\n\n"
        f"{'Boshlanishi' if field == 'start' else 'Tugashi'}: `{new_hour:02d}:00`\n\n"
        "Tugmalar bilan soatni o'zgartiring, keyin *✅ Saqlash* ni bosing."
    )

    # DB ga darhol yozish
    db.set_setting(db_key, str(new_hour))

    try:
        query.edit_message_text(
            status_text,
            parse_mode="Markdown",
            reply_markup=kb.shift_edit_keyboard(shift_key),
        )
    except Exception:
        pass


def show_shift_current(query, shift_key: str, field: str):
    """Hozirgi qiymatni ko'rsatish"""
    is_online = shift_key.startswith("online_")
    branch_key = "online" if is_online else "default"
    inner_shift = shift_key.replace("online_", "") if is_online else shift_key
    settings = db.get_custom_shift_times()
    current = settings[branch_key][inner_shift][field]
    label = "Boshlanishi" if field == "start" else "Tugashi"
    try:
        query.answer(f"{label}: {current:02d}:00", show_alert=True)
    except Exception:
        pass


async def save_shift(query, shift_key: str):
    """Shift sozlamalarini saqlash va tasdiqlash"""
    is_online = shift_key.startswith("online_")
    branch_key = "online" if is_online else "default"
    inner_shift = shift_key.replace("online_", "") if is_online else shift_key
    settings = db.get_custom_shift_times()
    s = settings[branch_key][inner_shift]
    shift_label = "🌅 Ertalab" if inner_shift == "morning" else "🌆 Kechki"
    branch_label = " (Online)" if is_online else " (Integro/AT/XD/Central)"
    await query.edit_message_text(
        f"✅ *{shift_label}{branch_label} saqlandi!*\n\n"
        f"Boshlanishi: `{s['start']:02d}:00`\n"
        f"Tugashi: `{s['end']:02d}:00`\n\n"
        "O'zgartirishlar darhol amal qiladi.",
        parse_mode="Markdown",
        reply_markup=kb.work_time_settings_keyboard(),
    )


# ══════════════════════════════════════
#  ERROR HANDLER
# ══════════════════════════════════════

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")


# ══════════════════════════════════════
#  DAILY REMINDER
# ══════════════════════════════════════

async def morning_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Ertalabki eslatma — morning shift xodimlariga"""
    morning_emps = db.get_employees_by_shift("morning")
    for emp in morning_emps:
        try:
            await context.bot.send_message(
                emp["telegram_id"],
                "🌅 *Xayrli tong!*\n\n"
                "Bugungi smenangiz boshlandi (08:00).\n"
                "Check-in uchun *video* yuboring!",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Morning reminder error {emp['telegram_id']}: {e}")


async def evening_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Kechki eslatma — evening shift xodimlariga"""
    evening_emps = db.get_employees_by_shift("evening")
    for emp in evening_emps:
        try:
            await context.bot.send_message(
                emp["telegram_id"],
                "🌆 *Xayrli kech!*\n\n"
                "Kechki smenangiz boshlandi (14:00).\n"
                "Check-in uchun *video* yuboring!",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Evening reminder error {emp['telegram_id']}: {e}")


async def check_out_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Check-out eslatmasi"""
    all_emps = db.get_all_employees()
    now = datetime.now(tz)
    for emp in all_emps:
        if db.is_checked_in(emp["telegram_id"]) and not db.is_checked_out(emp["telegram_id"]):
            try:
                await context.bot.send_message(
                    emp["telegram_id"],
                    "⏰ *Smena tugashiga 1 soat qoldi!*\n\n"
                    "Check-out qilishni unutmang!",
                    parse_mode="Markdown",
                )
            except Exception:
                pass


# ══════════════════════════════════════
#  TASK VAQTI ESMATLARI + TUGMALAR
# ══════════════════════════════════════

# Duplicate eslatmalarni oldini olish: DB da saqlanadi
# (reminder_key -> sent_at) - restartda takrorlanmasligi uchun

# "Bajara olmayman" sabab kutayotgan xodimlar: {user_id: task_id}
pending_task_reason = {}

async def task_time_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Task vaqti kelganda xodimga avtomatik eslatma + tugmalar
    Har 60 sekundda ishlaydi, lekin bir taskni 10 daqiqada 1 marta eslatadi"""
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    now_ts = now.timestamp()

    all_emps = db.get_all_employees()
    for emp in all_emps:
        user_id = emp["telegram_id"]
        tasks = db.get_today_tasks(user_id)
        for t in tasks:
            if t["status"] == "completed":
                continue

            time_slot = t.get("time_slot", "")
            if not time_slot or "-" not in time_slot:
                continue

            start_time_str = time_slot.split("-")[0].strip()
            end_time_str = time_slot.split("-")[1].strip()

            # Vaqtni parse qilish
            try:
                sh, sm = map(int, start_time_str.split(":"))
                eh, em = map(int, end_time_str.split(":"))
                task_start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                task_end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
                if task_end <= task_start:  # Yarrim kechadan o'tuvchi task (masalan 22:00-00:00)
                    task_end += timedelta(days=1)
            except (ValueError, IndexError):
                continue

            # Hali vaqti kelmagan bo'lsa o'tkazib yuboramiz
            if now < task_start:
                continue

            # Task vaqti tugagan bo'lsa o'tkazib yuboramiz
            if now > task_end:
                continue

            reminder_key = f"{today_str}_{user_id}_{t['task_id']}"
            last_sent = db.get_task_reminder(reminder_key)

            # 10 daqiqadan kam bo'lsa o'tkazib yuboramiz (600 sekund)
            if now_ts - last_sent < 600:
                continue

            db.set_task_reminder(reminder_key, now_ts)

            task_text = t.get("task_text", "")
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Bajarishni boshladim", callback_data=f"task_started_{t['task_id']}")],
                [InlineKeyboardButton("❌ Bajara olmayman", callback_data=f"task_cant_do_{t['task_id']}")],
            ])
            try:
                await context.bot.send_message(
                    user_id,
                    f"⏰ *Task vaqti!*\n\n"
                    f"🕐 *{time_slot}*\n"
                    f"📝 {task_text}\n\n"
                    f"Quyidagilardan birini tanlang:",
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
            except Exception as e:
                logger.error(f"Task reminder error {user_id}: {e}")


# ══════════════════════════════════════
#  MAIN
# ══════════════════════════════════════

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add flow ni bekor qilish"""
    context.user_data.pop("add_state", None)
    context.user_data.pop("add_emp_id", None)
    context.user_data.pop("add_emp_name", None)
    context.user_data.pop("add_emp_branch", None)
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=kb.admin_keyboard())


def main():
    # DB ni initializatsiya
    db.init_db()

    token = config.BOT_TOKEN
    if not token:
        logger.error("BOT_TOKEN topilmadi! .env faylini tekshiring.")
        return

    app = Application.builder().token(token).build()

    # ── Handlers ──
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # Admin komandalari
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("date", date_cmd))
    app.add_handler(CommandHandler("week", week_cmd))
    app.add_handler(CommandHandler("month", month_cmd))
    app.add_handler(CommandHandler("late", late_cmd))
    app.add_handler(CommandHandler("absent", absent_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("add", add_employee_start))
    app.add_handler(CommandHandler("remove", remove_employee_cmd))
    app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(CommandHandler("taskweek", task_week_cmd))

    # Video handler
    app.add_handler(MessageHandler(
        filters.VIDEO | filters.VIDEO_NOTE,
        handle_video
    ))

    # Callback query handler
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Text handler (eng oxirgi)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_buttons))

    # Error handler
    app.add_error_handler(error_handler)

    # ── Job queue: Eslatmalar ──
    job_q = app.job_queue

    # Ertalabki eslatma (07:50)
    job_q.run_daily(
        morning_reminder,
        time=datetime.strptime("07:50", "%H:%M").time(),
        name="morning_reminder",
    )

    # Kechki eslatma (13:50)
    job_q.run_daily(
        evening_reminder,
        time=datetime.strptime("13:50", "%H:%M").time(),
        name="evening_reminder",
    )

    # Check-out eslatma (morning: 14:00, evening: 00:00)
    job_q.run_daily(
        check_out_reminder,
        time=datetime.strptime("14:00", "%H:%M").time(),
        name="checkout_reminder_morning",
    )
    job_q.run_daily(
        check_out_reminder,
        time=datetime.strptime("00:00", "%H:%M").time(),
        name="checkout_reminder_evening",
    )

    # Task vaqti eslatmasi (har daqiqada tekshiradi)
    job_q.run_repeating(
        task_time_reminder,
        interval=60,
        first=10,
        name="task_time_reminder",
    )

    logger.info("🤖 Office Manager Bot ishga tushdi!")

    # Google Sheets dan xodimlarni sinxronlash (startup da)
    if sheets.get_client():
        # 1. Mavjud xodimlarni Sheets ga yozish
        local_emps = db.get_all_employees()
        if local_emps:
            synced_count = 0
            for emp in local_emps:
                if sheets.sync_employee_to_sheets(emp):
                    synced_count += 1
            logger.info(f"[Startup] {synced_count}/{len(local_emps)} xodim Sheets ga yozildi")

        # 2. Adminlarni ham employee qilib qo'shish (agar yo'q bo'lsa)
        admin_names = {1054482233: "Karimboy", 909473085: "Ziyoda"}
        for admin_id in config.ADMIN_IDS:
            if not db.get_employee(admin_id):
                name = admin_names.get(admin_id, f"Admin {admin_id}")
                db.add_employee(admin_id, name, role="office_manager", branch="integro", shift="morning")
                logger.info(f"[Startup] Admin {name} (ID: {admin_id}) employee ga qo'shildi")
                emp = db.get_employee(admin_id)
                if emp:
                    sheets.sync_employee_to_sheets(emp)

        # 3. Sheets dan xodimlarni o'qib, DB ni to'ldirish
        synced = sheets.get_employees_from_sheets()
        if synced:
            for emp in synced:
                existing = db.get_employee(emp["telegram_id"])
                if not existing:
                    db.add_employee(
                        emp["telegram_id"],
                        emp["name"],
                        role=emp.get("role", "office_manager"),
                        branch=emp.get("branch", "integro"),
                        shift=emp.get("shift", "morning"),
                    )
                    logger.info(f"[Startup] Xodim Sheets dan qo'shildi: {emp['name']} (ID: {emp['telegram_id']})")
            logger.info(f"[Startup] Sheets dan {len(synced)} ta xodim sinxronlandi")
        else:
            logger.info("[Startup] Sheets da xodimlar topilmadi")
    else:
        logger.info("[Startup] Google Sheets ulanishi yo'q")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
