import logging
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import ADMIN_LIST, DEFAULT_SMM_MARKUP_PERCENT
from database.models import db
from utils.api_client import smm_client

router = Router()
logger = logging.getLogger(__name__)

def service_hub_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="💸 Narxlar", callback_data="adm_prices"),
        types.InlineKeyboardButton(text="🗂 Kategoriyalar", callback_data="adm_categories"),
    )
    builder.row(
        types.InlineKeyboardButton(text="🔄 API dan sync", callback_data="adm_sync_services"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()

@router.callback_query(F.data == "adm_services", F.from_user.id.in_(ADMIN_LIST))
async def adm_services_hub(call: types.CallbackQuery):
    services = await db.get_smm_services(active_only=False)
    groups = await db.get_smm_groups(active_only=False)
    text = (
        "🛍 <b>Xizmatlarni sozlash</b>\n\n"
        f"Xizmatlar soni: <b>{len(services)}</b>\n"
        f"Guruhlar soni: <b>{len(groups)}</b>"
    )
    await call.message.edit_text(text, reply_markup=service_hub_keyboard())

@router.callback_query(F.data == "adm_sync_services", F.from_user.id.in_(ADMIN_LIST))
async def adm_sync_services(call: types.CallbackQuery):
    await call.answer("⏳ Sinxronizatsiya boshlandi...")
    try:
        raw_services = await smm_client.get_services(apply_markup=False)
        if not raw_services:
            return await call.message.answer("❌ API'dan xizmatlar olinmadi.")
        
        await db.sync_smm_services(raw_services)
        await call.message.answer(f"✅ {len(raw_services)} ta xizmat muvaffaqiyatli sinxronizatsiya qilindi.")
    except Exception as e:
        logger.exception("SMM sync error")
        await call.message.answer(f"❌ Xatolik: {e}")
