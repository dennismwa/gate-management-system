"""
Visitor management routes
Handles visitor registration, check-in/out, and management
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc, func
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from typing import Optional, List
import os
import logging

from ..database import get_db
from ..models.user import User
from ..models.visitor import Visitor, VisitorStatus
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
class VisitorCreateRequest(BaseModel):
    full_name: str
    phone: Optional[str] = None
    id_number: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    purpose: Optional[str] = None
    host_name: Optional[str] = None
    host_phone: Optional[str] = None
    expected_duration: Optional[int] = None
    location_id: int

class VisitorUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    id_number: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    purpose: Optional[str] = None
    host_name: Optional[str] = None
    host_phone: Optional[str] = None
    expected_duration: Optional[int] = None

class VisitorCheckInRequest(BaseModel):
    visitor_id: int
    notes: Optional[str] = None

class VisitorCheckOutRequest(BaseModel):
    visitor_id: int
    notes: Optional[str] = None

# Visitor list page
@router.get("/", response_class=HTMLResponse)
async def visitors_list(
    request: Request,
    status_filter: Optional[str] = None,
    location_filter: Optional[int] = None,
    search: Optional[str] = None,
    page: int = 1,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Display visitors list page"""
    try:
        # Get locations for filter
        locations_stmt = select(Location).where(Location.is_active == True)
        if not current_user.is_admin and current_user.location_id:
            locations_stmt = locations_stmt.where(Location.id == current_user.location_id)
        
        locations_result = await db.execute(locations_stmt)
        locations = locations_result.scalars().all()
        
        return templates.TemplateResponse(
            "visitors/index.html",
            {
                "request": request,
                "user": current_user.to_dict(),
                "locations": [loc.to_dict() for loc in locations],
                "page_title": "Visitor Management"
            }
        )
    except Exception as e:
        logger.error(f"Error loading visitors page: {e}")
        raise HTTPException(status_code=500, detail="Failed to load visitors page")

