import aiosqlite
from datetime import datetime, timedelta, timezone
from core.config import DB_PATH, get_env_config

DEFAULT_SETTINGS = {
    # Маржа владельца платформы с каждого рекламного задания (%)
    "platform_fee_pct": "30",
    # Комиссия на вывод заработанных средств (%)
    "withdraw_fee_pct": "5",
    # 3-уровневая партнёрка с заработка рефералов (% от награды исполнителя, платится из фонда платформы)
    "ref_task_l1": "15",
    "ref_task_l2": "5",
    "ref_task_l3": "2",
    # 3-уровневая партнёрка с рекламных пополнений приглашённых рекламодателей (%)
    "ref_adv_l1": "10",
    "ref_adv_l2": "3",
    "ref_adv_l3": "1",
    # Бонус при переводе с баланса заработка на рекламный баланс (%)
    "reinvest_bonus_pct": "10",
    # Курс 1 Звезды Telegram (XTR) при зачислении на баланс бота (в рублях)
    "stars_rate_rub": "1.50",
    # Минимальные цены на рекламу для рекламодателей (в рублях за 1 действие/показ)
    "min_price_channel_sub": "3.50",
    "min_price_post_view": "1.20",
    "min_price_bot_start": "4.00",
    "min_price_sponsor_op": "6.00",
    "min_price_native_ad": "0.50",
    "min_price_broadcast": "0.80",
    # Стоимость VIP-Партнёр статуса (₽ или в пересчёте на Stars)
    "vip_price_rub": "390",
    # Минимальная сумма вывода по СБП (₽)
    "min_withdraw_rub": "100",
    # Ежедневный бонус для удержания аудитории (₽)
    "daily_bonus_rub": "1.00",
    # Срок контроля неотписки от каналов рекламодателей (дней)
    "unsub_hold_days": "7",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    return db


async def init_db(seed_demo: bool = True) -> None:
    db = await get_db()
    try:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                full_name TEXT DEFAULT 'Пользователь',
                balance_earn REAL DEFAULT 0.0,
                balance_adv REAL DEFAULT 0.0,
                referrer_id INTEGER DEFAULT NULL,
                partner_rank TEXT DEFAULT 'Старт',
                total_earned REAL DEFAULT 0.0,
                ref_earned REAL DEFAULT 0.0,
                ad_spent REAL DEFAULT 0.0,
                tasks_completed INTEGER DEFAULT 0,
                referrals_l1 INTEGER DEFAULT 0,
                is_vip INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                is_demo INTEGER DEFAULT 0,
                last_bonus_at TEXT DEFAULT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                target_url TEXT NOT NULL,
                channel_username TEXT DEFAULT '',
                price_per_action REAL NOT NULL,
                worker_reward REAL NOT NULL,
                total_qty INTEGER NOT NULL,
                completed_qty INTEGER DEFAULT 0,
                budget_locked REAL DEFAULT 0.0,
                status TEXT DEFAULT 'active',
                announced_in_feed INTEGER DEFAULT 0,
                is_demo INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reward REAL NOT NULL,
                owner_profit REAL DEFAULT 0.0,
                partner_paid REAL DEFAULT 0.0,
                hold_until TEXT DEFAULT NULL,
                status TEXT DEFAULT 'paid',
                created_at TEXT NOT NULL,
                UNIQUE(campaign_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS partner_accruals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                level INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                amount REAL NOT NULL,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vouchers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                creator_id INTEGER NOT NULL,
                amount_per_use REAL NOT NULL,
                max_uses INTEGER NOT NULL,
                used_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS voucher_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(voucher_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                method TEXT NOT NULL,
                amount_rub REAL NOT NULL,
                fee_rub REAL DEFAULT 0.0,
                net_rub REAL NOT NULL,
                stars_amount INTEGER DEFAULT 0,
                check_amount_rub REAL DEFAULT 0.0,
                requisites TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                is_demo INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS platform_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                gross_amount REAL NOT NULL,
                owner_profit REAL NOT NULL,
                partner_payout REAL DEFAULT 0.0,
                worker_payout REAL DEFAULT 0.0,
                note TEXT DEFAULT '',
                is_demo INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )

        # Заполняем базовые настройки, если их ещё нет
        for k, v in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )

        env_cfg = get_env_config()
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('sbp_phone', ?)",
            (env_cfg["sbp_phone"],),
        )
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('sbp_bank', ?)",
            (env_cfg["sbp_bank"],),
        )
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('sbp_recipient', ?)",
            (env_cfg["sbp_recipient"],),
        )

        await db.commit()

        if seed_demo:
            cur = await db.execute("SELECT COUNT(*) as cnt FROM users")
            row = await cur.fetchone()
            if row["cnt"] == 0:
                await _seed_demo_data(db)
    finally:
        await db.close()


