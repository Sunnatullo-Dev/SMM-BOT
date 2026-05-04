import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, CallbackQuery

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, delay: float = 0.5):
        self.users = {}
        self.delay = delay
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = None
        if isinstance(event, (Message, CallbackQuery)):
            user_id = event.from_user.id
            if isinstance(event, CallbackQuery) and str(event.data or "").startswith("force_sub_check"):
                return await handler(event, data)

        if user_id:
            now = time.time()
            if user_id in self.users:
                last_time = self.users[user_id]
                if now - last_time < self.delay:
                    if isinstance(event, CallbackQuery):
                        await event.answer("⚠️ Iltimos, biroz kuting...", show_alert=False)
                    return
            self.users[user_id] = now
            
            # Tozalash (xotira to'lib ketmasligi uchun)
            if len(self.users) > 10000:
                self.users.clear()

        return await handler(event, data)
