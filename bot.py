import os
import json
from datetime import datetime, time, timedelta
import pytz
import telebot
from telebot import types
import gspread
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.background import BackgroundScheduler
import uuid
from dotenv import load_dotenv

load_dotenv()

# ── Environment ──
TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SHEET_KEY")
GROUP_ID = os.getenv("GROUP_ID", "0")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_CREDENTIALS_B64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_B64", "")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "1054482233")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

if not TOKEN or not SPREADSHEET_ID or not GROUP_ID:
    print("Error: BOT_TOKEN, SHEET_KEY, GROUP_ID required")
    exit(1)

# ── Constants ──
TIMEZONE = pytz.timezone("Asia/Tashkent")
GROUP_ID_INT = int(GROUP_ID)

POSITIONS = ["Office Manager", "Cashier", "Online Office Manager", "Academic Support"]

BRANCHES = {
    "integro": "Integro",
    "amir_temur": "Amir Temur",
    "xalqlar": "Xalqlar Do'stligi",
    "online": "Online",
}

SHIFTS = {
    "morning": {"start": 8, "end": 17, "label": "Ertalab (08:00-17:00)"},
    "evening": {"start": 14, "end": 21, "label": "Kechki (14:00-21:00)"},
}

SHIFT_MORNING_START = time(8, 0, tzinfo=TIMEZONE)
SHIFT_MORNING_END = time(17, 0, tzinfo=TIMEZONE)
SHIFT_EVENING_START = time(14, 0, tzinfo=TIMEZONE)
SHIFT_EVENING_END = time(21, 0, tzinfo=TIMEZONE)
AUTO_CHECKOUT_TIME = time(0, 0, tzinfo=TIMEZONE)

# ── Google Sheets ──
gc = None
davomat_ws = None
foydalanuvchilar_ws = None
tasklar_ws = None
ranking_ws = None

def init_sheets():
    global gc, davomat_ws, foydalanuvchilar_ws, tasklar_ws, ranking_ws
    try:
        creds = None
        scope = ["https://www.googleapis.com/auth/spreadsheets"]

        if GOOGLE_CREDENTIALS_B64:
            import base64
            creds = Credentials.from_service_account_info(
                json.loads(base64.b64decode(GOOGLE_CREDENTIALS_B64).decode()), scopes=scope
            )
        elif GOOGLE_CREDENTIALS_JSON:
            if os.path.isfile(GOOGLE_CREDENTIALS_JSON):
                creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_JSON, scopes=scope)
            else:
                creds = Credentials.from_service_account_info(json.loads(GOOGLE_CREDENTIALS_JSON), scopes=scope)
        else:
            print("[Sheets] No credentials found")
            return False

        gc = gspread.authorize(creds)
        ss = gc.open_by_key(SPREADSHEET_ID)

        for ws_name in ["Davomat", "Foydalanuvchilar", "Tasklar", "Ranking"]:
            try:
                ws = ss.worksheet(ws_name)
            except:
                ws = ss.add_worksheet(title=ws_name, rows=100, cols=20)
                if ws_name == "Davomat":
                    ws.append_row(["Sana", "Ism", "Lavozim", "Filial", "Smena", "Kirish vaqti", "Chiqish vaqti", "Kirish video", "Chiqish video", "chat_id"])
                elif ws_name == "Foydalanuvchilar":
                    ws.append_row(["chat_id", "Ism", "Lavozim", "Filial", "Smena", "Holat", "Tasdiqlangan vaqt"])
                elif ws_name == "Tasklar":
                    ws.append_row(["Yaratilgan vaqt", "ID", "Vazifa nomi", "Turi", "Hodimlar(chat_id)", "Muddat", "Holat"])
                elif ws_name == "Ranking":
                    ws.append_row(["Sana", "chat_id", "Ism", "Lavozim", "Kelish vaqti", "Ball"])

        davomat_ws = ss.worksheet("Davomat")
        foydalanuvchilar_ws = ss.worksheet("Foydalanuvchilar")
        tasklar_ws = ss.worksheet("Tasklar")
        ranking_ws = ss.worksheet("Ranking")
        return True
    except Exception as e:
        print(f"[Sheets] init error: {e}")
        return False

# ── Bot ──
bot = telebot.TeleBot(TOKEN)
scheduler = BackgroundScheduler(timezone=TIMEZONE)
user_states = {}

