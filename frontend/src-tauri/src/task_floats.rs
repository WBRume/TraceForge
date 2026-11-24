use serde_json::{json, Value};
use std::{collections::HashMap, sync::Mutex};
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, Url, WebviewUrl, WebviewWindow};
use tauri_plugin_opener::OpenerExt;

const PREFIX: &str = "task-float-";

enum FinishAction {
    Dismissed,
    Returned(Option<(f64, f64)>),
}

#[derive(Default)]
pub struct DetachedFloats(Mutex<HashMap<String, Option<FinishAction>>>);

fn valid_id(value: &Value) -> Result<&str, String> {
    value
        .as_str()
        .filter(|id| {
            !id.is_empty()
                && id.len() <= 128
                && id
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'-' | b'_'))
        })
        .ok_or_else(|| "Invalid task float identifier".to_owned())
}

pub fn local_navigation(url: &Url) -> bool {
    url.scheme() == "tauri"
        || url.host_str() == Some("tauri.localhost")
        || (cfg!(debug_assertions)
            && url.host_str() == Some("127.0.0.1")
            && url.port() == Some(5173))
}

pub fn prepare(app: &AppHandle, request: &Value) -> Result<Value, String> {
    let id = valid_id(&request["id"])?;
    let workspace_id = valid_id(&request["workspaceId"])?;
    let task_id = valid_id(&request["taskId"])?;
    let label = format!("{PREFIX}{id}");
    if app.get_webview_window(&label).is_some() {
        return Ok(Value::Null);
    }
    let title = request["title"]
        .as_str()
        .filter(|title| !title.is_empty())
        .unwrap_or("TraceForge 会话");
    let size = |key: &str| {
        request["size"][key]
            .as_f64()
            .filter(|value| *value > 0.0 && *value <= 16384.0)
            .ok_or_else(|| "Invalid task float size".to_owned())
    };
    let width = size("width")?;
    let height = size("height")?;
    let fragment = format!("/task-float?id={id}&workspaceId={workspace_id}&taskId={task_id}");
    let url = WebviewUrl::App(format!("index.html#{fragment}").into());
    let opener = app.clone();
    let window = tauri::WebviewWindowBuilder::new(app, label, url)
        .title(title)
        .inner_size(width, height)
        .min_inner_size(width.min(300.0), height.min(200.0))
        .center()
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .minimizable(false)
        .maximizable(false)
        .visible(false)
        .focused(false)
        .focusable(false)
        .on_navigation(move |url| local_navigation(url) && url.fragment() == Some(&fragment))
        .on_new_window(move |url, _| {
            if matches!(url.scheme(), "http" | "https") {
                let _ = opener.opener().open_url(url.as_str(), None::<&str>);
            }
            tauri::webview::NewWindowResponse::Deny
        })
        .build()
        .map_err(|error| error.to_string())?;
    #[cfg(windows)]
    disable_transitions(&window);
    #[cfg(not(windows))]
    let _ = window;
    Ok(Value::Null)
}

#[cfg(windows)]
fn disable_transitions(window: &WebviewWindow) {
    use windows::Win32::{
        Foundation::TRUE,
        Graphics::Dwm::{DwmSetWindowAttribute, DWMWA_TRANSITIONS_FORCEDISABLED},
    };

    if let Ok(handle) = window.hwnd() {
        let disabled = TRUE;
        // The handle belongs to this live window and DWM reads a Windows BOOL.
        let _ = unsafe {
            DwmSetWindowAttribute(
                handle,
                DWMWA_TRANSITIONS_FORCEDISABLED,
                (&raw const disabled).cast(),
                std::mem::size_of_val(&disabled) as u32,
            )
        };
    }
}

fn hide(window: &WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|error| error.to_string())?;
    // Synchronize with the native event loop before restoring the client surface.
    window
        .is_visible()
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn destroy(window: &WebviewWindow) -> Result<(), String> {
    hide(window)?;
    window.destroy().map_err(|error| error.to_string())
}

