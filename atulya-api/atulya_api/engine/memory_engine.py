"""
Memory Engine for Memory Banks.

This implements a sophisticated memory architecture that combines:
1. Temporal links: Memories connected by time proximity
2. Semantic links: Memories connected by meaning/similarity
3. Entity links: Memories connected by shared entities (PERSON, ORG, etc.)
4. Spreading activation: Search through the graph with activation decay
5. Dynamic weighting: Recency and frequency-based importance
"""

import asyncio
import base64
import contextvars
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast

import asyncpg
import httpx
import tiktoken

from ..brain import AtulyaBrainRuntime, BrainRuntimeConfig
from ..brain.intelligence import (
    InfluenceFeatures,
    confidence_bands,
    ewma,
    hour_weekday_heatmap,
    influence_score,
    iqr_anomaly_flags,
    robust_zscore,
)
from ..config import get_config
from ..metrics import get_metrics_collector
from ..reflect_serialization import serialize_reflect_response
from ..tracing import create_operation_span
from ..utils import mask_network_location
from ..worker.exceptions import RetryTaskAt
from .db_budget import budgeted_operation
from .dreaming import (
    DreamConfidenceModel,
    DreamEvidenceBasis,
    DreamGrowthHypothesis,
    DreamLLMOutput,
    DreamPrediction,
    DreamPromotionProposal,
    DreamRunRecord,
    DreamSignals,
    DreamValidationOutcome,
    build_dream_html,
    compute_novelty_score,
    infer_maturity_tier,
    normalize_dream_config,
    render_dream_narrative_html,
    score_dream_quality,
    summarize_confidence,
    to_jsonable,
)
from .operation_metadata import (
    BatchRetainChildMetadata,
    BatchRetainParentMetadata,
    CodebaseOperationMetadata,
    ConsolidationMetadata,
    RefreshMentalModelMetadata,
    RetainMetadata,
)

# Context variable for current schema (async-safe, per-task isolation)
# Note: default is None, actual default comes from config via get_current_schema()
_current_schema: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_schema", default=None)


def get_current_schema() -> str:
    """Get the current schema from context (falls back to config default)."""
    schema = _current_schema.get()
    if schema is None:
        # Fall back to configured default schema
        return get_config().database_schema
    return schema


# Initialize tiktoken encoder once at module level for efficiency
_tiktoken_encoder = tiktoken.get_encoding("cl100k_base")  # GPT-4/GPT-3.5-turbo encoding


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken (cl100k_base encoding for GPT-4/3.5)."""
    return len(_tiktoken_encoder.encode(text))


def decode_jsonb(raw_value: Any, default: Any) -> Any:
    """Decode asyncpg JSONB values that may already be deserialized."""
    if raw_value is None:
        return default
    if isinstance(raw_value, (dict, list)):
        return raw_value
    if isinstance(raw_value, str):
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return default
    return default


def build_temporal_block(
    *,
    occurred_start: datetime | str | None = None,
    mentioned_at: datetime | str | None = None,
    created_at: datetime | str | None = None,
    timeline_anchor_at: datetime | str | None = None,
    timeline_anchor_kind: str | None = None,
    temporal_direction: str | None = None,
    temporal_confidence: float | None = None,
    temporal_reference_text: str | None = None,
) -> dict[str, object | None]:
    anchor_at = timeline_anchor_at or occurred_start or mentioned_at or created_at
    recorded_at = mentioned_at or created_at
    normalized_anchor_at = anchor_at if isinstance(anchor_at, datetime) else None
    normalized_recorded_at = recorded_at if isinstance(recorded_at, datetime) else None
    anchor_kind = timeline_anchor_kind or default_anchor_kind(
        occurred_start=occurred_start if isinstance(occurred_start, datetime) else None,
        mentioned_at=mentioned_at if isinstance(mentioned_at, datetime) else None,
        created_at=created_at if isinstance(created_at, datetime) else None,
    )
    direction = temporal_direction or infer_direction(normalized_anchor_at, normalized_recorded_at)
    return serialize_temporal_metadata(
        anchor_at=anchor_at,
        anchor_kind=anchor_kind,
        recorded_at=recorded_at,
        direction=direction,
        confidence=temporal_confidence,
        reference_text=temporal_reference_text,
    )


def fq_table(table_name: str) -> str:
    """
    Get fully-qualified table name with current schema.

    Example:
        fq_table("memory_units") -> "public.memory_units"
        fq_table("memory_units") -> "tenant_xyz.memory_units" (if schema is set)
    """
    return f"{get_current_schema()}.{table_name}"


# Tables that must be schema-qualified (for runtime validation)
_PROTECTED_TABLES = frozenset(
    [
        "memory_units",
        "memory_links",
        "unit_entities",
        "entities",
        "entity_cooccurrences",
        "banks",
        "documents",
        "chunks",
        "async_operations",
        "file_storage",
        "codebases",
        "codebase_snapshots",
        "codebase_files",
        "codebase_symbols",
        "codebase_edges",
        "dream_artifacts",
        "dream_runs",
        "dream_predictions",
        "dream_proposals",
        "dream_prediction_outcomes",
    ]
)

# Enable runtime SQL validation (can be disabled in production for performance)
_VALIDATE_SQL_SCHEMAS = True


class UnqualifiedTableError(Exception):
    """Raised when SQL contains unqualified table references."""

    pass


def validate_sql_schema(sql: str) -> None:
    """
    Validate that SQL doesn't contain unqualified table references.

    This is a runtime safety check to prevent cross-tenant data access.
    Raises UnqualifiedTableError if any protected table is referenced
    without a schema prefix.

    Args:
        sql: The SQL query to validate

    Raises:
        UnqualifiedTableError: If unqualified table reference found
    """
    if not _VALIDATE_SQL_SCHEMAS:
        return

    import re

    sql_upper = sql.upper()

    for table in _PROTECTED_TABLES:
        table_upper = table.upper()

        # Pattern: SQL keyword followed by unqualified table name
        # Matches: FROM memory_units, JOIN memory_units, INTO memory_units, UPDATE memory_units
        patterns = [
            rf"FROM\s+{table_upper}(?:\s|$|,|\)|;)",
            rf"JOIN\s+{table_upper}(?:\s|$|,|\)|;)",
            rf"INTO\s+{table_upper}(?:\s|$|\()",
            rf"UPDATE\s+{table_upper}(?:\s|$)",
            rf"DELETE\s+FROM\s+{table_upper}(?:\s|$|;)",
        ]

        for pattern in patterns:
            match = re.search(pattern, sql_upper)
            if match:
                # Check if it's actually qualified (preceded by schema.)
                # Look backwards from match to see if there's a dot
                start = match.start()
                # Find the table name position in the match
                table_pos = sql_upper.find(table_upper, start)
                if table_pos > 0:
                    # Check character before table name (skip whitespace)
                    prefix = sql[:table_pos].rstrip()
                    if not prefix.endswith("."):
                        raise UnqualifiedTableError(
                            f"Unqualified table reference '{table}' in SQL. "
                            f"Use fq_table('{table}') for schema safety. "
                            f"SQL snippet: ...{sql[max(0, start - 10) : start + 50]}..."
                        )


import asyncpg
from pydantic import BaseModel, Field

from .codebase_index import (
    IndexedChunk,
    IndexedEdge,
    IndexedFile,
    build_archive_index,
    load_zip_archive,
)
from .cross_encoder import CrossEncoderModel
from .embedding_similarity import cosine_similarity
from .embeddings import Embeddings, create_embeddings_from_env
from .interface import MemoryEngineInterface

if TYPE_CHECKING:
    from atulya_api.extensions import OperationValidatorExtension, TenantExtension
    from atulya_api.models import RequestContext


from enum import Enum

from ..metrics import get_metrics_collector
from ..pg0 import EmbeddedPostgres, parse_pg0_url
from .entity_resolver import EntityResolver
from .llm_wrapper import LLMConfig, requires_api_key
from .query_analyzer import QueryAnalyzer
from .reflect import run_reflect_agent
from .reflect.tools import tool_expand, tool_recall, tool_search_mental_models, tool_search_observations
from .response_models import (
    VALID_RECALL_FACT_TYPES,
    EntityObservation,
    EntityState,
    LLMCallTrace,
    MemoryFact,
    ObservationRef,
    ReflectResult,
    TokenUsage,
    ToolCallTrace,
)
from .response_models import RecallResult as RecallResultModel
from .retain import bank_utils, embedding_utils
from .retain.types import RetainContentDict
from .search import think_utils
from .search.reranking import CrossEncoderReranker, apply_combined_scoring
from .search.tags import TagsMatch, build_tags_where_clause
from .task_backend import BrokerTaskBackend, SyncTaskBackend, TaskBackend
from .temporal import (
    classify_snapshot_temporal_metadata,
    default_anchor_kind,
    infer_direction,
    serialize_temporal_metadata,
)


class Budget(str, Enum):
    """Budget levels for recall/reflect operations."""

    LOW = "low"
    MID = "mid"
    HIGH = "high"


def utcnow():
    """Get current UTC time with timezone info."""
    return datetime.now(UTC)


# Logger for memory system
logger = logging.getLogger(__name__)

import tiktoken

from .db_utils import acquire_with_retry

# Cache tiktoken encoding for token budget filtering (module-level singleton)
_TIKTOKEN_ENCODING = None


def _get_tiktoken_encoding():
    """Get cached tiktoken encoding (cl100k_base for GPT-4/3.5)."""
    global _TIKTOKEN_ENCODING
    if _TIKTOKEN_ENCODING is None:
        _TIKTOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")
    return _TIKTOKEN_ENCODING


class MemoryEngine(MemoryEngineInterface):
    """
    Advanced memory system using temporal and semantic linking with PostgreSQL.

    This class provides:
    - Embedding generation for semantic search
    - Entity, temporal, and semantic link creation
    - Think operations for formulating answers with opinions
    - bank profile and disposition management
    """

    def __init__(
        self,
        db_url: str | None = None,
        memory_llm_provider: str | None = None,
        memory_llm_api_key: str | None = None,
        memory_llm_model: str | None = None,
        memory_llm_base_url: str | None = None,
        # Per-operation LLM config (optional, falls back to memory_llm_* params)
        retain_llm_provider: str | None = None,
        retain_llm_api_key: str | None = None,
        retain_llm_model: str | None = None,
        retain_llm_base_url: str | None = None,
        reflect_llm_provider: str | None = None,
        reflect_llm_api_key: str | None = None,
        reflect_llm_model: str | None = None,
        reflect_llm_base_url: str | None = None,
        consolidation_llm_provider: str | None = None,
        consolidation_llm_api_key: str | None = None,
        consolidation_llm_model: str | None = None,
        consolidation_llm_base_url: str | None = None,
        embeddings: Embeddings | None = None,
        cross_encoder: CrossEncoderModel | None = None,
        query_analyzer: QueryAnalyzer | None = None,
        pool_min_size: int | None = None,
        pool_max_size: int | None = None,
        db_command_timeout: int | None = None,
        db_acquire_timeout: int | None = None,
        task_backend: TaskBackend | None = None,
        run_migrations: bool = True,
        operation_validator: "OperationValidatorExtension | None" = None,
        tenant_extension: "TenantExtension | None" = None,
        skip_llm_verification: bool | None = None,
        lazy_reranker: bool | None = None,
    ):
        """
        Initialize the temporal + semantic memory system.

        All parameters are optional and will be read from environment variables if not provided.
        See atulya_api.config for environment variable names and defaults.

        Args:
            db_url: PostgreSQL connection URL. Defaults to ATULYA_API_DATABASE_URL env var or "pg0".
                    Also supports pg0 URLs: "pg0" or "pg0://instance-name" or "pg0://instance-name:port"
            memory_llm_provider: LLM provider. Defaults to ATULYA_API_LLM_PROVIDER env var or "groq".
            memory_llm_api_key: API key for the LLM provider. Defaults to ATULYA_API_LLM_API_KEY env var.
            memory_llm_model: Model name. Defaults to ATULYA_API_LLM_MODEL env var.
            memory_llm_base_url: Base URL for the LLM API. Defaults based on provider.
            retain_llm_provider: LLM provider for retain operations. Falls back to memory_llm_provider.
            retain_llm_api_key: API key for retain LLM. Falls back to memory_llm_api_key.
            retain_llm_model: Model for retain operations. Falls back to memory_llm_model.
            retain_llm_base_url: Base URL for retain LLM. Falls back to memory_llm_base_url.
            reflect_llm_provider: LLM provider for reflect operations. Falls back to memory_llm_provider.
            reflect_llm_api_key: API key for reflect LLM. Falls back to memory_llm_api_key.
            reflect_llm_model: Model for reflect operations. Falls back to memory_llm_model.
            reflect_llm_base_url: Base URL for reflect LLM. Falls back to memory_llm_base_url.
            consolidation_llm_provider: LLM provider for consolidation operations. Falls back to memory_llm_provider.
            consolidation_llm_api_key: API key for consolidation LLM. Falls back to memory_llm_api_key.
            consolidation_llm_model: Model for consolidation operations. Falls back to memory_llm_model.
            consolidation_llm_base_url: Base URL for consolidation LLM. Falls back to memory_llm_base_url.
            embeddings: Embeddings implementation. If not provided, created from env vars.
            cross_encoder: Cross-encoder model. If not provided, created from env vars.
            query_analyzer: Query analyzer implementation. If not provided, uses DateparserQueryAnalyzer.
            pool_min_size: Minimum number of connections in the pool. Defaults to ATULYA_API_DB_POOL_MIN_SIZE.
            pool_max_size: Maximum number of connections in the pool. Defaults to ATULYA_API_DB_POOL_MAX_SIZE.
            db_command_timeout: PostgreSQL command timeout in seconds. Defaults to ATULYA_API_DB_COMMAND_TIMEOUT.
            db_acquire_timeout: Connection acquisition timeout in seconds. Defaults to ATULYA_API_DB_ACQUIRE_TIMEOUT.
            task_backend: Custom task backend. If not provided, uses BrokerTaskBackend for distributed processing.
            run_migrations: Whether to run database migrations during initialize(). Default: True
            operation_validator: Optional extension to validate operations before execution.
                                If provided, retain/recall/reflect operations will be validated.
            tenant_extension: Optional extension for multi-tenancy and API key authentication.
                             If provided, operations require a RequestContext for authentication.
            skip_llm_verification: Skip LLM connection verification during initialization.
                                  Defaults to ATULYA_API_SKIP_LLM_VERIFICATION env var or False.
            lazy_reranker: Delay reranker initialization until first use. Useful for retain-only
                          operations that don't need the cross-encoder. Defaults to
                          ATULYA_API_LAZY_RERANKER env var or False.
        """
        # Load config from environment for any missing parameters
        from ..config import get_config

        config = get_config()

        # Apply optimization flags from config if not explicitly provided
        self._skip_llm_verification = (
            skip_llm_verification if skip_llm_verification is not None else config.skip_llm_verification
        )
        self._lazy_reranker = lazy_reranker if lazy_reranker is not None else config.lazy_reranker

        # Apply defaults from config
        db_url = db_url or config.database_url
        memory_llm_provider = memory_llm_provider or config.llm_provider
        memory_llm_api_key = memory_llm_api_key or config.llm_api_key
        if not memory_llm_api_key and requires_api_key(memory_llm_provider):
            raise ValueError("LLM API key is required. Set ATULYA_API_LLM_API_KEY environment variable.")
        memory_llm_model = memory_llm_model or config.llm_model
        memory_llm_base_url = memory_llm_base_url or config.get_llm_base_url() or None
        # Track pg0 instance (if used)
        self._pg0: EmbeddedPostgres | None = None

        # Initialize PostgreSQL connection URL
        # The actual URL will be set during initialize() after starting the server
        # Supports: "pg0" (default instance), "pg0://instance-name" (named instance), or regular postgresql:// URL
        self._use_pg0, self._pg0_instance_name, self._pg0_port = parse_pg0_url(db_url)
        if self._use_pg0:
            self.db_url = None
        else:
            self.db_url = db_url

        # Set default base URL if not provided
        if memory_llm_base_url is None:
            if memory_llm_provider.lower() == "groq":
                memory_llm_base_url = "https://api.groq.com/openai/v1"
            elif memory_llm_provider.lower() == "ollama":
                memory_llm_base_url = "http://localhost:11434/v1"
            else:
                memory_llm_base_url = ""

        # Connection pool (will be created in initialize())
        self._pool = None
        self._initialized = False
        self._pool_min_size = pool_min_size if pool_min_size is not None else config.db_pool_min_size
        self._pool_max_size = pool_max_size if pool_max_size is not None else config.db_pool_max_size
        self._db_command_timeout = db_command_timeout if db_command_timeout is not None else config.db_command_timeout
        self._db_acquire_timeout = db_acquire_timeout if db_acquire_timeout is not None else config.db_acquire_timeout
        self._run_migrations = run_migrations
        self._retain_entity_lookup = config.retain_entity_lookup
        self._brain_runtime = AtulyaBrainRuntime(
            BrainRuntimeConfig(
                enabled=config.brain_enabled,
                cache_dir=config.brain_cache_dir,
                default_file_name=config.brain_default_file_name,
                native_library_path=config.brain_native_library_path,
                circuit_breaker_threshold=config.brain_circuit_breaker_threshold,
                max_file_size_bytes=config.brain_max_file_size_mb * 1024 * 1024,
                hardware_tier=cast(Any, config.brain_hardware_tier),
                prediction_mode=cast(Any, config.brain_prediction_mode),
            )
        )

        # Webhook manager (will be created in initialize() after pool is ready)
        self._webhook_manager = None
        self._http_client: httpx.AsyncClient | None = None

        # Initialize entity resolver (will be created in initialize())
        self.entity_resolver = None

        # Initialize embeddings (from env vars if not provided)
        if embeddings is not None:
            self.embeddings = embeddings
        else:
            self.embeddings = create_embeddings_from_env()

        # Initialize query analyzer
        if query_analyzer is not None:
            self.query_analyzer = query_analyzer
        else:
            from .query_analyzer import DateparserQueryAnalyzer

            self.query_analyzer = DateparserQueryAnalyzer()

        # Initialize LLM configuration (default, used as fallback)
        self._llm_config = LLMConfig(
            provider=memory_llm_provider,
            api_key=memory_llm_api_key,
            base_url=memory_llm_base_url,
            model=memory_llm_model,
        )

        # Store client and model for convenience (deprecated: use _llm_config.call() instead)
        self._llm_client = self._llm_config._client
        self._llm_model = self._llm_config.model

        # Initialize per-operation LLM configs (fall back to default if not specified)
        # Retain LLM config - for fact extraction (benefits from strong structured output)
        retain_provider = retain_llm_provider or config.retain_llm_provider or memory_llm_provider
        retain_api_key = retain_llm_api_key or config.retain_llm_api_key or memory_llm_api_key
        retain_model = retain_llm_model or config.retain_llm_model or memory_llm_model
        retain_base_url = retain_llm_base_url or config.retain_llm_base_url or memory_llm_base_url
        # Apply provider-specific base URL defaults for retain
        if retain_base_url is None:
            if retain_provider.lower() == "groq":
                retain_base_url = "https://api.groq.com/openai/v1"
            elif retain_provider.lower() == "ollama":
                retain_base_url = "http://localhost:11434/v1"
            else:
                retain_base_url = ""

        self._retain_llm_config = LLMConfig(
            provider=retain_provider,
            api_key=retain_api_key,
            base_url=retain_base_url,
            model=retain_model,
        )

        # Reflect LLM config - for think/observe operations (can use lighter models)
        reflect_provider = reflect_llm_provider or config.reflect_llm_provider or memory_llm_provider
        reflect_api_key = reflect_llm_api_key or config.reflect_llm_api_key or memory_llm_api_key
        reflect_model = reflect_llm_model or config.reflect_llm_model or memory_llm_model
        reflect_base_url = reflect_llm_base_url or config.reflect_llm_base_url or memory_llm_base_url
        # Apply provider-specific base URL defaults for reflect
        if reflect_base_url is None:
            if reflect_provider.lower() == "groq":
                reflect_base_url = "https://api.groq.com/openai/v1"
            elif reflect_provider.lower() == "ollama":
                reflect_base_url = "http://localhost:11434/v1"
            else:
                reflect_base_url = ""

        self._reflect_llm_config = LLMConfig(
            provider=reflect_provider,
            api_key=reflect_api_key,
            base_url=reflect_base_url,
            model=reflect_model,
        )

        # Consolidation LLM config - for mental model consolidation (can use efficient models)
        consolidation_provider = consolidation_llm_provider or config.consolidation_llm_provider or memory_llm_provider
        consolidation_api_key = consolidation_llm_api_key or config.consolidation_llm_api_key or memory_llm_api_key
        consolidation_model = consolidation_llm_model or config.consolidation_llm_model or memory_llm_model
        consolidation_base_url = consolidation_llm_base_url or config.consolidation_llm_base_url or memory_llm_base_url
        # Apply provider-specific base URL defaults for consolidation
        if consolidation_base_url is None:
            if consolidation_provider.lower() == "groq":
                consolidation_base_url = "https://api.groq.com/openai/v1"
            elif consolidation_provider.lower() == "ollama":
                consolidation_base_url = "http://localhost:11434/v1"
            else:
                consolidation_base_url = ""

        self._consolidation_llm_config = LLMConfig(
            provider=consolidation_provider,
            api_key=consolidation_api_key,
            base_url=consolidation_base_url,
            model=consolidation_model,
        )

        # Initialize cross-encoder reranker (cached for performance)
        self._cross_encoder_reranker = CrossEncoderReranker(cross_encoder=cross_encoder)

        # Initialize task backend
        # If no custom backend provided, use BrokerTaskBackend which stores tasks in PostgreSQL
        # The pool_getter lambda will return the pool once it's initialized
        self._task_backend = task_backend or BrokerTaskBackend(
            pool_getter=lambda: self._pool,
            schema_getter=get_current_schema,
        )

        # Backpressure mechanism: limit concurrent searches to prevent overwhelming the database
        # Configurable via ATULYA_API_RECALL_MAX_CONCURRENT (default: 50)
        self._search_semaphore = asyncio.Semaphore(get_config().recall_max_concurrent)

        # Backpressure for put operations: limit concurrent puts to prevent database contention
        # Each put_batch holds a connection for the entire transaction, so we limit to 5
        # concurrent puts to avoid connection pool exhaustion and reduce write contention
        self._put_semaphore = asyncio.Semaphore(5)

        # initialize encoding eagerly to avoid delaying the first time
        _get_tiktoken_encoding()

        # Store operation validator extension (optional)
        self._operation_validator = operation_validator

        # Store tenant extension (always set, use default if none provided)
        if tenant_extension is None:
            from ..extensions.builtin.tenant import DefaultTenantExtension

            tenant_extension = DefaultTenantExtension(config={})
        self._tenant_extension = tenant_extension
        self._graph_intelligence_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._graph_summary_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._graph_neighborhood_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}

    @property
    def tenant_extension(self) -> "TenantExtension | None":
        """The configured tenant extension, if any."""
        return self._tenant_extension

    async def _validate_operation(self, validation_coro) -> None:
        """
        Run validation if an operation validator is configured.

        Args:
            validation_coro: Coroutine that returns a ValidationResult

        Raises:
            OperationValidationError: If validation fails
        """
        if self._operation_validator is None:
            return

        from atulya_api.extensions import OperationValidationError

        result = await validation_coro
        if not result.allowed:
            raise OperationValidationError(result.reason or "Operation not allowed", result.status_code)

    async def _authenticate_tenant(self, request_context: "RequestContext | None") -> str:
        """
        Authenticate tenant and set schema in context variable.

        The schema is stored in a contextvar for async-safe, per-task isolation.
        Use fq_table(table_name) to get fully-qualified table names.

        Args:
            request_context: The request context with API key. Required if tenant_extension is configured.

        Returns:
            Schema name that was set in the context.

        Raises:
            AuthenticationError: If authentication fails or request_context is missing when required.
        """
        from atulya_api.extensions import AuthenticationError

        if request_context is None:
            raise AuthenticationError("RequestContext is required")

        # For internal/background operations (e.g., worker tasks), skip extension authentication.
        # The task was already authenticated at submission time, and execute_task sets _current_schema
        # from the task's _schema field.
        if request_context.internal:
            return _current_schema.get()

        # Authenticate through tenant extension (always set, may be default no-auth extension)
        tenant_context = await self._tenant_extension.authenticate(request_context)

        _current_schema.set(tenant_context.schema_name)
        return tenant_context.schema_name

    async def _handle_batch_retain(self, task_dict: dict[str, Any]):
        """
        Handler for batch retain tasks.

        Args:
            task_dict: Dict with 'bank_id', 'contents', 'operation_id'

        Raises:
            ValueError: If bank_id is missing
            Exception: Any exception from retain_batch_async (propagates to execute_task for retry)
        """
        bank_id = task_dict.get("bank_id")
        if not bank_id:
            raise ValueError("bank_id is required for batch retain task")
        contents = task_dict.get("contents", [])
        document_tags = task_dict.get("document_tags")
        operation_id = task_dict.get("operation_id")  # For batch API crash recovery

        logger.info(
            f"[BATCH_RETAIN_TASK] Starting background batch retain for bank_id={bank_id}, {len(contents)} items, operation_id={operation_id}"
        )

        # Restore tenant_id/api_key_id from task payload so extensions
        # (e.g., operation validators) can attribute the operation correctly.
        # internal=True to skip extension auth (worker has no API key),
        # user_initiated=True so extensions know this originated from a user request.
        from atulya_api.models import RequestContext

        context = RequestContext(
            internal=True,
            user_initiated=True,
            tenant_id=task_dict.get("_tenant_id"),
            api_key_id=task_dict.get("_api_key_id"),
        )
        await self.retain_batch_async(
            bank_id=bank_id,
            contents=contents,
            document_tags=document_tags,
            request_context=context,
            operation_id=operation_id,
            outbox_callback=self._build_retain_outbox_callback(
                bank_id=bank_id,
                contents=contents,
                operation_id=operation_id,
                schema=_current_schema.get(),
            ),
        )

        # If this retain was triggered by file conversion, update document with file metadata
        file_metadata = task_dict.get("_file_metadata")
        if file_metadata and len(contents) == 1:
            doc_id = contents[0].get("document_id")
            if doc_id:
                pool = await self._get_pool()
                async with acquire_with_retry(pool) as conn:
                    await conn.execute(
                        f"""
                        UPDATE {fq_table("documents")}
                        SET file_storage_key = $3,
                            file_original_name = $4,
                            file_content_type = $5,
                            updated_at = NOW()
                        WHERE id = $1 AND bank_id = $2
                        """,
                        doc_id,
                        bank_id,
                        file_metadata["file_storage_key"],
                        file_metadata["file_original_name"],
                        file_metadata["file_content_type"],
                    )

        logger.info(f"[BATCH_RETAIN_TASK] Completed background batch retain for bank_id={bank_id}")

    async def _handle_file_convert_retain(self, task_dict: dict[str, Any]):
        """
        Handler for file conversion tasks.

        Converts a file to markdown, then submits a separate async retain operation
        and marks this conversion as completed — all in a single transaction.
        This avoids holding a worker slot during the expensive retain pipeline.

        Args:
            task_dict: Dict with 'bank_id', 'storage_key', 'parser', etc.

        Raises:
            ValueError: If required fields are missing
            Exception: Any exception from conversion (includes filename in error)
        """
        bank_id = task_dict.get("bank_id")
        storage_key = task_dict.get("storage_key")
        document_id = task_dict.get("document_id")
        operation_id = task_dict.get("operation_id")
        filename = task_dict.get("original_filename", "unknown")

        if not all([bank_id, storage_key, document_id]):
            raise ValueError("bank_id, storage_key, and document_id are required for file_convert_retain task")

        logger.info(f"[FILE_CONVERT_RETAIN] Starting for bank_id={bank_id}, document_id={document_id}, file={filename}")

        try:
            # Retrieve file from storage
            file_data = await self._file_storage.retrieve(storage_key)

            # Convert to markdown using the ordered fallback chain stored in the task payload.
            # task_dict["parser"] is always a list[str] set at submission time.
            parser_chain: list[str] = task_dict.get("parser") or []
            if not parser_chain:
                raise ValueError("No parser chain defined for file_convert_retain task")
            convert_result = await self._parser_registry.convert_with_fallback(
                parsers=parser_chain,
                file_data=file_data,
                filename=filename,
                content_type=task_dict.get("content_type"),
            )
            markdown_content = convert_result.content
            winning_parser = convert_result.parser_name
        except Exception as e:
            # Re-raise with filename context for better error reporting
            error_msg = f"Failed to parse file '{filename}': {str(e)}"
            logger.error(f"[FILE_CONVERT_RETAIN] {error_msg}")
            raise RuntimeError(error_msg) from e

        logger.info(
            f"[FILE_CONVERT_RETAIN] Converted file for bank_id={bank_id}, "
            f"document_id={document_id}, {len(markdown_content)} chars. Submitting retain task."
        )

        # Fire file conversion hook (e.g., for Iris billing)
        if self._operation_validator:
            try:
                from atulya_api.extensions.operation_validator import FileConvertResult
                from atulya_api.models import RequestContext

                convert_context = RequestContext(
                    internal=True,
                    user_initiated=True,
                    tenant_id=task_dict.get("_tenant_id"),
                    api_key_id=task_dict.get("_api_key_id"),
                )
                await self._operation_validator.on_file_convert_complete(
                    FileConvertResult(
                        bank_id=bank_id,
                        parser_name=winning_parser,
                        filename=filename,
                        output_chars=len(markdown_content),
                        output_text=markdown_content,
                        request_context=convert_context,
                    )
                )
            except Exception as e:
                logger.warning(f"[FILE_CONVERT_RETAIN] on_file_convert_complete hook failed: {e}")

        # Build retain task payload
        retain_contents = [
            {
                "content": markdown_content,
                "document_id": document_id,
                "context": task_dict.get("context"),
                "metadata": task_dict.get("metadata", {}),
                "tags": task_dict.get("tags", []),
                "timestamp": task_dict.get("timestamp"),
            }
        ]
        document_tags = task_dict.get("document_tags")

        retain_task_payload: dict[str, Any] = {"contents": retain_contents}
        if document_tags:
            retain_task_payload["document_tags"] = document_tags

        # Pass tenant/api_key context through to retain task
        if task_dict.get("_tenant_id"):
            retain_task_payload["_tenant_id"] = task_dict["_tenant_id"]
        if task_dict.get("_api_key_id"):
            retain_task_payload["_api_key_id"] = task_dict["_api_key_id"]

        # File metadata to attach after retain creates the document
        retain_task_payload["_file_metadata"] = {
            "file_storage_key": storage_key,
            "file_original_name": task_dict["original_filename"],
            "file_content_type": task_dict["content_type"],
        }

        # In one transaction: create the retain async operation AND mark this conversion as completed
        retain_operation_id = uuid.uuid4()
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            async with conn.transaction():
                # Create the retain operation record
                await conn.execute(
                    f"""
                    INSERT INTO {fq_table("async_operations")}
                    (operation_id, bank_id, operation_type, result_metadata, status)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    retain_operation_id,
                    bank_id,
                    "retain",
                    json.dumps({}),
                    "pending",
                )

                # Mark this file_convert_retain operation as completed
                if operation_id:
                    await conn.execute(
                        f"""
                        UPDATE {fq_table("async_operations")}
                        SET status = 'completed', updated_at = NOW(), completed_at = NOW()
                        WHERE operation_id = $1
                        """,
                        uuid.UUID(operation_id),
                    )

        # Submit the retain task to the task backend (outside the transaction)
        full_retain_payload = {
            "type": "batch_retain",
            "operation_id": str(retain_operation_id),
            "bank_id": bank_id,
            **retain_task_payload,
        }
        await self._task_backend.submit_task(full_retain_payload)

        logger.info(
            f"[FILE_CONVERT_RETAIN] Completed conversion for bank_id={bank_id}, "
            f"document_id={document_id}. Retain task submitted as operation {retain_operation_id}"
        )

        # Delete file bytes from storage if configured (saves storage costs)
        from ..config import get_config

        config = get_config()
        if config.file_delete_after_retain:
            try:
                await self._file_storage.delete(storage_key)
                logger.info(f"[FILE_CONVERT_RETAIN] Deleted file bytes for {storage_key} (conversion completed)")
            except Exception as e:
                # Non-fatal - log and continue
                logger.warning(f"[FILE_CONVERT_RETAIN] Failed to delete file {storage_key}: {e}")

    def _chunk_codebase_text(self, text: str, *, chunk_size: int = 2000, overlap: int = 200) -> list[str]:
        """Split source text into deterministic overlapping chunks for recall."""
        normalized = text.strip()
        if not normalized:
            return []

        chunks: list[str] = []
        start = 0
        text_len = len(normalized)
        while start < text_len:
            end = min(text_len, start + chunk_size)
            if end < text_len:
                newline_break = normalized.rfind("\n", start, end)
                if newline_break > start + 200:
                    end = newline_break
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= text_len:
                break
            start = max(end - overlap, start + 1)
        return chunks

    @staticmethod
    def _encode_codebase_cursor(offset: int) -> str:
        payload = json.dumps({"offset": max(0, offset)}, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii")

    @staticmethod
    def _decode_codebase_cursor(cursor: str | None) -> int:
        if not cursor:
            return 0
        try:
            payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        except Exception:
            return 0
        try:
            return max(0, int(payload.get("offset", 0)))
        except (TypeError, ValueError, AttributeError):
            return 0

    async def _build_codebase_chunk_graph(
        self,
        *,
        indexed_files: list[IndexedFile],
        file_edges: list[IndexedEdge],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build cluster and related-chunk metadata from deterministic chunks."""
        chunk_rows: list[dict[str, Any]] = []
        chunks_by_path: dict[str, list[IndexedChunk]] = {}

        for indexed_file in indexed_files:
            for chunk in indexed_file.chunks:
                chunks_by_path.setdefault(chunk.path, []).append(chunk)
                chunk_rows.append(
                    {
                        "chunk_key": chunk.chunk_key,
                        "path": chunk.path,
                        "language": chunk.language,
                        "kind": chunk.kind,
                        "label": chunk.label,
                        "content_hash": chunk.content_hash,
                        "content_text": chunk.content_text,
                        "preview_text": chunk.preview_text,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "container": chunk.container,
                        "parent_symbol": chunk.parent_symbol,
                        "parent_fq_name": chunk.parent_fq_name,
                        "parse_confidence": chunk.parse_confidence,
                        "cluster_id": None,
                        "cluster_label": None,
                    }
                )

        if not chunk_rows:
            return [], []

        file_neighbors: dict[str, set[str]] = {}
        for edge in file_edges:
            if edge.edge_type != "imports" or not edge.to_path:
                continue
            file_neighbors.setdefault(edge.from_path, set()).add(edge.to_path)
            file_neighbors.setdefault(edge.to_path, set()).add(edge.from_path)

        texts = [row["content_text"] for row in chunk_rows]
        embeddings: list[list[float]] = []
        try:
            from .retain import embedding_processing

            embeddings = await embedding_processing.generate_embeddings_batch(self.embeddings, texts)
        except Exception:
            embeddings = []

        row_by_key = {row["chunk_key"]: row for row in chunk_rows}
        cluster_members: dict[str, list[str]] = {}
        chunk_edges: list[dict[str, Any]] = []
        seen_edge_keys: set[tuple[str, str, str]] = set()

        for chunk in chunk_rows:
            path_prefix = "/".join(chunk["path"].split("/")[:2]) if "/" in chunk["path"] else chunk["path"]
            cluster_id = hashlib.sha1(
                f"{chunk['language'] or 'unknown'}|{path_prefix}|{chunk['container'] or chunk['path']}".encode("utf-8")
            ).hexdigest()[:16]
            cluster_label = chunk["container"] or path_prefix or chunk["path"]
            chunk["cluster_id"] = cluster_id
            chunk["cluster_label"] = cluster_label
            cluster_members.setdefault(cluster_id, []).append(chunk["chunk_key"])

        def add_edge(edge_type: str, from_key: str, to_key: str, score: float | None, label: str | None) -> None:
            if from_key == to_key:
                return
            ordered = tuple(sorted((from_key, to_key)))
            dedupe_key = (edge_type, ordered[0], ordered[1])
            if dedupe_key in seen_edge_keys:
                return
            seen_edge_keys.add(dedupe_key)
            chunk_edges.append(
                {
                    "edge_type": edge_type,
                    "from_chunk_key": from_key,
                    "to_chunk_key": to_key,
                    "score": score,
                    "label": label,
                }
            )

        for path, path_chunks in chunks_by_path.items():
            ordered = sorted(path_chunks, key=lambda item: (item.start_line, item.end_line))
            for left, right in zip(ordered, ordered[1:], strict=False):
                add_edge("adjacent", left.chunk_key, right.chunk_key, None, "same-file")
            for neighbor_path in file_neighbors.get(path, set()):
                for left in ordered:
                    for right in chunks_by_path.get(neighbor_path, [])[:4]:
                        add_edge("file_import", left.chunk_key, right.chunk_key, None, neighbor_path)

        if embeddings and len(embeddings) == len(chunk_rows):
            embedding_index_by_key = {row["chunk_key"]: index for index, row in enumerate(chunk_rows)}
            candidate_keys: dict[str, list[str]] = {}
            for row in chunk_rows:
                candidates: list[str] = []
                for same_path_chunk in chunks_by_path.get(row["path"], []):
                    if same_path_chunk.chunk_key != row["chunk_key"]:
                        candidates.append(same_path_chunk.chunk_key)
                for neighbor_path in file_neighbors.get(row["path"], set()):
                    candidates.extend(chunk.chunk_key for chunk in chunks_by_path.get(neighbor_path, [])[:8])
                if len(chunk_rows) <= 160:
                    candidates.extend(
                        other_row["chunk_key"]
                        for other_row in chunk_rows
                        if other_row["language"] == row["language"] and other_row["chunk_key"] != row["chunk_key"]
                    )
                candidate_keys[row["chunk_key"]] = list(dict.fromkeys(candidates))

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

        cluster_label_by_id = {
            cluster_id: (
                sorted(
                    members,
                    key=lambda member_key: (
                        row_by_key[member_key]["path"],
                        row_by_key[member_key]["start_line"],
                    ),
                )[0]
            )
            for cluster_id, members in cluster_members.items()
        }
        for cluster_id, member_key in cluster_label_by_id.items():
            row = row_by_key[member_key]
            label = row["cluster_label"] or row["label"]
            for chunk_key in cluster_members[cluster_id]:
                row_by_key[chunk_key]["cluster_label"] = label

        return chunk_rows, chunk_edges

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

    async def _delete_codebase_memory_chunk(
        self,
        conn: asyncpg.Connection,
        *,
        bank_id: str,
        document_id: str,
    ) -> None:
        """Delete a chunk-backed codebase memory document if it exists."""
        await conn.execute(
            f"DELETE FROM {fq_table('documents')} WHERE id = $1 AND bank_id = $2",
            document_id,
            bank_id,
        )

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
        return document_id

    async def _delete_codebase_memory_document(
        self,
        conn: asyncpg.Connection,
        *,
        bank_id: str,
        document_id: str,
    ) -> None:
        """Delete a codebase-backed memory document if it exists."""
        await conn.execute(
            f"DELETE FROM {fq_table('documents')} WHERE id = $1 AND bank_id = $2",
            document_id,
            bank_id,
        )

    async def _copy_codebase_path_graph(
        self,
        conn: asyncpg.Connection,
        *,
        bank_id: str,
        codebase_id: str,
        source_snapshot_id: str,
        target_snapshot_id: str,
        path: str,
        valid_paths: set[str],
    ) -> None:
        """Copy deterministic graph rows for an unchanged file into a new snapshot."""
        source_snapshot_uuid = uuid.UUID(source_snapshot_id)
        target_snapshot_uuid = uuid.UUID(target_snapshot_id)
        codebase_uuid = uuid.UUID(codebase_id)

        symbols = await conn.fetch(
            f"""
            SELECT path, language, name, kind, fq_name, container, start_line, end_line
            FROM {fq_table("codebase_symbols")}
            WHERE snapshot_id = $1 AND path = $2 AND bank_id = $3
            """,
            source_snapshot_uuid,
            path,
            bank_id,
        )
        for row in symbols:
            await conn.execute(
                f"""
                INSERT INTO {fq_table("codebase_symbols")}
                    (codebase_id, snapshot_id, bank_id, path, language, name, kind, fq_name, container, start_line, end_line)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                codebase_uuid,
                target_snapshot_uuid,
                bank_id,
                row["path"],
                row["language"],
                row["name"],
                row["kind"],
                row["fq_name"],
                row["container"],
                row["start_line"],
                row["end_line"],
            )

        edges = await conn.fetch(
            f"""
            SELECT edge_type, from_path, from_symbol, to_path, to_symbol, target_ref, label
            FROM {fq_table("codebase_edges")}
            WHERE snapshot_id = $1 AND from_path = $2 AND bank_id = $3
            """,
            source_snapshot_uuid,
            path,
            bank_id,
        )
        for row in edges:
            if row["to_path"] and row["to_path"] not in valid_paths:
                continue
            await conn.execute(
                f"""
                INSERT INTO {fq_table("codebase_edges")}
                    (codebase_id, snapshot_id, bank_id, edge_type, from_path, from_symbol, to_path, to_symbol, target_ref, label)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                codebase_uuid,
                target_snapshot_uuid,
                bank_id,
                row["edge_type"],
                row["from_path"],
                row["from_symbol"],
                row["to_path"],
                row["to_symbol"],
                row["target_ref"],
                row["label"],
            )

    async def _update_codebase_snapshot(
        self,
        snapshot_id: str,
        *,
        status: str,
        stats: dict[str, Any] | None = None,
        source_commit_sha: str | None = None,
    ) -> None:
        """Persist codebase snapshot status and stats."""
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            await conn.execute(
                f"""
                UPDATE {fq_table("codebase_snapshots")}
                SET status = $2,
                    stats = COALESCE($3::jsonb, stats),
                    source_commit_sha = COALESCE($4, source_commit_sha),
                    updated_at = NOW()
                WHERE id = $1
                """,
                uuid.UUID(snapshot_id),
                status,
                json.dumps(stats) if stats is not None else None,
                source_commit_sha,
            )

    async def _mark_codebase_snapshot_approved(self, snapshot_id: str) -> None:
        """Mark a codebase snapshot as approved for memory hydration."""
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            await conn.execute(
                f"""
                UPDATE {fq_table("codebase_snapshots")}
                SET status = 'approved',
                    approved_at = NOW(),
                    updated_at = NOW()
                WHERE id = $1
                """,
                uuid.UUID(snapshot_id),
            )

    async def _mark_codebase_snapshot_failed(self, snapshot_id: str, error_message: str) -> None:
        """Mark a codebase snapshot as failed."""
        await self._update_codebase_snapshot(
            snapshot_id,
            status="failed",
            stats={"error": error_message[:2000]},
        )

    async def _store_codebase_snapshot_archive(
        self,
        *,
        bank_id: str,
        codebase_id: str,
        snapshot_id: str,
        archive_bytes: bytes,
    ) -> str:
        """Persist raw snapshot archive bytes for later review and approval."""
        storage_key = f"banks/{bank_id}/codebases/{codebase_id}/snapshots/{snapshot_id}/archive.zip"
        await self._file_storage.store(
            file_data=archive_bytes,
            key=storage_key,
            metadata={"bank_id": bank_id, "codebase_id": codebase_id, "snapshot_id": snapshot_id},
        )
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            await conn.execute(
                f"""
                UPDATE {fq_table("codebase_snapshots")}
                SET source_archive_storage_key = $2, updated_at = NOW()
                WHERE id = $1
                """,
                uuid.UUID(snapshot_id),
                storage_key,
            )
        return storage_key

    async def _hydrate_codebase_snapshot_memory(
        self,
        *,
        bank_id: str,
        codebase_id: str,
        snapshot_id: str,
        operation_id: str | None = None,
        batch_size: int = 20,
        memory_ingest_mode: str = "direct",
        request_context: "RequestContext | None" = None,
    ) -> dict[str, int]:
        """Hydrate routed memory chunks into stable memory documents in small batches."""
        codebase_uuid = uuid.UUID(codebase_id)
        snapshot_uuid = uuid.UUID(snapshot_id)

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            approved_snapshot_row = await conn.fetchrow(
                f"""
                SELECT approved_snapshot_id
                FROM {fq_table("codebases")}
                WHERE id = $1 AND bank_id = $2
                """,
                codebase_uuid,
                bank_id,
            )
            approved_snapshot_id = (
                str(approved_snapshot_row["approved_snapshot_id"])
                if approved_snapshot_row and approved_snapshot_row["approved_snapshot_id"]
                else None
            )

            current_rows = await conn.fetch(
                f"""
                SELECT c.id, c.chunk_key, c.path, c.language, c.label, c.content_hash, c.content_text, c.document_id,
                       c.start_line, c.end_line, c.parent_symbol, c.cluster_label, r.route_target
                FROM {fq_table("codebase_chunks")} c
                JOIN {fq_table("codebase_review_routes")} r
                  ON r.snapshot_id = c.snapshot_id AND r.chunk_id = c.id
                WHERE c.snapshot_id = $1 AND c.bank_id = $2 AND c.codebase_id = $3
                ORDER BY c.path ASC, c.start_line ASC
                """,
                snapshot_uuid,
                bank_id,
                codebase_uuid,
            )

            previous_rows = []
            if approved_snapshot_id:
                previous_rows = await conn.fetch(
                    f"""
                    SELECT c.chunk_key, c.content_hash, c.document_id, r.route_target
                    FROM {fq_table("codebase_chunks")} c
                    JOIN {fq_table("codebase_review_routes")} r
                      ON r.snapshot_id = c.snapshot_id AND r.chunk_id = c.id
                    WHERE c.snapshot_id = $1 AND c.bank_id = $2 AND c.codebase_id = $3
                    """,
                    uuid.UUID(approved_snapshot_id),
                    bank_id,
                    codebase_uuid,
                )

        previous_memory_chunks = {
            row["chunk_key"]: {"content_hash": row["content_hash"], "document_id": row["document_id"]}
            for row in previous_rows
            if row["route_target"] == "memory" and row["document_id"]
        }
        current_memory_rows = [row for row in current_rows if row["route_target"] == "memory"]
        current_memory_keys = {row["chunk_key"] for row in current_memory_rows}

        hydrated_files = 0
        reused_files = 0
        deleted_files = 0

        if operation_id:
            await self._set_operation_stage(
                operation_id,
                "batching",
                {
                    "snapshot_id": snapshot_id,
                    "codebase_id": codebase_id,
                    "total_items": len(current_memory_rows),
                    "batch_size": batch_size,
                },
            )

        for start in range(0, len(current_memory_rows), batch_size):
            batch = current_memory_rows[start : start + batch_size]
            if operation_id:
                await self._set_operation_stage(
                    operation_id,
                    "hydrating",
                    {
                        "snapshot_id": snapshot_id,
                        "codebase_id": codebase_id,
                        "processed": start,
                        "batch_size": len(batch),
                        "memory_ingest_mode": memory_ingest_mode,
                    },
                )

            rows_to_update: list[tuple[uuid.UUID, str]] = []
            rows_to_ingest: list[asyncpg.Record] = []
            for row in batch:
                stable_document_id = f"codebase:{codebase_id}:chunk:{row['chunk_key']}"
                previous = previous_memory_chunks.get(row["chunk_key"])
                rows_to_update.append((row["id"], stable_document_id))
                if previous and previous["content_hash"] == row["content_hash"]:
                    reused_files += 1
                    continue
                rows_to_ingest.append(row)

            if rows_to_ingest:
                if memory_ingest_mode == "retain":
                    if request_context is None:
                        raise ValueError("request_context is required for retain-based codebase hydration")
                    rows_by_language: dict[str | None, list[dict[str, Any]]] = {}
                    for row in rows_to_ingest:
                        stable_document_id = f"codebase:{codebase_id}:chunk:{row['chunk_key']}"
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
                                "document_id": stable_document_id,
                            }
                        )
                    for language, contents in rows_by_language.items():
                        document_tags = ["scope:codebase", f"codebase:{codebase_id}"]
                        if language:
                            document_tags.append(f"language:{language}")
                        await self.retain_batch_async(
                            bank_id=bank_id,
                            contents=contents,
                            request_context=request_context,
                            document_tags=document_tags,
                        )
                    hydrated_files += len(rows_to_ingest)
                else:
                    async with acquire_with_retry(pool) as conn:
                        async with conn.transaction():
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
                    hydrated_files += len(rows_to_ingest)

            async with acquire_with_retry(pool) as conn:
                async with conn.transaction():
                    for chunk_id, document_id in rows_to_update:
                        await conn.execute(
                            f"""
                            UPDATE {fq_table("codebase_chunks")}
                            SET document_id = $4
                            WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3 AND id = $5
                            """,
                            snapshot_uuid,
                            bank_id,
                            codebase_uuid,
                            document_id,
                            chunk_id,
                        )

        stale_chunk_keys = set(previous_memory_chunks) - current_memory_keys
        for stale_key in stale_chunk_keys:
            previous_document_id = cast(str | None, previous_memory_chunks[stale_key]["document_id"])
            if not previous_document_id:
                continue
            async with acquire_with_retry(pool) as conn:
                async with conn.transaction():
                    await self._delete_codebase_memory_chunk(
                        conn,
                        bank_id=bank_id,
                        document_id=previous_document_id,
                    )
                    deleted_files += 1

        if operation_id:
            await self._set_operation_stage(
                operation_id,
                "pruning_removed_items",
                {"snapshot_id": snapshot_id, "codebase_id": codebase_id, "deleted": deleted_files},
            )

        return {
            "hydrated_files": hydrated_files,
            "reused_files": reused_files,
            "deleted_files": deleted_files,
            "applied_routes": len(current_memory_rows),
        }

    async def _resolve_public_github_commit_sha(self, owner: str, repo: str, ref: str) -> str:
        """Resolve a public GitHub ref to a commit SHA."""
        client = self._http_client or httpx.AsyncClient(timeout=30.0)
        owns_client = self._http_client is None
        try:
            response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits/{ref}",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "atulya-api"},
            )
            if response.status_code == 404:
                raise ValueError(f"Public GitHub ref not found: {owner}/{repo}@{ref}")
            response.raise_for_status()
            payload = response.json()
            sha = payload.get("sha")
            if not sha:
                raise ValueError(f"GitHub did not return a commit SHA for {owner}/{repo}@{ref}")
            return str(sha)
        finally:
            if owns_client:
                await client.aclose()

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

            raise ValueError(f"GitHub archive redirect chain exceeded limit for {owner}/{repo}@{commit_sha}")
        finally:
            if response is not None:
                await response.aclose()
            if owns_client:
                await client.aclose()

    async def _process_codebase_archive(
        self,
        *,
        bank_id: str,
        codebase_id: str,
        snapshot_id: str,
        archive_bytes: bytes,
        archive_storage_key: str | None,
        root_path: str | None,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        source_commit_sha: str | None,
        operation_id: str | None,
    ) -> dict[str, Any]:
        """Build an ASD-backed reviewable codebase snapshot without hydrating memory."""
        if operation_id:
            await self._set_operation_stage(
                operation_id, "processing", {"snapshot_id": snapshot_id, "codebase_id": codebase_id}
            )
        await self._update_codebase_snapshot(snapshot_id, status="processing", source_commit_sha=source_commit_sha)

        if not archive_storage_key:
            archive_storage_key = await self._store_codebase_snapshot_archive(
                bank_id=bank_id,
                codebase_id=codebase_id,
                snapshot_id=snapshot_id,
                archive_bytes=archive_bytes,
            )

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            async with conn.transaction():
                codebase_row = await conn.fetchrow(
                    f"""
                    SELECT current_snapshot_id
                    FROM {fq_table("codebases")}
                    WHERE id = $1 AND bank_id = $2
                    """,
                    uuid.UUID(codebase_id),
                    bank_id,
                )

                if not codebase_row:
                    raise ValueError(f"Codebase {codebase_id} not found in bank {bank_id}")

                previous_snapshot_id = (
                    str(codebase_row["current_snapshot_id"]) if codebase_row["current_snapshot_id"] else None
                )
                previous_files_rows = []
                previous_chunk_route_rows = []
                if previous_snapshot_id:
                    previous_files_rows = await conn.fetch(
                        f"""
                        SELECT path, content_hash, document_id, status
                        FROM {fq_table("codebase_files")}
                        WHERE snapshot_id = $1
                        """,
                        uuid.UUID(previous_snapshot_id),
                    )
                    previous_chunk_route_rows = await conn.fetch(
                        f"""
                        SELECT c.chunk_key, c.content_hash, r.route_target
                        FROM {fq_table("codebase_chunks")} c
                        JOIN {fq_table("codebase_review_routes")} r
                          ON r.snapshot_id = c.snapshot_id AND r.chunk_id = c.id
                        WHERE c.snapshot_id = $1 AND c.bank_id = $2 AND c.codebase_id = $3
                        """,
                        uuid.UUID(previous_snapshot_id),
                        bank_id,
                        uuid.UUID(codebase_id),
                    )
                previous_hashes = {row["path"]: row["content_hash"] for row in previous_files_rows}
                previous_routes = {
                    row["chunk_key"]: {"content_hash": row["content_hash"], "route_target": row["route_target"]}
                    for row in previous_chunk_route_rows
                }

                await conn.execute(
                    f"DELETE FROM {fq_table('codebase_review_routes')} WHERE snapshot_id = $1", uuid.UUID(snapshot_id)
                )
                await conn.execute(
                    f"DELETE FROM {fq_table('codebase_chunk_edges')} WHERE snapshot_id = $1", uuid.UUID(snapshot_id)
                )
                await conn.execute(
                    f"DELETE FROM {fq_table('codebase_chunks')} WHERE snapshot_id = $1", uuid.UUID(snapshot_id)
                )
                await conn.execute(
                    f"DELETE FROM {fq_table('codebase_edges')} WHERE snapshot_id = $1", uuid.UUID(snapshot_id)
                )
                await conn.execute(
                    f"DELETE FROM {fq_table('codebase_symbols')} WHERE snapshot_id = $1", uuid.UUID(snapshot_id)
                )
                await conn.execute(
                    f"DELETE FROM {fq_table('codebase_files')} WHERE snapshot_id = $1", uuid.UUID(snapshot_id)
                )

                normalized_files = load_zip_archive(
                    archive_bytes,
                    root_path=root_path,
                    include_globs=include_globs,
                    exclude_globs=exclude_globs,
                )
                index_result = build_archive_index(normalized_files, previous_hashes=previous_hashes)
                file_edges = [edge for indexed_file in index_result.files for edge in indexed_file.edges]
                chunk_rows, chunk_edge_rows = await self._build_codebase_chunk_graph(
                    indexed_files=index_result.files,
                    file_edges=file_edges,
                )

                if operation_id:
                    await self._set_operation_stage(
                        operation_id,
                        "asd_indexing",
                        {
                            "total_files": len(index_result.files),
                            "total_chunks": len(chunk_rows),
                            "changed_files": len(index_result.changed_files),
                            "deleted_files": len(index_result.deleted_files),
                        },
                    )

                symbol_count = 0
                edge_count = 0
                indexed_count = 0
                retained_count = 0
                manifest_only_count = 0
                excluded_count = 0

                for indexed_file in index_result.files:
                    for symbol in indexed_file.symbols:
                        await conn.execute(
                            f"""
                            INSERT INTO {fq_table("codebase_symbols")}
                                (codebase_id, snapshot_id, bank_id, path, language, name, kind, fq_name, container, start_line, end_line)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                            """,
                            uuid.UUID(codebase_id),
                            uuid.UUID(snapshot_id),
                            bank_id,
                            symbol.path,
                            symbol.language,
                            symbol.name,
                            symbol.kind,
                            symbol.fq_name,
                            symbol.container,
                            symbol.start_line,
                            symbol.end_line,
                        )
                    for edge in indexed_file.edges:
                        await conn.execute(
                            f"""
                            INSERT INTO {fq_table("codebase_edges")}
                                (codebase_id, snapshot_id, bank_id, edge_type, from_path, from_symbol, to_path, to_symbol, target_ref, label)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                            """,
                            uuid.UUID(codebase_id),
                            uuid.UUID(snapshot_id),
                            bank_id,
                            edge.edge_type,
                            edge.from_path,
                            edge.from_symbol,
                            edge.to_path,
                            edge.to_symbol,
                            edge.target_ref,
                            edge.label,
                        )

                    await conn.execute(
                        f"""
                        INSERT INTO {fq_table("codebase_files")}
                            (codebase_id, snapshot_id, bank_id, path, language, size_bytes, content_hash, document_id, status, change_kind, reason)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                        """,
                        uuid.UUID(codebase_id),
                        uuid.UUID(snapshot_id),
                        bank_id,
                        indexed_file.path,
                        indexed_file.language,
                        indexed_file.size_bytes,
                        indexed_file.content_hash,
                        None,
                        indexed_file.status,
                        indexed_file.change_kind,
                        indexed_file.reason,
                    )

                    symbol_count += len(indexed_file.symbols)
                    edge_count += len(indexed_file.edges)
                    if indexed_file.status == "indexed":
                        indexed_count += 1
                    elif indexed_file.status == "retained":
                        retained_count += 1
                    elif indexed_file.status == "manifest_only":
                        manifest_only_count += 1
                    elif indexed_file.status == "excluded":
                        excluded_count += 1

                chunk_id_map: dict[str, uuid.UUID] = {}
                route_counts = {"unrouted": 0, "memory": 0, "research": 0, "dismissed": 0}
                for chunk_row in chunk_rows:
                    inserted = await conn.fetchrow(
                        f"""
                        INSERT INTO {fq_table("codebase_chunks")}
                            (codebase_id, snapshot_id, bank_id, chunk_key, document_id, path, language, kind, label,
                             content_hash, preview_text, content_text, start_line, end_line, container,
                             parent_symbol, parent_fq_name, parse_confidence, cluster_id, cluster_label)
                        VALUES ($1, $2, $3, $4, NULL, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                        RETURNING id
                        """,
                        uuid.UUID(codebase_id),
                        uuid.UUID(snapshot_id),
                        bank_id,
                        chunk_row["chunk_key"],
                        chunk_row["path"],
                        chunk_row["language"],
                        chunk_row["kind"],
                        chunk_row["label"],
                        chunk_row["content_hash"],
                        chunk_row["preview_text"],
                        chunk_row["content_text"],
                        chunk_row["start_line"],
                        chunk_row["end_line"],
                        chunk_row["container"],
                        chunk_row["parent_symbol"],
                        chunk_row["parent_fq_name"],
                        chunk_row["parse_confidence"],
                        chunk_row["cluster_id"],
                        chunk_row["cluster_label"],
                    )
                    chunk_id = inserted["id"]
                    chunk_id_map[chunk_row["chunk_key"]] = chunk_id
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

                related_chunk_count = 0
                for chunk_edge in chunk_edge_rows:
                    from_chunk_id = chunk_id_map.get(chunk_edge["from_chunk_key"])
                    to_chunk_id = chunk_id_map.get(chunk_edge["to_chunk_key"])
                    if not from_chunk_id or not to_chunk_id:
                        continue
                    await conn.execute(
                        f"""
                        INSERT INTO {fq_table("codebase_chunk_edges")}
                            (codebase_id, snapshot_id, bank_id, edge_type, from_chunk_id, to_chunk_id, score, label)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        uuid.UUID(codebase_id),
                        uuid.UUID(snapshot_id),
                        bank_id,
                        chunk_edge["edge_type"],
                        from_chunk_id,
                        to_chunk_id,
                        chunk_edge["score"],
                        chunk_edge["label"],
                    )
                    if chunk_edge["edge_type"] == "related":
                        related_chunk_count += 1

                cluster_count = len({row["cluster_id"] for row in chunk_rows if row["cluster_id"]})

                stats = {
                    "total_files": len(index_result.files),
                    "indexed_files": indexed_count,
                    "retained_files": retained_count,
                    "manifest_only_files": manifest_only_count,
                    "excluded_files": excluded_count,
                    "symbol_count": symbol_count,
                    "edge_count": edge_count,
                    "added_files": len(index_result.added_files),
                    "changed_files": len(index_result.changed_files),
                    "unchanged_files": len(index_result.unchanged_files),
                    "deleted_files": len(index_result.deleted_files),
                    "chunk_count": index_result.chunk_count,
                    "cluster_count": cluster_count,
                    "related_chunk_count": related_chunk_count,
                    "parse_coverage": round(index_result.parse_coverage, 4),
                    "review_counts": route_counts,
                }
                await conn.execute(
                    f"""
                    UPDATE {fq_table("codebase_snapshots")}
                    SET status = 'review_required',
                        stats = $2::jsonb,
                        source_commit_sha = COALESCE($3, source_commit_sha),
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    uuid.UUID(snapshot_id),
                    json.dumps(stats),
                    source_commit_sha,
                )
                await conn.execute(
                    f"""
                    UPDATE {fq_table("codebases")}
                    SET current_snapshot_id = $2, updated_at = NOW()
                    WHERE id = $1
                    """,
                    uuid.UUID(codebase_id),
                    uuid.UUID(snapshot_id),
                )

        return {
            "codebase_id": codebase_id,
            "snapshot_id": snapshot_id,
            "status": "review_required",
            "added_files": len(index_result.added_files),
            "changed_files": len(index_result.changed_files),
            "deleted_files": len(index_result.deleted_files),
            "noop": False,
            "stats": stats,
            "review_counts": route_counts,
        }

    async def _handle_codebase_import_zip(self, task_dict: dict[str, Any]) -> dict[str, Any]:
        """Handle ZIP-backed codebase import tasks."""
        storage_key = task_dict.get("storage_key")
        if not storage_key:
            raise ValueError("storage_key is required for codebase ZIP import")
        archive_bytes = await self._file_storage.retrieve(storage_key)
        return await self._process_codebase_archive(
            bank_id=task_dict["bank_id"],
            codebase_id=task_dict["codebase_id"],
            snapshot_id=task_dict["snapshot_id"],
            archive_bytes=archive_bytes,
            archive_storage_key=storage_key,
            root_path=task_dict.get("root_path"),
            include_globs=task_dict.get("include_globs"),
            exclude_globs=task_dict.get("exclude_globs"),
            source_commit_sha=task_dict.get("source_commit_sha"),
            operation_id=task_dict.get("operation_id"),
        )

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

    async def _handle_codebase_approve(self, task_dict: dict[str, Any]) -> dict[str, Any]:
        """Hydrate the selected reviewable snapshot into memory after explicit approval."""
        from atulya_api.models import RequestContext

        bank_id = task_dict["bank_id"]
        codebase_id = task_dict["codebase_id"]
        snapshot_id = task_dict["snapshot_id"]
        operation_id = task_dict.get("operation_id")
        memory_ingest_mode = task_dict.get("memory_ingest_mode", "direct")

        internal_context = RequestContext(
            internal=True,
            tenant_id=task_dict.get("_tenant_id"),
            api_key_id=task_dict.get("_api_key_id"),
        )

        if operation_id:
            await self._set_operation_stage(
                operation_id,
                "loading_snapshot",
                {
                    "snapshot_id": snapshot_id,
                    "codebase_id": codebase_id,
                    "memory_ingest_mode": memory_ingest_mode,
                },
            )

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            snapshot_row = await conn.fetchrow(
                f"""
                SELECT s.id, s.status
                FROM {fq_table("codebase_snapshots")} s
                WHERE s.id = $1 AND s.codebase_id = $2 AND s.bank_id = $3
                """,
                uuid.UUID(snapshot_id),
                uuid.UUID(codebase_id),
                bank_id,
            )
            if not snapshot_row:
                raise ValueError(f"Snapshot {snapshot_id} not found for codebase {codebase_id}")
            if snapshot_row["status"] not in {
                "review_required",
                "review_in_progress",
                "partially_approved",
                "approved",
            }:
                raise ValueError(f"Snapshot {snapshot_id} is not ready for approval.")

        hydration = await self._hydrate_codebase_snapshot_memory(
            bank_id=bank_id,
            codebase_id=codebase_id,
            snapshot_id=snapshot_id,
            operation_id=operation_id,
            memory_ingest_mode=memory_ingest_mode,
            request_context=internal_context,
        )

        async with acquire_with_retry(pool) as conn:
            route_counts = await conn.fetchrow(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE route_target = 'unrouted') AS unrouted_count,
                    COUNT(*) FILTER (WHERE route_target = 'memory') AS memory_count,
                    COUNT(*) FILTER (WHERE route_target = 'research') AS research_count,
                    COUNT(*) FILTER (WHERE route_target = 'dismissed') AS dismissed_count
                FROM {fq_table("codebase_review_routes")}
                WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3
                """,
                uuid.UUID(snapshot_id),
                bank_id,
                uuid.UUID(codebase_id),
            )
            snapshot_status = (
                "approved" if not route_counts or not route_counts["unrouted_count"] else "partially_approved"
            )
            stats_row = await conn.fetchrow(
                f"SELECT stats FROM {fq_table('codebase_snapshots')} WHERE id = $1",
                uuid.UUID(snapshot_id),
            )
            stats = decode_jsonb(stats_row["stats"] if stats_row else None, {})
            stats["review_counts"] = {
                "unrouted": int(route_counts["unrouted_count"] or 0) if route_counts else 0,
                "memory": int(route_counts["memory_count"] or 0) if route_counts else 0,
                "research": int(route_counts["research_count"] or 0) if route_counts else 0,
                "dismissed": int(route_counts["dismissed_count"] or 0) if route_counts else 0,
            }
            async with conn.transaction():
                await conn.execute(
                    f"""
                    UPDATE {fq_table("codebase_snapshots")}
                    SET status = $2,
                        approved_at = NOW(),
                        stats = $3::jsonb,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    uuid.UUID(snapshot_id),
                    snapshot_status,
                    json.dumps(stats),
                )
                await conn.execute(
                    f"""
                    UPDATE {fq_table("codebases")}
                    SET approved_snapshot_id = $2, updated_at = NOW()
                    WHERE id = $1
                    """,
                    uuid.UUID(codebase_id),
                    uuid.UUID(snapshot_id),
                )

        return {
            "codebase_id": codebase_id,
            "snapshot_id": snapshot_id,
            "status": snapshot_status,
            "memory_ingest_mode": memory_ingest_mode,
            **hydration,
        }

    async def _handle_consolidation(self, task_dict: dict[str, Any]):
        """
        Handler for consolidation tasks.

        Consolidates new memories into mental models for a bank.

        Args:
            task_dict: Dict with 'bank_id'

        Raises:
            ValueError: If bank_id is missing
            Exception: Any exception from consolidation (propagates to execute_task for retry)
        """
        bank_id = task_dict.get("bank_id")
        if not bank_id:
            raise ValueError("bank_id is required for consolidation task")

        from atulya_api.models import RequestContext

        from .consolidation import run_consolidation_job

        # Restore tenant_id/api_key_id from task payload so downstream operations
        # (e.g., mental model refreshes) can attribute usage to the correct org.
        internal_context = RequestContext(
            internal=True,
            tenant_id=task_dict.get("_tenant_id"),
            api_key_id=task_dict.get("_api_key_id"),
        )
        result = await run_consolidation_job(
            memory_engine=self,
            bank_id=bank_id,
            request_context=internal_context,
        )

        logger.info(f"[CONSOLIDATION] bank={bank_id} completed: {result.get('memories_processed', 0)} processed")

        # Hybrid trigger: event-driven dream generation after meaningful consolidation updates.
        try:
            settings = normalize_dream_config(
                (await self._config_resolver.resolve_full_config(bank_id, internal_context)).dream
            )
            if settings.get("enabled") and settings.get("trigger_mode") in ("event", "hybrid"):
                meaningful_delta = (result.get("observations_created", 0) + result.get("observations_updated", 0)) > 0
                if meaningful_delta:
                    await self.submit_async_dream_generation(
                        bank_id=bank_id,
                        request_context=internal_context,
                        trigger_source="event",
                    )
        except Exception as e:
            logger.warning(f"Failed to queue dream_generation after consolidation for bank={bank_id}: {e}")
        return result

    async def _insert_dream_artifact(
        self,
        *,
        bank_id: str,
        run_type: str,
        trigger_source: str,
        html_blob: str,
        input_refs: list[dict[str, Any]],
        stats: dict[str, Any],
        quality_score: float,
        distilled_written: bool,
    ) -> str:
        pool = await self._get_pool()
        artifact_id = uuid.uuid4()
        async with acquire_with_retry(pool) as conn:
            await conn.execute(
                f"""
                INSERT INTO {fq_table("dream_artifacts")}
                    (id, bank_id, run_type, trigger_source, html_blob, input_refs, stats, quality_score, distilled_written)
                VALUES
                    ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)
                """,
                artifact_id,
                bank_id,
                run_type,
                trigger_source,
                html_blob,
                json.dumps(input_refs),
                json.dumps(stats),
                quality_score,
                distilled_written,
            )
        return str(artifact_id)

    async def _insert_dream_run_record(
        self,
        *,
        bank_id: str,
        run_type: str,
        trigger_source: str,
        status: str,
        summary: str | None,
        narrative_html: str | None,
        evidence_basis: DreamEvidenceBasis,
        signals: DreamSignals,
        predictions: list[DreamPrediction],
        growth_hypotheses: list[DreamGrowthHypothesis],
        promotion_proposals: list[DreamPromotionProposal],
        validation_outcomes: list[DreamValidationOutcome],
        confidence: DreamConfidenceModel,
        novelty_score: float,
        maturity_tier: str,
        quality_score: float,
        validation_rate: float,
        calibration_score: float,
        failure_reason: str | None,
        result_metadata: dict[str, Any],
        source_artifact_id: str | None = None,
        created_at: datetime | None = None,
    ) -> DreamRunRecord:
        created_ts = created_at or datetime.now(UTC)
        run_id = str(uuid.uuid4())
        stored_metadata = dict(result_metadata)
        stored_metadata["growth_hypotheses"] = [item.model_dump(mode="json") for item in growth_hypotheses]
        prediction_payloads: list[tuple[DreamPrediction, str]] = []
        for item in predictions:
            prediction_id = item.prediction_id or str(uuid.uuid4())
            prediction_payloads.append((item.model_copy(update={"prediction_id": prediction_id}), prediction_id))
        proposal_payloads: list[tuple[DreamPromotionProposal, str]] = []
        for item in promotion_proposals:
            proposal_id = item.proposal_id or str(uuid.uuid4())
            proposal_payloads.append((item.model_copy(update={"proposal_id": proposal_id}), proposal_id))
        outcome_payloads: list[tuple[DreamValidationOutcome, str]] = []
        for item in validation_outcomes:
            outcome_id = item.outcome_id or str(uuid.uuid4())
            outcome_payloads.append((item.model_copy(update={"outcome_id": outcome_id}), outcome_id))

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            await conn.execute(
                f"""
                INSERT INTO {fq_table("dream_runs")}
                    (id, bank_id, run_type, trigger_source, status, summary, narrative_html,
                     evidence_basis, signals, confidence, novelty_score, maturity_tier,
                     quality_score, validation_rate, calibration_score, result_metadata,
                     failure_reason, source_artifact_id, created_at, updated_at)
                VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10::jsonb,
                     $11, $12, $13, $14, $15, $16::jsonb, $17, $18, $19, $19)
                """,
                uuid.UUID(run_id),
                bank_id,
                run_type,
                trigger_source,
                status,
                summary,
                narrative_html,
                json.dumps(to_jsonable(evidence_basis)),
                json.dumps(to_jsonable(signals)),
                json.dumps(to_jsonable(confidence)),
                novelty_score,
                maturity_tier,
                quality_score,
                validation_rate,
                calibration_score,
                json.dumps(to_jsonable(stored_metadata) or {}),
                failure_reason,
                uuid.UUID(source_artifact_id) if source_artifact_id else None,
                created_ts,
            )
            for item, prediction_id in prediction_payloads:
                await conn.execute(
                    f"""
                    INSERT INTO {fq_table("dream_predictions")}
                        (id, run_id, bank_id, title, description, target_ref, target_kind, horizon,
                         confidence, success_criteria, expiration_window_days, status,
                         supporting_evidence_ids, validation_notes, created_at, updated_at)
                    VALUES
                        ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12, $13::jsonb, $14, $15, $15)
                    """,
                    uuid.UUID(prediction_id),
                    uuid.UUID(run_id),
                    bank_id,
                    item.title,
                    item.description,
                    item.target_ref,
                    item.target_kind,
                    item.horizon,
                    item.confidence,
                    json.dumps(item.success_criteria),
                    item.expiration_window_days,
                    item.status,
                    json.dumps(item.supporting_evidence_ids),
                    item.validation_notes,
                    created_ts,
                )
            for item, proposal_id in proposal_payloads:
                await conn.execute(
                    f"""
                    INSERT INTO {fq_table("dream_proposals")}
                        (id, run_id, bank_id, proposal_type, title, content, confidence, tags,
                         supporting_evidence_ids, review_status, rationale, created_at, updated_at)
                    VALUES
                        ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11, $12, $12)
                    """,
                    uuid.UUID(proposal_id),
                    uuid.UUID(run_id),
                    bank_id,
                    item.proposal_type,
                    item.title,
                    item.content,
                    item.confidence,
                    json.dumps(item.tags),
                    json.dumps(item.supporting_evidence_ids),
                    item.review_status,
                    item.rationale,
                    created_ts,
                )
            for item, outcome_id in outcome_payloads:
                await conn.execute(
                    f"""
                    INSERT INTO {fq_table("dream_prediction_outcomes")}
                        (id, prediction_id, bank_id, outcome_status, note, evidence_ids, created_at)
                    VALUES
                        ($1, $2, $3, $4, $5, $6::jsonb, $7)
                    """,
                    uuid.UUID(outcome_id),
                    uuid.UUID(item.prediction_id),
                    bank_id,
                    item.status,
                    item.note,
                    json.dumps(item.evidence_ids),
                    created_ts,
                )

        return DreamRunRecord(
            run_id=run_id,
            bank_id=bank_id,
            status=status,
            run_type=run_type,
            trigger_source=trigger_source,
            created_at=created_ts.isoformat(),
            updated_at=created_ts.isoformat(),
            narrative_html=narrative_html,
            summary=summary,
            evidence_basis=evidence_basis,
            signals=signals,
            predictions=[item for item, _ in prediction_payloads],
            growth_hypotheses=growth_hypotheses,
            promotion_proposals=[item for item, _ in proposal_payloads],
            validation_outcomes=[item for item, _ in outcome_payloads],
            confidence=confidence,
            novelty_score=novelty_score,
            maturity_tier=cast(Any, maturity_tier),
            failure_reason=failure_reason,
            quality_score=quality_score,
            source_artifact_id=source_artifact_id,
        )

    def _build_recency_distribution(self, timestamps: list[datetime | None]) -> dict[str, int]:
        buckets = {"last_24h": 0, "last_7d": 0, "last_30d": 0, "older": 0, "unknown": 0}
        now = datetime.now(UTC)
        for item in timestamps:
            if item is None:
                buckets["unknown"] += 1
                continue
            age_days = max((now - item).total_seconds() / 86400.0, 0.0)
            if age_days <= 1:
                buckets["last_24h"] += 1
            elif age_days <= 7:
                buckets["last_7d"] += 1
            elif age_days <= 30:
                buckets["last_30d"] += 1
            else:
                buckets["older"] += 1
        return buckets

    async def _recent_dream_history(
        self,
        *,
        bank_id: str,
        validation_lookback_days: int,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        await self._authenticate_tenant(request_context)
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            recent_rows = await conn.fetch(
                f"""
                SELECT summary
                FROM {fq_table("dream_runs")}
                WHERE bank_id = $1
                ORDER BY created_at DESC
                LIMIT 6
                """,
                bank_id,
            )
            prediction_row = await conn.fetchrow(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('pending', 'unresolved')) AS unresolved_count,
                    COUNT(*) FILTER (WHERE status = 'confirmed') AS confirmed_count,
                    COUNT(*) FILTER (WHERE status = 'contradicted') AS contradicted_count
                FROM {fq_table("dream_predictions")}
                WHERE bank_id = $1
                """,
                bank_id,
            )
            outcomes = await conn.fetch(
                f"""
                SELECT outcome_status
                FROM {fq_table("dream_prediction_outcomes")}
                WHERE bank_id = $1
                  AND created_at >= NOW() - ($2::text || ' days')::interval
                ORDER BY created_at DESC
                LIMIT 200
                """,
                bank_id,
                str(validation_lookback_days),
            )
        outcome_total = len(outcomes)
        confirmed_total = sum(1 for row in outcomes if row["outcome_status"] == "confirmed")
        contradicted_total = sum(1 for row in outcomes if row["outcome_status"] == "contradicted")
        validation_rate = confirmed_total / outcome_total if outcome_total else 0.0
        calibration_score = confirmed_total / max(confirmed_total + contradicted_total, 1) if outcome_total else 0.0
        return {
            "recent_summaries": [str(row["summary"] or "") for row in recent_rows if row["summary"]],
            "unresolved_prediction_backlog": int(prediction_row["unresolved_count"] or 0) if prediction_row else 0,
            "confirmed_predictions": int(prediction_row["confirmed_count"] or 0) if prediction_row else 0,
            "contradicted_predictions": int(prediction_row["contradicted_count"] or 0) if prediction_row else 0,
            "validation_rate": validation_rate,
            "calibration_score": calibration_score,
        }

    def _coerce_dream_output(self, payload: Any) -> DreamLLMOutput:
        if isinstance(payload, DreamLLMOutput):
            return payload
        if isinstance(payload, dict):
            return DreamLLMOutput.model_validate(payload)
        raise TypeError("Dream generation returned an unexpected payload type")

    def _apply_prediction_horizon_policy(
        self,
        predictions: list[DreamPrediction],
        *,
        prediction_horizon: str,
        unresolved_backlog: int,
        max_pending_predictions: int,
    ) -> list[DreamPrediction]:
        mode = str(prediction_horizon or "mixed").lower()
        if mode == "near":
            predictions = [item for item in predictions if item.horizon == "near_term"]
        elif mode == "far":
            predictions = [item for item in predictions if item.horizon in ("mid_term", "long_term")]

        available_slots = max(max_pending_predictions - unresolved_backlog, 0)
        if available_slots <= 0:
            return []
        return predictions[:available_slots]

    async def _list_dream_validation_outcomes_by_prediction(
        self,
        prediction_ids: list[str],
    ) -> dict[str, list[DreamValidationOutcome]]:
        if not prediction_ids:
            return {}
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, prediction_id, outcome_status, note, evidence_ids, created_at
                FROM {fq_table("dream_prediction_outcomes")}
                WHERE prediction_id = ANY($1::uuid[])
                ORDER BY created_at DESC
                """,
                [uuid.UUID(item) for item in prediction_ids],
            )
        grouped: dict[str, list[DreamValidationOutcome]] = {}
        for row in rows:
            prediction_id = str(row["prediction_id"])
            grouped.setdefault(prediction_id, []).append(
                DreamValidationOutcome(
                    outcome_id=str(row["id"]),
                    prediction_id=prediction_id,
                    status=row["outcome_status"],
                    note=row["note"],
                    evidence_ids=decode_jsonb(row["evidence_ids"], []),
                    created_at=row["created_at"].isoformat() if row["created_at"] else None,
                )
            )
        return grouped

    async def _handle_dream_generation(self, task_dict: dict[str, Any]) -> dict[str, Any]:
        bank_id = task_dict.get("bank_id")
        if not bank_id:
            raise ValueError("bank_id is required for dream_generation task")

        from atulya_api.models import RequestContext

        internal_context = RequestContext(
            internal=True,
            tenant_id=task_dict.get("_tenant_id"),
            api_key_id=task_dict.get("_api_key_id"),
        )
        resolved = await self._config_resolver.resolve_full_config(bank_id, internal_context)
        settings = normalize_dream_config(resolved.dream)
        if not settings.get("enabled"):
            return {"skipped": True, "reason": "dream_disabled"}

        cooldown_minutes = int(settings.get("cooldown_minutes", 60))
        trigger_source = str(task_dict.get("trigger_source", "event"))
        run_type = str(task_dict.get("run_type", "dream"))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            recent = await conn.fetchrow(
                f"""
                SELECT created_at
                FROM {fq_table("dream_runs")}
                WHERE bank_id = $1
                  AND trigger_source = $2
                  AND status IN ('success', 'low_signal', 'duplicate_low_novelty')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                bank_id,
                trigger_source,
            )
        if recent and recent["created_at"]:
            elapsed = datetime.now(UTC) - recent["created_at"]
            if elapsed < timedelta(minutes=cooldown_minutes):
                return {"skipped": True, "reason": "cooldown_active", "cooldown_minutes": cooldown_minutes}

        recall_query = "What patterns, likely next steps, and practical what-if insights are emerging?"
        recall_result = await self.recall_async(
            bank_id=bank_id,
            query=recall_query,
            max_tokens=int(settings["max_input_tokens"]),
            budget=Budget.LOW,
            fact_type=["world", "experience", "observation"],
            request_context=internal_context,
            _quiet=True,
        )
        top_k = int(settings["top_k"])
        top_results = recall_result.results[:top_k]
        min_recall_results = int(settings.get("min_recall_results", 2))
        input_refs: list[dict[str, Any]] = []
        recall_lines: list[str] = []
        recurring_entities: dict[str, int] = {}
        recurring_themes: dict[str, int] = {}
        timestamps: list[datetime | None] = []
        for r in top_results:
            fact_type = getattr(r, "fact_type", None) or getattr(r, "type", None) or "unknown"
            text = getattr(r, "text", None)
            if not isinstance(text, str):
                text = str(text or "")
            rid = getattr(r, "id", None)
            input_refs.append({"id": str(rid) if rid is not None else "", "type": str(fact_type)})
            recall_lines.append(f"- ({fact_type}) {text}")
            raw_timestamp = (
                getattr(r, "occurred_start", None) or getattr(r, "mentioned_at", None) or getattr(r, "created_at", None)
            )
            if isinstance(raw_timestamp, str):
                try:
                    raw_timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    raw_timestamp = None
            timestamps.append(raw_timestamp)
            for entity_name in list(getattr(r, "entities", []) or []):
                key = str(entity_name).strip()
                if key:
                    recurring_entities[key] = recurring_entities.get(key, 0) + 1
            for token in {tok for tok in text.lower().split() if len(tok) > 4}:
                recurring_themes[token] = recurring_themes.get(token, 0) + 1

        graph_intelligence = await self.get_graph_intelligence(
            bank_id=bank_id,
            limit=12,
            confidence_min=0.55,
            node_kind="all",
            window_days=90,
            request_context=internal_context,
        )
        graph_signals = [
            str(node.get("status_reason") or "")
            for node in graph_intelligence.get("nodes", [])[:4]
            if node.get("status_reason")
        ]
        contradictions = [
            str(event.get("summary") or "")
            for event in graph_intelligence.get("change_events", [])
            if event.get("change_type") == "contradiction"
        ][:3]
        history = await self._recent_dream_history(
            bank_id=bank_id,
            validation_lookback_days=int(settings.get("validation_lookback_days", 45)),
            request_context=internal_context,
        )
        maturity_tier = infer_maturity_tier(
            evidence_count=len(top_results),
            recurring_entities=sum(1 for count in recurring_entities.values() if count > 1),
            contradiction_count=len(contradictions),
            confirmed_predictions=int(history["confirmed_predictions"]),
        )
        evidence_basis = DreamEvidenceBasis(
            evidence_count=len(top_results),
            recall_memory_ids=[item["id"] for item in input_refs if item["id"]],
            recurring_entities=[
                name for name, _count in sorted(recurring_entities.items(), key=lambda item: (-item[1], item[0]))[:5]
            ],
            recurring_themes=[
                name
                for name, count in sorted(recurring_themes.items(), key=lambda item: (-item[1], item[0]))
                if count > 1
            ][:5],
            contradictions=contradictions,
            graph_signals=graph_signals,
            recency_distribution=self._build_recency_distribution(timestamps),
            unresolved_prediction_backlog=int(history["unresolved_prediction_backlog"]),
            maturity_reason=(
                "Sparse bank: dreams should emphasize uncertainty mapping."
                if maturity_tier == "sparse"
                else (
                    "Emerging bank: enough recurring evidence exists for near-term forecasts."
                    if maturity_tier == "emerging"
                    else "Mature bank: validated prediction history supports mixed-horizon foresight."
                )
            ),
        )
        source_block = "\n".join(recall_lines) if recall_lines else "- No strong recall signal yet."
        if len(top_results) < min_recall_results:
            summary = "The bank does not yet have enough stable evidence for a trustworthy foresight run."
            signals = DreamSignals(
                hypotheses=["The memory bank is still sparse, so uncertainty should be made explicit."],
                recommended_validations=[
                    "Capture 1-2 more concrete observations tied to the same entity or topic.",
                    "Re-run dreams after another consolidation or state-graph change.",
                ],
            )
            confidence = summarize_confidence(
                evidence_count=len(top_results),
                contradiction_count=len(contradictions),
                novelty_score=0.0,
                calibration_score=float(history["calibration_score"]),
                predictions=[],
                summary=summary,
            )
            quality_score = 0.22
            narrative_html = render_dream_narrative_html(
                bank_id=bank_id,
                run_type=run_type,
                summary=summary,
                maturity_tier=maturity_tier,
                hypotheses=signals.hypotheses,
                predictions=[],
                growth_hypotheses=[],
                risks=["Low evidence density can produce misleading conclusions."],
                opportunities=[],
                recommended_validations=signals.recommended_validations,
                quality_score=quality_score,
                max_bytes=int(settings.get("max_artifact_bytes", 24_000)),
            )
            artifact_id = await self._insert_dream_artifact(
                bank_id=bank_id,
                run_type=run_type,
                trigger_source=trigger_source,
                html_blob=narrative_html,
                input_refs=input_refs,
                stats={
                    "top_k_used": len(top_results),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "status": "low_signal",
                    "prompt_template_version": settings.get("prompt_template_version", "v3-evidence-foresight"),
                },
                quality_score=quality_score,
                distilled_written=False,
            )
            run = await self._insert_dream_run_record(
                bank_id=bank_id,
                run_type=run_type,
                trigger_source=trigger_source,
                status="low_signal",
                summary=summary,
                narrative_html=narrative_html,
                evidence_basis=evidence_basis,
                signals=signals,
                predictions=[],
                growth_hypotheses=[],
                promotion_proposals=[],
                validation_outcomes=[],
                confidence=confidence,
                novelty_score=0.0,
                maturity_tier=maturity_tier,
                quality_score=quality_score,
                validation_rate=float(history["validation_rate"]),
                calibration_score=float(history["calibration_score"]),
                failure_reason=None,
                result_metadata={"top_k_used": len(top_results), "status": "low_signal", "input_refs": input_refs},
                source_artifact_id=artifact_id,
            )
            return {
                "run_id": run.run_id,
                "artifact_id": artifact_id,
                "status": run.status,
                "quality_score": quality_score,
                "top_k_used": len(top_results),
            }

        system_prompt = (
            "You are the Atulya dream foresight engine.\n"
            "Produce structured, evidence-grounded foresight from the bank. Stay concrete, non-fictional, "
            "and tied to the supplied evidence. Never claim certainty where evidence is weak. "
            "If evidence is sparse, reflect that in the output instead of inventing detail."
        )
        worker_prompt = str(settings.get("worker_prompt") or "")
        value_focus = settings.get("value_focus", {"money": 1.0, "time": 1.0, "happiness": 1.0})
        tone = settings.get("language_tone", "plain-layman")
        dream_experience = str(settings.get("dream_experience", "hybrid"))
        layman_clause = (
            "Use very simple language a non-technical user can understand."
            if settings.get("enforce_layman", True)
            else ""
        )
        user_prompt = (
            f"{worker_prompt}\n\n"
            "Return structured foresight with predictions, growth hypotheses, risks, opportunities, "
            "validation steps, and proposal candidates. Predictions must be testable and evidence-grounded.\n\n"
            f"Value focus weights: money={value_focus.get('money', 1.0)}, "
            f"time={value_focus.get('time', 1.0)}, happiness={value_focus.get('happiness', 1.0)}.\n"
            f"Dream experience mode: {dream_experience}.\n"
            f"Tone: {tone}. {layman_clause}\n"
            f"Prediction horizon policy: {settings.get('prediction_horizon', 'mixed')}.\n"
            f"Promotion gate: {settings.get('promotion_gate', 'human_review')}.\n\n"
            f"Bank maturity: {maturity_tier}\n"
            f"Validation history: confirmation_rate={float(history['validation_rate']):.2f}, calibration_score={float(history['calibration_score']):.2f}\n"
            f"Unresolved prediction backlog: {int(history['unresolved_prediction_backlog'])}\n"
            f"Recurring entities: {', '.join(evidence_basis.recurring_entities) or 'none'}\n"
            f"Recurring themes: {', '.join(evidence_basis.recurring_themes) or 'none'}\n"
            f"Contradictions: {', '.join(evidence_basis.contradictions) or 'none'}\n"
            f"Graph signals: {', '.join(evidence_basis.graph_signals) or 'none'}\n"
            f"Recency distribution: {json.dumps(evidence_basis.recency_distribution)}\n\n"
            f"Evidence:\n{source_block}"
        )

        llm_output: DreamLLMOutput
        usage_in = 0
        usage_out = 0
        try:
            llm = self._reflect_llm_config.with_config(resolved)
            llm_result, usage = await llm.call(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                response_format=DreamLLMOutput,
                max_completion_tokens=int(settings["max_output_tokens"]),
                return_usage=True,
                scope="dream",
            )
            llm_output = self._coerce_dream_output(llm_result)
            usage_in = usage.input_tokens
            usage_out = usage.output_tokens
        except Exception as e:
            summary = "Dream generation failed before a trustworthy foresight run could be produced."
            signals = DreamSignals(
                risks=["The LLM call failed, so no structured dream should be promoted or trusted."],
                recommended_validations=["Resolve the underlying model/runtime issue and rerun the dream engine."],
            )
            confidence = summarize_confidence(
                evidence_count=len(top_results),
                contradiction_count=len(contradictions),
                novelty_score=0.0,
                calibration_score=float(history["calibration_score"]),
                predictions=[],
                summary=summary,
            )
            run = await self._insert_dream_run_record(
                bank_id=bank_id,
                run_type=run_type,
                trigger_source=trigger_source,
                status="failed_llm",
                summary=summary,
                narrative_html=None,
                evidence_basis=evidence_basis,
                signals=signals,
                predictions=[],
                growth_hypotheses=[],
                promotion_proposals=[],
                validation_outcomes=[],
                confidence=confidence,
                novelty_score=0.0,
                maturity_tier=maturity_tier,
                quality_score=0.0,
                validation_rate=float(history["validation_rate"]),
                calibration_score=float(history["calibration_score"]),
                failure_reason=str(e),
                result_metadata={
                    "top_k_used": len(top_results),
                    "input_refs": input_refs,
                    "llm_error": str(e)[:1000],
                    "prompt_template_version": settings.get("prompt_template_version", "v3-evidence-foresight"),
                },
                source_artifact_id=None,
            )
            return {"run_id": run.run_id, "status": run.status, "quality_score": 0.0, "top_k_used": len(top_results)}

        novelty_score = compute_novelty_score(llm_output.summary, history["recent_summaries"])
        predictions = [item.model_copy(update={"status": "pending"}) for item in llm_output.predicted_next_events]
        predictions = self._apply_prediction_horizon_policy(
            predictions,
            prediction_horizon=str(settings.get("prediction_horizon", "mixed")),
            unresolved_backlog=int(history["unresolved_prediction_backlog"]),
            max_pending_predictions=int(settings.get("max_pending_predictions", 24)),
        )
        signals = DreamSignals(
            hypotheses=llm_output.hypotheses,
            risks=llm_output.risks,
            opportunities=llm_output.opportunities,
            recommended_validations=llm_output.recommended_validations,
            candidate_state_changes=llm_output.predicted_state_changes,
        )
        if int(history["unresolved_prediction_backlog"]) >= int(settings.get("max_pending_predictions", 24)):
            signals.recommended_validations.append(
                "Resolve or review existing pending dream predictions before generating more."
            )
        confidence = summarize_confidence(
            evidence_count=len(top_results),
            contradiction_count=len(contradictions),
            novelty_score=novelty_score,
            calibration_score=float(history["calibration_score"]),
            predictions=predictions,
            summary=llm_output.summary,
        )
        quality_score = score_dream_quality(llm_output.narrative or llm_output.summary, top_k=top_k)
        quality_score = round(max(quality_score, confidence.overall), 3)
        quality_threshold = float(settings.get("quality_threshold", 0.65))
        status = "success"
        if quality_score < quality_threshold:
            status = "failed_validation"
        elif novelty_score < float(settings.get("novelty_threshold", 0.58)):
            status = "duplicate_low_novelty"
        promotion_proposals = llm_output.promotion_proposals
        if status == "failed_validation":
            promotion_proposals = []
            signals.recommended_validations.append(
                f"Raise the dream quality above {quality_threshold:.2f} before promoting any proposal."
            )
        narrative_html = render_dream_narrative_html(
            bank_id=bank_id,
            run_type=run_type,
            summary=llm_output.summary,
            maturity_tier=maturity_tier,
            hypotheses=llm_output.hypotheses,
            predictions=predictions,
            growth_hypotheses=llm_output.growth_hypotheses,
            risks=llm_output.risks,
            opportunities=llm_output.opportunities,
            recommended_validations=signals.recommended_validations,
            quality_score=quality_score,
            max_bytes=int(settings.get("max_artifact_bytes", 24_000)),
        )
        artifact_id = None
        if status != "failed_validation":
            artifact_id = await self._insert_dream_artifact(
                bank_id=bank_id,
                run_type=run_type,
                trigger_source=trigger_source,
                html_blob=narrative_html,
                input_refs=input_refs,
                stats={
                    "top_k_used": len(top_results),
                    "input_tokens": usage_in,
                    "output_tokens": usage_out,
                    "status": status,
                    "novelty_score": novelty_score,
                    "prompt_template_version": settings.get("prompt_template_version", "v3-evidence-foresight"),
                },
                quality_score=quality_score,
                distilled_written=False,
            )
        run = await self._insert_dream_run_record(
            bank_id=bank_id,
            run_type=run_type,
            trigger_source=trigger_source,
            status=status,
            summary=llm_output.summary,
            narrative_html=narrative_html,
            evidence_basis=evidence_basis,
            signals=signals,
            predictions=predictions,
            growth_hypotheses=llm_output.growth_hypotheses,
            promotion_proposals=promotion_proposals,
            validation_outcomes=[],
            confidence=confidence,
            novelty_score=novelty_score,
            maturity_tier=maturity_tier,
            quality_score=quality_score,
            validation_rate=float(history["validation_rate"]),
            calibration_score=float(history["calibration_score"]),
            failure_reason=None,
            result_metadata={
                "top_k_used": len(top_results),
                "input_refs": input_refs,
                "input_tokens": usage_in,
                "output_tokens": usage_out,
                "status": status,
                "prompt_template_version": settings.get("prompt_template_version", "v3-evidence-foresight"),
                "dream_experience": dream_experience,
                "quality_threshold": quality_threshold,
                "auto_write_posture": settings.get("auto_write_posture", "aggressive_proposals"),
                "promotion_gate": settings.get("promotion_gate", "human_review"),
            },
            source_artifact_id=artifact_id,
        )
        return {
            "run_id": run.run_id,
            "artifact_id": artifact_id,
            "status": run.status,
            "quality_score": quality_score,
            "top_k_used": len(top_results),
        }

    async def _handle_reflect(self, task_dict: dict[str, Any]) -> None:
        """Execute a queued reflect operation and persist the final response payload."""
        bank_id = task_dict.get("bank_id")
        query = task_dict.get("query")
        operation_id = task_dict.get("operation_id")

        if not bank_id or not query or not operation_id:
            raise ValueError("bank_id, query, and operation_id are required for reflect task")

        from atulya_api.models import RequestContext

        internal_context = RequestContext(
            internal=True,
            tenant_id=task_dict.get("_tenant_id"),
            api_key_id=task_dict.get("_api_key_id"),
        )

        await self._set_operation_stage(operation_id, "reflecting")

        budget_value = task_dict.get("budget")
        budget = Budget(budget_value) if budget_value else None
        include_facts = bool(task_dict.get("include_facts", False))
        include_tool_calls = bool(task_dict.get("include_tool_calls", False))
        include_tool_call_output = bool(task_dict.get("include_tool_call_output", True))

        reflect_result = await self.reflect_async(
            bank_id=bank_id,
            query=query,
            budget=budget,
            max_tokens=int(task_dict.get("max_tokens", 4096)),
            response_schema=task_dict.get("response_schema"),
            request_context=internal_context,
            tags=task_dict.get("tags"),
            tags_match=task_dict.get("tags_match", "any"),
        )

        await self._set_operation_stage(operation_id, "persisting_result")
        reflect_payload = serialize_reflect_response(
            reflect_result,
            include_facts=include_facts,
            include_tool_calls=include_tool_calls,
            include_tool_call_output=include_tool_call_output,
        )
        await self._mark_operation_completed(operation_id, result_payload=reflect_payload)

    async def _handle_refresh_mental_model(self, task_dict: dict[str, Any]):
        """
        Handler for refresh_mental_model tasks.

        Re-runs the source query through reflect and updates the mental model content.

        Args:
            task_dict: Dict with 'bank_id', 'mental_model_id', 'operation_id'

        Raises:
            ValueError: If required fields are missing
            Exception: Any exception from reflect/update (propagates to execute_task for retry)
        """
        bank_id = task_dict.get("bank_id")
        mental_model_id = task_dict.get("mental_model_id")

        if not bank_id or not mental_model_id:
            raise ValueError("bank_id and mental_model_id are required for refresh_mental_model task")

        logger.info(f"[REFRESH_MENTAL_MODEL_TASK] Starting for bank_id={bank_id}, mental_model_id={mental_model_id}")

        from atulya_api.models import RequestContext

        # Restore tenant_id/api_key_id from task payload so extensions can
        # attribute the mental_model_refresh operation to the correct org.
        internal_context = RequestContext(
            internal=True,
            tenant_id=task_dict.get("_tenant_id"),
            api_key_id=task_dict.get("_api_key_id"),
        )

        # Get the current mental model to get source_query
        mental_model = await self.get_mental_model(bank_id, mental_model_id, request_context=internal_context)
        if not mental_model:
            raise ValueError(f"Mental model {mental_model_id} not found in bank {bank_id}")

        source_query = mental_model["source_query"]

        # SECURITY: If the mental model has tags, pass them to reflect with "all_strict" matching
        # to ensure it can only access other mental models/memories with the SAME tags.
        # This prevents cross-tenant/cross-user information leakage by excluding untagged content.
        tags = mental_model.get("tags")
        tags_match = "all_strict" if tags else "any"

        # Run reflect to generate new content, excluding the mental model being refreshed
        reflect_result = await self.reflect_async(
            bank_id=bank_id,
            query=source_query,
            request_context=internal_context,
            tags=tags,
            tags_match=tags_match,
            exclude_mental_model_ids=[mental_model_id],
        )

        generated_content = reflect_result.text or "No content generated"

        # Build reflect_response payload to store
        # based_on contains MemoryFact objects for most types, but plain dicts for directives
        based_on_serialized: dict[str, list[dict[str, Any]]] = {}
        for fact_type, facts in reflect_result.based_on.items():
            serialized_facts = []
            for fact in facts:
                if isinstance(fact, dict):
                    # Plain dict (e.g., directives with id, name, content)
                    serialized_facts.append(
                        {
                            "id": str(fact["id"]),
                            "text": fact.get("text", fact.get("content", fact.get("name", ""))),
                            "type": fact_type,
                        }
                    )
                else:
                    # MemoryFact object with .id and .text attributes
                    serialized_facts.append(
                        {
                            "id": str(fact.id),
                            "text": fact.text,
                            "type": fact_type,
                        }
                    )
            based_on_serialized[fact_type] = serialized_facts

        reflect_response = {
            "text": reflect_result.text,
            "based_on": based_on_serialized,
        }

        # Update the mental model with the generated content and reflect_response
        await self.update_mental_model(
            bank_id=bank_id,
            mental_model_id=mental_model_id,
            content=generated_content,
            reflect_response=reflect_response,
            request_context=internal_context,
        )

        # Call post-operation hook if validator is configured
        if self._operation_validator:
            from atulya_api.extensions.operation_validator import MentalModelRefreshResult

            # Count facts and mental models from based_on
            facts_used = 0
            mental_models_used = 0
            if reflect_result.based_on:
                for fact_type, facts in reflect_result.based_on.items():
                    if facts:
                        if fact_type == "mental_models":
                            mental_models_used += len(facts)
                        else:
                            facts_used += len(facts)

            # Estimate tokens
            query_tokens = len(source_query) // 4 if source_query else 0
            output_tokens = len(generated_content) // 4 if generated_content else 0
            context_tokens = 0  # refresh doesn't use additional context

            result_ctx = MentalModelRefreshResult(
                bank_id=bank_id,
                mental_model_id=mental_model_id,
                request_context=internal_context,
                query_tokens=query_tokens,
                output_tokens=output_tokens,
                context_tokens=context_tokens,
                facts_used=facts_used,
                mental_models_used=mental_models_used,
                success=True,
            )
            try:
                await self._operation_validator.on_mental_model_refresh_complete(result_ctx)
            except Exception as hook_err:
                logger.warning(f"Post-mental-model-refresh hook error (non-fatal): {hook_err}")

        logger.info(f"[REFRESH_MENTAL_MODEL_TASK] Completed for bank_id={bank_id}, mental_model_id={mental_model_id}")

    async def _collect_sub_routine_inputs(
        self,
        bank_id: str,
        *,
        request_context: "RequestContext",
        include_full_copy: bool,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[datetime]]:
        """
        Collect reproducible inputs for sub_routine derivation.

        Query limits match the runtime's hardware tier budget so that higher
        tiers can actually utilise their full capacity.

        Data source:
        - mental_models table (high-value synthesized knowledge)
        - memory_units table (optional full copy and activity timestamps)
        """
        model_budget, copy_budget = self._brain_runtime._budget_for_tier()
        mental_models = await self.list_mental_models(
            bank_id=bank_id, limit=model_budget, request_context=request_context
        )
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, text, fact_type, mentioned_at, created_at
                FROM {fq_table("memory_units")}
                WHERE bank_id = $1
                ORDER BY COALESCE(mentioned_at, created_at) DESC
                LIMIT $2
                """,
                bank_id,
                copy_budget,
            )

        full_copy: list[dict[str, Any]] = []
        events: list[datetime] = []
        for row in rows:
            ts = row["mentioned_at"] or row["created_at"]
            if ts:
                events.append(ts if isinstance(ts, datetime) else datetime.now(UTC))
            if include_full_copy:
                full_copy.append(
                    {
                        "id": str(row["id"]),
                        "text": row["text"],
                        "type": row["fact_type"],
                        "mentioned_at": ts.isoformat() if ts else None,
                    }
                )
        return mental_models, full_copy, events

    async def _handle_sub_routine(self, task_dict: dict[str, Any]):
        """Handler for sub_routine tasks."""
        bank_id = task_dict.get("bank_id")
        operation_id = task_dict.get("operation_id")
        if not bank_id:
            raise ValueError("bank_id is required for sub_routine task")
        mode = task_dict.get("mode", "incremental")
        include_full_copy = mode == "full_copy"
        if not self._brain_runtime.enabled:
            logger.info("[SUB_ROUTINE] brain runtime disabled; skipping task for bank=%s", bank_id)
            if operation_id:
                await self._set_operation_stage(operation_id, "fallback", {"fallback_reason": "runtime_disabled"})
            return
        if operation_id:
            await self._set_operation_stage(operation_id, "building")

        from atulya_api.models import RequestContext

        internal_context = RequestContext(
            internal=True,
            tenant_id=task_dict.get("_tenant_id"),
            api_key_id=task_dict.get("_api_key_id"),
        )
        mental_models, full_copy, events = await self._collect_sub_routine_inputs(
            bank_id=bank_id,
            request_context=internal_context,
            include_full_copy=include_full_copy,
        )
        result = await self._brain_runtime.build_or_refresh(
            bank_id=bank_id,
            mental_models=mental_models,
            full_copy=full_copy,
            events=events,
            mode=mode,
        )
        if operation_id:
            await self._set_operation_stage(
                operation_id,
                "predicting",
                {"mental_model_count": result.get("mental_model_count", 0)},
            )
        prediction = await self._brain_runtime.predict_activity_time(
            bank_id=bank_id,
            horizon_hours=int(task_dict.get("horizon_hours", 24)),
        )
        if operation_id:
            await self._set_operation_stage(
                operation_id,
                "completed",
                {
                    "prediction_points": len(prediction.get("predictions", [])),
                    "native_library_loaded": result.get("native_library_loaded", False),
                },
            )
        logger.info(
            "[SUB_ROUTINE] bank=%s mode=%s models=%s full_copy=%s",
            bank_id,
            mode,
            result.get("mental_model_count"),
            result.get("full_copy_count"),
        )

    async def _handle_brain_learn(self, task_dict: dict[str, Any]):
        """Handler for brain_learn tasks — brain-to-brain knowledge transfer."""
        bank_id = task_dict.get("bank_id")
        operation_id = task_dict.get("operation_id")
        if not bank_id:
            raise ValueError("bank_id is required for brain_learn task")

        remote_endpoint = task_dict.get("remote_endpoint", "")
        remote_bank_id = task_dict.get("remote_bank_id", "")
        remote_api_key = task_dict.get("remote_api_key", "")
        mode = task_dict.get("mode", "incremental")
        learning_type = task_dict.get("learning_type", "auto")

        if not remote_endpoint or not remote_bank_id:
            raise ValueError("remote_endpoint and remote_bank_id are required for brain_learn")

        if not self._brain_runtime.enabled:
            logger.info("[BRAIN_LEARN] brain runtime disabled; skipping for bank=%s", bank_id)
            if operation_id:
                await self._set_operation_stage(operation_id, "fallback", {"fallback_reason": "runtime_disabled"})
            return

        if operation_id:
            await self._set_operation_stage(
                operation_id,
                "fetching",
                {"remote_endpoint": remote_endpoint, "learning_type": learning_type},
            )

        from atulya_api.models import RequestContext

        internal_context = RequestContext(
            internal=True,
            tenant_id=task_dict.get("_tenant_id"),
            api_key_id=task_dict.get("_api_key_id"),
        )
        mental_models, full_copy, events = await self._collect_sub_routine_inputs(
            bank_id=bank_id,
            request_context=internal_context,
            include_full_copy=(mode == "full_copy"),
        )

        if operation_id:
            await self._set_operation_stage(
                operation_id,
                "learning",
                {
                    "local_models": len(mental_models),
                    "local_events": len(events),
                },
            )

        result = await self._brain_runtime.learn_from_remote(
            bank_id=bank_id,
            remote_endpoint=remote_endpoint,
            remote_bank_id=remote_bank_id,
            remote_api_key=remote_api_key,
            local_mental_models=mental_models,
            local_full_copy=full_copy,
            local_events=events,
            learning_type=learning_type,
            mode=mode,
        )

        if operation_id:
            await self._set_operation_stage(
                operation_id,
                "storing",
                {
                    "merged_model_count": result.get("merged_model_count", 0),
                    "remote_model_count": result.get("remote_model_count", 0),
                    "remote_memory_count": result.get("remote_memory_count", 0),
                    "learning_type_effective": result.get("learning_type_effective", learning_type),
                },
            )

        # Direct-store remote knowledge — skip LLM pipeline since remote
        # already did fact extraction, entity linking, and temporal parsing.
        # We only generate local embeddings (cheap) for vector search.
        remote_memories: list[dict[str, Any]] = result.get("_remote_memories", [])
        remote_mental_models: list[dict[str, Any]] = result.get("_remote_mental_models", [])
        stored_memories = 0
        stored_models = 0
        skipped_duplicates = 0
        source_label = f"brain-learn:{remote_endpoint}/{remote_bank_id}"
        source_tag = f"source:{remote_bank_id}"

        pool = await self._get_pool()

        # Collect existing texts to deduplicate against repeated learn runs
        existing_texts: set[str] = set()
        try:
            async with acquire_with_retry(pool) as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT text FROM {fq_table("memory_units")}
                    WHERE bank_id = $1 AND tags @> $2::varchar[]
                    """,
                    bank_id,
                    ["brain-learn", source_tag],
                )
                existing_texts = {r["text"] for r in rows}
        except Exception as exc:
            logger.warning("[BRAIN_LEARN] Could not load existing texts for dedup: %s", exc)

        if remote_memories:
            valid_memories: list[dict[str, Any]] = []
            for mem in remote_memories:
                text = mem.get("text", "")
                if not text or text in existing_texts:
                    if text in existing_texts:
                        skipped_duplicates += 1
                    continue
                valid_memories.append(mem)

            if valid_memories:
                EMBED_BATCH = 64
                all_embeddings: list[list[float]] = []
                for ei in range(0, len(valid_memories), EMBED_BATCH):
                    chunk_texts = [m.get("text", "") for m in valid_memories[ei : ei + EMBED_BATCH]]
                    embs = await embedding_utils.generate_embeddings_batch(self.embeddings, chunk_texts)
                    all_embeddings.extend(embs)

                DB_BATCH = 50
                for i in range(0, len(valid_memories), DB_BATCH):
                    batch_mems = valid_memories[i : i + DB_BATCH]
                    batch_embs = all_embeddings[i : i + DB_BATCH]

                    b_texts: list[str] = []
                    b_embeddings: list[str] = []
                    b_event_dates: list[datetime] = []
                    b_mentioned_ats: list[datetime | None] = []
                    b_contexts: list[str] = []
                    b_fact_types: list[str] = []
                    b_tags: list[str] = []

                    for mem, emb in zip(batch_mems, batch_embs):
                        text = mem.get("text", "")
                        b_texts.append(text)
                        b_embeddings.append(str(emb))
                        fact_type = mem.get("fact_type", "world")
                        b_fact_types.append(fact_type)
                        context = mem.get("context", "")
                        b_contexts.append(context if context else f"[learned from {source_label}]")
                        tags = mem.get("tags", [])
                        if "brain-learn" not in tags:
                            tags = ["brain-learn", source_tag] + tags
                        b_tags.append(json.dumps(tags))

                        mentioned_at_raw = mem.get("mentioned_at") or mem.get("date")
                        mentioned_at = None
                        if mentioned_at_raw:
                            try:
                                mentioned_at = (
                                    datetime.fromisoformat(mentioned_at_raw.replace("Z", "+00:00"))
                                    if isinstance(mentioned_at_raw, str)
                                    else mentioned_at_raw
                                )
                            except (ValueError, TypeError):
                                pass
                        b_mentioned_ats.append(mentioned_at)
                        b_event_dates.append(mentioned_at or datetime.now(UTC))

                    try:
                        async with acquire_with_retry(pool) as conn:
                            rows = await conn.fetch(
                                f"""
                                WITH input_data AS (
                                    SELECT * FROM unnest(
                                        $2::text[], $3::vector[], $4::timestamptz[],
                                        $5::timestamptz[], $6::text[], $7::text[], $8::jsonb[]
                                    ) AS t(text, embedding, event_date,
                                           mentioned_at, context, fact_type, tags_json)
                                )
                                INSERT INTO {fq_table("memory_units")}
                                (bank_id, text, embedding, event_date, mentioned_at,
                                 context, fact_type, tags)
                                SELECT
                                    $1, text, embedding, event_date, mentioned_at,
                                    context, fact_type,
                                    COALESCE(
                                        (SELECT array_agg(elem) FROM jsonb_array_elements_text(tags_json) AS elem),
                                        '{{}}'::varchar[]
                                    )
                                FROM input_data
                                RETURNING id
                                """,
                                bank_id,
                                b_texts,
                                b_embeddings,
                                b_event_dates,
                                b_mentioned_ats,
                                b_contexts,
                                b_fact_types,
                                b_tags,
                            )
                            stored_memories += len(rows)
                    except Exception as exc:
                        logger.warning(
                            "[BRAIN_LEARN] Failed to store memory batch %d-%d: %s",
                            i,
                            i + len(batch_mems),
                            exc,
                        )

        if remote_mental_models:
            existing_model_names: set[str] = set()
            try:
                async with acquire_with_retry(pool) as conn:
                    rows = await conn.fetch(
                        f"""
                        SELECT name FROM {fq_table("mental_models")}
                        WHERE bank_id = $1 AND tags @> $2::varchar[]
                        """,
                        bank_id,
                        ["brain-learn", source_tag],
                    )
                    existing_model_names = {r["name"] for r in rows}
            except Exception as exc:
                logger.warning("[BRAIN_LEARN] Could not load existing model names for dedup: %s", exc)

            for model in remote_mental_models:
                name = model.get("name") or model.get("title", "")
                display_name = f"{name} [learned]" if name else f"Learned from {remote_bank_id}"
                if display_name in existing_model_names:
                    skipped_duplicates += 1
                    continue
                content = model.get("content") or model.get("text", "")
                if not content:
                    continue
                source_query = model.get("source_query", "")
                tags = model.get("tags", [])
                if "brain-learn" not in tags:
                    tags = ["brain-learn", source_tag] + tags
                try:
                    await self.create_mental_model(
                        bank_id=bank_id,
                        name=display_name,
                        source_query=source_query or f"Distilled from {source_label}",
                        content=content,
                        tags=tags,
                        request_context=internal_context,
                    )
                    stored_models += 1
                except Exception as exc:
                    logger.warning("[BRAIN_LEARN] Failed to store mental model '%s': %s", name, exc)

        consolidation_submission: dict[str, Any] | None = None
        if stored_memories > 0:
            try:
                # Direct inserts bypass retain pipeline hooks, so queue consolidation explicitly.
                consolidation_submission = await self.submit_async_consolidation(
                    bank_id=bank_id,
                    request_context=internal_context,
                )
            except Exception as exc:
                logger.warning("[BRAIN_LEARN] Failed to queue consolidation after learn: %s", exc)

        if operation_id:
            await self._set_operation_stage(
                operation_id,
                "completed",
                {
                    "merged_model_count": result.get("merged_model_count", 0),
                    "remote_model_count": result.get("remote_model_count", 0),
                    "remote_memory_count": result.get("remote_memory_count", 0),
                    "total_events": result.get("total_events", 0),
                    "remote_brain_used": result.get("remote_brain_used", False),
                    "learning_type_requested": learning_type,
                    "learning_type_effective": result.get("learning_type_effective", learning_type),
                    "remote_capabilities": result.get("remote_capabilities", {}),
                    "stored_memories": stored_memories,
                    "stored_models": stored_models,
                    "skipped_duplicates": skipped_duplicates,
                    "consolidation_queued": consolidation_submission is not None,
                    "consolidation_operation_id": (
                        consolidation_submission.get("operation_id") if consolidation_submission else None
                    ),
                    "consolidation_deduplicated": (
                        consolidation_submission.get("deduplicated", False) if consolidation_submission else False
                    ),
                },
            )

        logger.info(
            "[BRAIN_LEARN] bank=%s remote=%s stored_memories=%d stored_models=%d "
            "skipped_dupes=%d consolidation_queued=%s events=%s",
            bank_id,
            remote_endpoint,
            stored_memories,
            stored_models,
            skipped_duplicates,
            consolidation_submission is not None,
            result.get("total_events"),
        )

    async def execute_task(self, task_dict: dict[str, Any]):
        """
        Execute a task by routing it to the appropriate handler.

        This method is called by the task backend to execute tasks.
        It receives a plain dict that can be serialized and sent over the network.

        Args:
            task_dict: Task dictionary with 'type' key and other payload data
                      Example: {'type': 'batch_retain', 'bank_id': '...', 'contents': [...]}
        """
        task_type = task_dict.get("type")
        operation_id = task_dict.get("operation_id")

        # Set schema context for multi-tenant task execution
        schema = task_dict.pop("_schema", None)
        if schema:
            _current_schema.set(schema)

        # Check if operation was cancelled (only for tasks with operation_id)
        if operation_id:
            try:
                pool = await self._get_pool()
                async with acquire_with_retry(pool) as conn:
                    result = await conn.fetchrow(
                        f"SELECT operation_id FROM {fq_table('async_operations')} WHERE operation_id = $1",
                        uuid.UUID(operation_id),
                    )
                    if not result:
                        # Operation was cancelled, skip processing
                        logger.info(f"Skipping cancelled operation: {operation_id}")
                        return
            except Exception as e:
                logger.error(f"Failed to check operation status {operation_id}: {e}")
                # Continue with processing if we can't check status

        consolidation_result: dict | None = None
        task_result_payload: dict[str, Any] | None = None
        try:
            if task_type == "batch_retain":
                await self._handle_batch_retain(task_dict)
            elif task_type == "file_convert_retain":
                await self._handle_file_convert_retain(task_dict)
            elif task_type == "codebase_import_zip":
                task_result_payload = await self._handle_codebase_import_zip(task_dict)
            elif task_type == "codebase_import_github":
                task_result_payload = await self._handle_codebase_import_github(task_dict)
            elif task_type == "codebase_approve":
                task_result_payload = await self._handle_codebase_approve(task_dict)
            elif task_type == "consolidation":
                consolidation_result = await self._handle_consolidation(task_dict)
            elif task_type == "reflect":
                await self._handle_reflect(task_dict)
            elif task_type == "refresh_mental_model":
                await self._handle_refresh_mental_model(task_dict)
            elif task_type == "sub_routine":
                await self._handle_sub_routine(task_dict)
            elif task_type == "brain_learn":
                await self._handle_brain_learn(task_dict)
            elif task_type == "dream_generation":
                await self._handle_dream_generation(task_dict)
            elif task_type == "webhook_delivery":
                await self._handle_webhook_delivery(task_dict)
            else:
                logger.error(f"Unknown task type: {task_type}")
                # Don't retry unknown task types
                if operation_id:
                    await self._delete_operation_record(operation_id)
                return

            # Task succeeded - mark operation as completed
            # file_convert_retain marks itself as completed in a transaction, skip double-marking
            if operation_id and task_type not in ("file_convert_retain", "reflect"):
                if task_type == "consolidation":
                    # Atomically mark completed AND queue webhook delivery in one transaction
                    await self._mark_operation_completed_and_fire_webhook(
                        operation_id=operation_id,
                        bank_id=task_dict.get("bank_id", ""),
                        status="completed",
                        result=consolidation_result,
                        schema=schema,
                    )
                else:
                    await self._mark_operation_completed(operation_id, result_payload=task_result_payload)

        except RetryTaskAt:
            # Task-owned retry: let the poller handle scheduling
            raise
        except Exception as e:
            logger.error(f"Task execution failed: {task_type}, error: {e}")
            import traceback

            error_traceback = traceback.format_exc()
            traceback.print_exc()
            if task_type in ("sub_routine", "brain_learn", "dream_generation") and operation_id:
                await self._set_operation_stage(
                    operation_id,
                    "fallback",
                    {"fallback_reason": str(e)[:500]},
                )

            if task_type == "file_convert_retain":
                # Non-retryable: mark as failed immediately.
                # Conversion failures won't improve on retry (missing OCR, corrupted file, etc.)
                logger.error(f"Not retrying task {task_type} (non-retryable), marking as failed")
                if operation_id:
                    await self._mark_operation_failed(operation_id, str(e), error_traceback)
            else:
                if task_type == "consolidation" and operation_id:
                    # Fire failure webhook (non-transactional — operation not yet marked failed;
                    # poller will mark it failed after this raise)
                    await self._fire_consolidation_webhook(
                        bank_id=task_dict.get("bank_id", ""),
                        operation_id=operation_id,
                        status="failed",
                        result=None,
                        error_message=str(e),
                        schema=schema,
                    )
                elif task_type in ("codebase_import_zip", "codebase_import_github"):
                    retry_count = task_dict.get("_retry_count", 0)
                    if retry_count >= 3:
                        snapshot_id = task_dict.get("snapshot_id")
                        if snapshot_id:
                            await self._mark_codebase_snapshot_failed(snapshot_id, str(e))
                # Retryable: use RetryTaskAt if under the retry limit, else re-raise (poller marks failed)
                retry_count = task_dict.get("_retry_count", 0)
                if retry_count < 3:
                    raise RetryTaskAt(retry_at=datetime.now(UTC) + timedelta(seconds=60), message=str(e))
                raise

    async def _fire_consolidation_webhook(
        self,
        bank_id: str,
        operation_id: str,
        status: str,
        result: dict | None,
        error_message: str | None = None,
        schema: str | None = None,
    ) -> None:
        """Fire a consolidation webhook event. Non-fatal - logs errors but does not raise."""
        if not self._webhook_manager:
            return
        try:
            from datetime import datetime, timezone

            from ..webhooks.models import ConsolidationEventData, WebhookEvent, WebhookEventType

            data = ConsolidationEventData(
                observations_created=result.get("observations_created") if result else None,
                observations_updated=result.get("observations_updated") if result else None,
                observations_deleted=result.get("observations_deleted") if result else None,
                error_message=error_message,
            )
            event = WebhookEvent(
                event=WebhookEventType.CONSOLIDATION_COMPLETED,
                bank_id=bank_id,
                operation_id=operation_id,
                status=status,
                timestamp=datetime.now(timezone.utc),
                data=data,
            )
            await self._webhook_manager.fire_event(event, schema=schema)
        except Exception as e:
            logger.error(f"Failed to fire consolidation webhook for operation {operation_id}: {e}")

    def _build_retain_outbox_callback(
        self,
        bank_id: str,
        contents: list[dict],
        operation_id: str | None,
        schema: str | None = None,
    ) -> "Callable[[asyncpg.Connection], Awaitable[None]] | None":
        """Build a transactional outbox callback for retain.completed webhook events.

        Returns a coroutine function that queues one webhook delivery row per content
        item using the provided connection (inside the retain transaction). Returns None
        if no webhook manager is configured.
        """
        webhook_manager = getattr(self, "_webhook_manager", None)
        if not webhook_manager:
            return None

        from ..webhooks.models import RetainEventData, WebhookEvent, WebhookEventType

        now = datetime.now(UTC)
        op_id = operation_id or uuid.uuid4().hex
        events = []
        for content in contents:
            doc_id = content.get("document_id")
            tags = content.get("tags")
            data = RetainEventData(
                document_id=doc_id,
                tags=tags if isinstance(tags, list) else None,
            )
            events.append(
                WebhookEvent(
                    event=WebhookEventType.RETAIN_COMPLETED,
                    bank_id=bank_id,
                    operation_id=op_id,
                    status="completed",
                    timestamp=now,
                    data=data,
                )
            )

        async def _callback(conn: asyncpg.Connection) -> None:
            for event in events:
                await webhook_manager.fire_event_with_conn(event, conn, schema=schema)

        return _callback

    async def _update_webhook_delivery_metadata(
        self, operation_id: str, status_code: int | None, response_body: str | None
    ) -> None:
        """Persist last HTTP attempt info into async_operations.result_metadata."""
        try:
            pool = await self._get_pool()
            meta = json.dumps(
                {
                    "last_status_code": status_code,
                    "last_response_body": (response_body or "")[:2048],
                    "last_attempt_at": datetime.now(UTC).isoformat(),
                }
            )
            async with acquire_with_retry(pool) as conn:
                await conn.execute(
                    f"UPDATE {fq_table('async_operations')} SET result_metadata = $2::jsonb, updated_at = now() WHERE operation_id = $1",
                    uuid.UUID(operation_id),
                    meta,
                )
        except Exception as meta_err:
            logger.debug(f"Failed to update webhook delivery metadata: {meta_err}")

    async def _set_operation_stage(self, operation_id: str, stage: str, extras: dict[str, Any] | None = None) -> None:
        """Patch operation metadata with stage transitions."""
        try:
            pool = await self._get_pool()
            async with acquire_with_retry(pool) as conn:
                row = await conn.fetchrow(
                    f"SELECT result_metadata FROM {fq_table('async_operations')} WHERE operation_id = $1",
                    uuid.UUID(operation_id),
                )
                current_meta: dict[str, Any] = {}
                if row and row["result_metadata"]:
                    raw_meta = row["result_metadata"]
                    current_meta = json.loads(raw_meta) if isinstance(raw_meta, str) else dict(raw_meta)
                current_meta["operation_stage"] = stage
                current_meta["stage_updated_at"] = datetime.now(UTC).isoformat()
                if extras:
                    current_meta.update(extras)
                await conn.execute(
                    f"UPDATE {fq_table('async_operations')} SET result_metadata = $2::jsonb, updated_at = NOW() WHERE operation_id = $1",
                    uuid.UUID(operation_id),
                    json.dumps(current_meta),
                )
        except Exception as exc:
            logger.debug("Failed to set operation stage (%s -> %s): %s", operation_id, stage, exc)

    async def _handle_webhook_delivery(self, task_dict: dict[str, Any]) -> None:
        """Deliver a webhook event via HTTP.

        Raises RetryTaskAt to schedule a retry on failure (up to MAX_ATTEMPTS).
        Raises the original exception when retries are exhausted (poller marks failed).
        Response status code and body are stored in result_metadata for debugging.
        """
        from ..webhooks.manager import MAX_ATTEMPTS, RETRY_DELAYS
        from ..webhooks.models import WebhookHttpConfig

        url = task_dict["url"]
        secret = task_dict.get("secret")
        event_type = task_dict["event_type"]
        raw_payload = task_dict["payload"]
        retry_count = task_dict.get("_retry_count", 0)
        operation_id: str | None = task_dict.get("_operation_id")
        http_config = WebhookHttpConfig.model_validate(task_dict.get("http_config") or {})

        if isinstance(raw_payload, dict):
            payload_bytes = json.dumps(raw_payload).encode()
        else:
            payload_bytes = str(raw_payload).encode()

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Atulya-Event": event_type,
            **http_config.headers,
        }
        if secret and self._webhook_manager:
            headers["X-Atulya-Signature"] = self._webhook_manager._sign_payload(secret, payload_bytes)

        if self._http_client is None:
            raise RuntimeError("HTTP client not initialized")

        response = None
        try:
            request_kwargs: dict[str, Any] = {
                "headers": headers,
                "params": http_config.params if http_config.params else None,
                "timeout": http_config.timeout_seconds,
            }
            if http_config.method.upper() == "GET":
                response = await self._http_client.get(url, **request_kwargs)
            else:
                response = await self._http_client.post(url, content=payload_bytes, **request_kwargs)
            response.raise_for_status()
            if operation_id:
                await self._update_webhook_delivery_metadata(operation_id, response.status_code, response.text)
        except Exception as e:
            status_code = response.status_code if response is not None else None
            response_body = response.text if response is not None else None
            if operation_id:
                await self._update_webhook_delivery_metadata(operation_id, status_code, response_body)
            if retry_count >= MAX_ATTEMPTS - 1:
                logger.error(
                    f"webhook_delivery permanently_failed url={url} attempts={retry_count + 1} "
                    f"status_code={status_code} error={e}"
                )
                raise
            delay = RETRY_DELAYS[retry_count] if retry_count < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
            retry_at = datetime.now(UTC) + timedelta(seconds=delay)
            logger.warning(
                f"webhook_delivery failed url={url} attempt={retry_count + 1}/{MAX_ATTEMPTS} "
                f"status_code={status_code} retry_in={delay}s error={e}"
            )
            raise RetryTaskAt(retry_at=retry_at, message=str(e))

    async def _delete_operation_record(self, operation_id: str):
        """Helper to delete an operation record from the database."""
        try:
            pool = await self._get_pool()
            async with acquire_with_retry(pool) as conn:
                await conn.execute(
                    f"DELETE FROM {fq_table('async_operations')} WHERE operation_id = $1", uuid.UUID(operation_id)
                )
        except Exception as e:
            logger.error(f"Failed to delete async operation record {operation_id}: {e}")

    async def _mark_operation_failed(self, operation_id: str, error_message: str, error_traceback: str):
        """Helper to mark an operation as failed in the database.

        Also checks if this is a child operation and updates the parent if all siblings are done.
        Uses a single transaction to avoid race conditions when multiple children fail simultaneously.
        """
        try:
            pool = await self._get_pool()
            # Truncate error message to avoid extremely long strings
            full_error = f"{error_message}\n\nTraceback:\n{error_traceback}"
            truncated_error = full_error[:5000] if len(full_error) > 5000 else full_error

            async with acquire_with_retry(pool) as conn:
                async with conn.transaction():
                    # Mark this operation as failed
                    await conn.execute(
                        f"""
                        UPDATE {fq_table("async_operations")}
                        SET status = 'failed', error_message = $2, updated_at = NOW()
                        WHERE operation_id = $1
                        """,
                        uuid.UUID(operation_id),
                        truncated_error,
                    )
                    logger.info(f"Marked async operation as failed: {operation_id}")

                    # Check if this is a child operation and update parent if all siblings are done
                    # This happens in the same transaction after the child status is updated
                    await self._maybe_update_parent_operation(operation_id, conn)
        except Exception as e:
            logger.error(f"Failed to mark operation as failed {operation_id}: {e}")

    async def _mark_operation_completed(self, operation_id: str, result_payload: dict[str, Any] | None = None) -> None:
        """Helper to mark an operation as completed in the database.

        Also checks if this is a child operation and updates the parent if all siblings are done.
        Uses a single transaction to avoid race conditions when multiple children complete simultaneously.
        """
        try:
            pool = await self._get_pool()
            async with acquire_with_retry(pool) as conn:
                async with conn.transaction():
                    # Mark this operation as completed
                    if result_payload is None:
                        await conn.execute(
                            f"""
                            UPDATE {fq_table("async_operations")}
                            SET status = 'completed', updated_at = NOW(), completed_at = NOW()
                            WHERE operation_id = $1
                            """,
                            uuid.UUID(operation_id),
                        )
                    else:
                        await conn.execute(
                            f"""
                            UPDATE {fq_table("async_operations")}
                            SET status = 'completed',
                                updated_at = NOW(),
                                completed_at = NOW(),
                                result_payload = $2::jsonb
                            WHERE operation_id = $1
                            """,
                            uuid.UUID(operation_id),
                            json.dumps(result_payload),
                        )
                    logger.info(f"Marked async operation as completed: {operation_id}")

                    # Check if this is a child operation and update parent if all siblings are done
                    # This happens in the same transaction after the child status is updated
                    await self._maybe_update_parent_operation(operation_id, conn)
        except Exception as e:
            logger.error(f"Failed to mark operation as completed {operation_id}: {e}")

    async def _mark_operation_completed_and_fire_webhook(
        self,
        operation_id: str,
        bank_id: str,
        status: str,
        result: dict | None,
        schema: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Mark an operation as completed and queue webhook deliveries in a single transaction.

        Uses the transactional outbox pattern: the webhook delivery row is inserted in the
        same database transaction as the status update. This guarantees at-least-once delivery
        even if the process crashes immediately after committing.
        """
        from ..webhooks.models import ConsolidationEventData, WebhookEvent, WebhookEventType

        try:
            pool = await self._get_pool()
            async with acquire_with_retry(pool) as conn:
                async with conn.transaction():
                    await conn.execute(
                        f"""
                        UPDATE {fq_table("async_operations")}
                        SET status = 'completed', updated_at = NOW(), completed_at = NOW()
                        WHERE operation_id = $1
                        """,
                        uuid.UUID(operation_id),
                    )
                    logger.info(f"Marked async operation as completed: {operation_id}")
                    await self._maybe_update_parent_operation(operation_id, conn)

                    # Queue webhook deliveries inside the same transaction
                    if self._webhook_manager:
                        data = ConsolidationEventData(
                            observations_created=result.get("observations_created") if result else None,
                            observations_updated=result.get("observations_updated") if result else None,
                            observations_deleted=result.get("observations_deleted") if result else None,
                            error_message=error_message,
                        )
                        event = WebhookEvent(
                            event=WebhookEventType.CONSOLIDATION_COMPLETED,
                            bank_id=bank_id,
                            operation_id=operation_id,
                            status=status,
                            timestamp=datetime.now(UTC),
                            data=data,
                        )
                        await self._webhook_manager.fire_event_with_conn(event, conn, schema=schema)
        except Exception as e:
            logger.error(f"Failed to mark operation completed and fire webhook {operation_id}: {e}")

    async def _maybe_update_parent_operation(self, child_operation_id: str, conn):
        """Check if this is a child operation and update parent status if all siblings are done.

        Must be called within an active transaction that has already updated the child's status.
        Uses SELECT FOR UPDATE to lock the parent and prevent race conditions.

        Args:
            child_operation_id: The operation ID that just completed or failed
            conn: Database connection with an active transaction
        """
        try:
            # Get this operation's metadata to check if it has a parent
            row = await conn.fetchrow(
                f"""
                SELECT result_metadata, bank_id
                FROM {fq_table("async_operations")}
                WHERE operation_id = $1
                """,
                uuid.UUID(child_operation_id),
            )

            if not row:
                return

            result_metadata = json.loads(row["result_metadata"]) if row["result_metadata"] else {}
            parent_operation_id = result_metadata.get("parent_operation_id")

            if not parent_operation_id:
                # Not a child operation
                return

            bank_id = row["bank_id"]

            # Lock the parent operation to prevent concurrent updates from other children
            # Use FOR UPDATE to ensure only one child can update the parent at a time
            parent_row = await conn.fetchrow(
                f"""
                SELECT operation_id
                FROM {fq_table("async_operations")}
                WHERE operation_id = $1 AND bank_id = $2
                FOR UPDATE
                """,
                uuid.UUID(parent_operation_id),
                bank_id,
            )

            if not parent_row:
                # Parent doesn't exist (shouldn't happen)
                return

            # Get all sibling operations (including this one)
            # This query runs in the same transaction, so it sees the current child's updated status
            siblings = await conn.fetch(
                f"""
                SELECT status
                FROM {fq_table("async_operations")}
                WHERE bank_id = $1
                AND result_metadata::jsonb @> $2::jsonb
                """,
                bank_id,
                json.dumps({"parent_operation_id": parent_operation_id}),
            )

            if not siblings:
                return

            # Check if all siblings are done (completed or failed)
            all_completed = all(sib["status"] == "completed" for sib in siblings)
            any_failed = any(sib["status"] == "failed" for sib in siblings)
            all_done = all(sib["status"] in ("completed", "failed") for sib in siblings)

            if not all_done:
                # Some siblings still pending/processing
                return

            # All siblings are done - update parent status
            if any_failed:
                new_status = "failed"
                # Set parent error message to indicate child failure
                await conn.execute(
                    f"""
                    UPDATE {fq_table("async_operations")}
                    SET status = $2, error_message = $3, updated_at = NOW()
                    WHERE operation_id = $1
                    """,
                    uuid.UUID(parent_operation_id),
                    new_status,
                    "One or more sub-batches failed",
                )
            elif all_completed:
                new_status = "completed"
                await conn.execute(
                    f"""
                    UPDATE {fq_table("async_operations")}
                    SET status = $2, updated_at = NOW(), completed_at = NOW()
                    WHERE operation_id = $1
                    """,
                    uuid.UUID(parent_operation_id),
                    new_status,
                )

            logger.info(f"Updated parent operation {parent_operation_id} to status '{new_status}' (all children done)")

        except Exception as e:
            logger.error(f"Failed to update parent operation for child {child_operation_id}: {e}")
            # Re-raise to rollback the transaction
            raise

    async def initialize(self):
        """Initialize the connection pool, models, and background workers.

        Loads models (embeddings, cross-encoder) in parallel with pg0 startup
        for faster overall initialization.
        """
        if self._initialized:
            return

        # Run model loading in thread pool (CPU-bound) in parallel with pg0 startup
        loop = asyncio.get_event_loop()

        async def start_pg0():
            """Start pg0 if configured."""
            if self._use_pg0:
                kwargs = {"name": self._pg0_instance_name}
                if self._pg0_port is not None:
                    kwargs["port"] = self._pg0_port
                pg0 = EmbeddedPostgres(**kwargs)
                # Check if pg0 is already running before we start it
                was_already_running = await pg0.is_running()
                self.db_url = await pg0.ensure_running()
                # Only track pg0 (to stop later) if WE started it
                if not was_already_running:
                    self._pg0 = pg0

        async def init_embeddings():
            """Initialize embedding model."""
            # For local providers, run in thread pool to avoid blocking event loop
            if self.embeddings.provider_name == "local":
                await loop.run_in_executor(None, lambda: asyncio.run(self.embeddings.initialize()))
            else:
                await self.embeddings.initialize()

        async def init_cross_encoder():
            """Initialize cross-encoder model."""
            cross_encoder = self._cross_encoder_reranker.cross_encoder
            # For local providers, run in thread pool to avoid blocking event loop
            if cross_encoder.provider_name == "local":
                await loop.run_in_executor(None, lambda: asyncio.run(cross_encoder.initialize()))
            else:
                await cross_encoder.initialize()
            # Mark reranker as initialized
            self._cross_encoder_reranker._initialized = True

        async def init_query_analyzer():
            """Initialize query analyzer model."""
            # Query analyzer load is sync and CPU-bound
            await loop.run_in_executor(None, self.query_analyzer.load)

        async def verify_llm():
            """Verify LLM connections are working for all unique configs."""
            if not self._skip_llm_verification:
                # Verify default config
                await self._llm_config.verify_connection()
                # Verify retain config if different from default
                retain_is_different = (
                    self._retain_llm_config.provider != self._llm_config.provider
                    or self._retain_llm_config.model != self._llm_config.model
                )
                if retain_is_different:
                    await self._retain_llm_config.verify_connection()
                # Verify reflect config if different from default and retain
                reflect_is_different = (
                    self._reflect_llm_config.provider != self._llm_config.provider
                    or self._reflect_llm_config.model != self._llm_config.model
                ) and (
                    self._reflect_llm_config.provider != self._retain_llm_config.provider
                    or self._reflect_llm_config.model != self._retain_llm_config.model
                )
                if reflect_is_different:
                    await self._reflect_llm_config.verify_connection()
                # Verify consolidation config if different from all others
                consolidation_is_different = (
                    (
                        self._consolidation_llm_config.provider != self._llm_config.provider
                        or self._consolidation_llm_config.model != self._llm_config.model
                    )
                    and (
                        self._consolidation_llm_config.provider != self._retain_llm_config.provider
                        or self._consolidation_llm_config.model != self._retain_llm_config.model
                    )
                    and (
                        self._consolidation_llm_config.provider != self._reflect_llm_config.provider
                        or self._consolidation_llm_config.model != self._reflect_llm_config.model
                    )
                )
                if consolidation_is_different:
                    await self._consolidation_llm_config.verify_connection()

        # Build list of initialization tasks
        init_tasks = [
            start_pg0(),
            init_embeddings(),
            init_query_analyzer(),
        ]

        # Only init cross-encoder eagerly if not using lazy initialization
        if not self._lazy_reranker:
            init_tasks.append(init_cross_encoder())

        # Only verify LLM if not skipping
        if not self._skip_llm_verification:
            init_tasks.append(verify_llm())

        # Run pg0 and selected model initializations in parallel
        await asyncio.gather(*init_tasks)

        # Run database migrations if enabled
        if self._run_migrations:
            from ..migrations import (
                ensure_embedding_dimension,
                ensure_text_search_extension,
                ensure_vector_extension,
                run_migrations,
            )

            if not self.db_url:
                raise ValueError("Database URL is required for migrations")

            # Migrate all schemas from the tenant extension
            # The tenant extension is the single source of truth for which schemas exist
            logger.info("Running database migrations...")
            tenants = await self._tenant_extension.list_tenants()
            if tenants:
                logger.info(f"Running migrations on {len(tenants)} schema(s)...")
                for tenant in tenants:
                    schema = tenant.schema
                    if schema:
                        run_migrations(self.db_url, schema=schema)
                logger.info("Schema migrations completed")

                # Get config for vector extension setting
                config = get_config()

                # Ensure embedding column dimension matches the model's dimension
                # This is done after migrations and after embeddings.initialize()
                for tenant in tenants:
                    schema = tenant.schema
                    if schema:
                        ensure_embedding_dimension(
                            self.db_url,
                            self.embeddings.dimension,
                            schema=schema,
                            vector_extension=config.vector_extension,
                        )

                # Ensure vector indexes match the configured extension
                for tenant in tenants:
                    schema = tenant.schema
                    if schema:
                        ensure_vector_extension(self.db_url, vector_extension=config.vector_extension, schema=schema)

                # Ensure text search columns/indexes match the configured extension
                for tenant in tenants:
                    schema = tenant.schema
                    if schema:
                        ensure_text_search_extension(
                            self.db_url, text_search_extension=config.text_search_extension, schema=schema
                        )

        logger.info(f"Connecting to PostgreSQL at {mask_network_location(self.db_url)}")

        # Create connection pool
        # For read-heavy workloads with many parallel think/search operations,
        # we need a larger pool. Read operations don't need strong isolation.
        self._pool = await asyncpg.create_pool(
            self.db_url,
            min_size=self._pool_min_size,
            max_size=self._pool_max_size,
            command_timeout=self._db_command_timeout,
            statement_cache_size=0,  # Disable prepared statement cache
            timeout=self._db_acquire_timeout,  # Connection acquisition timeout (seconds)
        )

        # Initialize entity resolver with pool and configured lookup strategy
        self.entity_resolver = EntityResolver(
            self._pool,
            entity_lookup=self._retain_entity_lookup,
        )

        # Initialize config resolver for hierarchical configuration
        from ..config_resolver import ConfigResolver

        self._config_resolver = ConfigResolver(pool=self._pool, tenant_extension=self._tenant_extension)
        logger.debug("Config resolver initialized for hierarchical configuration")

        # Initialize file storage
        from .storage import create_file_storage

        config = get_config()
        self._file_storage = create_file_storage(
            storage_type=config.file_storage_type,
            pool_getter=lambda: self._pool,
            schema_getter=get_current_schema,
        )
        logger.debug(f"File storage initialized ({config.file_storage_type})")

        # Initialize parser registry
        from .parsers import FileParserRegistry, IrisParser, MarkitdownParser

        self._parser_registry = FileParserRegistry()
        try:
            self._parser_registry.register(MarkitdownParser())
            logger.debug("Registered markitdown parser")
        except ImportError:
            logger.warning("markitdown not available - file parsing disabled")
        iris_token = config.file_parser_iris_token
        iris_org_id = config.file_parser_iris_org_id
        if iris_token and iris_org_id:
            self._parser_registry.register(IrisParser(token=iris_token, org_id=iris_org_id))
            logger.debug("Registered iris parser")
        else:
            logger.debug("Iris parser not registered (VECTORIZE_TOKEN or VECTORIZE_ORG_ID not set)")

        # Initialize webhook manager
        from ..webhooks import WebhookManager
        from ..webhooks.models import WebhookConfig

        webhook_global: list[WebhookConfig] = []
        if config.webhook_url:
            webhook_global = [
                WebhookConfig(
                    id="",  # No DB row for env-configured global webhook
                    bank_id=None,
                    url=config.webhook_url,
                    secret=config.webhook_secret,
                    event_types=config.webhook_event_types,
                    enabled=True,
                )
            ]
        self._webhook_manager = WebhookManager(
            pool=self._pool,
            global_webhooks=webhook_global,
            tenant_extension=self._tenant_extension,
        )
        logger.debug("Webhook manager initialized")

        # Long-lived HTTP client for webhook delivery tasks
        self._http_client = httpx.AsyncClient(timeout=30.0)

        # Set executor for task backend and initialize
        self._task_backend.set_executor(self.execute_task)
        await self._task_backend.initialize()

        self._initialized = True
        logger.info("Memory system initialized (pool and task backend started)")

    async def _get_pool(self) -> asyncpg.Pool:
        """Get the connection pool (must call initialize() first)."""
        if not self._initialized:
            await self.initialize()
        return self._pool

    async def _acquire_connection(self):
        """
        Acquire a connection from the pool with retry logic.

        Returns an async context manager that yields a connection.
        Retries on transient connection errors with exponential backoff.
        """
        pool = await self._get_pool()

        async def acquire():
            return await pool.acquire()

        return await _retry_with_backoff(acquire)

    async def health_check(self) -> dict:
        """
        Perform a health check by querying the database.

        Returns:
            dict with status and optional error message

        Note:
            Returns unhealthy until initialize() has completed successfully.
        """
        # Not healthy until fully initialized
        if not self._initialized:
            return {"status": "unhealthy", "reason": "not_initialized"}

        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                if result == 1:
                    return {"status": "healthy", "database": "connected"}
                else:
                    return {"status": "unhealthy", "database": "unexpected response"}
        except Exception as e:
            return {"status": "unhealthy", "database": "error", "error": str(e)}

    async def close(self):
        """Close the connection pool and shutdown background workers."""
        logger.info("close() started")

        # Shutdown task backend
        await self._task_backend.shutdown()

        # Close HTTP client used for webhook delivery
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

        # Close pool
        if self._pool is not None:
            self._pool.terminate()
            self._pool = None

        self._initialized = False

        # Stop pg0 if we started it
        if self._pg0 is not None:
            logger.info("Stopping pg0...")
            await self._pg0.stop()
            self._pg0 = None
            logger.info("pg0 stopped")

    async def wait_for_background_tasks(self):
        """
        Wait for all pending background tasks to complete.

        This is useful in tests to ensure background tasks complete before making assertions.
        """
        if hasattr(self._task_backend, "wait_for_pending_tasks"):
            await self._task_backend.wait_for_pending_tasks()

    def _format_readable_date(self, dt: datetime) -> str:
        """
        Format a datetime into a readable string for temporal matching.

        Examples:
            - June 2024
            - January 15, 2024
            - December 2023

        This helps queries like "camping in June" match facts that happened in June.

        Args:
            dt: datetime object to format

        Returns:
            Readable date string
        """
        # Format as "Month Year" for most cases
        # Could be extended to include day for very specific dates if needed
        month_name = dt.strftime("%B")  # Full month name (e.g., "June")
        year = dt.strftime("%Y")  # Year (e.g., "2024")

        # For now, use "Month Year" format
        # Could check if day is significant (not 1st or 15th) and include it
        return f"{month_name} {year}"

    def retain(
        self,
        bank_id: str,
        content: str,
        context: str = "",
        event_date: datetime | None = None,
        request_context: "RequestContext | None" = None,
    ) -> list[str]:
        """
        Store content as memory units (synchronous wrapper).

        This is a synchronous wrapper around retain_async() for convenience.
        For best performance, use retain_async() directly.

        Args:
            bank_id: Unique identifier for the bank
            content: Text content to store
            context: Context about when/why this memory was formed
            event_date: When the event occurred (defaults to now)
            request_context: Request context for authentication (optional, uses internal context if not provided)

        Returns:
            List of created unit IDs
        """
        # Run async version synchronously
        from atulya_api.models import RequestContext as RC

        ctx = request_context if request_context is not None else RC()
        return asyncio.run(self.retain_async(bank_id, content, context, event_date, request_context=ctx))

    async def retain_async(
        self,
        bank_id: str,
        content: str,
        context: str = "",
        event_date: datetime | None = None,
        document_id: str | None = None,
        fact_type_override: str | None = None,
        confidence_score: float | None = None,
        *,
        request_context: "RequestContext",
    ) -> list[str]:
        """
        Store content as memory units with temporal and semantic links (ASYNC version).

        This is a convenience wrapper around retain_batch_async for a single content item.

        Args:
            bank_id: Unique identifier for the bank
            content: Text content to store
            context: Context about when/why this memory was formed
            event_date: When the event occurred (defaults to now)
            document_id: Optional document ID for tracking (always upserts if document already exists)
            fact_type_override: Override fact type ('world', 'experience')
            confidence_score: Confidence score (0.0 to 1.0)
            request_context: Request context for authentication.

        Returns:
            List of created unit IDs
        """
        # Build content dict
        content_dict: RetainContentDict = {"content": content, "context": context}
        if event_date:
            content_dict["event_date"] = event_date
        if document_id:
            content_dict["document_id"] = document_id

        # Use retain_batch_async with a single item (avoids code duplication)
        result = await self.retain_batch_async(
            bank_id=bank_id,
            contents=[content_dict],
            request_context=request_context,
            fact_type_override=fact_type_override,
            confidence_score=confidence_score,
        )

        # Return the first (and only) list of unit IDs
        return result[0] if result else []

    async def retain_batch_async(
        self,
        bank_id: str,
        contents: list[RetainContentDict],
        *,
        request_context: "RequestContext",
        document_id: str | None = None,
        fact_type_override: str | None = None,
        confidence_score: float | None = None,
        document_tags: list[str] | None = None,
        return_usage: bool = False,
        operation_id: str | None = None,
        outbox_callback: "Callable[[asyncpg.Connection], Awaitable[None]] | None" = None,
    ):
        """
        Store multiple content items as memory units in ONE batch operation.

        This is MUCH more efficient than calling retain_async multiple times:
        - Extracts facts from all contents in parallel
        - Generates ALL embeddings in ONE batch
        - Does ALL database operations in ONE transaction
        - Automatically chunks large batches to prevent timeouts

        Args:
            bank_id: Unique identifier for the bank
            contents: List of dicts with keys:
                - "content" (required): Text content to store
                - "context" (optional): Context about the memory
                - "event_date" (optional): When the event occurred
                - "document_id" (optional): Document ID for this specific content item
            document_id: **DEPRECATED** - Use "document_id" key in each content dict instead.
                        Applies the same document_id to ALL content items that don't specify their own.
            fact_type_override: Override fact type for all facts ('world', 'experience')
            confidence_score: Confidence score (0.0 to 1.0)
            return_usage: If True, returns tuple of (unit_ids, TokenUsage). Default False for backward compatibility.

        Returns:
            If return_usage=False: List of lists of unit IDs (one list per content item)
            If return_usage=True: Tuple of (unit_ids, TokenUsage)

        Example (new style - per-content document_id):
            unit_ids = await memory.retain_batch_async(
                bank_id="user123",
                contents=[
                    {"content": "Alice works at Google", "document_id": "doc1"},
                    {"content": "Bob loves Python", "document_id": "doc2"},
                    {"content": "More about Alice", "document_id": "doc1"},
                ]
            )
            # Returns: [["unit-id-1"], ["unit-id-2"], ["unit-id-3"]]

        Example (deprecated style - batch-level document_id):
            unit_ids = await memory.retain_batch_async(
                bank_id="user123",
                contents=[
                    {"content": "Alice works at Google"},
                    {"content": "Bob loves Python"},
                ],
                document_id="meeting-2024-01-15"
            )
            # Returns: [["unit-id-1"], ["unit-id-2"]]
        """
        start_time = time.time()

        if not contents:
            if return_usage:
                return [], TokenUsage()
            return []

        # Authenticate tenant and set schema in context (for fq_table())
        await self._authenticate_tenant(request_context)

        # Validate operation if validator is configured
        contents_copy = [dict(c) for c in contents]  # Convert TypedDict to regular dict for extension
        if self._operation_validator:
            from atulya_api.extensions import RetainContext

            ctx = RetainContext(
                bank_id=bank_id,
                contents=contents_copy,
                request_context=request_context,
                document_id=document_id,
                fact_type_override=fact_type_override,
                confidence_score=confidence_score,
            )
            await self._validate_operation(self._operation_validator.validate_retain(ctx))

        # Apply batch-level document_id to contents that don't have their own (backwards compatibility)
        if document_id:
            for item in contents:
                if "document_id" not in item:
                    item["document_id"] = document_id

        # Validate no duplicate document_ids in the batch
        # Having duplicate document_ids causes race conditions in document upserts during parallel processing
        doc_ids = [item.get("document_id") for item in contents if item.get("document_id")]
        if len(doc_ids) != len(set(doc_ids)):
            from collections import Counter

            duplicates = [doc_id for doc_id, count in Counter(doc_ids).items() if count > 1]
            raise ValueError(
                f"Batch contains duplicate document_ids: {duplicates}. "
                f"Each content item in a batch must have a unique document_id to avoid race conditions."
            )

        # Auto-chunk large batches by token count to avoid timeouts and memory issues
        # Calculate total token count
        total_tokens = sum(count_tokens(item.get("content", "")) for item in contents)
        total_usage = TokenUsage()

        # Get batch size threshold from config
        config = get_config()
        tokens_per_batch = config.retain_batch_tokens

        if total_tokens > tokens_per_batch:
            # Split into smaller batches based on token count
            logger.info(
                f"Large batch detected ({total_tokens:,} tokens from {len(contents)} items). Splitting into sub-batches of ~{tokens_per_batch:,} tokens each..."
            )

            sub_batches = []
            current_batch = []
            current_batch_tokens = 0

            for item in contents:
                item_tokens = count_tokens(item.get("content", ""))

                # If adding this item would exceed the limit, start a new batch
                # (unless current batch is empty - then we must include it even if it's large)
                if current_batch and current_batch_tokens + item_tokens > tokens_per_batch:
                    sub_batches.append(current_batch)
                    current_batch = [item]
                    current_batch_tokens = item_tokens
                else:
                    current_batch.append(item)
                    current_batch_tokens += item_tokens

            # Add the last batch
            if current_batch:
                sub_batches.append(current_batch)

            logger.info(f"Split into {len(sub_batches)} sub-batches: {[len(b) for b in sub_batches]} items each")

            # Process each sub-batch
            all_results = []
            for i, sub_batch in enumerate(sub_batches, 1):
                sub_batch_tokens = sum(count_tokens(item.get("content", "")) for item in sub_batch)
                logger.info(
                    f"Processing sub-batch {i}/{len(sub_batches)}: {len(sub_batch)} items, {sub_batch_tokens:,} tokens"
                )

                sub_results, sub_usage = await self._retain_batch_async_internal(
                    bank_id=bank_id,
                    contents=sub_batch,
                    request_context=request_context,
                    document_id=document_id,
                    is_first_batch=i == 1,  # Only upsert on first batch
                    fact_type_override=fact_type_override,
                    confidence_score=confidence_score,
                    document_tags=document_tags,
                    operation_id=operation_id,
                    # Outbox callback runs inside the last sub-batch's transaction so the
                    # webhook delivery row is committed atomically with the final retain data.
                    outbox_callback=outbox_callback if i == len(sub_batches) else None,
                )
                all_results.extend(sub_results)
                total_usage = total_usage + sub_usage

            total_time = time.time() - start_time
            logger.info(
                f"RETAIN_BATCH_ASYNC (chunked) COMPLETE: {len(all_results)} results from {len(contents)} contents in {total_time:.3f}s"
            )
            result = all_results
        else:
            # Small batch - use internal method directly
            result, total_usage = await self._retain_batch_async_internal(
                bank_id=bank_id,
                contents=contents,
                request_context=request_context,
                document_id=document_id,
                is_first_batch=True,
                fact_type_override=fact_type_override,
                confidence_score=confidence_score,
                document_tags=document_tags,
                operation_id=operation_id,
                outbox_callback=outbox_callback,
            )

        # Call post-operation hook if validator is configured
        if self._operation_validator:
            from atulya_api.extensions import RetainResult

            result_ctx = RetainResult(
                bank_id=bank_id,
                contents=contents_copy,
                request_context=request_context,
                document_id=document_id,
                fact_type_override=fact_type_override,
                confidence_score=confidence_score,
                unit_ids=result,
                success=True,
                error=None,
                llm_input_tokens=total_usage.input_tokens,
                llm_output_tokens=total_usage.output_tokens,
                llm_total_tokens=total_usage.total_tokens,
            )
            try:
                await self._operation_validator.on_retain_complete(result_ctx)
            except Exception as e:
                logger.warning(f"Post-retain hook error (non-fatal): {e}")

        # Trigger consolidation as a tracked async operation if enabled
        # Resolve bank-specific config to check if observations are enabled for this bank
        config = await self._config_resolver.resolve_full_config(bank_id, request_context)
        if config.enable_observations:
            try:
                await self.submit_async_consolidation(bank_id=bank_id, request_context=request_context)
            except Exception as e:
                # Log but don't fail the retain - consolidation is non-critical
                logger.warning(f"Failed to submit consolidation task for bank {bank_id}: {e}")

        if return_usage:
            return result, total_usage
        return result

    async def _retain_batch_async_internal(
        self,
        bank_id: str,
        contents: list[RetainContentDict],
        request_context: "RequestContext",
        document_id: str | None = None,
        is_first_batch: bool = True,
        fact_type_override: str | None = None,
        confidence_score: float | None = None,
        document_tags: list[str] | None = None,
        operation_id: str | None = None,
        outbox_callback: "Callable[[asyncpg.Connection], Awaitable[None]] | None" = None,
    ) -> tuple[list[list[str]], "TokenUsage"]:
        """
        Internal method for batch processing without chunking logic.

        Assumes contents are already appropriately sized (< 50k chars).
        Called by retain_batch_async after chunking large batches.

        Uses semaphore for backpressure to limit concurrent retains.

        Args:
            bank_id: Unique identifier for the bank
            contents: List of dicts with content, context, event_date
            request_context: Request context for config resolution
            document_id: Optional document ID (always upserts if exists)
            is_first_batch: Whether this is the first batch (for chunked operations, only delete on first batch)
            fact_type_override: Override fact type for all facts
            confidence_score: Confidence score for opinions
            document_tags: Tags applied to all items in this batch

        Returns:
            Tuple of (unit ID lists, token usage for fact extraction)
        """
        # Backpressure: limit concurrent retains to prevent database contention
        async with self._put_semaphore:
            # Use the new modular orchestrator
            from .retain import orchestrator

            pool = await self._get_pool()

            # Resolve bank-specific config for this operation
            resolved_config = await self._config_resolver.resolve_full_config(bank_id, request_context)

            # Create parent span for retain operation
            with create_operation_span("retain", bank_id):
                return await orchestrator.retain_batch(
                    pool=pool,
                    embeddings_model=self.embeddings,
                    llm_config=self._retain_llm_config.with_config(resolved_config),
                    entity_resolver=self.entity_resolver,
                    format_date_fn=self._format_readable_date,
                    bank_id=bank_id,
                    contents_dicts=contents,
                    document_id=document_id,
                    is_first_batch=is_first_batch,
                    fact_type_override=fact_type_override,
                    confidence_score=confidence_score,
                    document_tags=document_tags,
                    config=resolved_config,
                    operation_id=operation_id,
                    schema=request_context.tenant_id if request_context else None,
                    outbox_callback=outbox_callback,
                )

    def recall(
        self,
        bank_id: str,
        query: str,
        fact_type: str,
        budget: Budget = Budget.MID,
        max_tokens: int = 4096,
        enable_trace: bool = False,
    ) -> tuple[list[dict[str, Any]], Any | None]:
        """
        Recall memories using 4-way parallel retrieval (synchronous wrapper).

        This is a synchronous wrapper around recall_async() for convenience.
        For best performance, use recall_async() directly.

        Args:
            bank_id: bank ID to recall for
            query: Recall query
            fact_type: Required filter for fact type ('world', 'experience', or 'opinion')
            budget: Budget level for graph traversal (low=100, mid=300, high=600 units)
            max_tokens: Maximum tokens to return (counts only 'text' field, default 4096)
            enable_trace: If True, returns detailed trace object

        Returns:
            Tuple of (results, trace)
        """
        # Run async version synchronously - deprecated sync method, passing None for request_context
        from atulya_api.models import RequestContext

        return asyncio.run(
            self.recall_async(
                bank_id,
                query,
                budget=budget,
                max_tokens=max_tokens,
                enable_trace=enable_trace,
                fact_type=[fact_type],
                request_context=RequestContext(),
            )
        )

    async def recall_async(
        self,
        bank_id: str,
        query: str,
        *,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        enable_trace: bool = False,
        fact_type: list[str] | None = None,
        question_date: datetime | None = None,
        include_entities: bool = False,
        max_entity_tokens: int = 500,
        include_chunks: bool = False,
        max_chunk_tokens: int = 8192,
        include_source_facts: bool = False,
        max_source_facts_tokens: int = 4096,
        max_source_facts_tokens_per_observation: int = -1,
        request_context: "RequestContext",
        tags: list[str] | None = None,
        tags_match: TagsMatch = "any",
        _connection_budget: int | None = None,
        _quiet: bool = False,
        _record_access_telemetry: bool = True,
    ) -> RecallResultModel:
        """
        Recall memories using N*4-way parallel retrieval (N fact types × 4 retrieval methods).

        This implements the core RECALL operation:
        1. Retrieval: For each fact type, run 4 parallel retrievals (semantic vector, BM25 keyword, graph activation, temporal graph)
        2. Merge: Combine using Reciprocal Rank Fusion (RRF)
        3. Rerank: Score using selected reranker (heuristic or cross-encoder)
        4. Diversify: Apply MMR for diversity
        5. Token Filter: Return results up to max_tokens budget

        Args:
            bank_id: bank ID to recall for
            query: Recall query
            fact_type: List of fact types to recall (e.g., ['world', 'experience'])
            budget: Budget level for graph traversal (low=100, mid=300, high=600 units)
            max_tokens: Maximum tokens to return (counts only 'text' field, default 4096)
                       Results are returned until token budget is reached, stopping before
                       including a fact that would exceed the limit
            enable_trace: Whether to return trace for debugging (deprecated)
            question_date: Optional date when question was asked (for temporal filtering)
            include_entities: Whether to include entity observations in the response
            max_entity_tokens: Maximum tokens for entity observations (default 500)
            include_chunks: Whether to include raw chunks in the response
            max_chunk_tokens: Maximum tokens for chunks (default 8192)
                             NOTE: Chunks are fetched independently of max_tokens filtering.
                             This means setting max_tokens=0 will return 0 facts but can still
                             return chunks from the top-scored (reranked) results.
                             Chunks are fetched in batches (estimated as (max_chunk_tokens // retain_chunk_size) * 2)
                             until the token budget is exhausted or all chunks are fetched.
                             This handles varying chunk sizes across documents.
            tags: Optional list of tags for visibility filtering (OR matching - returns
                  memories that have at least one matching tag)

        Returns:
            RecallResultModel containing:
            - results: List of MemoryFact objects (filtered by max_tokens)
            - trace: Optional trace information for debugging
            - entities: Optional dict of entity states (if include_entities=True)
            - chunks: Optional dict of chunks (if include_chunks=True, independent of max_tokens)
        """
        # Authenticate tenant and set schema in context (for fq_table())
        await self._authenticate_tenant(request_context)

        # Default to all fact types if not specified
        if fact_type is None:
            fact_type = list(VALID_RECALL_FACT_TYPES)

        # Filter out 'opinion' early (deprecated, silently ignore)
        fact_type = [ft for ft in fact_type if ft != "opinion"]

        # Validate fact types
        invalid_types = set(fact_type) - VALID_RECALL_FACT_TYPES
        if invalid_types:
            raise ValueError(
                f"Invalid fact type(s): {', '.join(sorted(invalid_types))}. "
                f"Must be one of: {', '.join(sorted(VALID_RECALL_FACT_TYPES))}"
            )
        if not fact_type:
            # All requested types were opinions - return empty result
            return RecallResultModel(results=[], entities={}, chunks={})

        # Validate operation if validator is configured
        if self._operation_validator:
            from atulya_api.extensions import RecallContext

            ctx = RecallContext(
                bank_id=bank_id,
                query=query,
                request_context=request_context,
                budget=budget,
                max_tokens=max_tokens,
                enable_trace=enable_trace,
                fact_types=list(fact_type),
                question_date=question_date,
                include_entities=include_entities,
                max_entity_tokens=max_entity_tokens,
                include_chunks=include_chunks,
                max_chunk_tokens=max_chunk_tokens,
            )
            await self._validate_operation(self._operation_validator.validate_recall(ctx))

        # Map budget enum to thinking_budget number (default to MID if None)
        budget_mapping = {Budget.LOW: 100, Budget.MID: 300, Budget.HIGH: 1000}
        effective_budget = budget if budget is not None else Budget.MID
        thinking_budget = budget_mapping[effective_budget]

        # Log recall start with tags if present (skip if quiet mode for internal operations)
        if not _quiet:
            tags_info = f", tags={tags} ({tags_match})" if tags else ""
            logger.info(f"[RECALL {bank_id[:8]}] Starting recall for query: {query[:50]}...{tags_info}")

        # Create parent span for recall operation
        from ..tracing import get_tracer

        tracer = get_tracer()
        # Use start_as_current_span to ensure child spans are linked properly
        recall_span_context = tracer.start_as_current_span("atulya.recall")
        recall_span = recall_span_context.__enter__()
        recall_span.set_attribute("atulya.bank_id", bank_id)
        recall_span.set_attribute("atulya.query", query[:100])
        recall_span.set_attribute("atulya.fact_types", ",".join(fact_type))
        recall_span.set_attribute("atulya.thinking_budget", thinking_budget)
        recall_span.set_attribute("atulya.max_tokens", max_tokens)

        try:
            # Backpressure: limit concurrent recalls to prevent overwhelming the database
            result = None
            error_msg = None
            semaphore_wait_start = time.time()
            async with self._search_semaphore:
                semaphore_wait = time.time() - semaphore_wait_start
                # Retry loop for connection errors
                max_retries = 3
                for attempt in range(max_retries + 1):
                    try:
                        result = await self._search_with_retries(
                            bank_id,
                            query,
                            fact_type,
                            thinking_budget,
                            max_tokens,
                            enable_trace,
                            question_date,
                            include_entities,
                            max_entity_tokens,
                            include_chunks,
                            max_chunk_tokens,
                            request_context,
                            semaphore_wait=semaphore_wait,
                            tags=tags,
                            tags_match=tags_match,
                            connection_budget=_connection_budget,
                            quiet=_quiet,
                            include_source_facts=include_source_facts,
                            max_source_facts_tokens=max_source_facts_tokens,
                            max_source_facts_tokens_per_observation=max_source_facts_tokens_per_observation,
                        )
                        break  # Success - exit retry loop
                    except Exception as e:
                        # Check if it's a connection error
                        is_connection_error = (
                            isinstance(e, asyncpg.TooManyConnectionsError)
                            or isinstance(e, asyncpg.CannotConnectNowError)
                            or (isinstance(e, asyncpg.PostgresError) and "connection" in str(e).lower())
                        )

                        if is_connection_error and attempt < max_retries:
                            # Wait with exponential backoff before retry
                            wait_time = 0.5 * (2**attempt)  # 0.5s, 1s, 2s
                            logger.warning(
                                f"Connection error on search attempt {attempt + 1}/{max_retries + 1}: {str(e)}. "
                                f"Retrying in {wait_time:.1f}s..."
                            )
                            await asyncio.sleep(wait_time)
                        else:
                            # Not a connection error or out of retries - call post-hook and raise
                            error_msg = str(e)
                            if self._operation_validator:
                                from atulya_api.extensions.operation_validator import RecallResult

                                result_ctx = RecallResult(
                                    bank_id=bank_id,
                                    query=query,
                                    request_context=request_context,
                                    budget=budget,
                                    max_tokens=max_tokens,
                                    enable_trace=enable_trace,
                                    fact_types=list(fact_type),
                                    question_date=question_date,
                                    include_entities=include_entities,
                                    max_entity_tokens=max_entity_tokens,
                                    include_chunks=include_chunks,
                                    max_chunk_tokens=max_chunk_tokens,
                                    result=None,
                                    success=False,
                                    error=error_msg,
                                )
                                try:
                                    await self._operation_validator.on_recall_complete(result_ctx)
                                except Exception as hook_err:
                                    logger.warning(f"Post-recall hook error (non-fatal): {hook_err}")
                            raise
                else:
                    # Exceeded max retries
                    error_msg = "Exceeded maximum retries for search due to connection errors."
                    if self._operation_validator:
                        from atulya_api.extensions.operation_validator import RecallResult

                        result_ctx = RecallResult(
                            bank_id=bank_id,
                            query=query,
                            request_context=request_context,
                            budget=budget,
                            max_tokens=max_tokens,
                            enable_trace=enable_trace,
                            fact_types=list(fact_type),
                            question_date=question_date,
                            include_entities=include_entities,
                            max_entity_tokens=max_entity_tokens,
                            include_chunks=include_chunks,
                            max_chunk_tokens=max_chunk_tokens,
                            result=None,
                            success=False,
                            error=error_msg,
                        )
                        try:
                            await self._operation_validator.on_recall_complete(result_ctx)
                        except Exception as hook_err:
                            logger.warning(f"Post-recall hook error (non-fatal): {hook_err}")
                    raise Exception(error_msg)

            # Call post-operation hook for success
            if self._operation_validator and result is not None:
                from atulya_api.extensions.operation_validator import RecallResult

                result_ctx = RecallResult(
                    bank_id=bank_id,
                    query=query,
                    request_context=request_context,
                    budget=budget,
                    max_tokens=max_tokens,
                    enable_trace=enable_trace,
                    fact_types=list(fact_type),
                    question_date=question_date,
                    include_entities=include_entities,
                    max_entity_tokens=max_entity_tokens,
                    include_chunks=include_chunks,
                    max_chunk_tokens=max_chunk_tokens,
                    result=result,
                    success=True,
                    error=None,
                )
                try:
                    await self._operation_validator.on_recall_complete(result_ctx)
                except Exception as e:
                    logger.warning(f"Post-recall hook error (non-fatal): {e}")

            if _record_access_telemetry:
                await self._record_access_telemetry(bank_id=bank_id, result=result)
            return result
        finally:
            recall_span_context.__exit__(None, None, None)

    async def _apply_access_count_updates(
        self,
        *,
        bank_id: str,
        fact_counts: dict[str, int],
        chunk_counts: dict[str, int],
        mental_model_counts: dict[str, int] | None = None,
    ) -> None:
        """Persist access-count updates for influence telemetry."""
        if not fact_counts and not chunk_counts and not mental_model_counts:
            return
        valid_fact_counts: dict[uuid.UUID, int] = {}
        for raw_id, weight in fact_counts.items():
            try:
                valid_fact_counts[uuid.UUID(str(raw_id))] = int(weight)
            except (ValueError, TypeError):
                continue
        valid_model_counts: dict[uuid.UUID, int] = {}
        for raw_id, weight in (mental_model_counts or {}).items():
            try:
                valid_model_counts[uuid.UUID(str(raw_id))] = int(weight)
            except (ValueError, TypeError):
                continue
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            memory_rows_updated = 0
            chunk_rows_updated = 0
            model_rows_updated = 0
            if valid_fact_counts:
                fact_ids = list(valid_fact_counts.keys())
                fact_weights = [valid_fact_counts[i] for i in fact_ids]
                status = await conn.execute(
                    f"""
                    WITH updates AS (
                        SELECT UNNEST($2::uuid[]) AS id, UNNEST($3::int[]) AS w
                    )
                    UPDATE {fq_table("memory_units")} mu
                    SET access_count = COALESCE(mu.access_count, 0) + updates.w,
                        last_accessed_at = NOW()
                    FROM updates
                    WHERE mu.bank_id = $1
                      AND mu.id = updates.id
                    """,
                    bank_id,
                    fact_ids,
                    fact_weights,
                )
                try:
                    memory_rows_updated = int(str(status).split()[-1])
                except Exception:
                    memory_rows_updated = 0
            if chunk_counts:
                chunk_ids = list(chunk_counts.keys())
                chunk_weights = [chunk_counts[i] for i in chunk_ids]
                status = await conn.execute(
                    f"""
                    WITH updates AS (
                        SELECT UNNEST($2::text[]) AS id, UNNEST($3::int[]) AS w
                    )
                    UPDATE {fq_table("chunks")} ch
                    SET access_count = COALESCE(ch.access_count, 0) + updates.w,
                        last_accessed_at = NOW()
                    FROM updates
                    WHERE ch.bank_id = $1
                      AND ch.chunk_id = updates.id
                    """,
                    bank_id,
                    chunk_ids,
                    chunk_weights,
                )
                try:
                    chunk_rows_updated = int(str(status).split()[-1])
                except Exception:
                    chunk_rows_updated = 0
            if valid_model_counts:
                model_ids = list(valid_model_counts.keys())
                model_weights = [valid_model_counts[i] for i in model_ids]
                status = await conn.execute(
                    f"""
                    WITH updates AS (
                        SELECT UNNEST($2::uuid[]) AS id, UNNEST($3::int[]) AS w
                    )
                    UPDATE {fq_table("mental_models")} mm
                    SET access_count = COALESCE(mm.access_count, 0) + updates.w,
                        last_accessed_at = NOW()
                    FROM updates
                    WHERE mm.bank_id = $1
                      AND mm.id = updates.id
                    """,
                    bank_id,
                    model_ids,
                    model_weights,
                )
                try:
                    model_rows_updated = int(str(status).split()[-1])
                except Exception:
                    model_rows_updated = 0
            logger.debug(
                "access telemetry persisted bank=%s memory_rows=%d chunk_rows=%d model_rows=%d requested(memory=%d,chunk=%d,model=%d)",
                bank_id,
                memory_rows_updated,
                chunk_rows_updated,
                model_rows_updated,
                len(valid_fact_counts),
                len(chunk_counts),
                len(valid_model_counts),
            )

    async def _record_access_telemetry(self, *, bank_id: str, result: RecallResultModel | None) -> None:
        """
        Best-effort telemetry update for influence scoring.
        Never raises to avoid impacting recall latency/availability.
        """
        if result is None:
            return
        try:
            # Dedup within a single recall operation to keep counters meaningful:
            # one operation-level access signal per artifact.
            fact_ids_seen: set[str] = set()
            chunk_ids_seen: set[str] = set()

            def _add(target: set[str], raw_id: object) -> None:
                if not raw_id:
                    return
                key = str(raw_id)
                if key:
                    target.add(key)

            # Primary recalled facts always count as accesses.
            for item in result.results:
                _add(fact_ids_seen, getattr(item, "id", None))

            # Only chunks explicitly materialized in the recall response are counted.
            # This prevents overcounting provenance chunk_ids that were never expanded/used.
            for chunk_id in (result.chunks or {}).keys():
                _add(chunk_ids_seen, chunk_id)

            # Observation source facts can contribute to answer quality even when not
            # present in top-level results; include them in access telemetry.
            for source_fact in (result.source_facts or {}).values():
                _add(fact_ids_seen, getattr(source_fact, "id", None))

            fact_counts = {fid: 1 for fid in fact_ids_seen}
            chunk_counts = {cid: 1 for cid in chunk_ids_seen}

            await self._apply_access_count_updates(
                bank_id=bank_id,
                fact_counts=fact_counts,
                chunk_counts=chunk_counts,
            )
        except Exception as e:
            logger.warning("access telemetry update skipped for bank=%s: %s", bank_id, e)

    async def _record_reflect_access_telemetry(
        self,
        *,
        bank_id: str,
        based_on: dict[str, list["MemoryFact"] | list[dict[str, Any]]],
        tool_trace: list[Any] | None = None,
    ) -> None:
        """Best-effort telemetry update from reflect `based_on` artifacts."""
        try:
            # Dedup within a single reflect operation for stable, meaningful counts.
            fact_ids_seen: set[str] = set()
            chunk_ids_seen: set[str] = set()
            model_ids_seen: set[str] = set()

            def _add(target: set[str], raw_id: object) -> None:
                if not raw_id:
                    return
                key = str(raw_id)
                if key:
                    target.add(key)

            for fact_type, facts in based_on.items():
                for fact in facts:
                    if isinstance(fact, dict):
                        item_id = fact.get("id")
                        chunk_id = fact.get("chunk_id")
                    else:
                        item_id = getattr(fact, "id", None)
                        chunk_id = getattr(fact, "chunk_id", None)

                    if fact_type == "mental-models":
                        _add(model_ids_seen, item_id)
                    elif fact_type != "directives":
                        _add(fact_ids_seen, item_id)

            # Count only chunks that were explicitly expanded/materialized by reflect tools.
            for tc in tool_trace or []:
                output = getattr(tc, "output", None) or {}
                if not isinstance(output, dict):
                    continue
                if tc.tool == "recall":
                    for chunk_id in (output.get("chunks") or {}).keys():
                        _add(chunk_ids_seen, chunk_id)
                elif tc.tool == "expand":
                    for row in output.get("results") or []:
                        if isinstance(row, dict):
                            chunk_obj = row.get("chunk")
                            if isinstance(chunk_obj, dict):
                                _add(chunk_ids_seen, chunk_obj.get("id"))

            fact_counts = {fid: 1 for fid in fact_ids_seen}
            chunk_counts = {cid: 1 for cid in chunk_ids_seen}
            mental_model_counts = {mid: 1 for mid in model_ids_seen}

            await self._apply_access_count_updates(
                bank_id=bank_id,
                fact_counts=fact_counts,
                chunk_counts=chunk_counts,
                mental_model_counts=mental_model_counts,
            )
        except Exception as e:
            logger.warning("reflect access telemetry update skipped for bank=%s: %s", bank_id, e)

    async def _search_with_retries(
        self,
        bank_id: str,
        query: str,
        fact_type: list[str],
        thinking_budget: int,
        max_tokens: int,
        enable_trace: bool,
        question_date: datetime | None = None,
        include_entities: bool = False,
        max_entity_tokens: int = 500,
        include_chunks: bool = False,
        max_chunk_tokens: int = 8192,
        request_context: "RequestContext" = None,
        semaphore_wait: float = 0.0,
        tags: list[str] | None = None,
        tags_match: TagsMatch = "any",
        connection_budget: int | None = None,
        quiet: bool = False,
        include_source_facts: bool = False,
        max_source_facts_tokens: int = 4096,
        max_source_facts_tokens_per_observation: int = -1,
    ) -> RecallResultModel:
        """
        Search implementation with modular retrieval and reranking.

        Architecture:
        1. Retrieval: 4-way parallel (semantic, keyword, graph, temporal graph)
        2. Merge: RRF to combine ranked lists
        3. Reranking: Pluggable strategy (heuristic or cross-encoder)
        4. Diversity: MMR with λ=0.5
        5. Chunks: Fetch chunks from top-scored results (BEFORE token filtering)
        6. Token Filter: Limit facts to max_tokens budget

        Args:
            bank_id: bank IDentifier
            query: Search query
            fact_type: Type of facts to search
            thinking_budget: Nodes to explore in graph traversal
            max_tokens: Maximum tokens to return (counts only 'text' field)
            enable_trace: Whether to return search trace (deprecated)
            include_entities: Whether to include entity observations
            max_entity_tokens: Maximum tokens for entity observations
            include_chunks: Whether to include raw chunks (fetched before max_tokens filtering)
            max_chunk_tokens: Maximum tokens for chunks

        Returns:
            RecallResultModel with results, trace, optional entities, and optional chunks
        """
        # Initialize tracer if requested
        from .search.tracer import SearchTracer

        tracer = (
            SearchTracer(query, thinking_budget, max_tokens, tags=tags, tags_match=tags_match) if enable_trace else None
        )
        if tracer:
            tracer.start()

        pool = await self._get_pool()
        recall_start = time.time()

        # Buffer logs for clean output in concurrent scenarios
        recall_id = f"{bank_id[:8]}-{int(time.time() * 1000) % 100000}"
        log_buffer = []
        tags_info = f", tags={tags}, tags_match={tags_match}" if tags else ""
        log_buffer.append(
            f"[RECALL {recall_id}] Query: '{query[:50]}...' (budget={thinking_budget}, max_tokens={max_tokens}{tags_info})"
        )

        # Import tracing utilities
        from ..tracing import get_tracer

        tracer_otel = get_tracer()

        try:
            # Step 1: Generate query embedding (for semantic search)
            step_start = time.time()

            embedding_span = tracer_otel.start_span("atulya.recall_embedding")
            embedding_span.set_attribute("atulya.bank_id", bank_id)
            embedding_span.set_attribute("atulya.query", query[:100])

            try:
                query_embedding = embedding_utils.generate_embedding(self.embeddings, query)
                step_duration = time.time() - step_start
                log_buffer.append(f"  [1] Generate query embedding: {step_duration:.3f}s")
            finally:
                embedding_span.end()

            if tracer:
                tracer.record_query_embedding(query_embedding)
                tracer.add_phase_metric("generate_query_embedding", step_duration)

            # Step 2: Optimized parallel retrieval using batched queries
            # - Semantic + BM25 combined in 1 CTE query for ALL fact types
            # - Graph runs per fact type (complex traversal)
            # - Temporal runs per fact type (if constraint detected)
            step_start = time.time()
            query_embedding_str = str(query_embedding)

            from .search.retrieval import (
                get_default_graph_retriever,
                retrieve_all_fact_types_parallel,
            )

            # Track each retrieval start time
            retrieval_start = time.time()

            retrieval_span = tracer_otel.start_span("atulya.recall_retrieval")
            retrieval_span.set_attribute("atulya.bank_id", bank_id)
            retrieval_span.set_attribute("atulya.fact_types", ",".join(fact_type))
            retrieval_span.set_attribute("atulya.thinking_budget", thinking_budget)

            try:
                # Run optimized retrieval with connection budget
                config = get_config()
                effective_connection_budget = (
                    connection_budget if connection_budget is not None else config.recall_connection_budget
                )
                async with budgeted_operation(
                    max_connections=effective_connection_budget,
                    operation_id=f"recall-{recall_id}",
                ) as op:
                    budgeted_pool = op.wrap_pool(pool)
                    parallel_start = time.time()
                    multi_result = await retrieve_all_fact_types_parallel(
                        budgeted_pool,
                        query,
                        query_embedding_str,
                        bank_id,
                        fact_type,  # Pass all fact types at once
                        thinking_budget,
                        question_date,
                        self.query_analyzer,
                        tags=tags,
                        tags_match=tags_match,
                    )
                    parallel_duration = time.time() - parallel_start
            finally:
                retrieval_span.end()

            # Combine all results from all fact types and aggregate timings
            semantic_results = []
            bm25_results = []
            graph_results = []
            temporal_results = []
            aggregated_timings = {
                "semantic": 0.0,
                "bm25": 0.0,
                "graph": 0.0,
                "temporal": 0.0,
                "temporal_extraction": 0.0,
            }
            all_mpfp_timings = []

            detected_temporal_constraint = None
            max_conn_wait = multi_result.max_conn_wait
            for ft in fact_type:
                retrieval_result = multi_result.results_by_fact_type.get(ft)
                if not retrieval_result:
                    continue

                # Log fact types in this retrieval batch
                logger.debug(
                    f"[RECALL {recall_id}] Fact type '{ft}': semantic={len(retrieval_result.semantic)}, bm25={len(retrieval_result.bm25)}, graph={len(retrieval_result.graph)}, temporal={len(retrieval_result.temporal) if retrieval_result.temporal else 0}"
                )

                semantic_results.extend(retrieval_result.semantic)
                bm25_results.extend(retrieval_result.bm25)
                graph_results.extend(retrieval_result.graph)
                if retrieval_result.temporal:
                    temporal_results.extend(retrieval_result.temporal)
                # Track max timing for each method (since they run in parallel across fact types)
                for method, duration in retrieval_result.timings.items():
                    aggregated_timings[method] = max(aggregated_timings.get(method, 0.0), duration)
                # Capture temporal constraint (same across all fact types)
                if retrieval_result.temporal_constraint:
                    detected_temporal_constraint = retrieval_result.temporal_constraint

            # If no temporal results from any fact type, set to None
            if not temporal_results:
                temporal_results = None

            # Sort combined results by score (descending) so higher-scored results
            # get better ranks in the trace, regardless of fact type
            semantic_results.sort(key=lambda r: r.similarity if hasattr(r, "similarity") else 0, reverse=True)
            bm25_results.sort(key=lambda r: r.bm25_score if hasattr(r, "bm25_score") else 0, reverse=True)
            graph_results.sort(key=lambda r: r.activation if hasattr(r, "activation") else 0, reverse=True)
            if temporal_results:
                temporal_results.sort(
                    key=lambda r: r.combined_score if hasattr(r, "combined_score") else 0, reverse=True
                )

            retrieval_duration = time.time() - retrieval_start

            step_duration = time.time() - step_start
            total_retrievals = len(fact_type) * (4 if temporal_results else 3)
            # Format per-method timings
            timing_parts = [
                f"semantic={len(semantic_results)}({aggregated_timings['semantic']:.3f}s)",
                f"bm25={len(bm25_results)}({aggregated_timings['bm25']:.3f}s)",
                f"graph={len(graph_results)}({aggregated_timings['graph']:.3f}s)",
                f"temporal_extraction={aggregated_timings['temporal_extraction']:.3f}s",
            ]
            temporal_info = ""
            if detected_temporal_constraint:
                start_dt, end_dt = detected_temporal_constraint
                temporal_count = len(temporal_results) if temporal_results else 0
                timing_parts.append(f"temporal={temporal_count}({aggregated_timings['temporal']:.3f}s)")
                temporal_info = f" | temporal_range={start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}"
            log_buffer.append(
                f"  [2] Parallel retrieval ({len(fact_type)} fact_types): {', '.join(timing_parts)} in {parallel_duration:.3f}s{temporal_info}"
            )

            # Log graph retriever timing breakdown if available
            if all_mpfp_timings:
                retriever_name = get_default_graph_retriever().name.upper()
                mpfp_total = all_mpfp_timings[0]  # Take first fact type's timing as representative
                mpfp_parts = [
                    f"db_queries={mpfp_total.db_queries}",
                    f"edge_load={mpfp_total.edge_load_time:.3f}s",
                    f"edges={mpfp_total.edge_count}",
                    f"patterns={mpfp_total.pattern_count}",
                ]
                if mpfp_total.seeds_time > 0.01:
                    mpfp_parts.append(f"seeds={mpfp_total.seeds_time:.3f}s")
                if mpfp_total.fusion > 0.001:
                    mpfp_parts.append(f"fusion={mpfp_total.fusion:.3f}s")
                if mpfp_total.fetch > 0.001:
                    mpfp_parts.append(f"fetch={mpfp_total.fetch:.3f}s")
                log_buffer.append(f"      [{retriever_name}] {', '.join(mpfp_parts)}")
                # Log detailed hop timing for debugging slow queries
                if mpfp_total.hop_details:
                    for hd in mpfp_total.hop_details:
                        log_buffer.append(
                            f"        hop{hd['hop']}: exec={hd.get('exec_time', 0) * 1000:.0f}ms, "
                            f"uncached={hd.get('uncached_after_filter', 0)}, "
                            f"load={hd.get('load_time', 0) * 1000:.0f}ms, "
                            f"edges={hd.get('edges_loaded', 0)}"
                        )

            # Record temporal constraint in tracer if detected
            if tracer and detected_temporal_constraint:
                start_dt, end_dt = detected_temporal_constraint
                tracer.record_temporal_constraint(start_dt, end_dt)

            # Record retrieval results for tracer - per fact type
            if tracer:
                # Convert RetrievalResult to old tuple format for tracer
                def to_tuple_format(results):
                    return [(r.id, r.__dict__) for r in results]

                # Add retrieval results per fact type (to show parallel execution in UI)
                for ft_name in fact_type:
                    rr = multi_result.results_by_fact_type.get(ft_name)
                    if not rr:
                        continue

                    # Add semantic retrieval results for this fact type
                    tracer.add_retrieval_results(
                        method_name="semantic",
                        results=to_tuple_format(rr.semantic),
                        duration_seconds=rr.timings.get("semantic", 0.0),
                        score_field="similarity",
                        metadata={"limit": thinking_budget},
                        fact_type=ft_name,
                    )

                    # Add BM25 retrieval results for this fact type
                    tracer.add_retrieval_results(
                        method_name="bm25",
                        results=to_tuple_format(rr.bm25),
                        duration_seconds=rr.timings.get("bm25", 0.0),
                        score_field="bm25_score",
                        metadata={"limit": thinking_budget},
                        fact_type=ft_name,
                    )

                    # Add graph retrieval results for this fact type
                    tracer.add_retrieval_results(
                        method_name="graph",
                        results=to_tuple_format(rr.graph),
                        duration_seconds=rr.timings.get("graph", 0.0),
                        score_field="activation",
                        metadata={"budget": thinking_budget},
                        fact_type=ft_name,
                    )

                    # Add temporal retrieval results for this fact type
                    # Show temporal even with 0 results if constraint was detected
                    if rr.temporal is not None or rr.temporal_constraint is not None:
                        temporal_metadata = {"budget": thinking_budget}
                        if rr.temporal_constraint:
                            start_dt, end_dt = rr.temporal_constraint
                            temporal_metadata["constraint"] = {
                                "start": start_dt.isoformat() if start_dt else None,
                                "end": end_dt.isoformat() if end_dt else None,
                            }
                        tracer.add_retrieval_results(
                            method_name="temporal",
                            results=to_tuple_format(rr.temporal or []),
                            duration_seconds=rr.timings.get("temporal", 0.0),
                            score_field="temporal_score",
                            metadata=temporal_metadata,
                            fact_type=ft_name,
                        )

                # Record entry points (from semantic results) for legacy graph view
                for rank, retrieval in enumerate(semantic_results[:10], start=1):  # Top 10 as entry points
                    tracer.add_entry_point(retrieval.id, retrieval.text, retrieval.similarity or 0.0, rank)

                tracer.add_phase_metric(
                    "parallel_retrieval",
                    step_duration,
                    {
                        "semantic_count": len(semantic_results),
                        "bm25_count": len(bm25_results),
                        "graph_count": len(graph_results),
                        "temporal_count": len(temporal_results) if temporal_results else 0,
                    },
                )
                # Also expose each retrieval method as its own phase so
                # benchmarks can pinpoint which sub-query drives latency.
                for _method, _dur in aggregated_timings.items():
                    if _dur > 0:
                        tracer.add_phase_metric(f"retrieval_{_method}", _dur)

            # Step 3: Merge with RRF
            step_start = time.time()
            from .search.fusion import reciprocal_rank_fusion

            fusion_span = tracer_otel.start_span("atulya.recall_fusion")
            fusion_span.set_attribute("atulya.bank_id", bank_id)
            fusion_span.set_attribute("atulya.semantic_count", len(semantic_results))
            fusion_span.set_attribute("atulya.bm25_count", len(bm25_results))
            fusion_span.set_attribute("atulya.graph_count", len(graph_results))
            fusion_span.set_attribute("atulya.temporal_count", len(temporal_results) if temporal_results else 0)

            try:
                # Merge 3 or 4 result lists depending on temporal constraint
                if temporal_results:
                    merged_candidates = reciprocal_rank_fusion(
                        [semantic_results, bm25_results, graph_results, temporal_results]
                    )
                else:
                    merged_candidates = reciprocal_rank_fusion([semantic_results, bm25_results, graph_results])

                step_duration = time.time() - step_start
                log_buffer.append(
                    f"  [3] RRF merge: {len(merged_candidates)} unique candidates in {step_duration:.3f}s"
                )
            finally:
                fusion_span.set_attribute("atulya.merged_count", len(merged_candidates))
                fusion_span.end()

            if tracer:
                # Convert MergedCandidate to old tuple format for tracer
                tracer_merged = [
                    (mc.id, mc.retrieval.__dict__, {"rrf_score": mc.rrf_score, **mc.source_ranks})
                    for mc in merged_candidates
                ]
                tracer.add_rrf_merged(tracer_merged)
                tracer.add_phase_metric("rrf_merge", step_duration, {"candidates_merged": len(merged_candidates)})

            # Step 4: Rerank using cross-encoder (MergedCandidate -> ScoredResult)
            step_start = time.time()
            reranker_instance = self._cross_encoder_reranker

            rerank_span = tracer_otel.start_span("atulya.recall_rerank")
            rerank_span.set_attribute("atulya.bank_id", bank_id)
            rerank_span.set_attribute("atulya.candidates_count", len(merged_candidates))

            scored_results: list = []
            pre_filtered_count = 0
            try:
                # Ensure reranker is initialized (for lazy initialization mode)
                await reranker_instance.ensure_initialized()

                # Pre-filter candidates to reduce reranking cost (RRF already provides good ranking)
                # This is especially important for remote rerankers with network latency
                reranker_max_candidates = get_config().reranker_max_candidates
                if len(merged_candidates) > reranker_max_candidates:
                    # Sort by RRF score and take top candidates
                    merged_candidates.sort(key=lambda mc: mc.rrf_score, reverse=True)
                    pre_filtered_count = len(merged_candidates) - reranker_max_candidates
                    merged_candidates = merged_candidates[:reranker_max_candidates]

                # Rerank using cross-encoder
                scored_results = await reranker_instance.rerank(query, merged_candidates)

                step_duration = time.time() - step_start
                pre_filter_note = f" (pre-filtered {pre_filtered_count})" if pre_filtered_count > 0 else ""
                log_buffer.append(
                    f"  [4] Reranking: {len(scored_results)} candidates scored in {step_duration:.3f}s{pre_filter_note}"
                )
            finally:
                rerank_span.set_attribute("atulya.scored_count", len(scored_results))
                if pre_filtered_count > 0:
                    rerank_span.set_attribute("atulya.pre_filtered_count", pre_filtered_count)
                rerank_span.end()

            # Step 4.5: Combine cross-encoder score with retrieval signals via multiplicative boosts.
            # See apply_combined_scoring for the full rationale and formula.
            if scored_results:
                apply_combined_scoring(scored_results, now=utcnow())
                scored_results.sort(key=lambda x: x.weight, reverse=True)
                log_buffer.append("  [4.6] Combined scoring: ce * recency_boost(0.2) * temporal_boost(0.2)")

            # Add reranked results to tracer AFTER combined scoring (so normalized values are included)
            if tracer:
                results_dict = [sr.to_dict() for sr in scored_results]
                tracer_merged = [
                    (mc.id, mc.retrieval.__dict__, {"rrf_score": mc.rrf_score, **mc.source_ranks})
                    for mc in merged_candidates
                ]
                tracer.add_reranked(results_dict, tracer_merged)
                tracer.add_phase_metric(
                    "reranking",
                    step_duration,
                    {"reranker_type": "cross-encoder", "candidates_reranked": len(scored_results)},
                )

            # Step 5: Truncate to thinking_budget * 2 for token filtering
            rerank_limit = thinking_budget * 2
            top_scored = scored_results[:rerank_limit]
            log_buffer.append(f"  [5] Truncated to top {len(top_scored)} results")

            # Step 5.5: Fetch chunks from top-scored results (before token filtering)
            # Chunks are fetched independently of max_tokens filtering
            chunks_dict = None
            total_chunk_tokens = 0
            if include_chunks and top_scored:
                from .response_models import ChunkInfo

                # Collect chunk_ids in order of fact relevance (preserving order from top_scored).
                # Observations have no direct chunk_id — use a placeholder so their source
                # chunks end up at the observation's rank position, not appended at the end.
                # ordered_items: list of ('chunk', chunk_id) | ('obs', sr.id)
                ordered_items: list[tuple[str, str]] = []
                seen_chunk_ids: set[str] = set()
                observation_ids_ordered: list[uuid.UUID] = []
                for sr in top_scored:
                    chunk_id = sr.retrieval.chunk_id
                    if chunk_id and chunk_id not in seen_chunk_ids:
                        ordered_items.append(("chunk", chunk_id))
                        seen_chunk_ids.add(chunk_id)
                    elif not chunk_id and sr.retrieval.fact_type == "observation":
                        ordered_items.append(("obs", sr.id))
                        observation_ids_ordered.append(uuid.UUID(sr.id))

                # Resolve source chunk_ids for all observations in a single query,
                # ordered by observation rank so per-observation results stay grouped correctly.
                obs_chunk_ids: dict[str, list[str]] = {}
                if observation_ids_ordered:
                    async with acquire_with_retry(pool) as obs_conn:
                        obs_source_rows = await obs_conn.fetch(
                            f"""
                            SELECT obs.id AS obs_id, mu.chunk_id
                            FROM {fq_table("memory_units")} obs
                            JOIN {fq_table("memory_units")} mu
                              ON mu.id = ANY(obs.source_memory_ids)
                            WHERE obs.id = ANY($1::uuid[])
                              AND mu.chunk_id IS NOT NULL
                            ORDER BY array_position($1::uuid[], obs.id)
                            """,
                            observation_ids_ordered,
                        )
                    for row in obs_source_rows:
                        obs_id = str(row["obs_id"])
                        cid = row["chunk_id"]
                        if cid not in seen_chunk_ids:
                            obs_chunk_ids.setdefault(obs_id, []).append(cid)
                            seen_chunk_ids.add(cid)

                # Flatten ordered_items into chunk_ids_ordered, expanding obs placeholders
                chunk_ids_ordered = []
                for item_type, item_id in ordered_items:
                    if item_type == "chunk":
                        chunk_ids_ordered.append(item_id)
                    else:
                        chunk_ids_ordered.extend(obs_chunk_ids.get(item_id, []))

                if chunk_ids_ordered:
                    chunks_dict = {}
                    encoding = _get_tiktoken_encoding()

                    # Fetch all candidate chunks in a single query. Token-budget accounting
                    # happens in Python after the fetch — one round-trip is always faster
                    # than multiple batched round-trips when the candidate set is large.
                    async with acquire_with_retry(pool) as conn:
                        chunks_rows = await conn.fetch(
                            f"""
                            SELECT chunk_id, chunk_text, chunk_index
                            FROM {fq_table("chunks")}
                            WHERE chunk_id = ANY($1::text[])
                            """,
                            chunk_ids_ordered,
                        )

                    chunks_lookup = {row["chunk_id"]: row for row in chunks_rows}

                    # Process chunks in relevance order, respecting token budget
                    for chunk_id in chunk_ids_ordered:
                        if chunk_id not in chunks_lookup:
                            continue

                        row = chunks_lookup[chunk_id]
                        chunk_text = row["chunk_text"]
                        chunk_tokens = len(encoding.encode(chunk_text))

                        if total_chunk_tokens + chunk_tokens > max_chunk_tokens:
                            remaining_tokens = max_chunk_tokens - total_chunk_tokens
                            if remaining_tokens > 0:
                                truncated_text = encoding.decode(encoding.encode(chunk_text)[:remaining_tokens])
                                chunks_dict[chunk_id] = ChunkInfo(
                                    chunk_text=truncated_text, chunk_index=row["chunk_index"], truncated=True
                                )
                                total_chunk_tokens = max_chunk_tokens
                            break
                        else:
                            chunks_dict[chunk_id] = ChunkInfo(
                                chunk_text=chunk_text, chunk_index=row["chunk_index"], truncated=False
                            )
                            total_chunk_tokens += chunk_tokens

            # Step 6: Token budget filtering
            step_start = time.time()

            # Convert to dict for token filtering (backward compatibility)
            top_dicts = [sr.to_dict() for sr in top_scored]
            filtered_dicts, total_tokens = self._filter_by_token_budget(top_dicts, max_tokens)

            # Convert back to list of IDs and filter scored_results
            filtered_ids = {d["id"] for d in filtered_dicts}
            top_scored = [sr for sr in top_scored if sr.id in filtered_ids]

            step_duration = time.time() - step_start
            log_buffer.append(
                f"  [6] Token filtering: {len(top_scored)} results, {total_tokens}/{max_tokens} tokens in {step_duration:.3f}s"
            )

            if tracer:
                tracer.add_phase_metric(
                    "token_filtering",
                    step_duration,
                    {"results_selected": len(top_scored), "tokens_used": total_tokens, "max_tokens": max_tokens},
                )

            # Record visits for all retrieved nodes
            if tracer:
                for sr in scored_results:
                    tracer.visit_node(
                        node_id=sr.id,
                        text=sr.retrieval.text,
                        context=sr.retrieval.context or "",
                        event_date=sr.retrieval.occurred_start,
                        is_entry_point=(sr.id in [ep.node_id for ep in tracer.entry_points]),
                        parent_node_id=None,  # In parallel retrieval, there's no clear parent
                        link_type=None,
                        link_weight=None,
                        activation=sr.candidate.rrf_score,  # Use RRF score as activation
                        semantic_similarity=sr.retrieval.similarity or 0.0,
                        recency=sr.recency,
                        frequency=0.0,
                        final_weight=sr.weight,
                    )

            # Log fact_type distribution in results
            fact_type_counts = {}
            for sr in top_scored:
                ft = sr.retrieval.fact_type
                fact_type_counts[ft] = fact_type_counts.get(ft, 0) + 1

            fact_type_summary = ", ".join([f"{ft}={count}" for ft, count in sorted(fact_type_counts.items())])

            # Convert ScoredResult to dicts with ISO datetime strings
            top_results_dicts = []
            for sr in top_scored:
                result_dict = sr.to_dict()
                # Convert datetime objects to ISO strings for JSON serialization
                if result_dict.get("occurred_start"):
                    occurred_start = result_dict["occurred_start"]
                    result_dict["occurred_start"] = (
                        occurred_start.isoformat() if hasattr(occurred_start, "isoformat") else occurred_start
                    )
                if result_dict.get("occurred_end"):
                    occurred_end = result_dict["occurred_end"]
                    result_dict["occurred_end"] = (
                        occurred_end.isoformat() if hasattr(occurred_end, "isoformat") else occurred_end
                    )
                if result_dict.get("mentioned_at"):
                    mentioned_at = result_dict["mentioned_at"]
                    result_dict["mentioned_at"] = (
                        mentioned_at.isoformat() if hasattr(mentioned_at, "isoformat") else mentioned_at
                    )
                top_results_dicts.append(result_dict)

            # Fetch source facts for observation-type results (mirrors chunks pattern)
            source_fact_ids_by_obs: dict[str, list[str]] = {}  # obs_id -> [source_id, ...]
            source_facts_dict: dict[str, MemoryFact] | None = None
            if include_source_facts:
                observation_ids = [uuid.UUID(sr.id) for sr in top_scored if sr.retrieval.fact_type == "observation"]
                if observation_ids:
                    async with acquire_with_retry(pool) as sf_conn:
                        # Fetch source_memory_ids for all observation results
                        obs_rows = await sf_conn.fetch(
                            f"""
                            SELECT id, source_memory_ids
                            FROM {fq_table("memory_units")}
                            WHERE id = ANY($1::uuid[]) AND fact_type = 'observation'
                            """,
                            observation_ids,
                        )

                        # Collect unique source IDs in order of first appearance
                        seen_source_ids: set[str] = set()
                        source_ids_ordered: list[str] = []
                        for obs_row in obs_rows:
                            obs_id = str(obs_row["id"])
                            sids = [str(s) for s in (obs_row["source_memory_ids"] or [])]
                            source_fact_ids_by_obs[obs_id] = sids
                            for sid in sids:
                                if sid not in seen_source_ids:
                                    source_ids_ordered.append(sid)
                                    seen_source_ids.add(sid)

                        # Fetch source fact content up to token budget
                        if source_ids_ordered:
                            import uuid as uuid_module

                            source_rows = await sf_conn.fetch(
                                f"""
                                SELECT id, text, fact_type, context, occurred_start, occurred_end,
                                       mentioned_at, document_id, chunk_id, tags
                                FROM {fq_table("memory_units")}
                                WHERE id = ANY($1::uuid[])
                                """,
                                [uuid_module.UUID(sid) for sid in source_ids_ordered],
                            )
                            source_row_by_id = {str(r["id"]): r for r in source_rows}

                            encoding = _get_tiktoken_encoding()
                            source_facts_dict = {}

                            def _make_source_fact(sid: str, r: Any) -> MemoryFact:
                                return MemoryFact(
                                    id=sid,
                                    text=r["text"],
                                    fact_type=r["fact_type"],
                                    context=r["context"],
                                    occurred_start=r["occurred_start"].isoformat() if r["occurred_start"] else None,
                                    occurred_end=r["occurred_end"].isoformat() if r["occurred_end"] else None,
                                    mentioned_at=r["mentioned_at"].isoformat() if r["mentioned_at"] else None,
                                    document_id=r["document_id"],
                                    chunk_id=str(r["chunk_id"]) if r["chunk_id"] else None,
                                    tags=r["tags"] or None,
                                )

                            if max_source_facts_tokens_per_observation >= 0:
                                # Per-observation capping: each observation independently selects
                                # source facts up to its token budget.
                                for obs_id, sids in source_fact_ids_by_obs.items():
                                    obs_tokens = 0
                                    for sid in sids:
                                        if sid not in source_row_by_id:
                                            continue
                                        r = source_row_by_id[sid]
                                        fact_tokens = len(encoding.encode(r["text"]))
                                        if obs_tokens + fact_tokens > max_source_facts_tokens_per_observation:
                                            break
                                        obs_tokens += fact_tokens
                                        if sid not in source_facts_dict:
                                            source_facts_dict[sid] = _make_source_fact(sid, r)
                            else:
                                # Global budget: fill in order of first appearance until exhausted.
                                total_source_tokens = 0
                                for sid in source_ids_ordered:
                                    if sid not in source_row_by_id:
                                        continue
                                    r = source_row_by_id[sid]
                                    fact_tokens = len(encoding.encode(r["text"]))
                                    if (
                                        max_source_facts_tokens >= 0
                                        and total_source_tokens + fact_tokens > max_source_facts_tokens
                                    ):
                                        break
                                    source_facts_dict[sid] = _make_source_fact(sid, r)
                                    total_source_tokens += fact_tokens

            # Get entities for each fact if include_entities is requested
            fact_entity_map = {}  # unit_id -> list of (entity_id, entity_name)
            if include_entities and top_scored:
                unit_ids = [uuid.UUID(sr.id) for sr in top_scored]
                if unit_ids:
                    async with acquire_with_retry(pool) as entity_conn:
                        entity_rows = await entity_conn.fetch(
                            f"""
                            SELECT ue.unit_id, e.id as entity_id, e.canonical_name
                            FROM {fq_table("unit_entities")} ue
                            JOIN {fq_table("entities")} e ON ue.entity_id = e.id
                            WHERE ue.unit_id = ANY($1::uuid[])
                            """,
                            unit_ids,
                        )
                        for row in entity_rows:
                            unit_id = str(row["unit_id"])
                            if unit_id not in fact_entity_map:
                                fact_entity_map[unit_id] = []
                            fact_entity_map[unit_id].append(
                                {"entity_id": str(row["entity_id"]), "canonical_name": row["canonical_name"]}
                            )

            # Convert results to MemoryFact objects
            memory_facts = []
            for result_dict in top_results_dicts:
                result_id = str(result_dict.get("id"))
                # Get entity names for this fact
                entity_names = None
                if include_entities and result_id in fact_entity_map:
                    entity_names = [e["canonical_name"] for e in fact_entity_map[result_id]]

                memory_facts.append(
                    MemoryFact(
                        id=result_id,
                        text=result_dict.get("text"),
                        fact_type=result_dict.get("fact_type", "world"),
                        entities=entity_names,
                        context=result_dict.get("context"),
                        occurred_start=result_dict.get("occurred_start"),
                        occurred_end=result_dict.get("occurred_end"),
                        mentioned_at=result_dict.get("mentioned_at"),
                        document_id=result_dict.get("document_id"),
                        chunk_id=result_dict.get("chunk_id"),
                        tags=result_dict.get("tags"),
                        source_fact_ids=source_fact_ids_by_obs.get(result_id) if include_source_facts else None,
                    )
                )

            # Fetch entity observations if requested
            entities_dict = None
            total_entity_tokens = 0
            if include_entities and fact_entity_map:
                # Collect unique entities in order of fact relevance (preserving order from top_scored)
                entities_ordered = []  # list of (entity_id, entity_name) tuples
                seen_entity_ids = set()

                for sr in top_scored:
                    unit_id = sr.id
                    if unit_id in fact_entity_map:
                        for entity in fact_entity_map[unit_id]:
                            entity_id = entity["entity_id"]
                            entity_name = entity["canonical_name"]
                            if entity_id not in seen_entity_ids:
                                entities_ordered.append((entity_id, entity_name))
                                seen_entity_ids.add(entity_id)

                # Return entities with empty observations (summaries now live in mental models)
                entities_dict = {}
                for entity_id, entity_name in entities_ordered:
                    entities_dict[entity_name] = EntityState(
                        entity_id=entity_id,
                        canonical_name=entity_name,
                        observations=[],  # Mental models provide this now
                    )

            # Finalize trace if enabled
            trace_dict = None
            if tracer:
                trace = tracer.finalize(top_results_dicts)
                trace_dict = trace.to_dict() if trace else None

            # Log final recall stats
            total_time = time.time() - recall_start
            num_chunks = len(chunks_dict) if chunks_dict else 0
            num_entities = len(entities_dict) if entities_dict else 0
            # Include wait times in log if significant
            wait_parts = []
            if semaphore_wait > 0.01:
                wait_parts.append(f"sem={semaphore_wait:.3f}s")
            if max_conn_wait > 0.01:
                wait_parts.append(f"conn={max_conn_wait:.3f}s")
            wait_info = f" | waits: {', '.join(wait_parts)}" if wait_parts else ""
            log_buffer.append(
                f"[RECALL {recall_id}] Complete: {len(top_scored)} facts ({total_tokens} tok), {num_chunks} chunks ({total_chunk_tokens} tok), {num_entities} entities ({total_entity_tokens} tok) | {fact_type_summary} | {total_time:.3f}s{wait_info}"
            )
            if not quiet:
                logger.info("\n" + "\n".join(log_buffer))

            return RecallResultModel(
                results=memory_facts,
                trace=trace_dict,
                entities=entities_dict,
                chunks=chunks_dict,
                source_facts=source_facts_dict,
            )

        except Exception as e:
            log_buffer.append(f"[RECALL {recall_id}] ERROR after {time.time() - recall_start:.3f}s: {str(e)}")
            if not quiet:
                logger.error("\n" + "\n".join(log_buffer))
            raise Exception(f"Failed to search memories: {str(e)}")

    def _filter_by_token_budget(
        self, results: list[dict[str, Any]], max_tokens: int
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Filter results to fit within token budget.

        Counts tokens only for the 'text' field using tiktoken (cl100k_base encoding).
        Stops before including a fact that would exceed the budget.

        Args:
            results: List of search results
            max_tokens: Maximum tokens allowed

        Returns:
            Tuple of (filtered_results, total_tokens_used)
        """
        encoding = _get_tiktoken_encoding()

        filtered_results = []
        total_tokens = 0

        for result in results:
            text = result.get("text", "")
            text_tokens = len(encoding.encode(text))

            # Check if adding this result would exceed budget
            if total_tokens + text_tokens <= max_tokens:
                filtered_results.append(result)
                total_tokens += text_tokens
            else:
                # Stop before including a fact that would exceed limit
                break

        return filtered_results, total_tokens

    async def get_document(
        self,
        document_id: str,
        bank_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any] | None:
        """
        Retrieve document metadata and statistics.

        Args:
            document_id: Document ID to retrieve
            bank_id: bank ID that owns the document
            request_context: Request context for authentication.

        Returns:
            Dictionary with document info or None if not found
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_document", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            doc = await conn.fetchrow(
                f"""
                SELECT d.id, d.bank_id, d.original_text, d.content_hash,
                       d.created_at, d.updated_at, d.tags, COUNT(mu.id) as unit_count
                FROM {fq_table("documents")} d
                LEFT JOIN {fq_table("memory_units")} mu ON mu.document_id = d.id
                WHERE d.id = $1 AND d.bank_id = $2
                GROUP BY d.id, d.bank_id, d.original_text, d.content_hash, d.created_at, d.updated_at, d.tags
                """,
                document_id,
                bank_id,
            )

            if not doc:
                return None

            return {
                "id": doc["id"],
                "bank_id": doc["bank_id"],
                "original_text": doc["original_text"],
                "content_hash": doc["content_hash"],
                "memory_unit_count": doc["unit_count"],
                "created_at": doc["created_at"].isoformat() if doc["created_at"] else None,
                "updated_at": doc["updated_at"].isoformat() if doc["updated_at"] else None,
                "tags": list(doc["tags"]) if doc["tags"] else [],
            }

    async def delete_document(
        self,
        document_id: str,
        bank_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, int]:
        """
        Delete a document and all its associated memory units and links.

        Args:
            document_id: Document ID to delete
            bank_id: bank ID that owns the document
            request_context: Request context for authentication.

        Returns:
            Dictionary with counts of deleted items
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="delete_document", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()
        invalidated_obs = 0
        async with acquire_with_retry(pool) as conn:
            async with conn.transaction():
                # Get memory unit IDs before deletion (for observation cleanup)
                unit_rows = await conn.fetch(
                    f"SELECT id FROM {fq_table('memory_units')} WHERE document_id = $1 AND fact_type IN ('experience', 'world')",
                    document_id,
                )
                unit_ids = [str(row["id"]) for row in unit_rows]
                units_count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {fq_table('memory_units')} WHERE document_id = $1", document_id
                )

                # Invalidate observations referencing these memories before deletion
                if unit_ids:
                    invalidated_obs = await self._delete_stale_observations_for_memories(conn, bank_id, unit_ids)

                # Delete document (cascades to memory_units and all their links)
                deleted = await conn.fetchval(
                    f"DELETE FROM {fq_table('documents')} WHERE id = $1 AND bank_id = $2 RETURNING id",
                    document_id,
                    bank_id,
                )

                result = {
                    "document_deleted": 1 if deleted else 0,
                    "memory_units_deleted": units_count if deleted else 0,
                }

        if invalidated_obs > 0:
            await self.submit_async_consolidation(bank_id=bank_id, request_context=request_context)

        return result

    async def delete_memory_unit(
        self,
        unit_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """
        Delete a single memory unit and all its associated links.

        Due to CASCADE DELETE constraints, this will automatically delete:
        - All links from this unit (memory_links where from_unit_id = unit_id)
        - All links to this unit (memory_links where to_unit_id = unit_id)
        - All entity associations (unit_entities where unit_id = unit_id)

        Observations referencing this memory are deleted and their other source
        memories are reset for re-consolidation.

        Args:
            unit_id: UUID of the memory unit to delete
            request_context: Request context for authentication.

        Returns:
            Dictionary with deletion result
        """
        await self._authenticate_tenant(request_context)
        pool = await self._get_pool()
        invalidated_obs = 0
        bank_id_for_consolidation: str | None = None
        async with acquire_with_retry(pool) as conn:
            async with conn.transaction():
                # Get bank_id and fact_type before deletion
                row = await conn.fetchrow(
                    f"SELECT bank_id, fact_type FROM {fq_table('memory_units')} WHERE id = $1",
                    unit_id,
                )
                bank_id = row["bank_id"] if row else None
                fact_type = row["fact_type"] if row else None

                # Invalidate observations before deletion (only for source memory types)
                if bank_id and fact_type in ("experience", "world"):
                    invalidated_obs = await self._delete_stale_observations_for_memories(conn, bank_id, [unit_id])
                    if invalidated_obs > 0:
                        bank_id_for_consolidation = bank_id

                # Delete the memory unit (cascades to links and associations)
                deleted = await conn.fetchval(
                    f"DELETE FROM {fq_table('memory_units')} WHERE id = $1 RETURNING id", unit_id
                )

                result = {
                    "success": deleted is not None,
                    "unit_id": str(deleted) if deleted else None,
                    "message": "Memory unit and all its links deleted successfully"
                    if deleted
                    else "Memory unit not found",
                }

        if bank_id_for_consolidation:
            await self.submit_async_consolidation(bank_id=bank_id_for_consolidation, request_context=request_context)

        return result

    async def delete_bank(
        self,
        bank_id: str,
        fact_type: str | None = None,
        *,
        request_context: "RequestContext",
    ) -> dict[str, int]:
        """
        Delete all data for a specific agent (multi-tenant cleanup).

        This is much more efficient than dropping all tables and allows
        multiple agents to coexist in the same database.

        Deletes (with CASCADE):
        - All memory units for this bank (optionally filtered by fact_type)
        - All entities for this bank (if deleting all memory units)
        - All associated links, unit-entity associations, and co-occurrences

        Args:
            bank_id: bank ID to delete
            fact_type: Optional fact type filter (world, experience, opinion). If provided, only deletes memories of that type.
            request_context: Request context for authentication.

        Returns:
            Dictionary with counts of deleted items
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="delete_bank", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()
        invalidated_obs = 0
        result: dict[str, int] = {}
        archive_storage_keys: list[str] = []
        async with acquire_with_retry(pool) as conn:
            # Ensure connection is not in read-only mode (can happen with connection poolers)
            await conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE")
            async with conn.transaction():
                try:
                    if fact_type:
                        # For source memory types, clean up observations before deletion
                        if fact_type in ("experience", "world"):
                            unit_id_rows = await conn.fetch(
                                f"SELECT id FROM {fq_table('memory_units')} WHERE bank_id = $1 AND fact_type = $2",
                                bank_id,
                                fact_type,
                            )
                            unit_ids = [str(row["id"]) for row in unit_id_rows]
                            if unit_ids:
                                invalidated_obs = await self._delete_stale_observations_for_memories(
                                    conn, bank_id, unit_ids
                                )

                        # Delete only memories of a specific fact type
                        units_count = await conn.fetchval(
                            f"SELECT COUNT(*) FROM {fq_table('memory_units')} WHERE bank_id = $1 AND fact_type = $2",
                            bank_id,
                            fact_type,
                        )
                        await conn.execute(
                            f"DELETE FROM {fq_table('memory_units')} WHERE bank_id = $1 AND fact_type = $2",
                            bank_id,
                            fact_type,
                        )

                        # Note: We don't delete entities when fact_type is specified,
                        # as they may be referenced by other memory units
                        result = {"memory_units_deleted": units_count, "entities_deleted": 0}
                    else:
                        # Delete all data for the bank — observations are included, no invalidation needed
                        units_count = await conn.fetchval(
                            f"SELECT COUNT(*) FROM {fq_table('memory_units')} WHERE bank_id = $1", bank_id
                        )
                        entities_count = await conn.fetchval(
                            f"SELECT COUNT(*) FROM {fq_table('entities')} WHERE bank_id = $1", bank_id
                        )
                        documents_count = await conn.fetchval(
                            f"SELECT COUNT(*) FROM {fq_table('documents')} WHERE bank_id = $1", bank_id
                        )
                        operations_count = await conn.fetchval(
                            f"SELECT COUNT(*) FROM {fq_table('async_operations')} WHERE bank_id = $1", bank_id
                        )
                        codebases_count = await conn.fetchval(
                            f"SELECT COUNT(*) FROM {fq_table('codebases')} WHERE bank_id = $1", bank_id
                        )
                        archive_storage_rows = await conn.fetch(
                            f"""
                            SELECT source_archive_storage_key
                            FROM {fq_table("codebase_snapshots")}
                            WHERE bank_id = $1 AND source_archive_storage_key IS NOT NULL
                            """,
                            bank_id,
                        )
                        archive_storage_keys = [row["source_archive_storage_key"] for row in archive_storage_rows]

                        # Delete documents (cascades to chunks)
                        await conn.execute(f"DELETE FROM {fq_table('documents')} WHERE bank_id = $1", bank_id)

                        # Delete memory units (cascades to unit_entities, memory_links)
                        await conn.execute(f"DELETE FROM {fq_table('memory_units')} WHERE bank_id = $1", bank_id)

                        # Delete entities (cascades to unit_entities, entity_cooccurrences, memory_links with entity_id)
                        await conn.execute(f"DELETE FROM {fq_table('entities')} WHERE bank_id = $1", bank_id)

                        # Delete async operations for this bank (pending/processing/completed/failed),
                        # so a recreated bank starts with a clean queue state.
                        await conn.execute(f"DELETE FROM {fq_table('async_operations')} WHERE bank_id = $1", bank_id)

                        # Delete codebases (cascades to snapshots, files, symbols, edges)
                        await conn.execute(f"DELETE FROM {fq_table('codebases')} WHERE bank_id = $1", bank_id)

                        # Delete the bank profile itself
                        await conn.execute(f"DELETE FROM {fq_table('banks')} WHERE bank_id = $1", bank_id)

                        result = {
                            "memory_units_deleted": units_count,
                            "entities_deleted": entities_count,
                            "documents_deleted": documents_count,
                            "operations_deleted": operations_count,
                            "codebases_deleted": codebases_count,
                            "bank_deleted": True,
                        }

                except Exception as e:
                    raise Exception(f"Failed to delete agent data: {str(e)}")

        if invalidated_obs > 0:
            await self.submit_async_consolidation(bank_id=bank_id, request_context=request_context)

        if not fact_type:
            for storage_key in archive_storage_keys:
                try:
                    await self._file_storage.delete(storage_key)
                except Exception as exc:
                    logger.warning(
                        "[DELETE_BANK] Failed to delete codebase archive %s for bank=%s: %s", storage_key, bank_id, exc
                    )

            # Remove derived local brain cache file for this bank.
            try:
                snapshot_delete = await self._brain_runtime.delete_snapshot(bank_id)
                result["brain_cache_deleted"] = int(bool(snapshot_delete.get("deleted")))
            except Exception as exc:
                logger.warning("[DELETE_BANK] Failed to delete brain cache for bank=%s: %s", bank_id, exc)
                result["brain_cache_deleted"] = 0

        return result

    async def clear_observations(
        self,
        bank_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, int]:
        """
        Clear all observations for a bank (consolidated knowledge).

        Args:
            bank_id: Bank ID to clear observations for
            request_context: Request context for authentication.

        Returns:
            Dictionary with count of deleted observations
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="clear_observations", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            async with conn.transaction():
                # Count observations before deletion
                count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {fq_table('memory_units')} WHERE bank_id = $1 AND fact_type = 'observation'",
                    bank_id,
                )

                # Delete all observations
                await conn.execute(
                    f"DELETE FROM {fq_table('memory_units')} WHERE bank_id = $1 AND fact_type = 'observation'",
                    bank_id,
                )

                # Reset consolidated_at on source memories so they get re-consolidated
                await conn.execute(
                    f"UPDATE {fq_table('memory_units')} SET consolidated_at = NULL WHERE bank_id = $1 AND fact_type IN ('experience', 'world')",
                    bank_id,
                )

                # Reset consolidation timestamp
                await conn.execute(
                    f"UPDATE {fq_table('banks')} SET last_consolidated_at = NULL WHERE bank_id = $1",
                    bank_id,
                )

                return {"deleted_count": count or 0}

    async def clear_observations_for_memory(
        self,
        bank_id: str,
        memory_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, int]:
        """
        Clear all observations derived from a specific memory and mark source memories
        (including the given memory itself) for re-consolidation.

        Unlike deleting the memory, the memory itself is preserved. This is useful
        when you want to force re-consolidation of a specific memory's observations
        without losing the underlying fact.

        Args:
            bank_id: Bank ID
            memory_id: ID of the memory whose observations should be cleared
            request_context: Request context for authentication.

        Returns:
            Dictionary with count of deleted observations
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(
                bank_id=bank_id, operation="clear_observations_for_memory", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()
        deleted_count = 0

        async with acquire_with_retry(pool) as conn:
            async with conn.transaction():
                import uuid as uuid_module

                deleted_count = await self._delete_stale_observations_for_memories(conn, bank_id, [memory_id])

                # Also reset this memory's own consolidated_at so it gets re-consolidated
                # (the memory was a source for the deleted observations, so it needs new ones)
                if deleted_count > 0:
                    await conn.execute(
                        f"""
                        UPDATE {fq_table("memory_units")}
                        SET consolidated_at = NULL
                        WHERE id = $1
                          AND bank_id = $2
                          AND fact_type IN ('experience', 'world')
                        """,
                        uuid_module.UUID(memory_id),
                        bank_id,
                    )

        if deleted_count > 0:
            await self.submit_async_consolidation(bank_id=bank_id, request_context=request_context)

        return {"deleted_count": deleted_count}

    async def run_consolidation(
        self,
        bank_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, int]:
        """
        Run memory consolidation to create/update mental models.

        Args:
            bank_id: Bank ID to run consolidation for
            request_context: Request context for authentication.

        Returns:
            Dictionary with consolidation stats
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="run_consolidation", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))

        from .consolidation import run_consolidation_job

        # Create parent span for consolidation operation
        with create_operation_span("consolidation", bank_id):
            result = await run_consolidation_job(
                memory_engine=self,
                bank_id=bank_id,
                request_context=request_context,
            )

            return {
                "processed": result.get("processed", 0),
                "created": result.get("created", 0),
                "updated": result.get("updated", 0),
                "skipped": result.get("skipped", 0),
            }

    async def get_graph_data(
        self,
        bank_id: str | None = None,
        fact_type: str | None = None,
        *,
        limit: int = 1000,
        q: str | None = None,
        tags: list[str] | None = None,
        tags_match: str = "all_strict",
        request_context: "RequestContext",
    ):
        """
        Get graph data for visualization.

        Args:
            bank_id: Filter by bank ID
            fact_type: Filter by fact type (world, experience, opinion)
            limit: Maximum number of items to return (default: 1000)
            q: Full-text search query (searches text and context fields)
            tags: Filter by tags
            tags_match: Tag matching mode (default: all_strict)
            request_context: Request context for authentication.

        Returns:
            Dict with nodes, edges, table_rows, total_units, and limit
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_graph_data", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            # Get memory units, optionally filtered by bank_id and fact_type
            query_conditions = []
            query_params = []
            param_count = 0

            if bank_id:
                param_count += 1
                query_conditions.append(f"bank_id = ${param_count}")
                query_params.append(bank_id)

            if fact_type:
                param_count += 1
                query_conditions.append(f"fact_type = ${param_count}")
                query_params.append(fact_type)

            if q:
                param_count += 1
                query_conditions.append(f"(text ILIKE ${param_count} OR context ILIKE ${param_count})")
                query_params.append(f"%{q}%")

            if tags:
                from .search.tags import build_tags_where_clause_simple

                tag_clause = build_tags_where_clause_simple(tags, param_count + 1, match=tags_match)
                if tag_clause:
                    query_conditions.append(tag_clause.removeprefix("AND "))
                    param_count += 1
                    query_params.append(tags)

            where_clause = "WHERE " + " AND ".join(query_conditions) if query_conditions else ""

            # Get total count first
            total_count_result = await conn.fetchrow(
                f"""
                SELECT COUNT(*) as total
                FROM {fq_table("memory_units")}
                {where_clause}
            """,
                *query_params,
            )
            total_count = total_count_result["total"] if total_count_result else 0

            # Get units with limit
            param_count += 1
            units = await conn.fetch(
                f"""
                SELECT id, text, event_date, context, occurred_start, occurred_end, mentioned_at,
                       timeline_anchor_at, timeline_anchor_kind, temporal_direction, temporal_confidence,
                       temporal_reference_text, document_id, chunk_id, fact_type, tags, created_at,
                       proof_count, source_memory_ids, access_count
                FROM {fq_table("memory_units")}
                {where_clause}
                ORDER BY mentioned_at DESC NULLS LAST, event_date DESC
                LIMIT ${param_count}
            """,
                *query_params,
                limit,
            )

            # Get links, filtering to only include links between units of the selected agent
            # Use DISTINCT ON with LEAST/GREATEST to deduplicate bidirectional links
            unit_ids = [row["id"] for row in units]
            unit_id_set = set(unit_ids)

            # Collect source memory IDs from observations
            source_memory_ids = []
            for unit in units:
                if unit["source_memory_ids"]:
                    source_memory_ids.extend(unit["source_memory_ids"])
            source_memory_ids = list(set(source_memory_ids))  # Deduplicate

            # Fetch links involving both visible units AND source memories
            all_relevant_ids = unit_ids + source_memory_ids
            if all_relevant_ids:
                links = await conn.fetch(
                    f"""
                    SELECT DISTINCT ON (LEAST(ml.from_unit_id, ml.to_unit_id), GREATEST(ml.from_unit_id, ml.to_unit_id), ml.link_type, COALESCE(ml.entity_id, '00000000-0000-0000-0000-000000000000'::uuid))
                        ml.from_unit_id,
                        ml.to_unit_id,
                        ml.link_type,
                        ml.weight,
                        e.canonical_name as entity_name
                    FROM {fq_table("memory_links")} ml
                    LEFT JOIN {fq_table("entities")} e ON ml.entity_id = e.id
                    WHERE ml.from_unit_id = ANY($1::uuid[]) OR ml.to_unit_id = ANY($1::uuid[])
                    ORDER BY LEAST(ml.from_unit_id, ml.to_unit_id), GREATEST(ml.from_unit_id, ml.to_unit_id), ml.link_type, COALESCE(ml.entity_id, '00000000-0000-0000-0000-000000000000'::uuid), ml.weight DESC
                """,
                    all_relevant_ids,
                )
            else:
                links = []

            # Copy links from source memories to observations
            # Observations inherit links from their source memories via source_memory_ids
            # Build a map from source_id to observation_ids
            source_to_observations = {}
            for unit in units:
                if unit["source_memory_ids"]:
                    for source_id in unit["source_memory_ids"]:
                        if source_id not in source_to_observations:
                            source_to_observations[source_id] = []
                        source_to_observations[source_id].append(unit["id"])

            copied_links = []
            for link in links:
                from_id = link["from_unit_id"]
                to_id = link["to_unit_id"]

                # Get observations that should inherit this link
                from_observations = source_to_observations.get(from_id, [])
                to_observations = source_to_observations.get(to_id, [])

                # If from_id is a source memory, copy links to its observations
                if from_observations:
                    for obs_id in from_observations:
                        # Only include if the target is visible
                        if to_id in unit_id_set or to_observations:
                            target = to_observations[0] if to_observations and to_id not in unit_id_set else to_id
                            if target in unit_id_set and obs_id != target:
                                copied_links.append(
                                    {
                                        "from_unit_id": obs_id,
                                        "to_unit_id": target,
                                        "link_type": link["link_type"],
                                        "weight": link["weight"],
                                        "entity_name": link["entity_name"],
                                    }
                                )

                # If to_id is a source memory, copy links to its observations
                if to_observations and from_id in unit_id_set:
                    for obs_id in to_observations:
                        if from_id != obs_id:
                            copied_links.append(
                                {
                                    "from_unit_id": from_id,
                                    "to_unit_id": obs_id,
                                    "link_type": link["link_type"],
                                    "weight": link["weight"],
                                    "entity_name": link["entity_name"],
                                }
                            )

            # Keep only direct links between visible nodes
            direct_links = [
                link for link in links if link["from_unit_id"] in unit_id_set and link["to_unit_id"] in unit_id_set
            ]

            # Get entity information only for currently relevant units
            # (visible units + their source memories), to avoid full-table scans.
            if all_relevant_ids:
                unit_entities = await conn.fetch(
                    f"""
                    SELECT ue.unit_id, e.canonical_name
                    FROM {fq_table("unit_entities")} ue
                    JOIN {fq_table("entities")} e ON ue.entity_id = e.id
                    WHERE ue.unit_id = ANY($1::uuid[])
                    ORDER BY ue.unit_id
                """,
                    all_relevant_ids,
                )
            else:
                unit_entities = []

        # Build entity mapping
        entity_map = {}
        for row in unit_entities:
            unit_id = row["unit_id"]
            entity_name = row["canonical_name"]
            if unit_id not in entity_map:
                entity_map[unit_id] = []
            entity_map[unit_id].append(entity_name)

        # For observations, inherit entities from source memories
        for unit in units:
            if unit["source_memory_ids"] and unit["id"] not in entity_map:
                # Collect entities from all source memories
                source_entities = []
                for source_id in unit["source_memory_ids"]:
                    if source_id in entity_map:
                        source_entities.extend(entity_map[source_id])
                if source_entities:
                    # Deduplicate while preserving order
                    entity_map[unit["id"]] = list(dict.fromkeys(source_entities))

        # Build nodes
        nodes = []
        for row in units:
            unit_id = row["id"]
            text = row["text"]
            event_date = row["event_date"]
            context = row["context"]

            entities = entity_map.get(unit_id, [])
            entity_count = len(entities)

            # Color by entity count
            if entity_count == 0:
                color = "#e0e0e0"
            elif entity_count == 1:
                color = "#90caf9"
            else:
                color = "#42a5f5"

            nodes.append(
                {
                    "data": {
                        "id": str(unit_id),
                        "label": f"{text[:30]}..." if len(text) > 30 else text,
                        "text": text,
                        "date": event_date.isoformat() if event_date else "",
                        "context": context if context else "",
                        "entities": ", ".join(entities) if entities else "None",
                        "color": color,
                        "accessCount": int(row["access_count"] or 0),
                    }
                }
            )

        # Build observation-inferred links from inherited entities and shared source memories.
        # Observations never have direct memory_links rows, so all their links must be derived.
        observation_units = [unit for unit in units if unit["fact_type"] == "observation"]
        observation_ids = {unit["id"] for unit in observation_units}

        # Entity links: pair observations that share at least one inherited entity
        entity_to_observations: dict[str, list] = {}
        for obs_id in observation_ids:
            for entity_name in entity_map.get(obs_id, []):
                entity_to_observations.setdefault(entity_name, []).append(obs_id)

        # Semantic links: pair observations that share at least one source memory
        source_to_obs_for_semantic: dict = {}
        for unit in observation_units:
            if unit["source_memory_ids"]:
                for src_id in unit["source_memory_ids"]:
                    source_to_obs_for_semantic.setdefault(src_id, []).append(unit["id"])

        observation_inferred_links = []
        seen_inferred: set[tuple] = set()

        for entity_name, obs_ids in entity_to_observations.items():
            for i, obs_a in enumerate(obs_ids):
                for obs_b in obs_ids[i + 1 :]:
                    pair = (min(str(obs_a), str(obs_b)), max(str(obs_a), str(obs_b)), "entity", entity_name)
                    if pair not in seen_inferred:
                        seen_inferred.add(pair)
                        observation_inferred_links.append(
                            {
                                "from_unit_id": obs_a,
                                "to_unit_id": obs_b,
                                "link_type": "entity",
                                "weight": 1.0,
                                "entity_name": entity_name,
                            }
                        )

        for src_id, obs_ids in source_to_obs_for_semantic.items():
            for i, obs_a in enumerate(obs_ids):
                for obs_b in obs_ids[i + 1 :]:
                    pair = (min(str(obs_a), str(obs_b)), max(str(obs_a), str(obs_b)), "semantic", "")
                    if pair not in seen_inferred:
                        seen_inferred.add(pair)
                        observation_inferred_links.append(
                            {
                                "from_unit_id": obs_a,
                                "to_unit_id": obs_b,
                                "link_type": "semantic",
                                "weight": 1.0,
                                "entity_name": None,
                            }
                        )

        # Build edges (combine direct links, copied links from sources, and observation-inferred links)
        edges = []
        seen_edges: set[tuple] = set()
        all_links = direct_links + copied_links + observation_inferred_links
        for row in all_links:
            from_id = str(row["from_unit_id"])
            to_id = str(row["to_unit_id"])
            link_type = row["link_type"]
            weight = row["weight"]
            entity_name = row.get("entity_name")

            # Color by link type
            if link_type == "temporal":
                color = "#00bcd4"
                line_style = "dashed"
            elif link_type == "semantic":
                color = "#ff69b4"
                line_style = "solid"
            elif link_type == "entity":
                color = "#ffd700"
                line_style = "solid"
            else:
                color = "#999999"
                line_style = "solid"

            edge_key = (from_id, to_id, link_type, entity_name or "")
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            edges.append(
                {
                    "data": {
                        "id": f"{from_id}-{to_id}-{link_type}",
                        "source": from_id,
                        "target": to_id,
                        "linkType": link_type,
                        "weight": weight,
                        "entityName": entity_name if entity_name else "",
                        "color": color,
                        "lineStyle": line_style,
                    }
                }
            )

        # Build table rows
        table_rows = []
        for row in units:
            unit_id = row["id"]
            entities = entity_map.get(unit_id, [])

            table_rows.append(
                {
                    "id": str(unit_id),
                    "text": row["text"],
                    "context": row["context"] if row["context"] else "N/A",
                    "occurred_start": row["occurred_start"].isoformat() if row["occurred_start"] else None,
                    "occurred_end": row["occurred_end"].isoformat() if row["occurred_end"] else None,
                    "mentioned_at": row["mentioned_at"].isoformat() if row["mentioned_at"] else None,
                    "timeline_anchor_at": row["timeline_anchor_at"].isoformat() if row["timeline_anchor_at"] else None,
                    "timeline_anchor_kind": row["timeline_anchor_kind"],
                    "temporal_direction": row["temporal_direction"],
                    "temporal_confidence": row["temporal_confidence"],
                    "temporal_reference_text": row["temporal_reference_text"],
                    "temporal": build_temporal_block(
                        occurred_start=row["occurred_start"],
                        mentioned_at=row["mentioned_at"],
                        created_at=row["created_at"],
                        timeline_anchor_at=row["timeline_anchor_at"],
                        timeline_anchor_kind=row["timeline_anchor_kind"],
                        temporal_direction=row["temporal_direction"],
                        temporal_confidence=row["temporal_confidence"],
                        temporal_reference_text=row["temporal_reference_text"],
                    ),
                    "date": row["event_date"].strftime("%Y-%m-%d %H:%M")
                    if row["event_date"]
                    else "N/A",  # Deprecated, kept for backwards compatibility
                    "entities": ", ".join(entities) if entities else "None",
                    "document_id": row["document_id"],
                    "chunk_id": row["chunk_id"] if row["chunk_id"] else None,
                    "fact_type": row["fact_type"],
                    "tags": list(row["tags"]) if row["tags"] else [],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "proof_count": row["proof_count"] if row["proof_count"] else None,
                    "access_count": int(row["access_count"] or 0),
                }
            )

        return {"nodes": nodes, "edges": edges, "table_rows": table_rows, "total_units": total_count, "limit": limit}

    async def get_timeline(
        self,
        bank_id: str,
        *,
        fact_type: str | None = None,
        q: str | None = None,
        tags: list[str] | None = None,
        tags_match: str = "all_strict",
        limit: int = 500,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_timeline", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))

        from .search.tags import build_tags_where_clause_simple

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            query_conditions: list[str] = []
            query_params: list[Any] = []
            param_count = 0

            param_count += 1
            query_conditions.append(f"bank_id = ${param_count}")
            query_params.append(bank_id)

            if fact_type:
                param_count += 1
                query_conditions.append(f"fact_type = ${param_count}")
                query_params.append(fact_type)

            if q:
                param_count += 1
                query_conditions.append(f"(text ILIKE ${param_count} OR context ILIKE ${param_count})")
                query_params.append(f"%{q}%")

            if tags:
                tag_clause = build_tags_where_clause_simple(tags, param_count + 1, match=tags_match)
                if tag_clause:
                    query_conditions.append(tag_clause.removeprefix("AND "))
                    param_count += 1
                    query_params.append(tags)

            where_clause = "WHERE " + " AND ".join(query_conditions)
            param_count += 1
            query_params.append(limit)

            memory_rows = await conn.fetch(
                f"""
                SELECT id, text, context, fact_type, occurred_start, occurred_end, mentioned_at,
                       timeline_anchor_at, timeline_anchor_kind, temporal_direction, temporal_confidence,
                       temporal_reference_text, created_at, tags, proof_count, source_memory_ids
                FROM {fq_table("memory_units")}
                {where_clause}
                ORDER BY COALESCE(timeline_anchor_at, occurred_start, mentioned_at, created_at) DESC NULLS LAST,
                         created_at DESC
                LIMIT ${param_count}
            """,
                *query_params,
            )

            unit_ids = [row["id"] for row in memory_rows]
            entity_map: dict[Any, list[str]] = {}
            if unit_ids:
                entity_rows = await conn.fetch(
                    f"""
                    SELECT ue.unit_id, e.canonical_name
                    FROM {fq_table("unit_entities")} ue
                    JOIN {fq_table("entities")} e ON ue.entity_id = e.id
                    WHERE ue.unit_id = ANY($1::uuid[])
                    ORDER BY ue.unit_id, e.canonical_name
                """,
                    unit_ids,
                )
                for row in entity_rows:
                    entity_map.setdefault(row["unit_id"], []).append(row["canonical_name"])

            link_rows = []
            if unit_ids:
                link_rows = await conn.fetch(
                    f"""
                    SELECT from_unit_id, to_unit_id, link_type, weight
                    FROM {fq_table("memory_links")}
                    WHERE from_unit_id = ANY($1::uuid[]) AND to_unit_id = ANY($1::uuid[])
                """,
                    unit_ids,
                )

            model_query_params: list[Any] = [bank_id]
            model_param_count = 1
            model_conditions = ["bank_id = $1"]
            if q:
                model_param_count += 1
                model_conditions.append(f"(name ILIKE ${model_param_count} OR content ILIKE ${model_param_count})")
                model_query_params.append(f"%{q}%")
            if tags:
                tag_clause = build_tags_where_clause_simple(tags, model_param_count + 1, match=tags_match)
                if tag_clause:
                    model_conditions.append(tag_clause.removeprefix("AND "))
                    model_param_count += 1
                    model_query_params.append(tags)
            model_param_count += 1
            model_query_params.append(max(25, min(limit, 150)))
            mental_model_rows = await conn.fetch(
                f"""
                SELECT id, name, source_query, content, tags, last_refreshed_at, created_at, reflect_response
                FROM {fq_table("mental_models")}
                WHERE {" AND ".join(model_conditions)}
                ORDER BY COALESCE(last_refreshed_at, created_at) DESC NULLS LAST
                LIMIT ${model_param_count}
            """,
                *model_query_params,
            )

        items: list[dict[str, Any]] = []
        visible_ids: set[str] = set()
        priority_order = {"fact": 0, "observation": 1, "mental_model": 2}

        for row in memory_rows:
            item_id = str(row["id"])
            kind = "observation" if row["fact_type"] == "observation" else "fact"
            temporal = build_temporal_block(
                occurred_start=row["occurred_start"],
                mentioned_at=row["mentioned_at"],
                created_at=row["created_at"],
                timeline_anchor_at=row["timeline_anchor_at"],
                timeline_anchor_kind=row["timeline_anchor_kind"],
                temporal_direction=row["temporal_direction"],
                temporal_confidence=row["temporal_confidence"],
                temporal_reference_text=row["temporal_reference_text"],
            )
            items.append(
                {
                    "id": item_id,
                    "kind": kind,
                    "fact_type": row["fact_type"],
                    "text": row["text"],
                    "context": row["context"] or "",
                    "anchor_at": temporal["anchor_at"],
                    "anchor_kind": temporal["anchor_kind"],
                    "recorded_at": temporal["recorded_at"],
                    "occurred_start": row["occurred_start"].isoformat() if row["occurred_start"] else None,
                    "occurred_end": row["occurred_end"].isoformat() if row["occurred_end"] else None,
                    "temporal_direction": temporal["direction"],
                    "temporal_confidence": temporal["confidence"],
                    "temporal_reference_text": temporal["reference_text"],
                    "temporal": temporal,
                    "entities": entity_map.get(row["id"], []),
                    "tags": list(row["tags"] or []),
                    "source_memory_ids": [str(source_id) for source_id in (row["source_memory_ids"] or [])],
                    "proof_count": int(row["proof_count"] or 0),
                }
            )
            visible_ids.add(item_id)

        for row in mental_model_rows:
            temporal_metadata = classify_snapshot_temporal_metadata(
                recorded_at=row["last_refreshed_at"] or row["created_at"],
                anchor_at=row["last_refreshed_at"] or row["created_at"],
            )
            supporting_memories = [
                str(item.get("id"))
                for item in decode_jsonb(row["reflect_response"], {}).get("based_on", {}).get("memories", [])
                if item.get("id")
            ]
            temporal = serialize_temporal_metadata(
                anchor_at=temporal_metadata.anchor_at,
                anchor_kind=temporal_metadata.anchor_kind,
                recorded_at=row["last_refreshed_at"] or row["created_at"],
                direction=temporal_metadata.direction,
                confidence=temporal_metadata.confidence,
                reference_text=None,
            )
            item_id = str(row["id"])
            items.append(
                {
                    "id": item_id,
                    "kind": "mental_model",
                    "fact_type": "mental_model",
                    "text": row["content"],
                    "context": row["source_query"],
                    "title": row["name"],
                    "anchor_at": temporal["anchor_at"],
                    "anchor_kind": temporal["anchor_kind"],
                    "recorded_at": temporal["recorded_at"],
                    "occurred_start": None,
                    "occurred_end": None,
                    "temporal_direction": temporal["direction"],
                    "temporal_confidence": temporal["confidence"],
                    "temporal_reference_text": None,
                    "temporal": temporal,
                    "entities": [],
                    "tags": list(row["tags"] or []),
                    "source_memory_ids": supporting_memories,
                    "proof_count": len(supporting_memories),
                }
            )
            visible_ids.add(item_id)

        def _item_sort_key(item: dict[str, Any]) -> tuple[str, int, str]:
            anchor_value = item.get("anchor_at") or item.get("recorded_at") or ""
            return (str(anchor_value), priority_order.get(item["kind"], 99), item["id"])

        items.sort(key=_item_sort_key)

        edges: list[dict[str, Any]] = []
        for idx in range(len(items) - 1):
            edges.append(
                {
                    "source": items[idx]["id"],
                    "target": items[idx + 1]["id"],
                    "edge_kind": "chronological",
                    "weight": 1.0,
                }
            )

        for row in link_rows:
            source = str(row["from_unit_id"])
            target = str(row["to_unit_id"])
            if source not in visible_ids or target not in visible_ids:
                continue
            link_type = row["link_type"]
            if link_type in {"semantic", "temporal", "entity"}:
                edge_kind = link_type
            elif link_type in {"causes", "caused_by", "enables", "prevents"}:
                edge_kind = "causal"
            else:
                edge_kind = "semantic"
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "edge_kind": edge_kind,
                    "weight": float(row["weight"] or 1.0),
                }
            )

        for item in items:
            edge_kind = "derived" if item["kind"] == "mental_model" else "source"
            for source_id in item.get("source_memory_ids", []):
                if source_id in visible_ids:
                    edges.append(
                        {
                            "source": item["id"],
                            "target": source_id,
                            "edge_kind": edge_kind,
                            "weight": 1.0,
                        }
                    )

        return {"items": items, "edges": edges, "total_items": len(items), "limit": limit}

    def _graph_intelligence_cache_key(
        self,
        *,
        bank_id: str,
        fact_type: str | None,
        limit: int,
        q: str | None,
        tags: list[str] | None,
        tags_match: str,
        confidence_min: float,
        node_kind: str,
        window_days: int | None,
    ) -> str:
        return json.dumps(
            {
                "bank_id": bank_id,
                "fact_type": fact_type,
                "limit": limit,
                "q": q,
                "tags": sorted(tags or []),
                "tags_match": tags_match,
                "confidence_min": round(confidence_min, 3),
                "node_kind": node_kind,
                "window_days": window_days,
                "graph_contradiction_cosine_min": round(get_config().graph_contradiction_cosine_min, 3),
                "graph_contradiction_cosine_max": round(get_config().graph_contradiction_cosine_max, 3),
                "graph_contradiction_confidence_penalty": round(get_config().graph_contradiction_confidence_penalty, 3),
                "schema": get_current_schema(),
            },
            sort_keys=True,
        )

    def _graph_surface_cache_key(
        self,
        *,
        endpoint: str,
        bank_id: str,
        surface: str,
        fact_type: str | None,
        q: str | None,
        tags: list[str] | None,
        tags_match: str,
        confidence_min: float,
        node_kind: str,
        window_days: int | None,
        focus_ids: list[str] | None = None,
        depth: int | None = None,
        limit_nodes: int | None = None,
        limit_edges: int | None = None,
    ) -> str:
        return json.dumps(
            {
                "endpoint": endpoint,
                "bank_id": bank_id,
                "surface": surface,
                "fact_type": fact_type,
                "q": q,
                "tags": sorted(tags or []),
                "tags_match": tags_match,
                "confidence_min": round(confidence_min, 3),
                "node_kind": node_kind,
                "window_days": window_days,
                "graph_contradiction_cosine_min": round(get_config().graph_contradiction_cosine_min, 3),
                "graph_contradiction_cosine_max": round(get_config().graph_contradiction_cosine_max, 3),
                "graph_contradiction_confidence_penalty": round(get_config().graph_contradiction_confidence_penalty, 3),
                "focus_ids": sorted(focus_ids or []),
                "depth": depth,
                "limit_nodes": limit_nodes,
                "limit_edges": limit_edges,
                "schema": get_current_schema(),
            },
            sort_keys=True,
        )

    @staticmethod
    def _parse_optional_datetime(value: str | datetime | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    async def _load_graph_intelligence_units(
        self,
        conn,
        *,
        bank_id: str,
        fact_type: str | None,
        limit: int,
        q: str | None,
        tags: list[str] | None,
        tags_match: str,
        window_days: int | None,
    ) -> list["GraphEvidenceUnit"]:
        from .embedding_similarity import parse_embedding_text
        from .graph_intelligence import GraphEvidenceUnit
        from .search.tags import build_tags_where_clause_simple

        query_conditions = ["bank_id = $1"]
        query_params: list[Any] = [bank_id]
        param_count = 1

        if fact_type:
            param_count += 1
            query_conditions.append(f"fact_type = ${param_count}")
            query_params.append(fact_type)

        if q:
            param_count += 1
            query_conditions.append(f"(text ILIKE ${param_count} OR context ILIKE ${param_count})")
            query_params.append(f"%{q}%")

        if tags:
            tag_clause = build_tags_where_clause_simple(tags, param_count + 1, match=cast(Any, tags_match))
            if tag_clause:
                query_conditions.append(tag_clause.removeprefix("AND "))
                param_count += 1
                query_params.append(tags)

        if window_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=window_days)
            param_count += 1
            query_conditions.append(f"COALESCE(occurred_start, mentioned_at, created_at) >= ${param_count}")
            query_params.append(cutoff)

        where_clause = "WHERE " + " AND ".join(query_conditions)
        fetch_limit = min(max(limit * 25, 250), 2000)
        param_count += 1
        query_params.append(fetch_limit)

        rows = await conn.fetch(
            f"""
            SELECT id, text, fact_type, context, occurred_start, mentioned_at, created_at,
                   proof_count, access_count, tags, source_memory_ids, chunk_id,
                   embedding::text AS embedding_text
            FROM {fq_table("memory_units")}
            {where_clause}
            ORDER BY COALESCE(occurred_start, mentioned_at, created_at) DESC NULLS LAST, created_at DESC
            LIMIT ${param_count}
        """,
            *query_params,
        )

        if not rows:
            return []

        unit_ids = [row["id"] for row in rows]
        unit_entities = await conn.fetch(
            f"""
            SELECT ue.unit_id, e.canonical_name
            FROM {fq_table("unit_entities")} ue
            JOIN {fq_table("entities")} e ON ue.entity_id = e.id
            WHERE ue.unit_id = ANY($1::uuid[])
            ORDER BY ue.unit_id, e.canonical_name
        """,
            unit_ids,
        )

        entity_map: dict[Any, list[str]] = {}
        for row in unit_entities:
            entity_map.setdefault(row["unit_id"], []).append(row["canonical_name"])

        units: list[GraphEvidenceUnit] = []
        for row in rows:
            units.append(
                GraphEvidenceUnit(
                    id=str(row["id"]),
                    text=row["text"],
                    fact_type=row["fact_type"],
                    embedding=parse_embedding_text(row["embedding_text"]),
                    context=row["context"],
                    occurred_start=row["occurred_start"],
                    mentioned_at=row["mentioned_at"],
                    created_at=row["created_at"],
                    proof_count=int(row["proof_count"] or 0),
                    access_count=int(row["access_count"] or 0),
                    tags=list(row["tags"] or []),
                    entities=entity_map.get(row["id"], []),
                    source_memory_ids=[str(source_id) for source_id in (row["source_memory_ids"] or [])],
                    chunk_id=row["chunk_id"],
                )
            )

        return units

    async def get_graph_intelligence(
        self,
        bank_id: str,
        *,
        fact_type: str | None = None,
        limit: int = 18,
        q: str | None = None,
        tags: list[str] | None = None,
        tags_match: str = "all_strict",
        confidence_min: float = 0.55,
        node_kind: str = "all",
        window_days: int | None = 90,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        from atulya_api.extensions import BankReadContext

        from .graph_intelligence import GraphBuildOptions, build_graph_intelligence

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankReadContext(bank_id=bank_id, operation="get_graph_intelligence", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))

        cache_key = self._graph_intelligence_cache_key(
            bank_id=bank_id,
            fact_type=fact_type,
            limit=limit,
            q=q,
            tags=tags,
            tags_match=tags_match,
            confidence_min=confidence_min,
            node_kind=node_kind,
            window_days=window_days,
        )
        cached = self._graph_intelligence_cache.get(cache_key)
        now = datetime.now(UTC)
        if cached and now - cached[0] < timedelta(seconds=60):
            response = dict(cached[1])
            response["cached"] = True
            return response

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            units = await self._load_graph_intelligence_units(
                conn,
                bank_id=bank_id,
                fact_type=fact_type,
                limit=limit,
                q=q,
                tags=tags,
                tags_match=tags_match,
                window_days=window_days,
            )

        intelligence = build_graph_intelligence(
            units,
            GraphBuildOptions(
                limit=limit,
                confidence_min=confidence_min,
                node_kind=cast(Any, node_kind),
                window_days=window_days,
                contradiction_cosine_min=get_config().graph_contradiction_cosine_min,
                contradiction_cosine_max=get_config().graph_contradiction_cosine_max,
                contradiction_confidence_penalty=get_config().graph_contradiction_confidence_penalty,
                now=now,
            ),
        ).model_dump(mode="json")
        self._graph_intelligence_cache[cache_key] = (now, intelligence)
        return intelligence

    async def get_graph_summary(
        self,
        bank_id: str,
        *,
        surface: str = "state",
        fact_type: str | None = None,
        q: str | None = None,
        tags: list[str] | None = None,
        tags_match: str = "all_strict",
        confidence_min: float = 0.55,
        node_kind: str = "all",
        window_days: int | None = 90,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        from atulya_api.extensions import BankReadContext

        from .graph_intelligence import GraphIntelligenceResponse
        from .graph_scaling import (
            EVIDENCE_SUMMARY_BUILD_LIMIT,
            STATE_SUMMARY_BUILD_LIMIT,
            build_evidence_graph_summary,
            build_state_graph_from_units,
            build_state_graph_summary,
        )

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankReadContext(bank_id=bank_id, operation="get_graph_summary", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))

        cache_key = self._graph_surface_cache_key(
            endpoint="summary",
            bank_id=bank_id,
            surface=surface,
            fact_type=fact_type,
            q=q,
            tags=tags,
            tags_match=tags_match,
            confidence_min=confidence_min,
            node_kind=node_kind,
            window_days=window_days,
        )
        now = datetime.now(UTC)
        cached = self._graph_summary_cache.get(cache_key)
        if cached and now - cached[0] < timedelta(seconds=60):
            response = dict(cached[1])
            response["cached"] = True
            return response

        if surface == "state":
            pool = await self._get_pool()
            async with acquire_with_retry(pool) as conn:
                units = await self._load_graph_intelligence_units(
                    conn,
                    bank_id=bank_id,
                    fact_type=fact_type,
                    limit=STATE_SUMMARY_BUILD_LIMIT,
                    q=q,
                    tags=tags,
                    tags_match=tags_match,
                    window_days=window_days,
                )
            graph = build_state_graph_from_units(
                units,
                limit=STATE_SUMMARY_BUILD_LIMIT,
                confidence_min=confidence_min,
                node_kind=cast(Any, node_kind),
                window_days=window_days,
                now=now,
            )
            summary = build_state_graph_summary(GraphIntelligenceResponse.model_validate(graph.model_dump(mode="json")))
        else:
            graph_data = await self.get_graph_data(
                bank_id,
                fact_type=fact_type,
                limit=EVIDENCE_SUMMARY_BUILD_LIMIT,
                q=q,
                tags=tags,
                tags_match=tags_match,
                request_context=request_context,
            )
            summary = build_evidence_graph_summary(graph_data)

        payload = summary.model_dump(mode="json")
        self._graph_summary_cache[cache_key] = (now, payload)
        return payload

    async def get_graph_neighborhood(
        self,
        bank_id: str,
        *,
        surface: str = "state",
        fact_type: str | None = None,
        q: str | None = None,
        tags: list[str] | None = None,
        tags_match: str = "all_strict",
        confidence_min: float = 0.55,
        node_kind: str = "all",
        window_days: int | None = 90,
        focus_ids: list[str] | None = None,
        depth: int = 1,
        limit_nodes: int = 60,
        limit_edges: int = 140,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        from atulya_api.extensions import BankReadContext

        from .graph_intelligence import GraphIntelligenceResponse
        from .graph_scaling import (
            EVIDENCE_SUMMARY_BUILD_LIMIT,
            STATE_SUMMARY_BUILD_LIMIT,
            build_evidence_graph_neighborhood,
            build_state_graph_from_units,
            build_state_graph_neighborhood,
        )

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankReadContext(bank_id=bank_id, operation="get_graph_neighborhood", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))

        cache_key = self._graph_surface_cache_key(
            endpoint="neighborhood",
            bank_id=bank_id,
            surface=surface,
            fact_type=fact_type,
            q=q,
            tags=tags,
            tags_match=tags_match,
            confidence_min=confidence_min,
            node_kind=node_kind,
            window_days=window_days,
            focus_ids=focus_ids,
            depth=depth,
            limit_nodes=limit_nodes,
            limit_edges=limit_edges,
        )
        now = datetime.now(UTC)
        cached = self._graph_neighborhood_cache.get(cache_key)
        if cached and now - cached[0] < timedelta(seconds=60):
            response = dict(cached[1])
            response["cached"] = True
            return response

        if surface == "state":
            pool = await self._get_pool()
            async with acquire_with_retry(pool) as conn:
                units = await self._load_graph_intelligence_units(
                    conn,
                    bank_id=bank_id,
                    fact_type=fact_type,
                    limit=STATE_SUMMARY_BUILD_LIMIT,
                    q=q,
                    tags=tags,
                    tags_match=tags_match,
                    window_days=window_days,
                )
            graph = build_state_graph_from_units(
                units,
                limit=STATE_SUMMARY_BUILD_LIMIT,
                confidence_min=confidence_min,
                node_kind=cast(Any, node_kind),
                window_days=window_days,
                now=now,
            )
            neighborhood = build_state_graph_neighborhood(
                GraphIntelligenceResponse.model_validate(graph.model_dump(mode="json")),
                focus_ids=focus_ids,
                depth=depth,
                limit_nodes=limit_nodes,
                limit_edges=limit_edges,
            )
        else:
            graph_data = await self.get_graph_data(
                bank_id,
                fact_type=fact_type,
                limit=EVIDENCE_SUMMARY_BUILD_LIMIT,
                q=q,
                tags=tags,
                tags_match=tags_match,
                request_context=request_context,
            )
            neighborhood = build_evidence_graph_neighborhood(
                graph_data,
                focus_ids=focus_ids,
                depth=depth,
                limit_nodes=limit_nodes,
                limit_edges=limit_edges,
            )

        payload = neighborhood.model_dump(mode="json")
        self._graph_neighborhood_cache[cache_key] = (now, payload)
        return payload

    async def investigate_graph(
        self,
        bank_id: str,
        *,
        query: str,
        fact_type: str | None = None,
        limit: int = 18,
        tags: list[str] | None = None,
        tags_match: str = "all_strict",
        confidence_min: float = 0.55,
        node_kind: str = "all",
        window_days: int | None = 90,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        from atulya_api.extensions import BankReadContext

        from .graph_intelligence import (
            GraphEvidenceUnit,
            GraphIntelligenceResponse,
        )
        from .graph_intelligence import (
            investigate_graph as build_investigation,
        )

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankReadContext(bank_id=bank_id, operation="investigate_graph", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))

        graph = GraphIntelligenceResponse.model_validate(
            await self.get_graph_intelligence(
                bank_id,
                fact_type=fact_type,
                limit=limit,
                q=None,
                tags=tags,
                tags_match=tags_match,
                confidence_min=confidence_min,
                node_kind=node_kind,
                window_days=window_days,
                request_context=request_context,
            )
        )
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            recall_units = await self._load_graph_intelligence_units(
                conn,
                bank_id=bank_id,
                fact_type=fact_type,
                limit=max(limit, 12),
                q=None,
                tags=tags,
                tags_match=tags_match,
                window_days=window_days,
            )
        investigation = build_investigation(query, graph, recall_units)
        return investigation.model_dump(mode="json")

    async def list_memory_units(
        self,
        bank_id: str,
        *,
        fact_type: str | None = None,
        search_query: str | None = None,
        limit: int = 100,
        offset: int = 0,
        request_context: "RequestContext",
    ):
        """
        List memory units for table view with optional full-text search.

        Args:
            bank_id: Filter by bank ID
            fact_type: Filter by fact type (world, experience, opinion)
            search_query: Full-text search query (searches text and context fields)
            limit: Maximum number of results to return
            offset: Offset for pagination
            request_context: Request context for authentication.

        Returns:
            Dict with items (list of memory units) and total count
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="list_memory_units", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            # Build query conditions
            query_conditions = []
            query_params = []
            param_count = 0

            if bank_id:
                param_count += 1
                query_conditions.append(f"bank_id = ${param_count}")
                query_params.append(bank_id)

            if fact_type:
                param_count += 1
                query_conditions.append(f"fact_type = ${param_count}")
                query_params.append(fact_type)

            if search_query:
                # Full-text search on text and context fields using ILIKE
                param_count += 1
                query_conditions.append(f"(text ILIKE ${param_count} OR context ILIKE ${param_count})")
                query_params.append(f"%{search_query}%")

            where_clause = "WHERE " + " AND ".join(query_conditions) if query_conditions else ""

            # Get total count
            count_query = f"""
                SELECT COUNT(*) as total
                FROM {fq_table("memory_units")}
                {where_clause}
            """
            count_result = await conn.fetchrow(count_query, *query_params)
            total = count_result["total"]

            # Get units with limit and offset
            param_count += 1
            limit_param = f"${param_count}"
            query_params.append(limit)

            param_count += 1
            offset_param = f"${param_count}"
            query_params.append(offset)

            units = await conn.fetch(
                f"""
                SELECT id, text, event_date, context, fact_type, mentioned_at, occurred_start, occurred_end,
                       timeline_anchor_at, timeline_anchor_kind, temporal_direction, temporal_confidence,
                       temporal_reference_text, created_at, chunk_id, proof_count, tags
                FROM {fq_table("memory_units")}
                {where_clause}
                ORDER BY mentioned_at DESC NULLS LAST, created_at DESC
                LIMIT {limit_param} OFFSET {offset_param}
            """,
                *query_params,
            )

            # Get entity information for these units
            if units:
                unit_ids = [row["id"] for row in units]
                unit_entities = await conn.fetch(
                    f"""
                    SELECT ue.unit_id, e.canonical_name
                    FROM {fq_table("unit_entities")} ue
                    JOIN {fq_table("entities")} e ON ue.entity_id = e.id
                    WHERE ue.unit_id = ANY($1::uuid[])
                    ORDER BY ue.unit_id
                """,
                    unit_ids,
                )
            else:
                unit_entities = []

            # Build entity mapping
            entity_map = {}
            for row in unit_entities:
                unit_id = row["unit_id"]
                entity_name = row["canonical_name"]
                if unit_id not in entity_map:
                    entity_map[unit_id] = []
                entity_map[unit_id].append(entity_name)

            # Build result items
            items = []
            for row in units:
                unit_id = row["id"]
                entities = entity_map.get(unit_id, [])

                items.append(
                    {
                        "id": str(unit_id),
                        "text": row["text"],
                        "context": row["context"] if row["context"] else "",
                        "date": row["event_date"].isoformat() if row["event_date"] else "",
                        "fact_type": row["fact_type"],
                        "mentioned_at": row["mentioned_at"].isoformat() if row["mentioned_at"] else None,
                        "occurred_start": row["occurred_start"].isoformat() if row["occurred_start"] else None,
                        "occurred_end": row["occurred_end"].isoformat() if row["occurred_end"] else None,
                        "timeline_anchor_at": row["timeline_anchor_at"].isoformat()
                        if row["timeline_anchor_at"]
                        else None,
                        "timeline_anchor_kind": row["timeline_anchor_kind"],
                        "temporal_direction": row["temporal_direction"],
                        "temporal_confidence": row["temporal_confidence"],
                        "temporal_reference_text": row["temporal_reference_text"],
                        "temporal": build_temporal_block(
                            occurred_start=row["occurred_start"],
                            mentioned_at=row["mentioned_at"],
                            created_at=row["created_at"],
                            timeline_anchor_at=row["timeline_anchor_at"],
                            timeline_anchor_kind=row["timeline_anchor_kind"],
                            temporal_direction=row["temporal_direction"],
                            temporal_confidence=row["temporal_confidence"],
                            temporal_reference_text=row["temporal_reference_text"],
                        ),
                        "entities": ", ".join(entities) if entities else "",
                        "chunk_id": row["chunk_id"] if row["chunk_id"] else None,
                        "proof_count": row["proof_count"] if row["proof_count"] is not None else 1,
                        "tags": list(row["tags"]) if row["tags"] else [],
                    }
                )

            return {"items": items, "total": total, "limit": limit, "offset": offset}

    async def get_memory_unit(
        self,
        bank_id: str,
        memory_id: str,
        request_context: "RequestContext",
    ):
        """
        Get a single memory unit by ID.

        Args:
            bank_id: Bank ID
            memory_id: Memory unit ID
            request_context: Request context for authentication.

        Returns:
            Dict with memory unit data or None if not found
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_memory_unit", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            # Get the memory unit (include source_memory_ids for mental models)
            row = await conn.fetchrow(
                f"""
                SELECT id, text, context, event_date, occurred_start, occurred_end,
                       mentioned_at, timeline_anchor_at, timeline_anchor_kind, temporal_direction,
                       temporal_confidence, temporal_reference_text, created_at,
                       fact_type, document_id, chunk_id, tags, source_memory_ids,
                       observation_scopes
                FROM {fq_table("memory_units")}
                WHERE id = $1 AND bank_id = $2
                """,
                memory_id,
                bank_id,
            )

            if not row:
                return None

            # Get entity information
            entities_rows = await conn.fetch(
                f"""
                SELECT e.canonical_name
                FROM {fq_table("unit_entities")} ue
                JOIN {fq_table("entities")} e ON ue.entity_id = e.id
                WHERE ue.unit_id = $1
                """,
                row["id"],
            )
            entities = [r["canonical_name"] for r in entities_rows]

            # For observations with no direct entities, inherit from source memories
            if not entities and row["fact_type"] == "observation" and row["source_memory_ids"]:
                source_entities_rows = await conn.fetch(
                    f"""
                    SELECT DISTINCT e.canonical_name
                    FROM {fq_table("unit_entities")} ue
                    JOIN {fq_table("entities")} e ON ue.entity_id = e.id
                    WHERE ue.unit_id = ANY($1::uuid[])
                    """,
                    row["source_memory_ids"],
                )
                entities = [r["canonical_name"] for r in source_entities_rows]

            result = {
                "id": str(row["id"]),
                "text": row["text"],
                "context": row["context"] if row["context"] else "",
                "date": row["event_date"].isoformat() if row["event_date"] else "",
                "type": row["fact_type"],
                "mentioned_at": row["mentioned_at"].isoformat() if row["mentioned_at"] else None,
                "occurred_start": row["occurred_start"].isoformat() if row["occurred_start"] else None,
                "occurred_end": row["occurred_end"].isoformat() if row["occurred_end"] else None,
                "timeline_anchor_at": row["timeline_anchor_at"].isoformat() if row["timeline_anchor_at"] else None,
                "timeline_anchor_kind": row["timeline_anchor_kind"],
                "temporal_direction": row["temporal_direction"],
                "temporal_confidence": row["temporal_confidence"],
                "temporal_reference_text": row["temporal_reference_text"],
                "temporal": build_temporal_block(
                    occurred_start=row["occurred_start"],
                    mentioned_at=row["mentioned_at"],
                    created_at=row["created_at"],
                    timeline_anchor_at=row["timeline_anchor_at"],
                    timeline_anchor_kind=row["timeline_anchor_kind"],
                    temporal_direction=row["temporal_direction"],
                    temporal_confidence=row["temporal_confidence"],
                    temporal_reference_text=row["temporal_reference_text"],
                ),
                "entities": entities,
                "document_id": row["document_id"] if row["document_id"] else None,
                "chunk_id": str(row["chunk_id"]) if row["chunk_id"] else None,
                "tags": row["tags"] if row["tags"] else [],
                "observation_scopes": row["observation_scopes"] if row["observation_scopes"] else None,
            }

            # For observations, include source_memory_ids
            # history is deprecated here - use GET /memories/{id}/history instead
            if row["fact_type"] == "observation":
                result["history"] = []

            if row["fact_type"] == "observation" and row["source_memory_ids"]:
                source_ids = row["source_memory_ids"]
                result["source_memory_ids"] = [str(sid) for sid in source_ids]

                # Fetch source memories
                source_rows = await conn.fetch(
                    f"""
                    SELECT id, text, fact_type, context, occurred_start, mentioned_at, timeline_anchor_at,
                           timeline_anchor_kind, temporal_direction, temporal_confidence,
                           temporal_reference_text, created_at
                    FROM {fq_table("memory_units")}
                    WHERE id = ANY($1::uuid[])
                    ORDER BY mentioned_at DESC NULLS LAST
                    """,
                    source_ids,
                )
                result["source_memories"] = [
                    {
                        "id": str(r["id"]),
                        "text": r["text"],
                        "type": r["fact_type"],
                        "context": r["context"],
                        "occurred_start": r["occurred_start"].isoformat() if r["occurred_start"] else None,
                        "mentioned_at": r["mentioned_at"].isoformat() if r["mentioned_at"] else None,
                        "temporal": build_temporal_block(
                            occurred_start=r["occurred_start"],
                            mentioned_at=r["mentioned_at"],
                            created_at=r["created_at"],
                            timeline_anchor_at=r["timeline_anchor_at"],
                            timeline_anchor_kind=r["timeline_anchor_kind"],
                            temporal_direction=r["temporal_direction"],
                            temporal_confidence=r["temporal_confidence"],
                            temporal_reference_text=r["temporal_reference_text"],
                        ),
                    }
                    for r in source_rows
                ]

            return result

    async def get_observation_history(
        self,
        bank_id: str,
        memory_id: str,
        request_context: "RequestContext",
    ) -> list[dict] | None:
        """
        Get the history of an observation, with source facts resolved to their text.

        Returns None if the memory is not found or is not an observation.
        Returns a list of history entries (most recent first), each with source_facts resolved.
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_observation_history", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT fact_type, history, source_memory_ids
                FROM {fq_table("memory_units")}
                WHERE id = $1 AND bank_id = $2
                """,
                uuid.UUID(memory_id),
                bank_id,
            )
            if not row:
                return None
            if row["fact_type"] != "observation":
                return []

            raw_history = row["history"]
            if isinstance(raw_history, str):
                raw_history = json.loads(raw_history)
            if not raw_history:
                return []

            # Collect all source memory IDs (current full set + all historical new ones)
            current_source_ids: list[str] = [str(sid) for sid in (row["source_memory_ids"] or [])]
            all_source_ids: set[uuid.UUID] = set(uuid.UUID(sid) for sid in current_source_ids)
            for entry in raw_history:
                for sid in entry.get("new_source_memory_ids", []):
                    try:
                        all_source_ids.add(uuid.UUID(sid))
                    except (ValueError, AttributeError):
                        pass

            # Resolve all source memories in one query
            source_map: dict[str, dict] = {}
            if all_source_ids:
                source_rows = await conn.fetch(
                    f"""
                    SELECT id, text, fact_type, context
                    FROM {fq_table("memory_units")}
                    WHERE id = ANY($1::uuid[])
                    """,
                    list(all_source_ids),
                )
                for r in source_rows:
                    source_map[str(r["id"])] = {
                        "id": str(r["id"]),
                        "text": r["text"],
                        "type": r["fact_type"],
                        "context": r["context"] or None,
                    }

            # Reconstruct cumulative source IDs per change by working backwards from current state.
            # Source IDs are only ever accumulated (never removed), so:
            #   after_change_N = before_change_N + new_source_memory_ids_N
            cumulative_ids: list[str] = list(current_source_ids)
            enriched: list[dict] = []
            for entry in reversed(raw_history):
                new_ids_in_entry: set[str] = set(entry.get("new_source_memory_ids", []))
                source_facts = []
                for sid in cumulative_ids:
                    fact = source_map.get(sid, {"id": sid, "text": None, "type": None, "context": None})
                    source_facts.append({**fact, "is_new": sid in new_ids_in_entry})
                enriched_entry = dict(entry)
                enriched_entry["source_facts"] = source_facts
                enriched.append(enriched_entry)
                # Step back: remove the new IDs added by this change to get the prior state
                cumulative_ids = [sid for sid in cumulative_ids if sid not in new_ids_in_entry]

            enriched.reverse()
            return enriched

    async def list_documents(
        self,
        bank_id: str,
        *,
        search_query: str | None = None,
        tags: list[str] | None = None,
        tags_match: "TagsMatch" = "any_strict",
        limit: int = 100,
        offset: int = 0,
        request_context: "RequestContext",
    ):
        """
        List documents with optional search and pagination.

        Args:
            bank_id: bank ID (required)
            search_query: Search in document ID
            tags: Filter by tags
            tags_match: How to match tags (any, all, any_strict, all_strict)
            limit: Maximum number of results
            offset: Offset for pagination
            request_context: Request context for authentication.

        Returns:
            Dict with items (list of documents without original_text) and total count
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="list_documents", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            # Build query conditions
            query_conditions = []
            query_params = []
            param_count = 0

            param_count += 1
            query_conditions.append(f"bank_id = ${param_count}")
            query_params.append(bank_id)

            if search_query:
                # Search in document ID
                param_count += 1
                query_conditions.append(f"id ILIKE ${param_count}")
                query_params.append(f"%{search_query}%")

            tags_clause, tags_params, next_param = build_tags_where_clause(
                tags, param_offset=param_count + 1, match=tags_match
            )
            query_params.extend(tags_params)
            param_count = next_param - 1  # next_param is next available; convert to last used

            where_clause = "WHERE " + " AND ".join(query_conditions) if query_conditions else ""
            if tags_clause:
                # tags_clause starts with "AND", append after WHERE conditions
                where_clause = where_clause + " " + tags_clause if where_clause else "WHERE " + tags_clause[4:].lstrip()

            # Get total count
            count_query = f"""
                SELECT COUNT(*) as total
                FROM {fq_table("documents")}
                {where_clause}
            """
            count_result = await conn.fetchrow(count_query, *query_params)
            total = count_result["total"]

            # Get documents with limit and offset (without original_text for performance)
            param_count += 1
            limit_param = f"${param_count}"
            query_params.append(limit)

            param_count += 1
            offset_param = f"${param_count}"
            query_params.append(offset)

            documents = await conn.fetch(
                f"""
                SELECT
                    id,
                    bank_id,
                    content_hash,
                    created_at,
                    updated_at,
                    LENGTH(original_text) as text_length,
                    retain_params,
                    tags
                FROM {fq_table("documents")}
                {where_clause}
                ORDER BY created_at DESC
                LIMIT {limit_param} OFFSET {offset_param}
            """,
                *query_params,
            )

            # Get memory unit count for each document
            if documents:
                doc_ids = [(row["id"], row["bank_id"]) for row in documents]

                # Create placeholders for the query
                placeholders = []
                params_for_count = []
                for i, (doc_id, bank_id_val) in enumerate(doc_ids):
                    idx_doc = i * 2 + 1
                    idx_agent = i * 2 + 2
                    placeholders.append(f"(document_id = ${idx_doc} AND bank_id = ${idx_agent})")
                    params_for_count.extend([doc_id, bank_id_val])

                where_clause_count = " OR ".join(placeholders)

                unit_counts = await conn.fetch(
                    f"""
                    SELECT document_id, bank_id, COUNT(*) as unit_count
                    FROM {fq_table("memory_units")}
                    WHERE {where_clause_count}
                    GROUP BY document_id, bank_id
                """,
                    *params_for_count,
                )
            else:
                unit_counts = []

            # Build count mapping
            count_map = {(row["document_id"], row["bank_id"]): row["unit_count"] for row in unit_counts}

            # Build result items
            items = []
            for row in documents:
                doc_id = row["id"]
                bank_id_val = row["bank_id"]
                unit_count = count_map.get((doc_id, bank_id_val), 0)

                items.append(
                    {
                        "id": doc_id,
                        "bank_id": bank_id_val,
                        "content_hash": row["content_hash"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
                        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
                        "text_length": row["text_length"] or 0,
                        "memory_unit_count": unit_count,
                        "retain_params": row["retain_params"] if row["retain_params"] else None,
                        "tags": row["tags"] if row["tags"] else [],
                    }
                )

            return {"items": items, "total": total, "limit": limit, "offset": offset}

    async def get_chunk(
        self,
        chunk_id: str,
        *,
        request_context: "RequestContext",
    ):
        """
        Get a specific chunk by its ID.

        Args:
            chunk_id: Chunk ID (format: bank_id_document_id_chunk_index)
            request_context: Request context for authentication.

        Returns:
            Dict with chunk details including chunk_text, or None if not found
        """
        await self._authenticate_tenant(request_context)
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            chunk = await conn.fetchrow(
                f"""
                SELECT
                    chunk_id,
                    document_id,
                    bank_id,
                    chunk_index,
                    chunk_text,
                    created_at
                FROM {fq_table("chunks")}
                WHERE chunk_id = $1
            """,
                chunk_id,
            )

            if not chunk:
                return None

            if self._operation_validator:
                from atulya_api.extensions import BankReadContext

                ctx = BankReadContext(bank_id=chunk["bank_id"], operation="get_chunk", request_context=request_context)
                await self._validate_operation(self._operation_validator.validate_bank_read(ctx))

            return {
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "bank_id": chunk["bank_id"],
                "chunk_index": chunk["chunk_index"],
                "chunk_text": chunk["chunk_text"],
                "created_at": chunk["created_at"].isoformat() if chunk["created_at"] else "",
            }

    # ==================== bank profile Methods ====================

    async def get_bank_profile(
        self,
        bank_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """
        Get bank profile (name, disposition + mission).
        Auto-creates agent with default values if not exists.

        Args:
            bank_id: bank IDentifier
            request_context: Request context for authentication.

        Returns:
            Dict with name, disposition traits, and mission
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_bank_profile", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        profile = await bank_utils.get_bank_profile(pool, bank_id)

        # reflect_mission and disposition in config take precedence over the legacy DB columns
        config_dict = await self._config_resolver.get_bank_config(bank_id, request_context)
        mission = config_dict.get("reflect_mission") or profile["mission"]

        # Overlay disposition from config if explicitly set; fall back to DB values
        db_disp = profile["disposition"]
        db_disp_dict = db_disp.model_dump() if hasattr(db_disp, "model_dump") else dict(db_disp)
        cfg_skep = config_dict.get("disposition_skepticism")
        cfg_lit = config_dict.get("disposition_literalism")
        cfg_emp = config_dict.get("disposition_empathy")
        disposition = {
            "skepticism": cfg_skep if cfg_skep is not None else db_disp_dict["skepticism"],
            "literalism": cfg_lit if cfg_lit is not None else db_disp_dict["literalism"],
            "empathy": cfg_emp if cfg_emp is not None else db_disp_dict["empathy"],
        }

        return {
            "bank_id": bank_id,
            "name": profile["name"],
            "disposition": disposition,
            "mission": mission,
        }

    async def update_bank_disposition(
        self,
        bank_id: str,
        disposition: dict[str, int],
        *,
        request_context: "RequestContext",
    ) -> None:
        """
        Update bank disposition traits.

        Args:
            bank_id: bank IDentifier
            disposition: Dict with skepticism, literalism, empathy (all 1-5)
            request_context: Request context for authentication.
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(
                bank_id=bank_id, operation="update_bank_disposition", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()
        await bank_utils.update_bank_disposition(pool, bank_id, disposition)

    async def set_bank_mission(
        self,
        bank_id: str,
        mission: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """
        Set the mission for a bank.

        Args:
            bank_id: bank IDentifier
            mission: The mission text
            request_context: Request context for authentication.

        Returns:
            Dict with bank_id and mission.
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="set_bank_mission", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()
        await bank_utils.set_bank_mission(pool, bank_id, mission)
        return {"bank_id": bank_id, "mission": mission}

    async def merge_bank_mission(
        self,
        bank_id: str,
        new_info: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """
        Merge new mission information with existing mission using LLM.
        Normalizes to first person ("I") and resolves conflicts.

        Args:
            bank_id: bank IDentifier
            new_info: New mission information to add/merge
            request_context: Request context for authentication.

        Returns:
            Dict with 'mission' (str) key
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="merge_bank_mission", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()
        return await bank_utils.merge_bank_mission(pool, self._reflect_llm_config, bank_id, new_info)

    async def list_banks(
        self,
        *,
        request_context: "RequestContext",
    ) -> list[dict[str, Any]]:
        """
        List all agents in the system.

        Args:
            request_context: Request context for authentication.

        Returns:
            List of dicts with bank_id, name, disposition, mission, created_at, updated_at
        """
        await self._authenticate_tenant(request_context)
        pool = await self._get_pool()
        banks = await bank_utils.list_banks(pool)
        if self._operation_validator:
            from atulya_api.extensions import BankListContext

            result = await self._operation_validator.filter_bank_list(
                BankListContext(banks=banks, request_context=request_context)
            )
            banks = result.banks
        return banks

    # ==================== Reflect Methods ====================

    async def reflect_async(
        self,
        bank_id: str,
        query: str,
        *,
        budget: Budget | None = None,
        context: str | None = None,
        max_tokens: int = 4096,
        response_schema: dict | None = None,
        request_context: "RequestContext",
        tags: list[str] | None = None,
        tags_match: TagsMatch = "any",
        exclude_mental_model_ids: list[str] | None = None,
        _skip_span: bool = False,
    ) -> ReflectResult:
        """
        Reflect and formulate an answer using an agentic loop with tools.

        The reflect agent iteratively uses tools to:
        1. lookup: Get mental models (synthesized knowledge)
        2. recall: Search facts (semantic + temporal retrieval)
        3. learn: Create/update mental models with new insights
        4. expand: Get chunk/document context for memories

        The agent starts with empty context and must call tools to gather
        information. On the last iteration, tools are removed to force a
        final text response.

        Args:
            bank_id: bank identifier
            query: Question to answer
            budget: Budget level (currently unused, reserved for future)
            context: Additional context string to include in agent prompt
            max_tokens: Max tokens (currently unused, reserved for future)
            response_schema: Optional JSON Schema for structured output (not yet supported)
            tags: Optional tags to filter memories
            tags_match: How to match tags - "any" (OR), "all" (AND)
            exclude_mental_model_ids: Optional list of mental model IDs to exclude from search
                (used when refreshing a mental model to avoid circular reference)

        Returns:
            ReflectResult containing:
                - text: Plain text answer
                - based_on: Empty dict (agent retrieves facts dynamically)
                - structured_output: None (not yet supported for agentic reflect)
        """
        # Use cached LLM config
        if self._reflect_llm_config is None:
            raise ValueError("Memory LLM API key not set. Set ATULYA_API_LLM_API_KEY environment variable.")

        # Authenticate tenant and set schema in context (for fq_table())
        await self._authenticate_tenant(request_context)

        # Validate operation if validator is configured
        if self._operation_validator:
            from atulya_api.extensions import ReflectContext

            ctx = ReflectContext(
                bank_id=bank_id,
                query=query,
                request_context=request_context,
                budget=budget,
                context=context,
            )
            await self._validate_operation(self._operation_validator.validate_reflect(ctx))

        reflect_start = time.time()
        reflect_id = f"{bank_id[:8]}-{int(time.time() * 1000) % 100000}"
        tags_info = f", tags={tags} ({tags_match})" if tags else ""
        logger.info(f"[REFLECT {reflect_id}] Starting agentic reflect for query: {query[:50]}...{tags_info}")

        # Get bank profile for agent identity
        profile = await self.get_bank_profile(bank_id, request_context=request_context)

        # NOTE: Mental models are NOT pre-loaded to keep the initial prompt small.
        # The agent can call lookup() to list available models if needed.
        # This is critical for banks with many mental models to avoid huge prompts.

        resolved_reflect_config = await self._config_resolver.resolve_full_config(bank_id, request_context)

        # Compute max iterations based on budget
        config = get_config()
        base_max_iterations = config.reflect_max_iterations
        # Budget multipliers: low=0.5x, mid=1x, high=2x
        budget_multipliers = {Budget.LOW: 0.5, Budget.MID: 1.0, Budget.HIGH: 2.0}
        effective_budget = budget or Budget.LOW
        max_iterations = max(1, int(base_max_iterations * budget_multipliers.get(effective_budget, 1.0)))
        max_context_tokens = config.reflect_max_context_tokens

        # Run agentic loop - acquire connections only when needed for DB operations
        # (not held during LLM calls which can be slow)
        pool = await self._get_pool()

        # Get bank stats for freshness info
        bank_stats = await self.get_bank_stats(bank_id, request_context=request_context)
        last_consolidated_at = bank_stats.last_consolidated_at if hasattr(bank_stats, "last_consolidated_at") else None
        pending_consolidation = bank_stats.pending_consolidation if hasattr(bank_stats, "pending_consolidation") else 0

        # Create tool callbacks that acquire connections only when needed
        from .retain import embedding_utils

        async def search_mental_models_fn(q: str, max_results: int = 5) -> dict[str, Any]:
            # Generate embedding for the query
            embeddings = await embedding_utils.generate_embeddings_batch(self.embeddings, [q])
            query_embedding = embeddings[0]
            async with pool.acquire() as conn:
                return await tool_search_mental_models(
                    conn,
                    bank_id,
                    q,
                    query_embedding,
                    max_results=max_results,
                    tags=tags,
                    tags_match=tags_match,
                    exclude_ids=exclude_mental_model_ids,
                    pending_consolidation=pending_consolidation,
                )

        async def search_observations_fn(q: str, max_tokens: int = 5000) -> dict[str, Any]:
            return await tool_search_observations(
                self,
                bank_id,
                q,
                request_context,
                max_tokens=max_tokens,
                tags=tags,
                tags_match=tags_match,
                last_consolidated_at=last_consolidated_at,
                pending_consolidation=pending_consolidation,
            )

        async def recall_fn(q: str, max_tokens: int = 4096, max_chunk_tokens: int = 1000) -> dict[str, Any]:
            return await tool_recall(
                self,
                bank_id,
                q,
                request_context,
                max_tokens=max_tokens,
                tags=tags,
                tags_match=tags_match,
                max_chunk_tokens=max_chunk_tokens,
            )

        async def expand_fn(memory_ids: list[str], depth: str) -> dict[str, Any]:
            async with pool.acquire() as conn:
                return await tool_expand(conn, bank_id, memory_ids, depth)

        # Load directives from the dedicated directives table
        # Directives are hard rules that must be followed in all responses
        # Use isolation_mode=True to prevent tag-scoped directives from leaking into untagged operations
        # Use the same tags_match as the reflect request so directives respect the same scoping rules
        directives_raw = await self.list_directives(
            bank_id=bank_id,
            tags=tags,
            tags_match=tags_match,
            active_only=True,
            request_context=request_context,
            isolation_mode=True,
        )
        directives = directives_raw
        if directives:
            logger.info(f"[REFLECT {reflect_id}] Loaded {len(directives)} directives")

        # Check if the bank has any mental models
        async with pool.acquire() as conn:
            mental_model_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {fq_table('mental_models')} WHERE bank_id = $1",
                bank_id,
            )
        has_mental_models = mental_model_count > 0
        if has_mental_models:
            logger.info(f"[REFLECT {reflect_id}] Bank has {mental_model_count} mental models")

        # Run the agent with parent span for reflect operation (skip if called from another operation)
        if not _skip_span:
            span_context = create_operation_span("reflect", bank_id)
            span_context.__enter__()
        else:
            span_context = None

        try:
            agent_result = await run_reflect_agent(
                llm_config=self._reflect_llm_config.with_config(resolved_reflect_config),
                bank_id=bank_id,
                query=query,
                bank_profile=profile,
                search_mental_models_fn=search_mental_models_fn,
                search_observations_fn=search_observations_fn,
                recall_fn=recall_fn,
                expand_fn=expand_fn,
                context=context,
                max_iterations=max_iterations,
                max_tokens=max_tokens,
                response_schema=response_schema,
                directives=directives,
                has_mental_models=has_mental_models,
                budget=effective_budget,
                max_context_tokens=max_context_tokens,
            )

            total_time = time.time() - reflect_start
            logger.info(
                f"[REFLECT {reflect_id}] Complete: {len(agent_result.text)} chars, "
                f"{agent_result.iterations} iterations, {agent_result.tools_called} tool calls | {total_time:.3f}s"
            )

            # Convert agent tool trace to ToolCallTrace objects
            tool_trace_result = [
                ToolCallTrace(
                    tool=tc.tool,
                    reason=tc.reason,
                    input=tc.input,
                    output=tc.output,
                    duration_ms=tc.duration_ms,
                    iteration=tc.iteration,
                )
                for tc in agent_result.tool_trace
            ]

            # Convert agent LLM trace to LLMCallTrace objects
            llm_trace_result = [
                LLMCallTrace(scope=lc.scope, duration_ms=lc.duration_ms) for lc in agent_result.llm_trace
            ]

            # Extract memories and observations from tool outputs - only include those the agent actually used
            # agent_result.used_memory_ids / used_observation_ids contain validated IDs from the done action
            used_memory_ids_set = set(agent_result.used_memory_ids) if agent_result.used_memory_ids else set()
            used_observation_ids_set = (
                set(agent_result.used_observation_ids) if agent_result.used_observation_ids else set()
            )
            # based_on stores facts, mental models, and directives
            # Note: directives list stores raw directive dicts (not MemoryFact), which will be converted to Directive objects
            based_on: dict[str, list[MemoryFact] | list[dict[str, Any]]] = {
                "world": [],
                "experience": [],
                "opinion": [],
                "observation": [],
                "mental-models": [],
                "directives": [],
            }
            seen_memory_ids: set[str] = set()
            for tc in agent_result.tool_trace:
                if tc.tool == "recall" and "memories" in tc.output:
                    for memory_data in tc.output["memories"]:
                        memory_id = memory_data.get("id")
                        # Only include memories that the agent declared as used (or all if none specified)
                        if memory_id and memory_id not in seen_memory_ids:
                            if used_memory_ids_set and memory_id not in used_memory_ids_set:
                                continue  # Skip memories not actually used by the agent
                            seen_memory_ids.add(memory_id)
                            fact_type = memory_data.get("fact_type", "world")
                            if fact_type in based_on:
                                based_on[fact_type].append(
                                    MemoryFact(
                                        id=memory_id,
                                        text=memory_data.get("text", ""),
                                        fact_type=fact_type,
                                        context=memory_data.get("context"),
                                        occurred_start=memory_data.get("occurred_start"),
                                        occurred_end=memory_data.get("occurred_end"),
                                        chunk_id=memory_data.get("chunk_id"),
                                    )
                                )
                elif tc.tool == "search_observations" and "observations" in tc.output:
                    for obs_data in tc.output["observations"]:
                        obs_id = obs_data.get("id")
                        if obs_id and obs_id not in seen_memory_ids:
                            if used_observation_ids_set and obs_id not in used_observation_ids_set:
                                continue  # Skip observations not actually used by the agent
                            seen_memory_ids.add(obs_id)
                            based_on["observation"].append(MemoryFact(**obs_data))

            # Extract mental models from tool outputs - only include models the agent actually used
            # agent_result.used_mental_model_ids contains validated IDs from the done action
            used_model_ids_set = (
                set(agent_result.used_mental_model_ids) if agent_result.used_mental_model_ids else set()
            )
            based_on["mental-models"] = []
            seen_model_ids: set[str] = set()
            for tc in agent_result.tool_trace:
                if tc.tool == "get_mental_model":
                    # Single model lookup (with full details)
                    if tc.output.get("found") and "model" in tc.output:
                        model = tc.output["model"]
                        model_id = model.get("id")
                        if model_id and model_id not in seen_model_ids:
                            # Only include models that the agent declared as used (or all if none specified)
                            if used_model_ids_set and model_id not in used_model_ids_set:
                                continue  # Skip models not actually used by the agent
                            seen_model_ids.add(model_id)
                            # Add to based_on as MemoryFact with type "mental-models"
                            model_name = model.get("name", "")
                            model_content = model.get("content", "")
                            based_on["mental-models"].append(
                                MemoryFact(
                                    id=model_id,
                                    text=f"{model_name}: {model_content}",
                                    fact_type="mental-models",
                                    context=f"{model.get('type', 'concept')} ({model.get('subtype', 'structural')})",
                                    occurred_start=None,
                                    occurred_end=None,
                                )
                            )
                elif tc.tool == "search_mental_models":
                    # Search mental models - include all returned models (filtered by used_model_ids_set if specified)
                    for model in tc.output.get("mental_models", []):
                        model_id = model.get("id")
                        if model_id and model_id not in seen_model_ids:
                            # Only include models that the agent declared as used (or all if none specified)
                            if used_model_ids_set and model_id not in used_model_ids_set:
                                continue  # Skip models not actually used by the agent
                            seen_model_ids.add(model_id)
                            # Add to based_on as MemoryFact with type "mental-models"
                            model_name = model.get("name", "")
                            model_content = model.get("content", "")
                            based_on["mental-models"].append(
                                MemoryFact(
                                    id=model_id,
                                    text=f"{model_name}: {model_content}",
                                    fact_type="mental-models",
                                    context=f"{model.get('type', 'concept')} ({model.get('subtype', 'structural')})",
                                    occurred_start=None,
                                    occurred_end=None,
                                )
                            )

            # Add directives to based_on["directives"]
            # Store raw directive dicts (with id, name, content) for http.py to convert to ReflectDirective
            for directive_raw in directives_raw:
                based_on["directives"].append(
                    {
                        "id": directive_raw["id"],
                        "name": directive_raw["name"],
                        "content": directive_raw["content"],
                    }
                )

            # Build directives_applied from agent result
            from atulya_api.engine.response_models import DirectiveRef

            directives_applied_result = [
                DirectiveRef(id=d.id, name=d.name, content=d.content) for d in agent_result.directives_applied
            ]

            # Convert agent usage to TokenUsage format
            from atulya_api.engine.response_models import TokenUsage

            usage = TokenUsage(
                input_tokens=agent_result.usage.input_tokens,
                output_tokens=agent_result.usage.output_tokens,
                total_tokens=agent_result.usage.total_tokens,
            )

            # Return response (compatible with existing API)
            result = ReflectResult(
                text=agent_result.text,
                based_on=based_on,
                structured_output=agent_result.structured_output,
                usage=usage,
                tool_trace=tool_trace_result,
                llm_trace=llm_trace_result,
                directives_applied=directives_applied_result,
            )

            # Call post-operation hook if validator is configured
            if self._operation_validator:
                from atulya_api.extensions.operation_validator import ReflectResultContext

                result_ctx = ReflectResultContext(
                    bank_id=bank_id,
                    query=query,
                    request_context=request_context,
                    budget=budget,
                    context=context,
                    result=result,
                    success=True,
                    error=None,
                )
                try:
                    await self._operation_validator.on_reflect_complete(result_ctx)
                except Exception as e:
                    logger.warning(f"Post-reflect hook error (non-fatal): {e}")

            await self._record_reflect_access_telemetry(
                bank_id=bank_id, based_on=based_on, tool_trace=agent_result.tool_trace
            )

            return result
        finally:
            if span_context:
                span_context.__exit__(None, None, None)

    async def list_entities(
        self,
        bank_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """
        List all entities for a bank with pagination.

        Args:
            bank_id: bank IDentifier
            limit: Maximum number of entities to return
            offset: Offset for pagination
            request_context: Request context for authentication.

        Returns:
            Dict with items, total, limit, offset
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="list_entities", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            # Get total count
            total_row = await conn.fetchrow(
                f"""
                SELECT COUNT(*) as total
                FROM {fq_table("entities")}
                WHERE bank_id = $1
                """,
                bank_id,
            )
            total = total_row["total"] if total_row else 0

            # Get paginated entities
            rows = await conn.fetch(
                f"""
                SELECT id, canonical_name, mention_count, first_seen, last_seen, metadata
                FROM {fq_table("entities")}
                WHERE bank_id = $1
                ORDER BY mention_count DESC, last_seen DESC, id ASC
                LIMIT $2 OFFSET $3
                """,
                bank_id,
                limit,
                offset,
            )

            entities = []
            for row in rows:
                # Handle metadata - may be dict, JSON string, or None
                metadata = row["metadata"]
                if metadata is None:
                    metadata = {}
                elif isinstance(metadata, str):
                    import json

                    try:
                        metadata = json.loads(metadata)
                    except json.JSONDecodeError:
                        metadata = {}

                entities.append(
                    {
                        "id": str(row["id"]),
                        "canonical_name": row["canonical_name"],
                        "mention_count": row["mention_count"],
                        "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
                        "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
                        "metadata": metadata,
                    }
                )
            return {
                "items": entities,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def list_tags(
        self,
        bank_id: str,
        *,
        pattern: str | None = None,
        limit: int = 100,
        offset: int = 0,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """
        List all unique tags for a bank with usage counts.

        Use this to discover available tags or expand wildcard patterns.
        Supports '*' as wildcard for flexible matching (case-insensitive):
        - 'user:*' matches user:alice, user:bob
        - '*-admin' matches role-admin, super-admin
        - 'env*-prod' matches env-prod, environment-prod

        Args:
            bank_id: Bank identifier
            pattern: Wildcard pattern to filter tags (use '*' as wildcard, case-insensitive)
            limit: Maximum number of tags to return
            offset: Offset for pagination
            request_context: Request context for authentication.

        Returns:
            Dict with items (list of {tag, count}), total, limit, offset
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="list_tags", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            # Build pattern filter if provided (convert * to % for ILIKE)
            pattern_clause = ""
            params: list[Any] = [bank_id]
            if pattern:
                # Convert wildcard pattern: * -> % for SQL ILIKE
                sql_pattern = pattern.replace("*", "%")
                pattern_clause = "AND tag ILIKE $2"
                params.append(sql_pattern)

            # Get total count of distinct tags matching pattern
            total_row = await conn.fetchrow(
                f"""
                SELECT COUNT(DISTINCT tag) as total
                FROM {fq_table("memory_units")}, unnest(tags) AS tag
                WHERE bank_id = $1 AND tags IS NOT NULL AND tags != '{{}}'
                {pattern_clause}
                """,
                *params,
            )
            total = total_row["total"] if total_row else 0

            # Get paginated tags with counts, ordered by frequency
            limit_param = len(params) + 1
            offset_param = len(params) + 2
            params.extend([limit, offset])

            rows = await conn.fetch(
                f"""
                SELECT tag, COUNT(*) as count
                FROM {fq_table("memory_units")}, unnest(tags) AS tag
                WHERE bank_id = $1 AND tags IS NOT NULL AND tags != '{{}}'
                {pattern_clause}
                GROUP BY tag
                ORDER BY count DESC, tag ASC
                LIMIT ${limit_param} OFFSET ${offset_param}
                """,
                *params,
            )

            items = [{"tag": row["tag"], "count": row["count"]} for row in rows]

            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def get_entity_state(
        self,
        bank_id: str,
        entity_id: str,
        entity_name: str,
        *,
        limit: int = 10,
        request_context: "RequestContext",
    ) -> EntityState:
        """
        Get the current state of an entity.

        NOTE: Entity observations/summaries have been moved to mental models.
        This method returns an entity with empty observations.

        Args:
            bank_id: bank IDentifier
            entity_id: Entity UUID
            entity_name: Canonical name of the entity
            limit: Maximum number of observations to include (kept for backwards compat)
            request_context: Request context for authentication.

        Returns:
            EntityState with empty observations (summaries now in mental models)
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_entity_state", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        return EntityState(entity_id=entity_id, canonical_name=entity_name, observations=[])

    # =========================================================================
    # Statistics & Operations (for HTTP API layer)
    # =========================================================================

    async def get_bank_stats(
        self,
        bank_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Get statistics about memory nodes and links for a bank."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_bank_stats", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            # Get node counts by fact_type
            node_stats = await conn.fetch(
                f"""
                SELECT fact_type, COUNT(*) as count
                FROM {fq_table("memory_units")}
                WHERE bank_id = $1
                GROUP BY fact_type
                """,
                bank_id,
            )

            # Single query for all link stats — avoids triple join on memory_links (can be 21M+ rows).
            # link_counts and link_counts_by_fact_type are derived in Python from the breakdown.
            link_breakdown_stats = await conn.fetch(
                f"""
                SELECT mu.fact_type, ml.link_type, COUNT(*) as count
                FROM {fq_table("memory_links")} ml
                JOIN {fq_table("memory_units")} mu ON ml.from_unit_id = mu.id
                WHERE mu.bank_id = $1
                GROUP BY mu.fact_type, ml.link_type
                """,
                bank_id,
            )

            link_counts: dict[str, int] = {}
            link_counts_by_fact_type: dict[str, int] = {}
            for row in link_breakdown_stats:
                link_counts[row["link_type"]] = link_counts.get(row["link_type"], 0) + row["count"]
                link_counts_by_fact_type[row["fact_type"]] = (
                    link_counts_by_fact_type.get(row["fact_type"], 0) + row["count"]
                )

            ops_stats = await conn.fetch(
                f"""
                SELECT status, COUNT(*) as count
                FROM {fq_table("async_operations")}
                WHERE bank_id = $1
                GROUP BY status
                """,
                bank_id,
            )
            doc_count_row = await conn.fetchrow(
                f"SELECT COUNT(*) as count FROM {fq_table('documents')} WHERE bank_id = $1",
                bank_id,
            )
            consolidation_row = await conn.fetchrow(
                f"""
                SELECT
                    MAX(consolidated_at) as last_consolidated_at,
                    COUNT(*) FILTER (WHERE consolidated_at IS NULL AND fact_type IN ('experience', 'world')) as pending
                FROM {fq_table("memory_units")}
                WHERE bank_id = $1
                """,
                bank_id,
            )

            node_counts = {row["fact_type"]: row["count"] for row in node_stats}
            ops_by_status = {row["status"]: row["count"] for row in ops_stats}
            last_consolidated_at = consolidation_row["last_consolidated_at"] if consolidation_row else None

            return {
                "bank_id": bank_id,
                "node_counts": node_counts,
                "link_counts": link_counts,
                "link_counts_by_fact_type": link_counts_by_fact_type,
                "link_breakdown": [
                    {"fact_type": row["fact_type"], "link_type": row["link_type"], "count": row["count"]}
                    for row in link_breakdown_stats
                ],
                "operations": ops_by_status,
                "total_documents": doc_count_row["count"] if doc_count_row else 0,
                "last_consolidated_at": last_consolidated_at.isoformat() if last_consolidated_at else None,
                "pending_consolidation": consolidation_row["pending"] if consolidation_row else 0,
                "total_observations": node_counts.get("observation", 0),
            }

    async def get_entity(
        self,
        bank_id: str,
        entity_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any] | None:
        """Get entity details including metadata and observations."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_entity", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            entity_row = await conn.fetchrow(
                f"""
                SELECT id, canonical_name, mention_count, first_seen, last_seen, metadata
                FROM {fq_table("entities")}
                WHERE bank_id = $1 AND id = $2
                """,
                bank_id,
                uuid.UUID(entity_id),
            )

        if not entity_row:
            return None

        return {
            "id": str(entity_row["id"]),
            "canonical_name": entity_row["canonical_name"],
            "mention_count": entity_row["mention_count"],
            "first_seen": entity_row["first_seen"].isoformat() if entity_row["first_seen"] else None,
            "last_seen": entity_row["last_seen"].isoformat() if entity_row["last_seen"] else None,
            "metadata": entity_row["metadata"] or {},
            "observations": [],
        }

    def _parse_observations(self, observations_raw: list):
        """Parse raw observation dicts into typed Observation models.

        Returns list of Observation models with computed trend/evidence_span/evidence_count.
        """
        from .reflect.observations import Observation, ObservationEvidence

        observations: list[Observation] = []
        for obs in observations_raw:
            if not isinstance(obs, dict):
                continue

            try:
                parsed = Observation(
                    title=obs.get("title", ""),
                    content=obs.get("content", ""),
                    evidence=[
                        ObservationEvidence(
                            memory_id=ev.get("memory_id", ""),
                            quote=ev.get("quote", ""),
                            relevance=ev.get("relevance", ""),
                            timestamp=ev.get("timestamp"),
                        )
                        for ev in obs.get("evidence", [])
                        if isinstance(ev, dict)
                    ],
                    created_at=obs.get("created_at"),
                )
                observations.append(parsed)
            except Exception as e:
                logger.warning(f"Failed to parse observation: {e}")
                continue

        return observations

    async def _count_memories_since(
        self,
        bank_id: str,
        since_timestamp: str | None,
        pool=None,
    ) -> int:
        """
        Count memories created after a given timestamp.

        Args:
            bank_id: Bank identifier
            since_timestamp: ISO timestamp string. If None, returns total count.
            pool: Optional database pool (uses default if not provided)

        Returns:
            Number of memories created since the timestamp
        """
        if pool is None:
            pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            if since_timestamp:
                # Parse the timestamp
                from datetime import datetime

                try:
                    ts = datetime.fromisoformat(since_timestamp.replace("Z", "+00:00"))
                except ValueError:
                    # Invalid timestamp, return total count
                    ts = None

                if ts:
                    count = await conn.fetchval(
                        f"SELECT COUNT(*) FROM {fq_table('memory_units')} WHERE bank_id = $1 AND created_at > $2",
                        bank_id,
                        ts,
                    )
                    return count or 0

            # No timestamp or invalid, return total count
            count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {fq_table('memory_units')} WHERE bank_id = $1",
                bank_id,
            )
            return count or 0

    async def _delete_stale_observations_for_memories(
        self,
        conn,
        bank_id: str,
        fact_ids: list[str],
    ) -> int:
        """
        Handle cleanup of observations when source memories are deleted.

        For each observation referencing any of the deleted fact IDs:
        1. Delete the observation (its text is stale without those source memories)
        2. Reset consolidated_at=NULL on the remaining source memories so they get re-consolidated

        Must be called within an active transaction, before the source memories are deleted.

        Args:
            conn: Database connection (must be in an active transaction)
            bank_id: Bank identifier
            fact_ids: List of fact IDs (as strings) that are being deleted

        Returns:
            Number of observations deleted
        """
        if not fact_ids:
            return 0

        import uuid as uuid_module

        fact_uuids = [uuid_module.UUID(fid) for fid in fact_ids]

        # Find all observations referencing any of the deleted facts
        affected_obs = await conn.fetch(
            f"""
            SELECT id, source_memory_ids
            FROM {fq_table("memory_units")}
            WHERE bank_id = $1
              AND fact_type = 'observation'
              AND source_memory_ids && $2::uuid[]
            """,
            bank_id,
            fact_uuids,
        )

        if not affected_obs:
            return 0

        # Collect observation IDs to delete and remaining source memory IDs to reset
        deleted_set = {str(uid) for uid in fact_uuids}
        obs_ids = [obs["id"] for obs in affected_obs]
        seen_remaining: set[str] = set()
        remaining_source_ids: list[uuid_module.UUID] = []

        for obs in affected_obs:
            for src_id in obs["source_memory_ids"] or []:
                src_str = str(src_id)
                if src_str not in deleted_set and src_str not in seen_remaining:
                    remaining_source_ids.append(src_id)
                    seen_remaining.add(src_str)

        # Delete the stale observations
        await conn.execute(
            f"DELETE FROM {fq_table('memory_units')} WHERE id = ANY($1::uuid[])",
            obs_ids,
        )

        # Reset consolidated_at on remaining source memories so they get re-consolidated
        if remaining_source_ids:
            await conn.execute(
                f"""
                UPDATE {fq_table("memory_units")}
                SET consolidated_at = NULL
                WHERE id = ANY($1::uuid[])
                  AND fact_type IN ('experience', 'world')
                """,
                remaining_source_ids,
            )

        logger.info(
            f"[OBSERVATIONS] Deleted {len(obs_ids)} observations, reset {len(remaining_source_ids)} "
            f"source memories for re-consolidation in bank {bank_id}"
        )
        return len(obs_ids)

    # =========================================================================
    # MENTAL MODELS (CONSOLIDATED) - Read-only access to auto-consolidated mental models
    # =========================================================================

    async def list_mental_models_consolidated(
        self,
        bank_id: str,
        *,
        tags: list[str] | None = None,
        tags_match: str = "any",
        limit: int = 100,
        offset: int = 0,
        request_context: "RequestContext",
    ) -> list[dict[str, Any]]:
        """List auto-consolidated observations for a bank.

        Observations are stored in memory_units with fact_type='observation'.
        They are automatically created and updated by the consolidation engine.

        Args:
            bank_id: Bank identifier
            tags: Optional tags to filter by
            tags_match: How to match tags - 'any', 'all', or 'exact'
            limit: Maximum number of results
            offset: Offset for pagination
            request_context: Request context for authentication

        Returns:
            List of observation dicts
        """
        await self._authenticate_tenant(request_context)
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            # Build tag filter
            tag_filter = ""
            params: list[Any] = [bank_id, limit, offset]
            if tags:
                if tags_match == "all":
                    tag_filter = " AND tags @> $4::varchar[]"
                elif tags_match == "exact":
                    tag_filter = " AND tags = $4::varchar[]"
                else:  # any
                    tag_filter = " AND tags && $4::varchar[]"
                params.append(tags)

            rows = await conn.fetch(
                f"""
                SELECT id, bank_id, text, proof_count, history, tags, source_memory_ids, created_at, updated_at
                FROM {fq_table("memory_units")}
                WHERE bank_id = $1 AND fact_type = 'observation' {tag_filter}
                ORDER BY updated_at DESC NULLS LAST
                LIMIT $2 OFFSET $3
                """,
                *params,
            )

            return [self._row_to_observation_consolidated(row) for row in rows]

    async def get_observation_consolidated(
        self,
        bank_id: str,
        observation_id: str,
        *,
        include_source_memories: bool = True,
        request_context: "RequestContext",
    ) -> dict[str, Any] | None:
        """Get a single observation by ID.

        Args:
            bank_id: Bank identifier
            observation_id: Observation ID
            include_source_memories: Whether to include full source memory details
            request_context: Request context for authentication

        Returns:
            Observation dict or None if not found
        """
        await self._authenticate_tenant(request_context)
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id, bank_id, text, proof_count, history, tags, source_memory_ids, created_at, updated_at
                FROM {fq_table("memory_units")}
                WHERE bank_id = $1 AND id = $2 AND fact_type = 'observation'
                """,
                bank_id,
                observation_id,
            )

            if not row:
                return None

            result = self._row_to_observation_consolidated(row)

            # Fetch source memories if requested and source_memory_ids exist
            if include_source_memories and result.get("source_memory_ids"):
                source_ids = [uuid.UUID(sid) if isinstance(sid, str) else sid for sid in result["source_memory_ids"]]
                source_rows = await conn.fetch(
                    f"""
                    SELECT id, text, fact_type, context, occurred_start, mentioned_at
                    FROM {fq_table("memory_units")}
                    WHERE id = ANY($1::uuid[])
                    ORDER BY mentioned_at DESC NULLS LAST
                    """,
                    source_ids,
                )
                result["source_memories"] = [
                    {
                        "id": str(r["id"]),
                        "text": r["text"],
                        "type": r["fact_type"],
                        "context": r["context"],
                        "occurred_start": r["occurred_start"].isoformat() if r["occurred_start"] else None,
                        "mentioned_at": r["mentioned_at"].isoformat() if r["mentioned_at"] else None,
                    }
                    for r in source_rows
                ]

            return result

    def _row_to_observation_consolidated(self, row: Any) -> dict[str, Any]:
        """Convert a database row to an observation dict."""
        import json

        history = row["history"]
        if isinstance(history, str):
            history = json.loads(history)
        elif history is None:
            history = []

        # Convert source_memory_ids to strings
        source_memory_ids = row.get("source_memory_ids") or []
        source_memory_ids = [str(sid) for sid in source_memory_ids]

        return {
            "id": str(row["id"]),
            "bank_id": row["bank_id"],
            "text": row["text"],
            "proof_count": row["proof_count"] or 1,
            "history": history,
            "tags": row["tags"] or [],
            "source_memory_ids": source_memory_ids,
            "source_memories": [],  # Populated separately when fetching full details
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    # =========================================================================
    # MENTAL MODELS CRUD
    # =========================================================================

    async def list_mental_models(
        self,
        bank_id: str,
        *,
        tags: list[str] | None = None,
        tags_match: str = "any",
        limit: int = 100,
        offset: int = 0,
        request_context: "RequestContext",
    ) -> list[dict[str, Any]]:
        """List pinned mental models for a bank.

        Args:
            bank_id: Bank identifier
            tags: Optional tags to filter by
            tags_match: How to match tags - 'any', 'all', or 'exact'
            limit: Maximum number of results
            offset: Offset for pagination
            request_context: Request context for authentication

        Returns:
            List of pinned mental model dicts
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="list_mental_models", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            # Build tag filter
            tag_filter = ""
            params: list[Any] = [bank_id, limit, offset]
            if tags:
                if tags_match == "all":
                    tag_filter = " AND tags @> $4::varchar[]"
                elif tags_match == "exact":
                    tag_filter = " AND tags = $4::varchar[]"
                else:  # any
                    tag_filter = " AND tags && $4::varchar[]"
                params.append(tags)

            rows = await conn.fetch(
                f"""
                SELECT id, bank_id, name, source_query, content, tags,
                       last_refreshed_at, created_at, reflect_response,
                       max_tokens, trigger
                FROM {fq_table("mental_models")}
                WHERE bank_id = $1 {tag_filter}
                ORDER BY last_refreshed_at DESC
                LIMIT $2 OFFSET $3
                """,
                *params,
            )

            return [self._row_to_mental_model(row) for row in rows]

    async def get_mental_model(
        self,
        bank_id: str,
        mental_model_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any] | None:
        """Get a single pinned mental model by ID.

        Args:
            bank_id: Bank identifier
            mental_model_id: Pinned mental model UUID
            request_context: Request context for authentication

        Returns:
            Pinned mental model dict or None if not found
        """
        await self._authenticate_tenant(request_context)

        # Pre-operation validation (credit check / usage metering)
        if self._operation_validator:
            from atulya_api.extensions.operation_validator import MentalModelGetContext

            ctx = MentalModelGetContext(
                bank_id=bank_id,
                mental_model_id=mental_model_id,
                request_context=request_context,
            )
            await self._validate_operation(self._operation_validator.validate_mental_model_get(ctx))

        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id, bank_id, name, source_query, content, tags,
                       last_refreshed_at, created_at, reflect_response,
                       max_tokens, trigger
                FROM {fq_table("mental_models")}
                WHERE bank_id = $1 AND id = $2
                """,
                bank_id,
                mental_model_id,
            )

            result = self._row_to_mental_model(row) if row else None

        # Post-operation hook (usage recording)
        if result and self._operation_validator:
            from atulya_api.extensions.operation_validator import MentalModelGetResult

            content = result.get("content", "")
            output_tokens = len(content) // 4 if content else 0

            result_ctx = MentalModelGetResult(
                bank_id=bank_id,
                mental_model_id=mental_model_id,
                request_context=request_context,
                output_tokens=output_tokens,
                success=True,
            )
            try:
                await self._operation_validator.on_mental_model_get_complete(result_ctx)
            except Exception as hook_err:
                logger.warning(f"Post-mental-model-get hook error (non-fatal): {hook_err}")

        return result

    async def get_mental_model_history(
        self,
        bank_id: str,
        mental_model_id: str,
        *,
        request_context: "RequestContext",
    ) -> list[dict] | None:
        """Get the refresh history of a mental model.

        Returns None if the mental model is not found.
        Returns a list of history entries (most recent first), each with previous_content and changed_at.
        """
        await self._authenticate_tenant(request_context)
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT history
                FROM {fq_table("mental_models")}
                WHERE bank_id = $1 AND id = $2
                """,
                bank_id,
                mental_model_id,
            )
            if row is None:
                return None
            raw_history = row["history"]
            if isinstance(raw_history, str):
                raw_history = json.loads(raw_history)
            if not raw_history:
                return []
            return list(reversed(raw_history))

    async def create_mental_model(
        self,
        bank_id: str,
        name: str,
        source_query: str,
        content: str,
        *,
        mental_model_id: str | None = None,
        tags: list[str] | None = None,
        max_tokens: int | None = None,
        trigger: dict[str, Any] | None = None,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Create a new pinned mental model.

        Args:
            bank_id: Bank identifier
            name: Human-readable name for the mental model
            source_query: The query that generated this mental model
            content: The synthesized content
            mental_model_id: Optional UUID for the mental model (auto-generated if not provided)
            tags: Optional tags for scoped visibility
            max_tokens: Token limit for content generation during refresh
            trigger: Trigger settings (e.g., refresh_after_consolidation)
            request_context: Request context for authentication

        Returns:
            The created pinned mental model dict
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="create_mental_model", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()

        # Generate embedding for the content
        embedding_text = f"{name} {content}"
        embedding = await embedding_utils.generate_embeddings_batch(self.embeddings, [embedding_text])
        # Convert embedding to string for asyncpg vector type
        embedding_str = str(embedding[0]) if embedding else None

        async with acquire_with_retry(pool) as conn:
            if mental_model_id:
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {fq_table("mental_models")}
                    (id, bank_id, name, source_query, content, embedding, tags, max_tokens, trigger)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, COALESCE($8, 2048), COALESCE($9, '{{"refresh_after_consolidation": false}}'::jsonb))
                    RETURNING id, bank_id, name, source_query, content, tags,
                              last_refreshed_at, created_at, reflect_response,
                              max_tokens, trigger
                    """,
                    mental_model_id,
                    bank_id,
                    name,
                    source_query,
                    content,
                    embedding_str,
                    tags or [],
                    max_tokens,
                    json.dumps(trigger) if trigger else None,
                )
            else:
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO {fq_table("mental_models")}
                    (bank_id, name, source_query, content, embedding, tags, max_tokens, trigger)
                    VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, 2048), COALESCE($8, '{{"refresh_after_consolidation": false}}'::jsonb))
                    RETURNING id, bank_id, name, source_query, content, tags,
                              last_refreshed_at, created_at, reflect_response,
                              max_tokens, trigger
                    """,
                    bank_id,
                    name,
                    source_query,
                    content,
                    embedding_str,
                    tags or [],
                    max_tokens,
                    json.dumps(trigger) if trigger else None,
                )

        logger.info(f"[MENTAL_MODELS] Created pinned mental model '{name}' for bank {bank_id}")
        return self._row_to_mental_model(row)

    async def refresh_mental_model(
        self,
        bank_id: str,
        mental_model_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any] | None:
        """Refresh a pinned mental model by re-running its source query.

        This method:
        1. Gets the pinned mental model
        2. Runs the source_query through reflect
        3. Updates the content with the new synthesis
        4. Updates last_refreshed_at

        Args:
            bank_id: Bank identifier
            mental_model_id: Pinned mental model UUID
            request_context: Request context for authentication

        Returns:
            Updated pinned mental model dict or None if not found
        """
        await self._authenticate_tenant(request_context)

        # Get the current mental model
        mental_model = await self.get_mental_model(bank_id, mental_model_id, request_context=request_context)
        if not mental_model:
            return None

        # Create parent span for mental model refresh operation
        with create_operation_span("mental_model_refresh", bank_id):
            # SECURITY: If the mental model has tags, pass them to reflect with "all_strict" matching
            # to ensure it can only access other mental models/memories with the SAME tags.
            # This prevents cross-tenant/cross-user information leakage by excluding untagged content.
            tags = mental_model.get("tags")
            tags_match = "all_strict" if tags else "any"

            # Run reflect with the source query, excluding the mental model being refreshed
            # Skip creating a nested "atulya.reflect" span since we already have "atulya.mental_model_refresh"
            reflect_result = await self.reflect_async(
                bank_id=bank_id,
                query=mental_model["source_query"],
                request_context=request_context,
                tags=tags,
                tags_match=tags_match,
                exclude_mental_model_ids=[mental_model_id],
                _skip_span=True,
            )

            # Build reflect_response payload to store
            # based_on contains MemoryFact objects for most types, but plain dicts for directives
            based_on_serialized_payload: dict[str, list[dict[str, Any]]] = {}
            for fact_type, facts in reflect_result.based_on.items():
                serialized_facts = []
                for fact in facts:
                    if isinstance(fact, dict):
                        # Plain dict (e.g., directives with id, name, content)
                        serialized_facts.append(
                            {
                                "id": str(fact["id"]),
                                "text": fact.get("text", fact.get("content", fact.get("name", ""))),
                                "type": fact_type,
                                "context": fact.get("context", None),
                            }
                        )
                    else:
                        # MemoryFact object with .id, .text, .context attributes
                        serialized_facts.append(
                            {
                                "id": str(fact.id),
                                "text": fact.text,
                                "type": fact_type,
                                "context": fact.context,
                            }
                        )
                based_on_serialized_payload[fact_type] = serialized_facts

            reflect_response_payload = {
                "text": reflect_result.text,
                "based_on": based_on_serialized_payload,
                "mental_models": [],  # Mental models are included in based_on["mental-models"]
            }

            # Update the mental model with new content and reflect_response
            return await self.update_mental_model(
                bank_id,
                mental_model_id,
                content=reflect_result.text,
                reflect_response=reflect_response_payload,
                request_context=request_context,
            )

    async def update_mental_model(
        self,
        bank_id: str,
        mental_model_id: str,
        *,
        name: str | None = None,
        content: str | None = None,
        source_query: str | None = None,
        max_tokens: int | None = None,
        tags: list[str] | None = None,
        trigger: dict[str, Any] | None = None,
        reflect_response: dict[str, Any] | None = None,
        request_context: "RequestContext",
    ) -> dict[str, Any] | None:
        """Update a pinned mental model.

        Args:
            bank_id: Bank identifier
            mental_model_id: Pinned mental model UUID
            name: New name (if changing)
            content: New content (if changing)
            source_query: New source query (if changing)
            max_tokens: New max tokens (if changing)
            tags: New tags (if changing)
            trigger: New trigger settings (if changing)
            reflect_response: Full reflect API response payload (if changing)
            request_context: Request context for authentication

        Returns:
            Updated pinned mental model dict or None if not found
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="update_mental_model", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            # If content is changing, fetch current content first to record history
            previous_content: str | None = None
            if content is not None:
                current_row = await conn.fetchrow(
                    f"SELECT content FROM {fq_table('mental_models')} WHERE bank_id = $1 AND id = $2",
                    bank_id,
                    mental_model_id,
                )
                if current_row:
                    previous_content = current_row["content"]

            # Build dynamic update
            updates = []
            params: list[Any] = [bank_id, mental_model_id]
            param_idx = 3

            if name is not None:
                updates.append(f"name = ${param_idx}")
                params.append(name)
                param_idx += 1

            if content is not None:
                updates.append(f"content = ${param_idx}")
                params.append(content)
                param_idx += 1
                updates.append("last_refreshed_at = NOW()")
                # Record history entry with the previous content
                if get_config().enable_mental_model_history:
                    history_entry = json.dumps(
                        [{"previous_content": previous_content, "changed_at": datetime.now(timezone.utc).isoformat()}]
                    )
                    updates.append(f"history = COALESCE(history, '[]'::jsonb) || ${param_idx}::jsonb")
                    params.append(history_entry)
                    param_idx += 1
                # Also update embedding (convert to string for asyncpg vector type)
                embedding_text = f"{name or ''} {content}"
                embedding = await embedding_utils.generate_embeddings_batch(self.embeddings, [embedding_text])
                if embedding:
                    updates.append(f"embedding = ${param_idx}")
                    params.append(str(embedding[0]))
                    param_idx += 1

            if reflect_response is not None:
                updates.append(f"reflect_response = ${param_idx}")
                params.append(json.dumps(reflect_response))
                param_idx += 1

            if source_query is not None:
                updates.append(f"source_query = ${param_idx}")
                params.append(source_query)
                param_idx += 1

            if max_tokens is not None:
                updates.append(f"max_tokens = ${param_idx}")
                params.append(max_tokens)
                param_idx += 1

            if tags is not None:
                updates.append(f"tags = ${param_idx}")
                params.append(tags)
                param_idx += 1

            if trigger is not None:
                updates.append(f"trigger = ${param_idx}")
                params.append(json.dumps(trigger))
                param_idx += 1

            if not updates:
                return None

            query = f"""
                UPDATE {fq_table("mental_models")}
                SET {", ".join(updates)}
                WHERE bank_id = $1 AND id = $2
                RETURNING id, bank_id, name, source_query, content, tags,
                          last_refreshed_at, created_at, reflect_response,
                          max_tokens, trigger
            """

            row = await conn.fetchrow(query, *params)

            return self._row_to_mental_model(row) if row else None

    async def delete_mental_model(
        self,
        bank_id: str,
        mental_model_id: str,
        *,
        request_context: "RequestContext",
    ) -> bool:
        """Delete a pinned mental model.

        Args:
            bank_id: Bank identifier
            mental_model_id: Pinned mental model UUID
            request_context: Request context for authentication

        Returns:
            True if deleted, False if not found
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="delete_mental_model", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            result = await conn.execute(
                f"DELETE FROM {fq_table('mental_models')} WHERE bank_id = $1 AND id = $2",
                bank_id,
                mental_model_id,
            )

        return result == "DELETE 1"

    def _row_to_mental_model(self, row) -> dict[str, Any]:
        """Convert a database row to a mental model dict."""
        reflect_response = row.get("reflect_response")
        # Parse JSON string to dict if needed (asyncpg may return JSONB as string)
        if isinstance(reflect_response, str):
            try:
                reflect_response = json.loads(reflect_response)
            except json.JSONDecodeError:
                reflect_response = None
        trigger = row.get("trigger")
        if isinstance(trigger, str):
            try:
                trigger = json.loads(trigger)
            except json.JSONDecodeError:
                trigger = None
        return {
            "id": str(row["id"]),
            "bank_id": row["bank_id"],
            "name": row["name"],
            "source_query": row["source_query"],
            "content": row["content"],
            "tags": row["tags"] or [],
            "max_tokens": row.get("max_tokens"),
            "trigger": trigger,
            "last_refreshed_at": row["last_refreshed_at"].isoformat() if row["last_refreshed_at"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "reflect_response": reflect_response,
        }

    # =========================================================================
    # Directives - Hard rules injected into prompts
    # =========================================================================

    async def list_directives(
        self,
        bank_id: str,
        *,
        tags: list[str] | None = None,
        tags_match: str = "any",
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
        request_context: "RequestContext",
        isolation_mode: bool = False,
    ) -> list[dict[str, Any]]:
        """List directives for a bank.

        Args:
            bank_id: Bank identifier
            tags: Optional tags to filter by
            tags_match: How to match tags - 'any', 'all', or 'exact'
            active_only: Only return active directives (default True)
            limit: Maximum number of results
            offset: Offset for pagination
            request_context: Request context for authentication
            isolation_mode: When True and tags=None, only return directives with no tags.
                This prevents tag-scoped directives from leaking into untagged operations.
                Default False (normal API behavior - returns all directives when tags=None)

        Returns:
            List of directive dicts
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="list_directives", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            # Build filters
            filters = ["bank_id = $1"]
            params: list[Any] = [bank_id]
            param_idx = 2

            if active_only:
                filters.append("is_active = TRUE")

            # Apply tags filter for directives:
            # Directives have special scoping rules:
            #   - Untagged directives (tags=[] or null) always apply regardless of reflect tags
            #   - Tagged directives only apply when the reflect operation includes matching tags
            #   - If tags=None and isolation_mode=True: only untagged directives (no leakage)
            #   - If tags=None and isolation_mode=False: all directives (normal API behavior)
            if tags:
                tags_clause, tags_params, param_idx = build_tags_where_clause(
                    tags=tags, param_offset=param_idx, table_alias="", match=tags_match
                )
                if tags_clause:
                    # Always include untagged directives; tagged ones must match the reflect tags
                    scoped_clause = tags_clause.replace("AND ", "", 1)
                    filters.append(f"((tags IS NULL OR tags = '{{}}') OR ({scoped_clause}))")
                    params.extend(tags_params)
            elif isolation_mode:
                # Isolation mode: only include directives with empty/null tags
                # This ensures tag-scoped directives don't apply to untagged operations
                filters.append("(tags IS NULL OR tags = '{}')")

            params.extend([limit, offset])

            rows = await conn.fetch(
                f"""
                SELECT id, bank_id, name, content, priority, is_active, tags, created_at, updated_at
                FROM {fq_table("directives")}
                WHERE {" AND ".join(filters)}
                ORDER BY priority DESC, created_at DESC
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
                """,
                *params,
            )

            return [self._row_to_directive(row) for row in rows]

    async def get_directive(
        self,
        bank_id: str,
        directive_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any] | None:
        """Get a single directive by ID.

        Args:
            bank_id: Bank identifier
            directive_id: Directive UUID
            request_context: Request context for authentication

        Returns:
            Directive dict or None if not found
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_directive", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id, bank_id, name, content, priority, is_active, tags, created_at, updated_at
                FROM {fq_table("directives")}
                WHERE bank_id = $1 AND id = $2
                """,
                bank_id,
                directive_id,
            )

            return self._row_to_directive(row) if row else None

    async def create_directive(
        self,
        bank_id: str,
        name: str,
        content: str,
        *,
        priority: int = 0,
        is_active: bool = True,
        tags: list[str] | None = None,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Create a new directive.

        Args:
            bank_id: Bank identifier
            name: Human-readable name for the directive
            content: The directive text to inject into prompts
            priority: Higher priority directives are injected first (default 0)
            is_active: Whether this directive is active (default True)
            tags: Optional tags for filtering
            request_context: Request context for authentication

        Returns:
            The created directive dict
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="create_directive", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                INSERT INTO {fq_table("directives")}
                (bank_id, name, content, priority, is_active, tags)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, bank_id, name, content, priority, is_active, tags, created_at, updated_at
                """,
                bank_id,
                name,
                content,
                priority,
                is_active,
                tags or [],
            )

        logger.info(f"[DIRECTIVES] Created directive '{name}' for bank {bank_id}")
        return self._row_to_directive(row)

    async def update_directive(
        self,
        bank_id: str,
        directive_id: str,
        *,
        name: str | None = None,
        content: str | None = None,
        priority: int | None = None,
        is_active: bool | None = None,
        tags: list[str] | None = None,
        request_context: "RequestContext",
    ) -> dict[str, Any] | None:
        """Update a directive.

        Args:
            bank_id: Bank identifier
            directive_id: Directive UUID
            name: New name (optional)
            content: New content (optional)
            priority: New priority (optional)
            is_active: New active status (optional)
            tags: New tags (optional)
            request_context: Request context for authentication

        Returns:
            Updated directive dict or None if not found
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="update_directive", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()

        # Build update query dynamically
        updates = ["updated_at = now()"]
        params: list[Any] = []
        param_idx = 1

        if name is not None:
            updates.append(f"name = ${param_idx}")
            params.append(name)
            param_idx += 1

        if content is not None:
            updates.append(f"content = ${param_idx}")
            params.append(content)
            param_idx += 1

        if priority is not None:
            updates.append(f"priority = ${param_idx}")
            params.append(priority)
            param_idx += 1

        if is_active is not None:
            updates.append(f"is_active = ${param_idx}")
            params.append(is_active)
            param_idx += 1

        if tags is not None:
            updates.append(f"tags = ${param_idx}")
            params.append(tags)
            param_idx += 1

        params.extend([bank_id, directive_id])

        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE {fq_table("directives")}
                SET {", ".join(updates)}
                WHERE bank_id = ${param_idx} AND id = ${param_idx + 1}
                RETURNING id, bank_id, name, content, priority, is_active, tags, created_at, updated_at
                """,
                *params,
            )

            return self._row_to_directive(row) if row else None

    async def delete_directive(
        self,
        bank_id: str,
        directive_id: str,
        *,
        request_context: "RequestContext",
    ) -> bool:
        """Delete a directive.

        Args:
            bank_id: Bank identifier
            directive_id: Directive UUID
            request_context: Request context for authentication

        Returns:
            True if deleted, False if not found
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="delete_directive", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            result = await conn.execute(
                f"DELETE FROM {fq_table('directives')} WHERE bank_id = $1 AND id = $2",
                bank_id,
                directive_id,
            )

        return result == "DELETE 1"

    def _row_to_directive(self, row) -> dict[str, Any]:
        """Convert a database row to a directive dict."""
        return {
            "id": str(row["id"]),
            "bank_id": row["bank_id"],
            "name": row["name"],
            "content": row["content"],
            "priority": row["priority"],
            "is_active": row["is_active"],
            "tags": row["tags"] or [],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    async def list_operations(
        self,
        bank_id: str,
        *,
        status: str | None = None,
        task_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """List async operations for a bank with optional filtering and pagination.

        Args:
            bank_id: Bank identifier
            status: Optional status filter (pending, completed, failed)
            task_type: Optional operation type filter (retain, consolidation, etc.)
            limit: Maximum number of operations to return (default 20)
            offset: Number of operations to skip (default 0)
            request_context: Request context for authentication

        Returns:
            Dict with total count and list of operations, sorted by most recent first
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="list_operations", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            # Build WHERE clause
            where_conditions = ["bank_id = $1"]
            params: list[Any] = [bank_id]

            if status:
                # Map API status to DB statuses (pending includes processing)
                if status == "pending":
                    where_conditions.append("status IN ('pending', 'processing')")
                else:
                    where_conditions.append(f"status = ${len(params) + 1}")
                    params.append(status)
            if task_type:
                where_conditions.append(f"operation_type = ${len(params) + 1}")
                params.append(task_type)

            where_clause = " AND ".join(where_conditions)

            # Get total count (with filter)
            total_row = await conn.fetchrow(
                f"SELECT COUNT(*) as total FROM {fq_table('async_operations')} WHERE {where_clause}",
                *params,
            )
            total = total_row["total"] if total_row else 0

            # Get operations with pagination (include result_metadata to check for parent operations)
            operations = await conn.fetch(
                f"""
                SELECT operation_id, operation_type, created_at, status, error_message, result_metadata
                FROM {fq_table("async_operations")}
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
                """,
                *params,
                limit,
                offset,
            )

            # Build operation list using status from database
            # Parent operations have their status updated when all children complete/fail
            operation_list = []
            for row in operations:
                # Map DB status to API status (pending includes processing)
                db_status = row["status"]
                api_status = "pending" if db_status in ("pending", "processing") else db_status

                operation_list.append(
                    {
                        "id": str(row["operation_id"]),
                        "task_type": row["operation_type"],
                        "items_count": 0,
                        "document_id": None,
                        "created_at": row["created_at"].isoformat(),
                        "status": api_status,
                        "error_message": row["error_message"],
                    }
                )

            return {
                "total": total,
                "operations": operation_list,
            }

    async def get_operation_status(
        self,
        bank_id: str,
        operation_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Get the status of a specific async operation.

        For parent operations, the status is automatically updated in the database when all children complete/fail.

        Returns:
            - status: "pending", "completed", or "failed" (from database)
            - updated_at: last update timestamp
            - completed_at: completion timestamp (if completed)
            - child_operations: (for parent operations) list of child operation statuses
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_operation_status", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()

        op_uuid = uuid.UUID(operation_id)

        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT operation_id, operation_type, created_at, updated_at, completed_at, status, error_message, result_metadata
                FROM {fq_table("async_operations")}
                WHERE operation_id = $1 AND bank_id = $2
                """,
                op_uuid,
                bank_id,
            )

            if row:
                # Check if this is a parent operation
                result_metadata = decode_jsonb(row["result_metadata"], {})
                is_parent = result_metadata.get("is_parent", False)
                stage = result_metadata.get("operation_stage")

                # Use status from database (parent status is updated when all children complete/fail)
                db_status = row["status"]
                api_status = "pending" if db_status in ("pending", "processing") else db_status

                # For parent operations, include child operations list
                if is_parent:
                    # Query child operations
                    child_rows = await conn.fetch(
                        f"""
                        SELECT operation_id, status, error_message, result_metadata
                        FROM {fq_table("async_operations")}
                        WHERE bank_id = $1
                        AND result_metadata::jsonb @> $2::jsonb
                        ORDER BY (result_metadata->>'sub_batch_index')::int
                        """,
                        bank_id,
                        json.dumps({"parent_operation_id": operation_id}),
                    )

                    # Build child operations list and check if parent status needs updating
                    child_statuses = []
                    all_done = True
                    any_failed = False
                    all_completed = True

                    for child_row in child_rows:
                        child_metadata = decode_jsonb(child_row["result_metadata"], {})
                        child_status = child_row["status"]

                        child_statuses.append(
                            {
                                "operation_id": str(child_row["operation_id"]),
                                "status": child_status,
                                "sub_batch_index": child_metadata.get("sub_batch_index"),
                                "items_count": child_metadata.get("items_count"),
                                "error_message": child_row["error_message"],
                            }
                        )

                        if child_status not in ("completed", "failed"):
                            all_done = False
                        if child_status == "failed":
                            any_failed = True
                        if child_status != "completed":
                            all_completed = False

                    # Self-healing: if parent status is out of sync with children, update it
                    if all_done and api_status == "pending":
                        correct_status = "failed" if any_failed else "completed"
                        logger.warning(
                            f"Parent operation {operation_id} status out of sync (DB: pending, should be: {correct_status}). Fixing."
                        )
                        await conn.execute(
                            f"""
                            UPDATE {fq_table("async_operations")}
                            SET status = $2, updated_at = NOW(), completed_at = NOW()
                            WHERE operation_id = $1
                            """,
                            op_uuid,
                            correct_status,
                        )
                        api_status = correct_status

                    return {
                        "operation_id": operation_id,
                        "status": api_status,
                        "operation_type": row["operation_type"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                        "error_message": row["error_message"],
                        "stage": stage,
                        "result_metadata": result_metadata,
                        "child_operations": child_statuses,
                    }
                else:
                    # Regular operation (not a parent)
                    return {
                        "operation_id": operation_id,
                        "status": api_status,
                        "operation_type": row["operation_type"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                        "error_message": row["error_message"],
                        "stage": stage,
                        "result_metadata": result_metadata,
                    }
            else:
                # Operation not found
                return {
                    "operation_id": operation_id,
                    "status": "not_found",
                    "operation_type": None,
                    "created_at": None,
                    "updated_at": None,
                    "completed_at": None,
                    "error_message": None,
                    "stage": None,
                }

    async def get_operation_result(
        self,
        bank_id: str,
        operation_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Get the current result payload for an async operation."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_operation_result", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()

        op_uuid = uuid.UUID(operation_id)

        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT operation_id, operation_type, created_at, updated_at, completed_at,
                       status, error_message, result_metadata, result_payload
                FROM {fq_table("async_operations")}
                WHERE operation_id = $1 AND bank_id = $2
                """,
                op_uuid,
                bank_id,
            )

            if not row:
                return {
                    "operation_id": operation_id,
                    "status": "not_found",
                    "operation_type": None,
                    "created_at": None,
                    "updated_at": None,
                    "completed_at": None,
                    "error_message": None,
                    "stage": None,
                    "result": None,
                }

            result_metadata = decode_jsonb(row["result_metadata"], {})
            result_payload = decode_jsonb(row["result_payload"], None)
            db_status = row["status"]
            api_status = "pending" if db_status in ("pending", "processing") else db_status

            return {
                "operation_id": operation_id,
                "status": api_status,
                "operation_type": row["operation_type"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                "error_message": row["error_message"],
                "stage": result_metadata.get("operation_stage"),
                "result": result_payload if api_status == "completed" else None,
            }

    async def cancel_operation(
        self,
        bank_id: str,
        operation_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Cancel a pending async operation."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="cancel_operation", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()

        op_uuid = uuid.UUID(operation_id)

        async with acquire_with_retry(pool) as conn:
            result = await conn.fetchrow(
                f"""
                SELECT bank_id, status, operation_type, result_metadata
                FROM {fq_table("async_operations")}
                WHERE operation_id = $1 AND bank_id = $2
                """,
                op_uuid,
                bank_id,
            )

            if not result:
                raise ValueError(f"Operation {operation_id} not found for bank {bank_id}")

            if result["status"] == "processing":
                raise ValueError(f"Operation {operation_id} is already processing and can no longer be cancelled")
            if result["status"] != "pending":
                raise ValueError(
                    f"Operation {operation_id} is already {result['status']} and can no longer be cancelled"
                )

            async with conn.transaction():
                await self._cleanup_cancelled_operation_state(
                    conn,
                    bank_id=bank_id,
                    operation_type=result["operation_type"],
                    result_metadata=decode_jsonb(result["result_metadata"], {}),
                )
                await conn.execute(f"DELETE FROM {fq_table('async_operations')} WHERE operation_id = $1", op_uuid)

            return {
                "success": True,
                "message": f"Operation {operation_id} cancelled",
                "operation_id": operation_id,
                "bank_id": bank_id,
            }

    async def _cleanup_cancelled_operation_state(
        self,
        conn,
        *,
        bank_id: str,
        operation_type: str | None,
        result_metadata: dict[str, Any],
    ) -> None:
        """Clean up queued state for operations that are cancelled before execution starts."""
        if operation_type not in {"codebase_import", "codebase_refresh"}:
            return

        codebase_id = result_metadata.get("codebase_id")
        snapshot_id = result_metadata.get("snapshot_id")
        if not codebase_id or not snapshot_id:
            return

        codebase_uuid = uuid.UUID(codebase_id)
        snapshot_uuid = uuid.UUID(snapshot_id)

        codebase_row = await conn.fetchrow(
            f"""
            SELECT current_snapshot_id, approved_snapshot_id
            FROM {fq_table("codebases")}
            WHERE id = $1 AND bank_id = $2
            """,
            codebase_uuid,
            bank_id,
        )
        if not codebase_row:
            return

        await conn.execute(
            f"""
            DELETE FROM {fq_table("codebase_snapshots")}
            WHERE id = $1 AND codebase_id = $2 AND bank_id = $3 AND status = 'pending'
            """,
            snapshot_uuid,
            codebase_uuid,
            bank_id,
        )

        if codebase_row["current_snapshot_id"] or codebase_row["approved_snapshot_id"]:
            return

        remaining_snapshots = await conn.fetchval(
            f"SELECT COUNT(*) FROM {fq_table('codebase_snapshots')} WHERE codebase_id = $1 AND bank_id = $2",
            codebase_uuid,
            bank_id,
        )
        if remaining_snapshots == 0:
            await conn.execute(
                f"DELETE FROM {fq_table('codebases')} WHERE id = $1 AND bank_id = $2",
                codebase_uuid,
                bank_id,
            )

    async def update_bank(
        self,
        bank_id: str,
        *,
        name: str | None = None,
        mission: str | None = None,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Update bank name and/or mission."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="update_bank", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()

        async with acquire_with_retry(pool) as conn:
            if name is not None:
                await conn.execute(
                    f"""
                    UPDATE {fq_table("banks")}
                    SET name = $2, updated_at = NOW()
                    WHERE bank_id = $1
                    """,
                    bank_id,
                    name,
                )

            if mission is not None:
                await conn.execute(
                    f"""
                    UPDATE {fq_table("banks")}
                    SET mission = $2, updated_at = NOW()
                    WHERE bank_id = $1
                    """,
                    bank_id,
                    mission,
                )

        # Return updated profile
        return await self.get_bank_profile(bank_id, request_context=request_context)

    async def _submit_async_operation(
        self,
        bank_id: str,
        operation_type: str,
        task_type: str,
        task_payload: dict[str, Any],
        *,
        result_metadata: dict[str, Any] | None = None,
        dedupe_by_bank: bool = False,
        dedupe_key: str | None = None,
    ) -> dict[str, Any]:
        """Generic helper to submit an async operation.

        Args:
            bank_id: Bank identifier
            operation_type: Operation type for the async_operations record (e.g., 'consolidation', 'retain')
            task_type: Task type for the task payload (e.g., 'consolidation', 'batch_retain')
            task_payload: Additional task payload fields (operation_id and bank_id are added automatically)
            result_metadata: Optional metadata to store with the operation record
            dedupe_by_bank: If True, skip creating a new task if one is already pending for this bank+operation_type
            dedupe_key: Optional deterministic key used for idempotent queueing

        Returns:
            Dict with operation_id and optionally deduplicated=True if an existing task was found
        """
        import json

        pool = await self._get_pool()

        # Check for existing pending task if deduplication is enabled
        # Note: We only check 'pending', not 'processing', because a processing task
        # uses a watermark from when it started - new memories added after that point
        # would need another consolidation run to be processed.
        if dedupe_by_bank:
            async with acquire_with_retry(pool) as conn:
                if dedupe_key:
                    existing = await conn.fetchrow(
                        f"""
                        SELECT operation_id FROM {fq_table("async_operations")}
                        WHERE bank_id = $1
                          AND operation_type = $2
                          AND status = 'pending'
                          AND result_metadata->>'dedupe_key' = $3
                        LIMIT 1
                        """,
                        bank_id,
                        operation_type,
                        dedupe_key,
                    )
                else:
                    existing = await conn.fetchrow(
                        f"""
                        SELECT operation_id FROM {fq_table("async_operations")}
                        WHERE bank_id = $1 AND operation_type = $2 AND status = 'pending'
                        LIMIT 1
                        """,
                        bank_id,
                        operation_type,
                    )
                if existing:
                    logger.debug(
                        f"{operation_type} task already pending for bank_id={bank_id}, "
                        f"skipping duplicate (existing operation_id={existing['operation_id']})"
                    )
                    return {
                        "operation_id": str(existing["operation_id"]),
                        "deduplicated": True,
                    }

        operation_id = uuid.uuid4()
        metadata_payload = dict(result_metadata or {})
        metadata_payload.setdefault("operation_stage", "queued")
        if dedupe_key:
            metadata_payload["dedupe_key"] = dedupe_key

        # Insert operation record into database
        async with acquire_with_retry(pool) as conn:
            await conn.execute(
                f"""
                INSERT INTO {fq_table("async_operations")} (operation_id, bank_id, operation_type, result_metadata, status)
                VALUES ($1, $2, $3, $4, $5)
                """,
                operation_id,
                bank_id,
                operation_type,
                json.dumps(metadata_payload),
                "pending",
            )

        # Build and submit task payload
        full_payload = {
            "type": task_type,
            "operation_type": operation_type,
            "operation_id": str(operation_id),
            "bank_id": bank_id,
            **task_payload,
        }

        await self._task_backend.submit_task(full_payload)

        logger.info(f"{operation_type} task queued for bank_id={bank_id}, operation_id={operation_id}")

        return {
            "operation_id": str(operation_id),
        }

    async def submit_async_codebase_zip_import(
        self,
        bank_id: str,
        *,
        name: str,
        archive_name: str,
        archive_bytes: bytes,
        root_path: str | None = None,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        refresh_existing: bool = False,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Queue a ZIP-based codebase import."""
        from atulya_api.extensions import BankWriteContext

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankWriteContext(bank_id=bank_id, operation="submit_codebase_import", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))

        config = get_config()
        max_archive_bytes = config.file_conversion_max_batch_size_bytes
        if len(archive_bytes) > max_archive_bytes:
            archive_mb = len(archive_bytes) / (1024 * 1024)
            raise ValueError(
                f"Archive size ({archive_mb:.1f}MB) exceeds maximum of {config.file_conversion_max_batch_size_mb}MB"
            )

        pool = await self._get_pool()
        source_config = {
            "root_path": root_path,
            "include_globs": include_globs or [],
            "exclude_globs": exclude_globs or [],
        }
        async with acquire_with_retry(pool) as conn:
            existing = await conn.fetchrow(
                f"""
                SELECT id
                FROM {fq_table("codebases")}
                WHERE bank_id = $1 AND name = $2 AND source_type = 'zip'
                """,
                bank_id,
                name,
            )
            if existing and not refresh_existing:
                raise ValueError(f"Codebase '{name}' already exists in bank {bank_id}. Use refresh_existing=true.")

            if existing:
                codebase_id = str(existing["id"])
                await conn.execute(
                    f"""
                    UPDATE {fq_table("codebases")}
                    SET source_config = $2::jsonb, updated_at = NOW()
                    WHERE id = $1
                    """,
                    uuid.UUID(codebase_id),
                    json.dumps(source_config),
                )
            else:
                codebase_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {fq_table("codebases")} (bank_id, name, source_type, source_config)
                    VALUES ($1, $2, 'zip', $3::jsonb)
                    RETURNING id
                    """,
                    bank_id,
                    name,
                    json.dumps(source_config),
                )
                codebase_id = str(codebase_row["id"])

            snapshot_row = await conn.fetchrow(
                f"""
                INSERT INTO {fq_table("codebase_snapshots")} (codebase_id, bank_id, source_ref, status)
                VALUES ($1, $2, $3, 'pending')
                RETURNING id
                """,
                uuid.UUID(codebase_id),
                bank_id,
                archive_name,
            )
            snapshot_id = str(snapshot_row["id"])

        storage_key = f"banks/{bank_id}/codebases/{codebase_id}/snapshots/{snapshot_id}/archive.zip"
        await self._file_storage.store(
            file_data=archive_bytes,
            key=storage_key,
            metadata={"bank_id": bank_id, "codebase_id": codebase_id, "snapshot_id": snapshot_id},
        )
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            await conn.execute(
                f"""
                UPDATE {fq_table("codebase_snapshots")}
                SET source_archive_storage_key = $2, updated_at = NOW()
                WHERE id = $1
                """,
                uuid.UUID(snapshot_id),
                storage_key,
            )

        operation = await self._submit_async_operation(
            bank_id=bank_id,
            operation_type="codebase_import",
            task_type="codebase_import_zip",
            task_payload={
                "codebase_id": codebase_id,
                "snapshot_id": snapshot_id,
                "storage_key": storage_key,
                "root_path": root_path,
                "include_globs": include_globs or [],
                "exclude_globs": exclude_globs or [],
            },
            result_metadata=CodebaseOperationMetadata(
                codebase_id=codebase_id,
                snapshot_id=snapshot_id,
                source_type="zip",
                source_ref=archive_name,
            ).to_dict(),
            dedupe_by_bank=False,
        )
        return {
            "codebase_id": codebase_id,
            "snapshot_id": snapshot_id,
            "operation_id": operation["operation_id"],
            "status": "pending",
        }

    async def submit_async_codebase_github_import(
        self,
        bank_id: str,
        *,
        owner: str,
        repo: str,
        ref: str,
        root_path: str | None = None,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        refresh_existing: bool = False,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Queue a public GitHub-backed codebase import."""
        from atulya_api.extensions import BankWriteContext

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankWriteContext(bank_id=bank_id, operation="submit_codebase_import", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))

        resolved_commit_sha = await self._resolve_public_github_commit_sha(owner, repo, ref)
        name = f"{owner}/{repo}"
        source_config = {
            "owner": owner,
            "repo": repo,
            "ref": ref,
            "root_path": root_path,
            "include_globs": include_globs or [],
            "exclude_globs": exclude_globs or [],
        }

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            existing = await conn.fetchrow(
                f"""
                SELECT id
                FROM {fq_table("codebases")}
                WHERE bank_id = $1 AND name = $2 AND source_type = 'github'
                """,
                bank_id,
                name,
            )
            if existing and not refresh_existing:
                raise ValueError(f"Codebase '{name}' already exists in bank {bank_id}. Use refresh_existing=true.")

            if existing:
                codebase_id = str(existing["id"])
                await conn.execute(
                    f"""
                    UPDATE {fq_table("codebases")}
                    SET source_config = $2::jsonb, updated_at = NOW()
                    WHERE id = $1
                    """,
                    uuid.UUID(codebase_id),
                    json.dumps(source_config),
                )
            else:
                codebase_row = await conn.fetchrow(
                    f"""
                    INSERT INTO {fq_table("codebases")} (bank_id, name, source_type, source_config)
                    VALUES ($1, $2, 'github', $3::jsonb)
                    RETURNING id
                    """,
                    bank_id,
                    name,
                    json.dumps(source_config),
                )
                codebase_id = str(codebase_row["id"])

            snapshot_row = await conn.fetchrow(
                f"""
                INSERT INTO {fq_table("codebase_snapshots")} (codebase_id, bank_id, source_ref, source_commit_sha, status)
                VALUES ($1, $2, $3, $4, 'pending')
                RETURNING id
                """,
                uuid.UUID(codebase_id),
                bank_id,
                ref,
                resolved_commit_sha,
            )
            snapshot_id = str(snapshot_row["id"])

        operation = await self._submit_async_operation(
            bank_id=bank_id,
            operation_type="codebase_import",
            task_type="codebase_import_github",
            task_payload={
                "codebase_id": codebase_id,
                "snapshot_id": snapshot_id,
                "owner": owner,
                "repo": repo,
                "root_path": root_path,
                "include_globs": include_globs or [],
                "exclude_globs": exclude_globs or [],
                "source_commit_sha": resolved_commit_sha,
            },
            result_metadata=CodebaseOperationMetadata(
                codebase_id=codebase_id,
                snapshot_id=snapshot_id,
                source_type="github",
                source_ref=ref,
            ).to_dict(),
            dedupe_by_bank=False,
        )
        return {
            "codebase_id": codebase_id,
            "snapshot_id": snapshot_id,
            "operation_id": operation["operation_id"],
            "resolved_commit_sha": resolved_commit_sha,
            "status": "pending",
        }

    async def submit_async_codebase_refresh(
        self,
        bank_id: str,
        codebase_id: str,
        *,
        ref: str | None = None,
        full_rebuild: bool = False,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Queue an explicit GitHub-backed codebase refresh or return a no-op."""
        from atulya_api.extensions import BankWriteContext

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankWriteContext(
                bank_id=bank_id, operation="submit_codebase_refresh", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id, source_type, source_config, current_snapshot_id
                FROM {fq_table("codebases")}
                WHERE id = $1 AND bank_id = $2
                """,
                uuid.UUID(codebase_id),
                bank_id,
            )
            if not row:
                raise ValueError(f"Codebase {codebase_id} not found in bank {bank_id}")
            if row["source_type"] != "github":
                raise ValueError("Explicit refresh is only supported for public GitHub codebases in v1.")

            source_config = decode_jsonb(row["source_config"], {})
            effective_ref = ref or source_config.get("ref")
            if not effective_ref:
                raise ValueError("Codebase refresh requires a GitHub ref.")
            owner = source_config.get("owner")
            repo = source_config.get("repo")
            if not owner or not repo:
                raise ValueError("GitHub codebase is missing owner/repo source configuration.")

            current_snapshot_row = None
            if row["current_snapshot_id"]:
                current_snapshot_row = await conn.fetchrow(
                    f"""
                    SELECT id, source_commit_sha
                    FROM {fq_table("codebase_snapshots")}
                    WHERE id = $1
                    """,
                    row["current_snapshot_id"],
                )

        resolved_commit_sha = await self._resolve_public_github_commit_sha(owner, repo, effective_ref)
        current_snapshot_id = str(current_snapshot_row["id"]) if current_snapshot_row else None
        current_commit_sha = str(current_snapshot_row["source_commit_sha"]) if current_snapshot_row else None
        if not full_rebuild and current_commit_sha == resolved_commit_sha:
            return {
                "snapshot_id": current_snapshot_id,
                "operation_id": None,
                "status": "completed",
                "noop": True,
                "added_files": 0,
                "changed_files": 0,
                "deleted_files": 0,
            }

        updated_source_config = dict(source_config)
        updated_source_config["ref"] = effective_ref
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            await conn.execute(
                f"""
                UPDATE {fq_table("codebases")}
                SET source_config = $2::jsonb, updated_at = NOW()
                WHERE id = $1
                """,
                uuid.UUID(codebase_id),
                json.dumps(updated_source_config),
            )
            snapshot_row = await conn.fetchrow(
                f"""
                INSERT INTO {fq_table("codebase_snapshots")} (codebase_id, bank_id, source_ref, source_commit_sha, status)
                VALUES ($1, $2, $3, $4, 'pending')
                RETURNING id
                """,
                uuid.UUID(codebase_id),
                bank_id,
                effective_ref,
                resolved_commit_sha,
            )
            snapshot_id = str(snapshot_row["id"])

        operation = await self._submit_async_operation(
            bank_id=bank_id,
            operation_type="codebase_refresh",
            task_type="codebase_import_github",
            task_payload={
                "codebase_id": codebase_id,
                "snapshot_id": snapshot_id,
                "owner": owner,
                "repo": repo,
                "root_path": updated_source_config.get("root_path"),
                "include_globs": updated_source_config.get("include_globs") or [],
                "exclude_globs": updated_source_config.get("exclude_globs") or [],
                "source_commit_sha": resolved_commit_sha,
            },
            result_metadata=CodebaseOperationMetadata(
                codebase_id=codebase_id,
                snapshot_id=snapshot_id,
                source_type="github",
                source_ref=effective_ref,
            ).to_dict(),
            dedupe_by_bank=False,
        )
        return {
            "snapshot_id": snapshot_id,
            "operation_id": operation["operation_id"],
            "status": "pending",
            "noop": False,
            "added_files": 0,
            "changed_files": 0,
            "deleted_files": 0,
        }

    async def submit_async_codebase_approval(
        self,
        bank_id: str,
        codebase_id: str,
        *,
        snapshot_id: str | None = None,
        memory_ingest_mode: str = "direct",
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Queue explicit approval for snapshot-backed memory hydration."""
        from atulya_api.extensions import BankWriteContext

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankWriteContext(
                bank_id=bank_id, operation="submit_codebase_approval", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id, current_snapshot_id, source_type, source_config
                FROM {fq_table("codebases")}
                WHERE id = $1 AND bank_id = $2
                """,
                uuid.UUID(codebase_id),
                bank_id,
            )
            if not row:
                raise ValueError(f"Codebase {codebase_id} not found in bank {bank_id}")
            target_snapshot_id = snapshot_id or (
                str(row["current_snapshot_id"]) if row["current_snapshot_id"] else None
            )
            if not target_snapshot_id:
                raise ValueError("Codebase has no parsed snapshot available for approval.")

            snapshot_row = await conn.fetchrow(
                f"""
                SELECT id, status
                FROM {fq_table("codebase_snapshots")}
                WHERE id = $1 AND codebase_id = $2 AND bank_id = $3
                """,
                uuid.UUID(target_snapshot_id),
                uuid.UUID(codebase_id),
                bank_id,
            )
            if not snapshot_row:
                raise ValueError(f"Snapshot {target_snapshot_id} not found for codebase {codebase_id}")
            if snapshot_row["status"] == "approved":
                raise ValueError("Current snapshot is already approved for memory hydration.")
            if snapshot_row["status"] not in {"review_required", "review_in_progress", "partially_approved"}:
                raise ValueError("Only review-required snapshots can be approved.")
            memory_route_count = await conn.fetchval(
                f"""
                SELECT COUNT(*)
                FROM {fq_table("codebase_review_routes")}
                WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3 AND route_target = 'memory'
                """,
                uuid.UUID(target_snapshot_id),
                bank_id,
                uuid.UUID(codebase_id),
            )
            if not memory_route_count:
                raise ValueError("Route at least one chunk to memory before approving.")

        if memory_ingest_mode not in {"direct", "retain"}:
            raise ValueError("memory_ingest_mode must be direct or retain.")

        task_payload: dict[str, Any] = {
            "codebase_id": codebase_id,
            "snapshot_id": target_snapshot_id,
            "memory_ingest_mode": memory_ingest_mode,
        }
        if request_context.tenant_id:
            task_payload["_tenant_id"] = request_context.tenant_id
        if request_context.api_key_id:
            task_payload["_api_key_id"] = request_context.api_key_id

        operation = await self._submit_async_operation(
            bank_id=bank_id,
            operation_type="codebase_approve",
            task_type="codebase_approve",
            task_payload=task_payload,
            result_metadata=CodebaseOperationMetadata(
                codebase_id=codebase_id,
                snapshot_id=target_snapshot_id,
                source_type=row["source_type"],
            ).to_dict()
            | {"memory_ingest_mode": memory_ingest_mode},
            dedupe_by_bank=True,
            dedupe_key=f"codebase_approve:{codebase_id}:{target_snapshot_id}:{memory_ingest_mode}",
        )
        return {
            "codebase_id": codebase_id,
            "snapshot_id": target_snapshot_id,
            "operation_id": operation["operation_id"],
            "status": "pending",
            "memory_ingest_mode": memory_ingest_mode,
        }

    def _derive_codebase_memory_state(
        self,
        *,
        current_snapshot_id: str | None,
        approved_snapshot_id: str | None,
        snapshot_status: str | None,
    ) -> tuple[str, str]:
        """Derive approval and memory lifecycle labels for codebase responses."""
        if not current_snapshot_id:
            return "not_ready", "not_hydrated"
        if snapshot_status == "failed":
            return "parse_failed", "not_hydrated" if not approved_snapshot_id else "hydrated_from_previous_snapshot"
        if snapshot_status in {"review_in_progress"}:
            if not approved_snapshot_id:
                memory_state = "not_hydrated"
            elif approved_snapshot_id == current_snapshot_id:
                memory_state = "hydrated"
            else:
                memory_state = "hydrated_from_previous_snapshot"
            return (
                "review_in_progress",
                memory_state,
            )
        if (
            snapshot_status == "partially_approved"
            and approved_snapshot_id
            and current_snapshot_id == approved_snapshot_id
        ):
            return "partially_approved", "hydrated"
        if approved_snapshot_id and current_snapshot_id == approved_snapshot_id:
            return "approved", "hydrated"
        if snapshot_status == "review_required":
            return (
                "pending_approval",
                "hydrated_from_previous_snapshot" if approved_snapshot_id else "not_hydrated",
            )
        if snapshot_status in {"pending", "processing"}:
            return (
                "parsing",
                "hydrated_from_previous_snapshot" if approved_snapshot_id else "not_hydrated",
            )
        return (
            "pending_approval" if current_snapshot_id else "not_ready",
            "hydrated_from_previous_snapshot" if approved_snapshot_id else "not_hydrated",
        )

    def _serialize_codebase_row(self, row: asyncpg.Record) -> dict[str, Any]:
        current_snapshot_id = str(row["current_snapshot_id"]) if row["current_snapshot_id"] else None
        approved_snapshot_id = str(row["approved_snapshot_id"]) if row["approved_snapshot_id"] else None
        approval_status, memory_status = self._derive_codebase_memory_state(
            current_snapshot_id=current_snapshot_id,
            approved_snapshot_id=approved_snapshot_id,
            snapshot_status=row["snapshot_status"],
        )
        return {
            "id": str(row["id"]),
            "bank_id": row["bank_id"],
            "name": row["name"],
            "source_type": row["source_type"],
            "source_config": decode_jsonb(row["source_config"], {}),
            "current_snapshot_id": current_snapshot_id,
            "approved_snapshot_id": approved_snapshot_id,
            "source_ref": row["source_ref"],
            "source_commit_sha": row["source_commit_sha"],
            "snapshot_status": row["snapshot_status"],
            "approved_source_ref": row["approved_source_ref"],
            "approved_source_commit_sha": row["approved_source_commit_sha"],
            "approved_snapshot_status": row["approved_snapshot_status"],
            "approval_status": approval_status,
            "memory_status": memory_status,
            "stats": decode_jsonb(row["stats"], {}),
            "review_counts": decode_jsonb(row["stats"], {}).get("review_counts", {}),
            "cluster_count": decode_jsonb(row["stats"], {}).get("cluster_count", 0),
            "related_chunk_count": decode_jsonb(row["stats"], {}).get("related_chunk_count", 0),
            "parse_coverage": decode_jsonb(row["stats"], {}).get("parse_coverage", 0.0),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "snapshot_created_at": row["snapshot_created_at"].isoformat() if row["snapshot_created_at"] else None,
            "snapshot_updated_at": row["snapshot_updated_at"].isoformat() if row["snapshot_updated_at"] else None,
            "approved_snapshot_updated_at": (
                row["approved_snapshot_updated_at"].isoformat() if row["approved_snapshot_updated_at"] else None
            ),
        }

    async def list_codebases(
        self,
        bank_id: str,
        *,
        request_context: "RequestContext",
    ) -> list[dict[str, Any]]:
        """List codebases for a bank."""
        from atulya_api.extensions import BankReadContext

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankReadContext(bank_id=bank_id, operation="list_codebases", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            rows = await conn.fetch(
                f"""
                SELECT c.id, c.bank_id, c.name, c.source_type, c.source_config, c.current_snapshot_id, c.approved_snapshot_id,
                       s.source_ref, s.source_commit_sha, s.status AS snapshot_status, s.stats,
                       s.created_at AS snapshot_created_at, s.updated_at AS snapshot_updated_at,
                       approved.source_ref AS approved_source_ref,
                       approved.source_commit_sha AS approved_source_commit_sha,
                       approved.status AS approved_snapshot_status,
                       approved.updated_at AS approved_snapshot_updated_at,
                       c.created_at, c.updated_at
                FROM {fq_table("codebases")} c
                LEFT JOIN {fq_table("codebase_snapshots")} s ON s.id = c.current_snapshot_id
                LEFT JOIN {fq_table("codebase_snapshots")} approved ON approved.id = c.approved_snapshot_id
                WHERE c.bank_id = $1
                ORDER BY c.updated_at DESC, c.created_at DESC
                """,
                bank_id,
            )
        return [self._serialize_codebase_row(row) for row in rows]

    async def get_codebase(
        self,
        bank_id: str,
        codebase_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any] | None:
        """Get codebase metadata and current snapshot summary."""
        from atulya_api.extensions import BankReadContext

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankReadContext(bank_id=bank_id, operation="get_codebase", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT c.id, c.bank_id, c.name, c.source_type, c.source_config, c.current_snapshot_id, c.approved_snapshot_id,
                       s.source_ref, s.source_commit_sha, s.status AS snapshot_status, s.stats,
                       approved.source_ref AS approved_source_ref,
                       approved.source_commit_sha AS approved_source_commit_sha,
                       approved.status AS approved_snapshot_status,
                       c.created_at, c.updated_at, s.created_at AS snapshot_created_at, s.updated_at AS snapshot_updated_at,
                       approved.updated_at AS approved_snapshot_updated_at
                FROM {fq_table("codebases")} c
                LEFT JOIN {fq_table("codebase_snapshots")} s ON s.id = c.current_snapshot_id
                LEFT JOIN {fq_table("codebase_snapshots")} approved ON approved.id = c.approved_snapshot_id
                WHERE c.id = $1 AND c.bank_id = $2
                """,
                uuid.UUID(codebase_id),
                bank_id,
            )
        if not row:
            return None
        return self._serialize_codebase_row(row)

    async def _refresh_codebase_review_stats(
        self,
        conn: asyncpg.Connection,
        *,
        bank_id: str,
        codebase_id: str,
        snapshot_id: str,
    ) -> dict[str, int]:
        counts_row = await conn.fetchrow(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE route_target = 'unrouted') AS unrouted_count,
                COUNT(*) FILTER (WHERE route_target = 'memory') AS memory_count,
                COUNT(*) FILTER (WHERE route_target = 'research') AS research_count,
                COUNT(*) FILTER (WHERE route_target = 'dismissed') AS dismissed_count
            FROM {fq_table("codebase_review_routes")}
            WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3
            """,
            uuid.UUID(snapshot_id),
            bank_id,
            uuid.UUID(codebase_id),
        )
        counts = {
            "unrouted": int(counts_row["unrouted_count"] or 0) if counts_row else 0,
            "memory": int(counts_row["memory_count"] or 0) if counts_row else 0,
            "research": int(counts_row["research_count"] or 0) if counts_row else 0,
            "dismissed": int(counts_row["dismissed_count"] or 0) if counts_row else 0,
        }
        stats_row = await conn.fetchrow(
            f"SELECT stats FROM {fq_table('codebase_snapshots')} WHERE id = $1",
            uuid.UUID(snapshot_id),
        )
        stats = decode_jsonb(stats_row["stats"] if stats_row else None, {})
        stats["review_counts"] = counts
        snapshot_status = (
            "review_required"
            if counts["memory"] == 0 and counts["research"] == 0 and counts["dismissed"] == 0
            else "review_in_progress"
        )
        await conn.execute(
            f"""
            UPDATE {fq_table("codebase_snapshots")}
            SET status = $2,
                stats = $3::jsonb,
                updated_at = NOW()
            WHERE id = $1
            """,
            uuid.UUID(snapshot_id),
            snapshot_status,
            json.dumps(stats),
        )
        return counts

    async def get_codebase_review(
        self,
        bank_id: str,
        codebase_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Return review-oriented summary for the current codebase snapshot."""
        codebase = await self.get_codebase(bank_id, codebase_id, request_context=request_context)
        if not codebase:
            raise ValueError(f"Codebase {codebase_id} not found in bank {bank_id}")
        snapshot_id = codebase.get("current_snapshot_id")
        if not snapshot_id:
            return {
                "codebase_id": codebase_id,
                "snapshot_id": None,
                "snapshot_status": None,
                "approval_status": codebase.get("approval_status"),
                "memory_status": codebase.get("memory_status"),
                "review_counts": {},
                "cluster_count": 0,
                "related_chunk_count": 0,
                "parse_coverage": 0.0,
                "changed_summary": {"added_files": 0, "changed_files": 0, "deleted_files": 0},
                "diagnostics": [],
            }

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            rows = await conn.fetch(
                f"""
                SELECT reason, COUNT(*) AS count
                FROM {fq_table("codebase_files")}
                WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3 AND reason IS NOT NULL
                GROUP BY reason
                ORDER BY count DESC, reason ASC
                LIMIT 10
                """,
                uuid.UUID(snapshot_id),
                bank_id,
                uuid.UUID(codebase_id),
            )
        stats = cast(dict[str, Any], codebase.get("stats") or {})
        return {
            "codebase_id": codebase_id,
            "snapshot_id": snapshot_id,
            "snapshot_status": codebase.get("snapshot_status"),
            "approval_status": codebase.get("approval_status"),
            "memory_status": codebase.get("memory_status"),
            "review_counts": codebase.get("review_counts") or {},
            "cluster_count": codebase.get("cluster_count") or 0,
            "related_chunk_count": codebase.get("related_chunk_count") or 0,
            "parse_coverage": codebase.get("parse_coverage") or 0.0,
            "changed_summary": {
                "added_files": stats.get("added_files", 0),
                "changed_files": stats.get("changed_files", 0),
                "deleted_files": stats.get("deleted_files", 0),
            },
            "diagnostics": [{"reason": row["reason"], "count": int(row["count"] or 0)} for row in rows],
        }

    async def list_codebase_chunks(
        self,
        bank_id: str,
        codebase_id: str,
        *,
        path_prefix: str | None = None,
        language: str | None = None,
        cluster_id: str | None = None,
        route_target: str | None = None,
        changed_only: bool = False,
        kind: str | None = None,
        q: str | None = None,
        limit: int = 25,
        cursor: str | None = None,
        snapshot_id: str | None = None,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """List reviewable codebase chunks with cursor-based pagination."""
        from atulya_api.extensions import BankReadContext

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankReadContext(bank_id=bank_id, operation="list_codebase_chunks", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            codebase = await conn.fetchrow(
                f"SELECT current_snapshot_id FROM {fq_table('codebases')} WHERE id = $1 AND bank_id = $2",
                uuid.UUID(codebase_id),
                bank_id,
            )
            if not codebase:
                raise ValueError(f"Codebase {codebase_id} not found in bank {bank_id}")
            effective_snapshot_id = snapshot_id or (
                str(codebase["current_snapshot_id"]) if codebase["current_snapshot_id"] else None
            )
            if not effective_snapshot_id:
                return {
                    "codebase_id": codebase_id,
                    "snapshot_id": None,
                    "items": [],
                    "next_cursor": None,
                    "has_more": False,
                }

            where_clauses = ["c.snapshot_id = $1", "c.bank_id = $2", "c.codebase_id = $3"]
            params: list[Any] = [uuid.UUID(effective_snapshot_id), bank_id, uuid.UUID(codebase_id)]
            if path_prefix:
                where_clauses.append(f"c.path LIKE ${len(params) + 1}")
                params.append(f"{path_prefix}%")
            if language:
                where_clauses.append(f"c.language = ${len(params) + 1}")
                params.append(language)
            if cluster_id:
                where_clauses.append(f"c.cluster_id = ${len(params) + 1}")
                params.append(cluster_id)
            if route_target:
                where_clauses.append(f"r.route_target = ${len(params) + 1}")
                params.append(route_target)
            if changed_only:
                where_clauses.append("f.change_kind != 'unchanged'")
            if kind:
                where_clauses.append(f"c.kind = ${len(params) + 1}")
                params.append(kind)
            if q:
                where_clauses.append(f"(c.label ILIKE ${len(params) + 1} OR c.preview_text ILIKE ${len(params) + 1})")
                params.append(f"%{q}%")

            offset = self._decode_codebase_cursor(cursor)
            rows = await conn.fetch(
                f"""
                SELECT c.id, c.chunk_key, c.path, c.language, c.kind, c.label, c.preview_text,
                       c.start_line, c.end_line, c.container, c.parent_symbol, c.parent_fq_name,
                       c.parse_confidence, c.cluster_id, c.cluster_label, c.document_id,
                       r.route_target, r.route_source, f.change_kind,
                       (
                           SELECT COUNT(*)
                           FROM {fq_table("codebase_chunk_edges")} e
                           WHERE e.snapshot_id = c.snapshot_id
                             AND e.edge_type = 'related'
                             AND (e.from_chunk_id = c.id OR e.to_chunk_id = c.id)
                       ) AS related_count
                FROM {fq_table("codebase_chunks")} c
                JOIN {fq_table("codebase_review_routes")} r
                  ON r.snapshot_id = c.snapshot_id AND r.chunk_id = c.id
                JOIN {fq_table("codebase_files")} f
                  ON f.snapshot_id = c.snapshot_id AND f.codebase_id = c.codebase_id AND f.bank_id = c.bank_id AND f.path = c.path
                WHERE {" AND ".join(where_clauses)}
                ORDER BY
                    CASE r.route_target
                        WHEN 'unrouted' THEN 0
                        WHEN 'memory' THEN 1
                        WHEN 'research' THEN 2
                        ELSE 3
                    END,
                    CASE f.change_kind
                        WHEN 'modified' THEN 0
                        WHEN 'added' THEN 1
                        ELSE 2
                    END,
                    c.path ASC,
                    c.start_line ASC
                OFFSET ${len(params) + 1}
                LIMIT ${len(params) + 2}
                """,
                *params,
                offset,
                limit + 1,
            )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = self._encode_codebase_cursor(offset + limit) if has_more else None
        return {
            "codebase_id": codebase_id,
            "snapshot_id": effective_snapshot_id,
            "items": [
                {
                    "id": str(row["id"]),
                    "chunk_key": row["chunk_key"],
                    "path": row["path"],
                    "language": row["language"],
                    "kind": row["kind"],
                    "label": row["label"],
                    "preview_text": row["preview_text"],
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                    "container": row["container"],
                    "parent_symbol": row["parent_symbol"],
                    "parent_fq_name": row["parent_fq_name"],
                    "parse_confidence": float(row["parse_confidence"] or 0.0),
                    "cluster_id": row["cluster_id"],
                    "cluster_label": row["cluster_label"],
                    "route_target": row["route_target"],
                    "route_source": row["route_source"],
                    "change_kind": row["change_kind"],
                    "related_count": int(row["related_count"] or 0),
                    "document_id": row["document_id"],
                }
                for row in page
            ],
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    async def get_codebase_chunk_detail(
        self,
        bank_id: str,
        codebase_id: str,
        chunk_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Return detailed review data for one chunk."""
        from atulya_api.extensions import BankReadContext

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankReadContext(
                bank_id=bank_id, operation="get_codebase_chunk_detail", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT c.id, c.snapshot_id, c.chunk_key, c.path, c.language, c.kind, c.label,
                       c.content_text, c.preview_text, c.start_line, c.end_line, c.container,
                       c.parent_symbol, c.parent_fq_name, c.parse_confidence, c.cluster_id, c.cluster_label,
                       c.document_id, r.route_target, r.route_source, f.change_kind
                FROM {fq_table("codebase_chunks")} c
                JOIN {fq_table("codebase_review_routes")} r
                  ON r.snapshot_id = c.snapshot_id AND r.chunk_id = c.id
                JOIN {fq_table("codebase_files")} f
                  ON f.snapshot_id = c.snapshot_id AND f.codebase_id = c.codebase_id AND f.bank_id = c.bank_id AND f.path = c.path
                WHERE c.id = $1 AND c.codebase_id = $2 AND c.bank_id = $3
                """,
                uuid.UUID(chunk_id),
                uuid.UUID(codebase_id),
                bank_id,
            )
            if not row:
                raise ValueError(f"Chunk {chunk_id} not found for codebase {codebase_id}")

            related_rows = await conn.fetch(
                f"""
                SELECT other.id, other.label, other.path, other.kind, other.start_line, other.end_line,
                       other.cluster_label, e.edge_type, e.score
                FROM {fq_table("codebase_chunk_edges")} e
                JOIN {fq_table("codebase_chunks")} other
                  ON (
                       (e.from_chunk_id = $1 AND other.id = e.to_chunk_id)
                    OR (e.to_chunk_id = $1 AND other.id = e.from_chunk_id)
                  )
                WHERE e.snapshot_id = $2 AND e.edge_type = 'related'
                ORDER BY e.score DESC NULLS LAST, other.path ASC, other.start_line ASC
                LIMIT 4
                """,
                uuid.UUID(chunk_id),
                row["snapshot_id"],
            )
            symbol_rows = await conn.fetch(
                f"""
                SELECT name, kind, fq_name, path, language, container, start_line, end_line
                FROM {fq_table("codebase_symbols")}
                WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3 AND path = $4
                  AND start_line <= $5 AND end_line >= $6
                ORDER BY start_line ASC
                LIMIT 8
                """,
                row["snapshot_id"],
                bank_id,
                uuid.UUID(codebase_id),
                row["path"],
                row["end_line"],
                row["start_line"],
            )
            impact_rows = await conn.fetch(
                f"""
                SELECT edge_type, from_path, from_symbol, to_path, to_symbol, target_ref, label
                FROM {fq_table("codebase_edges")}
                WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3
                  AND (from_path = $4 OR to_path = $4)
                ORDER BY from_path ASC, to_path ASC NULLS LAST
                LIMIT 20
                """,
                row["snapshot_id"],
                bank_id,
                uuid.UUID(codebase_id),
                row["path"],
            )
            cluster_rows = []
            if row["cluster_id"]:
                cluster_rows = await conn.fetch(
                    f"""
                    SELECT id, label, path, kind, start_line, end_line
                    FROM {fq_table("codebase_chunks")}
                    WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3 AND cluster_id = $4 AND id != $5
                    ORDER BY path ASC, start_line ASC
                    LIMIT 8
                    """,
                    row["snapshot_id"],
                    bank_id,
                    uuid.UUID(codebase_id),
                    row["cluster_id"],
                    uuid.UUID(chunk_id),
                )
        return {
            "id": str(row["id"]),
            "snapshot_id": str(row["snapshot_id"]),
            "chunk_key": row["chunk_key"],
            "path": row["path"],
            "language": row["language"],
            "kind": row["kind"],
            "label": row["label"],
            "content_text": row["content_text"],
            "preview_text": row["preview_text"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "container": row["container"],
            "parent_symbol": row["parent_symbol"],
            "parent_fq_name": row["parent_fq_name"],
            "parse_confidence": float(row["parse_confidence"] or 0.0),
            "cluster_id": row["cluster_id"],
            "cluster_label": row["cluster_label"],
            "route_target": row["route_target"],
            "route_source": row["route_source"],
            "change_kind": row["change_kind"],
            "document_id": row["document_id"],
            "related_chunks": [
                {
                    "id": str(related["id"]),
                    "label": related["label"],
                    "path": related["path"],
                    "kind": related["kind"],
                    "start_line": related["start_line"],
                    "end_line": related["end_line"],
                    "cluster_label": related["cluster_label"],
                    "score": float(related["score"] or 0.0),
                }
                for related in related_rows
            ],
            "symbols": [
                {
                    "name": symbol["name"],
                    "kind": symbol["kind"],
                    "fq_name": symbol["fq_name"],
                    "path": symbol["path"],
                    "language": symbol["language"],
                    "container": symbol["container"],
                    "start_line": symbol["start_line"],
                    "end_line": symbol["end_line"],
                }
                for symbol in symbol_rows
            ],
            "impact_edges": [
                {
                    "edge_type": edge["edge_type"],
                    "from_path": edge["from_path"],
                    "from_symbol": edge["from_symbol"],
                    "to_path": edge["to_path"],
                    "to_symbol": edge["to_symbol"],
                    "target_ref": edge["target_ref"],
                    "label": edge["label"],
                }
                for edge in impact_rows
            ],
            "cluster_members": [
                {
                    "id": str(item["id"]),
                    "label": item["label"],
                    "path": item["path"],
                    "kind": item["kind"],
                    "start_line": item["start_line"],
                    "end_line": item["end_line"],
                }
                for item in cluster_rows
            ],
        }

    async def route_codebase_review_items(
        self,
        bank_id: str,
        codebase_id: str,
        *,
        item_ids: list[str],
        target: str,
        queue_memory_import: bool = False,
        memory_ingest_mode: str = "direct",
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Route review chunks to memory, research, or dismissed."""
        from atulya_api.extensions import BankWriteContext

        if target not in {"memory", "research", "dismissed", "unrouted"}:
            raise ValueError("target must be one of memory, research, dismissed, or unrouted")
        if not item_ids:
            raise ValueError("item_ids is required")
        if memory_ingest_mode not in {"direct", "retain"}:
            raise ValueError("memory_ingest_mode must be direct or retain")

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankWriteContext(
                bank_id=bank_id, operation="route_codebase_review_items", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            snapshot_row = await conn.fetchrow(
                f"SELECT current_snapshot_id FROM {fq_table('codebases')} WHERE id = $1 AND bank_id = $2",
                uuid.UUID(codebase_id),
                bank_id,
            )
            if not snapshot_row or not snapshot_row["current_snapshot_id"]:
                raise ValueError(f"Codebase {codebase_id} has no active snapshot")
            snapshot_id = str(snapshot_row["current_snapshot_id"])
            async with conn.transaction():
                await conn.execute(
                    f"""
                    UPDATE {fq_table("codebase_review_routes")}
                    SET route_target = $4,
                        route_source = 'manual',
                        updated_at = NOW()
                    WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3 AND chunk_id = ANY($5::uuid[])
                    """,
                    uuid.UUID(snapshot_id),
                    bank_id,
                    uuid.UUID(codebase_id),
                    target,
                    [uuid.UUID(item_id) for item_id in item_ids],
                )
                review_counts = await self._refresh_codebase_review_stats(
                    conn,
                    bank_id=bank_id,
                    codebase_id=codebase_id,
                    snapshot_id=snapshot_id,
                )
        operation_id: str | None = None
        queued_for_memory = False
        if target == "memory" and queue_memory_import:
            approval = await self.submit_async_codebase_approval(
                bank_id,
                codebase_id,
                snapshot_id=snapshot_id,
                memory_ingest_mode=memory_ingest_mode,
                request_context=request_context,
            )
            operation_id = approval["operation_id"]
            queued_for_memory = True
        return {
            "codebase_id": codebase_id,
            "snapshot_id": snapshot_id,
            "updated_count": len(item_ids),
            "target": target,
            "operation_id": operation_id,
            "queued_for_memory": queued_for_memory,
            "memory_ingest_mode": memory_ingest_mode,
            "review_counts": review_counts,
        }

    async def list_codebase_research_queue(
        self,
        bank_id: str,
        codebase_id: str,
        *,
        cursor: str | None = None,
        limit: int = 25,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Return chunks routed to the research queue."""
        return await self.list_codebase_chunks(
            bank_id,
            codebase_id,
            route_target="research",
            cursor=cursor,
            limit=limit,
            request_context=request_context,
        )

    async def list_codebase_files(
        self,
        bank_id: str,
        codebase_id: str,
        *,
        path_prefix: str | None = None,
        language: str | None = None,
        changed_only: bool = False,
        snapshot_id: str | None = None,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """List files in the current or selected codebase snapshot."""
        from atulya_api.extensions import BankReadContext

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankReadContext(bank_id=bank_id, operation="list_codebase_files", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            codebase = await conn.fetchrow(
                f"SELECT current_snapshot_id, name FROM {fq_table('codebases')} WHERE id = $1 AND bank_id = $2",
                uuid.UUID(codebase_id),
                bank_id,
            )
            if not codebase:
                raise ValueError(f"Codebase {codebase_id} not found in bank {bank_id}")
            effective_snapshot_id = snapshot_id or (
                str(codebase["current_snapshot_id"]) if codebase["current_snapshot_id"] else None
            )
            if not effective_snapshot_id:
                return {
                    "codebase_id": codebase_id,
                    "snapshot_id": None,
                    "source_ref": None,
                    "source_commit_sha": None,
                    "snapshot_status": None,
                    "items": [],
                }

            snapshot_row = await conn.fetchrow(
                f"""
                SELECT source_ref, source_commit_sha, status
                FROM {fq_table("codebase_snapshots")}
                WHERE id = $1 AND codebase_id = $2 AND bank_id = $3
                """,
                uuid.UUID(effective_snapshot_id),
                uuid.UUID(codebase_id),
                bank_id,
            )

            where_clauses = ["snapshot_id = $1", "bank_id = $2", "codebase_id = $3"]
            params: list[Any] = [uuid.UUID(effective_snapshot_id), bank_id, uuid.UUID(codebase_id)]
            if path_prefix:
                where_clauses.append(f"path LIKE ${len(params) + 1}")
                params.append(f"{path_prefix}%")
            if language:
                where_clauses.append(f"language = ${len(params) + 1}")
                params.append(language)
            if changed_only:
                where_clauses.append("change_kind != 'unchanged'")

            rows = await conn.fetch(
                f"""
                SELECT path, language, size_bytes, content_hash, document_id, status, change_kind, reason,
                       (
                           SELECT COUNT(*)
                           FROM {fq_table("codebase_chunks")} c
                           WHERE c.snapshot_id = {fq_table("codebase_files")}.snapshot_id
                             AND c.bank_id = {fq_table("codebase_files")}.bank_id
                             AND c.codebase_id = {fq_table("codebase_files")}.codebase_id
                             AND c.path = {fq_table("codebase_files")}.path
                       ) AS chunk_count
                FROM {fq_table("codebase_files")}
                WHERE {" AND ".join(where_clauses)}
                ORDER BY path ASC
                """,
                *params,
            )
        return {
            "codebase_id": codebase_id,
            "snapshot_id": effective_snapshot_id,
            "source_ref": snapshot_row["source_ref"] if snapshot_row else None,
            "source_commit_sha": snapshot_row["source_commit_sha"] if snapshot_row else None,
            "snapshot_status": snapshot_row["status"] if snapshot_row else None,
            "items": [
                {
                    "path": row["path"],
                    "language": row["language"],
                    "size_bytes": row["size_bytes"],
                    "content_hash": row["content_hash"],
                    "document_id": row["document_id"],
                    "status": row["status"],
                    "change_kind": row["change_kind"],
                    "reason": row["reason"],
                    "chunk_count": int(row["chunk_count"] or 0),
                }
                for row in rows
            ],
        }

    async def search_codebase_symbols(
        self,
        bank_id: str,
        codebase_id: str,
        *,
        q: str,
        kind: str | None = None,
        path_prefix: str | None = None,
        language: str | None = None,
        limit: int = 50,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Search deterministic codebase symbols by exact, prefix, and fuzzy match."""
        from atulya_api.extensions import BankReadContext

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankReadContext(bank_id=bank_id, operation="search_codebase_symbols", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            codebase = await conn.fetchrow(
                f"SELECT current_snapshot_id FROM {fq_table('codebases')} WHERE id = $1 AND bank_id = $2",
                uuid.UUID(codebase_id),
                bank_id,
            )
            if not codebase:
                raise ValueError(f"Codebase {codebase_id} not found in bank {bank_id}")
            if not codebase["current_snapshot_id"]:
                return {"codebase_id": codebase_id, "snapshot_id": None, "items": []}

            where_clauses = ["snapshot_id = $1", "bank_id = $2", "codebase_id = $3"]
            params: list[Any] = [codebase["current_snapshot_id"], bank_id, uuid.UUID(codebase_id)]
            if kind:
                where_clauses.append(f"kind = ${len(params) + 1}")
                params.append(kind)
            if path_prefix:
                where_clauses.append(f"path LIKE ${len(params) + 1}")
                params.append(f"{path_prefix}%")
            if language:
                where_clauses.append(f"language = ${len(params) + 1}")
                params.append(language)

            params.extend([q, f"{q}%", f"%{q}%"])
            query = f"""
                SELECT path, language, name, kind, fq_name, container, start_line, end_line,
                       (
                           SELECT array_agg(c.id::text ORDER BY c.start_line ASC)
                           FROM {fq_table("codebase_chunks")} c
                           WHERE c.snapshot_id = {fq_table("codebase_symbols")}.snapshot_id
                             AND c.bank_id = {fq_table("codebase_symbols")}.bank_id
                             AND c.codebase_id = {fq_table("codebase_symbols")}.codebase_id
                             AND c.path = {fq_table("codebase_symbols")}.path
                             AND c.start_line <= {fq_table("codebase_symbols")}.end_line
                             AND c.end_line >= {fq_table("codebase_symbols")}.start_line
                       ) AS chunk_ids,
                       CASE
                           WHEN name = ${len(params) - 2} OR fq_name = ${len(params) - 2} THEN 'exact'
                           WHEN name LIKE ${len(params) - 1} OR fq_name LIKE ${len(params) - 1} THEN 'prefix'
                           ELSE 'fuzzy'
                       END AS match_mode,
                       CASE
                           WHEN name = ${len(params) - 2} OR fq_name = ${len(params) - 2} THEN 3
                           WHEN name LIKE ${len(params) - 1} OR fq_name LIKE ${len(params) - 1} THEN 2
                           ELSE 1
                       END AS match_rank
                FROM {fq_table("codebase_symbols")}
                WHERE {" AND ".join(where_clauses)}
                  AND (
                      name = ${len(params) - 2}
                      OR fq_name = ${len(params) - 2}
                      OR name LIKE ${len(params) - 1}
                      OR fq_name LIKE ${len(params) - 1}
                      OR name ILIKE ${len(params)}
                      OR fq_name ILIKE ${len(params)}
                  )
                ORDER BY match_rank DESC, path ASC, start_line ASC
                LIMIT ${len(params) + 1}
            """
            rows = await conn.fetch(query, *params, limit)
            snapshot_id = str(codebase["current_snapshot_id"])
        return {
            "codebase_id": codebase_id,
            "snapshot_id": snapshot_id,
            "items": [
                {
                    "name": row["name"],
                    "kind": row["kind"],
                    "fq_name": row["fq_name"],
                    "path": row["path"],
                    "language": row["language"],
                    "container": row["container"],
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                    "match_mode": row["match_mode"],
                    "chunk_ids": list(row["chunk_ids"] or []),
                }
                for row in rows
            ],
        }

    async def analyze_codebase_impact(
        self,
        bank_id: str,
        codebase_id: str,
        *,
        path: str | None = None,
        symbol: str | None = None,
        query: str | None = None,
        max_depth: int = 2,
        limit: int = 50,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Run deterministic impact analysis over codebase import edges."""
        from atulya_api.extensions import BankReadContext

        provided = [value for value in (path, symbol, query) if value]
        if len(provided) != 1:
            raise ValueError("Exactly one of path, symbol, or query is required.")

        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            ctx = BankReadContext(bank_id=bank_id, operation="analyze_codebase_impact", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            codebase = await conn.fetchrow(
                f"SELECT current_snapshot_id FROM {fq_table('codebases')} WHERE id = $1 AND bank_id = $2",
                uuid.UUID(codebase_id),
                bank_id,
            )
            if not codebase:
                raise ValueError(f"Codebase {codebase_id} not found in bank {bank_id}")
            snapshot_id = codebase["current_snapshot_id"]
            if not snapshot_id:
                return {
                    "codebase_id": codebase_id,
                    "snapshot_id": None,
                    "seed": None,
                    "impacted_files": [],
                    "matched_symbols": [],
                    "edges": [],
                    "explanation": "No snapshot has been imported for this codebase yet.",
                }

            file_rows = await conn.fetch(
                f"""
                SELECT path, language, size_bytes, content_hash, document_id, status, change_kind
                FROM {fq_table("codebase_files")}
                WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3
                """,
                snapshot_id,
                bank_id,
                uuid.UUID(codebase_id),
            )
            edge_rows = await conn.fetch(
                f"""
                SELECT edge_type, from_path, from_symbol, to_path, to_symbol, target_ref, label
                FROM {fq_table("codebase_edges")}
                WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3 AND edge_type = 'imports'
                """,
                snapshot_id,
                bank_id,
                uuid.UUID(codebase_id),
            )
            chunk_count_rows = await conn.fetch(
                f"""
                SELECT path, COUNT(*) AS chunk_count
                FROM {fq_table("codebase_chunks")}
                WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3
                GROUP BY path
                """,
                snapshot_id,
                bank_id,
                uuid.UUID(codebase_id),
            )
            file_map = {row["path"]: row for row in file_rows}
            chunk_count_by_path = {row["path"]: int(row["chunk_count"] or 0) for row in chunk_count_rows}

            matched_symbols: list[dict[str, Any]] = []
            seed_paths: list[str] = []
            seed_description = None

            if path:
                normalized_path = path.replace("\\", "/").lstrip("/")
                if normalized_path not in file_map:
                    raise ValueError(f"Path not found in codebase snapshot: {path}")
                seed_paths = [normalized_path]
                seed_description = {"type": "path", "value": normalized_path}
                symbol_rows = await conn.fetch(
                    f"""
                    SELECT name, kind, fq_name, path, language, container, start_line, end_line
                    FROM {fq_table("codebase_symbols")}
                    WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3 AND path = $4
                    ORDER BY start_line ASC
                    LIMIT $5
                    """,
                    snapshot_id,
                    bank_id,
                    uuid.UUID(codebase_id),
                    normalized_path,
                    min(limit, 25),
                )
                matched_symbols = [
                    {
                        "name": row["name"],
                        "kind": row["kind"],
                        "fq_name": row["fq_name"],
                        "path": row["path"],
                        "language": row["language"],
                        "container": row["container"],
                        "start_line": row["start_line"],
                        "end_line": row["end_line"],
                    }
                    for row in symbol_rows
                ]
            else:
                lookup = symbol or query or ""
                symbol_rows = await conn.fetch(
                    f"""
                    SELECT name, kind, fq_name, path, language, container, start_line, end_line
                    FROM {fq_table("codebase_symbols")}
                    WHERE snapshot_id = $1 AND bank_id = $2 AND codebase_id = $3
                      AND (
                          name = $4
                          OR fq_name = $4
                          OR name ILIKE $5
                          OR fq_name ILIKE $5
                      )
                    ORDER BY CASE WHEN name = $4 OR fq_name = $4 THEN 0 ELSE 1 END, path ASC, start_line ASC
                    LIMIT $6
                    """,
                    snapshot_id,
                    bank_id,
                    uuid.UUID(codebase_id),
                    lookup,
                    f"%{lookup}%",
                    min(limit, 25),
                )
                if symbol_rows:
                    matched_symbols = [
                        {
                            "name": row["name"],
                            "kind": row["kind"],
                            "fq_name": row["fq_name"],
                            "path": row["path"],
                            "language": row["language"],
                            "container": row["container"],
                            "start_line": row["start_line"],
                            "end_line": row["end_line"],
                        }
                        for row in symbol_rows
                    ]
                    seed_paths = sorted({row["path"] for row in symbol_rows})
                    seed_description = {"type": "symbol" if symbol else "query", "value": lookup}
                else:
                    path_matches = [row["path"] for row in file_rows if lookup.lower() in row["path"].lower()][
                        : min(limit, 10)
                    ]
                    if not path_matches:
                        return {
                            "codebase_id": codebase_id,
                            "snapshot_id": str(snapshot_id),
                            "seed": {"type": "query", "value": lookup},
                            "impacted_files": [],
                            "matched_symbols": [],
                            "edges": [],
                            "explanation": f"No file path or symbol matched '{lookup}'.",
                        }
                    seed_paths = path_matches
                    seed_description = {"type": "query", "value": lookup}

            reverse_edges: dict[str, list[dict[str, Any]]] = {}
            for row in edge_rows:
                if row["to_path"]:
                    reverse_edges.setdefault(row["to_path"], []).append(
                        {
                            "edge_type": row["edge_type"],
                            "from_path": row["from_path"],
                            "from_symbol": row["from_symbol"],
                            "to_path": row["to_path"],
                            "to_symbol": row["to_symbol"],
                            "target_ref": row["target_ref"],
                            "label": row["label"],
                        }
                    )

            visited_depth: dict[str, int] = {}
            traversed_edges: list[dict[str, Any]] = []
            queue: list[tuple[str, int]] = [(seed_path, 0) for seed_path in seed_paths]
            while queue:
                current_path, depth = queue.pop(0)
                if current_path in visited_depth and visited_depth[current_path] <= depth:
                    continue
                visited_depth[current_path] = depth
                if depth >= max_depth:
                    continue
                for edge in reverse_edges.get(current_path, []):
                    traversed_edges.append(dict(edge))
                    upstream = edge["from_path"]
                    if upstream not in visited_depth or visited_depth[upstream] > depth + 1:
                        queue.append((upstream, depth + 1))

            ordered_paths = sorted(visited_depth, key=lambda candidate: (visited_depth[candidate], candidate))
            impacted_files = [
                {
                    "path": file_map[path_value]["path"],
                    "language": file_map[path_value]["language"],
                    "size_bytes": file_map[path_value]["size_bytes"],
                    "content_hash": file_map[path_value]["content_hash"],
                    "document_id": file_map[path_value]["document_id"],
                    "status": file_map[path_value]["status"],
                    "change_kind": file_map[path_value]["change_kind"],
                    "chunk_count": chunk_count_by_path.get(path_value, 0),
                    "depth": visited_depth[path_value],
                }
                for path_value in ordered_paths[:limit]
                if path_value in file_map
            ]

        explanation = (
            f"Seeded impact analysis from {seed_description['type']} '{seed_description['value']}'. "
            f"Traversed reverse import edges up to depth {max_depth} and found {len(impacted_files)} impacted files."
        )
        return {
            "codebase_id": codebase_id,
            "snapshot_id": str(snapshot_id),
            "seed": seed_description,
            "impacted_files": impacted_files,
            "matched_symbols": matched_symbols,
            "edges": traversed_edges[: limit * 4],
            "explanation": explanation,
        }

    async def submit_async_retain(
        self,
        bank_id: str,
        contents: list[dict[str, Any]],
        *,
        request_context: "RequestContext",
        document_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Submit a batch retain operation to run asynchronously.

        For large batches (exceeding retain_batch_chars threshold), automatically splits
        into smaller sub-batches and creates a parent operation that tracks all children.
        """
        await self._authenticate_tenant(request_context)

        # Run operation validator (bank access, credits, etc.) before queuing
        if self._operation_validator:
            from atulya_api.extensions import RetainContext

            ctx = RetainContext(
                bank_id=bank_id,
                contents=[dict(c) for c in contents],
                request_context=request_context,
            )
            await self._validate_operation(self._operation_validator.validate_retain(ctx))

        # Validate no duplicate document_ids in the batch
        # Having duplicate document_ids causes race conditions in document upserts during parallel processing
        doc_ids = [item.get("document_id") for item in contents if item.get("document_id")]
        if len(doc_ids) != len(set(doc_ids)):
            from collections import Counter

            duplicates = [doc_id for doc_id, count in Counter(doc_ids).items() if count > 1]
            raise ValueError(
                f"Batch contains duplicate document_ids: {duplicates}. "
                f"Each content item in a batch must have a unique document_id to avoid race conditions."
            )

        # Calculate total token count and determine if we need to split
        total_tokens = sum(count_tokens(item.get("content", "")) for item in contents)
        config = get_config()
        tokens_per_batch = config.retain_batch_tokens

        # Split into sub-batches based on token count
        sub_batches = []
        current_batch = []
        current_batch_tokens = 0

        for item in contents:
            item_tokens = count_tokens(item.get("content", ""))

            # If adding this item would exceed the limit, start a new batch
            # (unless current batch is empty - then we must include it even if it's large)
            if current_batch and current_batch_tokens + item_tokens > tokens_per_batch:
                sub_batches.append(current_batch)
                current_batch = [item]
                current_batch_tokens = item_tokens
            else:
                current_batch.append(item)
                current_batch_tokens += item_tokens

        # Add the last batch
        if current_batch:
            sub_batches.append(current_batch)

        # Log splitting info if we actually split
        if len(sub_batches) > 1:
            logger.info(
                f"Large async retain batch ({total_tokens:,} tokens from {len(contents)} items). "
                f"Split into {len(sub_batches)} sub-batches: {[len(b) for b in sub_batches]} items each"
            )

        # Always create parent operation (even for single batch - simpler, more reliable code path)
        import uuid

        parent_operation_id = uuid.uuid4()
        pool = await self._get_pool()

        # Create typed metadata for parent operation
        parent_metadata = BatchRetainParentMetadata(
            items_count=len(contents),
            total_tokens=total_tokens,
            num_sub_batches=len(sub_batches),
        )

        async with acquire_with_retry(pool) as conn:
            await conn.execute(
                f"""
                INSERT INTO {fq_table("async_operations")} (operation_id, bank_id, operation_type, result_metadata, status)
                VALUES ($1, $2, $3, $4, $5)
                """,
                parent_operation_id,
                bank_id,
                "batch_retain",
                json.dumps(parent_metadata.to_dict()),
                "pending",  # Will be updated by status aggregation
            )

        logger.info(f"Created parent operation {parent_operation_id} for {len(sub_batches)} sub-batch(es)")

        # Submit child operations for each sub-batch
        for i, sub_batch in enumerate(sub_batches, 1):
            if len(sub_batches) > 1:
                sub_batch_tokens = sum(count_tokens(item.get("content", "")) for item in sub_batch)
                logger.info(
                    f"Submitting sub-batch {i}/{len(sub_batches)}: {len(sub_batch)} items, {sub_batch_tokens:,} tokens"
                )

            task_payload: dict[str, Any] = {"contents": sub_batch}
            if document_tags:
                task_payload["document_tags"] = document_tags
            # Pass tenant_id and api_key_id through task payload
            if request_context.tenant_id:
                task_payload["_tenant_id"] = request_context.tenant_id
            if request_context.api_key_id:
                task_payload["_api_key_id"] = request_context.api_key_id

            # Create typed metadata for child operation
            child_metadata = BatchRetainChildMetadata(
                items_count=len(sub_batch),
                parent_operation_id=str(parent_operation_id),
                sub_batch_index=i,
                total_sub_batches=len(sub_batches),
            )

            # Create child operation with reference to parent
            await self._submit_async_operation(
                bank_id=bank_id,
                operation_type="retain",
                task_type="batch_retain",
                task_payload=task_payload,
                result_metadata=child_metadata.to_dict(),
                dedupe_by_bank=False,
            )

        return {
            "operation_id": str(parent_operation_id),
            "items_count": len(contents),
        }

    async def submit_async_file_retain(
        self,
        bank_id: str,
        file_items: list[dict[str, Any]],
        document_tags: list[str] | None,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """
        Submit batch file conversion + retain operation.

        Each file is converted to markdown and then retained as a memory.
        Files are stored in object storage and conversion happens asynchronously.

        Args:
            bank_id: Bank ID
            file_items: List of file items, each containing:
                - file: UploadFile object (FastAPI)
                - document_id: Document ID
                - context: Optional context
                - metadata: Optional metadata dict
                - tags: Optional tags list
                - timestamp: Optional timestamp
                - parser: Ordered list of parser names to try (fallback chain)
            document_tags: Tags applied to all documents
            request_context: Request context for authentication

        Returns:
            dict with operation_id and files_count
        """
        await self._authenticate_tenant(request_context)

        config = get_config()

        # Validate file count
        if len(file_items) > config.file_conversion_max_batch_size:
            raise ValueError(f"Too many files. Maximum {config.file_conversion_max_batch_size} files per request.")

        # Read all files and validate total batch size
        files_data = []
        total_batch_size = 0

        for item in file_items:
            file = item["file"]
            file_data = await file.read()
            total_batch_size += len(file_data)
            files_data.append((item, file, file_data))

        # Validate total batch size
        if total_batch_size > config.file_conversion_max_batch_size_bytes:
            total_mb = total_batch_size / (1024 * 1024)
            raise ValueError(
                f"Total batch size ({total_mb:.1f}MB) exceeds maximum of {config.file_conversion_max_batch_size_mb}MB"
            )

        # Submit individual operation for each file
        operation_ids = []
        for item, file, file_data in files_data:
            # Generate storage key
            storage_key = f"banks/{bank_id}/files/{item['document_id']}/{file.filename}"

            # Store file in object storage
            await self._file_storage.store(
                file_data=file_data,
                key=storage_key,
                metadata={
                    "content_type": file.content_type or "application/octet-stream",
                    "original_filename": file.filename,
                    "bank_id": bank_id,
                    "document_id": item["document_id"],
                },
            )

            # Create individual operation and submit task
            task_payload: dict[str, Any] = {
                "document_id": item["document_id"],
                "storage_key": storage_key,
                "original_filename": file.filename,
                "content_type": file.content_type or "application/octet-stream",
                "parser": item["parser"],
                "context": item.get("context"),
                "metadata": item.get("metadata", {}),
                "tags": item.get("tags", []),
                "document_tags": document_tags or [],
                "timestamp": item.get("timestamp"),
            }

            # Pass tenant_id and api_key_id through task payload
            if request_context.tenant_id:
                task_payload["_tenant_id"] = request_context.tenant_id
            if request_context.api_key_id:
                task_payload["_api_key_id"] = request_context.api_key_id

            result = await self._submit_async_operation(
                bank_id=bank_id,
                operation_type="file_convert_retain",
                task_type="file_convert_retain",
                task_payload=task_payload,
                result_metadata={
                    "original_filename": file.filename,
                },
                dedupe_by_bank=False,
            )
            operation_ids.append(result["operation_id"])

        return {
            "operation_ids": operation_ids,
            "files_count": len(file_items),
        }

    async def submit_async_consolidation(
        self,
        bank_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Submit a consolidation operation to run asynchronously.

        Deduplicates by bank_id - if there's already a pending consolidation for this bank,
        returns the existing operation_id instead of creating a new one.

        Args:
            bank_id: Bank identifier
            request_context: Request context for authentication

        Returns:
            Dict with operation_id
        """
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(
                bank_id=bank_id, operation="submit_async_consolidation", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))

        # Pass tenant_id and api_key_id through task payload so the worker
        # can provide request context to extension hooks (e.g., usage metering
        # for mental model refreshes triggered by consolidation).
        task_payload: dict[str, Any] = {}
        if request_context.tenant_id:
            task_payload["_tenant_id"] = request_context.tenant_id
        if request_context.api_key_id:
            task_payload["_api_key_id"] = request_context.api_key_id

        return await self._submit_async_operation(
            bank_id=bank_id,
            operation_type="consolidation",
            task_type="consolidation",
            task_payload=task_payload,
            dedupe_by_bank=True,
        )

    async def submit_async_reflect(
        self,
        bank_id: str,
        *,
        query: str,
        budget: Budget | None = None,
        max_tokens: int = 4096,
        include_facts: bool = False,
        include_tool_calls: bool = False,
        include_tool_call_output: bool = True,
        response_schema: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        tags_match: str = "any",
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Submit a reflect operation to run asynchronously."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import ReflectContext

            ctx = ReflectContext(
                bank_id=bank_id,
                query=query,
                request_context=request_context,
                budget=budget,
                context=None,
            )
            await self._validate_operation(self._operation_validator.validate_reflect(ctx))

        task_payload: dict[str, Any] = {
            "query": query,
            "budget": budget.value if budget else None,
            "max_tokens": max_tokens,
            "include_facts": include_facts,
            "include_tool_calls": include_tool_calls,
            "include_tool_call_output": include_tool_call_output,
            "response_schema": response_schema,
            "tags": tags,
            "tags_match": tags_match,
        }
        if request_context.tenant_id:
            task_payload["_tenant_id"] = request_context.tenant_id
        if request_context.api_key_id:
            task_payload["_api_key_id"] = request_context.api_key_id

        return await self._submit_async_operation(
            bank_id=bank_id,
            operation_type="reflect",
            task_type="reflect",
            task_payload=task_payload,
            result_metadata={
                "query_preview": f"{query[:117]}..." if len(query) > 120 else query,
                "budget": budget.value if budget else None,
                "max_tokens": max_tokens,
                "include_facts": include_facts,
                "include_tool_calls": include_tool_calls,
                "tags": tags,
                "tags_match": tags_match,
            },
            dedupe_by_bank=False,
        )

    async def submit_async_refresh_mental_model(
        self,
        bank_id: str,
        mental_model_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Submit an async mental model refresh operation.

        This schedules a background task to re-run the source query and update the content.

        Args:
            bank_id: Bank identifier
            mental_model_id: Mental model UUID to refresh
            request_context: Request context for authentication

        Returns:
            Dict with operation_id
        """
        await self._authenticate_tenant(request_context)

        # Pre-operation validation (credit check)
        if self._operation_validator:
            from atulya_api.extensions.operation_validator import MentalModelRefreshContext

            ctx = MentalModelRefreshContext(
                bank_id=bank_id,
                mental_model_id=mental_model_id,
                request_context=request_context,
            )
            await self._validate_operation(self._operation_validator.validate_mental_model_refresh(ctx))

        # Verify mental model exists
        mental_model = await self.get_mental_model(bank_id, mental_model_id, request_context=request_context)
        if not mental_model:
            raise ValueError(f"Mental model {mental_model_id} not found in bank {bank_id}")

        # Pass tenant_id and api_key_id through task payload so the worker
        # can provide request context to extension hooks.
        task_payload: dict[str, Any] = {
            "mental_model_id": mental_model_id,
        }
        if request_context.tenant_id:
            task_payload["_tenant_id"] = request_context.tenant_id
        if request_context.api_key_id:
            task_payload["_api_key_id"] = request_context.api_key_id

        return await self._submit_async_operation(
            bank_id=bank_id,
            operation_type="refresh_mental_model",
            task_type="refresh_mental_model",
            task_payload=task_payload,
            result_metadata={"mental_model_id": mental_model_id, "name": mental_model["name"]},
            dedupe_by_bank=False,
        )

    async def submit_async_sub_routine(
        self,
        bank_id: str,
        *,
        mode: str = "incremental",
        horizon_hours: int = 24,
        force_rebuild: bool = False,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Submit a sub_routine operation to run asynchronously."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(
                bank_id=bank_id, operation="submit_async_sub_routine", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))

        task_payload: dict[str, Any] = {
            "mode": mode,
            "horizon_hours": horizon_hours,
            "force_rebuild": force_rebuild,
        }
        dedupe_key = f"{bank_id}:{mode}:{horizon_hours}:{int(force_rebuild)}"
        if request_context.tenant_id:
            task_payload["_tenant_id"] = request_context.tenant_id
        if request_context.api_key_id:
            task_payload["_api_key_id"] = request_context.api_key_id

        return await self._submit_async_operation(
            bank_id=bank_id,
            operation_type="sub_routine",
            task_type="sub_routine",
            task_payload=task_payload,
            result_metadata={"mode": mode, "horizon_hours": horizon_hours, "force_rebuild": force_rebuild},
            dedupe_by_bank=True,
            dedupe_key=dedupe_key,
        )

    async def submit_async_dream_generation(
        self,
        bank_id: str,
        *,
        request_context: "RequestContext",
        trigger_source: str = "manual",
        run_type: str = "dream",
    ) -> dict[str, Any]:
        """Submit a dream generation operation to run asynchronously."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(
                bank_id=bank_id, operation="submit_async_dream_generation", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))

        task_payload: dict[str, Any] = {
            "trigger_source": trigger_source,
            "run_type": run_type,
        }
        if request_context.tenant_id:
            task_payload["_tenant_id"] = request_context.tenant_id
        if request_context.api_key_id:
            task_payload["_api_key_id"] = request_context.api_key_id
        dedupe_key = f"{bank_id}:{trigger_source}:{run_type}"
        return await self._submit_async_operation(
            bank_id=bank_id,
            operation_type="dream_generation",
            task_type="dream_generation",
            task_payload=task_payload,
            result_metadata={"trigger_source": trigger_source, "run_type": run_type},
            dedupe_by_bank=True,
            dedupe_key=dedupe_key,
        )

    async def _assemble_dream_runs(
        self,
        run_rows: list[Any],
    ) -> list[dict[str, Any]]:
        if not run_rows:
            return []
        run_ids = [str(row["id"]) for row in run_rows]
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            prediction_rows = await conn.fetch(
                f"""
                SELECT id, run_id, title, description, target_ref, target_kind, horizon, confidence,
                       success_criteria, expiration_window_days, status, supporting_evidence_ids,
                       validation_notes, created_at, updated_at
                FROM {fq_table("dream_predictions")}
                WHERE run_id = ANY($1::uuid[])
                ORDER BY created_at ASC
                """,
                [uuid.UUID(item) for item in run_ids],
            )
            proposal_rows = await conn.fetch(
                f"""
                SELECT id, run_id, proposal_type, title, content, confidence, tags,
                       supporting_evidence_ids, review_status, rationale, reviewed_at, created_at
                FROM {fq_table("dream_proposals")}
                WHERE run_id = ANY($1::uuid[])
                ORDER BY created_at ASC
                """,
                [uuid.UUID(item) for item in run_ids],
            )
        prediction_ids = [str(row["id"]) for row in prediction_rows]
        outcomes_by_prediction = await self._list_dream_validation_outcomes_by_prediction(prediction_ids)

        predictions_by_run: dict[str, list[DreamPrediction]] = {}
        outcomes_by_run: dict[str, list[DreamValidationOutcome]] = {}
        for row in prediction_rows:
            prediction = DreamPrediction(
                prediction_id=str(row["id"]),
                title=row["title"],
                description=row["description"],
                target_ref=row["target_ref"],
                target_kind=row["target_kind"],
                horizon=row["horizon"],
                confidence=float(row["confidence"] or 0.0),
                success_criteria=decode_jsonb(row["success_criteria"], []),
                expiration_window_days=int(row["expiration_window_days"] or 14),
                status=row["status"],
                supporting_evidence_ids=decode_jsonb(row["supporting_evidence_ids"], []),
                validation_notes=row["validation_notes"],
            )
            run_id = str(row["run_id"])
            predictions_by_run.setdefault(run_id, []).append(prediction)
            outcomes_by_run.setdefault(run_id, []).extend(outcomes_by_prediction.get(str(row["id"]), []))

        proposals_by_run: dict[str, list[DreamPromotionProposal]] = {}
        for row in proposal_rows:
            run_id = str(row["run_id"])
            proposals_by_run.setdefault(run_id, []).append(
                DreamPromotionProposal(
                    proposal_id=str(row["id"]),
                    proposal_type=row["proposal_type"],
                    title=row["title"],
                    content=row["content"],
                    confidence=float(row["confidence"] or 0.0),
                    tags=decode_jsonb(row["tags"], []),
                    supporting_evidence_ids=decode_jsonb(row["supporting_evidence_ids"], []),
                    review_status=row["review_status"],
                    rationale=row["rationale"],
                )
            )

        items: list[dict[str, Any]] = []
        for row in run_rows:
            run_id = str(row["id"])
            record = DreamRunRecord(
                run_id=run_id,
                bank_id=row["bank_id"],
                status=row["status"],
                run_type=row["run_type"],
                trigger_source=row["trigger_source"],
                created_at=row["created_at"].isoformat() if row["created_at"] else datetime.now(UTC).isoformat(),
                updated_at=row["updated_at"].isoformat() if row["updated_at"] else None,
                narrative_html=row["narrative_html"],
                summary=row["summary"],
                evidence_basis=DreamEvidenceBasis.model_validate(decode_jsonb(row["evidence_basis"], {})),
                signals=DreamSignals.model_validate(decode_jsonb(row["signals"], {})),
                predictions=predictions_by_run.get(run_id, []),
                growth_hypotheses=[
                    DreamGrowthHypothesis.model_validate(item)
                    for item in decode_jsonb(row["result_metadata"], {}).get("growth_hypotheses", [])
                ],
                promotion_proposals=proposals_by_run.get(run_id, []),
                validation_outcomes=outcomes_by_run.get(run_id, []),
                confidence=DreamConfidenceModel.model_validate(decode_jsonb(row["confidence"], {})),
                novelty_score=float(row["novelty_score"] or 0.0),
                maturity_tier=row["maturity_tier"],
                failure_reason=row["failure_reason"],
                quality_score=float(row["quality_score"] or 0.0),
                source_artifact_id=str(row["source_artifact_id"]) if row["source_artifact_id"] else None,
            )
            items.append(record.model_dump(mode="json"))
        return items

    def _legacy_artifact_to_dream_run(self, row: dict[str, Any]) -> dict[str, Any]:
        quality_score = float(row.get("quality_score") or 0.0)
        return DreamRunRecord(
            run_id=f"legacy:{row['id']}",
            bank_id=row["bank_id"],
            status="success",
            run_type=row["run_type"],
            trigger_source=row["trigger_source"],
            created_at=row["created_at"].isoformat() if row.get("created_at") else datetime.now(UTC).isoformat(),
            narrative_html=row["html_blob"],
            summary="Legacy narrative-only dream run.",
            confidence=DreamConfidenceModel(overall=quality_score, novelty_score=0.0),
            novelty_score=0.0,
            maturity_tier="sparse",
            quality_score=quality_score,
            legacy_run=True,
            source_artifact_id=str(row["id"]),
        ).model_dump(mode="json")

    async def list_dream_artifacts(
        self,
        bank_id: str,
        *,
        limit: int = 20,
        request_context: "RequestContext",
    ) -> list[dict[str, Any]]:
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="list_dream_artifacts", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            run_rows = await conn.fetch(
                f"""
                SELECT id, bank_id, run_type, trigger_source, status, summary, narrative_html,
                       evidence_basis, signals, confidence, novelty_score, maturity_tier,
                       quality_score, result_metadata, failure_reason, source_artifact_id,
                       created_at, updated_at
                FROM {fq_table("dream_runs")}
                WHERE bank_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                bank_id,
                max(1, min(limit, 100)),
            )
            artifact_rows = await conn.fetch(
                f"""
                SELECT id, bank_id, run_type, trigger_source, html_blob, input_refs, stats, quality_score, distilled_written, created_at
                FROM {fq_table("dream_artifacts")}
                WHERE bank_id = $1
                  AND id NOT IN (
                      SELECT source_artifact_id
                      FROM {fq_table("dream_runs")}
                      WHERE bank_id = $1 AND source_artifact_id IS NOT NULL
                  )
                ORDER BY created_at DESC
                LIMIT $2
                """,
                bank_id,
                max(1, min(limit, 100)),
            )
        items = await self._assemble_dream_runs(list(run_rows))
        for row in artifact_rows:
            items.append(self._legacy_artifact_to_dream_run(dict(row)))
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return items[: max(1, min(limit, 100))]

    async def get_dream_stats(self, bank_id: str, *, request_context: "RequestContext") -> dict[str, Any]:
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="get_dream_stats", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT
                  COUNT(*) AS total_runs,
                  MAX(created_at) AS last_run_at,
                  AVG(quality_score) AS avg_quality,
                  AVG(COALESCE((result_metadata->>'input_tokens')::float, 0) + COALESCE((result_metadata->>'output_tokens')::float, 0)) AS avg_tokens,
                  AVG(COALESCE((result_metadata->>'output_tokens')::float, 0)) AS avg_output_tokens,
                  AVG(novelty_score) AS avg_novelty,
                  COUNT(*) FILTER (WHERE status IN ('failed_llm', 'failed_validation')) AS failed_run_count,
                  COUNT(*) FILTER (WHERE status = 'duplicate_low_novelty') AS duplicate_suppression_count
                FROM {fq_table("dream_runs")}
                WHERE bank_id = $1
                """,
                bank_id,
            )
            prediction_row = await conn.fetchrow(
                f"""
                SELECT
                  COUNT(*) FILTER (WHERE status = 'confirmed') AS confirmed_count,
                  COUNT(*) FILTER (WHERE status = 'contradicted') AS contradicted_count,
                  COUNT(*) FILTER (WHERE status IN ('pending', 'unresolved')) AS unresolved_backlog
                FROM {fq_table("dream_predictions")}
                WHERE bank_id = $1
                """,
                bank_id,
            )
        total = int(row["total_runs"] or 0)
        confirmed = int(prediction_row["confirmed_count"] or 0) if prediction_row else 0
        contradicted = int(prediction_row["contradicted_count"] or 0) if prediction_row else 0
        unresolved = int(prediction_row["unresolved_backlog"] or 0) if prediction_row else 0
        validation_denominator = confirmed + contradicted
        confirmation_rate = confirmed / validation_denominator if validation_denominator else 0.0
        return {
            "bank_id": bank_id,
            "total_runs": total,
            "last_run_at": row["last_run_at"].isoformat() if row["last_run_at"] else None,
            "avg_quality": float(row["avg_quality"] or 0.0),
            "avg_tokens": float(row["avg_tokens"] or 0.0),
            "avg_output_tokens": float(row["avg_output_tokens"] or 0.0),
            "distillation_pass_rate": 0.0,
            "distilled_count": 0,
            "validation_rate": confirmation_rate,
            "avg_novelty": float(row["avg_novelty"] or 0.0),
            "failed_run_count": int(row["failed_run_count"] or 0),
            "duplicate_suppression_count": int(row["duplicate_suppression_count"] or 0),
            "prediction_confirmation_rate": confirmation_rate,
            "unresolved_prediction_backlog": unresolved,
        }

    async def review_dream_proposal(
        self,
        bank_id: str,
        proposal_id: str,
        *,
        action: str,
        note: str | None,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="review_dream_proposal", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id, run_id, proposal_type, title, content, confidence, tags, supporting_evidence_ids, review_status
                FROM {fq_table("dream_proposals")}
                WHERE bank_id = $1 AND id = $2
                """,
                bank_id,
                uuid.UUID(proposal_id),
            )
            if row is None:
                raise ValueError("Dream proposal not found")
            if row["review_status"] == "approved" and action == "approve":
                raise ValueError("Dream proposal already approved")

        review_status = {
            "approve": "approved",
            "reject": "rejected",
            "request_more_evidence": "needs_more_evidence",
        }.get(action)
        if review_status is None:
            raise ValueError("Unsupported dream proposal action")

        approval_metadata: dict[str, Any] = {"note": note, "action": action}
        if action == "approve":
            if row["proposal_type"] == "mental_model":
                created = await self.create_mental_model(
                    bank_id=bank_id,
                    name=row["title"],
                    source_query="dream_proposal",
                    content=row["content"],
                    tags=decode_jsonb(row["tags"], []),
                    request_context=request_context,
                )
                approval_metadata["created_mental_model_id"] = created.get("id")
            else:
                retained = await self.retain_batch_async(
                    bank_id=bank_id,
                    contents=[{"content": row["content"], "context": f"dream_proposal:{row['proposal_type']}"}],
                    request_context=request_context,
                    fact_type_override="observation",
                    confidence_score=float(row["confidence"] or 0.6),
                )
                approval_metadata["retained"] = retained

        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            updated = await conn.fetchrow(
                f"""
                UPDATE {fq_table("dream_proposals")}
                SET review_status = $3,
                    rationale = COALESCE($4, rationale),
                    approval_metadata = $5::jsonb,
                    reviewed_at = NOW(),
                    updated_at = NOW()
                WHERE bank_id = $1 AND id = $2
                RETURNING id, proposal_type, title, content, confidence, tags, supporting_evidence_ids, review_status, rationale
                """,
                bank_id,
                uuid.UUID(proposal_id),
                review_status,
                note,
                json.dumps(approval_metadata),
            )
        return DreamPromotionProposal(
            proposal_id=str(updated["id"]),
            proposal_type=updated["proposal_type"],
            title=updated["title"],
            content=updated["content"],
            confidence=float(updated["confidence"] or 0.0),
            tags=decode_jsonb(updated["tags"], []),
            supporting_evidence_ids=decode_jsonb(updated["supporting_evidence_ids"], []),
            review_status=updated["review_status"],
            rationale=updated["rationale"],
        ).model_dump(mode="json")

    async def update_dream_prediction_outcome(
        self,
        bank_id: str,
        prediction_id: str,
        *,
        status: str,
        note: str | None,
        evidence_ids: list[str] | None,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(
                bank_id=bank_id, operation="update_dream_prediction_outcome", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        if status not in {"confirmed", "contradicted", "request_more_evidence"}:
            raise ValueError("Unsupported dream prediction outcome status")
        prediction_status = "unresolved" if status == "request_more_evidence" else status
        pool = await self._get_pool()
        async with acquire_with_retry(pool) as conn:
            prediction = await conn.fetchrow(
                f"""
                UPDATE {fq_table("dream_predictions")}
                SET status = $3,
                    validation_notes = COALESCE($4, validation_notes),
                    updated_at = NOW()
                WHERE bank_id = $1 AND id = $2
                RETURNING id, title, description, target_ref, target_kind, horizon, confidence,
                          success_criteria, expiration_window_days, status, supporting_evidence_ids, validation_notes
                """,
                bank_id,
                uuid.UUID(prediction_id),
                prediction_status,
                note,
            )
            if prediction is None:
                raise ValueError("Dream prediction not found")
            outcome_id = uuid.uuid4()
            await conn.execute(
                f"""
                INSERT INTO {fq_table("dream_prediction_outcomes")}
                    (id, prediction_id, bank_id, outcome_status, note, evidence_ids, created_at)
                VALUES
                    ($1, $2, $3, $4, $5, $6::jsonb, NOW())
                """,
                outcome_id,
                uuid.UUID(prediction_id),
                bank_id,
                status,
                note,
                json.dumps(evidence_ids or []),
            )
        return {
            "prediction": DreamPrediction(
                prediction_id=str(prediction["id"]),
                title=prediction["title"],
                description=prediction["description"],
                target_ref=prediction["target_ref"],
                target_kind=prediction["target_kind"],
                horizon=prediction["horizon"],
                confidence=float(prediction["confidence"] or 0.0),
                success_criteria=decode_jsonb(prediction["success_criteria"], []),
                expiration_window_days=int(prediction["expiration_window_days"] or 14),
                status=prediction["status"],
                supporting_evidence_ids=decode_jsonb(prediction["supporting_evidence_ids"], []),
                validation_notes=prediction["validation_notes"],
            ).model_dump(mode="json"),
            "outcome": DreamValidationOutcome(
                outcome_id=str(outcome_id),
                prediction_id=prediction_id,
                status=status,
                note=note,
                evidence_ids=evidence_ids or [],
                created_at=datetime.now(UTC).isoformat(),
            ).model_dump(mode="json"),
        }

    async def get_brain_runtime_status(self, bank_id: str, *, request_context: "RequestContext") -> dict[str, Any]:
        """Get current brain runtime/cache status for a bank."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(
                bank_id=bank_id, operation="get_brain_runtime_status", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        return await self._brain_runtime.get_status(bank_id)

    async def get_sub_routine_predictions(
        self,
        bank_id: str,
        *,
        horizon_hours: int = 24,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Get activity-time predictions generated from brain cache."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(
                bank_id=bank_id, operation="get_sub_routine_predictions", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        return await self._brain_runtime.predict_activity_time(bank_id, horizon_hours=horizon_hours)

    async def get_sub_routine_histogram(
        self,
        bank_id: str,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Get full 24-hour activity histogram generated from brain cache."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(
                bank_id=bank_id, operation="get_sub_routine_histogram", request_context=request_context
            )
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        return await self._brain_runtime.get_activity_histogram(bank_id)

    async def get_brain_influence_analytics(
        self,
        bank_id: str,
        *,
        window_days: int = 14,
        top_k: int = 12,
        entity_type: str = "all",
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        await self._authenticate_tenant(request_context)
        pool = await self._get_pool()
        since_days = max(1, min(window_days, 90))
        top_n = max(5, min(top_k, 50))
        entity_filter = (entity_type or "all").lower()
        if entity_filter not in {"all", "memory", "chunk", "mental_model"}:
            entity_filter = "all"
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                WITH candidates AS (
                    SELECT
                           id::text AS id,
                           COALESCE(text, '')::text AS text,
                           COALESCE(fact_type, 'memory')::text AS item_type,
                           created_at,
                           last_accessed_at,
                           COALESCE(access_count, 0) AS access_count
                    FROM {fq_table("memory_units")}
                    WHERE bank_id = $1
                    UNION ALL
                    SELECT
                           chunk_id::text AS id,
                           COALESCE(chunk_text, '')::text AS text,
                           'chunk'::text AS item_type,
                           created_at,
                           last_accessed_at,
                           COALESCE(access_count, 0) AS access_count
                    FROM {fq_table("chunks")}
                    WHERE bank_id = $1
                    UNION ALL
                    SELECT
                           id::text AS id,
                           COALESCE(name, '')::text AS text,
                           'mental_model'::text AS item_type,
                           created_at,
                           last_accessed_at,
                           COALESCE(access_count, 0) AS access_count
                    FROM {fq_table("mental_models")}
                    WHERE bank_id = $1
                )
                SELECT id, text, item_type, created_at, last_accessed_at, access_count
                FROM candidates
                WHERE $3::text = 'all'
                   OR ($3::text = 'memory' AND item_type <> 'chunk' AND item_type <> 'mental_model')
                   OR ($3::text = 'chunk' AND item_type = 'chunk')
                   OR ($3::text = 'mental_model' AND item_type = 'mental_model')
                ORDER BY access_count DESC, COALESCE(last_accessed_at, created_at) DESC
                LIMIT $2
                """,
                bank_id,
                top_n,
                entity_filter,
            )
            dream_rows = await conn.fetch(
                f"""
                SELECT id, quality_score, created_at
                FROM {fq_table("dream_runs")}
                WHERE bank_id = $1
                  AND created_at >= NOW() - ($2::text || ' days')::interval
                ORDER BY created_at DESC
                LIMIT 200
                """,
                bank_id,
                str(since_days),
            )
            access_rows = await conn.fetch(
                f"""
                SELECT ts FROM (
                    SELECT COALESCE(last_accessed_at, created_at) AS ts
                    FROM {fq_table("memory_units")}
                    WHERE bank_id = $1
                    UNION ALL
                    SELECT COALESCE(last_accessed_at, created_at) AS ts
                    FROM {fq_table("chunks")}
                    WHERE bank_id = $1
                    UNION ALL
                    SELECT COALESCE(last_accessed_at, created_at) AS ts
                    FROM {fq_table("mental_models")}
                    WHERE bank_id = $1
                    UNION ALL
                    SELECT created_at AS ts
                    FROM {fq_table("dream_runs")}
                    WHERE bank_id = $1
                ) combined
                WHERE ts >= NOW() - ($2::text || ' days')::interval
                ORDER BY ts ASC
                LIMIT 3000
                """,
                bank_id,
                str(since_days),
            )

        dream_signal = 0.0
        if dream_rows:
            dream_signal = sum(float(r["quality_score"] or 0.0) for r in dream_rows) / max(len(dream_rows), 1)
            dream_signal = max(0.0, min(dream_signal, 1.0))
        leaderboard: list[dict[str, Any]] = []
        trend_raw: list[float] = []
        now = datetime.now(UTC)
        for idx, row in enumerate(rows):
            created_at = row["created_at"] or now
            last_accessed_at = row["last_accessed_at"] or created_at
            recency_days = max((now - last_accessed_at).total_seconds() / 86400.0, 0.0)
            freq_raw = float(row["access_count"] or 0.0)
            freq_score = min(freq_raw / 20.0, 1.0)
            graph_signal = max(0.0, min(1.0, (top_n - idx) / max(top_n, 1)))
            rerank_signal = max(0.0, min(1.0, 0.5 + 0.5 * graph_signal))
            score, parts = influence_score(
                InfluenceFeatures(
                    recency_days=recency_days,
                    access_freq=freq_score,
                    graph_signal=graph_signal,
                    rerank_signal=rerank_signal,
                    dream_signal=dream_signal,
                )
            )
            leaderboard.append(
                {
                    "id": row["id"],
                    "type": row["item_type"] or "unknown",
                    "text": (row["text"] or "")[:180],
                    "access_count": int(freq_raw),
                    "influence_score": score,
                    "contribution": parts,
                    "last_accessed_at": last_accessed_at.isoformat() if last_accessed_at else None,
                }
            )
            trend_raw.append(score)

        access_ts = [r["ts"] for r in access_rows if r["ts"] is not None]
        day_counts: dict[str, int] = {}
        for ts in access_ts:
            day_key = ts.astimezone(UTC).date().isoformat()
            day_counts[day_key] = day_counts.get(day_key, 0) + 1
        ordered_days = sorted(day_counts.keys())
        if ordered_days:
            peak = max(day_counts[d] for d in ordered_days) or 1
            trend_raw = [round(day_counts[d] / peak, 6) for d in ordered_days]
        trend_ewma = ewma(trend_raw, alpha=0.35)
        trend_band = confidence_bands(trend_ewma)
        iqr_flags = iqr_anomaly_flags(trend_ewma)
        anomalies = []
        for i, v in enumerate(trend_ewma):
            z = robust_zscore(v, trend_ewma)
            iqr_flag = iqr_flags[i] if i < len(iqr_flags) else False
            if abs(z) >= 2.5 or iqr_flag:
                anomalies.append({"index": i, "score": round(v, 6), "zscore": round(z, 3), "iqr": iqr_flag})
        heatmap = hour_weekday_heatmap(access_ts)

        return {
            "bank_id": bank_id,
            "window_days": since_days,
            "entity_type": entity_filter,
            "leaderboard": leaderboard,
            "heatmap": heatmap,
            "trend": [
                {
                    "index": i,
                    "raw": trend_raw[i],
                    "ewma": trend_ewma[i],
                    "lower": trend_band[i]["lower"],
                    "upper": trend_band[i]["upper"],
                }
                for i in range(len(trend_raw))
            ],
            "anomalies": anomalies,
            "summary": {
                "entity_count": len(leaderboard),
                "dream_runs": len(dream_rows),
                "avg_dream_quality": round(dream_signal, 6),
                "top_influence": leaderboard[0]["influence_score"] if leaderboard else 0.0,
            },
        }

    async def export_brain_snapshot(self, bank_id: str, *, request_context: "RequestContext") -> bytes:
        """Export the bank's validated .brain snapshot."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="export_brain_snapshot", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        return await self._brain_runtime.export_snapshot(bank_id)

    async def validate_brain_import(
        self,
        bank_id: str,
        raw: bytes,
        *,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Validate incoming brain snapshot payload without importing it."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankReadContext

            ctx = BankReadContext(bank_id=bank_id, operation="validate_brain_import", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_read(ctx))
        report = await self._brain_runtime.validate_import_payload(raw)
        return {
            "valid": report.valid,
            "version": report.version,
            "reason": report.reason,
        }

    async def import_brain_snapshot(
        self, bank_id: str, raw: bytes, *, request_context: "RequestContext"
    ) -> dict[str, Any]:
        """Import a validated .brain snapshot for a bank."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="import_brain_snapshot", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))
        return await self._brain_runtime.import_snapshot(bank_id, raw)

    async def submit_brain_learn(
        self,
        bank_id: str,
        *,
        remote_endpoint: str,
        remote_bank_id: str,
        remote_api_key: str = "",
        learning_type: str = "auto",
        mode: str = "incremental",
        horizon_hours: int = 24,
        request_context: "RequestContext",
    ) -> dict[str, Any]:
        """Submit a brain-learn operation to distill knowledge from a remote brain."""
        await self._authenticate_tenant(request_context)
        if self._operation_validator:
            from atulya_api.extensions import BankWriteContext

            ctx = BankWriteContext(bank_id=bank_id, operation="submit_brain_learn", request_context=request_context)
            await self._validate_operation(self._operation_validator.validate_bank_write(ctx))

        task_payload: dict[str, Any] = {
            "mode": mode,
            "horizon_hours": horizon_hours,
            "remote_endpoint": remote_endpoint,
            "remote_bank_id": remote_bank_id,
            "remote_api_key": remote_api_key,
            "learning_type": learning_type,
        }
        dedupe_key = f"{bank_id}:learn:{remote_endpoint}:{remote_bank_id}:{learning_type}"
        if request_context.tenant_id:
            task_payload["_tenant_id"] = request_context.tenant_id
        if request_context.api_key_id:
            task_payload["_api_key_id"] = request_context.api_key_id

        return await self._submit_async_operation(
            bank_id=bank_id,
            operation_type="brain_learn",
            task_type="brain_learn",
            task_payload=task_payload,
            result_metadata={
                "mode": mode,
                "learning_type": learning_type,
                "remote_endpoint": remote_endpoint,
                "remote_bank_id": remote_bank_id,
            },
            dedupe_by_bank=True,
            dedupe_key=dedupe_key,
        )

    async def enqueue_startup_brain_warmup(self) -> int:
        """Queue non-blocking startup warmup sub_routine tasks for known banks."""
        from atulya_api.models import RequestContext

        if not self._brain_runtime.enabled:
            return 0
        internal_context = RequestContext(internal=True)
        banks = await self.list_banks(request_context=internal_context)
        queued = 0
        for bank in banks:
            bank_id = str(bank.get("bank_id", ""))
            if not bank_id:
                continue
            await self._submit_async_operation(
                bank_id=bank_id,
                operation_type="sub_routine",
                task_type="sub_routine",
                task_payload={"mode": "warmup", "horizon_hours": 24, "force_rebuild": False},
                result_metadata={"startup_warmup": True},
                dedupe_by_bank=True,
                dedupe_key=f"{bank_id}:warmup:24:0",
            )
            queued += 1
        return queued
