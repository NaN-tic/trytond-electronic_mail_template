from trytond.model import fields
from trytond.pool import PoolMeta

__all__ = ['Attachment']


class Attachment(metaclass=PoolMeta):
    __name__ = 'ir.attachment'
    email_template_cid = fields.Boolean('Is CID email Template?')
