# app/admin_panel/routes/store_management.py

"""
Admin Panel Store Management Routes

This module contains routes for managing the store system:
- Store item management (CRUD)
- Order processing and tracking
- Store analytics and reporting
- Category management
"""

import logging
import json
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, desc, and_, or_

from .. import admin_panel_bp
from app.core import db
from app.models.store import StoreItem, StoreOrder
from app.models.core import User, Season
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required

# Set up the module logger
logger = logging.getLogger(__name__)


@admin_panel_bp.route('/store')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def store_management():
    """Store management hub page."""
    try:
        # Get store statistics
        total_items = StoreItem.query.count()
        active_items = StoreItem.query.filter_by(is_active=True).count()
        total_orders = StoreOrder.query.count()
        pending_orders = StoreOrder.query.filter_by(status='PENDING').count()
        processing_orders = StoreOrder.query.filter_by(status='PROCESSING').count()
        
        # Recent orders (last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_orders = StoreOrder.query.filter(
            StoreOrder.order_date >= week_ago
        ).count()
        
        # Order status breakdown
        order_status_breakdown = db.session.query(
            StoreOrder.status,
            func.count(StoreOrder.id).label('count')
        ).group_by(StoreOrder.status).all()
        
        # Popular items (by order count)
        popular_items = db.session.query(
            StoreItem.name,
            func.count(StoreOrder.id).label('order_count')
        ).join(StoreOrder).group_by(StoreItem.id, StoreItem.name)\
         .order_by(desc('order_count')).limit(5).all()
        
        # Recent activity
        recent_activity = []
        
        # Recent orders
        latest_orders = StoreOrder.query.order_by(desc(StoreOrder.order_date)).limit(5).all()
        for order in latest_orders:
            recent_activity.append({
                'type': 'order',
                'timestamp': order.order_date,
                'description': f"New order for {order.item.name if order.item else 'Unknown Item'} by {order.orderer.username if order.orderer else 'Unknown User'}",
                'status': order.status
            })
        
        # Recent item updates
        latest_items = StoreItem.query.order_by(desc(StoreItem.updated_at)).limit(3).all()
        for item in latest_items:
            recent_activity.append({
                'type': 'item_update',
                'timestamp': item.updated_at,
                'description': f"Item '{item.name}' was updated",
                'status': 'active' if item.is_active else 'inactive'
            })
        
        # Sort by timestamp
        recent_activity.sort(key=lambda x: x['timestamp'], reverse=True)
        recent_activity = recent_activity[:10]
        
        stats = {
            'total_items': total_items,
            'active_items': active_items,
            'inactive_items': total_items - active_items,
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'processing_orders': processing_orders,
            'recent_orders': recent_orders,
            'order_status_breakdown': dict(order_status_breakdown),
            'popular_items': [{'name': name, 'count': count} for name, count in popular_items]
        }
        
        return render_template('admin_panel/store/management.html',
                             stats=stats,
                             recent_activity=recent_activity)
    except Exception as e:
        logger.error(f"Error loading store management: {e}")
        flash('Store management unavailable. Check database connectivity and store models.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/store/items')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def store_items():
    """Store items management page."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        # Build query with filters
        query = StoreItem.query
        
        # Category filter
        category = request.args.get('category')
        if category and category != 'all':
            query = query.filter(StoreItem.category == category)
        
        # Status filter
        status = request.args.get('status')
        if status == 'active':
            query = query.filter(StoreItem.is_active == True)
        elif status == 'inactive':
            query = query.filter(StoreItem.is_active == False)
        
        # Search filter
        search = request.args.get('search', '').strip()
        if search:
            query = query.filter(or_(
                StoreItem.name.ilike(f'%{search}%'),
                StoreItem.description.ilike(f'%{search}%'),
                StoreItem.category.ilike(f'%{search}%')
            ))
        
        # Order by
        order_by = request.args.get('order_by', 'name')
        if order_by == 'name':
            query = query.order_by(StoreItem.name)
        elif order_by == 'created_at':
            query = query.order_by(desc(StoreItem.created_at))
        elif order_by == 'updated_at':
            query = query.order_by(desc(StoreItem.updated_at))
        elif order_by == 'category':
            query = query.order_by(StoreItem.category, StoreItem.name)
        
        items = query.paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Get all categories for filter dropdown
        categories = db.session.query(StoreItem.category).filter(
            StoreItem.category.isnot(None)
        ).distinct().all()
        categories = [cat[0] for cat in categories if cat[0]]
        
        return render_template('admin_panel/store/items.html',
                             items=items,
                             categories=categories,
                             current_filters={
                                 'category': category or 'all',
                                 'status': status or 'all',
                                 'search': search,
                                 'order_by': order_by
                             })
    except Exception as e:
        logger.error(f"Error loading store items: {e}")
        flash('Store items data unavailable. Verify database connection and item models.', 'error')
        return redirect(url_for('admin_panel.store_management'))


@admin_panel_bp.route('/store/items/create', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def create_store_item():
    """Create new store item."""
    if request.method == 'POST':
        try:
            # Get form data
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            image_url = request.form.get('image_url', '').strip()
            category = request.form.get('category', '').strip()
            price = request.form.get('price', '').strip()
            
            # Get colors and sizes
            colors = []
            sizes = []
            for key, value in request.form.items():
                if key.startswith('color_') and value.strip():
                    colors.append(value.strip())
                elif key.startswith('size_') and value.strip():
                    sizes.append(value.strip())
            
            # Validation
            if not name:
                flash('Item name is required.', 'error')
                return render_template('admin_panel/store/item_form.html', 
                                     action='create', item=None)
            
            # Check for duplicate name
            if StoreItem.query.filter_by(name=name).first():
                flash('An item with this name already exists.', 'error')
                return render_template('admin_panel/store/item_form.html', 
                                     action='create', item=None)
            
            # Create item
            item = StoreItem(
                name=name,
                description=description or None,
                image_url=image_url or None,
                category=category or None,
                price=float(price) if price else None,
                available_colors=json.dumps(colors) if colors else None,
                available_sizes=json.dumps(sizes) if sizes else None,
                created_by=current_user.id,
                is_active=True
            )
            
            db.session.add(item)
            db.session.commit()
            
            # Log the action
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='create_store_item',
                resource_type='store',
                resource_id=str(item.id),
                new_value=f"Created store item: {item.name}",
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            flash(f'Store item "{item.name}" created successfully.', 'success')
            return redirect(url_for('admin_panel.store_items'))
            
        except ValueError as e:
            flash('Invalid price format.', 'error')
            return render_template('admin_panel/store/item_form.html', 
                                 action='create', item=None)
        except Exception as e:
            logger.error(f"Error creating store item: {e}")
            db.session.rollback()
            flash('Store item creation failed. Check database connectivity and input validation.', 'error')
            return render_template('admin_panel/store/item_form.html', 
                                 action='create', item=None)
    
    # GET request - show form
    return render_template('admin_panel/store/item_form.html', 
                         action='create', item=None)


@admin_panel_bp.route('/store/items/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def edit_store_item(item_id):
    """Edit store item."""
    item = StoreItem.query.get_or_404(item_id)
    
    if request.method == 'POST':
        try:
            # Store old values for audit log
            old_values = {
                'name': item.name,
                'description': item.description,
                'category': item.category,
                'is_active': item.is_active
            }
            
            # Update item
            item.name = request.form.get('name', '').strip()
            item.description = request.form.get('description', '').strip() or None
            item.image_url = request.form.get('image_url', '').strip() or None
            item.category = request.form.get('category', '').strip() or None
            price = request.form.get('price', '').strip()
            item.price = float(price) if price else None
            item.is_active = 'is_active' in request.form
            
            # Get colors and sizes
            colors = []
            sizes = []
            for key, value in request.form.items():
                if key.startswith('color_') and value.strip():
                    colors.append(value.strip())
                elif key.startswith('size_') and value.strip():
                    sizes.append(value.strip())
            
            item.available_colors = json.dumps(colors) if colors else None
            item.available_sizes = json.dumps(sizes) if sizes else None
            item.updated_at = datetime.utcnow()
            
            # Validation
            if not item.name:
                flash('Item name is required.', 'error')
                return render_template('admin_panel/store/item_form.html', 
                                     action='edit', item=item)
            
            # Check for duplicate name (excluding current item)
            duplicate = StoreItem.query.filter(
                and_(StoreItem.name == item.name, StoreItem.id != item.id)
            ).first()
            if duplicate:
                flash('An item with this name already exists.', 'error')
                return render_template('admin_panel/store/item_form.html', 
                                     action='edit', item=item)
            
            db.session.commit()
            
            # Log the action
            changes = []
            for key, old_value in old_values.items():
                new_value = getattr(item, key)
                if old_value != new_value:
                    changes.append(f"{key}: '{old_value}' → '{new_value}'")
            
            if changes:
                AdminAuditLog.log_action(
                    user_id=current_user.id,
                    action='update_store_item',
                    resource_type='store',
                    resource_id=str(item.id),
                    old_value=str(old_values),
                    new_value=f"Updated: {'; '.join(changes)}",
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get('User-Agent')
                )
            
            flash(f'Store item "{item.name}" updated successfully.', 'success')
            return redirect(url_for('admin_panel.store_items'))
            
        except ValueError as e:
            flash('Invalid price format.', 'error')
            return render_template('admin_panel/store/item_form.html', 
                                 action='edit', item=item)
        except Exception as e:
            logger.error(f"Error updating store item: {e}")
            db.session.rollback()
            flash('Store item update failed. Check database connectivity and permissions.', 'error')
            return render_template('admin_panel/store/item_form.html', 
                                 action='edit', item=item)
    
    # GET request - show form
    return render_template('admin_panel/store/item_form.html', 
                         action='edit', item=item)


@admin_panel_bp.route('/store/items/<int:item_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin'])
def delete_store_item(item_id):
    """Delete store item."""
    try:
        item = StoreItem.query.get_or_404(item_id)
        
        # Check if item has orders
        order_count = StoreOrder.query.filter_by(item_id=item.id).count()
        if order_count > 0:
            flash(f'Cannot delete item "{item.name}" - it has {order_count} associated orders. Consider deactivating instead.', 'error')
            return redirect(url_for('admin_panel.store_items'))
        
        item_name = item.name
        
        # Log the action before deletion
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='delete_store_item',
            resource_type='store',
            resource_id=str(item.id),
            old_value=f"Deleted store item: {item_name}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        db.session.delete(item)
        db.session.commit()
        
        flash(f'Store item "{item_name}" deleted successfully.', 'success')
        
    except Exception as e:
        logger.error(f"Error deleting store item: {e}")
        db.session.rollback()
        flash('Store item deletion failed. Check database connectivity and item constraints.', 'error')
    
    return redirect(url_for('admin_panel.store_items'))


@admin_panel_bp.route('/store/orders')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def store_orders():
    """Store orders management page."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        # Build query with filters
        query = StoreOrder.query.join(StoreItem).join(User, StoreOrder.ordered_by == User.id)
        
        # Status filter
        status = request.args.get('status')
        if status and status != 'all':
            query = query.filter(StoreOrder.status == status)
        
        # Date range filter
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        if date_from:
            try:
                from_date = datetime.strptime(date_from, '%Y-%m-%d')
                query = query.filter(StoreOrder.order_date >= from_date)
            except ValueError:
                pass
        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%Y-%m-%d')
                # Add one day to include the entire day
                to_date = to_date.replace(hour=23, minute=59, second=59)
                query = query.filter(StoreOrder.order_date <= to_date)
            except ValueError:
                pass
        
        # Search filter
        search = request.args.get('search', '').strip()
        if search:
            query = query.filter(or_(
                StoreItem.name.ilike(f'%{search}%'),
                User.username.ilike(f'%{search}%'),
                StoreOrder.selected_color.ilike(f'%{search}%'),
                StoreOrder.selected_size.ilike(f'%{search}%')
            ))
        
        # Order by
        order_by = request.args.get('order_by', 'order_date_desc')
        if order_by == 'order_date_desc':
            query = query.order_by(desc(StoreOrder.order_date))
        elif order_by == 'order_date_asc':
            query = query.order_by(StoreOrder.order_date)
        elif order_by == 'status':
            query = query.order_by(StoreOrder.status, desc(StoreOrder.order_date))
        elif order_by == 'item_name':
            query = query.order_by(StoreItem.name, desc(StoreOrder.order_date))
        elif order_by == 'orderer':
            query = query.order_by(User.username, desc(StoreOrder.order_date))
        
        orders = query.paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Get order statuses for filter dropdown
        order_statuses = ['PENDING', 'PROCESSING', 'ORDERED', 'DELIVERED', 'CANCELLED']
        
        return render_template('admin_panel/store/orders.html',
                             orders=orders,
                             order_statuses=order_statuses,
                             current_filters={
                                 'status': status or 'all',
                                 'date_from': date_from or '',
                                 'date_to': date_to or '',
                                 'search': search,
                                 'order_by': order_by
                             })
    except Exception as e:
        logger.error(f"Error loading store orders: {e}")
        flash('Store orders data unavailable. Verify database connection and order models.', 'error')
        return redirect(url_for('admin_panel.store_management'))