# ── Helper Functions ──
def is_admin(chat_id):
    return chat_id in ADMIN_IDS

def get_all_users():
    try:
        return foydalanuvchilar_ws.get_all_records()
    except:
        return []

def get_user_by_chat_id(chat_id):
    users = get_all_users()
    for u in users:
        if str(u.get("chat_id")) == str(chat_id):
            return u
    return None

def add_new_user(chat_id, name, position, branch="integro"):
    try:
        foydalanuvchilar_ws.append_row([str(chat_id), name, position, branch, "", "Kutilmoqda", ""])
        return True
    except:
        return False

def update_user_status(chat_id, status, shift=""):
    try:
        cell = foydalanuvchilar_ws.find(str(chat_id), in_column=1)
        if cell:
            foydalanuvchilar_ws.update_cell(cell.row, 6, status)
            if shift:
                foydalanuvchilar_ws.update_cell(cell.row, 5, shift)
            if status == "Tasdiqlangan":
                foydalanuvchilar_ws.update_cell(cell.row, 7, datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S"))
            return True
        return False
    except:
        return False

def record_check_in(chat_id, name, position, branch, shift, check_in_time, video_id):
    try:
        davomat_ws.append_row([
            check_in_time.strftime("%Y-%m-%d"), name, position, branch, shift,
            check_in_time.strftime("%H:%M:%S"), "", video_id, "", str(chat_id)
        ])
        return True
    except:
        return False

def record_check_out(chat_id, check_out_time, video_id):
    try:
        today = check_out_time.strftime("%Y-%m-%d")
        records = davomat_ws.get_all_records()
        for i, row in enumerate(records):
            if str(row.get("chat_id")) == str(chat_id) and row.get("Sana") == today and not row.get("Chiqish vaqti"):
                davomat_ws.update_cell(i + 2, 7, check_out_time.strftime("%H:%M:%S"))
                davomat_ws.update_cell(i + 2, 9, video_id)
                return True
        return False
    except:
        return False

def get_today_attendance(chat_id):
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    records = davomat_ws.get_all_records()
    for row in records:
        if str(row.get("chat_id")) == str(chat_id) and row.get("Sana") == today:
            return row
    return None

def get_all_attendance_today():
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    records = davomat_ws.get_all_records()
    return [r for r in records if r.get("Sana") == today]

def calculate_ranking_score(arrival_time):
    shift_start_dt = arrival_time.replace(hour=8, minute=0, second=0, microsecond=0)
    if arrival_time <= shift_start_dt:
        return 100
    late_minutes = (arrival_time - shift_start_dt).total_seconds() / 60
    if late_minutes >= 30:
        return 0
    return max(0, round(100 - (late_minutes / 30) * 100))

def record_ranking(date, chat_id, name, position, arrival_time_str, score):
    try:
        records = ranking_ws.get_all_records()
        for i, row in enumerate(records):
            if row.get("Sana") == date and str(row.get("chat_id")) == str(chat_id):
                ranking_ws.update_cell(i + 2, 6, score)
                return True
        ranking_ws.append_row([date, str(chat_id), name, position, arrival_time_str, score])
        return True
    except:
        return False

def get_daily_ranking(date_str):
    records = ranking_ws.get_all_records()
    daily = [r for r in records if r.get("Sana") == date_str]
    daily.sort(key=lambda x: x.get("Ball", 0), reverse=True)
    return daily

def get_overall_ranking():
    records = ranking_ws.get_all_records()
    scores = {}
    for row in records:
        cid = row.get("chat_id")
        s = row.get("Ball", 0)
        if cid not in scores:
            scores[cid] = {"Ism": row.get("Ism"), "Lavozim": row.get("Lavozim"), "total": 0, "count": 0}
        scores[cid]["total"] += s
        scores[cid]["count"] += 1
    overall = []
    for cid, data in scores.items():
        if data["count"] > 0:
            overall.append({"chat_id": cid, "Ism": data["Ism"], "Lavozim": data["Lavozim"], "Ball": round(data["total"] / data["count"], 2)})
    overall.sort(key=lambda x: x.get("Ball", 0), reverse=True)
    return overall

# ── Keyboards ──
def employee_kb():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("💼 Ishga keldim"),
        types.KeyboardButton("🚪 Ishdan ketdim"),
        types.KeyboardButton("📝 Mening vazifalarim"),
        types.KeyboardButton("🏆 Reytingim"),
    )
    return markup

