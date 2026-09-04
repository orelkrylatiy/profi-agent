# Бэклог profi-agent

> Обновлён 04.09.2026. Текущий основной flow: fast-path — свежий заказ
> открывается один раз, full gates + LLM/fallback + отправка идут в той же
> вкладке. На Windows один supervisor на аккаунт держит живыми Chrome + worker.

## Сделано 03–04.09

- [x] **Fast-path**: `feed → order → details → full gates → LLM/fallback → send`
  в одной открытой карточке; старый autopilot при `PROFI_FAST_PATH=1` no-op.
- [x] **Profile fallback при проблеме LLM**: acquisition не останавливается из-за
  LLM cooldown/лимита; безопасный шаблон выбирается из business-profile после
  детерминированных гейтов. Нормальный LLM verdict `skip` fallback не переопределяет.
- [x] **Защита от дублей**: atomic `draft=generating`, `send=sending`; terminal
  `sent/unknown/skipped/failed`, фонового reopen/retry свежего заказа нет.
- [x] **Два ключа z.ai**: свой ключ на аккаунт + взаимный fallback провайдера.
- [x] **`PROFI_CHROME_NO_LAUNCH=1` у worker**: Python business-process сам Chrome
  не стартует. Владение браузером вынесено наружу, чтобы не повторять инцидент
  с захватом чужого/занятого профиля.
- [x] **referer при прямой навигации** на заказ (`orders.py`): устранил 45-с
  tarpit/timeout на `n.php?o=…`.
- [x] **Windows Chrome supervisor**: `scripts/account/supervise-win.ps1` проверяет
  `/json/version`, поднимает exact profile+CDP, перезапускает managed Chrome при
  устойчивом dead-CDP и fail-closed ждёт, если профиль занят foreign Chrome.
- [x] **Windows worker supervisor**: тот же процесс перезапускает worker при падении;
  `start-win.ps1` идемпотентен, `stop-win.ps1 -Account <acc>` останавливает owner
  перед children, чтобы не было respawn-race. Chrome при stop намеренно остаётся.
- [x] **Windows rollback compatibility**: отдельный 120-с autopilot-loop запускается
  только при явном `PROFI_FAST_PATH=0`.

## Бэклог

### 1. Наблюдаемость fast-path на реальном трафике
После выката сравнить с до-fast-path периодом:
- time-to-send;
- `OPEN_FAIL`, `tab_hygiene`, `BROWSER_OFFLINE`;
- `sent / unknown / failed`;
- `draft_source=llm|fallback`;
- конверсию LLM vs fallback и по профилям.

### 2. Windows supervisor: эксплуатационная проверка
Unit/static tests закрывают policy и PowerShell parsing, но после merge нужен
реальный smoke на Windows:
- запустить `start-win -Account <acc>` дважды → один supervisor;
- закрыть managed Chrome → тот же profile+port поднимается автоматически;
- убить worker → worker возвращается;
- вручную открыть тот же profile без ожидаемого CDP → supervisor не должен его убить,
  только `PROFILE_IN_USE_NO_CDP` в `logs/supervisor-<acc>.log`.

### 3. thinking-токены glm-5.3-flash
Модель по anthropic-протоколу отдаёт `thinking` + `text`; размышление ест
`max_tokens`. При росте `LLM/JSON` ошибок проверить обрезание ответа/лимиты.

### 4. Ротация ключей и лимиты
При упоре обоих аккаунтов в лимит добавить третий ключ или перераспределить
модели/квоты. Ключи держать только в локальных `.env`/`accounts/*.env`, не в Git.

### 5. Детектор скрытых заказов
Если карточка загрузилась, но нет ни тарифов, ни CTA, возможно заказ уже скрыт,
даже когда в body нет явного текста «Заказ скрыт». Нужна структурная эвристика,
чтобы считать это clean skip, а не send failure.

### 6. Гигиена репо/процессов
- следить, чтобы в публичный Git не попадали реальные account env, профили браузера,
  cookies, ключи, сырые чаты/заказы;
- старые Mac/VPS legacy-autopilot entrypoints со временем можно удалить после
  подтверждения, что fast-path стабилен в production.
