import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "adpartner.db"
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH, override=True)


def get_env_config() -> dict:
    load_dotenv(ENV_PATH, override=True)
    raw_admins = os.getenv("ADMIN_IDS", "100000001")
    admin_ids = []
    for part in raw_admins.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            admin_ids.append(int(part))
    if not admin_ids:
        admin_ids = [100000001]

    return {
        "bot_token": os.getenv("BOT_TOKEN", "").strip(),
        "admin_ids": admin_ids,
        "bot_username": os.getenv("BOT_USERNAME", "AdPartnerPro_Bot").strip().lstrip("@"),
        "sbp_phone": os.getenv("SBP_PHONE", "+7 (900) 000-00-00").strip(),
        "sbp_bank": os.getenv("SBP_BANK", "Т-Банк / Сбербанк (СБП)").strip(),
        "sbp_recipient": os.getenv("SBP_RECIPIENT", "Получатель СБП").strip(),
        "public_feed_channel": os.getenv("PUBLIC_FEED_CHANNEL", "").strip(),
        "web_host": os.getenv("WEB_HOST", "0.0.0.0").strip(),
        "web_port": int(os.getenv("WEB_PORT", "8000") or 8000),
        "admin_web_key": os.getenv("ADMIN_WEB_KEY", "admin2026").strip(),
    }


def update_env_file(updates: dict) -> None:
    """Сохраняет обновлённые переменные в файл .env с сохранением структуры."""
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

    lines = [
        "# Автоматически сохранённые настройки AdPartner Pro",
    ]
    for k, v in existing.items():
        lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load_dotenv(ENV_PATH, override=True)
