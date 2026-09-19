#!/usr/bin/env python3
"""measure_cad_profile.py — where the chamfer and the neck cone in build_cubot_urdf.py come from.

Reads the printed CAD (binary STL), takes each part's CONVEX HULL (outer profile only) and prints
  * support in the cube's face / edge / corner directions  -> the 8 mm equatorial-edge chamfer
  * r_max(t): max radius from the <111> hinge axis per 1 mm slab of height t  -> NECK_R0 / NECK_SLOPE
  * a superset check of the generated half-cube solids against the CAD hulls.

Run:  python3 measure_cad_profile.py [--cad ~/Desktop/CuBot\\ CAD] [--parts ~/Desktop/Microbots]
"""
import argparse, os, struct, sys
import numpy as np
from scipy.spatial import ConvexHull

N = np.ones(3) / np.sqrt(3)


def read_stl(path):
    b = open(path, "rb").read()
    n = struct.unpack("<I", b[80:84])[0]
    a = np.frombuffer(b[84:84 + n * 50], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return a["v"].reshape(-1, 3).astype(float)


def hull_points(*files):
    P = np.vstack([np.unique(np.round(read_stl(f), 4), axis=0) for f in files])
    return P[ConvexHull(P).vertices]


def supports(P):
    import itertools
    print("  support h(d) = max d.p  (ideal 80 mm cube: face 40, edge 56.57, corner 69.28)")
    for label, dirs in (("edge", [d for d in itertools.product([-1, 0, 1], repeat=3) if sum(map(abs, d)) == 2]),
                        ("corner", [d for d in itertools.product([-1, 1], repeat=3)])):
        for d in dirs:
            dn = np.array(d, float) / np.linalg.norm(d)
            print(f"    {label:6s} {str(d):14s} h = {(P @ dn).max():7.2f}")


def profile(P, lo, hi, step=1.0):
    """r_max of the hull SURFACE in each slab [t, t+step): hull vertices plus hull-edge crossings."""
    t = P @ N; r = np.linalg.norm(P - np.outer(t, N), axis=1)
    H = ConvexHull(P); E = np.array(list({tuple(sorted((s[i], s[(i + 1) % 3]))) for s in H.simplices for i in range(3)}))
    out = {}
    for a in np.arange(lo, hi, step):
        sel = (t >= a) & (t < a + step); rm = r[sel].max() if sel.any() else 0.0
        for tp in (a, a + step):
            ta, tb = t[E[:, 0]], t[E[:, 1]]; cross = (ta - tp) * (tb - tp) < 0
            if cross.any():
                w = (tp - ta[cross]) / (tb[cross] - ta[cross])
                Q = P[E[cross, 0]] + w[:, None] * (P[E[cross, 1]] - P[E[cross, 0]])
                rm = max(rm, np.linalg.norm(Q - np.outer(Q @ N, N), axis=1).max())
        out[a] = rm
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cad", default=os.path.expanduser("~/Desktop/CuBot CAD"))
    ap.add_argument("--parts", default=os.path.expanduser("~/Desktop/Microbots"))
    a = ap.parse_args()
    top = hull_points(f"{a.cad}/Top.stl")
    hub = hull_points(f"{a.cad}/Hub_Still.stl")
    still = hull_points(f"{a.parts}/MicroBots_Bottom_V12.stl", f"{a.cad}/Hub_Still.stl")

    print("Top.stl (moving half) — the chamfer shows as edge support 51.02 (= (80-7.85)/sqrt2) on the six")
    print("equatorial edges, corner support 64.66 (= 112/sqrt3) on the three equatorial corners:")
    supports(top)
    print(f"  r111 (max radius about <111>) = {np.linalg.norm(top - np.outer(top @ N, N), axis=1).max():.3f}  (8 mm chamfer ridge = 58.788)")

    pt, ps, ph = profile(top, 0, 30), profile(still, -30, 0), profile(hub, 0, 18)
    print("\nOuter profile r_max(t), mm, per 1 mm slab.  profile = max(moving at +t, still at -t, hub at +t)")
    print("  |t|    moving(Top)   still(Bottom+Hub, at -t)   hub cone (t>0)   -> knot")
    knots = []
    for k in range(0, 17):
        mv, st, hb = pt.get(float(k), 0), ps.get(float(-k - 1), 0), ph.get(float(k), 0)
        knots.append((k, round(max(mv, st, hb), 2)))
        print(f"  {k:3d}    {mv:8.2f}      {st:8.2f}                  {hb:8.2f}          {knots[-1][1]:.2f}")
    print("measured knots =", knots)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import build_cubot_urdf as b
        margin = min(b.NECK_R0 + b.NECK_SLOPE * t - r for t, r in knots)
        print(f"cone r = {b.NECK_R0} + {b.NECK_SLOPE}*|t| vs measured slabs: min margin {margin:+.3f} mm ({'OK, contains the profile' if margin >= 0 else 'TOO TIGHT'})")
    except Exception as e:  # noqa
        print("(no generator found:", e, ")")

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import build_cubot_urdf as b
        print("\nSuperset check of the generated solids (worst CAD hull vertex outside the model, mm; <= 0 is a superset,")
        print("+0.11 is the 8.00 mm nominal chamfer vs the 7.85 mm printed one):")
        for sign, label, P in ((+1, "moving vs Top.stl", top), (-1, "still vs Bottom+Hub (t<=0)", still[still @ N <= 0])):
            print(f"  {label}: {max(((P @ d) - h * 1000).max() for d, h in b.halfspaces(sign)):+.3f}")
        hs = [(d, h) for d, h in b.halfspaces(+1) if abs(abs(d @ N) - 1) > 1e-9]
        print(f"  hub cone (t>0) inside the MOVING half's solid: {max(((hub[hub @ N > 0] @ d) - h * 1000).max() for d, h in hs):+.3f}")
    except Exception as e:  # noqa
        print("(skipped superset check:", e, ")")


if __name__ == "__main__":
    main()
