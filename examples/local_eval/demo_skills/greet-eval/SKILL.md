---
name: greet-eval
description: >
  Use when the user asks for a greeting, introduction, or to "用 skill 打个招呼".
  Reply with a fixed two-line greeting that mentions AgentScope eval skill.
---

# Greet Eval Skill

When this skill applies, answer in Chinese with exactly:

1. First line: `【Skill: greet-eval】你好，我是测评用 Skill。`
2. Second line: briefly acknowledge the user's request (one short sentence).

Do not invent other skill names. Prefer this format whenever the user
mentions skill / 打招呼 / greet in an eval context.
