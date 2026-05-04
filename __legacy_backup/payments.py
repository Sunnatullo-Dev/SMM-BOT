from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from states.bot_states import Deposit
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()

@router.message(F.text == "📩 Hisob To'ldirish")
async def deposit_start(message: types.Message, state: FSMContext):
    await message.answer("💰 <b>Qancha summa qo'shmoqchisiz?</b>\n(Minimal: 1,000 so'm)")
    await state.set_state(Deposit.entering_amount)

@router.message(Deposit.entering_amount)
async def deposit_amount_entered(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    from database.models import db
    user = await db.get_user(user_id)
    internal_id = user['id'] if user else "Topilmadi"
    if not message.text.isdigit():
        return await message.answer("❌ Faqat raqam kiriting!")
    
    amount = int(message.text)
    if amount < 5000:
        return await message.answer("❌ Minimal summa 1,000 so'm!")
    
    await state.update_data(amount=amount)
    
    card_number = "5614 6847 0909 0318" # Demo card
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📋 Kartani nusxalash", callback_data=f"copy_card_{card_number.replace(' ', '')}"))
    builder.row(types.InlineKeyboardButton(text="✅ To'ladim", callback_data="confirm_payment"))
    
    text = (
        f"💳 <b>To'lov ma'lumotlari:</b>\n\n"
        f"💰 <b>To'lov summasi:</b> {amount:,.0f} so'm\n"
        f"💳 <b>Karta:</b> <code>{card_number}</code>\n"
        f"👤 <b>Ega:</b> Sunnatulla Samandarov\n\n"
        f"⚠️ <b>Muhim:</b> To'lov o'tkazayotganda <b>izoh (kommentariya)</b> qismiga o'z ID raqamingizni yozishni unutmang!\n"
        f"📝 <b>Sizning ID raqamingiz:</b> <code>{internal_id}</code>\n\n"
        "<i>To'lovni amalga oshirgach 'To'ladim' tugmasini bosing.</i>"
    )
    
    await message.answer(text, reply_markup=builder.as_markup())
    await state.set_state(Deposit.confirming_payment)

@router.callback_query(F.data == "confirm_payment")
async def confirm_payment(call: types.CallbackQuery, state: FSMContext, bot: types.Bot):
    data = await state.get_data()
    amount = data.get('amount')
    user_id = call.from_user.id
    
    if not amount:
        return await call.message.edit_text("❌ Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.")
        
    # Adminga yuborish
    from config import ADMINS
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_{user_id}_{amount}"),
        types.InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{user_id}")
    )
    
    for admin in ADMINS:
        try:
            await bot.send_message(
                admin,
                f"💳 <b>Yangi to'lov!</b>\n\n"
                f"👤 Foydalanuvchi: {call.from_user.full_name} (<code>{user_id}</code>)\n"
                f"💰 Summa: {amount:,.0f} so'm\n\n"
                f"Iltimos, to'lovni tasdiqlang:",
                reply_markup=builder.as_markup()
            )
        except Exception:
            pass

    await call.message.edit_text(
        "⏳ <b>To'lovingiz tekshirilmoqda...</b>\n\n"
        "Operator to'lovni tasdiqlashi bilan balansigizga tushadi. "
        "Odatda 5-15 daqiqa vaqt oladi."
    )
    await state.clear()