# Add visitor page
@router.get("/add", response_class=HTMLResponse)
async def add_visitor_page(
    request: Request,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Display add visitor form"""
    try:
        # Get locations
        locations_stmt = select(Location).where(Location.is_active == True)
        if not current_user.is_admin and current_user.location_id:
            locations_stmt = locations_stmt.where(Location.id == current_user.location_id)
        
        locations_result = await db.execute(locations_stmt)
        locations = locations_result.scalars().all()
        
        return templates.TemplateResponse(
            "visitors/add.html",
            {
                "request": request,
                "user": current_user.to_dict(),
                "locations": [loc.to_dict() for loc in locations],
                "page_title": "Add Visitor"
            }
        )
    except Exception as e:
        logger.error(f"Error loading add visitor page: {e}")
        raise HTTPException(status_code=500, detail="Failed to load add visitor page")

# Get visitors list (API)
@router.get("/api/list")
async def get_visitors_list(
    status_filter: Optional[str] = None,
    location_filter: Optional[int] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get paginated visitors list"""
    try:
        # Build query
        stmt = select(Visitor)
        
        # Location filter based on user permissions
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Visitor.location_id == current_user.location_id)
        elif location_filter:
            stmt = stmt.where(Visitor.location_id == location_filter)
        
        # Status filter
        if status_filter and status_filter != "all":
            stmt = stmt.where(Visitor.status == VisitorStatus(status_filter))
        
        # Search filter
        if search:
            search_pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Visitor.full_name.ilike(search_pattern),
                    Visitor.phone.ilike(search_pattern),
                    Visitor.company.ilike(search_pattern),
                    Visitor.id_number.ilike(search_pattern)
                )
            )
        
        # Get total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await db.execute(count_stmt)
        total = total_result.scalar()
        
        # Apply pagination and ordering
        offset = (page - 1) * limit
        stmt = stmt.order_by(desc(Visitor.created_at)).offset(offset).limit(limit)
        
        result = await db.execute(stmt)
        visitors = result.scalars().all()
        
        return {
            "visitors": [visitor.to_dict() for visitor in visitors],
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
        
    except Exception as e:
        logger.error(f"Error getting visitors list: {e}")
        raise HTTPException(status_code=500, detail="Failed to load visitors")

# Create visitor
@router.post("/api/create")
async def create_visitor(
    visitor_data: VisitorCreateRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Create new visitor"""
    try:
        # Check location access
        await require_location_access(visitor_data.location_id, current_user)
        
        # Check if visitor already exists (by phone or ID)
        if visitor_data.phone or visitor_data.id_number:
            existing_stmt = select(Visitor).where(
                and_(
                    Visitor.location_id == visitor_data.location_id,
                    or_(
                        Visitor.phone == visitor_data.phone if visitor_data.phone else False,
                        Visitor.id_number == visitor_data.id_number if visitor_data.id_number else False
                    ),
                    Visitor.status.in_([VisitorStatus.PENDING, VisitorStatus.CHECKED_IN])
                )
            )
            existing_result = await db.execute(existing_stmt)
            existing_visitor = existing_result.scalar_one_or_none()
            
            if existing_visitor:
                return {
                    "success": False,
                    "message": "Visitor already exists with pending or checked-in status",
                    "existing_visitor": existing_visitor.to_dict()
                }
        
        # Create visitor
        visitor = Visitor(
            full_name=visitor_data.full_name,
            phone=visitor_data.phone,
            id_number=visitor_data.id_number,
            email=visitor_data.email,
            company=visitor_data.company,
            purpose=visitor_data.purpose,
            host_name=visitor_data.host_name,
            host_phone=visitor_data.host_phone,
            expected_duration=visitor_data.expected_duration,
            location_id=visitor_data.location_id,
            created_by=current_user.id,
            status=VisitorStatus.PENDING
        )
        
        db.add(visitor)
        await db.commit()
        await db.refresh(visitor)
        
        # Generate QR code
        qr_code = qr_generator.generate_unique_code()
        qr_data = qr_generator.create_qr_data(
            qr_code, "visitor", visitor.id, visitor_data.location_id
        )
        
        # Create QR code record
        qr_record = QRCode(
            code=qr_code,
            type=QRCodeType.VISITOR,
            data=qr_data,
            created_by=current_user.id,
            location_id=visitor_data.location_id,
            expires_at=datetime.utcnow() + timedelta(hours=settings.qr_code_expiry_hours)
        )
        
        db.add(qr_record)
        await db.commit()
        await db.refresh(qr_record)
        
        # Link QR code to visitor
        visitor.qr_code_id = qr_record.id
        await db.commit()
        await db.refresh(visitor)
        
        logger.info(f"Visitor created: {visitor.full_name} by {current_user.username}")
        
        return {
            "success": True,
            "message": "Visitor created successfully",
            "visitor": visitor.to_dict(),
            "qr_code": qr_code
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating visitor: {e}")
        raise HTTPException(status_code=500, detail="Failed to create visitor")

# Get visitor details
@router.get("/api/{visitor_id}")
async def get_visitor(
    visitor_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get visitor details"""
    try:
        stmt = select(Visitor).where(Visitor.id == visitor_id)
        
        # Location access check
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Visitor.location_id == current_user.location_id)
        
        result = await db.execute(stmt)
        visitor = result.scalar_one_or_none()
        
        if not visitor:
            raise HTTPException(status_code=404, detail="Visitor not found")
        
        return {"visitor": visitor.to_dict()}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting visitor {visitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get visitor")

# Update visitor
@router.put("/api/{visitor_id}")
async def update_visitor(
    visitor_id: int,
    visitor_data: VisitorUpdateRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Update visitor information"""
    try:
        stmt = select(Visitor).where(Visitor.id == visitor_id)
        
        # Location access check
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Visitor.location_id == current_user.location_id)
        
        result = await db.execute(stmt)
        visitor = result.scalar_one_or_none()
        
        if not visitor:
            raise HTTPException(status_code=404, detail="Visitor not found")
        
        # Update fields
        update_fields = visitor_data.dict(exclude_unset=True)
        for field, value in update_fields.items():
            setattr(visitor, field, value)
        
        await db.commit()
        await db.refresh(visitor)
        
        logger.info(f"Visitor {visitor_id} updated by {current_user.username}")
        
        return {
            "success": True,
            "message": "Visitor updated successfully",
            "visitor": visitor.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating visitor {visitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update visitor")

# Check in visitor
@router.post("/api/check-in")
async def check_in_visitor(
    check_in_data: VisitorCheckInRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Check in a visitor"""
    try:
        # Get visitor
        stmt = select(Visitor).where(Visitor.id == check_in_data.visitor_id)
        
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Visitor.location_id == current_user.location_id)
        
        result = await db.execute(stmt)
        visitor = result.scalar_one_or_none()
        
        if not visitor:
            raise HTTPException(status_code=404, detail="Visitor not found")
        
        if visitor.status == VisitorStatus.CHECKED_IN:
            raise HTTPException(status_code=400, detail="Visitor is already checked in")
        
        # Update visitor status
        visitor.status = VisitorStatus.CHECKED_IN
        
        # Create entry record
        entry = Entry(
            visitor_id=visitor.id,
            entry_type=EntryType.VISITOR,
            action=EntryAction.CHECK_IN,
            location_id=visitor.location_id,
            operator_id=current_user.id,
            notes=check_in_data.notes
        )
        
        db.add(entry)
        await db.commit()
        await db.refresh(visitor)
        
        logger.info(f"Visitor {visitor.full_name} checked in by {current_user.username}")
        
        return {
            "success": True,
            "message": f"{visitor.full_name} checked in successfully",
            "visitor": visitor.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error checking in visitor: {e}")
        raise HTTPException(status_code=500, detail="Failed to check in visitor")

# Check out visitor
@router.post("/api/check-out")
async def check_out_visitor(
    check_out_data: VisitorCheckOutRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Check out a visitor"""
    try:
        # Get visitor
        stmt = select(Visitor).where(Visitor.id == check_out_data.visitor_id)
        
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Visitor.location_id == current_user.location_id)
        
        result = await db.execute(stmt)
        visitor = result.scalar_one_or_none()
        
        if not visitor:
            raise HTTPException(status_code=404, detail="Visitor not found")
        
        if visitor.status != VisitorStatus.CHECKED_IN:
            raise HTTPException(status_code=400, detail="Visitor is not checked in")
        
        # Update visitor status
        visitor.status = VisitorStatus.CHECKED_OUT
        
        # Create entry record
        entry = Entry(
            visitor_id=visitor.id,
            entry_type=EntryType.VISITOR,
            action=EntryAction.CHECK_OUT,
            location_id=visitor.location_id,
            operator_id=current_user.id,
            notes=check_out_data.notes
        )
        
        db.add(entry)
        await db.commit()
        await db.refresh(visitor)
        
        logger.info(f"Visitor {visitor.full_name} checked out by {current_user.username}")
        
        return {
            "success": True,
            "message": f"{visitor.full_name} checked out successfully",
            "visitor": visitor.to_dict()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error checking out visitor: {e}")
        raise HTTPException(status_code=500, detail="Failed to check out visitor")

# Delete visitor
@router.delete("/api/{visitor_id}")
async def delete_visitor(
    visitor_id: int,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Delete a visitor (admin only)"""
    try:
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        stmt = select(Visitor).where(Visitor.id == visitor_id)
        result = await db.execute(stmt)
        visitor = result.scalar_one_or_none()
        
        if not visitor:
            raise HTTPException(status_code=404, detail="Visitor not found")
        
        if visitor.status == VisitorStatus.CHECKED_IN:
            raise HTTPException(status_code=400, detail="Cannot delete checked-in visitor")
        
        await db.delete(visitor)
        await db.commit()
        
        logger.info(f"Visitor {visitor_id} deleted by {current_user.username}")
        
        return {
            "success": True,
            "message": "Visitor deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting visitor {visitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete visitor")

# Generate visitor QR sticker
@router.get("/api/{visitor_id}/qr-sticker")
async def generate_visitor_sticker(
    visitor_id: int,
    size: str = "medium",
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Generate QR code sticker for visitor"""
    try:
        # Get visitor with QR code
        stmt = select(Visitor).where(Visitor.id == visitor_id)
        
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Visitor.location_id == current_user.location_id)
        
        result = await db.execute(stmt)
        visitor = result.scalar_one_or_none()
        
        if not visitor:
            raise HTTPException(status_code=404, detail="Visitor not found")
        
        if not visitor.qr_code:
            raise HTTPException(status_code=404, detail="QR code not found for visitor")
        
        # Generate sticker
        visitor_data = visitor.to_dict()
        qr_data = visitor.qr_code.data
        
        sticker_img = qr_generator.create_visitor_sticker(visitor_data, qr_data, size)
        sticker_base64 = qr_generator.image_to_base64(sticker_img)
        
        return {
            "success": True,
            "sticker": sticker_base64,
            "filename": f"visitor_{visitor_id}_sticker.png"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating sticker for visitor {visitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate sticker")

# Bulk operations
@router.post("/api/bulk-check-out")
async def bulk_check_out_visitors(
    visitor_ids: List[int],
    notes: Optional[str] = None,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Bulk check out multiple visitors"""
    try:
        results = []
        
        for visitor_id in visitor_ids:
            try:
                # Get visitor
                stmt = select(Visitor).where(Visitor.id == visitor_id)
                
                if not current_user.is_admin and current_user.location_id:
                    stmt = stmt.where(Visitor.location_id == current_user.location_id)
                
                result = await db.execute(stmt)
                visitor = result.scalar_one_or_none()
                
                if not visitor:
                    results.append({"visitor_id": visitor_id, "success": False, "message": "Visitor not found"})
                    continue
                
                if visitor.status != VisitorStatus.CHECKED_IN:
                    results.append({"visitor_id": visitor_id, "success": False, "message": "Visitor not checked in"})
                    continue
                
                # Update visitor status
                visitor.status = VisitorStatus.CHECKED_OUT
                
                # Create entry record
                entry = Entry(
                    visitor_id=visitor.id,
                    entry_type=EntryType.VISITOR,
                    action=EntryAction.CHECK_OUT,
                    location_id=visitor.location_id,
                    operator_id=current_user.id,
                    notes=notes
                )
                
                db.add(entry)
                results.append({"visitor_id": visitor_id, "success": True, "message": "Checked out successfully"})
                
            except Exception as e:
                results.append({"visitor_id": visitor_id, "success": False, "message": str(e)})
        
        await db.commit()
        
        success_count = sum(1 for r in results if r["success"])
        logger.info(f"Bulk check-out: {success_count}/{len(visitor_ids)} visitors by {current_user.username}")
        
        return {
            "success": True,
            "message": f"Processed {len(visitor_ids)} visitors, {success_count} successful",
            "results": results
        }
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error in bulk check-out: {e}")
        raise HTTPException(status_code=500, detail="Failed to process bulk check-out")

# Visitor statistics
@router.get("/api/stats")
async def get_visitor_stats(
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get visitor statistics"""
    try:
        # Location filter
        location_filter = True
        if not current_user.is_admin and current_user.location_id:
            location_filter = Visitor.location_id == current_user.location_id
        
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())
        
        # Today's visitors
        today_stmt = select(func.count(Visitor.id)).where(
            and_(
                func.date(Visitor.created_at) == today,
                location_filter
            )
        )
        today_result = await db.execute(today_stmt)
        today_count = today_result.scalar() or 0
        
        # Week's visitors
        week_stmt = select(func.count(Visitor.id)).where(
            and_(
                func.date(Visitor.created_at) >= week_start,
                location_filter
            )
        )
        week_result = await db.execute(week_stmt)
        week_count = week_result.scalar() or 0
        
        # Status breakdown
        status_stmt = select(
            Visitor.status,
            func.count(Visitor.id)
        ).where(location_filter).group_by(Visitor.status)
        
        status_result = await db.execute(status_stmt)
        status_breakdown = {status: count for status, count in status_result.fetchall()}
        
        return {
            "today_visitors": today_count,
            "week_visitors": week_count,
            "status_breakdown": status_breakdown,
            "current_checked_in": status_breakdown.get(VisitorStatus.CHECKED_IN, 0)
        }
        
    except Exception as e:
        logger.error(f"Error getting visitor stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get visitor statistics")