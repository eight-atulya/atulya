mod diagnostics;
mod install_state;
mod process_supervisor;
mod runtime_manager;
mod runtime_profiles;
mod settings_store;
mod updater;

use std::sync::Arc;

use tauri::Manager;
use tokio::sync::RwLock;
use tracing::info;

use diagnostics::DiagnosticsManager;
use install_state::InstallState;
use runtime_manager::RuntimeManager;
use settings_store::SettingsStore;

pub struct AppState {
    pub settings: Arc<RwLock<SettingsStore>>,
    pub runtime: Arc<RuntimeManager>,
    pub install: Arc<RwLock<InstallState>>,
    pub diagnostics: Arc<DiagnosticsManager>,
}

#[tauri::command]
async fn get_runtime_status(
    state: tauri::State<'_, Arc<AppState>>,
) -> Result<serde_json::Value, String> {
    let status = state.runtime.status().await;
    serde_json::to_value(&status).map_err(|e| e.to_string())
}

#[tauri::command]
async fn start_runtime(
    state: tauri::State<'_, Arc<AppState>>,
) -> Result<serde_json::Value, String> {
    state.runtime.start().await.map_err(|e| e.to_string())?;
    let status = state.runtime.status().await;
    serde_json::to_value(&status).map_err(|e| e.to_string())
}

#[tauri::command]
async fn stop_runtime(
    state: tauri::State<'_, Arc<AppState>>,
) -> Result<serde_json::Value, String> {
    state.runtime.stop().await.map_err(|e| e.to_string())?;
    let status = state.runtime.status().await;
    serde_json::to_value(&status).map_err(|e| e.to_string())
}

#[tauri::command]
async fn get_settings(
    state: tauri::State<'_, Arc<AppState>>,
) -> Result<serde_json::Value, String> {
    let store = state.settings.read().await;
    serde_json::to_value(store.settings()).map_err(|e| e.to_string())
}

#[tauri::command]
async fn update_settings(
    state: tauri::State<'_, Arc<AppState>>,
    patch: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let mut store = state.settings.write().await;
    store.apply_patch(patch).map_err(|e| e.to_string())?;
    serde_json::to_value(store.settings()).map_err(|e| e.to_string())
}

#[tauri::command]
async fn get_install_state(
    state: tauri::State<'_, Arc<AppState>>,
) -> Result<serde_json::Value, String> {
    let install = state.install.read().await;
    serde_json::to_value(install.summary()).map_err(|e| e.to_string())
}

#[tauri::command]
async fn export_support_bundle(
    state: tauri::State<'_, Arc<AppState>>,
    output_path: String,
) -> Result<String, String> {
    state
        .diagnostics
        .export_support_bundle(&output_path)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn check_for_updates(
    app: tauri::AppHandle,
) -> Result<serde_json::Value, String> {
    updater::check_for_updates(&app).await.map_err(|e| e.to_string())
}

pub fn run() {
    let _guard = diagnostics::init_tracing();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .setup(|app| {
            #[cfg(desktop)]
            app.handle()
                .plugin(tauri_plugin_updater::Builder::new().build())?;

            let app_handle = app.handle().clone();
            let data_dir = app_handle
                .path()
                .app_data_dir()
                .expect("failed to resolve app data dir");

            std::fs::create_dir_all(&data_dir)
                .expect("failed to create app data dir");

            let settings = Arc::new(RwLock::new(
                SettingsStore::load_or_default(&data_dir),
            ));
            let install = Arc::new(RwLock::new(
                InstallState::load_or_init(&data_dir),
            ));
            let diag = Arc::new(DiagnosticsManager::new(data_dir.clone()));

            let runtime = {
                let settings_snapshot = {
                    let guard = settings.blocking_read();
                    guard.settings().clone()
                };
                Arc::new(RuntimeManager::new(
                    data_dir.clone(),
                    settings_snapshot,
                ))
            };

            let state = Arc::new(AppState {
                settings,
                runtime: runtime.clone(),
                install,
                diagnostics: diag,
            });

            app.manage(state.clone());

            let rt = runtime.clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = rt.start().await {
                    tracing::error!("failed to auto-start runtime: {e}");
                }
            });

            info!("atulya-desktop setup complete");
            Ok(())
        })
        .on_event(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let state = app.state::<Arc<AppState>>();
                let rt = state.runtime.clone();
                tauri::async_runtime::block_on(async {
                    if let Err(e) = rt.stop().await {
                        tracing::error!("runtime stop on exit failed: {e}");
                    }
                });
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_runtime_status,
            start_runtime,
            stop_runtime,
            get_settings,
            update_settings,
            get_install_state,
            export_support_bundle,
            check_for_updates,
        ])
        .run(tauri::generate_context!())
        .expect("error while running atulya-desktop");
}
