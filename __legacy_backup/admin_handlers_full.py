import asyncio
import math
from html import escape

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_LIST, DAILY_BONUS_DEFAULT, DEFAULT_SMM_MARKUP_PERCENT, REFERRAL_BONUS, USD_RATE
from database.models import db
from services.referral_service import process_referral_reward
from states.bot_states import AdminStates
from utils.api_client import sms_client, smm_client
from utils.service_catalog import detect_country_flag

router = Router()

BROADCAST_BATCH_SIZE = 25
BROADCAST_BATCH_PAUSE = 1.0
SMS_COUNTRY_PAGE_SIZE = 8

ORDER_STATUS_LABELS = {
    "pending": "Kutilmoqda",
    "processing": "Jarayonda",
    "completed": "Tugallangan",
    "cancelled": "Bekor qilingan",
    "failed": "Muvaffaqiyatsiz",
}


def admin_main_keyboard():
    builder = InlineKeyboardBuilder()
    rows = [
        ("🛍 Xizmatlarni sozlash", "adm_services", "📝 Ma'lumotlarni tahrirlash", "adm_content"),
        ("✉️ Xabar yuborish", "adm_broadcast", "📊 Statistika", "adm_stats"),
        ("👤 Foydalanuvchi", "adm_user_lookup", "📚 Qo'llanma sozlash ⚙️", "adm_guide"),
        ("🛍 Chegirmalar", "adm_discounts", "🤖 Bot holati", "adm_bot_status"),
        ("⚖️ Foizni o'rnatish", "adm_markup", "🔑 API sozlamalari", "adm_api"),
        ("⚙️ Referal sozlamalari", "adm_referral", "🔍 Buyurtma tekshirish", "adm_order_check"),
        ("📢 Kanallar", "adm_channels", "💳 To'lov usullari", "adm_payment_methods"),
        ("🎟 Promokod", "adm_promocode", "🎁 Kunlik bonus", "adm_daily_bonus"),
        ("💎 Premium olish xizmati", "adm_premium", "📞 Nomer sozlamalari", "adm_sms_settings"),
    ]
    for left_text, left_cb, right_text, right_cb in rows:
        builder.row(
            types.InlineKeyboardButton(text=left_text, callback_data=left_cb),
            types.InlineKeyboardButton(text=right_text, callback_data=right_cb),
        )
    return builder.as_markup()


def back_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def stats_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🏆 TOP 100 Balans", callback_data="adm_top_users"))
    builder.row(types.InlineKeyboardButton(text="♻️ Buyurtmalar xolatini yangilash", callback_data="adm_refresh_orders"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def inline_back_keyboard(callback_data):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data=callback_data))
    return builder.as_markup()


