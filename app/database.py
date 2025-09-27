"""
Database configuration and connection management
Handles SQLAlchemy setup with async support and connection pooling
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, text
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import asyncio
import logging
from .config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Create async engine with connection pooling
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,
    max_overflow=30,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True
)

# Create sync engine for migrations and initial setup
sync_engine = create_engine(
    settings.sync_database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True
)

# Create session makers
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)

SessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False
)

# Base class for models
Base = declarative_base()

async def init_db():
    """Initialize database - create tables if they don't exist"""
    try:
        # Test database connection
        async with async_engine.begin() as conn:
            # Set timezone
            await conn.execute(text("SET time_zone = '+03:00'"))
            logger.info("✅ Database connection established")
            
        # Import all models to ensure they're registered
        from .models import user, visitor, vehicle, location, qr_code, entry, setting, audit_log, session
        
        # Create tables
        async with async_engine.begin() as conn:
            # Check if tables exist, create if not
            result = await conn.execute(text("SHOW TABLES"))
            existing_tables = {row[0] for row in result.fetchall()}
            
            if not existing_tables:
                logger.info("Creating database tables...")
                await conn.run_sync(Base.metadata.create_all)
                logger.info("✅ Database tables created")
            else:
                logger.info("✅ Database tables already exist")
                
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            await session.close()

@asynccontextmanager
async def get_db_context():
    """Context manager for database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"Database context error: {e}")
            raise

class DatabaseManager:
    """Database management utilities"""
    
    @staticmethod
    async def execute_raw_sql(query: str, params: dict = None):
        """Execute raw SQL query"""
        async with AsyncSessionLocal() as session:
            try:
                result = await session.execute(text(query), params or {})
                await session.commit()
                return result
            except Exception as e:
                await session.rollback()
                logger.error(f"Raw SQL execution failed: {e}")
                raise
    
    @staticmethod
    async def get_table_count(table_name: str) -> int:
        """Get count of records in a table"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            return result.scalar()
    
    @staticmethod
    async def backup_database(backup_path: str):
        """Create database backup (requires mysqldump)"""
        import subprocess
        import os
        from datetime import datetime
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = f"{backup_path}/backup_{timestamp}.sql"
            
            cmd = [
                'mysqldump',
                f'-h{settings.database_host}',
                f'-P{settings.database_port}',
                f'-u{settings.database_user}',
                f'-p{settings.database_password}',
                '--single-transaction',
                '--routines',
                '--triggers',
                settings.database_name
            ]
            
            with open(backup_file, 'w') as f:
                process = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, check=True)
            
            logger.info(f"✅ Database backup created: {backup_file}")
            return backup_file
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Database backup failed: {e.stderr.decode()}")
            raise
        except Exception as e:
            logger.error(f"❌ Database backup failed: {e}")
            raise
    
    @staticmethod
    async def health_check() -> dict:
        """Check database health"""
        try:
            async with AsyncSessionLocal() as session:
                # Test connection
                await session.execute(text("SELECT 1"))
                
                # Get connection info
                result = await session.execute(text("SELECT VERSION(), NOW()"))
                version, current_time = result.fetchone()
                
                # Get basic stats
                tables_result = await session.execute(text("SHOW TABLES"))
                table_count = len(tables_result.fetchall())
                
                return {
                    "status": "healthy",
                    "version": version,
                    "current_time": current_time.isoformat(),
                    "table_count": table_count,
                    "timezone": settings.timezone
                }
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e)
            }

# Connection testing
async def test_connection():
    """Test database connection"""
    try:
        async with async_engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            logger.info("✅ Database connection test successful")
            return True
    except Exception as e:
        logger.error(f"❌ Database connection test failed: {e}")
        return False