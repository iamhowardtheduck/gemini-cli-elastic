#!/usr/bin/env python3
"""Generate the Gemini CLI Transcripts ML inference pipelines, inference fields, dashboards and
detection rules from their Claude Code Transcripts counterparts.

    python3 tools/port_gemini.py          # rewrite the generated files
    python3 tools/port_gemini.py --check  # exit 1 if a generated file is out of date

Re-run it after changing the Claude secret redaction, inference pipelines, dashboards or rules. Generated files:
  packages/gemini_cli_transcripts/data_stream/transcript/elasticsearch/ingest_pipeline/default.yml
      (only the secret-scanner functions and their params inside the redact-secrets processor)
  packages/gemini_cli_transcripts/data_stream/transcript/elasticsearch/ingest_pipeline/{inference,classify}.yml
  packages/gemini_cli_transcripts/data_stream/transcript/fields/inference-fields.yml
  packages/gemini_cli_transcripts/kibana/dashboard/gemini_cli_transcripts-{business,security}.json
  extras/detection-rules/gemini-cli-rules.ndjson

Everything product-specific is listed below: field renames, Claude-only panels and rules that are
dropped or replaced, spend panels priced from the gemini-model-pricing lookup, and wording.
"""
import json, os, re, sys
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the Claude Code sources live in a checkout of iamhowardtheduck/claude-code-elastic (default: next to this repository)
CLAUDE_ROOT = os.path.abspath(os.environ.get("CLAUDE_REPO") or os.path.join(ROOT, "..", "claude-code-elastic"))
SRC = os.path.join(CLAUDE_ROOT, "packages", "claude_code_transcripts")
if not os.path.isdir(SRC):
    sys.exit(f"Claude Code sources not found in {CLAUDE_ROOT}; clone iamhowardtheduck/claude-code-elastic there or set CLAUDE_REPO")
DST = os.path.join(ROOT, "packages", "gemini_cli_transcripts")
DS_SRC = os.path.join(SRC, "data_stream", "transcript")
DS_DST = os.path.join(DST, "data_stream", "transcript")
OUT = {}  # path -> content


def must_replace(text, old, new, count=None, what=""):
    n = text.count(old)
    if n == 0 or (count is not None and n != count):
        sys.exit(f"port_gemini: expected {count or 'some'} occurrence(s) of {old[:70]!r} {what}, found {n}")
    return text.replace(old, new)


# ---------------------------------------------------------------- field and wording map
# Order matters: specific Claude fields before the generic claude_code. -> gemini_cli. rename.
FIELD_MAP = [
    ("logs-claude_code.transcript-*", "logs-gemini_cli.transcript-*"),
    ("claude_code.sessionId", "gen_ai.conversation.id"),
    ("claude_code.project_slug", "gemini_cli.project"),
    ("claude_code.message.content.name", "gemini_cli.tool_names"),
    ("claude_code.", "gemini_cli."),
]
# credential files: Claude's own -> Gemini CLI's own and gcloud's
SENSITIVE_OLD = 'OR fp LIKE """*/.claude/.credentials.json""" OR fp LIKE """*/.claude.json"""'
SENSITIVE_NEW = ('OR fp LIKE """*/.gemini/oauth_creds.json""" OR fp LIKE """*/.gemini/google_accounts.json""" '
                 'OR fp LIKE """*/.config/gcloud/application_default_credentials.json""" '
                 'OR fp LIKE """*/.config/gcloud/credentials.db""" OR fp LIKE """*/.config/gcloud/access_tokens.db"""')


def map_fields(s):
    for a, b in FIELD_MAP:
        s = s.replace(a, b)
    return s


def map_esql(q):
    q = q.replace(SENSITIVE_OLD, SENSITIVE_NEW)
    return map_fields(q)


# ---------------------------------------------------------------- 0. secret scanner (redact-secrets)
def _scanner_regions(text, start_marker, cond_line):
    """(helpers, params) line ranges of the redact-secrets processor that starts after start_marker."""
    L = text.split("\n")
    i = next(n for n, l in enumerate(L) if l.strip() == start_marker)
    s = next(n for n in range(i, len(L)) if L[n].strip() == "source: |") + 1
    e = next(n for n in range(s, len(L)) if L[n].strip().startswith("// ---- main"))
    p = next(n for n in range(e, len(L)) if L[n] == "    params:")
    q = next(n for n in range(p, len(L)) if L[n] == cond_line)
    return L, (s, e), (p, q)


