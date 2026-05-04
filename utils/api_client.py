import logging
import os
import aiohttp
import api_handler
from config import SMM_API_KEY, SMM_API_URL, SMS_API_KEY, SMS_API_URL
from database.models import db

SMM_KEY_PLACEHOLDERS = {"", "your_smm_api_key_here", "YOUR_SMM_PANEL_API_KEY"}
SMMWIZ_ENV_KEY = os.getenv("SMMWIZ_API_KEY", "").strip()
SMMWIZ_ENV_URL = (os.getenv("SMMWIZ_API_URL") or "https://smmwiz.com/api/v2").strip()
LEGACY_SMM_URL = "https://locksmm.com/api/v2"
SMS_URL_PLACEHOLDERS = {
    "",
    "https://api.sms-activate.org/stubs/handler_api.php",
    "https://locksmm.com",
    "https://locksmm.com/",
}
LOCKSMM_SMS_ENV_URL = (os.getenv("LOCKSMM_SMS_API_URL") or os.getenv("SMS_API_URL") or "https://locksmm.uz").strip()

class SMMClient:
    def __init__(self, api_key, api_url):
        self.default_api_key = api_key
        self.default_api_url = api_url
        self.timeout = aiohttp.ClientTimeout(total=30)

    async def _get_credentials(self):
        api_key = await db.get_setting("smm_api_key", self.default_api_key)
        api_url = await db.get_setting("smm_api_url", self.default_api_url)
        api_key = (api_key or "").strip()
        api_url = (api_url or "").strip()

        if api_key in SMM_KEY_PLACEHOLDERS and SMMWIZ_ENV_KEY:
            api_key = SMMWIZ_ENV_KEY
            if not api_url or api_url == LEGACY_SMM_URL:
                api_url = SMMWIZ_ENV_URL

        return api_key, api_url

    async def get_services(self, apply_markup=False):
        api_key, api_url = await self._get_credentials()
        return await api_handler.get_services(
            api_key=api_key,
            api_url=api_url,
            apply_markup=apply_markup,
        )

    async def add_order(self, service_id, link, quantity):
        api_key, api_url = await self._get_credentials()
        result = await api_handler.create_order(
            service_id=service_id,
            link=link,
            quantity=quantity,
            api_key=api_key,
            api_url=api_url,
        )
        if isinstance(result, dict) and "order" in result:
            return result["order"]
        return None

    async def check_status(self, order_id):
        api_key, api_url = await self._get_credentials()
        result = await api_handler.get_status(
            order_id=order_id,
            api_key=api_key,
            api_url=api_url,
        )
        if isinstance(result, dict) and "status" in result:
            return result["status"]
        return "Unknown"

    async def get_balance(self):
        api_key, api_url = await self._get_credentials()
        result = await api_handler.get_balance(api_key=api_key, api_url=api_url)
        if isinstance(result, dict) and "balance" in result:
            try:
                balance = float(result["balance"])
            except (TypeError, ValueError):
                balance = 0.0
            return {"balance": balance, "currency": result.get("currency", "USD")}
        return {"balance": 0.0, "currency": "USD"}

class SMSClient:
    def __init__(self, api_key, api_url):
        self.default_api_key = api_key
        self.default_api_url = api_url
        self.timeout = aiohttp.ClientTimeout(total=30)

    @staticmethod
    def _normalize_api_url(value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        return raw.rstrip("/")

    async def _get_credentials(self):
        api_key = await db.get_setting("sms_api_key", self.default_api_key)
        api_url = await db.get_setting("sms_api_url", self.default_api_url)
        api_key = (api_key or "").strip()
        api_url = self._normalize_api_url(api_url or self.default_api_url)
        if api_url in SMS_URL_PLACEHOLDERS:
            api_url = self._normalize_api_url(LOCKSMM_SMS_ENV_URL)
        return api_key, api_url

    async def _request_json(self, action, **kwargs):
        api_key, api_url = await self._get_credentials()
        params = {"key": api_key, "action": action}
        params.update(kwargs)

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(api_url, params=params) as response:
                    return await response.json(content_type=None)
        except Exception as e:
            logging.error(f"SMS API Exception: {e}")
            return {"error": str(e)}

    @staticmethod
    def _coerce_country_count(value):
        try:
            return max(1, int(float(value or 0)))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _coerce_country_price(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _normalize_countries_payload(cls, payload):
        if not payload:
            return {}
        if isinstance(payload, dict) and "error" in payload:
            return {}

        source = payload
        if isinstance(payload, dict) and isinstance(payload.get("countries"), (dict, list)):
            source = payload["countries"]
        elif isinstance(payload, dict) and isinstance(payload.get("data"), (dict, list)):
            source = payload["data"]

        normalized = {}
        if isinstance(source, dict):
            items = source.items()
        elif isinstance(source, list):
            items = []
            for item in source:
                if isinstance(item, dict):
                    item_code = item.get("code") or item.get("country_code") or item.get("id") or item.get("name")
                    items.append((item_code, item))
        else:
            return {}

        for raw_code, raw_info in items:
            if not raw_code or not isinstance(raw_info, (dict, int, float, str)):
                continue
            if isinstance(raw_info, dict):
                code = str(raw_info.get("code") or raw_info.get("country_code") or raw_code).strip().upper()
                name = str(raw_info.get("country") or raw_info.get("name") or code).strip()
                price = cls._coerce_country_price(raw_info.get("price"))
                count = cls._coerce_country_count(
                    raw_info.get("count", raw_info.get("qty", raw_info.get("available", 1)))
                )
            else:
                code = str(raw_code).strip().upper()
                name = code
                price = cls._coerce_country_price(raw_info)
                count = 1
            if not code:
                continue
            normalized[code] = {
                "code": code,
                "name": name,
                "price": price,
                "count": count,
            }
        return normalized

    async def get_countries(self, service="tg"):
        payload = await self._request_json(action="countries", service=service)
        countries = self._normalize_countries_payload(payload)
        if countries:
            return countries
        return {}

    async def buy_number(self, service, country, price=None):
        params = {"code": str(country or "").strip().upper()}
        if price:
            params["price"] = price
        payload = await self._request_json("getnum", **params)
        if not isinstance(payload, dict):
            return {"error": "Provider noto'g'ri javob qaytardi"}
        return payload

    async def check_sms(self, order_id):
        payload = await self._request_json("getsms", hash=str(order_id or "").strip())
        if not isinstance(payload, dict):
            return {"error": "Provider noto'g'ri javob qaytardi"}
        return payload

    async def get_balance(self):
        """SMS API balansini olish"""
        response = await self._request_json("balance")
        if isinstance(response, dict) and "balance" in response:
            try:
                balance = float(response.get("balance", 0) or 0)
                return {"balance": balance, "currency": str(response.get("currency", "UZS") or "UZS").upper()}
            except (TypeError, ValueError):
                pass
        return {"balance": 0.0, "currency": "UZS"}

    async def set_status(self, order_id, status):
        return {"error": "Locksmm SMS API set_status qo'llab-quvvatlanmaydi", "hash": order_id, "status": status}

smm_client = SMMClient(SMM_API_KEY, SMM_API_URL)
sms_client = SMSClient(SMS_API_KEY, SMS_API_URL)