def admin_kb():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("💼 Ishga keldim"),
        types.KeyboardButton("🚪 Ishdan ketdim"),
        types.KeyboardButton("✅ Foydalanuvchilarni boshqarish"),
        types.KeyboardButton("➕ Vazifa yaratish"),
        types.KeyboardButton("📋 Vazifalarni ko'rish"),
        types.KeyboardButton("👥 Xodimlar faoliyati"),
        types.KeyboardButton("📊 Reytinglar"),
        types.KeyboardButton("📈 Hisobotlar"),
    )
    return markup

def positions_kb():
    markup = types.InlineKeyboardMarkup(row_width=1)
    for pos in POSITIONS:
        markup.add(types.InlineKeyboardButton(pos, callback_data=f"reg_pos_{pos}"))
    return markup

def approval_kb(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"apr_{chat_id}"),
        types.InlineKeyboardButton("❌ Rad etish", callback_data=f"rej_{chat_id}"),
    )
    return markup

def shift_kb(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("☀️ Ertalab (08:00-17:00)", callback_data=f"shift_{chat_id}_morning"),
        types.InlineKeyboardButton("🌙 Kechki (14:00-21:00)", callback_data=f"shift_{chat_id}_evening"),
    )
    return markup

def proof_type_kb():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Foto", callback_data="proof_photo"),
        types.InlineKeyboardButton("Video", callback_data="proof_video"),
        types.InlineKeyboardButton("Matn", callback_data="proof_text"),
        types.InlineKeyboardButton("Hech biri", callback_data="proof_none"),
    )
    return markup

# ── Handlers ──
@bot.message_handler(commands=["start"])
def cmd_start(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)

    if user:
        if user.get("Holat") == "Tasdiqlangan":
            if is_admin(chat_id):
                bot.send_message(chat_id, "Assalomu alaykum, admin!", reply_markup=admin_kb())
            else:
                bot.send_message(chat_id, "Assalomu alaykum, xodim!", reply_markup=employee_kb())
        elif user.get("Holat") == "Kutilmoqda":
            bot.send_message(chat_id, "Arizangiz ko'rib chiqilmoqda. Admin tasdiqlashini kuting.")
        else:
            bot.send_message(chat_id, "Arizangiz rad etilgan. Admin bilan bog'laning.")
    else:
        user_states[chat_id] = {"state": "waiting_for_name"}
        bot.send_message(chat_id, "Assalomu alaykum! Ismingizni kiriting:")

@bot.message_handler(func=lambda m: user_states.get(m.chat.id, {}).get("state") == "waiting_for_name")
def handle_name(message):
    chat_id = message.chat.id
    user_states[chat_id]["name"] = message.text
    user_states[chat_id]["state"] = "waiting_for_position"
    bot.send_message(chat_id, "Lavozimingizni tanlang:", reply_markup=positions_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("reg_pos_"))
def handle_position(call):
    chat_id = call.message.chat.id
    if user_states.get(chat_id, {}).get("state") != "waiting_for_position":
        bot.answer_callback_query(call.id)
        return
    position = call.data.replace("reg_pos_", "")
    name = user_states[chat_id]["name"]

    if add_new_user(chat_id, name, position):
        bot.edit_message_text(
            chat_id=chat_id, message_id=call.message.message_id,
            text=f"Arizangiz qabul qilindi:\nIsm: {name}\nLavozim: {position}\n\nAdmin tasdiqlashini kuting."
        )
        for admin_id in ADMIN_IDS:
            bot.send_message(
                admin_id,
                f"🆕 *Yangi xodim*\n\nIsm: {name}\nLavozim: {position}\nID: {chat_id}",
                parse_mode="Markdown",
                reply_markup=approval_kb(chat_id),
            )
    else:
        bot.send_message(chat_id, "Xatolik yuz berdi. Qayta urinib ko'ring.")
    user_states.pop(chat_id, None)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("apr_"))
