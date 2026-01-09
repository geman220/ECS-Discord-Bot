# app/store.py

"""
Store Module

This module handles the mock store functionality for league merchandise.
It includes endpoints for managing store items (admin only) and placing orders (coaches).
The store is a simple mock system that tracks orders but doesn't process payments.
"""

import logging
import json
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, g
from flask_login import login_required
from sqlalchemy.orm import selectinload

from app.models import StoreItem, StoreOrder, User, Season
from app.alert_helpers import show_success, show_error, show_warning, show_info
from app.decorators import role_required
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

# Create the blueprint for store management
store_bp = Blueprint('store', __name__, url_prefix='/store')


@store_bp.route('/', endpoint='index', methods=['GET'])
@login_required
@role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def store_index():
    """
    Display the store front page with available items for coaches to order.
    Only accessible by coaches and admins.
    """
    session = g.db_session
    
    try:
        # Get current pub league season
        current_season = session.query(Season).filter_by(
            league_type='Pub League',
            is_current=True
        ).first()
        
        # Check if user has already ordered this season
        has_ordered_this_season = False
        current_season_order = None
        if current_season:
            current_season_order = session.query(StoreOrder).options(
                selectinload(StoreOrder.item)
            ).filter_by(
                ordered_by=safe_current_user.id,
                season_id=current_season.id
            ).first()
            has_ordered_this_season = current_season_order is not None
        
        # Get all active store items
        items = session.query(StoreItem).filter(
            StoreItem.is_active == True
        ).order_by(StoreItem.category, StoreItem.name).all()
        
        # Get user's recent orders
        recent_orders = session.query(StoreOrder).options(
            selectinload(StoreOrder.item),
            selectinload(StoreOrder.season)
        ).filter(
            StoreOrder.ordered_by == safe_current_user.id
        ).order_by(StoreOrder.order_date.desc()).limit(5).all()
        
        return render_template(
            'store/index_flowbite.html',
            title='League Store',
            items=items,
            recent_orders=recent_orders,
            current_season=current_season,
            has_ordered_this_season=has_ordered_this_season,
            current_season_order=current_season_order
        )
        
    except Exception as e:
        logger.exception(f"Error loading store: {str(e)}")
        show_error('Error loading store items.')
        return redirect(url_for('main.index'))


