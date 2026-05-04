import logging
import secrets
import time
from html import escape, unescape

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import db
from keyboards.navigation import user_flow_keyboard
from states.bot_states import OrderState
from utils.api_client import smm_client
from utils.service_catalog import (
    calculate_price_uzs,
    calculate_quantity_price_uzs,
    is_instagram_link,
    normalize_text,
)

router = Router()

SERVICES_MENU_TEXT = "<b>SMM xizmatlari</b>\n\nKerakli ijtimoiy tarmoqni tanlang:"
GROUP_SERVICES_TEXT = "Marhamat, kerakli ta'rifni tanlang! Narxlar 1000 tasi uchun berilgan."
DEFAULT_USD_RATE = 12_800
DEFAULT_MARKUP_PERCENT = 25
MAX_SERVICE_BUTTONS = 30
SMM_CACHE_TTL = 120  # 2 minutes

_smm_services_cache = None
_smm_services_cache_expires_at = 0.0

NETWORKS_DATA = [
    {
        "label": "\U0001F4F8 Instagram",
        "platform_keywords": ("instagram", "insta", "ig"),
        "groups": [
            {
                "label": "\U0001F465 Kuzatuvchilar (Followers)",
                "match_any": (
                    "follower",
                    "followers",
                    "follow",
                    "subscriber",
                    "subscribers",
                    "obunachi",
                    "obunachilar",
                    "kuzatuvchi",
                    "kuzatuvchilar",
                ),
            },
            {
                "label": "\u2764\uFE0F Layklar (Likes)",
                "match_any": ("like", "likes", "layk", "layklar", "heart", "yoqtirish"),
            },
            {
                "label": "\U0001F3AC Reels ko'rishlari",
                "match_any": ("reel", "reels", "korishlar"),
            },
            {
                "label": "\U0001F441 Story ko'rishlari",
                "match_any": ("story", "stories"),
            },
            {
                "label": "\U0001F4CA Impressions/reach & profil tashriflari",
                "match_any": ("impression", "reach", "profile", "visit", "visitor"),
            },
            {
                "label": "\U0001F4AC Sharhlar (Comments)",
                "match_any": ("comment", "comments", "sharh", "izoh"),
            },
            {
                "label": "\U0001F4BE Saqlashlar va ulashishlar",
                "match_any": ("save", "saves", "saved", "share", "shares", "ulashish", "saqlash", "repost"),
            },
        ],
    },
    {
        "label": "\U0001F3A5 YouTube",
        "platform_keywords": ("youtube",),
        "groups": [
            {
                "label": "\U0001F441 Ko'rishlar (Views)",
                "match_any": ("view", "views", "korishlar"),
                "exclude_any": ("watch time", "4000", "hour"),
            },
            {
                "label": "\u23F1 Tomosha vaqti (4000 soat)",
                "match_any": ("watch time", "4000", "hour", "hours", "monetization", "tomosha"),
            },
            {
                "label": "\U0001F465 Obunachilar (Subscribers)",
                "match_any": ("subscriber", "subscribers", "obunachi", "obunachilar"),
            },
            {
                "label": "\U0001F44D Layklar va impressionlar",
                "match_any": ("like", "likes", "layk", "layklar", "impression", "impressions"),
            },
        ],
    },
    {
        "label": "\U0001F3B5 TikTok (Reels)",
        "platform_keywords": ("tiktok", "tik tok"),
        "groups": [
            {
                "label": "\U0001F465 Kuzatuvchilar (Followers)",
                "match_any": ("follower", "followers", "subscriber", "subscribers", "obunachi", "obunachilar"),
            },
            {
                "label": "\u2764\uFE0F Layklar (Likes)",
                "match_any": ("like", "likes", "layk", "layklar"),
            },
            {
                "label": "\U0001F441 Ko'rishlar (Views)",
                "match_any": ("view", "views", "korishlar"),
            },
            {
                "label": "\u2197\uFE0F Ulashishlar (Shares)",
                "match_any": ("share", "shares", "repost", "ulashish"),
            },
        ],
    },
    {
        "label": "\U0001F4D8 Facebook",
        "platform_keywords": ("facebook", "fb"),
        "groups": [
            {
                "label": "\U0001F465 Sahifa layklari va kuzatuvchilar",
                "match_any": ("page like", "page likes", "page follower", "page followers", "follower", "followers"),
            },
            {
                "label": "\U0001F44D Post layklari",
                "match_any": ("post like", "post likes", "like", "likes"),
                "exclude_any": ("page follower", "page followers"),
            },
            {
                "label": "\U0001F4AC Sharhlar va ulashishlar",
                "match_any": ("comment", "comments", "share", "shares"),
            },
            {
                "label": "\U0001F3AC Video ko'rishlar",
                "match_any": ("video view", "video views", "view", "views"),
            },
            {
                "label": "\u2B50 Sharhlar va baholar (Reviews)",
                "match_any": ("review", "reviews", "rating", "ratings", "star"),
            },
        ],
    },
    {
        "label": "\U0001F4BC LinkedIn",
        "platform_keywords": ("linkedin", "linked in"),
        "groups": [
            {
                "label": "\U0001F465 Kuzatuvchilar va ulanishlar",
                "match_any": ("follower", "followers", "connection", "connections", "connect"),
            },
            {
                "label": "\U0001F441 Profil ko'rinishlari va tashriflar",
                "match_any": ("profile", "visit", "visitor", "view"),
            },
            {
                "label": "\U0001F44D Postga layklar va ulashishlar",
                "match_any": ("post like", "post likes", "like", "share", "shares", "repost"),
            },
            {
                "label": "\U0001F4C4 Maqola ko'rishlari va endorsements",
                "match_any": ("article", "endorsement", "endorsements", "skill"),
            },
            {
                "label": "\U0001F3E2 Kompaniya sahifasi kuzatuvchilari",
                "match_any": ("company", "page follower", "company page"),
            },
        ],
    },
    {
        "label": "\u2708\uFE0F Telegram",
        "platform_keywords": ("telegram", "tg"),
        "groups": [
            {
                "label": "\U0001F465 Kanal/guruh a'zolari",
                "match_any": (
                    "member",
                    "members",
                    "subscriber",
                    "subscribers",
                    "channel",
                    "group",
                    "join",
                    "obunachi",
                    "obunachilar",
                    "azo",
                    "azolari",
                ),
                "exclude_any": ("premium", "bot start", "reaction", "emoji", "poll", "vote", "view"),
            },
            {
                "label": "\U0001F441 Post ko'rishlari",
                "match_any": ("view", "views", "post", "korishlar"),
            },
            {
                "label": "\U0001F525 Reaksiyalar va emoji reaksiyalar",
                "match_any": ("reaction", "reactions", "emoji"),
            },
            {
                "label": "\U0001F4CA So'rovnomalarda ovoz berish (Poll)",
                "match_any": ("poll", "vote", "votes", "ovoz", "boost"),
            },
            {
                "label": "\u2B50 Premium a'zolar va bot startlari",
                "match_any": ("premium", "bot start", "start"),
            },
        ],
    },
    {
        "label": "\u2716\uFE0F Twitter (X)",
        "platform_keywords": ("twitter", "tweet", "retweet"),
        "groups": [
            {
                "label": "\U0001F465 Kuzatuvchilar (Followers)",
                "match_any": ("follower", "followers"),
            },
            {
                "label": "\u2764\uFE0F Layklar va retvitlar/repostlar",
                "match_any": ("like", "likes", "retweet", "retweets", "repost", "reposts", "favorite"),
            },
            {
                "label": "\U0001F4CA Impressionlar",
                "match_any": ("impression", "impressions", "view", "views"),
            },
            {
                "label": "\U0001F4AC Xushbo'y sharhlar",
                "match_any": ("comment", "comments", "reply", "replies", "quote"),
            },
        ],
    },
    {
        "label": "\U0001F47B Snapchat",
        "platform_keywords": ("snapchat", "snap chat", "snap"),
        "groups": [
            {
                "label": "\U0001F441 Story ko'rishlari",
                "match_any": ("story", "view", "views"),
            },
            {
                "label": "\U0001F465 Kuzatuvchilar",
                "match_any": ("follower", "followers"),
            },
            {
                "label": "\U0001F525 Auditoriya reaksiyalari",
                "match_any": ("reaction", "reactions", "engagement", "audience"),
            },
        ],
    },
    {
        "label": "\U0001F3AE Twitch",
        "platform_keywords": ("twitch",),
        "groups": [
            {
                "label": "\U0001F534 Jonli efir ko'rishlari (Live)",
                "match_any": ("live", "viewer", "viewers", "stream", "watch"),
            },
            {
                "label": "\U0001F465 Kuzatuvchilar (Followers)",
                "match_any": ("follower", "followers"),
            },
            {
                "label": "\U0001F4AC Chat faoliyati",
                "match_any": ("chat", "message", "messages"),
            },
        ],
    },
    {
        "label": "\U0001F3A7 Spotify",
        "platform_keywords": ("spotify",),
        "groups": [
            {
                "label": "\u25B6\uFE0F Tinglashlar (Plays)",
                "match_any": ("play", "plays", "stream", "streams"),
                "exclude_any": ("playlist", "monthly listener", "monthly listeners"),
            },
            {
                "label": "\U0001F465 Kuzatuvchilar (Followers)",
                "match_any": ("follower", "followers"),
            },
            {
                "label": "\U0001F4BE Saqlashlar va playlist boost",
                "match_any": ("save", "saves", "playlist"),
            },
            {
                "label": "\U0001F4C8 Oylik tinglovchilarni ko'paytirish",
                "match_any": ("monthly listener", "monthly listeners", "listener", "listeners"),
            },
        ],
    },
]

