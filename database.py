from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ✅ connect to your existing DB
DATABASE_URL = "sqlite:///./DB/training_data.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine)