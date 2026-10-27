import json
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.services import datasets


@pytest.mark.parametrize('values', [[10, 20], [float('nan'), 20], [None, None]])
def test_normal_missing_and_empty_statistics_are_json_safe(values):
    _, columns, quality = datasets.profile_frame(pd.DataFrame({'revenue': values}))
    json.dumps({'columns': columns, 'quality': quality}, allow_nan=False)


@pytest.mark.parametrize('raw', [b'revenue\nInfinity\n', b'revenue\n1e308\n1e308\n'])
def test_nonfinite_input_or_calculated_statistics_never_become_ready(raw):
    engine = create_engine('sqlite://')
    with Session(engine) as db:
        ds = datasets.ingest(db, {'username': 'test'}, 'Invalid numbers', raw, '.csv')
        assert ds.status == 'FAILED'
        assert db.get(Dataset, ds.id).status == 'FAILED'
        assert not any(name.startswith('dataset_') for name in inspect(engine).get_table_names())
        json.dumps(datasets.public(ds), allow_nan=False)
    engine.dispose()


def test_public_legacy_metadata_does_not_emit_nonfinite_numbers():
    ds = SimpleNamespace(id='test', name='Legacy', owner='test', status='READY', source_type='csv',
        created_at=None, updated_at=None, row_count=1, column_count=1,
        profile={'columns': [{'name':'revenue', 'statistics':{'mean':float('inf')}}]},
        semantics={}, capabilities={}, quality={}, error=None)
    result = datasets.public(ds)
    assert result['schema']['columns'][0]['statistics']['mean'] is None
    json.dumps(result, allow_nan=False)
