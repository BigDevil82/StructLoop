"""Explicit operator CLI for ETABS verification; not an LLM command executor."""
from __future__ import annotations

import argparse
from pathlib import Path

from struct_agent.adapters.etabs.contracts import CantileverSpec,ResidentialSpec,ETABSConfig
from struct_agent.adapters.etabs.runtime import run_verification
from struct_agent.schemas import ProjectSpec,LayoutCandidate,DesignCandidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',choices=('cantilever','residential'))
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=600.)
    parser.add_argument('--beam-theory',choices=('timoshenko','euler_comparison'),default='timoshenko')
    parser.add_argument('--wall-vertical-subdivisions',type=int,choices=(1,2,4),default=1)
    parser.add_argument('--reference-wall-subdivisions',type=int,choices=(1,2,4),default=1)
    parser.add_argument('--reference-fiber-refinement',type=int,choices=(1,2,4),default=1)
    parser.add_argument('--layout',type=Path)
    parser.add_argument('--spec',type=Path,default=Path('configs/etabs_12_story_spec.json'))
    parser.add_argument('--design',type=Path)
    parser.add_argument('--opensees-reference',type=Path)
    parser.add_argument('--comparison',type=Path)
    args = parser.parse_args()
    if (args.reference_wall_subdivisions!=1 or args.reference_fiber_refinement!=1 or args.comparison) and args.opensees_reference is None:
        parser.error('Reference mesh/comparison options require --opensees-reference')
    if args.case=='cantilever' and (args.beam_theory!='timoshenko' or args.wall_vertical_subdivisions!=1 or args.opensees_reference is not None):
        parser.error('Beam/mesh/reference comparison requires the residential diagnostic')
    spec: CantileverSpec | ResidentialSpec
    if args.case=='cantilever':
        spec = CantileverSpec()
    else:
        if args.layout is None or args.design is None:
            parser.error('residential requires --layout and --design')
        spec = ResidentialSpec(project=ProjectSpec.model_validate_json(args.spec.read_bytes()),
            layout=LayoutCandidate.model_validate_json(args.layout.read_bytes()),
            design=DesignCandidate.model_validate_json(args.design.read_bytes()))
    result = run_verification(spec,args.run,ETABSConfig(timeout_s=args.timeout,beam_theory=args.beam_theory,
        wall_vertical_subdivisions=args.wall_vertical_subdivisions))
    print(f"ETABS status={result['status']}; elapsed={result['elapsed_s']:.2f}s; run={args.run}")
    if result['status']!='SUCCESS':
        raise RuntimeError('ETABS verification failed; inspect preserved outcome and worker_error')
    if isinstance(spec,ResidentialSpec) and args.opensees_reference is not None:
        from struct_agent.adapters.etabs.opensees_reference import run_reference
        from struct_agent.adapters.etabs.reference_mesh import ReferenceMesh
        run_reference(spec,args.opensees_reference,mesh=ReferenceMesh(vertical_subdivisions=args.reference_wall_subdivisions,
            fiber_refinement=args.reference_fiber_refinement))
        if args.comparison is not None:
            from struct_agent.adapters.etabs.comparison import compare
            compare(args.run,args.opensees_reference,args.comparison)


if __name__=='__main__':
    main()
