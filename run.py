"""
Entry point — starts the uvicorn server.
Run with:  python run.py
"""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,  # Set True during development for auto-reload
        log_level=settings.log_level.lower(),
    )
