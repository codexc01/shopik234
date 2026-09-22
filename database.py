import os
import time
import json
from typing import List, Dict, Any, Optional, Tuple

# проверяем наличие postgres url
DB_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
IS_POSTGRES = bool(DB_URL and ("postgres://" in DB_URL or "postgresql://" in DB_URL))

if IS_POSTGRES:
    if DB_URL.startswith("postgres://"):
        DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)
    import psycopg2
    from psycopg2.extras import RealDictCursor
else:
    import sqlite3
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        DB_PATH = "/tmp/norvex_shop.db"
    else:
        DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "norvex_shop.db")

# подключение к бд
def get_connection():
    if IS_POSTGRES:
        conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
        conn.autocommit = True
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def placeholder(sql: str) -> str:
    if IS_POSTGRES:
        return sql.replace("?", "%s")
    return sql

# создание таблиц в базе
def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # категории
    cur.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        icon_key TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0
    );
    """)

    # товары
    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        category_id TEXT NOT NULL,
        price INTEGER NOT NULL,
        old_price INTEGER DEFAULT 0,
        badge TEXT DEFAULT '',
        image_url TEXT DEFAULT '',
        description TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # заказы
    if IS_POSTGRES:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            order_code TEXT UNIQUE NOT NULL,
            buyer_id BIGINT,
            buyer_name TEXT,
            buyer_username TEXT,
            total_rub INTEGER NOT NULL,
            total_count INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            payment_method TEXT DEFAULT '',
            payment_id TEXT DEFAULT '',
            payment_url TEXT DEFAULT '',
            discount_rub INTEGER DEFAULT 0,
            promo_code TEXT DEFAULT '',
            bonus_used INTEGER DEFAULT 0,
            delivered_keys TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            price INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            subtotal INTEGER NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS product_stock (
            id SERIAL PRIMARY KEY,
            product_id TEXT NOT NULL,
            item_data TEXT NOT NULL,
            is_used BOOLEAN DEFAULT FALSE,
            order_code TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            discount_type TEXT NOT NULL,
            discount_val NUMERIC NOT NULL,
            min_order INTEGER DEFAULT 0,
            max_uses INTEGER DEFAULT 0,
            uses_count INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_referrals (
            user_id BIGINT PRIMARY KEY,
            referrer_id BIGINT,
            bonus_balance INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_users (
            user_id BIGINT PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_code TEXT UNIQUE NOT NULL,
            buyer_id INTEGER,
            buyer_name TEXT,
            buyer_username TEXT,
            total_rub INTEGER NOT NULL,
            total_count INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            payment_method TEXT DEFAULT '',
            payment_id TEXT DEFAULT '',
            payment_url TEXT DEFAULT '',
            discount_rub INTEGER DEFAULT 0,
            promo_code TEXT DEFAULT '',
            bonus_used INTEGER DEFAULT 0,
            delivered_keys TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            price INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            subtotal INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS product_stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            item_data TEXT NOT NULL,
            is_used INTEGER DEFAULT 0,
            order_code TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            discount_type TEXT NOT NULL,
            discount_val REAL NOT NULL,
            min_order INTEGER DEFAULT 0,
            max_uses INTEGER DEFAULT 0,
            uses_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_referrals (
            user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER,
            bonus_balance INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

    # миграции колонок если старая бд
    cols_to_add = [
        ("orders", "payment_method", "TEXT DEFAULT ''"),
        ("orders", "payment_id", "TEXT DEFAULT ''"),
        ("orders", "payment_url", "TEXT DEFAULT ''"),
        ("orders", "discount_rub", "INTEGER DEFAULT 0"),
        ("orders", "promo_code", "TEXT DEFAULT ''"),
        ("orders", "bonus_used", "INTEGER DEFAULT 0"),
        ("orders", "delivered_keys", "TEXT DEFAULT ''")
    ]
    for tbl, col, ctype in cols_to_add:
        try:
            cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {ctype};")
        except Exception:
            pass

    # создаем корневую категорию если пусто
    cur.execute("SELECT COUNT(*) as cnt FROM categories;")
    res = cur.fetchone()
    count = res["cnt"] if (isinstance(res, dict) or hasattr(res, "keys")) else res[0]
    if count == 0:
        cur.execute(placeholder("INSERT INTO categories (id, name, icon_key, sort_order) VALUES (?, ?, ?, ?);"), ('all', 'Все товары', 'all', 0))

    if not IS_POSTGRES:
        conn.commit()
    conn.close()

# --- КАТЕГОРИИ ---
def get_categories() -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, icon_key as \"iconKey\", sort_order FROM categories ORDER BY sort_order ASC, id ASC;")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def create_category(cat_id: str, name: str, icon_key: str) -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("INSERT INTO categories (id, name, icon_key, sort_order) VALUES (?, ?, ?, 10);"), (cat_id, name, icon_key))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return {"id": cat_id, "name": name, "iconKey": icon_key}

def delete_category(cat_id: str) -> bool:
    if cat_id == 'all':
        return False
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("DELETE FROM categories WHERE id = ?;"), (cat_id,))
    cur.execute(placeholder("UPDATE products SET category_id = 'keys' WHERE category_id = ?;"), (cat_id,))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return True

# --- ТОВАРЫ ---
def get_products(category_id: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    
    query = """
    SELECT id, name, category_id as "catId", price, old_price as "oldPrice", badge, image_url as img, description as "desc", created_at
    FROM products
    WHERE 1=1
    """
    params = []
    if category_id and category_id != 'all':
        query += " AND category_id = ?"
        params.append(category_id)
    if search:
        query += " AND (name ILIKE ? OR description ILIKE ?)" if IS_POSTGRES else " AND (name LIKE ? OR description LIKE ?)"
        params.append(f"%{search}%")
        params.append(f"%{search}%")
    
    query += " ORDER BY created_at DESC;"
    cur.execute(placeholder(query), tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    
    # подтягиваем остаток ключей на складе
    for p in rows:
        cur.execute(placeholder("SELECT COUNT(*) as cnt FROM product_stock WHERE product_id = ? AND (is_used = FALSE OR is_used = 0);"), (p["id"],))
        s_res = cur.fetchone()
        p["stockCount"] = s_res["cnt"] if (isinstance(s_res, dict) or hasattr(s_res, "keys")) else s_res[0]
        
    conn.close()
    return rows

def get_product(prod_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("""
    SELECT id, name, category_id as "catId", price, old_price as "oldPrice", badge, image_url as img, description as "desc"
    FROM products WHERE id = ?;
    """), (prod_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    res = dict(row)
    cur.execute(placeholder("SELECT COUNT(*) as cnt FROM product_stock WHERE product_id = ? AND (is_used = FALSE OR is_used = 0);"), (prod_id,))
    s_res = cur.fetchone()
    res["stockCount"] = s_res["cnt"] if (isinstance(s_res, dict) or hasattr(s_res, "keys")) else s_res[0]
    conn.close()
    return res

def create_product(name: str, category_id: str, price: int, old_price: int = 0, badge: str = "", image_url: str = "", description: str = "") -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()
    prod_id = f"prod_{int(time.time() * 1000)}"
    cur.execute(placeholder("""
    INSERT INTO products (id, name, category_id, price, old_price, badge, image_url, description)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """), (prod_id, name, category_id, price, old_price, badge, image_url, description))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return {
        "id": prod_id,
        "name": name,
        "catId": category_id,
        "price": price,
        "oldPrice": old_price,
        "badge": badge,
        "img": image_url,
        "desc": description,
        "stockCount": 0
    }

def update_product(prod_id: str, name: str, category_id: str, price: int, old_price: int = 0, badge: str = "", image_url: str = "", description: str = "") -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("""
    UPDATE products
    SET name = ?, category_id = ?, price = ?, old_price = ?, badge = ?, image_url = ?, description = ?
    WHERE id = ?;
    """), (name, category_id, price, old_price, badge, image_url, description, prod_id))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return get_product(prod_id)

def delete_product(prod_id: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("DELETE FROM products WHERE id = ?;"), (prod_id,))
    cur.execute(placeholder("DELETE FROM product_stock WHERE product_id = ?;"), (prod_id,))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return True

# --- АВТОВЫДАЧА / СКЛАД ЦИФРОВЫХ КЛЮЧЕЙ ---
def add_product_stock(product_id: str, items: List[str]) -> int:
    if not items:
        return 0
    conn = get_connection()
    cur = conn.cursor()
    added = 0
    for item in items:
        cleaned = item.strip()
        if cleaned:
            cur.execute(placeholder("""
            INSERT INTO product_stock (product_id, item_data, is_used) VALUES (?, ?, FALSE);
            """ if IS_POSTGRES else """
            INSERT INTO product_stock (product_id, item_data, is_used) VALUES (?, ?, 0);
            """), (product_id, cleaned))
            added += 1
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return added

def get_product_stock(product_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("""
    SELECT id, product_id, item_data as "itemData", is_used as "isUsed", order_code as "orderCode", created_at as "createdAt"
    FROM product_stock WHERE product_id = ? ORDER BY id DESC;
    """), (product_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def pop_keys_for_order(order_code: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    
    # Проверка на случай если ключи уже были выданы этому заказу ранее
    cur.execute(placeholder("SELECT delivered_keys FROM orders WHERE order_code = ?;"), (order_code,))
    existing = cur.fetchone()
    if existing and existing["delivered_keys"]:
        conn.close()
        try:
            return json.loads(existing["delivered_keys"])
        except Exception:
            return []

    delivered = []
    
    for it in items:
        prod_id = str(it["productId"] if "productId" in it else it.get("product_id", ""))
        qty = max(1, min(int(it.get("qty", 1)), 100))
        prod_name = it.get("name") or it.get("product_name", "")
        
        # выбираем свободные ключи
        cur.execute(placeholder("""
        SELECT id, item_data FROM product_stock
        WHERE product_id = ? AND (is_used = FALSE OR is_used = 0)
        ORDER BY id ASC LIMIT ?;
        """), (prod_id, qty))
        stock_rows = cur.fetchall()
        
        keys_for_item = []
        for s in stock_rows:
            s_dict = dict(s)
            s_id = s_dict["id"]
            k_data = s_dict["item_data"]
            keys_for_item.append(k_data)
            cur.execute(placeholder("""
            UPDATE product_stock SET is_used = TRUE, order_code = ? WHERE id = ?;
            """ if IS_POSTGRES else """
            UPDATE product_stock SET is_used = 1, order_code = ? WHERE id = ?;
            """), (order_code, s_id))
            
        if keys_for_item:
            delivered.append({
                "productId": prod_id,
                "productName": prod_name,
                "keys": keys_for_item
            })
            
    if delivered:
        cur.execute(placeholder("UPDATE orders SET delivered_keys = ? WHERE order_code = ?;"), (json.dumps(delivered, ensure_ascii=False), order_code))
        
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return delivered

# --- ПРОМОКОДЫ ---
def create_promo_code(code: str, discount_type: str, discount_val: float, min_order: int = 0, max_uses: int = 0) -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()
    c_clean = code.strip().upper()
    cur.execute(placeholder("""
    INSERT INTO promo_codes (code, discount_type, discount_val, min_order, max_uses, uses_count, is_active)
    VALUES (?, ?, ?, ?, ?, 0, TRUE)
    ON CONFLICT (code) DO UPDATE SET discount_type = EXCLUDED.discount_type, discount_val = EXCLUDED.discount_val;
    """ if IS_POSTGRES else """
    INSERT OR REPLACE INTO promo_codes (code, discount_type, discount_val, min_order, max_uses, uses_count, is_active)
    VALUES (?, ?, ?, ?, ?, 0, 1);
    """), (c_clean, discount_type, discount_val, min_order, max_uses))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return {"code": c_clean, "discountType": discount_type, "discountVal": discount_val}

def delete_promo_code(code: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("DELETE FROM promo_codes WHERE code = ?;"), (code.strip().upper(),))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return True

def get_all_promos() -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT code, discount_type as "discountType", discount_val as "discountVal", 
           min_order as "minOrder", max_uses as "maxUses", uses_count as "usesCount", is_active as "isActive"
    FROM promo_codes ORDER BY created_at DESC;
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def validate_promo(code: str, total_rub: int) -> Tuple[bool, str, int]:
    if not code:
        return False, "Код не указан", 0
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("SELECT * FROM promo_codes WHERE code = ?;"), (code.strip().upper(),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False, "Промокод не найден", 0
    p = dict(row)
    if not p.get("is_active"):
        return False, "Промокод не активен", 0
    if p.get("max_uses", 0) > 0 and p.get("uses_count", 0) >= p.get("max_uses", 0):
        return False, "Лимит использования промокода исчерпан", 0
    if total_rub < p.get("min_order", 0):
        return False, f"Минимальная сумма для промокода: {p.get('min_order')} ₽", 0

    discount_type = p["discount_type"]
    discount_val = float(p["discount_val"])
    discount_rub = 0
    if discount_type == "percent":
        discount_rub = int(round(total_rub * (discount_val / 100.0)))
    else:
        discount_rub = int(round(discount_val))
    discount_rub = min(discount_rub, total_rub)
    return True, "Промокод применен", discount_rub

def increment_promo_use(code: str):
    if not code:
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("UPDATE promo_codes SET uses_count = uses_count + 1 WHERE code = ?;"), (code.strip().upper(),))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()

# --- ПОЛЬЗОВАТЕЛИ И РЕФЕРАЛЫ ---
def register_bot_user(user_id: int, username: str = "", first_name: str = "", referrer_id: Optional[int] = None):
    if not user_id:
        return
    conn = get_connection()
    cur = conn.cursor()
    
    # сохраняем в bot_users
    if IS_POSTGRES:
        cur.execute("""
        INSERT INTO bot_users (user_id, username, first_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name, is_active = TRUE;
        """, (user_id, username, first_name))
    else:
        cur.execute("""
        INSERT OR REPLACE INTO bot_users (user_id, username, first_name, is_active)
        VALUES (?, ?, ?, 1);
        """, (user_id, username, first_name))

    # проверяем реферала
    cur.execute(placeholder("SELECT user_id FROM user_referrals WHERE user_id = ?;"), (user_id,))
    if not cur.fetchone():
        ref_id = referrer_id if (referrer_id and referrer_id != user_id) else None
        cur.execute(placeholder("""
        INSERT INTO user_referrals (user_id, referrer_id, bonus_balance, total_earned)
        VALUES (?, ?, 0, 0);
        """), (user_id, ref_id))

    if not IS_POSTGRES:
        conn.commit()
    conn.close()

def get_user_profile(user_id: int) -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute(placeholder("SELECT bonus_balance as \"bonusBalance\", total_earned as \"totalEarned\" FROM user_referrals WHERE user_id = ?;"), (user_id,))
    ref_row = cur.fetchone()
    bonus_balance = ref_row["bonusBalance"] if ref_row else 0
    total_earned = ref_row["totalEarned"] if ref_row else 0
    
    # считаем приглашенных друзей
    cur.execute(placeholder("SELECT COUNT(*) as cnt FROM user_referrals WHERE referrer_id = ?;"), (user_id,))
    cnt_row = cur.fetchone()
    invited_count = cnt_row["cnt"] if (isinstance(cnt_row, dict) or hasattr(cnt_row, "keys")) else (cnt_row[0] if cnt_row else 0)
    
    # считаем выполненные заказы
    cur.execute(placeholder("SELECT COUNT(*) as cnt, COALESCE(SUM(total_rub), 0) as total_spent FROM orders WHERE buyer_id = ? AND status = 'paid';"), (user_id,))
    ord_row = cur.fetchone()
    orders_count = ord_row["cnt"] if (isinstance(ord_row, dict) or hasattr(ord_row, "keys")) else ord_row[0]
    total_spent = ord_row["total_spent"] if (isinstance(ord_row, dict) or hasattr(ord_row, "keys")) else ord_row[1]
    
    conn.close()
    return {
        "userId": user_id,
        "bonusBalance": bonus_balance,
        "totalEarned": total_earned,
        "invitedCount": invited_count,
        "ordersCount": orders_count,
        "totalSpent": total_spent
    }

def add_referral_bonus(user_id: int, bonus_rub: int):
    if not user_id or bonus_rub <= 0:
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("""
    UPDATE user_referrals
    SET bonus_balance = bonus_balance + ?, total_earned = total_earned + ?
    WHERE user_id = ?;
    """), (bonus_rub, bonus_rub, user_id))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()

def deduct_referral_bonus(user_id: int, amount_rub: int):
    if not user_id or amount_rub <= 0:
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("""
    UPDATE user_referrals
    SET bonus_balance = CASE WHEN bonus_balance >= ? THEN bonus_balance - ? ELSE 0 END
    WHERE user_id = ?;
    """), (amount_rub, amount_rub, user_id))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()

def get_referrer_for_user(user_id: int) -> Optional[int]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("SELECT referrer_id FROM user_referrals WHERE user_id = ?;"), (user_id,))
    row = cur.fetchone()
    conn.close()
    if row and row["referrer_id"]:
        return int(row["referrer_id"])
    return None

def get_all_bot_users() -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id as \"userId\", username, first_name as \"firstName\" FROM bot_users WHERE is_active = TRUE;")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

# --- ЗАКАЗЫ ---
def create_secure_order(
    buyer_id: Optional[int], 
    buyer_name: str, 
    buyer_username: str, 
    client_items: List[Dict[str, Any]],
    promo_code: str = "",
    use_bonus: int = 0
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if not client_items:
        raise ValueError("корзина пуста")

    conn = get_connection()
    cur = conn.cursor()

    order_code = f"NVX-{int(time.time() * 1000) % 1000000:06d}"
    verified_items = []
    subtotal_rub = 0
    total_count = 0

    for it in client_items:
        prod_id = str(it.get("id"))
        qty = int(it.get("qty", 1))
        if qty <= 0:
            continue

        cur.execute(placeholder("SELECT id, name, price, image_url FROM products WHERE id = ?;"), (prod_id,))
        p = cur.fetchone()
        if not p:
            continue

        actual_price = int(p["price"])
        subtotal = actual_price * qty
        subtotal_rub += subtotal
        total_count += qty

        verified_items.append({
            "product_id": p["id"],
            "name": p["name"],
            "price": actual_price,
            "qty": qty,
            "subtotal": subtotal,
            "img": p["image_url"]
        })

    if not verified_items or subtotal_rub <= 0:
        conn.close()
        raise ValueError("выбранные товары не найдены")

    # расчет скидки по промокоду
    discount_rub = 0
    valid_promo = ""
    if promo_code:
        ok, msg, disc = validate_promo(promo_code, subtotal_rub)
        if ok:
            discount_rub = disc
            valid_promo = promo_code.strip().upper()

    # расчет бонусов
    actual_bonus_used = 0
    if buyer_id and use_bonus > 0:
        cur.execute(placeholder("SELECT bonus_balance FROM user_referrals WHERE user_id = ?;"), (buyer_id,))
        b_row = cur.fetchone()
        available_bonus = b_row["bonus_balance"] if b_row else 0
        max_bonus_possible = max(0, subtotal_rub - discount_rub - 1)
        actual_bonus_used = min(available_bonus, use_bonus, max_bonus_possible)

    final_total_rub = max(1, subtotal_rub - discount_rub - actual_bonus_used)

    # запись заказа в бд
    if IS_POSTGRES:
        cur.execute("""
        INSERT INTO orders (order_code, buyer_id, buyer_name, buyer_username, total_rub, total_count, status, discount_rub, promo_code, bonus_used)
        VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s) RETURNING id;
        """, (order_code, buyer_id, buyer_name, buyer_username, final_total_rub, total_count, discount_rub, valid_promo, actual_bonus_used))
        order_db_id = cur.fetchone()["id"]
    else:
        cur.execute("""
        INSERT INTO orders (order_code, buyer_id, buyer_name, buyer_username, total_rub, total_count, status, discount_rub, promo_code, bonus_used)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?);
        """, (order_code, buyer_id, buyer_name, buyer_username, final_total_rub, total_count, discount_rub, valid_promo, actual_bonus_used))
        order_db_id = cur.lastrowid

    # запись позиций заказа
    for vi in verified_items:
        cur.execute(placeholder("""
        INSERT INTO order_items (order_id, product_id, product_name, price, qty, subtotal)
        VALUES (?, ?, ?, ?, ?, ?);
        """), (order_db_id, vi["product_id"], vi["name"], vi["price"], vi["qty"], vi["subtotal"]))

    if not IS_POSTGRES:
        conn.commit()
    conn.close()

    order_data = {
        "orderId": order_code,
        "dbId": order_db_id,
        "buyerId": buyer_id,
        "buyerName": buyer_name,
        "buyerUsername": buyer_username,
        "subtotalRub": subtotal_rub,
        "discountRub": discount_rub,
        "bonusUsed": actual_bonus_used,
        "totalRub": final_total_rub,
        "totalCount": total_count,
        "items": verified_items,
        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    return order_data, verified_items

def get_order(order_code: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("""
    SELECT id, order_code as "orderCode", buyer_id as "buyerId", buyer_name as "buyerName", 
           buyer_username as "buyerUsername", total_rub as "totalRub", total_count as "totalCount", 
           status, payment_method as "paymentMethod", payment_id as "paymentId", payment_url as "paymentUrl", 
           discount_rub as "discountRub", promo_code as "promoCode", bonus_used as "bonusUsed", 
           delivered_keys as "deliveredKeys", created_at as "createdAt"
    FROM orders WHERE order_code = ?;
    """), (order_code,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    order_data = dict(row)
    
    cur.execute(placeholder("""
    SELECT product_id as "productId", product_name as "name", price, qty, subtotal
    FROM order_items WHERE order_id = ?;
    """), (order_data["id"],))
    order_data["items"] = [dict(r) for r in cur.fetchall()]
    conn.close()
    return order_data

def get_user_orders(buyer_id: int) -> List[Dict[str, Any]]:
    if not buyer_id:
        return []
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("""
    SELECT id, order_code as "orderCode", total_rub as "totalRub", total_count as "totalCount", 
           status, payment_method as "paymentMethod", delivered_keys as "deliveredKeys", created_at as "createdAt"
    FROM orders WHERE buyer_id = ? ORDER BY id DESC LIMIT 50;
    """), (buyer_id,))
    orders = [dict(r) for r in cur.fetchall()]
    
    for o in orders:
        cur.execute(placeholder("SELECT product_name as \"name\", price, qty, subtotal FROM order_items WHERE order_id = ?;"), (o["id"],))
        o["items"] = [dict(r) for r in cur.fetchall()]
        if o.get("deliveredKeys"):
            try:
                o["deliveredKeys"] = json.loads(o["deliveredKeys"])
            except Exception:
                pass
                
    conn.close()
    return orders

def update_order_payment(order_code: str, payment_method: str, payment_id: str = "", payment_url: str = "", status: str = "pending") -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("""
    UPDATE orders 
    SET payment_method = ?, payment_id = ?, payment_url = ?, status = ?
    WHERE order_code = ?;
    """), (payment_method, payment_id, payment_url, status, order_code))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return True

def mark_order_paid(order_code: str, payment_id: Optional[str] = None) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    if payment_id:
        cur.execute(placeholder("""
        UPDATE orders SET status = 'paid', payment_id = ? WHERE order_code = ?;
        """), (payment_id, order_code))
    else:
        cur.execute(placeholder("""
        UPDATE orders SET status = 'paid' WHERE order_code = ?;
        """), (order_code,))
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return True

# --- НАСТРОЙКИ ---
def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(placeholder("SELECT value FROM settings WHERE key = ?;"), (key,))
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0] if isinstance(row, (tuple, list)) else row["value"]
    return default

def set_setting(key: str, value: str):
    conn = get_connection()
    cur = conn.cursor()
    if IS_POSTGRES:
        cur.execute("""
        INSERT INTO settings (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, (key, value))
    else:
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?);", (key, value))
        conn.commit()
    conn.close()

# инициализация базы данных
init_db()
