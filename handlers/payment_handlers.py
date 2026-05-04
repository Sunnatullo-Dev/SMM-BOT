import secrets
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMINS, CARD_HOLDER, CARD_NUMBER
from database.models import db
from keyboards.main_menu import main_menu_keyboard
from keyboards.navigation import user_flow_keyboard
from states.bot_states import Deposit

router = Router()
MAX_PAYMENT_AMOUNT = 1_000_000
PAYMENT_SUPPORT_URL = "https://t.me/prosmmuz_admin"
UZBEKISTAN_TZ = ZoneInfo("Asia/Tashkent")
PAYMENT_METHOD_ORDER = {
    "payme": 0,
    "all_apps_auto": 1,
    "humo_uzcard_auto": 2,
    "click": 3,
    "admin_support": 4,
}
PAYMENT_METHOD_SETTING_FLAGS = {
    "payme": "payme_enabled",
    "click": "click_enabled",
}


async def get_payment_runtime_settings():
    settings = await db.get_settings(
        [
            "card_holder",
            "card_number",
            "payme_enabled",
            "click_enabled",
            "payment_note",
            "min_payment_amount",
        ]
    )
    wallets = await db.get_payment_wallets(active_only=True)
    primary_wallet = wallets[0] if wallets else None
    try:
        min_payment_amount = int(float(settings.get("min_payment_amount", "1000") or 1000))
    except (TypeError, ValueError):
        min_payment_amount = 1000
    min_payment_amount = max(1000, min(min_payment_amount, MAX_PAYMENT_AMOUNT))
    return {
        "card_holder": settings.get("card_holder", CARD_HOLDER),
        "card_number": settings.get("card_number", CARD_NUMBER),
        "payme_enabled": settings.get("payme_enabled", "1") != "0",
        "click_enabled": settings.get("click_enabled", "1") != "0",
        "payment_note": settings.get("payment_note", "To'lov usulini tanlang va summani yuboring."),
        "min_payment_amount": min_payment_amount,
        "max_payment_amount": MAX_PAYMENT_AMOUNT,
        "wallets": wallets,
        "primary_wallet": primary_wallet,
    }


def payment_method_sort_key(method):
    return (
        PAYMENT_METHOD_ORDER.get(str(method["callback_data"] or ""), 99),
        int(method["id"]),
    )


async def get_support_contact_url():
    return PAYMENT_SUPPORT_URL


async def payment_menu_keyboard():
    runtime_settings = await get_payment_runtime_settings()
    methods = sorted(await db.get_payment_methods(active_only=True), key=payment_method_sort_key)
    builder = InlineKeyboardBuilder()
    support_url = await get_support_contact_url()

    for method in methods:
        setting_flag = PAYMENT_METHOD_SETTING_FLAGS.get(str(method["callback_data"] or ""))
        if setting_flag and not runtime_settings.get(setting_flag, True):
            continue
        if method["callback_data"] == "admin_support":
            builder.row(types.InlineKeyboardButton(text=method["name"], url=support_url))
            continue
        builder.row(
            types.InlineKeyboardButton(
                text=method["name"],
                callback_data=f"pay_method_{method['id']}",
            )
        )

    builder.row(types.InlineKeyboardButton(text="🏠 Asosiy sahifa", callback_data="user_main"))
    return builder.as_markup()


def payment_ready_keyboard(amount, method_id):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📋 Summa",
            callback_data=f"copy_text_{int(amount)}",
        ),
    )
    builder.row(types.InlineKeyboardButton(text="✅ To'ladim", callback_data="confirm_deposit"))
    builder.row(
        types.InlineKeyboardButton(text="🏠 Asosiy sahifa", callback_data="user_main"),
        types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_payment"),
    )
    return builder.as_markup()


@router.message(F.text == "💰 Hisob to'ldirish")
async def payment_start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(Deposit.choosing_method)
    runtime_settings = await get_payment_runtime_settings()

    wallet_lines = []
    for wallet in runtime_settings["wallets"][:3]:
        wallet_lines.append(
            f"├─ <b>{wallet['label']}</b>: <code>{wallet['wallet_number']}</code> ({wallet['holder_name']})"
        )
    if not wallet_lines:
        wallet_lines.append(f"├─ 💳 Karta: <code>{runtime_settings['card_number']}</code>")
        wallet_lines.append(f"└─ 👤 Ega: <b>{runtime_settings['card_holder']}</b>")
    else:
        wallet_lines[-1] = wallet_lines[-1].replace("├─", "└─", 1)

    text = (
        "💰 <b>HISOBNI TO'LDIRISH</b>\n\n"
        "🏦 <b>Hamyonlar:</b>\n"
        f"{chr(10).join(wallet_lines)}\n\n"
        f"💵 <b>Limit:</b> <b>{runtime_settings['min_payment_amount']:,.0f}</b> - "
        f"<b>{runtime_settings['max_payment_amount']:,.0f}</b> so'm\n\n"
        f"📝 <b>Izoh:</b>\n<i>{runtime_settings['payment_note']}</i>\n\n"
        "👇 <b>To'lov tizimini tanlang:</b>"
    )
    await message.answer(text, reply_markup=await payment_menu_keyboard())


