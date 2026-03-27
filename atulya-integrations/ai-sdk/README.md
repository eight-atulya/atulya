# Atulya Memory Integration for Vercel AI SDK

Give your AI agents persistent, human-like memory using [Atulya](https://github.com/eight-atulya/atulya) with the [Vercel AI SDK](https://ai-sdk.dev).

## Quick Start

```bash
npm install @eight-atulya/atulya-ai-sdk @eight-atulya/atulya-client ai zod
```

```typescript
import { AtulyaClient } from '@eight-atulya/atulya-client';
import { createAtulyaTools } from '@eight-atulya/atulya-ai-sdk';
import { generateText } from 'ai';
import { anthropic } from '@ai-sdk/anthropic';

// 1. Initialize Atulya client
const atulyaClient = new AtulyaClient({
  apiUrl: 'http://localhost:8000',
});

// 2. Create memory tools
const tools = createAtulyaTools({ client: atulyaClient });

// 3. Use with AI SDK
const result = await generateText({
  model: anthropic('claude-sonnet-4-20250514'),
  tools,
  system: `You have long-term memory. Use:
  - 'recall' to search past conversations
  - 'retain' to remember important information
  - 'reflect' to synthesize insights from memories`,
  prompt: 'Remember that Alice loves hiking and prefers spicy food',
});

console.log(result.text);
```

## Features

✅ **Three Memory Tools**: `retain` (store), `recall` (retrieve), and `reflect` (reason over memories)
✅ **AI SDK 6 Native**: Works with `generateText`, `streamText`, and `ToolLoopAgent`
✅ **Multi-User Support**: Dynamic bank IDs per call for multi-user scenarios
✅ **Type-Safe**: Full TypeScript support with Zod schemas
✅ **Flexible Client**: Works with the official TypeScript client or custom HTTP clients

## Documentation

📖 **[Full Documentation](https://github.com/eight-atulya/atulya/blob/main/atulya-docs/docs/sdks/integrations/ai-sdk.mdx)**

The complete documentation includes:
- Detailed tool descriptions and parameters
- Advanced usage patterns (streaming, multi-user, ToolLoopAgent)
- HTTP client example (no dependencies)
- TypeScript types and API reference
- Best practices and system prompt examples

## Running Atulya Locally

```bash
# Install and run with embedded mode (no setup required)
uvx atulya-embed@latest -p myapp daemon start

# The API will be available at http://localhost:8000
```

## Examples

Full examples are available in the [GitHub repository](https://github.com/eight-atulya/atulya/tree/main/examples/ai-sdk).

## Support

- [Documentation](https://github.com/eight-atulya/atulya/tree/main/atulya-docs)
- [GitHub Issues](https://github.com/eight-atulya/atulya/issues)
- Email: support@eightengine.com

## License

MIT
