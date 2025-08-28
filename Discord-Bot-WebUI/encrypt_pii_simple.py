#!/usr/bin/env python
"""Simple PII encryption using Fernet directly."""

from cryptography.fernet import Fernet
import os
import base64
import hashlib
import hmac
from app import create_app
from app.core import db

def get_or_create_key():
    """Get or create encryption key."""
    secret = os.environ.get('SECRET_KEY', 'dev-key-change-in-prod')
    # Create a proper Fernet key from the secret
    key_bytes = hashlib.sha256(secret.encode()).digest()[:32]
    return base64.urlsafe_b64encode(key_bytes)

def encrypt_value(value, fernet):
    """Encrypt a string value."""
    if not value:
        return None
    return fernet.encrypt(value.encode()).decode()

def create_hash(value, key):
    """Create searchable hash."""
    if not value:
        return None
    return hmac.new(key, value.lower().encode(), hashlib.sha256).hexdigest()

def main():
    app = create_app()
    with app.app_context():
        # Get encryption key
        key = get_or_create_key()
        fernet = Fernet(key)
        
        print("Starting PII encryption...")
        
        # Direct SQL approach to avoid SQLAlchemy type issues
        from sqlalchemy import text
        
        # Encrypt user emails
        print("Encrypting user emails...")
        result = db.session.execute(text("SELECT id, email FROM users WHERE email IS NOT NULL"))
        users = result.fetchall()
        
        print(f"Found {len(users)} users with emails")
        
        for user_id, email in users:
            if email:
                encrypted = encrypt_value(email, fernet)
                email_hash = create_hash(email, key)
                
                db.session.execute(
                    text("UPDATE users SET encrypted_email = :encrypted, email_hash = :hash WHERE id = :id"),
                    {"encrypted": encrypted, "hash": email_hash, "id": user_id}
                )
        
        db.session.commit()
        print("✅ User emails encrypted")
        
        # Encrypt player phones
        print("Encrypting player phones...")
        result = db.session.execute(text("SELECT id, phone FROM player WHERE phone IS NOT NULL AND phone != ''"))
        players = result.fetchall()
        
        print(f"Found {len(players)} players with phones")
        
        for player_id, phone in players:
            if phone:
                encrypted = encrypt_value(phone, fernet)
                phone_hash = create_hash(phone, key)
                
                db.session.execute(
                    text("UPDATE player SET encrypted_phone = :encrypted, phone_hash = :hash WHERE id = :id"),
                    {"encrypted": encrypted, "hash": phone_hash, "id": player_id}
                )
        
        db.session.commit()
        print("✅ Player phones encrypted")
        
        print("🎉 Encryption complete!")
        
        # Verify it worked
        result = db.session.execute(text("""
            SELECT COUNT(*) as total,
                   COUNT(encrypted_email) as encrypted 
            FROM users 
            WHERE email IS NOT NULL
        """))
        row = result.fetchone()
        print(f"Users: {row.encrypted}/{row.total} encrypted")
        
        result = db.session.execute(text("""
            SELECT COUNT(*) as total,
                   COUNT(encrypted_phone) as encrypted 
            FROM player 
            WHERE phone IS NOT NULL AND phone != ''
        """))
        row = result.fetchone()
        print(f"Players: {row.encrypted}/{row.total} encrypted")

if __name__ == '__main__':
    main()