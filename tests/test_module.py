
# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from textwrap import dedent

from sql import Column
from trytond.modules.company.tests import CompanyTestMixin
from trytond.pool import Pool
from trytond.tests.test_tryton import ModuleTestCase, with_transaction
from trytond.transaction import Transaction


class ElectronicMailTemplateTestCase(CompanyTestMixin, ModuleTestCase):
    'Test ElectronicMailTemplate module'
    module = 'electronic_mail_template'

    @with_transaction()
    def test_markdown_to_html_extensions(self):
        Template = Pool().get('electronic.mail.template')
        value = dedent("""\
            ```python
            print(\"hello\")
            ```

            | A | B |
            | - | - |
            | 1 | 2 |

            4. four
            5. five

            * three
            * four
            """)

        html = Template._markdown_to_html(value)

        self.assertIn(
            '<pre><code class=\"language-python\">print(&quot;hello&quot;)',
            html)
        self.assertIn('<table>', html)
        self.assertIn('<td>1</td>', html)
        self.assertIn('<ol start=\"4\">', html)
        self.assertIn('<ul>', html)

    @with_transaction()
    def test_markdown_to_plain_extensions(self):
        Template = Pool().get('electronic.mail.template')
        value = dedent("""\
            ```python
            print(\"hello\")
            ```

            | A | B |
            | - | - |
            | 1 | 2 |

            4. four
            5. five

            * three
            * four
            """)

        plain = Template._markdown_to_plain(value)

        self.assertIn('print("hello")', plain)
        self.assertIn('A | B', plain)
        self.assertIn('1 | 2', plain)
        self.assertIn('4. four', plain)
        self.assertIn('* three', plain)

    @with_transaction()
    def test_html_to_markdown_unescapes_template_expressions(self):
        Template = Pool().get('electronic.mail.template')
        value = dedent("""\
            <p>Dear customer,</p>
            <p>Invoice {{ record.number }} dated on
            {{ record.invoice_date and
            record.invoice_date.strftime('%d/%m/%Y') }} is attached below.</p>
            <p>Reference: ${record.invoice_date}</p>
            """)

        markdown = Template._html_to_markdown(value)

        self.assertIn('{{ record.number }}', markdown)
        self.assertIn('{{ record.invoice_date and', markdown)
        self.assertIn("record.invoice_date.strftime('%d/%m/%Y') }}", markdown)
        self.assertIn('${record.invoice_date}', markdown)
        self.assertNotIn(r'\_', markdown)

    @with_transaction()
    def test_unescape_template_expressions_keeps_normal_markdown_escaping(self):
        Template = Pool().get('electronic.mail.template')
        value = (
            r'Use customer_name for plain text and '
            r'{{ record.invoice\_date }} in templates')

        unescaped = Template._unescape_template_expressions(value)

        self.assertIn('customer_name', unescaped)
        self.assertIn('{{ record.invoice_date }}', unescaped)
        self.assertNotIn(r'{{ record.invoice\_date }}', unescaped)

    @with_transaction()
    def test_register_migrates_translated_html_when_source_is_empty(self):
        pool = Pool()
        Lang = pool.get('ir.lang')
        Mailbox = pool.get('electronic.mail.mailbox')
        Model = pool.get('ir.model')
        SMTPServer = pool.get('smtp.server')
        Template = pool.get('electronic.mail.template')
        Translation = pool.get('ir.translation')

        lang, = Lang.search([
                ('code', '!=', 'en'),
                ], limit=1)
        lang.translatable = True
        lang.save()

        mailbox, draft_mailbox = Mailbox.create([
                {'name': 'Inbox'},
                {'name': 'Draft'},
                ])
        model, = Model.search([
                ('name', '=', 'res.user'),
                ], limit=1)
        smtp_server, = SMTPServer.create([{
                    'name': 'SMTP',
                    'smtp_server': 'smtp.example.com',
                    'smtp_email': 'support@example.com',
                    }])
        SMTPServer.done([smtp_server])
        template, = Template.create([{
                    'name': 'Template',
                    'model': model.id,
                    'mailbox': mailbox.id,
                    'draft_mailbox': draft_mailbox.id,
                    'smtp_server': smtp_server.id,
                    }])

        table_handler = Template.__table_handler__('electronic_mail_template')
        table_handler.add_column('plain', 'TEXT')
        table_handler.add_column('html', 'TEXT')

        sql_table = Template.__table__()
        plain = Column(sql_table, 'plain')
        html = Column(sql_table, 'html')
        cursor = Transaction().connection.cursor()
        cursor.execute(*sql_table.update(
                [plain, html], ['', ''],
                where=sql_table.id == template.id))

        plain_value = 'Translated plain body'
        html_value = '<h1>Translated html body</h1><p>Use <strong>Markdown</strong></p>'
        expected_markdown = Template._html_to_markdown(html_value)

        Translation.create([{
                    'name': 'electronic.mail.template,plain',
                    'lang': lang.code,
                    'type': 'model',
                    'res_id': template.id,
                    'src': '',
                    'value': plain_value,
                    'module': 'electronic_mail_template',
                    'fuzzy': False,
                    }, {
                    'name': 'electronic.mail.template,html',
                    'lang': lang.code,
                    'type': 'model',
                    'res_id': template.id,
                    'src': '',
                    'value': html_value,
                    'module': 'electronic_mail_template',
                    'fuzzy': False,
                    }])

        table_handler.drop_column('markdown')

        Template.__register__('electronic_mail_template')

        with Transaction().set_context(language=lang.code):
            translated_template = Template(template.id)
            self.assertEqual(translated_template.markdown, expected_markdown)

        translations = Translation.search([
                ('lang', '=', lang.code),
                ('type', '=', 'model'),
                ('res_id', '=', template.id),
                ('name', 'in', [
                        'electronic.mail.template,plain',
                        'electronic.mail.template,html',
                        'electronic.mail.template,markdown',
                        ]),
                ])
        self.assertEqual(len(translations), 1)
        self.assertEqual(
            translations[0].name, 'electronic.mail.template,markdown')
        self.assertEqual(translations[0].src, '')
        self.assertEqual(translations[0].value, expected_markdown)


    @with_transaction()
    def test_register_migrates_user_signature_to_html_format(self):
        pool = Pool()
        User = pool.get('res.user')
        Template = pool.get('electronic.mail.template')

        user = User(Transaction().user)
        html_signature = '<p>Best <strong>Regards</strong></p>'
        user.signature_html = html_signature
        user.signature = Template._html_to_markdown(html_signature)
        user.save()

        table_handler = Template.__table_handler__('electronic_mail_template')
        table_handler.add_column('plain', 'TEXT')
        table_handler.drop_column('markdown')

        Template.__register__('electronic_mail_template')

        migrated_user = User(user.id)
        self.assertEqual(migrated_user.signature, html_signature)


del ModuleTestCase
