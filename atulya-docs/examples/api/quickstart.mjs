#!/usr/bin/env node
/**
 * Quickstart examples for Atulya API (Node.js)
 * Run: node examples/api/quickstart.mjs
 */

const ATULYA_URL = process.env.ATULYA_API_URL || 'http://localhost:8888';

// =============================================================================
// Doc Examples
// =============================================================================

// [docs:quickstart-full]
import { AtulyaClient } from '@eight-atulya/atulya-client';

const client = new AtulyaClient({ baseUrl: 'http://localhost:8888' });

// Retain: Store information
await client.retain('my-bank', 'Alice works at Google as a software engineer');

// Recall: Search memories
await client.recall('my-bank', 'What does Alice do?');

// Reflect: Generate response
await client.reflect('my-bank', 'Tell me about Alice');
// [/docs:quickstart-full]


// =============================================================================
// Cleanup (not shown in docs)
// =============================================================================
await fetch(`${ATULYA_URL}/v1/default/banks/my-bank`, { method: 'DELETE' });

console.log('quickstart.mjs: All examples passed');
