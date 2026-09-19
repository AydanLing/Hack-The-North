#!/usr/bin/env python3
"""build_cubot_urdf.py — the shipped CuBot chain as a URDF (+ MJCF scene) with real chamfers.

Everything geometric here was confirmed against roll.html (the shipped roll viewer),
CuBot/presets/shipped.json (the roll word) and the printed CAD in ~/Desktop/CuBot CAD.

MODULE (all lengths mm, module frame at the cube centre)
  * 80 mm cube, cut by the plane x + y + z = 0 (normal = the <111> body diagonal).
      still  half = the -x-y-z side, carries the servo body, "inboard" in roll.html
      moving half = the +x+y+z side, the servo turns it, "outboard" in roll.html
  * The SIX equatorial edges — the cube edges that cross the cut plane — carry a
    45 deg chamfer with 8.00 mm legs:  |x-y| <= 72, |y-z| <= 72, |z-x| <= 72.
    The apex corners (+,+,+) / (-,-,-) and their six edges are sharp. Where two
    chamfers meet at an equatorial corner they form a ridge parallel to <111> at
    r111 = 58.788 mm, the number CuBot/tools/build-solid.mjs reports for the CAD.
    (The printed part measures 7.85 mm; 8.00 is the design value — see CHAMFER.)
  * NECK. Near the cut plane the printed halves are turned down around the hinge
    axis (the bearing/hub region), and that is what lets a half swing past its
    neighbour at a 2.2 mm gap: an un-necked half sweeps 2.33 mm past its own
    face mid-swing, the real part 0.06 mm. The outer profile — max radius from the
    <111> axis at height |t| above the cut plane — was measured on the convex
    hulls of Top.stl (moving) and MicroBots_Bottom_V12 + Hub_Still (still) in 1 mm
    slabs (measure_cad_profile.py); the two are mirror images to ~1 mm and the
    combined profile is bounded by ONE straight cone, r <= NECK_R0 + NECK_SLOPE*|t|,
    which reaches the chamfer ridge (58.79) at t ~ 10.6 mm. It is revolved as a
    NECK_SIDES-gon whose inscribed radius is the cone, so it contains the true
    surface. The hub cone that protrudes past the cut plane (t in [0,18],
    r <= 45.7 falling to 12.6) lies inside the moving half's neck at every
    height, for every servo angle, so the module envelope is complete without it.
    Only the outer profile is modelled: no pockets, bores or internal features.
  * Servo joint: continuous, axis +<111>/sqrt(3) from the still half into the moving
    half, right-handed. q = 0 is the straight chain. Detents are 120 deg apart and
    the servo travels -240..+240 deg; the controller enforces that, not this file.

CHAIN
  * 27 modules along +X.  still(k) -servo- moving(k) =rigid= still(k+1) ...
  * Neighbouring faces are GAP = 2.2 mm apart, so the centre pitch is 82.2 mm.
    A 50 x 50 x 2.2 mm spacer (the footprint of CuBot_Spacer.stl) sits in the gap,
    rigid on the moving half's +X face.
  * Roll word (26 digits, CuBot/presets/shipped.json): module k+1 is mounted rolled
    r_k * 90 deg about +X (right-hand, +X points toward module 27) relative to
    module k — the same rule roll.html applies:  M_{k+1} = M_k * Rx^{r_k}.
  * Zero pose: straight along +X, Z up, every cube resting on its -Z face,
    module 1 centre at the origin. The MJCF scene lifts the root by 40 mm.

MASS: 250 g per module, 125 g per half, uniform density; inertia integrated exactly
over the chamfered polytope. Spacers are massless (part of the 125 g).

Outputs (next to this script):  cubot_shipped.urdf, cubot_shipped.xml (MJCF),
scene.xml, meshes/still.stl, meshes/moving.stl   — units: metres, radians.

Run:  python3 build_cubot_urdf.py        (needs numpy + scipy)
"""
import json, os, struct
import numpy as np
from scipy.spatial import ConvexHull, HalfspaceIntersection

