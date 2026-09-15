<script setup lang="ts">
import { useRouter } from 'vue-router'
import { 
  ChevronLeft, Monitor, Server, Database, 
  Terminal, Workflow, Cpu,
  Layers, Globe, Lock,
  MessageSquareDiff, Settings, ServerCog, Code
} from 'lucide-vue-next'

const router = useRouter()
</script>

<template>
  <div class="arch-container">
    <!-- Header -->
    <header class="arch-header">
      <div class="back-btn" @click="router.push('/')">
        <ChevronLeft class="w-5 h-5" />
        <span>返回首页</span>
      </div>
      <h1 class="title">TraceForge 系统架构拓扑</h1>
      <div class="subtitle">Spec-Driven Development · 核心链路逻辑</div>
    </header>

    <!-- Diagram Area -->
    <main class="diagram-canvas">
      
      <!-- Layer 1: Portal UI -->
      <div class="layer-section">
        <div class="layer-header">
          <Monitor class="w-5 h-5" />
          <span>PLANTFORM PORTAL UI (VUE3 + VITE)</span>
        </div>
        <div class="node-grid">
          <div class="node-box portal">
            <Globe class="w-4 h-4" />
            <span>门户 & Chat 交互台</span>
          </div>
          <div class="node-box highlight-light">
            <MessageSquareDiff class="w-4 h-4" />
            <span>需求可视化块级评审 (Task Spec)</span>
          </div>
          <div class="node-box highlight-light">
            <Settings class="w-4 h-4" />
            <span>Skill Runtime 配置中心</span>
          </div>
          <div class="node-box dashboard">
            <Layers class="w-4 h-4" />
            <span>自动化资产与多维看板</span>
          </div>
        </div>
      </div>

      <!-- Connector to Mock Layer -->
      <div class="connection-pipe short">
        <div class="pipe-label">Vite Proxy 拦截</div>
      </div>

      <!-- Virtual Mock Layer (Node/Vite) -->
      <div class="layer-section virtual-mock">
        <div class="layer-header mock-header">
          <ServerCog class="w-5 h-5" />
          <span>CLIENT VIRTUAL SERVER (NODE.JS / VITE)</span>
        </div>
        <div class="node-row">
          <div class="node-box highlight-purple flex-1 justify-center">
            <Code class="w-4 h-4" />
            <span>API Mocking Workbench (契约预发布隔离与虚拟响应机制)</span>
          </div>
        </div>
      </div>

      <!-- Connector -->
      <div class="connection-pipe">
        <div class="pipe-label">WebSocket / REST API</div>
      </div>

      <!-- Layer 2: Backend -->
      <div class="layer-section backend">
        <div class="layer-header">
          <Server class="w-5 h-5" />
          <span>CORE BACKEND (FASTAPI)</span>
        </div>
        <div class="node-grid">
          <div class="node-box auth">
            <Lock class="w-4 h-4" />
            <span>JWT / RBAC 鉴权系统</span>
          </div>
          <div class="node-box engine">
            <Workflow class="w-4 h-4" />
            <span>SDD 状态机引擎</span>
          </div>
          <div class="node-box bridge">
            <Terminal class="w-4 h-4" />
            <span>PTY 桥接 / Agent Bridge</span>
          </div>
          <div class="node-box asset-svc">
            <Database class="w-4 h-4" />
            <span>Asset Svc / SQLAlchemy</span>
          </div>
        </div>
      </div>

      <!-- Connections Split -->
      <div class="split-connectors">
        <div class="connector-left"></div>
        <div class="connector-right"></div>
      </div>

      <!-- Layer 3: Storage & Execution -->
      <div class="layer-bottom">
        <div class="bottom-node storage">
          <div class="node-header">
            <Database class="w-4 h-4" />
            <span>STORAGE LAYER</span>
          </div>
          <div class="node-box">
            MySQL / sdd_platform
          </div>
        </div>

        <div class="bottom-node engine-cli">
          <div class="node-header">
            <Cpu class="w-4 h-4" />
            <span>EXECUTION ENGINE</span>
          </div>
          <div class="node-box highlight">
            Agent CLI + Superpowers
          </div>
        </div>
      </div>

    </main>

    <!-- Legend -->
    <footer class="arch-legend">
      <div class="legend-item">
        <div class="dot portal"></div>
        <span>前端视图层</span>
      </div>
      <div class="legend-item">
        <div class="dot backend"></div>
        <span>中枢调度层</span>
      </div>
      <div class="legend-item">
        <div class="dot storage"></div>
        <span>持久化与执行层</span>
      </div>
    </footer>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&display=swap');

