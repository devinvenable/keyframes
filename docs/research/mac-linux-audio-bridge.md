# Mac-to-Linux Audio Bridge via PreSonus Quantum 2626

## Overview

Stream 3 channels of audio (1 mono mic + 1 stereo instrument pair) from a Mac Mini M2 to a Linux box over LAN using ffmpeg RTP and PipeWire.

## Hardware & Network

| Role   | Machine         | IP              | OS / Audio Stack              |
|--------|-----------------|-----------------|-------------------------------|
| Sender | Mac Mini M2     | 192.168.1.103   | macOS 15.4.1, ffmpeg 8.0.1   |
| Receiver | Linux (AMD B350) | 192.168.1.217 | Ubuntu, PipeWire 1.2.7        |

- **Audio interface:** PreSonus Quantum 2626 (Thunderbolt 3, 26in/26out)
- **AVFoundation device index:** `:1` (audio device 1 = "Quantum 2626")
- **BlackHole 2ch** is also available on Mac as device `:0` (useful for routing app audio)

## Architecture

```
Quantum 2626 (Thunderbolt)
    │
    ▼
Mac Mini (ffmpeg -f avfoundation)
    │  pan filter selects channels
    │  encodes as L16 (uncompressed PCM)
    ▼
RTP over LAN (UDP)
    │  Port 5004 = stereo instruments
    │  Port 5006 = mono mic
    ▼
Linux (PipeWire rtp-source module)
    │
    ▼
PipeWire graph (available as sources for any app)
```

## Quantum 2626 Channel Map

The Quantum 2626 exposes 26 input channels via AVFoundation (0-indexed):

| Channel | Physical Input |
|---------|---------------|
| 0-1     | Analog 1-2 (combo XLR/TRS, with preamps) |
| 2-3     | Analog 3-4 (combo XLR/TRS, with preamps) |
| 4-5     | Analog 5-6 (TRS line) |
| 6-7     | Analog 7-8 (TRS line) |
| 8-9     | ADAT 1-2 |
| 10-17   | ADAT 3-10 |
| 18-19   | S/PDIF L/R |
| 20-25   | Loopback / digital |

**Typical routing:**
- **Mic:** Channel 0 (Analog 1, XLR with 48V phantom power via Universal Control)
- **Stereo synth/instruments:** Channels 2-3 (Analog 3-4) or 4-5 (Analog 5-6)

Adjust channel numbers below to match your actual physical connections.

## Method: ffmpeg RTP → PipeWire rtp-source

This is the recommended approach. It requires:
- **Mac side:** ffmpeg (already installed at `/usr/local/bin/ffmpeg`)
- **Linux side:** PipeWire with rtp-source module (already installed)

No additional software needed on either side.

### Verified Working

Tested 2026-03-27: ffmpeg successfully streams L16/48000/2 from Quantum 2626 to Linux at 1.0x realtime with no errors.

---

## Mac Side: Sending Audio

### Stream 1: Stereo Instruments (channels 2-3 → port 5004)

```bash
/usr/local/bin/ffmpeg \
  -f avfoundation -i ':1' \
  -filter_complex 'pan=stereo|FL=c2|FR=c3' \
  -ar 48000 -acodec pcm_s16be \
  -f rtp rtp://192.168.1.217:5004
```

### Stream 2: Mono Mic (channel 0 → port 5006)

```bash
/usr/local/bin/ffmpeg \
  -f avfoundation -i ':1' \
  -filter_complex 'pan=mono|c0=c0' \
  -ar 48000 -acodec pcm_s16be \
  -f rtp rtp://192.168.1.217:5006
```

### Combined: Both streams in one ffmpeg process

```bash
/usr/local/bin/ffmpeg \
  -f avfoundation -i ':1' \
  -filter_complex 'pan=stereo|FL=c2|FR=c3[inst];pan=mono|c0=c0[mic]' \
  -map '[inst]' -ar 48000 -acodec pcm_s16be -f rtp rtp://192.168.1.217:5004 \
  -map '[mic]' -ar 48000 -acodec pcm_s16be -f rtp rtp://192.168.1.217:5006
```

### Wrapper script: `~/audio-bridge.sh` (on Mac)

```bash
#!/bin/bash
# Stream Quantum 2626 audio to Linux over RTP
# Usage: ~/audio-bridge.sh [start|stop]

FFMPEG=/usr/local/bin/ffmpeg
LINUX_IP=192.168.1.217
PIDFILE=/tmp/audio-bridge.pid

case "${1:-start}" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Already running (PID $(cat $PIDFILE))"
      exit 1
    fi
    $FFMPEG \
      -f avfoundation -i ':1' \
      -filter_complex 'pan=stereo|FL=c2|FR=c3[inst];pan=mono|c0=c0[mic]' \
      -map '[inst]' -ar 48000 -acodec pcm_s16be -f rtp rtp://${LINUX_IP}:5004 \
      -map '[mic]'  -ar 48000 -acodec pcm_s16be -f rtp rtp://${LINUX_IP}:5006 \
      </dev/null >/tmp/audio-bridge.log 2>&1 &
    echo $! > "$PIDFILE"
    echo "Started (PID $!). Log: /tmp/audio-bridge.log"
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then
      kill "$(cat "$PIDFILE")" 2>/dev/null
      rm -f "$PIDFILE"
      echo "Stopped."
    else
      echo "Not running."
    fi
    ;;
  *)
    echo "Usage: $0 [start|stop]"
    ;;
esac
```

