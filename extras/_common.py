"""Shared helpers for extras/setup.py, copied from claude-code-elastic's extras/setup.py (connection, auth, report, models).
Run extras/setup.sh, not this file.

Original usage text:
Optional setup for the Claude Code integration (things an integration package cannot install).

Usage: extras/setup.sh <command> [<command> ...]
  pricing               create/refresh the claude-model-pricing lookup index (spend panels)
  inference-mapping     add the claude_code.prompt_embedding dense_vector mapping (needed before enabling inference)
  rules                 import the detection rules (disabled; enable them in Security > Rules)
  inference-monitoring  stats collector (ILM, template, pipeline, workflow), admin dashboard, alert rules (disabled)
  all                   all of the above

  models [--dry-run] [--restart]   import missing NLP models (eland in Docker) and start/update their deployments
                                   to match extras/models/models.json (--restart: stop+start when threads change)
  models-status                    deployment state, allocations, latency, queue and errors per model
  classify "<prompt text>"         run one prompt through the installed classify pipeline (_simulate, nothing indexed);
                                   CLASSIFY_PIPELINE_FILE=<edited classify.yml> tests your changes before rebuilding

Environment:
  ES_URL, KIBANA_URL           e.g. https://es.example:9200, https://kibana.example:5601
  CLOUD_ID                     Elastic Cloud Hosted alternative to ES_URL/KIBANA_URL (from the deployment page)
  ES_API_KEY                   base64 API key (preferred), or ES_USER + ES_PASSWORD
  CA_CERT                      optional path to a CA bundle; INSECURE=true skips TLS verification (testing only)
  PKG_VERSION                  installed claude_code_transcripts package version (default 0.2.4; used for pipeline names)
  MODELS_FILE                  your own copy of extras/models/models.json (sizing for your cluster)
  HF_TOKEN                     Hugging Face token, only for gated models
"""
import base64, json, os, ssl, sys, uuid, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

def _from_cloud_id(cid):
    """Elastic Cloud ID -> (Elasticsearch URL, Kibana URL)."""
    try:
        b = cid.split(":", 1)[1]
        host, es_id, kb_id = (base64.b64decode(b + "=" * (-len(b) % 4)).decode().split("$") + ["", ""])[:3]
    except Exception:
        sys.exit("CLOUD_ID is not a valid Elastic Cloud ID")
    port = "443"
    if ":" in host:
        host, port = host.rsplit(":", 1)
    return f"https://{es_id}.{host}:{port}", (f"https://{kb_id}.{host}:{port}" if kb_id else "")

ES, KB = os.environ.get("ES_URL", "").rstrip("/"), os.environ.get("KIBANA_URL", "").rstrip("/")
if os.environ.get("CLOUD_ID") and not (ES and KB):
    _es, _kb = _from_cloud_id(os.environ["CLOUD_ID"])
    ES, KB = ES or _es, KB or _kb
PKG_VERSION = os.environ.get("PKG_VERSION", "0.2.4")

def _auth():
    if os.environ.get("ES_API_KEY"):
        return "ApiKey " + os.environ["ES_API_KEY"]
    if os.environ.get("ES_USER") and os.environ.get("ES_PASSWORD"):
        return "Basic " + base64.b64encode(f"{os.environ['ES_USER']}:{os.environ['ES_PASSWORD']}".encode()).decode()
    sys.exit("Set ES_API_KEY, or ES_USER and ES_PASSWORD")

def _ctx():
    if os.environ.get("INSECURE") == "true":
        c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c
    return ssl.create_default_context(cafile=os.environ.get("CA_CERT") or None)

def call(base, method, path, body=None, ctype="application/json", ok=(200, 201)):
    if not base:
        sys.exit("ES_URL / KIBANA_URL not set")
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    h = {"Authorization": _auth(), "Content-Type": ctype, "kbn-xsrf": "true"}
    req = urllib.request.Request(base + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, context=_ctx()) as r:
            txt = r.read().decode(); return r.status, (json.loads(txt) if txt.strip().startswith(("{", "[")) else txt)
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        if e.code in ok:
            return e.code, txt
        return e.code, (json.loads(txt) if txt.strip().startswith("{") else txt)

def es(m, p, b=None, **k): return call(ES, m, p, b, **k)
def kb(m, p, b=None, **k): return call(KB, m, p, b, **k)
def load(*p): return json.load(open(os.path.join(HERE, *p)))
FAILURES = 0
def report(what, res):
    global FAILURES
    code, body = res
    FAILURES += code >= 300
    print(f"  {'ok ' if code < 300 else 'ERR'} {what} ({code})" + ("" if code < 300 else f": {json.dumps(body)[:300]}"))

def merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict): merge(a[k], v)
        else: a[k] = v
    return a

def pricing():
    print("pricing")
    code, _ = es("HEAD", "/claude-model-pricing", ok=(200, 404))
    if code == 404:
        report("create lookup index claude-model-pricing", es("PUT", "/claude-model-pricing", load("pricing", "claude-model-pricing.index.json")))
    nd = open(os.path.join(HERE, "pricing", "claude-model-pricing.ndjson"), "rb").read()
    code, body = es("POST", "/claude-model-pricing/_bulk?refresh=true", nd, ctype="application/x-ndjson")
    report(f"load {sum(1 for l in nd.splitlines() if b'_id' in l)} model prices" + (" (with item errors)" if isinstance(body, dict) and body.get("errors") else ""), (code, body))

def inference_mapping():
    print("inference-mapping")
    add = load("inference", "prompt-embedding.mapping.json")
    name = "logs-claude_code.transcript@custom"
    code, body = es("GET", f"/_component_template/{name}", ok=(200, 404))
    tpl = {"template": {"mappings": {}}}
    if code == 200:
        tpl = body["component_templates"][0]["component_template"]
        for k in ("created_date_millis", "modified_date_millis", "created_date", "modified_date"): tpl.pop(k, None)
    merge(tpl.setdefault("template", {}).setdefault("mappings", {}), add)
    report(f"component template {name}", es("PUT", f"/_component_template/{name}", tpl))
    code, body = es("PUT", "/logs-claude_code.transcript-*/_mapping", add, ok=(200, 404))
    report("existing transcript data streams", (code if code != 404 else 200, body))

def rules():
    print("rules")
    path = os.path.join(HERE, "detection-rules", "claude-code-rules.ndjson")
    b = "----claude" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"rules.ndjson\"\r\nContent-Type: application/x-ndjson\r\n\r\n").encode() \
        + open(path, "rb").read() + f"\r\n--{b}--\r\n".encode()
    code, res = kb("POST", "/api/detection_engine/rules/_import?overwrite=true", body, ctype=f"multipart/form-data; boundary={b}")
    report(f"import detection rules: {res.get('success_count') if isinstance(res, dict) else '?'} imported, errors {res.get('errors') if isinstance(res, dict) else res}", (code, res))

def inference_monitoring():
    print("inference-monitoring")
    D = "inference-monitoring"
    report("ILM policy ml-inference-stats", es("PUT", "/_ilm/policy/ml-inference-stats", load(D, "stats-ilm.json")))
    report("ingest pipeline ml-inference-stats", es("PUT", "/_ingest/pipeline/ml-inference-stats", load(D, "stats-pipeline.json")))
    report("index template ml-inference-stats", es("PUT", "/_index_template/ml-inference-stats", load(D, "stats-template.json")))
    pipes = f"logs-claude_code.transcript-{PKG_VERSION},logs-claude_code.transcript-{PKG_VERSION}-classify"
    y = open(os.path.join(HERE, D, "collector.yaml")).read().replace("__PIPELINES__", pipes)
    wid = "ml-inference-stats-collector"
    code, body = kb("PUT", f"/api/workflows/workflow/{wid}", {"yaml": y}, ok=(200, 404))
    if code == 404:
        code, body = kb("POST", "/api/workflows", {"workflows": [{"id": wid, "yaml": y}]})
    report(f"workflow {wid} (collects stats every minute)", (code, body))
    nd = open(os.path.join(HERE, D, "ml-inference-admin.ndjson"), "rb").read()
    b = "----claude" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"dash.ndjson\"\r\nContent-Type: application/x-ndjson\r\n\r\n").encode() + nd + f"\r\n--{b}--\r\n".encode()
    report("dashboard [ML Inference] Admin", kb("POST", "/api/saved_objects/_import?overwrite=true", body, ctype=f"multipart/form-data; boundary={b}"))
    for r in load(D, "alert-rules.json"):
        rid = r.pop("id"); r["enabled"] = False
        code, res = kb("POST", f"/api/alerting/rule/{rid}", r, ok=(200, 409))
        if code == 409:
            upd = {k: r[k] for k in ("name", "schedule", "tags", "actions", "params")}
            code, res = kb("PUT", f"/api/alerting/rule/{rid}", upd)
        report(f"alert rule {rid} (disabled; add a connector action, then enable)", (code, res))

# ---------------------------------------------------------------- models
import shlex, shutil, subprocess

