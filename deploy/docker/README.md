# Docker 部署

[项目首页](../../README.md) · [全部文档](../../README.md#文档导航) · [后端配置](../../backend/README.md) · [搜索部署](../search/README.md)

本目录的 Compose 启动 MySQL、Redis、单进程 API 和 Nginx Web，并在 API 启动前执行数据库迁移。它不包含桌面客户端，适合内部试用部署。

## 首次启动

安装并启动 Docker Engine / Docker Desktop 与 Compose 插件。从仓库根目录执行：

```powershell
cd deploy/docker
Copy-Item .env.example .env
```

编辑 [配置模板](.env.example) 对应的 `.env`：

- 替换 `JWT_SECRET_KEY`；设置数据库密码，保持 `MYSQL_ROOT_PASSWORD` 与 `DB_PASSWORD` 一致。
- 保持 `MYSQL_DATABASE` 与 `DB_NAME` 一致；按需配置 Redis 密码。
- 本机默认 `WEB_PORT=8080`。远程部署时，把 `FRONTEND_BASE_URL` 和 `CORS_ORIGINS` 改为实际访问地址。
- 配置准备使用的 [Agent](../../backend/README.md#配置-agent)。远端地址必须能从 API 容器访问；访问宿主机服务时使用部署环境可达的宿主机地址。

```powershell
docker compose up -d --build
docker compose ps -a
docker compose logs --tail=100 migrate api
```

确认 `migrate` 以退出码 0 完成，`api` 为 healthy，再打开 [本地 Web 页面](http://localhost:8080)。首个注册账号是管理员，可进入系统配置检查 Agent、搜索等能力。

## Agent 连接

后端镜像默认安装 Claude Code CLI，但安装 CLI 不等于已完成授权。使用 Claude Code 时，按其授权方式配置 API Key，或在容器中交互式完成登录：

```powershell
docker compose exec api claude
```

Compose 将 `/root/.claude` 挂载到本地 `volumes/claude/`。需要其他凭据或配置文件时，应根据实际认证方式补充环境变量或挂载。

OpenCode 与 DSH 服务需另外准备；在系统配置或 `.env` 中填写地址与认证信息。工作区克隆私有仓库还需要为 API 容器提供相应 Git 凭据，SSH 挂载示例见 [Compose 文件](docker-compose.yml)。

## 配置与数据

- `.env` 保存部署环境配置；修改后用 `docker compose up -d --force-recreate api` 重新创建 API 容器，单纯 `restart` 不会更新环境变量。
- `volumes/` 保存 MySQL、Redis、Skills、上传文件、任务与 CLI 状态、日志和已挂载的凭据。升级前备份数据库、运行数据及配置密钥。
- API 保持一个进程、一个副本；不要增加 `--workers` 或扩展 `api` 副本。
- 默认使用轻量搜索，无需启动 Elasticsearch。语义检索、回填和可选的独立 worker 见[搜索部署](../search/README.md)。
- Web 语音模式通过构建参数 `TRACEFORGE_SPEECH_MODE` 选择，运行服务的在线语音供应商另行配置，见[语音说明](../../frontend/README.md#语音输入构建时选择-api--离线--关闭)。

## 更新与排错

更新代码后重新执行 `docker compose up -d --build`，确认本次迁移成功后再使用。检查服务时可执行：

```powershell
docker compose ps -a
docker compose logs --tail=100 mysql redis migrate api web
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').read().decode())"
```

数据库连接失败先核对数据库名与密码；Agent 失败先核对容器内的授权及远端网络连接。更多检查见[后端常见问题](../../backend/README.md#常见问题)。
