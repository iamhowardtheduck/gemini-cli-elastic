# Models deck (Gemini CLI only)

> Gemini CLI only. The decks covering Claude Code, and Claude Code and Gemini CLI together, are in [claude-code-elastic](https://github.com/iamhowardtheduck/claude-code-elastic).

The seven ML models behind the Gemini CLI Transcripts redaction and classification pipeline, one slide each, in the elastic-web kit. The same deployed models serve the Claude Code integration too.

- **Slides:** https://iamhowardtheduck.github.io/gemini-cli-elastic/models/
- **PDF:** [docs/gemini-cli-transcripts-models.pdf](../docs/gemini-cli-transcripts-models.pdf)

1. **Cover** and **where the models sit**: which switch on the Gemini CLI integration policy turns on which model.
2. **One slide per model**: embedding (`.jina-embeddings-v5-text-nano`), prompt injection, jailbreak, toxicity, offensive, zero-shot and NER. Each gives the model ID, source, labels, threshold, `gemini_cli.*` output fields, ML memory and an example inference call. Zero-shot uses the interaction label "a question about Gemini itself"; NER ignores Gemini, Gemini CLI and Google.
3. **Loading the models** with Eland or `extras/setup.sh models` (skip it if the models are already deployed for Claude Code), plus the embedding mapping on `logs-gemini_cli.transcript@custom`.

```bash
cd deck-models
npx fslides serve    # http://localhost:30024
npx fslides pdf      # re-export, then copy the PDF to docs/gemini-cli-transcripts-models.pdf
```