def scanner():
    src = open(os.path.join(DS_SRC, "elasticsearch", "ingest_pipeline", "default.yml")).read()
    L, (s, e), (p, q) = _scanner_regions(src, "description: Detect and redact secrets in message, message.content and wireToolInputs (type + length only)",
                                         "    if: ctx.claude_code != null")
    helpers, params = L[s:e], L[p:q]
    dst_path = os.path.join(DS_DST, "elasticsearch", "ingest_pipeline", "default.yml")
    dst = open(dst_path).read()
    D, (s2, e2), (p2, q2) = _scanner_regions(dst, "description: Detect and redact secrets in message, content, toolCalls and thoughts (type + length only)",
                                             "    if: ctx.gemini_cli != null")
    D = D[:s2] + helpers + D[e2:p2] + params + D[q2:]
    OUT[dst_path] = "\n".join(D)


# ---------------------------------------------------------------- 1. inference pipelines
def pipelines():
    for name in ("inference.yml", "classify.yml"):
        t = open(os.path.join(DS_SRC, "elasticsearch", "ingest_pipeline", name)).read()
        t = t.replace("claude_code_embed", "gemini_cli_embed").replace("claude_code_classify", "gemini_cli_classify")
        t = t.replace("Claude Code transcripts", "Gemini CLI transcripts").replace("claude-code-transcript", "gemini-cli-transcript")
        if name == "classify.yml":
            t = must_replace(t, "a question about Claude itself", "a question about Gemini itself", 2)
            t = must_replace(t, "      ner_ignore:\n      - Claude\n      - Anthropic\n      - Claude Code\n",
                             "      ner_ignore:\n      - Gemini\n      - Gemini CLI\n      - Google\n", 1)
        t = t.replace("claude_code", "gemini_cli")
        left = [l for l in t.splitlines() if re.search(r"(?i)claude|anthropic", l)]
        if left:
            sys.exit(f"port_gemini: {name} still mentions Claude: {left[:3]}")
        OUT[os.path.join(DS_DST, "elasticsearch", "ingest_pipeline", name)] = t


# ---------------------------------------------------------------- 2. inference fields
def inference_fields():
    f = yaml.safe_load(open(os.path.join(DS_SRC, "fields", "fields.yml")))
    cc = next(x for x in f if x["name"] == "claude_code")
    keep = ("inference", "prompt_classification", "prompt_embedding_error", "prompt_embedding_model")
    sub = [c for c in cc["fields"] if c["name"] in keep]
    if len(sub) != len(keep):
        sys.exit("port_gemini: inference fields missing in the Claude package")
    doc = [{"name": "gemini_cli", "type": "group", "fields": sub}]
    head = "# Generated by tools/port_gemini.py from the Claude Code Transcripts fields. Do not edit.\n"
    OUT[os.path.join(DS_DST, "fields", "inference-fields.yml")] = head + map_fields(yaml.safe_dump(doc, sort_keys=False, width=1000))


# ---------------------------------------------------------------- 3. dashboards
# Token columns for spend panels. Gemini's prompt count includes cached tokens; output excludes thinking.
TOK = ("FROM logs-gemini_cli.transcript-* | WHERE gen_ai.usage.input_tokens IS NOT NULL"
       " | EVAL cr = COALESCE(gen_ai.usage.cache_read.input_tokens, 0), th = COALESCE(gemini_cli.tokens.thoughts, 0)"
       " | EVAL i = gen_ai.usage.input_tokens - cr, o = gen_ai.usage.output_tokens - th, project = gemini_cli.project, session = gen_ai.conversation.id")
