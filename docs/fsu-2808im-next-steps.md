# FSU-2808IM Next Steps

This document lists safe follow-up work for FSU-2808IM integration. It intentionally excludes packet sending, automatic ACK behavior, and runtime gateway reply changes.

## Read-Only Observation

- Keep collecting raw `UDP_DSC` and `UDP_RDS` packets into daily raw packet logs.
- Improve raw-log rotation visibility so current active logs are obvious.
- Add dashboard indicators for:
  - current DSC source port
  - current RDS source port
  - latest `DSC_CONFIG_209` / `DSC_CONFIG_245` timestamp
  - current frameClass distribution
  - current typeA distribution
  - current length distribution
- Track whether source ports change around device restart, timeout, or network events.

## Log Analysis

- Build read-only reports for:
  - DSC_CONFIG frequency over time
  - DSC_SHORT_24 frequency over time
  - RDS_SHORT_30 frequency over time
  - UNKNOWN frame count and examples
  - remotePort changes by protocol
- Add daily summary files for raw packet logs.
- Add comparison reports for pre/post windows without requiring any ACK experiment.
- Flag stale-log risks whenever an analysis uses a log file that is not the latest raw packet log.

## Protocol Classification

- Continue classifying unknown `typeA` values, lengths, and payload structures.
- Track new frame classes separately from known classes.
- Extract and index visible ASCII regions from all long frames.
- Maintain a field dictionary for DSC_CONFIG URI fields:
  - UDP URI entries
  - FTP URI entries
  - DHCP placeholder usage
  - explicit IP usage
  - declared ports

## Alarm And Event Recognition

- Watch for frame classes that appear only after state changes or device operations.
- Correlate candidate event/alarm frames with:
  - frame length
  - typeA
  - payload length
  - visible ASCII
  - source port
  - timing relative to device logs
- Keep event identification read-only until the payload format is understood.

## RDS Data Analysis

- Continue observing `UDP_RDS` traffic on platform UDP `7000`.
- Separate RDS short heartbeat-like frames from any future longer RDS data frames.
- Track whether RDS behavior changes when DSC_CONFIG repetitions stop or change.
- Build RDS-specific summaries:
  - source port
  - frame length
  - typeA
  - payload length
  - ASCII spans

## Device Log Correlation

- When available, collect device-side logs read-only and correlate with raw packet timestamps:
  - `SiteUnit.log`
  - `RDS.log`
  - `XML.log`
  - `gprs_monitor.log`
- Look for:
  - `LoginToDSC`
  - `Register OK`
  - timeout messages
  - data send queue messages
  - event send messages
  - RDS send/receive messages

## UI And Panel Work

- Add a read-only FSU status panel showing:
  - last packet time by protocol
  - current DSC/RDS source ports
  - frameClass counts
  - current DSC_CONFIG cadence
  - last URI values seen in config frames
  - recent UNKNOWN frames
- Add a packet detail viewer for a selected raw log entry:
  - frame header fields
  - parsed length/checksum fields
  - typeA
  - body offset
  - ASCII spans
  - URI extraction
- Add warnings in the UI when:
  - selected log is stale
  - source port changed recently
  - candidate analysis was based on an old raw log

## Documentation Hygiene

- Keep protocol notes separate from confirmed runtime behavior.
- Mark all inferred fields with confidence levels.
- Do not promote candidate ACK structures to confirmed protocol until accepted behavior is demonstrated and reproducible.
- Keep experiment reports linked from protocol notes, but avoid embedding operational packet-send instructions in general documentation.

## Boundaries

The next safe work should remain limited to read-only observation, parsing, reporting, and UI display. Do not add automatic response logic or change gateway packet handling based on the current candidate ACK model.
