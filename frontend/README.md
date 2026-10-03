# TraceForge 前端和双桌面构建

Vue 3 + TypeScript 的同一套页面同时运行于 Web、Electron 和 Tauri 2。业务通过 `getSddDesktop()` 和 `SddDesktopApi` 调用配置、Git、补丁、文件保存、命令输出、OAuth 和本地资源服务。

## 开发

```powershell
npm ci
npm run dev             # 浏览器
npm run dev:electron    # 原有 Electron 开发，不需要 Rust
```

Tauri 开发另外需要 Rust stable 和系统构建工具。Windows 安装 Visual Studio C++ Build Tools 和 WebView2，然后执行 `npm run dev:tauri`。Bun 由 npm 开发依赖提供，不要求全局安装。桌面用户无需安装 Node、Bun 或 Rust；本地 Agent 和 Git 的要求与原 Electron 相同。

## Windows x64 安装包

```powershell
npm run build:electron -- --win --x64
npm run build:tauri -- --bundles nsis
```

两种桌面应用均以 `TraceForge` 作为应用名称、窗口标题和主程序名（Windows 为 `TraceForge.exe`）。npm 包名为 `traceforge`。

两种安装包按桌面运行时分目录输出：Electron 为 `release/electron/TraceForge Setup <版本>.exe`，Tauri 为 `release/tauri/TraceForge_<版本>_x64-setup.exe`。CI 上传时保留 `electron/` 和 `tauri/` 目录。Electron 使用安装向导，支持选择安装目录。Tauri 的 `target/` 保留编译缓存和原始打包文件。

Tauri 的业务 HTTP 请求使用原生 HTTP 通道，支持已配置的 HTTP/HTTPS 后端地址，避免 WebView 来源导致的 CORS 拒绝；Axios 的认证头、错误拦截器和超时行为继续生效。

Tauri 包含独立编译的桌面服务和 Resource Host Worker，使用系统 WebView2；系统缺少 WebView2 时，安装器会联网下载，安装包体积不包含该下载大小。两轨共享版本号，安装标识和配置目录各自独立，允许并存。默认构建未签名。

桌面构建使用相对资源路径和 hash 路由，并用系统字体回退避免远程字体失败阻断页面加载。Web 构建继续使用原有根路径和字体设置。Windows CI 会构建两种 NSIS 包、运行桥接和可执行文件测试、上传安装包。

## 适配边界和检查

`desktop/api.ts` 维护统一命令/事件协议。Electron preload 与 `src/desktop/initialize.ts` 的 Tauri 适配器复用它；Vue 入口在加载路由/API 模块前安装适配器。`desktop/native.ts` 定义原生依赖边界，Tauri 的 Bun 编译阶段替换为 `tauri-native.ts`，复用 `electron/ipc/` 中的业务实现。Rust 只向本地 main 窗口开放桥入口，提供原生对话框、外部打开和服务生命周期管理，IPC 不开放 TCP 端口。

```powershell
npm run test:run -- src/desktop/__tests__ electron/ipc/__tests__/localResources.spec.ts
npx vue-tsc -b --pretty false
npm run build:desktop:host
node --test desktop/tests/host.smoke.mjs
cargo fmt --manifest-path src-tauri/Cargo.toml --check
```

Tauri 的当前 CI 发布目标是 Windows x64，其他平台的安装器尚未验证。