async def _seed_demo_data(db: aiosqlite.Connection) -> None:
    """Создаёт наглядные стартовые данные для тестирования всех функций в 1 клик."""
    ts = now_iso()
    hold_ts = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    # 1. Пользователи (админ/владелец + рекламодатели + 3 уровня партнёрской сети + тестовый аккаунт симулятора)
    demo_users = [
        # tg_id, username, full_name, bal_earn, bal_adv, ref_id, rank, tot_earn, ref_earn, ad_spent, tasks, refs_l1, vip
        (100000001, "owner_admin", "Владелец Платформы", 1450.0, 5000.0, None, "Амбассадор", 4820.0, 3150.0, 1200.0, 12, 14, 1),
        (777000111, "demo_partner", "Алексей (Тест-Аккаунт)", 245.50, 650.0, 100000001, "Актив", 680.50, 312.0, 850.0, 28, 12, 0),
        (200000002, "stavropol_news", "Ставрополь Live (Рекламодатель)", 40.0, 2400.0, 777000111, "Старт", 40.0, 0.0, 6800.0, 3, 0, 0),
        (200000003, "crypto_maxim", "Максим (Лидер 1-й линии)", 890.0, 300.0, 777000111, "Лидер", 2340.0, 1420.0, 500.0, 64, 53, 1),
        (200000004, "elena_smm", "Елена SMM (2-я линия)", 315.0, 1100.0, 200000003, "Актив", 790.0, 210.0, 2100.0, 41, 11, 0),
        (200000005, "dmitry_work", "Дмитрий (3-я линия)", 128.0, 0.0, 200000004, "Старт", 228.0, 18.0, 0.0, 52, 2, 0),
    ]
    for u in demo_users:
        await db.execute(
            """
            INSERT OR IGNORE INTO users (
                tg_id, username, full_name, balance_earn, balance_adv, referrer_id,
                partner_rank, total_earned, ref_earned, ad_spent, tasks_completed,
                referrals_l1, is_vip, is_demo, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (*u, ts),
        )

    # 2. Активные рекламные кампании всех форматов
    demo_campaigns = [
        # owner_id, type, title, desc, url, channel_username, price, reward, total, done, locked, status
        (
            200000002,
            "channel_sub",
            "Новости и вакансии Ставрополя 26",
            "Подпишитесь на городской канал новостей и горячих вакансий. Не отписывайтесь 7 дней!",
            "https://t.me/stavropol_live_demo",
            "@stavropol_live_demo",
            4.00,
            2.40,
            500,
            184,
            1264.0,
            "active",
        ),
        (
            200000004,
            "channel_sub",
            "Удалёнка и Фриланс с нуля",
            "Ежедневные подборки подработок и заказов без опыта. Автопроверка подписки.",
            "https://t.me/freelance_start_demo",
            "@freelance_start_demo",
            3.50,
            2.10,
            300,
            92,
            728.0,
            "active",
        ),
        (
            200000002,
            "post_view",
            "Просмотр закрепа: Скидки 30% на услуги",
            "Откройте пост, прочитайте условия акции (10 секунд) и нажмите кнопку подтверждения.",
            "https://t.me/stavropol_live_demo/105",
            "",
            1.50,
            0.90,
            1000,
            412,
            882.0,
            "active",
        ),
        (
            200000004,
            "bot_start",
            "Запуск полезного AI-бота помощника",
            "Перейдите в партнёрского бота, нажмите /start и вернитесь за мгновенной выплатой.",
            "https://t.me/ai_helper_demo_bot?start=adpartner",
            "",
            4.50,
            2.70,
            200,
            65,
            607.50,
            "active",
        ),
        (
            200000002,
            "sponsor_op",
            "🔥 Спонсор ОП: Главный канал скидок и работы",
            "Обязательная подписка спонсора перед доступом к заданиям (максимальная конверсия).",
            "https://t.me/sponsor_vip_demo",
            "@sponsor_vip_demo",
            6.00,
            0.00,
            300,
            118,
            1092.0,
            "active",
        ),
        (
            200000004,
            "native_ad",
            "💎 Нужны клиенты из Telegram? Запусти рекламу от 150 ₽ прямо в этом боте!",
            "Нативный рекламный блок внизу каждого сообщения меню",
            "https://t.me/elena_smm_demo",
            "",
            0.50,
            0.00,
            2000,
            740,
            630.0,
            "active",
        ),
    ]
    for c in demo_campaigns:
        await db.execute(
            """
            INSERT INTO campaigns (
                owner_id, type, title, description, target_url, channel_username,
                price_per_action, worker_reward, total_qty, completed_qty,
                budget_locked, status, announced_in_feed, is_demo, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?)
            """,
            (*c, ts),
        )

    # 3. Вирусный партнёрский чек (ваучер)
    await db.execute(
        """
        INSERT OR IGNORE INTO vouchers (code, creator_id, amount_per_use, max_uses, used_count, status, created_at)
        VALUES ('BONUS2026', 777000111, 3.00, 50, 14, 'active', ?)
        """,
        (ts,),
    )

    # 4. Примеры начислений по 3-уровневой партнёрке
    accruals = [
        (200000002, 777000111, 1, "ad_deposit", 250.00, "10% с пополнения рекламы @stavropol_news (2 500 ₽)"),
        (200000003, 777000111, 1, "task", 38.40, "18% с выполненных заданий реферала 1-го ур."),
        (200000004, 777000111, 2, "ad_deposit", 63.00, "3% с рекламы 2-го ур. @elena_smm"),
        (200000005, 777000111, 3, "task", 6.80, "2% с заданий реферала 3-го ур."),
    ]
    for a in accruals:
        await db.execute(
            """
            INSERT INTO partner_accruals (from_user_id, to_user_id, level, source_type, amount, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (*a, ts),
        )

    # 5. Примеры заявок СБП и автоплатежей Telegram Stars
    demo_payments = [
        (200000002, "deposit", "stars", 750.0, 0.0, 750.0, 500, 0.0, "Telegram Stars (500 ⭐)", "approved"),
        (200000004, "deposit", "sbp", 1000.0, 0.0, 1004.0, 0, 1004.0, "Перевод СБП (проверочная сумма 1004 ₽)", "pending"),
        (200000003, "withdraw", "sbp", 500.0, 25.0, 475.0, 0, 0.0, "+7 (918) 555-12-34 — Т-Банк (Максим К.)", "pending"),
    ]
    for p in demo_payments:
        await db.execute(
            """
            INSERT INTO payments (
                user_id, direction, method, amount_rub, fee_rub, net_rub,
                stars_amount, check_amount_rub, requisites, status, is_demo, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (*p, ts),
        )

    # 6. Примеры записей в кассе прибыли владельца (platform_ledger)
    ledger_rows = [
        ("task_margin", 736.0, 228.16, 66.24, 441.60, "Комиссия платформы со 184 подписок (@stavropol_live_demo)"),
        ("sponsor_op", 708.0, 637.20, 70.80, 0.00, "Доход со слота Спонсорской ОП (118 подписок)"),
        ("native_ads", 370.0, 358.90, 11.10, 0.00, "Авто-показы нативной рекламы в меню (740 показов)"),
        ("vip_sale", 390.0, 351.00, 39.00, 0.00, "Продажа статуса VIP-Партнёр через Telegram Stars"),
        ("withdraw_fee", 600.0, 30.00, 0.00, 570.00, "Комиссия 5% с выводов средств по СБП"),
    ]
    for l in ledger_rows:
        await db.execute(
            """
            INSERT INTO platform_ledger (
                event_type, gross_amount, owner_profit, partner_payout, worker_payout, note, is_demo, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (*l, ts),
        )

    # Одно выполненное задание на холде для наглядности
    await db.execute(
        """
        INSERT OR IGNORE INTO task_completions (campaign_id, user_id, reward, owner_profit, partner_paid, hold_until, status, created_at)
        VALUES (1, 200000005, 2.40, 1.12, 0.48, ?, 'paid', ?)
        """,
        (hold_ts, ts),
    )

    await db.commit()
