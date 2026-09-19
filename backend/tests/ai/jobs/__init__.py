"""AI job（app.domains.ai.services.jobs 子包）测试。

模块清单：
- ai_job_test_utils —— SessionLocal 聚合 patch 与共享 job 构造器；
- test_ai_job_convergence_evidence / running_cancel / remote_convergence /
  adapter_protocol —— 原 test_ai_job_convergence.py 按业务边界拆分；
- test_ai_job_claim_recovery / ownership / runtime_workers / state_machine /
  cli_evidence —— 原 test_ai_job_reliability.py 按业务边界拆分。
"""
