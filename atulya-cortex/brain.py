"""
brain.py

Ψ OS: Hybrid Ψ + Transformer-style controller:
- External LLM kernel (OpenAI / Ollama / local HF).
- Embedding-based semantic memory with persistence.
- Persistent user meta-preference profile (wᵢ with invariant core).
- Ψ-state (Δx) affecting planning, tools, and answer generation.
- Two-pass (plan → act → answer) reasoning.
- Hierarchical memory: short-term, episodic, semantic.
- Tool-calling with registry and typed results.
- Task abstraction for multi-step problem solving.

You can:
- Run as a REPL.
- Later wrap in FastAPI / gRPC / CLI for real production.
"""

import time
import uuid
import json
import tempfile
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple, Callable
from collections import deque
import math
import os
import textwrap
import traceback

# ============================================================
# 0) UTILITIES
# ============================================================

def cosine_sim(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x*y for x, y in zip(a, b))
    da = math.sqrt(sum(x*x for x in a))
    db = math.sqrt(sum(x*x for x in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def now_ts() -> float:
    return time.time()


def safe_truncate(text: str, max_len: int = 4000) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# ============================================================
# 1) CONFIGURATION
# ============================================================

@dataclass
class PsiConfig:
    profile_path: str = "psi_profile.json"
    memory_path: str = "psi_memory.json"
    episodic_path: str = "psi_episodic.json"
    max_history: int = 64
    max_semantic_items: int = 1024
    max_episodic_items: int = 256
    planning_temperature: float = 0.3
    answer_temperature: float = 0.4
    max_tokens_plan: int = 1024
    max_tokens_answer: int = 1536
    dummy_backend: bool = True  # set False when wiring real LLM


# ============================================================
# 2) LLM / EMBEDDING CLIENTS
# ============================================================

class LLMClient:
    """
    Adapter over your LLM.
    Customize 'generate' for:
    - OpenAI API
    - Ollama server
    - Local HF model server
    """

    def __init__(
        self,
        backend: str = "dummy",   # "openai" | "ollama" | "dummy"
        model: str = "gpt-4.1-mini",
        temperature: float = 0.3,
        max_tokens: int = 512,
    ):
        self.backend = backend
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, messages: List[Dict[str, str]]) -> str:
        """
        messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
        """
        if self.backend == "dummy":
            # Deterministic echo-style kernel with slight transformation
            last_user = [m for m in messages if m["role"] == "user"]
            content = last_user[-1]["content"] if last_user else ""
            return f"[Ψ DUMMY KERNEL] Planned response to: {safe_truncate(content, 200)}"

        # Example: OpenAI-compatible
        # import requests
        # url = "https://api.openai.com/v1/chat/completions"
        # headers = {
        #     "Authorization": f"Bearer YOUR_API_KEY",
        #     "Content-Type": "application/json",
        # }
        # payload = {
        #     "model": self.model,
        #     "temperature": self.temperature,
        #     "max_tokens": self.max_tokens,
        #     "messages": messages,
        # }
        # r = requests.post(url, headers=headers, json=payload, timeout=60)
        # r.raise_for_status()
        # data = r.json()
        # return data["choices"][0]["message"]["content"]

        # Example: Ollama-compatible
        # import requests
        # url = "http://localhost:11434/v1/chat/completions"
        # payload = {
        #     "model": self.model,
        #     "temperature": self.temperature,
        #     "messages": messages,
        # }
        # r = requests.post(url, json=payload, timeout=120)
        # r.raise_for_status()
        # data = r.json()
        # return data["choices"][0]["message"]["content"]

        raise NotImplementedError(
            "Implement LLMClient.generate() for your backend or set backend='dummy'."
        )


class EmbeddingClient:
    """
    Embedding provider for semantic memory.
    """

    def __init__(self, backend: str = "dummy", model: str = "small-embed-model"):
        self.backend = backend
        self.model = model

    def embed(self, text: str) -> List[float]:
        """
        Return an embedding vector for the given text.
        Implement using your preferred backend.

        Dummy backend: length-64 deterministic hash-based vector.
        """
        if self.backend == "dummy":
            v = [0.0] * 64
            data = text.encode("utf-8")
            for i, ch in enumerate(data):
                v[i % 64] += (ch % 17) / 17.0
            norm = math.sqrt(sum(x*x for x in v)) or 1.0
            return [x / norm for x in v]

        # Example OpenAI-like:
        # import requests
        # url = "https://api.openai.com/v1/embeddings"
        # headers = {
        #     "Authorization": f"Bearer YOUR_API_KEY",
        #     "Content-Type": "application/json",
        # }
        # payload = {"model": self.model, "input": text}
        # r = requests.post(url, headers=headers, json=payload, timeout=60)
        # r.raise_for_status()
        # data = r.json()
        # return data["data"][0]["embedding"]

        raise NotImplementedError(
            "Implement EmbeddingClient.embed() or use backend='dummy'."
        )


# ============================================================
# 3) CORE DATA STRUCTURES
# ============================================================

@dataclass
class Turn:
    role: str          # "user" | "assistant" | "tool" | "system"
    content: str
    timestamp: float = field(default_factory=now_ts)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryItem:
    id: str
    text: str
    embedding: List[float]
    score: float
    last_updated: float
    kind: str = "semantic"   # "semantic" | "episodic"


@dataclass
class PsiState:
    """
    Ψ-layer internal state.
    Δx represents "recent change" in semantic/behavioral context.
    """
    last_topics: List[str] = field(default_factory=list)
    last_style_vector: Dict[str, float] = field(default_factory=dict)
    delta_topic_magnitude: float = 0.0
    delta_style_magnitude: float = 0.0

    def to_summary(self) -> str:
        return (
            f"Δx topics change: {self.delta_topic_magnitude:.2f}, "
            f"Δx style change: {self.delta_style_magnitude:.2f}, "
            f"current topics: {', '.join(self.last_topics[:6]) or 'none'}"
        )


@dataclass
class PreferenceProfile:
    """
    Heuristic preference model inferred from user turns.
    Values in [0, 1] roughly.

    Plus an invariant meta-preference core:
      - complexity_bias
      - novelty_bias
      - info_density_bias
    """
    emotional_depth: float = 0.5
    technical_depth: float = 0.5
    metaphorical: float = 0.5
    brevity: float = 0.5
    directness: float = 0.5

    complexity_bias: float = 0.7
    novelty_bias: float = 0.7
    info_density_bias: float = 0.7

    def apply_update(self, feature: str, delta: float) -> None:
        old = getattr(self, feature)
        new = max(0.0, min(1.0, old + delta))
        setattr(self, feature, new)

    def as_text(self) -> str:
        return (
            f"User seems to prefer: "
            f"emotional_depth={self.emotional_depth:.2f}, "
            f"technical_depth={self.technical_depth:.2f}, "
            f"metaphorical={self.metaphorical:.2f}, "
            f"brevity={self.brevity:.2f}, "
            f"directness={self.directness:.2f}. "
            f"Invariant core biases: complexity={self.complexity_bias:.2f}, "
            f"novelty={self.novelty_bias:.2f}, info_density={self.info_density_bias:.2f}."
        )


# ============================================================
# 4) PERSISTENT PROFILE STORE (∫ over time)
# ============================================================

class ProfileStore:
    """
    Persistent storage of PreferenceProfile and PsiState.
    This is where ∫ over time is realized.
    """

    def __init__(self, path: str):
        self.path = path
        self.profile = PreferenceProfile()
        self.psi_state = PsiState()
        self._load()

    def _load(self) -> None:
        raw = load_json(self.path, None)
        if not raw:
            return
        p = raw.get("preferences")
        s = raw.get("psi_state")
        if p:
            self.profile = PreferenceProfile(**p)
        if s:
            self.psi_state = PsiState(**s)

    def save(self) -> None:
        data = {
            "preferences": asdict(self.profile),
            "psi_state": asdict(self.psi_state),
        }
        save_json(self.path, data)


# ============================================================
# 5) MEMORY SYSTEMS: SEMANTIC + EPISODIC
# ============================================================

class VectorMemoryStore:
    """
    Embedding-based memory store with persistent JSON.
    Supports semantic or episodic items (kind field).
    """

    def __init__(
        self,
        emb: EmbeddingClient,
        path: str,
        max_items: int = 1024,
        kind: str = "semantic",
    ):
        self.emb = emb
        self.path = path
        self.max_items = max_items
        self.kind = kind
        self.items: Dict[str, MemoryItem] = {}
        self._load()

    def _load(self) -> None:
        raw = load_json(self.path, [])
        now = now_ts()
        self.items = {}
        for obj in raw:
            try:
                it = MemoryItem(
                    id=obj["id"],
                    text=obj["text"],
                    embedding=obj["embedding"],
                    score=obj.get("score", 0.5),
                    last_updated=obj.get("last_updated", now),
                    kind=obj.get("kind", self.kind),
                )
                self.items[it.id] = it
            except Exception:
                continue

    def _save(self) -> None:
        data = []
        for it in self.items.values():
            data.append(
                {
                    "id": it.id,
                    "text": it.text,
                    "embedding": it.embedding,
                    "score": it.score,
                    "last_updated": it.last_updated,
                    "kind": it.kind,
                }
            )
        save_json(self.path, data)

    def _decay_factor(self, age_sec: float) -> float:
        # Half-life of 3 days
        half_life = 3 * 24 * 3600
        return math.exp(-math.log(2) * age_sec / half_life)

    def add(self, text: str, importance: float = 0.5) -> None:
        now = now_ts()
        text = text.strip()
        if not text:
            return
        emb = self.emb.embed(text)
        it = MemoryItem(
            id=str(uuid.uuid4()),
            text=text,
            embedding=emb,
            score=importance,
            last_updated=now,
            kind=self.kind,
        )
        self.items[it.id] = it

        if len(self.items) > self.max_items:
            lowest = min(self.items.values(), key=lambda x: x.score)
            del self.items[lowest.id]

        self._save()

    def retrieve_top(self, query: str, k: int = 5) -> List[MemoryItem]:
        if not self.items:
            return []
        now = now_ts()
        q_emb = self.emb.embed(query)
        scored: List[Tuple[float, MemoryItem]] = []
        for it in self.items.values():
            sim = cosine_sim(q_emb, it.embedding)
            age = now - it.last_updated
            decay = self._decay_factor(age)
            score = (it.score * decay) + sim
            scored.append((score, it))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in scored[:k]]

    def summary(self, k: int = 8) -> str:
        if not self.items:
            return f"No {self.kind} memory stored yet."
        top = sorted(self.items.values(), key=lambda it: it.score, reverse=True)[:k]
        return "\n".join(f"- {it.text}" for it in top)


