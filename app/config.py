import os

BOT_TOKEN = os.environ["BOT_TOKEN"]

DB_PATH = os.getenv("DB_PATH", "data.db")

# как часто бот проверяет ВСЕ товары (в минутах)
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))

# чтобы не долбить сайты: сколько одновременных запросов максимум
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "5"))

USER_AGENT = os.getenv(
    "USER_AGENT",
    "PriceWatcherBot/0.1 (respect robots; personal use)"
)
