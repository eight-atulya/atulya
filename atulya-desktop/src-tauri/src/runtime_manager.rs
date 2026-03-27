use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tokio::sync::RwLock;
use tracing::{error, info};

use crate::process_supervisor::{ProcessConfig, ProcessState, ProcessStatus, SupervisedProcess};
use crate::runtime_profiles::{resolve_profile, RuntimeProfile};
use crate::settings_store::Settings;

const API_PORT: u16 = 8888;
const CP_PORT: u16 = 9999;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeStatus {
    pub api: ProcessStatus,
    pub control_plane: ProcessStatus,
    pub profile_id: String,
    pub data_dir: String,
}

pub struct RuntimeManager {
    data_dir: PathBuf,
    profile: RwLock<RuntimeProfile>,
    api_process: SupervisedProcess,
    cp_process: SupervisedProcess,
}

impl RuntimeManager {
    pub fn new(data_dir: PathBuf, settings: Settings) -> Self {
        let profile = resolve_profile(&settings.profile);

        let env_vars = profile.to_env_vars(
            &data_dir,
            Self::resolve_native_lib(&data_dir).as_deref(),
        );
        let env_vec: Vec<(String, String)> = env_vars.into_iter().collect();

        let api_runtime_dir = data_dir.join("runtime").join("api");
        let cp_runtime_dir = data_dir.join("runtime").join("control-plane");

        let api_config = ProcessConfig {
            name: "atulya-api".into(),
            command: Self::resolve_python(&api_runtime_dir),
            args: vec![
                "-m".into(),
                "atulya_api".into(),
            ],
            working_dir: Some(api_runtime_dir.clone()),
            env: env_vec.clone(),
            health_url: Some(format!("http://127.0.0.1:{API_PORT}/health")),
            health_timeout: Duration::from_secs(120),
            health_interval: Duration::from_secs(1),
            health_retries: 120,
            max_restarts: 3,
            shutdown_timeout: Duration::from_secs(10),
        };

        let mut cp_env = env_vec;
        cp_env.push(("PORT".into(), CP_PORT.to_string()));
        cp_env.push(("NODE_ENV".into(), "production".into()));
        cp_env.push((
            "ATULYA_CP_DATAPLANE_API_URL".into(),
            format!("http://127.0.0.1:{API_PORT}"),
        ));

        let cp_config = ProcessConfig {
            name: "control-plane".into(),
            command: Self::resolve_node(&cp_runtime_dir),
            args: vec!["server.js".into()],
            working_dir: Some(cp_runtime_dir),
            env: cp_env,
            health_url: Some(format!("http://127.0.0.1:{CP_PORT}/")),
            health_timeout: Duration::from_secs(30),
            health_interval: Duration::from_secs(1),
            health_retries: 30,
            max_restarts: 3,
            shutdown_timeout: Duration::from_secs(5),
        };

        Self {
            data_dir,
            profile: RwLock::new(profile),
            api_process: SupervisedProcess::new(api_config),
            cp_process: SupervisedProcess::new(cp_config),
        }
    }

    pub async fn start(&self) -> Result<(), RuntimeError> {
        info!("starting atulya runtime");

        self.api_process
            .start()
            .await
            .map_err(|e| RuntimeError::ApiStartFailed(e.to_string()))?;

        self.cp_process
            .start()
            .await
            .map_err(|e| RuntimeError::ControlPlaneStartFailed(e.to_string()))?;

        info!("atulya runtime started");
        Ok(())
    }

    pub async fn stop(&self) -> Result<(), RuntimeError> {
        info!("stopping atulya runtime");

        // Stop control plane first, then API (reverse dependency order)
        if let Err(e) = self.cp_process.stop().await {
            error!("control-plane stop error: {e}");
        }
        if let Err(e) = self.api_process.stop().await {
            error!("api stop error: {e}");
        }

        info!("atulya runtime stopped");
        Ok(())
    }

    pub async fn status(&self) -> RuntimeStatus {
        let profile = self.profile.read().await;
        RuntimeStatus {
            api: self.api_process.status().await,
            control_plane: self.cp_process.status().await,
            profile_id: profile.id.to_string(),
            data_dir: self.data_dir.display().to_string(),
        }
    }

    fn resolve_python(api_dir: &Path) -> String {
        let venv_python = if cfg!(windows) {
            api_dir.join(".venv").join("Scripts").join("python.exe")
        } else {
            api_dir.join(".venv").join("bin").join("python")
        };
        if venv_python.exists() {
            return venv_python.display().to_string();
        }
        "python3".into()
    }

    fn resolve_node(cp_dir: &Path) -> String {
        let local_node = if cfg!(windows) {
            cp_dir.join("node.exe")
        } else {
            cp_dir.join("node")
        };
        if local_node.exists() {
            return local_node.display().to_string();
        }
        "node".into()
    }

    fn resolve_native_lib(data_dir: &Path) -> Option<PathBuf> {
        let lib_name = if cfg!(target_os = "macos") {
            "libatulya_brain.dylib"
        } else if cfg!(target_os = "windows") {
            "atulya_brain.dll"
        } else {
            "libatulya_brain.so"
        };

        let path = data_dir.join("runtime").join("brain").join(lib_name);
        if path.exists() {
            Some(path)
        } else {
            None
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum RuntimeError {
    #[error("API start failed: {0}")]
    ApiStartFailed(String),

    #[error("Control plane start failed: {0}")]
    ControlPlaneStartFailed(String),
}
