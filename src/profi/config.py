"""Конфигурация воркера Контур A.

Наружные настройки — .env в корне проекта (шаблон: .env.example), плюс
переопределение на запуск через переменные окружения (launchd, accounts/<acc>.env,
ручные прогоны). Приоритет: окружение процесса > .env > profile > дефолт здесь.
Постоянные политики (гейты, ритм, URL) — литералами ниже, снаружи не меняются.
"""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

from profi.profiles import load_profile

PROJECT_DIR = Path(__file__).resolve().parents[2]  # src/profi/config.py → корень репо


def _load_env_file() -> dict[str, str]:
    """KEY=VALUE из корневого .env (тот же файл, что читает llm/client.py)."""
    env: dict[str, str] = {}
    path = PROJECT_DIR / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip("'\"")
    return env


_ENVFILE = _load_env_file()


def _get(name: str, default: str | None = None) -> str | None:
    """Приоритет: окружение процесса > .env > default. Пустая строка = не задано."""
    v = os.environ.get(name)
    if not v:
        v = _ENVFILE.get(name)
    return v if v else default


DATA_DIR = PROJECT_DIR / "data"
LOG_DIR = PROJECT_DIR / "logs"
DB_PATH = Path(_get("PROFI_DB", str(DATA_DIR / "profi.db")))

# --- Разделение нескольких акков на одной машине: свой лог и лок ---
# PROFI_LOG_TAG задаётся в accounts/<акк>.env; пустой = старые имена файлов.
LOG_TAG = _get("PROFI_LOG_TAG", "").strip()
WORKER_LOG = LOG_DIR / (f"worker-{LOG_TAG}.log" if LOG_TAG else "worker.log")
AUTOPILOT_LOG = LOG_DIR / (f"autopilot-{LOG_TAG}.log" if LOG_TAG else "autopilot.log")
AUTOPILOT_LOCK = DATA_DIR / (f"{LOG_TAG}.autopilot.lock" if LOG_TAG else "autopilot.lock")

# Production account workers на VPS маркируются PROFI_RHYTHM_TAG. Внешний
# run_account.sh и внутренний restart из autopilot обязаны использовать один
# и тот же lifetime-lock, иначе после первой платной отправки worker мог быть
# поднят уже без singleton-защиты.
RHYTHM_TAG = os.environ.get("PROFI_RHYTHM_TAG", "").strip()
WORKER_LOCK = DATA_DIR / (f"{RHYTHM_TAG}.worker.lock" if RHYTHM_TAG else "worker.lock")
if RHYTHM_TAG and shutil.which("flock") and not os.environ.get("PROFI_WORKER_START_CMD"):
    _project_q = shlex.quote(str(PROJECT_DIR))
    _lock_q = shlex.quote(str(WORKER_LOCK))
    _tag_q = shlex.quote(RHYTHM_TAG)
    _log_q = shlex.quote(str(WORKER_LOG))
    os.environ["PROFI_WORKER_START_CMD"] = (
        f"cd {_project_q} && nohup flock -w 15 {_lock_q} "
        f"env PROFI_RHYTHM_TAG={_tag_q} uv run python -m profi.main "
        f"--rhythm-tag {_tag_q} >> {_log_q} 2>&1 &"
    )

# Файл-сигнал «идёт платная отправка»: нужен legacy-autopilot при rollback
# PROFI_FAST_PATH=0. В fast-path свежий заказ обрабатывает сам worker.
SEND_PAUSE_FILE = DATA_DIR / (f"{LOG_TAG}.send-pause" if LOG_TAG else "send-pause")

# Файл-пауза «LLM у провайдера на лимите». Fresh fast-path продолжает читать
# ленту и использует profile fallback; legacy-autopilot/чаты LLM не вызывают.
LLM_COOLDOWN_FILE = DATA_DIR / (f"{LOG_TAG}.llm-cooldown" if LOG_TAG else "llm-cooldown")

# --- Business profile: оффер отдельно от конкретного аккаунта ---
PROFILE_DIR = PROJECT_DIR / "profiles"
_legacy_persona = _get("PROFI_PERSONA", "info")
_explicit_profile = _get("PROFI_PROFILE")
_legacy_profile = {"info": "info", "lang": "languages"}.get(_legacy_persona)
PROFILE_NAME = _explicit_profile or _legacy_profile

# Явный PROFI_PROFILE fail-closed: опечатка не должна молча переключить предмет.
# Для неизвестной legacy persona сохраняем старый режим без profile.
PROFILE = load_profile(PROFILE_NAME, PROFILE_DIR) if PROFILE_NAME else None