def handle_approve(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Ruxsat yo'q!")
        return
    user_chat_id = int(call.data.replace("apr_", ""))
    user = get_user_by_chat_id(user_chat_id)
    if not user:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Foydalanuvchi topilmadi.")
        bot.answer_callback_query(call.id)
        return
    bot.edit_message_text(
        chat_id=call.message.chat.id, message_id=call.message.message_id,
        text=f"{user['Ism']} ({user['Lavozim']}) uchun smenani tanlang:",
        reply_markup=shift_kb(user_chat_id),
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rej_"))
def handle_reject(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Ruxsat yo'q!")
        return
    user_chat_id = int(call.data.replace("rej_", ""))
    user = get_user_by_chat_id(user_chat_id)
    if not user:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Foydalanuvchi topilmadi.")
        bot.answer_callback_query(call.id)
        return
    update_user_status(user_chat_id, "Rad etilgan")
    bot.edit_message_text(
        chat_id=call.message.chat.id, message_id=call.message.message_id,
        text=f"{user['Ism']} ({user['Lavozim']}) rad etildi."
    )
    bot.send_message(user_chat_id, "Arizangiz rad etildi. Admin bilan bog'laning.")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("shift_"))
def handle_shift(call):
    if not is_admin(call.message.chat.id):
        bot.answer_callback_query(call.id, "Ruxsat yo'q!")
        return
    parts = call.data.split("_")
    user_chat_id = int(parts[1])
    shift = parts[2]
    user = get_user_by_chat_id(user_chat_id)
    if not user:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Foydalanuvchi topilmadi.")
        bot.answer_callback_query(call.id)
        return
    shift_label = SHIFTS[shift]["label"] if shift in SHIFTS else shift
    if update_user_status(user_chat_id, "Tasdiqlangan", shift):
        bot.edit_message_text(
            chat_id=call.message.chat.id, message_id=call.message.message_id,
            text=f"{user['Ism']} ({user['Lavozim']}) tasdiqlandi — {shift_label}"
        )
        bot.send_message(
            user_chat_id,
            f"✅ Tasdiqlandingiz! Smena: {shift_label}\n\n/start bosib ishga kirishingiz mumkin.",
            reply_markup=employee_kb(),
        )
    bot.answer_callback_query(call.id)

# ── Check-in / Check-out ──
@bot.message_handler(func=lambda m: m.text == "💼 Ishga keldim")
def check_in_button(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)
    if not user or user.get("Holat") != "Tasdiqlangan":
        bot.send_message(chat_id, "Ro'yxatdan o'tmagan yoki tasdiqlanmagansiz. /start bosing.")
        return
    today = get_today_attendance(chat_id)
    if today and today.get("Kirish vaqti"):
        bot.send_message(chat_id, "Bugun allaqachon ishga kelganingiz qayd etilgan.")
        return
    user_states[chat_id] = {"state": "waiting_for_check_in_video"}
    bot.send_message(chat_id, "Ishga kelganingizni tasdiqlash uchun **video_note (aylana video)** yuboring:", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🚪 Ishdan ketdim")
def check_out_button(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)
    if not user or user.get("Holat") != "Tasdiqlangan":
        bot.send_message(chat_id, "Ro'yxatdan o'tmagan yoki tasdiqlanmagansiz.")
        return
    today = get_today_attendance(chat_id)
    if not today or not today.get("Kirish vaqti"):
        bot.send_message(chat_id, "Bugun ishga kelganingiz qayd etilmagan.")
        return
    if today and today.get("Chiqish vaqti"):
        bot.send_message(chat_id, "Bugun allaqachon ishdan ketganingiz qayd etilgan.")
        return
    user_states[chat_id] = {"state": "waiting_for_check_out_video"}
    bot.send_message(chat_id, "Ishdan ketganingizni tasdiqlash uchun **video_note (aylana video)** yuboring:", parse_mode="Markdown")

@bot.message_handler(content_types=["video_note"], func=lambda m: user_states.get(m.chat.id, {}).get("state") in ["waiting_for_check_in_video", "waiting_for_check_out_video"])
def handle_video_note(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id, {}).get("state")
    video_id = message.video_note.file_id
    now = datetime.now(TIMEZONE)
    user = get_user_by_chat_id(chat_id)

    if not user:
        bot.send_message(chat_id, "Foydalanuvchi topilmadi.")
        user_states.pop(chat_id, None)
        return

    try:
        if state == "waiting_for_check_in_video":
            shift = "morning" if SHIFT_MORNING_START <= now.time() < SHIFT_MORNING_END else "evening"
            shift_label = SHIFTS[shift]["label"]
            branch = user.get("Filial", "integro")
            branch_label = BRANCHES.get(branch, branch)
            position = user.get("Lavozim", "office_manager")

            if record_check_in(chat_id, user["Ism"], position, branch_label, shift_label, now, video_id):
                bot.send_message(chat_id, f"✅ Ishga kelganingiz qayd etildi. Vaqt: {now.strftime('%H:%M:%S')}")

                score = calculate_ranking_score(now)
                record_ranking(now.strftime("%Y-%m-%d"), chat_id, user["Ism"], position, now.strftime("%H:%M:%S"), score)

                msg = f"✅ *{user['Ism']}* — Check-in: {now.strftime('%H:%M')}\n📍 {branch_label} | {shift_label}"
                for admin_id in ADMIN_IDS:
                    try:
                        bot.send_message(admin_id, msg, parse_mode="Markdown")
                        bot.forward_message(admin_id, chat_id, message.message_id)
                    except:
                        pass
                if GROUP_ID_INT:
                    try:
                        bot.send_message(GROUP_ID_INT, msg, parse_mode="Markdown")
                        bot.forward_message(GROUP_ID_INT, chat_id, message.message_id)
                    except:
                        pass
            else:
                bot.send_message(chat_id, "Xatolik yuz berdi. Qayta urinib ko'ring.")

        elif state == "waiting_for_check_out_video":
            shift_label = SHIFTS.get(user.get("Smena", "morning"), {}).get("label", user.get("Smena", ""))
            if record_check_out(chat_id, now, video_id):
                bot.send_message(chat_id, f"✅ Ishdan ketganingiz qayd etildi. Vaqt: {now.strftime('%H:%M:%S')}")

                msg = f"👋 *{user['Ism']}* — Check-out: {now.strftime('%H:%M')}"
                for admin_id in ADMIN_IDS:
                    try:
                        bot.send_message(admin_id, msg, parse_mode="Markdown")
                        bot.forward_message(admin_id, chat_id, message.message_id)
                    except:
                        pass
                if GROUP_ID_INT:
                    try:
                        bot.send_message(GROUP_ID_INT, msg, parse_mode="Markdown")
                        bot.forward_message(GROUP_ID_INT, chat_id, message.message_id)
                    except:
                        pass
            else:
                bot.send_message(chat_id, "Xatolik yuz berdi (yoki bugun ishga kelmagansiz).")
    except Exception as e:
        print(f"Video_note error: {e}")
        bot.send_message(chat_id, "Xatolik yuz berdi.")
    user_states.pop(chat_id, None)

# ── Tasks ──
def add_task(task_name, proof_type, emp_chat_ids, due_date):
    try:
        task_id = str(uuid.uuid4())[:8]
        tasklar_ws.append_row([
            datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S"),
            task_id, task_name, proof_type,
            ",".join(map(str, emp_chat_ids)),
            due_date.strftime("%Y-%m-%d %H:%M:%S"), "Yangi",
        ])
        return task_id
    except:
        return None

def get_user_tasks(chat_id):
    tasks = tasklar_ws.get_all_records()
    return [t for t in tasks if str(chat_id) in t.get("Hodimlar(chat_id)", "").split(",") and t.get("Holat") != "Yakunlangan"]

def update_task_status(task_id, status):
    try:
        cell = tasklar_ws.find(task_id, in_column=2)
        if cell:
            tasklar_ws.update_cell(cell.row, 7, status)
            return True
        return False
    except:
        return False

@bot.message_handler(func=lambda m: m.text == "📝 Mening vazifalarim")
def my_tasks(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)
    if not user or user.get("Holat") != "Tasdiqlangan":
        bot.send_message(chat_id, "Ro'yxatdan o'tmagan yoki tasdiqlanmagansiz.")
        return
    tasks = get_user_tasks(chat_id)
    if not tasks:
        bot.send_message(chat_id, "Sizga biriktirilgan vazifalar yo'q.")
        return
    for t in tasks:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Bajarildi", callback_data=f"done_task_{t['ID']}"))
        bot.send_message(
            chat_id,
            f"📋 *{t['Vazifa nomi']}*\nID: {t['ID']}\nTuri: {t['Turi']}\nMuddat: {t['Muddat']}\nHolat: {t['Holat']}",
            parse_mode="Markdown",
            reply_markup=markup,
        )

@bot.callback_query_handler(func=lambda c: c.data.startswith("done_task_"))
def complete_task(call):
    chat_id = call.message.chat.id
    task_id = call.data.replace("done_task_", "")
    records = tasklar_ws.get_all_records()
    task = None
    for t in records:
        if t.get("ID") == task_id:
            task = t
            break
    if not task:
        bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Vazifa topilmadi.")
        bot.answer_callback_query(call.id)
        return
    proof_type = task.get("Turi")
    if proof_type == "Hech biri":
        if update_task_status(task_id, "Yakunlangan"):
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=f"✅ '{task['Vazifa nomi']}' yakunlandi!")
        bot.answer_callback_query(call.id)
        return
    user_states[chat_id] = {"state": "waiting_for_task_proof", "task_id": task_id, "proof_type": proof_type}
    bot.send_message(chat_id, f"'{task['Vazifa nomi']}' uchun {proof_type} dalil yuboring:")
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=["photo", "video", "text"], func=lambda m: user_states.get(m.chat.id, {}).get("state") == "waiting_for_task_proof")
def handle_task_proof(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id, {})
    task_id = state.get("task_id")
    expected = state.get("proof_type")
    proof = ""
    if message.photo and expected == "Foto":
        proof = message.photo[-1].file_id
    elif message.video and expected == "Video":
        proof = message.video.file_id
    elif message.text and expected == "Matn":
        proof = message.text
    else:
        bot.send_message(chat_id, f"Iltimos, {expected} yuboring.")
        return
    if update_task_status(task_id, "Yakunlangan"):
        bot.send_message(chat_id, f"✅ Vazifa yakunlandi!")
        for admin_id in ADMIN_IDS:
            try:
                if message.photo:
                    bot.send_photo(admin_id, message.photo[-1].file_id, caption=f"Task {task_id} dalil (xodim: {chat_id})")
                elif message.video:
                    bot.send_video(admin_id, message.video.file_id, caption=f"Task {task_id} dalil (xodim: {chat_id})")
                elif message.text:
                    bot.send_message(admin_id, f"Task {task_id} dalil (xodim: {chat_id}):\n{message.text}")
            except:
                pass
    user_states.pop(chat_id, None)

# ── Ranking ──
@bot.message_handler(func=lambda m: m.text == "🏆 Reytingim")
def my_ranking(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)
    if not user or user.get("Holat") != "Tasdiqlangan":
        return
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    daily = get_daily_ranking(today)
    overall = get_overall_ranking()

    msg = "🏆 *Bugungi Reyting:*\n"
    found = False
    for i, r in enumerate(daily):
        marker = " *" if str(r.get("chat_id")) == str(chat_id) else ""
        msg += f"{i+1}. {r['Ism']} — {r['Ball']} ball (Kelish: {r['Kelish vaqti']}){marker}\n"
        if str(r.get("chat_id")) == str(chat_id):
            found = True
    if not found:
        msg += "Siz bugun reytingda yo'qsiz.\n"

    msg += "\n📈 *Umumiy Reyting:*\n"
    for i, r in enumerate(overall):
        marker = " *" if str(r.get("chat_id")) == str(chat_id) else ""
        msg += f"{i+1}. {r['Ism']} — {r['Ball']} ball{marker}\n"

    bot.send_message(chat_id, msg, parse_mode="Markdown")

# ── Admin Handlers ──
@bot.message_handler(func=lambda m: is_admin(m.chat.id) and m.text == "✅ Foydalanuvchilarni boshqarish")
def admin_user_mgmt(message):
    chat_id = message.chat.id
    pending = [u for u in get_all_users() if u.get("Holat") == "Kutilmoqda"]
    if not pending:
        bot.send_message(chat_id, "Kutilayotgan foydalanuvchilar yo'q.")
        return
    for u in pending:
        bot.send_message(
            chat_id,
            f"👤 {u['Ism']}\nLavozim: {u['Lavozim']}\nID: {u['chat_id']}",
            reply_markup=approval_kb(u["chat_id"]),
        )

@bot.message_handler(func=lambda m: is_admin(m.chat.id) and m.text == "➕ Vazifa yaratish")
def admin_create_task(message):
    chat_id = message.chat.id
    user_states[chat_id] = {"state": "waiting_for_task_name"}
    bot.send_message(chat_id, "Vazifa nomini kiriting:")

@bot.message_handler(func=lambda m: is_admin(m.chat.id) and user_states.get(m.chat.id, {}).get("state") == "waiting_for_task_name")
def admin_task_name(message):
    chat_id = message.chat.id
    user_states[chat_id]["task_name"] = message.text
    user_states[chat_id]["state"] = "waiting_for_proof_type"
    bot.send_message(chat_id, "Dalil turini tanlang:", reply_markup=proof_type_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("proof_") and is_admin(c.message.chat.id) and user_states.get(c.message.chat.id, {}).get("state") == "waiting_for_proof_type")
def admin_proof_type(call):
    chat_id = call.message.chat.id
    proof_type = call.data.replace("proof_", "").capitalize()
    user_states[chat_id]["proof_type"] = proof_type

    approved = [u for u in get_all_users() if u.get("Holat") == "Tasdiqlangan" and not is_admin(int(u.get("chat_id", 0)))]
    if not approved:
        bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Tasdiqlangan xodimlar yo'q.")
        user_states.pop(chat_id, None)
        bot.answer_callback_query(call.id)
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for u in approved:
        markup.add(types.InlineKeyboardButton(u["Ism"], callback_data=f"sel_emp_{u['chat_id']}"))
    markup.add(types.InlineKeyboardButton("✅ Tugatish", callback_data="finish_emp_sel"))

    user_states[chat_id]["selected"] = []
    user_states[chat_id]["state"] = "waiting_for_employee_selection"
    bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Xodimlarni tanlang:", reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sel_emp_") and is_admin(c.message.chat.id) and user_states.get(c.message.chat.id, {}).get("state") == "waiting_for_employee_selection")
