import os
import logging
from flask import Flask, jsonify, Blueprint
from google.oauth2 import service_account
from googleapiclient.discovery import build
from email.mime.text import MIMEText
import base64
import traceback

email_bp = Blueprint('email', __name__, template_folder='templates')

logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s %(levelname)s %(message)s', 
    datefmt='%Y-%m-%d %H:%M:%S'
)

def send_email(to, subject, body):
    SCOPES = ['https://www.googleapis.com/auth/gmail.send']
    
    logging.debug("Starting send_email function")
    
    credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

    if not credentials_path:
        logging.error("GOOGLE_APPLICATION_CREDENTIALS is not set or is empty.")
        return None
    
    logging.debug(f"GOOGLE_APPLICATION_CREDENTIALS is set to: {credentials_path}")
    
    if not os.path.exists(credentials_path):
        logging.error(f"Service account JSON file not found at {credentials_path}")
        return None
    else:
        logging.debug(f"Service account JSON file found at {credentials_path}")

    try:
        delegated_credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES, subject='donotreply@weareecs.com'
        )
        logging.debug("Successfully loaded delegated credentials from the service account file")
    except Exception as e:
        logging.error(f"Failed to load credentials: {e}")
        traceback.print_exc()
        return None

    try:
        service = build('gmail', 'v1', credentials=delegated_credentials)
        logging.debug("Gmail service built successfully with delegated credentials")
    except Exception as e:
        logging.error(f"Failed to build Gmail service: {e}")
        traceback.print_exc()
        return None

    try:
        # Set the MIME type as 'html' to ensure the email is rendered as HTML
        message = MIMEText(body, "html")
        message['to'] = to
        message['from'] = 'donotreply@weareecs.com'
        message['subject'] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        message_body = {'raw': raw}

        message = service.users().messages().send(userId="me", body=message_body).execute()
        logging.debug(f"Email sent successfully with Message Id: {message['id']}")
        return message
    except Exception as error:
        logging.error(f"An error occurred while sending the email: {error}")
        traceback.print_exc()  # Log full stack trace for debugging
        return None