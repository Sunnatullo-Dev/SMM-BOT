import asyncio
import logging
from html import escape
from aiogram import Bot
from database.models import db
from utils.api_client import smm_client

logger = logging.getLogger(__name__)

async def notify_user_order_completed(bot: Bot, order: dict):
    if not order or not order.get("user_id"):
        return

    try:
        service_name = escape(str(order.get("service_name") or "Xizmat"))
        target = escape(str(order.get("target") or "—"))
        order_id = order.get("id")
        amount = int(order.get("amount") or 0)

        text = (
            "✅ <b>Xizmat bajarildi!</b>\n\n"
            f"📌 Xizmat: <b>{service_name}</b>\n"
            f"🎯 Maqsad: <code>{target}</code>\n"
            f"💰 Summa: <b>{amount:,}</b> so'm\n"
            f"📦 Buyurtma: <code>{order_id}</code>\n"
            "🚥 Holat: <b>Tugallangan</b>\n\n"
            "<i>Mahsulotingiz hozirda yetkazib berilmoqda.</i>\n"
            "\n"
            "<b>Bizni Botimizdan Foydalanganingiz uchun minnatdormiz!</b>"
        )
        await bot.send_message(order["user_id"], text)
    except Exception as exc:
        logger.debug("Foydalanuvchiga xabar yuborilmadi: %s", exc)

async def sync_smm_orders(bot: Bot):
    """Pending va Processing holatdagi SMM buyurtmalarini API orqali tekshiradi"""
    while True:
        try:
            # 1. Sinxron qilinishi kerak bo'lgan buyurtmalarni olish
            orders = await db.get_syncable_orders(limit=50)
            if not orders:
                await asyncio.sleep(60) # Buyurtma bo'lmasa 1 daqiqa kutish
                continue

            for order in orders:
                order_id = order["id"]
                external_id = order["external_id"]
                
                if not external_id:
                    continue
                
                # 2. API orqali statusni tekshirish
                new_status = await smm_client.check_status(external_id)
                new_status = str(new_status).lower()
                
                # 3. Agar status o'zgargan bo'lsa, bazani yangilash
                # SMM API statuslari: Pending, In progress, Completed, Partial, Canceled
                status_map = {
                    "pending": "pending",
                    "in progress": "processing",
                    "processing": "processing",
                    "completed": "completed",
                    "partial": "partial",
                    "canceled": "cancelled",
                    "cancelled": "cancelled",
                    "failed": "failed"
                }
                
                mapped_status = status_map.get(new_status, "processing")
                
                if mapped_status != order["status"]:
                    await db.update_order_status(order_id, mapped_status)
                    logger.info(f"Order {order_id} status updated to {mapped_status} (API: {new_status})")
                    
                    # Agar buyurtma tugallangan bo'lsa, referal bonusini berish (agar birinchi buyurtma bo'lsa)
                    if mapped_status == "completed":
                        await db.award_referral_bonus_for_completed_order(order["user_id"], order_id)
                        await notify_user_order_completed(bot, order)

            await asyncio.sleep(300) # Har 5 daqiqada bir marta tekshirish
            
        except Exception as e:
            logger.error(f"Error in sync_smm_orders: {e}")
            await asyncio.sleep(60)
