# notifications.py
import os
import smtplib
from email.message import EmailMessage

# Twilio est optionnel. Si non installé / non configuré, on continue sans planter.
try:
    from twilio.rest import Client as TwilioClient
    _TWILIO_OK = True
except Exception:
    _TWILIO_OK = False


def _bool_env(name: str, default: bool = True) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def normalize_phone(num: str) -> str | None:
    """Normalise en E.164 simple. Ajoute DEFAULT_COUNTRY_CODE si nécessaire."""
    if not num:
        return None
    n = num.strip().replace(" ", "").replace("-", "")
    if n.startswith("+"):
        return n
    cc = os.environ.get("DEFAULT_COUNTRY_CODE", "+212")  # Maroc par défaut
    # enlève éventuel 0 de tête
    if n.startswith("0"):
        n = n[1:]
    return f"{cc}{n}"


# ---------------- Email ----------------
def send_email(to_email: str | None, subject: str, text: str, html: str | None = None) -> bool:
    if not to_email:
        return False

    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    pwd  = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("SMTP_FROM", user or "no-reply@tighri.com")

    if not host or not user or not pwd:
        # Pas de config SMTP -> on ignore en silence (fail-soft)
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_email
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")

        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
        return True
    except Exception:
        return False


# ---------------- SMS ----------------
def send_sms(to_phone: str | None, text: str) -> bool:
    if not to_phone:
        return False
    if not _TWILIO_OK:
        return False

    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    tok = os.environ.get("TWILIO_AUTH_TOKEN")
    from_sms = os.environ.get("TWILIO_FROM_SMS")

    if not sid or not tok or not from_sms:
        return False

    try:
        client = TwilioClient(sid, tok)
        client.messages.create(
            body=text,
            from_=from_sms,
            to=normalize_phone(to_phone)
        )
        return True
    except Exception:
        return False


# ---------------- WhatsApp ----------------
def send_whatsapp(to_phone: str | None, text: str) -> bool:
    if not to_phone:
        return False
    if not _TWILIO_OK:
        return False

    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    tok = os.environ.get("TWILIO_AUTH_TOKEN")
    from_wa = os.environ.get("TWILIO_FROM_WHATSAPP")  # ex: "whatsapp:+1415XXXXXXX"

    if not sid or not tok or not from_wa:
        return False

    try:
        client = TwilioClient(sid, tok)
        client.messages.create(
            body=text,
            from_=from_wa,
            to=f"whatsapp:{normalize_phone(to_phone)}"
        )
        return True
    except Exception:
        return False
