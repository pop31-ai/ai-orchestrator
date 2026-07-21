"""
Prompt Booster Module — TinyLlama Coach
Я (Orchestrator) анализирую запрос и создаю структурированный промпт.
TinyLlama получает готовые примеры → отвечает лучше.
"""
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("prompt_booster")

@dataclass
class BoostedPrompt:
    raw_input: str
    intent: str
    template: str
    examples: List[Dict[str, str]]
    system_hint: str
    output_constraint: str
    final_prompt: str = ""


class PromptBooster:
    """
    Анализирует входящий запрос, подбирает шаблон и примеры,
    возвращает промпт для TinyLlama.
    """

    INTENTS = {
        "code": {
            "keywords": ["напиши", "создай", "код", "code", "script", "python", "game", "игру"],
            "template": """Write code for the following task. Output ONLY valid Python code, no explanations.

Task: {task}

Requirements:
- Use simple, clear syntax
- Include comments in Russian or English
- The code must be runnable

```python
{code}```""",
            "system_hint": "You are a Python code generator. Output ONLY runnable code.",
        },
        "explain": {
            "keywords": ["объясни", "что такое", "как работает", "explain", "what is", "how"],
            "template": """Explain in simple terms (2-3 sentences max):

Q: {task}
A:""",
            "system_hint": "Answer briefly and simply. Maximum 3 sentences.",
        },
        "creative": {
            "keywords": ["придумай", "идея", "придумай идею", "concept", "idea", "design"],
            "template": """Generate a creative concept. Format:

## Idea
(one sentence)

## How it works
(2-3 bullet points)

## Example
(one concrete example)

Task: {task}""",
            "system_hint": "Generate creative ideas in a structured format. Be concise.",
        },
        "search": {
            "keywords": ["найди", "поиск", "search", "find", "look for"],
            "template": """Search query: {task}
To find information, use the search tool or check Wikipedia.""",
            "system_hint": "Suggest search queries and sources.",
        },
        "default": {
            "keywords": [],
            "template": """Answer briefly:

Q: {task}
A:""",
            "system_hint": "Answer in 1-2 sentences.",
        },
    }

    EXAMPLES = {
        "code": [
            {"q": "напиши игру арканоид", "a": 'import pygame\n...\n# full arkanoid game in 50 lines'},
            {"q": "создай калькулятор", "a": 'def calc(a, op, b):\n    if op == "+": return a + b\n    ...'},
        ],
        "explain": [
            {"q": "что такое рекурсия", "a": "Рекурсия — когда функция вызывает саму себя."},
            {"q": "как работает HashMap", "a": "HashMap хранит пары ключ-значение, используя хеш-функцию для быстрого доступа."},
        ],
    }

    def analyze(self, text: str) -> str:
        text_lower = text.lower().strip()
        for intent, config in self.INTENTS.items():
            if intent == "default":
                continue
            for kw in config["keywords"]:
                if kw in text_lower:
                    logger.debug(f"Intent detected: {intent} (keyword: {kw})")
                    return intent
        return "default"

    def build(self, user_input: str, context: Optional[Dict] = None) -> BoostedPrompt:
        intent = self.analyze(user_input)
        config = self.INTENTS.get(intent, self.INTENTS["default"])
        examples = self.EXAMPLES.get(intent, [])

        # Build the few-shot part
        few_shot = ""
        if examples:
            few_shot = "\nExamples:\n"
            for ex in examples:
                few_shot += f"  Input: {ex['q']}\n  Output: {ex['a']}\n\n"

        # Build final prompt
        template = config["template"]
        task_part = template.replace("{task}", user_input)
        if "{code}" in task_part:
            task_part = task_part.replace("{code}", "# your code here")

        if few_shot:
            final = f"{config['system_hint']}\n\n{few_shot}\n{task_part}"
        else:
            final = f"{config['system_hint']}\n\n{task_part}"

        return BoostedPrompt(
            raw_input=user_input,
            intent=intent,
            template=template,
            examples=examples,
            system_hint=config["system_hint"],
            output_constraint="keep it short",
            final_prompt=final,
        )


# Глобальный экземпляр
booster = PromptBooster()
