"""Container timing shared by the audio master and silent video follower."""
import math


def stream_start(stream):
    return float((stream.start_time or 0) * stream.time_base)


def stream_duration(container, stream):
    # MPEG program streams often report a duration ending at the last sampled
    # keyframe, truncating silent playback by an entire GOP. Scan packet PTS
    # (no image decoding) when no reliable indexed video duration is available.
    if stream.type == 'video' and (
            container.format.name in ('mpeg', 'mpegvideo', 'm4v') or
            stream.duration is None):
        end = None
        for packet in container.demux(stream):
            if packet.pts is not None:
                step = (float(packet.duration * stream.time_base) if packet.duration else
                        1 / float(stream.average_rate) if stream.average_rate else 0)
                stamp = float(packet.pts * stream.time_base) + step
                end = stamp if end is None else max(end, stamp)
        if end is None:
            raise ValueError('video stream has no timestamps')
        duration = end - stream_start(stream)
    elif stream.duration is not None:
        duration = float(stream.duration * stream.time_base)
    elif container.duration is not None:
        import av
        duration = container.duration / av.time_base
    else:
        raise ValueError(f'{stream.type} stream has no duration')
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f'{stream.type} stream has no duration')
    return duration
