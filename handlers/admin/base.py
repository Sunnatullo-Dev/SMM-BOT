import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import ADMIN_LIST

router = Router()
logger = logging.getLogger(__name__)

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

def inline_back_keyboard(callback_data):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data=callback_data))
    return builder.as_markup()

@router.message(Command("admin"), F.from_user.id.in_(ADMIN_LIST))
async def admin_start(message: types.Message):
    await message.answer(
        "👨‍💻 <b>Admin paneliga xush kelibsiz!</b>\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=admin_main_keyboard()
    )

@router.callback_query(F.data == "adm_main", F.from_user.id.in_(ADMIN_LIST))
async def admin_main_menu_callback(call: types.CallbackQuery):
    await call.message.edit_text(
        "👨‍💻 <b>Asosiy admin paneli:</b>",
        reply_markup=admin_main_keyboard()
    )
