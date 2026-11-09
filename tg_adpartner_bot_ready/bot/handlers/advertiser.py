from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from bot import keyboards as kb
from bot.states import CreateCampaignFSM
from core import engine
from core.database import get_db

router = Router()


async def _render_adv_cabinet(msg: Message, user_id: int, edit: bool = False):
    u = await engine.get_user(user_id)
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(completed_qty), 0) AS actions FROM campaigns WHERE owner_id = ?",
            (user_id,),
        )
        stat = await cur.fetchone()
    finally:
        await db.close()

    text = (
        f"🚀 <b>Кабинет автопродвижения и рекламы</b>\n\n"
        f"📣 <b>Рекламный баланс:</b> <code>{u['balance_adv']:.2f} ₽</code>\n"
        f"📊 Ваших кампаний: <b>{stat['cnt']}</b> | Получено целевых действий: <b>{stat['actions']}</b>\n\n"
        f"<b>Доступные авто-форматы 24/7:</b>\n"
        f"• 📢 <b>Подписчики в ТГ-канал</b> (автопроверка + защита от отписок 7 дней)\n"
        f"• 👁 <b>Просмотры постов</b> и переходы в ботов\n"
        f"• 🔒 <b>Слот ОП (Спонсор)</b> — обязательная подписка всех участников\n"
        f"• 🎯 <b>Авто-показы под меню</b> — нативная строка в каждом ответе бота\n"
        f"• 🚀 <b>Авто-рассылка</b> по всей активной базе в 1 клик"
    )
    if edit:
        await msg.edit_text(text, reply_markup=kb.advertiser_menu_kb())
    else:
        await msg.answer(text, reply_markup=kb.advertiser_menu_kb())


@router.message(F.text == "🚀 Продвижение / Реклама")
async def msg_adv_menu(message: Message, state: FSMContext):
    await state.clear()
    await _render_adv_cabinet(message, message.from_user.id, edit=False)


@router.callback_query(F.data == "adv:menu")
async def cb_adv_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await _render_adv_cabinet(call.message, call.from_user.id, edit=True)
    await call.answer()


@router.callback_query(F.data == "adv:new")
async def cb_adv_new(call: CallbackQuery, state: FSMContext):
    await state.clear()
    settings = await engine.get_settings()
    await call.message.edit_text(
        "🎯 <b>Выберите формат автоматического продвижения:</b>",
        reply_markup=kb.campaign_types_kb(settings),
    )
    await call.answer()


@router.callback_query(F.data.startswith("adv:type:"))
async def cb_choose_type(call: CallbackQuery, state: FSMContext):
    c_type = call.data.split(":")[2]
    settings = await engine.get_settings()
    min_price = float(settings.get(f"min_price_{c_type}", 1.0))
    await state.update_data(c_type=c_type, min_price=min_price)
    await state.set_state(CreateCampaignFSM.entering_title)
    label = engine.CAMPAIGN_TYPE_LABELS.get(c_type, c_type)
    await call.message.edit_text(
        f"✍️ <b>Шаг 1 из 5 — Заголовок ({label})</b>\n\n"
        f"Введите короткое и привлекательное название (до 70 символов):"
    )
    await call.answer()


@router.message(CreateCampaignFSM.entering_title)
async def fsm_adv_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if len(title) < 4:
        await message.answer("Введите заголовок минимум из 4 символов:")
        return
    await state.update_data(title=title)
    await state.set_state(CreateCampaignFSM.entering_description)
    await message.answer(
        "📝 <b>Шаг 2 из 5 — Описание / текст задания</b>\n\n"
        "Напишите, что получит пользователь или что нужно сделать (до 200 символов):"
    )


@router.message(CreateCampaignFSM.entering_description)
async def fsm_adv_desc(message: Message, state: FSMContext):
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(CreateCampaignFSM.entering_url)
    await message.answer(
        "🔗 <b>Шаг 3 из 5 — Целевая ссылка</b>\n\n"
        "Отправьте ссылку на ваш ТГ-канал, пост или бота (начинается с <code>https://t.me/...</code> или <code>https://...</code>):"
    )


