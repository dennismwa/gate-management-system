"""
Configuration module for Gate Management System
Handles all application settings and environment variables
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
import os

class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # Application
    app_name: str = Field(default="Gate Management System", env="APP_NAME")
    environment: str = Field(default="development", env="ENVIRONMENT")
    debug: bool = Field(default=True, env="DEBUG")
    
    # Database Configuration
    database_host: str = Field(default="localhost", env="DB_HOST")
    database_port: int = Field(default=3306, env="DB_PORT")
    database_name: str = Field(default="vxjtgclw_Gate Management System", env="DB_NAME")
    database_user: str = Field(default="vxjtgclw_Gate-Management-System", env="DB_USER")
    database_password: str = Field(default="%Bwo+biP9,0R+]yy", env="DB_PASSWORD")
    database_charset: str = Field(default="utf8mb4", env="DB_CHARSET")
    
    # Security
    secret_key: str = Field(default="gate-management-super-secret-key-change-in-production", env="SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", env="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(default=720, env="JWT_EXPIRE_MINUTES")  # 12 hours
    password_hash_algorithm: str = Field(default="bcrypt", env="PASSWORD_HASH_ALGORITHM")
    max_login_attempts: int = Field(default=3, env="MAX_LOGIN_ATTEMPTS")
    lockout_duration_minutes: int = Field(default=15, env="LOCKOUT_DURATION_MINUTES")
    
    # File Upload
    upload_directory: str = Field(default="uploads", env="UPLOAD_DIRECTORY")
    max_file_size: int = Field(default=5242880, env="MAX_FILE_SIZE")  # 5MB
    allowed_image_extensions: list = Field(default=["jpg", "jpeg", "png", "gif"], env="ALLOWED_IMAGE_EXTENSIONS")
    
    # QR Code Settings
    qr_code_size: int = Field(default=300, env="QR_CODE_SIZE")
    qr_code_border: int = Field(default=4, env="QR_CODE_BORDER")
    qr_code_expiry_hours: int = Field(default=24, env="QR_CODE_EXPIRY_HOURS")
    
    # Printing
    print_server_url: str = Field(default="", env="PRINT_SERVER_URL")
    sticker_sizes: dict = Field(
        default={
            "small": {"width": 200, "height": 100},
            "medium": {"width": 300, "height": 150},
            "large": {"width": 400, "height": 200}
        }
    )
    
    # Notifications
    sms_enabled: bool = Field(default=False, env="SMS_ENABLED")
    sms_api_key: str = Field(default="", env="SMS_API_KEY")
    sms_sender_id: str = Field(default="GateMS", env="SMS_SENDER_ID")
    
    email_enabled: bool = Field(default=True, env="EMAIL_ENABLED")
    smtp_server: str = Field(default="localhost", env="SMTP_SERVER")
    smtp_port: int = Field(default=587, env="SMTP_PORT")
    smtp_username: str = Field(default="", env="SMTP_USERNAME")
    smtp_password: str = Field(default="", env="SMTP_PASSWORD")
    email_from: str = Field(default="noreply@gatemanagement.com", env="EMAIL_FROM")
    
    # Cache and Performance
    redis_enabled: bool = Field(default=False, env="REDIS_ENABLED")
    redis_host: str = Field(default="localhost", env="REDIS_HOST")
    redis_port: int = Field(default=6379, env="REDIS_PORT")
    redis_db: int = Field(default=0, env="REDIS_DB")
    cache_ttl_seconds: int = Field(default=300, env="CACHE_TTL_SECONDS")  # 5 minutes
    
    # API Rate Limiting
    rate_limit_enabled: bool = Field(default=True, env="RATE_LIMIT_ENABLED")
    rate_limit_requests: int = Field(default=100, env="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(default=60, env="RATE_LIMIT_WINDOW")  # seconds
    
    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_file: str = Field(default="logs/gate_management.log", env="LOG_FILE")
    log_max_bytes: int = Field(default=10485760, env="LOG_MAX_BYTES")  # 10MB
    log_backup_count: int = Field(default=5, env="LOG_BACKUP_COUNT")
    
    # Backup
    backup_enabled: bool = Field(default=True, env="BACKUP_ENABLED")
    backup_frequency: str = Field(default="daily", env="BACKUP_FREQUENCY")
    backup_directory: str = Field(default="backups", env="BACKUP_DIRECTORY")
    backup_retention_days: int = Field(default=30, env="BACKUP_RETENTION_DAYS")
    
    # UI/Theme
    default_theme_color: str = Field(default="#3B82F6", env="DEFAULT_THEME_COLOR")
    company_name: str = Field(default="Your Company", env="COMPANY_NAME")
    company_logo: str = Field(default="/static/images/logo.png", env="COMPANY_LOGO")
    
    # Timezone
    timezone: str = Field(default="Africa/Nairobi", env="TIMEZONE")
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"
    
    @property
    def database_url(self) -> str:
        """Construct database URL"""
        return f"mysql+aiomysql://{self.database_user}:{self.database_password}@{self.database_host}:{self.database_port}/{self.database_name}?charset={self.database_charset}"
    
    @property
    def sync_database_url(self) -> str:
        """Construct synchronous database URL"""
        return f"mysql+pymysql://{self.database_user}:{self.database_password}@{self.database_host}:{self.database_port}/{self.database_name}?charset={self.database_charset}"
    
    def ensure_directories(self):
        """Create necessary directories"""
        directories = [
            self.upload_directory,
            "logs",
            "backups",
            "app/static/images/uploads",
            "app/static/qr_codes"
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)

@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    settings = Settings()
    settings.ensure_directories()
    return settings