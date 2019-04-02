# This file is part electronic_mail_template module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import fields
from trytond.pool import PoolMeta

__all__ = ['ActionReport']


class ActionReport:
    "Action report"
    __name__ = 'ir.action.report'
    __metaclass__ = PoolMeta
    file_name = fields.Char('File Name Pattern', translate=True,
        help='File name e-mail attachment without extension. '
        'with a syntax according to the engine that will be used in the template. '
        'eg. sale_${record.reference}')
