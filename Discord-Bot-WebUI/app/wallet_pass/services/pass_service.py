# app/wallet_pass/services/pass_service.py

"""
Unified Wallet Pass Service

Provides a high-level interface for creating, managing, and validating
wallet passes across different platforms (Apple, Google).
"""

import re
import json
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional, Dict, Any, List, Tuple

from app.core import db
from app.models.wallet import (
    WalletPass, WalletPassType, WalletPassCheckin,
    PassStatus, create_ecs_membership_pass, create_pub_league_pass
)
from app.wallet_pass.generators import (
    ApplePassGenerator, validate_apple_config,
    GooglePassGenerator, validate_google_config, GOOGLE_WALLET_AVAILABLE
)

logger = logging.getLogger(__name__)


class PassService:
    """
    Unified service for wallet pass operations.

    Handles pass creation, generation, validation, and management
    for both Apple and Google Wallet platforms.
    """

    def __init__(self):
        self._apple_config_valid = None
        self._google_config_valid = None

    # =========================================================================
    # Pass Creation
    # =========================================================================

    def create_ecs_membership(
        self,
        member_name: str,
        member_email: str,
        year: int,
        woo_order_id: Optional[int] = None,
        user_id: Optional[int] = None,
        subgroup: Optional[str] = None,
        commit: bool = True
    ) -> WalletPass:
        """
        Create an ECS membership pass.

        Args:
            member_name: Name to display on pass
            member_email: Member's email address
            year: Membership year (e.g., 2025)
            woo_order_id: WooCommerce order ID (optional)
            user_id: Portal user ID (optional)
            subgroup: Supporter subgroup (optional, e.g., 'Gorilla FC')
            commit: Whether to commit to database

        Returns:
            WalletPass instance
        """
        wallet_pass = create_ecs_membership_pass(
            member_name=member_name,
            member_email=member_email,
            year=year,
            woo_order_id=woo_order_id,
            user_id=user_id,
            subgroup=subgroup
        )

        db.session.add(wallet_pass)
        if commit:
            db.session.commit()

        logger.info(
            f"Created ECS membership pass for {member_name} ({year}), "
            f"order: {woo_order_id}, subgroup: {subgroup}"
        )
        return wallet_pass

    def create_pub_league_pass(
        self,
        player,
        season,
        woo_order_id: Optional[int] = None,
        commit: bool = True
    ) -> WalletPass:
        """
        Create a Pub League pass for a player.

        Args:
            player: Player model instance
            season: Season model instance
            woo_order_id: WooCommerce order ID (optional)
            commit: Whether to commit to database

        Returns:
            WalletPass instance
        """
        wallet_pass = create_pub_league_pass(
            player=player,
            season=season,
            woo_order_id=woo_order_id
        )

        db.session.add(wallet_pass)
        if commit:
            db.session.commit()

        logger.info(
            f"Created Pub League pass for {player.name} ({season.name}), "
            f"order: {woo_order_id}"
        )
        return wallet_pass

    # =========================================================================
    # Pass Generation (File/URL Creation)
    # =========================================================================

    def generate_apple_pass(self, wallet_pass: WalletPass) -> BytesIO:
        """
        Generate Apple Wallet .pkpass file.

        Args:
            wallet_pass: WalletPass model instance

        Returns:
            BytesIO containing .pkpass file
        """
        generator = ApplePassGenerator(wallet_pass.pass_type)
        pass_file = generator.generate(wallet_pass)

        # Record the download
        wallet_pass.record_download('apple')
        db.session.commit()

        return pass_file

    def generate_google_pass_url(
        self,
        wallet_pass: WalletPass,
        apple_pass_bytes: Optional[bytes] = None
    ) -> str:
        """
        Generate Google Wallet save URL.

        Generates a native Google Wallet pass using JWT signing.
        Uses the same field configurations as Apple passes for parity.

        Args:
            wallet_pass: WalletPass model instance
            apple_pass_bytes: Ignored (kept for API compatibility)

        Returns:
            URL string for "Add to Google Wallet"
        """
        if not GOOGLE_WALLET_AVAILABLE:
            raise NotImplementedError(
                "Google Wallet is not configured. Ensure GOOGLE_WALLET_ISSUER_ID "
                "is set and service account credentials are available."
            )

        generator = GooglePassGenerator(wallet_pass.pass_type)
        save_url = generator.generate(wallet_pass, apple_pass_bytes=apple_pass_bytes)

        # Record the download
        wallet_pass.record_download('google')
        db.session.commit()

        return save_url

    def generate_both_platforms(
        self,
        wallet_pass: WalletPass
    ) -> Dict[str, Any]:
        """
        Generate passes for both Apple and Google Wallet platforms.

        Creates both platform passes from a single wallet pass record.
        The Google pass is generated by converting the Apple pass,
        ensuring consistency across platforms.

        Args:
            wallet_pass: WalletPass model instance

        Returns:
            Dict with 'apple' (BytesIO) and 'google' (URL string) keys.
            Values may be None if platform is not configured.
        """
        result = {
            'apple': None,
            'google': None,
            'apple_error': None,
            'google_error': None,
        }

        apple_pass_bytes = None

        # Generate Apple pass first (needed for both platforms)
        try:
            apple_config = self.get_apple_config_status()
            if apple_config.get('configured'):
                apple_pass_file = self.generate_apple_pass(wallet_pass)
                result['apple'] = apple_pass_file
                # Store bytes for Google conversion
                apple_pass_bytes = apple_pass_file.getvalue()
                # Reset file position for any subsequent reads
                apple_pass_file.seek(0)
                logger.info(f"Generated Apple pass for {wallet_pass.member_name}")
        except Exception as e:
            result['apple_error'] = str(e)
            logger.error(f"Error generating Apple pass: {e}")

        # Generate Google pass by converting Apple pass
        try:
            google_config = self.get_google_config_status()
            if google_config.get('configured'):
                # Reuse Apple pass bytes if available (more efficient)
                result['google'] = self.generate_google_pass_url(
                    wallet_pass,
                    apple_pass_bytes=apple_pass_bytes
                )
                logger.info(f"Generated Google pass for {wallet_pass.member_name}")
        except Exception as e:
            result['google_error'] = str(e)
            logger.error(f"Error generating Google pass: {e}")

        return result

    def get_pass_download(
        self,
        wallet_pass: WalletPass,
        platform: str = 'apple'
    ) -> Tuple[BytesIO, str, str]:
        """
        Get pass download file with metadata.

        Args:
            wallet_pass: WalletPass model instance
            platform: 'apple' or 'google'

        Returns:
            Tuple of (file_bytes, filename, mimetype)
        """
        if platform == 'apple':
            pass_file = self.generate_apple_pass(wallet_pass)
            safe_name = wallet_pass.member_name.replace(' ', '_')
            filename = f"{safe_name}_{wallet_pass.pass_type.code}.pkpass"
            mimetype = 'application/vnd.apple.pkpass'
            return pass_file, filename, mimetype
        elif platform == 'google':
            # Google returns a URL, not a file
            url = self.generate_google_pass_url(wallet_pass)
            return url, None, None
        else:
            raise ValueError(f"Unknown platform: {platform}")

    # =========================================================================
    # Pass Lookup
    # =========================================================================

    def find_by_download_token(self, token: str) -> Optional[WalletPass]:
        """Find pass by download token"""
        return WalletPass.find_by_download_token(token)

    def find_by_barcode(self, barcode: str) -> Optional[WalletPass]:
        """Find pass by barcode data"""
        return WalletPass.find_by_barcode(barcode)

    def find_by_woo_order(self, order_id: int) -> List[WalletPass]:
        """Find all passes for a WooCommerce order"""
        return WalletPass.find_by_woo_order(order_id)

    def find_active_for_user(
        self,
        user_id: int,
        pass_type_code: Optional[str] = None
    ) -> List[WalletPass]:
        """Find active passes for a user"""
        return WalletPass.find_active_for_user(user_id, pass_type_code)

    # =========================================================================
    # Pass Validation
    # =========================================================================

    def validate_barcode(
        self,
        barcode: str,
        record_checkin: bool = True,
        check_in_type: str = 'qr_scan',
        location: Optional[str] = None,
        event_name: Optional[str] = None,
        checked_by_user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Validate a pass by its barcode.

        Args:
            barcode: Barcode data string
            record_checkin: Whether to record this as a check-in
            check_in_type: Type of check-in (qr_scan, nfc_tap, manual)
            location: Location of check-in
            event_name: Name of event
            checked_by_user_id: User ID who performed the check-in

        Returns:
            Dict with validation result
        """
        # Parse barcode
        parsed = self._parse_barcode(barcode)
        if not parsed:
            return {
                'valid': False,
                'error': 'Invalid barcode format',
                'barcode': barcode
            }

        # Find pass
        wallet_pass = WalletPass.query.filter(
            WalletPass.barcode_data == barcode
        ).first()

        if not wallet_pass:
            return {
                'valid': False,
                'error': 'Pass not found',
                'barcode': barcode
            }

        # Check validity
        is_valid = wallet_pass.is_valid
        validation_message = None

        if not is_valid:
            if wallet_pass.status == PassStatus.VOIDED.value:
                validation_message = 'Pass has been voided'
            elif wallet_pass.is_expired:
                validation_message = 'Pass has expired'
            else:
                validation_message = 'Pass is not active'

        # Record check-in
        if record_checkin:
            WalletPassCheckin.record_checkin(
                wallet_pass=wallet_pass,
                check_in_type=check_in_type,
                location=location,
                event_name=event_name,
                checked_by_user_id=checked_by_user_id,
                was_valid=is_valid,
                validation_message=validation_message
            )
            db.session.commit()

        return {
            'valid': is_valid,
            'message': validation_message,
            'pass': {
                'id': wallet_pass.id,
                'member_name': wallet_pass.member_name,
                'pass_type': wallet_pass.pass_type.name,
                'team_name': wallet_pass.team_name,
                'valid_until': wallet_pass.valid_until.isoformat(),
                'status': wallet_pass.status,
                'display_validity': wallet_pass.display_validity
            },
            'checkin_recorded': record_checkin
        }

    def _parse_barcode(self, barcode: str) -> Optional[Dict[str, str]]:
        """
        Parse barcode data.

        Expected format: ECSFC-{TYPE}-{SERIAL}
        Example: ECSFC-ECS-A1B2C3D4E5F6

        Returns:
            Dict with parsed components or None if invalid
        """
        pattern = r'^ECSFC-([A-Z]{3})-([A-Z0-9]+)$'
        match = re.match(pattern, barcode.upper())

        if not match:
            return None

        return {
            'type_code': match.group(1),
            'serial': match.group(2)
        }

    # =========================================================================
    # Pass Management
    # =========================================================================

    def void_pass(
        self,
        wallet_pass: WalletPass,
        reason: Optional[str] = None,
        voided_by_user_id: Optional[int] = None,
        send_push: bool = True
    ) -> WalletPass:
        """
        Void a pass.

        Args:
            wallet_pass: WalletPass to void
            reason: Reason for voiding
            voided_by_user_id: User who voided the pass
            send_push: Whether to send push updates to devices

        Returns:
            Updated WalletPass instance
        """
        wallet_pass.void(reason=reason, voided_by_user_id=voided_by_user_id)
        db.session.commit()

        logger.info(
            f"Voided pass {wallet_pass.serial_number} for {wallet_pass.member_name}: {reason}"
        )

        # Send push notification to update pass on device
        if send_push:
            try:
                from app.wallet_pass.services.push_service import push_service
                push_result = push_service.send_update_to_all_platforms(wallet_pass)
                logger.info(f"Push update result for voided pass: {push_result}")
            except Exception as e:
                logger.warning(f"Failed to send push update for voided pass: {e}")

        return wallet_pass

    def reactivate_pass(self, wallet_pass: WalletPass, send_push: bool = True) -> WalletPass:
        """
        Reactivate a voided pass.

        Args:
            wallet_pass: WalletPass to reactivate
            send_push: Whether to send push updates to devices

        Returns:
            Updated WalletPass instance
        """
        if wallet_pass.is_expired:
            raise ValueError("Cannot reactivate an expired pass")

        wallet_pass.status = PassStatus.ACTIVE.value
        wallet_pass.voided_at = None
        wallet_pass.voided_reason = None
        wallet_pass.voided_by_user_id = None
        wallet_pass.version += 1
        db.session.commit()

        logger.info(f"Reactivated pass {wallet_pass.serial_number}")

        # Send push notification to update pass on device
        if send_push:
            try:
                from app.wallet_pass.services.push_service import push_service
                push_result = push_service.send_update_to_all_platforms(wallet_pass)
                logger.info(f"Push update result for reactivated pass: {push_result}")
            except Exception as e:
                logger.warning(f"Failed to send push update for reactivated pass: {e}")

        return wallet_pass

    def update_pass_type_design(
        self,
        pass_type_id: int,
        send_push: bool = True
    ) -> Dict[str, Any]:
        """
        Update all passes when pass type design changes.

        When colors, logos, or other design elements change,
        this pushes updates to all devices with passes of this type.
        Also updates the Google Wallet class definition.

        Args:
            pass_type_id: ID of the pass type that was updated
            send_push: Whether to send push updates to devices

        Returns:
            Dict with summary of update results
        """
        from app.models.wallet import WalletPassType

        pass_type = WalletPassType.query.get(pass_type_id)
        if not pass_type:
            raise ValueError(f"Pass type {pass_type_id} not found")

        result = {
            'pass_type': pass_type.name,
            'total_passes': 0,
            'push_results': None,
            'google_class_updated': False
        }

        # Update Google Wallet class definition with new design
        try:
            from app.wallet_pass.generators.google import (
                GooglePassConfig, ensure_google_wallet_class_exists
            )
            config = GooglePassConfig()
            if config.issuer_id:
                ensure_google_wallet_class_exists(config, pass_type, force_update=True)
                result['google_class_updated'] = True
                logger.info(f"Updated Google Wallet class for {pass_type.name}")
        except Exception as e:
            logger.warning(f"Could not update Google Wallet class: {e}")
            result['google_class_error'] = str(e)

        if send_push:
            try:
                from app.wallet_pass.services.push_service import push_service
                result['push_results'] = push_service.update_pass_design(pass_type)
                result['total_passes'] = result['push_results'].get('total_passes', 0)
                logger.info(f"Design update pushed for {pass_type.name}: {result['push_results']}")
            except Exception as e:
                result['error'] = str(e)
                logger.error(f"Failed to push design update: {e}")

        return result

    # =========================================================================
    # WooCommerce Integration
    # =========================================================================

    def process_woo_order(
        self,
        order_id: int,
        customer_name: str,
        customer_email: str,
        products: List[Dict[str, Any]],
        order_meta: Optional[Dict[str, Any]] = None
    ) -> List[WalletPass]:
        """
        Process a WooCommerce order and create appropriate passes.

        Args:
            order_id: WooCommerce order ID
            customer_name: Customer's name
            customer_email: Customer's email
            products: List of product dicts with 'name' and 'quantity'
            order_meta: Order metadata (may contain 'subgroup', custom fields)

        Returns:
            List of created WalletPass instances
        """
        created_passes = []
        order_meta = order_meta or {}

        # Extract subgroup from order meta (common field names)
        subgroup = (
            order_meta.get('subgroup') or
            order_meta.get('supporter_group') or
            order_meta.get('ecs_subgroup') or
            order_meta.get('_billing_subgroup')
        )

        for product in products:
            product_name = product.get('name', '')
            quantity = product.get('quantity', 1)

            # Product-level metadata may override order-level
            product_meta = product.get('meta', {})
            product_subgroup = (
                product_meta.get('subgroup') or
                product_meta.get('supporter_group') or
                subgroup  # Fall back to order-level
            )

            # Check for ECS Membership
            ecs_match = self._match_ecs_membership_product(product_name)
            if ecs_match:
                year = ecs_match['year']
                for _ in range(quantity):
                    wallet_pass = self.create_ecs_membership(
                        member_name=customer_name,
                        member_email=customer_email,
                        year=year,
                        woo_order_id=order_id,
                        subgroup=product_subgroup,
                        commit=False
                    )
                    created_passes.append(wallet_pass)
                continue

            # Check for Pub League (would need player matching logic)
            # pub_match = self._match_pub_league_product(product_name)
            # if pub_match:
            #     # Pub League passes are typically created during registration
            #     # not directly from WooCommerce orders
            #     pass

        if created_passes:
            db.session.commit()
            logger.info(
                f"Created {len(created_passes)} passes for WooCommerce order {order_id}"
            )

        return created_passes

    def _match_ecs_membership_product(self, product_name: str) -> Optional[Dict]:
        """
        Check if product name matches ECS membership pattern.

        Patterns (case-insensitive, ignores suffixes like "(testing)"):
        - "ECS 2026 Membership Card"
        - "ECS 2026 Membership Card (testing)"
        - "ECS Membership 2024"
        - "ECS Membership Package 2024"

        Returns:
            Dict with 'year' if matched, None otherwise
        """
        # Strip any parenthetical suffixes for cleaner matching (e.g., "(testing)")
        clean_name = re.sub(r'\s*\([^)]*\)\s*$', '', product_name).strip()

        patterns = [
            r'ECS\s+(\d{4})\s+Membership',           # "ECS 2026 Membership..."
            r'ECS\s+Membership\s+(\d{4})',            # "ECS Membership 2026"
            r'ECS\s+Membership\s+Card\s*(\d{4})?',    # "ECS Membership Card" (optionally with year)
            r'ECS\s+Membership\s+Package\s+(\d{4})',  # "ECS Membership Package 2026"
        ]

        for pattern in patterns:
            # Try clean name first, then original
            for name in [clean_name, product_name]:
                match = re.search(pattern, name, re.IGNORECASE)
                if match:
                    year_str = match.group(1) if match.lastindex and match.group(1) else None
                    if year_str:
                        return {'year': int(year_str)}
                    else:
                        # Default to current year if not specified
                        return {'year': datetime.now().year}

        return None

    # =========================================================================
    # Configuration Status
    # =========================================================================

    def get_apple_config_status(self) -> Dict[str, Any]:
        """Get Apple Wallet configuration status"""
        return validate_apple_config()

    def get_google_config_status(self) -> Dict[str, Any]:
        """Get Google Wallet configuration status"""
        is_valid, errors = validate_google_config()
        return {
            'configured': is_valid,
            'issues': errors
        }

    def get_config_status(self) -> Dict[str, Any]:
        """Get overall wallet configuration status"""
        apple = self.get_apple_config_status()
        google = self.get_google_config_status()

        return {
            'apple': apple,
            'google': google,
            'any_configured': apple['configured'] or google['configured']
        }

    def is_pass_type_ready(self, pass_type_code: str) -> Dict[str, Any]:
        """
        Check if a specific pass type is ready for pass generation.

        A pass type is ready when:
        - Certificates are configured (shared)
        - The specific pass type has all required assets (icon, logo)
        - The specific pass type has a default template

        Args:
            pass_type_code: 'ecs_membership' or 'pub_league'

        Returns:
            Dict with 'ready' bool and details about what's missing
        """
        from app.models.wallet_asset import WalletAsset, WalletTemplate, WalletCertificate

        result = {
            'ready': False,
            'pass_type_exists': False,
            'certificates_complete': False,
            'assets_complete': False,
            'template_complete': False,
            'issues': []
        }

        # Check certificates (shared between pass types)
        cert_complete = WalletCertificate.has_complete_apple_config()
        result['certificates_complete'] = cert_complete
        if not cert_complete:
            result['issues'].append('Apple signing certificates not configured')

        # Get pass type
        if pass_type_code == 'ecs_membership':
            pass_type = WalletPassType.get_ecs_membership()
        elif pass_type_code == 'pub_league':
            pass_type = WalletPassType.get_pub_league()
        else:
            result['issues'].append(f'Unknown pass type: {pass_type_code}')
            return result

        if not pass_type:
            result['issues'].append(f'Pass type {pass_type_code} not initialized')
            return result

        result['pass_type_exists'] = True

        # Check assets
        required_assets = ['icon', 'logo']
        assets = WalletAsset.get_assets_by_pass_type(pass_type.id)
        assets_complete = all(any(a.asset_type == req for a in assets) for req in required_assets)
        result['assets_complete'] = assets_complete
        if not assets_complete:
            missing = [req for req in required_assets if not any(a.asset_type == req for a in assets)]
            result['issues'].append(f'Missing assets for {pass_type.name}: {", ".join(missing)}')

        # Check template
        template = WalletTemplate.get_default(pass_type.id, 'apple')
        result['template_complete'] = template is not None
        if not template:
            result['issues'].append(f'No default template for {pass_type.name}')

        # Overall readiness
        result['ready'] = cert_complete and assets_complete and template is not None

        return result

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_statistics(self) -> Dict[str, Any]:
        """Get wallet pass statistics"""
        from sqlalchemy import func

        stats = {
            'total_passes': WalletPass.query.count(),
            'active_passes': WalletPass.query.filter_by(status=PassStatus.ACTIVE.value).count(),
            'voided_passes': WalletPass.query.filter_by(status=PassStatus.VOIDED.value).count(),
            'total_checkins': WalletPassCheckin.query.count(),
            'by_type': {}
        }

        # Stats by pass type
        for pass_type in WalletPassType.query.all():
            type_stats = {
                'total': WalletPass.query.filter_by(pass_type_id=pass_type.id).count(),
                'active': WalletPass.query.filter_by(
                    pass_type_id=pass_type.id,
                    status=PassStatus.ACTIVE.value
                ).count()
            }
            stats['by_type'][pass_type.code] = type_stats

        return stats


# Singleton instance
pass_service = PassService()
