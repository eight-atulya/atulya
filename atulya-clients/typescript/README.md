# Atulya TypeScript Client

TypeScript client library for the Atulya API.

## Installation

```bash
npm install @eight-atulya/atulya-client
# or
yarn add @eight-atulya/atulya-client
```

## Usage

```typescript
import { AtulyaClient } from '@eight-atulya/atulya-client';

const client = new AtulyaClient({ baseUrl: 'http://localhost:8888' });

// Retain information
await client.retain('my-bank', 'Alice works at Google in Mountain View.');

// Recall memories
const results = await client.recall('my-bank', 'Where does Alice work?');

// Reflect and get an opinion
const response = await client.reflect('my-bank', 'What do you think about Alice\'s career?');
```

## API Reference

### `retain(bankId, content, options?)`

Store a single memory.

```typescript
await client.retain('my-bank', 'User prefers dark mode', {
  timestamp: new Date(),
  context: 'Settings conversation',
  metadata: { source: 'chat' }
});
```

### `retainBatch(bankId, items, options?)`

Store multiple memories in batch.

```typescript
await client.retainBatch('my-bank', [
  { content: 'Alice loves hiking' },
  { content: 'Alice visited Paris last summer' }
], { async: true });
```

### `recall(bankId, query, options?)`

Recall memories matching a query.

```typescript
const results = await client.recall('my-bank', 'What are Alice\'s hobbies?', {
  budget: 'mid'
});
```

### `reflect(bankId, query, options?)`

Generate a contextual answer using the bank's identity and memories.

```typescript
const response = await client.reflect('my-bank', 'What should I do this weekend?', {
  budget: 'low'
});
console.log(response.text);
```

### `createBank(bankId, options)`

Create or update a memory bank with personality.

```typescript
await client.createBank('my-bank', {
  name: 'My Assistant',
  background: 'A helpful assistant that remembers everything.'
});
```

## Documentation

For full documentation, visit [atulya](https://github.com/eight-atulya/atulya).