pub fn place(main: &WebviewWindow, request: &Value) -> Result<Value, String> {
    let app = main.app_handle();
    let id = valid_id(&request["id"])?;
    let window = app
        .get_webview_window(&format!("{PREFIX}{id}"))
        .ok_or("Task float is unavailable")?;
    let position = &request["position"];
    if position.is_null() {
        hide(&window)?;
        return Ok(Value::Null);
    }
    let coordinate = |key: &str| {
        position[key]
            .as_f64()
            .filter(|value| value.abs() <= 32768.0)
            .ok_or_else(|| "Invalid task float position".to_owned())
    };
    let origin = main.inner_position().map_err(|error| error.to_string())?;
    let scale = main.scale_factor().map_err(|error| error.to_string())?;
    let mut x = origin.x + (coordinate("x")? * scale).round() as i32;
    let mut y = origin.y + (coordinate("y")? * scale).round() as i32;
    let dropped = request["dropped"].as_bool().unwrap_or(false);
    if dropped {
        let size = window.outer_size().map_err(|error| error.to_string())?;
        let width = size.width as i32;
        let height = size.height as i32;
        let monitor = app
            .monitor_from_point((x + width / 2) as f64, f64::from(y) + 21.0 * scale)
            .ok()
            .flatten()
            .or_else(|| window.current_monitor().ok().flatten());
        if let Some(monitor) = monitor {
            let area = monitor.work_area();
            let title_width = width
                .min(area.size.width as i32)
                .min((160.0 * scale) as i32);
            let title_height = height
                .min(area.size.height as i32)
                .min((42.0 * scale) as i32);
            x = x
                .min(area.position.x + area.size.width as i32 - title_width)
                .max(area.position.x + title_width - width);
            y = y
                .min(area.position.y + area.size.height as i32 - title_height)
                .max(area.position.y);
        }
    }
    window
        .set_position(PhysicalPosition::new(x, y))
        .map_err(|error| error.to_string())?;
    if !window.is_visible().map_err(|error| error.to_string())? {
        window.show().map_err(|error| error.to_string())?;
    }
    if dropped {
        window
            .set_focusable(true)
            .map_err(|error| error.to_string())?;
        app.state::<DetachedFloats>()
            .0
            .lock()
            .map_err(|error| error.to_string())?
            .entry(window.label().to_owned())
            .or_insert(None);
    }
    Ok(Value::Null)
}

pub fn close(app: &AppHandle, request: &Value) -> Result<Value, String> {
    let id = valid_id(&request["id"])?;
    if let Some(window) = app.get_webview_window(&format!("{PREFIX}{id}")) {
        destroy(&window)?;
    }
    Ok(Value::Null)
}

pub fn close_all(app: &AppHandle) {
    for (label, window) in app.webview_windows() {
        if label.starts_with(PREFIX) {
            let _ = window.destroy();
        }
    }
}

pub fn on_destroyed(window: &tauri::Window) {
    if window.label() == "main" {
        close_all(window.app_handle());
    } else if let Some(id) = window.label().strip_prefix(PREFIX) {
        let action = window
            .state::<DetachedFloats>()
            .0
            .lock()
            .ok()
            .and_then(|mut floats| floats.remove(window.label()).flatten());
        let payload = match action {
            Some(FinishAction::Dismissed) => json!({ "id": id, "action": "dismissed" }),
            Some(FinishAction::Returned(Some((x, y)))) => {
                json!({ "id": id, "action": "returned", "position": { "x": x, "y": y } })
            }
            Some(FinishAction::Returned(None)) => json!({ "id": id, "action": "returned" }),
            None => json!({ "id": id, "action": "closed" }),
        };
        let _ = window.emit_to(
            "main",
            "desktop-event",
            json!({
                "channel": "sdd:task-float:closed",
                "payload": payload
            }),
        );
    }
}

