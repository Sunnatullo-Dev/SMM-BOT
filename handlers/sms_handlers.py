import logging
import math
import time

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import db
from keyboards.navigation import user_flow_keyboard
from states.bot_states import BuySMS
from utils.api_client import sms_client
from utils.service_catalog import detect_country_flag, normalize_text

router = Router()

SERVICE_NAMES = {
    "tg": "Telegram",
    "wa": "WhatsApp",
    "ig": "Instagram",
}

SMS_MAIN_TEXT = "Kerakli bo'limni tanlang:"
READY_ACCOUNTS_TEXT = "\U0001F4DE <b>Tayyor Akkauntlar</b>\n\nKerakli davlatni tanlang:"
NUMBER_COUNTRIES_TEXT = "\u260E\uFE0F <b>Nomer Olish</b>\n\nDavlatni tanlang:"
SERVER_BUTTON_TEXT = "SERVER_1 \u2705"
READY_ACCOUNT_PAGE_SIZE = 10
NUMBER_COUNTRY_PAGE_SIZE = 10
COUNTRY_CACHE_TTL_SECONDS = 120

READY_ACCOUNTS = [
    {"key": "uz", "flag": "\U0001F1FA\U0001F1FF", "name": "O'zbekiston", "price_uzs": 45000},
    {"key": "ru", "flag": "\U0001F1F7\U0001F1FA", "name": "Rossiya", "price_uzs": 42000},
    {"key": "kz", "flag": "\U0001F1F0\U0001F1FF", "name": "Qozog'iston", "price_uzs": 44000},
    {"key": "us", "flag": "\U0001F1FA\U0001F1F8", "name": "AQSh", "price_uzs": 68000},
    {"key": "tr", "flag": "\U0001F1F9\U0001F1F7", "name": "Turkiya", "price_uzs": 52000},
    {"key": "ua", "flag": "\U0001F1FA\U0001F1E6", "name": "Ukraina", "price_uzs": 43000},
    {"key": "de", "flag": "\U0001F1E9\U0001F1EA", "name": "Germaniya", "price_uzs": 71000},
    {"key": "fr", "flag": "\U0001F1EB\U0001F1F7", "name": "Fransiya", "price_uzs": 73000},
    {"key": "gb", "flag": "\U0001F1EC\U0001F1E7", "name": "Angliya", "price_uzs": 76000},
    {"key": "it", "flag": "\U0001F1EE\U0001F1F9", "name": "Italiya", "price_uzs": 69000},
    {"key": "es", "flag": "\U0001F1EA\U0001F1F8", "name": "Ispaniya", "price_uzs": 70000},
    {"key": "pl", "flag": "\U0001F1F5\U0001F1F1", "name": "Polsha", "price_uzs": 47000},
    {"key": "nl", "flag": "\U0001F1F3\U0001F1F1", "name": "Niderlandiya", "price_uzs": 74000},
    {"key": "ca", "flag": "\U0001F1E8\U0001F1E6", "name": "Kanada", "price_uzs": 72000},
    {"key": "in", "flag": "\U0001F1EE\U0001F1F3", "name": "Hindiston", "price_uzs": 39000},
    {"key": "id", "flag": "\U0001F1EE\U0001F1E9", "name": "Indoneziya", "price_uzs": 41000},
    {"key": "my", "flag": "\U0001F1F2\U0001F1FE", "name": "Malayziya", "price_uzs": 48000},
    {"key": "ae", "flag": "\U0001F1E6\U0001F1EA", "name": "BAA", "price_uzs": 65000},
    {"key": "sa", "flag": "\U0001F1F8\U0001F1E6", "name": "Saudiya", "price_uzs": 62000},
    {"key": "br", "flag": "\U0001F1E7\U0001F1F7", "name": "Braziliya", "price_uzs": 53000},
    {"key": "mx", "flag": "\U0001F1F2\U0001F1FD", "name": "Meksika", "price_uzs": 54000},
    {"key": "jp", "flag": "\U0001F1EF\U0001F1F5", "name": "Yaponiya", "price_uzs": 81000},
    {"key": "kr", "flag": "\U0001F1F0\U0001F1F7", "name": "Janubiy Koreya", "price_uzs": 79000},
    {"key": "az", "flag": "\U0001F1E6\U0001F1FF", "name": "Ozarbayjon", "price_uzs": 46000},
]