TOTAL = "i + cr + o + th"
# Spend: list prices from the gemini-model-pricing lookup (extras/setup.sh pricing). Per model turn, the
# announced next price applies from pricing.price_change_date, and the long-context price above
# pricing.long_context_threshold prompt tokens. Thinking tokens are billed at the output price.
COST = (TOK + " | LOOKUP JOIN gemini-model-pricing ON gen_ai.response.model"
        " | EVAL nxt = pricing.price_change_date IS NOT NULL AND @timestamp >= pricing.price_change_date,"
        " lng = pricing.long_context_threshold IS NOT NULL AND gen_ai.usage.input_tokens > pricing.long_context_threshold"
        " | EVAL pin = CASE(nxt, pricing.next_input_per_mtok, lng, pricing.long_input_per_mtok, pricing.input_per_mtok),"
        " pout = CASE(nxt, pricing.next_output_per_mtok, lng, pricing.long_output_per_mtok, pricing.output_per_mtok),"
        " pcr = CASE(nxt, pricing.next_cache_read_per_mtok, lng, pricing.long_cache_read_per_mtok, pricing.cache_read_per_mtok)"
        " | EVAL cost = (i * pin + (o + th) * pout + cr * pcr) / 1000000.0")
TOKEN_PANELS = {
    # panel id: (title or None to keep, query, {old column: new column}, keep currency format)
    "b-spend": (None, COST + " | STATS `Estimated spend (USD)` = SUM(cost)", {}, True),
    "b-tokens": (None, TOK + f" | STATS `Tokens processed` = SUM({TOTAL})", {}, False),
    "b-cache": (None, TOK + " | STATS t = SUM(i + cr), r = SUM(cr) | EVAL `Cache hit rate` = TO_DOUBLE(r) / t | KEEP `Cache hit rate`", {}, False),
    "b-per-session": (None, COST + " | STATS c = SUM(cost), s = COUNT_DISTINCT(session) | EVAL `Avg spend per session` = c / s | KEEP `Avg spend per session`", {}, True),
    "b-spend-time": (None, COST + " | WHERE @timestamp <= ?_tend AND @timestamp > ?_tstart | STATS spend = SUM(cost) BY BUCKET(@timestamp, 40, ?_tstart, ?_tend), user.name", {}, True),
    "b-spend-project": (None, COST + " | STATS spend = SUM(cost) BY project | SORT spend DESC | LIMIT 12", {}, True),
    "b-tokmix": (None, COST + ' | STATS a = SUM(i * pin), b = SUM(o * pout), c = SUM(cr * pcr), d = SUM(th * pout) | EVAL type = ["Input","Output","Cache read","Thinking"] | MV_EXPAND type'
                 ' | EVAL spend = CASE(type == "Input", a, type == "Output", b, type == "Cache read", c, d) / 1000000.0 | KEEP type, spend', {}, True),
    "b-user-model": (None, COST + " | STATS `Spend (USD)` = SUM(cost), `Input` = SUM(i), `Output` = SUM(o), `Cache read` = SUM(cr), `Thinking` = SUM(th), `Model turns` = COUNT(*)"
                     " BY `User` = user.name, `Model` = gen_ai.response.model | SORT `Spend (USD)` DESC",
                     {"Cache write": "Thinking", "API calls": "Model turns"}, True),
}
TITLES = {
    "What Claude is used for (semantic topic of human prompts)": "What Gemini CLI is used for (semantic topic of human prompts)",
    "When Claude is used (human prompts, UTC)": "When Gemini CLI is used (human prompts, UTC)",
    "Risky shell commands run by Claude": "Risky shell commands run by Gemini CLI",
}
TOPIC = [('"configure Claude Code settings, skills, agents, prompts and plugins"',
          '"configure Gemini CLI settings, extensions, GEMINI.md context, MCP servers and custom commands"'),
         ('"Claude & AI tooling"', '"Gemini & AI tooling"')]
# Claude-only panels (auto-mode classifier) -> Gemini tool-call failures, same grid slots
FAILED_METRIC = ('FROM logs-gemini_cli.transcript-* | WHERE event.action == "tool-use" AND event.outcome == "failure" | STATS `Failed tool calls` = COUNT(*)',
                 {"Auto-mode blocks": "Failed tool calls"})
FAILED_CHART = ('FROM logs-gemini_cli.transcript-* | WHERE event.action == "tool-use" AND event.outcome == "failure" | MV_EXPAND gemini_cli.tool_names'
                ' | STATS failures = COUNT(*) BY tool = gemini_cli.tool_names | SORT failures DESC | LIMIT 10', {"blocks": "failures", "category": "tool"})


