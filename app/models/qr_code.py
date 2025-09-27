"""
QR Code model for managing generated QR codes
Handles QR code generation, validation and tracking
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timedelta
from ..database import Base
import enum
import json

class QRCodeType(enum.Enum):
    VISITOR = "visitor"
    VEHICLE = "vehicle"

class QRCode(Base):
    __tablename__ = "qr_codes"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(255), unique=True, nullable=False, index=True)
    type = Column(Enum(QRCodeType), nullable=False, index=True)
    data = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    expires_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    used_count = Column(Integer, default=0)
    last_scanned_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    creator = relationship("User")
    location = relationship("Location", back_populates="qr_codes")
    visitors = relationship("Visitor", back_populates="qr_code")
    vehicles = relationship("Vehicle", back_populates="qr_code")
    
    def __repr__(self):
        return f"<QRCode(id={self.id}, code='{self.code[:10]}...', type='{self.type.value}')>"
    
    def to_dict(self, include_data=False):
        """Convert QR code to dictionary"""
        data = {
            "id": self.id,
            "code": self.code,
            "type": self.type.value,
            "is_active": self.is_active,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "location_id": self.location_id,
            "used_count": self.used_count,
            "last_scanned_at": self.last_scanned_at.isoformat() if self.last_scanned_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
        
        if include_data:
            data["data"] = self.data
        
        if self.location:
            data["location"] = {
                "id": self.location.id,
                "name": self.location.name,
                "code": self.location.code
            }
        
        if self.creator:
            data["created_by_user"] = {
                "id": self.creator.id,
                "full_name": self.creator.full_name,
                "username": self.creator.username
            }
        
        return data
    
    @property
    def is_expired(self):
        """Check if QR code is expired"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    @property
    def is_valid(self):
        """Check if QR code is valid for use"""
        return self.is_active and not self.is_expired
    
    @property
    def time_until_expiry(self):
        """Get time until expiry in minutes"""
        if not self.expires_at:
            return None
        
        remaining = self.expires_at - datetime.utcnow()
        if remaining.total_seconds() <= 0:
            return 0
        
        return int(remaining.total_seconds() / 60)
    
    def mark_used(self):
        """Mark QR code as used"""
        self.used_count += 1
        self.last_scanned_at = datetime.utcnow()
    
    def deactivate(self):
        """Deactivate QR code"""
        self.is_active = False
    
    def extend_expiry(self, hours: int):
        """Extend QR code expiry"""
        if self.expires_at:
            self.expires_at = max(self.expires_at, datetime.utcnow()) + timedelta(hours=hours)
        else:
            self.expires_at = datetime.utcnow() + timedelta(hours=hours)
    
    def get_related_record(self):
        """Get the related visitor or vehicle record"""
        if self.type == QRCodeType.VISITOR and self.visitors:
            return self.visitors[0]
        elif self.type == QRCodeType.VEHICLE and self.vehicles:
            return self.vehicles[0]
        return None