def _eland_cmd(m, image):
    """docker command for eland_import_hub_model; secrets are passed by environment name only (-e VAR), never on the command line."""
    if not ES:
        sys.exit("ES_URL (or CLOUD_ID) not set")
    os.environ["ES_URL"] = ES          # eland gets the resolved URL, also when only CLOUD_ID was given
    args = ["eland_import_hub_model", "--url", "$ES_URL", "--hub-model-id", m["hub_model_id"], "--task-type", m["task_type"],
            "--es-model-id", m["model_id"]]
    if m.get("max_model_input_length"):
        args += ["--max-model-input-length", str(m["max_model_input_length"])]
    docker = ["docker", "run", "--rm", "--network", "host", "-e", "ES_URL"]
    if os.environ.get("ES_API_KEY"):
        docker += ["-e", "ES_API_KEY"]; args += ["--es-api-key", "$ES_API_KEY"]
    else:
        docker += ["-e", "ES_USER", "-e", "ES_PASSWORD"]; args += ["--es-username", "$ES_USER", "--es-password", "$ES_PASSWORD"]
    if os.environ.get("HF_TOKEN"):          # gated Hugging Face models
        docker += ["-e", "HF_TOKEN"]; args += ["--hub-access-token", "$HF_TOKEN"]
    if os.environ.get("INSECURE") == "true":
        args += ["--insecure"]
    elif os.environ.get("CA_CERT"):
        docker += ["-v", f"{os.path.abspath(os.environ['CA_CERT'])}:/ca.crt:ro"]; args += ["--ca-certs", "/ca.crt"]
    # never pass --quantize: int8 models crashed pytorch_inference with SIGILL in testing
    # "$VAR" arguments are expanded inside the container by a python launcher (not sh -c: the shell in
    # eland:latest 9.2.0 fails with a missing libcrypt.so.1), so secret values never reach the host command line
    launcher = ("import os,sys; from eland.cli.eland_import_hub_model import main; "
                "sys.argv = [os.path.expandvars(a) if a.startswith('$') else a for a in sys.argv[1:]]; sys.exit(main())")
    return docker + ["--entrypoint", "", image, "python3", "-c", launcher] + args

def _deployment(model_id):
    code, body = es("GET", f"/_ml/trained_models/{model_id}/_stats", ok=(200, 404))
    if code != 200 or not body.get("trained_model_stats"):
        return None
    d = body["trained_model_stats"][0].get("deployment_stats")
    return d[0] if isinstance(d, list) and d else d

def _models_cfg():
    f = os.environ.get("MODELS_FILE")
    return json.load(open(f)) if f else load("models", "models.json")

def models(dry=False, restart=False):
    global FAILURES
    cfg = _models_cfg()
    print("models" + (" (dry run)" if dry else ""))
    for m in cfg["models"]:
        mid, want = m["model_id"], m["deployment"]
        code, _ = es("GET", f"/_ml/trained_models/{mid}", ok=(200, 404))
        if code == 404:
            cmd = _eland_cmd(m, cfg["eland_image"])
            print(f"  import {mid} <- {m['hub_model_id']} ({m['task_type']})")
            if dry or not shutil.which("docker"):
                print("    " + ("run: " if not dry else "would run: ") + " ".join(shlex.quote(c) for c in cmd))
                if not dry: print("    docker not found: run the command above on a host with Docker, then re-run 'models'")
                continue
            r = subprocess.run(cmd)
            if r.returncode != 0:
                FAILURES += 1
                print(f"  ERR import {mid} failed (exit {r.returncode})"); continue
        dep = _deployment(mid)
        threads = want.get("threads_per_allocation", 1)
        adaptive = want.get("adaptive_allocations")
        if dep and dep.get("state") in ("started", "starting") and restart and dep.get("threads_per_allocation") != threads:
            print(f"  restart {mid}: threads {dep.get('threads_per_allocation')} -> {threads}")
            if not dry:
                report(f"stop {mid}", es("POST", f"/_ml/trained_models/{mid}/deployment/_stop?force=true"))
            dep = None
        if not dep or dep.get("state") not in ("started", "starting"):
            q = f"threads_per_allocation={threads}&priority={want.get('priority', 'normal')}&wait_for=started&timeout=10m"
            body = None
            if adaptive: body = {"adaptive_allocations": adaptive}
            else: q += f"&number_of_allocations={want.get('number_of_allocations', 1)}"
            print(f"  start {mid}: {threads} thread(s) x " + (f"adaptive {adaptive['min_number_of_allocations']}-{adaptive['max_number_of_allocations']}" if adaptive else f"{want.get('number_of_allocations', 1)} allocation(s)"))
            if not dry:
                report(f"start {mid}", es("POST", f"/_ml/trained_models/{mid}/deployment/_start?{q}", body))
            continue
        # running: bring allocations in line
        cur_ad = dep.get("adaptive_allocations") or {}
        if adaptive:
            same = cur_ad.get("enabled") and cur_ad.get("min_number_of_allocations") == adaptive["min_number_of_allocations"] and cur_ad.get("max_number_of_allocations") == adaptive["max_number_of_allocations"]
            upd = None if same else {"adaptive_allocations": adaptive}
        else:
            n = want.get("number_of_allocations", 1)
            same = not cur_ad.get("enabled") and dep.get("number_of_allocations") == n
            upd = None if same else {"number_of_allocations": n, "adaptive_allocations": {"enabled": False}}
        note = "" if dep.get("threads_per_allocation") == threads else f" (threads {dep.get('threads_per_allocation')} != {threads}: re-run with --restart)"
        if upd is None:
            print(f"  ok  {mid}: already as configured{note}")
        else:
            print(f"  update {mid}: {json.dumps(upd)}{note}")
            if not dry:
                report(f"update {mid}", es("POST", f"/_ml/trained_models/{dep.get('deployment_id', mid)}/deployment/_update", upd))

