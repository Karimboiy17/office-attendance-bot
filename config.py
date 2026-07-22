"""Office Manager Bot — Konfiguratsiya"""

import os
from dotenv import load_dotenv
load_dotenv()

# ── Bot ──
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ── Admin lar ──
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "1054482233")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

# ── Guruh ID si (video check-in lar shu yerda) ──
GROUP_ID = int(os.getenv("GROUP_ID", "0"))

# ── Filiallar ──
BRANCHES = {
    "integro": "Integro",
    "amir_temur": "Amir Temur",
    "xalqlar": "Xalqlar Do'stligi",
    "online": "Online",
}

BRANCH_LIST = list(BRANCHES.keys())

# ── Rollar ──
ROLES = ["office_manager"]
ROLE_EMOJIS = {"office_manager": "👔"}
ROLE_LABELS = {"office_manager": "👔 Office Manager"}

# ── Smenalar ──
SHIFTS = {
    "morning": {"start": 8, "end": 17, "label": "Ertalab (08:00-17:00)"},
    "evening": {"start": 14, "end": 21, "label": "Kechki (14:00-21:00)"},
}

# Check-in deadline — necha daqiqagacha "on_time" hisoblanadi
CHECKIN_DEADLINE_MINUTES = 5

# Avtomatik tekshirish vaqti (smena boshlangandan necha daqiqa keyin)
AUTO_CHECK_OFFSET_MINUTES = 15

# ── Ish kunlari ──
WORK_DAYS = [0, 1, 2, 3, 4, 5]  # Mon=0 .. Sat=5 (Yakshanba dam)

# ── Google Sheets ──
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SERVICE_ACCOUNT_B64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_B64", "")
SHEET_KEY = os.getenv("SHEET_KEY", "")

# ── Default task schedule (smena bo'yicha) ──
# Har bir smenadagi xodimga avtomatik beriladigan tasklar
DEFAULT_TASKS = {
    "morning": [
        {"time": "08:00-09:00", "task": "SSP toldirish, Telegramm ga toliq javob berib chiqish, Test topshirgan mijozla bilan bog'lanib chiqish"},
        {"time": "09:00-09:30", "task": "Ochilgan aktiv telegramm guruhlaga birma bir kirib holat ko'rib chiqish"},
        {"time": "09:30-11:00", "task": "Online 50 lead bilan ishlab chiqish, guruhga sotuv va aktiv raqamlani yuborish"},
        {"time": "11:00-11:10", "task": "Kozlarga dam berish, turib biroz aylanish"},
        {"time": "11:10-12:00", "task": "Instagramm target dan tushkan lead la bilan ishlab chiqish"},
        {"time": "12:00-13:00", "task": "Care students"},
        {"time": "13:00-14:00", "task": "Ozimizga oqituvchilarimiz davomat qardzdorlik (guuh nazorat qilish)"},
        {"time": "14:00-15:00", "task": "Abeh vohti"},
    ],
    "evening": [
        {"time": "14:00-15:00", "task": "Telegramga javob berish, Instagramm target 50 lead bilan bog'lanish"},
        {"time": "15:00-16:00", "task": "Telegramga javob berish, Instagramm target 50 lead bilan bog'lanish (davom)"},
        {"time": "16:00-17:00", "task": "Telegramga javob berish, Oldingi sheets degi lead la bilan ishlash"},
        {"time": "17:00-17:10", "task": "Telegramga javob berish, Oldingi sheets degi lead la bilan ishlash (davom)"},
        {"time": "17:10-18:00", "task": "Ertaning ochishimiz kere borgan guruhlaga start berish va malumotlani yuborib qoyish"},
        {"time": "18:00-19:00", "task": "Ertaning ochishimiz kere borgan guruhlaga start berish va malumotlani yuborib qoyish (davom)"},
        {"time": "19:00-20:00", "task": "Kozlarga dam berish, turib biroz aylanish"},
        {"time": "20:00-21:00", "task": "Instagram lead bilan ishlash"},
        {"time": "21:00-22:00", "task": "6 8 9 pm degi guruhlaga boshida va ohirida 15 minutan kirish"},
        {"time": "22:00-23:00", "task": "6 8 9 pm degi guruhlaga boshida va ohirida 15 minutan kirish (davom)"},
        {"time": "23:00-00:00", "task": "Care students, eski sheets degi lead bilan ishlab chiqish"},
        {"time": "00:00-01:00", "task": "Kassani yopib ketish"},
    ],
}

# ── Vaqt mintaqasi ──
TIMEZONE = "Asia/Tashkent"
