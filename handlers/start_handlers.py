from html import escape

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from database.models import db
from keyboards.main_menu import main_menu_keyboard

router = Router()


def _extract_referrer_id(message: types.Message) -> int:
    args = (message.text or "").split()
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != message.from_user.id:
            return referrer_id
    return 0


async def send_start_screen(message: types.Message, referrer_id: int = 0, actor: types.User | None = None):
    actor_user = actor or message.from_user
    user_id = actor_user.id
    username = actor_user.username
    full_name = actor_user.full_name

    existing_user = await db.get_user(user_id)
    start_text_override = await db.get_setting("start_text", "")

    if not existing_user:
        await db.add_user(user_id, username, full_name, referrer_id)

    user = await db.get_user(user_id)
    balance = user["balance"] if user else 0
    internal_id = user["id"] if user else "?"

    default_text = (
        f"👋 <b>XUSH KELIBSIZ, {escape((full_name or '').upper())}!</b>\n\n"
        "✨ <i>Premium SMM va SMS xizmatlari botiga xush kelibsiz. "
        "Bu yerda siz ijtimoiy tarmoqlaringizni rivojlantirishingiz va virtual raqamlardan foydalanishingiz mumkin.</i>\n\n"
        "👤 <b>Ma'lumotlaringiz:</b>\n"
        f"├─ 🆔 Tartib ID: <code>{internal_id}</code>\n"
        f"└─ 💰 Balans: <b>{balance:,.0f}</b> so'm\n\n"
        "🚀 <b>Xizmatlardan foydalanish uchun pastdagi menyudan foydalaning:</b>"
    )
    text = start_text_override if start_text_override and start_text_override != "Botga xush kelibsiz." else default_text
    await message.answer(text, reply_markup=main_menu_keyboard())


@router.message(CommandStart())
async def start_command(message: types.Message):
    await send_start_screen(message, _extract_referrer_id(message), actor=message.from_user)


@router.message(F.text == "🔙 Asosiy menyu")
async def back_to_main(message: types.Message):
    await message.answer("Asosiy menyu.", reply_markup=main_menu_keyboard())


@router.callback_query(F.data == "user_main")
async def user_main_callback(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await call.message.answer("Asosiy sahifa.", reply_markup=main_menu_keyboard())
    await call.answer()


@router.callback_query(F.data.startswith("force_sub_check"))
async def force_sub_check_callback(call: types.CallbackQuery):
    # Required-channel confirmation flow is handled in middleware.
    await call.answer()


@router.callback_query(F.data == "user_cancel")
async def user_cancel_callback(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.edit_text("❌ Jarayon bekor qilindi.")
    except TelegramBadRequest:
        pass
    await call.message.answer("Asosiy sahifa.", reply_markup=main_menu_keyboard())
    await call.answer()
