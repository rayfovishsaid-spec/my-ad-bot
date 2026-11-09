from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message, TelegramObject
from core import engine


class UserContextMiddleware(BaseMiddleware):
    """Автоматически регистрирует пользователя и блокирует доступ забаненным аккаунтам."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user = None
        if isinstance(event, Message) and event.from_user:
            tg_user = event.from_user
        elif isinstance(event, CallbackQuery) and event.from_user:
            tg_user = event.from_user

        if tg_user:
            user_row, _ = await engine.ensure_user(
                tg_id=tg_user.id,
                username=tg_user.username or "",
                full_name=tg_user.full_name or "Пользователь",
            )
            if user_row.get("is_banned"):
                if isinstance(event, Message):
                    await event.answer("⛔ Ваш аккаунт заблокирован за нарушение правил платформы.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("⛔ Ваш аккаунт заблокирован.", show_alert=True)
                return None
            data["db_user"] = user_row

        return await handler(event, data)


async def append_native_ad(text: str, user_id: int | None = None) -> str:
    """Автоматически прикрепляет оплаченный рекламный блок внизу сообщения и списывает 1 показ."""
    ad = await engine.pick_native_ad(exclude_user_id=user_id)
    if not ad:
        return text
    ad_block = (
        f"\n\n━━━━━━━━━━━━━━━━━━\n"
        f"💎 <b>Спонсор показа:</b> <a href=\"{ad['target_url']}\">{ad['title']}</a>"
    )
    return text + ad_block


async def verify_telegram_membership(bot: Bot, channel_username: str, user_id: int) -> tuple[bool, str]:
    """Проверяет реальную подписку пользователя на ТГ-канал через Telegram Bot API."""
    if not channel_username:
        return True, "OK"
    try:
        member = await bot.get_chat_member(chat_id=channel_username, user_id=user_id)
        status_val = member.status.value if hasattr(member.status, "value") else str(member.status)
        if status_val in ("member", "administrator", "creator", "restricted"):
            # Если restricted, проверим is_member при наличии
            if status_val == "restricted" and hasattr(member, "is_member") and not member.is_member:
                return False, "Вы ещё не подписались на канал."
            return True, "OK"
        return False, "Подписка не обнаружена. Подпишитесь на канал и нажмите проверку снова!"
    except Exception as exc:
        err_str = str(exc).lower()
        # Если рекламодатель ещё не выдал боту права администратора канала — не блокируем систему
        if "chat not found" in err_str or "member list is inaccessible" in err_str or "forbidden" in err_str:
            return False, (
                "Бот не может проверить подписку: владелец канала должен добавить этого бота "
                "в администраторы канала (достаточно базового права просмотра участников)."
            )
        return False, "Не удалось проверить подписку. Проверьте, что вы подписались на канал."
