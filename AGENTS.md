# LLM context budget

- Design for local LLMs with limited context windows.
- Keep LLM-visible tool and field descriptions concise and non-redundant. Include
  only tool selection, input semantics, and essential accuracy safeguards.
- Put setup instructions, rationale, and lengthy examples in blueprint READMEs,
  not tool metadata.
- Keep responses compact without losing units, timing, provider semantics, or
  missing-data and coverage warnings.
- When changing descriptions, inspect HA's exported tool metadata and measure its
  size rather than assuming shorter YAML means less model context.
