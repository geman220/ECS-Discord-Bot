# app/static.py
from flask import send_from_directory, current_app, request
from werkzeug.middleware.proxy_fix import ProxyFix
from app.database.cache import cache_static_file
from pathlib import Path
import mimetypes
import logging
from werkzeug.utils import safe_join

logger = logging.getLogger(__name__)

def configure_static_serving(app):
    static_folder = Path(app.static_folder)
    
    @app.route('/static/<path:filename>')
    @cache_static_file()
    def serve_static(filename):
        try:
            # Secure file path handling
            file_path = safe_join(static_folder, filename)
            if not file_path or not Path(file_path).exists():
                return app.send_static_file('404.html'), 404

            # ETag handling
            if request.if_none_match and current_app.config['DEBUG'] is False:
                response = current_app.make_response()
                response.status_code = 304
                return response
                
            response = send_from_directory(static_folder, filename)
            
            # Set correct content type
            content_type = mimetypes.guess_type(filename)[0]
            if content_type:
                response.headers['Content-Type'] = content_type
                
            response.headers.update({
                'Cache-Control': 'public, max-age=31536000',
                'X-Content-Type-Options': 'nosniff',
                'Access-Control-Allow-Origin': '*'
            })
            return response
            
        except Exception as e:
            logger.error(f"Static file error: {e}")
            return app.send_static_file('500.html'), 500