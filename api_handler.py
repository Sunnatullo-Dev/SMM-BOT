import logging
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import aiohttp
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

logger = logging.getLogger(__name__)

SMMWIZ_API_KEY = os.getenv("SMMWIZ_API_KEY") or os.getenv("SMM_API_KEY", "")
SMMWIZ_API_URL = os.getenv("SMMWIZ_API_URL") or os.getenv("SMM_API_URL", "https://locksmm.com/api/v2")
MARKUP_PERCENT = Decimal("25")
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


def _apply_markup(rate_value: Any) -> str:
    try:
        rate_decimal = Decimal(str(rate_value))
    except (InvalidOperation, TypeError, ValueError):
        return str(rate_value)

    final_rate = rate_decimal + (rate_decimal * MARKUP_PERCENT / Decimal("100"))
    normalized = final_rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return format(normalized.normalize(), "f")


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_api_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw
    path = (parsed.path or "").strip()
    if path in {"", "/"}:
        parsed = parsed._replace(path="/api/v2")
        return urlunparse(parsed)
    return raw


def _resolve_credentials(api_key: str | None = None, api_url: str | None = None) -> tuple[str, str]:
    resolved_key = (api_key or SMMWIZ_API_KEY or "").strip()
    resolved_url = _normalize_api_url(api_url or SMMWIZ_API_URL or "")
    return resolved_key, resolved_url


async def _request(
    action: str,
    *,
    api_key: str | None = None,
    api_url: str | None = None,
    **params: Any,
) -> dict[str, Any] | list[dict[str, Any]]:
    resolved_key, resolved_url = _resolve_credentials(api_key=api_key, api_url=api_url)

    if not resolved_key:
        error_message = "SMMWIZ_API_KEY is not configured in .env"
        logger.error(error_message)
        return {"error": error_message}

    if not resolved_url:
        error_message = "SMMWIZ_API_URL is not configured in .env"
        logger.error(error_message)
        return {"error": error_message}

    payload = {"key": resolved_key, "action": action}
    payload.update(params)

    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.get(resolved_url, params=payload) as response:
                if response.status != 200:
                    error_message = f"Smmwiz API HTTP error: {response.status}"
                    logger.error(error_message)
                    return {"error": error_message}
                return await response.json(content_type=None)
    except aiohttp.ClientError as exc:
        logger.exception("Smmwiz API client error during %s", action, exc_info=exc)
        return {"error": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive safety for bot runtime
        logger.exception("Unexpected Smmwiz API error during %s", action, exc_info=exc)
        return {"error": str(exc)}


async def get_balance(api_key: str | None = None, api_url: str | None = None) -> dict[str, Any]:
    try:
        result = await _request("balance", api_key=api_key, api_url=api_url)
        if isinstance(result, dict) and "balance" in result:
            return {
                "balance": result.get("balance"),
                "currency": result.get("currency", "USD"),
            }
        return {"error": "Invalid balance response", "raw": result}
    except Exception as exc:  # pragma: no cover - outer safety for caller stability
        logger.exception("get_balance failed", exc_info=exc)
        return {"error": str(exc)}


async def get_services(
    api_key: str | None = None,
    api_url: str | None = None,
    apply_markup: bool = True,
) -> list[dict[str, Any]] | dict[str, Any]:
    try:
        result = await _request("services", api_key=api_key, api_url=api_url)
        if not isinstance(result, list):
            return {"error": "Invalid services response", "raw": result}

        if not apply_markup:
            return result

        services_with_markup: list[dict[str, Any]] = []
        for service in result:
            if not isinstance(service, dict):
                continue
            service_copy = dict(service)
            original_rate = service_copy.get("rate", "0")
            service_copy["original_rate"] = str(original_rate)
            service_copy["rate"] = _apply_markup(original_rate)
            service_copy["markup_percent"] = int(MARKUP_PERCENT)
            services_with_markup.append(service_copy)
        return services_with_markup
    except Exception as exc:  # pragma: no cover - outer safety for caller stability
        logger.exception("get_services failed", exc_info=exc)
        return {"error": str(exc)}


async def create_order(
    service_id: str | int,
    link: str,
    quantity: int,
    api_key: str | None = None,
    api_url: str | None = None,
) -> dict[str, Any]:
    try:
        if not str(service_id).strip():
            return {"error": "service_id is required"}
        if not isinstance(quantity, int) or quantity <= 0:
            return {"error": "quantity must be a positive integer"}
        if not _is_http_url(link):
            return {"error": "link must start with http:// or https://"}
        result = await _request(
            "add",
            service=service_id,
            link=link,
            quantity=quantity,
            api_key=api_key,
            api_url=api_url,
        )
        if isinstance(result, dict):
            return result
        return {"error": "Invalid order response", "raw": result}
    except Exception as exc:  # pragma: no cover - outer safety for caller stability
        logger.exception("create_order failed", exc_info=exc)
        return {"error": str(exc)}


async def get_status(
    order_id: str | int,
    api_key: str | None = None,
    api_url: str | None = None,
) -> dict[str, Any]:
    try:
        if not str(order_id).strip():
            return {"error": "order_id is required"}
        result = await _request("status", order=order_id, api_key=api_key, api_url=api_url)
        if isinstance(result, dict):
            return result
        return {"error": "Invalid status response", "raw": result}
    except Exception as exc:  # pragma: no cover - outer safety for caller stability
        logger.exception("get_status failed", exc_info=exc)
        return {"error": str(exc)}
