import logging
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import ADMIN_LIST
from database.models import db

router = Router()
logger = logging.getLogger(__name__)

def payment_methods_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="📋 Hamyonlar", callback_data="adm_wallets"),
        types.InlineKeyboardButton(text="💵 To'lov so'rovlari", callback_data="adm_pending_payments"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()

@router.callback_query(F.data == "adm_payment_methods", F.from_user.id.in_(ADMIN_LIST))
async def adm_payment_hub(call: types.CallbackQuery):
    wallets = await db.get_payment_wallets(active_only=False)
    pending = await db.get_pending_transactions(limit=100)
    text = (
        "💳 <b>To'lov usullari</b>\n\n"
        f"🏦 Hamyonlar: <b>{len(wallets)} ta</b>\n"
        f"⏳ Kutilayotgan to'lovlar: <b>{len(pending)} ta</b>"
    )
    await call.message.edit_text(text, reply_markup=payment_methods_keyboard())

@router.callback_query(F.data == "adm_wallets", F.from_user.id.in_(ADMIN_LIST))
async def adm_wallets_list(call: types.CallbackQuery):
    wallets = await db.get_payment_wallets(active_only=False)
    lines = ["📋 <b>Hamyonlar ro'yxati:</b>\n"]
    for w in wallets:
        status = "🟢" if w["is_active"] else "⚪"
        lines.append(f"{status} <b>{w['label']}</b>: <code>{w['wallet_number']}</code>")
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_payment_methods"))
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
