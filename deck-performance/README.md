# Load-test deck (Gemini CLI only)

> Gemini CLI only. The decks covering Claude Code, and Claude Code and Gemini CLI together, are in [claude-code-elastic](https://github.com/iamhowardtheduck/claude-code-elastic).

A 10-slide [fslides](https://fslides.dev) presentation of the 2026-11-17 Gemini CLI load test: the Gemini CLI Transcripts integration on a self-managed Elasticsearch 9.5.6 cluster, driven by `tools/loadgen.py --product gemini` and run back to back with Claude Code on the same cluster, generator and models (18 one-thread zero-shot allocations on one ML node with 24 logical CPUs). It covers the saturation probe, classified and embedding-only steps, where the classifier time goes, what the cluster classifies an hour and how to size ML for it. ML autoscaling and the inference cache were measured only in the Claude Code test on Elastic Cloud (`../../deck-performance/`).

- **Watch it:** https://iamhowardtheduck.github.io/gemini-cli-elastic/load-test/
- **PDF:** [docs/gemini-cli-transcripts-load-test.pdf](../docs/gemini-cli-transcripts-load-test.pdf)

## Edit it

The deck uses the `elastic-web` fslides kit (`style: 'elastic-web'` in `fslides.config.js`; tokens and the isometric engine in `slides/style/`).

```bash
cd deck-performance
fslides serve        # player with live reload
fslides pdf          # re-export, then copy the PDF to docs/gemini-cli-transcripts-load-test.pdf
```

On Ubuntu 24.04 headless Chrome may refuse to start ("No usable sandbox"); point `PUPPETEER_EXECUTABLE_PATH` at a Chrome you trust.

## Reproduce the numbers

```bash
export ES_URL=... ES_API_KEY=...        # or CLOUD_ID, or ES_USER + ES_PASSWORD
# run 2, Gemini CLI: classified steps, then embedding only
python3 tools/loadgen.py --product gemini run --ramp 0.15:240,0.25:240,0.35:240,0.45:240 --lines-per-prompt 20 --timeout 300
python3 tools/loadgen.py --product gemini run --no-classify --ramp 1:180,3:180 --lines-per-prompt 20
python3 tools/loadgen.py --product gemini report --since 60m
# the Claude Code reference: the same two ramps with --product claude
python3 tools/loadgen.py --product gemini cleanup
```

Wait for the zero-shot queue to drain between runs. Run 1, the saturation probe, was `--product claude run --ramp 0.25:240,0.5:240,1:240,1.5:240 --lines-per-prompt 20`, stopped during the 1.5 step.
