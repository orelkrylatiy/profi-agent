"""Конфигурация воркера Контур A.

Всё, что обычно приходится менять, — здесь.
Секреты (LLM-ключ) позже пойдут в .env, в коде их не хранить.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]  # src/profi/config.py → корень репо
DATA_DIR = PROJECT_DIR / "data"
LOG_DIR = PROJECT_DIR / "logs"
DB_PATH = Path(os.environ.get("PROFI_DB", str(DATA_DIR / "profi.db")))

# --- Персона (промпт) и фильтры: один аккаунт = одна персона ---
PERSONA = os.environ.get("PROFI_PERSONA", "info")
PERSONA_DIR = PROJECT_DIR / "personas"
SUBJECT_KEYWORDS = [s.strip() for s in os.environ.get(
    "PROFI_SUBJECTS", "информатик,программирован"
).split(",") if s.strip()]

# --- Chrome (правило: один аккаунт = один user-data-dir, свой CDP-порт) ---
CHROME_PATH = os.environ.get(
    "PROFI_CHROME_PATH",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
# Профили браузеров живут внутри проекта (data/browser-profiles/<акк>);
# относительный PROFI_CHROME_PROFILE из accounts/<acc>.env считается от
# PROJECT_DIR, чтобы env-файлы не зависели от расположения проекта.
_profile = os.environ.get("PROFI_CHROME_PROFILE")
USER_DATA_DIR = Path(_profile) if _profile else PROJECT_DIR / "data" / "chrome-profiles" / "main"
if not USER_DATA_DIR.is_absolute():
    USER_DATA_DIR = PROJECT_DIR / USER_DATA_DIR
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
# Подстроки в title+description (без учёта регистра); переопределяется PROFI_SUBJECTS
MIN_RATE = None          # 2026-08-31: фильтр по цене ВЫКЛЮЧЕН владельцем (вход на площадку, берём любые бюджеты)
VACANCY_PATTERNS = ["ваканс"]
REMOTE_ONLY = True        # geo.remote пуст → только очно → skip

# --- Денежные предохранители (RULES.md §2; ревью P0-2) ---
MAX_RESPONSE_PRICE_RUB = 500   # отклик дороже — отмена отправки
DAILY_SEND_LIMIT = 3           # платных отправок за сутки максимум
RATE = 2000                    # ставка ₽/час в форме отклика (RULES: менять здесь)

# --- Тариф отклика (адаптивность: акк может откликаться платно или через комиссию) ---
# PROFI_RESPOND_MODE: "pay" (платный отклик, дефолт) | "commission" (через комиссию Profi)
# При "commission" в блоке тарифов выбирается карточка «Комиссия», если она доступна
# на аккаунте; иначе отправка отменяется с ошибкой (RULES.md §2).
RESPOND_MODE = os.environ.get("PROFI_RESPOND_MODE", "pay").strip().lower()

# Рабочие часы автопилота (часы локального времени, отправка только внутри)
# Норма: (8, 23). 2026-09-01 ночь: (0, 24) — тест полной цепочки по приказу
# владельца («пусть всю ночь работает — проверим как ловит и доводит до отклика»)
WORK_HOURS = (0, 24)

LOG_LEVEL = os.environ.get("PROFI_LOG_LEVEL", "INFO")

# --- Кандидаты и детали (спека §16, §19-22) ---
# v0.5: кандидат создаётся по PASS hard-фильтров, LLM-триаж подключается на M3
AUTO_CREATE_CANDIDATES = True
AUTO_LOAD_DETAILS = True
