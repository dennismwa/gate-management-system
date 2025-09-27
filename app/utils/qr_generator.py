"""
QR Code generation and management utilities
Handles QR code creation, validation, and printing layouts
"""

import qrcode
from qrcode.image.pil import PilImage
from PIL import Image, ImageDraw, ImageFont
import io
import base64
import secrets
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
import os

from ..config import get_settings

settings = get_settings()

class QRCodeGenerator:
    """QR Code generation and management"""
    
    def __init__(self):
        self.size = settings.qr_code_size
        self.border = settings.qr_code_border
    
    def generate_unique_code(self) -> str:
        """Generate unique QR code identifier"""
        return f"GMS_{secrets.token_urlsafe(16)}_{int(datetime.now().timestamp())}"
    
    def create_qr_data(
        self, 
        code: str, 
        record_type: str, 
        record_id: int, 
        location_id: int,
        expires_hours: int = None
    ) -> Dict[str, Any]:
        """Create QR code data payload"""
        expires_hours = expires_hours or settings.qr_code_expiry_hours
        expires_at = datetime.now() + timedelta(hours=expires_hours)
        
        return {
            "code": code,
            "type": record_type,
            "record_id": record_id,
            "location_id": location_id,
            "created_at": datetime.now().isoformat(),
            "expires_at": expires_at.isoformat(),
            "version": "1.0"
        }
    
    def generate_qr_image(
        self, 
        data: Dict[str, Any], 
        size: int = None, 
        border: int = None
    ) -> Image.Image:
        """Generate QR code image"""
        qr_size = size or self.size
        qr_border = border or self.border
        
        # Create QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=qr_size // 25,  # Adjust based on size
            border=qr_border,
        )
        
        # Add data as JSON
        qr.add_data(json.dumps(data))
        qr.make(fit=True)
        
        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Resize to exact dimensions
        img = img.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
        
        return img
    
    def create_visitor_sticker(
        self, 
        visitor_data: Dict[str, Any], 
        qr_data: Dict[str, Any],
        sticker_size: str = "medium"
    ) -> Image.Image:
        """Create visitor sticker with QR code and info"""
        
        # Get sticker dimensions
        dimensions = settings.sticker_sizes.get(sticker_size, settings.sticker_sizes["medium"])
        width, height = dimensions["width"], dimensions["height"]
        
        # Create base image
        img = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(img)
        
        # Generate QR code (smaller for sticker)
        qr_size = min(width, height) // 3
        qr_img = self.generate_qr_image(qr_data, qr_size)
        
        # Paste QR code
        qr_x = 10
        qr_y = 10
        img.paste(qr_img, (qr_x, qr_y))
        
        # Add visitor information
        try:
            # Try to load a font
            font_path = self._get_font_path()
            title_font = ImageFont.truetype(font_path, 14)
            info_font = ImageFont.truetype(font_path, 10)
        except:
            # Fallback to default font
            title_font = ImageFont.load_default()
            info_font = ImageFont.load_default()
        
        # Text area starts after QR code
        text_x = qr_x + qr_size + 15
        text_y = qr_y
        
        # Visitor name (title)
        name = visitor_data.get('full_name', 'Visitor')
        draw.text((text_x, text_y), name, fill='black', font=title_font)
        text_y += 20
        
        # Company
        if visitor_data.get('company'):
            draw.text((text_x, text_y), f"Company: {visitor_data['company']}", fill='black', font=info_font)
            text_y += 15
        
        # Purpose
        if visitor_data.get('purpose'):
            purpose = visitor_data['purpose'][:30] + "..." if len(visitor_data['purpose']) > 30 else visitor_data['purpose']
            draw.text((text_x, text_y), f"Purpose: {purpose}", fill='black', font=info_font)
            text_y += 15
        
        # Date
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        draw.text((text_x, text_y), f"Date: {date_str}", fill='black', font=info_font)
        text_y += 15
        
        # Location
        if visitor_data.get('location'):
            draw.text((text_x, text_y), f"Location: {visitor_data['location']['name']}", fill='black', font=info_font)
            text_y += 15
        
        # Add border
        draw.rectangle([(0, 0), (width-1, height-1)], outline='black', width=2)
        
        return img
    
    def create_vehicle_sticker(
        self, 
        vehicle_data: Dict[str, Any], 
        qr_data: Dict[str, Any],
        sticker_size: str = "medium"
    ) -> Image.Image:
        """Create vehicle sticker with QR code and info"""
        
        # Get sticker dimensions
        dimensions = settings.sticker_sizes.get(sticker_size, settings.sticker_sizes["medium"])
        width, height = dimensions["width"], dimensions["height"]
        
        # Create base image
        img = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(img)
        
        # Generate QR code (smaller for sticker)
        qr_size = min(width, height) // 3
        qr_img = self.generate_qr_image(qr_data, qr_size)
        
        # Paste QR code
        qr_x = 10
        qr_y = 10
        img.paste(qr_img, (qr_x, qr_y))
        
        # Add vehicle information
        try:
            # Try to load a font
            font_path = self._get_font_path()
            title_font = ImageFont.truetype(font_path, 14)
            info_font = ImageFont.truetype(font_path, 10)
        except:
            # Fallback to default font
            title_font = ImageFont.load_default()
            info_font = ImageFont.load_default()
        
        # Text area starts after QR code
        text_x = qr_x + qr_size + 15
        text_y = qr_y
        
        # License plate (title)
        plate = vehicle_data.get('license_plate', 'VEHICLE')
        draw.text((text_x, text_y), plate.upper(), fill='black', font=title_font)
        text_y += 20
        
        # Driver name
        driver = vehicle_data.get('driver_name', '')
        if driver:
            draw.text((text_x, text_y), f"Driver: {driver}", fill='black', font=info_font)
            text_y += 15
        
        # Vehicle type and purpose
        vtype = vehicle_data.get('vehicle_type', '').title()
        purpose = vehicle_data.get('purpose', '').replace('_', ' ').title()
        draw.text((text_x, text_y), f"Type: {vtype}", fill='black', font=info_font)
        text_y += 15
        draw.text((text_x, text_y), f"Purpose: {purpose}", fill='black', font=info_font)
        text_y += 15
        
        # Date
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        draw.text((text_x, text_y), f"Date: {date_str}", fill='black', font=info_font)
        text_y += 15
        
        # Location
        if vehicle_data.get('location'):
            draw.text((text_x, text_y), f"Location: {vehicle_data['location']['name']}", fill='black', font=info_font)
        
        # Add border
        draw.rectangle([(0, 0), (width-1, height-1)], outline='black', width=2)
        
        return img
    
    def image_to_base64(self, img: Image.Image, format: str = "PNG") -> str:
        """Convert PIL image to base64 string"""
        buffer = io.BytesIO()
        img.save(buffer, format=format)
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/{format.lower()};base64,{img_str}"
    
    def save_qr_image(self, img: Image.Image, filename: str) -> str:
        """Save QR image to file"""
        qr_dir = "app/static/qr_codes"
        os.makedirs(qr_dir, exist_ok=True)
        
        filepath = os.path.join(qr_dir, filename)
        img.save(filepath, "PNG")
        
        return f"/static/qr_codes/{filename}"
    
    def _get_font_path(self) -> str:
        """Get system font path"""
        # Common font paths for different systems
        font_paths = [
            "/System/Library/Fonts/Arial.ttf",  # macOS
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",  # Linux
            "C:/Windows/Fonts/arial.ttf",  # Windows
            "/usr/share/fonts/TTF/arial.ttf",  # Linux alt
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux DejaVu
        ]
        
        for path in font_paths:
            if os.path.exists(path):
                return path
        
        # Return default if no system font found
        return None
    
    def validate_qr_data(self, qr_string: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Validate and parse QR code data"""
        try:
            data = json.loads(qr_string)
            
            # Check required fields
            required_fields = ['code', 'type', 'record_id', 'location_id', 'expires_at']
            for field in required_fields:
                if field not in data:
                    return False, None
            
            # Check expiry
            expires_at = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
            if datetime.now() > expires_at:
                return False, {"error": "QR code has expired"}
            
            # Check type
            if data['type'] not in ['visitor', 'vehicle']:
                return False, {"error": "Invalid QR code type"}
            
            return True, data
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            return False, {"error": f"Invalid QR code format: {str(e)}"}
    
    def create_batch_stickers(
        self, 
        records: list, 
        record_type: str, 
        sticker_size: str = "medium"
    ) -> list:
        """Create multiple stickers in batch"""
        stickers = []
        
        for record in records:
            try:
                # Generate QR data
                code = self.generate_unique_code()
                qr_data = self.create_qr_data(
                    code, 
                    record_type, 
                    record['id'], 
                    record['location_id']
                )
                
                # Create sticker based on type
                if record_type == "visitor":
                    img = self.create_visitor_sticker(record, qr_data, sticker_size)
                else:
                    img = self.create_vehicle_sticker(record, qr_data, sticker_size)
                
                # Convert to base64
                base64_img = self.image_to_base64(img)
                
                stickers.append({
                    "record_id": record['id'],
                    "qr_code": code,
                    "qr_data": qr_data,
                    "image": base64_img,
                    "filename": f"{record_type}_{record['id']}_{int(datetime.now().timestamp())}.png"
                })
                
            except Exception as e:
                stickers.append({
                    "record_id": record['id'],
                    "error": str(e)
                })
        
        return stickers

class QRCodePrinter:
    """Handle QR code printing operations"""
    
    def __init__(self):
        self.generator = QRCodeGenerator()
    
    def create_print_layout(
        self, 
        stickers: list, 
        layout: str = "grid",
        page_size: Tuple[int, int] = (2480, 3508)  # A4 at 300 DPI
    ) -> Image.Image:
        """Create print layout with multiple stickers"""
        
        if layout == "grid":
            return self._create_grid_layout(stickers, page_size)
        elif layout == "list":
            return self._create_list_layout(stickers, page_size)
        else:
            return self._create_grid_layout(stickers, page_size)
    
    def _create_grid_layout(self, stickers: list, page_size: Tuple[int, int]) -> Image.Image:
        """Create grid layout for printing"""
        page_width, page_height = page_size
        
        # Calculate grid dimensions
        sticker_width = 400
        sticker_height = 200
        margin = 20
        
        cols = (page_width - margin) // (sticker_width + margin)
        rows = (page_height - margin) // (sticker_height + margin)
        
        # Create page
        page = Image.new('RGB', page_size, 'white')
        
        for i, sticker_data in enumerate(stickers[:cols * rows]):
            if 'error' in sticker_data:
                continue
            
            row = i // cols
            col = i % cols
            
            x = margin + col * (sticker_width + margin)
            y = margin + row * (sticker_height + margin)
            
            # Decode base64 image
            try:
                img_data = base64.b64decode(sticker_data['image'].split(',')[1])
                sticker_img = Image.open(io.BytesIO(img_data))
                sticker_img = sticker_img.resize((sticker_width, sticker_height), Image.Resampling.LANCZOS)
                
                page.paste(sticker_img, (x, y))
            except Exception as e:
                # Draw error placeholder
                draw = ImageDraw.Draw(page)
                draw.rectangle([(x, y), (x + sticker_width, y + sticker_height)], outline='red', width=2)
                draw.text((x + 10, y + 10), f"Error: {str(e)}", fill='red')
        
        return page
    
    def _create_list_layout(self, stickers: list, page_size: Tuple[int, int]) -> Image.Image:
        """Create list layout for printing"""
        page_width, page_height = page_size
        
        # Create page
        page = Image.new('RGB', page_size, 'white')
        
        sticker_height = 150
        margin = 20
        y_offset = margin
        
        for sticker_data in stickers:
            if 'error' in sticker_data:
                continue
            
            if y_offset + sticker_height > page_height:
                break
            
            # Decode base64 image
            try:
                img_data = base64.b64decode(sticker_data['image'].split(',')[1])
                sticker_img = Image.open(io.BytesIO(img_data))
                
                # Resize to fit width
                aspect_ratio = sticker_img.height / sticker_img.width
                new_width = page_width - 2 * margin
                new_height = int(new_width * aspect_ratio)
                
                if new_height > sticker_height:
                    new_height = sticker_height
                    new_width = int(new_height / aspect_ratio)
                
                sticker_img = sticker_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                x = (page_width - new_width) // 2
                page.paste(sticker_img, (x, y_offset))
                
                y_offset += new_height + margin
                
            except Exception as e:
                # Draw error placeholder
                draw = ImageDraw.Draw(page)
                draw.rectangle([(margin, y_offset), (page_width - margin, y_offset + sticker_height)], outline='red', width=2)
                draw.text((margin + 10, y_offset + 10), f"Error: {str(e)}", fill='red')
                y_offset += sticker_height + margin
        
        return page

# Global instances
qr_generator = QRCodeGenerator()
qr_printer = QRCodePrinter()