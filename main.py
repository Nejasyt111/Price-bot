import asyncio
import json
import re
from bs4 import BeautifulSoup
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command

from app.config import BOT_TOKEN, DB_PATH, CHECK_INTERVAL_MINUTES, MAX_CONCURRENCY, USER_AGENT
from app.db import init_db, add_sub, list_subs, remove_sub, get_active_subs, save_price, get_history


def extract_price_from_jsonld(html: str) -> float | None:
    """
    Очень простой “универсальный” способ:
    ищем schema.org JSON-LD, где есть offers.price.
    На некоторых сайтах (особенно маркетплейсах) может НЕ сработать — тогда добавим сайт-специфичный парсер позже.
    """
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for s in scripts:
        txt = s.get_text(strip=True)
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue

        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            offers = item.get("offers")
            if isinstance(offers, dict):
                price = offers.get("price")
                if price is not None:
                    try:
                        return float(str(price).replace(" ", "").replace(",", "."))
                    except Exception:
                        pass
            if isinstance(offers, list):
                for off in offers:
                    if isinstance(off, dict) and off.get("price") is not None:
                        try:
                            return float(str(off["price"]).replace(" ", "").replace(",", "."))
                        except Exception:
                            pass
    return None


async def fetch_html(url: str) -> str:
    timeout = aiohttp.ClientTimeout(total=20)
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
        async with s.get(url) as r:
            r.raise_for_status()
            return await r.text()


async def checker_loop(bot: Bot):
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    while True:
        subs = await get_active_subs(DB_PATH)

        async def handle_one(row):
            sub_id, chat_id, url, label, last_price = row
            async with sem:
                try:
                    html = await fetch_html(url)
                    price = extract_price_from_jsonld(html)
                    if price is None:
                        return  # пока молча (чтобы не спамить), позже можно слать “не смог прочитать цену”
                    old = float(last_price) if last_price is not None else None

                    await save_price(DB_PATH, sub_id, price)

                    # Уведомляем ТОЛЬКО если цена стала ниже
                    if old is not None and price < old:
                        diff = old - price
                        pct = (diff / old * 100.0) if old else 0.0
                        name = label or url
                        await bot.send_message(
                            chat_id,
                            f"📉 Цена снизилась!\n"
                            f"{name}\n"
                            f"Было: {old:.2f}\n"
                            f"Стало: {price:.2f}\n"
                            f"Снижение: -{diff:.2f} (-{pct:.1f}%)\n"
                            f"Ссылка: {url}"
                        )
                except Exception:
                    # не падаем из-за одного товара/сайта
                    return

        await asyncio.gather(*(handle_one(r) for r in subs))

        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)


async def main():
    await init_db(DB_PATH)

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def start(m: Message):
        await m.answer(
            "Привет! Я слежу за ценой по ссылке и пишу, когда цена стала НИЖЕ.\n\n"
            "Команды:\n"
            "/add <ссылка> [название]\n"
            "/add_sku <ozon|wb|site> <артикул> (помогу открыть поиск)\n"
            "/list\n"
            "/remove <id>\n"
            "/price <id>\n"
        )

    @dp.message(Command("add"))
    async def add_cmd(m: Message):
        parts = m.text.split(maxsplit=2)
        if len(parts) < 2:
            await m.answer("Пример: /add https://... Куртка Lacoste")
            return
        url = parts[1].strip()
        label = parts[2].strip() if len(parts) >= 3 else None
        sub_id = await add_sub(DB_PATH, m.chat.id, url, label)
        await m.answer(f"✅ Добавил. ID = {sub_id}\nЯ напишу, когда цена станет ниже.")

    @dp.message(Command("add_sku"))
    async def add_sku_cmd(m: Message):
        parts = m.text.split(maxsplit=2)
        if len(parts) < 3:
            await m.answer("Пример: /add_sku ozon 123456\nИли: /add_sku wb 123456")
            return
        source = parts[1].strip().lower()
        sku = parts[2].strip()

        # безопасно: не парсим поиск, а просто даём ссылку на поиск,
        # а ты выбираешь товар и кидаешь мне ссылку через /add
        if source == "ozon":
            search_url = f"https://www.ozon.ru/search/?text={sku}"
        elif source == "wb":
            search_url = f"https://www.wildberries.ru/catalog/0/search.aspx?search={sku}"
        else:
            search_url = f"(для сайтов одежды лучше сразу копировать ссылку товара)"

        await m.answer(
            "Ок. Самый надёжный способ:\n"
            "1) Открой поиск по ссылке ниже\n"
            "2) Найди нужный товар\n"
            "3) Открой товар → Поделиться → Копировать ссылку\n"
            "4) Пришли мне: /add <ссылка> [название]\n\n"
            f"Ссылка на поиск: {search_url}"
        )

    @dp.message(Command("list"))
    async def list_cmd(m: Message):
        rows = await list_subs(DB_PATH, m.chat.id)
        if not rows:
            await m.answer("Список пуст. Добавь товар: /add <ссылка>")
            return
        lines = []
        for (sid, url, label, last_price, last_checked_at, is_active) in rows:
            if not is_active:
                continue
            name = label or url
            price_txt = f"{float(last_price):.2f}" if last_price is not None else "—"
            lines.append(f"{sid}) {name}\n   цена: {price_txt}\n   проверка: {last_checked_at or '—'}")
        await m.answer("\n\n".join(lines))

    @dp.message(Command("remove"))
    async def remove_cmd(m: Message):
        parts = m.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            await m.answer("Пример: /remove 3")
            return
        ok = await remove_sub(DB_PATH, m.chat.id, int(parts[1]))
        await m.answer("✅ Удалил." if ok else "Не нашёл такой ID.")

    @dp.message(Command("price"))
    async def price_cmd(m: Message):
        parts = m.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            await m.answer("Пример: /price 3")
            return
        sub_id = int(parts[1])
        hist = await get_history(DB_PATH, m.chat.id, sub_id, limit=5)
        if not hist:
            await m.answer("Истории пока нет (бот ещё не успел проверить).")
            return
        txt = "\n".join([f"{p:.2f} — {ts}" for (p, ts) in hist])
        await m.answer("Последние цены:\n" + txt)

    # запускаем проверялку отдельной задачей
    asyncio.create_task(checker_loop(bot))

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
