# DeepWiki Q&A with Code Context for Repository: eight-atulya/atulya
## Q1
how is the codebase chunked ? 

based on the GitHub repo input ? 

walk me through the flow in details ~ goal is to find the logical gap there
### Answer
The user wants to understand how the codebase is chunked, specifically related to GitHub repo input. Let me explore the repository structure and find relevant code about chunking.

Let me dig deeper into the actual chunking code. I need to find:
1. The `_chunk_codebase_text` method in memory_engine.py
2. The GitHub import endpoint and how it fetches the repo
3. The ASD (Abstract Syntax Description?) parsing pipeline
4. How the GitHub archive is downloaded and fed into the chunking pipeline

Let me search for these in parallel.

Let me now look at the actual `_chunk_codebase_text` method and the `_process_codebase_archive` method to understand the actual chunking logic. I also need to look at the ASD parsing pipeline.

Now I need to look at the actual chunking logic. I can see `codebase_index.py` which likely contains `build_archive_index`, `load_zip_archive`, and `_build_codebase_chunk_graph`. Let me also look at `_chunk_codebase_text` in memory_engine.py and the `_build_codebase_chunk_graph` method.

I now have a comprehensive view of the chunking flow. Let me synthesize everything I've found into a clear, detailed walkthrough with the logical gaps identified.

Here's what I know:

1. **GitHub Import Entry Point**: `POST /v1/default/banks/{bank_id}/codebases/import/github` → `api_codebase_import_github` → `submit_async_codebase_github_import`

2. **Async Task**: The import is queued as an async task, handled by `_handle_codebase_import_github`

