"""Command-line runner. All analysis is local and does not call any AI API."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from . import __version__
from .hwpx import HWPXReader,HWPXError
from .analysis import analyze
from .master import export_results,write_json
from .library import Library

DEFAULT_BASELINE=Path(__file__).resolve().parent.parent/'evaluation'/'reference'/'approved_baseline_309.json'

def analyze_file(src, out, *, segmentation='auto', knowledge='generic', hash_images=True):
    print('원본 HWPX 분석 시작 (승인 정답 파일은 열지 않습니다):',src, flush=True)
    with HWPXReader(src) as reader:
        result=analyze(reader,segmentation,hash_images,knowledge)
    export_results(out,result)
    print('분석 결과 생성:',str(Path(out)/'engine_result.json'), flush=True)
    print('카드 추정:',result['result_stats']['card_count'],
          '/ 이미지 참조:',result['result_stats']['image_references_resolved'],
          '/ 태그 초안:',result['result_stats']['tag_candidates'],flush=True)
    return result

def comparison(result, gold_path, out):
    from evaluation.compare import compare, save_comparison
    if Path(gold_path).resolve()==Path(out).resolve():raise ValueError('정답 파일과 결과 경로가 같습니다.')
    gold=json.loads(Path(gold_path).read_text(encoding='utf8'))
    report=compare(result,gold)
    save_comparison(Path(out),report)
    print('베이스화 비교 보고서:',str(Path(out)/'comparison.html'),flush=True)
    print('카드 완전일치:',report['source_count']['exact_text'],
          '/ 이미지 재현율:',report['image_references']['recall_pct'],
          '/ 태그 재현율:',report['tags']['recall_pct'], flush=True)
    return report

def main(argv=None):
    parser=argparse.ArgumentParser(prog='bbolprom',
        description='뽈프롬 독립 엔진: HWPX→태그 분류·정규화→하이라이팅→마스터·색인→검증')
    parser.add_argument('--version',action='version',version=__version__)
    sub=parser.add_subparsers(dest='cmd',required=True)
    def analysis_opts(p):
        p.add_argument('--input','-i',type=Path,required=True,help='실제 HWPX 원본')
        p.add_argument('--out','-o',type=Path,required=True,help='분석 결과 출력 폴더')
        p.add_argument('--segmentation',choices=('auto','structure','paragraph','blank'),default='auto')
        p.add_argument('--knowledge',choices=('generic','approved_terms'),default='generic',
            help='generic: 순수 규칙 / approved_terms: 승인된 표준 태그명만 참고(카드별 정답은 사용 안 함)')
        p.add_argument('--skip-image-hash',action='store_true',help='빠른 시험용; 등록은 불가능')
    pa=sub.add_parser('analyze',help='정답과 분리하여 독립 분석')
    analysis_opts(pa)
    pc=sub.add_parser('compare',help='이미 저장된 엔진 결과를 베이스화와 별도로 비교')
    pc.add_argument('--engine',type=Path,required=True)
    pc.add_argument('--baseline',type=Path,default=DEFAULT_BASELINE)
    pc.add_argument('--out','-o',type=Path,required=True)
    pt=sub.add_parser('test-pt',help='A안: PT 원본을 순수 분석 후 베이스화 정답과 비교')
    analysis_opts(pt)
    pt.add_argument('--baseline',type=Path,default=DEFAULT_BASELINE)
    pr=sub.add_parser('register',help='분석 결과의 중복 검토/명시적 승인 후 로컬 등록')
    pr.add_argument('--engine',type=Path,required=True)
    pr.add_argument('--input','-i',type=Path,required=True)
    pr.add_argument('--db',type=Path,required=True)
    pr.add_argument('--out',type=Path,required=True)
    pr.add_argument('--commit',action='store_true',help='검토한 결과를 실제 저장(기본: 읽기 전용 검토)')
    args=parser.parse_args(argv)
    try:
        if args.cmd in ('analyze','test-pt'):
            result=analyze_file(args.input,args.out,segmentation=args.segmentation,
                knowledge=args.knowledge,hash_images=not args.skip_image_hash)
            if args.cmd=='test-pt':comparison(result,args.baseline,args.out/'baseline_comparison')
        elif args.cmd=='compare':
            result=json.loads(args.engine.read_text(encoding='utf8'))
            comparison(result,args.baseline,args.out)
        elif args.cmd=='register':
            result=json.loads(args.engine.read_text(encoding='utf8'))
            if args.commit:library=Library(args.db)
            else:
                library=Library.__new__(Library)
                library.root=args.db.resolve();library.db=library.root/'library.sqlite3'
            plan={'decisions':library.plan(result),'source':'v0.3 library exact-text identity'}
            plan['summary']={name:sum(r['action']==name for r in plan['decisions']) for name in ('new_card','add_images','skip_identical')}
            if args.commit:library.commit_hwpx(args.input,result)
            args.out.mkdir(parents=True,exist_ok=True)
            write_json(args.out/'import_review.json',plan)
            print('중복 검토:',plan['summary'],flush=True)
            print('등록:', '실제 DB 반영됨' if args.commit else '미반영 · 검토 전용', flush=True)
    except (OSError,ValueError,HWPXError,json.JSONDecodeError) as exc:
        print('오류:',exc,file=sys.stderr)
        return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
