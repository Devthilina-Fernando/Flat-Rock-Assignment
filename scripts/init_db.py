"""Create all SQLite tables."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.base import Base
from app.db.session import engine
from app.db import models  # noqa: F401 — import models so they register with Base

Base.metadata.create_all(bind=engine)
print("Database tables created successfully.")
