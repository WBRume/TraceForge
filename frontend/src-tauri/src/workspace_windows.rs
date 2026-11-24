use crate::{task_floats, Bridge, Reply};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{AppHandle, Manager, PhysicalPosition, WebviewUrl, WebviewWindow};
use tauri_plugin_opener::OpenerExt;
use windows::Win32::{
    Foundation::POINT,
    Graphics::Gdi::{GetMonitorInfoW, MonitorFromRect, MONITORINFO, MONITOR_DEFAULTTONEAREST},
    UI::WindowsAndMessaging::{
        GetAncestor, GetWindowPlacement, SetWindowPos, WindowFromPoint, GA_ROOT, SWP_NOACTIVATE,
        SWP_NOZORDER, SW_SHOWMAXIMIZED, WINDOWPLACEMENT, WPF_RESTORETOMAXIMIZED,
    },
};

const MIN_WIDTH: f64 = 720.0;
const MIN_HEIGHT: f64 = 520.0;
const DETACHED_WIDTH: f64 = 1320.0;
const DETACHED_HEIGHT: f64 = 820.0;
static QUITTING: AtomicBool = AtomicBool::new(false);

pub fn is_secondary(label: &str) -> bool {
    label.strip_prefix("workspace-").is_some_and(|id| {
        id.len() == 36
            && id
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() || byte == b'-')
    })
}

pub fn is_workspace(label: &str) -> bool {
    label == "main" || is_secondary(label)
}

fn placement(window: &WebviewWindow) -> Option<Value> {
    let handle = window.hwnd().ok()?;
    let mut placement = WINDOWPLACEMENT {
        length: std::mem::size_of::<WINDOWPLACEMENT>() as u32,
        ..Default::default()
    };
    // The normal bounds remain available while the window is maximized or minimized.
    unsafe { GetWindowPlacement(handle, &mut placement) }.ok()?;
    let rect = placement.rcNormalPosition;
    let mut monitor = MONITORINFO {
        cbSize: std::mem::size_of::<MONITORINFO>() as u32,
        ..Default::default()
    };
    // Win32 returns workspace coordinates for regular top-level windows. Convert to screen pixels.
    let handle = unsafe { MonitorFromRect(&rect, MONITOR_DEFAULTTONEAREST) };
    let _ = unsafe { GetMonitorInfoW(handle, &mut monitor) };
    Some(json!({
        "x": rect.left + monitor.rcWork.left - monitor.rcMonitor.left,
        "y": rect.top + monitor.rcWork.top - monitor.rcMonitor.top,
        "width": rect.right - rect.left,
        "height": rect.bottom - rect.top,
        "maximized": placement.showCmd == SW_SHOWMAXIMIZED.0 as u32
            || (window.is_minimized().unwrap_or(false) && placement.flags.0 & WPF_RESTORETOMAXIMIZED.0 != 0),
    }))
}

pub fn on_event(window: &tauri::Window, event: &tauri::WindowEvent) {
    let label = window.label();
    if !is_workspace(label) || QUITTING.load(Ordering::Relaxed) {
        return;
    }
    let app = window.app_handle();
    let bridge = app.state::<Bridge>();
    match event {
        tauri::WindowEvent::CloseRequested { api, .. } if label == "main" => {
            api.prevent_close();
            QUITTING.store(true, Ordering::Relaxed);
            app.exit(0);
        }
        tauri::WindowEvent::Destroyed if is_secondary(label) => {
            let _ = bridge.write(
                &json!({ "kind": "workspace-window-event", "event": "closed", "window": label }),
            );
        }
        tauri::WindowEvent::Moved(_)
        | tauri::WindowEvent::Resized(_)
        | tauri::WindowEvent::ScaleFactorChanged { .. } => {
            if let Some(bounds) = app
                .get_webview_window(label)
                .and_then(|window| placement(&window))
            {
                let _ = bridge.write(&json!({ "kind": "workspace-window-event", "event": "geometry", "window": label, "placement": bounds }));
            }
        }
        _ => {}
    }
}

