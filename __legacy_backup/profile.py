from aiogram import Router, types, F
from database.models import db

router = Router()

@router.message(F.text == "💳 Hisobim")
async def profile_cmd(message: types.Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        return
    
    # user_id, username, full_name, balance, total_spent, referrer_id, phone_number, joined_at
    user_id, username, full_name, balance, total_spent, referrer_id, phone_number, joined_at = user
    
    text = (
        "👤 <b>Shaxsiy Kabinet</b>\n\n"
        f"🆔 <b>Sizning ID:</b> <code>{user_id}</code>\n"
        f"💰 <b>Balans:</b> {balance:,.0f} so'm\n"
        f"🛒 <b>Jami xarajatlar:</b> {total_spent:,.0f} so'm\n"
        f"📱 <b>Telefon:</b> {phone_number if phone_number else 'Kiritilmagan'}\n\n"
        "💳 <i>Balansni to'ldirish uchun 'Hisob To'ldirish' tugmasini bosing.</i>"
    )
    
    await message.answer(text)
