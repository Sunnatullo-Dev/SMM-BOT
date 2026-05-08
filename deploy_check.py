import asyncio
import sys

import httpx

import bot
import main
import web_app_api
from config import DB_NAME, WEB_APP_ALLOWED_ORIGINS, validate_runtime_config
from database.models import db, init_db


async def main() -> int:
    errors = validate_runtime_config()
    if errors:
        print("CONFIG_ERROR:", "; ".join(errors))
        return 1

    await init_db()

    async with db.connect() as conn:
        async with conn.execute("PRAGMA journal_mode") as cursor:
            journal_mode = (await cursor.fetchone())[0]
        async with conn.execute("PRAGMA busy_timeout") as cursor:
            busy_timeout = (await cursor.fetchone())[0]

    transport = httpx.ASGITransport(app=web_app_api.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/healthz")

    print("IMPORTS: ok")
    print(f"DB_PATH: {DB_NAME}")
    print(f"SQLITE_JOURNAL_MODE: {journal_mode}")
    print(f"SQLITE_BUSY_TIMEOUT: {busy_timeout}")
    print(f"HEALTHZ: {response.status_code} {response.text}")
    print(f"BOT_MODULE: {bot.__name__}")
    print(f"MAIN_MODULE: {main.__name__}")

    if not WEB_APP_ALLOWED_ORIGINS:
        print("WARNING: WEB_APP_ALLOWED_ORIGINS is empty")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
