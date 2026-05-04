from aiogram import Router
from .base import router as base_router
from .users import router as users_router
from .orders import router as orders_router
from .settings import router as settings_router
from .services import router as services_router
from .payments import router as payments_router
from .misc import router as misc_router

admin_router = Router()
admin_router.include_routers(
    base_router,
    users_router,
    orders_router,
    settings_router,
    services_router,
    payments_router,
    misc_router,
)
