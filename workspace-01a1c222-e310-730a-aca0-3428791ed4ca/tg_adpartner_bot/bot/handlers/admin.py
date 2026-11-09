import asyncio
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from bot import keyboards as kb
from bot.states import AdminFSM
from core import engine
from core.database import get_db

router = Router()


async def _is_admin(user_id: int) -> bool:
    return await engine.check_or_claim_admin(user_id)


async def _render_admin_home(msg: Message, edit: bool = False):
    dash = await engine.get_admin_dashboard()
    s = dash["summary"]
    pending = sum(1 for p in dash["payments"] if p["status"] == "pending")
    text = (
        f"👑 <b>Панель владельца AdPartner Pro</b>\n\n"
        f"💰 <b>Ваша чистая прибыль (Сейф): {s['net_owner_profit']:.2f} ₽</b>\n"
        f"📈 Валовой оборот платформы: <b>{s['gross_turnover']:.2f} ₽</b>\n"
        f"🤝 Выплачено партнёрам (3 ур.): <b>{s['partner_paid']:.2f} ₽</b>\n"
        f"👷 Выплачено исполнителям: <b>{s['worker_paid']:.2f} ₽</b>\n\n"
        f"👥 Участников: <b>{s['users_count']}</b> (VIP: <b>{s['vip_count']}</b>)\n"
        f"💳 Ожидают решения по СБП: <b>{pending} заяв.</b>"
    )
    markup = kb.admin_panel_kb(pending_count=pending)
    if edit:
        await msg.edit_text(text, reply_markup=markup)
    else:
        await msg.answer(text, reply_markup=markup)


@router.message(Command("admin"))
@router.message(F.text == "👑 Админ-панель")
async def cmd_admin(message: Message, state: FSMContext):
    if not await _is_admin(message.from_user.id):
        await message.answer("⛔ Доступ только для владельца бота (проверьте ADMIN_IDS в настройках).")
        return
    await state.clear()
    await _render_admin_home(message, edit=False)


@router.callback_query(F.data == "adm:home")
async def cb_adm_home(call: CallbackQuery, state: FSMContext):
    if not await _is_admin(call.from_user.id):
        return
    await state.clear()
    await _render_admin_home(call.message, edit=True)
    await call.answer()


@router.callback_query(F.data == "adm:vault")
async def cb_adm_vault(call: CallbackQuery):
    if not await _is_admin(call.from_user.id):
        return
    dash = await engine.get_admin_dashboard()
    names = {
        "task_margin": "📢 Маржа с заданий",
        "sponsor_op": "🔒 Слоты ОП (Спонсоры)",
        "native_ads": "🎯 Авто-показы под меню",
        "broadcast": "🚀 Прямые авто-рассылки",
        "vip_sale": "💎 Продажа VIP-статусов",
        "withdraw_fee": "🏦 Комиссия на вывод",
    }
    lines = ["📈 <b>Детализация чистой прибыли владельца:</b>\n"]
    for item in dash["profit_breakdown"]:
        lbl = names.get(item["event_type"], item["event_type"])
        lines.append(f"• {lbl}: <b>+{item['profit']:.2f} ₽</b> (оборот {item['gross']:.2f} ₽)")
    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад в админку", callback_data="adm:home")]]
    )
    await call.message.edit_text("\n".join(lines), reply_markup=back_kb)
    await call.answer()


@router.callback_query(F.data == "adm:payments")
async def cb_adm_payments(call: CallbackQuery):
    if not await _is_admin(call.from_user.id):
        return
    dash = await engine.get_admin_dashboard()
    pend = [p for p in dash["payments"] if p["status"] == "pending"]
    if not pend:
        await call.answer("Нет необработанных заявок СБП!", show_alert=True)
        return

    p = pend[0]
    dir_txt = "📥 ПОПОЛНЕНИЕ СБП" if p["direction"] == "deposit" else "📤 ВЫВОД НА СБП"
    amt_str = f"+{p['net_rub']:.0f} ₽" if p["direction"] == "deposit" else f"{p['net_rub']:.2f} ₽"
    text = (
        f"💳 <b>Заявка #{p['id']} ({dir_txt})</b> — ещё в очереди: {len(pend)}\n\n"
        f"👤 Пользователь: {p.get('full_name') or ''} (ID <code>{p['user_id']}</code>)\n"
        f"💰 Сумма: <b>{p['amount_rub']:.2f} ₽</b> | Чистыми: <b>{p['net_rub']:.2f} ₽</b>\n"
        f"📋 Реквизиты / детали: <code>{p['requisites']}</code>"
    )
    markup = kb.admin_payment_decision_kb(p["id"], p["direction"], amt_str)
    markup.inline_keyboard.append([InlineKeyboardButton(text="◀️ В админ-меню", callback_data="adm:home")])
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data.startswith("adm:pay_ok:") | F.data.startswith("adm:pay_no:"))
async def cb_adm_resolve_pay(call: CallbackQuery, bot: Bot):
    if not await _is_admin(call.from_user.id):
        return
    parts = call.data.split(":")
    approve = parts[1] == "pay_ok"
    pay_id = int(parts[2])

    res = await engine.resolve_payment_request(pay_id, approve=approve)
    if not res["ok"]:
        await call.answer(res["error"], show_alert=True)
        return

    p = res["payment"]
    try:
        if p["direction"] == "deposit":
            msg_txt = (
                f"✅ <b>Пополнение СБП #{pay_id} подтверждено!</b>\n"
                f"На рекламный баланс зачислено <b>+{p['net_rub']:.2f} ₽</b>."
                if approve
                else f"❌ Заявка на пополнение #{pay_id} отклонена (платёж не найден)."
            )
        else:
            msg_txt = (
                f"💸 <b>Выплата #{pay_id} на сумму {p['net_rub']:.2f} ₽ отправлена по вашим реквизитам СБП!</b>"
                if approve
                else f"↩️ Заявка на вывод #{pay_id} отменена, {p['amount_rub']:.2f} ₽ возвращены на ваш баланс."
            )
        await bot.send_message(p["user_id"], msg_txt)
    except Exception:
        pass

    await call.answer("✅ Готово! Статус обновлён.", show_alert=True)
    await _render_admin_home(call.message, edit=True)


