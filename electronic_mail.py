# This file is part electronic_mail_template module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import fields
from trytond.pool import PoolMeta


class ElectronicMail(metaclass=PoolMeta):
    __name__ = 'electronic.mail'
    template = fields.Many2One('electronic.mail.template', 'Template')

    @classmethod
    def check_xml_record(cls, records, values):
        '''It should be possible to overwrite templates'''
        return True

    @classmethod
    def _get_delivery_settings(cls, mail):
        if mail.template:
            return mail.template.smtp_server, mail.template.draft_mailbox
        return super()._get_delivery_settings(mail)
