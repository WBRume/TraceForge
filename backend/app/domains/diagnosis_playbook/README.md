# 故障诊断规程实现与启用

## 日常业务入口

1. 在案例详情点击“晋升为诊断规程”：服务端保存现象、调用链、分析过程、证据链、根因和解决方案的快照，生成可立即复用的分析规程版本，无需填写 YAML 或部署实验环境。同一案例内容重复晋升返回同一版本；内容变化生成新版本。
2. 在“新建任务”中选择问题定位类型并填写标题与现象（诊断规程仅问题定位任务可选，研发态任务不提供该入口；后端同样拒绝研发态绑定规程），点击“诊断规程”展开与 Skills/仓库互斥的侧栏，展开后才请求推荐。支持服务端分页（默认每页 8 项）和名称、症状、调用链搜索，翻页/搜索/关闭侧栏保留已选项。推荐依据标题、症状、错误标识和历史上下文的文本匹配，并展示匹配原因，不宣称模型语义评分。
3. 所选规程随任务创建事务一起绑定；任务仍保持用户选择的类型。绑定固定版本、摘要、调用链和排查步骤，后续案例修改不影响已创建任务。未选择规程的任务沿用原流程，推荐服务失败也不会阻止创建。
4. 普通 Agent 回合自动携带规程分析上下文；会话顶部显示已选规程。分析指引不启动物理 Worker，不要求 fixture，不生成物理验证回执。
5. 四阶段工作台默认采用人工审核；点击“确认并进入下一阶段”会将下一阶段持久化入队并自动执行，无需再发送消息。“自动执行全流程”开关内联在阶段工具栏中，位于“确认并进入下一阶段”左侧；打开后服务端在回合成功收尾时检查阶段条件、记录自动决策并衔接下一阶段，关闭页面不影响执行。主开关在两处任务级入口提供：新建问题定位任务表单与启动引擎确认弹窗（仅绑定规程的任务显示），写入任务元数据 `sop_auto_run`，新会话以其初始化自动执行；会话内手动开关仅在当前会话生效。假说阶段必须提供有当前证据支持的 `root_cause_hypothesis_id`；证据不足、缺少明确根因、未实际观察复现/回归结果或执行失败时暂停。关闭开关不打断当前回合，但结束后不再自动推进。每一步仍是普通消息提交、checkpoint 和作业，可使用既有恢复机制；不将模型报告标记为物理验证回执。
6. 每个假说用 `verdict`（`UNTESTED` / `SUPPORTED` / `REFUTED` / `INCONCLUSIVE`）和 `verdict_reason` 表达分析判定，独立于人工确认/排除状态。非待验证判定必须携带本次证据与理由。已证伪的假说展示判定依据，不提供确认根因入口；人工和自动模式均只允许有证据支持的假说成为根因。后续判定改变会撤销旧确认。旧报告缺少判定字段时显示待验证，不从聊天关键词或证据是否为空猜测结论。

规程库负责管理、导入和查看来源；已移除库内手填任务 ID/环境的“发起排查”入口。分析规程使用 `execution.mode=ANALYSIS_GUIDE`；旧物理规程也可在任务创建时仅复用其排查步骤，不自动运行实验。已有物理执行 API 保留，但不接受分析规程作为 Runner 输入。

## 执行链路

案例中心的规程库保存不可变版本。定位任务绑定规程后，由独立 Worker 通过共享 `TaskAgentEngine` 的可选 execution profile 调用 Provider；普通任务不加载规程状态。默认软门禁通过普通 Agent 回复中的结构化候选提交假说、实验和补丁，不需要额外插件、守卫端口、Bearer ticket 或 MCP 白名单。四个物理验证阶段的推进仍只接受 EvidenceRunner 产生的回执。

当前小团队上传日志、粘贴堆栈、描述现象的使用方式继续走普通定位会话，不要求绑定物理规程、配置 fixture 或部署守卫。Agent 分析和经验沉淀沿用已有诊断/案例入口；分析结论不自动升级为技术验证案例。下面的 MySQL fixture 配置只用于主动选择物理复现闭环的任务。

引擎按 `(task_id, scope_id)` 注册。假说采用有界顺序队列，每个假说使用独立的 Provider scope、上下文 anchor、候选记录和数据库 fixture；共享的基线只读。当前适配器没有认证原生 fork 的 cwd 重绑定，因此调度器使用 anchor 重建分支上下文。控制接口保留 eager/deferred fork 协议，但不把它的存在当作已经实测的能力。