NUMBER_COUNTRIES = [
    {
        "key": "uz",
        "flag": "\U0001F1FA\U0001F1FF",
        "name": "O'zbekiston",
        "aliases": ["uzbekistan", "uzb", "uz"],
    },
    {
        "key": "ru",
        "flag": "\U0001F1F7\U0001F1FA",
        "name": "Rossiya",
        "aliases": ["russia", "rus", "rossiya", "ru"],
    },
    {
        "key": "kz",
        "flag": "\U0001F1F0\U0001F1FF",
        "name": "Qozog'iston",
        "aliases": ["kazakhstan", "kazakh", "kz"],
    },
    {
        "key": "us",
        "flag": "\U0001F1FA\U0001F1F8",
        "name": "AQSh",
        "aliases": ["usa", "united states", "america", "us", "aqsh"],
    },
    {
        "key": "tr",
        "flag": "\U0001F1F9\U0001F1F7",
        "name": "Turkiya",
        "aliases": ["turkey", "turkiye", "tr"],
    },
    {
        "key": "ua",
        "flag": "\U0001F1FA\U0001F1E6",
        "name": "Ukraina",
        "aliases": ["ukraine", "ua"],
    },
    {
        "key": "de",
        "flag": "\U0001F1E9\U0001F1EA",
        "name": "Germaniya",
        "aliases": ["germany", "deutschland", "de"],
    },
    {
        "key": "fr",
        "flag": "\U0001F1EB\U0001F1F7",
        "name": "Fransiya",
        "aliases": ["france", "fr"],
    },
    {
        "key": "gb",
        "flag": "\U0001F1EC\U0001F1E7",
        "name": "Angliya",
        "aliases": ["uk", "united kingdom", "great britain", "england", "gb"],
    },
    {
        "key": "it",
        "flag": "\U0001F1EE\U0001F1F9",
        "name": "Italiya",
        "aliases": ["italy", "it"],
    },
    {
        "key": "es",
        "flag": "\U0001F1EA\U0001F1F8",
        "name": "Ispaniya",
        "aliases": ["spain", "es"],
    },
    {
        "key": "pl",
        "flag": "\U0001F1F5\U0001F1F1",
        "name": "Polsha",
        "aliases": ["poland", "pl"],
    },
    {
        "key": "nl",
        "flag": "\U0001F1F3\U0001F1F1",
        "name": "Niderlandiya",
        "aliases": ["netherlands", "holland", "nl"],
    },
    {
        "key": "ca",
        "flag": "\U0001F1E8\U0001F1E6",
        "name": "Kanada",
        "aliases": ["canada", "ca"],
    },
    {
        "key": "in",
        "flag": "\U0001F1EE\U0001F1F3",
        "name": "Hindiston",
        "aliases": ["india", "in"],
    },
    {
        "key": "id",
        "flag": "\U0001F1EE\U0001F1E9",
        "name": "Indoneziya",
        "aliases": ["indonesia", "id"],
    },
    {
        "key": "my",
        "flag": "\U0001F1F2\U0001F1FE",
        "name": "Malayziya",
        "aliases": ["malaysia", "my"],
    },
    {
        "key": "ae",
        "flag": "\U0001F1E6\U0001F1EA",
        "name": "BAA",
        "aliases": ["uae", "united arab emirates", "dubai", "ae"],
    },
    {
        "key": "sa",
        "flag": "\U0001F1F8\U0001F1E6",
        "name": "Saudiya",
        "aliases": ["saudi arabia", "saudi", "sa"],
    },
    {
        "key": "br",
        "flag": "\U0001F1E7\U0001F1F7",
        "name": "Braziliya",
        "aliases": ["brazil", "br"],
    },
    {
        "key": "mx",
        "flag": "\U0001F1F2\U0001F1FD",
        "name": "Meksika",
        "aliases": ["mexico", "mx"],
    },
    {
        "key": "jp",
        "flag": "\U0001F1EF\U0001F1F5",
        "name": "Yaponiya",
        "aliases": ["japan", "jp"],
    },
    {
        "key": "kr",
        "flag": "\U0001F1F0\U0001F1F7",
        "name": "Janubiy Koreya",
        "aliases": ["south korea", "korea", "kr"],
    },
    {
        "key": "az",
        "flag": "\U0001F1E6\U0001F1FF",
        "name": "Ozarbayjon",
        "aliases": ["azerbaijan", "az"],
    },
    {
        "key": "kg",
        "flag": "\U0001F1F0\U0001F1EC",
        "name": "Qirg'iziston",
        "aliases": ["kyrgyzstan", "kg", "qirgiziston"],
    },
    {
        "key": "tj",
        "flag": "\U0001F1F9\U0001F1EF",
        "name": "Tojikiston",
        "aliases": ["tajikistan", "tj"],
    },
]

