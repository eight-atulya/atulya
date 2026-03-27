use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use tracing::{info, warn};

use crate::runtime_profiles::ProfileId;

const SETTINGS_FILE: &str = "settings.json";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Settings {
    /// Active runtime profile (policy)
    pub profile: ProfileId,

    /// LLM provider override (used when profile is Hybrid)
    pub llm_provider: Option<String>,
    pub llm_api_key: Option<String>,
    pub llm_base_url: Option<String>,
    pub llm_model: Option<String>,

    /// Remote brain learning: requires explicit user opt-in
    pub allow_remote_brain_learning: bool,

    /// Telemetry consent
    pub allow_telemetry: bool,

    /// Auto-update channel
    pub update_channel: UpdateChannel,

    /// Theme preference
    pub theme: Theme,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UpdateChannel {
    Stable,
    Beta,
    Internal,
}

impl Default for UpdateChannel {
    fn default() -> Self {
        Self::Stable
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Theme {
    System,
    Light,
    Dark,
}

impl Default for Theme {
    fn default() -> Self {
        Self::System
    }
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            profile: ProfileId::FullyOffline,
            llm_provider: None,
            llm_api_key: None,
            llm_base_url: None,
            llm_model: None,
            allow_remote_brain_learning: false,
            allow_telemetry: false,
            update_channel: UpdateChannel::default(),
            theme: Theme::default(),
        }
    }
}

pub struct SettingsStore {
    path: PathBuf,
    current: Settings,
}

impl SettingsStore {
    pub fn load_or_default(data_dir: &Path) -> Self {
        let path = data_dir.join(SETTINGS_FILE);
        let current = if path.exists() {
            match std::fs::read_to_string(&path) {
                Ok(contents) => match serde_json::from_str::<Settings>(&contents) {
                    Ok(s) => {
                        info!("loaded settings from {}", path.display());
                        s
                    }
                    Err(e) => {
                        warn!("corrupt settings file, using defaults: {e}");
                        Settings::default()
                    }
                },
                Err(e) => {
                    warn!("could not read settings file: {e}");
                    Settings::default()
                }
            }
        } else {
            info!("no settings file found, using defaults");
            Settings::default()
        };

        Self { path, current }
    }

    pub fn settings(&self) -> &Settings {
        &self.current
    }

    pub fn apply_patch(&mut self, patch: serde_json::Value) -> Result<(), SettingsError> {
        let mut merged =
            serde_json::to_value(&self.current).map_err(|e| SettingsError::Serialize(e.to_string()))?;

        if let (Some(base), Some(overlay)) = (merged.as_object_mut(), patch.as_object()) {
            for (key, value) in overlay {
                base.insert(key.clone(), value.clone());
            }
        } else {
            return Err(SettingsError::InvalidPatch(
                "patch must be a JSON object".into(),
            ));
        }

        let updated: Settings =
            serde_json::from_value(merged).map_err(|e| SettingsError::Deserialize(e.to_string()))?;

        self.current = updated;
        self.persist()?;
        Ok(())
    }

    fn persist(&self) -> Result<(), SettingsError> {
        let json = serde_json::to_string_pretty(&self.current)
            .map_err(|e| SettingsError::Serialize(e.to_string()))?;

        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| SettingsError::Io(e.to_string()))?;
        }

        // Atomic write: write to temp file, then rename
        let tmp_path = self.path.with_extension("json.tmp");
        std::fs::write(&tmp_path, &json).map_err(|e| SettingsError::Io(e.to_string()))?;
        std::fs::rename(&tmp_path, &self.path).map_err(|e| SettingsError::Io(e.to_string()))?;

        info!("settings persisted to {}", self.path.display());
        Ok(())
    }
}

#[derive(Debug, thiserror::Error)]
pub enum SettingsError {
    #[error("serialization error: {0}")]
    Serialize(String),

    #[error("deserialization error: {0}")]
    Deserialize(String),

    #[error("invalid patch: {0}")]
    InvalidPatch(String),

    #[error("io error: {0}")]
    Io(String),
}
