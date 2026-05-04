import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router, types

from database.models import db
from keyboards.navigation import user_home_keyboard

logger = logging.getLogger(__name__)
UZBEKISTAN_TZ = ZoneInfo("Asia/Tashkent")

router = Router()

ORDER_STATUS_LABELS = {
    "pending": "Kutilmoqda",
    "processing": "Jarayonda",
    "completed": "Tugallangan",
    "cancelled": "Bekor qilingan",
    "failed": "Muvaffaqiyatsiz",
}


def detect_level(total_spent):
    total_spent = float(total_spent or 0)
    if total_spent >= 1_000_000:
        return "Gold"
    if total_spent >= 300_000:
        return "Silver"
    return "Bronze"


@router.message(F.text == "🖥 Akkaunt")
async def profile_handler(message: types.Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        return await message.answer("❌ Foydalanuvchi topilmadi.")

    orders_count, total_deposited = await db.get_user_stats(message.from_user.id)
    level = detect_level(user["total_spent"])
    text = (
        "🖥 <b>SHAXSIY AKKAUNT</b>\n\n"
        f"👑 Daraja: <b>{level.upper()}</b>\n\n"
        "📊 <b>Statistika:</b>\n"
        f"├─ 🆔 Tartib ID: <code>{user['id']}</code>\n"
        f"├─ 👤 Telegram ID: <code>{user['user_id']}</code>\n"
        f"├─ 💰 Joriy balans: <b>{user['balance']:,.0f}</b> so'm\n"
        f"├─ 📦 Buyurtmalar: <b>{orders_count} ta</b>\n"
        f"└─ 📥 Jami to'lov: <b>{total_deposited:,.0f}</b> so'm\n\n"
        "✨ <i>Bizning xizmatlarimizdan foydalanayotganingiz uchun rahmat!</i>"
    )
    await message.answer(text, reply_markup=user_home_keyboard())


@router.message(F.text == "📊 Buyurtmalarim")
async def orders_handler(message: types.Message):
    orders = await db.get_user_orders(message.from_user.id, limit=10)
    if not orders:
        return await message.answer("📊 Sizda hozircha buyurtmalar yo'q.", reply_markup=user_home_keyboard())

    lines = ["📊 <b>OXIRGI 10 TA BUYURTMA</b>\n"]
    for order in orders:
        try:
            created_at = datetime.strptime(str(order["created_at"])[:19], "%Y-%m-%d %H:%M:%S")
            created_at = created_at.replace(tzinfo=timezone.utc).astimezone(UZBEKISTAN_TZ)
            formatted_date = created_at.strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            logger.error(f"Error formatting date for order {order.get('id')}: {e}")
            formatted_date = str(order["created_at"])[:16]

        status_emoji = {
            "processing": "🔄",
            "completed": "✅",
            "cancelled": "❌",
            "pending": "⏳",
            "failed": "⚠️",
        }.get(order["status"], "❓")

        lines.append(
            f"📦 <b>Buyurtma #{order['id']}</b> {status_emoji}\n"
            f"├─ 📌 Xizmat: <b>{order['service_name']}</b>\n"
            f"├─ 💰 Summa: <b>{order['amount']:,.0f}</b> so'm\n"
            f"├─ 📊 Holat: <i>{ORDER_STATUS_LABELS.get(order['status'], order['status'])}</i>\n"
            f"└─ 🕒 Sana: <code>{formatted_date}</code>"
        )

    await message.answer("\n\n".join(lines), reply_markup=user_home_keyboard())