COUNTRY_OVERRIDES = {item["key"]: item for item in NUMBER_COUNTRIES}
_live_country_cache = []
_live_country_cache_expires_at = 0.0


def paginate_items(items, page, page_size):
    total_pages = max(1, math.ceil(len(items) / page_size))
    current_page = min(max(int(page), 1), total_pages)
    start_index = (current_page - 1) * page_size
    end_index = start_index + page_size
    return items[start_index:end_index], current_page, total_pages


def sms_section_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="\U0001F4DE Tayyor Akkauntlar",
            callback_data="sms_menu_ready",
        ),
        types.InlineKeyboardButton(
            text="\u260E\uFE0F Nomer Olish",
            callback_data="sms_menu_number",
        ),
    )
    builder.row(types.InlineKeyboardButton(text="\U0001F3E0 Asosiy sahifa", callback_data="user_main"))
    return builder.as_markup()


def build_pagination_row(builder, prefix, page, total_pages, next_text):
    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            types.InlineKeyboardButton(
                text="\u2B05\uFE0F Oldingi",
                callback_data=f"{prefix}_page_{page - 1}",
            )
        )
    nav_buttons.append(
        types.InlineKeyboardButton(
            text=f"{page}/{total_pages}",
            callback_data="sms_noop",
        )
    )
    if page < total_pages:
        nav_buttons.append(
            types.InlineKeyboardButton(
                text=next_text,
                callback_data=f"{prefix}_page_{page + 1}",
            )
        )
    builder.row(*nav_buttons)


def ready_accounts_keyboard(page=1):
    current_items, current_page, total_pages = paginate_items(
        READY_ACCOUNTS,
        page,
        READY_ACCOUNT_PAGE_SIZE,
    )
    builder = InlineKeyboardBuilder()
    for item in current_items:
        builder.add(
            types.InlineKeyboardButton(
                text=f"{item['flag']} {item['name']} - {item['price_uzs']:,} uzs",
                callback_data=f"ready_acc_{item['key']}",
            )
        )
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text=SERVER_BUTTON_TEXT, callback_data="sms_server_info"))
    build_pagination_row(builder, "sms_ready", current_page, total_pages, "\u25B6\uFE0F Keyingi")
    return builder.as_markup()


