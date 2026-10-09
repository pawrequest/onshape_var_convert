import os

import pytest

from . import helpers


def pytest_collection_modifyitems(config, items):
    if os.environ.get('ONSHAPE_TEST_API_KEY'):
        return
    skip = pytest.mark.skip(reason='ONSHAPE_TEST_API_KEY (access:secret) not set')
    for item in items:
        if 'live' in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope='session')
def doc():
    client = helpers.client_from_env()
    return helpers.Doc(client, helpers.find_studio_eid(client))


@pytest.fixture(autouse=True)
def baseline(request):
    if 'live' not in request.keywords:
        yield
        return
    doc = request.getfixturevalue('doc')
    doc.reset()
    yield
    doc.reset()
