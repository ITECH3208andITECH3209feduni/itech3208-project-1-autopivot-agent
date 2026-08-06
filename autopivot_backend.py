import uvicorn

from api import app
from config import settings


if __name__ == "__main__":
    uvicorn.run(
        "autopivot_backend:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
