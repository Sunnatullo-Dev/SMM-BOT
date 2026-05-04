from html import escape

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import db
from keyboards.navigation import user_flow_keyboard
from states.bot_states import OrderSMM
from utils.service_catalog import is_instagram_link

router = Router()


def platform_keyboard(platforms, include_bonus_button=True):
    builder = InlineKeyboardBuilder()
    for platform in platforms:
        builder.row(
            types.InlineKeyboardButton(
                text=f"{platform['platform_emoji']} {platform['platform_label']}",
                callback_data=f"smm_pf_{platform['platform_key']}",
            )
        )
    if include_bonus_button:
        builder.row(types.InlineKeyboardButton(text="💎 Bonuslar", callback_data="smm_bonus"))
    builder.row(types.InlineKeyboardButton(text="🏠 Asosiy sahifa", callback_data="user_main"))
    return builder.as_markup()


def groups_keyboard(platform_key, groups):
    builder = InlineKeyboardBuilder()
    for group in groups:
        builder.row(
            types.InlineKeyboardButton(
                text=f"{group['group_emoji']} {group['group_label']} ({group['service_count']})",
                callback_data=f"smm_grp_{group['group_key']}",
            )
        )
    builder.row(
        types.InlineKeyboardButton(text="🔙 Orqaga", callback_data="smm_main"),
        types.InlineKeyboardButton(text="🏠 Asosiy sahifa", callback_data="user_main"),
    )
    return builder.as_markup()


def services_keyboard(services, back_callback):
    builder = InlineKeyboardBuilder()
    for service in services[:30]:
        label = f"{service['name']} | {service['price_per_1000']:,.0f} so'm"
        builder.row(
            types.InlineKeyboardButton(
                text=label[:64],
                callback_data=f"smm_svc_{service['service_id']}",
            )
        )
    builder.row(
        types.InlineKeyboardButton(text="🔙 Orqaga", callback_data=back_callback),
        types.InlineKeyboardButton(text="🏠 Asosiy sahifa", callback_data="user_main"),
    )
    return builder.as_markup()


async def render_smm_main(target):
    platforms = await db.get_smm_platforms(active_only=True, include_bonus=False)
    if not platforms:
        text = "❌ Hozircha nakrutka xizmatlari yuklanmagan. Admin xizmatlarni sinxron qilishi kerak."
        return await _send_or_edit(target, text, user_flow_keyboard())

    text = (
        "⚡️ <b>TEZKOR NAKRUTKA</b>\n\n"
        "✨ <i>Ijtimoiy tarmoqlaringizni yangi bosqichga olib chiqing.</i>\n\n"
        "📌 <b>Katalog haqida:</b>\n"
        "• Xizmatlar Locksmm API orqali amalga oshiriladi\n"
        "• Narxlar real vaqtda so'mda ko'rsatiladi\n"
        "• Buyurtmalar 24/7 rejimida qabul qilinadi\n\n"
        "👇 <b>Platformani tanlang:</b>"
    )
    await _send_or_edit(target, text, platform_keyboard(platforms))


async def render_group_list(target, platform_key):
    groups = await db.get_smm_groups(platform=platform_key, active_only=True)
    if not groups:
        return await _send_or_edit(target, "❌ Bu platforma uchun aktiv guruh topilmadi.", user_flow_keyboard())

    platform_title = groups[0]["platform_key"].capitalize()
    text = (
        f"📂 <b>{platform_title} xizmatlari</b>\n\n"
        "💎 <i>Eng sifatli va tezkor xizmatlar to'plami.</i>\n\n"
        "👇 <b>Kategoriyani tanlang:</b>"
    )
    if platform_key == "instagram":
        text = (
            f"📂 <b>{platform_title} xizmatlari</b>\n\n"
            "📸 <i>API ichidan faqat Instagram xizmatlari ajratib ko'rsatilmoqda.</i>\n\n"
            "👇 <b>Kerakli bo'limni tanlang:</b>"
        )
    await _send_or_edit(target, text, groups_keyboard(platform_key, groups))


async def render_service_list(target, group_key, title):
    services = await db.get_smm_services(group_key=group_key, active_only=True)
    if not services:
        return await _send_or_edit(target, "❌ Bu bo'limda aktiv xizmat yo'q.", user_flow_keyboard())

    back_callback = "smm_bonus" if services[0]["platform_key"] == "bonus" else f"smm_pf_{services[0]['platform_key']}"
    text = (
        f"🧩 <b>{title}</b>\n\n"
        "✅ <i>Barcha xizmatlar tekshirilgan va barqaror.</i>\n\n"
        "👇 <b>Xizmatni tanlang:</b>"
    )
    await _send_or_edit(target, text, services_keyboard(services, back_callback))


async def render_bonus_list(target):
    groups = await db.get_smm_groups(platform="bonus", active_only=True)
    if not groups:
        return await _send_or_edit(target, "💎 Hozircha bonus xizmatlar topilmadi.", user_flow_keyboard())
    await render_service_list(target, groups[0]["group_key"], "Bonus xizmatlar")


