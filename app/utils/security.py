"""
Security utilities for authentication, authorization and password management
Handles JWT tokens, password hashing, and access control
"""

from fastapi import HTTPException, status, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt
import secrets
import hashlib
from typing import Optional, Dict, Any
import re

from ..config import get_settings
from ..database import get_db
from ..models.user import User, UserRole
from ..models.session import Session

settings = get_settings()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT Security
security = HTTPBearer(auto_error=False)

class SecurityManager:
    """Centralized security management"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using bcrypt"""
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify password against hash"""
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def validate_password_strength(password: str) -> Dict[str, Any]:
        """Validate password strength"""
        errors = []
        
        if len(password) < 8:
            errors.append("Password must be at least 8 characters long")
        
        if not re.search(r"[A-Z]", password):
            errors.append("Password must contain at least one uppercase letter")
        
        if not re.search(r"[a-z]", password):
            errors.append("Password must contain at least one lowercase letter")
        
        if not re.search(r"\d", password):
            errors.append("Password must contain at least one number")
        
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            errors.append("Password must contain at least one special character")
        
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "strength": "strong" if len(errors) == 0 else "weak"
        }
    
    @staticmethod
    def generate_quick_code() -> str:
        """Generate unique quick login code"""
        return secrets.token_urlsafe(6).upper()[:6]
    
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create JWT access token"""
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)
        return encoded_jwt
    
    @staticmethod
    def decode_token(token: str) -> Optional[Dict[str, Any]]:
        """Decode JWT token"""
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
            return payload
        except JWTError:
            return None
    
    @staticmethod
    def hash_token(token: str) -> str:
        """Hash token for secure storage"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    @staticmethod
    async def create_session(
        db: AsyncSession, 
        user: User, 
        token: str, 
        ip_address: str = None, 
        user_agent: str = None
    ) -> Session:
        """Create user session"""
        token_hash = SecurityManager.hash_token(token)
        expires_at = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
        
        session = Session(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        db.add(session)
        await db.commit()
        await db.refresh(session)
        
        return session
    
    @staticmethod
    async def invalidate_session(db: AsyncSession, token: str):
        """Invalidate user session"""
        token_hash = SecurityManager.hash_token(token)
        
        stmt = select(Session).where(
            Session.token_hash == token_hash,
            Session.is_active == True
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        
        if session:
            session.deactivate()
            await db.commit()
    
    @staticmethod
    async def cleanup_expired_sessions(db: AsyncSession):
        """Clean up expired sessions"""
        from sqlalchemy import delete
        
        stmt = delete(Session).where(Session.expires_at < datetime.utcnow())
        await db.execute(stmt)
        await db.commit()

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Get current authenticated user"""
    
    # Try to get token from Authorization header
    token = None
    if credentials:
        token = credentials.credentials
    
    # Fallback: try to get token from cookies
    if not token:
        token = request.cookies.get("access_token")
    
    if not token:
        return None
    
    # Decode token
    payload = SecurityManager.decode_token(token)
    if not payload:
        return None
    
    user_id = payload.get("sub")
    if not user_id:
        return None
    
    # Verify session exists and is active
    token_hash = SecurityManager.hash_token(token)
    stmt = select(Session).where(
        Session.token_hash == token_hash,
        Session.is_active == True,
        Session.expires_at > datetime.utcnow()
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        return None
    
    # Get user
    stmt = select(User).where(User.id == int(user_id), User.is_active == True)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    return user

async def require_auth(current_user: User = Depends(get_current_user)) -> User:
    """Require authentication"""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user

async def require_admin(current_user: User = Depends(require_auth)) -> User:
    """Require admin role"""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

async def require_location_access(
    location_id: int,
    current_user: User = Depends(require_auth)
) -> User:
    """Require access to specific location"""
    if not current_user.can_access_location(location_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this location"
        )
    return current_user

class RateLimiter:
    """Rate limiting for API endpoints"""
    
    def __init__(self):
        self.requests = {}
        self.blocked = {}
    
    def is_allowed(self, identifier: str, limit: int = 100, window: int = 60) -> bool:
        """Check if request is allowed"""
        now = datetime.utcnow()
        
        # Check if blocked
        if identifier in self.blocked:
            if now < self.blocked[identifier]:
                return False
            else:
                del self.blocked[identifier]
        
        # Initialize or clean old requests
        if identifier not in self.requests:
            self.requests[identifier] = []
        
        # Remove old requests outside window
        cutoff = now - timedelta(seconds=window)
        self.requests[identifier] = [
            req_time for req_time in self.requests[identifier] 
            if req_time > cutoff
        ]
        
        # Check limit
        if len(self.requests[identifier]) >= limit:
            # Block for the window duration
            self.blocked[identifier] = now + timedelta(seconds=window)
            return False
        
        # Add current request
        self.requests[identifier].append(now)
        return True

# Global rate limiter instance
rate_limiter = RateLimiter()

async def check_rate_limit(request: Request):
    """Rate limiting middleware"""
    if not settings.rate_limit_enabled:
        return
    
    client_ip = request.client.host
    
    if not rate_limiter.is_allowed(
        client_ip, 
        settings.rate_limit_requests, 
        settings.rate_limit_window
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )