from aiogram import Router, types, F
from aiogram.filters import CommandStart, Command
from database.models import db
from keyboards.reply import main_menu
from config import ADMINS

router = Router()

@router.message(CommandStart())
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    
    # Check for referral
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id == user_id:
            referrer_id = None

    await db.add_user(user_id, username, full_name, referrer_id)
    
    welcome_text = (
        f"👋 <b>Assalomu alaykum, {full_name}!</b>\n\n"
        "🚀 <b>Premium SMM & SMS Bot</b>ga xush kelibsiz!\n\n"
        "Bu yerda siz:\n"
        "• Ijtimoiy tarmoqlar uchun SMM xizmatlari\n"
        "• Virtual raqamlar (SMS) sotib olishingiz mumkin.\n\n"
        "👇 Kerakli bo'limni tanlang:"
    )
    
    await message.answer(welcome_text, reply_markup=main_menu())

@router.message(F.text == "📕 Qo'llanma")
async def guide_cmd(message: types.Message):
    text = (
        "📖 <b>Foydalanish bo'yicha qo'llanma:</b>\n\n"
        "1. 💳 <b>Hisobni to'ldiring</b> - 'Hisob To'ldirish' bo'limi orqali.\n"
        "2. 📞 <b>Nomer oling</b> - Kerakli davlat va servisni tanlang.\n"
        "3. 🛍️ <b>SMM xizmatlar</b> - Instagram, Telegram va boshqalar uchun buyurtma bering.\n"
        "4. 💸 <b>Pul ishlang</b> - Do'stlaringizni taklif qiling va bonusga ega bo'ling."
    )
    await message.answer(text)

@router.message(F.text == "☎️ Qo'llab-quvvatlash")
async def support_cmd(message: types.Message):
    text = (
        "🆘 <b>Yordam kerakmi?</b>\n\n"
        "Savollaringiz yoki muammolaringiz bo'lsa, adminga murojaat qiling:\n"
        "👤 @admin_username\n\n"
        "Ish vaqti: 09:00 - 22:00"
    )
    await message.answer(text)
