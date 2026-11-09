from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from bot import keyboards as kb
from bot.states import PaymentFSM
from core import engine
from core.config import get_env_config

router = Router()


# ==================== TELEGRAM STARS (XTR — 100% АВТО) ====================

@router.callback_query(F.data == "pay:stars")
async def cb_stars_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    settings = await engine.get_settings()
    rate = float(settings.get("stars_rate_rub", 1.50))
    await call.message.edit_text(
        f"⭐ <b>Мгновенное пополнение через Telegram Stars (Авто 24/7)</b>\n\n"
        f"Курс зачисления: <b>1 ⭐ = {rate:.2f} ₽</b> на рекламный баланс.\n"
        f"Средства зачисляются автоматически сразу после оплаты в Telegram!\n\n"
        f"Выберите пакет или введите произвольное число Звёзд:",
        reply_markup=kb.stars_packages_kb(rate),
    )
    await call.answer()


@router.callback_query(F.data.startswith("pay:stars_pack:"))
async def cb_stars_send_invoice(call: CallbackQuery, bot: Bot):
    stars = int(call.data.split(":")[2])
    await _send_xtr_invoice(bot, call.from_user.id, stars)
    await call.answer("Счёт на оплату Telegram Stars отправлен ниже 👇")


@router.callback_query(F.data == "pay:stars_custom")
async def cb_stars_custom(call: CallbackQuery, state: FSMContext):
    await state.set_state(PaymentFSM.entering_stars_amount)
    await call.message.edit_text("⭐ Введите количество Telegram Stars для оплаты (от <code>10</code> до <code>25000</code>):")
    await call.answer()


@router.message(PaymentFSM.entering_stars_amount)
async def fsm_stars_custom(message: Message, state: FSMContext, bot: Bot):
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (10 <= int(raw) <= 25000):
        await message.answer("Введите целое число от 10 до 25000:")
        return
    await state.clear()
    await _send_xtr_invoice(bot, message.from_user.id, int(raw))


async def _send_xtr_invoice(bot: Bot, chat_id: int, stars_amount: int):
    settings = await engine.get_settings()
    rate = float(settings.get("stars_rate_rub", 1.50))
    rub = round(stars_amount * rate, 2)
    await bot.send_invoice(
        chat_id=chat_id,
        title=f"Пополнение рекламы (+{rub:.0f} ₽)",
        description=f"Автоматическое пополнение рекламного баланса на {rub:.2f} ₽ в AdPartner Pro.",
        payload=f"ad_topup_stars:{stars_amount}",
        provider_token="",  # Пустая строка обязательна для Telegram Stars (XTR)
        currency="XTR",
        prices=[LabeledPrice(label=f"+{rub:.0f} ₽ на баланс", amount=stars_amount)],
    )


@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_stars_payment(message: Message):
    sp = message.successful_payment
    if sp.currency == "XTR":
        stars_paid = int(sp.total_amount)
        res = await engine.credit_stars_deposit(message.from_user.id, stars_paid)
        await message.answer(
            f"✅ <b>Оплата {stars_paid} ⭐ успешно принята автоматически!</b>\n"
            f"На ваш рекламный баланс зачислено <b>+{res['rub_amount']:.2f} ₽</b>.\n"
            f"Можете сразу запускать рекламные кампании!",
            reply_markup=kb.advertiser_menu_kb(),
        )


# ==================== ПОПОЛНЕНИЕ ПО СБП (БЕЗ ИП) ====================

@router.callback_query(F.data == "pay:sbp_dep")
async def cb_sbp_deposit_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(PaymentFSM.entering_sbp_deposit_amount)
    await call.message.edit_text(
        "🏦 <b>Пополнение рекламного баланса по СБП (0% комиссии)</b>\n\n"
        "Введите сумму пополнения в рублях (от <code>100</code> ₽, например: <code>500</code>):"
    )
    await call.answer()


@router.message(PaymentFSM.entering_sbp_deposit_amount)
async def fsm_sbp_deposit_amount(message: Message, state: FSMContext):
    try:
        amt = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите сумму числом (например: 500):")
        return
    await state.clear()
    res = await engine.create_sbp_deposit_request(message.from_user.id, amt)
    if not res["ok"]:
        await message.answer(f"❌ {res['error']}")
        return

    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ Я перевёл ровно {res['check_amount']:.0f} ₽",
                    callback_data=f"pay:sbp_paid:{res['payment_id']}",
                )
            ],
            [InlineKeyboardButton(text="◀️ В кошелёк", callback_data="pay:wallet")],
        ]
    )
    await message.answer(
        f"🏦 <b>Заявка на пополнение #{res['payment_id']} создана!</b>\n\n"
        f"Переведите по СБП <b>ТОЧНУЮ проверочную сумму</b> (вся она зачислится вам на баланс):\n"
        f"💰 Сумма к переводу: <code>{res['check_amount']:.0f}</code> ₽\n"
        f"📱 Телефон СБП: <code>{res['sbp_phone']}</code>\n"
        f"🏛 Банк: <b>{res['sbp_bank']}</b>\n"
        f"👤 Получатель: <b>{res['sbp_recipient']}</b>\n\n"
        f"После перевода нажмите кнопку <b>«✅ Я перевёл»</b> ниже — администратор подтвердит зачисление в 1 клик!",
        reply_markup=confirm_kb,
    )


