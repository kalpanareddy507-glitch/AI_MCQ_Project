import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 1. Safely retrieve the encrypted credentials from Streamlit's secrets wrapper
db_config = st.secrets["mysql"]

# 2. Build the live, public production connection string
DATABASE_URL = f"mysql+pymysql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}"

# 3. Spin up your SQLAlchemy engine with production safety parameters
engine = create_engine(
    DATABASE_URL,
    pool_recycle=3600, # Prevents cloud server connection timeouts
    pool_pre_ping=True  # Checks database health before running student queries
)

# 4. Standard SQLAlchemy session setup for your app queries
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
