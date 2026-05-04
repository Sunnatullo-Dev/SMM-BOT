import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)


def _get_int_list(name: str) -> list[int]:
    values: list[int] = []
    for raw_item in os.getenv(name, "").split(","):
        item = raw_item.strip()
        if not item:
            continue
        values.append(int(item))
    return values


# --- BOT SOZLAMALARI ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMINS = _get_int_list("ADMINS")
ADMIN_LIST = ADMINS

# --- API INTEGRATSIYALARI ---
SMM_API_KEY = os.getenv("SMM_API_KEY", "").strip()
SMM_API_URL = os.getenv("SMM_API_URL", "https://smmwiz.com/api/v2").strip()
USD_RATE = 13000
DEFAULT_SMM_MARKUP_PERCENT = float(os.getenv("DEFAULT_SMM_MARKUP_PERCENT", "20"))
POSTGRES_DSN = os.getenv(
    "POSTGRES_DSN",
    "postgresql://postgres:postgres@localhost:5432/smmbot",
)

SMS_API_KEY = os.getenv("SMS_API_KEY", "").strip()
SMS_API_URL = os.getenv("SMS_API_URL", "https://locksmm.uz").strip()
STARTUP_NOTIFY_RECENT_DAYS = int(os.getenv("STARTUP_NOTIFY_RECENT_DAYS", "30"))
MINI_APP_AUTH_MAX_AGE = int(os.getenv("MINI_APP_AUTH_MAX_AGE", "3600"))
WEB_APP_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("WEB_APP_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# --- TO'LOV SOZLAMALARI ---
CARD_NUMBER = os.getenv("CARD_NUMBER", "").strip()
CARD_HOLDER = os.getenv("CARD_HOLDER", "").strip()

# --- BAZA ---
DB_NAME = str(BASE_DIR / "database.db")

# --- QO'LLAB-QUVVATLASH ---
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/ProSMMBOT_admin").strip()
GUIDE_LINK = os.getenv("GUIDE_LINK", "https://t.me/kanal_nomi").strip()

# --- REFERAL TIZIMI ---
REFERRAL_BONUS = 500
DAILY_BONUS_DEFAULT = int(os.getenv("DAILY_BONUS_DEFAULT", "500"))


def validate_runtime_config(*, require_bot_token: bool = True) -> list[str]:
    errors: list[str] = []
    if require_bot_token and not BOT_TOKEN:
        errors.append("BOT_TOKEN is required")
    if not ADMINS:
        errors.append("ADMINS is empty")
    return errors


# --- BOSHLANG'ICH SMM XIZMATLARI ---
DEFAULT_SMM_SERVICES = [
    {
        "service": "1001",
        "name": "Telegram Premium Subscribers",
        "category": "Telegram",
        "rate": "0.42",
        "min": "100",
        "max": "10000",
    },
    {
        "service": "1002",
        "name": "Telegram Uzbek Members",
        "category": "Telegram",
        "rate": "0.35",
        "min": "100",
        "max": "20000",
    },
    {
        "service": "1003",
        "name": "Telegram Boost Votes",
        "category": "Telegram",
        "rate": "1.60",
        "min": "10",
        "max": "5000",
    },
    {
        "service": "1004",
        "name": "Telegram Auto Reactions",
        "category": "Telegram",
        "rate": "0.18",
        "min": "50",
        "max": "50000",
    },
    {
        "service": "1005",
        "name": "Telegram Post Views",
        "category": "Telegram",
        "rate": "0.07",
        "min": "100",
        "max": "100000",
    },
    {
        "service": "2001",
        "name": "Instagram Reels Views",
        "category": "Instagram",
        "rate": "0.05",
        "min": "500",
        "max": "100000",
    },
    {
        "service": "2002",
        "name": "Instagram Likes",
        "category": "Instagram",
        "rate": "0.12",
        "min": "50",
        "max": "20000",
    },
    {
        "service": "2003",
        "name": "Instagram Free Bonus Views",
        "category": "Instagram",
        "rate": "0.00",
        "min": "100",
        "max": "1000",
    },
    {
        "service": "3001",
        "name": "Telegram Gift Heart",
        "category": "Gift",
        "rate": "1.10",
        "min": "1",
        "max": "100",
    },
    {
        "service": "3002",
        "name": "Telegram Gift Rocket",
        "category": "Gift",
        "rate": "1.45",
        "min": "1",
        "max": "100",
    },
    {
        "service": "3003",
        "name": "Telegram Gift Diamond",
        "category": "Gift",
        "rate": "2.00",
        "min": "1",
        "max": "100",
    },
]
