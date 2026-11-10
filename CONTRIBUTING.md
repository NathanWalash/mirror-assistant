# Working on mirror-assistant

## Getting set up

1. Accept the GitHub collaborator invite.
2. Clone and set up:
   ```bash
   git clone https://github.com/NathanWalash/mirror-assistant.git
   cd mirror-assistant
   scripts/setup.sh
   scripts/talk.sh --selftest   # should print what it heard and Mirror's reply
   ```
3. You need macOS with Homebrew for now. Linux/Pi instructions come with the Pi setup.

## Making changes

- Branch off `main`: `git switch -c yourname/short-description`
- Before pushing, run the same checks CI does:
  ```bash
  uv run ruff check . && uv run ruff format --check . && uv run pytest
  ```
  `uv run ruff format .` fixes formatting for you.
- Open a pull request into `main`. CI must pass, and the other person gives it a look
  before merging.

## Adding a widget (calendar, buses, ...)

Follow [docs/widgets.md](docs/widgets.md): one Python module that fetches, one JS file
that draws, one config block. `uv run mirror-hub` shows the screen without the voice loop.

## Private vs shared

| Shared (committed) | Private (git-ignored) |
|---|---|
| `personality/personas/mirror.example.md` | `personality/personas/mirror.md` |
| `config.example.yaml` | `config.yaml` |
| code, docs, scripts | `models/`, `cache/`, `.env` (API keys), `*.wav` |

**The repo is public.** Names, addresses, calendar links, API keys and in-jokes about real
people go in the private files only. If a personality tweak is good for everyone,
copy it into `mirror.example.md`.

## Adding Python dependencies

```bash
uv add --package mirror-voice some-package   # runtime dependency of the voice loop
uv add --dev some-tool                        # dev-only tool
```

Commit the updated `uv.lock`.
