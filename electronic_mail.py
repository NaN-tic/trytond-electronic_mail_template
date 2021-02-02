# This file is part electronic_mail_template module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.modules.electronic_mail_template.tools import recipients_from_fields

__all__ = ['ElectronicMail']


class ElectronicMail(metaclass=PoolMeta):
    __name__ = 'electronic.mail'
    template = fields.Many2One('electronic.mail.template', 'Template')

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
    def send_mail(cls, mails):
        pool = Pool()
        Configuration = pool.get('electronic.mail.configuration')
        ElectronicMail = pool.get('electronic.mail')
        SMTP = pool.get('smtp.server')

        config = Configuration(1)

        draft_mailbox = config.draft
        smtp_servers = SMTP.search([
                ('state', '=', 'done'),
                ('default', '=', True),
                ], limit=1)
        if smtp_servers:
            smtp_server, = smtp_servers
        else:
            raise UserError(gettext(
                'electronic_mail_template.smtp_server_default'))

        cls.lock(mails)

        to_flag_send = []
        to_draft = []
        for mail in mails:
            recipients = recipients_from_fields(mail)

            mail_smtp_server = mail.template.server or smtp_server if mail.template else smtp_server
            mail_draft_mailbox = mail.template.draft_mailbox or draft_mailbox if mail.template else draft_mailbox

            # Validate recipients to send or move email to draft mailbox
            if not ElectronicMail.validate_emails(recipients):
                to_draft.extend(([mail], {'mailbox': mail_draft_mailbox}))
                continue

            mail_str = ElectronicMail._get_mail(mail)
            mail_smtp_server.send_mail(mail.from_, recipients, mail_str)
            if not mail.flag_send:
                to_flag_send.append(mail)

        if to_flag_send:
            ElectronicMail.write(to_flag_send, {'flag_send': True})

        if to_draft:
            ElectronicMail.write(*to_draft)
