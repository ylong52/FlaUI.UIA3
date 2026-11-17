"""服务入口。

启动：
    .venv\\Scripts\\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8790
"""

from __future__ import annotations

import logging

from api.routes import create_app
from config import Settings

settings = Settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logging.getLogger(__name__).info("配置文件：%s", settings.config_file)

app = create_app(settings)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
