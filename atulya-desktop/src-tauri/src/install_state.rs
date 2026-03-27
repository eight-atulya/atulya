use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tracing::{info, warn};

const INSTALL_STATE_FILE: &str = "install-state.json";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InstallPhase {
    Fresh,
    Bootstrapping,
    Ready,
    Upgrading,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstallState {
    pub phase: InstallPhase,
    pub schema_version: u32,
    pub app_version: String,
    pub installed_at: DateTime<Utc>,
    pub last_boot_at: Option<DateTime<Utc>>,
    pub last_error: Option<String>,
    pub runtime_checksum: Option<String>,

    #[serde(skip)]
    path: PathBuf,
}

impl InstallState {
    /// Current schema version. Bump when the on-disk layout changes in a
    /// way that requires migration (new folders, renamed files, etc.).
    const CURRENT_SCHEMA: u32 = 1;

    pub fn load_or_init(data_dir: &Path) -> Self {
        let path = data_dir.join(INSTALL_STATE_FILE);
        if path.exists() {
            match std::fs::read_to_string(&path) {
                Ok(contents) => match serde_json::from_str::<InstallState>(&contents) {
                    Ok(mut state) => {
                        state.path = path;
                        if state.schema_version < Self::CURRENT_SCHEMA {
                            info!(
                                from = state.schema_version,
                                to = Self::CURRENT_SCHEMA,
                                "install state schema migration needed"
                            );
                            state.migrate_schema();
                        }
                        state.last_boot_at = Some(Utc::now());
                        let _ = state.persist();
                        return state;
                    }
                    Err(e) => {
                        warn!("corrupt install state, re-initializing: {e}");
                    }
                },
                Err(e) => {
                    warn!("could not read install state: {e}");
                }
            }
        }

        let mut state = Self {
            phase: InstallPhase::Fresh,
            schema_version: Self::CURRENT_SCHEMA,
            app_version: env!("CARGO_PKG_VERSION").into(),
            installed_at: Utc::now(),
            last_boot_at: Some(Utc::now()),
            last_error: None,
            runtime_checksum: None,
            path,
        };
        let _ = state.persist();
        state
    }

    pub fn summary(&self) -> InstallSummary {
        InstallSummary {
            phase: self.phase,
            schema_version: self.schema_version,
            app_version: self.app_version.clone(),
            installed_at: self.installed_at,
            last_boot_at: self.last_boot_at,
            last_error: self.last_error.clone(),
            runtime_checksum: self.runtime_checksum.clone(),
        }
    }

    pub fn mark_phase(&mut self, phase: InstallPhase) {
        self.phase = phase;
        if phase == InstallPhase::Failed {
            // keep last_error as-is
        }
        let _ = self.persist();
    }

    pub fn mark_failed(&mut self, error: String) {
        self.phase = InstallPhase::Failed;
        self.last_error = Some(error);
        let _ = self.persist();
    }

    pub fn mark_ready(&mut self, checksum: Option<String>) {
        self.phase = InstallPhase::Ready;
        self.last_error = None;
        self.runtime_checksum = checksum;
        let _ = self.persist();
    }

    pub fn verify_runtime_integrity(&self, data_dir: &Path) -> IntegrityResult {
        let runtime_dir = data_dir.join("runtime");
        if !runtime_dir.exists() {
            return IntegrityResult::Missing;
        }

        let api_dir = runtime_dir.join("api");
        let cp_dir = runtime_dir.join("control-plane");

        if !api_dir.exists() || !cp_dir.exists() {
            return IntegrityResult::Incomplete;
        }

        // Verify checksum if we have one
        if let Some(ref expected) = self.runtime_checksum {
            let actual = Self::compute_runtime_checksum(&runtime_dir);
            if actual.as_deref() != Some(expected.as_str()) {
                return IntegrityResult::Corrupted;
            }
        }

        IntegrityResult::Valid
    }

    fn compute_runtime_checksum(runtime_dir: &Path) -> Option<String> {
        let mut hasher = Sha256::new();
        let manifest = runtime_dir.join("manifest.json");
        if manifest.exists() {
            if let Ok(bytes) = std::fs::read(&manifest) {
                hasher.update(&bytes);
                return Some(hex::encode(hasher.finalize()));
            }
        }
        None
    }

    fn migrate_schema(&mut self) {
        // Future: add migration steps here when CURRENT_SCHEMA > 1
        self.schema_version = Self::CURRENT_SCHEMA;
        info!("install state migrated to schema v{}", self.schema_version);
    }

    fn persist(&self) -> Result<(), std::io::Error> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let json = serde_json::to_string_pretty(&self)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

        let tmp = self.path.with_extension("json.tmp");
        std::fs::write(&tmp, &json)?;
        std::fs::rename(&tmp, &self.path)?;
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstallSummary {
    pub phase: InstallPhase,
    pub schema_version: u32,
    pub app_version: String,
    pub installed_at: DateTime<Utc>,
    pub last_boot_at: Option<DateTime<Utc>>,
    pub last_error: Option<String>,
    pub runtime_checksum: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IntegrityResult {
    Valid,
    Missing,
    Incomplete,
    Corrupted,
}
