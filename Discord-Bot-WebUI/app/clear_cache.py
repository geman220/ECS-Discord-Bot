# app/clear_cache.py

"""
Cache Clear Module

This module provides endpoints for clearing browser cache when updates are made to
mobile responsive CSS and JavaScript files.
"""

from flask import Blueprint, render_template, redirect, url_for

clear_cache_bp = Blueprint('clear_cache', __name__)

@clear_cache_bp.route('/clear_cache')
def clear_cache():
    """
    Renders a page that forces browsers to clear their cache of critical mobile files.
    
    This route displays a loading spinner while JavaScript clears the browser cache
    of key responsive files, then redirects to the home page.
    
    Returns:
        The rendered clear_cache.html template
    """
    return render_template('clear_cache_flowbite.html', title='Updating Mobile Experience')