#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::{json, Value};
use std::{
    collections::HashMap,
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
};
use tauri::{Emitter, Manager};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};
use tokio::sync::oneshot;

type Reply = Result<Value, String>;

#[derive(Default)]
struct Bridge {
    child: Mutex<Option<CommandChild>>,
    pending: Mutex<HashMap<String, oneshot::Sender<Reply>>>,
    sequence: AtomicU64,
}

impl Bridge {
    fn write(&self, message: &Value) -> Result<(), String> {
        let mut bytes = serde_json::to_vec(message).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        self.child
            .lock()
            .map_err(|e| e.to_string())?
            .as_mut()
            .ok_or("Desktop service is unavailable")?
            .write(&bytes)
            .map_err(|e| e.to_string())
    }

    fn fail_pending(&self, reason: &str) {
        if let Ok(mut pending) = self.pending.lock() {
            for (_, reply) in pending.drain() {
                let _ = reply.send(Err(reason.to_owned()));
            }
        }
    }
}

#[tauri::command]
fn desktop_platform() -> &'static str {
    match std::env::consts::OS {
        "windows" => "win32",
        "macos" => "darwin",
        platform => platform,
    }
}

#[tauri::command]
async fn desktop_invoke(
    window: tauri::WebviewWindow,
    bridge: tauri::State<'_, Bridge>,
    channel: String,
    payload: Value,
) -> Reply {
    if window.label() != "main" || !channel.starts_with("sdd:") {
        return Err("Desktop command is not allowed".into());
    }
    let id = bridge.sequence.fetch_add(1, Ordering::Relaxed).to_string();
    let (reply, receiver) = oneshot::channel();
    bridge
        .pending
        .lock()
        .map_err(|e| e.to_string())?
        .insert(id.clone(), reply);
    if let Err(error) = bridge.write(&json!({ "id": id, "channel": channel, "payload": payload })) {
        bridge
            .pending
            .lock()
            .map_err(|e| e.to_string())?
            .remove(&id);
        return Err(error);
    }
    // OAuth can wait five minutes and Git can wait five minutes.
    match tokio::time::timeout(std::time::Duration::from_secs(360), receiver).await {
        Ok(result) => result.map_err(|_| "Desktop service closed".to_owned())?,
        Err(_) => {
            bridge
                .pending
                .lock()
                .map_err(|e| e.to_string())?
                .remove(&id);
            Err("Desktop command timed out".into())
        }
    }
}

fn native_request(app: &tauri::AppHandle, method: &str, payload: &Value) -> Reply {
    match method {
        "attention" => {
            let window = app
                .get_webview_window("main")
                .ok_or("Main window is unavailable")?;
            set_attention(&window, payload)?;
            Ok(json!({ "ok": true }))
        }
        "select-directory" => {
            let path = app
                .dialog()
                .file()
                .set_title("Select local repository")
                .blocking_pick_folder();
            let path = path.map(|p| p.to_string());
            Ok(
                json!({ "canceled": path.is_none(), "filePaths": path.into_iter().collect::<Vec<_>>() }),
            )
        }
        "save-file" => {
            let mut dialog = app.dialog().file().set_title("保存文件");
            if let Some(path) = payload["defaultPath"].as_str() {
                let path = std::path::Path::new(path);
                if let Some(parent) = path.parent() {
                    dialog = dialog.set_directory(parent);
                }
                if let Some(name) = path.file_name() {
                    dialog = dialog.set_file_name(name.to_string_lossy());
                }
            }
            if let Some(filters) = payload["filters"].as_array() {
                for filter in filters {
                    if let (Some(name), Some(extensions)) =
                        (filter["name"].as_str(), filter["extensions"].as_array())
                    {
                        let extensions: Vec<&str> = extensions
                            .iter()
                            .filter_map(Value::as_str)
                            .filter(|e| *e != "*")
                            .collect();
                        if !extensions.is_empty() {
                            dialog = dialog.add_filter(name, &extensions);
                        }
                    }
                }
            }
            let path = dialog.blocking_save_file().map(|p| p.to_string());
            Ok(json!({ "canceled": path.is_none(), "filePath": path }))
        }
        "open-external" => {
            let url = payload["url"].as_str().ok_or("URL is required")?;
            if !url.starts_with("http://") && !url.starts_with("https://") {
                return Err("Only http(s) URLs can be opened externally".into());
            }
            app.opener()
                .open_url(url, None::<&str>)
                .map_err(|e| e.to_string())?;
            Ok(Value::Null)
        }
        "open-path" => {
            let path = payload["path"].as_str().ok_or("Path is required")?;
            app.opener()
                .open_path(path, None::<&str>)
                .map_err(|e| e.to_string())?;
            Ok(Value::Null)
        }
        _ => Err("Unknown native operation".into()),
    }
}

