"""
Entry model for tracking check-in/check-out events
Handles logging of all entry and exit activities
"""

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from ..database import Base
import enum

class EntryType(enum.Enum):
    VISITOR = "visitor"
    VEHICLE = "vehicle"

class EntryAction(enum.Enum):
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"

class Entry(Base):
    __tablename__ = "entries"
    
    id = Column(Integer, primary_key=True, index=True)
    visitor_id = Column(Integer, ForeignKey("visitors.id"), nullable=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=True)
    entry_type = Column(Enum(EntryType), nullable=False, index=True)
    action = Column(Enum(EntryAction), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    qr_code_scanned = Column(String(255), nullable=True)
    
    # Relationships
    visitor = relationship("Visitor", back_populates="entries")
    vehicle = relationship("Vehicle", back_populates="entries")
    location = relationship("Location", back_populates="entries")
    operator = relationship("User", back_populates="entries")
    
    def __repr__(self):
        return f"<Entry(id={self.id}, type='{self.entry_type.value}', action='{self.action.value}')>"
    
    def to_dict(self):
        """Convert entry to dictionary"""
        data = {
            "id": self.id,
            "entry_type": self.entry_type.value,
            "action": self.action.value,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "notes": self.notes,
            "qr_code_scanned": self.qr_code_scanned
        }
        
        if self.visitor:
            data["visitor"] = {
                "id": self.visitor.id,
                "full_name": self.visitor.full_name,
                "phone": self.visitor.phone,
                "company": self.visitor.company
            }
        
        if self.vehicle:
            data["vehicle"] = {
                "id": self.vehicle.id,
                "license_plate": self.vehicle.license_plate,
                "driver_name": self.vehicle.driver_name,
                "driver_phone": self.vehicle.driver_phone,
                "company": self.vehicle.company
            }
        
        if self.location:
            data["location"] = {
                "id": self.location.id,
                "name": self.location.name,
                "code": self.location.code
            }
        
        if self.operator:
            data["operator"] = {
                "id": self.operator.id,
                "full_name": self.operator.full_name,
                "username": self.operator.username
            }
        
        return data
    
    @property
    def subject_name(self):
        """Get the name of the visitor or driver"""
        if self.visitor:
            return self.visitor.full_name
        elif self.vehicle:
            return self.vehicle.driver_name
        return "Unknown"
    
    @property
    def subject_identifier(self):
        """Get identifier (phone or license plate)"""
        if self.visitor:
            return self.visitor.phone or self.visitor.id_number
        elif self.vehicle:
            return self.vehicle.license_plate
        return "Unknown"