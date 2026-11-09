import os
import re
from pathlib import Path
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "adpartner.db"
ENV_PATH = BASE_DIR / ".env"

_TG_TOKEN_RE = re.compile(r"^\d{7,14}:[A-Za-z0-9_-]{30,60}$")


def _pick(keys: list[str], file_vals: dict, default: str = "") -> str:
    for k in keys:
        env_v = os.environ.get(k, "").strip()
        if env_v:
            return env_v
    for k in keys:
        file_v = (file_vals.get(k) or "").strip()
        if file_v:
            return file_v
    return default


def _detect_bot_token(file_vals: dict) -> str:
    direct = _pick(
        [
            "BOT_TOKEN",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_TOKEN",
            "TOKEN",
            "API_TOKEN",
            "TG_BOT_TOKEN",
            "TG_TOKEN",
        ],
        file_vals,
        "",
    )
    if direct:
        return direct
    # Автопоиск по формату токена @BotFather в любых переменных окружения хостинга
    for val in os.environ.values():
        v = (val or "").strip()
        if _TG_TOKEN_RE.match(v):
            return v
    for val in file_vals.values():
        v = (val or "").strip()
        if _TG_TOKEN_RE.match(v):
            return v
    return ""


def get_env_config() -> dict:
    file_vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}

    raw_admins = _pick(["ADMIN_IDS", "ADMIN_ID", "OWNER_ID"], file_vals, "100000001")
    admin_ids = []
    for part in raw_admins.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            admin_ids.append(int(part))
    if not admin_ids:
        admin_ids = [100000001]

    return {
        "bot_token": _detect_bot_token(file_vals),
        "admin_ids": admin_ids,
        "bot_username": _pick(["BOT_USERNAME"], file_vals, "StavAdPartner_bot").lstrip("@"),
        "sbp_phone": _pick(["SBP_PHONE"], file_vals, "+7 (900) 000-00-00"),
        "sbp_bank": _pick(["SBP_BANK"], file_vals, "Т-Банк / Сбербанк (СБП)"),
        "sbp_recipient": _pick(["SBP_RECIPIENT"], file_vals, "Получатель СБП"),
        "public_feed_channel": _pick(["PUBLIC_FEED_CHANNEL"], file_vals, ""),
        "web_host": _pick(["WEB_HOST"], file_vals, "0.0.0.0"),
        "web_port": int(_pick(["WEB_PORT", "PORT"], file_vals, "8000") or 8000),
        "admin_web_key": _pick(["ADMIN_WEB_KEY"], file_vals, "admin2026"),
    }


def update_env_file(updates: dict) -> None:
    """Сохраняет обновлённые переменные в файл .env."""
    key_map = {
        "bot_token": "BOT_TOKEN",
        "admin_ids": "ADMIN_IDS",
        "bot_username": "BOT_USERNAME",
        "sbp_phone": "SBP_PHONE",
        "sbp_bank": "SBP_BANK",
        "sbp_recipient": "SBP_RECIPIENT",
        "public_feed_channel": "PUBLIC_FEED_CHANNEL",
    }
    existing = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, v = stripped.split("=", 1)
                existing[k.strip()] = v.strip()

    for k, v in updates.items():
        env_key = key_map.get(k, k)
        if isinstance(v, list):
            v = ",".join(str(x) for x in v)
        existing[env_key] = str(v).strip()

    lines = ["# Автоматически сохранённые настройки AdPartner Pro"]
    for k, v in existing.items():
        lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
