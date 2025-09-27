"""
Authentication routes for login, logout and user management
Handles user authentication, registration, and session management
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from typing import Optional
import logging

from ..database import get_db
from ..models.user import User, UserRole
from ..models.location import Location
from ..utils.security import (
    SecurityManager, get_current_user, require_auth, require_admin,
    check_rate_limit
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Pydantic models for request/response
class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False

class QuickLoginRequest(BaseModel):
    quick_code: str

class UserCreateRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str
    role: str = "operator"
    location_id: Optional[int] = None
    phone: Optional[str] = None

class UserUpdateRequest(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    location_id: Optional[int] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict

# Login page
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Display login page"""
    return templates.TemplateResponse(
        "auth/login.html", 
        {"request": request, "page_title": "Login"}
    )

# Login endpoint
@router.post("/login")
async def login(
    request: Request,
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """Authenticate user and create session"""
    await check_rate_limit(request)
    
    try:
        # Find user by username or email
        stmt = select(User).where(
            and_(
                or_(
                    User.username == login_data.username,
                    User.email == login_data.username
                ),
                User.is_active == True
            )
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )
        
        # Check if account is locked
        if user.is_locked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Account locked until {user.locked_until}"
            )
        
        # Verify password
        if not SecurityManager.verify_password(login_data.password, user.password_hash):
            # Increment failed attempts
            user.failed_login_attempts += 1
            
            # Lock account after max attempts
            from ..config import get_settings
            settings = get_settings()
            
            if user.failed_login_attempts >= settings.max_login_attempts:
                user.locked_until = datetime.utcnow() + timedelta(
                    minutes=settings.lockout_duration_minutes
                )
            
            await db.commit()
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )
        
        # Reset failed attempts on successful login
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login = datetime.utcnow()
        
        # Create JWT token
        token_data = {
            "sub": str(user.id),
            "username": user.username,
            "role": user.role.value,
            "location_id": user.location_id
        }
        
        expires_delta = timedelta(days=30) if login_data.remember_me else None
        access_token = SecurityManager.create_access_token(token_data, expires_delta)
        
        # Create session
        client_ip = request.client.host
        user_agent = request.headers.get("user-agent", "")
        
        await SecurityManager.create_session(
            db, user, access_token, client_ip, user_agent
        )
        
        await db.commit()
        
        # Create response
        response_data = TokenResponse(
            access_token=access_token,
            expires_in=2592000 if login_data.remember_me else 43200,  # 30 days or 12 hours
            user=user.to_dict()
        )
        
        # Set cookie for web interface
        response = JSONResponse(content=response_data.dict())
        response.set_cookie(
            key="access_token",
            value=access_token,
            max_age=2592000 if login_data.remember_me else 43200,
            httponly=True,
            secure=True,  # Set to True in production with HTTPS
            samesite="lax"
        )
        
        logger.info(f"User {user.username} logged in successfully")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )

# Quick login for operators
@router.post("/quick-login")
async def quick_login(
    request: Request,
    quick_data: QuickLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """Quick login using operator code"""
    await check_rate_limit(request)
    
    try:
        # Find user by quick code
        stmt = select(User).where(
            and_(
                User.quick_code == quick_data.quick_code.upper(),
                User.is_active == True,
                User.role == UserRole.OPERATOR
            )
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid quick code"
            )
        
        # Check if account is locked
        if user.is_locked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is locked"
            )
        
        # Update login info
        user.last_login = datetime.utcnow()
        user.failed_login_attempts = 0
        
        # Create JWT token
        token_data = {
            "sub": str(user.id),
            "username": user.username,
            "role": user.role.value,
            "location_id": user.location_id
        }
        
        access_token = SecurityManager.create_access_token(token_data)
        
        # Create session
        client_ip = request.client.host
        user_agent = request.headers.get("user-agent", "")
        
        await SecurityManager.create_session(
            db, user, access_token, client_ip, user_agent
        )
        
        await db.commit()
        
        # Create response
        response_data = TokenResponse(
            access_token=access_token,
            expires_in=43200,  # 12 hours
            user=user.to_dict()
        )
        
        response = JSONResponse(content=response_data.dict())
        response.set_cookie(
            key="access_token",
            value=access_token,
            max_age=43200,
            httponly=True,
            secure=True,
            samesite="lax"
        )
        
        logger.info(f"User {user.username} quick logged in successfully")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quick login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Quick login failed"
        )

