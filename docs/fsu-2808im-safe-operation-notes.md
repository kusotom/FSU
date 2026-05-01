# FSU-2808IM Safe Operation Notes

This document defines the safe operating boundary for the FSU-2808IM integration work.

## Current Operating Policy

- Online ACK is not enabled.
- Automatic UDP replies are not enabled.
- `fsu-gateway` runtime reply logic must not be modified for ACK behavior without a separate approved implementation review.
- Business main tables must not be written by reverse-analysis tools.
- Raw packet analysis and diagnostics must remain read-only.
- `/fsu-debug` is a read-only diagnostics page. It does not send UDP packets and does not enable ACK behavior.

## ACK-Related Scripts

Scripts under `backend/scripts/fsu-ack-experiments/` are experimental tools. They exist for offline modeling, historical reports, dry-runs, or manually approved one-shot lab experiments.

They must be treated as:

- Experimental only.
- Not production tooling.
- Not part of normal platform startup.
- Not an automatic reply mechanism.
- Requiring explicit manual approval before any packet send is considered.

## Production Restrictions

The following must not be run in production:

- `backend/scripts/fsu-ack-experiments/send-one-shot-ack.js`
- Any script mode that sends UDP packets.
- Any loop that repeats ACK candidates.
- Any wrapper that calls `send-one-shot-ack.js` automatically.
- Any runtime hook that turns candidate ACKs into platform replies.

`send-one-shot-ack.js` is not a production command. It should be used only in an approved lab window, with an explicit one-shot command, current raw log evidence, and packet observation before and after the send.

## Allowed Read-Only Activities

Allowed work includes:

- Reading `backend/logs/fsu_raw_packets/*.jsonl`.
- Reading readonly parse outputs.
- Reading generated daily observation reports.
- Running offline parsers, classifiers, and report generators.
- Updating documentation.
- Updating `/fsu-debug` read-only diagnostics.
- Exporting raw packet samples for offline review.

## Required Warnings In User-Facing Views

Any FSU reverse-analysis page or report should state:

- Current protocol parsing is reverse-analysis output.
- Candidate ACK is not confirmed.
- Online ACK/reply is not enabled.
- Results do not prove full protocol semantics.

## Future Controlled Experiments

Any future live packet experiment must be explicitly approved and must:

- Select the current latest raw packet log automatically.
- Select the latest fresh `DSC_CONFIG_245` or `DSC_CONFIG_209` request.
- Use the current request source `remotePort`, not a stale fixed port.
- Pass offline simulation first.
- Send at most one UDP packet.
- Observe before and after windows.
- Stop immediately after one attempt regardless of success, no effect, or abnormal behavior.

This document does not approve any send experiment. It only records the safety boundary.
