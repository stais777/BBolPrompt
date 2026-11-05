"""Read-only baseline and latest explicit user editions, with provenance checks."""
import copy,json,sqlite3
from pathlib import Path
from ..baseline import load_dataset,MASTER_SHA
from ..baseline_edits import digest as legacy_digest
from ..library import validate_tags
from ..sqlite_utils import ClosingConnection
from .common import digest


def read(db,records=None):
    records=load_dataset() if records is None else records
    frozen={r['card_id']:r for r in records};edits={}
    with sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True,factory=ClosingConnection) as c:
        c.row_factory=sqlite3.Row
        for row in c.execute('''SELECT x.* FROM baseline_tag_editions x WHERE revision=(
                SELECT max(revision) FROM baseline_tag_editions y WHERE y.card_id=x.card_id)'''):
            original=frozen[row['card_id']];tags=json.loads(row['tags_json'])
            if row['source_sha']!=original['source_text_sha256'] or row['original_sha']!=legacy_digest(original) or row['tags_sha']!=legacy_digest(tags):raise ValueError('베이스 수동 수정 이력 무결성 불일치')
            validate_tags(original['source_text'],tags)
            edits[row['card_id']]={'tags':tags,'revision':row['revision'],'sha':row['tags_sha']}
    cards=copy.deepcopy(records)
    for card in cards:
        if card['card_id'] in edits:
            edition=edits[card['card_id']]
            card.update(tags=edition['tags'],user_tag_revision=edition['revision'],user_tag_revision_sha256=edition['sha'])
    return {'cards':cards,'edited_card_ids':list(edits),'fingerprint':digest(edits),'master_sha256':MASTER_SHA}


def catalog(snapshot):
    return {'schema':'bbolprom-approved-gallery-readonly-v1','origin':{'master_sha256':MASTER_SHA},'cards':snapshot['cards']}
