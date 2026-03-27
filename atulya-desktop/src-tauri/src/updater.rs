use serde::Serialize;
use tracing::{info, warn};

#[derive(Debug, Serialize)]
pub struct UpdateCheckResult {
    pub available: bool,
    pub current_version: String,
    pub latest_version: Option<String>,
    pub release_notes: Option<String>,
    pub error: Option<String>,
}

/// Check for available updates using the Tauri updater plugin.
/// The plugin reads endpoints + pubkey from tauri.conf.json.
pub async fn check_for_updates(
    app: &tauri::AppHandle,
) -> Result<serde_json::Value, UpdaterError> {
    #[cfg(desktop)]
    {
        use tauri_plugin_updater::UpdaterExt;

        let current = env!("CARGO_PKG_VERSION").to_string();

        match app.updater().check().await {
            Ok(Some(update)) => {
                info!(
                    current = %current,
                    latest = %update.version,
                    "update available"
                );
                let result = UpdateCheckResult {
                    available: true,
                    current_version: current,
                    latest_version: Some(update.version.clone()),
                    release_notes: update.body.clone(),
                    error: None,
                };
                serde_json::to_value(&result)
                    .map_err(|e| UpdaterError::Internal(e.to_string()))
            }
            Ok(None) => {
                info!("no update available");
                let result = UpdateCheckResult {
                    available: false,
                    current_version: current,
                    latest_version: None,
                    release_notes: None,
                    error: None,
                };
                serde_json::to_value(&result)
                    .map_err(|e| UpdaterError::Internal(e.to_string()))
            }
            Err(e) => {
                warn!("update check failed: {e}");
                let result = UpdateCheckResult {
                    available: false,
                    current_version: current,
                    latest_version: None,
                    release_notes: None,
                    error: Some(e.to_string()),
                };
                serde_json::to_value(&result)
                    .map_err(|e| UpdaterError::Internal(e.to_string()))
            }
        }
    }

    #[cfg(not(desktop))]
    {
        let _ = app;
        Err(UpdaterError::NotSupported)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum UpdaterError {
    #[error("internal error: {0}")]
    Internal(String),

    #[error("updater not supported on this platform")]
    NotSupported,
}
