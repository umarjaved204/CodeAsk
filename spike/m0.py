"""M0 spike: prove the free tiers work end to end, and measure them.

Throwaway code: one file, no abstractions, no tests. Every retry is capped.

Subcommands (run from the project root with the venv active):
    python spike/m0.py count  repos/itsdangerous      token counts, no API calls
    python spike/m0.py ingest repos/itsdangerous      embed new chunks, store in Neon
    python spike/m0.py ask    itsdangerous "question" retrieve + Groq answer
    python spike/m0.py sanity itsdangerous            known-answer questions: rank, hit@5, MRR
    python spike/m0.py demo   4                        N users' queries within 60 s, raw HTTP
    python spike/m0.py tools                           Groq tool tests A and B, 5 runs each
    python spike/m0.py gemini                          one tiny Gemini call
"""

import argparse
import hashlib
import json
import os
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import groq
import psycopg
import requests
import voyageai
from dotenv import load_dotenv
from google import genai
from voyageai.error import RateLimitError

ROOT = Path(__file__).resolve().parent.parent
REPOS = ROOT / "repos"
load_dotenv(ROOT / ".env")

EMBED_MODEL = "voyage-code-3"  # trained on code: "verify a signature" lands near def verify(...)
EMBED_DIM = 1024
GROQ_MODEL = "openai/gpt-oss-120b"
GEMINI_MODEL = "gemini-flash-latest"
MAX_OUTPUT_TOKENS = 600

# Naive chunking on purpose: the baseline M1's function-level chunking must beat.
# Overlap means code that straddles a window boundary still appears whole once.
CHUNK_LINES = 60
OVERLAP = 10
TOP_K = 5

# Voyage without a card: 3 requests and 10K tokens per minute.
VOYAGE_RPM = 3
VOYAGE_TPM = 10_000
BATCH_TOKENS = 9_000
MAX_RETRIES = 3

# ---------- File filtering ----------
# With a 10K tokens/min budget, every embedded token should be something a user
# might ask about. Lockfiles, build output and changelogs never are.
SOURCE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".c", ".h",
              ".cpp", ".cs", ".php", ".swift", ".kt", ".vue", ".svelte", ".sql", ".sh"}
DOC_EXT = {".md", ".rst"}
SKIP_DIRS = {".git", ".github", "node_modules", "dist", "build", "vendor", ".venv", "venv",
             "__pycache__", ".next", "out", "coverage", "target"}
SKIP_NAME_PREFIXES = ("changes", "changelog", "license", "history")
MAX_FILE_BYTES = 100_000


def classify(path: Path, repo_dir: Path):
    """Return 'source', 'tests', 'docs', or None to skip."""
    rel = path.relative_to(repo_dir)
    name = path.name.lower()
    if any(part in SKIP_DIRS for part in rel.parts[:-1]):
        return None
    if path.stat().st_size > MAX_FILE_BYTES or ".min." in name:
        return None
    if path.suffix in DOC_EXT:
        return None if name.startswith(SKIP_NAME_PREFIXES) else "docs"
    if path.suffix not in SOURCE_EXT:
        return None
    is_test = (
        any(part in {"test", "tests", "__tests__", "spec"} for part in rel.parts[:-1])
        or name.startswith("test_") or name.endswith("_test.py")
        or ".test." in name or ".spec." in name
    )
    return "tests" if is_test else "source"


def chunk_repo(repo_dir: Path, categories):
    chunks = []
    step = CHUNK_LINES - OVERLAP
    for f in sorted(repo_dir.rglob("*")):
        if not f.is_file():
            continue
        category = classify(f, repo_dir)
        if category not in categories:
            continue
        path = f.relative_to(repo_dir).as_posix()
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        for start in range(0, max(len(lines), 1), step):
            end = min(start + CHUNK_LINES, len(lines))
            content = "\n".join(lines[start:end])
            if content.strip():
                chunks.append({
                    "path": path, "start": start + 1, "end": end, "content": content,
                    "category": category,
                    # The path prefix gives the embedding a hint the code alone may lack.
                    "text": f"File: {path}\n\n{content}",
                })
            if end == len(lines):
                break
    return chunks