fn start_bridge(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let state_root = app.path().app_config_dir()?;
    std::fs::create_dir_all(&state_root)?;
    let downloads = app.path().download_dir()?;
    let (mut events, child) = app
        .shell()
        .sidecar("traceforge-desktop-host")?
        .args([
            state_root.to_string_lossy().to_string(),
            downloads.to_string_lossy().to_string(),
        ])
        .spawn()?;
    *app.state::<Bridge>().child.lock().unwrap() = Some(child);
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let message: Value = match serde_json::from_slice(&bytes) {
                        Ok(message) => message,
                        Err(_) => {
                            app.state::<Bridge>()
                                .fail_pending("Invalid desktop service response");
                            continue;
                        }
                    };
                    let id = message["id"].as_str().unwrap_or_default().to_owned();
                    match message["kind"].as_str() {
                        Some("result") => {
                            if let Some(reply) =
                                app.state::<Bridge>().pending.lock().unwrap().remove(&id)
                            {
                                let result = message["error"].as_str().map_or_else(
                                    || Ok(message["result"].clone()),
                                    |error| Err(error.to_owned()),
                                );
                                let _ = reply.send(result);
                            }
                        }
                        Some("event") => {
                            let _ = app.emit_to("main", "desktop-event", json!({ "channel": message["channel"], "payload": message["payload"] }));
                        }
                        Some("native") => {
                            let app = app.clone();
                            tauri::async_runtime::spawn_blocking(move || {
                                let result = native_request(
                                    &app,
                                    message["method"].as_str().unwrap_or_default(),
                                    &message["payload"],
                                );
                                let response = match result {
                                    Ok(result) => {
                                        json!({ "kind": "native-result", "id": id, "result": result })
                                    }
                                    Err(error) => {
                                        json!({ "kind": "native-result", "id": id, "error": error })
                                    }
                                };
                                if let Err(error) = app.state::<Bridge>().write(&response) {
                                    app.state::<Bridge>().fail_pending(&error);
                                }
                            });
                        }
                        _ => app
                            .state::<Bridge>()
                            .fail_pending("Unknown desktop service response"),
                    }
                }
                CommandEvent::Stderr(bytes) => eprintln!("{}", String::from_utf8_lossy(&bytes)),
                CommandEvent::Error(error) => app.state::<Bridge>().fail_pending(&error),
                CommandEvent::Terminated(_) => {
                    app.state::<Bridge>().child.lock().unwrap().take();
                    app.state::<Bridge>().fail_pending("Desktop service exited");
                    break;
                }
                _ => {}
            }
        }
        app.state::<Bridge>().fail_pending("Desktop service closed");
    });
    Ok(())
}

fn set_attention(window: &tauri::WebviewWindow, payload: &Value) -> Result<(), String> {
    let background = !window.is_focused().map_err(|e| e.to_string())?
        || window.is_minimized().map_err(|e| e.to_string())?;
    let flash = background && payload["flash"].as_bool().unwrap_or(false);
    window
        .request_user_attention(if flash {
            Some(tauri::UserAttentionType::Critical)
        } else {
            None
        })
        .map_err(|e| e.to_string())?;
    let count = if background {
        payload["hitlCount"].as_i64().unwrap_or(0).clamp(0, 99)
    } else {
        0
    };
    #[cfg(target_os = "windows")]
    window
        .set_overlay_icon(if count > 0 {
            Some(attention_dot())
        } else {
            None
        })
        .map_err(|e| e.to_string())?;
    #[cfg(target_os = "macos")]
    window
        .set_badge_label(if count > 0 {
            Some("●".to_owned())
        } else {
            None
        })
        .map_err(|e| e.to_string())?;
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    let _ = count;
    Ok(())
}

#[cfg(target_os = "windows")]
fn attention_dot() -> tauri::image::Image<'static> {
    let mut rgba = Vec::with_capacity(16 * 16 * 4);
    for y in 0..16_i32 {
        for x in 0..16_i32 {
            let distance = (2 * x - 15).pow(2) + (2 * y - 15).pow(2);
            rgba.extend_from_slice(if distance <= 121 {
                &[245, 158, 11, 255]
            } else if distance <= 185 {
                &[255, 255, 255, 255]
            } else {
                &[0, 0, 0, 0]
            });
        }
    }
    tauri::image::Image::new_owned(rgba, 16, 16)
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_http::init())
        .manage(Bridge::default())
        .invoke_handler(tauri::generate_handler![desktop_platform, desktop_invoke])
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Focused(true)) {
                let _ = window.request_user_attention(None);
                #[cfg(target_os = "windows")]
                let _ = window.set_overlay_icon(None);
                #[cfg(target_os = "macos")]
                let _ = window.set_badge_label(None);
            }
        })
        .setup(|app| {
            start_bridge(app.handle())?;
            let opener = app.handle().clone();
            tauri::WebviewWindowBuilder::from_config(app.handle(), &app.config().app.windows[0])?
                .on_new_window(move |url, _| {
                    if matches!(url.scheme(), "http" | "https") {
                        let _ = opener.opener().open_url(url.as_str(), None::<&str>);
                    }
                    tauri::webview::NewWindowResponse::Deny
                })
                .on_navigation(|url| {
                    url.scheme() == "tauri"
                        || url.host_str() == Some("tauri.localhost")
                        || (cfg!(debug_assertions)
                            && url.host_str() == Some("127.0.0.1")
                            && url.port() == Some(5173))
                })
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Failed to build TraceForge desktop")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                // Let the host release owned workers before the final kill fallback.
                let _ = app.state::<Bridge>().write(&json!({ "kind": "shutdown" }));
                std::thread::sleep(std::time::Duration::from_millis(200));
                if let Some(child) = app.state::<Bridge>().child.lock().unwrap().take() {
                    let _ = child.kill();
                }
                app.state::<Bridge>().fail_pending("Application closed");
            }
        });
}
