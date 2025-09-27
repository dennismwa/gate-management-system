"""
QR Code management routes
Handles QR code scanning, generation, and validation
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json
import logging

from ..database import get_db
from ..models.user import User
from ..models.visitor import Visitor, VisitorStatus
from ..models.vehicle import Vehicle, VehicleStatus
from ..models.qr_code import QRCode, QRCodeType
from ..models.entry import Entry, EntryType, EntryAction
from ..models.location import Location
from ..utils.security import require_auth, require_location_access
from ..utils.qr_generator import qr_generator
from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")
settings = get_settings()

# Pydantic models
class QRScanRequest(BaseModel):
    qr_data: str
    location_id: Optional[int] = None
    notes: Optional[str] = None

class QRGenerateRequest(BaseModel):
    record_type: str  # "visitor" or "vehicle"
    record_id: int
    location_id: int
    expires_hours: Optional[int] = None

class QRValidateRequest(BaseModel):
    qr_code: str

# QR Scanner page
@router.get("/scan", response_class=HTMLResponse)
async def qr_scanner_page(
    request: Request,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Display QR code scanner page"""
    try:
        # Get user's locations
        locations_stmt = select(Location).where(Location.is_active == True)
        if not current_user.is_admin and current_user.location_id:
            locations_stmt = locations_stmt.where(Location.id == current_user.location_id)
        
        locations_result = await db.execute(locations_stmt)
        locations = locations_result.scalars().all()
        
        return templates.TemplateResponse(
            "qr/scanner.html",
            {
                "request": request,
                "user": current_user.to_dict(),
                "locations": [loc.to_dict() for loc in locations],
                "page_title": "QR Code Scanner"
            }
        )
    except Exception as e:
        logger.error(f"Error loading QR scanner page: {e}")
        raise HTTPException(status_code=500, detail="Failed to load QR scanner page")

