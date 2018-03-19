import logging; logging.basicConfig(level=logging.INFO)

import asyncio
import os
import json
import time
from datetime import datetime
from aiohttp import web
from jinja2 import Environment, FileSystemLoader

from config import configs

import orm
from coroweb import add_routes, add_static
from handlers import cookie2user, COOKIE_NAME

def init_jinja2(app, **kw):
    logging.info('init jinja2...')
    options = dict(
        autoescape = kw.get('autoescape', True),
        block_start_string = kw.get('block_start_string', '{%'),
        block_end_string = kw.get('block_end_string', '%}'),
        variable_start_string = kw.get('variable_start_string', '{{'),
        variable_end_string = kw.get('variable_end_string', '}}'),
        auto_reload = kw.get('auto_reload', True)
    )
    path = kw.get('path', None)
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    logging.info(f'set jinja2 template path: {path}')
    env = Environment(loader=FileSystemLoader(path), **options)
    filters = kw.get('filters', None)
    if filters is not None:
        for name, f in filters.items():
            env.filters[name] = f
    app['__templating__'] = env

@web.middleware
async def logger(request, handler):
    logging.info(f'Request: {request.method} {request.path}')
    # await asyncio.sleep(0.3)
    return (await handler(request))

@web.middleware
async def auth(request, handler):
    logging.info(f'check user: {request.method} {request.path}')
    request.__user__ = None
    cookie_str = request.cookies.get(COOKIE_NAME)
    if cookie_str:
        user = await cookie2user(cookie_str)
        if user:
            logging.info('set current user: %s' % user.email)
            request.__user__ = user
    if request.path.startswith('/manage/') and (request.__user__ is None or not request.__user__.admin):
        return web.HTTPFound('/signin')
    return (await handler(request))

@web.middleware
async def parse_data(request, handler):
    if request.method == 'POST':
        if request.content_type.startswith('application/json'):
            request.__data__ = await request.json()
            logging.info(f'request json: {request.__data__}')
        elif request.content_type.startswith('application/x-www-form-urlencoded'):
            request.__data__ = await request.multipart()
            logging.info(f'request form: {request.__data__}')
    return (await handler(request))

@web.middleware
async def response(request, handler):
    logging.info('Response handler...')
    r = await handler(request)
    if isinstance(r, web.StreamResponse):
        return r
    if isinstance(r, bytes):
        resp = web.Response(body=r)
        resp.content_type = 'application/octet-stream'
        return resp
    if isinstance(r, str):
        if r.startswith('redirect:'):
            return web.HTTPFound(r[9:])
        resp = web.Response(body=r.encode('utf-8'))
        resp.content_type = 'text/html;charset=utf-8'
        return resp
    if isinstance(r, dict):
        template = r.get('__template__')
        if template is None:
            resp = web.Response(body=json.dumps(r, ensure_ascii=False, default=lambda o: o.__dict__).encode('utf-8'))
            resp.content_type = 'application/json;charset=utf-8'
            return resp
        else:
            r['__user__'] = request.__user__
            resp = web.Response(body=request.app['__templating__'].get_template(template).render(**r).encode('utf-8'))
            resp.content_type = 'text/html;charset=utf-8'
            return resp
    if isinstance(r, int) and r >= 100 and r < 600:
        return web.Response(status=r)
    if isinstance(r, tuple) and len(r) == 2:
        t, m = r
        if isinstance(t, int) and t >= 100 and t < 600:
            return web.Response(status=t, body=str(m).encode())
    # default:
    resp = web.Response(body=str(r).encode('utf-8'))
    resp.content_type = 'text/plain;charset=utf-8'
    return resp

def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:
        return u'1分钟前'
    if delta < 3600:
        return f'{delta // 60}分钟前'
    if delta < 86400:
        return f'{delta // 3600}小时前'
    if delta < 604800:
        return f'{delta // 86400}天前'
    dt = datetime.fromtimestamp(t)
    return f'{dt.year}年{dt.month}月{dt.day}日'

async def init(loop):
    await orm.create_pool(loop=loop, host='127.0.0.1', port=3306, user='user1', password='Hg4oHqJPmmbbWBoW', db='user1')
    #创建一个web服务器对象
    app = web.Application(loop=loop, middlewares=[logger, auth, parse_data, logger, response])
    #初始化jinja2
    init_jinja2(app, filters=dict(datetime=datetime_filter))
    #关联链接地址和对应的处理函数
    add_routes(app, 'handlers')
    add_static(app)
    # app.router.add_route('GET', '/', index)
    #获得web服务器
    srv = await loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    logging.info('server started at http://127.0.0.1:9000...')
    return srv

loop = asyncio.get_event_loop()
loop.run_until_complete(init(loop))
loop.run_forever()
