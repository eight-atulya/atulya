---
sidebar_position: 15
---

# Atulya AI SDK - Personal Chef


:::info Complete Application
This is a complete, runnable application demonstrating Atulya integration.
[**View source on GitHub →**](https://github.com/eight-atulya/atulya-cookbook/tree/main/applications/taste-ai)
:::


A personal food assistant demonstrating three key Atulya integrations using the [Vercel AI SDK v6](https://sdk.vercel.ai/docs).

## Architecture: Single Bank with User Tags

This demo uses a **single Atulya bank** (`taste-ai`) for all users, with each user's data tagged using `user:${username}`.

```typescript
// All users share the same bank
const BANK_ID = 'taste-ai';

// Each memory is tagged with the user
await atulyaTools.retain.execute({
  bankId: BANK_ID,
  content: userData,
  tags: [`user:${username}`],
});
```

This architecture enables:
- **Per-user queries**: Filter by `user:alice` to get personalized results
- **Aggregated insights**: Query across all users to find popular recipes or common dietary patterns
- **Simplified management**: One bank to maintain instead of per-user banks

## Three Atulya Integrations

### 1. Meal Suggestions with Memory Recall & Reflection

Uses `recall` and `reflect` tools with AI SDK's agent-based approach to gather personalized context.

```typescript
const contextResult = await generateText({
  model: llmModel,
  tools: {
    recall: atulyaTools.recall,
    reflect: atulyaTools.reflect,
  },
  toolChoice: 'auto',
  prompt: `You are gathering context for personalized ${mealType} recipe suggestions.

Use the recall tool to search for the user's food preferences, dislikes, and recent meals.
Then use the reflect tool to analyze their dietary patterns and restrictions.

After gathering context, summarize their preferences and recent eating patterns.`,
});
```

The AI agent autonomously:
- Searches memory for cuisine preferences and dietary restrictions
- Analyzes recent protein consumption for variety
- Identifies foods to avoid

### 2. Goal Progress Tracking with Mental Models

Uses mental models to automatically maintain updated insights about user progress.

```typescript
// Create a mental model that auto-refreshes after new meals
await atulyaTools.createMentalModel.execute({
  bankId: BANK_ID,
  mentalModelId: getMentalModelId(username, 'goals'),
  name: `${username}'s Goal Progress`,
  sourceQuery: `Analyze ${username}'s dietary goals and eating patterns.
    Describe their progress towards their stated goals (weight loss, muscle gain, etc.).`,
  tags: [`user:${username}`],
  autoRefresh: true, // Refreshes automatically after consolidation
});

// Query the mental model for current insights
const result = await atulyaTools.queryMentalModel.execute({
  bankId: BANK_ID,
  mentalModelId: mentalModelId,
});
```

Mental models automatically:
- Track progress towards dietary goals
- Update after each new meal is logged
- Provide fresh insights without manual refresh

### 3. Language Enforcement with Directives

Uses directives to ensure all responses match user's language preference.

```typescript
await atulyaClient.createDirective(BANK_ID, {
  name: `${username}'s Language Preference`,
  content: `Always respond in ${language}. All suggestions must be in ${language}.`,
  priority: 100,
  tags: [`user:${username}`, 'directive:language'],
});
```

Directives are automatically injected when mental models generate insights, ensuring consistent language across all interactions.

## Running the Demo

```bash
npm install
npm run dev
```

**Requirements:**
- Atulya server running at `http://localhost:8888` (or set `ATULYA_URL`)
- Node.js 18+

## Learn More

- [Atulya AI SDK on npm](https://www.npmjs.com/package/@eight-atulya/atulya-ai-sdk)
- [AI SDK Documentation](https://sdk.vercel.ai/docs)
