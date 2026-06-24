---
title: "Give your OpenAI app a memory in five minutes"
authors: [atulya]
date: 2026-03-05
tags: [memory, openai, python, docker, rag, llm]
hide_table_of_contents: true
slug: openai-app-memory
---

Build a ChatGPT-style loop with `retain()`, `recall()`, and `reflect()`. No vector DB, no embedding pipeline, no custom RAG.

<!-- truncate -->

## TL;DR

- `retain()` after each turn
- `recall()` before each completion (or `reflect()` for synthesis questions)
- Restart the process; memory survives in the bank

## The problem

```python
messages = [{"role": "system", "content": "You are a helpful assistant."}]
```

Works until you restart. Serializing `messages` to disk hits context limits, cost, and truncation. That is chat history, not durable memory.

## Architecture

```
User message
     ↓
recall(query)
     ↓
OpenAI completion  (system + recalled context)
     ↓
retain(exchange)
     ↓
Response
```

## Step 1: start Atulya

```bash
pip install atulya-all
export ATULYA_API_LLM_API_KEY=YOUR_OPENAI_KEY
atulya-api
```

Runs at `http://localhost:8888` with embedded Postgres, extraction, search, graph, synthesis.

[Atulya Cloud](https://ui.atulya.eightengine.com/signup): swap `base_url` for your cloud endpoint.

## Step 2: baseline chat (no memory)

```python
from openai import OpenAI

openai = OpenAI()
messages = [{"role": "system", "content": "You are a helpful assistant."}]

while True:
    user_input = input("You: ")
    if user_input in ("quit", "exit"):
        break
    messages.append({"role": "user", "content": user_input})
    response = openai.chat.completions.create(model="gpt-4o-mini", messages=messages)
    reply = response.choices[0].message.content
    messages.append({"role": "assistant", "content": reply})
    print(reply)
```

Restart, ask your name: blank.

## Step 3: retain

```python
from atulya_client import Atulya

atulya = Atulya(base_url="http://localhost:8888")
atulya.create_bank(
    bank_id="chatbot",
    name="Chatbot Memory",
    reflect_mission="Remember user preferences and important facts.",
)

atulya.retain(
    bank_id="chatbot",
    content=f"User: {user_input}\nAssistant: {reply}",
)
```

## Step 4: recall

```python
memories = atulya.recall(bank_id="chatbot", query=user_input, budget="low")
memory_context = "\n".join(r.text for r in memories.results)

system_prompt = "You are a helpful assistant."
if memory_context:
    system_prompt += "\n\nRelevant past context:\n" + memory_context
```

## Step 5: reflect for synthesis

For "what do you know about me?" / "summarize our chats":

```python
reflection = atulya.reflect(bank_id="chatbot", query=user_input)
memory_context = reflection.text
```

## Full example

```python
from openai import OpenAI
from atulya_client import Atulya

openai = OpenAI()
atulya = Atulya(base_url="http://localhost:8888")

atulya.create_bank(
    bank_id="chatbot",
    name="Chatbot Memory",
    reflect_mission="Remember user preferences and key facts.",
)

SYSTEM_PROMPT = "You are a helpful assistant with long-term memory."
SYNTHESIS_KEYWORDS = ["summarize", "what do you know about me", "what have we talked about"]


def get_memory_context(user_input):
    if any(k in user_input.lower() for k in SYNTHESIS_KEYWORDS):
        return atulya.reflect(bank_id="chatbot", query=user_input).text
    memories = atulya.recall(bank_id="chatbot", query=user_input, budget="low")
    return "\n".join(r.text for r in memories.results)


def main():
    conversation = []
    print("Chat with memory. Type 'quit' to exit.\n")
    while True:
        user_input = input("You: ")
        if user_input in ("quit", "exit"):
            break
        memory_context = get_memory_context(user_input)
        conversation.append({"role": "user", "content": user_input})
        system = SYSTEM_PROMPT
        if memory_context:
            system += "\n\nRelevant context:\n" + memory_context
        messages = [{"role": "system", "content": system}] + conversation
        response = openai.chat.completions.create(model="gpt-4o-mini", messages=messages)
        reply = response.choices[0].message.content
        conversation.append({"role": "assistant", "content": reply})
        print(f"\nAssistant: {reply}\n")
        atulya.retain(
            bank_id="chatbot",
            content=f"User: {user_input}\nAssistant: {reply}",
        )


if __name__ == "__main__":
    main()
```

## Production notes

1. Retain **after** responding.
2. `budget="low"` in chat loops; raise only when needed.
3. One bank per user in multi-tenant apps.
4. Set a clear bank mission.
5. Retain everything first; optimize later.

## When to use / skip

**Use:** cross-session memory, synthesis over time, no appetite to run RAG infra.

**Skip:** single-session-only bots, structured data that belongs in a database.

## Next steps

- Per-user `bank_id`
- Tags on retain, `tags_match` on recall
- `response_schema` on reflect for structured output
- Control plane / Docker UI on port 9999
- [Hosted Atulya](https://ui.atulya.eightengine.com/signup)