NETWORK_LABELS = [network["label"] for network in NETWORKS_DATA]


def main_services_keyboard():
    builder = InlineKeyboardBuilder()
    for index, network_name in enumerate(NETWORK_LABELS):
        builder.add(
            types.InlineKeyboardButton(
                text=network_name,
                callback_data=f"svc_net:{index}",
            )
        )
    builder.adjust(2)
    return builder.as_markup()


def network_groups_keyboard(network_index):
    builder = InlineKeyboardBuilder()
    network = NETWORKS_DATA[network_index]
    for group_index, group in enumerate(network["groups"]):
        builder.row(
            types.InlineKeyboardButton(
                text=group["label"],
                callback_data=f"svc_cat:{network_index}:{group_index}",
            )
        )
    builder.row(types.InlineKeyboardButton(text="\U0001F519 Orqaga", callback_data="svc_back"))
    return builder.as_markup()


def api_services_keyboard(network_index, group_index, services):
    builder = InlineKeyboardBuilder()
    for service in services[:MAX_SERVICE_BUTTONS]:
        label = f"\U0001F4A5 {service['name']} - {service['price_per_1000']:,} so'm"
        builder.row(
            types.InlineKeyboardButton(
                text=label[:64],
                callback_data=f"svc_api:{network_index}:{group_index}:{service['service_id']}",
            )
        )
    builder.row(
        types.InlineKeyboardButton(
            text="\u2B05\uFE0F Orqaga",
            callback_data=f"svc_net:{network_index}",
        )
    )
    return builder.as_markup()