async def _send_or_edit(target, text, reply_markup):
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=reply_markup)
    else:
        await target.answer(text, reply_markup=reply_markup)


@router.message(F.text == "⚡️ Tezkor Nakrutka")
async def smm_start_handler(message: types.Message, state: FSMContext):
    from handlers.services_handlers import send_services_menu

    await state.clear()
    await send_services_menu(message)


@router.message(F.text == "💎 Bonuslar")
async def bonus_start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(OrderSMM.choosing_service)
    await render_bonus_list(message)


@router.callback_query(F.data == "smm_main")
async def smm_main_callback(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(OrderSMM.choosing_platform)
    await render_smm_main(call)
    await call.answer()


@router.callback_query(F.data == "smm_bonus")
async def smm_bonus_callback(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(OrderSMM.choosing_service)
    await render_bonus_list(call)
    await call.answer()


@router.callback_query(F.data.startswith("smm_pf_"))
async def smm_platform_handler(call: types.CallbackQuery, state: FSMContext):
    platform_key = call.data.split("_", 2)[2]
    await state.update_data(platform_key=platform_key)
    await state.set_state(OrderSMM.choosing_group)
    await render_group_list(call, platform_key)
    await call.answer()


@router.callback_query(F.data.startswith("smm_grp_"))
async def smm_group_handler(call: types.CallbackQuery, state: FSMContext):
    group_key = call.data.split("_", 2)[2]
    services = await db.get_smm_services(group_key=group_key, active_only=True)
    if not services:
        await call.answer("Bu guruhda aktiv xizmat yo'q.", show_alert=True)
        return

    title = services[0]["group_label"]
    await state.update_data(group_key=group_key)
    await state.set_state(OrderSMM.choosing_service)
    await render_service_list(call, group_key, title)
    await call.answer()


@router.callback_query(F.data.startswith("smm_svc_"))
async def smm_service_handler(call: types.CallbackQuery, state: FSMContext):
    service_id = call.data.split("_", 2)[2]
    service = await db.get_smm_service(service_id, active_only=True)
    if not service:
        await call.answer("Xizmat topilmadi yoki yashirilgan.", show_alert=True)
        return

    min_order = int(service["min_order"] or 0)
    max_order = int(service["max_order"] or 0)
    await state.update_data(
        service_id=service["service_id"],
        service_name=service["name"],
        platform_key=service["platform_key"],
        group_key=service["group_key"],
        final_price_per_1000=int(service["price_per_1000"]),
        price_per_1000=int(service["price_per_1000"]),
        min_order=min_order,
        max_order=max_order,
    )
    await state.set_state(OrderSMM.entering_link)

    text = (
        f"💎 <b>{escape(service['name'])}</b>\n\n"
        f"💳 Yakuniy narx: <b>{service['price_per_1000']:,.0f}</b> so'm / 1000\n"
        f"📉 Min: <b>{min_order:,}</b>\n"
        f"📈 Max: <b>{max_order:,}</b>\n\n"
        "🔗 <b>Buyurtma uchun link (havola) yuboring:</b>"
    )
    if service["platform_key"] == "instagram":
        text += "\n\nFaqat <code>instagram.com</code> havolalari qabul qilinadi."
    await call.message.edit_text(
        text,
        reply_markup=user_flow_keyboard(
            back_callback=f"smm_grp_{service['group_key']}",
            back_text="🔙 Xizmatlarga qaytish",
            include_cancel=True,
        ),
    )
    await call.answer()


@router.message(OrderSMM.entering_link)
async def smm_link_handler(message: types.Message, state: FSMContext):
    link = (message.text or "").strip()
    data = await state.get_data()
    back_callback = f"smm_grp_{data.get('group_key', '')}" if data.get("group_key") else None
    if not link.startswith("http"):
        return await message.answer(
            "⚠️ To'g'ri link yuboring. Link `http` yoki `https` bilan boshlansin.",
            reply_markup=user_flow_keyboard(
                back_callback=back_callback,
                back_text="🔙 Xizmatlarga qaytish",
                include_cancel=True,
            ),
        )

    if data.get("platform_key") == "instagram" and not is_instagram_link(link):
        return await message.answer(
            "Instagram xizmati uchun havola `instagram.com` domeniga tegishli bo'lishi kerak.",
            reply_markup=user_flow_keyboard(
                back_callback=back_callback,
                back_text="🔙 Xizmatlarga qaytish",
                include_cancel=True,
            ),
        )

    min_order = int(data.get("min_order", 100) or 100)
    max_order = int(data.get("max_order", 50000) or 50000)

    await state.update_data(link=link)
    await state.set_state(OrderSMM.entering_quantity)
    await message.answer(
        "🔢 Miqdorni yuboring.\n\n"
        f"Min: <b>{min_order:,}</b>\n"
        f"Max: <b>{max_order:,}</b>",
        reply_markup=user_flow_keyboard(
            back_callback=back_callback,
            back_text="🔙 Xizmatlarga qaytish",
            include_cancel=True,
        ),
    )
