# TraceForge 前端和双桌面构建

Vue 3 + TypeScript 的同一套页面同时运行于 Web、Electron 和 Tauri 2。业务通过 `getSddDesktop()` 和 `SddDesktopApi` 调用配置、Git、补丁、文件保存、命令输出、OAuth 和本地资源服务。

浏览器仅允许创建服务器资源任务；本地资源任务的创建和本地服务配置仅在 Electron、Tauri 客户端开放。请求拦截器根据原生桥接设置 `X-TraceForge-Client: desktop` 或 `web`，任务创建 API 对缺少桌面端标识的 `LOCAL` 请求返回 `403 / LOCAL_TASK_DESKTOP_REQUIRED`，且不创建任务记录或资源准备作业。

本地文件、Git worktree、快照、补丁、Skills 和文档操作实现位于 `desktop/local-resource/`，由客户端启动并管理，不再提供独立资源服务的安装包、启动器或托盘。原有任务执行绑定和本地状态目录继续使用。

## 开发

```powershell
npm ci
npm run dev             # 浏览器
npm run dev:electron    # 原有 Electron 开发，不需要 Rust
```

Electron 开发沿用快速启动流程，预热入口和首页，在初始路由完成渲染后显示窗口。Vite 仅扫描 `index.html`，不把 Tauri 编译缓存或安装包内的 HTML 当作入口，文件监听也排除这些构建产物。Electron 使用已有 preload，仅 Tauri 等待异步桥接和原生 HTTP 初始化。桌面开发使用系统字体，避免外部字体网络请求。开发端口固定为 `127.0.0.1:5173`，端口占用会直接报错。

开发工具按需打开，按 `F12` 切换。设置 `TRACEFORGE_DEVTOOLS=1` 可恢复启动时自动打开。

Tauri 开发另外需要 Rust stable 和系统构建工具。Windows 安装 Visual Studio C++ Build Tools 和 WebView2，然后执行 `npm run dev:tauri`。Bun 由 npm 开发依赖提供，不要求全局安装。桌面用户无需安装 Node、Bun 或 Rust；本地 Agent 和 Git 的要求与原 Electron 相同。

## Windows x64 安装包

```powershell
npm run build:electron -- --win --x64
npm run build:tauri -- --bundles nsis
```

两种桌面应用均以 `TraceForge` 作为应用名称、窗口标题和主程序名（Windows 为 `TraceForge.exe`）。npm 包名为 `traceforge`。

两种安装包按桌面运行时分目录输出：Electron 为 `release/electron/TraceForge Setup <版本>.exe`，Tauri 为 `release/tauri/TraceForge_<版本>_x64-setup.exe`。CI 上传时保留 `electron/` 和 `tauri/` 目录。Electron 使用安装向导，支持选择安装目录。Tauri 的 `target/` 保留编译缓存和原始打包文件。

Tauri 的业务 HTTP 请求使用原生 HTTP 通道，支持已配置的 HTTP/HTTPS 后端地址，避免 WebView 来源导致的 CORS 拒绝；Axios 的认证头、错误拦截器和超时行为继续生效。

Tauri 包含编译后的桌面服务和内置本地资源 Worker，使用系统 WebView2；系统缺少 WebView2 时，安装器会联网下载，安装包体积不包含该下载大小。两轨共享版本号，安装标识和配置目录各自独立，允许并存。默认构建未签名。

桌面构建使用相对资源路径和 hash 路由，并用系统字体回退避免远程字体失败阻断页面加载。Web 构建继续使用原有根路径和字体设置。Windows CI 会构建两种 NSIS 包、运行桥接和可执行文件测试、上传安装包。

## 适配边界和检查

`desktop/api.ts` 维护统一命令/事件协议。Electron preload 与 `src/desktop/initialize.ts` 的 Tauri 适配器复用它；Vue 入口在加载路由/API 模块前安装适配器。`desktop/native.ts` 定义原生依赖边界，Tauri 的 Bun 编译阶段替换为 `tauri-native.ts`，复用 `electron/ipc/` 中的业务实现。Rust 只向本地 main 窗口开放桥入口，提供原生对话框、外部打开和服务生命周期管理，IPC 不开放 TCP 端口。

```powershell
npm run test:run -- src/desktop/__tests__ electron/ipc/__tests__/localResources.spec.ts
npm run test:desktop:resources
npx vue-tsc -b --pretty false
npm run build:desktop:host
node --test desktop/tests/host.smoke.mjs
cargo fmt --manifest-path src-tauri/Cargo.toml --check
```

Tauri 的当前 CI 发布目标是 Windows x64，其他平台的安装器尚未验证。

## 语音输入：构建时选择 API / 离线 / 关闭