进程意图先持久化，再启动受监管进程树。未知执行不重派；租约失效后先确认旧进程树死亡或远端 session 停止。Runner 的收集或准备失败生成 ERROR 回执。确认死亡后的取消、继续、输入替换，以及人工排除/恢复假说均带版本检查和幂等键。心跳续租不改变用户命令的状态版本。

完成后创建技术验证 revision，保留现有人工作品。新自动案例标记 `archive_origin=PLAYBOOK`、`TECHNICALLY_VERIFIED`，不产生人工采纳记录。多个关联案例必须明确选择归档目标。案例详情可提炼候选、编辑、校验、保存新规程版本；没有对应物理适配器的候选保留 unresolved 字段，不会伪装成可运行规程。

## 启用

应用数据库需要先执行增量迁移 `b7d91a36c204`，它接续现有 Alembic head，不重置历史数据。本次实现没有自动迁移开发数据库。

后端配置：

```dotenv
DIAGNOSIS_PLAYBOOK_ENFORCEMENT_LEVEL=ADVISORY_GUARD
DIAGNOSIS_PLAYBOOK_WORKER_ENABLED=true
DIAGNOSIS_PLAYBOOK_EVIDENCE_ROOT=G:/traceforge-runtime/evidence
DIAGNOSIS_PLAYBOOK_TOOL_URL=http://127.0.0.1:8000/api/playbook-tools
DIAGNOSIS_PLAYBOOK_MYSQL_ENVIRONMENTS_FILE=G:/traceforge-runtime/mysql-environments.json
```

部署参数支持三档，修改后重启后端生效：

| 配置值 | 行为与依赖 |
| --- | --- |
| `ADVISORY_GUARD`（默认） | 提示约束 + 普通 Agent 原有工具 + 结构化回复。不探测 DSH 插件/4198，不要求专属 Host，不安装 MCP 或工具白名单。不是强隔离。 |
| `WORKTREE_BROKER` | 要求环境实际认证工作树隔离与匹配的 Backend Host；启用严格工具路径，DSH 需要守卫插件。 |
| `CONTAINER_SANDBOX` | 为后续 K8s 专属环境保留。要求环境实际认证容器隔离与 Backend Host；当前内置本机 bundle 不提供此能力。 |

非法配置会在启动时校验失败。选择强策略而部署能力不足时返回 `SOP_CONFIGURED_ENFORCEMENT_UNAVAILABLE`，不会静默降为建议级；需要降阶时显式修改此参数。原有 Provider 的登录/连接鉴权不受影响。

软门禁在回复末尾接收单个 `traceforge-playbook` JSON 代码块，内容为 `{"proposals":[{"name":"propose_patch","arguments":{"files":{"transfer.py":"完整候选源码"}}}]}`。平台复用候选校验和阶段约束；格式错误进入待补充状态，可继续重试。模型无法通过这个格式提交回执或宣称 PASS。额外 MCP 接口仍保留给强策略，但建议级不签发有效工具 ticket。

### 守护策略对比与 ADVISORY_GUARD 深度解读

#### 1. 三档守护策略梯度对比

| 守护策略 | 输入端防护方式 | 输出端准出依据 | 依赖外部基础设施 | 适用场景与阶段定位 |
| :--- | :--- | :--- | :--- | :--- |
| **`ADVISORY_GUARD`（建议级/默认）** | 提示词协议软规约（System Prompt 注入阶段权限要求与输出 Schema） | 平台独立执行器出具的真机物理凭据（Sealed Evidence） | 普通 Agent 原生环境，无需特殊插件或容器支持 | **当前开发态、日常日志排查、代码分析阶段的首选**（零部署门槛） |
| **`WORKTREE_BROKER`（工作树级）** | Git Worktree 独立分支文件物理隔离 + DSH 插件拦截非白名单系统调用 | 同上 | 本地 Git 工作树、认证的 Backend Host、DSH 守卫插件 | 团队级受限环境，需要防止 Agent 意外改写本地源码基线 |
| **`CONTAINER_SANDBOX`（容器级）** | K8s Pod / Docker 容器 Namespace、虚拟网络、只读根文件系统强隔离 | 同上 | Kubernetes 集群、容器运行时、专用动态调度器 | **后续生产级 AIOps / 云上自动化诊断环境**（具备完整基础设施时） |

## 内置 MySQL 实验边界

内置 bundle 支持 MySQL 8/9 与一个明确的 Python 应用事务端口：

