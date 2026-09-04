"""Style guardrails for client-facing Profi messages.

The goal is not to "beat" AI detectors. It is to keep outreach useful and
message-like: a concrete offer, a simple first step, and one next action.
"""

from __future__ import annotations

import random
import re
from collections.abc import Sequence

OUTREACH_STYLE_OVERRIDE = (
    "ФИНАЛЬНЫЙ СТИЛЬ ОТКЛИКА (эти правила важнее общих пожеланий выше): "
    "пиши как одно короткое сообщение в чате, не как мини-презентацию. "
    "Основной каркас: конкретно предложи помощь («могу помочь с ...» / "
    "«готов помочь с ...»), затем одной фразой скажи, как предлагаешь начать, "
    "и закончи одним простым следующим шагом. "
    "Обычно 2–4 предложения и примерно 180–340 символов; не заполняй лимит "
    "ради объёма. Персонализация необязательна: не вытягивай из заявки редкие "
    "детали ради эффекта. Обычно достаточно предмета или основной цели клиента, "
    "а иногда и этого не нужно. "
    "Не пересказывай заявку и не перечисляй одновременно цель клиента, методику, "
    "формат, длительность и пробное. Онлайн и 60–90 минут НЕ обязаны быть в каждом "
    "первом отклике: упоминай логистику только когда она помогает сделать предложение "
    "конкретнее. Один вопросительный знак максимум. "
    "Не доказывай экспертность демонстрационными английскими фразами, названиями "
    "учебников, методик или buzzword-ами. Даже если в заявке есть необычная деталь, "
    "не надо обязательно отражать её в отклике. "
    "Лучше нормальное «могу помочь, предлагаю начать так» без глубокой персонализации, "
    "чем гладкий рекламный абзац. Не добавляй нарочно опечатки, ошибки, улыбки или "
    "разговорные слова только ради «человечности». "
)

CHAT_STYLE_OVERRIDE = (
    "ФИНАЛЬНЫЙ СТИЛЬ ЧАТА: сначала ответь на последний прямой вопрос клиента. "
    "Потом максимум одна короткая фраза про следующий шаг. Не повторяй "
    "самопрезентацию и методику из первого сообщения. Обычно хватает 1–3 "
    "предложений и одного вопроса. Если клиент спросил цену, формат или время, "
    "дай факт в первой фразе без вступления. "
)

# Patterns observed in the real outreach examples: they are not unsafe, but
# they make otherwise personalized copy sound like the same generated scaffold.
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


def client_copy_issues(text: str, *, channel: str = "outreach") -> list[str]:
    """Return style issues worth one cheap regeneration attempt.

    Safety (contacts, links, etc.) stays in the existing text guard. This helper
    only catches the most repetitive copy patterns and therefore must not be a
    terminal business gate by itself.
    """

    text = str(text or "").strip()
    issues: list[str] = []

    preferred_max = 380 if channel == "outreach" else 450
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
        + ". Перепиши с нуля, сохрани факты, ничего нового не придумывай. "
        "Сделай конкретный оффер: коротко предложи помощь, скажи, как предлагаешь "
        "начать, и задай максимум один вопрос. Глубокая персонализация не нужна."
    )


_OUTREACH_SHAPES = (
    (
        "Вариант композиции: «Могу помочь с [задачей]. Предлагаю начать с "
        "[простого первого шага]. [Один вопрос]». Не усложняй."
    ),
    (
        "Вариант композиции: сначала прямое предложение помощи, затем конкретно "
        "что предлагаешь сделать на первом занятии, затем один вопрос."
    ),
    (
        "Вариант композиции: если важна логистика, дай один факт (например онлайн "
        "или цена), затем предложи первый шаг и задай один вопрос."
    ),
    (
        "Вариант композиции: обычный короткий оффер без глубокой персонализации. "
        "Достаточно назвать предмет или цель, предложить, с чего начать, и спросить "
        "про удобное время."
    ),
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


def style_variation(channel: str = "outreach") -> str:
    """Vary message structure instead of forcing cosmetic punctuation quirks."""

    shapes = _CHAT_SHAPES if channel == "chat" else _OUTREACH_SHAPES
    shape = random.choice(shapes)
    # Do not force a smile. It is allowed rarely when it fits the sentence,
    # but forced random smiles quickly become their own automation signature.
    if random.random() < (0.15 if channel == "chat" else 0.08):
        casual = (
            " Лёгкая «)» допустима только если сама естественно просится; специально не добавляй."
        )
    else:
        casual = " Улыбку специально не добавляй."
    return shape + casual + " "
