from aiogram import Router, types, F
from aiogram.filters import Command
from config import ADMINS
from keyboards.reply import admin_menu, main_menu
from aiogram.fsm.context import FSMContext
from states.bot_states import AdminStates
from database.models import db

router = Router()

@router.message(Command("admin"))
async def admin_start(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    
    await message.answer("👨‍💻 <b>Admin panelga xush kelibsiz!</b>", reply_markup=admin_menu())

@router.message(F.text == "🔙 Asosiy menyu")
async def back_to_main(message: types.Message):
    await message.answer("Asosiy menyuga qaytdingiz.", reply_markup=main_menu())

@router.message(F.text == "📊 Statistika")
async def stats_cmd(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    # This would count from DB
    await message.answer("📊 <b>Bot statistikasi:</b>\n\n👤 Foydalanuvchilar: 1,234 ta\n🛒 Buyurtmalar: 567 ta")

@router.message(F.text == "💰 Balans qo'shish")
async def add_balance_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("👤 <b>Foydalanuvchi ID sini kiriting:</b>")
    await state.set_state(AdminStates.adding_balance_id)

@router.message(AdminStates.adding_balance_id)
async def add_balance_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ ID raqam bo'lishi kerak!")
    
    await state.update_data(user_id=int(message.text))
    await message.answer("💰 <b>Qancha summa qo'shmoqchisiz?</b>")
    await state.set_state(AdminStates.adding_balance_amount)

@router.message(AdminStates.adding_balance_amount)
async def add_balance_amount(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ Summa raqam bo'lishi kerak!")
    
    amount = int(message.text)
    data = await state.get_data()
    user_id = data['user_id']
    
    await db.update_balance(user_id, amount)
    
    await message.answer(f"✅ ID: <code>{user_id}</code> ga {amount:,.0f} so'm qo'shildi!")
    await state.clear()
