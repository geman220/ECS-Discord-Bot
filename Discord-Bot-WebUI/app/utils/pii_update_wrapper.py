"""
Wrapper functions to ensure PII encryption on updates.

Import and use these functions instead of directly setting email/phone fields.
"""

from app.utils.pii_encryption import set_encrypted_email, set_encrypted_phone, get_decrypted_email, get_decrypted_phone
from app.core import db


def update_user_email(user, new_email):
    """Update user email with encryption."""
    set_encrypted_email(user, new_email)
    db.session.commit()
    return True


def update_player_phone(player, new_phone):
    """Update player phone with encryption."""
    set_encrypted_phone(player, new_phone)
    db.session.commit()
    return True


def safe_get_email(user):
    """Safely get user email (decrypted if needed)."""
    return get_decrypted_email(user)


def safe_get_phone(player):
    """Safely get player phone (decrypted if needed)."""
    return get_decrypted_phone(player)


# Monkey-patch the User and Player models to auto-encrypt on save
def init_pii_encryption():
    """Initialize PII encryption for models (call this on app startup)."""
    from app.models.core import User
    from app.models.players import Player
    
    # Store original email setter
    original_email_setter = User.email.fset if hasattr(User, 'email') and hasattr(User.email, 'fset') else None
    
    # Create new email property that auto-encrypts
    def email_getter(self):
        if self.encrypted_email:
            return get_decrypted_email(self)
        return self._email
    
    def email_setter(self, value):
        set_encrypted_email(self, value)
    
    # Override email property
    User.email = property(email_getter, email_setter)
    
    # Store original phone column BEFORE overriding it
    original_phone_column = Player.__table__.columns.get('phone')
    
    # Create new phone property for Player that auto-encrypts
    def phone_getter(self):
        if self.encrypted_phone:
            return get_decrypted_phone(self)
        # Access the underlying column value directly
        return object.__getattribute__(self, '_sa_instance_state').dict.get('phone', None)
    
    def phone_setter(self, value):
        # Store in a temporary attribute to avoid recursion
        if not hasattr(self, '_setting_phone'):
            self._setting_phone = True
            try:
                set_encrypted_phone(self, value)
            finally:
                self._setting_phone = False
    
    # Store reference to original column
    Player._phone_column = original_phone_column
    
    # Override phone property
    Player.phone = property(phone_getter, phone_setter)
    
    return True