from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from bot import keyboards as kb
from bot.middlewares import append_native_ad
from bot.states import PartnerVoucherFSM
from core import engine
from core.database import get_db

router = Router()


async def _render_partner_hub(msg: Message, user_id: int, edit: bool = False):
    stats = await engine.get_partner_network_stats(user_id)
    if not stats:
        return
    settings = await engine.get_settings()
    u = stats["user"]
    c = stats["counts"]
    e = stats["earned_by_level"]
    r = stats["rates"]
    vip_price = settings.get("vip_price_rub", "390")

    text = (
        f"🤝 <b>Внутренняя партнёрская сеть (3 уровня Авто-дохода)</b>\n\n"
        f"🎖 Ваш ранг: <b>{'💎 VIP-Амбассадор' if u['is_vip'] else u['partner_rank']}</b>\n"
        f"💰 Заработано с сети: <b>{u['ref_earned']:.2f} ₽</b>\n\n"
        f"🌳 <b>Ваша команда ({c['total']} чел.):</b>\n"
        f"• 1-я линия: <b>{c['l1']} партн.</b> → принесли <b>{e[1]:.2f} ₽</b>\n"
        f"  └ Ставка: <b>{r['task_l1']:.0f}%</b> с заданий + <b>{r['adv_l1']:.0f}%</b> с рекламы\n"
        f"• 2-я линия: <b>{c['l2']} партн.</b> → принесли <b>{e[2]:.2f} ₽</b>\n"
        f"  └ Ставка: <b>{r['task_l2']:.0f}%</b> с заданий + <b>{r['adv_l2']:.0f}%</b> с рекламы\n"
        f"• 3-я линия: <b>{c['l3']} партн.</b> → принесли <b>{e[3]:.2f} ₽</b>\n"
        f"  └ Ставка: <b>{r['task_l3']:.0f}%</b> с заданий + <b>{r['adv_l3']:.0f}%</b> с рекламы\n\n"
        f"🔗 <b>Ваша персональная ссылка автопривлечения:</b>\n"
        f"<code>{stats['ref_link']}</code>\n"
        f"<i>(Нажмите на ссылку, чтобы скопировать в 1 клик)</i>"
    )
    text = await append_native_ad(text, user_id=user_id)
    markup = kb.partner_network_kb(stats["ref_link"], bool(u["is_vip"]), vip_price)
    if edit:
        await msg.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    else:
        await msg.answer(text, reply_markup=markup, disable_web_page_preview=True)


@router.message(F.text == "🤝 Партнёрская сеть")
async def msg_partners(message: Message, state: FSMContext):
    await state.clear()
    await _render_partner_hub(message, message.from_user.id, edit=False)


@router.callback_query(F.data == "part:hub")
async def cb_partners_hub(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await _render_partner_hub(call.message, call.from_user.id, edit=True)
    await call.answer()


@router.callback_query(F.data == "part:promos")
async def cb_partner_promos(call: CallbackQuery):
    stats = await engine.get_partner_network_stats(call.from_user.id)
    blocks = ["📣 <b>Готовые креативы для автопродвижения вашей ссылки:</b>\n"]
    for idx, tpl in enumerate(stats.get("promo_templates", []), start=1):
        blocks.append(f"<b>Вариант #{idx} ({tpl['target']}):</b>\n<code>{tpl['text']}</code>\n")
    blocks.append("💡 <i>Нажмите на любой текст — он скопируется вместе с вашей реферальной ссылкой!</i>")
    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад в партнёрскую сеть", callback_data="part:hub")]]
    )
    await call.message.edit_text("\n".join(blocks), reply_markup=back_kb, disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data == "part:ranks")
async def cb_partner_ranks(call: CallbackQuery):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT full_name, partner_rank, referrals_l1, ref_earned FROM users ORDER BY ref_earned DESC LIMIT 7"
        )
        leaders = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    lines = [
        "🏆 <b>Система рангов и Топ партнёров сети:</b>\n",
        "• 🥉 <b>Старт</b> (0+ реф.) — 15% / 5% / 2%",
        "• 🥈 <b>Актив</b> (от 10 реф.) — 18% / 6% / 2%",
        "• 🥇 <b>Лидер</b> (от 50 реф.) — 22% / 7% / 3%",
        "• 💎 <b>Амбассадор / VIP</b> (от 200 реф. или VIP) — 25% / 8% / 4% + 15% к заданиям!\n",
        "🔥 <b>Лидеры по партнёрскому доходу:</b>",
    ]
    for i, ldr in enumerate(leaders, start=1):
        lines.append(
            f"{i}. <b>{ldr['full_name'][:22]}</b> ({ldr['partner_rank']}) — <b>{ldr['ref_earned']:.2f} ₽</b> ({ldr['referrals_l1']} в 1-й лин.)"
        )
    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад в партнёрскую сеть", callback_data="part:hub")]]
    )
    await call.message.edit_text("\n".join(lines), reply_markup=back_kb)
    await call.answer()


@router.callback_query(F.data == "part:buy_vip")
async def cb_buy_vip(call: CallbackQuery):
    res = await engine.buy_vip_status(call.from_user.id)
    if not res["ok"]:
        await call.answer(f"⚠️ {res['error']}", show_alert=True)
        return
    await call.answer("💎 Поздравляем! Статус VIP-Амбассадор активирован навсегда!", show_alert=True)
    await _render_partner_hub(call.message, call.from_user.id, edit=True)


@router.callback_query(F.data == "part:new_voucher")
async def cb_new_voucher(call: CallbackQuery, state: FSMContext):
    await state.set_state(PartnerVoucherFSM.entering_amount_per_use)
    await call.message.edit_text(
        "🎫 <b>Создание вирусного реферального чека</b>\n\n"
        "Как это работает: вы создаёте денежный чек-ссылку и кидаете её в чаты/комментарии/канал. "
        "Каждый новичок, забравший бонус по чеку, <b>автоматически закрепляется в вашей 1-й линии навсегда!</b>\n\n"
        "Введите сумму награды на 1 человека в рублях (от <code>1</code> ₽, например: <code>2</code>):"
    )
    await call.answer()


@router.message(PartnerVoucherFSM.entering_amount_per_use)
async def fsm_voucher_amount(message: Message, state: FSMContext):
    try:
        amt = float((message.text or "").replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите число от 1 и выше:")
        return
    if amt < 1.0:
        await message.answer("Минимальная сумма на 1 активацию — 1 ₽:")
        return
    await state.update_data(amount_per_use=amt)
    await state.set_state(PartnerVoucherFSM.entering_max_uses)
    await message.answer("Введите количество активаций чека (например: <code>10</code>):")


@router.message(PartnerVoucherFSM.entering_max_uses)
async def fsm_voucher_uses(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await message.answer("Введите целое число активаций (от 1):")
        return
    data = await state.get_data()
    await state.clear()
    res = await engine.create_voucher(message.from_user.id, data["amount_per_use"], int(raw))
    if not res["ok"]:
        await message.answer(f"❌ {res['error']}")
        return
    await message.answer(
        f"✅ <b>Вирусный чек создан!</b> (списано {res['total_cost']:.2f} ₽)\n\n"
        f"🔑 Код чека: <code>{res['code']}</code>\n"
        f"🔗 Ссылка для автораздачи и набора рефералов:\n"
        f"<code>{res['deep_link']}</code>"
    )
