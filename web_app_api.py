import json
import logging
import time
from urllib.parse import parse_qsl

import runtime_bootstrap
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from auth_validator import validate_telegram_data
from config import WEB_APP_ALLOWED_ORIGINS
from database.models import db, init_db
from utils.api_client import smm_client
from utils.service_catalog import calculate_quantity_price_uzs

app = FastAPI(title="SMM Bot Mini App API")
logger = logging.getLogger(__name__)

if WEB_APP_ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=WEB_APP_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


async def get_user_from_auth(init_data: str):
    """
    Validates init_data and returns the user dict.
    Throws HTTPException if invalid.
    """
    if not init_data:
        raise HTTPException(status_code=401, detail="No initData provided")

    if not validate_telegram_data(init_data):
        raise HTTPException(status_code=403, detail="Invalid Telegram auth data")

    try:
        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        user_dict = json.loads(parsed_data["user"])
        return user_dict
    except Exception:
        raise HTTPException(status_code=400, detail="Could not parse user data")


async def get_active_user_from_auth(init_data: str):
    user_info = await get_user_from_auth(init_data)
    user_id = user_info.get("id")
    user = await db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found in bot database")
    if int(user["is_blocked"] or 0) == 1:
        raise HTTPException(status_code=403, detail="User account is blocked")
    return user_info, user


def calculate_smm_price(price_per_1000, quantity):
    return calculate_quantity_price_uzs(price_per_1000, quantity)


@app.on_event("startup")
async def app_startup():
    await init_db()


@app.get("/healthz")
async def healthcheck():
    return {"status": "ok"}


@app.get("/api/user/balance")
async def get_balance(authorization: str = Header(None)):
    """Foydalanuvchi balansini olish"""
    _, user = await get_active_user_from_auth(authorization)

    return {"balance": user["balance"]}


@app.get("/api/smm/services")
async def get_smm_services(authorization: str = Header(None)):
    """SMM xizmatlari ro'yxati"""
    await get_active_user_from_auth(authorization)
    services = await db.get_smm_services(active_only=True)
    return [
        {
            "id": service["service_id"],
            "name": service["name"],
            "price": service["price_per_1000"],
            "final_price_per_1000": service["price_per_1000"],
            "platform": service["platform_label"],
            "group": service["group_label"],
            "category": service["category"].capitalize(),
            "min": service["min_order"],
            "max": service["max_order"],
        }
        for service in services
    ]


@app.post("/api/smm/order")
async def create_smm_order(request: Request, authorization: str = Header(None)):
    """SMM buyurtma berish"""
    user_info, _ = await get_active_user_from_auth(authorization)
    user_id = user_info.get("id")

    try:
        data = await request.json()
    except Exception as exc:
        logger.warning("Invalid mini app JSON payload: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    service_id = data.get("service_id")
    link = data.get("link")
    raw_quantity = data.get("quantity", 100)

    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Quantity must be an integer")

    if not isinstance(link, str) or not link.strip():
        raise HTTPException(status_code=400, detail="Link is required")
    link = link.strip()
    if not link.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Link must start with http:// or https://")

    service = await db.get_smm_service(service_id, active_only=True)
    if not service:
        raise HTTPException(status_code=400, detail="Invalid service ID")

    min_order = int(service["min_order"] or 0)
    max_order = int(service["max_order"] or 0)
    if quantity < min_order or quantity > max_order:
        raise HTTPException(
            status_code=400,
            detail=f"Quantity must be between {min_order} and {max_order}",
        )

    final_price = calculate_smm_price(service["price_per_1000"], quantity)

    balance_spent = await db.spend_balance(
        user_id,
        final_price,
        method="SMM Purchase",
        tx_type="purchase",
        reference=f"miniapp:smm:{service_id}:{quantity}",
    )
    if not balance_spent:
        raise HTTPException(status_code=402, detail="Insufficient balance or balance changed")

    try:
        external_order_id = await smm_client.add_order(
            service_id=service_id,
            link=link,
            quantity=quantity,
        )
    except Exception as exc:
        logger.error("WebApp SMM order failed: %s", exc)
        external_order_id = None

    if not external_order_id:
        await db.refund_balance(
            user_id,
            final_price,
            method="SMM Refund",
            tx_type="refund",
            reference=f"miniapp:smm:{service_id}:{quantity}",
        )
        raise HTTPException(status_code=500, detail="Order could not be sent to provider. Balance refunded.")

    local_order_id = await db.add_order(
        user_id,
        "SMM",
        service["name"],
        link,
        final_price,
        str(external_order_id)
    )

    return {
        "status": "success",
        "order_id": str(external_order_id),
        "local_id": local_order_id,
        "price": final_price,
        "final_price": final_price
    }
