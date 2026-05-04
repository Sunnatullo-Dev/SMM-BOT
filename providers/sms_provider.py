from typing import Any

from providers.base import BaseProvider
from providers.exceptions import ProviderResponseError


class SMSProvider(BaseProvider):
    def __init__(self, api_key: str, api_url: str, timeout_seconds: int = 20):
        normalized_url = str(api_url or "").strip().rstrip("/")
        super().__init__("SMS provider", api_key, normalized_url, timeout_seconds)

    def _params(self, action: str, **extra: Any) -> dict[str, Any]:
        params = {"key": self.api_key, "action": action}
        params.update(extra)
        return params

    @staticmethod
    def _coerce_country_count(value: Any) -> int:
        try:
            return max(1, int(float(value or 0)))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _coerce_country_price(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _normalize_countries_payload(cls, payload: Any) -> dict[str, Any]:
        if not payload or not isinstance(payload, (dict, list)):
            return {}
        if isinstance(payload, dict) and "error" in payload:
            return {}

        source = payload
        if isinstance(payload, dict) and isinstance(payload.get("countries"), (dict, list)):
            source = payload["countries"]
        elif isinstance(payload, dict) and isinstance(payload.get("data"), (dict, list)):
            source = payload["data"]

        normalized: dict[str, Any] = {}
        if isinstance(source, dict):
            items = source.items()
        else:
            items = []
            for item in source:
                if isinstance(item, dict):
                    item_code = item.get("code") or item.get("country_code") or item.get("id") or item.get("name")
                    items.append((item_code, item))

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

    async def get_countries(self, service: str = "tg") -> dict[str, Any]:
        payload = await self._get_json(self._params("countries"))
        countries = self._normalize_countries_payload(payload)
        if not countries:
            raise ProviderResponseError("SMS countries response must contain at least one country.")
        return countries

    async def buy_number(self, service: str, country: str) -> dict[str, Any]:
        payload = await self._get_json(self._params("getnum", code=str(country or "").strip().upper()))
        if not isinstance(payload, dict):
            raise ProviderResponseError("SMS buy_number response must be a JSON object.")
        if str(payload.get("status", "")).lower() != "ok":
            raise ProviderResponseError(f"SMS buy_number failed: {payload.get('error') or payload}")
        return payload

    async def get_balance(self) -> dict[str, Any]:
        payload = await self._get_json(self._params("balance"))
        if not isinstance(payload, dict) or "balance" not in payload:
            raise ProviderResponseError(f"SMS balance response is invalid: {payload}")
        return {
            "balance": payload.get("balance"),
            "currency": str(payload.get("currency", "UZS") or "UZS").upper(),
        }

    async def get_status(self, order_id: str) -> dict[str, Any]:
        payload = await self._get_json(self._params("getsms", hash=str(order_id or "").strip()))
        if not isinstance(payload, dict):
            raise ProviderResponseError("SMS status response must be a JSON object.")
        return payload