def admin_select_emp(call):
    chat_id = call.message.chat.id
    emp_id = int(call.data.replace("sel_emp_", ""))
    if emp_id not in user_states[chat_id]["selected"]:
        user_states[chat_id]["selected"].append(emp_id)
        bot.answer_callback_query(call.id, "Tanlandi!")
    else:
        user_states[chat_id]["selected"].remove(emp_id)
        bot.answer_callback_query(call.id, "Bekor qilindi!")

    approved = [u for u in get_all_users() if u.get("Holat") == "Tasdiqlangan" and not is_admin(int(u.get("chat_id", 0)))]
    markup = types.InlineKeyboardMarkup(row_width=1)
    for u in approved:
        text = u["Ism"]
        if int(u["chat_id"]) in user_states[chat_id]["selected"]:
            text += " ✅"
        markup.add(types.InlineKeyboardButton(text, callback_data=f"sel_emp_{u['chat_id']}"))
    markup.add(types.InlineKeyboardButton("✅ Tugatish", callback_data="finish_emp_sel"))
    bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "finish_emp_sel" and is_admin(c.message.chat.id) and user_states.get(c.message.chat.id, {}).get("state") == "waiting_for_employee_selection")
def admin_finish_emp_sel(call):
    chat_id = call.message.chat.id
    if not user_states[chat_id].get("selected"):
        bot.answer_callback_query(call.id, "Kamida bitta xodim tanlang!")
        return
    user_states[chat_id]["state"] = "waiting_for_due_date"
    bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Muddatni kiriting (YYYY-MM-DD HH:MM):")
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: is_admin(m.chat.id) and user_states.get(m.chat.id, {}).get("state") == "waiting_for_due_date")
def admin_due_date(message):
    chat_id = message.chat.id
    try:
        due = datetime.strptime(message.text, "%Y-%m-%d %H:%M").replace(tzinfo=TIMEZONE)
        s = user_states[chat_id]
        task_id = add_task(s["task_name"], s["proof_type"], s["selected"], due)
        if task_id:
            bot.send_message(chat_id, f"✅ Vazifa yaratildi (ID: {task_id})")
            for eid in s["selected"]:
                try:
                    bot.send_message(eid, f"📋 *Yangi vazifa*\n\n{s['task_name']}\nMuddat: {message.text}\n\n📝 Mening vazifalarim tugmasini bosing.", parse_mode="Markdown", reply_markup=employee_kb())
                except:
                    pass
        else:
            bot.send_message(chat_id, "Xatolik yuz berdi.")
    except ValueError:
        bot.send_message(chat_id, "Noto'g'ri format. YYYY-MM-DD HH:MM (masalan: 2026-12-31 18:00):")
        return
    user_states.pop(chat_id, None)