@router.message(CreateCampaignFSM.entering_url)
async def fsm_adv_url(message: Message, state: FSMContext):
    url = (message.text or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.answer("Ссылка должна начинаться с https:// (например: https://t.me/durov):")
        return
    data = await state.get_data()
    await state.update_data(target_url=url)

    if data["c_type"] in ("channel_sub", "sponsor_op"):
        await state.set_state(CreateCampaignFSM.entering_channel)
        await message.answer(
            "📡 <b>Юзернейм канала для автопроверки подписки</b>\n\n"
            "Отправьте <code>@username</code> вашего канала (например: <code>@my_channel</code>).\n"
            "⚠️ <i>Не забудьте добавить этого бота в администраторы канала, чтобы он автоматически проверял подписки и штрафовал за отписки!</i>"
        )
    else:
        await state.update_data(channel_username="")
        await state.set_state(CreateCampaignFSM.entering_price)
        await message.answer(
            f"💵 <b>Шаг 4 из 5 — Цена за 1 выполнение / показ</b>\n\n"
            f"Минимальная цена: <b>{data['min_price']:.2f} ₽</b>.\n"
            f"Чем выше ставка — тем выше ваше задание в списке!\n"
            f"Введите цену в рублях (например: <code>{data['min_price']:.2f}</code>):"
        )


@router.message(CreateCampaignFSM.entering_channel)
async def fsm_adv_channel(message: Message, state: FSMContext):
    ch = (message.text or "").strip()
    data = await state.get_data()
    await state.update_data(channel_username=ch)
    await state.set_state(CreateCampaignFSM.entering_price)
    await message.answer(
        f"💵 <b>Шаг 4 из 5 — Цена за 1 подписчика</b>\n\n"
        f"Минимальная цена: <b>{data['min_price']:.2f} ₽</b>.\n"
        f"Введите цену в рублях (например: <code>{data['min_price']:.2f}</code>):"
    )


@router.message(CreateCampaignFSM.entering_price)
async def fsm_adv_price(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").strip()
    try:
        price = float(raw)
    except ValueError:
        await message.answer("Введите число (например: 4.00):")
        return

    data = await state.get_data()
    if price < data["min_price"]:
        await message.answer(f"Минимальная ставка для этого формата: {data['min_price']:.2f} ₽. Введите ставку не ниже:")
        return

    await state.update_data(price_per_action=price)
    await state.set_state(CreateCampaignFSM.entering_qty)
    await message.answer(
        "🔢 <b>Шаг 5 из 5 — Количество выполнений / показов</b>\n\n"
        "Введите нужное количество (минимум <code>5</code>, например: <code>100</code>):"
    )


@router.message(CreateCampaignFSM.entering_qty)
async def fsm_adv_qty(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 5:
        await message.answer("Введите целое число от 5 и выше (например: 50):")
        return

    qty = int(raw)
    data = await state.get_data()
    await state.clear()

    res = await engine.create_campaign(
        owner_id=message.from_user.id,
        c_type=data["c_type"],
        title=data["title"],
        description=data["description"],
        target_url=data["target_url"],
        channel_username=data.get("channel_username", ""),
        price_per_action=data["price_per_action"],
        total_qty=qty,
    )
    if not res["ok"]:
        await message.answer(
            f"❌ <b>Не удалось запустить кампанию:</b>\n{res['error']}",
            reply_markup=kb.advertiser_menu_kb(),
        )
        return

    await message.answer(
        f"✅ <b>Рекламная кампания #{res['campaign_id']} запущена автоматически!</b>\n\n"
        f"📌 Формат: <b>{engine.CAMPAIGN_TYPE_LABELS[data['c_type']]}</b>\n"
        f"💰 Бюджет заморожен: <b>{res['total_cost']:.2f} ₽</b> ({qty} × {data['price_per_action']:.2f} ₽)\n\n"
        f"Она уже откручивается в системе 24/7!",
        reply_markup=kb.advertiser_menu_kb(),
    )


@router.callback_query(F.data == "adv:my")
async def cb_my_campaigns(call: CallbackQuery):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM campaigns WHERE owner_id = ? ORDER BY id DESC LIMIT 10",
            (call.from_user.id,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    if not rows:
        await call.answer("У вас пока нет созданных кампаний.", show_alert=True)
        return

    lines = ["📊 <b>Ваши рекламные кампании:</b>\n"]
    buttons = []
    for c in rows:
        st_icon = "🟢" if c["status"] == "active" else ("⏸" if c["status"] == "paused" else "✅")
        lines.append(
            f"{st_icon} <b>#{c['id']} {c['title']}</b>\n"
            f"   Выполнено: <b>{c['completed_qty']} / {c['total_qty']}</b> | Ставка: {c['price_per_action']:.2f} ₽"
        )
        if c["status"] in ("active", "paused"):
            toggle_lbl = f"⏸ Пауза #{c['id']}" if c["status"] == "active" else f"▶️ Старт #{c['id']}"
            buttons.append([InlineKeyboardButton(text=toggle_lbl, callback_data=f"adv:toggle:{c['id']}")])

    buttons.append([InlineKeyboardButton(text="◀️ В рекламный кабинет", callback_data="adv:menu")])
    await call.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await call.answer()


@router.callback_query(F.data.startswith("adv:toggle:"))
async def cb_toggle_campaign(call: CallbackQuery):
    camp_id = int(call.data.split(":")[2])
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT status FROM campaigns WHERE id = ? AND owner_id = ?",
            (camp_id, call.from_user.id),
        )
        row = await cur.fetchone()
        if row and row["status"] in ("active", "paused"):
            nxt = "paused" if row["status"] == "active" else "active"
            await db.execute("UPDATE campaigns SET status = ? WHERE id = ?", (nxt, camp_id))
            await db.commit()
    finally:
        await db.close()
    await cb_my_campaigns(call)
