from datetime import timedelta
from typing import Callable

import pytest
import sqlalchemy
import sqlalchemy.exc
from charset_normalizer.md import lru_cache
from fastapi.testclient import TestClient
from sqlalchemy import select, text, delete
from sqlalchemy.orm import Session

from app import app
from backend.auth.password import hash_password
from backend.auth.utils.jwt import create_token
from backend.auth.utils.session import SessionClaims
from model.identity import User, Session as UserSession, IdentityProvider, Issuer


@pytest.fixture(scope="session")
def engine():
    """Create a single SQLAlchemy engine for the whole test session.

    - Ensures citext extension exists
    - Creates all tables at session start
    - Drops all tables at session end to delete everything in the DB
    """
    from model import Base as ModelBase

    engine = sqlalchemy.create_engine(
        "postgresql+psycopg2://talos_app:kirowashere@localhost:5432/test"
    )

    # init db extension
    with Session(engine) as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        session.commit()

    # create schema for tests
    ModelBase.metadata.create_all(engine)

    try:
        yield engine
    finally:
        # Remove all tables / data at the end of the test session
        ModelBase.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture(autouse=True)
def db_session(engine):
    """Provide a per-test DB session and override app dependency to return it."""
    from model import get_db

    try:
        with Session(engine) as db:
            app.dependency_overrides[get_db] = lambda: db
            yield db
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="function")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def path(client: TestClient):
    def build_path(route: str | Callable, **path_params):
        if callable(route):
            route = route.__name__
        return client.app.url_path_for(route, **path_params)

    return build_path


@pytest.fixture
def test_user(db_session: Session):
    from faker import Faker
    faker = Faker()

    user_name = faker.user_name()
    try:
        user = User(
            username=user_name,
            primary_email=faker.email(),
            email_verified=True,
            name=faker.name(),
            data={},
            roles=[],
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    except sqlalchemy.exc.IntegrityError:
        user = db_session.scalar(
            select(User)
            .where(User.username == user_name)
        ).one()

    yield user

    # Cleanup
    db_session.execute(delete(User).where(User.id == user.id))
    db_session.commit()


@lru_cache
def hash_pw_cached(pwd):
    return hash_password(pwd)


@pytest.fixture
def test_user_with_password(db_session: Session, test_user: User):
    password = "TestPassword123!"
    password_hash = hash_pw_cached(password)

    identity = IdentityProvider(
        user_id=test_user.id,
        issuer=Issuer.password,
        data={"hash": password_hash},
    )
    db_session.add(identity)
    db_session.commit()

    return test_user, password


@pytest.fixture
def test_session(db_session, test_user) -> SessionClaims:
    from datetime import timezone, datetime
    session = UserSession(user_id=test_user.id)
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    return SessionClaims(
        sub=test_user.id,
        jti=session.id,
        exp=datetime.now(timezone.utc) + timedelta(days=30),
    )


@pytest.fixture
def auth_token(test_session) -> str:
    return create_token(test_session)


@pytest.fixture
def sudo_auth_token(test_user: User, test_session: SessionClaims) -> str:
    from datetime import timezone, datetime
    claims = SessionClaims(
        sub=test_user.id,
        jti=test_session.jti,
        exp=datetime.now(timezone.utc) + timedelta(minutes=15),
        sudo_exp=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    return create_token(claims)


@pytest.fixture
def expired_token(test_user: User, test_session: SessionClaims) -> str:
    from datetime import timezone, datetime
    claims = SessionClaims(
        sub=test_user.id,
        jti=test_session.jti,
        exp=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    return create_token(claims)
