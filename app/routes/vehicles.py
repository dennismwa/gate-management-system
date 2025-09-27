"""
Vehicle management routes
Handles vehicle registration, check-in/out, and management
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc, func
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import logging

from ..database import get_db
from ..models.user import User
from ..models.vehicle import Vehicle, VehicleStatus, VehicleType, VehiclePurpose
from ..models.location import Location
from ..models.qr_code import QRCode, QRCodeType
from ..models.entry import Entry, EntryType, EntryAction
from ..utils.security import require_auth, require_location_access
from ..utils.qr_generator import qr_generator
from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="templates")
settings = get_settings()

# Pydantic models
class VehicleCreateRequest(BaseModel):
    license_plate: str
    driver_name: str
    driver_phone: Optional[str] = None
    driver_id: Optional[str] = None
    vehicle_type: str = "car"
    purpose: str = "other"
    company: Optional[str] = None
    notes: Optional[str] = None
    location_id: int

class VehicleUpdateRequest(BaseModel):
    license_plate: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    driver_id: Optional[str] = None
    vehicle_type: Optional[str] = None
    purpose: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None

class VehicleCheckInRequest(BaseModel):
    vehicle_id: int
    notes: Optional[str] = None

class VehicleCheckOutRequest(BaseModel):
    vehicle_id: int
    notes: Optional[str] = None

# Vehicle list page
@router.get("/", response_class=HTMLResponse)
async def vehicles_list(
    request: Request,
    status_filter: Optional[str] = None,
    location_filter: Optional[int] = None,
    search: Optional[str] = None,
    page: int = 1,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Display vehicles list page"""
    try:
        # Get locations for filter
        locations_stmt = select(Location).where(Location.is_active == True)
        if not current_user.is_admin and current_user.location_id:
            locations_stmt = locations_stmt.where(Location.id == current_user.location_id)
        
        locations_result = await db.execute(locations_stmt)
        locations = locations_result.scalars().all()
        
        return templates.TemplateResponse(
            "vehicles/index.html",
            {
                "request": request,
                "user": current_user.to_dict(),
                "locations": [loc.to_dict() for loc in locations],
                "vehicle_types": [vt.value for vt in VehicleType],
                "vehicle_purposes": [vp.value for vp in VehiclePurpose],
                "page_title": "Vehicle Management"
            }
        )
    except Exception as e:
        logger.error(f"Error loading vehicles page: {e}")
        raise HTTPException(status_code=500, detail="Failed to load vehicles page")

