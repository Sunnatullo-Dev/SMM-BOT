from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiosqlite

from config import (
    DB_NAME,
    USD_RATE,
    SMM_API_KEY,
    SMM_API_URL,
    SMS_API_KEY,
    SMS_API_URL,
    DEFAULT_SMM_MARKUP_PERCENT,
    DEFAULT_SMM_SERVICES,
    CARD_NUMBER,
    CARD_HOLDER,
    SUPPORT_LINK,
    GUIDE_LINK,
    REFERRAL_BONUS,
    DAILY_BONUS_DEFAULT,
)
from utils.service_catalog import (
    GROUP_META,
    PLATFORM_META,
    calculate_price_uzs,
    classify_smm_service,
)


DEFAULT_SETTINGS = {
    "usd_rate": str(USD_RATE),
    "markup_percentage": str(DEFAULT_SMM_MARKUP_PERCENT),
    "smm_markup_percent": str(DEFAULT_SMM_MARKUP_PERCENT),
    "sms_markup_percent": "0",
    "smm_api_key": SMM_API_KEY,
    "smm_api_url": SMM_API_URL,
    "sms_api_key": SMS_API_KEY,
    "sms_api_url": SMS_API_URL,
    "bot_status": "active",
    "referral_bonus": str(REFERRAL_BONUS),
    "daily_bonus_amount": str(DAILY_BONUS_DEFAULT),
    "discount_percent": "0",
    "card_number": CARD_NUMBER,
    "card_holder": CARD_HOLDER,
    "payme_enabled": "1",
    "click_enabled": "1",
    "start_text": "Botga xush kelibsiz.",
    "guide_text": "Qo'llanma hali sozlanmagan.",
    "support_link": SUPPORT_LINK,
    "channels_text": GUIDE_LINK,
    "promo_code_value": "",
    "promo_code_bonus": "0",
    "promo_code_expires_at": "",
    "payment_note": "To'lov usulini tanlang va summani yuboring.",
    "referral_enabled": "1",
    "referral_diamond_uz": "2",
    "referral_diamond_foreign": "2",
    "referral_cash_uz": "100",
    "referral_cash_foreign": "50",
    "referral_banner_file_id": "",
    "admin_username": "@admin",
    "news_channel": GUIDE_LINK,
    "news_group": "",
    "orders_channel": "",
    "required_channels": "",
    "min_payment_amount": "1000",
    "auto_payment_url": "",
    "auto_payment_key": "",
    "sms_api_id": "",
    "license_label": "Demo",
}

DEFAULT_PAYMENT_METHODS = (
    {
        "name": "🅿️ PAYME [ Avto ]",
        "callback_data": "payme",
        "instruction": "Payme orqali avtomatik to'lovni amalga oshiring va summani kiriting.",
    },
    {
        "name": "☑️ Barcha ilova [ Avto ]",
        "callback_data": "all_apps_auto",
        "instruction": "Bank ilovasi orqali avtomatik to'lovni amalga oshiring va summani kiriting.",
    },
    {
        "name": "🔶 Humo | Uzcard [ Avto ]",
        "callback_data": "humo_uzcard_auto",
        "instruction": "Humo yoki Uzcard orqali to'lovni amalga oshiring va summani kiriting.",
    },
    {
        "name": "🔵 CLICK [ Avto ]",
        "callback_data": "click",
        "instruction": "Click orqali avtomatik to'lovni amalga oshiring va summani kiriting.",
    },
    {
        "name": "☎️ Adminga murojaat",
        "callback_data": "admin_support",
        "instruction": "Agar avtomatik to'lovda muammo bo'lsa, admin bilan bog'laning.",
    },
)

PAYMENT_METHOD_LABELS = {
    "payme": "🅿️ PAYME [ Avto ]",
    "all_apps_auto": "☑️ Barcha ilova [ Avto ]",
    "humo_uzcard_auto": "🔶 Humo | Uzcard [ Avto ]",
    "click": "🔵 CLICK [ Avto ]",
    "admin_support": "☎️ Adminga murojaat",
}


SERVICE_COLUMNS = {
    "platform_key": "TEXT DEFAULT ''",
    "platform_label": "TEXT DEFAULT ''",
    "platform_sort_order": "INTEGER DEFAULT 999",
    "group_key": "TEXT DEFAULT ''",
    "group_label": "TEXT DEFAULT ''",
    "group_sort_order": "INTEGER DEFAULT 999",
    "provider_price_usd": "REAL DEFAULT 0",
    "manual_price_per_1000": "INTEGER",
    "min_order": "INTEGER DEFAULT 0",
    "max_order": "INTEGER DEFAULT 0",
    "is_bonus": "INTEGER DEFAULT 0",
}


TRANSACTION_COLUMNS = {
    "direction": "TEXT DEFAULT 'credit'",
    "tx_type": "TEXT DEFAULT 'deposit'",
    "reference": "TEXT DEFAULT ''",
}


def _group_setting_key(group_key):
    return f"group_visible_{group_key}"


def _coerce_money(value):
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _normalize_sms_api_price_to_uzs(api_price, usd_rate):
    try:
        price_value = float(api_price or 0)
    except (TypeError, ValueError):
        return 0
    try:
        usd_rate_value = float(usd_rate or USD_RATE)
    except (TypeError, ValueError):
        usd_rate_value = float(USD_RATE)

    if price_value <= 0:
        return 0

    # locksmm.uz countries endpoint currently returns fractional values; treat them as USD-like
    # and convert to so'm. Large values are assumed to already be in so'm.
    if price_value < 100:
        return _coerce_money(price_value * usd_rate_value)
    return _coerce_money(price_value)


APP_TIMEZONE = ZoneInfo("Asia/Tashkent")


