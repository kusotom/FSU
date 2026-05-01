#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import shutil
import tarfile
import tempfile
from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def patch_ini_section(content: str, section: str, updates: dict[str, str]) -> str:
    lines = content.splitlines()
    out: list[str] = []
    in_target = False
    applied: dict[str, bool] = {key: False for key in updates}

    for idx, line in enumerate(lines):
        stripped = line.strip()
        is_section = stripped.startswith("[") and stripped.endswith("]")
        if is_section:
            if in_target:
                for key, done in applied.items():
                    if not done:
                        out.append(f"{key} = {updates[key]}")
                applied = {key: False for key in updates}
            in_target = stripped == section
            out.append(line)
            continue

        if in_target:
            replaced = False
            for key, value in updates.items():
                if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                    prefix = "" if "=" in line[: len(key) + 2] else ""
                    out.append(f"{key} = {value}")
                    applied[key] = True
                    replaced = True
                    break
            if replaced:
                continue
        out.append(line)

    if in_target:
        for key, done in applied.items():
            if not done:
                out.append(f"{key} = {updates[key]}")

    return "\n".join(out) + "\n"


def patch_disaster_ini(content: str, updates: dict[str, str], section_names: set[str] | None) -> str:
    lines = content.splitlines()
    out: list[str] = []
    current_section: str | None = None
    applied: dict[str, bool] = {}

    def should_patch(name: str | None) -> bool:
        if not name:
            return False
        if section_names is None:
            return True
        return name in section_names

    for line in lines:
        stripped = line.strip()
        is_section = stripped.startswith("[") and stripped.endswith("]")
        if is_section:
            if should_patch(current_section):
                for key, done in applied.items():
                    if not done:
                        out.append(f"{key}={updates[key]}")
            current_section = stripped[1:-1]
            applied = {key: False for key in updates}
            out.append(line)
            continue

        if should_patch(current_section):
            replaced = False
            for key, value in updates.items():
                if stripped.startswith(f"{key}="):
                    out.append(f"{key}={value}")
                    applied[key] = True
                    replaced = True
                    break
            if replaced:
                continue
        out.append(line)

    if should_patch(current_section):
        for key, done in applied.items():
            if not done:
                out.append(f"{key}={updates[key]}")

    return "\n".join(out) + "\n"


def patch_ppp_options(content: str, updates: dict[str, str]) -> str:
    lines = content.splitlines()
    out: list[str] = []
    applied: dict[str, bool] = {key: False for key in updates}

    for line in lines:
        stripped = line.strip()
        replaced = False
        for key, value in updates.items():
            if stripped.startswith(f"{key} "):
                out.append(f"{key} {value}")
                applied[key] = True
                replaced = True
                break
        if not replaced:
            out.append(line)

    for key, done in applied.items():
        if not done:
            out.append(f"{key} {updates[key]}")
    return "\n".join(out) + "\n"


def file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rebuild_tar_gz(source_dir: Path, tar_path: Path) -> None:
    with tarfile.open(tar_path, "w:gz") as tf:
        for item in sorted(source_dir.rglob("*")):
            arcname = item.relative_to(source_dir).as_posix()
            tf.add(item, arcname=arcname)