def number_countries_keyboard(items, page=1):
    current_items, current_page, total_pages = paginate_items(
        items,
        page,
        NUMBER_COUNTRY_PAGE_SIZE,
    )
    builder = InlineKeyboardBuilder()
    for item in current_items:
        price_suffix = f" - {int(item.get('price_uzs', 0) or 0):,} so'm" if int(item.get("price_uzs", 0) or 0) > 0 else ""
        builder.add(
            types.InlineKeyboardButton(
                text=f"{item['flag']} {item['name']}{price_suffix}",
                callback_data=f"sms_country|{item.get('provider_code', item['key']).lower()}|{current_page}",
            )
        )
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="🎉 Arzon raqamlar", callback_data="sms_cheap"))
    builder.row(types.InlineKeyboardButton(text=SERVER_BUTTON_TEXT, callback_data="sms_server_info"))
    build_pagination_row(builder, "sms_numbers", current_page, total_pages, "Keyingi-➡")
    return builder.as_markup()


def get_ready_account(key):
    return next((item for item in READY_ACCOUNTS if item["key"] == key), None)

def get_number_country_from_items(key, items):
    normalized_key = str(key or "").strip().lower()
    return next((item for item in items if str(item.get("key", "")).strip().lower() == normalized_key), None)


def country_aliases(country_item):
    aliases = set(country_item.get("aliases", []))
    aliases.add(country_item["key"])
    aliases.add(country_item["name"])
    return {normalize_text(alias) for alias in aliases if alias}


def flag_from_country_code(code):
    normalized = str(code or "").strip().upper()
    if len(normalized) != 2 or not normalized.isalpha():
        return "\U0001F3F3\uFE0F"
    return "".join(chr(127397 + ord(char)) for char in normalized)


async def get_live_number_countries(force_refresh=False):
    global _live_country_cache, _live_country_cache_expires_at

    now = time.monotonic()
    if not force_refresh and _live_country_cache and now < _live_country_cache_expires_at:
        return [dict(item) for item in _live_country_cache]

    countries_data = await sms_client.get_countries()
    if not countries_data:
        if _live_country_cache:
            return [dict(item) for item in _live_country_cache]
        return []

    live_items = []
    for raw_code, raw_info in sorted(
        countries_data.items(),
        key=lambda item: normalize_text(item[1].get("name", item[0])),
    ):
        provider_code = str(raw_info.get("code") or raw_code or "").strip().upper()
        if not provider_code:
            continue
        key = provider_code.lower()
        static_item = COUNTRY_OVERRIDES.get(key)
        name = str(raw_info.get("name") or (static_item["name"] if static_item else provider_code)).strip()
        aliases = set(static_item.get("aliases", [])) if static_item else set()
        aliases.update({provider_code, key, name})
        display_price = await db.get_sms_price(provider_code, "tg", raw_info.get("price", 0))
        live_items.append(
            {
                "key": key,
                "provider_code": provider_code,
                "flag": static_item["flag"] if static_item else flag_from_country_code(provider_code) or detect_country_flag(name),
                "name": name,
                "aliases": sorted(alias for alias in aliases if alias),
                "price_uzs": display_price,
                "count": int(raw_info.get("count", 1) or 1),
            }
        )
    _live_country_cache = [dict(item) for item in live_items]
    _live_country_cache_expires_at = now + COUNTRY_CACHE_TTL_SECONDS
    return live_items


async def render_sms_main(target):
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(SMS_MAIN_TEXT, reply_markup=sms_section_keyboard())
        await target.answer()
        return
    await target.answer(SMS_MAIN_TEXT, reply_markup=sms_section_keyboard())


async def render_ready_accounts(target, page=1, markup_only=False):
    markup = ready_accounts_keyboard(page)
    if isinstance(target, types.CallbackQuery):
        if markup_only:
            await target.message.edit_reply_markup(reply_markup=markup)
        else:
            await target.message.edit_text(READY_ACCOUNTS_TEXT, reply_markup=markup)
        await target.answer()
        return
    await target.answer(READY_ACCOUNTS_TEXT, reply_markup=markup)


