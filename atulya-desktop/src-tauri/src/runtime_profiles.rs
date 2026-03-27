use std::collections::BTreeMap;
use std::path::Path;

use serde::{Deserialize, Serialize};

/// Runtime profile acts as the policy layer that governs how Atulya operates
/// locally. A profile is more than a bag of env vars — it captures network
/// policy, model source policy, telemetry policy, and feature gates. Env-var
/// generation is one output of a resolved policy.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProfileId {
    FullyOffline,
    Hybrid,
    Custom,
}

impl Default for ProfileId {
    fn default() -> Self {
        Self::FullyOffline
    }
}

impl std::fmt::Display for ProfileId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::FullyOffline => write!(f, "fully_offline"),
            Self::Hybrid => write!(f, "hybrid"),
            Self::Custom => write!(f, "custom"),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkPolicy {
    pub allow_outbound: bool,
    pub allow_remote_brain_learning: bool,
    pub allow_model_downloads: bool,
    pub allow_telemetry: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelSourcePolicy {
    pub embeddings_provider: String,
    pub reranker_provider: String,
    pub llm_provider: String,
    pub llm_base_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BrainPolicy {
    pub enabled: bool,
    pub import_export_enabled: bool,
    pub startup_warmup: bool,
    pub hardware_tier: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeProfile {
    pub id: ProfileId,
    pub display_name: String,
    pub network: NetworkPolicy,
    pub models: ModelSourcePolicy,
    pub brain: BrainPolicy,
}

impl RuntimeProfile {
    pub fn fully_offline() -> Self {
        Self {
            id: ProfileId::FullyOffline,
            display_name: "Fully Offline".into(),
            network: NetworkPolicy {
                allow_outbound: false,
                allow_remote_brain_learning: false,
                allow_model_downloads: false,
                allow_telemetry: false,
            },
            models: ModelSourcePolicy {
                embeddings_provider: "local".into(),
                reranker_provider: "local".into(),
                llm_provider: "ollama".into(),
                llm_base_url: Some("http://localhost:11434/v1".into()),
            },
            brain: BrainPolicy {
                enabled: true,
                import_export_enabled: true,
                startup_warmup: true,
                hardware_tier: "balanced".into(),
            },
        }
    }

    pub fn hybrid() -> Self {
        Self {
            id: ProfileId::Hybrid,
            display_name: "Hybrid".into(),
            network: NetworkPolicy {
                allow_outbound: true,
                allow_remote_brain_learning: false,
                allow_model_downloads: true,
                allow_telemetry: false,
            },
            models: ModelSourcePolicy {
                embeddings_provider: "local".into(),
                reranker_provider: "local".into(),
                llm_provider: "openai".into(),
                llm_base_url: None,
            },
            brain: BrainPolicy {
                enabled: true,
                import_export_enabled: true,
                startup_warmup: true,
                hardware_tier: "balanced".into(),
            },
        }
    }

    /// Resolve this profile into a flat set of environment variables that
    /// `atulya-api` understands. This is the single point of translation
    /// between the desktop policy model and the API's env-based config.
    pub fn to_env_vars(
        &self,
        data_dir: &Path,
        native_lib_path: Option<&Path>,
    ) -> BTreeMap<String, String> {
        let mut env = BTreeMap::new();

        // Database: always embedded pg0 for desktop
        env.insert("ATULYA_API_DATABASE_URL".into(), "pg0://atulya-desktop".into());
        env.insert("ATULYA_API_RUN_MIGRATIONS_ON_STARTUP".into(), "true".into());

        // Bind to loopback only
        env.insert("ATULYA_API_HOST".into(), "127.0.0.1".into());
        env.insert("ATULYA_API_PORT".into(), "8888".into());
        env.insert("ATULYA_API_LOG_LEVEL".into(), "info".into());

        // LLM
        env.insert(
            "ATULYA_API_LLM_PROVIDER".into(),
            self.models.llm_provider.clone(),
        );
        if let Some(ref base_url) = self.models.llm_base_url {
            env.insert("ATULYA_API_LLM_BASE_URL".into(), base_url.clone());
        }
        env.insert(
            "ATULYA_API_SKIP_LLM_VERIFICATION".into(),
            "true".into(),
        );

        // Embeddings + reranker
        env.insert(
            "ATULYA_API_EMBEDDINGS_PROVIDER".into(),
            self.models.embeddings_provider.clone(),
        );
        env.insert(
            "ATULYA_API_RERANKER_PROVIDER".into(),
            self.models.reranker_provider.clone(),
        );

        // Pin HuggingFace / model caches into app data dir
        let models_cache = data_dir.join("models");
        env.insert("HF_HOME".into(), models_cache.display().to_string());
        env.insert(
            "SENTENCE_TRANSFORMERS_HOME".into(),
            models_cache.display().to_string(),
        );
        env.insert(
            "TRANSFORMERS_CACHE".into(),
            models_cache.display().to_string(),
        );

        // Suppress noisy model loading output
        env.insert("TRANSFORMERS_VERBOSITY".into(), "error".into());
        env.insert("HF_HUB_VERBOSITY".into(), "error".into());
        env.insert("TOKENIZERS_PARALLELISM".into(), "false".into());
        env.insert("PYTHONUNBUFFERED".into(), "1".into());

        // Brain
        env.insert(
            "ATULYA_API_BRAIN_ENABLED".into(),
            self.brain.enabled.to_string(),
        );
        let brain_cache = data_dir.join("brain");
        env.insert(
            "ATULYA_API_BRAIN_CACHE_DIR".into(),
            brain_cache.display().to_string(),
        );
        env.insert(
            "ATULYA_API_BRAIN_IMPORT_EXPORT_ENABLED".into(),
            self.brain.import_export_enabled.to_string(),
        );
        env.insert(
            "ATULYA_API_BRAIN_STARTUP_WARMUP".into(),
            self.brain.startup_warmup.to_string(),
        );
        env.insert(
            "ATULYA_API_BRAIN_HARDWARE_TIER".into(),
            self.brain.hardware_tier.clone(),
        );

        if let Some(lib_path) = native_lib_path {
            env.insert(
                "ATULYA_API_BRAIN_NATIVE_LIBRARY_PATH".into(),
                lib_path.display().to_string(),
            );
        }

        // File storage: native (pg BYTEA) for desktop
        env.insert("ATULYA_API_FILE_STORAGE_TYPE".into(), "native".into());

        // MCP
        env.insert("ATULYA_API_MCP_ENABLED".into(), "true".into());

        // Worker (single-node)
        env.insert("ATULYA_API_WORKER_ENABLED".into(), "true".into());

        env
    }
}

/// Load built-in profiles. In the future, this could load from
/// `runtime-manifests/profiles/` for user-defined custom profiles.
pub fn builtin_profiles() -> Vec<RuntimeProfile> {
    vec![RuntimeProfile::fully_offline(), RuntimeProfile::hybrid()]
}

pub fn resolve_profile(id: &ProfileId) -> RuntimeProfile {
    match id {
        ProfileId::FullyOffline => RuntimeProfile::fully_offline(),
        ProfileId::Hybrid => RuntimeProfile::hybrid(),
        ProfileId::Custom => RuntimeProfile::fully_offline(),
    }
}
