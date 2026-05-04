import logging
from html import escape
from typing import Any, Awaitable, Callable, Dict
from urllib.parse import urlparse

from aiogram import BaseMiddleware, types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_LIST
from database.models import db

CHECK_SUB_CALLBACK = "force_sub_check"


def _extract_referrer_id_from_start_text(text: str) -> int:
    parts = str(text or "").split()
    if len(parts) > 1 and parts[1].isdigit():
        return int(parts[1])
    return 0


def _build_check_callback(referrer_id: int = 0) -> str:
    referrer_id = int(referrer_id or 0)
    return f"{CHECK_SUB_CALLBACK}:{referrer_id}" if referrer_id > 0 else CHECK_SUB_CALLBACK


def _parse_check_callback(data: str) -> int:
    raw = str(data or "").strip()
    if raw == CHECK_SUB_CALLBACK:
        return 0
    prefix = f"{CHECK_SUB_CALLBACK}:"
    if raw.startswith(prefix):
        tail = raw[len(prefix) :].strip()
        if tail.isdigit():
            return int(tail)
    return 0


def _parse_required_channels(raw_value: str) -> list[dict]:
    channels = []
    for raw_line in str(raw_value or "").splitlines():
        entry = raw_line.strip()
        if not entry:
            continue

        url = None
        chat_id = None
        label = entry

        if entry.startswith(("https://", "http://")):
            parsed = urlparse(entry)
            if parsed.netloc.lower().endswith("t.me"):
                slug = parsed.path.strip("/").split("/", 1)[0].strip()
                if slug and not slug.startswith("+") and slug != "joinchat":
                    chat_id = f"@{slug.lstrip('@')}"
                    url = f"https://t.me/{slug.lstrip('@')}"
                    label = f"@{slug.lstrip('@')}"
                else:
                    url = entry
            else:
                url = entry
        elif entry.startswith("t.me/"):
            slug = entry[5:].strip("/").split("/", 1)[0].strip()
            if slug and not slug.startswith("+") and slug != "joinchat":
                chat_id = f"@{slug.lstrip('@')}"
                url = f"https://t.me/{slug.lstrip('@')}"
                label = f"@{slug.lstrip('@')}"
            else:
                url = f"https://{entry}"
        elif entry.startswith("@"):
            slug = entry.lstrip("@")
            if slug:
                chat_id = f"@{slug}"
                url = f"https://t.me/{slug}"
                label = f"@{slug}"
        elif entry.lstrip("-").isdigit():
            chat_id = int(entry)
            label = entry
        else:
            slug = entry.strip("/")
            if slug:
                chat_id = f"@{slug.lstrip('@')}"
                url = f"https://t.me/{slug.lstrip('@')}"
                label = f"@{slug.lstrip('@')}"

        channels.append(
            {
                "raw": entry,
                "label": label,
                "url": url,
                "chat_id": chat_id,
                "checkable": chat_id is not None,
            }
        )
    return channels


async def _is_member(bot, chat_id, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception as exc:
        logging.warning("Required channel check failed for %s: %s", chat_id, exc)
        return False

    status = getattr(member, "status", "")
    if status in {"creator", "administrator", "member"}:
        return True
    if status == "restricted" and getattr(member, "is_member", False):
        return True
    return False


async def _get_missing_channels(bot, user_id: int) -> list[dict]:
    raw_channels = await db.get_setting("required_channels", "")
    channels = _parse_required_channels(raw_channels)
    if not channels:
        return []

    missing = []
    for channel in channels:
        if not channel["checkable"]:
            continue
        if not await _is_member(bot, channel["chat_id"], user_id):
            missing.append(channel)
    return missing


def _required_channels_keyboard(missing_channels: list[dict], referrer_id: int = 0):
    builder = InlineKeyboardBuilder()
    for channel in missing_channels:
        url = channel.get("url")
        if not url:
            continue
        builder.row(
            types.InlineKeyboardButton(
                text=f"📢 {channel['label']}",
                url=url,
            )
        )
    builder.row(
        types.InlineKeyboardButton(
            text="✅ Tekshirish",
            callback_data=_build_check_callback(referrer_id),
        )
    )
    return builder.as_markup()


def _required_channels_text(missing_channels: list[dict]) -> str:
    lines = [
        "📢 <b>Majburiy obuna</b>",
        "",
        "Botdan foydalanishdan oldin quyidagi kanallarga obuna bo'ling:",
        "",
    ]
    for channel in missing_channels:
        lines.append(f"• <code>{escape(channel['label'])}</code>")
    lines.extend(
        [
            "",
            "Obuna bo'lgach, pastdagi <b>✅ Tekshirish</b> tugmasini bosing.",
        ]
    )
    return "\n".join(lines)


async def _send_subscription_prompt(
    event: types.Message | types.CallbackQuery,
    missing_channels: list[dict],
    referrer_id: int = 0,
):
    text = _required_channels_text(missing_channels)
    markup = _required_channels_keyboard(missing_channels, referrer_id)

    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=markup)
        return

    await event.answer("Avval majburiy kanallarga obuna bo'ling.", show_alert=True)
    try:
        await event.message.edit_text(text, reply_markup=markup)
    except Exception:
        await event.message.answer(text, reply_markup=markup)


async def _handle_successful_subscription(event: types.CallbackQuery, referrer_id: int):
    from handlers.start_handlers import send_start_screen

    await event.answer("Obuna tasdiqlandi.")
    try:
        await event.message.edit_text(
            "✅ Siz kanallarga obuna bo'ldingiz.\n\nEndi hohlagan tugmani tanlang.",
            reply_markup=None,
        )
    except Exception:
        pass
    await send_start_screen(event.message, referrer_id=referrer_id, actor=event.from_user)


class CheckStatusMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, (types.Message, types.CallbackQuery)):
            user_id = event.from_user.id

            if user_id not in ADMIN_LIST:
                bot_status = await db.get_setting("bot_status", "active")
                if str(bot_status).strip().lower() != "active":
                    text = "🤖 Bot vaqtincha texnik rejimda. Keyinroq qayta urinib ko'ring."
                    if isinstance(event, types.Message):
                        await event.answer(text)
                    else:
                        await event.answer(text, show_alert=True)
                    return

            user = await db.get_user(user_id)
            if user:
                try:
                    is_blocked = user["is_blocked"]
                except Exception:
                    is_blocked = 0

                if is_blocked == 1:
                    text = "🚫 Sizning hisobingiz admin tomonidan bloklangan. Murojaat uchun: @ProSMMBOT_admin"
                    if isinstance(event, types.Message):
                        await event.answer(text)
                    else:
                        await event.answer(text, show_alert=True)
                    return

            if user_id not in ADMIN_LIST:
                missing_channels = await _get_missing_channels(event.bot, user_id)

                if isinstance(event, types.CallbackQuery) and str(event.data or "").startswith(CHECK_SUB_CALLBACK):
                    referrer_id = _parse_check_callback(event.data)
                    if missing_channels:
                        await _send_subscription_prompt(event, missing_channels, referrer_id)
                        return
                    await _handle_successful_subscription(event, referrer_id)
                    return

                if missing_channels:
                    referrer_id = 0
                    if isinstance(event, types.Message) and (event.text or "").startswith("/start"):
                        referrer_id = _extract_referrer_id_from_start_text(event.text or "")
                    await _send_subscription_prompt(event, missing_channels, referrer_id)
                    return

        return await handler(event, data)
