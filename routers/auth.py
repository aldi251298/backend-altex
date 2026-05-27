"""
Authentication router.
Endpoints: login, logout, refresh, me, register, change password.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from constants import (
    LOGIN_FAIL_DELAY_SECONDS,
    time_ns,
)
from env import settings
from models.users import User
from utils.auth import (
    create_access_token,
    create_refresh_token,
    get_verified_user,
    hash_password,
    verify_password,
)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ============================================================================
# Endpoints
# ============================================================================


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login dengan email & password",
)
async def login(
    form_data: LoginRequest,
    background_tasks: BackgroundTasks,
):
    """Login dengan email dan password. Returns JWT tokens."""
    from database import async_session_factory
    
    async with async_session_factory() as db:
        user = await User.get_by_email(db, form_data.email)
        
        # Verify password (with delay for timing attack prevention)
        if not user or not verify_password(form_data.password, user.hashed_password):
            background_tasks.add_task(_delayed_response, LOGIN_FAIL_DELAY_SECONDS)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email atau password salah",
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akun dinonaktifkan",
            )
        
        # Generate tokens
        access_token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
        )
        refresh_token = create_refresh_token(user_id=user.id)
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            user=user.to_response(),
        )


@router.post("/logout", summary="Logout (invalidate token)")
async def logout(user=Depends(get_verified_user)):
    """Logout - in stateless JWT, client just discards token."""
    return {"message": "Logout berhasil. Hapus token di client."}


@router.get("/me", response_model=dict, summary="Get current user profile")
async def get_me(user=Depends(get_verified_user)):
    """Get current authenticated user profile."""
    from database import async_session_factory
    
    async with async_session_factory() as db:
        user_obj = await User.get_by_id(db, user["id"])
    
    if not user_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User tidak ditemukan",
        )
    
    return user_obj.to_response()


@router.post(
    "/register",
    response_model=TokenResponse,
    summary="Register user baru",
)
async def register(
    request: RegisterRequest,
    background_tasks: BackgroundTasks,
):
    """Register user baru (jika ENABLE_SIGNUP=true)."""
    if not settings.enable_signup:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registrasi dinonaktifkan",
        )
    
    from database import async_session_factory
    
    async with async_session_factory() as db:
        # Check if email already exists
        existing = await User.get_by_email(db, request.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email sudah terdaftar",
            )
        
        # Create user
        user = await User.create(
            db=db,
            email=request.email,
            name=request.name,
            hashed_password=hash_password(request.password),
            role="user",
        )
        
        access_token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role,
        )
        refresh_token = create_refresh_token(user_id=user.id)
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            user=user.to_response(),
        )


@router.post("/refresh", response_model=TokenResponse, summary="Refresh access token")
async def refresh_token(
    request: dict,
):
    """Refresh access token using refresh token."""
    from jose import jwt
    from utils.auth import SECRET_KEY
    
    refresh = request.get("refresh_token", "")
    
    try:
        payload = jwt.decode(refresh, SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token tidak valid",
        )
    
    from database import async_session_factory
    
    async with async_session_factory() as db:
        user = await User.get_by_id(db, payload["sub"])
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User tidak ditemukan",
        )
    
    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
    )
    new_refresh = create_refresh_token(user_id=user.id)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        token_type="bearer",
        user=user.to_response(),
    )


@router.put("/me/password", summary="Ganti password")
async def change_password(
    request: ChangePasswordRequest,
    user_info=Depends(get_verified_user),
):
    """Ganti password user."""
    from database import async_session_factory
    
    async with async_session_factory() as db:
        user = await User.get_by_id(db, user_info["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User tidak ditemukan",
            )
        
        if not verify_password(request.old_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password lama salah",
            )
        
        user.hashed_password = hash_password(request.new_password)
        user.updated_at = time_ns()
        await db.commit()
    
    return {"message": "Password berhasil diubah"}


# ============================================================================
# Helper Functions
# ============================================================================


async def _delayed_response(seconds: float):
    """Add delay for timing attack prevention."""
    import asyncio
    await asyncio.sleep(seconds)
