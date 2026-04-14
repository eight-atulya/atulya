use anyhow::{Context, Result};
use chrono::Utc;
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use crate::api::{
    ApiClient, BrainLearnRequest, BrainRuntimeStatusResponse, SubRoutineHistogramResponse, SubRoutinePredictionResponse,
};
use crate::output::{self, OutputFormat};
use crate::ui;

#[derive(Debug, Serialize)]
struct BrainExportResult {
    bank_id: String,
    output_path: String,
    bytes_written: usize,
}

#[derive(Debug, Serialize)]
struct BrainOperationResult {
    bank_id: String,
    operation_id: String,
    deduplicated: bool,
    completed: bool,
}

#[derive(Debug, Serialize)]
struct CommandCapture {
    command: String,
    status_code: Option<i32>,
    success: bool,
    stdout: String,
    stderr: String,
    spawn_error: Option<String>,
}

#[derive(Debug, Serialize)]
struct CapabilitySnapshot {
    generated_at_utc: String,
    host: String,
    os: String,
    arch: String,
    logical_cpus: usize,
    commands: Vec<CommandCapture>,
}

pub fn status(client: &ApiClient, bank_id: &str, verbose: bool, output_format: OutputFormat) -> Result<()> {
    let spinner = if output_format == OutputFormat::Pretty {
        Some(ui::create_spinner("Fetching brain status..."))
    } else {
        None
    };

    let response = client.get_brain_status(bank_id, verbose);

    if let Some(mut sp) = spinner {
        sp.finish();
    }

    match response {
        Ok(result) => print_status(&result, output_format),
        Err(e) => Err(e),
    }
}

pub fn subroutine_trigger(
    client: &ApiClient,
    bank_id: &str,
    mode: &str,
    horizon_hours: i32,
    force_rebuild: bool,
    wait: bool,
    poll_interval: u64,
    verbose: bool,
    output_format: OutputFormat,
) -> Result<()> {
    let spinner = if output_format == OutputFormat::Pretty {
        Some(ui::create_spinner("Triggering sub-routine..."))
    } else {
        None
    };

    let response = client.trigger_sub_routine(bank_id, mode, horizon_hours as i64, force_rebuild, verbose);

    if let Some(mut sp) = spinner {
        sp.finish();
    }

    let result = response?;
    let mut payload = BrainOperationResult {
        bank_id: bank_id.to_string(),
        operation_id: result.operation_id.clone(),
        deduplicated: result.deduplicated,
        completed: false,
    };

    if wait {
        wait_for_operation(client, bank_id, &result.operation_id, poll_interval, verbose)?;
        payload.completed = true;
    }

    if output_format == OutputFormat::Pretty {
        ui::print_success("Sub-routine queued");
        println!("  {} {}", ui::dim("Operation ID:"), payload.operation_id);
        println!("  {} {}", ui::dim("Deduplicated:"), payload.deduplicated);
        if wait {
            println!("  {} true", ui::dim("Completed:"));
        } else {
            println!("  {} Use --wait to block until completion", ui::dim("Tip:"));
        }
    } else {
        output::print_output(&payload, output_format)?;
    }
    Ok(())
}

pub fn subroutine_predictions(
    client: &ApiClient,
    bank_id: &str,
    horizon_hours: i32,
    verbose: bool,
    output_format: OutputFormat,
) -> Result<()> {
    let response = client.get_sub_routine_predictions(bank_id, horizon_hours as i64, verbose)?;
    print_predictions(&response, output_format)
}

pub fn subroutine_histogram(client: &ApiClient, bank_id: &str, verbose: bool, output_format: OutputFormat) -> Result<()> {
    let response = client.get_sub_routine_histogram(bank_id, verbose)?;
    print_histogram(&response, output_format)
}

pub fn export(
    client: &ApiClient,
    bank_id: &str,
    out: Option<PathBuf>,
    verbose: bool,
    output_format: OutputFormat,
) -> Result<()> {
    let spinner = if output_format == OutputFormat::Pretty {
        Some(ui::create_spinner("Exporting brain snapshot..."))
    } else {
        None
    };

    let bytes = client.export_brain_snapshot(bank_id, verbose)?;
    let out_path = out.unwrap_or_else(|| PathBuf::from(format!("{}.brain", bank_id)));
    if let Some(parent) = out_path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("Failed to create parent directory for {}", out_path.display()))?;
        }
    }
    std::fs::write(&out_path, &bytes).with_context(|| format!("Failed to write {}", out_path.display()))?;

    if let Some(mut sp) = spinner {
        sp.finish();
    }

    let payload = BrainExportResult {
        bank_id: bank_id.to_string(),
        output_path: out_path.display().to_string(),
        bytes_written: bytes.len(),
    };

    if output_format == OutputFormat::Pretty {
        ui::print_success("Brain snapshot exported");
        println!("  {} {}", ui::dim("Path:"), payload.output_path);
        println!("  {} {}", ui::dim("Bytes:"), payload.bytes_written);
    } else {
        output::print_output(&payload, output_format)?;
    }
    Ok(())
}