# QR Management page
@router.get("/manage", response_class=HTMLResponse)
async def qr_management_page(
    request: Request,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Display QR code management page"""
    try:
        return templates.TemplateResponse(
            "qr/manage.html",
            {
                "request": request,
                "user": current_user.to_dict(),
                "page_title": "QR Code Management"
            }
        )
    except Exception as e:
        logger.error(f"Error loading QR management page: {e}")
        raise HTTPException(status_code=500, detail="Failed to load QR management page")

# Scan QR code
@router.post("/api/scan")
async def scan_qr_code(
    scan_data: QRScanRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Process QR code scan"""
    try:
        # Validate QR data
        is_valid, qr_content = qr_generator.validate_qr_data(scan_data.qr_data)
        
        if not is_valid:
            return {
                "success": False,
                "message": "Invalid QR code",
                "error": qr_content.get("error", "Unknown error") if qr_content else "Invalid format"
            }
        
        # Get QR code record
        qr_code = qr_content["code"]
        stmt = select(QRCode).where(
            and_(
                QRCode.code == qr_code,
                QRCode.is_active == True
            )
        )
        result = await db.execute(stmt)
        qr_record = result.scalar_one_or_none()
        
        if not qr_record:
            return {
                "success": False,
                "message": "QR code not found or inactive"
            }
        
        # Check if QR code is expired
        if qr_record.is_expired:
            return {
                "success": False,
                "message": "QR code has expired"
            }
        
        # Check location access
        scan_location_id = scan_data.location_id or current_user.location_id
        if not current_user.is_admin and current_user.location_id:
            if qr_record.location_id != current_user.location_id:
                return {
                    "success": False,
                    "message": "QR code not valid for this location"
                }
        
        # Process based on QR type
        if qr_record.type == QRCodeType.VISITOR:
            result = await process_visitor_scan(qr_record, scan_data, current_user, db)
        elif qr_record.type == QRCodeType.VEHICLE:
            result = await process_vehicle_scan(qr_record, scan_data, current_user, db)
        else:
            return {
                "success": False,
                "message": "Unknown QR code type"
            }
        
        # Mark QR code as used
        if result.get("success"):
            qr_record.mark_used()
            await db.commit()
        
        return result
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error scanning QR code: {e}")
        raise HTTPException(status_code=500, detail="Failed to process QR code scan")

async def process_visitor_scan(
    qr_record: QRCode,
    scan_data: QRScanRequest,
    current_user: User,
    db: AsyncSession
) -> Dict[str, Any]:
    """Process visitor QR code scan"""
    try:
        # Get visitor
        visitor_id = qr_record.data.get("record_id")
        stmt = select(Visitor).where(Visitor.id == visitor_id)
        result = await db.execute(stmt)
        visitor = result.scalar_one_or_none()
        
        if not visitor:
            return {
                "success": False,
                "message": "Visitor not found"
            }
        
        # Determine action based on current status
        if visitor.status == VisitorStatus.PENDING:
            # Check in visitor
            visitor.status = VisitorStatus.CHECKED_IN
            action = EntryAction.CHECK_IN
            message = f"{visitor.full_name} checked in successfully"
            
        elif visitor.status == VisitorStatus.CHECKED_IN:
            # Check out visitor
            visitor.status = VisitorStatus.CHECKED_OUT
            action = EntryAction.CHECK_OUT
            message = f"{visitor.full_name} checked out successfully"
            
        elif visitor.status == VisitorStatus.CHECKED_OUT:
            return {
                "success": False,
                "message": "Visitor has already checked out",
                "visitor": visitor.to_dict()
            }
        else:
            return {
                "success": False,
                "message": f"Invalid visitor status: {visitor.status.value}",
                "visitor": visitor.to_dict()
            }
        
        # Create entry record
        entry = Entry(
            visitor_id=visitor.id,
            entry_type=EntryType.VISITOR,
            action=action,
            location_id=visitor.location_id,
            operator_id=current_user.id,
            notes=scan_data.notes,
            qr_code_scanned=qr_record.code
        )
        
        db.add(entry)
        await db.commit()
        await db.refresh(visitor)
        
        logger.info(f"Visitor QR scan: {visitor.full_name} {action.value} by {current_user.username}")
        
        return {
            "success": True,
            "message": message,
            "type": "visitor",
            "action": action.value,
            "visitor": visitor.to_dict(),
            "entry": entry.to_dict()
        }
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error processing visitor scan: {e}")
        raise

async def process_vehicle_scan(
    qr_record: QRCode,
    scan_data: QRScanRequest,
    current_user: User,
    db: AsyncSession
) -> Dict[str, Any]:
    """Process vehicle QR code scan"""
    try:
        # Get vehicle
        vehicle_id = qr_record.data.get("record_id")
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
        result = await db.execute(stmt)
        vehicle = result.scalar_one_or_none()
        
        if not vehicle:
            return {
                "success": False,
                "message": "Vehicle not found"
            }
        
        # Determine action based on current status
        if vehicle.status == VehicleStatus.PENDING:
            # Check in vehicle
            vehicle.status = VehicleStatus.CHECKED_IN
            action = EntryAction.CHECK_IN
            message = f"Vehicle {vehicle.license_plate} checked in successfully"
            
        elif vehicle.status == VehicleStatus.CHECKED_IN:
            # Check out vehicle
            vehicle.status = VehicleStatus.CHECKED_OUT
            action = EntryAction.CHECK_OUT
            message = f"Vehicle {vehicle.license_plate} checked out successfully"
            
        elif vehicle.status == VehicleStatus.CHECKED_OUT:
            return {
                "success": False,
                "message": "Vehicle has already checked out",
                "vehicle": vehicle.to_dict()
            }
        else:
            return {
                "success": False,
                "message": f"Invalid vehicle status: {vehicle.status.value}",
                "vehicle": vehicle.to_dict()
            }
        
        # Create entry record
        entry = Entry(
            vehicle_id=vehicle.id,
            entry_type=EntryType.VEHICLE,
            action=action,
            location_id=vehicle.location_id,
            operator_id=current_user.id,
            notes=scan_data.notes,
            qr_code_scanned=qr_record.code
        )
        
        db.add(entry)
        await db.commit()
        await db.refresh(vehicle)
        
        logger.info(f"Vehicle QR scan: {vehicle.license_plate} {action.value} by {current_user.username}")
        
        return {
            "success": True,
            "message": message,
            "type": "vehicle",
            "action": action.value,
            "vehicle": vehicle.to_dict(),
            "entry": entry.to_dict()
        }
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error processing vehicle scan: {e}")
        raise

# Generate QR code
@router.post("/api/generate")
async def generate_qr_code(
    generate_data: QRGenerateRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Generate new QR code for record"""
    try:
        # Check location access
        await require_location_access(generate_data.location_id, current_user)
        
        # Validate record type
        if generate_data.record_type not in ["visitor", "vehicle"]:
            raise HTTPException(status_code=400, detail="Invalid record type")
        
        # Check if record exists
        if generate_data.record_type == "visitor":
            stmt = select(Visitor).where(Visitor.id == generate_data.record_id)
            result = await db.execute(stmt)
            record = result.scalar_one_or_none()
        else:
            stmt = select(Vehicle).where(Vehicle.id == generate_data.record_id)
            result = await db.execute(stmt)
            record = result.scalar_one_or_none()
        
        if not record:
            raise HTTPException(status_code=404, detail=f"{generate_data.record_type.title()} not found")
        
        # Check if record already has an active QR code
        if record.qr_code and record.qr_code.is_valid:
            return {
                "success": False,
                "message": "Record already has an active QR code",
                "existing_qr": record.qr_code.to_dict()
            }
        
        # Generate new QR code
        qr_code = qr_generator.generate_unique_code()
        expires_hours = generate_data.expires_hours or settings.qr_code_expiry_hours
        
        qr_data = qr_generator.create_qr_data(
            qr_code,
            generate_data.record_type,
            generate_data.record_id,
            generate_data.location_id,
            expires_hours
        )
        
        # Create QR code record
        qr_record = QRCode(
            code=qr_code,
            type=QRCodeType.VISITOR if generate_data.record_type == "visitor" else QRCodeType.VEHICLE,
            data=qr_data,
            created_by=current_user.id,
            location_id=generate_data.location_id,
            expires_at=datetime.utcnow() + timedelta(hours=expires_hours)
        )
        
        db.add(qr_record)
        await db.commit()
        await db.refresh(qr_record)
        
        # Link QR code to record
        record.qr_code_id = qr_record.id
        await db.commit()
        
        logger.info(f"QR code generated for {generate_data.record_type} {generate_data.record_id} by {current_user.username}")
        
        return {
            "success": True,
            "message": "QR code generated successfully",
            "qr_code": qr_record.to_dict(include_data=True)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error generating QR code: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate QR code")

# Validate QR code
@router.post("/api/validate")
async def validate_qr_code(
    validate_data: QRValidateRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Validate QR code without processing"""
    try:
        # Validate QR data format
        is_valid, qr_content = qr_generator.validate_qr_data(validate_data.qr_code)
        
        if not is_valid:
            return {
                "valid": False,
                "message": "Invalid QR code format",
                "error": qr_content.get("error", "Unknown error") if qr_content else "Invalid format"
            }
        
        # Get QR code record
        qr_code = qr_content["code"]
        stmt = select(QRCode).where(QRCode.code == qr_code)
        result = await db.execute(stmt)
        qr_record = result.scalar_one_or_none()
        
        if not qr_record:
            return {
                "valid": False,
                "message": "QR code not found in system"
            }
        
        # Check if expired
        if qr_record.is_expired:
            return {
                "valid": False,
                "message": "QR code has expired",
                "expired_at": qr_record.expires_at.isoformat() if qr_record.expires_at else None
            }
        
        # Check if active
        if not qr_record.is_active:
            return {
                "valid": False,
                "message": "QR code has been deactivated"
            }
        
        # Get associated record
        record_data = None
        if qr_record.type == QRCodeType.VISITOR:
            visitor_id = qr_record.data.get("record_id")
            stmt = select(Visitor).where(Visitor.id == visitor_id)
            result = await db.execute(stmt)
            visitor = result.scalar_one_or_none()
            if visitor:
                record_data = {
                    "type": "visitor",
                    "record": visitor.to_dict()
                }
        else:
            vehicle_id = qr_record.data.get("record_id")
            stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
            result = await db.execute(stmt)
            vehicle = result.scalar_one_or_none()
            if vehicle:
                record_data = {
                    "type": "vehicle",
                    "record": vehicle.to_dict()
                }
        
        return {
            "valid": True,
            "message": "QR code is valid",
            "qr_code": qr_record.to_dict(),
            "record": record_data,
            "time_until_expiry": qr_record.time_until_expiry
        }
        
    except Exception as e:
        logger.error(f"Error validating QR code: {e}")
        raise HTTPException(status_code=500, detail="Failed to validate QR code")

# Get QR code details
@router.get("/api/{qr_code}")
async def get_qr_details(
    qr_code: str,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get QR code details"""
    try:
        stmt = select(QRCode).where(QRCode.code == qr_code)
        result = await db.execute(stmt)
        qr_record = result.scalar_one_or_none()
        
        if not qr_record:
            raise HTTPException(status_code=404, detail="QR code not found")
        
        # Check location access
        if not current_user.is_admin and current_user.location_id:
            if qr_record.location_id != current_user.location_id:
                raise HTTPException(status_code=403, detail="Access denied for this QR code")
        
        return {
            "qr_code": qr_record.to_dict(include_data=True)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting QR code details: {e}")
        raise HTTPException(status_code=500, detail="Failed to get QR code details")

# Deactivate QR code
@router.post("/api/{qr_code}/deactivate")
async def deactivate_qr_code(
    qr_code: str,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate QR code"""
    try:
        stmt = select(QRCode).where(QRCode.code == qr_code)
        result = await db.execute(stmt)
        qr_record = result.scalar_one_or_none()
        
        if not qr_record:
            raise HTTPException(status_code=404, detail="QR code not found")
        
        # Check location access
        if not current_user.is_admin and current_user.location_id:
            if qr_record.location_id != current_user.location_id:
                raise HTTPException(status_code=403, detail="Access denied for this QR code")
        
        # Deactivate QR code
        qr_record.deactivate()
        await db.commit()
        
        logger.info(f"QR code {qr_code} deactivated by {current_user.username}")
        
        return {
            "success": True,
            "message": "QR code deactivated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deactivating QR code: {e}")
        raise HTTPException(status_code=500, detail="Failed to deactivate QR code")

# Extend QR code expiry
@router.post("/api/{qr_code}/extend")
async def extend_qr_expiry(
    qr_code: str,
    hours: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Extend QR code expiry"""
    try:
        if hours <= 0 or hours > 168:  # Max 1 week
            raise HTTPException(status_code=400, detail="Invalid hours value (1-168)")
        
        stmt = select(QRCode).where(QRCode.code == qr_code)
        result = await db.execute(stmt)
        qr_record = result.scalar_one_or_none()
        
        if not qr_record:
            raise HTTPException(status_code=404, detail="QR code not found")
        
        # Check location access
        if not current_user.is_admin and current_user.location_id:
            if qr_record.location_id != current_user.location_id:
                raise HTTPException(status_code=403, detail="Access denied for this QR code")
        
        # Extend expiry
        qr_record.extend_expiry(hours)
        await db.commit()
        
        logger.info(f"QR code {qr_code} extended by {hours} hours by {current_user.username}")
        
        return {
            "success": True,
            "message": f"QR code expiry extended by {hours} hours",
            "new_expiry": qr_record.expires_at.isoformat() if qr_record.expires_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error extending QR code expiry: {e}")
        raise HTTPException(status_code=500, detail="Failed to extend QR code expiry")

# Get scan history
@router.get("/api/scan-history")
async def get_scan_history(
    limit: int = 50,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get recent scan history"""
    try:
        # Build query for entries with QR codes
        stmt = select(Entry).where(Entry.qr_code_scanned.isnot(None))
        
        # Location filter
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Entry.location_id == current_user.location_id)
        
        # Order by timestamp and limit
        stmt = stmt.order_by(Entry.timestamp.desc()).limit(limit)
        
        result = await db.execute(stmt)
        entries = result.scalars().all()
        
        return {
            "scan_history": [entry.to_dict() for entry in entries]
        }
        
    except Exception as e:
        logger.error(f"Error getting scan history: {e}")
        raise HTTPException(status_code=500, detail="Failed to get scan history")

# QR Code statistics
@router.get("/api/stats")
async def get_qr_stats(
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get QR code statistics"""
    try:
        # Location filter
        location_filter = True
        if not current_user.is_admin and current_user.location_id:
            location_filter = QRCode.location_id == current_user.location_id
        
        # Total QR codes
        total_stmt = select(func.count(QRCode.id)).where(location_filter)
        total_result = await db.execute(total_stmt)
        total_qr_codes = total_result.scalar() or 0
        
        # Active QR codes
        active_stmt = select(func.count(QRCode.id)).where(
            and_(location_filter, QRCode.is_active == True)
        )
        active_result = await db.execute(active_stmt)
        active_qr_codes = active_result.scalar() or 0
        
        # Expired QR codes
        expired_stmt = select(func.count(QRCode.id)).where(
            and_(
                location_filter,
                QRCode.expires_at < datetime.utcnow()
            )
        )
        expired_result = await db.execute(expired_stmt)
        expired_qr_codes = expired_result.scalar() or 0
        
        # Usage stats
        usage_stmt = select(
            func.sum(QRCode.used_count),
            func.avg(QRCode.used_count)
        ).where(location_filter)
        usage_result = await db.execute(usage_stmt)
        total_scans, avg_scans = usage_result.fetchone()
        
        # Recent scans (last 24 hours)
        recent_scans_stmt = select(func.count(Entry.id)).where(
            and_(
                Entry.qr_code_scanned.isnot(None),
                Entry.timestamp >= datetime.utcnow() - timedelta(hours=24),
                location_filter if not current_user.is_admin else True
            )
        )
        recent_result = await db.execute(recent_scans_stmt)
        recent_scans = recent_result.scalar() or 0
        
        return {
            "total_qr_codes": total_qr_codes,
            "active_qr_codes": active_qr_codes,
            "expired_qr_codes": expired_qr_codes,
            "total_scans": int(total_scans) if total_scans else 0,
            "average_scans_per_qr": round(float(avg_scans), 2) if avg_scans else 0,
            "recent_scans_24h": recent_scans
        }
        
    except Exception as e:
        logger.error(f"Error getting QR stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get QR statistics")