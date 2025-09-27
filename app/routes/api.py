"""
General API routes for external integrations and mobile apps
Provides RESTful API endpoints for third-party access
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc, func
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any
import logging

from ..database import get_db, DatabaseManager
from ..models.user import User, UserRole
from ..models.visitor import Visitor, VisitorStatus
from ..models.vehicle import Vehicle, VehicleStatus
from ..models.location import Location
from ..models.entry import Entry, EntryType, EntryAction
from ..models.audit_log import AuditLog
from ..utils.security import require_auth, require_admin, get_current_user
from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

# Pydantic models for API responses
class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: datetime = datetime.utcnow()

class PaginatedResponse(BaseModel):
    success: bool = True
    data: List[Dict[str, Any]]
    pagination: Dict[str, Any]
    timestamp: datetime = datetime.utcnow()

class SystemHealthResponse(BaseModel):
    status: str
    version: str
    database: Dict[str, Any]
    uptime: str
    timestamp: datetime

# System health endpoint
@router.get("/health", response_model=SystemHealthResponse)
async def system_health(db: AsyncSession = Depends(get_db)):
    """Get system health status"""
    try:
        # Database health check
        db_health = await DatabaseManager.health_check()
        
        # Calculate uptime (approximate)
        uptime_start = datetime.utcnow() - timedelta(hours=1)  # Placeholder
        uptime = str(datetime.utcnow() - uptime_start)
        
        return SystemHealthResponse(
            status="healthy" if db_health["status"] == "healthy" else "unhealthy",
            version="1.0.0",
            database=db_health,
            uptime=uptime,
            timestamp=datetime.utcnow()
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return SystemHealthResponse(
            status="unhealthy",
            version="1.0.0",
            database={"status": "unhealthy", "error": str(e)},
            uptime="unknown",
            timestamp=datetime.utcnow()
        )

# System statistics
@router.get("/stats")
async def system_stats(
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get comprehensive system statistics"""
    try:
        # Location filter
        location_filter = True
        if not current_user.is_admin and current_user.location_id:
            visitor_location_filter = Visitor.location_id == current_user.location_id
            vehicle_location_filter = Vehicle.location_id == current_user.location_id
            entry_location_filter = Entry.location_id == current_user.location_id
        else:
            visitor_location_filter = True
            vehicle_location_filter = True
            entry_location_filter = True
        
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        
        # Visitor statistics
        visitor_stats = {}
        
        # Total visitors
        total_visitors_stmt = select(func.count(Visitor.id)).where(visitor_location_filter)
        total_visitors_result = await db.execute(total_visitors_stmt)
        visitor_stats["total"] = total_visitors_result.scalar() or 0
        
        # Current checked-in visitors
        checked_in_visitors_stmt = select(func.count(Visitor.id)).where(
            and_(visitor_location_filter, Visitor.status == VisitorStatus.CHECKED_IN)
        )
        checked_in_visitors_result = await db.execute(checked_in_visitors_stmt)
        visitor_stats["current_checked_in"] = checked_in_visitors_result.scalar() or 0
        
        # Today's visitors
        today_visitors_stmt = select(func.count(Visitor.id)).where(
            and_(visitor_location_filter, func.date(Visitor.created_at) == today)
        )
        today_visitors_result = await db.execute(today_visitors_stmt)
        visitor_stats["today"] = today_visitors_result.scalar() or 0
        
        # This week's visitors
        week_visitors_stmt = select(func.count(Visitor.id)).where(
            and_(visitor_location_filter, func.date(Visitor.created_at) >= week_start)
        )
        week_visitors_result = await db.execute(week_visitors_stmt)
        visitor_stats["this_week"] = week_visitors_result.scalar() or 0
        
        # This month's visitors
        month_visitors_stmt = select(func.count(Visitor.id)).where(
            and_(visitor_location_filter, func.date(Visitor.created_at) >= month_start)
        )
        month_visitors_result = await db.execute(month_visitors_stmt)
        visitor_stats["this_month"] = month_visitors_result.scalar() or 0
        
        # Vehicle statistics
        vehicle_stats = {}
        
        # Total vehicles
        total_vehicles_stmt = select(func.count(Vehicle.id)).where(vehicle_location_filter)
        total_vehicles_result = await db.execute(total_vehicles_stmt)
        vehicle_stats["total"] = total_vehicles_result.scalar() or 0
        
        # Current checked-in vehicles
        checked_in_vehicles_stmt = select(func.count(Vehicle.id)).where(
            and_(vehicle_location_filter, Vehicle.status == VehicleStatus.CHECKED_IN)
        )
        checked_in_vehicles_result = await db.execute(checked_in_vehicles_stmt)
        vehicle_stats["current_checked_in"] = checked_in_vehicles_result.scalar() or 0
        
        # Today's vehicles
        today_vehicles_stmt = select(func.count(Vehicle.id)).where(
            and_(vehicle_location_filter, func.date(Vehicle.created_at) == today)
        )
        today_vehicles_result = await db.execute(today_vehicles_stmt)
        vehicle_stats["today"] = today_vehicles_result.scalar() or 0
        
        # This week's vehicles
        week_vehicles_stmt = select(func.count(Vehicle.id)).where(
            and_(vehicle_location_filter, func.date(Vehicle.created_at) >= week_start)
        )
        week_vehicles_result = await db.execute(week_vehicles_stmt)
        vehicle_stats["this_week"] = week_vehicles_result.scalar() or 0
        
        # Entry statistics
        entry_stats = {}
        
        # Today's entries
        today_entries_stmt = select(func.count(Entry.id)).where(
            and_(entry_location_filter, func.date(Entry.timestamp) == today)
        )
        today_entries_result = await db.execute(today_entries_stmt)
        entry_stats["today"] = today_entries_result.scalar() or 0
        
        # Check-ins vs check-outs today
        today_checkins_stmt = select(func.count(Entry.id)).where(
            and_(
                entry_location_filter,
                func.date(Entry.timestamp) == today,
                Entry.action == EntryAction.CHECK_IN
            )
        )
        today_checkins_result = await db.execute(today_checkins_stmt)
        entry_stats["today_checkins"] = today_checkins_result.scalar() or 0
        
        today_checkouts_stmt = select(func.count(Entry.id)).where(
            and_(
                entry_location_filter,
                func.date(Entry.timestamp) == today,
                Entry.action == EntryAction.CHECK_OUT
            )
        )
        today_checkouts_result = await db.execute(today_checkouts_stmt)
        entry_stats["today_checkouts"] = today_checkouts_result.scalar() or 0
        
        # Peak hours analysis (last 7 days)
        peak_hours_stmt = select(
            func.hour(Entry.timestamp).label('hour'),
            func.count(Entry.id).label('count')
        ).where(
            and_(
                entry_location_filter,
                Entry.timestamp >= datetime.utcnow() - timedelta(days=7)
            )
        ).group_by(func.hour(Entry.timestamp)).order_by(func.count(Entry.id).desc())
        
        peak_hours_result = await db.execute(peak_hours_stmt)
        peak_hours = [{"hour": hour, "count": count} for hour, count in peak_hours_result.fetchall()]
        
        return APIResponse(
            success=True,
            message="Statistics retrieved successfully",
            data={
                "visitors": visitor_stats,
                "vehicles": vehicle_stats,
                "entries": entry_stats,
                "peak_hours": peak_hours[:5],  # Top 5 peak hours
                "summary": {
                    "total_current": visitor_stats["current_checked_in"] + vehicle_stats["current_checked_in"],
                    "total_today": visitor_stats["today"] + vehicle_stats["today"],
                    "total_week": visitor_stats["this_week"] + vehicle_stats["this_week"]
                }
            }
        ).dict()
        
    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve statistics")

