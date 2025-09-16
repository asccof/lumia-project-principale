# notifications.py
# Envoi d’e-mails via SMTP (Zoho, Gmail, SendGrid SMTP, etc.). SMS/WhatsApp restent des stubs.

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Iterable, List, Optional

# -------- Helpers --------
def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    val = val.strip().lower()
    return val in {"1", "true", "yes", "on", "y"}

def _split_recipients(value: str) -> List[str]:
    parts = []
    for chunk in (value or "").replace(";", ",").split(","):
        c = chunk.strip()
        if c:
            parts.append(c)
    return parts

def _choose_port(use_ssl: bool, use_tls: bool, env_port: Optional[str]) -> int:
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    if use_ssl:
        return 465
    if use_tls:
        return 587
    return 25

# -------- Configuration (supporte EMAIL_* et MAIL_*) --------
# Priorité aux variables EMAIL_* ; fallback sur MAIL_* pour compat.
SMTP_HOST = os.getenv("EMAIL_HOST") or os.getenv("MAIL_SERVER") or "smtp.zoho.com"

# Modes SSL/TLS : on prend les flags explicites si fournis, sinon heuristique par port.
USE_SSL = _env_bool("EMAIL_USE_SSL", _env_bool("MAIL_USE_SSL", False))
USE_TLS = _env_bool("EMAIL_USE_TLS", _env_bool("MAIL_USE_TLS", True))  # défaut True (Zoho 587)

# Si un port explicite est fourni, on le respecte, sinon on devine selon SSL/TLS.
SMTP_PORT = _choose_port(
    USE_SSL, USE_TLS,
    os.getenv("EMAIL_PORT") or os.getenv("MAIL_PORT")
)

SMTP_USERNAME = os.getenv("EMAIL_USER") or os.getenv("MAIL_USERNAME")
SMTP_PASSWORD = os.getenv("EMAIL_PASS") or os.getenv("MAIL_PASSWORD")

FROM_NAME      = os.getenv("EMAIL_FROM_NAME") or os.getenv("MAIL_FROM_NAME") or os.getenv("MAIL_DEFAULT_SENDER_NAME") or "Tighri"
DEFAULT_SENDER = os.getenv("EMAIL_FROM") or os.getenv("MAIL_DEFAULT_SENDER") or SMTP_USERNAME or "no-reply@tighri.com"
REPLY_TO       = os.getenv("EMAIL_REPLY_TO") or os.getenv("MAIL_REPLY_TO")  # optionnel

BRAND = os.getenv("BRAND_NAME", "Tighri")

EMAIL_ENABLED = _env_bool("EMAIL_ENABLED", True)  # si tu veux pouvoir couper l’envoi rapidement

# -------- Core email --------
def _build_message(
    to_addresses: Iterable[str],
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{FROM_NAME} <{DEFAULT_SENDER}>" if FROM_NAME and DEFAULT_SENDER else (DEFAULT_SENDER or "")
    msg["To"] = ", ".join(to_addresses)
    msg["Subject"] = subject
    if REPLY_TO:
        msg["Reply-To"] = REPLY_TO

    if body_html:
        msg.set_content(body_text or "")
        msg.add_alternative(body_html, subtype="html")
    else:
        msg.set_content(body_text or "")

    return msg

def _send_via_smtp(msg: EmailMessage) -> bool:
    if not EMAIL_ENABLED:
        print(f"[NOTIF][EMAIL] Désactivé (EMAIL_ENABLED=false) — skip → {msg.get('To')} : {msg.get('Subject')}")
        return False

    if not SMTP_HOST:
        print("[NOTIF][EMAIL] ERREUR: SMTP_HOST non défini (EMAIL_HOST/MAIL_SERVER).")
        return False
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("[NOTIF][EMAIL] ERREUR: identifiants manquants (EMAIL_USER/PASS ou MAIL_USERNAME/PASSWORD).")
        return False
    if not DEFAULT_SENDER:
        print("[NOTIF][EMAIL] ERREUR: expéditeur manquant (EMAIL_FROM ou MAIL_DEFAULT_SENDER).")
        return False

    try:
        if USE_SSL:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=20) as s:
                s.login(SMTP_USERNAME, SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                s.ehlo()
                if USE_TLS:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                s.login(SMTP_USERNAME, SMTP_PASSWORD)
                s.send_message(msg)
        print(f"[NOTIF][EMAIL] OK → {msg.get('To')} : {msg.get('Subject')}")
        return True
    except Exception as e:
        print(f"[NOTIF][EMAIL] ERREUR → {msg.get('To')} : {e}")
        return False

# -------- API publique --------
def _send_raw_email(to_address: str, subject: str, body: str) -> bool:
    recipients = _split_recipients(to_address)
    if not recipients:
        print(f"[NOTIF][EMAIL] Destinataire manquant.")
        return False
    msg = _build_message(recipients, subject, body_text=body, body_html=None)
    return _send_via_smtp(msg)

def send_email(email: str, subject: str, body: str, html: Optional[str] = None) -> bool:
    recipients = _split_recipients(email)
    if not recipients:
        print("[NOTIF][EMAIL] Destinataire manquant.")
        return False
    msg = _build_message(recipients, subject, body_text=body, body_html=html)
    return _send_via_smtp(msg)

def send_sms(phone: str, text: str) -> bool:
    # Stub pour intégration future (Twilio/Vonage…)
    print(f"[NOTIF][SMS] (stub) → {phone}: {text}")
    return False

def send_whatsapp(phone: str, text: str) -> bool:
    # Stub pour intégration future (WhatsApp Business API / Twilio)
    print(f"[NOTIF][WA] (stub) → {phone}: {text}")
    return False
