"""
Pub League Order Admin Routes

Admin routes for managing Pub League WooCommerce orders, including:
- Viewing all orders and their linking status
- Viewing order details with line items and claims
- Resending claim emails
- Manually linking passes
- Cancelling claims
"""

import logging
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, url_for
from flask_login import login_required, current_user
from sqlalchemy import desc, or_, func, distinct
from sqlalchemy.orm import joinedload

from app.core import db
from app.models import (
    PubLeagueOrder, PubLeagueOrderLineItem, PubLeagueOrderClaim,
    PubLeagueOrderStatus, PubLeagueLineItemStatus, PubLeagueClaimStatus,
    Player, User
)
from app.decorators import role_required
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

pub_league_orders_admin_bp = Blueprint('pub_league_orders_admin', __name__, url_prefix='/admin-panel')


@pub_league_orders_admin_bp.route('/pub-league-orders')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def orders_list():
    """Display list of all Pub League orders with filtering and pagination."""
    try:
        # Get filter parameters
        status_filter = request.args.get('status', 'all')
        search = request.args.get('search', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = 25

        # Subquery for divisions - aggregates distinct divisions per order
        # Use string_agg for PostgreSQL (group_concat is MySQL)
        division_subq = (
            db.session.query(
                PubLeagueOrderLineItem.order_id,
                func.string_agg(distinct(PubLeagueOrderLineItem.division), ',').label('divisions')
            )
            .group_by(PubLeagueOrderLineItem.order_id)
            .subquery()
        )

        # Base query with eager loading and division subquery
        # Note: line_items uses lazy='dynamic' so we can't use joinedload on it
        query = db.session.query(
            PubLeagueOrder,
            division_subq.c.divisions
        ).options(
            joinedload(PubLeagueOrder.primary_user)
        ).outerjoin(
            division_subq,
            PubLeagueOrder.id == division_subq.c.order_id
        )

        # Apply status filter
        if status_filter != 'all':
            query = query.filter(PubLeagueOrder.status == status_filter)

        # Apply search filter
        if search:
            search_term = f'%{search}%'
            query = query.filter(
                or_(
                    PubLeagueOrder.customer_name.ilike(search_term),
                    PubLeagueOrder.customer_email.ilike(search_term),
                    PubLeagueOrder.woo_order_id.cast(db.String).ilike(search_term)
                )
            )

        # Order by created_at descending
        query = query.order_by(desc(PubLeagueOrder.created_at))

        # Paginate - need to handle the tuple results
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        # Convert tuples to objects with divisions attribute
        class OrderWithDivisions:
            def __init__(self, order, divisions):
                self._order = order
                self.divisions = divisions

            def __getattr__(self, name):
                return getattr(self._order, name)

        orders_with_divisions = [OrderWithDivisions(order, divisions) for order, divisions in pagination.items]

        # Create a custom pagination-like object
        class PaginationWrapper:
            def __init__(self, items, pagination):
                self.items = items
                self.page = pagination.page
                self.pages = pagination.pages
                self.has_prev = pagination.has_prev
                self.has_next = pagination.has_next
                self.prev_num = pagination.prev_num
                self.next_num = pagination.next_num
                self.total = pagination.total

            def iter_pages(self, **kwargs):
                return pagination.iter_pages(**kwargs)

        orders = PaginationWrapper(orders_with_divisions, pagination)

        # Calculate statistics
        stats = {
            'total': db.session.query(PubLeagueOrder).count(),
            'not_started': db.session.query(PubLeagueOrder).filter_by(
                status=PubLeagueOrderStatus.NOT_STARTED.value
            ).count(),
            'pending': db.session.query(PubLeagueOrder).filter_by(
                status=PubLeagueOrderStatus.PENDING.value
            ).count(),
            'partial': db.session.query(PubLeagueOrder).filter_by(
                status=PubLeagueOrderStatus.PARTIALLY_LINKED.value
            ).count(),
            'fully_linked': db.session.query(PubLeagueOrder).filter_by(
                status=PubLeagueOrderStatus.FULLY_LINKED.value
            ).count(),
            'cancelled': db.session.query(PubLeagueOrder).filter_by(
                status=PubLeagueOrderStatus.CANCELLED.value
            ).count(),
        }

        # Get user roles for template
        user_roles = [role.name for role in safe_current_user.roles] if safe_current_user.is_authenticated else []

        # Get product URL settings
        from app.models.admin_config import AdminConfig
        premier_product_slug = AdminConfig.get_setting('pub_league_premier_product_slug', '')
        classic_product_slug = AdminConfig.get_setting('pub_league_classic_product_slug', '')

        return render_template(
            'admin/pub_league_orders_flowbite.html',
            title='Pub League Orders',
            orders=orders,
            stats=stats,
            status_filter=status_filter,
            search=search,
            user_roles=user_roles,
            PubLeagueOrderStatus=PubLeagueOrderStatus,
            premier_product_slug=premier_product_slug,
            classic_product_slug=classic_product_slug,
            now=datetime.utcnow()
        )

    except Exception as e:
        logger.error(f"Error loading pub league orders: {e}", exc_info=True)
        return render_template(
            'admin/pub_league_orders_flowbite.html',
            title='Pub League Orders',
            orders=None,
            stats={},
            error=str(e),
            user_roles=[],
            now=datetime.utcnow()
        )


@pub_league_orders_admin_bp.route('/pub-league-orders/<int:order_id>')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def order_detail(order_id):
    """Display detailed view of a specific Pub League order."""
    try:
        # Note: line_items uses lazy='dynamic' so we query it separately
        order = db.session.query(PubLeagueOrder).options(
            joinedload(PubLeagueOrder.primary_user)
        ).filter_by(id=order_id).first_or_404()

        # Eager load line items with their relationships
        # Since line_items is dynamic, we need to query them separately
        line_items = order.line_items.options(
            joinedload(PubLeagueOrderLineItem.assigned_player),
            joinedload(PubLeagueOrderLineItem.assigned_user),
            joinedload(PubLeagueOrderLineItem.wallet_pass)
        ).all()

        # Get all claims for this order
        claims = db.session.query(PubLeagueOrderClaim).options(
            joinedload(PubLeagueOrderClaim.line_item),
            joinedload(PubLeagueOrderClaim.created_by),
            joinedload(PubLeagueOrderClaim.claimed_by_player),
            joinedload(PubLeagueOrderClaim.claimed_by_user)
        ).filter_by(order_id=order_id).order_by(desc(PubLeagueOrderClaim.created_at)).all()

        # Get user roles for template
        user_roles = [role.name for role in safe_current_user.roles] if safe_current_user.is_authenticated else []

        return render_template(
            'admin/pub_league_order_detail_flowbite.html',
            title=f'Order #{order.woo_order_id}',
            order=order,
            line_items=line_items,
            claims=claims,
            user_roles=user_roles,
            PubLeagueOrderStatus=PubLeagueOrderStatus,
            PubLeagueLineItemStatus=PubLeagueLineItemStatus,
            PubLeagueClaimStatus=PubLeagueClaimStatus
        )

    except Exception as e:
        logger.error(f"Error loading pub league order {order_id}: {e}", exc_info=True)
        from flask import redirect, flash
        flash('Failed to load order details.', 'error')
        return redirect(url_for('pub_league_orders_admin.orders_list'))


@pub_league_orders_admin_bp.route('/pub-league-orders/api/search-players')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_search_players():
    """Search for players to manually assign passes to."""
    query = request.args.get('q', '').strip()
    suggest_for = request.args.get('suggest_for', '').strip()

    def _format_player(player):
        """Format a player for JSON response."""
        user = player.user
        return {
            'player_id': player.id,
            'user_id': user.id if user else None,
            'name': player.name,
            'discord_username': player.discord_username,
            'email_hint': _mask_email(user.email) if user and hasattr(user, 'email') and user.email else None,
            'is_current_player': player.is_current_player,
        }

    # Suggestion mode: search by customer name parts
    if suggest_for and len(query) < 2:
        try:
            name_parts = suggest_for.split()
            conditions = []
            for part in name_parts:
                if len(part) >= 2:
                    conditions.append(Player.name.ilike(f'%{part}%'))

            if conditions:
                players = db.session.query(Player).options(
                    joinedload(Player.user)
                ).filter(or_(*conditions)).limit(10).all()

                # Score by name part matches
                results = []
                for player in players:
                    player_lower = player.name.lower()
                    match_count = sum(1 for part in name_parts if part.lower() in player_lower)
                    results.append((player, match_count))
                results.sort(key=lambda x: x[1], reverse=True)

                return jsonify({
                    'success': True,
                    'players': [_format_player(p) for p, _ in results[:5]],
                    'is_suggestion': True,
                    'suggested_for': suggest_for
                })

            return jsonify({'success': True, 'players': [], 'is_suggestion': True})

        except Exception as e:
            logger.error(f"Error in suggestion search: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    # Normal search mode
    if len(query) < 2:
        return jsonify({'success': True, 'players': []})

    try:
        search_term = f'%{query}%'
        players = db.session.query(Player).options(
            joinedload(Player.user)
        ).filter(
            or_(
                Player.name.ilike(search_term),
                Player.discord_username.ilike(search_term)
            )
        ).limit(10).all()

        results = [_format_player(player) for player in players]

        return jsonify({'success': True, 'players': results})

    except Exception as e:
        logger.error(f"Error searching players: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/manual-link', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_manual_link():
    """Manually link a pass to a player."""
    data = request.get_json() or {}
    line_item_id = data.get('line_item_id')
    player_id = data.get('player_id')

    if not line_item_id or not player_id:
        return jsonify({'success': False, 'error': 'Missing line_item_id or player_id'}), 400

    try:
        line_item = db.session.query(PubLeagueOrderLineItem).options(
            joinedload(PubLeagueOrderLineItem.order)
        ).filter_by(id=line_item_id).first()

        if not line_item:
            return jsonify({'success': False, 'error': 'Line item not found'}), 404

        if line_item.status != PubLeagueLineItemStatus.UNASSIGNED.value:
            return jsonify({'success': False, 'error': 'Pass is already assigned'}), 400

        player = db.session.query(Player).options(
            joinedload(Player.user)
        ).filter_by(id=player_id).first()

        if not player:
            return jsonify({'success': False, 'error': 'Player not found'}), 404

        # Import services
        from app.pub_league.services import PubLeagueOrderService, PlayerActivationService

        # Link the pass
        user = player.user if player.user_id else None
        PubLeagueOrderService.link_pass_to_player(line_item, player, user)

        # Activate player for the division
        if user:
            PlayerActivationService.activate_player_for_league(
                player=player,
                user=user,
                division=line_item.division,
                jersey_size=line_item.jersey_size
            )

        logger.info(f"Admin {current_user.id} manually linked line item {line_item_id} to player {player_id}")

        return jsonify({
            'success': True,
            'message': f'Pass linked to {player.name}',
            'line_item': line_item.to_dict()
        })

    except Exception as e:
        logger.error(f"Error manually linking pass: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/resend-claim', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_resend_claim():
    """Resend claim email to recipient."""
    data = request.get_json() or {}
    claim_id = data.get('claim_id')

    if not claim_id:
        return jsonify({'success': False, 'error': 'Missing claim_id'}), 400

    try:
        claim = db.session.query(PubLeagueOrderClaim).options(
            joinedload(PubLeagueOrderClaim.line_item),
            joinedload(PubLeagueOrderClaim.order)
        ).filter_by(id=claim_id).first()

        if not claim:
            return jsonify({'success': False, 'error': 'Claim not found'}), 404

        if not claim.recipient_email:
            return jsonify({'success': False, 'error': 'No recipient email on claim'}), 400

        if claim.status != PubLeagueClaimStatus.PENDING.value:
            return jsonify({'success': False, 'error': 'Claim is not pending'}), 400

        # Send claim email
        from app.pub_league.email_helpers import send_claim_link_email
        line_item = claim.line_item
        order = claim.order

        email_sent = send_claim_link_email(
            recipient_email=claim.recipient_email,
            recipient_name=claim.recipient_name,
            claim_token=claim.claim_token,
            division=line_item.division if line_item else 'Pub League',
            sender_name=order.customer_name if order else 'ECS Pub League',
            expires_at=claim.expires_at
        )

        if email_sent:
            claim.email_sent_at = datetime.utcnow()
            db.session.commit()
            logger.info(f"Admin {current_user.id} resent claim email for claim {claim_id}")
            return jsonify({'success': True, 'message': 'Claim email sent'})
        else:
            return jsonify({'success': False, 'error': 'Failed to send email'}), 500

    except Exception as e:
        logger.error(f"Error resending claim email: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/cancel-claim', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_cancel_claim():
    """Cancel a pending claim."""
    data = request.get_json() or {}
    claim_id = data.get('claim_id')

    if not claim_id:
        return jsonify({'success': False, 'error': 'Missing claim_id'}), 400

    try:
        claim = db.session.query(PubLeagueOrderClaim).options(
            joinedload(PubLeagueOrderClaim.line_item)
        ).filter_by(id=claim_id).first()

        if not claim:
            return jsonify({'success': False, 'error': 'Claim not found'}), 404

        if claim.status != PubLeagueClaimStatus.PENDING.value:
            return jsonify({'success': False, 'error': 'Claim is not pending'}), 400

        # Cancel the claim
        claim.status = PubLeagueClaimStatus.CANCELLED.value

        # Unlink from line item if needed
        if claim.line_item:
            claim.line_item.claim_id = None

        db.session.commit()
        logger.info(f"Admin {current_user.id} cancelled claim {claim_id}")

        return jsonify({'success': True, 'message': 'Claim cancelled'})

    except Exception as e:
        logger.error(f"Error cancelling claim: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/refresh-order', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_refresh_order():
    """Refresh order data from WooCommerce."""
    data = request.get_json() or {}
    order_id = data.get('order_id')

    if not order_id:
        return jsonify({'success': False, 'error': 'Missing order_id'}), 400

    try:
        order = db.session.query(PubLeagueOrder).filter_by(id=order_id).first()

        if not order:
            return jsonify({'success': False, 'error': 'Order not found'}), 404

        # Fetch fresh data from WooCommerce
        from app.pub_league.services import PubLeagueOrderService
        order_data = PubLeagueOrderService.fetch_order_from_woocommerce(order.woo_order_id)

        if not order_data:
            return jsonify({'success': False, 'error': 'Could not fetch order from WooCommerce'}), 500

        # Update cached data
        order.woo_order_data = order_data

        # Update customer info if changed
        billing = order_data.get('billing', {})
        new_name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
        new_email = billing.get('email', '')

        if new_name:
            order.customer_name = new_name
        if new_email:
            order.customer_email = new_email

        order.updated_at = datetime.utcnow()
        db.session.commit()

        logger.info(f"Admin {current_user.id} refreshed order {order_id} from WooCommerce")

        return jsonify({
            'success': True,
            'message': 'Order data refreshed from WooCommerce',
            'order': order.to_dict()
        })

    except Exception as e:
        logger.error(f"Error refreshing order: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/delete-order', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_delete_order():
    """Delete an entire Pub League order and all its line items and claims."""
    data = request.get_json() or {}
    order_id = data.get('order_id')

    if not order_id:
        return jsonify({'success': False, 'error': 'Missing order_id'}), 400

    try:
        order = db.session.query(PubLeagueOrder).filter_by(id=order_id).first()

        if not order:
            return jsonify({'success': False, 'error': 'Order not found'}), 404

        woo_order_id = order.woo_order_id

        # Delete all claims for this order
        db.session.query(PubLeagueOrderClaim).filter_by(order_id=order_id).delete()

        # Delete all line items for this order
        db.session.query(PubLeagueOrderLineItem).filter_by(order_id=order_id).delete()

        # Delete the order itself
        db.session.delete(order)
        db.session.commit()

        logger.info(f"Admin {current_user.id} deleted pub league order {order_id} (WooCommerce #{woo_order_id})")

        return jsonify({
            'success': True,
            'message': f'Order #{woo_order_id} deleted successfully'
        })

    except Exception as e:
        logger.error(f"Error deleting order: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/unassign-pass', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_unassign_pass():
    """Unassign a pass from a player (make it available again)."""
    data = request.get_json() or {}
    line_item_id = data.get('line_item_id')

    if not line_item_id:
        return jsonify({'success': False, 'error': 'Missing line_item_id'}), 400

    try:
        line_item = db.session.query(PubLeagueOrderLineItem).options(
            joinedload(PubLeagueOrderLineItem.order),
            joinedload(PubLeagueOrderLineItem.assigned_player)
        ).filter_by(id=line_item_id).first()

        if not line_item:
            return jsonify({'success': False, 'error': 'Line item not found'}), 404

        if line_item.status == PubLeagueLineItemStatus.UNASSIGNED.value:
            return jsonify({'success': False, 'error': 'Pass is already unassigned'}), 400

        old_player_name = line_item.assigned_player.name if line_item.assigned_player else 'Unknown'

        # Clear assignment
        line_item.assigned_player_id = None
        line_item.assigned_user_id = None
        line_item.assigned_at = None
        line_item.status = PubLeagueLineItemStatus.UNASSIGNED.value

        # Update order linked count
        order = line_item.order
        if order:
            order.linked_passes = max(0, order.linked_passes - 1)
            order.update_status()

        db.session.commit()

        logger.info(f"Admin {current_user.id} unassigned line item {line_item_id} (was assigned to {old_player_name})")

        return jsonify({
            'success': True,
            'message': f'Pass unassigned from {old_player_name}'
        })

    except Exception as e:
        logger.error(f"Error unassigning pass: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@pub_league_orders_admin_bp.route('/pub-league-orders/api/update-line-item', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def api_update_line_item():
    """Update a line item's division or jersey size."""
    data = request.get_json() or {}
    line_item_id = data.get('line_item_id')
    division = data.get('division')
    jersey_size = data.get('jersey_size')

    if not line_item_id:
        return jsonify({'success': False, 'error': 'Missing line_item_id'}), 400

    try:
        line_item = db.session.query(PubLeagueOrderLineItem).filter_by(id=line_item_id).first()

        if not line_item:
            return jsonify({'success': False, 'error': 'Line item not found'}), 404

        changes = []

        if division is not None and division != line_item.division:
            if division not in ['Classic', 'Premier', '']:
                return jsonify({'success': False, 'error': 'Invalid division'}), 400
            old_division = line_item.division
            line_item.division = division if division else None
            changes.append(f"division: {old_division} → {division or 'None'}")

        if jersey_size is not None and jersey_size != line_item.jersey_size:
            old_size = line_item.jersey_size
            line_item.jersey_size = jersey_size if jersey_size else None
            changes.append(f"size: {old_size} → {jersey_size or 'None'}")

        if not changes:
            return jsonify({'success': True, 'message': 'No changes made'})

        db.session.commit()

        logger.info(f"Admin {current_user.id} updated line item {line_item_id}: {', '.join(changes)}")

        return jsonify({
            'success': True,
            'message': f'Updated: {", ".join(changes)}'
        })

    except Exception as e:
        logger.error(f"Error updating line item: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


def _mask_email(email: str) -> str:
    """Mask an email for display (e.g., j***@example.com)."""
    if not email or '@' not in email:
        return None

    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked_local = local[0] + '*'
    else:
        masked_local = local[0] + '*' * (len(local) - 2) + local[-1]

    return f"{masked_local}@{domain}"
