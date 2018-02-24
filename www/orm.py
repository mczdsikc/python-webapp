import asyncio
import aiomysql
import logging; logging.basicConfig(level=logging.INFO)

def log(sql, args=()):
    logging.info('SQL: %s, args: %s' % (sql, args))

async def create_pool(loop=None, **kw):
    logging.info('create database connection pool...')
    global __pool
    __pool = await aiomysql.create_pool(
        host=kw.get('host', 'localhost'),
        port=kw.get('port', 3306),
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf8'),
        autocommit=kw.get('autocommit', True),
        maxsize=kw.get('maxsize', 10),
        minsize=kw.get('minsize', 1),
        loop=loop
    )

async def destory_pool():
    global __pool
    if __pool is not None :
        __pool.close()
        await __pool.wait_closed()

async def select(sql, args, size=None):
    log(sql, args)
    global __pool
    # with (await __pool) as conn:
    async with __pool.get() as conn:
        # cur = await conn.cursor(aiomysql.DictCursor)
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql.replace('?', '%s'), args or ())
            if size:
                rs = await cur.fetchmany(size)
            else:
                rs = await cur.fetchall()
        # await cur.close()
        logging.info('rows returned: %s' % len(rs))
        return rs

async def execute(sql, args, autocommit=True):
    log(sql,args)
    async with __pool.get() as conn:
        if not autocommit:
            await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?', '%s'), args)
                affected = cur.rowcount
            if not autocommit:
                await conn.commit()
        except:
            if not autocommit:
                await conn.rollback()
            raise
        return affected

def create_args(n):
    return ','.join(['?']*n)

class ModelMetaclass(type):

    def __new__(cls, name, bases, attrs):
        # 排除Model类本身:
        if name=='Model':
            return type.__new__(cls, name, bases, attrs)
        # 获取table名称:
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))
        # 获取所有的Field和主键名:
        mappings = dict()
        fields = []
        primaryKey = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info('  found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                if v.primary_key: # 找到主键（假设主键唯一）:
                    if primaryKey:
                        raise RuntimeError('Duplicate primary key for field: %s' % k)
                    primaryKey = k
                else:
                    fields.append(k)
        if not primaryKey:
            raise RuntimeError('Primary key not found.')
        # 删除找到的Field和主键
        for k in mappings.keys():
            attrs.pop(k)
        # 保存对应关系
        attrs['__primary_key__'] = primaryKey # 主键列名
        attrs['__fields__'] = fields # 除主键外的列名
        attrs['__mappings__'] = mappings # 所有列名=>类型
        attrs['__table__'] = tableName
        # 构造默认的SELECT, INSERT, UPDATE和DELETE语句:
        escaped_fields = ','.join([f'`{f}`' for f in fields])
        update_fields = ','.join([f'`{f}`=?' for f in fields])
        all_fields = escaped_fields + f',`{primaryKey}`'
        attrs['__select__'] = f'select {all_fields} from `{tableName}`'
        attrs['__insert__'] = f'insert into `{tableName}` ({all_fields}) values ({create_args(len(fields) + 1)})'
        attrs['__update__'] = f'update `{tableName}` set {update_fields} where `{primaryKey}`=?'
        attrs['__delete__'] = f'delete from `{tableName}` where `{primaryKey}`=?'
        return type.__new__(cls, name, bases, attrs)

class Model(dict, metaclass=ModelMetaclass):

    # def __init__(self, **kw):
    #     super(Model, self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'Model' object has no attribute '{key}'")

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):
        return getattr(self, key, None)

    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug(f'using default value for {key}: {value}')
                setattr(self, key, value)
        return value

    @classmethod
    async def find(cls, pk):
        ' find object by primary key. '
        rs = await select(f'{cls.__select__} where `{cls.__primary_key__}`=?', [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where. '
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        ' find objects by where clause. '
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update record: affected rows: %s' % rows)

    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)

class Field(object):

    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return f'<{self.__class__.__name__}, {self.column_type}:{self.name}>'

class StringField(Field):

    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(255)'):
        super().__init__(name, ddl, primary_key, default)

class IntegerField(Field):

    def __init__(self, name=None, primary_key=False, default=None):
        super().__init__(name, 'bigint', primary_key, default)

class BooleanField(Field):

    def __init__(self, name=None, default=None):
        super().__init__(name, 'boolean', False, default)

class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)

class TextField(Field):

    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)






