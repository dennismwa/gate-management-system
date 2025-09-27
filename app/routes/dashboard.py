"""
Dashboard routes for main application interface
Handles dashboard display, statistics, and real-time updates
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from datetime import datetime, date, timedelta
from typing import Dict, Any, List

from ..database import get_db
from ..models.user import User
from ..models.visitor import Visitor, VisitorStatus
from ..models.vehicle import Vehicle, VehicleStatus
from ..models.entry import Entry, EntryAction
from ..models.location import Location
from ..utils.security import require_auth

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/", response_class=HTMLResponse)
async def dashboard_home(
    request: Request,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Main dashboard page"""
    try:
        # Get basic stats for the dashboard
        stats = await get_dashboard_stats(db, current_user)
        
        return templates.TemplateResponse(
            "dashboard/index.html",
            {
                "request": request,
                "user": current_user.to_dict(),
                "stats": stats,
                "page_title": "Dashboard"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats")
async def get_stats(
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get dashboard statistics"""
    stats = await get_dashboard_stats(db, current_user)
    return JSONResponse(content=stats)

@router.get("/activity")
async def get_recent_activity(
    limit: int = 20,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get recent activity feed"""
    try:
        # Build location filter for user access
        location_filter = True
        if not current_user.is_admin and current_user.location_id:
            location_filter = Entry.location_id == current_user.location_id
        
        # Get recent entries with related data
        stmt = (
            select(Entry)
            .where(location_filter)
            .order_by(desc(Entry.timestamp))
            .limit(limit)
        )
        
        result = await db.execute(stmt)
        entries = result.scalars().all()
        
        activity_feed = []
        for entry in entries:
            activity_feed.append(entry.to_dict())
        
        return JSONResponse(content={"activity": activity_feed})
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chart-data")
async def get_chart_data(
    period: str = "week",
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get chart data for dashboard visualizations"""
    try:
        # Calculate date range
        end_date = datetime.now().date()
        
        if period == "week":
            start_date = end_date - timedelta(days=7)
            date_format = "%Y-%m-%d"
        elif period == "month":
            start_date = end_date - timedelta(days=30)
            date_format = "%Y-%m-%d"
        elif period == "year":
            start_date = end_date - timedelta(days=365)
            date_format = "%Y-%m"
        else:
            start_date = end_date - timedelta(days=7)
            date_format = "%Y-%m-%d"
        
        # Build location filter
        location_filter = True
        if not current_user.is_admin and current_user.location_id:
            location_filter = Entry.location_id == current_user.location_id
        
        # Get daily visitor/vehicle counts
        daily_stats = {}
        
        # Visitors check-ins per day
        stmt = (
            select(
                func.date(Entry.timestamp).label('date'),
                func.count(Entry.id).label('count')
            )
            .where(
                and_(
                    Entry.entry_type == 'visitor',
                    Entry.action == EntryAction.CHECK_IN,
                    func.date(Entry.timestamp) >= start_date,
                    func.date(Entry.timestamp) <= end_date,
                    location_filter
                )
            )
            .group_by(func.date(Entry.timestamp))
            .order_by(func.date(Entry.timestamp))
        )
        
        result = await db.execute(stmt)
        visitor_data = result.fetchall()
        
        # Vehicles check-ins per day
        stmt = (
            select(
                func.date(Entry.timestamp).label('date'),
                func.count(Entry.id).label('count')
            )
            .where(
                and_(
                    Entry.entry_type == 'vehicle',
                    Entry.action == EntryAction.CHECK_IN,
                    func.date(Entry.timestamp) >= start_date,
                    func.date(Entry.timestamp) <= end_date,
                    location_filter
                )
            )
            .group_by(func.date(Entry.timestamp))
            .order_by(func.date(Entry.timestamp))
        )
        
        result = await db.execute(stmt)
        vehicle_data = result.fetchall()
        
        # Create chart data
        chart_data = {
            "labels": [],
            "visitors": [],
            "vehicles": []
        }
        
        # Create date range
        current_date = start_date
        visitor_dict = {row.date: row.count for row in visitor_data}
        vehicle_dict = {row.date: row.count for row in vehicle_data}
        
        while current_date <= end_date:
            chart_data["labels"].append(current_date.strftime(date_format))
            chart_data["visitors"].append(visitor_dict.get(current_date, 0))
            chart_data["vehicles"].append(vehicle_dict.get(current_date, 0))
            current_date += timedelta(days=1)
        
        return JSONResponse(content=chart_data)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def get_dashboard_stats(db: AsyncSession, user: User) -> Dict[str, Any]:
    """Get comprehensive dashboard statistics"""
    
    # Build location filter based on user access
    location_filter = True
    if not user.is_admin and user.location_id:
        location_filter_visitors = Visitor.location_id == user.location_id
        location_filter_vehicles = Vehicle.location_id == user.location_id
        location_filter_entries = Entry.location_id == user.location_id
    else:
        location_filter_visitors = True
        location_filter_vehicles = True
        location_filter_entries = True
    
    today = date.today()
    
    # Current visitors inside
    stmt = select(func.count(Visitor.id)).where(
        and_(
            Visitor.status == VisitorStatus.CHECKED_IN,
            location_filter_visitors
        )
    )
    result = await db.execute(stmt)
    current_visitors = result.scalar() or 0
    
    # Current vehicles inside
    stmt = select(func.count(Vehicle.id)).where(
        and_(
            Vehicle.status == VehicleStatus.CHECKED_IN,
            location_filter_vehicles
        )
    )
    result = await db.execute(stmt)
    current_vehicles = result.scalar() or 0
    
    # Today's visitor check-ins
    stmt = select(func.count(Entry.id)).where(
        and_(
            Entry.entry_type == 'visitor',
            Entry.action == EntryAction.CHECK_IN,
            func.date(Entry.timestamp) == today,
            location_filter_entries
        )
    )
    result = await db.execute(stmt)
    todays_visitors = result.scalar() or 0
    
    # Today's vehicle check-ins
    stmt = select(func.count(Entry.id)).where(
        and_(
            Entry.entry_type == 'vehicle',
            Entry.action == EntryAction.CHECK_IN,
            func.date(Entry.timestamp) == today,
            location_filter_entries
        )
    )
    result = await db.execute(stmt)
    todays_vehicles = result.scalar() or 0
    
    # This week's stats
    week_start = today - timedelta(days=today.weekday())
    
    stmt = select(func.count(Entry.id)).where(
        and_(
            Entry.entry_type == 'visitor',
            Entry.action == EntryAction.CHECK_IN,
            func.date(Entry.timestamp) >= week_start,
            location_filter_entries
        )
    )
    result = await db.execute(stmt)
    week_visitors = result.scalar() or 0
    
    stmt = select(func.count(Entry.id)).where(
        and_(
            Entry.entry_type == 'vehicle',
            Entry.action == EntryAction.CHECK_IN,
            func.date(Entry.timestamp) >= week_start,
            location_filter_entries
        )
    )
    result = await db.execute(stmt)
    week_vehicles = result.scalar() or 0
    
    # Get recent visitors
    stmt = (
        select(Visitor)
        .where(location_filter_visitors)
        .order_by(desc(Visitor.created_at))
        .limit(5)
    )
    result = await db.execute(stmt)
    recent_visitors = [v.to_dict() for v in result.scalars().all()]
    
    # Get recent vehicles
    stmt = (
        select(Vehicle)
        .where(location_filter_vehicles)
        .order_by(desc(Vehicle.created_at))
        .limit(5)
    )
    result = await db.execute(stmt)
    recent_vehicles = [v.to_dict() for v in result.scalars().all()]
    
    # Get user's location info
    user_location = None
    if user.location_id:
        stmt = select(Location).where(Location.id == user.location_id)
        result = await db.execute(stmt)
        location = result.scalar_one_or_none()
        if location:
            user_location = location.to_dict()
    
    return {
        "current_visitors": current_visitors,
        "current_vehicles": current_vehicles,
        "todays_visitors": todays_visitors,
        "todays_vehicles": todays_vehicles,
        "week_visitors": week_visitors,
        "week_vehicles": week_vehicles,
        "total_today": todays_visitors + todays_vehicles,
        "total_week": week_visitors + week_vehicles,
        "recent_visitors": recent_visitors,
        "recent_vehicles": recent_vehicles,
        "user_location": user_location,
        "last_updated": datetime.now().isoformat()
    }

@router.get("/locations")
async def get_locations(
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get locations accessible to current user"""
    
    if current_user.is_admin:
        # Admin can see all locations
        stmt = select(Location).where(Location.is_active == True).order_by(Location.name)
    else:
        # Operator can only see their assigned location
        stmt = select(Location).where(
            and_(
                Location.id == current_user.location_id,
                Location.is_active == True
            )
        )
    
    result = await db.execute(stmt)
    locations = result.scalars().all()
    
    return JSONResponse(content={
        "locations": [location.to_dict() for location in locations]
    })

@router.get("/quick-actions")
async def get_quick_actions(
    current_user: User = Depends(require_auth)
):
    """Get quick action buttons for dashboard"""
    
    actions = [
        {
            "id": "add_visitor",
            "title": "Add Visitor",
            "icon": "user-plus",
            "url": "/visitors/add",
            "color": "blue"
        },
        {
            "id": "add_vehicle", 
            "title": "Add Vehicle",
            "icon": "truck",
            "url": "/vehicles/add",
            "color": "green"
        },
        {
            "id": "scan_qr",
            "title": "Scan QR Code",
            "icon": "qr-code",
            "url": "/qr/scan",
            "color": "purple"
        }
    ]
    
    if current_user.is_admin:
        actions.extend([
            {
                "id": "manage_users",
                "title": "Manage Users",
                "icon": "users",
                "url": "/admin/users",
                "color": "red"
            },
            {
                "id": "system_settings",
                "title": "Settings",
                "icon": "settings",
                "url": "/admin/settings",
                "color": "gray"
            }
        ])
    
    return JSONResponse(content={"actions": actions})