pub fn on_close_requested(window: &tauri::Window) {
    if window.label().starts_with(PREFIX) {
        if let Ok(mut floats) = window.state::<DetachedFloats>().0.lock() {
            if let Some(action) = floats.get_mut(window.label()) {
                action.get_or_insert(FinishAction::Dismissed);
            }
        }
    }
}

fn finish(window: &WebviewWindow, action: FinishAction) -> Result<(), String> {
    let state = window.state::<DetachedFloats>();
    let return_to_client = matches!(&action, FinishAction::Returned(_));
    {
        let mut floats = state.0.lock().map_err(|error| error.to_string())?;
        let outcome = floats
            .get_mut(window.label())
            .ok_or("The command requires a detached task float")?;
        if outcome.is_some() {
            return Ok(());
        }
        *outcome = Some(action);
    }
    if let Err(error) = destroy(window) {
        if let Ok(mut floats) = state.0.lock() {
            if let Some(outcome) = floats.get_mut(window.label()) {
                *outcome = None;
            }
        }
        return Err(error);
    }
    if return_to_client {
        if let Some(main) = window.app_handle().get_webview_window("main") {
            main.unminimize().map_err(|error| error.to_string())?;
            main.show().map_err(|error| error.to_string())?;
            main.set_focus().map_err(|error| error.to_string())?;
        }
    }
    Ok(())
}

#[tauri::command]
pub async fn task_float_finish(
    window: WebviewWindow,
    return_to_client: bool,
) -> Result<(), String> {
    finish(
        &window,
        if return_to_client {
            FinishAction::Returned(None)
        } else {
            FinishAction::Dismissed
        },
    )
}

#[tauri::command]
pub async fn task_float_drag(window: WebviewWindow, request: Value) -> Result<(), String> {
    let app = window.app_handle();
    if !app
        .state::<DetachedFloats>()
        .0
        .lock()
        .map_err(|error| error.to_string())?
        .get(window.label())
        .is_some_and(Option::is_none)
    {
        return Err("The command requires a detached task float".into());
    }
    let grab = |axis: &str| {
        request["grab"][axis]
            .as_f64()
            .filter(|value| (0.0..=32768.0).contains(value))
            .ok_or_else(|| "Invalid task float drag position".to_owned())
    };
    let cursor = app.cursor_position().map_err(|error| error.to_string())?;
    let scale = match app
        .monitor_from_point(cursor.x, cursor.y)
        .map_err(|error| error.to_string())?
    {
        Some(monitor) => monitor.scale_factor(),
        None => window.scale_factor().map_err(|error| error.to_string())?,
    };
    let x = cursor.x - grab("x")? * scale;
    let y = cursor.y - grab("y")? * scale;
    if request["dropped"].as_bool() == Some(true) {
        if let Some(main) = app.get_webview_window("main") {
            if main.is_visible().map_err(|error| error.to_string())?
                && !main.is_minimized().map_err(|error| error.to_string())?
            {
                let client = main.inner_position().map_err(|error| error.to_string())?;
                let size = main.inner_size().map_err(|error| error.to_string())?;
                let left = f64::from(client.x);
                let top = f64::from(client.y);
                if cursor.x >= left
                    && cursor.x < left + f64::from(size.width)
                    && cursor.y >= top
                    && cursor.y < top + f64::from(size.height)
                {
                    let client_scale = main.scale_factor().map_err(|error| error.to_string())?;
                    return finish(
                        &window,
                        FinishAction::Returned(Some((
                            (x - left) / client_scale,
                            (y - top) / client_scale,
                        ))),
                    );
                }
            }
        }
    }
    let outer = window.outer_position().map_err(|error| error.to_string())?;
    let inner = window.inner_position().map_err(|error| error.to_string())?;
    window
        .set_position(PhysicalPosition::new(
            x.round() as i32 + outer.x - inner.x,
            y.round() as i32 + outer.y - inner.y,
        ))
        .map_err(|error| error.to_string())
}