pub fn import_validate(
    client: &ApiClient,
    bank_id: &str,
    file: &Path,
    verbose: bool,
    output_format: OutputFormat,
) -> Result<()> {
    if !file.exists() {
        anyhow::bail!("Brain file not found: {}", file.display());
    }
    let response = client.validate_brain_import(bank_id, file, verbose)?;
    if output_format == OutputFormat::Pretty {
        if response.valid {
            ui::print_success("Brain import payload is valid");
        } else {
            ui::print_warning("Brain import payload is not valid");
        }
        println!("  {} {}", ui::dim("Version:"), response.version.map(|v| v.to_string()).unwrap_or_else(|| "-".to_string()));
        if let Some(reason) = response.reason {
            println!("  {} {}", ui::dim("Reason:"), reason);
        }
    } else {
        output::print_output(&response, output_format)?;
    }
    Ok(())
}

pub fn import(
    client: &ApiClient,
    bank_id: &str,
    file: &Path,
    verbose: bool,
    output_format: OutputFormat,
) -> Result<()> {
    if !file.exists() {
        anyhow::bail!("Brain file not found: {}", file.display());
    }
    let response = client.import_brain_snapshot(bank_id, file, verbose)?;
    if output_format == OutputFormat::Pretty {
        ui::print_success("Brain snapshot imported");
        println!("  {} {}", ui::dim("File path:"), response.file_path);
        println!("  {} {}", ui::dim("Bytes:"), response.size_bytes);
        if let Some(version) = response.format_version {
            println!("  {} {}", ui::dim("Format version:"), version);
        }
    } else {
        output::print_output(&response, output_format)?;
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub fn learn(
    client: &ApiClient,
    bank_id: &str,
    remote_endpoint: &str,
    remote_bank_id: &str,
    remote_api_key: &str,
    learning_type: &str,
    mode: &str,
    horizon_hours: i32,
    wait: bool,
    poll_interval: u64,
    verbose: bool,
    output_format: OutputFormat,
) -> Result<()> {
    let req = BrainLearnRequest {
        remote_endpoint: remote_endpoint.to_string(),
        remote_bank_id: remote_bank_id.to_string(),
        remote_api_key: remote_api_key.to_string(),
        learning_type: learning_type.to_string(),
        mode: mode.to_string(),
        horizon_hours: horizon_hours as i64,
    };

    let response = client.brain_learn(bank_id, &req, verbose)?;
    let mut payload = BrainOperationResult {
        bank_id: bank_id.to_string(),
        operation_id: response.operation_id.clone(),
        deduplicated: response.deduplicated,
        completed: false,
    };

    if wait {
        wait_for_operation(client, bank_id, &response.operation_id, poll_interval, verbose)?;
        payload.completed = true;
    }

    if output_format == OutputFormat::Pretty {
        ui::print_success("Brain learn queued");
        println!("  {} {}", ui::dim("Operation ID:"), payload.operation_id);
        println!("  {} {}", ui::dim("Deduplicated:"), payload.deduplicated);
        if wait {
            println!("  {} true", ui::dim("Completed:"));
        } else {
            println!("  {} Use --wait to block until completion", ui::dim("Tip:"));
        }
    } else {
        output::print_output(&payload, output_format)?;
    }
    Ok(())
}

pub fn capabilities_scan(out: Option<PathBuf>, output_format: OutputFormat) -> Result<()> {
    let host = hostname();
    let timestamp = Utc::now();
    let logical_cpus = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(0);
    let default_path = PathBuf::from("atulya-cortex")
        .join("capabilities")
        .join(format!("{}-{}.json", sanitize_filename(&host), timestamp.format("%Y%m%dT%H%M%SZ")));
    let output_path = out.unwrap_or(default_path);

    let mut commands = vec![
        run_cmd("uname", &["-a"]),
        run_cmd("hostname", &[]),
        run_cmd("ifconfig", &["-a"]),
        run_cmd("netstat", &["-rn"]),
        run_cmd("scutil", &["--dns"]),
        run_cmd("ip", &["addr", "show"]),
        run_cmd("ip", &["route", "show"]),
        run_cmd("resolvectl", &["status"]),
        run_cmd("route", &["-n", "get", "default"]),
        run_cmd("sysctl", &["-a"]),
        run_cmd("system_profiler", &["SPHardwareDataType", "SPDisplaysDataType"]),
        run_cmd("lscpu", &[]),
        run_cmd("nvidia-smi", &["-q"]),
        run_cmd("df", &["-h"]),
        run_cmd("mount", &[]),
        run_cmd("ping", &["-c", "3", "8.8.8.8"]),
        run_cmd("curl", &["-I", "https://eightengine.com"]),
    ];

    // Keep deterministic ordering for git diffs.
    commands.sort_by(|a, b| a.command.cmp(&b.command));

    let snapshot = CapabilitySnapshot {
        generated_at_utc: timestamp.to_rfc3339(),
        host,
        os: std::env::consts::OS.to_string(),
        arch: std::env::consts::ARCH.to_string(),
        logical_cpus,
        commands,
    };

    if let Some(parent) = output_path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("Failed creating {}", parent.display()))?;
        }
    }
    let json = serde_json::to_string_pretty(&snapshot)?;
    std::fs::write(&output_path, json).with_context(|| format!("Failed writing {}", output_path.display()))?;

    if output_format == OutputFormat::Pretty {
        ui::print_success("Capability scan complete");
        println!("  {} {}", ui::dim("Output:"), output_path.display());
        println!("  {} {} (full raw mode)", ui::dim("Network detail:"), "enabled");
    } else {
        let payload = serde_json::json!({
            "output_path": output_path.display().to_string(),
            "generated_at_utc": snapshot.generated_at_utc,
            "host": snapshot.host,
            "logical_cpus": snapshot.logical_cpus,
            "commands_collected": snapshot.commands.len()
        });
        output::print_output(&payload, output_format)?;
    }
    Ok(())
}