def layer(p):
    layers = p["embeddableConfig"]["attributes"]["state"]["datasourceStates"]["textBased"]["layers"]
    if len(layers) != 1:
        sys.exit(f"port_gemini: panel {p['gridData']['i']} has {len(layers)} layers")
    return next(iter(layers.values()))


def set_query(p, q, cols, keep_currency=False):
    lay = layer(p)
    lay["query"]["esql"] = q
    p["embeddableConfig"]["attributes"]["state"]["query"]["esql"] = q
    names = {c["fieldName"] for c in lay["columns"]}
    for old in cols:
        if old not in names:
            sys.exit(f"port_gemini: panel {p['gridData']['i']} has no column {old!r} ({names})")
    for c in lay["columns"]:
        c["fieldName"] = cols.get(c["fieldName"], c["fieldName"])
        fmt = c.get("params", {}).get("format", {})
        if "$" in json.dumps(fmt) and not keep_currency:   # currency -> plain number
            c["params"]["format"] = {"id": "number", "params": {"decimals": 0}}
        if c.get("customLabel") and c.get("label") in cols:
            c["label"] = cols[c["label"]]


def port_panel_json(p):
    s = json.dumps(p)
    s = s.replace(json.dumps(SENSITIVE_OLD)[1:-1], json.dumps(SENSITIVE_NEW)[1:-1])
    for a, b in TOPIC:
        s = s.replace(json.dumps(a)[1:-1], json.dumps(b)[1:-1])
    s = s.replace('claude_code.message.content.is_error == true', 'event.action == \\"tool-result\\" AND event.outcome == \\"failure\\"')
    s = map_fields(s)
    p = json.loads(s)
    t = p["embeddableConfig"].get("title")
    if t in TITLES:
        p["embeddableConfig"]["title"] = TITLES[t]
    return p