.arch-container {
  min-height: 100vh;
  background: #f0f9ff;
  font-family: 'Outfit', sans-serif;
  color: #1e3a8a;
  padding: 4rem 2rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.arch-header {
  text-align: center;
  margin-bottom: 5rem;
  position: relative;
  width: 100%;
  max-width: 1000px;
}

.back-btn {
  position: absolute;
  left: 0;
  top: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: #0ea5e9;
  font-weight: 600;
  cursor: pointer;
}

.title {
  font-size: 2.25rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
}

.subtitle {
  color: #64748b;
  font-size: 1rem;
}

/* Diagram Canvas */
.diagram-canvas {
  flex: 1;
  width: 100%;
  max-width: 1000px;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.layer-section {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  padding: 1.5rem;
  box-shadow: 0 10px 25px -5px rgba(14, 165, 233, 0.1);
  position: relative;
  z-index: 2;
}

.layer-header {
  font-size: 0.75rem;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: 0.1em;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.node-row {
  display: flex;
  gap: 1rem;
  justify-content: space-around;
}

.node-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.node-box {
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  padding: 1rem;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.9375rem;
  font-weight: 600;
  transition: all 0.3s;
}

.node-box:hover {
  transform: translateY(-4px);
  border-color: #0ea5e9;
  box-shadow: 0 8px 16px -4px rgba(14, 165, 233, 0.2);
}

.node-box.highlight {
  background: #0ea5e9;
  color: white;
  border-color: #0284c7;
}

.node-box.highlight-light {
  background: #e0f2fe;
  color: #0369a1;
  border-color: #7dd3fc;
}

.node-box.highlight-purple {
  background: #f3e8ff;
  color: #7e22ce;
  border-color: #d8b4fe;
}

.virtual-mock {
  border-style: dashed;
  border-color: #c084fc;
  background: #faf5ff;
}

.mock-header {
  color: #9333ea;
}

.flex-1 { flex: 1; }
.justify-center { justify-content: center; }

/* Pipe */
.connection-pipe {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.connection-pipe.short {
  height: 40px;
}

.connection-pipe::before {
  content: '';
  position: absolute;
  width: 4px;
  height: 100%;
  background: linear-gradient(to bottom, #0284c7, #3b82f6);
  z-index: 1;
}

.pipe-label {
  background: white;
  padding: 0.25rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 700;
  color: #64748b;
  z-index: 2;
}

.split-connectors {
  height: 60px;
  position: relative;
  width: 100%;
}

.connector-left, .connector-right {
  position: absolute;
  top: 0;
  width: 25%;
  height: 100%;
  border-top: 4px solid #3b82f6;
}

.connector-left {
  left: 25%;
  border-left: 4px solid #3b82f6;
  border-top-left-radius: 12px;
}

.connector-right {
  right: 25%;
  border-right: 4px solid #3b82f6;
  border-top-right-radius: 12px;
}

/* Bottom Layer */
.layer-bottom {
  display: flex;
  justify-content: space-between;
  gap: 4rem;
  margin-top: -4px;
}

.bottom-node {
  flex: 1;
  background: white;
  border: 2px solid #3b82f6;
  border-radius: 20px;
  padding: 1.5rem;
}

.node-header {
  font-size: 0.8125rem;
  font-weight: 700;
  color: #3b82f6;
  margin-bottom: 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.arch-legend {
  margin-top: 5rem;
  display: flex;
  gap: 3rem;
  padding: 1.5rem 3rem;
  background: white;
  border-radius: 9999px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  color: #64748b;
  font-weight: 600;
}

.dot { width: 10px; height: 10px; border-radius: 50%; }
.dot.portal { background: #0ea5e9; }
.dot.backend { background: #3b82f6; }
.dot.storage { background: #1a1a1a; }
</style>
