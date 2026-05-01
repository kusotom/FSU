# FSU-2808IM Stage Summary - 2026-04-30

This document freezes the current FSU-2808IM integration and reverse-analysis state as of 2026-04-30. It is a project stage summary, not a confirmed production protocol specification.

## Scope And Safety Boundary

- Current work is read-only by default.
- Online ACK and automatic reply behavior are not enabled.
- `fsu-gateway` reply logic is not changed by this stage.
- Raw packet analysis reads only `backend/logs/fsu_raw_packets/*.jsonl` and generated read-only reports.
- ACK-related scripts remain offline modeling or historical experiment tools unless an explicit manual experiment is approved.

## Current Topology

- Device IP: `192.168.100.100`
- Platform IP: `192.168.100.123`
- Platform listeners:
  - UDP DSC receive: `9000`
  - UDP RDS receive: `7000`
  - HTTP platform service: `8000`
- Observed device source ports:
  - UDP_DSC: `6000`, `6002`, `6003`, `6005`
  - UDP_RDS: `6001`

The DSC source port changes over time. Any future controlled experiment must select the current latest raw log and the current latest `DSC_CONFIG_209/245` source port.

## Identified Frame Classes

| frameClass | Protocol | Length | typeA | Notes |
| --- | --- | ---: | --- | --- |
| `DSC_SHORT_24_TYPE_1F00_D2FF` | `UDP_DSC` | 24 | `1f00d2ff` | Short DSC frame; checksum behavior differs from long frames. |
| `RDS_SHORT_30_TYPE_1180_D2FF` | `UDP_RDS` | 30 | `1180d2ff` | RDS short frame. |
| `DSC_CONFIG_209_TYPE_1100_46FF` | `UDP_DSC` | 209 | `110046ff` | Config/service-address long frame with URI strings. |
| `DSC_CONFIG_245_TYPE_1100_46FF` | `UDP_DSC` | 245 | `110046ff` | Config/service-address long frame with explicit URI strings. |

## Recovered Frame Layout

| Offset | Field | Current Understanding |
| --- | --- | --- |
| `0..1` | SOI | Confirmed `6d7e`. |
| `2..3` | `seqLE` | Little-endian sequence; response validation not strongly confirmed. |
| `4..7` | `typeA` | Command/type bytes. Login response candidate is `110047ff`, confidence medium. |
| `8..19` | Header context | Common candidate `00000000c162002d00000000`; mirror latest request remains conservative strategy. |
| `20..21` | `lengthLE` | Little-endian body length, equals `totalLength - 24`. |
| `22..23` | `checksumLE` | Little-endian checksum. |
| `24..` | body | Body starts at `frame + 0x18`. |

Checksum for long config and RDS short classes:

```text
uint16 sum(buffer[2..totalLen-1]), with bytes 22..23 zeroed before summing
```

`DSC_SHORT_24_TYPE_1F00_D2FF` does not satisfy the same formula and should not be used as the source for ACK construction.

## DSC_CONFIG URI Structure

The `DSC_CONFIG_209/245` frames contain visible URI-like ASCII values such as:

- `udp://192.168.100.100:6000`
- `udp://192.168.100.100:6002`
- `udp://[dhcp]:6002`
- `udp://[dhcp]:6003`
- `ftp://root:hello@192.168.100.100`
- `ftp://root:hello@[dhcp]`

The observed long-frame repetition indicates the device is repeatedly requesting or advertising service address configuration.

## Login Response Candidate Body

Static reverse engineering of `SiteUnit` identified the login status handler around `0x7e804`.

Current candidate structure:

```text
body[0]    = status
             0: Success
             1: Fail
             2: UnRegister
body[1..2] = entryCount uint16LE

repeated entry:
  fieldId     uint8
  valueLength uint8
  valueBytes  ASCII string
```

Required field IDs for a success path:

| fieldId | Required Flag | Candidate Meaning | Current Recommended Value |
| ---: | ---: | --- | --- |
| 0 | `0x01` | Diagnostic/service endpoint | `udp://192.168.100.123:9000` |
| 5 | `0x02` | Upstream publish endpoint | `udp://192.168.100.123:9000` |
| 6 | `0x04` | Event endpoint | `udp://192.168.100.123:9000` |
| 7 | `0x08` | Real-time data endpoint | `udp://192.168.100.123:9000` |
| 8 | `0x10` | History data endpoint | `udp://192.168.100.123:9000` |
| 9 | `0x20` | Image publish endpoint | `udp://192.168.100.123:9000` |

The `all_9000_profile` is the current recommended offline body profile, but it is still a candidate and not a confirmed accepted online protocol behavior.

## Experiments

| Experiment | Action | Result | Current Interpretation |
| --- | --- | --- | --- |
| A | Mirrored `DSC_SHORT_24` to old DSC source port `6002`. | No obvious reaction. | Does not prove current-source-port ACK invalid. |
| B | Mirrored latest `DSC_SHORT_24` to current DSC source port `6003`. | No obvious reaction. | Mirror raw packet strategy abandoned. |
| C | Sent generated login ACK candidate once. | No useful validity conclusion. | Used stale `2026-04-28` log and old remotePort `6000`; live traffic had moved to `2026-04-29` and DSC source port `6005`. |
| D dry-run | Reworked tooling to select current raw log, latest DSC_CONFIG request, freshness, and current source port before preparing a candidate. | Dry-run/report only. | Prepared for manual review; no ACK sent by dry-run. |

## Platform Read-Only Capabilities

Implemented or available:

- Raw packet logging under `backend/logs/fsu_raw_packets/YYYY-MM-DD.jsonl`.
- Read-only parser and frame classification.
- `/fsu-debug` FSU access diagnostics page:
  - online status for DSC/RDS/HTTP_SOAP
  - current phase judgement
  - frameClass/typeA/length/remotePort/URI statistics
  - UNKNOWN and non-standard frame samples
  - recent 100 raw packets with `rawHex` copy
  - export bundles for recent raw packets, daily reports, UNKNOWN samples, and DSC_CONFIG samples
- Offline new-frame detection script.
- Offline daily observation report script.

## Still Unconfirmed

- Whether `typeA=110047ff` is accepted by the live device as login ACK.
- Whether response `seqLE` must mirror the latest request, can be independent, or follows another rule.
- Whether `offset8..19` must mirror the latest request or can use a fixed constant.
- Whether `all_9000_profile` endpoint values are accepted by this firmware.
- Whether any generated candidate changes the device into a real data/event/alarm phase.
- Business-frame payload layouts for future real-time, history, event, alarm, image, and RDS data.

## Recommended State

Keep the system in read-only observation mode. Continue collecting daily raw logs, classifying new frame types, and using `/fsu-debug` for diagnostics. Any future send experiment must be a separately approved, one-shot, controlled test using the current latest raw log and current source port.
