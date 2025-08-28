"""Simple PII encryption utilities for ongoing use."""

import os
import base64
import hashlib
import hmac
from cryptography.fernet import Fernet


def get_encryption_key():
    """Get or create encryption key."""
    secret = os.environ.get('SECRET_KEY', 'dev-key-change-in-prod')
    # Create a proper Fernet key from the secret
    key_bytes = hashlib.sha256(secret.encode()).digest()[:32]
    return base64.urlsafe_b64encode(key_bytes)


# Initialize Fernet once
_fernet = None

def get_fernet():
    """Get or create Fernet instance."""
    global _fernet
    if _fernet is None:
        _fernet = Fernet(get_encryption_key())
    return _fernet


def encrypt_value(value):
    """Encrypt a string value."""
    if not value:
        return None
    return get_fernet().encrypt(value.encode()).decode()


def decrypt_value(encrypted_value):
    """Decrypt a string value."""
    if not encrypted_value:
        return None
    try:
        return get_fernet().decrypt(encrypted_value.encode()).decode()
    except:
        # If decryption fails, assume it's not encrypted
        return encrypted_value


def create_hash(value):
    """Create searchable hash."""
    if not value:
        return None
    key = get_encryption_key()
    return hmac.new(key, value.lower().encode(), hashlib.sha256).hexdigest()


def set_encrypted_email(user, email):
    """Set user email with encryption."""
    if email:
        user.encrypted_email = encrypt_value(email)
        user.email_hash = create_hash(email)
        # Set the underlying column directly to avoid recursion
        user._email = email  # This is already the underlying column
    else:
        user.encrypted_email = None
        user.email_hash = None
        user._email = None


def get_decrypted_email(user):
    """Get decrypted email from user."""
    if user.encrypted_email:
        return decrypt_value(user.encrypted_email)
    return user._email  # Fallback to legacy field


def set_encrypted_phone(player, phone):
    """Set player phone with encryption."""
    if phone:
        player.encrypted_phone = encrypt_value(phone)
        player.phone_hash = create_hash(phone)
        # Set the underlying column value directly via SQLAlchemy's internal state
        player._sa_instance_state.dict['phone'] = phone
    else:
        player.encrypted_phone = None
        player.phone_hash = None
        player._sa_instance_state.dict['phone'] = None


def get_decrypted_phone(player):
    """Get decrypted phone from player."""
    if player.encrypted_phone:
        return decrypt_value(player.encrypted_phone)
    return player.phone  # Fallback to legacy field