聊天输入框提供录音、停止和取消操作，页面不提供功能开关或模式选择。API 模式的识别结果实时写入输入框光标处，同一句的中间结果在原位置修订，停止时不会重复追加；离线模式在停止录音、完成本地推理后写入。输入框原有内容保留，不自动发送；取消或断线保留已经写入的文字。录音期间暂停发送，切换会话、离开页面或取消会释放麦克风并丢弃迟到结果。手动修改正在识别的文字时会结束本次语音输入，保留手动修改。每段最多 60 秒。

`TRACEFORGE_SPEECH_MODE` 在**前端构建进程的环境变量**中配置，修改后需要重新构建前端及桌面主进程：

| 值 | 浏览器 | Electron / Tauri | 附加资源 |
| --- | --- | --- | --- |
| `api`（默认） | 百炼流式识别 | 百炼流式识别 | 无本地模型或 Sherpa 依赖 |
| `offline` | 不显示录音入口 | Sherpa-ONNX + SenseVoice-Small INT8 | 本地准备资源，可选随包携带 |
| `off` | 不显示录音入口 | 不显示录音入口 | 无 |

```powershell
$env:TRACEFORGE_SPEECH_MODE = 'api'  # 也可为 offline / off
$env:TRACEFORGE_BUNDLE_SPEECH = '0'
npm run build                       # Web
npm run build:electron -- --win --x64
npm run build:tauri -- --bundles nsis
```

开发命令同样读取上述环境变量。Docker Web 镜像支持同名 build argument；Compose 使用 `${TRACEFORGE_SPEECH_MODE:-api}`。桌面 CI 读取同名仓库变量，默认 API 模式、不附带语音资源。不要将长期 API Key 写进任何 `VITE_*` 或前端构建变量。

### API 模式：半直连

固定使用 `qwen-audio-3.1-asr-flash-streaming`。后端 `.env` / 部署环境配置：

```dotenv
SPEECH_API_ENABLED=true
SPEECH_API_KEY=<百炼长期 API Key，仅后端持有>
SPEECH_API_REGION=beijing
SPEECH_TOKEN_TTL_SECONDS=120
SPEECH_TOKEN_REQUESTS_PER_MINUTE=6
```

登录用户通过 `POST /api/speech/sessions` 领取短期 `st-` 凭证，响应禁止缓存；Redis 按用户限制签发次数，Redis 不可用时返回 503。前端仅将临时凭证保存在本次录音的内存中，通过 `wss://dashscope.aliyuncs.com/api-ws/v1/inference?api_key=<临时凭证>` 直连百炼；音频不经过 TraceForge 后端。新加坡 Key 使用 `SPEECH_API_REGION=singapore`，两个地域的 Key 不能混用。

聊天输入组件可用时自动领取短期凭证、建立 WebSocket 并启动识别任务，不依赖输入框聚焦、鼠标悬停或点击，点击前不访问麦克风。页面保持在前台且输入可用时保持任务待命，每秒发送 100 毫秒合成静音保活，约增加每分钟前台待命 6 秒的上传音频（实际计费以百炼用量为准）。窗口失焦、页面隐藏、输入禁用或组件卸载时释放闲置连接，恢复可用后自动准备；后台失败采用递增退避，遇到签发限流至少等 60 秒重试。短期凭证仅缓存在组件内存，在失效前 15 秒更新，后续录音复用尚有效的凭证，切换服务器时清除；后端复用 HTTP 连接并在应用退出时释放。

点击录音复用待命任务，麦克风设备、AudioContext 和 AudioWorklet 并行初始化，不等待网络；麦克风就绪即提示“请开始说话”，音量条实时反馈采集状态。首次访问仍须允许麦克风权限。每 20 毫秒发送 PCM；连接未完成时音频暂存在最多容纳 20 秒的内存队列，收到 `task-started` 才按顺序发送。停止时先排空队列，再发送 `finish-task`，完成后自动准备下次任务。使用 VAD 断句和 600 毫秒停顿阈值；`result-generated` 的中间/最终句子直接更新输入框，不另设文字预览浮层。设备不支持 16 kHz 时在发送音频前按实际采样率重新建立任务。预连接失败会在点击时重试；录音中连接超时、上游错误或断线则停止录音，不自动重传音频。浏览器麦克风需要 HTTPS 或 localhost。

待命只消除连接准备的等待，不能消除音频上下文、网络传输和服务端识别的耗时。验收须同时记录点击到首字、有声音频发出到上游首个非空结果、收到结果到输入框显示，且直接点击麦克风前不得聚焦输入框或悬停按钮。样例中的开头静音不应被当作模型推理时间。

临时凭证继承长期 Key 的权限；生产建议使用仅授权此 ASR 模型的百炼 Key。临时凭证的 TTL 和签发限流不等同于单次识别计费配额。

