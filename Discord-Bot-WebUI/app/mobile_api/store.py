# app/mobile_api/store.py

"""
Mobile API Store Endpoints

Provides league store functionality for mobile clients:
- Browse store items
- Place orders
- View order history
- Check ordering eligibility
"""

import json
import logging
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import selectinload

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required
from app.core.session_manager import managed_session
from app.models import User, StoreItem, StoreOrder, Season

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/store/items', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def get_store_items():
    """
    Get all active store items.

    Query Parameters:
        category: Filter by category (optional)

    Returns:
        JSON with list of store items
    """
    category = request.args.get('category', '').strip()

    with managed_session() as session:
        query = session.query(StoreItem).filter(StoreItem.is_active == True)

        if category:
            query = query.filter(StoreItem.category == category)

        query = query.order_by(StoreItem.category, StoreItem.name)
        items = query.all()

        items_data = []
        for item in items:
            # Parse JSON fields
            colors = []
            sizes = []
            try:
                if item.available_colors:
                    colors = json.loads(item.available_colors)
            except (json.JSONDecodeError, TypeError):
                pass
            try:
                if item.available_sizes:
                    sizes = json.loads(item.available_sizes)
            except (json.JSONDecodeError, TypeError):
                pass

            items_data.append({
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "image_url": item.image_url,
                "category": item.category,
                "price": float(item.price) if item.price else None,
                "available_colors": colors,
                "available_sizes": sizes,
                "is_active": item.is_active
            })

        # Get unique categories for filtering
        categories = list(set(item.category for item in items if item.category))

        return jsonify({
            "items": items_data,
            "categories": sorted(categories),
            "total": len(items_data)
        }), 200


