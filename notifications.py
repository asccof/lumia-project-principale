# notifications.py
# Envoi d’e-mails via SMTP Zoho (gratuit). SMS/WhatsApp gardés en stubs pour plus tard.

import os, smtplib, ssl
from email.message import EmailMessage

SMTP_HOST = os.getenv('MAIL_SERVER', 'smtp.zoho.com')
SMTP_PORT = int(os.getenv('MAIL_PORT', '465'))  # 465 SSL recommandé
SMTP_USERNAME = os.getenv('MAIL_USERNAME')
SMTP_PASSWORD = os.getenv('MAIL_PASSWORD')
USE_SSL = os.getenv('MAIL_USE_SSL', 'True') == 'True'
USE_TLS = os.getenv('MAIL_USE_TLS', 'False') == 'True'
DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER') or SMTP_USERNAME

def _send_raw_email(to_address: str, subject: str, body: str) -> bool:
    if not to_address or not SMTP_USERNAME or not SMTP_PASSWORD:
        print(f"[NOTIF][EMAIL] Config incomplète ou destinataire manquant (to={to_address})")
        return False

    msg = EmailMessage()
    msg['From'] = DEFAULT_SENDER
    msg['To'] = to_address
    msg['Subject'] = subject
    msg.set_content(body)

    try:
        if USE_SSL:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=20) as s:
                s.login(SMTP_USERNAME, SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                s.ehlo()
                if USE_TLS:
                    s.starttls(context=ssl.create_default_context())
                s.login(SMTP_USERNAME, SMTP_PASSWORD)
                s.send_message(msg)
        print(f"[NOTIF][EMAIL] OK -> {to_address} : {subject}")
        return True
    except Exception as e:
        print(f"[NOTIF][EMAIL] ERREUR -> {to_address}: {e}")
        return False

def send_email(email: str, subject: str, body: str) -> bool:
    return _send_raw_email(email, subject, body)

def send_sms(phone: str, text: str) -> bool:
    # Stub pour plus tard (Twilio, Vonage, etc.)
    print(f"[NOTIF][SMS] (stub) -> {phone}: {text}")
    return False

def send_whatsapp(phone: str, text: str) -> bool:
    # Stub pour plus tard (WhatsApp Business API / Twilio)
    print(f"[NOTIF][WA] (stub) -> {phone}: {text}")
    return False
