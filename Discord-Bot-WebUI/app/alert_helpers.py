"""
Sweet Alert helpers for unified notification system.
Replaces Flask flash messages with Sweet Alerts (SA2).
"""

from flask import session


def show_sweet_alert(title, text, icon='success'):
    """
    Set a Sweet Alert to be displayed on the next page load.
    
    Args:
        title (str): Alert title
        text (str): Alert message
        icon (str): Alert icon ('success', 'error', 'warning', 'info', 'question')
    """
    session['sweet_alert'] = {
        'title': title,
        'text': text,
        'icon': icon
    }


def show_success(message, title='Success'):
    """Show success alert."""
    show_sweet_alert(title, message, 'success')


def show_error(message, title='Error'):
    """Show error alert."""
    show_sweet_alert(title, message, 'error')


def show_warning(message, title='Warning'):
    """Show warning alert."""
    show_sweet_alert(title, message, 'warning')


def show_info(message, title='Info'):
    """Show info alert."""
    show_sweet_alert(title, message, 'info')