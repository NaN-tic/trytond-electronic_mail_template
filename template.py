# This file is part electronic_mail_template module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import logging
import mimetypes
import tempfile
import markdown
from email import encoders, charset
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.utils import formatdate, make_msgid
from email import policy
from genshi.template import TextTemplate
from html2text import html2text
from markitdown import (FileConversionException, MarkItDown,
    UnsupportedFormatException)
from sql import Column

logger = logging.getLogger(__name__)

try:
    from jinja2 import Template as Jinja2Template
    jinja2_loaded = True
except ImportError:
    jinja2_loaded = False
    logger.error(
        'Unable to import jinja2. Install jinja2 package.')

from trytond.config import config
from trytond.model import ModelView, ModelSQL, fields
from trytond.pyson import Eval
from trytond.pool import Pool
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.transaction import Transaction
from trytond.modules.electronic_mail_template.tools import unaccent
from trytond.report import Report
from trytond.tools import cursor_dict

QUEUE_NAME = config.get('electronic_mail', 'queue_name', default='default')


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
    markdown = fields.Text('Markdown Body', translate=True)
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
    message_id = fields.Char('Message ID', help='Unique Message Identifier')
    in_reply_to = fields.Char('In Reply To')
    references = fields.Char('References')

    @staticmethod
    def default_engine():
        return 'jinja2' if jinja2_loaded else 'genshi'

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

    @classmethod
    def __register__(cls, module_name):
        table_handler = cls.__table_handler__(module_name)
        has_plain = table_handler.column_exist('plain')
        has_html = table_handler.column_exist('html')
        has_markdown = table_handler.column_exist('markdown')

        super().__register__(module_name)

        if not (has_plain or has_html) or has_markdown:
            return

        cursor = Transaction().connection.cursor()
        sql_table = cls.__table__()
        cls._migrate_content(cursor, sql_table, has_plain, has_html)

    @classmethod
    def _migrate_content(cls, cursor, sql_table, has_plain, has_html):
        # 1) Template body: plain/html -> markdown (HTML wins)
        markdown_col = Column(sql_table, 'markdown')
        columns = [sql_table.id, markdown_col]
        if has_html:
            columns.append(Column(sql_table, 'html'))
        if has_plain:
            columns.append(Column(sql_table, 'plain'))

        cursor.execute(*sql_table.select(*columns))
        rows = list(cursor_dict(cursor))
        for row in rows:
            if row.get('markdown'):
                continue
            source_html = (row.get('html') if has_html else None) or ''
            source_plain = (row.get('plain') if has_plain else None) or ''
            source_html = source_html.strip()
            if source_html:
                markdown_value = cls._html_to_markdown(source_html)
            else:
                markdown_value = source_plain
            if markdown_value:
                cursor.execute(*sql_table.update(
                        [markdown_col], [markdown_value],
                        where=sql_table.id == row['id']))

        # 2) Translations: plain/html -> markdown (HTML wins)
        Translation = Pool().get('ir.translation')
        translation = Translation.__table__()
        name_markdown = '%s,markdown' % cls.__name__
        name_html = '%s,html' % cls.__name__
        name_plain = '%s,plain' % cls.__name__

        cursor.execute(*translation.select(
                translation.id, translation.name, translation.lang,
                translation.res_id, translation.value, translation.src,
                where=(translation.type == 'model')
                & (translation.name.in_([name_html, name_plain]))))
        rows = list(cursor_dict(cursor))
        grouped = {}
        for row in rows:
            key = (row['res_id'], row['lang'])
            if key not in grouped or row['name'] == name_html:
                grouped[key] = row
        keep_ids = {row['id'] for row in grouped.values()}
        delete_ids = [row['id'] for row in rows if row['id'] not in keep_ids]
        if delete_ids:
            cursor.execute(*translation.delete(
                    where=translation.id.in_(delete_ids)))
        for row in grouped.values():
            if row['name'] == name_html:
                convert = cls._html_to_markdown
            else:
                convert = lambda value: value or ''
            new_src = convert(row['src']) if row['src'] else row['src']
            new_value = convert(row['value']) if row['value'] else row['value']
            cursor.execute(*translation.update(
                    [translation.name, translation.src, translation.value],
                    [name_markdown, new_src, new_value],
                    where=translation.id == row['id']))

        # 3) User signatures: signature_html -> signature (markdown)
        User = Pool().get('res.user')
        table_handler = User.__table_handler__()
        if not (table_handler.column_exist('signature')
                and table_handler.column_exist('signature_html')):
            return
        user_table = User.__table__()
        cursor.execute(*user_table.select(
                user_table.id, user_table.signature,
                user_table.signature_html))
        rows = list(cursor_dict(cursor))
        for row in rows:
            signature_html = (row.get('signature_html') or '').strip()
            if not signature_html:
                continue
            current_signature = (row.get('signature') or '').strip()
            signature_markdown = cls._html_to_markdown(signature_html)
            if current_signature and current_signature not in {
                    signature_html, signature_markdown}:
                continue
            if current_signature == signature_html:
                continue
            cursor.execute(*user_table.update(
                    [user_table.signature], [signature_html],
                    where=user_table.id == row['id']))

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
            'format_date': Report.format_date,
            'format_datetime': Report.format_datetime,
            'format_timedelta': Report.format_timedelta,
            'format_currency': Report.format_currency,
            'format_number': Report.format_number,
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

    @staticmethod
    def _get_policy():
        # See https://docs.python.org/3/library/email.policy.html
        return policy.compat32.clone(linesep='\r\n', raise_on_defect=True)

    @staticmethod
    def _html_to_markdown(value):
        if not value:
            return ''
        converter = MarkItDown()
        try:
            with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.html', encoding='utf-8') as f:
                f.write(value)
                f.flush()
                result = converter.convert(f.name)
                return result.text_content.replace('\x00', '').strip()
        except (FileConversionException, UnsupportedFormatException) as exc:
            logger.error(
                'MarkItDown conversion error while processing HTML content: %s',
                exc, exc_info=True)
        return ''

    @classmethod
    def _markdown_to_html(cls, value):
        if not value:
            return ''
        return markdown.markdown(
            value, extensions=['fenced_code', 'tables', 'sane_lists'])

    @classmethod
    def _markdown_to_plain(cls, value):
        if not value:
            return ''
        html = cls._markdown_to_html(value)
        if not html:
            return ''
        return html2text(html, bodywidth=0).strip()

    @classmethod
    def render(cls, template, record, values, render_report=True,
            extra_attachments=None):
        '''Renders the template and returns as email object
        :param template: Browse Record of the template
        :param record: Browse Record of the record on which the template
            is to generate the data on
        :param extra_attachments: A dictionary with 2 keys 'filename' and
            'data' to attach external documents.
        :return: 'email.message.Message' instance
        '''
        # It is hard to write correct e-mails even using the email module.
        # It is a good practice to check the generated e-mail using
        # https://www.mimevalidator.net/index.html
        # any time we make a change here.
        # Remember to use unix2dos before uploading for check as smtplib does
        # that conversion automatically.
        ElectronicMail = Pool().get('electronic.mail')

        message = MIMEMultipart(policy=cls._get_policy())
        messageid = template.eval(values['message_id'], record)
        message['Message-Id'] = messageid or make_msgid()
        message['Date'] = formatdate(localtime=1)
        if values.get('in_reply_to'):
            message['In-Reply-To'] = template.eval(values['in_reply_to'],
                record)
        if values.get('references'):
            message['References'] = template.eval(values['references'],
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
                record), 'utf-8').encode()

        # HTML & Text Alternate parts
        markdown_text = template.eval(values['markdown'], record)
        header = """
            <html>
            <head><head>
            <body>
            """
        footer = """
            </body>
            </html>
            """
        if template.signature:
            User = Pool().get('res.user')
            user = User(Transaction().user)
            signature_markdown = (user.signature or '').strip()
            if ('<' in signature_markdown and '>' in signature_markdown):
                converted_signature = cls._html_to_markdown(signature_markdown)
                if converted_signature:
                    signature_markdown = converted_signature
            if signature_markdown:
                if markdown_text:
                    markdown_text = '%s\n\n--\n%s' % (
                        markdown_text, signature_markdown)
                else:
                    markdown_text = '--\n%s' % signature_markdown

        html_body = cls._markdown_to_html(markdown_text)
        plain = cls._markdown_to_plain(markdown_text)
        html = ''
        if html_body:
            html = "%s%s%s" % (header, html_body, footer)
        body = None
        if html and plain:
            body = MIMEMultipart('alternative', policy=cls._get_policy())
        charset.add_charset('utf-8', charset.QP, charset.QP)
        if plain:
            if body:
                body.attach(MIMEText(plain, 'plain', _charset='utf-8',
                        policy=cls._get_policy()))
            else:
                message.attach(MIMEText(plain, 'plain', _charset='utf-8',
                        policy=cls._get_policy()))
        if html:
            if body:
                body.attach(MIMEText(html, 'html', _charset='utf-8',
                        policy=cls._get_policy()))
            else:
                message.attach(MIMEText(html, 'html', _charset='utf-8',
                        policy=cls._get_policy()))
        if body:
            message.attach(body)

        # Attach reports
        if render_report and template.reports:
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

                attachment = MIMEBase(maintype, subtype,
                    policy=cls._get_policy())
                attachment.set_payload(data)
                encoders.encode_base64(attachment)
                attachment.add_header(
                    'Content-Disposition', 'attachment', filename=filename)
                message.attach(attachment)
        if extra_attachments:
            for attach in extra_attachments:
                filename = attach['name']
                content_type, _ = mimetypes.guess_type(filename)
                maintype, subtype = (
                    content_type or 'application/octet-stream'
                    ).split('/', 1)

                attachment = MIMEBase(maintype, subtype,
                    policy=cls._get_policy())
                attachment.set_payload(attach['data'])
                encoders.encode_base64(attachment)
                attachment.add_header(
                    'Content-Disposition', 'attachment', filename=filename)
                message.attach(attachment)

        return message

    @classmethod
    def render_reports(cls, template, record):
        '''Renders the reports and returns as a list of tuple

        :param template: Browse Record of the template
        :param record: List Browse Record or Browse Record of the record
            on which the template is to generate the data on
        :return: List of tuples with:
            report_type
            data
            the report name
            the report file name (optional)
        '''
        pool = Pool()
        ActionReport = pool.get('ir.action.report')
        Lang = pool.get('ir.lang')

        if isinstance(record, list):
            ids = [r.id for r in record]
            record = record[0]
        else:
            ids = [record.id]

        lang = Transaction().language
        if template.language:
            lang = template.eval(template.language, record) or lang

        html_report_language = None
        if lang:
            langs = Lang.search([('code', '=', lang)], limit=1)
            html_report_language = langs[0] if langs else None

        reports = []
        for report_action in template.reports:
            context = {'language': lang}
            if html_report_language:
                context.update({
                    'html_report_language': html_report_language,
                    'report_lang': html_report_language.code,
                    })
            with Transaction().set_context(**context):
                report_action = ActionReport(report_action.id)
                report = Pool().get(report_action.report_name, type='report')
                report_execute = report.execute(ids, {
                    'model': report_action.model,
                    'id': ids[0],
                    'ids': ids,
                    'action_id': report_action.id,
                    })
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
            else:
                language = Transaction().context.get('language')

            with Transaction().set_context(language=language):
                template = Template(template.id)

            values = {'template': template}
            tmpl_fields = ('from_', 'sender', 'to', 'cc', 'bcc', 'subject',
                'message_id', 'in_reply_to', 'references', 'markdown')
            for field_name in tmpl_fields:
                values[field_name] = getattr(template, field_name)

            with Transaction().set_context(language=language):
                mail_message = cls.render(template, record, values)
            electronic_mail = ElectronicEmail.create_from_mail(
                mail_message, template.mailbox.id, record)
            if not electronic_mail:
                continue
            electronic_mail.template = template
            electronic_mail.save()

            with Transaction().set_context(
                    queue_name=QUEUE_NAME,
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

            attachment = MIMEBase(maintype, subtype, policy=self._get_policy())
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
