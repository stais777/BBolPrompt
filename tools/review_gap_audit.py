"""Cross-check the additional 22-item audit without promoting proposals to approvals.

The stored audit is supplementary evidence, not a replacement for original user
approval transcripts. Never opens the deferred UI archive or executes attachments.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bbolprom_engine.baseline import MASTER_SHA, load_dataset

# Current implementation status, distinct from the supplied audit's claim about
# historic approval. Preserve each original CSV row separately below.
WORK={
 'GAP-01':('implemented_fixed_baseline_regression','109/110 원문과 순서 있는 1/14 이미지 참조 보존 시험. 과거 분리 코드 재현은 아님.'),
 'GAP-02':('original_evidence_missing','세 패키지에 v0.3.2 원본이 없다는 감사 보고. 검증 HTML을 그 파서로 부르지 않음.'),
 'GAP-03':('partial','고정 ID/운영 데이터 보호. 새 소스 버전의 동일성 비교·사용자 메타데이터 갱신은 미구현.'),
 'GAP-04':('partial','다른 SHA 입력은 거절하고 기존 데이터 유지. 버전별 소실 상태·갱신 기능은 미구현.'),
 'GAP-05':('recorded_pending_implementation','세컨드리 개념키와 상태 분리는 보고된 승인 설계로 기록. 관계표/검색/API 연결 미구현.'),
 'GAP-06':('reported_approval_missing_item_evidence','37/37 및 15묶음 유지 결과는 감사서 보고. 실제 15묶음 목록·원 승인표를 임의 생성하지 않음.'),
 'GAP-07':('original_evidence_missing','최종 Excel에는 가로1~2차 상세 탭만 확인. 3~7차의 행별 원 승인 로그는 재생성하지 않음.'),
 'GAP-08':('partial','기존 표준어 참조·미분류 저장·신규 편집 경로 있음. 사용자 확정/제외를 재분석에서 보존하는 계약은 후속.'),
 'GAP-09':('deferred_historical_proposal','반입 단위 통째 되돌리기는 초기 설계로 보존. 현재 백업 기능과 구분, 미구현.'),
 'GAP-10':('pending_implementation','소스 버전별 diff·불확실 대응 검토 미구현. 확정 PT 연결 경로에서 갱신 파일 자동 적용하지 않음.'),
 'GAP-11':('final_values_verified_history_attributed','223/227 E열 쪼리와 251 E열에서 맨발 설정 부재 확인. 승인 대화 원문 확인으로 확대하지 않음.'),
 'GAP-12':('verified_with_location_correction','역사 상태 문자열은 운영규칙 B3(현재 누적). 첨부의 A2:B2 위치 표기는 틀림. 원본 수정 안 함.'),
 'GAP-13':('current_schema_verified_old_schema_attributed','최종 J=이미지참조/O=원본프롬프트 확인. 과거 외형 보강본의 열 재사용은 감사서 보고로 구분.'),
 'GAP-14':('recorded_pending_video_source','이미지/영상 소스 역할 구분 기록. 실제 영상 원본·연계 흐름 미구현. UI 원본 보관 지시 유지.'),
 'GAP-15':('deferred_historical_proposal','10슬롯/인물 판별 상세는 과거안. 현재 확정 기능으로 승격하지 않음.'),
 'GAP-16':('deferred_historical_proposal','관계 그래프 및 제안/확정/제외 상태 일부는 과거 설계. 확정 관계 DB 보유로 주장하지 않음.'),
 'GAP-17':('deferred_historical_proposal','85/60 등 수치는 초기 제안. 현재 유사도 기준에 자동 적용하지 않음.'),
 'GAP-18':('deferred_UI','채택 추적 후보만 보존. UI ZIP은 계속 미분석·미구현.'),
 'GAP-19':('evidence_limit_recorded','원문/승인 데이터 일치와 이미지 픽셀 전수 시각검수는 별개. 전체 시각검수 완료라고 하지 않음.'),
 'GAP-20':('partial','원본/고정 baseline_cards/운영 cards 분리 및 보호. 사용자 태그 확정·제외 상태의 완전한 재분석 보존은 후속.'),
 'GAP-21':('recorded','필수 장문 판단 로그·검색어 사전 UI 없음. 내부 근거/해시/제공한 API 기준 출처 보존.'),
 'GAP-22':('deferred_historical_proposal','과거 .NET/WinForms/JSONL 제안을 현재 필수 기술요건으로 올리지 않음.'),
}


def review(master_path,out):
 import openpyxl
 folder=ROOT/'docs/handoff/gap-audit-20261105'
 master_path=Path(master_path)
 if Path(out).resolve()==master_path.resolve() or Path(out).resolve().is_relative_to(folder.resolve()):
  raise ValueError('Keep review output outside original evidence files')
 hashes={}
 for line in (folder/'SHA256SUMS.txt').read_text().splitlines():
  expected,name=line.split('  ',1)
  target=(folder/name).resolve()
  if not target.is_relative_to(folder.resolve()):raise ValueError('Unsafe audit path')
  actual=hashlib.sha256(target.read_bytes()).hexdigest()
  if actual!=expected:raise ValueError('Audit checksum mismatch: '+name)
  hashes[name]=actual
 with (folder/'03_누락목록_22항목.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
 if [r['번호'] for r in rows]!=['GAP-'+str(i).zfill(2) for i in range(1,23)]:raise ValueError('Gap ID mismatch')
 if hashlib.sha256(master_path.read_bytes()).hexdigest()!=MASTER_SHA:raise ValueError('Master hash mismatch')
 w=openpyxl.load_workbook(master_path,read_only=True,data_only=True)
 source=list(w['카드별태그'].values)
 cards={c['card_id']:c for c in load_dataset()}
 assert cards[109]['image_ref']=='image195'
 assert [i['ref'] for i in cards[110]['expected_images']]==['image'+str(i) for i in range(196,210)]
 assert cards[109]['source_text']!=cards[110]['source_text']
 assert '쪼리' in source[223][4].splitlines() and '쪼리' in source[227][4].splitlines()
 assert '맨발 설정' not in source[251][4].splitlines()
 assert source[0][9]=='이미지참조' and source[0][14]=='원본프롬프트'
 operating=list(w['운영규칙'].values)
 assert operating[2][0]=='현재 누적' and '사용자 승인 전' in operating[2][1]
 assert not any(any(s.startswith('가로'+str(i)+'차_') for i in range(3,8)) for s in w.sheetnames)
 actual_warning={'sheet':'운영규칙','key_cell':'A3','value_cell':'B3','value':operating[2][1]}
 w.close()
 result={'schema':'bbolprom-gap-audit-review-1','audit_package_sha256':'9361ecb0d79f4e5d8e4f42ebb5dfc8090699821e0dd6e8b7e9975d74f398986c',
  'original_member_sha256':hashes,'master_sha256':MASTER_SHA,'UI_zip_opened':False,
  'PT_present_or_rerun':False,'historic_approval_transcripts_reconstructed':False,
  'direct_checks':{'109_refs':['image195'],'110_refs':['image'+str(i) for i in range(196,210)],
                   '223_227_E_contains_쪼리':True,'251_E_excludes_맨발설정':True,'current_J_O_schema':True,
                   'historic_warning_actual_location':actual_warning,'horizontal_3_to_7_detail_sheets_absent':True},
  'corrections':[{'id':'GAP-12','audit_claim':'운영규칙 A2:B2','verified_location':'운영규칙 A3:B3',
                  'action':'Preserve attached document unchanged; annotate this review.'}],
  'items':[{'id':r['번호'],'supplied_audit_row':r,'source':{'path':'03_누락목록_22항목.csv','record':i+2,
             'sha256':hashes['03_누락목록_22항목.csv']},'work_status':WORK[r['번호']][0],'implementation_note':WORK[r['번호']][1]}
           for i,r in enumerate(rows)],
  'precedence':'Current user scope and original approvals/master win over attached audit recommendations. '
                'This audit is not proof of the missing row-level approvals and does not authorize deferred UI work.'}
 Path(out).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
 return result


if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--master',type=Path,required=True)
 p.add_argument('--out',type=Path,default=ROOT/'evaluation/gap-audit-review.json')
 a=p.parse_args();r=review(a.master,a.out)
 print(json.dumps({'items':len(r['items']),'member_hashes_verified':len(r['original_member_sha256']),
                   'corrections':r['corrections'],'UI_zip_opened':False},ensure_ascii=False))
