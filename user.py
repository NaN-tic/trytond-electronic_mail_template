from trytond.model import fields
from trytond.pool import PoolMeta

__all__ = ['User']


class User:
    __name__ = "res.user"
    __metaclass__ = PoolMeta

    smtp_server = fields.Many2One('smtp.server', 'SMTP Server',
        domain=[('state', '=', 'done')])
