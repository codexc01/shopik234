import hmac
import hashlib
import json
import urllib.parse
from typing import Optional, Dict, Any

# проверка подписи телеграм через hmac sha256
def validate_telegram_init_data(init_data: str, bot_token: str, admin_ids: list) -> Optional[Dict[str, Any]]:
    if not init_data:
        return None

    try:
        # разбираем строку параметров
        parsed_params = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        data_dict = dict(parsed_params)

        if "hash" not in data_dict:
            return None

        received_hash = data_dict.pop("hash")

        # сортируем ключи по алфавиту
        sorted_items = sorted(data_dict.items(), key=lambda item: item[0])
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted_items])

        # генерируем секретный ключ
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()

        # считаем хэш
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        # получаем данные пользователя
        user_raw = data_dict.get("user")
        user_obj = json.loads(user_raw) if user_raw else {}

        user_id = user_obj.get("id")
        username = (user_obj.get("username") or "").lower()

        # сверяем со списком админов
        clean_admins = [str(a).strip().replace("@", "").lower() for a in admin_ids if str(a).strip()]
        is_admin = False
        if clean_admins:
            if str(user_id) in clean_admins or (username and username in clean_admins):
                is_admin = True

        return {
            "valid": True,
            "user": user_obj,
            "user_id": user_id,
            "username": username,
            "is_admin": is_admin,
            "auth_date": data_dict.get("auth_date")
        }

    except Exception as e:
        print(f"ошибка валидации initData: {e}")
        return None
