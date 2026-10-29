"""Final bounded modeling audit and full-building walls-only counterfactual."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback
from typing import Any

from struct_agent.io.artifacts import create_run, sha256, write_json
from struct_agent.schemas import ErrorRecord
from .axis_review import review_axes
from .client import ETABSClient
from .comparison import compare
from .connection_audit import inspect_connections
from .contracts import ModelFormReviewSpec, ConnectionAuditSpec, ResidentialSpec, ETABSConfig
from .exceedance_causes import failed_metric_effect
from .opensees_reference import run_reference
from .reference_mesh import ReferenceMesh
from .residential import build_and_analyze
from .runtime import run_verification
from .tolerance import assess_comparison


def build_review(client: ETABSClient, request: ModelFormReviewSpec, directory: Path,
                 config: ETABSConfig) -> dict[str, Any]:
    """Read copied existing beams, then solve one fresh walls-only model."""
    audit = directory/'audit'
    create_run(audit,seed=0,inputs={'source_model':request.audit.model},config={'spec':request.audit.model_dump(mode='json')})
    inspected = inspect_connections(client,request.audit,audit)
    axes = review_axes(inspected,request.residential)
    write_json(audit/'axes.json',axes)
    if not axes['verified']:
        raise ValueError('Physical beam-axis mismatch; investigate before accepting a model-form difference')
    target = directory/'walls_only'
    create_run(target,seed=0,inputs={'parent_manifest':directory/'manifest.json'},
        config={'spec':request.residential.model_dump(mode='json'),'etabs':config.model_dump(mode='json')|{'connection_mode':'walls_only'}})
    result = build_and_analyze(client,request.residential,target,beam_theory='euler_comparison',
        wall_vertical_subdivisions=config.wall_vertical_subdivisions,connection_mode='walls_only')
    write_json(target/'worker_result.json',{'status':'SUCCESS' if result['verified'] else 'INVALID_RESULT','result':result})
    return {'verified':result['verified'] and axes['verified'],'axes':axes['beams_reviewed'],
        'engineering_feasibility':'NOT_EVALUATED'}


def run_review(source: Path, previous: Path, directory: Path, report: Path) -> dict[str, Any]:
    source, previous, directory, report = (p.resolve() for p in (source,previous,directory,report))
    if report.exists():
        raise FileExistsError(report)
    manifest_path = source/'archived_inputs'/'residential_mesh4'/'etabs'/'manifest.json'
    spec = ResidentialSpec.model_validate_json(json.dumps(json.loads(manifest_path.read_text(encoding='utf-8'))['config']['spec']))
    original = json.loads((source/'assessment.json').read_text(encoding='utf-8'))['structures']['residential_mesh4']
    mapping_path = previous/'etabs'/'pinned_bending'/'model_mapping.json'
    model = mapping_path.parent/'model.EDB'
    mapping = json.loads(mapping_path.read_text(encoding='utf-8'))
    names = tuple(o['etabs_object'] for o in mapping['objects'] if o['story']==1 and o['role']!='wall')
    create_run(directory,seed=0,inputs={'source_manifest':manifest_path,'original_assessment':source/'assessment.json',
        'previous_mapping':mapping_path,'previous_model':model,'previous_results':previous/'results.json'},
        config={'purpose':'FINAL_MODEL_FORM_REVIEW','spec':spec.model_dump(mode='json'),
            'counterfactual':'remove all beam stiffness, retain original prescribed floor mass and load points'})
    try:
        outcome = run_verification(ModelFormReviewSpec(residential=spec,audit=ConnectionAuditSpec(
            model=model,model_sha256=sha256(model),frame_names=names,detailed_axes=True)),directory/'etabs',
            ETABSConfig(beam_theory='euler_comparison',wall_vertical_subdivisions=4,timeout_s=1200.))
        if outcome['status'] != 'SUCCESS':
            raise RuntimeError(f"Final review failed: {outcome['status']}; inspect retained worker error")
        effects, assessments, inputs = {}, {}, {}
        for name, mesh in (
                ('mvlem',ReferenceMesh(vertical_subdivisions=4,fiber_refinement=2,remove_beam_stiffness=True)),
                ('shell_dkgq',ReferenceMesh(vertical_subdivisions=4,wall_formulation='shell_dkgq',remove_beam_stiffness=True))):
            print('FINAL_PROBE '+name,flush=True)
            target = directory/'opensees'/name
            run_reference(spec,target,mesh=mesh)
            comparison = compare(directory/'etabs'/'walls_only',target,directory/'comparisons'/name)
            assessment = assess_comparison(comparison,spec.project.story_height_m)
            effects[name] = failed_metric_effect(original,assessment)
            assessments[name] = assessment
            inputs[name] = directory/'comparisons'/name/'comparison.json'
        result = {'purpose':'FINAL_MODEL_FORM_REVIEW','effects':effects,'assessments':assessments,
            'axes':json.loads((directory/'etabs'/'audit'/'axes.json').read_text(encoding='utf-8')),
            'production_implementation':'UNCHANGED','engineering_feasibility':'NOT_EVALUATED'}
        write_json(directory/'results.json',result)
        create_run(report,seed=0,inputs=inputs|{'results':directory/'results.json'},config={'purpose':'FINAL_MODEL_FORM_REVIEW'})
        write_json(report/'results.json',result)
        lines = ['# 整栋模型差异最终核对','',
            '原12层住宅、原质量与加载点；仅移除梁单元刚度。辅助点仅消除未连接的UZ/RX/RY空自由度。',
            '保留全部差异；原通过项不重开，反事实不替换生产模型。','',
            f"梁轴及物理惯性矩审计：{result['axes']['verified']}，{result['axes']['beams_reviewed']}根源梁。",'',
            '| 墙单元 | 原超限项 | 本探针进入5%以内 |','|---|---:|---:|']
        lines += [f"| {name} | {value['original_failed_count']} | {value['below_5_percent_in_probe']} |" for name,value in effects.items()]
        lines += ['','该探针用于归因；单一细网格结果不是真值，不能据此证明收敛或工程可行性。','']
        (report/'report.md').write_text('\n'.join(lines),encoding='utf-8')
        return result
    except Exception as error:
        record = ErrorRecord(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),
            context={'operation':'final model form review','directory':str(directory)},attempt=1)
        write_json(directory/'error.json',record.model_dump())
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('outputs/current/structural_comparison_01'))
    parser.add_argument('--previous',type=Path,default=Path('outputs/current/whole_connection_02'))
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    result = run_review(args.source,args.previous,args.run,args.report)
    print({name:row['below_5_percent_in_probe'] for name,row in result['effects'].items()})


if __name__ == '__main__':
    main()
