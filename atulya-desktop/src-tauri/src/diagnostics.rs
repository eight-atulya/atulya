use std::path::{Path, PathBuf};

use chrono::Utc;
use serde::Serialize;
use tracing::info;
use tracing_appender::non_blocking::WorkerGuard;
use tracing_subscriber::EnvFilter;

const LOG_DIR: &str = "logs";
const LOG_FILE_PREFIX: &str = "atulya-desktop";
const MAX_LOG_FILES: usize = 10;

/// Initialise structured tracing with both stdout and rolling file output.
/// Returns a guard that must be held for the lifetime of the application
/// to ensure buffered log lines are flushed.
pub fn init_tracing() -> WorkerGuard {
    let data_dir = directories::ProjectDirs::from("com", "atulya", "Atulya Desktop")
        .map(|d| d.data_dir().to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."));

    let log_dir = data_dir.join(LOG_DIR);
    let _ = std::fs::create_dir_all(&log_dir);

    let file_appender =
        tracing_appender::rolling::daily(&log_dir, LOG_FILE_PREFIX);
    let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);

    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info,atulya_desktop=debug"));

    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_writer(non_blocking)
        .with_ansi(false)
        .with_target(true)
        .with_thread_ids(true)
        .json()
        .init();

    guard
}

pub struct DiagnosticsManager {
    data_dir: PathBuf,
}

#[derive(Debug, Serialize)]
struct SupportBundleManifest {
    generated_at: String,
    app_version: String,
    os: String,
    arch: String,
    files: Vec<String>,
}

impl DiagnosticsManager {
    pub fn new(data_dir: PathBuf) -> Self {
        Self { data_dir }
    }

    /// Collect all diagnostic data into a zip-like support bundle.
    /// Returns the path to the generated archive.
    pub async fn export_support_bundle(
        &self,
        output_path: &str,
    ) -> Result<String, DiagnosticsError> {
        let output = PathBuf::from(output_path);
        if let Some(parent) = output.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| DiagnosticsError::Io(e.to_string()))?;
        }

        let bundle_dir = self.data_dir.join("support-bundle-tmp");
        let _ = std::fs::remove_dir_all(&bundle_dir);
        std::fs::create_dir_all(&bundle_dir)
            .map_err(|e| DiagnosticsError::Io(e.to_string()))?;

        let mut files_collected = Vec::new();

        // Collect log files
        let log_dir = self.data_dir.join(LOG_DIR);
        if log_dir.exists() {
            let target_log_dir = bundle_dir.join("logs");
            std::fs::create_dir_all(&target_log_dir)
                .map_err(|e| DiagnosticsError::Io(e.to_string()))?;

            let mut log_files = Self::list_files(&log_dir)?;
            log_files.sort();
            log_files.reverse();
            for (i, src) in log_files.iter().enumerate() {
                if i >= MAX_LOG_FILES {
                    break;
                }
                if let Some(name) = src.file_name() {
                    let dest = target_log_dir.join(name);
                    let _ = std::fs::copy(src, &dest);
                    files_collected.push(format!("logs/{}", name.to_string_lossy()));
                }
            }
        }

        // Collect settings (redact secrets)
        let settings_path = self.data_dir.join("settings.json");
        if settings_path.exists() {
            let dest = bundle_dir.join("settings.json");
            if let Ok(contents) = std::fs::read_to_string(&settings_path) {
                let redacted = Self::redact_secrets(&contents);
                let _ = std::fs::write(&dest, redacted);
                files_collected.push("settings.json".into());
            }
        }

        // Collect install state
        let install_path = self.data_dir.join("install-state.json");
        if install_path.exists() {
            let dest = bundle_dir.join("install-state.json");
            let _ = std::fs::copy(&install_path, &dest);
            files_collected.push("install-state.json".into());
        }

        // Collect system info
        let sys_info = Self::collect_system_info();
        let sys_info_path = bundle_dir.join("system-info.json");
        let _ = std::fs::write(
            &sys_info_path,
            serde_json::to_string_pretty(&sys_info).unwrap_or_default(),
        );
        files_collected.push("system-info.json".into());

        // Write manifest
        let manifest = SupportBundleManifest {
            generated_at: Utc::now().to_rfc3339(),
            app_version: env!("CARGO_PKG_VERSION").into(),
            os: std::env::consts::OS.into(),
            arch: std::env::consts::ARCH.into(),
            files: files_collected,
        };
        let manifest_path = bundle_dir.join("manifest.json");
        let _ = std::fs::write(
            &manifest_path,
            serde_json::to_string_pretty(&manifest).unwrap_or_default(),
        );

        // For now, just copy the directory as the output (tar/zip can be added later)
        let final_path = output.display().to_string();
        if output.exists() {
            let _ = std::fs::remove_dir_all(&output);
        }
        std::fs::rename(&bundle_dir, &output)
            .map_err(|e| DiagnosticsError::Io(e.to_string()))?;

        info!(path = %final_path, "support bundle exported");
        Ok(final_path)
    }

    fn list_files(dir: &Path) -> Result<Vec<PathBuf>, DiagnosticsError> {
        let mut result = Vec::new();
        let entries = std::fs::read_dir(dir)
            .map_err(|e| DiagnosticsError::Io(e.to_string()))?;
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_file() {
                result.push(path);
            }
        }
        Ok(result)
    }

    fn redact_secrets(json_str: &str) -> String {
        if let Ok(mut val) = serde_json::from_str::<serde_json::Value>(json_str) {
            if let Some(obj) = val.as_object_mut() {
                for key in ["llm_api_key", "api_key", "secret", "password", "token"] {
                    if obj.contains_key(key) {
                        obj.insert(key.to_string(), serde_json::Value::String("***REDACTED***".into()));
                    }
                }
            }
            serde_json::to_string_pretty(&val).unwrap_or_else(|_| json_str.to_string())
        } else {
            json_str.to_string()
        }
    }

    fn collect_system_info() -> serde_json::Value {
        let sys = sysinfo::System::new_all();
        serde_json::json!({
            "os": std::env::consts::OS,
            "arch": std::env::consts::ARCH,
            "family": std::env::consts::FAMILY,
            "total_memory_mb": sys.total_memory() / 1024 / 1024,
            "available_memory_mb": sys.available_memory() / 1024 / 1024,
            "cpu_count": sys.cpus().len(),
            "app_version": env!("CARGO_PKG_VERSION"),
        })
    }
}

#[derive(Debug, thiserror::Error)]
pub enum DiagnosticsError {
    #[error("io error: {0}")]
    Io(String),
}