def confirmation_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="\u2705 Tasdiqlash", callback_data="svc_confirm"),
        types.InlineKeyboardButton(text="\u274C Bekor qilish", callback_data="user_cancel"),
    )
    return builder.as_markup()


def build_network_text(network_name):
    return f"<b>{network_name} xizmatlari</b>\n\nKerakli bo'limni tanlang:"


def build_group_text(network_label, group_label, count):
    return (
        f"<b>{escape(network_label)} / {escape(group_label)}</b>\n\n"
        f"Topilgan xizmatlar: <b>{count}</b>\n\n"
        f"{GROUP_SERVICES_TEXT}"
    )


def _extract_service_id(service):
    return str(service.get("service") or service.get("service_id") or service.get("id") or "").strip()


def _service_haystack(service):
    return normalize_text(
        unescape(str(service.get("category", ""))),
        unescape(str(service.get("name", ""))),
    )


def _contains_any(haystack, keywords):
    return any(keyword in haystack for keyword in keywords)


def _matches_network(service, network):
    haystack = _service_haystack(service)
    return _contains_any(haystack, network["platform_keywords"])


def _matches_group(service, group):
    haystack = _service_haystack(service)
    if not _contains_any(haystack, group["match_any"]):
        return False
    excluded = group.get("exclude_any", ())
    if excluded and _contains_any(haystack, excluded):
        return False
    return True


