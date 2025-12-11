"""
Apple Wallet Pass Generation Module

This module handles the creation and signing of Apple Wallet (.pkpass) files
for ECS FC membership cards. It integrates with the existing player/user database
to generate personalized membership passes.
"""

import os
import json
import uuid
import logging
import requests
from datetime import datetime, timedelta
from io import BytesIO
from flask import current_app
from wallet.models import Pass, Barcode, StoreCard
from PIL import Image

logger = logging.getLogger(__name__)


class WalletPassConfig:
    """Configuration class for wallet pass settings"""
    
    def __init__(self):
        # These should be set via environment variables or config
        # Force new pass type to bypass env variable issue
        self.pass_type_identifier = 'pass.com.weareecs.membership'
        # Use the Apple Developer Team ID from environment (required)
        self.team_identifier = os.getenv('WALLET_TEAM_ID')
        if not self.team_identifier:
            raise ValueError("WALLET_TEAM_ID environment variable is required")
        self.organization_name = 'ECS FC'
        self.certificate_path = os.getenv('WALLET_CERT_PATH', 'app/wallet_pass/certs/certificate.pem')
        self.key_path = os.getenv('WALLET_KEY_PATH', 'app/wallet_pass/certs/key.pem')
        self.wwdr_path = os.getenv('WALLET_WWDR_PATH', 'app/wallet_pass/certs/wwdr.pem')
        self.key_password = os.getenv('WALLET_KEY_PASSWORD', '')
        self.web_service_url = os.getenv('WALLET_WEB_SERVICE_URL', '')


