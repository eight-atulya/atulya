import { describe, it, expect } from 'vitest';
import { AtulyaClient } from './client.js';

describe('AtulyaClient remote mode without LLM config', () => {
  it('should initialize successfully with only apiUrl and apiToken', () => {
    const client = new AtulyaClient({
      apiUrl: 'https://api.example.com',
      apiToken: 'secret-token',
    });

    expect(client).toBeDefined();
    expect(client).toBeInstanceOf(AtulyaClient);
  });

  it('should allow initialization with partial config', () => {
    const client = new AtulyaClient({
      apiUrl: 'https://api.example.com',
      llmModel: 'gpt-4o-mini',
    });
    expect(client).toBeDefined();
  });
});
