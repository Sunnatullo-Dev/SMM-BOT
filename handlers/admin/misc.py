import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_LIST, DAILY_BONUS_DEFAULT, DEFAULT_SMM_MARKUP_PERCENT, REFERRAL_BONUS, USD_RATE
from database.models import db
from states.bot_states import AdminStates
from utils.api_client import smm_client, sms_client
from utils.order_sync import notify_user_order_completed

router = Router()
logger = logging.getLogger(__name__)

BROADCAST_BATCH_SIZE = 25
BROADCAST_BATCH_PAUSE = 0.5
SMS_COUNTRY_PAGE_SIZE = 12


def _back_markup(callback_data="adm_main", text="🔙 Orqaga"):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text=text, callback_data=callback_data))
    return builder.as_markup()


def _single_edit_markup(label, callback_data, back_callback="adm_main"):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text=label, callback_data=callback_data))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data=back_callback))
    return builder.as_markup()


async def _send_or_edit(target, text, reply_markup):
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=reply_markup)
    else:
        await target.answer(text, reply_markup=reply_markup)


async def _get_float_setting(key, default):
    try:
        return float(await db.get_setting(key, default) or default)
    except (TypeError, ValueError):
        return float(default)


def _mask_secret(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "sozlanmagan"
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{raw[:4]}***{raw[-2:]}"


def _parse_required_channels(raw_value: str) -> list[str]:
    return [line.strip() for line in str(raw_value or "").splitlines() if line.strip()]


def _normalize_channel_input(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("https://t.me/"):
        raw = "@" + raw.split("https://t.me/", 1)[1].strip("/").split("/", 1)[0]
    elif raw.startswith("http://t.me/"):
        raw = "@" + raw.split("http://t.me/", 1)[1].strip("/").split("/", 1)[0]
    elif raw.startswith("t.me/"):
        raw = "@" + raw.split("t.me/", 1)[1].strip("/").split("/", 1)[0]
    if raw.startswith("@"):
        slug = raw[1:].strip()
        return f"@{slug}" if slug else None
    return None


def _provider_to_local_status(provider_status):
    normalized = str(provider_status or "").strip().lower()
    return {
        "pending": "pending",
        "processing": "processing",
        "in progress": "processing",
        "completed": "completed",
        "partial": "processing",
        "canceled": "cancelled",
        "cancelled": "cancelled",
        "failed": "failed",
    }.get(normalized)


def _content_keyboard():
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


def _guide_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="📚 Qo'llanma matni", callback_data="adm_edit_setting|guide_text|guide"),
        types.InlineKeyboardButton(text="🆘 Support link", callback_data="adm_edit_setting|support_link|guide"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def _api_settings_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🚀 SMM URL", callback_data="adm_edit_setting|smm_api_url|api"),
        types.InlineKeyboardButton(text="🔑 SMM KEY", callback_data="adm_edit_setting|smm_api_key|api"),
    )
    builder.row(
        types.InlineKeyboardButton(text="📱 SMS URL", callback_data="adm_edit_setting|sms_api_url|api"),
        types.InlineKeyboardButton(text="🔑 SMS KEY", callback_data="adm_edit_setting|sms_api_key|api"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def _channels_keyboard(channels: list[str]):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="adm_channel_add"),
        types.InlineKeyboardButton(text="🗑 Kanal o'chirish", callback_data="adm_channel_remove_menu"),
    )
    if channels:
        builder.row(types.InlineKeyboardButton(text="✏️ Matn bilan tahrirlash", callback_data="adm_edit_setting|required_channels|channels"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def _channels_remove_keyboard(channels: list[str]):
    builder = InlineKeyboardBuilder()
    for index, channel in enumerate(channels):
        builder.row(types.InlineKeyboardButton(text=f"🗑 {channel}", callback_data=f"adm_channel_remove|{index}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_channels"))
    return builder.as_markup()


def _pending_payments_keyboard(transactions):
    builder = InlineKeyboardBuilder()
    for tx in transactions:
        label = f"#{tx['id']} | {tx['amount']:,.0f} so'm | {tx['method']}"
        builder.row(types.InlineKeyboardButton(text=label[:64], callback_data=f"adm_tx_card|{tx['id']}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_payment_methods"))
    return builder.as_markup()


def _payment_card_keyboard(transaction):
    builder = InlineKeyboardBuilder()
    if transaction["status"] == "pending":
        builder.row(
            types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_tx_{transaction['id']}"),
            types.InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_tx_{transaction['id']}"),
        )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_pending_payments"))
    return builder.as_markup()


def _broadcast_review_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Yuborish", callback_data="adm_broadcast_send"),
        types.InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="adm_broadcast_edit"),
    )
    builder.row(types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm_broadcast_cancel"))
    return builder.as_markup()


def _price_list_keyboard(services):
    builder = InlineKeyboardBuilder()
    for service in services[:20]:
        label = f"{service['service_id']} | {service['price_per_1000']:,.0f} so'm | {service['name']}"
        builder.row(types.InlineKeyboardButton(text=label[:64], callback_data=f"adm_price_card|{service['service_id']}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_services"))
    return builder.as_markup()


def _price_card_keyboard(service):
    builder = InlineKeyboardBuilder()
    next_state = 0 if service["is_active"] else 1
    toggle_label = "⏸ O'chirish" if service["is_active"] else "▶️ Faollashtirish"
    builder.row(
        types.InlineKeyboardButton(text="💰 Narxni tahrirlash", callback_data=f"adm_price_edit|{service['service_id']}"),
        types.InlineKeyboardButton(text=toggle_label, callback_data=f"adm_price_toggle|{service['service_id']}|{next_state}"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_prices"))
    return builder.as_markup()


def _categories_keyboard(groups):
    builder = InlineKeyboardBuilder()
    for group in groups:
        icon = "🟢" if group["is_visible"] else "⚪"
        next_state = 0 if group["is_visible"] else 1
        text = f"{icon} {group['group_label']} ({group['service_count']})"
        builder.row(types.InlineKeyboardButton(text=text[:64], callback_data=f"adm_group|{group['group_key']}|{next_state}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_services"))
    return builder.as_markup()


def _promo_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🎟 Kodni o'rnatish", callback_data="adm_edit_setting|promo_code_value|promo"),
        types.InlineKeyboardButton(text="💰 Bonusni o'rnatish", callback_data="adm_edit_setting|promo_code_bonus|promo"),
    )
    builder.row(types.InlineKeyboardButton(text="🗓 Muddatni belgilash", callback_data="adm_edit_setting|promo_code_expires_at|promo"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def _referral_keyboard(enabled):
    builder = InlineKeyboardBuilder()
    toggle_text = "⏸ Referalni o'chirish" if enabled else "▶️ Referalni yoqish"
    builder.row(types.InlineKeyboardButton(text=toggle_text, callback_data=f"adm_set_referral|{0 if enabled else 1}"))
    builder.row(
        types.InlineKeyboardButton(text="💎 Diamond UZ", callback_data="adm_edit_setting|referral_diamond_uz|referral"),
        types.InlineKeyboardButton(text="💎 Diamond Chet", callback_data="adm_edit_setting|referral_diamond_foreign|referral"),
    )
    builder.row(
        types.InlineKeyboardButton(text="💵 Cash UZ", callback_data="adm_edit_setting|referral_cash_uz|referral"),
        types.InlineKeyboardButton(text="💵 Cash Chet", callback_data="adm_edit_setting|referral_cash_foreign|referral"),
    )
    builder.row(
        types.InlineKeyboardButton(text="🧹 Referallarni tozalash", callback_data="adm_clear_referrals"),
        types.InlineKeyboardButton(text="🎁 Umumiy bonus", callback_data="adm_edit_setting|referral_bonus|referral"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


def _sms_settings_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🌐 SMS URL", callback_data="adm_edit_setting|sms_api_url|sms"),
        types.InlineKeyboardButton(text="🔑 SMS KEY", callback_data="adm_edit_setting|sms_api_key|sms"),
    )
    builder.row(
        types.InlineKeyboardButton(text="🆔 SMS API ID", callback_data="adm_edit_setting|sms_api_id|sms"),
        types.InlineKeyboardButton(text="⚖️ SMS Foiz", callback_data="adm_edit_setting|sms_markup_percent|sms"),
    )
    builder.row(types.InlineKeyboardButton(text="💵 Dollar kursi", callback_data="adm_edit_setting|usd_rate|sms"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()


async def _render_content_settings(target):
    settings = await db.get_settings(["admin_username", "news_channel", "news_group", "orders_channel"])
    text = (
        "📝 <b>Ma'lumotlarni tahrirlash</b>\n\n"
        f"👤 Admin user: <code>{settings.get('admin_username', '')}</code>\n"
        f"📢 Yangiliklar kanal: <code>{settings.get('news_channel', '')}</code>\n"
        f"👥 Yangiliklar guruh: <code>{settings.get('news_group', '')}</code>\n"
        f"📦 Buyurtmalar kanal: <code>{settings.get('orders_channel', '')}</code>"
    )
    await _send_or_edit(target, text, _content_keyboard())


async def _render_guide_settings(target):
    settings = await db.get_settings(["guide_text", "support_link"])
    text = (
        "📚 <b>Qo'llanma sozlash</b>\n\n"
        f"Matn: <code>{(settings.get('guide_text') or '')[:120]}</code>\n\n"
        f"Support: <code>{settings.get('support_link', '')}</code>"
    )
    await _send_or_edit(target, text, _guide_keyboard())


async def _render_api_settings(target):
    settings = await db.get_settings(["smm_api_url", "smm_api_key", "sms_api_url", "sms_api_key"])
    text = (
        "🔑 <b>API key</b>\n\n"
        "🚀 <b>Nakrutka API</b>\n"
        f"🌐 URL: <code>{settings.get('smm_api_url') or 'sozlanmagan'}</code>\n"
        f"🔐 KEY: <code>{_mask_secret(settings.get('smm_api_key'))}</code>\n\n"
        "📱 <b>Raqam API</b>\n"
        f"🌐 URL: <code>{settings.get('sms_api_url') or 'sozlanmagan'}</code>\n"
        f"🔐 KEY: <code>{_mask_secret(settings.get('sms_api_key'))}</code>"
    )
    await _send_or_edit(target, text, _api_settings_keyboard())


async def _render_discount_settings(target):
    discount = await _get_float_setting("discount_percent", 0)
    text = (
        "🛍 <b>Chegirmalar</b>\n\n"
        f"Joriy umumiy chegirma: <b>{discount:.2f}%</b>"
    )
    await _send_or_edit(target, text, _single_edit_markup("✏️ Chegirmani tahrirlash", "adm_edit_setting|discount_percent|discounts"))


async def _render_markup_settings(target):
    markup = await _get_float_setting("markup_percentage", DEFAULT_SMM_MARKUP_PERCENT)
    text = (
        "⚖️ <b>Foizni o'rnatish</b>\n\n"
        f"API narxlariga qo'shiladigan ustama: <b>{markup:.2f}%</b>\n\n"
        "Formula: <code>final_price = rate + (rate * markup_percentage / 100)</code>"
    )
    await _send_or_edit(target, text, _single_edit_markup("✏️ Ustamani tahrirlash", "adm_edit_setting|markup_percentage|markup"))


async def _render_referral_settings(target):
    referral_bonus = await _get_float_setting("referral_bonus", REFERRAL_BONUS)
    enabled = await db.get_setting_bool("referral_enabled", True)
    diamond_uz = await _get_float_setting("referral_diamond_uz", 2)
    diamond_foreign = await _get_float_setting("referral_diamond_foreign", 2)
    cash_uz = await _get_float_setting("referral_cash_uz", 100)
    cash_foreign = await _get_float_setting("referral_cash_foreign", 50)
    status_text = "Yoqilgan" if enabled else "O'chirilgan"
    text = (
        "⚙️ <b>Referal sozlamalari</b>\n\n"
        f"Holat: <b>{status_text}</b>\n"
        f"Umumiy bonus: <b>{referral_bonus:,.0f}</b> so'm\n"
        f"Diamond UZ: <b>{diamond_uz:.0f}</b>\n"
        f"Diamond Chet: <b>{diamond_foreign:.0f}</b>\n"
        f"Cash UZ: <b>{cash_uz:,.0f}</b> so'm\n"
        f"Cash Chet: <b>{cash_foreign:,.0f}</b> so'm"
    )
    await _send_or_edit(target, text, _referral_keyboard(enabled))


async def _render_channels_settings(target):
    channels = _parse_required_channels(await db.get_setting("required_channels", ""))
    preview = "\n".join(f"• <code>{escape(channel)}</code>" for channel in channels[:12]) or "• Hali kanal qo'shilmagan"
    text = (
        "📢 <b>Kanallar</b>\n\n"
        f"Jami kanallar: <b>{len(channels)}</b>\n\n"
        f"{preview}"
    )
    await _send_or_edit(target, text, _channels_keyboard(channels))


async def _render_pending_payments(target):
    transactions = await db.get_pending_transactions(limit=20)
    if not transactions:
        return await _send_or_edit(target, "💵 Pending to'lovlar yo'q.", _back_markup("adm_payment_methods"))
    await _send_or_edit(target, "💵 <b>Pending to'lov so'rovlari</b>\n\nKerakli so'rovni tanlang.", _pending_payments_keyboard(transactions))


async def _render_payment_card(target, transaction):
    if not transaction:
        return await _send_or_edit(target, "❌ Tranzaksiya topilmadi.", _back_markup("adm_pending_payments"))
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
    await _send_or_edit(target, text, _payment_card_keyboard(transaction))


async def _render_top_users(target):
    users = await db.get_top_users(limit=100)
    if not users:
        return await _send_or_edit(target, "❌ Foydalanuvchilar topilmadi.", _back_markup("adm_stats"))
    lines = ["🏆 <b>TOP 100 Balans</b>\n"]
    for index, user in enumerate(users, start=1):
        name = (user["full_name"] or user["username"] or "N/A")[:18]
        lines.append(f"{index:02}. <b>{escape(name)}</b> — <b>{int(user['balance'] or 0):,}</b> so'm")
    await _send_or_edit(target, "\n".join(lines), _back_markup("adm_stats"))


async def _render_prices(target):
    services = await db.get_smm_services(active_only=False, include_hidden_groups=True)
    if not services:
        return await _send_or_edit(target, "❌ Xizmatlar topilmadi.", _back_markup("adm_services"))
    await _send_or_edit(target, "💸 <b>Narxlar</b>\n\nXizmatni tanlab narxini yoki holatini boshqaring.", _price_list_keyboard(services))


async def _render_price_card(target, service):
    if not service:
        return await _send_or_edit(target, "❌ Xizmat topilmadi.", _back_markup("adm_prices"))
    status_text = "Aktiv" if service["is_active"] else "O'chirilgan"
    text = (
        "💸 <b>Xizmat kartasi</b>\n\n"
        f"🆔 Service ID: <code>{service['service_id']}</code>\n"
        f"📂 Guruh: <b>{service['group_label']}</b>\n"
        f"📊 Nomi: <b>{escape(service['name'])}</b>\n"
        f"💵 API narxi: <b>${float(service['provider_price_usd'] or 0):,.4f}</b>\n"
        f"🇺🇿 Bot narxi: <b>{int(service['price_per_1000'] or 0):,}</b> so'm\n"
        f"📉 Min: <b>{int(service['min_order'] or 0):,}</b>\n"
        f"📈 Max: <b>{int(service['max_order'] or 0):,}</b>\n"
        f"🚦 Holat: <b>{status_text}</b>"
    )
    await _send_or_edit(target, text, _price_card_keyboard(service))


async def _render_categories(target):
    groups = await db.get_smm_groups(active_only=False, include_hidden=True)
    if not groups:
        return await _send_or_edit(target, "❌ Guruhlar topilmadi.", _back_markup("adm_services"))
    await _send_or_edit(target, "🗂 <b>Kategoriyalar</b>\n\nGuruhlarni yashirish yoki ko'rsatish mumkin.", _categories_keyboard(groups))


async def _render_promocode(target):
    settings = await db.get_settings(["promo_code_value", "promo_code_bonus", "promo_code_expires_at"])
    promo_code = settings.get("promo_code_value") or "o'rnatilmagan"
    text = (
        "🎟 <b>Promokod</b>\n\n"
        f"Kod: <code>{promo_code}</code>\n"
        f"Bonus: <b>{float(settings.get('promo_code_bonus', 0) or 0):,.0f}</b> so'm\n"
        f"Muddat: <b>{settings.get('promo_code_expires_at') or 'cheklanmagan'}</b>"
    )
    await _send_or_edit(target, text, _promo_keyboard())


async def _render_daily_bonus(target):
    bonus = await _get_float_setting("daily_bonus_amount", DAILY_BONUS_DEFAULT)
    await _send_or_edit(
        target,
        f"🎁 <b>Kunlik bonus</b>\n\nFoydalanuvchi uchun kunlik bonus: <b>{bonus:,.0f}</b> so'm",
        _single_edit_markup("✏️ Bonus miqdorini tahrirlash", "adm_edit_setting|daily_bonus_amount|daily_bonus"),
    )


async def _render_premium(target):
    groups = await db.get_smm_groups(active_only=False, include_hidden=True)
    premium_group = next((group for group in groups if group["group_key"] == "tg_premium"), None)
    is_visible = bool(premium_group["is_visible"]) if premium_group else True
    toggle_text = "⏸ Premiumni yashirish" if is_visible else "▶️ Premiumni ko'rsatish"
    visibility_text = "Ko'rinadi" if is_visible else "Yashirilgan"
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text=toggle_text, callback_data=f"adm_group|tg_premium|{0 if is_visible else 1}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    await _send_or_edit(
        target,
        f"💎 <b>Premium olish xizmati</b>\n\nTelegram Premium guruhi holati: <b>{visibility_text}</b>",
        builder.as_markup(),
    )


async def _render_sms_settings(target):
    settings = await db.get_settings(["sms_api_url", "sms_api_key", "sms_api_id", "sms_markup_percent"])
    sms_markup = await _get_float_setting("sms_markup_percent", 0)
    usd_rate = await _get_float_setting("usd_rate", USD_RATE)
    balance_info = await sms_client.get_balance()
    text = (
        "📞 <b>Nomer sozlamalari</b>\n\n"
        f"Ulanish: <b>{'Faol' if settings.get('sms_api_key') else 'Sozlanmagan'}</b>\n"
        f"Balans ({balance_info.get('currency', 'UZS')}): <b>{float(balance_info.get('balance', 0) or 0):,.2f}</b>\n"
        f"Foiz: <b>{sms_markup:.2f}%</b>\n"
        f"Dollar kursi: <b>{usd_rate:,.0f}</b> so'm\n\n"
        f"API ID: <code>{settings.get('sms_api_id') or 'sozlanmagan'}</code>\n"
        f"SMS URL: <code>{settings.get('sms_api_url') or ''}</code>\n"
        f"SMS KEY: <code>{_mask_secret(settings.get('sms_api_key'))}</code>"
    )
    await _send_or_edit(target, text, _sms_settings_keyboard())


async def _render_broadcast_preview(target, payload_text):
    text = (
        "📨 <b>Tarqatish preview</b>\n\n"
        "Turi: <b>Matn</b>\n\n"
        f"<code>{escape(payload_text[:500])}</code>"
    )
    await _send_or_edit(target, text, _broadcast_review_keyboard())


def _view_renderer(return_view):
    return {
        "content": _render_content_settings,
        "guide": _render_guide_settings,
        "api": _render_api_settings,
        "discounts": _render_discount_settings,
        "markup": _render_markup_settings,
        "referral": _render_referral_settings,
        "channels": _render_channels_settings,
        "promo": _render_promocode,
        "daily_bonus": _render_daily_bonus,
        "sms": _render_sms_settings,
    }.get(return_view)


@router.callback_query(F.data == "adm_content", F.from_user.id.in_(ADMIN_LIST))
async def adm_content(call: types.CallbackQuery):
    await _render_content_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_guide", F.from_user.id.in_(ADMIN_LIST))
async def adm_guide(call: types.CallbackQuery):
    await _render_guide_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_discounts", F.from_user.id.in_(ADMIN_LIST))
async def adm_discounts(call: types.CallbackQuery):
    await _render_discount_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_markup", F.from_user.id.in_(ADMIN_LIST))
async def adm_markup(call: types.CallbackQuery):
    await _render_markup_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_referral", F.from_user.id.in_(ADMIN_LIST))
async def adm_referral(call: types.CallbackQuery):
    await _render_referral_settings(call)
    await call.answer()


@router.callback_query(F.data.startswith("adm_set_referral|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_set_referral(call: types.CallbackQuery):
    enabled = call.data.split("|", 1)[1]
    await db.set_setting("referral_enabled", enabled)
    await _render_referral_settings(call)
    await call.answer("Referal holati yangilandi.")


@router.callback_query(F.data == "adm_channels", F.from_user.id.in_(ADMIN_LIST))
async def adm_channels(call: types.CallbackQuery):
    await _render_channels_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_channel_add", F.from_user.id.in_(ADMIN_LIST))
async def adm_channel_add(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.editing_setting)
    await state.update_data(edit_type="channel_add", return_view="channels")
    await call.message.answer("📢 Kanal username yuboring.\n\nMisol: <code>@my_channel</code>", reply_markup=_back_markup())
    await call.answer()


@router.callback_query(F.data == "adm_channel_remove_menu", F.from_user.id.in_(ADMIN_LIST))
async def adm_channel_remove_menu(call: types.CallbackQuery):
    channels = _parse_required_channels(await db.get_setting("required_channels", ""))
    if not channels:
        await call.answer("O'chirish uchun kanal yo'q.", show_alert=True)
        return
    await _send_or_edit(call, "🗑 <b>Kanalni o'chirish</b>\n\nOlib tashlanadigan kanalni tanlang.", _channels_remove_keyboard(channels))
    await call.answer()


@router.callback_query(F.data.startswith("adm_channel_remove|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_channel_remove(call: types.CallbackQuery):
    channels = _parse_required_channels(await db.get_setting("required_channels", ""))
    try:
        index = int(call.data.split("|")[1])
    except (IndexError, ValueError):
        await call.answer("Kanal topilmadi.", show_alert=True)
        return
    if index < 0 or index >= len(channels):
        await call.answer("Kanal topilmadi.", show_alert=True)
        return
    removed = channels.pop(index)
    await db.set_setting("required_channels", "\n".join(channels))
    await _render_channels_settings(call)
    await call.answer(f"{removed} olib tashlandi.")


@router.callback_query(F.data == "adm_promocode", F.from_user.id.in_(ADMIN_LIST))
async def adm_promocode(call: types.CallbackQuery):
    await _render_promocode(call)
    await call.answer()


@router.callback_query(F.data == "adm_daily_bonus", F.from_user.id.in_(ADMIN_LIST))
async def adm_daily_bonus(call: types.CallbackQuery):
    await _render_daily_bonus(call)
    await call.answer()


@router.callback_query(F.data == "adm_premium", F.from_user.id.in_(ADMIN_LIST))
async def adm_premium(call: types.CallbackQuery):
    await _render_premium(call)
    await call.answer()


@router.callback_query(F.data == "adm_sms_settings", F.from_user.id.in_(ADMIN_LIST))
async def adm_sms_settings(call: types.CallbackQuery):
    await _render_sms_settings(call)
    await call.answer()


@router.callback_query(F.data == "adm_pending_payments", F.from_user.id.in_(ADMIN_LIST))
async def adm_pending_payments(call: types.CallbackQuery):
    await _render_pending_payments(call)
    await call.answer()


@router.callback_query(F.data.startswith("adm_tx_card|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_tx_card(call: types.CallbackQuery):
    transaction = await db.get_transaction(int(call.data.split("|")[1]))
    await _render_payment_card(call, transaction)
    await call.answer()


@router.callback_query(F.data.startswith("approve_tx_"), F.from_user.id.in_(ADMIN_LIST))
async def approve_tx_callback(call: types.CallbackQuery, bot: Bot):
    transaction_id = int(call.data.split("_")[2])
    transaction, status = await db.confirm_transaction(transaction_id)
    if status == "confirmed":
        try:
            await bot.send_message(transaction["user_id"], f"✅ To'lovingiz tasdiqlandi.\n\nBalansga: <b>{transaction['amount']:,.0f}</b> so'm qo'shildi.")
        except Exception:
            pass
        await _render_payment_card(call, transaction)
        await call.answer("To'lov tasdiqlandi.")
        return
    if status == "already_processed":
        await call.answer(f"Bu to'lov allaqachon {transaction['status']} qilingan.", show_alert=True)
        return
    await call.answer("To'lovni tasdiqlab bo'lmadi.", show_alert=True)


@router.callback_query(F.data.startswith("reject_tx_"), F.from_user.id.in_(ADMIN_LIST))
async def reject_tx_callback(call: types.CallbackQuery, bot: Bot):
    transaction_id = int(call.data.split("_")[2])
    transaction, status = await db.reject_transaction(transaction_id)
    if status == "rejected":
        try:
            await bot.send_message(transaction["user_id"], f"❌ To'lov so'rovingiz rad etildi.\n\nSumma: <b>{transaction['amount']:,.0f}</b> so'm")
        except Exception:
            pass
        await _render_payment_card(call, transaction)
        await call.answer("To'lov rad etildi.")
        return
    if status == "already_processed":
        await call.answer(f"Bu to'lov allaqachon {transaction['status']} qilingan.", show_alert=True)
        return
    await call.answer("To'lovni rad etib bo'lmadi.", show_alert=True)


@router.callback_query(F.data == "adm_top_users", F.from_user.id.in_(ADMIN_LIST))
async def adm_top_users(call: types.CallbackQuery):
    await _render_top_users(call)
    await call.answer()


@router.callback_query(F.data == "adm_refresh_orders", F.from_user.id.in_(ADMIN_LIST))
async def adm_refresh_orders(call: types.CallbackQuery, bot: Bot):
    orders = await db.get_syncable_orders(limit=50)
    checked = 0
    updated = 0
    for order in orders:
        checked += 1
        try:
            provider_status = await smm_client.check_status(order["external_id"])
        except Exception:
            provider_status = None
        mapped = _provider_to_local_status(provider_status)
        if mapped and mapped != order["status"]:
            updated_order = await db.update_order_status(order["id"], mapped)
            if mapped == "completed":
                await db.award_referral_bonus_for_completed_order(updated_order["user_id"], updated_order["id"])
                await notify_user_order_completed(bot, updated_order)
            updated += 1
    await call.answer(f"{checked} ta buyurtma tekshirildi, {updated} tasi yangilandi.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("Buyurtmalar holati yangilandi.", reply_markup=_back_markup("adm_stats"))


@router.callback_query(F.data == "adm_prices", F.from_user.id.in_(ADMIN_LIST))
async def adm_prices(call: types.CallbackQuery):
    await _render_prices(call)
    await call.answer()


@router.callback_query(F.data.startswith("adm_price_card|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_price_card(call: types.CallbackQuery):
    service = await db.get_smm_service(call.data.split("|")[1], include_hidden_groups=True)
    await _render_price_card(call, service)
    await call.answer()


@router.callback_query(F.data.startswith("adm_price_toggle|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_price_toggle(call: types.CallbackQuery):
    _, service_id, next_state = call.data.split("|")
    await db.set_smm_service_active(service_id, bool(int(next_state)))
    service = await db.get_smm_service(service_id, include_hidden_groups=True)
    await _render_price_card(call, service)
    await call.answer("Holat yangilandi.")


@router.callback_query(F.data.startswith("adm_price_edit|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_price_edit(call: types.CallbackQuery, state: FSMContext):
    service_id = call.data.split("|")[1]
    await state.set_state(AdminStates.editing_service_price)
    await state.update_data(service_id=service_id)
    await call.message.answer("💰 Yangi narxni so'mda yuboring.", reply_markup=_back_markup("adm_prices"))
    await call.answer()


@router.message(AdminStates.editing_service_price, F.from_user.id.in_(ADMIN_LIST))
async def adm_price_edit_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        price = int((message.text or "").strip())
    except ValueError:
        return await message.answer("❌ Narx son bo'lishi kerak.")
    if price <= 0:
        return await message.answer("❌ Narx 0 dan katta bo'lishi kerak.")
    await db.update_smm_service_price(data["service_id"], price)
    service = await db.get_smm_service(data["service_id"], include_hidden_groups=True)
    await state.clear()
    await render_for_message(message, service)


async def render_for_message(message: types.Message, service):
    text = (
        "💸 <b>Xizmat kartasi</b>\n\n"
        f"🆔 Service ID: <code>{service['service_id']}</code>\n"
        f"📂 Guruh: <b>{service['group_label']}</b>\n"
        f"📊 Nomi: <b>{escape(service['name'])}</b>\n"
        f"🇺🇿 Bot narxi: <b>{int(service['price_per_1000'] or 0):,}</b> so'm"
    )
    await message.answer(text, reply_markup=_price_card_keyboard(service))


@router.callback_query(F.data == "adm_categories", F.from_user.id.in_(ADMIN_LIST))
async def adm_categories(call: types.CallbackQuery):
    await _render_categories(call)
    await call.answer()


@router.callback_query(F.data.startswith("adm_group|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_group_toggle(call: types.CallbackQuery):
    _, group_key, next_state = call.data.split("|")
    await db.set_group_visibility(group_key, bool(int(next_state)))
    if group_key == "tg_premium":
        await _render_premium(call)
    else:
        await _render_categories(call)
    await call.answer("Kategoriya holati yangilandi.")


@router.callback_query(F.data == "adm_broadcast", F.from_user.id.in_(ADMIN_LIST))
async def adm_broadcast(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.broadcasting)
    await call.message.answer("✉️ Yuboriladigan matnni jo'nating.", reply_markup=_back_markup())
    await call.answer()


@router.message(AdminStates.broadcasting, F.from_user.id.in_(ADMIN_LIST))
async def adm_broadcast_message(message: types.Message, state: FSMContext):
    payload = (message.text or "").strip()
    if not payload:
        return await message.answer("❌ Hozircha faqat matnli xabar yuborishni qo'llab-quvvatlayman.")
    await state.update_data(broadcast_payload=payload)
    await state.set_state(AdminStates.broadcast_review)
    await _render_broadcast_preview(message, payload)


@router.callback_query(F.data == "adm_broadcast_edit", F.from_user.id.in_(ADMIN_LIST))
async def adm_broadcast_edit(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.broadcasting)
    await call.message.answer("✏️ Yangi matn yuboring.", reply_markup=_back_markup())
    await call.answer()


@router.callback_query(F.data == "adm_broadcast_cancel", F.from_user.id.in_(ADMIN_LIST))
async def adm_broadcast_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("❌ Tarqatish bekor qilindi.", reply_markup=_back_markup())
    await call.answer()


@router.callback_query(F.data == "adm_broadcast_send", F.from_user.id.in_(ADMIN_LIST))
async def adm_broadcast_send(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    payload = str(data.get("broadcast_payload", "")).strip()
    if not payload:
        await state.clear()
        await call.answer("Draft topilmadi.", show_alert=True)
        return
    user_ids = await db.get_all_user_ids()
    sent = 0
    failed = 0
    await call.message.answer(f"✉️ Tarqatish boshlandi. Jami: <b>{len(user_ids)}</b>")
    for index, user_id in enumerate(user_ids, start=1):
        try:
            await bot.send_message(user_id, payload)
            sent += 1
        except Exception:
            failed += 1
        if index % BROADCAST_BATCH_SIZE == 0:
            await asyncio.sleep(BROADCAST_BATCH_PAUSE)
    await state.clear()
    await call.message.answer(f"✅ Tarqatish yakunlandi.\nYuborildi: <b>{sent}</b>\nXatolik: <b>{failed}</b>", reply_markup=_back_markup())
    await call.answer()


@router.callback_query(F.data.startswith("adm_edit_setting|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_edit_setting(call: types.CallbackQuery, state: FSMContext):
    _, setting_key, return_view = call.data.split("|", 2)
    await state.set_state(AdminStates.editing_setting)
    await state.update_data(edit_type=setting_key, return_view=return_view)
    await call.message.answer(f"Yangi qiymat yuboring:\n<code>{setting_key}</code>", reply_markup=_back_markup())
    await call.answer()


@router.message(AdminStates.editing_setting, F.from_user.id.in_(ADMIN_LIST))
async def adm_edit_setting_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    edit_type = data.get("edit_type")
    return_view = data.get("return_view", "adm_main")
    raw_value = (message.text or "").strip()

    if edit_type == "channel_add":
        normalized = _normalize_channel_input(raw_value)
        if not normalized:
            return await message.answer("❌ To'g'ri kanal username yuboring. Masalan: @my_channel")
        channels = _parse_required_channels(await db.get_setting("required_channels", ""))
        if normalized.casefold() not in {channel.casefold() for channel in channels}:
            channels.append(normalized)
            await db.set_setting("required_channels", "\n".join(channels))
        await state.clear()
        return await _render_channels_settings(message)

    if not raw_value:
        return await message.answer("❌ Bo'sh qiymat yubormang.")

    numeric_keys = {
        "discount_percent",
        "markup_percentage",
        "referral_bonus",
        "referral_diamond_uz",
        "referral_diamond_foreign",
        "referral_cash_uz",
        "referral_cash_foreign",
        "promo_code_bonus",
        "daily_bonus_amount",
        "sms_markup_percent",
        "usd_rate",
        "min_payment_amount",
    }
    if edit_type in numeric_keys:
        try:
            float(raw_value)
        except ValueError:
            return await message.answer("❌ Son yuboring.")

    await db.set_setting(edit_type, raw_value)
    await state.clear()
    renderer = _view_renderer(return_view)
    if renderer:
        await renderer(message)
    else:
        await message.answer("✅ Sozlama saqlandi.", reply_markup=_back_markup())
