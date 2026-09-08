# TraceForge 前端（Web 模式）镜像：Vite 构建 + Nginx 静态托管
# build context 必须是仓库根目录：
#   docker build -f deploy/docker/frontend.Dockerfile -t traceforge-web .
FROM node:22-alpine AS build

WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Web 模式构建产物 = dist/（Electron 相关产物不参与本次构建）
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /src/dist /usr/share/nginx/html
COPY deploy/docker/nginx/default.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
