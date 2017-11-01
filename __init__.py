# This file is part electronic_mail_template module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from .template import *
from .electronic_mail import *
from .trigger import *
from .report import *
from .user import *


def register():
    Pool.register(
        ElectronicMail,
        ActionReport,
        Template,
        TemplateReport,
        Trigger,
        User,
        module='electronic_mail_template', type_='model')