# ============================================================
# 6) STYLE / TOPIC ANALYZERS (for Δx and wᵢ updates)
# ============================================================

def extract_topics(text: str) -> List[str]:
    stop = {
        "the", "and", "or", "for", "with", "this", "that", "you", "are", "was",
        "have", "has", "from", "into", "your", "about", "what", "when", "how",
        "why", "can", "could", "should", "would", "will", "just", "like"
    }
    freq: Dict[str, int] = {}
    for raw in text.split():
        w = "".join(ch for ch in raw.lower() if ch.isalnum())
        if len(w) < 4 or w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    topics = sorted(freq.keys(), key=lambda k: freq[k], reverse=True)
    return topics[:10]


def analyze_style_vector(text: str) -> Dict[str, float]:
    lowered = text.lower()
    length = max(1, len(text))

    emotion_words = ["feel", "love", "hate", "anxious", "excited", "afraid",
                     "happy", "sad", "tensed", "overwhelmed", "hurt"]
    technical_words = ["api", "model", "vector", "tensor", "neural", "gpu",
                       "python", "transformer", "agent", "gradient", "docker",
                       "kubernetes", "devops", "llm", "embedding"]
    metaphor_words = ["mirror", "fractal", "soul", "psyche", "ghost",
                      "shadow", "echo", "spiral", "labyrinth"]

    emotional = sum(lowered.count(w) for w in emotion_words)
    technical = sum(lowered.count(w) for w in technical_words)
    metaphorical = sum(lowered.count(w) for w in metaphor_words)

    exclam = lowered.count("!") + lowered.count("…")
    question = lowered.count("?")

    emotional_score = min(1.0, (emotional + exclam * 0.3) / 5.0)
    technical_score = min(1.0, (technical) / 5.0)
    metaphor_score = min(1.0, (metaphorical) / 4.0)

    brevity_score = max(0.0, min(1.0, 400.0 / length))
    directness_markers = ["tell me", "explain", "give me", "show me", "how to", "help me"]
    directness_score = min(
        1.0,
        sum(1 for m in directness_markers if m in lowered) / len(directness_markers) * 2.0,
    )
    directness_score += min(0.4, question * 0.1)

    return {
        "emotional_depth": emotional_score,
        "technical_depth": technical_score,
        "metaphorical": metaphor_score,
        "brevity": brevity_score,
        "directness": max(0.0, min(1.0, directness_score)),
    }


