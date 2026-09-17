"""AI 异步作业（SddAiJob）运行时子包。

模块分层（依赖单向，自上而下）：

- ``constants``      状态集合、作业类别、队列键等共享词汇
- ``registry``       进程内运行时：worker 身份、取消信号、心跳任务、队列 runner、关停标志
- ``store``          SddAiJob 持久层（同步 DB 段 + run_db 包装）
- ``fencing``        带 run-token fence 的状态写入（CAS 与终态 convergence 转交）
- ``attempts``       attempt 绑定/证据解析/终止收敛与取消入口
- ``state``          异步状态推进（写库 + 广播 + 调度）
- ``publishing``     作业负载的 WS 广播与入队入口
- ``provider_turn``  CLI/远程后端单回合执行器
- ``reaper``         孤儿作业回收（扫描/收养/停止）
- ``workers``        reaper/dispatcher 常驻 worker 与健康遥测
- ``queue_runner``   队列 runner：认领 → 绑定 attempt → 执行 → 收敛收尾
- ``executors``      按作业族划分的执行器（asset_thread / task_chat / diagnosis_summary / task_baseline）

外部调用方应按需从具体模块导入，不经过本包 ``__init__`` 转发。
"""