pub fn ready(window: &WebviewWindow) -> Reply {
    if !is_workspace(window.label()) {
        return Err("Workspace window is not allowed".into());
    }
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;
    if let Some(bounds) = placement(window) {
        let _ = window.app_handle().state::<Bridge>().write(&json!({
            "kind": "workspace-window-event", "event": "geometry", "window": window.label(), "placement": bounds,
        }));
    }
    Ok(Value::Null)
}

pub fn control(window: &WebviewWindow, action: &Value) -> Reply {
    if !is_workspace(window.label()) {
        return Err("Workspace window is not allowed".into());
    }
    match action.as_str() {
        Some("minimize") => window.minimize(),
        Some("maximize") if window.is_maximized().unwrap_or(false) => window.unmaximize(),
        Some("maximize") => window.maximize(),
        Some("close") => window.close(),
        _ => return Err("Unknown workspace window control".into()),
    }
    .map_err(|error| error.to_string())?;
    Ok(Value::Null)
}

pub fn move_window(window: &WebviewWindow, grab: &Value) -> Reply {
    if !is_workspace(window.label()) {
        return Err("Workspace window is not allowed".into());
    }
    let coordinate = |key: &str| {
        grab[key]
            .as_f64()
            .filter(|value| (0.0..=32768.0).contains(value))
            .ok_or("Invalid workspace window grab point")
    };
    let (grab_x, grab_y) = (coordinate("x")?, coordinate("y")?);
    let cursor = window
        .cursor_position()
        .map_err(|error| error.to_string())?;
    if window.is_maximized().unwrap_or(false) {
        window.unmaximize().map_err(|error| error.to_string())?;
    }
    let scale = window.scale_factor().map_err(|error| error.to_string())?;
    let size = window.inner_size().map_err(|error| error.to_string())?;
    let inner = window.inner_position().map_err(|error| error.to_string())?;
    let outer = window.outer_position().map_err(|error| error.to_string())?;
    let x = cursor.x - (grab_x * scale).min((f64::from(size.width) - 24.0 * scale).max(0.0))
        + f64::from(outer.x - inner.x);
    let y = cursor.y - grab_y * scale + f64::from(outer.y - inner.y);
    window
        .set_position(PhysicalPosition::new(x.round() as i32, y.round() as i32))
        .map_err(|error| error.to_string())?;
    Ok(Value::Null)
}

fn place(window: &WebviewWindow, saved: &Value, drop_point: &Value) -> Reply {
    if saved.is_null() && drop_point.is_null() {
        return Ok(Value::Null);
    }
    let value = if saved.is_null() { drop_point } else { saved };
    let x = value["x"].as_f64().ok_or("Missing window position")?;
    let y = value["y"].as_f64().ok_or("Missing window position")?;
    let app = window.app_handle();
    let monitor_x = x + saved["width"].as_f64().unwrap_or_default() / 2.0;
    let monitor_y = y + saved["height"].as_f64().unwrap_or_default() / 2.0;
    let screen = app
        .monitor_from_point(monitor_x, monitor_y)
        .ok()
        .flatten()
        .or_else(|| app.primary_monitor().ok().flatten());
    let Some(monitor) = screen else {
        return Ok(Value::Null);
    };
    let area = monitor.work_area();
    let scale = monitor.scale_factor();
    let width = saved["width"]
        .as_f64()
        .unwrap_or(DETACHED_WIDTH * scale)
        .max(MIN_WIDTH * scale)
        .min(f64::from(area.size.width));
    let height = saved["height"]
        .as_f64()
        .unwrap_or(DETACHED_HEIGHT * scale)
        .max(MIN_HEIGHT * scale)
        .min(f64::from(area.size.height));
    let desired_x = if saved.is_null() {
        x - 110.0 * scale
    } else {
        x
    };
    let desired_y = if saved.is_null() { y - 18.0 * scale } else { y };
    let x = desired_x.clamp(
        f64::from(area.position.x),
        f64::from(area.position.x) + f64::from(area.size.width) - width,
    );
    let y = desired_y.clamp(
        f64::from(area.position.y),
        f64::from(area.position.y) + f64::from(area.size.height) - height,
    );
    if window.is_maximized().unwrap_or(false) {
        window.unmaximize().map_err(|error| error.to_string())?;
    }
    let handle = window.hwnd().map_err(|error| error.to_string())?;
    // Restore the outer rectangle in physical pixels, including the frame insets.
    unsafe {
        SetWindowPos(
            handle,
            None,
            x.round() as i32,
            y.round() as i32,
            width.round() as i32,
            height.round() as i32,
            SWP_NOACTIVATE | SWP_NOZORDER,
        )
    }
    .map_err(|error| error.to_string())?;
    if saved["maximized"].as_bool() == Some(true) {
        window.maximize().map_err(|error| error.to_string())?;
    }
    Ok(Value::Null)
}