HERE = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------------- parameters
N_MODULES   = 27
CUBE        = 0.080          # m, cube edge
CHAMFER     = 0.008          # m, chamfer leg on the six equatorial edges (design value; printed = 0.00785)
GAP         = 0.0022         # m, face-to-face gap between neighbouring modules
PITCH       = CUBE + GAP     # m, centre-to-centre = 0.0822
SPACER      = (0.0022, 0.050, 0.050)   # m, (thickness along X, width Y, width Z) of the interface spacer
MODULE_MASS = 0.250          # kg per module
HALF_MASS   = MODULE_MASS / 2
ROLL_WORD   = "12001300133101230333233210"     # presets/shipped.json; digit k = mount roll of module k+2 vs k+1

# Servo limits reported in the URDF <limit> (informational for a continuous joint).
# 5.8 N·m = the 60 % STS3215 12 V register through 4:1, the planner's default cap.
EFFORT_NM    = 5.8
VELOCITY_RAD = 1.2

# Outer profile near the cut plane, measured per 1 mm slab (measure_cad_profile.py), max of both halves:
#   |t| mm : 0     1     2     3     4     5     6     7     8     9    10    11    12    13    14    15   16
#   r  mm  : 46.80 47.92 49.05 50.17 51.29 52.41 53.49 54.60 55.42 56.09 56.77 57.27 57.61 57.95 58.30 58.64 58.79
# One cone bounds all of it (checked in measure_cad_profile.py): r <= NECK_R0 + NECK_SLOPE * |t|.
NECK_R0    = 46.80   # mm, cone radius at the cut plane
NECK_SLOPE = 1.13    # mm per mm of height
NECK_SIDES = 12                                       # facets of the revolved cut (inradius = the cone)

AXIS = np.ones(3) / np.sqrt(3)               # servo axis, still -> moving
COL_STILL, COL_MOVING, COL_SPACER = "0.85 0.83 0.78 1", "0.91 0.51 0.23 1", "0.45 0.47 0.5 1"  # roll.html colours


def roll_word():
    """Prefer the live shipped.json; fall back to the literal, and refuse a mismatch."""
    p = os.path.join(HERE, "..", "CuBot", "presets", "shipped.json")
    if os.path.exists(p):
        w = "".join(str(d) for d in json.load(open(p))["roll"])
        assert w == ROLL_WORD, f"shipped.json roll {w} != ROLL_WORD {ROLL_WORD}: update ROLL_WORD"
    assert len(ROLL_WORD) == N_MODULES - 1 and set(ROLL_WORD) <= set("0123")
    return [int(d) for d in ROLL_WORD]


# ----------------------------------------------------------------------------- the half-cube polytope
def halfspaces(sign):
    """(unit normal, offset) pairs; the solid is {p : n.p <= h for all}. sign=+1 moving, -1 still."""
    a, c = CUBE / 2, CHAMFER
    hs = []
    for i in range(3):
        for s in (1, -1):
            d = np.zeros(3); d[i] = s; hs.append((d, a))
    for i, j in ((0, 1), (1, 2), (2, 0)):                       # |x-y|, |y-z|, |z-x| <= 2a - c
        for s in (1, -1):
            d = np.zeros(3); d[i] = s; d[j] = -s; hs.append((d / np.sqrt(2), (2 * a - c) / np.sqrt(2)))
    hs.append((-sign * AXIS, 0.0))                              # sign * (x+y+z) >= 0
    # neck: r <= NECK_R0 + NECK_SLOPE*|t| as an NECK_SIDES-gon cone (inradius = the cone)
    e1 = np.array([1, -1, 0]) / np.sqrt(2); e2 = np.array([1, 1, -2]) / np.sqrt(6)
    for k in range(NECK_SIDES):
        phi = 2 * np.pi * (k + 0.5) / NECK_SIDES
        u = np.cos(phi) * e1 + np.sin(phi) * e2                   # u.p = radial coordinate along this azimuth
        d = u - NECK_SLOPE * sign * AXIS                          # u.p - slope*|t| <= r0
        hs.append((d / np.linalg.norm(d), NECK_R0 / 1000 / np.linalg.norm(d)))
    return hs


def polytope_vertices(sign):
    hs = halfspaces(sign)
    A = np.array([np.append(d, -h) for d, h in hs])              # scipy wants  d.p + b <= 0
    interior = sign * AXIS * 0.02                                # 20 mm up the axis: inside the neck
    V = HalfspaceIntersection(A, interior).intersections
    return np.unique(np.round(V, 9), axis=0)