class ECSFCPassGenerator:
    """Generates Apple Wallet passes for ECS FC members"""
    
    def __init__(self, config=None):
        self.config = config or WalletPassConfig()
        self.template_path = 'app/wallet_pass/templates/ecsfc_pass.json'
        self.assets_path = 'app/wallet_pass/assets'
    
    def generate_pass_for_player(self, player):
        """
        Generate a wallet pass for a specific player
        
        Args:
            player: Player model instance
            
        Returns:
            BytesIO: Generated .pkpass file as bytes
        """
        try:
            # Validate player eligibility
            if not self._is_player_eligible(player):
                raise ValueError(f"Player {player.name} is not eligible for a membership pass")
            
            # Load and customize pass template
            pass_data = self._load_pass_template(player)
            
            # Create the pass object
            pass_obj = self._create_pass_object(pass_data, player)
            
            # Add required assets including player profile image
            self._add_pass_assets(pass_obj, player)
            
            # Generate and sign the pass
            pass_file = self._sign_and_create_pass(pass_obj)
            
            logger.info(f"Successfully generated wallet pass for player {player.name} (ID: {player.id})")
            return pass_file
            
        except Exception as e:
            logger.error(f"Error generating wallet pass for player {player.name}: {str(e)}")
            raise
    
    def _is_player_eligible(self, player):
        """Check if player is eligible for a membership pass"""
        # Check if player has any team assignment (primary, current season, or any team)
        has_any_team = (
            (hasattr(player, 'primary_team') and player.primary_team is not None) or
            (hasattr(player, 'teams') and player.teams and len(player.teams) > 0)
        )
        
        return (
            player.is_current_player and
            player.user and
            player.user.is_authenticated and
            has_any_team
        )
    
    def _load_pass_template(self, player):
        """Load and customize the pass template with player data"""
        try:
            logger.info(f"Loading template from: {self.template_path}")
            logger.info(f"Template file exists: {os.path.exists(self.template_path)}")
            
            with open(self.template_path, 'r') as f:
                template = f.read()
            
            logger.info(f"Template contains #213e96: {'#213e96' in template}")
            logger.info(f"Template contains backgroundColor: {'backgroundColor' in template}")
            
            # Get player data for template
            template_data = self._get_template_data(player)
            
            # Replace template variables
            for key, value in template_data.items():
                template = template.replace(f'{{{{{key}}}}}', str(value))
            
            # Debug: Log the final JSON being used
            logger.info(f"Final pass JSON contains backgroundColor: {'#213e96' in template}")
            logger.info(f"Pass type in final JSON: {template_data.get('pass_type_identifier', 'NOT_SET')}")
            
            # Log a snippet of the actual JSON
            parsed_json = json.loads(template)
            logger.info(f"Actual backgroundColor in JSON: {parsed_json.get('backgroundColor', 'MISSING')}")
            logger.info(f"Actual passTypeIdentifier in JSON: {parsed_json.get('passTypeIdentifier', 'MISSING')}")
            
            return parsed_json
            
        except Exception as e:
            logger.error(f"Error loading pass template: {str(e)}")
            raise
    
    def _get_template_data(self, player):
        """Extract template data from player model"""
        # Generate unique identifiers
        pass_uuid = str(uuid.uuid4())
        auth_token = str(uuid.uuid4())
        
        # Get current season info
        current_season = self._get_current_season()
        season_name = current_season.name if current_season else "Current Season"
        
        # Team information - get the best available team
        team_name = "Unassigned"
        if player.primary_team:
            team_name = player.primary_team.name
        elif hasattr(player, 'teams') and player.teams and len(player.teams) > 0:
            team_name = player.teams[0].name
            
        league_name = player.league.name if player.league else "ECS Pub League"
        
        # Player status
        status = "Active Member" if player.is_current_player else "Inactive"
        
        # Simple barcode data for scanning (keep it simple for QR code readability)
        barcode_data = f"ECSFC-{player.id}-{team_name}-{season_name}-{pass_uuid[:8]}"
        
        # Set expiration date (end of current season + 1 month grace period)
        expiration_date = self._get_expiration_date(current_season)
        
        # Check if pass should be voided (player no longer current)
        voided = "false" if player.is_current_player else "true"
        
        # Get additional player info
        season_history = self._get_season_history(player)
        
        # Debug logging
        logger.info(f"Generating pass with ECS blue background and season history: {season_history}")
        
        return {
            'uuid': pass_uuid,
            'user_name': player.name,
            'team_name': team_name,
            'season': season_name,
            'league_name': league_name,
            'player_id': str(player.id),
            'status': status,
            'phone': player.phone or 'N/A',
            'issue_date': datetime.now().strftime('%Y-%m-%d'),
            'barcode_data': barcode_data,
            'web_service_url': self.config.web_service_url,
            'auth_token': auth_token,
            'expiration_date': expiration_date,
            'voided': voided,
            'team_identifier': self.config.team_identifier,
            'pass_type_identifier': self.config.pass_type_identifier,
            'organization_name': self.config.organization_name,
            'season_history': season_history
        }
    
    def _get_current_season(self):
        """Get the current active Pub League season"""
        try:
            from app.models import Season
            # Get Pub League season since that's what determines membership
            return Season.query.filter_by(
                league_type='Pub League',
                is_current=True
            ).first()
        except Exception as e:
            logger.warning(f"Could not fetch current Pub League season: {str(e)}")
            return None
    
    def _get_expiration_date(self, season):
        """Calculate expiration date for the pass"""
        try:
            from datetime import datetime, timedelta
            
            if season and hasattr(season, 'end_date') and season.end_date:
                # Season end date + 1 month grace period
                expiration = season.end_date + timedelta(days=30)
            else:
                # Default: 1 year from now
                expiration = datetime.now() + timedelta(days=365)
            
            # Return in ISO format for Apple Wallet
            return expiration.strftime('%Y-%m-%dT%H:%M:%SZ')
            
        except Exception as e:
            logger.warning(f"Error calculating expiration date: {str(e)}")
            # Default: 1 year from now
            return (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    def _get_season_history(self, player):
        """Get player's season history"""
        try:
            from app.models import PlayerTeamSeason, Season, Team
            
            # Get player's season assignments
            assignments = PlayerTeamSeason.query\
                .join(Season).join(Team)\
                .filter(PlayerTeamSeason.player_id == player.id)\
                .order_by(Season.start_date.desc())\
                .limit(5).all()
            
            if not assignments:
                return "New player - first season"
            
            history_parts = []
            for assignment in assignments:
                season_name = assignment.season.name if assignment.season else "Unknown Season"
                team_name = assignment.team.name if assignment.team else "Unknown Team"
                history_parts.append(f"{season_name}: {team_name}")
            
            return " • ".join(history_parts[:3])  # Limit to 3 most recent
        except Exception as e:
            logger.warning(f"Error getting season history: {str(e)}")
            return "History unavailable"
    
    def _create_pass_object(self, pass_data, player):
        """Create the wallet pass object"""
        try:
            # Create store card (best for membership/loyalty cards - supports strip image)
            card_info = StoreCard()

            # Add primary fields - try storeCard first, fall back to generic for compatibility
            card_data = pass_data.get('storeCard', pass_data.get('generic', {}))
            for field in card_data.get('primaryFields', []):
                card_info.addPrimaryField(field['key'], field['value'], field['label'])
            
            # Add secondary fields
            for field in card_data.get('secondaryFields', []):
                card_info.addSecondaryField(field['key'], field['value'], field['label'])

            # Add auxiliary fields
            for field in card_data.get('auxiliaryFields', []):
                card_info.addAuxiliaryField(field['key'], field['value'], field['label'])

            # Add back fields
            for field in card_data.get('backFields', []):
                card_info.addBackField(field['key'], field['value'], field['label'])
            
            # Create the pass
            pass_obj = Pass(
                card_info,
                passTypeIdentifier=pass_data['passTypeIdentifier'],
                organizationName=pass_data['organizationName'],
                teamIdentifier=pass_data['teamIdentifier']
            )
            
            # Set pass properties
            pass_obj.serialNumber = pass_data['serialNumber']
            pass_obj.description = pass_data['description']
            
            # Add barcode
            if 'barcode' in pass_data:
                barcode_format = pass_data['barcode']['format']
                barcode_message = pass_data['barcode']['message']
                pass_obj.barcode = Barcode(
                    message=barcode_message,
                    format=barcode_format
                )
            
            # Set colors
            if 'backgroundColor' in pass_data:
                pass_obj.backgroundColor = pass_data['backgroundColor']
            if 'foregroundColor' in pass_data:
                pass_obj.foregroundColor = pass_data['foregroundColor']
            if 'labelColor' in pass_data:
                pass_obj.labelColor = pass_data['labelColor']
            
            # Set logo text
            if 'logoText' in pass_data:
                pass_obj.logoText = pass_data['logoText']
            
            # Web service configuration for push updates
            if pass_data.get('webServiceURL'):
                pass_obj.webServiceURL = pass_data['webServiceURL']
                pass_obj.authenticationToken = pass_data['authenticationToken']
            
            return pass_obj
            
        except Exception as e:
            logger.error(f"Error creating pass object: {str(e)}")
            raise
    
    def _add_pass_assets(self, pass_obj, player=None):
        """Add required image assets to the pass"""
        assets = {
            'icon.png': 'icon.png',
            'icon@2x.png': 'icon@2x.png', 
            'logo.png': 'logo.png',
            'logo@2x.png': 'logo@2x.png'
        }
        
        # Add standard assets
        for pass_filename, asset_filename in assets.items():
            asset_path = os.path.join(self.assets_path, asset_filename)
            if os.path.exists(asset_path):
                with open(asset_path, 'rb') as f:
                    pass_obj.addFile(pass_filename, f)
                logger.debug(f"Added asset: {pass_filename}")
            else:
                logger.warning(f"Asset not found: {asset_path}")
        
        # Add player profile image if available
        if player and self._add_player_profile_image(pass_obj, player):
            logger.info(f"Successfully added player profile image for {player.name}")
        else:
            logger.warning(f"Could not add profile image for {player.name if player else 'unknown player'}")
    
    def _add_player_profile_image(self, pass_obj, player):
        """Add player's profile image to the pass"""
        try:
            if not player.profile_picture_url:
                return False
            
            # Get the profile image
            image_data = self._get_player_image_data(player.profile_picture_url)
            if not image_data:
                return False
            
            # Process image for wallet pass (Apple recommends 180x180 for thumbnail)
            processed_image = self._process_image_for_wallet(image_data)
            if not processed_image:
                return False
            
            # Try both strip and thumbnail to see which works
            pass_obj.addFile('strip.png', processed_image)
            pass_obj.addFile('strip@2x.png', processed_image)
            pass_obj.addFile('thumbnail.png', processed_image)
            pass_obj.addFile('thumbnail@2x.png', processed_image)
            
            return True
        except Exception as e:
            logger.warning(f"Error adding player profile image: {str(e)}")
            return False
    
    def _get_player_image_data(self, image_url):
        """Download and return player's profile image data"""
        try:
            if image_url.startswith('/static/'):
                # Local file
                local_path = os.path.join('app', image_url.lstrip('/'))
                if os.path.exists(local_path):
                    with open(local_path, 'rb') as f:
                        return BytesIO(f.read())
            elif image_url.startswith('http'):
                # Remote image
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    return BytesIO(response.content)
            
            return None
        except Exception as e:
            logger.warning(f"Error downloading image from {image_url}: {str(e)}")
            return None
    
    def _process_image_for_wallet(self, image_data):
        """Process image for Apple Wallet (resize, format, etc.)"""
        try:
            # Open image with PIL
            img = Image.open(image_data)
            
            # Convert to RGB if needed
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            
            # Resize to Apple Wallet strip image size (320x84 for main visual element)
            img = img.resize((320, 84), Image.Resampling.LANCZOS)
            
            # Save as PNG
            output = BytesIO()
            img.save(output, format='PNG', optimize=True)
            output.seek(0)
            
            return output
        except Exception as e:
            logger.warning(f"Error processing image for wallet: {str(e)}")
            return None
    
    def _sign_and_create_pass(self, pass_obj):
        """Sign and create the final .pkpass file"""
        try:
            # Check if certificate files exist
            if not all(os.path.exists(path) for path in [
                self.config.certificate_path,
                self.config.key_path, 
                self.config.wwdr_path
            ]):
                raise FileNotFoundError("Required certificate files not found")
            
            # Validate configuration before creating pass
            self._validate_pass_configuration()
            
            # Create pass file in memory
            pass_buffer = BytesIO()
            
            # Create the signed pass
            pass_obj.create(
                self.config.certificate_path,
                self.config.key_path,
                self.config.wwdr_path,
                self.config.key_password,
                pass_buffer
            )
            
            pass_buffer.seek(0)
            return pass_buffer
            
        except Exception as e:
            logger.error(f"Error signing pass: {str(e)}")
            raise
    
    def _validate_pass_configuration(self):
        """Validate that the pass configuration meets Apple requirements"""
        errors = []
        
        # Check team identifier format (should be 10 characters)
        if len(self.config.team_identifier) != 10:
            errors.append(f"Team identifier must be exactly 10 characters, got {len(self.config.team_identifier)}")
        
        # Check pass type identifier format
        if not self.config.pass_type_identifier.startswith('pass.'):
            errors.append("Pass type identifier must start with 'pass.'")
        
        # Verify certificates are properly formatted
        try:
            with open(self.config.certificate_path, 'r') as f:
                cert_content = f.read()
                if not ('-----BEGIN CERTIFICATE-----' in cert_content and '-----END CERTIFICATE-----' in cert_content):
                    errors.append("Certificate file appears to be invalid")
        except Exception as e:
            errors.append(f"Cannot read certificate file: {str(e)}")
        
        if errors:
            raise ValueError(f"Pass configuration errors: {'; '.join(errors)}")


def create_pass_for_player(player_id):
    """
    Convenience function to create a pass for a player by ID
    
    Args:
        player_id: Player ID
        
    Returns:
        BytesIO: Generated .pkpass file
    """
    from app.models import Player
    
    player = Player.query.get(player_id)
    if not player:
        raise ValueError(f"Player with ID {player_id} not found")
    
    generator = ECSFCPassGenerator()
    return generator.generate_pass_for_player(player)


def validate_pass_configuration(pass_type_code=None):
    """
    Validate that the wallet pass system is properly configured.

    Args:
        pass_type_code: Optional. If provided ('ecs' or 'pub'), validates
            that specific pass type using database assets. If None, validates
            that at least one pass type is fully configured.

    Returns:
        dict: Configuration status and any issues
    """
    from app.models.wallet import WalletPassType
    from app.models.wallet_asset import WalletAsset, WalletCertificate

    issues = []
    ecs_ready = False
    pub_ready = False

    # Check certificates from database (shared between both pass types)
    apple_cert_complete = WalletCertificate.has_complete_apple_config()
    google_cert_complete = WalletCertificate.has_complete_google_config()
    cert_complete = apple_cert_complete or google_cert_complete

    if not cert_complete:
        issues.append("No wallet certificates configured (Apple or Google)")

    required_assets = ['icon', 'logo']

    if pass_type_code:
        # Validate specific pass type
        if pass_type_code == 'ecs':
            pass_type = WalletPassType.get_ecs_membership()
        elif pass_type_code == 'pub':
            pass_type = WalletPassType.get_pub_league()
        else:
            issues.append(f"Unknown pass type: {pass_type_code}")
            pass_type = None

        if pass_type:
            assets = WalletAsset.get_assets_by_pass_type(pass_type.id)
            asset_types = [a.asset_type for a in assets]

            for req in required_assets:
                if req not in asset_types:
                    issues.append(f"Required asset not found for {pass_type.name}: {req}")
    else:
        # Check if at least one pass type is fully configured
        ecs_type = WalletPassType.get_ecs_membership()
        pub_type = WalletPassType.get_pub_league()

        if ecs_type:
            ecs_assets = WalletAsset.get_assets_by_pass_type(ecs_type.id)
            ecs_asset_types = [a.asset_type for a in ecs_assets]
            ecs_ready = cert_complete and all(req in ecs_asset_types for req in required_assets)

        if pub_type:
            pub_assets = WalletAsset.get_assets_by_pass_type(pub_type.id)
            pub_asset_types = [a.asset_type for a in pub_assets]
            pub_ready = cert_complete and all(req in pub_asset_types for req in required_assets)

        # Only report asset issues if NEITHER pass type is ready
        if not ecs_ready and not pub_ready:
            if ecs_type:
                for req in required_assets:
                    if req not in ecs_asset_types:
                        issues.append(f"ECS Membership missing: {req}")
            else:
                issues.append("ECS Membership pass type not configured")

            if pub_type:
                for req in required_assets:
                    if req not in pub_asset_types:
                        issues.append(f"Pub League missing: {req}")
            else:
                issues.append("Pub League pass type not configured")

    # Legacy config for backwards compatibility
    config = WalletPassConfig()

    return {
        'configured': len(issues) == 0 or ecs_ready or pub_ready,
        'issues': issues,
        'ecs_ready': ecs_ready,
        'pub_ready': pub_ready,
        'config': {
            'pass_type_identifier': config.pass_type_identifier,
            'team_identifier': config.team_identifier,
            'organization_name': config.organization_name,
            'web_service_url': config.web_service_url
        }
    }