fn pointer(app: &AppHandle) -> Reply {
    let cursor = app.cursor_position().map_err(|error| error.to_string())?;
    let point = POINT {
        x: cursor.x.round() as i32,
        y: cursor.y.round() as i32,
    };
    let root = unsafe { GetAncestor(WindowFromPoint(point), GA_ROOT) };
    let mut result = json!({ "screen": { "x": cursor.x, "y": cursor.y } });
    for (label, window) in app.webview_windows() {
        if !is_workspace(&label) || window.hwnd().ok() != Some(root) {
            continue;
        }
        let origin = window.inner_position().map_err(|error| error.to_string())?;
        let scale = window.scale_factor().map_err(|error| error.to_string())?;
        result["windowId"] = json!(label);
        result["local"] = json!({ "x": (cursor.x - f64::from(origin.x)) / scale, "y": (cursor.y - f64::from(origin.y)) / scale });
        break;
    }
    Ok(result)
}

pub fn request(app: &AppHandle, payload: &Value) -> Reply {
    let action = payload["action"]
        .as_str()
        .ok_or("Missing workspace window action")?;
    if action == "pointer" {
        return pointer(app);
    }
    let id = payload["id"]
        .as_str()
        .filter(|label| is_workspace(label))
        .ok_or("Invalid workspace window identifier")?;
    if action == "create" && is_secondary(id) {
        let opener = app.clone();
        let window =
            tauri::WebviewWindowBuilder::new(app, id, WebviewUrl::App("index.html".into()))
                .title("TraceForge")
                .inner_size(DETACHED_WIDTH, DETACHED_HEIGHT)
                .min_inner_size(MIN_WIDTH, MIN_HEIGHT)
                .center()
                .decorations(false)
                .visible(false)
                .focused(false)
                .on_document_title_changed(update_title)
                .on_navigation(task_floats::local_navigation)
                .on_new_window(move |url, _| {
                    if matches!(url.scheme(), "http" | "https") {
                        let _ = opener.opener().open_url(url.as_str(), None::<&str>);
                    }
                    tauri::webview::NewWindowResponse::Deny
                })
                .build()
                .map_err(|error| error.to_string())?;
        let result = place(&window, &payload["placement"], &payload["position"]);
        if result.is_err() {
            let _ = window.destroy();
        }
        return result;
    }
    let window = app.get_webview_window(id);
    match (action, window) {
        ("destroy", Some(window)) if is_secondary(id) => {
            window.destroy().map_err(|error| error.to_string())?
        }
        ("focus", Some(window)) => {
            if window.is_minimized().unwrap_or(false) {
                window.unminimize().map_err(|error| error.to_string())?;
            }
            window.set_focus().map_err(|error| error.to_string())?;
        }
        ("restore", Some(window)) if id == "main" => {
            return place(&window, &payload["placement"], &Value::Null)
        }
        _ => {}
    }
    Ok(Value::Null)
}

pub fn update_title(window: WebviewWindow, title: String) {
    let _ = window.set_title(&title);
}
