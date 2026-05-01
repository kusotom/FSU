# FSU ACK Experiments

This directory contains offline and manual-only tools for controlled ACK/handshake experiments.

## Purpose

The current captures show repeated DSC config URI frames and paired DSC/RDS short frames, with no confirmed business data frame class yet. Firmware strings include `Register OK`, `LoginToDSC`, `Login to Dsc timeout`, `LOGIN_ACK`, `SendRealDataQueue`, `SendEventData`, and `RecvRdsData`.

The goal is to prepare safe one-shot experiments that can test whether the FSU reacts to a platform-side UDP response. These scripts do not define the real ACK protocol.

## Known Endpoint Relationship

- FSU device IP: `192.168.100.100`
- Platform IP: `192.168.100.123`
- Platform UDP listeners:
  - DSC local port: `9000`
  - RDS local port: `7000`
- Observed FSU source ports:
  - DSC mainly `6002`, with smaller `6000` / `6003` groups
  - RDS `6001`
- Long config URI ports:
  - `udp://192.168.100.100:6002`
  - `udp://[dhcp]:6002`
  - smaller `6000` / `6003` groups

## Why Reply To Source Port First

For UDP request/response behavior, the immediate reply normally targets the datagram source address and source port. In the current logs, the DSC source port usually matches the declared URI port. Because of that, source port and declared URI port often point to the same target, but source port is still the safer first hypothesis.

Declared URI ports remain research candidates. They should not override the source port hypothesis without firmware or live experiment evidence.

## Why This Is Not Integrated Into The Platform

The ACK type, ACK body, and checksum are not confirmed. Integrating automatic replies into `fsu-gateway` could alter device state, hide useful evidence, or create a false protocol implementation. These tools are intentionally separate and manual.

## One-Shot Experiment Workflow

1. Record a baseline time `T0`.
2. Observe baseline traffic for at least 60 seconds.
3. Manually select one raw packet from `backend/logs/fsu_raw_packets/2026-04-28.jsonl`.
4. Build candidate metadata offline:

```powershell
node backend\scripts\fsu-ack-experiments\build-ack-candidates.js --raw-hex <rawHex> --protocol UDP_DSC --remote-address 192.168.100.100 --remote-port 6002 --local-port 9000
```

5. If you intentionally choose a candidate with a non-null `ackHex`, send exactly one packet:

```powershell
node backend\scripts\fsu-ack-experiments\send-one-shot-ack.js --target-host 192.168.100.100 --target-port 6002 --ack-hex <hex> --label EXPERIMENT_A_MIRROR_DSC_SHORT_24 --yes-i-know-this-is-experimental
```

6. Continue observing for at least 60 seconds.
7. Compare before/after traffic:

```powershell
node backend\scripts\fsu-ack-experiments\watch-after-ack.js --log backend\logs\fsu_raw_packets\2026-04-28.jsonl --since "2026-04-28T09:00:00.000Z" --seconds 60
```

## How To Stop

The sender sends one UDP packet and exits. There is no daemon and no automatic reply loop. To stop an observation command, use `Ctrl+C`.

## What To Observe

- Whether `DSC_CONFIG_209` / `DSC_CONFIG_245` frequency changes.
- Whether new `frameClass`, `typeA`, or frame lengths appear.
- Whether payload length candidates change.
- Whether obvious ASCII payload data appears.
- Whether the device stops sending, restarts, or changes source ports.
- Whether RDS short-frame pairing changes.

## First Recommended Experiment

Experiment A: mirror the latest `DSC_SHORT_24_TYPE_1F00_D2FF` packet from source port `6002` back to `192.168.100.100:6002`.

Purpose: observe whether the FSU reacts to a same-protocol short frame from the platform side.

This is not a correct ACK. It is a conservative network reaction probe. No change does not mean the ACK path is impossible; it only means this mirror short frame is not sufficient.

## Risks

- The FSU may ignore the packet.
- The FSU may reset a socket or alter its state.
- The FSU may temporarily stop/restart transmission.
- A mirrored frame could be interpreted as invalid or unexpected input.
- The true ACK may require a different command type, checksum, or body.

Do not run these tools against production devices without an approved experiment window and packet capture.
