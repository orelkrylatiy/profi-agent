"""Конфигурация воркера Контур A.

Всё, что обычно приходится менять, — здесь.
Секреты (LLM-ключ) позже пойдут в .env, в коде их не хранить.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
LOG_DIR = PROJECT_DIR / "logs"
DB_PATH = DATA_DIR / "profi.db"

# --- Chrome (правило: один аккаунт = один user-data-dir, свой CDP-порт) ---
CHROME_PATH = os.environ.get(
    "PROFI_CHROME_PATH",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
USER_DATA_DIR = Path(
    os.environ.get("PROFI_CHROME_PROFILE", str(PROJECT_DIR / "data" / "chrome-profiles" / "main"))
)
CDP_PORT = int(os.environ.get("PROFI_CDP_PORT", "9333"))

FEED_URL = "https://profi.ru/backoffice/n.php"
FEED_HOST = "profi.ru"
FEED_PATH = "/backoffice/n.php"

# --- Ритм цикла ---
# Рекон 2026-08-30: ~10 одинаковых запросов за 5 мин = мягкий 403.
# Рабочий интервал 90–120 с, при 401/403 — пауза 30–60 мин.
RELOAD_INTERVAL_MIN_S = 90
RELOAD_INTERVAL_MAX_S = 120
CAPTURE_WINDOW_S = 8.0   # сколько ждём первый BoSearchBoardItems после reload
CAPTURE_EXTRA_S = 3.0    # сколько ещё собираем повторы после первого пойманного
AUTH_WAIT_S = 30         # период проверки, пока ждём ручной логин
AUTH_COOLDOWN_S = 30 * 60  # пауза после 401/403

# --- Hard filters (до LLM). Настройки под цель: ЕГЭ/ОГЭ информатика, дистанционно ---
# Подстроки в title+description (без учёта регистра).
SUBJECT_KEYWORDS = ["информатик", "программирован"]
MIN_RATE = None          # 2026-08-31: фильтр по цене ВЫКЛЮЧЕН владельцем (вход на площадку, берём любые бюджеты)
VACANCY_PATTERNS = ["ваканс"]
REMOTE_ONLY = True        # geo.remote пуст → только очно → skip

# --- Денежные предохранители (RULES.md §2; ревью P0-2) ---
MAX_RESPONSE_PRICE_RUB = 500   # отклик дороже — отмена отправки
DAILY_SEND_LIMIT = 3           # платных отправок за сутки максимум
RATE = 2000                    # ставка ₽/час в форме отклика (RULES: менять здесь)

LOG_LEVEL = os.environ.get("PROFI_LOG_LEVEL", "INFO")

# --- Кандидаты и детали (спека §16, §19-22) ---
# v0.5: кандидат создаётся по PASS hard-фильтров, LLM-триаж подключается на M3
AUTO_CREATE_CANDIDATES = True
AUTO_LOAD_DETAILS = True
