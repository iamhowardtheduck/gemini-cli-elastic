# Overview deck (Gemini CLI only)

> Gemini CLI only. The decks covering Claude Code, and Claude Code and Gemini CLI together, are in [claude-code-elastic](https://github.com/iamhowardtheduck/claude-code-elastic).

A 12-slide [fslides](https://github.com/fslides/fslides) presentation on the Gemini CLI Transcripts integration: what it collects, why it's built the way it is, and what it solves for security, leadership and compliance teams.

- **Watch it:** https://iamhowardtheduck.github.io/gemini-cli-elastic/
- **PDF:** [docs/gemini-cli-transcripts-deck.pdf](../docs/gemini-cli-transcripts-deck.pdf)

## Edit it

```bash
cd deck
npm install
npm run serve        # full player with live reload
npm run pdf          # re-export, then copy the PDF to docs/gemini-cli-transcripts-deck.pdf
```

Every slide is an HTML file in `slides/`, built on the [elastic-web](https://fslides.dev/kits/) fslides kit: `slides/style/eweb.css` and `eweb.js` (isometric engine, dot fields, counters, footer). The kit's design brief isn't in this repo; with access to the kit, `fslides kit use elastic-web` installs it locally under `deck/.claude/skills/`. Animations settle by 1.8s so the PDF export captures each slide's final frame; order and labels live in `fslides.config.js`.