# Activity feed
@router.get("/activity")
async def get_activity_feed(
    limit: int = 20,
    offset: int = 0,
    entry_type: Optional[str] = None,
    action: Optional[str] = None,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Get recent activity feed"""
    try:
        # Build query
        stmt = select(Entry)
        
        # Location filter
        if not current_user.is_admin and current_user.location_id:
            stmt = stmt.where(Entry.location_id == current_user.location_id)
        
        # Type filter
        if entry_type and entry_type in ["visitor", "vehicle"]:
            stmt = stmt.where(Entry.entry_type == EntryType(entry_type))
        
        # Action filter
        if action and action in ["check_in", "check_out"]:
            stmt = stmt.where(Entry.action == EntryAction(action))
        
        # Get total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await db.execute(count_stmt)
        total = total_result.scalar()
        
        # Apply pagination and ordering
        stmt = stmt.order_by(desc(Entry.timestamp)).offset(offset).limit(limit)
        
        result = await db.execute(stmt)
        entries = result.scalars().all()
        
        return PaginatedResponse(
            data=[entry.to_dict() for entry in entries],
            pagination={
                "total": total,
                "limit": limit,
                "offset": offset,
                "pages": (total + limit - 1) // limit if limit > 0 else 1
            }
        ).dict()
        
    except Exception as e:
        logger.error(f"Error getting activity feed: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve activity feed")

# Search across all entities
@router.get("/search")
async def global_search(
    query: str,
    entity_type: Optional[str] = None,
    limit: int = 10,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Global search across visitors, vehicles, and entries"""
    try:
        if len(query.strip()) < 2:
            raise HTTPException(status_code=400, detail="Search query must be at least 2 characters")
        
        search_pattern = f"%{query}%"
        results = {"visitors": [], "vehicles": [], "entries": []}
        
        # Location filter
        visitor_location_filter = True
        vehicle_location_filter = True
        entry_location_filter = True
        
        if not current_user.is_admin and current_user.location_id:
            visitor_location_filter = Visitor.location_id == current_user.location_id
            vehicle_location_filter = Vehicle.location_id == current_user.location_id
            entry_location_filter = Entry.location_id == current_user.location_id
        
        # Search visitors
        if not entity_type or entity_type == "visitors":
            visitor_stmt = select(Visitor).where(
                and_(
                    visitor_location_filter,
                    or_(
                        Visitor.full_name.ilike(search_pattern),
                        Visitor.phone.ilike(search_pattern),
                        Visitor.company.ilike(search_pattern),
                        Visitor.id_number.ilike(search_pattern),
                        Visitor.email.ilike(search_pattern)
                    )
                )
            ).order_by(desc(Visitor.created_at)).limit(limit)
            
            visitor_result = await db.execute(visitor_stmt)
            visitors = visitor_result.scalars().all()
            results["visitors"] = [visitor.to_dict() for visitor in visitors]
        
        # Search vehicles
        if not entity_type or entity_type == "vehicles":
            vehicle_stmt = select(Vehicle).where(
                and_(
                    vehicle_location_filter,
                    or_(
                        Vehicle.license_plate.ilike(search_pattern),
                        Vehicle.driver_name.ilike(search_pattern),
                        Vehicle.driver_phone.ilike(search_pattern),
                        Vehicle.company.ilike(search_pattern)
                    )
                )
            ).order_by(desc(Vehicle.created_at)).limit(limit)
            
            vehicle_result = await db.execute(vehicle_stmt)
            vehicles = vehicle_result.scalars().all()
            results["vehicles"] = [vehicle.to_dict() for vehicle in vehicles]
        
        # Search entries (by notes)
        if not entity_type or entity_type == "entries":
            entry_stmt = select(Entry).where(
                and_(
                    entry_location_filter,
                    Entry.notes.ilike(search_pattern)
                )
            ).order_by(desc(Entry.timestamp)).limit(limit)
            
            entry_result = await db.execute(entry_stmt)
            entries = entry_result.scalars().all()
            results["entries"] = [entry.to_dict() for entry in entries]
        
        # Calculate total results
        total_results = len(results["visitors"]) + len(results["vehicles"]) + len(results["entries"])
        
        return APIResponse(
            success=True,
            message=f"Found {total_results} results for '{query}'",
            data={
                "query": query,
                "total_results": total_results,
                "results": results
            }
        ).dict()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in global search: {e}")
        raise HTTPException(status_code=500, detail="Search failed")

# Export data
@router.get("/export")
async def export_data(
    entity_type: str,
    format: str = "json",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(require_admin),  # Admin only
    db: AsyncSession = Depends(get_db)
):
    """Export data in various formats"""
    try:
        if entity_type not in ["visitors", "vehicles", "entries", "audit_logs"]:
            raise HTTPException(status_code=400, detail="Invalid entity type")
        
        if format not in ["json", "csv"]:
            raise HTTPException(status_code=400, detail="Invalid format. Supported: json, csv")
        
        # Parse date filters
        date_filter = True
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                if entity_type == "entries":
                    date_filter = and_(date_filter, Entry.timestamp >= start_dt)
                elif entity_type == "audit_logs":
                    date_filter = and_(date_filter, AuditLog.timestamp >= start_dt)
                else:
                    date_filter = and_(date_filter, 
                        getattr(eval(entity_type.title()[:-1]), 'created_at') >= start_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format")
        
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
                if entity_type == "entries":
                    date_filter = and_(date_filter, Entry.timestamp <= end_dt)
                elif entity_type == "audit_logs":
                    date_filter = and_(date_filter, AuditLog.timestamp <= end_dt)
                else:
                    date_filter = and_(date_filter, 
                        getattr(eval(entity_type.title()[:-1]), 'created_at') <= end_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format")
        
        # Build query based on entity type
        if entity_type == "visitors":
            stmt = select(Visitor).where(date_filter).order_by(desc(Visitor.created_at))
        elif entity_type == "vehicles":
            stmt = select(Vehicle).where(date_filter).order_by(desc(Vehicle.created_at))
        elif entity_type == "entries":
            stmt = select(Entry).where(date_filter).order_by(desc(Entry.timestamp))
        elif entity_type == "audit_logs":
            stmt = select(AuditLog).where(date_filter).order_by(desc(AuditLog.timestamp))
        
        result = await db.execute(stmt)
        records = result.scalars().all()
        
        # Convert to dictionaries
        data = [record.to_dict() for record in records]
        
        if format == "json":
            return APIResponse(
                success=True,
                message=f"Exported {len(data)} {entity_type} records",
                data={
                    "export_type": entity_type,
                    "format": format,
                    "count": len(data),
                    "records": data,
                    "exported_at": datetime.utcnow().isoformat()
                }
            ).dict()
        
        # CSV format would require additional processing
        # For now, return JSON with CSV structure info
        return APIResponse(
            success=True,
            message=f"CSV export prepared for {len(data)} {entity_type} records",
            data={
                "export_type": entity_type,
                "format": "csv",
                "count": len(data),
                "csv_headers": list(data[0].keys()) if data else [],
                "download_url": f"/api/v1/export/{entity_type}/download?format=csv"
            }
        ).dict()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting data: {e}")
        raise HTTPException(status_code=500, detail="Export failed")

# Reporting endpoints
@router.get("/reports/summary")
async def get_summary_report(
    start_date: str,
    end_date: str,
    location_id: Optional[int] = None,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db)
):
    """Generate summary report for date range"""
    try:
        # Parse dates
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
        
        if end_dt <= start_dt:
            raise HTTPException(status_code=400, detail="End date must be after start date")
        
        # Location filter
        location_filter = True
        if not current_user.is_admin and current_user.location_id:
            location_filter = current_user.location_id
        elif location_id:
            location_filter = location_id
        
        # Entry statistics
        entry_stats = {}
        
        # Total entries in period
        total_entries_stmt = select(func.count(Entry.id)).where(
            and_(
                Entry.timestamp >= start_dt,
                Entry.timestamp <= end_dt,
                Entry.location_id == location_filter if location_filter != True else True
            )
        )
        total_entries_result = await db.execute(total_entries_stmt)
        entry_stats["total_entries"] = total_entries_result.scalar() or 0
        
        # Entries by type
        entries_by_type_stmt = select(
            Entry.entry_type,
            Entry.action,
            func.count(Entry.id)
        ).where(
            and_(
                Entry.timestamp >= start_dt,
                Entry.timestamp <= end_dt,
                Entry.location_id == location_filter if location_filter != True else True
            )
        ).group_by(Entry.entry_type, Entry.action)
        
        entries_by_type_result = await db.execute(entries_by_type_stmt)
        entries_breakdown = {}
        for entry_type, action, count in entries_by_type_result.fetchall():
            key = f"{entry_type.value}_{action.value}"
            entries_breakdown[key] = count
        
        # Daily breakdown
        daily_breakdown_stmt = select(
            func.date(Entry.timestamp).label('date'),
            Entry.entry_type,
            func.count(Entry.id).label('count')
        ).where(
            and_(
                Entry.timestamp >= start_dt,
                Entry.timestamp <= end_dt,
                Entry.location_id == location_filter if location_filter != True else True
            )
        ).group_by(func.date(Entry.timestamp), Entry.entry_type).order_by(func.date(Entry.timestamp))
        
        daily_breakdown_result = await db.execute(daily_breakdown_stmt)
        daily_stats = {}
        for date_val, entry_type, count in daily_breakdown_result.fetchall():
            date_str = date_val.isoformat()
            if date_str not in daily_stats:
                daily_stats[date_str] = {"visitors": 0, "vehicles": 0}
            daily_stats[date_str][entry_type.value + "s"] = count
        
        # Peak times analysis
        peak_times_stmt = select(
            func.hour(Entry.timestamp).label('hour'),
            func.count(Entry.id).label('count')
        ).where(
            and_(
                Entry.timestamp >= start_dt,
                Entry.timestamp <= end_dt,
                Entry.location_id == location_filter if location_filter != True else True
            )
        ).group_by(func.hour(Entry.timestamp)).order_by(func.count(Entry.id).desc())
        
        peak_times_result = await db.execute(peak_times_stmt)
        peak_times = [{"hour": hour, "count": count} for hour, count in peak_times_result.fetchall()]
        
        # Average duration calculation (for checked out visitors/vehicles)
        avg_duration_stmt = select(
            func.avg(
                func.timestampdiff(
                    'MINUTE',
                    func.min(Entry.timestamp),
                    func.max(Entry.timestamp)
                )
            )
        ).select_from(
            select(Entry.visitor_id, Entry.vehicle_id, Entry.timestamp)
            .where(
                and_(
                    Entry.timestamp >= start_dt,
                    Entry.timestamp <= end_dt,
                    Entry.location_id == location_filter if location_filter != True else True
                )
            )
            .group_by(Entry.visitor_id, Entry.vehicle_id)
            .having(func.count(Entry.id) >= 2)
            .subquery()
        )
        
        avg_duration_result = await db.execute(avg_duration_stmt)
        avg_duration = avg_duration_result.scalar()
        
        return APIResponse(
            success=True,
            message="Summary report generated successfully",
            data={
                "period": {
                    "start_date": start_dt.isoformat(),
                    "end_date": end_dt.isoformat(),
                    "days": (end_dt - start_dt).days + 1
                },
                "summary": {
                    "total_entries": entry_stats["total_entries"],
                    "entries_breakdown": entries_breakdown,
                    "average_duration_minutes": round(avg_duration, 2) if avg_duration else None
                },
                "daily_breakdown": daily_stats,
                "peak_times": peak_times[:10],  # Top 10 peak hours
                "generated_at": datetime.utcnow().isoformat(),
                "generated_by": current_user.full_name
            }
        ).dict()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating summary report: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate report")

# Audit logs
@router.get("/audit-logs")
async def get_audit_logs(
    limit: int = 50,
    offset: int = 0,
    action: Optional[str] = None,
    table_name: Optional[str] = None,
    user_id: Optional[int] = None,
    current_user: User = Depends(require_admin),  # Admin only
    db: AsyncSession = Depends(get_db)
):
    """Get audit logs (admin only)"""
    try:
        # Build query
        stmt = select(AuditLog)
        
        # Filters
        if action:
            stmt = stmt.where(AuditLog.action == action)
        
        if table_name:
            stmt = stmt.where(AuditLog.table_name == table_name)
        
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        
        # Get total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await db.execute(count_stmt)
        total = total_result.scalar()
        
        # Apply pagination and ordering
        stmt = stmt.order_by(desc(AuditLog.timestamp)).offset(offset).limit(limit)
        
        result = await db.execute(stmt)
        audit_logs = result.scalars().all()
        
        return PaginatedResponse(
            data=[log.to_dict() for log in audit_logs],
            pagination={
                "total": total,
                "limit": limit,
                "offset": offset,
                "pages": (total + limit - 1) // limit if limit > 0 else 1
            }
        ).dict()
        
    except Exception as e:
        logger.error(f"Error getting audit logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve audit logs")

# System configuration
@router.get("/config")
async def get_system_config(
    current_user: User = Depends(require_admin)
):
    """Get system configuration (admin only)"""
    try:
        return APIResponse(
            success=True,
            message="System configuration retrieved",
            data={
                "app_name": settings.app_name,
                "environment": settings.environment,
                "timezone": settings.timezone,
                "features": {
                    "qr_scanning": True,
                    "visitor_management": True,
                    "vehicle_management": True,
                    "multi_location": True,
                    "audit_logging": True,
                    "api_access": True
                },
                "limits": {
                    "max_file_size": settings.max_file_size,
                    "qr_code_expiry_hours": settings.qr_code_expiry_hours,
                    "max_login_attempts": settings.max_login_attempts
                },
                "version": "1.0.0"
            }
        ).dict()
        
    except Exception as e:
        logger.error(f"Error getting system config: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve configuration")

# Rate limiting info
@router.get("/rate-limits")
async def get_rate_limits(current_user: User = Depends(get_current_user)):
    """Get current rate limiting information"""
    return APIResponse(
        success=True,
        message="Rate limit information",
        data={
            "enabled": settings.rate_limit_enabled,
            "requests_per_window": settings.rate_limit_requests,
            "window_seconds": settings.rate_limit_window,
            "current_user": {
                "id": current_user.id if current_user else None,
                "role": current_user.role.value if current_user else None
            }
        }
    ).dict()

# Database statistics
@router.get("/database/stats")
async def get_database_stats(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get database statistics (admin only)"""
    try:
        stats = {}
        
        # Table counts
        table_counts = {}
        
        # Visitors
        visitor_count = await DatabaseManager.get_table_count("visitors")
        table_counts["visitors"] = visitor_count
        
        # Vehicles
        vehicle_count = await DatabaseManager.get_table_count("vehicles")
        table_counts["vehicles"] = vehicle_count
        
        # Entries
        entry_count = await DatabaseManager.get_table_count("entries")
        table_counts["entries"] = entry_count
        
        # QR Codes
        qr_count = await DatabaseManager.get_table_count("qr_codes")
        table_counts["qr_codes"] = qr_count
        
        # Users
        user_count = await DatabaseManager.get_table_count("users")
        table_counts["users"] = user_count
        
        # Audit logs
        audit_count = await DatabaseManager.get_table_count("audit_logs")
        table_counts["audit_logs"] = audit_count
        
        # Database health
        db_health = await DatabaseManager.health_check()
        
        return APIResponse(
            success=True,
            message="Database statistics retrieved",
            data={
                "table_counts": table_counts,
                "total_records": sum(table_counts.values()),
                "health": db_health,
                "database_name": settings.database_name,
                "generated_at": datetime.utcnow().isoformat()
            }
        ).dict()
        
    except Exception as e:
        logger.error(f"Error getting database stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve database statistics")