class SMMProvider:
    def __init__(self, api_key: str, api_url: str):
        self.api_key = api_key
        self.api_url = api_url

    async def get_services(self) -> list[dict]:
        """Return available SMM services.

        This is a placeholder implementation. If no provider API integration
        is available, it returns an empty list.
        """
        return []
