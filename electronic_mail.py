# This file is part electronic_mail_template module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import ModelView
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool

__all__ = ['ElectronicMail']


class ElectronicMail:
    __metaclass__ = PoolMeta
    __name__ = 'electronic.mail'

    @classmethod
    def __setup__(cls):
        super(ElectronicMail, cls).__setup__()
        cls._buttons.update({
                'send_mail': {
                    'invisible': ((Bool(Eval('body_plain') == '') &
                            Bool(Eval('body_html') == '')) |
                        ~Eval('flag_send')),
                    },
                })

    @classmethod
    def check_xml_record(cls, records, values):
        '''It should be possible to overwrite templates'''
        return True

    @classmethod
    @ModelView.button
    def send_mail(self, mails):
        Template = Pool().get('electronic.mail.template')
        for mail in mails:
            Template.send_mail(mail)
