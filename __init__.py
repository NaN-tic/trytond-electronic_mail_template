# This file is part electronic_mail_template module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import template
from . import electronic_mail
from . import trigger
from . import report


def register():
    Pool.register(
        electronic_mail.ElectronicMail,
        report.ActionReport,
        template.Template,
        template.TemplateReport,
        trigger.Trigger,
        module='electronic_mail_template', type_='model')
