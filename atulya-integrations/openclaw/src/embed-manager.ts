import { spawn, ChildProcess } from 'child_process';
import { join } from 'path';
import { homedir } from 'os';

export class AtulyaEmbedManager {
  private process: ChildProcess | null = null;
  private port: number;
  private baseUrl: string;
  private embedDir: string;
  private llmProvider: string;
  private llmApiKey: string;
  private llmModel?: string;
  private llmBaseUrl?: string;
  private daemonIdleTimeout: number;
  private embedVersion: string;
  private embedPackagePath?: string;

  constructor(
    port: number,
    llmProvider: string,
    llmApiKey: string,
    llmModel?: string,
    llmBaseUrl?: string,
    daemonIdleTimeout: number = 0, // Default: never timeout
    embedVersion: string = 'latest', // Default: latest
    embedPackagePath?: string // Local path to atulya package
  ) {
    // Use the configured port (default: 9077 from config)
    this.port = port;
    this.baseUrl = `http://127.0.0.1:${port}`;
    this.embedDir = join(homedir(), '.openclaw', 'atulya-embed');
    this.llmProvider = llmProvider;
    this.llmApiKey = llmApiKey;
    this.llmModel = llmModel;
    this.llmBaseUrl = llmBaseUrl;
    this.daemonIdleTimeout = daemonIdleTimeout;
    this.embedVersion = embedVersion || 'latest';
    this.embedPackagePath = embedPackagePath;
  }

  /**
   * Get the command to run atulya-embed (either local or from PyPI)
   */
  private getEmbedCommand(): string[] {
    if (this.embedPackagePath) {
      // Local package: uv run --directory <path> atulya-embed
      return ['uv', 'run', '--directory', this.embedPackagePath, 'atulya-embed'];
    } else {
      // PyPI package: uvx atulya-embed@version
      const embedPackage = this.embedVersion ? `atulya-embed@${this.embedVersion}` : 'atulya-embed@latest';
      return ['uvx', embedPackage];
    }
  }

  async start(): Promise<void> {
    console.log(`[Atulya] Starting atulya-embed daemon...`);

    // Build environment variables using standard ATULYA_API_LLM_* variables
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      ATULYA_API_LLM_PROVIDER: this.llmProvider,
      ATULYA_API_LLM_API_KEY: this.llmApiKey,
      ATULYA_EMBED_DAEMON_IDLE_TIMEOUT: this.daemonIdleTimeout.toString(),
    };

    if (this.llmModel) {
      env['ATULYA_API_LLM_MODEL'] = this.llmModel;
    }

    // Pass through base URL for OpenAI-compatible providers (OpenRouter, etc.)
    if (this.llmBaseUrl) {
      env['ATULYA_API_LLM_BASE_URL'] = this.llmBaseUrl;
    }

    // On macOS, force CPU for embeddings/reranker to avoid MPS/Metal issues in daemon mode
    if (process.platform === 'darwin') {
      env['ATULYA_API_EMBEDDINGS_LOCAL_FORCE_CPU'] = '1';
      env['ATULYA_API_RERANKER_LOCAL_FORCE_CPU'] = '1';
    }

    // Configure "openclaw" profile using atulya-embed configure (non-interactive)
    console.log('[Atulya] Configuring "openclaw" profile...');
    await this.configureProfile(env);

    // Start atulya-embed daemon with openclaw profile
    const embedCmd = this.getEmbedCommand();
    const startDaemon = spawn(
      embedCmd[0],
      [...embedCmd.slice(1), 'daemon', '--profile', 'openclaw', 'start'],
      {
        stdio: 'pipe',
      }
    );

    // Collect output
    let output = '';
    startDaemon.stdout?.on('data', (data) => {
      const text = data.toString();
      output += text;
      console.log(`[Atulya] ${text.trim()}`);
    });

    startDaemon.stderr?.on('data', (data) => {
      const text = data.toString();
      output += text;
      console.error(`[Atulya] ${text.trim()}`);
    });

