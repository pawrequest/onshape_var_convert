"""Parse Onshape document URLs."""

from __future__ import annotations

import re
from dataclasses import dataclass

_URL = re.compile(
    r'/documents/(?P<did>[0-9a-f]{24})/(?P<wvm>[wvm])/(?P<wvmid>[0-9a-f]{24})'
    r'(?:/e/(?P<eid>[0-9a-f]{24}))?'
)


@dataclass(frozen=True)
class Location:
    did: str
    wvm: str
    wvmid: str
    eid: str | None = None

    def require_workspace(self) -> None:
        if self.wvm != 'w':
            raise ValueError(
                'Writes require a workspace URL (/w/...); versions and microversions are immutable.'
            )

    def require_element(self) -> str:
        if not self.eid:
            raise ValueError('URL must include an element (/e/...).')
        return self.eid


def parse_url(url: str) -> Location:
    match = _URL.search(url)
    if not match:
        raise ValueError(f'Not a recognised Onshape document URL: {url}')
    return Location(match['did'], match['wvm'], match['wvmid'], match['eid'])
