# app/email.py

"""
Email Module

This module provides functionality for sending emails using the Gmail API.
It utilizes a service account with delegated credentials to build the Gmail
service and send HTML-formatted emails. Detailed logging and error handling
are included to facilitate debugging and ensure reliable email delivery.
"""

import os
import logging
import base64
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Blueprint
from google.oauth2 import service_account
from googleapiclient.discovery import build

email_bp = Blueprint('email', __name__, template_folder='templates')

logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s %(levelname)s %(message)s', 
    datefmt='%Y-%m-%d %H:%M:%S'
)

def send_email(to, subject, body):
    """
    Sends an HTML email using the Gmail API with a service account.

    Parameters:
        to (str or list): Recipient email address or a list of email addresses.
        subject (str): The subject of the email.
        body (str): The HTML body content of the email.

    Returns:
        dict or None: The sent message data on success, or None if an error occurred.
    """
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
        message['to'] = ', '.join(to) if isinstance(to, list) else to
        message['from'] = 'donotreply@weareecs.com'
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        message_body = {'raw': raw}
        sent_message = service.users().messages().send(userId="me", body=message_body).execute()
        logging.debug(f"Email sent successfully with Message Id: {sent_message['id']}")
        return sent_message
    except Exception as error:
        logging.error(f"An error occurred while sending the email: {error}")
        traceback.print_exc()
        return None


def send_email_bcc(bcc_list, subject, body):
    """
    Sends an HTML email to multiple recipients using BCC via the Gmail API.

    The 'To' header is set to undisclosed-recipients and all actual addresses
    go in the BCC header so recipients cannot see each other.

    Parameters:
        bcc_list (list): List of email addresses for BCC.
        subject (str): The subject of the email.
        body (str): The HTML body content of the email.

    Returns:
        dict or None: The sent message data on success, or None if an error occurred.
    """
    if not bcc_list:
        logging.warning("send_email_bcc called with empty bcc_list")
        return None

    SCOPES = ['https://www.googleapis.com/auth/gmail.send']

    credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if not credentials_path:
        logging.error("GOOGLE_APPLICATION_CREDENTIALS is not set or is empty.")
        return None

    if not os.path.exists(credentials_path):
        logging.error(f"Service account JSON file not found at {credentials_path}")
        return None

    try:
        delegated_credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES, subject='donotreply@weareecs.com'
        )
    except Exception as e:
        logging.error(f"Failed to load credentials: {e}")
        traceback.print_exc()
        return None

    try:
        service = build('gmail', 'v1', credentials=delegated_credentials)
    except Exception as e:
        logging.error(f"Failed to build Gmail service: {e}")
        traceback.print_exc()
        return None

    try:
        message = MIMEText(body, "html")
        message['to'] = 'donotreply@weareecs.com'
        message['from'] = 'donotreply@weareecs.com'
        message['bcc'] = ', '.join(bcc_list)
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        message_body = {'raw': raw}
        sent_message = service.users().messages().send(userId="me", body=message_body).execute()
        logging.debug(f"BCC email sent successfully to {len(bcc_list)} recipients, Message Id: {sent_message['id']}")
        return sent_message
    except Exception as error:
        logging.error(f"An error occurred while sending BCC email: {error}")
        traceback.print_exc()
        return None