fn print_status(result: &BrainRuntimeStatusResponse, output_format: OutputFormat) -> Result<()> {
    if output_format == OutputFormat::Pretty {
        ui::print_section_header(&format!("Brain Status: {}", result.bank_id));
        println!("  {} {}", ui::dim("Enabled:"), result.enabled);
        println!("  {} {}", ui::dim("Exists:"), result.exists);
        println!("  {} {}", ui::dim("Circuit open:"), result.circuit_open);
        println!("  {} {}", ui::dim("Failure count:"), result.failure_count);
        println!("  {} {}", ui::dim("File:"), result.file_path);
        println!("  {} {}", ui::dim("Bytes:"), result.size_bytes);
        if let Some(v) = result.format_version {
            println!("  {} {}", ui::dim("Format version:"), v);
        }
        if let Some(sig) = &result.model_signature {
            println!("  {} {}", ui::dim("Model signature:"), sig);
        }
    } else {
        output::print_output(result, output_format)?;
    }
    Ok(())
}

fn print_predictions(result: &SubRoutinePredictionResponse, output_format: OutputFormat) -> Result<()> {
    if output_format == OutputFormat::Pretty {
        ui::print_section_header(&format!("Sub-Routine Predictions: {}", result.bank_id));
        println!("  {} {}", ui::dim("Horizon hours:"), result.horizon_hours);
        println!("  {} {}", ui::dim("Sample count:"), result.sample_count);
        for p in &result.predictions {
            println!("  hour {:02}  score {:.4}", p.hour_utc, p.score);
        }
    } else {
        output::print_output(result, output_format)?;
    }
    Ok(())
}

fn print_histogram(result: &SubRoutineHistogramResponse, output_format: OutputFormat) -> Result<()> {
    if output_format == OutputFormat::Pretty {
        ui::print_section_header(&format!("Sub-Routine Histogram: {}", result.bank_id));
        println!("  {} {}", ui::dim("Sample count:"), result.sample_count);
        for p in &result.histogram {
            println!("  hour {:02}  score {:.4}", p.hour_utc, p.score);
        }
    } else {
        output::print_output(result, output_format)?;
    }
    Ok(())
}

fn wait_for_operation(
    client: &ApiClient,
    bank_id: &str,
    operation_id: &str,
    poll_interval: u64,
    verbose: bool,
) -> Result<()> {
    if verbose {
        eprintln!("Waiting for operation {}...", operation_id);
    }
    loop {
        let op = client.get_operation(bank_id, operation_id, verbose)?;
        match op.status.to_string().as_str() {
            "completed" => return Ok(()),
            "failed" => {
                let err = op.error_message.unwrap_or_else(|| "operation failed".to_string());
                anyhow::bail!("Operation {} failed: {}", operation_id, err);
            }
            "not_found" => {
                anyhow::bail!("Operation {} not found", operation_id);
            }
            "pending" => {
                std::thread::sleep(Duration::from_secs(poll_interval.max(1)));
            }
            other => {
                anyhow::bail!("Operation {} returned unexpected status: {}", operation_id, other);
            }
        }
    }
}

fn run_cmd(bin: &str, args: &[&str]) -> CommandCapture {
    let cmdline = format!("{} {}", bin, args.join(" "));
    match Command::new(bin).args(args).output() {
        Ok(output) => CommandCapture {
            command: cmdline,
            status_code: output.status.code(),
            success: output.status.success(),
            stdout: String::from_utf8_lossy(&output.stdout).to_string(),
            stderr: String::from_utf8_lossy(&output.stderr).to_string(),
            spawn_error: None,
        },
        Err(e) => CommandCapture {
            command: cmdline,
            status_code: None,
            success: false,
            stdout: String::new(),
            stderr: String::new(),
            spawn_error: Some(e.to_string()),
        },
    }
}

fn hostname() -> String {
    if let Ok(output) = Command::new("hostname").output() {
        let raw = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !raw.is_empty() {
            return raw;
        }
    }
    "unknown-host".to_string()
}

fn sanitize_filename(input: &str) -> String {
    input
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' })
        .collect()
}
