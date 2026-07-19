from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.dependencies import get_current_user
from app.auth.security import (
    hash_password,
    issue_access_token,
    verify_password,
)
from app.database import get_session
from app.models.user import TokenResponse, User, UserLogin, UserPublic, UserRegister

router = APIRouter()


@router.post(
    "/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
async def register(data: UserRegister, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(User).where(
            (User.email == data.email) | (User.username == data.username)
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already registered",
        )

    user = User(
        email=data.email,
        username=data.username,
        password=hash_password(data.password),
        display_name=data.display_name,
    )

    session.add(user)
    await session.commit()

    return issue_access_token(user)


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.email == data.email))
    user = result.scalars().first()

    if user is None or not verify_password(data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    return issue_access_token(user)


@router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
