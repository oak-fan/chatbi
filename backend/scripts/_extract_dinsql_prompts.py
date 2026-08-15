from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "Spider2" / "spider2-lite" / "baselines" / "dinsql" / "DIN-SQL.py"
TARGET = (
    ROOT
    / "backend"
    / "app"
    / "services"
    / "system"
    / "chatbi"
    / "dinsql"
    / "prompts.py"
)
PROMPT_NAMES = [
    "schema_linking_prompt",
    "classification_prompt",
    "easy_prompt",
    "medium_prompt",
    "hard_prompt",
]


def main() -> None:
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    values: dict[str, str] = {}
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in PROMPT_NAMES:
                values[target.id] = ast.literal_eval(node.value)
    missing = [name for name in PROMPT_NAMES if name not in values]
    if missing:
        raise RuntimeError(f"missing DIN-SQL prompt constants: {missing}")

    lines = [
        '"""DIN-SQL prompt constants copied from Spider2 baseline.',
        "",
        "Keep these strings semantically aligned with the baseline; integration code",
        "adapts inputs and LLM transport around them instead of editing wording.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    for name in PROMPT_NAMES:
        lines.append(f"{name.upper()} = {values[name]!r}")
        lines.append("")
    lines.append("__all__ = [")
    for name in PROMPT_NAMES:
        lines.append(f'    "{name.upper()}",')
    lines.append("]")
    lines.append("")
    TARGET.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
