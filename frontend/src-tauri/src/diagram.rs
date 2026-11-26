use serde_json::{json, Value};
use std::{path::PathBuf, sync::Mutex};
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{GlobalShortcut, Shortcut, ShortcutState};

pub const WINDOW: &str = "diagram";
const DEFAULT_SHORTCUT: &str = "Ctrl+Alt+D";
const MODIFIERS: [&str; 4] = ["Ctrl", "Alt", "Shift", "Super"];

#[derive(Default)]
pub struct Diagram {
    shortcut: Mutex<(String, bool)>,
    opening: tokio::sync::Mutex<()>,
}

fn normalize(input: &str) -> Option<String> {
    if input.len() > 35 {
        return None;
    }
    let mut parts: Vec<&str> = input.split('+').collect();
    let key = parts.pop()?;
    let valid_key = (key.len() == 1
        && key
            .bytes()
            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit()))
        || [
            "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
        ]
        .contains(&key);
    if !valid_key
        || !parts
            .iter()
            .any(|part| matches!(*part, "Ctrl" | "Alt" | "Super"))
    {
        return None;
    }
    let mut ordered: Vec<&str> = MODIFIERS
        .into_iter()
        .filter(|part| parts.contains(part))
        .collect();
    if ordered.len() != parts.len() {
        return None;
    }
    ordered.push(key);
    Some(ordered.join("+"))
}

fn path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|path| path.join("diagram-shortcut"))
        .map_err(|error| error.to_string())
}

async fn open(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<Diagram>();
    let _opening = state.opening.lock().await;
    if let Some(window) = app.get_webview_window(WINDOW) {
        window.unminimize().map_err(|error| error.to_string())?;
        window.show().map_err(|error| error.to_string())?;
        return window.set_focus().map_err(|error| error.to_string());
    }
    let builder = WebviewWindowBuilder::new(app, WINDOW, WebviewUrl::App("diagram.html".into()))
        .title("TraceForge · 绘图板")
        .inner_size(1280.0, 820.0)
        .min_inner_size(720.0, 500.0)
        .center()
        .on_navigation(|url| {
            super::task_floats::local_navigation(url) && url.path().ends_with("/diagram.html")
        })
        .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny);
    #[cfg(windows)]
    let builder = builder.decorations(false);
    builder
        .build()
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn register(app: &AppHandle, accelerator: &str) -> Result<(), String> {
    let shortcut = accelerator
        .parse::<Shortcut>()
        .map_err(|_| "DIAGRAM_INVALID_SHORTCUT".to_owned())?;
    app.try_state::<GlobalShortcut<tauri::Wry>>()
        .ok_or_else(|| "DIAGRAM_SHORTCUT_UNAVAILABLE".to_owned())?
        .on_shortcut(shortcut, |app, _, event| {
            if event.state == ShortcutState::Pressed {
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(error) = open(&app).await {
                        eprintln!("Could not open diagram window: {error}");
                    }
                });
            }
        })
        .map_err(|_| "DIAGRAM_SHORTCUT_CONFLICT".to_owned())
}

fn unregister(app: &AppHandle, accelerator: &str) {
    if let (Some(shortcuts), Ok(shortcut)) = (
        app.try_state::<GlobalShortcut<tauri::Wry>>(),
        accelerator.parse::<Shortcut>(),
    ) {
        let _ = shortcuts.unregister(shortcut);
    }
}

pub fn initialize(app: &AppHandle) {
    if let Err(error) = app.plugin(tauri_plugin_global_shortcut::Builder::new().build()) {
        eprintln!("Could not initialize global shortcuts: {error}");
    }
    let accelerator = path(app)
        .ok()
        .and_then(|path| std::fs::read_to_string(path).ok())
        .and_then(|value| normalize(value.trim()))
        .unwrap_or_else(|| DEFAULT_SHORTCUT.to_owned());
    let registered = register(app, &accelerator).is_ok();
    if let Ok(mut state) = app.state::<Diagram>().shortcut.lock() {
        *state = (accelerator, registered);
    }
}

pub async fn command(app: &AppHandle, channel: &str, payload: &Value) -> Result<Value, String> {
    if channel == "sdd:diagram:open" {
        open(app).await?;
        return Ok(Value::Null);
    }
    let diagram = app.state::<Diagram>();
    let mut state = diagram.shortcut.lock().map_err(|error| error.to_string())?;
    if channel == "sdd:diagram:set-shortcut" {
        let next = payload
            .as_str()
            .and_then(normalize)
            .ok_or("DIAGRAM_INVALID_SHORTCUT")?;
        if next != state.0 || !state.1 {
            let path = path(app)?;
            register(app, &next)?;
            let temporary = path.with_extension("tmp");
            let saved =
                std::fs::write(&temporary, &next).and_then(|_| std::fs::rename(&temporary, &path));
            if let Err(error) = saved {
                unregister(app, &next);
                let _ = std::fs::remove_file(temporary);
                return Err(error.to_string());
            }
            if state.1 {
                unregister(app, &state.0);
            }
            *state = (next, true);
        }
    } else if channel != "sdd:diagram:shortcut" {
        return Err("Unknown diagram command".into());
    }
    Ok(json!({ "accelerator": state.0, "registered": state.1 }))
}
