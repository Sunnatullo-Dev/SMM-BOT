import logging
from aiogram import Bot, Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import ADMIN_LIST
from database.models import db
from states.bot_states import AdminStates
from utils.order_sync import notify_user_order_completed

router = Router()
logger = logging.getLogger(__name__)

ORDER_STATUS_LABELS = {
    "pending": "Kutilmoqda",
    "processing": "Jarayonda",
    "completed": "Tugallangan",
    "cancelled": "Bekor qilingan",
    "failed": "Muvaffaqiyatsiz",
}

def order_check_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔎 ID bo'yicha qidirish", callback_data="adm_order_search"))
    builder.row(
        types.InlineKeyboardButton(text="⏳ Kutilayotgan", callback_data="adm_orders|pending"),
        types.InlineKeyboardButton(text="🔄 Jarayonda", callback_data="adm_orders|processing"),
    )
    builder.row(
        types.InlineKeyboardButton(text="✅ Tugallangan", callback_data="adm_orders|completed"),
        types.InlineKeyboardButton(text="❌ Bekor", callback_data="adm_orders|cancelled"),
    )
    builder.row(
        types.InlineKeyboardButton(text="⚠️ Xato", callback_data="adm_orders|failed"),
        types.InlineKeyboardButton(text="📦 Barchasi", callback_data="adm_orders|all"),
    )
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_main"))
    return builder.as_markup()

def orders_keyboard(orders, current_filter):
    builder = InlineKeyboardBuilder()
    for order in orders[:10]:
        status = ORDER_STATUS_LABELS.get(order["status"], order["status"])
        label = f"#{order['id']} {status} | {order['amount']:,.0f}"
        builder.row(types.InlineKeyboardButton(text=label[:64], callback_data=f"adm_order_card|{order['id']}|{current_filter}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_order_check"))
    return builder.as_markup()

def order_card_keyboard(order_id, current_filter):
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="⏳ Kutilayotgan", callback_data=f"adm_order_status|{order_id}|pending|{current_filter}"),
        types.InlineKeyboardButton(text="🔄 Jarayonda", callback_data=f"adm_order_status|{order_id}|processing|{current_filter}"),
    )
    builder.row(
        types.InlineKeyboardButton(text="✅ Tugallangan", callback_data=f"adm_order_status|{order_id}|completed|{current_filter}"),
        types.InlineKeyboardButton(text="❌ Bekor", callback_data=f"adm_order_status|{order_id}|cancelled|{current_filter}"),
    )
    builder.row(types.InlineKeyboardButton(text="⚠️ Xato", callback_data=f"adm_order_status|{order_id}|failed|{current_filter}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"adm_orders|{current_filter}"))
    return builder.as_markup()

@router.callback_query(F.data == "adm_order_check", F.from_user.id.in_(ADMIN_LIST))
async def adm_order_hub(call: types.CallbackQuery):
    pending = await db.count_orders_by_status("pending")
    processing = await db.count_orders_by_status("processing")
    completed = await db.count_orders_by_status("completed")
    cancelled = await db.count_orders_by_status("cancelled")
    failed = await db.count_orders_by_status("failed")
    total = pending + processing + completed + cancelled + failed
    
    text = (
        "🔍 <b>Buyurtma tekshirish</b>\n\n"
        "┌─ <b>Buyurtmalar soni</b> ─┐\n"
        f"│ ⏳ Kutilayotgan: <b>{pending}</b>\n"
        f"│ 🔄 Jarayonda: <b>{processing}</b>\n"
        f"│ ✅ Tugallangan: <b>{completed}</b>\n"
        f"│ ❌ Bekor: <b>{cancelled}</b>\n"
        f"│ ⚠️ Xato: <b>{failed}</b>\n"
        f"│ 📊 Jami: <b>{total}</b>\n"
        "└──────────────────────┘"
    )
    await call.message.edit_text(text, reply_markup=order_check_keyboard())

@router.callback_query(F.data == "adm_order_search", F.from_user.id.in_(ADMIN_LIST))
async def adm_order_search_start(call: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="adm_order_check"))
    await call.message.edit_text(
        "🔎 <b>Buyurtma qidirish</b>\n\nBuyurtma ID sini yuboring:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.searching_order)

@router.message(AdminStates.searching_order, F.from_user.id.in_(ADMIN_LIST))
async def adm_order_search_process(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ Iltimos, raqamli ID yuboring.")
    
    order = await db.get_order_by_id(int(message.text))
    if not order:
        return await message.answer("❌ Buyurtma topilmadi.")
    
    await state.clear()
    await render_order_card(message, order, "all")

async def render_order_card(target, order, current_filter):
    user = await db.get_user(order["user_id"])
    user_name = user["full_name"] if user else "N/A"
    
    status_icon = {
        "pending": "⏳",
        "processing": "🔄",
        "completed": "✅",
        "cancelled": "❌",
        "failed": "⚠️",
    }.get(order["status"], "❓")
    
    text = (
        "📦 <b>Buyurtma kartasi</b>\n\n"
        f"🆔 ID: <code>{order['id']}</code>\n"
        f"👤 Foydalanuvchi: <b>{user_name}</b>\n"
        f"📌 Xizmat: <b>{order['service_name']}</b>\n"
        f"🎯 Target: <code>{order['target']}</code>\n"
        f"💰 Summa: <b>{order['amount']:,.0f}</b> so'm\n"
        f"🌐 Panel ID: <code>{order['external_id']}</code>\n"
        f"🚥 Holat: {status_icon} <b>{ORDER_STATUS_LABELS.get(order['status'], order['status'])}</b>\n"
        f"🕒 Sana: <code>{order['created_at']}</code>"
    )
    
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=order_card_keyboard(order["id"], current_filter))
    else:
        await target.answer(text, reply_markup=order_card_keyboard(order["id"], current_filter))

@router.callback_query(F.data.startswith("adm_orders|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_orders_list(call: types.CallbackQuery):
    _, status_filter = call.data.split("|")
    orders = await db.get_recent_orders(limit=15, status=status_filter)
    
    if not orders:
        return await call.answer("❌ Buyurtmalar topilmadi.", show_alert=True)
    
    title = "Barchasi" if status_filter == "all" else ORDER_STATUS_LABELS.get(status_filter, status_filter)
    text = f"📦 <b>Buyurtmalar: {title}</b>"
    await call.message.edit_text(text, reply_markup=orders_keyboard(orders, status_filter))

@router.callback_query(F.data.startswith("adm_order_card|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_order_card_callback(call: types.CallbackQuery):
    _, order_id, current_filter = call.data.split("|")
    order = await db.get_order_by_id(int(order_id))
    await render_order_card(call, order, current_filter)

@router.callback_query(F.data.startswith("adm_order_status|"), F.from_user.id.in_(ADMIN_LIST))
async def adm_order_status_update(call: types.CallbackQuery, bot: Bot):
    _, order_id, new_status, current_filter = call.data.split("|")
    order = await db.get_order_by_id(int(order_id))
    previous_status = order["status"] if order else None
    updated_order = await db.update_order_status(int(order_id), new_status)
    if previous_status != "completed" and new_status == "completed" and updated_order:
        await notify_user_order_completed(bot, updated_order)
    await render_order_card(call, updated_order, current_filter)
    await call.answer(f"Status {new_status}ga o'zgartirildi.")
