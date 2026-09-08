# TraceForge 后端镜像
# build context 必须是仓库根目录：
#   docker build -f deploy/docker/backend.Dockerfile -t traceforge-api .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app

# 运行时依赖：
#  - git     : 工作区仓库 clone / worktree / skill 的 git 集成
#  - nodejs  : Claude CLI 运行依赖
#  - curl/ps : 诊断与进程树回收（process_supervisor 用 psutil）
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates curl procps nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Claude CLI（Agent 编排要 spawn 本地子进程）
# 内网构建无外网时可加 --build-arg INSTALL_CLAUDE_CLI=false，改为运行时挂载
ARG INSTALL_CLAUDE_CLI=true
RUN if [ "$INSTALL_CLAUDE_CLI" = "true" ]; then \
        npm install -g @anthropic-ai/claude-code \
        && npm cache clean --force ; \
    else echo "skip claude cli" ; fi

WORKDIR ${APP_HOME}

# wexpect 是 Windows-only（依赖 pywin32），Linux 下必然装失败；
# 且全仓库 grep 业务代码无 wexpect 引用，仅 requirements 残留 —— 构建时剔除。
COPY backend/requirements.txt /tmp/requirements.raw.txt
RUN grep -v -E '^[[:space:]]*(wexpect)' /tmp/requirements.raw.txt > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend/alembic.ini ${APP_HOME}/alembic.ini
COPY backend/alembic ${APP_HOME}/alembic
COPY backend/app ${APP_HOME}/app

# 运行态目录（由 compose 挂卷持久化，见 docker-compose.yml）
RUN mkdir -p ${APP_HOME}/storage/skills \
             ${APP_HOME}/uploads \
             ${APP_HOME}/tmp/api_mock_workspace \
             ${APP_HOME}/tmp/cli_state \
             ${APP_HOME}/tmp/workspace_archive \
             ${APP_HOME}/logs/ai_sessions

EXPOSE 8000

# 单 worker 是硬性约束：进程内运行态 + CLI 会话状态不可跨副本共享
# （README「部署说明」第 1 条）。不要改成 --workers > 1，也不要靠 compose 扩副本。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
