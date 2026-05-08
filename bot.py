import asyncio
import contextlib
import logging

import runtime_bootstrap

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config import ADMINS, BOT_TOKEN, STARTUP_NOTIFY_RECENT_DAYS, validate_runtime_config
from database.models import db, init_db
from handlers import (
    order_handlers,
    payment_handlers,
    provider_structure_handlers,
    referral,
    services_handlers,
    smm_handlers,
    sms_handlers,
    start_handlers,
    user_handlers,
)
from handlers.admin import admin_router
from middlewares.check_status import CheckStatusMiddleware
from middlewares.throttling import ThrottlingMiddleware
from utils.order_sync import sync_smm_orders


def configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )


def create_bot() -> Bot:
    return Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(start_handlers.router)
    dp.include_router(user_handlers.router)
    dp.include_router(referral.router)
    dp.include_router(provider_structure_handlers.router)
    dp.include_router(services_handlers.router)
    dp.include_router(smm_handlers.router)
    dp.include_router(sms_handlers.router)
    dp.include_router(payment_handlers.router)
    dp.include_router(admin_router)
    dp.include_router(order_handlers.router)

    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())
    dp.message.middleware(CheckStatusMiddleware())
    dp.callback_query.middleware(CheckStatusMiddleware())
    dp.startup.register(on_startup)
    return dp


async def notify_users_on_start(bot: Bot):
    user_ids = await db.get_recent_user_ids(STARTUP_NOTIFY_RECENT_DAYS)
    if not user_ids:
        return

    for user_id in user_ids:
        if user_id in ADMINS:
            continue
        try:
            await bot.send_message(
                user_id,
                "🔔 <b>Bot qayta ishga tushdi!</b>\nBot endi yana ishlamoqda va barcha xizmatlar tayyor.",
            )
        except Exception as exc:
            logging.debug("Foydalanuvchi %s ga xabar yuborib bo'lmadi: %s", user_id, exc)
        await asyncio.sleep(0.1)


async def on_startup(bot: Bot):
    await init_db()

    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, "🚀 <b>Bot muvaffaqiyatli ishga tushdi!</b>")
        except Exception as exc:
            logging.error("Admin %s ga xabar yuborib bo'lmadi: %s", admin_id, exc)

    asyncio.create_task(notify_users_on_start(bot))


async def run_bot_polling(
    *,
    bot: Bot | None = None,
    dp: Dispatcher | None = None,
    handle_signals: bool = True,
    close_bot_session: bool = True,
) -> None:
    bot_instance = bot or create_bot()
    dispatcher = dp or create_dispatcher()
    sync_task = asyncio.create_task(sync_smm_orders(bot_instance))

    try:
        while True:
            try:
                logging.info("Bot polling ishga tushdi")
                await dispatcher.start_polling(
                    bot_instance,
                    handle_signals=handle_signals,
                    close_bot_session=False,
                )
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.error("Polling xatosi: %s", exc)
                await asyncio.sleep(5)
    finally:
        sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sync_task
        if close_bot_session:
            await bot_instance.session.close()


async def main() -> None:
    config_errors = validate_runtime_config()
    if config_errors:
        raise RuntimeError("Config xatolari: " + "; ".join(config_errors))

    configure_logging()
    await run_bot_polling()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi")
