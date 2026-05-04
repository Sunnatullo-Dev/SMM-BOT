import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import ADMIN_LIST, USD_RATE, REFERRAL_BONUS
from database.models import db
from states.bot_states import AdminStates
from utils.api_client import smm_client

router = Router()
logger = logging.getLogger(__name__)

# Keyboardlar (admin_handlers.py dan ko'chirilgan)
def stats_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🏆 TOP 100 Balans", callback_data="adm_top_users"))
    builder.row(types.InlineKeyboardButton(text="♻️ Buyurtmalar xolatini yangilash", callback_data="adm_refresh_orders"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()

def bot_status_keyboard(is_active):
    builder = InlineKeyboardBuilder()
    toggle_text = "⏸ Botni to'xtatish" if is_active else "▶️ Botni yoqish"
    next_status = "paused" if is_active else "active"
    builder.row(types.InlineKeyboardButton(text=toggle_text, callback_data=f"adm_set_bot_status|{next_status}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()

# Handlerlar
@router.callback_query(F.data == "adm_stats", F.from_user.id.in_(ADMIN_LIST))
async def adm_stats(call: types.CallbackQuery):
    stats = await db.get_admin_stats()
    text = (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{stats['total_users']}</b>\n"
        f"🆕 Bugun qo'shilganlar: <b>{stats['today_users']}</b>\n"
        f"💰 Kunlik aylanma: <b>{stats['today_sales']:,.0f}</b> so'm\n"
        f"💵 Jami tushum: <b>{stats['total_income']:,.0f}</b> so'm\n"
        f"🏦 Foydalanuvchilar balansi: <b>{stats['total_user_balances']:,.0f}</b> so'm"
    )
    await call.message.edit_text(text, reply_markup=stats_keyboard())

@router.callback_query(F.data == "adm_bot_status", F.from_user.id.in_(ADMIN_LIST))
async def adm_bot_status(call: types.CallbackQuery):
    status = await db.get_setting("bot_status", "active")
    is_active = status == "active"
    status_label = "Ishlamoqda" if is_active else "To'xtatilgan"
    text = (
        "🤖 <b>Bot holati</b>\n\n"
        f"Hozirgi holat: <b>{status_label}</b>\n"
        "To'xtatilgan holatda bot faqat adminlar uchun ishlaydi."
    )
    await call.message.edit_text(text, reply_markup=bot_status_keyboard(is_active))

@router.callback_query(F.data.startswith("adm_set_bot_status|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_set_bot_status(call: types.CallbackQuery):
    _, new_status = call.data.split("|")
    await db.set_setting("bot_status", new_status)
    await adm_bot_status(call)
    await call.answer("Bot holati yangilandi.")

@router.callback_query(F.data == "adm_api", F.from_user.id.in_(ADMIN_LIST))
async def adm_api_settings(call: types.CallbackQuery):
    smm_url = await db.get_setting("smm_api_url", "sozlanmagan")
    sms_url = await db.get_setting("sms_api_url", "sozlanmagan")
    text = (
        "🔑 <b>API sozlamalari</b>\n\n"
        f"🌐 SMM URL: <code>{smm_url}</code>\n"
        f"🌐 SMS URL: <code>{sms_url}</code>\n\n"
        "Kalitlarni o'zgartirish uchun 'Ma'lumotlarni tahrirlash' bo'limiga o'ting."
    )
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    await call.message.edit_text(text, reply_markup=builder.as_markup())