def models_status():
    cfg = _models_cfg()
    print(f"{'model':48} {'state':9} {'alloc':>9} {'avg ms':>8} {'pending':>7} {'errors':>6}  nodes")
    for m in cfg["models"]:
        d = _deployment(m["model_id"])
        if not d:
            print(f"{m['model_id']:48} {'missing' if es('GET', '/_ml/trained_models/' + m['model_id'], ok=(200, 404))[0] == 404 else 'stopped':9}"); continue
        nodes = [n for n in d.get("nodes", []) if (n.get("routing_state") or {}).get("routing_state") == "started"]
        cnt = sum(n.get("inference_count", 0) for n in nodes)
        avg = (sum(n.get("average_inference_time_ms", 0) * n.get("inference_count", 0) for n in nodes) / cnt) if cnt else 0
        ad = d.get("adaptive_allocations") or {}
        alloc = f"{d.get('number_of_allocations')}x{d.get('threads_per_allocation')}" + ("A" if ad.get("enabled") else "")
        names = sorted({list(n["node"].values())[0].get("name", "?") for n in nodes})
        print(f"{m['model_id']:48} {d.get('state', '?'):9} {alloc:>9} {avg:8.0f} {sum(n.get('number_of_pending_requests', 0) for n in nodes):7} "
              f"{sum(n.get('error_count', 0) + n.get('rejected_execution_count', 0) + n.get('timeout_count', 0) for n in nodes):6}  {','.join(names)}")
    print("alloc: allocations x threads, A = adaptive. avg ms is per request since the deployment started.")

def classify(text):
    pipe = f"logs-claude_code.transcript-{PKG_VERSION}-classify"
    doc = {"message": text, "claude_code": {"human_prompt": True}}
    import time; t = time.time()
    f = os.environ.get("CLASSIFY_PIPELINE_FILE")       # test an edited classify.yml before rebuilding the package
    if f:
        try:
            import yaml
        except ImportError:
            sys.exit("CLASSIFY_PIPELINE_FILE needs PyYAML (pip install pyyaml)")
        pipe = f"{f} (not installed, simulated inline)"
        code, body = es("POST", "/_ingest/pipeline/_simulate", {"pipeline": yaml.safe_load(open(f)), "docs": [{"_source": doc}]})
    else:
        code, body = es("POST", f"/_ingest/pipeline/{pipe}/_simulate", {"docs": [{"_source": doc}]})
    if code >= 300:
        sys.exit(f"ERR {code}: {json.dumps(body)[:400]}")
    src = body["docs"][0].get("doc", {}).get("_source", {})
    pc = src.get("claude_code", {}).get("prompt_classification", {})
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

CMDS = {"pricing": pricing, "inference-mapping": inference_mapping, "rules": rules, "inference-monitoring": inference_monitoring}
if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["models"]:
        models(dry="--dry-run" in args, restart="--restart" in args)
        if FAILURES: print(f"{FAILURES} step(s) failed"); sys.exit(1)
        sys.exit()
    if args[:1] == ["models-status"]:
        models_status(); sys.exit()
    if args[:1] == ["classify"] and len(args) == 2:
        classify(args[1]); sys.exit()
    if not args or any(a not in CMDS and a != "all" for a in args):
        sys.exit(__doc__)
    for a in (list(CMDS) if "all" in args else args):
        CMDS[a]()
