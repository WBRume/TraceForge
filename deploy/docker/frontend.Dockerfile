# TraceForge 前端（Web 模式）镜像：Vite 构建 + Nginx 静态托管
# build context 必须是仓库根目录：
#   docker build -f deploy/docker/frontend.Dockerfile -t traceforge-web .
FROM node:22-alpine AS build

ENV ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ \
    ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/ \
    npm_config_registry=https://registry.npmmirror.com

WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --legacy-peer-deps

COPY frontend/ ./
# Web 模式构建产物 = dist/（跳过 vue-tsc 类型检查，直接 vite build）
RUN npx vite build

FROM nginx:1.27-alpine

COPY --from=build /src/dist /usr/share/nginx/html
COPY deploy/docker/nginx/default.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