@router.callback_query(F.data == "adm:campaigns")
async def cb_adm_campaigns(call: CallbackQuery):
    if not await _is_admin(call.from_user.id):
        return
    dash = await engine.get_admin_dashboard()
    lines = ["📢 <b>Активные кампании на платформе:</b>\n"]
    for c in dash["campaigns"][:10]:
        lines.append(
            f"• #{c['id']} [{c['status']}] <b>{c['title'][:28]}</b> — {c['completed_qty']}/{c['total_qty']} ({c['price_per_action']:.2f} ₽)"
        )
    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад в админку", callback_data="adm:home")]]
    )
    await call.message.edit_text("\n".join(lines), reply_markup=back_kb)
    await call.answer()


@router.callback_query(F.data == "adm:settings")
async def cb_adm_settings(call: CallbackQuery):
    if not await _is_admin(call.from_user.id):
        return
    s = await engine.get_settings()
    buttons = [
        [InlineKeyboardButton(text=f"Маржа владельца: {s.get('platform_fee_pct')}%", callback_data="adm:set:platform_fee_pct")],
        [InlineKeyboardButton(text=f"Телефон СБП: {s.get('sbp_phone')}", callback_data="adm:set:sbp_phone")],
        [InlineKeyboardButton(text=f"Банк СБП: {s.get('sbp_bank')}", callback_data="adm:set:sbp_bank")],
        [InlineKeyboardButton(text=f"Получатель СБП: {s.get('sbp_recipient')}", callback_data="adm:set:sbp_recipient")],
        [InlineKeyboardButton(text=f"Курс 1 Star: {s.get('stars_rate_rub')} ₽", callback_data="adm:set:stars_rate_rub")],
        [InlineKeyboardButton(text=f"Мин. вывод: {s.get('min_withdraw_rub')} ₽", callback_data="adm:set:min_withdraw_rub")],
        [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="adm:home")],
    ]
    await call.message.edit_text(
        "⚙️ <b>Настройки монетизации и СБП (нажмите на параметр для изменения):</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm:set:"))
async def cb_adm_edit_setting(call: CallbackQuery, state: FSMContext):
    if not await _is_admin(call.from_user.id):
        return
    key = call.data.split(":")[2]
    await state.update_data(setting_key=key)
    await state.set_state(AdminFSM.entering_setting_value)
    await call.message.edit_text(f"✏️ Введите новое значение для параметра <code>{key}</code>:")
    await call.answer()


@router.message(AdminFSM.entering_setting_value)
async def fsm_adm_save_setting(message: Message, state: FSMContext):
    if not await _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    await state.clear()
    await engine.update_settings({data["setting_key"]: (message.text or "").strip()})
    await message.answer(f"✅ Параметр <code>{data['setting_key']}</code> успешно сохранён!")
    await _render_admin_home(message, edit=False)


@router.callback_query(F.data == "adm:broadcast")
async def cb_adm_broadcast(call: CallbackQuery, state: FSMContext):
    if not await _is_admin(call.from_user.id):
        return
    await state.set_state(AdminFSM.entering_broadcast_text)
    await call.message.edit_text("📨 Отправьте текст сообщения для рассылки всем пользователям бота:")
    await call.answer()


@router.message(AdminFSM.entering_broadcast_text)
async def fsm_adm_broadcast_send(message: Message, state: FSMContext, bot: Bot):
    if not await _is_admin(message.from_user.id):
        return
    text = message.html_text or message.text or ""
    await state.clear()

    db = await get_db()
    try:
        cur = await db.execute("SELECT tg_id FROM users WHERE is_banned = 0 AND is_demo = 0")
        uids = [r["tg_id"] for r in await cur.fetchall()]
    finally:
        await db.close()

    sent = 0
    for uid in uids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)

    await message.answer(f"✅ Рассылка завершена! Успешно доставлено: <b>{sent}</b> чел.")


@router.callback_query(F.data == "adm:clear_demo")
async def cb_adm_clear_demo(call: CallbackQuery):
    if not await _is_admin(call.from_user.id):
        return
    await engine.clear_demo_data()
    await call.answer("🧹 Демо-данные очищены! Бот готов к чистому боевому старту.", show_alert=True)
    await _render_admin_home(call.message, edit=True)
