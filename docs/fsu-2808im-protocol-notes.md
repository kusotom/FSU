# FSU-2808IM Protocol Notes

This document records the current reverse-engineering notes for integrating an FSU-2808IM device. It is a working analysis record, not a confirmed protocol specification. Do not treat any login ACK candidate as production behavior.

## Current Topology

- Device IP: `192.168.100.100`
- Platform IP: `192.168.100.123`
- Platform UDP listeners observed in the project:
  - DSC receive: UDP `9000`
  - RDS receive: UDP `7000`
- Device UDP source ports observed:
  - UDP_DSC: `6000`, `6002`, `6003`, `6005` across different windows
  - UDP_RDS: `6001`

The active DSC source port changes over time. Any observation or experiment must use current raw packet logs, not a stale date-specific log.

## Identified Frame Classes

Known frame classes in raw packet logs:

- `DSC_SHORT_24_TYPE_1F00_D2FF`
  - Protocol: `UDP_DSC`
  - Length: `24`
  - `typeA`: `1f00d2ff`
- `RDS_SHORT_30_TYPE_1180_D2FF`
  - Protocol: `UDP_RDS`
  - Length: `30`
  - `typeA`: `1180d2ff`
- `DSC_CONFIG_209_TYPE_1100_46FF`
  - Protocol: `UDP_DSC`
  - Length: `209`
  - `typeA`: `110046ff`
- `DSC_CONFIG_245_TYPE_1100_46FF`
  - Protocol: `UDP_DSC`
  - Length: `245`
  - `typeA`: `110046ff`

## Frame Layout

Recovered binary layout:

| Offset | Field | Notes |
| --- | --- | --- |
| `0..1` | SOI | Confirmed `6d7e` |
| `2..3` | `seqLE` | Little-endian sequence candidate; validation semantics not fully confirmed |
| `4..7` | `typeA` | Command/type bytes |
| `8..19` | Header context | Common observed value `00000000c162002d00000000`; acceptance semantics not fully confirmed |
| `20..21` | `lengthLE` | Little-endian body length; equals `totalLength - 24` |
| `22..23` | `checksumLE` | Little-endian checksum |
| `24..` | body | Body starts at `frame + 0x18` |

Checksum formula recovered from `ParseData` and verified against long config and RDS short frames:

```text
uint16 sum(buffer[2..totalLen-1]), with bytes 22..23 zeroed before summing
```

Important caveat: `DSC_SHORT_24_TYPE_1F00_D2FF` does not match the same checksum formula directly and should not be used as an ACK model source.

## DSC_CONFIG_209 / DSC_CONFIG_245 URI Structure

`DSC_CONFIG_209` and `DSC_CONFIG_245` carry ASCII URI-like strings in the body.

Observed examples:

- `udp://192.168.100.100:6000`
- `udp://192.168.100.100:6002`
- `udp://[dhcp]:6002`
- `udp://[dhcp]:6003`
- `ftp://root:hello@192.168.100.100`
- `ftp://root:hello@[dhcp]`

The `245` variant tends to include explicit IP forms. The `209` variant tends to include `[dhcp]` placeholder forms. Both use `typeA = 110046ff`.

## Login Response Candidate Body

Firmware reverse engineering found a login status response handler around `0x7e804`. `ParseData` dispatches to this handler when:

```text
frame[6] == 0x47
```

The candidate response body layout is:

```text
body[0]    = status
body[1..2] = entryCount uint16LE

repeat entryCount times:
  fieldId:     uint8
  valueLength: uint8
  valueBytes:  ASCII bytes, length valueLength
```

Status values recovered from handler behavior:

- `0`: Success
- `1`: Fail
- `2`: UnRegister

Success requires a local flags mask of `0x3f`, set by these required `fieldId` values:

| fieldId | Required flag | Current meaning candidate |
| --- | --- | --- |
| `0` | `0x01` | Diagnostic data channel endpoint |
| `5` | `0x02` | Uplink publish channel endpoint |
| `6` | `0x04` | Event data channel endpoint |
| `7` | `0x08` | Real-time data channel endpoint |
| `8` | `0x10` | Historical data channel endpoint |
| `9` | `0x20` | Image publish channel endpoint |

