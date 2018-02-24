import orm
import asyncio
from models import User, Blog, Comment

async def test():
    await orm.create_pool(loop=loop, user='user1', password='password', db='user1')
    u1 = User(name='Test', email='test@example.com', passwd='1234567890', admin=0, image='about:blank')
    u2 = User(name='Test1', email='test1@example.com', passwd='1234567890', admin=0, image='about:blank')
    u3 = User(name='Test2', email='test2@example.com', passwd='1234567890', admin=0, image='about:blank')
    await u1.save()
    await u2.save()
    await u3.save()
    x = await User.findAll()
    for y in x: print(y)
    await orm.destory_pool()

loop = asyncio.get_event_loop()
loop.run_until_complete(test())
loop.close()
