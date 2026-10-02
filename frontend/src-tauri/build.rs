fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["desktop_invoke", "desktop_platform"]),
    ))
    .expect("Failed to build Tauri resources")
}
