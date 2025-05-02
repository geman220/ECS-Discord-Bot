from flask import Blueprint, render_template

demo_bp = Blueprint('demo', __name__, url_prefix='/demo')

@demo_bp.route('/responsive-tables')
def responsive_tables():
    """Demo page for responsive tables implementation."""
    return render_template('demo-responsive-tables.html', title="Responsive Tables Demo")