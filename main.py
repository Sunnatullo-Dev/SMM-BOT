import asyncio
import contextlib
import logging
import os

import runtime_bootstrap
from fastapi import FastAPI

from bot import configure_logging, create_bot, create_dispatcher, run_bot_polling
from config import validate_runtime_config
from web_app_api import app


def get_app() -> FastAPI:
    return app


app = get_app()


@app.on_event("startup")
async def combined_service_startup() -> None:
    config_errors = validate_runtime_config()
    if config_errors:
        raise RuntimeError("Config xatolari: " + "; ".join(config_errors))

    if getattr(app.state, "bot_polling_task", None):
        return

    configure_logging()
    bot = create_bot()
    dispatcher = create_dispatcher()

    app.state.bot_instance = bot
    app.state.dispatcher = dispatcher
    app.state.bot_polling_task = asyncio.create_task(
        run_bot_polling(
            bot=bot,
            dp=dispatcher,
            handle_signals=False,
            close_bot_session=False,
        )
    )
    logging.info("Combined web+bot service startup completed")


@app.on_event("shutdown")
async def combined_service_shutdown() -> None:
    polling_task = getattr(app.state, "bot_polling_task", None)
    dispatcher = getattr(app.state, "dispatcher", None)
    bot = getattr(app.state, "bot_instance", None)

    if dispatcher is not None:
        with contextlib.suppress(RuntimeError):
            await dispatcher.stop_polling()

    if polling_task is not None:
        try:
            await asyncio.wait_for(polling_task, timeout=15)
        except asyncio.TimeoutError:
            polling_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await polling_task
        except asyncio.CancelledError:
            pass

    if bot is not None:
        await bot.session.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
