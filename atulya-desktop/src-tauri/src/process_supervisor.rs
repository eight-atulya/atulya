use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::{watch, Mutex};
use tracing::{debug, error, info, warn};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessState {
    Stopped,
    Starting,
    Running,
    Stopping,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProcessStatus {
    pub name: String,
    pub state: ProcessState,
    pub pid: Option<u32>,
    pub exit_code: Option<i32>,
    pub restart_count: u32,
    pub last_error: Option<String>,
}

#[derive(Debug, Clone)]
pub struct ProcessConfig {
    pub name: String,
    pub command: String,
    pub args: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub env: Vec<(String, String)>,
    pub health_url: Option<String>,
    pub health_timeout: Duration,
    pub health_interval: Duration,
    pub health_retries: u32,
    pub max_restarts: u32,
    pub shutdown_timeout: Duration,
}

impl Default for ProcessConfig {
    fn default() -> Self {
        Self {
            name: String::new(),
            command: String::new(),
            args: Vec::new(),
            working_dir: None,
            env: Vec::new(),
            health_url: None,
            health_timeout: Duration::from_secs(120),
            health_interval: Duration::from_secs(1),
            health_retries: 120,
            max_restarts: 3,
            shutdown_timeout: Duration::from_secs(10),
        }
    }
}

struct Inner {
    child: Option<Child>,
    state: ProcessState,
    pid: Option<u32>,
    exit_code: Option<i32>,
    restart_count: u32,
    last_error: Option<String>,
}

pub struct SupervisedProcess {
    config: ProcessConfig,
    inner: Arc<Mutex<Inner>>,
    state_tx: watch::Sender<ProcessState>,
    state_rx: watch::Receiver<ProcessState>,
}

impl SupervisedProcess {
    pub fn new(config: ProcessConfig) -> Self {
        let (state_tx, state_rx) = watch::channel(ProcessState::Stopped);
        Self {
            config,
            inner: Arc::new(Mutex::new(Inner {
                child: None,
                state: ProcessState::Stopped,
                pid: None,
                exit_code: None,
                restart_count: 0,
                last_error: None,
            })),
            state_tx,
            state_rx,
        }
    }

    pub fn subscribe(&self) -> watch::Receiver<ProcessState> {
        self.state_rx.clone()
    }

    fn set_state(inner: &mut Inner, tx: &watch::Sender<ProcessState>, s: ProcessState) {
        inner.state = s;
        let _ = tx.send(s);
    }

    pub async fn start(&self) -> Result<(), SupervisorError> {
        let mut guard = self.inner.lock().await;
        if guard.state == ProcessState::Running || guard.state == ProcessState::Starting {
            return Ok(());
        }

        Self::set_state(&mut guard, &self.state_tx, ProcessState::Starting);
        guard.exit_code = None;
        guard.last_error = None;

        let child = self.spawn_child().await?;
        let pid = child.id();
        guard.child = Some(child);
        guard.pid = pid;

        info!(
            name = %self.config.name,
            pid = ?pid,
            "process spawned"
        );

        Self::set_state(&mut guard, &self.state_tx, ProcessState::Running);
        drop(guard);

        if self.config.health_url.is_some() {
            self.wait_healthy().await?;
        }

        Ok(())
    }

    pub async fn stop(&self) -> Result<(), SupervisorError> {
        let mut guard = self.inner.lock().await;
        if guard.state == ProcessState::Stopped {
            return Ok(());
        }

        Self::set_state(&mut guard, &self.state_tx, ProcessState::Stopping);

        if let Some(ref mut child) = guard.child {
            #[cfg(unix)]
            {
                if let Some(pid) = child.id() {
                    unsafe {
                        libc::kill(pid as i32, libc::SIGTERM);
                    }
                }
            }
            #[cfg(windows)]
            {
                let _ = child.kill().await;
            }

            let timeout = self.config.shutdown_timeout;
            match tokio::time::timeout(timeout, child.wait()).await {
                Ok(Ok(status)) => {
                    guard.exit_code = status.code();
                    info!(name = %self.config.name, code = ?status.code(), "process exited");
                }
                Ok(Err(e)) => {
                    warn!(name = %self.config.name, err = %e, "wait failed, force killing");
                    let _ = child.kill().await;
                }
                Err(_) => {
                    warn!(name = %self.config.name, "graceful timeout, force killing");
                    let _ = child.kill().await;
                    let _ = child.wait().await;
                }
            }
        }

        guard.child = None;
        guard.pid = None;
        Self::set_state(&mut guard, &self.state_tx, ProcessState::Stopped);
        Ok(())
    }

    pub async fn status(&self) -> ProcessStatus {
        let guard = self.inner.lock().await;
        ProcessStatus {
            name: self.config.name.clone(),
            state: guard.state,
            pid: guard.pid,
            exit_code: guard.exit_code,
            restart_count: guard.restart_count,
            last_error: guard.last_error.clone(),
        }
    }

    async fn spawn_child(&self) -> Result<Child, SupervisorError> {
        let mut cmd = Command::new(&self.config.command);
        cmd.args(&self.config.args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);

        if let Some(ref dir) = self.config.working_dir {
            cmd.current_dir(dir);
        }

        for (key, val) in &self.config.env {
            cmd.env(key, val);
        }

        let mut child = cmd.spawn().map_err(|e| SupervisorError::SpawnFailed {
            name: self.config.name.clone(),
            source: e.to_string(),
        })?;

        let name = self.config.name.clone();
        if let Some(stdout) = child.stdout.take() {
            let name = name.clone();
            tokio::spawn(async move {
                let reader = BufReader::new(stdout);
                let mut lines = reader.lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    debug!(process = %name, "{line}");
                }
            });
        }
        if let Some(stderr) = child.stderr.take() {
            tokio::spawn(async move {
                let reader = BufReader::new(stderr);
                let mut lines = reader.lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    warn!(process = %name, stderr = true, "{line}");
                }
            });
        }

        Ok(child)
    }

    async fn wait_healthy(&self) -> Result<(), SupervisorError> {
        let url = match &self.config.health_url {
            Some(u) => u.clone(),
            None => return Ok(()),
        };

        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(5))
            .build()
            .map_err(|e| SupervisorError::HealthCheckFailed {
                name: self.config.name.clone(),
                source: e.to_string(),
            })?;

        for attempt in 1..=self.config.health_retries {
            {
                let guard = self.inner.lock().await;
                if guard.state != ProcessState::Running && guard.state != ProcessState::Starting {
                    return Err(SupervisorError::ProcessExitedDuringHealthCheck {
                        name: self.config.name.clone(),
                    });
                }
            }

            match client.get(&url).send().await {
                Ok(resp) if resp.status().is_success() => {
                    info!(
                        name = %self.config.name,
                        attempt,
                        "health check passed"
                    );
                    return Ok(());
                }
                Ok(resp) => {
                    debug!(
                        name = %self.config.name,
                        attempt,
                        status = %resp.status(),
                        "health check non-200"
                    );
                }
                Err(e) => {
                    debug!(
                        name = %self.config.name,
                        attempt,
                        err = %e,
                        "health check failed"
                    );
                }
            }

            tokio::time::sleep(self.config.health_interval).await;
        }

        let mut guard = self.inner.lock().await;
        let msg = format!(
            "health check failed after {} attempts",
            self.config.health_retries
        );
        guard.last_error = Some(msg.clone());
        Self::set_state(&mut guard, &self.state_tx, ProcessState::Failed);

        Err(SupervisorError::HealthCheckFailed {
            name: self.config.name.clone(),
            source: msg,
        })
    }
}

#[derive(Debug, thiserror::Error)]
pub enum SupervisorError {
    #[error("failed to spawn {name}: {source}")]
    SpawnFailed { name: String, source: String },

    #[error("health check failed for {name}: {source}")]
    HealthCheckFailed { name: String, source: String },

    #[error("{name} exited during health check")]
    ProcessExitedDuringHealthCheck { name: String },
}
