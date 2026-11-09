import asyncio
import logging
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from core import engine
from core.config import get_env_config
from core.database import get_db, now_iso

logger = logging.getLogger("adpartner.workers")


async def unsubscribe_guard_worker(bot: Bot) -> None:
    """Каждые 30 минут проверяет, не отписались ли исполнители раньше срока холда (7 дней)."""
    while True:
        try:
            await asyncio.sleep(1800)
            db = await get_db()
            try:
                cur = await db.execute(
                    """
                    SELECT tc.id, tc.user_id, c.channel_username
                    FROM task_completions tc
                    JOIN campaigns c ON c.id = tc.campaign_id
                    WHERE tc.status = 'paid'
                      AND tc.hold_until IS NOT NULL
                      AND tc.hold_until > ?
                      AND c.channel_username != ''
                      AND c.is_demo = 0
                    LIMIT 100
                    """,
                    (now_iso(),),
                )
                rows = [dict(r) for r in await cur.fetchall()]
            finally:
                await db.close()

            for item in rows:
                try:
                    member = await bot.get_chat_member(
                        chat_id=item["channel_username"], user_id=item["user_id"]
                    )
                    st = member.status.value if hasattr(member.status, "value") else str(member.status)
                    if st in ("left", "kicked"):
                        pen = await engine.penalize_unsubscribed_task(item["id"])
                        if pen:
                            try:
                                await bot.send_message(
                                    pen["user_id"],
                                    f"⚠️ <b>Штраф за раннюю отписку!</b>\n"
                                    f"Вы отписались от канала {pen['channel']} раньше срока холда.\n"
                                    f"С баланса списано <b>-{pen['reward']:.2f} ₽</b>, место возвращено рекламодателю.",
                                )
                            except Exception:
                                pass
                    await asyncio.sleep(0.1)
                except Exception:
                    continue
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Ошибка в unsubscribe_guard_worker: %s", exc)


async def broadcast_queue_worker(bot: Bot) -> None:
    """Каждые 20 секунд проверяет оплаченные авто-рассылки и безопасно доставляет их (20 сообщ/сек)."""
    while True:
        try:
            await asyncio.sleep(20)
            db = await get_db()
            try:
                cur = await db.execute(
                    """
                    SELECT * FROM campaigns
                    WHERE type = 'broadcast' AND status = 'active' AND completed_qty < total_qty AND is_demo = 0
                    ORDER BY id ASC LIMIT 1
                    """
                )
                camp = await cur.fetchone()
                if not camp:
                    continue
                camp_dict = dict(camp)
                rem = int(camp_dict["total_qty"]) - int(camp_dict["completed_qty"])
                ucur = await db.execute(
                    "SELECT tg_id FROM users WHERE is_banned = 0 AND is_demo = 0 LIMIT ?",
                    (rem,),
                )
                targets = [r["tg_id"] for r in await ucur.fetchall()]
            finally:
                await db.close()

            kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔗 Перейти к предложению", url=camp_dict["target_url"])]]
            )
            sent = 0
            for uid in targets:
                try:
                    await bot.send_message(
                        uid,
                        f"🔥 <b>Рекламное предложение</b>\n\n"
                        f"<b>{camp_dict['title']}</b>\n{camp_dict['description']}",
                        reply_markup=kb,
                    )
                    sent += 1
                except Exception:
                    pass
                await asyncio.sleep(0.05)  # Строгий лимит 20 сообщений в секунду

            db = await get_db()
            try:
                new_done = int(camp_dict["completed_qty"]) + max(sent, 1)
                await db.execute(
                    "UPDATE campaigns SET completed_qty = ?, status = 'completed' WHERE id = ?",
                    (min(new_done, int(camp_dict["total_qty"])), camp_dict["id"]),
                )
                await db.commit()
            finally:
                await db.close()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Ошибка в broadcast_queue_worker: %s", exc)


async def public_feed_announcer_worker(bot: Bot) -> None:
    """Автоматически публикует новые задания в открытый канал-витрину для бесплатного притока юзеров."""
    while True:
        try:
            await asyncio.sleep(30)
            env_cfg = get_env_config()
            feed_channel = env_cfg.get("public_feed_channel")
            if not feed_channel:
                continue

            db = await get_db()
            try:
                cur = await db.execute(
                    """
                    SELECT * FROM campaigns
                    WHERE announced_in_feed = 0
                      AND status = 'active'
                      AND type IN ('channel_sub', 'post_view', 'bot_start')
                      AND is_demo = 0
                    ORDER BY id ASC LIMIT 3
                    """
                )
                new_tasks = [dict(r) for r in await cur.fetchall()]
            finally:
                await db.close()

            for t in new_tasks:
                deep_link = f"https://t.me/{env_cfg['bot_username']}?start=task_{t['id']}"
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=f"💰 Забрать +{t['worker_reward']:.2f} ₽ в боте", url=deep_link)]
                    ]
                )
                try:
                    await bot.send_message(
                        feed_channel,
                        f"⚡️ <b>Новое задание #{t['id']}!</b>\n\n"
                        f"📌 <b>{t['title']}</b>\n"
                        f"💵 Оплата за выполнение: <b>+{t['worker_reward']:.2f} ₽</b>\n"
                        f"👥 Свободных мест: <b>{t['total_qty'] - t['completed_qty']}</b>\n\n"
                        f"👇 Жми кнопку ниже и забирай оплату за 15 секунд!",
                        reply_markup=kb,
                    )
                except Exception as exc:
                    logger.warning("Не удалось отправить анонс в витрину %s: %s", feed_channel, exc)

                db = await get_db()
                try:
                    await db.execute("UPDATE campaigns SET announced_in_feed = 1 WHERE id = ?", (t["id"],))
                    await db.commit()
                finally:
                    await db.close()
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Ошибка в public_feed_announcer_worker: %s", exc)