def chunk_key(repo, c):
    # The model is part of the key: vectors from different models live in different
    # spaces, so switching models must re-embed everything.
    raw = f"{EMBED_MODEL}\n{repo}\n{c['path']}\n{c['start']}\n{c['text']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def to_vec(embedding):
    # pgvector accepts the text form '[0.1,0.2,...]'; we never read vectors back,
    # so the pgvector package would only add a dependency.
    return "[" + ",".join(map(str, embedding)) + "]"


# ---------- Neon ----------

def connect_neon(timings):
    # prepare_threshold=None: Neon's pooler (PgBouncer) shares server connections
    # between clients, which can break psycopg's automatic prepared statements.
    print("Connecting to Neon...", flush=True)
    url = os.environ["DATABASE_URL"]
    # Local workaround: Neon's hostname returns IPv6 addresses first, and from my home
    # network libpq stalled on them (~90 s). hostaddr pins an IPv4 address; libpq still
    # uses the hostname for TLS/SNI, which Neon needs to route to the right endpoint.
    host = urlparse(url).hostname
    ipv4 = socket.getaddrinfo(host, 5432, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    t0 = time.perf_counter()
    conn = psycopg.connect(url, hostaddr=ipv4, autocommit=True, prepare_threshold=None,
                           connect_timeout=30)
    timings["neon_connect_s"] = round(time.perf_counter() - t0, 2)
    print(f"  connected in {timings['neon_connect_s']}s via IPv4 {ipv4}", flush=True)
    t0 = time.perf_counter()
    conn.execute("SELECT 1")
    timings["neon_first_query_s"] = round(time.perf_counter() - t0, 3)
    t0 = time.perf_counter()
    conn.execute("SELECT 1")
    timings["neon_second_query_s"] = round(time.perf_counter() - t0, 3)

    print("  checking schema...", flush=True)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # No vector index: exact search over a few hundred rows takes milliseconds and has
    # perfect recall. Approximate indexes (HNSW) pay off at tens of thousands of rows.
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS m0_chunks (
            id bigserial PRIMARY KEY,
            repo text NOT NULL,
            path text NOT NULL,
            start_line int NOT NULL,
            end_line int NOT NULL,
            content text NOT NULL,
            chunk_key text UNIQUE NOT NULL,
            embedding vector({EMBED_DIM}) NOT NULL
        )
    """)
    return conn


def search(conn, repo, q_emb, k, exclude=None):
    # <=> is cosine distance: compares what vectors are "about" (direction),
    # not their length. 0 = identical direction.
    sql = ("SELECT path, start_line, end_line, content, embedding <=> %s::vector AS distance"
           " FROM m0_chunks WHERE repo = %s")
    params = [to_vec(q_emb), repo]
    if exclude:
        sql += " AND path NOT LIKE %s"
        params.append(f"%{exclude}%")
    sql += " ORDER BY distance LIMIT %s"
    params.append(k)
    return conn.execute(sql, params).fetchall()


# ---------- Voyage (SDK, paced) ----------

_voyage_log = []  # (timestamp, tokens) of recent requests, for the sliding-window pacer


def voyage_client():
    return voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"], max_retries=0)


def voyage_embed(vo, texts, input_type, tokens, stats):
    """One paced Voyage call: waits until the last 60 s has room for another request
    and `tokens` more tokens. input_type matters: questions and code look nothing
    alike, so Voyage embeds them asymmetrically ("query" vs "document")."""
    while True:
        now = time.time()
        _voyage_log[:] = [(t, n) for t, n in _voyage_log if now - t < 60]
        used = sum(n for _, n in _voyage_log)
        # Also space requests >= 20 s apart, in case Voyage uses a refilling bucket
        # (1 request per 20 s) rather than a fixed 60 s window.
        gap = 60 / VOYAGE_RPM - (now - _voyage_log[-1][0]) if _voyage_log else 0
        if len(_voyage_log) < VOYAGE_RPM and used + tokens <= VOYAGE_TPM and gap <= 0:
            break
        wait = max(gap, 0.5) if len(_voyage_log) < VOYAGE_RPM and used + tokens <= VOYAGE_TPM \
            else 60 - (now - _voyage_log[0][0]) + 0.5
        print(f"  pacer: waiting {wait:.0f}s ({len(_voyage_log)} requests, {used} tokens in last 60s)")
        time.sleep(wait)

    for attempt in range(MAX_RETRIES + 1):
        _voyage_log.append((time.time(), tokens))
        try:
            return vo.embed(texts, model=EMBED_MODEL, input_type=input_type)
        except RateLimitError as e:
            stats["429s"] = stats.get("429s", 0) + 1
            headers = dict(getattr(e, "headers", None) or {})
            retry_after = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
            rl = {k: v for k, v in headers.items() if "ratelimit" in k.lower()}
            print(f"  429 from Voyage (attempt {attempt + 1}, request ~{tokens} tokens);"
                  f" Retry-After={retry_after!r} {rl or ''}")
            stats["retry_after_seen"] = stats.get("retry_after_seen", False) or retry_after is not None
            if attempt == MAX_RETRIES:
                raise
            time.sleep(float(retry_after) if retry_after else 60)


# ---------- Subcommands ----------

def cmd_count(args):
    repo_dir = Path(args.repo_dir).resolve()
    chunks = chunk_repo(repo_dir, {"source", "tests", "docs"})
    vo = voyage_client()
    print(f"{repo_dir.name}: counting tokens locally with the {EMBED_MODEL} tokenizer (no API calls)")
    total_tokens = 0
    for category in ("source", "tests", "docs"):
        cs = [c for c in chunks if c["category"] == category]
        tokens = vo.count_tokens([c["text"] for c in cs], model=EMBED_MODEL) if cs else 0
        files = len({c["path"] for c in cs})
        total_tokens += tokens
        print(f"  {category:<7} files={files:<4} chunks={len(cs):<5} tokens={tokens}")
    # Time is bounded by whichever limit binds first: tokens/min or requests/min.
    requests_needed = max(1, -(-total_tokens // BATCH_TOKENS))
    minutes = max(total_tokens / VOYAGE_TPM, requests_needed / VOYAGE_RPM)
    print(f"  TOTAL   tokens={total_tokens} (overlap included)  est. ingest ≈ {minutes:.1f} min at no-card limits")


def cmd_ingest(args):
    repo_dir = Path(args.repo_dir).resolve()
    repo = repo_dir.name
    categories = set(args.categories.split(","))
    timings = {}
    conn = connect_neon(timings)
    vo = voyage_client()

    chunks = chunk_repo(repo_dir, categories)
    for c in chunks:
        c["key"] = chunk_key(repo, c)
    existing = {r[0] for r in conn.execute("SELECT chunk_key FROM m0_chunks WHERE repo = %s", (repo,))}
    current = {c["key"] for c in chunks}
    new = [c for c in chunks if c["key"] not in existing]
    stale = list(existing - current)
    if stale:
        conn.execute("DELETE FROM m0_chunks WHERE chunk_key = ANY(%s)", (stale,))
    print(f"{repo} [{args.categories}]: {len(chunks)} chunks, {len(new)} new, "
          f"{len(chunks) - len(new)} cached, {len(stale)} stale deleted")
    if not new:
        return

    # Exact token counts (code tokenizes very differently from prose, so a chars/4
    # guess can be off by 30%+). Then pack chunks into requests under BATCH_TOKENS.
    counts = [vo.count_tokens([c["text"]], model=EMBED_MODEL) for c in new]
    batches, batch, batch_tokens = [], [], 0
    for c, n in zip(new, counts):
        if batch and batch_tokens + n > args.batch_tokens:
            batches.append((batch, batch_tokens))
            batch, batch_tokens = [], 0
        batch.append(c)
        batch_tokens += n
    if batch:
        batches.append((batch, batch_tokens))

    stats = {}
    total_tokens = 0
    t0 = time.perf_counter()
    for i, (batch, est) in enumerate(batches, 1):
        result = voyage_embed(vo, [c["text"] for c in batch], "document", est, stats)
        total_tokens += result.total_tokens
        # Store after every batch so an interrupted run keeps its progress.
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO m0_chunks (repo, path, start_line, end_line, content, chunk_key, embedding)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s::vector) ON CONFLICT (chunk_key) DO NOTHING",
                [(repo, c["path"], c["start"], c["end"], c["content"], c["key"], to_vec(e))
                 for c, e in zip(batch, result.embeddings)],
            )
        print(f"  request {i}/{len(batches)}: {result.total_tokens} tokens, "
              f"{time.perf_counter() - t0:.0f}s elapsed")
    wall = time.perf_counter() - t0

    print("\n===== ingest measurements =====")
    print(json.dumps({
        "batch_tokens_limit": args.batch_tokens,
        "requests": len(batches), "tokens": total_tokens, "wall_s": round(wall, 1),
        "real_tokens_per_min": round(total_tokens / (wall / 60), 0) if wall > 1 else None,
        "voyage_429s": stats.get("429s", 0),
        "retry_after_seen": stats.get("retry_after_seen", "no 429s"),
        **timings,
    }, indent=2))


def cmd_ask(args):
    timings = {}
    conn = connect_neon(timings)
    vo = voyage_client()

    t0 = time.perf_counter()
    q_emb = voyage_embed(vo, [args.question], "query", 50, {}).embeddings[0]
    timings["voyage_query_embed_s"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    hits = search(conn, args.repo, q_emb, TOP_K)
    timings["neon_vector_search_s"] = round(time.perf_counter() - t0, 3)
    if not hits:
        print(f"No chunks for repo '{args.repo}'. Run ingest first.")
        return

    print(f"Top {TOP_K} chunks:")
    for p, s, e, _, d in hits:
        print(f"  {p}:{s}-{e}  (cosine distance {d:.3f})")

    client = groq_client()
    answer, info = groq_answer(client, REPOS / args.repo, args.question, hits, first_choice="auto")
    print(f"\nAnswer:\n{answer}\n")
    print("===== ask measurements =====")
    print(json.dumps({**timings, **info}, indent=2))


SANITY = {
    "itsdangerous": [
        ("How is the signing key derived from the secret key?", ["signer.py"]),
        ("How does it check that a timestamped signature hasn't expired (max_age)?", ["timed.py"]),
        ("How does the URL-safe serializer compress the payload?", ["url_safe.py"]),
        ("How does base64 decoding handle missing padding and errors?", ["encoding.py"]),
        ("How does it support rotating to a new secret key while old keys still work?",
         ["serializer.py", "signer.py"]),
    ],
    "TableTalk": [],  # 5 questions + expected files, written by me (I know this repo)
}


def cmd_sanity(args):
    questions = SANITY.get(args.repo) or []
    if not questions:
        print(f"No sanity questions for '{args.repo}' yet.")
        return
    conn = connect_neon({})
    vo = voyage_client()
    # All questions in ONE request: batching is how you live with 3 requests/min.
    q_embs = voyage_embed(vo, [q for q, _ in questions], "query", 50 * len(questions), {}).embeddings

    reciprocal_ranks, hits_at_5 = [], 0
    for (q, expected), q_emb in zip(questions, q_embs):
        rows = search(conn, args.repo, q_emb, 10)
        # Rank = position of the first chunk from an expected file (1-based), within top 10.
        rank = next((i for i, r in enumerate(rows, 1) if any(r[0].endswith(f) for f in expected)), None)
        reciprocal_ranks.append(1 / rank if rank else 0)
        hits_at_5 += bool(rank and rank <= 5)
        print(f"\nQ: {q}\n   expected {expected} -> rank {rank or 'not in top 10'}")
        for i, (p, s, e, _, d) in enumerate(rows[:5], 1):
            print(f"   {i}. {p}:{s}-{e}  ({d:.3f})")

    n = len(questions)
    print("\n===== sanity measurements =====")
    print(f"hit@5 = {hits_at_5}/{n} = {hits_at_5 / n:.2f}   MRR@10 = {sum(reciprocal_ranks) / n:.2f}")


DEMO_QUESTIONS = [
    "How do I sign a value with a secret key?",
    "What happens when a signature has expired?",
    "How can I serialize a dict into a URL-safe token?",
    "Which hash algorithm is used by default?",
    "How do I add a salt to a serializer?",
    "What exception is raised for a bad signature?",
]


def cmd_demo(args):
    """N simulated visitors, evenly spread over 60 s, each embedding a different
    question with raw HTTP (no pacer, no SDK) so we see Voyage's real behaviour."""
    n = args.n
    print("Waiting 61s so no earlier Voyage calls share this minute...")
    time.sleep(61)
    url = "https://api.voyageai.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"}
    t_start = time.time()
    log, results, lock = [], {}, threading.Lock()

    def visitor(i):
        scheduled = i * 60 / n
        time.sleep(scheduled)
        body = {"input": [DEMO_QUESTIONS[i]], "model": EMBED_MODEL, "input_type": "query"}
        backoff = 5
        for attempt in range(MAX_RETRIES + 1):
            sent = time.time() - t_start
            try:
                r = requests.post(url, json=body, headers=headers, timeout=30)
            except requests.RequestException as e:
                results[i] = {"error": f"network: {e}", "attempts": attempt + 1}
                return
            with lock:
                log.append((sent, i + 1, attempt + 1, r.status_code, r.headers.get("retry-after"),
                            {k: v for k, v in r.headers.items() if "ratelimit" in k.lower()}))
            if r.status_code == 200:
                results[i] = {"added_wait_s": round(sent - scheduled, 1), "attempts": attempt + 1}
                return
            if r.status_code != 429 or attempt == MAX_RETRIES:
                results[i] = {"error": f"HTTP {r.status_code}", "attempts": attempt + 1}
                return
            retry_after = r.headers.get("retry-after")
            time.sleep(float(retry_after) if retry_after else backoff)
            backoff *= 2  # 5, 10, 20 s

    threads = [threading.Thread(target=visitor, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"\nTimeline (seconds from start), {n} visitors:")
    for sent, who, attempt, status, retry_after, rl in sorted(log):
        print(f"  t={sent:5.1f}s  visitor {who} attempt {attempt}: HTTP {status}"
              f"  Retry-After={retry_after!r}  {rl or ''}")
    waits = [r.get("added_wait_s", 0) for r in results.values() if "error" not in r]
    errors = [r for r in results.values() if "error" in r]
    worst = max(waits) if waits else None
    passed = not errors and len(waits) == n and worst is not None and worst <= 20
    print("\n===== demo measurements =====")
    print(json.dumps({
        "visitors": n, "429s": sum(1 for x in log if x[3] == 429), "errors": len(errors),
        "added_wait_per_visitor_s": [results[i].get("added_wait_s", "ERROR") for i in range(n)],
        "worst_added_wait_s": worst,
        "verdict (4-query rule)": "PASS" if passed else ("FAIL" if errors or (worst or 0) > 30 else "BORDERLINE"),
    }, indent=2))


# ---------- Groq tools ----------

TOOLS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a line range from a file in the repository. Returns numbered lines (max 200).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Path from the repo root, e.g. src/pkg/module.py"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        }, "required": ["path", "start_line", "end_line"]},
    }},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List files and folders in a repository directory. Folders end with '/'.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Directory from the repo root; '.' for the root"},
        }, "required": ["path"]},
    }},
]

