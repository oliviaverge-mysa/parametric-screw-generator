"""Interactive plain-text screw query preview."""

from __future__ import annotations

import argparse

from ..assembly import make_screw_from_query
from ..export import export_step, export_stl, out_path


def _prompt(message: str) -> str:
    return input(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build one screw from plain-text dimensions.")
    parser.add_argument(
        "--query",
        type=str,
        default="",
        help="Plain text query, e.g. \"pan head, head diameter 8, head height 4, shank diameter 4, root diameter 3, length 25, tip length 3, pitch 1, thread length 20\"",
    )
    parser.add_argument("--stl", action="store_true", help="Also export STL.")
    parser.add_argument("--stl-tol", type=float, default=0.25, help="STL linear tolerance.")
    parser.add_argument("--stl-ang", type=float, default=0.35, help="STL angular tolerance.")
    args = parser.parse_args()

    query = args.query.strip() or input("Search screw: ").strip()
    screw = make_screw_from_query(query, prompt=_prompt)
    step_path = export_step(screw, out_path("screws", "step", "screw_from_query.step"))
    print(f"STEP -> {step_path}")
    if args.stl:
        stl_path = export_stl(
            screw,
            out_path("screws", "stl", "screw_from_query.stl"),
            tolerance=args.stl_tol,
            angular_tolerance=args.stl_ang,
        )
        print(f"STL  -> {stl_path}")
    print("Done.")


if __name__ == "__main__":
    main()

