import hashlib
from werkzeug.security import generate_password_hash

def get_hashing_method():
    """Return the best available hashing method for the current environment."""
    return 'scrypt' if hasattr(hashlib, 'scrypt') else 'pbkdf2:sha256'

def secure_hash_password(password):
    """Hash a password using the best available method."""
    return generate_password_hash(password, method=get_hashing_method())
