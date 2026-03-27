import { describe, it, expect } from 'vitest';
import { AtulyaClient } from './client.js';

describe('AtulyaClient', () => {
  it('should create instance with model', () => {
    const client = new AtulyaClient({ llmModel: 'gpt-4' });
    expect(client).toBeInstanceOf(AtulyaClient);
  });

  it('should set bank ID', () => {
    const client = new AtulyaClient({});
    expect(() => client.setBankId('test-bank')).not.toThrow();
  });

  it('should create instance with embed package path', () => {
    const client = new AtulyaClient({ llmModel: 'gpt-4', embedPackagePath: '/path/to/atulya' });
    expect(client).toBeInstanceOf(AtulyaClient);
  });

  it('should create instance in HTTP mode', () => {
    const client = new AtulyaClient({
      apiUrl: 'https://api.example.com/',
      apiToken: 'bearer-token',
    });
    expect(client).toBeInstanceOf(AtulyaClient);
  });
});
