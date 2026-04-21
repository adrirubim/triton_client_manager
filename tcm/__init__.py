"""
Compatibility package.

Historically the manager ran with `apps/manager` as CWD, making `tcm.*` a
top-level package. For repo-root module execution we proxy `tcm.*` to
`apps.manager.tcm.*` without sys.path mutation.
"""

from apps.manager.tcm.docker import *  # noqa: F401,F403
from apps.manager.tcm.job import *  # noqa: F401,F403
from apps.manager.tcm.openstack import *  # noqa: F401,F403
from apps.manager.tcm.triton import *  # noqa: F401,F403
from apps.manager.tcm.websocket import *  # noqa: F401,F403

