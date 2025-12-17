"""Authentication routes."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps.database import get_db
from backend.api.deps.auth import (
    create_access_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from backend.api.schemas.auth import (
    UserCreate,
    UserLogin,
    UserResponse,
    TokenResponse,
)
from backend.model.identity import User, UserPassword
from backend.app.auth import hash_password, verify_password

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """
    Register a new user.

    Args:
        user_data: User registration data
        db: Database session

    Returns:
        Token response with access token and user info
    """
    # Check if username exists
    existing_username = db.execute(
        select(User).where(User.username == user_data.username.lower())
    ).scalar_one_or_none()

    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Check if email exists
    existing_email = db.execute(
        select(User).where(User.primary_email == user_data.email.lower())
    ).scalar_one_or_none()

    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create user
    user = User(
        username=user_data.username.lower(),
        primary_email=user_data.email.lower(),
        name=user_data.name,
        email_verified=False,
        data={},
    )
    db.add(user)
    db.flush()

    # Create password
    password_hash = hash_password(user_data.password)
    user_password = UserPassword(
        user_id=user.id,
        hashed_password=password_hash,
    )
    db.add(user_password)
    db.commit()
    db.refresh(user)

    # Create access token
    access_token = create_access_token(user.id)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(
            id=user.id,
            username=user.username,
            email=user.primary_email,
            name=user.name,
            email_verified=user.email_verified,
            created_at=user.created_at,
            roles=[],
        ),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """
    Authenticate user and return access token.

    Args:
        credentials: Login credentials
        db: Database session

    Returns:
        Token response with access token and user info
    """
    # Find user by email
    user = db.execute(
        select(User).where(
            User.primary_email == credentials.email.lower(),
            User.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Get password
    user_password = db.execute(
        select(UserPassword).where(UserPassword.user_id == user.id)
    ).scalar_one_or_none()

    if not user_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Verify password
    if not verify_password(credentials.password, user_password.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Create access token
    access_token = create_access_token(user.id)

    # Get user roles
    role_names = [role.name for role in user.roles] if user.roles else []

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(
            id=user.id,
            username=user.username,
            email=user.primary_email,
            name=user.name,
            email_verified=user.email_verified,
            created_at=user.created_at,
            roles=role_names,
        ),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Get current user information.

    Args:
        current_user: Currently authenticated user

    Returns:
        User information
    """
    role_names = [role.name for role in current_user.roles] if current_user.roles else []

    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.primary_email,
        name=current_user.name,
        email_verified=current_user.email_verified,
        created_at=current_user.created_at,
        roles=role_names,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Logout current user.

    Note: For JWT tokens, logout is handled client-side by discarding the token.
    This endpoint can be used for audit logging or token blacklisting if needed.

    Args:
        current_user: Currently authenticated user
    """
    # For stateless JWT, we just return success
    # In a production system, you might want to blacklist the token
    pass
