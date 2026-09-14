# Host integration and portability

The canonical packages use portable `name` and `description` frontmatter plus standard-library Python. `scripts/install.py` keeps the canonical persistent copies under `~/.agents/skills` and exposes the same directories to provider-specific roots with links when supported.

| Host | Verified discovery behavior | Integration status |
| --- | --- | --- |
| Codex CLI 0.154 | Global and project `.agents/skills`; legacy `.codex/skills` also supported | Skill discovery verified locally; no universal edit-interception hook claimed |
| Claude Code 2.1 | Project/global `.claude/skills` | Installer provides links to canonical skills; native path documented locally |
| OpenCode 1.18 | Global `.agents/skills` and `.claude/skills`, plus native config roots | Shared canonical discovery documented locally; restart may be required |
| Grok CLI 1.0 | User/project `.agents`, `.claude`, and `.grok` skill roots | Shared canonical discovery documented locally |

Versions identify the environment used for evidence, not permanent compatibility guarantees. Future hosts can use `install.py --skill-root <path>` and must be validated before being described as supported.

Three enforcement layers are distinct:

1. Skill instructions guide the agent.
2. Runtime commands enforce managed paths/state and detect later direct drift.
3. Host hooks can invoke those guards only where a documented hook API exists and is actually configured.

No Markdown instruction can intercept every arbitrary edit, expose hidden context usage, survive host compaction by itself, or launch a fresh model. Do not claim those capabilities without an observed adapter test.
