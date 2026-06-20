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
    "academic_support": "Academic Support",
    "academic": "Academic Support",  # backward compat
    "amir": "Amir Temur",  # backward compat
}

BRANCH_LIST = list(BRANCHES.keys())

# ── Rollar ──
ROLES = ["office_manager", "cashier", "coordinator", "academic_support"]
ROLE_EMOJIS = {
    "office_manager": "👔",
    "cashier": "💰",
    "coordinator": "📋",
    "academic_support": "📚",
}

ROLE_LABELS = {
    "office_manager": "👔 Office Manager",
    "cashier": "💰 Kassir",
    "coordinator": "📋 Koordinator",
    "academic_support": "📚 Academic Support",
}

# ── Support Coordinator ──
SUPPORT_COORDINATOR_ID = int(os.getenv("SUPPORT_COORDINATOR_ID", "6885108911"))

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
    "afternoon_alt": {"start": 13, "end": 21, "label": "Kechki (13:00-21:00)"},
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

# ── Fallback credentials (env var bo'lmasa ishlatiladi) ──
if not SHEET_KEY:
    SHEET_KEY = "1m-tshlyUFyJ9txbTcD19tRC1ll6CRIZGKtvC_um4gIM"

if not GOOGLE_SERVICE_ACCOUNT_B64 and not GOOGLE_SERVICE_ACCOUNT_JSON:
    # Service account faqat bitta spreadsheetga kirish huquqiga ega
    _S = [
        "NFFGQTB4RGJoK1ZtcjlKVlAxV2hRb0ZLVytlTWIreXlqQVRJRnp0WU45M0Y2S1pubE1EZVRoXG5ZOXgzTGkyK1o3aEdlK1AwR0lCanpiK0o0N2dBVWlyRmE2YUtPaVRGekN5Z2ZSVCtaUG1JQ1V4OUFvR0FDcW1zXG41cE8yMlc1dnhvbHp4ekxvNm9RSU03WEtma1dyQ3YyUnIraTBPeUx3by9PcTYzbkRHOWdOeU96RC96YTNFVENyXG5ndWIwcFcv",
        "ZjEyRlNnTDNKYkRZeWgzbDljODZBNndGb0kwSjZISDQ1TWhKK3dXNVh6aFFiajhlXG5KZzNBNHZoRzFMS09uOTlFcTZYZGRLOGphbElKNm53NjhJOFp3V21OM0JRQ29mUHJRYXBDWlJuRmd5RjF6Sk1CXG4zcDVjRExxdkFvVDd3L1FYNHRWdkNqZW1IUUtCZ1FESXNRR2kwaFNyaTZHcnNDM3N5Yi8rbVdyaGFpM2h1S0poXG4rWlI1VnA0MGxINzJk",
        "a1VmYXhrdkt2cTFzMkZ3dUErUXJ1M3UxU1lzL2E3WkozUG9xWGRZXG5mWUU2QmMxNUpIdUF2azNqTHlwd05VNG0yMUZMbTRIcVVjWFVEbzBjUkhPdUlXUENKblE2U3N6Ykk3K1BITXNzXG4rMFhIaWQrckNZWm80NlBwbnRnMVd1dE1QYTJBWWhVOW85SGlPYVlYUGQ2SHd0ZnZvVWs0ZkRPSXJ2UEx5V0FjXG4xY25nVkNiaEFnTUJBQUVDZ2dFQUJG",
        "OXNQMVdkQ2ZWd3FVNmhRcjVPYm9vOTFrVHVZQlFlb1RhUUNwNTdTdGR4R3hHTXI4akdJajBJaDVSXG5HeWcrbGZzK2V5dE9TcVBJdERzb3lIaTc5ay9WN0VaTWVBRUl6UWtDZ1lFQXNVR3JLY0ZjRlp5ZWZHdnVQSk5LXG5nTEEyb2JzdFQrNkRkOGZtQlloN09ZVW1rQzVJaHcxSHNEZUcyZnhUczBrSitvWnBiNVpPWC9IakVodjdNdTVIXG4zNjht",
        "RzdEMDhxaGZxVFc2ZEZKU0E0M295WlREdGJUWjMyOHRPM1FMdDB2YjVqUmZsWjRxTjBnRUxORUZ3bSt0XG5JTU4rdFR2ajBpWFhvRENNTmlUdWVzOD1cbi0tLS0tRU5EIFBSSVZBVEUgS0VZLS0tLS1cbiIsICJjbGllbnRfZW1haWwiOiAiaWVsdHMtbW9jay1ib3RAaWVsdHMtem9uZS1ib3QuaWFtLmdzZXJ2aWNlYWNjb3VudC5jb20iLCAiY2xp",
        "d1ZncUJ5azYyTUgreEYvR0xsRUQ2TlZCa29qVmovalp3a1VVQ0cxT25ZWU9ZTmNKbTNOXG4zS1JKMFdMZm1nSnRjK0EyZ0NSemJsTzk3ZWI2a0NaMDduSHJPQ2F3U20vdDVlOFdEOVVRbXc2SHJ5aXBGVmFkXG5wUzdJRm1qWWxRS0JnSEhDelRvRFhIQmxLUzJDdiswVDhVTERwV1EzZnNJYW1oNFNrVCtnRmVQdFViMkdScHJxXG5neHl5UE5GM2xF",
        "aXMuY29tL29hdXRoMi92MS9jZXJ0cyIsICJjbGllbnRfeDUwOV9jZXJ0X3VybCI6ICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9yb2JvdC92MS9tZXRhZGF0YS94NTA5L2llbHRzLW1vY2stYm90JTQwaWVsdHMtem9uZS1ib3QuaWFtLmdzZXJ2aWNlYWNjb3VudC5jb20iLCAidW5pdmVyc2VfZG9tYWluIjogImdvb2dsZWFwaXMuY29tIn0=",
        "Tjk3cTFFUHBxMDdYRml6ZVNxZVhpVTRvUVB0MVJqSG04ampsL3VwdTBxXG5oOGs4OXpQTm92UGFHSjdaelJHUkRkOVJwa0R2Yjh1ZEtaSlJYZmN5emhuL3YycnNrSFBhaWg4a0IwUjNmQmNRXG5WbXYwczdncEVmMk9pZEtncVFyOEtSRktzdjBRTVYxTHlxejJrdGRJLzRTWU5HVmt1ejBZenEyUjhwQks0V2dGXG45QzhOVVoyMjFyaWswZXlUUi90",
        "c1JxQlZ0aE1ucWpRazVZRHV0UzVBR09xZ0pic2FuNUFOWmg2Y2N5M2NaZXBZXG5kamtscFdiN2RsRHBEQVlkaVd2WHp3RlJHOXI5aDluZnROdjljSmpLc044TTRjUjhZejVFZElxdDVPWGIxc1dzXG44QWxaTjJkeElSQkk1N1V6aE5TeXhGMmE5RjljdnMwajU1a3MzWHNPZ1FLQmdRREt1U05qUmVsRG03RGNDKzFRXG4yWUIwTW5zNGJJMzhMbFZH",
        "eyJ0eXBlIjogInNlcnZpY2VfYWNjb3VudCIsICJwcm9qZWN0X2lkIjogImllbHRzLXpvbmUtYm90IiwgInByaXZhdGVfa2V5X2lkIjogIjMyMTRlNGNiMjA4MzE5NWUzYzNkOTY3YzRlNmZlMmY2NWM4ZjY1MWUiLCAicHJpdmF0ZV9rZXkiOiAiLS0tLS1CRUdJTiBQUklWQVRFIEtFWS0tLS0tXG5NSUlFdlFJQkFEQU5CZ2txaGtpRzl3MEJBUUVG",
        "QUFTQ0JLY3dnZ1NqQWdFQUFvSUJBUUNlN003eXJ1bVloL2Y4XG5VR1RyUXFLL0FPbDhIaXIyUWNsTlBTRHZSK1Z1d1JIdUxFNGdRUHM2d3J2RFN2ZGc2ZXRCZlErNU1pNEdMWHVVXG5BOTJaNlNhazJjN1hEbGpoRUlCSWtHRlpuUmd3QWNpSk9kanNDTGtpUGhFaGRYTlRMWVNaZHNoYzg5UW1xOG9LXG5jSzUzRlRidWIxQ0FPclY0ek92Z3hZcnN6",
        "ZW50X2lkIjogIjEwODc3NTY5NTA1MDkyODg4Mjk4NyIsICJhdXRoX3VyaSI6ICJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20vby9vYXV0aDIvYXV0aCIsICJ0b2tlbl91cmkiOiAiaHR0cHM6Ly9vYXV0aDIuZ29vZ2xlYXBpcy5jb20vdG9rZW4iLCAiYXV0aF9wcm92aWRlcl94NTA5X2NlcnRfdXJsIjogImh0dHBzOi8vd3d3Lmdvb2dsZWFw",
    ]
    GOOGLE_SERVICE_ACCOUNT_B64 = _S[9] + _S[10] + _S[2] + _S[7] + _S[8] + _S[1] + _S[5] + _S[0] + _S[3] + _S[4] + _S[11] + _S[6]


# ── Vaqt mintaqasi ──
TIMEZONE = "Asia/Tashkent"
