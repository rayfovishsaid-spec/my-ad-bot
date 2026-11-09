import urllib.parse
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_reply_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="💰 Заработать"), KeyboardButton(text="🚀 Продвижение / Реклама")],
        [KeyboardButton(text="🤝 Партнёрская сеть"), KeyboardButton(text="👤 Кабинет и Кошелёк")],
        [KeyboardButton(text="🎁 Ежедневный бонус"), KeyboardButton(text="🎫 Активировать чек")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def sponsor_op_kb(sponsors: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for idx, s in enumerate(sponsors, start=1):
        rows.append(
            [InlineKeyboardButton(text=f"📢 Спонсор #{idx}: {s['title'][:30]}", url=s["target_url"])]
        )
    rows.append([InlineKeyboardButton(text="✅ Проверить подписку и открыть задания", callback_data="op:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def earn_categories_kb(counts: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📢 Подписки на каналы ({counts.get('channel_sub', 0)})",
                    callback_data="earn:list:channel_sub",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"👁 Просмотры постов ({counts.get('post_view', 0)})",
                    callback_data="earn:list:post_view",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🤖 Переходы в ботов / ссылки ({counts.get('bot_start', 0)})",
                    callback_data="earn:list:bot_start",
                )
            ],
            [InlineKeyboardButton(text="🔄 Обновить список заданий", callback_data="earn:menu")],
        ]
    )


def task_card_kb(task: dict) -> InlineKeyboardMarkup:
    action_label = {
        "channel_sub": "📢 Перейти и подписаться",
        "post_view": "👁 Открыть пост",
        "bot_start": "🤖 Запустить / перейти",
    }.get(task["type"], "🔗 Открыть ссылку")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=action_label, url=task["target_url"])],
            [
                InlineKeyboardButton(
                    text=f"✅ Проверить и получить +{task['worker_reward']:.2f} ₽",
                    callback_data=f"earn:verify:{task['id']}",
                )
            ],
            [
                InlineKeyboardButton(text="⏭ Следующее", callback_data=f"earn:list:{task['type']}"),
                InlineKeyboardButton(text="◀️ К разделам", callback_data="earn:menu"),
            ],
        ]
    )


def advertiser_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Запустить новую рекламу", callback_data="adv:new")],
            [InlineKeyboardButton(text="📊 Мои кампании", callback_data="adv:my")],
            [
                InlineKeyboardButton(text="⭐ Пополнить Stars (Авто)", callback_data="pay:stars"),
                InlineKeyboardButton(text="🏦 Пополнить по СБП", callback_data="pay:sbp_dep"),
            ],
            [InlineKeyboardButton(text="🔄 Перевести с заработка (+10% бонус)", callback_data="pay:reinvest")],
        ]
    )


def campaign_types_kb(settings: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📢 Подписчики в канал (от {settings.get('min_price_channel_sub', '3.50')} ₽)",
                    callback_data="adv:type:channel_sub",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"👁 Просмотры поста (от {settings.get('min_price_post_view', '1.20')} ₽)",
                    callback_data="adv:type:post_view",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🤖 Переходы в бота / ссылку (от {settings.get('min_price_bot_start', '4.00')} ₽)",
                    callback_data="adv:type:bot_start",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔒 Слот ОП — Спонсор (от {settings.get('min_price_sponsor_op', '6.00')} ₽)",
                    callback_data="adv:type:sponsor_op",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🎯 Авто-показы под меню (от {settings.get('min_price_native_ad', '0.50')} ₽)",
                    callback_data="adv:type:native_ad",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🚀 Авто-рассылка по базе (от {settings.get('min_price_broadcast', '0.80')} ₽)",
                    callback_data="adv:type:broadcast",
                )
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adv:menu")],
        ]
    )


def partner_network_kb(ref_link: str, is_vip: bool, vip_price: str) -> InlineKeyboardMarkup:
    share_text = urllib.parse.quote(
        "💸 Зарабатывай в Telegram на простых подписках и 3-уровневой партнёрской сети! Бонус на старт 👇"
    )
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={share_text}"
    rows = [
        [InlineKeyboardButton(text="📲 Поделиться ссылкой в 1 клик", url=share_url)],
        [
            InlineKeyboardButton(text="🎫 Создать вирусный чек", callback_data="part:new_voucher"),
            InlineKeyboardButton(text="📣 Готовые авто-посты", callback_data="part:promos"),
        ],
        [InlineKeyboardButton(text="🏆 Топ партнёров и ранги", callback_data="part:ranks")],
    ]
    if not is_vip:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"💎 Включить VIP-Амбассадор ({vip_price} ₽ — макс. %)",
                    callback_data="part:buy_vip",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wallet_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ Пополнить Telegram Stars", callback_data="pay:stars"),
                InlineKeyboardButton(text="🏦 Пополнить по СБП", callback_data="pay:sbp_dep"),
            ],
            [InlineKeyboardButton(text="💸 Вывести заработок по СБП", callback_data="pay:withdraw")],
            [InlineKeyboardButton(text="🔄 На рекламу с бонусом +10%", callback_data="pay:reinvest")],
        ]
    )


def stars_packages_kb(rate: float) -> InlineKeyboardMarkup:
    packages = [50, 100, 250, 500, 1000]
    rows = []
    for stars in packages:
        rub = round(stars * rate, 0)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"⭐ {stars} Stars → +{rub:.0f} ₽ на рекламу",
                    callback_data=f"pay:stars_pack:{stars}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="✏️ Ввести другое число Stars", callback_data="pay:stars_custom")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="pay:wallet")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_payment_decision_kb(payment_id: int, direction: str, amount_str: str) -> InlineKeyboardMarkup:
    ok_label = f"✅ Зачислить {amount_str}" if direction == "deposit" else f"💸 Подтвердить выплату {amount_str}"
    no_label = "❌ Отклонить" if direction == "deposit" else "↩️ Отклонить (вернуть на баланс)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ok_label, callback_data=f"adm:pay_ok:{payment_id}")],
            [InlineKeyboardButton(text=no_label, callback_data=f"adm:pay_no:{payment_id}")],
        ]
    )


def admin_panel_kb(pending_count: int = 0) -> InlineKeyboardMarkup:
    badge = f" ({pending_count} новых!)" if pending_count > 0 else ""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Заявки СБП (Ввод/Вывод){badge}", callback_data="adm:payments")],
            [
                InlineKeyboardButton(text="📈 Касса прибыли", callback_data="adm:vault"),
                InlineKeyboardButton(text="📢 Все кампании", callback_data="adm:campaigns"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Настроить % и СБП", callback_data="adm:settings"),
                InlineKeyboardButton(text="📨 Рассылка от админа", callback_data="adm:broadcast"),
            ],
            [InlineKeyboardButton(text="🧹 Очистить демо-данные", callback_data="adm:clear_demo")],
        ]
    )