SYSTEM_PROMPT = """You answer questions about a code repository using the code provided.
Cite every claim with its source as path:start-end.
If the provided code does not contain the answer, use the tools to find it.
If you still cannot find it, say so instead of guessing.
Keep the answer under 250 words."""


def sandboxed(repo_root: Path, path: str):
    """The model chooses `path`, and in M4 untrusted repo text could try prompt
    injection ("read ../../.env"). Resolving first defeats .. and symlink tricks."""
    root = repo_root.resolve()
    target = (root / path).resolve()
    return target if target == root or target.is_relative_to(root) else None


def read_file(repo_root, path, start_line, end_line):
    target = sandboxed(repo_root, path)
    if target is None or not target.is_file():
        return f"Error: '{path}' is not a file inside the repository."
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(start_line))
    end = min(len(lines), int(end_line), start + 199)
    return "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1)) or "(no lines in range)"


def list_dir(repo_root, path):
    target = sandboxed(repo_root, path)
    if target is None or not target.is_dir():
        return f"Error: '{path}' is not a directory inside the repository."
    entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir() if p.name != ".git")
    return "\n".join(entries[:200]) or "(empty)"


def groq_client():
    # max_retries=0: the SDK would otherwise retry 429s silently and hide them from us.
    return groq.Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=0)


