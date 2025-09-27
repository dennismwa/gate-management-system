#!/usr/bin/env python3
"""
Gate Management System - Main Application
High-performance, mobile-responsive gate management system
"""

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from contextlib import asynccontextmanager
import uvicorn
import os
from datetime import datetime

# Import application modules
from app.config import get_settings
from app.database import init_db, get_db
from app.routes import auth, dashboard, qr_management, api, visitors, vehicles
from app.utils.security import get_current_user
from app.models.user import User

# App settings
settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    print("🚀 Gate Management System started successfully!")
    print(f"📍 Database: {settings.database_host}")
    print(f"🌍 Environment: {settings.environment}")
    yield
    # Shutdown
    print("🛑 Gate Management System shutting down...")

# Initialize FastAPI application
app = FastAPI(
    title="Gate Management System",
    description="High-performance gate management with QR code scanning",
    version="1.0.0",
    docs_url="/admin/docs",
    redoc_url="/admin/redoc",
    lifespan=lifespan
)

# Security middleware
app.add_middleware(
    TrustedHostMiddleware, 
    allowed_hosts=["*"]  # Configure for production
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compression middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="templates")

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(qr_management.router, prefix="/qr", tags=["QR Management"])
app.include_router(visitors.router, prefix="/visitors", tags=["Visitors"])
app.include_router(vehicles.router, prefix="/vehicles", tags=["Vehicles"])
app.include_router(api.router, prefix="/api/v1", tags=["API"])

# Root route - redirect to dashboard or login
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root route - serves main application"""
    try:
        # Try to get current user from session
        user = await get_current_user(request)
        if user:
            return templates.TemplateResponse(
                "dashboard/index.html", 
                {
                    "request": request,
                    "user": user,
                    "page_title": "Dashboard"
                }
            )
    except:
        pass
    
    # Show login page if not authenticated
    return templates.TemplateResponse(
        "auth/login.html", 
        {
            "request": request,
            "page_title": "Login"
        }
    )

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }

# PWA manifest
@app.get("/manifest.json")
async def manifest():
    """PWA manifest"""
    return JSONResponse({
        "name": "Gate Management System",
        "short_name": "GateMS",
        "description": "Professional gate management with QR scanning",
        "start_url": "/",
        "display": "standalone",
        "theme_color": "#3B82F6",
        "background_color": "#ffffff",
        "orientation": "portrait-primary",
        "icons": [
            {
                "src": "/static/images/icon-192.png",
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": "/static/images/icon-512.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    })

# Service worker
@app.get("/sw.js")
async def service_worker(request: Request):
    """Service worker for PWA functionality"""
    with open("app/static/js/sw.js", "r") as f:
        content = f.read()
    
    return HTMLResponse(
        content=content,
        headers={"Content-Type": "application/javascript"}
    )

# Error handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """Custom 404 page"""
    return templates.TemplateResponse(
        "errors/404.html",
        {"request": request, "page_title": "Page Not Found"},
        status_code=404
    )

@app.exception_handler(500)
async def server_error_handler(request: Request, exc: HTTPException):
    """Custom 500 page"""
    return templates.TemplateResponse(
        "errors/500.html",
        {"request": request, "page_title": "Server Error"},
        status_code=500
    )

# Development server
if __name__ == "__main__":
    uvicorn.run(
        "run:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=1 if settings.environment == "development" else 4,
        log_level="info"
    )