def _to_utc_sql(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _today_bounds_sql() -> tuple[str, str]:
    now_local = datetime.now(APP_TIMEZONE)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return _to_utc_sql(start_local), _to_utc_sql(end_local)


def _month_bounds_sql() -> tuple[str, str]:
    now_local = datetime.now(APP_TIMEZONE)
    start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start_local.month == 12:
        end_local = start_local.replace(year=start_local.year + 1, month=1)
    else:
        end_local = start_local.replace(month=start_local.month + 1)
    return _to_utc_sql(start_local), _to_utc_sql(end_local)


class Database:
    def __init__(self, db_path):
        self.db_path = db_path

    @asynccontextmanager
    async def connect(self):
        db = await aiosqlite.connect(self.db_path, timeout=10)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
        finally:
            await db.close()

    async def initialize(self):
        async with self.connect() as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE,
                    username TEXT,
                    full_name TEXT,
                    balance INTEGER DEFAULT 0,
                    total_spent INTEGER DEFAULT 0,
                    referrer_id INTEGER DEFAULT 0,
                    phone_number TEXT DEFAULT 'No',
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_blocked INTEGER DEFAULT 0
                )
                """
            )

            async with db.execute("PRAGMA table_info(users)") as cursor:
                columns = await cursor.fetchall()
            if not any(column["name"] == "last_seen" for column in columns):
                await db.execute("ALTER TABLE users ADD COLUMN last_seen TIMESTAMP")
                await db.execute(
                    "UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE last_seen IS NULL"
                )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    method TEXT,
                    status TEXT DEFAULT 'pending',
                    direction TEXT DEFAULT 'credit',
                    tx_type TEXT DEFAULT 'deposit',
                    reference TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    service_type TEXT,
                    service_name TEXT,
                    target TEXT,
                    amount INTEGER,
                    external_id TEXT,
                    status TEXT DEFAULT 'processing',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS payment_methods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    callback_data TEXT UNIQUE,
                    is_active INTEGER DEFAULT 1,
                    instruction TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS payment_wallets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    holder_name TEXT NOT NULL,
                    wallet_number TEXT NOT NULL UNIQUE,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS service_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id TEXT UNIQUE,
                    category TEXT NOT NULL,
                    name TEXT NOT NULL,
                    price_per_1000 INTEGER NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sms_price_overrides (
                    country_id TEXT NOT NULL,
                    service_code TEXT NOT NULL,
                    override_price INTEGER NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (country_id, service_code)
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS action_locks (
                    lock_key TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS referral_rewards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inviter_user_id INTEGER NOT NULL,
                    referred_user_id INTEGER NOT NULL UNIQUE,
                    order_id INTEGER NOT NULL,
                    reward_amount INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            await self._ensure_transaction_schema(db)
            await self._ensure_service_schema(db)
            await self._ensure_money_schema(db)
            await self._reclassify_services(db)

            for key, value in DEFAULT_SETTINGS.items():
                await db.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, str(value)),
                )

            await db.execute(
                """
                UPDATE settings
                SET value = (
                    SELECT old.value
                    FROM settings AS old
                    WHERE old.key = 'smm_markup_percent'
                ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE key = 'markup_percentage'
                  AND (value = ? OR value = '' OR value IS NULL)
                  AND EXISTS (
                    SELECT 1
                    FROM settings AS old
                    WHERE old.key = 'smm_markup_percent'
                      AND COALESCE(old.value, '') != ''
                  )
                """,
                (str(DEFAULT_SMM_MARKUP_PERCENT),),
            )

            for group_key in GROUP_META:
                await db.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, '1')",
                    (_group_setting_key(group_key),),
                )

            await self._ensure_default_payment_methods(db)
            if CARD_NUMBER.strip():
                await db.execute(
                    """
                    INSERT OR IGNORE INTO payment_wallets (label, holder_name, wallet_number, is_active, sort_order)
                    VALUES (?, ?, ?, 1, 0)
                    """,
                    ("💳 Uzcard / Humo", CARD_HOLDER, CARD_NUMBER),
                )

            await db.commit()

            async with db.execute("SELECT COUNT(*) AS cnt FROM service_catalog") as cursor:
                service_count = (await cursor.fetchone())["cnt"]
            async with db.execute(
                "SELECT COUNT(*) AS cnt FROM service_catalog WHERE COALESCE(group_key, '') != ''"
            ) as cursor:
                classified_count = (await cursor.fetchone())["cnt"]

            if service_count == 0:
                await self._sync_smm_services(db, DEFAULT_SMM_SERVICES)
            elif classified_count == 0:
                await self._backfill_legacy_services(db)
            if service_count < 6:
                await self._sync_smm_services(db, DEFAULT_SMM_SERVICES)

            await self._ensure_sequences(db)
            await db.commit()

    async def _ensure_default_payment_methods(self, db):
        await db.execute(
            "DELETE FROM payment_methods WHERE callback_data = ? OR name = ?",
            ("receipt", "🧾 Chek yuborish"),
        )

        for method in DEFAULT_PAYMENT_METHODS:
            method_name = PAYMENT_METHOD_LABELS.get(method["callback_data"], method["name"])
            await db.execute(
                """
                INSERT INTO payment_methods (name, callback_data, instruction, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(callback_data) DO UPDATE SET
                    name = excluded.name,
                    instruction = excluded.instruction
                """,
                (
                    method_name,
                    method["callback_data"],
                    method["instruction"],
                ),
            )

    async def _ensure_service_schema(self, db):
        async with db.execute("PRAGMA table_info(service_catalog)") as cursor:
            existing_columns = {row["name"] for row in await cursor.fetchall()}

        for column_name, definition in SERVICE_COLUMNS.items():
            if column_name not in existing_columns:
                await db.execute(f"ALTER TABLE service_catalog ADD COLUMN {column_name} {definition}")

    async def _ensure_transaction_schema(self, db):
        async with db.execute("PRAGMA table_info(transactions)") as cursor:
            existing_columns = {row["name"] for row in await cursor.fetchall()}

        for column_name, definition in TRANSACTION_COLUMNS.items():
            if column_name not in existing_columns:
                await db.execute(f"ALTER TABLE transactions ADD COLUMN {column_name} {definition}")

    async def _ensure_money_schema(self, db):
        migrations = {
            "users": {
                "expected_types": {
                    "balance": "INTEGER",
                    "total_spent": "INTEGER",
                },
                "create_sql": """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER UNIQUE,
                        username TEXT,
                        full_name TEXT,
                        balance INTEGER DEFAULT 0,
                        total_spent INTEGER DEFAULT 0,
                        referrer_id INTEGER DEFAULT 0,
                        phone_number TEXT DEFAULT 'No',
                        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_blocked INTEGER DEFAULT 0
                    )
                """,
                "copy_sql": """
                    INSERT INTO users (
                        id, user_id, username, full_name, balance, total_spent,
                        referrer_id, phone_number, registered_at, is_blocked
                    )
                    SELECT
                        id,
                        user_id,
                        username,
                        full_name,
                        CAST(ROUND(COALESCE(balance, 0)) AS INTEGER),
                        CAST(ROUND(COALESCE(total_spent, 0)) AS INTEGER),
                        COALESCE(referrer_id, 0),
                        COALESCE(phone_number, 'No'),
                        registered_at,
                        COALESCE(is_blocked, 0)
                    FROM {old_table}
                """,
            },
            "transactions": {
                "expected_types": {
                    "amount": "INTEGER",
                },
                "create_sql": """
                    CREATE TABLE transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        amount INTEGER,
                        method TEXT,
                        status TEXT DEFAULT 'pending',
                        direction TEXT DEFAULT 'credit',
                        tx_type TEXT DEFAULT 'deposit',
                        reference TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """,
                "copy_sql": """
                    INSERT INTO transactions (
                        id, user_id, amount, method, status, direction, tx_type, reference, created_at
                    )
                    SELECT
                        id,
                        user_id,
                        CAST(ROUND(COALESCE(amount, 0)) AS INTEGER),
                        method,
                        COALESCE(status, 'pending'),
                        COALESCE(direction, 'credit'),
                        COALESCE(tx_type, 'deposit'),
                        COALESCE(reference, ''),
                        created_at
                    FROM {old_table}
                """,
            },
            "orders": {
                "expected_types": {
                    "amount": "INTEGER",
                },
                "create_sql": """
                    CREATE TABLE orders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        service_type TEXT,
                        service_name TEXT,
                        target TEXT,
                        amount INTEGER,
                        external_id TEXT,
                        status TEXT DEFAULT 'processing',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """,
                "copy_sql": """
                    INSERT INTO orders (
                        id, user_id, service_type, service_name, target, amount, external_id, status, created_at
                    )
                    SELECT
                        id,
                        user_id,
                        service_type,
                        service_name,
                        target,
                        CAST(ROUND(COALESCE(amount, 0)) AS INTEGER),
                        external_id,
                        COALESCE(status, 'processing'),
                        created_at
                    FROM {old_table}
                """,
            },
            "service_catalog": {
                "expected_types": {
                    "price_per_1000": "INTEGER",
                    "manual_price_per_1000": "INTEGER",
                },
                "create_sql": """
                    CREATE TABLE service_catalog (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        service_id TEXT UNIQUE,
                        category TEXT NOT NULL,
                        name TEXT NOT NULL,
                        price_per_1000 INTEGER NOT NULL,
                        is_active INTEGER DEFAULT 1,
                        sort_order INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        platform_key TEXT DEFAULT '',
                        platform_label TEXT DEFAULT '',
                        platform_sort_order INTEGER DEFAULT 999,
                        group_key TEXT DEFAULT '',
                        group_label TEXT DEFAULT '',
                        group_sort_order INTEGER DEFAULT 999,
                        provider_price_usd REAL DEFAULT 0,
                        manual_price_per_1000 INTEGER,
                        min_order INTEGER DEFAULT 0,
                        max_order INTEGER DEFAULT 0,
                        is_bonus INTEGER DEFAULT 0
                    )
                """,
                "copy_sql": """
                    INSERT INTO service_catalog (
                        id, service_id, category, name, price_per_1000, is_active, sort_order,
                        created_at, updated_at, platform_key, platform_label, platform_sort_order,
                        group_key, group_label, group_sort_order, provider_price_usd,
                        manual_price_per_1000, min_order, max_order, is_bonus
                    )
                    SELECT
                        id,
                        service_id,
                        category,
                        name,
                        CAST(ROUND(COALESCE(price_per_1000, 0)) AS INTEGER),
                        COALESCE(is_active, 1),
                        COALESCE(sort_order, 0),
                        created_at,
                        updated_at,
                        COALESCE(platform_key, ''),
                        COALESCE(platform_label, ''),
                        COALESCE(platform_sort_order, 999),
                        COALESCE(group_key, ''),
                        COALESCE(group_label, ''),
                        COALESCE(group_sort_order, 999),
                        COALESCE(provider_price_usd, 0),
                        CASE
                            WHEN manual_price_per_1000 IS NULL THEN NULL
                            ELSE CAST(ROUND(manual_price_per_1000) AS INTEGER)
                        END,
                        COALESCE(min_order, 0),
                        COALESCE(max_order, 0),
                        COALESCE(is_bonus, 0)
                    FROM {old_table}
                """,
            },
            "sms_price_overrides": {
                "expected_types": {
                    "override_price": "INTEGER",
                },
                "create_sql": """
                    CREATE TABLE sms_price_overrides (
                        country_id TEXT NOT NULL,
                        service_code TEXT NOT NULL,
                        override_price INTEGER NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (country_id, service_code)
                    )
                """,
                "copy_sql": """
                    INSERT INTO sms_price_overrides (
                        country_id, service_code, override_price, updated_at
                    )
                    SELECT
                        country_id,
                        service_code,
                        CAST(ROUND(COALESCE(override_price, 0)) AS INTEGER),
                        updated_at
                    FROM {old_table}
                """,
            },
        }

        for table_name, spec in migrations.items():
            async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
                columns = {
                    row["name"]: (row["type"] or "").upper()
                    for row in await cursor.fetchall()
                }
            if not columns:
                continue
            if all(columns.get(column, "").startswith(expected) for column, expected in spec["expected_types"].items()):
                continue

            legacy_table = f"{table_name}__money_legacy"
            await db.execute(f"ALTER TABLE {table_name} RENAME TO {legacy_table}")
            await db.execute(spec["create_sql"])
            await db.execute(spec["copy_sql"].format(old_table=legacy_table))
            await db.execute(f"DROP TABLE {legacy_table}")
            await db.commit()

    async def _ensure_sequences(self, db):
        try:
            await db.execute(
                """
                INSERT INTO sqlite_sequence (name, seq)
                SELECT 'users', 1999
                WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'users')
                """
            )
            await db.execute(
                """
                INSERT INTO sqlite_sequence (name, seq)
                SELECT 'orders', 1999
                WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'orders')
                """
            )
        except Exception:
            return

    async def _backfill_legacy_services(self, db):
        async with db.execute(
            """
            SELECT service_id, category, name, price_per_1000, is_active, sort_order
            FROM service_catalog
            WHERE COALESCE(group_key, '') = ''
            """
        ) as cursor:
            rows = await cursor.fetchall()

        _usd_rate, markup_percent = await self._get_runtime_pricing(db)
        multiplier = 1 + (markup_percent / 100)

        for row in rows:
            classification = classify_smm_service(row["name"], row["category"])
            if not classification:
                continue

            current_price = float(row["price_per_1000"] or 0)
            provider_price = round(current_price / multiplier, 6) if multiplier > 0 else 0
            default_min = 1 if classification["group_key"] == "gift_items" else 100
            default_max = 100 if classification["group_key"] == "gift_items" else 50000

            await db.execute(
                """
                UPDATE service_catalog
                SET category = ?,
                    platform_key = ?,
                    platform_label = ?,
                    platform_sort_order = ?,
                    group_key = ?,
                    group_label = ?,
                    group_sort_order = ?,
                    provider_price_usd = ?,
                    min_order = CASE WHEN min_order > 0 THEN min_order ELSE ? END,
                    max_order = CASE WHEN max_order > 0 THEN max_order ELSE ? END,
                    is_bonus = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE service_id = ?
                """,
                (
                    classification["platform_key"],
                    classification["platform_key"],
                    classification["platform_label"],
                    classification["platform_sort_order"],
                    classification["group_key"],
                    classification["group_label"],
                    classification["group_sort_order"],
                    provider_price,
                    default_min,
                    default_max,
                    classification["is_bonus"],
                    row["service_id"],
                ),
            )

    async def _reclassify_services(self, db):
        async with db.execute(
            """
            SELECT service_id, category, name
            FROM service_catalog
            """
        ) as cursor:
            rows = await cursor.fetchall()

        for row in rows:
            classification = classify_smm_service(row["name"], row["category"])
            if not classification:
                continue

            await db.execute(
                """
                UPDATE service_catalog
                SET category = ?,
                    platform_key = ?,
                    platform_label = ?,
                    platform_sort_order = ?,
                    group_key = ?,
                    group_label = ?,
                    group_sort_order = ?,
                    is_bonus = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE service_id = ?
                """,
                (
                    classification["platform_key"],
                    classification["platform_key"],
                    classification["platform_label"],
                    classification["platform_sort_order"],
                    classification["group_key"],
                    classification["group_label"],
                    classification["group_sort_order"],
                    classification["is_bonus"],
                    row["service_id"],
                ),
            )

    async def _get_runtime_pricing(self, db):
        async with db.execute(
            "SELECT key, value FROM settings WHERE key IN ('usd_rate', 'markup_percentage', 'smm_markup_percent')"
        ) as cursor:
            rows = await cursor.fetchall()
        settings = {row["key"]: row["value"] for row in rows}
        try:
            usd_rate = float(settings.get("usd_rate", USD_RATE))
        except (TypeError, ValueError):
            usd_rate = float(USD_RATE)
        try:
            markup = float(
                settings.get(
                    "markup_percentage",
                    settings.get("smm_markup_percent", DEFAULT_SMM_MARKUP_PERCENT),
                )
            )
        except (TypeError, ValueError):
            markup = float(DEFAULT_SMM_MARKUP_PERCENT)
        return usd_rate, markup

    async def _group_visibility_map(self, db):
        prefix = "group_visible_"
        async with db.execute(
            "SELECT key, value FROM settings WHERE key LIKE 'group_visible_%'"
        ) as cursor:
            rows = await cursor.fetchall()
        visibility = {}
        for row in rows:
            group_key = row["key"][len(prefix):]
            visibility[group_key] = str(row["value"]).strip() != "0"
        return visibility

    async def _filter_services_by_visibility(self, rows, include_hidden_groups=False):
        if include_hidden_groups:
            return rows

        async with self.connect() as db:
            visibility = await self._group_visibility_map(db)
        return [row for row in rows if visibility.get(row["group_key"], True)]

    async def _sync_smm_services(self, db, services):
        usd_rate, markup_percent = await self._get_runtime_pricing(db)

        for raw_service in services:
            service_id = str(
                raw_service.get("service")
                or raw_service.get("service_id")
                or raw_service.get("id")
                or ""
            ).strip()
            service_name = str(raw_service.get("name", "")).strip()
            service_category = str(raw_service.get("category", "")).strip()

            if not service_id or not service_name:
                continue

            classification = classify_smm_service(service_name, service_category)
            if not classification:
                continue

            try:
                provider_price = float(raw_service.get("rate", raw_service.get("price", 0)) or 0)
            except (TypeError, ValueError):
                provider_price = 0.0
            try:
                min_order = int(float(raw_service.get("min", 0) or 0))
            except (TypeError, ValueError):
                min_order = 0
            try:
                max_order = int(float(raw_service.get("max", 0) or 0))
            except (TypeError, ValueError):
                max_order = 0

            async with db.execute(
                "SELECT manual_price_per_1000, is_active FROM service_catalog WHERE service_id = ?",
                (service_id,),
            ) as cursor:
                existing_row = await cursor.fetchone()

            manual_price = existing_row["manual_price_per_1000"] if existing_row else None
            is_active = existing_row["is_active"] if existing_row else 1
            computed_price = calculate_price_uzs(
                provider_price,
                usd_rate,
                markup_percent,
                manual_price,
            )

            await db.execute(
                """
                INSERT INTO service_catalog (
                    service_id,
                    category,
                    name,
                    price_per_1000,
                    is_active,
                    sort_order,
                    updated_at,
                    platform_key,
                    platform_label,
                    platform_sort_order,
                    group_key,
                    group_label,
                    group_sort_order,
                    provider_price_usd,
                    manual_price_per_1000,
                    min_order,
                    max_order,
                    is_bonus
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_id) DO UPDATE SET
                    category = excluded.category,
                    name = excluded.name,
                    price_per_1000 = excluded.price_per_1000,
                    is_active = excluded.is_active,
                    sort_order = excluded.sort_order,
                    updated_at = CURRENT_TIMESTAMP,
                    platform_key = excluded.platform_key,
                    platform_label = excluded.platform_label,
                    platform_sort_order = excluded.platform_sort_order,
                    group_key = excluded.group_key,
                    group_label = excluded.group_label,
                    group_sort_order = excluded.group_sort_order,
                    provider_price_usd = excluded.provider_price_usd,
                    min_order = excluded.min_order,
                    max_order = excluded.max_order,
                    is_bonus = excluded.is_bonus,
                    manual_price_per_1000 = COALESCE(service_catalog.manual_price_per_1000, excluded.manual_price_per_1000)
                """,
                (
                    service_id,
                    classification["platform_key"],
                    service_name,
                    computed_price,
                    is_active,
                    classification["group_sort_order"],
                    classification["platform_key"],
                    classification["platform_label"],
                    classification["platform_sort_order"],
                    classification["group_key"],
                    classification["group_label"],
                    classification["group_sort_order"],
                    provider_price,
                    manual_price,
                    min_order,
                    max_order,
                    classification["is_bonus"],
                ),
            )

    # --- SETTINGS OPERATIONS ---
    async def get_setting(self, key, default=None):
        async with self.connect() as db:
            async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                return row["value"] if row else default

    async def set_setting(self, key, value):
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, str(value)),
            )
            if key == "markup_percentage":
                await db.execute(
                    """
                    INSERT INTO settings (key, value, updated_at)
                    VALUES ('smm_markup_percent', ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (str(value),),
                )
            elif key == "smm_markup_percent":
                await db.execute(
                    """
                    INSERT INTO settings (key, value, updated_at)
                    VALUES ('markup_percentage', ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (str(value),),
                )
            await db.commit()

        if key in {"usd_rate", "smm_markup_percent", "markup_percentage"}:
            await self.recalculate_smm_prices()

    async def get_settings(self, keys=None):
        async with self.connect() as db:
            if keys:
                placeholders = ",".join("?" for _ in keys)
                query = f"SELECT key, value FROM settings WHERE key IN ({placeholders})"
                async with db.execute(query, tuple(keys)) as cursor:
                    rows = await cursor.fetchall()
            else:
                async with db.execute("SELECT key, value FROM settings") as cursor:
                    rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}

    async def get_setting_bool(self, key, default=False):
        raw_value = await self.get_setting(key, "1" if default else "0")
        return str(raw_value).strip().lower() not in {"0", "false", "off", "no", ""}

    async def get_sms_price_override(self, country_id, service_code):
        async with self.connect() as db:
            async with db.execute(
                """
                SELECT override_price
                FROM sms_price_overrides
                WHERE country_id = ? AND service_code = ?
                """,
                (str(country_id), str(service_code)),
            ) as cursor:
                row = await cursor.fetchone()
        return int(row["override_price"]) if row else None

    async def set_sms_price_override(self, country_id, service_code, price):
        price = _coerce_money(price)
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO sms_price_overrides (country_id, service_code, override_price, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(country_id, service_code) DO UPDATE SET
                    override_price = excluded.override_price,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(country_id), str(service_code), price),
            )
            await db.commit()

    async def get_sms_price(self, country_id, service_code, api_price):
        override_price = await self.get_sms_price_override(country_id, service_code)
        if override_price is not None:
            return override_price

        markup_raw = await self.get_setting("sms_markup_percent", "0")
        usd_rate_raw = await self.get_setting("usd_rate", USD_RATE)
        try:
            markup_percent = float(markup_raw)
        except (TypeError, ValueError):
            markup_percent = 0.0
        base_price = _normalize_sms_api_price_to_uzs(api_price, usd_rate_raw)
        return _coerce_money(base_price * (1 + markup_percent / 100))

    # --- USER OPERATIONS ---
    async def add_user(self, user_id, username, full_name, referrer_id=0, last_seen=None):
        async with self.connect() as db:
            if last_seen is None:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO users (user_id, username, full_name, referrer_id, last_seen)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (user_id, username, full_name, referrer_id),
                )
            else:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO users (user_id, username, full_name, referrer_id, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, username, full_name, referrer_id, last_seen),
                )
            await db.commit()

    async def update_user_last_seen(self, user_id, last_seen=None):
        async with self.connect() as db:
            if last_seen is None:
                await db.execute(
                    "UPDATE users SET last_seen = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (user_id,),
                )
            else:
                await db.execute(
                    "UPDATE users SET last_seen = ? WHERE user_id = ?",
                    (last_seen, user_id),
                )
            await db.commit()

    async def get_user(self, user_id):
        async with self.connect() as db:
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchone()

    async def block_user(self, user_id, status):
        async with self.connect() as db:
            await db.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (status, user_id))
            await db.commit()
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchone()

    async def get_user_by_internal_id(self, internal_id):
        async with self.connect() as db:
            async with db.execute("SELECT * FROM users WHERE id = ?", (internal_id,)) as cursor:
                user = await cursor.fetchone()
                if user:
                    return user
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (internal_id,)) as cursor:
                return await cursor.fetchone()

    async def get_all_users(self, limit=10):
        async with self.connect() as db:
            async with db.execute(
                "SELECT * FROM users ORDER BY registered_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                return await cursor.fetchall()

    async def get_all_user_ids(self):
        async with self.connect() as db:
            async with db.execute("SELECT user_id FROM users ORDER BY id ASC") as cursor:
                rows = await cursor.fetchall()
        return [row["user_id"] for row in rows]

    async def get_recent_user_ids(self, days: int):
        async with self.connect() as db:
            async with db.execute(
                "SELECT user_id FROM users WHERE registered_at >= datetime('now', ?)",
                (f'-{days} days',),
            ) as cursor:
                rows = await cursor.fetchall()
        return [row["user_id"] for row in rows]

    async def update_balance(self, user_id, amount):
        amount = _coerce_money(amount)
        if amount == 0:
            return False
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            if amount > 0:
                cursor = await db.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                    (amount, user_id),
                )
            else:
                debit = abs(amount)
                cursor = await db.execute(
                    """
                    UPDATE users
                    SET balance = balance - ?
                    WHERE user_id = ? AND balance >= ?
                    """,
                    (debit, user_id, debit),
                )
            if cursor.rowcount == 0:
                await db.rollback()
                return False
            await db.commit()
        return True

    async def spend_balance(self, user_id, amount, method="Balance debit", tx_type="purchase", reference=""):
        amount = _coerce_money(amount)
        if amount <= 0:
            raise ValueError("Amount must be positive")

        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                UPDATE users
                SET balance = balance - ?, total_spent = total_spent + ?
                WHERE user_id = ? AND balance >= ?
                """,
                (amount, amount, user_id, amount),
            )
            if cursor.rowcount == 0:
                await db.rollback()
                return False

            await db.execute(
                """
                INSERT INTO transactions (user_id, amount, method, status, direction, tx_type, reference)
                VALUES (?, ?, ?, 'confirmed', 'debit', ?, ?)
                """,
                (user_id, amount, method, tx_type, reference),
            )
            await db.commit()
        return cursor.rowcount > 0

    async def refund_balance(self, user_id, amount, method="Refund", tx_type="refund", reference=""):
        amount = _coerce_money(amount)
        if amount <= 0:
            raise ValueError("Amount must be positive")

        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                UPDATE users
                SET balance = balance + ?,
                    total_spent = CASE
                        WHEN total_spent >= ? THEN total_spent - ?
                        ELSE 0
                    END
                WHERE user_id = ?
                """,
                (amount, amount, amount, user_id),
            )
            if cursor.rowcount == 0:
                await db.rollback()
                return False

            await db.execute(
                """
                INSERT INTO transactions (user_id, amount, method, status, direction, tx_type, reference)
                VALUES (?, ?, ?, 'confirmed', 'credit', ?, ?)
                """,
                (user_id, amount, method, tx_type, reference),
            )
            await db.commit()
        return cursor.rowcount > 0

    # --- TRANSACTION OPERATIONS ---
    async def add_transaction(
        self,
        user_id,
        amount,
        method="Card",
        status="pending",
        direction="credit",
        tx_type="deposit",
        reference="",
    ):
        amount = _coerce_money(amount)
        if amount <= 0:
            raise ValueError("Transaction amount must be positive")
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO transactions (user_id, amount, method, status, direction, tx_type, reference)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, amount, method, status, direction, tx_type, reference),
            )
            last_id = cursor.lastrowid
            await db.commit()
        return last_id

    async def get_transaction(self, transaction_id):
        async with self.connect() as db:
            async with db.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)) as cursor:
                return await cursor.fetchone()

    async def claim_action_lock(self, lock_key):
        lock_key = str(lock_key or "").strip()
        if not lock_key:
            return False
        async with self.connect() as db:
            cursor = await db.execute(
                "INSERT OR IGNORE INTO action_locks (lock_key) VALUES (?)",
                (lock_key,),
            )
            await db.commit()
        return cursor.rowcount > 0

    async def get_recent_transactions(self, limit=10, status=None):
        async with self.connect() as db:
            if status:
                query = "SELECT * FROM transactions WHERE status = ? ORDER BY created_at DESC LIMIT ?"
                params = (status, limit)
            else:
                query = "SELECT * FROM transactions ORDER BY created_at DESC LIMIT ?"
                params = (limit,)
            async with db.execute(query, params) as cursor:
                return await cursor.fetchall()

    async def get_pending_transactions(self, limit=20):
        return await self.get_recent_transactions(limit=limit, status="pending")

    async def _sum_turnover(self, db, period_sql="", params=()):
        query = f"""
            SELECT COALESCE(SUM(
                CASE
                    WHEN tx_type = 'purchase' AND direction = 'debit' AND status = 'confirmed' THEN amount
                    WHEN tx_type = 'refund' AND status = 'confirmed' THEN -amount
                    ELSE 0
                END
            ), 0) AS total
            FROM transactions
            WHERE 1 = 1
            {period_sql}
        """
        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return int(row["total"] or 0)

    async def confirm_transaction(self, transaction_id):
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")

            async with db.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)) as cursor:
                transaction = await cursor.fetchone()

            if not transaction:
                await db.rollback()
                return None, "not_found"

            if transaction["status"] != "pending":
                await db.rollback()
                return transaction, "already_processed"

            if transaction["direction"] != "credit" or transaction["tx_type"] != "deposit":
                await db.rollback()
                return transaction, "invalid_transaction"

            if int(transaction["amount"] or 0) <= 0:
                await db.rollback()
                return transaction, "invalid_transaction"

            cursor = await db.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (transaction["amount"], transaction["user_id"]),
            )
            if cursor.rowcount == 0:
                await db.rollback()
                return transaction, "user_not_found"

            await db.execute(
                "UPDATE transactions SET status = 'confirmed' WHERE id = ?",
                (transaction_id,),
            )
            await db.commit()

            async with db.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)) as cursor:
                return await cursor.fetchone(), "confirmed"

    async def reject_transaction(self, transaction_id):
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")

            async with db.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)) as cursor:
                transaction = await cursor.fetchone()

            if not transaction:
                await db.rollback()
                return None, "not_found"

            if transaction["status"] != "pending":
                await db.rollback()
                return transaction, "already_processed"

            await db.execute(
                "UPDATE transactions SET status = 'rejected' WHERE id = ?",
                (transaction_id,),
            )
            await db.commit()

            async with db.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)) as cursor:
                return await cursor.fetchone(), "rejected"

    # --- SERVICE CATALOG OPERATIONS ---
    async def recalculate_smm_prices(self):
        async with self.connect() as db:
            usd_rate, markup_percent = await self._get_runtime_pricing(db)
            async with db.execute(
                "SELECT service_id, provider_price_usd, manual_price_per_1000 FROM service_catalog"
            ) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                price = calculate_price_uzs(
                    row["provider_price_usd"],
                    usd_rate,
                    markup_percent,
                    row["manual_price_per_1000"],
                )
                await db.execute(
                    """
                    UPDATE service_catalog
                    SET price_per_1000 = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE service_id = ?
                    """,
                    (price, row["service_id"]),
                )
            await db.commit()

    async def sync_smm_services(self, services, usd_rate=None):
        async with self.connect() as db:
            if usd_rate is not None:
                await db.execute(
                    """
                    INSERT INTO settings (key, value, updated_at)
                    VALUES ('usd_rate', ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (str(usd_rate),),
                )
            await self._sync_smm_services(db, services)
            await db.commit()

    async def get_smm_services(
        self,
        category=None,
        platform=None,
        group_key=None,
        active_only=True,
        include_hidden_groups=False,
    ):
        query = "SELECT * FROM service_catalog WHERE 1 = 1"
        params = []

        if active_only:
            query += " AND is_active = 1"
        if platform:
            query += " AND platform_key = ?"
            params.append(platform)
        if group_key:
            query += " AND group_key = ?"
            params.append(group_key)
        if category and not platform and not group_key:
            query += " AND (category = ? OR platform_key = ? OR group_key = ?)"
            params.extend([category, category, category])

        query += " ORDER BY platform_sort_order, group_sort_order, sort_order, name"

        async with self.connect() as db:
            async with db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()

        return await self._filter_services_by_visibility(rows, include_hidden_groups)

    async def get_smm_service(self, service_id, active_only=False, include_hidden_groups=False):
        query = "SELECT * FROM service_catalog WHERE service_id = ?"
        params = [str(service_id)]
        if active_only:
            query += " AND is_active = 1"

        async with self.connect() as db:
            async with db.execute(query, tuple(params)) as cursor:
                row = await cursor.fetchone()
            visibility = await self._group_visibility_map(db)

        if not row:
            return None
        if not include_hidden_groups and not visibility.get(row["group_key"], True):
            return None
        return row

    async def get_smm_platforms(self, active_only=True, include_bonus=False):
        services = await self.get_smm_services(
            active_only=active_only,
            include_hidden_groups=False,
        )
        seen = {}
        for service in services:
            platform_key = service["platform_key"]
            if platform_key == "bonus" and not include_bonus:
                continue
            if platform_key not in seen:
                meta = PLATFORM_META.get(platform_key, {})
                seen[platform_key] = {
                    "platform_key": platform_key,
                    "platform_label": service["platform_label"] or meta.get("label", platform_key.title()),
                    "platform_emoji": meta.get("emoji", "📦"),
                    "platform_sort_order": service["platform_sort_order"] or meta.get("sort_order", 999),
                    "service_count": 0,
                }
            seen[platform_key]["service_count"] += 1
        return sorted(seen.values(), key=lambda item: item["platform_sort_order"])

    async def get_smm_groups(self, platform=None, active_only=True, include_hidden=False):
        services = await self.get_smm_services(
            platform=platform,
            active_only=active_only,
            include_hidden_groups=include_hidden,
        )
        seen = {}
        for service in services:
            group_key = service["group_key"]
            if group_key not in seen:
                seen[group_key] = {
                    "group_key": group_key,
                    "group_label": service["group_label"],
                    "group_emoji": GROUP_META.get(group_key, {}).get("emoji", "📁"),
                    "group_sort_order": service["group_sort_order"],
                    "platform_key": service["platform_key"],
                    "service_count": 0,
                    "is_visible": 1,
                }
            seen[group_key]["service_count"] += 1

        async with self.connect() as db:
            visibility = await self._group_visibility_map(db)

        for group in seen.values():
            group["is_visible"] = 1 if visibility.get(group["group_key"], True) else 0

        return sorted(seen.values(), key=lambda item: item["group_sort_order"])

    async def get_categories(self, active_only=True):
        platforms = await self.get_smm_platforms(active_only=active_only, include_bonus=False)
        return [platform["platform_key"] for platform in platforms]

    async def set_group_visibility(self, group_key, is_visible):
        await self.set_setting(_group_setting_key(group_key), "1" if is_visible else "0")

    async def update_smm_service_price(self, service_id, price_per_1000):
        price_per_1000 = _coerce_money(price_per_1000)
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE service_catalog
                SET manual_price_per_1000 = ?, price_per_1000 = ?, updated_at = CURRENT_TIMESTAMP
                WHERE service_id = ?
                """,
                (price_per_1000, price_per_1000, str(service_id)),
            )
            await db.commit()

    async def set_smm_service_active(self, service_id, is_active):
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE service_catalog
                SET is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE service_id = ?
                """,
                (1 if is_active else 0, str(service_id)),
            )
            await db.commit()

    # --- ORDER OPERATIONS ---
    async def add_order(self, user_id, service_type, service_name, target, amount, external_id):
        amount = _coerce_money(amount)
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO orders (user_id, service_type, service_name, target, amount, external_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, service_type, service_name, target, amount, external_id),
            )
            lastrowid = cursor.lastrowid
            await db.commit()
        return lastrowid

    async def get_order(self, order_id):
        async with self.connect() as db:
            async with db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cursor:
                return await cursor.fetchone()

    async def get_recent_orders(self, limit=10, status=None):
        async with self.connect() as db:
            if status and status != "all":
                query = "SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC LIMIT ?"
                params = (status, limit)
            else:
                query = "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?"
                params = (limit,)
            async with db.execute(query, params) as cursor:
                return await cursor.fetchall()

    async def update_order_status(self, order_id, status):
        async with self.connect() as db:
            await db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
            await db.commit()
            async with db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cursor:
                return await cursor.fetchone()

    async def get_order_by_id(self, order_id):
        return await self.get_order(order_id)

    async def get_user_stats(self, user_id):
        async with self.connect() as db:
            async with db.execute("SELECT COUNT(*) AS cnt FROM orders WHERE user_id = ?", (user_id,)) as cursor:
                orders_count = (await cursor.fetchone())["cnt"]
            async with db.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM transactions
                WHERE user_id = ?
                  AND status = 'confirmed'
                  AND direction = 'credit'
                  AND tx_type = 'deposit'
                """,
                (user_id,),
            ) as cursor:
                total_deposited = int((await cursor.fetchone())["total"] or 0)
        return orders_count, total_deposited

    async def get_referral_stats(self, user_id):
        async with self.connect() as db:
            async with db.execute("SELECT COUNT(*) AS cnt FROM users WHERE referrer_id = ?", (user_id,)) as cursor:
                return (await cursor.fetchone())["cnt"]

    async def get_referral_reward_count(self, user_id):
        async with self.connect() as db:
            async with db.execute(
                "SELECT COUNT(*) AS cnt FROM referral_rewards WHERE inviter_user_id = ?",
                (user_id,),
            ) as cursor:
                row = await cursor.fetchone()
                return row["cnt"] if row else 0

    async def award_referral_bonus_for_completed_order(self, referred_user_id, order_id):
        referred_user_id = int(referred_user_id)
        order_id = int(order_id)

        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")

            async with db.execute(
                "SELECT user_id, referrer_id FROM users WHERE user_id = ?",
                (referred_user_id,),
            ) as cursor:
                referred_user = await cursor.fetchone()

            if not referred_user:
                await db.rollback()
                return None, "user_not_found"

            inviter_user_id = int(referred_user["referrer_id"] or 0)
            if not inviter_user_id or inviter_user_id == referred_user_id:
                await db.rollback()
                return None, "no_referrer"

            async with db.execute(
                "SELECT * FROM referral_rewards WHERE referred_user_id = ?",
                (referred_user_id,),
            ) as cursor:
                existing_reward = await cursor.fetchone()

            if existing_reward:
                await db.rollback()
                return {
                    "inviter_user_id": int(existing_reward["inviter_user_id"]),
                    "referred_user_id": int(existing_reward["referred_user_id"]),
                    "order_id": int(existing_reward["order_id"]),
                    "reward_amount": int(existing_reward["reward_amount"]),
                }, "already_rewarded"

            async with db.execute(
                "SELECT value FROM settings WHERE key = 'referral_enabled'"
            ) as cursor:
                enabled_row = await cursor.fetchone()
            referral_enabled = str(enabled_row["value"] if enabled_row else "1").strip().lower() not in {
                "0",
                "false",
                "off",
                "no",
                "",
            }
            if not referral_enabled:
                await db.rollback()
                return None, "disabled"

            async with db.execute(
                "SELECT value FROM settings WHERE key = 'referral_bonus'"
            ) as cursor:
                reward_row = await cursor.fetchone()
            reward_amount = _coerce_money(reward_row["value"] if reward_row else REFERRAL_BONUS)
            if reward_amount <= 0:
                await db.rollback()
                return None, "disabled"

            async with db.execute(
                "SELECT COUNT(*) AS cnt FROM orders WHERE user_id = ? AND status = 'completed'",
                (referred_user_id,),
            ) as cursor:
                completed_count = int((await cursor.fetchone())["cnt"] or 0)

            if completed_count != 1:
                await db.rollback()
                return None, "not_first_completed"

            cursor = await db.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (reward_amount, inviter_user_id),
            )
            if cursor.rowcount == 0:
                await db.rollback()
                return None, "inviter_not_found"

            reference = f"referral:{inviter_user_id}:{referred_user_id}:{order_id}"
            await db.execute(
                """
                INSERT INTO transactions (user_id, amount, method, status, direction, tx_type, reference)
                VALUES (?, ?, ?, 'confirmed', 'credit', 'referral_bonus', ?)
                """,
                (inviter_user_id, reward_amount, "Referral Bonus", reference),
            )
            await db.execute(
                """
                INSERT INTO referral_rewards (inviter_user_id, referred_user_id, order_id, reward_amount)
                VALUES (?, ?, ?, ?)
                """,
                (inviter_user_id, referred_user_id, order_id, reward_amount),
            )
            await db.commit()

        return {
            "inviter_user_id": inviter_user_id,
            "referred_user_id": referred_user_id,
            "order_id": order_id,
            "reward_amount": reward_amount,
        }, "rewarded"

    async def add_deposit(self, internal_id, amount, comment=""):
        amount = _coerce_money(amount)
        async with self.connect() as db:
            async with db.execute("SELECT user_id FROM users WHERE id = ?", (internal_id,)) as cursor:
                user = await cursor.fetchone()
            if not user:
                return False

            user_id = user["user_id"]
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            await db.execute(
                """
                INSERT INTO transactions (user_id, amount, method, status, direction, tx_type, reference)
                VALUES (?, ?, ?, 'confirmed', 'credit', 'deposit', ?)
                """,
                (user_id, amount, comment or "Monitoring", f"internal:{internal_id}"),
            )
            await db.commit()
        return user_id

    async def get_user_orders(self, user_id, limit=10):
        async with self.connect() as db:
            async with db.execute(
                "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ) as cursor:
                return await cursor.fetchall()

    async def get_user_transactions(self, user_id, limit=5):
        async with self.connect() as db:
            async with db.execute(
                "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ) as cursor:
                return await cursor.fetchall()

    async def get_admin_stats(self):
        async with self.connect() as db:
            today_start, today_end = _today_bounds_sql()
            month_start, month_end = _month_bounds_sql()
            async with db.execute("SELECT COUNT(*) AS cnt FROM users") as cursor:
                total_users = (await cursor.fetchone())["cnt"]
            async with db.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE registered_at >= ? AND registered_at < ?",
                (today_start, today_end),
            ) as cursor:
                today_users = (await cursor.fetchone())["cnt"]
            async with db.execute("SELECT COUNT(*) AS cnt FROM orders") as cursor:
                total_orders = (await cursor.fetchone())["cnt"]
            async with db.execute(
                "SELECT COUNT(*) AS cnt FROM orders WHERE created_at >= ? AND created_at < ?",
                (today_start, today_end),
            ) as cursor:
                today_orders = (await cursor.fetchone())["cnt"]
            async with db.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status = 'processing'") as cursor:
                processing_orders = (await cursor.fetchone())["cnt"]
            async with db.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status = 'pending'") as cursor:
                pending_orders = (await cursor.fetchone())["cnt"]
            async with db.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status = 'completed'") as cursor:
                completed_orders = (await cursor.fetchone())["cnt"]
            async with db.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status = 'cancelled'") as cursor:
                cancelled_orders = (await cursor.fetchone())["cnt"]
            async with db.execute("SELECT COUNT(*) AS cnt FROM orders WHERE status = 'failed'") as cursor:
                failed_orders = (await cursor.fetchone())["cnt"]
            total_income = await self._sum_turnover(db)
            monthly_income = await self._sum_turnover(
                db,
                "AND created_at >= ? AND created_at < ?",
                (month_start, month_end),
            )
            today_sales = await self._sum_turnover(
                db,
                "AND created_at >= ? AND created_at < ?",
                (today_start, today_end),
            )
            async with db.execute("SELECT COALESCE(SUM(balance), 0) AS total FROM users") as cursor:
                total_user_balances = int((await cursor.fetchone())["total"] or 0)
            async with db.execute("SELECT COUNT(*) AS cnt FROM transactions WHERE status = 'pending'") as cursor:
                pending_transactions = (await cursor.fetchone())["cnt"]

        return {
            "total_users": total_users,
            "today_users": today_users,
            "total_orders": total_orders,
            "today_orders": today_orders,
            "pending_orders": pending_orders,
            "processing_orders": processing_orders,
            "completed_orders": completed_orders,
            "cancelled_orders": cancelled_orders,
            "failed_orders": failed_orders,
            "total_income": total_income,
            "monthly_income": monthly_income,
            "today_sales": today_sales,
            "total_user_balances": total_user_balances,
            "pending_transactions": pending_transactions,
        }

    async def get_order_stats_by_status(self):
        """Buyurtmalar holati bo'yicha statistika"""
        async with self.connect() as db:
            stats = {}
            async with db.execute(
                "SELECT status, COUNT(*) as cnt FROM orders GROUP BY status"
            ) as cursor:
                rows = await cursor.fetchall()
            for row in rows:
                stats[row["status"]] = row["cnt"]
            return stats

    async def get_daily_income(self):
        """Bugungi kunlik netto aylanma: purchase debetlari minus refundlar"""
        async with self.connect() as db:
            today_start, today_end = _today_bounds_sql()
            return await self._sum_turnover(
                db,
                "AND created_at >= ? AND created_at < ?",
                (today_start, today_end),
            )

    async def get_total_users_balance(self):
        """Barcha foydalanuvchilar jami balansi"""
        async with self.connect() as db:
            async with db.execute("SELECT COALESCE(SUM(balance), 0) as total FROM users") as cursor:
                return int((await cursor.fetchone())["total"] or 0)

    async def get_top_users(self, limit=100):
        """Eng balansli foydalanuvchilar"""
        async with self.connect() as db:
            async with db.execute(
                "SELECT user_id, username, full_name, balance FROM users ORDER BY balance DESC LIMIT ?",
                (limit,),
            ) as cursor:
                return await cursor.fetchall()

    async def get_user_country_stats(self, limit=6):
        async with self.connect() as db:
            async with db.execute("SELECT COUNT(*) AS cnt FROM users") as cursor:
                total_users = (await cursor.fetchone())["cnt"]
            async with db.execute(
                """
                SELECT user_id, service_name
                FROM orders
                WHERE service_type = 'SMS'
                ORDER BY created_at DESC
                """
            ) as cursor:
                rows = await cursor.fetchall()

        seen_users = set()
        counts = {}
        for row in rows:
            user_id = row["user_id"]
            if user_id in seen_users:
                continue
            seen_users.add(user_id)

            service_name = str(row["service_name"] or "").strip()
            country = service_name.rsplit(" - ", 1)[-1].strip() if " - " in service_name else "Aniqlanmagan"
            if not country:
                country = "Aniqlanmagan"
            counts[country] = counts.get(country, 0) + 1

        unknown_count = max(total_users - len(seen_users), 0)
        if unknown_count:
            counts["Aniqlanmagan"] = counts.get("Aniqlanmagan", 0) + unknown_count

        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [{"country": country, "count": count} for country, count in ordered[:limit]]

    async def clear_referrals(self):
        """Barcha referallarni tozalash"""
        async with self.connect() as db:
            cursor = await db.execute("UPDATE users SET referrer_id = 0 WHERE referrer_id != 0")
            await db.execute("DELETE FROM referral_rewards")
            await db.commit()
            return cursor.rowcount

    async def set_user_block_status(self, user_id, is_blocked):
        async with self.connect() as db:
            await db.execute(
                "UPDATE users SET is_blocked = ? WHERE user_id = ?",
                (1 if int(is_blocked) else 0, int(user_id)),
            )
            await db.commit()

    async def count_orders_by_status(self, status):
        """Holatli buyurtmalarni sanash"""
        async with self.connect() as db:
            async with db.execute(
                "SELECT COUNT(*) as cnt FROM orders WHERE status = ?", (status,)
            ) as cursor:
                row = await cursor.fetchone()
                return row["cnt"] if row else 0

    async def get_syncable_orders(self, limit=50):
        async with self.connect() as db:
            async with db.execute(
                """
                SELECT *
                FROM orders
                WHERE service_type = 'SMM'
                  AND status IN ('pending', 'processing')
                  AND COALESCE(external_id, '') != ''
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                return await cursor.fetchall()

    # --- PAYMENT METHODS ---
    async def get_payment_methods(self, active_only=False):
        query = "SELECT * FROM payment_methods"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY id ASC"
        async with self.connect() as db:
            async with db.execute(query) as cursor:
                return await cursor.fetchall()

    async def get_payment_method(self, method_id):
        async with self.connect() as db:
            async with db.execute("SELECT * FROM payment_methods WHERE id = ?", (method_id,)) as cursor:
                return await cursor.fetchone()

    async def add_payment_method(self, name, callback_data, instruction=""):
        async with self.connect() as db:
            await db.execute(
                "INSERT INTO payment_methods (name, callback_data, instruction) VALUES (?, ?, ?)",
                (name, callback_data, instruction)
            )
            await db.commit()

    async def update_payment_method(self, method_id, name=None, is_active=None, instruction=None):
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(int(is_active))
        if instruction is not None:
            updates.append("instruction = ?")
            params.append(instruction)
        
        if not updates:
            return
            
        query = f"UPDATE payment_methods SET {', '.join(updates)} WHERE id = ?"
        params.append(method_id)
        
        async with self.connect() as db:
            await db.execute(query, tuple(params))
            await db.commit()

    async def delete_payment_method(self, method_id):
        async with self.connect() as db:
            await db.execute("DELETE FROM payment_methods WHERE id = ?", (method_id,))
            await db.commit()

    # --- PAYMENT WALLETS ---
    async def get_payment_wallets(self, active_only=False):
        query = "SELECT * FROM payment_wallets"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY sort_order ASC, id ASC"
        async with self.connect() as db:
            async with db.execute(query) as cursor:
                return await cursor.fetchall()

    async def add_payment_wallet(self, label, holder_name, wallet_number, is_active=True):
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO payment_wallets (label, holder_name, wallet_number, is_active)
                VALUES (?, ?, ?, ?)
                """,
                (label, holder_name, wallet_number, 1 if is_active else 0),
            )
            await db.commit()

    async def delete_payment_wallet(self, wallet_id):
        async with self.connect() as db:
            await db.execute("DELETE FROM payment_wallets WHERE id = ?", (wallet_id,))
            await db.commit()

    async def get_primary_payment_wallet(self):
        wallets = await self.get_payment_wallets(active_only=True)
        return wallets[0] if wallets else None


db = Database(DB_NAME)


async def init_db():
    await db.initialize()
