# This file is part electronic_mail_template module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import logging
from trytond.config import config
from trytond.model import ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.transaction import Transaction
from trytond.modules.electronic_mail_template.tools import (
    recipients_from_fields)

QUEUE_NAME = config.get('electronic_mail', 'queue_name', default='default')
logger = logging.getLogger(__name__)


class ElectronicMail(metaclass=PoolMeta):
    __name__ = 'electronic.mail'
    template = fields.Many2One('electronic.mail.template', 'Template')

    @classmethod
    def __setup__(cls):
        super(ElectronicMail, cls).__setup__()
        cls._buttons.update({
                'send_mail': {
                    'invisible': (
                        (
                        Bool(Eval('body_plain') == '') &
                        Bool(Eval('body_html') == '')) |
                        Eval('flag_send')
                        ),
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
        SMTP = pool.get('smtp.server')

        config = Configuration(1)

        smtp_servers = SMTP.search([
                ('state', '=', 'done'),
                ('default', '=', True),
                ], limit=1)
        if not smtp_servers:
            raise UserError(gettext(
                'electronic_mail_template.msg_smtp_server_default'))

        to_send = []
        for mail in mails:
            cls.lock([mail])
            # Given that the lock (which is a SELECT FOR UPDATE NOWAIT) guarantees that no concurrent
            # process is updating it, we must read now the flag_send value, and not rely on the value that
            # may be in the cache of the object before the lock, which could have an older value.
            mail = cls(mail.id)
            if mail.flag_send:
                continue
            if not mail.mail_file:
                raise UserError(gettext(
                        'electronic_mail_template.msg_smtp_server_default',
                        email=mail.rec_name))

            recipients = recipients_from_fields(mail)
            # validate_emails raise UserError or return ''
            if cls.validate_emails(recipients):
                to_send.append(mail)

        for mail in to_send:
            with Transaction().set_context(
                    queue_name=QUEUE_NAME,
                    queue_scheduled_at=config.send_email_after):
                cls.__queue__._send_mail([mail])

    @classmethod
    def _send_mail(cls, mails):
        pool = Pool()
        Configuration = pool.get('electronic.mail.configuration')
        SMTP = pool.get('smtp.server')

        config = Configuration(1)
        draft_mailbox = config.draft

        smtp_servers = SMTP.search([
                ('state', '=', 'done'),
                ('default', '=', True),
                ], limit=1)
        smtp_server = smtp_servers[0] if smtp_servers else None

        to_flag_send = []
        to_draft = []
        for mail in mails:
            if not mail.mail_file:
                continue

            recipients = recipients_from_fields(mail)

            mail_smtp_server = (mail.template.smtp_server if mail.template
                else smtp_server)
            mail_draft_mailbox = (mail.template.draft_mailbox if mail.template
                else draft_mailbox)

            if not mail_smtp_server or not mail_draft_mailbox:
                if not mail_smtp_server:
                    logger.warning(
                        'Missing default SMTP server mail ID: %s' % mail.id)
                if not mail_smtp_server:
                    logger.warning(
                        'Missing default Mailbox mail ID: %s' % mail.id)
                continue

            # Validate recipients to send or move email to draft mailbox
            if not cls.validate_emails(recipients, raise_exception=False):
                to_draft.extend(([mail], {'mailbox': mail_draft_mailbox}))
                continue

            mail_smtp_server.send_mail(mail.from_, recipients, mail.mail_file)
            if not mail.flag_send:
                to_flag_send.append(mail)

        if to_flag_send:
            cls.write(to_flag_send, {'flag_send': True})

        if to_draft:
            cls.write(*to_draft)
