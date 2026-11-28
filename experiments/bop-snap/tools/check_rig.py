"""Check the bind geometry across the entire greeting and inspect the PNG master."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from render import Scene


def double_area(vertices, indices):
    a, b, c = (vertices[indices[:, i]] for i in range(3))
    u, v = b - a, c - a
    return u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', type=Path, default=root/'frames')
    folder = parser.parse_args().frames
    scene = Scene(root / 'model/rig.json')
    frame_count = scene.motion['frames']
    hashes = set()
    min_ratio = float('inf')
    max_head_scale_error = 0
    first = scene.matrices(0)
    last = scene.matrices(frame_count)
    loop_error = max(np.abs(first[b] - last[b]).max() for b in first)
    assert loop_error < 1e-8, 'Loop does not return to its first pose'
    for frame in range(frame_count):
        pose = scene.matrices(frame)
        singular = np.linalg.svd(pose['head'][:2, :2], compute_uv=False)
        max_head_scale_error = max(max_head_scale_error, np.abs(singular - 1).max())
        for slot in scene.rig['slots']:
            part = scene.rig['attachments'][slot['attachment']]
            mesh = part.get('mesh')
            if mesh is None:
                continue
            vertices = np.array(mesh['vertices'])
            indices = np.array(mesh['triangles'])
            bind = (scene.bind[slot['bone']] @ np.c_[vertices, np.ones(len(vertices))].T).T
            deformed = np.zeros_like(vertices)
            for b in {k for weights in mesh['weights'] for k in weights}:
                w = np.array([v.get(b, 0) for v in mesh['weights']])
                positions = (pose[b] @ scene.inverse_bind[b] @ bind.T).T
                deformed += w[:, None] * positions[:, :2]
            ratios = double_area(deformed, indices) / double_area(vertices, indices)
            min_ratio = min(min_ratio, ratios.min())
        with Image.open(folder / f'{frame:04d}.png') as image:
            assert image.size == (768, 768) and image.mode == 'RGBA'
            assert image.getchannel('A').getextrema() == (0, 255)
            hashes.add(hashlib.sha256(image.tobytes()).digest())
    assert len(list(folder.glob('*.png'))) == frame_count
    assert max_head_scale_error < 1e-8 and min_ratio > 0
    report = {
        'frames': frame_count,
        'fps': scene.motion['fps'],
        'seconds': frame_count / scene.motion['fps'],
        'unique_raster_frames': len(hashes),
        'max_head_scale_error': float(max_head_scale_error),
        'max_loop_endpoint_matrix_error': float(loop_error),
        'minimum_deformed_to_bind_triangle_area_ratio': float(min_ratio),
        'bones': len(scene.rig['bones']),
        'draw_order_slots': len(scene.rig['slots']),
        'weighted_meshes': sum('mesh' in a for a in scene.rig['attachments'].values()),
        'right_hand_cels': sum(k.startswith('hand-r-') for k in scene.rig['attachments']),
    }
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
