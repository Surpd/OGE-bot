import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const input = path.resolve(root, 'model/rig.json');
const modelDir = path.dirname(input);
const outputDir = path.resolve(root, 'rigby');
const defaultRigbySource = path.resolve(here, '../../../../.tmp/bop-rigby/rigby2d');
let rigbySource = process.env.RIGBY_SOURCE || defaultRigbySource;
let outputName = 'bop-snap.rigby';
for (let i = 2; i < process.argv.length; i++) {
  const arg = process.argv[i];
  if (arg === '--rigby-source') {
    if (!process.argv[i + 1]) throw new Error('--rigby-source needs a path');
    rigbySource = process.argv[++i];
  } else if (arg.startsWith('--rigby-source=')) rigbySource = arg.slice('--rigby-source='.length);
  else if (arg.startsWith('-')) throw new Error(`unknown option '${arg}'`);
  else if (outputName === 'bop-snap.rigby') outputName = arg;
  else throw new Error('usage: node convert.mjs [output.rigby] [--rigby-source <path>]');
}
const output = path.resolve(outputDir, outputName);
rigbySource = path.resolve(rigbySource);
const rigbyModule = (name) => import(pathToFileURL(path.join(rigbySource, name)).href);
const [{ Animation, makeKey }, { transform }, { Pose }, { Skeleton, makeAttachment, makeBone, makeSlot }, { zip }] = await Promise.all([
  rigbyModule('src/core/animation.js'), rigbyModule('src/core/math.js'), rigbyModule('src/core/pose.js'),
  rigbyModule('src/core/model.js'), rigbyModule('src/editor/zip.js'),
]);

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function safePath(relative) {
  check(typeof relative === 'string' && relative.length > 0, 'attachment file must be a non-empty relative path');
  const resolved = path.resolve(modelDir, relative);
  check(resolved.startsWith(`${root}${path.sep}`), `attachment path escapes bop-snap: ${relative}`);
  return resolved;
}

function safeOutput(file) {
  check(file.startsWith(`${outputDir}${path.sep}`), `output must stay inside ${outputDir}`);
  check(path.extname(file).toLowerCase() === '.rigby', 'output must end in .rigby');
}

function number(value, context) {
  check(Number.isFinite(value), `${context} must be a finite number`);
  return value;
}

function bezier() {
  // Smoothstep 3t²−2t³ represented exactly as a cubic Bezier with x=t.
  return { bezier: [1 / 3, 0, 2 / 3, 1] };
}

function keys(entries, convert, curve = bezier()) {
  check(Array.isArray(entries), 'animation channels must be arrays of [frame, value] pairs');
  const seen = new Set();
  return entries.map((entry) => {
    check(Array.isArray(entry) && entry.length === 2, 'animation keys must be [frame, value] pairs');
    const frame = number(entry[0], 'key frame');
    check(frame >= 0 && frame <= 72, `key frame ${frame} is outside 0..72`);
    check(!seen.has(frame), `duplicate key at frame ${frame}`);
    seen.add(frame);
    const isLast = entry === entries.at(-1);
    return makeKey(frame / 24, convert(entry[1]), isLast && curve !== 'stepped' ? 'linear' : structuredClone(curve));
  }).sort((a, b) => a.time - b.time);
}

