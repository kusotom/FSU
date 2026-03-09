from pathlib import Path
import sys

from sqlalchemy import select

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from app.db.session import SessionLocal  # noqa: E402
from app.models.notify import NotifyChannel, NotifyPolicy  # noqa: E402


def _normalized_channel_name(channel: NotifyChannel) -> str | None:
    raw = str(channel.name or "").strip()
    if channel.channel_type == "pushplus" and ("?" in raw or raw == "PushPlus??"):
        return "PushPlus微信"
    if channel.channel_type == "webhook" and (raw == "????" or raw == "__dup_test__"):
        return f"测试Webhook通道{channel.id}"
    return None


def _normalized_policy_name(policy: NotifyPolicy) -> str | None:
    raw = str(policy.name or "").strip()
    if "?" in raw and raw.startswith("PushPlus"):
        return "PushPlus默认策略"
    if raw.isdigit():
        return "测试通知策略"
    return None


def main():
    session = SessionLocal()
    try:
        changed = []

        channels = list(session.scalars(select(NotifyChannel).order_by(NotifyChannel.id.asc())).all())
        for channel in channels:
            new_name = _normalized_channel_name(channel)
            if new_name and new_name != channel.name:
                changed.append(("channel", channel.id, channel.name, new_name))
                channel.name = new_name

        policies = list(session.scalars(select(NotifyPolicy).order_by(NotifyPolicy.id.asc())).all())
        for policy in policies:
            new_name = _normalized_policy_name(policy)
            if new_name and new_name != policy.name:
                changed.append(("policy", policy.id, policy.name, new_name))
                policy.name = new_name

        session.commit()

        print(f"changed_count={len(changed)}")
        for kind, item_id, old, new in changed:
            print(f"{kind}#{item_id}: {old!r} -> {new!r}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
