"""Deliberately vulnerable example application; amounts are integer cents.

This is a demonstration target, not a claim about any TraceForge defect.
"""
def transfer(tx, source_id, target_id, amount):
    if source_id == target_id:
        raise ValueError("same_account")
    if amount <= 0:
        raise ValueError("invalid_amount")
    source_balance = tx.lock_account(source_id)
    target_balance = tx.lock_account(target_id)
    if source_balance < amount:
        raise ValueError("insufficient_funds")
    tx.set_balance(source_id, source_balance - amount)
    tx.set_balance(target_id, target_balance + amount)
