# app/services/asset_service.py

"""
Wallet Asset Service

This module provides services for managing wallet pass assets:
- Image assets (icons, logos, etc.)
- Certificates
- Templates
"""

import os
import logging
import uuid
import base64
from io import BytesIO
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import current_app
from PIL import Image

from app.core import db
from app.models.wallet_asset import WalletAsset, WalletTemplate, WalletCertificate

logger = logging.getLogger(__name__)

# Valid asset types and their requirements
# StoreCard ONLY supports: icon, logo, strip
# NOT supported for StoreCard: thumbnail, background, footer
# Reference: https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/PassKit_PG/Creating.html
ASSET_TYPES = {
    'icon': {
        'description': 'Pass icon (shown on lock screen)',
        'formats': ['png'],
        'max_size': 1 * 1024 * 1024,  # 1MB
        'dimensions': '29x29',
        'required': True,
        'apple_filename': 'icon'  # Actual filename for Apple Wallet
    },
    'icon2x': {
        'description': 'High-resolution pass icon',
        'formats': ['png'],
        'max_size': 1 * 1024 * 1024,
        'dimensions': '58x58',
        'required': False,
        'apple_filename': 'icon@2x'  # Apple requires @ symbol for retina
    },
    'logo': {
        'description': 'Pass logo (displayed in header) - optional',
        'formats': ['png'],
        'max_size': 1 * 1024 * 1024,
        'dimensions': '160x50',
        'required': False,  # Logo is optional - can use logo_text or header fields instead
        'apple_filename': 'logo'
    },
    'logo2x': {
        'description': 'High-resolution pass logo',
        'formats': ['png'],
        'max_size': 1 * 1024 * 1024,
        'dimensions': '320x100',
        'required': False,
        'apple_filename': 'logo@2x'
    },
    'strip': {
        'description': 'Pass strip image (main visual banner)',
        'formats': ['png'],
        'max_size': 2 * 1024 * 1024,  # 2MB
        'dimensions': '375x123',
        'required': False,
        'apple_filename': 'strip'
    },
    'strip2x': {
        'description': 'High-resolution pass strip image',
        'formats': ['png'],
        'max_size': 2 * 1024 * 1024,
        'dimensions': '750x246',
        'required': False,
        'apple_filename': 'strip@2x'
    },
    'thumbnail': {
        'description': 'Pass thumbnail image (for generic passes)',
        'formats': ['png'],
        'max_size': 1 * 1024 * 1024,
        'dimensions': '90x90',
        'required': False,
        'apple_filename': 'thumbnail'
    },
    'thumbnail2x': {
        'description': 'High-resolution pass thumbnail',
        'formats': ['png'],
        'max_size': 1 * 1024 * 1024,
        'dimensions': '180x180',
        'required': False,
        'apple_filename': 'thumbnail@2x'
    },
}

# Asset types supported by each pass style
# This ensures we only allow assets that are actually supported
PASS_STYLE_ASSETS = {
    'storeCard': ['icon', 'icon2x', 'logo', 'logo2x', 'strip', 'strip2x'],
    'boardingPass': ['icon', 'icon2x', 'logo', 'logo2x', 'footer', 'footer2x'],
    'coupon': ['icon', 'icon2x', 'logo', 'logo2x', 'strip', 'strip2x'],
    'eventTicket': ['icon', 'icon2x', 'logo', 'logo2x', 'strip', 'strip2x', 'background', 'background2x', 'thumbnail', 'thumbnail2x'],
    'generic': ['icon', 'icon2x', 'logo', 'logo2x', 'thumbnail', 'thumbnail2x'],
}