@router.callback_query(F.data.startswith("pay_method_"))
async def payment_method_handler(call: types.CallbackQuery, state: FSMContext):
    method_id = int(call.data.split("_", 2)[2])
    method = await db.get_payment_method(method_id)
    if not method or not method["is_active"]:
        await call.answer("Ushbu to'lov turi vaqtincha o'chirilgan.", show_alert=True)
        return
    if method["callback_data"] == "admin_support":
        await call.answer("Admin bilan bog'lanish tugmasidan foydalaning.", show_alert=True)
        return

    await state.update_data(payment_method_id=method_id, payment_method_name=method["name"])
    await state.set_state(Deposit.entering_amount)

    instruction = (
        f"💳 <b>{method['name'].upper()} ORQALI TO'LOV</b>\n\n"
        "📝 <b>Yo'riqnoma:</b>\n"
        f"<i>{method['instruction']}</i>\n\n"
        "👇 <b>To'lov qilmoqchi bo'lgan summani so'mda yuboring:</b>\n"
        "(Masalan: <code>50000</code>)"
    )

    await call.message.edit_text(
        instruction,
        reply_markup=user_flow_keyboard(include_cancel=True),
    )
    await call.answer()


@router.message(Deposit.entering_amount)
async def amount_entered_handler(message: types.Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        return await message.answer(
            "⚠️ Summani faqat raqam bilan yuboring.",
            reply_markup=user_flow_keyboard(include_cancel=True),
        )

    amount = int(message.text)
    runtime_settings = await get_payment_runtime_settings()
    min_payment_amount = runtime_settings["min_payment_amount"]
    max_payment_amount = runtime_settings["max_payment_amount"]
    if amount < min_payment_amount:
        return await message.answer(
            f"⚠️ Minimal to'lov summasi {min_payment_amount:,.0f} so'm.",
            reply_markup=user_flow_keyboard(include_cancel=True),
        )
    if amount > max_payment_amount:
        return await message.answer(
            f"⚠️ Maksimal to'lov summasi {max_payment_amount:,.0f} so'm.",
            reply_markup=user_flow_keyboard(include_cancel=True),
        )

    data = await state.get_data()
    method_id = data.get("payment_method_id")
    method = await db.get_payment_method(method_id)
    if not method or not method["is_active"]:
        await state.clear()
        return await message.answer(
            "❌ To'lov turi topilmadi. Qaytadan urinib ko'ring.",
            reply_markup=main_menu_keyboard(),
        )

    await state.update_data(amount=amount, confirm_token=secrets.token_urlsafe(16))
    await state.set_state(Deposit.confirming_payment)

    payment_text = (
        "✅ <b>TO'LOV MA'LUMOTLARI</b>\n\n"
        "💎 <b>Tafsilotlar:</b>\n"
        f"├─ 🏦 Tizim: <b>{method['name']}</b>\n"
        f"└─ 💰 Summa: <b>{amount:,.0f}</b> so'm\n\n"
        "💳 <i>To'lovni amalga oshirgach, tasdiqlash uchun pastdagi tugmani bosing.</i>"
    )

    await message.answer(payment_text, reply_markup=payment_ready_keyboard(amount, method_id))


@router.callback_query(F.data == "confirm_deposit")
async def confirm_deposit_handler(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    amount = int(data.get("amount", 0) or 0)
    method = str(data.get("payment_method_name", "payment_request"))
    confirm_token = str(data.get("confirm_token", "")).strip()
    user = call.from_user
    requested_at = datetime.now(UZBEKISTAN_TZ)
    requested_at_text = requested_at.strftime("%Y-%m-%d %H:%M:%S")

    if amount <= 0:
        await call.answer("Summa topilmadi. Qaytadan urinib ko'ring.", show_alert=True)
        await state.clear()
        return

    if not confirm_token or not await db.claim_action_lock(f"deposit:{confirm_token}"):
        await call.answer("Bu to'lov so'rovi allaqachon yuborilgan.", show_alert=True)
        return

    transaction_id = await db.add_transaction(user.id, amount, method=method, status="pending")
    admin_text = (
        "🔔 <b>Yangi to'lov so'rovi</b>\n\n"
        f"🕒 Vaqt: <b>{requested_at_text}</b>\n"
        f"👤 Foydalanuvchi: {escape(user.full_name or '')} (@{escape(user.username or 'yoq')})\n"
        f"🆔 Telegram ID: <code>{user.id}</code>\n"
        f"💰 Summa: <b>{amount:,.0f}</b> so'm\n"
        f"💳 Usul: <b>{escape(method)}</b>\n"
        f"🧾 So'rov ID: <code>{transaction_id}</code>"
    )

    for admin_id in ADMINS:
        try:
            builder = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_tx_{transaction_id}"))
            builder.row(types.InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_tx_{transaction_id}"))
            await bot.send_message(admin_id, admin_text, reply_markup=builder.as_markup())
        except Exception:
            continue

    await state.clear()
    await call.message.edit_text(
        "⏳ <b>SO'ROV YUBORILDI</b>\n\n"
        "👤 <i>Sizning to'lov so'rovingiz adminlarga yuborildi.</i>\n\n"
        "✅ <b>Holat:</b> Tekshirilmoqda\n"
        "📦 <b>Tasdiqlash:</b> 5-15 daqiqa\n\n"
        "📨 <i>Iltimos, 5-15 daqiqadan keyin pul hisobingizda bo'ladi, agar to'lovingizda muammo bo'lmagan bo'lsa.</i>",
        reply_markup=user_flow_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("copy_text_"))
async def copy_text_handler(call: types.CallbackQuery):
    text_to_copy = call.data.split("_", 2)[-1]
    await call.message.answer(f"<code>{text_to_copy}</code>")
    await call.answer("Nusxa tayyor.")


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment_handler(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ To'lov jarayoni bekor qilindi.")
    await call.message.answer("Asosiy sahifa.", reply_markup=main_menu_keyboard())
    await call.answer()