def style_distance(a: Dict[str, float], b: Dict[str, float]) -> float:
    keys = set(a.keys()) | set(b.keys())
    sq = 0.0
    for k in keys:
        sq += (a.get(k, 0.0) - b.get(k, 0.0)) ** 2
    return math.sqrt(sq / max(1, len(keys)))


# ============================================================
# 7) TOOLS AND REGISTRY
# ============================================================

class ToolResult:
    def __init__(self, tool: str, input_text: str, output_text: str, ok: bool = True):
        self.tool = tool
        self.input = input_text
        self.output = output_text
        self.ok = ok

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "input": self.input,
            "output": self.output,
            "ok": self.ok,
        }


class ToolBase:
    name: str = "base"
    description: str = "Base tool"

    @classmethod
    def run(cls, input_text: str) -> ToolResult:
        raise NotImplementedError


class MathTool(ToolBase):
    """
    Very simple math tool.
    Expression is evaluated in a restricted environment.
    """

    name = "math_tool"
    description = "Safely evaluate a mathematical expression (basic arithmetic, pow, trig)."

    @classmethod
    def run(cls, expression: str) -> ToolResult:
        allowed_names = {
            "abs": abs,
            "round": round,
            "pow": pow,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "pi": math.pi,
            "e": math.e,
        }
        try:
            code = compile(expression, "<math_tool>", "eval")
            for node in code.co_names:
                if node not in allowed_names:
                    raise ValueError(f"Use of '{node}' is not allowed.")
            result = eval(code, {"__builtins__": {}}, allowed_names)
            return ToolResult(cls.name, expression, f"Result: {result}", ok=True)
        except Exception as e:
            return ToolResult(cls.name, expression, f"Error evaluating expression: {e}", ok=False)


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, ToolBase] = {}
        self.register(MathTool)

    def register(self, tool_cls: type):
        self.tools[tool_cls.name] = tool_cls

    def run(self, name: str, input_text: str) -> ToolResult:
        tool_cls = self.tools.get(name)
        if not tool_cls:
            return ToolResult(name, input_text, f"Unknown tool: {name}", ok=False)
        try:
            return tool_cls.run(input_text)
        except Exception as e:
            return ToolResult(name, input_text, f"Tool error: {e}", ok=False)