协议参考：[模型接入](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-model-access)、[客户端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-client-events)、[服务端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-server-events)、[临时 API Key](https://help.aliyun.com/zh/model-studio/generate-temporary-api-key)。浏览器使用临时 Key 的 query 鉴权已通过实际建连验证。

### 离线模式：可选资源，默认不随包携带

模型限定为 **SenseVoice-Small**。官方 `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17` 中的 `model.int8.onnx` 约 228 MB

桌面端以本机 `sherpa-onnx-offline` 子进程识别，不依赖 Python、Node 原生扩展；识别时无需网络。Windows x64 可显式运行下面的命令准备资源，普通安装/构建不会调用该命令：

```powershell
# 在 frontend/ 下执行，仅部署者准备离线版时下载一次。
npm run speech:prepare
$env:TRACEFORGE_SPEECH_MODE = 'offline'
$env:TRACEFORGE_SPEECH_ASSETS = (Resolve-Path './offline-speech').Path
$env:TRACEFORGE_BUNDLE_SPEECH = '0'  # 外置资源，保持客户端安装包体积
npm run dev:electron                # 或 npm run dev:tauri
```

准备脚本固定 Sherpa-ONNX 1.13.8（Windows x64 shared-MT/no-tts）和官方 SenseVoice-Small INT8 2024-07-17 模型，校验下载文件 SHA-256，只保留识别需要的可执行文件、DLL、模型、词表和许可证。**实际识别官方中文样例成功后**才生成最终资源目录及 `manifest.json`。下载失败、校验失败、DLL/模型无法加载都会报错，不留下半成品资源目录。目标目录已存在时不会覆盖；更换版本请指定新的 `TRACEFORGE_SPEECH_ASSETS`。

下载缓存默认在系统临时目录的 `traceforge-speech-cache/`，可用 `TRACEFORGE_SPEECH_CACHE` 指定。断网准备环境可提前复制完整缓存（文件名和 SHA-256 见 `desktop/speech/prepare.ts`），随后运行同一命令。其他平台须准备匹配目标 OS/架构的官方运行库；自动准备及真实推理当前验收平台为 Windows x64。

资源目录布局如下：

```text
offline-speech/
  model.int8.onnx             # SenseVoice-Small INT8
  tokens.txt
  bin/sherpa-onnx-offline.exe  # Linux/macOS 无 .exe 后缀
  bin/*.dll                  # Windows 依赖库；其他平台保留发行包 lib/ 布局
  lib/                       # 如所用平台发行包需要
  licenses/                  # 模型和运行库许可证
  manifest.json              # 准备脚本生成的来源、版本、平台、文件 SHA-256
```

`TRACEFORGE_SPEECH_MODE=offline`、`TRACEFORGE_BUNDLE_SPEECH=0` 可在没有资源的构建机上打包。运行时通过环境变量 `TRACEFORGE_SPEECH_ASSETS` 指定本地目录，或将资源放到应用资源目录下的 `offline-speech/`（Electron 开发默认 `frontend/offline-speech/`）。缺失资源时录音按钮不可用，并提供缺失提示。

只有显式设置 `TRACEFORGE_BUNDLE_SPEECH=1` 才将 `TRACEFORGE_SPEECH_ASSETS`（默认 `frontend/offline-speech/`）复制到安装包；仅允许与 `offline` 模式组合，资源或 Windows ONNX DLL 缺失、manifest 标注了不匹配的模型/平台/架构时会终止打包。关闭此选项时不会检测/下载/携带模型，构建机无需安装 Sherpa-ONNX。不要把整个上游开发包、测试音频或其他模型放入打包目录。

离线音频通过桌面 IPC 传递，校验为 16 kHz 单声道 PCM16 WAV，并在独立临时目录识别；完成或取消后清理音频。识别进程有 120 秒超时，应用正常退出时等待识别进程终止和临时音频删除。

真实桌面服务回归命令（需要本地资源，独立于不带模型的普通 CI）：

```powershell
$env:TRACEFORGE_SPEECH_MODE = 'offline'
npm run build:desktop:host
$env:TRACEFORGE_SPEECH_TEST_WAV = 'C:\path\to\test_wavs\zh.wav'
npm run test:desktop:speech
```

该检查直接调用编译后的 Tauri sidecar，使用官方样例执行真实识别、取消、再次识别、退出中断和临时音频清理。默认验证 `frontend/offline-speech/` 资源路径；设 `TRACEFORGE_SPEECH_TEST_RESOURCE_ROOT` 可验证打包产物中包含 `offline-speech/` 的资源父目录。

2026-10-06 Windows x64 验收：Electron 实际打包程序通过样例麦克风输入，断网完成「录音按钮 → AudioWorklet → preload IPC → 包内 Sherpa → 草稿追加」，同时验证草稿保留、不自动发送、取消和麦克风释放；Tauri 通过编译服务的真实推理/取消/退出清理，并完成携带资源的 NSIS 构建。Tauri WebView 前台录音及物理麦克风/系统授权仍需人工验收，不能用样例注入或服务测试替代。