def hull_triangles(V):
    """Outward-wound triangles of the convex hull of V."""
    hull = ConvexHull(V); centre = V[hull.vertices].mean(axis=0); tris = []
    for simp in hull.simplices:
        a, b, c = V[simp]
        if np.dot(np.cross(b - a, c - a), a - centre) < 0:
            b, c = c, b
        tris.append((a, b, c))
    return tris


def write_stl(path, tris):
    with open(path, "wb") as f:
        f.write(b"cubot half-cube, metres".ljust(80, b"\0") + struct.pack("<I", len(tris)))
        for a, b, c in tris:
            n = np.cross(b - a, c - a); n /= np.linalg.norm(n)
            f.write(struct.pack("<12fH", *n, *a, *b, *c, 0))


def mass_properties(tris, mass):
    """Volume, centre of mass and inertia about the COM of a uniform solid bounded by
    outward-wound triangles (tetrahedra against the origin, signed)."""
    vol = 0.0; first = np.zeros(3); second = np.zeros((3, 3))
    for a, b, c in tris:
        v = np.linalg.det(np.array([a, b, c])) / 6.0
        vol += v
        first += v * (a + b + c) / 4.0
        s = a + b + c
        second += v / 20.0 * (np.outer(a, a) + np.outer(b, b) + np.outer(c, c) + np.outer(s, s))
    rho = mass / vol
    com = first / vol
    I0 = rho * (np.trace(second) * np.eye(3) - second)                # about the origin
    I = I0 - mass * (np.dot(com, com) * np.eye(3) - np.outer(com, com))   # about the COM
    return vol, com, I


def support(V, d):
    return (V @ d).max()


# ----------------------------------------------------------------------------- URDF
def urdf_link(name, sign, com, I, spacer):
    mesh = "meshes/moving.stl" if sign > 0 else "meshes/still.stl"
    mat = "moving" if sign > 0 else "still"
    sp = ""
    if spacer:
        sx, sy, sz = SPACER
        sp = f"""    <visual>
      <origin xyz="{CUBE/2 + sx/2:.6f} 0 0" rpy="0 0 0"/>
      <geometry><box size="{sx} {sy} {sz}"/></geometry>
      <material name="spacer"/>
    </visual>
    <collision>
      <origin xyz="{CUBE/2 + sx/2:.6f} 0 0" rpy="0 0 0"/>
      <geometry><box size="{sx} {sy} {sz}"/></geometry>
    </collision>
"""
    return f"""  <link name="{name}">
    <visual>
      <geometry><mesh filename="{mesh}"/></geometry>
      <material name="{mat}"/>
    </visual>
    <collision>
      <geometry><mesh filename="{mesh}"/></geometry>
    </collision>
{sp}    <inertial>
      <origin xyz="{com[0]:.8f} {com[1]:.8f} {com[2]:.8f}" rpy="0 0 0"/>
      <mass value="{HALF_MASS}"/>
      <inertia ixx="{I[0,0]:.8e}" ixy="{I[0,1]:.8e}" ixz="{I[0,2]:.8e}" iyy="{I[1,1]:.8e}" iyz="{I[1,2]:.8e}" izz="{I[2,2]:.8e}"/>
    </inertial>
  </link>
"""