    // Wait for daemon start command to complete
    await new Promise<void>((resolve, reject) => {
      startDaemon.on('exit', (code) => {
        if (code === 0) {
          console.log('[Atulya] Daemon start command completed');
          resolve();
        } else {
          reject(new Error(`Daemon start failed with code ${code}: ${output}`));
        }
      });

      startDaemon.on('error', (error) => {
        reject(error);
      });
    });

    // Wait for server to be ready
    await this.waitForReady();
    console.log('[Atulya] Daemon is ready');
  }

  async stop(): Promise<void> {
    console.log('[Atulya] Stopping atulya-embed daemon...');

    const embedCmd = this.getEmbedCommand();
    const stopDaemon = spawn(embedCmd[0], [...embedCmd.slice(1), 'daemon', '--profile', 'openclaw', 'stop'], {
      stdio: 'pipe',
    });

    await new Promise<void>((resolve) => {
      stopDaemon.on('exit', () => {
        console.log('[Atulya] Daemon stopped');
        resolve();
      });

      stopDaemon.on('error', (error) => {
        console.error('[Atulya] Error stopping daemon:', error);
        resolve(); // Resolve anyway
      });

      // Timeout after 5 seconds
      setTimeout(() => {
        console.log('[Atulya] Daemon stop timeout');
        resolve();
      }, 5000);
    });
  }

  private async waitForReady(maxAttempts = 30): Promise<void> {
    console.log('[Atulya] Waiting for daemon to be ready...');
    for (let i = 0; i < maxAttempts; i++) {
      try {
        const response = await fetch(`${this.baseUrl}/health`);
        if (response.ok) {
          console.log('[Atulya] Daemon health check passed');
          return;
        }
      } catch {
        // Not ready yet
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error('Atulya daemon failed to become ready within 30 seconds');
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  isRunning(): boolean {
    return this.process !== null;
  }

  async checkHealth(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/health`, { signal: AbortSignal.timeout(2000) });
      return response.ok;
    } catch {
      return false;
    }
  }

  private async configureProfile(env: NodeJS.ProcessEnv): Promise<void> {
    // Build profile create command args with --merge, --port and --env flags
    // Use --merge to allow updating existing profile
    const createArgs = ['profile', 'create', 'openclaw', '--merge', '--port', this.port.toString()];

    // Add all environment variables as --env flags
    const envVars = [
      'ATULYA_API_LLM_PROVIDER',
      'ATULYA_API_LLM_MODEL',
      'ATULYA_API_LLM_API_KEY',
      'ATULYA_API_LLM_BASE_URL',
      'ATULYA_EMBED_DAEMON_IDLE_TIMEOUT',
      'ATULYA_API_EMBEDDINGS_LOCAL_FORCE_CPU',
      'ATULYA_API_RERANKER_LOCAL_FORCE_CPU',
    ];

    for (const envVar of envVars) {
      if (env[envVar]) {
        createArgs.push('--env', `${envVar}=${env[envVar]}`);
      }
    }

    // Run profile create command (non-interactive, overwrites if exists)
    const embedCmd = this.getEmbedCommand();
    const create = spawn(embedCmd[0], [...embedCmd.slice(1), ...createArgs], {
      stdio: 'pipe',
    });

    let output = '';
    create.stdout?.on('data', (data) => {
      const text = data.toString();
      output += text;
      console.log(`[Atulya] ${text.trim()}`);
    });

    create.stderr?.on('data', (data) => {
      const text = data.toString();
      output += text;
      console.error(`[Atulya] ${text.trim()}`);
    });

    await new Promise<void>((resolve, reject) => {
      create.on('exit', (code) => {
        if (code === 0) {
          console.log('[Atulya] Profile "openclaw" configured successfully');
          resolve();
        } else {
          reject(new Error(`Profile create failed with code ${code}: ${output}`));
        }
      });

      create.on('error', (error) => {
        reject(error);
      });
    });
  }
}
