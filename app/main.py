from app.core.logging import setup_logging
from app.core.setup import create_app

setup_logging()

app = create_app()