# Logout endpoint
@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Logout user and invalidate session"""
    try:
        # Get token from request
        token = None
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = request.cookies.get("access_token")
        
        if token:
            # Invalidate session
            await SecurityManager.invalidate_session(db, token)
        
        # Clear cookie
        response.delete_cookie("access_token")
        
        logger.info(f"User {current_user.username if current_user else 'Unknown'} logged out")
        
        return {"message": "Logged out successfully"}
        
    except Exception as e:
        logger.error(f"Logout error: {e}")
        return {"message": "Logged out"}

# Get current user info
@router.get("/me")
async def get_current_user_info(current_user: User = Depends(require_auth)):
    """Get current user information"""
    return {"user": current_user.to_dict()}

# Change password
@router.post("/change-password")
async def change_password(
    password_data: PasswordChangeRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Change user password"""
    try:
        # Verify current password
        if not SecurityManager.verify_password(
            password_data.current_password, 
            current_user.password_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect"
            )
        
        # Validate new password
        if password_data.new_password != password_data.confirm_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New passwords do not match"
            )
        
        # Check password strength
        validation = SecurityManager.validate_password_strength(password_data.new_password)
        if not validation["is_valid"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Password does not meet requirements", "errors": validation["errors"]}
            )
        
        # Update password
        current_user.password_hash = SecurityManager.hash_password(password_data.new_password)
        await db.commit()
        
        logger.info(f"User {current_user.username} changed password")
        
        return {"message": "Password changed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password change error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed"
        )

# User management endpoints (Admin only)
@router.get("/users")
async def list_users(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """List all users (Admin only)"""
    stmt = select(User).order_by(User.created_at.desc())
    result = await db.execute(stmt)
    users = result.scalars().all()
    
    return {
        "users": [user.to_dict() for user in users]
    }

@router.post("/users")
async def create_user(
    user_data: UserCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Create new user (Admin only)"""
    try:
        # Check if username/email already exists
        stmt = select(User).where(
            or_(
                User.username == user_data.username,
                User.email == user_data.email
            )
        )
        result = await db.execute(stmt)
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username or email already exists"
            )
        
        # Validate password
        validation = SecurityManager.validate_password_strength(user_data.password)
        if not validation["is_valid"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Password does not meet requirements", "errors": validation["errors"]}
            )
        
        # Validate role
        try:
            role = UserRole(user_data.role)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role"
            )
        
        # Create user
        new_user = User(
            username=user_data.username,
            email=user_data.email,
            password_hash=SecurityManager.hash_password(user_data.password),
            full_name=user_data.full_name,
            role=role,
            location_id=user_data.location_id,
            phone=user_data.phone,
            quick_code=SecurityManager.generate_quick_code() if role == UserRole.OPERATOR else None
        )
        
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        
        logger.info(f"User {new_user.username} created by {current_user.username}")
        
        return {"message": "User created successfully", "user": new_user.to_dict()}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User creation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User creation failed"
        )

@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    user_data: UserUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Update user (Admin only)"""
    try:
        # Get user
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Update fields
        if user_data.email is not None:
            user.email = user_data.email
        if user_data.full_name is not None:
            user.full_name = user_data.full_name
        if user_data.role is not None:
            try:
                user.role = UserRole(user_data.role)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid role"
                )
        if user_data.location_id is not None:
            user.location_id = user_data.location_id
        if user_data.phone is not None:
            user.phone = user_data.phone
        if user_data.is_active is not None:
            user.is_active = user_data.is_active
        
        await db.commit()
        await db.refresh(user)
        
        logger.info(f"User {user.username} updated by {current_user.username}")
        
        return {"message": "User updated successfully", "user": user.to_dict()}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User update error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User update failed"
        )