@bot.message_handler(func=lambda m: is_admin(m.chat.id) and m.text == "📋 Vazifalarni ko'rish")
def admin_view_tasks(message):
    chat_id = message.chat.id
    tasks = tasklar_ws.get_all_records()
    if not tasks:
        bot.send_message(chat_id, "Vazifalar yo'q.")
        return
    for t in tasks:
        names = []
        for eid in t.get("Hodimlar(chat_id)", "").split(","):
            if eid:
                u = get_user_by_chat_id(int(eid))
                names.append(u["Ism"] if u else f"Noma'lum ({eid})")
        bot.send_message(
            chat_id,
            f"📋 *{t['Vazifa nomi']}*\nID: {t['ID']}\nTuri: {t['Turi']}\nHodimlar: {', '.join(names)}\nMuddat: {t['Muddat']}\nHolat: {t['Holat']}",
            parse_mode="Markdown",
        )

@bot.message_handler(func=lambda m: is_admin(m.chat.id) and m.text == "👥 Xodimlar faoliyati")
def admin_activity(message):
    chat_id = message.chat.id
    today = get_all_attendance_today()
    if not today:
        bot.send_message(chat_id, "Bugun faoliyat yo'q.")
        return
    msg = "👥 *Bugungi faoliyat:*\n\n"
    for r in today:
        msg += f"👤 {r['Ism']} ({r['Lavozim']})\n📍 {r.get('Filial', '')}\n⬆️ Kirish: {r['Kirish vaqti']}\n⬇️ Chiqish: {r.get('Chiqish vaqti', '—')}\n\n"
    bot.send_message(chat_id, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: is_admin(m.chat.id) and m.text == "📊 Reytinglar")
