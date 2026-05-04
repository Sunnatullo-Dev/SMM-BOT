import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_LIST
from database.models import db
from states.bot_states import AdminStates

router = Router()
logger = logging.getLogger(__name__)


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


async def render_user_card(target, user):
    if not user:
        if isinstance(target, types.CallbackQuery):
            await target.answer("❌ Foydalanuvchi topilmadi.", show_alert=True)
        else:
            await target.answer("❌ Foydalanuvchi topilmadi.")
        return

    is_blocked_label = "🔴 Bloklangan" if user["is_blocked"] else "🟢 Faol"
    orders_count, total_deposited = await db.get_user_stats(user["user_id"])

    text = (
        "👤 <b>Foydalanuvchi kartasi</b>\n\n"
        f"🆔 Tartib ID: <code>{user['id']}</code>\n"
        f"🔗 Telegram ID: <code>{user['user_id']}</code>\n"
        f"👤 Ism: <b>{user['full_name']}</b>\n"
        f"🌐 Username: @{user['username'] or 'yoq'}\n"
        f"🚥 Holat: <b>{is_blocked_label}</b>\n\n"
        f"💰 Balans: <b>{user['balance']:,.0f}</b> so'm\n"
        f"📦 Buyurtmalar: <b>{orders_count} ta</b>\n"
        f"📥 Jami to'lov: <b>{total_deposited:,.0f}</b> so'm\n"
        f"🕒 Qo'shilgan: <code>{user['registered_at']}</code>"
    )

    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=user_card_keyboard(user))
    else:
        await target.answer(text, reply_markup=user_card_keyboard(user))


@router.callback_query(F.data == "adm_user_lookup", F.from_user.id.in_(ADMIN_LIST))
async def adm_user_lookup_start(call: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    await call.message.edit_text(
        "👤 <b>Foydalanuvchi qidirish</b>\n\nFoydalanuvchi <b>Telegram ID</b> yoki <b>Tartib ID</b>sini yuboring:",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(AdminStates.searching_user)


@router.message(AdminStates.searching_user, F.from_user.id.in_(ADMIN_LIST))
async def adm_user_lookup_process(message: types.Message, state: FSMContext):
    query = (message.text or "").strip()
    if not query.isdigit():
        return await message.answer("❌ Iltimos, faqat raqamli ID yuboring.")

    user = await db.get_user(int(query)) or await db.get_user_by_internal_id(int(query))
    if not user:
        return await message.answer("❌ Foydalanuvchi topilmadi.")

    await state.clear()
    await render_user_card(message, user)


@router.callback_query(F.data.startswith("adm_user_toggle|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_user_toggle_process(call: types.CallbackQuery):
    _, user_id, next_status = call.data.split("|")
    user_id = int(user_id)
    next_status = int(next_status)

    await db.set_user_block_status(user_id, next_status)
    user = await db.get_user(user_id)
    await render_user_card(call, user)
    await call.answer("Holat yangilandi.")


@router.callback_query(F.data.startswith("adm_user_balance|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_user_balance_start(call: types.CallbackQuery, state: FSMContext):
    _, user_id, action = call.data.split("|")
    label = "qo'shmoqchi" if action == "add" else "ayirmoqchi"
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="adm_main"))
    await call.message.edit_text(
        f"💰 <b>Balansni o'zgartirish</b>\n\nFoydalanuvchi ID: <code>{user_id}</code>\nQancha summa {label}siz? (Faqat raqam):",
        reply_markup=builder.as_markup(),
    )
    await state.update_data(target_user_id=int(user_id), action=action)
    await state.set_state(AdminStates.editing_user_balance)


@router.message(AdminStates.editing_user_balance, F.from_user.id.in_(ADMIN_LIST))
async def adm_user_balance_process(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data["target_user_id"]
    action = data["action"]

    try:
        amount = int((message.text or "").strip())
    except ValueError:
        return await message.answer("❌ Iltimos, faqat raqam kiriting.")

    if amount <= 0:
        return await message.answer("❌ Summa 0 dan katta bo'lishi kerak.")

    signed_amount = amount if action == "add" else -amount
    balance_updated = await db.update_balance(user_id, signed_amount)
    if not balance_updated:
        return await message.answer("❌ Balansni o'zgartirib bo'lmadi.")

    await db.add_transaction(
        user_id,
        amount,
        method="Admin Edit",
        status="confirmed",
        direction="credit" if signed_amount > 0 else "debit",
        tx_type="admin_adjust",
        reference=f"admin_adjust:{user_id}",
    )

    user = await db.get_user(user_id)
    await state.clear()
    await message.answer("✅ Balans muvaffaqiyatli o'zgartirildi.")
    await render_user_card(message, user)
