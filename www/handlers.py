' url handlers '

import re
import time
import json
import logging
import hashlib
import base64
import asyncio
from aiohttp import web

from coroweb import get, post
from models import User, Blog, Comment, next_id

@get('/')
async def index(request):
    users = await User.findAll()
    return {
        '__template__': 'test.html',
        'users': users
    }