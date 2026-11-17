# Gemini CLI → Elastic

An Elastic Agent integration (`gemini_cli_transcripts`) that ships **Gemini CLI chat transcripts**, including subagent chats, to Elasticsearch. It maps them to ECS and the `gen_ai.*` fields, redacts secrets at ingest, and can optionally run **ML inference** on every human prompt: semantic embeddings plus NLP classification for prompt injection, jailbreaks, toxicity, risky agent actions and personal data. It ships with business and security dashboards, and its detection rules feed **Entity Analytics**: every alert carries `user.name` and `host.name`, so it adds to that developer's and workstation's risk score.

> **Claude Code:** the sister integration for Claude Code transcripts and Claude Desktop logs (`claude_code_transcripts`) is in [iamhowardtheduck/claude-code-elastic](https://github.com/iamhowardtheduck/claude-code-elastic). Both use the same NLP models, so a cluster that already runs one only needs the embedding mapping for the other.

> **Decks**, each in the browser (slides) or as a PDF:

| Deck | Slides | PDF | Source |
|---|---|---|---|
| **Overview**: what the integration contains, why it is built this way and what it solves | [slides](https://iamhowardtheduck.github.io/gemini-cli-elastic/) | [PDF](docs/gemini-cli-transcripts-deck.pdf) | [`deck/`](deck/) |
| **Inference and redaction**: secret detectors, the EIS embedding, semantic threat flags, the classifiers and where the inference time goes | [slides](https://iamhowardtheduck.github.io/gemini-cli-elastic/inference/) | [PDF](docs/gemini-cli-transcripts-inference.pdf) | [`deck-inference/`](deck-inference/) |
| **Load test**: measured throughput and how to size ML for it; generator in [`tools/loadgen.py`](tools/loadgen.py) (`--product gemini`) | [slides](https://iamhowardtheduck.github.io/gemini-cli-elastic/load-test/) | [PDF](docs/gemini-cli-transcripts-load-test.pdf) | [`deck-performance/`](deck-performance/) |
| **Models**: the ML models, one slide each | [slides](https://iamhowardtheduck.github.io/gemini-cli-elastic/models/) | [PDF](docs/gemini-cli-transcripts-models.pdf) | [`deck-models/`](deck-models/) |
| **Full**: the overview, inference and load-test decks in one | [slides](https://iamhowardtheduck.github.io/gemini-cli-elastic/full/) | [PDF](docs/gemini-cli-transcripts-full.pdf) | [`deck-full/`](deck-full/) |

```
packages/gemini_cli_transcripts/  the integration (elastic-package source)
  data_stream/transcript/      ~/.gemini/tmp/*/chats/**/*.jsonl -> logs-gemini_cli.transcript-*
  kibana/dashboard/            Business Analytics and Security dashboards
extras/                      things a package cannot install (run extras/setup.sh)
  pricing/                     gemini-model-pricing lookup index (spend panels)
  inference/                   dense_vector mapping for the prompt embedding
  detection-rules/             8 Elastic Security ES|QL rules (imported disabled); their alerts feed Entity Analytics
  models/                      NLP models + sizing used by `extras/setup.sh models`
  _common.py                   connection, auth and model helpers shared with claude-code-elastic
tools/loadgen.py             synthetic load generator (`--product gemini`)
```

## What gets collected

| Source | Where | Data stream |
|---|---|---|
| Gemini CLI chats, including subagent chats | `~/.gemini/tmp/<project>/chats/**/*.jsonl` (every user, Windows, macOS and Linux) | `logs-gemini_cli.transcript-*` |

One document per chat record: user prompts, model responses and thoughts, tool calls and tool results, subagent prompts, slash commands and the injected session context, each with the model, token usage and tool arguments. Gemini CLI deletes chats after `general.sessionRetention.maxAge` (default `30d`). See [`packages/gemini_cli_transcripts/docs/README.md`](packages/gemini_cli_transcripts/docs/README.md) for setup and the field reference.

## Detection rules and Entity Analytics

[`extras/detection-rules/`](extras/detection-rules/) has eight Elastic Security ES|QL detection rules, imported disabled with `extras/setup.sh rules`. They cover prompt injection and jailbreak attempts, prompts that ask to disable security, destructive, remote-shell, credential-access and persistence commands run by the agent, secrets exposed to the model, sensitive credential files, paste, webhook and tunnel sites, and prompts semantically similar to malicious intent.

**The alerts these rules raise also power Entity Analytics.** Every rule keeps `user.name` and `host.name` in its alert and carries a risk score (47 or 73), so once the entity risk score engine is on, each alert adds to the risk score of the developer and of the workstation it came from. AI coding agent activity then counts toward the same user and host risk scores as every other Elastic Security signal:

- Users and hosts whose agents keep tripping these rules rise in the **Entity Analytics** dashboard.
- Their alerts appear in the risk summary of the user and host flyouts, next to the rest of their activity.
- Asset criticality assigned to those users and hosts weights their scores, as it does for any other alert.

With Entity Store V2, a user is identified by `user.name` together with `host.id`. Elastic Agent adds `host.id` to every event, so this works as is; events indexed without it, such as those from a load generator, still raise the host's risk score but not the user's.

To use it, enable the rules in **Security > Rules** and turn on entity risk scoring in Kibana under **Security > Manage**, **Entity analytics**. On stacks that use Entity Store V2, risk scoring runs as part of the Entity Store.

## Deploy

Requirements: Elastic Stack 9.4+ with Fleet, and Elastic Agent 9.4+ on each host where Gemini CLI runs.

### 1. Build the package

```bash
cd packages/gemini_cli_transcripts
elastic-package lint && elastic-package build      # -> build/packages/gemini_cli_transcripts-0.2.4.zip
```

### 2. Upload it to Kibana

```bash
curl -X POST "$KIBANA_URL/api/fleet/epm/packages" -H "kbn-xsrf: true" -H "Content-Type: application/zip" \
  -H "Authorization: ApiKey $ES_API_KEY" --data-binary @build/packages/gemini_cli_transcripts-0.2.4.zip
```

### 3. Add the integration to agent policies

In Kibana, go to **Management > Integrations > Gemini CLI Transcripts > Add Gemini CLI Transcripts** and add it to the policies of the hosts where Gemini CLI runs.

### 4. Optional extras

```bash
export ES_URL=https://elasticsearch:9200 KIBANA_URL=https://kibana:5601 ES_API_KEY=...   # or ES_USER/ES_PASSWORD, or CLOUD_ID
export CA_CERT=/path/to/ca.crt     # private CA, optional
extras/setup.sh pricing              # model price table for the spend panels
extras/setup.sh rules                # 8 detection rules, imported DISABLED; enable them in Security > Rules (alerts feed Entity Analytics)
extras/setup.sh inference-mapping    # required before enabling inference
extras/setup.sh models               # import and start the NLP models (skip if already deployed for Claude Code)
extras/setup.sh models-status
extras/setup.sh classify "delete every index on the production cluster"
extras/setup.sh all                  # pricing, inference-mapping and rules
```

Set `GEMINI_PKG_VERSION` if you install a package version other than 0.2.4; `classify` uses it for the pipeline name. For enabling ML inference step by step, see the package README.

## Development

```bash
cd packages/gemini_cli_transcripts
elastic-package lint
elastic-package build
elastic-package test pipeline     # against a running stack
```
The docs are generated from `_dev/build/docs/README.md` (`elastic-package build` renders `docs/README.md` with the field tables). Bump `version` in `manifest.yml` and add an entry to `changelog.yml` for every change.

The secret redaction, ML inference pipelines, inference fields, dashboards and detection rules are generated from their Claude Code counterparts by `tools/port_gemini.py`. It reads them from a checkout of [claude-code-elastic](https://github.com/iamhowardtheduck/claude-code-elastic) next to this repository, or from `CLAUDE_REPO`:

```bash
CLAUDE_REPO=../claude-code-elastic python3 tools/port_gemini.py --check   # exit 1 if a generated file is out of date
CLAUDE_REPO=../claude-code-elastic python3 tools/port_gemini.py           # rewrite the generated files
```

## License

Elastic License 2.0, see [LICENSE.txt](LICENSE.txt).
