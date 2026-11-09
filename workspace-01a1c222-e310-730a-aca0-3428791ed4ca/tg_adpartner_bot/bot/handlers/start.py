from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot import keyboards as kb
from bot.middlewares import append_native_ad
from bot.states import PartnerVoucherFSM
from core import engine
from core.config import get_env_config

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot, state: FSMContext):
    await state.clear()
    args = (command.args or "").strip()
    ref_id = None
    voucher_code = None

    if args.startswith("ref_"):
        raw = args.replace("ref_", "")
        if raw.isdigit():
            ref_id = int(raw)
    elif args.startswith("chk_"):
        voucher_code = args.replace("chk_", "")

    user, is_new = await engine.ensure_user(
        tg_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name or "Пользователь",
        referrer_id=ref_id,
    )

    if is_new and user.get("referrer_id"):
        try:
            await bot.send_message(
                user["referrer_id"],
                f"🎉 <b>Новый партнёр в 1-й линии!</b>\n"
                f"К вашей сети присоединился <b>{message.from_user.full_name}</b>.\n"
                f"Вы будете автоматически получать % с его заданий и рекламных пополнений!",
            )
        except Exception:
            pass

    voucher_note = ""
    if voucher_code:
        res = await engine.claim_voucher(message.from_user.id, voucher_code)
        if res["ok"]:
            voucher_note = f"\n\n🎁 <b>Чек активирован!</b> На ваш баланс зачислено <b>+{res['amount']:.2f} ₽</b>!"
        else:
            voucher_note = f"\n\nℹ️ {res['error']}"

    is_admin = await engine.check_or_claim_admin(message.from_user.id)
    welcome = (
        f"👋 <b>Добро пожаловать в AdPartner Pro!</b>\n\n"
        f"Это автоматизированная биржа продвижения в Telegram и 3-уровневая партнёрская сеть:\n"
        f"• 💰 <b>Зарабатывайте</b> на простых подписках и просмотрах с выводом по СБП\n"
        f"• 🚀 <b>Продвигайте</b> свои ТГ-каналы, посты и ботов с автопроверкой подписки\n"
        f"• 🤝 <b>Стройте партнёрскую сеть</b> (до 25% с заданий + до 10% с рекламы 3 уровней!)"
        f"{voucher_note}"
    )
    welcome = await append_native_ad(welcome, user_id=message.from_user.id)
    await message.answer(welcome, reply_markup=kb.main_reply_kb(is_admin=is_admin), disable_web_page_preview=True)


@router.message(F.text == "👤 Кабинет и Кошелёк")
async def show_profile(message: Message, state: FSMContext):
    await state.clear()
    await _send_wallet_card(message, message.from_user.id)


@router.callback_query(F.data == "pay:wallet")
async def cb_wallet(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await _send_wallet_card(call.message, call.from_user.id, edit=True)
    await call.answer()


async def _send_wallet_card(msg: Message, user_id: int, edit: bool = False):
    u = await engine.get_user(user_id)
    if not u:
        return
    vip_badge = "💎 VIP-Амбассадор" if u["is_vip"] else f"🎖 Ранг: {u['partner_rank']}"
    text = (
        f"👤 <b>Личный кабинет и Кошелёк</b>\n"
        f"🆔 Ваш ID: <code>{u['tg_id']}</code> | {vip_badge}\n\n"
        f"💵 <b>Баланс заработка (доступно к выводу):</b> <code>{u['balance_earn']:.2f} ₽</code>\n"
        f"📣 <b>Рекламный баланс:</b> <code>{u['balance_adv']:.2f} ₽</code>\n\n"
        f"📊 <b>Статистика автоматизации:</b>\n"
        f"• Выполнено заданий: <b>{u['tasks_completed']}</b>\n"
        f"• Всего заработано: <b>{u['total_earned']:.2f} ₽</b>\n"
        f"• Доход с партнёрской сети: <b>{u['ref_earned']:.2f} ₽</b>\n"
        f"• Вложено в рекламу: <b>{u['ad_spent']:.2f} ₽</b>"
    )
    text = await append_native_ad(text, user_id=user_id)
    if edit:
        await msg.edit_text(text, reply_markup=kb.wallet_kb(), disable_web_page_preview=True)
    else:
        await msg.answer(text, reply_markup=kb.wallet_kb(), disable_web_page_preview=True)


@router.message(F.text == "🎁 Ежедневный бонус")
async def msg_daily_bonus(message: Message):
    res = await engine.claim_daily_bonus(message.from_user.id)
    if res["ok"]:
        txt = await append_native_ad(
            f"🎁 <b>Ежедневный бонус получен!</b>\n"
            f"На баланс заработка начислено <b>+{res['bonus']:.2f} ₽</b>.\n"
            f"Заходите завтра за новым бонусом и свежими заданиями!",
            user_id=message.from_user.id,
        )
        await message.answer(txt, disable_web_page_preview=True)
    else:
        await message.answer(f"⏳ {res['error']}")


@router.message(F.text == "🎫 Активировать чек")
async def msg_claim_voucher(message: Message, state: FSMContext):
    await state.set_state(PartnerVoucherFSM.entering_claim_code)
    await message.answer(
        "🎫 <b>Активация денежного чека</b>\n\n"
        "Введите код чека (например: <code>BONUS2026</code>):"
    )


@router.message(PartnerVoucherFSM.entering_claim_code)
async def fsm_claim_voucher(message: Message, state: FSMContext):
    await state.clear()
    res = await engine.claim_voucher(message.from_user.id, message.text or "")
    if res["ok"]:
        await message.answer(
            f"✅ <b>Чек успешно активирован!</b>\n"
            f"Вам зачислено <b>+{res['amount']:.2f} ₽</b> на основной баланс!"
        )
    else:
        await message.answer(f"❌ {res['error']}")
