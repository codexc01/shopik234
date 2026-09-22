import os
import json
import hashlib
import hmac
import logging
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger("norvex_payments")

# --- CryptoBot (CryptoPay API) ---

async def create_cryptobot_invoice(
    api_token: str,
    order_code: str,
    amount_rub: float,
    description: str = "Оплата заказа",
    paid_btn_url: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    if not api_token or api_token.startswith("YOUR_"):
        return None

    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": api_token}
    
    payload = {
        "currency_type": "fiat",
        "fiat": "RUB",
        "amount": str(round(amount_rub, 2)),
        "accepted_assets": "USDT,TON,BTC,ETH,LTC,BNB,TRX,USDC",
        "description": f"{description} #{order_code}",
        "payload": order_code,
        "allow_comments": False,
        "allow_anonymous": False,
        "expires_in": 3600
    }
    if paid_btn_url:
        payload["paid_btn_name"] = "openBot"
        payload["paid_btn_url"] = paid_btn_url

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            data = resp.json()
            if data.get("ok"):
                result = data.get("result", {})
                return {
                    "invoice_id": result.get("invoice_id"),
                    "pay_url": result.get("bot_invoice_url") or result.get("mini_app_invoice_url") or result.get("web_app_invoice_url") or result.get("pay_url"),
                    "mini_app_url": result.get("mini_app_invoice_url"),
                    "bot_url": result.get("bot_invoice_url"),
                    "status": result.get("status")
                }
            else:
                logger.error(f"CryptoBot createInvoice error: {data.get('error')}")
                return None
    except Exception as e:
        logger.error(f"CryptoBot request failed: {e}")
        return None

def verify_cryptobot_webhook(body_bytes: bytes, signature_header: str, api_token: str) -> bool:
    if not signature_header or not api_token:
        return False
    try:
        secret = hashlib.sha256(api_token.encode("utf-8")).digest()
        calc_sign = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(calc_sign, signature_header)
    except Exception as e:
        logger.error(f"CryptoBot webhook verify failed: {e}")
        return False


# --- Telegram Stars (XTR) ---

async def create_telegram_stars_invoice_link(
    bot_token: str,
    order_code: str,
    title: str,
    description: str,
    stars_amount: int
) -> Optional[str]:
    if not bot_token or bot_token.startswith("YOUR_"):
        return None

    url = f"https://api.telegram.org/bot{bot_token}/createInvoiceLink"
    payload = {
        "title": title[:32],
        "description": description[:255],
        "payload": order_code,
        "currency": "XTR",
        "prices": [{"label": "Оплата звездами", "amount": max(1, int(stars_amount))}]
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if data.get("ok"):
                return data.get("result")
            else:
                logger.error(f"Telegram Stars createInvoiceLink error: {data.get('description')}")
                return None
    except Exception as e:
        logger.error(f"Telegram Stars request failed: {e}")
        return None


# --- Aaio (СБП, Карты РФ, физлица) ---

def create_aaio_payment_url(
    merchant_id: str,
    secret_1: str,
    order_code: str,
    amount_rub: float,
    description: str = "Оплата заказа",
    currency: str = "RUB"
) -> Optional[str]:
    if not merchant_id or not secret_1 or merchant_id.startswith("YOUR_"):
        return None

    try:
        amount_str = f"{amount_rub:.2f}"
        sign_str = f"{merchant_id}:{amount_str}:{currency}:{secret_1}:{order_code}"
        sign = hashlib.sha256(sign_str.encode("utf-8")).hexdigest()
        
        import urllib.parse
        params = {
            "merchant_id": merchant_id,
            "amount": amount_str,
            "currency": currency,
            "order_id": order_code,
            "sign": sign,
            "desc": f"{description} #{order_code}"
        }
        return f"https://aaio.so/merchant/pay?{urllib.parse.urlencode(params)}"
    except Exception as e:
        logger.error(f"Aaio create payment URL failed: {e}")
        return None

def verify_aaio_webhook(
    merchant_id: str,
    secret_2: str,
    order_id: str,
    amount: str,
    currency: str,
    received_sign: str
) -> bool:
    if not merchant_id or not secret_2 or not received_sign:
        return False
    try:
        sign_str = f"{merchant_id}:{amount}:{currency}:{secret_2}:{order_id}"
        calc_sign = hashlib.sha256(sign_str.encode("utf-8")).hexdigest()
        return hmac.compare_digest(calc_sign.lower(), received_sign.lower())
    except Exception as e:
        logger.error(f"Aaio webhook verify failed: {e}")
        return False
