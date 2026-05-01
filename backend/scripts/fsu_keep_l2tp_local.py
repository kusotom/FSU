from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass

import requests


LOGGER = logging.getLogger("fsu-keep-l2tp-local")


@dataclass
class FSUConfig:
    base_url: str
    username: str
    password: str
    local_lns: str
    main_subnet: str
    vpn_subnet: str
    interval: int
    timeout: int


class FSUClient:
    def __init__(self, config: FSUConfig):
        self.config = config
        self.url = f"{config.base_url.rstrip('/')}/cgi-bin/web_main.cgi"
        self.headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}

    def _post(self, payload: str) -> str:
        response = requests.post(self.url, data=payload, headers=self.headers, timeout=self.config.timeout)
        response.raise_for_status()
        return response.text.replace("\r", "").replace("\n", "")

    def login(self) -> str:
        payload = (
            "commandid=0x0001&&resultCode=0&&sessionid=&&port=9528&&msgBody="
            f"{self.config.username}`{self.config.password}`0"
        )
        text = self._post(payload)
        parts = text.split("`")
        if len(parts) != 3:
            raise RuntimeError(f"unexpected login response: {text!r}")
        LOGGER.info("logged in as %s level=%s", parts[0], parts[2])
        return parts[1]

    def read_main_vpn(self, sessionid: str) -> str:
        return self._post(
            f"commandid=0x0050&&resultCode=0&&sessionid={sessionid}&&port=9528&&msgBody="
        )

    def set_main_vpn(self, sessionid: str) -> str:
        msg = "`".join(
            [
                self.config.local_lns,
                self.config.local_lns,
                self.config.main_subnet,
                "ttcw2015",
                "ttcw@2015",
                self.config.local_lns,
                self.config.main_subnet,
                self.config.local_lns,
                self.config.main_subnet,
                self.config.vpn_subnet,
                self.config.local_lns,
                self.config.main_subnet,
            ]
        )
        return self._post(
            f"commandid=0x0050&&resultCode=1&&sessionid={sessionid}&&port=9528&&msgBody={msg}"
        )

    def set_dr_vpn(self, sessionid: str) -> str:
        msg = "`".join(
            [
                self.config.local_lns,
                self.config.local_lns,
                self.config.main_subnet,
                "ttcw2015",
                "ttcw@2015",
                self.config.local_lns,
                self.config.main_subnet,
                "172.0.0.0/8",
            ]
        )
        return self._post(
            f"commandid=0x0050&&resultCode=23&&sessionid={sessionid}&&port=9528&&msgBody={msg}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Keep FSU L2TP server settings pinned to a local bait host")
    parser.add_argument("--base-url", default="http://192.168.100.100")
    parser.add_argument("--username", default="operator")
    parser.add_argument("--password", default="Enpc@2022")
    parser.add_argument("--local-lns", default="192.168.100.123")
    parser.add_argument("--main-subnet", default="10.0.0.0/8")
    parser.add_argument("--vpn-subnet", default="192.168.100.1/8")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def run_once(client: FSUClient) -> None:
    sessionid = client.login()
    before = client.read_main_vpn(sessionid)
    LOGGER.info("main vpn before: %s", before)
    result_main = client.set_main_vpn(sessionid)
    result_dr = client.set_dr_vpn(sessionid)
    after = client.read_main_vpn(sessionid)
    LOGGER.info("set main result=%s set dr result=%s", result_main, result_dr)
    LOGGER.info("main vpn after: %s", after)


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = FSUClient(
        FSUConfig(
            base_url=args.base_url,
            username=args.username,
            password=args.password,
            local_lns=args.local_lns,
            main_subnet=args.main_subnet,
            vpn_subnet=args.vpn_subnet,
            interval=args.interval,
            timeout=args.timeout,
        )
    )
    if args.once:
        run_once(client)
        return

    while True:
        try:
            run_once(client)
        except Exception as exc:  # pragma: no cover - device loop best effort
            LOGGER.exception("keepalive iteration failed: %s", exc)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
