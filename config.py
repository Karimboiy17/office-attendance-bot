"""Office Attendance Bot — Konfiguratsiya"""

import os
from dotenv import load_dotenv
load_dotenv()

# ── Bot ──
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ── Admin lar ──
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "1054482233")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

# ── Guruh ID si (video check-in lar shu yerda) ──
GROUP_ID = int(os.getenv("GROUP_ID", "-1003981182641"))

# ── Filiallar ──
BRANCHES = {
    "integro": "Integro",
    "amir_temur": "Amir Temur",
    "xalqlar": "Xalqlar Do'stligi",
    "online": "Online",
}

BRANCH_LIST = list(BRANCHES.keys())

# ── Rollar ──
ROLES = ["office_manager", "cashier", "coordinator"]
ROLE_LABELS = {
    "office_manager": "Office Manager",
    "cashier": "Kassir",
    "coordinator": "Koordinator",
}

# ── Coordinator lar (branch adminlari) ──
# Format: "integro:5238121241,1054482233;amir_temur:87654321;xalqlas:111111;online:222222"
# Yoki eski format: "5238121241" (branch ko'rsatilmagan bo'lsa, hamma filialni ko'radi)
COORDINATORS_RAW = os.getenv("COORDINATORS", "")
COORDINATORS = {}  # {branch: [user_id, ...]}
COORDINATOR_IDS = []  # Hamma coordinatorlarning flat listi

if COORDINATORS_RAW:
    for part in COORDINATORS_RAW.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            branch, ids_str = part.split(":", 1)
            branch = branch.strip()
            ids = [int(x.strip()) for x in ids_str.split(",") if x.strip().isdigit()]
            if ids:
                COORDINATORS[branch] = ids
                COORDINATOR_IDS.extend(ids)
        else:
            # Eski format — faqat ID lar, hamma branch ni ko'radi
            ids = [int(x.strip()) for x in part.split(",") if x.strip().isdigit()]
            for bid in ids:
                for b in BRANCHES:
                    COORDINATORS.setdefault(b, []).append(bid)
            COORDINATOR_IDS.extend(ids)

# ── Smenalar ──
SHIFTS = {
    "morning": {"start": 8, "end": 14, "label": "Ertalab (08:00-14:00)"},
    "afternoon": {"start": 14, "end": 21, "label": "Kechki (14:00-21:00)"},
}

# Check-in deadline — necha daqiqagacha "on_time" hisoblanadi
CHECKIN_DEADLINE_MINUTES = 0  # 08:00 da deadline, 08:01 = late

# Avtomatik tekshirish vaqti (smena boshlangandan necha daqiqa keyin)
AUTO_CHECK_OFFSET_MINUTES = 10  # 08:10 va 14:10 da

# ── Ish kunlari ──
WORK_DAYS = [0, 1, 2, 3, 4, 5]  # Mon=0, Tue=1, ..., Sat=5 (Yakshanba dam)

# ── Google Sheets ──
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SERVICE_ACCOUNT_B64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_B64", "")
SHEET_KEY = os.getenv("SHEET_KEY", "")

# ── Vaqt mintaqasi ──
TIMEZONE = "Asia/Tashkent"