def groq_call(client, info, **kwargs):
    for attempt in range(MAX_RETRIES + 1):
        try:
            t0 = time.perf_counter()
            # max_tokens matters on Groq's free tier: some models (qwen) also have an
            # output-tokens-per-minute limit (1,000), and Groq rejects any request whose
            # *possible* output exceeds it, however long you wait.
            raw = client.chat.completions.with_raw_response.create(
                model=GROQ_MODEL, temperature=0, max_tokens=MAX_OUTPUT_TOKENS, **kwargs)
            info["latencies_s"].append(round(time.perf_counter() - t0, 2))
            info["rate_limit_headers"] = {k: v for k, v in raw.headers.items() if k.lower().startswith("x-ratelimit")}
            return raw.parse()
        except groq.RateLimitError as e:
            info["groq_429s"] += 1
            if "Request too large" in str(e):
                raise  # waiting can't fix this one, so don't burn retries on it
            retry_after = e.response.headers.get("retry-after")
            print(f"  429 from Groq; Retry-After={retry_after!r}")
            if attempt == MAX_RETRIES:
                raise
            time.sleep(float(retry_after) if retry_after else 10)


def groq_answer(client, repo_root, question, hits, first_choice):
    """Question + retrieved chunks -> answer, running tool calls in a capped loop.
    The last turn forbids tools so the loop always ends."""
    context = "\n\n".join(f"[{p}:{s}-{e}]\n{content}" for p, s, e, content, _ in hits)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Question: {question}\n\nRetrieved code:\n\n{context}"},
    ]
    info = {"latencies_s": [], "groq_429s": 0, "tool_calls": [], "tool_errors": 0, "bad_json": 0,
            "invalid_tool_calls": []}
    max_turns = 4
    for turn in range(max_turns):
        if turn == max_turns - 1:
            choice = "none"
        elif turn == 0:
            choice = first_choice
        else:
            choice = "auto"
        try:
            resp = groq_call(client, info, messages=messages, tools=TOOLS, tool_choice=choice)
        except groq.BadRequestError as e:
            # Groq validates tool calls server-side. If the model invents a tool that
            # wasn't offered (gpt-oss was trained with built-in tools like "search"),
            # Groq rejects the whole response. Feed the error back, like an agent would.
            body = e.body if isinstance(e.body, dict) else {}
            err = body.get("error", body)
            if err.get("code") != "tool_use_failed":
                raise
            failed = err.get("failed_generation", "")
            info["invalid_tool_calls"].append(failed[:150])
            print(f"  invalid tool call rejected by Groq: {failed[:150]}")
            # Pass Groq's reason back: better error feedback means better self-correction.
            messages.append({"role": "user", "content":
                f"Your last response was rejected: {err.get('message', '')[:300]} "
                "The only tools are read_file(path, start_line, end_line) and list_dir(path). "
                "Use exactly these names and argument names, or answer."})
            continue
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content, info

        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]})
        for tc in msg.tool_calls:
            try:
                a = json.loads(tc.function.arguments)
                if tc.function.name == "read_file":
                    result = read_file(repo_root, a["path"], a["start_line"], a["end_line"])
                elif tc.function.name == "list_dir":
                    result = list_dir(repo_root, a["path"])
                else:
                    result = f"Error: unknown tool {tc.function.name}"
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                info["bad_json"] += 1
                a, result = tc.function.arguments, f"Error: bad arguments ({e})"
            if result.startswith("Error"):
                info["tool_errors"] += 1
            info["tool_calls"].append(f"{tc.function.name}({a})")
            print(f"  tool call: {tc.function.name}({a})")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return None, info


