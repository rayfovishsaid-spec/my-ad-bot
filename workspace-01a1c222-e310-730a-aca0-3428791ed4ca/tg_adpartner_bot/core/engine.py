import random
import string
from datetime import datetime, timedelta, timezone
from core.config import get_env_config
from core.database import get_db, now_iso

RANK_THRESHOLDS = [
    ("Амбассадор", 200, 10.0, 3.0, 2.0),  # (название, мин. рефералов L1, бонус к L1%, L2%, L3%)
    ("Лидер", 50, 7.0, 2.0, 1.0),
    ("Актив", 10, 3.0, 1.0, 0.0),
    ("Старт", 0, 0.0, 0.0, 0.0),
]

CAMPAIGN_TYPE_LABELS = {
    "channel_sub": "📢 Подписка на канал / чат",
    "post_view": "👁 Просмотр поста",
    "bot_start": "🤖 Переход в бота / сайт",
    "sponsor_op": "🔒 Слот ОП (Обязательная подписка)",
    "native_ad": "🎯 Авто-показ под меню бота",
    "broadcast": "🚀 Авто-рассылка по базе",
}


async def get_settings() -> dict:
    db = await get_db()
    try:
        cur = await db.execute("SELECT key, value FROM settings")
        rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        await db.close()


async def update_settings(updates: dict) -> dict:
    db = await get_db()
    try:
        for k, v in updates.items():
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(k), str(v).strip()),
            )
        await db.commit()
    finally:
        await db.close()
    return await get_settings()


def _calc_rank_name(refs_l1: int, is_vip: int) -> str:
    if is_vip:
        return "Амбассадор"
    for name, threshold, _, _, _ in RANK_THRESHOLDS:
        if refs_l1 >= threshold:
            return name
    return "Старт"


def compute_partner_rates(user_row: dict, settings: dict) -> tuple[float, float, float]:
    base_l1 = float(settings.get("ref_task_l1", 15))
    base_l2 = float(settings.get("ref_task_l2", 5))
    base_l3 = float(settings.get("ref_task_l3", 2))
    rank = user_row.get("partner_rank") or "Старт"
    if user_row.get("is_vip"):
        rank = "Амбассадор"
    for r_name, _, b1, b2, b3 in RANK_THRESHOLDS:
        if r_name == rank:
            return (base_l1 + b1, base_l2 + b2, base_l3 + b3)
    return (base_l1, base_l2, base_l3)


