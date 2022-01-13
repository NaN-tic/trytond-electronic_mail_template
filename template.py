# This file is part electronic_mail_template module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
"Email Template"


import logging
import mimetypes
from email import encoders, charset
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.utils import formatdate, make_msgid
from genshi.template import TextTemplate
try:
    from jinja2 import Template as Jinja2Template
    jinja2_loaded = True
except ImportError:
    jinja2_loaded = False
    logging.getLogger('electronic_mail_template').error(
        'Unable to import jinja2. Install jinja2 package.')

from trytond.model import ModelView, ModelSQL, fields
from trytond.pyson import Eval
from trytond.pool import Pool
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.transaction import Transaction
from trytond.modules.electronic_mail_template.tools import unaccent


__all__ = ['Template', 'TemplateReport']


class Template(ModelSQL, ModelView):
    'Email Template'
    __name__ = 'electronic.mail.template'

    from_ = fields.Char('From')
    sender = fields.Char('Sender')
    to = fields.Char('To')
    cc = fields.Char('CC')
    bcc = fields.Char('BCC')
    subject = fields.Char('Subject', translate=True)
    smtp_server = fields.Many2One('smtp.server', 'SMTP Server',
        domain=[('state', '=', 'done')], required=True)
    name = fields.Char('Name', required=True, translate=True)
    model = fields.Many2One('ir.model', 'Model', required=True)
    mailbox = fields.Many2One('electronic.mail.mailbox', 'Mailbox',
        required=True)
    draft_mailbox = fields.Many2One('electronic.mail.mailbox', 'Draft Mailbox',
        required=True)
    language = fields.Char('Language', help=('Expression to find the ISO '
        'langauge code'))
    plain = fields.Text('Plain Text Body', translate=True)
    html = fields.Text('HTML Body', translate=True)
    reports = fields.Many2Many('electronic.mail.template.ir.action.report',
        'template', 'report', 'Reports')
    engine = fields.Selection('get_engines', 'Engine', required=True)
    triggers = fields.One2Many('ir.trigger', 'email_template', 'Triggers',
        context={
            'model': Eval('model'),
            'email_template': True,
            })
    signature = fields.Boolean('Use Signature',
        help='The signature from the User details will be appened to the '
        'mail.')
    message_id = fields.Char('Message-ID', help='Unique Message Identifier')
    in_reply_to = fields.Char('In Repply To')
    attachments = fields.One2Many('ir.attachment', 'resource', "Attachments")

    @staticmethod
    def default_engine():
        '''Default Engine'''
        return 'genshi'

    @classmethod
    def get_engines(cls):
        '''Returns the engines as list of tuple

        :return: List of tuples
        '''
        engines = [
            ('python', 'Python'),
            ('genshi', 'Genshi'),
            ]
        if jinja2_loaded:
            engines.append(('jinja2', 'Jinja2'))
        return engines

    @classmethod
    def check_xml_record(cls, records, values):
        '''It should be possible to overwrite templates'''
        return True

    def eval(self, expression, record):
        '''Evaluates the given :attr:expression

        :param expression: Expression to evaluate
        :param record: The browse record of the record
        '''
        engine_method = getattr(self, '_engine_' + self.engine)
        return engine_method(expression, record)

    @staticmethod
    def template_context(record):
        """Generate the tempalte context

        This is mainly to assist in the inheritance pattern
        """
        User = Pool().get('res.user')
        user = None
        if Transaction().user:
            user = User(Transaction().user)
        return {
            'record': record,
            'user': user,
            }

    @classmethod
    def _engine_python(cls, expression, record):
        '''Evaluate the pythonic expression and return its value
        '''
        if expression is None:
            return ''

        assert record is not None, 'Record is undefined'
        template_context = cls.template_context(record)
        return eval(expression, template_context)

    @classmethod
    def _engine_genshi(cls, expression, record):
        '''
        :param expression: Expression to evaluate
        :param record: Browse record
        '''
        if not expression:
            return ''

        template = TextTemplate(expression)
        template_context = cls.template_context(record)

        try:
            return template.generate(**template_context).render(
                encoding=None)
        except Exception as message:
            raise UserError(gettext(
                'electronic_mail_template.generate_template_exception',
                error=repr(message)))

    @classmethod
    def _engine_jinja2(cls, expression, record):
        '''
        :param expression: Expression to evaluate
        :param record: Browse record
        '''
        if not jinja2_loaded or not expression:
            return ''

        template = Jinja2Template(expression)
        template_context = cls.template_context(record)
        return template.render(template_context)

    @classmethod
    def render(cls, template, record, values):
        '''Renders the template and returns as email object
        :param template: Browse Record of the template
        :param record: Browse Record of the record on which the template
            is to generate the data on
        :return: 'email.message.Message' instance
        '''
        ElectronicMail = Pool().get('electronic.mail')
        message = MIMEMultipart()
        messageid = template.eval(values['message_id'], record)
        message['Message-Id'] = messageid or make_msgid()
        message['Date'] = formatdate(localtime=1)
        if values.get('in_reply_to'):
            message['In-Reply-To'] = template.eval(values['in_reply_to'],
                record)
        message['From'] = ElectronicMail.validate_emails(
            template.eval(values['from_'], record))
        if values.get('sender'):
            message['Sender'] = ElectronicMail.validate_emails(
                template.eval(values['sender'], record))
        message['To'] = ElectronicMail.validate_emails(
            template.eval(values['to'], record))
        if values.get('cc'):
            message['Cc'] = ElectronicMail.validate_emails(
                template.eval(values['cc'], record))
        if values.get('bcc'):
            message['Bcc'] = ElectronicMail.validate_emails(
                template.eval(values['bcc'], record))

        message['Subject'] = Header(template.eval(values['subject'],
                record), 'utf-8')

        # HTML & Text Alternate parts
        plain = template.eval(values['plain'], record)
        html = template.eval(values['html'], record)
        header = """
            <html>
            <head><head>
            <body>
            """
        footer = """
            </body>
            </html>
            """
        if html:
            html = "%s%s" % (header, html)
        if template.signature:
            User = Pool().get('res.user')
            user = User(Transaction().user)
            if html and user.signature_html:
                signature = user.signature_html
                html = '%s<br>--<br>%s' % (html, signature)
            if plain and user.signature:
                signature = user.signature
                plain = '%s\n--\n%s' % (plain, signature)
                if html and not user.signature_html:
                    html = '%s<br>--<br>%s' % (html,
                        signature.replace('\n', '<br>'))
        if html:
            html = "%s%s" % (html, footer)
        body = None
        if html and plain:
            body = MIMEMultipart('alternative')
        charset.add_charset('utf-8', charset.QP, charset.QP)
        if plain:
            if body:
                body.attach(MIMEText(plain, 'plain', _charset='utf-8'))
            else:
                message.attach(MIMEText(plain, 'plain', _charset='utf-8'))
        if html:
            if body:
                body.attach(MIMEText(html, 'html', _charset='utf-8'))
            else:
                message.attach(MIMEText(html, 'html', _charset='utf-8'))
        if body:
            message.attach(body)

        # Attach reports
        if template.reports:
            reports = cls.render_reports(template, record)
            for report in reports:
                ext, data, filename, file_name = report[0:5]
                if file_name:
                    filename = template.eval(file_name, record)
                filename = unaccent(filename)
                filename = ext and '%s.%s' % (filename, ext) or filename
                content_type, _ = mimetypes.guess_type(filename)
                maintype, subtype = (
                    content_type or 'application/octet-stream'
                    ).split('/', 1)

                attachment = MIMEBase(maintype, subtype)
                attachment.set_payload(data)
                encoders.encode_base64(attachment)
            User = Pool().get('res.user')
            user = User(Transaction().user)
            if html and user.signature_html:
                attachment.add_header(
                    'Content-Disposition', 'attachment', filename=filename)
                message.attach(attachment)

        # Attach attachments
        attachments = []
        if 'attachments' in values:
            attachments = values.get('attachments')
        else:
            attachments = template.attachments
        if attachments:
            for attach in attachments:
                # only support attach data; not links
                if attach.type != 'data':
                    continue
                filename = unaccent(attach.name)
                content_type, _ = mimetypes.guess_type(filename)
                maintype, subtype = (
                    content_type or 'application/octet-stream'
                    ).split('/', 1)

                if attach.email_template_cid and maintype == 'image':
                    attachment = MIMEImage(attach.data, subtype)
                    attachment.add_header(
                        'Content-ID', '<%s>' % filename.replace('.%s' % subtype, ''))
                else:
                    attachment = MIMEBase(maintype, subtype)
                    attachment.set_payload(attach.data)
                    encoders.encode_base64(attachment)
                    attachment.add_header(
                        'Content-Disposition', 'attachment', filename=filename)
                message.attach(attachment)

        # attachment user signature
        if template.signature and html and user.signature_html:
            attachments = [a for a in user.attachments if a.email_template_cid]
            for attach in attachments:
                # only support attach data; not links
                if attach.type != 'data':
                    continue
                filename = unaccent(attach.name)
                content_type, _ = mimetypes.guess_type(filename)
                maintype, subtype = (
                    content_type or 'application/octet-stream'
                    ).split('/', 1)

                if maintype == 'image':
                    attachment = MIMEImage(attach.data, subtype)
                    attachment.add_header(
                        'Content-ID', '<%s>' % filename.replace('.%s' % subtype, ''))
                    message.attach(attachment)

        # attach extra files
        if values.get('attachment_files'):
            for attach in values.get('attachment_files'):
                filename = unaccent(attach.name)
                content_type, _ = mimetypes.guess_type(filename)
                maintype, subtype = (
                    content_type or 'application/octet-stream'
                    ).split('/', 1)
                attachment = MIMEBase(maintype, subtype)
                attachment.set_payload(attach.data)
                encoders.encode_base64(attachment)
                attachment.add_header(
                    'Content-Disposition', 'attachment', filename=filename)
                message.attach(attachment)

        return message

    @classmethod
    def render_reports(cls, template, record):
        '''Renders the reports and returns as a list of tuple

        :param template: Browse Record of the template
        :param record: Browse Record of the record on which the template
            is to generate the data on
        :return: List of tuples with:
            report_type
            data
            the report name
            the report file name (optional)
        '''
        pool = Pool()
        ActionReport = pool.get('ir.action.report')

        if template.language:
            language = template.eval(template.language, record)
        else:
            language = False

        reports = []
        for report_action in template.reports:
            if language:
                with Transaction().set_context(language=language):
                    report_action = ActionReport(report_action.id)
            report = Pool().get(report_action.report_name, type='report')
            report_execute = report.execute([record.id], {'id': record.id})
            if report_execute:
                reports.append([report_execute, report_action.file_name])

        # The boolean for direct print in the tuple is useless for emails
        return [(r[0][0], r[0][1], r[0][3], r[1]) for r in reports]

    @classmethod
    def render_and_send(cls, template_id, records):
        """
        Render the template and send
        :param template_id: ID template
        :param records: List Object of the records
        """
        pool = Pool()
        Configuration = pool.get('electronic.mail.configuration')
        ElectronicEmail = pool.get('electronic.mail')
        Template = pool.get('electronic.mail.template')

        template = cls(template_id)
        config = Configuration(1)

        for record in records:
            # load data in language when send a record
            if template.language:
                language = template.eval(template.language, record)
                with Transaction().set_context(language=language):
                    template = Template(template.id)

            values = {'template': template}
            tmpl_fields = ('from_', 'sender', 'to', 'cc', 'bcc', 'subject',
                'message_id', 'in_reply_to', 'plain', 'html')
            for field_name in tmpl_fields:
                values[field_name] = getattr(template, field_name)
            mail_message = cls.render(template, record, values)
            electronic_mail = ElectronicEmail.create_from_mail(
                mail_message, template.mailbox.id, record)
            if not electronic_mail:
                continue
            electronic_mail.template = template
            electronic_mail.save()

            with Transaction().set_context(
                    queue_name='electronic_mail',
                    queue_scheduled_at=config.send_email_after):
                ElectronicEmail.__queue__.send_mail([electronic_mail])
        return True

    @classmethod
    def mail_from_trigger(cls, records, trigger_id):
        """
        To be used with ir.trigger to send mails automatically

        The process involves identifying the tempalte which needs
        to be pulled when the trigger is.

        :param records: Object of the records
        :param trigger_id: ID of the trigger
        """
        Trigger = Pool().get('ir.trigger')
        trigger = Trigger(trigger_id)
        return cls.render_and_send(trigger.email_template.id, records)

    def get_attachments(self, records):
        record_ids = [r.id for r in records]
        attachments = []
        for report in self.reports:
            report = Pool().get(report.report_name, type='report')
            ext, data, filename, file_name = report.execute(record_ids, {})

            if file_name:
                filename = self.eval(file_name, record_ids)
            filename = ext and '%s.%s' % (filename, ext) or filename
            content_type, _ = mimetypes.guess_type(filename)
            maintype, subtype = (
                content_type or 'application/octet-stream'
                ).split('/', 1)

            attachment = MIMEBase(maintype, subtype)
            attachment.set_payload(data)
            encoders.encode_base64(attachment)
            attachment.add_header(
                'Content-Disposition', 'attachment', filename=filename)
            attachments.append(attachment)
        return attachments


class TemplateReport(ModelSQL):
    'Template - Report Action'
    __name__ = 'electronic.mail.template.ir.action.report'

    template = fields.Many2One('electronic.mail.template', 'Template')
    report = fields.Many2One('ir.action.report', 'Report')