async def render_number_countries(target, page=1, markup_only=False):
    countries = await get_live_number_countries(force_refresh=not markup_only and page == 1)
    if not countries:
        error_text = "⚠️ Hozircha davlatlar ro'yxatini API'dan olib bo'lmadi. Keyinroq urinib ko'ring."
        if isinstance(target, types.CallbackQuery):
            await target.message.edit_text(
                error_text,
                reply_markup=user_flow_keyboard(back_callback="sms_menu_number"),
            )
            await target.answer("API javob bermadi.", show_alert=True)
            return
        await target.answer(error_text, reply_markup=user_flow_keyboard())
        return
    markup = number_countries_keyboard(countries, page)
    if isinstance(target, types.CallbackQuery):
        if markup_only:
            await target.message.edit_reply_markup(reply_markup=markup)
        else:
            await target.message.edit_text(NUMBER_COUNTRIES_TEXT, reply_markup=markup)
        await target.answer()
        return
    await target.answer(NUMBER_COUNTRIES_TEXT, reply_markup=markup)


async def resolve_live_country(country_item, service_code):
    countries_data = await sms_client.get_countries(service_code)
    if not isinstance(countries_data, dict):
        return None, None

    provider_code = str(country_item.get("provider_code") or country_item.get("key") or "").strip().upper()
    if provider_code and provider_code in countries_data:
        return provider_code, countries_data[provider_code]

    wanted_aliases = country_aliases(country_item)
    partial_match = None

    for country_id, country_info in countries_data.items():
        response_code = str(country_info.get("code") or country_id or "").strip().upper()
        if provider_code and response_code == provider_code:
            return response_code, country_info
        provider_name = normalize_text(country_info.get("name", ""))
        if not provider_name:
            continue
        if provider_name in wanted_aliases:
            return response_code or str(country_id), country_info
        if any(alias and (alias in provider_name or provider_name in alias) for alias in wanted_aliases):
            partial_match = (response_code or str(country_id), country_info)

    return partial_match or (None, None)


@router.message(F.text == "📞 Raqam olish")
async def sms_rules_handler(message: types.Message, state: FSMContext):
    await state.clear()
    text = (
        "<b>🚀 Bizning bot orqali taqdim etilayotgan akkauntlar — tayyor ochilgan Telegram akkauntlar bazasidan olinadi "
        "va sotib olishdan oldin maʼlumotlarni tekshirish sizning vazifangizdir:</b>\n\n"
        "<blockquote>⚠️ Kod faqat <u>Telegraph</u> ilovasi orqali yuborilishi lozim! agar Telegramning Rasmiy ilovasidan kod yuborilsa, "
        "kod yetib bormasligi yoki xatoliklar boʻlishi mumkin — buning uchun adminlar javobgar emas!\n\n"
        "‼️ Sotib olingan akkauntlar uchun hech qanday kafolat yoʻq. Muammo boʻlsa, pulni qaytarish yoki almashtirish kafolati berilmaydi. ❌\n\n"
        "✅ Raqamni toʻgʻri ishlatish, spamdan saqlash va xavfsizlik choralariga rioya qilish — butunlay foydalanuvchi masʼuliyatidadir. 🛡️</blockquote>\n\n"
        "<b>👆 Qoidalar bilan tanishib chiqing va \"✅ Davom etish\" tugmasini bosing!</b>"
    )
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="✅ Davom etish", callback_data="nomerolamiz"))
    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "nomerolamiz")