def build_urdf(roll, props):
    out = ['<?xml version="1.0"?>',
           "<!-- Generated by build_cubot_urdf.py; edit that script, not this file.",
           f"     27 x 80 mm cubes, <111> hinge, 8 mm equatorial chamfers + CAD neck profile, {GAP*1000:.1f} mm gap (pitch {PITCH*1000:.1f} mm),",
           f"     shipped roll word {ROLL_WORD} (right-hand about +X, toward module 27). Units: m, rad, kg. -->",
           '<robot name="cubot_shipped">',
           '  <mujoco><compiler meshdir="." discardvisual="false" fusestatic="false" balanceinertia="true"/></mujoco>',
           "",
           f'  <material name="still"><color rgba="{COL_STILL}"/></material>',
           f'  <material name="moving"><color rgba="{COL_MOVING}"/></material>',
           f'  <material name="spacer"><color rgba="{COL_SPACER}"/></material>', ""]
    for i in range(1, N_MODULES + 1):
        s, m = f"m{i:02d}_still", f"m{i:02d}_moving"
        out.append(f"  <!-- ==================== module {i:02d} ==================== -->")
        out.append(urdf_link(s, -1, props[-1]["com"], props[-1]["I"], spacer=False))
        out.append(urdf_link(m, +1, props[+1]["com"], props[+1]["I"], spacer=i < N_MODULES))
        out.append(f"""  <joint name="servo{i:02d}" type="continuous">
    <parent link="{s}"/>
    <child link="{m}"/>
    <origin xyz="0 0 0" rpy="0 0 0"/>
    <axis xyz="{AXIS[0]:.8f} {AXIS[1]:.8f} {AXIS[2]:.8f}"/>
    <limit effort="{EFFORT_NM}" velocity="{VELOCITY_RAD}"/>
  </joint>
""")
        if i < N_MODULES:
            r = roll[i - 1]
            out.append(f"""  <joint name="mount{i:02d}_{i + 1:02d}" type="fixed">
    <!-- roll digit {r}: module {i + 1} mounted {r * 90} deg about +X relative to module {i} -->
    <parent link="{m}"/>
    <child link="m{i + 1:02d}_still"/>
    <origin xyz="{PITCH:.4f} 0 0" rpy="{r * np.pi / 2:.8f} 0 0"/>
  </joint>
""")
    out.append("</robot>\n")
    return "\n".join(out)


# ----------------------------------------------------------------------------- MJCF (same data, plus a free base)
def build_mjcf(roll, props):
    def inertial(sign):
        c, I = props[sign]["com"], props[sign]["I"]
        full = f"{I[0,0]:.8e} {I[1,1]:.8e} {I[2,2]:.8e} {I[0,1]:.8e} {I[0,2]:.8e} {I[1,2]:.8e}"
        return f'<inertial pos="{c[0]:.8f} {c[1]:.8f} {c[2]:.8f}" mass="{HALF_MASS}" fullinertia="{full}"/>'
    sx, sy, sz = SPACER
    ind = lambda d: "  " * d
    body = []
    depth = 2
    for i in range(1, N_MODULES + 1):
        s, m = f"m{i:02d}_still", f"m{i:02d}_moving"
        if i == 1:
            body.append(f'{ind(depth)}<body name="{s}" pos="0 0 {CUBE/2:.4f}">')
            body.append(f'{ind(depth+1)}<freejoint name="root"/>')
        else:
            r = roll[i - 2]; h = r * np.pi / 4
            body.append(f'{ind(depth)}<body name="{s}" pos="{PITCH:.4f} 0 0" quat="{np.cos(h):.8f} {np.sin(h):.8f} 0 0">')
        depth += 1
        body.append(f'{ind(depth)}{inertial(-1)}')
        body.append(f'{ind(depth)}<geom class="still" mesh="still"/>')
        body.append(f'{ind(depth)}<body name="{m}">')
        depth += 1
        body.append(f'{ind(depth)}<joint name="servo{i:02d}" axis="{AXIS[0]:.8f} {AXIS[1]:.8f} {AXIS[2]:.8f}"/>')
        body.append(f'{ind(depth)}{inertial(+1)}')
        body.append(f'{ind(depth)}<geom class="moving" mesh="moving"/>')
        if i < N_MODULES:
            body.append(f'{ind(depth)}<geom class="spacer" pos="{CUBE/2 + sx/2:.6f} 0 0" size="{sx/2} {sy/2} {sz/2}"/>')
    for d in range(depth - 1, 1, -1):
        body.append(f"{ind(d)}</body>")
    acts = "\n".join(f'    <position class="servo" name="servo{i:02d}" joint="servo{i:02d}"/>' for i in range(1, N_MODULES + 1))
    return f"""<!-- Generated by build_cubot_urdf.py; edit that script, not this file.
     Same chain as cubot_shipped.urdf, with a free base so it lies loose on the table. -->
<mujoco model="cubot_shipped">
  <compiler angle="radian" meshdir="meshes" autolimits="true"/>
  <option timestep="0.002" integrator="implicitfast"/>

  <default>
    <joint damping="0.05" armature="0.005"/>
    <geom friction="0.8 0.01 0.001"/>
    <default class="still"><geom type="mesh" rgba="{COL_STILL}"/></default>
    <default class="moving"><geom type="mesh" rgba="{COL_MOVING}"/></default>
    <default class="spacer"><geom type="box" rgba="{COL_SPACER}"/></default>
    <default class="servo">
      <!-- a stiff position servo holding whatever detent it is commanded; force-capped at the planner's default -->
      <position kp="30" kv="1" ctrlrange="-4.18879 4.18879" forcerange="-{EFFORT_NM} {EFFORT_NM}"/>
    </default>
  </default>

  <asset>
    <mesh name="still" file="still.stl"/>
    <mesh name="moving" file="moving.stl"/>
  </asset>

  <worldbody>
{chr(10).join(body)}
  </worldbody>

  <actuator>
{acts}
  </actuator>
</mujoco>
"""


