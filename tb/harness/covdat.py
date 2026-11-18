"""Parse Verilator coverage records; retain full keys for identity and merging.

Based on closed_loop/parse.py. No coverage type is guessed or silently discarded.
"""
import argparse
import json
import re
from pathlib import Path


def parse_dat(path):
    points = []
    for line in Path(path).read_text().splitlines():
        match = re.fullmatch(r"C\s+'(.*)'\s+(\d+)\s*", line)
        if not match:
            continue
        key, count = match.groups()
        fields = dict(field.split('\x02', 1) for field in key.split('\x01')
                      if '\x02' in field)
        points.append(dict(key=key, fields=fields, hits=int(count),
                           type=fields.get('page', '').split('/')[0],
                           file=fields.get('f', ''), name=fields.get('o', '')))
    return points


def summarize(points, scopes=()):
    by_type = {}
    for point in points:
        if scopes and point['type'] in ('v_line', 'v_branch', 'v_toggle'):
            if not any(s in point['file'] for s in scopes):
                continue
        item = by_type.setdefault(point['type'], dict(hit=0, total=0))
        item['total'] += 1
        item['hit'] += int(point['hits'] > 0)
    return by_type


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('dat')
    parser.add_argument('--scope', action='append', default=[])
    args = parser.parse_args()
    print(json.dumps(summarize(parse_dat(args.dat), args.scope), indent=2))
