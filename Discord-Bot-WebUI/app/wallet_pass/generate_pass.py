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
from datetime import datetime
from io import BytesIO
from flask import current_app
from wallet.models import Pass, Barcode, Generic

logger = logging.getLogger(__name__)


class WalletPassConfig:
    """Configuration class for wallet pass settings"""
    
    def __init__(self):
        # These should be set via environment variables or config
        self.pass_type_identifier = os.getenv('WALLET_PASS_TYPE_ID', 'pass.com.ecsfc.membership')
        self.team_identifier = os.getenv('WALLET_TEAM_ID', 'YOUR_TEAM_ID')
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
            
            # Add required assets
            self._add_pass_assets(pass_obj)
            
            # Generate and sign the pass
            pass_file = self._sign_and_create_pass(pass_obj)
            
            logger.info(f"Successfully generated wallet pass for player {player.name} (ID: {player.id})")
            return pass_file
            
        except Exception as e:
            logger.error(f"Error generating wallet pass for player {player.name}: {str(e)}")
            raise
    
    def _is_player_eligible(self, player):
        """Check if player is eligible for a membership pass"""
        return (
            player.is_current_player and
            player.user and
            player.user.is_authenticated and
            hasattr(player, 'primary_team') and
            player.primary_team is not None
        )
    
    def _load_pass_template(self, player):
        """Load and customize the pass template with player data"""
        try:
            with open(self.template_path, 'r') as f:
                template = f.read()
            
            # Get player data for template
            template_data = self._get_template_data(player)
            
            # Replace template variables
            for key, value in template_data.items():
                template = template.replace(f'{{{{{key}}}}}', str(value))
            
            return json.loads(template)
            
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
        
        # Team information
        team_name = player.primary_team.name if player.primary_team else "Unassigned"
        league_name = player.league.name if player.league else "ECS Pub League"
        
        # Player status
        status = "Active Member" if player.is_current_player else "Inactive"
        
        # Barcode data (could be player ID, QR code data, etc.)
        barcode_data = f"ECSFC-{player.id}-{pass_uuid[:8]}"
        
        # Set expiration date (end of current season + 1 month grace period)
        expiration_date = self._get_expiration_date(current_season)
        
        # Check if pass should be voided (player no longer current)
        voided = "false" if player.is_current_player else "true"
        
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
            'voided': voided
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
    
    def _create_pass_object(self, pass_data, player):
        """Create the wallet pass object"""
        try:
            # Create generic pass card
            card_info = Generic()
            
            # Add primary fields
            for field in pass_data.get('generic', {}).get('primaryFields', []):
                card_info.addPrimaryField(field['key'], field['value'], field['label'])
            
            # Add secondary fields
            for field in pass_data.get('generic', {}).get('secondaryFields', []):
                card_info.addSecondaryField(field['key'], field['value'], field['label'])
            
            # Add auxiliary fields  
            for field in pass_data.get('generic', {}).get('auxiliaryFields', []):
                card_info.addAuxiliaryField(field['key'], field['value'], field['label'])
            
            # Add back fields
            for field in pass_data.get('generic', {}).get('backFields', []):
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
    
    def _add_pass_assets(self, pass_obj):
        """Add required image assets to the pass"""
        assets = {
            'icon.png': 'icon.png',
            'icon@2x.png': 'icon@2x.png', 
            'logo.png': 'logo.png',
            'logo@2x.png': 'logo@2x.png'
        }
        
        for pass_filename, asset_filename in assets.items():
            asset_path = os.path.join(self.assets_path, asset_filename)
            if os.path.exists(asset_path):
                with open(asset_path, 'rb') as f:
                    pass_obj.addFile(pass_filename, f)
                logger.debug(f"Added asset: {pass_filename}")
            else:
                logger.warning(f"Asset not found: {asset_path}")
    
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


def validate_pass_configuration():
    """
    Validate that the wallet pass system is properly configured
    
    Returns:
        dict: Configuration status and any issues
    """
    config = WalletPassConfig()
    issues = []
    
    # Check certificate files
    cert_files = {
        'Certificate': config.certificate_path,
        'Private Key': config.key_path,
        'WWDR Certificate': config.wwdr_path
    }
    
    for name, path in cert_files.items():
        if not os.path.exists(path):
            issues.append(f"{name} not found at {path}")
    
    # Check required directories
    required_dirs = [
        'app/wallet_pass/templates',
        'app/wallet_pass/assets'
    ]
    
    for dir_path in required_dirs:
        if not os.path.exists(dir_path):
            issues.append(f"Directory not found: {dir_path}")
    
    # Check for required assets
    asset_path = 'app/wallet_pass/assets'
    required_assets = ['icon.png', 'logo.png']
    
    for asset in required_assets:
        if not os.path.exists(os.path.join(asset_path, asset)):
            issues.append(f"Required asset not found: {asset}")
    
    return {
        'configured': len(issues) == 0,
        'issues': issues,
        'config': {
            'pass_type_identifier': config.pass_type_identifier,
            'team_identifier': config.team_identifier,
            'organization_name': config.organization_name,
            'web_service_url': config.web_service_url
        }
    }