import asyncio
import io
import logging
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from aiogram import Bot
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from bot_only import run_telegram_bot
from core import engine
from core.config import BASE_DIR, get_env_config, update_env_file
from core.database import _seed_demo_data, get_db, init_db

logger = logging.getLogger("adpartner.web")
STATIC_DIR = Path(__file__).resolve().parent / "static"

_bot_runtime: dict[str, Any] = {
    "task": None,
    "running": False,
    "username": "",
    "error": "",
}


async def _start_or_restart_live_bot(token: str) -> dict:
    old_task = _bot_runtime.get("task")
    if old_task and not old_task.done():
        old_task.cancel()
        try:
            await old_task
        except BaseException:
            pass
    _bot_runtime["running"] = False
    _bot_runtime["error"] = ""

    if not token:
        return {"ok": True, "running": False, "message": "Настройки сохранены (токен пока не указан)."}

    # Проверяем токен через Telegram API перед запуском поллинга
    try:
        test_bot = Bot(token=token)
        me = await test_bot.get_me()
        await test_bot.session.close()
    except Exception as exc:
        _bot_runtime["error"] = str(exc)
        return {"ok": False, "error": f"Telegram отклонил токен: {exc}"}

    update_env_file({"bot_username": me.username or "AdPartnerPro_Bot"})
    task = asyncio.create_task(run_telegram_bot(token))
    _bot_runtime["task"] = task
    _bot_runtime["running"] = True
    _bot_runtime["username"] = me.username or ""
    return {
        "ok": True,
        "running": True,
        "username": me.username,
        "message": f"Живой Telegram-бот @{me.username} успешно запущен и отвечает в Telegram!",
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(seed_demo=True)
    cfg = get_env_config()
    if cfg["bot_token"]:
        await _start_or_restart_live_bot(cfg["bot_token"])
    yield
    t = _bot_runtime.get("task")
    if t and not t.done():
        t.cancel()


app = FastAPI(title="AdPartner Pro — Панель и Симулятор", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SimActionPayload(BaseModel):
    user_id: int = 777000111
    action: str
    params: dict[str, Any] = {}


class PaymentResolvePayload(BaseModel):
    payment_id: int
    approve: bool


class ToggleCampaignPayload(BaseModel):
    campaign_id: int


class SettingsPayload(BaseModel):
    settings: dict[str, str]


class BotSetupPayload(BaseModel):
    bot_token: str = ""
    admin_ids: str = "100000001"
    bot_username: str = "AdPartnerPro_Bot"
    sbp_phone: str = "+7 (900) 000-00-00"
    sbp_bank: str = "Т-Банк / Сбербанк (СБП)"
    sbp_recipient: str = "Получатель СБП"
    public_feed_channel: str = ""


@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/dashboard")
async def api_dashboard():
    dash = await engine.get_admin_dashboard()
    t = _bot_runtime.get("task")
    dash["live_bot"] = {
        "running": bool(t and not t.done() and _bot_runtime["running"]),
        "username": _bot_runtime["username"] or dash["env"]["bot_username"],
        "error": _bot_runtime["error"],
    }
    return JSONResponse(dash)


@app.get("/api/sim/state")
async def api_sim_state(user_id: int = 777000111, consume_ad: bool = False):
    user, _ = await engine.ensure_user(user_id, "demo_user", f"Участник {user_id}")
    sponsors = await engine.get_mandatory_sponsors(user_id)
    tasks = await engine.list_available_tasks(user_id)
    partner = await engine.get_partner_network_stats(user_id)
    settings = await engine.get_settings()

    native_ad = None
    if consume_ad:
        native_ad = await engine.pick_native_ad(exclude_user_id=user_id)
    else:
        db = await get_db()
        try:
            cur = await db.execute(
                "SELECT * FROM campaigns WHERE type='native_ad' AND status='active' AND completed_qty < total_qty LIMIT 1"
            )
            row = await cur.fetchone()
            native_ad = dict(row) if row else None
        finally:
            await db.close()

    return JSONResponse(
        {
            "user": user,
            "sponsors": sponsors,
            "tasks": tasks,
            "partner": partner,
            "settings": settings,
            "native_ad": native_ad,
        }
    )


@app.post("/api/sim/action")
async def api_sim_action(payload: SimActionPayload):
    uid = payload.user_id
    act = payload.action
    p = payload.params or {}

    if act == "op_verify":
        sponsors = await engine.get_mandatory_sponsors(uid)
        count = 0
        for sp in sponsors:
            if await engine.complete_sponsor_op(uid, sp["id"]):
                count += 1
        return {"ok": True, "message": f"✅ Спонсорские подписки подтверждены ({count} шт.)! Доступ к заданиям открыт."}

    if act == "complete_task":
        res = await engine.complete_task(uid, int(p.get("campaign_id", 0)))
        if not res["ok"]:
            return res
        return {
            "ok": True,
            "message": (
                f"🎉 Выполнено! Вам +{res['worker_reward']:.2f} ₽ | "
                f"Сети партнёров +{res['partner_paid']:.2f} ₽ | "
                f"Чистая прибыль владельца +{res['owner_profit']:.2f} ₽"
            ),
            "details": res,
        }

    if act == "daily_bonus":
        res = await engine.claim_daily_bonus(uid)
        if res["ok"]:
            # Списываем также 1 нативный авто-показ спонсора
            await engine.pick_native_ad(exclude_user_id=uid)
            return {"ok": True, "message": f"🎁 Ежедневный бонус +{res['bonus']:.2f} ₽ зачислен (+ откручен 1 рекламный показ)!"}
        return res

    if act == "claim_voucher":
        res = await engine.claim_voucher(uid, str(p.get("code", "")))
        if res["ok"]:
            return {"ok": True, "message": f"🎫 Чек активирован! На баланс начислено +{res['amount']:.2f} ₽."}
        return res

    if act == "create_voucher":
        res = await engine.create_voucher(
            uid,
            float(p.get("amount_per_use", 2.0)),
            int(p.get("max_uses", 10)),
        )
        if res["ok"]:
            return {
                "ok": True,
                "message": f"🎫 Вирусный чек {res['code']} создан! Ссылка: {res['deep_link']}",
                "voucher": res,
            }
        return res

    if act == "stars_topup":
        stars = int(p.get("stars", 100))
        res = await engine.credit_stars_deposit(uid, stars)
        return {
            "ok": True,
            "message": f"⭐ Автоплатёж {stars} Stars принят! На рекламный счёт +{res['rub_amount']:.2f} ₽.",
            "details": res,
        }

    if act == "sbp_deposit":
        res = await engine.create_sbp_deposit_request(uid, float(p.get("amount", 500)))
        if res["ok"]:
            return {
                "ok": True,
                "message": (
                    f"🏦 Заявка СБП #{res['payment_id']} создана на точную сумму {res['check_amount']:.0f} ₽! "
                    f"Откройте вкладку «Админ-панель», чтобы подтвердить её в 1 клик."
                ),
                "details": res,
            }
        return res

    if act == "sbp_withdraw":
        res = await engine.create_sbp_withdraw_request(
            uid,
            float(p.get("amount", 150)),
            str(p.get("requisites", "+7 (918) 000-11-22, Т-Банк")),
        )
        if res["ok"]:
            return {
                "ok": True,
                "message": f"💸 Заявка на вывод #{res['payment_id']} ({res['net_rub']:.2f} ₽ чистыми) отправлена в Админ-панель!",
            }
        return res

    if act == "reinvest":
        res = await engine.reinvest_earn_to_adv(uid, float(p.get("amount", 50)))
        if res["ok"]:
            return {
                "ok": True,
                "message": f"🔄 Переведено {res['debited']:.2f} ₽ → зачислено +{res['credited']:.2f} ₽ на рекламу (+{res['bonus_pct']:.0f}% бонус)!",
            }
        return res

    if act == "buy_vip":
        res = await engine.buy_vip_status(uid)
        if res["ok"]:
            return {
                "ok": True,
                "message": f"💎 VIP-Амбассадор активирован! В сейф владельца поступило +{res['owner_profit']:.2f} ₽.",
            }
        return res

    if act == "create_campaign":
        res = await engine.create_campaign(
            owner_id=uid,
            c_type=str(p.get("type", "channel_sub")),
            title=str(p.get("title", "Мой Telegram-канал")),
            description=str(p.get("description", "Подпишитесь на канал и получите мгновенное вознаграждение!")),
            target_url=str(p.get("target_url", "https://t.me/telegram")),
            channel_username=str(p.get("channel_username", "@telegram")),
            price_per_action=float(p.get("price_per_action", 4.0)),
            total_qty=int(p.get("total_qty", 50)),
        )
        if res["ok"]:
            return {
                "ok": True,
                "message": f"🚀 Кампания #{res['campaign_id']} запущена! Бюджет {res['total_cost']:.2f} ₽ уже в работе 24/7.",
            }
        return res

    return {"ok": False, "error": "Неизвестное действие."}


@app.post("/api/admin/resolve-payment")
async def api_resolve_payment(payload: PaymentResolvePayload):
    return await engine.resolve_payment_request(payload.payment_id, payload.approve)


@app.post("/api/admin/toggle-campaign")
async def api_toggle_campaign(payload: ToggleCampaignPayload):
    db = await get_db()
    try:
        cur = await db.execute("SELECT status FROM campaigns WHERE id = ?", (payload.campaign_id,))
        row = await cur.fetchone()
        if not row:
            return {"ok": False, "error": "Кампания не найдена."}
        nxt = "paused" if row["status"] == "active" else "active"
        await db.execute("UPDATE campaigns SET status = ? WHERE id = ?", (nxt, payload.campaign_id))
        await db.commit()
        return {"ok": True, "status": nxt}
    finally:
        await db.close()


@app.post("/api/admin/settings")
async def api_update_settings(payload: SettingsPayload):
    updated = await engine.update_settings(payload.settings)
    env_sync = {}
    for k in ("sbp_phone", "sbp_bank", "sbp_recipient"):
        if k in payload.settings:
            env_sync[k] = payload.settings[k]
    if env_sync:
        update_env_file(env_sync)
    return {"ok": True, "settings": updated}


@app.post("/api/admin/setup-bot")
async def api_setup_bot(payload: BotSetupPayload):
    update_env_file(
        {
            "bot_token": payload.bot_token.strip(),
            "admin_ids": payload.admin_ids.strip(),
            "bot_username": payload.bot_username.strip().lstrip("@"),
            "sbp_phone": payload.sbp_phone.strip(),
            "sbp_bank": payload.sbp_bank.strip(),
            "sbp_recipient": payload.sbp_recipient.strip(),
            "public_feed_channel": payload.public_feed_channel.strip(),
        }
    )
    await engine.update_settings(
        {
            "sbp_phone": payload.sbp_phone.strip(),
            "sbp_bank": payload.sbp_bank.strip(),
            "sbp_recipient": payload.sbp_recipient.strip(),
        }
    )
    res = await _start_or_restart_live_bot(payload.bot_token.strip())
    return res


@app.post("/api/admin/clear-demo")
async def api_clear_demo():
    return await engine.clear_demo_data()


@app.post("/api/admin/restore-demo")
async def api_restore_demo():
    db = await get_db()
    try:
        await _seed_demo_data(db)
    finally:
        await db.close()
    return {"ok": True}


@app.get("/api/download-zip")
async def api_download_zip():
    """Собирает чистый готовый к загрузке на бесплатный хостинг ZIP-архив со всеми настройками."""
    buf = io.BytesIO()
    exclude_dirs = {"__pycache__", ".git", ".venv", "data"}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in BASE_DIR.rglob("*"):
            if any(part in exclude_dirs for part in path.parts):
                continue
            if path.is_file() and path.suffix != ".pyc":
                rel = path.relative_to(BASE_DIR)
                zf.write(path, arcname=str(rel))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="tg_adpartner_bot_ready.zip"'},
    )