def parse_sections(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="为 eStoneII 升级包生成一份定制化批量接入版本。"
    )
    parser.add_argument("--input-dir", required=True, help="原始 eStoneII 升级包目录")
    parser.add_argument("--output-dir", required=True, help="输出的新升级包目录")
    parser.add_argument("--server-ip", required=True, help="主 server_ip / disaster_recovery_server_ip")
    parser.add_argument("--server-subnet", default="172.0.0.0/8")
    parser.add_argument("--l2tp-lns", required=True, help="主 LNS 地址")
    parser.add_argument("--l2tp-subnet", required=True, help="主 L2TP 子网，例如 10.45.0.0/16")
    parser.add_argument("--l2tp-lns-bak1", required=True, help="备 LNS 地址")
    parser.add_argument("--l2tp-bak1-subnet", required=True, help="备 L2TP 子网")
    parser.add_argument("--ppp-name", default="ttcw2015")
    parser.add_argument("--ppp-password", default="ttcw@2015")
    parser.add_argument(
        "--ttproxy-server",
        required=True,
        help="tt_proxy.ini 的 server= 值，支持逗号分隔多个 host:port",
    )
    parser.add_argument(
        "--disaster-sections",
        help="只改 disaster.ini 里的指定省份段，例如 51,52；默认修改全部段",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not input_dir.exists():
        raise SystemExit(f"input dir not found: {input_dir}")
    if output_dir.exists():
        raise SystemExit(f"output dir already exists: {output_dir}")

    shutil.copytree(input_dir, output_dir)

    outer_gprs_dir = output_dir / "modem" / "gprs_monitor"
    outer_ttproxy_ini = outer_gprs_dir / "tt_proxy.ini"
    outer_gprs_ini = outer_gprs_dir / "gprs_monitor.default.ini"
    outer_ppp_options = outer_gprs_dir / "options.l2tpd.client.tieta"

    gprs_updates = {
        "name": args.ppp_name,
        "password": args.ppp_password,
        "server_ip": args.server_ip,
        "subnet": args.server_subnet,
        "l2tp_lns": args.l2tp_lns,
        "l2tp_subnet": args.l2tp_subnet,
        "l2tp_lns_bak1": args.l2tp_lns_bak1,
        "l2tp_bak1_subnet": args.l2tp_bak1_subnet,
        "l2tp_lns_bak2": args.l2tp_lns,
        "l2tp_bak2_subnet": args.l2tp_subnet,
        "l2tp_lns_bak3": args.l2tp_lns_bak1,
        "l2tp_bak3_subnet": args.l2tp_bak1_subnet,
    }
    ttproxy_updates = {"server": args.ttproxy_server}
    ppp_updates = {"name": args.ppp_name, "password": args.ppp_password}
    disaster_updates = {
        "disaster_recovery_server_ip": args.server_ip,
        "disaster_recovery_subnet": args.server_subnet,
        "disaster_recovery_l2tp_lns": args.l2tp_lns,
        "disaster_recovery_l2tp_subnet": args.l2tp_subnet,
        "disaster_recovery_l2tp_lns_bak1": args.l2tp_lns_bak1,
        "disaster_recovery_l2tp_bak1_subnet": args.l2tp_bak1_subnet,
        "disaster_recovery_name": args.ppp_name,
        "disaster_recovery_password": args.ppp_password,
    }

    write_text(
        outer_ttproxy_ini,
        patch_ini_section(read_text(outer_ttproxy_ini), "[servers]", ttproxy_updates),
    )
    write_text(
        outer_gprs_ini,
        patch_ini_section(read_text(outer_gprs_ini), "[l2tp_tunnel0]", gprs_updates),
    )
    write_text(
        outer_ppp_options,
        patch_ppp_options(read_text(outer_ppp_options), ppp_updates),
    )

    tar_path = output_dir / "update.tar.gz"
    with tempfile.TemporaryDirectory() as tmp_dir:
        payload_dir = Path(tmp_dir) / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar_path, "r:gz") as tf:
            tf.extractall(payload_dir)

        payload_gprs_dir = payload_dir / "modem" / "gprs_monitor"
        write_text(
            payload_gprs_dir / "tt_proxy.ini",
            patch_ini_section(read_text(payload_gprs_dir / "tt_proxy.ini"), "[servers]", ttproxy_updates),
        )
        write_text(
            payload_gprs_dir / "gprs_monitor.default.ini",
            patch_ini_section(read_text(payload_gprs_dir / "gprs_monitor.default.ini"), "[l2tp_tunnel0]", gprs_updates),
        )
        write_text(
            payload_gprs_dir / "options.l2tpd.client.tieta",
            patch_ppp_options(read_text(payload_gprs_dir / "options.l2tpd.client.tieta"), ppp_updates),
        )
        disaster_sections = parse_sections(args.disaster_sections)
        disaster_path = payload_dir / "disaster.ini"
        write_text(
            disaster_path,
            patch_disaster_ini(read_text(disaster_path), disaster_updates, disaster_sections),
        )

        rebuild_tar_gz(payload_dir, tar_path)

    write_text(output_dir / "tar.md5", file_md5(tar_path) + "\n")

    print(f"patched package written to: {output_dir}")
    print(f"tar.md5 updated: {output_dir / 'tar.md5'}")
    print(f"tt_proxy server: {args.ttproxy_server}")
    print(f"l2tp lns: {args.l2tp_lns} / backup: {args.l2tp_lns_bak1}")
    if args.disaster_sections:
        print(f"disaster.ini sections updated: {args.disaster_sections}")
    else:
        print("disaster.ini sections updated: all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