---

## Linux Side: Receiving Audio

### Option A: PipeWire rtp-source module (recommended)

Create a PipeWire config drop-in to auto-receive both streams.

**File: `~/.config/pipewire/pipewire.conf.d/rtp-receive.conf`**

```
context.modules = [
  {
    name = libpipewire-module-rtp-source
    args = {
      local.ifname  = ""
      source.ip     = "192.168.1.103"
      source.port   = 5004
      sess.name     = "Quantum Instruments"
      node.name     = "rtp_quantum_instruments"
      node.description = "Quantum 2626 Instruments (stereo)"
      audio.format  = S16BE
      audio.rate    = 48000
      audio.channels = 2
      audio.position = [ FL FR ]
    }
  }
  {
    name = libpipewire-module-rtp-source
    args = {
      local.ifname  = ""
      source.ip     = "192.168.1.103"
      source.port   = 5006
      sess.name     = "Quantum Mic"
      node.name     = "rtp_quantum_mic"
      node.description = "Quantum 2626 Mic (mono)"
      audio.format  = S16BE
      audio.rate    = 48000
      audio.channels = 1
      audio.position = [ MONO ]
    }
  }
]
```

Then restart PipeWire:

```bash
systemctl --user restart pipewire
```

The sources will appear in `pw-cli ls Node` and in PulseAudio-compatible tools (`pavucontrol`, etc).

### Option B: ffplay receiver (for quick testing)

No PipeWire config needed — just receive and play:

```bash
# Terminal 1: stereo instruments
ffplay -nodisp -f rtp -i rtp://0.0.0.0:5004 -acodec pcm_s16be -ar 48000 -ac 2

# Terminal 2: mono mic
ffplay -nodisp -f rtp -i rtp://0.0.0.0:5006 -acodec pcm_s16be -ar 48000 -ac 1
```

### Option C: Direct SDP file approach

ffmpeg prints an SDP block when it starts. Save it to a file and use it on Linux:

```bash
# On Mac, redirect stderr to grab SDP
/usr/local/bin/ffmpeg -f avfoundation -i ':1' \
  -filter_complex 'pan=stereo|FL=c2|FR=c3' \
  -ar 48000 -acodec pcm_s16be \
  -f rtp rtp://192.168.1.217:5004 2>&1 | tee /tmp/ffmpeg.log

# Copy the SDP block to Linux, save as stream.sdp, then:
ffplay -protocol_whitelist file,rtp,udp -i stream.sdp
```

---

## Verification

### Check streams are arriving (Linux)

```bash
# Check UDP traffic on port 5004
ss -ulnp | grep 500[46]

# Check PipeWire nodes
pw-cli ls Node | grep -i quantum

# List PipeWire sources
pactl list sources short | grep rtp
```

### Measure latency

```bash
# On Mac, generate a click and stream it
# On Linux, record from RTP source and local mic simultaneously
# Compare waveforms in Audacity to measure round-trip delay

# Expected: ~10-50ms over LAN (dominated by ffmpeg buffering, not network)
```

### Adjust buffering (latency tuning)

On the Mac ffmpeg side, reduce output buffer:
```bash
# Add before output URL:
-flush_packets 1 -max_delay 0
```

On the PipeWire side, adjust node latency:
```
# In the rtp-source module args:
node.latency = 256/48000    # ~5.3ms
```

---

## Alternative Methods Considered

| Method | Pros | Cons | Verdict |
|--------|------|------|---------|
| **ffmpeg RTP → PipeWire** | No install needed, works now, uncompressed | Slightly more latency than JACK | ✅ **Chosen** |
| JACK NetJack | Ultra-low latency | Requires JACK on both sides, complex setup on Mac | Overkill for recording |
| PulseAudio network | Simple | Mac doesn't run PulseAudio natively | N/A |
| Roc Toolkit | FEC, adaptive jitter | Needs build from source on Mac | Future option |
| Dante/AVB | Pro-grade | Requires Dante hardware or Virtual Soundcard license ($) | Too expensive |

## Troubleshooting

**ffmpeg "Rematrix" error on Mac:**
The Quantum has 26 channels. You MUST use the `pan` filter to select channels. `-ac 2` alone won't work because ffmpeg can't auto-downmix 26 channels.

**No audio on Linux:**
1. Check firewall: `sudo ufw allow 5004/udp; sudo ufw allow 5006/udp`
2. Verify Mac is sending: check `/tmp/audio-bridge.log` for `speed=1x`
3. Verify network: `tcpdump -i any udp port 5004 -c 5`

**Choppy audio:**
- Increase PipeWire node.latency (e.g., `1024/48000`)
- Check network with `ping -c 100 192.168.1.103` — should be <1ms on LAN

**PipeWire rtp-source not picking up stream:**
- The module may need SAP (Session Announcement Protocol). Try adding `sap.ip = "224.0.0.56"` and `sap.port = 9875` to the module args, and on Mac side use multicast.
- Alternative: use the SDP file approach (Option C above).

## Remote control (start/stop from Linux)

```bash
# Start streaming from Linux
ssh mini '~/audio-bridge.sh start'

# Stop streaming from Linux
ssh mini '~/audio-bridge.sh stop'

# Check if running
ssh mini 'cat /tmp/audio-bridge.pid 2>/dev/null && echo running || echo stopped'
```