# ============================================================
# 8) TASK ABSTRACTION
# ============================================================

@dataclass
class PsiTask:
    """
    Abstract task to be solved by Ψ OS.
    """
    id: str
    user_message: str
    created_at: float
    status: str = "pending"   # pending | running | done | failed
    result: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    tool_results: List[ToolResult] = field(default_factory=list)


# ============================================================
# 9) Ψ ENGINE CONTROLLER (THE CORE)
# ============================================================

class PsiEngine:
    """
    High-level Ψ controller:
    - Tracks conversation
    - Learns preferences (wᵢ evolution with invariant core)
    - Maintains semantic + episodic memory (ξᵢ with scores)
    - Computes Δx and uses φ(Δx) to modulate behaviour
    - Two-pass (plan → act → answer) with tool-calling
    """

    def __init__(
        self,
        cfg: PsiConfig,
        llm_plan: LLMClient,
        llm_answer: LLMClient,
        emb: EmbeddingClient,
        profile_store: ProfileStore,
        semantic_memory: VectorMemoryStore,
        episodic_memory: VectorMemoryStore,
        tools: ToolRegistry,
    ):
        self.cfg = cfg
        self.llm_plan = llm_plan
        self.llm_answer = llm_answer
        self.emb = emb
        self.profile_store = profile_store
        self.semantic_memory = semantic_memory
        self.episodic_memory = episodic_memory
        self.tools = tools

        self.history: deque[Turn] = deque(maxlen=cfg.max_history)

    @property
    def preferences(self) -> PreferenceProfile:
        return self.profile_store.profile

    @property
    def psi_state(self) -> PsiState:
        return self.profile_store.psi_state

    # ---- internal helpers ----

    def _update_preferences_from_user(self, user_text: str) -> None:
        style = analyze_style_vector(user_text)
        for k, v in style.items():
            current = getattr(self.preferences, k)
            delta = (v - current) * 0.2
            self.preferences.apply_update(k, delta)

        # meta-preference reinforcement: complexity/novelty/info_density
        length = len(user_text)
        complexity_sig = min(1.0, length / 500.0)
        novelty_sig = 0.5  # placeholder; could detect unusual vocabulary
        info_sig = min(1.0, len(set(user_text.split())) / 80.0)

        self.preferences.apply_update("complexity_bias", (complexity_sig - self.preferences.complexity_bias) * 0.05)
        self.preferences.apply_update("novelty_bias", (novelty_sig - self.preferences.novelty_bias) * 0.05)
        self.preferences.apply_update("info_density_bias", (info_sig - self.preferences.info_density_bias) * 0.05)

    def _update_psi_state(self, user_text: str) -> None:
        new_topics = extract_topics(user_text)
        new_style = analyze_style_vector(user_text)

        topic_overlap = len(set(new_topics) & set(self.psi_state.last_topics))
        topic_div = len(set(new_topics) | set(self.psi_state.last_topics)) or 1
        topic_change = 1.0 - (topic_overlap / topic_div)

        style_change = style_distance(self.psi_state.last_style_vector, new_style)

        self.psi_state.last_topics = new_topics
        self.psi_state.last_style_vector = new_style
        self.psi_state.delta_topic_magnitude = topic_change
        self.psi_state.delta_style_magnitude = style_change

    def _maybe_store_memory(self, user_text: str, assistant_text: str) -> None:
        lowered = user_text.lower()
        markers = ["remember", "goal", "plan", "target", "important", "value"]
        if any(m in lowered for m in markers):
            self.semantic_memory.add(f"User goal/value: {safe_truncate(user_text, 400)}", importance=0.9)
        if "i am" in lowered or "i want to be" in lowered:
            self.semantic_memory.add(
                f"User self-description: {safe_truncate(user_text, 400)}",
                importance=0.85,
            )

        # store episodic trace
        episode = f"EPISODE user: {safe_truncate(user_text, 200)} || assistant: {safe_truncate(assistant_text, 200)}"
        self.episodic_memory.add(episode, importance=0.4)

    def _history_as_text(self, last_n: int = 8) -> str:
        turns = list(self.history)[-last_n:]
        if not turns:
            return "(no prior turns)"
        lines = []
        for t in turns:
            lines.append(f"{t.role.upper()}: {t.content}")
        return "\n".join(lines)

    def _build_memory_block(self, user_text: str) -> str:
        sem = self.semantic_memory.retrieve_top(query=user_text, k=4)
        epi = self.episodic_memory.retrieve_top(query=user_text, k=2)
        if not sem and not epi:
            return "No strongly relevant memories."
        lines = []
        if sem:
            lines.append("Semantic memories:")
            for it in sem:
                lines.append(f"- {it.text}")
        if epi:
            lines.append("Episodic memories:")
            for it in epi:
                lines.append(f"- {it.text}")
        return "\n".join(lines)

    def _mode_hint(self) -> str:
        delta = max(self.psi_state.delta_topic_magnitude, self.psi_state.delta_style_magnitude)
        if delta > 0.7:
            return "User context changed significantly. Ask for clarification if ambiguity is high and state assumptions explicitly."
        elif delta > 0.4:
            return "User context shifted moderately. Briefly restate assumptions before solving."
        else:
            return "User context is relatively stable. You can build directly on prior turns."

    def _build_control_instructions(self) -> str:
        prefs_text = self.preferences.as_text()
        psi_text = self.psi_state.to_summary()
        mode_hint = self._mode_hint()

        return textwrap.dedent(
            f"""
            You are a Ψ-hybrid reasoning agent built on top of a stateless LLM kernel.

            Conceptual mapping:
            - ξᵢ: semantic chunks of current and retrieved context.
            - wᵢ: user preference weights (profile) and memory importance scores, modulated by invariant meta-preference biases (complexity, novelty, info density).
            - Δx: recent changes in topics and style.
            - φ(Δx): you adjust how cautiously and explicitly you reason based on Δx.
            - ∫ over time: profile and memory persist and accumulate between turns.

            Objectives:
            - Solve the user's problem concretely and efficiently.
            - Adapt to user preferences and style.
            - Maintain coherence across turns using the provided memory.
            - Use clear, structured reasoning internally, but reveal only clean, concise answers.

            Preference profile:
            {prefs_text}

            Ψ-state:
            {psi_text}

            Mode hint derived from φ(Δx):
            {mode_hint}

            Behavioural rules:
            - Be precise and technically correct when the user is technical.
            - Allow emotional nuance when the user expresses feelings.
            - Use metaphors only if aligned with preferences.
            - Prefer direct, concise answers unless the user clearly wants deep exploration.
            - Avoid hallucinating concrete external facts; mark uncertainty when necessary.
            - You may call tools if the plan indicates them, but report only the useful result.

            Only output the final answer to the user, with no debug or meta text.
            """
        ).strip()

    # ---- planning / tool / answer pipeline ----

    def _build_planning_prompt(self, task: PsiTask) -> List[Dict[str, str]]:
        user_text = task.user_message
        control = self._build_control_instructions()
        memory_block = self._build_memory_block(user_text)
        history_snippet = self._history_as_text(last_n=8)

        system_msg = {
            "role": "system",
            "content": (
                control
                + "\n\nYou are now in PLANNING mode. "
                  "Produce a terse, structured JSON plan for how you will answer. "
                  "Schema:\n"
                  "{\n"
                  '  "problem": "...",\n'
                  '  "assumptions": ["..."],\n'
                  '  "steps": ["..."],\n'
                  '  "tool_calls": [\n'
                  '     {"tool": "math_tool", "input": "2+2"},\n'
                  "     ...\n"
                  "  ]\n"
                  "}\n"
                  "If no tools are needed, use an empty array for tool_calls."
            ),
        }

        planning_user = {
            "role": "user",
            "content": textwrap.dedent(
                f"""
                USER_MESSAGE:
                {user_text}

                RECENT_HISTORY:
                {history_snippet}

                MEMORY_CONTEXT:
                {memory_block}

                Task:
                - Analyze the user message.
                - Infer what the user really needs.
                - Prepare a JSON plan following the schema above.
                - Do NOT output any explanation text, only valid JSON.
                """
            ).strip(),
        }

        return [system_msg, planning_user]

    def _parse_plan(self, plan_raw: str) -> Dict[str, Any]:
        plan_raw = plan_raw.strip()
        try:
            first = plan_raw.find("{")
            last = plan_raw.rfind("}")
            if first != -1 and last != -1:
                plan_raw = plan_raw[first:last+1]
            plan = json.loads(plan_raw)
            if not isinstance(plan, dict):
                raise ValueError("Plan JSON is not an object.")
            plan.setdefault("problem", "")
            plan.setdefault("assumptions", [])
            plan.setdefault("steps", [])
            plan.setdefault("tool_calls", [])
            return plan
        except Exception:
            return {
                "problem": "",
                "assumptions": [],
                "steps": [],
                "tool_calls": [],
            }

    def _execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[ToolResult]:
        results: List[ToolResult] = []
        for call in tool_calls:
            tool_name = call.get("tool")
            tool_input = str(call.get("input", ""))
            res = self.tools.run(tool_name, tool_input)
            results.append(res)
        return results

    def _build_answer_prompt(
        self,
        task: PsiTask,
        plan: Dict[str, Any],
        tool_results: List[ToolResult],
    ) -> List[Dict[str, str]]:
        user_text = task.user_message
        control = self._build_control_instructions()
        memory_block = self._build_memory_block(user_text)
        history_snippet = self._history_as_text(last_n=8)

        system_msg = {
            "role": "system",
            "content": (
                control
                + "\n\nYou are now in ANSWER mode. "
                  "You have access to an internal JSON plan and tool results. "
                  "Use them to produce a clean final answer. "
                  "Do not show the raw JSON or tool logs unless explicitly asked."
            ),
        }

        tool_json = [tr.to_dict() for tr in tool_results]

        answer_user = {
            "role": "user",
            "content": textwrap.dedent(
                f"""
                USER_MESSAGE:
                {user_text}

                INTERNAL_PLAN (JSON):
                {json.dumps(plan, ensure_ascii=False, indent=2)}

                TOOL_RESULTS:
                {json.dumps(tool_json, ensure_ascii=False, indent=2)}

                RECENT_HISTORY:
                {history_snippet}

                MEMORY_CONTEXT:
                {memory_block}

                Instructions:
                - Follow the plan unless you see a clear improvement.
                - Use tool_results to support calculations or facts they directly provide.
                - Be precise, non-repetitive, and avoid filler.
                - Answer exactly the user's real need.
                - If you had to make assumptions, state them briefly at the end.
                """
            ).strip(),
        }

        return [system_msg, answer_user]

    # ---- public entrypoint ----

    def handle_user_message(self, user_text: str) -> str:
        task = PsiTask(
            id=str(uuid.uuid4()),
            user_message=user_text,
            created_at=now_ts(),
        )

        user_turn = Turn(role="user", content=user_text)
        self.history.append(user_turn)

        # Update Ψ components
        self._update_preferences_from_user(user_text)
        self._update_psi_state(user_text)

        # 1) Planning
        try:
            planning_prompt = self._build_planning_prompt(task)
            plan_raw = self.llm_plan.generate(planning_prompt)
            plan = self._parse_plan(plan_raw)
            task.plan = plan
        except Exception:
            plan = {
                "problem": "",
                "assumptions": [],
                "steps": [],
                "tool_calls": [],
            }
            task.plan = plan

        # 2) Tools
        tool_calls = plan.get("tool_calls", []) or []
        tool_results = self._execute_tools(tool_calls)
        task.tool_results = tool_results

        # 3) Final answer
        try:
            answer_prompt = self._build_answer_prompt(task, plan, tool_results)
            answer_raw = self.llm_answer.generate(answer_prompt)
            answer_text = answer_raw.strip()
        except Exception:
            answer_text = "An internal error occurred while generating the answer."

        task.result = answer_text
        task.status = "done"

        # 4) Memory update
        try:
            self._maybe_store_memory(user_text, answer_text)
        except Exception:
            pass

        # 5) History + persist profile
        self.history.append(Turn(role="assistant", content=answer_text))
        self.profile_store.save()

        return answer_text


