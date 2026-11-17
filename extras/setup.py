#!/usr/bin/env python3
"""Optional setup for the Gemini CLI Transcripts integration (things an integration package cannot install).

Usage: extras/setup.sh <command> [<command> ...]
  pricing               create/refresh the gemini-model-pricing lookup index (Google list prices; spend panels)
  inference-mapping     add the gemini_cli.prompt_embedding dense_vector mapping (needed before enabling inference)
  rules                 import the Gemini CLI detection rules (disabled; enable them in Security > Rules)
  all                   all of the above

  models [--dry-run] [--restart]   import and start the NLP models; the same models serve both integrations
  models-status                    deployment state, allocations, latency, queue and errors per model
  classify "<prompt text>"         run one prompt through the installed Gemini classify pipeline (_simulate, nothing indexed)

Environment: ES_URL, KIBANA_URL or CLOUD_ID, ES_API_KEY or ES_USER + ES_PASSWORD,
CA_CERT, MODELS_FILE, plus:
  GEMINI_PKG_VERSION           installed gemini_cli_transcripts package version (default 0.2.3; used for pipeline names)
"""
import os, sys, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as base   # extras/_common.py: connection, auth, report, models (shared with claude-code-elastic)

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_VERSION = os.environ.get("GEMINI_PKG_VERSION", "0.2.3")
DATASET = "logs-gemini_cli.transcript"


def pricing():
    print("pricing")
    idx = "gemini-model-pricing"
    code, _ = base.es("HEAD", f"/{idx}", ok=(200, 404))
    if code == 404:
        body = base.json.load(open(os.path.join(HERE, "pricing", f"{idx}.index.json")))
        base.report(f"create lookup index {idx}", base.es("PUT", f"/{idx}", body))
    nd = open(os.path.join(HERE, "pricing", f"{idx}.ndjson"), "rb").read()
    code, body = base.es("POST", f"/{idx}/_bulk?refresh=true", nd, ctype="application/x-ndjson")
    n = sum(1 for l in nd.splitlines() if b'"_id"' in l)
    base.report(f"load {n} model prices" + (" (with item errors)" if isinstance(body, dict) and body.get("errors") else ""), (code, body))


def inference_mapping():
    print("inference-mapping")
    add = base.json.load(open(os.path.join(HERE, "inference", "prompt-embedding.mapping.json")))
    name = f"{DATASET}@custom"
    code, body = base.es("GET", f"/_component_template/{name}", ok=(200, 404))
    tpl = {"template": {"mappings": {}}}
    if code == 200:
        tpl = body["component_templates"][0]["component_template"]
        for k in ("created_date_millis", "modified_date_millis", "created_date", "modified_date"): tpl.pop(k, None)
    base.merge(tpl.setdefault("template", {}).setdefault("mappings", {}), add)
    base.report(f"component template {name}", base.es("PUT", f"/_component_template/{name}", tpl))
    code, body = base.es("PUT", f"/{DATASET}-*/_mapping", add, ok=(200, 404))
    base.report("existing Gemini transcript data streams", (code if code != 404 else 200, body))


def rules():
    print("rules")
    path = os.path.join(HERE, "detection-rules", "gemini-cli-rules.ndjson")
    b = "----gemini" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"rules.ndjson\"\r\nContent-Type: application/x-ndjson\r\n\r\n").encode() \
        + open(path, "rb").read() + f"\r\n--{b}--\r\n".encode()
    code, res = base.kb("POST", "/api/detection_engine/rules/_import?overwrite=true", body, ctype=f"multipart/form-data; boundary={b}")
    ok = isinstance(res, dict)
    base.report(f"import detection rules: {res.get('success_count') if ok else '?'} imported, errors {res.get('errors') if ok else res}", (code, res))


def classify(text):
    # reuse the Claude command's output formatting against the Gemini pipeline and field names
    import time
    pipe = f"{DATASET}-{PKG_VERSION}-classify"
    doc = {"message": text, "gemini_cli": {"human_prompt": True}}
    t = time.time()
    code, body = base.es("POST", f"/_ingest/pipeline/{pipe}/_simulate", {"docs": [{"_source": doc}]})
    if code >= 300:
        sys.exit(f"ERR {code}: {base.json.dumps(body)[:400]}")
    src = body["docs"][0].get("doc", {}).get("_source", {})
    pc = src.get("gemini_cli", {}).get("prompt_classification", {})
    print(f"pipeline {pipe}  ({time.time() - t:.1f} s)")
    print("flagged:   ", pc.get("flagged"))
    print("categories:", pc.get("categories"))
    for k, v in sorted((pc.get("scores") or {}).items()):
        if isinstance(v, dict):
            top = sorted(((s, l) for l, s in v.items() if isinstance(s, (int, float))), reverse=True)[:3]
            print(f"  {k:14} " + ", ".join(f"{l} {s:.2f}" for s, l in top))
        else:
            print(f"  {k:14} {v:.3f}" if isinstance(v, (int, float)) else f"  {k:14} {v}")
    if pc.get("entities"): print("entities:  ", pc.get("entities"))
    if pc.get("errors"): print("errors:    ", pc.get("errors"))


CMDS = {"pricing": pricing, "inference-mapping": inference_mapping, "rules": rules}
if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["models"]:
        base.models(dry="--dry-run" in args, restart="--restart" in args)
        if base.FAILURES: print(f"{base.FAILURES} step(s) failed"); sys.exit(1)
        sys.exit()
    if args[:1] == ["models-status"]:
        base.models_status(); sys.exit()
    if args[:1] == ["classify"] and len(args) == 2:
        classify(args[1]); sys.exit()
    if not args or any(a not in CMDS and a != "all" for a in args):
        sys.exit(__doc__)
    for a in (list(CMDS) if "all" in args else args):
        CMDS[a]()
    if base.FAILURES: print(f"{base.FAILURES} step(s) failed"); sys.exit(1)