async def _get_runtime_pricing():
    usd_rate_raw = await db.get_setting("usd_rate", str(DEFAULT_USD_RATE))
    markup_raw = await db.get_setting("markup_percentage", str(DEFAULT_MARKUP_PERCENT))
    try:
        usd_rate = int(float(usd_rate_raw))
    except (TypeError, ValueError):
        usd_rate = DEFAULT_USD_RATE
    try:
        markup_percent = float(markup_raw)
    except (TypeError, ValueError):
        markup_percent = float(DEFAULT_MARKUP_PERCENT)
    return usd_rate, markup_percent


def _prepare_service_card(raw_service, usd_rate, markup_percent):
    service_id = _extract_service_id(raw_service)
    service_name = unescape(str(raw_service.get("name", ""))).strip()
    if not service_id or not service_name:
        return None

    try:
        min_order = int(float(raw_service.get("min", 0) or 0))
    except (TypeError, ValueError):
        min_order = 0
    try:
        max_order = int(float(raw_service.get("max", 0) or 0))
    except (TypeError, ValueError):
        max_order = 0

    price_per_1000 = int(
        calculate_price_uzs(
            raw_service.get("rate", raw_service.get("price", 0)),
            usd_rate,
            markup_percent,
        )
    )
    if price_per_1000 <= 0:
        return None

    return {
        "service_id": service_id,
        "name": service_name,
        "price_per_1000": price_per_1000,
        "min_order": min_order,
        "max_order": max_order,
    }


async def _get_raw_services_cached():
    global _smm_services_cache, _smm_services_cache_expires_at
    now = time.monotonic()
    if _smm_services_cache is not None and now < _smm_services_cache_expires_at:
        return _smm_services_cache

    raw_services = await smm_client.get_services(apply_markup=False)
    if isinstance(raw_services, list):
        _smm_services_cache = raw_services
        _smm_services_cache_expires_at = now + SMM_CACHE_TTL
        return raw_services
    return _smm_services_cache if _smm_services_cache is not None else None


async def _load_group_services(network_index, group_index):
    raw_services = await _get_raw_services_cached()
    if raw_services is None:
        return None

    usd_rate, markup_percent = await _get_runtime_pricing()
    network = NETWORKS_DATA[network_index]
    group = network["groups"][group_index]

    prepared = []
    seen_ids = set()
    for raw_service in raw_services:
        if not isinstance(raw_service, dict):
            continue
        if not _matches_network(raw_service, network):
            continue
        if not _matches_group(raw_service, group):
            continue

        service_card = _prepare_service_card(raw_service, usd_rate, markup_percent)
        if not service_card or service_card["service_id"] in seen_ids:
            continue

        seen_ids.add(service_card["service_id"])
        prepared.append(service_card)

    prepared.sort(key=lambda item: (item["price_per_1000"], item["name"].casefold()))
    return prepared


async def _find_group_service(network_index, group_index, service_id):
    services = await _load_group_services(network_index, group_index)
    if services is None:
        return None, None
    for service in services:
        if service["service_id"] == str(service_id):
            return service, services
    return None, services


def _is_instagram_network(network_index):
    network_label = NETWORKS_DATA[network_index]["label"]
    return "instagram" in normalize_text(network_label)


