import logging
from html import escape

from aiogram import Router, types
from aiogram.fsm.context import FSMContext

from database.models import db
from keyboards.navigation import user_flow_keyboard
from states.bot_states import OrderSMM
from utils.api_client import smm_client
from utils.service_catalog import calculate_quantity_price_uzs

router = Router()


def calculate_smm_price(price_per_1000, quantity):
    return calculate_quantity_price_uzs(price_per_1000, quantity)


@router.message(OrderSMM.entering_quantity)
async def smm_quantity_handler(message: types.Message, state: FSMContext):
    try:
        user_data = await state.get_data()
        back_callback = f"smm_grp_{user_data.get('group_key', '')}" if user_data.get('group_key') else None

        if not message.text or not message.text.isdigit():
            return await message.answer(
                "⚠️ Miqdor faqat raqamlardan iborat bo'lishi kerak.",
                reply_markup=user_flow_keyboard(
                    back_callback=back_callback,
                    back_text="🔙 Xizmatlarga qaytish",
                    include_cancel=True,
                ),
            )

        quantity = int(message.text)

        min_order = int(user_data.get("min_order", 100) or 100)
        max_order = int(user_data.get("max_order", 50000) or 50000)
        if quantity < min_order:
            return await message.answer(
                f"⚠️ Minimal buyurtma miqdori: <b>{min_order:,}</b>",
                reply_markup=user_flow_keyboard(
                    back_callback=back_callback,
                    back_text="🔙 Xizmatlarga qaytish",
                    include_cancel=True,
                ),
            )
        if quantity > max_order:
            return await message.answer(
                f"⚠️ Maksimal buyurtma miqdori: <b>{max_order:,}</b>",
                reply_markup=user_flow_keyboard(
                    back_callback=back_callback,
                    back_text="🔙 Xizmatlarga qaytish",
                    include_cancel=True,
                ),
            )

        required_keys = {"service_id", "link", "service_name"}
        if not required_keys.issubset(user_data):
            await state.clear()
            return await message.answer("❌ Buyurtma ma'lumotlari yo'qoldi. Qaytadan tanlang.", reply_markup=user_flow_keyboard())

        final_price_per_1000 = user_data.get("final_price_per_1000", user_data.get("price_per_1000"))
        if final_price_per_1000 is None:
            await state.clear()
            return await message.answer("❌ Xizmat narxi topilmadi. Qaytadan tanlang.", reply_markup=user_flow_keyboard())

        price_uzs = calculate_smm_price(final_price_per_1000, quantity)
        user = await db.get_user(message.from_user.id)
        balance = user["balance"] if user else 0
        if not user or balance < price_uzs:
            return await message.answer(
                "❌ Balans yetarli emas.\n\n"
                f"Kerakli summa: <b>{price_uzs:,.0f}</b> so'm\n"
                f"Sizning balans: <b>{balance:,.0f}</b> so'm",
                reply_markup=user_flow_keyboard(
                    back_callback=back_callback,
                    back_text="🔙 Xizmatlarga qaytish",
                    include_cancel=True,
                ),
            )

        balance_spent = await db.spend_balance(
            message.from_user.id,
            price_uzs,
            method="SMM Purchase",
            tx_type="purchase",
            reference=f"smm:{user_data['service_id']}:{quantity}",
        )
        if not balance_spent:
            return await message.answer(
                "⚠️ Balans o'zgargan. Qaytadan urinib ko'ring.",
                reply_markup=user_flow_keyboard(
                    back_callback=back_callback,
                    back_text="🔙 Xizmatlarga qaytish",
                    include_cancel=True,
                ),
            )

        try:
            external_order_id = await smm_client.add_order(
                service_id=user_data["service_id"],
                link=user_data["link"],
                quantity=quantity,
            )
        except Exception as exc:
            logging.error("SMM order failed: %s", exc)
            external_order_id = None

        if not external_order_id:
            await db.refund_balance(
                message.from_user.id,
                price_uzs,
                method="SMM Refund",
                tx_type="refund",
                reference=f"smm:{user_data['service_id']}:{quantity}",
            )
            return await message.answer(
                "⚠️ Buyurtma panelga yuborilmadi. Pul balansga qaytarildi.",
                reply_markup=user_flow_keyboard(),
            )

        local_order_id = await db.add_order(
            user_id=message.from_user.id,
            service_type="SMM",
            service_name=user_data["service_name"],
            target=user_data["link"],
            amount=price_uzs,
            external_id=str(external_order_id),
        )

        await state.clear()
        await message.answer(
            "✅ Buyurtma qabul qilindi.\n\n"
            f"🧾 Lokal ID: <code>{local_order_id}</code>\n"
            f"🌐 Panel ID: <code>{external_order_id}</code>\n"
            f"📌 Xizmat: <b>{escape(user_data['service_name'])}</b>\n"
            f"🔢 Miqdor: <b>{quantity:,}</b>\n"
            f"💰 Narx: <b>{price_uzs:,.0f}</b> so'm\n\n"
            "Holatni `📊 Buyurtmalarim` bo'limida kuzatishingiz mumkin.",
            reply_markup=user_flow_keyboard(),
        )
        return
    except Exception as exc:
        logging.exception("Unexpected error in smm_quantity_handler")
        await state.clear()
        return await message.answer(
            "❌ Buyurtma bajarishda ichki xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.",
            reply_markup=user_flow_keyboard(),
        )
