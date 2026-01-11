import aiosqlite
import datetime as dt

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL,
  url TEXT NOT NULL,
  label TEXT,
  last_price REAL,
  last_checked_at TEXT,
  is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS price_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sub_id INTEGER NOT NULL,
  price REAL NOT NULL,
  ts TEXT NOT NULL,
  FOREIGN KEY(sub_id) REFERENCES subscriptions(id)
);
"""

async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)
        await db.commit()

async def add_sub(db_path: str, chat_id: int, url: str, label: str | None) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "INSERT INTO subscriptions(chat_id,url,label) VALUES(?,?,?)",
            (chat_id, url, label),
        )
        await db.commit()
        return cur.lastrowid

async def list_subs(db_path: str, chat_id: int):
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT id,url,label,last_price,last_checked_at,is_active FROM subscriptions WHERE chat_id=? ORDER BY id DESC",
            (chat_id,),
        )
        return await cur.fetchall()

async def remove_sub(db_path: str, chat_id: int, sub_id: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "UPDATE subscriptions SET is_active=0 WHERE chat_id=? AND id=?",
            (chat_id, sub_id),
        )
        await db.commit()
        return cur.rowcount > 0

async def get_active_subs(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT id,chat_id,url,label,last_price FROM subscriptions WHERE is_active=1"
        )
        return await cur.fetchall()

async def save_price(db_path: str, sub_id: int, price: float):
    now = dt.datetime.utcnow().isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO price_history(sub_id,price,ts) VALUES(?,?,?)",
            (sub_id, price, now),
        )
        await db.execute(
            "UPDATE subscriptions SET last_price=?, last_checked_at=? WHERE id=?",
            (price, now, sub_id),
        )
        await db.commit()

async def get_history(db_path: str, chat_id: int, sub_id: int, limit: int = 5):
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            """
            SELECT ph.price, ph.ts
            FROM price_history ph
            JOIN subscriptions s ON s.id=ph.sub_id
            WHERE s.chat_id=? AND s.id=?
            ORDER BY ph.id DESC
            LIMIT ?
            """,
            (chat_id, sub_id, limit),
        )
        return await cur.fetchall()
