import os 

from sqlalchemy import create_engine 
from sqlalchemy.orm import DeclarativeBase, sessionmaker 

"""
# define where the databases lives 
# on auzre, app service injects DATABASE_URL, pointing at PostgreSQL
"""

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./incidents.db") 

"""
SQLite refuses to share one connection across threads unless told unless otherwise, and FastAPI can hop threads within a request. 
Postgres has no such option and would reject it, so only pass it for SQLite
"""

if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_the_thread": False}
else:
    connect_args = {}

"""
The engine: the single app-wide object that owns the connection pool and knows which SQL dialect to speak. echo=True prints every SQL statement
"""
engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=True)

"""Factory for Sessions"""

SessionLocal = sessionmaker(autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()