# ============================================================
# 10) WIRED RUNTIME / REPL
# ============================================================

def build_default_engine(cfg: Optional[PsiConfig] = None) -> PsiEngine:
    cfg = cfg or PsiConfig()

    backend_type = "dummy" if cfg.dummy_backend else "openai"

    llm_plan = LLMClient(
        backend=backend_type,
        model="gpt-4.1-mini",
        temperature=cfg.planning_temperature,
        max_tokens=cfg.max_tokens_plan,
    )
    llm_answer = LLMClient(
        backend=backend_type,
        model="gpt-4.1-mini",
        temperature=cfg.answer_temperature,
        max_tokens=cfg.max_tokens_answer,
    )

    emb = EmbeddingClient(backend="dummy")
    profile_store = ProfileStore(path=cfg.profile_path)
    semantic_memory = VectorMemoryStore(
        emb, path=cfg.memory_path, max_items=cfg.max_semantic_items, kind="semantic"
    )
    episodic_memory = VectorMemoryStore(
        emb, path=cfg.episodic_path, max_items=cfg.max_episodic_items, kind="episodic"
    )
    tools = ToolRegistry()

    engine = PsiEngine(
        cfg=cfg,
        llm_plan=llm_plan,
        llm_answer=llm_answer,
        emb=emb,
        profile_store=profile_store,
        semantic_memory=semantic_memory,
        episodic_memory=episodic_memory,
        tools=tools,
    )
    return engine


