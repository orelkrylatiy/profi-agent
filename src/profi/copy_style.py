"""Style guardrails and A/B/C variants for client-facing Profi messages.

The experiment tests message structure, not fake typos or cosmetic punctuation.
Each order is assigned one stable variant in SQLite before generation.
"""

from __future__ import annotations

import random
import re
from collections.abc import Sequence

OUTREACH_EXPERIMENT_ID = "outreach_offer_v1"
OUTREACH_VARIANT_IDS = ("A", "B", "C")
OUTREACH_EXPERIMENT_MARKER = "OUTREACH_EXPERIMENT="

OUTREACH_STYLE_OVERRIDE = (
    "ФИНАЛЬНЫЙ СТИЛЬ ОТКЛИКА (эти правила важнее общих пожеланий выше): "
    "пиши как одно короткое сообщение в чате, не как мини-презентацию. "
    "Нужен конкретный оффер, а не глубокая персонализация. Обычно достаточно "
    "предмета или основной цели клиента; не вытягивай из заявки редкие детали "
    "ради эффекта. Не пересказывай заявку. Не демонстрируй экспертность "
    "английскими фразами, названиями учебников, методик или buzzword-ами. "
    "Обычно 2–4 предложения и примерно 160–320 символов; 500 — только потолок. "
    "Онлайн, 60–90 минут, методика и пробное НЕ обязаны одновременно появляться "
    "в каждом сообщении. Один вопросительный знак максимум. "
    "Не добавляй нарочно опечатки, ошибки или улыбки ради «человечности». "
)

OUTREACH_VARIANTS: dict[str, str] = {
    "A": (
        "ВАРИАНТ A — DIRECT OFFER. Начни с прямого предложения помощи: "
        "«Могу помочь с ...» или естественного эквивалента. Следующей фразой "
        "предложи простой первый шаг, обычно пробное занятие. Закончи одним "
        "вопросом про удобное время. Не объясняй всю методику."
    ),
    "B": (
        "ВАРИАНТ B — DIAGNOSTIC. Сначала прямо скажи, что можешь помочь. Затем "
        "конкретно предложи первое занятие как короткую диагностику: посмотреть "
        "текущий уровень/что уже получается и после этого определить приоритет. "
        "Закончи одним вопросом. Не добавляй другие детали только ради персонализации."
    ),
    "C": (
        "ВАРИАНТ C — COMPACT NEXT STEP. Сделай самый короткий нормальный оффер: "
        "предложи помощь, при необходимости дай только один действительно полезный "
        "факт (например, что работаешь онлайн), и сразу предложи следующий шаг. "
        "Один вопрос в конце. Никакой мини-презентации и демонстрации знаний."
    ),
}

CHAT_STYLE_OVERRIDE = (
    "ФИНАЛЬНЫЙ СТИЛЬ ЧАТА: сначала ответь на последний прямой вопрос клиента. "
    "Потом максимум одна короткая фраза про следующий шаг. Не повторяй "
    "самопрезентацию и методику из первого сообщения. Обычно хватает 1–3 "
    "предложений и одного вопроса. Если клиент спросил цену, формат или время, "
    "дай факт в первой фразе без вступления. "
)

# Patterns observed in real outreach examples. They trigger one best-effort
# rewrite attempt, never a terminal business decision.
_AIISH_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bзадач[аи]\s+(?:понятн|ясн)\w*", re.I),
        "мета-фраза «задача понятна»",
    ),
    (
        re.compile(r"\bвс[её]\s+(?:понятн|ясн)\w*", re.I),
        "мета-фраза «всё понятно»",
    ),
    (
        re.compile(r"\bпонял[аи]?\s+ваш\s+приоритет\b", re.I),
        "пересказ «поняла ваш приоритет»",
    ),
    (
        re.compile(r"\bхорошая\s+база\s+для\b", re.I),
        "оценочный пересказ уровня",
    ),
    (
        re.compile(r"\bзначит\s+уже\s+есть\s+база\b", re.I),
        "шаблонный вывод из уровня",
    ),
    (
        re.compile(r"\bсамое\s+время\s+начать\b", re.I),
        "рекламный штамп «самое время»",
    ),
    (
        re.compile(r"\bпоэтому\s+на\s+занятиях\b", re.I),
        "шаблонный переход к методике",
    ),
    (
        re.compile(r"\bформат\s+дистанционн\w*", re.I),
        "канцелярское «формат дистанционный»",
    ),
    (re.compile(r"\bstep\s+by\s+step\b", re.I), "AI-штамп step by step"),
    (re.compile(r"\bшаг\s+за\s+шагом\b", re.I), "AI-штамп «шаг за шагом»"),
    (re.compile(r"\bзакрыва\w*\s+пробел", re.I), "шаблон «закрываем пробелы»"),
)


def outreach_variant_prompt(variant: str) -> str:
    """Return the exact versioned prompt suffix for an assigned experiment arm."""
    if variant not in OUTREACH_VARIANTS:
        raise ValueError(f"unknown outreach prompt variant: {variant!r}")
    return (
        OUTREACH_STYLE_OVERRIDE
        + f"{OUTREACH_EXPERIMENT_MARKER}{OUTREACH_EXPERIMENT_ID}; VARIANT={variant}. "
        + OUTREACH_VARIANTS[variant]
        + " "
    )


def client_copy_issues(text: str, *, channel: str = "outreach") -> list[str]:
    """Return style issues worth one cheap regeneration attempt."""
    text = str(text or "").strip()
    issues: list[str] = []

    preferred_max = 360 if channel == "outreach" else 450
    if len(text) > preferred_max:
        issues.append(f"слишком длинно ({len(text)} > {preferred_max})")
    if text.count("?") > 1:
        issues.append("больше одного вопроса")
    if "—" in text:
        issues.append("длинное тире")

    for pattern, label in _AIISH_PATTERNS:
        if pattern.search(text):
            issues.append(label)

    return issues


def style_retry_instruction(issues: Sequence[str]) -> str:
    """Feedback appended only after a draft failed the style check."""
    short = "; ".join(str(issue) for issue in issues[:5])
    return (
        " Предыдущий черновик отклонён только по стилю: "
        + short
        + ". Перепиши с нуля, сохрани факты и ТОТ ЖЕ экспериментальный вариант. "
        "Ничего нового не придумывай. Сделай конкретный оффер, короче и проще, "
        "максимум один вопрос. Глубокая персонализация не нужна."
    )


_CHAT_SHAPES = (
    (
        "Вариант композиции чата: ответ на вопрос клиента -> один следующий "
        "шаг. Без повторной презентации себя."
    ),
    (
        "Вариант композиции чата: если хватает одной фразы и вопроса, так и "
        "ответь. Не раздувай сообщение."
    ),
    ("Вариант композиции чата: факт/решение сначала, затем один вариант следующего шага."),
)


def style_variation(channel: str = "chat") -> str:
    """Small chat-only variation; outreach variants stay fixed for clean experiments."""
    if channel != "chat":
        return ""
    shape = random.choice(_CHAT_SHAPES)
    if random.random() < 0.12:
        casual = (
            " Лёгкая «)» допустима только если сама естественно просится; специально не добавляй."
        )
    else:
        casual = " Улыбку специально не добавляй."
    return shape + casual + " "
