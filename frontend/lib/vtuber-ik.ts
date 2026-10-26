export type Point3 = [number, number, number];
const subtract = (a: Point3, b: Point3): Point3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Point3, b: Point3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const scale = (a: Point3, n: number): Point3 => [a[0] * n, a[1] * n, a[2] * n];
const add = (a: Point3, b: Point3): Point3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const length = (a: Point3) => Math.hypot(...a);

// Analytic two-segment arm IK. The pole controls which way the elbow bends.
export function solveArmChain(shoulder: Point3, target: Point3, pole: Point3, upper: number, lower: number) {
  const delta = subtract(target, shoulder), rawDistance = length(delta);
  const direction: Point3 = rawDistance > 1e-8 ? scale(delta, 1 / rawDistance) : [0, -1, 0];
  const distance = Math.max(Math.abs(upper - lower) + 1e-6, Math.min(upper + lower - 1e-6, rawDistance));
  const towardPole = subtract(pole, shoulder);
  let bend = subtract(towardPole, scale(direction, dot(towardPole, direction)));
  if (length(bend) < 1e-8) {
    const fallback: Point3 = Math.abs(direction[2]) < .9 ? [0, 0, 1] : [1, 0, 0];
    bend = subtract(fallback, scale(direction, dot(fallback, direction)));
  }
  bend = scale(bend, 1 / length(bend));
  const along = (upper * upper - lower * lower + distance * distance) / (2 * distance);
  const outward = Math.sqrt(Math.max(0, upper * upper - along * along));
  return {
    elbow: add(shoulder, add(scale(direction, along), scale(bend, outward))),
    hand: add(shoulder, scale(direction, distance)),
  };
}