def build_isolated_config(base_dir: Optional[str] = None) -> PsiConfig:
    """
    Build a config whose persistent state lives in an isolated directory.
    Useful for simulations, tests, and edit-review passes where we do not want
    to pollute the main persistent profile or memory files.
    """
    if base_dir is None:
        base_dir = tempfile.mkdtemp(prefix="atulya-brain-")

    return PsiConfig(
        profile_path=os.path.join(base_dir, "psi_profile.json"),
        memory_path=os.path.join(base_dir, "psi_memory.json"),
        episodic_path=os.path.join(base_dir, "psi_episodic.json"),
    )


def run_once(user_text: str, cfg: Optional[PsiConfig] = None) -> str:
    """
    Run a single prompt through the default engine without entering the REPL.
    """
    engine = build_default_engine(cfg or build_isolated_config())
    return engine.handle_user_message(user_text)


def repl():
    cfg = PsiConfig()
    engine = build_default_engine(cfg)

    print("Ψ OS REPL")
    print("Type 'exit' or 'quit' to stop.")
    print("-" * 60)

    while True:
        try:
            user_text = input("\nYOU: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if user_text.lower() in {"exit", "quit"}:
            print("Exiting.")
            break

        if not user_text:
            continue

        try:
            response = engine.handle_user_message(user_text)
        except Exception as e:
            traceback.print_exc()
            response = f"Internal error: {e}"

        print("\nΨ-AGENT:")
        print(response)


if __name__ == "__main__":
    repl()