def cmd_tools(args):
    repo = "itsdangerous"
    repo_root = REPOS / repo
    client = groq_client()
    available = sorted(m.id for m in client.models.list().data)
    if GROQ_MODEL not in available:
        print(f"{GROQ_MODEL} not available. Models your key can use:\n  " + "\n  ".join(available))
        return

    conn = connect_neon({})
    vo = voyage_client()
    q_a = "How is the signing key derived from the secret key?"
    q_b = "How does the URL-safe serializer compress the payload?"
    emb_a, emb_b = voyage_embed(vo, [q_a, q_b], "query", 100, {}).embeddings
    hits_a = search(conn, repo, emb_a, TOP_K)
    # Test B: url_safe.py is deliberately excluded, so the answer is NOT in context.
    hits_b = search(conn, repo, emb_b, TOP_K, exclude="url_safe")

    print(f"\n=== Test A: forced read_file x{args.runs} (plumbing) ===")
    a_ok = 0
    forced = {"type": "function", "function": {"name": "read_file"}}
    for run in range(1, args.runs + 1):
        answer, info = groq_answer(client, repo_root, q_a, hits_a, first_choice=forced)
        ok = (bool(info["tool_calls"]) and info["bad_json"] == 0 and info["tool_errors"] == 0
              and not info["invalid_tool_calls"] and bool(answer))
        a_ok += ok
        print(f"  run {run}: {'OK' if ok else 'FAIL'}  calls={len(info['tool_calls'])} "
              f"bad_json={info['bad_json']} tool_errors={info['tool_errors']} "
              f"invalid_tools={len(info['invalid_tool_calls'])} latencies={info['latencies_s']}")
        time.sleep(3)

    print(f"\n=== Test B: auto, answer not in context x{args.runs} (does it know it doesn't know?) ===")
    outcomes = {"tool_and_correct": 0, "correct_without_tool": 0, "wrong": 0}
    read_right_file = 0
    for run in range(1, args.runs + 1):
        answer, info = groq_answer(client, repo_root, q_b, hits_b, first_choice="auto")
        # Correct = mentions zlib (url_safe.py compresses with zlib when it's shorter).
        correct = "zlib" in (answer or "").lower()
        used_tool = bool(info["tool_calls"])
        read_right_file += any("url_safe" in c and c.startswith("read_file") for c in info["tool_calls"])
        key = "wrong" if not correct else ("tool_and_correct" if used_tool else "correct_without_tool")
        outcomes[key] += 1
        print(f"  run {run}: {key}  tools={info['tool_calls']}  invalid_tools={len(info['invalid_tool_calls'])}")
        print(f"    answer: {(answer or '(none)')[:200]!r}")
        time.sleep(3)

    print("\n===== tools measurements =====")
    print(json.dumps({
        "model": GROQ_MODEL,
        "test_A_clean_round_trips": f"{a_ok}/{args.runs}",
        "test_B_outcomes": outcomes,
        "test_B_read_url_safe_py": f"{read_right_file}/{args.runs}",
        "last_rate_limit_headers": info.get("rate_limit_headers"),
    }, indent=2))


