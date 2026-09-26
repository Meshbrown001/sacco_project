"""
The connection to Safaricom's Daraja API.
Handles the access token, the password, the STK push and the status query.
"""

import base64
import logging

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

BASE_URLS = {
    "sandbox": "https://sandbox.safaricom.co.ke",
    "production": "https://api.safaricom.co.ke",
}
TOKEN_CACHE_KEY = "mpesa_access_token"
REQUEST_TIMEOUT = 30  # seconds


class DarajaError(Exception):
    """Safaricom refused or could not be reached. The message is safe to show."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details


def base_url():
    try:
        return BASE_URLS[settings.MPESA_ENV]
    except KeyError:
        raise DarajaError(f"MPESA_ENV must be sandbox or production, not {settings.MPESA_ENV!r}.")


def get_access_token(force_refresh=False):
    """Returns a token, reusing a cached one until shortly before it expires."""
    if not force_refresh:
        token = cache.get(TOKEN_CACHE_KEY)
        if token:
            return token

    key = settings.MPESA_CONSUMER_KEY
    secret = settings.MPESA_CONSUMER_SECRET
    if not key or not secret:
        raise DarajaError("The M-Pesa consumer key or secret is missing from .env.")

    try:
        response = requests.get(
            f"{base_url()}/oauth/v1/generate",
            params={"grant_type": "client_credentials"},
            auth=(key, secret),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise DarajaError("Could not reach Safaricom.", str(exc))

    if response.status_code != 200:
        raise DarajaError("Safaricom rejected the M-Pesa keys.", response.text[:500])

    data = response.json()
    token = data.get("access_token")
    if not token:
        raise DarajaError("Safaricom returned no access token.", data)

    expires_in = int(data.get("expires_in", 3599))
    cache.set(TOKEN_CACHE_KEY, token, max(expires_in - 60, 60))
    return token


def make_timestamp():
    """Safaricom expects Kenyan time as YYYYMMDDHHMMSS."""
    return timezone.localtime().strftime("%Y%m%d%H%M%S")


def make_password(shortcode, timestamp):
    raw = f"{shortcode}{settings.MPESA_PASSKEY}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


def _post(path, payload):
    """POSTs to Daraja, refreshing the token once if Safaricom says it expired."""
    for attempt in (1, 2):
        token = get_access_token(force_refresh=(attempt == 2))
        try:
            response = requests.post(
                f"{base_url()}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise DarajaError("Could not reach Safaricom.", str(exc))

        if response.status_code == 401 and attempt == 1:
            continue

        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text[:500]}
        return response.status_code, data

    return response.status_code, {}


def stk_push(payment_settings, phone_number, amount, callback_url, description="Contribution"):
    """Sends the PIN prompt to the member's phone."""
    timestamp = make_timestamp()
    shortcode = payment_settings.business_shortcode

    if payment_settings.shortcode_type == "till":
        transaction_type = "CustomerBuyGoodsOnline"
        party_b = payment_settings.till_number
    else:
        transaction_type = "CustomerPayBillOnline"
        party_b = shortcode

    payload = {
        "BusinessShortCode": shortcode,
        "Password": make_password(shortcode, timestamp),
        "Timestamp": timestamp,
        "TransactionType": transaction_type,
        "Amount": int(amount),
        "PartyA": phone_number,
        "PartyB": party_b,
        "PhoneNumber": phone_number,
        "CallBackURL": callback_url,
        "AccountReference": payment_settings.account_reference[:12],
        "TransactionDesc": description[:13],
    }

    status_code, data = _post("/mpesa/stkpush/v1/processrequest", payload)
    if status_code == 200 and str(data.get("ResponseCode")) == "0":
        return data

    message = data.get("errorMessage") or data.get("ResponseDescription") or "M-Pesa did not accept the request."
    raise DarajaError(message, data)


def stk_query(payment_settings, checkout_request_id):
    """Asks Safaricom for the outcome of an earlier prompt."""
    timestamp = make_timestamp()
    shortcode = payment_settings.business_shortcode
    payload = {
        "BusinessShortCode": shortcode,
        "Password": make_password(shortcode, timestamp),
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id,
    }
    return _post("/mpesa/stkpushquery/v1/query", payload)