async def send_services_menu(target):
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(
            SERVICES_MENU_TEXT,
            reply_markup=main_services_keyboard(),
        )
    else:
        await target.answer(
            SERVICES_MENU_TEXT,
            reply_markup=main_services_keyboard(),
        )


@router.callback_query(F.data == "svc_back")
async def services_back_callback(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await send_services_menu(call)
    await call.answer()


@router.callback_query(F.data.startswith("svc_net:"))
async def services_network_callback(call: types.CallbackQuery, state: FSMContext):
    try:
        network_index = int(call.data.split(":")[1])
        network_name = NETWORK_LABELS[network_index]
    except (IndexError, ValueError):
        await call.answer("Tarmoq topilmadi.", show_alert=True)
        return

    await state.clear()
    await call.message.edit_text(
        build_network_text(network_name),
        reply_markup=network_groups_keyboard(network_index),
    )
    await call.answer()


@router.callback_query(F.data.startswith("svc_cat:"))
async def services_group_callback(call: types.CallbackQuery, state: FSMContext):
    try:
        _, network_index_raw, group_index_raw = call.data.split(":")
        network_index = int(network_index_raw)
        group_index = int(group_index_raw)
        network = NETWORKS_DATA[network_index]
        group = network["groups"][group_index]
    except (IndexError, ValueError):
        await call.answer("Bo'lim topilmadi.", show_alert=True)
        return

    await state.clear()
    services = await _load_group_services(network_index, group_index)
    if services is None:
        await call.answer("API xizmatlarini yuklab bo'lmadi.", show_alert=True)
        return
    if not services:
        await call.answer("Bu tugma vaqtincha ishlamaydi.", show_alert=True)
        return

    await call.message.edit_text(
        build_group_text(network["label"], group["label"], len(services)),
        reply_markup=api_services_keyboard(network_index, group_index, services),
    )
    await call.answer()


@router.callback_query(F.data.startswith("svc_api:"))
async def service_pick_callback(call: types.CallbackQuery, state: FSMContext):
    try:
        _, network_index_raw, group_index_raw, service_id = call.data.split(":", 3)
        network_index = int(network_index_raw)
        group_index = int(group_index_raw)
    except ValueError:
        await call.answer("Xizmat ma'lumotlari buzilgan.", show_alert=True)
        return

    service, services = await _find_group_service(network_index, group_index, service_id)
    if services is None:
        await call.answer("Xizmat ma'lumotlarini yuklab bo'lmadi.", show_alert=True)
        return
    if not service:
        await call.answer("Xizmat topilmadi yoki yangilanib ketgan.", show_alert=True)
        return

    await state.update_data(
        selected_network=NETWORK_LABELS[network_index],
        selected_network_index=network_index,
        selected_group_label=NETWORKS_DATA[network_index]["groups"][group_index]["label"],
        selected_group_index=group_index,
        service_source="api_dynamic",
        service_id=service["service_id"],
        service_name=service["name"],
        price_per_1000=service["price_per_1000"],
        min_order=service["min_order"],
        max_order=service["max_order"],
        confirm_token=secrets.token_urlsafe(16),
    )
    await state.set_state(OrderState.waiting_for_link)

    await call.message.edit_text(
        f"Tanlandi: {escape(service['name'])}\n"
        f"Narxi (1000 ta): {service['price_per_1000']:,} so'm\n\n"
        "\U0001F517 Endi havolani yuboring:",
        reply_markup=user_flow_keyboard(
            back_callback=f"svc_cat:{network_index}:{group_index}",
            back_text="\u2B05\uFE0F Orqaga",
            include_cancel=True,
        ),
    )
    await call.answer()


@router.message(OrderState.waiting_for_link)
async def service_link_handler(message: types.Message, state: FSMContext):
    link = (message.text or "").strip()
    data = await state.get_data()
    network_index = data.get("selected_network_index")
    group_index = data.get("selected_group_index")
    back_callback = None
    if network_index is not None and group_index is not None:
        back_callback = f"svc_cat:{network_index}:{group_index}"

    if not link.startswith("http"):
        return await message.answer(
            "Noto'g'ri havola. Iltimos, `http` yoki `https` bilan boshlanuvchi havola yuboring.",
            reply_markup=user_flow_keyboard(
                back_callback=back_callback,
                back_text="\u2B05\uFE0F Orqaga",
                include_cancel=True,
            ),
        )

    if network_index is not None and _is_instagram_network(network_index) and not is_instagram_link(link):
        return await message.answer(
            "Instagram xizmati uchun havola `instagram.com` domeniga tegishli bo'lishi kerak.",
            reply_markup=user_flow_keyboard(
                back_callback=back_callback,
                back_text="\u2B05\uFE0F Orqaga",
                include_cancel=True,
            ),
        )

    await state.update_data(order_link=link)
    await state.set_state(OrderState.waiting_for_quantity)
    await message.answer(
        "\U0001F522 Miqdorni kiriting:",
        reply_markup=user_flow_keyboard(
            back_callback=back_callback,
            back_text="\u2B05\uFE0F Orqaga",
            include_cancel=True,
        ),
    )


@router.message(OrderState.waiting_for_quantity)
async def service_quantity_handler(message: types.Message, state: FSMContext):
    raw_quantity = (message.text or "").strip()
    data = await state.get_data()

    if not raw_quantity.isdigit():
        return await message.answer("Miqdor faqat raqamlardan iborat bo'lishi kerak.")

    quantity = int(raw_quantity)
    min_order = int(data.get("min_order", 0) or 0)
    max_order = int(data.get("max_order", 0) or 0)

    if min_order and quantity < min_order:
        return await message.answer(f"Minimal miqdor: <b>{min_order:,}</b>")
    if max_order and quantity > max_order:
        return await message.answer(f"Maksimal miqdor: <b>{max_order:,}</b>")

    price_per_1000 = int(data.get("price_per_1000", 0) or 0)
    total_price = calculate_quantity_price_uzs(price_per_1000, quantity)

    await state.update_data(order_quantity=quantity, total_price=total_price)
    await state.set_state(OrderState.waiting_for_confirmation)
    await message.answer(
        f"Siz <b>{quantity:,}</b> ta buyurtma bermoqchisiz.\n"
        f"Jami: <b>{total_price:,}</b> so'm.\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=confirmation_keyboard(),
    )


@router.callback_query(F.data == "svc_confirm")
async def service_confirm_callback(call: types.CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        required_keys = {
            "service_id",
            "service_name",
            "order_link",
            "order_quantity",
            "price_per_1000",
            "total_price",
            "selected_network_index",
            "selected_group_index",
        }
        if not required_keys.issubset(data):
            await state.clear()
            await call.message.edit_text("❌ Buyurtma ma'lumotlari topilmadi. Qaytadan urinib ko'ring.")
            await call.answer()
            return

        network_index = int(data["selected_network_index"])
        group_index = int(data["selected_group_index"])
        service_id = str(data["service_id"])
        order_quantity = int(data["order_quantity"])
        order_link = str(data["order_link"]).strip()

        current_service, all_group_services = await _find_group_service(network_index, group_index, service_id)
        if all_group_services is None:
            await call.answer("Xizmat ma'lumotlarini tekshirib bo'lmadi.", show_alert=True)
            return
        if not current_service:
            await state.clear()
            await call.message.edit_text(
                "❌ Tanlangan xizmat API ichida topilmadi yoki o'zgargan.",
                reply_markup=user_flow_keyboard(),
            )
            await call.answer()
            return

        min_order = int(current_service["min_order"] or 0)
        max_order = int(current_service["max_order"] or 0)
        if (min_order and order_quantity < min_order) or (max_order and order_quantity > max_order):
            await state.clear()
            await call.message.edit_text(
                "❌ Xizmat limiti yangilanib ketgan. Iltimos, qaytadan tanlang.",
                reply_markup=user_flow_keyboard(),
            )
            await call.answer()
            return

        current_price = int(current_service["price_per_1000"])
        current_total = calculate_quantity_price_uzs(current_price, order_quantity)
        if current_price != int(data["price_per_1000"]) or current_total != int(data["total_price"]):
            await state.update_data(
                service_name=current_service["name"],
                price_per_1000=current_price,
                total_price=current_total,
                min_order=min_order,
                max_order=max_order,
            )
            await call.message.edit_text(
                f"Narx yangilandi: <b>{current_price:,}</b> so'm / 1000\n"
                f"Yangi jami: <b>{current_total:,}</b> so'm\n\n"
                "Davom ettirish uchun yana `Tasdiqlash` tugmasini bosing.",
                reply_markup=confirmation_keyboard(),
            )
            await call.answer("Narx yangilandi.", show_alert=True)
            return

        if network_index is not None and _is_instagram_network(network_index) and not is_instagram_link(order_link):
            await state.clear()
            await call.message.edit_text(
                "❌ Instagram havolasi yaroqsiz bo'lib qoldi. Qaytadan buyurtma bering.",
                reply_markup=user_flow_keyboard(),
            )
            await call.answer()
            return

        confirm_token = str(data.get("confirm_token", "")).strip()
        if not confirm_token or not await db.claim_action_lock(f"smm:{confirm_token}"):
            await call.answer("Bu buyurtma allaqachon qayta ishlanmoqda.", show_alert=True)
            return

        user = await db.get_user(call.from_user.id)
        balance = user["balance"] if user else 0
        if not user or balance < current_total:
            await state.clear()
            await call.message.edit_text(
                "❌ Balans yetarli emas.\n\n"
                f"Kerakli summa: <b>{current_total:,}</b> so'm\n"
                f"Sizning balans: <b>{balance:,.0f}</b> so'm",
                reply_markup=user_flow_keyboard(),
            )
            await call.answer()
            return

        spent = await db.spend_balance(
            call.from_user.id,
            current_total,
            method="SMM Purchase",
            tx_type="purchase",
            reference=f"svc:{service_id}:{order_quantity}",
        )
        if not spent:
            await call.message.edit_text(
                "⚠️ Balans o'zgargan. Qaytadan urinib ko'ring.",
                reply_markup=user_flow_keyboard(),
            )
            await call.answer()
            return

        try:
            external_order_id = await smm_client.add_order(
                service_id=service_id,
                link=order_link,
                quantity=order_quantity,
            )
        except Exception as exc:  # pragma: no cover - network safety
            logging.error("Dynamic SMM order failed: %s", exc)
            external_order_id = None

        if not external_order_id:
            await db.refund_balance(
                call.from_user.id,
                current_total,
                method="SMM Refund",
                tx_type="refund",
                reference=f"svc:{service_id}:{order_quantity}",
            )
            await state.clear()
            await call.message.edit_text(
                "⚠️ Buyurtma panelga yuborilmadi. Pul balansga qaytarildi.",
                reply_markup=user_flow_keyboard(),
            )
            await call.answer()
            return

        local_order_id = await db.add_order(
            user_id=call.from_user.id,
            service_type="SMM",
            service_name=current_service["name"],
            target=order_link,
            amount=current_total,
            external_id=str(external_order_id),
        )

        await state.clear()
        await call.message.edit_text(
            "✅ Buyurtma qabul qilindi.\n\n"
            f"🧾 Lokal ID: <code>{local_order_id}</code>\n"
            f"🌐 Panel ID: <code>{external_order_id}</code>\n"
            f"📊 Xizmat: <b>{escape(current_service['name'])}</b>\n"
            f"🔢 Miqdor: <b>{order_quantity:,}</b>\n"
            f"💰 Narx: <b>{current_total:,}</b> so'm",
            reply_markup=user_flow_keyboard(),
        )
        await call.answer()
        return
    except Exception as exc:
        logging.exception("Unexpected error in service_confirm_callback")
        await state.clear()
        try:
            await call.message.edit_text(
                "❌ Buyurtma bajarishda ichki xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.",
                reply_markup=user_flow_keyboard(),
            )
        except Exception:
            pass
        await call.answer("Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.", show_alert=True)