async def sms_start_handler(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_number_countries(call, page=1, markup_only=False)


@router.callback_query(F.data == "sms_menu_ready")
async def sms_ready_menu_handler(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_ready_accounts(call, page=1, markup_only=False)


@router.callback_query(F.data == "sms_menu_number")
async def sms_number_menu_handler(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(BuySMS.choosing_country)
    await render_number_countries(call, page=1, markup_only=False)


@router.callback_query(F.data.startswith("sms_ready_page_"))
async def sms_ready_page_handler(call: types.CallbackQuery):
    page = int(call.data.split("_")[-1])
    await render_ready_accounts(call, page=page, markup_only=True)


@router.callback_query(F.data.startswith("sms_numbers_page_"))
async def sms_numbers_page_handler(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(BuySMS.choosing_country)
    page = int(call.data.split("_")[-1])
    await render_number_countries(call, page=page, markup_only=True)


@router.callback_query(F.data == "sms_server_info")
async def sms_server_info_handler(call: types.CallbackQuery):
    await call.answer("SERVER_1 faol.", show_alert=False)


@router.callback_query(F.data == "sms_cheap")
async def sms_cheap_handler(call: types.CallbackQuery, state: FSMContext):
    try:
        countries = await get_live_number_countries()
        if not countries:
            logger.warning("No countries found for cheap list")
            return await call.answer("Xizmatlar hozircha mavjud emas.", show_alert=True)
        
        # Sort by price_uzs, ensuring it's a number
        def sort_key(x):
            p = x.get("price_uzs")
            return float(p) if p is not None else 9999999.0

        sorted_countries = sorted(countries, key=sort_key)
        cheap_list = sorted_countries[:10]
        
        builder = InlineKeyboardBuilder()
        for item in cheap_list:
            price = int(float(item.get("price_uzs", 0) or 0))
            builder.row(
                types.InlineKeyboardButton(
                    text=f"{item['flag']} {item['name']} — {price:,} so'm",
                    callback_data=f"sms_country|{item['key']}|1"
                )
            )
        
        builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="nomerolamiz"))
        
        text = "<b>✅ Eng arzon raqamlar ro'yxati:</b>\n\nQuyidagi davlatlardan birini tanlang:"
        await call.message.edit_text(text, reply_markup=builder.as_markup())
        await call.answer()
    except Exception as e:
        logger.exception("Error in sms_cheap_handler")
        await call.answer(f"Xatolik yuz berdi: {e}", show_alert=True)


@router.callback_query(F.data == "sms_noop")
async def sms_noop_handler(call: types.CallbackQuery):
    await call.answer()


@router.callback_query(F.data.startswith("ready_acc_"))
async def ready_account_pick_handler(call: types.CallbackQuery):
    item_key = call.data.removeprefix("ready_acc_")
    item = get_ready_account(item_key)
    if not item:
        await call.answer("Davlat topilmadi.", show_alert=True)
        return
    await call.answer(
        f"{item['name']} tayyor akkauntlari tez orada ulanadi.",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("sms_country|"))
async def sms_country_handler(call: types.CallbackQuery, state: FSMContext):
    try:
        _, country_key, page_raw = call.data.split("|")
        page = int(page_raw)
    except ValueError:
        await call.answer("Davlat ma'lumotlari buzilgan.", show_alert=True)
        return

    live_countries = await get_live_number_countries()
    country = get_number_country_from_items(country_key, live_countries)
    if not country:
        await call.answer("Bu davlat hozir API ro'yxatida yo'q.", show_alert=True)
        return

    await state.update_data(
        country_key=country["key"],
        provider_country_code=str(country.get("provider_code", country["key"])).upper(),
        country_name=country["name"],
        country_flag=country["flag"],
        country_page=page,
    )
    await state.set_state(BuySMS.choosing_service)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="\u2708\uFE0F Telegram", callback_data="sms_svc_tg"))
    builder.row(types.InlineKeyboardButton(text="\U0001F4AC WhatsApp", callback_data="sms_svc_wa"))
    builder.row(types.InlineKeyboardButton(text="\U0001F4F8 Instagram", callback_data="sms_svc_ig"))
    builder.row(
        types.InlineKeyboardButton(
            text="\U0001F519 Davlatlarga qaytish",
            callback_data=f"sms_numbers_page_{page}",
        ),
        types.InlineKeyboardButton(text="\U0001F3E0 Asosiy sahifa", callback_data="user_main"),
    )

    text = (
        f"{country['flag']} <b>DAVLAT: {country['name'].upper()}</b>\n\n"
        "\u26A1\uFE0F <i>Ushbu davlat uchun mavjud servislar:</i>\n\n"
        "\U0001F447 <b>Servisni tanlang:</b>"
    )
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("sms_svc_"))
async def sms_service_handler(call: types.CallbackQuery, state: FSMContext):
    service_code = call.data.split("_")[-1]
    service_name = SERVICE_NAMES.get(service_code)
    data = await state.get_data()
    country_name = data.get("country_name", "Unknown")
    country_flag = data.get("country_flag", "\U0001F3F3\uFE0F")
    country_page = int(data.get("country_page", 1) or 1)
    country_key = data.get("country_key")
    provider_country_code = str(data.get("provider_country_code", country_key or "")).strip().upper()

    live_countries = await get_live_number_countries()
    country = get_number_country_from_items(country_key, live_countries) if country_key else None
    if not service_name or not country:
        await state.clear()
        await call.answer("Jarayonni qaytadan boshlang.", show_alert=True)
        return

    country["provider_code"] = provider_country_code or str(country.get("provider_code", country["key"])).upper()
    country_id, country_info = await resolve_live_country(country, service_code)
    if not country_id or not country_info:
        await call.answer("Bu servis tanlangan davlatda mavjud emas.", show_alert=True)
        return

    api_price = float(country_info.get("price", 0) or 0)
    price = await db.get_sms_price(country_id, service_code, api_price)
    available = int(country_info.get("count", 1) or 1)
    if price <= 0:
        await call.answer("Narxni aniqlab bo'lmadi.", show_alert=True)
        return
    if available <= 0:
        await call.answer("Hozircha raqam tugagan.", show_alert=True)
        return

    user = await db.get_user(call.from_user.id)
    balance = user["balance"] if user else 0
    if not user or balance < price:
        await call.message.edit_text(
            "\u274C Balans yetarli emas.\n\n"
            f"Kerakli summa: <b>{price:,.0f}</b> so'm\n"
            f"Sizning balans: <b>{balance:,.0f}</b> so'm",
            reply_markup=user_flow_keyboard(
                back_callback=f"sms_numbers_page_{country_page}",
                back_text="\U0001F519 Davlatlarga qaytish",
            ),
        )
        await call.answer("Balans yetarli emas.", show_alert=True)
        return

    await state.update_data(
        purchase_price=price,
        purchase_service_code=service_code,
        purchase_country_id=country_id,
        purchase_service_name=service_name
    )

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="✅ Sotib olish", callback_data="sms_confirm_yes"))
    builder.row(types.InlineKeyboardButton(text="🚫 Bekor qilish", callback_data=f"sms_country|{country_key}|{country_page}"))

    text = (
        "📋 <b>Buyurtmangizni tasdiqlang:</b>\n\n"
        f"🌏 Davlat: <b>{country_name} {country_flag}</b>\n"
        f"💵 Narxi: <b>{price:,.0f} so'm!</b>\n\n"
        "<blockquote>⚠️ Nomerni Rasmiy ilovadan faollashtirmang! faqat norasmiy "
        "ilovalardan foydalaning!</blockquote>\n\n"
        "✅ Buyurtma bilan tanishib chiqib ( ✅ Sotib olish ) tugmasini bosing!"
    )
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data == "sms_confirm_yes")
async def sms_confirm_purchase_handler(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    price = data.get("purchase_price")
    service_code = data.get("purchase_service_code")
    country_id = data.get("purchase_country_id")
    service_name = data.get("purchase_service_name")
    country_name = data.get("country_name", "Unknown")
    country_flag = data.get("country_flag", "")
    country_page = int(data.get("country_page", 1) or 1)

    if not all([price, service_code, country_id]):
        await call.answer("Ma'lumotlar eskirgan. Qaytadan urinib ko'ring.", show_alert=True)
        return

    # Anti-spam/double-click lock
    lock_key = f"sms_buy:{call.from_user.id}:{country_id}:{service_code}"
    if not await db.claim_action_lock(lock_key):
        await call.answer("⏳ Buyurtma allaqachon bajarilmoqda. Iltimos, kuting...", show_alert=True)
        return

    # Check balance again just in case
    user = await db.get_user(call.from_user.id)
    if not user or user["balance"] < price:
        await call.answer("Mablag' yetarli emas.", show_alert=True)
        return

    balance_spent = await db.spend_balance(
        call.from_user.id,
        price,
        method="SMS Purchase",
        tx_type="purchase",
        reference=f"sms:{service_code}:{country_id}",
    )
    if not balance_spent:
        await call.answer("Balans o'zgargan. Qaytadan urinib ko'ring.", show_alert=True)
        return

    await call.message.edit_text("⏳ <b>Raqam olinmoqda...</b>")

    try:
        api_response = await sms_client.buy_number(service_code, country_id, price=price)
    except Exception as exc:
        logger.error("SMS buy_number failed: %s", exc)
        api_response = {"error": str(exc)}

    if not isinstance(api_response, dict) or str(api_response.get("status", "")).lower() != "ok":
        await db.refund_balance(
            call.from_user.id,
            price,
            method="SMS Refund",
            tx_type="refund",
            reference=f"sms:{service_code}:{country_id}",
        )
        await call.message.edit_text(
            "⚠️ Raqam olishning iloji bo'lmadi. Pul balansga qaytarildi.",
            reply_markup=user_flow_keyboard(
                back_callback=f"sms_numbers_page_{country_page}",
                back_text="🔙 Davlatlarga qaytish",
            ),
        )
        await state.clear()
        await call.answer()
        return

    phone_number = str(api_response.get("phone", "")).strip()
    activation_id = str(api_response.get("hash") or phone_number).strip()
    provider_country_name = str(api_response.get("country") or country_name).strip()
    if not phone_number or not activation_id:
        await db.refund_balance(
            call.from_user.id,
            price,
            method="SMS Refund",
            tx_type="refund",
            reference=f"sms:{service_code}:{country_id}",
        )
        await call.message.edit_text(
            "⚠️ Provider noto'g'ri javob qaytardi. Pul balansga qaytarildi.",
            reply_markup=user_flow_keyboard(
                back_callback=f"sms_numbers_page_{country_page}",
                back_text="🔙 Davlatlarga qaytish",
            ),
        )
        await state.clear()
        await call.answer()
        return

    local_order_id = await db.add_order(
        user_id=call.from_user.id,
        service_type="SMS",
        service_name=f"{service_name} - {provider_country_name}",
        target=phone_number,
        amount=price,
        external_id=str(activation_id),
    )

    await call.message.edit_text(
        "✅ <b>RAQAM OLINDI</b>\n\n"
        "💳 <b>Buyurtma tafsilotlari:</b>\n"
        f"├─ 🧾 Lokal ID: <code>{local_order_id}</code>\n"
        f"├─ 📱 Servis: <b>{service_name}</b>\n"
        f"├─ {country_flag} Davlat: <b>{provider_country_name}</b>\n"
        f"├─ 💰 Narx: <b>{price:,.0f}</b> so'm\n"
        f"└─ 🌐 Hash: <code>{activation_id}</code>\n\n"
        f"📞 <b>RAQAM:</b> <code>{phone_number}</code>\n\n"
        "⚠️ <i>Kod kelganda avtomatik xabar yuboriladi yoki 'Buyurtmalarim' bo'limidan tekshiring.</i>",
        reply_markup=user_flow_keyboard(),
    )
    await state.clear()
    await call.answer("Raqam tayyor.")