@store_bp.route('/admin', endpoint='admin', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def store_admin():
    """
    Display the store administration page for managing items and orders.
    Only accessible by admins.
    """
    session = g.db_session
    
    try:
        # Get all store items
        items = session.query(StoreItem).options(
            selectinload(StoreItem.creator)
        ).order_by(StoreItem.created_at.desc()).all()
        
        # Get all orders
        orders = session.query(StoreOrder).options(
            selectinload(StoreOrder.item),
            selectinload(StoreOrder.orderer),
            selectinload(StoreOrder.processor)
        ).order_by(StoreOrder.order_date.desc()).all()
        
        return render_template(
            'store/admin_flowbite.html',
            title='Store Administration',
            items=items,
            orders=orders
        )
        
    except Exception as e:
        logger.exception(f"Error loading store admin: {str(e)}")
        show_error('Error loading store administration.')
        return redirect(url_for('store.index'))


@store_bp.route('/admin/item/create', endpoint='create_item', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def create_item():
    """
    Create a new store item via AJAX modal.
    """
    session = g.db_session
    
    try:
        # Get form data
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        image_url = request.form.get('image_url', '').strip()
        category = request.form.get('category', '').strip()
        price_str = request.form.get('price', '').strip()
        
        # Get colors and sizes as arrays
        colors = [c.strip() for c in request.form.getlist('colors[]') if c.strip()]
        sizes = [s.strip() for s in request.form.getlist('sizes[]') if s.strip()]
        
        # Validate required fields
        if not name:
            return jsonify({'success': False, 'message': 'Item name is required.'})
        
        # Parse price
        price = None
        if price_str:
            try:
                price = float(price_str)
            except ValueError:
                return jsonify({'success': False, 'message': 'Invalid price format.'})
        
        # Handle file upload
        uploaded_file = request.files.get('image_file')
        if uploaded_file and uploaded_file.filename:
            # TODO: Implement file upload handling
            # For now, just use the URL field
            pass
        
        # Create new item
        item = StoreItem(
            name=name,
            description=description if description else None,
            image_url=image_url if image_url else None,
            category=category if category else None,
            price=price,
            available_colors=json.dumps(colors) if colors else None,
            available_sizes=json.dumps(sizes) if sizes else None,
            created_by=safe_current_user.id
        )
        
        session.add(item)
        session.commit()
        
        logger.info(f"Store item '{name}' created by user {safe_current_user.id}")
        return jsonify({
            'success': True,
            'message': f"Item '{name}' created successfully."
        })
        
    except Exception as e:
        session.rollback()
        logger.exception(f"Error creating store item: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error creating store item.'
        })


@store_bp.route('/admin/item/<int:item_id>/edit', endpoint='edit_item', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_item(item_id):
    """
    Edit an existing store item.
    """
    session = g.db_session
    item = session.query(StoreItem).get(item_id)
    
    if not item:
        show_error('Store item not found.')
        return redirect(url_for('store.admin'))
    
    if request.method == 'POST':
        try:
            # Get form data
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            image_url = request.form.get('image_url', '').strip()
            category = request.form.get('category', '').strip()
            price_str = request.form.get('price', '').strip()
            is_active = 'is_active' in request.form
            
            # Get colors and sizes as arrays
            colors = [c.strip() for c in request.form.getlist('colors[]') if c.strip()]
            sizes = [s.strip() for s in request.form.getlist('sizes[]') if s.strip()]
            
            # Parse price
            price = None
            if price_str:
                try:
                    price = float(price_str)
                except ValueError:
                    show_error('Invalid price format.')
                    return redirect(url_for('store.edit_item', item_id=item_id))
            
            # Validate required fields
            if not name:
                show_error('Item name is required.')
                return redirect(url_for('store.edit_item', item_id=item_id))
            
            # Update item
            item.name = name
            item.description = description if description else None
            item.image_url = image_url if image_url else None
            item.category = category if category else None
            item.price = price
            item.available_colors = json.dumps(colors) if colors else None
            item.available_sizes = json.dumps(sizes) if sizes else None
            item.is_active = is_active
            item.updated_at = datetime.utcnow()
            
            session.add(item)
            session.commit()
            
            logger.info(f"Store item '{name}' updated by user {safe_current_user.id}")
            show_success(f"Item '{name}' updated successfully.")
            return redirect(url_for('store.admin'))
            
        except Exception as e:
            session.rollback()
            logger.exception(f"Error updating store item: {str(e)}")
            show_error('Error updating store item.')
            return redirect(url_for('store.edit_item', item_id=item_id))
    
    return render_template(
        'store/edit_item_flowbite.html',
        title='Edit Store Item',
        item=item
    )


@store_bp.route('/admin/item/<int:item_id>/delete', endpoint='delete_item', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_item(item_id):
    """
    Delete a store item.
    """
    session = g.db_session
    item = session.query(StoreItem).get(item_id)
    
    if not item:
        return jsonify({'success': False, 'message': 'Store item not found.'})
    
    try:
        item_name = item.name
        session.delete(item)
        session.commit()
        
        logger.info(f"Store item '{item_name}' deleted by user {safe_current_user.id}")
        return jsonify({
            'success': True,
            'message': f"Item '{item_name}' deleted successfully."
        })
        
    except Exception as e:
        session.rollback()
        logger.exception(f"Error deleting store item: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error deleting store item.'
        })


@store_bp.route('/order/<int:item_id>', endpoint='place_order', methods=['POST'])
@login_required
@role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def place_order(item_id):
    """
    Place an order for a store item.
    """
    session = g.db_session
    item = session.query(StoreItem).get(item_id)
    
    if not item:
        return jsonify({'success': False, 'message': 'Store item not found.'})
    
    if not item.is_active:
        return jsonify({'success': False, 'message': 'This item is no longer available.'})
    
    try:
        # Get current pub league season
        current_season = session.query(Season).filter_by(
            league_type='Pub League',
            is_current=True
        ).first()
        
        if not current_season:
            return jsonify({'success': False, 'message': 'No current season found. Cannot place order.'})
        
        # Check if user already has an order for this season (coaches can only order once per season)
        existing_order = session.query(StoreOrder).filter_by(
            ordered_by=safe_current_user.id,
            season_id=current_season.id
        ).first()
        
        if existing_order:
            return jsonify({
                'success': False, 
                'message': f'You have already placed an order this season ({current_season.name}). Only one order per season is allowed.'
            })
        
        # Get order details from form
        quantity = int(request.form.get('quantity', 1))
        selected_color = request.form.get('color', '').strip()
        selected_size = request.form.get('size', '').strip()
        notes = request.form.get('notes', '').strip()
        
        # Validate quantity
        if quantity < 1:
            return jsonify({'success': False, 'message': 'Quantity must be at least 1.'})
        
        # Validate color and size selection (both are now required)
        if not selected_color:
            return jsonify({'success': False, 'message': 'Color selection is required.'})
        
        if not selected_size:
            return jsonify({'success': False, 'message': 'Size selection is required.'})
        
        # Create order
        order = StoreOrder(
            item_id=item_id,
            ordered_by=safe_current_user.id,
            quantity=quantity,
            selected_color=selected_color if selected_color else None,
            selected_size=selected_size if selected_size else None,
            notes=notes if notes else None,
            season_id=current_season.id
        )
        
        session.add(order)
        session.commit()
        
        logger.info(f"Order placed for item '{item.name}' by user {safe_current_user.id}")
        return jsonify({
            'success': True,
            'message': f"Order placed successfully for {quantity}x {item.name}."
        })
        
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid quantity specified.'})
    except Exception as e:
        session.rollback()
        logger.exception(f"Error placing order: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error placing order.'
        })


@store_bp.route('/admin/order/<int:order_id>/update', endpoint='update_order', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_order(order_id):
    """
    Update the status of an order.
    """
    session = g.db_session
    order = session.query(StoreOrder).get(order_id)
    
    if not order:
        return jsonify({'success': False, 'message': 'Order not found.'})
    
    try:
        new_status = request.form.get('status', '').strip().upper()
        valid_statuses = ['PENDING', 'PROCESSING', 'ORDERED', 'DELIVERED', 'CANCELLED']
        
        if new_status not in valid_statuses:
            return jsonify({'success': False, 'message': 'Invalid status.'})
        
        old_status = order.status
        order.status = new_status
        order.processed_by = safe_current_user.id
        
        # Update timestamps
        if new_status == 'PROCESSING' and old_status == 'PENDING':
            order.processed_date = datetime.utcnow()
        elif new_status == 'DELIVERED' and old_status in ['PROCESSING', 'ORDERED']:
            order.delivered_date = datetime.utcnow()
        
        session.add(order)
        session.commit()
        
        logger.info(f"Order {order_id} status updated from {old_status} to {new_status} by user {safe_current_user.id}")
        return jsonify({
            'success': True,
            'message': f"Order status updated to {new_status}."
        })
        
    except Exception as e:
        session.rollback()
        logger.exception(f"Error updating order: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error updating order.'
        })


@store_bp.route('/my-orders', endpoint='my_orders', methods=['GET'])
@login_required
@role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def my_orders():
    """
    Display the user's order history.
    """
    session = g.db_session
    
    try:
        orders = session.query(StoreOrder).options(
            selectinload(StoreOrder.item),
            selectinload(StoreOrder.processor)
        ).filter(
            StoreOrder.ordered_by == safe_current_user.id
        ).order_by(StoreOrder.order_date.desc()).all()
        
        return render_template(
            'store/my_orders_flowbite.html',
            title='My Orders',
            orders=orders
        )
        
    except Exception as e:
        logger.exception(f"Error loading user orders: {str(e)}")
        show_error('Error loading your orders.')
        return redirect(url_for('store.index'))


@store_bp.route('/admin/orders/bulk-update', endpoint='bulk_update_orders', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def bulk_update_orders():
    """
    Bulk update the status of multiple orders.
    """
    session = g.db_session
    
    try:
        # Get JSON data from request
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided.'})
        
        order_ids = data.get('order_ids', [])
        new_status = data.get('status', '').strip().upper()
        
        # Validate input
        if not order_ids:
            return jsonify({'success': False, 'message': 'No orders selected.'})
        
        valid_statuses = ['PENDING', 'PROCESSING', 'ORDERED', 'DELIVERED', 'CANCELLED']
        if new_status not in valid_statuses:
            return jsonify({'success': False, 'message': 'Invalid status provided.'})
        
        # Get all orders to update
        orders = session.query(StoreOrder).filter(
            StoreOrder.id.in_(order_ids)
        ).all()
        
        if not orders:
            return jsonify({'success': False, 'message': 'No valid orders found.'})
        
        # Update all orders
        updated_count = 0
        for order in orders:
            old_status = order.status
            order.status = new_status
            order.processed_by = safe_current_user.id
            
            # Update timestamps based on new status
            if new_status == 'PROCESSING' and old_status == 'PENDING':
                order.processed_date = datetime.utcnow()
            elif new_status == 'DELIVERED' and old_status in ['PROCESSING', 'ORDERED']:
                order.delivered_date = datetime.utcnow()
            
            session.add(order)
            updated_count += 1
        
        session.commit()
        
        logger.info(f"Bulk updated {updated_count} orders to {new_status} by user {safe_current_user.id}")
        return jsonify({
            'success': True,
            'message': f"Successfully updated {updated_count} orders to {new_status}."
        })
        
    except Exception as e:
        session.rollback()
        logger.exception(f"Error bulk updating orders: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error updating orders.'
        })


@store_bp.route('/admin/reset-season-ordering', endpoint='reset_season_ordering', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def reset_season_ordering():
    """
    Reset ordering eligibility for the current season.
    """
    session = g.db_session
    
    try:
        # Get JSON data from request
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided.'})
        
        reset_type = data.get('reset_type', '').strip()
        
        # Validate input
        if reset_type not in ['all', 'eligibility']:
            return jsonify({'success': False, 'message': 'Invalid reset type.'})
        
        # Get current pub league season
        current_season = session.query(Season).filter_by(
            league_type='Pub League',
            is_current=True
        ).first()
        
        if not current_season:
            return jsonify({'success': False, 'message': 'No current season found.'})
        
        if reset_type == 'all':
            # Delete all orders for the current season
            orders_to_delete = session.query(StoreOrder).filter_by(
                season_id=current_season.id
            ).all()
            
            deleted_count = len(orders_to_delete)
            
            for order in orders_to_delete:
                session.delete(order)
            
            session.commit()
            
            logger.info(f"Deleted {deleted_count} orders for season {current_season.name} by user {safe_current_user.id}")
            return jsonify({
                'success': True,
                'message': f"Successfully deleted {deleted_count} orders for {current_season.name}. All coaches can now place new orders."
            })
        
        elif reset_type == 'eligibility':
            # For now, we'll implement this by creating a simple flag system
            # In a more complex system, you might want a separate table to track eligibility
            # For simplicity, we'll just remove the season_id from existing orders to "hide" them from eligibility checks
            # This allows keeping the order history while allowing new orders
            
            # This approach modifies existing orders to remove season association temporarily
            # A better approach would be to add an "eligibility_reset" table or flag
            
            orders_to_modify = session.query(StoreOrder).filter_by(
                season_id=current_season.id
            ).all()
            
            modified_count = len(orders_to_modify)
            
            # For this implementation, we'll add a note to existing orders and allow new ones
            # In practice, you might want a more sophisticated approach
            for order in orders_to_modify:
                if order.notes:
                    order.notes += f" [ELIGIBILITY RESET: {datetime.utcnow().strftime('%Y-%m-%d')}]"
                else:
                    order.notes = f"[ELIGIBILITY RESET: {datetime.utcnow().strftime('%Y-%m-%d')}]"
                # Remove season association temporarily to allow new orders
                order.season_id = None
                session.add(order)
            
            session.commit()
            
            logger.info(f"Reset eligibility for {modified_count} orders in season {current_season.name} by user {safe_current_user.id}")
            return jsonify({
                'success': True,
                'message': f"Successfully reset ordering eligibility for {current_season.name}. Coaches can now place additional orders while keeping order history."
            })
        
    except Exception as e:
        session.rollback()
        logger.exception(f"Error resetting season ordering: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error resetting season ordering.'
        })


@store_bp.route('/admin/order/<int:order_id>/delete', endpoint='delete_order', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_order(order_id):
    """
    Delete a single order.
    """
    session = g.db_session
    order = session.query(StoreOrder).get(order_id)
    
    if not order:
        return jsonify({'success': False, 'message': 'Order not found.'})
    
    try:
        order_info = f"Order #{order.id} for {order.item.name if order.item else 'Unknown Item'}"
        customer_name = order.orderer.username if order.orderer else 'Unknown Customer'
        
        session.delete(order)
        session.commit()
        
        logger.info(f"Order {order_id} deleted by user {safe_current_user.id}")
        return jsonify({
            'success': True,
            'message': f"Successfully deleted {order_info} from {customer_name}."
        })
        
    except Exception as e:
        session.rollback()
        logger.exception(f"Error deleting order {order_id}: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error deleting order.'
        })


@store_bp.route('/admin/orders/bulk-delete', endpoint='bulk_delete_orders', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def bulk_delete_orders():
    """
    Bulk delete multiple orders.
    """
    session = g.db_session
    
    try:
        # Get JSON data from request
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided.'})
        
        order_ids = data.get('order_ids', [])
        
        # Validate input
        if not order_ids:
            return jsonify({'success': False, 'message': 'No orders selected.'})
        
        # Get all orders to delete
        orders = session.query(StoreOrder).filter(
            StoreOrder.id.in_(order_ids)
        ).all()
        
        if not orders:
            return jsonify({'success': False, 'message': 'No valid orders found.'})
        
        # Delete all orders
        deleted_count = 0
        for order in orders:
            session.delete(order)
            deleted_count += 1
        
        session.commit()
        
        logger.info(f"Bulk deleted {deleted_count} orders by user {safe_current_user.id}")
        return jsonify({
            'success': True,
            'message': f"Successfully deleted {deleted_count} orders."
        })
        
    except Exception as e:
        session.rollback()
        logger.exception(f"Error bulk deleting orders: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error deleting orders.'
        })