# Add vehicle page
@router.get("/add", response_class=HTMLResponse)
async def add_vehicle_page(
    request: Request,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Display add vehicle form"""
    try:
        # Get locations
        locations_stmt = select(Location).where(Location.is_active == True)
        if not current_user.is_admin and current_user.location_id:
            locations_stmt = locations_stmt.where(Location.id == current_user.location_id)
        
        locations_result = await db.execute(locations_stmt)
        locations = locations_result.scalars().all()
        
        return templates.TemplateResponse(
            "vehicles/add.html",
            {
                "request": request,
                "user": current_user.to_dict(),
                "locations": [loc.to_dict() for loc in locations],
                "vehicle_types": [{"value": vt.value, "label": vt.value.replace("_", " ").title()} for vt in VehicleType],
                "vehicle_purposes": [{"value": vp.value, "label": vp.value.replace("_", " ").title()} for vp in VehiclePurpose],
                "page_title": "Add Vehicle"
            }
        )
    except Exception as e:
        logger.error(f"Error loading add vehicle page: {e}")
        raise HTTPException(status_code=500, detail="Failed to load add vehicle page")

# Get vehicles list (API)
@router.get("/api/list")
async def get_vehicles_list(
    status_filter: Optional[str] = None,
    location_filter: Optional[int] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get paginated vehicles list"""
    try:
        # Build query
        stmt = select(Vehicle)
        
        # Location filter based on user permissions
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Vehicle.location_id == current_user.location_id)
        elif location_filter:
            stmt = stmt.where(Vehicle.location_id == location_filter)
        
        # Status filter
        if status_filter and status_filter != "all":
            stmt = stmt.where(Vehicle.status == VehicleStatus(status_filter))
        
        # Search filter
        if search:
            search_pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Vehicle.license_plate.ilike(search_pattern),
                    Vehicle.driver_name.ilike(search_pattern),
                    Vehicle.driver_phone.ilike(search_pattern),
                    Vehicle.company.ilike(search_pattern)
                )
            )
        
        # Get total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await db.execute(count_stmt)
        total = total_result.scalar()
        
        # Apply pagination and ordering
        offset = (page - 1) * limit
        stmt = stmt.order_by(desc(Vehicle.created_at)).offset(offset).limit(limit)
        
        result = await db.execute(stmt)
        vehicles = result.scalars().all()
        
        return {
            "vehicles": [vehicle.to_dict() for vehicle in vehicles],
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
        
    except Exception as e:
        logger.error(f"Error getting vehicles list: {e}")
        raise HTTPException(status_code=500, detail="Failed to load vehicles")

# Create vehicle
@router.post("/api/create")
async def create_vehicle(
    vehicle_data: VehicleCreateRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Create new vehicle"""
    try:
        # Check location access
        await require_location_access(vehicle_data.location_id, current_user)
        
        # Normalize license plate
        license_plate = vehicle_data.license_plate.upper().strip()
        
        # Check if vehicle already exists
        existing_stmt = select(Vehicle).where(
            and_(
                Vehicle.license_plate == license_plate,
                Vehicle.location_id == vehicle_data.location_id,
                Vehicle.status.in_([VehicleStatus.PENDING, VehicleStatus.CHECKED_IN])
            )
        )
        existing_result = await db.execute(existing_stmt)
        existing_vehicle = existing_result.scalar_one_or_none()
        
        if existing_vehicle:
            return {
                "success": False,
                "message": "Vehicle already exists with pending or checked-in status",
                "existing_vehicle": existing_vehicle.to_dict()
            }
        
        # Validate enums
        try:
            vehicle_type = VehicleType(vehicle_data.vehicle_type)
            purpose = VehiclePurpose(vehicle_data.purpose)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid vehicle type or purpose: {e}")
        
        # Create vehicle
        vehicle = Vehicle(
            license_plate=license_plate,
            driver_name=vehicle_data.driver_name,
            driver_phone=vehicle_data.driver_phone,
            driver_id=vehicle_data.driver_id,
            vehicle_type=vehicle_type,
            purpose=purpose,
            company=vehicle_data.company,
            notes=vehicle_data.notes,
            location_id=vehicle_data.location_id,
            created_by=current_user.id,
            status=VehicleStatus.PENDING
        )
        
        db.add(vehicle)
        await db.commit()
        await db.refresh(vehicle)
        
        # Generate QR code
        qr_code = qr_generator.generate_unique_code()
        qr_data = qr_generator.create_qr_data(
            qr_code, "vehicle", vehicle.id, vehicle_data.location_id
        )
        
        # Create QR code record
        qr_record = QRCode(
            code=qr_code,
            type=QRCodeType.VEHICLE,
            data=qr_data,
            created_by=current_user.id,
            location_id=vehicle_data.location_id,
            expires_at=datetime.utcnow() + timedelta(hours=settings.qr_code_expiry_hours)
        )
        
        db.add(qr_record)
        await db.commit()
        await db.refresh(qr_record)
        
        # Link QR code to vehicle
        vehicle.qr_code_id = qr_record.id
        await db.commit()
        await db.refresh(vehicle)
        
        logger.info(f"Vehicle created: {vehicle.license_plate} by {current_user.username}")
        
        return {
            "success": True,
            "message": "Vehicle created successfully",
            "vehicle": vehicle.to_dict(),
            "qr_code": qr_code
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating vehicle: {e}")
        raise HTTPException(status_code=500, detail="Failed to create vehicle")

# Get vehicle details
@router.get("/api/{vehicle_id}")
async def get_vehicle(
    vehicle_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get vehicle details"""
    try:
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
        
        # Location access check
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Vehicle.location_id == current_user.location_id)
        
        result = await db.execute(stmt)
        vehicle = result.scalar_one_or_none()
        
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        
        return {"vehicle": vehicle.to_dict()}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get vehicle")

# Update vehicle
@router.put("/api/{vehicle_id}")
async def update_vehicle(
    vehicle_id: int,
    vehicle_data: VehicleUpdateRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Update vehicle information"""
    try:
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
        
        # Location access check
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Vehicle.location_id == current_user.location_id)
        
        result = await db.execute(stmt)
        vehicle = result.scalar_one_or_none()
        
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        
        # Update fields
        update_fields = vehicle_data.dict(exclude_unset=True)
        for field, value in update_fields.items():
            if field == "license_plate" and value:
                value = value.upper().strip()
            elif field == "vehicle_type" and value:
                value = VehicleType(value)
            elif field == "purpose" and value:
                value = VehiclePurpose(value)
            
            setattr(vehicle, field, value)
        
        await db.commit()
        await db.refresh(vehicle)
        
        logger.info(f"Vehicle {vehicle_id} updated by {current_user.username}")
        
        return {
            "success": True,
            "message": "Vehicle updated successfully",
            "vehicle": vehicle.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update vehicle")

# Check in vehicle
@router.post("/api/check-in")
async def check_in_vehicle(
    check_in_data: VehicleCheckInRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Check in a vehicle"""
    try:
        # Get vehicle
        stmt = select(Vehicle).where(Vehicle.id == check_in_data.vehicle_id)
        
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Vehicle.location_id == current_user.location_id)
        
        result = await db.execute(stmt)
        vehicle = result.scalar_one_or_none()
        
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        
        if vehicle.status == VehicleStatus.CHECKED_IN:
            raise HTTPException(status_code=400, detail="Vehicle is already checked in")
        
        # Update vehicle status
        vehicle.status = VehicleStatus.CHECKED_IN
        
        # Create entry record
        entry = Entry(
            vehicle_id=vehicle.id,
            entry_type=EntryType.VEHICLE,
            action=EntryAction.CHECK_IN,
            location_id=vehicle.location_id,
            operator_id=current_user.id,
            notes=check_in_data.notes
        )
        
        db.add(entry)
        await db.commit()
        await db.refresh(vehicle)
        
        logger.info(f"Vehicle {vehicle.license_plate} checked in by {current_user.username}")
        
        return {
            "success": True,
            "message": f"Vehicle {vehicle.license_plate} checked in successfully",
            "vehicle": vehicle.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error checking in vehicle: {e}")
        raise HTTPException(status_code=500, detail="Failed to check in vehicle")

# Check out vehicle
@router.post("/api/check-out")
async def check_out_vehicle(
    check_out_data: VehicleCheckOutRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Check out a vehicle"""
    try:
        # Get vehicle
        stmt = select(Vehicle).where(Vehicle.id == check_out_data.vehicle_id)
        
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Vehicle.location_id == current_user.location_id)
        
        result = await db.execute(stmt)
        vehicle = result.scalar_one_or_none()
        
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        
        if vehicle.status != VehicleStatus.CHECKED_IN:
            raise HTTPException(status_code=400, detail="Vehicle is not checked in")
        
        # Update vehicle status
        vehicle.status = VehicleStatus.CHECKED_OUT
        
        # Create entry record
        entry = Entry(
            vehicle_id=vehicle.id,
            entry_type=EntryType.VEHICLE,
            action=EntryAction.CHECK_OUT,
            location_id=vehicle.location_id,
            operator_id=current_user.id,
            notes=check_out_data.notes
        )
        
        db.add(entry)
        await db.commit()
        await db.refresh(vehicle)
        
        logger.info(f"Vehicle {vehicle.license_plate} checked out by {current_user.username}")
        
        return {
            "success": True,
            "message": f"Vehicle {vehicle.license_plate} checked out successfully",
            "vehicle": vehicle.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error checking out vehicle: {e}")
        raise HTTPException(status_code=500, detail="Failed to check out vehicle")

# Delete vehicle
@router.delete("/api/{vehicle_id}")
async def delete_vehicle(
    vehicle_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Delete a vehicle (admin only)"""
    try:
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
        result = await db.execute(stmt)
        vehicle = result.scalar_one_or_none()
        
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        
        if vehicle.status == VehicleStatus.CHECKED_IN:
            raise HTTPException(status_code=400, detail="Cannot delete checked-in vehicle")
        
        await db.delete(vehicle)
        await db.commit()
        
        logger.info(f"Vehicle {vehicle_id} deleted by {current_user.username}")
        
        return {
            "success": True,
            "message": "Vehicle deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete vehicle")

# Generate vehicle QR sticker
@router.get("/api/{vehicle_id}/qr-sticker")
async def generate_vehicle_sticker(
    vehicle_id: int,
    size: str = "medium",
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Generate QR code sticker for vehicle"""
    try:
        # Get vehicle with QR code
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
        
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Vehicle.location_id == current_user.location_id)
        
        result = await db.execute(stmt)
        vehicle = result.scalar_one_or_none()
        
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        
        if not vehicle.qr_code:
            raise HTTPException(status_code=404, detail="QR code not found for vehicle")
        
        # Generate sticker
        vehicle_data = vehicle.to_dict()
        qr_data = vehicle.qr_code.data
        
        sticker_img = qr_generator.create_vehicle_sticker(vehicle_data, qr_data, size)
        sticker_base64 = qr_generator.image_to_base64(sticker_img)
        
        return {
            "success": True,
            "sticker": sticker_base64,
            "filename": f"vehicle_{vehicle_id}_sticker.png"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating sticker for vehicle {vehicle_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate sticker")

# Bulk operations
@router.post("/api/bulk-check-out")
async def bulk_check_out_vehicles(
    vehicle_ids: List[int],
    notes: Optional[str] = None,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Bulk check out multiple vehicles"""
    try:
        results = []
        
        for vehicle_id in vehicle_ids:
            try:
                # Get vehicle
                stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
                
                if not current_user.is_admin and current_user.location_id:
                    stmt = stmt.where(Vehicle.location_id == current_user.location_id)
                
                result = await db.execute(stmt)
                vehicle = result.scalar_one_or_none()
                
                if not vehicle:
                    results.append({"vehicle_id": vehicle_id, "success": False, "message": "Vehicle not found"})
                    continue
                
                if vehicle.status != VehicleStatus.CHECKED_IN:
                    results.append({"vehicle_id": vehicle_id, "success": False, "message": "Vehicle not checked in"})
                    continue
                
                # Update vehicle status
                vehicle.status = VehicleStatus.CHECKED_OUT
                
                # Create entry record
                entry = Entry(
                    vehicle_id=vehicle.id,
                    entry_type=EntryType.VEHICLE,
                    action=EntryAction.CHECK_OUT,
                    location_id=vehicle.location_id,
                    operator_id=current_user.id,
                    notes=notes
                )
                
                db.add(entry)
                results.append({"vehicle_id": vehicle_id, "success": True, "message": "Checked out successfully"})
                
            except Exception as e:
                results.append({"vehicle_id": vehicle_id, "success": False, "message": str(e)})
        
        await db.commit()
        
        success_count = sum(1 for r in results if r["success"])
        logger.info(f"Bulk check-out: {success_count}/{len(vehicle_ids)} vehicles by {current_user.username}")
        
        return {
            "success": True,
            "message": f"Processed {len(vehicle_ids)} vehicles, {success_count} successful",
            "results": results
        }
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in bulk check-out: {e}")
        raise HTTPException(status_code=500, detail="Failed to process bulk check-out")

# Vehicle statistics
@router.get("/api/stats")
async def get_vehicle_stats(
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get vehicle statistics"""
    try:
        # Location filter
        location_filter = True
        if not current_user.is_admin and current_user.location_id:
            location_filter = Vehicle.location_id == current_user.location_id
        
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())
        
        # Today's vehicles
        today_stmt = select(func.count(Vehicle.id)).where(
            and_(
                func.date(Vehicle.created_at) == today,
                location_filter
            )
        )
        today_result = await db.execute(today_stmt)
        today_count = today_result.scalar() or 0
        
        # Week's vehicles
        week_stmt = select(func.count(Vehicle.id)).where(
            and_(
                func.date(Vehicle.created_at) >= week_start,
                location_filter
            )
        )
        week_result = await db.execute(week_stmt)
        week_count = week_result.scalar() or 0
        
        # Status breakdown
        status_stmt = select(
            Vehicle.status,
            func.count(Vehicle.id)
        ).where(location_filter).group_by(Vehicle.status)
        
        status_result = await db.execute(status_stmt)
        status_breakdown = {status: count for status, count in status_result.fetchall()}
        
        # Purpose breakdown
        purpose_stmt = select(
            Vehicle.purpose,
            func.count(Vehicle.id)
        ).where(location_filter).group_by(Vehicle.purpose)
        
        purpose_result = await db.execute(purpose_stmt)
        purpose_breakdown = {purpose.value: count for purpose, count in purpose_result.fetchall()}
        
        return {
            "today_vehicles": today_count,
            "week_vehicles": week_count,
            "status_breakdown": status_breakdown,
            "purpose_breakdown": purpose_breakdown,
            "current_checked_in": status_breakdown.get(VehicleStatus.CHECKED_IN, 0)
        }
        
    except Exception as e:
        logger.error(f"Error getting vehicle stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get vehicle statistics")