def cmd_gemini(args):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    t0 = time.perf_counter()
    try:
        r = client.models.generate_content(model=GEMINI_MODEL, contents="Reply with exactly: ok")
        print(f"Gemini OK in {time.perf_counter() - t0:.2f}s, reply: {(r.text or '').strip()!r}")
    except Exception as e:
        print(f"Gemini failed: {str(e)[:300]}")
        print("Flash models your key can see:", [m.name for m in client.models.list() if "flash" in m.name])


def main():
    global GROQ_MODEL
    p = argparse.ArgumentParser(description="CodeAsk M0 spike")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("count"); s.add_argument("repo_dir"); s.set_defaults(fn=cmd_count)
    s = sub.add_parser("ingest"); s.add_argument("repo_dir")
    s.add_argument("--categories", default="source", help="comma list of source,tests,docs")
    s.add_argument("--batch-tokens", type=int, default=BATCH_TOKENS, help="max tokens per Voyage request")
    s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("ask"); s.add_argument("repo"); s.add_argument("question"); s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("sanity"); s.add_argument("repo"); s.set_defaults(fn=cmd_sanity)
    s = sub.add_parser("demo"); s.add_argument("n", type=int, choices=[4, 6]); s.set_defaults(fn=cmd_demo)
    s = sub.add_parser("tools"); s.add_argument("--runs", type=int, default=5); s.set_defaults(fn=cmd_tools)
    s = sub.add_parser("gemini"); s.set_defaults(fn=cmd_gemini)
    for name in ("ask", "tools"):
        sub.choices[name].add_argument("--model", default=GROQ_MODEL, help="Groq model id")
    args = p.parse_args()
    if getattr(args, "model", None):
        GROQ_MODEL = args.model
    args.fn(args)


if __name__ == "__main__":
    main()