def dashboard(src_name, dst_name, kind):
    d = json.load(open(os.path.join(SRC, "kibana", "dashboard", src_name)))
    a = d["attributes"]
    panels = json.loads(a["panelsJSON"])
    out = []
    for p in panels:
        pid = p["gridData"]["i"]
        p = port_panel_json(p)
        if pid in TOKEN_PANELS:
            title, q, cols, cur = TOKEN_PANELS[pid]
            set_query(p, q, cols, cur)
            if title:
                p["embeddableConfig"]["title"] = title
        elif pid == "s-blocked":
            set_query(p, *FAILED_METRIC)
        elif pid == "s-blocked-cat":
            set_query(p, *FAILED_CHART)
            p["embeddableConfig"]["title"] = "Failed tool calls by tool"
        elif pid == "s-time":
            q = layer(p)["query"]["esql"]
            q2 = re.sub(r'gemini_cli\.toolDenialKind == "automode-blocked", "[^"]+", ', "", q)
            if q2 == q:
                sys.exit("port_gemini: s-time auto-mode series not found")
            set_query(p, q2, {})
        out.append(p)
    a["panelsJSON"] = json.dumps(out, separators=(",", ":"))
    d["id"] = f"gemini_cli_transcripts-{kind}"
    a["title"] = {"business": "[Gemini CLI Transcripts] Business Analytics", "security": "[Gemini CLI Transcripts] Security"}[kind]
    a["description"] = {
        "business": "Who uses Gemini CLI, for what (semantic topic + task classifier), and what it costs. Spend is an estimate: token usage per model turn joined with Google list prices in the gemini-model-pricing lookup index (extras/gemini/setup.sh pricing).",
        "security": "Security signals from Gemini CLI transcripts: classifier flags, semantic similarity to malicious intent (Jina embeddings), redacted secrets, risky commands, sensitive file access and failed tool calls. Paired with detection rules tagged 'Gemini CLI'.",
    }[kind]
    s = json.dumps(d)
    left = sorted(set(re.findall(r"claude_code\.[A-Za-z_.]+|toolDenialKind|permissionDecision|claude-model-pricing|\.claude\b", s)))
    if left:
        sys.exit(f"port_gemini: {dst_name} still references {left}")
    if re.search(r"(?i)claude", json.dumps(d)):
        hits = sorted(set(m.group(0) for m in re.finditer(r"(?i).{30}claude.{30}", json.dumps(d))))
        sys.exit(f"port_gemini: {dst_name} still mentions Claude: {hits[:5]}")
    OUT[os.path.join(DST, "kibana", "dashboard", dst_name)] = json.dumps(d, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- 4. detection rules
SKIP_RULES = {"claude-code-automode-block", "claude-code-automode-block-burst"}   # Claude auto-mode classifier only
RULE_TEXT = [
    ("Claude Code file tool (Read, Edit, Write)", "Gemini CLI file tool (read_file, write_file, replace, read_many_files)"),
    ("Claude's own credentials", "Gemini CLI's own and gcloud credentials"),
    ("Claude Code tool call (WebFetch URL or shell command)", "Gemini CLI tool call (web_fetch URL or shell command)"),
    (" (claude_code.prompt_classification.semantic, package 0.1.2+)", " (gemini_cli.prompt_classification.semantic)"),
    ("A human prompt sent to Claude Code", "A human prompt sent to Gemini CLI"),
    ("in a Claude Code prompt", "in a Gemini CLI prompt"),
    ("Claude Code executed", "Gemini CLI executed"),
    ("Dashboard: [Claude Code Transcripts] Security (claude-transcripts-security)", "Dashboard: [Gemini CLI Transcripts] Security"),
    ("Dashboard: [Claude Code Transcripts] Security", "Dashboard: [Gemini CLI Transcripts] Security"),
    ("real prompts 1 of 147", "real Claude Code prompts 1 of 147"),   # evaluation was on Claude Code prompts; say so
]


def rules():
    out = []
    pkg = yaml.safe_load(open(os.path.join(DST, "manifest.yml")))
    for line in open(os.path.join(CLAUDE_ROOT, "extras", "detection-rules", "claude-code-rules.ndjson")):
        r = json.loads(line)
        if "rule_id" not in r or r["rule_id"] in SKIP_RULES:
            continue
        r["rule_id"] = r["rule_id"].replace("claude-code-", "gemini-cli-")
        r["name"] = must_replace(r["name"], "Claude Code - ", "Gemini CLI - ", 1)
        r["query"] = map_esql(r["query"])
        for k in ("description", "note"):
            for a, b in RULE_TEXT:
                r[k] = r[k].replace(a, b)
            r[k] = map_fields(r[k])
        r["tags"] = ["Gemini CLI", "Gemini CLI Transcripts", "Domain: LLM", "Data Source: Gemini CLI"]
        r["related_integrations"] = [{"package": "gemini_cli_transcripts", "version": "^" + pkg["version"]}]
        r["author"] = ["claude-code-elastic"]
        r["version"] = 1
        s = json.dumps(r, ensure_ascii=False)
        left = [m.group(0) for m in re.finditer(r"(?i).{25}(claude|anthropic).{25}", s.replace("claude-code-elastic", "")
                                                    .replace("real Claude Code prompts", ""))]
        if left:
            sys.exit(f"port_gemini: rule {r['rule_id']} still mentions Claude: {left[:3]}")
        out.append(s)
    if len(out) != 8:
        sys.exit(f"port_gemini: expected 8 rules, built {len(out)}")
    OUT[os.path.join(ROOT, "extras", "detection-rules", "gemini-cli-rules.ndjson")] = "\n".join(out) + "\n"


if __name__ == "__main__":
    scanner(); pipelines(); inference_fields()
    dashboard("claude_code_transcripts-business.json", "gemini_cli_transcripts-business.json", "business")
    dashboard("claude_code_transcripts-security.json", "gemini_cli_transcripts-security.json", "security")
    rules()
    stale = []
    for path, content in OUT.items():
        cur = open(path).read() if os.path.exists(path) else None
        if cur != content:
            stale.append(os.path.relpath(path, ROOT))
            if "--check" not in sys.argv:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w").write(content)
    if "--check" in sys.argv:
        print("out of date: " + ", ".join(stale) if stale else "generated files are up to date")
        sys.exit(1 if stale else 0)
    print("wrote " + (", ".join(stale) if stale else "nothing (up to date)"))
