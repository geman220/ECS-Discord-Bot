"""
Pub League Order Admin Routes

Admin routes for managing Pub League WooCommerce orders, including:
- Viewing all orders and their linking status
- Viewing order details with line items and claims
- Resending claim emails
- Manually linking passes
- Cancelling claims
"""

import io
import logging
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, url_for, send_file, abort
from flask_login import login_required, current_user
from sqlalchemy import desc, or_, and_, func, distinct
from sqlalchemy.orm import joinedload

from app.core import db
from app.models import (
    PubLeagueOrder, PubLeagueOrderLineItem, PubLeagueOrderClaim,
    PubLeagueOrderStatus, PubLeagueLineItemStatus, PubLeagueClaimStatus,
    Player, User, Season
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

        # Season scope — default to the CURRENT Pub League season so the list is
        # not clogged with last season's orders. This "ties to rollover": whichever
        # season is is_current becomes the default view automatically, no config.
        # 'all' shows every season; a numeric id shows one specific season.
        current_season = db.session.query(Season).filter_by(
            league_type='Pub League', is_current=True
        ).first()
        season_filter = request.args.get('season', 'current')
        is_current_view = False
        if season_filter == 'all':
            selected_season_id = None
        elif season_filter == 'current':
            selected_season_id = current_season.id if current_season else None
            is_current_view = True
        else:
            try:
                selected_season_id = int(season_filter)
                is_current_view = bool(current_season and selected_season_id == current_season.id)
            except (TypeError, ValueError):
                selected_season_id = current_season.id if current_season else None
                season_filter = 'current'
                is_current_view = True

        # Season scope condition, reused for both the list and the stat counts.
        # The current view also surfaces orphan/unmatched orders (season_id IS NULL)
        # that need admin attention; a specific past season shows only that season.
        season_condition = None
        if season_filter != 'all' and selected_season_id is not None:
            if is_current_view:
                # Current view = orders in the current season, PLUS genuine
                # orphans that need attention. An orphan is a NULL season_id
                # with no season_name (truly unmatched) or a name that IS the
                # current season. We must NOT sweep in legacy orders that carry
                # a PAST season_name (e.g. "2024 Spring") but never had their
                # season_id backfilled — those were flooding the current view.
                orphan_names = [PubLeagueOrder.season_name.is_(None), PubLeagueOrder.season_name == '']
                if current_season and current_season.name:
                    orphan_names.append(PubLeagueOrder.season_name == current_season.name)
                season_condition = or_(
                    PubLeagueOrder.season_id == selected_season_id,
                    and_(
                        PubLeagueOrder.season_id.is_(None),
                        or_(*orphan_names)
                    )
                )
            else:
                season_condition = PubLeagueOrder.season_id == selected_season_id

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

        # Apply season scope
        if season_condition is not None:
            query = query.filter(season_condition)

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

        # Statistics — scoped to the SELECTED season so the counts match the list.
        def _order_count(status=None):
            q = db.session.query(func.count(PubLeagueOrder.id))
            if season_condition is not None:
                q = q.filter(season_condition)
            if status is not None:
                q = q.filter(PubLeagueOrder.status == status)
            return q.scalar() or 0

        stats = {
            'total': _order_count(),
            'not_started': _order_count(PubLeagueOrderStatus.NOT_STARTED.value),
            'pending': _order_count(PubLeagueOrderStatus.PENDING.value),
            'partial': _order_count(PubLeagueOrderStatus.PARTIALLY_LINKED.value),
            'fully_linked': _order_count(PubLeagueOrderStatus.FULLY_LINKED.value),
            'cancelled': _order_count(PubLeagueOrderStatus.CANCELLED.value),
        }

        # Season options for the filter dropdown — only seasons that actually
        # have orders, newest first.
        season_options = [
            {'id': sid, 'name': sname or f'Season {sid}'}
            for sid, sname in db.session.query(
                PubLeagueOrder.season_id, PubLeagueOrder.season_name
            ).filter(PubLeagueOrder.season_id.isnot(None)).distinct().all()
        ]
        season_options.sort(key=lambda s: s['id'], reverse=True)

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
            season_filter=season_filter,
            selected_season_id=selected_season_id,
            season_options=season_options,
            current_season=current_season,
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
            season_filter='current',
            selected_season_id=None,
            season_options=[],
            current_season=None,
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

        # Real jersey sizes actually in use — same source as the player profile
        # form and the link-order wizard, so the edit dropdown here can't drift
        # from a hardcoded XS/SM/… list that doesn't match reality. Fold in any
        # size already on this order's line items so it stays selectable even if
        # no existing player currently uses it.
        jersey_size_choices = sorted({
            r[0] for r in db.session.query(Player.jersey_size).distinct().all() if r[0]
        } | {li.jersey_size for li in line_items if li.jersey_size})

        return render_template(
            'admin/pub_league_order_detail_flowbite.html',
            title=f'Order #{order.woo_order_id}',
            order=order,
            line_items=line_items,
            claims=claims,
            user_roles=user_roles,
            jersey_size_choices=jersey_size_choices,
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
            return jsonify({'success': False, 'error': 'Internal Server Error'}), 500

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
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


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

        player = db.session.query(Player).options(
            joinedload(Player.user)
        ).filter_by(id=player_id).first()

        if not player:
            return jsonify({'success': False, 'error': 'Player not found'}), 404

        # Reassignment: if this pass is already assigned to someone else, clear
        # the previous holder first. assign_to_player() below increments the
        # order's linked_passes and flips status to assigned, so we mustn't let
        # it double-count — an already-assigned pass keeps the same slot.
        was_assigned = line_item.status != PubLeagueLineItemStatus.UNASSIGNED.value
        previous_name = line_item.assigned_player.name if line_item.assigned_player else None
        if was_assigned and line_item.assigned_player_id == player.id:
            return jsonify({'success': False, 'error': 'Pass is already assigned to this player'}), 400
        if was_assigned:
            # Return it to unassigned WITHOUT touching linked_passes (assign
            # re-increments), and drop the old wallet pass so the new holder gets
            # a fresh one rather than the previous holder's.
            line_item.assigned_player_id = None
            line_item.assigned_user_id = None
            line_item.assigned_at = None
            line_item.wallet_pass_id = None
            line_item.pass_created_at = None
            line_item.status = PubLeagueLineItemStatus.UNASSIGNED.value
            if line_item.order:
                line_item.order.linked_passes = max(0, line_item.order.linked_passes - 1)
            db.session.flush()

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

        verb = 'reassigned' if was_assigned else 'linked'
        logger.info(
            f"Admin {current_user.id} {verb} line item {line_item_id} to player {player_id}"
            + (f" (was {previous_name})" if previous_name else "")
        )

        msg = (f'Pass reassigned from {previous_name} to {player.name}'
               if was_assigned and previous_name else f'Pass linked to {player.name}')
        return jsonify({
            'success': True,
            'message': msg,
            'line_item': line_item.to_dict()
        })

    except Exception as e:
        logger.error(f"Error manually linking pass: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


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
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


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
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


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
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


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
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


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

        # Clear assignment AND the generated wallet pass. Clearing the pass link
        # matters: generate-pass short-circuits on a non-null wallet_pass_id and
        # returns the OLD pass, so without this a re-linked line item would never
        # mint a fresh pass — it'd hand back the previous holder's. This returns
        # the line item to a truly clean unassigned state (the right behaviour for
        # both a real reassignment and re-testing the flow).
        line_item.assigned_player_id = None
        line_item.assigned_user_id = None
        line_item.assigned_at = None
        line_item.wallet_pass_id = None
        line_item.pass_created_at = None
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
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


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
        return jsonify({'success': False, 'error': 'Internal Server Error'}), 500


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


# ============================================================================
# Pre-season party QR codes
# ============================================================================
#
# Passes sell out in about an hour, and first access is earned by showing up to
# the pre-season party. These render the QR you put on the wall / on the table
# at the party. Scanning it opens the app for anyone who has it (and the browser
# for anyone who doesn't), then drops them straight into WooCommerce's own
# checkout — which is where the presale password gate and the card form live.
#
# There is deliberately NO "buy a pass" button inside the app: access to the
# purchase is the thing being rationed, so the QR (and later the public on-sale
# link) is the only way in.

def _buy_url(division: str = None) -> str:
    """
    The Universal Link a QR encodes.

    Deliberately carries NO season and NO product id — only (optionally) the
    division. Everything else is resolved at scan time from whichever Pub League
    season is is_current. That means ONE printed QR survives every rollover:
    scan it this season and it lands on the 2026-fall product, scan the same
    code next season and it lands on 2027-spring.

    src=app is always included: it's a no-op in a browser, and in the app it's
    what makes WooCommerce's post-payment redirect bounce the buyer back into
    the app instead of stranding them in the browser sheet.
    """
    kwargs = {'src': 'app', '_external': True}
    if division:
        kwargs['division'] = division
    return url_for('pub_league.buy', **kwargs)


@pub_league_orders_admin_bp.route('/pub-league-orders/qr.png')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def buy_qr_png():
    """
    PNG QR for the buy link.

    No ?division= -> the ONE code for the party: it lands on the division picker.
    ?division=classic|premier -> a code that skips straight to that division,
    for when you want a separate sign at each table.
    """
    import qrcode

    division = (request.args.get('division') or '').lower() or None
    if division and division not in ('classic', 'premier'):
        abort(404)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(_buy_url(division))
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


@pub_league_orders_admin_bp.route('/pub-league-orders/qr')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def buy_qr_print():
    """Printable QR sheet for the pre-season party."""
    from app.pub_league.services import ProductUrlService

    season_name = ProductUrlService.get_current_season_name()
    options = ProductUrlService.get_buy_options(season_name)

    # Per-division codes, for anyone who wants a sign at each table instead of
    # (or as well as) the single picker code.
    divisions = [
        {
            'name': option['name'],
            'slug': option['division'],
            'buy_url': _buy_url(option['division']),
            # Surfaced so an admin sees at a glance whether the product slug
            # actually resolves. A missing one means the QR dead-ends, and the
            # party is the worst possible place to discover that.
            'product_url': option['product_url'],
            # A hardcoded slug pins the link to ONE product and will NOT follow
            # the next rollover — the whole point of the QR is that it does.
            'slug_override': option['slug_override'],
            'qr_png': url_for('pub_league_orders_admin.buy_qr_png', division=option['division']),
        }
        for option in options
    ]

    return render_template(
        'admin/pub_league_buy_qr.html',
        season_name=season_name,
        divisions=divisions,
        picker_qr_png=url_for('pub_league_orders_admin.buy_qr_png'),
        picker_url=_buy_url(),
        any_available=any(d['product_url'] for d in divisions),
    )