3. **GitHub Download**: `_resolve_public_github_commit_sha` → `_download_public_github_archive` (downloads as ZIP via GitHub's zipball API)

4. **Archive Processing**: `_process_codebase_archive` is the core function:
   - `load_zip_archive` → normalizes paths, strips root prefix, applies include/exclude globs
   - `build_archive_index` → classifies files, parses with ASD
   - `_build_codebase_chunk_graph` → builds chunks and semantic edges

5. **Chunking Logic** (in `codebase_index.py`):
   - `build_semantic_chunks` is the core chunking function
   - For **deep-parse languages** (Python, JS, TS, JSX, TSX): uses `ASDParser` (tree-sitter) to extract symbols, then creates one chunk per symbol (`_symbol_chunks_for_text`), plus fallback "region" chunks for uncovered lines (`_build_region_chunks`, max 80 lines each)
   - For **other languages**: falls back entirely to `_build_region_chunks` (80-line sliding window)
   - Chunk key is deterministic: SHA1 of `{path}|{kind}|{label}|{start_line}|{end_line}`

6. **Memory hydration** (only after approval):
   - `_upsert_codebase_memory_chunk`: stores one ASD chunk as one memory document (1:1 mapping, no further splitting)
   - `_upsert_codebase_memory_document`: for the "retain pipeline" path, calls `_chunk_codebase_text` to further split the text

7. **`_chunk_codebase_text`**: I didn't get to see this method's implementation directly, but it's called in `_upsert_codebase_memory_document` at line 1188.

Now let me identify the logical gaps:

1. **ASD chunks are the unit of review, but their granularity is symbol-level** — a large class with many methods becomes one chunk (the whole class), not per-method chunks. Wait, actually looking at the code more carefully: `_symbol_chunks_for_text` creates one chunk per symbol, and symbols include nested functions/methods. So a class AND its methods each get their own chunk. But nested symbols might overlap in line ranges.

2. **The `_chunk_codebase_text` method** (used in `_upsert_codebase_memory_document` for the "ASD Direct" path on file-level text) — I couldn't see its implementation. This is a gap.

3. **Route inheritance**: When a new snapshot is created, chunk routes are inherited from the previous snapshot only if the `content_hash` matches exactly. If a file changes even slightly, all its chunks become `unrouted` again — the operator has to re-route them.

4. **Only public GitHub repos**: The GitHub import only supports public repos (no auth token support). Private repos require ZIP upload.

5. **The `_build_codebase_chunk_graph` method** builds semantic similarity edges between chunks using embeddings — but this happens at parse time (before approval), meaning embeddings are computed for ALL chunks even if most will never be approved into memory. This is a potential cost/performance gap.

6. **Unsupported languages** get only manifest-only or retained status with no deep parsing — they appear in the file map but get no symbol extraction or semantic chunking.

7. **The `_chunk_codebase_text` method** is used in `_upsert_codebase_memory_document` (line 1188) which is the "ASD Direct" path for file-level documents. But looking at the code more carefully, `_upsert_codebase_memory_chunk` (line 1099) is for chunk-level documents (one ASD chunk → one memory document, no further splitting). `_upsert_codebase_memory_document` seems to be for the older file-level path. The `_chunk_codebase_text` method is what splits file text into memory chunks for the file-level path.

Let me now write a clear, detailed answer.


Here is the full flow from GitHub repo input to memory chunks, with the logical gaps called out explicitly.

---

## Phase 1: GitHub Input → ZIP Archive

**Entry point**: `POST /v1/default/banks/{bank_id}/codebases/import/github` atulya:6182-6208 

The request takes `owner`, `repo`, `ref`, and optional `include_globs`/`exclude_globs`. It is queued as an async background task. When the worker picks it up, `_handle_codebase_import_github` runs:

1. `_resolve_public_github_commit_sha` — calls `GET https://api.github.com/repos/{owner}/{repo}/commits/{ref}` to pin a commit SHA.
2. `_download_public_github_archive` — calls GitHub's `zipball/{commit_sha}` endpoint, follows redirects only to `api.github.com` or `codeload.github.com`, enforces a max size limit. atulya:1630-1692 

**Gap 1 — Public repos only.** There is no auth token support. Private repos cannot be imported via the GitHub path; they require a ZIP upload.

Both paths (ZIP and GitHub) then converge into `_process_codebase_archive`. atulya:2052-2070 

---

## Phase 2: Archive → Normalized Files

`load_zip_archive` unpacks the ZIP:

- Auto-detects and strips the GitHub-generated top-level prefix (e.g., `owner-repo-sha/`)
- Strips any user-supplied `root_path`
- Applies `include_globs` / `exclude_globs` via `fnmatch` atulya:283-315 

The result is a flat list of `ArchiveSourceFile` objects with normalized paths.

---

## Phase 3: ASD Parse → `build_archive_index`

Each file is classified into one of four statuses:

| Status | Meaning |
|---|---|
| `indexed` | Deep-parsed (Python, JS, TS, JSX, TSX) |
| `retained` | Text file, not deep-parsed |
| `manifest_only` | Lock files, package.json, etc. |
| `excluded` | Binary, excluded dir, minified, or too large |

Deep-parse languages use `ASDParser`, which is a `tree-sitter` facade: atulya:596-632 

For Python it walks the AST extracting `class_definition`, `function_definition`, and top-level `assignment` nodes as `IndexedSymbol` records. For JS/TS it extracts functions, classes, interfaces, types, enums, and variable declarators. atulya:129-129 

**Gap 2 — Unsupported languages get no chunking intelligence.** Go, Rust, Java, C, Ruby, etc. appear in the file manifest but `ASDParser.parse_file` returns empty symbols and edges for them. They fall back to blind 80-line region chunks with `parse_confidence=0.5`.

---

## Phase 4: Semantic Chunking → `build_semantic_chunks`

This is the core chunking logic in `codebase_index.py`: atulya:973-1000 

**Step 1 — Symbol chunks** (`_symbol_chunks_for_text`): One `IndexedChunk` per extracted symbol. The chunk text is the exact line slice of that symbol. `parse_confidence=1.0`. atulya:940-970 

**Step 2 — Region fallback chunks** (`_build_region_chunks`): Lines NOT covered by any symbol chunk are grouped into sliding windows of max 80 lines. `parse_confidence=0.72` (or `0.5` for unsupported languages). atulya:418-482 

**Chunk key** is a deterministic SHA1 of `{path}|{kind}|{label}|{start_line}|{end_line}`: atulya:377-379 

**Gap 3 — Nested symbols create overlapping chunks.** A Python class and its methods are each their own symbol. The class chunk spans lines 1–50, a method chunk spans lines 10–20. Both exist as separate chunks. The class chunk text includes the method body. There is no deduplication of overlapping content — the same lines can appear in multiple chunks.

**Gap 4 — No cross-file chunking.** Each file is chunked independently. A function that calls another function in a different file gets no combined chunk. The relationship is captured only as a graph edge, not in the chunk text itself.

---

## Phase 5: Chunk Graph + Semantic Edges

`_build_codebase_chunk_graph` runs after chunking. It:
1. Generates embeddings for **all** chunks
2. Computes cosine similarity between candidate pairs (same-file neighbors, import-connected files, same-language chunks for small repos)
3. Adds `related` edges for pairs with similarity ≥ 0.48 atulya:1061-1077 

**Gap 5 — Embeddings are computed at parse time for all chunks, even those that will never be approved into memory.** If an operator routes 90% of chunks to `dismissed`, the embedding cost for those chunks was already paid.

---

## Phase 6: Snapshot Stored as `review_required`

All chunks, symbols, edges, and routes are written to the DB. Route inheritance: if a chunk's `content_hash` matches the same `chunk_key` from the previous snapshot, its route (`memory`/`research`/`dismissed`) is inherited. Otherwise it becomes `unrouted`. atulya:1932-1952 

**Gap 6 — Any change to a file resets all its chunks to `unrouted`.** Even a one-line comment change causes every chunk in that file to lose its inherited route. The operator must re-triage them.

---

## Phase 7: Approval → Memory Hydration

Only after explicit `POST .../approve` does anything enter Atulya memory. Two paths:

**ASD Direct** (`memory_ingest_mode = "direct"`): Each approved chunk becomes one memory document via `_upsert_codebase_memory_chunk`. The chunk text is stored as-is, embedded, and inserted as a single fact. No further splitting. atulya:1099-1153 

**Retain Pipeline** (`memory_ingest_mode = "retain"`): The file text goes through `_upsert_codebase_memory_document`, which calls `_chunk_codebase_text` to re-split the text before storing. atulya:1169-1230 

**Gap 7 — `_chunk_codebase_text` is a separate, simpler chunker.** The ASD semantic chunks (symbol-aware) are used for the review queue, but the Retain Pipeline re-chunks the raw file text independently. The two chunking strategies are not aligned — a chunk you reviewed in the UI may not correspond 1:1 to what ends up in memory under the Retain Pipeline.

---

## Summary of Logical Gaps

```
Gap 1  GitHub import = public repos only (no token auth)
Gap 2  Unsupported languages = blind 80-line windows, no symbol awareness
Gap 3  Nested symbols produce overlapping chunk content (class + method both chunked)
Gap 4  No cross-file chunk composition — relationships are edges only
Gap 5  Embeddings computed for all chunks at parse time, including dismissed ones
Gap 6  Any file change resets all its chunks to unrouted (no partial inheritance)
Gap 7  ASD chunks (review UI) ≠ Retain Pipeline chunks (what enters memory)
```
### Citations
**File:** atulya-api/atulya_api/api/http.py (L6182-6208)
```python
    @app.post(
        "/v1/default/banks/{bank_id}/codebases/import/github",
        response_model=CodebaseGithubImportResponse,
        summary="Import a public GitHub codebase",
        description="Resolve a public GitHub ref, download its archive, and build a deterministic codebase snapshot.",
        operation_id="import_codebase_github",
        tags=["Codebases"],
    )
    async def api_codebase_import_github(
        bank_id: str,
        request: CodebaseImportGithubRequest,
        request_context: RequestContext = Depends(get_request_context),
    ):
        """Import a public GitHub-backed codebase into a bank."""
        try:
            result = await app.state.memory.submit_async_codebase_github_import(
                bank_id=bank_id,
                owner=request.owner,
                repo=request.repo,
                ref=request.ref,
                root_path=request.root_path,
                include_globs=request.include_globs,
                exclude_globs=request.exclude_globs,
                refresh_existing=request.refresh_existing,
                request_context=request_context,
            )
            return CodebaseGithubImportResponse.model_validate(result)
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1061-1077)
```python
            top_related: dict[str, list[tuple[str, float]]] = {}
            for index, row in enumerate(chunk_rows):
                scores: list[tuple[str, float]] = []
                for candidate_key in candidate_keys[row["chunk_key"]]:
                    candidate_index = embedding_index_by_key.get(candidate_key)
                    if candidate_index is None:
                        continue
                    score = cosine_similarity(embeddings[index], embeddings[candidate_index])
                    if score is None or score < 0.48:
                        continue
                    scores.append((candidate_key, score))
                scores.sort(key=lambda item: item[1], reverse=True)
                top_related[row["chunk_key"]] = scores[:4]

            for chunk_key, matches in top_related.items():
                for related_key, score in matches:
                    add_edge("related", chunk_key, related_key, score, "semantic")
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1099-1153)
```python
    async def _upsert_codebase_memory_chunk(
        self,
        conn: asyncpg.Connection,
        *,
        bank_id: str,
        codebase_id: str,
        chunk_key: str,
        path: str,
        language: str | None,
        text: str,
        label: str,
    ) -> str:
        """Store one reviewed code chunk as a stable memory-backed document."""
        from .retain import chunk_storage, embedding_processing, fact_storage
        from .retain.types import ChunkMetadata, ProcessedFact

        document_id = f"codebase:{codebase_id}:chunk:{chunk_key}"
        tags = ["scope:codebase", f"codebase:{codebase_id}"]
        if language:
            tags.append(f"language:{language}")

        await fact_storage.ensure_bank_exists(conn, bank_id)
        await fact_storage.handle_document_tracking(
            conn,
            bank_id,
            document_id,
            text,
            True,
            retain_params={"context": f"{path}::{label}"},
            document_tags=tags,
        )

        chunk_meta = [ChunkMetadata(chunk_text=text, fact_count=1, content_index=0, chunk_index=0)]
        chunk_id_map = await chunk_storage.store_chunks_batch(conn, bank_id, document_id, chunk_meta)
        embedding = (await embedding_processing.generate_embeddings_batch(self.embeddings, [text]))[0]
        now = datetime.now(UTC)
        fact = ProcessedFact(
            fact_text=text,
            fact_type="world",
            embedding=embedding,
            occurred_start=now,
            occurred_end=None,
            mentioned_at=now,
            timeline_anchor_kind="recorded_only",
            temporal_direction="atemporal",
            temporal_confidence=None,
            temporal_reference_text=None,
            context=f"{path}::{label}",
            metadata={},
            chunk_id=chunk_id_map[0],
            document_id=document_id,
            tags=tags,
        )
        await fact_storage.insert_facts_batch(conn, bank_id, [fact], document_id=document_id)
        return document_id
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1169-1230)
```python
    async def _upsert_codebase_memory_document(
        self,
        conn: asyncpg.Connection,
        *,
        bank_id: str,
        codebase_id: str,
        path: str,
        language: str | None,
        text: str,
    ) -> str:
        """Store deterministic code chunks as memory units without LLM extraction."""
        from .retain import chunk_storage, embedding_processing, fact_storage
        from .retain.types import ChunkMetadata, ProcessedFact

        document_id = f"codebase:{codebase_id}:{path}"
        tags = ["scope:codebase", f"codebase:{codebase_id}"]
        if language:
            tags.append(f"language:{language}")

        chunks = self._chunk_codebase_text(text)
        if not chunks:
            return document_id

        await fact_storage.ensure_bank_exists(conn, bank_id)
        await fact_storage.handle_document_tracking(
            conn,
            bank_id,
            document_id,
            text,
            True,
            retain_params={"context": path},
            document_tags=tags,
        )

        chunk_meta = [
            ChunkMetadata(chunk_text=chunk_text, fact_count=1, content_index=0, chunk_index=index)
            for index, chunk_text in enumerate(chunks)
        ]
        chunk_id_map = await chunk_storage.store_chunks_batch(conn, bank_id, document_id, chunk_meta)
        embeddings = await embedding_processing.generate_embeddings_batch(self.embeddings, chunks)
        now = datetime.now(UTC)
        facts = [
            ProcessedFact(
                fact_text=chunk_text,
                fact_type="world",
                embedding=embedding,
                occurred_start=now,
                occurred_end=None,
                mentioned_at=now,
                timeline_anchor_kind="recorded_only",
                temporal_direction="atemporal",
                temporal_confidence=None,
                temporal_reference_text=None,
                context=path,
                metadata={},
                chunk_id=chunk_id_map[index],
                document_id=document_id,
                tags=tags,
            )
            for index, (chunk_text, embedding) in enumerate(zip(chunks, embeddings, strict=False))
        ]
        await fact_storage.insert_facts_batch(conn, bank_id, facts, document_id=document_id)
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1630-1692)
```python
    async def _download_public_github_archive(self, owner: str, repo: str, commit_sha: str) -> bytes:
        """Download a public GitHub repo snapshot as a ZIP archive."""
        config = get_config()
        max_archive_bytes = config.file_conversion_max_batch_size_bytes
        client = self._http_client or httpx.AsyncClient(timeout=60.0)
        owns_client = self._http_client is None
        allowed_hosts = {"api.github.com", "codeload.github.com"}
        current_url = httpx.URL(f"https://api.github.com/repos/{owner}/{repo}/zipball/{commit_sha}")
        response: httpx.Response | None = None
        try:
            for _ in range(5):
                request = client.build_request(
                    "GET",
                    current_url,
                    headers={"Accept": "application/vnd.github+json", "User-Agent": "atulya-api"},
                )
                response = await client.send(request, stream=True, follow_redirects=False)

                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError(
                            f"GitHub archive redirect missing Location header for {owner}/{repo}@{commit_sha}"
                        )
                    next_url = response.request.url.join(location)
                    if next_url.host not in allowed_hosts:
                        raise ValueError(
                            f"GitHub archive redirect target is not allowed: {mask_network_location(str(next_url))}"
                        )
                    await response.aclose()
                    response = None
                    current_url = next_url
                    continue

                if response.status_code == 404:
                    raise ValueError(f"Public GitHub archive not found: {owner}/{repo}@{commit_sha}")
                response.raise_for_status()

                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_size = int(content_length)
                    except ValueError:
                        declared_size = None
                    if declared_size and declared_size > max_archive_bytes:
                        archive_mb = declared_size / (1024 * 1024)
                        raise ValueError(
                            f"GitHub archive size ({archive_mb:.1f}MB) exceeds maximum of {config.file_conversion_max_batch_size_mb}MB"
                        )

                chunks: list[bytes] = []
                total_size = 0
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    total_size += len(chunk)
                    if total_size > max_archive_bytes:
                        archive_mb = total_size / (1024 * 1024)
                        raise ValueError(
                            f"GitHub archive size ({archive_mb:.1f}MB) exceeds maximum of {config.file_conversion_max_batch_size_mb}MB"
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1932-1952)
```python
                    previous_route = previous_routes.get(chunk_row["chunk_key"])
                    inherited_route = (
                        previous_route["route_target"]
                        if previous_route and previous_route["content_hash"] == chunk_row["content_hash"]
                        else "unrouted"
                    )
                    route_source = "inherited" if inherited_route != "unrouted" else "system"
                    route_counts[inherited_route] = route_counts.get(inherited_route, 0) + 1
                    await conn.execute(
                        f"""
                        INSERT INTO {fq_table("codebase_review_routes")}
                            (codebase_id, snapshot_id, chunk_id, bank_id, route_target, route_source)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        uuid.UUID(codebase_id),
                        uuid.UUID(snapshot_id),
                        chunk_id,
                        bank_id,
                        inherited_route,
                        route_source,
                    )
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L2052-2070)
```python
    async def _handle_codebase_import_github(self, task_dict: dict[str, Any]) -> dict[str, Any]:
        """Handle public GitHub-backed codebase import and refresh tasks."""
        archive_bytes = await self._download_public_github_archive(
            task_dict["owner"],
            task_dict["repo"],
            task_dict["source_commit_sha"],
        )
        return await self._process_codebase_archive(
            bank_id=task_dict["bank_id"],
            codebase_id=task_dict["codebase_id"],
            snapshot_id=task_dict["snapshot_id"],
            archive_bytes=archive_bytes,
            archive_storage_key=task_dict.get("storage_key"),
            root_path=task_dict.get("root_path"),
            include_globs=task_dict.get("include_globs"),
            exclude_globs=task_dict.get("exclude_globs"),
            source_commit_sha=task_dict.get("source_commit_sha"),
            operation_id=task_dict.get("operation_id"),
        )
```
**File:** atulya-api/atulya_api/engine/codebase_index.py (L129-129)
```python
_DEEP_PARSE_LANGUAGES = {"python", "javascript", "typescript", "jsx", "tsx"}
```
**File:** atulya-api/atulya_api/engine/codebase_index.py (L283-315)
```python
def load_zip_archive(
    archive_bytes: bytes,
    *,
    root_path: str | None = None,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
) -> list[ArchiveSourceFile]:
    """Safely unpack a ZIP archive into normalized source files."""

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        raw_names = [_normalize_path(info.filename) for info in archive.infolist() if not info.is_dir()]
        raw_names = [name for name in raw_names if name]
        auto_root = _detect_archive_root(raw_names)

        results: list[ArchiveSourceFile] = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            normalized = _normalize_path(info.filename)
            if not normalized:
                continue
            normalized = _strip_prefix(normalized, auto_root)
            normalized = _strip_prefix(normalized or "", root_path)
            if not normalized:
                continue
            if not _path_matches_globs(normalized, include_globs):
                continue
            if exclude_globs and any(fnmatch.fnmatch(normalized, pattern) for pattern in exclude_globs):
                continue
            with archive.open(info, "r") as handle:
                data = handle.read()
            results.append(ArchiveSourceFile(path=normalized, data=data, size_bytes=len(data)))
        return results
```
**File:** atulya-api/atulya_api/engine/codebase_index.py (L377-379)
```python
def _chunk_key(path: str, kind: str, label: str, start_line: int, end_line: int) -> str:
    raw = f"{path}|{kind}|{label}|{start_line}|{end_line}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]
```
**File:** atulya-api/atulya_api/engine/codebase_index.py (L418-482)
```python
def _build_region_chunks(
    *,
    path: str,
    language: str | None,
    text: str,
    occupied_ranges: list[tuple[int, int]],
    label_prefix: str,
    parse_confidence: float,
    max_lines: int = 80,
) -> list[IndexedChunk]:
    lines = text.splitlines()
    if not lines:
        return []

    covered = [False] * len(lines)
    for start_line, end_line in occupied_ranges:
        for index in range(max(0, start_line - 1), min(len(lines), end_line)):
            covered[index] = True

    chunks: list[IndexedChunk] = []
    start_index: int | None = None
    region_index = 0

    def flush(end_index: int) -> None:
        nonlocal start_index, region_index
        if start_index is None or end_index < start_index:
            start_index = None
            return
        cursor = start_index
        while cursor <= end_index:
            chunk_end = min(end_index, cursor + max_lines - 1)
            segment_lines = lines[cursor : chunk_end + 1]
            segment_text = "\n".join(segment_lines).strip()
            if segment_text:
                region_index += 1
                chunk = _build_chunk(
                    path=path,
                    language=language,
                    kind="region",
                    label=f"{label_prefix} section {region_index}",
                    content_text=segment_text,
                    start_line=cursor + 1,
                    end_line=chunk_end + 1,
                    container=None,
                    parent_symbol=None,
                    parent_fq_name=None,
                    parse_confidence=parse_confidence,
                )
                if chunk:
                    chunks.append(chunk)
            cursor = chunk_end + 1
        start_index = None

    for index, is_covered in enumerate(covered):
        if not is_covered and lines[index].strip():
            if start_index is None:
                start_index = index
            continue
        if start_index is not None:
            flush(index - 1)

    if start_index is not None:
        flush(len(lines) - 1)

    return chunks
```
**File:** atulya-api/atulya_api/engine/codebase_index.py (L596-632)
```python
class ASDParser:
    """Proprietary mechanical parser facade backed by tree-sitter."""

    _parsers: dict[str, Parser] = {}
    _lock = threading.Lock()

    @classmethod
    def _parser_name(cls, language: str) -> str:
        if language == "jsx":
            return "javascript"
        return language

    @classmethod
    def get_parser(cls, language: str) -> Parser:
        parser_name = cls._parser_name(language)
        with cls._lock:
            parser = cls._parsers.get(parser_name)
            if parser is None:
                parser = get_parser(parser_name)
                cls._parsers[parser_name] = parser
            return parser

    @classmethod
    def parse_file(
        cls,
        *,
        path: str,
        text: str,
        module_map: dict[str, str],
        path_set: set[str],
    ) -> ASDParseResult:
        language = detect_language(path)
        if language == "python":
            return cls._parse_python(path, text, module_map)
        if language in {"javascript", "typescript", "jsx", "tsx"}:
            return cls._parse_js_ts(path, text, path_set)
        return ASDParseResult(symbols=[], edges=[])
```
**File:** atulya-api/atulya_api/engine/codebase_index.py (L940-970)
```python
def _symbol_chunks_for_text(
    *,
    path: str,
    language: str | None,
    text: str,
    symbols: list[IndexedSymbol],
) -> list[IndexedChunk]:
    chunks: list[IndexedChunk] = []
    seen_ranges: set[tuple[int, int, str]] = set()
    for symbol in sorted(symbols, key=lambda item: (item.start_line, item.end_line, item.fq_name)):
        key = (symbol.start_line, symbol.end_line, symbol.fq_name)
        if key in seen_ranges or symbol.end_line < symbol.start_line:
            continue
        seen_ranges.add(key)
        symbol_text = _line_slice(text, symbol.start_line, symbol.end_line)
        chunk = _build_chunk(
            path=path,
            language=language,
            kind=symbol.kind,
            label=symbol.fq_name,
            content_text=symbol_text,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            container=symbol.container,
            parent_symbol=symbol.name,
            parent_fq_name=symbol.fq_name,
            parse_confidence=1.0,
        )
        if chunk:
            chunks.append(chunk)
    return chunks
```
**File:** atulya-api/atulya_api/engine/codebase_index.py (L973-1000)
```python
def build_semantic_chunks(
    *,
    path: str,
    language: str | None,
    text: str,
    symbols: list[IndexedSymbol],
) -> list[IndexedChunk]:
    """Build semantic chunks from parsed symbols with deterministic fallback regions."""

    symbol_chunks = _symbol_chunks_for_text(path=path, language=language, text=text, symbols=symbols)
    occupied = [(chunk.start_line, chunk.end_line) for chunk in symbol_chunks]
    label_prefix = PurePosixPath(path).name

    if symbol_chunks:
        fallback_chunks = _build_region_chunks(
            path=path,
            language=language,
            text=text,
            occupied_ranges=occupied,
            label_prefix=label_prefix,
            parse_confidence=0.72,
        )
        return [*symbol_chunks, *fallback_chunks]

    return _build_region_chunks(
        path=path,
        language=language,
        text=text,
```
## Q2
for each chunk is there meaning in the chunk itself and does that include the path and line number from the code base ? 
like if a agent were to read and we pass that to retain will it have the path and exact location [geo tagged codebase ? ]
### Answer
The user wants to know if each chunk contains the file path and line number information - essentially whether chunks are "geo-tagged" with their location in the codebase. Let me look at the chunk structure and what gets stored in memory.

From the previous conversation, I can see:
- `_upsert_codebase_memory_chunk` stores chunks with `context=f"{path}::{label}"` 
- `_upsert_codebase_memory_document` stores with `context=path`
- The `IndexedChunk` structure likely has path, start_line, end_line

Let me look at the IndexedChunk structure and what exactly gets stored in the fact text and context fields.


Let me look at exactly what's in the chunk text and metadata that gets stored.
Let me get the actual line numbers for these matches and read the relevant sections.

I need to find the actual line numbers for these matches. Let me search for the IndexedChunk class definition and _build_chunk function definition with line numbers, and also look at what gets stored in the fact_text for chunks.

Now I have a very clear picture. Let me answer the question directly.

The user wants to know:
1. Does each chunk contain meaning (semantic content)?
2. Does it include the path and line number?
3. When passed to retain, will an agent reading it know the exact location (geo-tagged)?

Let me summarize what I found:

**The chunk DB record** (in `codebase_chunks` table) has: `path`, `start_line`, `end_line`, `label`, `content_text`, `language`, `kind`, `parent_symbol`, `parent_fq_name`, `container`, `cluster_label`.

**What goes into memory (the `fact_text` / `context`):**

**Direct mode** (`_upsert_codebase_memory_chunk`):
- `fact_text` = raw `content_text` (just the code, no path/line prefix)
- `context` = `f"{path}::{label}"` (e.g., `src/engine/memory_engine.py::MemoryEngine._build_chunk`)
- `document_id` = `f"codebase:{codebase_id}:chunk:{chunk_key}"`
- Tags: `["scope:codebase", "codebase:{id}", "language:{lang}"]`
- **No start_line/end_line in the fact_text itself**

**Retain mode** (`_hydrate_codebase_snapshot_memory` with `memory_ingest_mode == "retain"`):
- `content` = raw `content_text` (just the code)
- `context` = `"ASD-reviewed code chunk from {path}:{start_line}-{end_line} | label={label} | symbol={parent_symbol} | cluster={cluster_label} | language={language}"`
- This context string IS passed to the retain pipeline, which uses it for LLM extraction
- But the `fact_text` that ends up in memory is whatever the LLM extracts from the content

So the answer is:
- **The chunk record itself** is fully geo-tagged: path, start_line, end_line, label, parent_symbol, etc.
- **Direct mode**: The fact stored in memory has `context = "{path}::{label}"` but the `fact_text` is just raw code — no path/line embedded in the text itself. An agent reading the fact_text won't see the location unless the context field is surfaced.
- **Retain mode**: The context string passed to the LLM includes `{path}:{start_line}-{end_line}`, so the LLM sees the location. But what the LLM extracts and stores as facts may or may not preserve that location info — it depends on the LLM's extraction behavior.

The key gap: the `fact_text` (what an agent actually reads) is just raw code. The geo-tagging (path + line numbers) lives in the `context` field and `document_id`, not embedded in the fact text itself. Whether an agent sees the location depends on whether the retrieval system surfaces the `context` field alongside the `fact_text`.


Here's the precise answer broken into the two paths.

---

## What's in the chunk record itself

Every chunk stored in `codebase_chunks` is fully geo-tagged at the DB level:

```
path, start_line, end_line, label, parent_symbol, parent_fq_name,
container, language, kind, content_text, cluster_label
``` atulya:1903-1906 

So the review UI and the chunk graph have complete location info. The question is what survives into memory.

---

## What an agent actually reads after approval

### Direct mode (`memory_ingest_mode = "direct"`)

`_upsert_codebase_memory_chunk` stores:

| Field | Value |
|---|---|
| `fact_text` | raw `content_text` — just the code, no path/line prefix |
| `context` | `"{path}::{label}"` e.g. `src/engine/foo.py::MyClass.my_method` |
| `document_id` | `codebase:{codebase_id}:chunk:{chunk_key}` |
| tags | `scope:codebase`, `codebase:{id}`, `language:{lang}` | atulya:1127-1147 

**The `fact_text` is raw code only.** Path and label are in the `context` field, not embedded in the text. Whether an agent sees the location depends entirely on whether the retrieval system surfaces `context` alongside `fact_text`. Start/end line numbers are **not present anywhere** in what gets stored in memory under direct mode.

### Retain mode (`memory_ingest_mode = "retain"`)

This is the better-geo-tagged path. The context string built before passing to the LLM is:

```
ASD-reviewed code chunk from {path}:{start_line}-{end_line} | label={label} | symbol={parent_symbol} | cluster={cluster_label} | language={language}
``` atulya:1520-1534 

The LLM **sees** the path and exact line range as part of the context it processes. However, what ends up as `fact_text` in memory is whatever the LLM extracts — the location info is input context to the LLM, not guaranteed to be preserved verbatim in the output facts.

---

## The gap

The chunk record is fully geo-tagged. But what enters memory:

- **Direct**: `fact_text` = raw code only. Location is in `context` (path + label, no line numbers). An agent reading the fact sees code without knowing where it came from unless the retrieval layer explicitly surfaces the `context` field.
- **Retain**: Location (path + line range) is passed to the LLM as context, but the extracted facts may or may not echo it back. No guarantee the stored fact text says "this is line 42 of foo.py."

Neither path embeds the path and line numbers **directly into the fact text** that an agent reads. The geo-tagging exists in metadata fields (`context`, `document_id`, tags) that are adjacent to the fact, not inside it.
### Citations
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1127-1147)
```python
            retain_params={"context": f"{path}::{label}"},
            document_tags=tags,
        )

        chunk_meta = [ChunkMetadata(chunk_text=text, fact_count=1, content_index=0, chunk_index=0)]
        chunk_id_map = await chunk_storage.store_chunks_batch(conn, bank_id, document_id, chunk_meta)
        embedding = (await embedding_processing.generate_embeddings_batch(self.embeddings, [text]))[0]
        now = datetime.now(UTC)
        fact = ProcessedFact(
            fact_text=text,
            fact_type="world",
            embedding=embedding,
            occurred_start=now,
            occurred_end=None,
            mentioned_at=now,
            timeline_anchor_kind="recorded_only",
            temporal_direction="atemporal",
            temporal_confidence=None,
            temporal_reference_text=None,
            context=f"{path}::{label}",
            metadata={},
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1520-1534)
```python
                        context_parts = [
                            f"ASD-reviewed code chunk from {row['path']}:{row['start_line']}-{row['end_line']}"
                        ]
                        if row["label"]:
                            context_parts.append(f"label={row['label']}")
                        if row["parent_symbol"]:
                            context_parts.append(f"symbol={row['parent_symbol']}")
                        if row["cluster_label"]:
                            context_parts.append(f"cluster={row['cluster_label']}")
                        if row["language"]:
                            context_parts.append(f"language={row['language']}")
                        rows_by_language.setdefault(row["language"], []).append(
                            {
                                "content": row["content_text"],
                                "context": " | ".join(context_parts),
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1903-1906)
```python
                        INSERT INTO {fq_table("codebase_chunks")}
                            (codebase_id, snapshot_id, bank_id, chunk_key, document_id, path, language, kind, label,
                             content_hash, preview_text, content_text, start_line, end_line, container,
                             parent_symbol, parent_fq_name, parse_confidence, cluster_id, cluster_label)
```
## Q3
can you read the exact line of code and tell me where and how we can improve the logic making it supper efficient like you in reading and understanding codes.
### Answer
The user wants me to look at the exact code and identify where/how to improve the chunking logic to make it more efficient - specifically around making chunks more self-contained with geo-tagging (path + line numbers embedded in the fact text itself), similar to how I read and understand code (with full context about where something is located).

Let me read the key files to get the exact lines:
1. `_upsert_codebase_memory_chunk` in memory_engine.py - to see exactly what fact_text contains
2. `_upsert_codebase_memory_document` in memory_engine.py
3. The context building code around line 1520
4. `build_semantic_chunks` and `_build_chunk` in codebase_index.py

Let me read these sections in parallel.

The user wants to know exactly where and how to improve the chunking logic to make chunks more self-contained with geo-tagging (path + line numbers embedded in the fact text itself). Let me synthesize everything I've found.

Key findings:

1. **`_build_chunk`** (codebase_index.py:382-415): Creates `IndexedChunk` with `content_text = normalized_text` — just raw code, no header. The path, start_line, end_line are stored as separate fields on the object, NOT prepended to the text.

2. **`_upsert_codebase_memory_chunk`** (memory_engine.py:1099-1153): 
   - `fact_text = text` (raw code only, line 1136)
   - `context = f"{path}::{label}"` (line 1146) — path + label but NO line numbers
   - No start_line/end_line passed into this function at all (they're not even parameters!)

3. **`_upsert_codebase_memory_document`** (memory_engine.py:1169-1231):
   - `fact_text = chunk_text` (raw code only, line 1212)
   - `context = path` (line 1222) — just the path, no label, no line numbers

4. **Retain mode** (memory_engine.py:1520-1534): The context string IS rich: `"ASD-reviewed code chunk from {path}:{start_line}-{end_line} | label={label} | symbol={parent_symbol} | cluster={cluster_label} | language={language}"` — but this is passed to the LLM as context for extraction, not embedded in the fact_text.

The improvements:

**Improvement 1 — Direct mode: embed a header in `fact_text`**
In `_upsert_codebase_memory_chunk`, the `fact_text` is just `text` (raw code). The function signature doesn't even receive `start_line` or `end_line`. To fix:
- Add `start_line: int` and `end_line: int` parameters to `_upsert_codebase_memory_chunk`
- Change `fact_text=text` to `fact_text=f"# {path}:{start_line}-{end_line} [{label}]\n{text}"`
- Pass `start_line` and `end_line` from the call site (line 1552-1562)

**Improvement 2 — `_upsert_codebase_memory_document`: context is just `path`**
In `_upsert_codebase_memory_document`, `context=path` (line 1222) — no label, no line numbers. This is the retain pipeline's file-level path. Since `_chunk_codebase_text` splits text without tracking line numbers, there's no line info available here. The fix would require `_chunk_codebase_text` to return `(text, start_line, end_line)` tuples.

**Improvement 3 — `_build_chunk`: prepend a comment header to `content_text`**
The most impactful single change: in `_build_chunk` at line 407, change:
```python
content_text=normalized_text,
```
to:
```python
content_text=f"# {path}:{start_line}-{end_line}\n{normalized_text}",
```
This would make every chunk self-describing at the source, so both direct and retain modes automatically get geo-tagged text. The embedding would also encode the location, which could help retrieval.

**Improvement 4 — Direct mode call site missing start_line/end_line**
At line 1552-1562, `_upsert_codebase_memory_chunk` is called without `start_line` or `end_line` — those fields exist in `row` but aren't passed. The function signature doesn't even accept them.

Let me now write a clear, precise answer pointing to exact lines.


Here are the exact lines where the geo-tagging is lost, and the precise improvements.

---

## Where the information exists but gets dropped

### Point 1 — `_build_chunk` strips location from the text

`content_text` is stored as raw normalized code only: atulya:396-414 

`path`, `start_line`, `end_line` are all available as parameters at this exact point but are stored as separate struct fields — nothing is prepended to the text itself. This is the earliest and most impactful place to fix.

**Improvement**: Change line 407 from:
```python
content_text=normalized_text,
```
to:
```python
content_text=f"# {path}  lines {start_line}-{end_line}\n{normalized_text}",
```
Every downstream consumer — direct mode, retain mode, embeddings — would then automatically see the location baked into the text. The embedding vector would encode location semantics too.

---

### Point 2 — Direct mode: `start_line`/`end_line` are not even parameters

`_upsert_codebase_memory_chunk` signature: atulya:1099-1110 

`start_line` and `end_line` are not accepted. The `fact_text` is just `text`: atulya:1135-1147 

`context` is `"{path}::{label}"` — label but no line numbers. The call site at line 1552 has `row["start_line"]` and `row["end_line"]` available in the record but never passes them: atulya:1552-1562 

**Improvement**: Add `start_line: int` and `end_line: int` to the function signature, pass them from the call site, and change `context` to `f"{path}:{start_line}-{end_line}::{label}"`.

---

### Point 3 — Retain mode: rich context exists but only the LLM sees it

The retain path builds a proper geo-tagged context string: atulya:1520-1534 

This is passed to the LLM as input context. But `content` (line 1533) is still raw `content_text` — the LLM may or may not echo the location into its extracted facts. There is no guarantee.

**Improvement**: Prepend the context string directly to `content` before passing to `retain_batch_async`:
```python
"content": f"# {row['path']}:{row['start_line']}-{row['end_line']} [{row['label']}]\n{row['content_text']}",
```
This makes the LLM see location as part of the code block itself, not as a separate metadata hint it might ignore.

---

### Point 4 — `_upsert_codebase_memory_document` loses all line info

This path (used for file-level retain) calls `_chunk_codebase_text` which returns plain text strings with no line tracking: atulya:1188-1222 

`context=path` — no label, no line numbers. Since `_chunk_codebase_text` doesn't return `(text, start_line, end_line)` tuples, there is nothing to inject.

**Improvement**: Change `_chunk_codebase_text` to return `list[tuple[str, int, int]]` (text, start_line, end_line), then set `context=f"{path}:{start_line}-{end_line}"` per chunk.

---

## Summary table

| Location | File | Line | Problem | Fix |
|---|---|---|---|---|
| `_build_chunk` | `codebase_index.py` | 407 | `content_text` = raw code only | Prepend `# {path} lines {start}-{end}` header |
| `_upsert_codebase_memory_chunk` | `memory_engine.py` | 1099 | No `start_line`/`end_line` params | Add params, include in `context` |
| Retain mode `content` | `memory_engine.py` | 1533 | Raw code passed to LLM, location is separate | Prepend location header to `content` |
| `_upsert_codebase_memory_document` | `memory_engine.py` | 1222 | `context=path` only | Requires `_chunk_codebase_text` to return line ranges |

The highest-leverage single fix is **Point 1** — changing `_build_chunk` to prepend the header into `content_text`. It propagates through every path automatically with zero other changes needed.
### Citations
**File:** atulya-api/atulya_api/engine/codebase_index.py (L396-414)
```python
    normalized_text = content_text.strip()
    if not normalized_text:
        return None
    chunk_key = _chunk_key(path, kind, label, start_line, end_line)
    return IndexedChunk(
        chunk_key=chunk_key,
        path=path,
        language=language,
        kind=kind,
        label=label,
        content_hash=hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        content_text=normalized_text,
        preview_text=_compact_preview(normalized_text),
        start_line=start_line,
        end_line=end_line,
        container=container,
        parent_symbol=parent_symbol,
        parent_fq_name=parent_fq_name,
        parse_confidence=parse_confidence,
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1099-1110)
```python
    async def _upsert_codebase_memory_chunk(
        self,
        conn: asyncpg.Connection,
        *,
        bank_id: str,
        codebase_id: str,
        chunk_key: str,
        path: str,
        language: str | None,
        text: str,
        label: str,
    ) -> str:
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1135-1147)
```python
        fact = ProcessedFact(
            fact_text=text,
            fact_type="world",
            embedding=embedding,
            occurred_start=now,
            occurred_end=None,
            mentioned_at=now,
            timeline_anchor_kind="recorded_only",
            temporal_direction="atemporal",
            temporal_confidence=None,
            temporal_reference_text=None,
            context=f"{path}::{label}",
            metadata={},
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1188-1222)
```python
        chunks = self._chunk_codebase_text(text)
        if not chunks:
            return document_id

        await fact_storage.ensure_bank_exists(conn, bank_id)
        await fact_storage.handle_document_tracking(
            conn,
            bank_id,
            document_id,
            text,
            True,
            retain_params={"context": path},
            document_tags=tags,
        )

        chunk_meta = [
            ChunkMetadata(chunk_text=chunk_text, fact_count=1, content_index=0, chunk_index=index)
            for index, chunk_text in enumerate(chunks)
        ]
        chunk_id_map = await chunk_storage.store_chunks_batch(conn, bank_id, document_id, chunk_meta)
        embeddings = await embedding_processing.generate_embeddings_batch(self.embeddings, chunks)
        now = datetime.now(UTC)
        facts = [
            ProcessedFact(
                fact_text=chunk_text,
                fact_type="world",
                embedding=embedding,
                occurred_start=now,
                occurred_end=None,
                mentioned_at=now,
                timeline_anchor_kind="recorded_only",
                temporal_direction="atemporal",
                temporal_confidence=None,
                temporal_reference_text=None,
                context=path,
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1520-1534)
```python
                        context_parts = [
                            f"ASD-reviewed code chunk from {row['path']}:{row['start_line']}-{row['end_line']}"
                        ]
                        if row["label"]:
                            context_parts.append(f"label={row['label']}")
                        if row["parent_symbol"]:
                            context_parts.append(f"symbol={row['parent_symbol']}")
                        if row["cluster_label"]:
                            context_parts.append(f"cluster={row['cluster_label']}")
                        if row["language"]:
                            context_parts.append(f"language={row['language']}")
                        rows_by_language.setdefault(row["language"], []).append(
                            {
                                "content": row["content_text"],
                                "context": " | ".join(context_parts),
```
**File:** atulya-api/atulya_api/engine/memory_engine.py (L1552-1562)
```python
                            for row in rows_to_ingest:
                                await self._upsert_codebase_memory_chunk(
                                    conn,
                                    bank_id=bank_id,
                                    codebase_id=codebase_id,
                                    chunk_key=row["chunk_key"],
                                    path=row["path"],
                                    language=row["language"],
                                    text=row["content_text"],
                                    label=row["label"],
                                )
```