@admin_panel_bp.route('/store/orders/<int:order_id>/update-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def update_order_status(order_id):
    """Update order status."""
    try:
        order = StoreOrder.query.get_or_404(order_id)
        new_status = request.form.get('status')
        
        if new_status not in ['PENDING', 'PROCESSING', 'ORDERED', 'DELIVERED', 'CANCELLED']:
            flash('Invalid status.', 'error')
            return redirect(url_for('admin_panel.store_orders'))
        
        old_status = order.status
        order.status = new_status
        
        # Update timestamps based on status
        if new_status == 'PROCESSING' and old_status == 'PENDING':
            order.processed_date = datetime.utcnow()
            order.processed_by = current_user.id
        elif new_status == 'DELIVERED':
            order.delivered_date = datetime.utcnow()
            if not order.processed_by:
                order.processed_by = current_user.id
        
        db.session.commit()
        
        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='update_order_status',
            resource_type='store',
            resource_id=str(order.id),
            old_value=old_status,
            new_value=new_status,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        flash(f'Order status updated from {old_status} to {new_status}.', 'success')
        
    except Exception as e:
        logger.error(f"Error updating order status: {e}")
        db.session.rollback()
        flash('Order status update failed. Check database connectivity and permissions.', 'error')
    
    return redirect(url_for('admin_panel.store_orders'))


@admin_panel_bp.route('/store/orders/<int:order_id>/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def order_details(order_id):
    """Get order details via AJAX."""
    try:
        order = StoreOrder.query.get_or_404(order_id)
        
        details = {
            'id': order.id,
            'item_name': order.item.name if order.item else 'Unknown Item',
            'item_image': order.item.image_url if order.item else None,
            'orderer_name': order.orderer.username if order.orderer else 'Unknown User',
            'quantity': order.quantity,
            'selected_color': order.selected_color,
            'selected_size': order.selected_size,
            'notes': order.notes,
            'status': order.status,
            'order_date': order.order_date.strftime('%Y-%m-%d %H:%M:%S') if order.order_date else None,
            'processed_date': order.processed_date.strftime('%Y-%m-%d %H:%M:%S') if order.processed_date else None,
            'delivered_date': order.delivered_date.strftime('%Y-%m-%d %H:%M:%S') if order.delivered_date else None,
            'processor_name': order.processor.username if order.processor else None,
            'season_name': order.season.name if order.season else None
        }
        
        return jsonify({'success': True, 'order': details})
        
    except Exception as e:
        logger.error(f"Error getting order details: {e}")
        return jsonify({'success': False, 'message': 'Error retrieving order details'}), 500


@admin_panel_bp.route('/store/analytics')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def store_analytics():
    """Store analytics and reporting page."""
    try:
        # Date range for analysis (default: last 30 days)
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        
        # Custom date range from parameters
        custom_start = request.args.get('start_date')
        custom_end = request.args.get('end_date')
        if custom_start:
            try:
                start_date = datetime.strptime(custom_start, '%Y-%m-%d')
            except ValueError:
                pass
        if custom_end:
            try:
                end_date = datetime.strptime(custom_end, '%Y-%m-%d')
                end_date = end_date.replace(hour=23, minute=59, second=59)
            except ValueError:
                pass
        
        # Order statistics by status
        status_stats = db.session.query(
            StoreOrder.status,
            func.count(StoreOrder.id).label('count')
        ).filter(
            StoreOrder.order_date.between(start_date, end_date)
        ).group_by(StoreOrder.status).all()
        
        # Popular items
        popular_items = db.session.query(
            StoreItem.name,
            func.count(StoreOrder.id).label('total_orders'),
            func.sum(StoreOrder.quantity).label('total_quantity')
        ).join(StoreOrder).filter(
            StoreOrder.order_date.between(start_date, end_date)
        ).group_by(StoreItem.id, StoreItem.name)\
         .order_by(desc('total_orders')).limit(10).all()
        
        # Orders by day (for chart)
        daily_orders = db.session.query(
            func.date(StoreOrder.order_date).label('date'),
            func.count(StoreOrder.id).label('count')
        ).filter(
            StoreOrder.order_date.between(start_date, end_date)
        ).group_by(func.date(StoreOrder.order_date))\
         .order_by('date').all()
        
        # Category analysis
        category_stats = db.session.query(
            StoreItem.category,
            func.count(StoreOrder.id).label('order_count'),
            func.sum(StoreOrder.quantity).label('quantity_sum')
        ).join(StoreOrder).filter(
            and_(
                StoreOrder.order_date.between(start_date, end_date),
                StoreItem.category.isnot(None)
            )
        ).group_by(StoreItem.category).all()
        
        # Top customers
        top_customers = db.session.query(
            User.username,
            func.count(StoreOrder.id).label('order_count'),
            func.sum(StoreOrder.quantity).label('total_items')
        ).join(StoreOrder).filter(
            StoreOrder.order_date.between(start_date, end_date)
        ).group_by(User.id, User.username)\
         .order_by(desc('order_count')).limit(10).all()
        
        analytics_data = {
            'date_range': {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': end_date.strftime('%Y-%m-%d')
            },
            'status_stats': dict(status_stats),
            'popular_items': [
                {
                    'name': name,
                    'orders': total_orders,
                    'quantity': total_quantity
                }
                for name, total_orders, total_quantity in popular_items
            ],
            'daily_orders': [
                {
                    'date': date.strftime('%Y-%m-%d'),
                    'count': count
                }
                for date, count in daily_orders
            ],
            'category_stats': [
                {
                    'category': category or 'Uncategorized',
                    'orders': order_count,
                    'quantity': quantity_sum
                }
                for category, order_count, quantity_sum in category_stats
            ],
            'top_customers': [
                {
                    'username': username,
                    'orders': order_count,
                    'items': total_items
                }
                for username, order_count, total_items in top_customers
            ]
        }
        
        return render_template('admin_panel/store/analytics.html',
                             analytics=analytics_data)
        
    except Exception as e:
        logger.error(f"Error loading store analytics: {e}")
        flash('Store analytics unavailable. Verify database connection and analytics data.', 'error')
        return redirect(url_for('admin_panel.store_management'))


# API Endpoints for AJAX operations

@admin_panel_bp.route('/api/store/items', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def store_items_api():
    """Manage store items via API."""
    if request.method == 'GET':
        try:
            items = StoreItem.query.filter_by(is_active=True).all()
            return jsonify([{
                'id': item.id,
                'name': item.name,
                'description': item.description,
                'price': float(item.price) if item.price else 0,
                'category': item.category,
                'stock_quantity': getattr(item, 'stock_quantity', 0),
                'available_colors': json.loads(item.available_colors) if item.available_colors else [],
                'available_sizes': json.loads(item.available_sizes) if item.available_sizes else [],
                'created_at': item.created_at.isoformat()
            } for item in items])
        except Exception as e:
            logger.error(f"Error getting store items: {e}")
            return jsonify({'error': 'Failed to get store items'}), 500
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            
            item = StoreItem(
                name=data['name'],
                description=data.get('description', ''),
                price=data.get('price', 0),
                category=data.get('category', ''),
                available_colors=json.dumps(data.get('colors', [])),
                available_sizes=json.dumps(data.get('sizes', [])),
                created_by=current_user.id
            )
            
            db.session.add(item)
            db.session.commit()
            
            # Log item creation
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='create_store_item',
                resource_type='store',
                resource_id=str(item.id),
                new_value=f"Created store item: {item.name}",
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            return jsonify({
                'success': True,
                'message': f'Item "{item.name}" created successfully',
                'item_id': item.id
            })
            
        except Exception as e:
            logger.error(f"Error creating store item: {e}")
            db.session.rollback()
            return jsonify({
                'success': False,
                'message': 'Failed to create item'
            }), 500


@admin_panel_bp.route('/api/store/orders')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def store_orders_api():
    """Get store orders with filtering."""
    try:
        status_filter = request.args.get('status')
        query = StoreOrder.query.join(StoreItem).join(User, StoreOrder.ordered_by == User.id)
        
        if status_filter:
            query = query.filter(StoreOrder.status == status_filter)
            
        orders = query.order_by(StoreOrder.order_date.desc()).limit(50).all()
        
        return jsonify([{
            'id': order.id,
            'item_name': order.item.name,
            'orderer_name': order.orderer.username,
            'quantity': order.quantity,
            'selected_color': order.selected_color,
            'selected_size': order.selected_size,
            'status': order.status,
            'order_date': order.order_date.isoformat(),
            'notes': order.notes
        } for order in orders])
        
    except Exception as e:
        logger.error(f"Error getting store orders: {e}")
        return jsonify({'error': 'Failed to get orders'}), 500