import sys
import os
import argparse
from pathlib import Path
## 进入后端目录
#cd backend
# 列出所有账号
#python scripts/manage_users.py list
# 重置指定账号密码
#python scripts/manage_users.py reset-password test@example.com new_password_123
# 将项目根目录添加到 sys.path
backend_root = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_root))

from app.database import SessionLocal
from app.models.user import User
from app.services.auth_service import hash_password

def list_users():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        print(f"{'ID':<38} | {'Email':<30} | {'Display Name':<20}")
        print("-" * 95)
        for user in users:
            print(f"{user.id:<38} | {user.email:<30} | {user.display_name:<20}")
    finally:
        db.close()

def reset_password(email: str, new_password: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"Error: User with email '{email}' not found.")
            return

        user.hashed_password = hash_password(new_password)
        db.commit()
        print(f"Success: Password for '{email}' has been reset.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SDD Native Platform User Management CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # List command
    subparsers.add_parser("list", help="List all users")

    # Reset password command
    reset_pwd_parser = subparsers.add_parser("reset-password", help="Reset a user's password")
    reset_pwd_parser.add_argument("email", help="Target user's email")
    reset_pwd_parser.add_argument("new_password", help="The new password")

    args = parser.parse_args()

    if args.command == "list":
        list_users()
    elif args.command == "reset-password":
        reset_password(args.email, args.new_password)
    else:
        parser.print_help()
