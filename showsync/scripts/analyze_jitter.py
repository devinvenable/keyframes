#!/usr/bin/env python3
"""Decompose recorded jitter runs into send-side vs delivery-side error.

Reads measure_jitter.py records: a summary JSON (its raw_samples pointer is
resolved relative to the summary), a JSON with inline samples, or a raw
samples .json.gz directly. This analysis is what attributed every recorded
Mac worst-case spike to cold-start loopback delivery, motivating the
send-time gate (docs/verification.md).
"""
import gzip
import json
from pathlib import Path
import sys

import numpy as np


def load_samples(path):
    path = Path(path)
    if path.suffix == '.gz':
        return json.loads(gzip.decompress(path.read_bytes()))
    record = json.loads(path.read_text())
    if isinstance(record, list):
        return record
    if 'samples' in record:
        return record['samples']
    if 'raw_samples' in record:
        return load_samples(path.parent / record['raw_samples'])
    raise ValueError(f'{path}: no samples, raw_samples pointer, or sample list')


def describe(error_ms, label):
    print(f'  {label:33s} sigma={np.std(error_ms):7.3f}'
          f'  p99|.|={np.percentile(np.abs(error_ms), 99):7.3f}'
          f'  worst|.|={np.max(np.abs(error_ms)):8.3f} ms')


def analyze(path):
    samples = load_samples(path)
    ideal = np.array([row['ideal'] for row in samples])
    sent = np.array([row['sent'] for row in samples])
    received = np.array([row['received'] for row in samples])
    print(f'\n== {path} ({len(samples)} ticks)')
    total = (np.diff(received) - np.diff(ideal)) * 1000
    send = (np.diff(sent) - np.diff(ideal)) * 1000
    delivery = (np.diff(received) - np.diff(sent)) * 1000
    latency = (received - sent) * 1000
    describe(send, 'send interval error (gate)')
    describe(total, 'received interval error')
    describe(delivery, 'delivery interval error')
    describe(latency, 'one-way delivery latency')
    print('  worst received-interval ticks, split into send vs delivery:')
    for i in np.argsort(-np.abs(total))[:5]:
        print(f'    tick {samples[i + 1]["tick"]:5d}: total={total[i]:8.3f}'
              f'  send={send[i]:8.3f}  delivery={delivery[i]:8.3f} ms')


def main():
    if len(sys.argv) < 2:
        raise SystemExit(f'usage: {sys.argv[0]} <record.json|record.json.gz> ...')
    for path in sys.argv[1:]:
        analyze(path)


if __name__ == '__main__':
    main()
