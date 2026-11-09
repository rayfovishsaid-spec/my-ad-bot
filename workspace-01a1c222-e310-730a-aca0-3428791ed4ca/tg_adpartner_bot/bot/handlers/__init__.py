from aiogram import Router
from bot.handlers import admin, advertiser, earn, partners, payments, start


def setup_routers() -> Router:
    root = Router()
    root.include_router(admin.router)
    root.include_router(payments.router)
    root.include_router(start.router)
    root.include_router(earn.router)
    root.include_router(advertiser.router)
    root.include_router(partners.router)
    return root
