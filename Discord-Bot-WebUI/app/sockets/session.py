# app/sockets/session.py

from contextlib import contextmanager
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

SessionLocal = sessionmaker(expire_on_commit=False)

@contextmanager
def socket_session(engine):
    session = SessionLocal(bind=engine)
    try:
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()
