# Inference and redaction deck (Gemini CLI only)

> Gemini CLI only. The decks covering Claude Code, and Claude Code and Gemini CLI together, are in [claude-code-elastic](https://github.com/iamhowardtheduck/claude-code-elastic).

A 12-slide [fslides](https://github.com/fslides/fslides) deck, in the elastic-web kit, on everything the Gemini CLI Transcripts ingest pipelines do to a prompt before it is stored. It covers secret redaction (19 detector types over `message`, `gemini_cli.content`, `gemini_cli.toolCalls` and `gemini_cli.thoughts`, failing closed), the EIS embedding, semantic threat flags, the five single-pass classifiers, the five zero-shot passes, the classified document and where the inference time goes.

- Slides: https://iamhowardtheduck.github.io/gemini-cli-elastic/inference/
- PDF: [`docs/gemini-cli-transcripts-inference.pdf`](../docs/gemini-cli-transcripts-inference.pdf)

## Edit it

```bash
cd deck-inference
npm install
npx fslides serve    # http://localhost:30022
npx fslides pdf
```

Sources: `packages/gemini_cli_transcripts/data_stream/transcript/elasticsearch/ingest_pipeline/` (`default.yml`, `inference.yml`, `classify.yml`, generated from the Claude Code sources by `tools/port_gemini.py`), `packages/gemini_cli_transcripts/docs/README.md` and `docs/inference-tuning.md`. The example prompt is synthetic, from `tools/loadgen.py`. The 37 s average ML time was measured on 12 real Gemini CLI prompts on a self-managed test cluster.
