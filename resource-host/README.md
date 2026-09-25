# TraceForge Resource Host

TypeScript 实现的同机资源服务。Web 用户可以单独下载、解压并启动；Electron 复用同一套 TypeScript 业务逻辑，使用客户端自带的 Node 运行时与 SQLite，通过 utility process 和 Worker 启动，无需构建或运行独立 Bun 程序。Web 独立发布文件自带运行时，用户电脑无需安装 Node.js、Bun、Python 或平台后端依赖。

当前仅支持内网部署。平台服务器必须能访问 Agent 与 Resource Host；两者在同一开发机器上运行。开发机器需要 Git，以及单独安装并运行的 OpenCode serve 或 DSH web/host。Claude Code CLI 暂不支持。

## Web 用户

1. 获取对应系统的发布目录或压缩包，里面包含 `traceforge-resource-host.exe`（Windows）或 `traceforge-resource-host`（Linux/macOS）、配置示例、本文和 SHA256SUMS。
2. 将 `host.example.json` 复制为私人配置，填写绝对路径和至少 32 位的随机 token。`allowed_roots` 只包含允许服务操作的工作区和个人仓库目录；`state_root` 放在任务工作区之外，保存身份、操作 journal 和检查点，不要删除。
3. 启动：

Windows 用户可以直接双击 `traceforge-resource-host.exe` 启动，或在命令行启动：

```powershell
# 推荐：直接双击运行，或指定配置启动
.\traceforge-resource-host.exe --config G:/private/host.json

# 无头模式（不启动监控面板和系统托盘）
.\traceforge-resource-host.exe --headless
```

Linux / macOS 启动：

```sh
chmod +x ./traceforge-resource-host
./traceforge-resource-host --config /home/me/.config/traceforge/host.json
```

启动后会自动打开可视化的**轻量监控面板**（亦可访问 `http://127.0.0.1:4098/`），展示服务状态、实时 Uptime、Token、授权目录与近期操作记录。Windows 下同时会在**任务栏保留应用图标**，并在**系统托盘（任务工具栏/通知区域）常驻图标**，支持最小化保留、悬浮状态查看、一键复制配置与托盘菜单安全退出。


4. 在同机启动 `opencode serve --hostname 0.0.0.0 --port 4096`（设置 `OPENCODE_SERVER_PASSWORD`），或 `dsh web --host 0.0.0.0 --port 3080 --no-open`（使用启动时的 token）。防火墙允许平台所在内网访问对应端口。
Electron 的“一键启动并配置”不要求工作区目录：仅在“服务地址与网络”步骤启动服务并回填地址与凭据；连接检测成功后自动保存在 Pinia 内存中，再允许进入目录配置。凭据不会写入浏览器 localStorage。同一 Agent 类型复用服务实例。Resource Host 可使用空的 `allowed_roots` 启动，此时不允许操作任何工作目录；保存 Electron 管理的资源配置后追加目录授权，无需重启，已有任务目录授权保留。独立运行时修改配置文件中的 `allowed_roots` 也会在后续目录检查中生效。

5. 在平台个人设置填写 Agent 地址、同机资源服务地址、凭据、工作区根目录、个人 fork Git 地址与仓库目录，保存并检测。Web 无需安装 Electron。

配置可选 `dsh_session_root` 指定与 DSH 相同的会话目录；默认依次读取 DSH_SESSION_ROOT、DSH_HOME/sessions、~/.dsh/sessions。`document_roots` 可覆盖文档扫描根目录，默认 `["docs/superpowers", "superpowers/docs/superpowers", "."]`。

## 开发与独立发布

仅构建机器需要开发工具。项目锁定 Bun 和 TypeScript；不使用 Python/PyInstaller，也不依赖 Electron 构建流程。

```sh
cd resource-host
npm ci
npm run typecheck
npm test
npm run build
```

`npm run build` 输出当前系统可执行文件到 `dist/<platform>-<arch>/`，同时生成独立 `.tar.gz` 发布包。`npm run build:all` 交叉编译 Windows x64、Linux x64/arm64、macOS x64/arm64；首次交叉编译会下载对应运行时。跨平台产物需要在目标系统验证。拥有 Bun 的开发机器也可直接 `bun install`、`bun run build`。

编译将 TypeScript、SQLite 与运行时一起放入可执行文件，Git 子进程参数不经过 shell。HTTP 服务保持响应，文件和 Git 操作在独立 Worker 中串行执行。

## 平台部署

沿用现有数据库执行 `alembic upgrade head`，设置 `LOCAL_RESOURCES_MODE=intranet`、`LOCAL_RESOURCES_ENCRYPTION_KEY=<Fernet key>`。默认允许私有 IPv4 与回环地址；可用 LOCAL_RESOURCES_ALLOWED_NETWORKS 配置内网范围。密钥必须备份，不能随意轮换。

资源身份与 journal 持久化；重复准备操作复用原 worktree。原仓库脏修改不会被覆盖。删除任务时保留脏 worktree，离线清理记录在个人设置重新检测后重试。补丁通过临时 Git index 生成；应用到独立 worktree。检查点按内容摘要保存文件，恢复时保留排除的依赖目录。

本次 TypeScript 服务使用版本 3 的 worktree 检查点格式；旧 Python 原型的检查点不自动转换，不应在仍需撤销的旧任务上直接替换状态目录。平台 HTTP 协议仍为 v1。

Electron 开发与构建只需 frontend 的现有 npm 工具链：`npm run build:electron:main` / `npm run build:electron`；无需先执行 Resource Host 独立构建。OpenCode 接入要求 2.x，使用 `/api/info`、`/api/event` 和 `/api/session`，不再回退旧版接口。