async def ensure_user(
    tg_id: int,
    username: str = "",
    full_name: str = "Пользователь",
    referrer_id: int | None = None,
) -> tuple[dict, bool]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        if row:
            if username or full_name:
                await db.execute(
                    "UPDATE users SET username = COALESCE(NULLIF(?, ''), username), "
                    "full_name = COALESCE(NULLIF(?, ''), full_name) WHERE tg_id = ?",
                    (username or "", full_name or "", tg_id),
                )
                await db.commit()
                cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
                row = await cur.fetchone()
            return dict(row), False

        valid_ref = None
        if referrer_id and referrer_id != tg_id:
            rcur = await db.execute("SELECT tg_id, referrals_l1, is_vip FROM users WHERE tg_id = ?", (referrer_id,))
            rrow = await rcur.fetchone()
            if rrow:
                valid_ref = referrer_id
                new_l1 = int(rrow["referrals_l1"]) + 1
                new_rank = _calc_rank_name(new_l1, int(rrow["is_vip"]))
                await db.execute(
                    "UPDATE users SET referrals_l1 = ?, partner_rank = ? WHERE tg_id = ?",
                    (new_l1, new_rank, valid_ref),
                )

        ts = now_iso()
        await db.execute(
            """
            INSERT INTO users (tg_id, username, full_name, referrer_id, partner_rank, created_at)
            VALUES (?, ?, ?, ?, 'Старт', ?)
            """,
            (tg_id, username or "", full_name or "Пользователь", valid_ref, ts),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        created = await cur.fetchone()
        return dict(created), True
    finally:
        await db.close()


async def get_user(tg_id: int) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_mandatory_sponsors(user_id: int) -> list[dict]:
    """Возвращает активные каналы Обязательной Подписки (ОП), на которые юзер ещё не подписался."""
    db = await get_db()
    try:
        cur = await db.execute(
            """
            SELECT c.* FROM campaigns c
            WHERE c.type = 'sponsor_op'
              AND c.status = 'active'
              AND c.completed_qty < c.total_qty
              AND c.owner_id != ?
              AND NOT EXISTS (
                  SELECT 1 FROM task_completions tc
                  WHERE tc.campaign_id = c.id AND tc.user_id = ?
              )
            ORDER BY c.price_per_action DESC, c.id ASC
            LIMIT 4
            """,
            (user_id, user_id),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def complete_sponsor_op(user_id: int, campaign_id: int) -> bool:
    """Фиксирует прохождение обязательной подписки (100% доход платформы с вычетом реф. кэшбэка)."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM campaigns WHERE id = ? AND type = 'sponsor_op' AND status = 'active'",
            (campaign_id,),
        )
        camp = await cur.fetchone()
        if not camp or camp["completed_qty"] >= camp["total_qty"]:
            return False

        chk = await db.execute(
            "SELECT id FROM task_completions WHERE campaign_id = ? AND user_id = ?",
            (campaign_id, user_id),
        )
        if await chk.fetchone():
            return True

        ts = now_iso()
        price = float(camp["price_per_action"])
        new_done = int(camp["completed_qty"]) + 1
        new_status = "completed" if new_done >= int(camp["total_qty"]) else "active"

        await db.execute(
            """
            INSERT INTO task_completions (campaign_id, user_id, reward, owner_profit, partner_paid, status, created_at)
            VALUES (?, ?, 0.0, ?, 0.0, 'paid', ?)
            """,
            (campaign_id, user_id, price, ts),
        )
        await db.execute(
            "UPDATE campaigns SET completed_qty = ?, budget_locked = MAX(0, budget_locked - ?), status = ? WHERE id = ?",
            (new_done, price, new_status, campaign_id),
        )
        await db.execute(
            """
            INSERT INTO platform_ledger (event_type, gross_amount, owner_profit, partner_payout, worker_payout, note, created_at)
            VALUES ('sponsor_op', ?, ?, 0.0, 0.0, ?, ?)
            """,
            (price, price, f"Слот ОП #{campaign_id} ({camp['title'][:35]})", ts),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def pick_native_ad(exclude_user_id: int | None = None) -> dict | None:
    """Выбирает нативный рекламный блок для автопоказа внизу меню и списывает 1 показ."""
    db = await get_db()
    try:
        cur = await db.execute(
            """
            SELECT * FROM campaigns
            WHERE type = 'native_ad' AND status = 'active' AND completed_qty < total_qty
            ORDER BY RANDOM() LIMIT 1
            """
        )
        ad = await cur.fetchone()
        if not ad:
            return None

        price = float(ad["price_per_action"])
        new_done = int(ad["completed_qty"]) + 1
        new_status = "completed" if new_done >= int(ad["total_qty"]) else "active"
        ts = now_iso()

        await db.execute(
            "UPDATE campaigns SET completed_qty = ?, budget_locked = MAX(0, budget_locked - ?), status = ? WHERE id = ?",
            (new_done, price, new_status, ad["id"]),
        )
        await db.execute(
            """
            INSERT INTO platform_ledger (event_type, gross_amount, owner_profit, partner_payout, worker_payout, note, created_at)
            VALUES ('native_ads', ?, ?, 0.0, 0.0, ?, ?)
            """,
            (price, price, f"Авто-показ #{ad['id']}", ts),
        )
        await db.commit()
        return dict(ad)
    finally:
        await db.close()


async def list_available_tasks(user_id: int, c_type: str | None = None) -> list[dict]:
    db = await get_db()
    try:
        params = [user_id, user_id]
        type_sql = "AND c.type IN ('channel_sub', 'post_view', 'bot_start')"
        if c_type in ("channel_sub", "post_view", "bot_start"):
            type_sql = "AND c.type = ?"
            params.insert(0, c_type)
            # Пересобираем порядок параметров под SQL ниже
            cur = await db.execute(
                """
                SELECT c.* FROM campaigns c
                WHERE c.status = 'active'
                  AND c.completed_qty < c.total_qty
                  AND c.type = ?
                  AND c.owner_id != ?
                  AND NOT EXISTS (
                      SELECT 1 FROM task_completions tc
                      WHERE tc.campaign_id = c.id AND tc.user_id = ?
                  )
                ORDER BY c.worker_reward DESC, c.id DESC
                """,
                (c_type, user_id, user_id),
            )
            return [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            f"""
            SELECT c.* FROM campaigns c
            WHERE c.status = 'active'
              AND c.completed_qty < c.total_qty
              {type_sql}
              AND c.owner_id != ?
              AND NOT EXISTS (
                  SELECT 1 FROM task_completions tc
                  WHERE tc.campaign_id = c.id AND tc.user_id = ?
              )
            ORDER BY c.worker_reward DESC, c.id DESC
            """,
            (user_id, user_id),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def complete_task(user_id: int, campaign_id: int) -> dict:
    """Начисляет оплату за задание, распределяет 3 уровня партнёрки и фиксирует чистую прибыль владельца."""
    settings = await get_settings()
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
        camp = await cur.fetchone()
        if not camp or camp["status"] != "active" or camp["completed_qty"] >= camp["total_qty"]:
            return {"ok": False, "error": "Задание уже завершено или недоступно."}
        if int(camp["owner_id"]) == int(user_id):
            return {"ok": False, "error": "Нельзя выполнять собственное задание."}

        dup = await db.execute(
            "SELECT id FROM task_completions WHERE campaign_id = ? AND user_id = ?",
            (campaign_id, user_id),
        )
        if await dup.fetchone():
            return {"ok": False, "error": "Вы уже выполняли это задание и получили оплату."}

        ucur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (user_id,))
        worker = await ucur.fetchone()
        if not worker:
            return {"ok": False, "error": "Пользователь не найден."}

        price = float(camp["price_per_action"])
        base_reward = float(camp["worker_reward"])
        # VIP-партнёр получает +15% к награде из бонусного пула, но не выше 75% цены рекламодателя
        worker_reward = round(min(price * 0.75, base_reward * (1.15 if worker["is_vip"] else 1.0)), 2)

        # Распределение 3 уровней партнёрской сети
        partner_paid_total = 0.0
        partner_payouts = []
        curr_ref_id = worker["referrer_id"]
        ts = now_iso()

        for level in (1, 2, 3):
            if not curr_ref_id:
                break
            rcur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (curr_ref_id,))
            ref_user = await rcur.fetchone()
            if not ref_user:
                break
            r_dict = dict(ref_user)
            l1_pct, l2_pct, l3_pct = compute_partner_rates(r_dict, settings)
            pct = {1: l1_pct, 2: l2_pct, 3: l3_pct}[level]
            bonus = round(worker_reward * (pct / 100.0), 2)
            # Гарантия положительной маржи платформы
            if worker_reward + partner_paid_total + bonus <= price * 0.90 and bonus >= 0.01:
                partner_paid_total = round(partner_paid_total + bonus, 2)
                await db.execute(
                    """
                    UPDATE users
                    SET balance_earn = ROUND(balance_earn + ?, 2),
                        total_earned = ROUND(total_earned + ?, 2),
                        ref_earned = ROUND(ref_earned + ?, 2)
                    WHERE tg_id = ?
                    """,
                    (bonus, bonus, bonus, r_dict["tg_id"]),
                )
                await db.execute(
                    """
                    INSERT INTO partner_accruals (from_user_id, to_user_id, level, source_type, amount, note, created_at)
                    VALUES (?, ?, ?, 'task', ?, ?, ?)
                    """,
                    (
                        user_id,
                        r_dict["tg_id"],
                        level,
                        bonus,
                        f"Ур.{level} ({pct:.0f}%) за задание #{campaign_id}",
                        ts,
                    ),
                )
                partner_payouts.append({"tg_id": r_dict["tg_id"], "level": level, "amount": bonus})
            curr_ref_id = ref_user["referrer_id"]

        owner_profit = round(max(0.0, price - worker_reward - partner_paid_total), 2)
        hold_days = int(settings.get("unsub_hold_days", 7))
        hold_until = None
        if camp["type"] == "channel_sub":
            hold_until = (datetime.now(timezone.utc) + timedelta(days=hold_days)).strftime("%Y-%m-%d %H:%M:%S")

        # Обновляем баланс исполнителя
        await db.execute(
            """
            UPDATE users
            SET balance_earn = ROUND(balance_earn + ?, 2),
                total_earned = ROUND(total_earned + ?, 2),
                tasks_completed = tasks_completed + 1
            WHERE tg_id = ?
            """,
            (worker_reward, worker_reward, user_id),
        )

        # Записываем выполнение
        await db.execute(
            """
            INSERT INTO task_completions (
                campaign_id, user_id, reward, owner_profit, partner_paid, hold_until, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'paid', ?)
            """,
            (campaign_id, user_id, worker_reward, owner_profit, partner_paid_total, hold_until, ts),
        )

        new_done = int(camp["completed_qty"]) + 1
        new_status = "completed" if new_done >= int(camp["total_qty"]) else "active"
        await db.execute(
            "UPDATE campaigns SET completed_qty = ?, budget_locked = ROUND(MAX(0, budget_locked - ?), 2), status = ? WHERE id = ?",
            (new_done, price, new_status, campaign_id),
        )

        await db.execute(
            """
            INSERT INTO platform_ledger (
                event_type, gross_amount, owner_profit, partner_payout, worker_payout, note, created_at
            ) VALUES ('task_margin', ?, ?, ?, ?, ?, ?)
            """,
            (
                price,
                owner_profit,
                partner_paid_total,
                worker_reward,
                f"Задание #{campaign_id} ({camp['title'][:32]})",
                ts,
            ),
        )

        await db.commit()
        return {
            "ok": True,
            "worker_reward": worker_reward,
            "owner_profit": owner_profit,
            "partner_paid": partner_paid_total,
            "partner_payouts": partner_payouts,
            "hold_days": hold_days if hold_until else 0,
            "campaign_title": camp["title"],
        }
    finally:
        await db.close()


async def penalize_unsubscribed_task(completion_id: int) -> dict | None:
    """Штрафует исполнителя при ранней отписке от канала и бесплатно возвращает слот рекламодателю."""
    db = await get_db()
    try:
        cur = await db.execute(
            """
            SELECT tc.*, c.title, c.channel_username
            FROM task_completions tc
            JOIN campaigns c ON c.id = tc.campaign_id
            WHERE tc.id = ? AND tc.status = 'paid'
            """,
            (completion_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None

        reward = float(row["reward"])
        await db.execute(
            "UPDATE task_completions SET status = 'penalized_unsub' WHERE id = ?",
            (completion_id,),
        )
        await db.execute(
            "UPDATE users SET balance_earn = ROUND(balance_earn - ?, 2) WHERE tg_id = ?",
            (reward, row["user_id"]),
        )
        await db.execute(
            """
            UPDATE campaigns
            SET completed_qty = MAX(0, completed_qty - 1),
                status = CASE WHEN status = 'completed' THEN 'active' ELSE status END
            WHERE id = ?
            """,
            (row["campaign_id"],),
        )
        await db.commit()
        return {
            "user_id": row["user_id"],
            "reward": reward,
            "title": row["title"],
            "channel": row["channel_username"],
        }
    finally:
        await db.close()


async def claim_daily_bonus(user_id: int) -> dict:
    settings = await get_settings()
    bonus = float(settings.get("daily_bonus_rub", 1.0))
    db = await get_db()
    try:
        cur = await db.execute("SELECT last_bonus_at FROM users WHERE tg_id = ?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return {"ok": False, "error": "Пользователь не найден."}

        now = datetime.now(timezone.utc)
        if row["last_bonus_at"]:
            last_dt = datetime.strptime(row["last_bonus_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            diff = now - last_dt
            if diff < timedelta(hours=24):
                rem = timedelta(hours=24) - diff
                hours = int(rem.total_seconds() // 3600)
                mins = int((rem.total_seconds() % 3600) // 60)
                return {"ok": False, "error": f"Бонус уже получен! Следующий будет доступен через {hours} ч. {mins} мин."}

        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            """
            UPDATE users
            SET balance_earn = ROUND(balance_earn + ?, 2),
                total_earned = ROUND(total_earned + ?, 2),
                last_bonus_at = ?
            WHERE tg_id = ?
            """,
            (bonus, bonus, ts, user_id),
        )
        await db.commit()
        return {"ok": True, "bonus": bonus}
    finally:
        await db.close()


async def create_campaign(
    owner_id: int,
    c_type: str,
    title: str,
    description: str,
    target_url: str,
    channel_username: str,
    price_per_action: float,
    total_qty: int,
) -> dict:
    settings = await get_settings()
    if c_type not in CAMPAIGN_TYPE_LABELS:
        return {"ok": False, "error": "Неизвестный формат рекламы."}

    min_key = f"min_price_{c_type}"
    min_price = float(settings.get(min_key, 1.0))
    if price_per_action < min_price:
        return {"ok": False, "error": f"Минимальная цена для этого формата: {min_price:.2f} ₽."}
    if total_qty < 5:
        return {"ok": False, "error": "Минимальный объём заказа — 5 выполнений/показов."}

    total_cost = round(price_per_action * total_qty, 2)
    fee_pct = float(settings.get("platform_fee_pct", 30))

    # Для форматов спонсора ОП, нативной рекламы и рассылок исполнитель получает 0, доход идёт платформе
    if c_type in ("sponsor_op", "native_ad", "broadcast"):
        worker_reward = 0.0
    else:
        # Оставляем запас под комиссию платформы (fee_pct) и пул реферальной сети (~10%)
        worker_share = max(0.45, min(0.80, (100.0 - fee_pct - 10.0) / 100.0))
        worker_reward = round(price_per_action * worker_share, 2)

    clean_channel = channel_username.strip()
    if clean_channel and not clean_channel.startswith("@") and not clean_channel.startswith("-100"):
        if "t.me/" in clean_channel:
            slug = clean_channel.split("t.me/")[-1].split("/")[0].split("?")[0]
            clean_channel = f"@{slug}"
        else:
            clean_channel = f"@{clean_channel}"

    db = await get_db()
    try:
        cur = await db.execute("SELECT balance_adv FROM users WHERE tg_id = ?", (owner_id,))
        u = await cur.fetchone()
        if not u or float(u["balance_adv"]) < total_cost:
            have = float(u["balance_adv"]) if u else 0.0
            return {
                "ok": False,
                "error": f"Недостаточно средств на рекламном балансе. Нужно {total_cost:.2f} ₽, доступно {have:.2f} ₽.",
            }

        ts = now_iso()
        await db.execute(
            """
            UPDATE users
            SET balance_adv = ROUND(balance_adv - ?, 2),
                ad_spent = ROUND(ad_spent + ?, 2)
            WHERE tg_id = ?
            """,
            (total_cost, total_cost, owner_id),
        )
        ins = await db.execute(
            """
            INSERT INTO campaigns (
                owner_id, type, title, description, target_url, channel_username,
                price_per_action, worker_reward, total_qty, completed_qty,
                budget_locked, status, announced_in_feed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'active', 0, ?)
            """,
            (
                owner_id,
                c_type,
                title.strip()[:80],
                description.strip()[:250],
                target_url.strip(),
                clean_channel,
                round(price_per_action, 2),
                worker_reward,
                int(total_qty),
                total_cost,
                ts,
            ),
        )
        camp_id = ins.lastrowid

        # Если это рассылка — ставим её в очередь воркера рассылок (или логируем доход сразу)
        if c_type == "broadcast":
            await db.execute(
                """
                INSERT INTO platform_ledger (event_type, gross_amount, owner_profit, partner_payout, worker_payout, note, created_at)
                VALUES ('broadcast', ?, ?, 0.0, 0.0, ?, ?)
                """,
                (total_cost, total_cost, f"Заказ авто-рассылки #{camp_id} ({total_qty} получ.)", ts),
            )

        await db.commit()
        return {
            "ok": True,
            "campaign_id": camp_id,
            "total_cost": total_cost,
            "worker_reward": worker_reward,
        }
    finally:
        await db.close()


async def create_voucher(creator_id: int, amount_per_use: float, max_uses: int) -> dict:
    """Создаёт вирусный денежный чек для бесплатного привлечения рефералов в партнёрскую сеть."""
    if amount_per_use < 1.0 or max_uses < 1:
        return {"ok": False, "error": "Минимум 1 ₽ на 1 активацию."}
    total_cost = round(amount_per_use * max_uses, 2)

    db = await get_db()
    try:
        cur = await db.execute("SELECT balance_earn, balance_adv FROM users WHERE tg_id = ?", (creator_id,))
        u = await cur.fetchone()
        if not u:
            return {"ok": False, "error": "Пользователь не найден."}

        # Можно списать с основного баланса заработка или рекламного баланса
        if float(u["balance_earn"]) >= total_cost:
            await db.execute(
                "UPDATE users SET balance_earn = ROUND(balance_earn - ?, 2) WHERE tg_id = ?",
                (total_cost, creator_id),
            )
        elif float(u["balance_adv"]) >= total_cost:
            await db.execute(
                "UPDATE users SET balance_adv = ROUND(balance_adv - ?, 2) WHERE tg_id = ?",
                (total_cost, creator_id),
            )
        else:
            return {
                "ok": False,
                "error": f"Недостаточно средств для создания чека на {total_cost:.2f} ₽.",
            }

        code = "CHK" + "".join(random.choices(string.ascii_uppercase + string.digits, k=7))
        await db.execute(
            """
            INSERT INTO vouchers (code, creator_id, amount_per_use, max_uses, used_count, status, created_at)
            VALUES (?, ?, ?, ?, 0, 'active', ?)
            """,
            (code, creator_id, round(amount_per_use, 2), int(max_uses), now_iso()),
        )
        await db.commit()
        env_cfg = get_env_config()
        link = f"https://t.me/{env_cfg['bot_username']}?start=chk_{code}"
        return {"ok": True, "code": code, "total_cost": total_cost, "deep_link": link}
    finally:
        await db.close()


async def claim_voucher(user_id: int, code: str) -> dict:
    clean_code = code.strip().upper().replace("CHK_", "")
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM vouchers WHERE UPPER(code) = ? AND status = 'active'", (clean_code,))
        v = await cur.fetchone()
        if not v or int(v["used_count"]) >= int(v["max_uses"]):
            return {"ok": False, "error": "Чек не найден или все активации уже разобрали."}
        if int(v["creator_id"]) == int(user_id):
            return {"ok": False, "error": "Нельзя активировать собственный чек."}

        dup = await db.execute(
            "SELECT id FROM voucher_claims WHERE voucher_id = ? AND user_id = ?",
            (v["id"], user_id),
        )
        if await dup.fetchone():
            return {"ok": False, "error": "Вы уже активировали этот чек."}

        amount = float(v["amount_per_use"])
        new_used = int(v["used_count"]) + 1
        new_status = "completed" if new_used >= int(v["max_uses"]) else "active"
        ts = now_iso()

        await db.execute(
            "INSERT INTO voucher_claims (voucher_id, user_id, created_at) VALUES (?, ?, ?)",
            (v["id"], user_id, ts),
        )
        await db.execute(
            "UPDATE vouchers SET used_count = ?, status = ? WHERE id = ?",
            (new_used, new_status, v["id"]),
        )
        await db.execute(
            """
            UPDATE users
            SET balance_earn = ROUND(balance_earn + ?, 2),
                total_earned = ROUND(total_earned + ?, 2)
            WHERE tg_id = ?
            """,
            (amount, amount, user_id),
        )

        # Если у пользователя ещё не было пригласителя — автоматически закрепляем за создателем чека!
        ucur = await db.execute("SELECT referrer_id FROM users WHERE tg_id = ?", (user_id,))
        urow = await ucur.fetchone()
        bound_partner = False
        if urow and urow["referrer_id"] is None:
            creator_id = int(v["creator_id"])
            await db.execute("UPDATE users SET referrer_id = ? WHERE tg_id = ?", (creator_id, user_id))
            ccur = await db.execute("SELECT referrals_l1, is_vip FROM users WHERE tg_id = ?", (creator_id,))
            crow = await ccur.fetchone()
            if crow:
                nl1 = int(crow["referrals_l1"]) + 1
                nrank = _calc_rank_name(nl1, int(crow["is_vip"]))
                await db.execute(
                    "UPDATE users SET referrals_l1 = ?, partner_rank = ? WHERE tg_id = ?",
                    (nl1, nrank, creator_id),
                )
                bound_partner = True

        await db.commit()
        return {"ok": True, "amount": amount, "bound_partner": bound_partner, "creator_id": v["creator_id"]}
    finally:
        await db.close()


async def reinvest_earn_to_adv(user_id: int, amount: float) -> dict:
    """Перевод заработанных средств на рекламный баланс с бонусом +10%."""
    if amount < 10:
        return {"ok": False, "error": "Минимальная сумма перевода на рекламу — 10 ₽."}
    settings = await get_settings()
    bonus_pct = float(settings.get("reinvest_bonus_pct", 10))
    credited = round(amount * (1.0 + bonus_pct / 100.0), 2)

    db = await get_db()
    try:
        cur = await db.execute("SELECT balance_earn FROM users WHERE tg_id = ?", (user_id,))
        u = await cur.fetchone()
        if not u or float(u["balance_earn"]) < amount:
            return {"ok": False, "error": "Недостаточно средств на балансе заработка."}

        await db.execute(
            """
            UPDATE users
            SET balance_earn = ROUND(balance_earn - ?, 2),
                balance_adv = ROUND(balance_adv + ?, 2)
            WHERE tg_id = ?
            """,
            (amount, credited, user_id),
        )
        await db.commit()
        return {"ok": True, "debited": amount, "credited": credited, "bonus_pct": bonus_pct}
    finally:
        await db.close()


async def buy_vip_status(user_id: int) -> dict:
    settings = await get_settings()
    price = float(settings.get("vip_price_rub", 390))
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (user_id,))
        u = await cur.fetchone()
        if not u:
            return {"ok": False, "error": "Пользователь не найден."}
        if u["is_vip"]:
            return {"ok": False, "error": "У вас уже активирован статус VIP-Партнёр (Амбассадор)!"}

        if float(u["balance_adv"]) >= price:
            col = "balance_adv"
        elif float(u["balance_earn"]) >= price:
            col = "balance_earn"
        else:
            return {
                "ok": False,
                "error": f"Для покупки VIP нужно {price:.0f} ₽ на рекламном или основном балансе.",
            }

        ts = now_iso()
        await db.execute(
            f"UPDATE users SET {col} = ROUND({col} - ?, 2), is_vip = 1, partner_rank = 'Амбассадор' WHERE tg_id = ?",
            (price, user_id),
        )

        # 15% рефереру 1-го уровня с продажи VIP, 85% — чистая прибыль владельца
        partner_cut = 0.0
        if u["referrer_id"]:
            partner_cut = round(price * 0.15, 2)
            await db.execute(
                """
                UPDATE users
                SET balance_earn = ROUND(balance_earn + ?, 2),
                    total_earned = ROUND(total_earned + ?, 2),
                    ref_earned = ROUND(ref_earned + ?, 2)
                WHERE tg_id = ?
                """,
                (partner_cut, partner_cut, partner_cut, u["referrer_id"]),
            )
            await db.execute(
                """
                INSERT INTO partner_accruals (from_user_id, to_user_id, level, source_type, amount, note, created_at)
                VALUES (?, ?, 1, 'vip_sale', ?, '15% бонус за покупку VIP рефералом', ?)
                """,
                (user_id, u["referrer_id"], partner_cut, ts),
            )

        owner_profit = round(price - partner_cut, 2)
        await db.execute(
            """
            INSERT INTO platform_ledger (event_type, gross_amount, owner_profit, partner_payout, worker_payout, note, created_at)
            VALUES ('vip_sale', ?, ?, ?, 0.0, ?, ?)
            """,
            (price, owner_profit, partner_cut, f"Покупка VIP пользователем ID {user_id}", ts),
        )
        await db.commit()
        return {"ok": True, "price": price, "owner_profit": owner_profit}
    finally:
        await db.close()


async def _distribute_adv_referral_bonus(db, user_id: int, deposit_rub: float, settings: dict, ts: str) -> list[dict]:
    """Начисляет 3-уровневый партнёрский % (10% / 3% / 1%) с пополнений рекламного бюджета."""
    cur = await db.execute("SELECT referrer_id FROM users WHERE tg_id = ?", (user_id,))
    u = await cur.fetchone()
    if not u or not u["referrer_id"]:
        return []

    rates = {
        1: float(settings.get("ref_adv_l1", 10)),
        2: float(settings.get("ref_adv_l2", 3)),
        3: float(settings.get("ref_adv_l3", 1)),
    }
    curr_ref = u["referrer_id"]
    paid = []
    for lvl in (1, 2, 3):
        if not curr_ref:
            break
        rcur = await db.execute("SELECT tg_id, referrer_id FROM users WHERE tg_id = ?", (curr_ref,))
        r = await rcur.fetchone()
        if not r:
            break
        pct = rates[lvl]
        bonus = round(deposit_rub * (pct / 100.0), 2)
        if bonus >= 0.01:
            await db.execute(
                """
                UPDATE users
                SET balance_earn = ROUND(balance_earn + ?, 2),
                    total_earned = ROUND(total_earned + ?, 2),
                    ref_earned = ROUND(ref_earned + ?, 2)
                WHERE tg_id = ?
                """,
                (bonus, bonus, bonus, r["tg_id"]),
            )
            await db.execute(
                """
                INSERT INTO partner_accruals (from_user_id, to_user_id, level, source_type, amount, note, created_at)
                VALUES (?, ?, ?, 'ad_deposit', ?, ?, ?)
                """,
                (user_id, r["tg_id"], lvl, bonus, f"Ур.{lvl} ({pct:.0f}%) с пополнения рекламы ({deposit_rub:.0f} ₽)", ts),
            )
            paid.append({"tg_id": r["tg_id"], "level": lvl, "amount": bonus})
        curr_ref = r["referrer_id"]
    return paid


async def credit_stars_deposit(user_id: int, stars_amount: int) -> dict:
    """Мгновенное автозачисление оплаты через встроенные Telegram Stars (XTR)."""
    settings = await get_settings()
    rate = float(settings.get("stars_rate_rub", 1.50))
    rub_amount = round(stars_amount * rate, 2)
    ts = now_iso()

    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET balance_adv = ROUND(balance_adv + ?, 2) WHERE tg_id = ?",
            (rub_amount, user_id),
        )
        await db.execute(
            """
            INSERT INTO payments (
                user_id, direction, method, amount_rub, fee_rub, net_rub,
                stars_amount, check_amount_rub, requisites, status, created_at
            ) VALUES (?, 'deposit', 'stars', ?, 0.0, ?, ?, 0.0, ?, 'approved', ?)
            """,
            (user_id, rub_amount, rub_amount, stars_amount, f"Автоплатёж Telegram Stars ({stars_amount} ⭐)", ts),
        )
        ref_paid = await _distribute_adv_referral_bonus(db, user_id, rub_amount, settings, ts)
        await db.commit()
        return {"ok": True, "rub_amount": rub_amount, "stars_amount": stars_amount, "ref_paid": ref_paid}
    finally:
        await db.close()


async def create_sbp_deposit_request(user_id: int, amount_rub: float) -> dict:
    if amount_rub < 100:
        return {"ok": False, "error": "Минимальная сумма пополнения через СБП — 100 ₽."}
    settings = await get_settings()
    # Уникальная надбавка +1..9 ₽, чтобы владелец сразу узнал перевод в банковском приложении
    unique_add = random.randint(1, 9)
    check_amount = round(amount_rub + unique_add, 2)
    ts = now_iso()

    db = await get_db()
    try:
        ins = await db.execute(
            """
            INSERT INTO payments (
                user_id, direction, method, amount_rub, fee_rub, net_rub,
                stars_amount, check_amount_rub, requisites, status, created_at
            ) VALUES (?, 'deposit', 'sbp', ?, 0.0, ?, 0, ?, ?, 'pending', ?)
            """,
            (
                user_id,
                amount_rub,
                check_amount,
                check_amount,
                f"СБП перевод на точную сумму {check_amount:.0f} ₽",
                ts,
            ),
        )
        pay_id = ins.lastrowid
        await db.commit()
        return {
            "ok": True,
            "payment_id": pay_id,
            "check_amount": check_amount,
            "sbp_phone": settings.get("sbp_phone", "+7 (900) 000-00-00"),
            "sbp_bank": settings.get("sbp_bank", "Т-Банк / Сбербанк"),
            "sbp_recipient": settings.get("sbp_recipient", "Получатель СБП"),
        }
    finally:
        await db.close()


async def create_sbp_withdraw_request(user_id: int, amount_rub: float, requisites: str) -> dict:
    settings = await get_settings()
    min_w = float(settings.get("min_withdraw_rub", 100))
    fee_pct = float(settings.get("withdraw_fee_pct", 5))
    if amount_rub < min_w:
        return {"ok": False, "error": f"Минимальная сумма вывода — {min_w:.0f} ₽."}
    if len(requisites.strip()) < 6:
        return {"ok": False, "error": "Укажите номер телефона и банк для СБП (например: +79991234567 Т-Банк)."}

    fee = round(amount_rub * (fee_pct / 100.0), 2)
    net = round(amount_rub - fee, 2)
    ts = now_iso()

    db = await get_db()
    try:
        cur = await db.execute("SELECT balance_earn FROM users WHERE tg_id = ?", (user_id,))
        u = await cur.fetchone()
        if not u or float(u["balance_earn"]) < amount_rub:
            return {"ok": False, "error": "Недостаточно средств на балансе заработка."}

        await db.execute(
            "UPDATE users SET balance_earn = ROUND(balance_earn - ?, 2) WHERE tg_id = ?",
            (amount_rub, user_id),
        )
        ins = await db.execute(
            """
            INSERT INTO payments (
                user_id, direction, method, amount_rub, fee_rub, net_rub,
                stars_amount, check_amount_rub, requisites, status, created_at
            ) VALUES (?, 'withdraw', 'sbp', ?, ?, ?, 0, 0.0, ?, 'pending', ?)
            """,
            (user_id, amount_rub, fee, net, requisites.strip()[:150], ts),
        )
        pay_id = ins.lastrowid
        await db.commit()
        return {"ok": True, "payment_id": pay_id, "amount_rub": amount_rub, "fee_rub": fee, "net_rub": net}
    finally:
        await db.close()


async def resolve_payment_request(payment_id: int, approve: bool) -> dict:
    """Обработка пополнения или вывода СБП в 1 клик администратором."""
    settings = await get_settings()
    ts = now_iso()
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
        p = await cur.fetchone()
        if not p:
            return {"ok": False, "error": "Заявка не найдена."}
        if p["status"] != "pending":
            return {"ok": False, "error": f"Заявка уже обработана ({p['status']})."}

        new_status = "approved" if approve else "rejected"
        await db.execute("UPDATE payments SET status = ? WHERE id = ?", (new_status, payment_id))

        ref_paid = []
        if p["direction"] == "deposit":
            if approve:
                credit = float(p["net_rub"])
                await db.execute(
                    "UPDATE users SET balance_adv = ROUND(balance_adv + ?, 2) WHERE tg_id = ?",
                    (credit, p["user_id"]),
                )
                ref_paid = await _distribute_adv_referral_bonus(db, int(p["user_id"]), credit, settings, ts)
        elif p["direction"] == "withdraw":
            if approve:
                fee = float(p["fee_rub"])
                if fee > 0:
                    await db.execute(
                        """
                        INSERT INTO platform_ledger (
                            event_type, gross_amount, owner_profit, partner_payout, worker_payout, note, created_at
                        ) VALUES ('withdraw_fee', ?, ?, 0.0, ?, ?, ?)
                        """,
                        (float(p["amount_rub"]), fee, float(p["net_rub"]), f"Комиссия с вывода СБП #{payment_id}", ts),
                    )
            else:
                # Возвращаем полную сумму обратно пользователю при отклонении вывода
                await db.execute(
                    "UPDATE users SET balance_earn = ROUND(balance_earn + ?, 2) WHERE tg_id = ?",
                    (float(p["amount_rub"]), p["user_id"]),
                )

        await db.commit()
        return {
            "ok": True,
            "payment": dict(p),
            "new_status": new_status,
            "ref_paid": ref_paid,
        }
    finally:
        await db.close()


async def get_partner_network_stats(user_id: int) -> dict:
    settings = await get_settings()
    env_cfg = get_env_config()
    db = await get_db()
    try:
        ucur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (user_id,))
        u = await ucur.fetchone()
        if not u:
            return {}
        u_dict = dict(u)

        # Считаем 1, 2 и 3 линии рефералов
        c1 = await db.execute("SELECT COUNT(*) AS cnt FROM users WHERE referrer_id = ?", (user_id,))
        l1_cnt = (await c1.fetchone())["cnt"]

        c2 = await db.execute(
            """
            SELECT COUNT(*) AS cnt FROM users
            WHERE referrer_id IN (SELECT tg_id FROM users WHERE referrer_id = ?)
            """,
            (user_id,),
        )
        l2_cnt = (await c2.fetchone())["cnt"]

        c3 = await db.execute(
            """
            SELECT COUNT(*) AS cnt FROM users
            WHERE referrer_id IN (
                SELECT tg_id FROM users
                WHERE referrer_id IN (SELECT tg_id FROM users WHERE referrer_id = ?)
            )
            """,
            (user_id,),
        )
        l3_cnt = (await c3.fetchone())["cnt"]

        acur = await db.execute(
            """
            SELECT level, COALESCE(SUM(amount), 0) AS total
            FROM partner_accruals WHERE to_user_id = ?
            GROUP BY level
            """,
            (user_id,),
        )
        by_lvl = {1: 0.0, 2: 0.0, 3: 0.0}
        for r in await acur.fetchall():
            by_lvl[int(r["level"])] = round(float(r["total"]), 2)

        recent_cur = await db.execute(
            """
            SELECT * FROM partner_accruals
            WHERE to_user_id = ?
            ORDER BY id DESC LIMIT 8
            """,
            (user_id,),
        )
        recent = [dict(r) for r in await recent_cur.fetchall()]

        vcur = await db.execute(
            "SELECT * FROM vouchers WHERE creator_id = ? ORDER BY id DESC LIMIT 5",
            (user_id,),
        )
        vouchers = [dict(r) for r in await vcur.fetchall()]

        l1_rate, l2_rate, l3_rate = compute_partner_rates(u_dict, settings)
        ref_link = f"https://t.me/{env_cfg['bot_username']}?start=ref_{user_id}"

        promo_templates = [
            {
                "target": "Для чатов подработки / студентов",
                "text": (
                    f"💸 Заработок в Telegram с телефона без вложений!\n"
                    f"Платит за простые подписки и просмотры постов (вывод на карту по СБП от {settings.get('min_withdraw_rub', '100')} ₽).\n"
                    f"Плюс 3-уровневая партнёрка до 25%!\n"
                    f"👉 Забрать бонус и начать: {ref_link}"
                ),
            },
            {
                "target": "Для админов ТГ-каналов и бизнеса (высокий чек!)",
                "text": (
                    f"🚀 Нужны живые подписчики и просмотры в Telegram-канал?\n"
                    f"В боте автопроверка подписки и контроль отписок 7 дней! Запуск рекламы за 1 минуту от 20 ₽.\n"
                    f"👉 Кабинет рекламодателя: {ref_link}"
                ),
            },
            {
                "target": "Для Shorts / Reels / TikTok / ВК Клипов",
                "text": (
                    f"Проверяю бота, который платит рубли на СБП за обычные подписки в ТГ 🔥 "
                    f"За 10 минут накапало на кофе, а с друзей идёт пассив с 3 уровней. Ссылка: {ref_link}"
                ),
            },
        ]

        return {
            "user": u_dict,
            "ref_link": ref_link,
            "counts": {"l1": l1_cnt, "l2": l2_cnt, "l3": l3_cnt, "total": l1_cnt + l2_cnt + l3_cnt},
            "earned_by_level": by_lvl,
            "rates": {
                "task_l1": l1_rate,
                "task_l2": l2_rate,
                "task_l3": l3_rate,
                "adv_l1": float(settings.get("ref_adv_l1", 10)),
                "adv_l2": float(settings.get("ref_adv_l2", 3)),
                "adv_l3": float(settings.get("ref_adv_l3", 1)),
            },
            "recent_accruals": recent,
            "vouchers": vouchers,
            "promo_templates": promo_templates,
        }
    finally:
        await db.close()


async def get_admin_dashboard() -> dict:
    settings = await get_settings()
    env_cfg = get_env_config()
    db = await get_db()
    try:
        u_stat = await (
            await db.execute(
                """
                SELECT
                    COUNT(*) AS users_count,
                    SUM(CASE WHEN is_vip = 1 THEN 1 ELSE 0 END) AS vip_count,
                    COALESCE(SUM(balance_earn), 0) AS total_user_earn_bal,
                    COALESCE(SUM(balance_adv), 0) AS total_user_adv_bal
                FROM users
                """
            )
        ).fetchone()

        l_stat = await (
            await db.execute(
                """
                SELECT
                    COALESCE(SUM(gross_amount), 0) AS gross_turnover,
                    COALESCE(SUM(owner_profit), 0) AS net_owner_profit,
                    COALESCE(SUM(partner_payout), 0) AS partner_paid,
                    COALESCE(SUM(worker_payout), 0) AS worker_paid
                FROM platform_ledger
                """
            )
        ).fetchone()

        by_source_cur = await db.execute(
            """
            SELECT event_type, COALESCE(SUM(owner_profit), 0) AS profit, COALESCE(SUM(gross_amount), 0) AS gross
            FROM platform_ledger
            GROUP BY event_type
            """
        )
        profit_breakdown = [dict(r) for r in await by_source_cur.fetchall()]

        camps_cur = await db.execute(
            """
            SELECT c.*, u.username AS owner_username, u.full_name AS owner_name
            FROM campaigns c
            LEFT JOIN users u ON u.tg_id = c.owner_id
            ORDER BY c.id DESC LIMIT 25
            """
        )
        campaigns = [dict(r) for r in await camps_cur.fetchall()]

        pays_cur = await db.execute(
            """
            SELECT p.*, u.username, u.full_name
            FROM payments p
            LEFT JOIN users u ON u.tg_id = p.user_id
            ORDER BY CASE WHEN p.status = 'pending' THEN 0 ELSE 1 END, p.id DESC
            LIMIT 25
            """
        )
        payments = [dict(r) for r in await pays_cur.fetchall()]

        users_cur = await db.execute(
            "SELECT * FROM users ORDER BY ref_earned DESC, total_earned DESC LIMIT 20"
        )
        top_users = [dict(r) for r in await users_cur.fetchall()]

        ledger_cur = await db.execute("SELECT * FROM platform_ledger ORDER BY id DESC LIMIT 15")
        recent_ledger = [dict(r) for r in await ledger_cur.fetchall()]

        return {
            "summary": {
                "users_count": u_stat["users_count"] or 0,
                "vip_count": u_stat["vip_count"] or 0,
                "total_user_earn_bal": round(float(u_stat["total_user_earn_bal"]), 2),
                "total_user_adv_bal": round(float(u_stat["total_user_adv_bal"]), 2),
                "gross_turnover": round(float(l_stat["gross_turnover"]), 2),
                "net_owner_profit": round(float(l_stat["net_owner_profit"]), 2),
                "partner_paid": round(float(l_stat["partner_paid"]), 2),
                "worker_paid": round(float(l_stat["worker_paid"]), 2),
            },
            "profit_breakdown": profit_breakdown,
            "campaigns": campaigns,
            "payments": payments,
            "top_users": top_users,
            "recent_ledger": recent_ledger,
            "settings": settings,
            "env": {
                "bot_token_configured": bool(env_cfg["bot_token"]),
                "bot_token_masked": (
                    env_cfg["bot_token"][:8] + "..." + env_cfg["bot_token"][-4:]
                    if len(env_cfg["bot_token"]) > 14
                    else ""
                ),
                "admin_ids": ",".join(str(x) for x in env_cfg["admin_ids"]),
                "bot_username": env_cfg["bot_username"],
                "sbp_phone": settings.get("sbp_phone", env_cfg["sbp_phone"]),
                "sbp_bank": settings.get("sbp_bank", env_cfg["sbp_bank"]),
                "sbp_recipient": settings.get("sbp_recipient", env_cfg["sbp_recipient"]),
                "public_feed_channel": env_cfg["public_feed_channel"],
            },
        }
    finally:
        await db.close()


async def clear_demo_data() -> dict:
    """Очищает демонстрационные записи перед реальным запуском бота, сохраняя настройки и тарифы."""
    db = await get_db()
    try:
        await db.executescript(
            """
            DELETE FROM voucher_claims;
            DELETE FROM vouchers;
            DELETE FROM task_completions;
            DELETE FROM partner_accruals;
            DELETE FROM payments WHERE is_demo = 1;
            DELETE FROM campaigns WHERE is_demo = 1;
            DELETE FROM platform_ledger WHERE is_demo = 1;
            DELETE FROM users WHERE is_demo = 1;
            """
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


async def get_all_admin_ids() -> list[int]:
    """Возвращает список ID всех администраторов (из ENV + автоматически закреплённого владельца)."""
    env_ids = list(get_env_config()["admin_ids"])
    settings = await get_settings()
    claimed = (settings.get("claimed_owner_id") or "").strip()
    if claimed.isdigit() and int(claimed) not in env_ids:
        env_ids.append(int(claimed))
    return env_ids


async def check_or_claim_admin(user_id: int) -> bool:
    """Если ADMIN_IDS не был задан вручную, первый реальный пользователь бота автоматически становится владельцем."""
    env_ids = get_env_config()["admin_ids"]
    if user_id in env_ids:
        return True
    settings = await get_settings()
    claimed = (settings.get("claimed_owner_id") or "").strip()
    if claimed.isdigit():
        return int(claimed) == int(user_id)
    # Автозакрепление срабатывает только если ADMIN_IDS остался дефолтным (100000001)
    if env_ids == [100000001]:
        await update_settings({"claimed_owner_id": str(user_id)})
        return True
    return False