SCENE = """<mujoco model="cubot shipped scene">
  <!-- Load THIS file. It adds the floor, lights and camera around the chain in cubot_shipped.xml. -->
  <include file="cubot_shipped.xml"/>

  <statistic center="1.07 0 0.05" extent="2.4"/>
  <visual>
    <headlight diffuse="0.6 0.6 0.6" ambient="0.3 0.3 0.3" specular="0 0 0"/>
    <rgba haze="0.15 0.25 0.35 1"/>
    <global azimuth="140" elevation="-25" offwidth="1920" offheight="1080"/>
    <map znear="0.01"/>
  </visual>
  <asset>
    <texture type="skybox" builtin="gradient" rgb1="0.3 0.5 0.7" rgb2="0 0 0" width="512" height="3072"/>
    <texture type="2d" name="groundplane" builtin="checker" mark="edge" rgb1="0.2 0.3 0.4" rgb2="0.1 0.2 0.3"
             markrgb="0.8 0.8 0.8" width="300" height="300"/>
    <material name="groundplane" texture="groundplane" texuniform="true" texrepeat="5 5" reflectance="0.2"/>
  </asset>
  <worldbody>
    <light pos="0 0 3" dir="0 0 -1" directional="true"/>
    <light pos="1.5 -1.5 2" dir="-0.4 0.4 -1" diffuse="0.4 0.4 0.4"/>
    <geom name="floor" type="plane" size="0 0 0.05" material="groundplane"/>
  </worldbody>
</mujoco>
"""


# ----------------------------------------------------------------------------- main
def main():
    roll = roll_word()
    os.makedirs(os.path.join(HERE, "meshes"), exist_ok=True)
    props = {}
    for sign, name in ((+1, "moving"), (-1, "still")):
        V = polytope_vertices(sign); tris = hull_triangles(V)
        write_stl(os.path.join(HERE, "meshes", f"{name}.stl"), tris)
        vol, com, I = mass_properties(tris, HALF_MASS)
        props[sign] = dict(V=V, vol=vol, com=com, I=I)
        r111 = max(np.linalg.norm(p - np.dot(p, AXIS) * AXIS) for p in V)
        print(f"{name:6s}: {len(V)} vertices, {len(tris)} tris, volume {vol*1e6:.2f} cm3, "
              f"COM along <111> = {np.dot(com, AXIS)*1000:+.3f} mm, r111 = {r111*1000:.3f} mm, "
              f"support <111> = {support(V, sign*AXIS)*1000:.3f} mm")
    with open(os.path.join(HERE, "cubot_shipped.urdf"), "w") as f:
        f.write(build_urdf(roll, props))
    with open(os.path.join(HERE, "cubot_shipped.xml"), "w") as f:
        f.write(build_mjcf(roll, props))
    with open(os.path.join(HERE, "scene.xml"), "w") as f:
        f.write(SCENE)
    print(f"wrote cubot_shipped.urdf, cubot_shipped.xml, scene.xml, meshes/still.stl, meshes/moving.stl "
          f"(roll {''.join(map(str, roll))}, pitch {PITCH*1000:.1f} mm)")


if __name__ == "__main__":
    main()
