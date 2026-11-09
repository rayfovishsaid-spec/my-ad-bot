from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot import keyboards as kb
from bot.middlewares import append_native_ad, verify_telegram_membership
from core import engine
from core.database import get_db

router = Router()


async def _check_and_render_earn_menu(target_msg: Message, user_id: int, edit: bool = False):
    sponsors = await engine.get_mandatory_sponsors(user_id)
    if sponsors:
        text = (
            "🔒 <b>Доступ к платным заданиям почти открыт!</b>\n\n"
            "Для запуска автоматического заработка подпишитесь на каналы наших спонсоров ниже "
            "и нажмите <b>«✅ Проверить подписку»</b>:"
        )
        if edit:
            await target_msg.edit_text(text, reply_markup=kb.sponsor_op_kb(sponsors))
        else:
            await target_msg.answer(text, reply_markup=kb.sponsor_op_kb(sponsors))
        return

    all_tasks = await engine.list_available_tasks(user_id)
    counts = {"channel_sub": 0, "post_view": 0, "bot_start": 0}
    total_sum = 0.0
    for t in all_tasks:
        counts[t["type"]] = counts.get(t["type"], 0) + 1
        total_sum += float(t["worker_reward"])

    text = (
        f"💰 <b>Биржа заданий (Автозаработок)</b>\n\n"
        f"Доступно заданий прямо сейчас: <b>{len(all_tasks)}</b> на сумму <b>{total_sum:.2f} ₽</b>!\n"
        f"Выберите категорию ниже, выполните действие и мгновенно заберите оплату:"
    )
    text = await append_native_ad(text, user_id=user_id)
    if edit:
        await target_msg.edit_text(text, reply_markup=kb.earn_categories_kb(counts), disable_web_page_preview=True)
    else:
        await target_msg.answer(text, reply_markup=kb.earn_categories_kb(counts), disable_web_page_preview=True)


@router.message(F.text == "💰 Заработать")
async def msg_earn_menu(message: Message, state: FSMContext):
    await state.clear()
    await _check_and_render_earn_menu(message, message.from_user.id, edit=False)


@router.callback_query(F.data == "earn:menu")
async def cb_earn_menu(call: CallbackQuery):
    await _check_and_render_earn_menu(call.message, call.from_user.id, edit=True)
    await call.answer()


@router.callback_query(F.data == "op:check")
async def cb_verify_op_sponsors(call: CallbackQuery, bot: Bot):
    sponsors = await engine.get_mandatory_sponsors(call.from_user.id)
    for sp in sponsors:
        # Для реальных каналов проверяем подписку через Telegram Bot API
        if sp.get("channel_username") and not sp.get("is_demo"):
            ok, reason = await verify_telegram_membership(bot, sp["channel_username"], call.from_user.id)
            if not ok:
                await call.answer(f"❌ {sp['title'][:25]}: {reason}", show_alert=True)
                return
        await engine.complete_sponsor_op(call.from_user.id, sp["id"])

    await call.answer("✅ Все подписки подтверждены! Доступ к заданиям открыт.")
    await _check_and_render_earn_menu(call.message, call.from_user.id, edit=True)


@router.callback_query(F.data.startswith("earn:list:"))
async def cb_list_category_task(call: CallbackQuery):
    c_type = call.data.split(":")[2]
    tasks = await engine.list_available_tasks(call.from_user.id, c_type=c_type)
    if not tasks:
        await call.answer("В этой категории пока все задания выполнены! Загляните чуть позже.", show_alert=True)
        await _check_and_render_earn_menu(call.message, call.from_user.id, edit=True)
        return

    t = tasks[0]
    hold_note = "\n🛡 <i>Контроль отписки: 7 дней (не выходите из канала, чтобы сохранить оплату).</i>" if t["type"] == "channel_sub" else ""
    text = (
        f"📌 <b>Задание #{t['id']}: {t['title']}</b>\n\n"
        f"{t['description'] or 'Перейдите по кнопке ниже, выполните условие и нажмите проверку.'}\n\n"
        f"💵 Ваша выплата: <b>+{t['worker_reward']:.2f} ₽</b>\n"
        f"👥 Осталось мест: <b>{t['total_qty'] - t['completed_qty']}</b>"
        f"{hold_note}"
    )
    await call.message.edit_text(text, reply_markup=kb.task_card_kb(t), disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data.startswith("earn:verify:"))
async def cb_verify_task(call: CallbackQuery, bot: Bot):
    camp_id = int(call.data.split(":")[2])
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM campaigns WHERE id = ?", (camp_id,))
        camp = await cur.fetchone()
    finally:
        await db.close()

    if not camp:
        await call.answer("Задание не найдено.", show_alert=True)
        return

    if camp["type"] == "channel_sub" and camp["channel_username"] and not camp["is_demo"]:
        ok, reason = await verify_telegram_membership(bot, camp["channel_username"], call.from_user.id)
        if not ok:
            await call.answer(f"❌ {reason}", show_alert=True)
            return

    res = await engine.complete_task(call.from_user.id, camp_id)
    if not res["ok"]:
        await call.answer(f"⚠️ {res['error']}", show_alert=True)
        return

    # Уведомляем рефереров при крупных начислениях или просто копим в балансе
    await call.answer(f"🎉 Зачислено +{res['worker_reward']:.2f} ₽ на баланс!", show_alert=True)
    await _check_and_render_earn_menu(call.message, call.from_user.id, edit=True)