@router.callback_query(F.data.startswith("pay:sbp_paid:"))
async def cb_sbp_notify_admin(call: CallbackQuery, bot: Bot):
    pay_id = int(call.data.split(":")[2])
    env_cfg = get_env_config()
    u = call.from_user
    dash = await engine.get_admin_dashboard()
    pay = next((p for p in dash["payments"] if int(p["id"]) == pay_id), None)
    if not pay:
        await call.answer("Заявка не найдена.", show_alert=True)
        return

    for admin_id in env_cfg["admin_ids"]:
        try:
            await bot.send_message(
                admin_id,
                f"💳 <b>Новое пополнение СБП #{pay_id}!</b>\n\n"
                f"👤 Клиент: {u.full_name} (@{u.username or 'без_ника'}, ID <code>{u.id}</code>)\n"
                f"💰 Проверочная сумма к поступлению: <b>{pay['net_rub']:.0f} ₽</b>\n\n"
                f"Проверьте поступление в банке и нажмите кнопку:",
                reply_markup=kb.admin_payment_decision_kb(pay_id, "deposit", f"+{pay['net_rub']:.0f} ₽"),
            )
        except Exception:
            pass

    await call.message.edit_text(
        f"⏳ <b>Уведомление по заявке #{pay_id} отправлено!</b>\n"
        f"Как только перевод будет проверен, бот пришлёт уведомление и автоматически пополнит ваш баланс."
    )
    await call.answer("Уведомление отправлено!")


# ==================== ВЫВОД ЗАРАБОТКА ПО СБП ====================

@router.callback_query(F.data == "pay:withdraw")
async def cb_withdraw_start(call: CallbackQuery, state: FSMContext):
    settings = await engine.get_settings()
    u = await engine.get_user(call.from_user.id)
    min_w = settings.get("min_withdraw_rub", "100")
    fee = settings.get("withdraw_fee_pct", "5")
    await state.set_state(PaymentFSM.entering_withdraw_amount)
    await call.message.edit_text(
        f"💸 <b>Вывод средств по СБП</b>\n\n"
        f"Доступно к выводу: <b>{u['balance_earn']:.2f} ₽</b>\n"
        f"Минимальная сумма: <b>{min_w} ₽</b> (комиссия шлюза {fee}%).\n\n"
        f"Введите сумму вывода в рублях:"
    )
    await call.answer()


@router.message(PaymentFSM.entering_withdraw_amount)
async def fsm_withdraw_amount(message: Message, state: FSMContext):
    try:
        amt = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите сумму числом:")
        return
    settings = await engine.get_settings()
    if amt < float(settings.get("min_withdraw_rub", 100)):
        await message.answer(f"Минимальная сумма вывода — {settings.get('min_withdraw_rub', '100')} ₽:")
        return
    await state.update_data(withdraw_amount=amt)
    await state.set_state(PaymentFSM.entering_withdraw_requisites)
    await message.answer(
        "📱 Введите ваш <b>номер телефона СБП, название банка и Имя О.</b>\n"
        "Пример: <code>+7 918 123-45-67, Т-Банк, Алексей П.</code>"
    )


@router.message(PaymentFSM.entering_withdraw_requisites)
async def fsm_withdraw_req(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    res = await engine.create_sbp_withdraw_request(
        user_id=message.from_user.id,
        amount_rub=data["withdraw_amount"],
        requisites=message.text or "",
    )
    if not res["ok"]:
        await message.answer(f"❌ {res['error']}")
        return

    env_cfg = get_env_config()
    u = message.from_user
    for admin_id in env_cfg["admin_ids"]:
        try:
            await bot.send_message(
                admin_id,
                f"📤 <b>Заявка на вывод СБП #{res['payment_id']}</b>\n\n"
                f"👤 Партнёр: {u.full_name} (@{u.username or 'без_ника'}, ID <code>{u.id}</code>)\n"
                f"💵 Списано с баланса: {res['amount_rub']:.2f} ₽ (ваша комиссия +{res['fee_rub']:.2f} ₽)\n"
                f"💸 <b>К переводу по СБП: {res['net_rub']:.2f} ₽</b>\n"
                f"🏦 Реквизиты: <code>{message.text}</code>",
                reply_markup=kb.admin_payment_decision_kb(res["payment_id"], "withdraw", f"{res['net_rub']:.2f} ₽"),
            )
        except Exception:
            pass

    await message.answer(
        f"✅ <b>Заявка на вывод #{res['payment_id']} принята!</b>\n"
        f"Сумма к получению на карту по СБП: <b>{res['net_rub']:.2f} ₽</b>.\n"
        f"Ожидайте уведомления о выплате!"
    )


# ==================== РЕИНВЕСТ С БОНУСОМ +10% ====================

@router.callback_query(F.data == "pay:reinvest")
async def cb_reinvest_start(call: CallbackQuery, state: FSMContext):
    u = await engine.get_user(call.from_user.id)
    await state.set_state(PaymentFSM.entering_reinvest_amount)
    await call.message.edit_text(
        f"🔄 <b>Перевод заработанных средств на рекламу (+10% БОНУС!)</b>\n\n"
        f"Ваш баланс заработка: <b>{u['balance_earn']:.2f} ₽</b>.\n"
        f"Введите сумму для мгновенного перевода на рекламный счёт (от 10 ₽):"
    )
    await call.answer()


@router.message(PaymentFSM.entering_reinvest_amount)
async def fsm_reinvest_do(message: Message, state: FSMContext):
    try:
        amt = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите сумму числом:")
        return
    await state.clear()
    res = await engine.reinvest_earn_to_adv(message.from_user.id, amt)
    if not res["ok"]:
        await message.answer(f"❌ {res['error']}")
        return
    await message.answer(
        f"🎉 <b>Перевод выполнен мгновенно!</b>\n"
        f"Списано: {res['debited']:.2f} ₽ → На рекламный баланс зачислено <b>+{res['credited']:.2f} ₽</b> (+{res['bonus_pct']:.0f}% бонус)!"
    )
