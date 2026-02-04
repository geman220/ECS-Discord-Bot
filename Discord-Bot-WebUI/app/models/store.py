# app/models/store.py

"""
Store Models Module

This module contains models related to the store system:
- StoreItem: Items available in the store
- StoreOrder: Orders placed in the store
"""

import logging
from datetime import datetime

from app.core import db

logger = logging.getLogger(__name__)


class StoreItem(db.Model):
    """Model representing an item available in the mock store."""
    __tablename__ = 'store_items'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    available_colors = db.Column(db.Text, nullable=True)  # JSON string of available colors
    available_sizes = db.Column(db.Text, nullable=True)   # JSON string of available sizes
    category = db.Column(db.String(100), nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=True)  # For admin tracking only
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Relationships
    creator = db.relationship('User', backref=db.backref('created_store_items', lazy='dynamic'))
    orders = db.relationship('StoreOrder', back_populates='item', cascade='all, delete-orphan')
    
    def to_dict(self):
        import json
        try:
            colors = json.loads(self.available_colors) if self.available_colors else []
        except:
            colors = []
        try:
            sizes = json.loads(self.available_sizes) if self.available_sizes else []
        except:
            sizes = []
            
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'image_url': self.image_url,
            'available_colors': colors,
            'available_sizes': sizes,
            'category': self.category,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<StoreItem {self.name}>'


class StoreOrder(db.Model):
    """Model representing an order placed in the mock store."""
    __tablename__ = 'store_orders'
    
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('store_items.id', ondelete='CASCADE'), nullable=False)
    ordered_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    selected_color = db.Column(db.String(100), nullable=True)
    selected_size = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='PENDING', nullable=False)  # PENDING, PROCESSING, ORDERED, DELIVERED, CANCELLED
    order_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed_date = db.Column(db.DateTime, nullable=True)
    delivered_date = db.Column(db.DateTime, nullable=True)
    processed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)  # Track which season this order is for
    
    # Relationships - passive_deletes=True trusts DB's ON DELETE CASCADE
    item = db.relationship('StoreItem', back_populates='orders', passive_deletes=True)
    orderer = db.relationship('User', foreign_keys=[ordered_by], backref=db.backref('store_orders', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    processor = db.relationship('User', foreign_keys=[processed_by], backref=db.backref('processed_orders', lazy='dynamic'))
    season = db.relationship('Season', backref=db.backref('store_orders', lazy='dynamic'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'item_id': self.item_id,
            'item_name': self.item.name if self.item else 'Unknown Item',
            'ordered_by': self.ordered_by,
            'orderer_name': self.orderer.username if self.orderer else 'Unknown User',
            'quantity': self.quantity,
            'selected_color': self.selected_color,
            'selected_size': self.selected_size,
            'notes': self.notes,
            'status': self.status,
            'order_date': self.order_date.isoformat() if self.order_date else None,
            'processed_date': self.processed_date.isoformat() if self.processed_date else None,
            'delivered_date': self.delivered_date.isoformat() if self.delivered_date else None
        }
    
    def __repr__(self):
        return f'<StoreOrder {self.id}: {self.item.name if self.item else "Unknown"} by {self.orderer.username if self.orderer else "Unknown"}>'