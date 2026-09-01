import os
import time
from typing import List, Dict, Any, Optional, Tuple

# проверяем наличие postgres url
DB_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
IS_POSTGRES = bool(DB_URL and ("postgres://" in DB_URL or "postgresql://" in DB_URL))

if IS_POSTGRES:
    # заменяем старый префикс если нужно
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
    # меняет ? на %s для postgres
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

    # создаем корневую категорию если пусто
    cur.execute("SELECT COUNT(*) as cnt FROM categories;")
    res = cur.fetchone()
    count = res["cnt"] if (isinstance(res, dict) or hasattr(res, "keys")) else res[0]
    if count == 0:
        cur.execute(placeholder("INSERT INTO categories (id, name, icon_key, sort_order) VALUES (?, ?, ?, ?);"), ('all', 'Все товары', 'all', 0))

    if not IS_POSTGRES:
        conn.commit()
    conn.close()

# работа с категориями
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

# работа с товарами
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
    conn.close()
    return dict(row) if row else None

def create_product(name: str, category_id: str, price: int, old_price: int, badge: str, image_url: str, description: str) -> Dict[str, Any]:
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
        "desc": description
    }

def update_product(prod_id: str, name: str, category_id: str, price: int, old_price: int, badge: str, image_url: str, description: str) -> Optional[Dict[str, Any]]:
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
    if not IS_POSTGRES:
        conn.commit()
    conn.close()
    return True

# расчет и сохранение заказа
def create_secure_order(buyer_id: Optional[int], buyer_name: str, buyer_username: str, client_items: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if not client_items:
        raise ValueError("корзина пуста")

    conn = get_connection()
    cur = conn.cursor()

    order_code = f"NVX-{int(time.time() * 1000) % 1000000:06d}"
    verified_items = []
    total_rub = 0
    total_count = 0

    for it in client_items:
        prod_id = str(it.get("id"))
        qty = int(it.get("qty", 1))
        if qty <= 0:
            continue

        # берем актуальную цену прямо из базы
        cur.execute(placeholder("SELECT id, name, price, image_url FROM products WHERE id = ?;"), (prod_id,))
        p = cur.fetchone()
        if not p:
            continue

        actual_price = int(p["price"])
        subtotal = actual_price * qty
        total_rub += subtotal
        total_count += qty

        verified_items.append({
            "product_id": p["id"],
            "name": p["name"],
            "price": actual_price,
            "qty": qty,
            "subtotal": subtotal,
            "img": p["image_url"]
        })

    if not verified_items or total_rub <= 0:
        conn.close()
        raise ValueError("выбранные товары не найдены")

    # запись заказа в бд
    if IS_POSTGRES:
        cur.execute("""
        INSERT INTO orders (order_code, buyer_id, buyer_name, buyer_username, total_rub, total_count, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'pending') RETURNING id;
        """, (order_code, buyer_id, buyer_name, buyer_username, total_rub, total_count))
        order_db_id = cur.fetchone()["id"]
    else:
        cur.execute("""
        INSERT INTO orders (order_code, buyer_id, buyer_name, buyer_username, total_rub, total_count, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending');
        """, (order_code, buyer_id, buyer_name, buyer_username, total_rub, total_count))
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
        "totalRub": total_rub,
        "totalCount": total_count,
        "items": verified_items,
        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    return order_data, verified_items

# сохранение и чтение настроек
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

# инициализируем базу данных
init_db()