@mobile_api_v2.route('/store/items/<int:item_id>', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def get_store_item(item_id: int):
    """
    Get details for a specific store item.

    Args:
        item_id: Store item ID

    Returns:
        JSON with item details
    """
    with managed_session() as session:
        item = session.query(StoreItem).get(item_id)

        if not item:
            return jsonify({"msg": "Store item not found"}), 404

        # Parse JSON fields
        colors = []
        sizes = []
        try:
            if item.available_colors:
                colors = json.loads(item.available_colors)
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            if item.available_sizes:
                sizes = json.loads(item.available_sizes)
        except (json.JSONDecodeError, TypeError):
            pass

        return jsonify({
            "item": {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "image_url": item.image_url,
                "category": item.category,
                "price": float(item.price) if item.price else None,
                "available_colors": colors,
                "available_sizes": sizes,
                "is_active": item.is_active
            }
        }), 200


@mobile_api_v2.route('/store/eligibility', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def check_store_eligibility():
    """
    Check if the current user is eligible to place an order this season.

    Returns:
        JSON with eligibility status and current season info
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Get current pub league season
        current_season = session.query(Season).filter_by(
            league_type='Pub League',
            is_current=True
        ).first()

        if not current_season:
            return jsonify({
                "eligible": False,
                "reason": "No current season found",
                "season": None
            }), 200

        # Check if user has already ordered this season
        existing_order = session.query(StoreOrder).filter_by(
            ordered_by=current_user_id,
            season_id=current_season.id
        ).first()

        if existing_order:
            return jsonify({
                "eligible": False,
                "reason": f"You have already placed an order this season ({current_season.name}). Only one order per season is allowed.",
                "season": {
                    "id": current_season.id,
                    "name": current_season.name
                },
                "existing_order": {
                    "id": existing_order.id,
                    "item_id": existing_order.item_id,
                    "status": existing_order.status,
                    "order_date": existing_order.order_date.isoformat() if existing_order.order_date else None
                }
            }), 200

        return jsonify({
            "eligible": True,
            "reason": None,
            "season": {
                "id": current_season.id,
                "name": current_season.name
            },
            "existing_order": None
        }), 200


@mobile_api_v2.route('/store/orders', methods=['POST'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def place_order():
    """
    Place an order for a store item.

    Expected JSON:
        item_id: ID of the store item to order
        quantity: Number of items (default: 1)
        color: Selected color (required if item has colors)
        size: Selected size (required if item has sizes)
        notes: Optional notes

    Returns:
        JSON with order confirmation
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    item_id = data.get('item_id')
    quantity = data.get('quantity', 1)
    color = data.get('color', '').strip()
    size = data.get('size', '').strip()
    notes = data.get('notes', '').strip()

    if not item_id:
        return jsonify({"msg": "item_id is required"}), 400

    try:
        quantity = int(quantity)
        if quantity < 1:
            return jsonify({"msg": "Quantity must be at least 1"}), 400
    except (ValueError, TypeError):
        return jsonify({"msg": "Invalid quantity"}), 400

    with managed_session() as session:
        # Get the item
        item = session.query(StoreItem).get(item_id)
        if not item:
            return jsonify({"msg": "Store item not found"}), 404

        if not item.is_active:
            return jsonify({"msg": "This item is no longer available"}), 400

        # Get current pub league season
        current_season = session.query(Season).filter_by(
            league_type='Pub League',
            is_current=True
        ).first()

        if not current_season:
            return jsonify({"msg": "No current season found. Cannot place order."}), 400

        # Check if user has already ordered this season
        existing_order = session.query(StoreOrder).filter_by(
            ordered_by=current_user_id,
            season_id=current_season.id
        ).first()

        if existing_order:
            return jsonify({
                "msg": f"You have already placed an order this season ({current_season.name}). Only one order per season is allowed."
            }), 400

        # Validate color selection if item has colors
        if item.available_colors:
            try:
                available_colors = json.loads(item.available_colors)
                if available_colors and not color:
                    return jsonify({"msg": "Color selection is required for this item"}), 400
                if color and color not in available_colors:
                    return jsonify({"msg": f"Invalid color. Available: {', '.join(available_colors)}"}), 400
            except (json.JSONDecodeError, TypeError):
                pass

        # Validate size selection if item has sizes
        if item.available_sizes:
            try:
                available_sizes = json.loads(item.available_sizes)
                if available_sizes and not size:
                    return jsonify({"msg": "Size selection is required for this item"}), 400
                if size and size not in available_sizes:
                    return jsonify({"msg": f"Invalid size. Available: {', '.join(available_sizes)}"}), 400
            except (json.JSONDecodeError, TypeError):
                pass

        # Create order
        order = StoreOrder(
            item_id=item_id,
            ordered_by=current_user_id,
            quantity=quantity,
            selected_color=color if color else None,
            selected_size=size if size else None,
            notes=notes if notes else None,
            season_id=current_season.id
        )

        session.add(order)
        session.commit()

        logger.info(f"Order placed for item '{item.name}' by user {current_user_id}")

        return jsonify({
            "success": True,
            "message": f"Order placed successfully for {quantity}x {item.name}",
            "order": {
                "id": order.id,
                "item_id": order.item_id,
                "item_name": item.name,
                "quantity": order.quantity,
                "color": order.selected_color,
                "size": order.selected_size,
                "status": order.status,
                "order_date": order.order_date.isoformat() if order.order_date else None
            }
        }), 201


@mobile_api_v2.route('/store/my-orders', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def get_my_orders():
    """
    Get the current user's order history.

    Returns:
        JSON with list of orders
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        orders = session.query(StoreOrder).options(
            selectinload(StoreOrder.item),
            selectinload(StoreOrder.season)
        ).filter(
            StoreOrder.ordered_by == current_user_id
        ).order_by(StoreOrder.order_date.desc()).all()

        orders_data = []
        for order in orders:
            orders_data.append({
                "id": order.id,
                "item": {
                    "id": order.item.id,
                    "name": order.item.name,
                    "image_url": order.item.image_url
                } if order.item else None,
                "quantity": order.quantity,
                "color": order.selected_color,
                "size": order.selected_size,
                "status": order.status,
                "notes": order.notes,
                "order_date": order.order_date.isoformat() if order.order_date else None,
                "processed_date": order.processed_date.isoformat() if order.processed_date else None,
                "delivered_date": order.delivered_date.isoformat() if order.delivered_date else None,
                "season": {
                    "id": order.season.id,
                    "name": order.season.name
                } if order.season else None
            })

        return jsonify({
            "orders": orders_data,
            "total": len(orders_data)
        }), 200


@mobile_api_v2.route('/store/orders/<int:order_id>', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def get_order_detail(order_id: int):
    """
    Get details for a specific order.

    Args:
        order_id: Order ID

    Returns:
        JSON with order details
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Get user to check role
        user = session.query(User).options(
            selectinload(User.roles)
        ).get(current_user_id)

        if not user:
            return jsonify({"msg": "User not found"}), 404

        user_roles = [role.name for role in user.roles]
        is_admin = any(r in ['Global Admin', 'Pub League Admin'] for r in user_roles)

        # Get order
        order = session.query(StoreOrder).options(
            selectinload(StoreOrder.item),
            selectinload(StoreOrder.season),
            selectinload(StoreOrder.orderer),
            selectinload(StoreOrder.processor)
        ).get(order_id)

        if not order:
            return jsonify({"msg": "Order not found"}), 404

        # Check authorization - user can only view their own orders unless admin
        if order.ordered_by != current_user_id and not is_admin:
            return jsonify({"msg": "Not authorized to view this order"}), 403

        return jsonify({
            "order": {
                "id": order.id,
                "item": {
                    "id": order.item.id,
                    "name": order.item.name,
                    "description": order.item.description,
                    "image_url": order.item.image_url,
                    "price": float(order.item.price) if order.item.price else None
                } if order.item else None,
                "quantity": order.quantity,
                "color": order.selected_color,
                "size": order.selected_size,
                "status": order.status,
                "notes": order.notes,
                "order_date": order.order_date.isoformat() if order.order_date else None,
                "processed_date": order.processed_date.isoformat() if order.processed_date else None,
                "delivered_date": order.delivered_date.isoformat() if order.delivered_date else None,
                "ordered_by": {
                    "id": order.orderer.id,
                    "username": order.orderer.username
                } if order.orderer else None,
                "processed_by": {
                    "id": order.processor.id,
                    "username": order.processor.username
                } if order.processor else None,
                "season": {
                    "id": order.season.id,
                    "name": order.season.name
                } if order.season else None
            }
        }), 200