```python
def transfer(tx, source_id, target_id, amount):
    # amount 和 balance 为整数分；tx 操作真实 InnoDB 独立连接。
    balance = tx.lock_account(source_id)
    tx.set_balance(source_id, balance - amount)
```

实际应用入口在独立子进程中运行，完整基线示例在 `../../runtime/evidence_runner/bundles/mysql_deadlock/example_app/transfer.py`（相对本目录需向上回到 app）。其他应用应通过受审查的事务端口适配接入，不能用这个示例替代真实应用后宣称证明了其根因。当前内置控制器运行于本机 OS 身份，报告 **ADVISORY_GUARD**，规程和每次 Run 都必须明确允许；它不声称提供容器级隔离。

观察连接只运行 SELECT/SHOW；变更只发生在单独的 `tf_playbook_*` fixture 数据库。数据库应预先存在，fixture 账户需要其上的建表、读写、删表权限及采集死锁状态所需权限。不能将业务数据库作为 fixture。每个分支/批次创建独立随机表，正常结束和已确认死亡的恢复路径只清理本次 execution 所有的表。

受管环境文件样例（凭据只引用后端进程环境变量）：

```json
{
  "work_root": "G:/traceforge-runtime/mysql-runs",
  "environments": {
    "mysql-demo": {
      "workspace_ids": ["<workspace-id>"],
      "target_operation": "transfer:transfer",
      "source_snapshot": {"ref": "snapshot:transfer-v1", "path": "G:/snapshots/transfer-v1", "digest": "sha256:<tree-manifest-digest>"},
      "observation_connection": {"ref": "connection:observation", "host": "127.0.0.1", "port": 3306, "user": "observer", "database": "observed_database", "table": "accounts", "password_env": "PLAYBOOK_OBSERVER_PASSWORD"},
      "fixture_template": {"ref": "fixture:transfers", "host": "127.0.0.1", "port": 3306, "user": "fixture_runner", "database": "tf_playbook_fixture", "password_env": "PLAYBOOK_FIXTURE_PASSWORD"},
      "observed_error_sample": {"ref": "artifact:incident", "path": "G:/incidents/incident.json", "digest": "sha256:<file-digest>"}
    }
  }
}
```

源码摘要使用 `digest(tree_manifest(path))`，由 `bundles.mysql_deadlock.files` 提供；不是 Git commit ID。错误样本包含 `error_code:1213`、`table`、Unix `captured_at` 和参与请求的 `connection_ids`，并与只读采集的 InnoDB 最近死锁对应。缺少同次请求关联、样本超出时间窗口、导入失败、超时或零测试均不会作为成功复现。

源码、输入、运行时、fixture、判别器和样本摘要绑定到回执。补丁仅可修改已有应用 Python 文件；测试、依赖、配置、oracle、证据存储不能通过提案修改。目标并发请求全部完成、主键全序取锁、余额与提交结果一致，以及同账户/余额不足/无效金额/有效转账回归均参与补丁判定。

内置程序提供三个已注册判别引用：`builtin:mysql-deadlock/lock_order`、`builtin:mysql-deadlock/pool_wait`、`builtin:mysql-deadlock/range_lock`。模型提出可证伪假说并选择对应实验，不能替换判别器代码。实验候选单独冻结留档。

只有强策略才要求 DSH 在 Run 专属 Host 加载 `integrations/dsh-playbook` 插件、OpenCode 在专属 Host 安装本次 MCP，以及 Claude 使用严格 MCP 配置。默认建议级不启用这些路径，也不报告为强隔离。

## 验证

```powershell
cd G:/proj/TraceForge/backend
python -m pytest tests/diagnosis_playbook -q
$env:TRACEFORGE_MYSQL_PLAYBOOK_LIVE='1'
python -m pytest tests/diagnosis_playbook/test_mysql_bundle.py -q
```

显式启用的真实 MySQL 测试从现有后端设置读取连接，创建两个 UUID 命名的 `tf_playbook_test_*` 数据库并在 finally 中删除它们，不访问业务表。测试包括真实应用死锁、四阶段受监管 Runner，以及固定模型替身驱动的 engine/profile/MCP/Worker/Case 全链路。固定模型替身测试不能证明真实 Provider 的模型行为或隔离强度。

真实 Claude、DSH、OpenCode 端到端模型调用、强隔离部署和浏览器实际交互仍需环境验收。前端类型检查、构建和 Vitest 与后端/数据库验证分别报告。
