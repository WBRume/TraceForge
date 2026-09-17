"""Workspace Asset 服务层。

按业务子域组织（依赖方向自上而下，禁止反向；守护测试见
``tests/test_workspace_asset_structure.py``）::

    common/                    共享内核：领域错误、值助手、过程资产展示器
    requirements/              Requirement 子域（读/写/导入确认/文档分段）
      preview/                 Requirement AI preview 作业（prompt/作业服务/三段式 runner）
    tasks/                     Task 资产视角（摘要展示器/详情/列表/轻量摘要/分节查询）
    task_process/              Task 过程资产写边界（Review/Delta/Evidence/Decision/Clarification）
    task_final_workflow/       终审工作流（评审/澄清/终审总结/基线/工作流状态）
    traceability.py            追溯视图与覆盖矩阵（覆盖状态机唯一归属）
    overview.py                工作区资产总览与知识资产列表
    human_delta_compare_service.py  Human Delta 对比引擎（叶子模块）

跨域约定：
- 展示器（模型 → Response）只存在于 ``common.process_presenters`` 与各子域
  ``presenters``，查询与写入函数不得内联构建 Response；
- ``common.primitives.is_human_confirmation`` / ``coverage_status`` 是
  Verified coverage 的唯一判定来源；
- 领域业务错误统一为 ``common.errors.WorkspaceAssetError``（message +
  status_code，路由层翻译为 HTTPException）。
"""