# Valid certificate types
CERT_TYPES = {
    'apple': {
        'certificate': {
            'description': 'Pass Type ID Certificate',
            'formats': ['pem', 'p12', 'cer', 'crt'],
            'max_size': 1 * 1024 * 1024  # 1MB
        },
        'key': {
            'description': 'Private Key',
            'formats': ['pem', 'key', 'p12'],
            'max_size': 1 * 1024 * 1024
        },
        'wwdr': {
            'description': 'Apple WWDR Certificate',
            'formats': ['pem', 'cer', 'crt'],
            'max_size': 1 * 1024 * 1024
        },
        'apns_key': {
            'description': 'APNs Push Key (for automatic pass updates)',
            'formats': ['p8'],
            'max_size': 1 * 1024 * 1024
        }
    },
    'google': {
        'credentials': {
            'description': 'Google Service Account Credentials',
            'formats': ['json'],
            'max_size': 1 * 1024 * 1024
        }
    }
}


class AssetService:
    """Service for managing wallet pass assets"""

    def __init__(self):
        # Paths relative to Docker's working directory (/app)
        # The app package is at /app/app/, so wallet_pass is at /app/app/wallet_pass/
        # From CWD /app, we need 'app/wallet_pass/assets'
        self.asset_path = 'app/wallet_pass/assets'
        self.cert_path = 'app/wallet_pass/certs'
        self.template_path = 'app/wallet_pass/templates'
    
    # =========================================================================
    # Image Assets
    # =========================================================================
    
    def upload_asset(self, file, asset_type, pass_type_id):
        """
        Upload an asset file
        
        Args:
            file: Uploaded file object
            asset_type: Type of asset (icon, logo, etc.)
            pass_type_id: Pass type ID
            
        Returns:
            WalletAsset instance
        """
        if asset_type not in ASSET_TYPES:
            raise ValueError(f"Invalid asset type: {asset_type}")
            
        # Check file type
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        
        if ext not in ASSET_TYPES[asset_type]['formats']:
            raise ValueError(
                f"Invalid file format: {ext}. Expected: {ASSET_TYPES[asset_type]['formats']}"
            )
            
        # Check file size (content_length may be None for streamed uploads)
        max_size = ASSET_TYPES[asset_type]['max_size']
        if file.content_length and file.content_length > max_size:
            max_mb = max_size / (1024 * 1024)
            raise ValueError(f"File too large. Maximum size: {max_mb}MB")

        # Use Apple Wallet compatible filename (e.g., icon.png, icon@2x.png)
        # The @ symbol is required by Apple for retina assets
        apple_filename = ASSET_TYPES[asset_type].get('apple_filename', asset_type)
        unique_filename = f"{apple_filename}.{ext}"

        # Use meaningful folder names based on pass type ID
        # pass_type_id 1 = ECS Membership, 2 = Pub League
        folder_names = {1: 'ecs_membership', 2: 'pub_league'}
        pass_type_subdir = folder_names.get(pass_type_id, f"pass_type_{pass_type_id}")

        # Create directory if it doesn't exist
        asset_dir = os.path.join(self.asset_path, pass_type_subdir)
        os.makedirs(asset_dir, exist_ok=True)
        
        # Save file
        file_path = os.path.join(asset_dir, unique_filename)
        file.save(file_path)
        
        # Check if asset already exists for this pass type
        existing_asset = WalletAsset.get_by_type_and_pass_type(asset_type, pass_type_id)
        if existing_asset:
            # Remove old file
            if os.path.exists(existing_asset.file_path):
                os.remove(existing_asset.file_path)
                
            # Update record
            existing_asset.file_name = filename
            existing_asset.file_path = file_path
            existing_asset.content_type = file.content_type
            existing_asset.file_size = os.path.getsize(file_path)
            existing_asset.updated_at = datetime.utcnow()
            
            asset = existing_asset
        else:
            # Create new record
            asset = WalletAsset(
                pass_type_id=pass_type_id,
                asset_type=asset_type,
                file_name=filename,
                file_path=file_path,
                content_type=file.content_type,
                file_size=os.path.getsize(file_path)
            )
            db.session.add(asset)
            
        db.session.commit()
        
        logger.info(
            f"Uploaded asset '{asset_type}' for pass type {pass_type_id}: {filename}"
        )

        return asset

    def process_cropped_asset(self, base64_data, asset_type, pass_type_id):
        """
        Process a base64 encoded cropped image and save as asset

        Args:
            base64_data: Base64 encoded image data (with or without data URI prefix)
            asset_type: Type of asset (icon, logo, etc.)
            pass_type_id: Pass type ID

        Returns:
            WalletAsset instance
        """
        if asset_type not in ASSET_TYPES:
            raise ValueError(f"Invalid asset type: {asset_type}")

        # Remove data URI prefix if present
        if ',' in base64_data:
            base64_data = base64_data.split(',')[1]

        # Decode base64
        try:
            image_data = base64.b64decode(base64_data)
        except Exception as e:
            raise ValueError(f"Invalid base64 data: {e}")

        # Open image with PIL
        try:
            image = Image.open(BytesIO(image_data))
        except Exception as e:
            raise ValueError(f"Invalid image data: {e}")

        # Get target dimensions
        dimensions = ASSET_TYPES[asset_type]['dimensions']
        target_width, target_height = map(int, dimensions.split('x'))

        # Resize to exact dimensions if needed
        if image.size != (target_width, target_height):
            image = image.resize((target_width, target_height), Image.LANCZOS)

        # Convert to RGBA for PNG support
        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        # Save to buffer
        buffer = BytesIO()
        image.save(buffer, format='PNG', optimize=True)
        buffer.seek(0)

        # Use Apple Wallet compatible filename (e.g., icon.png, icon@2x.png)
        apple_filename = ASSET_TYPES[asset_type].get('apple_filename', asset_type)
        filename = f"{apple_filename}.png"

        # Use meaningful folder names based on pass type ID
        folder_names = {1: 'ecs_membership', 2: 'pub_league'}
        pass_type_subdir = folder_names.get(pass_type_id, f"pass_type_{pass_type_id}")

        # Create directory if it doesn't exist
        asset_dir = os.path.join(self.asset_path, pass_type_subdir)
        os.makedirs(asset_dir, exist_ok=True)

        # Save file
        file_path = os.path.join(asset_dir, filename)
        with open(file_path, 'wb') as f:
            f.write(buffer.getvalue())

        file_size = os.path.getsize(file_path)

        # Check if asset already exists for this pass type
        existing_asset = WalletAsset.get_by_type_and_pass_type(asset_type, pass_type_id)
        if existing_asset:
            # Update record (file already replaced)
            existing_asset.file_name = filename
            existing_asset.file_path = file_path
            existing_asset.content_type = 'image/png'
            existing_asset.file_size = file_size
            existing_asset.updated_at = datetime.utcnow()
            asset = existing_asset
        else:
            # Create new record
            asset = WalletAsset(
                pass_type_id=pass_type_id,
                asset_type=asset_type,
                file_name=filename,
                file_path=file_path,
                content_type='image/png',
                file_size=file_size
            )
            db.session.add(asset)

        db.session.commit()

        logger.info(
            f"Processed cropped asset '{asset_type}' for pass type {pass_type_id}: {filename} ({target_width}x{target_height})"
        )

        return asset

    def get_asset(self, asset_id):
        """Get asset by ID"""
        return WalletAsset.query.get_or_404(asset_id)
    
    def delete_asset(self, asset_id):
        """Delete an asset"""
        asset = self.get_asset(asset_id)
        
        # Remove file
        if os.path.exists(asset.file_path):
            os.remove(asset.file_path)
            
        # Delete record
        db.session.delete(asset)
        db.session.commit()
        
        logger.info(
            f"Deleted asset '{asset.asset_type}' for pass type {asset.pass_type_id}: {asset.file_name}"
        )
        
        return True
    
    # =========================================================================
    # Templates
    # =========================================================================
    
    def upload_template(self, name, content, pass_type_id, platform, is_default=False):
        """
        Upload a template
        
        Args:
            name: Template name
            content: Template content (JSON string)
            pass_type_id: Pass type ID
            platform: Platform (apple, google)
            is_default: Whether this is the default template
            
        Returns:
            WalletTemplate instance
        """
        # Check if template already exists
        existing = WalletTemplate.query.filter_by(
            name=name,
            pass_type_id=pass_type_id,
            platform=platform
        ).first()
        
        if existing:
            # Update record
            existing.content = content
            existing.updated_at = datetime.utcnow()
            
            if is_default:
                existing.is_default = True
                # Unset other defaults
                WalletTemplate.query.filter(
                    WalletTemplate.pass_type_id == pass_type_id,
                    WalletTemplate.platform == platform,
                    WalletTemplate.id != existing.id,
                    WalletTemplate.is_default == True
                ).update({WalletTemplate.is_default: False})
                
            template = existing
        else:
            # Create new record
            template = WalletTemplate(
                name=name,
                content=content,
                pass_type_id=pass_type_id,
                platform=platform,
                is_default=is_default
            )
            
            if is_default:
                # Unset other defaults
                WalletTemplate.query.filter(
                    WalletTemplate.pass_type_id == pass_type_id,
                    WalletTemplate.platform == platform,
                    WalletTemplate.is_default == True
                ).update({WalletTemplate.is_default: False})
                
            db.session.add(template)
            
        db.session.commit()
        
        logger.info(
            f"Uploaded template '{name}' for pass type {pass_type_id} ({platform})"
        )
        
        return template
    
    def get_template(self, template_id):
        """Get template by ID"""
        return WalletTemplate.query.get_or_404(template_id)
    
    def delete_template(self, template_id):
        """Delete a template"""
        template = self.get_template(template_id)
        
        # Delete record
        db.session.delete(template)
        db.session.commit()
        
        logger.info(
            f"Deleted template '{template.name}' for pass type {template.pass_type_id}"
        )
        
        return True
    
    def set_default_template(self, template_id):
        """Set a template as default"""
        return WalletTemplate.set_default(template_id)
    
    # =========================================================================
    # Certificates
    # =========================================================================
    
    def upload_certificate(self, file, cert_type, platform, name, team_identifier=None,
                          pass_type_identifier=None, issuer_id=None, apns_key_id=None):
        """
        Upload a certificate file

        Args:
            file: Uploaded file object
            cert_type: Type of certificate (certificate, key, wwdr, credentials, apns_key)
            platform: Platform (apple, google)
            name: Certificate name
            team_identifier: Apple team identifier (optional)
            pass_type_identifier: Apple pass type identifier (optional)
            issuer_id: Google issuer ID (optional)
            apns_key_id: APNs key ID for token-based auth (optional, required for apns_key type)

        Returns:
            WalletCertificate instance
        """
        if platform not in CERT_TYPES:
            raise ValueError(f"Invalid platform: {platform}")
            
        if cert_type not in CERT_TYPES[platform]:
            raise ValueError(f"Invalid certificate type: {cert_type} for platform: {platform}")
            
        # Check file type
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        
        if ext not in CERT_TYPES[platform][cert_type]['formats']:
            raise ValueError(
                f"Invalid file format: {ext}. Expected: {CERT_TYPES[platform][cert_type]['formats']}"
            )
            
        # Check file size (content_length may be None for streamed uploads, so we check after saving)
        max_size = CERT_TYPES[platform][cert_type]['max_size']
        if file.content_length and file.content_length > max_size:
            max_mb = max_size / (1024 * 1024)
            raise ValueError(f"File too large. Maximum size: {max_mb}MB")
        
        # Generate unique filename
        unique_filename = f"{uuid.uuid4().hex}.{ext}"
        platform_subdir = platform
        
        # Create directory if it doesn't exist
        cert_dir = os.path.join(self.cert_path, platform_subdir)
        os.makedirs(cert_dir, exist_ok=True)
        
        # Save file
        file_path = os.path.join(cert_dir, unique_filename)
        file.save(file_path)

        # Verify file size after saving (in case content_length was None)
        actual_size = os.path.getsize(file_path)
        if actual_size > max_size:
            os.remove(file_path)
            max_mb = max_size / (1024 * 1024)
            raise ValueError(f"File too large ({actual_size} bytes). Maximum size: {max_mb}MB")

        # Create certificate record
        certificate = WalletCertificate(
            name=name,
            type=cert_type,
            platform=platform,
            file_name=filename,
            file_path=file_path,
            team_identifier=team_identifier,
            pass_type_identifier=pass_type_identifier,
            issuer_id=issuer_id,
            apns_key_id=apns_key_id,
            is_active=True
        )
        
        # If a certificate of the same type and platform is already active, deactivate it
        if certificate.is_active:
            WalletCertificate.query.filter(
                WalletCertificate.type == cert_type,
                WalletCertificate.platform == platform,
                WalletCertificate.is_active == True
            ).update({WalletCertificate.is_active: False})
            
        db.session.add(certificate)
        db.session.commit()
        
        # Special case: if this is a certificate for Apple, also copy to standard location
        if platform == 'apple' and cert_type in ['certificate', 'key', 'wwdr', 'apns_key']:
            standard_filename = None
            if cert_type == 'certificate':
                standard_filename = 'certificate.pem'
            elif cert_type == 'key':
                standard_filename = 'key.pem'
            elif cert_type == 'wwdr':
                standard_filename = 'wwdr.pem'
            elif cert_type == 'apns_key':
                standard_filename = 'apns_key.p8'

            if standard_filename:
                standard_path = os.path.join(self.cert_path, standard_filename)
                try:
                    with open(file_path, 'rb') as src, open(standard_path, 'wb') as dest:
                        dest.write(src.read())
                    logger.info(f"Copied {file_path} to {standard_path}")
                except Exception as e:
                    logger.error(f"Error copying certificate to standard location: {e}")
        
        logger.info(
            f"Uploaded certificate '{cert_type}' for {platform}: {name}"
        )
        
        return certificate
    
    def get_certificate(self, cert_id):
        """Get certificate by ID"""
        return WalletCertificate.query.get_or_404(cert_id)
    
    def delete_certificate(self, cert_id):
        """Delete a certificate"""
        cert = self.get_certificate(cert_id)
        
        # Remove file
        if os.path.exists(cert.file_path):
            try:
                os.remove(cert.file_path)
            except Exception as e:
                logger.warning(f"Error removing certificate file: {e}")
            
        # Delete record
        db.session.delete(cert)
        db.session.commit()
        
        logger.info(
            f"Deleted certificate '{cert.type}' for {cert.platform}: {cert.name}"
        )
        
        return True
    
    def toggle_certificate(self, cert_id):
        """Toggle certificate active status"""
        cert = self.get_certificate(cert_id)
        
        # If activating, deactivate other certificates of same type and platform
        if not cert.is_active:
            WalletCertificate.query.filter(
                WalletCertificate.type == cert.type,
                WalletCertificate.platform == cert.platform,
                WalletCertificate.id != cert.id,
                WalletCertificate.is_active == True
            ).update({WalletCertificate.is_active: False})
            
        cert.is_active = not cert.is_active
        db.session.commit()
        
        logger.info(
            f"{'Activated' if cert.is_active else 'Deactivated'} certificate: {cert.name}"
        )
        
        return cert
    
    def get_certificates_by_platform(self, platform=None):
        """
        Get certificates grouped by type
        
        Args:
            platform: Filter by platform (optional)
            
        Returns:
            Dict of certificates grouped by type
        """
        query = WalletCertificate.query
        
        if platform:
            query = query.filter_by(platform=platform)
            
        certificates = query.all()
        
        result = {}
        for cert in certificates:
            if cert.type not in result:
                result[cert.type] = []
            result[cert.type].append(cert)
            
        return result


# Singleton instance
asset_service = AssetService()