# Старые переменные остаются override'ами для плавной миграции account env.
PERSONA = _get("PROFI_PERSONA", PROFILE.persona if PROFILE else _legacy_persona)
PERSONA_DIR = PROJECT_DIR / "personas"
_subjects_default = ",".join(PROFILE.subject_keywords) if PROFILE else "информатик,программирован"
SUBJECT_KEYWORDS = [
    s.strip() for s in _get("PROFI_SUBJECTS", _subjects_default).split(",") if s.strip()
]
_stop_default = ",".join(PROFILE.stop_patterns) if PROFILE else ""
PROFILE_FALLBACK_ENABLED = PROFILE.fallback_enabled if PROFILE else False
PROFILE_FALLBACK_TEMPLATES = list(PROFILE.fallback_templates) if PROFILE else []

# --- Chrome (правило: один аккаунт = один user-data-dir, свой CDP-порт) ---
# 1 = Chrome сами не запускаем: нет CDP — BROWSER_OFFLINE и ждём. 0 = auto-launch.
CHROME_NO_LAUNCH = _get("PROFI_CHROME_NO_LAUNCH", "0") == "1"
CHROME_PATH = _get(
    "PROFI_CHROME_PATH",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
_profile = _get("PROFI_CHROME_PROFILE")
USER_DATA_DIR = Path(_profile) if _profile else PROJECT_DIR / "data" / "chrome-profiles" / "main"
if not USER_DATA_DIR.is_absolute():
    USER_DATA_DIR = PROJECT_DIR / USER_DATA_DIR
CDP_PORT = int(_get("PROFI_CDP_PORT", "9333"))

FEED_URL = "https://profi.ru/backoffice/n.php"
FEED_HOST = "profi.ru"
FEED_PATH = "/backoffice/n.php"

# --- Ритм цикла ---
# 45–60 с = ~6.7 запроса/5мин; при 401/403 — cooldown.
RELOAD_INTERVAL_MIN_S = int(_get("PROFI_RELOAD_MIN", "45"))
RELOAD_INTERVAL_MAX_S = int(_get("PROFI_RELOAD_MAX", "60"))
CAPTURE_WINDOW_S = 8.0
CAPTURE_EXTRA_S = 3.0
AUTH_WAIT_S = 30
AUTH_COOLDOWN_S = 30 * 60

# --- Hard filters (до LLM) ---
MIN_RATE = None
VACANCY_PATTERNS = ["ваканс"]
SPECIAL_NEEDS_PATTERNS = [
    "сдвг",
    "adhd",
    "аутиз",
    "аутичн",
    "аутист",
    "зпр",
    "дислекси",
    "дисграфи",
    "овз",
    "дцп",
]
BARTER_PATTERNS = [
    "бартер",
    "обмен урок",
    "обмен услуг",
    "взаимозачёт",
    "взаимозачет",
    "бесплатн",
]
# Очные занятия — не наш формат (решение Макса 04.09). Regex со словесной
# границей, а не подстрока: \bочн… ловит «очно/очных/очные/очная»,
# но НЕ «заочно» («учусь заочно, нужна помощь» — наш заказ).
ONSITE_PATTERNS = [r"\bочн[а-яё]*"]
STOP_PATTERNS = [
    s.strip().lower() for s in _get("PROFI_STOP_PATTERNS", _stop_default).split(",") if s.strip()
]
REMOTE_ONLY = PROFILE.remote_only if PROFILE else True

# --- Денежные предохранители ---
MAX_RESPONSE_PRICE_RUB = int(_get("PROFI_MAX_RESPONSE_PRICE", "500"))
DAILY_SEND_LIMIT = int(_get("PROFI_DAILY_SEND_LIMIT", "0"))
MAX_COMPETITION_POSITION = int(_get("PROFI_MAX_POSITION", "20"))
RATE = 2000

# --- Тариф отклика ---
RESPOND_MODE = _get("PROFI_RESPOND_MODE", "pay").strip().lower()
if RESPOND_MODE not in {"pay", "commission"}:
    raise RuntimeError(
        f"невалидный PROFI_RESPOND_MODE={RESPOND_MODE!r}; разрешены только 'pay' или 'commission'"
    )


# --- Рабочие часы: локальное время, [lo, hi) ---
def _parse_work_hours(v: str | None) -> tuple[int, int]:
    if not v or "," not in v:
        return (8, 23)
    lo, _, hi = v.partition(",")
    try:
        return (max(0, int(lo.strip())), min(24, int(hi.strip())))
    except ValueError:
        return (8, 23)


WORK_HOURS = _parse_work_hours(_get("PROFI_WORK_HOURS"))

LOG_LEVEL = _get("PROFI_LOG_LEVEL", "INFO")

# --- Чаты в цикле воркера ---
CHAT_CHECK_EVERY_CYCLES = int(_get("PROFI_CHAT_EVERY", "3"))

# --- Кандидаты и детали ---
# Default-on: свежий заказ проходит details -> decision -> send в той же вкладке.
# 0 = быстрый rollback к старому details-only worker + отдельному autopilot.
FAST_PATH_ENABLED = _get("PROFI_FAST_PATH", "1") != "0"
AUTO_CREATE_CANDIDATES = True
AUTO_LOAD_DETAILS = True
