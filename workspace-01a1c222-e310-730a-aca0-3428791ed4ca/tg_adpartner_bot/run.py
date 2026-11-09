import uvicorn
from core.config import get_env_config

if __name__ == "__main__":
    cfg = get_env_config()
    uvicorn.run(
        "web.app:app",
        host=cfg["web_host"],
        port=cfg["web_port"],
        reload=False,
    )
