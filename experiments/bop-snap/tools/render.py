"""Render a layered 2D rig to straight-alpha PNG frames."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def affine(x, y, degrees):
    angle = np.radians(degrees)
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, x], [s, c, y], [0, 0, 1]])


def sample(keys, frame):
    if frame <= keys[0][0]:
        return keys[0][1]
    for (start, left), (end, right) in zip(keys, keys[1:]):
        if frame <= end:
            t = (frame - start) / (end - start)
            return left + (right - left) * t * t * (3 - 2 * t)
    return keys[-1][1]


class Scene:
    def __init__(self, source):
        self.rig = json.loads(source.read_text(encoding='utf-8'))
        self.motion = self.rig['animation']
        self.images = {}
        for name, part in self.rig['attachments'].items():
            image = np.array(Image.open(source.parent / part['file']).convert('RGBA'), np.float32) / 255
            image[:, :, :3] *= image[:, :, 3:4]
            self.images[name] = image
        self.bind = self.matrices(None)
        self.inverse_bind = {name: np.linalg.inv(m) for name, m in self.bind.items()}

    def matrices(self, frame):
        world = {}
        for bone in self.rig['bones']:
            values = [bone.get(k, 0) for k in ('x', 'y', 'rotation')]
            if frame is not None:
                tracks = self.motion['tracks'].get(bone['name'], {})
                for i, key in enumerate(('x', 'y', 'rotation')):
                    if key in tracks:
                        values[i] += sample(tracks[key], frame)
            local = affine(*values)
            parent = bone['parent']
            world[bone['name']] = world[parent] @ local if parent else local
        return world

    def draw(self, frame, scale=1.5):
        stage = self.rig['stage']
        width, height = stage['width'], stage['height']
        canvas = np.zeros((round(height * scale), round(width * scale), 4), np.float32)
        world = self.matrices(frame)
        for slot in self.rig['slots']:
            name = slot['attachment']
            for start, replacement in self.motion['swaps'].get(slot['name'], []):
                if frame < start:
                    break
                name = replacement
            if not name:
                continue
            tex = self.images[name]
            h, w = tex.shape[:2]
            part = self.rig['attachments'][name]
            x, y, pw, ph = (part[k] for k in ('x', 'y', 'width', 'height'))
            bone = slot['bone']
            mesh = part.get('mesh')
            if mesh:
                local = np.asarray(mesh['vertices'])
                bind_vertices = (self.bind[bone] @ np.c_[local, np.ones(len(local))].T).T
                points = np.zeros((len(local), 2))
                for influence in {key for mix in mesh['weights'] for key in mix}:
                    mix = np.array([m.get(influence, 0) for m in mesh['weights']])
                    deformed = (world[influence] @ self.inverse_bind[influence] @ bind_vertices.T).T
                    points += mix[:, None] * deformed[:, :2]
            else:
                local = np.array([[x, y], [x + pw, y], [x, y + ph], [x + pw, y + ph]])
                points = (world[bone] @ np.c_[local, np.ones(4)].T).T[:, :2]
            points = points * scale - .5
            uv = (local - [x, y]) * [w / pw, h / ph] - .5
            lo = np.maximum(np.floor(points.min(0) - 2).astype(int), 0)
            hi = np.minimum(np.ceil(points.max(0) + 3).astype(int), canvas.shape[1::-1])
            if (hi <= lo).any():
                continue
            size = tuple(hi - lo)
            dest = (points - lo).astype(np.float32)
            uv = uv.astype(np.float32)
            if mesh:
                pixels = mesh_warp(tex, dest, uv, mesh['triangles'], size)
            else:
                mat = cv2.getAffineTransform(uv[:3], dest[:3])
                pixels = cv2.warpAffine(tex, mat, size, flags=cv2.INTER_LINEAR)
            region = canvas[lo[1]:hi[1], lo[0]:hi[0]]
            region[:] = pixels + region * (1 - pixels[:, :, 3:4])
        if scale != 1:
            canvas = cv2.resize(canvas, (width, height), interpolation=cv2.INTER_AREA)
        alpha = canvas[:, :, 3:4]
        canvas[:, :, :3] /= np.maximum(alpha, 1e-6)
        return Image.fromarray(np.uint8(np.clip(canvas * 255 + .5, 0, 255)))


def mesh_warp(texture, dest, uv, triangles, size):
    """Use one inverse map for the entire surface. Shared edges composite once."""
    map_xy = np.full((size[1], size[0], 2), -10, np.float32)
    for triangle in triangles:
        coords = dest[triangle]
        matrix = cv2.getAffineTransform(coords, uv[triangle])
        x, y, w, h = cv2.boundingRect(coords)
        left, top = max(0, x - 1), max(0, y - 1)
        right, bottom = min(size[0], x + w + 1), min(size[1], y + h + 1)
        if right <= left or bottom <= top:
            continue
        yy, xx = np.mgrid[top:bottom, left:right]
        inside = np.zeros(xx.shape, np.uint8)
        polygon = np.rint((coords - [left, top]) * 256).astype(np.int32)
        cv2.fillConvexPoly(inside, polygon, 255, shift=8)
        sy, sx = np.nonzero(inside)
        map_xy[top + sy, left + sx] = (
            (left + sx[:, None]) * matrix[:, 0]
            + (top + sy[:, None]) * matrix[:, 1] + matrix[:, 2]
        )
    return cv2.remap(texture, map_xy, None, cv2.INTER_LINEAR)


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=root / 'model/rig.json')
    parser.add_argument('--out', type=Path, default=root / 'frames')
    parser.add_argument('--frames', type=int, nargs='+', help='Specific zero-based frame indices')
    args = parser.parse_args()
    scene = Scene(args.model)
    args.out.mkdir(parents=True, exist_ok=True)
    for frame in args.frames or range(scene.motion['frames']):
        scene.draw(frame).save(args.out / f'{frame:04d}.png')


if __name__ == '__main__':
    main()
