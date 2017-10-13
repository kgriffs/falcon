# Copyright 2017 by Kurt Griffiths. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Uvicorn specializations."""

__all__ = ['UvAPI', 'UvRequest', 'UvResponse']

import sys

if sys.version_info < (3, 5):
    raise RuntimeError('The uv module requires Python 3.x >= 3.5')

from falcon.uv.api import UvAPI  # NOQA
from falcon.uv.request import UvRequest  # NOQA
from falcon.uv.response import UvResponse  # NOQA