async function main() {
  safeOutput(output);
  const rig = JSON.parse(await fs.readFile(input, 'utf8'));
  check(rig.stage && number(rig.stage.width, 'stage.width') > 0 && number(rig.stage.height, 'stage.height') > 0, 'stage width and height must be positive');
  check(Array.isArray(rig.bones) && rig.bones.length > 0, 'bones must be a non-empty array');
  check(Array.isArray(rig.slots), 'slots must be an array');
  check(rig.attachments && typeof rig.attachments === 'object', 'attachments must be an object');
  const doc = new Skeleton();
  doc.name = 'BOP Snap';
  doc.workspace = 'film';
  doc.settings = {
    fps: rig.animation?.fps ?? 24,
    width: rig.stage.width,
    height: rig.stage.height,
    background: null,
    frame: { x: rig.stage.width / 2, y: -rig.stage.height / 2, scale: 1 },
  };
  doc.settingsInFile = true;
  const pending = rig.bones.map((bone, order) => ({ bone, order }));
  const boneIndex = new Map();
  const add = (bone) => {
    check(typeof bone.name === 'string' && bone.name.length > 0, 'every bone needs a name');
    check(!boneIndex.has(bone.name), `duplicate bone '${bone.name}'`);
    const parent = bone.parent == null ? null : boneIndex.get(bone.parent);
    check(bone.parent == null || parent !== undefined, `bone '${bone.name}' has missing or cyclic parent '${bone.parent}'`);
    const item = makeBone(bone.name, parent, transform(number(bone.x ?? 0, `${bone.name}.x`), -number(bone.y ?? 0, `${bone.name}.y`), -number(bone.rotation ?? 0, `${bone.name}.rotation`)), 0);
    if (!boneIndex.size && doc.bones.length === 1 && doc.bones[0].name === 'root') doc.bones[0] = item;
    else doc.bones.push(item);
    boneIndex.set(bone.name, doc.bones.length - 1);
  };
  while (pending.length) {
    const ready = pending.filter(({ bone }) => bone.parent == null || boneIndex.has(bone.parent));
    check(ready.length > 0, `missing/cyclic bone parents: ${pending.map(({ bone }) => bone.name).join(', ')}`);
    for (const { bone } of ready) {
      add(bone);
      pending.splice(pending.findIndex((item) => item.bone === bone), 1);
    }
  }

  const imageByFile = new Map();
  const imageEntries = [];
  let imageCount = 0;
  const sourceAttachments = new Map();
  for (const [name, source] of Object.entries(rig.attachments)) {
    check(source && typeof source === 'object', `attachment '${name}' must be an object`);
    check(typeof source.file === 'string', `attachment '${name}' needs file`);
    const sourceFile = safePath(source.file);
    let imageName = imageByFile.get(sourceFile);
    if (!imageName) {
      const bytes = await fs.readFile(sourceFile);
      check(bytes.length >= 24 && bytes.toString('ascii', 1, 4) === 'PNG', `${source.file} is not a PNG`);
      const width = bytes.readUInt32BE(16);
      const height = bytes.readUInt32BE(20);
      check(width > 0 && height > 0, `${source.file} has invalid dimensions`);
      imageName = `image_${String(++imageCount).padStart(3, '0')}`;
      imageByFile.set(sourceFile, imageName);
      doc.images.push({ name: imageName, path: null, width, height });
      imageEntries.push({ path: `images/${imageName}.png`, bytes: new Uint8Array(bytes) });
    }
    const x = number(source.x ?? 0, `${name}.x`);
    const y = number(source.y ?? 0, `${name}.y`);
    const width = number(source.width, `${name}.width`);
    const height = number(source.height, `${name}.height`);
    check(width > 0 && height > 0, `${name} width and height must be positive`);
    let attachment;
    if (source.mesh) {
      const mesh = source.mesh;
      check(Array.isArray(mesh.vertices) && mesh.vertices.length >= 3, `${name}.mesh needs at least three vertices`);
      check(Array.isArray(mesh.triangles), `${name}.mesh.triangles must be an array`);
      const flatVertices = [];
      const uvs = [];
      for (const [index, vertex] of mesh.vertices.entries()) {
        check(Array.isArray(vertex) && vertex.length === 2, `${name}.mesh vertex ${index} must be [x, y]`);
        const vx = number(vertex[0], `${name}.mesh vertex x`);
        const vy = number(vertex[1], `${name}.mesh vertex y`);
        flatVertices.push(vx, -vy);
        uvs.push((vx - x) / width, (vy - y) / height);
      }
      const triangles = mesh.triangles.flatMap((triangle) => {
        check(Array.isArray(triangle) && triangle.length === 3, `${name}.mesh triangles must be [a, b, c]`);
        for (const i of triangle) check(Number.isInteger(i) && i >= 0 && i < mesh.vertices.length, `${name}.mesh triangle index ${i} is invalid`);
        return triangle;
      });
      const hull = 2 * mesh.vertices.length - triangles.length / 3 - 2;
      check(Number.isInteger(hull) && hull >= 3 && hull <= mesh.vertices.length, `${name}.mesh does not form a simple triangulated polygon (derived hull: ${hull})`);
      attachment = {
        name, type: 'mesh', image: imageName, color: [1, 1, 1, 1], width, height, uvs, triangles,
        hull, edges: null, vertices: flatVertices,
      };
      if (mesh.weights !== undefined) attachment._sourceWeights = mesh.weights;
    } else {
      attachment = makeAttachment(name, imageName, transform(x + width / 2, -(y + height / 2), 0), width, height);
    }
    sourceAttachments.set(name, { attachment, source });
  }

  for (const [slotIndex, sourceSlot] of rig.slots.entries()) {
    check(typeof sourceSlot.name === 'string' && sourceSlot.name.length > 0, `slot ${slotIndex} needs a name`);
    check(boneIndex.has(sourceSlot.bone), `slot '${sourceSlot.name}' references missing bone '${sourceSlot.bone}'`);
    const selected = sourceSlot.attachment == null ? null : sourceAttachments.get(sourceSlot.attachment);
    check(sourceSlot.attachment == null || selected, `slot '${sourceSlot.name}' references missing attachment '${sourceSlot.attachment}'`);
    const slot = makeSlot(sourceSlot.name, boneIndex.get(sourceSlot.bone), selected?.attachment ?? null);
    const alternatives = rig.animation?.swaps?.[sourceSlot.name]?.map(([, name]) => name) ?? [];
    const attachmentNames = [...new Set([sourceSlot.attachment, ...alternatives].filter((name) => name != null))];
    slot.attachments = attachmentNames.map((name) => {
      const item = sourceAttachments.get(name);
      check(item, `slot '${sourceSlot.name}' references missing attachment '${name}'`);
      return item.attachment;
    });
    doc.slots.push(slot);
  }

  const pose = new Pose(doc);
  for (const slot of doc.slots) {
    for (const attachment of slot.attachments) {
      const sourceWeights = attachment._sourceWeights;
      delete attachment._sourceWeights;
      if (sourceWeights === undefined) continue;
      check(Array.isArray(sourceWeights) && sourceWeights.length === attachment.vertices.length / 2, `${attachment.name}.mesh.weights must have one entry per vertex`);
      const invWorld = new Map();
      attachment.weights = sourceWeights.map((vertexWeights, vertexIndex) => {
        check(vertexWeights && typeof vertexWeights === 'object' && !Array.isArray(vertexWeights), `${attachment.name}.mesh.weights[${vertexIndex}] must map bone names to weights`);
        const entries = Object.entries(vertexWeights).filter(([, weight]) => Number(weight) > 0);
        check(entries.length > 0, `${attachment.name}.mesh vertex ${vertexIndex} has no positive weights`);
        let total = 0;
        const x = attachment.vertices[vertexIndex * 2];
        const y = attachment.vertices[vertexIndex * 2 + 1];
        const slotBone = doc.bones[doc.slots.find((s) => s.attachments.includes(attachment)).bone];
        const slotBoneIndex = boneIndex.get(slotBone.name);
        const world = pose.world[slotBoneIndex].apply([x, y]);
        return entries.map(([name, rawWeight]) => {
          check(boneIndex.has(name), `${attachment.name}.mesh vertex ${vertexIndex} weights missing bone '${name}'`);
          const weight = number(Number(rawWeight), `${attachment.name}.mesh weight`);
          total += weight;
          if (!invWorld.has(name)) invWorld.set(name, pose.world[boneIndex.get(name)].inverse());
          const [bx, by] = invWorld.get(name).apply(world);
          return { bone: boneIndex.get(name), x: bx, y: by, weight };
        }).map((weight) => ({ ...weight, weight: weight.weight / total }));
      });
      attachment.vertices = null;
    }
  }

  const animation = new Animation('loop', 3);
  for (const [name, channels] of Object.entries(rig.animation?.tracks ?? {})) {
    check(boneIndex.has(name), `animation references missing bone '${name}'`);
    const timeline = animation.boneTimelineMut(boneIndex.get(name));
    if (channels.x) timeline.translateX = keys(channels.x, (v) => number(v, `${name}.x`));
    if (channels.y) timeline.translateY = keys(channels.y, (v) => -number(v, `${name}.y`));
    if (channels.rotation) timeline.rotate = keys(channels.rotation, (v) => -number(v, `${name}.rotation`));
  }
  for (const [slotName, swaps] of Object.entries(rig.animation?.swaps ?? {})) {
    const slotIndex = doc.slots.findIndex((slot) => slot.name === slotName);
    check(slotIndex >= 0, `swaps reference missing slot '${slotName}'`);
    const available = new Set(doc.slots[slotIndex].attachments.map((attachment) => attachment.name));
    for (const [, attachment] of swaps) check(attachment == null || available.has(attachment), `swap '${attachment}' is not an attachment of slot '${slotName}'`);
    animation.slotTimelineMut(slotIndex).attachment = keys(swaps, (v) => v, 'stepped');
  }
  if (animation.bones.length || animation.slots.length) doc.animations.push(animation);

  const entries = [{ path: 'project.json', bytes: new TextEncoder().encode(doc.toJson()) }, ...imageEntries];
  await fs.mkdir(outputDir, { recursive: true });
  await fs.writeFile(output, zip(entries));
  console.log(JSON.stringify({ input, output, bones: doc.bones.length, slots: doc.slots.length, images: doc.images.length, animations: doc.animations.map((item) => item.name) }, null, 2));
}

main().catch((error) => { console.error(`Rigby conversion failed: ${error.message}`); process.exitCode = 1; });