The value format candidate for each required field is:

```text
udp://host:port
```

Current endpoint profile candidate:

```text
all_9000_profile:
  fieldId 0 -> udp://192.168.100.123:9000
  fieldId 5 -> udp://192.168.100.123:9000
  fieldId 6 -> udp://192.168.100.123:9000
  fieldId 7 -> udp://192.168.100.123:9000
  fieldId 8 -> udp://192.168.100.123:9000
  fieldId 9 -> udp://192.168.100.123:9000
```

This is still a candidate profile. The endpoint mapping has not been proven by a successful live acceptance result.

## Login ACK Candidate Status

Current candidate header choices:

- `typeA`: `110047ff`
  - Basis: observed request `110046ff`; response dispatch checks `frame[6] == 0x47`.
  - Confidence: medium, not fully confirmed.
- `seqLE`: mirror latest request `seqLE`
  - No strong response sequence validation was found.
  - Confidence: low-medium.
- `frame[8..19]`: mirror latest request `frame[8..19]`
  - No strong response header-context validation was found.
  - Confidence: medium.

Still not fully confirmed:

- Whether `110047ff` is the complete accepted login response `typeA`.
- Whether the response must mirror request `seqLE`.
- Whether `frame[8..19]` must mirror the request or may use a fixed context.
- Whether the device accepts the candidate response on the wire.
- Whether all required endpoint values should use UDP `9000` in every deployment.

## Experiments

### Experiment A

- Action: mirrored `DSC_SHORT_24` to old DSC source port `6002`.
- Result: no obvious reaction.
- Interpretation: only showed no obvious effect when sent to an old port; it did not prove that sending to the current source port is ineffective.

### Experiment B

- Action: mirrored latest `DSC_SHORT_24` to the then-current DSC source port `6003`.
- Result: no obvious reaction.
- Interpretation: raw packet mirroring is not a useful ACK strategy. Work moved to firmware reverse engineering of `LOGIN_ACK`, `Register OK`, and `ParseData`.

### Experiment C

- Action: generated login ACK candidate from `2026-04-28.jsonl`, then sent once.
- Selected request source port: `6000`.
- Actual observation period used current `2026-04-29.jsonl`; DSC source port in that window was `6005`.
- Result: no meaningful state change.
- Interpretation: result is limited. It cannot prove the candidate ACK content is invalid; it only shows no obvious effect when sent to stale port `6000`.

### Experiment D Dry Run

Dry run only. No UDP packet was sent.

- Latest raw log selected: `backend/logs/fsu_raw_packets/2026-04-29.jsonl`
- Selected request:
  - `receivedAt`: `2026-04-29T15:30:56.001271+00:00`
  - `frameClass`: `DSC_CONFIG_209_TYPE_1100_46FF`
  - `remoteAddress`: `192.168.100.100`
  - `remotePort`: `6003`
  - `seqLE`: `6000`
  - `typeA`: `110046ff`
  - `frame[8..19]`: `00000000c162002d00000000`
- Freshness check: passed in dry-run output.
- Port freshness check: passed in dry-run output.
- Candidate:
  - `typeA`: `110047ff`
  - `seqLE`: `6000`
  - `offset8..19`: `00000000c162002d00000000`
  - `bodyLength`: `171`
  - `checksumLE`: `5727`
- Offline simulator checks passed:
  - SOI
  - length
  - checksum
  - not busy
  - dispatch `frame[6] == 0x47`
  - status success
  - TLV parsed
  - required flags

Experiment D remains a dry run. It is not a live acceptance result.

## Safety Notes

- No automatic ACK is enabled.
- No gateway runtime response logic should be changed based on these notes.
- Candidate ACK frames remain experimental.
- Offline simulation passing only means the candidate matches the recovered parser model; it does not prove device acceptance.