def admin_ranking(message):
    chat_id = message.chat.id
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    daily = get_daily_ranking(today)
    overall = get_overall_ranking()

    msg = "🏆 *Bugungi Reyting:*\n"
    for i, r in enumerate(daily):
        msg += f"{i+1}. {r['Ism']} ({r['Lavozim']}) — {r['Ball']} ball\n"
    msg += "\n📈 *Umumiy Reyting:*\n"
    for i, r in enumerate(overall):
        msg += f"{i+1}. {r['Ism']} ({r['Lavozim']}) — {r['Ball']} ball\n"
    bot.send_message(chat_id, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: is_admin(m.chat.id) and m.text == "📈 Hisobotlar")
def admin_reports(message):
    bot.send_message(message.chat.id, "Hisobotlar funksiyasi ishlab chiqilmoqda.")


# ── Fallback (catch-all for debug) ──
@bot.message_handler(func=lambda m: True)
def fallback_handler(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)
    if not user or user.get("Holat") != "Tasdiqlangan":
        return
    bot.send_message(chat_id, f"ℹ️ Noto'g'ri buyruq: {message.text}")


# ── Scheduler ──
def send_shift_reminders():
    now = datetime.now(TIMEZONE)
    if now.hour == 7 and now.minute == 50:
        for u in get_all_users():
            if u.get("Holat") == "Tasdiqlangan" and u.get("Smena") == "morning":
                try:
                    bot.send_message(int(u["chat_id"]), "⏰ Ertalabki smena 10 daqiqadan keyin boshlanadi (08:00).")
                except:
                    pass
    elif now.hour == 13 and now.minute == 50:
        for u in get_all_users():
            if u.get("Holat") == "Tasdiqlangan" and u.get("Smena") == "evening":
                try:
                    bot.send_message(int(u["chat_id"]), "⏰ Kechki smena 10 daqiqadan keyin boshlanadi (14:00).")
                except:
                    pass

def auto_checkout_job():
    now = datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")
    records = davomat_ws.get_all_records()
    for i, row in enumerate(records):
        if row.get("Sana") == today and not row.get("Chiqish vaqti"):
            try:
                davomat_ws.update_cell(i + 2, 7, AUTO_CHECKOUT_TIME.strftime("%H:%M:%S"))
            except:
                pass

# ── Main ──
if __name__ == "__main__":
    import time
    if not init_sheets():
        print("Failed to init Sheets. Exiting.")
        exit(1)
    scheduler.add_job(send_shift_reminders, "cron", hour="*", minute="50", id="shift_reminders")
    scheduler.add_job(auto_checkout_job, "cron", hour=AUTO_CHECKOUT_TIME.hour, minute=AUTO_CHECKOUT_TIME.minute, id="auto_checkout")
    scheduler.start()
    print("Bot started polling...")

    # Telegram API vaqti-vaqti bilan 502/read-timeout berishi mumkin.
    # polling crash bo'lsa avtomatik qayta ishga tushadi.
    while True:
        try:
            bot.polling(none_stop=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"⚠️ Polling crash: {e}. 10 soniyadan keyin qayta ishga tushadi...")
            time.sleep(10)