def broadcast_review_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Yuborish", callback_data="adm_broadcast_send"),
        types.InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="adm_broadcast_edit"),
    )
    builder.row(types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm_broadcast_cancel"))
    return builder.as_markup()


def user_card_keyboard(user):
    builder = InlineKeyboardBuilder()
    ban_text = "✅ Blokdan chiqarish" if user["is_blocked"] else "🔔 Banlash"
    next_status = 0 if user["is_blocked"] else 1
    builder.row(types.InlineKeyboardButton(text=ban_text, callback_data=f"adm_user_toggle|{user['user_id']}|{next_status}"))
    builder.row(
        types.InlineKeyboardButton(text="➕ Pul qo'shish", callback_data=f"adm_user_balance|{user['user_id']}|add"),
        types.InlineKeyboardButton(text="➖ Pul ayirish", callback_data=f"adm_user_balance|{user['user_id']}|subtract"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def service_hub_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="💸 Narxlar", callback_data="adm_prices"),
        types.InlineKeyboardButton(text="🗂 Kategoriyalar", callback_data="adm_categories"),
    )
    builder.row(
        types.InlineKeyboardButton(text="💎 Premium xizmat", callback_data="adm_premium"),
        types.InlineKeyboardButton(text="🔄 API dan sync", callback_data="adm_sync_services"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def content_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="👤 Admin user", callback_data="adm_edit_setting|admin_username|content"),
        types.InlineKeyboardButton(text="📢 Yangiliklar kanal", callback_data="adm_edit_setting|news_channel|content"),
    )
    builder.row(
        types.InlineKeyboardButton(text="👥 Yangiliklar guruh", callback_data="adm_edit_setting|news_group|content"),
        types.InlineKeyboardButton(text="📦 Buyurtmalar kanal", callback_data="adm_edit_setting|orders_channel|content"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def guide_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="📚 Qo'llanma matni", callback_data="adm_edit_setting|guide_text|guide"),
        types.InlineKeyboardButton(text="🆘 Support link", callback_data="adm_edit_setting|support_link|guide"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def bot_status_keyboard(is_active):
    builder = InlineKeyboardBuilder()
    toggle_text = "⏸ Botni to'xtatish" if is_active else "▶️ Botni yoqish"
    next_status = "paused" if is_active else "active"
    builder.row(types.InlineKeyboardButton(text=toggle_text, callback_data=f"adm_set_bot_status|{next_status}"))
    builder.row(types.InlineKeyboardButton(text="🔐 Litsenziyani tahrirlash", callback_data="adm_edit_setting|license_label|bot_status"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def single_edit_keyboard(button_text, callback_data, back_callback="adm_main"):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text=button_text, callback_data=callback_data))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data=back_callback))
    return builder.as_markup()


def channels_keyboard(channel_count):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="adm_channel_add"),
        types.InlineKeyboardButton(text="🗑 Kanal o'chirish", callback_data="adm_channel_remove_menu"),
    )
    if channel_count:
        builder.row(types.InlineKeyboardButton(text="✏️ Hammasini matn bilan tahrirlash", callback_data="adm_edit_setting|required_channels|channels"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def channels_remove_keyboard(channels):
    builder = InlineKeyboardBuilder()
    for index, channel in enumerate(channels):
        builder.row(
            types.InlineKeyboardButton(
                text=f"🗑 {channel}",
                callback_data=f"adm_channel_remove|{index}",
            )
        )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_channels"))
    return builder.as_markup()


def api_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🌐 Smmwiz URL", callback_data="adm_edit_setting|smm_api_url|api"),
        types.InlineKeyboardButton(text="🔑 Smmwiz KEY", callback_data="adm_edit_setting|smm_api_key|api"),
    )
    builder.row(
        types.InlineKeyboardButton(text="🌐 SMS URL", callback_data="adm_edit_setting|sms_api_url|api"),
        types.InlineKeyboardButton(text="🔑 SMS KEY", callback_data="adm_edit_setting|sms_api_key|api"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def referral_settings_keyboard(is_enabled):
    builder = InlineKeyboardBuilder()
    toggle_text = "⏸ Referal tizimini o'chirish" if is_enabled else "▶️ Referal tizimini yoqish"
    next_status = "0" if is_enabled else "1"
    builder.row(types.InlineKeyboardButton(text=toggle_text, callback_data=f"adm_toggle_setting|referral_enabled|{next_status}|referral"))
    builder.row(
        types.InlineKeyboardButton(text="💎 Olmos UZ", callback_data="adm_edit_setting|referral_diamond_uz|referral"),
        types.InlineKeyboardButton(text="💎 Olmos Chet", callback_data="adm_edit_setting|referral_diamond_foreign|referral"),
    )
    builder.row(
        types.InlineKeyboardButton(text="💵 Pul UZ", callback_data="adm_edit_setting|referral_cash_uz|referral"),
        types.InlineKeyboardButton(text="💵 Pul Chet", callback_data="adm_edit_setting|referral_cash_foreign|referral"),
    )
    builder.row(
        types.InlineKeyboardButton(text="🖼 Banner yuklash", callback_data="adm_referral_banner"),
        types.InlineKeyboardButton(text="🧹 Referallarni tozalash", callback_data="adm_clear_referrals"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def order_check_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔎 ID bo'yicha qidirish", callback_data="adm_order_search"))
    builder.row(
        types.InlineKeyboardButton(text="⏳ Kutilayotgan", callback_data="adm_orders|pending"),
        types.InlineKeyboardButton(text="🔄 Jarayonda", callback_data="adm_orders|processing"),
    )
    builder.row(
        types.InlineKeyboardButton(text="✅ Tugallangan", callback_data="adm_orders|completed"),
        types.InlineKeyboardButton(text="❌ Bekor", callback_data="adm_orders|cancelled"),
    )
    builder.row(
        types.InlineKeyboardButton(text="⚠️ Xato", callback_data="adm_orders|failed"),
        types.InlineKeyboardButton(text="📦 Barchasi", callback_data="adm_orders|all"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def prices_keyboard(services):
    builder = InlineKeyboardBuilder()
    for service in services[:20]:
        status = "🟢" if service["is_active"] else "⚪"
        label = f"{status} {service['service_id']} | {service['price_per_1000']:,.0f}"
        builder.row(types.InlineKeyboardButton(text=label[:64], callback_data=f"adm_price_card|{service['service_id']}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_services"))
    return builder.as_markup()


def price_card_keyboard(service):
    builder = InlineKeyboardBuilder()
    next_state = 0 if service["is_active"] else 1
    toggle_label = "⏸ O'chirish" if service["is_active"] else "▶️ Faollashtirish"
    builder.row(
        types.InlineKeyboardButton(text="💰 Narxni tahrirlash", callback_data=f"adm_price_edit|{service['service_id']}"),
        types.InlineKeyboardButton(text=toggle_label, callback_data=f"adm_price_toggle|{service['service_id']}|{next_state}"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_prices"))
    return builder.as_markup()


def categories_keyboard(groups):
    builder = InlineKeyboardBuilder()
    for group in groups:
        icon = "🟢" if group["is_visible"] else "⚪"
        next_state = 0 if group["is_visible"] else 1
        text = f"{icon} {group['group_label']} ({group['service_count']})"
        builder.row(types.InlineKeyboardButton(text=text[:64], callback_data=f"adm_group|{group['group_key']}|{next_state}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_services"))
    return builder.as_markup()


def payment_methods_keyboard(settings):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="➕ Yangi hamyon", callback_data="adm_wallet_add"),
        types.InlineKeyboardButton(text="📋 Hamyonlar", callback_data="adm_wallets"),
    )
    builder.row(
        types.InlineKeyboardButton(text="💵 Minimal summa", callback_data="adm_edit_setting|min_payment_amount|payment"),
        types.InlineKeyboardButton(text="🤖 Avto-to'lov API", callback_data="adm_auto_payment"),
    )
    builder.row(
        types.InlineKeyboardButton(text="⚙️ To'lov turlari", callback_data="adm_manage_payment_methods"),
        types.InlineKeyboardButton(text="🧾 To'lov izohi", callback_data="adm_edit_setting|payment_note|payment"),
    )
    builder.row(
        types.InlineKeyboardButton(text="💵 To'lov so'rovlari", callback_data="adm_pending_payments"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def wallets_keyboard(wallets):
    builder = InlineKeyboardBuilder()
    for wallet in wallets[:15]:
        label = f"🗑 {wallet['label']} | {wallet['wallet_number']}"
        builder.row(types.InlineKeyboardButton(text=label[:64], callback_data=f"adm_wallet_del|{wallet['id']}"))
    builder.row(types.InlineKeyboardButton(text="➕ Yangi hamyon", callback_data="adm_wallet_add"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_payment_methods"))
    return builder.as_markup()


def auto_payment_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🌐 API URL", callback_data="adm_edit_setting|auto_payment_url|auto_payment"),
        types.InlineKeyboardButton(text="🔑 API KEY", callback_data="adm_edit_setting|auto_payment_key|auto_payment"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_payment_methods"))
    return builder.as_markup()


def manage_payment_methods_keyboard(methods):
    builder = InlineKeyboardBuilder()
    for m in methods:
        status = "🟢" if m["is_active"] else "⚪"
        builder.row(types.InlineKeyboardButton(text=f"{status} {m['name']}", callback_data=f"adm_pm_card|{m['id']}"))
    
    builder.row(types.InlineKeyboardButton(text="➕ Yangi qo'shish", callback_data="adm_pm_add"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_payment_methods"))
    return builder.as_markup()


def payment_method_card_keyboard(method):
    builder = InlineKeyboardBuilder()
    toggle_text = "⏸ Muzlatish" if method["is_active"] else "▶️ Faollashtirish"
    builder.row(
        types.InlineKeyboardButton(text="📝 Nomini o'zgartirish", callback_data=f"adm_pm_edit_name|{method['id']}"),
        types.InlineKeyboardButton(text="📖 Yo'riqnomani tahrirlash", callback_data=f"adm_pm_edit_instr|{method['id']}"),
    )
    builder.row(
        types.InlineKeyboardButton(text=toggle_text, callback_data=f"adm_pm_toggle|{method['id']}"),
        types.InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"adm_pm_delete|{method['id']}"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_manage_payment_methods"))
    return builder.as_markup()


def pending_payments_keyboard(transactions):
    builder = InlineKeyboardBuilder()
    for tx in transactions[:15]:
        text = f"#{tx['id']} | {tx['method']} | {tx['amount']:,.0f}"
        builder.row(types.InlineKeyboardButton(text=text[:64], callback_data=f"adm_tx_card|{tx['id']}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_payment_methods"))
    return builder.as_markup()


def payment_card_keyboard(transaction):
    builder = InlineKeyboardBuilder()
    if transaction["status"] == "pending":
        builder.row(
            types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_tx_{transaction['id']}"),
            types.InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_tx_{transaction['id']}"),
        )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_pending_payments"))
    return builder.as_markup()


def promo_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🎟 Kodni o'rnatish", callback_data="adm_edit_setting|promo_code_value|promo"),
        types.InlineKeyboardButton(text="💰 Bonusni o'rnatish", callback_data="adm_edit_setting|promo_code_bonus|promo"),
    )
    builder.row(types.InlineKeyboardButton(text="🗓 Muddatni belgilash", callback_data="adm_edit_setting|promo_code_expires_at|promo"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def premium_keyboard(is_visible):
    builder = InlineKeyboardBuilder()
    toggle_text = "⏸ Premiumni yashirish" if is_visible else "▶️ Premiumni ko'rsatish"
    builder.row(types.InlineKeyboardButton(text=toggle_text, callback_data=f"adm_group|tg_premium|{0 if is_visible else 1}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def sms_settings_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔑 API kalitni o'zgartirish", callback_data="adm_edit_setting|sms_api_key|sms"))
    builder.row(types.InlineKeyboardButton(text="🆔 ID tahrirlash", callback_data="adm_edit_setting|sms_api_id|sms"))
    builder.row(types.InlineKeyboardButton(text="⚖️ Foizni yangilash", callback_data="adm_edit_setting|sms_markup_percent|sms"))
    builder.row(types.InlineKeyboardButton(text="💵 Kursni belgilash", callback_data="adm_edit_setting|usd_rate|sms"))
    builder.row(types.InlineKeyboardButton(text="🌐 API URL", callback_data="adm_edit_setting|sms_api_url|sms"))
    builder.row(types.InlineKeyboardButton(text="🌍 Davlat narxlari", callback_data="adm_sms_countries|1"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def sms_countries_keyboard(countries, page, total_pages):
    builder = InlineKeyboardBuilder()
    for country_id, country_info in countries:
        flag = detect_country_flag(country_info.get("name", ""))
        builder.add(
            types.InlineKeyboardButton(
                text=f"{flag} {country_info.get('name', 'Unknown')}",
                callback_data=f"adm_sms_country|{country_id}|{page}",
            )
        )
    builder.adjust(2)

    navigation = []
    if page > 1:
        navigation.append(types.InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"adm_sms_countries|{page - 1}"))
    if page < total_pages:
        navigation.append(types.InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"adm_sms_countries|{page + 1}"))
    if navigation:
        builder.row(*navigation)
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_sms_settings"))
    return builder.as_markup()


def sms_country_services_keyboard(country_id, page):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✈️ Telegram", callback_data=f"adm_sms_service|{country_id}|tg|{page}"),
        types.InlineKeyboardButton(text="💬 WhatsApp", callback_data=f"adm_sms_service|{country_id}|wa|{page}"),
    )
    builder.row(
        types.InlineKeyboardButton(text="📸 Instagram", callback_data=f"adm_sms_service|{country_id}|ig|{page}"),
        types.InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"adm_sms_countries|{page}"),
    )
    return builder.as_markup()


def orders_keyboard(orders, current_filter):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⏳ Jarayonda", callback_data="adm_orders|processing"),
        types.InlineKeyboardButton(text="✅ Tugallangan", callback_data="adm_orders|completed"),
    )
    builder.row(
        types.InlineKeyboardButton(text="📋 Barchasi", callback_data="adm_orders|all"),
        types.InlineKeyboardButton(text="❌ Bekor", callback_data="adm_orders|cancelled"),
    )
    builder.row(types.InlineKeyboardButton(text="⚠️ Xato", callback_data="adm_orders|failed"))
    for order in orders[:10]:
        status = ORDER_STATUS_LABELS.get(order["status"], order["status"])
        label = f"#{order['id']} {status} | {order['amount']:,.0f}"
        builder.row(types.InlineKeyboardButton(text=label[:64], callback_data=f"adm_order_card|{order['id']}|{current_filter}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_order_check"))
    return builder.as_markup()


def order_card_keyboard(order_id, current_filter):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⏳ Kutilayotgan", callback_data=f"adm_order_status|{order_id}|pending|{current_filter}"),
        types.InlineKeyboardButton(text="🔄 Jarayonda", callback_data=f"adm_order_status|{order_id}|processing|{current_filter}"),
    )
    builder.row(
        types.InlineKeyboardButton(text="✅ Tugallangan", callback_data=f"adm_order_status|{order_id}|completed|{current_filter}"),
        types.InlineKeyboardButton(text="❌ Bekor", callback_data=f"adm_order_status|{order_id}|cancelled|{current_filter}"),
    )
    builder.row(types.InlineKeyboardButton(text="⚠️ Xato", callback_data=f"adm_order_status|{order_id}|failed|{current_filter}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"adm_orders|{current_filter}"))
    return builder.as_markup()


def mask_secret(value):
    if not value:
        return "sozlanmagan"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def is_cancel_text(text):
    return (text or "").strip().lower() in {"/cancel", "cancel", "bekor"}


def parse_required_channels(raw_value):
    return [line.strip() for line in str(raw_value or "").splitlines() if line.strip()]


def normalize_channel_username(raw_value):
    value = (raw_value or "").strip()
    if value.startswith("https://t.me/"):
        value = value[len("https://t.me/"):]
    elif value.startswith("http://t.me/"):
        value = value[len("http://t.me/"):]
    elif value.startswith("t.me/"):
        value = value[len("t.me/"):]
    value = value.strip().strip("/")
    if value.startswith("@"):
        value = value[1:]
    if not value:
        return None
    if not all(char.isalnum() or char == "_" for char in value):
        return None
    if len(value) < 4 or len(value) > 32:
        return None
    return f"@{value}"


def extract_broadcast_payload(message: types.Message):
    if message.text:
        return {
            "kind": "text",
            "text": message.text,
            "summary": message.text[:140],
        }
    if message.photo:
        caption = message.caption or ""
        return {
            "kind": "photo",
            "file_id": message.photo[-1].file_id,
            "caption": caption,
            "summary": caption[:140] or "Rasmli xabar",
        }
    if message.video:
        caption = message.caption or ""
        return {
            "kind": "video",
            "file_id": message.video.file_id,
            "caption": caption,
            "summary": caption[:140] or "Video xabar",
        }
    if message.document:
        caption = message.caption or ""
        return {
            "kind": "document",
            "file_id": message.document.file_id,
            "caption": caption,
            "summary": caption[:140] or f"Fayl: {message.document.file_name or 'document'}",
        }
    if message.animation:
        caption = message.caption or ""
        return {
            "kind": "animation",
            "file_id": message.animation.file_id,
            "caption": caption,
            "summary": caption[:140] or "GIF xabar",
        }
    return None


async def render_broadcast_review(message: types.Message, payload):
    audience_size = len(await db.get_all_user_ids())
    kind_label = {
        "text": "Matn",
        "photo": "Rasm",
        "video": "Video",
        "document": "Fayl",
        "animation": "GIF",
    }.get(payload["kind"], payload["kind"])
    summary = payload.get("summary", "").strip() or "Preview mavjud"
    text = (
        "📨 <b>Tarqatish preview</b>\n\n"
        f"Turi: <b>{kind_label}</b>\n"
        f"Qabul qiluvchilar: <b>{audience_size}</b>\n"
        f"Qisqa ko'rinish: <code>{escape(summary[:180])}</code>\n\n"
        "Hammasi to'g'ri bo'lsa yuboring yoki tahrirlashni tanlang."
    )
    await message.answer(text, reply_markup=broadcast_review_keyboard())


async def send_broadcast_payload(bot: Bot, user_id: int, payload):
    kind = payload["kind"]
    if kind == "text":
        await bot.send_message(user_id, payload["text"], parse_mode=None)
        return
    if kind == "photo":
        await bot.send_photo(user_id, payload["file_id"], caption=payload.get("caption") or None, parse_mode=None)
        return
    if kind == "video":
        await bot.send_video(user_id, payload["file_id"], caption=payload.get("caption") or None, parse_mode=None)
        return
    if kind == "document":
        await bot.send_document(user_id, payload["file_id"], caption=payload.get("caption") or None, parse_mode=None)
        return
    if kind == "animation":
        await bot.send_animation(user_id, payload["file_id"], caption=payload.get("caption") or None, parse_mode=None)
        return
    raise ValueError(f"Unsupported broadcast payload: {kind}")


async def send_or_edit(target, text, reply_markup):
    if isinstance(target, types.CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest:
            await target.message.answer(text, reply_markup=reply_markup)
    else:
        await target.answer(text, reply_markup=reply_markup)


async def get_float_setting(key, default):
    raw_value = await db.get_setting(key, str(default))
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return float(default)


def balance_to_uzs_text(balance_value, currency, usd_rate):
    currency_code = str(currency or "USD").upper()
    if currency_code == "USD":
        return f"{round(balance_value * usd_rate):,.0f} so'm"
    if currency_code == "UZS":
        return f"{round(balance_value):,.0f} so'm"
    return f"{currency_code} bo'yicha avtomatik UZS hisoblanmadi"


def provider_to_local_status(raw_status):
    status = str(raw_status or "").strip().lower()
    if status in {"completed", "complete", "success", "successful"}:
        return "completed"
    if status in {"canceled", "cancelled", "canceled_partial", "partial", "refunded"}:
        return "cancelled"
    if status in {"failed", "fail", "error", "rejected"}:
        return "failed"
    if status in {"pending", "in progress", "inprogress", "processing", "progress"}:
        return "processing"
    return None


async def render_return_view(target, return_view):
    if return_view == "content":
        await render_content_settings(target)
    elif return_view == "guide":
        await render_guide_settings(target)
    elif return_view == "discounts":
        await render_discount_settings(target)
    elif return_view == "bot_status":
        await render_bot_status(target)
    elif return_view == "markup":
        await render_markup_settings(target)
    elif return_view == "api":
        await render_api_settings(target)
    elif return_view == "referral":
        await render_referral_settings(target)
    elif return_view == "channels":
        await render_channels_settings(target)
    elif return_view == "payment":
        await render_payment_methods(target)
    elif return_view == "wallets":
        await render_wallets(target)
    elif return_view == "auto_payment":
        await render_auto_payment_settings(target)
    elif return_view == "promo":
        await render_promocode_settings(target)
    elif return_view == "daily_bonus":
        await render_daily_bonus_settings(target)
    elif return_view == "sms":
        await render_sms_settings(target)
    else:
        await render_main(target)


async def render_main(target):
    text = (
        "🧩 <b>Admin Panel</b>\n\n"
        "Barcha boshqaruv bo'limlari inline menyuda jamlandi. Kerakli bo'limni tanlang."
    )
    await send_or_edit(target, text, admin_main_keyboard())


async def render_stats(target):
    stats = await db.get_admin_stats()
    usd_rate = await get_float_setting("usd_rate", USD_RATE)
    balance_data = await smm_client.get_balance()
    panel_balance = float(balance_data.get("balance", 0) or 0)
    panel_currency = str(balance_data.get("currency", "USD") or "USD").upper()
    panel_balance_uzs = balance_to_uzs_text(panel_balance, panel_currency, usd_rate)
    order_stats = await db.get_order_stats_by_status()
    pending_count = order_stats.get("pending", 0)
    processing_count = order_stats.get("processing", 0)
    completed_count = order_stats.get("completed", 0)
    cancelled_count = order_stats.get("cancelled", 0)
    failed_count = order_stats.get("failed", 0)
    geography = await db.get_user_country_stats(limit=6)
    geo_text = "\n".join(f"• {item['country']}: <b>{item['count']}</b>" for item in geography) or "• Ma'lumot yo'q"

    text = (
        "📊 <b>Statistika</b>\n\n"
        "┌─ <b>Buyurtmalar Holati</b> ─┐\n"
        f"│ ⏳ Kutilayotgan: <b>{pending_count}</b>\n"
        f"│ 🔄 Jarayonda: <b>{processing_count}</b>\n"
        f"│ ✅ Tugallangan: <b>{completed_count}</b>\n"
        f"│ ❌ Bekor qilingan: <b>{cancelled_count}</b>\n"
        f"│ ⚠️ Muvaffaqiyatsiz: <b>{failed_count}</b>\n"
        "└──────────────────────┘\n\n"
        "┌─ <b>Foydalanuvchilar</b> ─┐\n"
        f"│ 👥 Jami: <b>{stats['total_users']}</b>\n"
        f"│ 🆕 Bugun: <b>{stats['today_users']}</b>\n"
        "└──────────────────────┘\n\n"
        "<b>🌍 Geografiya</b>\n"
        f"{geo_text}\n\n"
        "┌─ <b>Moliya</b> ─┐\n"
        f"│ 💰 Kunlik aylanma: <b>{stats['today_sales']:,.0f}</b> so'm\n"
        f"│ 💵 Jami tushum: <b>{stats['total_income']:,.0f}</b> so'm\n"
        f"│ 📅 Oylik tushum: <b>{stats['monthly_income']:,.0f}</b> so'm\n"
        f"│ 🏦 Foydalanuvchilar balansi: <b>{stats['total_user_balances']:,.0f}</b> so'm\n"
        "└──────────────────────┘\n\n"
        "┌─ <b>Panel Balansi</b> ─┐\n"
        f"│ 💵 Balans ({panel_currency}): <b>{panel_balance:,.2f}</b>\n"
        f"│ 🇺🇿 So'mda: <b>{panel_balance_uzs}</b>\n"
        f"│ 💳 Dollar kursi: <b>{usd_rate:,.0f}</b> so'm\n"
        "└──────────────────────┘"
    )
    await send_or_edit(target, text, stats_keyboard())


async def render_services_hub(target):
    services = await db.get_smm_services(active_only=False, include_hidden_groups=True)
    groups = await db.get_smm_groups(active_only=False, include_hidden=True)
    markup = await get_float_setting("markup_percentage", DEFAULT_SMM_MARKUP_PERCENT)
    text = (
        "🛍 <b>Xizmatlarni sozlash</b>\n\n"
        f"💸 Xizmatlar soni: <b>{len(services)}</b>\n"
        f"🗂 Guruhlar soni: <b>{len(groups)}</b>\n"
        f"⚖️ Joriy ustama: <b>{markup:.2f}%</b>\n"
        "Narxlar API `rate` qiymatidan avtomatik final narx sifatida hisoblanadi."
    )
    await send_or_edit(target, text, service_hub_keyboard())


async def render_content_settings(target):
    settings = await db.get_settings(["admin_username", "news_channel", "news_group", "orders_channel"])
    text = (
        "📝 <b>Ma'lumotlarni tahrirlash</b>\n\n"
        f"👤 Admin user: <code>{settings.get('admin_username', '')}</code>\n"
        f"📢 Yangiliklar kanal: <code>{settings.get('news_channel', '')}</code>\n"
        f"👥 Yangiliklar guruh: <code>{settings.get('news_group', '')}</code>\n"
        f"📦 Buyurtmalar kanal: <code>{settings.get('orders_channel', '')}</code>"
    )
    await send_or_edit(target, text, content_keyboard())


async def render_guide_settings(target):
    settings = await db.get_settings(["guide_text", "support_link"])
    text = (
        "📚 <b>Qo'llanma sozlash</b>\n\n"
        f"📚 Matn: <code>{(settings.get('guide_text') or '')[:80]}</code>\n"
        f"🆘 Support: <code>{settings.get('support_link', '')}</code>"
    )
    await send_or_edit(target, text, guide_keyboard())


async def render_discount_settings(target):
    discount = await get_float_setting("discount_percent", 0)
    text = (
        "🛍 <b>Chegirmalar</b>\n\n"
        f"Joriy umumiy chegirma: <b>{discount:.2f}%</b>\n"
        "Bu qiymat promo/aksiya boshqaruvi uchun saqlanadi."
    )
    await send_or_edit(
        target,
        text,
        single_edit_keyboard("✏️ Chegirmani tahrirlash", "adm_edit_setting|discount_percent|discounts"),
    )


async def render_bot_status(target):
    bot_status = await db.get_setting("bot_status", "active")
    license_label = await db.get_setting("license_label", "Demo")
    is_active = str(bot_status).strip().lower() == "active"
    text = (
        "🤖 <b>Bot holati</b>\n\n"
        f"Joriy holat: <b>{'Ishlayapti' if is_active else 'Pauza'}</b>\n"
        f"Litsenziya: <b>{license_label}</b>\n"
        "Pauza holatida oddiy foydalanuvchilarga xizmat ko'rsatilmaydi."
    )
    await send_or_edit(target, text, bot_status_keyboard(is_active))


async def render_markup_settings(target):
    markup = await get_float_setting("markup_percentage", DEFAULT_SMM_MARKUP_PERCENT)
    text = (
        "⚖️ <b>Foizni o'rnatish</b>\n\n"
        f"API narxlariga qo'shiladigan ustama: <b>{markup:.2f}%</b>\n\n"
        "Formula: <code>final_price = rate + (rate * markup_percentage / 100)</code>"
    )
    await send_or_edit(
        target,
        text,
        single_edit_keyboard("✏️ Ustamani tahrirlash", "adm_edit_setting|markup_percentage|markup"),
    )


async def render_api_settings(target):
    settings = await db.get_settings(["smm_api_url", "smm_api_key", "sms_api_url", "sms_api_key"])
    text = (
        "🔑 <b>API sozlamalari</b>\n\n"
        f"🌐 Smmwiz URL:\n<code>{settings.get('smm_api_url', '')}</code>\n\n"
        f"🔑 Smmwiz KEY:\n<code>{mask_secret(settings.get('smm_api_key'))}</code>\n\n"
        f"🌐 SMS URL:\n<code>{settings.get('sms_api_url', '')}</code>\n\n"
        f"🔑 SMS KEY:\n<code>{mask_secret(settings.get('sms_api_key'))}</code>"
    )
    await send_or_edit(target, text, api_keyboard())


async def render_referral_settings(target):
    referral_bonus = await get_float_setting("referral_bonus", REFERRAL_BONUS)
    referral_enabled = await db.get_setting_bool("referral_enabled", True)
    diamond_bonus = await get_float_setting("referral_diamond_uz", 2)
    diamond_foreign = await get_float_setting("referral_diamond_foreign", 2)
    cash_uz = await get_float_setting("referral_cash_uz", 100)
    cash_foreign = await get_float_setting("referral_cash_foreign", 50)
    banner_file_id = await db.get_setting("referral_banner_file_id", "")
    
    status = "✅ Yoqilgan" if referral_enabled else "❌ O'chirilgan"
    banner_status = "Yuklangan" if banner_file_id else "Yuklanmagan"
    text = (
        "⚙️ <b>Referal sozlamalari</b>\n\n"
        f"Holat: <b>{status}</b>\n\n"
        "┌─ <b>Olmos (Diamond) Bonus</b> ─┐\n"
        f"│ 🇺🇿 O'zbekiston: <b>{diamond_bonus:.0f} ta</b>\n"
        f"│ 🌍 Chet el: <b>{diamond_foreign:.0f} ta</b>\n"
        "└──────────────────────┘\n\n"
        "┌─ <b>Pul (Cash) Bonus</b> ─┐\n"
        f"│ 🇺🇿 O'zbekiston: <b>{cash_uz:,.0f} so'm</b>\n"
        f"│ 🌍 Chet el: <b>{cash_foreign:,.0f} so'm</b>\n"
        "└──────────────────────┘\n\n"
        f"💵 Umumiy pul bonusi: <b>{referral_bonus:,.0f}</b> so'm\n"
        f"🖼 Banner: <b>{banner_status}</b>"
    )
    await send_or_edit(target, text, referral_settings_keyboard(referral_enabled))


async def render_order_hub(target):
    pending = await db.count_orders_by_status("pending")
    processing = await db.count_orders_by_status("processing")
    completed = await db.count_orders_by_status("completed")
    cancelled = await db.count_orders_by_status("cancelled")
    failed = await db.count_orders_by_status("failed")
    total = pending + processing + completed + cancelled + failed
    
    text = (
        "🔍 <b>Buyurtma tekshirish</b>\n\n"
        "┌─ <b>Buyurtmalar soni</b> ─┐\n"
        f"│ ⏳ Kutilayotgan: <b>{pending}</b>\n"
        f"│ 🔄 Jarayonda: <b>{processing}</b>\n"
        f"│ ✅ Tugallangan: <b>{completed}</b>\n"
        f"│ ❌ Bekor: <b>{cancelled}</b>\n"
        f"│ ⚠️ Xato: <b>{failed}</b>\n"
        f"│ 📊 Jami: <b>{total}</b>\n"
        "└──────────────────────┘"
    )
    await send_or_edit(target, text, order_check_keyboard())


async def render_orders(target, status_filter):
    orders = await db.get_recent_orders(limit=15, status=status_filter)
    if not orders:
        title = "Barchasi" if status_filter == "all" else ORDER_STATUS_LABELS.get(status_filter, status_filter)
        text = f"📦 <b>Buyurtmalar</b>\n\nFilter: <b>{title}</b>\n\n❌ Buyurtma topilmadi."
        return await send_or_edit(target, text, orders_keyboard([], status_filter))
    
    title = "Barchasi" if status_filter == "all" else ORDER_STATUS_LABELS.get(status_filter, status_filter)
    lines = [f"📦 <b>Buyurtmalar</b>\n", f"Filter: <b>{title}</b> ({len(orders)})", ""]
    for order in orders:
        status_emoji = {
            "pending": "⏳",
            "processing": "🔄",
            "completed": "✅",
            "cancelled": "❌",
            "failed": "⚠️",
        }.get(order["status"], "❓")
        lines.append(f"{status_emoji} #{order['id']} | {order['amount']:,.0f} so'm")
    
    text = "\n".join(lines)
    await send_or_edit(target, text, orders_keyboard(orders, status_filter))


async def render_order_card(target, order, current_filter):
    if not order:
        return await send_or_edit(target, "❌ Buyurtma topilmadi.", inline_back_keyboard("adm_order_check"))

    user = await db.get_user(order["user_id"])
    user_name = user["full_name"] if user else "N/A"
    user_internal_id = user["id"] if user else "?"
    
    status_icon = {
        "pending": "⏳",
        "processing": "🔄",
        "completed": "✅",
        "cancelled": "❌",
        "failed": "⚠️",
    }.get(order["status"], "❓")
    
    text = (
        "📦 <b>Buyurtma kartasi</b>\n\n"
        "┌─ <b>Asosiy ma'lumotlar</b> ─┐\n"
        f"│ 🆔 Buyurtma ID: <code>{order['id']}</code>\n"
        f"│ 👤 Foydalanuvchi: <b>{user_name}</b>\n"
        f"│ 🔗 Telegram ID: <code>{order['user_id']}</code>\n"
        f"│ 📍 Tartib ID: <code>{user_internal_id}</code>\n"
        "└──────────────────────┘\n\n"
        "┌─ <b>Buyurtma tafsiloti</b> ─┐\n"
        f"│ 📌 Xizmat: <b>{order['service_name']}</b>\n"
        f"│ 🎯 Target: <code>{order['target'][:50]}</code>\n"
        f"│ 💰 Summa: <b>{order['amount']:,.0f}</b> so'm\n"
        f"│ 🌐 Panel ID: <code>{order['external_id']}</code>\n"
        "└──────────────────────┘\n\n"
        "┌─ <b>Holat</b> ─┐\n"
        f"│ {status_icon} <b>{ORDER_STATUS_LABELS.get(order['status'], order['status'])}</b>\n"
        f"│ 🕒 Sana: <code>{order['created_at']}</code>\n"
        "└──────────────────────┘"
    )
    await send_or_edit(target, text, order_card_keyboard(order["id"], current_filter))


async def render_channels_settings(target):
    channels_text = await db.get_setting("required_channels", "")
    channels = parse_required_channels(channels_text)
    channels_preview = "\n".join(f"• <code>{escape(channel)}</code>" for channel in channels[:12]) or "• Hali kanal qo'shilmagan"
    text = (
        "📢 <b>Kanallar</b>\n\n"
        "Majburiy a'zolik uchun kanallar shu yerda boshqariladi.\n\n"
        f"Jami kanallar: <b>{len(channels)}</b>\n\n"
        f"{channels_preview}"
    )
    await send_or_edit(
        target,
        text,
        channels_keyboard(len(channels)),
    )


async def render_payment_methods(target):
    settings = await db.get_settings(
        ["payment_note", "min_payment_amount", "auto_payment_url", "auto_payment_key"]
    )
    wallets = await db.get_payment_wallets(active_only=False)
    methods = await db.get_payment_methods()
    min_payment_amount = settings.get("min_payment_amount", "5000")
    text = (
        "💳 <b>To'lov usullari</b>\n\n"
        f"🏦 Hamyonlar soni: <b>{len(wallets)}</b>\n"
        f"⚙️ To'lov tizimlari: <b>{len(methods)}</b>\n"
        f"💵 Limit: <b>{min_payment_amount}</b> - <b>1000000</b> so'm\n"
        f"🤖 Avto-to'lov URL: <code>{(settings.get('auto_payment_url') or 'sozlanmagan')[:70]}</code>\n"
        f"📝 Izoh: <code>{(settings.get('payment_note') or '')[:70]}</code>"
    )
    await send_or_edit(target, text, payment_methods_keyboard(settings))


async def render_wallets(target):
    wallets = await db.get_payment_wallets(active_only=False)
    if not wallets:
        return await send_or_edit(
            target,
            "📋 <b>Hamyonlar</b>\n\nHali hamyon qo'shilmagan.",
            wallets_keyboard([]),
        )
    lines = ["📋 <b>Hamyonlar ro'yxati</b>\n"]
    for wallet in wallets:
        status = "🟢" if wallet["is_active"] else "⚪"
        lines.append(
            f"{status} <b>{wallet['label']}</b> | <code>{wallet['wallet_number']}</code> | {wallet['holder_name']}"
        )
    await send_or_edit(target, "\n".join(lines), wallets_keyboard(wallets))


async def render_auto_payment_settings(target):
    settings = await db.get_settings(["auto_payment_url", "auto_payment_key"])
    text = (
        "🤖 <b>Avto-to'lov API</b>\n\n"
        f"🌐 URL:\n<code>{settings.get('auto_payment_url', '') or 'sozlanmagan'}</code>\n\n"
        f"🔑 KEY:\n<code>{mask_secret(settings.get('auto_payment_key'))}</code>"
    )
    await send_or_edit(target, text, auto_payment_keyboard())


async def render_pending_payments(target):
    transactions = await db.get_pending_transactions(limit=15)
    if not transactions:
        return await send_or_edit(target, "💵 Pending to'lovlar yo'q.", inline_back_keyboard("adm_payment_methods"))
    text = "💵 <b>Pending to'lov so'rovlari</b>\n\nKerakli so'rovni tanlang."
    await send_or_edit(target, text, pending_payments_keyboard(transactions))


async def render_manage_payment_methods(target):
    methods = await db.get_payment_methods()
    text = (
        "⚙️ <b>To'lov turlarini boshqarish</b>\n\n"
        "Bu yerda siz yangi to'lov turlarini qo'shishingiz, o'chirishingiz yoki vaqtincha muzlatib qo'yishingiz mumkin."
    )
    await send_or_edit(target, text, manage_payment_methods_keyboard(methods))


async def render_payment_method_card(target, method):
    if not method:
        return await send_or_edit(target, "❌ To'lov turi topilmadi.", inline_back_keyboard("adm_manage_payment_methods"))
    
    status = "🟢 Aktiv" if method["is_active"] else "⚪ Muzlatilgan"
    text = (
        "💳 <b>To'lov turi kartasi</b>\n\n"
        f"🆔 ID: <code>{method['id']}</code>\n"
        f"📝 Nomi: <b>{method['name']}</b>\n"
        f"🚥 Holati: <b>{status}</b>\n"
        f"📖 Yo'riqnoma: \n<i>{method['instruction']}</i>"
    )
    await send_or_edit(target, text, payment_method_card_keyboard(method))


async def render_payment_card(target, transaction):
    if not transaction:
        return await send_or_edit(target, "❌ Tranzaksiya topilmadi.", inline_back_keyboard("adm_pending_payments"))
    user = await db.get_user(transaction["user_id"])
    internal_id = user["id"] if user else "?"
    text = (
        "💵 <b>To'lov kartasi</b>\n\n"
        f"🧾 So'rov ID: <code>{transaction['id']}</code>\n"
        f"🆔 Tartib ID: <code>{internal_id}</code>\n"
        f"👤 Telegram ID: <code>{transaction['user_id']}</code>\n"
        f"💳 Usul: <b>{transaction['method']}</b>\n"
        f"💰 Summa: <b>{transaction['amount']:,.0f}</b> so'm\n"
        f"📊 Holat: <b>{transaction['status']}</b>"
    )
    await send_or_edit(target, text, payment_card_keyboard(transaction))


async def render_promocode_settings(target):
    settings = await db.get_settings(["promo_code_value", "promo_code_bonus", "promo_code_expires_at"])
    promo_code = settings.get("promo_code_value", "") or "o'rnatilmagan"
    promo_bonus = float(settings.get("promo_code_bonus", "0") or 0)
    promo_expire = settings.get("promo_code_expires_at", "") or "cheklanmagan"
    text = (
        "🎟 <b>Promokod</b>\n\n"
        f"Kod: <code>{promo_code}</code>\n"
        f"Bonus: <b>{promo_bonus:,.0f}</b> so'm\n"
        f"Muddat: <b>{promo_expire}</b>"
    )
    await send_or_edit(target, text, promo_keyboard())


async def render_daily_bonus_settings(target):
    daily_bonus = await get_float_setting("daily_bonus_amount", DAILY_BONUS_DEFAULT)
    text = (
        "🎁 <b>Kunlik bonus</b>\n\n"
        f"Foydalanuvchi uchun kunlik bonus: <b>{daily_bonus:,.0f}</b> so'm"
    )
    await send_or_edit(
        target,
        text,
        single_edit_keyboard("✏️ Bonus miqdorini tahrirlash", "adm_edit_setting|daily_bonus_amount|daily_bonus"),
    )


async def render_premium_settings(target):
    groups = await db.get_smm_groups(active_only=False, include_hidden=True)
    premium_group = next((group for group in groups if group["group_key"] == "tg_premium"), None)
    is_visible = bool(premium_group["is_visible"]) if premium_group else True
    visibility_text = "Ko'rinadi" if is_visible else "Yashirilgan"
    text = (
        "💎 <b>Premium olish xizmati</b>\n\n"
        f"Telegram Premium guruhi holati: <b>{visibility_text}</b>"
    )
    await send_or_edit(target, text, premium_keyboard(is_visible))


async def render_sms_settings(target):
    settings = await db.get_settings(["sms_api_url", "sms_api_key", "sms_markup_percent", "sms_api_id"])
    sms_markup = await get_float_setting("sms_markup_percent", 0)
    usd_rate = await get_float_setting("usd_rate", USD_RATE)
    sms_balance = await sms_client.get_balance()
    balance_value = float(sms_balance.get("balance", 0) or 0)
    balance_currency = str(sms_balance.get("currency", "USD") or "USD").upper()
    is_configured = bool((settings.get("sms_api_url") or "").strip() and (settings.get("sms_api_key") or "").strip())
    connection_text = "Faol" if is_configured else "Sozlanmagan"
    local_balance_text = balance_to_uzs_text(balance_value, balance_currency, usd_rate)

    text = (
        "📞 <b>Nomer sozlamalari</b>\n\n"
        "┌─ <b>Holat paneli</b> ─┐\n"
        f"│ 🔗 Ulanish: <b>{connection_text}</b>\n"
        f"│ 💵 Balans ({balance_currency}): <b>{balance_value:,.2f}</b>\n"
        f"│ 🇺🇿 Balans so'mda: <b>{local_balance_text}</b>\n"
        f"│ ⚖️ Joriy foiz: <b>{sms_markup:.2f}%</b>\n"
        f"│ 💳 Dollar kursi: <b>{usd_rate:,.0f}</b> so'm\n"
        "└──────────────────────┘\n\n"
        f"🆔 API ID: <code>{settings.get('sms_api_id', '') or 'sozlanmagan'}</code>\n\n"
        f"🌐 SMS URL:\n<code>{settings.get('sms_api_url', '')}</code>\n\n"
        f"🔑 SMS KEY:\n<code>{mask_secret(settings.get('sms_api_key'))}</code>"
    )
    await send_or_edit(target, text, sms_settings_keyboard())


async def render_sms_countries(target, page):
    countries_data = await sms_client.get_countries("tg")
    if not countries_data:
        return await send_or_edit(target, "❌ Davlatlar ro'yxatini olib bo'lmadi.", inline_back_keyboard("adm_sms_settings"))

    items = list(countries_data.items())
    total_pages = max(1, math.ceil(len(items) / SMS_COUNTRY_PAGE_SIZE))
    page = min(max(page, 1), total_pages)
    start = (page - 1) * SMS_COUNTRY_PAGE_SIZE
    current_items = items[start:start + SMS_COUNTRY_PAGE_SIZE]
    lines = [f"📞 <b>Davlat narxlari</b>\n\nSahifa: <b>{page}/{total_pages}</b>"]
    for _, country in current_items:
        flag = detect_country_flag(country.get("name", ""))
        lines.append(f"{flag} <b>{country.get('name', 'Unknown')}</b>")
    await send_or_edit(target, "\n".join(lines), sms_countries_keyboard(current_items, page, total_pages))


async def render_sms_country_services(target, country_id, page):
    countries = await sms_client.get_countries("tg")
    country = countries.get(country_id)
    if not country:
        return await send_or_edit(target, "❌ Davlat topilmadi.", inline_back_keyboard("adm_sms_settings"))
    flag = detect_country_flag(country.get("name", ""))
    text = (
        f"{flag} <b>{country.get('name', 'Unknown')}</b>\n\n"
        "Qaysi servis narxini tahrirlash kerakligini tanlang."
    )
    await send_or_edit(target, text, sms_country_services_keyboard(country_id, page))


async def render_sms_service_editor(target, country_id, service_code, page):
    country_sets = await sms_client.get_countries(service_code)
    country = country_sets.get(country_id)
    if not country:
        return await send_or_edit(target, "❌ Bu servis uchun davlat topilmadi.", inline_back_keyboard(f"adm_sms_country|{country_id}|{page}"))

    api_price = float(country.get("price", 0) or 0)
    override_price = await db.get_sms_price_override(country_id, service_code)
    effective_price = await db.get_sms_price(country_id, service_code, api_price)
    service_name = {"tg": "Telegram", "wa": "WhatsApp", "ig": "Instagram"}.get(service_code, service_code.upper())
    flag = detect_country_flag(country.get("name", ""))
    override_text = f"<b>{override_price:,.0f}</b> so'm" if override_price is not None else "<b>yo'q</b>"
    text = (
        f"{flag} <b>{country.get('name', 'Unknown')}</b> | <b>{service_name}</b>\n\n"
        f"API narxi: <b>{api_price:,.0f}</b> so'm\n"
        f"Override narx: {override_text}\n"
    )
    text += f"Foydalanuvchi ko'radigan narx: <b>{effective_price:,.0f}</b> so'm\n\nYangi override narxni yuboring."
    await send_or_edit(target, text, inline_back_keyboard(f"adm_sms_country|{country_id}|{page}"))


async def render_user_card(target, user):
    if not user:
        return await send_or_edit(target, "❌ Foydalanuvchi topilmadi.", back_main_keyboard())
    status_text = "banned" if user["is_blocked"] else "active"
    text = (
        "👤 <b>Foydalanuvchi</b>\n\n"
        f"ID: <code>{user['user_id']}</code>\n"
        f"Tartib ID: <code>{user['id']}</code>\n"
        f"Balans: <b>{user['balance']:,.0f}</b> so'm\n"
        f"Holati: <b>{status_text}</b>"
    )
    await send_or_edit(target, text, user_card_keyboard(user))


@router.message(Command("admin"))
async def admin_start_handler(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_LIST:
        return
    await state.clear()
    await render_main(message)


@router.callback_query(F.data == "adm_main", F.from_user.id.in_(ADMIN_LIST))
async def admin_main_callback(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_main(call)
    await call.answer()


@router.callback_query(F.data == "adm_services", F.from_user.id.in_(ADMIN_LIST))
async def services_hub_callback(call: types.CallbackQuery):
    await render_services_hub(call)
    await call.answer()


@router.callback_query(F.data == "adm_content", F.from_user.id.in_(ADMIN_LIST))
async def content_callback(call: types.CallbackQuery):
    await render_content_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_broadcast", F.from_user.id.in_(ADMIN_LIST))
async def broadcast_callback(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.broadcasting)
    await call.message.answer(
        "✉️ Yuboriladigan xabarni jo'nating.\nXabar qabul qilingach `Yuborish` va `Tahrirlash` tugmalari chiqadi.",
        reply_markup=back_main_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "adm_broadcast_edit", F.from_user.id.in_(ADMIN_LIST))
async def broadcast_edit_callback(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.broadcasting)
    await call.message.answer("✏️ Yangi xabarni yuboring.", reply_markup=back_main_keyboard())
    await call.answer()


@router.callback_query(F.data == "adm_broadcast_cancel", F.from_user.id.in_(ADMIN_LIST))
async def broadcast_cancel_callback(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("❌ Xabar yuborish bekor qilindi.")
    await render_main(call)
    await call.answer()


@router.callback_query(F.data == "adm_broadcast_send", F.from_user.id.in_(ADMIN_LIST))
async def broadcast_send_callback(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    payload = data.get("broadcast_payload")
    if not payload:
        await state.clear()
        await call.answer("Draft topilmadi. Qaytadan yuboring.", show_alert=True)
        return

    user_ids = await db.get_all_user_ids()
    sent = 0
    failed = 0

    await call.message.answer(f"✉️ Tarqatish boshlandi. Jami: <b>{len(user_ids)}</b>")
    for index, user_id in enumerate(user_ids, start=1):
        try:
            await send_broadcast_payload(bot, user_id, payload)
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await send_broadcast_payload(bot, user_id, payload)
                sent += 1
            except Exception:
                failed += 1
        except (TelegramForbiddenError, TelegramBadRequest, Exception):
            failed += 1

        if index % BROADCAST_BATCH_SIZE == 0:
            await asyncio.sleep(BROADCAST_BATCH_PAUSE)

    await state.clear()
    await call.message.answer(
        f"✅ Xabar yuborish yakunlandi.\nYuborildi: <b>{sent}</b>\nXatolik: <b>{failed}</b>",
        reply_markup=back_main_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "adm_stats", F.from_user.id.in_(ADMIN_LIST))
async def stats_callback(call: types.CallbackQuery):
    await render_stats(call)
    await call.answer()


@router.callback_query(F.data == "adm_refresh_orders", F.from_user.id.in_(ADMIN_LIST))
async def refresh_orders_callback(call: types.CallbackQuery, bot: Bot):
    orders = await db.get_syncable_orders(limit=50)
    checked = 0
    updated = 0
    for order in orders:
        checked += 1
        try:
            provider_status = await smm_client.check_status(order["external_id"])
        except Exception:
            provider_status = None
        local_status = provider_to_local_status(provider_status)
        if local_status and local_status != order["status"]:
            updated_order = await db.update_order_status(order["id"], local_status)
            if local_status == "completed":
                await process_referral_reward(bot, updated_order)
            updated += 1
    await render_stats(call)
    await call.answer(f"{checked} ta buyurtma tekshirildi, {updated} tasi yangilandi.")


@router.callback_query(F.data == "adm_top_users", F.from_user.id.in_(ADMIN_LIST))
async def top_users_callback(call: types.CallbackQuery):
    await render_top_users(call)
    await call.answer()


async def render_top_users(target):
    users = await db.get_top_users(limit=100)
    if not users:
        return await send_or_edit(target, "❌ Foydalanuvchilar topilmadi.", inline_back_keyboard("adm_stats"))

    lines = ["🏆 <b>TOP 100 Balans</b>\n"]
    for i, user in enumerate(users[:100], 1):
        name = (user["full_name"] or user["username"] or "N/A")[:18]
        balance = float(user["balance"] or 0)
        lines.append(f"{i:02}. <b>{name}</b> — <b>{balance:,.0f}</b> so'm")

    await send_or_edit(target, "\n".join(lines), inline_back_keyboard("adm_stats"))


@router.callback_query(F.data == "adm_user_lookup", F.from_user.id.in_(ADMIN_LIST))
async def user_lookup_callback(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.searching_user)
    await call.message.answer("👤 Foydalanuvchi ID yoki Tartib ID yuboring.", reply_markup=back_main_keyboard())
    await call.answer()


@router.callback_query(F.data == "adm_guide", F.from_user.id.in_(ADMIN_LIST))
async def guide_callback(call: types.CallbackQuery):
    await render_guide_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_discounts", F.from_user.id.in_(ADMIN_LIST))
async def discounts_callback(call: types.CallbackQuery):
    await render_discount_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_bot_status", F.from_user.id.in_(ADMIN_LIST))
async def bot_status_callback(call: types.CallbackQuery):
    await render_bot_status(call)
    await call.answer()


@router.callback_query(F.data == "adm_markup", F.from_user.id.in_(ADMIN_LIST))
async def markup_callback(call: types.CallbackQuery):
    await render_markup_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_api", F.from_user.id.in_(ADMIN_LIST))
async def api_callback(call: types.CallbackQuery):
    await render_api_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_referral", F.from_user.id.in_(ADMIN_LIST))
async def referral_callback(call: types.CallbackQuery):
    await render_referral_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_referral_banner", F.from_user.id.in_(ADMIN_LIST))
async def referral_banner_callback(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.editing_setting)
    await state.update_data(edit_type="referral_banner", return_view="referral")
    await call.message.answer("🖼 Referal banner rasmini yuboring.", reply_markup=back_main_keyboard())
    await call.answer()


@router.callback_query(F.data == "adm_clear_referrals", F.from_user.id.in_(ADMIN_LIST))
async def clear_referrals_callback(call: types.CallbackQuery):
    cleared = await db.clear_referrals()
    await call.message.answer(f"✅ {cleared} ta referal tozalandi.")
    await render_referral_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_order_check", F.from_user.id.in_(ADMIN_LIST))
async def order_check_callback(call: types.CallbackQuery):
    await render_order_hub(call)
    await call.answer()


@router.callback_query(F.data == "adm_channels", F.from_user.id.in_(ADMIN_LIST))
async def channels_callback(call: types.CallbackQuery):
    await render_channels_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_channel_add", F.from_user.id.in_(ADMIN_LIST))
async def channel_add_callback(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.editing_setting)
    await state.update_data(edit_type="channel_add", return_view="channels")
    await call.message.answer(
        "📢 Kanal username yuboring.\n\nMisol: <code>@my_channel</code>",
        reply_markup=back_main_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "adm_channel_remove_menu", F.from_user.id.in_(ADMIN_LIST))
async def channel_remove_menu_callback(call: types.CallbackQuery):
    channels = parse_required_channels(await db.get_setting("required_channels", ""))
    if not channels:
        await call.answer("O'chirish uchun kanal yo'q.", show_alert=True)
        return
    await send_or_edit(
        call,
        "🗑 <b>Kanalni o'chirish</b>\n\nOlib tashlanadigan kanalni tanlang.",
        channels_remove_keyboard(channels),
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_channel_remove|"), F.from_user.id.in_(ADMIN_LIST))
async def channel_remove_callback(call: types.CallbackQuery):
    channels = parse_required_channels(await db.get_setting("required_channels", ""))
    try:
        index = int(call.data.split("|")[1])
    except (IndexError, ValueError):
        await call.answer("Kanal topilmadi.", show_alert=True)
        return

    if index < 0 or index >= len(channels):
        await call.answer("Kanal topilmadi.", show_alert=True)
        return

    removed_channel = channels.pop(index)
    await db.set_setting("required_channels", "\n".join(channels))
    await render_channels_settings(call)
    await call.answer(f"{removed_channel} olib tashlandi.")


@router.callback_query(F.data == "adm_payment_methods", F.from_user.id.in_(ADMIN_LIST))
async def payment_methods_callback(call: types.CallbackQuery):
    await render_payment_methods(call)
    await call.answer()


@router.callback_query(F.data == "adm_wallets", F.from_user.id.in_(ADMIN_LIST))
async def wallets_callback(call: types.CallbackQuery):
    await render_wallets(call)
    await call.answer()


@router.callback_query(F.data == "adm_wallet_add", F.from_user.id.in_(ADMIN_LIST))
async def wallet_add_callback(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.editing_setting)
    await state.update_data(edit_type="wallet_add", return_view="wallets")
    await call.message.answer(
        "➕ Yangi hamyonni `Nomi | Ega | Raqam` formatida yuboring.\nMasalan: `Uzcard | Ali Valiyev | 8600 1234 5678 9012`",
        reply_markup=back_main_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_wallet_del|"), F.from_user.id.in_(ADMIN_LIST))
async def wallet_delete_callback(call: types.CallbackQuery):
    wallet_id = int(call.data.split("|")[1])
    await db.delete_payment_wallet(wallet_id)
    await render_wallets(call)
    await call.answer("Hamyon o'chirildi.")


@router.callback_query(F.data == "adm_auto_payment", F.from_user.id.in_(ADMIN_LIST))
async def auto_payment_callback(call: types.CallbackQuery):
    await render_auto_payment_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_promocode", F.from_user.id.in_(ADMIN_LIST))
async def promocode_callback(call: types.CallbackQuery):
    await render_promocode_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_daily_bonus", F.from_user.id.in_(ADMIN_LIST))
async def daily_bonus_callback(call: types.CallbackQuery):
    await render_daily_bonus_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_premium", F.from_user.id.in_(ADMIN_LIST))
async def premium_callback(call: types.CallbackQuery):
    await render_premium_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_sms_settings", F.from_user.id.in_(ADMIN_LIST))
async def sms_settings_callback(call: types.CallbackQuery):
    await render_sms_settings(call)
    await call.answer()


@router.callback_query(F.data.startswith("adm_edit_setting|"), F.from_user.id.in_(ADMIN_LIST))
async def edit_setting_callback(call: types.CallbackQuery, state: FSMContext):
    _, setting_key, return_view = call.data.split("|", 2)
    prompts = {
        "start_text": "👋 Yangi start xabarini yuboring.",
        "payment_note": "💰 Yangi to'lov izohini yuboring.",
        "channels_text": "📢 Yangi kanal matnini yuboring.",
        "required_channels": "📢 Majburiy kanallar ro'yxatini yangi qatordan yuboring.",
        "guide_text": "📚 Yangi qo'llanma matnini yuboring.",
        "support_link": "🆘 Yangi support linkni yuboring.",
        "discount_percent": "🛍 Yangi chegirma foizini yuboring.",
        "markup_percentage": "⚖️ Yangi ustama foizini yuboring.",
        "smm_markup_percent": "⚖️ Yangi ustama foizini yuboring.",
        "smm_api_url": "🌐 Yangi Smmwiz URL yuboring.",
        "smm_api_key": "🔑 Yangi Smmwiz KEY yuboring.",
        "sms_api_url": "🌐 Yangi SMS URL yuboring.",
        "sms_api_key": "🔑 Yangi SMS KEY yuboring.",
        "sms_api_id": "🆔 Yangi SMS API ID yuboring.",
        "license_label": "🔐 Litsenziya nomi yoki kalitini yuboring.",
        "referral_bonus": "⚙️ Yangi referal bonusini yuboring.",
        "referral_diamond_uz": "💎 O'zbekiston uchun olmos bonusini yuboring.",
        "referral_diamond_foreign": "💎 Chet el uchun olmos bonusini yuboring.",
        "referral_cash_uz": "💵 O'zbekiston uchun pul bonusini yuboring.",
        "referral_cash_foreign": "💵 Chet el uchun pul bonusini yuboring.",
        "card_number": "💳 Yangi karta raqamini yuboring.",
        "card_holder": "👤 Yangi karta egasi nomini yuboring.",
        "admin_username": "👤 Admin usernameni yuboring. Masalan: @admin",
        "news_channel": "📢 Yangiliklar kanalini yuboring. Masalan: @kanal",
        "news_group": "👥 Yangiliklar guruhini yuboring.",
        "orders_channel": "📦 Buyurtmalar kanalini yuboring.",
        "promo_code_value": "🎟 Promokod matnini yuboring.",
        "promo_code_bonus": "💰 Promokod bonusini yuboring.",
        "promo_code_expires_at": "🗓 Promokod muddatini yuboring. Masalan: 2026-12-31 23:59",
        "daily_bonus_amount": "🎁 Kunlik bonus miqdorini yuboring.",
        "sms_markup_percent": "⚖️ SMS uchun yangi ustama foizini yuboring.",
        "usd_rate": "💳 Yangi dollar kursini yuboring.",
        "min_payment_amount": "💵 Minimal to'lov summasini yuboring.",
        "auto_payment_url": "🌐 Avto-to'lov API URL yuboring.",
        "auto_payment_key": "🔑 Avto-to'lov API KEY yuboring.",
    }
    await state.set_state(AdminStates.editing_setting)
    await state.update_data(edit_type="setting", setting_key=setting_key, return_view=return_view)
    await call.message.answer(prompts.get(setting_key, "Yangi qiymatni yuboring."), reply_markup=back_main_keyboard())
    await call.answer()


@router.callback_query(F.data.startswith("adm_toggle_setting|"), F.from_user.id.in_(ADMIN_LIST))
async def toggle_setting_callback(call: types.CallbackQuery):
    _, setting_key, next_value, return_view = call.data.split("|", 3)
    await db.set_setting(setting_key, next_value)
    await call.answer("Holat yangilandi.")
    await render_return_view(call, return_view)


@router.callback_query(F.data.startswith("adm_set_bot_status|"), F.from_user.id.in_(ADMIN_LIST))
async def set_bot_status_callback(call: types.CallbackQuery):
    next_status = call.data.split("|")[1]
    await db.set_setting("bot_status", next_status)
    await render_bot_status(call)
    await call.answer("Bot holati yangilandi.")


@router.message(AdminStates.searching_user, F.from_user.id.in_(ADMIN_LIST))
async def user_search_input(message: types.Message, state: FSMContext):
    if is_cancel_text(message.text):
        await state.clear()
        return await render_main(message)
    if not message.text or not message.text.isdigit():
        return await message.answer("⚠️ ID raqam bo'lishi kerak.")

    user = await db.get_user_by_internal_id(int(message.text))
    if not user:
        user = await db.get_user(int(message.text))
    if not user:
        return await message.answer("❌ Foydalanuvchi topilmadi.")

    await state.clear()
    await render_user_card(message, user)


@router.callback_query(F.data.startswith("adm_user_toggle|"), F.from_user.id.in_(ADMIN_LIST))
async def user_toggle_callback(call: types.CallbackQuery, bot: Bot):
    _, user_id, status = call.data.split("|")
    user = await db.block_user(int(user_id), int(status))
    if not user:
        await call.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    try:
        if int(status) == 1:
            await bot.send_message(int(user_id), "🔔 Siz admin tomonidan ban qilindingiz.")
        else:
            await bot.send_message(int(user_id), "✅ Siz blokdan chiqarildingiz.")
    except Exception:
        pass
    await render_user_card(call, user)
    await call.answer("Foydalanuvchi holati yangilandi.")


@router.callback_query(F.data.startswith("adm_user_balance|"), F.from_user.id.in_(ADMIN_LIST))
async def user_balance_start(call: types.CallbackQuery, state: FSMContext):
    _, user_id, mode = call.data.split("|")
    user = await db.get_user(int(user_id))
    if not user:
        await call.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    await state.set_state(AdminStates.editing_user_balance)
    await state.update_data(target_user_id=int(user_id), balance_mode=mode)
    prompt = "qo'shish" if mode == "add" else "ayirish"
    await call.message.answer(f"{user['full_name']} uchun qancha pul {prompt} kerakligini yuboring.", reply_markup=back_main_keyboard())
    await call.answer()


@router.message(AdminStates.editing_user_balance, F.from_user.id.in_(ADMIN_LIST))
async def user_balance_input(message: types.Message, state: FSMContext, bot: Bot):
    if is_cancel_text(message.text):
        await state.clear()
        return await render_main(message)
    try:
        amount = int(message.text)
    except Exception:
        return await message.answer("⚠️ Summani son bilan yuboring.")
    if amount <= 0:
        return await message.answer("⚠️ Summa 0 dan katta bo'lishi kerak.")

    data = await state.get_data()
    user_id = data["target_user_id"]
    mode = data["balance_mode"]
    current_user = await db.get_user(user_id)
    if not current_user:
        await state.clear()
        return await message.answer("❌ Foydalanuvchi topilmadi.")
    if mode == "subtract" and int(current_user["balance"] or 0) < amount:
        return await message.answer("⚠️ Foydalanuvchi balansida buncha mablag' yo'q.")
    delta = amount if mode == "add" else -amount
    balance_updated = await db.update_balance(user_id, delta)
    if not balance_updated:
        return await message.answer("вљ пёЏ Balansni yangilab bo'lmadi. Qaytadan urinib ko'ring.")
    if delta > 0:
        await db.add_transaction(user_id, delta, method="Admin", status="confirmed")
    user = await db.get_user(user_id)

    try:
        notice = f"Balansingiz {amount:,.0f} so'mga yangilandi." if mode == "add" else f"Balansingizdan {amount:,.0f} so'm ayirildi."
        await bot.send_message(user_id, notice)
    except Exception:
        pass

    await state.clear()
    await message.answer("✅ Balans yangilandi.")
    await render_user_card(message, user)


@router.callback_query(F.data == "adm_order_search", F.from_user.id.in_(ADMIN_LIST))
async def order_search_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.searching_order)
    await call.message.answer("🔍 Buyurtma ID yuboring.", reply_markup=back_main_keyboard())
    await call.answer()


@router.message(AdminStates.searching_order, F.from_user.id.in_(ADMIN_LIST))
async def order_search_input(message: types.Message, state: FSMContext):
    if is_cancel_text(message.text):
        await state.clear()
        return await render_main(message)
    if not message.text or not message.text.isdigit():
        return await message.answer("⚠️ Buyurtma ID raqam bo'lishi kerak.")
    order = await db.get_order(int(message.text))
    await state.clear()
    await render_order_card(message, order, "all")


@router.callback_query(F.data.startswith("adm_orders|"), F.from_user.id.in_(ADMIN_LIST))
async def orders_callback(call: types.CallbackQuery):
    status_filter = call.data.split("|")[1]
    await render_orders(call, status_filter)
    await call.answer()


@router.callback_query(F.data.startswith("adm_order_card|"), F.from_user.id.in_(ADMIN_LIST))
async def order_card_callback(call: types.CallbackQuery):
    _, order_id, current_filter = call.data.split("|")
    order = await db.get_order(int(order_id))
    await render_order_card(call, order, current_filter)
    await call.answer()


@router.callback_query(F.data.startswith("adm_order_status|"), F.from_user.id.in_(ADMIN_LIST))
async def order_status_callback(call: types.CallbackQuery, bot: Bot):
    _, order_id, status, current_filter = call.data.split("|")
    previous_order = await db.get_order(int(order_id))
    order = await db.update_order_status(int(order_id), status)
    if (
        order
        and status == "completed"
        and previous_order
        and str(previous_order["status"]) != "completed"
    ):
        await process_referral_reward(bot, order)
    await render_order_card(call, order, current_filter)
    await call.answer("Buyurtma holati yangilandi.")


@router.callback_query(F.data == "adm_prices", F.from_user.id.in_(ADMIN_LIST))
async def prices_callback(call: types.CallbackQuery):
    services = await db.get_smm_services(active_only=False, include_hidden_groups=True)
    await send_or_edit(
        call,
        "💸 <b>Narxlar</b>\n\nXizmatni tanlab narxini yoki holatini boshqaring.",
        prices_keyboard(services),
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm_price_card|"), F.from_user.id.in_(ADMIN_LIST))
async def price_card_callback(call: types.CallbackQuery):
    service_id = call.data.split("|")[1]
    service = await db.get_smm_service(service_id, active_only=False, include_hidden_groups=True)
    if not service:
        await call.answer("Xizmat topilmadi.", show_alert=True)
        return
    text = (
        "💸 <b>Xizmat kartasi</b>\n\n"
        f"🆔 Service ID: <code>{service['service_id']}</code>\n"
        f"📂 Guruh: <b>{service['group_label']}</b>\n"
        f"📌 Nomi: <b>{service['name']}</b>\n"
        f"💵 API narxi: <b>${service['provider_price_usd']:,.4f}</b>\n"
        f"🇺🇿 Bot narxi: <b>{service['price_per_1000']:,.0f}</b> so'm\n"
        f"📉 Min: <b>{service['min_order']:,}</b>\n"
        f"📈 Max: <b>{service['max_order']:,}</b>\n"
        f"🚦 Holat: <b>{'Aktiv' if service['is_active'] else 'O‘chirilgan'}</b>"
    )
    await send_or_edit(call, text, price_card_keyboard(service))
    await call.answer()


@router.callback_query(F.data.startswith("adm_price_edit|"), F.from_user.id.in_(ADMIN_LIST))
async def price_edit_start(call: types.CallbackQuery, state: FSMContext):
    service_id = call.data.split("|")[1]
    service = await db.get_smm_service(service_id, active_only=False, include_hidden_groups=True)
    if not service:
        await call.answer("Xizmat topilmadi.", show_alert=True)
        return
    await state.set_state(AdminStates.editing_service_price)
    await state.update_data(service_id=service_id)
    await call.message.answer(f"{service['name']} uchun yangi UZS narx yuboring.", reply_markup=back_main_keyboard())
    await call.answer()


@router.message(AdminStates.editing_service_price, F.from_user.id.in_(ADMIN_LIST))
async def price_edit_input(message: types.Message, state: FSMContext):
    if is_cancel_text(message.text):
        await state.clear()
        return await render_main(message)
    try:
        price = int(message.text)
    except Exception:
        return await message.answer("⚠️ Narx son bo'lishi kerak.")
    if price <= 0:
        return await message.answer("⚠️ Narx 0 dan katta bo'lishi kerak.")
    service_id = (await state.get_data())["service_id"]
    await db.update_smm_service_price(service_id, price)
    service = await db.get_smm_service(service_id, active_only=False, include_hidden_groups=True)
    await state.clear()
    await message.answer("✅ Narx saqlandi.")
    await price_card_callback_from_message(message, service)


async def price_card_callback_from_message(message, service):
    text = (
        "💸 <b>Xizmat kartasi</b>\n\n"
        f"🆔 Service ID: <code>{service['service_id']}</code>\n"
        f"📂 Guruh: <b>{service['group_label']}</b>\n"
        f"📌 Nomi: <b>{service['name']}</b>\n"
        f"💵 API narxi: <b>${service['provider_price_usd']:,.4f}</b>\n"
        f"🇺🇿 Bot narxi: <b>{service['price_per_1000']:,.0f}</b> so'm\n"
        f"📉 Min: <b>{service['min_order']:,}</b>\n"
        f"📈 Max: <b>{service['max_order']:,}</b>\n"
        f"🚦 Holat: <b>{'Aktiv' if service['is_active'] else 'O‘chirilgan'}</b>"
    )
    await message.answer(text, reply_markup=price_card_keyboard(service))


@router.callback_query(F.data.startswith("adm_price_toggle|"), F.from_user.id.in_(ADMIN_LIST))
async def price_toggle_callback(call: types.CallbackQuery):
    _, service_id, next_state = call.data.split("|")
    await db.set_smm_service_active(service_id, int(next_state))
    service = await db.get_smm_service(service_id, active_only=False, include_hidden_groups=True)
    await price_card_callback_from_message(call.message, service)
    await call.answer("Xizmat holati yangilandi.")


@router.callback_query(F.data == "adm_categories", F.from_user.id.in_(ADMIN_LIST))
async def categories_callback(call: types.CallbackQuery):
    groups = await db.get_smm_groups(active_only=False, include_hidden=True)
    await send_or_edit(call, "🗂 <b>Kategoriyalar</b>\n\nGuruhlarni yashirish yoki ko'rsatish mumkin.", categories_keyboard(groups))
    await call.answer()


@router.callback_query(F.data.startswith("adm_group|"), F.from_user.id.in_(ADMIN_LIST))
async def group_toggle_callback(call: types.CallbackQuery):
    _, group_key, next_state = call.data.split("|")
    await db.set_group_visibility(group_key, int(next_state))
    if group_key == "tg_premium":
        await render_premium_settings(call)
    else:
        groups = await db.get_smm_groups(active_only=False, include_hidden=True)
        await send_or_edit(call, "🗂 <b>Kategoriyalar</b>\n\nGuruhlar yangilandi.", categories_keyboard(groups))
    await call.answer("Kategoriya holati yangilandi.")


@router.callback_query(F.data == "adm_sync_services", F.from_user.id.in_(ADMIN_LIST))
async def sync_services_callback(call: types.CallbackQuery):
    await call.message.edit_text("⏳ Smmwiz xizmatlari sinxron qilinmoqda...")
    services = await smm_client.get_services(apply_markup=False)
    if not isinstance(services, list):
        error_msg = services.get("error", "Noma'lum xatolik") if isinstance(services, dict) else "Noma'lum xatolik"
        await call.answer(f"Xatolik: {error_msg}", show_alert=True)
        await render_services_hub(call)
        return
    await db.sync_smm_services(services)
    await render_services_hub(call)
    await call.answer("Xizmatlar yangilandi.")


@router.callback_query(F.data == "adm_pending_payments", F.from_user.id.in_(ADMIN_LIST))
async def pending_payments_callback(call: types.CallbackQuery):
    await render_pending_payments(call)
    await call.answer()


@router.callback_query(F.data.startswith("adm_tx_card|"), F.from_user.id.in_(ADMIN_LIST))
async def tx_card_callback(call: types.CallbackQuery):
    transaction = await db.get_transaction(int(call.data.split("|")[1]))
    await render_payment_card(call, transaction)
    await call.answer()


@router.callback_query(F.data == "adm_sms_countries|1", F.from_user.id.in_(ADMIN_LIST))
async def sms_countries_default_callback(call: types.CallbackQuery):
    await render_sms_countries(call, 1)
    await call.answer()


@router.callback_query(F.data.startswith("adm_sms_countries|"), F.from_user.id.in_(ADMIN_LIST))
async def sms_countries_callback(call: types.CallbackQuery):
    page = int(call.data.split("|")[1])
    await render_sms_countries(call, page)
    await call.answer()


@router.callback_query(F.data.startswith("adm_sms_country|"), F.from_user.id.in_(ADMIN_LIST))
async def sms_country_callback(call: types.CallbackQuery):
    _, country_id, page = call.data.split("|")
    await render_sms_country_services(call, country_id, int(page))
    await call.answer()


@router.callback_query(F.data.startswith("adm_sms_service|"), F.from_user.id.in_(ADMIN_LIST))
async def sms_service_callback(call: types.CallbackQuery, state: FSMContext):
    _, country_id, service_code, page = call.data.split("|")
    await state.set_state(AdminStates.editing_setting)
    await state.update_data(
        edit_type="sms_override",
        country_id=country_id,
        service_code=service_code,
        return_view="sms",
        page=int(page),
    )
    await render_sms_service_editor(call, country_id, service_code, int(page))
    await call.answer()


@router.message(AdminStates.editing_setting, F.photo, F.from_user.id.in_(ADMIN_LIST))
async def setting_photo_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("edit_type") != "referral_banner":
        return
    photo = message.photo[-1]
    await db.set_setting("referral_banner_file_id", photo.file_id)
    await state.clear()
    await message.answer("✅ Referal banner saqlandi.")
    await render_referral_settings(message)


@router.message(AdminStates.editing_setting, F.from_user.id.in_(ADMIN_LIST))
async def setting_input(message: types.Message, state: FSMContext, bot: Bot):
    if is_cancel_text(message.text):
        await state.clear()
        return await render_main(message)

    data = await state.get_data()
    edit_type = data.get("edit_type", "setting")
    raw_value = (message.text or "").strip()

    if edit_type == "sms_override":
        try:
            price = int(raw_value)
        except Exception:
            return await message.answer("⚠️ Narx son bo'lishi kerak.")
        if price <= 0:
            return await message.answer("⚠️ Narx 0 dan katta bo'lishi kerak.")
        await db.set_sms_price_override(data["country_id"], data["service_code"], price)
        await state.clear()
        await message.answer("✅ SMS override narxi saqlandi.")
        return await render_sms_country_services(message, data["country_id"], data["page"])

    if edit_type == "wallet_add":
        parts = [part.strip() for part in raw_value.split("|")]
        if len(parts) != 3 or not all(parts):
            return await message.answer("⚠️ Format: `Nomi | Ega | Raqam`", reply_markup=back_main_keyboard())
        try:
            await db.add_payment_wallet(parts[0], parts[1], parts[2])
        except Exception:
            return await message.answer("⚠️ Bu hamyon allaqachon mavjud yoki format xato.")
        await state.clear()
        await message.answer("✅ Yangi hamyon qo'shildi.")
        return await render_wallets(message)

    if edit_type == "channel_add":
        username = normalize_channel_username(raw_value)
        if not username:
            return await message.answer(
                "⚠️ To'g'ri kanal username yuboring.\n\nMisol: <code>@my_channel</code>",
                reply_markup=back_main_keyboard(),
            )

        channels = parse_required_channels(await db.get_setting("required_channels", ""))
        lowered = {channel.casefold() for channel in channels}
        if username.casefold() in lowered:
            return await message.answer("⚠️ Bu kanal ro'yxatda allaqachon mavjud.", reply_markup=back_main_keyboard())

        try:
            chat = await bot.get_chat(username)
            me = await bot.get_me()
            bot_member = await bot.get_chat_member(username, me.id)
        except Exception:
            return await message.answer(
                "⚠️ Bot bu kanalni tekshira olmadi.\n\n"
                "Kanal public bo'lsin va bot kanalga admin qilingan bo'lsin.",
                reply_markup=back_main_keyboard(),
            )

        if getattr(chat, "type", "") not in {"channel", "supergroup"}:
            return await message.answer(
                "⚠️ Faqat kanal yoki supergroup username qo'shish mumkin.",
                reply_markup=back_main_keyboard(),
            )

        if getattr(bot_member, "status", "") not in {"administrator", "creator"}:
            return await message.answer(
                "⚠️ Tekshirish ishlashi uchun botni shu kanalga admin qiling.",
                reply_markup=back_main_keyboard(),
            )

        channels.append(username)
        await db.set_setting("required_channels", "\n".join(channels))
        await state.clear()
        await message.answer("✅ Kanal qo'shildi.")
        return await render_channels_settings(message)

    setting_key = data["setting_key"]
    return_view = data["return_view"]

    decimal_settings = {
        "discount_percent",
        "markup_percentage",
        "smm_markup_percent",
        "sms_markup_percent",
    }
    integer_settings = {
        "referral_bonus",
        "referral_diamond_uz",
        "referral_diamond_foreign",
        "referral_cash_uz",
        "referral_cash_foreign",
        "promo_code_bonus",
        "daily_bonus_amount",
        "min_payment_amount",
        "usd_rate",
    }
    url_settings = {"support_link", "smm_api_url", "sms_api_url", "auto_payment_url"}

    if raw_value == "-":
        value_to_save = ""
        await db.set_setting(setting_key, value_to_save)
        await state.clear()
        await message.answer("✅ Sozlama tozalandi.")
        return await render_return_view(message, return_view)

    if setting_key in integer_settings:
        try:
            value = int(raw_value)
        except Exception:
            return await message.answer("⚠️ Butun son yuboring.")
        if value < 0:
            return await message.answer("⚠️ Manfiy qiymat bo'lmaydi.")
        value_to_save = str(value)
    elif setting_key in decimal_settings:
        try:
            value = float(raw_value)
        except Exception:
            return await message.answer("⚠️ Son yuboring.")
        if value < 0:
            return await message.answer("⚠️ Manfiy qiymat bo'lmaydi.")
        value_to_save = str(value)
    elif setting_key in url_settings:
        if not raw_value.startswith("http"):
            return await message.answer("⚠️ URL `http` yoki `https` bilan boshlanishi kerak.")
        value_to_save = raw_value
    else:
        if not raw_value:
            return await message.answer("⚠️ Bo'sh qiymat yubormang.")
        value_to_save = raw_value

    await db.set_setting(setting_key, value_to_save)
    await state.clear()
    await message.answer("✅ Sozlama saqlandi.")
    await render_return_view(message, return_view)


@router.message(AdminStates.broadcasting, F.from_user.id.in_(ADMIN_LIST))
async def broadcast_input(message: types.Message, state: FSMContext):
    if message.text and is_cancel_text(message.text):
        await state.clear()
        return await render_main(message)

    payload = extract_broadcast_payload(message)
    if not payload:
        return await message.answer(
            "⚠️ Faqat matn, rasm, video, GIF yoki fayl yuborish mumkin.",
            reply_markup=back_main_keyboard(),
        )

    await state.update_data(broadcast_payload=payload)
    await state.set_state(AdminStates.broadcast_review)
    await render_broadcast_review(message, payload)


@router.message(AdminStates.broadcast_review, F.from_user.id.in_(ADMIN_LIST))
async def broadcast_review_input(message: types.Message, state: FSMContext):
    if message.text and is_cancel_text(message.text):
        await state.clear()
        return await render_main(message)
    await message.answer(
        "📨 Draft tayyor. Pastdagi `Yuborish` yoki `Tahrirlash` tugmalaridan foydalaning.",
        reply_markup=broadcast_review_keyboard(),
    )


@router.callback_query(F.data == "adm_manage_payment_methods", F.from_user.id.in_(ADMIN_LIST))
async def manage_payment_methods_callback(call: types.CallbackQuery):
    await render_manage_payment_methods(call)
    await call.answer()


@router.callback_query(F.data.startswith("adm_pm_card|"), F.from_user.id.in_(ADMIN_LIST))
async def pm_card_callback(call: types.CallbackQuery):
    method_id = int(call.data.split("|")[1])
    method = await db.get_payment_method(method_id)
    await render_payment_method_card(call, method)
    await call.answer()


@router.callback_query(F.data.startswith("adm_pm_toggle|"), F.from_user.id.in_(ADMIN_LIST))
async def pm_toggle_callback(call: types.CallbackQuery):
    method_id = int(call.data.split("|")[1])
    method = await db.get_payment_method(method_id)
    if method:
        await db.update_payment_method(method_id, is_active=not method["is_active"])
        method = await db.get_payment_method(method_id)
        await render_payment_method_card(call, method)
        await call.answer("Holat yangilandi.")
    else:
        await call.answer("Topilmadi.", show_alert=True)


@router.callback_query(F.data.startswith("adm_pm_delete|"), F.from_user.id.in_(ADMIN_LIST))
async def pm_delete_callback(call: types.CallbackQuery):
    method_id = int(call.data.split("|")[1])
    await db.delete_payment_method(method_id)
    await render_manage_payment_methods(call)
    await call.answer("O'chirildi.")


@router.callback_query(F.data == "adm_pm_add", F.from_user.id.in_(ADMIN_LIST))
async def pm_add_callback(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.adding_payment_method_name)
    await call.message.answer("📝 Yangi to'lov turi nomini yuboring (masalan: Humo yoki Uzcard).", reply_markup=back_main_keyboard())
    await call.answer()


@router.message(AdminStates.adding_payment_method_name, F.from_user.id.in_(ADMIN_LIST))
async def pm_add_name_input(message: types.Message, state: FSMContext):
    if is_cancel_text(message.text):
        await state.clear()
        return await render_main(message)
    
    await state.update_data(new_pm_name=message.text)
    await state.set_state(AdminStates.adding_payment_method_instr)
    await message.answer(f"📖 <b>{message.text}</b> uchun to'lov yo'riqnomasini yuboring (karta raqami va h.k.).", reply_markup=back_main_keyboard())


@router.message(AdminStates.adding_payment_method_instr, F.from_user.id.in_(ADMIN_LIST))
async def pm_add_instr_input(message: types.Message, state: FSMContext):
    if is_cancel_text(message.text):
        await state.clear()
        return await render_main(message)
    
    data = await state.get_data()
    name = data["new_pm_name"]
    callback_data = name.lower().replace(" ", "_")[:20]
    await db.add_payment_method(name, callback_data, message.text)
    await state.clear()
    await message.answer("✅ Yangi to'lov turi qo'shildi.")
    await render_manage_payment_methods(message)


@router.callback_query(F.data.startswith("adm_pm_edit_name|"), F.from_user.id.in_(ADMIN_LIST))
async def pm_edit_name_callback(call: types.CallbackQuery, state: FSMContext):
    method_id = int(call.data.split("|")[1])
    await state.set_state(AdminStates.editing_payment_method_name)
    await state.update_data(edit_pm_id=method_id)
    await call.message.answer("📝 Yangi nomni yuboring.", reply_markup=back_main_keyboard())
    await call.answer()


@router.message(AdminStates.editing_payment_method_name, F.from_user.id.in_(ADMIN_LIST))
async def pm_edit_name_input(message: types.Message, state: FSMContext):
    if is_cancel_text(message.text):
        await state.clear()
        return await render_main(message)
    
    data = await state.get_data()
    await db.update_payment_method(data["edit_pm_id"], name=message.text)
    method = await db.get_payment_method(data["edit_pm_id"])
    await state.clear()
    await message.answer("✅ Nom yangilandi.")
    await render_payment_method_card(message, method)


@router.callback_query(F.data.startswith("adm_pm_edit_instr|"), F.from_user.id.in_(ADMIN_LIST))
async def pm_edit_instr_callback(call: types.CallbackQuery, state: FSMContext):
    method_id = int(call.data.split("|")[1])
    await state.set_state(AdminStates.editing_payment_method_instr)
    await state.update_data(edit_pm_id=method_id)
    await call.message.answer("📖 Yangi yo'riqnomani yuboring.", reply_markup=back_main_keyboard())
    await call.answer()


@router.message(AdminStates.editing_payment_method_instr, F.from_user.id.in_(ADMIN_LIST))
async def pm_edit_instr_input(message: types.Message, state: FSMContext):
    if is_cancel_text(message.text):
        await state.clear()
        return await render_main(message)
    
    data = await state.get_data()
    await db.update_payment_method(data["edit_pm_id"], instruction=message.text)
    method = await db.get_payment_method(data["edit_pm_id"])
    await state.clear()
    await message.answer("✅ Yo'riqnoma yangilandi.")
    await render_payment_method_card(message, method)


@router.callback_query(F.data.startswith("approve_tx_"), F.from_user.id.in_(ADMIN_LIST))
async def approve_tx_callback(call: types.CallbackQuery, bot: Bot):
    transaction_id = int(call.data.split("_")[2])
    transaction, status = await db.confirm_transaction(transaction_id)
    if status == "not_found":
        await call.answer("Tranzaksiya topilmadi.", show_alert=True)
        return
    if status == "user_not_found":
        await call.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    if status == "already_processed":
        await call.answer(f"Bu to'lov allaqachon {transaction['status']} qilingan.", show_alert=True)
        return
    if status == "invalid_transaction":
        await call.answer("Bu tranzaksiya tasdiqlash uchun yaroqsiz.", show_alert=True)
        return
    try:
        await bot.send_message(transaction["user_id"], f"✅ To'lov tasdiqlandi. +{transaction['amount']:,.0f} so'm")
    except Exception:
        pass
    await render_payment_card(call, transaction)
    await call.answer("To'lov tasdiqlandi.")


@router.callback_query(F.data.startswith("reject_tx_"), F.from_user.id.in_(ADMIN_LIST))
async def reject_tx_callback(call: types.CallbackQuery, bot: Bot):
    transaction_id = int(call.data.split("_")[2])
    transaction, status = await db.reject_transaction(transaction_id)
    if status == "not_found":
        await call.answer("Tranzaksiya topilmadi.", show_alert=True)
        return
    if status == "already_processed":
        await call.answer(f"Bu to'lov allaqachon {transaction['status']} qilingan.", show_alert=True)
        return
    try:
        await bot.send_message(transaction["user_id"], "❌ To'lov rad etildi.")
    except Exception:
        pass
    await render_payment_card(call, transaction)
    await call.answer("To'lov rad etildi.")
