# app/sockets/session.py
from contextlib import contextmanager
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy import text
from flask import g

def create_socket_session_factory(engine):
    return scoped_session(
        sessionmaker(
            bind=engine,
            expire_on_commit=False
        )
    )

@contextmanager
def socket_session(engine):
    session = create_socket_session_factory(engine)  # however you create or scope it
    try:
        # Instead of just session.execute("SET LOCAL statement_timeout = '5s'")
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.remove()