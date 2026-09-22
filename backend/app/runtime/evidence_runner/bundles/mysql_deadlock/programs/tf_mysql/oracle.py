"""Frozen predicates over controller-owned SQL traces, never target PASS text."""
def complete(batch):
    rows = batch.get("requests", [])
    return (len(rows) == batch.get("requested_count") and bool(rows)
            and all(r.get("completed") is True and r.get("exit_code") == 0
                    and not r.get("harness_error") for r in rows))


def target_failed(batch):
    return (complete(batch) and batch.get("correlated_lock_cycle") is True
            and any(1213 in row.get("errors", []) and row.get("outcome") == "error" and not row.get("committed") for row in batch["requests"]))


def request_effect_matches(row):
    request, before = row["request"], row.get("reads", {})
    source, target, amount = str(request["source_id"]), str(request["target_id"]), request["amount"]
    if source == target or amount <= 0 or source not in before or target not in before:
        return False
    operations = row.get("operations", [])
    expected = {source: before[source] - amount, target: before[target] + amount}
    return len(operations) == 2 and {str(op["account_id"]): op["balance"] for op in operations} == expected


def balances_match(batch):
    expected = {"1": 1000, "2": 1000}
    for row in batch.get("requests", []):
        if row.get("committed"):
            request = row["request"]
            source, target, amount = request["source_id"], request["target_id"], request["amount"]
            if source == target or amount <= 0:
                return False
            expected[str(source)] -= amount
            expected[str(target)] += amount
    return batch.get("balances") == expected and all(v >= 0 for v in expected.values())


def target_passed(batch):
    return (complete(batch) and balances_match(batch)
            and all(r.get("committed") and r.get("outcome") == "success" and not r.get("errors")
                    and set(r.get("acquired", [])) == {1, 2}
                    and {op["account_id"] for op in r.get("operations", [])} == {1, 2}
                    and request_effect_matches(r)
                    for r in batch["requests"]))


def ordered(batch):
    return all(r.get("locks") == sorted(set(r.get("locks", []))) and bool(r.get("locks"))
               for r in batch.get("requests", []))


def regressions_passed(reports):
    expected = {"same_account", "insufficient_funds", "invalid_amount", "valid_transfer"}
    if set(reports) != expected:
        return False
    for name, batch in reports.items():
        if not complete(batch) or not balances_match(batch) or len(batch["requests"]) != 1:
            return False
        row = batch["requests"][0]
        if name == "valid_transfer":
            if not target_passed(batch):
                return False
        elif row.get("committed") or row.get("outcome") != "error" or row.get("target_error") != name or row.get("errors"):
            return False
    return True


def hypothesis_decisions(report):
    concurrent = report.get("concurrent", {})
    sequential = report.get("sequential", {})
    physical = target_failed(concurrent) and target_passed(sequential)
    statuses = "\n".join(r.get("deadlock_status", "") for r in concurrent.get("requests", []))
    decisions = []
    for hypothesis in report.get("hypotheses", []):
        branch = report.get("branches", {}).get(hypothesis["id"])
        if branch is not None:
            concurrent = branch.get("concurrent", {})
            sequential = branch.get("sequential", {})
            physical = target_failed(concurrent) and target_passed(sequential)
            statuses = "\n".join(r.get("deadlock_status", "") for r in concurrent.get("requests", []))
        script = hypothesis.get("discriminator_script")
        state = "INCONCLUSIVE"
        if script == "builtin:mysql-deadlock/lock_order" and physical:
            state = "SUPPORTED"
        elif script == "builtin:mysql-deadlock/pool_wait" and physical and all(
                r.get("connection_id") for r in concurrent.get("requests", [])):
            state = "REFUTED"
        elif script == "builtin:mysql-deadlock/range_lock" and physical and "locks rec but not gap" in statuses:
            state = "REFUTED"
        decisions.append({"id": hypothesis["id"], "state": state, "scenario": script,
                          "branch_id": hypothesis["id"], "fixture_refs": [concurrent.get("table"), sequential.get("table")],
                          "reason": "独立连接、主键等值取锁与数据库 1213 的同次实验对照；结论限定于绑定应用入口。"})
    return decisions


def facts(report):
    phase = report["phase"]
    if phase == "PROBE":
        probe = report["probe"]
        return {"probe.connection_ok": probe.get("connection_ok") is True,
                "probe.correlated_samples": int(probe.get("correlated_samples", 0)),
                "probe.lock_or_error_artifact_refs": ["probe.json"] if probe.get("correlated_samples") else []}
    if phase == "HYPOTHESIZE":
        decisions = hypothesis_decisions(report)
        return {"hypotheses.has_discriminating_physical_evidence": any(d["state"] == "SUPPORTED" for d in decisions),
                "hypotheses.required_conflicts_resolved": len(decisions) >= 2 and all(d["state"] in {"SUPPORTED", "REFUTED"} for d in decisions)}
    if phase == "REPRODUCE":
        baseline = report["baseline"]
        reproduced = target_failed(baseline)
        return {"tests.target_node_collected": complete(baseline), "tests.target_failure": "TransferDeadlockAssertion" if reproduced else "",
                "tests.collected": len(baseline.get("requests", [])), "tests.errors": sum(bool(r.get("harness_error")) for r in baseline.get("requests", [])),
                "database.error_code": 1213 if reproduced else 0,
                "database.correlated_lock_cycle": baseline.get("correlated_lock_cycle") is True,
                "oracle.matches_observed_symptom": reproduced and report.get("observed_error_code") == 1213}
    baseline, patch = report["baseline"], report["patch"]
    return {"comparison.baseline_target_failed": target_failed(baseline),
            "comparison.patch_target_passed": target_passed(patch),
            "comparison.oracle_digest_equal": report.get("baseline_oracle_digest") == report.get("patch_oracle_digest") and bool(report.get("baseline_oracle_digest")),
            "comparison.environment_equal_except_patch": report.get("baseline_environment_digest") == report.get("patch_environment_digest") and bool(report.get("baseline_environment_digest")),
            "comparison.expected_tests_collected": complete(baseline) and complete(patch) and baseline["requested_count"] == patch["requested_count"] == report.get("parallel_clients"),
            "comparison.regression_passed": regressions_passed(report.get("regressions", {})),
            "comparison.balance_conserved": balances_match(baseline) and balances_match(patch),
            "comparison.request_coverage_complete": complete(patch) and patch.get("requested_count") == report.get("parallel_clients"),
            "comparison.lock_order_consistent": ordered(patch)}
