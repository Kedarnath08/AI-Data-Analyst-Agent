from fastapi.middleware.cors import CORSMiddleware

from .config import settings


def setup_cors(app):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            *settings.CORS_EXTRA_ORIGINS,
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
