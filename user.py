from trytond.model import fields
from trytond.pool import PoolMeta

__all__ = ['User']


class User(metaclass=PoolMeta):
    __name__ = 'res.user'
    attachments = fields.One2Many('ir.attachment', 'resource', "Attachments")
